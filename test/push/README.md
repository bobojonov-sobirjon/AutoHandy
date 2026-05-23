# Push notification testlari (AutoHandy)

Bu papka **barcha FCM push**larni tekshirish uchun. Asosiy muammo ko‘pincha shunda:

1. **Token boshqa Firebase loyihasidan** (masalan, rider app `autohandy-rider`, backend esa `.env` dagi `FIREBASE_MASTER_PROJECT_ID=autohandymaster`).
2. **Token DB da yo‘q** — `notify_user_order_event` faqat `UserDevice` jadvalidagi tokenlarga yuboradi (`order.user_id` uchun).
3. **Firebase Console “history”** ko‘pincha bo‘sh ko‘rinadi — bu normal; muhim jihat — telefonda push kelishi va skriptdagi `success=1`.

## Tayyorgarlik

```powershell
cd "D:\Projects\Mobile Backend APPS\AutoHandy"
# .env allaqachon loyiha ildizida bo‘lishi kerak (FIREBASE_MASTER_*)
$env:FCM_DEBUG = "1"
```

## 1) Diagnostika (birinchi ish)

```powershell
python test/push/test_push_all.py diagnose --token "SIZNING_FCM_TOKEN"
# yoki
python test/push/test_push_all.py --token "SIZNING_FCM_TOKEN" diagnose
```

Ko‘rsatadi: Firebase `project_id`, token uzunligi, to‘g‘ridan-to‘g‘ri FCM natijasi (`success` / `failure` + xato matni).

## 2) To‘g‘ridan-to‘g‘ri token (DB siz)

```powershell
python test/push/test_push_all.py direct --token "SIZNING_FCM_TOKEN" --title "Test 1" --body "Direct FCM"
```

Agar **failure** bo‘lsa — token yoki Firebase loyiha noto‘g‘ri (app va backend bir xil `google-services.json` / iOS plist loyihasi kerak).

## 3) Tokenni user ga bog‘lash (production yo‘li)

**`user_id=42` ishlamaydi** — bazada bunday user yo‘q bo‘lsa `ForeignKeyViolation` chiqadi.

Avval mavjud userlarni ko‘ring:

```powershell
python test/push/test_push_all.py list-users
```

Keyin order yaratgan rider ning **haqiqiy** `id` sini ishlating (hozirgi DB da masalan `3`, `7`):

```powershell
python test/push/test_push_all.py register --user-id 3 --token "SIZNING_FCM_TOKEN" --device-type android
# yoki: --email strange0518unk@gmail.com
```

Keyin backend `notify_user_order_event` shu user uchun ishlaydi.

## 4) Barcha push `kind` lar (ketma-ket)

```powershell
python test/push/test_push_all.py all-kinds --user-id 3 --master-user-id 7 --order-id 1001 --delay 3
```

Har `kind` uchun alohida push keladi (taxminan 40+ ta). Telefonda ketma-ket tekshiring.

## 5) Order lifecycle (status o‘zgarishlari — sizning muammo)

```powershell
python test/push/test_push_all.py lifecycle --user-id 3 --order-id 1001 --delay 3
```

Yuboriladi: `order_accepted`, `order_status_changed` (on_the_way, arrived, in_progress, completed), va boshqalar.

**Eslatma:** Haqiqiy API orqali status o‘zgartirsangiz ham push **faqat** `order.user_id` uchun `UserDevice` da token bo‘lsa keladi.

## 6) MVP timer pushlari (rasmdagilar)

```powershell
python test/push/test_push_all.py mvp --user-id 3 --master-user-id 7 --order-id 1001 --delay 3
```

`SOS`: `sos_departure_warning`, `sos_communication_reminder`, `sos_rebroadcast`, …  
`Scheduled`: `scheduled_start_reminder`, `scheduled_no_start_warning`, `auto_cancel_scheduled_no_start`, …

## 7) Chat push

```powershell
# User chat xonalarini ko'rish
python test/push/test_push_all.py chat-rooms --user-id 3

# Push oluvchi user da token bo'lishi kerak (register)
python test/push/test_push_all.py chat --recipient-user-id 3 --room-id 5 --message-id 1 --text "Salom test"
```

REST `POST /api/chat/rooms/{id}/messages/` va WebSocket chat ikkalasi ham `notify_chat_message` ishlatadi.

## 8) Haqiqiy API orqali (ixtiyoriy)

Server ishlab turishi kerak (`python manage.py runserver`). Tokenni avval `register` qiling, keyin:

```powershell
$env:API_BASE = "http://127.0.0.1:8001"
$env:RIDER_JWT = "eyJ..."      # order yaratgan user
$env:MASTER_JWT = "eyJ..."     # master
$env:ORDER_ID = "1001"
python test/push/test_push_all.py api-lifecycle
```

Bu skript ketma-ket chaqiradi: device register → test-push → status PATCH (on_the_way → arrived → in_progress).

## Qaysi API da push bor?

| Bosqich | API / joy | Kim oladi | `kind` |
|--------|-----------|-----------|--------|
| Order yaratish (standard) | `POST /api/order/standard/` | Master (tanlangan) | `order_selected` |
| Order yaratish (SOS) | `POST /api/order/sos/` | Masters (navbat) | `order_new` |
| Custom request | `POST /api/order/custom-request/` | Radiusdagi masterlar | `custom_request_new` |
| Accept | `POST /api/order/{id}/accept/` | Rider (user) | `order_accepted` |
| Decline | `POST /api/order/{id}/decline/` | Rider | `order_declined` |
| Status | `PATCH /api/order/{id}/status/` | Rider | `order_status_changed` |
| Cancel | `POST /api/order/{id}/cancel/` | Ikkala tomonga | `order_cancelled` |
| Complete | `POST /api/order/{id}/complete/` | Rider | `order_completed`, `order_payment_charged` |
| Penalty | cancel + charge | Rider | `cancellation_penalty_charged` |
| Service add | add-request API | Rider / Master | `service_add_*` |
| Extra money | extra-money API | Rider / Master | `extra_money_*` |
| Chat REST | `POST /api/chat/rooms/{id}/messages/` | Qarshi tomonga | `chat_message` |
| Chat WS | WebSocket xabar | Qarshi tomonga | `chat_message` |
| Celery/Beat | timer tasks | user/master | `sos_departure_warning`, `scheduled_*`, … |

## Debug endpoint (allaqachon bor)

`POST /api/auth/device/test-push/` (JWT bilan) — faqat **joriy user** ning `UserDevice` tokeniga yuboradi.

## Agar `success=1` lekin telefonda yo‘q

- Ilova **boshqa Firebase project** dan token olganmi tekshiring (`autohandymaster` bilan mosligi).
- Android: notification channel `high_importance_channel` (`.env` `PUSH_ANDROID_CHANNEL_ID`).
- Ilova background cheklovlari / battery saver.
- iOS: APNs + FCM sozlamalari Firebase Console da.

## Default token

Skriptda default token siz yuborgan token; o‘zgartirish: `--token "..."` yoki `$env:TEST_FCM_TOKEN`.
