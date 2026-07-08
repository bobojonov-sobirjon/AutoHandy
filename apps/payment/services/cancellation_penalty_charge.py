"""Off-session Stripe charge for client cancellation penalties (platform only, no Connect transfer)."""
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

from django.conf import settings

from apps.order.models import Order, OrderStripePaymentStatus
from apps.payment.services.checkout_fees import money_to_cents
from apps.payment.services.order_charge import StripeChargeError
from apps.payment.services.stripe_cards import resolve_client_saved_card
from apps.payment.services.stripe_client import stripe_configured, stripe_sdk


def cancellation_penalty_already_collected(order: Order) -> bool:
    return (
        order.stripe_payment_status == OrderStripePaymentStatus.SUCCEEDED
        and bool((order.stripe_payment_intent_id or '').strip())
        and (order.order_penalty_total or 0) > 0
    )


def charge_cancellation_penalty(
    order: Order,
    *,
    amount: Decimal,
    penalty_percent: int,
) -> dict:
    """
    Charge the driver's card for a cancellation fee. Updates ``order`` stripe_* fields.

    Returns dict with keys: attempted, succeeded, error, payment_intent_id, amount_cents.
    """
    out = {
        'attempted': False,
        'succeeded': False,
        'error': '',
        'payment_intent_id': '',
        'amount_cents': 0,
        'penalty_percent': penalty_percent,
    }
    fee = amount.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    if fee <= 0:
        return out

    if not getattr(settings, 'CLIENT_CANCEL_PENALTY_CHARGE_ENABLED', True):
        out['error'] = 'Cancellation penalty charging is disabled.'
        return out

    if cancellation_penalty_already_collected(order):
        out['succeeded'] = True
        out['payment_intent_id'] = (order.stripe_payment_intent_id or '').strip()
        out['amount_cents'] = int(order.stripe_payment_amount_cents or 0)
        return out

    if not stripe_configured():
        out['error'] = 'Stripe is not configured on the server.'
        order.stripe_payment_status = OrderStripePaymentStatus.FAILED
        order.stripe_payment_error = out['error']
        return out

    card = resolve_client_saved_card(order)
    if not card:
        msg = 'No saved card on file. Add a card before cancelling with a fee.'
        order.stripe_payment_status = OrderStripePaymentStatus.FAILED
        order.stripe_payment_error = msg
        out['error'] = msg
        return out

    amount_cents = money_to_cents(fee)
    if amount_cents <= 0:
        return out

    currency = (getattr(settings, 'STRIPE_CHARGE_CURRENCY', 'usd') or 'usd').lower()
    stripe = stripe_sdk()
    idem = f'autohandy_order_{order.pk}_cancel_penalty_{amount_cents}'

    out['attempted'] = True
    out['amount_cents'] = amount_cents
    order.stripe_payment_status = OrderStripePaymentStatus.PENDING
    order.stripe_payment_error = ''

    params: dict = {
        'amount': amount_cents,
        'currency': currency,
        'customer': card.stripe_customer_id,
        'payment_method': card.stripe_payment_method_id,
        'confirm': True,
        'off_session': True,
        'description': f'Order #{order.pk} cancellation penalty ({penalty_percent}%)',
        'metadata': {
            'order_id': str(order.pk),
            'user_id': str(order.user_id),
            'charge_type': 'cancellation_penalty',
            'penalty_percent': str(penalty_percent),
        },
        'idempotency_key': idem,
    }

    try:
        pi = stripe.PaymentIntent.create(**params)
    except Exception as exc:  # noqa: BLE001
        msg = str(getattr(exc, 'user_message', None) or getattr(exc, 'message', None) or exc)
        order.stripe_payment_intent_id = ''
        order.stripe_payment_status = OrderStripePaymentStatus.FAILED
        order.stripe_payment_amount_cents = amount_cents
        order.stripe_payment_currency = currency
        order.stripe_payment_error = msg[:2000]
        out['error'] = msg
        return out

    st = getattr(pi, 'status', '') or ''
    order.stripe_payment_intent_id = str(pi.id)
    order.stripe_payment_amount_cents = amount_cents
    order.stripe_payment_currency = currency

    if st != 'succeeded':
        msg = f'PaymentIntent status={st}'
        order.stripe_payment_status = OrderStripePaymentStatus.FAILED
        order.stripe_payment_error = msg
        out['error'] = msg
        return out

    order.stripe_payment_status = OrderStripePaymentStatus.SUCCEEDED
    order.stripe_payment_error = ''
    out['succeeded'] = True
    out['payment_intent_id'] = str(pi.id)
    return out
