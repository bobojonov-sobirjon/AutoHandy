"""Attach PaymentMethod to Customer and persist SavedCard."""
from __future__ import annotations

from django.db import transaction

from apps.payment.models import SavedCard, SavedCardHolderRole
from apps.payment.services.stripe_client import stripe_configured, stripe_sdk


class StripeCardError(Exception):
    def __init__(self, message: str):
        self.message = message
        super().__init__(message)


def _holder_role_for_user(user) -> str:
    try:
        if user.groups.filter(name='Master').exists():
            return SavedCardHolderRole.MASTER
    except Exception:
        pass
    return SavedCardHolderRole.CLIENT


def ensure_stripe_customer_id(user) -> tuple[str, bool]:
    """Return (cus_id, created_this_call)."""
    if not stripe_configured():
        raise StripeCardError('Stripe is not configured on the server.')
    stripe = stripe_sdk()
    existing = (getattr(user, 'stripe_customer_id', '') or '').strip()
    if existing:
        return existing, False
    cust = stripe.Customer.create(
        email=(user.email or None),
        name=(user.get_full_name() or None),
        metadata={'user_id': str(user.pk)},
    )
    cid = str(cust.id)
    from apps.accounts.models import CustomUser

    CustomUser.objects.filter(pk=user.pk).update(stripe_customer_id=cid)
    user.stripe_customer_id = cid
    return cid, True


def save_payment_method_for_user(
    *,
    user,
    payment_method_id: str,
    stripe_customer_id: str | None = None,
) -> SavedCard:
    if not stripe_configured():
        raise StripeCardError('Stripe is not configured on the server.')
    stripe = stripe_sdk()
    pm_id = (payment_method_id or '').strip()
    if not pm_id:
        raise StripeCardError('payment_method_id is required.')

    pm = stripe.PaymentMethod.retrieve(pm_id)
    cust_in = (stripe_customer_id or '').strip() or None
    if cust_in and cust_in != (getattr(user, 'stripe_customer_id', '') or '').strip():
        if (getattr(user, 'stripe_customer_id', '') or '').strip() and cust_in != user.stripe_customer_id:
            raise StripeCardError('stripe_customer_id does not match this account.')

    cus, _ = ensure_stripe_customer_id(user)
    if cust_in and cust_in != cus:
        raise StripeCardError('stripe_customer_id mismatch after ensure customer.')

    if not pm.customer:
        stripe.PaymentMethod.attach(pm_id, customer=cus)
        pm = stripe.PaymentMethod.retrieve(pm_id)
    elif str(pm.customer) != cus:
        raise StripeCardError('This payment method is already attached to another Stripe customer.')

    card = getattr(pm, 'card', None)
    brand = getattr(card, 'brand', '') or '' if card else ''
    last4 = getattr(card, 'last4', '') or '' if card else ''
    exp_month = getattr(card, 'exp_month', None) if card else None
    exp_year = getattr(card, 'exp_year', None) if card else None
    funding = getattr(card, 'funding', '') or '' if card else ''

    role = _holder_role_for_user(user)

    with transaction.atomic():
        sc, created = SavedCard.objects.select_for_update().get_or_create(
            user=user,
            stripe_payment_method_id=pm_id,
            defaults={
                'holder_role': role,
                'stripe_customer_id': cus,
                'brand': brand,
                'last4': last4,
                'exp_month': exp_month,
                'exp_year': exp_year,
                'funding': funding or '',
                'is_default': not SavedCard.objects.filter(user=user, is_active=True, holder_role=role).exists(),
                'is_active': True,
            },
        )
        if not created:
            sc.stripe_customer_id = cus
            sc.brand = brand
            sc.last4 = last4
            sc.exp_month = exp_month
            sc.exp_year = exp_year
            sc.funding = funding or ''
            sc.is_active = True
            sc.save(
                update_fields=[
                    'stripe_customer_id',
                    'brand',
                    'last4',
                    'exp_month',
                    'exp_year',
                    'funding',
                    'is_active',
                    'updated_at',
                ]
            )
        if sc.is_default:
            SavedCard.objects.filter(user=user, holder_role=role, is_active=True).exclude(pk=sc.pk).update(
                is_default=False
            )
    return sc


def set_default_card(user, card_pk: int) -> SavedCard:
    role = _holder_role_for_user(user)
    sc = SavedCard.objects.get(pk=card_pk, user=user, is_active=True, holder_role=role)
    with transaction.atomic():
        SavedCard.objects.filter(user=user, holder_role=role, is_active=True).update(is_default=False)
        sc.is_default = True
        sc.save(update_fields=['is_default', 'updated_at'])
    return sc


def detach_card(user, card_pk: int) -> None:
    role = _holder_role_for_user(user)
    sc = SavedCard.objects.get(pk=card_pk, user=user, holder_role=role)
    if stripe_configured():
        try:
            stripe_sdk().PaymentMethod.detach(sc.stripe_payment_method_id)
        except Exception:
            pass
    sc.is_active = False
    sc.is_default = False
    sc.save(update_fields=['is_active', 'is_default', 'updated_at'])
    nxt = (
        SavedCard.objects.filter(user=user, holder_role=role, is_active=True)
        .order_by('-created_at')
        .first()
    )
    if nxt:
        SavedCard.objects.filter(user=user, holder_role=role, is_active=True).exclude(pk=nxt.pk).update(
            is_default=False
        )
        nxt.is_default = True
        nxt.save(update_fields=['is_default', 'updated_at'])
