from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from apps.master.models import Master
from apps.master.services.rates import (
    _master_completion_triplet,
    master_completion_rate_percent,
)
from apps.order.models import Order, OrderStatus
from apps.order.services.status_workflow import detach_master_after_pre_accept_client_cancel

User = get_user_model()


class CompletionRateCancelAttributionTestCase(TestCase):
    def setUp(self):
        self.driver = User.objects.create_user(
            username='driver_cr',
            email='driver_cr@example.com',
            password='pass',
        )
        self.master_user = User.objects.create_user(
            username='master_cr',
            email='master_cr@example.com',
            password='pass',
        )
        self.master = Master.objects.create(user=self.master_user)

        # One completed job so display rate is non-zero and cancels can hurt.
        Order.objects.create(
            user=self.driver,
            master=self.master,
            text='Done job',
            status=OrderStatus.COMPLETED,
            accepted_at=timezone.now(),
        )

    def test_pre_accept_client_cancel_does_not_lower_completion_rate(self):
        before = master_completion_rate_percent(self.master)
        completed, cancelled, _ = _master_completion_triplet(self.master)
        self.assertEqual(completed, 1)
        self.assertEqual(cancelled, 0)

        # Standard booking: master assigned, never accepted, client cancelled.
        Order.objects.create(
            user=self.driver,
            master=self.master,
            text='Client cancelled quickly',
            status=OrderStatus.CANCELLED,
            accepted_at=None,
        )

        after = master_completion_rate_percent(self.master)
        _, cancelled_after, _ = _master_completion_triplet(self.master)
        self.assertEqual(cancelled_after, 0)
        self.assertEqual(after, before)

    def test_post_accept_cancel_does_lower_completion_rate(self):
        before = master_completion_rate_percent(self.master)

        Order.objects.create(
            user=self.driver,
            master=self.master,
            text='Accepted then cancelled',
            status=OrderStatus.CANCELLED,
            accepted_at=timezone.now(),
        )

        after = master_completion_rate_percent(self.master)
        _, cancelled_after, _ = _master_completion_triplet(self.master)
        self.assertEqual(cancelled_after, 1)
        self.assertLess(after, before)

    def test_detach_master_after_pre_accept_client_cancel(self):
        order = Order.objects.create(
            user=self.driver,
            master=self.master,
            text='Detach me',
            status=OrderStatus.CANCELLED,
            accepted_at=None,
        )
        self.assertTrue(detach_master_after_pre_accept_client_cancel(order))
        order.refresh_from_db()
        self.assertIsNone(order.master_id)

        # Already accepted — must not detach.
        accepted = Order.objects.create(
            user=self.driver,
            master=self.master,
            text='Keep master',
            status=OrderStatus.CANCELLED,
            accepted_at=timezone.now(),
        )
        self.assertFalse(detach_master_after_pre_accept_client_cancel(accepted))
        accepted.refresh_from_db()
        self.assertEqual(accepted.master_id, self.master.id)
