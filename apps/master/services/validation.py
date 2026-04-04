"""Validation helpers for master skills (catalog subcategories)."""

from rest_framework import serializers as drf_serializers

from apps.categories.models import Category


def validate_skill_category(category: Category) -> None:
    """
    Skills (MasterServiceItems.category) must use the order-service catalog: by_order
    (subcategories used when drivers search/book, e.g. Lockout, Jump Start).
    """
    if category.type_category != Category.TypeCategory.BY_ORDER:
        raise drf_serializers.ValidationError(
            'Skill category must be type by_order (service catalog).'
        )
