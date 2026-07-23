"""Schedule Celery ETA tasks (offer expiry, client penalty-free window)."""
from __future__ import annotations

from datetime import datetime, timedelta

from django.conf import settings


def schedule_master_offer_expiry(order_id: int, deadline: datetime) -> None:
    try:
        from apps.order.tasks import expire_master_offer_order_task

        expire_master_offer_order_task.apply_async(args=[order_id], eta=deadline)
    except Exception:
        pass


def schedule_master_new_order_reminders(
    order_id: int,
    master_id: int,
    *,
    order_type: str | None = None,
) -> None:
    """
    Start repeating new-order FCM reminders until accept / decline / expiry.
    SOS: every 5s. Other orders: every 60s (1 minute).
    """
    try:
        from apps.order.services.offer_reminders import start_master_new_order_reminder_chain

        start_master_new_order_reminder_chain(order_id, master_id, order_type=order_type)
    except Exception:
        pass


def schedule_sos_rotation(order_id: int, master_id: int, countdown_seconds: int) -> None:
    try:
        from apps.order.tasks import sos_rotate_master_if_stale_task

        sos_rotate_master_if_stale_task.apply_async(
            args=[order_id, master_id],
            countdown=countdown_seconds,
        )
    except Exception:
        pass


def schedule_client_penalty_free_unlock(order_id: int, on_the_way_at: datetime) -> None:
    hours = int(getattr(settings, 'CLIENT_CANCEL_NO_PENALTY_AFTER_ON_THE_WAY_HOURS', 2))
    eta = on_the_way_at + timedelta(hours=hours)
    try:
        from apps.order.tasks import unlock_client_penalty_free_cancel_task

        unlock_client_penalty_free_cancel_task.apply_async(args=[order_id], eta=eta)
    except Exception:
        pass


def schedule_master_no_show_autocancel(order_id: int, arrival_deadline_at: datetime) -> None:
    try:
        from apps.order.tasks import auto_cancel_master_no_show_task

        auto_cancel_master_no_show_task.apply_async(args=[order_id], eta=arrival_deadline_at)
    except Exception:
        pass


def schedule_sos_master_no_departure_rebroadcast(order_id: int, accepted_at: datetime) -> None:
    """
    Legacy alias: SOS no-departure is scheduled via ``schedule_post_accept_timers``.
    """
    try:
        from apps.order.models import Order

        order = Order.objects.only('id', 'order_type').get(pk=order_id)
        from apps.order.services.mvp_timers import schedule_post_accept_timers

        schedule_post_accept_timers(
            order_id=order_id,
            order_type=str(order.order_type),
            accepted_at=accepted_at,
        )
    except Exception:
        pass


def schedule_master_no_departure_action(order_id: int, accepted_at: datetime) -> None:
    """Legacy alias for post-accept MVP timers."""
    schedule_sos_master_no_departure_rebroadcast(order_id, accepted_at)
