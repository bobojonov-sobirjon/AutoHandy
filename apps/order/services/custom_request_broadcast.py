"""Geographic broadcast list for custom-request orders (fixed radius in miles)."""
from __future__ import annotations

from django.conf import settings

from apps.categories.models import Category
from apps.master.models import Master
from apps.master.services.geo import MILES_TO_KM, haversine_distance_km


def get_custom_request_catalog_category() -> Category | None:
    """Main category flagged as the client-only custom request entry (by_order)."""
    return (
        Category.objects.filter(
            is_custom_request_entry=True,
            parent__isnull=True,
            type_category=Category.TypeCategory.BY_ORDER,
        )
        .order_by('id')
        .first()
    )


def master_ids_within_custom_request_radius(
    latitude: float,
    longitude: float,
    *,
    radius_miles: float | None = None,
) -> list[int]:
    """
    Masters with map coordinates within ``radius_miles`` of the client point (great-circle),
    unordered. Uses each master's work location (same helper as SOS distance).
    """
    miles = float(
        radius_miles
        if radius_miles is not None
        else getattr(settings, 'CUSTOM_REQUEST_BROADCAST_RADIUS_MILES', 10)
    )
    limit_km = miles * MILES_TO_KM

    masters = Master.objects.filter(latitude__isnull=False, longitude__isnull=False).only(
        'id',
        'latitude',
        'longitude',
    )
    out: list[int] = []
    for m in masters.iterator(chunk_size=200):
        mlat, mlon = m.get_work_location_for_distance()
        if mlat is None:
            continue
        if haversine_distance_km(latitude, longitude, float(mlat), float(mlon)) <= limit_km:
            out.append(m.id)
    return out


def master_within_custom_request_radius(
    master: Master,
    latitude: float,
    longitude: float,
    *,
    radius_miles: float | None = None,
) -> bool:
    mlat, mlon = master.get_work_location_for_distance()
    if mlat is None:
        return False
    miles = float(
        radius_miles
        if radius_miles is not None
        else getattr(settings, 'CUSTOM_REQUEST_BROADCAST_RADIUS_MILES', 10)
    )
    limit_km = miles * MILES_TO_KM
    return haversine_distance_km(latitude, longitude, float(mlat), float(mlon)) <= limit_km
