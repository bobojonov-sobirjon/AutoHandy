"""Expire master response offers that were not accepted within the deadline."""
from __future__ import annotations

from datetime import timedelta
from typing import Container

from django.utils import timezone

from apps.order.models import Order, OrderStatus, OrderType
from apps.order.services.assignment_failure import (
    record_sos_no_departure_failure,
    record_standard_no_departure_failure,
)
from apps.order.services.mvp_timers import no_departure_cutoff_minutes_for_order
from apps.order.services.order_scheduled_start import order_has_scheduled_start
from apps.order.services.scheduled_mvp import sweep_scheduled_mvp_deadlines
from apps.order.services.standard_accept_mvp import sweep_standard_accept_no_on_the_way
from apps.order.services.sos_rotation import (
    advance_sos_ring_after_decline_or_timeout,
    filter_master_ids_meeting_emergency_thresholds,
)


def expire_stale_master_offers(now=None, *, skip_order_ids: Container[int] | None = None) -> int:
    """
    Pending orders past master_response_deadline: SOS broadcast → reject if still unassigned;
    standard orders with master FK → reject.

    skip_order_ids: do not touch these orders (use on POST accept/decline so validation runs first).
    """
    now = now or timezone.now()
    qs = Order.objects.filter(
        status=OrderStatus.PENDING,
        master_response_deadline__isnull=False,
        master_response_deadline__lt=now,
    )
    if skip_order_ids:
        qs = qs.exclude(pk__in=set(skip_order_ids))
    n = 0
    for order in qs.iterator():
        if order.order_type == OrderType.SOS and order.sos_offer_queue:
            # Mark pending offers as expired for acceptance-rate metrics.
            try:
                from apps.order.models import MasterOfferEvent, MasterOfferEventStatus

                MasterOfferEvent.objects.filter(
                    order_id=order.pk,
                    status=MasterOfferEventStatus.SENT,
                ).update(status=MasterOfferEventStatus.EXPIRED, responded_at=now)
            except Exception:  # noqa: BLE001
                pass
            advance_sos_ring_after_decline_or_timeout(order)
            n += 1
            continue
        if not order.master_id:
            continue
        # Standard: offer expired for this assigned master.
        try:
            from apps.order.models import MasterOfferEvent, MasterOfferEventStatus

            MasterOfferEvent.objects.filter(
                order_id=order.pk,
                master_id=order.master_id,
                status=MasterOfferEventStatus.SENT,
            ).update(status=MasterOfferEventStatus.EXPIRED, responded_at=now)
        except Exception:  # noqa: BLE001
            pass
        old_master_id = order.master_id
        order.status = OrderStatus.REJECTED
        order.master = None
        order.master_response_deadline = None
        order.save(update_fields=['status', 'master', 'master_response_deadline', 'updated_at'])
        # Push notifications: order expired (no accept in time).
        try:
            from apps.master.models import Master
            from apps.order.services.notifications import notify_master_order_kind, notify_user_order_kind

            extra = {'by': 'system'}
            notify_user_order_kind(order, kind='offer_expired', extra_data=extra)
            mu = Master.objects.select_related('user').only('id', 'user_id').get(pk=old_master_id)
            notify_master_order_kind(
                master_user_id=mu.user_id,
                order_id=order.id,
                kind='offer_expired',
                extra_data=extra,
            )
        except Exception:  # noqa: BLE001
            pass
        n += 1

    # Also handle SOS orders that were accepted but the master never departed.
    # This is a fallback path for environments where Celery ETA tasks are unreliable.
    n += sweep_accepted_no_departure(now=now)
    n += sweep_scheduled_mvp_deadlines(now=now)
    n += sweep_standard_accept_no_on_the_way(now=now)
    return n


def rebroadcast_stale_accepted_sos_no_departure(*, now=None, order_id: int) -> bool:
    """ETA task entry: SOS-only no-departure rebroadcast."""
    return bool(handle_accepted_no_departure_for_order(order_id=order_id, now=now))


def handle_accepted_no_departure_for_order(*, order_id: int, now=None) -> int:
    """
    Handle a single accepted order that might be stale (master did not depart).
    Returns 1 if updated, else 0.
    """
    return sweep_accepted_no_departure(now=now, order_id=order_id)


def sweep_accepted_no_departure(*, now=None, order_id: int | None = None) -> int:
    """
    If an order is accepted but the master did not mark "on the way" in time,
    take action:
    - SOS: re-broadcast to other masters (MVP: 5 minutes after accept)
    - Custom request: reset to pending and broadcast again to masters in radius
    - Standard (no scheduled slot): auto-cancel and notify
    - Standard (with preferred_date/time): handled by scheduled_mvp (start + 30 min)
    """
    now = now or timezone.now()
    qs = (
        Order.objects.filter(
            status=OrderStatus.ACCEPTED,
            on_the_way_at__isnull=True,
            accepted_at__isnull=False,
        )
        .select_related('master')
        .prefetch_related('category')
        .only(
            'id',
            'user_id',
            'master_id',
            'order_type',
            'latitude',
            'longitude',
            'accepted_at',
            'preferred_date',
            'preferred_time_start',
        )
    )
    if order_id is not None:
        qs = qs.filter(pk=int(order_id))
    touched = 0
    for order in qs.iterator(chunk_size=100):
        minutes = no_departure_cutoff_minutes_for_order(order)
        if minutes is None:
            continue
        if order.accepted_at is None or order.accepted_at > now - timedelta(minutes=minutes):
            continue
        if order.order_type == OrderType.SOS:
            if _handle_sos_no_departure(order, now):
                touched += 1
            continue
        if order.order_type == OrderType.CUSTOM_REQUEST:
            if _handle_custom_request_no_departure(order, now):
                touched += 1
            continue
        if order.order_type == OrderType.STANDARD:
            if order_has_scheduled_start(order):
                continue
            if _handle_standard_no_departure(order, now):
                touched += 1
    return touched


def _handle_sos_no_departure(order, now) -> bool:
    old_master_id = order.master_id
    if order.latitude is None or order.longitude is None:
        return False
    try:
        from apps.order.services.sos_master_queue import build_sos_master_id_queue
        from apps.categories.models import Category

        cat_ids = list(
            order.category.filter(type_category=Category.TypeCategory.BY_ORDER).values_list('id', flat=True)
        )
        queue = build_sos_master_id_queue(float(order.latitude), float(order.longitude), cat_ids)
        queue = filter_master_ids_meeting_emergency_thresholds(queue)
    except Exception:
        queue = []
    if not queue:
        return False
    if old_master_id:
        record_sos_no_departure_failure(master_id=old_master_id, order_id=order.pk)
    order.status = OrderStatus.PENDING
    order.master = None
    order.accepted_at = None
    order.master_response_deadline = None
    order.sos_offer_queue = queue
    order.sos_offer_index = 0
    order.sos_declined_master_ids = []
    order.save(
        update_fields=[
            'status',
            'master',
            'accepted_at',
            'master_response_deadline',
            'sos_offer_queue',
            'sos_offer_index',
            'sos_declined_master_ids',
            'updated_at',
        ]
    )
    try:
        from apps.order.services.master_offer import activate_pending_master_offer

        activate_pending_master_offer(order, request=None, send_push=True)
    except Exception:
        pass
    try:
        from apps.order.services.notifications import notify_master_order_kind, notify_user_order_kind
        from apps.master.models import Master

        extra = {'by': 'system'}
        notify_user_order_kind(order, kind='sos_rebroadcast', extra_data=extra)
        if old_master_id:
            mu = Master.objects.select_related('user').only('id', 'user_id').get(pk=old_master_id)
            notify_master_order_kind(
                master_user_id=mu.user_id,
                order_id=order.id,
                kind='sos_unassigned_no_departure',
                extra_data=extra,
            )
    except Exception:  # noqa: BLE001
        pass
    return True


def _handle_custom_request_no_departure(order, now) -> bool:
    old_master_id = order.master_id
    order.status = OrderStatus.PENDING
    order.master = None
    order.accepted_at = None
    order.master_response_deadline = None
    order.save(update_fields=['status', 'master', 'accepted_at', 'master_response_deadline', 'updated_at'])
    try:
        from apps.order.tasks import schedule_broadcast_custom_request

        schedule_broadcast_custom_request(order.pk)
    except Exception:
        pass
    try:
        from apps.order.services.notifications import notify_master_order_kind, notify_user_order_kind
        from apps.master.models import Master

        extra = {'by': 'system'}
        notify_user_order_kind(order, kind='custom_request_rebroadcast', extra_data=extra)
        if old_master_id:
            mu = Master.objects.select_related('user').only('id', 'user_id').get(pk=old_master_id)
            notify_master_order_kind(
                master_user_id=mu.user_id,
                order_id=order.id,
                kind='custom_request_unassigned_no_departure',
                extra_data=extra,
            )
    except Exception:  # noqa: BLE001
        pass
    return True


def _handle_standard_no_departure(order, now) -> bool:
    old_master_id = order.master_id
    if old_master_id:
        record_standard_no_departure_failure(master_id=old_master_id, order_id=order.pk)
    order.status = OrderStatus.CANCELLED
    order.auto_cancel_reason = 'master_no_departure'
    order.master = None
    order.accepted_at = None
    order.master_response_deadline = None
    order.save(
        update_fields=['status', 'auto_cancel_reason', 'master', 'accepted_at', 'master_response_deadline', 'updated_at']
    )
    try:
        from apps.order.services.notifications import notify_master_order_kind, notify_user_order_kind
        from apps.master.models import Master

        extra = {'by': 'system'}
        notify_user_order_kind(order, kind='auto_cancel_no_departure', extra_data=extra)
        if old_master_id:
            mu = Master.objects.select_related('user').only('id', 'user_id').get(pk=old_master_id)
            notify_master_order_kind(
                master_user_id=mu.user_id,
                order_id=order.id,
                kind='auto_cancel_no_departure',
                extra_data=extra,
            )
    except Exception:  # noqa: BLE001
        pass
    return True


def expire_master_offer_for_order(order_id: int, now=None) -> bool:
    """
    Expire a single pending offer if its deadline passed. Idempotent.
    Returns True if the order was updated.
    """
    now = now or timezone.now()
    try:
        order = Order.objects.get(pk=order_id)
    except Order.DoesNotExist:
        return False
    if (
        order.status != OrderStatus.PENDING
        or not order.master_response_deadline
        or order.master_response_deadline >= now
    ):
        return False
    if order.order_type == OrderType.SOS and order.sos_offer_queue:
        advance_sos_ring_after_decline_or_timeout(order)
        return True
    if not order.master_id:
        return False
    old_master_id = order.master_id
    order.status = OrderStatus.REJECTED
    order.master = None
    order.master_response_deadline = None
    order.save(update_fields=['status', 'master', 'master_response_deadline', 'updated_at'])
    # Push notifications: order expired (no accept in time).
    try:
        from apps.master.models import Master
        from apps.order.services.notifications import notify_master_order_kind, notify_user_order_kind

        extra = {'by': 'system'}
        notify_user_order_kind(order, kind='offer_expired', extra_data=extra)
        mu = Master.objects.select_related('user').only('id', 'user_id').get(pk=old_master_id)
        notify_master_order_kind(
            master_user_id=mu.user_id,
            order_id=order.id,
            kind='offer_expired',
            extra_data=extra,
        )
    except Exception:  # noqa: BLE001
        pass
    return True
