"""Scheduled (standard) order start datetime from preferred_date + preferred_time_start."""
from __future__ import annotations

from datetime import datetime

from django.conf import settings
from django.utils import timezone


def order_has_scheduled_start(order) -> bool:
    return bool(getattr(order, 'preferred_date', None) and getattr(order, 'preferred_time_start', None))


def order_scheduled_start_datetime(order) -> datetime | None:
    """
    Combine preferred_date and preferred_time_start in Django TIME_ZONE.
    Returns None when either field is missing.
    """
    pd = getattr(order, 'preferred_date', None)
    ps = getattr(order, 'preferred_time_start', None)
    if not pd or not ps:
        return None
    naive = datetime.combine(pd, ps)
    tz = timezone.get_current_timezone()
    if timezone.is_naive(naive):
        return timezone.make_aware(naive, tz)
    return naive.astimezone(tz)
