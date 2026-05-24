"""Client MVP timers: SOS no-departure, scheduled start reminders, SOS communication reminders."""
from __future__ import annotations

from datetime import datetime, timedelta

from django.conf import settings
from django.utils import timezone

from apps.order.models import OrderStatus, OrderType
from apps.order.services.order_scheduled_start import order_has_scheduled_start, order_scheduled_start_datetime


def _sos_no_departure_warning_minutes() -> int:
    return int(getattr(settings, 'SOS_NO_DEPARTURE_WARNING_MINUTES', 4))


def _sos_no_departure_action_minutes() -> int:
    return int(getattr(settings, 'SOS_NO_DEPARTURE_ACTION_MINUTES', 5))


def _sos_on_the_way_reminder_minutes() -> int:
    return int(getattr(settings, 'SOS_ON_THE_WAY_REMINDER_MINUTES', 10))


def _scheduled_reminder_before_minutes() -> int:
    return int(getattr(settings, 'SCHEDULED_REMINDER_BEFORE_START_MINUTES', 60))


def _scheduled_no_start_warning_minutes() -> int:
    return int(getattr(settings, 'SCHEDULED_NO_START_WARNING_MINUTES', 20))


def _scheduled_no_start_cancel_minutes() -> int:
    return int(getattr(settings, 'SCHEDULED_NO_START_CANCEL_MINUTES', 30))


def _master_no_departure_minutes() -> int:
    return int(getattr(settings, 'MASTER_NO_DEPARTURE_MINUTES', 30))


def schedule_post_accept_timers(*, order_id: int, order_type: str, accepted_at: datetime) -> None:
    """Schedule Celery ETA tasks after master accepts an order."""
    if order_type == OrderType.SOS:
        _schedule_sos_no_departure_timers(order_id, accepted_at)
        return

    if order_type == OrderType.STANDARD:
        try:
            from apps.order.models import Order

            order = Order.objects.only(
                'id', 'order_type', 'preferred_date', 'preferred_time_start'
            ).get(pk=order_id)
        except Exception:  # noqa: BLE001
            order = None
        if order and order_has_scheduled_start(order):
            _schedule_standard_scheduled_timers(order_id, order)
            _schedule_standard_accept_no_on_the_way_notify(order_id, accepted_at)
            return
        _schedule_standard_no_departure_timer(order_id, accepted_at)


def _schedule_sos_no_departure_timers(order_id: int, accepted_at: datetime) -> None:
    warn_min = _sos_no_departure_warning_minutes()
    action_min = _sos_no_departure_action_minutes()
    try:
        from apps.order.tasks import (
            master_no_departure_action_task,
            sos_no_departure_warning_task,
        )

        if warn_min > 0 and warn_min < action_min:
            sos_no_departure_warning_task.apply_async(
                args=[order_id],
                eta=accepted_at + timedelta(minutes=warn_min),
            )
        master_no_departure_action_task.apply_async(
            args=[order_id],
            eta=accepted_at + timedelta(minutes=action_min),
        )
    except Exception:  # noqa: BLE001
        pass


def _schedule_standard_no_departure_timer(order_id: int, accepted_at: datetime) -> None:
    minutes = _master_no_departure_minutes()
    if minutes <= 0:
        return
    try:
        from apps.order.tasks import master_no_departure_action_task

        master_no_departure_action_task.apply_async(
            args=[order_id],
            eta=accepted_at + timedelta(minutes=minutes),
        )
    except Exception:  # noqa: BLE001
        pass


def _schedule_standard_accept_no_on_the_way_notify(order_id: int, accepted_at: datetime) -> None:
    """Scheduled standard: push at accept+N if still not on the way (order is not cancelled here)."""
    minutes = _master_no_departure_minutes()
    if minutes <= 0:
        return
    try:
        from apps.order.tasks import standard_accept_no_on_the_way_task

        standard_accept_no_on_the_way_task.apply_async(
            args=[order_id],
            eta=accepted_at + timedelta(minutes=minutes),
        )
    except Exception:  # noqa: BLE001
        pass


def _schedule_standard_scheduled_timers(order_id: int, order) -> None:
    start = order_scheduled_start_datetime(order)
    if not start:
        return
    now = timezone.now()
    try:
        from apps.order.tasks import (
            scheduled_no_start_cancel_task,
            scheduled_no_start_warning_task,
            scheduled_reminder_before_start_task,
        )

        reminder_at = start - timedelta(minutes=_scheduled_reminder_before_minutes())
        if reminder_at > now:
            scheduled_reminder_before_start_task.apply_async(args=[order_id], eta=reminder_at)

        warn_at = start + timedelta(minutes=_scheduled_no_start_warning_minutes())
        if warn_at > now:
            scheduled_no_start_warning_task.apply_async(args=[order_id], eta=warn_at)

        cancel_at = start + timedelta(minutes=_scheduled_no_start_cancel_minutes())
        if cancel_at > now:
            scheduled_no_start_cancel_task.apply_async(args=[order_id], eta=cancel_at)
    except Exception:  # noqa: BLE001
        pass


def schedule_sos_communication_reminder(*, order_id: int, from_dt: datetime | None = None) -> None:
    """Every N minutes while SOS order is active after on_the_way (MVP: no GPS tracking)."""
    minutes = _sos_on_the_way_reminder_minutes()
    if minutes <= 0:
        return
    base = from_dt or timezone.now()
    try:
        from apps.order.tasks import sos_on_the_way_communication_reminder_task

        sos_on_the_way_communication_reminder_task.apply_async(
            args=[order_id],
            eta=base + timedelta(minutes=minutes),
        )
    except Exception:  # noqa: BLE001
        pass


def no_departure_cutoff_minutes_for_order(order) -> int | None:
    """Minutes after accept before no-departure action; None if not applicable."""
    if order.order_type == OrderType.SOS:
        return _sos_no_departure_action_minutes()
    if order.order_type == OrderType.STANDARD and order_has_scheduled_start(order):
        return None
    if order.order_type in (OrderType.STANDARD, OrderType.CUSTOM_REQUEST):
        return _master_no_departure_minutes()
    return None
