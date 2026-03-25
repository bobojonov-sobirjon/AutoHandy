"""Validation helpers for master skills (catalog subcategories)."""

from rest_framework import serializers as drf_serializers

from apps.categories.models import Category


def validate_skill_category(category: Category) -> None:
    """
    Skills (MasterServiceItems.category) must use the master workshop catalog: by_master.
    Parent is optional (root or child by_master node).
    """
    if category.type_category != Category.TypeCategory.BY_MASTER:
        raise drf_serializers.ValidationError(
            'Skill category must be type by_master (workshop category catalog).'
        )
