"""General Automation System — Django settings (all configuration comes from the environment / .env)."""

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def env(name, default=""):
    return os.environ.get(name, default)


def env_list(name, default=""):
    return [item.strip() for item in env(name, default).split(",") if item.strip()]


SECRET_KEY = env("DJANGO_SECRET_KEY")
if not SECRET_KEY:
    raise RuntimeError("DJANGO_SECRET_KEY is not set (see .env.example).")
DEBUG = env("DJANGO_DEBUG", "0") == "1"
ALLOWED_HOSTS = env_list("ALLOWED_HOSTS", "localhost,127.0.0.1")
CSRF_TRUSTED_ORIGINS = env_list("CSRF_TRUSTED_ORIGINS")

INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "core",
    "mo_close",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.auth.middleware.LoginRequiredMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "core.middleware.OdooSessionMiddleware",
]

ROOT_URLCONF = "gas.urls"
WSGI_APPLICATION = "gas.wsgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
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

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": env("POSTGRES_DB", "gas"),
        "USER": env("POSTGRES_USER", "gas"),
        "PASSWORD": env("POSTGRES_PASSWORD"),
        "HOST": env("DB_HOST", "localhost"),
        "PORT": env("DB_PORT", "5432"),
        "CONN_MAX_AGE": 60,
    }
}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --- Auth: Odoo account login, roles kept in this system ---
AUTH_USER_MODEL = "core.User"
AUTHENTICATION_BACKENDS = ["core.backends.OdooBackend"]
LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "home"
SESSION_ENGINE = "django.contrib.sessions.backends.db"
SESSION_COOKIE_AGE = int(env("SESSION_HOURS", "12")) * 3600
SESSION_COOKIE_HTTPONLY = True
CSRF_COOKIE_HTTPONLY = False  # HTMX reads the token from the page, not the cookie

# --- Odoo ---
ODOO_URL = env("ODOO_URL", "https://erp.sawo.com").rstrip("/")
ODOO_DB = env("ODOO_DB", "sawo")
ODOO_TIMEOUT = int(env("ODOO_TIMEOUT", "30"))
ADMIN_ODOO_LOGINS = [login.lower() for login in env_list("ADMIN_ODOO_LOGIN")]

# --- Locale ---
LANGUAGE_CODE = "en-us"
TIME_ZONE = env("TIME_ZONE", "Asia/Manila")
USE_I18N = False
USE_TZ = True
DATETIME_FORMAT = "d-M-Y H:i"
DATE_FORMAT = "d-M-Y"
SHORT_DATETIME_FORMAT = "d-M-Y H:i"

# --- Files ---
STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}
MEDIA_ROOT = BASE_DIR / "media"
MEDIA_URL = "media/"
MAX_PDF_UPLOAD_MB = 10
DATA_UPLOAD_MAX_MEMORY_SIZE = MAX_PDF_UPLOAD_MB * 1024 * 1024

MESSAGE_TAGS = {40: "danger"}  # messages.ERROR → Bootstrap "danger"

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": "INFO"},
}
