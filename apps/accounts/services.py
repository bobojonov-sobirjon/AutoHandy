"""
Business logic for SMS and user services.
SMS is sent via Twilio; if Twilio fails, code is still returned in response (when configured).
"""
import re
import requests
import random
import logging
from typing import Any, Dict, List, Optional
from django.conf import settings
from django.core.cache import cache
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.mail import send_mail
from django.utils import timezone
from datetime import timedelta
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework import status
from rest_framework.response import Response
from .models import UserSMSCode

logger = logging.getLogger(__name__)

User = get_user_model()


def _phone_cache_id(identifier_type: str, identifier: str, phone_e164: Optional[str]) -> str:
    """Stable id for cache keys and User.phone_number (phone flow only)."""
    if identifier_type == 'phone' and phone_e164:
        return phone_e164
    return identifier


def _cross_app_role_violation(requested_role: str, user_group_names: List[str]) -> Optional[Dict[str, Any]]:
    """
    Block logging into the other app line: Master account cannot use Driver flow and vice versa.
    If the user already has both Driver and Master, no block (either role may be used).
    """
    if requested_role not in ('Driver', 'Master'):
        return None
    names = set(user_group_names or [])
    has_master = 'Master' in names
    has_driver = 'Driver' in names
    if has_master and has_driver:
        return None
    if has_master and requested_role == 'Driver':
        return {
            'success': False,
            'error': (
                'This phone number or email is already registered as a Master. '
                'You cannot sign in to the Driver app with this account.'
            ),
            'status_code': status.HTTP_400_BAD_REQUEST,
        }
    if has_driver and requested_role == 'Master':
        return {
            'success': False,
            'error': (
                'This phone number or email is already registered as a Driver. '
                'You cannot sign in to the Master app with this account.'
            ),
            'status_code': status.HTTP_400_BAD_REQUEST,
        }
    return None


class SMSService:
    """SMS services: Twilio (primary). Code is always saved and can be returned in response if send fails."""

    BOT_TOKEN = getattr(settings, 'TELEGRAM_BOT_TOKEN', '')
    BOT_NAME = getattr(settings, 'TELEGRAM_BOT_NAME', '')

    @staticmethod
    def send_telegram_sms(phone_number: str, message: str) -> dict:
        """Send SMS notification via Telegram Bot (optional)."""
        try:
            if not SMSService.BOT_TOKEN:
                return {'success': False, 'error': 'Telegram bot not configured'}
            telegram_message = f"SMS code for {phone_number}\n\n{message}"
            url = f"https://api.telegram.org/bot{SMSService.BOT_TOKEN}/sendMessage"
            admin_chat_id = getattr(settings, 'TELEGRAM_ADMIN_CHAT_ID', '')
            if not admin_chat_id:
                return {'success': False, 'error': 'TELEGRAM_ADMIN_CHAT_ID not set'}
            data = {'chat_id': admin_chat_id, 'text': telegram_message}
            response = requests.post(url, json=data, timeout=10)
            if response.status_code == 200:
                return {'success': True, 'message': 'SMS sent via Telegram'}
            return {'success': False, 'error': response.text}
        except Exception as e:
            logger.error(f"Error sending Telegram SMS: {e}")
            return {'success': False, 'error': str(e)}

    @staticmethod
    def format_phone_to_e164(phone_number: str) -> str:
        """
        Normalize phone to E.164 (digits only with country code).
        Supports all countries: Uzbekistan (998), Russia (7), and others (e.g. 1, 44, 90, ...).
        """
        cleaned = re.sub(r'\D', '', phone_number or '')
        if not cleaned:
            return phone_number
        # Russia: 8XXXXXXXXXX -> 7XXXXXXXXXX
        if len(cleaned) == 11 and cleaned.startswith('8') and cleaned[1] == '9':
            cleaned = '7' + cleaned[1:]
        elif len(cleaned) == 10 and cleaned.startswith('9'):
            # Russia 9XXXXXXXXX -> 79XXXXXXXXX
            cleaned = '7' + cleaned
        # If user entered national number without country code, optionally prepend default.
        # Example: US national 10 digits -> +1XXXXXXXXXX (if DEFAULT_PHONE_COUNTRY_CODE=1)
        default_cc = str(getattr(settings, 'DEFAULT_PHONE_COUNTRY_CODE', '') or '').strip()
        if default_cc and cleaned.isdigit() and len(cleaned) == 10:
            cleaned = f'{default_cc}{cleaned}'

        # Already has country code (e.g. 998..., 7..., 1..., 44...) or default applied above.
        return cleaned

    @staticmethod
    def format_phone_number(phone_number: str) -> str:
        """Alias for E.164 format (backward compatibility)."""
        return SMSService.format_phone_to_e164(phone_number)

    @staticmethod
    def send_sms_via_twilio(to_phone_e164: str, body: str) -> dict:
        """
        Send SMS via Twilio. to_phone_e164: digits with country code, or with +.
        Returns dict: success, message or error.
        """
        sid = getattr(settings, 'TWILIO_ACCOUNT_SID', None)
        token = getattr(settings, 'TWILIO_AUTH_TOKEN', None)
        from_number = getattr(settings, 'TWILIO_PHONE_NUMBER', None)
        if not sid or not token or not from_number:
            return {
                'success': False,
                'error': 'Twilio not configured (TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_PHONE_NUMBER)',
                'debug': {
                    'twilio_configured': False,
                    'twilio_sid_prefix': (sid[:2] if sid else None),
                    'twilio_from_number': from_number,
                },
            }
        to_formatted = to_phone_e164 if (to_phone_e164 or '').startswith('+') else f'+{to_phone_e164}'
        try:
            from twilio.rest import Client
            from twilio.base.exceptions import TwilioRestException
            client = Client(sid, token)
            message = client.messages.create(body=body, from_=from_number, to=to_formatted)
            logger.info(f"Twilio SMS sent to {to_formatted} sid={message.sid}")
            return {
                'success': True,
                'message_sid': message.sid,
                'debug': {
                    'twilio_configured': True,
                    'twilio_sid_prefix': sid[:2] if sid else None,
                    'twilio_from_number': from_number,
                    'twilio_to_number': to_formatted,
                },
            }
        except TwilioRestException as e:
            # Twilio gives structured error details (useful for geo-permissions / invalid number / trial restrictions).
            logger.warning(f"Twilio send failed: {e.status} {e.code} {e.msg}")
            return {
                'success': False,
                'error': str(e),
                'debug': {
                    'twilio_configured': True,
                    'twilio_sid_prefix': sid[:2] if sid else None,
                    'twilio_from_number': from_number,
                    'twilio_to_number': to_formatted,
                    'twilio_error_status': getattr(e, 'status', None),
                    'twilio_error_code': getattr(e, 'code', None),
                    'twilio_error_message': getattr(e, 'msg', None),
                    'twilio_more_info': getattr(e, 'more_info', None),
                },
            }
        except Exception as e:
            logger.warning(f"Twilio send failed (unknown): {e}")
            return {
                'success': False,
                'error': str(e),
                'debug': {
                    'twilio_configured': True,
                    'twilio_sid_prefix': sid[:2] if sid else None,
                    'twilio_from_number': from_number,
                    'twilio_to_number': to_formatted,
                },
            }
    
    @staticmethod
    def send_email_code(email: str, sms_code: str) -> dict:
        """
        Отправка кода подтверждения на email
        
        Args:
            email (str): Email адрес
            sms_code (str): Код подтверждения
            
        Returns:
            dict: Результат отправки
        """
        try:
            subject = 'Код подтверждения AutoHandy'
            message = f'Ваш код подтверждения: {sms_code}'
            from_email = settings.DEFAULT_FROM_EMAIL
            recipient_list = [email]
            
            send_mail(
                subject=subject,
                message=message,
                from_email=from_email,
                recipient_list=recipient_list,
                fail_silently=False,
            )
            
            logger.info(f"Email code {sms_code} sent to {email}")
            return {
                'success': True,
                'message': 'Код подтверждения отправлен на email'
            }
            
        except Exception as e:
            logger.error(f"Failed to send email to {email}: {str(e)}")
            return {
                'success': False,
                'error': f'Failed to send email: {str(e)}'
            }
    
    @staticmethod
    def check_smsc_balance() -> dict:
        """Check SMSC.ru balance (optional/legacy)."""
        try:
            login = getattr(settings, 'SMSC_LOGIN', None)
            psw = getattr(settings, 'SMSC_PASSWORD', None)
            if not login or not psw:
                return {'success': False, 'error': 'SMSC not configured', 'balance': 0}
            data = {'login': login, 'psw': psw, 'fmt': 3}
            response = requests.get('https://smsc.ru/sys/balance.php', params=data, timeout=10)
            result = response.json()
            if result.get('error'):
                return {'success': False, 'error': result.get('error'), 'balance': 0}
            return {'success': True, 'balance': float(result.get('balance', 0)), 'currency': result.get('currency', 'RUB')}
        except Exception as e:
            return {'success': False, 'error': str(e), 'balance': 0}

    @staticmethod
    def send_sms_code(identifier: str, identifier_type: str = 'phone', role: str = None) -> dict:
        """
        Send SMS code to phone (Twilio) or email. Saves code to DB always.
        For phone: sends via Twilio to any E.164 number. If Twilio fails and
        SMS_SEND_CODE_IN_RESPONSE_IF_FAIL is True, still returns success with sms_code in response.
        """
        try:
            if role and role not in ['Driver', 'Master', 'Owner']:
                return {'success': False, 'error': 'Invalid role', 'status_code': status.HTTP_400_BAD_REQUEST}

            user_exists = False
            phone_number = None

            if identifier_type == 'phone':
                phone_number = SMSService.format_phone_to_e164(identifier)
                try:
                    user = User.objects.prefetch_related('groups').get(phone_number=phone_number)
                    user_exists = True
                    if role:
                        user_groups = list(user.groups.values_list('name', flat=True))
                        cross = _cross_app_role_violation(role, user_groups)
                        if cross:
                            return cross
                        if user_groups and role not in user_groups:
                            return {
                                'success': False,
                                'error': f'Role mismatch. User roles: {", ".join(user_groups)}. You specified: {role}',
                                'status_code': status.HTTP_400_BAD_REQUEST
                            }
                except User.DoesNotExist:
                    user_exists = False
            elif identifier_type == 'email':
                try:
                    user = User.objects.prefetch_related('groups').get(email=identifier)
                    user_exists = True
                    if role:
                        user_groups = list(user.groups.values_list('name', flat=True))
                        cross = _cross_app_role_violation(role, user_groups)
                        if cross:
                            return cross
                        if user_groups and role not in user_groups:
                            return {'success': False, 'error': 'Invalid user role', 'status_code': status.HTTP_400_BAD_REQUEST}
                    phone_number = user.phone_number or identifier
                except User.DoesNotExist:
                    user_exists = False
                    phone_number = identifier

            if not phone_number:
                return {
                    'success': False,
                    'error': 'Could not determine phone number for SMS',
                    'status_code': status.HTTP_400_BAD_REQUEST
                }

            sms_code = str(random.randint(1000, 9999))
            sms_sent = False
            sms_error = None
            sms_debug = {}

            if identifier_type == 'email':
                email_result = SMSService.send_email_code(identifier, sms_code)
                if not email_result['success']:
                    return {'success': False, 'error': email_result['error'], 'status_code': status.HTTP_500_INTERNAL_SERVER_ERROR}
                sms_sent = True
            else:
                twilio_result = SMSService.send_sms_via_twilio(phone_number, f'Verification code to log in to the Autohandy mobile app: {sms_code}. This code will expire in 5 minutes. Do not share this code with anyone.')
                sms_sent = twilio_result.get('success', False)
                sms_error = twilio_result.get('error')
                sms_debug = twilio_result.get('debug') or {}
                if not sms_sent:
                    logger.warning(f"Twilio send failed for {phone_number}: {sms_error}")

            cache_id = _phone_cache_id(identifier_type, identifier, phone_number if identifier_type == 'phone' else None)

            if identifier_type == 'phone':
                UserSMSCode.objects.filter(
                    identifier_type=identifier_type,
                    identifier__in=[identifier, phone_number],
                    is_used=False,
                ).update(is_used=True, used_at=timezone.now())
            else:
                UserSMSCode.objects.filter(
                    identifier=identifier,
                    identifier_type=identifier_type,
                    is_used=False,
                ).update(is_used=True, used_at=timezone.now())

            expires_at = timezone.now() + timedelta(minutes=5)
            created_by_user = None
            if user_exists:
                try:
                    if identifier_type == 'phone':
                        created_by_user = User.objects.get(phone_number=phone_number)
                    else:
                        created_by_user = User.objects.get(email=identifier)
                except User.DoesNotExist:
                    pass

            UserSMSCode.objects.create(
                code=sms_code,
                identifier=cache_id,
                identifier_type=identifier_type,
                created_by=created_by_user,
                expires_at=expires_at
            )

            cache_key = f'sms_code_{identifier_type}_{cache_id}'
            cache.set(cache_key, sms_code, timeout=300)
            cache.set(f'user_exists_{identifier_type}_{cache_id}', user_exists, timeout=300)
            if role:
                cache.set(f'user_role_{identifier_type}_{cache_id}', role, timeout=300)

            send_code_in_response = getattr(settings, 'SMS_SEND_CODE_IN_RESPONSE_IF_FAIL', True)
            if identifier_type == 'email':
                message = 'Verification code sent to email'
            elif sms_sent:
                message = 'SMS code sent'
            else:
                message = 'Code generated; SMS could not be sent. Use the code below.' if send_code_in_response else 'SMS send failed'

            response_data = {
                'success': True,
                'message': message,
                'identifier': identifier,
                'identifier_type': identifier_type,
                'phone': phone_number if identifier_type == 'phone' else None,
                'email': identifier if identifier_type == 'email' else None,
                'user_exists': user_exists,
                'status_code': status.HTTP_200_OK
            }
            if identifier_type == 'email' or sms_sent or send_code_in_response:
                response_data['sms_code'] = sms_code
            if not sms_sent and identifier_type == 'phone' and sms_error:
                response_data['sms_error'] = sms_error
                response_data['sms_debug'] = {
                    'provider': 'twilio',
                    'sms_sent': False,
                    **sms_debug,
                }
            elif identifier_type == 'phone':
                response_data['sms_debug'] = {
                    'provider': 'twilio',
                    'sms_sent': bool(sms_sent),
                    **sms_debug,
                }

            return response_data

        except requests.exceptions.Timeout:
            return {'success': False, 'error': 'SMS service timeout', 'status_code': status.HTTP_408_REQUEST_TIMEOUT}
        except Exception as e:
            logger.exception(e)
            return {'success': False, 'error': str(e), 'status_code': status.HTTP_500_INTERNAL_SERVER_ERROR}
    
    @staticmethod
    def verify_sms_code(identifier: str, sms_code: str, identifier_type: str = 'phone', role: str = None) -> dict:
        """
        Проверка SMS кода
        
        Args:
            identifier (str): Номер телефона или email
            sms_code (str): SMS код
            identifier_type (str): Тип идентификатора ('phone' или 'email')
            role (str): Роль пользователя ('Driver' или 'Master') - только для новых пользователей
            
        Returns:
            dict: Результат
        """
        try:
            if role and role not in ['Driver', 'Master', 'Owner']:
                return {'success': False, 'error': 'Invalid role', 'status_code': status.HTTP_400_BAD_REQUEST}

            phone_number = SMSService.format_phone_to_e164(identifier) if identifier_type == 'phone' else None
            cache_id = _phone_cache_id(identifier_type, identifier, phone_number)

            # Get code from database (primary source)
            try:
                if identifier_type == 'phone':
                    sms_code_obj = UserSMSCode.objects.filter(
                        identifier_type=identifier_type,
                        identifier__in=[identifier, phone_number],
                        code=sms_code,
                        is_used=False,
                    ).order_by('-created_at').first()
                else:
                    sms_code_obj = UserSMSCode.objects.filter(
                        identifier=identifier,
                        identifier_type=identifier_type,
                        code=sms_code,
                        is_used=False,
                    ).order_by('-created_at').first()

                if not sms_code_obj:
                    cache_key = f'sms_code_{identifier_type}_{cache_id}'
                    stored_code = cache.get(cache_key)
                    if (not stored_code or stored_code != sms_code) and identifier_type == 'phone':
                        stored_code = cache.get(f'sms_code_{identifier_type}_{identifier}')

                    if not stored_code or stored_code != sms_code:
                        return {'success': False, 'error': 'Invalid SMS code', 'status_code': status.HTTP_400_BAD_REQUEST}
                else:
                    if sms_code_obj.is_expired():
                        return {'success': False, 'error': 'SMS code expired', 'status_code': status.HTTP_400_BAD_REQUEST}
                    sms_code_obj.mark_as_used()
                    logger.info(f"SMS code verified for {identifier}")

            except Exception as e:
                logger.error(f"Error verifying SMS code: {str(e)}")
                cache_key = f'sms_code_{identifier_type}_{cache_id}'
                stored_code = cache.get(cache_key)
                if (not stored_code or stored_code != sms_code) and identifier_type == 'phone':
                    stored_code = cache.get(f'sms_code_{identifier_type}_{identifier}')

                if not stored_code or stored_code != sms_code:
                    return {'success': False, 'error': 'Invalid SMS code', 'status_code': status.HTTP_400_BAD_REQUEST}

            # Find or create user
            user_exists = cache.get(f'user_exists_{identifier_type}_{cache_id}', False)
            if not user_exists and identifier_type == 'phone':
                user_exists = cache.get(f'user_exists_{identifier_type}_{identifier}', False)

            cached_role = cache.get(f'user_role_{identifier_type}_{cache_id}')
            if not cached_role and identifier_type == 'phone':
                cached_role = cache.get(f'user_role_{identifier_type}_{identifier}')
            if not role and cached_role:
                role = cached_role
            
            if user_exists:
                try:
                    if identifier_type == 'phone':
                        user = User.objects.prefetch_related('groups').get(phone_number=phone_number)
                    else:  # email
                        user = User.objects.prefetch_related('groups').get(email=identifier)
                    created = False
                    
                    if role:
                        user_groups = list(user.groups.values_list('name', flat=True))
                        cross = _cross_app_role_violation(role, user_groups)
                        if cross:
                            return cross
                        if user_groups and role not in user_groups:
                            return {'success': False, 'error': 'Invalid user role', 'status_code': status.HTTP_400_BAD_REQUEST}
                        if not user_groups:
                            try:
                                group = Group.objects.get(name=role)
                                user.groups.add(group)
                                logger.info(f"Added role {role} to existing user {user.email}")
                            except Group.DoesNotExist:
                                logger.warning(f"Group {role} not found, skipping role assignment")
                except User.DoesNotExist:
                    if identifier_type == 'phone':
                        user, created = User.objects.prefetch_related('groups').get_or_create(
                            phone_number=phone_number,
                            defaults={
                                'username': f'user_{phone_number}',
                                'email': None,
                                'first_name': '',
                                'last_name': '',
                                'is_verified': True
                            }
                        )
                        
                        if created and role:
                            try:
                                group = Group.objects.get(name=role)
                                user.groups.add(group)
                            except Group.DoesNotExist:
                                logger.warning(f"Group {role} not found, skipping role assignment")
                    else:  # email
                        user, created = User.objects.prefetch_related('groups').get_or_create(
                            email=identifier,
                            defaults={
                                'username': f'user_{identifier.split("@")[0]}',
                                'phone_number': None,
                                'first_name': '',
                                'last_name': '',
                                'is_verified': True
                            }
                        )
                        
                        if created and role:
                            try:
                                group = Group.objects.get(name=role)
                                user.groups.add(group)
                            except Group.DoesNotExist:
                                logger.warning(f"Group {role} not found, skipping role assignment")
            else:
                if identifier_type == 'phone':
                    user, created = User.objects.prefetch_related('groups').get_or_create(
                        phone_number=phone_number,
                        defaults={
                            'username': f'user_{phone_number}',
                            'email': None,
                            'first_name': '',
                            'last_name': '',
                            'is_verified': True
                        }
                    )
                    
                    if created and role:
                        try:
                            group = Group.objects.get(name=role)
                            user.groups.add(group)
                        except Group.DoesNotExist:
                            logger.warning(f"Group {role} not found, skipping role assignment")
                else:  # email
                    user, created = User.objects.prefetch_related('groups').get_or_create(
                        email=identifier,
                        defaults={
                            'username': f'user_{identifier.split("@")[0]}',
                            'phone_number': None,
                            'first_name': '',
                            'last_name': '',
                            'is_verified': True
                        }
                    )
                    
                    if created and role:
                        try:
                            group = Group.objects.get(name=role)
                            user.groups.add(group)
                        except Group.DoesNotExist:
                            logger.warning(f"Group {role} not found, skipping role assignment")
            
            # Phone sign-up: never keep placeholder name/email (safety net after create).
            if identifier_type == 'phone' and created:
                User.objects.filter(pk=user.pk).update(
                    first_name='',
                    last_name='',
                    email=None,
                )
                user.refresh_from_db(fields=['first_name', 'last_name', 'email'])

            refresh = RefreshToken.for_user(user)
            access_token = refresh.access_token
            
            cache.delete(f'user_exists_{identifier_type}_{cache_id}')
            cache.delete(f'user_role_{identifier_type}_{cache_id}')
            cache.delete(f'sms_code_{identifier_type}_{cache_id}')
            if identifier_type == 'phone':
                cache.delete(f'user_exists_{identifier_type}_{identifier}')
                cache.delete(f'user_role_{identifier_type}_{identifier}')
                cache.delete(f'sms_code_{identifier_type}_{identifier}')

            return {
                'success': True,
                'message': 'Login successful',
                'user': user,
                'user_created': created,
                'tokens': {
                    'access': str(access_token),
                    'refresh': str(refresh)
                },
                'status_code': status.HTTP_200_OK
            }
            
        except Exception as e:
            return {'success': False, 'error': str(e), 'status_code': status.HTTP_500_INTERNAL_SERVER_ERROR}


def upsert_user_device_for_login(user, device_token: str, device_type: str) -> None:
    """
    Create or update a device row for check-sms-code.
    ``device_token`` is unique: the same token is reassigned to the current user on each login.
    """
    from .models import UserDevice

    UserDevice.objects.update_or_create(
        device_token=device_token,
        defaults={'user': user, 'device_type': device_type},
    )
