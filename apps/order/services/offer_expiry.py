"""Expire master response offers that were not accepted within the deadline."""
from __future__ import annotations

from typing import Container

from django.utils import timezone

from apps.order.models import Order, OrderStatus, OrderType
from apps.order.services.sos_rotation import advance_sos_ring_after_decline_or_timeout


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
            advance_sos_ring_after_decline_or_timeout(order)
            n += 1
            continue
        if not order.master_id:
            continue
        old_master_id = order.master_id
        order.status = OrderStatus.REJECTED
        order.master = None
        order.master_response_deadline = None
        order.save(update_fields=['status', 'master', 'master_response_deadline', 'updated_at'])
        # Push notifications: order expired (no accept in time).
        try:
            from apps.master.models import Master
            from apps.order.services.notifications import notify_master_order_event, notify_user_order_event

            notify_user_order_event(
                order,
                title='Order expired',
                body=f'Order #{order.id}: no master accepted in time. Please choose another master or create a new request.',
                kind='offer_expired',
                extra_data={'by': 'system'},
            )
            mu = Master.objects.select_related('user').only('id', 'user_id').get(pk=old_master_id)
            notify_master_order_event(
                master_user_id=mu.user_id,
                order_id=order.id,
                title='Offer expired',
                body=f'Order #{order.id}: the response window ended.',
                kind='offer_expired',
                extra_data={'by': 'system'},
            )
        except Exception:  # noqa: BLE001
            pass
        n += 1
    return n


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
        from apps.order.services.notifications import notify_master_order_event, notify_user_order_event

        notify_user_order_event(
            order,
            title='Order expired',
            body=f'Order #{order.id}: no master accepted in time. Please choose another master or create a new request.',
            kind='offer_expired',
            extra_data={'by': 'system'},
        )
        mu = Master.objects.select_related('user').only('id', 'user_id').get(pk=old_master_id)
        notify_master_order_event(
            master_user_id=mu.user_id,
            order_id=order.id,
            title='Offer expired',
            body=f'Order #{order.id}: the response window ended.',
            kind='offer_expired',
            extra_data={'by': 'system'},
        )
    except Exception:  # noqa: BLE001
        pass
    return True
