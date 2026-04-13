# Celery: ishga tushirish (AutoHandy)

Loyihada Celery **broker sifatida Redis** ishlatadi (`CELERY_BROKER_URL`). Vaqtli vazifalar (SOS/custom broadcast, master offer muddati, client penalty-free unlock) worker + Beat bilan to‘liq ishlaydi.

## Talablar

1. **Redis** — odatda `127.0.0.1:6379` (Docker yoki mahalliy o‘rnatma).
2. **Python paketlar** — `requirements.txt` ichida: `celery`, `redis` va boshqalar.
3. **Loyiha ildizidan** ishga tushiring (bu yerda `manage.py` joylashgan papka).

## Muhit o‘zgaruvchilari (ixtiyoriy)

| O‘zgaruvchi | Default | Ma’nosi |
|-------------|---------|---------|
| `CELERY_BROKER_URL` | `redis://127.0.0.1:6379/0` | Broker va natija backend |
| `CELERY_RESULT_BACKEND` | broker bilan bir xil | Task natijalari |
| `CELERY_TASK_ALWAYS_EAGER` | `false` | `true` bo‘lsa tasklar sinxron bajariladi (Redis **kerak emas**, lekin prod uchun **tavsiya etilmaydi**) |

Windows PowerShell misoli:

```powershell
$env:CELERY_BROKER_URL = "redis://127.0.0.1:6379/0"
```

## Redis ni ishga tushirish (qisqa)

Docker misoli:

```bash
docker run -d --name redis -p 6379:6379 redis:7-alpine
```

Redis ishlayotganini tekshirish: `redis-cli ping` → `PONG`.

## Celery Worker

Loyiha ildizidan (masalan `D:\Projects\Mobile Backend APPS\AutoHandy`):

```bash
celery -A config.celery worker -l info
```

- **Windows:** `config/celery.py` da avtomatik **`solo` pool** (`prefork` muammolarini oldini olish uchun). Bitta jarayon, `concurrency=1`.
- **Linux/macOS:** kerak bo‘lsa aniq pool: `celery -A config.celery worker -l info -P prefork`

## Celery Beat (jadval bo‘yicha vazifalar)

Beat **worker dan alohida** jarayonda ishlamoq kerak (ikkinchi terminal):

```bash
celery -A config.celery beat -l info
```

Hozirgi `CELERY_BEAT_SCHEDULE` (`config/settings.py`):

| Vazifa | Chastota | Ma’nosi |
|--------|----------|---------|
| `expire_stale_master_offers_task` | har daqiqa | `master_response_deadline` o‘tgan pending takliflar (standard / SOS broadcast) |
| `sweep_client_penalty_free_unlock_task` | har 5 daqiqa | mijoz “yo‘lda” N soatdan keyin jarimasiz bekor qilish oynasi |

## Bir vaqtda ishga tushirish

Ikkita terminal:

1. `celery -A config.celery worker -l info`
2. `celery -A config.celery beat -l info`

Yoki bir terminalda (faqat ishlab chiqish uchun qulay):

```bash
# Linux/macOS (GNU parallel emas — ikkita fon jarayon)
celery -A config.celery worker -l info &
celery -A config.celery beat -l info
```

Windows da odatda **ikki alohida PowerShell oynasi** ishlatiladi.

## Django / ASGI bilan

- **HTTP + WebSocket** — `daphne`/`uvicorn` alohida ishlaydi; Celery alohida.
- Redis broker band bo‘lsa, kodda ba’zi joylarda task `delay()` o‘rniga **inline fallback** bo‘lishi mumkin (masalan custom-request broadcast) — lekin muddatli expire va beat vazifalari uchun **worker + beat + Redis** tavsiya etiladi.

## Redis siz tez tekshirish (faqat dev)

```powershell
$env:CELERY_TASK_ALWAYS_EAGER = "true"
python manage.py runserver
```

Bu rejimda Celery navbatidan foydolanilmaydi; production da ishlatmang.

## Tekshirish

Worker logida task nomlari ko‘rinadi. Beat ishlayotgan bo‘lsa, har daqiqa `expire_stale_master_offers_task` chaqirilishini kutiladi.

Qisqa debug task (agar kerak bo‘lsa, `config/celery.py` da `debug_task` bor):

```bash
celery -A config.celery call config.celery.debug_task
```

---

**Ilova moduli:** `config.celery` (`app = Celery('autohandy')`).  
**Sozlamalar:** `config/settings.py` → `CELERY_*`, `CELERY_BEAT_SCHEDULE`.
