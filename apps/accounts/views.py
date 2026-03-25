from rest_framework.views import APIView
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework import status
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from drf_spectacular.utils import extend_schema, OpenApiParameter, OpenApiExample
from drf_spectacular.types import OpenApiTypes
from datetime import timedelta

from django.utils import timezone

from .serializers import (
    PhoneNumberSerializer,
    IdentifierSerializer,
    SMSVerificationSerializer,
    UserSerializer,
    TokenResponseSerializer,
    SMSResponseSerializer,
    UserDetailsSerializer,
    UserProfileRegistrationSerializer,
    UserLimitedProfileUpdateSerializer,
    UserLocationUpdateSerializer,
    EmailVerificationConfirmSerializer,
    FAQSerializer,
    TelegramChatIdSerializer,
)
from .services import SMSService
from .models import CustomUser, FAQ, EmailVerificationToken
from .email_verification import build_verification_url, send_email_verification_message


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
        summary="Обновление профиля (ограниченные поля)",
        description=(
            "multipart/form-data: только first_name, last_name, avatar, date_of_birth. "
            "Остальные поля (email, address и т.д.) меняются через POST /api/auth/user/register-profile/."
        ),
        request=UserLimitedProfileUpdateSerializer,
        responses={
            200: {
                'type': 'object',
                'properties': {
                    'success': {'type': 'boolean', 'example': True},
                    'message': {'type': 'string', 'example': 'Profile updated'},
                    'user': {'type': 'object'},
                },
            },
            400: {'type': 'object', 'properties': {'success': {'type': 'boolean'}, 'errors': {'type': 'object'}}},
            401: {'type': 'object', 'properties': {'detail': {'type': 'string'}}},
        },
        tags=['User Profile'],
    )
    def put(self, request):
        """Обновление только имени, фамилии, аватара и даты рождения (form-data)."""
        user = request.user
        serializer = UserLimitedProfileUpdateSerializer(
            user, data=request.data, partial=True, context={'request': request}
        )
        if serializer.is_valid():
            serializer.save()
            detail_serializer = UserDetailsSerializer(user, context={'request': request})
            return Response(
                {
                    'success': True,
                    'message': 'Profile updated',
                    'user': detail_serializer.data,
                },
                status=status.HTTP_200_OK,
            )
        return Response({'success': False, 'errors': serializer.errors}, status=status.HTTP_400_BAD_REQUEST)

    @extend_schema(
        summary="Частичное обновление профиля (ограниченные поля)",
        description="То же, что PUT: только first_name, last_name, avatar, date_of_birth (multipart/form-data).",
        request=UserLimitedProfileUpdateSerializer,
        responses={
            200: {
                'type': 'object',
                'properties': {
                    'success': {'type': 'boolean'},
                    'message': {'type': 'string'},
                    'user': {'type': 'object'},
                },
            },
            400: {'type': 'object', 'properties': {'success': {'type': 'boolean'}, 'errors': {'type': 'object'}}},
            401: {'type': 'object', 'properties': {'detail': {'type': 'string'}}},
        },
        tags=['User Profile'],
    )
    def patch(self, request):
        user = request.user
        serializer = UserLimitedProfileUpdateSerializer(
            user, data=request.data, partial=True, context={'request': request}
        )
        if serializer.is_valid():
            serializer.save()
            detail_serializer = UserDetailsSerializer(user, context={'request': request})
            return Response(
                {
                    'success': True,
                    'message': 'Profile updated',
                    'user': detail_serializer.data,
                },
                status=status.HTTP_200_OK,
            )
        return Response({'success': False, 'errors': serializer.errors}, status=status.HTTP_400_BAD_REQUEST)


class UserLocationUpdateView(APIView):
    """Update latitude/longitude for the authenticated user (from JWT)."""

    permission_classes = [IsAuthenticated]
    parser_classes = [JSONParser, FormParser]

    @extend_schema(
        summary="Update user coordinates",
        description="JSON body: `latitude` and `longitude` (WGS84). Both fields are required.",
        request=UserLocationUpdateSerializer,
        responses={
            200: {
                'type': 'object',
                'properties': {
                    'success': {'type': 'boolean'},
                    'message': {'type': 'string'},
                    'user': {'type': 'object'},
                },
            },
            400: {'type': 'object'},
            401: {'type': 'object'},
        },
        tags=['User Profile'],
    )
    def put(self, request):
        serializer = UserLocationUpdateSerializer(
            request.user, data=request.data, partial=False, context={'request': request}
        )
        if serializer.is_valid():
            serializer.save()
            detail = UserDetailsSerializer(request.user, context={'request': request})
            return Response(
                {
                    'success': True,
                    'message': 'Location updated',
                    'user': detail.data,
                },
                status=status.HTTP_200_OK,
            )
        return Response({'success': False, 'errors': serializer.errors}, status=status.HTTP_400_BAD_REQUEST)


class UserProfileRegistrationView(APIView):
    """
    POST multipart/form: first_name, last_name, email, avatar, date_of_birth, address.
    If is_email_verified is False, saves profile and sends verification email (English HTML).
    If True, responds that the user is already registered.
    """
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    @extend_schema(
        summary="Register / complete profile + email verification",
        description=(
            "multipart/form-data. Updates profile for request.user. "
            "If email is not verified yet, sends HTML email with link "
            "`{FRONTEND_BASE}/email-verification/token={uuid}`. "
            "If already verified, returns a message that you are already registered."
        ),
        request=UserProfileRegistrationSerializer,
        responses={
            200: {
                'type': 'object',
                'properties': {
                    'success': {'type': 'boolean'},
                    'message': {'type': 'string'},
                    'user': {'type': 'object'},
                },
            },
            400: {'type': 'object'},
        },
        tags=['User Profile'],
    )
    def post(self, request):
        from django.conf import settings

        user = request.user
        if getattr(user, 'is_email_verified', False):
            detail = UserDetailsSerializer(user, context={'request': request})
            return Response(
                {
                    'success': False,
                    'message': 'You are already registered. Your email is already verified.',
                    'user': detail.data,
                },
                status=status.HTTP_200_OK,
            )

        serializer = UserProfileRegistrationSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(
                {'success': False, 'errors': serializer.errors},
                status=status.HTTP_400_BAD_REQUEST,
            )

        data = serializer.validated_data
        email = data['email'].strip().lower()
        if CustomUser.objects.exclude(pk=user.pk).filter(email=email).exists():
            return Response(
                {'success': False, 'error': 'This email is already in use by another account.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        user.first_name = data['first_name']
        user.last_name = data['last_name']
        user.email = email
        candidate_username = email[:150]
        if CustomUser.objects.exclude(pk=user.pk).filter(username=candidate_username).exists():
            candidate_username = f"{email.split('@')[0]}_{user.pk}"[:150]
        user.username = candidate_username
        if data.get('address') is not None:
            user.address = data['address'] or ''
        if 'date_of_birth' in data:
            user.date_of_birth = data['date_of_birth']
        if data.get('avatar') is not None:
            user.avatar = data['avatar']
        user.save()

        hours = getattr(settings, 'EMAIL_VERIFICATION_TOKEN_HOURS', 48)
        expires_at = timezone.now() + timedelta(hours=hours)
        EmailVerificationToken.objects.filter(user=user, is_used=False).update(is_used=True)
        token_obj = EmailVerificationToken.objects.create(
            user=user,
            email=email,
            expires_at=expires_at,
        )
        url = build_verification_url(token_obj.token)
        try:
            send_email_verification_message(email, url)
        except Exception as exc:
            return Response(
                {
                    'success': False,
                    'error': 'Profile saved but verification email could not be sent.',
                    'detail': str(exc),
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        detail = UserDetailsSerializer(user, context={'request': request})
        return Response(
            {
                'success': True,
                'message': 'Profile saved. Please check your email to verify your AutoHandy address.',
                'user': detail.data,
            },
            status=status.HTTP_200_OK,
        )


class EmailVerificationConfirmView(APIView):
    """POST JSON or form: token (UUID) — marks email verified if token is valid."""
    permission_classes = [AllowAny]

    @extend_schema(
        summary="Confirm email verification",
        description="Body: `token` (UUID from email link). Sets is_email_verified and is_verified.",
        request=EmailVerificationConfirmSerializer,
        responses={
            200: {'type': 'object', 'properties': {'success': {'type': 'boolean'}, 'message': {'type': 'string'}}},
            400: {'type': 'object'},
        },
        tags=['User Profile'],
    )
    def post(self, request):
        ser = EmailVerificationConfirmSerializer(data=request.data)
        if not ser.is_valid():
            return Response({'success': False, 'errors': ser.errors}, status=status.HTTP_400_BAD_REQUEST)
        token_uuid = ser.validated_data['token']
        try:
            rec = EmailVerificationToken.objects.select_related('user').get(token=token_uuid)
        except EmailVerificationToken.DoesNotExist:
            return Response(
                {'success': False, 'error': 'Invalid or unknown verification token.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if rec.is_used:
            return Response(
                {'success': False, 'error': 'This verification link has already been used.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if rec.is_expired():
            return Response(
                {'success': False, 'error': 'This verification link has expired. Request a new one from the app.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        u = rec.user
        if (u.email or '').lower() != (rec.email or '').lower():
            return Response(
                {'success': False, 'error': 'Email no longer matches this verification request.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        rec.is_used = True
        rec.save(update_fields=['is_used'])
        u.is_email_verified = True
        u.is_verified = True
        u.save(update_fields=['is_email_verified', 'is_verified'])
        return Response(
            {'success': True, 'message': 'Your email has been verified successfully.'},
            status=status.HTTP_200_OK,
        )


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
