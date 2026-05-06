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
    If a master accepts an SOS order but does not start the trip ("on_the_way") within N minutes,
    the order should be re-broadcast to other masters.
    """
    minutes = int(getattr(settings, 'SOS_MASTER_NO_DEPARTURE_MINUTES', 30))
    eta = accepted_at + timedelta(minutes=minutes)
    try:
        from apps.order.tasks import rebroadcast_sos_if_master_not_departed_task

        rebroadcast_sos_if_master_not_departed_task.apply_async(args=[order_id], eta=eta)
    except Exception:
        pass


def schedule_master_no_departure_action(order_id: int, accepted_at: datetime) -> None:
    """
    Generic "no departure" watchdog after accept (all order types):
    if the master does not mark ON_THE_WAY within N minutes, the system takes action.
    """
    minutes = int(getattr(settings, 'MASTER_NO_DEPARTURE_MINUTES', 30))
    eta = accepted_at + timedelta(minutes=minutes)
    try:
        from apps.order.tasks import master_no_departure_action_task

        master_no_departure_action_task.apply_async(args=[order_id], eta=eta)
    except Exception:
        pass
