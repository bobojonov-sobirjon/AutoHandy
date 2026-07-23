from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone

from apps.master.models import Master
from apps.order.models import Order, OrderStatus, OrderType
from apps.order.services.offer_reminders import (
    master_still_needs_new_order_reminder,
    send_and_reschedule_master_new_order_reminder,
)

User = get_user_model()


@override_settings(
    MASTER_NEW_ORDER_REMINDER_ENABLED=True,
    MASTER_NEW_ORDER_REMINDER_SECONDS=5,
    MASTER_NEW_ORDER_REMINDER_MAX_COUNT=10,
    CELERY_TASK_ALWAYS_EAGER=True,
)
class MasterNewOrderReminderTestCase(TestCase):
    def setUp(self):
        self.driver = User.objects.create_user(
            username='drv_rem',
            email='drv_rem@example.com',
            password='pass',
        )
        self.master_user = User.objects.create_user(
            username='mst_rem',
            email='mst_rem@example.com',
            password='pass',
        )
        self.master = Master.objects.create(user=self.master_user)
        self.order = Order.objects.create(
            user=self.driver,
            master=self.master,
            text='Pending offer',
            status=OrderStatus.PENDING,
            order_type=OrderType.STANDARD,
            master_response_deadline=timezone.now() + timedelta(minutes=10),
        )

    def test_eligible_while_pending(self):
        self.assertTrue(
            master_still_needs_new_order_reminder(order=self.order, master_id=self.master.id)
        )

    def test_not_eligible_after_accept(self):
        self.order.status = OrderStatus.ACCEPTED
        self.order.accepted_at = timezone.now()
        self.order.save(update_fields=['status', 'accepted_at', 'updated_at'])
        self.assertFalse(
            master_still_needs_new_order_reminder(order=self.order, master_id=self.master.id)
        )

    def test_not_eligible_after_deadline(self):
        self.order.master_response_deadline = timezone.now() - timedelta(seconds=1)
        self.order.save(update_fields=['master_response_deadline', 'updated_at'])
        self.assertFalse(
            master_still_needs_new_order_reminder(order=self.order, master_id=self.master.id)
        )

    @patch('apps.order.services.offer_reminders.schedule_master_new_order_reminder')
    @patch('apps.order.services.notifications.notify_master_new_order_reminder', return_value=1)
    def test_send_and_reschedule_while_pending(self, mock_notify, mock_schedule):
        ok = send_and_reschedule_master_new_order_reminder(
            order_id=self.order.id,
            master_id=self.master.id,
            attempt=1,
        )
        self.assertTrue(ok)
        mock_notify.assert_called_once()
        mock_schedule.assert_called_once()
        self.assertEqual(mock_schedule.call_args.kwargs.get('attempt') or mock_schedule.call_args[1].get('attempt'), 2)

    @patch('apps.order.services.offer_reminders.schedule_master_new_order_reminder')
    @patch('apps.order.services.notifications.notify_master_new_order_reminder', return_value=1)
    def test_no_send_when_already_accepted(self, mock_notify, mock_schedule):
        self.order.status = OrderStatus.ACCEPTED
        self.order.save(update_fields=['status', 'updated_at'])
        ok = send_and_reschedule_master_new_order_reminder(
            order_id=self.order.id,
            master_id=self.master.id,
            attempt=1,
        )
        self.assertFalse(ok)
        mock_notify.assert_not_called()
        mock_schedule.assert_not_called()
