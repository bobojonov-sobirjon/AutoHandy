from __future__ import annotations

from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.chat.constants import (
    CONTACT_WARNING_TEXT,
    CONVERSATION_CLOSED_TEXT,
    MESSAGING_CLOSED_ERROR,
    SAFETY_WELCOME_TEXT,
    SYSTEM_CODE_CONTACT_WARNING,
    SYSTEM_CODE_CONVERSATION_CLOSED,
    SYSTEM_CODE_SAFETY_WELCOME,
)
from apps.chat.contact_detection import message_contains_contact_info
from apps.chat.models import ChatMessage, ChatRoom


class ChatMessagingClosedError(Exception):
    def __init__(self, message: str = MESSAGING_CLOSED_ERROR):
        self.message = message
        super().__init__(message)


def chat_close_grace_hours() -> int:
    return int(getattr(settings, 'CHAT_CLOSE_HOURS_AFTER_ORDER_COMPLETE', 2) or 2)


def create_system_message(*, room: ChatRoom, text: str, system_code: str) -> ChatMessage:
    return ChatMessage.objects.create(
        room=room,
        sender=None,
        message_type='system',
        text=text,
        is_system=True,
        system_code=system_code,
        is_read=False,
    )


def post_safety_welcome_if_needed(*, room: ChatRoom) -> ChatMessage | None:
    if room.messages.filter(is_system=True, system_code=SYSTEM_CODE_SAFETY_WELCOME).exists():
        return None
    return create_system_message(
        room=room,
        text=SAFETY_WELCOME_TEXT,
        system_code=SYSTEM_CODE_SAFETY_WELCOME,
    )


def post_contact_warning(*, room: ChatRoom) -> ChatMessage:
    return create_system_message(
        room=room,
        text=CONTACT_WARNING_TEXT,
        system_code=SYSTEM_CODE_CONTACT_WARNING,
    )


def post_conversation_closed_if_needed(*, room: ChatRoom) -> ChatMessage | None:
    if room.messages.filter(is_system=True, system_code=SYSTEM_CODE_CONVERSATION_CLOSED).exists():
        return None
    return create_system_message(
        room=room,
        text=CONVERSATION_CLOSED_TEXT,
        system_code=SYSTEM_CODE_CONVERSATION_CLOSED,
    )


@transaction.atomic
def refresh_room_messaging_state(*, room: ChatRoom, ensure_closed_banner: bool = False) -> ChatRoom:
    """
    Lazy-close: if grace period ended, set is_active=False and optionally insert closed banner.
    Also back-fill closes_at from linked completed order when missing.
    """
    room = ChatRoom.objects.select_for_update().get(pk=room.pk)
    sync_closes_at_from_completed_order(room=room)

    from apps.order.models import Order, OrderStatus

    terminal = {OrderStatus.COMPLETED, OrderStatus.CANCELLED, OrderStatus.REJECTED}
    if (
        not room.messaging_is_open()
        and Order.objects.filter(chat_room_id=room.pk).exclude(status__in=terminal).exists()
    ):
        room.is_active = True
        room.closes_at = None
        room.save(update_fields=['is_active', 'closes_at', 'updated_at'])

    now = timezone.now()
    if room.closes_at and now >= room.closes_at and room.is_active:
        room.is_active = False
        room.save(update_fields=['is_active', 'updated_at'])

    if ensure_closed_banner and not room.messaging_is_open():
        post_conversation_closed_if_needed(room=room)

    return room


def sync_closes_at_from_completed_order(*, room: ChatRoom) -> None:
    """For legacy rooms: derive closes_at from latest completed order."""
    if room.closes_at is not None:
        return
    from apps.order.models import Order, OrderStatus

    terminal = {OrderStatus.COMPLETED, OrderStatus.CANCELLED, OrderStatus.REJECTED}
    if Order.objects.filter(chat_room_id=room.pk).exclude(status__in=terminal).exists():
        # Active order reuses this room — do not inherit close time from an older completed order.
        return

    order = (
        Order.objects.filter(chat_room_id=room.pk, status=OrderStatus.COMPLETED)
        .order_by('-updated_at')
        .only('updated_at')
        .first()
    )
    if not order or not order.updated_at:
        return
    room.closes_at = order.updated_at + timedelta(hours=chat_close_grace_hours())
    room.save(update_fields=['closes_at', 'updated_at'])


@transaction.atomic
def reopen_order_chat_messaging(*, room: ChatRoom) -> ChatRoom:
    """
    Re-enable messaging when the same customer/master pair starts a new order.
    Clears the previous grace-period deadline so history stays readable but sending works again.
    """
    room = ChatRoom.objects.select_for_update().get(pk=room.pk)
    if room.is_active and room.closes_at is None:
        return room
    room.is_active = True
    room.closes_at = None
    room.save(update_fields=['is_active', 'closes_at', 'updated_at'])
    return room


@transaction.atomic
def schedule_order_chat_grace_period(*, order) -> None:
    """Call when order moves to COMPLETED — chat stays open for N hours."""
    room_id = getattr(order, 'chat_room_id', None)
    if not room_id:
        return
    room = ChatRoom.objects.select_for_update().get(pk=room_id)
    room.closes_at = timezone.now() + timedelta(hours=chat_close_grace_hours())
    room.is_active = True
    room.save(update_fields=['closes_at', 'is_active', 'updated_at'])


def assert_room_allows_messaging(*, room: ChatRoom) -> None:
    room = refresh_room_messaging_state(room=room)
    if not room.messaging_is_open():
        raise ChatMessagingClosedError()


def after_user_message_saved(*, room: ChatRoom, message: ChatMessage) -> list[ChatMessage]:
    """
    Post-send hooks: contact-info warning (message is never blocked).
    Returns extra system messages to broadcast.
    """
    extras: list[ChatMessage] = []
    if message.is_system:
        return extras
    if message.message_type == 'text' and message_contains_contact_info(message.text):
        extras.append(post_contact_warning(room=room))
    return extras


@transaction.atomic
def get_or_create_order_chat_room(*, master_user, customer_user) -> tuple[ChatRoom, bool]:
    """
    Create a **new** 1:1 chat room for this order accept.

    Same customer/master pair always gets a fresh room so previous order threads
    (and any conflicts) stay isolated — delivery-style, not a lifelong DM.

    Returns (room, created). ``created`` is always True.
    """
    room = ChatRoom.objects.create(initiator=master_user, is_active=True, closes_at=None)
    room.participants.add(master_user, customer_user)
    post_safety_welcome_if_needed(room=room)
    return room, True


def close_due_chat_rooms(*, limit: int = 200) -> int:
    """Celery sweep: finalize rooms whose grace period ended."""
    now = timezone.now()
    qs = (
        ChatRoom.objects.filter(is_active=True, closes_at__isnull=False, closes_at__lte=now)
        .order_by('closes_at')[: max(1, int(limit))]
    )
    closed = 0
    for room in qs:
        refresh_room_messaging_state(room=room, ensure_closed_banner=True)
        closed += 1
    return closed


def broadcast_chat_messages(*, room_id: int, messages: list) -> None:
    """Best-effort WS broadcast for REST-created messages (serializers already built)."""
    if not messages:
        return
    try:
        import logging

        from asgiref.sync import async_to_sync
        from channels.layers import get_channel_layer

        layer = get_channel_layer()
        if not layer:
            return
        for payload in messages:
            async_to_sync(layer.group_send)(
                f'chat_{room_id}',
                {'type': 'chat_message', 'message': payload},
            )
    except Exception as exc:  # noqa: BLE001
        logging.getLogger(__name__).exception('chat_broadcast_failed room_id=%s: %s', room_id, exc)
