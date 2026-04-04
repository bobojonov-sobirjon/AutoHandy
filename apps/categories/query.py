"""Category tree helpers for smart filters (replaces old service_type linking)."""
from django.db.models import Q


def order_by_order_category_smart_q(category) -> Q:
    """
    Match orders whose problem category is the same node, a sibling (same parent),
    the parent node, or a direct child (when filtering by a root category).
    """
    q = Q(category_id=category.id)
    if category.parent_id:
        q |= Q(category__parent_id=category.parent_id)
        q |= Q(category_id=category.parent_id)
    else:
        q |= Q(category__parent_id=category.id)
    if category.name:
        q |= Q(category__name__icontains=category.name)
    return q


def master_by_order_category_strict_q(category) -> Q:
    """Masters who have at least one MasterServiceItem for this exact category (no parent/sibling expansion)."""
    return Q(master_services__master_service_items__category_id=category.id)


def master_by_order_category_smart_q(category) -> Q:
    """Masters relevant to a by_order category: MasterServiceItems + parent tree."""
    q = Q()
    item_path = 'master_services__master_service_items__category'
    q |= Q(**{f'{item_path}__id': category.id})
    if category.parent_id:
        q |= Q(**{f'{item_path}__parent_id': category.parent_id})
        q |= Q(**{f'{item_path}__id': category.parent_id})
    else:
        q |= Q(**{f'{item_path}__parent_id': category.id})

    if category.name:
        q |= Q(master_services__master_service_items__category__name__icontains=category.name)
    return q
