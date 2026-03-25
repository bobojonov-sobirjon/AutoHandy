import os

from django.conf import settings
from django.core.exceptions import ValidationError
from rest_framework import serializers

from apps.accounts.serializers import UserSerializer
from apps.categories.models import Category
from apps.categories.serializers import CategorySerializer

from .models import Car


class OptionalIntegerField(serializers.IntegerField):
    """Multipart/form often sends '' for empty optional numbers."""

    def to_internal_value(self, data):
        if data is None or data == '':
            return None
        return super().to_internal_value(data)


class OptionalPrimaryKeyRelatedField(serializers.PrimaryKeyRelatedField):
    """Multipart may send '' for an optional FK."""

    def to_internal_value(self, data):
        if data in ('', None):
            return None
        return super().to_internal_value(data)


def validate_car_image_file(value):
    if value:
        allowed_extensions = ['.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp', '.svg']
        ext = os.path.splitext(value.name)[1].lower()
        if ext not in allowed_extensions:
            raise ValidationError(
                f'File format not supported. Allowed formats: {", ".join(allowed_extensions)}'
            )
    return value


class CarSerializer(serializers.ModelSerializer):
    """Read serializer: nested category/user and absolute image URL."""

    category = serializers.SerializerMethodField()
    user = serializers.SerializerMethodField()

    class Meta:
        model = Car
        fields = [
            'id',
            'category',
            'brand',
            'model',
            'year',
            'image',
            'user',
            'created_at',
            'updated_at',
        ]
        read_only_fields = ['id', 'user', 'created_at', 'updated_at']

    def get_category(self, obj):
        if obj.category is None:
            return None
        return CategorySerializer(obj.category, context=self.context).data

    def get_user(self, obj):
        if obj.user is None:
            return None
        return UserSerializer(obj.user, context=self.context).data

    def to_representation(self, instance):
        representation = super().to_representation(instance)
        if instance.image:
            request = self.context.get('request')
            if request:
                representation['image'] = request.build_absolute_uri(instance.image.url)
            else:
                representation['image'] = f'{settings.MEDIA_URL}{instance.image.url}'
        else:
            representation['image'] = None
        return representation


class CarWriteSerializer(serializers.ModelSerializer):
    """Create/update via multipart/form-data or JSON; includes file field `image`."""

    category = OptionalPrimaryKeyRelatedField(
        queryset=Category.objects.all(),
        allow_null=True,
        required=False,
    )
    year = OptionalIntegerField(required=False, allow_null=True)
    image = serializers.ImageField(
        required=False,
        allow_null=True,
        validators=[validate_car_image_file],
    )

    class Meta:
        model = Car
        fields = ['category', 'brand', 'model', 'year', 'image']
        extra_kwargs = {
            'brand': {'allow_blank': True, 'required': False},
            'model': {'allow_blank': True, 'required': False},
        }

    def create(self, validated_data):
        validated_data['user'] = self.context['request'].user
        return super().create(validated_data)
