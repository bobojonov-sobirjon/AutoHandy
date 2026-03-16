from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from apps.categories.models import Category
from apps.categories.serializers import CategorySerializer
from rest_framework.permissions import AllowAny
from drf_spectacular.utils import extend_schema, OpenApiParameter
from drf_spectacular.types import OpenApiTypes

class CategoryListAPIView(APIView):
    permission_classes = [AllowAny]
    
    @extend_schema(
        summary="Получить список категорий",
        description="""
        Получить список всех категорий с возможностью фильтрации по типу.
        
        **Фильтрация:**
        - Используйте параметр `type` для фильтрации категорий по типу (TypeCategory)
        - Доступные значения фильтра:
          * `by_master` - Категории для мастерских (услуги мастеров)
          * `by_car` - Категории для автомобилей (марки, модели и т.д.)
          * `by_order` - Категории для заказов
        - Если параметр `type` не указан, возвращаются все категории
        
        **Примеры использования:**
        - `/api/categories/categories/` - все категории
        - `/api/categories/categories/?type=by_master` - только категории мастеров
        - `/api/categories/categories/?type=by_car` - только категории машин
        - `/api/categories/categories/?type=by_order` - только категории заказов
        
        **Поля в ответе:**
        - `id` - ID категории
        - `name` - Название категории
        - `type_category` - Тип категории (by_master, by_car, by_order)
        - `icon` - URL иконки категории (полный URL)
        - `created_at` - Дата создания
        - `updated_at` - Дата обновления
        """,
        parameters=[
            OpenApiParameter(
                name='type',
                type=str,
                location=OpenApiParameter.QUERY,
                description='Фильтр по типу категории (TypeCategory): by_master - Категории мастеров, by_car - Категории машин, by_order - Категории заказов',
                required=False,
                enum=['by_master', 'by_car', 'by_order']
            )
        ],
        responses={
            200: CategorySerializer(many=True)
        },
        tags=['Categories']
    )
    def get(self, request):
        """Получение списка категорий с фильтрацией по TypeCategory"""
        type_filter = request.query_params.get('type')
        
        if type_filter == 'by_master':
            categories = Category.by_master.all()
        elif type_filter == 'by_car':
            categories = Category.by_car.all()
        elif type_filter == 'by_order':
            categories = Category.by_order.all()
        else:
            categories = Category.objects.all()
        
        serializer = CategorySerializer(categories, many=True, context={'request': request})
        return Response(serializer.data)