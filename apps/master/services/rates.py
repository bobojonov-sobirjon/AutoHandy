"""Master operational metrics: acceptance/completion rates (percent)."""

from __future__ import annotations

from datetime import timedelta

from django.conf import settings
from django.utils import timezone


def _window_start(days_default: int) -> object:
    days = int(getattr(settings, 'MASTER_RATE_WINDOW_DAYS', days_default))
    return timezone.now() - timedelta(days=max(1, days))


def master_acceptance_rate_percent(master) -> int:
    """
    Acceptance rate (%) from MasterOfferEvent:
      accepted / (accepted + declined) * 100

    Expired offers do not affect the rate (client MVP: only explicit decline lowers it).
    """
    from apps.order.models import MasterOfferEvent, MasterOfferEventStatus

    start = _window_start(30)
    qs = MasterOfferEvent.objects.filter(master=master, offered_at__gte=start)
    denom = qs.filter(
        status__in=(
            MasterOfferEventStatus.ACCEPTED,
            MasterOfferEventStatus.DECLINED,
        )
    ).count()
    if denom <= 0:
        return 0
    num = qs.filter(status=MasterOfferEventStatus.ACCEPTED).count()
    return int(round(num / denom * 100))


def _safe_assignment_failure_count(*, master_ids: list[int], completed_order_ids) -> int:
    try:
        from apps.order.models import MasterAssignmentFailure

        return (
            MasterAssignmentFailure.objects.filter(master_id__in=master_ids)
            .exclude(order_id__in=completed_order_ids)
            .count()
        )
    except Exception:  # noqa: BLE001 — table missing before migrate, etc.
        return 0


def _user_completion_triplet(user) -> tuple[int, int, int]:
    """(completed, cancelled, failures) — same completed scope as profile counter."""
    from apps.master.models import Master
    from apps.order.models import Order, OrderStatus

    completed = Order.objects.filter(
        master__user=user,
        status=OrderStatus.COMPLETED,
    ).count()
    if completed <= 0:
        return 0, 0, 0

    cancelled = Order.objects.filter(
        master__user=user,
        status=OrderStatus.CANCELLED,
    ).count()

    master_ids = list(Master.objects.filter(user=user).values_list('id', flat=True))
    completed_ids = Order.objects.filter(
        master__user=user,
        status=OrderStatus.COMPLETED,
    ).values_list('id', flat=True)
    failures = _safe_assignment_failure_count(
        master_ids=master_ids,
        completed_order_ids=completed_ids,
    )
    return completed, cancelled, failures


def _master_completion_triplet(master) -> tuple[int, int, int]:
    from apps.order.models import Order, OrderStatus

    completed = Order.objects.filter(
        master_id=master.id,
        status=OrderStatus.COMPLETED,
    ).count()
    if completed <= 0:
        cancelled_only = Order.objects.filter(
            master_id=master.id,
            status=OrderStatus.CANCELLED,
        ).count()
        failures_only = _safe_assignment_failure_count(
            master_ids=[master.id],
            completed_order_ids=[],
        )
        return 0, cancelled_only, failures_only

    cancelled = Order.objects.filter(
        master_id=master.id,
        status=OrderStatus.CANCELLED,
    ).count()
    completed_ids = Order.objects.filter(
        master_id=master.id,
        status=OrderStatus.COMPLETED,
    ).values_list('id', flat=True)
    failures = _safe_assignment_failure_count(
        master_ids=[master.id],
        completed_order_ids=completed_ids,
    )
    return completed, cancelled, failures


def _display_completion_rate_percent(*, completed: int, cancelled: int, failures: int) -> int:
    """
    Profile completion % (rises quickly with first successes, soft on auto-failures).

    Raw: completed / (completed + cancelled + failures)
    Display: Bayesian prior (~94% over virtual prior orders) + failures/cancels weighted < 1.
    """
    if completed <= 0:
        return 0

    prior_pct = int(getattr(settings, 'COMPLETION_RATE_BAYESIAN_PRIOR_PERCENT', 94))
    prior_n = int(getattr(settings, 'COMPLETION_RATE_BAYESIAN_PRIOR_ORDERS', 10))
    fail_w = float(getattr(settings, 'COMPLETION_RATE_FAILURE_WEIGHT', 0.3))
    cancel_w = float(getattr(settings, 'COMPLETION_RATE_CANCEL_WEIGHT', 1.0))

    prior_n = max(1, prior_n)
    prior_pct = max(0, min(100, prior_pct))
    prior_successes = prior_pct / 100.0 * prior_n

    penalty = cancelled * cancel_w + failures * fail_w
    effective_resolved = completed + penalty

    numerator = completed + prior_successes
    denominator = effective_resolved + prior_n
    if denominator <= 0:
        return 0

    rate = numerator / denominator * 100.0
    return max(0, min(100, int(round(rate))))


def master_completion_rate_percent(master) -> int:
    """All-time display completion rate (%)."""
    completed, cancelled, failures = _master_completion_triplet(master)
    return _display_completion_rate_percent(
        completed=completed,
        cancelled=cancelled,
        failures=failures,
    )


def user_completion_rate_percent(user) -> int:
    """All-time display completion rate — aligned with profile ``completed_orders``."""
    completed, cancelled, failures = _user_completion_triplet(user)
    return _display_completion_rate_percent(
        completed=completed,
        cancelled=cancelled,
        failures=failures,
    )
