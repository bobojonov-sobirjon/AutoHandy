"""Order totals from line items + discount (amount or optional percent via settings)."""
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from django.conf import settings
from django.utils import timezone

try:
    from zoneinfo import ZoneInfo
except Exception:  # pragma: no cover
    ZoneInfo = None  # type: ignore[assignment]


def _q(x: Any) -> Decimal:
    return Decimal(str(x)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


def _order_penalty_total(order) -> Decimal:
    """Persisted penalties (cancel fees, etc.); non-negative for pricing."""
    try:
        v = getattr(order, 'order_penalty_total', None)
        if v is None:
            return Decimal('0')
        x = _q(v)
        return x if x > 0 else Decimal('0')
    except Exception:
        return Decimal('0')


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

    Penalties: ``order.order_penalty_total`` (non-negative) is added on top of the job total.
    Returned ``work_total`` is the job line (subtotal − discount + extra_money); ``total`` includes penalties.
    """
    extra_money = _q(getattr(order, 'extra_money', 0) or 0)
    offer_price = _custom_request_offer_subtotal(order)
    if offer_price is not None:
        # Custom-request pricing:
        # - offer_price is the base agreed amount (not multiplied by car_count)
        # - plus any added services (multiplied by car_count like standard orders)
        # - discount applies to the combined subtotal; discount is allocated proportionally across
        #   (offer + services) so totals stay consistent even though offer is not a service line.
        car_count = _order_car_count(order)
        rows: list[dict[str, Any]] = []
        services_subtotal = Decimal('0')

        for os_row in order.order_services.all().select_related('master_service_item').order_by('id'):
            item = os_row.master_service_item
            if not item:
                continue
            svc_count = int(getattr(os_row, 'count', 1) or 1)
            if svc_count < 1:
                svc_count = 1
            base_u = _q(item.price or 0)
            line_gross = _q(base_u * car_count * svc_count)
            services_subtotal += line_gross
            rows.append(
                {
                    'os': os_row,
                    'base_unit_price_per_car': base_u,
                    'car_count': car_count,
                    'service_count': svc_count,
                    'line_gross': line_gross,
                }
            )

        subtotal = _q(offer_price + services_subtotal)
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

        offer_discount_allocated = Decimal('0')
        lines_by_id: dict[int, dict[str, Any]] = {}

        if rows:
            n = len(rows)
            # Allocate discount proportionally across offer + services.
            # Offer has no OrderService row, so we store its allocation separately.
            if discount_applied and subtotal > 0:
                offer_discount_allocated = _q(discount_applied * offer_price / subtotal)
            remaining = _q(discount_applied - offer_discount_allocated)

            acc = Decimal('0')
            if remaining <= 0:
                remaining = Decimal('0')
            if services_subtotal <= 0:
                remaining = Decimal('0')

            for i, r in enumerate(rows):
                os_row = r['os']
                base_u = r['base_unit_price_per_car']
                lg = r['line_gross']
                if remaining == 0:
                    ld = Decimal('0')
                elif i == n - 1:
                    ld = _q(remaining - acc)
                else:
                    if mode == 'percent':
                        # Percent is based on the combined subtotal, but line allocation follows line gross.
                        ld = _q(lg / services_subtotal * remaining) if services_subtotal > 0 else Decimal('0')
                    else:
                        ld = _q(lg / services_subtotal * remaining) if services_subtotal > 0 else Decimal('0')
                    acc += ld
                lt = _q(max(lg - ld, Decimal('0')))
                lines_by_id[os_row.id] = {
                    'order_service_id': os_row.id,
                    'unit_price': base_u,  # custom-request: no emergency multiplier here
                    'base_unit_price': base_u,
                    'emergency_coefficient': _q(Decimal('1.0')),
                    'car_count': r.get('car_count', car_count),
                    'service_count': r.get('service_count', 1),
                    'discount_allocated': ld,
                    'line_total': lt,
                }
        else:
            # No services: discount allocation is fully on offer.
            offer_discount_allocated = discount_applied

        work_total = _q(
            max(
                (offer_price - offer_discount_allocated)
                + sum((v.get('line_total', Decimal('0')) for v in lines_by_id.values()), Decimal('0'))
                + extra_money,
                Decimal('0'),
            )
        )
        penalty_total = _order_penalty_total(order)
        total = _q(max(work_total + penalty_total, Decimal('0')))

        return {
            'offer_price': offer_price,
            'offer_discount_allocated': offer_discount_allocated,
            'services_subtotal': services_subtotal,
            'subtotal': subtotal,
            'extra_money': extra_money,
            'discount_raw': raw,
            'discount_mode': mode,
            'discount_applied': discount_applied,
            'work_total': work_total,
            'penalty_total': penalty_total,
            'total': total,
            'car_count': car_count,
            'lines_by_order_service_id': lines_by_id,
            'emergency': {
                'is_emergency': False,
                'time_zone': None,
                'time_bucket': None,
                'coefficient': _q(Decimal('1.0')),
                'note': None,
            },
        }

    # Emergency (SOS) pricing: day/night multipliers in America local time.
    from apps.order.models import OrderType

    emergency = {
        'is_emergency': bool(getattr(order, 'order_type', None) == OrderType.SOS),
        'time_zone': None,
        'time_bucket': None,
        'coefficient': Decimal('1.0'),
        'note': None,
    }
    if emergency['is_emergency']:
        tz_name = str(getattr(settings, 'EMERGENCY_TIME_ZONE', 'America/Los_Angeles') or 'America/Los_Angeles')
        coef_day = Decimal(str(getattr(settings, 'EMERGENCY_DAY_MULTIPLIER', 1.3)))
        coef_night = Decimal(str(getattr(settings, 'EMERGENCY_NIGHT_MULTIPLIER', 1.6)))
        dt = getattr(order, 'created_at', None) or timezone.now()
        if timezone.is_naive(dt):
            dt = timezone.make_aware(dt, timezone.get_current_timezone())
        local_dt = dt
        if ZoneInfo is not None:
            try:
                local_dt = dt.astimezone(ZoneInfo(tz_name))
                emergency['time_zone'] = tz_name
            except Exception:
                # Fallback: keep dt as-is; still apply multipliers based on its clock time.
                emergency['time_zone'] = None
        hhmm = (local_dt.hour, local_dt.minute)
        # Day: 06:00 (inclusive) → 23:00 (exclusive). Night: 23:00 → 06:00.
        is_day = (hhmm >= (6, 0)) and (hhmm < (23, 0))
        emergency['time_bucket'] = 'day' if is_day else 'night'
        emergency['coefficient'] = coef_day if is_day else coef_night
        emergency['note'] = 'Higher price due to urgency or time'

    car_count = _order_car_count(order)
    rows: list[dict[str, Any]] = []
    base_subtotal = Decimal('0')
    subtotal = Decimal('0')

    for os_row in order.order_services.all().select_related('master_service_item').order_by('id'):
        item = os_row.master_service_item
        if not item:
            continue
        svc_count = int(getattr(os_row, 'count', 1) or 1)
        if svc_count < 1:
            svc_count = 1
        base_p = _q(item.price or 0)
        line_base_gross = _q(base_p * car_count * svc_count)
        base_subtotal += line_base_gross
        rows.append(
            {
                'os': os_row,
                'base_unit_price_per_car': base_p,
                'car_count': car_count,
                'service_count': svc_count,
                'line_base_gross': line_base_gross,
            }
        )

    coef = (
        Decimal(str(emergency['coefficient'] or Decimal('1.0')))
        if emergency['is_emergency']
        else Decimal('1.0')
    )
    # Apply SOS multiplier once on the summed base subtotal.
    subtotal = _q(base_subtotal * _q(coef))

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

    work_total = _q(max(subtotal - discount_applied + extra_money, Decimal('0')))
    penalty_total = _order_penalty_total(order)
    total = _q(max(work_total + penalty_total, Decimal('0')))

    lines_out: list[dict[str, Any]] = []
    n = len(rows)
    acc_disc = Decimal('0')

    if not rows or discount_applied == 0:
        for r in rows:
            os_row = r['os']
            base_u = r['base_unit_price_per_car']
            base_g = r['line_base_gross']
            unit_final = _q(base_u * _q(coef))
            lg = _q(base_g * _q(coef))
            lines_out.append(
                {
                    'order_service_id': os_row.id,
                    'unit_price': unit_final,
                    'base_unit_price': base_u,
                    'emergency_coefficient': _q(coef),
                    'car_count': r.get('car_count', car_count),
                    'service_count': r.get('service_count', 1),
                    'discount_allocated': Decimal('0'),
                    'line_total': lg,
                }
            )
    else:
        for i, r in enumerate(rows):
            os_row = r['os']
            base_u = r['base_unit_price_per_car']
            base_g = r['line_base_gross']
            unit_final = _q(base_u * _q(coef))
            lg = _q(base_g * _q(coef))
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
                    'unit_price': unit_final,
                    'base_unit_price': base_u,
                    'emergency_coefficient': _q(coef),
                    'car_count': r.get('car_count', car_count),
                    'service_count': r.get('service_count', 1),
                    'discount_allocated': ld,
                    'line_total': lt,
                }
            )

    by_id = {x['order_service_id']: x for x in lines_out}
    return {
        'base_subtotal': base_subtotal,
        'subtotal': subtotal,
        'extra_money': extra_money,
        'discount_raw': raw,
        'discount_mode': mode,
        'discount_applied': discount_applied,
        'work_total': work_total,
        'penalty_total': penalty_total,
        'total': total,
        'car_count': car_count,
        'lines_by_order_service_id': by_id,
        'emergency': emergency,
    }


def get_cached_order_pricing(order, context: dict) -> dict[str, Any]:
    """One breakdown per order per serialization (shared by pricing block + services lines)."""
    cache = context.setdefault('_order_pricing_by_id', {})
    key = order.pk if getattr(order, 'pk', None) is not None else id(order)
    if key not in cache:
        cache[key] = compute_order_price_breakdown(order)
    return cache[key]


def order_payable_total_str(order) -> str:
    """Full payable total: job line (after discount rules) plus ``order_penalty_total``."""
    bd = compute_order_price_breakdown(order)
    return format(bd['total'], 'f')


def estimate_cancellation_penalty_amount(order, penalty_percent: int) -> str:
    """
    Rough fee = ``pricing.work_total * penalty_percent / 100`` (two decimals).
    Uses job subtotal (services/offer + extra − discount), excluding any existing ``order_penalty_total``.
    """
    if penalty_percent <= 0:
        return '0.00'
    bd = compute_order_price_breakdown(order)
    base = bd.get('work_total')
    if base is None:
        base = _q(Decimal(str(bd['total'])) - Decimal(str(bd.get('penalty_total', 0))))
    amt = _q(base * Decimal(penalty_percent) / Decimal('100'))
    return format(amt, 'f')
