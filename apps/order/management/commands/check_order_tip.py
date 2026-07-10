"""Diagnose tip charges vs marketplace fees (prod support / client disputes)."""
from __future__ import annotations

from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError
from django.db.models import Q
from django.utils import timezone

from apps.order.models import Order, OrderStripePaymentStatus
from apps.payment.services.checkout_fees import (
    build_order_marketplace_fee_display,
    build_order_tip_display,
    compute_marketplace_checkout,
    compute_tip_marketplace_checkout,
    customer_charge_cents,
    customer_tip_charge_cents,
    master_payout_cents,
    master_tip_payout_cents,
    money_to_cents,
    order_tip_is_paid,
)
from apps.payment.services.stripe_client import stripe_configured, stripe_sdk


def _cents_to_money(cents: int | None) -> str:
    if not cents:
        return '-'
    return f'${Decimal(int(cents)) / Decimal("100"):.2f}'


def _analyze_order(order: Order, *, fetch_stripe: bool = False) -> dict:
    issues: list[str] = []
    tip_paid = order_tip_is_paid(order)

    job_expected_cents = customer_charge_cents(order)
    job_actual_cents = int(order.stripe_payment_amount_cents or 0)
    tip_base = Decimal(str(order.tip_amount or 0))
    tip_expected_cents = customer_tip_charge_cents(order, tip_base) if tip_base > 0 else 0
    tip_actual_cents = int(order.tip_stripe_payment_amount_cents or 0)
    tip_base_cents = money_to_cents(tip_base) if tip_base > 0 else 0

    if tip_paid:
        if tip_actual_cents <= 0:
            issues.append('MISSING_TIP_CHARGE_CENTS (DB field empty — likely old code path)')
        elif tip_actual_cents == tip_base_cents:
            issues.append('TIP_CHARGED_WITHOUT_CUSTOMER_FEE (Stripe amount = tip base only)')
        elif tip_actual_cents != tip_expected_cents:
            issues.append(
                f'TIP_CHARGE_MISMATCH (DB {tip_actual_cents}c vs expected {tip_expected_cents}c)'
            )

    if (
        order.stripe_payment_status == OrderStripePaymentStatus.SUCCEEDED
        and job_actual_cents > 0
        and job_actual_cents != job_expected_cents
    ):
        issues.append(
            f'JOB_CHARGE_MISMATCH (DB {job_actual_cents}c vs expected {job_expected_cents}c)'
        )

    fees = build_order_marketplace_fee_display(order)
    tip_display = build_order_tip_display(order)

    stripe_job_pi = None
    stripe_tip_pi = None
    if fetch_stripe and stripe_configured():
        stripe = stripe_sdk()
        if order.stripe_payment_intent_id:
            try:
                stripe_job_pi = stripe.PaymentIntent.retrieve(order.stripe_payment_intent_id)
            except Exception as exc:  # noqa: BLE001
                issues.append(f'STRIPE_JOB_PI_ERROR: {exc}')
        if order.tip_stripe_payment_intent_id:
            try:
                stripe_tip_pi = stripe.PaymentIntent.retrieve(order.tip_stripe_payment_intent_id)
            except Exception as exc:  # noqa: BLE001
                issues.append(f'STRIPE_TIP_PI_ERROR: {exc}')

        if stripe_tip_pi is not None and tip_paid:
            live_cents = int(getattr(stripe_tip_pi, 'amount', 0) or 0)
            if live_cents == tip_base_cents:
                issues.append('STRIPE_TIP_NO_CUSTOMER_FEE (live PI amount = tip base)')
            elif live_cents != tip_expected_cents:
                issues.append(
                    f'STRIPE_TIP_AMOUNT_MISMATCH (live {live_cents}c vs expected {tip_expected_cents}c)'
                )
            app_fee = getattr(stripe_tip_pi, 'application_fee_amount', None)
            exp_app_fee = max(0, tip_expected_cents - master_tip_payout_cents(order, tip_base))
            if tip_paid and exp_app_fee > 0 and not app_fee:
                issues.append('STRIPE_TIP_NO_APPLICATION_FEE (master Connect tip has no platform cut)')

    return {
        'order': order,
        'tip_paid': tip_paid,
        'issues': issues,
        'job_expected_cents': job_expected_cents,
        'job_actual_cents': job_actual_cents,
        'tip_base': tip_base,
        'tip_expected_cents': tip_expected_cents,
        'tip_actual_cents': tip_actual_cents,
        'fees': fees,
        'tip_display': tip_display,
        'stripe_job_pi': stripe_job_pi,
        'stripe_tip_pi': stripe_tip_pi,
    }


class Command(BaseCommand):
    help = (
        'Inspect tip + job Stripe charges for completed orders. '
        'Flags tips billed without customer fee (old backend) or missing DB fields.'
    )

    def add_arguments(self, parser):
        parser.add_argument('order_id', type=int, nargs='?', help='Order primary key')
        parser.add_argument('--order-number', type=str, default='', help='Order number (e.g. ORD-…) ')
        parser.add_argument(
            '--recent',
            type=int,
            default=0,
            metavar='N',
            help='Scan last N completed orders that have a paid tip (no order_id needed)',
        )
        parser.add_argument(
            '--issues-only',
            action='store_true',
            help='With --recent, print only orders that have diagnostic issues',
        )
        parser.add_argument(
            '--stripe',
            action='store_true',
            help='Fetch PaymentIntent amounts from Stripe API and compare',
        )
        parser.add_argument(
            '--phone',
            type=str,
            default='',
            help='Filter --recent by customer phone contains (digits only match)',
        )

    def handle(self, *args, **options):
        order_id = options.get('order_id')
        order_number = (options.get('order_number') or '').strip()
        recent = int(options.get('recent') or 0)
        issues_only = bool(options.get('issues_only'))
        fetch_stripe = bool(options.get('stripe'))
        phone = ''.join(ch for ch in (options.get('phone') or '') if ch.isdigit())

        if fetch_stripe and not stripe_configured():
            raise CommandError('Stripe is not configured (STRIPE_SECRET_KEY).')

        if order_id or order_number:
            order = self._load_one(order_id, order_number)
            self._print_report(_analyze_order(order, fetch_stripe=fetch_stripe))
            return

        if recent <= 0:
            raise CommandError('Provide order_id, --order-number, or --recent N')

        qs = (
            Order.objects.filter(
                status='completed',
                tip_stripe_payment_status=OrderStripePaymentStatus.SUCCEEDED,
                tip_amount__gt=0,
            )
            .select_related('user', 'master', 'master__user')
            .order_by('-tip_paid_at', '-updated_at')
        )
        if phone:
            qs = qs.filter(
                Q(user__phone__icontains=phone) | Q(user__username__icontains=phone)
            )

        rows = list(qs[:recent])
        if not rows:
            self.stdout.write(self.style.WARNING('No completed orders with paid tips found.'))
            return

        self.stdout.write(
            f'Scanning {len(rows)} order(s) with paid tips (as of {timezone.now().isoformat()})\n'
        )
        issue_count = 0
        for order in rows:
            report = _analyze_order(order, fetch_stripe=fetch_stripe)
            if issues_only and not report['issues']:
                continue
            if report['issues']:
                issue_count += 1
            self._print_report(report, compact=True)
            self.stdout.write('-' * 72)

        self.stdout.write(
            self.style.NOTICE(f'\nDone. {issue_count} order(s) with issues out of {len(rows)} scanned.')
        )

    def _load_one(self, order_id: int | None, order_number: str) -> Order:
        qs = Order.objects.select_related('user', 'master', 'master__user')
        if order_id:
            try:
                return qs.get(pk=order_id)
            except Order.DoesNotExist as exc:
                raise CommandError(f'Order {order_id} not found') from exc
        if order_number:
            try:
                return qs.get(order_number=order_number)
            except Order.DoesNotExist as exc:
                raise CommandError(f'Order number {order_number!r} not found') from exc
        raise CommandError('order_id or --order-number required')

    def _print_report(self, report: dict, *, compact: bool = False) -> None:
        order: Order = report['order']
        fees = report['fees']
        tip_display = report['tip_display']
        issues = report['issues']

        self.stdout.write(f'order_id:       {order.pk}')
        self.stdout.write(f'order_number:   {order.order_number or "-"}')
        self.stdout.write(f'status:         {order.status}')
        self.stdout.write(f'order_type:     {order.order_type}')
        self.stdout.write(f'customer:       {order.user_id} / {getattr(order.user, "phone", "") or "-"}')
        if order.master_id:
            self.stdout.write(
                f'master:         {order.master_id} / {getattr(order.master.user, "phone", "") or "-"}'
            )
        self.stdout.write(f'completed/upd:  {order.updated_at}')
        self.stdout.write('')

        ck = compute_marketplace_checkout(order)
        self.stdout.write('--- job payment ---')
        self.stdout.write(f'work_total:           {ck["technician_total"]}')
        self.stdout.write(f'customer_total (calc):  {ck["customer_total"]}')
        self.stdout.write(f'master_payout (calc):   {ck["master_estimated_payout"]}')
        self.stdout.write(
            f'stripe job charge:      {_cents_to_money(report["job_actual_cents"])} '
            f'({report["job_actual_cents"]}c, expected {report["job_expected_cents"]}c)'
        )
        self.stdout.write(f'stripe job PI:          {order.stripe_payment_intent_id or "-"}')
        self.stdout.write('')

        self.stdout.write('--- tip payment ---')
        self.stdout.write(f'tip_paid:               {report["tip_paid"]}')
        self.stdout.write(f'tip_declined:           {order.tip_declined}')
        self.stdout.write(f'tip_base:               ${report["tip_base"]:.2f}')
        if report['tip_base'] > 0:
            tip_ck = compute_tip_marketplace_checkout(order, report['tip_base'])
            self.stdout.write(f'tip customer (calc):    {tip_ck["customer_total"]}')
            self.stdout.write(f'tip master (calc):     {tip_ck["master_estimated_payout"]}')
        self.stdout.write(
            f'stripe tip charge:      {_cents_to_money(report["tip_actual_cents"])} '
            f'({report["tip_actual_cents"]}c, expected {report["tip_expected_cents"]}c)'
        )
        self.stdout.write(f'tip_stripe_payment_amount_cents in DB: {order.tip_stripe_payment_amount_cents}')
        self.stdout.write(f'stripe tip PI:          {order.tip_stripe_payment_intent_id or "-"}')
        self.stdout.write(f'tip_paid_at:            {order.tip_paid_at or "-"}')
        self.stdout.write('')

        if not compact:
            self.stdout.write('--- API totals (what mobile should show) ---')
        self.stdout.write(f'client.total (job):     {fees["client"]["total"]}')
        self.stdout.write(f'client.grand_total:     {fees["client"]["grand_total"]}')
        self.stdout.write(f'master.estimated_payout: {fees["master"]["estimated_payout"]}')
        self.stdout.write(f'master.grand_payout:    {fees["master"]["grand_payout"]}')
        if tip_display:
            self.stdout.write(f'tip.base_amount:        {tip_display["base_amount"]}')
            self.stdout.write(f'tip.customer_charge:    {tip_display["customer_charge"]}')
            self.stdout.write(f'tip.master_payout:      {tip_display["master_payout"]}')
        else:
            self.stdout.write('tip:                    (none / not paid)')
        self.stdout.write('')

        if report.get('stripe_job_pi') is not None:
            pi = report['stripe_job_pi']
            self.stdout.write('--- Stripe live (job PI) ---')
            self.stdout.write(f'amount:   {_cents_to_money(int(getattr(pi, "amount", 0) or 0))}')
            self.stdout.write(f'status:   {getattr(pi, "status", "")}')
            self.stdout.write('')

        if report.get('stripe_tip_pi') is not None:
            pi = report['stripe_tip_pi']
            self.stdout.write('--- Stripe live (tip PI) ---')
            self.stdout.write(f'amount:   {_cents_to_money(int(getattr(pi, "amount", 0) or 0))}')
            self.stdout.write(f'app_fee:  {getattr(pi, "application_fee_amount", None)}')
            self.stdout.write(f'status:   {getattr(pi, "status", "")}')
            meta = getattr(pi, 'metadata', None) or {}
            kind = meta.get('kind') if isinstance(meta, dict) else None
            self.stdout.write(f'metadata: kind={kind!r}')
            self.stdout.write('')

        if issues:
            self.stdout.write(self.style.ERROR('ISSUES:'))
            for item in issues:
                self.stdout.write(self.style.ERROR(f'  - {item}'))
        else:
            self.stdout.write(self.style.SUCCESS('OK — no tip fee / data issues detected for this order.'))
