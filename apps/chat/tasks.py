"""Celery tasks for chat lifecycle."""
from __future__ import annotations

from celery import shared_task


@shared_task(name='apps.chat.tasks.close_expired_chat_rooms_task')
def close_expired_chat_rooms_task() -> int:
    from apps.chat.services import close_due_chat_rooms

    return close_due_chat_rooms()
