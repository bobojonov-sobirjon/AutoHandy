#!/usr/bin/env python
"""
AutoHandy — barcha push notificationlarni tekshirish.

Ishlatish: test/push/README.md

Misollar:
  python test/push/test_push_all.py diagnose --token "FCM_TOKEN"
  python test/push/test_push_all.py direct --token "FCM_TOKEN"
  python test/push/test_push_all.py register --user-id 1 --token "FCM_TOKEN"
  python test/push/test_push_all.py lifecycle --user-id 1 --order-id 10
  python test/push/test_push_all.py all-kinds --user-id 1 --master-user-id 2 --order-id 10
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

# Django setup
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

import django  # noqa: E402

django.setup()

DEFAULT_FCM_TOKEN = (
    'flRdi1gDS3O09ALrQv89-Q:APA91bEONw8snPjlkyuTWc67T5673Wbcso0HQD3vkaEH0TQL3srJvS7bOJCKDVzz-'
    'YNp8Xi7EwJPrPWr8jun9dWzX7YhKraKEml1UgXNZ4SdF8fG86b4C6Y'
)


@dataclass
class SendResult:
    success_count: int
    failure_count: int
    details: list[str]


def _token_from_args(args: argparse.Namespace) -> str:
    return (args.token or os.environ.get('TEST_FCM_TOKEN') or DEFAULT_FCM_TOKEN).strip()


def send_fcm_raw(
    *,
    tokens: list[str],
    title: str,
    body: str,
    data: dict[str, str] | None = None,
) -> SendResult:
    """To'g'ridan-to'g'ri FCM (UserDevice dan mustaqil)."""
    from django.conf import settings
    from firebase_admin import messaging

    from apps.order.services.notifications import _get_firebase_app

    if not tokens:
        return SendResult(0, 0, ['no tokens'])

    app = _get_firebase_app('master')
    channel_id = (
        str(getattr(settings, 'PUSH_ANDROID_CHANNEL_ID', '') or '').strip()
        or 'high_importance_channel'
    )
    payload_data = {str(k): str(v) for k, v in (data or {}).items()}
    msg = messaging.MulticastMessage(
        tokens=tokens,
        notification=messaging.Notification(title=title, body=body),
        data=payload_data,
        android=messaging.AndroidConfig(
            priority='high',
            notification=messaging.AndroidNotification(sound='default', channel_id=channel_id),
        ),
        apns=messaging.APNSConfig(
            headers={'apns-priority': '10'},
            payload=messaging.APNSPayload(aps=messaging.Aps(sound='default')),
        ),
    )
    if hasattr(messaging, 'send_each_for_multicast'):
        resp = messaging.send_each_for_multicast(msg, app=app)
    else:
        resp = messaging.send_multicast(msg, app=app)

    details: list[str] = []
    for i, r in enumerate(resp.responses):
        if r.success:
            details.append(f'  token[{i}]: OK')
        else:
            err = getattr(r, 'exception', None)
            details.append(f'  token[{i}]: FAIL code={getattr(err, "code", "")} err={err}')

    return SendResult(
        success_count=int(getattr(resp, 'success_count', 0) or 0),
        failure_count=int(getattr(resp, 'failure_count', 0) or 0),
        details=details,
    )


def cmd_diagnose(args: argparse.Namespace) -> int:
    from django.conf import settings

    from apps.order.services.notifications import _firebase_service_account_from_env

    token = _token_from_args(args)
    sa = _firebase_service_account_from_env('FIREBASE_MASTER_')
    print('=== Firebase (.env FIREBASE_MASTER_*) ===')
    print(f'  project_id:     {sa.get("project_id")}')
    print(f'  client_email:   {sa.get("client_email")}')
    print(f'  FCM_DEBUG:      {getattr(settings, "FCM_DEBUG", os.getenv("FCM_DEBUG"))}')
    print(f'  ANDROID_CH:     {getattr(settings, "PUSH_ANDROID_CHANNEL_ID", "")}')
    print('=== Token ===')
    print(f'  length:         {len(token)}')
    print(f'  prefix:         {token[:24]}…')
    print('=== Direct send (1 message) ===')
    res = send_fcm_raw(
        tokens=[token],
        title='AutoHandy diagnose',
        body='If you see this, FCM + token + Firebase project match.',
        data={'kind': 'test_diagnose'},
    )
    print(f'  success={res.success_count} failure={res.failure_count}')
    for line in res.details:
        print(line)
    if res.failure_count:
        print('\n>>> FAILURE: token boshqa Firebase project dan yoki eskirgan.')
        print('>>> Rider/Master app google-services.json project_id =', sa.get('project_id'), 'bo\'lishi kerak.')
    return 0 if res.success_count else 1


def cmd_direct(args: argparse.Namespace) -> int:
    token = _token_from_args(args)
    res = send_fcm_raw(
        tokens=[token],
        title=args.title,
        body=args.body,
        data={'kind': 'test_direct'},
    )
    print(f'success={res.success_count} failure={res.failure_count}')
    for line in res.details:
        print(line)
    return 0 if res.success_count else 1


def _resolve_user_id(args: argparse.Namespace) -> int | None:
    """user_id, --email yoki --phone orqali user topish."""
    from django.contrib.auth import get_user_model

    User = get_user_model()
    if getattr(args, 'user_id', None):
        uid = int(args.user_id)
        if User.objects.filter(pk=uid).exists():
            return uid
        print(f'XATO: user_id={uid} bazada yo\'q.')
        return None
    email = (getattr(args, 'email', None) or '').strip()
    if email:
        u = User.objects.filter(email__iexact=email).first()
        if u:
            return u.id
        print(f'XATO: email={email} topilmadi.')
        return None
    phone = (getattr(args, 'phone', None) or '').strip()
    if phone:
        u = User.objects.filter(phone_number=phone).first()
        if not u:
            u = User.objects.filter(phone_number__endswith=phone[-10:]).first()
        if u:
            return u.id
        print(f'XATO: phone={phone} topilmadi.')
        return None
    print('Kerak: --user-id ID yoki --email yoki --phone')
    return None


def cmd_list_users(args: argparse.Namespace) -> int:
    from apps.accounts.models import UserDevice
    from django.contrib.auth import get_user_model

    User = get_user_model()
    limit = int(args.limit)
    qs = User.objects.order_by('-id')[:limit]
    print(f'=== Oxirgi {limit} user (order yaratuvchi / master) ===')
    print(f'{"id":>6}  {"email":<28} {"phone":<16} device')
    print('-' * 70)
    for u in qs:
        dev = UserDevice.objects.filter(user_id=u.id).first()
        tok = (dev.device_token[:20] + '…') if dev and dev.device_token else '(yo\'q)'
        active = 'active' if dev and dev.is_active else ('inactive' if dev else '')
        email = (u.email or '-')[:28]
        phone = (u.phone_number or '-')[:16]
        print(f'{u.id:>6}  {email:<28} {phone:<16} {tok} {active}')
    print('\nRegister: python test/push/test_push_all.py register --user-id <ID> --token "..."')
    return 0


def cmd_register(args: argparse.Namespace) -> int:
    from apps.accounts.models import UserDevice
    from django.contrib.auth import get_user_model

    token = _token_from_args(args)
    uid = _resolve_user_id(args)
    if uid is None:
        print('\nMavjud userlarni ko\'rish: python test/push/test_push_all.py list-users')
        return 1

    User = get_user_model()
    user = User.objects.get(pk=uid)
    row, created = UserDevice.objects.update_or_create(
        user_id=uid,
        defaults={
            'device_token': token,
            'device_type': args.device_type,
            'is_active': True,
        },
    )
    label = user.email or user.phone_number or user.username
    print(f'OK UserDevice user_id={uid} ({label}) created={created}')
    print(f'   token_prefix={row.device_token[:20]}… device_type={row.device_type}')
    print('Keyingi: python test/push/test_push_all.py lifecycle --user-id', uid, '--order-id <ORDER_ID>')
    return 0


def _mock_order(order_id: int, user_id: int, master_id: int | None = None):
    """Minimal Order-like object for notify_* without DB."""
    from types import SimpleNamespace

    return SimpleNamespace(id=order_id, user_id=user_id, master_id=master_id, order_type='standard')


def _user_has_active_token(user_id: int) -> bool:
    from apps.accounts.models import UserDevice

    return UserDevice.objects.filter(user_id=user_id, is_active=True).exclude(device_token='').exists()


def _preflight_push_users(*, user_id: int, master_user_id: int | None = None) -> bool:
    ok = True
    if not _user_has_active_token(user_id):
        print(f'XATO: user_id={user_id} da UserDevice/token yo\'q — rider push ketmaydi.')
        print(f'      python test/push/test_push_all.py register --user-id {user_id} --token "..."')
        ok = False
    else:
        print(f'OK: user_id={user_id} da token bor (rider push ishlaydi).')
    if master_user_id is not None:
        if not _user_has_active_token(master_user_id):
            print(f'OGohlantirish: master user_id={master_user_id} da token yo\'q — master pushlar ketmaydi.')
            print(f'      python test/push/test_push_all.py register --user-id {master_user_id} --token "..."')
        else:
            print(f'OK: master user_id={master_user_id} da token bor.')
    return ok


def _pause(delay: float, label: str) -> None:
    if delay <= 0:
        return
    print(f'  … {label} ({delay}s)')
    time.sleep(delay)


def _run_push(label: str, fn: Callable[[], None], delay: float) -> bool:
    print(f'[{label}]')
    try:
        fn()
        print('  -> sent (check phone; see server log FCM success/failure)')
        _pause(delay, 'keyingisi')
        return True
    except Exception as exc:  # noqa: BLE001
        print(f'  -> ERROR: {exc}')
        _pause(delay, 'keyingisi')
        return False


def cmd_lifecycle(args: argparse.Namespace) -> int:
    from apps.order.services.notifications import notify_user_order_event

    uid = int(args.user_id)
    if not _preflight_push_users(user_id=uid):
        return 1
    oid = int(args.order_id)
    order = _mock_order(oid, uid, master_id=int(args.master_user_id) if args.master_user_id else None)
    delay = float(args.delay)

    steps = [
        ('order_accepted', lambda: notify_user_order_event(
            order, title='Order accepted', body=f'Order #{oid} accepted',
            kind='order_accepted', extra_data={'status': 'accepted'},
        )),
        ('order_status_changed → on_the_way', lambda: notify_user_order_event(
            order, title='Master is on the way', body=f'Order #{oid}: on the way',
            kind='order_status_changed', extra_data={'status': 'on_the_way'},
        )),
        ('order_status_changed → arrived', lambda: notify_user_order_event(
            order, title='Master arrived', body=f'Order #{oid}: arrived',
            kind='order_status_changed', extra_data={'status': 'arrived'},
        )),
        ('order_status_changed → in_progress', lambda: notify_user_order_event(
            order, title='Work started', body=f'Order #{oid}: in progress',
            kind='order_status_changed', extra_data={'status': 'in_progress'},
        )),
        ('order_completed', lambda: notify_user_order_event(
            order, title='Order completed', body=f'Order #{oid} completed',
            kind='order_completed', extra_data={'status': 'completed'},
        )),
        ('order_payment_charged', lambda: notify_user_order_event(
            order, title='Payment', body='Charged $10.00',
            kind='order_payment_charged', extra_data={'amount': '10.00'},
        )),
    ]
    print(f'=== Lifecycle pushes → user_id={uid} (UserDevice token kerak) ===')
    ok = 0
    for label, fn in steps:
        if _run_push(label, fn, delay):
            ok += 1
    print(f'Done: {ok}/{len(steps)}')
    return 0


def _all_kind_scenarios(
    *,
    user_id: int,
    master_user_id: int,
    order_id: int,
) -> list[tuple[str, Callable[[], None]]]:
    from apps.order.services.notifications import (
        notify_master_order_kind,
        notify_master_payout_day,
        notify_user_order_payment_charged,
        notify_user_cancellation_penalty_charged,
        notify_user_order_kind,
        notify_chat_message,
        send_fcm_to_user_devices,
    )

    order = _mock_order(order_id, user_id)
    out: list[tuple[str, Callable[[], None]]] = []

    def u(kind: str, **extra: str) -> None:
        notify_user_order_kind(order, kind=kind, extra_data=extra or None)

    def m(kind: str, **extra: str) -> None:
        notify_master_order_kind(
            master_user_id=master_user_id,
            order_id=order_id,
            kind=kind,
            extra_data=extra or None,
        )

    # —— Rider (user) — order lifecycle
    for label, fn in [
        ('user:order_accepted', lambda: u('order_accepted')),
        ('user:order_status_changed/on_the_way', lambda: u('order_status_changed', status='on_the_way')),
        ('user:order_status_changed/arrived', lambda: u('order_status_changed', status='arrived')),
        ('user:order_status_changed/in_progress', lambda: u('order_status_changed', status='in_progress')),
        ('user:order_completed', lambda: u('order_completed')),
        ('user:order_declined', lambda: u('order_declined')),
        ('user:order_cancelled', lambda: u('order_cancelled', by='master')),
        ('user:cancellation_penalty_charged', lambda: notify_user_cancellation_penalty_charged(order, amount_cents=500, penalty_percent=10)),
        ('user:order_payment_charged', lambda: notify_user_order_payment_charged(order, amount_cents=1000)),
        ('user:completion_pin_invalid', lambda: u('completion_pin_invalid')),
        ('user:order_services_added', lambda: u('order_services_added', service_count='2')),
        ('user:service_add_request', lambda: u('service_add_request')),
        ('user:custom_request_offer', lambda: u('custom_request_offer', price='$50.00', master_name='Test Master')),
        ('user:offer_expiring_soon', lambda: u('offer_expiring_soon', minutes_left='3')),
        ('user:sos_expiring_soon', lambda: u('sos_expiring_soon', minutes_left='3')),
        ('user:penalty_free_unlock_soon', lambda: u('penalty_free_unlock_soon')),
        ('user:penalty_free_unlocked', lambda: u('penalty_free_unlocked')),
        ('user:arrival_deadline_soon', lambda: u('arrival_deadline_soon')),
        ('user:auto_cancel_no_show', lambda: u('auto_cancel_no_show', by='system')),
        ('user:scheduled_start_reminder', lambda: u('scheduled_start_reminder', minutes_until_start='60')),
        ('user:scheduled_no_start_warning', lambda: u('scheduled_no_start_warning')),
        ('user:auto_cancel_scheduled_no_start', lambda: u('auto_cancel_scheduled_no_start')),
        ('user:auto_cancel_no_departure', lambda: u('auto_cancel_no_departure')),
        ('user:sos_rebroadcast', lambda: u('sos_rebroadcast')),
        ('user:sos_all_declined', lambda: u('sos_all_declined')),
        ('user:sos_expired', lambda: u('sos_expired')),
        ('user:extra_money_request', lambda: u('extra_money_request', amount='25.00')),
        ('user:offer_expired', lambda: u('offer_expired', by='system')),
    ]:
        out.append((label, fn))

    # —— Master
    for label, fn in [
        ('master:order_new', lambda: m('order_new', order_type='sos')),
        ('master:order_new/standard', lambda: m('order_new', order_type='standard')),
        ('master:offer_expiring_soon', lambda: m('offer_expiring_soon', minutes_left='3', order_type='standard')),
        ('master:offer_expired', lambda: m('offer_expired')),
        ('master:order_selected', lambda: m('order_selected')),
        ('master:custom_request_new', lambda: m('custom_request_new', order_type='custom_request')),
        ('master:penalty_free_unlock_soon', lambda: m('penalty_free_unlock_soon')),
        ('master:arrival_deadline_soon', lambda: m('arrival_deadline_soon')),
        ('master:auto_cancel_no_show', lambda: m('auto_cancel_no_show', by='system')),
        ('master:order_cancelled', lambda: m('order_cancelled', by='user')),
        ('master:sos_departure_warning', lambda: m('sos_departure_warning')),
        ('master:sos_unassigned_no_departure', lambda: m('sos_unassigned_no_departure')),
        ('master:sos_communication_reminder', lambda: m('sos_communication_reminder')),
        ('master:auto_cancel_no_departure', lambda: m('auto_cancel_no_departure')),
        ('master:scheduled_start_reminder', lambda: m('scheduled_start_reminder', minutes_until_start='60')),
        ('master:scheduled_no_start_warning', lambda: m('scheduled_no_start_warning')),
        ('master:auto_cancel_scheduled_no_start', lambda: m('auto_cancel_scheduled_no_start')),
        ('master:service_add_approved', lambda: m('service_add_approved')),
        ('master:service_add_rejected', lambda: m('service_add_rejected')),
        ('master:extra_money_approved', lambda: m('extra_money_approved', amount='5.00')),
        ('master:extra_money_rejected', lambda: m('extra_money_rejected')),
        ('master:payout_scheduled_today', lambda: notify_master_payout_day(master_user_id=master_user_id, anchor_day='monday')),
        ('master:review_created', lambda: m('review_created', rating='5', reviewer_name='Driver')),
    ]:
        out.append((label, fn))

    # Chat (production path)
    out.append((
        'chat:chat_message → user',
        lambda: notify_chat_message(
            recipient_user_id=user_id,
            room_id=1,
            message_id=1,
            message_type='text',
            text='Test chat from all-kinds',
            sender_display='Test',
        ),
    ))
    return out


def args_room_id(_: int) -> str:
    return '1'


def cmd_all_kinds(args: argparse.Namespace) -> int:
    uid = int(args.user_id)
    mid = int(args.master_user_id)
    oid = int(args.order_id)
    delay = float(args.delay)
    print('=== Preflight ===')
    if not _preflight_push_users(user_id=uid, master_user_id=mid):
        print('\n42 ishlatmaying — list-users dan haqiqiy id oling (masalan 3).')
        return 1
    print()
    scenarios = _all_kind_scenarios(user_id=uid, master_user_id=mid, order_id=oid)
    print(f'=== {len(scenarios)} push kinds → user_id={uid}, master_user_id={mid} ===')
    ok = 0
    for label, fn in scenarios:
        if _run_push(label, fn, delay):
            ok += 1
    print(f'Done: {ok}/{len(scenarios)}')
    return 0


def cmd_mvp(args: argparse.Namespace) -> int:
    """Faqat MVP timer / SOS / scheduled kindlar."""
    uid = int(args.user_id)
    mid = int(args.master_user_id)
    print('=== Preflight ===')
    if not _preflight_push_users(user_id=uid, master_user_id=mid):
        print('\n42 ishlatmaying — lifecycle ishlagan user-id ni ishlating (masalan 3).')
        return 1
    print()
    all_scenarios = _all_kind_scenarios(
        user_id=uid,
        master_user_id=mid,
        order_id=int(args.order_id),
    )
    mvp_prefixes = (
        'sos_', 'scheduled_', 'auto_cancel_scheduled', 'auto_cancel_no_departure',
        'sos_rebroadcast', 'master:sos_', 'user:sos_', 'user:scheduled',
    )
    scenarios = [(l, f) for l, f in all_scenarios if any(p in l for p in mvp_prefixes)]
    delay = float(args.delay)
    print(f'=== MVP: {len(scenarios)} pushes ===')
    for label, fn in scenarios:
        _run_push(label, fn, delay)
    return 0


def cmd_chat(args: argparse.Namespace) -> int:
    from apps.order.services.notifications import notify_chat_message

    recipient_id = int(args.recipient_user_id or args.user_id)
    if not _preflight_push_users(user_id=recipient_id):
        return 1
    room_id = int(args.room_id)
    message_id = int(args.message_id)
    sent = notify_chat_message(
        recipient_user_id=recipient_id,
        room_id=room_id,
        message_id=message_id,
        message_type='text',
        text=args.text or 'Test chat push from test_push_all.py',
        sender_display=args.sender or 'Test sender',
    )
    print(f'chat_message -> user_id={recipient_id} room_id={room_id} FCM success={sent}')
    if sent <= 0:
        print('Push ketmadi: recipient da token yo\'q yoki FCM xato.')
        return 1
    return 0


def cmd_chat_rooms(args: argparse.Namespace) -> int:
    from django.contrib.auth import get_user_model

    from apps.chat.models import ChatRoom

    User = get_user_model()
    uid = int(args.user_id)
    user = User.objects.filter(pk=uid).first()
    if not user:
        print(f'user_id={uid} topilmadi')
        return 1
    qs = ChatRoom.objects.filter(participants=uid).order_by('-updated_at')[: int(args.limit)]
    print(f'=== Chat rooms for user_id={uid} ===')
    if not qs:
        print('Chat yo\'q. Order accept qilingan bo\'lsa chat room yaratiladi.')
        return 0
    for room in qs:
        other = room.get_other_participant(user)
        other_id = other.id if other else '?'
        last = room.messages.order_by('-created_at').first()
        last_txt = (last.text or last.message_type)[:40] if last else '-'
        print(f'  room_id={room.id}  other_user_id={other_id}  last={last_txt!r}')
    print('\nTest: python test/push/test_push_all.py chat --recipient-user-id <OTHER> --room-id <ID> --user-id <RECIPIENT same>')
    return 0


def cmd_via_backend_path(args: argparse.Namespace) -> int:
    """UserDevice + send_fcm_to_user_devices (production code path)."""
    from apps.order.services.notifications import send_fcm_to_user_devices

    token = _token_from_args(args)
    uid = _resolve_user_id(args)
    if uid is None:
        return 1
    args.user_id = uid
    cmd_register(args)
    res_fn = lambda: send_fcm_to_user_devices(
        user_id=uid,
        firebase_kind='user',
        title='Backend path test',
        body='send_fcm_to_user_devices via UserDevice',
        data={'kind': 'test_backend_path'},
    )
    print('=== Production path (UserDevice lookup) ===')
    _run_push('backend_path', res_fn, 0)
    # Also direct compare
    print('=== Direct token (same message) ===')
    r = send_fcm_raw(tokens=[token], title='Direct compare', body='Same phone?', data={'kind': 'test_direct'})
    print(f'  direct success={r.success_count} failure={r.failure_count}')
    return 0


def cmd_api_lifecycle(args: argparse.Namespace) -> int:
    """HTTP: register device, test-push, status transitions (needs JWT + running server)."""
    try:
        import requests
    except ImportError:
        print('pip install requests kerak: pip install requests')
        return 1

    base = (os.environ.get('API_BASE') or args.api_base or 'http://127.0.0.1:8001').rstrip('/')
    rider_jwt = os.environ.get('RIDER_JWT') or args.rider_jwt
    master_jwt = os.environ.get('MASTER_JWT') or args.master_jwt
    order_id = os.environ.get('ORDER_ID') or args.order_id
    token = _token_from_args(args)

    if not rider_jwt or not master_jwt or not order_id:
        print('Kerak: RIDER_JWT, MASTER_JWT, ORDER_ID (env yoki --rider-jwt --master-jwt --order-id)')
        return 1

    headers_rider = {'Authorization': f'Bearer {rider_jwt}', 'Content-Type': 'application/json'}
    headers_master = {'Authorization': f'Bearer {master_jwt}', 'Content-Type': 'application/json'}

    def post(path: str, body: dict, headers: dict) -> requests.Response:
        url = f'{base}{path}'
        print(f'POST {url}')
        r = requests.post(url, json=body, headers=headers, timeout=60)
        print(f'  -> {r.status_code} {r.text[:200]}')
        return r

    def patch(path: str, body: dict, headers: dict) -> requests.Response:
        url = f'{base}{path}'
        print(f'PATCH {url} body={body}')
        r = requests.patch(url, json=body, headers=headers, timeout=60)
        print(f'  -> {r.status_code} {r.text[:300]}')
        return r

    # 1) Register token as rider
    post('/api/auth/device/', {'device_token': token, 'device_type': 'android'}, headers_rider)

    # 2) Test push endpoint
    post('/api/auth/device/test-push/', {'title': 'API test', 'body': 'test-push endpoint', 'firebase_kind': 'user'}, headers_rider)

    oid = int(order_id)
    delay = float(args.delay)

    # 3) Status flow (master) — on_the_way needs eta for standard
    for status, extra in [
        ('on_the_way', {'eta_minutes': 30}),
        ('arrived', {}),
        ('in_progress', {}),
    ]:
        body = {'status': status, **extra}
        patch(f'/api/order/{oid}/status/', body, headers_master)
        _pause(delay, status)

    print('Tugadi. Rider telefonida har status uchun push kelishi kerak.')
    return 0


def build_parser() -> argparse.ArgumentParser:
    parent = argparse.ArgumentParser(add_help=False)
    parent.add_argument('--token', help='FCM device token (default: built-in test token)')

    p = argparse.ArgumentParser(description='AutoHandy push notification tests')
    p.add_argument('--token', help='FCM device token (default: built-in test token)')
    sub = p.add_subparsers(dest='command', required=True)

    d = sub.add_parser('diagnose', parents=[parent], help='Firebase env + 1 direct FCM')
    d.set_defaults(func=cmd_diagnose)

    d = sub.add_parser('direct', parents=[parent], help='Send 1 message directly to token')
    d.add_argument('--title', default='AutoHandy direct test')
    d.add_argument('--body', default='Direct FCM to your token')
    d.set_defaults(func=cmd_direct)

    r = sub.add_parser('list-users', help='Bazadagi user id lar (register uchun)')
    r.add_argument('--limit', type=int, default=20)
    r.set_defaults(func=cmd_list_users)

    r = sub.add_parser('register', parents=[parent], help='Save token to UserDevice for user')
    r.add_argument('--user-id', type=int, default=None, help='accounts_customuser.id')
    r.add_argument('--email', default='', help='User email (user-id o\'rniga)')
    r.add_argument('--phone', default='', help='User phone (user-id o\'rniga)')
    r.add_argument('--device-type', default='android')
    r.set_defaults(func=cmd_register)

    r = sub.add_parser('backend-path', parents=[parent], help='register + send_fcm_to_user_devices')
    r.add_argument('--user-id', type=int, default=None)
    r.add_argument('--email', default='')
    r.add_argument('--phone', default='')
    r.add_argument('--device-type', default='android')
    r.set_defaults(func=cmd_via_backend_path)

    lc = sub.add_parser('lifecycle', parents=[parent], help='Order create→complete push kinds (user)')
    lc.add_argument('--user-id', type=int, required=True)
    lc.add_argument('--order-id', type=int, default=9999)
    lc.add_argument('--master-user-id', type=int, default=None)
    lc.add_argument('--delay', type=float, default=3.0)
    lc.set_defaults(func=cmd_lifecycle)

    ak = sub.add_parser('all-kinds', parents=[parent], help='All known push kinds')
    ak.add_argument('--user-id', type=int, required=True)
    ak.add_argument('--master-user-id', type=int, required=True)
    ak.add_argument('--order-id', type=int, default=9999)
    ak.add_argument('--delay', type=float, default=2.0)
    ak.set_defaults(func=cmd_all_kinds)

    mv = sub.add_parser('mvp', parents=[parent], help='SOS + scheduled MVP kinds only')
    mv.add_argument('--user-id', type=int, required=True)
    mv.add_argument('--master-user-id', type=int, required=True)
    mv.add_argument('--order-id', type=int, default=9999)
    mv.add_argument('--delay', type=float, default=2.0)
    mv.set_defaults(func=cmd_mvp)

    ch = sub.add_parser('chat', parents=[parent], help='Chat push (production notify_chat_message path)')
    ch.add_argument('--recipient-user-id', type=int, default=None, help='Kim push oladi')
    ch.add_argument('--user-id', type=int, default=None, help='recipient-user-id o\'rniga')
    ch.add_argument('--room-id', type=int, default=1)
    ch.add_argument('--message-id', type=int, default=1)
    ch.add_argument('--text', default='Salom, bu chat test push')
    ch.add_argument('--sender', default='AutoHandy test')
    ch.set_defaults(func=cmd_chat)

    cr = sub.add_parser('chat-rooms', help='User chat xonalari ro\'yxati')
    cr.add_argument('--user-id', type=int, required=True)
    cr.add_argument('--limit', type=int, default=10)
    cr.set_defaults(func=cmd_chat_rooms)

    api = sub.add_parser('api-lifecycle', parents=[parent], help='Real HTTP API status flow')
    api.add_argument('--api-base', default='http://127.0.0.1:8001')
    api.add_argument('--rider-jwt', default='')
    api.add_argument('--master-jwt', default='')
    api.add_argument('--order-id', default='')
    api.add_argument('--delay', type=float, default=5.0)
    api.set_defaults(func=cmd_api_lifecycle)

    return p


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return int(args.func(args))


if __name__ == '__main__':
    raise SystemExit(main())
