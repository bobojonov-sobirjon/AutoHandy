from rest_framework.views import APIView
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework import status
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from drf_spectacular.utils import extend_schema, OpenApiParameter, OpenApiExample
from drf_spectacular.types import OpenApiTypes
from .serializers import (
    PhoneNumberSerializer, 
    IdentifierSerializer,
    SMSVerificationSerializer, 
    UserSerializer, 
    TokenResponseSerializer,
    SMSResponseSerializer,
    UserDetailsSerializer,
    UserUpdateSerializer,
    FAQSerializer,
    TelegramChatIdSerializer
)
from .services import SMSService
from .models import CustomUser, FAQ


class HealthCheckView(APIView):
    """Test endpoint for checking CORS and server status"""
    permission_classes = [AllowAny]
    
    @extend_schema(
        summary="Health check endpoint",
        description="Simple endpoint to test CORS and server connectivity",
        tags=['System'],
        responses={
            200: {
                'type': 'object',
                'properties': {
                    'status': {'type': 'string'},
                    'message': {'type': 'string'},
                    'cors_enabled': {'type': 'boolean'}
                }
            }
        }
    )
    def get(self, request):
        """Health check"""
        return Response({
            'status': 'ok',
            'message': 'Server is running',
            'cors_enabled': True,
            'method': 'GET'
        }, status=status.HTTP_200_OK)
    
    def post(self, request):
        """Health check POST"""
        return Response({
            'status': 'ok',
            'message': 'Server is running',
            'cors_enabled': True,
            'method': 'POST',
            'data_received': request.data
        }, status=status.HTTP_200_OK)


class LoginView(APIView):
    """
    Вход по email или номеру телефона (отправка SMS кода)
    """
    permission_classes = [AllowAny]
    
    @extend_schema(
        summary="Отправка кода подтверждения",
        description="Отправка 4-значного кода подтверждения на номер телефона (SMS) или email. Если пользователь не найден, создается новый пользователь автоматически. Параметр 'role' (Driver, Master или Owner) обязателен.",
        request=IdentifierSerializer,
        responses={
            200: {
                'type': 'object',
                'properties': {
                    'success': {'type': 'boolean', 'example': True},
                    'message': {'type': 'string', 'example': 'Код подтверждения отправлен на email'},
                    'identifier': {'type': 'string', 'example': 'user@example.com'},
                    'identifier_type': {'type': 'string', 'example': 'email'},
                    'phone': {'type': 'string', 'example': '998901234567', 'description': 'Номер телефона (только для phone)'},
                    'email': {'type': 'string', 'example': 'user@example.com', 'description': 'Email адрес (только для email)'},
                    'user_exists': {'type': 'boolean', 'example': True},
                    'sms_code': {'type': 'string', 'example': '1234', 'description': 'SMS код подтверждения'}
                }
            },
            400: {
                'type': 'object',
                'properties': {
                    'success': {'type': 'boolean', 'example': False},
                    'errors': {'type': 'object'}
                }
            },
            500: {
                'type': 'object',
                'properties': {
                    'success': {'type': 'boolean', 'example': False},
                    'error': {'type': 'string'}
                }
            }
        },
        tags=['Authentication']
    )
    def post(self, request):
        """Вход - отправка кода подтверждения на телефон или email"""
        serializer = IdentifierSerializer(data=request.data, context={'request': request})
        
        if not serializer.is_valid():
            return Response({
                'success': False,
                'errors': serializer.errors
            }, status=status.HTTP_400_BAD_REQUEST)
        
        identifier_data = serializer.validated_data['identifier']
        identifier = identifier_data['value']
        identifier_type = identifier_data['type']
        role = serializer.validated_data.get('role')
        
        # Отправка кода через SMS сервис
        result = SMSService.send_sms_code(identifier, identifier_type, role)
        
        if result['success']:
            # Добавление информации о существовании пользователя
            response_data = {
                'success': True,
                'message': result['message'],
                'identifier': result['identifier'],
                'identifier_type': result['identifier_type'],
                'phone': result.get('phone'),
                'email': result.get('email'),
                'user_exists': result.get('user_exists', False),
                'sms_code': result.get('sms_code')  # Добавляем SMS код в response
            }
            return Response(response_data, status=result['status_code'])
        else:
            return Response({
                'success': False,
                'error': result['error']
            }, status=result['status_code'])


class CheckSMSCodeView(APIView):
    """
    Проверка SMS кода и выдача токена
    """
    permission_classes = [AllowAny]
    
    @extend_schema(
        summary="Проверка SMS кода",
        description="Проверка SMS кода и получение JWT токена. Параметр 'role' (Driver, Master или Owner) обязателен.",
        request=SMSVerificationSerializer,
        responses={
            200: TokenResponseSerializer,
            400: {
                'type': 'object',
                'properties': {
                    'success': {'type': 'boolean', 'example': False},
                    'errors': {'type': 'object'},
                    'error': {'type': 'string'}
                }
            },
            500: {
                'type': 'object',
                'properties': {
                    'success': {'type': 'boolean', 'example': False},
                    'error': {'type': 'string'}
                }
            }
        },
        tags=['Authentication']
    )
    def post(self, request):
        """Проверка SMS кода"""
        serializer = SMSVerificationSerializer(data=request.data, context={'request': request})
        
        if not serializer.is_valid():
            return Response({
                'success': False,
                'errors': serializer.errors
            }, status=status.HTTP_400_BAD_REQUEST)
        
        identifier_data = serializer.validated_data['identifier']
        identifier = identifier_data['value']
        identifier_type = identifier_data['type']
        sms_code = serializer.validated_data['sms_code']
        role = serializer.validated_data.get('role')
        
        # Проверка кода через SMS сервис
        result = SMSService.verify_sms_code(identifier, sms_code, identifier_type, role)
        
        if result['success']:
            # Сериализация данных пользователя
            user_serializer = UserSerializer(result['user'], context={'request': request})
            
            response_data = {
                'success': True,
                'message': result['message'],
                'user': user_serializer.data,
                'user_created': result.get('user_created', False),
                'tokens': result['tokens']
            }
            
            return Response(response_data, status=result['status_code'])
        else:
            return Response({
                'success': False,
                'error': result['error']
            }, status=result['status_code'])


class SMSServiceStatusView(APIView):
    """SMS service status (Twilio primary)."""
    permission_classes = [AllowAny]

    @extend_schema(
        summary="SMS service status",
        description="Check if Twilio SMS is configured. Optionally shows SMSC balance if configured.",
        responses={
            200: {
                'type': 'object',
                'properties': {
                    'success': {'type': 'boolean'},
                    'service': {'type': 'string', 'example': 'twilio'},
                    'twilio_configured': {'type': 'boolean'},
                    'status': {'type': 'string'}
                }
            }
        },
        tags=['SMS Service']
    )
    def get(self, request):
        from django.conf import settings
        sid = getattr(settings, 'TWILIO_ACCOUNT_SID', None)
        token = getattr(settings, 'TWILIO_AUTH_TOKEN', None)
        from_number = getattr(settings, 'TWILIO_PHONE_NUMBER', None)
        twilio_ok = bool(sid and token and from_number)
        return Response({
            'success': True,
            'service': 'twilio',
            'twilio_configured': twilio_ok,
            'status': 'active' if twilio_ok else 'not_configured'
        }, status=status.HTTP_200_OK)


class UserDetailsView(APIView):
    """
    Получение и обновление информации о текущем пользователе
    """
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]
    
    @extend_schema(
        summary="Получение информации о пользователе",
        description="Получение детальной информации о текущем авторизованном пользователе",
        responses={
            200: UserDetailsSerializer,
            401: {
                'type': 'object',
                'properties': {
                    'detail': {'type': 'string', 'example': 'Authentication credentials were not provided.'}
                }
            }
        },
        tags=['User Profile']
    )
    def get(self, request):
        """Получение информации о текущем пользователе"""
        user = request.user
        serializer = UserDetailsSerializer(user, context={'request': request})
        return Response({
            'success': True,
            'user': serializer.data
        }, status=status.HTTP_200_OK)
    
    @extend_schema(
        summary="Обновление информации о пользователе",
        description="Обновление информации о текущем пользователе. Поддерживает обновление всех полей, включая avatar (файл) и роль (группу).",
        request=UserUpdateSerializer,
        responses={
            200: {
                'type': 'object',
                'properties': {
                    'success': {'type': 'boolean', 'example': True},
                    'message': {'type': 'string', 'example': 'Информация о пользователе успешно обновлена'},
                    'user': {'type': 'object'}
                }
            },
            400: {
                'type': 'object',
                'properties': {
                    'success': {'type': 'boolean', 'example': False},
                    'errors': {'type': 'object'}
                }
            },
            401: {
                'type': 'object',
                'properties': {
                    'detail': {'type': 'string', 'example': 'Authentication credentials were not provided.'}
                }
            }
        },
        tags=['User Profile']
    )
    def put(self, request):
        """Полное обновление информации о пользователе"""
        user = request.user
        serializer = UserUpdateSerializer(user, data=request.data, partial=False, context={'request': request})
        
        if serializer.is_valid():
            serializer.save()
            # Возвращаем обновленные данные через UserDetailsSerializer
            detail_serializer = UserDetailsSerializer(user, context={'request': request})
            return Response({
                'success': True,
                'message': 'Информация о пользователе успешно обновлена',
                'user': detail_serializer.data
            }, status=status.HTTP_200_OK)
        
        return Response({
            'success': False,
            'errors': serializer.errors
        }, status=status.HTTP_400_BAD_REQUEST)
    
    @extend_schema(
        summary="Частичное обновление информации о пользователе",
        description="Частичное обновление информации о текущем пользователе. Можно обновить только нужные поля. Поддерживает avatar (файл) и роль (группу).",
        request=UserUpdateSerializer,
        responses={
            200: {
                'type': 'object',
                'properties': {
                    'success': {'type': 'boolean', 'example': True},
                    'message': {'type': 'string', 'example': 'Информация о пользователе успешно обновлена'},
                    'user': {'type': 'object'}
                }
            },
            400: {
                'type': 'object',
                'properties': {
                    'success': {'type': 'boolean', 'example': False},
                    'errors': {'type': 'object'}
                }
            },
            401: {
                'type': 'object',
                'properties': {
                    'detail': {'type': 'string', 'example': 'Authentication credentials were not provided.'}
                }
            }
        },
        tags=['User Profile']
    )
    def patch(self, request):
        """Частичное обновление информации о пользователе"""
        user = request.user
        serializer = UserUpdateSerializer(user, data=request.data, partial=True, context={'request': request})
        
        if serializer.is_valid():
            serializer.save()
            # Возвращаем обновленные данные через UserDetailsSerializer
            detail_serializer = UserDetailsSerializer(user, context={'request': request})
            return Response({
                'success': True,
                'message': 'Информация о пользователе успешно обновлена',
                'user': detail_serializer.data
            }, status=status.HTTP_200_OK)
        
        return Response({
            'success': False,
            'errors': serializer.errors
        }, status=status.HTTP_400_BAD_REQUEST)


class FAQListView(APIView):
    """
    Получение списка всех FAQ (часто задаваемых вопросов)
    """
    permission_classes = [AllowAny]
    
    @extend_schema(
        summary="Получение списка FAQ",
        description="Получение списка всех активных FAQ. Доступно без авторизации.",
        responses={
            200: {
                'type': 'object',
                'properties': {
                    'success': {'type': 'boolean', 'example': True},
                    'count': {'type': 'integer', 'example': 5},
                    'faqs': {
                        'type': 'array',
                        'items': {
                            'type': 'object',
                            'properties': {
                                'id': {'type': 'integer', 'example': 1},
                                'question': {'type': 'string', 'example': 'Как зарегистрироваться в системе?'},
                                'answer': {'type': 'string', 'example': 'Для регистрации...'},
                                'order': {'type': 'integer', 'example': 1},
                                'created_at': {'type': 'string', 'format': 'date-time'},
                                'updated_at': {'type': 'string', 'format': 'date-time'}
                            }
                        }
                    }
                }
            }
        },
        tags=['FAQ']
    )
    def get(self, request):
        """Получение всех активных FAQ"""
        faqs = FAQ.objects.filter(is_active=True)
        serializer = FAQSerializer(faqs, many=True, context={'request': request})
        
        return Response({
            'success': True,
            'count': faqs.count(),
            'faqs': serializer.data
        }, status=status.HTTP_200_OK)



class UpdateTelegramChatIdView(APIView):
    """
    API для обновления Telegram Chat ID пользователя
    """
    permission_classes = [IsAuthenticated]
    
    @extend_schema(
        summary="Обновить Telegram Chat ID",
        description="Обновляет Telegram Chat ID текущего пользователя для получения SMS",
        request=TelegramChatIdSerializer,
        responses={
            200: {
                'type': 'object',
                'properties': {
                    'success': {'type': 'boolean', 'example': True},
                    'message': {'type': 'string', 'example': 'Telegram Chat ID успешно обновлен'}
                }
            },
            400: {
                'type': 'object',
                'properties': {
                    'success': {'type': 'boolean', 'example': False},
                    'errors': {'type': 'object'}
                }
            },
            401: {'type': 'object', 'properties': {'detail': {'type': 'string'}}}
        },
        tags=['User Profile']
    )
    def post(self, request):
        """Обновление Telegram Chat ID"""
        serializer = TelegramChatIdSerializer(data=request.data, context={'request': request})
        
        if not serializer.is_valid():
            return Response({
                'success': False,
                'errors': serializer.errors
            }, status=status.HTTP_400_BAD_REQUEST)
        
        chat_id = serializer.validated_data['chat_id']
        
        # Обновляем Chat ID пользователя
        request.user.telegram_chat_id = chat_id
        request.user.save()
        
        return Response({
            'success': True,
            'message': 'Telegram Chat ID успешно обновлен'
        }, status=status.HTTP_200_OK)


class UserDetailsByIdView(APIView):
    """
    Получение информации о пользователе по ID
    """
    permission_classes = [AllowAny]
    
    @extend_schema(
        summary="Получить информацию о пользователе по ID",
        description="""
## Получить детальную информацию о пользователе

Возвращает полную информацию о пользователе по его ID.
Этот endpoint может использоваться для:
- Просмотра профиля мастера
- Получения информации о водителе
- Просмотра рейтинга и отзывов пользователя

## Response включает:
- Основную информацию (имя, email, телефон)
- Роли пользователя (Driver, Master)
- Баланс (если есть)
- Рейтинг и отзывы (для мастеров)
- Статистику (количество заказов, рекомендации)

## Примеры использования:

**Просмотр мастера:**
```
GET /api/auth/user/5/
```

**Просмотр водителя:**
```
GET /api/auth/user/10/
```
        """,
        parameters=[
            OpenApiParameter(
                name='user_id',
                type=OpenApiTypes.INT,
                location=OpenApiParameter.PATH,
                description='ID пользователя',
                required=True
            )
        ],
        responses={
            200: UserDetailsSerializer,
            404: {
                'type': 'object',
                'properties': {
                    'success': {'type': 'boolean', 'example': False},
                    'error': {'type': 'string', 'example': 'Пользователь не найден'}
                }
            }
        },
        tags=['User Profile']
    )
    def get(self, request, user_id):
        """Получение информации о пользователе по ID"""
        try:
            user = CustomUser.objects.get(id=user_id)
        except CustomUser.DoesNotExist:
            return Response({
                'success': False,
                'error': 'Пользователь не найден'
            }, status=status.HTTP_404_NOT_FOUND)
        
        serializer = UserDetailsSerializer(user, context={'request': request})
        return Response({
            'success': True,
            'user': serializer.data
        }, status=status.HTTP_200_OK)
