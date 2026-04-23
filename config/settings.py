import os
from datetime import timedelta
from pathlib import Path

from celery.schedules import crontab


# Load environment variables from .env file
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    load_dotenv = None
    
    
# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent


# Quick-start development settings - unsuitable for production
# See https://docs.djangoproject.com/en/5.2/howto/deployment/checklist/

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = 'django-insecure-698=9lt4($dou4__kd&*tor4j5kp9g#g2mh8bp37v334-c$8h^'

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = True

ALLOWED_HOSTS = ["*"]


# Application definition

LOCAL_APPS = [
    'apps.accounts',
    'apps.car',
    'apps.master',
    'apps.order',
    'apps.categories',
    'apps.chat',
]

INSTALLED_APPS = [
    'daphne',  # Must be first for WebSocket support
    'django.contrib.sites',
    'jazzmin',  # Admin theme — must be before django.contrib.admin
    'nested_admin',  # Master admin nested inlines; templates: nesting/admin/inlines/...
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'rest_framework',
    'rest_framework_simplejwt',
    'drf_spectacular',
    'corsheaders',
    'django_filters',
    'channels',
    *LOCAL_APPS,
]

LOCAL_MIDDLEWARE = [
    'config.middleware.middleware.JsonErrorResponseMiddleware',
    'config.middleware.middleware.Custom404Middleware',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    *LOCAL_MIDDLEWARE,
]

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [os.path.join(BASE_DIR, 'templates')],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'

# ASGI Application for WebSocket support
ASGI_APPLICATION = 'config.asgi.application'

# Channel layers: InMemory = one Python process only. HTTP and WebSocket must hit the SAME process
# (e.g. one Daphne on :8001 for both). If API runs on runserver :8000 and WS on Daphne :8001, groups
# do not match — use Redis (CHANNEL_LAYER_REDIS or REDIS_URL starting with redis://).
_CHANNEL_REDIS = os.getenv('CHANNEL_LAYER_REDIS', '') or os.getenv('REDIS_URL', '')
if _CHANNEL_REDIS.startswith('redis'):
    CHANNEL_LAYERS = {
        'default': {
            'BACKEND': 'channels_redis.core.RedisChannelLayer',
            'CONFIG': {'hosts': [_CHANNEL_REDIS]},
        },
    }
else:
    CHANNEL_LAYERS = {
        'default': {'BACKEND': 'channels.layers.InMemoryChannelLayer'},
    }


# Database
# https://docs.djangoproject.com/en/5.2/ref/settings/#databases

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': os.getenv('DB_NAME', 'autohandy'),
        'USER': os.getenv('DB_USER', 'postgres'),
        'PASSWORD': os.getenv('DB_PASSWORD', '0576'),
        'HOST': os.getenv('DB_HOST', 'localhost'),
        'PORT': os.getenv('DB_PORT', '5432'),
    }
}


# Password validation
# https://docs.djangoproject.com/en/5.2/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]


# Internationalization
# https://docs.djangoproject.com/en/5.2/topics/i18n/

LANGUAGE_CODE = 'en-us'

TIME_ZONE = 'UTC'

USE_I18N = True

USE_TZ = True


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/5.2/howto/static-files/

STATIC_URL = 'static/'
STATIC_ROOT = os.path.join(BASE_DIR, 'staticfiles')

MEDIA_URL = "/media/"
# Production uchun /var/www/media, development uchun local media folder
MEDIA_ROOT = os.getenv('MEDIA_ROOT', '/var/www/media')
# SOS WebSocket / Celery: /media/... ni to‘liq URL qilish (so‘ngida slash yo‘q). Masalan: http://localhost:8001
API_PUBLIC_BASE_URL = os.getenv('API_PUBLIC_BASE_URL', '').rstrip('/')


LOCALE_PATHS = [
    os.path.join(BASE_DIR, 'locale'),
]

# Default primary key field type
# https://docs.djangoproject.com/en/5.2/ref/settings/#default-auto-field

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'


REST_FRAMEWORK = {
    'DEFAULT_RENDERER_CLASSES': [
        'rest_framework.renderers.JSONRenderer',
        'rest_framework.renderers.BrowsableAPIRenderer',
    ],
    'DEFAULT_FILTER_BACKENDS': ['django_filters.rest_framework.DjangoFilterBackend'],
    'DEFAULT_AUTHENTICATION_CLASSES': (
        'rest_framework_simplejwt.authentication.JWTAuthentication',
    ),
    "DEFAULT_PARSER_CLASSES": (
        "rest_framework.parsers.JSONParser",
        "rest_framework.parsers.FormParser",
        "rest_framework.parsers.MultiPartParser",
        "rest_framework.parsers.FileUploadParser",
    ),
    'DEFAULT_PERMISSION_CLASSES': [
        'rest_framework.permissions.IsAuthenticated',
    ],
    "PAGE_SIZE": 100,
    'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.LimitOffsetPagination',
    'DEFAULT_SCHEMA_CLASS': 'drf_spectacular.openapi.AutoSchema',
}

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(days=7),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=1),
}

CSRF_TRUSTED_ORIGINS = [
    "http://localhost:3000",
    "http://localhost:8000",
    "http://127.0.0.1:5173",
    "http://31.128.43.149:6060",
    "http://31.128.43.149",
    "https://31.128.43.149:6060",
    "https://31.128.43.149",
]

CORS_ALLOWED_ORIGINS = [
    "http://localhost:3000",
    "http://localhost:8000",
    "http://127.0.0.1:5173",
    "http://31.128.43.149:6060",
    "http://31.128.43.149",
    "https://31.128.43.149:6060",
    "https://31.128.43.149",
]

CORS_ALLOW_ALL_ORIGINS = True
CORS_ALLOW_CREDENTIALS = True
CORS_EXPOSE_HEADERS = ['Content-Type', 'X-CSRFToken']

# CORS Headers
CORS_ALLOW_HEADERS = [
    'accept',
    'accept-encoding',
    'authorization',
    'content-type',
    'dnt',
    'origin',
    'user-agent',
    'x-csrftoken',
    'x-requested-with',
    'cache-control',
    'pragma',
]

# CORS Methods
CORS_ALLOW_METHODS = [
    'DELETE',
    'GET',
    'OPTIONS',
    'PATCH',
    'POST',
    'PUT',
]

# CSRF Settings for production
CSRF_COOKIE_SECURE = False  # Set True if using HTTPS
CSRF_COOKIE_HTTPONLY = False
CSRF_COOKIE_SAMESITE = 'Lax'
CSRF_USE_SESSIONS = False
CSRF_COOKIE_NAME = 'csrftoken'

# Session Settings
SESSION_COOKIE_SECURE = False  # Set True if using HTTPS
SESSION_COOKIE_SAMESITE = 'Lax'
SESSION_COOKIE_HTTPONLY = True

# Security Settings for development/production
SECURE_CROSS_ORIGIN_OPENER_POLICY = None

AUTHENTICATION_BACKENDS = (
    'django.contrib.auth.backends.ModelBackend',
)

AUTH_USER_MODEL = 'accounts.CustomUser'

SITE_ID = 1

# django-jazzmin — https://django-jazzmin.readthedocs.io/
JAZZMIN_SETTINGS = {
    'site_title': 'AutoHandy Admin',
    'site_header': 'AutoHandy',
    'site_brand': 'AutoHandy',
    'welcome_sign': 'AutoHandy administration',
    'copyright': 'AutoHandy',
    'search_model': ['accounts.CustomUser', 'auth.Group'],
    'user_avatar': None,
    'topmenu_links': [
        {'name': 'Admin home', 'url': 'admin:index', 'permissions': ['auth.view_user']},
        {'name': 'API docs', 'url': '/docs/', 'new_window': True},
    ],
    'show_sidebar': True,
    'navigation_expanded': False,
    'hide_apps': [],
    'hide_models': [],
    # Sidebar: Order ilovasi ichida modellarni alfavit emas, ish jarayoniga mos tartibda
    'order_with_respect_to': [
        'order.order',
        'order.standardorder',
        'order.sosorder',
        'order.orderservice',
        'order.review',
        'order.rating',
        'order.userrating',
        'order.masterordercancellation',
    ],
    'icons': {
        'auth': 'fas fa-users-cog',
        'auth.user': 'fas fa-user',
        'auth.Group': 'fas fa-users',
        'accounts': 'fas fa-user-circle',
        'accounts.customuser': 'fas fa-user',
        'sites': 'fas fa-globe',
    },
    'default_icon_parents': 'fas fa-folder',
    'default_icon_children': 'fas fa-circle',
    'related_modal_active': False,
    'custom_css': None,
    'custom_js': None,
    'use_google_fonts_cdn': True,
    'show_ui_builder': False,
    'changeform_format': 'horizontal_tabs',
    'changeform_format_overrides': {
        'auth.user': 'collapsible',
        'auth.group': 'vertical_tabs',
    },
}

JAZZMIN_UI_TWEAKS = {
    'navbar_small_text': False,
    'footer_small_text': False,
    'body_small_text': False,
    'brand_small_text': False,
    'brand_colour': 'navbar-dark',
    'accent': 'accent-teal',
    'navbar': 'navbar-dark',
    'navbar_fixed': False,
    'layout_boxed': False,
    'footer_fixed': False,
    'sidebar_fixed': True,
    'sidebar': 'sidebar-dark-primary',
    'theme': 'default',
    'dark_mode_theme': None,
    'button_classes': {
        'primary': 'btn-primary',
        'secondary': 'btn-secondary',
    },
}

# Email Configuration
EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
EMAIL_HOST = 'smtp.gmail.com'  # Change to your SMTP server
EMAIL_PORT = 587
EMAIL_USE_TLS = True
EMAIL_HOST_USER = 'sobirbobojonov2000@gmail.com'
EMAIL_HOST_PASSWORD = 'harntaefuxuvlqqw'
DEFAULT_FROM_EMAIL = 'sobirbobojonov2000@gmail.com'

# Public URL prefix for email verification links (no trailing slash). Example: https://app.yourdomain.com
EMAIL_VERIFICATION_PUBLIC_BASE = os.getenv('EMAIL_VERIFICATION_PUBLIC_BASE', 'https://autohandy.app')
EMAIL_VERIFICATION_TOKEN_HOURS = int(os.getenv('EMAIL_VERIFICATION_TOKEN_HOURS', '48'))

# Twilio SMS (primary)
TWILIO_ACCOUNT_SID = os.environ.get('TWILIO_ACCOUNT_SID', '')
TWILIO_AUTH_TOKEN = os.environ.get('TWILIO_AUTH_TOKEN', '')
TWILIO_PHONE_NUMBER = os.environ.get('TWILIO_PHONE_NUMBER', '')  # E.164 e.g. +1234567890
DEFAULT_PHONE_COUNTRY_CODE = os.environ.get('DEFAULT_PHONE_COUNTRY_CODE', '')  # e.g. 998 or 1

# SMS service settings
SMS_SERVICE = 'twilio'  # Primary: twilio
SMS_SEND_CODE_IN_RESPONSE_IF_FAIL = True  # If Twilio fails, still return sms_code in response (for dev/testing)
SMS_DEBUG_IN_RESPONSE = os.environ.get('SMS_DEBUG_IN_RESPONSE', '').lower() in ['1', 'true', 'yes']  # expose sms_debug in response (dev only)

# Legacy SMSC.ru (optional fallback, kept for reference)
SMSC_LOGIN = os.environ.get('SMSC_LOGIN', '')
SMSC_PASSWORD = os.environ.get('SMSC_PASSWORD', '')
SMSC_API_URL = 'https://smsc.ru/sys/send.php'

# Master must accept/decline assigned order within this window (minutes); then auto-decline.
MASTER_OFFER_RESPONSE_MINUTES = int(os.environ.get('MASTER_OFFER_RESPONSE_MINUTES', '15'))
# Legacy sequential SOS ring (unused for broadcast); kept for old clients reading payload fields.
SOS_OFFER_SECONDS_PER_MASTER = int(os.environ.get('SOS_OFFER_SECONDS_PER_MASTER', '30'))
# SOS broadcast: all in-zone masters in queue get the offer; shared countdown until auto-reject.
SOS_BROADCAST_RESPONSE_SECONDS = int(os.environ.get('SOS_BROADCAST_RESPONSE_SECONDS', '120'))
# Fallback when Celery countdown/beat is broken (e.g. Windows prefork): while masters stay on SOS WS,
# run expire_stale_master_offers at most once per this many seconds (per ASGI process). 0 = off.
SOS_WEBSOCKET_STALE_SWEEP_SEC = int(os.environ.get('SOS_WEBSOCKET_STALE_SWEEP_SEC', '8'))

# Custom request: broadcast pending jobs to masters within this radius (miles); master offer POST uses same limit.
CUSTOM_REQUEST_BROADCAST_RADIUS_MILES = float(os.environ.get('CUSTOM_REQUEST_BROADCAST_RADIUS_MILES', '10'))
CUSTOM_REQUEST_MIN_IMAGES = int(os.environ.get('CUSTOM_REQUEST_MIN_IMAGES', '2'))
CUSTOM_REQUEST_MAX_IMAGES = int(os.environ.get('CUSTOM_REQUEST_MAX_IMAGES', '10'))
# POST /api/order/<id>/work-completion-image/ — max files per request (multipart `images` repeated).
WORK_COMPLETION_MAX_IMAGES_PER_REQUEST = int(
    os.environ.get('WORK_COMPLETION_MAX_IMAGES_PER_REQUEST', '20')
)

# Celery (install redis and run: celery -A config worker -l info && celery -A config beat -l info)
CELERY_BROKER_URL = os.getenv('CELERY_BROKER_URL', 'redis://127.0.0.1:6379/0')
CELERY_RESULT_BACKEND = os.getenv('CELERY_RESULT_BACKEND', CELERY_BROKER_URL)
CELERY_TASK_ALWAYS_EAGER = os.getenv('CELERY_TASK_ALWAYS_EAGER', '').lower() in ('1', 'true', 'yes')
CELERY_ACCEPT_CONTENT = ['json']
CELERY_TASK_SERIALIZER = 'json'
CELERY_RESULT_SERIALIZER = 'json'
CELERY_TIMEZONE = TIME_ZONE
# Celery 6: startup broker retries (silences deprecation when True).
CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP = True

# Beat: run `celery -A config.celery beat -l info` alongside the worker.
# Standard (and non-queue SOS) pending orders use master_response_deadline = now + MASTER_OFFER_RESPONSE_MINUTES.
# If the master does not accept/decline before that time, expire_stale_master_offers marks the order rejected
# and clears master (same outcome as POST …/decline/). Per-order ETA tasks also call expire_master_offer_for_order;
# this schedule is the time-based safety net if a worker missed an ETA.
CELERY_BEAT_SCHEDULE = {
    'expire-stale-master-offers': {
        'task': 'apps.order.tasks.expire_stale_master_offers_task',
        'schedule': crontab(minute='*'),
    },
    'warn-upcoming-order-deadlines': {
        'task': 'apps.order.tasks.warn_upcoming_order_deadlines_task',
        'schedule': crontab(minute='*'),
    },
    'sweep-penalty-free-unlock': {
        'task': 'apps.order.tasks.sweep_client_penalty_free_unlock_task',
        'schedule': crontab(minute='*/5'),
    },
    'sweep-auto-cancel-master-no-show': {
        'task': 'apps.order.tasks.sweep_auto_cancel_master_no_show_task',
        'schedule': crontab(minute='*'),
    },
}

# Push warnings before automatic deadlines (minutes).
ORDER_DEADLINE_WARN_MINUTES = int(os.getenv('ORDER_DEADLINE_WARN_MINUTES', '3'))

# WebSocket chat upload limit (base64 decoded bytes).
CHAT_WS_MAX_UPLOAD_BYTES = int(os.getenv('CHAT_WS_MAX_UPLOAD_BYTES', str(5 * 1024 * 1024)))

# After master is "on the way", client may cancel without penalty after this many hours (still on the way).
CLIENT_CANCEL_NO_PENALTY_AFTER_ON_THE_WAY_HOURS = int(
    os.getenv('CLIENT_CANCEL_NO_PENALTY_AFTER_ON_THE_WAY_HOURS', '2')
)
# Client cancellation fees (see client_cancellation_snapshot in order status_workflow).
CLIENT_CANCEL_GRACE_MINUTES_AFTER_ACCEPT = int(
    os.getenv('CLIENT_CANCEL_GRACE_MINUTES_AFTER_ACCEPT', '10')
)
CLIENT_CANCEL_PENALTY_PERCENT_ACCEPTED_LATE = int(
    os.getenv('CLIENT_CANCEL_PENALTY_PERCENT_ACCEPTED_LATE', '10')
)
CLIENT_CANCEL_PENALTY_PERCENT_ON_THE_WAY = int(
    os.getenv('CLIENT_CANCEL_PENALTY_PERCENT_ON_THE_WAY', '15')
)
CLIENT_CANCEL_PENALTY_PERCENT_ARRIVED = int(
    os.getenv('CLIENT_CANCEL_PENALTY_PERCENT_ARRIVED', '25')
)
# Master "Start job" (in_progress): must be within this distance (meters) of order coordinates after arrived.
ORDER_START_JOB_MAX_DISTANCE_M = int(os.getenv('ORDER_START_JOB_MAX_DISTANCE_M', '300'))
# Max minutes master may declare for ETA when marking on_the_way (default 72h).
ORDER_ETA_MAX_MINUTES = int(os.getenv('ORDER_ETA_MAX_MINUTES', str(72 * 60)))
# Avg speed (km/h) for auto ETA: order GPS → master workshop/user GPS when status=on_the_way without manual eta.
ORDER_ETA_ASSUMED_SPEED_KMH = float(os.getenv('ORDER_ETA_ASSUMED_SPEED_KMH', '35'))
# Auto-cancel if the master did not arrive by (estimated_arrival_at + grace minutes).
ORDER_AUTO_CANCEL_NO_SHOW_GRACE_MINUTES = int(os.getenv('ORDER_AUTO_CANCEL_NO_SHOW_GRACE_MINUTES', '40'))
# If True: order.discount in 0..100 is a percent of subtotal; above 100 = fixed amount. If False: always fixed amount.
ORDER_DISCOUNT_IS_PERCENT = os.getenv('ORDER_DISCOUNT_IS_PERCENT', 'false').lower() in (
    '1',
    'true',
    'yes',
)
# Master cancel: first 3 cancellations in a calendar month do not cap schedule horizon; from the 4th on,
# see master_schedule_forward_horizon_days in apps.order.services.status_workflow.
MASTER_FREE_CANCELLATIONS_PER_MONTH = int(os.getenv('MASTER_FREE_CANCELLATIONS_PER_MONTH', '3'))
# When the master is under no cancellation-policy cap, bulk schedule must cover this many days from today.
MASTER_SCHEDULE_MIN_COVERAGE_DAYS_DEFAULT = int(os.getenv('MASTER_SCHEDULE_MIN_COVERAGE_DAYS_DEFAULT', '14'))

# DRF Spectacular Configuration
SPECTACULAR_SETTINGS = {
    'TITLE': 'AutoHandy APIs',
    'DESCRIPTION': 'AutoHandy Apies - JWT Authentication Required',
    'VERSION': 'v1',
    'SERVE_INCLUDE_SCHEMA': False,
    'COMPONENT_SPLIT_REQUEST': True,
    'SCHEMA_PATH_PREFIX': '/api/',
    'SWAGGER_UI_SETTINGS': {
        'deepLinking': True,
        'persistAuthorization': True,
        'displayOperationId': True,
    },
    'SWAGGER_UI_FAVICON_HREF': '/static/favicon.ico',
    'REDOC_UI_SETTINGS': {
        'hideDownloadButton': True,
        'hideHostname': True,
    },
    'SERVERS': [
        {'url': 'http://217.114.11.249:7002/', 'description': 'Production server'},
        {'url': 'http://localhost:8001', 'description': 'Development server'},
    ],
    'TAGS': [
        {'name': 'Authentication', 'description': 'User authentication and authorization'},
        {'name': 'Cars', 'description': 'Car management endpoints'},
        {'name': 'Masters', 'description': 'Master/service provider endpoints'},
        {'name': 'Order (Driver) — Create', 'description': 'POST /standard/ (alias /scheduled/), POST /sos/, GET /nearby-masters/'},
        {'name': 'Order (Driver) — Time slots', 'description': 'GET /available-slots/'},
        {'name': 'Order (Driver) — My orders', 'description': 'GET / (list), GET /by-user/'},
        {'name': 'Order (Driver) — Reviews', 'description': 'POST /reviews/create/'},
        {'name': 'Order (Driver) — Legacy', 'description': 'POST /add-services/, GET /services-list/, POST /add-master/'},
        {'name': 'Order — Details (Driver & Master)', 'description': 'GET/PUT/PATCH/DELETE /{id}/'},
        {'name': 'Order — Status (Driver & Master)', 'description': 'POST /{id}/status/'},
        {'name': 'Order (Master) — Available & accept', 'description': 'GET /available/, POST /{id}/accept/, POST /{id}/decline/'},
        {'name': 'Order (Master) — My orders', 'description': 'GET /by-master/'},
        {'name': 'Order (Master) — Complete', 'description': 'POST /{id}/complete/'},
        {'name': 'Categories', 'description': 'Category management endpoints'},
        {'name': 'System', 'description': 'Health check, app version'},
        {'name': 'FAQ', 'description': 'Frequently asked questions'},
        {'name': 'User Profile', 'description': 'User profile and registration'},
    ],
    'PREPROCESSING_HOOKS': [],
    'POSTPROCESSING_HOOKS': [],
    'GENERIC_ADDITIONAL_PROPERTIES': None,
    'CAMPAIGN': None,
    'CONTACT': {
        'name': 'API Support',
        'email': 'contact@snippets.local',
    },
    'LICENSE': {
        'name': 'BSD License',
    },
}