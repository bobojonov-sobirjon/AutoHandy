"""Stripe Connect external bank accounts for master payouts (US ACH)."""
from __future__ import annotations

import re
from typing import Any

from apps.master.models import Master
from apps.payment.services.stripe_client import stripe_configured, stripe_sdk
from apps.payment.services.stripe_connect_link import StripeConnectLinkError, fetch_connect_account_public_summary
from apps.payment.services.stripe_connect_onboarding import ensure_express_connect_account_for_master


class StripeConnectBankError(Exception):
    def __init__(self, message: str):
        self.message = message
        super().__init__(message)


def _is_bank_api_blocked_message(msg: str) -> bool:
    m = (msg or '').lower()
    return 'required permissions' in m or 'does not have access' in m


def build_external_account_payload(
    *,
    routing_number: str,
    account_number: str,
    account_holder_name: str | None = None,
    account_holder_type: str = 'individual',
) -> dict[str, Any]:
    routing = _normalize_routing(routing_number)
    account = _normalize_account_number(account_number)
    holder_type = (account_holder_type or 'individual').strip().lower()
    if holder_type not in ('individual', 'company'):
        holder_type = 'individual'
    payload: dict[str, Any] = {
        'object': 'bank_account',
        'country': 'US',
        'currency': 'usd',
        'routing_number': routing,
        'account_number': account,
        'account_holder_type': holder_type,
    }
    if (account_holder_name or '').strip():
        payload['account_holder_name'] = account_holder_name.strip()
    return payload


STRIPE_CONNECTED_ACCOUNT_AGREEMENT_URL = 'https://stripe.com/legal/connect-account'


def _normalize_routing(value: str) -> str:
    s = re.sub(r'\D', '', (value or '').strip())
    if len(s) != 9:
        raise StripeConnectBankError('Routing number must be 9 digits (US ACH).')
    return s


def _normalize_account_number(value: str) -> str:
    s = re.sub(r'\D', '', (value or '').strip())
    if len(s) < 4 or len(s) > 17:
        raise StripeConnectBankError('Account number must be 4–17 digits.')
    return s


def _bank_account_to_public_dict(ba: Any) -> dict[str, Any]:
    """Map Stripe BankAccount object to a safe API payload (no full account/routing)."""
    bank_name = (
        getattr(ba, 'bank_name', None)
        or (ba.get('bank_name') if isinstance(ba, dict) else None)
        or ''
    )
    last4 = getattr(ba, 'last4', None) or (ba.get('last4') if isinstance(ba, dict) else None) or ''
    status = getattr(ba, 'status', None) or (ba.get('status') if isinstance(ba, dict) else None) or ''
    ba_id = getattr(ba, 'id', None) or (ba.get('id') if isinstance(ba, dict) else None) or ''
    currency = (getattr(ba, 'currency', None) or (ba.get('currency') if isinstance(ba, dict) else None) or 'usd')
    country = getattr(ba, 'country', None) or (ba.get('country') if isinstance(ba, dict) else None) or 'US'
    default_for_currency = bool(
        getattr(ba, 'default_for_currency', False)
        or (ba.get('default_for_currency') if isinstance(ba, dict) else False)
    )
    holder_name = getattr(ba, 'account_holder_name', None) or (
        ba.get('account_holder_name') if isinstance(ba, dict) else None
    )

    label = bank_name.strip() if bank_name else 'Bank'
    if last4:
        display = f'{label} •••• {last4}'
    else:
        display = label

    return {
        'id': str(ba_id),
        'bank_name': str(bank_name or ''),
        'last4': str(last4 or ''),
        'currency': str(currency).upper(),
        'country': str(country).upper(),
        'status': str(status),
        'default_for_currency': default_for_currency,
        'account_holder_name': holder_name or None,
        'display_label': display,
    }


def list_connect_bank_accounts(*, stripe_connect_account_id: str, limit: int = 10) -> list[dict[str, Any]]:
    if not stripe_configured():
        raise StripeConnectBankError('Stripe is not configured on the server.')
    acct = (stripe_connect_account_id or '').strip()
    if not acct.startswith('acct_'):
        raise StripeConnectBankError('Invalid Connect account id.')

    stripe = stripe_sdk()
    try:
        result = stripe.Account.list_external_accounts(acct, object='bank_account', limit=limit)
    except Exception as exc:  # noqa: BLE001
        msg = str(getattr(exc, 'user_message', None) or getattr(exc, 'message', None) or exc)
        if _is_bank_api_blocked_message(msg):
            return []
        raise StripeConnectBankError(msg) from exc

    rows = list(getattr(result, 'data', []) or [])
    out = [_bank_account_to_public_dict(ba) for ba in rows]
    out.sort(key=lambda x: (not x.get('default_for_currency'), x.get('id') or ''))
    return out


def get_default_connect_bank_account(*, stripe_connect_account_id: str) -> dict[str, Any] | None:
    accounts = list_connect_bank_accounts(stripe_connect_account_id=stripe_connect_account_id, limit=10)
    if not accounts:
        return None
    for row in accounts:
        if row.get('default_for_currency'):
            return row
    return accounts[0]


def add_connect_bank_account(
    *,
    stripe_connect_account_id: str,
    routing_number: str,
    account_number: str,
    account_holder_name: str | None = None,
    account_holder_type: str = 'individual',
) -> dict[str, Any]:
    """
    Attach a US bank account to a Connect account for weekly direct deposit.

    Sensitive values are sent only to Stripe (never logged).
    """
    if not stripe_configured():
        raise StripeConnectBankError('Stripe is not configured on the server.')
    acct = (stripe_connect_account_id or '').strip()
    if not acct.startswith('acct_'):
        raise StripeConnectBankError('Invalid Connect account id.')

    stripe = stripe_sdk()
    payload = build_external_account_payload(
        routing_number=routing_number,
        account_number=account_number,
        account_holder_name=account_holder_name,
        account_holder_type=account_holder_type,
    )

    try:
        ba = stripe.Account.create_external_account(acct, external_account=payload)
    except Exception as exc:  # noqa: BLE001
        msg = str(getattr(exc, 'user_message', None) or getattr(exc, 'message', None) or exc)
        if _is_bank_api_blocked_message(msg):
            raise StripeConnectBankError(
                f'{msg} Express accounts cannot add a bank via API after creation; '
                'retry after the platform recreates a custom Connect account (automatic on next POST), '
                'or set STRIPE_CONNECT_ACCOUNT_TYPE=custom for new masters.'
            ) from exc
        raise StripeConnectBankError(msg) from exc

    return _bank_account_to_public_dict(ba)


def delete_connect_bank_account(*, stripe_connect_account_id: str, bank_account_id: str) -> None:
    if not stripe_configured():
        raise StripeConnectBankError('Stripe is not configured on the server.')
    acct = (stripe_connect_account_id or '').strip()
    ba_id = (bank_account_id or '').strip()
    if not acct.startswith('acct_'):
        raise StripeConnectBankError('Invalid Connect account id.')
    if not ba_id:
        raise StripeConnectBankError('bank_account_id is required.')

    stripe = stripe_sdk()
    try:
        stripe.Account.delete_external_account(acct, ba_id)
    except Exception as exc:  # noqa: BLE001
        msg = str(getattr(exc, 'user_message', None) or getattr(exc, 'message', None) or exc)
        raise StripeConnectBankError(msg) from exc


def build_master_payout_profile(*, master: Master) -> dict[str, Any]:
    """
    Payout screen payload: Connect status + default bank mask (Instacart-style).
    """
    from django.conf import settings

    acct = (getattr(master, 'stripe_connect_account_id', None) or '').strip()
    pk = (getattr(settings, 'STRIPE_PUBLISHABLE_KEY', '') or '').strip()

    base: dict[str, Any] = {
        'stripe_connect_account_id': acct or None,
        'stripe_publishable_key': pk,
        'connected_account_agreement_url': STRIPE_CONNECTED_ACCOUNT_AGREEMENT_URL,
        'account': None,
        'onboarding_complete': False,
        'bank_account': None,
        'bank_accounts': [],
        'weekly_direct_deposit': {
            'enabled': False,
            'bank_account': None,
            'fee_note': 'No fee',
        },
        'requirements': None,
    }

    if not acct:
        return base

    try:
        summary = fetch_connect_account_public_summary(acct)
    except StripeConnectLinkError as e:
        base['account_load_error'] = e.message
        return base

    base['account'] = summary
    base['onboarding_complete'] = bool(summary.get('charges_enabled')) and bool(summary.get('payouts_enabled'))

    try:
        banks = list_connect_bank_accounts(stripe_connect_account_id=acct)
    except StripeConnectBankError as e:
        base['bank_load_error'] = e.message
        banks = []

    base['bank_accounts'] = banks
    default_ba = None
    for row in banks:
        if row.get('default_for_currency'):
            default_ba = row
            break
    if not default_ba and banks:
        default_ba = banks[0]

    base['bank_account'] = default_ba
    base['weekly_direct_deposit'] = {
        'enabled': bool(default_ba),
        'bank_account': default_ba,
        'fee_note': 'No fee',
        'schedule_note': (
            'Payout schedule is configured on the connected account (typically weekly). '
            'Use GET /api/master/stripe-balance/ for balance and recent payouts.'
        ),
    }

    # Best-effort: surface if Stripe still needs identity/tax (may prompt later onboarding).
    if stripe_configured():
        try:
            stripe = stripe_sdk()
            a = stripe.Account.retrieve(acct)
            req = getattr(a, 'requirements', None)
            if req:
                currently = list(getattr(req, 'currently_due', None) or [])
                eventually = list(getattr(req, 'eventually_due', None) or [])
                past_due = list(getattr(req, 'past_due', None) or [])
                if currently or eventually or past_due:
                    base['requirements'] = {
                        'currently_due': currently,
                        'eventually_due': eventually,
                        'past_due': past_due,
                        'needs_additional_setup': bool(currently or past_due),
                    }
        except Exception:
            pass

    return base


def ensure_master_connect_and_add_bank(
    *,
    master: Master,
    routing_number: str,
    account_number: str,
    account_holder_name: str | None = None,
    account_holder_type: str = 'individual',
    user=None,
    request=None,
    accept_agreement: bool = True,
    dob_year: int | None = None,
    dob_month: int | None = None,
    dob_day: int | None = None,
    ssn_last4: str | None = None,
) -> dict[str, Any]:
    """
    Create Connect account if missing (default **custom**), attach US bank.

    If an old **express** ``acct_`` blocks API bank attach, clears the local link and
    recreates a **custom** account with the bank in one step.
    """
    from django.db import transaction

    from apps.payment.services.stripe_connect_onboarding import ensure_express_connect_account_for_master

    ext = build_external_account_payload(
        routing_number=routing_number,
        account_number=account_number,
        account_holder_name=account_holder_name,
        account_holder_type=account_holder_type,
    )

    with transaction.atomic():
        locked = Master.objects.select_for_update().get(pk=master.pk)
        acct = (locked.stripe_connect_account_id or '').strip()

        if acct:
            try:
                bank = add_connect_bank_account(
                    stripe_connect_account_id=acct,
                    routing_number=routing_number,
                    account_number=account_number,
                    account_holder_name=account_holder_name,
                    account_holder_type=account_holder_type,
                )
                master.stripe_connect_account_id = acct
                profile = _finalize_master_payout_profile(
                    master=master,
                    bank=bank,
                    user=user,
                    request=request,
                    accept_agreement=accept_agreement,
                    dob_year=dob_year,
                    dob_month=dob_month,
                    dob_day=dob_day,
                    ssn_last4=ssn_last4,
                    connect_account_recreated=False,
                )
                return profile
            except StripeConnectBankError as e:
                if not _is_bank_api_blocked_message(e.message):
                    raise
                Master.objects.filter(pk=locked.pk).update(stripe_connect_account_id='')
                locked.stripe_connect_account_id = ''
                master.stripe_connect_account_id = ''

        acct, created = ensure_express_connect_account_for_master(locked, external_account=ext)
        Master.objects.filter(pk=locked.pk).update(stripe_connect_account_id=acct)
        master.stripe_connect_account_id = acct

    bank = get_default_connect_bank_account(stripe_connect_account_id=acct)
    if not bank:
        bank = add_connect_bank_account(
            stripe_connect_account_id=acct,
            routing_number=routing_number,
            account_number=account_number,
            account_holder_name=account_holder_name,
            account_holder_type=account_holder_type,
        )
    return _finalize_master_payout_profile(
        master=master,
        bank=bank,
        user=user,
        request=request,
        accept_agreement=accept_agreement,
        dob_year=dob_year,
        dob_month=dob_month,
        dob_day=dob_day,
        ssn_last4=ssn_last4,
        connect_account_recreated=created,
    )


def _finalize_master_payout_profile(
    *,
    master: Master,
    bank: dict[str, Any],
    user=None,
    request=None,
    accept_agreement: bool,
    dob_year: int | None,
    dob_month: int | None,
    dob_day: int | None,
    ssn_last4: str | None,
    connect_account_recreated: bool,
) -> dict[str, Any]:
    from apps.payment.services.stripe_connect_setup import (
        StripeConnectSetupError,
        complete_connect_account_setup,
    )

    setup_result = None
    setup_error = None
    if user is not None and accept_agreement:
        try:
            setup_result = complete_connect_account_setup(
                master=master,
                user=user,
                request=request,
                accept_agreement=True,
                dob_year=dob_year,
                dob_month=dob_month,
                dob_day=dob_day,
                ssn_last4=ssn_last4,
            )
        except StripeConnectSetupError as e:
            setup_error = e.message

    profile = build_master_payout_profile(master=master)
    profile['bank_account'] = bank
    profile['connect_account_recreated'] = connect_account_recreated
    if setup_result:
        profile['connect_setup'] = setup_result
        if setup_result.get('onboarding_complete'):
            profile['onboarding_complete'] = True
        if setup_result.get('account'):
            profile['account'] = setup_result['account']
    if setup_error:
        profile['connect_setup_error'] = setup_error
    return profile
