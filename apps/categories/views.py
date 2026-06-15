from django.db.models import Q
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from apps.categories.models import Category
from apps.categories.serializers import CategorySerializer
from apps.categories.services.home_screen_order import order_categories_for_display
from rest_framework.permissions import AllowAny
from drf_spectacular.utils import extend_schema, OpenApiParameter
from drf_spectacular.types import OpenApiTypes


def _main_categories_queryset():
    return Category.objects.filter(parent__isnull=True)


def _parse_bool_query(value) -> bool | None:
    if value is None or value == '':
        return None
    return str(value).strip().lower() in ('1', 'true', 'yes')


def _exclude_custom_request_catalog(qs, request):
    """Masters must not see client-only Custom Request / Towing entries in public lists."""
    user = getattr(request, 'user', None)
    if user and user.is_authenticated and user.groups.filter(name='Master').exists():
        return qs.filter(is_custom_request_entry=False, is_towing_entry=False)
    return qs


def _apply_truck_catalog_filter(qs, request):
    """
    Default lists hide semi-truck-only categories (regular car app).
    Pass ``?is_truck=true`` to list truck roadside catalog only.
    """
    truck_only = _parse_bool_query(request.query_params.get('is_truck'))
    if truck_only is True:
        return qs.filter(is_truck=True)
    if truck_only is False:
        return qs.filter(is_truck=False)
    return qs.filter(is_truck=False)


class CategoryListAPIView(APIView):
    permission_classes = [AllowAny]
    
    @extend_schema(
        summary="Получить список категорий",
        description="""
        Возвращает только **основные (main) категории** — у которых нет родителя (`parent` = null).
        Подкатегории смотрите в `GET /api/categories/subcategories/?parent_id=...`.

        **Filtering:**
        - `type` — `by_car` or `by_order`
        - `is_truck` — `true` for **Emergency Roadside for Semi Trucks** catalog only; default hides truck categories

        **Sorting:** results are ordered by `sort_order` ascending (home screen order), then name.

        **Examples:**
        - `/api/categories/categories/?type=by_order` — car/service main categories
        - `/api/categories/categories/?type=by_order&is_truck=true` — semi-truck roadside main category
        """,
        parameters=[
            OpenApiParameter(
                name='type',
                type=str,
                location=OpenApiParameter.QUERY,
                description='Filter by category type: by_car or by_order.',
                required=False,
                enum=['by_car', 'by_order']
            ),
            OpenApiParameter(
                name='is_truck',
                type=bool,
                location=OpenApiParameter.QUERY,
                description='true = semi-truck services only; omitted/false = regular (non-truck) catalog.',
                required=False,
            ),
        ],
        responses={
            200: CategorySerializer(many=True)
        },
        tags=['Categories']
    )
    def get(self, request):
        """Список только основных категорий с фильтром по TypeCategory."""
        type_filter = request.query_params.get('type')
        if type_filter == 'by_master':
            type_filter = 'by_order'
        base = _main_categories_queryset()

        if type_filter == 'by_car':
            categories = base.filter(type_category='by_car')
        elif type_filter == 'by_order':
            categories = base.filter(type_category='by_order')
        else:
            categories = base

        categories = _exclude_custom_request_catalog(categories, request)
        categories = _apply_truck_catalog_filter(categories, request)
        categories = order_categories_for_display(categories)
        serializer = CategorySerializer(categories, many=True, context={'request': request})
        return Response(serializer.data)


class SubCategoryListAPIView(APIView):
    permission_classes = [AllowAny]

    @extend_schema(
        summary="Подкатегории по основной категории",
        description="""
        Список подкатегорий для указанной **основной** категории.
        `parent_id` — ID main-категории (без родителя). Если категория не main или не найдена — 404.
        """,
        parameters=[
            OpenApiParameter(
                name='parent_id',
                type=OpenApiTypes.INT,
                location=OpenApiParameter.QUERY,
                description='ID основной (main) категории',
                required=True,
            ),
        ],
        responses={
            200: CategorySerializer(many=True),
            400: OpenApiTypes.OBJECT,
            404: OpenApiTypes.OBJECT,
        },
        tags=['Categories'],
    )
    def get(self, request):
        raw = request.query_params.get('parent_id')
        if raw is None or raw == '':
            return Response(
                {'detail': 'Query parameter parent_id is required.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            parent_pk = int(raw)
        except (TypeError, ValueError):
            return Response(
                {'detail': 'parent_id must be an integer.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        main_exists = _main_categories_queryset().filter(pk=parent_pk).exists()
        if not main_exists:
            return Response(
                {'detail': 'Main category not found.'},
                status=status.HTTP_404_NOT_FOUND,
            )
        parent = Category.objects.filter(pk=parent_pk).first()
        if not parent:
            return Response(
                {'detail': 'Main category not found.'},
                status=status.HTTP_404_NOT_FOUND,
            )
        if parent.is_custom_request_entry or parent.is_towing_entry:
            return Response(
                {'detail': 'Main category not found.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        subs = Category.objects.filter(parent_id=parent_pk)
        subs = _exclude_custom_request_catalog(subs, request)
        subs = subs.filter(~Q(parent__is_custom_request_entry=True))
        truck_only = _parse_bool_query(request.query_params.get('is_truck'))
        if truck_only is True:
            subs = subs.filter(is_truck=True)
        elif truck_only is False:
            subs = subs.filter(is_truck=False)
        elif parent and parent.is_truck:
            subs = subs.filter(is_truck=True)
        else:
            subs = subs.filter(is_truck=False)
        subs = order_categories_for_display(subs)
        serializer = CategorySerializer(subs, many=True, context={'request': request})
        return Response(serializer.data)