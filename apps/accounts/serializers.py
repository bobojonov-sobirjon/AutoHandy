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
    cleaned = re.sub(r'\D', '', value)
    if len(cleaned) < 10 or len(cleaned) > 15:
        raise ValidationError("Phone number must be 10–15 digits (with country code)")
    # Russia: 8XXXXXXXXXX -> 7XXXXXXXXXX
    if len(cleaned) == 11 and cleaned.startswith('8'):
        cleaned = '7' + cleaned[1:]
    elif len(cleaned) == 10 and cleaned.startswith('9'):
        cleaned = '7' + cleaned
    return cleaned


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
        elif value.startswith(('+', '7', '8', '9')) or (value.replace('+', '').replace(' ', '').replace('-', '').isdigit()):
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
    device_token = serializers.CharField(
        max_length=512,
        required=False,
        allow_blank=False,
        write_only=True,
        help_text='Optional. Send together with device_type (e.g. FCM token). Only used on check-sms-code.',
    )
    device_type = serializers.CharField(
        max_length=32,
        required=False,
        allow_blank=False,
        write_only=True,
        help_text='Optional. e.g. ios, android, web. Must be sent with device_token.',
    )

    def validate(self, attrs):
        token = attrs.get('device_token')
        dtype = attrs.get('device_type')
        if (token and not dtype) or (dtype and not token):
            raise serializers.ValidationError(
                'device_token and device_type must both be sent together, or omit both.'
            )
        if token:
            attrs['device_token'] = token.strip()
        if dtype:
            attrs['device_type'] = dtype.strip()
        return attrs

    def validate_identifier(self, value):
        """Validate and determine identifier type"""
        if not value:
            raise ValidationError("Identifier is required")
        value = value.strip()
        if '@' in value:
            return {'type': 'email', 'value': validate_email_format(value)}
        elif value.startswith(('+', '7', '8', '9')) or (value.replace('+', '').replace(' ', '').replace('-', '').isdigit()):
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
    
    class Meta:
        model = CustomUser
        fields = [
            'id', 'private_id', 'phone_number', 'first_name', 'last_name', 'email',
            'is_verified', 'is_email_verified', 'created_at', 'roles', 'balance',
        ]
        read_only_fields = ['id', 'private_id', 'created_at', 'roles', 'balance']
    
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
    avatar = serializers.ImageField(use_url=True, read_only=True)
    reviews = serializers.SerializerMethodField()
    rating = serializers.SerializerMethodField()
    reviews_count = serializers.SerializerMethodField()
    completed_orders = serializers.SerializerMethodField()
    recommendation_percentage = serializers.SerializerMethodField()
    
    class Meta:
        model = CustomUser
        fields = [
            'id', 'private_id', 'username', 'email', 'phone_number', 'first_name',
            'last_name', 'date_of_birth', 'avatar', 'address',
            'longitude', 'latitude', 'is_verified', 'is_email_verified', 'roles', 'balance',
            'reviews', 'rating', 'reviews_count', 'completed_orders', 'recommendation_percentage',
            'created_at', 'updated_at', 'description',
        ]
        read_only_fields = [
            'id', 'private_id', 'email', 'phone_number', 'is_verified', 'is_email_verified', 'roles', 'balance',
            'reviews', 'rating', 'reviews_count', 'completed_orders', 'recommendation_percentage',
            'created_at', 'updated_at',
        ]
    
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
        return []
    
    def get_reviews(self, obj):
        """Get all reviews about user (as master)"""
        try:
            from apps.order.models import Review, ReviewTag, Order
            from apps.order.services.notifications import _media_url

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
                        'full_name': review.reviewer.get_full_name(),
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
    
    def get_recommendation_percentage(self, obj):
        """Get recommendation percentage (reviews with rating 4-5)"""
        try:
            from apps.order.models import Review, Order
            orders_as_main_master = Order.objects.filter(master__user=obj)
            all_order_ids = set(orders_as_main_master.values_list('id', flat=True))
            all_reviews = Review.objects.filter(order_id__in=all_order_ids)
            total_reviews = all_reviews.count()
            if total_reviews == 0:
                return 0
            positive_reviews = all_reviews.filter(rating__gte=4).count()
            percentage = round((positive_reviews / total_reviews) * 100)
            return percentage
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Error getting recommendation percentage for user {obj.id}: {str(e)}")
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

    def validate_longitude(self, value):
        if value is None:
            return value
        v = float(value)
        if v < -180 or v > 180:
            raise serializers.ValidationError('Longitude must be between -180 and 180.')
        return value


class EmailVerificationConfirmSerializer(serializers.Serializer):
    token = serializers.UUIDField(required=True)


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

