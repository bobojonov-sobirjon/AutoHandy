from rest_framework import status
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView
from drf_spectacular.utils import extend_schema

from .models import Car
from .permissions import IsDriverGroup
from .serializers import CarSerializer, CarWriteSerializer


class CarListCreateView(APIView):
    """Список и создание машин — тело запроса: multipart/form-data (рекомендуется) или JSON."""

    permission_classes = [IsDriverGroup]
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def get_queryset(self):
        return Car.objects.filter(user=self.request.user)

    @extend_schema(
        summary="Получить список машин",
        description="Получить список машин пользователя",
        responses={
            200: CarSerializer,
            403: {'type': 'object', 'properties': {'detail': {'type': 'string'}}},
        },
        tags=['Cars'],
    )
    def get(self, request):
        cars = self.get_queryset()
        serializer = CarSerializer(cars, many=True, context={'request': request})
        return Response(serializer.data, status=status.HTTP_200_OK)

    @extend_schema(
        summary="Создать новую машину",
        description=(
            "Используйте **multipart/form-data**: поля `category` (id), `brand`, `model`, `year`, "
            "файл `image`. Числа в форме передаются строками. JSON без файла тоже поддерживается."
        ),
        request=CarWriteSerializer,
        responses={
            201: CarSerializer,
            400: {'type': 'object', 'properties': {'detail': {'type': 'string'}}},
            403: {'type': 'object', 'properties': {'detail': {'type': 'string'}}},
        },
        tags=['Cars'],
    )
    def post(self, request):
        serializer = CarWriteSerializer(data=request.data, context={'request': request})
        if serializer.is_valid():
            car = serializer.save()
            response_serializer = CarSerializer(car, context={'request': request})
            return Response(response_serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class CarDetailView(APIView):
    """Детали, обновление и удаление — PUT/PATCH: multipart/form-data (рекомендуется) или JSON."""

    permission_classes = [IsDriverGroup]
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def get_object(self, pk):
        try:
            return Car.objects.get(pk=pk, user=self.request.user)
        except Car.DoesNotExist:
            return None

    @extend_schema(
        summary="Получить детали машины",
        description="Получить детали машины",
        responses={
            200: CarSerializer,
            404: {'type': 'object', 'properties': {'error': {'type': 'string'}}},
            403: {'type': 'object', 'properties': {'detail': {'type': 'string'}}},
        },
        tags=['Cars'],
    )
    def get(self, request, pk):
        car = self.get_object(pk)
        if not car:
            return Response({'error': 'Машина не найдена'}, status=status.HTTP_404_NOT_FOUND)

        serializer = CarSerializer(car, context={'request': request})
        return Response(serializer.data, status=status.HTTP_200_OK)

    @extend_schema(
        summary="Обновить машину",
        description=(
            "Полное обновление: **multipart/form-data** с полями `category`, `brand`, `model`, `year`, `image` "
            "(или JSON без загрузки файла)."
        ),
        request=CarWriteSerializer,
        responses={
            200: CarSerializer,
            400: {'type': 'object', 'properties': {'detail': {'type': 'string'}}},
            404: {'type': 'object', 'properties': {'error': {'type': 'string'}}},
            403: {'type': 'object', 'properties': {'detail': {'type': 'string'}}},
        },
        tags=['Cars'],
    )
    def put(self, request, pk):
        car = self.get_object(pk)
        if not car:
            return Response({'error': 'Машина не найдена'}, status=status.HTTP_404_NOT_FOUND)

        serializer = CarWriteSerializer(car, data=request.data, context={'request': request})
        if serializer.is_valid():
            serializer.save()
            car.refresh_from_db()
            return Response(CarSerializer(car, context={'request': request}).data, status=status.HTTP_200_OK)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    @extend_schema(
        summary="Частичное обновление машины",
        description="Частичное обновление через **multipart/form-data** (например, только `image`) или JSON.",
        request=CarWriteSerializer,
        responses={
            200: CarSerializer,
            400: {'type': 'object', 'properties': {'detail': {'type': 'string'}}},
            404: {'type': 'object', 'properties': {'error': {'type': 'string'}}},
            403: {'type': 'object', 'properties': {'detail': {'type': 'string'}}},
        },
        tags=['Cars'],
    )
    def patch(self, request, pk):
        car = self.get_object(pk)
        if not car:
            return Response({'error': 'Машина не найдена'}, status=status.HTTP_404_NOT_FOUND)

        serializer = CarWriteSerializer(car, data=request.data, partial=True, context={'request': request})
        if serializer.is_valid():
            serializer.save()
            car.refresh_from_db()
            return Response(CarSerializer(car, context={'request': request}).data, status=status.HTTP_200_OK)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    @extend_schema(
        summary="Удалить машину",
        description="Удалить машину",
        responses={
            204: {'description': 'Машина удалена'},
            404: {'type': 'object', 'properties': {'error': {'type': 'string'}}},
            403: {'type': 'object', 'properties': {'detail': {'type': 'string'}}},
        },
        tags=['Cars'],
    )
    def delete(self, request, pk):
        car = self.get_object(pk)
        if not car:
            return Response({'error': 'Машина не найдена'}, status=status.HTTP_404_NOT_FOUND)

        car.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class CarStatsView(APIView):
    """Статистика машин пользователя - только для группы Driver"""

    permission_classes = [IsDriverGroup]

    def get_queryset(self):
        return Car.objects.filter(user=self.request.user)

    @extend_schema(
        summary="Получить статистику машин",
        description="Получить статистику машин пользователя",
        responses={
            200: {
                'type': 'object',
                'properties': {
                    'total_cars': {'type': 'integer'},
                    'cars_by_category': {'type': 'object'},
                    'cars_by_brand': {'type': 'object'},
                },
            },
            403: {'type': 'object', 'properties': {'detail': {'type': 'string'}}},
        },
        tags=['Cars'],
    )
    def get(self, request):
        cars = self.get_queryset()

        cars_by_category = {}
        for car in cars:
            category_name = car.category.name if car.category else 'Без категории'
            cars_by_category[category_name] = cars_by_category.get(category_name, 0) + 1

        cars_by_brand = {}
        for car in cars:
            brand = car.brand or 'Не указано'
            cars_by_brand[brand] = cars_by_brand.get(brand, 0) + 1

        return Response(
            {
                'total_cars': cars.count(),
                'cars_by_category': cars_by_category,
                'cars_by_brand': cars_by_brand,
            },
            status=status.HTTP_200_OK,
        )
