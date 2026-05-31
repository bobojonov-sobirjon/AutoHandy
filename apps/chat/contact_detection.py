"""Detect contact information in chat text (message is never blocked)."""
from __future__ import annotations

import re

# Phone: US/international-ish (+998, +1, grouped digits, 7+ digits total)
_PHONE_RE = re.compile(
    r'(?:'
    r'\+?\d{1,3}[\s\-.]?\(?\d{2,4}\)?[\s\-.]?\d{2,4}[\s\-.]?\d{2,4}[\s\-.]?\d{0,4}'
    r'|\b\d{3}[\s\-.]?\d{3}[\s\-.]?\d{4}\b'
    r'|\b\d{7,15}\b'
    r')',
    re.IGNORECASE,
)

_EMAIL_RE = re.compile(
    r'\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b',
    re.IGNORECASE,
)

_URL_RE = re.compile(
    r'(?:https?://|www\.)\S+|\b[a-z0-9][a-z0-9\-]{0,62}\.(?:com|net|org|io|uz|ru|me|co|app)\b\S*',
    re.IGNORECASE,
)

_MESSENGER_KEYWORDS = re.compile(
    r'\b(?:'
    r'whatsapp|wa\.me|'
    r'telegram|t\.me|tg://|'
    r'signal|signal\.me|'
    r'messenger|m\.me|facebook\s*messenger|fb\.me|'
    r'viber|wechat|snapchat|instagram\s*dm|insta\s*dm'
    r')\b',
    re.IGNORECASE,
)

# @username handles often used to move off-platform
_HANDLE_RE = re.compile(r'@[A-Za-z0-9_]{3,32}\b')


def message_contains_contact_info(text: str | None) -> bool:
    """Return True if text likely contains off-platform contact details."""
    raw = (text or '').strip()
    if not raw:
        return False
    if _EMAIL_RE.search(raw):
        return True
    if _URL_RE.search(raw):
        return True
    if _MESSENGER_KEYWORDS.search(raw):
        return True
    if _PHONE_RE.search(raw):
        return True
    if _HANDLE_RE.search(raw):
        return True
    return False
