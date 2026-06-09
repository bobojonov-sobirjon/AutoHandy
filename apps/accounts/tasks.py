from __future__ import annotations

from celery import shared_task


@shared_task(
    ignore_result=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    max_retries=3,
)
def send_login_email_code_task(email: str, sms_code: str) -> None:
    """Send login OTP email in the background so /api/auth/login/ returns immediately."""
    from apps.accounts.services import SMSService

    SMSService.send_email_code(email, sms_code)
