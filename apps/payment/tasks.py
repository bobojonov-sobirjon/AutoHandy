"""Celery tasks for payment / Stripe Connect."""
from __future__ import annotations

from celery import shared_task


@shared_task(ignore_result=True)
def notify_masters_payout_day_task() -> int:
    """
    Runs daily (Beat). On ``STRIPE_CONNECT_PAYOUT_WEEKLY_ANCHOR`` (e.g. Monday), sends FCM to
    every master with a linked ``acct_`` Connect account.
    """
    from apps.payment.services.payout_day_notify import send_payout_day_reminders_to_connected_masters

    return send_payout_day_reminders_to_connected_masters()
