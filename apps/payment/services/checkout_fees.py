"""Customer totals and master payout from order pricing + configurable fees."""
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from django.conf import settings

from apps.order.models import OrderType
from apps.order.services.order_pricing import compute_order_price_breakdown


def _q(x: Decimal) -> Decimal:
    return x.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


def _money(amount: Decimal) -> str:
    return f"{_q(amount):.2f}"


def _dec_setting(name: str, default: str) -> Decimal:
    return Decimal(str(getattr(settings, name, default)))


def money_to_cents(amount: Decimal) -> int:
    return int((amount * Decimal('100')).quantize(Decimal('1'), rounding=ROUND_HALF_UP))


def _order_uses_emergency_marketplace_fees(order, breakdown: dict[str, Any] | None = None) -> bool:
    ot = getattr(order, 'order_type', None)
    if ot in (OrderType.SOS, OrderType.TOWING):
        return True
    if breakdown is None:
        breakdown = compute_order_price_breakdown(order)
    return bool((breakdown.get('emergency') or {}).get('is_emergency'))


def _marketplace_surcharges(
    tech: Decimal,
    *,
    is_emergency: bool,
    penalty: Decimal = Decimal('0'),
) -> dict[str, Any]:
    prov_pct = _dec_setting('PROVIDER_PLATFORM_FEE_PERCENT', '10')
    master_payout = _q(tech * (Decimal('100') - prov_pct) / Decimal('100'))

    if is_emergency:
        d_pct = _dec_setting('EMERGENCY_DISPATCH_FEE_PERCENT', '6')
        s_pct = _dec_setting('CUSTOMER_SERVICE_FEE_PERCENT_EMERGENCY', '5')
        dispatch_fee = _q(tech * d_pct / Decimal('100'))
        service_fee = _q(tech * s_pct / Decimal('100'))
        platform_fee = Decimal('0')
    else:
        dispatch_fee = Decimal('0')
        s_pct = _dec_setting('CUSTOMER_SERVICE_FEE_PERCENT_SCHEDULED', '4')
        client_platform_pct = _dec_setting('CUSTOMER_PLATFORM_FEE_PERCENT_SCHEDULED', '4')
        service_fee = _q(tech * s_pct / Decimal('100'))
        platform_fee = _q(tech * client_platform_pct / Decimal('100'))

    master_platform_fee = _q(tech - master_payout)
    customer_total = _q(tech + dispatch_fee + service_fee + platform_fee + penalty)
    platform_gross = _q(customer_total - master_payout)
    return {
        'technician_total': _money(tech),
        'penalty_total': _money(penalty),
        'is_emergency': is_emergency,
        'dispatch_fee': _money(dispatch_fee),
        'service_fee': _money(service_fee),
        'platform_fee': _money(platform_fee),
        'master_platform_fee': _money(master_platform_fee),
        'platform_fee_line': _money(platform_fee),
        'customer_total': _money(customer_total),
        'master_estimated_payout': _money(master_payout),
        'platform_estimated_gross': _money(platform_gross),
        '_customer_total_decimal': customer_total,
        '_master_payout_decimal': master_payout,
        '_technician_total_decimal': tech,
        '_penalty_decimal': penalty,
    }


def preview_marketplace_fees_for_work_total(
    work_total: Decimal | str | float,
    *,
    is_emergency: bool,
) -> dict[str, Any]:
    """Fee preview for estimates (no order row). Omits internal ``_*_decimal`` keys."""
    surcharges = _marketplace_surcharges(
        _q(Decimal(str(work_total))),
        is_emergency=is_emergency,
    )
    return {k: v for k, v in surcharges.items() if not k.startswith('_')}


def compute_marketplace_checkout(order) -> dict[str, Any]:
    """
    Returns technician_total (job subtotal after discount rules), optional penalty_total,
    customer surcharges, customer charge (includes penalties), master_payout (from job subtotal only),
    platform_gross (before Stripe processing).
    """
    bd = compute_order_price_breakdown(order)
    work = _q(Decimal(str(bd['work_total'])))
    penalty = _q(Decimal(str(bd.get('penalty_total', 0))))
    is_emergency = _order_uses_emergency_marketplace_fees(order, bd)
    return _marketplace_surcharges(work, is_emergency=is_emergency, penalty=penalty)


def customer_charge_cents(order) -> int:
    d = compute_marketplace_checkout(order)['_customer_total_decimal']
    return money_to_cents(d)


def master_payout_cents(order) -> int:
    d = compute_marketplace_checkout(order)['_master_payout_decimal']
    return money_to_cents(d)


def order_pricing_platform_fee(order) -> str:
    """Unified client platform fee amount (standard / custom_request / SOS)."""
    return compute_marketplace_checkout(order)['platform_fee']


def build_order_marketplace_fee_display(order) -> dict[str, Any]:
    """
    Human-readable fee breakdown for order details (driver vs master / TZ).

    Aligns with: scheduled (standard + custom_request) vs emergency (SOS);
    uses the same arithmetic as ``compute_marketplace_checkout``.
    """
    br = compute_order_price_breakdown(order)
    ck = compute_marketplace_checkout(order)

    ot = getattr(order, 'order_type', None)
    is_sos = ot == OrderType.SOS
    is_towing = ot == OrderType.TOWING
    is_custom = ot == OrderType.CUSTOM_REQUEST

    if is_sos:
        pricing_mode = 'emergency'
    elif is_towing:
        pricing_mode = 'emergency_towing'
    elif is_custom:
        pricing_mode = 'scheduled_custom_request'
    else:
        pricing_mode = 'scheduled_standard'

    em = br.get('emergency') or {}
    coef = _q(Decimal(str(em.get('coefficient', '1.0'))))

    raw_base = br.get('base_subtotal')
    if raw_base is None:
        base_catalog = Decimal('0')
    else:
        base_catalog = _q(Decimal(str(raw_base)))

    sub_after_coef = _q(Decimal(str(br.get('subtotal', 0))))
    work_total = _q(Decimal(str(br.get('work_total', 0))))
    discount_applied = _q(Decimal(str(br.get('discount_applied', 0))))
    penalty = _q(Decimal(str(br.get('penalty_total', 0))))
    extra_money = _q(Decimal(str(br.get('extra_money', 0))))
    car_count = int(br.get('car_count', 1) or 1)

    if is_custom:
        offer_p = br.get('offer_price')
        svc_sub = br.get('services_subtotal')
        combined_catalog = _q(Decimal(str(offer_p or 0)) + Decimal(str(svc_sub or 0)))
        base_price_display = format(combined_catalog, 'f')
        custom_offer_only = format(_q(Decimal(str(offer_p or 0))), 'f') if offer_p is not None else None
        services_subtotal_only = format(_q(Decimal(str(svc_sub or 0))), 'f') if svc_sub is not None else None
    else:
        base_price_display = format(base_catalog, 'f')
        custom_offer_only = None
        services_subtotal_only = None

    emergency_adjusted_subtotal = format(sub_after_coef, 'f') if is_sos else None
    time_bucket = em.get('time_bucket')
    tz_name = em.get('time_zone')

    platform_fee = ck['platform_fee']
    master_platform_fee = ck['master_platform_fee']

    customer_total = ck['customer_total']
    from apps.order.models import OrderStatus, OrderStripePaymentStatus

    cents = getattr(order, 'stripe_payment_amount_cents', None) or 0
    if (
        getattr(order, 'status', None) == OrderStatus.COMPLETED
        and getattr(order, 'stripe_payment_status', None) == OrderStripePaymentStatus.SUCCEEDED
        and int(cents) > 0
    ):
        customer_total = format(_q(Decimal(int(cents)) / Decimal('100')), 'f')

    return {
        'platform_fee': platform_fee,
        'pricing_mode': pricing_mode,
        'uses_emergency_multiplier': bool(em.get('is_emergency')),
        'emergency': {
            'time_zone': tz_name,
            'time_bucket': time_bucket,
            'coefficient': format(coef, 'f'),
            'note': em.get('note'),
        },
        'master': {
            'base_catalog_subtotal': base_price_display,
            'custom_request_offer_price': custom_offer_only,
            'custom_request_services_subtotal': services_subtotal_only,
            'emergency_adjusted_subtotal_before_discount': emergency_adjusted_subtotal,
            'discount_applied': format(discount_applied, 'f'),
            'extra_money': format(extra_money, 'f'),
            'technician_work_total': format(work_total, 'f'),
            'estimated_payout': ck['master_estimated_payout'],
            'platform_fee': master_platform_fee,
            'car_count': car_count,
        },
        'client': {
            'technician_price': ck['technician_total'],
            'emergency_dispatch_fee': ck['dispatch_fee'],
            'service_fee': ck['service_fee'],
            'platform_fee': platform_fee,
            'penalty_total': ck['penalty_total'],
            'total': customer_total,
        },
        'stripe_charge_alignment': {
            'customer_charge_matches': 'client.total (when paid by card on complete)',
        },
        'notes': {
            'scheduled_fees': 'Service fee + platform fee (% of technician price); no emergency coefficient.',
            'emergency_fees': 'Dispatch + service fee (% of emergency-adjusted technician price); no separate platform fee line.',
            'penalty': 'Added to client total when order.order_penalty_total > 0; payout math unchanged in Stripe (see platform fee).',
        },
    }
