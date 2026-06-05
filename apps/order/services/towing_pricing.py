"""Towing mileage pricing: base fee + per-mile rate + minimum total."""
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from django.conf import settings

from apps.master.models import Master, MasterTowingPricing
from apps.master.services.geo import MILES_TO_KM, haversine_distance_km, km_to_miles


def _q(x: Any) -> Decimal:
    return Decimal(str(x)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


def resolve_towing_distance_miles(
    *,
    pickup_lat: float,
    pickup_lon: float,
    delivery_lat: float | None = None,
    delivery_lon: float | None = None,
    distance_miles: Decimal | float | None = None,
) -> Decimal:
    """
    Client may send explicit ``distance_miles`` OR pickup + delivery coordinates.
    Explicit miles take precedence when > 0.
    """
    if distance_miles is not None:
        miles = _q(distance_miles)
        if miles > 0:
            return miles

    if delivery_lat is None or delivery_lon is None:
        raise ValueError('delivery coordinates or distance_miles required')

    km = haversine_distance_km(pickup_lat, pickup_lon, float(delivery_lat), float(delivery_lon))
    miles = _q(km_to_miles(km))
    if miles <= 0:
        raise ValueError('distance must be greater than zero')
    return miles


def calculate_towing_price(
    *,
    base_fee: Decimal,
    price_per_mile: Decimal,
    minimum_fee: Decimal,
    distance_miles: Decimal,
) -> dict[str, str]:
    """Return breakdown with string decimals for API responses."""
    base = _q(base_fee)
    rate = _q(price_per_mile)
    minimum = _q(minimum_fee)
    miles = _q(distance_miles)
    mileage_charge = _q(miles * rate)
    calculated = _q(base + mileage_charge)
    total = calculated if calculated >= minimum else minimum
    return {
        'distance_miles': format(miles, 'f'),
        'base_fee': format(base, 'f'),
        'price_per_mile': format(rate, 'f'),
        'minimum_fee': format(minimum, 'f'),
        'mileage_charge': format(mileage_charge, 'f'),
        'calculated_total': format(calculated, 'f'),
        'total_price': format(total, 'f'),
    }


def master_ids_within_towing_radius(
    latitude: float,
    longitude: float,
    *,
    radius_miles: float | None = None,
) -> list[int]:
    """Masters with active towing pricing within radius of pickup point."""
    miles = float(
        radius_miles
        if radius_miles is not None
        else getattr(settings, 'TOWING_ESTIMATE_RADIUS_MILES', 50)
    )
    limit_km = miles * MILES_TO_KM

    priced_master_ids = set(
        MasterTowingPricing.objects.filter(is_active=True, base_fee__gt=0)
        .values_list('master_id', flat=True)
    )
    if not priced_master_ids:
        return []

    masters = Master.objects.filter(
        id__in=priced_master_ids,
        latitude__isnull=False,
        longitude__isnull=False,
    ).only('id', 'latitude', 'longitude')

    out: list[int] = []
    for m in masters.iterator(chunk_size=200):
        mlat, mlon = m.get_work_location_for_distance()
        if mlat is None:
            continue
        if haversine_distance_km(latitude, longitude, float(mlat), float(mlon)) <= limit_km:
            out.append(m.id)
    return out


def build_towing_estimates_for_masters(
    *,
    pickup_lat: float,
    pickup_lon: float,
    delivery_lat: float | None = None,
    delivery_lon: float | None = None,
    distance_miles: Decimal | float | None = None,
    radius_miles: float | None = None,
    request=None,
) -> dict[str, Any]:
    """Estimate towing price for each eligible master near pickup."""
    from apps.master.api.serializers import MasterNearbySerializer

    serializer_context = {'request': request} if request is not None else {}

    miles = resolve_towing_distance_miles(
        pickup_lat=pickup_lat,
        pickup_lon=pickup_lon,
        delivery_lat=delivery_lat,
        delivery_lon=delivery_lon,
        distance_miles=distance_miles,
    )

    master_ids = master_ids_within_towing_radius(pickup_lat, pickup_lon, radius_miles=radius_miles)
    pricing_map = {
        p.master_id: p
        for p in MasterTowingPricing.objects.filter(master_id__in=master_ids, is_active=True)
    }

    masters = (
        Master.objects.filter(id__in=master_ids)
        .select_related('user')
        .order_by('id')
    )

    results: list[dict[str, Any]] = []
    for master in masters:
        pricing = pricing_map.get(master.id)
        if not pricing:
            continue
        breakdown = calculate_towing_price(
            base_fee=pricing.base_fee,
            price_per_mile=pricing.price_per_mile,
            minimum_fee=pricing.minimum_fee,
            distance_miles=miles,
        )
        wlat, wlon = master.get_work_location_for_distance()
        distance_to_pickup_mi = None
        if wlat is not None:
            km = haversine_distance_km(pickup_lat, pickup_lon, wlat, wlon)
            distance_to_pickup_mi = round(km_to_miles(km), 2)

        results.append(
            {
                'master_id': master.id,
                'master': MasterNearbySerializer(master, context=serializer_context).data,
                'distance_to_pickup_miles': distance_to_pickup_mi,
                'pricing': breakdown,
            }
        )

    results.sort(
        key=lambda x: (
            x['distance_to_pickup_miles'] is None,
            x['distance_to_pickup_miles'] or 9999,
            float(x['pricing']['total_price']),
        )
    )

    return {
        'distance_miles': format(miles, 'f'),
        'master_count': len(results),
        'masters': results,
    }
