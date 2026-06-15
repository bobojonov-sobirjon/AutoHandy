"""Semi-truck Emergency Roadside category helpers."""
from __future__ import annotations

from django.db.models import Q

from apps.categories.models import Category

TRUCK_ROADSIDE_MAIN_NAME = 'Roadside Semi Truck'
TRUCK_ROADSIDE_MAIN_LEGACY_NAME = 'Emergency Roadside for Semi Trucks'


def get_truck_roadside_main_category() -> Category | None:
    return (
        Category.objects.filter(
            is_truck=True,
            parent__isnull=True,
            type_category=Category.TypeCategory.BY_ORDER,
        )
        .filter(Q(name=TRUCK_ROADSIDE_MAIN_NAME) | Q(name=TRUCK_ROADSIDE_MAIN_LEGACY_NAME))
        .order_by('id')
        .first()
    )


def truck_subcategory_names() -> list[str]:
    main = get_truck_roadside_main_category()
    if not main:
        return []
    return list(
        Category.objects.filter(parent=main, is_truck=True)
        .order_by('name')
        .values_list('name', flat=True)
    )
