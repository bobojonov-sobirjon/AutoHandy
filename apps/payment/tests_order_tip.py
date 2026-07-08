from decimal import Decimal
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from apps.master.models import Master
from apps.order.models import Order, OrderStatus, OrderStripePaymentStatus
from apps.payment.models import SavedCard, SavedCardHolderRole
from apps.payment.services.order_charge import StripeChargeError, charge_order_tip

User = get_user_model()


class ChargeOrderTipTestCase(TestCase):
    def setUp(self):
        self.driver = User.objects.create_user(
            username='driver_tip',
            email='driver_tip@example.com',
            password='pass',
            stripe_customer_id='cus_test',
        )
        self.master_user = User.objects.create_user(
            username='master_tip',
            email='master_tip@example.com',
            password='pass',
        )
        self.master = Master.objects.create(user=self.master_user)
        self.order = Order.objects.create(
            user=self.driver,
            master=self.master,
            status=OrderStatus.COMPLETED,
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

    @patch('apps.payment.services.order_charge.stripe_configured', return_value=True)
    @patch('apps.payment.services.order_charge.stripe_sdk')
    def test_tip_uses_default_saved_card_when_order_has_none(self, mock_stripe_sdk, _mock_cfg):
        pi = MagicMock()
        pi.id = 'pi_tip_1'
        pi.status = 'succeeded'
        mock_stripe_sdk.return_value.PaymentIntent.create.return_value = pi

        charge_order_tip(self.order, Decimal('10.00'))

        self.assertEqual(self.order.saved_card_id, self.card.id)
        self.assertEqual(self.order.tip_amount, Decimal('10.00'))
        self.assertEqual(self.order.tip_stripe_payment_status, OrderStripePaymentStatus.SUCCEEDED)
        create_kwargs = mock_stripe_sdk.return_value.PaymentIntent.create.call_args.kwargs
        self.assertNotIn('transfer_data', create_kwargs)

    @patch('apps.payment.services.order_charge.stripe_configured', return_value=True)
    @patch('apps.payment.services.order_charge.stripe_sdk')
    @patch('apps.payment.services.order_charge._assert_connect_destination_can_receive_transfers')
    def test_tip_transfers_when_master_has_connect(self, _mock_assert, mock_stripe_sdk, _mock_cfg):
        self.master.stripe_connect_account_id = 'acct_test123'
        self.master.save(update_fields=['stripe_connect_account_id'])
        pi = MagicMock()
        pi.id = 'pi_tip_2'
        pi.status = 'succeeded'
        mock_stripe_sdk.return_value.PaymentIntent.create.return_value = pi

        charge_order_tip(self.order, Decimal('5.00'))

        create_kwargs = mock_stripe_sdk.return_value.PaymentIntent.create.call_args.kwargs
        self.assertEqual(create_kwargs['transfer_data']['destination'], 'acct_test123')

    def test_tip_without_any_saved_card_raises(self):
        self.card.is_active = False
        self.card.save(update_fields=['is_active'])
        with self.assertRaises(StripeChargeError) as ctx:
            charge_order_tip(self.order, Decimal('5.00'))
        self.assertIn('No saved card', ctx.exception.message)


class TipOnlyAPITestCase(APITestCase):
    def setUp(self):
        self.driver = User.objects.create_user(
            username='driver_api_tip',
            email='driver_api_tip@example.com',
            password='pass',
        )
        Group.objects.get_or_create(name='Driver')
        self.master_user = User.objects.create_user(
            username='master_api_tip',
            email='master_api_tip@example.com',
            password='pass',
        )
        self.master = Master.objects.create(user=self.master_user)
        self.order = Order.objects.create(
            user=self.driver,
            master=self.master,
            status=OrderStatus.COMPLETED,
        )
        SavedCard.objects.create(
            user=self.driver,
            holder_role=SavedCardHolderRole.CLIENT,
            stripe_customer_id='cus_test',
            stripe_payment_method_id='pm_test',
            brand='visa',
            last4='4242',
            is_default=True,
            is_active=True,
        )
        self.client.force_authenticate(user=self.driver)
        self.url = reverse('order:create-review')

    @patch('apps.payment.services.order_charge.charge_order_tip')
    def test_tip_only_returns_error_message_on_failure(self, mock_charge):
        mock_charge.side_effect = StripeChargeError('Card was declined.')
        response = self.client.post(
            self.url,
            {'order_id': self.order.pk, 'tip_only': True, 'tip_amount': '10.00'},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data['error'], 'Card was declined.')
