"""Towing mileage pricing per driver-selected service type."""
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from django.conf import settings
from django.db.models import Q

from apps.master.models import Master, MasterTowingPricing
from apps.master.services.geo import MILES_TO_KM, haversine_distance_km, km_to_miles
from apps.master.towing_types import (
    ALL_TOWING_SERVICE_TYPES,
    TOWING_SERVICE_TYPE_LABELS,
    TowingServiceType,
)


def _q(x: Any) -> Decimal:
    return Decimal(str(x)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


def normalize_towing_service_type(value: str) -> str:
    raw = (value or '').strip().lower()
    if raw not in ALL_TOWING_SERVICE_TYPES:
        raise ValueError(
            f'Invalid service_type. Use one of: {", ".join(ALL_TOWING_SERVICE_TYPES)}'
        )
    return raw


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
    service_type: str | None = None,
) -> dict[str, str]:
    """Return breakdown with string decimals for API responses."""
    base = _q(base_fee)
    rate = _q(price_per_mile)
    minimum = _q(minimum_fee)
    miles = _q(distance_miles)
    mileage_charge = _q(miles * rate)
    calculated = _q(base + mileage_charge)
    total = calculated if calculated >= minimum else minimum
    payload = {
        'distance_miles': format(miles, 'f'),
        'base_fee': format(base, 'f'),
        'price_per_mile': format(rate, 'f'),
        'minimum_fee': format(minimum, 'f'),
        'mileage_charge': format(mileage_charge, 'f'),
        'calculated_total': format(calculated, 'f'),
        'total_price': format(total, 'f'),
    }
    if service_type:
        payload['service_type'] = service_type
        payload['trip_type'] = service_type  # backward compat for older clients
    return payload


def calculate_towing_price_for_service(
    pricing: MasterTowingPricing,
    distance_miles: Decimal,
) -> dict[str, str]:
    """Price breakdown for a specific master service-type row."""
    return calculate_towing_price(
        base_fee=pricing.base_fee,
        price_per_mile=pricing.price_per_mile,
        minimum_fee=pricing.minimum_fee,
        distance_miles=distance_miles,
        service_type=pricing.service_type,
    )


def default_service_pricing_item(service_type: str) -> dict[str, Any]:
    return {
        'service_type': service_type,
        'label': TOWING_SERVICE_TYPE_LABELS.get(service_type, service_type),
        'base_fee': '0.00',
        'price_per_mile': '0.00',
        'minimum_fee': '0.00',
        'is_active': False,
        'configured': False,
    }


def build_master_towing_pricing_payload(
    master_id: int,
    items: list[MasterTowingPricing] | None = None,
) -> dict[str, Any]:
    """All towing service types for workshop / master API."""
    by_type = {p.service_type: p for p in (items or [])}
    services: list[dict[str, Any]] = []
    configured_any = False
    for service_type in ALL_TOWING_SERVICE_TYPES:
        row = by_type.get(service_type)
        if row is None:
            services.append(default_service_pricing_item(service_type))
            continue
        configured = row.has_configured_rates()
        configured_any = configured_any or configured
        services.append(
            {
                'service_type': service_type,
                'label': TOWING_SERVICE_TYPE_LABELS.get(service_type, service_type),
                'base_fee': format(_q(row.base_fee), 'f'),
                'price_per_mile': format(_q(row.price_per_mile), 'f'),
                'minimum_fee': format(_q(row.minimum_fee), 'f'),
                'is_active': row.is_active,
                'configured': configured,
                'created_at': row.created_at,
                'updated_at': row.updated_at,
            }
        )
    return {
        'master_id': master_id,
        'configured': configured_any,
        'services': services,
    }


def master_ids_with_towing_service(
    service_type: str,
    latitude: float,
    longitude: float,
    *,
    radius_miles: float | None = None,
) -> list[int]:
    """Masters with active pricing for the selected towing service type near pickup."""
    service_type = normalize_towing_service_type(service_type)
    miles = float(
        radius_miles
        if radius_miles is not None
        else getattr(settings, 'TOWING_ESTIMATE_RADIUS_MILES', 50)
    )
    limit_km = miles * MILES_TO_KM

    priced_master_ids = set(
        MasterTowingPricing.objects.filter(
            service_type=service_type,
            is_active=True,
        )
        .filter(Q(base_fee__gt=0) | Q(price_per_mile__gt=0))
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
    service_type: str,
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

    service_type = normalize_towing_service_type(service_type)
    serializer_context = {'request': request} if request is not None else {}

    miles = resolve_towing_distance_miles(
        pickup_lat=pickup_lat,
        pickup_lon=pickup_lon,
        delivery_lat=delivery_lat,
        delivery_lon=delivery_lon,
        distance_miles=distance_miles,
    )

    master_ids = master_ids_with_towing_service(
        service_type,
        pickup_lat,
        pickup_lon,
        radius_miles=radius_miles,
    )
    pricing_map = {
        p.master_id: p
        for p in MasterTowingPricing.objects.filter(
            master_id__in=master_ids,
            service_type=service_type,
            is_active=True,
        ).filter(Q(base_fee__gt=0) | Q(price_per_mile__gt=0))
    }

    masters = (
        Master.objects.filter(id__in=master_ids)
        .select_related('user')
        .order_by('id')
    )

    results: list[dict[str, Any]] = []
    for master in masters:
        pricing = pricing_map.get(master.id)
        if not pricing or not pricing.has_configured_rates():
            continue
        breakdown = calculate_towing_price_for_service(pricing, miles)
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
        'service_type': service_type,
        'service_label': TOWING_SERVICE_TYPE_LABELS.get(service_type, service_type),
        'distance_miles': format(miles, 'f'),
        'trip_type': service_type,  # backward compat
        'master_count': len(results),
        'masters': results,
    }
