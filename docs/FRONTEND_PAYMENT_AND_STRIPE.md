# AutoHandy — Payment & Stripe API (Mobile Frontend)

**Project:** AutoHandy  
**Stack:** Django 5 + Django REST Framework (DRF)  
**Auth:** JWT (`Authorization: Bearer <access>`)  
**Default JSON:** `Content-Type: application/json`

**Base URLs (configure per environment):**

| Environment | Example base URL |
|-------------|------------------|
| Local dev   | `http://127.0.0.1:8001` |
| Staging     | *(your server)* |
| Production  | http://217.114.11.249:7002/docs |

All paths below are **relative to the base URL** (e.g. `POST {BASE}/api/auth/login/`).

---

## 1. Authentication (JWT) — required for payment APIs

The app uses **SMS / email code** login, not password login for mobile.

### 1.1 Send verification code

| Field | Value |
|-------|--------|
| **METHOD** | `POST` |
| **URL** | `/api/auth/login/` |
| **Auth** | None (`AllowAny`) |
| **Content-Type** | `application/json` |

**Body (JSON)**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `identifier` | string | **Yes** | Email **or** phone (same string user typed). |
| `role` | string | **Yes** | One of: `Driver`, `Master`, `Owner`. |

**Example**

```json
{
  "identifier": "+998901234567",
  "role": "Driver"
}
```

**Success response (200)** — shape varies; typical fields:

| Field | Type | Description |
|-------|------|-------------|
| `success` | boolean | `true` |
| `message` | string | Human-readable |
| `identifier` | string | Normalized identifier |
| `identifier_type` | string | `phone` or `email` |
| `user_exists` | boolean | Whether user already existed |
| `sms_code` | string | **May appear in dev** when SMS fails or debug flags are on — do not rely on it in production |

**Errors:** `400` — `success: false`, `errors: { ... }`

---

### 1.2 Verify code and receive JWT

| Field | Value |
|-------|--------|
| **METHOD** | `POST` |
| **URL** | `/api/auth/check-sms-code/` |
| **Auth** | None |
| **Content-Type** | `application/json` |

**Body (JSON)**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `identifier` | string | **Yes** | **Same** value as in `/login/` (email or phone). |
| `sms_code` | string | **Yes** | Exactly **4** digits. |
| `role` | string | **Yes** | Same as login: `Driver`, `Master`, or `Owner`. |

**Example**

```json
{
  "identifier": "+998901234567",
  "sms_code": "1234",
  "role": "Driver"
}
```

**Success response (200)**

```json
{
  "success": true,
  "message": "…",
  "user": { },
  "user_created": false,
  "tokens": {
    "access": "<JWT access token>",
    "refresh": "<JWT refresh token>"
  }
}
```

| Field | Type | Description |
|-------|------|-------------|
| `tokens.access` | string | **Short-lived JWT** — send on every authenticated request. |
| `tokens.refresh` | string | Long-lived refresh — store securely; **no dedicated refresh HTTP route is registered in this repo** unless you add SimpleJWT URLs; use your backend policy or add `/api/auth/token/refresh/` if configured later. |
| `user` | object | Full user profile payload. |

**Authenticated requests**

```http
Authorization: Bearer <tokens.access>
Content-Type: application/json
```

---

### 1.3 Swagger-only OAuth token (optional, not for production app login)

| Field | Value |
|-------|--------|
| **METHOD** | `POST` |
| **URL** | `/api/auth/oauth/token/` |
| **Content-Type** | `application/x-www-form-urlencoded` or form |

Used for Swagger UI convenience; mobile apps should use **§1.1–1.2**.

---

## 2. Product overview — who pays what

| Role | Stripe product | Responsibility |
|------|----------------|----------------|
| **Driver** (order owner, `role: Driver`) | **Stripe Customer** (`cus_…`) | Save cards, attach card to order; **charged on order complete** (off-session PaymentIntent). |
| **Master** | **Stripe Connect Express** (`acct_…`) | Onboarding + bank payout; receives **destination transfer** from the customer charge (minus platform application fee). |

**Card charge timing:** when the **assigned master** calls `POST /api/order/{id}/complete/` with the correct **4-digit client PIN**, the backend creates/confirms a **PaymentIntent** using the order’s saved card and (if the master has Connect) `transfer_data.destination`.

---

## 3. Driver (client) — Stripe Customer & saved cards

**Requirement:** user must be in group **Driver** (not Master) for saved-card APIs. Masters get **403** with an error message pointing to Connect APIs.

### 3.1 Ensure Stripe Customer (bootstrap)

| Field | Value |
|-------|--------|
| **METHOD** | `GET` |
| **URL** | `/api/auth/stripe-customer/` |
| **Auth** | `Bearer` (any authenticated user; used by clients before collecting cards) |

**Body:** none.

**Success (200)**

```json
{
  "status": "success",
  "data": {
    "stripe_customer_id": "cus_…",
    "created": true,
    "stripe_publishable_key": "pk_test_…"
  }
}
```

| Field | Type | Description |
|-------|------|-------------|
| `data.stripe_customer_id` | string | Attach PaymentMethods to this customer in Stripe.js. |
| `data.created` | boolean | `true` if customer was just created. |
| `data.stripe_publishable_key` | string | Use with **Stripe.js** / PaymentSheet on device. |

**Errors:** `503` — Stripe not configured or server error (`status`, `message`).

**Mobile flow:** call once (or cache), then create `payment_method` on-device with Stripe SDK, then **§3.3**.

---

### 3.2 List saved cards

| Field | Value |
|-------|--------|
| **METHOD** | `GET` |
| **URL** | `/api/payment/saved-cards/` |
| **Auth** | `Bearer` (**Driver** only) |

**Response (200)** — JSON array of cards:

| Field | Type | Description |
|-------|------|-------------|
| `id` | integer | Internal DB id — use as `card_id` for order attach. |
| `holder_role` | string | e.g. `client` |
| `brand` | string | e.g. `visa` |
| `last4` | string | Last 4 digits |
| `exp_month` | integer | |
| `exp_year` | integer | |
| `funding` | string | e.g. `credit` |
| `is_default` | boolean | |
| `created_at` | string (ISO-8601) | |

**403** — user is **Master** (wrong role for this API).

---

### 3.3 Add saved card

| Field | Value |
|-------|--------|
| **METHOD** | `POST` |
| **URL** | `/api/payment/saved-cards/` |
| **Auth** | `Bearer` (**Driver** only) |

**Body (JSON)**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `payment_method_id` | string | **Yes** | Stripe `pm_…` from Stripe.js / mobile SDK (max 64 chars). |
| `stripe_customer_id` | string | No | Optional; normally inferred server-side after **§3.1**. |

**Success (201)** — single card object (same shape as list item).

**400** — `{ "error": "<message>" }` (e.g. Stripe error).

---

### 3.4 Set default card

| Field | Value |
|-------|--------|
| **METHOD** | `PUT` |
| **URL** | `/api/payment/saved-cards/{pk}/` |
| **Auth** | `Bearer` (**Driver** only) |

**Path**

| Param | Type | Required |
|-------|------|----------|
| `pk` | integer | **Yes** — saved card `id`. |

**Body (JSON)**

| Field | Type | Required |
|-------|------|----------|
| `is_default` | boolean | **Yes** — must be `true` (only supported operation). |

**200** — updated card object.  
**404** — `{ "error": "Card not found" }`

---

### 3.5 Delete saved card

| Field | Value |
|-------|--------|
| **METHOD** | `DELETE` |
| **URL** | `/api/payment/saved-cards/{pk}/` |
| **Auth** | `Bearer` (**Driver** only) |

**204** — no body.

---

### 3.6 Attach card to order (required before complete)

| Field | Value |
|-------|--------|
| **METHOD** | `PATCH` |
| **URL** | `/api/order/{order_id}/payment-card/` |
| **Auth** | `Bearer` (**order owner** = driver) |

**Path**

| Param | Type | Required |
|-------|------|----------|
| `order_id` | integer | **Yes** |

**Body (JSON)**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `card_id` | integer | **Yes** | From **§3.2** list item `id`. |

**Example**

```json
{ "card_id": 1 }
```

**200** — full `OrderSerializer` payload (includes `saved_card`, `payment_type`, etc.).

**Errors**

| HTTP | Body |
|------|------|
| `400` | `Invalid order_id`, `card_id is required`, `Cannot change payment on finished orders` |
| `403` | Not order owner |
| `404` | Order not found, or card not found / not a client card |

> **Important:** Listing cards on the driver profile is **not** enough — the order row must have `saved_card` set via this endpoint.

---

### 3.7 Checkout preview (driver or assigned master)

| Field | Value |
|-------|--------|
| **METHOD** | `GET` |
| **URL** | `/api/order/{order_id}/checkout-preview/` |
| **Auth** | `Bearer` |

**Allowed:** order owner **or** assigned master.

**200**

```json
{
  "checkout": {
    "technician_total": "10.00",
    "penalty_total": "0.00",
    "is_emergency": false,
    "dispatch_fee": "0.00",
    "service_fee": "0.40",
    "platform_fee_line": "0.40",
    "customer_total": "10.80",
    "master_estimated_payout": "9.00",
    "platform_estimated_gross": "1.80",
    "provider_platform_fee_percent": "10",
    "_customer_total_decimal": "10.80",
    "_master_payout_decimal": "9.00",
    "_technician_total_decimal": "10.00",
    "_penalty_decimal": "0.00"
  }
}
```

*(Decimal strings are examples; values depend on order lines, fees in `settings`, SOS vs scheduled.)*

**Note:** Keys starting with `_` are for server-side charge math; **mobile UI should ignore them** or hide them if you pass the object through as-is.

---

### 3.8 Order detail — pricing & marketplace fee display

| Field | Value |
|-------|--------|
| **METHOD** | `GET` (also `PUT`/`PATCH` where allowed) |
| **URL** | `/api/order/{id}/` |
| **Auth** | `Bearer` |

Nested object **`pricing`** includes:

| Field | Type | Description |
|-------|------|-------------|
| `discount`, `subtotal`, `work_total`, `penalty_total`, `total`, … | strings / numbers | Line pricing from services. |
| `emergency_pricing` | object | SOS: `coefficient`, `base_subtotal`, `final_subtotal`, `time_bucket`, etc. |
| **`marketplace_fees`** | object | **TZ-style breakdown** for UI: `pricing_mode` (`scheduled_standard` \| `scheduled_custom_request` \| `emergency`), `master` (base, estimated payout, platform % text), `client` (technician price, fees, penalty, total), `percentages`, `notes`. |

**Driver-only sensitive fields on order:** `stripe_payment_intent_id`, `stripe_payment_status`, `stripe_payment_amount_cents`, `stripe_payment_currency` are returned **only** when the authenticated user is the **order owner** (`order.user_id == request.user.id`). Masters may see other order fields but not those payment fields on the nested serializer (privacy).

---

## 4. Master — Stripe Connect & payouts

### 4.1 Connect onboarding — status

| Field | Value |
|-------|--------|
| **METHOD** | `GET` |
| **URL** | `/api/master/stripe-connect/onboarding/` |
| **Auth** | `Bearer` + user must be **Master** group |

**200 (no account yet)**

```json
{
  "stripe_connect_account_id": null,
  "account": null,
  "onboarding_complete": false,
  "stripe_publishable_key": "pk_…"
}
```

**200 (account exists)** — includes `account` summary from Stripe, `onboarding_complete` (heuristic: `details_submitted && payouts_enabled`), and publishable key.

---

### 4.2 Connect onboarding — start / resume (Stripe-hosted URL) — **disabled in URLs**

> Routes commented out in `apps/master/api/urls.py`. Use **§4.3 bank-account** instead. Uncomment only if Stripe requests extra KYC via hosted flow.

### 4.2 (legacy) Connect onboarding — start / resume (Stripe-hosted URL)

| Field | Value |
|-------|--------|
| **METHOD** | `POST` |
| **URL** | `/api/master/stripe-connect/onboarding/` |
| **Auth** | `Bearer` + **Master** |

**Body (JSON)** — both required **unless** Django settings define defaults:

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `return_url` | string (URL) | **Yes*** | HTTPS in production; `http://` only for `localhost` / `127.0.0.1`. |
| `refresh_url` | string (URL) | **Yes*** | Same rules. |

\*If `STRIPE_CONNECT_ONBOARDING_RETURN_URL` and `STRIPE_CONNECT_ONBOARDING_REFRESH_URL` are set in server env, body fields may be omitted.

**Success (200)**

```json
{
  "status": "success",
  "data": {
    "stripe_connect_account_id": "acct_…",
    "connect_account_created": false,
    "onboarding_url": "https://connect.stripe.com/…",
    "stripe_publishable_key": "pk_…"
  }
}
```

Open **`onboarding_url`** in in-app browser / Chrome Custom Tab / SFSafariViewController until Stripe finishes.

**503** — Stripe secret key not configured.  
**400** — validation / Stripe Connect errors.

---

### 4.3 Direct deposit — bank account in-app (Instacart-style) **recommended**

| Field | Value |
|-------|--------|
| **METHOD** | `GET` / `POST` / `DELETE` |
| **URL** | `/api/master/stripe-connect/bank-account/` |
| **Auth** | `Bearer` + **Master** |

Master enters **routing number** + **account number** in the app. Backend creates Connect Express `acct_…` if needed and attaches the bank in Stripe. Full numbers are **not** stored in Django DB.

**GET — Payments / Direct deposit screen**

```json
{
  "stripe_connect_account_id": "acct_…",
  "stripe_publishable_key": "pk_…",
  "connected_account_agreement_url": "https://stripe.com/legal/connect-account",
  "onboarding_complete": true,
  "account": { "charges_enabled": true, "payouts_enabled": true, "details_submitted": true },
  "bank_account": {
    "id": "ba_…",
    "bank_name": "BANK OF AMERICA, N.A.",
    "last4": "4141",
    "display_label": "BANK OF AMERICA, N.A. •••• 4141",
    "status": "verified",
    "default_for_currency": true
  },
  "bank_accounts": [ "…" ],
  "weekly_direct_deposit": {
    "enabled": true,
    "bank_account": { "…" },
    "fee_note": "No fee",
    "schedule_note": "…"
  },
  "requirements": null
}
```

If Stripe still needs identity/tax later, `requirements.needs_additional_setup` may be `true` — show a short “Complete setup” step (optional hosted link fallback).

**POST — Save bank (Edit bank account screen)**

| Field | Type | Required |
|-------|------|----------|
| `routing_number` | string | **Yes** — 9 digits (US) |
| `account_number` | string | **Yes** — 4–17 digits |
| `account_holder_name` | string | No — defaults to user full name |
| `account_holder_type` | string | No — `individual` (default) or `company` |

```json
{
  "routing_number": "110000000",
  "account_number": "000123456789",
  "account_holder_name": "Jane Doe"
}
```

**200** — `status: success`, full payout profile (same shape as GET) including `bank_account.display_label`.

Show under the form: link to `connected_account_agreement_url` (“Stripe Connected Account Agreement”).

**DELETE — Remove bank**

| Field | Type | Required |
|-------|------|----------|
| `bank_account_id` | string | No — if omitted, removes default bank (`ba_…`) |

**Mobile flow (master only):**

1. `GET /api/master/stripe-connect/bank-account/` → show `weekly_direct_deposit` or empty state.  
2. User taps Edit → form routing + account → `POST` → show `display_label`.  
3. Optional Remove → `DELETE`.  
4. Do **not** open `onboarding_url` unless `requirements.needs_additional_setup` is true.

`GET /api/master/stripe-connect/onboarding/` now includes the same `bank_account` / `weekly_direct_deposit` fields when `acct_…` exists.

---

### 4.4 Link / unlink Connect account manually — **disabled in URLs**

> Commented out. `POST bank-account` creates `acct_…` automatically.

### 4.4 (legacy) Link / unlink Connect account manually (optional)

| Field | Value |
|-------|--------|
| **METHOD** | `GET` / `POST` / `DELETE` |
| **URL** | `/api/master/stripe-connect/` |
| **Auth** | `Bearer` + **Master** |

**GET** — current link status (`linked`, `stripe_connect_account_id`, `account`).

**POST body (JSON)**

| Field | Type | Required |
|-------|------|----------|
| `stripe_connect_account_id` | string | **Yes** — must start with `acct_` (6–64 chars). |

**DELETE** — clears `acct` from master profile.

**409** — that `acct_` already linked to another master.

---

### 4.5 Connect balance & recent payouts

| Field | Value |
|-------|--------|
| **METHOD** | `GET` |
| **URL** | `/api/master/stripe-balance/` |
| **Auth** | `Bearer` + **Master** |

Requires `stripe_connect_account_id` on the master profile.

**200** — includes `available`, `pending`, `recent_payouts`, `payout_schedule_note`, etc. (read-only from Stripe).

**400** — Connect not linked.

---

### 4.6 Checkout history (completed orders + Stripe ledger)

| Field | Value |
|-------|--------|
| **METHOD** | `GET` |
| **URL** | `/api/master/checkout-history/` |
| **Auth** | `Bearer` + **Master** |

**Query (optional)**

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `page` | integer | `1` | Page number. |
| `page_size` | integer | `20` | 1–100. |
| `stripe_tx_limit` | integer | `30` | BalanceTransaction rows 1–100. |
| `stripe_starting_after` | string | — | Stripe pagination cursor `txn_…`. |

**200** — `orders` (paginated completed orders with Stripe payment fields) + `stripe_balance_transactions`.

---

## 5. Order complete (charge) — master only

| Field | Value |
|-------|--------|
| **METHOD** | `POST` |
| **URL** | `/api/order/{order_id}/complete/` |
| **Auth** | `Bearer` (**assigned master** only) |

**Prerequisites**

- Order `status` = `in_progress`
- At least one work completion image uploaded
- Driver set **`payment-card`** (**§3.6**)
- Master’s Connect account must be able to receive **transfers** if destination charges are used (otherwise 400 with a clear error)

**Body (JSON)**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `completion_pin` | string | **Yes** | Exactly **4** digits; client sees `client_completion_pin` on their order API while `in_progress`. |

**Example**

```json
{ "completion_pin": "6925" }
```

**200** — `{ "message": "…", "order": { … } }` — order includes updated `stripe_payment_*` for the owner when they fetch the order.

**400** — e.g. wrong PIN, missing photos, Stripe charge error, Connect not ready, no saved card on order.

---

## 6. Fee configuration (server-side)

Mobile apps **must not** hardcode fee percentages for production truth — use **`pricing.marketplace_fees`** and **`checkout`** from API. Backend defaults (env-overridable) include:

- `PROVIDER_PLATFORM_FEE_PERCENT` — master payout deduction
- Scheduled: `CUSTOMER_SERVICE_FEE_PERCENT_SCHEDULED`, `CUSTOMER_PLATFORM_FEE_PERCENT_SCHEDULED`
- Emergency (SOS): `EMERGENCY_DISPATCH_FEE_PERCENT`, `CUSTOMER_SERVICE_FEE_PERCENT_EMERGENCY`, day/night multipliers `EMERGENCY_DAY_MULTIPLIER` / `EMERGENCY_NIGHT_MULTIPLIER`

Charge currency: `STRIPE_CHARGE_CURRENCY` (e.g. `usd`).

---

## 7. Error shape (common)

Many endpoints return:

```json
{ "error": "Human readable message" }
```

or DRF validation:

```json
{ "detail": "Forbidden" }
```

or field errors:

```json
{ "errors": { "field": ["…"] } }
```

---

## 8. Quick checklist — driver app

1. `POST /api/auth/login/` → `POST /api/auth/check-sms-code/` → store `tokens.access` (and `refresh`).
2. `GET /api/auth/stripe-customer/` → get `cus_…` + `pk_…`.
3. Collect card with Stripe SDK → `POST /api/payment/saved-cards/` with `payment_method_id`.
4. After creating an order: `PATCH /api/order/{id}/payment-card/` with `card_id`.
5. Optionally `GET /api/order/{id}/checkout-preview/` and `GET /api/order/{id}/` for `pricing.marketplace_fees`.
6. Master completes job → client sees completion; master calls `POST /api/order/{id}/complete/` (payment runs server-side).

---

## 9. Quick checklist — master app

1. Same login as driver but `role: "Master"`.
2. `GET /api/master/stripe-connect/bank-account/` — Direct deposit screen.
3. `POST /api/master/stripe-connect/bank-account/` — routing + account (in-app Save).
4. Link `connected_account_agreement_url` under the form.
5. If `requirements.needs_additional_setup` → contact support or re-enable legacy onboarding URL in backend (commented in urls).
6. `GET /api/master/stripe-balance/` and `GET /api/master/checkout-history/` for earnings UI.
7. Complete orders only when Connect is **ready** (transfers active) or charges may fail.

---

## 10. OpenAPI / Swagger

Interactive docs (if enabled on server):

- **Swagger UI:** `GET /docs/`
- **OpenAPI schema:** `GET /schema/`

Use **Authorize** with `Bearer <access>` after obtaining a token.

---

*Generated from the AutoHandy Django codebase. If routes or serializers change, prefer `/schema/` as the source of truth.*
