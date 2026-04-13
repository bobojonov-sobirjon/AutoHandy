"""SOS emergency: broadcast to all nearest masters in zone; first accept wins."""
from __future__ import annotations

import logging
from datetime import timedelta
from typing import TYPE_CHECKING

from django.conf import settings
from django.utils import timezone

from apps.order.models import Order, OrderStatus, OrderType
from apps.order.services.master_service_zone import order_within_master_acceptance_zone

if TYPE_CHECKING:
    from django.http import HttpRequest

logger = logging.getLogger(__name__)


def _queue_master_ids(order: Order) -> list[int]:
    q = order.sos_offer_queue or []
    out: list[int] = []
    for x in q:
        try:
            out.append(int(x))
        except (TypeError, ValueError):
            continue
    return out


def sos_declined_master_ids_list(order: Order) -> list[int]:
    raw = order.sos_declined_master_ids or []
    out: list[int] = []
    for x in raw:
        try:
            out.append(int(x))
        except (TypeError, ValueError):
            continue
    return out


def master_in_sos_broadcast_queue(order: Order, master_id: int) -> bool:
    """Pending SOS with queue: master appears in broadcast list (for permissions / listings)."""
    if order.order_type != OrderType.SOS or order.status != OrderStatus.PENDING:
        return False
    if not order.sos_offer_queue:
        return False
    return master_id in _queue_master_ids(order)


def master_eligible_for_pending_sos_offer(order: Order, master_id: int) -> bool:
    """Can this master accept the pending SOS (in queue, not declined, inside acceptance zone)?"""
    if order.order_type != OrderType.SOS or order.status != OrderStatus.PENDING:
        return False
    if master_id not in _queue_master_ids(order):
        return False
    if master_id in sos_declined_master_ids_list(order):
        return False
    return order_within_master_acceptance_zone(order, master_id)


def eligible_sos_broadcast_master_ids(order: Order) -> list[int]:
    """Masters in queue who are in-zone and have not declined."""
    return [
        mid
        for mid in _queue_master_ids(order)
        if mid not in sos_declined_master_ids_list(order)
        and order_within_master_acceptance_zone(order, mid)
    ]


def current_sos_offered_master_id(order: Order) -> int | None:
    """
    Legacy: first queued master still eligible (for old Celery ticks / logging).
    Prefer master_eligible_* / master_in_sos_broadcast_queue in new code.
    """
    ids = eligible_sos_broadcast_master_ids(order)
    return ids[0] if ids else None


def order_ids_sos_currently_offered_to_master(master_pk: int, *, now=None) -> list[int]:
    """Order PKs for pending SOS broadcast where this master may still accept (active deadline only)."""
    now = now or timezone.now()
    ids: list[int] = []
    qs = (
        Order.objects.filter(
            order_type=OrderType.SOS,
            status=OrderStatus.PENDING,
            master__isnull=True,
            master_response_deadline__isnull=False,
            master_response_deadline__gt=now,
        )
        .exclude(sos_offer_queue=[])
        .only('id', 'sos_offer_queue', 'sos_declined_master_ids', 'latitude', 'longitude')
    )
    for o in qs.iterator(chunk_size=200):
        if master_eligible_for_pending_sos_offer(o, master_pk):
            ids.append(o.pk)
    return ids


def _finish_sos_broadcast_exhausted(order: Order) -> None:
    order.status = OrderStatus.REJECTED
    order.master = None
    order.master_response_deadline = None
    order.sos_offer_queue = []
    order.sos_offer_index = 0
    order.sos_declined_master_ids = []
    order.save(
        update_fields=[
            'status',
            'master',
            'master_response_deadline',
            'sos_offer_queue',
            'sos_offer_index',
            'sos_declined_master_ids',
            'updated_at',
        ]
    )


def finish_sos_broadcast_on_timeout(order: Order) -> None:
    """Global broadcast window ended with no accept."""
    _finish_sos_broadcast_exhausted(order)


def broadcast_sos_offers(order: Order, request: 'HttpRequest | None' = None) -> None:
    """
    Push SOS to every master in sos_offer_queue who is inside their acceptance zone.
    One shared deadline (SOS_BROADCAST_RESPONSE_SECONDS); first HTTP accept wins.
    """
    from apps.order.services.notifications import notify_master_new_order, push_sos_order_to_master_websocket
    from apps.order.services.celery_schedule import schedule_master_offer_expiry

    queue = _queue_master_ids(order)
    if not queue:
        return
    eligible = [mid for mid in queue if order_within_master_acceptance_zone(order, mid)]
    if not eligible:
        logger.warning('SOS order %s: no masters in queue within acceptance zone', order.pk)
        _finish_sos_broadcast_exhausted(order)
        return

    seconds = int(getattr(settings, 'SOS_BROADCAST_RESPONSE_SECONDS', 120))
    deadline = timezone.now() + timedelta(seconds=seconds)
    Order.objects.filter(pk=order.pk).update(
        master_response_deadline=deadline,
        sos_offer_index=0,
        sos_declined_master_ids=[],
    )
    order.refresh_from_db(
        fields=['master_response_deadline', 'sos_offer_index', 'sos_declined_master_ids']
    )

    for mid in eligible:
        notify_master_new_order(order, target_master_id=mid)
        push_sos_order_to_master_websocket(order, request=request, target_master_id=mid)

    schedule_master_offer_expiry(order.pk, deadline)


def sos_broadcast_decline(order: Order, master_id: int) -> bool:
    """Record decline for one master; others keep the offer until deadline."""
    if order.order_type != OrderType.SOS or not order.sos_offer_queue:
        return False
    q = _queue_master_ids(order)
    if master_id not in q:
        return False
    declined = sos_declined_master_ids_list(order)
    if master_id in declined:
        return True
    declined = declined + [master_id]
    order.sos_declined_master_ids = declined
    order.save(update_fields=['sos_declined_master_ids', 'updated_at'])
    return True


def try_rotate_sos_on_celery_tick(order_id: int, offered_master_id: int) -> None:
    """
    Legacy per-master SOS rotation (pre-broadcast). No longer advances ring; safe no-op
    if a stale task fires after deploy.
    """
    return


# Backwards-compatible names for offer_expiry imports
def advance_sos_ring_after_decline_or_timeout(order: Order) -> None:
    """Deprecated alias: timeout path rejects broadcast SOS (no sequential ring)."""
    finish_sos_broadcast_on_timeout(order)


def start_sos_offer_turn(order: Order, request: 'HttpRequest | None' = None) -> None:
    """Deprecated alias for sequential turn — use broadcast_sos_offers."""
    broadcast_sos_offers(order, request=request)
