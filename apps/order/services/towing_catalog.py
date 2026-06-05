"""Towing entry category lookup (client-only catalog entry)."""
from __future__ import annotations

from apps.categories.models import Category


def get_towing_catalog_category() -> Category | None:
    """Main category flagged as the client-only towing entry (by_order)."""
    return (
        Category.objects.filter(
            is_towing_entry=True,
            parent__isnull=True,
            type_category=Category.TypeCategory.BY_ORDER,
        )
        .order_by('id')
        .first()
    )
