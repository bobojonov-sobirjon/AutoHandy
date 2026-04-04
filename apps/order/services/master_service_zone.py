"""Order location vs master map pin + acceptance radius (15/45/100 mi or default)."""
from __future__ import annotations

from typing import TYPE_CHECKING

from apps.master.services.geo import haversine_distance_km
from apps.master.models import Master

if TYPE_CHECKING:
    from apps.order.models import Order


def order_within_master_acceptance_zone(order: 'Order', master_pk: int) -> bool:
    """
    True if order coordinates lie inside the master's work zone
    (distance from order to master's pin <= max_order_distance_km).
    """
    if order.latitude is None or order.longitude is None:
        return False
    try:
        master = Master.objects.get(pk=master_pk)
    except Master.DoesNotExist:
        return False
    wlat, wlon = master.get_work_location_for_distance()
    if wlat is None:
        return False
    dist_km = haversine_distance_km(
        float(order.latitude),
        float(order.longitude),
        wlat,
        wlon,
    )
    return dist_km <= float(master.max_order_distance_km())
