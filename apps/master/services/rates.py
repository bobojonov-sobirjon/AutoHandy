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
      accepted / (accepted + declined + expired) * 100
    """
    from apps.order.models import MasterOfferEvent, MasterOfferEventStatus

    start = _window_start(30)
    qs = MasterOfferEvent.objects.filter(master=master, offered_at__gte=start)
    denom = qs.filter(
        status__in=(
            MasterOfferEventStatus.ACCEPTED,
            MasterOfferEventStatus.DECLINED,
            MasterOfferEventStatus.EXPIRED,
        )
    ).count()
    if denom <= 0:
        return 0
    num = qs.filter(status=MasterOfferEventStatus.ACCEPTED).count()
    return int(round(num / denom * 100))


def master_completion_rate_percent(master) -> int:
    """
    Completion rate (%) from resolved assignments in the window (``accepted_at`` set):

      completed / (completed + cancelled) * 100

    In-progress orders (accepted, on_the_way, in_progress, …) are excluded until they
    finish as **completed** or **cancelled** (e.g. client declined, master cancel).
    """
    from apps.order.models import Order, OrderStatus

    start = _window_start(30)
    qs = Order.objects.filter(master=master, accepted_at__isnull=False, accepted_at__gte=start)
    completed = qs.filter(status=OrderStatus.COMPLETED).count()
    cancelled = qs.filter(status=OrderStatus.CANCELLED).count()
    resolved = completed + cancelled
    if resolved <= 0:
        return 0
    return int(round(completed / resolved * 100))

