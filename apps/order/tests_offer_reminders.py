from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase, override_settings
from django.utils import timezone

from apps.master.models import Master
from apps.order.models import Order, OrderStatus, OrderType
from apps.order.services.offer_reminders import (
    master_still_needs_new_order_reminder,
    reminder_interval_seconds_for_order,
    send_and_reschedule_master_new_order_reminder,
)

User = get_user_model()


class ReminderIntervalByOrderTypeTestCase(SimpleTestCase):
    @override_settings(
        MASTER_NEW_ORDER_REMINDER_SECONDS=60,
        MASTER_NEW_ORDER_REMINDER_SOS_SECONDS=5,
    )
    def test_sos_is_5s_others_60s(self):
        self.assertEqual(reminder_interval_seconds_for_order(order_type='sos'), 5)
        self.assertEqual(reminder_interval_seconds_for_order(order_type=OrderType.SOS), 5)
        self.assertEqual(reminder_interval_seconds_for_order(order_type='standard'), 60)
        self.assertEqual(reminder_interval_seconds_for_order(order_type='towing'), 60)
        self.assertEqual(reminder_interval_seconds_for_order(order_type='custom_request'), 60)


@override_settings(
    MASTER_NEW_ORDER_REMINDER_ENABLED=True,
    MASTER_NEW_ORDER_REMINDER_SECONDS=60,
    MASTER_NEW_ORDER_REMINDER_SOS_SECONDS=5,
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
    def test_standard_reschedule_uses_60s(self, mock_notify, mock_schedule):
        ok = send_and_reschedule_master_new_order_reminder(
            order_id=self.order.id,
            master_id=self.master.id,
            attempt=1,
        )
        self.assertTrue(ok)
        mock_notify.assert_called_once()
        mock_schedule.assert_called_once()
        kwargs = mock_schedule.call_args.kwargs
        self.assertEqual(kwargs.get('attempt'), 2)
        self.assertEqual(kwargs.get('countdown'), 60)
        self.assertEqual(kwargs.get('order_type'), 'standard')

    @patch('apps.order.services.sos_rotation.master_eligible_for_pending_sos_offer', return_value=True)
    @patch('apps.order.services.offer_reminders.schedule_master_new_order_reminder')
    @patch('apps.order.services.notifications.notify_master_new_order_reminder', return_value=1)
    def test_sos_reschedule_uses_5s(self, mock_notify, mock_schedule, _mock_eligible):
        self.order.order_type = OrderType.SOS
        self.order.sos_offer_queue = [self.master.id]
        self.order.save(update_fields=['order_type', 'sos_offer_queue', 'updated_at'])
        ok = send_and_reschedule_master_new_order_reminder(
            order_id=self.order.id,
            master_id=self.master.id,
            attempt=1,
        )
        self.assertTrue(ok)
        kwargs = mock_schedule.call_args.kwargs
        self.assertEqual(kwargs.get('countdown'), 5)
        self.assertEqual(kwargs.get('order_type'), 'sos')

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
