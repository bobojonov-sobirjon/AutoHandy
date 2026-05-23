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


def _master_completion_counts(master) -> tuple[int, int]:
    """
    All-time resolved assignments for this master:

      completed / (completed + cancelled + assignment_failures) * 100

    Examples: 1 complete → 100%; 2 complete → 100%; 2 complete + 1 cancel → 67%;
    then +1 complete → 75%.
    """
    from apps.order.models import MasterAssignmentFailure, Order, OrderStatus

    completed = Order.objects.filter(
        master_id=master.id,
        status=OrderStatus.COMPLETED,
    ).count()

    cancelled = Order.objects.filter(
        master_id=master.id,
        status=OrderStatus.CANCELLED,
    ).count()

    completed_ids = Order.objects.filter(
        master_id=master.id,
        status=OrderStatus.COMPLETED,
    ).values_list('id', flat=True)
    failures = (
        MasterAssignmentFailure.objects.filter(master_id=master.id)
        .exclude(order_id__in=completed_ids)
        .count()
    )

    resolved = completed + cancelled + failures
    return completed, resolved


def master_completion_rate_percent(master) -> int:
    """All-time completion rate (%); see ``_master_completion_counts``."""
    completed, resolved = _master_completion_counts(master)
    if resolved <= 0:
        return 0
    return int(round(completed / resolved * 100))


def user_completion_rate_percent(user) -> int:
    """All-time completion rate across every Master profile for this user."""
    from apps.master.models import Master

    masters = Master.objects.filter(user=user).only('id')
    if not masters.exists():
        return 0
    completed = 0
    resolved = 0
    for m in masters:
        c, r = _master_completion_counts(m)
        completed += c
        resolved += r
    if resolved <= 0:
        return 0
    return int(round(completed / resolved * 100))

