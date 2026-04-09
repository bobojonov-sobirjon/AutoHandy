from django.db.models import Q
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from apps.categories.models import Category
from apps.categories.serializers import CategorySerializer
from rest_framework.permissions import AllowAny
from drf_spectacular.utils import extend_schema, OpenApiParameter
from drf_spectacular.types import OpenApiTypes


def _main_categories_queryset():
    return Category.objects.filter(parent__isnull=True)


def _exclude_custom_request_catalog(qs, request):
    """Masters must not see the client-only Custom Request category in public lists."""
    user = getattr(request, 'user', None)
    if user and user.is_authenticated and user.groups.filter(name='Master').exists():
        return qs.filter(is_custom_request_entry=False)
    return qs


class CategoryListAPIView(APIView):
    permission_classes = [AllowAny]
    
    @extend_schema(
        summary="Получить список категорий",
        description="""
        Возвращает только **основные (main) категории** — у которых нет родителя (`parent` = null).
        Подкатегории смотрите в `GET /api/categories/subcategories/?parent_id=...`.

        **Фильтрация:**
        - Параметр `type` — по типу (TypeCategory): `by_car`, `by_order`
        - Без `type` — все основные категории

        **Примеры:**
        - `/api/categories/categories/` — все main-категории
        - `/api/categories/categories/?type=by_order` — main по заказам / услугам
        """,
        parameters=[
            OpenApiParameter(
                name='type',
                type=str,
                location=OpenApiParameter.QUERY,
                description='Фильтр по типу категории: by_car — машина, by_order — заказы/услуги.',
                required=False,
                enum=['by_car', 'by_order']
            )
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
        categories = categories.order_by('-created_at')
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
        user = getattr(request, 'user', None)
        if user and user.is_authenticated and user.groups.filter(name='Master').exists():
            if Category.objects.filter(pk=parent_pk, is_custom_request_entry=True).exists():
                return Response(
                    {'detail': 'Main category not found.'},
                    status=status.HTTP_404_NOT_FOUND,
                )

        subs = Category.objects.filter(parent_id=parent_pk)
        subs = _exclude_custom_request_catalog(subs, request)
        subs = subs.filter(
            ~Q(parent__is_custom_request_entry=True),
        ).order_by('-created_at')
        serializer = CategorySerializer(subs, many=True, context={'request': request})
        return Response(serializer.data)