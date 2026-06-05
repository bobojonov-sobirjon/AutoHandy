"""Fuel Delivery by_order category helpers."""
from __future__ import annotations

from apps.categories.models import Category

FUEL_DELIVERY_CATEGORY_NAME = 'Fuel Delivery'


def is_fuel_delivery_category(category: Category | None) -> bool:
    if not category:
        return False
    return (category.name or '').strip().lower() == FUEL_DELIVERY_CATEGORY_NAME.lower()


def fuel_delivery_category_ids() -> list[int]:
    return list(
        Category.objects.filter(
            name__iexact=FUEL_DELIVERY_CATEGORY_NAME,
            type_category=Category.TypeCategory.BY_ORDER,
        ).values_list('id', flat=True)
    )


def fuel_delivery_category_id_set() -> set[int]:
    return set(fuel_delivery_category_ids())


def categories_include_fuel_delivery(category_ids: list[int]) -> bool:
    if not category_ids:
        return False
    fuel_ids = fuel_delivery_category_id_set()
    return bool(fuel_ids.intersection(category_ids))
