# AutoHandy - Система аутентификации по SMS

## Описание проекта

AutoHandy - это Django REST API проект для аутентификации пользователей через SMS-коды. Поддерживает номера телефонов Узбекистана и России.

## Возможности

- ✅ **SMS аутентификация** - вход через SMS-код
- ✅ **Поддержка номеров** - Узбекистан (+998) и Россия (+7)
- ✅ **JWT токены** - безопасная аутентификация
- ✅ **Автоматическое создание пользователей**
- ✅ **Swagger документация** - интерактивная API документация
- ✅ **Валидация номеров** - проверка формата номеров
- ✅ **Кэширование** - оптимизация производительности

## Технологии

- **Django 5.2.6** - веб-фреймворк
- **Django REST Framework** - API фреймворк
- **JWT** - аутентификация
- **SMSC.ru** - SMS сервис
- **Swagger/OpenAPI** - документация API
- **SQLite** - база данных (по умолчанию)

## Установка

### 1. Клонирование репозитория
```bash
git clone <repository-url>
cd AutoHandy
```

### 2. Создание виртуального окружения
```bash
python -m venv env
# Windows
env\Scripts\activate
# Linux/Mac
source env/bin/activate
```

### 3. Установка зависимостей
```bash
pip install -r requirements.txt
```

### 4. Настройка переменных окружения
Создайте файл `.env` в корне проекта:
```env
DEBUG=True
SECRET_KEY=your-secret-key
SMSC_LOGIN=your-smsc-login
SMSC_PASSWORD=your-smsc-password
```

### 5. Применение миграций
```bash
python manage.py migrate
```

### 6. Создание суперпользователя
```bash
python manage.py createsuperuser
```

### 7. Запуск сервера
```bash
python manage.py runserver
```

## API Endpoints

### 1. Login (отправка SMS кода)
**POST** `/api/auth/login/`

Отправляет 4-значный SMS код на номер телефона.

**Request:**
```json
{
    "phone_number": "7914180518"
}
```

**Response:**
```json
{
    "success": true,
    "message": "SMS код отправлен",
    "phone": "7914180518",
    "user_exists": false
}
```

### 2. Check SMS Code (проверка SMS кода)
**POST** `/api/auth/check-sms-code/`

Проверяет SMS код и выдает JWT токен.

**Request:**
```json
{
    "phone_number": "7914180518",
    "sms_code": "1234"
}
```

**Response:**
```json
{
    "success": true,
    "message": "Успешный вход",
    "user": {
        "id": 1,
        "phone_number": "7914180518",
        "first_name": "User_RU",
        "last_name": "RU_914180518",
        "email": "7914180518@example.com",
        "is_verified": true,
        "created_at": "2024-01-01T12:00:00Z"
    },
    "user_created": true,
    "tokens": {
        "access": "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9...",
        "refresh": "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9..."
    }
}
```

## Поддерживаемые форматы номеров

### Узбекские номера:
- `998XXXXXXXXX` (12 цифр)
- `+998XXXXXXXXX` (12 цифр)

### Российские номера:
- `8XXXXXXXXXX` → `7XXXXXXXXXX` (11 цифр)
- `+7XXXXXXXXXX` → `7XXXXXXXXXX` (11 цифр)
- `7XXXXXXXXXX` (11 цифр)

## Swagger документация

После запуска сервера документация доступна по адресу:
- **Swagger UI**: http://127.0.0.1:8000/swagger/
- **ReDoc**: http://127.0.0.1:8000/redoc/

## Production Setup (Server Configuration)

### ⚠️ ВАЖНО: Cache Configuration для Production

**Проблема:** Localda код работает, но на сервере SMS код не находится.

**Причина:** Django работает с несколькими workers (Gunicorn), и `LocMemCache` не делится между процессами.

**Решение:**

✅ **AUTO:** Production muhitida (DEBUG=False) DatabaseCache avtomatik ishlaydi! Hech qanday sozlash kerak emas.

Yoki manual qilish:

1. **Database Cache (Простой вариант):**
```bash
# В .env файле на сервере:
USE_DB_CACHE=True

# Создать cache table:
python manage.py createcachetable

# Перезапустить сервер:
sudo systemctl restart gunicorn
```

2. **Redis Cache (Рекомендуется для high load):**
```bash
# Установить Redis:
sudo apt install redis-server

# В .env файле:
USE_REDIS_CACHE=True
REDIS_URL=redis://127.0.0.1:6379/1

# Установить пакеты:
pip install -r requirements.txt

# Перезапустить сервер:
sudo systemctl restart gunicorn
```

Подробности в файле `SERVERDA_NIMA_QILISH_KERAK.md`

## Настройка SMS сервиса

### SMSC.ru
1. Зарегистрируйтесь на https://smsc.ru
2. Получите API ID и пароль
3. Добавьте в настройки:
```python
SMSC_LOGIN = 'your-login'
SMSC_PASSWORD = 'your-password'
```

## Структура проекта

```
AutoHandy/
├── apps/
│   └── accounts/          # Приложение аутентификации
│       ├── models.py      # Модели пользователей
│       ├── views.py       # API представления
│       ├── serializers.py # Сериализаторы
│       ├── services.py    # Бизнес-логика
│       └── urls.py        # URL маршруты
├── config/                # Настройки Django
│   ├── settings.py        # Основные настройки
│   ├── urls.py           # Главные URL
│   └── wsgi.py           # WSGI конфигурация
├── requirements.txt       # Зависимости
├── manage.py             # Управление Django
└── README.md             # Документация
```

## Тестирование

### Тест с curl
```bash
# Отправка SMS кода
curl -X POST http://127.0.0.1:8000/api/auth/login/ \
  -H "Content-Type: application/json" \
  -d '{"phone_number": "+998914180518"}'

# Проверка SMS кода
curl -X POST http://127.0.0.1:8000/api/auth/check-sms-code/ \
  -H "Content-Type: application/json" \
  -d '{"phone_number": "+998914180518", "sms_code": "1234"}'
```

## Разработка

### Запуск в режиме разработки
```bash
python manage.py runserver --settings=config.settings
```

### Создание миграций
```bash
python manage.py makemigrations
python manage.py migrate
```

### Сбор статических файлов
```bash
python manage.py collectstatic
```

## Лицензия

Этот проект распространяется под лицензией MIT.

## Автор

Создано для проекта AutoHandy.

## Поддержка

Если у вас есть вопросы или проблемы, создайте issue в репозитории.
