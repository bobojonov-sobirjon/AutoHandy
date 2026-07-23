from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase

from apps.master.models import Master
from apps.order.models import Order, OrderStatus
from apps.order.services.notifications import (
    _new_order_push_sound_kwargs,
    notify_master_new_order,
)

User = get_user_model()


class NewOrderPushSoundConfigTestCase(SimpleTestCase):
    def test_default_new_order_sound_names(self):
        kw = _new_order_push_sound_kwargs()
        self.assertEqual(kw['android_channel_id'], 'incoming_orders_v3')
        self.assertEqual(kw['android_sound'], 'new_order')
        self.assertEqual(kw['apns_sound'], 'new_order.caf')
        self.assertEqual(kw['apns_badge'], 1)


class NotifyMasterNewOrderFcmPayloadTestCase(TestCase):
    def setUp(self):
        self.driver = User.objects.create_user(
            username='driver_push',
            email='driver_push@example.com',
            password='pass',
        )
        self.master_user = User.objects.create_user(
            username='master_push',
            email='master_push@example.com',
            password='pass',
        )
        self.master = Master.objects.create(user=self.master_user)
        self.order = Order.objects.create(
            user=self.driver,
            master=self.master,
            text='New job',
            status=OrderStatus.PENDING,
        )

    @patch('apps.order.services.notifications.send_fcm_to_user_devices', return_value=1)
    def test_notify_master_new_order_passes_custom_sound(self, mock_send):
        notify_master_new_order(self.order)
        self.assertTrue(mock_send.called)
        kwargs = mock_send.call_args.kwargs
        self.assertEqual(kwargs['android_channel_id'], 'incoming_orders_v3')
        self.assertEqual(kwargs['android_sound'], 'new_order')
        self.assertEqual(kwargs['apns_sound'], 'new_order.caf')
        self.assertEqual(kwargs['apns_badge'], 1)
        self.assertEqual(kwargs['data']['kind'], 'order_new')
        self.assertEqual(kwargs['data']['type'], 'new_order')
        self.assertEqual(kwargs['data']['order_id'], str(self.order.id))
