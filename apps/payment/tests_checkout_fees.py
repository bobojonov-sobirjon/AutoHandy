from decimal import Decimal
from unittest.mock import MagicMock

from django.test import SimpleTestCase, override_settings

from apps.order.models import OrderType
from apps.payment.services.checkout_fees import (
    compute_marketplace_checkout,
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
