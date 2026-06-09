"""HTML + plain-text templates for AutoHandy OTP emails (email-client safe, inline CSS only)."""


def build_login_code_email(code: str, *, expires_minutes: int = 5) -> tuple[str, str, str]:
    """Return (subject, plain_text, html) for sign-in OTP."""
    subject = 'Your AutoHandy sign-in code'
    plain = (
        f'Your AutoHandy sign-in code is: {code}\n\n'
        f'Enter this code in the app to continue. It expires in {expires_minutes} minutes.\n'
        'If you did not request this code, you can safely ignore this email.'
    )
    html = _otp_html(
        code=code,
        headline='Sign in to AutoHandy',
        intro='Use the verification code below to complete your sign-in. This code is valid for a limited time.',
        expires_minutes=expires_minutes,
        badge='Sign-in code',
    )
    return subject, plain, html


def build_email_verification_email(code: str, *, expires_minutes: int = 15) -> tuple[str, str, str]:
    """Return (subject, plain_text, html) for profile email verification OTP."""
    subject = 'Verify your AutoHandy email'
    plain = (
        f'Your AutoHandy email verification code is: {code}\n\n'
        f'Enter this code in the app. It expires in {expires_minutes} minutes.\n'
        'If you did not request this, you can ignore this message.'
    )
    html = _otp_html(
        code=code,
        headline='Verify your email',
        intro='Enter this code in the AutoHandy app to confirm your email address.',
        expires_minutes=expires_minutes,
        badge='Verification code',
    )
    return subject, plain, html


def _otp_html(
    *,
    code: str,
    headline: str,
    intro: str,
    expires_minutes: int,
    badge: str,
) -> str:
    # AutoHandy app palette: dark navy + orange accent (#F97316)
    digits = ''.join(
        f'<td style="width:52px;height:64px;text-align:center;vertical-align:middle;'
        f'background:#0F172A;border:2px solid #F97316;border-radius:12px;'
        f'font-size:28px;font-weight:700;color:#F97316;font-family:Consolas,Monaco,monospace;">{d}</td>'
        f'<td style="width:8px;"></td>'
        for d in code
    )
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <meta http-equiv="X-UA-Compatible" content="IE=edge">
  <title>{headline}</title>
</head>
<body style="margin:0;padding:0;background:#0B111D;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Arial,sans-serif;">
  <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background:#0B111D;">
    <tr>
      <td align="center" style="padding:40px 16px;">
        <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="max-width:560px;">
          <tr>
            <td style="padding:0 0 16px;text-align:center;">
              <span style="display:inline-block;padding:8px 16px;background:#1A2332;border:1px solid #F97316;
                border-radius:999px;font-size:11px;font-weight:700;letter-spacing:0.1em;text-transform:uppercase;color:#F97316;">
                {badge}
              </span>
            </td>
          </tr>
          <tr>
            <td style="background:#101828;border-radius:20px;overflow:hidden;
              box-shadow:0 16px 48px rgba(0,0,0,0.45);border:1px solid #1E293B;">
              <table role="presentation" width="100%" cellspacing="0" cellpadding="0">
                <tr>
                  <td style="padding:32px 32px 28px;background:linear-gradient(145deg,#101828 0%,#151D2E 50%,#1A2332 100%);
                    border-bottom:3px solid #F97316;">
                    <table role="presentation" width="100%" cellspacing="0" cellpadding="0">
                      <tr>
                        <td style="font-size:28px;font-weight:800;color:#FFFFFF;letter-spacing:-0.02em;">
                          <span style="color:#F97316;">A</span>utoHandy
                        </td>
                        <td align="right" style="font-size:26px;line-height:1;color:#F97316;">🔧</td>
                      </tr>
                      <tr>
                        <td colspan="2" style="padding-top:20px;font-size:22px;font-weight:700;color:#FFFFFF;">
                          {headline}
                        </td>
                      </tr>
                      <tr>
                        <td colspan="2" style="padding-top:8px;font-size:14px;line-height:1.5;color:#94A3B8;">
                          On-demand auto help, wherever you are
                        </td>
                      </tr>
                    </table>
                  </td>
                </tr>
                <tr>
                  <td style="padding:28px 32px 8px;font-size:16px;line-height:1.65;color:#CBD5E1;">
                    {intro}
                  </td>
                </tr>
                <tr>
                  <td align="center" style="padding:16px 24px 28px;">
                    <table role="presentation" cellspacing="0" cellpadding="0" style="margin:0 auto;">
                      <tr>{digits}</tr>
                    </table>
                  </td>
                </tr>
                <tr>
                  <td style="padding:0 32px 28px;">
                    <table role="presentation" width="100%" cellspacing="0" cellpadding="0"
                      style="background:#0F172A;border:1px solid #334155;border-left:4px solid #F97316;border-radius:14px;">
                      <tr>
                        <td style="padding:16px 18px;font-size:14px;line-height:1.6;color:#94A3B8;">
                          <strong style="color:#F97316;">Expires in {expires_minutes} minutes.</strong>
                          Never share this code with anyone. AutoHandy support will never ask for it.
                        </td>
                      </tr>
                    </table>
                  </td>
                </tr>
                <tr>
                  <td style="padding:0 32px 32px;font-size:13px;line-height:1.6;color:#64748B;">
                    If you did not request this code, you can safely ignore this email.
                    Someone may have entered your address by mistake.
                  </td>
                </tr>
              </table>
            </td>
          </tr>
          <tr>
            <td style="padding:24px 8px 0;text-align:center;font-size:12px;line-height:1.6;color:#64748B;">
              © AutoHandy · Professional auto services on your terms<br>
              <span style="color:#475569;">This is an automated message — please do not reply.</span>
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>"""
