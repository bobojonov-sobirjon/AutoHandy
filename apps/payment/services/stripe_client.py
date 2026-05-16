"""Stripe API key wrapper."""
from __future__ import annotations

from django.conf import settings


def stripe_sdk():
    import stripe

    key = getattr(settings, 'STRIPE_SECRET_KEY', '') or ''
    stripe.api_key = key
    return stripe


def stripe_configured() -> bool:
    return bool((getattr(settings, 'STRIPE_SECRET_KEY', '') or '').strip())
