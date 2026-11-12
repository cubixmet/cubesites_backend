"""CubeSites Django settings — env-driven, SQLite locally, Postgres-ready."""
from datetime import timedelta
from pathlib import Path

import environ

BASE_DIR = Path(__file__).resolve().parent.parent

env = environ.Env(
    DJANGO_DEBUG=(bool, True),
    JWT_ACCESS_MINUTES=(int, 60),
    # Keep signed-in users remembered for a year; refresh rotation extends this while active.
    JWT_REFRESH_DAYS=(int, 365),
)
environ.Env.read_env(BASE_DIR / ".env")

SECRET_KEY = env("DJANGO_SECRET_KEY", default="django-insecure-dev-only-change-me")
DEBUG = env("DJANGO_DEBUG")
ALLOWED_HOSTS = env.list(
    "DJANGO_ALLOWED_HOSTS",
    default=["localhost", "127.0.0.1", "testserver"],
)

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # third-party
    "corsheaders",
    "rest_framework",
    "rest_framework_simplejwt",
    # project
    "accounts",
    "jobsites",
    "ledger",
    "billing",
    "ops",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "cubesites_backend.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "cubesites_backend.wsgi.application"

# Prefer DATABASE_URL; fall back to local SQLite for practical development.
DATABASES = {"default": env.db("DATABASE_URL", default=f"sqlite:///{BASE_DIR / 'db.sqlite3'}")}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = env("DJANGO_TIME_ZONE", default="Asia/Kolkata")
USE_I18N = True
USE_TZ = True

STATIC_URL = env("STATIC_URL", default="/static/")
STATIC_ROOT = BASE_DIR / "staticfiles"
MEDIA_URL = env("MEDIA_URL", default="/media/")
MEDIA_ROOT = BASE_DIR / "media"

# Auth — Google Sign-In (GIS ID token) + SMTP for email OTP.
# Prefer env vars; if a downloaded client_secret*.json exists, fill any blanks from it.
GOOGLE_CLIENT_ID = env("GOOGLE_CLIENT_ID", default=env("google_client_id", default="")).strip()
GOOGLE_CLIENT_SECRET = env("GOOGLE_CLIENT_SECRET", default=env("google_client_secret", default="")).strip()
GOOGLE_REDIRECT_URI = env(
    "GOOGLE_REDIRECT_URI",
    default=env("google_redirect_uri", default="http://localhost:8080/auth/google/callback"),
).strip()
# Drive OAuth callback must hit Django (not the SPA). Add this URI in Google Cloud Console.
GOOGLE_DRIVE_REDIRECT_URI = env(
    "GOOGLE_DRIVE_REDIRECT_URI",
    default="http://localhost:8000/api/v1/drive/callback/",
).strip()
FRONTEND_URL = env("FRONTEND_URL", default="http://localhost:8080").strip().rstrip("/")

_google_json = next(BASE_DIR.glob("client_secret_*.json"), None)
if _google_json and _google_json.is_file():
    import json as _json

    try:
        _web = _json.loads(_google_json.read_text()).get("web") or {}
        GOOGLE_CLIENT_ID = GOOGLE_CLIENT_ID or str(_web.get("client_id") or "").strip()
        GOOGLE_CLIENT_SECRET = GOOGLE_CLIENT_SECRET or str(_web.get("client_secret") or "").strip()
        _uris = _web.get("redirect_uris") or []
        if _uris and (
            not GOOGLE_REDIRECT_URI
            or GOOGLE_REDIRECT_URI.startswith("/")
            or "://" not in GOOGLE_REDIRECT_URI
        ):
            GOOGLE_REDIRECT_URI = str(_uris[0]).strip()
    except Exception:
        pass

EMAIL_BACKEND = env(
    "EMAIL_BACKEND",
    default="django.core.mail.backends.smtp.EmailBackend",
)
EMAIL_HOST = env("EMAIL_HOST", default="smtp.gmail.com")
EMAIL_PORT = env.int("EMAIL_PORT", default=587)
EMAIL_USE_TLS = env.bool("EMAIL_USE_TLS", default=True)
EMAIL_HOST_USER = env("EMAIL_HOST_USER", default="")
EMAIL_HOST_PASSWORD = env("EMAIL_HOST_PASSWORD", default="")
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", default=EMAIL_HOST_USER or "noreply@cubosites.com")
OTP_EXPIRY_MINUTES = env.int("OTP_EXPIRY_MINUTES", default=10)

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
AUTH_USER_MODEL = "accounts.User"

CORS_ALLOWED_ORIGINS = env.list(
    "CORS_ALLOWED_ORIGINS",
    default=[
        "http://localhost:8080",
        "http://127.0.0.1:8080",
        "http://localhost:8081",
        "http://127.0.0.1:8081",
    ],
)
CORS_ALLOW_CREDENTIALS = True
CSRF_TRUSTED_ORIGINS = env.list("CSRF_TRUSTED_ORIGINS", default=[])

if not DEBUG:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_SSL_REDIRECT = env.bool("DJANGO_SECURE_SSL_REDIRECT", default=False)

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ),
    "DEFAULT_PERMISSION_CLASSES": ("rest_framework.permissions.IsAuthenticated",),
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 50,
    "DEFAULT_FILTER_BACKENDS": (
        "rest_framework.filters.SearchFilter",
        "rest_framework.filters.OrderingFilter",
    ),
    "EXCEPTION_HANDLER": "accounts.exceptions.api_exception_handler",
}

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=env("JWT_ACCESS_MINUTES")),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=env("JWT_REFRESH_DAYS")),
    # Issue a fresh refresh token on each use so active users stay signed in.
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": False,
    "AUTH_HEADER_TYPES": ("Bearer",),
}

# Default CubeSites pricing (paise) — overridable via PricingVersion rows.
DEFAULT_PRICING = {
    "site_per_month": 10900,
    "free_sites": 3,
    "staff_per_month": 2900,
    "free_staff": 1,
    "free_storage_mb": 250,
    "storage_block_mb": 250,
    "storage_block_price": 500,
    "days_per_month": 30,
}
