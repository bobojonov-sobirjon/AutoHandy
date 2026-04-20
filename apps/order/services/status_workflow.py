"""Strict order status transitions (TZ workflow) and cancel rules."""
from __future__ import annotations

import math
from datetime import date as date_type
from datetime import datetime, timedelta

from django.conf import settings
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from apps.master.services.geo import haversine_distance_km, km_to_miles
from apps.master.models import Master, MasterScheduleDay
from apps.order.models import (
    MasterCancelReason,
    MasterOrderCancellation,
    Order,
    OrderStatus,
    OrderType,
)


def _client_cancellation_rules_dict() -> dict:
    """Static policy numbers (same on every order; for mobile UI copy)."""
    return {
        'grace_minutes_after_accept': int(
            getattr(settings, 'CLIENT_CANCEL_GRACE_MINUTES_AFTER_ACCEPT', 10)
        ),
        'percent_after_grace_while_accepted': int(
            getattr(settings, 'CLIENT_CANCEL_PENALTY_PERCENT_ACCEPTED_LATE', 10)
        ),
        'percent_on_the_way': int(getattr(settings, 'CLIENT_CANCEL_PENALTY_PERCENT_ON_THE_WAY', 15)),
        'percent_arrived': int(getattr(settings, 'CLIENT_CANCEL_PENALTY_PERCENT_ARRIVED', 25)),
        'no_fee_after_hours_on_the_way': int(
            getattr(settings, 'CLIENT_CANCEL_NO_PENALTY_AFTER_ON_THE_WAY_HOURS', 2)
        ),
        'in_progress_cancellable': False,
    }


def client_cancellation_snapshot(order: Order, *, now: datetime | None = None) -> dict:
    """
    Per-order state for the client cancellation policy (also exposed on OrderSerializer as ``cancellation``).

    Rules (configurable via settings / env):
    - pending: cancel allowed, no fee
    - accepted: no fee until grace minutes after ``accepted_at``; then percent_after_grace_while_accepted
    - on_the_way: percent_on_the_way unless penalty-free flag or N hours on the way elapsed
    - arrived: percent_arrived
    - in_progress: cancel not allowed
    - completed / cancelled / rejected: cancel not allowed
    """
    now = timezone.now() if now is None else now
    rules = _client_cancellation_rules_dict()
    grace_min = rules['grace_minutes_after_accept']
    pct_late = rules['percent_after_grace_while_accepted']
    pct_otw = rules['percent_on_the_way']
    pct_arr = rules['percent_arrived']
    hours_free = rules['no_fee_after_hours_on_the_way']

    base = {
        'client_can_cancel': False,
        'penalty_applies': False,
        'penalty_percent': 0,
        'tier': 'unknown',
        'grace_ends_at': None,
        'seconds_remaining_in_grace': None,
        'summary': '',
        'rules': rules,
    }

    st = order.status

    if st in (OrderStatus.COMPLETED, OrderStatus.CANCELLED, OrderStatus.REJECTED):
        base.update(
            tier='terminal',
            summary='This order is already closed.',
        )
        return base

    if st == OrderStatus.IN_PROGRESS:
        base.update(
            tier='in_progress_blocked',
            summary='Cancellation is not allowed while work is in progress.',
        )
        return base

    if st == OrderStatus.PENDING:
        base.update(
            client_can_cancel=True,
            penalty_applies=False,
            penalty_percent=0,
            tier='pending',
            summary='You can cancel with no fee.',
        )
        return base

    if st == OrderStatus.ACCEPTED:
        if not order.accepted_at:
            base.update(
                client_can_cancel=True,
                penalty_applies=True,
                penalty_percent=pct_late,
                tier='accepted_late',
                summary=f'Cancellation fee: {pct_late}% (accept timestamp missing; late tier applied).',
            )
            return base
        grace_end = order.accepted_at + timedelta(minutes=grace_min)
        if now <= grace_end:
            secs = max(0, int((grace_end - now).total_seconds()))
            base.update(
                client_can_cancel=True,
                penalty_applies=False,
                penalty_percent=0,
                tier='accepted_grace',
                grace_ends_at=grace_end.isoformat(),
                seconds_remaining_in_grace=secs,
                summary=f'No fee if you cancel within {grace_min} minutes of acceptance.',
            )
            return base
        base.update(
            client_can_cancel=True,
            penalty_applies=True,
            penalty_percent=pct_late,
            tier='accepted_late',
            summary=f'Cancellation fee: {pct_late}% of the order.',
        )
        return base

    if st == OrderStatus.ON_THE_WAY:
        if order.client_penalty_free_cancel_unlocked:
            base.update(
                client_can_cancel=True,
                penalty_applies=False,
                penalty_percent=0,
                tier='on_the_way_penalty_free',
                summary='No cancellation fee (penalty-free window is unlocked).',
            )
            return base
        if order.on_the_way_at and now >= order.on_the_way_at + timedelta(hours=hours_free):
            base.update(
                client_can_cancel=True,
                penalty_applies=False,
                penalty_percent=0,
                tier='on_the_way_penalty_free',
                summary=f'No fee after {hours_free} hour(s) on the way.',
            )
            return base
        base.update(
            client_can_cancel=True,
            penalty_applies=True,
            penalty_percent=pct_otw,
            tier='on_the_way',
            summary=f'Cancellation fee: {pct_otw}% while the master is on the way.',
        )
        return base

    if st == OrderStatus.ARRIVED:
        base.update(
            client_can_cancel=True,
            penalty_applies=True,
            penalty_percent=pct_arr,
            tier='arrived',
            summary=f'Cancellation fee: {pct_arr}% (master has arrived).',
        )
        return base

    base['summary'] = 'Unknown order state for cancellation.'
    return base


def client_cancel_has_penalty(order: Order) -> bool:
    """True if a client cancel (when allowed) should be treated as penalized for billing."""
    snap = client_cancellation_snapshot(order)
    return bool(snap['client_can_cancel'] and snap['penalty_applies'])


def master_cancellations_this_month(master: Master) -> int:
    now = timezone.now()
    start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    return MasterOrderCancellation.objects.filter(master=master, created_at__gte=start).count()


def master_schedule_forward_horizon_days(master: Master) -> int | None:
    """
    After N master-initiated cancellations (accepted order → cancel) in the calendar month,
    cap how far ahead schedule/busy dates may be (see MASTER_FREE_CANCELLATIONS_PER_MONTH):
      n <= free — no cap
      n == free + 1 — up to 10 calendar days from today
      n == free + 2 — up to 5 days
      n >= free + 3 — only today
    """
    n = master_cancellations_this_month(master)
    free = int(getattr(settings, 'MASTER_FREE_CANCELLATIONS_PER_MONTH', 3))
    if n <= free:
        return None
    if n == free + 1:
        return 10
    if n == free + 2:
        return 5
    return 0


def master_schedule_max_date(master: Master) -> date_type | None:
    """Last calendar date the master may set in schedule when capped; None = no policy cap."""
    h = master_schedule_forward_horizon_days(master)
    if h is None:
        return None
    return timezone.localdate() + timedelta(days=h)


def master_schedule_coverage_span_days(master: Master) -> int:
    """Consecutive days from today that POST /schedule/ bulk must fully cover after save."""
    h = master_schedule_forward_horizon_days(master)
    if h is None:
        return int(getattr(settings, 'MASTER_SCHEDULE_MIN_COVERAGE_DAYS_DEFAULT', 14))
    return h + 1


def master_schedule_missing_coverage_dates(master: Master) -> list[date_type]:
    """Dates in the required coverage window that have no MasterScheduleDay row."""
    span = master_schedule_coverage_span_days(master)
    today = timezone.localdate()
    end = today + timedelta(days=span - 1)
    required = {today + timedelta(days=i) for i in range(span)}
    have = set(
        MasterScheduleDay.objects.filter(
            master=master,
            date__gte=today,
            date__lte=end,
        ).values_list('date', flat=True)
    )
    return sorted(required - have)


def validate_master_schedule_day_date(master: Master, d: date_type) -> tuple[bool, str]:
    """Reject past dates and dates beyond cancellation-policy horizon (schedule / slots / busy)."""
    today = timezone.localdate()
    if d < today:
        return False, 'Date cannot be in the past.'
    max_d = master_schedule_max_date(master)
    if max_d is not None and d > max_d:
        n = master_cancellations_this_month(master)
        return (
            False,
            f'Due to order cancellations this month ({n}), dates may not be later than {max_d.isoformat()}.',
        )
    return True, ''


def validate_master_cancel(order: Order, master: Master, reason: str | None) -> tuple[bool, str]:
    """
    Master cancel after accept: valid reason required; too_far is never allowed.
    Monthly cancellation count does not block cancel — it tightens schedule limits elsewhere.
    """
    if not reason:
        return False, 'Provide cancel_reason (cancellation reason).'
    if reason == 'too_far':
        return False, 'The "too_far" cancellation reason is not allowed.'
    valid = {c[0] for c in MasterCancelReason.choices}
    if reason not in valid:
        return False, f'Invalid reason. Allowed: {", ".join(sorted(valid))}.'
    return True, ''


def resolve_master_coordinates_for_start_job(
    master: Master,
    request_data: dict,
) -> tuple[float | None, float | None, str | None]:
    """
    GPS for arrived → in_progress distance check.
    If both latitude/longitude are in the body, use them; otherwise Master profile, then user profile.
    Returns (lat, lon, None) on success, or (None, None, error_key) for HTTP 400 messages in the view.
    """
    lat_raw = request_data.get('latitude')
    lon_raw = request_data.get('longitude')

    def _missing(v) -> bool:
        return v is None or v == ''

    has_lat = not _missing(lat_raw)
    has_lon = not _missing(lon_raw)
    if has_lat != has_lon:
        return None, None, 'partial_coords'

    if has_lat and has_lon:
        try:
            return float(lat_raw), float(lon_raw), None
        except (TypeError, ValueError):
            return None, None, 'invalid_coords'

    wlat, wlon = master.get_work_location_for_distance()
    if wlat is not None and wlon is not None:
        return wlat, wlon, None

    u = master.user
    if u.latitude is not None and u.longitude is not None:
        return float(u.latitude), float(u.longitude), None

    return None, None, 'no_master_coords'


def resolve_on_the_way_eta(
    request_data: dict,
    on_the_way_at: datetime,
) -> tuple[datetime | None, int | None, str | None]:
    """
    Optional body: estimated_arrival_at (ISO datetime) and/or eta_minutes (int).
    If both are omitted, returns (None, None, None).
    If both given, estimated_arrival_at wins; eta_minutes is derived from the delta when possible.
    """
    max_minutes = int(getattr(settings, 'ORDER_ETA_MAX_MINUTES', 72 * 60))
    max_delta = timedelta(minutes=max_minutes)

    raw_est = request_data.get('estimated_arrival_at')
    raw_min = request_data.get('eta_minutes')

    def _empty(v) -> bool:
        return v is None or v == ''

    if not _empty(raw_est):
        if isinstance(raw_est, datetime):
            est = raw_est
        else:
            est = parse_datetime(str(raw_est))
        if est is None:
            return None, None, 'invalid_estimated_arrival_at'
        if timezone.is_naive(est):
            est = timezone.make_aware(est, timezone.get_current_timezone())
        if est < on_the_way_at:
            return None, None, 'estimated_arrival_in_past'
        if est - on_the_way_at > max_delta:
            return None, None, 'estimated_arrival_too_far'
        delta_min = max(1, int(round((est - on_the_way_at).total_seconds() / 60)))
        return est, delta_min, None

    if not _empty(raw_min):
        try:
            m = int(raw_min)
        except (TypeError, ValueError):
            return None, None, 'invalid_eta_minutes'
        if m < 1 or m > max_minutes:
            return None, None, 'invalid_eta_minutes'
        est = on_the_way_at + timedelta(minutes=m)
        return est, m, None

    return None, None, None


def order_master_distance_mi(order: Order) -> float | None:
    """Straight-line miles from master’s saved location to order client coordinates."""
    if order.latitude is None or order.longitude is None or not order.master_id:
        return None
    mlat, mlon, _err = resolve_master_coordinates_for_start_job(order.master, {})
    if mlat is None or mlon is None:
        return None
    olat = float(order.latitude)
    olon = float(order.longitude)
    km = haversine_distance_km(mlat, mlon, olat, olon)
    return round(km_to_miles(km), 3)


def auto_eta_from_order_master(order: Order, master: Master, on_the_way_at: datetime) -> tuple[datetime | None, int | None]:
    """
    ETA from order (A) and master (B) coordinates: time = distance_km / ORDER_ETA_ASSUMED_SPEED_KMH.
    Returns (None, None) if coordinates missing.
    """
    if order.latitude is None or order.longitude is None:
        return None, None
    mlat, mlon, _err = resolve_master_coordinates_for_start_job(master, {})
    if mlat is None or mlon is None:
        return None, None

    olat = float(order.latitude)
    olon = float(order.longitude)
    dist_km = haversine_distance_km(mlat, mlon, olat, olon)

    speed = float(getattr(settings, 'ORDER_ETA_ASSUMED_SPEED_KMH', 35) or 35)
    if speed <= 0:
        speed = 35.0

    minutes = max(1, int(math.ceil((dist_km / speed) * 60.0)))
    max_minutes = int(getattr(settings, 'ORDER_ETA_MAX_MINUTES', 72 * 60))
    minutes = min(minutes, max_minutes)
    est = on_the_way_at + timedelta(minutes=minutes)
    return est, minutes

