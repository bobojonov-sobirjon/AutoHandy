import os
from datetime import timedelta
from pathlib import Path

from celery.schedules import crontab


try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    load_dotenv = None


BASE_DIR = Path(__file__).resolve().parent.parent


SECRET_KEY = 'django-insecure-698=9lt4($dou4__kd&*tor4j5kp9g#g2mh8bp37v334-c$8h^'

DEBUG = os.getenv('DJANGO_DEBUG', os.getenv('DEBUG', 'true')).lower() in (
    '1',
    'true',
    'yes',
)

ALLOWED_HOSTS = ["*"]


LOCAL_APPS = [
    'apps.accounts',
    'apps.car',
    'apps.master',
    'apps.order',
    'apps.payment',
    'apps.categories',
    'apps.chat',
]

INSTALLED_APPS = [
    'daphne',
    'django.contrib.sites',
    'jazzmin',
    'nested_admin',
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

ASGI_APPLICATION = 'config.asgi.application'

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


LANGUAGE_CODE = 'en-us'

TIME_ZONE = 'UTC'

USE_I18N = True

USE_TZ = True


STATIC_URL = 'static/'
STATIC_ROOT = os.path.join(BASE_DIR, 'staticfiles')

MEDIA_URL = "/media/"
MEDIA_ROOT = os.getenv('MEDIA_ROOT', '/var/www/media')
API_PUBLIC_BASE_URL = os.getenv('API_PUBLIC_BASE_URL', '').rstrip('/')


LOCALE_PATHS = [
    os.path.join(BASE_DIR, 'locale'),
]

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

CORS_ALLOW_METHODS = [
    'DELETE',
    'GET',
    'OPTIONS',
    'PATCH',
    'POST',
    'PUT',
]

CSRF_COOKIE_SECURE = False
CSRF_COOKIE_HTTPONLY = False
CSRF_COOKIE_SAMESITE = 'Lax'
CSRF_USE_SESSIONS = False
CSRF_COOKIE_NAME = 'csrftoken'

SESSION_COOKIE_SECURE = False
SESSION_COOKIE_SAMESITE = 'Lax'
SESSION_COOKIE_HTTPONLY = True

SECURE_CROSS_ORIGIN_OPENER_POLICY = None

AUTHENTICATION_BACKENDS = (
    'django.contrib.auth.backends.ModelBackend',
)

AUTH_USER_MODEL = 'accounts.CustomUser'

SITE_ID = 1

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

EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
EMAIL_HOST = 'smtp.gmail.com'
EMAIL_PORT = 587
EMAIL_USE_TLS = True
EMAIL_HOST_USER = 'sobirbobojonov2000@gmail.com'
EMAIL_HOST_PASSWORD = 'harntaefuxuvlqqw'
DEFAULT_FROM_EMAIL = 'sobirbobojonov2000@gmail.com'

EMAIL_VERIFICATION_PUBLIC_BASE = os.getenv('EMAIL_VERIFICATION_PUBLIC_BASE', 'https://autohandy.app')
EMAIL_VERIFICATION_TOKEN_HOURS = int(os.getenv('EMAIL_VERIFICATION_TOKEN_HOURS', '48'))

TWILIO_ACCOUNT_SID = os.environ.get('TWILIO_ACCOUNT_SID', '')
TWILIO_AUTH_TOKEN = os.environ.get('TWILIO_AUTH_TOKEN', '')
TWILIO_PHONE_NUMBER = os.environ.get('TWILIO_PHONE_NUMBER', '')
DEFAULT_PHONE_COUNTRY_CODE = os.environ.get('DEFAULT_PHONE_COUNTRY_CODE', '')

SMS_SERVICE = 'twilio'
SMS_SEND_CODE_IN_RESPONSE_IF_FAIL = True
SMS_DEBUG_IN_RESPONSE = os.environ.get('SMS_DEBUG_IN_RESPONSE', '').lower() in ['1', 'true', 'yes']

SMSC_LOGIN = os.environ.get('SMSC_LOGIN', '')
SMSC_PASSWORD = os.environ.get('SMSC_PASSWORD', '')
SMSC_API_URL = 'https://smsc.ru/sys/send.php'

MASTER_OFFER_RESPONSE_MINUTES = int(os.environ.get('MASTER_OFFER_RESPONSE_MINUTES', '15'))
MASTER_NO_DEPARTURE_MINUTES = int(os.environ.get('MASTER_NO_DEPARTURE_MINUTES', '30'))
SOS_NO_DEPARTURE_WARNING_MINUTES = int(os.environ.get('SOS_NO_DEPARTURE_WARNING_MINUTES', '4'))
SOS_NO_DEPARTURE_ACTION_MINUTES = int(os.environ.get('SOS_NO_DEPARTURE_ACTION_MINUTES', '5'))
SOS_MASTER_NO_DEPARTURE_MINUTES = int(
    os.environ.get('SOS_MASTER_NO_DEPARTURE_MINUTES', str(SOS_NO_DEPARTURE_ACTION_MINUTES))
)
SOS_ON_THE_WAY_REMINDER_MINUTES = int(os.environ.get('SOS_ON_THE_WAY_REMINDER_MINUTES', '10'))
SCHEDULED_REMINDER_BEFORE_START_MINUTES = int(os.environ.get('SCHEDULED_REMINDER_BEFORE_START_MINUTES', '60'))
SCHEDULED_NO_START_WARNING_MINUTES = int(os.environ.get('SCHEDULED_NO_START_WARNING_MINUTES', '20'))
SCHEDULED_NO_START_CANCEL_MINUTES = int(os.environ.get('SCHEDULED_NO_START_CANCEL_MINUTES', '30'))
SOS_OFFER_SECONDS_PER_MASTER = int(os.environ.get('SOS_OFFER_SECONDS_PER_MASTER', '420'))
SOS_BROADCAST_RESPONSE_SECONDS = int(os.environ.get('SOS_BROADCAST_RESPONSE_SECONDS', '420'))
EMERGENCY_TIME_ZONE = os.environ.get('EMERGENCY_TIME_ZONE', 'America/Los_Angeles')
EMERGENCY_DAY_MULTIPLIER = float(os.environ.get('EMERGENCY_DAY_MULTIPLIER', '1.3'))
EMERGENCY_NIGHT_MULTIPLIER = float(os.environ.get('EMERGENCY_NIGHT_MULTIPLIER', '1.6'))

MASTER_RATE_WINDOW_DAYS = int(os.environ.get('MASTER_RATE_WINDOW_DAYS', '30'))
# Completion % display: Bayesian prior + soft penalty (few orders → still ~90%+ if mostly completing).
COMPLETION_RATE_BAYESIAN_PRIOR_PERCENT = int(os.environ.get('COMPLETION_RATE_BAYESIAN_PRIOR_PERCENT', '95'))
COMPLETION_RATE_BAYESIAN_PRIOR_ORDERS = int(os.environ.get('COMPLETION_RATE_BAYESIAN_PRIOR_ORDERS', '12'))
COMPLETION_RATE_FAILURE_WEIGHT = float(os.environ.get('COMPLETION_RATE_FAILURE_WEIGHT', '0.25'))
COMPLETION_RATE_CANCEL_WEIGHT = float(os.environ.get('COMPLETION_RATE_CANCEL_WEIGHT', '1.0'))
EMERGENCY_ACCEPTANCE_RATE_MIN = int(os.environ.get('EMERGENCY_ACCEPTANCE_RATE_MIN', '90'))
EMERGENCY_COMPLETION_RATE_MIN = int(os.environ.get('EMERGENCY_COMPLETION_RATE_MIN', '90'))
EMERGENCY_LOW_TIER_DELAY_SECONDS = int(os.environ.get('EMERGENCY_LOW_TIER_DELAY_SECONDS', '120'))
SOS_WEBSOCKET_STALE_SWEEP_SEC = int(os.environ.get('SOS_WEBSOCKET_STALE_SWEEP_SEC', '8'))

CUSTOM_REQUEST_BROADCAST_RADIUS_MILES = float(os.environ.get('CUSTOM_REQUEST_BROADCAST_RADIUS_MILES', '10'))
CUSTOM_REQUEST_MIN_IMAGES = int(os.environ.get('CUSTOM_REQUEST_MIN_IMAGES', '2'))
CUSTOM_REQUEST_MAX_IMAGES = int(os.environ.get('CUSTOM_REQUEST_MAX_IMAGES', '10'))
WORK_COMPLETION_MAX_IMAGES_PER_REQUEST = int(
    os.environ.get('WORK_COMPLETION_MAX_IMAGES_PER_REQUEST', '20')
)

STRIPE_SECRET_KEY = (os.environ.get('STRIPE_SECRET_KEY') or '').strip()
STRIPE_PUBLISHABLE_KEY = (os.environ.get('STRIPE_PUBLISHABLE_KEY') or '').strip()
STRIPE_CHARGE_CURRENCY = (os.environ.get('STRIPE_CHARGE_CURRENCY') or 'usd').strip().lower()
STRIPE_CONNECT_EXTRA_APPLICATION_FEE_BPS = int(os.environ.get('STRIPE_CONNECT_EXTRA_APPLICATION_FEE_BPS', '0'))
STRIPE_CONNECT_ACCOUNT_DEFAULT_COUNTRY = (os.environ.get('STRIPE_CONNECT_ACCOUNT_DEFAULT_COUNTRY') or '').strip().upper()
STRIPE_CONNECT_ACCOUNT_TYPE = (os.environ.get('STRIPE_CONNECT_ACCOUNT_TYPE') or 'custom').strip().lower()
STRIPE_PLATFORM_BUSINESS_URL = (os.environ.get('STRIPE_PLATFORM_BUSINESS_URL') or '').strip()
STRIPE_CONNECT_TEST_BUSINESS_URL = (os.environ.get('STRIPE_CONNECT_TEST_BUSINESS_URL') or 'https://example.com').strip()
STRIPE_PLATFORM_MCC = (os.environ.get('STRIPE_PLATFORM_MCC') or '7538').strip()
STRIPE_PLATFORM_STATEMENT_DESCRIPTOR = (os.environ.get('STRIPE_PLATFORM_STATEMENT_DESCRIPTOR') or 'AUTOHANDY').strip()
STRIPE_PLATFORM_PRODUCT_DESCRIPTION = (
    os.environ.get('STRIPE_PLATFORM_PRODUCT_DESCRIPTION') or 'On-demand automotive services'
).strip()
STRIPE_CONNECT_ONBOARDING_RETURN_URL = (os.environ.get('STRIPE_CONNECT_ONBOARDING_RETURN_URL') or '').strip()
STRIPE_CONNECT_ONBOARDING_REFRESH_URL = (os.environ.get('STRIPE_CONNECT_ONBOARDING_REFRESH_URL') or '').strip()
PROVIDER_PLATFORM_FEE_PERCENT = float(os.environ.get('PROVIDER_PLATFORM_FEE_PERCENT', '10'))
CUSTOMER_SERVICE_FEE_PERCENT_SCHEDULED = float(os.environ.get('CUSTOMER_SERVICE_FEE_PERCENT_SCHEDULED', '4'))
CUSTOMER_PLATFORM_FEE_PERCENT_SCHEDULED = float(os.environ.get('CUSTOMER_PLATFORM_FEE_PERCENT_SCHEDULED', '4'))
EMERGENCY_DISPATCH_FEE_PERCENT = float(os.environ.get('EMERGENCY_DISPATCH_FEE_PERCENT', '6'))
CUSTOMER_SERVICE_FEE_PERCENT_EMERGENCY = float(os.environ.get('CUSTOMER_SERVICE_FEE_PERCENT_EMERGENCY', '5'))
MASTER_PAYOUT_SCHEDULE_NOTE = os.environ.get('MASTER_PAYOUT_SCHEDULE_NOTE', '').strip()
STRIPE_CONNECT_APPLY_PAYOUT_SCHEDULE = os.environ.get(
    'STRIPE_CONNECT_APPLY_PAYOUT_SCHEDULE', 'true'
).lower() in ('1', 'true', 'yes')
STRIPE_CONNECT_ENSURE_PAYOUT_SCHEDULE_ON_ONBOARDING = os.environ.get(
    'STRIPE_CONNECT_ENSURE_PAYOUT_SCHEDULE_ON_ONBOARDING', 'true'
).lower() in ('1', 'true', 'yes')
STRIPE_CONNECT_PAYOUT_INTERVAL = (os.environ.get('STRIPE_CONNECT_PAYOUT_INTERVAL') or 'weekly').strip().lower()
STRIPE_CONNECT_PAYOUT_WEEKLY_ANCHOR = (
    (os.environ.get('STRIPE_CONNECT_PAYOUT_WEEKLY_ANCHOR') or 'monday').strip().lower()
)
_STRIPE_CONNECT_PAYOUT_DELAY_RAW = (os.environ.get('STRIPE_CONNECT_PAYOUT_DELAY_DAYS') or '').strip()
STRIPE_CONNECT_PAYOUT_DELAY_DAYS: str | int | None
if not _STRIPE_CONNECT_PAYOUT_DELAY_RAW:
    STRIPE_CONNECT_PAYOUT_DELAY_DAYS = None
elif _STRIPE_CONNECT_PAYOUT_DELAY_RAW.lower() == 'minimum':
    STRIPE_CONNECT_PAYOUT_DELAY_DAYS = 'minimum'
else:
    try:
        STRIPE_CONNECT_PAYOUT_DELAY_DAYS = int(_STRIPE_CONNECT_PAYOUT_DELAY_RAW)
    except ValueError:
        STRIPE_CONNECT_PAYOUT_DELAY_DAYS = None
STRIPE_CONNECT_PAYOUT_REMINDER_ENABLED = os.getenv(
    'STRIPE_CONNECT_PAYOUT_REMINDER_ENABLED', 'true'
).lower() in ('1', 'true', 'yes')
STRIPE_CONNECT_PAYOUT_REMINDER_HOUR = int(os.getenv('STRIPE_CONNECT_PAYOUT_REMINDER_HOUR', '9'))
STRIPE_CONNECT_PAYOUT_REMINDER_MINUTE = int(os.getenv('STRIPE_CONNECT_PAYOUT_REMINDER_MINUTE', '0'))

CELERY_BROKER_URL = os.getenv('CELERY_BROKER_URL', 'redis://127.0.0.1:6379/0')
CELERY_RESULT_BACKEND = os.getenv('CELERY_RESULT_BACKEND', CELERY_BROKER_URL)
CELERY_TASK_ALWAYS_EAGER = os.getenv('CELERY_TASK_ALWAYS_EAGER', '').lower() in ('1', 'true', 'yes')
CELERY_ACCEPT_CONTENT = ['json']
CELERY_TASK_SERIALIZER = 'json'
CELERY_RESULT_SERIALIZER = 'json'
CELERY_TIMEZONE = TIME_ZONE
CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP = True

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
    'sweep-unpaid-cancellation-penalties': {
        'task': 'apps.order.tasks.sweep_unpaid_cancellation_penalties_task',
        'schedule': crontab(minute='*/5'),
    },
    'notify-masters-payout-day': {
        'task': 'apps.payment.tasks.notify_masters_payout_day_task',
        'schedule': crontab(
            hour=STRIPE_CONNECT_PAYOUT_REMINDER_HOUR,
            minute=STRIPE_CONNECT_PAYOUT_REMINDER_MINUTE,
        ),
    },
}

ORDER_DEADLINE_WARN_MINUTES = int(os.getenv('ORDER_DEADLINE_WARN_MINUTES', '3'))

PUSH_ANDROID_CHANNEL_ID = os.getenv('PUSH_ANDROID_CHANNEL_ID', 'high_importance_channel')

CHAT_WS_MAX_UPLOAD_BYTES = int(os.getenv('CHAT_WS_MAX_UPLOAD_BYTES', str(5 * 1024 * 1024)))

CLIENT_CANCEL_NO_PENALTY_AFTER_ON_THE_WAY_HOURS = int(
    os.getenv('CLIENT_CANCEL_NO_PENALTY_AFTER_ON_THE_WAY_HOURS', '2')
)
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
CLIENT_CANCEL_PENALTY_CHARGE_ENABLED = os.getenv(
    'CLIENT_CANCEL_PENALTY_CHARGE_ENABLED', 'true'
).lower() in ('1', 'true', 'yes')
ORDER_START_JOB_MAX_DISTANCE_M = int(os.getenv('ORDER_START_JOB_MAX_DISTANCE_M', '300'))
ORDER_ETA_MAX_MINUTES = int(os.getenv('ORDER_ETA_MAX_MINUTES', str(72 * 60)))
ORDER_ETA_ASSUMED_SPEED_KMH = float(os.getenv('ORDER_ETA_ASSUMED_SPEED_KMH', '35'))
ORDER_AUTO_CANCEL_NO_SHOW_GRACE_MINUTES = int(os.getenv('ORDER_AUTO_CANCEL_NO_SHOW_GRACE_MINUTES', '40'))
ORDER_DISCOUNT_IS_PERCENT = os.getenv('ORDER_DISCOUNT_IS_PERCENT', 'false').lower() in (
    '1',
    'true',
    'yes',
)
MASTER_FREE_CANCELLATIONS_PER_MONTH = int(os.getenv('MASTER_FREE_CANCELLATIONS_PER_MONTH', '3'))
MASTER_SCHEDULE_MIN_COVERAGE_DAYS_DEFAULT = int(os.getenv('MASTER_SCHEDULE_MIN_COVERAGE_DAYS_DEFAULT', '14'))

if os.name == 'nt' and not os.environ.get('DJANGO_LOG_FILE'):
    _DJANGO_LOG_FILE = str(BASE_DIR / 'logs' / 'django.log')
else:
    _DJANGO_LOG_FILE = os.environ.get(
        'DJANGO_LOG_FILE',
        '/var/www/AutoHandy/logs/django.log',
    )


def _log_file_is_writable(path: str) -> bool:
    try:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(path, 'a', encoding='utf-8'):
            pass
        return True
    except OSError:
        return False


_DJANGO_LOG_LEVEL = os.environ.get(
    'DJANGO_LOG_LEVEL',
    'DEBUG' if DEBUG else 'INFO',
)

_LOG_FALLBACK_FILE = str(BASE_DIR / 'logs' / 'django.log')
_DJANGO_LOG_EFFECTIVE = _DJANGO_LOG_FILE
if not _log_file_is_writable(_DJANGO_LOG_EFFECTIVE):
    if _LOG_FALLBACK_FILE != _DJANGO_LOG_EFFECTIVE and _log_file_is_writable(_LOG_FALLBACK_FILE):
        _DJANGO_LOG_EFFECTIVE = _LOG_FALLBACK_FILE
        _use_file_handler = True
    else:
        _DJANGO_LOG_EFFECTIVE = _DJANGO_LOG_FILE
        _use_file_handler = False
else:
    _use_file_handler = True

_LOG_HANDLERS: dict[str, dict] = {
    'console': {
        'level': _DJANGO_LOG_LEVEL,
        'class': 'logging.StreamHandler',
        'formatter': 'verbose',
    },
}
_ROOT_HANDLER_NAMES = ['console']
if _use_file_handler:
    _LOG_HANDLERS['file'] = {
        'level': 'DEBUG',
        'class': 'logging.handlers.RotatingFileHandler',
        'filename': _DJANGO_LOG_EFFECTIVE,
        'maxBytes': int(os.environ.get('DJANGO_LOG_MAX_BYTES', str(50 * 1024 * 1024))),
        'backupCount': int(os.environ.get('DJANGO_LOG_BACKUP_COUNT', '10')),
        'formatter': 'verbose',
    }
    _ROOT_HANDLER_NAMES = ['file', 'console']

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '{levelname} {asctime} {name} {message}',
            'style': '{',
            'datefmt': '%Y-%m-%d %H:%M:%S',
        },
    },
    'handlers': _LOG_HANDLERS,
    'loggers': {
        'celery.utils.functional': {
            'level': 'WARNING',
            'propagate': True,
        },
        'asyncio': {
            'level': 'WARNING',
            'propagate': True,
        },
    },
    'root': {
        'handlers': _ROOT_HANDLER_NAMES,
        'level': _DJANGO_LOG_LEVEL,
    },
}

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
        {'name': 'Stripe — Driver', 'description': 'Driver (order owner): Stripe Customer, client saved cards, order card attach, checkout preview.'},
        {'name': 'Stripe — Master', 'description': 'Master: Connect link/onboarding, balance, checkout history (Stripe Connect payouts).'},
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
