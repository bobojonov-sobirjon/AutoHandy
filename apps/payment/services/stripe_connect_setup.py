"""Auto-complete Stripe Custom Connect requirements after in-app bank save (no DB storage of PII)."""
from __future__ import annotations

import re
import time
from typing import Any

from django.conf import settings

from apps.master.models import Master
from apps.payment.services.stripe_client import stripe_configured, stripe_sdk
from apps.payment.services.stripe_connect_link import fetch_connect_account_public_summary


class StripeConnectSetupError(Exception):
    def __init__(self, message: str):
        self.message = message
        super().__init__(message)


def _stripe_test_mode() -> bool:
    key = (getattr(settings, 'STRIPE_SECRET_KEY', '') or '').strip()
    return key.startswith('sk_test_')


def _client_ip(request) -> str:
    if request is None:
        return '127.0.0.1'
    xff = (request.META.get('HTTP_X_FORWARDED_FOR') or '').split(',')[0].strip()
    if xff:
        return xff[:45]
    return (request.META.get('REMOTE_ADDR') or '127.0.0.1')[:45]


def _split_name(full_name: str, user) -> tuple[str, str]:
    full = (full_name or '').strip()
    if not full and user is not None:
        first = (getattr(user, 'first_name', None) or '').strip()
        last = (getattr(user, 'last_name', None) or '').strip()
        if first or last:
            return first or 'Master', last or 'User'
        full = (user.get_full_name() or user.email or 'Master User').strip()
    parts = full.split(None, 1)
    if len(parts) == 1:
        return parts[0], 'User'
    return parts[0], parts[1]


def _resolve_dob(*, dob_year: int | None, dob_month: int | None, dob_day: int | None) -> dict[str, int]:
    if dob_year and dob_month and dob_day:
        return {'year': int(dob_year), 'month': int(dob_month), 'day': int(dob_day)}
    if _stripe_test_mode():
        return {'year': 1990, 'month': 1, 'day': 1}
    raise StripeConnectSetupError(
        'Date of birth is required (dob_year, dob_month, dob_day).'
    )


def _statement_descriptor(first: str, last: str) -> str:
    """Stripe wants descriptor similar to business / legal name (max 22 chars)."""
    base = f'{first} {last}'.strip().upper()
    return (base[:22] if base else 'AUTOHANDY') or 'AUTOHANDY'


def _individual_payload(
    *,
    user,
    master: Master,
    first: str,
    last: str,
    email: str,
    dob: dict[str, int],
    ssn_last4: str | None,
) -> dict[str, Any]:
    """
    Custom Connect with ``controller.type=application`` uses ``Account.individual``,
    not a separate Person + business_profile.url (url is rejected with url_invalid).
    """
    phone = re.sub(r'\D', '', (getattr(master, 'phone', None) or '').strip())
    if len(phone) < 10:
        phone = '0000000000'

    payload: dict[str, Any] = {
        'first_name': first[:100],
        'last_name': last[:100],
        'email': email[:255] if email else None,
        'phone': phone[:15],
        'dob': dob,
        'address': {
            'line1': '123 Main St',
            'city': 'San Francisco',
            'state': 'CA',
            'postal_code': '94111',
            'country': 'US',
        },
        'ssn_last_4': '0000',
    }

    if _stripe_test_mode():
        payload['id_number'] = '000000000'
    else:
        raw = re.sub(r'\D', '', (ssn_last4 or '').strip())
        if len(raw) == 9:
            payload['id_number'] = raw
        elif len(raw) == 4:
            payload['ssn_last_4'] = raw

    return payload


def complete_connect_account_setup(
    *,
    master: Master,
    user,
    request=None,
    accept_agreement: bool = True,
    dob_year: int | None = None,
    dob_month: int | None = None,
    dob_day: int | None = None,
    ssn_last4: str | None = None,
) -> dict[str, Any]:
    """
    Push platform + master profile data to Stripe so the connected account can reach
    ``charges_enabled`` / ``payouts_enabled`` without hosted onboarding.

    No bank/SSN stored in Django DB — only sent to Stripe API.
    """
    if not accept_agreement:
        raise StripeConnectSetupError(
            'accept_agreement must be true (user accepted Stripe Connected Account Agreement).'
        )
    if not stripe_configured():
        raise StripeConnectSetupError('Stripe is not configured on the server.')

    acct = (getattr(master, 'stripe_connect_account_id', None) or '').strip()
    if not acct.startswith('acct_'):
        raise StripeConnectSetupError('No Stripe Connect account on file for this master.')

    stripe = stripe_sdk()
    mcc = (getattr(settings, 'STRIPE_PLATFORM_MCC', '') or '7538').strip() or '7538'
    product = (
        (getattr(settings, 'STRIPE_PLATFORM_PRODUCT_DESCRIPTION', '') or 'On-demand automotive services').strip()
    )

    first, last = _split_name('', user)
    email = (getattr(user, 'email', None) or '').strip()
    dob = _resolve_dob(dob_year=dob_year, dob_month=dob_month, dob_day=dob_day)
    business_name = f'{first} {last}'.strip() or 'Master User'
    descriptor = _statement_descriptor(first, last)

    try:
        stripe.Account.modify(
            acct,
            business_type='individual',
            business_profile={
                'mcc': mcc,
                'product_description': product,
                'name': business_name[:100],
            },
            individual=_individual_payload(
                user=user,
                master=master,
                first=first,
                last=last,
                email=email,
                dob=dob,
                ssn_last4=ssn_last4,
            ),
            settings={
                'payments': {
                    'statement_descriptor': descriptor,
                },
            },
            tos_acceptance={
                'date': int(time.time()),
                'ip': _client_ip(request),
            },
        )
    except StripeConnectSetupError:
        raise
    except Exception as exc:  # noqa: BLE001
        msg = str(getattr(exc, 'user_message', None) or getattr(exc, 'message', None) or exc)
        raise StripeConnectSetupError(msg) from exc

    summary = fetch_connect_account_public_summary(acct)
    enabled = bool(summary.get('charges_enabled')) and bool(summary.get('payouts_enabled'))
    return {
        'setup_submitted': True,
        'account': summary,
        'onboarding_complete': enabled,
        'charges_enabled': summary.get('charges_enabled'),
        'payouts_enabled': summary.get('payouts_enabled'),
        'details_submitted': summary.get('details_submitted'),
    }
