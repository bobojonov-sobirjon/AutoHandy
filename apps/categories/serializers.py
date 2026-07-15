from rest_framework import serializers
from apps.categories.models import Category
from apps.categories.media_urls import absolute_media_url
from django.core.exceptions import ValidationError
import os


def validate_icon_file(value):
    """Validator to ensure only image files (including SVG) are accepted"""
    if value:
        allowed_extensions = ['.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp', '.svg']
        ext = os.path.splitext(value.name)[1].lower()
        if ext not in allowed_extensions:
            raise ValidationError(
                f'File format not supported. Allowed formats: {", ".join(allowed_extensions)}'
            )
    return value


class CategorySerializer(serializers.ModelSerializer):

    class Meta:
        model = Category
        fields = [
            'id',
            'name',
            'icon',
            'type_category',
            'parent',
            'is_truck',
            'sort_order',
            'created_at',
            'updated_at',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']
        extra_kwargs = {
            'icon': {'validators': [validate_icon_file]},
            'parent': {'allow_null': True, 'required': False},
        }

    def validate_parent(self, value):
        if value and getattr(self.instance, 'pk', None) and value.pk == self.instance.pk:
            raise serializers.ValidationError('A category cannot be its own parent.')
        return value

    def to_representation(self, instance):
        """Override to return full HTTPS URL for icon field"""
        representation = super().to_representation(instance)
        representation['icon'] = absolute_media_url(self.context.get('request'), instance.icon)
        return representation