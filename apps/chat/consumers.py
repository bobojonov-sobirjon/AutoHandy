import json
import base64
import binascii
import os
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
                # Save message to DB (text) OR broadcast existing message (attachments uploaded via REST)
                msg_id = data.get('message_id')
                if msg_id:
                    message = await self.get_message_if_allowed(msg_id)
                    if not message:
                        await self.send(
                            text_data=json.dumps(
                                {'type': 'error', 'message': 'Message not found or access denied'}
                            )
                        )
                        return
                    messages = [message]
                else:
                    # New WS-native message. For multiple images, save_message may return a list.
                    messages = await self.save_message(data)
                    if not messages:
                        await self.send(
                            text_data=json.dumps({'type': 'error', 'message': 'Message validation failed'})
                        )
                        return

                payloads = []
                for message in messages:
                    # Push to the other participant (best-effort)
                    await self.push_other_participant(message)
                    payloads.append(await self.message_to_dict(message))

                # If this is a WS multi-image send, return/broadcast a single "gallery" object
                # with `images: [...]` (as requested by the mobile client).
                is_gallery = (
                    not msg_id
                    and isinstance(data.get('images'), list)
                    and (data.get('message_type') or '').strip() == 'image'
                    and len(payloads) > 1
                )
                if is_gallery:
                    gallery = {
                        'id': payloads[0].get('id'),
                        'room_id': payloads[0].get('room_id'),
                        'sender': payloads[0].get('sender'),
                        'sender_type': payloads[0].get('sender_type'),
                        'message_type': 'image',
                        'text': payloads[0].get('text') or '',
                        'file': None,
                        'image': None,
                        'audio': None,
                        'images': [
                            {
                                'id': p.get('id'),
                                'image': p.get('image'),
                                'image_name': p.get('image_name'),
                            }
                            for p in payloads
                        ],
                        'is_read': False,
                        'created_at': payloads[0].get('created_at'),
                    }
                    payloads_to_send = [gallery]
                else:
                    payloads_to_send = payloads

                # Always ACK back to the sender so API tools (Postman/Insomnia) show a response
                # even if the channel layer is not configured or group delivery is delayed.
                await self.send(
                    text_data=json.dumps(
                        {
                            'type': 'chat_message_ack',
                            'messages': payloads_to_send,
                            'ack': True,
                        }
                    )
                )

                # Send message to everyone in group
                if self.channel_layer:
                    if len(payloads_to_send) == 1:
                        await self.channel_layer.group_send(
                            self.room_group_name,
                            {
                                'type': 'chat_message',
                                'message': payloads_to_send[0],
                            },
                        )
                    else:
                        await self.channel_layer.group_send(
                            self.room_group_name,
                            {
                                'type': 'chat_message_batch',
                                'messages': payloads_to_send,
                            },
                        )

            elif message_type == 'typing':
                # Typing indicator
                if self.channel_layer:
                    await self.channel_layer.group_send(
                        self.room_group_name,
                        {
                            'type': 'typing_indicator',
                            'user_id': self.user.id,
                            'is_typing': data.get('is_typing', False),
                        },
                    )

            elif message_type == 'read_receipt':
                # Read receipt
                message_id = data.get('message_id')
                if message_id:
                    await self.mark_as_read(message_id)
                    if self.channel_layer:
                        await self.channel_layer.group_send(
                            self.room_group_name,
                            {
                                'type': 'read_receipt',
                                'message_id': message_id,
                                'user_id': self.user.id,
                            },
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

    async def chat_message_batch(self, event):
        """Send multiple messages (gallery) to WebSocket"""
        await self.send(
            text_data=json.dumps(
                {
                    'type': 'chat_message_batch',
                    'messages': event.get('messages') or [],
                }
            )
        )

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
        """Save message(s) to DB. Returns a list of ChatMessage."""
        from django.conf import settings
        from django.core.files.base import ContentFile

        def _max_bytes() -> int:
            return int(getattr(settings, 'CHAT_WS_MAX_UPLOAD_BYTES', 5 * 1024 * 1024))

        def _b64_to_content(raw: str, *, filename: str) -> ContentFile:
            if not isinstance(raw, str) or not raw.strip():
                raise ValueError('empty_base64')
            s = raw.strip()
            # Allow "data:<mime>;base64,<payload>"
            if ',' in s and s.lower().startswith('data:'):
                s = s.split(',', 1)[1].strip()
            try:
                blob = base64.b64decode(s, validate=True)
            except (binascii.Error, ValueError) as exc:
                raise ValueError('invalid_base64') from exc
            if len(blob) > _max_bytes():
                raise ValueError('file_too_large')
            return ContentFile(blob, name=filename or 'upload.bin')

        room = ChatRoom.objects.get(id=self.room_id)
        mtype = (data.get('message_type') or 'text').strip()
        text = data.get('text', '') or ''

        # WS-native uploads:
        # - For single attachment: <field>_base64 + <field>_name
        # - For multiple images: images = [{base64,name}, ...]
        created = []
        if mtype == 'image' and isinstance(data.get('images'), list):
            for item in data.get('images', [])[:20]:
                if not isinstance(item, dict):
                    continue
                raw = item.get('base64') or item.get('data')
                name = (item.get('name') or item.get('filename') or 'image.jpg').strip()
                cf = _b64_to_content(raw, filename=name)
                created.append(
                    ChatMessage.objects.create(
                        room=room,
                        sender=self.user,
                        message_type='image',
                        text=text,
                        image=cf,
                    )
                )
        else:
            kwargs = {
                'room': room,
                'sender': self.user,
                'message_type': mtype,
                'text': text,
            }
            if mtype == 'image' and data.get('image_base64'):
                name = (data.get('image_name') or data.get('filename') or 'image.jpg').strip()
                kwargs['image'] = _b64_to_content(data.get('image_base64'), filename=name)
            elif mtype == 'file' and data.get('file_base64'):
                name = (data.get('file_name') or data.get('filename') or 'file.bin').strip()
                kwargs['file'] = _b64_to_content(data.get('file_base64'), filename=name)
            elif mtype == 'audio' and data.get('audio_base64'):
                name = (data.get('audio_name') or data.get('filename') or 'audio.m4a').strip()
                kwargs['audio'] = _b64_to_content(data.get('audio_base64'), filename=name)

            created.append(ChatMessage.objects.create(**kwargs))

        room.save()
        return created

    @database_sync_to_async
    def get_message_if_allowed(self, message_id):
        try:
            msg = ChatMessage.objects.select_related('room', 'sender').get(id=message_id)
        except ChatMessage.DoesNotExist:
            return None
        if str(msg.room_id) != str(self.room_id):
            return None
        if not msg.room.participants.filter(id=self.user.id).exists():
            return None
        return msg

    @database_sync_to_async
    def _other_participant_id_and_kind(self):
        """
        Returns (other_user_id, firebase_kind_str).
        firebase_kind: "master" if other participant is a master user, else "user".
        """
        room = ChatRoom.objects.get(id=self.room_id)
        other = room.get_other_participant(self.user)
        if not other:
            return None, None
        try:
            # Master users have at least one master profile.
            is_master = bool(getattr(other, 'master_profiles', None) and other.master_profiles.exists())
        except Exception:  # noqa: BLE001
            is_master = False
        return other.id, ('master' if is_master else 'user')

    async def push_other_participant(self, message):
        try:
            other_user_id, other_kind = await self._other_participant_id_and_kind()
            if not other_user_id or not other_kind:
                return
            from apps.order.services.notifications import send_fcm_to_user_devices

            # Keep push body short
            body = ''
            if message.message_type == 'text':
                body = (message.text or '').strip()[:120] or 'You have a new message'
            else:
                body = f'You received a new {message.message_type} message'

            send_fcm_to_user_devices(
                user_id=other_user_id,
                firebase_kind=other_kind,
                title='New chat message',
                body=body,
                data={
                    'kind': 'chat_message',
                    'room_id': str(message.room_id),
                    'message_id': str(message.id),
                    'message_type': str(message.message_type),
                },
            )
        except Exception:  # noqa: BLE001
            return

    @database_sync_to_async
    def message_to_dict(self, message):
        """Convert message to dict"""
        from django.conf import settings

        def _abs(url: str | None) -> str | None:
            if not url:
                return None
            if url.startswith('http://') or url.startswith('https://'):
                return url
            base = (getattr(settings, 'API_PUBLIC_BASE_URL', '') or '').strip().rstrip('/')
            if not base:
                return url
            path = url if url.startswith('/') else f'/{url}'
            return f'{base}{path}'

        return {
            'id': message.id,
            'room_id': message.room.id,
            'sender': {
                'id': message.sender.id,
                'full_name': message.sender.get_full_name() or message.sender.email,
                'email': message.sender.email,
                'avatar': _abs(message.sender.avatar.url) if message.sender.avatar else None
            },
            # Mobile clients expect this field; keep it stable for now.
            'sender_type': 'initiator',
            'message_type': message.message_type,
            'text': message.text,
            'file': _abs(message.file.url) if message.file else None,
            'image': _abs(message.image.url) if message.image else None,
            'image_name': os.path.basename(message.image.name) if message.image else None,
            'audio': _abs(message.audio.url) if message.audio else None,
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
