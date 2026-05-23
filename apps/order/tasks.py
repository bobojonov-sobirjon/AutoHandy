from __future__ import annotations

import logging
from datetime import timedelta

from celery import shared_task
from django.conf import settings
from django.core.cache import cache
from django.utils import timezone

from apps.order.models import Order, OrderStatus, OrderType

logger = logging.getLogger(__name__)
from apps.order.services.offer_expiry import (
    expire_master_offer_for_order,
    expire_stale_master_offers,
)


@shared_task(ignore_result=True)
def rebroadcast_sos_if_master_not_departed_task(order_id: int) -> bool:
    """
    ETA task: if SOS order is still ACCEPTED and master did not mark ON_THE_WAY in time,
    unassign and re-broadcast to other masters.
    """
    try:
        from apps.order.services.offer_expiry import rebroadcast_stale_accepted_sos_no_departure

        return bool(rebroadcast_stale_accepted_sos_no_departure(now=timezone.now(), order_id=order_id))
    except Exception:
        return False


@shared_task(ignore_result=True)
def sos_no_departure_warning_task(order_id: int) -> bool:
    try:
        from apps.order.services.sos_mvp import send_sos_no_departure_warning

        return bool(send_sos_no_departure_warning(order_id=order_id))
    except Exception:
        return False


@shared_task(ignore_result=True)
def scheduled_reminder_before_start_task(order_id: int) -> bool:
    try:
        from apps.order.services.scheduled_mvp import send_scheduled_reminder_before_start

        return bool(send_scheduled_reminder_before_start(order_id=order_id))
    except Exception:
        return False


@shared_task(ignore_result=True)
def scheduled_no_start_warning_task(order_id: int) -> bool:
    try:
        from apps.order.services.scheduled_mvp import send_scheduled_no_start_warning

        return bool(send_scheduled_no_start_warning(order_id=order_id))
    except Exception:
        return False


@shared_task(ignore_result=True)
def scheduled_no_start_cancel_task(order_id: int) -> bool:
    try:
        from apps.order.services.scheduled_mvp import cancel_scheduled_no_start

        return bool(cancel_scheduled_no_start(order_id=order_id))
    except Exception:
        return False


@shared_task(ignore_result=True)
def sos_on_the_way_communication_reminder_task(order_id: int) -> bool:
    """
    SOS MVP: every N minutes after on_the_way, remind master to update the customer (no GPS).
    """
    try:
        order = Order.objects.only('id', 'order_type', 'status', 'master_id', 'on_the_way_at').get(pk=order_id)
    except Order.DoesNotExist:
        return False
    if order.order_type != OrderType.SOS:
        return False
    if order.status not in (
        OrderStatus.ON_THE_WAY,
        OrderStatus.ARRIVED,
        OrderStatus.IN_PROGRESS,
    ):
        return False
    if not order.master_id:
        return False
    try:
        from apps.master.models import Master
        from apps.order.services.notifications import notify_master_order_kind
        from apps.order.services.mvp_timers import schedule_sos_communication_reminder

        mu = Master.objects.select_related('user').only('id', 'user_id').get(pk=order.master_id)
        notify_master_order_kind(
            master_user_id=mu.user_id,
            order_id=order.id,
            kind='sos_communication_reminder',
            extra_data={'order_type': str(order.order_type)},
        )
        schedule_sos_communication_reminder(order_id=order.pk, from_dt=timezone.now())
    except Exception:  # noqa: BLE001
        return False
    return True


@shared_task(ignore_result=True)
def master_no_departure_action_task(order_id: int) -> bool:
    """
    ETA task: after accept, if master did not move order to ON_THE_WAY in time,
    take action depending on order_type.
    """
    try:
        from apps.order.services.offer_expiry import handle_accepted_no_departure_for_order

        return bool(handle_accepted_no_departure_for_order(order_id=order_id, now=timezone.now()))
    except Exception:
        return False


@shared_task(ignore_result=True)
def push_sos_offer_to_masters_task(order_id: int, master_ids: list[int]) -> int:
    """
    Low-tier SOS fallback: deliver offers after a delay if the order is still pending.
    """
    from apps.master.models import Master
    from apps.order.models import MasterOfferEvent, MasterOfferEventStatus
    from apps.order.services.notifications import notify_master_new_order, push_sos_order_to_master_websocket
    from apps.order.services.sos_rotation import master_eligible_for_pending_sos_offer

    try:
        order = Order.objects.get(pk=order_id)
    except Order.DoesNotExist:
        return 0
    if order.status != OrderStatus.PENDING or order.order_type != OrderType.SOS:
        return 0
    if not order.sos_offer_queue:
        return 0
    if order.master_response_deadline and timezone.now() > order.master_response_deadline:
        return 0

    sent = 0
    mids = [int(x) for x in master_ids if x is not None]
    masters = {m.id: m for m in Master.objects.filter(id__in=mids).only('id', 'user_id')}
    for mid in mids:
        if mid not in masters:
            continue
        if not master_eligible_for_pending_sos_offer(order, mid):
            continue
        notify_master_new_order(order, target_master_id=mid)
        push_sos_order_to_master_websocket(order, request=None, target_master_id=mid)
        try:
            MasterOfferEvent.objects.get_or_create(
                master_id=mid,
                order_id=order.pk,
                defaults={'status': MasterOfferEventStatus.SENT},
            )
        except Exception:  # noqa: BLE001
            pass
        sent += 1
    return sent


# ---------------------------------------------------------------------------
# Compatibility tasks (old names still present in Redis queue).
# These no-op or delegate to current task names so the worker won't error.
# ---------------------------------------------------------------------------


@shared_task(ignore_result=True, name='apps.order.tasks.expire_master_offer_for_order')
def expire_master_offer_for_order_compat(order_id: int) -> bool:
    """Legacy task name kept for old queued messages."""
    return bool(expire_master_offer_for_order(order_id))


@shared_task(ignore_result=True, name='apps.order.tasks.offer_deadline_reminder')
def offer_deadline_reminder_compat(order_id: int) -> None:
    """Legacy reminder task name; current reminders are handled by beat sweep task."""
    try:
        logger.info('Compat task offer_deadline_reminder called for order_id=%s (ignored)', order_id)
    except Exception:
        pass


@shared_task(ignore_result=True, name='apps.order.tasks.assign_driver_to_order_async')
def assign_driver_to_order_async_compat(order_id: int) -> None:
    """Legacy taxi/ride task name from another project; ignore safely."""
    try:
        logger.info('Compat task assign_driver_to_order_async called for order_id=%s (ignored)', order_id)
    except Exception:
        pass


@shared_task(ignore_result=True, name='apps.notification.tasks.send_push_notification_async')
def send_push_notification_async_compat(*args, **kwargs) -> None:
    """
    Legacy task name from another module/app not present in this repo.
    We keep a stub so Celery can consume old messages without crashing.
    """
    try:
        logger.info('Compat task send_push_notification_async called (ignored)')
    except Exception:
        pass


@shared_task(ignore_result=True)
def expire_stale_master_offers_task() -> int:
    """
    Celery Beat (every minute): pending orders whose master_response_deadline passed.
    Standard: status → rejected, master cleared. SOS with queue: broadcast window ended → reject.
    """
    return expire_stale_master_offers()


@shared_task(ignore_result=True)
def warn_upcoming_order_deadlines_task() -> int:
    """
    Beat (every minute): send push warnings a few minutes before automatic deadlines:
    - pending master_response_deadline (standard + SOS broadcast)
    - on_the_way penalty-free cancel unlock (2h)
    - on_the_way arrival_deadline_at (no-show auto-cancel)
    """
    from datetime import timedelta

    from apps.master.models import Master
    from apps.order.services.notifications import notify_master_order_kind, notify_user_order_kind

    now = timezone.now()
    warn_min = int(getattr(settings, 'ORDER_DEADLINE_WARN_MINUTES', 3))
    window = timedelta(minutes=warn_min)
    sent = 0

    # 1) Pending: master_response_deadline approaching (standard and SOS broadcast).
    qs = (
        Order.objects.filter(
            status=OrderStatus.PENDING,
            master_response_deadline__isnull=False,
            master_response_deadline__gt=now,
            master_response_deadline__lte=now + window,
        )
        .only('id', 'order_type', 'user_id', 'master_id', 'master_response_deadline', 'sos_offer_queue')
        .iterator(chunk_size=200)
    )
    for o in qs:
        key = f'push_warn_offer_deadline_{o.pk}'
        if cache.get(key):
            continue
        cache.set(key, 1, timeout=warn_min * 60 + 60)

        remaining = int(max(0, (o.master_response_deadline - now).total_seconds() // 60))
        # User warning (requested: always for pending expiry).
        try:
            kind = 'sos_expiring_soon' if (o.order_type == OrderType.SOS and o.sos_offer_queue) else 'offer_expiring_soon'
            notify_user_order_kind(
                o,
                kind=kind,
                extra_data={'minutes_left': str(remaining)},
            )
            sent += 1
        except Exception:  # noqa: BLE001
            pass

        # Master warning (only if a master is clearly the target).
        if o.order_type != OrderType.SOS and o.master_id:
            try:
                mu = Master.objects.select_related('user').only('id', 'user_id').get(pk=o.master_id)
                notify_master_order_kind(
                    master_user_id=mu.user_id,
                    order_id=o.id,
                    kind='offer_expiring_soon',
                    extra_data={'minutes_left': str(remaining), 'order_type': str(o.order_type)},
                )
                sent += 1
            except Exception:  # noqa: BLE001
                pass

    # 2) On the way: penalty-free cancel unlock approaching (client side) — notify both.
    hours = int(getattr(settings, 'CLIENT_CANCEL_NO_PENALTY_AFTER_ON_THE_WAY_HOURS', 2))
    unlock_cutoff = now - timedelta(hours=hours) + window
    qs2 = (
        Order.objects.filter(
            status=OrderStatus.ON_THE_WAY,
            on_the_way_at__isnull=False,
            client_penalty_free_cancel_unlocked=False,
            on_the_way_at__lte=unlock_cutoff,
        )
        .only('id', 'user_id', 'master_id', 'on_the_way_at')
        .iterator(chunk_size=200)
    )
    for o in qs2:
        key = f'push_warn_penalty_unlock_{o.pk}'
        if cache.get(key):
            continue
        cache.set(key, 1, timeout=warn_min * 60 + 300)
        try:
            notify_user_order_kind(
                o,
                kind='penalty_free_unlock_soon',
                extra_data={'minutes_left': str(warn_min)},
            )
            sent += 1
        except Exception:  # noqa: BLE001
            pass
        if o.master_id:
            try:
                mu = Master.objects.select_related('user').only('id', 'user_id').get(pk=o.master_id)
                notify_master_order_kind(
                    master_user_id=mu.user_id,
                    order_id=o.id,
                    kind='penalty_free_unlock_soon',
                    extra_data={'minutes_left': str(warn_min), 'order_type': str(o.order_type)},
                )
                sent += 1
            except Exception:  # noqa: BLE001
                pass

    # 3) On the way: arrival_deadline_at approaching — notify both.
    qs3 = (
        Order.objects.filter(
            status=OrderStatus.ON_THE_WAY,
            arrival_deadline_at__isnull=False,
            arrival_deadline_at__gt=now,
            arrival_deadline_at__lte=now + window,
        )
        .only('id', 'user_id', 'master_id', 'arrival_deadline_at')
        .iterator(chunk_size=200)
    )
    for o in qs3:
        key = f'push_warn_arrival_deadline_{o.pk}'
        if cache.get(key):
            continue
        cache.set(key, 1, timeout=warn_min * 60 + 60)
        try:
            notify_user_order_kind(
                o,
                kind='arrival_deadline_soon',
                extra_data={'minutes_left': str(warn_min)},
            )
            sent += 1
        except Exception:  # noqa: BLE001
            pass
        if o.master_id:
            try:
                mu = Master.objects.select_related('user').only('id', 'user_id').get(pk=o.master_id)
                notify_master_order_kind(
                    master_user_id=mu.user_id,
                    order_id=o.id,
                    kind='arrival_deadline_soon',
                    extra_data={'minutes_left': str(warn_min), 'order_type': str(o.order_type)},
                )
                sent += 1
            except Exception:  # noqa: BLE001
                pass

    return sent


def run_broadcast_custom_request(order_id: int) -> int:
    """
    Core logic for custom-request geo push (used by Celery task and inline fallback when Redis is down).
    """
    from apps.order.services.custom_request_broadcast import custom_request_broadcast_recipient_master_ids
    from apps.order.services.notifications import (
        notify_master_order_kind,
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
    out_mids = custom_request_broadcast_recipient_master_ids(order)
    for mid in out_mids:
        try:
            from apps.master.models import Master

            mu = (
                Master.objects.select_related('user')
                .only('id', 'user_id')
                .get(pk=mid)
            )
            notify_master_order_kind(
                master_user_id=mu.user_id,
                order_id=order.id,
                kind='custom_request_new',
                extra_data={'order_type': str(order.order_type)},
            )
        except Exception:  # noqa: BLE001
            pass
        push_custom_request_to_master_websocket(order, target_master_id=mid)
    return len(out_mids)


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
    from apps.master.models import Master
    from apps.order.services.notifications import notify_master_order_kind, notify_user_order_kind

    updated = Order.objects.filter(pk=order_id, status=OrderStatus.ON_THE_WAY).update(
        client_penalty_free_cancel_unlocked=True,
    )
    if not updated:
        return
    try:
        o = Order.objects.only('id', 'user_id', 'master_id').get(pk=order_id)
    except Exception:  # noqa: BLE001
        return
    # Notify user.
    try:
        notify_user_order_kind(o, kind='penalty_free_unlocked')
    except Exception:  # noqa: BLE001
        pass
    # Notify master.
    if o.master_id:
        try:
            mu = Master.objects.select_related('user').only('id', 'user_id').get(pk=o.master_id)
            notify_master_order_kind(
                master_user_id=mu.user_id,
                order_id=o.id,
                kind='penalty_free_unlocked',
            )
        except Exception:  # noqa: BLE001
            pass


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
        # Push notifications about auto-cancel (no-show).
        try:
            from apps.order.services.notifications import notify_master_order_kind, notify_user_order_kind
            from apps.master.models import Master

            extra = {'by': 'system'}
            notify_user_order_kind(order, kind='auto_cancel_no_show', extra_data=extra)
            if order.master_id:
                mu = Master.objects.select_related('user').only('id', 'user_id').get(pk=order.master_id)
                notify_master_order_kind(
                    master_user_id=mu.user_id,
                    order_id=order.id,
                    kind='auto_cancel_no_show',
                    extra_data=extra,
                )
        except Exception:  # noqa: BLE001
            pass


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


@shared_task(ignore_result=True)
def charge_cancellation_penalty_task(order_id: int) -> bool:
    """
    Retry charging ``order_penalty_total`` from the driver's saved card after client cancel.
    """
    from apps.order.models import OrderStripePaymentStatus
    from apps.order.services.client_cancel_penalty import collect_pending_cancellation_penalty

    try:
        order = Order.objects.select_related('saved_card', 'user').get(pk=order_id)
    except Order.DoesNotExist:
        return False
    if order.order_penalty_total <= 0:
        return True
    if order.stripe_payment_status == OrderStripePaymentStatus.SUCCEEDED:
        return True
    return collect_pending_cancellation_penalty(order)


@shared_task(ignore_result=True)
def sweep_unpaid_cancellation_penalties_task() -> int:
    """
    Beat fallback: cancelled orders with ``order_penalty_total`` but no successful Stripe capture.
    """
    from decimal import Decimal

    from apps.order.models import OrderStripePaymentStatus
    from apps.order.services.client_cancel_penalty import collect_pending_cancellation_penalty

    if not getattr(settings, 'CLIENT_CANCEL_PENALTY_CHARGE_ENABLED', True):
        return 0

    qs = (
        Order.objects.filter(status=OrderStatus.CANCELLED, order_penalty_total__gt=Decimal('0'))
        .exclude(stripe_payment_status=OrderStripePaymentStatus.SUCCEEDED)
        .select_related('saved_card', 'user')
        .order_by('id')[:200]
    )
    n = 0
    for order in qs.iterator():
        if collect_pending_cancellation_penalty(order):
            n += 1
    return n
