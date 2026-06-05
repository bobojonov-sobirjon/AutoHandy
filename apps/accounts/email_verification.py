"""Send email verification code (OTP-style, no external link)."""
import random
from datetime import timedelta

from django.conf import settings
from django.core.mail import send_mail
from django.utils import timezone


def generate_email_verification_code() -> str:
    return str(random.randint(1000, 9999))


def send_email_verification_message(to_email: str, code: str) -> None:
    subject = 'Your AutoHandy verification code'
    plain = (
        'Your AutoHandy email verification code is:\n\n'
        f'{code}\n\n'
        'Enter this code in the app. It expires in a few minutes.\n'
        'If you did not request this, you can ignore this message.'
    )
    html = f"""
<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="margin:0;padding:0;background:#f4f6f8;font-family:Arial,sans-serif;">
  <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background:#f4f6f8;padding:32px 16px;">
    <tr>
      <td align="center">
        <table role="presentation" width="100%" style="max-width:520px;background:#ffffff;border-radius:12px;
          box-shadow:0 2px 8px rgba(0,0,0,.06);overflow:hidden;">
          <tr>
            <td style="padding:28px 32px 8px;font-size:20px;font-weight:700;color:#0d9488;">
              AutoHandy
            </td>
          </tr>
          <tr>
            <td style="padding:8px 32px 16px;font-size:15px;line-height:1.55;color:#334155;">
              Enter this code in the app to verify your email:
            </td>
          </tr>
          <tr>
            <td align="center" style="padding:8px 32px 32px;">
              <div style="display:inline-block;padding:16px 32px;background:#f0fdfa;border-radius:8px;
                font-size:32px;font-weight:700;letter-spacing:8px;color:#0d9488;">
                {code}
              </div>
            </td>
          </tr>
          <tr>
            <td style="padding:0 32px 28px;font-size:12px;line-height:1.5;color:#64748b;">
              This code expires soon. Do not share it with anyone.
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>
"""
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
