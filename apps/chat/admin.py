from django.contrib import admin
# from .models import ChatRoom, ChatMessage

"""
@admin.register(ChatRoom)
class ChatRoomAdmin(admin.ModelAdmin):
    list_display = ['id', 'get_participants', 'created_at', 'updated_at']
    list_filter = ['created_at', 'updated_at']
    search_fields = ['participants__email', 'participants__first_name', 'participants__last_name']
    filter_horizontal = ['participants']
    readonly_fields = ['created_at', 'updated_at']
    def get_participants(self, obj):
        return ', '.join([p.get_full_name() or p.email for p in obj.participants.all()])
    get_participants.short_description = 'Participants'

@admin.register(ChatMessage)
class ChatMessageAdmin(admin.ModelAdmin):
    list_display = ['id', 'room', 'sender_name', 'message_type', 'text_preview', 'is_read', 'created_at']
    list_filter = ['message_type', 'is_read', 'created_at']
    search_fields = ['text', 'sender__email', 'sender__first_name', 'sender__last_name']
    readonly_fields = ['created_at']
    list_per_page = 50
    def sender_name(self, obj):
        return obj.sender.get_full_name() or obj.sender.email
    sender_name.short_description = 'Sender'
    def text_preview(self, obj):
        if obj.text:
            return obj.text[:50] + '...' if len(obj.text) > 50 else obj.text
        return '-'
    text_preview.short_description = 'Text'
"""
