"""Unstick Complete when Stripe idempotency cached an insufficient-funds decline."""
from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from apps.order.models import Order, OrderStatus, OrderStripePaymentStatus
from apps.payment.services.order_charge import (
    StripeChargeError,
    _complete_charge_idempotency_key,
    charge_order_on_completion,
)
from apps.payment.services.stripe_client import stripe_configured


class Command(BaseCommand):
    help = (
        'Inspect / bump / retry the job charge for an order stuck after insufficient funds. '
        'After deploy, simply Complete again in the app often works (new idempotency key format). '
        'Use --bump if the order is still on a failed attempt key.'
    )

    def add_arguments(self, parser):
        parser.add_argument('order_id', type=int, help='Order primary key')
        parser.add_argument(
            '--bump',
            action='store_true',
            help='Increment stripe_charge_attempt so the next charge uses a fresh idempotency key',
        )
        parser.add_argument(
            '--charge',
            action='store_true',
            help='Attempt charge_order_on_completion now (does not mark order completed)',
        )
        parser.add_argument(
            '--complete',
            action='store_true',
            help='Charge and, on success, set order status=completed (support escape hatch)',
        )

    def handle(self, *args, **options):
        order_id = int(options['order_id'])
        try:
            order = Order.objects.select_related('user', 'master', 'saved_card').get(pk=order_id)
        except Order.DoesNotExist as exc:
            raise CommandError(f'Order {order_id} not found') from exc

        self.stdout.write(f'order_id:              {order.pk}')
        self.stdout.write(f'order_number:          {order.order_number or "-"}')
        self.stdout.write(f'status:                {order.status}')
        self.stdout.write(f'stripe_payment_status: {order.stripe_payment_status}')
        self.stdout.write(f'stripe_pi:             {order.stripe_payment_intent_id or "-"}')
        self.stdout.write(f'stripe_error:          {(order.stripe_payment_error or "-")[:300]}')
        self.stdout.write(f'stripe_charge_attempt: {order.stripe_charge_attempt}')
        self.stdout.write(f'next_idempotency_key:  {_complete_charge_idempotency_key(order)}')
        self.stdout.write('')

        if options['bump']:
            order.stripe_charge_attempt = max(1, int(order.stripe_charge_attempt or 1)) + 1
            if order.stripe_payment_status == OrderStripePaymentStatus.SUCCEEDED:
                self.stdout.write(self.style.WARNING('Order charge already SUCCEEDED — bump skipped.'))
            else:
                order.stripe_payment_status = OrderStripePaymentStatus.FAILED
                order.save(
                    update_fields=['stripe_charge_attempt', 'stripe_payment_status', 'updated_at']
                )
                self.stdout.write(
                    self.style.SUCCESS(
                        f'Bumped attempt → {order.stripe_charge_attempt}; '
                        f'key={_complete_charge_idempotency_key(order)}'
                    )
                )

        if options['charge'] or options['complete']:
            if not stripe_configured():
                raise CommandError('Stripe is not configured.')
            if order.stripe_payment_status == OrderStripePaymentStatus.SUCCEEDED and (
                order.stripe_payment_intent_id or ''
            ).startswith('pi_'):
                self.stdout.write(self.style.NOTICE('Charge already succeeded — skipping create.'))
            else:
                try:
                    charge_order_on_completion(order)
                    order.save(
                        update_fields=[
                            'saved_card',
                            'payment_type',
                            'stripe_payment_intent_id',
                            'stripe_payment_status',
                            'stripe_payment_amount_cents',
                            'stripe_payment_currency',
                            'stripe_payment_error',
                            'stripe_charge_attempt',
                            'updated_at',
                        ]
                    )
                    self.stdout.write(
                        self.style.SUCCESS(
                            f'Charge OK pi={order.stripe_payment_intent_id} '
                            f'amount_cents={order.stripe_payment_amount_cents}'
                        )
                    )
                except StripeChargeError as exc:
                    order.refresh_from_db()
                    raise CommandError(f'Charge failed: {exc.message}') from exc

            if options['complete']:
                if order.stripe_payment_status != OrderStripePaymentStatus.SUCCEEDED:
                    raise CommandError('Cannot complete — charge not succeeded.')
                if order.status == OrderStatus.COMPLETED:
                    self.stdout.write(self.style.NOTICE('Order already completed.'))
                else:
                    order.status = OrderStatus.COMPLETED
                    order.save(update_fields=['status', 'updated_at'])
                    self.stdout.write(self.style.SUCCESS('Order marked completed.'))

        if not options['bump'] and not options['charge'] and not options['complete']:
            self.stdout.write(
                'Tip: after deploy, ask master to Complete again (new key format). '
                'If still stuck: --bump then Complete in app, or --complete here.'
            )
