"""Push masters on configured Stripe Connect payout anchor day (e.g. every Monday)."""
from __future__ import annotations

import logging
from datetime import date

from django.conf import settings
from django.core.cache import cache
from django.utils import timezone

logger = logging.getLogger(__name__)

# Python weekday(): Monday=0 … Sunday=6 (matches Stripe weekly_anchor names).
_ANCHOR_TO_WEEKDAY: dict[str, int] = {
    'monday': 0,
    'tuesday': 1,
    'wednesday': 2,
    'thursday': 3,
    'friday': 4,
    'saturday': 5,
    'sunday': 6,
}

_INTERVAL_LABELS: dict[str, str] = {
    'daily': 'daily',
    'weekly': 'weekly',
    'monthly': 'monthly',
    'manual': 'manual',
}


def payout_weekly_anchor() -> str:
    return (getattr(settings, 'STRIPE_CONNECT_PAYOUT_WEEKLY_ANCHOR', 'monday') or 'monday').strip().lower()


def payout_interval() -> str:
    return (getattr(settings, 'STRIPE_CONNECT_PAYOUT_INTERVAL', 'weekly') or 'weekly').strip().lower()


def is_payout_reminder_day(*, on_date: date | None = None) -> bool:
    """True when ``on_date`` (local) is the configured weekly payout anchor."""
    interval = payout_interval()
    if interval != 'weekly':
        return False
    anchor = payout_weekly_anchor()
    want = _ANCHOR_TO_WEEKDAY.get(anchor)
    if want is None:
        want = 0
    d = on_date or timezone.localdate()
    return d.weekday() == want


def anchor_day_display_name() -> str:
    anchor = payout_weekly_anchor()
    return anchor.capitalize() if anchor else 'Monday'


def send_payout_day_reminders_to_connected_masters(*, on_date: date | None = None) -> int:
    """
    FCM to every master with ``stripe_connect_account_id`` starting with ``acct_``.
    Returns count of masters notified (one push per master per local day).
    """
    if not getattr(settings, 'STRIPE_CONNECT_PAYOUT_REMINDER_ENABLED', True):
        return 0
    if not is_payout_reminder_day(on_date=on_date):
        return 0

    from apps.master.models import Master
    from apps.order.services.notifications import notify_master_payout_day

    today = on_date or timezone.localdate()
    anchor = anchor_day_display_name()
    interval = _INTERVAL_LABELS.get(payout_interval(), payout_interval())

    qs = (
        Master.objects.filter(stripe_connect_account_id__startswith='acct_')
        .exclude(stripe_connect_account_id='')
        .select_related('user')
        .only('id', 'user_id', 'stripe_connect_account_id')
    )

    sent = 0
    for master in qs.iterator(chunk_size=200):
        uid = getattr(master, 'user_id', None)
        if not uid:
            continue
        cache_key = f'payout_day_push_master_{master.pk}_{today.isoformat()}'
        if cache.get(cache_key):
            continue
        try:
            notify_master_payout_day(
                master_user_id=int(uid),
                anchor_day=anchor,
                interval=interval,
            )
            cache.set(cache_key, 1, timeout=60 * 60 * 26)
            sent += 1
        except Exception as exc:  # noqa: BLE001
            logger.warning('payout_day_push failed master_id=%s: %s', master.pk, exc)
    return sent
