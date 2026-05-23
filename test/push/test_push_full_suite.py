#!/usr/bin/env python
"""
To'liq push test: chat (HTTP) + complete + barcha kindlar + Celery/timer (vaqt kutmasdan).

Driver user_id=2, Master user_id=3. Har push orasida telefonni tekshirish uchun pauza.

Ishlatish:
  python test/push/test_push_full_suite.py
  python test/push/test_push_full_suite.py --pause 8
  python test/push/test_push_full_suite.py --phase chat --pause 8
  python test/push/test_push_full_suite.py --phase kinds --pause 8
  python test/push/test_push_full_suite.py --phase celery --pause 8
  python test/push/test_push_full_suite.py --skip-api   # server yo'q bo'lsa HTTP o'tkaziladi

Env: FCM_TOKEN, API_BASE, DRIVER_JWT, MASTER_JWT, PAUSE_SEC
"""
from __future__ import annotations

import argparse
import importlib.util
import os
import sys
import time
from datetime import timedelta
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

import django  # noqa: E402

django.setup()

DRIVER_USER_ID = 2
MASTER_USER_ID = 3
DEFAULT_MASTER_PK = 3
DEFAULT_FCM = (
    'flRdi1gDS3O09ALrQv89-Q:APA91bEONw8snPjlkyuTWc67T5673Wbcso0HQD3vkaEH0TQL3srJvS7bOJCKDVzz-'
    'YNp8Xi7EwJPrPWr8jun9dWzX7YhKraKEml1UgXNZ4SdF8fG86b4C6Y'
)


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


_push_all = _load_module('test_push_all', ROOT / 'test' / 'push' / 'test_push_all.py')
_api_flow = _load_module('test_api_push_flow', ROOT / 'test' / 'push' / 'test_api_push_flow.py')


def pause(sec: float, msg: str) -> None:
    if sec <= 0:
        return
    print(f'  ... {msg} ({sec}s — telefonda push tekshiring)')
    time.sleep(sec)


def register_tokens(fcm: str) -> None:
    from apps.accounts.models import UserDevice

    for uid in (DRIVER_USER_ID, MASTER_USER_ID):
        row, created = UserDevice.objects.update_or_create(
            user_id=uid,
            defaults={'device_token': fcm, 'device_type': 'android', 'is_active': True},
        )
        print(f'UserDevice user_id={uid} created={created} token={row.device_token[:20]}…')


def run_step(label: str, fn: Callable[[], object], delay: float) -> bool:
    print(f'\n>>> [{label}]')
    try:
        result = fn()
        if result is not None:
            print(f'    result={result!r}')
        print('    -> yuborildi (server log: FCM success=1)')
        pause(delay, 'keyingi push')
        return True
    except Exception as exc:  # noqa: BLE001
        print(f'    -> XATO: {exc}')
        pause(delay, 'keyingi push (xato dan keyin)')
        return False


def phase_complete_direct(order_id: int, delay: float) -> None:
    from apps.order.services.notifications import (
        notify_user_order_event,
        notify_user_order_payment_charged,
    )

    order = _push_all._mock_order(order_id, DRIVER_USER_ID, master_id=DEFAULT_MASTER_PK)
    print('\n=== COMPLETE push (Stripe siz — to\'g\'ridan-to\'g\'ri) ===')
    run_step(
        'user:order_completed',
        lambda: notify_user_order_event(
            order,
            title='Order completed',
            body=f'Order #{order_id} is complete.',
            kind='order_completed',
            extra_data={'status': 'completed'},
        ),
        delay,
    )
    run_step(
        'user:order_payment_charged',
        lambda: notify_user_order_payment_charged(order, amount_cents=1500),
        delay,
    )


def phase_chat_http(base: str, driver_jwt: str, master_jwt: str, delay: float) -> None:
    print('\n=== CHAT (HTTP API) ===')
    driver = _api_flow.ApiClient(base, driver_jwt, 'DRIVER')
    master = _api_flow.ApiClient(base, master_jwt, 'MASTER')
    _api_flow.run_chat_flow(driver, master, delay)


def phase_all_kinds(order_id: int, delay: float) -> None:
    print('\n=== BARCHA PUSH KINDLAR (driver + master) ===')
    if not _push_all._preflight_push_users(user_id=DRIVER_USER_ID, master_user_id=MASTER_USER_ID):
        print('Token yo\'q — register_tokens ishladi deb faraz qiling.')
    scenarios = _push_all._all_kind_scenarios(
        user_id=DRIVER_USER_ID,
        master_user_id=MASTER_USER_ID,
        order_id=order_id,
    )
    # chat ikkala tomonga alohida HTTP da; bu yerda ham chat kind bor
    print(f'Jami {len(scenarios)} ta push kind')
    ok = 0
    for label, fn in scenarios:
        if _push_all._run_push(label, fn, delay):
            ok += 1
    print(f'Kindlar: {ok}/{len(scenarios)} yuborildi')


def _post_standard(driver, master_pk: int, meta: dict, *, with_schedule: bool) -> tuple[int, str | None]:
    url = f'{driver.base}/api/order/standard/'
    pref_time = None
    for attempt in range(40):
        body = {
            'master_id': master_pk,
            'text': 'Push full suite test order',
            'location': meta['location'],
            'latitude': meta['latitude'],
            'longitude': meta['longitude'],
            'car_list': [meta['car_id']],
            'category_list': [meta['category_id']],
            'parts_purchase_required': False,
        }
        if with_schedule:
            pref_date, pref_time = _api_flow.unique_preferred_slot(attempt=attempt)
            body['preferred_date'] = pref_date
            body['preferred_time_start'] = pref_time
        resp = driver.session.post(url, json=body, timeout=90)
        if resp.status_code == 201:
            order = resp.json().get('order') or resp.json()
            return int(order['id']), pref_time
        if resp.status_code == 400 and with_schedule and 'preferred_time_start' in resp.text:
            continue
        raise RuntimeError(f'standard create failed: {resp.status_code} {resp.text[:300]}')
    raise RuntimeError('standard create: 40 slot band')


def phase_celery_real_paths(
    base: str,
    driver_jwt: str,
    master_jwt: str,
    delay: float,
) -> None:
    """Production sweep/task funksiyalari + DB backdate (vaqt kutmasdan)."""
    from django.core.cache import cache
    from django.utils import timezone

    from apps.order.models import Order, OrderStatus
    from apps.order.services.offer_expiry import (
        expire_master_offer_for_order,
        handle_accepted_no_departure_for_order,
    )
    from apps.order.services.scheduled_mvp import (
        send_scheduled_no_start_warning,
        send_scheduled_reminder_before_start,
    )
    from apps.order.services.sos_mvp import send_sos_no_departure_warning
    from apps.order.tasks import (
        auto_cancel_master_no_show_task,
        sos_on_the_way_communication_reminder_task,
        unlock_client_penalty_free_cancel_task,
        warn_upcoming_order_deadlines_task,
    )

    driver = _api_flow.ApiClient(base, driver_jwt, 'DRIVER')
    master = _api_flow.ApiClient(base, master_jwt, 'MASTER')
    meta = _api_flow.discover_payload(driver, DEFAULT_MASTER_PK)
    now = timezone.now()

    print('\n=== CELERY / TIMEOUT pushlar (haqiqiy kod yo\'li) ===')

    # 1) Offer expired
    oid = _post_standard(driver, DEFAULT_MASTER_PK, meta, with_schedule=True)[0]
    Order.objects.filter(pk=oid).update(master_response_deadline=now - timedelta(minutes=2))
    run_step('celery:offer_expired', lambda: expire_master_offer_for_order(oid), delay)

    # 2) Offer expiring soon (beat task)
    oid2 = _post_standard(driver, DEFAULT_MASTER_PK, meta, with_schedule=True)[0]
    Order.objects.filter(pk=oid2).update(master_response_deadline=now + timedelta(minutes=2))
    cache.delete(f'push_warn_offer_deadline_{oid2}')

    def _warn_deadlines():
        return warn_upcoming_order_deadlines_task()

    run_step('celery:offer_expiring_soon (+ arrival/penalty warn)', _warn_deadlines, delay)

    # 3) Standard no departure auto-cancel (schedule siz)
    oid3 = _post_standard(driver, DEFAULT_MASTER_PK, meta, with_schedule=False)[0]
    master.request('POST', f'/api/order/{oid3}/accept/', json_body={}, expected=(200, 201))
    Order.objects.filter(pk=oid3).update(accepted_at=now - timedelta(minutes=35))
    run_step(
        'celery:auto_cancel_no_departure',
        lambda: handle_accepted_no_departure_for_order(order_id=oid3),
        delay,
    )

    # 4) Scheduled: 1h reminder
    oid4, _ = _post_standard(driver, DEFAULT_MASTER_PK, meta, with_schedule=True)
    master.request('POST', f'/api/order/{oid4}/accept/', json_body={}, expected=(200, 201))
    start = now + timedelta(minutes=30)
    Order.objects.filter(pk=oid4).update(
        preferred_date=start.date(),
        preferred_time_start=start.time().replace(second=0, microsecond=0),
    )
    cache.delete(f'scheduled_reminder_{oid4}')
    run_step(
        'celery:scheduled_start_reminder',
        lambda: send_scheduled_reminder_before_start(order_id=oid4, now=now),
        delay,
    )

    # 5) Scheduled: +20 min warning
    oid5, _ = _post_standard(driver, DEFAULT_MASTER_PK, meta, with_schedule=True)
    master.request('POST', f'/api/order/{oid5}/accept/', json_body={}, expected=(200, 201))
    past_start = now - timedelta(minutes=25)
    Order.objects.filter(pk=oid5).update(
        preferred_date=past_start.date(),
        preferred_time_start=past_start.time().replace(second=0, microsecond=0),
    )
    cache.delete(f'scheduled_no_start_warn_{oid5}')
    run_step(
        'celery:scheduled_no_start_warning',
        lambda: send_scheduled_no_start_warning(order_id=oid5, now=now),
        delay,
    )

    # 6) On the way: penalty-free unlock
    oid6 = _post_standard(driver, DEFAULT_MASTER_PK, meta, with_schedule=False)[0]
    master.request('POST', f'/api/order/{oid6}/accept/', json_body={}, expected=(200, 201))
    master.request('POST', f'/api/order/{oid6}/status/', json_body={
        'status': 'on_the_way', 'eta_minutes': 20,
    }, expected=(200,))
    Order.objects.filter(pk=oid6).update(
        on_the_way_at=now - timedelta(hours=2),
        client_penalty_free_cancel_unlocked=False,
    )
    run_step(
        'celery:penalty_free_unlocked',
        lambda: unlock_client_penalty_free_cancel_task(oid6),
        delay,
    )

    # 7) On the way: no-show auto-cancel
    oid7 = _post_standard(driver, DEFAULT_MASTER_PK, meta, with_schedule=False)[0]
    master.request('POST', f'/api/order/{oid7}/accept/', json_body={}, expected=(200, 201))
    master.request('POST', f'/api/order/{oid7}/status/', json_body={
        'status': 'on_the_way', 'eta_minutes': 15,
    }, expected=(200,))
    Order.objects.filter(pk=oid7).update(arrival_deadline_at=now - timedelta(minutes=1))
    run_step('celery:auto_cancel_no_show', lambda: auto_cancel_master_no_show_task(oid7), delay)

    # 8) SOS departure warning (accepted SOS yoki standard SOS type emulyatsiya)
    oid8 = _post_standard(driver, DEFAULT_MASTER_PK, meta, with_schedule=False)[0]
    master.request('POST', f'/api/order/{oid8}/accept/', json_body={}, expected=(200, 201))
    Order.objects.filter(pk=oid8).update(
        order_type='sos',
        accepted_at=now - timedelta(minutes=5),
        on_the_way_at=None,
    )
    run_step(
        'celery:sos_departure_warning',
        lambda: send_sos_no_departure_warning(order_id=oid8),
        delay,
    )

    # 9) SOS on_the_way communication reminder
    oid9 = _post_standard(driver, DEFAULT_MASTER_PK, meta, with_schedule=False)[0]
    master.request('POST', f'/api/order/{oid9}/accept/', json_body={}, expected=(200, 201))
    master.request('POST', f'/api/order/{oid9}/status/', json_body={'status': 'on_the_way'}, expected=(200,))
    Order.objects.filter(pk=oid9).update(order_type='sos')
    run_step(
        'celery:sos_communication_reminder',
        lambda: sos_on_the_way_communication_reminder_task(oid9),
        delay,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description='Full push suite: chat + kinds + celery timers')
    parser.add_argument('--pause', type=float, default=float(os.environ.get('PAUSE_SEC', '8')))
    parser.add_argument('--fcm-token', default=os.environ.get('FCM_TOKEN', DEFAULT_FCM))
    parser.add_argument('--base', default=os.environ.get('API_BASE', 'http://127.0.0.1:8001'))
    parser.add_argument('--driver-jwt', default=os.environ.get('DRIVER_JWT', _api_flow.DEFAULT_DRIVER_JWT))
    parser.add_argument('--master-jwt', default=os.environ.get('MASTER_JWT', _api_flow.DEFAULT_MASTER_JWT))
    parser.add_argument('--order-id', type=int, default=96, help='complete/kinds uchun order id')
    parser.add_argument(
        '--phase',
        choices=['all', 'register', 'chat', 'complete', 'kinds', 'celery'],
        default='all',
    )
    parser.add_argument('--skip-api', action='store_true', help='HTTP (chat/celery) o\'tkazib yuborish')
    args = parser.parse_args()

    print('=' * 60)
    print('AutoHandy FULL PUSH SUITE')
    print(f'  driver={DRIVER_USER_ID} master={MASTER_USER_ID} pause={args.pause}s')
    print('=' * 60)

    if args.phase in ('all', 'register'):
        register_tokens(args.fcm_token)
        pause(args.pause, 'token register')

    if args.skip_api and args.phase in ('all', 'chat', 'celery'):
        print('\n--skip-api: chat va celery HTTP qadamlari o\'tkazildi')

    if not args.skip_api and args.phase in ('all', 'chat'):
        try:
            phase_chat_http(args.base, args.driver_jwt, args.master_jwt, args.pause)
        except Exception as exc:  # noqa: BLE001
            print(f'CHAT HTTP xato (server ishlayaptimi?): {exc}')

    if args.phase in ('all', 'complete'):
        phase_complete_direct(args.order_id, args.pause)

    if args.phase in ('all', 'kinds'):
        phase_all_kinds(args.order_id, args.pause)

    if not args.skip_api and args.phase in ('all', 'celery'):
        try:
            phase_celery_real_paths(args.base, args.driver_jwt, args.master_jwt, args.pause)
        except Exception as exc:  # noqa: BLE001
            print(f'CELERY phase xato: {exc}')

    print('\n' + '=' * 60)
    print('TUGADI.')
    print('Telefonda qidiring: Master is on the way, Work started, offer expired,')
    print('scheduled reminder, penalty unlock, no-show cancel, chat message, order completed, …')
    print('=' * 60)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
