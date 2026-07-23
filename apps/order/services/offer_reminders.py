"""Repeat FCM for unanswered master new-order offers (Celery)."""
from __future__ import annotations

import logging

from django.conf import settings
from django.utils import timezone

from apps.order.models import Order, OrderStatus, OrderType

logger = logging.getLogger(__name__)


def _reminder_enabled() -> bool:
    return bool(getattr(settings, 'MASTER_NEW_ORDER_REMINDER_ENABLED', True))


def reminder_interval_seconds_for_order(order: Order | None = None, *, order_type: str | None = None) -> int:
    """
    SOS → every 5s (loud/urgent).
    All other order types → every 60s (1 minute) by default.
    """
    ot = (order_type or (getattr(order, 'order_type', None) if order is not None else None) or '').strip().lower()
    if ot == OrderType.SOS or ot == 'sos':
        return max(1, int(getattr(settings, 'MASTER_NEW_ORDER_REMINDER_SOS_SECONDS', 5) or 5))
    return max(1, int(getattr(settings, 'MASTER_NEW_ORDER_REMINDER_SECONDS', 60) or 60))


def reminder_max_count() -> int:
    return max(1, int(getattr(settings, 'MASTER_NEW_ORDER_REMINDER_MAX_COUNT', 180) or 180))


def master_still_needs_new_order_reminder(*, order: Order, master_id: int) -> bool:
    """True while the offer is open and this master should keep getting loud reminders."""
    if order.status != OrderStatus.PENDING:
        return False
    if order.master_response_deadline and timezone.now() >= order.master_response_deadline:
        return False

    if order.order_type == OrderType.SOS and order.sos_offer_queue:
        from apps.order.services.sos_rotation import master_eligible_for_pending_sos_offer

        return bool(master_eligible_for_pending_sos_offer(order, master_id))

    return bool(order.master_id and int(order.master_id) == int(master_id))


def schedule_master_new_order_reminder(
    order_id: int,
    master_id: int,
    *,
    attempt: int = 1,
    order_type: str | None = None,
    countdown: int | None = None,
) -> None:
    """Queue the next reminder push (interval depends on SOS vs non-SOS)."""
    if not _reminder_enabled():
        return
    if attempt < 1 or attempt > reminder_max_count():
        return

    if countdown is None:
        if order_type:
            countdown = reminder_interval_seconds_for_order(order_type=order_type)
        else:
            try:
                ot = (
                    Order.objects.filter(pk=order_id)
                    .values_list('order_type', flat=True)
                    .first()
                )
            except Exception:  # noqa: BLE001
                ot = None
            countdown = reminder_interval_seconds_for_order(order_type=ot)

    try:
        from apps.order.tasks import remind_master_pending_offer_task

        remind_master_pending_offer_task.apply_async(
            args=[int(order_id), int(master_id), int(attempt)],
            countdown=int(countdown),
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            'schedule_master_new_order_reminder failed order_id=%s master_id=%s: %s',
            order_id,
            master_id,
            exc,
        )


def start_master_new_order_reminder_chain(
    order_id: int,
    master_id: int,
    *,
    order_type: str | None = None,
) -> None:
    """Call right after the first new-order FCM — first reminder after the type-specific interval."""
    schedule_master_new_order_reminder(
        order_id,
        master_id,
        attempt=1,
        order_type=order_type,
    )


def send_and_reschedule_master_new_order_reminder(
    *,
    order_id: int,
    master_id: int,
    attempt: int,
) -> bool:
    """
    Celery worker entry: send one reminder if still eligible, then schedule the next.
    Interval: SOS every 5s, other orders every 60s (configurable).
    """
    if not _reminder_enabled():
        return False
    if attempt < 1 or attempt > reminder_max_count():
        return False

    try:
        order = Order.objects.select_related('master').get(pk=order_id)
    except Order.DoesNotExist:
        return False

    if not master_still_needs_new_order_reminder(order=order, master_id=master_id):
        return False

    from apps.order.services.notifications import notify_master_new_order_reminder

    notify_master_new_order_reminder(order, target_master_id=master_id, attempt=attempt)

    next_attempt = attempt + 1
    interval = reminder_interval_seconds_for_order(order)
    if next_attempt <= reminder_max_count() and master_still_needs_new_order_reminder(
        order=order, master_id=master_id
    ):
        if order.master_response_deadline:
            remaining = (order.master_response_deadline - timezone.now()).total_seconds()
            if remaining <= interval:
                return True
        schedule_master_new_order_reminder(
            order_id,
            master_id,
            attempt=next_attempt,
            order_type=str(order.order_type),
            countdown=interval,
        )
    return True
