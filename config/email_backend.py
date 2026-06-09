"""Email backends for VPS hosts where outbound SMTP (587/465) is blocked."""
from __future__ import annotations

import socket
from typing import Iterable

import requests
from django.conf import settings
from django.core.mail.backends.base import BaseEmailBackend
from django.core.mail.backends.smtp import EmailBackend as SMTPEmailBackend
from django.core.mail.message import EmailMessage


class IPv4EmailBackend(SMTPEmailBackend):
    """SMTP over IPv4 only (helps when IPv6 routing is broken)."""

    def open(self):
        original_getaddrinfo = socket.getaddrinfo

        def ipv4_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
            return original_getaddrinfo(
                host, port, socket.AF_INET, type, proto, flags
            )

        socket.getaddrinfo = ipv4_getaddrinfo
        try:
            return super().open()
        finally:
            socket.getaddrinfo = original_getaddrinfo


def _html_body(message: EmailMessage) -> str | None:
    for content, mimetype in getattr(message, 'alternatives', []) or []:
        if mimetype == 'text/html':
            return content
    return None


def _request_timeout() -> int:
    return int(getattr(settings, 'EMAIL_TIMEOUT', 10) or 10)


class ResendEmailBackend(BaseEmailBackend):
    """Send mail via Resend HTTPS API (port 443 — works when SMTP is blocked)."""

    def send_messages(self, email_messages: Iterable[EmailMessage]) -> int:
        api_key = (getattr(settings, 'RESEND_API_KEY', '') or '').strip()
        if not api_key:
            if self.fail_silently:
                return 0
            raise ValueError('RESEND_API_KEY is not configured')

        sent = 0
        for message in email_messages:
            payload = {
                'from': message.from_email or settings.DEFAULT_FROM_EMAIL,
                'to': list(message.to),
                'subject': message.subject,
                'text': message.body,
            }
            html = _html_body(message)
            if html:
                payload['html'] = html

            response = requests.post(
                'https://api.resend.com/emails',
                json=payload,
                headers={
                    'Authorization': f'Bearer {api_key}',
                    'Content-Type': 'application/json',
                },
                timeout=_request_timeout(),
            )
            if response.status_code >= 400:
                if self.fail_silently:
                    continue
                raise RuntimeError(
                    f'Resend API error {response.status_code}: {response.text}'
                )
            sent += 1
        return sent


class SendGridEmailBackend(BaseEmailBackend):
    """Send mail via SendGrid HTTPS API (port 443)."""

    def send_messages(self, email_messages: Iterable[EmailMessage]) -> int:
        api_key = (getattr(settings, 'SENDGRID_API_KEY', '') or '').strip()
        if not api_key:
            if self.fail_silently:
                return 0
            raise ValueError('SENDGRID_API_KEY is not configured')

        sent = 0
        for message in email_messages:
            content = [{'type': 'text/plain', 'value': message.body}]
            html = _html_body(message)
            if html:
                content.append({'type': 'text/html', 'value': html})

            payload = {
                'personalizations': [
                    {'to': [{'email': address} for address in message.to]},
                ],
                'from': {'email': message.from_email or settings.DEFAULT_FROM_EMAIL},
                'subject': message.subject,
                'content': content,
            }
            response = requests.post(
                'https://api.sendgrid.com/v3/mail/send',
                json=payload,
                headers={
                    'Authorization': f'Bearer {api_key}',
                    'Content-Type': 'application/json',
                },
                timeout=_request_timeout(),
            )
            if response.status_code >= 400:
                if self.fail_silently:
                    continue
                raise RuntimeError(
                    f'SendGrid API error {response.status_code}: {response.text}'
                )
            sent += 1
        return sent
