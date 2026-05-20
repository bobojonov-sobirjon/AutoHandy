"""Create Stripe Connect Express account + Account Link for master onboarding."""
from __future__ import annotations

from django.conf import settings
from django.db import transaction

from apps.master.models import Master
from apps.payment.services.stripe_client import stripe_configured, stripe_sdk
from apps.payment.services.stripe_connect_link import StripeConnectLinkError


def _enrich_account_link_error_message(msg: str) -> str:
    """Append local hints for common Stripe Connect / Express configuration mistakes."""
    m = (msg or '').strip()
    if not m:
        return m
    if 'not enabled for Express' in m or 'Country and Capabilities' in m:
        return (
            f'{m} '
            '— Enable that country for Express in Stripe Dashboard, or use a US connected account. '
            'This API now creates **US** Express accounts and clears a saved acct_ whose country mismatches US '
            'on the next POST /stripe-connect/onboarding/.'
        )
    if 'capabilities' in m.lower() and 'account_onboarding' in m.lower():
        return (
            f'{m} '
            '— Ensure Express is enabled for the account country in the Stripe Dashboard, or recreate the connected account.'
        )
    return m


_WEEKLY_ANCHORS = frozenset(
    {'monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday'}
)
_PAYOUT_INTERVALS = frozenset({'daily', 'weekly', 'monthly', 'manual'})


def _connect_payout_schedule_dict() -> dict | None:
    """
    Stripe ``settings.payouts.schedule`` for new/modified Connect accounts.
    Returns None when payout scheduling is disabled in Django settings.
    """
    if not getattr(settings, 'STRIPE_CONNECT_APPLY_PAYOUT_SCHEDULE', True):
        return None
    interval = getattr(settings, 'STRIPE_CONNECT_PAYOUT_INTERVAL', 'weekly') or 'weekly'
    interval = str(interval).strip().lower()
    if interval not in _PAYOUT_INTERVALS:
        interval = 'weekly'
    sched: dict = {'interval': interval}
    if interval == 'weekly':
        anchor = getattr(settings, 'STRIPE_CONNECT_PAYOUT_WEEKLY_ANCHOR', 'monday') or 'monday'
        anchor = str(anchor).strip().lower()
        if anchor not in _WEEKLY_ANCHORS:
            anchor = 'monday'
        sched['weekly_anchor'] = anchor
    delay = getattr(settings, 'STRIPE_CONNECT_PAYOUT_DELAY_DAYS', None)
    if delay is not None and delay != '':
        sched['delay_days'] = delay
    return sched


def _connect_account_settings_with_payouts() -> dict | None:
    sched = _connect_payout_schedule_dict()
    if not sched:
        return None
    return {'payouts': {'schedule': sched}}


def _try_sync_connect_payout_schedule(stripe, account_id: str) -> None:
    """Best-effort: align an existing connected account with configured payout schedule."""
    if not getattr(settings, 'STRIPE_CONNECT_ENSURE_PAYOUT_SCHEDULE_ON_ONBOARDING', True):
        return
    inner = _connect_account_settings_with_payouts()
    if not inner:
        return
    aid = (account_id or '').strip()
    if not aid.startswith('acct_'):
        return
    try:
        stripe.Account.modify(aid, settings=inner)
    except Exception:
        pass


def default_connect_country_code() -> str:
    """
    Stripe Express connected-account **country** (ISO-3166 alpha-2).

    Locked to **US** so onboarding matches a typical Dashboard where only United States
    is enabled under Connect → Express → Countries. (CA/other: enable in Stripe first, then we can expose env.)
    """
    return 'US'


def connect_account_type() -> str:
    """
    ``custom`` — platform can attach bank via API (Instacart-style in-app form).
    ``express`` — bank via Stripe onboarding only (API attach after create is blocked).
    """
    from django.conf import settings

    t = (getattr(settings, 'STRIPE_CONNECT_ACCOUNT_TYPE', None) or 'custom').strip().lower()
    return t if t in ('custom', 'express') else 'custom'


def ensure_express_connect_account_for_master(
    master: Master,
    *,
    external_account: dict | None = None,
) -> tuple[str, bool]:
    """
    If ``master.stripe_connect_account_id`` is empty, create a Stripe Connect account
    (type from ``STRIPE_CONNECT_ACCOUNT_TYPE``, default **custom**) and save ``acct_…``.

    Optional ``external_account`` bank payload may be set only when the account is first created.

    Returns ``(acct_id, created_this_call)``.
    """
    if not stripe_configured():
        raise StripeConnectLinkError('Stripe is not configured on the server.')

    stripe = stripe_sdk()
    country = default_connect_country_code()

    with transaction.atomic():
        locked = Master.objects.select_for_update().get(pk=master.pk)
        existing = (locked.stripe_connect_account_id or '').strip()
        want = default_connect_country_code()

        if existing:
            try:
                a = stripe.Account.retrieve(existing)
                got = (getattr(a, 'country', None) or '').strip().upper()
                if got and got != want:
                    Master.objects.filter(pk=locked.pk).update(stripe_connect_account_id='')
                    master.stripe_connect_account_id = ''
                    existing = ''
                else:
                    _try_sync_connect_payout_schedule(stripe, existing)
            except Exception:
                pass

        if existing:
            return existing, False

        kwargs: dict = {
            'type': connect_account_type(),
            'country': country,
            'capabilities': {
                'transfers': {'requested': True},
                'card_payments': {'requested': True},
            },
            'metadata': {'master_id': str(locked.pk), 'user_id': str(locked.user_id)},
        }
        email = (getattr(locked.user, 'email', None) or '').strip()
        if email:
            kwargs['email'] = email

        payout_settings = _connect_account_settings_with_payouts()
        if payout_settings:
            kwargs['settings'] = payout_settings

        if external_account:
            kwargs['external_account'] = external_account

        try:
            acct = stripe.Account.create(**kwargs)
        except Exception as exc:  # noqa: BLE001
            msg = str(getattr(exc, 'user_message', None) or getattr(exc, 'message', None) or exc)
            raise StripeConnectLinkError(msg) from exc

        aid = str(getattr(acct, 'id', '') or '').strip()
        if not aid.startswith('acct_'):
            raise StripeConnectLinkError('Stripe did not return a valid Connect account id.')

        Master.objects.filter(pk=locked.pk).update(stripe_connect_account_id=aid)
        master.stripe_connect_account_id = aid
        return aid, True


def create_account_onboarding_url(*, account_id: str, refresh_url: str, return_url: str) -> str:
    """Stripe-hosted onboarding / resume URL (short-lived)."""
    if not stripe_configured():
        raise StripeConnectLinkError('Stripe is not configured on the server.')
    stripe = stripe_sdk()
    try:
        link = stripe.AccountLink.create(
            account=account_id.strip(),
            refresh_url=refresh_url.strip(),
            return_url=return_url.strip(),
            type='account_onboarding',
        )
    except Exception as exc:  # noqa: BLE001
        msg = str(getattr(exc, 'user_message', None) or getattr(exc, 'message', None) or exc)
        msg = _enrich_account_link_error_message(msg)
        raise StripeConnectLinkError(msg) from exc
    url = getattr(link, 'url', None) or ''
    if not url:
        raise StripeConnectLinkError('Stripe did not return an onboarding URL.')
    return str(url)
