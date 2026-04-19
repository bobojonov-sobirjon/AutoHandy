"""
Attach ``OrderService`` rows from the order's categories + assigned master's priced lines.

``MasterServiceItems`` rows are matched by ``category_id`` ∈ ``order.category`` for
``master_service__master_id`` = ``order.master_id``. Idempotent (get_or_create).
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from apps.order.models import Order


def sync_order_services_from_order_categories(order: 'Order') -> int:
    """
    For each ``MasterServiceItems`` row belonging to ``order.master`` whose ``category_id``
    appears on the order's category M2M, ensure an ``OrderService`` link exists.

    Returns the number of ``MasterServiceItems`` processed (lines ensured, including those
    that already existed).
    """
    from apps.master.models import MasterServiceItems
    from apps.order.models import OrderService

    master_id = order.master_id
    if not master_id:
        return 0

    cat_ids = list(order.category.values_list('pk', flat=True))
    if not cat_ids:
        return 0

    items = MasterServiceItems.objects.filter(
        master_service__master_id=master_id,
        category_id__in=cat_ids,
    )
    n = 0
    for item in items:
        OrderService.objects.get_or_create(
            order=order,
            master_service_item=item,
        )
        n += 1
    return n
