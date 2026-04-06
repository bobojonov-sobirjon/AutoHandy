# SOS master WebSocket — to‘liq response (Flutter)

Barcha serverdan keladigan matnlar **JSON** (`UTF-8`), `jsonEncode` / `jsonDecode`.

## Ulanish

```
wss://<HOST>/ws/sos/master/?token=<ACCESS_JWT>
```

- `token` — REST orqali olingan **access** token (query param).
- JWT yaroqsiz / master profili yo‘q → socket yopiladi: **4001** (auth), **4003** (master emas).

---

## 1. Ulanishdan keyin (har doim bir marta)

```json
{
  "type": "connected",
  "channel": "sos_incoming_orders"
}
```

---

## 2. SOS taklifi (asosiy payload)

Envelop:

```json
{
  "type": "sos_order_offer",
  "data": { ... }
}
```

`data` ichidagi **barcha kalitlar** (backend `build_sos_order_websocket_payload` bilan bir xil):

### Ildiz (`data`)

| Kalit | Flutter tipi | Izoh |
|--------|----------------|------|
| `order_id` | `int` | Buyurtma ID |
| `status` | `String` | Buyurtma status kodi |
| `text` | `String` | Matn, max ~4000 belgi |
| `location` | `String` | Matn manzil / tavsif |
| `latitude` | `String?` | Latitude **string** (Decimal) |
| `longitude` | `String?` | Longitude **string** |
| `location_source` | `String?` | Manba kodi (order maydoni) |
| `priority` | `String` yoki boshqa JSON tip | Prioritet |
| `order_type` | `String` | Odatda `sos` |
| `discount` | `String?` | Decimal string |
| `parts_purchase_required` | `bool` | |
| `preferred_date` | `String?` | ISO sana `YYYY-MM-DD` |
| `preferred_time_start` | `String?` | ISO vaqt |
| `preferred_time_end` | `String?` | ISO vaqt |
| `created_at` | `String?` | ISO datetime |
| `updated_at` | `String?` | ISO datetime |
| `user` | `Map` | Quyida |
| `car_data` | `List<dynamic>` | Quyida |
| `category_data` | `List<dynamic>` | Quyida |
| `services` | `List<dynamic>` | Quyida |
| `order_images` | `List<dynamic>` | Quyida |
| `master_response_deadline` | `String?` | ISO datetime — shu vaqtgacha javob |
| `seconds` | `int` | Timer uchun sekund (broadcast / yakka master) |
| `sos_offer_index` | `int` | Navbat indeksi |
| `sos_queue_length` | `int` | Navbat uzunligi |
| `sos_broadcast` | `bool` | Keng tarqalgan navbat rejimi |
| `offered_master_id` | `int?` | Ushu push qaysi **master** (profil) `id` |

### `data.user`

| Kalit | Tip |
|--------|-----|
| `id` | `int` |
| `private_id` | `String?` |
| `first_name` | `String` |
| `last_name` | `String` |
| `full_name` | `String?` |
| `phone_number` | `String?` |
| `email` | `String?` |
| `avatar` | `String?` | To‘liq URL yoki `null` |

### `data.car_data[]` element

| Kalit | Tip |
|--------|-----|
| `id` | `int` |
| `brand` | `String` |
| `model` | `String` |
| `year` | `int?` |
| `image` | `String?` |
| `category` | `Map?` yoki `null` — `id`, `name`, `type_category`, `parent_id` |

### `data.category_data[]` element

| Kalit | Tip |
|--------|-----|
| `id` | `int` |
| `name` | `String` |
| `type_category` | `String` |
| `parent_id` | `int?` |

### `data.services[]` element

| Kalit | Tip |
|--------|-----|
| `id` | `int` |
| `service_name` | `String?` |
| `category_id` | `int?` |
| `type_category` | `String?` |
| `price` | `String?` |

### `data.order_images[]` element

| Kalit | Tip |
|--------|-----|
| `id` | `int` |
| `image` | `String?` |
| `created_at` | `String?` |

---

## 3. Ping → Pong

Yuborish:

```json
{ "type": "ping" }
```

Javob:

```json
{ "type": "pong" }
```

---

## To‘liq misol (barcha nested maydonlar bilan)

Quyidagi JSON Flutterda `Map<String, dynamic>` sifatida parse qilinadi; listlar bo‘sh ham bo‘lishi mumkin.

```json
{
  "type": "sos_order_offer",
  "data": {
    "order_id": 42,
    "status": "pending_master",
    "text": "Shina portlangan, yordam kerak",
    "location": "Amir Temur ko'chasi",
    "latitude": "41.311081",
    "longitude": "69.279737",
    "location_source": "gps",
    "priority": "high",
    "order_type": "sos",
    "discount": null,
    "parts_purchase_required": false,
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
      "email": "ali@example.com",
      "avatar": "https://api.example.com/media/avatars/x.jpg"
    },
    "car_data": [
      {
        "id": 3,
        "brand": "Chevrolet",
        "model": "Cobalt",
        "year": 2020,
        "image": "https://api.example.com/media/cars/c1.jpg",
        "category": {
          "id": 12,
          "name": "Yengil avto",
          "type_category": "by_car",
          "parent_id": 2
        }
      }
    ],
    "category_data": [
      {
        "id": 15,
        "name": "Shina montaj",
        "type_category": "by_order",
        "parent_id": 5
      }
    ],
    "services": [
      {
        "id": 88,
        "service_name": "Shina almashtirish",
        "category_id": 15,
        "type_category": "by_order",
        "price": "150000.00"
      }
    ],
    "order_images": [
      {
        "id": 101,
        "image": "https://api.example.com/media/orders/o42_1.jpg",
        "created_at": "2026-04-06T12:00:01+00:00"
      }
    ],
    "master_response_deadline": "2026-04-06T12:02:00+00:00",
    "seconds": 120,
    "sos_offer_index": 0,
    "sos_queue_length": 3,
    "sos_broadcast": true,
    "offered_master_id": 5
  }
}
```

---

## Flutter parse g‘oyasi

```dart
void onMessage(dynamic raw) {
  final map = jsonDecode(raw as String) as Map<String, dynamic>;
  switch (map['type'] as String?) {
    case 'connected':
      break;
    case 'sos_order_offer':
      final data = map['data'] as Map<String, dynamic>;
      final orderId = data['order_id'] as int;
      // ...
      break;
    case 'pong':
      break;
  }
}
```

`latitude` / `longitude` **string** keladi — xaritaga `double.tryParse` qiling.

---

## Manba (backend)

- `apps/order/ws/consumers.py` — yuboriladigan `type` lar
- `apps/order/services/notifications.py` — `build_sos_order_websocket_payload`

To‘liq texnik qisqa qo‘llanma: [ws-sos-master.md](./ws-sos-master.md)
