"""Off-session PaymentIntent when master completes a card-paid order."""
from __future__ import annotations

from decimal import Decimal

from django.conf import settings
from django.utils import timezone

from apps.order.models import Order, OrderPaymentType, OrderStripePaymentStatus
from apps.payment.models import SavedCard
from apps.payment.services.checkout_fees import customer_charge_cents, master_payout_cents, money_to_cents
from apps.payment.services.stripe_cards import resolve_client_saved_card
from apps.payment.services.stripe_client import stripe_configured, stripe_sdk


class StripeChargeError(Exception):
    def __init__(self, message: str):
        self.message = message
        super().__init__(message)


def _capability_status(caps: object | None, key: str) -> str:
    if caps is None:
        return ''
    try:
        if isinstance(caps, dict):
            raw = caps.get(key, '')
        else:
            raw = getattr(caps, key, '') or ''
            if raw == '' and hasattr(caps, 'get'):
                raw = caps.get(key, '') or ''
        return str(raw).strip().lower()
    except Exception:
        return ''


def _assert_connect_destination_can_receive_transfers(stripe, account_id: str) -> None:
    """
    Destination charges require an eligible connected account (e.g. ``transfers`` active).
    Without this, Stripe returns a long error about capabilities on complete.
    """
    aid = (account_id or '').strip()
    if not aid.startswith('acct_'):
        raise StripeChargeError('Master has no valid Stripe Connect account id.')
    try:
        acct = stripe.Account.retrieve(aid)
    except Exception as exc:  # noqa: BLE001
        raise StripeChargeError(
            f'Could not load the master Stripe Connect account from Stripe: {exc}'
        ) from exc

    caps = getattr(acct, 'capabilities', None)
    if _capability_status(caps, 'transfers') == 'active':
        return
    if _capability_status(caps, 'legacy_payments') == 'active':
        return
    if _capability_status(caps, 'crypto_transfers') == 'active':
        return

    tr = _capability_status(caps, 'transfers') or 'unknown'
    charges_on = bool(getattr(acct, 'details_submitted', False)) and bool(getattr(acct, 'charges_enabled', False))
    if tr == 'pending':
        hint = (
            'Stripe is still activating this account (transfers=pending). '
            'Wait a short time or reopen onboarding if Stripe asks for more information.'
        )
    elif not charges_on:
        hint = (
            'Direct deposit is not finished: POST /api/master/stripe-connect/bank-account/ '
            'with routing_number and account_number, then retry.'
        )
    else:
        hint = (
            'The connected account cannot accept destination transfers yet. '
            'In Stripe Dashboard → Connect → this account, check requirements and capabilities; '
            'the master may need to finish onboarding or resolve restrictions.'
        )

    raise StripeChargeError(
        'This master’s Stripe Connect account cannot receive card payouts yet '
        f'(capabilities.transfers is not active; current status: {tr}). {hint}'
    )


def _friendly_stripe_destination_error(msg: str) -> str | None:
    m = (msg or '').lower()
    if 'destination account' in m and 'capabilities' in m:
        return (
            'The master’s Stripe Connect account cannot receive transfers yet (Stripe capabilities). '
            'They must link a bank account: POST /api/master/stripe-connect/bank-account/ '
            'and ensure Stripe Connect capabilities are active.'
        )
    return None


def _resolve_order_charge_card(order: Order) -> SavedCard:
    """
    Order-linked card first, else the client's default saved card (same as cancel penalties).
    Also links the card on the order when missing so later charges reuse it.
    """
    card = resolve_client_saved_card(order)
    if not card:
        raise StripeChargeError(
            'No saved card on file. Add a payment card in the app before leaving a tip.'
        )
    if card.user_id != order.user_id:
        raise StripeChargeError('Saved card does not belong to the order owner.')
    if not card.is_active:
        raise StripeChargeError('Saved card is inactive.')
    if not order.saved_card_id:
        order.saved_card = card
        order.payment_type = OrderPaymentType.CARD
    return card


def charge_order_on_completion(order: Order) -> None:
    """
    Charge the order owner's saved card when the master completes the job.
    On success updates order stripe_* fields via ORM (caller should save completion in same transaction).
    Raises StripeChargeError on failure (no DB writes on failure).
    """
    if not stripe_configured():
        raise StripeChargeError('Stripe is not configured on the server.')

    card = _resolve_order_charge_card(order)

    amount_cents = customer_charge_cents(order)
    if amount_cents <= 0:
        raise StripeChargeError('Charge amount must be positive.')

    payout_cents = master_payout_cents(order)
    application_fee = max(0, amount_cents - payout_cents)
    extra_bps = int(getattr(settings, 'STRIPE_CONNECT_EXTRA_APPLICATION_FEE_BPS', 0) or 0)
    if extra_bps > 0:
        application_fee = min(amount_cents, application_fee + int(amount_cents * extra_bps / 10000))

    currency = (getattr(settings, 'STRIPE_CHARGE_CURRENCY', 'usd') or 'usd').lower()
    dest = ''
    if order.master_id:
        try:
            dest = (order.master.stripe_connect_account_id or '').strip()
        except Exception:
            dest = ''

    stripe = stripe_sdk()
    if dest:
        _assert_connect_destination_can_receive_transfers(stripe, dest)

    idem = f'autohandy_order_{order.pk}_complete_charge_v1'

    params: dict = {
        'amount': amount_cents,
        'currency': currency,
        'customer': card.stripe_customer_id,
        'payment_method': card.stripe_payment_method_id,
        'confirm': True,
        'off_session': True,
        'metadata': {
            'order_id': str(order.pk),
            'user_id': str(order.user_id),
        },
        'idempotency_key': idem,
    }
    if dest:
        params['transfer_data'] = {'destination': dest}
        if application_fee > 0:
            params['application_fee_amount'] = application_fee

    try:
        pi = stripe.PaymentIntent.create(**params)
    except Exception as exc:  # noqa: BLE001
        msg = str(getattr(exc, 'user_message', None) or getattr(exc, 'message', None) or exc)
        friendly = _friendly_stripe_destination_error(msg)
        raise StripeChargeError(friendly or msg) from exc

    st = getattr(pi, 'status', '') or ''
    if st != 'succeeded':
        msg = f'PaymentIntent status={st}'
        raise StripeChargeError(msg)

    order.stripe_payment_intent_id = str(pi.id)
    order.stripe_payment_status = OrderStripePaymentStatus.SUCCEEDED
    order.stripe_payment_amount_cents = amount_cents
    order.stripe_payment_currency = currency
    order.stripe_payment_error = ''


def charge_order_tip(order: Order, tip_amount: Decimal) -> None:
    """
    Off-session tip after completion. When the master has an eligible Connect account,
    100% is transferred to them (no platform fee). Otherwise the tip is captured on
    the platform account (same as a job payment without Connect).
    """
    if not stripe_configured():
        raise StripeChargeError('Stripe is not configured on the server.')

    amount = Decimal(str(tip_amount))
    if amount <= 0:
        raise StripeChargeError('Tip amount must be positive.')

    card = _resolve_order_charge_card(order)

    amount_cents = money_to_cents(amount)
    currency = (getattr(settings, 'STRIPE_CHARGE_CURRENCY', 'usd') or 'usd').lower()
    dest = ''
    if order.master_id:
        try:
            dest = (order.master.stripe_connect_account_id or '').strip()
        except Exception:
            dest = ''

    stripe = stripe_sdk()
    if dest:
        _assert_connect_destination_can_receive_transfers(stripe, dest)

    idem = f'autohandy_order_{order.pk}_tip_v1'
    params: dict = {
        'amount': amount_cents,
        'currency': currency,
        'customer': card.stripe_customer_id,
        'payment_method': card.stripe_payment_method_id,
        'confirm': True,
        'off_session': True,
        'metadata': {
            'order_id': str(order.pk),
            'user_id': str(order.user_id),
            'kind': 'tip',
        },
        'idempotency_key': idem,
    }
    if dest:
        params['transfer_data'] = {'destination': dest}

    try:
        pi = stripe.PaymentIntent.create(**params)
    except Exception as exc:  # noqa: BLE001
        msg = str(getattr(exc, 'user_message', None) or getattr(exc, 'message', None) or exc)
        friendly = _friendly_stripe_destination_error(msg)
        raise StripeChargeError(friendly or msg) from exc

    st = getattr(pi, 'status', '') or ''
    if st != 'succeeded':
        raise StripeChargeError(f'Tip PaymentIntent status={st}')

    order.tip_amount = amount
    order.tip_stripe_payment_intent_id = str(pi.id)
    order.tip_stripe_payment_status = OrderStripePaymentStatus.SUCCEEDED
    order.tip_declined = False
    order.tip_paid_at = timezone.now()
