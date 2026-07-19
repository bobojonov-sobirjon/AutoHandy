from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from apps.chat.constants import SYSTEM_CODE_MASTER_GREETING
from apps.chat.models import ChatRoom
from apps.chat.services import (
    get_or_create_order_chat_room,
    refresh_room_messaging_state,
    reopen_order_chat_messaging,
)

User = get_user_model()


class OrderChatReopenTestCase(TestCase):
    def setUp(self):
        self.master_user = User.objects.create_user(
            username='master1',
            email='master1@example.com',
            password='pass',
        )
        self.customer_user = User.objects.create_user(
            username='customer1',
            email='customer1@example.com',
            password='pass',
        )

    def _closed_room(self) -> ChatRoom:
        room = ChatRoom.objects.create(
            initiator=self.master_user,
            is_active=False,
            closes_at=timezone.now() - timedelta(hours=1),
        )
        room.participants.add(self.master_user, self.customer_user)
        return room

    def test_reopen_order_chat_messaging_restores_sending(self):
        room = self._closed_room()
        self.assertFalse(room.messaging_is_open())

        reopened = reopen_order_chat_messaging(room=room)
        reopened.refresh_from_db()

        self.assertTrue(reopened.is_active)
        self.assertIsNone(reopened.closes_at)
        self.assertTrue(reopened.messaging_is_open())

    def test_get_or_create_order_chat_room_always_creates_new(self):
        old_room = self._closed_room()

        result, created = get_or_create_order_chat_room(
            master_user=self.master_user,
            customer_user=self.customer_user,
        )

        self.assertTrue(created)
        self.assertNotEqual(result.pk, old_room.pk)
        result.refresh_from_db()
        self.assertTrue(result.messaging_is_open())
        self.assertIsNone(result.closes_at)

        second, created_again = get_or_create_order_chat_room(
            master_user=self.master_user,
            customer_user=self.customer_user,
        )
        self.assertTrue(created_again)
        self.assertNotEqual(second.pk, result.pk)

    def test_new_room_posts_master_greeting_from_master(self):
        self.master_user.first_name = 'Anton'
        self.master_user.last_name = 'Kuznetsov'
        self.master_user.save(update_fields=['first_name', 'last_name'])

        room, _ = get_or_create_order_chat_room(
            master_user=self.master_user,
            customer_user=self.customer_user,
        )

        greeting = room.messages.filter(system_code=SYSTEM_CODE_MASTER_GREETING).first()
        self.assertIsNotNone(greeting)
        self.assertEqual(greeting.sender_id, self.master_user.id)
        self.assertFalse(greeting.is_system)
        self.assertIn('Anton', greeting.text)
        self.assertNotIn('Kuznetsov', greeting.text)

    def test_refresh_does_not_reclose_room_with_active_order(self):
        from apps.master.models import Master
        from apps.order.models import Order, OrderStatus, OrderType

        room = self._closed_room()
        master = Master.objects.create(user=self.master_user)
        Order.objects.create(
            user=self.customer_user,
            master=master,
            order_type=OrderType.TOWING,
            status=OrderStatus.ACCEPTED,
            chat_room=room,
        )
        reopen_order_chat_messaging(room=room)
        room.refresh_from_db()
        self.assertTrue(room.messaging_is_open())

        refresh_room_messaging_state(room=room)
        room.refresh_from_db()
        self.assertTrue(room.messaging_is_open())
        self.assertIsNone(room.closes_at)
