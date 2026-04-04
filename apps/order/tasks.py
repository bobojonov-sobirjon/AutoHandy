from __future__ import annotations

from datetime import timedelta

from celery import shared_task
from django.conf import settings
from django.utils import timezone

from apps.order.models import Order, OrderStatus
from apps.order.services.offer_expiry import (
    expire_master_offer_for_order,
    expire_stale_master_offers,
)


@shared_task(ignore_result=True)
def expire_stale_master_offers_task() -> int:
    """
    Celery Beat (every minute): pending orders whose master_response_deadline passed.
    Standard: status → rejected, master cleared. SOS with queue: broadcast window ended → reject.
    """
    return expire_stale_master_offers()


@shared_task(ignore_result=True)
def sos_rotate_master_if_stale_task(order_id: int, offered_master_id: int) -> None:
    from apps.order.services.sos_rotation import try_rotate_sos_on_celery_tick

    try_rotate_sos_on_celery_tick(order_id, offered_master_id)


@shared_task(ignore_result=True)
def expire_master_offer_order_task(order_id: int) -> bool:
    """ETA-fired task when the 15-minute (configurable) master offer ends."""
    return expire_master_offer_for_order(order_id)


@shared_task(ignore_result=True)
def unlock_client_penalty_free_cancel_task(order_id: int) -> None:
    """
    ETA task: after N hours «on the way», allow client penalty-free cancel (if still on the way).
    """
    Order.objects.filter(pk=order_id, status=OrderStatus.ON_THE_WAY).update(
        client_penalty_free_cancel_unlocked=True,
    )


@shared_task(ignore_result=True)
def sweep_client_penalty_free_unlock_task() -> int:
    """
    Fallback if ETA tasks were missed (worker down): unlock flag for stale on_the_way orders.
    """
    hours = int(getattr(settings, 'CLIENT_CANCEL_NO_PENALTY_AFTER_ON_THE_WAY_HOURS', 2))
    cutoff = timezone.now() - timedelta(hours=hours)
    qs = Order.objects.filter(
        status=OrderStatus.ON_THE_WAY,
        on_the_way_at__isnull=False,
        on_the_way_at__lte=cutoff,
        client_penalty_free_cancel_unlocked=False,
    )
    n = qs.update(client_penalty_free_cancel_unlocked=True)
    return n
