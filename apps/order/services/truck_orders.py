"""Semi-truck (Roadside Semi Truck) order helpers."""
from __future__ import annotations

from apps.categories.models import Category
from apps.master.towing_types import TowingServiceType

TRUCK_TOWING_SERVICE_TYPE = TowingServiceType.SEMI_TRUCK


def is_truck_towing_subcategory(category: Category) -> bool:
    return bool(
        category.is_truck
        and category.parent_id
        and 'towing' in (category.name or '').lower()
    )


def get_truck_subcategory(category_id: int) -> Category | None:
    return (
        Category.objects.filter(
            pk=category_id,
            is_truck=True,
            parent__isnull=False,
            type_category=Category.TypeCategory.BY_ORDER,
        )
        .select_related('parent')
        .first()
    )


def build_truck_order_text(
    category: Category,
    truck_make_model: str,
    truck_year: int | None = None,
) -> str:
    base = f'{category.name} — {truck_make_model.strip()}'
    if truck_year:
        return f'{base} ({truck_year})'
    return base


def truck_payload_from_order(order) -> dict | None:
    make_model = (getattr(order, 'truck_make_model', '') or '').strip()
    if not make_model:
        return None
    return {
        'make_model': make_model,
        'year': getattr(order, 'truck_year', None),
    }
