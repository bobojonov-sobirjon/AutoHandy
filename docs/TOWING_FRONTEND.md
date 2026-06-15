# Towing — Frontend integration guide

Guide for **Master (Workshop)** and **Driver** apps after the towing pricing refactor.

**Base URL:** `https://api.autohandy.app`  
**Last updated:** 2026-06-15

---

## What the client wanted (product logic)

The client expected **four separate towing services**, not one service with automatic distance switching:

| Workshop section | Backend `service_type` |
|------------------|------------------------|
| Local towing | `local` |
| Long distance towing | `long_distance` |
| Accident recovery | `accident_recovery` |
| Motorcycle towing | `motorcycle` |

For **each** section the master sets:

- **Base fee** — flat charge for that job type  
- **Per mile** — price per mile  
- **Minimum fee** — floor price for that job type (see below)

The **driver chooses the service type** when ordering. The server does **not** auto-pick local vs long distance by mileage anymore.

> **Removed:** `local_max_miles`, auto `trip_type` by distance, single combined towing tariff.

---

## Minimum fee — what to show in UI

**Purpose:** even on a very short trip, the master still gets at least this amount.

**Example (local):** base $80 + 2 mi × $5 = $90, but minimum $100 → customer pays **$100**.

**UI copy suggestion:**

- EN: *"Minimum charge for this service type"*  
- RU: *"Минимальная стоимость для этого типа услуги"*  

Each of the 4 types has its **own** `minimum_fee` (not shared).

---

## Service type constants

Use these exact strings in API requests:

```ts
type TowingServiceType =
  | 'local'
  | 'long_distance'
  | 'accident_recovery'
  | 'motorcycle';
```

| `service_type` | `label` (from API) |
|----------------|-------------------|
| `local` | Local towing |
| `long_distance` | Long distance towing |
| `accident_recovery` | Accident recovery |
| `motorcycle` | Motorcycle towing |

---

## Master app — Workshop / Towing screen

### Load pricing

**Option A — dedicated endpoint (recommended)**

```
GET /api/master/towing-pricing/
Authorization: Bearer <master_jwt>
```

Optional query: `?master_id=123` if the user has multiple workshops.

**Option B — workshop profile**

```
GET /api/master/masters/
```

Response includes `towing_pricing` (same shape) for the owner's profile only.

### Response shape

Always **4 items** in `services[]` (missing DB rows return `"0.00"` and `configured: false`):

```json
{
  "master_id": 1,
  "configured": true,
  "services": [
    {
      "service_type": "local",
      "label": "Local towing",
      "base_fee": "80.00",
      "price_per_mile": "5.00",
      "minimum_fee": "100.00",
      "is_active": true,
      "configured": true
    },
    {
      "service_type": "long_distance",
      "label": "Long distance towing",
      "base_fee": "120.00",
      "price_per_mile": "4.00",
      "minimum_fee": "100.00",
      "is_active": true,
      "configured": true
    },
    {
      "service_type": "accident_recovery",
      "label": "Accident recovery",
      "base_fee": "0.00",
      "price_per_mile": "0.00",
      "minimum_fee": "0.00",
      "is_active": false,
      "configured": false
    },
    {
      "service_type": "motorcycle",
      "label": "Motorcycle towing",
      "base_fee": "50.00",
      "price_per_mile": "3.00",
      "minimum_fee": "70.00",
      "is_active": true,
      "configured": true
    }
  ]
}
```

### Map UI → API

Each expandable card on the Workshop Towing screen = one `services[]` item:

| UI field | API field |
|----------|-----------|
| Base fee | `base_fee` |
| Per mile | `price_per_mile` |
| Minimum fee | `minimum_fee` |
| Section enabled | `is_active` |

**Do not** use a single flat `price` for motorcycle anymore — use `base_fee` + `price_per_mile` like the other types.

### Save (Save button)

```
PUT /api/master/towing-pricing/
Content-Type: application/json
Authorization: Bearer <master_jwt>
```

Send all sections the user edited (at least one item in `services`):

```json
{
  "master_id": 1,
  "services": [
    {
      "service_type": "local",
      "base_fee": 80,
      "price_per_mile": 5,
      "minimum_fee": 100,
      "is_active": true
    },
    {
      "service_type": "long_distance",
      "base_fee": 120,
      "price_per_mile": 4,
      "minimum_fee": 100,
      "is_active": true
    },
    {
      "service_type": "accident_recovery",
      "base_fee": 150,
      "price_per_mile": 6,
      "minimum_fee": 150,
      "is_active": true
    },
    {
      "service_type": "motorcycle",
      "base_fee": 50,
      "price_per_mile": 3,
      "minimum_fee": 70,
      "is_active": true
    }
  ]
}
```

Response = same structure as GET.

### Frontend helper — bind form to API

```ts
const SERVICE_ORDER: TowingServiceType[] = [
  'local',
  'long_distance',
  'accident_recovery',
  'motorcycle',
];

function mapApiToForm(data: TowingPricingResponse) {
  const byType = Object.fromEntries(
    data.services.map((s) => [s.service_type, s])
  );
  return SERVICE_ORDER.map((type) => ({
    service_type: type,
    label: byType[type]?.label ?? type,
    base_fee: byType[type]?.base_fee ?? '0',
    price_per_mile: byType[type]?.price_per_mile ?? '0',
    minimum_fee: byType[type]?.minimum_fee ?? '0',
    is_active: byType[type]?.is_active ?? false,
  }));
}

function mapFormToPut(services: FormRow[]) {
  return {
    services: services.map((row) => ({
      service_type: row.service_type,
      base_fee: Number(row.base_fee),
      price_per_mile: Number(row.price_per_mile),
      minimum_fee: Number(row.minimum_fee),
      is_active: row.is_active,
    })),
  };
}
```

---

## Driver app — estimate & create

### Breaking change

**`service_type` is required** on both endpoints (was optional / auto before).

### 1) User picks towing type

Show 4 options (or only types where nearby masters have `configured: true` after estimate).

### 2) Estimate

```
POST /api/order/towing/estimate/
Authorization: Bearer <driver_jwt>
```

```json
{
  "service_type": "long_distance",
  "latitude": 41.3111,
  "longitude": 69.2797,
  "delivery_latitude": 41.35,
  "delivery_longitude": 69.30,
  "distance_miles": 60,
  "radius_miles": 50
}
```

Either send `distance_miles` **or** `delivery_latitude` + `delivery_longitude`.

**Response:**

```json
{
  "service_type": "long_distance",
  "service_label": "Long distance towing",
  "distance_miles": "60.00",
  "trip_type": "long_distance",
  "master_count": 2,
  "masters": [
    {
      "master_id": 1,
      "master": { },
      "distance_to_pickup_miles": 2.5,
      "pricing": {
        "service_type": "long_distance",
        "trip_type": "long_distance",
        "distance_miles": "60.00",
        "base_fee": "120.00",
        "price_per_mile": "4.00",
        "minimum_fee": "100.00",
        "mileage_charge": "240.00",
        "calculated_total": "360.00",
        "total_price": "360.00"
      }
    }
  ]
}
```

Display `pricing.total_price` and `service_label` to the user.

### 3) Create order

```
POST /api/order/towing/
```

```json
{
  "service_type": "long_distance",
  "master_id": 1,
  "car_list": [42],
  "text": "Need towing",
  "location": "Pickup address",
  "latitude": 41.3111,
  "longitude": 69.2797,
  "delivery_location": "Delivery address",
  "delivery_latitude": 41.35,
  "delivery_longitude": 69.30,
  "distance_miles": 60
}
```

**Order detail — `order.towing`:**

```json
{
  "pickup": { "location": "...", "latitude": "...", "longitude": "..." },
  "delivery": { "location": "...", "latitude": "...", "longitude": "..." },
  "distance_miles": "60.00",
  "base_fee": "120.00",
  "price_per_mile": "4.00",
  "minimum_fee": "100.00",
  "total_price": "360.00",
  "service_type": "long_distance",
  "trip_type": "long_distance"
}
```

Use `service_type` in new code. `trip_type` is kept for backward compatibility (same value).

---

## Price formula (for UI preview)

```text
mileage_charge = distance_miles × price_per_mile
calculated     = base_fee + mileage_charge
total_price    = max(calculated, minimum_fee)
```

You can show a breakdown in the estimate step using fields from `pricing`.

---

## Migration checklist (frontend)

- [ ] Workshop Towing: 4 separate cards, each with base / per mile / minimum  
- [ ] Remove `local_max_miles` field from UI  
- [ ] Remove auto local/long switching logic on the client  
- [ ] Motorcycle: switch from single `price` to `base_fee` + `price_per_mile`  
- [ ] Driver: add service type selector before estimate  
- [ ] Pass `service_type` in `POST /towing/estimate/` and `POST /towing/`  
- [ ] Read `order.towing.service_type` in order details  
- [ ] PUT towing pricing uses `services[]` array (old flat `local_base_fee` body no longer works)

---

## Errors to handle

| Status | Field | Meaning |
|--------|-------|---------|
| 400 | `service_type` | Missing or invalid value |
| 400 | `master_id` | Master has no active pricing for this `service_type` |
| 400 | delivery / `distance_miles` | Need miles or delivery coordinates |

---

## Related: home screen category order

Main catalog order (Towing first, etc.) is separate:

```
GET /api/categories/categories/?type=by_order
```

Response items include `sort_order` — list is already sorted ascending. See backend `docs` / `apply_category_sort_order` if icons still look wrong (category **names** in DB must match).

---

## Quick reference

| Action | Method | Path |
|--------|--------|------|
| Get master towing tariffs | GET | `/api/master/towing-pricing/` |
| Save master towing tariffs | PUT | `/api/master/towing-pricing/` |
| Estimate price | POST | `/api/order/towing/estimate/` |
| Create towing order | POST | `/api/order/towing/` |

---

## Client FAQ (short answers for support / PM)

**Q: Why are Local and Long distance in one screen but separate?**  
A: They are **separate services** now. Same screen, separate rows — like Accident recovery and Motorcycle.

**Q: Who picks local vs long distance?**  
A: The **driver**, not the app by mileage.

**Q: What is minimum fee?**  
A: The **lowest price** for that service type, even if the mileage calculation is lower.

**Q: Do we still need “local max miles”?**  
A: **No** — removed from backend.
