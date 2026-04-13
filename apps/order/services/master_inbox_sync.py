"""REST sync for masters when WebSocket was offline (open custom-request jobs)."""
from __future__ import annotations

from django.db.models import Q
from django.utils import timezone

from apps.master.models import Master
from apps.order.models import Order, OrderStatus, OrderType
from apps.order.services.custom_request_broadcast import master_within_custom_request_radius


def pending_custom_request_order_ids_for_master(master: Master, *, now=None) -> list[int]:
    """
    Open custom-request jobs matching WebSocket geo broadcast: pending, unassigned,
    not past ``expiration_time``, within ``CUSTOM_REQUEST_BROADCAST_RADIUS_MILES``.
    """
    now = now or timezone.now()
    wlat, wlon = master.get_work_location_for_distance()
    if wlat is None:
        return []

    qs = (
        Order.objects.filter(
            order_type=OrderType.CUSTOM_REQUEST,
            status=OrderStatus.PENDING,
            master__isnull=True,
            latitude__isnull=False,
            longitude__isnull=False,
        )
        .filter(Q(expiration_time__isnull=True) | Q(expiration_time__gt=now))
        .only('id', 'latitude', 'longitude')
    )
    out: list[int] = []
    for order in qs.iterator(chunk_size=200):
        if master_within_custom_request_radius(master, float(order.latitude), float(order.longitude)):
            out.append(order.pk)
    return out


def pending_assigned_standard_order_ids_for_master(master_id: int, *, now=None) -> list[int]:
    """
    Standard orders where the client already chose this master (FK set) but the master has not
    accepted yet: ``pending`` only. Offer window: no deadline yet or ``master_response_deadline``
    still in the future (same notion as ``expire_stale_master_offers`` for assigned standard).
    """
    now = now or timezone.now()
    return list(
        Order.objects.filter(
            order_type=OrderType.STANDARD,
            status=OrderStatus.PENDING,
            master_id=master_id,
        )
        .filter(Q(master_response_deadline__isnull=True) | Q(master_response_deadline__gt=now))
        .order_by('master_response_deadline', 'id')
        .values_list('id', flat=True)
    )
