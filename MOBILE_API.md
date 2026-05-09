# AutoHandy Mobile API (DRF) — Frontend Documentation

This document describes the **Django + Django REST Framework** API surface used by the AutoHandy mobile apps (Driver + Master).

## General

- **Project**: AutoHandy
- **Framework**: Django + Django REST Framework (DRF)
- **Auth**: **JWT** (access + refresh are returned by `/api/auth/check-sms-code/`)
- **Content-Type**: `application/json` (unless endpoint explicitly uses multipart)
- **Base path**: all REST endpoints are under `/api/…`

### Base URL environments

Your backend is deployed per environment; set these in the mobile app config:

- **DEV**: `<DEV_BASE_URL>`
- **STAGING**: `<STAGING_BASE_URL>`
- **PROD**: `<PROD_BASE_URL>`

Examples below use paths only (e.g. `/api/order/...`) — prepend your base URL.

### Authentication (JWT)

After login verification you receive:
- `access` — short-lived JWT, send in `Authorization` header
- `refresh` — refresh JWT (storage: secure storage / keychain)

#### Authorization header

For all authenticated endpoints:

- `Authorization: Bearer <access>`

---

## JWT login flow (SMS / Email code)

> There is **no** “phone + password” login in this backend. Login is done via **verification code**.

### 1) Send verification code

- **METHOD**: `POST`
- **URL**: `/api/auth/login/`
- **Auth**: none
- **Body (JSON)**:
  - `identifier`: object (required)
    - `value`: string (required) — phone number or email
    - `type`: string (required) — one of: `phone`, `email`
  - `role`: string (required) — one of: `Driver`, `Master`, `Owner`

Example request:

```json
{
  "identifier": { "value": "11212121212", "type": "phone" },
  "role": "Driver"
}
```

Response (success):
- `success`: boolean
- `message`: string
- `identifier`: string
- `identifier_type`: string
- `user_exists`: boolean
- `sms_code`: string (debug only; may be hidden in production depending on settings)

### 2) Verify code and get JWT tokens

- **METHOD**: `POST`
- **URL**: `/api/auth/check-sms-code/`
- **Auth**: none
- **Body (JSON)**:
  - `identifier`: object (required)
    - `value`: string (required)
    - `type`: string (required) — `phone` or `email`
  - `sms_code`: string (required) — 4-digit code
  - `role`: string (required) — `Driver` / `Master` / `Owner`

Example request:

```json
{
  "identifier": { "value": "11212121212", "type": "phone" },
  "sms_code": "1234",
  "role": "Driver"
}
```

Response (success):

```json
{
  "success": true,
  "message": "OK",
  "user": { "id": 138, "phone_number": "11212121212" },
  "tokens": {
    "access": "jwt_access_token",
    "refresh": "jwt_refresh_token"
  }
}
```

---

## WebSockets (Realtime)

WebSockets use the same JWT `access` token.

### How to connect

All sockets accept token via query string:

- `ws(s)://<BASE_URL>/ws/.../?token=<JWT_ACCESS>`

Ping/pong:
- client → `{"type":"ping"}`
- server → `{"type":"pong"}`

### 1) SOS + Custom Request for Masters

- **URL**: `/ws/sos/master/`
- **Audience**: Master app
- **Incoming event types**:
  - `sos_order_offer` — SOS/emergency offer
  - `custom_request_job` — custom-request broadcast job

### 2) Custom Request offers for Drivers

- **URL**: `/ws/custom-request/rider/`
- **Audience**: Driver app
- **Incoming event types**:
  - `custom_request_offer`

### 3) Generic order events for Drivers (order owner)

- **URL**: `/ws/order/user/`
- **Audience**: Driver app
- **Incoming event types** (examples):
  - `extra_money_request` — pending “extra money” approval popup
  - `service_add_request` — pending “add service(s)” approval popup (NEW)
  - plus other order events depending on server logic

Payload is sent as:

```json
{
  "type": "<event_type>",
  "data": { }
}
```

### 4) Generic order events for Masters

- **URL**: `/ws/order/master/`
- **Audience**: Master app
- **Incoming event types** (examples):
  - `extra_money_decision`
  - `service_add_decision`

---

## Authentication / Profile / Devices

Base prefix: `/api/auth/`

### Health check
- **METHOD**: `GET` (also supports `POST`)
- **URL**: `/api/auth/health/` *(if enabled in views/urls; check Swagger if missing)*
- **Auth**: none

### SMS service status
- **METHOD**: `GET`
- **URL**: `/api/auth/sms-status/`
- **Auth**: none

### User details (me)
- **METHOD**: `GET`
- **URL**: `/api/auth/user/`
- **Auth**: Bearer JWT

### Update user location (me)
- **METHOD**: `PATCH`
- **URL**: `/api/auth/user/location/`
- **Auth**: Bearer JWT
- **Body (JSON)** (exact fields depend on serializer; common):
  - `latitude`: string/number (optional)
  - `longitude`: string/number (optional)
  - `address`: string (optional)

### Device token (FCM) — register/update “my device”
- **METHOD**: `POST` or `PATCH` (see Swagger)
- **URL**: `/api/auth/device/`
- **Auth**: Bearer JWT
- **Body (JSON)**:
  - `device_token`: string (required)
  - `device_type`: string (required) — e.g. `ios` / `android`

### Test push (debug)
- **METHOD**: `POST`
- **URL**: `/api/auth/device/test-push/`
- **Auth**: Bearer JWT

---

## Categories

Base prefix: `/api/categories/`

### List categories
- **METHOD**: `GET`
- **URL**: `/api/categories/categories/`
- **Auth**: optional (usually none)
- **Query params**: see Swagger (filtering may exist)

### List subcategories
- **METHOD**: `GET`
- **URL**: `/api/categories/subcategories/`

---

## Cars

Base prefix: `/api/car/`

### List cars / Create car
- **METHOD**: `GET` / `POST`
- **URL**: `/api/car/`
- **Auth**: Bearer JWT

### Car detail
- **METHOD**: `GET` / `PATCH` / `DELETE`
- **URL**: `/api/car/<id>/`
- **Auth**: Bearer JWT

### Car stats
- **METHOD**: `GET`
- **URL**: `/api/car/stats/`
- **Auth**: Bearer JWT

---

## Masters

Base prefix: `/api/master/`

### Create/Update master profile (me)
- **METHOD**: `GET` / `POST` / `PATCH` (depends on view implementation)
- **URL**: `/api/master/masters/`
- **Auth**: Bearer JWT

### Masters list
- **METHOD**: `GET`
- **URL**: `/api/master/masters/list/`

### Master details
- **METHOD**: `GET`
- **URL**: `/api/master/masters/<master_id>/`

### Add/update/delete service items (master’s services)
- **METHOD**: `POST`
- **URL**: `/api/master/service-items/`
- **METHOD**: `PATCH`
- **URL**: `/api/master/service-items/<item_id>/`
- **METHOD**: `POST`
- **URL**: `/api/master/service-items/<item_id>/delete/`

### Master images
- **POST** `/api/master/images/`
- **PATCH** `/api/master/images/<image_id>/`
- **POST** `/api/master/images/<image_id>/delete/`

### Master schedule
- **METHOD**: `GET` / `POST`
- **URL**: `/api/master/schedule/`
- **METHOD**: `GET` / `PATCH` / `DELETE`
- **URL**: `/api/master/schedule/<id>/`

### Busy slots
- **METHOD**: `GET` / `POST`
- **URL**: `/api/master/busy-slots/`
- **METHOD**: `GET` / `PATCH` / `DELETE`
- **URL**: `/api/master/busy-slots/<id>/`

---

## Orders

Base prefix: `/api/order/`

### Create STANDARD order
- **METHOD**: `POST`
- **URL**: `/api/order/standard/`
- **Auth**: Bearer JWT
- **Body (JSON)** (see `OrderCreateSerializer`):
  - `order_type`: string (required) — `standard` (legacy alias: `scheduled`)
  - `text`: string (required)
  - `location`: string (required)
  - `latitude`: string/number (required)
  - `longitude`: string/number (required)
  - `master_id`: int (required for standard)
  - `car_list`: int[] (required, non-empty)
  - `category_list`: int[] (required, non-empty)
  - `parts_purchase_required`: boolean (optional, default `false`)
  - `parts_purchase_required_json`: object[] (optional, default `[]`)
  - `preferred_date`: string `YYYY-MM-DD` (optional; must be sent together with `preferred_time_start`)
  - `preferred_time_start`: string `HH:MM(:SS)` (optional; must be sent together with `preferred_date`)

### Create SOS (Emergency) order
- **METHOD**: `POST`
- **URL**: `/api/order/sos/`
- **Auth**: Bearer JWT
- **Body**: same shape as standard, but:
  - `order_type`: `sos`
  - `master_id`: optional (if omitted, server builds queue)
  - `category_list`: must contain at least one `by_order` category

### Create Custom Request
- **METHOD**: `POST`
- **URL**: `/api/order/custom-request/`
- **Auth**: Bearer JWT
- **Body (JSON)**:
  - `text`: string (required)
  - `location`: string (required)
  - `latitude`: string/number (required)
  - `longitude`: string/number (required)
  - `average_price`: string/number (optional)
  - `average_service_name`: string (optional)
  - `preferred_date`: `YYYY-MM-DD` (optional; must be sent with `preferred_time_start`)
  - `preferred_time_start`: `HH:MM` (optional; must be sent with `preferred_date`)
  - `car_list`: int[] (optional, default `[]`)
  - `parts_purchase_required`: boolean (optional, default `false`)
  - `parts_purchase_required_json`: object[] (optional, default `[]`)

### Order detail
- **METHOD**: `GET`
- **URL**: `/api/order/<id>/`
- **Auth**: Bearer JWT

### Accept order (master)
- **METHOD**: `POST`
- **URL**: `/api/order/<order_id>/accept/`
- **Auth**: Bearer JWT (Master)

### Decline order (master)
- **METHOD**: `POST`
- **URL**: `/api/order/<order_id>/decline/`
- **Auth**: Bearer JWT (Master)

### Update status (in progress, etc.)
- **METHOD**: `PATCH`
- **URL**: `/api/order/<order_id>/status/`
- **Auth**: Bearer JWT
- **Body (JSON)**:
  - `status`: string (required) — one of server `OrderStatus` values

### Add extra money (immediate increment; assigned master only)
- **METHOD**: `PATCH`
- **URL**: `/api/order/<order_id>/extra-money/`
- **Auth**: Bearer JWT (Master)
- **Body (JSON)**:
  - `extra_money`: string/number (required) — amount to add (increment)

---

## Extra Money — Approval Flow (already existing)

### Create pending extra money request (master → client popup)
- **METHOD**: `POST`
- **URL**: `/api/order/<order_id>/extra-money/requests/`
- **Auth**: Bearer JWT (assigned Master)
- **Body (JSON)**:
  - `amount`: string/number (required, min `0.01`)
  - `comment`: string (optional)
- **Realtime**:
  - WS `/ws/order/user/` event type: `extra_money_request`

### Approve extra money request (client)
- **METHOD**: `POST`
- **URL**: `/api/order/extra-money/requests/<request_id>/approve/`
- **Auth**: Bearer JWT (order owner)
- **Body (JSON)**:
  - `comment`: string (optional)

### Reject extra money request (client)
- **METHOD**: `POST`
- **URL**: `/api/order/extra-money/requests/<request_id>/reject/`
- **Auth**: Bearer JWT (order owner)
- **Body (JSON)**:
  - `comment`: string (required)

### List pending extra money requests (client)
- **METHOD**: `GET`
- **URL**: `/api/order/extra-money/requests/pending/`
- **Auth**: Bearer JWT

---

## Add Services — Approval Flow (NEW, extra-money-like)

> This replaces the old behavior where services were added immediately and the client only received a notification.

### What happens now (high-level)

1) Master requests additional services → a **pending request** is created  
2) Client receives a **popup** via WS `/ws/order/user/` (`service_add_request`)  
3) Client approves or rejects  
4) Only on **Approve** the services are applied to the order (and pricing changes)

### A) Create service-add request (master → client popup)

- **METHOD**: `POST`
- **URL**: `/api/order/<order_id>/service-add/requests/`
- **Auth**: Bearer JWT (assigned Master)
- **Body (JSON)**:
  - `services_list`: int[] (required, non-empty) — `MasterServiceItems` IDs
    - duplicates are allowed and **increase count**
  - `comment`: string (optional) — message for client popup

Realtime:
- WS `/ws/order/user/` event type: `service_add_request`

### B) Approve service-add request (client)

- **METHOD**: `POST`
- **URL**: `/api/order/service-add/requests/<request_id>/approve/`
- **Auth**: Bearer JWT (order owner)
- **Body (JSON)**:
  - `comment`: string (optional)

Result:
- request becomes `approved`
- services are added to `order_services`
- client UI should refresh order details (`GET /api/order/<id>/`) to see updated pricing/services

### C) Reject service-add request (client)

- **METHOD**: `POST`
- **URL**: `/api/order/service-add/requests/<request_id>/reject/`
- **Auth**: Bearer JWT (order owner)
- **Body (JSON)**:
  - `comment`: string (required)

### D) List pending service-add requests (client)

- **METHOD**: `GET`
- **URL**: `/api/order/service-add/requests/pending/`
- **Auth**: Bearer JWT

### Backward compatibility: `/api/order/add-services/`

`POST /api/order/add-services/` still exists.

- If called by the **assigned master**, the backend will **NOT** apply services immediately.
  It will create a **pending service-add request** and send `service_add_request` to the client.
- If called by a non-master client (legacy), the backend may still apply immediately.

---

## Chat

Base prefix: `/api/chat/`

### Chat rooms list/create
- **METHOD**: `GET` / `POST`
- **URL**: `/api/chat/rooms/`
- **Auth**: Bearer JWT

### Chat room detail
- **METHOD**: `GET`
- **URL**: `/api/chat/rooms/<room_id>/`
- **Auth**: Bearer JWT

### Room messages
- **METHOD**: `GET` / `POST` (depends on view)
- **URL**: `/api/chat/rooms/<room_id>/messages/`
- **Auth**: Bearer JWT

### Mark as read
- **METHOD**: `POST`
- **URL**: `/api/chat/rooms/<room_id>/mark-read/`
- **Auth**: Bearer JWT

---

## Swagger / schema (for exact response shapes)

Use these endpoints for full schema:
- Swagger UI: `/docs/`
- OpenAPI schema: `/schema/`
- Redoc: `/redoc/`

