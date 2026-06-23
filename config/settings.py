from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Iterable

from django.core.exceptions import ImproperlyConfigured
from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parent.parent
ENV_FILE = Path(os.environ.get("DJANGO_ENV_FILE", BASE_DIR / ".env"))
load_dotenv(ENV_FILE)


def env_str(name: str, *, default: str | None = None, required: bool = False) -> str:
    value = os.environ.get(name, default)
    if required and (value is None or value == ""):
        raise ImproperlyConfigured(f"缺少必要环境变量：{name}")
    return "" if value is None else value


def env_bool(name: str, *, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    normalized = raw.strip().lower()
    if normalized in {"1", "true", "yes", "y", "on"}:
        return True
    if normalized in {"0", "false", "no", "n", "off"}:
        return False
    raise ImproperlyConfigured(f"环境变量 {name} 必须是布尔值")


def env_int(name: str, *, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ImproperlyConfigured(f"环境变量 {name} 必须是整数") from exc


def csv_env(name: str, *, default: Iterable[str]) -> list[str]:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return list(default)
    return [item.strip() for item in raw.split(",") if item.strip()]


APP_ENV = env_str("APP_ENV", default="development")
TESTING = APP_ENV == "test" or any("pytest" in arg.lower() for arg in sys.argv)

SECRET_KEY = env_str(
    "DJANGO_SECRET_KEY",
    default="test-secret-key-only-for-tests" if TESTING else None,
    required=not TESTING,
)
DEBUG = env_bool("DJANGO_DEBUG", default=False)
ALLOWED_HOSTS = csv_env("DJANGO_ALLOWED_HOSTS", default=["localhost", "127.0.0.1"])

INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "apps.foundation",
    "apps.alerts",
    "apps.audit",
    "apps.runtime_config",
]

MIDDLEWARE = [
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
    }
]
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

if TESTING:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": ":memory:",
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.mysql",
            "HOST": env_str("MYSQL_HOST", required=True),
            "PORT": env_str("MYSQL_PORT", default="3306"),
            "NAME": env_str("MYSQL_DATABASE", required=True),
            "USER": env_str("MYSQL_USER", required=True),
            "PASSWORD": env_str("MYSQL_PASSWORD", required=True),
            "OPTIONS": {
                "charset": "utf8mb4",
            },
        }
    }

REDIS_URL = env_str("REDIS_URL", default="redis://127.0.0.1:6379/0" if TESTING else None, required=not TESTING)
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache"
        if TESTING
        else "django_redis.cache.RedisCache",
        "LOCATION": "the-cypto-test-cache" if TESTING else REDIS_URL,
    }
}

CELERY_BROKER_URL = env_str(
    "CELERY_BROKER_URL",
    default="redis://127.0.0.1:6379/1" if TESTING else None,
    required=not TESTING,
)
CELERY_RESULT_BACKEND = env_str(
    "CELERY_RESULT_BACKEND",
    default="redis://127.0.0.1:6379/2" if TESTING else None,
    required=not TESTING,
)
CELERY_TIMEZONE = "UTC"
CELERY_ENABLE_UTC = True
CELERY_BEAT_SCHEDULE: dict[str, object] = {}

LANGUAGE_CODE = "zh-hans"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

ACTIVE_EXCHANGE = env_str("ACTIVE_EXCHANGE", default="Binance" if TESTING else None, required=not TESTING)
ACTIVE_MARKET_TYPE = env_str("ACTIVE_MARKET_TYPE", default="USDS-M" if TESTING else None, required=not TESTING)
ACTIVE_ACCOUNT_DOMAIN = env_str("ACTIVE_ACCOUNT_DOMAIN", default="default" if TESTING else None, required=not TESTING)
ACTIVE_SYMBOL = env_str("ACTIVE_SYMBOL", default="BTCUSDT" if TESTING else None, required=not TESTING)

DEPLOYMENT_REAL_TRADING_ENABLED = env_bool("DEPLOYMENT_REAL_TRADING_ENABLED", default=False)
ALLOW_REAL_EXTERNAL_SERVICES = env_bool("ALLOW_REAL_EXTERNAL_SERVICES", default=False)

BINANCE_BASE_URL = env_str("BINANCE_BASE_URL", default="")
BINANCE_RECV_WINDOW_MS = env_int("BINANCE_RECV_WINDOW_MS", default=5000)
EXTERNAL_REQUEST_TIMEOUT_SECONDS = env_int("EXTERNAL_REQUEST_TIMEOUT_SECONDS", default=10)
SAFE_READ_MAX_TECHNICAL_RETRIES = env_int("SAFE_READ_MAX_TECHNICAL_RETRIES", default=2)

DEEPSEEK_BASE_URL = env_str("DEEPSEEK_BASE_URL", default="")
DEEPSEEK_DEFAULT_MODEL_PROFILE = env_str("DEEPSEEK_DEFAULT_MODEL_PROFILE", default="default_review")

NOTIFICATIONS_DELIVERY_ENABLED = env_bool("NOTIFICATIONS_DELIVERY_ENABLED", default=False)
NOTIFICATIONS_DEFAULT_CHANNEL = env_str("NOTIFICATIONS_DEFAULT_CHANNEL", default="console_only")

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "filters": {
        "redact_sensitive": {
            "()": "apps.foundation.logging_filters.SensitiveDataFilter",
        }
    },
    "formatters": {
        "standard": {
            "format": "%(asctime)sZ %(levelname)s %(name)s %(message)s",
            "datefmt": "%Y-%m-%dT%H:%M:%S",
        }
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "standard",
            "filters": ["redact_sensitive"],
        }
    },
    "root": {
        "handlers": ["console"],
        "level": "INFO",
    },
}
