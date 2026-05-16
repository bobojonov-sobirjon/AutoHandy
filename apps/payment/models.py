from __future__ import annotations

from django.conf import settings
from django.db import models


class SavedCardHolderRole(models.TextChoices):
    """Who owns the saved card for UX grouping (paying user vs master wallet)."""

    CLIENT = 'client', 'Client (driver / order owner)'
    MASTER = 'master', 'Master (provider)'


class SavedCard(models.Model):
    """Stripe PaymentMethod attached to a user (customer)."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='saved_cards',
        verbose_name='User',
    )
    holder_role = models.CharField(
        max_length=16,
        choices=SavedCardHolderRole.choices,
        default=SavedCardHolderRole.CLIENT,
        verbose_name='Holder role',
    )
    stripe_payment_method_id = models.CharField(max_length=64, verbose_name='Stripe PM id')
    stripe_customer_id = models.CharField(max_length=64, verbose_name='Stripe customer id')
    brand = models.CharField(max_length=32, blank=True, default='', verbose_name='Brand')
    last4 = models.CharField(max_length=4, blank=True, default='', verbose_name='Last4')
    exp_month = models.PositiveSmallIntegerField(null=True, blank=True, verbose_name='Exp month')
    exp_year = models.PositiveSmallIntegerField(null=True, blank=True, verbose_name='Exp year')
    funding = models.CharField(max_length=16, blank=True, default='', verbose_name='Funding')
    is_default = models.BooleanField(default=False, verbose_name='Default card')
    is_active = models.BooleanField(default=True, verbose_name='Active')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='Created at')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='Updated at')

    class Meta:
        verbose_name = 'Saved card'
        verbose_name_plural = 'Saved cards'
        ordering = ['-is_default', '-created_at']
        constraints = [
            models.UniqueConstraint(
                fields=('user', 'stripe_payment_method_id'),
                name='uniq_savedcard_user_pm',
            ),
        ]

    def __str__(self) -> str:
        return f'{self.user_id} {self.brand} *{self.last4}'
