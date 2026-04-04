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
