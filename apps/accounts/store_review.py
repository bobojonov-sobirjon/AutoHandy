"""
App Store / Google Play review accounts: fixed OTP for configured phone numbers.
"""
from django.conf import settings


def get_store_review_otp() -> str:
    return (getattr(settings, 'STORE_REVIEW_OTP', '') or '').strip()


def get_store_review_phones_normalized() -> set:
    from .services import SMSService

    raw = getattr(settings, 'STORE_REVIEW_PHONES', '') or ''
    phones = set()
    for part in raw.split(','):
        part = part.strip()
        if part:
            phones.add(SMSService.format_phone_to_e164(part))
    return phones


def is_store_review_phone(phone_e164: str) -> bool:
    if not get_store_review_otp():
        return False
    phones = get_store_review_phones_normalized()
    if not phones:
        return False
    return phone_e164 in phones


def is_store_review_otp(code: str) -> bool:
    expected = get_store_review_otp()
    if not expected:
        return False
    return str(code or '').strip() == expected
