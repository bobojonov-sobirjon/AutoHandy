"""When a master is assigned on a pending order, start the response window + notify."""
from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING

from django.conf import settings
from django.utils import timezone

from apps.order.models import Order, OrderStatus, OrderType

if TYPE_CHECKING:
    from django.http import HttpRequest


def activate_pending_master_offer(
    order: Order,
    request: 'HttpRequest | None' = None,
    *,
    send_push: bool = True,
) -> None:
    """Set master_response_deadline; optionally trigger push (FCM hook)."""
    if order.status != OrderStatus.PENDING:
        return
    if order.order_type == OrderType.CUSTOM_REQUEST:
        return
    if order.order_type == OrderType.SOS:
        if order.sos_offer_queue:
            from apps.order.services.sos_rotation import broadcast_sos_offers

            broadcast_sos_offers(order, request=request)
        return
    if not order.master_id:
        return

    minutes = int(getattr(settings, 'MASTER_OFFER_RESPONSE_MINUTES', 15))
    deadline = timezone.now() + timedelta(minutes=minutes)
    Order.objects.filter(pk=order.pk).update(
        master_response_deadline=deadline,
    )
    order.refresh_from_db(fields=['master_response_deadline'])
    from apps.order.services.notifications import notify_master_new_order
    from apps.order.services.celery_schedule import (
        schedule_master_new_order_reminders,
        schedule_master_offer_expiry,
    )
    from apps.order.models import MasterOfferEvent, MasterOfferEventStatus

    if send_push:
        notify_master_new_order(order)
        if order.master_id:
            schedule_master_new_order_reminders(order.pk, order.master_id)
    if order.master_response_deadline:
        schedule_master_offer_expiry(order.pk, order.master_response_deadline)

    # Track offer for acceptance-rate metrics.
    try:
        MasterOfferEvent.objects.get_or_create(
            master_id=order.master_id,
            order_id=order.pk,
            defaults={'status': MasterOfferEventStatus.SENT},
        )
    except Exception:  # noqa: BLE001
        pass
