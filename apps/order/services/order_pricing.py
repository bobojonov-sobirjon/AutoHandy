"""Order totals from line items + discount (amount or optional percent via settings)."""
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from django.conf import settings


def _q(x: Any) -> Decimal:
    return Decimal(str(x)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


def _order_car_count(order) -> int:
    """
    Multiply line-item service prices by how many cars are on the order (same work per vehicle).
    If no cars are linked yet, use 1 so totals stay usable.
    """
    try:
        n = order.car.count()
    except Exception:
        n = 0
    return max(1, n)


def _custom_request_offer_subtotal(order) -> Decimal | None:
    """If custom-request order has assigned master and their offer row, use offer price as subtotal base."""
    from apps.order.models import CustomRequestOffer, OrderType

    if getattr(order, 'order_type', None) != OrderType.CUSTOM_REQUEST:
        return None
    if not getattr(order, 'master_id', None) or not getattr(order, 'pk', None):
        return None
    price = None
    cache = getattr(order, '_prefetched_objects_cache', None)
    if cache and 'custom_request_offers' in cache:
        for o in cache['custom_request_offers']:
            if o.master_id == order.master_id:
                price = getattr(o, 'price', None)
                break
    if price is None:
        offer = (
            CustomRequestOffer.objects.filter(order_id=order.pk, master_id=order.master_id)
            .only('price')
            .first()
        )
        if offer is not None:
            price = offer.price
    if price is None:
        return None
    return _q(price)


def compute_order_price_breakdown(order) -> dict[str, Any]:
    """
    Sum prices from OrderService → master_service_item.price.

    **Custom request:** if ``order.master`` is set and a ``CustomRequestOffer`` exists for that
    order+master, **subtotal** is the offer price only (not multiplied by car count); discount
    rules on ``order.discount`` apply the same way.

    Discount (``order.discount``):
    - Default: fixed **amount** in the same currency as line prices, capped at subtotal,
      split across lines proportionally to each line price.
    - If ``settings.ORDER_DISCOUNT_IS_PERCENT`` is True and discount is in ``0..100``,
      treat as **percent** of subtotal; values ``> 100`` are still treated as fixed amount.
    """
    offer_subtotal = _custom_request_offer_subtotal(order)
    if offer_subtotal is not None:
        car_count = _order_car_count(order)
        subtotal = offer_subtotal
        raw = _q(order.discount or 0)
        if raw < 0:
            raw = Decimal('0')
        use_percent = bool(getattr(settings, 'ORDER_DISCOUNT_IS_PERCENT', False))
        if raw == 0:
            mode = 'none'
            discount_applied = Decimal('0')
        elif use_percent and raw <= Decimal('100'):
            mode = 'percent'
            discount_applied = _q(subtotal * raw / Decimal('100'))
        else:
            mode = 'amount'
            discount_applied = _q(min(raw, subtotal))
        total = _q(max(subtotal - discount_applied, Decimal('0')))
        return {
            'subtotal': subtotal,
            'discount_raw': raw,
            'discount_mode': mode,
            'discount_applied': discount_applied,
            'total': total,
            'car_count': car_count,
            'lines_by_order_service_id': {},
        }

    car_count = _order_car_count(order)
    rows: list[dict[str, Any]] = []
    subtotal = Decimal('0')

    for os_row in order.order_services.all().select_related('master_service_item').order_by('id'):
        item = os_row.master_service_item
        if not item:
            continue
        p = _q(item.price or 0)
        line_gross = _q(p * car_count)
        subtotal += line_gross
        rows.append({'os': os_row, 'unit_price_per_car': p, 'line_gross': line_gross})

    raw = _q(order.discount or 0)
    if raw < 0:
        raw = Decimal('0')

    use_percent = bool(getattr(settings, 'ORDER_DISCOUNT_IS_PERCENT', False))
    if raw == 0:
        mode = 'none'
        discount_applied = Decimal('0')
    elif use_percent and raw <= Decimal('100'):
        mode = 'percent'
        discount_applied = _q(subtotal * raw / Decimal('100'))
    else:
        mode = 'amount'
        discount_applied = _q(min(raw, subtotal))

    total = _q(max(subtotal - discount_applied, Decimal('0')))

    lines_out: list[dict[str, Any]] = []
    n = len(rows)
    acc_disc = Decimal('0')

    if not rows or discount_applied == 0:
        for r in rows:
            os_row = r['os']
            p = r['unit_price_per_car']
            lg = r['line_gross']
            lines_out.append(
                {
                    'order_service_id': os_row.id,
                    'unit_price': p,
                    'car_count': car_count,
                    'discount_allocated': Decimal('0'),
                    'line_total': lg,
                }
            )
    else:
        for i, r in enumerate(rows):
            os_row = r['os']
            p = r['unit_price_per_car']
            lg = r['line_gross']
            if i == n - 1:
                ld = _q(discount_applied - acc_disc)
            else:
                if mode == 'percent':
                    ld = _q(lg * raw / Decimal('100'))
                else:
                    ld = _q(lg / subtotal * discount_applied) if subtotal > 0 else Decimal('0')
                acc_disc += ld
            lt = _q(lg - ld)
            lines_out.append(
                {
                    'order_service_id': os_row.id,
                    'unit_price': p,
                    'car_count': car_count,
                    'discount_allocated': ld,
                    'line_total': lt,
                }
            )

    by_id = {x['order_service_id']: x for x in lines_out}
    return {
        'subtotal': subtotal,
        'discount_raw': raw,
        'discount_mode': mode,
        'discount_applied': discount_applied,
        'total': total,
        'car_count': car_count,
        'lines_by_order_service_id': by_id,
    }


def get_cached_order_pricing(order, context: dict) -> dict[str, Any]:
    """One breakdown per order per serialization (shared by pricing block + services lines)."""
    cache = context.setdefault('_order_pricing_by_id', {})
    key = order.pk if getattr(order, 'pk', None) is not None else id(order)
    if key not in cache:
        cache[key] = compute_order_price_breakdown(order)
    return cache[key]


def order_payable_total_str(order) -> str:
    """Order total after line-item discount rules (same as ``pricing.total``)."""
    bd = compute_order_price_breakdown(order)
    return format(bd['total'], 'f')


def estimate_cancellation_penalty_amount(order, penalty_percent: int) -> str:
    """
    Rough fee = ``order_payable_total * penalty_percent / 100`` (two decimals).
    Billing may use a different base; this mirrors the order ``pricing.total`` snapshot.
    """
    if penalty_percent <= 0:
        return '0.00'
    bd = compute_order_price_breakdown(order)
    amt = _q(bd['total'] * Decimal(penalty_percent) / Decimal('100'))
    return format(amt, 'f')
