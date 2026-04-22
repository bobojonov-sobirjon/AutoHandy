from __future__ import annotations

import logging
from datetime import timedelta

from celery import shared_task
from django.conf import settings
from django.utils import timezone

from apps.order.models import Order, OrderStatus, OrderType

logger = logging.getLogger(__name__)
from apps.order.services.offer_expiry import (
    expire_master_offer_for_order,
    expire_stale_master_offers,
)


@shared_task(ignore_result=True)
def expire_stale_master_offers_task() -> int:
    """
    Celery Beat (every minute): pending orders whose master_response_deadline passed.
    Standard: status → rejected, master cleared. SOS with queue: broadcast window ended → reject.
    """
    return expire_stale_master_offers()


def run_broadcast_custom_request(order_id: int) -> int:
    """
    Core logic for custom-request geo push (used by Celery task and inline fallback when Redis is down).
    """
    from apps.order.services.custom_request_broadcast import master_ids_within_custom_request_radius
    from apps.order.services.notifications import (
        notify_master_order_event,
        push_custom_request_to_master_websocket,
    )

    try:
        order = Order.objects.get(pk=order_id)
    except Order.DoesNotExist:
        return 0
    if order.order_type != OrderType.CUSTOM_REQUEST or order.status != OrderStatus.PENDING:
        return 0
    if order.latitude is None or order.longitude is None:
        return 0
    mids = master_ids_within_custom_request_radius(float(order.latitude), float(order.longitude))
    for mid in mids:
        try:
            from apps.master.models import Master

            mu = (
                Master.objects.select_related('user')
                .only('id', 'user_id')
                .get(pk=mid)
            )
            notify_master_order_event(
                master_user_id=mu.user_id,
                order_id=order.id,
                title='New custom request',
                body=f'Order #{order.id} is available',
                kind='custom_request_new',
                extra_data={'order_type': str(order.order_type)},
            )
        except Exception:  # noqa: BLE001
            pass
        push_custom_request_to_master_websocket(order, target_master_id=mid)
    return len(mids)


@shared_task(ignore_result=True)
def broadcast_custom_request_task(order_id: int) -> int:
    """After create: notify masters in radius via WebSocket (Celery queue)."""
    return run_broadcast_custom_request(order_id)


def schedule_broadcast_custom_request(order_id: int) -> None:
    """
    Enqueue ``broadcast_custom_request_task``; if broker is unreachable (e.g. Redis not running on
    Windows dev), run the same work in-process so POST /custom-request/ still returns 201.
    """
    try:
        broadcast_custom_request_task.delay(order_id)
    except Exception as exc:  # noqa: BLE001 — broker/connection errors vary (kombu, redis, OSError)
        logger.warning(
            'Celery delay failed for broadcast_custom_request (order_id=%s): %s — running inline',
            order_id,
            exc,
        )
        run_broadcast_custom_request(order_id)


@shared_task(ignore_result=True)
def sos_rotate_master_if_stale_task(order_id: int, offered_master_id: int) -> None:
    from apps.order.services.sos_rotation import try_rotate_sos_on_celery_tick

    try_rotate_sos_on_celery_tick(order_id, offered_master_id)


@shared_task(ignore_result=True)
def expire_master_offer_order_task(order_id: int) -> bool:
    """ETA-fired task when the 15-minute (configurable) master offer ends."""
    return expire_master_offer_for_order(order_id)


@shared_task(ignore_result=True)
def unlock_client_penalty_free_cancel_task(order_id: int) -> None:
    """
    ETA task: after N hours «on the way», allow client penalty-free cancel (if still on the way).
    """
    Order.objects.filter(pk=order_id, status=OrderStatus.ON_THE_WAY).update(
        client_penalty_free_cancel_unlocked=True,
    )


@shared_task(ignore_result=True)
def sweep_client_penalty_free_unlock_task() -> int:
    """
    Fallback if ETA tasks were missed (worker down): unlock flag for stale on_the_way orders.
    """
    hours = int(getattr(settings, 'CLIENT_CANCEL_NO_PENALTY_AFTER_ON_THE_WAY_HOURS', 2))
    cutoff = timezone.now() - timedelta(hours=hours)
    qs = Order.objects.filter(
        status=OrderStatus.ON_THE_WAY,
        on_the_way_at__isnull=False,
        on_the_way_at__lte=cutoff,
        client_penalty_free_cancel_unlocked=False,
    )
    n = qs.update(client_penalty_free_cancel_unlocked=True)
    return n


@shared_task(ignore_result=True)
def auto_cancel_master_no_show_task(order_id: int) -> None:
    """
    ETA task: if the master is still "on the way" past arrival_deadline_at, auto-cancel the order
    and unlock client penalty-free cancellation (client should not be penalized for master no-show).
    """
    now = timezone.now()
    qs = Order.objects.filter(
        pk=order_id,
        status=OrderStatus.ON_THE_WAY,
        arrival_deadline_at__isnull=False,
        arrival_deadline_at__lte=now,
    )
    for order in qs.select_related('master').only(
        'id',
        'status',
        'arrival_deadline_at',
        'client_penalty_free_cancel_unlocked',
        'estimated_arrival_at',
        'eta_minutes',
        'completion_pin',
        'completion_pin_issued_at',
        'master_id',
    ):
        # Terminal / progressed states are filtered out by the queryset.
        order.status = OrderStatus.CANCELLED
        order.auto_cancel_reason = 'master_no_show'
        order.client_penalty_free_cancel_unlocked = True
        order.estimated_arrival_at = None
        order.eta_minutes = None
        order.arrival_deadline_at = None
        order.completion_pin = ''
        order.completion_pin_issued_at = None
        order.save(
            update_fields=[
                'status',
                'auto_cancel_reason',
                'client_penalty_free_cancel_unlocked',
                'estimated_arrival_at',
                'eta_minutes',
                'arrival_deadline_at',
                'completion_pin',
                'completion_pin_issued_at',
                'updated_at',
            ]
        )


@shared_task(ignore_result=True)
def sweep_auto_cancel_master_no_show_task() -> int:
    """
    Fallback if ETA tasks were missed (worker down): auto-cancel stale on_the_way orders
    whose arrival_deadline_at already passed.
    """
    now = timezone.now()
    qs = Order.objects.filter(
        status=OrderStatus.ON_THE_WAY,
        arrival_deadline_at__isnull=False,
        arrival_deadline_at__lte=now,
    )
    n = 0
    for order in qs.only(
        'id',
        'status',
        'arrival_deadline_at',
        'client_penalty_free_cancel_unlocked',
        'estimated_arrival_at',
        'eta_minutes',
        'completion_pin',
        'completion_pin_issued_at',
    ):
        order.status = OrderStatus.CANCELLED
        order.auto_cancel_reason = 'master_no_show'
        order.client_penalty_free_cancel_unlocked = True
        order.estimated_arrival_at = None
        order.eta_minutes = None
        order.arrival_deadline_at = None
        order.completion_pin = ''
        order.completion_pin_issued_at = None
        order.save(
            update_fields=[
                'status',
                'auto_cancel_reason',
                'client_penalty_free_cancel_unlocked',
                'estimated_arrival_at',
                'eta_minutes',
                'arrival_deadline_at',
                'completion_pin',
                'completion_pin_issued_at',
                'updated_at',
            ]
        )
        n += 1
    return n
