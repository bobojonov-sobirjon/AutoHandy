# Fuel Delivery — Backend hujjati

Bu hujjat **Fuel Delivery** (yo‘l-yo‘lakka yonilg‘i yetkazish) funksiyasi uchun backend o‘zgarishlarini, API kontraktini va serverga deploy qilish (migrate) tartibini tavsiflaydi.

---

## 1. Biznes talabi (qisqacha)

| Tomon | Talab |
|-------|-------|
| **Client** | Fuel Delivery tanlangach alohida ekranda *"Delivery of 2 gallons of fuel"* va majburiy tanlov: **Gasoline** yoki **Diesel** |
| **Client** | Tanlangan yoqilg‘i turi buyurtmada saqlanadi va master qabul qilgach ko‘rinadi |
| **Master** | Fuel Delivery narxi bilan birga **ikkala** checkbox majburiy: 2-gallon gas + 2-gallon diesel idishlari |
| **Master** | Ikkala checkbox bo‘lmasa — Fuel Delivery **faol emas** (buyurtma yaratib bo‘lmaydi) |

---

## 2. Qanday aniqlanadi «Fuel Delivery»?

Kategoriya **nomi** bo‘yicha (`name = "Fuel Delivery"`, `type_category = by_order`).

- Avtomobil **Roadside Assistance** katalogidagi Fuel Delivery
- **Emergency Roadside for Semi Trucks** (`is_truck=true`) ichidagi Fuel Delivery

Helper: `apps/categories/services/fuel_delivery_catalog.py`

---

## 3. Model o‘zgarishlari

### 3.1 `MasterServiceItems` (master skill qatori)

| Field | Tip | Default | Ma’nosi |
|-------|-----|---------|---------|
| `has_gas_container_2gal` | `bool` | `false` | «I have a separate 2-gallon gas container» |
| `has_diesel_container_2gal` | `bool` | `false` | «I have a separate 2-gallon diesel container» |

**Faollik qoidasi:** Fuel Delivery kategoriyasi uchun ikkalasi ham `true` bo‘lishi shart.

API javobida qo‘shimcha maydon: `fuel_delivery_active` (`true` / `false`).

**Migratsiya:** `master/0034_masterserviceitems_fuel_delivery_containers`

---

### 3.2 `Order` (buyurtma)

| Field | Tip | Qiymatlar |
|-------|-----|-----------|
| `fuel_delivery_type` | `CharField`, nullable | `gasoline`, `diesel` |

Client tanlovini saqlash uchun (ayniqsa SOS: master keyinroq tayinlanadi).

**Migratsiya:** `order/0055_order_fuel_delivery_type`

---

### 3.3 `OrderService` (buyurtma × skill qatori)

| Field | Tip | Qiymatlar |
|-------|-----|-----------|
| `fuel_type` | `CharField`, nullable | `gasoline`, `diesel` |

Fuel Delivery qatoriga bog‘langan yoqilg‘i turi (master buyurtma detalida ko‘radi).

**Migratsiya:** `order/0054_orderservice_fuel_type`

---

### 3.4 `FuelDeliveryType` (enum)

```python
class FuelDeliveryType(models.TextChoices):
    GASOLINE = 'gasoline', 'Gasoline'
    DIESEL = 'diesel', 'Diesel'
```

Fayl: `apps/order/models.py`

---

## 4. Validatsiya qoidalari

### 4.1 Master — skill qo‘shish / yangilash

**Endpointlar:**
- `POST /api/master/service-items/`
- `PUT /api/master/service-items/<item_id>/`

Fuel Delivery kategoriyasi uchun **ikkala** maydon `true` bo‘lishi shart. Aks holda `400`:

```json
{
  "has_gas_container_2gal": ["Fuel Delivery requires confirming both containers: ..."],
  "has_diesel_container_2gal": ["Fuel Delivery requires confirming both containers: ..."]
}
```

Validatsiya: `apps/master/services/fuel_delivery.py`

---

### 4.2 Client — buyurtma yaratish

**Endpointlar:**
- `POST /api/order/standard/`
- `POST /api/order/sos/`

`category_list` ichida Fuel Delivery bo‘lsa → `fuel_type` **majburiy** (`gasoline` yoki `diesel`).

| Holat | Natija |
|-------|--------|
| Fuel Delivery bor, `fuel_type` yo‘q | `400` |
| Fuel Delivery yo‘q, `fuel_type` yuborilgan | `400` |
| Standard + `master_id`, master ikkala idishni tasdiqlamagan | `400` (`master_id`) |

---

### 4.3 SOS master navbati

`build_sos_master_id_queue()` Fuel Delivery uchun faqat **ikkala idish tasdiqlangan** masterlarni qaytaradi.

Fayl: `apps/order/services/sos_master_queue.py`

---

### 4.4 OrderService ga fuel_type yozish

1. Buyurtma yaratilganda `fuel_delivery_type` saqlanadi.
2. `sync_order_services_from_order_categories()` chaqirilganda Fuel Delivery qatorlariga `fuel_type` yoziladi.
3. SOS: master **accept** qilganda ham sync ishlaydi — `fuel_delivery_type` allaqachon orderda bo‘lgani uchun avtomatik qo‘llanadi.

Fayl: `apps/order/services/fuel_delivery_orders.py`

---

## 5. API — Master

### 5.1 Skill qo‘shish

```http
POST /api/master/service-items/
Authorization: Bearer <master_jwt>
Content-Type: application/json
```

```json
{
  "master_id": 1,
  "services": [
    {
      "category": 42,
      "price": 100,
      "has_gas_container_2gal": true,
      "has_diesel_container_2gal": true
    }
  ]
}
```

`master_id` ixtiyoriy — agar foydalanuvchida bitta master profil bo‘lsa.

### 5.2 Skill yangilash

```http
PUT /api/master/service-items/<item_id>/
```

```json
{
  "price": 120,
  "has_gas_container_2gal": true,
  "has_diesel_container_2gal": true
}
```

### 5.3 Javob (skill qatori)

`master_service_items[].items[]` yoki `MasterServiceItemsSerializer`:

```json
{
  "id": 10,
  "category_id": 42,
  "name": "Fuel Delivery",
  "price": 100,
  "has_gas_container_2gal": true,
  "has_diesel_container_2gal": true,
  "fuel_delivery_active": true
}
```

`fuel_delivery_active: false` → UI da Save bloklanishi yoki xato ko‘rsatiladi.

---

## 6. API — Client (buyurtma yaratish)

### 6.1 Standard

```http
POST /api/order/standard/
Authorization: Bearer <client_jwt>
Content-Type: application/json
```

```json
{
  "master_id": 5,
  "text": "Need fuel on highway",
  "location": "I-80 exit 12",
  "latitude": 41.311100,
  "longitude": 69.279700,
  "car_list": [1],
  "category_list": [42],
  "fuel_type": "gasoline"
}
```

### 6.2 SOS

```http
POST /api/order/sos/
```

Xuddi shu maydonlar; `fuel_type` Fuel Delivery bo‘lsa majburiy.

`fuel_type` qiymatlari:
- `"gasoline"` — Gas (Regular)
- `"diesel"` — Diesel

---

## 7. API — Buyurtma javobi (master va client)

`GET` order detail / create javobidagi `order` obyekti:

### 7.1 Order darajasi

```json
{
  "fuel_delivery_type": "gasoline",
  "fuel_delivery_type_display": "Gasoline",
  "fuel_delivery_summary": "Delivery of 2 gallons of fuel (Gasoline)"
}
```

### 7.2 `services` guruhi (master ko‘rinishi)

```json
{
  "services": [
    {
      "parent": { "id": 40, "name": "Roadside Assistance" },
      "items": [
        {
          "order_service_id": 99,
          "name": "Fuel Delivery",
          "price": 100,
          "fuel_type": "gasoline",
          "fuel_type_display": "Gasoline",
          "fuel_delivery_summary": "Delivery of 2 gallons of fuel (Gasoline)"
        }
      ]
    }
  ]
}
```

### 7.3 `category_data`

Fuel Delivery kategoriyasi uchun ham `fuel_type`, `fuel_type_display`, `fuel_delivery_summary` qo‘shiladi.

---

## 8. O‘zgartirilgan / yangi fayllar

| Fayl | Vazifa |
|------|--------|
| `apps/categories/services/fuel_delivery_catalog.py` | Fuel Delivery kategoriyasini aniqlash |
| `apps/master/services/fuel_delivery.py` | Master idish validatsiyasi |
| `apps/order/services/fuel_delivery_orders.py` | OrderService ga fuel_type yozish |
| `apps/order/services/order_category_services.py` | Sync dan keyin fuel_type qo‘llash |
| `apps/order/services/sos_master_queue.py` | SOS filtri |
| `apps/master/models.py` | Container maydonlari |
| `apps/order/models.py` | `FuelDeliveryType`, order/service maydonlari |
| `apps/master/api/serializers.py` | Master API |
| `apps/master/api/views.py` | `POST service-items` |
| `apps/order/api/serializers.py` | Order create + order detail |
| `apps/order/tests_fuel_delivery.py` | 5 ta test |

---

## 9. Testlar

```bash
python manage.py test apps.order.tests_fuel_delivery -v 2
```

Qamrov:
- Master — ikkala idishsiz → 400
- Master — ikkala idish bilan → 201, `fuel_delivery_active: true`
- Client — `fuel_type` siz → 400
- Client — `fuel_type` bilan → order + OrderService saqlanadi
- Master idishsiz — standard buyurtma → 400

---

## 10. Serverga deploy — MIGRATE (barcha kerakli migratsiyalar)

Production / staging serverda loyiha ildizidan:

```bash
# Barcha kutilayotgan migratsiyalarni ko‘rish
python manage.py showmigrations

# Eng xavfsiz usul — barcha app larni bir martada
python manage.py migrate --noinput
```

### 10.1 Fuel Delivery uchun majburiy migratsiyalar

| App | Migratsiya | Nima qiladi |
|-----|------------|-------------|
| `master` | `0034_masterserviceitems_fuel_delivery_containers` | `has_gas_container_2gal`, `has_diesel_container_2gal` |
| `order` | `0054_orderservice_fuel_type` | `OrderService.fuel_type` |
| `order` | `0055_order_fuel_delivery_type` | `Order.fuel_delivery_type` |

Alohida ishga tushirish:

```bash
python manage.py migrate master 0034 --noinput
python manage.py migrate order 0054 --noinput
python manage.py migrate order 0055 --noinput
```

---

### 10.2 Oxirgi sessiyadagi boshqa backend funksiyalar (agar serverda hali qo‘llanmagan bo‘lsa)

Quyidagi migratsiyalar ham shu branch bilan birga kelishi mumkin. `showmigrations` da `[ ]` (bo‘sh) ko‘rinsa — migrate qiling.

#### Accounts — Email OTP tasdiqlash

```bash
python manage.py migrate accounts 0023 --noinput
python manage.py migrate accounts 0024 --noinput
```

| Migratsiya | Nima qiladi |
|------------|-------------|
| `0023_emailverificationtoken_code` | Email tasdiqlash uchun 4 xonali `code` |
| `0024_...` | Indeks tozalash |

#### Categories — Truck katalog + Towing

```bash
python manage.py migrate categories 0015 --noinput
python manage.py migrate categories 0016 --noinput
python manage.py migrate categories 0017 --noinput
python manage.py migrate categories 0018 --noinput
```

| Migratsiya | Nima qiladi |
|------------|-------------|
| `0015_category_is_towing_entry` | `Category.is_towing_entry` |
| `0016_seed_towing_entry_category` | Towing seed kategoriya |
| `0017_category_is_truck` | `Category.is_truck` |
| `0018_seed_truck_roadside_categories` | Semi Trucks Roadside + Fuel Delivery va boshqalar |

#### Master — Towing narxlash

```bash
python manage.py migrate master 0033 --noinput
```

| Migratsiya | Nima qiladi |
|------------|-------------|
| `0033_master_towing_pricing` | `MasterTowingPricing` modeli |

#### Order — Towing buyurtma

```bash
python manage.py migrate order 0052 --noinput
python manage.py migrate order 0053 --noinput
```

| Migratsiya | Nima qiladi |
|------------|-------------|
| `0052_order_towing` | Towing maydonlari (`delivery_location`, `towing_*`) |
| `0053_towingorder_and_more` | TowingOrder proxy va qo‘shimchalar |

---

### 10.3 Deploy checklist

```bash
# 1. Kodni tortish
git pull

# 2. Virtualenv / dependencies (agar kerak bo‘lsa)
pip install -r requirements.txt

# 3. Migratsiya
python manage.py migrate --noinput

# 4. Tekshirish
python manage.py showmigrations | findstr /V "\[X\]"   # Windows
# yoki
python manage.py showmigrations | grep -v "\[X\]"      # Linux

# 5. Test (ixtiyoriy)
python manage.py test apps.order.tests_fuel_delivery -v 2

# 6. Gunicorn/uWSGI/Daphne restart
# (serveringizdagi process manager bo‘yicha)
```

### 10.4 `.env` (mavjud sozlamalar — Fuel Delivery uchun yangi kalit yo‘q)

Fuel Delivery alohida env talab qilmaydi. Oxirgi funksiyalar uchun mavjud kalitlar:

| O‘zgaruvchi | Default | Ma’nosi |
|-------------|---------|---------|
| `EMAIL_VERIFICATION_CODE_MINUTES` | `15` | Email OTP muddati |
| `TOWING_ESTIMATE_RADIUS_MILES` | — | Towing estimate radius |

---

## 11. Xatoliklar (tez ma’lumot)

| HTTP | Field | Sabab |
|------|-------|-------|
| 400 | `fuel_type` | Fuel Delivery tanlangan, lekin yoqilg‘i turi yuborilmagan |
| 400 | `master_id` | Master Fuel Delivery ni faollashtirmagan (idishlar tasdiqlanmagan) |
| 400 | `has_gas_container_2gal` / `has_diesel_container_2gal` | Master skill saqlashda ikkala checkbox yo‘q |
| 400 | `category_list` (SOS) | Yaqin atrofda Fuel Delivery + idishlari tasdiqlangan master yo‘q |

---

*Hujjat: Fuel Delivery backend integratsiyasi. Frontend qo‘llanma: `docs/FUEL_DELIVERY_FRONTEND.md`*
