"""Standard order: notify when master accepted but did not mark on the way (accept + N minutes)."""
from __future__ import annotations

from datetime import timedelta

from django.core.cache import cache
from django.utils import timezone

from apps.order.models import Order, OrderStatus, OrderType
from apps.order.services.mvp_timers import _master_no_departure_minutes
from apps.order.services.order_scheduled_start import order_has_scheduled_start


def notify_standard_accept_no_on_the_way_if_due(*, order_id: int, now=None) -> bool:
    """
    Push user + master if order is still ACCEPTED without on_the_way_at and accept+N minutes passed.
    Does not cancel (scheduled orders keep start+30 cancel). Non-scheduled cancel is separate.
    """
    now = now or timezone.now()
    minutes = _master_no_departure_minutes()
    if minutes <= 0:
        return False
    try:
        order = Order.objects.select_related('master').get(pk=order_id)
    except Order.DoesNotExist:
        return False
    if order.order_type != OrderType.STANDARD or not order_has_scheduled_start(order):
        return False
    if order.status != OrderStatus.ACCEPTED or order.on_the_way_at is not None:
        return False
    if not order.accepted_at or order.accepted_at > now - timedelta(minutes=minutes):
        return False
    cache_key = f'std_accept_no_otw_{order_id}'
    if cache.get(cache_key):
        return False
    cache.set(cache_key, 1, timeout=minutes * 60 + 3600)
    try:
        from apps.master.models import Master
        from apps.order.services.notifications import notify_master_order_kind, notify_user_order_kind

        extra = {'by': 'system', 'minutes': str(minutes)}
        notify_user_order_kind(order, kind='standard_accept_no_on_the_way', extra_data=extra)
        if order.master_id:
            mu = Master.objects.select_related('user').only('id', 'user_id').get(pk=order.master_id)
            notify_master_order_kind(
                master_user_id=mu.user_id,
                order_id=order.id,
                kind='standard_accept_no_on_the_way',
                extra_data=extra,
            )
    except Exception:  # noqa: BLE001
        pass
    return True


def sweep_standard_accept_no_on_the_way(*, now=None) -> int:
    """Beat fallback: warn on all stale accepted standard orders (incl. scheduled)."""
    now = now or timezone.now()
    minutes = _master_no_departure_minutes()
    if minutes <= 0:
        return 0
    cutoff = now - timedelta(minutes=minutes)
    qs = Order.objects.filter(
        order_type=OrderType.STANDARD,
        status=OrderStatus.ACCEPTED,
        on_the_way_at__isnull=True,
        accepted_at__isnull=False,
        accepted_at__lte=cutoff,
        preferred_date__isnull=False,
        preferred_time_start__isnull=False,
    ).only('id', 'preferred_date', 'preferred_time_start')
    n = 0
    for order in qs.iterator(chunk_size=100):
        if notify_standard_accept_no_on_the_way_if_due(order_id=order.pk, now=now):
            n += 1
    return n
