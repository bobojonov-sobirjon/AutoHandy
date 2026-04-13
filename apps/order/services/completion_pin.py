"""4-digit completion PIN: issued when work starts (in_progress); client shows it, master submits it on complete."""

import secrets

from django.utils import timezone


def issue_completion_pin(order) -> None:
    """Set a new 4-digit PIN on the order. Caller must save."""
    order.completion_pin = f'{secrets.randbelow(10000):04d}'
    order.completion_pin_issued_at = timezone.now()


def clear_completion_pin(order) -> None:
    """Remove PIN (complete, cancel, etc.). Caller must save."""
    order.completion_pin = ''
    order.completion_pin_issued_at = None
