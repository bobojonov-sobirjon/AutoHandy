"""Send HTML email with verification link for AutoHandy profile flow."""
from django.conf import settings
from django.core.mail import send_mail


def build_verification_url(token) -> str:
    base = getattr(settings, 'EMAIL_VERIFICATION_PUBLIC_BASE', '').rstrip('/')
    if not base:
        base = 'http://localhost:8000'
    token_str = str(token)
    return f"{base}/email-verification/token={token_str}"


def send_email_verification_message(to_email: str, verification_url: str) -> None:
    subject = "Verify your AutoHandy email"
    plain = (
        "Please verify your email address for your AutoHandy account.\n\n"
        f"Open this link to confirm: {verification_url}\n\n"
        "If you did not request this, you can ignore this message."
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
            <td style="padding:8px 32px 24px;font-size:15px;line-height:1.55;color:#334155;">
              We need you to verify your email address to complete your AutoHandy registration.
            </td>
          </tr>
          <tr>
            <td align="center" style="padding:8px 32px 32px;">
              <a href="{verification_url}" style="display:inline-block;padding:14px 28px;background:#0d9488;
                color:#ffffff;text-decoration:none;border-radius:8px;font-weight:600;font-size:15px;">
                Verify email
              </a>
            </td>
          </tr>
          <tr>
            <td style="padding:0 32px 28px;font-size:12px;line-height:1.5;color:#64748b;">
              Or copy this link into your browser:<br/>
              <span style="word-break:break-all;color:#0f766e;">{verification_url}</span>
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
