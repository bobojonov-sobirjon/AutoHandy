# WebSocket: SOS offers for masters

Masters subscribe to incoming SOS order offers in real time.

## Connection

- **URL:** `ws://<host>/ws/sos/master/` or `wss://<host>/ws/sos/master/`
- **Auth:** JWT in query string: `?token=<access_jwt>`
- **Requirements:** user must be authenticated and must have a `Master` profile (`Master` row for that user). Otherwise the socket closes:
  - `4001` — not authenticated / invalid or expired token
  - `4003` — user is not a master

Channel layer (e.g. Redis) must be configured if HTTP API and WebSocket run in different processes.

## Messages from server → client

### 1. Connected (right after `accept`)

```json
{
  "type": "connected",
  "channel": "sos_incoming_orders"
}
```

### 2. SOS order offer (when an offer is pushed to this master)

```json
{
  "type": "sos_order_offer",
  "data": { /* payload — see below */ }
}
```

Payload `data` is built by `build_sos_order_websocket_payload()` (`apps/order/services/notifications.py`). Shape:

| Field | Type | Notes |
|--------|------|--------|
| `order_id` | int | |
| `status` | string | Order status code |
| `text` | string | Truncated to 4000 chars |
| `location` | string | |
| `latitude` | string or null | Decimal as string |
| `longitude` | string or null | Decimal as string |
| `location_source` | string or null | |
| `priority` | string/number | As stored on order |
| `order_type` | string | e.g. SOS |
| `discount` | string or null | |
| `parts_purchase_required` | bool | |
| `parts_purchase_required_json` | array | List of objects: `{ "vehicle_vin": "...", "part_name": "...", "is_address": true/false }` |
| `preferred_date` | string or null | ISO date |
| `preferred_time_start` | string or null | ISO time |
| `preferred_time_end` | string or null | ISO time |
| `created_at` | string or null | ISO datetime |
| `updated_at` | string or null | ISO datetime |
| `user` | object | `id`, `private_id`, `first_name`, `last_name`, `full_name`, `phone_number`, `email`, `avatar` (absolute URL when configured) |
| `car_data` | array | Cars linked to order |
| `category_data` | array | Order categories |
| `services` | array | Line items with `service_name`, `category_id`, price, etc. |
| `order_images` | array | `id`, `image` URL, `created_at` |
| `master_response_deadline` | string or null | ISO datetime — respond before this |
| `seconds` | int | UI countdown hint (`SOS_BROADCAST_RESPONSE_SECONDS` if broadcast queue else `SOS_OFFER_SECONDS_PER_MASTER`) |
| `sos_offer_index` | int | Position in rotation |
| `sos_queue_length` | int | Length of `sos_offer_queue` |
| `sos_broadcast` | bool | Whether queue-based broadcast is active |
| `offered_master_id` | int or null | Master id this push is for |

Example (illustrative only — values depend on DB):

```json
{
  "type": "sos_order_offer",
  "data": {
    "order_id": 42,
    "status": "pending_master",
    "text": "Flat tire",
    "location": "41.31, 69.28",
    "latitude": "41.311081",
    "longitude": "69.279737",
    "location_source": "gps",
    "priority": "high",
    "order_type": "sos",
    "discount": null,
    "parts_purchase_required": false,
    "parts_purchase_required_json": [],
    "preferred_date": null,
    "preferred_time_start": null,
    "preferred_time_end": null,
    "created_at": "2026-04-06T12:00:00+00:00",
    "updated_at": "2026-04-06T12:00:05+00:00",
    "user": {
      "id": 10,
      "private_id": "123456",
      "first_name": "Ali",
      "last_name": "Valiyev",
      "full_name": "Ali Valiyev",
      "phone_number": "998901234567",
      "email": null,
      "avatar": "https://api.example.com/media/avatars/x.jpg"
    },
    "car_data": [],
    "category_data": [],
    "services": [],
    "order_images": [],
    "master_response_deadline": "2026-04-06T12:02:00+00:00",
    "seconds": 30,
    "sos_offer_index": 0,
    "sos_queue_length": 3,
    "sos_broadcast": true,
    "offered_master_id": 5
  }
}
```

### 3. Pong (reply to client `ping`)

```json
{ "type": "pong" }
```

## Messages from client → server

Optional heartbeat:

```json
{ "type": "ping" }
```

Any other JSON is ignored unless you extend the consumer.

## Implementation reference

- Consumer: `apps/order/ws/consumers.py` — `MasterSosConsumer`
- Routing: `apps/order/ws/routing.py` — `^ws/sos/master/$`
- Push helper: `apps/order/services/notifications.py` — `push_sos_order_to_master_websocket`
- ASGI stack: `TokenAuthMiddleware` reads `?token=` — `config/middleware/tokenauth_middleware.py`

If `SOS_WEBSOCKET_STALE_SWEEP_SEC` > 0 in settings, the consumer periodically runs `expire_stale_master_offers` so the SOS ring can advance even when Celery countdown is unreliable (e.g. Windows).
