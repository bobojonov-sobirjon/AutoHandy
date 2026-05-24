"""Scheduled (standard) order start datetime from preferred_date + preferred_time_start."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from django.conf import settings
from django.utils import timezone


def scheduled_order_timezone() -> ZoneInfo:
    """
    Timezone for interpreting preferred_date + preferred_time_start.

    Clients send local calendar date/time without offset; combine them in the
    service region (not Django TIME_ZONE / UTC) so scheduled MVP timers match the app UI.
    """
    tz_name = getattr(settings, 'SCHEDULED_ORDER_TIMEZONE', None) or getattr(
        settings, 'TIME_ZONE', 'UTC'
    )
    return ZoneInfo(str(tz_name))


def order_has_scheduled_start(order) -> bool:
    return bool(getattr(order, 'preferred_date', None) and getattr(order, 'preferred_time_start', None))


def scheduled_start_datetime_from_fields(
    preferred_date: date | None,
    preferred_time_start: time | None,
) -> datetime | None:
    """Combine date + time in SCHEDULED_ORDER_TIMEZONE. Returns None if either field is missing."""
    if not preferred_date or not preferred_time_start:
        return None
    naive = datetime.combine(preferred_date, preferred_time_start)
    return naive.replace(tzinfo=scheduled_order_timezone())


def order_scheduled_start_datetime(order) -> datetime | None:
    """Combine preferred_date and preferred_time_start in the scheduled service timezone."""
    return scheduled_start_datetime_from_fields(
        getattr(order, 'preferred_date', None),
        getattr(order, 'preferred_time_start', None),
    )


def scheduled_no_start_cancel_deadline(
    *,
    order=None,
    preferred_date: date | None = None,
    preferred_time_start: time | None = None,
    now: datetime | None = None,
) -> datetime | None:
    """When auto-cancel fires if work has not started (start + SCHEDULED_NO_START_CANCEL_MINUTES)."""
    if order is not None:
        start = order_scheduled_start_datetime(order)
    else:
        start = scheduled_start_datetime_from_fields(preferred_date, preferred_time_start)
    if not start:
        return None
    cancel_after = int(getattr(settings, 'SCHEDULED_NO_START_CANCEL_MINUTES', 30))
    return start + timedelta(minutes=cancel_after)


def scheduled_slot_past_cancel_deadline(
    *,
    order=None,
    preferred_date: date | None = None,
    preferred_time_start: time | None = None,
    now: datetime | None = None,
) -> bool:
    """True when the scheduled no-start auto-cancel window has already passed."""
    deadline = scheduled_no_start_cancel_deadline(
        order=order,
        preferred_date=preferred_date,
        preferred_time_start=preferred_time_start,
    )
    if deadline is None:
        return False
    now = now or timezone.now()
    return now >= deadline


def scheduled_slot_is_in_future(
    *,
    preferred_date: date,
    preferred_time_start: time,
    now: datetime | None = None,
    grace_minutes: int | None = None,
) -> bool:
    """True if the slot start is still in the future (small grace for clock skew)."""
    start = scheduled_start_datetime_from_fields(preferred_date, preferred_time_start)
    if not start:
        return False
    now = now or timezone.now()
    grace = grace_minutes
    if grace is None:
        grace = int(getattr(settings, 'SCHEDULED_CREATE_PAST_GRACE_MINUTES', 5))
    return start > now - timedelta(minutes=max(0, grace))
