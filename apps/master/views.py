from rest_framework.views import APIView
from rest_framework import status
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.parsers import JSONParser, MultiPartParser, FormParser
from drf_spectacular.utils import extend_schema, OpenApiExample, OpenApiParameter
from drf_spectacular.types import OpenApiTypes
from django.db.models import Q
from .models import Master, MasterBusySlot, MasterImage, MasterScheduleDay, MasterService, MasterServiceItems
from .serializers import (
    MasterSerializer, MasterCreateSerializer, MasterUpdateSerializer, MasterNearbySerializer,
    MasterServiceSerializer, MasterServiceItemsSerializer,
    AddServiceItemsSerializer, UpdateServiceItemSerializer, AddMasterImagesSerializer,
    UpdateMasterImageSerializer, MasterImageSerializer,
    MasterScheduleDaySerializer, MasterScheduleBulkSerializer,
    MasterBusySlotSerializer,
)
from .permissions import IsMasterGroup
from .images_utils import save_master_images_from_request
from django.contrib.auth import get_user_model
from apps.accounts.services import SMSService

User = get_user_model()

from .serializers import (
    ServiceCardGroupSerializer,
    ServiceCardSerializer,
    ServiceCardsResponseSerializer,
)


class MasterProfileView(APIView):
    """
    API для управления профилем мастера.
    
    Поддерживаемые операции:
    - GET: получение профилей мастерских где пользователь является владельцем
    - POST: создание профиля мастера (доступно ТОЛЬКО для группы Master)
    """

    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def get_permissions(self):
        """Разные права доступа для разных методов"""
        if self.request.method == 'POST':
            return [IsMasterGroup()]
        elif self.request.method == 'GET':
            return [AllowAny()]
        return [IsMasterGroup()]
    
    def get_object(self):
        """
        Мастерские, где пользователь — владелец (Master.user).
        """
        return Master.objects.filter(user=self.request.user)
    
    @extend_schema(
        summary="Получить профиль мастера",
        description="""
        Получить профили мастерских текущего пользователя. Доступно для всех пользователей (публичный доступ).
        
        **Логика поиска:**
        - Если пользователь авторизован, возвращаются мастерские где он владелец (Master.user).
        - Если не авторизован — пустой список
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
        summary="Создать профиль мастера (только группа Master)",
        description="""
        Создание нового профиля мастера. Доступно только пользователям в группе **Master**.
        
        **ВАЖНО**: JWT обязателен; пользователь должен быть в группе Django `Master`.
        
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
        - `images`: Файлы (multipart) — поле можно повторять несколько раз для нескольких фото
        
        **Навыки (цены по подкатегориям)** не передаются при создании. Используйте
        `POST /api/master/service-items/` (`master_id` не обязателен, если у вас одна мастерская).
        
        **Примечания:**
        - User автоматически берется из текущего авторизованного пользователя
        - Категории должны существовать в базе данных и иметь тип 'by_master'
        - После создания мастерской пользователь остаётся/снова добавляется в группу 'Master' (если ещё не был)
        - Можно создать мастерскую вообще без данных и заполнить потом через PUT/PATCH
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
            403: {'type': 'object', 'properties': {'detail': {'type': 'string', 'example': "Нет доступа: нужна группа 'Master'"}}}
        },
        tags=['Masters']
    )
    def post(self, request):
        """Создание профиля мастера (только группа Master)"""
        serializer = MasterCreateSerializer(data=request.data, context={'request': request})
        if serializer.is_valid():
            master = serializer.save()
            save_master_images_from_request(master, request)
            response_serializer = MasterSerializer(master, context={'request': request})
            return Response([response_serializer.data], status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class MasterListView(APIView):
    """
    API для получения списка мастеров (публичный доступ).
    Без query-параметров возвращаются все мастера (сортировка по модели, обычно новые первые).
    Опционально можно сузить выборку: category, name, lat/long/radius.
    """
    permission_classes = [AllowAny]
    
    @extend_schema(
        summary="Получить список мастеров (все или с фильтрами)",
        description="""
        Список мастеров. **Без параметров** — все записи из БД.
        
        **Опциональные query-параметры:**
        - `category` - ID категории (by_order или by_master). При by_order ищет мастеров через дерево parent / название
        - `name` - Название мастерской (поиск по частичному совпадению)
        - `lat` / `long` - геоточка пользователя; вместе с `radius` (км, по умолчанию 10) оставляют мастеров в радиусе
        
        **Примеры:**
        - `/api/master/masters/list/` — полный список
        - `/api/master/masters/list/?category=1` - мастера по категории (умный поиск)
        - `/api/master/masters/list/?name=Авто` - поиск по названию
        - `/api/master/masters/list/?lat=41.3111&long=69.2797&radius=5` - мастера в радиусе 5 км
        - `/api/master/masters/list/?category=1&lat=41.3111&long=69.2797&radius=10` - комбинация фильтров
        
        **Умный поиск по категории:**
        - Если category типа by_order: ищет мастеров через MasterServiceItems по parent / названию
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
        """Список мастеров: без параметров — все; иначе фильтрация."""
        category_id = request.query_params.get('category')
        name = request.query_params.get('name')
        user_lat = request.query_params.get('lat')
        user_long = request.query_params.get('long')
        radius = request.query_params.get('radius', 10)  # По умолчанию 10 км

        masters = Master.objects.all()
        
        from apps.categories.models import Category
        from apps.categories.query import (
            master_by_order_category_smart_q,
            master_by_order_category_strict_q,
        )
        from django.db.models import Q
        
        # Собираем все условия поиска (OR между ними)
        search_conditions = Q()
        filter_service_category_id = None
        
        # Фильтр по категории (умный поиск)
        if category_id:
            try:
                category_id = int(category_id)
                category = Category.objects.get(id=category_id)
                strict = getattr(self, '_nearby_category_strict', False)
                
                # Если category типа by_order (из заказа)
                if category.type_category == 'by_order':
                    if strict:
                        search_conditions |= master_by_order_category_strict_q(category)
                        filter_service_category_id = category_id
                    else:
                        search_conditions |= master_by_order_category_smart_q(category)
                
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
            # Поиск по названию услуги (подкатегория) и группы
            name_conditions |= Q(master_services__master_service_items__category__name__icontains=name)
            name_conditions |= Q(master_services__master_service_items__category__parent__name__icontains=name)
            # Поиск в категориях самого Master
            name_conditions |= Q(category__name__icontains=name)
            name_conditions |= Q(category__parent__name__icontains=name)
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
        sctx = {'request': request}
        if filter_service_category_id is not None:
            sctx['filter_service_category_id'] = filter_service_category_id
        serializer = MasterSerializer(masters, many=True, context=sctx)
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
    PUT/PATCH/DELETE - группа Master и только владелец профиля (Master.user)
    """

    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def get_permissions(self):
        """Разные права доступа для разных методов"""
        if self.request.method in ['PUT', 'PATCH', 'DELETE']:
            return [IsMasterGroup()]
        elif self.request.method == 'GET':
            return [AllowAny()]
        return [IsAuthenticated()]

    def _master_write_forbidden(self, request, master):
        """Только владелец мастерской может менять/удалять этот профиль."""
        if master.user_id != request.user.id:
            return Response(
                {'detail': 'Вы можете изменять только свою мастерскую.'},
                status=status.HTTP_403_FORBIDDEN,
            )
        return None
    
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
        summary="Обновить мастера по ID (группа Master, свой профиль)",
        description="""
        Полное обновление информации о мастерской. Доступно пользователям в группе **Master**,
        и только для мастерской, где вы владелец (`Master.user` = текущий пользователь).
        
        **ВАЖНО**: JWT и группа `Master`; `master_id` должен быть вашей мастерской.
        
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
        
        Дополнительно в том же запросе можно передать новые файлы в поле `images`
        (multipart, поле можно повторять). Старые фото не удаляются; удаление — через
        DELETE /api/master/images/{image_id}/.
        """,
        request=MasterUpdateSerializer,
        responses={
            200: MasterSerializer,
            400: {'type': 'object', 'properties': {'detail': {'type': 'string'}}},
            404: {'type': 'object', 'properties': {'error': {'type': 'string'}}},
            403: {'type': 'object', 'properties': {'detail': {'type': 'string', 'example': "Нет доступа: группа Master и только своя мастерская"}}}
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
        denied = self._master_write_forbidden(request, master)
        if denied:
            return denied

        serializer = MasterUpdateSerializer(master, data=request.data, context={'request': request})
        if serializer.is_valid():
            updated_master = serializer.save()
            save_master_images_from_request(updated_master, request)
            response_serializer = MasterSerializer(updated_master, context={'request': request})
            return Response(response_serializer.data, status=status.HTTP_200_OK)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    @extend_schema(
        summary="Частичное обновление мастера по ID (группа Master, свой профиль)",
        description="""
        Частичное обновление. Группа **Master**; можно менять только мастерскую, владельцем которой вы являетесь.
        
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
        
        Новые файлы в поле `images` (multipart, повторяемое) добавляются к галерее.
        """,
        request=MasterUpdateSerializer,
        responses={
            200: MasterSerializer,
            400: {'type': 'object', 'properties': {'detail': {'type': 'string', 'example': 'Ошибка валидации данных'}}},
            404: {'type': 'object', 'properties': {'error': {'type': 'string', 'example': 'Мастер не найден'}}},
            403: {'type': 'object', 'properties': {'detail': {'type': 'string', 'example': "Нет доступа: группа Master и только своя мастерская"}}}
        },
        tags=['Masters']
    )
    def patch(self, request, master_id):
        """Частичное обновление мастера (группа Master)"""
        master = self.get_object(master_id)
        if not master:
            return Response(
                {'error': 'Мастер не найден'}, 
                status=status.HTTP_404_NOT_FOUND
            )
        denied = self._master_write_forbidden(request, master)
        if denied:
            return denied

        serializer = MasterUpdateSerializer(master, data=request.data, partial=True, context={'request': request})
        if serializer.is_valid():
            updated_master = serializer.save()
            save_master_images_from_request(updated_master, request)
            response_serializer = MasterSerializer(updated_master, context={'request': request})
            return Response(response_serializer.data, status=status.HTTP_200_OK)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    @extend_schema(
        summary="Удалить мастера по ID (группа Master, свой профиль)",
        description="""
        Удаление мастерской. Группа **Master**; удалить можно только свою мастерскую (`Master.user`).
        
        **ВНИМАНИЕ**: Это действие удалит мастерскую и все связанные с ней данные (услуги, изображения и т.д.)
        """,
        responses={
            204: {'description': 'Мастер успешно удален'},
            404: {'type': 'object', 'properties': {'error': {'type': 'string', 'example': 'Мастер не найден'}}},
            403: {'type': 'object', 'properties': {'detail': {'type': 'string', 'example': "Нет доступа: группа Master и только своя мастерская"}}}
        },
        tags=['Masters']
    )
    def delete(self, request, master_id):
        """Удаление мастера (группа Master)"""
        master = self.get_object(master_id)
        if not master:
            return Response(
                {'error': 'Мастер не найден'}, 
                status=status.HTTP_404_NOT_FOUND
            )
        denied = self._master_write_forbidden(request, master)
        if denied:
            return denied

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
        
        **Формат:** `master_items`: `[{"category": <id категории by_master>, "price": 100}, ...]`
        """,
        request=MasterServiceSerializer,
        examples=[
            OpenApiExample(
                'Пример создания услуги мастера',
                value={
                    "master_items": [
                        {"category": 101, "price": 150000},
                        {"category": 102, "price": 100000},
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
        
        services = (
            MasterServiceItems.objects.select_related('category')
            .values_list('category__name', flat=True)
            .distinct()
            .order_by('category__name')
        )
        services_list = [s for s in services if s]
        
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
                description='Фильтр по названию подкатегории услуги (category.name)',
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
        
        # Фильтр по услугам (service_items) — по имени подкатегории
        service_items = request.query_params.getlist('service_items')
        if service_items:
            service_conditions = Q()
            for service_item in service_items:
                service_conditions |= Q(
                    master_services__master_service_items__category__name__icontains=service_item
                )
                service_conditions |= Q(
                    master_services__master_service_items__category__parent__name__icontains=service_item
                )
            masters = masters.filter(service_conditions).distinct()

        # Фильтр по категориям - MULTIPLE
        categories = request.query_params.getlist('category')
        if categories:
            try:
                category_ids = [int(cat_id) for cat_id in categories if cat_id and int(cat_id) > 0]
                if category_ids:
                    masters = masters.filter(category__id__in=category_ids).distinct()
            except (ValueError, TypeError):
                pass

        # Фильтр по городам/районам - MULTIPLE
        locations = request.query_params.getlist('location')
        if locations:
            location_conditions = Q()
            for location in locations:
                location_conditions |= Q(city__icontains=location) | Q(address__icontains=location)
            masters = masters.filter(location_conditions)
        
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
        
        serializer = MasterSerializer(masters, many=True, context={'request': request})
        return Response(serializer.data, status=status.HTTP_200_OK)


class AddServiceItemsView(APIView):
    """
    Добавить навыки (подкатегория + цена) к мастерской.
    `master_id` обязателен только если у пользователя несколько мастерских.
    """
    permission_classes = [IsMasterGroup]

    @extend_schema(
        summary="Добавить услуги к мастеру",
        description="""
        Добавление услуг к мастерской текущего пользователя.

        **`master_id`** — если у вас **одна** мастерская (`Master.user`), поле можно не передавать.
        Если мастерских **несколько** — укажите `master_id` (только своя).

        **Логика:** находим или создаём `MasterService`, затем `MasterServiceItems` (upsert по паре master_service + category).

        **Тело:** `services` — `[{"category": <id категории by_master>, "price": 100000}, ...]`
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

        serializer = AddServiceItemsSerializer(data=request.data, context={'request': request})
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
            item, _ = MasterServiceItems.objects.update_or_create(
                master_service=master_service,
                category_id=service_data['category'],
                defaults={'price': service_data['price']},
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
        
        **Request Body:** `price` и/или `category` (категория by_master).
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
        
        serializer = UpdateServiceItemSerializer(item, data=request.data, partial=True, context={'request': request})
        if serializer.is_valid():
            serializer.save()
            out = MasterServiceItemsSerializer(item, context={'request': request})
            return Response(out.data, status=status.HTTP_200_OK)
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


def _resolve_schedule_master(request):
    """
    Расписание и busy-слоты привязаны к модели Master (не напрямую к User).
    JWT-user должен быть Master.user. Если мастерских несколько — передайте ?master_id=.
    """
    user = request.user
    qs = Master.objects.filter(user=user)
    mid = request.query_params.get('master_id')
    if mid in (None, ''):
        if not qs.exists():
            return None, Response(
                {'error': 'Профиль мастера не найден'},
                status=status.HTTP_404_NOT_FOUND,
            )
        if qs.count() > 1:
            return None, Response(
                {
                    'error': 'Укажите master_id в query (несколько мастерских).',
                    'master_ids': list(qs.values_list('id', flat=True)),
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        return qs.first(), None
    try:
        return qs.get(pk=int(mid)), None
    except (ValueError, TypeError, Master.DoesNotExist):
        return None, Response(
            {'error': 'Мастер не найден или не ваш'},
            status=status.HTTP_404_NOT_FOUND,
        )


class MasterScheduleListBulkView(APIView):
    """GET: list schedule days; POST: bulk upsert days (owner = current master's user)."""

    permission_classes = [IsMasterGroup]

    @extend_schema(
        summary='Расписание мастера (список)',
        parameters=[
            OpenApiParameter(name='date_from', type=OpenApiTypes.DATE, location=OpenApiParameter.QUERY, required=False),
            OpenApiParameter(name='date_to', type=OpenApiTypes.DATE, location=OpenApiParameter.QUERY, required=False),
            OpenApiParameter(
                name='master_id',
                type=int,
                location=OpenApiParameter.QUERY,
                required=False,
                description='Если у пользователя несколько мастерских — ID нужной мастерской',
            ),
        ],
        responses={200: MasterScheduleDaySerializer(many=True)},
        tags=['Master Schedule'],
    )
    def get(self, request):
        master, err = _resolve_schedule_master(request)
        if err:
            return err
        qs = MasterScheduleDay.objects.filter(master=master).order_by('date')
        df = request.query_params.get('date_from')
        dt = request.query_params.get('date_to')
        if df:
            qs = qs.filter(date__gte=df)
        if dt:
            qs = qs.filter(date__lte=dt)
        return Response(MasterScheduleDaySerializer(qs, many=True).data)

    @extend_schema(
        summary='Расписание: массовое сохранение дней',
        parameters=[
            OpenApiParameter(
                name='master_id',
                type=int,
                location=OpenApiParameter.QUERY,
                required=False,
                description='Несколько мастерских — ID мастерской (тот же query, что и у GET)',
            ),
        ],
        request=MasterScheduleBulkSerializer,
        responses={201: MasterScheduleDaySerializer(many=True)},
        tags=['Master Schedule'],
    )
    def post(self, request):
        master, err = _resolve_schedule_master(request)
        if err:
            return err
        ser = MasterScheduleBulkSerializer(data=request.data)
        if not ser.is_valid():
            return Response(ser.errors, status=status.HTTP_400_BAD_REQUEST)
        for day in ser.validated_data['days']:
            MasterScheduleDay.objects.update_or_create(
                master=master,
                date=day['date'],
                defaults={'start_time': day['start_time'], 'end_time': day['end_time']},
            )
        out = MasterScheduleDay.objects.filter(master=master).order_by('date')
        return Response(MasterScheduleDaySerializer(out, many=True).data, status=status.HTTP_201_CREATED)


class MasterScheduleDayDetailView(APIView):
    permission_classes = [IsMasterGroup]

    def get_object(self, pk, user):
        try:
            row = MasterScheduleDay.objects.select_related('master').get(pk=pk)
        except MasterScheduleDay.DoesNotExist:
            return None
        if row.master.user_id != user.id:
            return None
        return row

    @extend_schema(summary='Удалить день расписания', responses={204: None}, tags=['Master Schedule'])
    def delete(self, request, pk):
        row = self.get_object(pk, request.user)
        if not row:
            return Response({'error': 'Не найдено'}, status=status.HTTP_404_NOT_FOUND)
        row.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    @extend_schema(
        summary='Изменить день расписания',
        request=MasterScheduleDaySerializer,
        responses={200: MasterScheduleDaySerializer},
        tags=['Master Schedule'],
    )
    def patch(self, request, pk):
        row = self.get_object(pk, request.user)
        if not row:
            return Response({'error': 'Не найдено'}, status=status.HTTP_404_NOT_FOUND)
        ser = MasterScheduleDaySerializer(row, data=request.data, partial=True)
        if ser.is_valid():
            ser.save()
            return Response(ser.data)
        return Response(ser.errors, status=status.HTTP_400_BAD_REQUEST)


class MasterBusySlotListCreateView(APIView):
    """Ручная занятость (без заказа) или просмотр своих слотов с заказами."""

    permission_classes = [IsMasterGroup]

    @extend_schema(
        summary='Список занятых интервалов',
        parameters=[
            OpenApiParameter(name='date_from', type=OpenApiTypes.DATE, location=OpenApiParameter.QUERY, required=False),
            OpenApiParameter(name='date_to', type=OpenApiTypes.DATE, location=OpenApiParameter.QUERY, required=False),
            OpenApiParameter(name='manual_only', type=OpenApiTypes.BOOL, location=OpenApiParameter.QUERY, required=False),
            OpenApiParameter(
                name='master_id',
                type=int,
                location=OpenApiParameter.QUERY,
                required=False,
                description='Несколько мастерских — ID мастерской',
            ),
        ],
        responses={200: MasterBusySlotSerializer(many=True)},
        tags=['Master Schedule'],
    )
    def get(self, request):
        master, err = _resolve_schedule_master(request)
        if err:
            return err
        qs = MasterBusySlot.objects.filter(master=master).order_by('date', 'start_time')
        df = request.query_params.get('date_from')
        dt = request.query_params.get('date_to')
        if df:
            qs = qs.filter(date__gte=df)
        if dt:
            qs = qs.filter(date__lte=dt)
        if request.query_params.get('manual_only', '').lower() in ('1', 'true', 'yes'):
            qs = qs.filter(order__isnull=True)
        data = MasterBusySlotSerializer(qs, many=True).data
        return Response(data)

    @extend_schema(
        summary='Добавить ручной занятый интервал',
        parameters=[
            OpenApiParameter(
                name='master_id',
                type=int,
                location=OpenApiParameter.QUERY,
                required=False,
                description='Несколько мастерских — ID мастерской',
            ),
        ],
        request=MasterBusySlotSerializer,
        responses={201: MasterBusySlotSerializer},
        tags=['Master Schedule'],
    )
    def post(self, request):
        master, err = _resolve_schedule_master(request)
        if err:
            return err
        ser = MasterBusySlotSerializer(data=request.data)
        if not ser.is_valid():
            return Response(ser.errors, status=status.HTTP_400_BAD_REQUEST)
        slot = MasterBusySlot.objects.create(
            master=master,
            date=ser.validated_data['date'],
            start_time=ser.validated_data['start_time'],
            end_time=ser.validated_data['end_time'],
            reason=ser.validated_data.get('reason', ''),
            order=None,
        )
        return Response(MasterBusySlotSerializer(slot).data, status=status.HTTP_201_CREATED)


class MasterBusySlotDetailView(APIView):
    permission_classes = [IsMasterGroup]

    def get_object(self, pk, user):
        try:
            slot = MasterBusySlot.objects.select_related('master').get(pk=pk)
        except MasterBusySlot.DoesNotExist:
            return None
        if slot.master.user_id != user.id:
            return None
        return slot

    @extend_schema(
        summary='Изменить ручной слот (заказы нельзя менять здесь)',
        request=MasterBusySlotSerializer,
        responses={200: MasterBusySlotSerializer},
        tags=['Master Schedule'],
    )
    def patch(self, request, pk):
        slot = self.get_object(pk, request.user)
        if not slot:
            return Response({'error': 'Не найдено'}, status=status.HTTP_404_NOT_FOUND)
        if slot.order_id:
            return Response(
                {'error': 'Слот привязан к заказу; измените заказ или отмените его.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        ser = MasterBusySlotSerializer(slot, data=request.data, partial=True)
        if ser.is_valid():
            ser.save()
            return Response(MasterBusySlotSerializer(slot).data)
        return Response(ser.errors, status=status.HTTP_400_BAD_REQUEST)

    @extend_schema(summary='Удалить ручной слот', responses={204: None}, tags=['Master Schedule'])
    def delete(self, request, pk):
        slot = self.get_object(pk, request.user)
        if not slot:
            return Response({'error': 'Не найдено'}, status=status.HTTP_404_NOT_FOUND)
        if slot.order_id:
            return Response({'error': 'Нельзя удалить слот заказа'}, status=status.HTTP_400_BAD_REQUEST)
        slot.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class MasterServiceCardsView(APIView):
    """
    UI uchun service cards:
    - har bir by_master category bo'yicha (ota kategoriya bo'yicha group)
    - price min/max/avg: MasterServiceItems.price dan
    - stars: Masterga berilgan Rating dan (Avg)
    - "most common": group ichida masters_count bo'yicha top service
    """

    permission_classes = [AllowAny]

    @extend_schema(
        summary="Service cards (category bo'yicha)",
        description="""
        by_master kategoriyalar asosida service cards qaytaradi.

        Response'ni UI'ga "Locksmith service you need" kabi cardlar qilish uchun ishlating.

        Query params:
        - `parent_id` (int, ixtiyoriy): faqat shu ota kategoriyaning child service'lari chiqadi.
        """,
        tags=['Masters'],
        parameters=[
            OpenApiParameter(
                name='parent_id',
                type=OpenApiTypes.INT,
                location=OpenApiParameter.QUERY,
                required=False,
                description='by_master parent category id (ixtiyoriy)',
            ),
        ],
        responses={200: ServiceCardsResponseSerializer},
    )
    def get(self, request):
        from django.db.models import Avg, Count, Max, Min
        from apps.categories.models import Category
        from apps.order.models import Rating

        parent_id = request.query_params.get('parent_id')
        if parent_id in (None, ''):
            parent_id = None
        else:
            try:
                parent_id = int(parent_id)
            except (ValueError, TypeError):
                return Response({'error': 'parent_id must be int'}, status=status.HTTP_400_BAD_REQUEST)

        # 1) price + masters_count (ratings join qilmasdan, duplication bo'lmasligi uchun)
        price_qs = (
            MasterServiceItems.objects.filter(category__type_category=Category.TypeCategory.BY_MASTER)
            .values(
                'category_id',
                'category__name',
                'category__icon',
                'category__parent_id',
                'category__parent__name',
                'category__parent__icon',
            )
            .annotate(
                masters_count=Count('master_service__master', distinct=True),
                price_min=Min('price'),
                price_max=Max('price'),
                price_avg=Avg('price'),
            )
        )
        if parent_id is not None:
            price_qs = price_qs.filter(category__parent_id=parent_id)

        price_rows = list(price_qs)
        if not price_rows:
            return Response({'groups': []}, status=status.HTTP_200_OK)

        # 2) rating stats: category bo'yicha (again price joinsiz ishlaymiz)
        rating_qs = (
            MasterServiceItems.objects.filter(category__type_category=Category.TypeCategory.BY_MASTER)
            .values('category_id')
            .annotate(
                average_rating=Avg('master_service__master__ratings__rating'),
                rating_count=Count('master_service__master__ratings__id'),
            )
        )
        rating_map = {r['category_id']: r for r in rating_qs}

        # Group by parent
        def abs_url(file_field):
            """
            Category.icon odatda FileField bo'ladi, lekin .values() ishlatsak u string path bo'lib keladi.
            Shuning uchun ham FileField.url, ham string (MEDIA_ROOT ichidagi path)ni media url ga o'tkazamiz.
            """
            if not file_field:
                return None

            # absolute url bo'lsa, shunday qaytaramiz
            if isinstance(file_field, str):
                if file_field.startswith('http://') or file_field.startswith('https://'):
                    return file_field

                # request.build_absolute_uri faqat /media/... kabi pathlar bilan yaxshi ishlaydi
                try:
                    if file_field.startswith('/'):
                        return request.build_absolute_uri(file_field)
                except Exception:
                    pass

                from django.conf import settings
                media_prefix = (settings.MEDIA_URL or '').rstrip('/') + '/'
                # file_field ko'pincha "categories/icons/..." ko'rinishida keladi
                return request.build_absolute_uri(media_prefix + file_field.lstrip('/'))

            # FileField (FieldFile) bo'lsa
            url = getattr(file_field, 'url', None)
            if url:
                try:
                    return request.build_absolute_uri(url)
                except Exception:
                    return url
            return None

        groups_by_parent = {}
        for row in price_rows:
            pid = row['category__parent_id']
            group_id = pid if pid is not None else 0

            if group_id not in groups_by_parent:
                parent_name = row['category__parent__name'] if pid is not None else 'Other'
                parent_icon = abs_url(row['category__parent__icon'])
                groups_by_parent[group_id] = {
                    'parent_category_id': group_id if pid is not None else None,
                    'parent_category_name': parent_name,
                    'parent_category_icon': parent_icon,
                    'services': [],
                }

            cat_icon = abs_url(row['category__icon'])
            rating_row = rating_map.get(row['category_id'], {})

            groups_by_parent[group_id]['services'].append({
                'category_id': row['category_id'],
                'name': row['category__name'],
                'icon': cat_icon,
                'price_min': float(row['price_min']),
                'price_max': float(row['price_max']),
                'price_avg': float(row['price_avg']) if row['price_avg'] is not None else 0.0,
                'masters_count': row['masters_count'],
                'average_rating': float(rating_row.get('average_rating')) if rating_row.get('average_rating') is not None else None,
                'rating_count': int(rating_row.get('rating_count', 0) or 0),
                'is_most_common': False,  # keyin belgilaymiz
            })

        # Mark "most common" per group
        out_groups = []
        for g in groups_by_parent.values():
            services = g['services']
            services.sort(key=lambda x: x['masters_count'], reverse=True)
            if services:
                max_count = services[0]['masters_count']
                for s in services:
                    if s['masters_count'] == max_count:
                        s['is_most_common'] = True
            out_groups.append({
                'parent_category_id': g['parent_category_id'],
                'parent_category_name': g['parent_category_name'],
                'parent_category_icon': g['parent_category_icon'],
                'services': services,
            })

        # sort groups (most services first)
        out_groups.sort(key=lambda x: len(x['services']), reverse=True)
        return Response({'groups': out_groups}, status=status.HTTP_200_OK)
