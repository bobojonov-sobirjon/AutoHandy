"""SOS emergency: broadcast to all nearest masters in zone; first accept wins."""
from __future__ import annotations

import logging
from datetime import timedelta
from typing import TYPE_CHECKING

from django.conf import settings
from django.utils import timezone

from apps.order.models import Order, OrderStatus, OrderType
from apps.master.models import Master
from apps.order.services.master_service_zone import order_within_master_acceptance_zone

if TYPE_CHECKING:
    from django.http import HttpRequest

logger = logging.getLogger(__name__)


def _emergency_rate_thresholds() -> tuple[int, int]:
    try:
        min_acc = int(getattr(settings, 'EMERGENCY_ACCEPTANCE_RATE_MIN', 90))
        min_comp = int(getattr(settings, 'EMERGENCY_COMPLETION_RATE_MIN', 90))
    except Exception:
        min_acc, min_comp = 90, 90
    return min_acc, min_comp


def master_meets_emergency_offer_thresholds(master_id: int) -> bool:
    """
    True if master's acceptance and completion rates meet global SOS minima
    (same rule as broadcast push targets).
    """
    try:
        from apps.master.services.rates import master_acceptance_rate_percent, master_completion_rate_percent

        m = Master.objects.filter(pk=int(master_id)).first()
        if not m:
            return False
        min_acc, min_comp = _emergency_rate_thresholds()
        acc = master_acceptance_rate_percent(m)
        comp = master_completion_rate_percent(m)
    except Exception:
        return False
    return acc >= min_acc and comp >= min_comp


def filter_master_ids_meeting_emergency_thresholds(master_ids: list[int]) -> list[int]:
    """Keep input order; de-duplicate; drop masters below emergency rate floors."""
    from apps.master.services.rates import master_acceptance_rate_percent, master_completion_rate_percent

    min_acc, min_comp = _emergency_rate_thresholds()
    ids = []
    seen: set[int] = set()
    for x in master_ids:
        try:
            mid = int(x)
        except (TypeError, ValueError):
            continue
        if mid in seen:
            continue
        seen.add(mid)
        ids.append(mid)
    if not ids:
        return []
    masters = {m.id: m for m in Master.objects.filter(id__in=ids).only('id')}
    out: list[int] = []
    for mid in ids:
        m = masters.get(mid)
        if not m:
            continue
        try:
            acc = master_acceptance_rate_percent(m)
            comp = master_completion_rate_percent(m)
        except Exception:
            acc, comp = 0, 0
        if acc >= min_acc and comp >= min_comp:
            out.append(mid)
    return out


def _queue_master_ids(order: Order) -> list[int]:
    q = order.sos_offer_queue or []
    out: list[int] = []
    for x in q:
        try:
            out.append(int(x))
        except (TypeError, ValueError):
            continue
    return out


def sos_offer_recipient_master_ids(order: Order) -> list[int]:
    """Master PKs in ``sos_offer_queue`` — snapshot **before** clearing on accept/broadcast end."""
    return _queue_master_ids(order)


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
    """Pending SOS: master is in the geographic queue and meets emergency rate floors (same as push cohort)."""
    if order.order_type != OrderType.SOS or order.status != OrderStatus.PENDING:
        return False
    if not order.sos_offer_queue:
        return False
    if master_id not in _queue_master_ids(order):
        return False
    return master_meets_emergency_offer_thresholds(master_id)


def master_eligible_for_pending_sos_offer(order: Order, master_id: int) -> bool:
    """Can this master accept the pending SOS (in queue, not declined, in zone, emergency rates OK)?"""
    if order.order_type != OrderType.SOS or order.status != OrderStatus.PENDING:
        return False
    if master_id not in _queue_master_ids(order):
        return False
    if master_id in sos_declined_master_ids_list(order):
        return False
    if not order_within_master_acceptance_zone(order, master_id):
        return False
    return master_meets_emergency_offer_thresholds(master_id)


def eligible_sos_broadcast_master_ids(order: Order) -> list[int]:
    """Masters in queue who are in-zone, have not declined, and meet emergency rate floors."""
    return [
        mid
        for mid in _queue_master_ids(order)
        if mid not in sos_declined_master_ids_list(order)
        and order_within_master_acceptance_zone(order, mid)
        and master_meets_emergency_offer_thresholds(mid)
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
    # Note: notification is handled by the caller (timeout vs all-declined).


def finish_sos_broadcast_all_declined(order: Order) -> None:
    """
    Finish SOS broadcast because all eligible masters declined.
    Sends a single user notification (do NOT spam for each decline).
    """
    _finish_sos_broadcast_exhausted(order)
    try:
        from apps.order.services.notifications import notify_user_order_event

        notify_user_order_event(
            order,
            title='Emergency request declined',
            body='No technicians accepted your request. Please try again.',
            kind='sos_all_declined',
            extra_data={'by': 'system'},
        )
    except Exception:  # noqa: BLE001
        pass


def finish_sos_broadcast_on_timeout(order: Order) -> None:
    """Global broadcast window ended with no accept."""
    _finish_sos_broadcast_exhausted(order)
    # Timeout is different from "all declined": keep the existing semantics/message.
    try:
        from apps.order.services.notifications import notify_user_order_event

        notify_user_order_event(
            order,
            title='SOS request expired',
            body=f'SOS order #{order.id}: no master responded in time. Please try again.',
            kind='sos_expired',
            extra_data={'by': 'system'},
        )
    except Exception:  # noqa: BLE001
        pass


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

    min_acc, min_comp = _emergency_rate_thresholds()
    high = filter_master_ids_meeting_emergency_thresholds(eligible)

    # Strict rule: Emergency jobs are sent ONLY to masters meeting both thresholds.
    if not high:
        logger.info(
            'SOS order %s: no masters meet emergency thresholds acc>=%s comp>=%s; ending broadcast',
            order.pk,
            min_acc,
            min_comp,
        )
        _finish_sos_broadcast_exhausted(order)
        return

    send_now = high

    for mid in send_now:
        notify_master_new_order(order, target_master_id=mid)
        push_sos_order_to_master_websocket(order, request=request, target_master_id=mid)
        # Track offer event for acceptance-rate metrics.
        try:
            from apps.order.models import MasterOfferEvent, MasterOfferEventStatus

            MasterOfferEvent.objects.get_or_create(
                master_id=mid,
                order_id=order.pk,
                defaults={'status': MasterOfferEventStatus.SENT},
            )
        except Exception:  # noqa: BLE001
            pass

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
