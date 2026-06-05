"""Apply client fuel type to Fuel Delivery order lines."""
from __future__ import annotations

from typing import TYPE_CHECKING

from apps.categories.services.fuel_delivery_catalog import is_fuel_delivery_category
from apps.order.models import FuelDeliveryType, OrderService

if TYPE_CHECKING:
    from apps.order.models import Order


def apply_fuel_type_to_order_services(
    order: 'Order',
    fuel_type: str,
    category_ids: list[int] | None = None,
) -> int:
    """
    Set ``fuel_type`` on OrderService rows whose master line category is Fuel Delivery.
    Returns number of rows updated.
    """
    if fuel_type not in FuelDeliveryType.values:
        return 0

    cat_ids = category_ids if category_ids is not None else list(
        order.category.values_list('pk', flat=True)
    )
    if not cat_ids:
        return 0

    updated = 0
    qs = (
        OrderService.objects.filter(order=order)
        .select_related('master_service_item__category')
    )
    for os_row in qs:
        item = os_row.master_service_item
        if not item or not item.category_id:
            continue
        if item.category_id not in cat_ids:
            continue
        if not is_fuel_delivery_category(item.category):
            continue
        if os_row.fuel_type != fuel_type:
            os_row.fuel_type = fuel_type
            os_row.save(update_fields=['fuel_type'])
            updated += 1
    return updated
