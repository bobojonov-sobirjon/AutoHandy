from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from apps.chat.models import ChatMessage, ChatRoom

User = get_user_model()


class UnreadCountApiTestCase(TestCase):
    def setUp(self):
        self.master = User.objects.create_user(
            username='master_unread',
            email='master_unread@example.com',
            password='pass',
        )
        self.driver = User.objects.create_user(
            username='driver_unread',
            email='driver_unread@example.com',
            password='pass',
        )
        self.room = ChatRoom.objects.create(initiator=self.master, is_active=True)
        self.room.participants.add(self.master, self.driver)
        self.client = APIClient()

    def test_unread_count_for_master_and_driver(self):
        ChatMessage.objects.create(
            room=self.room,
            sender=self.driver,
            message_type='text',
            text='hi master',
            is_read=False,
        )
        ChatMessage.objects.create(
            room=self.room,
            sender=self.master,
            message_type='text',
            text='hi driver',
            is_read=False,
        )
        ChatMessage.objects.create(
            room=self.room,
            sender=None,
            message_type='system',
            text='system',
            is_system=True,
            is_read=False,
        )

        self.client.force_authenticate(user=self.master)
        r = self.client.get('/api/chat/unread-count/')
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertEqual(r.data['unread_count'], 1)

        self.client.force_authenticate(user=self.driver)
        r = self.client.get('/api/chat/unread-count/')
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertEqual(r.data['unread_count'], 1)

    def test_mark_read_clears_total(self):
        ChatMessage.objects.create(
            room=self.room,
            sender=self.driver,
            message_type='text',
            text='ping',
            is_read=False,
        )
        self.client.force_authenticate(user=self.master)
        r = self.client.post(f'/api/chat/rooms/{self.room.id}/mark-read/')
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertEqual(r.data['unread_count'], 0)

        r = self.client.get('/api/chat/unread-count/')
        self.assertEqual(r.data['unread_count'], 0)
