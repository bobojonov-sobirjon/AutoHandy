from rest_framework import serializers
from django.core.exceptions import ValidationError
import re
from config.wgs84 import WGS84_COORD_DECIMAL_KWARGS
from .models import AppVersion, CustomUser, FAQ


class TelegramChatIdSerializer(serializers.Serializer):
    """Serializer for updating Telegram Chat ID"""
    chat_id = serializers.CharField(
        max_length=50,
        required=True,
        help_text="Your Telegram Chat ID"
    )

    def validate_chat_id(self, value):
        """Validate Chat ID"""
        if not value:
            raise ValidationError("Chat ID is required")
        if not (value.isdigit() or value.startswith('@')):
            raise ValidationError("Invalid Chat ID format. Use numeric ID or @username")
        return value


def validate_email_format(value):
    """Validate email format"""
    if not value:
        raise ValidationError("Email is required")
    email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    if not re.match(email_pattern, value):
        raise ValidationError("Invalid email format")
    return value.lower().strip()


def validate_phone_number_format(value):
    """
    Validate and normalize phone number for any country (E.164).
    Accepts: +XXXXXXXXXX, 998..., 7..., 1..., 44..., etc. (10–15 digits with optional +).
    """
    if not value:
        raise ValidationError("Phone number is required")
    from apps.accounts.services import SMSService

    cleaned = SMSService.format_phone_to_e164(value)
    digits = re.sub(r'\D', '', cleaned or '')
    if len(digits) < 10 or len(digits) > 15:
        raise ValidationError("Phone number must be 10–15 digits (with country code)")
    return digits


class IdentifierSerializer(serializers.Serializer):
    """Serializer for identifier (email or phone number)"""
    identifier = serializers.CharField(max_length=255, required=True)
    role = serializers.ChoiceField(
        choices=['Driver', 'Master', 'Owner'],
        required=True,
        help_text="User role: Driver, Master or Owner (required)."
    )

    def validate_identifier(self, value):
        """Validate and determine identifier type"""
        if not value:
            raise ValidationError("Identifier is required")
        value = value.strip()
        if '@' in value:
            return {'type': 'email', 'value': validate_email_format(value)}
        elif value.startswith(('+', '1', '7', '8', '9')) or (
            value.replace('+', '').replace(' ', '').replace('-', '').replace('(', '').replace(')', '').isdigit()
        ):
            return {'type': 'phone', 'value': validate_phone_number_format(value)}
        raise ValidationError("Invalid format. Enter email or phone number")

    def validate_role(self, value):
        """Validate role"""
        if value and value not in ['Driver', 'Master', 'Owner']:
            raise ValidationError("Invalid role")
        return value


class PhoneNumberSerializer(serializers.Serializer):
    """Serializer for phone number"""
    phone_number = serializers.CharField(max_length=15, required=True)

    def validate_phone_number(self, value):
        """Validate and format phone number"""
        return validate_phone_number_format(value)


class SMSVerificationSerializer(serializers.Serializer):
    """Serializer for SMS code verification"""
    identifier = serializers.CharField(max_length=255, required=True)
    sms_code = serializers.CharField(max_length=4, min_length=4, required=True)
    role = serializers.ChoiceField(
        choices=['Driver', 'Master', 'Owner'],
        required=True,
        help_text="User role: Driver, Master or Owner (required)."
    )

    def validate_identifier(self, value):
        """Validate and determine identifier type"""
        if not value:
            raise ValidationError("Identifier is required")
        value = value.strip()
        if '@' in value:
            return {'type': 'email', 'value': validate_email_format(value)}
        elif value.startswith(('+', '1', '7', '8', '9')) or (
            value.replace('+', '').replace(' ', '').replace('-', '').replace('(', '').replace(')', '').isdigit()
        ):
            return {'type': 'phone', 'value': validate_phone_number_format(value)}
        raise ValidationError("Invalid format. Enter email or phone number")

    def validate_sms_code(self, value):
        """Validate SMS code"""
        if not value:
            raise ValidationError("SMS code is required")
        if not value.isdigit():
            raise ValidationError("SMS code must contain only digits")
        if len(value) != 4:
            raise ValidationError("SMS code must be 4 digits")
        return value

    def validate_role(self, value):
        """Validate role"""
        if value and value not in ['Driver', 'Master', 'Owner']:
            raise ValidationError("Invalid role")
        return value


class UserSerializer(serializers.ModelSerializer):
    """User data serializer"""
    roles = serializers.SerializerMethodField()
    balance = serializers.SerializerMethodField()
    requires_email_verification = serializers.SerializerMethodField()

    class Meta:
        model = CustomUser
        fields = [
            'id', 'private_id', 'phone_number', 'first_name', 'last_name', 'email',
            'is_verified', 'is_email_verified', 'requires_email_verification',
            'created_at', 'roles', 'balance',
        ]
        read_only_fields = ['id', 'private_id', 'created_at', 'roles', 'balance']

    def get_requires_email_verification(self, obj):
        from django.conf import settings

        if not getattr(settings, 'REQUIRE_EMAIL_VERIFICATION', True):
            return False
        return not bool(getattr(obj, 'is_email_verified', False))
    
    def get_roles(self, obj):
        """Get all user roles with full info"""
        # Check if obj is a model instance (not a dictionary)
        if hasattr(obj, 'groups'):
            try:
                groups = obj.groups.all()
                if groups.exists():
                    return [
                        {
                            'id': group.id,
                            'name': group.name
                        }
                        for group in groups
                    ]
            except Exception as e:
                # Log the error for debugging
                import logging
                logger = logging.getLogger(__name__)
                logger.error(f"Error getting roles for user {obj.id}: {str(e)}")
        return []
    
    def get_balance(self, obj):
        """Get user balance"""
        try:
            from .models import UserBalance
            balance = UserBalance.get_or_create_balance(obj)
            return {
                'amount': str(balance.amount),
                'updated_at': balance.updated_at
            }
        except Exception as e:
            # Log the error for debugging
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Error getting balance for user {obj.id}: {str(e)}")
            return {
                'amount': '0.00',
                'updated_at': None
            }


class TokenResponseSerializer(serializers.Serializer):
    """Token response serializer"""
    success = serializers.BooleanField()
    message = serializers.CharField()
    user = UserSerializer()
    tokens = serializers.DictField()
    
    class Meta:
        fields = ['success', 'message', 'user', 'tokens']


class SMSResponseSerializer(serializers.Serializer):
    """SMS send response serializer"""
    success = serializers.BooleanField()
    message = serializers.CharField()
    phone = serializers.CharField()
    
    class Meta:
        fields = ['success', 'message', 'phone']


class UserDetailsSerializer(serializers.ModelSerializer):
    """User details serializer (read-only)"""
    latitude = serializers.DecimalField(**WGS84_COORD_DECIMAL_KWARGS, required=False, allow_null=True)
    longitude = serializers.DecimalField(**WGS84_COORD_DECIMAL_KWARGS, required=False, allow_null=True)
    roles = serializers.SerializerMethodField()
    balance = serializers.SerializerMethodField()
    avatar = serializers.SerializerMethodField()
    reviews = serializers.SerializerMethodField()
    rating = serializers.SerializerMethodField()
    reviews_count = serializers.SerializerMethodField()
    completed_orders = serializers.SerializerMethodField()
    acceptance_rate = serializers.SerializerMethodField()
    completion_rate = serializers.SerializerMethodField()
    requires_email_verification = serializers.SerializerMethodField()
    
    class Meta:
        model = CustomUser
        fields = [
            'id', 'private_id', 'username', 'email', 'phone_number', 'first_name',
            'last_name', 'date_of_birth', 'avatar', 'address',
            'longitude', 'latitude', 'is_verified', 'is_email_verified', 'roles', 'balance',
            'reviews', 'rating', 'reviews_count', 'completed_orders',
            'acceptance_rate', 'completion_rate',
            'has_tools_confirmed', 'has_licenses_confirmed', 'workshop_compliance_confirmed_at',
            'requires_email_verification',
            'created_at', 'updated_at', 'description',
        ]
        read_only_fields = [
            'id', 'private_id', 'email', 'phone_number', 'is_verified', 'is_email_verified', 'roles', 'balance',
            'reviews', 'rating', 'reviews_count', 'completed_orders',
            'acceptance_rate', 'completion_rate',
            'has_tools_confirmed', 'has_licenses_confirmed', 'workshop_compliance_confirmed_at',
            'created_at', 'updated_at',
        ]

    def get_requires_email_verification(self, obj):
        from django.conf import settings

        if not getattr(settings, 'REQUIRE_EMAIL_VERIFICATION', True):
            return False
        return not bool(getattr(obj, 'is_email_verified', False))
    
    def get_roles(self, obj):
        """Get all user roles with full info"""
        # Check if obj is a model instance (not a dictionary)
        if hasattr(obj, 'groups'):
            try:
                groups = obj.groups.all()
                if groups.exists():
                    return [
                        {
                            'id': group.id,
                            'name': group.name
                        }
                        for group in groups
                    ]
            except Exception as e:
                # Log the error for debugging
                import logging
                logger = logging.getLogger(__name__)
                logger.error(f"Error getting roles for user {obj.id}: {str(e)}")
        return []

    def get_avatar(self, obj):
        from apps.order.services.notifications import _media_url

        return _media_url(self.context.get('request'), getattr(obj, 'avatar', None))

    def get_balance(self, obj):
        """Get user balance"""
        try:
            from .models import UserBalance
            balance = UserBalance.get_or_create_balance(obj)
            return {
                'amount': str(balance.amount),
                'updated_at': balance.updated_at
            }
        except Exception as e:
            # Log the error for debugging
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Error getting balance for user {obj.id}: {str(e)}")
            return {
                'amount': '0.00',
                'updated_at': None
            }
        return []
    
    def get_reviews(self, obj):
        """Get all reviews about user (as master)"""
        try:
            from apps.order.models import Review, ReviewTag, Order
            from apps.order.services.notifications import _media_url
            from apps.accounts.display_name import public_person_display_name

            request = self.context.get('request')
            orders_as_main_master = Order.objects.filter(master__user=obj)
            all_order_ids = set(orders_as_main_master.values_list('id', flat=True))
            reviews = (
                Review.objects.filter(order_id__in=all_order_ids)
                .order_by('-created_at')
                .select_related('reviewer', 'order')
            )

            def _tags_detail(tags):
                if not tags:
                    return []
                out = []
                for t in tags:
                    try:
                        label = str(ReviewTag(t).label)
                    except ValueError:
                        label = str(t)
                    out.append({'value': t, 'label': label})
                return out

            return [
                {
                    'id': review.id,
                    'rating': review.rating,
                    'comment': review.comment,
                    'tags': review.tags,
                    'tags_detail': _tags_detail(review.tags),
                    'reviewer': {
                        'id': review.reviewer.id,
                        'full_name': public_person_display_name(review.reviewer),
                        'avatar': _media_url(request, review.reviewer.avatar),
                    },
                    'order_id': review.order.id,
                    'created_at': review.created_at,
                }
                for review in reviews
            ]
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Error getting reviews for user {obj.id}: {str(e)}")
            return []
    
    def get_rating(self, obj):
        """Get user average rating"""
        try:
            from apps.order.models import UserRating
            
            user_rating = UserRating.objects.filter(user=obj).first()
            if user_rating:
                return float(user_rating.average_rating)
            return 0.0
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Error getting rating for user {obj.id}: {str(e)}")
            return 0.0
    
    def get_reviews_count(self, obj):
        """Get count of reviews about user (as master)"""
        try:
            from apps.order.models import Review, Order
            orders_as_main_master = Order.objects.filter(master__user=obj)
            all_order_ids = set(orders_as_main_master.values_list('id', flat=True))
            reviews_count = Review.objects.filter(order_id__in=all_order_ids).count()
            return reviews_count
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Error getting reviews count for user {obj.id}: {str(e)}")
            return 0
    
    def get_completed_orders(self, obj):
        """Get completed orders count"""
        try:
            from apps.order.models import Order, OrderStatus
            return Order.objects.filter(
                master__user=obj,
                status=OrderStatus.COMPLETED,
            ).count()
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Error getting completed orders for user {obj.id}: {str(e)}")
            return 0
    
    def get_acceptance_rate(self, obj):
        """Acceptance rate (%) for masters; drivers get 0."""
        try:
            from apps.master.models import Master
            from apps.master.services.rates import master_acceptance_rate_percent

            m = Master.objects.filter(user=obj).only('id').first()
            if not m:
                return 0
            return master_acceptance_rate_percent(m)
        except Exception:
            return 0

    def get_completion_rate(self, obj):
        """Completion rate (%) for masters; drivers get 0."""
        try:
            from apps.master.services.rates import user_completion_rate_percent

            return user_completion_rate_percent(obj)
        except Exception as e:
            import logging

            logging.getLogger(__name__).exception(
                'get_completion_rate failed user_id=%s: %s',
                getattr(obj, 'id', None),
                e,
            )
            return 0


class UserProfileRegistrationSerializer(serializers.Serializer):
    """Multipart/form POST: full profile fields + email verification flow."""
    first_name = serializers.CharField(max_length=150, required=True)
    last_name = serializers.CharField(max_length=150, required=True)
    email = serializers.EmailField(required=True)
    date_of_birth = serializers.DateField(required=False, allow_null=True)
    avatar = serializers.ImageField(required=False, allow_null=True)


class UserLimitedProfileUpdateSerializer(serializers.ModelSerializer):
    """PUT/PATCH: only first_name, last_name, avatar, date_of_birth (multipart/form-data)."""
    avatar = serializers.ImageField(
        use_url=True,
        required=False,
        allow_null=True,
        help_text="Profile image file",
    )

    class Meta:
        model = CustomUser
        fields = ['first_name', 'last_name', 'avatar', 'date_of_birth']
        extra_kwargs = {
            'first_name': {'required': False},
            'last_name': {'required': False},
            'date_of_birth': {'required': False, 'allow_null': True},
        }


class UserWorkshopComplianceUpdateSerializer(serializers.ModelSerializer):
    """
    PUT/POST: master workshop tools + licenses self-confirmation.

    Once both are confirmed, the attestation is locked: flags stay True and
    ``workshop_compliance_confirmed_at`` is never overwritten (legal evidence).
    """

    class Meta:
        model = CustomUser
        fields = ['has_tools_confirmed', 'has_licenses_confirmed']

    def validate(self, attrs):
        instance = self.instance
        if instance is not None and instance.workshop_compliance_is_locked():
            # Idempotent re-save is OK; unconfirming is not.
            tools = attrs.get('has_tools_confirmed', True)
            licenses = attrs.get('has_licenses_confirmed', True)
            if not tools or not licenses:
                raise serializers.ValidationError(
                    {
                        'non_field_errors': [
                            'Workshop compliance is already confirmed and cannot be changed.'
                        ]
                    }
                )
        return attrs

    def validate_has_tools_confirmed(self, value):
        if not value:
            raise serializers.ValidationError('You must confirm that you have the required tools.')
        return value

    def validate_has_licenses_confirmed(self, value):
        if not value:
            raise serializers.ValidationError(
                'You must confirm that you hold legally required licenses, if applicable.'
            )
        return value

    def update(self, instance, validated_data):
        import logging

        from django.utils import timezone

        from apps.accounts.models import WorkshopComplianceAuditLog

        already_locked = instance.workshop_compliance_is_locked()
        instance = super().update(instance, validated_data)

        first_confirmation = False
        if instance.has_tools_confirmed and instance.has_licenses_confirmed:
            if not instance.workshop_compliance_confirmed_at:
                instance.workshop_compliance_confirmed_at = timezone.now()
                instance.save(update_fields=['workshop_compliance_confirmed_at', 'updated_at'])
                first_confirmation = True
            elif already_locked:
                # Keep original timestamp; still persist True flags if somehow out of sync.
                pass

        if first_confirmation:
            request = self.context.get('request')
            ip = None
            ua = ''
            if request is not None:
                xff = (request.META.get('HTTP_X_FORWARDED_FOR') or '').split(',')[0].strip()
                ip = xff or request.META.get('REMOTE_ADDR') or None
                ua = (request.META.get('HTTP_USER_AGENT') or '')[:512]

            WorkshopComplianceAuditLog.objects.create(
                user=instance,
                has_tools_confirmed=True,
                has_licenses_confirmed=True,
                confirmed_at=instance.workshop_compliance_confirmed_at,
                ip_address=ip,
                user_agent=ua,
            )
            logging.getLogger('apps.accounts.workshop_compliance').info(
                'workshop_compliance_confirmed user_id=%s email=%s phone=%s confirmed_at=%s ip=%s',
                instance.pk,
                getattr(instance, 'email', None) or '',
                getattr(instance, 'phone_number', None) or '',
                instance.workshop_compliance_confirmed_at.isoformat()
                if instance.workshop_compliance_confirmed_at
                else '',
                ip or '',
            )
        return instance


class UserLocationUpdateSerializer(serializers.ModelSerializer):
    """JSON/FORM PUT: latitude, longitude and optional address."""

    latitude = serializers.DecimalField(**WGS84_COORD_DECIMAL_KWARGS, required=True, allow_null=True)
    longitude = serializers.DecimalField(**WGS84_COORD_DECIMAL_KWARGS, required=True, allow_null=True)

    class Meta:
        model = CustomUser
        fields = ['latitude', 'longitude', 'address']
        extra_kwargs = {
            'address': {'required': False, 'allow_blank': True, 'allow_null': True},
        }

    def validate_latitude(self, value):
        if value is None:
            return value
        v = float(value)
        if v < -90 or v > 90:
            raise serializers.ValidationError('Latitude must be between -90 and 90.')
        return value


class UserDeviceSerializer(serializers.Serializer):
    device_token = serializers.CharField()
    device_type = serializers.CharField()
    is_active = serializers.BooleanField()
    updated_at = serializers.DateTimeField()


class UserDeviceUpsertSerializer(serializers.Serializer):
    device_token = serializers.CharField(max_length=512, allow_blank=False)
    device_type = serializers.CharField(max_length=32, allow_blank=False)

    def validate_device_token(self, value):
        return (value or '').strip()

    def validate_device_type(self, value):
        return (value or '').strip()


class UserDeviceActivePatchSerializer(serializers.Serializer):
    is_active = serializers.BooleanField()

    def validate_longitude(self, value):
        if value is None:
            return value
        v = float(value)
        if v < -180 or v > 180:
            raise serializers.ValidationError('Longitude must be between -180 and 180.')
        return value


class EmailVerificationConfirmSerializer(serializers.Serializer):
    code = serializers.CharField(min_length=4, max_length=10, required=True, help_text='4-digit code from email')


class UserUpdateSerializer(serializers.ModelSerializer):
    """Serializer for updating user info"""
    latitude = serializers.DecimalField(**WGS84_COORD_DECIMAL_KWARGS, required=False, allow_null=True)
    longitude = serializers.DecimalField(**WGS84_COORD_DECIMAL_KWARGS, required=False, allow_null=True)
    avatar = serializers.ImageField(
        use_url=True,
        required=False,
        allow_null=True,
        help_text="Upload image file for avatar"
    )
    roles = serializers.CharField(
        required=False,
        allow_blank=True,
        write_only=True,
        help_text="User roles. One or comma-separated: 'Driver', 'Driver,Owner', 'Driver,Master,Owner'"
    )
    
    class Meta:
        model = CustomUser
        fields = [
            'username', 'first_name', 'last_name', 'date_of_birth', 
            'avatar', 'address', 'longitude', 'latitude', 'roles', 'description'
        ]
        extra_kwargs = {
            'username': {'required': False},
            'first_name': {'required': False},
            'last_name': {'required': False},
            'date_of_birth': {'required': False},
            'address': {'required': False},
            'description': {'required': False},
        }
    
    def validate_roles(self, value):
        """Validate and convert roles from string to list"""
        if not value:
            return []
        if isinstance(value, str):
            roles_list = [role.strip() for role in value.split(',') if role.strip()]
        elif isinstance(value, list):
            roles_list = value
        else:
            raise serializers.ValidationError("Roles must be a string or list")
        valid_roles = ['Driver', 'Master', 'Owner']
        for role in roles_list:
            if role not in valid_roles:
                raise serializers.ValidationError(f"Invalid role: {role}. Valid roles: {', '.join(valid_roles)}")
        return roles_list

    def update(self, instance, validated_data):
        """Update user with support for changing multiple roles (groups)"""
        from django.contrib.auth.models import Group
        
        roles = validated_data.pop('roles', None)
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()
        if roles is not None:
            if not roles:
                instance.groups.clear()
            else:
                instance.groups.clear()
                for role_name in roles:
                    group, created = Group.objects.get_or_create(name=role_name)
                    instance.groups.add(group)
        
        return instance


class FAQSerializer(serializers.ModelSerializer):
    """FAQ serializer"""

    class Meta:
        model = FAQ
        fields = ['id', 'question', 'answer', 'order', 'created_at', 'updated_at']
        read_only_fields = ['id', 'created_at', 'updated_at']


class AppVersionSerializer(serializers.ModelSerializer):
    class Meta:
        model = AppVersion
        fields = ["id", "version", "created_at"]
        read_only_fields = fields

