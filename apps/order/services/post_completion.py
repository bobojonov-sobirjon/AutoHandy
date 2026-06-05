"""Post-completion UX metadata (review + tip prompt) for completed orders."""
from __future__ import annotations

from decimal import Decimal
from typing import Any

from django.conf import settings

from apps.order.models import Order, OrderStatus, OrderStripePaymentStatus, Review


def tip_preset_amounts() -> list[int]:
    raw = (getattr(settings, 'TIP_PRESET_AMOUNTS', '5,10,20') or '5,10,20').strip()
    out: list[int] = []
    for part in raw.split(','):
        part = part.strip()
        if not part:
            continue
        try:
            out.append(int(Decimal(part)))
        except Exception:
            continue
    return out or [5, 10, 20]


def _tip_paid(order: Order) -> bool:
    return order.tip_stripe_payment_status == OrderStripePaymentStatus.SUCCEEDED


def build_post_completion_payload(order: Order) -> dict[str, Any] | None:
    """
    Driver-only hints for the post-completion flow:
    review screen, rating, and tip modal ($5 / $10 / $20 / Other / No Thanks).
    """
    if order.status != OrderStatus.COMPLETED:
        return None

    has_review = Review.objects.filter(order_id=order.pk).exists()
    tip_paid = _tip_paid(order)
    tip_declined = bool(order.tip_declined)
    needs_tip_prompt = not tip_paid and not tip_declined

    return {
        'needs_review': not has_review,
        'needs_tip_prompt': needs_tip_prompt,
        'review_submitted': has_review,
        'tip_presets': tip_preset_amounts(),
        'tip_amount': format(order.tip_amount or Decimal('0'), 'f'),
        'tip_paid': tip_paid,
        'tip_declined': tip_declined,
        'tip_prompt_title': 'Would you like to leave a tip for your provider?',
    }
