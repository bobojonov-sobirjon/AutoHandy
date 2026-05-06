# Manga: Chat (REST + WebSocket) logikasi

Bu hujjat loyihadagi chat qanday **ochilishi**, **qanday yuborilishi**, va message ichida **sender_type** qanday ajratilishi (bor/yo‘qligi) haqida.

## 1) Chat “ID” nima? (order details ichida qaysi ID chiqadi)

Bu loyihada chatning asosiy entitisi — `ChatRoom`.

- Order modelda chat alohida `chat_id` sifatida saqlanmaydi.
- `apps/order/models.py` ichida order chatga `chat_room` FK bilan bog‘langan:
  - `Order.chat_room` → `chat.ChatRoom`
- `order details` API (`OrderDetailView` → `OrderSerializer`) javobida chat uchun quyidagi field bor:
  - **`chat_room_id`**

Demak **order details ichida chiqadigan “chat id” shu `chat_room_id`** (ya’ni `ChatRoom.id`) hisoblanadi.

WS URL ham aynan shu ID bilan ishlaydi:

- `ws://<host>/ws/chat/<room_id>/?token=<JWT>`
- bu yerda `room_id` = `ChatRoom.id` = `OrderSerializer.chat_room_id`

> Muhim: “chat id” va “chat room id” alohida bo‘lishi kerak degan konsept bu codebase’da yo‘q — chatning o‘zi `ChatRoom`.

## 2) Chat qachon “ochiladi” (room qachon yaratiladi)

Chat room 2 xil yo‘l bilan paydo bo‘ladi:

### A) User o‘zi chat ochadi (manual create)

REST:
- `POST /api/chat/rooms/` body: `{ "participant_id": <other_user_id> }`
- Agar oldindan shu 2 user o‘rtasida room bo‘lsa — o‘sha mavjud room qaytadi, bo‘lmasa yangisi yaratiladi.

Kod: `apps/chat/views.py` → `ChatRoomListCreateView.post()`.

### B) Order accept bo‘lganda avtomatik chat ochiladi

Orderni master “accept” qilgandan keyin (order accepted flow) backend:
- `order.chat_room_id` yo‘q bo‘lsa
- va `order.master_id` mavjud bo‘lsa
→ master (initiator) va customer (receiver) o‘rtasida `ChatRoom` yaratadi yoki topadi.

Kod:
- `apps/order/api/views.py` (accept flow atrofida) `get_or_create_order_chat_room(...)`
- servis: `apps/chat/services.py` → `get_or_create_order_chat_room(master_user, customer_user)`

Natija:
- `Order.chat_room` set qilinadi
- `OrderSerializer` javobida `chat_room_id` paydo bo‘ladi

## 3) WebSocket autentifikatsiya

WS authentication query string orqali JWT bilan:

- `?token=<JWT>`

Middleware:
- `config/middleware/tokenauth_middleware.py` → `TokenAuthMiddleware`
- `config/asgi.py` websocket router: `TokenAuthMiddleware(URLRouter(...))`

Chat WS routing:
- `apps/chat/routing.py`:
  - `ws/chat/<room_id>/` → `ChatConsumer`

## 4) Message qanday yuboriladi

Loyihada 2 yo‘l bor (mobilga qulay bo‘lishi uchun):

### A) WebSocket orqali yuborish (real-time, DBga ham yoziladi)

WS frame JSON’da `type` bilan keladi.

1) Text:

```json
{ "type": "chat_message", "message_type": "text", "text": "Salom" }
```

2) Attachment’ni WS base64 bilan yuborish:
- image: `image_base64` + `image_name`
- file: `file_base64` + `file_name`
- audio: `audio_base64` + `audio_name`

3) Ko‘p rasm (gallery/batch):

```json
{
  "type": "chat_message",
  "message_type": "image",
  "text": "caption (optional)",
  "images": [
    { "name": "1.jpg", "base64": "<BASE64>" },
    { "name": "2.jpg", "base64": "<BASE64>" }
  ]
}
```

Backend bu holatda DBga **bir nechta `ChatMessage`** yaratadi, lekin WS’ga **bitta “gallery” object** qilib broadcast qiladi (`images: [...]`).

Kod: `apps/chat/consumers.py` → `ChatConsumer.receive()` + `save_message()`.

### B) REST orqali upload, keyin WS orqali “broadcast”

Attachment’lar uchun (file size limit yoki multipart qulay bo‘lsa):

1) REST bilan `multipart/form-data` upload:
- `POST /api/chat/rooms/<room_id>/messages/`

2) REST response’dan `message_id` olasiz.

3) WS orqali shu `message_id` ni broadcast qilasiz:

```json
{ "type": "chat_message", "message_id": 555 }
```

Bu yo‘lning ma’nosi:
- binary REST’da saqlanadi
- realtime event WS’da tarqatiladi

Kod:
- REST: `apps/chat/views.py` → `ChatMessagesView.post()`
- WS: `apps/chat/consumers.py` → `get_message_if_allowed(message_id)`

## 5) Messages olish (history) va sender_type masalasi

### REST orqali messages olishda sender_type bormi?

Ha, REST history chiqishda **`sender_type` bor**.

Endpoint:
- `GET /api/chat/rooms/<room_id>/messages/`

Payloadni backend `build_chat_messages_api_payload(...)` orqali quradi.

Kod: `apps/chat/serializers.py`
- `_chat_message_api_dict(...)` ichida **`sender_type`** hisoblanadi:
  - `initiator` agar `msg.sender_id == request.user.id`
  - aks holda `receiver`

Demak REST’da `sender_type` **current userga nisbatan** ajratiladi (siz uchun kim yubordi — “men”mi / “u”mi).

### WebSocket eventlarda sender_type bormi?

Ha, WS message payloadida ham `sender_type` field bor, lekin **hozirgi implementatsiyada u real ajratilmaydi**:

Kod: `apps/chat/consumers.py` → `message_to_dict(...)`
- `sender_type` **doim `'initiator'` qilib hardcode qilingan** (`Mobile clients expect this field; keep it stable for now.` deb yozilgan).

Shuning uchun:
- WS’dan kelgan message’larda `sender_type` **bor**, lekin **doim bir xil** chiqadi.
- REST’dan kelgan history’da esa `sender_type` **to‘g‘ri ajratiladi** (men/receiver).

## 6) Realtime eventlar (WS outgoing)

WS broadcast turlari:
- `type: "chat_message"` + `message: { ... }`
- `type: "chat_message_batch"` + `messages: [...]` (gallery)
- `type: "typing"`
- `type: "read_receipt"`

Kod: `apps/chat/consumers.py`:
- `chat_message()`
- `chat_message_batch()`
- `typing_indicator()`
- `read_receipt()`

## 7) Qisqa “end-to-end” flow (mobil uchun)

### Order’dan chatga kirish:
- `GET /api/order/<id>/` (order details)
- javobdan `chat_room_id` oling
- chat screen WS connect:
  - `ws://<host>/ws/chat/<chat_room_id>/?token=<JWT>`

### History:
- `GET /api/chat/rooms/<chat_room_id>/messages/`
- shu yerda `sender_type` bor (to‘g‘ri ajratilgan)

### Send:
- oddiy text → WS bilan yuborish
- attachment:
  - WS base64 bilan yuborish **yoki**
  - REST upload → WS `{message_id}` bilan broadcast

---

## Qo‘shimcha: Extra money approval (order pricing o‘zgarishi)

### Maqsad
Usta qo‘shimcha mablag‘ qo‘shganda mijozga “tasdiqlash / rad etish” chiqishi kerak.
Backend endi **order.extra_money** ni darrov oshirmaydi — avval **request** yaratiladi, keyin client approve/reject qiladi.

### WebSocket kanallar

- Client (order owner):
  - Connect: `ws://<host>/ws/order/user/?token=<JWT>`
  - Event:
    - `type: "extra_money_request"` → `data`: extra money request payload
- Master:
  - Connect: `ws://<host>/ws/order/master/?token=<JWT>`
  - Event:
    - `type: "extra_money_decision"` → `data`: request payload (status=approved/rejected)

### API oqimi

1) Master request yaratadi (pending):
- `POST /api/order/<order_id>/extra-money/requests/`
- body: `{ "amount": "10.00", "comment": "..." }`
- clientga push + WS: `extra_money_request`

2) Client tasdiqlaydi:
- `POST /api/order/extra-money/requests/<request_id>/approve/`
- (optional) body: `{ "comment": "ok" }`
- natija: request status=approved, **order.extra_money += amount**
- masterga push + WS: `extra_money_decision`

3) Client rad etadi:
- `POST /api/order/extra-money/requests/<request_id>/reject/`
- body: `{ "comment": "Nega rad etdim..." }` (**majburiy**)
- natija: request status=rejected, **order.extra_money o‘zgarmaydi**
- masterga push + WS: `extra_money_decision`

4) Offline fallback (faqat pending ko‘rsatish):
- `GET /api/order/extra-money/requests/pending/`
- client uchun barcha pending requestlar ro‘yxati qaytadi.

