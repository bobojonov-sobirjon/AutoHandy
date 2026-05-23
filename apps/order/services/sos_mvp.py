"""SOS MVP: no-departure warning before auto-rebroadcast."""
from __future__ import annotations

from django.utils import timezone

from apps.order.models import Order, OrderStatus, OrderType


def send_sos_no_departure_warning(*, order_id: int, now=None) -> bool:
    now = now or timezone.now()
    try:
        order = Order.objects.select_related('master').get(pk=order_id)
    except Order.DoesNotExist:
        return False
    if order.order_type != OrderType.SOS:
        return False
    if order.status != OrderStatus.ACCEPTED or order.on_the_way_at is not None:
        return False
    if not order.master_id:
        return False
    try:
        from apps.master.models import Master
        from apps.order.services.notifications import notify_master_order_kind

        mu = Master.objects.select_related('user').only('id', 'user_id').get(pk=order.master_id)
        notify_master_order_kind(
            master_user_id=mu.user_id,
            order_id=order.id,
            kind='sos_departure_warning',
            extra_data={'urgent': 'true', 'order_type': str(order.order_type)},
        )
    except Exception:  # noqa: BLE001
        pass
    return True
