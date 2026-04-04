"""Client location privacy: approximate coords until master accepts the order."""
from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from django.contrib.auth.models import AbstractBaseUser

    from apps.order.models import Order


def _order_type_sos_pending(order: 'Order') -> bool:
    from apps.order.models import OrderStatus, OrderType

    return order.order_type == OrderType.SOS and order.status == OrderStatus.PENDING


def approximate_lat_lon(lat: float, lon: float, order_id: int, version: str = 'v1') -> tuple[float, float]:
    """Deterministic ~2–4 km offset so the same order always maps to the same fuzzy point."""
    h = hashlib.sha256(f'{version}-{order_id}'.encode()).digest()
    # ~0.035° lat ≈ 3–4 km mid-latitudes
    dlat = (int.from_bytes(h[0:4], 'big') / 2**32 - 0.5) * 0.07
    dlon = (int.from_bytes(h[4:8], 'big') / 2**32 - 0.5) * 0.07
    return round(lat + dlat, 5), round(lon + dlon, 5)


def viewer_is_current_sos_offered_master(order: 'Order', user: 'AbstractBaseUser | None') -> bool:
    """True if this master is the one currently offered the SOS ring (order.master may still be null)."""
    if not _order_type_sos_pending(order):
        return False
    if not user or not user.is_authenticated:
        return False
    q = order.sos_offer_queue or []
    idx = int(order.sos_offer_index or 0)
    if idx >= len(q):
        return False
    try:
        mid = int(q[idx])
    except (TypeError, ValueError):
        return False
    return user.master_profiles.filter(pk=mid).exists()


def viewer_is_assigned_master(order: 'Order', user: 'AbstractBaseUser | None') -> bool:
    if not user or not user.is_authenticated or not order.master_id:
        return False
    master = getattr(user, 'master_profiles', None)
    if master is None:
        return False
    return master.filter(pk=order.master_id).exists()


def viewer_is_master_user(user: 'AbstractBaseUser | None') -> bool:
    if not user or not user.is_authenticated:
        return False
    return getattr(user, 'master_profiles', None) and user.master_profiles.exists()


def should_redact_exact_client_location(order: 'Order', user: 'AbstractBaseUser | None') -> bool:
    """
    Master sees blurred location until the order is accepted (accepted_at set).
    Client (order owner) always sees exact data.
    """
    if not user or not user.is_authenticated:
        return False
    if order.user_id == user.id:
        return False
    if order.accepted_at:
        return False
    if viewer_is_current_sos_offered_master(order, user):
        return False
    if viewer_is_assigned_master(order, user):
        return True
    if order.master_id is None and viewer_is_master_user(user):
        return True
    return False
