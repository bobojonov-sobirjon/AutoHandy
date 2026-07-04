from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from apps.chat.models import ChatRoom
from apps.chat.services import get_or_create_order_chat_room, reopen_order_chat_messaging

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

    def test_get_or_create_order_chat_room_reopens_closed_room(self):
        room = self._closed_room()

        result, created = get_or_create_order_chat_room(
            master_user=self.master_user,
            customer_user=self.customer_user,
        )

        self.assertFalse(created)
        self.assertEqual(result.pk, room.pk)
        result.refresh_from_db()
        self.assertTrue(result.messaging_is_open())
