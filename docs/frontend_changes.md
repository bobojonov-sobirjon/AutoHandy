# Frontend uchun o‘zgarishlar (API/WS)

Ushbu fayl frontend jamoaga yuborish uchun: order create/details, SOS WebSocket payload, emergency pricing, master rate’lar (Acceptance/Completion) va boshqa qo‘shimchalar.

---

## 1) Order create payload: `parts_purchase_required_json`

Order create endpoint’larida quyidagi field qo‘shildi:

- `parts_purchase_required` *(bool)* — master ehtiyot qism sotib olishi kerak bo‘lishi mumkin
- `parts_purchase_required_json` *(array<object>)* — ehtiyot qismlar ro‘yxati

`parts_purchase_required_json` item:

- `vehicle_vin` *(string, max 17; optional)*
- `part_name` *(string, max 100; optional)*
- `is_address` *(bool; required)* — mijoz qayerdan olishni biladimi (yes/no)

**Alias key’lar** (typo bo‘lsa ham qabul qilinadi):

- `"vehicle vin"` → `vehicle_vin`
- `"part name"` → `part_name`
- `"is_addess"` → `is_address`

### JSON example

```json
{
  "parts_purchase_required": true,
  "parts_purchase_required_json": [
    { "vehicle_vin": "1HGCM82633A004352", "part_name": "A/C Compressor", "is_address": true },
    { "vehicle_vin": "", "part_name": "Oil filter", "is_address": false }
  ]
}
```

### multipart/form-data’da yuborish

`parts_purchase_required_json` ni JSON string qilib yuboring:

```json
[{"vehicle_vin":"","part_name":"","is_address":true}]
```

### Order details’da ko‘rinishi

Order details/list response’larda `parts_purchase_required_json` qaytadi.

---

## 2) SOS timing (response window)

SOS offer response window default 7 minut qilib sozlangan:

- `SOS_OFFER_SECONDS_PER_MASTER = 420`
- `SOS_BROADCAST_RESPONSE_SECONDS = 420`

WS payload’da `seconds` shu qiymat bilan keladi (UI countdown uchun).

---

## 3) Emergency (SOS) pricing — America time (base + coefficient + final)

Emergency/SOS orderlarda narx base price’ga vaqtga qarab ko‘paytiriladi.
Time zone: **America local time** (default `America/Los_Angeles`).

### Koeffitsient qoidasi

- 06:00 → 23:00 (day): **×1.3**
- 23:00 → 06:00 (night): **×1.6**

### Order details response’da

`pricing.emergency_pricing` ichida:

- `is_emergency` (true/false)
- `time_zone` (string)
- `time_bucket` (`day` | `night`)
- `coefficient` (`"1.3"` yoki `"1.6"` yoki `"1.0"`)
- `note` (“Higher price due to urgency or time”)
- `base_subtotal` — koeffitsientsiz subtotal
- `final_subtotal` — koeffitsient qo‘llangan subtotal (bu `pricing.subtotal` bilan teng)

### Services line item’da

Order details’dagi `services[].items[]` ichida:

- `base_price` — master qo‘ygan bazaviy narx
- `emergency_coefficient`
- `final_price` — base × coefficient
- `line_total` — yakuniy line total

**Muhim**: hisoblash “pro” usulda: avval barcha base’lar yig‘iladi → keyin koeffitsient 1 marta umumiyga qo‘llanadi (double-multiply bo‘lmaydi).

---

## 4) SOS WebSocket payload: pricing + services narxlari

SOS WS `sos_order_offer` payload’da quyidagilar bor:

- `pricing`: `subtotal`, `discount_applied`, `total`, `emergency_pricing`
- `services[]`: har bir service uchun `base_price`, `emergency_coefficient`, `final_price`, `line_total`

**Eslatma**: SOS’da master order’ga biriktirilmagan bo‘lishi mumkin. Shunday holatda WS payload narxlari `offered_master_id` bo‘yicha o‘sha master’ning `MasterServiceItems` (base price) laridan hisoblanadi.

---

## 5) Master stats: `acceptance_rate` va `completion_rate` (`api/auth/user/`)

`api/auth/user/` response’ida:

- `recommendation_percentage` olib tashlandi
- qo‘shildi:
  - `acceptance_rate` *(int %; 0..100)*
  - `completion_rate` *(int %; 0..100)*

### Acceptance Rate (%)

Offer eventlar audit’i bo‘yicha:

`accepted / (accepted + declined + expired) * 100`

### Completion Rate (%)

Yakunlangan va bekor qilingan buyurtmalar bo‘yicha (jarayondagi acceptlar hisobga olinmaydi):

`completed / (completed + cancelled) * 100`

- **completed** — `status=completed`
- **cancelled** — `status=cancelled` (mijoz xohlamadi, usta bekor qildi, auto-cancel, …)
- **accepted / on_the_way / …** — denominatorga kirmaydi (ochiq zakaz completionni pasaytirmaydi)

Misol: 2 ta completed, 0 cancelled → **100%**. 2 completed + 1 cancelled → **67%**.

Window default: **30 kun** (settings orqali).

---

## 6) SOS dispatch: Acceptance/Completion rate bo‘yicha tier + delay

SOS orderlar masterlarga tarqatilishida prioritet:

- **High tier**: `acceptance_rate >= 90` va `completion_rate >= 80`
  - SOS offer **darhol** yuboriladi
- **Low tier**: qolganlar
  - High tier bo‘lsa: Low tier **delay** bilan yuboriladi (default `120s`)
  - High tier yo‘q bo‘lsa: Low tier **darhol** yuboriladi (fallback)

Settings:

- `EMERGENCY_ACCEPTANCE_RATE_MIN` (default 90)
- `EMERGENCY_COMPLETION_RATE_MIN` (default 80)
- `EMERGENCY_LOW_TIER_DELAY_SECONDS` (default 120)

---

## 7) WS route: token query yoki path (legacy)

Quyidagi ikkala format ishlaydi:

- Tavsiya: `ws://<host>/ws/sos/master/?token=<JWT>`
- Legacy: `ws://<host>/ws/sos/master/token=<JWT>`

---

## 8) Admin: `parts_purchase_required_json` UI

Django admin’da `parts_purchase_required_json` raw JSON bo‘lib ko‘rinmaydi — jadvalcha UI orqali tahrir qilinadi (VIN / Part name / is_address + add/remove row).

---

## 9) Custom request: faqat `preferred_date`

Custom request uchun “qachonga reja qilinyapti” field sifatida endi faqat:

- `preferred_date` *(string, date, optional)* — `YYYY-MM-DD`

### POST /api/order/custom-request/

Body’da `preferred_date` yuboriladi va `Order.preferred_date`ga saqlanadi.

**Eslatma:** `custom_request_date` va `custom_request_time` ishlatilmaydi (create’da ham, details’da ham qaytmaydi).

### Order details / list

Custom request orderlarda ham `preferred_date` order response’da ko‘rinadi.

### WS custom request payload

`custom_request_job` payload’da ham `preferred_date` qo‘shilgan.

