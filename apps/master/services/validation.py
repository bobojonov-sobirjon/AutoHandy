"""Validation helpers for master skills (catalog subcategories)."""

from rest_framework import serializers as drf_serializers

from apps.categories.models import Category


def validate_skill_category(category: Category) -> None:
    """
    Skills (MasterServiceItems.category) must use the order-service catalog: by_order
    (subcategories used when drivers search/book, e.g. Lockout, Jump Start).
    """
    if category.is_custom_request_entry or (
        category.parent_id
        and Category.objects.filter(pk=category.parent_id, is_custom_request_entry=True).exists()
    ):
        raise drf_serializers.ValidationError(
            'This category is reserved for client custom requests and cannot be used as a skill.'
        )
    if category.is_towing_entry or (
        category.parent_id
        and Category.objects.filter(pk=category.parent_id, is_towing_entry=True).exists()
    ):
        raise drf_serializers.ValidationError(
            'This category is reserved for client towing orders and cannot be used as a skill.'
        )
    from apps.order.services.truck_orders import is_truck_towing_subcategory

    if is_truck_towing_subcategory(category):
        raise drf_serializers.ValidationError(
            'Semi-truck towing uses mileage pricing (base fee + per mile). '
            'Set it under Master towing pricing with service_type semi_truck.'
        )
    if category.type_category != Category.TypeCategory.BY_ORDER:
        raise drf_serializers.ValidationError(
            'Skill category must be type by_order (service catalog).'
        )
