"""Home screen sort order for main by_order categories (driver app)."""
from __future__ import annotations

from django.db.models import F, Q, QuerySet

from apps.categories.models import Category

TRUCK_ROADSIDE_MAIN_NAME = 'Roadside Semi Truck'
TRUCK_ROADSIDE_MAIN_LEGACY_NAME = 'Emergency Roadside for Semi Trucks'

# Client-approved main catalog order (by_order, parent=null).
HOME_SCREEN_MAIN_BY_ORDER: tuple[dict, ...] = (
    {
        'sort_order': 1,
        'flags': {'is_towing_entry': True},
    },
    {
        'sort_order': 2,
        'names': ('Locksmith',),
    },
    {
        'sort_order': 3,
        'names': ('Roadside Assistance', 'Roadside Help'),
    },
    {
        'sort_order': 4,
        'names': ('Upgrades & Installations', 'Upgrades and Installations'),
    },
    {
        'sort_order': 5,
        'names': ('Window Tint',),
    },
    {
        'sort_order': 6,
        'names': ('Glass Services',),
    },
    {
        'sort_order': 7,
        'names': ('Cosmetic Repair',),
    },
    {
        'sort_order': 8,
        'names': ('Motorcycle Services', 'Motorcycle Service'),
    },
    {
        'sort_order': 9,
        'names': ('Car Detailing',),
    },
    {
        'sort_order': 10,
        'names': ('Bicycle Services', 'Bicycle Service'),
    },
    {
        'sort_order': 11,
        'names': ('Mobile Mechanic',),
    },
    {
        'sort_order': 12,
        'names': ('A/C Service', 'AC Service', 'Air Conditioning Service'),
    },
    {
        'sort_order': 13,
        'names': ('Tire Services', 'Tire Service'),
    },
    {
        'sort_order': 14,
        'names': ('Pre-Purchase Inspection', 'Pre Purchase Inspection'),
    },
    {
        'sort_order': 15,
        'names': (TRUCK_ROADSIDE_MAIN_NAME, TRUCK_ROADSIDE_MAIN_LEGACY_NAME),
        'flags': {'is_truck': True},
        'rename_to': TRUCK_ROADSIDE_MAIN_NAME,
    },
    {
        'sort_order': 16,
        'flags': {'is_custom_request_entry': True},
    },
)


def _name_lookup(names: tuple[str, ...]) -> Q:
    q = Q()
    for name in names:
        q |= Q(name__iexact=name)
    return q


def _find_main_by_order_categories(spec: dict) -> list[Category]:
    qs = Category.objects.filter(
        type_category=Category.TypeCategory.BY_ORDER,
        parent__isnull=True,
    )
    flags = spec.get('flags') or {}
    for key, value in flags.items():
        qs = qs.filter(**{key: value})

    names = spec.get('names') or ()
    if names:
        qs = qs.filter(_name_lookup(names))

    return list(qs.order_by('id'))


def apply_home_screen_category_order(*, dry_run: bool = False) -> dict[str, int]:
    """
    Assign ``sort_order`` to main by_order categories and rename semi-truck main category.

    Returns counters: matched, updated, renamed.
    """
    matched = 0
    updated = 0
    renamed = 0

    for spec in HOME_SCREEN_MAIN_BY_ORDER:
        categories = _find_main_by_order_categories(spec)
        if not categories:
            continue

        new_name = spec.get('rename_to')
        sort_order = spec['sort_order']

        for category in categories:
            matched += 1
            changed_fields: list[str] = []

            if new_name and category.name != new_name:
                if not dry_run:
                    category.name = new_name
                changed_fields.append('name')
                renamed += 1

            if category.sort_order != sort_order:
                if not dry_run:
                    category.sort_order = sort_order
                changed_fields.append('sort_order')

            if changed_fields and not dry_run:
                category.save(update_fields=changed_fields)
            if changed_fields:
                updated += 1

    return {'matched': matched, 'updated': updated, 'renamed': renamed}


def order_categories_for_display(qs: QuerySet) -> QuerySet:
    """Sort categories for public list APIs: sort_order asc, then name."""
    return qs.order_by(F('sort_order').asc(nulls_last=True), 'name', 'id')
