# AutoHandy — Yangi funksiyalar (Mobile / Frontend qo‘llanma)

Bu hujjat oxirgi release dagi **barcha** yangi funksiyalar uchun client (haydovchi) va master (usta) ilovalarida qanday ekranlar, API chaqiruvlari va validatsiya kerakligini tavsiflaydi.

Backend tafsilotlari: `docs/RELEASE_FEATURES_BACKEND.md`

| # | Funksiya |
|---|----------|
| 1 | Review, reyting, choycha |
| 2 | Workshop compliance (asbob + litsenziya) |
| 3 | Semi Trucks Roadside |
| 4 | Vaqt o‘zgartirish |
| 5 | Email OTP |
| 6 | Towing |
| 7 | Fuel Delivery |

---

# 1. Review, reyting va choycha

## Qachon ko‘rsatiladi

Buyurtma **Completed** bo‘lgach client ekranlari ochiladi.

Backend `GET /api/order/<id>/` yoki complete javobida `post_completion` blokini qaytaradi:

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

## UI oqimi

```
Order Completed
    ↓
Review ekrani (rating 1–5 + tags + comment)
    ↓
Choycha modal (avtomatik)
    "Would you like to leave a tip for your provider?"
    [$5] [$10] [$20] [Other Amount] [No Thanks]
```

### Choycha modal

| Tugma | Harakat |
|-------|---------|
| $5 / $10 / $20 | `tip_only: true`, `tip_amount` |
| Other Amount | Custom summa input → API |
| No Thanks | `tip_only: true`, `decline_tip: true` |

### Review ekrani

| Element | API |
|---------|-----|
| Yulduzlar 1–5 | `rating` |
| Taglar (kamida 1 ta) | `tags[]` |
| Izoh | `comment` (ixtiyoriy) |

**Mavjud taglar:** `fast_work`, `no_overpay`, `deadline`, `always_available`, `individual_approach`, `polite`, `late_or_delayed`, `poor_quality`, `overpriced`, `unprofessional`, `hard_to_reach`, `other_issue`

## API

```http
POST /api/order/reviews/create/
```

**Review:**
```json
{
  "order_id": 123,
  "rating": 5,
  "tags": ["fast_work", "polite"],
  "comment": "Thanks!"
}
```

**Choycha:**
```json
{
  "order_id": 123,
  "tip_only": true,
  "tip_amount": "10.00"
}
```

**Rad etish:**
```json
{
  "order_id": 123,
  "tip_only": true,
  "decline_tip": true
}
```

## UI qoidalari

- `needs_review=false` → review ekranini o‘tkazib yuborish mumkin
- `needs_tip_prompt=false` → modal ko‘rsatmaslik (allaqachon to‘langan yoki rad etilgan)
- Choycha uchun clientda **saqlangan karta** bo‘lishi kerak (Stripe)
- `tip_presets` ni backend dan oling — hardcode qilmang

## Checklist

- [ ] Completion dan keyin `post_completion` ni o‘qish
- [ ] Review ekrani (rating + tags)
- [ ] Tip modal (5 preset + Other + No Thanks)
- [ ] `POST reviews/create/` integratsiyasi
- [ ] Xato: karta yo‘q → UI xabari

---

# 2. Master workshop: asbob va litsenziya

## Qachon ko‘rsatiladi

Master onboarding yoki Workshop / Profile da **majburiy** tasdiq ekrani.

## UI

```
Workshop Compliance
─────────────────────
☑ I confirm I have the necessary tools for my services
☑ I confirm I have all required licenses (where applicable by law)

[Confirm & Continue]
```

Ikkala checkbox belgilanmaguncha tugma **bloklangan**.

## API

```http
PUT /api/auth/user/workshop-compliance/
Authorization: Bearer <master_token>
```

```json
{
  "has_tools_confirmed": true,
  "has_licenses_confirmed": true
}
```

**GET `/api/auth/user/`** dan holatni o‘qing:

```json
{
  "has_tools_confirmed": false,
  "has_licenses_confirmed": false,
  "workshop_compliance_confirmed_at": null
}
```

`workshop_compliance_confirmed_at` `null` bo‘lsa — ekranni ko‘rsatish / bloklash.

## Checklist

- [ ] Master login dan keyin compliance tekshiruvi
- [ ] Ikkala checkbox majburiy
- [ ] PUT workshop-compliance
- [ ] Tasdiqlangach asosiy ekranga o‘tish

---

# 3. Emergency Roadside for Semi Trucks

## Qachon ishlatiladi

Alohida yo‘nalish — **yuk mashinalari** (semi trucks) uchun, oddiy avtomobil katalogidan ajratilgan.

## Katalog yuklash

```http
GET /api/categories/categories/?type=by_order&is_truck=true
```

Asosiy: **Emergency Roadside for Semi Trucks**

```http
GET /api/categories/subcategories/?parent_id=<MAIN_ID>
```

**Subkategoriyalar:**
- Tire Service
- Jump Start
- Fuel Delivery
- Lockout
- Roadside Repair
- Towing

## UI

```
┌─────────────────────────────────┐
│ Emergency Roadside              │
│ for Semi Trucks                 │
├─────────────────────────────────┤
│ > Tire Service                  │
│ > Jump Start                    │
│ > Fuel Delivery                 │
│ > Lockout                       │
│ > Roadside Repair               │
│ > Towing                        │
└─────────────────────────────────┘
```

Oddiy avtomobil ilovasi: `is_truck` parametrsiz katalog — truck yo‘q.

Truck ilovasi / rejimi: `is_truck=true`.

## Buyurtma

Xuddi oddiy order:
- Standard: `POST /api/order/standard/`
- SOS: `POST /api/order/sos/`

`category_list` — truck subcategory ID lari.

**Eslatma:** Fuel Delivery truck katalogida ham bor — §7 qoidalariga amal qiling.

## Checklist

- [ ] Truck rejimi: `is_truck=true` katalog
- [ ] 6 ta xizmat ro‘yxati
- [ ] Towing truck uchun — §6 Towing oqimi
- [ ] Fuel Delivery truck uchun — §7

---

# 4. Buyurtma vaqtini o‘zgartirish

## Oqim

```
Master → yangi vaqt taklif qiladi
    ↓
Client → push / pending ro‘yxatda ko‘radi
    ↓
Client → Approve yoki Reject
    ↓
Approve → order vaqti avtomatik yangilanadi
```

## Master UI

Buyurtma detalida (accepted / on_the_way / arrived):

```
Propose new time
────────────────
Date: [picker]
Start: [time]
End: [time]        ← standard buyurtmalar uchun majburiy
Comment: [optional]

[Send proposal]
```

```http
POST /api/order/<order_id>/time-change/requests/
```

```json
{
  "proposed_preferred_date": "2026-06-10",
  "proposed_preferred_time_start": "14:00:00",
  "proposed_preferred_time_end": "16:00:00",
  "comment": "Can arrive earlier"
}
```

## Client UI

**Pending ro‘yxat:**
```http
GET /api/order/time-change/requests/pending/
```

**Tasdiqlash:**
```http
POST /api/order/time-change/requests/<id>/approve/
```
```json
{ "comment": "OK" }
```

**Rad:**
```http
POST /api/order/time-change/requests/<id>/reject/
```
```json
{ "comment": "That time does not work" }
```
(`comment` majburiy)

## Push / WebSocket

| Event | Kim |
|-------|-----|
| `time_change_request` | Client |
| `time_change_approved` | Master |
| `time_change_rejected` | Master |

## Checklist

- [ ] Master: propose time form
- [ ] Client: pending list + approve/reject
- [ ] Approve dan keyin order `preferred_*` yangilanganini ko‘rsatish
- [ ] Push listener

---

# 5. Email verification (OTP)

## Qachon

Ro‘yxatdan keyin yoki email qo‘shilganda — **verify qilmasdan** ko‘p funksiyalar bloklangan.

`GET /api/auth/user/`:
```json
{
  "is_email_verified": false,
  "requires_email_verification": true
}
```

## UI

```
Verify your email
─────────────────
We sent a 4-digit code to user@example.com

[ _ _ _ _ ]  ← OTP input

[Verify]  [Resend code]
```

## API

**Email qo‘shish / yangilash:**
```http
POST /api/auth/user/register-profile/
```
```json
{ "email": "user@example.com" }
```
→ Kod emailga yuboriladi.

**Tasdiqlash:**
```http
POST /api/auth/email-verification/
```
```json
{ "code": "4821" }
```

**Qayta yuborish:**
```http
POST /api/auth/email-verification/resend/
```

## UI qoidalari

- `requires_email_verification=true` → verify ekraniga yo‘naltirish
- Kod muddati: 15 daqiqa (default)
- 400 xatolar: noto‘g‘ri kod, muddati o‘tgan
- Dev: `EMAIL_DEBUG_IN_RESPONSE=true` bo‘lsa resend javobida kod bo‘lishi mumkin

## Master va Client

Ikkala rol uchun bir xil oqim.

## Checklist

- [ ] Register/profile dan keyin OTP ekran
- [ ] 4 xonali kod input
- [ ] Resend (cooldown UI)
- [ ] Verify muvaffaqiyat → asosiy ilova
- [ ] 403 blocked API → verify ekraniga qaytarish

---

# 6. Towing — mil bo‘yicha narx

## Client oqimi

```
1. Towing xizmatini tanlash
2. Pickup manzil (GPS)
3. Delivery manzil YOKI mil soni
4. Estimate → masterlar ro‘yxati + narx
5. Master tanlash
6. Buyurtma yaratish
```

## Master oqimi

```
My Workshop → Towing pricing
────────────────────────────
Base Fee ($):     [80]
Price per mile:   [5]
Minimum Fee ($):  [100]
[Save]
```

```http
PUT /api/master/towing-pricing/
```
```json
{
  "base_fee": 80,
  "price_per_mile": 5,
  "minimum_fee": 100,
  "is_active": true
}
```

## Client — estimate

```http
POST /api/order/towing/estimate/
```

**Variant A — ikki manzil:**
```json
{
  "latitude": "41.311100",
  "longitude": "69.279700",
  "delivery_latitude": "41.350000",
  "delivery_longitude": "69.300000"
}
```

**Variant B — mil:**
```json
{
  "latitude": "41.311100",
  "longitude": "69.279700",
  "distance_miles": "20"
}
```

**Javob:**
```json
{
  "distance_miles": "20.00",
  "master_count": 1,
  "masters": [
    {
      "master_id": 1,
      "master": { "id": 1, "name": "..." },
      "distance_to_pickup_miles": 2.5,
      "pricing": {
        "base_fee": "80.00",
        "price_per_mile": "5.00",
        "minimum_fee": "100.00",
        "mileage_charge": "100.00",
        "calculated_total": "180.00",
        "total_price": "180.00"
      }
    }
  ]
}
```

## Client — buyurtma

```http
POST /api/order/towing/
```

```json
{
  "master_id": 1,
  "car_list": [1],
  "text": "Need towing",
  "location": "Pickup address",
  "latitude": "41.311100",
  "longitude": "69.279700",
  "delivery_location": "Delivery address",
  "delivery_latitude": "41.350000",
  "delivery_longitude": "69.300000",
  "distance_miles": "20"
}
```

**`master_id` majburiy** — client ro‘yxatdan master tanlaydi.

## UI — narx ko‘rsatish

```
Base fee:     $80
20 miles × $5: $100
─────────────────
Total:        $180
```

Order detal: `order.towing.total_price` va breakdown.

## Checklist

- [ ] Master: towing pricing form
- [ ] Client: pickup + delivery yoki miles
- [ ] Estimate ekrani (master list + price)
- [ ] Master tanlash
- [ ] `POST /api/order/towing/`
- [ ] Order detail `towing` bloki

---

# 7. Fuel Delivery

Batafsil: `docs/FUEL_DELIVERY_FRONTEND.md`

## Client (qisqa)

1. Roadside → **Fuel Delivery** → alohida ekran
2. *"Delivery of 2 gallons of fuel"*
3. **Gasoline** / **Diesel** (majburiy)
4. Continue → buyurtma

```json
{
  "category_list": [<FUEL_DELIVERY_ID>],
  "fuel_type": "gasoline",
  "master_id": 1,
  ...
}
```

## Master (qisqa)

Fuel Delivery skill:
- Price
- ☑ 2-gallon gas container
- ☑ 2-gallon diesel container

Ikkalasi bo‘lmasa — Save bloklangan.

## Buyurtmada ko‘rinish

`fuel_delivery_summary`: *"Delivery of 2 gallons of fuel (Gasoline)"*

## Checklist

- [ ] Client fuel type ekrani
- [ ] `fuel_type` API
- [ ] Master 2 checkbox
- [ ] Order da summary ko‘rsatish

---

# Umumiy integratsiya checklist

## Client app

| Funksiya | Status |
|----------|--------|
| Post-completion review + tip | ☐ |
| Email OTP | ☐ |
| Towing estimate + create | ☐ |
| Fuel Delivery screen | ☐ |
| Truck catalog (`is_truck=true`) | ☐ |
| Time change approve/reject | ☐ |

## Master app

| Funksiya | Status |
|----------|--------|
| Workshop compliance | ☐ |
| Towing pricing | ☐ |
| Fuel Delivery containers | ☐ |
| Time change propose | ☐ |
| Email OTP | ☐ |
| Fuel type in order detail | ☐ |
| Truck services | ☐ |

---

# Backend tayyorligi (migrate)

Serverda barcha migratsiyalar qo‘llangan bo‘lishi kerak:

```bash
python manage.py migrate --noinput
```

To‘liq ro‘yxat: `docs/RELEASE_FEATURES_BACKEND.md` → **§ Serverga deploy**.

**Muhim `.env`:**
```env
REQUIRE_EMAIL_VERIFICATION=true
EMAIL_VERIFICATION_CODE_MINUTES=15
TIP_PRESET_AMOUNTS=5,10,20
TOWING_ESTIMATE_RADIUS_MILES=50
```

---

# API endpointlar — tez ro‘yxat

| Funksiya | Method | Path |
|----------|--------|------|
| Review/Tip | POST | `/api/order/reviews/create/` |
| Workshop compliance | PUT | `/api/auth/user/workshop-compliance/` |
| Truck categories | GET | `/api/categories/categories/?type=by_order&is_truck=true` |
| Time change (master) | POST | `/api/order/<id>/time-change/requests/` |
| Time change approve | POST | `/api/order/time-change/requests/<id>/approve/` |
| Time change reject | POST | `/api/order/time-change/requests/<id>/reject/` |
| Time change pending | GET | `/api/order/time-change/requests/pending/` |
| Email verify | POST | `/api/auth/email-verification/` |
| Email resend | POST | `/api/auth/email-verification/resend/` |
| Towing pricing | GET/PUT | `/api/master/towing-pricing/` |
| Towing estimate | POST | `/api/order/towing/estimate/` |
| Towing create | POST | `/api/order/towing/` |
| Fuel order | POST | `/api/order/standard/` (+ `fuel_type`) |
| Fuel skill | POST | `/api/master/service-items/` |

---

## Bog‘liq hujjatlar

| Fayl | Mazmun |
|------|--------|
| `docs/RELEASE_FEATURES_BACKEND.md` | Backend + migrate |
| `docs/FUEL_DELIVERY_FRONTEND.md` | Fuel Delivery batafsil |
| `docs/FUEL_DELIVERY_BACKEND.md` | Fuel Delivery backend |
| `docs/STRIPE_DRIVER_AND_RIDER_INTEGRATION.md` | Karta / choycha to‘lovi |

---

*Oxirgi yangilanish: 2026-06 release*
