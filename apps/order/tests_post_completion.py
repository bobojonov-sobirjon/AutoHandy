from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from apps.order.models import Order, OrderStatus, OrderStripePaymentStatus, Review, ReviewTag

User = get_user_model()


class PostCompletionFlowTestCase(APITestCase):
    def setUp(self):
        self.driver = User.objects.create_user(
            username='driver1',
            email='driver1@example.com',
            password='pass',
        )
        self.master_user = User.objects.create_user(
            username='master1',
            email='master1@example.com',
            password='pass',
        )
        Group.objects.get_or_create(name='Driver')
        Group.objects.get_or_create(name='Master')

        from apps.master.models import Master

        self.master = Master.objects.create(user=self.master_user)
        self.order = Order.objects.create(
            user=self.driver,
            master=self.master,
            text='Oil change',
            status=OrderStatus.COMPLETED,
            stripe_payment_status=OrderStripePaymentStatus.SUCCEEDED,
        )
        self.client.force_authenticate(user=self.driver)
        self.url = reverse('order:create-review')

    def test_order_detail_includes_post_completion(self):
        detail_url = reverse('order:order-detail', kwargs={'id': self.order.pk})
        response = self.client.get(detail_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        pc = response.data.get('post_completion')
        self.assertIsNotNone(pc)
        self.assertTrue(pc['needs_review'])
        self.assertTrue(pc['needs_tip_prompt'])
        self.assertEqual(pc['tip_presets'], [5, 10, 20])
        self.assertEqual(pc['tip_prompt_title'], 'Would you like to leave a tip for your provider?')

    def test_create_review_with_rating(self):
        response = self.client.post(
            self.url,
            {
                'order_id': self.order.pk,
                'rating': 5,
                'tags': [ReviewTag.POLITE],
                'comment': 'Great job',
            },
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertIn('review', response.data)
        self.assertFalse(response.data['post_completion']['needs_review'])
        self.assertTrue(response.data['post_completion']['needs_tip_prompt'])
        self.assertEqual(Review.objects.filter(order=self.order).count(), 1)

    @patch('apps.payment.services.order_charge.charge_order_tip')
    def test_tip_only_preset_amount(self, mock_charge):
        def _mark_paid(order, amount):
            order.tip_amount = amount
            order.tip_stripe_payment_status = OrderStripePaymentStatus.SUCCEEDED

        mock_charge.side_effect = _mark_paid
        response = self.client.post(
            self.url,
            {
                'order_id': self.order.pk,
                'tip_only': True,
                'tip_amount': '10.00',
            },
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        mock_charge.assert_called_once()
        self.assertEqual(response.data['tip_amount'], '10.00')
        self.assertFalse(response.data['post_completion']['needs_tip_prompt'])

    def test_decline_tip(self):
        response = self.client.post(
            self.url,
            {
                'order_id': self.order.pk,
                'tip_only': True,
                'decline_tip': True,
            },
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.order.refresh_from_db()
        self.assertTrue(self.order.tip_declined)
        self.assertFalse(response.data['post_completion']['needs_tip_prompt'])
