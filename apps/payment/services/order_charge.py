"""Off-session PaymentIntent when master completes a card-paid order."""
from __future__ import annotations

from decimal import Decimal

from django.conf import settings
from django.utils import timezone

from apps.order.models import Order, OrderPaymentType, OrderStripePaymentStatus
from apps.payment.models import SavedCard
from apps.payment.services.checkout_fees import (
    customer_charge_cents,
    customer_tip_charge_cents,
    master_payout_cents,
    master_tip_payout_cents,
    money_to_cents,
)
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


def _complete_charge_idempotency_key(order: Order) -> str:
    attempt = max(1, int(getattr(order, 'stripe_charge_attempt', None) or 1))
    return f'autohandy_order_{order.pk}_complete_charge_a{attempt}'


def _record_complete_charge_failure(order: Order, message: str) -> None:
    """
    Persist failure + bump attempt so the next Complete uses a fresh Stripe idempotency key.
    Without this, Stripe replays the cached decline (e.g. insufficient_funds) for ~24h.
    """
    attempt = max(1, int(getattr(order, 'stripe_charge_attempt', None) or 1))
    order.stripe_payment_status = OrderStripePaymentStatus.FAILED
    order.stripe_payment_error = (message or '')[:2000]
    order.stripe_charge_attempt = attempt + 1
    update_fields = [
        'stripe_payment_status',
        'stripe_payment_error',
        'stripe_charge_attempt',
        'updated_at',
    ]
    if order.saved_card_id:
        update_fields.append('saved_card')
    if order.payment_type:
        update_fields.append('payment_type')
    order.save(update_fields=update_fields)


def _bind_succeeded_payment_intent(order: Order, pi, *, amount_cents: int, currency: str) -> None:
    order.stripe_payment_intent_id = str(pi.id)
    order.stripe_payment_status = OrderStripePaymentStatus.SUCCEEDED
    order.stripe_payment_amount_cents = amount_cents
    order.stripe_payment_currency = currency
    order.stripe_payment_error = ''


def _find_existing_succeeded_job_payment(stripe, order: Order):
    """
    Recover after a client timeout: charge may have succeeded in Stripe while our DB
    never saved SUCCEEDED. Prefer an existing succeeded PI over creating a new one.
    """
    existing_id = (order.stripe_payment_intent_id or '').strip()
    if existing_id.startswith('pi_'):
        try:
            pi = stripe.PaymentIntent.retrieve(existing_id)
            if (getattr(pi, 'status', '') or '') == 'succeeded':
                return pi
        except Exception:  # noqa: BLE001
            pass

    q = f"metadata['order_id']:'{order.pk}'"
    try:
        res = stripe.PaymentIntent.search(query=q, limit=20)
    except Exception:  # noqa: BLE001
        return None

    rows = list(getattr(res, 'data', []) or [])
    succeeded = []
    for pi in rows:
        if (getattr(pi, 'status', '') or '') != 'succeeded':
            continue
        meta = getattr(pi, 'metadata', None) or {}
        kind = ''
        if isinstance(meta, dict):
            kind = str(meta.get('kind') or '')
        else:
            kind = str(getattr(meta, 'kind', '') or '')
        if kind == 'tip':
            continue
        succeeded.append(pi)
    if not succeeded:
        return None
    succeeded.sort(key=lambda p: int(getattr(p, 'created', 0) or 0), reverse=True)
    return succeeded[0]


def charge_order_on_completion(order: Order) -> None:
    """
    Charge the order owner's saved card when the master completes the job.

    On success updates order stripe_* fields via ORM (caller should save completion).
    On card/API failure: persists FAILED + increments ``stripe_charge_attempt`` so a later
    Complete is not stuck on Stripe's idempotent replay of the decline, then raises
    ``StripeChargeError``.
    """
    if not stripe_configured():
        raise StripeChargeError('Stripe is not configured on the server.')

    # Already captured — do not charge again (safe Complete retry after DB save race).
    if (
        order.stripe_payment_status == OrderStripePaymentStatus.SUCCEEDED
        and (order.stripe_payment_intent_id or '').startswith('pi_')
    ):
        return

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

    existing = _find_existing_succeeded_job_payment(stripe, order)
    if existing is not None:
        charged = int(getattr(existing, 'amount', 0) or amount_cents)
        cur = (getattr(existing, 'currency', None) or currency or 'usd').lower()
        _bind_succeeded_payment_intent(order, existing, amount_cents=charged, currency=cur)
        return

    attempt = max(1, int(getattr(order, 'stripe_charge_attempt', None) or 1))
    idem = _complete_charge_idempotency_key(order)

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
            'kind': 'job_complete',
            'charge_attempt': str(attempt),
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
        final_msg = friendly or msg
        try:
            _record_complete_charge_failure(order, final_msg)
        except Exception:  # noqa: BLE001
            pass
        raise StripeChargeError(final_msg) from exc

    st = getattr(pi, 'status', '') or ''
    if st != 'succeeded':
        msg = f'PaymentIntent status={st}'
        try:
            _record_complete_charge_failure(order, msg)
        except Exception:  # noqa: BLE001
            pass
        raise StripeChargeError(msg)

    _bind_succeeded_payment_intent(order, pi, amount_cents=amount_cents, currency=currency)


def _tip_idempotency_key(order: Order) -> str:
    attempt = max(1, int(getattr(order, 'tip_charge_attempt', None) or 1))
    return f'autohandy_order_{order.pk}_tip_a{attempt}'


def _record_tip_charge_failure(order: Order, message: str) -> None:
    """Bump attempt so the next tip retry uses a fresh Stripe idempotency key (no cached decline)."""
    attempt = max(1, int(getattr(order, 'tip_charge_attempt', None) or 1))
    order.tip_stripe_payment_status = OrderStripePaymentStatus.FAILED
    order.tip_charge_attempt = attempt + 1
    order.save(update_fields=['tip_stripe_payment_status', 'tip_charge_attempt', 'updated_at'])


def charge_order_tip(order: Order, tip_amount: Decimal) -> None:
    """
    Off-session tip after completion. Customer pays tip + marketplace surcharges (same % as the job).
    Master receives tip payout after PROVIDER_PLATFORM_FEE_PERCENT (default 10%).

    Attempt-based idempotency: a failed tip charge increments ``tip_charge_attempt`` so a later
    retry is not stuck replaying Stripe's cached decline for ~24h.
    """
    if not stripe_configured():
        raise StripeChargeError('Stripe is not configured on the server.')

    # Already paid — nothing to do (idempotent success).
    if order.tip_stripe_payment_status == OrderStripePaymentStatus.SUCCEEDED:
        return

    amount = Decimal(str(tip_amount))
    if amount <= 0:
        raise StripeChargeError('Tip amount must be positive.')

    card = _resolve_order_charge_card(order)

    amount_cents = customer_tip_charge_cents(order, amount)
    if amount_cents <= 0:
        raise StripeChargeError('Tip charge amount must be positive.')

    payout_cents = master_tip_payout_cents(order, amount)
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

    idem = _tip_idempotency_key(order)
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
            'tip_base': format(amount, 'f'),
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
        _record_tip_charge_failure(order, friendly or msg)
        raise StripeChargeError(friendly or msg) from exc

    st = getattr(pi, 'status', '') or ''
    if st != 'succeeded':
        _record_tip_charge_failure(order, f'Tip PaymentIntent status={st}')
        raise StripeChargeError(f'Tip PaymentIntent status={st}')

    order.tip_amount = amount
    order.tip_stripe_payment_intent_id = str(pi.id)
    order.tip_stripe_payment_status = OrderStripePaymentStatus.SUCCEEDED
    order.tip_stripe_payment_amount_cents = amount_cents
    order.tip_declined = False
    order.tip_paid_at = timezone.now()
