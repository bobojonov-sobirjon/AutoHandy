"""Customer-facing display names (first name + last initial only)."""
from __future__ import annotations

from typing import Any, Mapping, MutableMapping, Optional


def _last_name_initial(last_name: str) -> str:
    last = (last_name or '').strip()
    if not last:
        return ''
    initial = last[0]
    if initial.isalpha() and initial.isascii():
        initial = initial.upper()
    return initial


def customer_display_name(
    first_name: Optional[str],
    last_name: Optional[str],
    *,
    fallback: str = '',
) -> str:
    """
    Build privacy-safe name: "Anton K", "John W", "Антон К" (no full surname).
    """
    first = (first_name or '').strip()
    last = (last_name or '').strip()
    if first and last:
        return f'{first} {_last_name_initial(last)}'
    if first:
        return first
    if last:
        return _last_name_initial(last)
    return fallback


def should_mask_master_name_for_request(request, master_user_id: Optional[int]) -> bool:
    """
    Mask master identity for everyone except the master viewing their own profile.
    """
    if master_user_id is None:
        return True
    if not request:
        return True
    user = getattr(request, 'user', None)
    if not user or not getattr(user, 'is_authenticated', False):
        return True
    return user.id != master_user_id


def masked_master_full_name(user, *, fallback: Optional[str] = None) -> str:
    fb = fallback
    if fb is None:
        fb = (getattr(user, 'phone_number', None) or getattr(user, 'email', None) or '')
    return customer_display_name(
        getattr(user, 'first_name', None),
        getattr(user, 'last_name', None),
        fallback=fb or '',
    )


def apply_customer_name_privacy_to_user_data(
    data: Mapping[str, Any],
    user,
) -> dict[str, Any]:
    """Return user payload with masked first/last + display_name for customers."""
    out = dict(data)
    first = getattr(user, 'first_name', None) or out.get('first_name') or ''
    last = getattr(user, 'last_name', None) or out.get('last_name') or ''
    fallback = (
        out.get('phone_number')
        or out.get('email')
        or getattr(user, 'phone_number', None)
        or getattr(user, 'email', None)
        or ''
    )
    display = customer_display_name(first, last, fallback=str(fallback))
    out['display_name'] = display
    out['first_name'] = (first or '').strip()
    last_stripped = (last or '').strip()
    out['last_name'] = _last_name_initial(last_stripped) if last_stripped else ''
    if 'full_name' in out:
        out['full_name'] = display or None
    return out


def build_compact_master_user_payload(
    master,
    request,
    *,
    media_url_fn,
) -> dict[str, Any]:
    """Minimal master user block for order request serializers."""
    u = getattr(master, 'user', None)
    avatar = None
    full_name = None
    if u is not None:
        full_name = resolve_master_full_name_for_request(
            u, request, master_user_id=getattr(master, 'user_id', None)
        )
        avatar = media_url_fn(request, getattr(u, 'avatar', None))
    return {
        'id': getattr(master, 'id', None),
        'user_id': getattr(master, 'user_id', None),
        'full_name': full_name,
        'avatar': avatar,
    }


def resolve_master_full_name_for_request(user, request, *, master_user_id: Optional[int] = None) -> str:
    uid = master_user_id if master_user_id is not None else getattr(user, 'id', None)
    try:
        raw = user.get_full_name() or getattr(user, 'email', None) or getattr(user, 'phone_number', None)
    except Exception:  # noqa: BLE001
        raw = getattr(user, 'email', None) or getattr(user, 'phone_number', None)
    raw = (raw or '').strip()
    if should_mask_master_name_for_request(request, uid):
        return masked_master_full_name(user, fallback=raw)
    return raw
