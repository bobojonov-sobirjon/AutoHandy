"""
Direct FCM push check for a device token (no JWT, no UserDevice required).

Server / local:

  python manage.py test_fcm_push --token "eRNkfLYbakMQrt5_4AfOkt:APA91b..."

Optional:

  python manage.py test_fcm_push --token "..." --title "Test" --body "Hello"
  python manage.py test_fcm_push --user-id 3
"""
from __future__ import annotations

from dataclasses import dataclass

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError


@dataclass
class FcmProbeResult:
    ok: bool
    project_id: str
    token_length: int
    token_prefix: str
    success_count: int
    failure_count: int
    message_id: str
    error_code: str
    error_message: str
    db_user_id: int | None
    db_device_type: str
    db_is_active: bool | None
    notes: list[str]


def probe_fcm_token(
    *,
    token: str,
    title: str = 'AutoHandy test push',
    body: str = 'If you see this, FCM works for this token.',
) -> FcmProbeResult:
    """
    Send one FCM message to ``token`` using FIREBASE_MASTER_* credentials.
    Returns a structured result (success / failure + Firebase error text).
    """
    from apps.accounts.models import UserDevice
    from apps.order.services.notifications import (
        _firebase_service_account_from_env,
        _get_firebase_app,
    )

    token = (token or '').strip()
    notes: list[str] = []
    if not token:
        raise ValueError('token is empty')

    sa = _firebase_service_account_from_env('FIREBASE_MASTER_')
    project_id = (sa.get('project_id') or '').strip()
    if not project_id or not sa.get('private_key') or not sa.get('client_email'):
        raise RuntimeError(
            'FIREBASE_MASTER_* env incomplete '
            '(need PROJECT_ID, PRIVATE_KEY, CLIENT_EMAIL).'
        )

    device = (
        UserDevice.objects.filter(device_token=token)
        .select_related('user')
        .order_by('-updated_at')
        .first()
    )
    db_user_id = device.user_id if device else None
    db_device_type = (getattr(device, 'device_type', '') or '') if device else ''
    db_is_active = bool(device.is_active) if device else None
    if device is None:
        notes.append('Token is NOT in UserDevice — app may not have registered it.')
    elif not device.is_active:
        notes.append(f'Token is in DB but is_active=False (user_id={device.user_id}).')
    else:
        notes.append(f'Token is active in DB for user_id={device.user_id}.')

    try:
        from firebase_admin import messaging
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f'firebase-admin not installed: {exc}') from exc

    app = _get_firebase_app('user')
    channel_id = (
        str(getattr(settings, 'PUSH_ANDROID_CHANNEL_ID', '') or '').strip()
        or 'high_importance_channel'
    )
    message = messaging.Message(
        token=token,
        notification=messaging.Notification(title=title, body=body),
        data={
            'kind': 'test_fcm_push',
            'source': 'manage.py test_fcm_push',
        },
        android=messaging.AndroidConfig(
            priority='high',
            notification=messaging.AndroidNotification(
                sound='default',
                channel_id=channel_id,
            ),
        ),
        apns=messaging.APNSConfig(
            headers={'apns-priority': '10'},
            payload=messaging.APNSPayload(aps=messaging.Aps(sound='default')),
        ),
    )

    success_count = 0
    failure_count = 0
    message_id = ''
    error_code = ''
    error_message = ''
    try:
        message_id = str(messaging.send(message, app=app) or '')
        success_count = 1
        notes.append('FCM accepted the message (token + Firebase project match).')
    except Exception as exc:  # noqa: BLE001
        failure_count = 1
        error_code = str(getattr(exc, 'code', '') or '')
        error_message = str(exc)
        notes.append('FCM rejected the token (wrong Firebase project, stale token, or APNs misconfig).')
        low = error_message.lower()
        if 'not registered' in low or 'not found' in low or 'requested entity was not found' in low:
            notes.append(
                'Typical cause: app google-services.json / GoogleService-Info.plist '
                f'project_id is not "{project_id}".'
            )

    return FcmProbeResult(
        ok=success_count > 0,
        project_id=project_id,
        token_length=len(token),
        token_prefix=token[:28],
        success_count=success_count,
        failure_count=failure_count,
        message_id=message_id,
        error_code=error_code,
        error_message=error_message,
        db_user_id=db_user_id,
        db_device_type=db_device_type,
        db_is_active=db_is_active,
        notes=notes,
    )


class Command(BaseCommand):
    help = 'Send one test FCM push to a device token and print success/failure.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--token',
            default='',
            help='FCM registration token from the client app.',
        )
        parser.add_argument(
            '--user-id',
            type=int,
            default=0,
            help='If set (and --token omitted), use active UserDevice tokens for this user.',
        )
        parser.add_argument('--title', default='AutoHandy test push')
        parser.add_argument(
            '--body',
            default='If you see this, FCM works for this token.',
        )

    def handle(self, *args, **options):
        token = (options.get('token') or '').strip()
        user_id = int(options.get('user_id') or 0)
        title = options['title']
        body = options['body']

        tokens: list[str] = []
        if token:
            tokens = [token]
        elif user_id:
            from apps.accounts.models import UserDevice

            tokens = list(
                UserDevice.objects.filter(user_id=user_id, is_active=True)
                .order_by('-updated_at')
                .values_list('device_token', flat=True)
            )
            if not tokens:
                raise CommandError(f'No active UserDevice for user_id={user_id}')
        else:
            raise CommandError('Pass --token "..." or --user-id N')

        any_ok = False
        for i, t in enumerate(tokens):
            self.stdout.write(self.style.NOTICE(f'\n=== Probe [{i}] ==='))
            try:
                result = probe_fcm_token(token=t, title=title, body=body)
            except Exception as exc:  # noqa: BLE001
                raise CommandError(str(exc)) from exc

            self.stdout.write(f'project_id:     {result.project_id}')
            self.stdout.write(f'token_length:   {result.token_length}')
            self.stdout.write(f'token_prefix:   {result.token_prefix}…')
            self.stdout.write(f'db_user_id:     {result.db_user_id}')
            self.stdout.write(f'db_device_type: {result.db_device_type or "-"}')
            self.stdout.write(f'db_is_active:   {result.db_is_active}')
            self.stdout.write(f'success:        {result.success_count}')
            self.stdout.write(f'failure:        {result.failure_count}')
            if result.message_id:
                self.stdout.write(f'message_id:     {result.message_id}')
            if result.error_code or result.error_message:
                self.stdout.write(f'error_code:     {result.error_code}')
                self.stdout.write(f'error_message:  {result.error_message}')
            for note in result.notes:
                self.stdout.write(f'- {note}')

            if result.ok:
                any_ok = True
                self.stdout.write(self.style.SUCCESS('RESULT: OK — phone should show the notification.'))
            else:
                self.stdout.write(self.style.ERROR('RESULT: FAIL — push did not leave FCM successfully.'))

        if not any_ok:
            raise SystemExit(1)
