# To'liq API push test (`test_api_push_flow.py`)

Haqiqiy HTTP (`requests`) orqali **Driver (user 2)** va **Master (user 3)** JWT bilan order, chat, cancel, SOS, custom request va tizim (Celery) pushlarini tekshiradi.

## Tayyorgarlik

1. **Server:**
   ```powershell
   cd "D:\Projects\Mobile Backend APPS\AutoHandy"
   python manage.py runserver 8001
   ```

2. **Celery** (ixtiyoriy — faqat `mvp-tasks` / background timerlar uchun):
   ```powershell
   celery -A config worker -l info
   celery -A config beat -l info
   ```

3. **Tokenlar** skriptda default. O'zgartirish:
   ```powershell
   $env:API_BASE = "http://127.0.0.1:8001"
   $env:DRIVER_JWT = "..."
   $env:MASTER_JWT = "..."
   $env:FCM_TOKEN = "telefoningizdagi FCM token"
   $env:PAUSE_SEC = "5"
   $env:FCM_DEBUG = "1"
   ```

## Ishga tushirish

```powershell
cd "D:\Projects\Mobile Backend APPS\AutoHandy"

# Hammasi: standard + SOS + custom + chat + cancel + expire + MVP
python test/push/test_api_push_flow.py --pause 5

# Faqat standard (accept -> status -> extra money -> work photo)
python test/push/test_api_push_flow.py --only standard --pause 5

# Stripe/card yo'q bo'lsa
python test/push/test_api_push_flow.py --only standard --skip-complete

# SOS
python test/push/test_api_push_flow.py --only sos --pause 5

# Custom request (2 ta rasm multipart)
python test/push/test_api_push_flow.py --only custom --pause 5

# Chat
python test/push/test_api_push_flow.py --only chat

# Cancel push (alohida order)
python test/push/test_api_push_flow.py --only cancel

# Offer muddati tugashi (tizim push — Django ichida expire_stale_master_offers)
python test/push/test_api_push_flow.py --only expire

# MVP timer pushlar (SOS 4min, scheduled 1h va h.k.)
python test/push/test_api_push_flow.py --only mvp-tasks --order-id 92
```

## Qaysi pushlar tekshiriladi

| Qadam | API | Push |
|-------|-----|------|
| Device | `POST /api/auth/device/` | — |
| Test | `POST /api/auth/device/test-push/` | test |
| Standard create | `POST /api/order/standard/` | master: yangi buyurtma |
| Accept | `POST /api/order/{id}/accept/` | driver: **order_accepted** |
| Status | `POST /api/order/{id}/status/` | driver: **order_status_changed** |
| Extra money | `POST .../extra-money/requests/` + approve | driver/master |
| Service add | `POST /api/order/add-services/` + approve | driver/master |
| SOS | `POST /api/order/sos/` + accept + status | master + driver |
| Custom | `POST /api/order/custom-request/` + offer + add-master | **custom_request_offer** |
| Chat | `POST /api/chat/rooms/.../messages/` | **chat_message** |
| Cancel | `POST /api/order/{id}/cancel/` | **order_cancelled** |
| Expire | `expire_stale_master_offers()` | **offer_expired** |
| MVP | django `sos_mvp` / `scheduled_mvp` | timer pushlar |

## Telefon / FCM

- Testda **bitta FCM token** driver (2) va master (3) ga register qilinadi.
- Productionda har login: `POST /api/auth/device/` — **order egasi (driver)** uchun status pushlar.
- Chat data kalitlari: `chat_msg_id`, `chat_msg_type` (`message_id` / `message_type` emas).

## Complete

`complete` Stripe/saqlangan karta talab qiladi. Karta yo'q bo'lsa:
```powershell
python test/push/test_api_push_flow.py --skip-complete
```
PIN konsolda chiqadi (`client_completion_pin`).

## To'liq suite (chat + complete + barcha kind + Celery timeout)

```powershell
cd "D:\Projects\Mobile Backend APPS\AutoHandy"
$env:PAUSE_SEC = "8"
$env:FCM_DEBUG = "1"

# Hammasi (~50+ push, har biri 8 sek pauza — telefonni tekshiring)
python test/push/test_push_full_suite.py --pause 8

# Faqat chat (HTTP)
python test/push/test_push_full_suite.py --phase chat --pause 8

# Faqat complete + payment push (Stripe kerak emas)
python test/push/test_push_full_suite.py --phase complete --pause 8

# Faqat barcha push kindlar (40+)
python test/push/test_push_full_suite.py --phase kinds --pause 8

# Faqat Celery/timeout (offer expired, no-show, scheduled, penalty, SOS)
python test/push/test_push_full_suite.py --phase celery --pause 8

# Server yo'q — faqat kinds + complete
python test/push/test_push_full_suite.py --skip-api --phase kinds
```

`test_push_full_suite.py` ketma-ketligi:
1. FCM token register (user 2 + 3)
2. Chat HTTP (driver ↔ master)
3. Complete + payment push (to'g'ridan-to'g'ri)
4. Barcha `kind` lar (penalty, timeout, SOS, scheduled, …)
5. Celery haqiqiy kod: DB backdate + `expire_stale`, `warn_upcoming`, `auto_cancel`, …


```powershell
python test/push/test_push_all.py diagnose --user-id 2
python test/push/test_push_all.py lifecycle --user-id 2 --pause 3
python test/push/test_push_all.py chat --user-id 2 --peer-user-id 3
```
