"""Hourly slot generation for master schedule + optional rest window."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from decimal import Decimal
from types import SimpleNamespace


def _combine(d: date, t: time) -> datetime:
    return datetime.combine(d, t)


def break_window_times(
    check_date: date,
    rest_start: time,
    rest_hours: Decimal,
) -> tuple[datetime, datetime]:
    """Rest interval [start, end) on check_date. rest_hours may be fractional."""
    start_dt = _combine(check_date, rest_start)
    minutes = int(round(float(rest_hours) * 60))
    if minutes <= 0:
        return start_dt, start_dt
    end_dt = start_dt + timedelta(minutes=minutes)
    return start_dt, end_dt


def break_data_dict(
    check_date: date,
    rest_start: time | None,
    rest_hours: Decimal | None,
) -> dict | None:
    if rest_start is None or rest_hours is None:
        return None
    if rest_hours <= 0:
        return None
    b0, b1 = break_window_times(check_date, rest_start, rest_hours)
    return {
        'start_time_rest': rest_start.strftime('%H:%M'),
        'end_time_rest': b1.time().strftime('%H:%M'),
        'time_range_rest': str(rest_hours),
    }


def _fmt_time_label(t: time) -> str:
    """API always uses HH:MM (no seconds)."""
    return t.replace(second=0, microsecond=0).strftime('%H:%M')


def _slot_interval_worth_row(lo: datetime, hi: datetime, start_label: str, end_label: str) -> bool:
    """Drop zero-width or same HH:MM labels (sub-minute noise near rest boundaries)."""
    if lo >= hi:
        return False
    if start_label == end_label:
        return False
    return True


def _busy_half_open(check_date: date, start_t: time, end_t: time) -> tuple[datetime, datetime] | None:
    """
    Busy interval for overlap math: [lo, hi) with minute-granularity inclusive end
    (``end_t`` is the last booked minute shown to the client).
    """
    lo = _combine(check_date, start_t)
    hi = _combine(check_date, end_t) + timedelta(minutes=1)
    if hi <= lo:
        return None
    return lo, hi


def _work_segments_half_open(
    check_date: date,
    work_start: time,
    work_end: time,
    rest_start: time | None,
    rest_hours: Decimal | None,
) -> list[tuple[datetime, datetime]]:
    """Working time on ``check_date`` minus rest, as half-open [lo, hi). ``hi`` is ``work_end``."""
    ws = _combine(check_date, work_start)
    we = _combine(check_date, work_end)
    if ws >= we:
        return []
    if rest_start is not None and rest_hours is not None and rest_hours > 0:
        r0, r1 = break_window_times(check_date, rest_start, rest_hours)
        if r0 < r1:
            out: list[tuple[datetime, datetime]] = []
            if ws < r0:
                seg_hi = min(we, r0)
                if ws < seg_hi:
                    out.append((ws, seg_hi))
            if we > r1:
                seg_lo = max(ws, r1)
                if seg_lo < we:
                    out.append((seg_lo, we))
            return out
    return [(ws, we)]


def _merge_half_open(
    intervals: list[tuple[datetime, datetime]],
) -> list[tuple[datetime, datetime]]:
    if not intervals:
        return []
    s = sorted(intervals, key=lambda x: (x[0], x[1]))
    out: list[list[datetime]] = [[s[0][0], s[0][1]]]
    for lo, hi in s[1:]:
        if lo <= out[-1][1]:
            out[-1][1] = max(out[-1][1], hi)
        else:
            out.append([lo, hi])
    return [(a[0], a[1]) for a in out]


def _subtract_half_open(
    seg_lo: datetime,
    seg_hi: datetime,
    busy_merged: list[tuple[datetime, datetime]],
) -> list[tuple[datetime, datetime]]:
    free: list[tuple[datetime, datetime]] = []
    cur = seg_lo
    for blo, bhi in busy_merged:
        if bhi <= cur:
            continue
        if blo >= seg_hi:
            break
        if cur < blo:
            free.append((cur, min(blo, seg_hi)))
        cur = max(cur, bhi)
        if cur >= seg_hi:
            break
    if cur < seg_hi:
        free.append((cur, seg_hi))
    return free


def _split_available_aligned(lo: datetime, hi: datetime) -> list[tuple[datetime, datetime]]:
    """Split [lo, hi) into rows: full hours on the clock, then leading/trailing partials."""
    out: list[tuple[datetime, datetime]] = []
    cur = lo
    while cur < hi:
        on_hour = cur.minute == 0 and cur.second == 0 and cur.microsecond == 0
        if on_hour:
            nxt = min(cur + timedelta(hours=1), hi)
        else:
            next_hour = cur.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
            nxt = min(next_hour, hi)
        out.append((cur, nxt))
        cur = nxt
    return out


def _build_precise_day_slots(
    *,
    check_date: date,
    work_start: time,
    work_end: time,
    rest_start: time | None,
    rest_hours: Decimal | None,
    busy_blocks: list,
) -> list[dict]:
    """
    Unavailable rows use **exact** busy ``start``/``end`` labels from blocks (merged if overlapping).
    Available rows fill the rest of work (minus rest) with hour-aligned chunks.
    """
    work_segs = _work_segments_half_open(
        check_date, work_start, work_end, rest_start, rest_hours
    )

    raw_busy: list[dict] = []
    for b in busy_blocks:
        iv = _busy_half_open(check_date, b.start_time, b.end_time)
        if iv is None:
            continue
        lo, hi = iv
        oid = getattr(b, 'order_id', None)
        raw_busy.append(
            {
                'lo': lo,
                'hi': hi,
                'st': b.start_time,
                'et': b.end_time,
                'oid': oid,
            }
        )

    raw_busy.sort(key=lambda x: (x['lo'], x['hi']))
    merged: list[dict] = []
    for item in raw_busy:
        if not merged:
            merged.append(
                {
                    'lo': item['lo'],
                    'hi': item['hi'],
                    'st': item['st'],
                    'et': item['et'],
                    'oids': {item['oid']} if item['oid'] is not None else set(),
                }
            )
            continue
        m = merged[-1]
        if item['lo'] <= m['hi']:
            m['hi'] = max(m['hi'], item['hi'])
            m['st'] = min(m['st'], item['st'])
            m['et'] = max(m['et'], item['et'])
            if item['oid'] is not None:
                m['oids'].add(item['oid'])
        else:
            merged.append(
                {
                    'lo': item['lo'],
                    'hi': item['hi'],
                    'st': item['st'],
                    'et': item['et'],
                    'oids': {item['oid']} if item['oid'] is not None else set(),
                }
            )

    merged_lohi = [(m['lo'], m['hi']) for m in merged]

    ws = _combine(check_date, work_start)
    we = _combine(check_date, work_end)
    busy_rows: list[dict] = []
    for m in merged:
        blo, bhi = m['lo'], m['hi']
        if bhi <= ws or blo >= we:
            continue
        if blo >= bhi:
            continue
        st_l = _fmt_time_label(m['st'])
        et_l = _fmt_time_label(m['et'])
        row: dict = {
            'start': st_l,
            'end': et_l,
            'available': False,
        }
        oids = m['oids']
        if len(oids) == 1:
            row['order_id'] = next(iter(oids))
        busy_rows.append(row)

    avail_rows: list[dict] = []
    for seg_lo, seg_hi in work_segs:
        clipped: list[tuple[datetime, datetime]] = []
        for blo, bhi in merged_lohi:
            lo = max(blo, seg_lo)
            hi = min(bhi, seg_hi)
            if lo < hi:
                clipped.append((lo, hi))
        clipped = _merge_half_open(clipped)
        for free_lo, free_hi in _subtract_half_open(seg_lo, seg_hi, clipped):
            for alo, ahi in _split_available_aligned(free_lo, free_hi):
                sa = _fmt_time_label(alo.time())
                ea = _fmt_time_label(ahi.time())
                if not _slot_interval_worth_row(alo, ahi, sa, ea):
                    continue
                avail_rows.append(
                    {
                        'start': sa,
                        'end': ea,
                        'available': True,
                    }
                )

    combined = busy_rows + avail_rows

    def _row_sort_key(row: dict) -> tuple:
        tstr = row['start']
        try:
            tt = datetime.strptime(tstr, '%H:%M').time()
        except ValueError:
            tt = datetime.strptime(tstr, '%H:%M:%S').time()
        return (tt, 1 if row['available'] else 0)

    combined.sort(key=_row_sort_key)
    return combined


def _synthetic_end_one_hour_capped(start: time, work_end: time) -> time:
    """When master has not set preferred_time_end yet: treat as busy for 1h, not past work_end."""
    anchor = date(2000, 1, 1)
    plus = (_combine(anchor, start) + timedelta(hours=1)).time()
    return plus if plus <= work_end else work_end


def _accepted_standard_order_busy_blocks(
    master_id: int, check_date: date, work_end: time
) -> list[SimpleNamespace]:
    """
    Busy intervals from accepted standard orders on this date (preferred_date match).

    Uses ``preferred_time_end`` when set; otherwise a **provisional** end of
    min(start + 1 hour, work_end) so slots update right after accept (before PATCH).
    """
    from apps.order.models import Order, OrderStatus, OrderType

    qs = (
        Order.objects.filter(
            master_id=master_id,
            status=OrderStatus.ACCEPTED,
            order_type=OrderType.STANDARD,
            preferred_date=check_date,
        )
        .exclude(preferred_time_start__isnull=True)
        .only('id', 'preferred_time_start', 'preferred_time_end')
    )
    blocks: list[SimpleNamespace] = []
    for o in qs:
        st = o.preferred_time_start
        et = o.preferred_time_end
        if et is None:
            et = _synthetic_end_one_hour_capped(st, work_end)
        if et <= st:
            continue
        blocks.append(
            SimpleNamespace(
                start_time=st,
                end_time=et,
                order_id=o.id,
            )
        )
    return blocks


def build_master_day_slots_payload(
    master,
    check_date: date,
    *,
    busy_date_only: bool = False,
) -> tuple[dict | None, str | None]:
    """
    One-day calendar: working_hours, break_data, slots with availability.
    Same structure as GET /api/order/available-slots/ and GET master busy-slots?date=.

    If the master has a **manual** busy row on that date with ``start_time_rest`` and
    ``time_range_rest``, the day's **working window** (``working_hours``) is taken from that row's
    ``start_time`` / ``end_time`` instead of ``MasterScheduleDay`` / ``working_time``.

    **Unavailable** rows show **exact** busy bounds (accepted standard orders + manual busy slots),
    overlapping orders merged. **Available** rows fill remaining work time (minus rest) with
    hour-aligned free intervals.

    ``busy_date_only=True`` (nearby-masters date filter): **no** ``MasterScheduleDay`` / ``working_time``.
    Work window = min–max ``start_time``/``end_time`` over **all** ``MasterBusySlot`` rows for that date
    (unless the rest row above applies first). If there are no rows, caller should not invoke this mode.
    """
    from apps.master.models import MasterBusySlot, MasterScheduleDay
    from apps.order.services.status_workflow import validate_master_schedule_day_date

    ok, err_msg = validate_master_schedule_day_date(master, check_date)
    if not ok:
        return None, err_msg

    busy_all = list(MasterBusySlot.objects.filter(master=master, date=check_date))
    rest_slot = (
        MasterBusySlot.objects.filter(
            master=master,
            date=check_date,
            order__isnull=True,
        )
        .exclude(start_time_rest__isnull=True)
        .exclude(time_range_rest__isnull=True)
        .order_by('start_time')
        .first()
    )

    if rest_slot:
        work_start = rest_slot.start_time
        work_end = rest_slot.end_time
        schedule_source = 'master_busy_slot'
        working_hours_display = (
            f'{work_start.strftime("%H:%M")}-{work_end.strftime("%H:%M")}'
        )
    else:
        if busy_date_only:
            if not busy_all:
                return None, 'No busy slots for this date.'
            work_start = min(b.start_time for b in busy_all)
            work_end = max(b.end_time for b in busy_all)
            schedule_source = 'master_busy_slot_span'
            working_hours_display = (
                f'{work_start.strftime("%H:%M")}-{work_end.strftime("%H:%M")}'
            )
        else:
            day_row = MasterScheduleDay.objects.filter(master=master, date=check_date).first()
            schedule_source = 'master_schedule_day' if day_row else 'working_time_fallback'
            if day_row:
                work_start = day_row.start_time
                work_end = day_row.end_time
                working_hours_display = (
                    f'{day_row.start_time.strftime("%H:%M")}-{day_row.end_time.strftime("%H:%M")}'
                )
            else:
                working_time = master.working_time or '09:00-18:00'
                working_hours_display = working_time
                try:
                    start_time_str, end_time_str = working_time.split('-')
                    sh, sm = map(int, start_time_str.strip().split(':'))
                    eh, em = map(int, end_time_str.strip().split(':'))
                    work_start = time(sh, sm)
                    work_end = time(eh, em)
                except Exception:
                    work_start = time(9, 0)
                    work_end = time(18, 0)
    rest_start = rest_slot.start_time_rest if rest_slot else None
    rest_hours = rest_slot.time_range_rest if rest_slot else None
    busy_for_overlap = [b for b in busy_all if rest_slot is None or b.pk != rest_slot.pk]
    busy_for_overlap.extend(
        _accepted_standard_order_busy_blocks(master.id, check_date, work_end)
    )

    slots = _build_precise_day_slots(
        check_date=check_date,
        work_start=work_start,
        work_end=work_end,
        rest_start=rest_start,
        rest_hours=rest_hours,
        busy_blocks=busy_for_overlap,
    )
    break_data = break_data_dict(check_date, rest_start, rest_hours)

    return (
        {
            'date': check_date.isoformat(),
            'master_id': master.id,
            'master_name': master.user.get_full_name() or master.user.phone_number,
            'working_hours': working_hours_display,
            'schedule_source': schedule_source,
            'break_data': break_data,
            'slots': slots,
        },
        None,
    )


def parse_nearby_schedule_date(raw: str) -> date:
    return datetime.strptime(raw.strip(), '%Y-%m-%d').date()


def parse_nearby_schedule_time(raw: str) -> time:
    s = raw.strip()
    if s.endswith('Z') or s.endswith('z'):
        s = s[:-1]
    for fmt in ('%H:%M:%S.%f', '%H:%M:%S', '%H:%M'):
        try:
            return datetime.strptime(s, fmt).time().replace(microsecond=0)
        except ValueError:
            continue
    raise ValueError('invalid time')


def _parse_slot_boundary_label(label: str) -> time:
    s = label.strip()
    for fmt in ('%H:%M:%S', '%H:%M'):
        try:
            return datetime.strptime(s, fmt).time().replace(microsecond=0)
        except ValueError:
            continue
    raise ValueError(label)


def master_has_busy_slot_on_date(master, check_date: date) -> bool:
    """True if there is at least one ``MasterBusySlot`` row for this master on ``check_date``."""
    from apps.master.models import MasterBusySlot

    return MasterBusySlot.objects.filter(master=master, date=check_date).exists()


def master_has_free_slot_at(master, check_date: date, at_time: time | None) -> bool:
    """
    Nearby / list ``date``+``time`` filter: uses **only** ``MasterBusySlot`` rows on ``check_date``
    (plus accepted standard orders merged the same way as busy-slots). No ``MasterScheduleDay`` /
    ``working_time`` for the work window — span is min–max of that day's busy slots (or rest row).

    - ``at_time`` is None: keep master if there is at least one ``available: true`` row.
    - ``at_time`` set: keep only if that instant falls in ``[start, end)`` of an available row.
    """
    if not master_has_busy_slot_on_date(master, check_date):
        return False
    payload, err = build_master_day_slots_payload(master, check_date, busy_date_only=True)
    if err or payload is None:
        return False
    slots_list = payload.get('slots') or []
    if at_time is None:
        return any(bool(s.get('available')) for s in slots_list)
    point = _combine(check_date, at_time.replace(microsecond=0))
    for s in slots_list:
        if not s.get('available'):
            continue
        try:
            st_t = _parse_slot_boundary_label(s['start'])
            et_t = _parse_slot_boundary_label(s['end'])
        except (KeyError, ValueError):
            continue
        lo = _combine(check_date, st_t)
        hi = _combine(check_date, et_t)
        if lo <= point < hi:
            return True
    return False


def filter_masters_by_schedule_availability(
    masters: list,
    check_date: date,
    at_time: time | None,
) -> list:
    """Filter an in-memory master list (e.g. after geo) by one-day schedule."""
    if not masters:
        return masters
    return [m for m in masters if master_has_free_slot_at(m, check_date, at_time)]
