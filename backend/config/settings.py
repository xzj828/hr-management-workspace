import os
import secrets
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent

_local_secret_file = BASE_DIR / "local_secret.key"
if os.getenv("DJANGO_SECRET_KEY"):
    SECRET_KEY = os.environ["DJANGO_SECRET_KEY"]
else:
    if not _local_secret_file.exists():
        _local_secret_file.write_text(secrets.token_urlsafe(64), encoding="utf-8")
    SECRET_KEY = _local_secret_file.read_text(encoding="utf-8").strip()
DEBUG = os.getenv("DJANGO_DEBUG", "1") == "1"
ALLOWED_HOSTS = [host.strip() for host in os.getenv("DJANGO_ALLOWED_HOSTS", "*").split(",") if host.strip()]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "accounts",
    "attendance",
    "recruitment",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
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
        "DIRS": [BASE_DIR / "frontend_dist"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    }
]
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

if os.getenv("POSTGRES_DB"):
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": os.environ["POSTGRES_DB"],
            "USER": os.getenv("POSTGRES_USER", "postgres"),
            "PASSWORD": os.getenv("POSTGRES_PASSWORD", ""),
            "HOST": os.getenv("POSTGRES_HOST", "127.0.0.1"),
            "PORT": os.getenv("POSTGRES_PORT", "5432"),
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": Path(os.getenv("DATABASE_PATH", BASE_DIR / "db.sqlite3")),
            # SQLite ignores SELECT ... FOR UPDATE.  BEGIN IMMEDIATE acquires
            # the database write reservation before lifecycle code reads its
            # fence/version, so concurrent HTTP threads and Worker callbacks
            # serialize instead of failing later with a stale snapshot or
            # ``database is locked`` during the first write.
            "OPTIONS": {"timeout": 20, "transaction_mode": "IMMEDIATE"},
        }
    }

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "zh-hans"
TIME_ZONE = "Asia/Shanghai"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "frontend_dist"] if (BASE_DIR / "frontend_dist").exists() else []
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"
RPA_PROFILE_ROOT = Path(os.getenv("RPA_PROFILE_ROOT", BASE_DIR / "rpa_profiles"))

_local_worker_file = BASE_DIR / "local_worker.key"
if os.getenv("RPA_WORKER_TOKEN"):
    RPA_WORKER_TOKEN = os.environ["RPA_WORKER_TOKEN"]
else:
    if not _local_worker_file.exists():
        _local_worker_file.write_text(secrets.token_urlsafe(48), encoding="utf-8")
    RPA_WORKER_TOKEN = _local_worker_file.read_text(encoding="utf-8").strip()
RPA_API_BASE_URL = os.getenv("RPA_API_BASE_URL", "http://127.0.0.1:8000/api/recruitment/worker")
RPA_POLL_SECONDS = float(os.getenv("RPA_POLL_SECONDS", "3"))
AI_POLL_SECONDS = float(os.getenv("AI_POLL_SECONDS", "3"))
MODEL_API_HOST_ALLOWLIST = tuple(
    entry.strip()
    for entry in os.getenv("MODEL_API_HOST_ALLOWLIST", "").split(",")
    if entry.strip()
)
try:
    MODEL_API_MAX_RESPONSE_BYTES = max(1, int(os.getenv("MODEL_API_MAX_RESPONSE_BYTES", str(1024 * 1024))))
except ValueError:
    MODEL_API_MAX_RESPONSE_BYTES = 1024 * 1024
try:
    MODEL_API_TEST_TIMEOUT_SECONDS = max(1, int(os.getenv("MODEL_API_TEST_TIMEOUT_SECONDS", "10")))
except ValueError:
    MODEL_API_TEST_TIMEOUT_SECONDS = 10

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": ["rest_framework.authentication.SessionAuthentication"],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 500,
    "DEFAULT_THROTTLE_RATES": {
        "model_connection_test": os.getenv("MODEL_API_TEST_THROTTLE_RATE", "5/min"),
    },
}

CSRF_TRUSTED_ORIGINS = [
    origin.strip()
    for origin in os.getenv(
        "CSRF_TRUSTED_ORIGINS",
        "http://localhost:5173,http://127.0.0.1:5173",
    ).split(",")
    if origin.strip()
]
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_AGE = 30 * 24 * 60 * 60
SESSION_SAVE_EVERY_REQUEST = True
CSRF_COOKIE_SAMESITE = "Lax"
FILE_UPLOAD_MAX_MEMORY_SIZE = 10 * 1024 * 1024
DATA_UPLOAD_MAX_MEMORY_SIZE = 12 * 1024 * 1024
