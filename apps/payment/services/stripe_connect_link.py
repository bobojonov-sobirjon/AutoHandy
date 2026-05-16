"""Verify a Stripe Connect account id belongs to the platform, for master linking."""
from __future__ import annotations

from typing import Any

from apps.payment.services.stripe_client import stripe_configured, stripe_sdk


class StripeConnectLinkError(Exception):
    def __init__(self, message: str):
        self.message = message
        super().__init__(message)


def _normalize_acct(raw: str) -> str:
    s = (raw or '').strip()
    if not s:
        raise StripeConnectLinkError('stripe_connect_account_id is required.')
    if not s.startswith('acct_'):
        raise StripeConnectLinkError('stripe_connect_account_id must look like acct_…')
    if len(s) > 64 or len(s) < 6:
        raise StripeConnectLinkError('Invalid stripe_connect_account_id length.')
    return s


def fetch_connect_account_public_summary(account_id: str) -> dict[str, Any]:
    """
    Retrieve connected account metadata (platform secret key).
    Raises StripeConnectLinkError if Stripe is off or account is unknown / not on this platform.
    """
    if not stripe_configured():
        raise StripeConnectLinkError('Stripe is not configured on the server.')
    acct = _normalize_acct(account_id)
    stripe = stripe_sdk()
    try:
        a = stripe.Account.retrieve(acct)
    except Exception as exc:  # noqa: BLE001
        msg = str(getattr(exc, 'user_message', None) or getattr(exc, 'message', None) or exc)
        raise StripeConnectLinkError(msg) from exc

    return {
        'id': getattr(a, 'id', acct) or acct,
        'charges_enabled': bool(getattr(a, 'charges_enabled', False)),
        'payouts_enabled': bool(getattr(a, 'payouts_enabled', False)),
        'details_submitted': bool(getattr(a, 'details_submitted', False)),
        'country': getattr(a, 'country', None) or '',
        'default_currency': getattr(a, 'default_currency', None) or '',
    }
