from rest_framework import serializers
from django.contrib.auth import get_user_model
from .models import ChatRoom, ChatMessage

User = get_user_model()


class ChatParticipantSerializer(serializers.ModelSerializer):
    """Serializer for chat participant"""
    full_name = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ['id', 'email', 'first_name', 'last_name', 'full_name', 'avatar']

    def get_full_name(self, obj):
        return obj.get_full_name() or obj.email


class ChatMessageSerializer(serializers.ModelSerializer):
    """Serializer for chat message"""
    sender = ChatParticipantSerializer(read_only=True)
    sender_type = serializers.SerializerMethodField()
    file_url = serializers.SerializerMethodField()
    image_url = serializers.SerializerMethodField()
    audio_url = serializers.SerializerMethodField()

    class Meta:
        model = ChatMessage
        fields = [
            'id', 'room', 'sender', 'sender_type', 'message_type', 'text',
            'file', 'file_url', 'image', 'image_url', 'audio', 'audio_url',
            'is_read', 'created_at'
        ]
        read_only_fields = ['id', 'sender', 'created_at']

    def get_sender_type(self, obj):
        """Determine sender type relative to current user"""
        request = self.context.get('request')
        if request and request.user:
            if obj.sender == request.user:
                return 'initiator'
            return 'receiver'
        return 'initiator'

    def get_file_url(self, obj):
        if obj.file:
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(obj.file.url)
            return obj.file.url
        return None

    def get_image_url(self, obj):
        if obj.image:
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(obj.image.url)
            return obj.image.url
        return None

    def get_audio_url(self, obj):
        if obj.audio:
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(obj.audio.url)
            return obj.audio.url
        return None


def _chat_message_api_dict(*, msg: ChatMessage, request) -> dict:
    """
    Messages API output (used by room details last_message and messages list).
    NOTE: This is separate from WebSocket payloads to allow grouping images into a gallery object.
    """
    sender_data = ChatParticipantSerializer(msg.sender, context={'request': request}).data
    sender_type = 'initiator' if request and msg.sender_id == getattr(request.user, 'id', None) else 'receiver'

    # absolute URLs via request.build_absolute_uri (same behavior as ChatMessageSerializer)
    def _abs(url: str | None) -> str | None:
        if not url:
            return None
        if request:
            return request.build_absolute_uri(url)
        return url

    file_url = _abs(msg.file.url) if msg.file else None
    image_url = _abs(msg.image.url) if msg.image else None
    audio_url = _abs(msg.audio.url) if msg.audio else None

    return {
        'id': msg.id,
        'room_id': msg.room_id,
        'sender': sender_data,
        'sender_type': sender_type,
        'message_type': msg.message_type,
        'text': msg.text or '',
        'file': file_url,
        'image': image_url,
        'audio': audio_url,
        'is_read': bool(msg.is_read),
        'created_at': msg.created_at.isoformat() if msg.created_at else None,
    }


def build_chat_messages_api_payload(*, messages: list[ChatMessage], request) -> list[dict]:
    """
    Build API payload for message list with "gallery" grouping for images.

    If multiple consecutive image messages have:
    - same sender
    - same text
    - created very close together (WS batch)
    then they are grouped into one object:
      { message_type: "image", image: null, images: [ ... ] }
    """
    from datetime import timedelta
    import os

    if not messages:
        return []

    out: list[dict] = []
    i = 0
    # messages are expected in DESC created_at order
    while i < len(messages):
        m = messages[i]
        if m.message_type != 'image' or not m.image:
            out.append(_chat_message_api_dict(msg=m, request=request))
            i += 1
            continue

        # try to build a gallery block
        group = [m]
        j = i + 1
        while j < len(messages):
            n = messages[j]
            if n.message_type != 'image' or not n.image:
                break
            if n.sender_id != m.sender_id:
                break
            if (n.text or '') != (m.text or ''):
                break
            # time proximity (same WS batch): within 3 seconds
            if m.created_at and n.created_at and (m.created_at - n.created_at) > timedelta(seconds=3):
                break
            group.append(n)
            j += 1

        if len(group) == 1:
            out.append(_chat_message_api_dict(msg=m, request=request))
            i += 1
            continue

        base = _chat_message_api_dict(msg=group[0], request=request)
        base['image'] = None
        base['images'] = [
            {
                'id': g.id,
                'image': (request.build_absolute_uri(g.image.url) if request and g.image else (g.image.url if g.image else None)),
                'image_name': os.path.basename(g.image.name) if g.image else None,
            }
            for g in group
        ]
        out.append(base)
        i = j

    return out


class ChatRoomSerializer(serializers.ModelSerializer):
    """Serializer for chat room"""
    participants = ChatParticipantSerializer(many=True, read_only=True)
    last_message = serializers.SerializerMethodField()
    unread_count = serializers.SerializerMethodField()
    other_participant = serializers.SerializerMethodField()

    class Meta:
        model = ChatRoom
        fields = [
            'id', 'participants', 'other_participant', 'last_message',
            'unread_count', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']

    def get_last_message(self, obj):
        last_msg = obj.messages.order_by('-created_at').first()
        if last_msg:
            return ChatMessageSerializer(last_msg, context=self.context).data
        return None

    def get_unread_count(self, obj):
        request = self.context.get('request')
        if request and request.user:
            return obj.messages.filter(is_read=False).exclude(sender=request.user).count()
        return 0

    def get_other_participant(self, obj):
        request = self.context.get('request')
        if request and request.user:
            other = obj.get_other_participant(request.user)
            if other:
                return ChatParticipantSerializer(other, context=self.context).data
        return None


class OrderBriefSerializer(serializers.Serializer):
    """
    Minimal order payload for chat room details.
    (Avoids pulling the full OrderSerializer into chat responses.)
    """

    id = serializers.IntegerField()
    order_type = serializers.CharField()
    status = serializers.CharField()
    created_at = serializers.DateTimeField()


class ChatRoomDetailSerializer(serializers.ModelSerializer):
    """
    Room details payload for the room screen:
    - initiator / receiver as separate objects
    - linked order (if any)
    - last_message
    """

    initiator = ChatParticipantSerializer(read_only=True)
    receiver = serializers.SerializerMethodField()
    order = serializers.SerializerMethodField()
    last_message = serializers.SerializerMethodField()

    class Meta:
        model = ChatRoom
        fields = ['id', 'initiator', 'receiver', 'order', 'last_message', 'created_at', 'updated_at']
        read_only_fields = fields

    def get_receiver(self, obj):
        init = obj.initiator
        qs = obj.participants.all()
        if init:
            other = qs.exclude(id=init.id).first()
        else:
            # Fallback for legacy rooms without initiator.
            ordered = list(qs.order_by('id')[:2])
            other = ordered[1] if len(ordered) > 1 else (ordered[0] if ordered else None)
        if not other:
            return None
        return ChatParticipantSerializer(other, context=self.context).data

    def get_order(self, obj):
        # Linked via Order.chat_room (related_name='orders'); typically one.
        o = getattr(obj, 'orders', None)
        order = o.all().only('id', 'order_type', 'status', 'created_at').first() if o is not None else None
        if not order:
            return None
        return OrderBriefSerializer(
            {
                'id': order.id,
                'order_type': getattr(order, 'order_type', None),
                'status': getattr(order, 'status', None),
                'created_at': getattr(order, 'created_at', None),
            }
        ).data

    def get_last_message(self, obj):
        request = self.context.get('request')
        # Fetch a small window: if last message is part of a WS image batch, we need siblings to group.
        last_msgs = list(
            obj.messages.order_by('-created_at')
            .select_related('sender')
            .all()[:10]
        )
        if not last_msgs:
            return None
        grouped = build_chat_messages_api_payload(messages=last_msgs, request=request)
        return grouped[0] if grouped else None


class CreateChatRoomSerializer(serializers.Serializer):
    """Serializer for creating chat room"""
    participant_id = serializers.IntegerField(
        help_text='ID of the other user to create chat with'
    )

    def validate_participant_id(self, value):
        try:
            User.objects.get(id=value)
        except User.DoesNotExist:
            raise serializers.ValidationError(f'User with ID {value} not found')
        return value


class SendMessageSerializer(serializers.ModelSerializer):
    """Serializer for sending message"""

    class Meta:
        model = ChatMessage
        fields = ['room', 'message_type', 'text', 'file', 'image', 'audio']

    def validate(self, data):
        message_type = data.get('message_type')

        if message_type == 'text' and not data.get('text'):
            raise serializers.ValidationError({'text': 'Message text is required for type "text"'})

        if message_type == 'file' and not data.get('file'):
            raise serializers.ValidationError({'file': 'File is required for type "file"'})

        if message_type == 'image' and not data.get('image'):
            raise serializers.ValidationError({'image': 'Image is required for type "image"'})

        if message_type == 'audio' and not data.get('audio'):
            raise serializers.ValidationError({'audio': 'Audio is required for type "audio"'})

        return data
