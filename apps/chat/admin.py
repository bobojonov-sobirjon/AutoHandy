from django.contrib import admin
from django.urls import reverse
from django.utils.html import format_html

from .models import ChatMessage, ChatRoom


class ChatMessageInline(admin.TabularInline):
    model = ChatMessage
    extra = 0
    fields = ('sender', 'message_type', 'text_preview', 'is_read', 'created_at')
    readonly_fields = ('text_preview', 'created_at')
    raw_id_fields = ('sender',)
    show_change_link = True
    ordering = ('-created_at',)

    @admin.display(description='Text')
    def text_preview(self, obj):
        t = (obj.text or '').strip()
        if not t:
            return '—'
        return (t[:80] + '…') if len(t) > 80 else t


@admin.register(ChatRoom)
class ChatRoomAdmin(admin.ModelAdmin):
    list_display = ('participants_short', 'order_links', 'initiator', 'created_at', 'updated_at')
    list_filter = ('created_at', 'updated_at')
    search_fields = (
        'participants__email',
        'participants__first_name',
        'participants__last_name',
        'initiator__email',
    )
    filter_horizontal = ('participants',)
    readonly_fields = ('order_links', 'created_at', 'updated_at')
    inlines = (ChatMessageInline,)
    list_per_page = 25

    @admin.display(description='Participants')
    def participants_short(self, obj):
        names = [(p.get_full_name() or p.email or str(p.pk)).strip() for p in obj.participants.all()[:4]]
        suffix = '…' if obj.participants.count() > 4 else ''
        return ', '.join([n for n in names if n]) + suffix

    @admin.display(description='Order')
    def order_links(self, obj):
        """
        Chat rooms are linked to orders via Order.chat_room (related_name='orders').
        Usually it's one order; show up to a few just in case.
        """
        qs = obj.orders.all().only('id', 'order_type')[:5]
        if not qs:
            return '—'
        links = []
        for o in qs:
            url = reverse('admin:order_order_change', args=[o.id])
            ot = (getattr(o, 'order_type', '') or '').strip()
            label = ot.replace('_', ' ').title() if ot else ''
            suffix = f' ({label})' if label else ''
            links.append(format_html('<a href="{}">#{}{}</a>', url, o.id, suffix))
        out = format_html(', '.join(['{}'] * len(links)), *links)
        if obj.orders.count() > 5:
            return format_html('{} …', out)
        return out
