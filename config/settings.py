"""Einstellungen der Webseite des Fördervereins KF/JF Kreuzau.

Alle umgebungsabhängigen Werte kommen aus Umgebungsvariablen (auf dem Server aus
/etc/fv-web/env, siehe Betriebshandbuch). Ohne Variablen startet eine lokale
Entwicklungsumgebung mit SQLite.
"""

import os
from pathlib import Path

from django.utils.csp import CSP

BASE_DIR = Path(__file__).resolve().parent.parent


def env(name, default=None):
    return os.environ.get(name, default)


def env_bool(name, default=False):
    return env(name, "1" if default else "0").lower() in {"1", "true", "yes", "ja"}


DEBUG = env_bool("FV_DEBUG", False)
SECRET_KEY = env("FV_SECRET_KEY") or (
    "nur-fuer-die-entwicklung-nicht-produktiv-verwenden" if DEBUG else None
)
if not SECRET_KEY:
    raise RuntimeError("FV_SECRET_KEY ist nicht gesetzt.")

ALLOWED_HOSTS = [h for h in env("FV_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",") if h]
CSRF_TRUSTED_ORIGINS = [o for o in env("FV_CSRF_TRUSTED_ORIGINS", "").split(",") if o]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "simple_history",
    "seiten",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "django.middleware.csp.ContentSecurityPolicyMiddleware",
    "simple_history.middleware.HistoryRequestMiddleware",
]

ROOT_URLCONF = "config.urls"

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
                "django.template.context_processors.csp",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

# Datenbank: PostgreSQL auf dem Server, SQLite in der Entwicklung
if env("FV_DB_NAME"):
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": env("FV_DB_NAME"),
            "USER": env("FV_DB_USER", ""),
            "PASSWORD": env("FV_DB_PASSWORD", ""),
            "HOST": env("FV_DB_HOST", ""),  # leer = Unix-Socket
            "PORT": env("FV_DB_PORT", ""),
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
     "OPTIONS": {"min_length": 10}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "startseite"
LOGOUT_REDIRECT_URL = "startseite"

LANGUAGE_CODE = "de-de"
TIME_ZONE = "Europe/Berlin"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = Path(env("FV_STATIC_ROOT", BASE_DIR / "staticfiles"))
STATICFILES_DIRS = [BASE_DIR / "static"]

# Anhänge liegen außerhalb des Webverzeichnisses und werden nur über die
# Download-Ansicht nach Rechteprüfung ausgeliefert. Es gibt bewusst kein MEDIA_URL.
PRIVATE_MEDIA_ROOT = Path(env("FV_PRIVATE_MEDIA_ROOT", BASE_DIR / "private"))
ANHANG_MAX_BYTES = 20 * 1024 * 1024
ANHANG_ENDUNGEN = [
    "pdf", "jpg", "jpeg", "png", "gif", "webp",
    "doc", "docx", "xls", "xlsx", "ppt", "pptx", "odt", "ods", "odp", "txt",
]
DATA_UPLOAD_MAX_MEMORY_SIZE = 2_621_440
FILE_UPLOAD_PERMISSIONS = 0o640

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Sicherheit
SECURE_CSP = {
    "default-src": [CSP.SELF],
    "script-src": [CSP.SELF, CSP.NONCE],
    "style-src": [CSP.SELF],
    "img-src": [CSP.SELF, "data:"],
    "object-src": [CSP.NONE],
    "base-uri": [CSP.SELF],
    "frame-ancestors": [CSP.NONE],
    "form-action": [CSP.SELF],
}
SESSION_COOKIE_HTTPONLY = True
X_FRAME_OPTIONS = "DENY"
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"

if not DEBUG:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SECURE_SSL_REDIRECT = env_bool("FV_SSL_REDIRECT", True)
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = int(env("FV_HSTS_SECONDS", "31536000"))
    SECURE_HSTS_INCLUDE_SUBDOMAINS = env_bool("FV_HSTS_SUBDOMAINS", False)

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": env("FV_LOG_LEVEL", "INFO")},
}
