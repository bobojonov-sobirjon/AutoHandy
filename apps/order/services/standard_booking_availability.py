"""
Standard-order preferred slot checks: accepted orders + master rest (MasterBusySlot).
"""
from __future__ import annotations

from datetime import date, time
from decimal import Decimal

from apps.master.models import MasterBusySlot
from apps.master.services.slots import break_window_times
from apps.order.models import Order, OrderStatus, OrderType


def _closed_time_interval_contains(lo: time, hi: time, point: time) -> bool:
    """True if ``lo <= point <= hi`` (same calendar day, no overnight wrap)."""
    return lo <= point <= hi


def preferred_slot_blocked_message(
    *,
    master_id: int,
    preferred_date: date,
    preferred_time_start: time,
) -> str | None:
    """
    If the chosen instant is unavailable, return a short API message; else ``None``.

    - **Accepted orders** (same master, same date): blocked if ``preferred_time_start`` lies in
      ``[order.preferred_time_start, order.preferred_time_end]`` when both ends exist, or if it
      exactly equals another accepted order's start when that order has no end yet.
    - **Calendar blocks** (``MasterBusySlot`` with no ``order``): if ``start_time_rest`` and
      positive ``time_range_rest`` are set, only the **computed break** ``[rest_start, rest_end)``
      blocks booking (same as busy-slots / ``schedule_bulk`` full-day rows). Otherwise the whole
      ``start_time``–``end_time`` interval is a manual block.
    """
    accepted = Order.objects.filter(
        master_id=master_id,
        status=OrderStatus.ACCEPTED,
        order_type=OrderType.STANDARD,
        preferred_date=preferred_date,
    ).only('id', 'preferred_time_start', 'preferred_time_end')

    for o in accepted:
        ost = o.preferred_time_start
        if ost is None:
            continue
        oet = o.preferred_time_end
        if oet is not None:
            if _closed_time_interval_contains(ost, oet, preferred_time_start):
                return (
                    'This master is busy at this time: it overlaps another accepted order '
                    f'({ost.isoformat(timespec="seconds")}–{oet.isoformat(timespec="seconds")}).'
                )
        elif ost == preferred_time_start:
            return (
                'This master already has an accepted order at this exact start time '
                f'.'
            )

    busy_manual = MasterBusySlot.objects.filter(
        master_id=master_id,
        date=preferred_date,
        order__isnull=True,
    ).only('start_time', 'end_time', 'start_time_rest', 'time_range_rest', 'reason')

    pt = preferred_time_start.replace(microsecond=0)

    for slot in busy_manual:
        tr = slot.time_range_rest
        srs = slot.start_time_rest
        if srs is not None and tr is not None and tr > Decimal('0'):
            r0, r1 = break_window_times(preferred_date, srs, tr)
            lo = r0.time().replace(microsecond=0)
            hi = r1.time().replace(microsecond=0)
            if lo <= pt < hi:
                return (
                    'This time falls in the master’s scheduled break '
                    f'({lo.isoformat(timespec="seconds")}–{hi.isoformat(timespec="seconds")}).'
                )
            continue

        if _closed_time_interval_contains(slot.start_time, slot.end_time, preferred_time_start):
            note = (slot.reason or '').strip()
            suffix = f' ({note})' if note else ''
            return (
                'This time is blocked on the master’s calendar '
                f'({slot.start_time.isoformat(timespec="seconds")}–'
                f'{slot.end_time.isoformat(timespec="seconds")}){suffix}.'
            )

    return None
