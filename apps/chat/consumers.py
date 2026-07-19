import json
import base64
import binascii
import os
import logging
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from django.contrib.auth import get_user_model
from .models import ChatRoom, ChatMessage

User = get_user_model()


def _mask_sender_name(sender) -> str:
    """Chat never exposes a full surname to the other party ("Anton K")."""
    from apps.accounts.display_name import customer_display_name

    return customer_display_name(
        getattr(sender, 'first_name', None),
        getattr(sender, 'last_name', None),
        fallback=(getattr(sender, 'email', None) or ''),
    )


class ChatConsumer(AsyncWebsocketConsumer):
    """
    WebSocket consumer for real-time chat
    """

    async def connect(self):
        """On WebSocket connect"""
        self.room_id = self.scope['url_route']['kwargs']['room_id']
        self.room_group_name = f'chat_{self.room_id}'
        self.user = self.scope['user']

        if not self.user or not self.user.is_authenticated:
            await self.close(code=4001)
            return

        has_access = await self.check_room_access()

        if not has_access:
            await self.close(code=4003)
            return

        # Join room group
        await self.channel_layer.group_add(
            self.room_group_name,
            self.channel_name
        )

        await self.accept()

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

    async def receive(self, text_data=None, bytes_data=None):
        """Receive message from client"""
        try:
            if text_data is None and bytes_data is not None:
                try:
                    text_data = bytes_data.decode('utf-8', errors='replace')
                except Exception:  # noqa: BLE001
                    text_data = None
            if text_data is None:
                return

            if not text_data or not text_data.strip():
                return

            data = json.loads(text_data)
            message_type = data.get('type')

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
                    try:
                        messages, extra_system = await self.save_message(data)
                    except ValueError as exc:
                        await self.send(
                            text_data=json.dumps({'type': 'error', 'message': str(exc)})
                        )
                        return
                    if not messages:
                        await self.send(
                            text_data=json.dumps({'type': 'error', 'message': 'Message validation failed'})
                        )
                        return
                    if extra_system:
                        messages = list(messages) + list(extra_system)

                payloads = []
                for message in messages:
                    if not getattr(message, 'is_system', False):
                        await self.push_other_participant(message)
                    payloads.append(await self.message_to_dict(message))

                # If this is a WS multi-image send, return/broadcast a single "gallery" object
                image_payloads = [p for p in payloads if p.get('message_type') == 'image' and not p.get('is_system')]
                is_gallery = (
                    not msg_id
                    and isinstance(data.get('images'), list)
                    and (data.get('message_type') or '').strip() == 'image'
                    and len(image_payloads) > 1
                )
                if is_gallery:
                    gallery = {
                        'id': image_payloads[0].get('id'),
                        'room_id': image_payloads[0].get('room_id'),
                        'sender': image_payloads[0].get('sender'),
                        'sender_type': image_payloads[0].get('sender_type'),
                        'message_type': 'image',
                        'text': image_payloads[0].get('text') or '',
                        'file': None,
                        'image': None,
                        'audio': None,
                        'images': [
                            {
                                'id': p.get('id'),
                                'image': p.get('image'),
                                'image_name': p.get('image_name'),
                            }
                            for p in image_payloads
                        ],
                        'is_read': False,
                        'is_system': False,
                        'system_code': None,
                        'created_at': image_payloads[0].get('created_at'),
                    }
                    system_payloads = [p for p in payloads if p.get('is_system')]
                    payloads_to_send = [gallery] + system_payloads
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
            await self.send(text_data=json.dumps({
                'type': 'error',
                'message': error_msg
            }))

        except Exception as e:
            error_msg = f"Error processing message: {str(e)}"
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
            return room.participants.filter(id=self.user.id).exists()
        except ChatRoom.DoesNotExist:
            return False

    @database_sync_to_async
    def save_message(self, data):
        """Save message(s) to DB. Returns (list[ChatMessage], list[ChatMessage extras])."""
        from django.conf import settings
        from django.core.files.base import ContentFile

        from apps.chat.services import (
            ChatMessagingClosedError,
            after_user_message_saved,
            assert_room_allows_messaging,
        )

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
        try:
            assert_room_allows_messaging(room=room)
        except ChatMessagingClosedError as exc:
            raise ValueError(exc.message) from exc

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
        extras: list = []
        for msg in created:
            extras.extend(after_user_message_saved(room=room, message=msg))
        return created, extras

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

    @database_sync_to_async
    def _send_chat_push_sync(self, message) -> int:
        """Run FCM send in a sync thread (ORM + firebase-admin)."""
        from apps.order.services.notifications import notify_chat_message

        other_user_id, _other_kind = self._other_participant_id_and_kind_sync()
        if not other_user_id:
            return 0
        sender = getattr(message, 'sender', None) or self.user
        from apps.accounts.display_name import customer_display_name

        sender_name = customer_display_name(
            getattr(sender, 'first_name', None),
            getattr(sender, 'last_name', None),
            fallback=(
                getattr(sender, 'email', None)
                or getattr(sender, 'phone_number', None)
                or f'User {getattr(sender, "id", "")}'
            ),
        )
        return notify_chat_message(
            recipient_user_id=other_user_id,
            room_id=int(message.room_id),
            message_id=int(message.id),
            message_type=str(message.message_type),
            text=getattr(message, 'text', None),
            sender_display=str(sender_name),
        )

    def _other_participant_id_and_kind_sync(self):
        room = ChatRoom.objects.get(id=self.room_id)
        other = room.get_other_participant(self.user)
        if not other:
            return None, None
        try:
            is_master = bool(getattr(other, 'master_profiles', None) and other.master_profiles.exists())
        except Exception:  # noqa: BLE001
            is_master = False
        return other.id, ('master' if is_master else 'user')

    async def push_other_participant(self, message):
        try:
            other_user_id, other_kind = await self._other_participant_id_and_kind()
            if not other_user_id or not other_kind:
                return
            await self._send_chat_push_sync(message)
        except Exception:  # noqa: BLE001
            logging.getLogger(__name__).exception(
                'chat_push_failed room_id=%s message_id=%s',
                getattr(message, 'room_id', None),
                getattr(message, 'id', None),
            )

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
            'sender': None if message.sender_id is None else {
                'id': message.sender.id,
                'full_name': _mask_sender_name(message.sender),
                'email': message.sender.email,
                'avatar': _abs(message.sender.avatar.url) if message.sender.avatar else None
            },
            'sender_type': 'system' if message.is_system or message.sender_id is None else 'initiator',
            'message_type': message.message_type,
            'text': message.text,
            'file': _abs(message.file.url) if message.file else None,
            'image': _abs(message.image.url) if message.image else None,
            'image_name': os.path.basename(message.image.name) if message.image else None,
            'audio': _abs(message.audio.url) if message.audio else None,
            'is_read': message.is_read,
            'is_system': bool(message.is_system),
            'system_code': (message.system_code or '') or None,
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
