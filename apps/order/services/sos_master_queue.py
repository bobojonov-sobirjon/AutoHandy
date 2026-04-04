"""Build nearest-master queue for SOS orders (by_order service + distance)."""
from __future__ import annotations

from django.db.models import Q

from apps.categories.models import Category
from apps.master.services.geo import haversine_distance_km
from apps.master.models import Master


def build_sos_master_id_queue(
    latitude: float,
    longitude: float,
    category_ids: list[int],
) -> list[int]:
    """
    Masters that have at least one MasterServiceItems for selected by_order categories,
    sorted by distance (km) from client. Each master's own acceptance radius applies
    (map pin + 15/45/100 mi or default 50 km).
    """
    by_order_ids = list(
        Category.objects.filter(
            id__in=category_ids,
            type_category=Category.TypeCategory.BY_ORDER,
        ).values_list('id', flat=True)
    )
    if not by_order_ids:
        return []

    q_items = Q()
    for cid in by_order_ids:
        q_items |= Q(master_services__master_service_items__category_id=cid)

    masters = (
        Master.objects.filter(q_items)
        .filter(latitude__isnull=False, longitude__isnull=False)
        .distinct()
    )

    ranked: list[tuple[float, int]] = []
    for m in masters.iterator(chunk_size=100):
        mlat, mlon = m.get_work_location_for_distance()
        if mlat is None:
            continue
        dist_km = haversine_distance_km(latitude, longitude, mlat, mlon)
        max_km = float(m.max_order_distance_km())
        if dist_km <= max_km:
            ranked.append((dist_km, m.id))

    ranked.sort(key=lambda x: x[0])
    seen: set[int] = set()
    out: list[int] = []
    for _, mid in ranked:
        if mid not in seen:
            seen.add(mid)
            out.append(mid)
    return out
