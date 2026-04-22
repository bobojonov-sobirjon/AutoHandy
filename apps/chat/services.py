from __future__ import annotations

from django.db import transaction

from apps.chat.models import ChatRoom


@transaction.atomic
def get_or_create_order_chat_room(*, master_user, customer_user) -> ChatRoom:
    """
    Ensure a 1:1 chat room between the two users.
    master_user becomes initiator; customer_user is receiver.
    """
    existing = (
        ChatRoom.objects.filter(participants=master_user)
        .filter(participants=customer_user)
        .distinct()
        .first()
    )
    if existing:
        # If room exists but initiator is missing/wrong, keep existing room (don't mutate old chats).
        return existing

    room = ChatRoom.objects.create(initiator=master_user)
    room.participants.add(master_user, customer_user)
    return room

