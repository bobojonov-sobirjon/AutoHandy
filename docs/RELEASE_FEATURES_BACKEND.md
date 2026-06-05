# AutoHandy — Yangi funksiyalar (Backend hujjati)

Bu hujjat oxirgi release da qo‘shilgan **barcha** backend funksiyalarini, API kontraktini va serverga **migrate** tartibini bir joyda to‘plab beradi.

| # | Funksiya |
|---|----------|
| 1 | Review, reyting va choycha (tips) — buyurtma tugagach |
| 2 | Master workshop: asbob va litsenziya tasdiqlash |
| 3 | Emergency Roadside for Semi Trucks (`is_truck`) |
| 4 | Buyurtma vaqtini master o‘zgartirish (client tasdiqlashi) |
| 5 | Email verification (OTP kod) |
| 6 | Towing — mil bo‘yicha narx |
| 7 | Fuel Delivery — yoqilg‘i turi + master idishlari |

---

## Umumiy API prefikslar

| Prefiks | App |
|---------|-----|
| `/api/auth/` | accounts |
| `/api/order/` | order |
| `/api/master/` | master |
| `/api/categories/` | categories |

---

# 1. Review, reyting va choycha (post-completion)

## Talab

Buyurtma **Completed** bo‘lgach client ko‘radi:
- review (sharh + teglar);
- reyting (1–5);
- choycha modal: *"Would you like to leave a tip for your provider?"*
  - `$5`, `$10`, `$20`, `Other Amount`, `No Thanks`.

## Modellar

**`Order`** (`apps/order/models.py`):

| Field | Tavsif |
|-------|--------|
| `tip_amount` | Choycha summasi |
| `tip_declined` | Client «No Thanks» bosgan |
| `tip_stripe_payment_intent_id` | Stripe PI |
| `tip_stripe_payment_status` | `not_applicable` / `pending` / `succeeded` / `failed` |
| `tip_paid_at` | To‘lov vaqti |

**`Review`** — `order` (OneToOne), `rating` 1–5, `comment`, `tags` (JSON, ≥1 tag).

**`ReviewTag`:** `fast_work`, `no_overpay`, `deadline`, `always_available`, `individual_approach`, `polite`, `late_or_delayed`, `poor_quality`, `overpriced`, `unprofessional`, `hard_to_reach`, `other_issue`

**Migratsiya:** `order/0050_order_tip_fields.py`

## API

### Review + reyting yaratish

```http
POST /api/order/reviews/create/
Authorization: Bearer <client_jwt>
```

**To‘liq review:**
```json
{
  "order_id": 123,
  "rating": 5,
  "tags": ["fast_work", "polite"],
  "comment": "Great service"
}
```

**Faqat choycha:**
```json
{
  "order_id": 123,
  "tip_only": true,
  "tip_amount": "10.00"
}
```

**Choychadan voz kechish:**
```json
{
  "order_id": 123,
  "tip_only": true,
  "decline_tip": true
}
```

### `post_completion` blok (order detail)

Completed buyurtmada client uchun:

```json
{
  "post_completion": {
    "needs_review": true,
    "needs_tip_prompt": true,
    "review_submitted": false,
    "tip_presets": [5, 10, 20],
    "tip_amount": "0.00",
    "tip_paid": false,
    "tip_declined": false,
    "tip_prompt_title": "Would you like to leave a tip for your provider?"
  }
}
```

## Validatsiya

- Faqat `status=completed` buyurtma
- Faqat buyurtma egasi (client)
- Bir buyurtmaga bir review
- Choycha: saqlangan karta + master Stripe Connect kerak
- `tip_presets` — `.env` dan (`TIP_PRESET_AMOUNTS`)

## Fayllar

- `apps/order/services/post_completion.py`
- `apps/payment/services/order_charge.py` (`charge_order_tip`)
- `apps/order/tests_post_completion.py`

## Env

| O‘zgaruvchi | Default |
|-------------|---------|
| `TIP_PRESET_AMOUNTS` | `5,10,20` |
| `STRIPE_CHARGE_CURRENCY` | `usd` |

---

# 2. Master workshop: asbob va litsenziya tasdiqlash

## Talab

Master profilida / Workshop da majburiy tasdiq:
- kerakli asboblar borligi;
- qonun talab qilsa — litsenziyalar borligi.

## Model

**`CustomUser`** (`apps/accounts/models.py`):

| Field | Tavsif |
|-------|--------|
| `has_tools_confirmed` | Asboblar tasdiqlangan |
| `has_licenses_confirmed` | Litsenziyalar tasdiqlangan |
| `workshop_compliance_confirmed_at` | Ikkalasi `true` bo‘lganda vaqt |

**Migratsiya:** `accounts/0022_customuser_workshop_compliance.py`

## API

```http
PUT /api/auth/user/workshop-compliance/
Authorization: Bearer <master_jwt>
```

```json
{
  "has_tools_confirmed": true,
  "has_licenses_confirmed": true
}
```

**200:**
```json
{
  "success": true,
  "message": "Workshop compliance confirmed",
  "user": {
    "has_tools_confirmed": true,
    "has_licenses_confirmed": true,
    "workshop_compliance_confirmed_at": "2026-06-03T12:00:00Z"
  }
}
```

**GET `/api/auth/user/`** — shu maydonlar read-only qaytadi.

## Validatsiya

- Ikkala maydon ham `true` bo‘lishi shart (`false` yuborib bo‘lmaydi)
- Partial update yo‘q — ikkalasi birga yuboriladi

## Fayllar

- `apps/accounts/serializers.py` — `UserWorkshopComplianceUpdateSerializer`
- `apps/accounts/views.py` — `UserWorkshopComplianceView`
- `apps/accounts/tests_workshop_compliance.py`

---

# 3. Emergency Roadside for Semi Trucks

## Talab

AQSh bo‘ylab yuk mashinalari (semi trucks) uchun alohida yo‘nalish.

**Xizmatlar:** Tire Service, Jump Start, Fuel Delivery, Lockout, Roadside Repair, Towing.

## Model

**`Category.is_truck`** — `boolean`, default `false`.

**Migratsiyalar:**
- `categories/0017_category_is_truck.py`
- `categories/0018_seed_truck_roadside_categories.py` — seed katalog

**Helper:** `apps/categories/services/truck_catalog.py`

## API

```http
GET /api/categories/categories/?type=by_order&is_truck=true
```

Truck asosiy kategoriyalar.

```http
GET /api/categories/subcategories/?parent_id=<TRUCK_MAIN_ID>
```

Subkategoriyalar (Fuel Delivery va boshqalar).

**Default ro‘yxat** (`is_truck` parametrsiz) — truck kategoriyalar **yashirin**.

**`CategorySerializer`:** `is_truck` maydoni qaytadi.

## Buyurtma

Truck xizmatlari uchun oddiy order oqimi:
- `POST /api/order/standard/`
- `POST /api/order/sos/`

`category_list` da truck katalogidan olingan ID lar ishlatiladi.

## Fayllar

- `apps/categories/views.py` — filtrlash
- `apps/categories/tests_truck_categories.py`

---

# 4. Buyurtma vaqtini master o‘zgartirish

## Talab

Master boshqa vaqt taklif qiladi → client tasdiqlaydi → `preferred_date/time` avtomatik yangilanadi.

## Model

**`OrderTimeChangeRequest`** (`apps/order/models.py`):

| Field | Tavsif |
|-------|--------|
| `order`, `master` | FK |
| `previous_preferred_*` | Eski jadval snapshot |
| `proposed_preferred_date/time_start/time_end` | Taklif |
| `master_comment` | Master izohi |
| `status` | `pending` / `approved` / `rejected` |
| `client_comment`, `decided_at` | Client qarori |

**Migratsiya:** `order/0051_order_time_change_request.py`

**Service:** `apps/order/services/order_time_change.py`

## API

| Method | Path | Kim |
|--------|------|-----|
| `POST` | `/api/order/<order_id>/time-change/requests/` | Master |
| `POST` | `/api/order/time-change/requests/<id>/approve/` | Client |
| `POST` | `/api/order/time-change/requests/<id>/reject/` | Client |
| `GET` | `/api/order/time-change/requests/pending/` | Client |

### Master taklif yaratish

```json
{
  "proposed_preferred_date": "2026-06-10",
  "proposed_preferred_time_start": "14:00:00",
  "proposed_preferred_time_end": "16:00:00",
  "comment": "Earlier slot available"
}
```

### Client approve

```json
{ "comment": "OK" }
```

**200:** `{ "request": {...}, "order": {...}, "message": "Order time updated" }`

### Client reject

```json
{ "comment": "Does not work for me" }
```

(`comment` reject da majburiy)

## Validatsiya

- `order_type`: `standard` yoki `custom_request`
- `status`: `accepted`, `on_the_way`, `arrived`
- Taklif kelajakdagi slot bo‘lishi kerak
- Bir buyurtmada bitta `pending` so‘rov
- Standard: `proposed_preferred_time_end` majburiy

## Bildirishnomalar

- Push: `time_change_request`, `time_change_approved`, `time_change_rejected`
- WebSocket: `time_change_request`, `time_change_decision`

## Fayllar

- `apps/order/tests_time_change.py`

---

# 5. Email verification (OTP)

## Talab

Email tasdiqlash majburiy (master va client). Ilova to‘liq ishlashi uchun email verify qilinishi kerak.

## Model

**`CustomUser.is_email_verified`**

**`EmailVerificationToken`:**
| Field | Tavsif |
|-------|--------|
| `code` | 4 xonali OTP |
| `email` | Snapshot |
| `expires_at` | Muddat |
| `is_used` | Ishlatilgan |

**Migratsiyalar:**
- `accounts/0012_...` — asosiy model
- `accounts/0023_emailverificationtoken_code.py` — OTP `code`
- `accounts/0024_...` — indeks tozalash

**Email yuborish:** `apps/accounts/email_verification.py`

## API

| Method | Path | Auth |
|--------|------|------|
| `POST` | `/api/auth/email-verification/` | JWT (unverified OK) |
| `POST` | `/api/auth/email-verification/resend/` | JWT |
| `POST` | `/api/auth/user/register-profile/` | JWT — email + kod yuborish |

### OTP tasdiqlash

```json
{ "code": "4821" }
```

**200:**
```json
{
  "success": true,
  "message": "Your email has been verified successfully.",
  "user": { "is_email_verified": true, "requires_email_verification": false }
}
```

### Kod qayta yuborish

```http
POST /api/auth/email-verification/resend/
```

## Middleware

`REQUIRE_EMAIL_VERIFICATION=true` bo‘lsa — verify qilmagan user ko‘p `/api/*` endpointlarga kira olmaydi.

**Istisnolar:** profile, register-profile, email confirm/resend, device, delete account.

## Fayllar

- `config/middleware/email_verification.py`
- `apps/accounts/permissions.py`
- `apps/accounts/tests_email_verification_code.py`
- `apps/accounts/tests_email_verification_required.py`

## Env

| O‘zgaruvchi | Default |
|-------------|---------|
| `REQUIRE_EMAIL_VERIFICATION` | `true` |
| `EMAIL_VERIFICATION_CODE_MINUTES` | `15` |
| `EMAIL_VERIFICATION_TOKEN_HOURS` | `48` |
| `EMAIL_VERIFICATION_PUBLIC_BASE` | `https://autohandy.app` |
| `EMAIL_DEBUG_IN_RESPONSE` | `false` (dev da `true` — kod API da qaytadi) |

---

# 6. Towing — mil bo‘yicha narx

## Talab

Master: base fee, min fee, price per mile.
Client: delivery manzil yoki mil soni → avtomatik narx.

**Formula:**
```
mileage_charge = miles × price_per_mile
calculated = base_fee + mileage_charge
total = max(calculated, minimum_fee)
```

**Misol:** Base $80 + 20 mil × $5 = **$180**.

## Modellar

**`MasterTowingPricing`** (OneToOne Master):
- `base_fee`, `price_per_mile`, `minimum_fee`, `is_active`

**`Order` towing snapshot:**
- `delivery_location/lat/lon`
- `towing_distance_miles`, `towing_base_fee`, `towing_price_per_mile`, `towing_minimum_fee`, `towing_total`
- `order_type = towing`

**Migratsiyalar:**
- `master/0033_master_towing_pricing.py`
- `order/0052_order_towing.py`
- `order/0053_towingorder_and_more.py`

## API

| Method | Path | Kim |
|--------|------|-----|
| `GET` | `/api/master/towing-pricing/` | Master |
| `PUT` | `/api/master/towing-pricing/` | Master |
| `POST` | `/api/order/towing/estimate/` | Client |
| `POST` | `/api/order/towing/` | Client |

### Master tariff

```json
{
  "base_fee": 80,
  "price_per_mile": 5,
  "minimum_fee": 100,
  "is_active": true
}
```

### Estimate

```json
{
  "latitude": "41.311100",
  "longitude": "69.279700",
  "delivery_latitude": "41.350000",
  "delivery_longitude": "69.300000"
}
```

yoki

```json
{
  "latitude": "41.311100",
  "longitude": "69.279700",
  "distance_miles": "20"
}
```

### Buyurtma yaratish

```json
{
  "master_id": 1,
  "car_list": [1],
  "text": "Need towing",
  "location": "Pickup",
  "latitude": "41.311100",
  "longitude": "69.279700",
  "delivery_location": "Destination",
  "delivery_latitude": "41.350000",
  "delivery_longitude": "69.300000",
  "distance_miles": "20"
}
```

**`master_id` majburiy** — client master tanlaydi (broadcast emas).

### Order javob `towing` bloki

```json
{
  "towing": {
    "pickup": { "location": "...", "latitude": "...", "longitude": "..." },
    "delivery": { "location": "...", "latitude": "...", "longitude": "..." },
    "distance_miles": "20.00",
    "base_fee": "80.00",
    "price_per_mile": "5.00",
    "minimum_fee": "100.00",
    "total_price": "180.00"
  }
}
```

## Push

Towing uchun maxsus copy («master» so‘zi, towing-specific title/body).

## Fayllar

- `apps/order/services/towing_pricing.py`
- `apps/order/services/towing_catalog.py`
- `apps/order/services/towing_notifications.py`
- `apps/order/tests_towing.py`

## Env

| O‘zgaruvchi | Default |
|-------------|---------|
| `TOWING_ESTIMATE_RADIUS_MILES` | `50` |

---

# 7. Fuel Delivery

## Talab

**Client:** alohida ekran — *"Delivery of 2 gallons of fuel"*, majburiy `gasoline` / `diesel`.

**Master:** ikkala idish tasdiqlanmagan bo‘lsa Fuel Delivery faol emas.

Batafsil: `docs/FUEL_DELIVERY_BACKEND.md`

## Modellar

| Model | Maydonlar | Migratsiya |
|-------|-----------|------------|
| `Order` | `fuel_delivery_type` | `order/0055` |
| `OrderService` | `fuel_type` | `order/0054` |
| `MasterServiceItems` | `has_gas_container_2gal`, `has_diesel_container_2gal` | `master/0034` |

## API (qisqa)

```http
POST /api/order/standard/   # fuel_type majburiy (Fuel Delivery bo‘lsa)
POST /api/master/service-items/   # ikkala container=true
```

## Fayllar

- `apps/categories/services/fuel_delivery_catalog.py`
- `apps/master/services/fuel_delivery.py`
- `apps/order/tests_fuel_delivery.py`

---

# Serverga deploy — BARCHA MIGRATSIYALAR

Production / staging da loyiha ildizidan:

```bash
python manage.py showmigrations
python manage.py migrate --noinput
```

## To‘liq migratsiya jadvali (shu release)

| App | Migratsiya | Funksiya |
|-----|------------|----------|
| **accounts** | `0022_customuser_workshop_compliance` | Workshop compliance |
| **accounts** | `0023_emailverificationtoken_code` | Email OTP `code` |
| **accounts** | `0024_remove_emailverificationtoken_accounts_em_user_co_91a2b1_idx` | Indeks |
| **categories** | `0017_category_is_truck` | `is_truck` maydoni |
| **categories** | `0018_seed_truck_roadside_categories` | Truck katalog seed |
| **categories** | `0015_category_is_towing_entry` | Towing entry flag |
| **categories** | `0016_seed_towing_entry_category` | Towing seed |
| **master** | `0033_master_towing_pricing` | Towing tariff |
| **master** | `0034_masterserviceitems_fuel_delivery_containers` | Fuel containers |
| **order** | `0050_order_tip_fields` | Tips |
| **order** | `0051_order_time_change_request` | Vaqt o‘zgartirish |
| **order** | `0052_order_towing` | Towing maydonlari |
| **order** | `0053_towingorder_and_more` | TowingOrder proxy |
| **order** | `0054_orderservice_fuel_type` | Fuel type (line) |
| **order** | `0055_order_fuel_delivery_type` | Fuel type (order) |

## App bo‘yicha alohida

```bash
python manage.py migrate accounts --noinput
python manage.py migrate categories --noinput
python manage.py migrate master --noinput
python manage.py migrate order --noinput
```

## Deploy checklist

```bash
git pull
pip install -r requirements.txt
python manage.py migrate --noinput
python manage.py showmigrations
```

### Testlar (ixtiyoriy)

```bash
python manage.py test apps.order.tests_post_completion -v 2
python manage.py test apps.accounts.tests_workshop_compliance -v 2
python manage.py test apps.categories.tests_truck_categories -v 2
python manage.py test apps.order.tests_time_change -v 2
python manage.py test apps.accounts.tests_email_verification_code -v 2
python manage.py test apps.order.tests_towing -v 2
python manage.py test apps.order.tests_fuel_delivery -v 2
```

### `.env` yangi / muhim kalitlar

```env
REQUIRE_EMAIL_VERIFICATION=true
EMAIL_VERIFICATION_CODE_MINUTES=15
EMAIL_DEBUG_IN_RESPONSE=false

TIP_PRESET_AMOUNTS=5,10,20

TOWING_ESTIMATE_RADIUS_MILES=50
```

### Restart

Migrate dan keyin application serverni qayta ishga tushiring (Gunicorn / Daphne / uWSGI).

---

## Bog‘liq hujjatlar

| Hujjat | Mazmun |
|--------|--------|
| `docs/RELEASE_FEATURES_FRONTEND.md` | Mobile integratsiya (barcha 7 funksiya) |
| `docs/FUEL_DELIVERY_BACKEND.md` | Fuel Delivery batafsil (backend) |
| `docs/FUEL_DELIVERY_FRONTEND.md` | Fuel Delivery batafsil (frontend) |
| `docs/STRIPE_DRIVER_AND_RIDER_INTEGRATION.md` | Choycha to‘lovi (Stripe) |

---

*Oxirgi yangilanish: 2026-06 release*
