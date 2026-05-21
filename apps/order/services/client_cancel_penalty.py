"""Client cancel: persist penalty total and charge the driver's saved card."""
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

from django.conf import settings

from apps.order.models import Order, OrderStripePaymentStatus
from apps.order.services.order_pricing import estimate_cancellation_penalty_amount
from apps.payment.services.cancellation_penalty_charge import (
    cancellation_penalty_already_collected,
    charge_cancellation_penalty,
)


def apply_client_cancel_penalty_and_charge(
    order: Order,
    *,
    penalty_applies: bool,
    penalty_percent: int,
) -> dict:
    """
    Add cancellation fee to ``order_penalty_total`` and charge the driver's card when applicable.

    Returns API-friendly fields (does not save the order — caller saves after cancel fields).
    """
    result = {
        'penalty_applies': bool(penalty_applies),
        'penalty_percent': int(penalty_percent or 0),
        'penalty_amount_estimate': '0.00',
        'penalty_charge_attempted': False,
        'penalty_charge_succeeded': False,
        'penalty_charge_error': '',
        'stripe_payment_intent_id': (order.stripe_payment_intent_id or '').strip(),
    }

    if not penalty_applies or penalty_percent <= 0:
        return result

    est = estimate_cancellation_penalty_amount(order, penalty_percent)
    result['penalty_amount_estimate'] = est
    fee = Decimal(est)
    if fee <= 0:
        return result

    prev = getattr(order, 'order_penalty_total', None) or Decimal('0')
    order.order_penalty_total = (prev + fee).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

    if cancellation_penalty_already_collected(order):
        result['penalty_charge_succeeded'] = True
        result['stripe_payment_intent_id'] = (order.stripe_payment_intent_id or '').strip()
        return result

    if not getattr(settings, 'CLIENT_CANCEL_PENALTY_CHARGE_ENABLED', True):
        result['penalty_charge_error'] = 'Penalty charge is disabled in settings.'
        return result

    charge_out = charge_cancellation_penalty(
        order,
        amount=fee,
        penalty_percent=penalty_percent,
    )
    result['penalty_charge_attempted'] = charge_out.get('attempted', False)
    result['penalty_charge_succeeded'] = charge_out.get('succeeded', False)
    result['penalty_charge_error'] = charge_out.get('error', '') or ''
    result['stripe_payment_intent_id'] = (
        charge_out.get('payment_intent_id', '') or (order.stripe_payment_intent_id or '').strip()
    )

    if result['penalty_charge_attempted'] and not result['penalty_charge_succeeded']:
        _schedule_penalty_retry(order.pk)
    elif result['penalty_charge_succeeded']:
        _notify_penalty_charged(order, penalty_percent=penalty_percent, amount_cents=charge_out.get('amount_cents'))

    return result


def collect_pending_cancellation_penalty(order: Order) -> bool:
    """
    Celery/retry: charge ``order_penalty_total`` for a cancelled order if not yet succeeded.
    Returns True if collected or nothing owed.
    """
    from apps.order.models import OrderStatus

    if order.status != OrderStatus.CANCELLED:
        return False
    total = getattr(order, 'order_penalty_total', None) or Decimal('0')
    if total <= 0:
        return True
    if cancellation_penalty_already_collected(order):
        return True
    if order.stripe_payment_status == OrderStripePaymentStatus.SUCCEEDED:
        return True

    charge_out = charge_cancellation_penalty(order, amount=Decimal(str(total)), penalty_percent=0)
    order.save(
        update_fields=[
            'stripe_payment_intent_id',
            'stripe_payment_status',
            'stripe_payment_amount_cents',
            'stripe_payment_currency',
            'stripe_payment_error',
            'updated_at',
        ]
    )
    if charge_out.get('succeeded'):
        _notify_penalty_charged(order, penalty_percent=0, amount_cents=charge_out.get('amount_cents'))
    return bool(charge_out.get('succeeded'))


def _notify_penalty_charged(order: Order, *, penalty_percent: int, amount_cents: int | None) -> None:
    try:
        from apps.payment.services.checkout_fees import money_to_cents

        cents = int(amount_cents) if amount_cents else money_to_cents(order.order_penalty_total or Decimal('0'))
        if cents <= 0:
            return
        from apps.order.services.notifications import notify_user_cancellation_penalty_charged

        notify_user_cancellation_penalty_charged(
            order,
            amount_cents=cents,
            penalty_percent=int(penalty_percent or 0),
            currency=(order.stripe_payment_currency or '').strip() or None,
        )
    except Exception:  # noqa: BLE001
        pass


def _schedule_penalty_retry(order_id: int) -> None:
    try:
        from apps.order.tasks import charge_cancellation_penalty_task

        charge_cancellation_penalty_task.apply_async(args=[order_id], countdown=90)
    except Exception:  # noqa: BLE001
        pass
