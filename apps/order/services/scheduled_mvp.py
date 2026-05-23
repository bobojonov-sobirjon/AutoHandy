"""Scheduled-order MVP: reminders, warnings, auto-cancel when master did not start."""
from __future__ import annotations

from datetime import timedelta

from django.conf import settings
from django.core.cache import cache
from django.utils import timezone

from apps.order.models import Order, OrderStatus, OrderType
from apps.order.services.order_scheduled_start import order_has_scheduled_start, order_scheduled_start_datetime


def _active_before_work_started(order) -> bool:
    return order.status in (OrderStatus.ACCEPTED, OrderStatus.ON_THE_WAY)


def send_scheduled_reminder_before_start(*, order_id: int, now=None) -> bool:
    now = now or timezone.now()
    try:
        order = Order.objects.select_related('master').get(pk=order_id)
    except Order.DoesNotExist:
        return False
    if order.order_type != OrderType.STANDARD or not order_has_scheduled_start(order):
        return False
    if order.status not in (
        OrderStatus.ACCEPTED,
        OrderStatus.ON_THE_WAY,
        OrderStatus.ARRIVED,
        OrderStatus.IN_PROGRESS,
    ):
        return False
    start = order_scheduled_start_datetime(order)
    if not start:
        return False
    before_min = int(getattr(settings, 'SCHEDULED_REMINDER_BEFORE_START_MINUTES', 60))
    if now < start - timedelta(minutes=before_min):
        return False
    if now >= start:
        return False
    cache_key = f'scheduled_reminder_{order_id}'
    if cache.get(cache_key):
        return False
    cache.set(cache_key, 1, timeout=3600)
    try:
        from apps.master.models import Master
        from apps.order.services.notifications import notify_master_order_kind, notify_user_order_kind

        remaining = int(max(0, (start - now).total_seconds() // 60))
        extra = {'minutes_until_start': str(remaining)}
        notify_user_order_kind(order, kind='scheduled_start_reminder', extra_data=extra)
        if order.master_id:
            mu = Master.objects.select_related('user').only('id', 'user_id').get(pk=order.master_id)
            notify_master_order_kind(
                master_user_id=mu.user_id,
                order_id=order.id,
                kind='scheduled_start_reminder',
                extra_data=extra,
            )
    except Exception:  # noqa: BLE001
        pass
    return True


def send_scheduled_no_start_warning(*, order_id: int, now=None) -> bool:
    now = now or timezone.now()
    try:
        order = Order.objects.select_related('master').get(pk=order_id)
    except Order.DoesNotExist:
        return False
    if order.order_type != OrderType.STANDARD or not order_has_scheduled_start(order):
        return False
    if not _active_before_work_started(order):
        return False
    start = order_scheduled_start_datetime(order)
    if not start:
        return False
    warn_after = int(getattr(settings, 'SCHEDULED_NO_START_WARNING_MINUTES', 20))
    if now < start + timedelta(minutes=warn_after):
        return False
    cache_key = f'scheduled_no_start_warn_{order_id}'
    if cache.get(cache_key):
        return False
    cache.set(cache_key, 1, timeout=3600)
    try:
        from apps.master.models import Master
        from apps.order.services.notifications import notify_master_order_kind, notify_user_order_kind

        extra = {'by': 'system'}
        notify_user_order_kind(order, kind='scheduled_no_start_warning', extra_data=extra)
        if order.master_id:
            mu = Master.objects.select_related('user').only('id', 'user_id').get(pk=order.master_id)
            notify_master_order_kind(
                master_user_id=mu.user_id,
                order_id=order.id,
                kind='scheduled_no_start_warning',
                extra_data={**extra, 'urgent': 'true'},
            )
    except Exception:  # noqa: BLE001
        pass
    return True


def cancel_scheduled_no_start(*, order_id: int, now=None) -> bool:
    now = now or timezone.now()
    try:
        order = Order.objects.select_related('master').get(pk=order_id)
    except Order.DoesNotExist:
        return False
    if order.order_type != OrderType.STANDARD or not order_has_scheduled_start(order):
        return False
    if not _active_before_work_started(order):
        return False
    start = order_scheduled_start_datetime(order)
    if not start:
        return False
    cancel_after = int(getattr(settings, 'SCHEDULED_NO_START_CANCEL_MINUTES', 30))
    if now < start + timedelta(minutes=cancel_after):
        return False

    old_master_id = order.master_id
    order.status = OrderStatus.CANCELLED
    order.auto_cancel_reason = 'scheduled_no_start'
    order.save(update_fields=['status', 'auto_cancel_reason', 'updated_at'])
    try:
        from apps.master.models import Master
        from apps.order.services.notifications import notify_master_order_kind, notify_user_order_kind

        extra = {'by': 'system'}
        notify_user_order_kind(order, kind='auto_cancel_scheduled_no_start', extra_data=extra)
        if old_master_id:
            mu = Master.objects.select_related('user').only('id', 'user_id').get(pk=old_master_id)
            notify_master_order_kind(
                master_user_id=mu.user_id,
                order_id=order.id,
                kind='auto_cancel_scheduled_no_start',
                extra_data=extra,
            )
    except Exception:  # noqa: BLE001
        pass
    return True


def sweep_scheduled_mvp_deadlines(*, now=None) -> int:
    """Beat fallback for scheduled MVP timers when Celery ETA tasks were missed."""
    now = now or timezone.now()
    from django.conf import settings

    before_min = int(getattr(settings, 'SCHEDULED_REMINDER_BEFORE_START_MINUTES', 60))
    warn_after = int(getattr(settings, 'SCHEDULED_NO_START_WARNING_MINUTES', 20))
    cancel_after = int(getattr(settings, 'SCHEDULED_NO_START_CANCEL_MINUTES', 30))

    qs = (
        Order.objects.filter(
            order_type=OrderType.STANDARD,
            preferred_date__isnull=False,
            preferred_time_start__isnull=False,
            status__in=(OrderStatus.ACCEPTED, OrderStatus.ON_THE_WAY),
        )
        .only('id', 'preferred_date', 'preferred_time_start', 'status')
    )
    n = 0
    for order in qs.iterator(chunk_size=100):
        start = order_scheduled_start_datetime(order)
        if not start:
            continue
        if send_scheduled_reminder_before_start(order_id=order.pk, now=now):
            n += 1
            continue
        if now >= start + timedelta(minutes=cancel_after):
            if cancel_scheduled_no_start(order_id=order.pk, now=now):
                n += 1
            continue
        if now >= start + timedelta(minutes=warn_after):
            if send_scheduled_no_start_warning(order_id=order.pk, now=now):
                n += 1
    return n
