# 2026-05-06 — Qilingan ishlar (Order/WS/Push)

Quyida bugun qo‘shilgan/yangilangan funksiyalar bo‘yicha qisqa va aniq texnik hujjat.

## 1) Accept qilingandan keyin 30 daqiqada “On the way” bo‘lmasa (no-departure watchdog)

### Muammo
Master orderni `accepted` qilib qo‘yib, uzoq vaqt `on_the_way` bosmasa ham tizim:
- ogohlantirmasdi
- orderni bekor qilmasdi
- boshqa masterlarga qayta yubormasdi

Sabab: avvalgi auto-cancel logika faqat `ON_THE_WAY` holatidan keyin ishlardi (`arrival_deadline_at` va `auto_cancel_master_no_show_task`).

### Yechim (yangi logika)
Order `accepted` bo‘lgandan keyin \(default 30 daqiqa\) ichida master `ON_THE_WAY` bosmasa, tizim order type’ga qarab action qiladi.

#### Konfiguratsiya
`config/settings.py`
- `MASTER_NO_DEPARTURE_MINUTES` (default: `30`)

#### Schedule
`apps/order/api/views.py`
- `AcceptOrderView` ichida accept bo‘lganda:
  - `schedule_master_no_departure_action(order_id, accepted_at)` chaqiriladi

`apps/order/services/celery_schedule.py`
- `schedule_master_no_departure_action(order_id, accepted_at)`
  - Celery ETA task: `master_no_departure_action_task(order_id)` ni `accepted_at + MASTER_NO_DEPARTURE_MINUTES` ga schedule qiladi.

#### Task
`apps/order/tasks.py`
- `master_no_departure_action_task(order_id)`
  - `handle_accepted_no_departure_for_order(order_id=..., now=...)` chaqiradi.

#### Core handler + fallback sweep
`apps/order/services/offer_expiry.py`
- `sweep_accepted_no_departure(now, order_id=None)`
  - **SOS**: masterdan yechadi → `pending` → `sos_offer_queue` yangidan quradi → SOS broadcast qayta yuboradi
  - **CUSTOM_REQUEST**: masterdan yechadi → `pending` → radiusdagi masterlarga custom-request broadcast qayta yuboradi
  - **STANDARD**: masterdan yechadi → `cancelled` (`auto_cancel_reason="master_no_departure"`)
  - Push xabarlar: user va old masterga best-effort yuboriladi

Shuningdek, Celery ETA ishlamay qolsa ham “safety net” bo‘lsin deb:
- `expire_stale_master_offers()` oxirida `sweep_accepted_no_departure()` ham chaqiriladi.

### Outcome
- Master accept qilib “harakatlanmasa”, order “osilib” qolmaydi.
- SOS/custom_request bo‘lsa qayta broadcast bo‘ladi.
- Standard bo‘lsa auto-cancel bo‘ladi (client o‘zi boshqa master tanlaydi).

---

## 2) Extra money: master qo‘shadi, client approve/reject qiladi (silent increase yo‘q)

### Muammo
Avval `PATCH /api/order/<order_id>/extra-money/` orderga darrov qo‘shib yuborardi.
Clientda popup/notify bo‘lmasdi — umumiy summa “jim” oshib qolardi.

### Yechim (approval flow)
Endi master extra money ni **request** qiladi (pending), client **approve/reject** qiladi.

#### Model + tarix
`apps/order/models.py`
- `OrderExtraMoneyRequest`
  - `amount`
  - `master_comment`
  - `status`: `pending|approved|rejected`
  - `client_comment` (reject bo‘lsa majburiy)
  - `decided_at`, `created_at`, `updated_at`

Migratsiya:
- `apps/order/migrations/0040_order_extra_money_request.py`

#### API
1) **Master → create request (pending)**
- `POST /api/order/<order_id>/extra-money/requests/`
- Body:

```json
{ "amount": "10.00", "comment": "Reason..." }
```

- Natija: `OrderExtraMoneyRequestSerializer` payload (status=`pending`)
- Side effects:
  - Clientga **WS event** + **push**

2) **Client → approve**
- `POST /api/order/extra-money/requests/<request_id>/approve/`
- Body (optional):

```json
{ "comment": "ok" }
```

- Natija: request status=`approved`
- Side effects:
  - `order.extra_money += amount`
  - Masterga **WS event** + **push**

3) **Client → reject (comment majburiy)**
- `POST /api/order/extra-money/requests/<request_id>/reject/`
- Body:

```json
{ "comment": "Why rejected..." }
```

- Natija: request status=`rejected`
- Side effects:
  - Order o‘zgarmaydi
  - Masterga **WS event** + **push**

4) **Client offline fallback (faqat pending)**
- `GET /api/order/extra-money/requests/pending/`
- Natija: faqat `pending` requestlar ro‘yxati (approve/reject bo‘lganlar chiqmaydi)

#### WS (Extra money uchun qaysi websocket)
Bu eventlar chat WS emas, **order events WS** orqali keladi.

Routing:
- `apps/order/ws/routing.py`

Client:
- **Path**: `ws://<host>/ws/order/user/?token=<JWT>`
- Event:
  - `type: "extra_money_request"`

Master:
- **Path**: `ws://<host>/ws/order/master/?token=<JWT>`
- Event:
  - `type: "extra_money_decision"`

#### Extra money WS response shape (updated)
`OrderExtraMoneyRequestSerializer` endi `master` va `order` qisqa bloklarini ham beradi:
- `master.full_name` (kamida nom ko‘rinsin)
- `order`: `{id, order_number, order_type, status}`

Misol:

```json
{
  "type": "extra_money_request",
  "data": {
    "id": 1,
    "order_id": 65,
    "master_id": 3,
    "master_user_id": 3,
    "master": { "id": 3, "user_id": 3, "full_name": "...", "avatar": "..." },
    "order": { "id": 65, "order_number": "ORD_1234", "order_type": "sos", "status": "accepted" },
    "amount": "100.00",
    "master_comment": "....",
    "status": "pending",
    "client_comment": "",
    "decided_at": null,
    "created_at": "...",
    "updated_at": "..."
  }
}
```

---

## 3) Emergency (SOS) order yaratishdan oldin taxminiy narx (estimate)

### Muammo
SOS order yaratishdan oldin client (va master UI) taxminiy narxni ko‘rmasdi.
Narx faqat order yaratilgandan keyin order_services/pricing qurilganda chiqardi.

### Yechim: estimate endpoint
Yangi API endpoint “nearby masters” priced services asosida min/avg/max taxminiy narx qaytaradi va SOS koeffitsient \(1.3/1.6\) ni qo‘llaydi.

#### API
- `POST /api/order/emergency/estimate-price/`

Body:

```json
{
  "latitude": 41.3111,
  "longitude": 69.2797,
  "address": "optional",
  "category_list": [12, 13],
  "radius_miles": 10
}
```

Logic:
- radius ichidagi masterlarni topadi
- masterda tanlangan barcha `category_list` bo‘yicha `MasterServiceItems.price` bor masterlarni “matched” qiladi
- har master uchun subtotal = sum(prices)
- min/avg/max chiqaradi
- vaqt bo‘yicha SOS koeffitsient (day/night) qo‘llab emergency min/avg/max qaytaradi

Response fields (asosiylari):
- `master_count`, `matched_master_count`
- `base_min/base_avg/base_max`
- `coefficient`, `time_bucket`, `time_zone`
- `emergency_min/emergency_avg/emergency_max`

---

## Qo‘shimcha: Push debugging uchun test endpoint

Push backenddan yuborilayaptimi yoki telefon/channel muammosimi degan joyda aniq tekshirish uchun debug endpoint qo‘shildi:

- `POST /api/auth/device/test-push/`
- Body:

```json
{ "firebase_kind": "master", "title": "Test push", "body": "Hello" }
```

Bu endpoint `request.user` device token’iga test FCM yuboradi (logs: `send_attempt/send_result`).

