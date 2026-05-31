from django.db import models
from django.contrib.auth import get_user_model
from django.utils import timezone

User = get_user_model()


class ChatRoom(models.Model):
    """
    Chat room - chat between two users
    """
    initiator = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='initiated_chats',
        verbose_name='Initiator',
        help_text='User who created the chat',
        null=True,
        blank=True
    )
    participants = models.ManyToManyField(
        User,
        related_name='chat_rooms',
        verbose_name='Participants'
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name='Created at'
    )
    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name='Updated at'
    )
    is_active = models.BooleanField(
        default=True,
        verbose_name='Messaging active',
        help_text='When false, participants can read history but cannot send new messages.',
    )
    closes_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name='Messaging closes at',
        help_text='After order completion: grace period end (default +2h). Then is_active becomes false.',
    )

    class Meta:
        verbose_name = 'Chat room'
        verbose_name_plural = 'Chat rooms'
        ordering = ['-updated_at']

    def __str__(self):
        participants_names = ', '.join([p.get_full_name() or p.email for p in self.participants.all()[:2]])
        return f"Chat #{self.id}: {participants_names}"

    def get_other_participant(self, user):
        """Get the other chat participant"""
        return self.participants.exclude(id=user.id).first()

    def get_sender_type(self, user):
        """Determine sender type relative to current user"""
        if self.initiator is None:
            first_participant = self.participants.first()
            if first_participant and first_participant == user:
                return 'initiator'
            return 'receiver'

        if self.initiator == user:
            return 'initiator'
        return 'receiver'

    def messaging_is_open(self) -> bool:
        """True while participants may send new messages."""
        from django.utils import timezone

        if not self.is_active:
            return False
        if self.closes_at and timezone.now() >= self.closes_at:
            return False
        return True


class ChatMessage(models.Model):
    """
    Chat message - text, file, image, audio
    """
    MESSAGE_TYPE_CHOICES = [
        ('text', 'Text'),
        ('image', 'Image'),
        ('file', 'File'),
        ('audio', 'Audio'),
        ('system', 'System'),
    ]

    room = models.ForeignKey(
        ChatRoom,
        on_delete=models.CASCADE,
        related_name='messages',
        verbose_name='Room'
    )
    sender = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='sent_messages',
        verbose_name='Sender',
        null=True,
        blank=True,
    )
    message_type = models.CharField(
        max_length=10,
        choices=MESSAGE_TYPE_CHOICES,
        default='text',
        verbose_name='Message type'
    )
    text = models.TextField(
        blank=True,
        null=True,
        verbose_name='Message text'
    )
    file = models.FileField(
        upload_to='chat/files/%Y/%m/%d/',
        blank=True,
        null=True,
        verbose_name='File'
    )
    image = models.ImageField(
        upload_to='chat/images/%Y/%m/%d/',
        blank=True,
        null=True,
        verbose_name='Image'
    )
    audio = models.FileField(
        upload_to='chat/audio/%Y/%m/%d/',
        blank=True,
        null=True,
        verbose_name='Audio'
    )
    is_read = models.BooleanField(
        default=False,
        verbose_name='Read'
    )
    is_system = models.BooleanField(
        default=False,
        verbose_name='System message',
        help_text='Platform-generated message (safety, warnings, conversation closed).',
    )
    system_code = models.CharField(
        max_length=64,
        blank=True,
        default='',
        verbose_name='System message code',
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name='Sent at',
        db_index=True
    )

    class Meta:
        verbose_name = 'Chat message'
        verbose_name_plural = 'Chat messages'
        ordering = ['created_at']

    def __str__(self):
        if self.is_system:
            return f'System message in room {self.room_id} at {self.created_at}'
        name = self.sender.get_full_name() if self.sender_id else 'System'
        return f"Message from {name} at {self.created_at}"
