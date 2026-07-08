"""Diagnose client cancel penalty for a cancelled (or active) order."""
from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from apps.order.models import Order
from apps.order.services.order_pricing import estimate_cancellation_penalty_amount, order_payable_total_str
from apps.order.services.status_workflow import client_cancellation_snapshot
from apps.payment.services.cancellation_penalty_charge import resolve_client_saved_card


class Command(BaseCommand):
    help = 'Show cancellation policy + penalty charge state for an order (support / debug).'

    def add_arguments(self, parser):
        parser.add_argument('order_id', type=int, help='Order primary key')
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Only print policy; do not attempt a penalty charge retry.',
        )

    def handle(self, *args, **options):
        order_id = options['order_id']
        try:
            order = Order.objects.select_related('user', 'saved_card', 'master').get(pk=order_id)
        except Order.DoesNotExist as exc:
            raise CommandError(f'Order {order_id} not found') from exc

        snap = client_cancellation_snapshot(order)
        card = resolve_client_saved_card(order)

        self.stdout.write(f'order_id:        {order.pk}')
        self.stdout.write(f'order_type:      {order.order_type}')
        self.stdout.write(f'status:          {order.status}')
        self.stdout.write(f'truck:           {order.truck_make_model or "-"}')
        self.stdout.write(f'towing_total:    {order.towing_total}')
        self.stdout.write(f'work_total est:  {order_payable_total_str(order)}')
        self.stdout.write('')
        self.stdout.write('--- cancellation policy (current status) ---')
        self.stdout.write(f'client_can_cancel:  {snap["client_can_cancel"]}')
        self.stdout.write(f'penalty_applies:    {snap["penalty_applies"]}')
        self.stdout.write(f'penalty_percent:    {snap["penalty_percent"]}')
        self.stdout.write(f'tier:               {snap["tier"]}')
        self.stdout.write(f'summary:            {snap["summary"]}')
        if snap['penalty_applies']:
            est = estimate_cancellation_penalty_amount(order, int(snap['penalty_percent'] or 0))
            self.stdout.write(f'penalty_estimate:   {est} ({snap["penalty_percent"]}% of job total)')
        self.stdout.write('')
        self.stdout.write('--- payment / card ---')
        self.stdout.write(f'order.saved_card_id: {order.saved_card_id}')
        self.stdout.write(f'resolve_card:        {card.id if card else None} ({card.last4 if card else "NONE"})')
        self.stdout.write(f'order_penalty_total: {order.order_penalty_total}')
        self.stdout.write(f'stripe_status:       {order.stripe_payment_status}')
        self.stdout.write(f'stripe_pi:           {order.stripe_payment_intent_id or "-"}')
        self.stdout.write(f'stripe_error:        {order.stripe_payment_error or "-"}')
        self.stdout.write(f'stripe_amount_cents: {order.stripe_payment_amount_cents}')

        if options['dry_run']:
            return

        if not snap['penalty_applies']:
            self.stdout.write(self.style.WARNING('\nNo penalty applies at current status.'))
            return

        if order.order_penalty_total and order.order_penalty_total > 0:
            self.stdout.write(self.style.NOTICE('\n--- retry charge (if not yet succeeded) ---'))
            from apps.order.services.client_cancel_penalty import collect_pending_cancellation_penalty

            ok = collect_pending_cancellation_penalty(order)
            order.refresh_from_db()
            self.stdout.write(f'retry_succeeded:     {ok}')
            self.stdout.write(f'stripe_status after:  {order.stripe_payment_status}')
            self.stdout.write(f'stripe_error after:   {order.stripe_payment_error or "-"}')
            return

        self.stdout.write(self.style.NOTICE('\n--- simulate penalty apply (does not cancel order) ---'))
        self.stdout.write('Order is not cancelled yet; showing what cancel would charge:')
        est = estimate_cancellation_penalty_amount(order, int(snap['penalty_percent'] or 0))
        self.stdout.write(f'would_charge_about: {est}')
        if not card:
            self.stdout.write(
                self.style.ERROR(
                    'BLOCKER: no saved client card — cancel would record fee but card charge would fail.'
                )
            )
