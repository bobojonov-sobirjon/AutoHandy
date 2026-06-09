"""Send email verification code (OTP-style, no external link)."""
import random
from datetime import timedelta

from django.conf import settings
from django.core.mail import send_mail
from django.utils import timezone

from .email_templates import build_email_verification_email


def generate_email_verification_code() -> str:
    return str(random.randint(1000, 9999))


def send_email_verification_message(to_email: str, code: str) -> None:
    minutes = int(getattr(settings, 'EMAIL_VERIFICATION_CODE_MINUTES', 15))
    subject, plain, html = build_email_verification_email(code, expires_minutes=minutes)
    send_mail(
        subject,
        plain,
        settings.DEFAULT_FROM_EMAIL,
        [to_email],
        html_message=html,
        fail_silently=False,
    )


def issue_and_send_email_verification(user, *, email: str | None = None):
    """Invalidate old codes, create a new one, send email with numeric code."""
    from apps.accounts.models import EmailVerificationToken

    target_email = (email or user.email or '').strip().lower()
    if not target_email:
        raise ValueError('User has no email address.')

    minutes = int(getattr(settings, 'EMAIL_VERIFICATION_CODE_MINUTES', 15))
    expires_at = timezone.now() + timedelta(minutes=minutes)
    code = generate_email_verification_code()

    EmailVerificationToken.objects.filter(user=user, is_used=False).update(is_used=True)
    token_obj = EmailVerificationToken.objects.create(
        user=user,
        email=target_email,
        code=code,
        expires_at=expires_at,
    )
    send_email_verification_message(target_email, code)
    return token_obj
