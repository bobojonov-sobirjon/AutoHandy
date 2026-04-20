"""Shared geodesic helpers for master service area and distance checks."""
from __future__ import annotations

import math

R_EARTH_KM = 6371.0
MILES_TO_KM = 1.609344
KM_TO_MILES = 1.0 / MILES_TO_KM


def km_to_miles(km: float) -> float:
    """Convert kilometers to statute miles (same basis as ``MILES_TO_KM``)."""
    return km * KM_TO_MILES


def haversine_distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in kilometers (WGS84 sphere approximation)."""
    lat1_rad = math.radians(lat1)
    lon1_rad = math.radians(lon1)
    lat2_rad = math.radians(lat2)
    lon2_rad = math.radians(lon2)
    dlat = lat2_rad - lat1_rad
    dlon = lon2_rad - lon1_rad
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(dlon / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R_EARTH_KM * c


def haversine_distance_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in meters."""
    return haversine_distance_km(lat1, lon1, lat2, lon2) * 1000.0
