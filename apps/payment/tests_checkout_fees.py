from decimal import Decimal
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, override_settings

from apps.order.models import OrderStatus, OrderStripePaymentStatus, OrderType
from apps.payment.services.checkout_fees import (
    build_order_marketplace_fee_display,
    compute_marketplace_checkout,
    compute_tip_marketplace_checkout,
    preview_marketplace_fees_for_work_total,
)


@override_settings(
    EMERGENCY_DISPATCH_FEE_PERCENT=6,
    CUSTOMER_SERVICE_FEE_PERCENT_EMERGENCY=5,
    CUSTOMER_PLATFORM_FEE_PERCENT_SCHEDULED=4,
    CUSTOMER_SERVICE_FEE_PERCENT_SCHEDULED=4,
    PROVIDER_PLATFORM_FEE_PERCENT=10,
)
class TowingMarketplaceFeesTestCase(SimpleTestCase):
    def test_preview_towing_fees_includes_dispatch(self):
        fees = preview_marketplace_fees_for_work_total('160.00', is_emergency=True)
        self.assertEqual(fees['technician_total'], '160.00')
        self.assertEqual(fees['dispatch_fee'], '9.60')
        self.assertEqual(fees['service_fee'], '8.00')
        self.assertEqual(fees['platform_fee'], '0.00')
        self.assertEqual(fees['customer_total'], '177.60')
        self.assertTrue(fees['is_emergency'])

    def test_compute_checkout_for_towing_order(self):
        order = MagicMock()
        order.order_type = OrderType.TOWING
        order.towing_total = Decimal('160.00')
        order.discount = Decimal('0')
        order.extra_money = Decimal('0')
        order.order_penalty_total = Decimal('0')
        order.car.count = MagicMock(return_value=1)

        with self.settings(ORDER_DISCOUNT_IS_PERCENT=False):
            from apps.order.services.order_pricing import compute_order_price_breakdown

            bd = compute_order_price_breakdown(order)
            self.assertTrue(bd['emergency']['is_emergency'])

            ck = compute_marketplace_checkout(order)
            self.assertEqual(ck['dispatch_fee'], '9.60')
            self.assertEqual(ck['customer_total'], '177.60')
            self.assertTrue(ck['is_emergency'])


@override_settings(
    CUSTOMER_PLATFORM_FEE_PERCENT_SCHEDULED=4,
    CUSTOMER_SERVICE_FEE_PERCENT_SCHEDULED=4,
    PROVIDER_PLATFORM_FEE_PERCENT=10,
)
class TipMarketplaceFeesTestCase(SimpleTestCase):
    def test_tip_scheduled_fees(self):
        order = MagicMock()
        order.order_type = OrderType.STANDARD
        order.towing_total = None
        order.discount = Decimal('0')
        order.extra_money = Decimal('0')
        order.order_penalty_total = Decimal('0')
        order.car.count = MagicMock(return_value=1)

        with self.settings(ORDER_DISCOUNT_IS_PERCENT=False):
            ck = compute_tip_marketplace_checkout(order, Decimal('5.00'))
            self.assertEqual(ck['customer_total'], '5.40')
            self.assertEqual(ck['master_estimated_payout'], '4.50')
            self.assertEqual(ck['service_fee'], '0.20')
            self.assertEqual(ck['platform_fee'], '0.20')

    def test_build_fee_display_includes_tip_totals(self):
        order = MagicMock()
        order.order_type = OrderType.STANDARD
        order.towing_total = None
        order.discount = Decimal('0')
        order.extra_money = Decimal('0')
        order.order_penalty_total = Decimal('0')
        order.car.count = MagicMock(return_value=1)
        order.status = OrderStatus.COMPLETED
        order.stripe_payment_status = OrderStripePaymentStatus.SUCCEEDED
        order.stripe_payment_amount_cents = 194
        order.tip_amount = Decimal('5.00')
        order.tip_stripe_payment_status = OrderStripePaymentStatus.SUCCEEDED
        order.tip_stripe_payment_amount_cents = 540
        order.tip_stripe_payment_intent_id = 'pi_tip'
        order.tip_paid_at = None

        with self.settings(ORDER_DISCOUNT_IS_PERCENT=False):
            with patch(
                'apps.payment.services.checkout_fees.compute_order_price_breakdown',
                return_value={
                    'work_total': Decimal('1.80'),
                    'subtotal': Decimal('1.80'),
                    'base_subtotal': Decimal('1.80'),
                    'discount_applied': Decimal('0'),
                    'extra_money': Decimal('0'),
                    'penalty_total': Decimal('0'),
                    'car_count': 1,
                    'emergency': {'is_emergency': False},
                },
            ):
                display = build_order_marketplace_fee_display(order)
            self.assertEqual(display['tip']['base_amount'], '5.00')
            self.assertEqual(display['totals']['customer_grand_total'], '7.34')
            self.assertEqual(display['totals']['master_grand_payout'], '6.12')
            self.assertTrue(display['totals']['includes_tip'])
