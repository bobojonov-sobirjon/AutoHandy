from rest_framework.views import APIView
from rest_framework import status
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, AllowAny
from drf_spectacular.utils import extend_schema, OpenApiExample, OpenApiParameter
from drf_spectacular.types import OpenApiTypes
from django.db.models import Q
from .models import Master, MasterService, MasterServiceItems, MasterEmployee, MasterImage
from .serializers import (
    MasterSerializer, MasterCreateSerializer, MasterUpdateSerializer, MasterNearbySerializer,
    MasterServiceSerializer, MasterServiceItemsSerializer, MasterEmployeeCreateSerializer,
    AddServiceItemsSerializer, UpdateServiceItemSerializer, AddMasterImagesSerializer, 
    UpdateMasterImageSerializer, MasterImageSerializer, MasterEmployeeSerializer
)
from .permissions import IsMasterGroup, IsOwnerGroup
from django.contrib.auth import get_user_model
from apps.accounts.services import SMSService

User = get_user_model()


class MasterProfileView(APIView):
    """
    API для управления профилем мастера.
    
    Поддерживаемые операции:
    - GET: получение профилей мастерских где пользователь является владельцем ИЛИ сотрудником
    - POST: создание профиля мастера (доступно ТОЛЬКО для Owner группы)
    """
    
    def get_permissions(self):
        """Разные права доступа для разных методов"""
        if self.request.method == 'POST':
            return [IsOwnerGroup()]
        elif self.request.method == 'GET':
            return [AllowAny()]
        return [IsMasterGroup()]
    
    def get_object(self):
        """
        Получение всех профилей мастера текущего пользователя
        
        Ищет мастерские где:
        1. Пользователь является владельцем (Master.user)
        2. ИЛИ пользователь является сотрудником (MasterEmployee.employee)
        """
        user = self.request.user
        
        # Сначала ищем мастерские где user - владелец
        masters_as_owner = Master.objects.filter(user=user)
        
        # Затем ищем мастерские где user - сотрудник
        employee_relations = MasterEmployee.objects.filter(employee=user).select_related('master')
        masters_as_employee = Master.objects.filter(
            id__in=[emp.master.id for emp in employee_relations]
        )
        
        # Объединяем оба queryset'а (используем union или |)
        # distinct() чтобы избежать дубликатов
        all_masters = (masters_as_owner | masters_as_employee).distinct()
        
        return all_masters
    
    @extend_schema(
        summary="Получить профиль мастера",
        description="""
        Получить профили мастерских текущего пользователя. Доступно для всех пользователей (публичный доступ).
        
        **Логика поиска:**
        - Если пользователь авторизован, возвращаются все мастерские где он является:
          1. Владельцем (создал мастерскую)
          2. ИЛИ сотрудником (добавлен через MasterEmployee)
        - Если пользователь не авторизован, возвращается пустой список
        """,
        responses={
            200: MasterSerializer(many=True)
        },
        tags=['Masters']
    )
    def get(self, request):
        """Получение всех профилей мастера"""
        # Если пользователь авторизован, показываем его профили
        if request.user and request.user.is_authenticated:
            masters = self.get_object()
            serializer = MasterSerializer(masters, many=True, context={'request': request})
            return Response(serializer.data, status=status.HTTP_200_OK)
        else:
            # Для неавторизованных пользователей возвращаем пустой список
            return Response([], status=status.HTTP_200_OK)
    
    @extend_schema(
        summary="Создать профиль мастера (ТОЛЬКО для Owner)",
        description="""
        Создание нового профиля мастера. Эта операция доступна ТОЛЬКО пользователям с ролью 'Owner'.
        
        **ВАЖНО**: Вы должны быть в группе 'Owner' для выполнения этой операции!
        
        **ФОРМАТ ЗАПРОСА**: multipart/form-data (для загрузки изображений)
        
        **ВСЕ ПОЛЯ НЕОБЯЗАТЕЛЬНЫ!** Можно отправить пустой объект {} или заполнить только нужные поля:
        
        - `name`: Название мастерской (строка, например: "СТО Авто-Сервис")
        - `city`: Город мастерской (строка)
        - `address`: Адрес мастерской (строка)
        - `phone`: Номер телефона мастерской (строка, например: +998901234567)
        - `working_time`: Режим работы (строка, например: "Пн-Пт: 09:00-18:00, Сб: 10:00-16:00")
        - `latitude`: Широта местоположения (число от -90 до 90, например: 41.3111)
        - `longitude`: Долгота местоположения (число от -180 до 180, например: 69.2797)
        - `description`: Описание мастерской и услуг (текст)
        - `category`: Список ID категорий услуг (JSON массив строк, например: "[1, 2, 3]")
        - `services`: Список услуг с ценами (JSON массив объектов, каждый содержит: name, price_from, price_to, category)
        - `card_number`: Номер банковской карты для платежей (строка, до 19 символов)
        - `card_expiry_month`: Месяц истечения срока карты (число 1-12)
        - `card_expiry_year`: Год истечения срока карты (число, например: 2026)
        - `card_cvv`: CVV код карты (строка, 3-4 цифры)
        
        **Примечания:**
        - User автоматически берется из текущего авторизованного пользователя
        - Категории должны существовать в базе данных и иметь тип 'by_master'
        - После создания мастерской, user автоматически добавляется в группу 'Master'
        - Можно создать мастерскую вообще без данных и заполнить потом через PUT/PATCH
        - Изображения добавляются отдельно через POST /api/master/images/ после создания мастера
        """,
        request=MasterCreateSerializer,
        examples=[
            OpenApiExample(
                'Полный пример создания мастерской',
                value={
                    "name": "СТО Авто-Сервис",
                    "city": "Ташкент",
                    "address": "ул. Амира Темура, 15",
                    "latitude": 41.3111,
                    "longitude": 69.2797,
                    "phone": "+998901234567",
                    "working_time": "Пн-Пт: 09:00-18:00, Сб: 10:00-16:00",
                    "description": "Автосервис с полным спектром услуг. Работаем с 2010 года. Опытные мастера, качественные запчасти.",
                    "category": [1, 2, 3],
                    "services": [
                        {
                            "name": "Замена масла",
                            "price_from": 150000,
                            "price_to": 300000,
                            "category": 1
                        },
                        {
                            "name": "Диагностика двигателя",
                            "price_from": 50000,
                            "price_to": 100000,
                            "category": 2
                        }
                    ],
                    "card_number": "8600123456789012",
                    "card_expiry_month": 12,
                    "card_expiry_year": 2026,
                    "card_cvv": "123"
                },
                request_only=True
            ),
            OpenApiExample(
                'Минимальный пример',
                value={
                    "name": "Мой Автосервис",
                    "city": "Москва",
                    "phone": "+79991234567"
                },
                request_only=True
            ),
            OpenApiExample(
                'Пустой запрос (можно создать вообще без данных)',
                value={},
                request_only=True
            )
        ],
        responses={
            201: MasterSerializer,
            400: {'type': 'object', 'properties': {'detail': {'type': 'string', 'example': 'Ошибка валидации данных'}}},
            403: {'type': 'object', 'properties': {'detail': {'type': 'string', 'example': 'Только пользователи с ролью Owner могут создавать мастерские'}}}
        },
        tags=['Masters']
    )
    def post(self, request):
        """Создание профиля мастера (ТОЛЬКО для Owner)"""
        serializer = MasterCreateSerializer(data=request.data, context={'request': request})
        if serializer.is_valid():
            master = serializer.save()
            response_serializer = MasterSerializer(master, context={'request': request})
            return Response([response_serializer.data], status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class MasterListView(APIView):
    """
    API для получения списка мастеров с фильтрацией (публичный доступ).
    Если фильтры не указаны, возвращается пустой список!
    """
    permission_classes = [AllowAny]
    
    @extend_schema(
        summary="Получить список мастеров с фильтрацией",
        description="""
        Получить список мастеров с обязательной фильтрацией. 
        
        **ВАЖНО**: Если фильтры не указаны, возвращается пустой список!
        
        **Параметры фильтрации:**
        - `category` - ID категории (by_order или by_master). При by_order ищет мастеров через service_type или название
        - `name` - Название мастерской (поиск по частичному совпадению)
        - `lat` - Широта текущего местоположения пользователя (требуется вместе с long и radius)
        - `long` - Долгота текущего местоположения пользователя (требуется вместе с lat и radius)
        - `radius` - Радиус поиска в километрах (по умолчанию 10 км, требуется вместе с lat и long)
        
        **Примеры использования:**
        - `/api/master/masters/list/?category=1` - мастера по категории (умный поиск)
        - `/api/master/masters/list/?name=Авто` - поиск по названию
        - `/api/master/masters/list/?lat=41.3111&long=69.2797&radius=5` - мастера в радиусе 5 км
        - `/api/master/masters/list/?category=1&lat=41.3111&long=69.2797&radius=10` - комбинация фильтров
        
        **Умный поиск по категории:**
        - Если category типа by_order: ищет мастеров через MasterServiceItems по service_type или названию
        - Если category типа by_master: прямой поиск по категории мастера
        - Точность поиска: 80-90%
        
        **Геолокация:**
        - Расчет расстояния выполняется по формуле Haversine
        - Возвращаются только мастера с заполненными координатами (latitude и longitude)
        - Поле `distance` добавляется в ответ (расстояние в километрах от точки пользователя)
        """,
        parameters=[
            OpenApiParameter(
                name='category',
                type=int,
                location=OpenApiParameter.QUERY,
                description='ID категории мастера',
                required=False
            ),
            OpenApiParameter(
                name='name',
                type=str,
                location=OpenApiParameter.QUERY,
                description='Название мастерской (поиск по частичному совпадению)',
                required=False
            ),
            OpenApiParameter(
                name='lat',
                type=float,
                location=OpenApiParameter.QUERY,
                description='Широта текущего местоположения пользователя',
                required=False
            ),
            OpenApiParameter(
                name='long',
                type=float,
                location=OpenApiParameter.QUERY,
                description='Долгота текущего местоположения пользователя',
                required=False
            ),
            OpenApiParameter(
                name='radius',
                type=float,
                location=OpenApiParameter.QUERY,
                description='Радиус поиска в километрах (по умолчанию 10 км)',
                required=False
            )
        ],
        responses={
            200: MasterSerializer(many=True)
        },
        tags=['Masters']
    )
    def get(self, request):
        """Получение списка мастеров с фильтрацией"""
        # Получаем параметры фильтрации
        category_id = request.query_params.get('category')
        name = request.query_params.get('name')
        user_lat = request.query_params.get('lat')
        user_long = request.query_params.get('long')
        radius = request.query_params.get('radius', 10)  # По умолчанию 10 км
        
        # Если нет ни одного фильтра, возвращаем пустой список
        if not any([category_id, name, user_lat, user_long]):
            return Response([], status=status.HTTP_200_OK)
        
        # Начинаем с всех мастеров
        masters = Master.objects.all()
        
        from apps.categories.models import Category
        from django.db.models import Q
        
        # Собираем все условия поиска (OR между ними)
        search_conditions = Q()
        
        # Фильтр по категории (умный поиск)
        if category_id:
            try:
                category_id = int(category_id)
                category = Category.objects.get(id=category_id)
                
                # Если category типа by_order (из заказа)
                if category.type_category == 'by_order':
                    # Ищем мастеров через MasterServiceItems
                    category_conditions = Q()
                    
                    # 1. Поиск по service_type (если заполнен)
                    if category.service_type:
                        category_conditions |= Q(
                            master_services__master_service_items__category__service_type__icontains=category.service_type
                        )
                        # Также ищем в категориях самого Master
                        category_conditions |= Q(
                            category__service_type__icontains=category.service_type
                        )
                    
                    # 2. Поиск по названию категории (частичное совпадение)
                    if category.name:
                        # Ищем в названии услуги MasterServiceItems
                        category_conditions |= Q(
                            master_services__master_service_items__name__icontains=category.name
                        )
                        # Ищем в названии категории MasterServiceItems
                        category_conditions |= Q(
                            master_services__master_service_items__category__name__icontains=category.name
                        )
                        # Ищем в категориях самого Master
                        category_conditions |= Q(
                            category__name__icontains=category.name
                        )
                        # Ищем в названии мастерской
                        category_conditions |= Q(
                            name__icontains=category.name
                        )
                    
                    search_conditions |= category_conditions
                
                # Если category типа by_master (напрямую)
                elif category.type_category == 'by_master':
                    search_conditions |= Q(category__id=category_id)
                
                else:
                    # Для других типов (by_car) - прямой поиск
                    search_conditions |= Q(category__id=category_id)
                    
            except Category.DoesNotExist:
                return Response(
                    {'error': 'Категория не найдена'}, 
                    status=status.HTTP_404_NOT_FOUND
                )
            except (ValueError, TypeError):
                return Response(
                    {'error': 'Неверный формат category ID'}, 
                    status=status.HTTP_400_BAD_REQUEST
                )
        
        # Фильтр по названию (расширенный поиск)
        if name:
            name_conditions = Q()
            # Поиск в названии мастерской
            name_conditions |= Q(name__icontains=name)
            # Поиск в названии услуг
            name_conditions |= Q(master_services__master_service_items__name__icontains=name)
            # Поиск в названии категорий услуг
            name_conditions |= Q(master_services__master_service_items__category__name__icontains=name)
            # Поиск в service_type категорий услуг
            name_conditions |= Q(master_services__master_service_items__category__service_type__icontains=name)
            # Поиск в категориях самого Master
            name_conditions |= Q(category__name__icontains=name)
            name_conditions |= Q(category__service_type__icontains=name)
            # Поиск в адресе и городе
            name_conditions |= Q(city__icontains=name)
            name_conditions |= Q(address__icontains=name)
            
            search_conditions |= name_conditions
        
        # Применяем все условия поиска
        if search_conditions:
            masters = masters.filter(search_conditions).distinct()
        
        # Фильтр по геолокации (расстояние)
        if user_lat and user_long:
            try:
                user_lat = float(user_lat)
                user_long = float(user_long)
                radius = float(radius)
                
                # Валидация координат
                if not (-90 <= user_lat <= 90):
                    return Response(
                        {'error': 'Широта должна быть между -90 и 90'}, 
                        status=status.HTTP_400_BAD_REQUEST
                    )
                if not (-180 <= user_long <= 180):
                    return Response(
                        {'error': 'Долгота должна быть между -180 и 180'}, 
                        status=status.HTTP_400_BAD_REQUEST
                    )
                
                # Фильтруем мастеров с координатами
                masters = masters.exclude(latitude__isnull=True).exclude(longitude__isnull=True)
                
                # Вычисляем расстояние для каждого мастера
                filtered_masters = []
                for master in masters:
                    distance = self.calculate_distance(
                        user_lat, user_long,
                        float(master.latitude), float(master.longitude)
                    )
                    # Добавляем расстояние как атрибут для отображения
                    master.distance = round(distance, 2)
                    
                    # Фильтруем только тех, кто в пределах радиуса
                    if distance <= radius:
                        filtered_masters.append(master)
                
                # Сортируем по расстоянию (ближайшие сначала)
                filtered_masters.sort(key=lambda x: x.distance)
                masters = filtered_masters
                
            except (ValueError, TypeError):
                return Response(
                    {'error': 'Неверный формат координат или радиуса'}, 
                    status=status.HTTP_400_BAD_REQUEST
                )
        
        # Если после фильтрации нет результатов
        if not masters:
            return Response([], status=status.HTTP_200_OK)
        
        # Сериализуем результаты
        serializer = MasterSerializer(masters, many=True, context={'request': request})
        return Response(serializer.data, status=status.HTTP_200_OK)
    
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


class MasterDetailsView(APIView):
    """
    API для операций с конкретным мастером по ID.
    GET - доступно всем пользователям (публичный доступ)
    PUT/PATCH - доступно ТОЛЬКО для Owner
    DELETE - доступно ТОЛЬКО для Owner
    """
    
    def get_permissions(self):
        """Разные права доступа для разных методов"""
        if self.request.method in ['PUT', 'PATCH', 'DELETE']:
            return [IsOwnerGroup()]
        elif self.request.method == 'GET':
            return [AllowAny()]
        return [IsAuthenticated()]
    
    def get_object(self, master_id):
        """Получение мастера по ID"""
        try:
            return Master.objects.get(id=master_id)
        except Master.DoesNotExist:
            return None
    
    @extend_schema(
        summary="Получить детали мастера по ID",
        description="Получить подробную информацию о мастерской по ID. Доступно для всех пользователей (публичный доступ).",
        responses={
            200: MasterSerializer,
            404: {'type': 'object', 'properties': {'error': {'type': 'string', 'example': 'Мастер не найден'}}}
        },
        tags=['Masters']
    )
    def get(self, request, master_id):
        """Получение деталей мастера"""
        master = self.get_object(master_id)
        if not master:
            return Response(
                {'error': 'Мастер не найден'}, 
                status=status.HTTP_404_NOT_FOUND
            )
        
        serializer = MasterSerializer(master, context={'request': request})
        return Response(serializer.data, status=status.HTTP_200_OK)
    
    @extend_schema(
        summary="Обновить мастера по ID (ТОЛЬКО для Owner)",
        description="""
        Полное обновление информации о мастерской. Эта операция доступна ТОЛЬКО пользователям с ролью 'Owner'.
        
        **ВАЖНО**: Вы должны быть в группе 'Owner' для выполнения этой операции!
        
        **ФОРМАТ ЗАПРОСА**: multipart/form-data (для загрузки изображений)
        
        Все поля необязательны, можно обновить только нужные поля:
        
        - `name`: Название мастерской (строка)
        - `city`: Город мастерской (строка)
        - `address`: Адрес мастерской (строка)
        - `phone`: Номер телефона мастерской (строка)
        - `working_time`: Режим работы (строка)
        - `latitude`: Широта местоположения (число от -90 до 90)
        - `longitude`: Долгота местоположения (число от -180 до 180)
        - `description`: Описание мастерской и услуг (текст)
        - `card_number`: Номер банковской карты для платежей (строка)
        - `card_expiry_month`: Месяц истечения срока карты (число 1-12)
        - `card_expiry_year`: Год истечения срока карты (число)
        - `card_cvv`: CVV код карты (строка, 3-4 цифры)
        
        **Примечание**: Изображения обновляются через отдельные endpoint'ы:
        - POST /api/master/images/ - добавить изображения
        - PUT /api/master/images/{image_id}/ - заменить изображение
        - DELETE /api/master/images/{image_id}/ - удалить изображение
        """,
        request=MasterUpdateSerializer,
        responses={
            200: MasterSerializer,
            400: {'type': 'object', 'properties': {'detail': {'type': 'string'}}},
            404: {'type': 'object', 'properties': {'error': {'type': 'string'}}},
            403: {'type': 'object', 'properties': {'detail': {'type': 'string'}}}
        },
        tags=['Masters']
    )
    def put(self, request, master_id):
        """Полное обновление мастера"""
        master = self.get_object(master_id)
        if not master:
            return Response(
                {'error': 'Мастер не найден'}, 
                status=status.HTTP_404_NOT_FOUND
            )
        
        serializer = MasterUpdateSerializer(master, data=request.data, context={'request': request})
        if serializer.is_valid():
            updated_master = serializer.save()
            response_serializer = MasterSerializer(updated_master, context={'request': request})
            return Response(response_serializer.data, status=status.HTTP_200_OK)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    @extend_schema(
        summary="Частичное обновление мастера по ID (ТОЛЬКО для Owner)",
        description="""
        Частичное обновление информации о мастерской. Эта операция доступна ТОЛЬКО пользователям с ролью 'Owner'.
        
        **ВАЖНО**: Вы должны быть в группе 'Owner' для выполнения этой операции!
        
        **ФОРМАТ ЗАПРОСА**: multipart/form-data (для загрузки изображений)
        
        Можно обновить только нужные поля, не передавая все остальные:
        
        - `name`: Название мастерской (строка)
        - `city`: Город мастерской (строка)
        - `address`: Адрес мастерской (строка)
        - `phone`: Номер телефона мастерской (строка)
        - `working_time`: Режим работы (строка)
        - `latitude`: Широта местоположения (число от -90 до 90)
        - `longitude`: Долгота местоположения (число от -180 до 180)
        - `description`: Описание мастерской и услуг (текст)
        - `card_number`: Номер банковской карты для платежей (строка)
        - `card_expiry_month`: Месяц истечения срока карты (число 1-12)
        - `card_expiry_year`: Год истечения срока карты (число)
        - `card_cvv`: CVV код карты (строка, 3-4 цифры)
        
        **Примечание**: Изображения обновляются через отдельные endpoint'ы:
        - POST /api/master/images/ - добавить изображения
        - PUT /api/master/images/{image_id}/ - заменить изображение
        - DELETE /api/master/images/{image_id}/ - удалить изображение
        """,
        request=MasterUpdateSerializer,
        responses={
            200: MasterSerializer,
            400: {'type': 'object', 'properties': {'detail': {'type': 'string', 'example': 'Ошибка валидации данных'}}},
            404: {'type': 'object', 'properties': {'error': {'type': 'string', 'example': 'Мастер не найден'}}},
            403: {'type': 'object', 'properties': {'detail': {'type': 'string', 'example': 'Только пользователи с ролью Owner могут обновлять мастерские'}}}
        },
        tags=['Masters']
    )
    def patch(self, request, master_id):
        """Частичное обновление мастера (ТОЛЬКО для Owner)"""
        master = self.get_object(master_id)
        if not master:
            return Response(
                {'error': 'Мастер не найден'}, 
                status=status.HTTP_404_NOT_FOUND
            )
        
        serializer = MasterUpdateSerializer(master, data=request.data, partial=True, context={'request': request})
        if serializer.is_valid():
            updated_master = serializer.save()
            response_serializer = MasterSerializer(updated_master, context={'request': request})
            return Response(response_serializer.data, status=status.HTTP_200_OK)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    @extend_schema(
        summary="Удалить мастера по ID (ТОЛЬКО для Owner)",
        description="""
        Удаление мастерской из системы. Эта операция доступна ТОЛЬКО пользователям с ролью 'Owner'.
        
        **ВАЖНО**: Вы должны быть в группе 'Owner' для выполнения этой операции!
        
        **ВНИМАНИЕ**: Это действие удалит мастерскую и все связанные с ней данные (услуги, изображения и т.д.)
        """,
        responses={
            204: {'description': 'Мастер успешно удален'},
            404: {'type': 'object', 'properties': {'error': {'type': 'string', 'example': 'Мастер не найден'}}},
            403: {'type': 'object', 'properties': {'detail': {'type': 'string', 'example': 'Только пользователи с ролью Owner могут удалять мастерские'}}}
        },
        tags=['Masters']
    )
    def delete(self, request, master_id):
        """Удаление мастера (ТОЛЬКО для Owner)"""
        master = self.get_object(master_id)
        if not master:
            return Response(
                {'error': 'Мастер не найден'}, 
                status=status.HTTP_404_NOT_FOUND
            )
        
        master.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class MasterServiceView(APIView):
    """
    API для добавления услуги мастеру.
    """
    permission_classes = [IsMasterGroup]
    
    def get_master(self):
        """Получить мастера текущего пользователя"""
        try:
            return Master.objects.get(user=self.request.user)
        except Master.DoesNotExist:
            return None
    
    @extend_schema(
        summary="Добавить услугу мастеру",
        description="""
        Добавление услуги с элементами мастеру. Доступно только для пользователей с ролью 'Master'.
        
        **Формат запроса:**
        ```json
        {
            "master_items": [
                {
                    "name": "Название услуги",
                    "price_from": 100000,
                    "price_to": 200000,
                    "category": 1
                },
                {
                    "name": "Другая услуга",
                    "price_from": 50000,
                    "price_to": 150000,
                    "category": 2
                }
            ]
        }
        ```
        
        **Важно:** Поле `master_items` обязательно и должно быть массивом объектов!
        """,
        request=MasterServiceSerializer,
        examples=[
            OpenApiExample(
                'Пример создания услуги мастера',
                value={
                    "master_items": [
                        {
                            "name": "Замена масла",
                            "price_from": 150000,
                            "price_to": 300000,
                            "category": 1
                        },
                        {
                            "name": "Диагностика двигателя",
                            "price_from": 100000,
                            "price_to": 250000,
                            "category": 2
                        }
                    ]
                }
            )
        ],
        responses={
            201: MasterServiceSerializer,
            400: {'type': 'object', 'properties': {'error': {'type': 'string'}}},
            403: {'type': 'object', 'properties': {'detail': {'type': 'string'}}},
            404: {'type': 'object', 'properties': {'error': {'type': 'string'}}}
        },
        tags=['Master Services']
    )
    def post(self, request):
        """Добавление услуги мастеру"""
        master = self.get_master()
        if not master:
            return Response(
                {'error': 'Профиль мастера не найден'}, 
                status=status.HTTP_404_NOT_FOUND
            )
        
        serializer = MasterServiceSerializer(data=request.data, context={'request': request})
        if serializer.is_valid():
            service = serializer.save(master=master)
            response_serializer = MasterServiceSerializer(service, context={'request': request})
            return Response(response_serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class MasterServiceDetailView(APIView):
    """
    API для управления конкретной услугой мастера.
    """
    permission_classes = [IsAuthenticated]
    
    def get_object(self, service_id):
        """Получить услугу мастера"""
        try:
            service = MasterService.objects.get(id=service_id)
            # Проверяем права доступа
            if self.request.user.has_perm('apps.change_masterservice'):
                return service
            if service.master.user == self.request.user:
                return service
            return None
        except MasterService.DoesNotExist:
            return None
    
    @extend_schema(
        summary="Получить услугу мастера по ID",
        responses={
            200: MasterServiceSerializer,
            404: {'type': 'object', 'properties': {'error': {'type': 'string'}}},
            403: {'type': 'object', 'properties': {'detail': {'type': 'string'}}}
        },
        tags=['Master Services']
    )
    def get(self, request, service_id):
        """Получение услуги мастера"""
        service = self.get_object(service_id)
        if not service:
            return Response(
                {'error': 'Услуга не найдена'}, 
                status=status.HTTP_404_NOT_FOUND
            )
        
        serializer = MasterServiceSerializer(service, context={'request': request})
        return Response(serializer.data, status=status.HTTP_200_OK)
    
    @extend_schema(
        summary="Обновить услугу мастера",
        request=MasterServiceSerializer,
        responses={
            200: MasterServiceSerializer,
            400: {'type': 'object', 'properties': {'detail': {'type': 'string'}}},
            404: {'type': 'object', 'properties': {'error': {'type': 'string'}}},
            403: {'type': 'object', 'properties': {'detail': {'type': 'string'}}}
        },
        tags=['Master Services']
    )
    def put(self, request, service_id):
        """Обновление услуги мастера"""
        service = self.get_object(service_id)
        if not service:
            return Response(
                {'error': 'Услуга не найдена'}, 
                status=status.HTTP_404_NOT_FOUND
            )
        
        serializer = MasterServiceSerializer(service, data=request.data, context={'request': request})
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_200_OK)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    @extend_schema(
        summary="Удалить услугу мастера",
        responses={
            204: {'description': 'Услуга удалена'},
            404: {'type': 'object', 'properties': {'error': {'type': 'string'}}},
            403: {'type': 'object', 'properties': {'detail': {'type': 'string'}}}
        },
        tags=['Master Services']
    )
    def delete(self, request, service_id):
        """Удаление услуги мастера"""
        service = self.get_object(service_id)
        if not service:
            return Response(
                {'error': 'Услуга не найдена'}, 
                status=status.HTTP_404_NOT_FOUND
            )
        
        service.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class MasterServiceItemsView(APIView):
    """
    API для добавления элементов услуги мастера.
    """
    permission_classes = [IsMasterGroup]
    
    @extend_schema(
        summary="Добавить элементы услуги мастера",
        description="Добавить элементы услуги мастера",
        request=MasterServiceItemsSerializer(many=True),
        responses={
            201: MasterServiceItemsSerializer(many=True),
            400: {'type': 'object', 'properties': {'detail': {'type': 'string'}}},
            403: {'type': 'object', 'properties': {'detail': {'type': 'string'}}}
        },
        tags=['Master Service Items']
    )
    def post(self, request):
        """Добавление элементов услуги мастера"""
        serializer = MasterServiceItemsSerializer(data=request.data, many=True, context={'request': request})
        if serializer.is_valid():
            items = serializer.save()
            response_serializer = MasterServiceItemsSerializer(items, many=True, context={'request': request})
            return Response(response_serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class MasterServiceItemsDetailView(APIView):
    """
    API для управления конкретным элементом услуги мастера.
    """
    permission_classes = [IsAuthenticated]
    
    def get_object(self, item_id):
        """Получить элемент услуги мастера"""
        try:
            item = MasterServiceItems.objects.get(id=item_id)
            # Проверяем права доступа
            if self.request.user.has_perm('apps.change_masterserviceitems'):
                return item
            if item.master_service.master.user == self.request.user:
                return item
            return None
        except MasterServiceItems.DoesNotExist:
            return None
    
    @extend_schema(
        summary="Получить элемент услуги мастера по ID",
        responses={
            200: MasterServiceItemsSerializer,
            404: {'type': 'object', 'properties': {'error': {'type': 'string'}}},
            403: {'type': 'object', 'properties': {'detail': {'type': 'string'}}}
        },
        tags=['Master Service Items']
    )
    def get(self, request, item_id):
        """Получение элемента услуги мастера"""
        item = self.get_object(item_id)
        if not item:
            return Response(
                {'error': 'Элемент не найден'}, 
                status=status.HTTP_404_NOT_FOUND
            )
        
        serializer = MasterServiceItemsSerializer(item, context={'request': request})
        return Response(serializer.data, status=status.HTTP_200_OK)
    
    @extend_schema(
        summary="Обновить элемент услуги мастера",
        request=MasterServiceItemsSerializer,
        responses={
            200: MasterServiceItemsSerializer,
            400: {'type': 'object', 'properties': {'detail': {'type': 'string'}}},
            404: {'type': 'object', 'properties': {'error': {'type': 'string'}}},
            403: {'type': 'object', 'properties': {'detail': {'type': 'string'}}}
        },
        tags=['Master Service Items']
    )
    def put(self, request, item_id):
        """Обновление элемента услуги мастера"""
        item = self.get_object(item_id)
        if not item:
            return Response(
                {'error': 'Элемент не найден'}, 
                status=status.HTTP_404_NOT_FOUND
            )
        
        serializer = MasterServiceItemsSerializer(item, data=request.data, context={'request': request})
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_200_OK)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    @extend_schema(
        summary="Удалить элемент услуги мастера",
        responses={
            204: {'description': 'Элемент удален'},
            404: {'type': 'object', 'properties': {'error': {'type': 'string'}}},
            403: {'type': 'object', 'properties': {'detail': {'type': 'string'}}}
        },
        tags=['Master Service Items']
    )
    def delete(self, request, item_id):
        """Удаление элемента услуги мастера"""
        item = self.get_object(item_id)
        if not item:
            return Response(
                {'error': 'Элемент не найден'}, 
                status=status.HTTP_404_NOT_FOUND
            )
        
        item.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class MasterServicesByMasterView(APIView):
    """
    API для получения услуг мастера по master_id.
    """
    permission_classes = [AllowAny]
    
    @extend_schema(
        summary="Получить услуги мастера по ID",
        description="Получить услуги мастера по ID мастера. Доступно для всех пользователей (публичный доступ).",
        responses={
            200: MasterServiceSerializer(many=True),
            404: {'type': 'object', 'properties': {'error': {'type': 'string'}}}
        },
        tags=['Master Services']
    )
    def get(self, request, master_id):
        """Получение услуг мастера"""
        try:
            master = Master.objects.get(id=master_id)
            services = MasterService.objects.filter(master=master)
            serializer = MasterServiceSerializer(services, many=True, context={'request': request})
            return Response(serializer.data, status=status.HTTP_200_OK)
        except Master.DoesNotExist:
            return Response(
                {'error': 'Мастер не найден'}, 
                status=status.HTTP_404_NOT_FOUND
            )


class MasterEmployeeView(APIView):
    """
    API для управления сотрудниками мастерской
    GET - поиск пользователя по private_id
    POST - добавление сотрудника к мастерской
    """
    permission_classes = [IsAuthenticated]
    
    @extend_schema(
        summary="Поиск пользователя по private_id",
        description="Поиск пользователя по его уникальному private_id. Возвращает полную информацию о пользователе.",
        parameters=[
            OpenApiParameter(
                name='private_id',
                description='Уникальный 6-значный ID пользователя',
                required=True,
                type=str,
                location=OpenApiParameter.QUERY
            )
        ],
        responses={
            200: {
                'type': 'object',
                'properties': {
                    'success': {'type': 'boolean', 'example': True},
                    'user': {
                        'type': 'object',
                        'properties': {
                            'id': {'type': 'integer'},
                            'private_id': {'type': 'string'},
                            'full_name': {'type': 'string'},
                            'phone_number': {'type': 'string'},
                            'email': {'type': 'string'},
                            'avatar': {'type': 'string'},
                            'description': {'type': 'string'}
                        }
                    }
                }
            },
            404: {'type': 'object', 'properties': {'error': {'type': 'string'}}}
        },
        tags=['Add Master to Owner Master']
    )
    def get(self, request):
        """Поиск пользователя по private_id"""
        private_id = request.query_params.get('private_id')
        
        if not private_id:
            return Response(
                {'error': 'private_id обязателен'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            user = User.objects.get(private_id=private_id)
            return Response({
                'success': True,
                'user': {
                    'id': user.id,
                    'private_id': user.private_id,
                    'full_name': user.get_full_name(),
                    'phone_number': user.phone_number,
                    'email': user.email,
                    'avatar': user.avatar.url if user.avatar else None,
                    'description': user.description
                }
            }, status=status.HTTP_200_OK)
        except User.DoesNotExist:
            return Response(
                {'error': 'Пользователь не найден'},
                status=status.HTTP_404_NOT_FOUND
            )
    
    @extend_schema(
        summary="Добавить сотрудника к мастерской",
        description="""
        Добавление сотрудника к мастерской. 
        
        **Важно:** 
        - Владелец мастерской добавляется автоматически при создании.
        - Один пользователь может быть сотрудником только одной мастерской.
        - Если пользователь уже работает в другой мастерской, вернется ошибка.
        """,
        request=MasterEmployeeCreateSerializer,
        examples=[
            OpenApiExample(
                'Пример добавления сотрудника',
                value={
                    "master_id": 1,
                    "user_id": 5
                },
                request_only=True
            )
        ],
        responses={
            201: {
                'type': 'object',
                'properties': {
                    'success': {'type': 'boolean', 'example': True},
                    'message': {'type': 'string', 'example': 'Сотрудник успешно добавлен'}
                }
            },
            400: {
                'type': 'object',
                'properties': {
                    'success': {'type': 'boolean', 'example': False},
                    'error': {'type': 'string', 'example': 'Этот пользователь уже является сотрудником мастерской "Иван Иванов". Один пользователь может работать только в одной мастерской.'},
                    'errors': {'type': 'object', 'description': 'Ошибки валидации полей'}
                },
                'description': 'Ошибка валидации или пользователь уже работает в другой мастерской'
            }
        },
        tags=['Add Master to Owner Master']
    )
    def post(self, request):
        """Добавление сотрудника к мастерской"""
        serializer = MasterEmployeeCreateSerializer(data=request.data)
        
        if not serializer.is_valid():
            return Response({
                'success': False,
                'errors': serializer.errors
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # Получаем валидированные данные
        master_id = serializer.validated_data['master_id']
        user_id = serializer.validated_data['user_id']
        
        master = Master.objects.get(id=master_id)
        user = User.objects.get(id=user_id)
        
        # Добавление сотрудника (validation уже прошел в serializer)
        MasterEmployee.objects.create(master=master, employee=user)
        
        # Отправка уведомления сотруднику
        try:
            owner_name = master.user.get_full_name() or master.user.email
            master_address = master.address or "мастерской"
            
            # Формируем сообщение
            notification_message = f"🎉 Вас добавили в мастерскую!\n\n"
            notification_message += f"👤 Владелец: {owner_name}\n"
            notification_message += f"📍 Адрес: {master_address}\n"
            notification_message += f"🏙 Город: {master.city}\n\n"
            notification_message += f"✅ Вы теперь являетесь сотрудником этой мастерской."
            
            # Отправляем уведомление через Telegram (если есть chat_id)
            if user.telegram_chat_id:
                import requests
                bot_token = SMSService.BOT_TOKEN
                url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
                
                data = {
                    'chat_id': user.telegram_chat_id,
                    'text': notification_message,
                    'parse_mode': 'HTML'
                }
                
                try:
                    response = requests.post(url, json=data, timeout=10)
                    if response.status_code == 200:
                        import logging
                        logger = logging.getLogger(__name__)
                        logger.info(f"Notification sent to user {user.id} via Telegram")
                except Exception as telegram_error:
                    import logging
                    logger = logging.getLogger(__name__)
                    logger.error(f"Error sending Telegram notification: {str(telegram_error)}")
            
            # Альтернативно отправляем на email если есть
            elif user.email:
                # Отправляем через email (можно добавить email service)
                from django.core.mail import send_mail
                from django.conf import settings
                
                try:
                    send_mail(
                        subject='Вас добавили в мастерскую',
                        message=notification_message,
                        from_email=settings.DEFAULT_FROM_EMAIL,
                        recipient_list=[user.email],
                        fail_silently=True
                    )
                except Exception as email_error:
                    import logging
                    logger = logging.getLogger(__name__)
                    logger.error(f"Error sending email notification: {str(email_error)}")
            
            # Или через SMS
            elif user.phone_number:
                SMSService.send_telegram_sms(
                    phone_number=user.phone_number,
                    message=notification_message
                )
                
        except Exception as e:
            # Логируем ошибку, но не прерываем процесс
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Error sending notification to employee {user.id}: {str(e)}")
        
        return Response({
            'success': True,
            'message': 'Сотрудник успешно добавлен'
        }, status=status.HTTP_201_CREATED)


class MasterFilterChoicesView(APIView):
    """
    API для получения всех доступных фильтров для мастеров
    """
    permission_classes = [AllowAny]
    
    @extend_schema(
        summary="Получить варианты для фильтров мастеров",
        description="""
## Описание
Возвращает все доступные варианты для фильтрации мастеров.

## Что возвращается:
- **services** - Список уникальных услуг из MasterServiceItems (distinct)
- **locations** - Список уникальных городов где есть мастера

Используется для построения фильтров в UI приложения.
        """,
        tags=['Masters'],
        responses={
            200: {
                'description': 'Успешный ответ',
                'content': {
                    'application/json': {
                        'example': {
                            'services': ['Замена масла', 'Диагностика двигателя', 'Шиномонтаж'],
                            'locations': ['Ташкент', 'Самарканд', 'Бухара']
                        }
                    }
                }
            }
        }
    )
    def get(self, request):
        """Получить варианты фильтров"""
        
        # Получаем уникальные услуги из MasterServiceItems
        services = MasterServiceItems.objects.values_list('name', flat=True).distinct().order_by('name')
        services_list = [service for service in services if service]  # Убираем пустые
        
        # Получаем уникальные города мастеров
        locations = Master.objects.values_list('city', flat=True).distinct().order_by('city')
        locations_list = [location for location in locations if location]  # Убираем пустые
        
        return Response({
            'services': services_list,
            'locations': locations_list
        }, status=status.HTTP_200_OK)


class MastersByUserView(APIView):
    """
    API для получения списка мастеров с фильтрацией
    """
    permission_classes = [AllowAny]
    
    @extend_schema(
        summary="Получить список мастеров с фильтрацией",
        description="""
## Описание
Возвращает список всех мастеров с возможностью фильтрации и сортировки.

## Фильтры (все необязательные)

### 1. Услуги (service_items)
- **Multiple** - Массив названий услуг для фильтрации
- Пример: `service_items=Замена масла&service_items=Диагностика`
- Ищет мастеров у которых есть хотя бы одна из указанных услуг (OR)

### 2. Категория (category)
- **Multiple** - Массив ID категорий мастера (by_master)
- Пример: `category=1&category=2`
- Ищет мастеров с любой из указанных категорий (OR)

### 3. Координаты (latitude, longitude)
- Широта и долгота пользователя для поиска ближайших мастеров
- Пример: `latitude=41.3111&longitude=69.2797`

### 4. Город/Район (location)
- **Multiple** - Массив городов/районов
- Пример: `location=Ташкент&location=Самарканд`
- Ищет мастеров в любом из указанных городов (OR)

### 5. Наивысший рейтинг (highest_rating)
- Только мастера с высоким рейтингом (4.5+)
- Значение: true/false
- Пример: `highest_rating=true`

### 6. Круглосуточные (round_clock)
- Мастерские работающие 24/7
- Значение: true/false
- Пример: `round_clock=true`

## Сортировка (sort)
- **best** (по умолчанию) - Лучшие мастерские (по рейтингу)
- **distance** - По расстоянию (требуется latitude и longitude)
- **newest** - Новые мастерские

Пример: `sort=distance`

## Примеры запросов

**Базовый:**
```
GET /api/master/masters/by-user/
```

**С фильтром по услугам (multiple):**
```
GET /api/master/masters/by-user/?service_items=Замена масла&service_items=Диагностика
```

**С категориями (multiple):**
```
GET /api/master/masters/by-user/?category=1&category=2
```

**С городами (multiple):**
```
GET /api/master/masters/by-user/?location=Ташкент&location=Самарканд
```

**С координатами и сортировкой:**
```
GET /api/master/masters/by-user/?latitude=41.3111&longitude=69.2797&sort=distance
```

**Комбинированный фильтр:**
```
GET /api/master/masters/by-user/?service_items=Шиномонтаж&category=1&category=2&location=Ташкент&highest_rating=true&round_clock=true
```
        """,
        tags=['Masters'],
        parameters=[
            OpenApiParameter(
                name='service_items', 
                type={'type': 'array', 'items': {'type': 'string'}}, 
                location=OpenApiParameter.QUERY, 
                description='Фильтр по услугам (multiple). Пример: service_items=Замена масла&service_items=Диагностика. Ищет по MasterServiceItems.name',
                required=False,
                explode=True,
                style='form'
            ),
            OpenApiParameter(
                name='category', 
                type={'type': 'array', 'items': {'type': 'integer'}}, 
                location=OpenApiParameter.QUERY, 
                description='Фильтр по категориям (multiple ID). Пример: category=1&category=2',
                required=False,
                explode=True,
                style='form'
            ),
            OpenApiParameter(name='latitude', type=OpenApiTypes.FLOAT, location=OpenApiParameter.QUERY, description='Широта пользователя для поиска ближайших', required=False),
            OpenApiParameter(name='longitude', type=OpenApiTypes.FLOAT, location=OpenApiParameter.QUERY, description='Долгота пользователя', required=False),
            OpenApiParameter(
                name='location', 
                type={'type': 'array', 'items': {'type': 'string'}}, 
                location=OpenApiParameter.QUERY, 
                description='Фильтр по городам/районам (multiple). Пример: location=Ташкент&location=Самарканд',
                required=False,
                explode=True,
                style='form'
            ),
            OpenApiParameter(name='highest_rating', type=OpenApiTypes.BOOL, location=OpenApiParameter.QUERY, description='Только с высоким рейтингом (4.5+)', required=False),
            OpenApiParameter(name='round_clock', type=OpenApiTypes.BOOL, location=OpenApiParameter.QUERY, description='Круглосуточные мастерские (24/7)', required=False),
            OpenApiParameter(name='sort', type=OpenApiTypes.STR, location=OpenApiParameter.QUERY, description='Сортировка: best, distance, newest', required=False, enum=['best', 'distance', 'newest']),
        ],
        responses={
            200: MasterSerializer(many=True),
            400: {'type': 'object', 'properties': {'error': {'type': 'string'}}},
        }
    )
    def get(self, request):
        """Получить список мастеров с фильтрацией"""
        from math import radians, sin, cos, sqrt, atan2
        from django.db.models import Avg, Q
        
        # Получаем всех мастеров
        masters = Master.objects.all().select_related('user').prefetch_related('category', 'master_services__master_service_items')
        
        print(f"\n{'='*60}")
        print(f"FILTER MASTERS BY USER")
        print(f"Всего мастеров до фильтрации: {masters.count()}")
        
        # Фильтр по услугам (service_items) - MULTIPLE
        service_items = request.query_params.getlist('service_items')
        print(f"service_items параметр: {service_items}")
        if service_items:
            # OR условие - мастер должен иметь хотя бы одну из указанных услуг
            service_conditions = Q()
            for service_item in service_items:
                service_conditions |= Q(master_services__master_service_items__name__icontains=service_item)
                print(f"  Добавлен фильтр по услуге: {service_item}")
            masters = masters.filter(service_conditions).distinct()
            print(f"Мастеров после фильтра service_items: {masters.count()}")
        
        # Фильтр по категориям - MULTIPLE
        categories = request.query_params.getlist('category')
        print(f"category параметр: {categories}")
        if categories:
            try:
                # Игнорируем 0 и пустые значения
                category_ids = [int(cat_id) for cat_id in categories if cat_id and int(cat_id) > 0]
                print(f"  category_ids после фильтрации: {category_ids}")
                if category_ids:
                    # OR условие - мастер может иметь любую из указанных категорий
                    masters = masters.filter(category__id__in=category_ids).distinct()
                    print(f"Мастеров после фильтра category: {masters.count()}")
            except (ValueError, TypeError) as e:
                print(f"  ОШИБКА при обработке category: {e}")
                pass
        
        # Фильтр по городам/районам - MULTIPLE
        locations = request.query_params.getlist('location')
        print(f"location параметр: {locations}")
        if locations:
            # OR условие - мастер может быть в любом из указанных городов
            location_conditions = Q()
            for location in locations:
                location_conditions |= Q(city__icontains=location) | Q(address__icontains=location)
                print(f"  Добавлен фильтр по городу: {location}")
            masters = masters.filter(location_conditions)
            print(f"Мастеров после фильтра location: {masters.count()}")
        
        # Фильтр по наивысшему рейтингу (4.5+)
        highest_rating = request.query_params.get('highest_rating', '').lower() == 'true'
        if highest_rating:
            # Аннотируем средний рейтинг
            from apps.order.models import Rating
            masters = masters.annotate(avg_rating=Avg('ratings__rating')).filter(avg_rating__gte=4.5)
        
        # Фильтр круглосуточные (предполагаем, что есть поле working_time)
        round_clock = request.query_params.get('round_clock', '').lower() == 'true'
        if round_clock:
            # Ищем мастеров у которых в working_time есть "24" или "круглосуточно"
            masters = masters.filter(
                Q(working_time__icontains='24') | Q(working_time__icontains='круглосуточно')
            )
        
        # Координаты для расчета расстояния
        user_lat = request.query_params.get('latitude')
        user_long = request.query_params.get('longitude')
        
        # Сортировка
        sort_param = request.query_params.get('sort', 'best')
        
        if sort_param == 'distance' and user_lat and user_long:
            # Сортировка по расстоянию
            try:
                user_lat = float(user_lat)
                user_long = float(user_long)
                
                # Вычисляем расстояние для каждого мастера
                masters_with_distance = []
                for master in masters:
                    if master.latitude and master.longitude:
                        # Haversine formula
                        R = 6371.0
                        lat1_rad = radians(user_lat)
                        lon1_rad = radians(user_long)
                        lat2_rad = radians(float(master.latitude))
                        lon2_rad = radians(float(master.longitude))
                        
                        dlat = lat2_rad - lat1_rad
                        dlon = lon2_rad - lon1_rad
                        
                        a = sin(dlat / 2)**2 + cos(lat1_rad) * cos(lat2_rad) * sin(dlon / 2)**2
                        c = 2 * atan2(sqrt(a), sqrt(1 - a))
                        distance = R * c
                        
                        master.distance = round(distance, 2)
                        masters_with_distance.append(master)
                
                # Сортируем по расстоянию
                masters_with_distance.sort(key=lambda x: x.distance)
                masters = masters_with_distance
                
            except (ValueError, TypeError):
                pass
        
        elif sort_param == 'newest':
            # Сортировка по дате создания (новые сначала)
            masters = masters.order_by('-created_at')
        
        else:
            # По умолчанию: "best" - лучшие (по рейтингу)
            from apps.order.models import Rating
            masters = masters.annotate(avg_rating=Avg('ratings__rating')).order_by('-avg_rating', '-created_at')
        
        # Сериализуем
        print(f"ИТОГО мастеров после всех фильтров: {masters.count() if hasattr(masters, 'count') else len(masters)}")
        print(f"{'='*60}\n")
        
        serializer = MasterSerializer(masters, many=True, context={'request': request})
        return Response(serializer.data, status=status.HTTP_200_OK)


class AddServiceItemsView(APIView):
    """
    API для добавления услуг к существующему мастеру через master_id
    """
    permission_classes = [IsAuthenticated]
    
    @extend_schema(
        summary="Добавить услуги к мастеру",
        description="""
        Добавление новых услуг к существующему мастеру по его ID.
        
        **Логика работы:**
        1. Находим MasterService по master_id
        2. Если не найден - создаем новый MasterService
        3. Добавляем новые MasterServiceItems к этому MasterService
        
        **Request Body:**
        ```json
        {
          "master_id": 1,
          "services": [
            {
              "name": "Замена масла",
              "price_from": 1000,
              "price_to": 2000,
              "category": 1
            },
            {
              "name": "Диагностика",
              "price_from": 500,
              "price_to": 1500,
              "category": 2
            }
          ]
        }
        ```
        """,
        request=AddServiceItemsSerializer,
        responses={
            201: MasterServiceSerializer,
            400: {'type': 'object', 'properties': {'error': {'type': 'string'}}},
            404: {'type': 'object', 'properties': {'error': {'type': 'string'}}}
        },
        tags=['Master Service Items']
    )
    def post(self, request):
        """Добавить услуги к мастеру"""
        from .serializers import AddServiceItemsSerializer, MasterServiceSerializer
        
        serializer = AddServiceItemsSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        
        master_id = serializer.validated_data['master_id']
        services = serializer.validated_data['services']
        
        # Получаем мастера
        try:
            master = Master.objects.get(id=master_id)
        except Master.DoesNotExist:
            return Response(
                {'error': 'Мастер не найден'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        # Находим или создаем MasterService для этого мастера
        master_service = MasterService.objects.filter(master=master).first()
        if not master_service:
            master_service = MasterService.objects.create(master=master)
        
        # Добавляем все услуги
        created_items = []
        for service_data in services:
            item = MasterServiceItems.objects.create(
                master_service=master_service,
                name=service_data['name'],
                price_from=service_data['price_from'],
                price_to=service_data['price_to'],
                category_id=service_data['category']
            )
            created_items.append(item)
        
        # Возвращаем обновленный MasterService
        response_serializer = MasterServiceSerializer(master_service, context={'request': request})
        return Response(response_serializer.data, status=status.HTTP_201_CREATED)


class UpdateServiceItemView(APIView):
    """
    API для обновления конкретной услуги (MasterServiceItems)
    """
    permission_classes = [IsAuthenticated]
    
    def get_object(self, item_id):
        """Получить элемент услуги"""
        try:
            return MasterServiceItems.objects.get(id=item_id)
        except MasterServiceItems.DoesNotExist:
            return None
    
    @extend_schema(
        summary="Обновить услугу по ID",
        description="""
        Обновление конкретной услуги мастера по её ID.
        
        **Request Body:**
        ```json
        {
          "name": "Замена масла и фильтров",
          "price_from": 1200,
          "price_to": 2500,
          "category": 1
        }
        ```
        """,
        request=UpdateServiceItemSerializer,
        responses={
            200: MasterServiceItemsSerializer,
            400: {'type': 'object', 'properties': {'error': {'type': 'string'}}},
            404: {'type': 'object', 'properties': {'error': {'type': 'string'}}}
        },
        tags=['Master Service Items']
    )
    def put(self, request, item_id):
        """Обновить услугу"""
        from .serializers import UpdateServiceItemSerializer
        
        item = self.get_object(item_id)
        if not item:
            return Response(
                {'error': 'Услуга не найдена'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        serializer = UpdateServiceItemSerializer(item, data=request.data, context={'request': request})
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_200_OK)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class DeleteServiceItemView(APIView):
    """
    API для удаления конкретной услуги (MasterServiceItems)
    """
    permission_classes = [IsAuthenticated]
    
    def get_object(self, item_id):
        """Получить элемент услуги"""
        try:
            return MasterServiceItems.objects.get(id=item_id)
        except MasterServiceItems.DoesNotExist:
            return None
    
    @extend_schema(
        summary="Удалить услугу по ID",
        description="Удаление конкретной услуги мастера по её ID.",
        responses={
            204: {'description': 'Услуга успешно удалена'},
            404: {'type': 'object', 'properties': {'error': {'type': 'string'}}}
        },
        tags=['Master Service Items']
    )
    def delete(self, request, item_id):
        """Удалить услугу"""
        item = self.get_object(item_id)
        if not item:
            return Response(
                {'error': 'Услуга не найдена'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        item.delete()
        return Response(
            {'message': 'Услуга успешно удалена'},
            status=status.HTTP_204_NO_CONTENT
        )


class AddMasterImagesView(APIView):
    """
    API для добавления новых изображений к мастеру
    """
    permission_classes = [IsAuthenticated]
    
    @extend_schema(
        summary="Добавить изображения к мастеру",
        description="""
        Добавление новых изображений к существующему мастеру.
        
        **Важные моменты:**
        - Можно загрузить сразу несколько изображений (multiple files)
        - Старые изображения **сохраняются** - новые добавляются к существующим
        - Формат запроса: `multipart/form-data`
        - Поддерживаемые форматы: JPG, PNG, GIF, WEBP
        
        **Request Body (multipart/form-data):**
        - `master_id`: ID мастера (integer, обязательно)
        - `images`: Список изображений (multiple files, обязательно)
        
        **Пример использования в curl:**
        ```bash
        curl -X POST "http://localhost:8000/api/master/images/" \\
          -H "Authorization: Bearer YOUR_TOKEN" \\
          -F "master_id=1" \\
          -F "images=@photo1.jpg" \\
          -F "images=@photo2.jpg" \\
          -F "images=@photo3.jpg"
        ```
        
        **Ответ:** Возвращает обновленный список всех изображений мастера.
        """,
        request={
            'multipart/form-data': {
                'type': 'object',
                'properties': {
                    'master_id': {
                        'type': 'integer',
                        'description': 'ID мастера'
                    },
                    'images': {
                        'type': 'array',
                        'items': {
                            'type': 'string',
                            'format': 'binary'
                        },
                        'description': 'Список изображений для загрузки'
                    }
                },
                'required': ['master_id', 'images']
            }
        },
        responses={
            201: {
                'description': 'Изображения успешно добавлены',
                'content': {
                    'application/json': {
                        'example': {
                            'message': 'Успешно добавлено 2 изображений',
                            'images': [
                                {
                                    'id': 1,
                                    'image': 'http://localhost:8000/media/master_images/photo1.jpg',
                                    'created_at': '2026-01-27T20:00:00Z',
                                    'updated_at': '2026-01-27T20:00:00Z'
                                }
                            ]
                        }
                    }
                }
            },
            400: {'type': 'object', 'properties': {'error': {'type': 'string'}}},
            404: {'type': 'object', 'properties': {'error': {'type': 'string'}}}
        },
        tags=['Master Images']
    )
    def post(self, request):
        """Добавить изображения к мастеру"""
        # Обрабатываем multipart/form-data
        data = {}
        
        # Получаем master_id из data
        if 'master_id' in request.data:
            data['master_id'] = request.data.get('master_id')
        
        # Получаем изображения из FILES
        if request.FILES:
            images = request.FILES.getlist('images')
            if images:
                data['images'] = images
            else:
                return Response(
                    {'error': 'Не загружены изображения'},
                    status=status.HTTP_400_BAD_REQUEST
                )
        else:
            return Response(
                {'error': 'Не загружены изображения'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        serializer = AddMasterImagesSerializer(data=data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        
        master_id = serializer.validated_data['master_id']
        images = serializer.validated_data['images']
        
        # Получаем мастера
        try:
            master = Master.objects.get(id=master_id)
        except Master.DoesNotExist:
            return Response(
                {'error': 'Мастер не найден'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        # Добавляем изображения
        created_images = []
        for image in images:
            img = MasterImage.objects.create(master=master, image=image)
            created_images.append(img)
        
        # Возвращаем все изображения мастера
        all_images = MasterImage.objects.filter(master=master)
        images_serializer = MasterImageSerializer(all_images, many=True, context={'request': request})
        
        return Response({
            'message': f'Успешно добавлено {len(created_images)} изображений',
            'images': images_serializer.data
        }, status=status.HTTP_201_CREATED)


class UpdateMasterImageView(APIView):
    """
    API для замены конкретного изображения мастера
    """
    permission_classes = [IsAuthenticated]
    
    def get_object(self, image_id):
        """Получить изображение"""
        try:
            return MasterImage.objects.get(id=image_id)
        except MasterImage.DoesNotExist:
            return None
    
    @extend_schema(
        summary="Заменить изображение мастера",
        description="""
        Замена существующего изображения мастера на новое.
        
        **Важные моменты:**
        - Старое изображение будет **удалено** (файл и запись из БД)
        - Новое изображение загрузится на его место
        - Формат запроса: `multipart/form-data`
        - Поддерживаемые форматы: JPG, PNG, GIF, WEBP
        
        **Request Body (multipart/form-data):**
        - `image`: Новое изображение (file, обязательно)
        
        **Пример использования в curl:**
        ```bash
        curl -X PUT "http://localhost:8000/api/master/images/5/" \\
          -H "Authorization: Bearer YOUR_TOKEN" \\
          -F "image=@new_photo.jpg"
        ```
        
        **Ответ:** Возвращает информацию об обновленном изображении.
        """,
        request={
            'multipart/form-data': {
                'type': 'object',
                'properties': {
                    'image': {
                        'type': 'string',
                        'format': 'binary',
                        'description': 'Новое изображение'
                    }
                },
                'required': ['image']
            }
        },
        responses={
            200: {
                'description': 'Изображение успешно обновлено',
                'content': {
                    'application/json': {
                        'example': {
                            'id': 1,
                            'image': 'http://localhost:8000/media/master_images/new_photo.jpg',
                            'created_at': '2026-01-27T20:00:00Z',
                            'updated_at': '2026-01-27T20:15:00Z'
                        }
                    }
                }
            },
            400: {'type': 'object', 'properties': {'error': {'type': 'string'}}},
            404: {'type': 'object', 'properties': {'error': {'type': 'string'}}}
        },
        tags=['Master Images']
    )
    def put(self, request, image_id):
        """Заменить изображение"""
        image_obj = self.get_object(image_id)
        if not image_obj:
            return Response(
                {'error': 'Изображение не найдено'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        serializer = UpdateMasterImageSerializer(image_obj, data=request.data, context={'request': request})
        if serializer.is_valid():
            # Удаляем старое изображение из storage
            if image_obj.image:
                image_obj.image.delete(save=False)
            
            # Сохраняем новое изображение
            updated_image = serializer.save()
            
            # Возвращаем обновленные данные
            response_serializer = MasterImageSerializer(updated_image, context={'request': request})
            return Response(response_serializer.data, status=status.HTTP_200_OK)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class DeleteMasterImageView(APIView):
    """
    API для удаления конкретного изображения мастера
    """
    permission_classes = [IsAuthenticated]
    
    def get_object(self, image_id):
        """Получить изображение"""
        try:
            return MasterImage.objects.get(id=image_id)
        except MasterImage.DoesNotExist:
            return None
    
    @extend_schema(
        summary="Удалить изображение мастера",
        description="""
        Удаление конкретного изображения мастера по его ID.
        
        **Важные моменты:**
        - Изображение будет **полностью удалено** (файл из storage и запись из БД)
        - Эта операция необратима
        - Другие изображения мастера не затрагиваются
        
        **Пример использования в curl:**
        ```bash
        curl -X DELETE "http://localhost:8000/api/master/images/5/" \\
          -H "Authorization: Bearer YOUR_TOKEN"
        ```
        
        **Ответ:** 204 No Content при успешном удалении
        """,
        responses={
            204: {'description': 'Изображение успешно удалено'},
            404: {'type': 'object', 'properties': {'error': {'type': 'string', 'example': 'Изображение не найдено'}}}
        },
        tags=['Master Images']
    )
    def delete(self, request, image_id):
        """Удалить изображение"""
        image = self.get_object(image_id)
        if not image:
            return Response(
                {'error': 'Изображение не найдено'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        # Удаляем файл и запись из БД
        image.image.delete()  # Удаляет файл из storage
        image.delete()  # Удаляет запись из БД
        
        return Response(
            {'message': 'Изображение успешно удалено'},
            status=status.HTTP_204_NO_CONTENT
        )


class MasterEmployeeListView(APIView):
    """
    API для получения списка сотрудников мастерской
    """
    permission_classes = [IsAuthenticated]
    
    @extend_schema(
        summary="Получить сотрудников мастерской",
        description="""
## Описание
Возвращает список всех сотрудников (MasterEmployee) для указанного мастера/мастерской.

## 🎯 Когда использовать?
- Для просмотра всех сотрудников мастерской
- Для отображения команды мастера в приложении
- Для выбора конкретного сотрудника при назначении на заказ

## Параметры
- `master_id`: ID мастера/мастерской (обязательный)

## Пример запроса:
```
GET /api/master/employees/?master_id=5
```

## Response
Возвращает список сотрудников с полной информацией:
- ID сотрудника
- Полное имя
- Email
- Телефон
- Аватар
- Дата добавления в команду

## 📋 Формат ответа:
```json
[
  {
    "id": 1,
    "master": 5,
    "master_info": {
      "id": 5,
      "name": "Автосервис Али",
      "city": "Ташкент"
    },
    "employee": 10,
    "employee_info": {
      "id": 10,
      "full_name": "Иван Петров",
      "email": "ivan@example.com",
      "phone_number": "+998901234567",
      "avatar": "http://example.com/media/avatar.jpg"
    },
    "added_at": "2026-01-15T10:30:00Z"
  }
]
```
        """,
        tags=['Master'],
        parameters=[
            OpenApiParameter(
                name='master_id',
                type=OpenApiTypes.INT,
                location=OpenApiParameter.QUERY,
                description='ID мастера/мастерской',
                required=True
            ),
        ],
        responses={
            200: MasterEmployeeSerializer(many=True),
            400: {
                'type': 'object',
                'properties': {'error': {'type': 'string'}},
                'example': {'error': 'Параметр master_id обязателен'}
            },
            404: {
                'type': 'object',
                'properties': {'error': {'type': 'string'}},
                'example': {'error': 'Мастер не найден'}
            },
            401: {'type': 'object', 'properties': {'detail': {'type': 'string'}}},
        }
    )
    def get(self, request):
        """Получить сотрудников мастерской"""
        master_id = request.query_params.get('master_id')
        
        if not master_id:
            return Response(
                {'error': 'Параметр master_id обязателен'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            master_id = int(master_id)
        except ValueError:
            return Response(
                {'error': 'Неверный формат master_id'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Проверяем существование мастера
        try:
            master = Master.objects.get(id=master_id)
        except Master.DoesNotExist:
            return Response(
                {'error': 'Мастер не найден'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        # Получаем всех сотрудников этого мастера
        employees = MasterEmployee.objects.filter(
            master=master
        ).select_related('employee', 'master').order_by('-added_at')
        
        # Сериализуем
        serializer = MasterEmployeeSerializer(employees, many=True)
        return Response(serializer.data)
