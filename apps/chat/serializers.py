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
