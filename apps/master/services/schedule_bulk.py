"""Busy-slot rows mirrored from POST /api/master/.../schedule/ bulk payload."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from apps.master.models import MasterBusySlot
from apps.master.services.slots import break_window_times

# Rows created/updated by MasterScheduleListBulkView (idempotent per master+date).
SCHEDULE_BULK_BUSY_REASON = 'schedule_bulk'


def is_schedule_bulk_calendar_mirror_row(slot) -> bool:
    """
    True for bulk-schedule mirror rows: they define the day on the calendar but must not count as
    unavailable time in slot math or standard-order booking (same semantics as docs for reason).
    """
    if getattr(slot, 'order_id', None):
        return False
    reason = (getattr(slot, 'reason', None) or '').strip()
    return reason == SCHEDULE_BULK_BUSY_REASON


def upsert_schedule_bulk_busy_slots(
    master,
    days: list[dict],
    *,
    rest_start,
    rest_hours: Decimal | None,
) -> None:
    """
    One manual ``MasterBusySlot`` per date with ``reason=SCHEDULE_BULK_BUSY_REASON``:
    ``start_time``/``end_time`` = working window; optional ``start_time_rest`` /
    ``time_range_rest`` shared across days (same as busy-slots API semantics).
    """
    for day in days:
        d = day['date']
        st = day['start_time']
        et = day['end_time']
        qs = MasterBusySlot.objects.filter(
            master=master,
            date=d,
            reason=SCHEDULE_BULK_BUSY_REASON,
            order_id__isnull=True,
        ).order_by('id')
        row = qs.first()
        if qs.count() > 1:
            qs.exclude(pk=row.pk).delete()

        rest_s = rest_start
        rest_h = rest_hours
        if row:
            row.start_time = st
            row.end_time = et
            row.start_time_rest = rest_s
            row.time_range_rest = rest_h
            row.order = None
            row.save()
        else:
            MasterBusySlot.objects.create(
                master=master,
                date=d,
                start_time=st,
                end_time=et,
                start_time_rest=rest_s,
                time_range_rest=rest_h,
                order=None,
                reason=SCHEDULE_BULK_BUSY_REASON,
            )


def rest_interval_outside_work(
    work_date,
    work_start,
    work_end,
    rest_start,
    rest_hours: Decimal,
) -> bool:
    """True if rest [r0, r1) is not fully inside [work_start, work_end] on that date."""
    r0, r1 = break_window_times(work_date, rest_start, rest_hours)
    w0 = datetime.combine(work_date, work_start)
    w1 = datetime.combine(work_date, work_end)
    if r0 < w0 or r1 > w1:
        return True
    return False
