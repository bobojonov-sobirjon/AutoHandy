"""Lock per-line service prices on an order so master profile edits do not rewrite history."""
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from apps.master.models import MasterServiceItems
    from apps.order.models import Order, OrderService


def _q(x) -> Decimal:
    return Decimal(str(x)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


def locked_unit_price_for_item(item: 'MasterServiceItems') -> Decimal:
    return _q(getattr(item, 'price', None) or 0)


def order_service_unit_price(os_row: 'OrderService', item: 'MasterServiceItems | None' = None) -> Decimal:
    """
    Price used in order totals: frozen ``OrderService.unit_price`` when set,
    otherwise live ``master_service_item.price`` (legacy rows).
    """
    snap = getattr(os_row, 'unit_price', None)
    if snap is not None:
        return _q(snap)
    if item is None:
        item = getattr(os_row, 'master_service_item', None)
    if item is not None:
        return locked_unit_price_for_item(item)
    return Decimal('0')


def get_or_create_order_service_locked(
    *,
    order: 'Order',
    master_service_item: 'MasterServiceItems',
    count: int = 1,
) -> tuple['OrderService', bool]:
    from apps.order.models import OrderService

    defaults = {
        'unit_price': locked_unit_price_for_item(master_service_item),
        'count': max(1, int(count or 1)),
    }
    os_row, created = OrderService.objects.get_or_create(
        order=order,
        master_service_item=master_service_item,
        defaults=defaults,
    )
    if not created:
        update_fields: list[str] = []
        if os_row.unit_price is None:
            os_row.unit_price = locked_unit_price_for_item(master_service_item)
            update_fields.append('unit_price')
        if update_fields:
            os_row.save(update_fields=update_fields)
    return os_row, created


def lock_order_service_prices(order: 'Order') -> int:
    """
    Snapshot any missing ``unit_price`` values from the current master line price.
    Idempotent — safe to call on accept and again on complete.
    """
    from apps.order.models import OrderService

    updated = 0
    qs = (
        OrderService.objects.filter(order=order, unit_price__isnull=True)
        .select_related('master_service_item')
    )
    for os_row in qs:
        item = os_row.master_service_item
        if not item:
            continue
        os_row.unit_price = locked_unit_price_for_item(item)
        os_row.save(update_fields=['unit_price'])
        updated += 1
    return updated
