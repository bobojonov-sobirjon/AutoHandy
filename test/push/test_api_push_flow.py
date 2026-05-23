#!/usr/bin/env python
"""
AutoHandy — to'liq API orqali push notification test (requests).

Driver (user 2) + Master (user 3) JWT bilan order yaratishdan complete/chat gacha.

Ishlatish:
  1) Server: python manage.py runserver 8001
  2) Celery worker + beat (MVP timer pushlar uchun ixtiyoriy)
  3) python test/push/test_api_push_flow.py
  4) python test/push/test_api_push_flow.py --only chat
  5) python test/push/test_api_push_flow.py --only mvp-tasks --order-id 123

Env (ixtiyoriy):
  API_BASE, DRIVER_JWT, MASTER_JWT, FCM_TOKEN, PAUSE_SEC
"""
from __future__ import annotations

import argparse
import base64
import io
import json
import os
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

try:
    import requests
except ImportError:
    print('pip install requests')
    raise SystemExit(1)

ROOT = Path(__file__).resolve().parents[2]

# --- Default credentials (env bilan override) ---
DEFAULT_DRIVER_JWT = (
    'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJ0b2tlbl90eXBlIjoiYWNjZXNzIiwiZXhwIjoxNzc5OD'
    'cwMjg4LCJpYXQiOjE3NzkyNjU0ODgsImp0aSI6IjRjOTc4NmZjMWQyODQxZGNhMjg0OGM4NzM5YTM3ZDIx'
    'IiwidXNlcl9pZCI6Mn0.j_jfX5DmOgZCsTvSAIihiph3xQRJzyvK10sib0tvR4E'
)
DEFAULT_MASTER_JWT = (
    'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJ0b2tlbl90eXBlIjoiYWNjZXNzIiwiZXhwIjoxNzgwMTE'
    '2NTg0LCJpYXQiOjE3Nzk1MTE3ODQsImp0aSI6Ijc2MWU0YmU3MTI2YTQwYWM4ZjRjNzYyMzFjOGEzNTk1'
    'IiwidXNlcl9pZCI6M30.dSoyzigYDUZDZP6PCuscnZgzSpbgH6JhmTpMHvZa8zQ'
)
DEFAULT_FCM = (
    'flRdi1gDS3O09ALrQv89-Q:APA91bEONw8snPjlkyuTWc67T5673Wbcso0HQD3vkaEH0TQL3srJvS7bOJCKDVzz-'
    'YNp8Xi7EwJPrPWr8jun9dWzX7YhKraKEml1UgXNZ4SdF8fG86b4C6Y'
)

DRIVER_USER_ID = 2
MASTER_USER_ID = 3
DEFAULT_MASTER_PK = 3  # Master profile id (user 3)

# Master workshop coords (DB dan)
DEFAULT_LAT = 39.8041397
DEFAULT_LON = 64.4282619

# 1x1 PNG
TINY_PNG = base64.b64decode(
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=='
)


class ApiClient:
    def __init__(self, base: str, jwt: str, label: str) -> None:
        self.base = base.rstrip('/')
        self.label = label
        self.session = requests.Session()
        self.session.headers.update({
            'Authorization': f'Bearer {jwt}',
            'Accept': 'application/json',
        })

    def request(
        self,
        method: str,
        path: str,
        *,
        json_body: dict | None = None,
        data: dict | None = None,
        files: dict | None = None,
        expected: tuple[int, ...] = (200, 201),
    ) -> requests.Response:
        url = f'{self.base}{path}'
        print(f'\n[{self.label}] {method} {path}')
        if json_body is not None:
            print(f'  body: {json.dumps(json_body, ensure_ascii=True)[:300]}')
        resp = self.session.request(method, url, json=json_body, data=data, files=files, timeout=90)
        ok = resp.status_code in expected
        mark = 'OK' if ok else 'FAIL'
        snippet = resp.text[:400].encode('ascii', 'replace').decode('ascii')
        print(f'  -> {mark} {resp.status_code} {snippet}')
        if not ok:
            raise RuntimeError(f'{method} {path} failed: {resp.status_code} {resp.text[:500]}')
        return resp


def pause(sec: float, msg: str) -> None:
    if sec <= 0:
        return
    print(f'  ... {msg} ({sec}s - telefonda push tekshiring)')
    time.sleep(sec)


def unique_preferred_slot(days_ahead: int = 14, attempt: int = 0) -> tuple[str, str]:
    """Master band slotlari bilan to'qnashmaslik uchun sana/vaqt (attempt har safar boshqa slot)."""
    total_slots = (int(time.time()) // 60 + attempt * 41) % (45 * 56)
    day_off = days_ahead + total_slots // 56
    slot = total_slots % 56
    hour = 7 + (slot // 4)
    minute = (slot % 4) * 15
    d = date.today() + timedelta(days=day_off)
    return d.isoformat(), f'{hour:02d}:{minute:02d}:00'


def preferred_time_end_after(start: str, hours: int = 2) -> str:
    parts = start.split(':')
    h, m = int(parts[0]), int(parts[1])
    h2 = min(h + hours, 23)
    return f'{h2:02d}:{m:02d}:00'


def create_standard_order(driver: ApiClient, master_pk: int, meta: dict) -> tuple[int, str]:
    url = f'{driver.base}/api/order/standard/'
    pref_time = '10:00:00'
    for attempt in range(40):
        pref_date, pref_time = unique_preferred_slot(attempt=attempt)
        body = {
            'master_id': master_pk,
            'text': 'API push test - standard order',
            'location': meta['location'],
            'latitude': meta['latitude'],
            'longitude': meta['longitude'],
            'car_list': [meta['car_id']],
            'category_list': [meta['category_id']],
            'preferred_date': pref_date,
            'preferred_time_start': pref_time,
            'parts_purchase_required': False,
        }
        print(f'\n[DRIVER] POST /api/order/standard/ (attempt {attempt + 1})')
        print(f'  body: {json.dumps(body, ensure_ascii=True)[:300]}')
        resp = driver.session.post(url, json=body, timeout=90)
        snippet = resp.text[:400].encode('ascii', 'replace').decode('ascii')
        print(f'  -> {"OK" if resp.status_code == 201 else "FAIL"} {resp.status_code} {snippet}')
        if resp.status_code == 201:
            data = resp.json()
            order = data.get('order') or data
            return int(order['id']), pref_time
        if resp.status_code == 400 and 'preferred_time_start' in resp.text:
            continue
        raise RuntimeError(f'POST /api/order/standard/ failed: {resp.status_code} {resp.text[:500]}')
    raise RuntimeError('POST /api/order/standard/ failed: 40 ta slot band, boshqa master yoki sana sinab ko\'ring')


def register_devices(base: str, driver: ApiClient, master: ApiClient, fcm: str) -> None:
    def upsert_device(client: ApiClient) -> None:
        body = {'device_token': fcm, 'device_type': 'android'}
        url_path = '/api/auth/device/'
        url = f'{client.base}{url_path}'
        resp = client.session.post(url, json=body, timeout=90)
        if resp.status_code == 400 and 'already' in resp.text.lower():
            resp = client.session.put(url, json=body, timeout=90)
        print(f'\n[{client.label}] device register -> {resp.status_code}')
        if resp.status_code not in (200, 201):
            raise RuntimeError(f'device register failed: {resp.status_code} {resp.text}')

    upsert_device(driver)
    upsert_device(master)
    for client, kind in ((driver, 'user'), (master, 'master')):
        client.request('POST', '/api/auth/device/test-push/', json_body={
            'title': f'Test push ({kind})',
            'body': 'API flow test started',
            'firebase_kind': kind,
        }, expected=(200,))


def discover_payload(driver: ApiClient, master_pk: int) -> dict[str, Any]:
    cars_resp = driver.request('GET', '/api/car/', expected=(200,))
    cars = cars_resp.json()
    if isinstance(cars, dict) and 'results' in cars:
        cars = cars['results']
    car_id = cars[0]['id'] if cars else 1

    cat_resp = driver.request('GET', '/api/categories/categories/', expected=(200,))
    cats = cat_resp.json()
    if isinstance(cats, dict) and 'results' in cats:
        cats = cats['results']
    by_order = [
        c['id'] for c in cats
        if str(c.get('type_category', '')).lower() == 'by_order'
        and 'custom' not in str(c.get('name', '')).lower()
    ]
    category_id = by_order[0] if by_order else (cats[0]['id'] if cats else 5)

    master_resp = driver.request('GET', f'/api/master/masters/{master_pk}/', expected=(200,))
    md = master_resp.json()
    lat = float(md.get('latitude') or DEFAULT_LAT)
    lon = float(md.get('longitude') or DEFAULT_LON)

    # SOS uchun masterning haqiqiy xizmat kategoriyasi (Motor Detailing emas)
    sos_category_id = category_id
    try:
        svc_resp = driver.session.get(
            f'{driver.base}/api/order/services-list/?master_id={master_pk}',
            timeout=90,
        )
        if svc_resp.status_code == 200:
            svc_items = svc_resp.json()
            if isinstance(svc_items, list) and svc_items:
                first = svc_items[0]
                sos_category_id = int(first.get('category') or first.get('parent_category_id') or category_id)
    except Exception:  # noqa: BLE001
        pass

    return {
        'car_id': car_id,
        'category_id': category_id,
        'sos_category_id': sos_category_id,
        'latitude': lat,
        'longitude': lon,
        'location': md.get('address') or 'Test workshop location',
    }


def run_standard_lifecycle(
    *,
    base: str,
    driver: ApiClient,
    master: ApiClient,
    master_pk: int,
    pause_sec: float,
    skip_complete: bool,
) -> int:
    meta = discover_payload(driver, master_pk)
    order_id, pref_start = create_standard_order(driver, master_pk, meta)
    print(f'\n=== STANDARD order_id={order_id} ===')
    pause(pause_sec, 'order yaratildi (master: order_new/order_selected)')

    master.request('POST', f'/api/order/{order_id}/accept/', json_body={}, expected=(200, 201))
    pause(pause_sec, 'accept -> driver: order_accepted')

    master.request('PATCH', f'/api/order/{order_id}/preferred-time/', json_body={
        'preferred_time_end': preferred_time_end_after(pref_start, hours=2),
    }, expected=(200,))

    master.request('POST', f'/api/order/{order_id}/status/', json_body={
        'status': 'on_the_way',
        'eta_minutes': 25,
    }, expected=(200,))
    pause(pause_sec, 'on_the_way -> telefon: "Master is on the way"')

    master.request('POST', f'/api/order/{order_id}/status/', json_body={
        'status': 'arrived',
    }, expected=(200,))
    pause(pause_sec, 'arrived -> telefon: "Master arrived"')

    master.request('POST', f'/api/order/{order_id}/status/', json_body={
        'status': 'in_progress',
        'latitude': meta['latitude'],
        'longitude': meta['longitude'],
    }, expected=(200,))
    pause(pause_sec, 'in_progress -> telefon: "Work started" + PIN')

    # Service add request (master -> driver push)
    try:
        svc = master.request(
            'GET',
            f'/api/order/services-list/?master_id={master_pk}',
            expected=(200,),
        )
        svc_data = svc.json()
        items = svc_data if isinstance(svc_data, list) else svc_data.get('results', [])
        if items:
            sid = items[0].get('id') or items[0].get('master_service_item_id')
            master.request('POST', '/api/order/add-services/', json_body={
                'order_id': order_id,
                'services_list': [sid],
                'discount': 0,
                'comment': 'API test add services',
            }, expected=(201,))
            pause(pause_sec, 'service_add -> telefon: "Additional services request"')
            pending = driver.request('GET', '/api/order/service-add/requests/pending/', expected=(200,))
            plist = pending.json()
            if isinstance(plist, list) and plist:
                req_id = plist[0]['id']
                driver.request('POST', f'/api/order/service-add/requests/{req_id}/approve/', json_body={}, expected=(200, 201))
                pause(pause_sec, 'service_add_approved -> master push')
    except Exception as exc:  # noqa: BLE001
        print(f'  (add-services skipped: {exc})')

    try:
        master.request('POST', f'/api/order/{order_id}/extra-money/requests/', json_body={
            'amount': '5.00',
            'comment': 'API test extra money',
        }, expected=(201,))
        pause(pause_sec, 'extra_money_request -> driver push')
        pending_em = driver.request('GET', '/api/order/extra-money/requests/pending/', expected=(200,))
        em_list = pending_em.json()
        if isinstance(em_list, list) and em_list:
            em_id = em_list[0]['id']
            driver.request(
                'POST',
                f'/api/order/extra-money/requests/{em_id}/approve/',
                json_body={},
                expected=(200, 201),
            )
            pause(pause_sec, 'extra_money_approved -> master push')
    except Exception as exc:  # noqa: BLE001
        print(f'  (extra-money skipped: {exc})')

    # Work photo + complete
    master.request(
        'POST',
        f'/api/order/{order_id}/work-completion-image/',
        files={'image': ('work.png', io.BytesIO(TINY_PNG), 'image/png')},
        expected=(200, 201),
    )

    order_resp = driver.request('GET', f'/api/order/{order_id}/', expected=(200,))
    order_data = order_resp.json()
    pin = order_data.get('client_completion_pin') or order_data.get('completion_pin') or ''

    if skip_complete:
        print(f'  complete skipped (--skip-complete). PIN={pin!r}')
        return order_id

    if not pin:
        print('  WARNING: no completion_pin on order — complete skipped')
        return order_id

    try:
        master.request('POST', f'/api/order/{order_id}/complete/', json_body={
            'completion_pin': str(pin),
        }, expected=(200,))
        pause(pause_sec, 'complete -> order_completed + payment push')
    except RuntimeError as exc:
        print(f'  complete failed (Stripe/card?): {exc}')
        print('  Pushlar in_progress gacha ishladi. To\'liq complete uchun driver saved card kerak.')

    return order_id


def run_chat_flow(driver: ApiClient, master: ApiClient, pause_sec: float) -> None:
    print('\n=== CHAT push test ===')
    resp = driver.request('POST', '/api/chat/rooms/', json_body={
        'participant_id': MASTER_USER_ID,
    }, expected=(200, 201))
    room = resp.json()
    room_id = room.get('id') or room.get('room', {}).get('id')
    if not room_id:
        raise RuntimeError(f'chat room create: no id in {room}')

    driver.request('POST', f'/api/chat/rooms/{room_id}/messages/', json_body={
        'room': room_id,
        'message_type': 'text',
        'text': 'Driver -> Master chat push test',
    }, expected=(201,))
    pause(pause_sec, 'chat driver->master (master telefon)')

    master.request('POST', f'/api/chat/rooms/{room_id}/messages/', json_body={
        'room': room_id,
        'message_type': 'text',
        'text': 'Master -> Driver chat push test',
    }, expected=(201,))
    pause(pause_sec, 'chat master->driver (driver telefon)')


def create_sos_order(driver: ApiClient, meta: dict) -> int:
    body = {
        'text': 'API push test - SOS emergency',
        'location': meta['location'],
        'latitude': meta['latitude'],
        'longitude': meta['longitude'],
        'car_list': [meta['car_id']],
        'category_list': [meta['sos_category_id']],
        'priority': 'high',
        'parts_purchase_required': False,
    }
    resp = driver.request('POST', '/api/order/sos/', json_body=body, expected=(201,))
    data = resp.json()
    order = data.get('order') or data
    return int(order['id'])


def run_sos_lifecycle(
    driver: ApiClient,
    master: ApiClient,
    meta: dict,
    pause_sec: float,
    *,
    skip_complete: bool,
) -> int:
    print('\n=== SOS order push test ===')
    order_id = create_sos_order(driver, meta)
    print(f'  SOS order_id={order_id}')
    pause(pause_sec, 'SOS yaratildi -> master: order_new / sos push')

    master.request('GET', '/api/order/master/incoming-sync/', expected=(200,))
    try:
        master.request('POST', f'/api/order/{order_id}/accept/', json_body={}, expected=(200, 201))
        pause(pause_sec, 'SOS accept -> driver: order_accepted')
    except RuntimeError as exc:
        print(f'  SOS accept skipped (radius/queue?): {exc}')
        return order_id

    master.request('POST', f'/api/order/{order_id}/status/', json_body={
        'status': 'on_the_way',
    }, expected=(200,))
    pause(pause_sec, 'SOS on_the_way (ETA ixtiyoriy)')

    master.request('POST', f'/api/order/{order_id}/status/', json_body={'status': 'arrived'}, expected=(200,))
    master.request('POST', f'/api/order/{order_id}/status/', json_body={
        'status': 'in_progress',
        'latitude': meta['latitude'],
        'longitude': meta['longitude'],
    }, expected=(200,))
    pause(pause_sec, 'SOS in_progress')

    if skip_complete:
        return order_id

    order_resp = driver.request('GET', f'/api/order/{order_id}/', expected=(200,))
    pin = order_resp.json().get('client_completion_pin') or ''
    if pin:
        try:
            master.request('POST', f'/api/order/{order_id}/complete/', json_body={
                'completion_pin': str(pin),
            }, expected=(200,))
        except RuntimeError as exc:
            print(f'  SOS complete skipped: {exc}')
    return order_id


def create_custom_request_order(driver: ApiClient, meta: dict) -> int:
    pref_date, pref_time = unique_preferred_slot(days_ahead=21)
    png = io.BytesIO(TINY_PNG)
    files = [
        ('images', ('a.png', png, 'image/png')),
        ('images', ('b.png', io.BytesIO(TINY_PNG), 'image/png')),
    ]
    data = {
        'text': 'API push test - custom request',
        'location': meta['location'],
        'latitude': str(meta['latitude']),
        'longitude': str(meta['longitude']),
        'car_list': json.dumps([meta['car_id']]),
        'preferred_date': pref_date,
        'preferred_time_start': pref_time[:5],
        'parts_purchase_required': 'false',
    }
    url = f'{driver.base}/api/order/custom-request/'
    print(f'\n[DRIVER] POST /api/order/custom-request/ (multipart)')
    resp = driver.session.post(url, data=data, files=files, timeout=90)
    snippet = resp.text[:400].encode('ascii', 'replace').decode('ascii')
    print(f'  -> {"OK" if resp.status_code == 201 else "FAIL"} {resp.status_code} {snippet}')
    if resp.status_code != 201:
        raise RuntimeError(f'custom-request failed: {resp.status_code} {resp.text[:500]}')
    order = resp.json().get('order') or resp.json()
    return int(order['id'])


def run_custom_request_lifecycle(
    driver: ApiClient,
    master: ApiClient,
    master_pk: int,
    meta: dict,
    pause_sec: float,
) -> int:
    print('\n=== CUSTOM REQUEST push test ===')
    order_id = create_custom_request_order(driver, meta)
    print(f'  custom_request order_id={order_id}')
    pause(pause_sec, 'custom request yaratildi -> masterlar broadcast')

    master.request('POST', f'/api/order/custom-request/{order_id}/offers/', json_body={
        'price': '150.00',
    }, expected=(201,))
    pause(pause_sec, 'master offer -> driver: custom_request_offer')

    driver.request('POST', '/api/order/add-master/', json_body={
        'order_id': order_id,
        'master_id': master_pk,
    }, expected=(200, 201))
    pause(pause_sec, 'add-master -> master assigned')

    master.request('POST', f'/api/order/{order_id}/accept/', json_body={}, expected=(200, 201))
    pause(pause_sec, 'custom accept -> driver push')
    return order_id


def run_offer_expire_push_test(driver: ApiClient, master_pk: int, meta: dict) -> None:
    """Celery/beat o'rniga: deadline o'tgan pending order -> offer_expired push."""
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
    import django

    django.setup()
    from django.utils import timezone

    from apps.order.models import Order
    from apps.order.services.offer_expiry import expire_stale_master_offers

    print('\n=== OFFER EXPIRE (system) push test ===')
    order_id, _pref = create_standard_order(driver, master_pk, meta)
    past = timezone.now() - timedelta(minutes=5)
    Order.objects.filter(pk=order_id).update(master_response_deadline=past)
    n = expire_stale_master_offers()
    print(f'  expire_stale_master_offers touched={n} order_id={order_id}')
    print('  Telefon: driver + master offer_expired push')


def run_cancel_push_test(driver: ApiClient, master: ApiClient, master_pk: int, meta: dict, pause_sec: float) -> None:
    print('\n=== CANCEL push test (alohida order) ===')
    order_id, _pref = create_standard_order(driver, master_pk, meta)
    master.request('POST', f'/api/order/{order_id}/accept/', json_body={}, expected=(200, 201))
    driver.request('POST', f'/api/order/{order_id}/cancel/', json_body={}, expected=(200,))
    pause(pause_sec, 'cancel -> order_cancelled push')


def run_mvp_tasks(order_id: int) -> None:
    """Celery o'rniga MVP timer push funksiyalarini chaqirish (django kerak)."""
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
    import django

    django.setup()

    print(f'\n=== MVP timer pushes (order_id={order_id}) ===')
    from apps.order.services.sos_mvp import send_sos_no_departure_warning
    from apps.order.services.scheduled_mvp import (
        send_scheduled_reminder_before_start,
        send_scheduled_no_start_warning,
    )

    send_sos_no_departure_warning(order_id=order_id)
    print('  sos_departure_warning (master)')
    send_scheduled_reminder_before_start(order_id=order_id)
    print('  scheduled_start_reminder')
    send_scheduled_no_start_warning(order_id=order_id)
    print('  scheduled_no_start_warning')


def main() -> int:
    parser = argparse.ArgumentParser(description='Full API push notification flow test')
    parser.add_argument('--base', default=os.environ.get('API_BASE', 'http://127.0.0.1:8001'))
    parser.add_argument('--driver-jwt', default=os.environ.get('DRIVER_JWT', DEFAULT_DRIVER_JWT))
    parser.add_argument('--master-jwt', default=os.environ.get('MASTER_JWT', DEFAULT_MASTER_JWT))
    parser.add_argument('--fcm-token', default=os.environ.get('FCM_TOKEN', DEFAULT_FCM))
    parser.add_argument('--master-id', type=int, default=int(os.environ.get('MASTER_ID', DEFAULT_MASTER_PK)))
    parser.add_argument('--pause', type=float, default=float(os.environ.get('PAUSE_SEC', '4')))
    parser.add_argument('--skip-complete', action='store_true', help='Stripe/card bo\'lmasa complete o\'tkazib yuborish')
    parser.add_argument(
        '--only',
        choices=[
            'all', 'standard', 'sos', 'custom', 'chat', 'cancel',
            'expire', 'mvp-tasks',
        ],
        default='all',
    )
    parser.add_argument('--order-id', type=int, default=0, help='mvp-tasks uchun order id')
    args = parser.parse_args()

    driver = ApiClient(args.base, args.driver_jwt, 'DRIVER')
    master = ApiClient(args.base, args.master_jwt, 'MASTER')

    print('=' * 60)
    print('AutoHandy API Push Flow Test')
    print(f'  API_BASE={args.base}')
    print(f'  driver user_id={DRIVER_USER_ID}, master user_id={MASTER_USER_ID}, master_pk={args.master_id}')
    print(f'  pause={args.pause}s between steps')
    print('=' * 60)

    register_devices(args.base, driver, master, args.fcm_token)

    order_id = args.order_id

    if args.only in ('all', 'standard'):
        order_id = run_standard_lifecycle(
            base=args.base,
            driver=driver,
            master=master,
            master_pk=args.master_id,
            pause_sec=args.pause,
            skip_complete=args.skip_complete,
        )

    if args.only in ('all', 'chat'):
        run_chat_flow(driver, master, args.pause)

    meta = None
    if args.only in ('all', 'standard', 'sos', 'custom', 'cancel', 'expire'):
        meta = discover_payload(driver, args.master_id)

    if args.only in ('all', 'sos'):
        try:
            run_sos_lifecycle(
                driver, master, meta, args.pause, skip_complete=args.skip_complete,
            )
        except RuntimeError as exc:
            print(f'\n  SOS skipped: {exc}')
            print('  Master xizmat zonasi / emergency rate talablarini admin orqali tekshiring.')

    if args.only in ('all', 'custom'):
        run_custom_request_lifecycle(driver, master, args.master_id, meta, args.pause)

    if args.only in ('all', 'cancel'):
        run_cancel_push_test(driver, master, args.master_id, meta, args.pause)

    if args.only in ('all', 'expire'):
        run_offer_expire_push_test(driver, args.master_id, meta)

    if args.only in ('all', 'mvp-tasks') or args.only == 'mvp-tasks':
        oid = order_id or args.order_id
        if not oid:
            print('mvp-tasks: order_id kerak (--order-id yoki avval standard flow)')
        else:
            run_mvp_tasks(oid)

    print('\n' + '=' * 60)
    print('TUGADI. Telefonda pushlarni tekshiring.')
    print('Status push sarlavhalari: on_the_way="Master is on the way", in_progress="Work started"')
    print('Add service: "Additional services request" / approve: "Services approved"')
    print('Driver (user 2) va Master (user 3) ikkalasida ham token register qilindi.')
    print('=' * 60)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
