"""Django settings for the Solar Hub backend.

All environment-specific values are read from a `.env` file (django-environ);
nothing secret is hard-coded. See `.env.example` for the full list.
"""

from datetime import timedelta
from pathlib import Path

import environ

BASE_DIR = Path(__file__).resolve().parent.parent

env = environ.Env()
environ.Env.read_env(BASE_DIR / ".env")

# --- Core ---------------------------------------------------------------
SECRET_KEY = env("DJANGO_SECRET_KEY")
DEBUG = env.bool("DEBUG", default=False)
ALLOWED_HOSTS = env.list("ALLOWED_HOSTS", default=["*"])

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # third-party
    "rest_framework",
    "rest_framework_simplejwt",
    "corsheaders",
    # local
    "apps.accounts",
    "apps.core",
    "apps.sites",
    "apps.catalog",
    "apps.orders",
    "apps.sync",
    "apps.monitoring",
    "apps.integrations",
]

MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

# --- Database (host-OS Postgres via host.docker.internal; env-driven) ----
DATABASES = {"default": env.db("DATABASE_URL")}
# CONN_MAX_AGE=0: close after each use. Celery workers bypass Django's request
# middleware (which normally closes persistent connections), so keeping connections
# alive causes "too many clients" under any meaningful concurrency.
DATABASES["default"]["CONN_MAX_AGE"] = 0

# --- Auth ---------------------------------------------------------------
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# --- i18n ---------------------------------------------------------------
LANGUAGE_CODE = "en-us"
TIME_ZONE = "Asia/Ho_Chi_Minh"
USE_I18N = True
USE_TZ = True

# --- Static -------------------------------------------------------------
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

# --- Media (user uploads: site-note image attachments) ------------------
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --- DRF ----------------------------------------------------------------
REST_FRAMEWORK = {
    "DEFAULT_PAGINATION_CLASS": "config.pagination.StandardPagination",
    "PAGE_SIZE": 25,
    "DEFAULT_RENDERER_CLASSES": [
        "rest_framework.renderers.JSONRenderer",
        "rest_framework.renderers.BrowsableAPIRenderer",
    ],
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
}

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=60),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=7),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": False,
    "AUTH_HEADER_TYPES": ("Bearer",),
}

# --- Cache (Redis, DB 1 — separate from the Celery broker on DB 0) -------
# Used for distributed task locks (e.g. pull_all_categories deduplication).
# Django 4.0+ built-in Redis backend; requires the ``redis`` package (pulled
# in by celery[redis]).
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": env("CACHE_URL", default="redis://redis:6379/1"),
    }
}

# --- Celery -------------------------------------------------------------
CELERY_BROKER_URL = env("REDIS_URL", default="redis://redis:6379/0")
CELERY_RESULT_BACKEND = env("CELERY_RESULT_BACKEND", default=CELERY_BROKER_URL)
CELERY_TIMEZONE = TIME_ZONE
CELERY_TASK_TRACK_STARTED = True

# How often Celery Beat polls orders across all sites (seconds).
ORDER_POLL_INTERVAL_SECONDS = env.int("ORDER_POLL_INTERVAL_SECONDS", default=480)

# Sites polled concurrently per order-sync batch (one batch task per chunk).
ORDER_POLL_BATCH_SIZE = env.int("ORDER_POLL_BATCH_SIZE", default=8)

# Product push ("Sync all"): sites pushed concurrently per batch task, max items
# (create+update+delete) per WooCommerce /products/batch request (~100 cap), and
# a small throttle between chunks to one site (shared hosts choke easily).
PRODUCT_PUSH_BATCH_SIZE = env.int("PRODUCT_PUSH_BATCH_SIZE", default=8)
PRODUCT_BATCH_ITEM_LIMIT = env.int("PRODUCT_BATCH_ITEM_LIMIT", default=100)
PRODUCT_PUSH_THROTTLE_SECONDS = env.float("PRODUCT_PUSH_THROTTLE_SECONDS", default=0.5)

# Site health-check (periodic, apps.monitoring.tasks.check_all_sites):
#  - TIMEOUT: per-call timeout (s) for the system_status round-trip.
#  - OK / FAIL INTERVAL: re-check cadence. A site that passed its last check is
#    re-checked every OK interval; a site that failed (or was never reached) is
#    retried every FAIL interval. The Celery beat tick (config/celery.py) is the
#    FAIL interval, so it must stay <= OK interval.
SITE_HEALTHCHECK_TIMEOUT_SECONDS = env.float("SITE_HEALTHCHECK_TIMEOUT_SECONDS", default=15.0)
SITE_HEALTHCHECK_OK_INTERVAL_SECONDS = env.int(
    "SITE_HEALTHCHECK_OK_INTERVAL_SECONDS", default=600
)  # 10 min
SITE_HEALTHCHECK_FAIL_INTERVAL_SECONDS = env.int(
    "SITE_HEALTHCHECK_FAIL_INTERVAL_SECONDS", default=300
)  # 5 min

# --- CORS / CSRF (CORS only needed for dev-on-host Vite at :5173) --------
CORS_ALLOWED_ORIGINS = env.list("CORS_ALLOWED_ORIGINS", default=["http://localhost:5173"])
CSRF_TRUSTED_ORIGINS = env.list(
    "CSRF_TRUSTED_ORIGINS",
    default=["http://localhost:5173", "http://localhost:8000"],
)

# --- Secrets ------------------------------------------------------------
# Read now so a missing/invalid key surfaces at startup, not mid-feature.
FERNET_KEY = env("FERNET_KEY")

# --- Logging (console only, no PII) -------------------------------------
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "simple": {"format": "%(levelname)s %(asctime)s %(name)s %(message)s"},
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "simple"},
    },
    "root": {"handlers": ["console"], "level": "INFO"},
}
