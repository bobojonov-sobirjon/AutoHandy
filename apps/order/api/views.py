from rest_framework import status, filters
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.parsers import JSONParser, MultiPartParser, FormParser
from rest_framework.pagination import PageNumberPagination
from django_filters.rest_framework import DjangoFilterBackend
from django.db import transaction
from django.db.models import Prefetch, Q
from django.shortcuts import get_object_or_404
from django.contrib.auth import get_user_model
from django.utils import timezone
from django.conf import settings
import json
import logging
import secrets

from apps.categories.query import order_by_order_category_smart_q
from apps.order.services.completion_pin import clear_completion_pin, issue_completion_pin
from apps.order.services.offer_expiry import expire_stale_master_offers
from apps.order.services.master_offer import activate_pending_master_offer
from apps.order.services.status_workflow import (
    auto_eta_from_order_master,
    client_cancellation_snapshot,
    resolve_master_coordinates_for_start_job,
    resolve_on_the_way_eta,
    validate_master_cancel,
)
from apps.order.services.celery_schedule import schedule_client_penalty_free_unlock
from apps.order.services.master_inbox_sync import (
    pending_assigned_standard_order_ids_for_master,
    pending_custom_request_order_ids_for_master,
)
from apps.order.services.sos_rotation import (
    master_eligible_for_pending_sos_offer,
    master_in_sos_broadcast_queue,
    order_ids_sos_currently_offered_to_master,
    sos_broadcast_decline,
)
from apps.master.services.geo import MILES_TO_KM, haversine_distance_m, haversine_distance_km

from drf_spectacular.utils import extend_schema, OpenApiParameter, OpenApiExample
from drf_spectacular.types import OpenApiTypes

from apps.order.models import (
    CustomRequestOffer,
    MasterOrderCancellation,
    Order,
    OrderStatus,
    OrderType,
    OrderWorkCompletionImage,
    Rating,
    OrderService,
    Review,
    ReviewTag,
)
from apps.order.api.payload import (
    attach_order_images_from_request,
    normalize_custom_request_create_data,
    normalize_order_create_request_data,
    normalize_review_create_request_data,
    _coerce_tag_string_list,
)
from apps.order.api.serializers import (
    OrderSerializer,
    OrderCreateSerializer,
    CustomRequestCreateSerializer,
    CustomRequestOfferCreateSerializer,
    CustomRequestOfferSerializer,
    CustomRequestOfferWithMasterSerializer,
    OrderMasterPreferredTimePatchSerializer,
    OrderUpdateSerializer,
    AddServicesToOrderSerializer,
    AddMasterToOrderSerializer,
    OrderServiceSerializer,
    ReviewSerializer,
    ReviewCreateSerializer,
    CancelOrderRequestSerializer,
)
from apps.order.services.order_pricing import estimate_cancellation_penalty_amount, order_payable_total_str
from apps.order.permissions import IsOrderOwnerOrMaster, IsOrderOwner, IsMaster
from apps.master.models import Master
from apps.master.api.serializers import MasterSerializer
from apps.master.api.views import MasterListView
from apps.accounts.models import UserBalance

User = get_user_model()

logger = logging.getLogger(__name__)

# Swagger: order endpoints grouped by role/flow (see SPECTACULAR_SETTINGS['TAGS'])
STAG_ORDER_DRIVER_CREATE = 'Order (Driver) — Create'
STAG_ORDER_DRIVER_SLOTS = 'Order (Driver) — Time slots'
STAG_ORDER_DRIVER_MY = 'Order (Driver) — My orders'
STAG_ORDER_DRIVER_REVIEWS = 'Order (Driver) — Reviews'
STAG_ORDER_DRIVER_LEGACY = 'Order (Driver) — Legacy'
STAG_ORDER_DETAILS = 'Order — Details (Driver & Master)'
STAG_ORDER_STATUS = 'Order — Status (Driver & Master)'
STAG_ORDER_MASTER_AVAILABLE = 'Order (Master) — Available & accept'
STAG_ORDER_MASTER_MY = 'Order (Master) — My orders'
STAG_ORDER_MASTER_COMPLETE = 'Order (Master) — Complete'

MASTER_ACTIVE_WORK_STATUSES = (
    OrderStatus.ACCEPTED,
    OrderStatus.ON_THE_WAY,
    OrderStatus.ARRIVED,
    OrderStatus.IN_PROGRESS,
)


def _custom_request_offers_list_access(request, order):
    """
    Who may GET offers for a custom-request order:
    - Order owner (driver): all offers.
    - Assigned master: all offers.
    - Any master who submitted an offer: only their own row(s) (no competitor prices).
    Returns (allowed: bool, restrict_to_master: Master | None).
    """
    if order.user_id == request.user.id:
        return True, None
    viewer_master = Master.objects.filter(user=request.user).first()
    if not viewer_master:
        return False, None
    if order.master_id == viewer_master.id:
        return True, None
    if CustomRequestOffer.objects.filter(order=order, master=viewer_master).exists():
        return True, viewer_master
    return False, None


def _normalize_order_type_query_param(raw: str | None) -> str | None:
    """Legacy clients may send ``order_type=scheduled``; stored value is ``standard``."""
    if not raw:
        return None
    v = raw.strip().lower()
    if v == 'scheduled':
        return OrderType.STANDARD
    return v


def _nearby_masters_debug_snapshot(
    *,
    user_lat: float,
    user_lng: float,
    radius_km: float,
    category_id_raw: str | None,
) -> dict:
    """
    Why /nearby-masters can return []: counts after each constraint (coords, strict category, radius).
    """
    from apps.categories.models import Category
    from apps.categories.query import master_by_order_category_strict_q

    out: dict = {
        'search_point': {'lat': user_lat, 'lng': user_lng},
        'radius_km': radius_km,
        'category_query': category_id_raw,
        'masters_total': Master.objects.count(),
        'masters_with_coordinates': Master.objects.filter(
            latitude__isnull=False,
            longitude__isnull=False,
        ).count(),
    }
    qs = Master.objects.filter(latitude__isnull=False, longitude__isnull=False)
    if category_id_raw not in (None, ''):
        try:
            cid = int(category_id_raw)
            cat = Category.objects.filter(pk=cid).first()
            if not cat:
                out['category_filter'] = 'not_found'
            elif cat.type_category != Category.TypeCategory.BY_ORDER:
                out['category_filter'] = f'wrong_type:{cat.type_category}'
            else:
                qs = qs.filter(master_by_order_category_strict_q(cat)).distinct()
                out['category_filter'] = f'strict_by_order_id={cid}'
        except (ValueError, TypeError):
            out['category_filter'] = 'invalid_param'
    else:
        out['category_filter'] = 'none'

    out['masters_after_category_and_coords'] = qs.count()

    in_radius = 0
    for m in qs.iterator(chunk_size=200):
        mlat, mlon = m.get_work_location_for_distance()
        if mlat is None or mlon is None:
            continue
        if haversine_distance_km(user_lat, user_lng, mlat, mlon) <= radius_km:
            in_radius += 1
    out['masters_within_radius'] = in_radius
    return out


def _nearby_nearest_outside_radius(
    *,
    user_lat: float,
    user_lng: float,
    radius_km: float,
    category_id_raw: str | None,
    limit: int = 20,
) -> list[dict]:
    """Masters that pass category+coords but are farther than radius — sorted nearest first."""
    from apps.categories.models import Category
    from apps.categories.query import master_by_order_category_strict_q

    qs = Master.objects.filter(latitude__isnull=False, longitude__isnull=False)
    if category_id_raw not in (None, ''):
        try:
            cid = int(category_id_raw)
            cat = Category.objects.filter(pk=cid).first()
            if cat and cat.type_category == Category.TypeCategory.BY_ORDER:
                qs = qs.filter(master_by_order_category_strict_q(cat)).distinct()
            else:
                qs = qs.none()
        except (ValueError, TypeError):
            qs = qs.none()

    rows: list[dict] = []
    for m in qs.iterator(chunk_size=200):
        mlat, mlon = m.get_work_location_for_distance()
        if mlat is None or mlon is None:
            continue
        d = haversine_distance_km(user_lat, user_lng, mlat, mlon)
        if d > radius_km:
            rows.append(
                {
                    'master_id': m.id,
                    'distance_km': round(d, 2),
                    'km_beyond_radius': round(d - radius_km, 2),
                }
            )
    rows.sort(key=lambda x: x['distance_km'])
    return rows[:limit]


def _nearby_strict_category_missing_coords_count(category_id_raw: str | None) -> int | None:
    """How many masters have the strict skill but no lat/lon."""
    from django.db.models import Q

    from apps.categories.models import Category
    from apps.categories.query import master_by_order_category_strict_q

    if category_id_raw in (None, ''):
        return None
    try:
        cat = Category.objects.get(pk=int(category_id_raw))
    except (Category.DoesNotExist, ValueError, TypeError):
        return None
    if cat.type_category != Category.TypeCategory.BY_ORDER:
        return None
    return (
        Master.objects.filter(master_by_order_category_strict_q(cat))
        .filter(Q(latitude__isnull=True) | Q(longitude__isnull=True))
        .distinct()
        .count()
    )


def _nearby_build_full_explain(
    *,
    user_lat: float,
    user_lng: float,
    radius_km: float,
    radius_miles: float,
    category_id_raw: str | None,
    coord_source: str,
) -> dict:
    snap = _nearby_masters_debug_snapshot(
        user_lat=user_lat,
        user_lng=user_lng,
        radius_km=radius_km,
        category_id_raw=category_id_raw,
    )
    snap['radius_miles'] = radius_miles
    snap['coord_source'] = coord_source
    snap['nearest_outside_radius'] = _nearby_nearest_outside_radius(
        user_lat=user_lat,
        user_lng=user_lng,
        radius_km=radius_km,
        category_id_raw=category_id_raw,
        limit=20,
    )
    snap['masters_skill_match_but_no_coordinates'] = _nearby_strict_category_missing_coords_count(
        category_id_raw
    )
    snap['hint'] = (
        'radius query is in miles; radius_km is the effective search radius. '
        'nearest_outside_radius: same filters (category if any) + coords, but distance_km > radius_km; '
        'km_beyond_radius = km past that circle. '
        'masters_skill_match_but_no_coordinates: have the skill but lat/lon empty.'
    )
    return snap


class NearbyMasterCandidatesView(MasterListView):
    """
    Masters near a GPS point — same logic as GET /api/master/masters/list/
    with lat/long + radius (**miles**); default 50 mi. Coordinates from query or user profile.
    """

    permission_classes = [IsAuthenticated]
    # Exact subcategory match on MasterServiceItems (no parent/sibling expansion).
    _nearby_category_strict = True

    @extend_schema(
        summary='Кандидаты-мастера рядом (выбор для заказа)',
        description="""
Тот же движок, что **`GET /api/master/masters/list/`** (Haversine, `distance` в ответе).

**Координаты точки поиска:**
- Если в query переданы `lat` и `long` (или `latitude` / `longitude`) — используются они.
- Иначе берутся **`request.user.latitude` и `request.user.longitude`** из профиля (если заданы).
- Если ни query, ни профиль не дают координаты — **400** с подсказкой.

**По умолчанию:** `radius=50` **миль** (в ответе `distance` по-прежнему в км).

**Опционально:** `category` (by_order; **строгое** совпадение навыка), `name`.

**Расписание (только ``Master busy slot`` с полем ``date``):**
- На выбранную `date` у мастера должен быть **хотя бы один** busy-slot с этой датой. Рабочий коридор = min–max времени по слотам этого дня (или строка с обедом — как в GET busy-slots). **Master schedule days** и **working_time** для этого фильтра не используются.
- Далее: **хотя бы один** свободный слот (`date` без `time`) или момент внутри свободного `[start, end)` (`date` + `time`).
- `time` без `date` → **400**.

**Пояснение в теле ответа (не ошибка):** `explain=1` или `debug=1` — вместо голого массива приходит объект:
`{ "masters": [...], "nearby_explain": { счётчики, nearest_outside_radius (ближайшие за пределами radius с distance_km и km_beyond_radius), ... } }`.

Без `explain` ответ по-прежнему **массив** мастеров (как раньше).

JWT обязателен.
        """,
        parameters=[
            OpenApiParameter(
                name='lat',
                type=OpenApiTypes.DOUBLE,
                location=OpenApiParameter.QUERY,
                required=False,
                description='Широта точки поиска (если не задана — из профиля пользователя)',
            ),
            OpenApiParameter(
                name='long',
                type=OpenApiTypes.DOUBLE,
                location=OpenApiParameter.QUERY,
                required=False,
                description='Долгота точки поиска (если не задана — из профиля пользователя)',
            ),
            OpenApiParameter(
                name='radius',
                type=OpenApiTypes.DOUBLE,
                location=OpenApiParameter.QUERY,
                required=False,
                description='Радиус поиска в милях (по умолчанию 50 mi); distance в списке мастеров — км',
            ),
            OpenApiParameter(
                name='category',
                type=OpenApiTypes.INT,
                location=OpenApiParameter.QUERY,
                required=False,
            ),
            OpenApiParameter(
                name='name',
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                required=False,
            ),
            OpenApiParameter(
                name='explain',
                type=OpenApiTypes.BOOL,
                location=OpenApiParameter.QUERY,
                required=False,
                description='1/true — тело: { masters, nearby_explain } (почему пусто, кто чуть дальше radius)',
            ),
            OpenApiParameter(
                name='debug',
                type=OpenApiTypes.BOOL,
                location=OpenApiParameter.QUERY,
                required=False,
                description='То же что explain=1 (алиас)',
            ),
            OpenApiParameter(
                name='date',
                type=OpenApiTypes.DATE,
                location=OpenApiParameter.QUERY,
                required=False,
                description='Фильтр по дню: мастер с ≥1 свободным слотом (логика busy-slots)',
            ),
            OpenApiParameter(
                name='time',
                type=OpenApiTypes.TIME,
                location=OpenApiParameter.QUERY,
                required=False,
                description='С date: мастер свободен в этот момент (интервал [start,end) из slots)',
            ),
        ],
        responses={200: MasterSerializer(many=True)},
        tags=[STAG_ORDER_DRIVER_CREATE],
    )
    def get(self, request):
        lat = request.query_params.get('lat') or request.query_params.get('latitude')
        lng = request.query_params.get('long') or request.query_params.get('longitude')
        coord_source = 'query'

        if lat is None or lng is None:
            u = request.user
            ulat = getattr(u, 'latitude', None)
            ulng = getattr(u, 'longitude', None)
            if ulat is not None and ulng is not None:
                lat = str(ulat)
                lng = str(ulng)
                coord_source = 'user_profile'
            else:
                return Response(
                    {
                        'error': (
                            'Provide lat and long in the query (or latitude / longitude), '
                            'or set latitude and longitude on the user profile.'
                        ),
                        'code': 'location_required',
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

        q = request.query_params.copy()
        q['lat'] = str(lat)
        q['long'] = str(lng)
        if not q.get('radius'):
            q['radius'] = '50'  # miles (≈80.5 km)
        request._request.GET = q

        want_explain = request.query_params.get('explain', '').lower() in ('1', 'true', 'yes') or request.query_params.get(
            'debug', ''
        ).lower() in ('1', 'true', 'yes')

        response = super().get(request)

        explain = None
        need_explain_build = want_explain or (
            response.status_code == status.HTTP_200_OK
            and isinstance(response.data, list)
            and len(response.data) == 0
        )
        if need_explain_build:
            try:
                u_lat_f = float(lat)
                u_lng_f = float(lng)
                r_mi = float(q.get('radius') or '50')
                r_km = r_mi * MILES_TO_KM
                explain = _nearby_build_full_explain(
                    user_lat=u_lat_f,
                    user_lng=u_lng_f,
                    radius_km=r_km,
                    radius_miles=r_mi,
                    category_id_raw=request.query_params.get('category'),
                    coord_source=coord_source,
                )
            except (TypeError, ValueError) as e:
                explain = {'coord_source': coord_source, 'snapshot_error': str(e)}

        if (
            response.status_code == status.HTTP_200_OK
            and isinstance(response.data, list)
            and len(response.data) == 0
            and explain
        ):
            logger.warning(
                'nearby_masters_empty user_id=%s coord_source=%s category=%s explain=%s',
                request.user.pk,
                coord_source,
                request.query_params.get('category'),
                explain,
            )

        if want_explain and response.status_code == status.HTTP_200_OK and isinstance(response.data, list):
            return Response({'masters': response.data, 'nearby_explain': explain or {}})

        return response


class OrderPagination(PageNumberPagination):
    """Pagination for orders"""
    page_size = 10
    page_size_query_param = 'page_size'
    max_page_size = 100


class StandardOrderCreateView(APIView):
    """Create standard order (normal booking with a chosen master)."""
    permission_classes = [IsAuthenticated]
    parser_classes = [JSONParser, MultiPartParser, FormParser]

    @extend_schema(
        summary="Create standard order",
        description="""
# Standard order

This endpoint creates a **standard** (non-emergency) order when the client:
- Selects **master/workshop** in advance
- Sends **location** and **service** details (cars, categories)

**Preferred time (standard):** send **`preferred_date`** + **`preferred_time_start`** together (both or neither). Do **not** send **`preferred_time_end`** on create — the **assigned master** sets it after **accept** via `PATCH /api/order/<order_id>/preferred-time/`.

## Content types

- **application/json** — `car_list` / `category_list` as JSON arrays.
- **multipart/form-data** — same fields as strings; `car_list` / `category_list` as **JSON strings** (e.g. `[1,2]`) or comma-separated IDs; the API **parses them to int lists** before validation. Optional file field **`images`** (repeat for multiple photos).

`order_type` is set server-side to **`standard`** — you do not need to send it (JSON or multipart).

**URL:** `POST /api/order/standard/` (legacy alias: `POST /api/order/scheduled/`).

## When to use

- Planned maintenance (oil change, tire fitting, diagnostics)
- Client has chosen a workshop from the list

Do NOT use for **emergencies** (use `/api/order/sos/`).

## Typical payload (validated server-side; missing fields → 400)

- **master_id**, **text**, **location**, **latitude**, **longitude**, **car_list**, **category_list**
- Optional: **preferred_date** + **preferred_time_start** (pair), **parts_purchase_required**, **images** (multipart)

## Validation

- Order coordinates must fall within the selected master’s **acceptance zone** (map pin + radius).
- If **preferred_date** + **preferred_time_start** are sent: that instant must not fall inside another **accepted** standard order’s `[preferred_time_start, preferred_time_end]` for the same master and date, nor inside a **MasterBusySlot** without `order` (rest or manual block) on that date.
        """,
        tags=[STAG_ORDER_DRIVER_CREATE],
        request={
            'application/json': {
                'type': 'object',
                'properties': {
                    'order_type': {
                        'type': 'string',
                        'enum': ['standard'],
                        'description': 'Optional in body; server always sets `standard` for this endpoint.',
                        'example': 'standard',
                    },
                    'master_id': {'type': 'integer', 'description': 'Master/workshop ID', 'example': 5},
                    'text': {'type': 'string', 'description': 'Service description', 'example': 'Oil and filter change'},
                    'location': {'type': 'string', 'description': 'Workshop address', 'example': 'Auto Service, Main St. 15'},
                    'latitude': {'type': 'number', 'description': 'Workshop latitude', 'example': 41.3111},
                    'longitude': {'type': 'number', 'description': 'Workshop longitude', 'example': 69.2797},
                    'car_list': {'type': 'array', 'items': {'type': 'integer'}, 'description': 'List of car IDs', 'example': [2]},
                    'category_list': {'type': 'array', 'items': {'type': 'integer'}, 'description': 'List of category IDs', 'example': [1]},
                    'preferred_date': {'type': 'string', 'format': 'date', 'description': 'With preferred_time_start only'},
                    'preferred_time_start': {'type': 'string', 'format': 'time', 'description': 'With preferred_date only'},
                    'parts_purchase_required': {'type': 'boolean', 'default': False},
                },
            },
            'multipart/form-data': {
                'type': 'object',
                'properties': {
                    'master_id': {'type': 'integer'},
                    'text': {'type': 'string'},
                    'location': {'type': 'string'},
                    'latitude': {'type': 'string', 'description': 'Decimal as string'},
                    'longitude': {'type': 'string', 'description': 'Decimal as string'},
                    'car_list': {
                        'type': 'string',
                        'description': 'JSON array as string e.g. [1,2] or comma-separated 1,2 (parsed server-side)',
                    },
                    'category_list': {
                        'type': 'string',
                        'description': 'JSON array as string e.g. [5] or comma-separated (parsed server-side)',
                    },
                    'preferred_date': {'type': 'string', 'format': 'date'},
                    'preferred_time_start': {'type': 'string', 'format': 'time'},
                    'parts_purchase_required': {'type': 'boolean', 'default': False},
                    'images': {'type': 'array', 'items': {'type': 'string', 'format': 'binary'}},
                },
            },
        },
        responses={
            201: {
                'description': 'Order created successfully',
                'content': {
                    'application/json': {
                        'example': {
                            'message': 'Your order has been created and sent to the master',
                            'order': {
                                'id': 123,
                                'order_type': 'standard',
                                'status': 'pending',
                                'master': {'id': 5, 'name': 'Auto Service'},
                                'text': 'Oil and filter change'
                            }
                        }
                    }
                }
            },
            400: {
                'description': 'Validation error',
                'content': {
                    'application/json': {
                        'examples': {
                            'missing_master': {
                                'summary': 'Master not specified',
                                'value': {'master_id': ['Master is required for standard order']}
                            },
                            'distance_error': {
                                'summary': 'Master too far',
                                'value': {'master_id': ['Selected master is too far (150.5 km). Maximum distance: 50 km.']}
                            }
                        }
                    }
                }
            },
            401: {'description': 'Not authenticated'}
        }
    )
    def post(self, request):
        """Create standard order"""
        data = normalize_order_create_request_data(request)
        data['order_type'] = OrderType.STANDARD

        serializer = OrderCreateSerializer(data=data, context={'request': request})
        if serializer.is_valid():
            order = serializer.save(user=request.user)
            attach_order_images_from_request(order, request)
            order_serializer = OrderSerializer(order, context={'request': request})
            return Response({
                'message': 'Your order has been created and sent to the master',
                'order': order_serializer.data
            }, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class SOSOrderCreateView(APIView):
    """Create SOS order (emergency assistance)"""
    permission_classes = [IsAuthenticated]
    parser_classes = [JSONParser, MultiPartParser, FormParser]

    @extend_schema(
        summary="Create SOS order (emergency assistance)",
        description="""
# SOS order (Emergency assistance)

This endpoint creates an **emergency order** when the client:
- Is in an **emergency** (car broke down, flat tire, etc.)
- Needs **immediate assistance**
- Sends current **GPS location**
- System finds nearest available masters within radius

## Content types

- **application/json** — arrays for `car_list` / `category_list`.
- **multipart/form-data** — `car_list` / `category_list` as **JSON strings**; optional **`images`** (multiple files).

`order_type` is set server-side to `sos`.

## When to use

- Car broke down on the road
- Flat tire on the highway
- Engine won't start
- Any emergency requiring immediate help

Do NOT use for **planned work** (use `/api/order/standard/`).

## Required fields

- **text**: problem description
- **car_list**, **category_list**: car and category IDs (**нужна хотя бы одна by_order** категория)
- **location**, **latitude**, **longitude**: current location (GPS)

## Optional

- **priority** (default **high**)
- **parts_purchase_required** (boolean, default false)
- **images** (multipart)

## Validation

- Очередь мастеров по расстоянию и услуге (**by_order**); **ws/sos/master/?token=JWT** для мастера.
        """,
        tags=[STAG_ORDER_DRIVER_CREATE],
        request={
            'application/json': {
                'type': 'object',
                'required': ['text', 'location', 'latitude', 'longitude', 'car_list', 'category_list'],
                'properties': {
                    'order_type': {
                        'type': 'string',
                        'enum': ['sos'],
                        'description': 'Optional in body; server always sets `sos` for this endpoint.',
                        'example': 'sos',
                    },
                    'priority': {'type': 'string', 'enum': ['low', 'high'], 'description': 'Optional; default high', 'example': 'high'},
                    'text': {'type': 'string', 'description': 'Problem description', 'example': 'Flat tire on highway'},
                    'location': {'type': 'string', 'description': 'Current location description', 'example': 'Highway M39, km 45, near Shell station'},
                    'latitude': {'type': 'number', 'description': 'Current latitude (GPS)', 'example': 41.2548},
                    'longitude': {'type': 'number', 'description': 'Current longitude (GPS)', 'example': 69.2107},
                    'car_list': {'type': 'array', 'items': {'type': 'integer'}, 'description': 'List of car IDs', 'example': [2]},
                    'category_list': {'type': 'array', 'items': {'type': 'integer'}, 'description': 'List of category IDs', 'example': [1]},
                    'parts_purchase_required': {'type': 'boolean', 'default': False},
                },
            },
            'multipart/form-data': {
                'type': 'object',
                'required': ['text', 'location', 'latitude', 'longitude', 'car_list', 'category_list'],
                'properties': {
                    'priority': {'type': 'string', 'enum': ['low', 'high']},
                    'text': {'type': 'string'},
                    'location': {'type': 'string'},
                    'latitude': {'type': 'string'},
                    'longitude': {'type': 'string'},
                    'car_list': {
                        'type': 'string',
                        'description': 'JSON array as string e.g. [1,2] or comma-separated 1,2 (parsed server-side)',
                    },
                    'category_list': {
                        'type': 'string',
                        'description': 'JSON array as string e.g. [5] or comma-separated (parsed server-side)',
                    },
                    'parts_purchase_required': {'type': 'boolean', 'default': False},
                    'images': {'type': 'array', 'items': {'type': 'string', 'format': 'binary'}},
                },
            },
        },
        responses={
            201: {
                'description': 'SOS order created successfully',
                'content': {
                    'application/json': {
                        'example': {
                            'message': 'Your emergency order has been sent to the master',
                            'order': {
                                'id': 456,
                                'order_type': 'sos',
                                'status': 'pending',
                                'priority': 'high',
                                'master': {'id': 5, 'name': 'Auto Service'},
                                'location': 'Highway M39, km 45',
                                'latitude': 41.2548,
                                'longitude': 69.2107,
                                'text': 'Flat front right tire'
                            }
                        }
                    }
                }
            },
            400: {
                'description': 'Validation error',
                'content': {
                    'application/json': {
                        'examples': {
                            'sos_category_by_order': {
                                'summary': 'SOS without master: need by_order category',
                                'value': {'category_list': ['For car SOS, select at least one by_order service category.']}
                            },
                            'missing_location': {
                                'summary': 'Location not specified',
                                'value': {'latitude': ['This field is required'], 'longitude': ['This field is required']}
                            },
                            'distance_error': {
                                'summary': 'Master too far',
                                'value': {'master_id': ['Selected master is too far (150.5 km). Maximum distance: 50 km.']}
                            }
                        }
                    }
                }
            },
            401: {'description': 'Not authenticated'}
        }
    )
    def post(self, request):
        """Create SOS order"""
        data = normalize_order_create_request_data(request)
        data['order_type'] = OrderType.SOS

        serializer = OrderCreateSerializer(data=data, context={'request': request})
        if serializer.is_valid():
            order = serializer.save(user=request.user)
            attach_order_images_from_request(order, request)
            order_serializer = OrderSerializer(order, context={'request': request})
            return Response({
                'message': 'Your emergency order has been created and sent to the master',
                'order': order_serializer.data
            }, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class CustomRequestCreateView(APIView):
    """
    Client-only custom request: description, address + GPS, photos (see settings for min/max count).
    Masters are notified on the existing SOS master WebSocket (`custom_request_job`); category is set server-side.
    """

    permission_classes = [IsAuthenticated]
    parser_classes = [JSONParser, MultiPartParser, FormParser]

    @extend_schema(
        summary='Create custom request order',
        description="""
Creates `order_type=custom_request`. Service category is set **server-side** (main category with `is_custom_request_entry`).

**Multipart:** field **`images`** — **2–10** files by default (`CUSTOM_REQUEST_MIN_IMAGES` / `CUSTOM_REQUEST_MAX_IMAGES`).

**JSON** cannot carry files; use **multipart/form-data** when uploading photos.

Broadcast to masters within **`CUSTOM_REQUEST_BROADCAST_RADIUS_MILES`** runs asynchronously (**Celery** after create).
        """,
        tags=[STAG_ORDER_DRIVER_CREATE],
        request={
            'application/json': {
                'type': 'object',
                'required': ['text', 'location', 'latitude', 'longitude'],
                'properties': {
                    'text': {
                        'type': 'string',
                        'description': 'Problem / request description (tafsilot).',
                        'example': 'Need inspection: unusual noise after cold start',
                    },
                    'location': {
                        'type': 'string',
                        'description': 'Address or location text (manzil).',
                        'example': 'Toshkent, Chilonzor 8-kvartal, 12-uy',
                    },
                    'latitude': {
                        'type': 'number',
                        'description': 'GPS latitude (WGS84).',
                        'example': 41.3111,
                    },
                    'longitude': {
                        'type': 'number',
                        'description': 'GPS longitude (WGS84).',
                        'example': 69.2797,
                    },
                    'custom_request_date': {
                        'type': 'string',
                        'format': 'date',
                        'description': 'Preferred calendar day for the service (client local / request date).',
                        'example': '2026-04-18',
                    },
                    'custom_request_time': {
                        'type': 'string',
                        'format': 'time',
                        'description': 'Preferred local time for the service (HH:MM or HH:MM:SS).',
                        'example': '14:30:00',
                    },
                    'car_list': {
                        'type': 'array',
                        'items': {'type': 'integer'},
                        'description': 'Optional. Car IDs belonging to the current user.',
                        'example': [1, 2],
                    },
                    'parts_purchase_required': {
                        'type': 'boolean',
                        'default': False,
                        'description': 'Whether spare parts may need to be purchased.',
                    },
                },
            },
            'multipart/form-data': {
                'type': 'object',
                'required': ['text', 'location', 'latitude', 'longitude', 'images'],
                'properties': {
                    'text': {'type': 'string', 'description': 'Problem / request description'},
                    'location': {'type': 'string', 'description': 'Address or location text'},
                    'latitude': {
                        'type': 'string',
                        'description': 'Decimal as string (e.g. "41.3111")',
                        'example': '41.3111',
                    },
                    'longitude': {
                        'type': 'string',
                        'description': 'Decimal as string (e.g. "69.2797")',
                        'example': '69.2797',
                    },
                    'custom_request_date': {
                        'type': 'string',
                        'format': 'date',
                        'description': 'Preferred calendar day (YYYY-MM-DD).',
                    },
                    'custom_request_time': {
                        'type': 'string',
                        'description': 'Local time, e.g. "14:30" or "14:30:00".',
                    },
                    'car_list': {
                        'type': 'string',
                        'description': 'JSON array string, e.g. `[1,2]`, or comma-separated `1,2`',
                        'example': '[1]',
                    },
                    'parts_purchase_required': {
                        'type': 'boolean',
                        'default': False,
                        'description': 'Multipart booleans often sent as string "true"/"false"',
                    },
                    'images': {
                        'type': 'array',
                        'description': '2–10 image files (default); field name repeated per file.',
                        'items': {'type': 'string', 'format': 'binary'},
                        'minItems': 2,
                        'maxItems': 10,
                    },
                },
            },
        },
        responses={
            201: {
                'description': 'Created',
                'content': {
                    'application/json': {
                        'schema': {
                            'type': 'object',
                            'properties': {
                                'message': {'type': 'string'},
                                'order': {'type': 'object', 'description': 'OrderSerializer payload'},
                            },
                        },
                        'example': {
                            'message': 'Your custom request has been sent to nearby masters',
                            'order': {
                                'id': 1,
                                'order_type': 'custom_request',
                                'status': 'pending',
                            },
                        },
                    }
                },
            },
            400: {
                'description': 'Validation error (e.g. image count, missing fields)',
                'content': {
                    'application/json': {
                        'example': {
                            'images': ['Attach between 2 and 10 images.'],
                        }
                    }
                },
            },
            401: {'description': 'Not authenticated'},
        },
    )
    def post(self, request):
        data = normalize_custom_request_create_data(request)
        serializer = CustomRequestCreateSerializer(data=data, context={'request': request})
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        n_images = len(request.FILES.getlist('images'))
        lo = int(getattr(settings, 'CUSTOM_REQUEST_MIN_IMAGES', 2))
        hi = int(getattr(settings, 'CUSTOM_REQUEST_MAX_IMAGES', 10))
        if n_images < lo or n_images > hi:
            return Response(
                {'images': [f'Attach between {lo} and {hi} images.']},
                status=status.HTTP_400_BAD_REQUEST,
            )

        order = serializer.save()
        attach_order_images_from_request(order, request)
        from apps.order.tasks import schedule_broadcast_custom_request

        schedule_broadcast_custom_request(order.pk)
        order_serializer = OrderSerializer(order, context={'request': request})
        return Response(
            {
                'message': 'Your custom request has been sent to nearby masters',
                'order': order_serializer.data,
            },
            status=status.HTTP_201_CREATED,
        )


class CustomRequestOfferListCreateView(APIView):
    """GET: driver (owner) or master lists offers + full order. POST: master submits one offer per order."""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        summary='List custom-request offers with full master + order (driver or master)',
        description=(
            '**Driver** (order owner): all offers, each with full `master` (MasterSerializer), plus `order`. '
            '**Master**: only if they placed an offer on this order or are the assigned master; '
            'competing masters see **only their own** offer in `offers`.'
        ),
        tags=[STAG_ORDER_DETAILS],
        responses={
            200: {
                'type': 'object',
                'properties': {
                    'order': {'type': 'object', 'description': 'OrderSerializer payload'},
                    'offers': {
                        'type': 'array',
                        'items': {'type': 'object'},
                    },
                },
            },
        },
    )
    def get(self, request, order_id):
        order = get_object_or_404(
            Order.objects.select_related('user', 'master', 'master__user').prefetch_related(
                'images', 'category', 'category__parent', 'car', 'car__category'
            ),
            pk=order_id,
        )
        if order.order_type != OrderType.CUSTOM_REQUEST:
            return Response(
                {'detail': 'Not a custom request order.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        allowed, restrict_master = _custom_request_offers_list_access(request, order)
        if not allowed:
            return Response(status=status.HTTP_403_FORBIDDEN)

        offers = (
            CustomRequestOffer.objects.filter(order=order)
            .select_related('master', 'master__user')
            .order_by('-created_at')
        )
        if restrict_master is not None:
            offers = offers.filter(master=restrict_master)

        ser_ctx = {'request': request, 'order': order}
        return Response(
            {
                'order': OrderSerializer(order, context={'request': request}).data,
                'offers': CustomRequestOfferWithMasterSerializer(
                    offers, many=True, context=ser_ctx
                ).data,
            }
        )

    @extend_schema(
        summary='Submit a price offer (master, once per order)',
        tags=[STAG_ORDER_MASTER_AVAILABLE],
        request=CustomRequestOfferCreateSerializer,
        responses={
            201: CustomRequestOfferSerializer(),
            400: {'description': 'Duplicate offer or validation error'},
        },
    )
    def post(self, request, order_id):
        order = get_object_or_404(Order, pk=order_id)
        if order.order_type != OrderType.CUSTOM_REQUEST:
            return Response(
                {'detail': 'Not a custom request order.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if order.status != OrderStatus.PENDING or order.master_id:
            return Response(
                {'detail': 'This order is not open for new offers.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        master = Master.objects.filter(user=request.user).first()
        if not master:
            return Response(status=status.HTTP_403_FORBIDDEN)

        from apps.order.services.custom_request_broadcast import master_within_custom_request_radius
        from apps.order.services.notifications import push_custom_request_offer_to_rider_websocket

        if order.latitude is None or order.longitude is None:
            return Response(
                {'detail': 'Order has no coordinates.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if not master_within_custom_request_radius(
            master, float(order.latitude), float(order.longitude)
        ):
            return Response(
                {'detail': 'You are outside the service radius for this request.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        wr = CustomRequestOfferCreateSerializer(data=request.data)
        if not wr.is_valid():
            return Response(wr.errors, status=status.HTTP_400_BAD_REQUEST)

        if CustomRequestOffer.objects.filter(order=order, master=master).exists():
            return Response(
                {
                    'detail': (
                        'You have already submitted an offer for this order. '
                        'You cannot send another offer for the same request.'
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        offer = CustomRequestOffer.objects.create(
            order=order,
            master=master,
            price=wr.validated_data['price'],
        )
        push_custom_request_offer_to_rider_websocket(
            order,
            offer_id=offer.pk,
            master_id=master.pk,
            price=str(offer.price),
            created_at_iso=offer.created_at.isoformat() if offer.created_at else None,
            request=request,
        )
        return Response(
            CustomRequestOfferSerializer(offer).data,
            status=status.HTTP_201_CREATED,
        )


class AvailableTimeSlotsView(APIView):
    """Get available time slots for master on a given date"""
    permission_classes = [IsAuthenticated]

    @extend_schema(
        summary="Get available time slots for booking",
        description="""
# Available time slots

Returns time slots for booking with a master on a given date.
**Unavailable** rows use **exact** busy start/end (accepted standard orders with preferred times,
plus manual `MasterBusySlot`); overlapping busy is merged. **Available** rows fill the rest of the
work day (excluding **rest** / `break_data`) using hour-aligned free intervals.

## Required parameters

- **master_id** (query) - Master/workshop ID
- **date** (query) - Date in YYYY-MM-DD format (e.g. 2026-01-30)

## Response format

Each row: **start**, **end** (HH:MM), **available** (boolean). **order_id** may appear on a single-hour
unavailable row when only one order maps to it; merged busy spans omit it.
**break_data** from a **busy-slot** row with ``start_time_rest`` + ``time_range_rest`` (one per day); null if none.
        """,
        tags=[STAG_ORDER_DRIVER_SLOTS],
        parameters=[
            OpenApiParameter(
                name='master_id',
                type=OpenApiTypes.INT,
                location=OpenApiParameter.QUERY,
                description='Master ID (required). Example: 5',
                required=True
            ),
            OpenApiParameter(
                name='date',
                type=OpenApiTypes.DATE,
                location=OpenApiParameter.QUERY,
                description='Date for slot check (YYYY-MM-DD). Example: 2026-01-30',
                required=True
            ),
        ],
        responses={
            200: {
                'description': 'List of available time slots',
                'content': {
                    'application/json': {
                        'example': {
                            'date': '2026-01-30',
                            'master_id': 5,
                            'master_name': 'Auto Service',
                            'working_hours': '09:00-18:00',
                            'break_data': {
                                'start_time_rest': '13:00',
                                'end_time_rest': '14:00',
                                'time_range_rest': '1.00',
                            },
                            'slots': [
                                {'start': '09:00', 'end': '10:00', 'available': True},
                                {'start': '10:00', 'end': '12:00', 'available': False},
                                {'start': '14:00', 'end': '15:00', 'available': True},
                            ]
                        }
                    }
                }
            },
            400: {
                'description': 'Validation error',
                'content': {
                    'application/json': {
                        'examples': {
                            'missing_params': {
                                'summary': 'Missing parameters',
                                'value': {'error': 'master_id and date are required'}
                            },
                            'invalid_date': {
                                'summary': 'Invalid date format',
                                'value': {'error': 'Invalid date format. Use YYYY-MM-DD'}
                            }
                        }
                    }
                }
            },
            404: {
                'description': 'Master not found',
                'content': {
                    'application/json': {
                        'example': {'error': 'Master not found'}
                    }
                }
            }
        }
    )
    def get(self, request):
        """Get available time slots"""
        from datetime import datetime

        # Get parameters
        master_id = request.query_params.get('master_id')
        date_str = request.query_params.get('date')
        
        # Validate parameters
        if not master_id or not date_str:
            return Response(
                {'error': 'master_id and date are required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Validate date
        try:
            check_date = datetime.strptime(date_str, '%Y-%m-%d').date()
        except ValueError:
            return Response(
                {'error': 'Invalid date format. Use YYYY-MM-DD (e.g. 2026-01-30)'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Get master
        try:
            master = Master.objects.get(id=master_id)
        except Master.DoesNotExist:
            return Response(
                {'error': 'Master not found'},
                status=status.HTTP_404_NOT_FOUND
            )

        from apps.master.services.slots import build_master_day_slots_payload

        payload, err_msg = build_master_day_slots_payload(master, check_date)
        if err_msg:
            return Response({'error': err_msg}, status=status.HTTP_400_BAD_REQUEST)
        return Response(payload)


class OrderListCreateView(APIView):
    """Order list"""
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['status', 'priority', 'master']
    search_fields = ['text', 'location', 'user__first_name', 'user__last_name', 'user__email']
    ordering_fields = ['created_at', 'updated_at', 'status', 'priority']
    ordering = ['-created_at']

    def get_queryset(self):
        user = self.request.user
        
        # If user is master, show orders assigned to them
        master = user.master_profiles.first()
        if master:
            return Order.objects.filter(master=master)
        
        # If regular user, show only their orders
        return Order.objects.filter(user=user)

    @extend_schema(
        summary="Получить список заказов",
        description="Возвращает список заказов с возможностью фильтрации, поиска и сортировки",
        tags=[STAG_ORDER_DRIVER_MY],
        parameters=[
            {'name': 'status', 'in': 'query', 'description': 'Фильтр по статусу заказа', 'type': 'string', 'enum': [choice[0] for choice in OrderStatus.choices]},
            {'name': 'priority', 'in': 'query', 'description': 'Фильтр по приоритету заказа', 'type': 'string', 'enum': ['low', 'high']},
            {'name': 'master', 'in': 'query', 'description': 'Фильтр по мастеру (ID мастера)', 'type': 'integer'},
            {'name': 'search', 'in': 'query', 'description': 'Поиск по тексту заказа, местоположению или имени пользователя', 'type': 'string'},
            {'name': 'ordering', 'in': 'query', 'description': 'Сортировка по полю (created_at, updated_at, status, priority)', 'type': 'string', 'enum': ['created_at', '-created_at', 'updated_at', '-updated_at', 'status', '-status', 'priority', '-priority']},
        ],
        responses={
            200: OrderSerializer(many=True),
            401: {'type': 'object', 'properties': {'detail': {'type': 'string'}}},
        }
    )
    def get(self, request):
        """Get order list"""
        expire_stale_master_offers()
        queryset = self.get_queryset().prefetch_related('images', 'category', 'car')

        # Apply filters
        queryset = self.apply_filters(queryset, request)
        
        serializer = OrderSerializer(queryset, many=True, context={'request': request})
        return Response(serializer.data)

    def apply_filters(self, queryset, request):
        """Apply filters to queryset"""
        # Filter by status
        if 'status' in request.query_params:
            queryset = queryset.filter(status=request.query_params['status'])
        
        # Filter by priority
        if 'priority' in request.query_params:
            queryset = queryset.filter(priority=request.query_params['priority'])
        
        # Filter by master
        if 'master' in request.query_params:
            queryset = queryset.filter(master=request.query_params['master'])
        
        # Search
        if 'search' in request.query_params:
            search_term = request.query_params['search']
            queryset = queryset.filter(
                Q(text__icontains=search_term) |
                Q(location__icontains=search_term) |
                Q(user__first_name__icontains=search_term) |
                Q(user__last_name__icontains=search_term) |
                Q(user__email__icontains=search_term)
            )
        
        # Ordering
        ordering = request.query_params.get('ordering', '-created_at')
        if ordering in self.ordering_fields:
            queryset = queryset.order_by(ordering)
        else:
            queryset = queryset.order_by(*self.ordering)
        
        return queryset


class OrderDetailView(APIView):
    """Order detail, update and delete"""
    permission_classes = [IsAuthenticated, IsOrderOwnerOrMaster]

    def get_object(self, order_id):
        """Get order object"""
        try:
            order = (
                Order.objects.prefetch_related(
                    'images',
                    'category',
                    'car',
                    Prefetch(
                        'custom_request_offers',
                        queryset=CustomRequestOffer.objects.only(
                            'id', 'order_id', 'master_id', 'price', 'created_at', 'updated_at'
                        ),
                    ),
                ).get(id=order_id)
            )
            # Check access
            self.check_object_permissions(self.request, order)
            return order
        except Order.DoesNotExist:
            return None

    @extend_schema(
        summary="Get order details",
        description="Returns detailed information about a specific order",
        tags=[STAG_ORDER_DETAILS],
        parameters=[
            {'name': 'id', 'in': 'path', 'description': 'Order ID', 'type': 'integer', 'required': True},
        ],
        responses={
            200: OrderSerializer,
            404: {'type': 'object', 'properties': {'error': {'type': 'string'}}},
            401: {'type': 'object', 'properties': {'detail': {'type': 'string'}}},
            403: {'type': 'object', 'properties': {'detail': {'type': 'string'}}},
        }
    )
    def get(self, request, id):
        """Get order details"""
        expire_stale_master_offers()
        order = self.get_object(id)
        if not order:
            return Response(
                {'error': 'Order not found'}, 
                status=status.HTTP_404_NOT_FOUND
            )
        
        serializer = OrderSerializer(order, context={'request': request})
        return Response(serializer.data)

    @extend_schema(
        summary="Полное обновление заказа",
        description="Полностью обновляет все поля заказа. "
                  "Fields: text, location, priority (low/high), status (pending, in_progress, completed, cancelled, rejected), latitude, longitude, master (ID).",
        tags=[STAG_ORDER_DETAILS],
        parameters=[
            {'name': 'id', 'in': 'path', 'description': 'Order ID', 'type': 'integer', 'required': True},
        ],
        request={
            'application/json': {
                'type': 'object',
                'properties': {
                    'text': {'type': 'string', 'description': 'Order description', 'example': 'Need help with wheel replacement'},
                    'status': {'type': 'string', 'enum': ['pending', 'in_progress', 'completed', 'cancelled', 'rejected'], 'description': 'Order status', 'example': 'in_progress'},
                    'priority': {'type': 'string', 'enum': ['low', 'high'], 'description': 'Order priority', 'example': 'high'},
                    'location': {'type': 'string', 'description': 'Address or place description', 'example': 'Main St. 15'},
                    'latitude': {'type': 'number', 'description': 'Latitude (-90 to 90)', 'example': 41.3111},
                    'longitude': {'type': 'number', 'description': 'Longitude (-180 to 180)', 'example': 69.2797},
                    'master': {'type': 'integer', 'description': 'Master ID', 'example': 1}
                }
            }
        },
        responses={
            200: OrderSerializer,
            400: {'type': 'object', 'properties': {'detail': {'type': 'string'}}},
            404: {'type': 'object', 'properties': {'error': {'type': 'string'}}},
            401: {'type': 'object', 'properties': {'detail': {'type': 'string'}}},
            403: {'type': 'object', 'properties': {'detail': {'type': 'string'}}},
        }
    )
    def put(self, request, id):
        """Full order update"""
        order = self.get_object(id)
        if not order:
            return Response(
                {'error': 'Order not found'}, 
                status=status.HTTP_404_NOT_FOUND
            )
        
        serializer = OrderUpdateSerializer(order, data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    @extend_schema(
        summary="Частичное обновление заказа",
        description="Частично обновляет поля заказа. Можно указать только те поля, которые нужно обновить. "
                  "Fields: text, location, priority (low/high), status (pending, in_progress, completed, cancelled, rejected), latitude, longitude, master (ID).",
        tags=[STAG_ORDER_DETAILS],
        parameters=[
            {'name': 'id', 'in': 'path', 'description': 'Order ID', 'type': 'integer', 'required': True},
        ],
        request={
            'application/json': {
                'type': 'object',
                'properties': {
                    'text': {'type': 'string', 'description': 'Order description', 'example': 'Need help with wheel replacement'},
                    'status': {'type': 'string', 'enum': ['pending', 'in_progress', 'completed', 'cancelled', 'rejected'], 'description': 'Order status', 'example': 'in_progress'},
                    'priority': {'type': 'string', 'enum': ['low', 'high'], 'description': 'Order priority', 'example': 'high'},
                    'location': {'type': 'string', 'description': 'Address or place description', 'example': 'Main St. 15'},
                    'latitude': {'type': 'number', 'description': 'Latitude (-90 to 90)', 'example': 41.3111},
                    'longitude': {'type': 'number', 'description': 'Longitude (-180 to 180)', 'example': 69.2797},
                    'master': {'type': 'integer', 'description': 'Master ID', 'example': 1}
                }
            }
        },
        responses={
            200: OrderSerializer,
            400: {'type': 'object', 'properties': {'detail': {'type': 'string'}}},
            404: {'type': 'object', 'properties': {'error': {'type': 'string'}}},
            401: {'type': 'object', 'properties': {'detail': {'type': 'string'}}},
            403: {'type': 'object', 'properties': {'detail': {'type': 'string'}}},
        }
    )
    def patch(self, request, id):
        """Partial order update"""
        order = self.get_object(id)
        if not order:
            return Response(
                {'error': 'Order not found'}, 
                status=status.HTTP_404_NOT_FOUND
            )
        
        serializer = OrderUpdateSerializer(order, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    @extend_schema(
        summary="Удалить заказ",
        description="Удаляет заказ из системы",
        tags=[STAG_ORDER_DETAILS],
        parameters=[
            {'name': 'id', 'in': 'path', 'description': 'Order ID', 'type': 'integer', 'required': True},
        ],
        responses={
            204: {'description': 'Заказ успешно удален'},
            404: {'type': 'object', 'properties': {'error': {'type': 'string'}}},
            401: {'type': 'object', 'properties': {'detail': {'type': 'string'}}},
            403: {'type': 'object', 'properties': {'detail': {'type': 'string'}}},
        }
    )
    def delete(self, request, id):
        """Delete order"""
        order = self.get_object(id)
        if not order:
            return Response(
                {'error': 'Order not found'}, 
                status=status.HTTP_404_NOT_FOUND
            )
        
        order.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class OrdersByUserView(APIView):
    """
    API для получения заказов текущего пользователя
    """
    permission_classes = [IsAuthenticated]
    pagination_class = OrderPagination
    
    @extend_schema(
        summary="Получить заказы текущего пользователя",
        description="""
## Описание
Возвращает все заказы текущего авторизованного пользователя (user берется из header/token).

## Фильтры (все необязательные)

### 1. Статус заказа (status)
- Значения: pending, in_progress, completed, cancelled, rejected
- Пример: `status=in_progress`

### 2. Приоритет (priority)
- Значения: low (низкий), high (высокий)
- Пример: `priority=high`

### 3. Тип проблемы (category)
- ID категории типа **by_order**
- Использует **smart filter** через дерево parent категории
- Пример: `category=1` — заказы с той же категорией, соседями (общий parent), родителем или дочерними

### 4. Район (location)
- Поиск по адресу заказа
- Пример: `location=Ташкент` или `location=Навои`
- Поиск нечувствителен к регистру

### 5. Тип ТС (car_category)
- ID категории машины типа **by_car**
- Прямой фильтр по ID
- Пример: `car_category=3` (где 3 - это "Легковой")

### 6. Тип заказа (order_type)
- Фильтр по типу заказа
- Значения: `standard` (обычный заказ с мастером) или `sos` (экстренный)
- Устаревшее значение `scheduled` воспринимается как `standard`
- Пример: `order_type=standard` — только стандартные заказы
- Пример: `order_type=sos` — только SOS заказы

### 7. Имя мастера (name)
- Поиск по имени мастера
- Пример: `name=Алексей`

## Pagination
- По умолчанию 10 заказов на страницу
- Можно изменить через `page_size` (макс. 100)

## Примеры запросов

**Базовый:**
```
GET /api/order/by-user/
```

**С фильтром по статусу:**
```
GET /api/order/by-user/?status=in_progress
```

**С фильтром по проблеме (smart filter):**
```
GET /api/order/by-user/?category=1
```

**С несколькими фильтрами:**
```
GET /api/order/by-user/?status=pending&priority=high&category=1&location=Ташкент
```

**Только стандартные заказы:**
```
GET /api/order/by-user/?order_type=standard
```

**Только SOS заказы (экстренные):**
```
GET /api/order/by-user/?order_type=sos
```

**Стандартные заказы со статусом pending:**
```
GET /api/order/by-user/?order_type=standard&status=pending
```
        """,
        tags=[STAG_ORDER_DRIVER_MY],
        parameters=[
            OpenApiParameter(name='status', type=OpenApiTypes.STR, location=OpenApiParameter.QUERY, description='Фильтр по статусу заказа', required=False, enum=[choice[0] for choice in OrderStatus.choices]),
            OpenApiParameter(name='priority', type=OpenApiTypes.STR, location=OpenApiParameter.QUERY, description='Фильтр по приоритету (low, high)', required=False, enum=['low', 'high']),
            OpenApiParameter(name='category', type=OpenApiTypes.INT, location=OpenApiParameter.QUERY, description='Фильтр по типу проблемы. ID категории by_order. Smart filter по parent-дереву.', required=False),
            OpenApiParameter(name='location', type=OpenApiTypes.STR, location=OpenApiParameter.QUERY, description='Фильтр по району (поиск по адресу заказа)', required=False),
            OpenApiParameter(name='car_category', type=OpenApiTypes.INT, location=OpenApiParameter.QUERY, description='Фильтр по типу ТС (ID категории машины типа by_car)', required=False),
            OpenApiParameter(name='order_type', type=OpenApiTypes.STR, location=OpenApiParameter.QUERY, description='Фильтр: standard или sos (устар. scheduled = standard)', required=False, enum=['standard', 'sos', 'scheduled']),
            OpenApiParameter(name='name', type=OpenApiTypes.STR, location=OpenApiParameter.QUERY, description='Поиск по имени мастера', required=False),
            OpenApiParameter(name='page', type=OpenApiTypes.INT, location=OpenApiParameter.QUERY, description='Номер страницы для пагинации', required=False),
            OpenApiParameter(name='page_size', type=OpenApiTypes.INT, location=OpenApiParameter.QUERY, description='Количество заказов на странице (макс. 100)', required=False),
        ],
        responses={
            200: OrderSerializer(many=True),
            401: {'type': 'object', 'properties': {'detail': {'type': 'string'}}},
        }
    )
    def get(self, request):
        """Получить заказы текущего пользователя"""
        expire_stale_master_offers()
        orders = Order.objects.filter(user=request.user).prefetch_related(
            'images',
            'category',
            'car',
            Prefetch(
                'custom_request_offers',
                queryset=CustomRequestOffer.objects.only(
                    'id', 'order_id', 'master_id', 'price', 'created_at', 'updated_at'
                ),
            ),
        )
        
        # Фильтр по статусу
        status_filter = request.query_params.get('status')
        if status_filter:
            orders = orders.filter(status=status_filter)
        
        # Фильтр по приоритету
        priority_filter = request.query_params.get('priority')
        if priority_filter:
            orders = orders.filter(priority=priority_filter)
        
        # Фильтр по типу заказа (standard / sos; legacy scheduled → standard)
        order_type_filter = _normalize_order_type_query_param(request.query_params.get('order_type'))
        if order_type_filter:
            if order_type_filter in (OrderType.STANDARD, OrderType.SOS, OrderType.CUSTOM_REQUEST):
                orders = orders.filter(order_type=order_type_filter)
        
        # Smart фильтр по категории проблемы (Тип проблемы)
        category_filter = request.query_params.get('category')
        if category_filter:
            try:
                from apps.categories.models import Category
                category_id = int(category_filter)
                category = Category.objects.get(id=category_id)
                
                if category.type_category == 'by_order':
                    orders = orders.filter(order_by_order_category_smart_q(category))
                else:
                    # Для других типов - прямой фильтр по ID
                    orders = orders.filter(category__id=category_id)
                    
            except Category.DoesNotExist:
                pass
            except (ValueError, TypeError):
                pass
        
        # Фильтр по району/местоположению (Районы)
        location_filter = request.query_params.get('location')
        if location_filter:
            orders = orders.filter(location__icontains=location_filter)
        
        # Фильтр по типу ТС (категория машины)
        car_category_filter = request.query_params.get('car_category')
        if car_category_filter:
            try:
                car_category_id = int(car_category_filter)
                orders = orders.filter(car__category__id=car_category_id)
            except (ValueError, TypeError):
                pass
        
        # Фильтр по имени мастера
        name = request.query_params.get('name')
        if name:
            orders = orders.filter(
                Q(master__user__first_name__icontains=name) |
                Q(master__user__last_name__icontains=name) |
                Q(master__user__get_full_name__icontains=name)
            )
        
        # Убираем дубликаты и сортируем
        orders = orders.distinct().order_by('-created_at')
        
        # Применяем пагинацию
        paginator = self.pagination_class()
        page = paginator.paginate_queryset(orders, request)
        if page is not None:
            serializer = OrderSerializer(page, many=True, context={'request': request})
            return paginator.get_paginated_response(serializer.data)
        
        serializer = OrderSerializer(orders, many=True, context={'request': request})
        return Response(serializer.data)


class OrdersByMasterView(APIView):
    """
    API для получения заказов текущего мастера
    """
    permission_classes = [IsAuthenticated]
    pagination_class = OrderPagination
    
    @extend_schema(
        summary="Получить заказы текущего мастера",
        description="""
## Описание
Возвращает список заказов, назначенных текущему мастеру (``master`` FK = вы), плюс активные SOS в очереди.
**Custom request** с пустым ``master`` сюда **не входит** (пока клиент не выбрал мастера) — только incoming sync / WebSocket.

## Фильтры (все необязательные)

### 1. Статус заказа (status)
- Значения: pending, in_progress, completed, cancelled, rejected
- Пример: `status=in_progress`

### 2. Приоритет (priority)
- Значения: low (низкий), high (высокий)
- Пример: `priority=high`

### 3. Тип проблемы (category)
- ID категории типа **by_order**
- Использует **smart filter** через дерево parent категории
- Пример: `category=1` — заказы с той же категорией, соседями (общий parent), родителем или дочерними

### 4. Район (location)
- Поиск по адресу заказа
- Пример: `location=Ташкент` или `location=Навои`
- Поиск нечувствителен к регистру

### 5. Тип ТС (car_category)
- ID категории машины типа **by_car**
- Прямой фильтр по ID
- Пример: `car_category=3` (где 3 - это "Легковой")

### 6. Географическая область (4 точки)
- Фильтр по координатам (полигон)
- Требуется указать все 4 точки
- Пример: `point1_lat=41.3&point1_lon=69.2&point2_lat=...`

### 7. Новые заказы (is_new)
- Фильтр для отображения новых заказов
- Значение: `true` или `false`
- Показывает заказы без назначенного master (FK master пустой)
- Пример: `is_new=true`

### 8. В работе (is_work)
- Фильтр для заказов в работе
- Значение: `true` или `false`
- Показывает заказы текущего мастера со статусом IN_PROGRESS
- Пример: `is_work=true`

### 9. Архив (is_archive)
- Фильтр для завершенных заказов
- Значение: `true` или `false`
- Показывает заказы текущего мастера со статусом COMPLETED
- Пример: `is_archive=true`

### 10. Тип заказа (order_type)
- Фильтр по типу заказа
- Значения: `standard` или `sos` (устар. `scheduled` = standard)
- Пример: `order_type=standard` — только стандартные заказы
- Пример: `order_type=sos` — только SOS заказы

## Pagination
- По умолчанию 10 заказов на страницу
- Можно изменить через `page_size` (макс. 100)

## Примеры запросов

**Базовый:**
```
GET /api/order/by-master/
```

**Новые заказы:**
```
GET /api/order/by-master/?is_new=true
```

**Заказы в работе:**
```
GET /api/order/by-master/?is_work=true
```

**Завершенные заказы (архив):**
```
GET /api/order/by-master/?is_archive=true
```

**С фильтром по статусу:**
```
GET /api/order/by-master/?status=in_progress
```

**С фильтром по проблеме (smart filter):**
```
GET /api/order/by-master/?category=1
```

**С несколькими фильтрами:**
```
GET /api/order/by-master/?status=pending&priority=high&category=1&location=Ташкент
```

**Только стандартные заказы:**
```
GET /api/order/by-master/?order_type=standard
```

**Только SOS заказы (экстренные):**
```
GET /api/order/by-master/?order_type=sos
```

**Стандартные заказы со статусом pending:**
```
GET /api/order/by-master/?order_type=standard&status=pending
```
        """,
        tags=[STAG_ORDER_MASTER_MY],
        parameters=[
            OpenApiParameter(name='status', type=OpenApiTypes.STR, location=OpenApiParameter.QUERY, description='Фильтр по статусу заказа', required=False, enum=[choice[0] for choice in OrderStatus.choices]),
            OpenApiParameter(name='priority', type=OpenApiTypes.STR, location=OpenApiParameter.QUERY, description='Фильтр по приоритету (low, high)', required=False, enum=['low', 'high']),
            OpenApiParameter(name='category', type=OpenApiTypes.INT, location=OpenApiParameter.QUERY, description='Фильтр по типу проблемы. ID категории by_order. Smart filter по parent-дереву.', required=False),
            OpenApiParameter(name='location', type=OpenApiTypes.STR, location=OpenApiParameter.QUERY, description='Фильтр по району (поиск по адресу заказа)', required=False),
            OpenApiParameter(name='car_category', type=OpenApiTypes.INT, location=OpenApiParameter.QUERY, description='Фильтр по типу ТС (ID категории машины типа by_car)', required=False),
            # Координаты полигона (4 точки)
            OpenApiParameter(name='point1_lat', type=OpenApiTypes.FLOAT, location=OpenApiParameter.QUERY, description='Широта точки 1 (для географического фильтра)', required=False),
            OpenApiParameter(name='point1_lon', type=OpenApiTypes.FLOAT, location=OpenApiParameter.QUERY, description='Долгота точки 1', required=False),
            OpenApiParameter(name='point2_lat', type=OpenApiTypes.FLOAT, location=OpenApiParameter.QUERY, description='Широта точки 2', required=False),
            OpenApiParameter(name='point2_lon', type=OpenApiTypes.FLOAT, location=OpenApiParameter.QUERY, description='Долгота точки 2', required=False),
            OpenApiParameter(name='point3_lat', type=OpenApiTypes.FLOAT, location=OpenApiParameter.QUERY, description='Широта точки 3', required=False),
            OpenApiParameter(name='point3_lon', type=OpenApiTypes.FLOAT, location=OpenApiParameter.QUERY, description='Долгота точки 3', required=False),
            OpenApiParameter(name='point4_lat', type=OpenApiTypes.FLOAT, location=OpenApiParameter.QUERY, description='Широта точки 4', required=False),
            OpenApiParameter(name='point4_lon', type=OpenApiTypes.FLOAT, location=OpenApiParameter.QUERY, description='Долгота точки 4', required=False),
            OpenApiParameter(name='is_new', type=OpenApiTypes.BOOL, location=OpenApiParameter.QUERY, description='Новые заказы (master не назначен)', required=False),
            OpenApiParameter(name='is_work', type=OpenApiTypes.BOOL, location=OpenApiParameter.QUERY, description='Заказы в работе (status=IN_PROGRESS)', required=False),
            OpenApiParameter(name='is_archive', type=OpenApiTypes.BOOL, location=OpenApiParameter.QUERY, description='Завершенные заказы (status=COMPLETED)', required=False),
            OpenApiParameter(name='order_type', type=OpenApiTypes.STR, location=OpenApiParameter.QUERY, description='Фильтр: standard или sos (устар. scheduled = standard)', required=False, enum=['standard', 'sos', 'scheduled']),
            OpenApiParameter(name='page', type=OpenApiTypes.INT, location=OpenApiParameter.QUERY, description='Номер страницы для пагинации', required=False),
            OpenApiParameter(name='page_size', type=OpenApiTypes.INT, location=OpenApiParameter.QUERY, description='Количество заказов на странице (макс. 100)', required=False),
        ],
        responses={
            200: OrderSerializer(many=True),
            401: {'type': 'object', 'properties': {'detail': {'type': 'string'}}},
            403: {'type': 'object', 'properties': {'error': {'type': 'string'}}},
        }
    )
    def get(self, request):
        """Получить заказы текущего мастера (custom request без назначенного master FK не включаются)."""
        expire_stale_master_offers()
        # Проверяем, что пользователь является мастером
        try:
            master = request.user.master_profiles.first()
            if not master:
                return Response(
                    {'error': 'User is not a master'},
                    status=status.HTTP_403_FORBIDDEN
                )
        except AttributeError:
            return Response(
                {'error': 'User is not a master'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        # Заказы: FK master + pending SOS. Custom request с master=null не показываем — клиент должен назначить мастера.
        extra_sos = order_ids_sos_currently_offered_to_master(master.id)
        extra_ids = list(dict.fromkeys(extra_sos))
        if extra_ids:
            orders = Order.objects.filter(Q(master=master) | Q(pk__in=extra_ids))
        else:
            orders = Order.objects.filter(master=master)
        
        # Фильтр is_new — заказы без назначенного master (FK)
        is_new = request.query_params.get('is_new', '').lower() == 'true'
        if is_new:
            orders = Order.objects.filter(master__isnull=True)
        
        # Фильтр is_work — активные после принятия мастером
        is_work = request.query_params.get('is_work', '').lower() == 'true'
        if is_work:
            orders = Order.objects.filter(master=master, status__in=MASTER_ACTIVE_WORK_STATUSES)
        
        # Фильтр is_archive - завершенные заказы (COMPLETED)
        is_archive = request.query_params.get('is_archive', '').lower() == 'true'
        if is_archive:
            orders = Order.objects.filter(master=master, status=OrderStatus.COMPLETED)
        
        # Фильтр по статусу
        status_filter = request.query_params.get('status')
        if status_filter:
            orders = orders.filter(status=status_filter)
        
        # Фильтр по приоритету
        priority_filter = request.query_params.get('priority')
        if priority_filter:
            orders = orders.filter(priority=priority_filter)
        
        # Фильтр по типу заказа (standard / sos; legacy scheduled → standard)
        order_type_filter = _normalize_order_type_query_param(request.query_params.get('order_type'))
        if order_type_filter:
            if order_type_filter in (OrderType.STANDARD, OrderType.SOS, OrderType.CUSTOM_REQUEST):
                orders = orders.filter(order_type=order_type_filter)
        
        # Smart фильтр по категории проблемы (Тип проблемы)
        category_filter = request.query_params.get('category')
        if category_filter:
            try:
                from apps.categories.models import Category
                category_id = int(category_filter)
                category = Category.objects.get(id=category_id)
                
                if category.type_category == 'by_order':
                    orders = orders.filter(order_by_order_category_smart_q(category))
                else:
                    # Для других типов - прямой фильтр по ID
                    orders = orders.filter(category__id=category_id)
                    
            except Category.DoesNotExist:
                pass
            except (ValueError, TypeError):
                pass
        
        # Фильтр по району/местоположению (Районы)
        location_filter = request.query_params.get('location')
        if location_filter:
            orders = orders.filter(location__icontains=location_filter)
        
        # Фильтр по типу ТС (категория машины)
        car_category_filter = request.query_params.get('car_category')
        if car_category_filter:
            try:
                car_category_id = int(car_category_filter)
                orders = orders.filter(car__category__id=car_category_id)
            except (ValueError, TypeError):
                pass
        
        # Фильтр по локации: 4 точки полигона (bounding box)
        area_filter = _get_area_filter_for_orders(request)
        if area_filter:
            # Faqat koordinatalari bo'lgan orderlarni filter qilamiz
            orders = orders.filter(
                latitude__isnull=False,
                longitude__isnull=False,
                **area_filter
            )
        
        # Убираем дубликаты и сортируем
        orders = orders.distinct().order_by('-created_at')
        orders = orders.prefetch_related(
            'images',
            'category',
            'car',
            Prefetch(
                'custom_request_offers',
                queryset=CustomRequestOffer.objects.only(
                    'id', 'order_id', 'master_id', 'price', 'created_at', 'updated_at'
                ),
            ),
        )
        
        # Применяем пагинацию
        paginator = self.pagination_class()
        page = paginator.paginate_queryset(orders, request)
        if page is not None:
            serializer = OrderSerializer(page, many=True, context={'request': request})
            return paginator.get_paginated_response(serializer.data)
        
        serializer = OrderSerializer(orders, many=True, context={'request': request})
        return Response(serializer.data)


def _incoming_sync_typed_items(orders: list[Order], request) -> list[dict]:
    """Each entry: ``order_type`` (sos | custom_request | standard) + full ``order`` payload."""
    if not orders:
        return []
    ctx = {'request': request}
    rows = OrderSerializer(orders, many=True, context=ctx).data
    return [{'order_type': o.order_type, 'order': row} for o, row in zip(orders, rows)]


def _incoming_sync_custom_request_typed_items(
    orders: list[Order],
    request,
    master: Master,
) -> list[dict]:
    """Like ``_incoming_sync_typed_items`` plus ``is_offer_sent`` from ``CustomRequestOffer``."""
    if not orders:
        return []
    oid_set = {o.id for o in orders}
    offered = set(
        CustomRequestOffer.objects.filter(master=master, order_id__in=oid_set).values_list(
            'order_id', flat=True
        )
    )
    ctx = {'request': request}
    rows = OrderSerializer(orders, many=True, context=ctx).data
    return [
        {
            'order_type': o.order_type,
            'is_offer_sent': o.id in offered,
            'order': row,
        }
        for o, row in zip(orders, rows)
    ]


class MasterIncomingSyncView(APIView):
    """
    REST-ответ на случай, если WebSocket был офлайн: активные SOS, открытые custom_request
    и назначенные standard (pending, клиент передал master_id, мастер ещё не принял).
    """

    permission_classes = [IsAuthenticated, IsMaster]

    @extend_schema(
        summary='Синхронизация входящих SOS, custom request и standard (pending)',
        description="""
Вызывайте при открытии приложения мастера, после **reconnect** WebSocket ``/ws/sos/master/`` или по pull-to-refresh.

1. Сначала выполняется ``expire_stale_master_offers`` (как в других master-эндпоинтах) — просроченные SOS/назначенный standard/custom-offer окна приводятся к актуальному состоянию.
2. **sos** — ``pending``, broadcast-очередь, ``master_response_deadline`` в будущем, мастер в зоне приёма и не в ``sos_declined_master_ids``.
3. **custom_request** — ``pending``, без назначенного мастера, не истёк ``expiration_time``, точка заказа в пределах ``CUSTOM_REQUEST_BROADCAST_RADIUS_MILES`` (как при Celery broadcast).
4. **standard** — ``pending``, ``master`` = текущий мастер (клиент указал ``master_id`` при создании), срок ответа не истёк (см. ``MASTER_OFFER_RESPONSE_MINUTES``).

Каждый элемент **sos** и **standard** — ``{ "order_type": "...", "order": { ... OrderSerializer } }``.

Элементы **custom_request** дополнительно содержат ``is_offer_sent`` (bool): есть ли у этого мастера строка ``CustomRequestOffer`` на данный заказ.

Ответ не заменяет WebSocket; дубли с уже показанными push-сообщениями клиент может смержить по ``order.id``.
        """,
        tags=[STAG_ORDER_MASTER_AVAILABLE],
        responses={
            200: {
                'type': 'object',
                'properties': {
                    'stale_offers_swept': {'type': 'integer'},
                    'server_time': {'type': 'string', 'format': 'date-time'},
                    'sos': {
                        'type': 'array',
                        'items': {
                            'type': 'object',
                            'properties': {
                                'order_type': {'type': 'string'},
                                'order': {'type': 'object'},
                            },
                        },
                    },
                    'custom_request': {
                        'type': 'array',
                        'items': {
                            'type': 'object',
                            'properties': {
                                'order_type': {'type': 'string'},
                                'is_offer_sent': {'type': 'boolean'},
                                'order': {'type': 'object'},
                            },
                        },
                    },
                    'standard': {
                        'type': 'array',
                        'items': {
                            'type': 'object',
                            'properties': {
                                'order_type': {'type': 'string'},
                                'order': {'type': 'object'},
                            },
                        },
                    },
                },
            },
            403: {'type': 'object', 'properties': {'error': {'type': 'string'}}},
        },
    )
    def get(self, request):
        master = request.user.master_profiles.first()
        if not master:
            return Response({'error': 'User is not a master'}, status=status.HTTP_403_FORBIDDEN)

        swept = expire_stale_master_offers()
        sos_ids = order_ids_sos_currently_offered_to_master(master.id)
        custom_ids = pending_custom_request_order_ids_for_master(master)
        standard_ids = pending_assigned_standard_order_ids_for_master(master.id)
        id_set = set(sos_ids) | set(custom_ids) | set(standard_ids)
        order_map: dict[int, Order] = {}
        if id_set:
            order_map = {
                o.id: o
                for o in Order.objects.select_related('user', 'master', 'master__user').prefetch_related(
                    'images',
                    'category',
                    'category__parent',
                    'car',
                    'car__category',
                ).filter(pk__in=id_set)
            }

        sos_orders = [order_map[i] for i in sos_ids if i in order_map]
        custom_orders = [order_map[i] for i in custom_ids if i in order_map]
        standard_orders = [order_map[i] for i in standard_ids if i in order_map]
        sos_orders.sort(key=lambda o: (o.master_response_deadline is None, o.master_response_deadline))
        custom_orders.sort(key=lambda o: o.created_at, reverse=True)
        standard_orders.sort(key=lambda o: (o.master_response_deadline is None, o.master_response_deadline))

        return Response(
            {
                'stale_offers_swept': swept,
                'server_time': timezone.now().isoformat(),
                'sos': _incoming_sync_typed_items(sos_orders, request),
                'custom_request': _incoming_sync_custom_request_typed_items(custom_orders, request, master),
                'standard': _incoming_sync_typed_items(standard_orders, request),
            }
        )


class UpdateOrderStatusView(APIView):
    """
    Строгий workflow: мастер — accepted → on_the_way → arrived → in_progress
    (для проверки дистанции: lat/lon в теле опционально — иначе из профиля Master / user).
    Standard: перед **on_the_way** должен быть задан **preferred_time_end** (PATCH preferred-time после accept).
    **completed** через этот endpoint запрещён — только **POST /complete/** с PIN.
    Клиент / мастер — отмена: предпочтительно **POST /api/order/{id}/cancel/**. Здесь `status=cancelled` для совместимости.
    """

    permission_classes = [IsAuthenticated, IsOrderOwnerOrMaster]

    @extend_schema(
        summary="Обновить статус заказа (workflow)",
        description=(
            'Мастер: on_the_way (опционально eta_minutes или estimated_arrival_at — ETA для клиента), '
            'arrived, in_progress (для in_progress — опционально latitude/longitude; '
            'если не переданы, берутся из профиля Master, иначе из аккаунта пользователя; '
            'расстояние до точки заказа ≤ ORDER_START_JOB_MAX_DISTANCE_M). '
            'Отмена мастером: status=cancelled, cancel_reason. '
            'Клиент: status=cancelled. '
            'После N ч «в пути» (Celery / таймер) — client_penalty_free_cancel_unlocked и отмена без штрафа. '
            'В in_progress отмена клиентом запрещена (см. cancellation в Order). '
            'После перехода в in_progress клиенту выдаётся 4-значный PIN (поле client_completion_pin в заказе); '
            'завершение только мастером: POST /complete/ с completion_pin.'
        ),
        tags=[STAG_ORDER_STATUS],
        parameters=[
            {'name': 'order_id', 'in': 'path', 'description': 'Order ID', 'type': 'integer', 'required': True},
        ],
        request={
            'application/json': {
                'type': 'object',
                'required': ['status'],
                'properties': {
                    'status': {
                        'type': 'string',
                        'enum': [c[0] for c in OrderStatus.choices],
                    },
                    'latitude': {
                        'type': 'number',
                        'description': 'Опционально для in_progress; иначе — координаты из профиля мастера / user',
                    },
                    'longitude': {
                        'type': 'number',
                        'description': 'Опционально для in_progress; иначе — координаты из профиля мастера / user',
                    },
                    'cancel_reason': {
                        'type': 'string',
                        'description': 'При отмене мастером: client_request, vehicle_unavailable, duplicate, emergency, other',
                    },
                    'eta_minutes': {
                        'type': 'integer',
                        'description': 'Опционально при on_the_way: минут до прибытия (1…ORDER_ETA_MAX_MINUTES).',
                    },
                    'estimated_arrival_at': {
                        'type': 'string',
                        'format': 'date-time',
                        'description': 'Опционально при on_the_way: ожидаемое время прибытия (ISO 8601). Имеет приоритет над eta_minutes.',
                    },
                },
            }
        },
        responses={
            200: OrderSerializer,
            400: {'type': 'object', 'properties': {'error': {'type': 'string'}}},
            404: {'type': 'object', 'properties': {'error': {'type': 'string'}}},
            401: {'type': 'object', 'properties': {'detail': {'type': 'string'}}},
            403: {'type': 'object', 'properties': {'detail': {'type': 'string'}}},
        },
    )
    def post(self, request, order_id):
        expire_stale_master_offers()
        try:
            order = Order.objects.get(id=order_id)
            self.check_object_permissions(request, order)
        except Order.DoesNotExist:
            return Response({'error': 'Order not found'}, status=status.HTTP_404_NOT_FOUND)

        new_status = request.data.get('status')
        if not new_status:
            return Response({'error': 'Status is required'}, status=status.HTTP_400_BAD_REQUEST)
        if new_status not in [c[0] for c in OrderStatus.choices]:
            return Response({'error': 'Invalid status'}, status=status.HTTP_400_BAD_REQUEST)

        if new_status == OrderStatus.COMPLETED:
            return Response(
                {
                    'error': 'Do not set status to completed here. '
                    'Use POST /api/order/<order_id>/complete/ with completion_pin.',
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        master = request.user.master_profiles.first()
        is_assigned_master = bool(master and order.master_id == master.id)
        is_owner = order.user_id == request.user.id
        now = timezone.now()

        if new_status in (OrderStatus.REJECTED, OrderStatus.PENDING):
            return Response(
                {'error': 'Use /accept/ or /decline/ for these statuses.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        extra_response = {}

        if new_status == OrderStatus.CANCELLED:
            if is_owner:
                snap = client_cancellation_snapshot(order)
                if not snap['client_can_cancel']:
                    return Response(
                        {'error': snap['summary'], 'cancellation': snap},
                        status=status.HTTP_400_BAD_REQUEST,
                    )
                extra_response['cancellation_penalty_applies'] = snap['penalty_applies']
                extra_response['cancellation_penalty_percent'] = snap['penalty_percent']
                extra_response['order_total'] = order_payable_total_str(order)
                extra_response['penalty_amount_estimate'] = estimate_cancellation_penalty_amount(
                    order, snap['penalty_percent'] if snap['penalty_applies'] else 0
                )
                order.status = OrderStatus.CANCELLED
                order.client_penalty_free_cancel_unlocked = False
                order.estimated_arrival_at = None
                order.eta_minutes = None
                clear_completion_pin(order)
                order.save()
                data = OrderSerializer(order, context={'request': request}).data
                data.update(extra_response)
                return Response(data)

            if is_assigned_master:
                reason = request.data.get('cancel_reason')
                ok, err_msg = validate_master_cancel(order, master, reason)
                if not ok:
                    return Response({'error': err_msg}, status=status.HTTP_400_BAD_REQUEST)
                MasterOrderCancellation.objects.create(master=master, order=order, reason=reason)
                order.status = OrderStatus.CANCELLED
                order.client_penalty_free_cancel_unlocked = False
                order.estimated_arrival_at = None
                order.eta_minutes = None
                clear_completion_pin(order)
                order.save()
                return Response(OrderSerializer(order, context={'request': request}).data)

            return Response({'error': 'Not allowed to cancel'}, status=status.HTTP_403_FORBIDDEN)

        if not is_assigned_master:
            return Response(
                {'error': 'Only the assigned master can change workflow status.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if order.status == OrderStatus.ACCEPTED and new_status == OrderStatus.ON_THE_WAY:
            if order.order_type == OrderType.STANDARD and order.preferred_time_end is None:
                return Response(
                    {
                        'error': 'Set preferred_time_end before marking on the way '
                        '(PATCH /api/order/<order_id>/preferred-time/).',
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )
            est, em, eta_err = resolve_on_the_way_eta(request.data, now)
            if eta_err:
                eta_messages = {
                    'invalid_estimated_arrival_at': 'Invalid estimated_arrival_at (expected ISO datetime).',
                    'estimated_arrival_in_past': 'estimated_arrival_at cannot be in the past.',
                    'estimated_arrival_too_far': 'Arrival time is too far ahead (see ORDER_ETA_MAX_MINUTES).',
                    'invalid_eta_minutes': 'eta_minutes: provide an integer from 1 to ORDER_ETA_MAX_MINUTES.',
                }
                return Response(
                    {'error': eta_messages.get(eta_err, eta_err)},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            if est is None and em is None:
                est, em = auto_eta_from_order_master(order, master, now)
            order.status = OrderStatus.ON_THE_WAY
            order.on_the_way_at = now
            order.client_penalty_free_cancel_unlocked = False
            order.estimated_arrival_at = est
            order.eta_minutes = em
            order.save(
                update_fields=[
                    'status',
                    'on_the_way_at',
                    'client_penalty_free_cancel_unlocked',
                    'estimated_arrival_at',
                    'eta_minutes',
                    'updated_at',
                ]
            )
            schedule_client_penalty_free_unlock(order.pk, order.on_the_way_at)
            return Response(OrderSerializer(order, context={'request': request}).data)

        if order.status == OrderStatus.ON_THE_WAY and new_status == OrderStatus.ARRIVED:
            order.status = OrderStatus.ARRIVED
            order.arrived_at = now
            order.client_penalty_free_cancel_unlocked = False
            order.estimated_arrival_at = None
            order.eta_minutes = None
            order.save(
                update_fields=[
                    'status',
                    'arrived_at',
                    'client_penalty_free_cancel_unlocked',
                    'estimated_arrival_at',
                    'eta_minutes',
                    'updated_at',
                ]
            )
            return Response(OrderSerializer(order, context={'request': request}).data)

        if order.status == OrderStatus.ARRIVED and new_status == OrderStatus.IN_PROGRESS:
            if order.latitude is None or order.longitude is None:
                return Response(
                    {'error': 'Order has no client coordinates; distance cannot be verified.'},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            mlat, mlon, coord_err = resolve_master_coordinates_for_start_job(master, request.data)
            if coord_err == 'partial_coords':
                return Response(
                    {
                        'error': 'Send both latitude and longitude, or omit both '
                        '(then master/user profile coordinates are used).',
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )
            if coord_err == 'invalid_coords':
                return Response(
                    {'error': 'Invalid latitude or longitude in the request.'},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            if coord_err == 'no_master_coords' or mlat is None or mlon is None:
                return Response(
                    {
                        'error': 'No master coordinates: pass latitude/longitude in the request '
                        'or set them on the master or user profile.',
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )
            dist_m = haversine_distance_m(
                mlat,
                mlon,
                float(order.latitude),
                float(order.longitude),
            )
            max_m = int(getattr(settings, 'ORDER_START_JOB_MAX_DISTANCE_M', 300))
            if dist_m > max_m:
                return Response(
                    {
                        'error': f'Too far from the client ({round(dist_m, 1)} m). '
                        f'Maximum {max_m} m after status arrived.',
                        'distance_meters': round(dist_m, 1),
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )
            order.status = OrderStatus.IN_PROGRESS
            order.work_started_at = now
            order.estimated_arrival_at = None
            order.eta_minutes = None
            issue_completion_pin(order)
            order.save(
                update_fields=[
                    'status',
                    'work_started_at',
                    'estimated_arrival_at',
                    'eta_minutes',
                    'completion_pin',
                    'completion_pin_issued_at',
                    'updated_at',
                ]
            )
            return Response(OrderSerializer(order, context={'request': request}).data)

        return Response(
            {'error': f'Invalid transition {order.status} → {new_status}.'},
            status=status.HTTP_400_BAD_REQUEST,
        )


class CancelOrderView(APIView):
    """
    Явная отмена заказа (клиент или назначенный мастер).
    Для клиента: правила и оценка штрафа — ``cancellation`` + ``penalty_amount_estimate`` (от ``pricing.total``).
    """

    permission_classes = [IsAuthenticated, IsOrderOwnerOrMaster]

    @extend_schema(
        summary='Отменить заказ',
        description="""
**Владелец (driver):** тело можно пустым. Проверяются правила из ``cancellation`` на заказе; при ``in_progress`` — 400.

**Назначенный мастер:** передайте ``cancel_reason``: client_request, vehicle_unavailable, duplicate, emergency, other.
Причина ``too_far`` (слишком далеко) **запрещена** — мастер сам задаёт зону и радиус.

Первые **3** отмены принятого заказа в календарном месяце не ограничивают планирование расписания.
С **4-й** отмены в месяц: расписание и слоты только до **10** календарных дней вперёд; с **5-й** — до **5** дней; с **6-й** — только **текущий** день (см. ``POST /api/master/schedule/``, слоты ``GET /api/order/available-slots/``).

Ответ включает заказ (``OrderSerializer``) и поля оценки штрафа для клиента (для мастера штраф клиента не считается).
        """,
        tags=[STAG_ORDER_STATUS],
        parameters=[
            {'name': 'order_id', 'in': 'path', 'description': 'Order ID', 'type': 'integer', 'required': True},
        ],
        request=CancelOrderRequestSerializer,
        responses={
            200: OrderSerializer,
            400: {'type': 'object', 'properties': {'error': {'type': 'string'}, 'cancellation': {'type': 'object'}}},
            403: {'type': 'object', 'properties': {'detail': {'type': 'string'}, 'error': {'type': 'string'}}},
            404: {'type': 'object', 'properties': {'error': {'type': 'string'}}},
        },
    )
    def post(self, request, order_id):
        expire_stale_master_offers()
        try:
            order = Order.objects.get(id=order_id)
            self.check_object_permissions(request, order)
        except Order.DoesNotExist:
            return Response({'error': 'Order not found'}, status=status.HTTP_404_NOT_FOUND)

        master = request.user.master_profiles.first()
        is_assigned_master = bool(master and order.master_id == master.id)
        is_owner = order.user_id == request.user.id

        if is_owner:
            snap = client_cancellation_snapshot(order)
            if not snap['client_can_cancel']:
                return Response(
                    {'error': snap['summary'], 'cancellation': snap},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            order.status = OrderStatus.CANCELLED
            order.client_penalty_free_cancel_unlocked = False
            order.estimated_arrival_at = None
            order.eta_minutes = None
            clear_completion_pin(order)
            order.save()
            data = OrderSerializer(order, context={'request': request}).data
            data['cancellation_penalty_applies'] = snap['penalty_applies']
            data['cancellation_penalty_percent'] = snap['penalty_percent']
            data['order_total'] = order_payable_total_str(order)
            data['penalty_amount_estimate'] = estimate_cancellation_penalty_amount(
                order, snap['penalty_percent'] if snap['penalty_applies'] else 0
            )
            return Response(data)

        if is_assigned_master:
            reason = request.data.get('cancel_reason')
            ok, err_msg = validate_master_cancel(order, master, reason)
            if not ok:
                return Response({'error': err_msg}, status=status.HTTP_400_BAD_REQUEST)
            MasterOrderCancellation.objects.create(master=master, order=order, reason=reason)
            order.status = OrderStatus.CANCELLED
            order.client_penalty_free_cancel_unlocked = False
            order.estimated_arrival_at = None
            order.eta_minutes = None
            clear_completion_pin(order)
            order.save()
            return Response(
                {
                    'message': 'Order cancelled by master.',
                    'order': OrderSerializer(order, context={'request': request}).data,
                }
            )

        return Response({'error': 'Not allowed to cancel'}, status=status.HTTP_403_FORBIDDEN)


class AcceptOrderView(APIView):
    """
    API для принятия заказа в работу
    """
    permission_classes = [IsAuthenticated, IsMaster]
    
    @extend_schema(
        summary="Принять заказ в работу",
        description="""
Принимает заказ в работу (статус **accepted**). Списание с баланса мастера при accept **не выполняется**.
        """,
        tags=[STAG_ORDER_MASTER_AVAILABLE],
        parameters=[
            {'name': 'order_id', 'in': 'path', 'description': 'Order ID', 'type': 'integer', 'required': True},
        ],
        responses={
            200: {
                'type': 'object',
                'properties': {
                    'message': {'type': 'string'},
                    'order': {'type': 'object'},
                }
            },
            400: {
                'type': 'object',
                'properties': {
                    'error': {'type': 'string'},
                }
            },
            404: {'type': 'object', 'properties': {'error': {'type': 'string'}}},
            401: {'type': 'object', 'properties': {'detail': {'type': 'string'}}},
            403: {'type': 'object', 'properties': {'detail': {'type': 'string'}}},
        }
    )
    def post(self, request, order_id):
        """Принять заказ в работу"""
        try:
            oid = int(order_id)
        except (TypeError, ValueError):
            return Response({'error': 'Invalid order_id'}, status=status.HTTP_400_BAD_REQUEST)
        expire_stale_master_offers(skip_order_ids={oid})

        master = request.user.master_profiles.first()
        if not master:
            return Response(
                {'error': 'Only a master can accept the order'},
                status=status.HTTP_403_FORBIDDEN,
            )

        try:
            with transaction.atomic():
                order = Order.objects.select_for_update().get(id=oid)

                if order.status != OrderStatus.PENDING:
                    return Response(
                        {
                            'error': 'Only orders in pending status can be accepted (awaiting master response)',
                        },
                        status=status.HTTP_400_BAD_REQUEST,
                    )

                if order.order_type == OrderType.SOS and order.sos_offer_queue:
                    if not master_eligible_for_pending_sos_offer(order, master.id):
                        return Response(
                            {
                                'error': 'You are not in the SOS queue, already declined, outside acceptance zone, or the order is unavailable',
                            },
                            status=status.HTTP_400_BAD_REQUEST,
                        )
                elif not order.master_id or order.master_id != master.id:
                    return Response(
                        {
                            'error': 'This order is assigned to another master or no master is assigned yet',
                        },
                        status=status.HTTP_400_BAD_REQUEST,
                    )

                if order.master_response_deadline and timezone.now() > order.master_response_deadline:
                    if order.order_type == OrderType.SOS:
                        msg = (
                            'The SOS response window has expired. The order was cancelled or already accepted by another master.'
                        )
                    else:
                        msg = 'The response deadline has passed. This order is no longer available to accept.'
                    return Response({'error': msg}, status=status.HTTP_400_BAD_REQUEST)

                if order.is_expired():
                    order.mark_as_cancelled_if_expired()
                    return Response(
                        {'error': 'Order expired and was cancelled'},
                        status=status.HTTP_400_BAD_REQUEST,
                    )

                order.master = master
                order.status = OrderStatus.ACCEPTED
                order.accepted_at = timezone.now()
                order.master_response_deadline = None
                order.sos_offer_queue = []
                order.sos_offer_index = 0
                order.sos_declined_master_ids = []
                order.save(
                    update_fields=[
                        'master',
                        'status',
                        'accepted_at',
                        'master_response_deadline',
                        'sos_offer_queue',
                        'sos_offer_index',
                        'sos_declined_master_ids',
                        'updated_at',
                    ]
                )
                from apps.order.services.order_category_services import sync_order_services_from_order_categories

                sync_order_services_from_order_categories(order)

            order.refresh_from_db()
            serializer = OrderSerializer(order, context={'request': request})
            return Response(
                {
                    'message': 'Заказ принят. Далее: «В пути» → «Прибыл» → «Начать работу».',
                    'order': serializer.data,
                }
            )

        except Order.DoesNotExist:
            return Response(
                {'error': 'Order not found'}, 
                status=status.HTTP_404_NOT_FOUND
            )


class DeclineOrderView(APIView):
    """
    Мастер отклоняет назначенную заявку до принятия (не нарушение).
    """

    permission_classes = [IsAuthenticated, IsMaster]

    @extend_schema(
        summary='Отклонить заявку (до Accept)',
        description="""
Доступно только назначенному мастеру, пока заказ **`pending`**.
После отклонения: `rejected`, мастер снимается; клиент может создать новый запрос / выбрать другого мастера.
        """,
        tags=[STAG_ORDER_MASTER_AVAILABLE],
        responses={
            200: OrderSerializer,
            400: {'type': 'object', 'properties': {'error': {'type': 'string'}}},
            403: {'type': 'object', 'properties': {'error': {'type': 'string'}}},
            404: {'type': 'object', 'properties': {'error': {'type': 'string'}}},
        },
    )
    def post(self, request, order_id):
        try:
            oid = int(order_id)
        except (TypeError, ValueError):
            return Response({'error': 'Invalid order_id'}, status=status.HTTP_400_BAD_REQUEST)
        expire_stale_master_offers(skip_order_ids={oid})
        try:
            order = Order.objects.get(id=oid)
        except Order.DoesNotExist:
            return Response({'error': 'Order not found'}, status=status.HTTP_404_NOT_FOUND)

        master = request.user.master_profiles.first()
        if not master:
            return Response({'error': 'Master account required'}, status=status.HTTP_403_FORBIDDEN)

        if order.status != OrderStatus.PENDING:
            return Response(
                {'error': 'Only orders in pending status can be declined'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if order.order_type == OrderType.SOS and order.sos_offer_queue:
            if not master_in_sos_broadcast_queue(order, master.id):
                return Response(
                    {'error': 'This SOS offer is not in your queue'},
                    status=status.HTTP_400_BAD_REQUEST,
                )
        elif order.master_id != master.id:
            return Response(
                {'error': 'Order is assigned to another master'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if order.order_type == OrderType.SOS and order.sos_offer_queue:
            if not sos_broadcast_decline(order, master.id):
                return Response(
                    {'error': 'Could not record SOS decline'},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            order.refresh_from_db()
            return Response(
                OrderSerializer(order, context={'request': request}).data,
                status=status.HTTP_200_OK,
            )

        order.status = OrderStatus.REJECTED
        order.master = None
        order.master_response_deadline = None
        order.save(update_fields=['status', 'master', 'master_response_deadline', 'updated_at'])
        return Response(
            OrderSerializer(order, context={'request': request}).data,
            status=status.HTTP_200_OK,
        )


class OrderMasterPreferredTimePatchView(APIView):
    """Master only: set preferred_time_end after accept (preferred_time_start from client on create)."""

    permission_classes = [IsAuthenticated, IsMaster]

    @extend_schema(
        summary='Предпочтительное время окончания (мастер, после accept)',
        description=(
            'Только **standard** заказ, статус **accepted**, назначенный мастер. '
            'Клиент при создании передаёт `preferred_date` + `preferred_time_start`; '
            'в теле запроса только **`preferred_time_end`**.'
        ),
        tags=[STAG_ORDER_MASTER_AVAILABLE],
        parameters=[
            {'name': 'order_id', 'in': 'path', 'required': True, 'schema': {'type': 'integer'}},
        ],
        request=OrderMasterPreferredTimePatchSerializer,
        responses={200: OrderSerializer},
    )
    def patch(self, request, order_id):
        master = request.user.master_profiles.first()
        if not master:
            return Response({'error': 'Master account required'}, status=status.HTTP_403_FORBIDDEN)
        try:
            order = Order.objects.get(id=order_id)
        except Order.DoesNotExist:
            return Response({'error': 'Order not found'}, status=status.HTTP_404_NOT_FOUND)

        if order.order_type != OrderType.STANDARD:
            return Response(
                {'error': 'Only for standard orders'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if order.status != OrderStatus.ACCEPTED:
            return Response(
                {'error': 'Only available when order status is accepted'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if order.master_id != master.id:
            return Response(
                {'error': 'Order is assigned to another master'},
                status=status.HTTP_403_FORBIDDEN,
            )

        ser = OrderMasterPreferredTimePatchSerializer(
            data=request.data,
            context={'order': order},
        )
        if not ser.is_valid():
            return Response(ser.errors, status=status.HTTP_400_BAD_REQUEST)

        order.preferred_time_end = ser.validated_data['preferred_time_end']
        order.save(update_fields=['preferred_time_end', 'updated_at'])
        return Response(OrderSerializer(order, context={'request': request}).data)


class CompleteOrderView(APIView):
    """
    Завершение заказа только назначенным мастером: в теле JSON обязателен **completion_pin**
    (4 цифры, клиент видит код в приложении пока заказ **in_progress**).
    """

    permission_classes = [IsAuthenticated]

    @extend_schema(
        summary="Завершить заказ (мастер + PIN клиента)",
        description="""
Только **назначенный мастер**. Статус заказа — **in_progress**, загружено ≥1 фото работы.

В теле передайте **completion_pin** — 4-значный код, который клиент видит в своём приложении
(поле **client_completion_pin** в ответе заказа для владельца).

Клиент не может завершить заказ через этот endpoint.
        """,
        tags=[STAG_ORDER_MASTER_COMPLETE],
        parameters=[
            {'name': 'order_id', 'in': 'path', 'description': 'Order ID', 'type': 'integer', 'required': True},
        ],
        request={
            'application/json': {
                'type': 'object',
                'required': ['completion_pin'],
                'properties': {
                    'completion_pin': {
                        'type': 'string',
                        'description': '4-digit code from the client app',
                        'example': '4242',
                    },
                },
            }
        },
        responses={
            200: {
                'type': 'object',
                'properties': {
                    'message': {'type': 'string', 'example': 'Order completed successfully'},
                    'order': {'$ref': '#/components/schemas/Order'},
                },
            },
            400: {'type': 'object', 'properties': {'error': {'type': 'string'}}},
            403: {'type': 'object', 'properties': {'error': {'type': 'string'}, 'detail': {'type': 'string'}}},
            404: {'type': 'object', 'properties': {'error': {'type': 'string'}}},
            401: {
                'type': 'object',
                'properties': {'detail': {'type': 'string'}},
            },
        },
    )
    def post(self, request, order_id):
        """Завершить заказ: только мастер, с PIN от клиента."""
        expire_stale_master_offers()
        try:
            order = Order.objects.get(id=order_id)
            master = request.user.master_profiles.first()

            if order.user_id == request.user.id and not master:
                return Response(
                    {
                        'error': 'Only the assigned master can complete the order. '
                        'Show the completion code (client_completion_pin) to the master.',
                    },
                    status=status.HTTP_403_FORBIDDEN,
                )

            if not master or order.master_id != master.id:
                return Response({'error': 'Access denied'}, status=status.HTTP_403_FORBIDDEN)

            if order.status != OrderStatus.IN_PROGRESS:
                return Response(
                    {
                        'error': 'You can complete the order only when status is in_progress. '
                        'Finish the workflow first, then call this endpoint.',
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

            if not order.work_completion_images.exists():
                return Response(
                    {
                        'error': 'Upload at least one work completion photo '
                        '(POST /api/order/{id}/work-completion-image/) before completing.',
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

            raw_pin = request.data.get('completion_pin')
            if raw_pin is None:
                return Response(
                    {'error': 'completion_pin is required (4-digit code from the client).'},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            pin_s = ''.join(ch for ch in str(raw_pin).strip() if ch.isdigit())
            if len(pin_s) != 4:
                return Response(
                    {'error': 'completion_pin must be exactly 4 digits.'},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            expected = (order.completion_pin or '').strip()
            if len(expected) != 4:
                return Response(
                    {
                        'error': 'No valid completion PIN on this order. '
                        'Ask the client to refresh the order or contact support.',
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

            if not secrets.compare_digest(expected, pin_s):
                return Response(
                    {'error': 'Invalid completion PIN.'},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            order.status = OrderStatus.COMPLETED
            clear_completion_pin(order)
            order.save(
                update_fields=[
                    'status',
                    'completion_pin',
                    'completion_pin_issued_at',
                    'updated_at',
                ]
            )

            serializer = OrderSerializer(order, context={'request': request})
            return Response(
                {
                    'message': 'Order completed successfully',
                    'order': serializer.data,
                },
                status=status.HTTP_200_OK,
            )

        except Order.DoesNotExist:
            return Response(
                {'error': 'Order not found'},
                status=status.HTTP_404_NOT_FOUND,
            )


class UploadOrderWorkCompletionImageView(APIView):
    """Master uploads work-completion photos (≥1 total on order before POST /complete/). Multipart: repeat **`images`**."""

    permission_classes = [IsAuthenticated, IsMaster]
    parser_classes = [MultiPartParser, FormParser]

    @extend_schema(
        summary='Загрузить фото выполненной работы (несколько файлов)',
        description=(
            '**multipart/form-data**: repeat field **`images`** for each file. '
            'Legacy single field **`image`** is still accepted once. '
            'Max files per request: **WORK_COMPLETION_MAX_IMAGES_PER_REQUEST** (default 20).'
        ),
        tags=[STAG_ORDER_MASTER_COMPLETE],
        request={
            'multipart/form-data': {
                'type': 'object',
                'properties': {
                    'images': {'type': 'array', 'items': {'type': 'string', 'format': 'binary'}},
                    'image': {'type': 'string', 'format': 'binary', 'description': 'Legacy single file'},
                },
            }
        },
        responses={201: OrderSerializer, 400: {'type': 'object'}, 403: {'type': 'object'}},
    )
    def post(self, request, order_id):
        expire_stale_master_offers()
        master = request.user.master_profiles.first()
        if not master:
            return Response({'error': 'Master account required'}, status=status.HTTP_403_FORBIDDEN)
        try:
            order = Order.objects.get(pk=order_id)
        except Order.DoesNotExist:
            return Response({'error': 'Order not found'}, status=status.HTTP_404_NOT_FOUND)
        if order.master_id != master.id:
            return Response({'error': 'This is not your order'}, status=status.HTTP_403_FORBIDDEN)
        if order.status not in MASTER_ACTIVE_WORK_STATUSES:
            return Response(
                {'error': 'Photos can be added after the order is accepted and until it is completed.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        files = [f for f in request.FILES.getlist('images') if f]
        if not files:
            one = request.FILES.get('image')
            if one:
                files = [one]
        if not files:
            return Response(
                {'error': 'Pass one or more files as `images` (repeat field) or a single `image`.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        max_per = int(getattr(settings, 'WORK_COMPLETION_MAX_IMAGES_PER_REQUEST', 20))
        if len(files) > max_per:
            return Response(
                {'error': f'At most {max_per} images per request.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        with transaction.atomic():
            for f in files:
                OrderWorkCompletionImage.objects.create(order=order, image=f)

        order.refresh_from_db()
        return Response(OrderSerializer(order, context={'request': request}).data, status=status.HTTP_201_CREATED)


class CreateReviewView(APIView):
    """POST review: multipart (tags) or JSON. Work photos use **`POST .../work-completion-image/`** only."""

    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    @extend_schema(
        summary='Create order review (multipart or JSON; multiple tags)',
        description="""
Submit as **`multipart/form-data`** or JSON:

- **`order_id`**, **`rating`**, **`tags`** (one or more — JSON string array, CSV, or repeated form fields), optional **`comment`**.

Work completion photos are **not** attached here — use **`POST /api/order/{order_id}/work-completion-image/`** with repeated **`images`**.

Response: **`tags`**, **`tags_detail`**, absolute URLs on nested media where applicable.
        """,
        tags=[STAG_ORDER_DRIVER_REVIEWS],
        request=ReviewCreateSerializer,
        responses={
            201: ReviewSerializer,
            400: {
                'type': 'object',
                'properties': {'error': {'type': 'string'}},
                'examples': {
                    'not_completed': {'value': {'error': 'Reviews are only allowed for completed orders'}},
                    'already_exists': {'value': {'error': 'A review for this order already exists'}},
                },
            },
            404: {
                'type': 'object',
                'properties': {'error': {'type': 'string'}},
                'example': {'error': 'Order not found'},
            },
            401: {
                'type': 'object',
                'properties': {'detail': {'type': 'string'}},
            },
        },
    )
    def post(self, request):
        ct = (request.content_type or '').lower()
        if 'multipart/form-data' in ct:
            data = normalize_review_create_request_data(request)
        else:
            data = dict(request.data)
            if isinstance(data.get('tags'), str):
                data['tags'] = _coerce_tag_string_list(data['tags'])

        serializer = ReviewCreateSerializer(data=data, context={'request': request})
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        order_id = serializer.validated_data['order_id']
        order = Order.objects.get(id=order_id)
        rating = serializer.validated_data['rating']
        comment = serializer.validated_data.get('comment') or ''
        tags = serializer.validated_data['tags']

        review = Review.objects.create(
            order=order,
            reviewer=request.user,
            rating=rating,
            comment=comment,
            tags=tags,
        )

        review = Review.objects.select_related('order', 'reviewer').get(pk=review.pk)
        result_serializer = ReviewSerializer(review, context={'request': request})
        return Response(
            {
                'message': 'Review created successfully. Rating applied to masters.',
                'review': result_serializer.data,
            },
            status=status.HTTP_201_CREATED,
        )


def _get_area_filter_for_orders(request):
    """Получение фильтра по прямоугольной области для orders_by_master - Order model ichidagi lat/long bilan"""
    # Получаем параметры точек
    point_params = {
        'point1': (request.query_params.get('point1_lat'), request.query_params.get('point1_lon')),
        'point2': (request.query_params.get('point2_lat'), request.query_params.get('point2_lon')),
        'point3': (request.query_params.get('point3_lat'), request.query_params.get('point3_lon')),
        'point4': (request.query_params.get('point4_lat'), request.query_params.get('point4_lon'))
    }
    
    # Проверяем, что все параметры переданы
    all_params = [param for point in point_params.values() for param in point]
    
    # Agar heч qanday parametr berilmagan bo'lsa, None qaytar
    if not any(all_params):
        return None
    
    # Agar ba'zi parametrlar berilgan bo'lsa, lekin barchasi emas bo'lsa, None qaytar
    if not all(all_params):
        return None
    
    # Валидируем и преобразуем координаты
    points = []
    for point_name, (lat_str, lon_str) in point_params.items():
        try:
            lat = float(lat_str)
            lon = float(lon_str)
            # Order model uchun coordinate validation
            if not (-90 <= lat <= 90):
                return None
            if not (-180 <= lon <= 180):
                return None
            points.append((lat, lon))
        except (ValueError, TypeError):
            return None
    
    # Вычисляем границы прямоугольника
    lats = [point[0] for point in points]
    lons = [point[1] for point in points]
    
    min_lat = min(lats)
    max_lat = max(lats)
    min_lon = min(lons)
    max_lon = max(lons)
    
    # Order model ichidagi latitude va longitude bilan filter qilamiz
    return {
        'latitude__gte': min_lat,
        'latitude__lte': max_lat,
        'longitude__gte': min_lon,
        'longitude__lte': max_lon
    }


class AvailableOrdersForMasterView(APIView):
    """
    API для получения доступных заказов для мастера
    Показывает заказы без назначенного мастера в радиусе от мастера
    """
    permission_classes = [IsAuthenticated]
    pagination_class = OrderPagination
    
    def calculate_distance(self, lat1, lon1, lat2, lon2):
        """
        Вычисление расстояния между двумя точками по формуле Haversine
        Возвращает расстояние в километрах
        """
        from math import radians, sin, cos, sqrt, atan2
        
        # Радиус Земли в километрах
        R = 6371.0
        
        # Конвертируем градусы в радианы
        lat1_rad = radians(lat1)
        lon1_rad = radians(lon1)
        lat2_rad = radians(lat2)
        lon2_rad = radians(lon2)
        
        # Разница координат
        dlat = lat2_rad - lat1_rad
        dlon = lon2_rad - lon1_rad
        
        # Формула Haversine
        a = sin(dlat / 2)**2 + cos(lat1_rad) * cos(lat2_rad) * sin(dlon / 2)**2
        c = 2 * atan2(sqrt(a), sqrt(1 - a))
        
        distance = R * c
        return distance
    
    @extend_schema(
        summary="Получить доступные заказы для мастера",
        description="""
## Описание
Возвращает список доступных заказов (без назначенного мастера) в радиусе от местоположения мастера.

## Обязательные параметры
- **master_id** - ID мастера (координаты берутся из профиля мастера)

## Необязательные параметры
- **radius** - Радиус поиска в **милях**, если у мастера нет `service_area_radius_miles` (по умолчанию 10 mi)

## Фильтры (все необязательные)

### 1. Тип проблемы (category)
- ID категории типа **by_order**
- Использует **smart filter** через дерево parent категории
- Пример: `category=1` — заказы с той же категорией, соседями (общий parent), родителем или дочерними

### 2. Район (location)
- Поиск по адресу заказа
- Пример: `location=Ташкент` или `location=Навои`
- Поиск нечувствителен к регистру (case-insensitive)

### 3. Тип ТС (car_category)
- ID категории машины типа **by_car**
- Прямой фильтр по ID
- Пример: `car_category=3` (где 3 - это "Легковой")

### 4. Приоритет (priority)
- Уровень приоритета заказа
- Значения: `low` (низкий) или `high` (высокий)
- Пример: `priority=high`

## Логика работы
1. Базовая точка: координаты мастера на карте (`latitude` / `longitude`).
2. Радиус: если задан **service_area_radius_miles** (15/45/100), используется он (перевод в км); иначе query-параметр **radius** (**мили**, по умолчанию 10).
3. Заказы без назначенного master (FK пустой), с координатами.
4. Доп. фильтры: category, location, car_category, priority; расстояние Haversine; сортировка по расстоянию.

## Pagination
- По умолчанию 10 заказов на страницу
- Можно изменить через `page_size` (макс. 100)
- Навигация через `page` (номер страницы)

## Примеры запросов

**Базовый (только обязательные параметры):**
```
GET /api/order/available/?master_id=5
```

**С радиусом:**
```
GET /api/order/available/?master_id=5&radius=20
```

**С фильтром по проблеме:**
```
GET /api/order/available/?master_id=5&radius=15&category=1
```

**С несколькими фильтрами:**
```
GET /api/order/available/?master_id=5&radius=15&category=1&location=Ташкент&car_category=3&priority=high
```

**С пагинацией:**
```
GET /api/order/available/?master_id=5&radius=10&page=2&page_size=20
```
        """,
        tags=[STAG_ORDER_MASTER_AVAILABLE],
        parameters=[
            OpenApiParameter(
                name='master_id',
                type=OpenApiTypes.INT,
                location=OpenApiParameter.QUERY,
                description='ID мастера (обязательно). Точка отсчёта: рабочая зона, иначе профиль.',
                required=True
            ),
            OpenApiParameter(
                name='radius',
                type=OpenApiTypes.FLOAT,
                location=OpenApiParameter.QUERY,
                description='Радиус в милях, если у мастера нет service_area_radius_miles; иначе игнорируется.',
                required=False
            ),
            OpenApiParameter(
                name='category',
                type=OpenApiTypes.INT,
                location=OpenApiParameter.QUERY,
                description='Фильтр по типу проблемы. ID категории by_order. Smart filter по parent-дереву.',
                required=False
            ),
            OpenApiParameter(
                name='location',
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                description='Фильтр по району. Поиск по адресу заказа (например: "Ташкент", "Навои", "ул. Амира Темура").',
                required=False
            ),
            OpenApiParameter(
                name='car_category',
                type=OpenApiTypes.INT,
                location=OpenApiParameter.QUERY,
                description='Фильтр по типу ТС. ID категории машины типа by_car (например: 3 для "Легковой").',
                required=False
            ),
            OpenApiParameter(
                name='priority',
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                description='Фильтр по приоритету. Допустимые значения: "low" (низкий) или "high" (высокий).',
                required=False
            ),
            OpenApiParameter(
                name='page',
                type=OpenApiTypes.INT,
                location=OpenApiParameter.QUERY,
                description='Номер страницы для пагинации. Начинается с 1.',
                required=False
            ),
            OpenApiParameter(
                name='page_size',
                type=OpenApiTypes.INT,
                location=OpenApiParameter.QUERY,
                description='Количество заказов на странице. По умолчанию 10, максимум 100.',
                required=False
            ),
        ],
        responses={
            200: {
                'description': 'Успешный ответ с пагинацией',
                'content': {
                    'application/json': {
                        'example': {
                            'count': 5,
                            'next': 'http://localhost:8000/api/order/available/?master_id=5&page=2',
                            'previous': None,
                            'results': [
                                {
                                    'id': 10,
                                    'user': {
                                        'id': 4,
                                        'private_id': '829137',
                                        'full_name': 'Иван Иванов',
                                        'phone_number': '998914495644',
                                        'email': 'ivan@example.com',
                                        'avatar': 'http://localhost:8000/media/avatars/avatar.jpg'
                                    },
                                    'car_data': [
                                        {
                                            'id': 2,
                                            'brand': 'Toyota',
                                            'model': 'Camry',
                                            'year': 2020,
                                            'category': {'id': 3, 'name': 'Легковой', 'type_category': 'by_car'}
                                        }
                                    ],
                                    'category_data': [
                                        {
                                            'id': 1,
                                            'name': 'Пробито колесо',
                                            'type_category': 'by_order',
                                            'parent': None
                                        }
                                    ],
                                    'text': 'Нужна помощь с заменой колеса',
                                    'status': 'pending',
                                    'priority': 'high',
                                    'location': 'ул. Навои, д. 15, Ташкент',
                                    'latitude': '41.3111000',
                                    'longitude': '69.2797000',
                                    'master': None,
                                    'distance': 2.35,
                                    'created_at': '2026-01-21T12:00:00Z',
                                    'updated_at': '2026-01-21T12:00:00Z'
                                }
                            ]
                        }
                    }
                }
            },
            400: {
                'description': 'Parameter validation error',
                'content': {
                    'application/json': {
                        'examples': {
                            'missing_master_id': {
                                'summary': 'master_id missing',
                                'value': {'error': 'master_id query parameter is required'}
                            },
                            'invalid_format': {
                                'summary': 'Invalid parameter format',
                                'value': {'error': 'Invalid parameter format'}
                            },
                            'no_coordinates': {
                                'summary': 'Master has no coordinates',
                                'value': {'error': 'Master has no coordinates set'}
                            }
                        }
                    }
                }
            },
            401: {
                'description': 'Unauthorized',
                'content': {
                    'application/json': {
                        'example': {'detail': 'Authentication credentials were not provided.'}
                    }
                }
            },
            404: {
                'description': 'Master not found',
                'content': {
                    'application/json': {
                        'example': {'error': 'Master not found'}
                    }
                }
            },
        }
    )
    def get(self, request):
        """Получить доступные заказы для мастера"""
        expire_stale_master_offers()
        # Получаем параметры
        master_id = request.query_params.get('master_id')
        radius = request.query_params.get('radius', 10)  # мили, если нет service_area на мастере
        
        # Валидация обязательных параметров
        if not master_id:
            return Response(
                {'error': 'master_id query parameter is required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            master_id = int(master_id)
            radius = float(radius)
        except (ValueError, TypeError):
            return Response(
                {'error': 'Invalid parameter format'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Проверяем существование мастера
        try:
            master = Master.objects.get(id=master_id)
        except Master.DoesNotExist:
            return Response(
                {'error': 'Master not found'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        master_lat, master_long = master.get_work_location_for_distance()
        if master_lat is None:
            return Response(
                {
                    'error': 'Master has no map coordinates (latitude and longitude)'
                },
                status=status.HTTP_400_BAD_REQUEST
            )

        if master.service_area_radius_miles:
            radius = master.max_order_distance_km()
        else:
            radius = float(radius) * MILES_TO_KM
        
        # Заказы без назначенного master (FK), с координатами (custom_request — только push/WS, не каталог)
        orders = Order.objects.filter(
            master__isnull=True,
            latitude__isnull=False,
            longitude__isnull=False,
        ).exclude(order_type=OrderType.CUSTOM_REQUEST)
        
        # Применяем дополнительные фильтры
        category_filter = request.query_params.get('category')
        location_filter = request.query_params.get('location')
        car_category_filter = request.query_params.get('car_category')
        priority_filter = request.query_params.get('priority')
        
        # Smart фильтр по категории проблемы (Тип проблемы)
        if category_filter:
            try:
                from apps.categories.models import Category
                category_id = int(category_filter)
                category = Category.objects.get(id=category_id)
                
                if category.type_category == 'by_order':
                    orders = orders.filter(order_by_order_category_smart_q(category))
                else:
                    # Для других типов - прямой фильтр по ID
                    orders = orders.filter(category__id=category_id)
                    
            except Category.DoesNotExist:
                pass
            except (ValueError, TypeError):
                pass
        
        # Фильтр по району (location)
        if location_filter:
            orders = orders.filter(location__icontains=location_filter)
        
        # Smart фильтр по типу ТС (car_category)
        if car_category_filter:
            try:
                from apps.categories.models import Category
                car_cat_id = int(car_category_filter)
                car_category = Category.objects.get(id=car_cat_id)
                
                # Прямой фильтр по ID категории машины
                orders = orders.filter(car__category__id=car_cat_id)
                
            except Category.DoesNotExist:
                pass
            except (ValueError, TypeError):
                pass
        
        # Фильтр по приоритету
        if priority_filter:
            orders = orders.filter(priority=priority_filter)
        
        # Убираем дубликаты после фильтров
        orders = orders.distinct()
        
        # Вычисляем расстояние и фильтруем по радиусу
        filtered_orders = []
        for order in orders:
            distance = self.calculate_distance(
                master_lat, master_long,
                float(order.latitude), float(order.longitude)
            )
            
            if distance <= radius:
                # Добавляем расстояние как атрибут
                order.distance = round(distance, 2)
                filtered_orders.append(order)
        
        # Сортируем по расстоянию (ближайшие сначала)
        filtered_orders.sort(key=lambda x: x.distance)
        
        # Применяем пагинацию
        paginator = self.pagination_class()
        page = paginator.paginate_queryset(filtered_orders, request)
        if page is not None:
            serializer = OrderSerializer(page, many=True, context={'request': request})
            return paginator.get_paginated_response(serializer.data)
        
        serializer = OrderSerializer(filtered_orders, many=True, context={'request': request})
        return Response(serializer.data)


class AddServicesToOrderView(APIView):
    """
    API для добавления услуг к заказу
    """
    permission_classes = [IsAuthenticated]
    
    @extend_schema(
        summary="Добавить услуги к заказу",
        description="""
## Описание
Добавляет выбранные услуги мастера к заказу.

## Request Body
- `order_id`: ID заказа
- `services_list`: Список ID услуг мастера (MasterServiceItems)
- `discount`: Скидка на заказ (необязательно, по умолчанию 0.00)

## Пример запроса:
```json
{
  "order_id": 5,
  "services_list": [1, 2, 3, 4, 5],
  "discount": 150.00
}
```

## Response
Возвращает список добавленных услуг с полной информацией о каждой услуге.
        """,
        tags=[STAG_ORDER_DRIVER_LEGACY],
        request=AddServicesToOrderSerializer,
        responses={
            201: OrderServiceSerializer(many=True),
            400: {
                'type': 'object',
                'properties': {
                    'error': {'type': 'string'}
                },
                'examples': {
                    'application/json': {
                        'example': {'error': 'Order with ID 999 not found'}
                    }
                }
            },
            401: {'type': 'object', 'properties': {'detail': {'type': 'string'}}},
        }
    )
    def post(self, request):
        """Добавить услуги к заказу"""
        serializer = AddServicesToOrderSerializer(data=request.data)
        
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        
        order_id = serializer.validated_data['order_id']
        services_list = serializer.validated_data['services_list']
        discount = serializer.validated_data.get('discount', 0.00)
        
        # Получаем заказ
        try:
            order = Order.objects.get(id=order_id)
        except Order.DoesNotExist:
            return Response(
                {'error': f'Order with ID {order_id} not found'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        # Обновляем скидку в заказе
        order.discount = discount
        order.save()
        
        # Создаем связи OrderService
        from apps.master.models import MasterServiceItems
        created_services = []
        
        for service_id in services_list:
            try:
                service_item = MasterServiceItems.objects.get(id=service_id)
                # Используем get_or_create чтобы избежать дубликатов
                order_service, created = OrderService.objects.get_or_create(
                    order=order,
                    master_service_item=service_item
                )
                created_services.append(order_service)
            except MasterServiceItems.DoesNotExist:
                continue
        
        # Сериализуем результат
        result_serializer = OrderServiceSerializer(created_services, many=True)
        return Response(result_serializer.data, status=status.HTTP_201_CREATED)


class MasterServicesListView(APIView):
    """
    API для получения услуг мастера
    """
    permission_classes = [IsAuthenticated]
    
    @extend_schema(
        summary="Получить услуги мастера",
        description="""
## Описание
Возвращает список всех услуг (MasterServiceItems) для указанного мастера.
Формат ответа аналогичен формату в detail мастера.

## Параметры
- `master_id`: ID мастера (обязательный)

## Пример запроса:
```
GET /api/order/services-list/?master_id=5
```

## Response
Возвращает навыки мастера: подкатегория каталога (by_order) + цена мастера.
        """,
        tags=[STAG_ORDER_DRIVER_LEGACY],
        parameters=[
            OpenApiParameter(
                name='master_id',
                type=OpenApiTypes.INT,
                location=OpenApiParameter.QUERY,
                description='ID мастера',
                required=True
            ),
        ],
        responses={
            200: {
                'type': 'array',
                'items': {
                    'type': 'object',
                    'properties': {
                        'id': {'type': 'integer'},
                        'category': {'type': 'integer'},
                        'service_name': {'type': 'string'},
                        'parent_category_id': {'type': 'integer', 'nullable': True},
                        'parent_category_name': {'type': 'string', 'nullable': True},
                        'price': {'type': 'number'},
                        'master_service': {'type': 'integer'},
                    }
                },
                'example': [
                    {
                        'id': 1,
                        'category': 12,
                        'service_name': 'Headlight Restoration',
                        'parent_category_id': 3,
                        'parent_category_name': 'Lights',
                        'price': 100.0,
                        'master_service': 5,
                    }
                ]
            },
            400: {
                'type': 'object',
                'properties': {'error': {'type': 'string'}},
                'example': {'error': 'master_id query parameter is required'}
            },
            404: {
                'type': 'object',
                'properties': {'error': {'type': 'string'}},
                'example': {'error': 'Master not found'}
            },
            401: {'type': 'object', 'properties': {'detail': {'type': 'string'}}},
        }
    )
    def get(self, request):
        """Получить услуги мастера"""
        master_id = request.query_params.get('master_id')
        
        if not master_id:
            return Response(
                {'error': 'master_id query parameter is required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            master_id = int(master_id)
        except ValueError:
            return Response(
                {'error': 'Invalid master_id format'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Проверяем существование мастера
        try:
            master = Master.objects.get(id=master_id)
        except Master.DoesNotExist:
            return Response(
                {'error': 'Master not found'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        # Получаем все MasterServiceItems для этого мастера
        from apps.master.models import MasterServiceItems, MasterService
        from apps.master.api.serializers import MasterServiceItemsSerializer
        
        # Находим все MasterService для этого мастера
        master_services = MasterService.objects.filter(master=master)
        
        # Получаем все items этих services
        service_items = MasterServiceItems.objects.filter(
            master_service__in=master_services
        ).select_related('category', 'master_service')
        
        # Сериализуем
        serializer = MasterServiceItemsSerializer(service_items, many=True)
        return Response(serializer.data)


class AddMasterToOrderView(APIView):
    """
    Driver: assign primary master on order (`order.master` FK).
    Body: order_id, master_id (Master profile id, same as POST /standard/).
    """

    permission_classes = [IsAuthenticated]

    @extend_schema(
        summary='Назначить мастера на заказ (add master)',
        description="""
**POST** — в теле `order_id` и `master_id` (ID профиля **Master**).

Устанавливает поле **`order.master`**. Доступно только **владельцу заказа** (водителю), пока статус **`pending`**. После принятия мастером (`in_progress`) смена через этот endpoint запрещена — используйте рабочий процесс accept / support.
        """,
        tags=[STAG_ORDER_DRIVER_LEGACY],
        request=AddMasterToOrderSerializer,
        responses={
            200: OrderSerializer,
            400: {'type': 'object', 'properties': {'error': {'type': 'string'}}},
            403: {'type': 'object', 'properties': {'detail': {'type': 'string'}}},
            404: {'type': 'object', 'properties': {'error': {'type': 'string'}}},
            401: {'type': 'object', 'properties': {'detail': {'type': 'string'}}},
        },
    )
    def post(self, request):
        expire_stale_master_offers()
        ser = AddMasterToOrderSerializer(data=request.data)
        if not ser.is_valid():
            return Response(ser.errors, status=status.HTTP_400_BAD_REQUEST)

        order_id = ser.validated_data['order_id']
        master_pk = ser.validated_data['master_id']

        try:
            order = Order.objects.get(id=order_id)
        except Order.DoesNotExist:
            return Response(
                {'error': f'Order with ID {order_id} not found'},
                status=status.HTTP_404_NOT_FOUND,
            )

        if order.user_id != request.user.id:
            return Response(
                {'detail': 'Only the order owner can assign a master'},
                status=status.HTTP_403_FORBIDDEN,
            )

        if order.status != OrderStatus.PENDING:
            return Response(
                {'error': 'A master can only be assigned while the order is pending'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            master = Master.objects.get(id=master_pk)
        except Master.DoesNotExist:
            return Response(
                {'error': f'Master with ID {master_pk} not found'},
                status=status.HTTP_404_NOT_FOUND,
            )

        order.master = master
        order.save(update_fields=['master', 'updated_at'])
        if order.status == OrderStatus.PENDING:
            activate_pending_master_offer(order, request=request)
        return Response(
            OrderSerializer(order, context={'request': request}).data,
            status=status.HTTP_200_OK,
        )
