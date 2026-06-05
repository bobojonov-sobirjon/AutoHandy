# AutoHandy — `.env` to‘liq qo‘llanma

Barcha muhim environment o‘zgaruvchilar.  
**Eslatma:** `.env` ni git ga commit qilmang. Production da haqiqiy kalitlardan foydalaning.

---

## Sizning `.env` ga QO‘SHISH kerak (yangi funksiyalar)

Hozirgi faylingizda **yo‘q**, lekin yangi release uchun **kerak**:

```env
# --- Email OTP verification ---
REQUIRE_EMAIL_VERIFICATION=true
EMAIL_VERIFICATION_CODE_MINUTES=15
EMAIL_VERIFICATION_PUBLIC_BASE=https://autohandy.app
EMAIL_VERIFICATION_TOKEN_HOURS=48
# Faqat local dev (production da false!)
EMAIL_DEBUG_IN_RESPONSE=false

# --- Towing estimate radius (miles) ---
TOWING_ESTIMATE_RADIUS_MILES=50
```

**Choycha (tips)** — sizda allaqachon bor:
```env
TIP_PRESET_AMOUNTS=5,10,20
```
Stripe kalitlari ham bor — lekin `STRIPE_WEBHOOK_SECRET` ni haqiqiy `whsec_...` bilan almashtiring.

---

## To‘liq `.env` shablon

Quyidagi blokni nusxa oling va qiymatlarni to‘ldiring.

```env
# =============================================================================
# ASOSIY / DJANGO
# =============================================================================
DJANGO_DEBUG=false
# DEBUG=true   # faqat local

# =============================================================================
# DATABASE (PostgreSQL)
# =============================================================================
DB_NAME=autohandy
DB_USER=postgres
DB_PASSWORD=your_db_password
DB_HOST=localhost
DB_PORT=5432

# =============================================================================
# API / MEDIA
# =============================================================================
API_PUBLIC_BASE_URL=https://api.yourdomain.com
MEDIA_ROOT=/var/www/media

# =============================================================================
# REDIS / CELERY / WebSocket
# =============================================================================
REDIS_URL=redis://127.0.0.1:6379/0
CHANNEL_LAYER_REDIS=redis://127.0.0.1:6379/0
CELERY_BROKER_URL=redis://127.0.0.1:6379/0
CELERY_RESULT_BACKEND=redis://127.0.0.1:6379/0
CELERY_TASK_ALWAYS_EAGER=false

# =============================================================================
# EMAIL VERIFICATION (OTP) — yangi
# =============================================================================
REQUIRE_EMAIL_VERIFICATION=true
EMAIL_VERIFICATION_CODE_MINUTES=15
EMAIL_VERIFICATION_PUBLIC_BASE=https://autohandy.app
EMAIL_VERIFICATION_TOKEN_HOURS=48
EMAIL_DEBUG_IN_RESPONSE=false

# =============================================================================
# SMS (Twilio)
# =============================================================================
TWILIO_ACCOUNT_SID=ACxxxxxxxx
TWILIO_AUTH_TOKEN=xxxxxxxx
TWILIO_PHONE_NUMBER=+1xxxxxxxxxx
DEFAULT_PHONE_COUNTRY_CODE=+1
SMS_DEBUG_IN_RESPONSE=false

# App Store / Play review test login
STORE_REVIEW_PHONES=+15555550100
STORE_REVIEW_OTP=4242

# =============================================================================
# STRIPE — to‘lov, choycha, master payout
# =============================================================================
STRIPE_SECRET_KEY=sk_live_xxx
STRIPE_PUBLISHABLE_KEY=pk_live_xxx
STRIPE_WEBHOOK_SECRET=whsec_xxx
STRIPE_CHARGE_CURRENCY=usd

STRIPE_CONNECT_ACCOUNT_TYPE=custom
STRIPE_CONNECT_ACCOUNT_DEFAULT_COUNTRY=US
STRIPE_PLATFORM_BUSINESS_URL=https://autohandy.app
STRIPE_PLATFORM_MCC=7538
STRIPE_PLATFORM_STATEMENT_DESCRIPTOR=AUTOHANDY
STRIPE_PLATFORM_PRODUCT_DESCRIPTION=On-demand automotive services

STRIPE_CONNECT_ONBOARDING_RETURN_URL=https://autohandy.app/stripe/return
STRIPE_CONNECT_ONBOARDING_REFRESH_URL=https://autohandy.app/stripe/refresh

STRIPE_IDENTITY_REQUIRE_ID_NUMBER=true
STRIPE_IDENTITY_REQUIRE_MATCHING_SELFIE=true
STRIPE_IDENTITY_REQUIRE_LIVE_CAPTURE=true
STRIPE_IDENTITY_ENFORCE_BEFORE_PAYOUT=true

STRIPE_CONNECT_PAYOUT_INTERVAL=weekly
STRIPE_CONNECT_PAYOUT_WEEKLY_ANCHOR=monday
STRIPE_CONNECT_PAYOUT_REMINDER_ENABLED=true
STRIPE_CONNECT_PAYOUT_REMINDER_HOUR=9
STRIPE_CONNECT_PAYOUT_REMINDER_MINUTE=0

# Komissiyalar (%)
PROVIDER_PLATFORM_FEE_PERCENT=10
CUSTOMER_SERVICE_FEE_PERCENT_SCHEDULED=4
CUSTOMER_PLATFORM_FEE_PERCENT_SCHEDULED=4
EMERGENCY_DISPATCH_FEE_PERCENT=6
CUSTOMER_SERVICE_FEE_PERCENT_EMERGENCY=5

# =============================================================================
# TIPS (choycha) — yangi
# =============================================================================
TIP_PRESET_AMOUNTS=5,10,20

# =============================================================================
# TOWING — yangi
# =============================================================================
TOWING_ESTIMATE_RADIUS_MILES=50

# =============================================================================
# FUEL DELIVERY, TRUCK, WORKSHOP COMPLIANCE, TIME CHANGE
# =============================================================================
# Alohida .env kalitlari yo‘q — faqat migrate + API

# =============================================================================
# BUYURTMA TAYMERLARI / TIMEZONE
# =============================================================================
SCHEDULED_ORDER_TIMEZONE=America/Los_Angeles
EMERGENCY_TIME_ZONE=America/Los_Angeles

MASTER_OFFER_RESPONSE_MINUTES=15
MASTER_NO_DEPARTURE_MINUTES=30
SOS_NO_DEPARTURE_WARNING_MINUTES=4
SOS_NO_DEPARTURE_ACTION_MINUTES=5
SOS_ON_THE_WAY_REMINDER_MINUTES=10
SCHEDULED_REMINDER_BEFORE_START_MINUTES=60
SCHEDULED_NO_START_WARNING_MINUTES=20
SCHEDULED_NO_START_CANCEL_MINUTES=30

EMERGENCY_DAY_MULTIPLIER=1.3
EMERGENCY_NIGHT_MULTIPLIER=1.6
EMERGENCY_ACCEPTANCE_RATE_MIN=90
EMERGENCY_COMPLETION_RATE_MIN=90

CUSTOM_REQUEST_BROADCAST_RADIUS_MILES=10

# =============================================================================
# CLIENT CANCEL PENALTY
# =============================================================================
CLIENT_CANCEL_GRACE_MINUTES_AFTER_ACCEPT=10
CLIENT_CANCEL_PENALTY_PERCENT_ACCEPTED_LATE=10
CLIENT_CANCEL_PENALTY_PERCENT_ON_THE_WAY=15
CLIENT_CANCEL_NO_PENALTY_AFTER_ON_THE_WAY_HOURS=2
CLIENT_CANCEL_PENALTY_PERCENT_ARRIVED=25
CLIENT_CANCEL_PENALTY_CHARGE_ENABLED=true

# =============================================================================
# CHAT
# =============================================================================
CHAT_CLOSE_HOURS_AFTER_ORDER_COMPLETE=2
CHAT_WS_MAX_UPLOAD_BYTES=5242880

# =============================================================================
# PUSH (Firebase FCM — Master app)
# =============================================================================
FIREBASE_MASTER_TYPE=service_account
FIREBASE_MASTER_PROJECT_ID=your-project-id
FIREBASE_MASTER_PRIVATE_KEY_ID=xxx
FIREBASE_MASTER_PRIVATE_KEY="-----BEGIN PRIVATE KEY-----\n...\n-----END PRIVATE KEY-----\n"
FIREBASE_MASTER_CLIENT_EMAIL=firebase-adminsdk@your-project.iam.gserviceaccount.com
FIREBASE_MASTER_CLIENT_ID=xxx
FIREBASE_MASTER_AUTH_URI=https://accounts.google.com/o/oauth2/auth
FIREBASE_MASTER_TOKEN_URI=https://oauth2.googleapis.com/token
FIREBASE_MASTER_AUTH_PROVIDER_X509_CERT_URL=https://www.googleapis.com/oauth2/v1/certs
FIREBASE_MASTER_CLIENT_X509_CERT_URL=https://www.googleapis.com/robot/v1/metadata/x509/...
FIREBASE_MASTER_UNIVERSE_DOMAIN=googleapis.com
FCM_DEBUG=0
PUSH_ANDROID_CHANNEL_ID=high_importance_channel

# =============================================================================
# TELEGRAM BOT (ixtiyoriy)
# =============================================================================
BOT_TOKEN=xxx
BOT_NAME=your_bot_name
```

---

## Funksiya bo‘yicha qaysi `.env` kerak

| Funksiya | Kerakli `.env` |
|----------|----------------|
| **Email OTP** | `REQUIRE_EMAIL_VERIFICATION`, `EMAIL_VERIFICATION_CODE_MINUTES`, SMTP (`settings.py` da hozir hardcode) |
| **Tips / choycha** | `STRIPE_*`, `TIP_PRESET_AMOUNTS`, `STRIPE_CHARGE_CURRENCY` |
| **Towing** | `TOWING_ESTIMATE_RADIUS_MILES`, `STRIPE_*` (to‘lov uchun) |
| **Fuel Delivery** | `.env` yo‘q |
| **Semi Trucks** | `.env` yo‘q |
| **Workshop compliance** | `.env` yo‘q |
| **Time change** | `.env` yo‘q |
| **Review** | `.env` yo‘q (Stripe tips uchun Stripe kerak) |
| **Push** | `FIREBASE_MASTER_*` |
| **SMS login** | `TWILIO_*` |
| **Celery timers** | `CELERY_BROKER_URL`, `REDIS_URL` |

---

## Email SMTP

Hozir `config/settings.py` da SMTP **to‘g‘ridan-to‘g‘ri** yozilgan (`EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`).  
OTP email yuborish uchun SMTP ishlashi shart. Production da Gmail App Password yoki SendGrid/SES ishlating.

---

## Local development tavsiyalar

```env
DJANGO_DEBUG=true
EMAIL_DEBUG_IN_RESPONSE=true
SMS_DEBUG_IN_RESPONSE=true
CELERY_TASK_ALWAYS_EAGER=true

# Stripe test kalitlari
STRIPE_SECRET_KEY=sk_test_xxx
STRIPE_PUBLISHABLE_KEY=pk_test_xxx
```

---

## Production checklist

- [ ] `DJANGO_DEBUG=false`
- [ ] `EMAIL_DEBUG_IN_RESPONSE=false`
- [ ] `REQUIRE_EMAIL_VERIFICATION=true`
- [ ] Haqiqiy `STRIPE_WEBHOOK_SECRET`
- [ ] `API_PUBLIC_BASE_URL` — production domain
- [ ] Redis + Celery worker ishlayapti
- [ ] `python manage.py migrate --noinput`

---

*Bog‘liq: `docs/RELEASE_FEATURES_BACKEND.md`*
