"""
App Store / Google Play review accounts: fixed OTP per test phone number.

Driver and Master can use separate phone + OTP pairs (see settings).
Legacy ``STORE_REVIEW_PHONES`` + ``STORE_REVIEW_OTP`` still works for any role.
"""
from __future__ import annotations

from django.conf import settings


def _normalize_phone(raw: str) -> str:
    from .services import SMSService

    return SMSService.format_phone_to_e164(raw.strip())


def _build_store_review_map() -> dict[str, dict[str, str | None]]:
    """
    phone_e164 -> {'otp': str, 'role': 'Driver'|'Master'|None}
    Role-specific entries override legacy list for the same phone.
    """
    out: dict[str, dict[str, str | None]] = {}

    legacy_otp = (getattr(settings, 'STORE_REVIEW_OTP', '') or '').strip()
    legacy_raw = getattr(settings, 'STORE_REVIEW_PHONES', '') or ''
    for part in legacy_raw.split(','):
        part = part.strip()
        if part and legacy_otp:
            out[_normalize_phone(part)] = {'otp': legacy_otp, 'role': None}

    role_pairs = (
        ('STORE_REVIEW_DRIVER_PHONE', 'STORE_REVIEW_DRIVER_OTP', 'Driver'),
        ('STORE_REVIEW_MASTER_PHONE', 'STORE_REVIEW_MASTER_OTP', 'Master'),
    )
    for phone_key, otp_key, role in role_pairs:
        phone = (getattr(settings, phone_key, '') or '').strip()
        otp = (getattr(settings, otp_key, '') or '').strip()
        if phone and otp:
            out[_normalize_phone(phone)] = {'otp': otp, 'role': role}

    return out


def get_store_review_config(phone_e164: str) -> dict[str, str | None] | None:
    return _build_store_review_map().get(phone_e164)


def is_store_review_phone(phone_e164: str) -> bool:
    return get_store_review_config(phone_e164) is not None


def get_store_review_otp_for_phone(phone_e164: str) -> str:
    cfg = get_store_review_config(phone_e164)
    if not cfg:
        return ''
    return str(cfg['otp'])


def validate_store_review_role(phone_e164: str, role: str | None) -> str | None:
    """Return error message if role is required but mismatched."""
    cfg = get_store_review_config(phone_e164)
    if not cfg:
        return None
    expected = cfg.get('role')
    if not expected or not role:
        return None
    if role != expected:
        return f'This test phone is for the {expected} app only. Use role={expected}.'
    return None


def is_store_review_otp_for_phone(phone_e164: str, code: str, role: str | None = None) -> bool:
    cfg = get_store_review_config(phone_e164)
    if not cfg:
        return False
    if str(code or '').strip() != str(cfg['otp']):
        return False
    expected_role = cfg.get('role')
    if expected_role and role and role != expected_role:
        return False
    return True


# Backward-compatible helpers (legacy single OTP for all phones).
def get_store_review_otp() -> str:
    return (getattr(settings, 'STORE_REVIEW_OTP', '') or '').strip()


def get_store_review_phones_normalized() -> set[str]:
    return set(_build_store_review_map().keys())


def is_store_review_otp(code: str) -> bool:
    code_s = str(code or '').strip()
    if not code_s:
        return False
    return any(str(cfg['otp']) == code_s for cfg in _build_store_review_map().values())
