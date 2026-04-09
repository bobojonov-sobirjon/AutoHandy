"""Push / outbound notifications for orders (extend with FCM/APNs)."""
from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.conf import settings
from django.core.serializers.json import DjangoJSONEncoder
if TYPE_CHECKING:
    from django.http import HttpRequest

    from apps.order.models import Order

logger = logging.getLogger(__name__)


def _ws_json_safe(value: Any) -> Any:
    """Make nested dicts safe for Channels (Redis JSON) and ``json.dumps`` on the consumer."""
    return json.loads(json.dumps(value, cls=DjangoJSONEncoder))


def _absolute_media_path(request: 'HttpRequest | None', relative_url: str) -> str:
    """Turn /media/... into full URL. Prefer API_PUBLIC_BASE_URL (SOS rotation has no request)."""
    if not relative_url:
        return relative_url
    if relative_url.startswith('http://') or relative_url.startswith('https://'):
        return relative_url
    base = (getattr(settings, 'API_PUBLIC_BASE_URL', '') or '').strip().rstrip('/')
    if base:
        path = relative_url if relative_url.startswith('/') else f'/{relative_url}'
        return f'{base}{path}'
    if request:
        return request.build_absolute_uri(relative_url)
    return relative_url


def _media_url(request: 'HttpRequest | None', file_field) -> str | None:
    if not file_field:
        return None
    try:
        url = file_field.url
    except ValueError:
        return None
    return _absolute_media_path(request, url)


def build_sos_order_websocket_payload(
    order: 'Order',
    *,
    request: 'HttpRequest | None' = None,
    offered_master_id: int | None = None,
) -> dict[str, Any]:
    """
    Rich SOS offer payload for WebSocket (exact location for emergency).
    """
    from apps.order.models import Order as OrderModel

    oid = order.pk
    order = (
        OrderModel.objects.filter(pk=oid)
        .select_related('user')
        .prefetch_related(
            'car__category',
            'category',
            'order_services__master_service_item__category',
            'order_services__master_service_item__category__parent',
            'images',
        )
        .get(pk=oid)
    )

    u = order.user
    full_name = (u.get_full_name() or '').strip() or None

    user_out: dict[str, Any] = {
        'id': u.id,
        'private_id': u.private_id,
        'first_name': u.first_name or '',
        'last_name': u.last_name or '',
        'full_name': full_name,
        'phone_number': getattr(u, 'phone_number', None) or None,
        'email': getattr(u, 'email', None) or None,
        'avatar': _media_url(request, getattr(u, 'avatar', None)),
    }

    car_data: list[dict[str, Any]] = []
    for car in order.car.all():
        cat = car.category
        car_data.append(
            {
                'id': car.id,
                'brand': car.brand,
                'model': car.model,
                'year': car.year,
                'image': _media_url(request, car.image),
                'category': (
                    {
                        'id': cat.id,
                        'name': cat.name,
                        'type_category': cat.type_category,
                        'parent_id': cat.parent_id,
                    }
                    if cat
                    else None
                ),
            }
        )

    category_data = [
        {
            'id': c.id,
            'name': c.name,
            'type_category': c.type_category,
            'parent_id': c.parent_id,
        }
        for c in order.category.all()
    ]

    services_out: list[dict[str, Any]] = []
    for os_row in order.order_services.all():
        msi = os_row.master_service_item
        if not msi:
            continue
        cat = msi.category
        services_out.append(
            {
                'id': msi.id,
                'service_name': cat.name if cat else None,
                'category_id': cat.id if cat else None,
                'type_category': cat.type_category if cat else None,
                'price': str(msi.price) if msi.price is not None else None,
            }
        )

    order_images = [
        {
            'id': im.id,
            'image': _media_url(request, im.image),
            'created_at': im.created_at.isoformat() if im.created_at else None,
        }
        for im in order.images.all()
    ]

    queue = order.sos_offer_queue or []
    sos_broadcast = bool(queue)
    seconds = int(
        getattr(settings, 'SOS_BROADCAST_RESPONSE_SECONDS', 120)
        if sos_broadcast
        else getattr(settings, 'SOS_OFFER_SECONDS_PER_MASTER', 30)
    )

    return {
        'order_id': order.id,
        'status': order.status,
        'text': (order.text or '')[:4000],
        'location': order.location or '',
        'latitude': str(order.latitude) if order.latitude is not None else None,
        'longitude': str(order.longitude) if order.longitude is not None else None,
        'location_source': order.location_source,
        'priority': order.priority,
        'order_type': order.order_type,
        'discount': str(order.discount) if order.discount is not None else None,
        'parts_purchase_required': order.parts_purchase_required,
        'preferred_date': (
            order.preferred_date.isoformat() if order.preferred_date else None
        ),
        'preferred_time_start': (
            order.preferred_time_start.isoformat()
            if order.preferred_time_start
            else None
        ),
        'preferred_time_end': (
            order.preferred_time_end.isoformat()
            if order.preferred_time_end
            else None
        ),
        'created_at': order.created_at.isoformat() if order.created_at else None,
        'updated_at': order.updated_at.isoformat() if order.updated_at else None,
        'user': user_out,
        'car_data': car_data,
        'category_data': category_data,
        'services': services_out,
        'order_images': order_images,
        'master_response_deadline': (
            order.master_response_deadline.isoformat() if order.master_response_deadline else None
        ),
        'seconds': seconds,
        'sos_offer_index': order.sos_offer_index,
        'sos_queue_length': len(queue),
        'sos_broadcast': sos_broadcast,
        'offered_master_id': offered_master_id,
    }


def build_custom_request_websocket_payload(
    order: 'Order',
    *,
    request: 'HttpRequest | None' = None,
) -> dict[str, Any]:
    """Payload for masters on ``custom_request_push`` — category labels are neutral (no catalog leakage)."""
    from apps.order.models import Order as OrderModel

    oid = order.pk
    order = (
        OrderModel.objects.filter(pk=oid)
        .select_related('user')
        .prefetch_related('car__category', 'category', 'images')
        .get(pk=oid)
    )
    u = order.user
    full_name = (u.get_full_name() or '').strip() or None
    user_out: dict[str, Any] = {
        'id': u.id,
        'private_id': u.private_id,
        'first_name': u.first_name or '',
        'last_name': u.last_name or '',
        'full_name': full_name,
        'phone_number': getattr(u, 'phone_number', None) or None,
        'email': getattr(u, 'email', None) or None,
        'avatar': _media_url(request, getattr(u, 'avatar', None)),
    }
    car_data: list[dict[str, Any]] = []
    for car in order.car.all():
        cat = car.category
        car_data.append(
            {
                'id': car.id,
                'brand': car.brand,
                'model': car.model,
                'year': car.year,
                'image': _media_url(request, car.image),
                'category': (
                    {
                        'id': cat.id,
                        'name': cat.name,
                        'type_category': cat.type_category,
                        'parent_id': cat.parent_id,
                    }
                    if cat
                    else None
                ),
            }
        )
    mask = 'Incoming request'
    category_data = [
        {
            'id': c.id,
            'name': mask,
            'type_category': c.type_category,
            'parent_id': c.parent_id,
        }
        for c in order.category.all()
    ]
    order_images = [
        {
            'id': im.id,
            'image': _media_url(request, im.image),
            'created_at': im.created_at.isoformat() if im.created_at else None,
        }
        for im in order.images.all()
    ]
    return {
        'order_id': order.id,
        'kind': 'custom_request',
        'status': order.status,
        'text': (order.text or '')[:4000],
        'location': order.location or '',
        'latitude': str(order.latitude) if order.latitude is not None else None,
        'longitude': str(order.longitude) if order.longitude is not None else None,
        'location_source': order.location_source,
        'priority': order.priority,
        'order_type': order.order_type,
        'created_at': order.created_at.isoformat() if order.created_at else None,
        'updated_at': order.updated_at.isoformat() if order.updated_at else None,
        'user': user_out,
        'car_data': car_data,
        'category_data': category_data,
        'order_images': order_images,
    }


def push_custom_request_to_master_websocket(
    order: 'Order',
    *,
    request: 'HttpRequest | None' = None,
    target_master_id: int,
) -> None:
    """Real-time custom-request job to one master (same WS connection as SOS: ``ws/sos/master/``)."""
    try:
        from apps.master.models import Master

        master = Master.objects.select_related('user').get(pk=target_master_id)
        group = f'master_sos_{master.user_id}'
        layer = get_channel_layer()
        if not layer:
            return
        payload = build_custom_request_websocket_payload(order, request=request)
        async_to_sync(layer.group_send)(
            group,
            {'type': 'custom_request_push', 'payload': payload},
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning('push_custom_request_to_master_websocket failed: %s', exc)


def push_custom_request_offer_to_rider_websocket(
    order: 'Order',
    *,
    offer_id: int,
    master_id: int,
    price: str,
    created_at_iso: str | None,
    request: 'HttpRequest | None' = None,
) -> None:
    """Notify the client (driver) over ``ws/custom-request/rider/`` when a master submits a price."""
    try:
        from apps.master.api.serializers import MasterSerializer
        from apps.master.models import Master
        from apps.master.services.geo import haversine_distance_km

        master = (
            Master.objects.select_related('user')
            .prefetch_related(
                'master_images',
                'master_services',
                'master_services__master_service_items',
                'master_services__master_service_items__category',
                'master_services__master_service_items__category__parent',
            )
            .get(pk=master_id)
        )

        wlat, wlon = master.get_work_location_for_distance()
        if (
            order.latitude is not None
            and order.longitude is not None
            and wlat is not None
            and wlon is not None
        ):
            master.distance = float(
                haversine_distance_km(
                    float(order.latitude),
                    float(order.longitude),
                    float(wlat),
                    float(wlon),
                )
            )
        else:
            master.distance = None

        layer = get_channel_layer()
        if not layer:
            return

        ctx: dict[str, Any] = {
            'request': request,
            'hide_master_exact_location': False,
            'embed_order_min_price': True,
        }
        first_cat = order.category.first()
        if first_cat is not None and not getattr(first_cat, 'is_custom_request_entry', False):
            ctx['filter_service_category_id'] = first_cat.id

        payload = _ws_json_safe(
            {
                'offer_id': offer_id,
                'order_id': order.id,
                'price': price,
                'created_at': created_at_iso,
                'master': MasterSerializer(master, context=ctx).data,
            }
        )
        group = f'rider_custom_request_{order.user_id}'
        async_to_sync(layer.group_send)(
            group,
            {'type': 'rider_custom_request_offer', 'payload': payload},
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning('push_custom_request_offer_to_rider_websocket failed: %s', exc)


def push_sos_order_to_master_websocket(
    order: 'Order',
    *,
    request: 'HttpRequest | None' = None,
    target_master_id: int | None = None,
) -> None:
    """
    Real-time SOS offer to master's WebSocket group.
    Connect: ws://.../ws/sos/master/?token=<JWT>

    Use Redis channel layer if HTTP and WS (or Celery) run in different processes.
    """
    from apps.order.models import OrderType
    from apps.order.services.master_service_zone import order_within_master_acceptance_zone

    mid = target_master_id if target_master_id is not None else order.master_id
    if not mid:
        return
    if order.order_type == OrderType.SOS and not order_within_master_acceptance_zone(order, mid):
        logger.warning(
            'push_sos_order_to_master_websocket skipped: order %s not in master %s acceptance zone',
            order.id,
            mid,
        )
        return
    try:
        from apps.master.models import Master

        master = Master.objects.select_related('user').get(pk=mid)
        group = f'master_sos_{master.user_id}'
        layer = get_channel_layer()
        if not layer:
            return
        payload = build_sos_order_websocket_payload(
            order, request=request, offered_master_id=mid
        )
        async_to_sync(layer.group_send)(
            group,
            {'type': 'sos_order_push', 'payload': payload},
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning('push_sos_order_to_master_websocket failed: %s', exc)


def notify_master_new_order(order: 'Order', *, target_master_id: int | None = None) -> None:
    """
    Loud alert for new assignment (integrate mobile push + vibration on client).
    Hook: send FCM to order.master.user_id devices.
    """
    mid = target_master_id if target_master_id is not None else order.master_id
    if not mid:
        return
    logger.info(
        'notify_master_new_order: order_id=%s master_id=%s (implement FCM for production)',
        order.id,
        mid,
    )
