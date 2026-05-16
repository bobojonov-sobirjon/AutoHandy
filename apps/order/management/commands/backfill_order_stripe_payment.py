"""Backfill Order.stripe_* from Stripe when complete-save missed them (historical bug)."""
from __future__ import annotations

from django.core.management.base import BaseCommand

from apps.order.models import Order, OrderStatus, OrderStripePaymentStatus
from apps.payment.services.stripe_client import stripe_configured, stripe_sdk


class Command(BaseCommand):
    help = (
        'Set stripe_payment_* on an order from a Stripe PaymentIntent '
        '(metadata order_id must match). Use when complete succeeded in Stripe but DB fields stayed empty.'
    )

    def add_arguments(self, parser):
        parser.add_argument('order_id', type=int, help='Order primary key')
        parser.add_argument(
            '--payment-intent',
            dest='payment_intent',
            default='',
            help='PaymentIntent id (pi_…). If omitted, searches Stripe by metadata order_id.',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Print what would be updated without saving',
        )

    def handle(self, *args, **options):
        if not stripe_configured():
            self.stderr.write('Stripe is not configured (STRIPE_SECRET_KEY).')
            return

        order_id = int(options['order_id'])
        pi_id = (options.get('payment_intent') or '').strip()
        dry = bool(options.get('dry_run'))

        try:
            order = Order.objects.get(pk=order_id)
        except Order.DoesNotExist:
            self.stderr.write(f'Order {order_id} not found.')
            return

        stripe = stripe_sdk()
        pi = None

        if pi_id:
            try:
                pi = stripe.PaymentIntent.retrieve(pi_id)
            except Exception as exc:  # noqa: BLE001
                self.stderr.write(f'Could not retrieve {pi_id}: {exc}')
                return
        else:
            q = f"metadata['order_id']:'{order_id}'"
            try:
                res = stripe.PaymentIntent.search(query=q, limit=10)
            except Exception as exc:  # noqa: BLE001
                self.stderr.write(
                    f'PaymentIntent.search failed: {exc}\n'
                    f'Pass --payment-intent pi_… from Stripe Dashboard (PaymentIntent metadata order_id).'
                )
                return
            rows = list(getattr(res, 'data', []) or [])
            succeeded = [p for p in rows if (getattr(p, 'status', '') or '') == 'succeeded']
            candidates = succeeded or rows
            if not candidates:
                self.stderr.write(f'No PaymentIntent found for query {q!r}. Use --payment-intent pi_…')
                return
            pi = candidates[0]
            if len(candidates) > 1:
                self.stdout.write(
                    self.style.WARNING(
                        f'Multiple matches ({len(candidates)}); using latest in page: {getattr(pi, "id", "")}'
                    )
                )

        meta = getattr(pi, 'metadata', None) or {}
        mid = meta.get('order_id') if isinstance(meta, dict) else getattr(meta, 'get', lambda k: None)('order_id')
        if str(mid or '') != str(order_id):
            self.stderr.write(
                f'PaymentIntent metadata order_id={mid!r} does not match requested order {order_id}. Abort.'
            )
            return

        st = (getattr(pi, 'status', '') or '').strip()
        if st != 'succeeded':
            self.stderr.write(f'PaymentIntent status is {st!r}, not succeeded. Abort.')
            return

        amt = int(getattr(pi, 'amount', 0) or 0)
        cur = (getattr(pi, 'currency', '') or '').lower()
        pid = str(getattr(pi, 'id', '') or '')

        self.stdout.write(
            f'Order {order_id}: will set pi={pid} amount_cents={amt} currency={cur} status=succeeded '
            f'(current order.status={order.status})'
        )

        if dry:
            return

        order.stripe_payment_intent_id = pid
        order.stripe_payment_status = OrderStripePaymentStatus.SUCCEEDED
        order.stripe_payment_amount_cents = amt
        order.stripe_payment_currency = cur
        order.stripe_payment_error = ''
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
        self.stdout.write(self.style.SUCCESS(f'Updated order {order_id}.'))
