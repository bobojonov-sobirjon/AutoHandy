from decimal import Decimal
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.master.models import Master
from apps.order.models import Order, OrderStatus, OrderStripePaymentStatus
from apps.payment.models import SavedCard, SavedCardHolderRole
from apps.payment.services.order_charge import (
    StripeChargeError,
    _complete_charge_idempotency_key,
    charge_order_on_completion,
)

User = get_user_model()


class ChargeOrderOnCompletionRetryTestCase(TestCase):
    def setUp(self):
        self.driver = User.objects.create_user(
            username='driver_complete',
            email='driver_complete@example.com',
            password='pass',
            stripe_customer_id='cus_test',
        )
        self.master_user = User.objects.create_user(
            username='master_complete',
            email='master_complete@example.com',
            password='pass',
        )
        self.master = Master.objects.create(user=self.master_user)
        self.order = Order.objects.create(
            user=self.driver,
            master=self.master,
            status=OrderStatus.IN_PROGRESS,
            text='Test job',
        )
        self.card = SavedCard.objects.create(
            user=self.driver,
            holder_role=SavedCardHolderRole.CLIENT,
            stripe_customer_id='cus_test',
            stripe_payment_method_id='pm_test',
            brand='visa',
            last4='4242',
            is_default=True,
            is_active=True,
        )
        self.order.saved_card = self.card
        self.order.save(update_fields=['saved_card'])

    @patch('apps.payment.services.order_charge.customer_charge_cents', return_value=216)
    @patch('apps.payment.services.order_charge.master_payout_cents', return_value=180)
    @patch('apps.payment.services.order_charge.stripe_configured', return_value=True)
    @patch('apps.payment.services.order_charge.stripe_sdk')
    def test_failed_charge_bumps_attempt_for_fresh_idempotency_key(
        self, mock_stripe_sdk, _cfg, _payout, _charge
    ):
        mock_stripe = MagicMock()
        mock_stripe_sdk.return_value = mock_stripe
        mock_stripe.PaymentIntent.search.return_value = MagicMock(data=[])
        mock_stripe.PaymentIntent.create.side_effect = Exception(
            'Your card has insufficient funds.'
        )

        self.assertEqual(self.order.stripe_charge_attempt, 1)
        self.assertEqual(
            _complete_charge_idempotency_key(self.order),
            f'autohandy_order_{self.order.pk}_complete_charge_a1',
        )

        with self.assertRaises(StripeChargeError) as ctx:
            charge_order_on_completion(self.order)
        self.assertIn('insufficient funds', ctx.exception.message.lower())

        self.order.refresh_from_db()
        self.assertEqual(self.order.stripe_payment_status, OrderStripePaymentStatus.FAILED)
        self.assertEqual(self.order.stripe_charge_attempt, 2)
        self.assertIn('insufficient funds', (self.order.stripe_payment_error or '').lower())
        self.assertEqual(
            _complete_charge_idempotency_key(self.order),
            f'autohandy_order_{self.order.pk}_complete_charge_a2',
        )

        create_kwargs = mock_stripe.PaymentIntent.create.call_args.kwargs
        self.assertEqual(
            create_kwargs['idempotency_key'],
            f'autohandy_order_{self.order.pk}_complete_charge_a1',
        )

    @patch('apps.payment.services.order_charge.customer_charge_cents', return_value=216)
    @patch('apps.payment.services.order_charge.master_payout_cents', return_value=180)
    @patch('apps.payment.services.order_charge.stripe_configured', return_value=True)
    @patch('apps.payment.services.order_charge.stripe_sdk')
    def test_retry_after_failure_uses_new_idempotency_key(
        self, mock_stripe_sdk, _cfg, _payout, _charge
    ):
        self.order.stripe_payment_status = OrderStripePaymentStatus.FAILED
        self.order.stripe_payment_error = 'Your card has insufficient funds.'
        self.order.stripe_charge_attempt = 2
        self.order.save(
            update_fields=['stripe_payment_status', 'stripe_payment_error', 'stripe_charge_attempt']
        )

        pi = MagicMock()
        pi.id = 'pi_retry_ok'
        pi.status = 'succeeded'
        mock_stripe = MagicMock()
        mock_stripe_sdk.return_value = mock_stripe
        mock_stripe.PaymentIntent.search.return_value = MagicMock(data=[])
        mock_stripe.PaymentIntent.create.return_value = pi

        charge_order_on_completion(self.order)

        create_kwargs = mock_stripe.PaymentIntent.create.call_args.kwargs
        self.assertEqual(
            create_kwargs['idempotency_key'],
            f'autohandy_order_{self.order.pk}_complete_charge_a2',
        )
        self.assertEqual(self.order.stripe_payment_status, OrderStripePaymentStatus.SUCCEEDED)
        self.assertEqual(self.order.stripe_payment_intent_id, 'pi_retry_ok')

    @patch('apps.payment.services.order_charge.customer_charge_cents', return_value=216)
    @patch('apps.payment.services.order_charge.master_payout_cents', return_value=180)
    @patch('apps.payment.services.order_charge.stripe_configured', return_value=True)
    @patch('apps.payment.services.order_charge.stripe_sdk')
    def test_already_succeeded_skips_new_charge(self, mock_stripe_sdk, _cfg, _payout, _charge):
        self.order.stripe_payment_status = OrderStripePaymentStatus.SUCCEEDED
        self.order.stripe_payment_intent_id = 'pi_already'
        self.order.stripe_payment_amount_cents = 216
        self.order.save(
            update_fields=[
                'stripe_payment_status',
                'stripe_payment_intent_id',
                'stripe_payment_amount_cents',
            ]
        )

        charge_order_on_completion(self.order)
        mock_stripe_sdk.return_value.PaymentIntent.create.assert_not_called()
