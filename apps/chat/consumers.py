import json
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from django.contrib.auth import get_user_model
from .models import ChatRoom, ChatMessage

User = get_user_model()


class ChatConsumer(AsyncWebsocketConsumer):
    """
    WebSocket consumer for real-time chat
    """

    async def connect(self):
        """On WebSocket connect"""
        self.room_id = self.scope['url_route']['kwargs']['room_id']
        self.room_group_name = f'chat_{self.room_id}'
        self.user = self.scope['user']

        print(f"[DEBUG] WebSocket connect attempt: room_id={self.room_id}, user={self.user}")

        # Check authentication
        if not self.user or not self.user.is_authenticated:
            print(f"[DEBUG] Authentication failed: user={self.user}")
            await self.close(code=4001)
            return

        # Check room access
        has_access = await self.check_room_access()
        print(f"[DEBUG] Room access check: has_access={has_access}")

        if not has_access:
            print(f"[DEBUG] Access denied to room {self.room_id} for user {self.user.id}")
            await self.close(code=4003)
            return

        # Join room group
        await self.channel_layer.group_add(
            self.room_group_name,
            self.channel_name
        )

        await self.accept()

        print(f"[DEBUG] User {self.user.id} successfully connected to room {self.room_id}")

        # Send connection confirmation
        await self.send(text_data=json.dumps({
            'type': 'connection_established',
            'message': 'Successfully connected to chat'
        }))

    async def disconnect(self, close_code):
        """On WebSocket disconnect"""
        # Leave room group
        await self.channel_layer.group_discard(
            self.room_group_name,
            self.channel_name
        )

    async def receive(self, text_data):
        """Receive message from client"""
        try:
            print(f"[DEBUG] Received data: {text_data[:100]}")  # First 100 chars

            if not text_data or not text_data.strip():
                print("[DEBUG] Empty message received, ignoring")
                return

            data = json.loads(text_data)
            message_type = data.get('type')

            print(f"[DEBUG] Message type: {message_type}")

            if message_type == 'chat_message':
                # Save message to DB
                message = await self.save_message(data)

                # Send message to everyone in group
                await self.channel_layer.group_send(
                    self.room_group_name,
                    {
                        'type': 'chat_message',
                        'message': await self.message_to_dict(message)
                    }
                )

            elif message_type == 'typing':
                # Typing indicator
                await self.channel_layer.group_send(
                    self.room_group_name,
                    {
                        'type': 'typing_indicator',
                        'user_id': self.user.id,
                        'is_typing': data.get('is_typing', False)
                    }
                )

            elif message_type == 'read_receipt':
                # Read receipt
                message_id = data.get('message_id')
                if message_id:
                    await self.mark_as_read(message_id)
                    await self.channel_layer.group_send(
                        self.room_group_name,
                        {
                            'type': 'read_receipt',
                            'message_id': message_id,
                            'user_id': self.user.id
                        }
                    )

        except json.JSONDecodeError as e:
            error_msg = f"Invalid JSON format: {str(e)}"
            print(f"[DEBUG] JSON decode error: {error_msg}")
            print(f"[DEBUG] Received text: {text_data}")
            await self.send(text_data=json.dumps({
                'type': 'error',
                'message': error_msg
            }))

        except Exception as e:
            error_msg = f"Error processing message: {str(e)}"
            print(f"[DEBUG] General error: {error_msg}")
            await self.send(text_data=json.dumps({
                'type': 'error',
                'message': error_msg
            }))

    async def chat_message(self, event):
        """Send message to WebSocket"""
        await self.send(text_data=json.dumps({
            'type': 'chat_message',
            'message': event['message']
        }))

    async def typing_indicator(self, event):
        """Send typing indicator"""
        if event['user_id'] != self.user.id:
            await self.send(text_data=json.dumps({
                'type': 'typing',
                'user_id': event['user_id'],
                'is_typing': event['is_typing']
            }))

    async def read_receipt(self, event):
        """Send read receipt"""
        await self.send(text_data=json.dumps({
            'type': 'read_receipt',
            'message_id': event['message_id'],
            'user_id': event['user_id']
        }))

    @database_sync_to_async
    def check_room_access(self):
        """Check room access"""
        try:
            room = ChatRoom.objects.get(id=self.room_id)
            participants = room.participants.all()
            participant_ids = [p.id for p in participants]

            print(f"[DEBUG] Room {self.room_id} participants: {participant_ids}")
            print(f"[DEBUG] Current user ID: {self.user.id}")

            has_access = room.participants.filter(id=self.user.id).exists()
            print(f"[DEBUG] Access result: {has_access}")

            return has_access
        except ChatRoom.DoesNotExist:
            print(f"[DEBUG] Room {self.room_id} does not exist")
            return False

    @database_sync_to_async
    def save_message(self, data):
        """Save message to DB"""
        room = ChatRoom.objects.get(id=self.room_id)
        message = ChatMessage.objects.create(
            room=room,
            sender=self.user,
            message_type=data.get('message_type', 'text'),
            text=data.get('text', '')
        )
        room.save()
        return message

    @database_sync_to_async
    def message_to_dict(self, message):
        """Convert message to dict"""
        return {
            'id': message.id,
            'room_id': message.room.id,
            'sender': {
                'id': message.sender.id,
                'full_name': message.sender.get_full_name() or message.sender.email,
                'email': message.sender.email,
                'avatar': message.sender.avatar.url if message.sender.avatar else None
            },
            'sender_type': 'initiator',
            'message_type': message.message_type,
            'text': message.text,
            'file': message.file.url if message.file else None,
            'image': message.image.url if message.image else None,
            'audio': message.audio.url if message.audio else None,
            'is_read': message.is_read,
            'created_at': message.created_at.isoformat()
        }

    @database_sync_to_async
    def mark_as_read(self, message_id):
        """Mark message as read"""
        try:
            message = ChatMessage.objects.get(id=message_id)
            if message.sender != self.user:
                message.is_read = True
                message.save()
        except ChatMessage.DoesNotExist:
            pass
