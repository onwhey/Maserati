from __future__ import annotations

import os
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Iterable

from celery.schedules import crontab
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


def env_decimal(name: str, *, default: str) -> Decimal:
    raw = os.environ.get(name, default)
    try:
        value = Decimal(raw)
    except InvalidOperation as exc:
        raise ImproperlyConfigured(f"环境变量 {name} 必须是 Decimal") from exc
    if not value.is_finite():
        raise ImproperlyConfigured(f"环境变量 {name} 必须是有限 Decimal")
    return value


def csv_env(name: str, *, default: Iterable[str]) -> list[str]:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return list(default)
    return [item.strip() for item in raw.split(",") if item.strip()]


APP_ENV = env_str("APP_ENV", default="development")
TESTING = APP_ENV == "test" or any("pytest" in arg.lower() for arg in sys.argv)
PRODUCTION = APP_ENV == "production"

SECRET_KEY = env_str(
    "DJANGO_SECRET_KEY",
    default="test-secret-key-only-for-tests" if TESTING else None,
    required=not TESTING,
)
DEBUG = env_bool("DJANGO_DEBUG", default=False)
ALLOWED_HOSTS = csv_env("DJANGO_ALLOWED_HOSTS", default=["localhost", "127.0.0.1"])

SECURE_SSL_REDIRECT = env_bool("DJANGO_SECURE_SSL_REDIRECT", default=PRODUCTION)
SECURE_HSTS_SECONDS = env_int("DJANGO_SECURE_HSTS_SECONDS", default=31536000 if PRODUCTION else 0)
SECURE_HSTS_INCLUDE_SUBDOMAINS = env_bool("DJANGO_SECURE_HSTS_INCLUDE_SUBDOMAINS", default=PRODUCTION)
SECURE_HSTS_PRELOAD = env_bool("DJANGO_SECURE_HSTS_PRELOAD", default=False)
SESSION_COOKIE_SECURE = env_bool("DJANGO_SESSION_COOKIE_SECURE", default=PRODUCTION)
CSRF_COOKIE_SECURE = env_bool("DJANGO_CSRF_COOKIE_SECURE", default=PRODUCTION)
SESSION_COOKIE_HTTPONLY = True
CSRF_COOKIE_HTTPONLY = False
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"
X_FRAME_OPTIONS = "DENY"

INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "apps.foundation",
    "apps.alerts",
    "apps.audit",
    "apps.orchestration",
    "apps.runtime_guard",
    "apps.runtime_config",
    "apps.performance_metrics",
    "apps.ops_console",
    "apps.deepseek_gateway",
    "apps.ai_review",
    "apps.binance_gateway",
    "apps.binance_account_sync",
    "apps.price_snapshot",
    "apps.order_plan",
    "apps.risk_check",
    "apps.execution_preparation",
    "apps.execution",
    "apps.order_status_sync",
    "apps.fill_sync",
    "apps.market_data",
    "apps.strategy_analysis",
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
ORCHESTRATION_MAIN_CYCLE_BEAT_ENABLED = env_bool("ORCHESTRATION_MAIN_CYCLE_BEAT_ENABLED", default=False)
RUNTIME_GUARD_BEAT_ENABLED = env_bool("RUNTIME_GUARD_BEAT_ENABLED", default=False)
NOTIFICATIONS_PENDING_SCAN_BEAT_ENABLED = env_bool("NOTIFICATIONS_PENDING_SCAN_BEAT_ENABLED", default=False)

if ORCHESTRATION_MAIN_CYCLE_BEAT_ENABLED:
    CELERY_BEAT_SCHEDULE["orchestration-main-trading-cycle"] = {
        "task": "orchestration.start_main_trading_cycle",
        "schedule": crontab(minute=5, hour="*/4"),
        "kwargs": {},
    }
if RUNTIME_GUARD_BEAT_ENABLED:
    CELERY_BEAT_SCHEDULE["runtime-guard-run"] = {
        "task": "runtime_guard.run",
        "schedule": crontab(minute="*/10"),
        "kwargs": {"dry_run": False, "confirm_write": True, "trace_id": ""},
    }
if NOTIFICATIONS_PENDING_SCAN_BEAT_ENABLED:
    CELERY_BEAT_SCHEDULE["notifications-scan-pending"] = {
        "task": "notifications.scan_pending",
        "schedule": crontab(minute="*/1"),
        "kwargs": {"limit": 50},
    }

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

DATA_COLLECTION_EXCHANGE = env_str("DATA_COLLECTION_EXCHANGE", default="binance")
DATA_COLLECTION_MARKET_TYPE = env_str("DATA_COLLECTION_MARKET_TYPE", default="usds_m_futures")
DATA_COLLECTION_SYMBOL = env_str("DATA_COLLECTION_SYMBOL", default="BTCUSDT")
DATA_COLLECTION_TIMEFRAMES = csv_env("DATA_COLLECTION_TIMEFRAMES", default=["4h", "1d"])
DATA_COLLECTION_4H_LOOKBACK_COUNT = env_int("DATA_COLLECTION_4H_LOOKBACK_COUNT", default=10)
DATA_COLLECTION_1D_LOOKBACK_COUNT = env_int("DATA_COLLECTION_1D_LOOKBACK_COUNT", default=5)
DATA_BACKFILL_KLINE_PAGE_LIMIT = env_int("DATA_BACKFILL_KLINE_PAGE_LIMIT", default=1000)
DATA_BACKFILL_MAX_PAGES_PER_RUN = env_int("DATA_BACKFILL_MAX_PAGES_PER_RUN", default=10)
DATA_BACKFILL_MAX_BARS_PER_RUN = env_int("DATA_BACKFILL_MAX_BARS_PER_RUN", default=5000)
MARKET_SNAPSHOT_4H_LOOKBACK_COUNT = env_int("MARKET_SNAPSHOT_4H_LOOKBACK_COUNT", default=500)
MARKET_SNAPSHOT_1D_LOOKBACK_COUNT = env_int("MARKET_SNAPSHOT_1D_LOOKBACK_COUNT", default=365)

FEATURE_SCHEMA_VERSION = env_str("FEATURE_SCHEMA_VERSION", default="1.0")
SIGNAL_SCHEMA_VERSION = env_str("SIGNAL_SCHEMA_VERSION", default="1.0")
ATOMIC_SIGNAL_FAILURE_BLOCK_RATIO = env_decimal("ATOMIC_SIGNAL_FAILURE_BLOCK_RATIO", default="0.3")
DOMAIN_SIGNAL_SCHEMA_VERSION = env_str("DOMAIN_SIGNAL_SCHEMA_VERSION", default="1.0")
MARKET_REGIME_SCHEMA_VERSION = env_str("MARKET_REGIME_SCHEMA_VERSION", default="1.0")
STRATEGY_ROUTE_SCHEMA_VERSION = env_str("STRATEGY_ROUTE_SCHEMA_VERSION", default="1.0")
STRATEGY_SIGNAL_SCHEMA_VERSION = env_str("STRATEGY_SIGNAL_SCHEMA_VERSION", default="1.0")
STRATEGY_SIGNAL_QUALITY_IDEMPOTENCY_LOCK_TTL_SECONDS = env_int(
    "STRATEGY_SIGNAL_QUALITY_IDEMPOTENCY_LOCK_TTL_SECONDS",
    default=60,
)
STRATEGY_SIGNAL_QUALITY_MAX_CHECK_COUNT = env_int("STRATEGY_SIGNAL_QUALITY_MAX_CHECK_COUNT", default=100)
STRATEGY_SIGNAL_QUALITY_MAX_EXECUTION_SECONDS = env_int("STRATEGY_SIGNAL_QUALITY_MAX_EXECUTION_SECONDS", default=10)
DECISION_SNAPSHOT_SCHEMA_VERSION = env_str("DECISION_SNAPSHOT_SCHEMA_VERSION", default="1.0")
DECISION_SNAPSHOT_IDEMPOTENCY_LOCK_TTL_SECONDS = env_int("DECISION_SNAPSHOT_IDEMPOTENCY_LOCK_TTL_SECONDS", default=60)
DECISION_SNAPSHOT_MAX_EXECUTION_SECONDS = env_int("DECISION_SNAPSHOT_MAX_EXECUTION_SECONDS", default=10)

BINANCE_GATEWAY_ENABLED = env_bool("BINANCE_GATEWAY_ENABLED", default=False)
BINANCE_PUBLIC_DATA_ENABLED = env_bool("BINANCE_PUBLIC_DATA_ENABLED", default=False)
BINANCE_ACCOUNT_READ_ENABLED = env_bool("BINANCE_ACCOUNT_READ_ENABLED", default=False)
BINANCE_ORDER_SUBMISSION_ENABLED = env_bool("BINANCE_ORDER_SUBMISSION_ENABLED", default=False)
BINANCE_ORDER_STATUS_QUERY_ENABLED = env_bool("BINANCE_ORDER_STATUS_QUERY_ENABLED", default=False)
BINANCE_FILL_QUERY_ENABLED = env_bool("BINANCE_FILL_QUERY_ENABLED", default=False)
BINANCE_BASE_URL = env_str("BINANCE_BASE_URL", default="")
BINANCE_USDS_M_BASE_URL = env_str("BINANCE_USDS_M_BASE_URL", default=BINANCE_BASE_URL)
BINANCE_COIN_M_BASE_URL = env_str("BINANCE_COIN_M_BASE_URL", default="")
BINANCE_USDS_M_READ_API_KEY = env_str("BINANCE_USDS_M_READ_API_KEY", default="")
BINANCE_USDS_M_READ_API_SECRET = env_str("BINANCE_USDS_M_READ_API_SECRET", default="")
BINANCE_COIN_M_READ_API_KEY = env_str("BINANCE_COIN_M_READ_API_KEY", default="")
BINANCE_COIN_M_READ_API_SECRET = env_str("BINANCE_COIN_M_READ_API_SECRET", default="")
BINANCE_USDS_M_TRADE_API_KEY = env_str("BINANCE_USDS_M_TRADE_API_KEY", default="")
BINANCE_USDS_M_TRADE_API_SECRET = env_str("BINANCE_USDS_M_TRADE_API_SECRET", default="")
BINANCE_COIN_M_TRADE_API_KEY = env_str("BINANCE_COIN_M_TRADE_API_KEY", default="")
BINANCE_COIN_M_TRADE_API_SECRET = env_str("BINANCE_COIN_M_TRADE_API_SECRET", default="")
BINANCE_RECV_WINDOW_MS = env_int("BINANCE_RECV_WINDOW_MS", default=5000)
BINANCE_CONNECT_TIMEOUT_SECONDS = env_int("BINANCE_CONNECT_TIMEOUT_SECONDS", default=10)
BINANCE_READ_TIMEOUT_SECONDS = env_int("BINANCE_READ_TIMEOUT_SECONDS", default=10)
BINANCE_SAFE_READ_MAX_ATTEMPTS = env_int("BINANCE_SAFE_READ_MAX_ATTEMPTS", default=2)
BINANCE_MAX_CLOCK_SKEW_MS = env_int("BINANCE_MAX_CLOCK_SKEW_MS", default=1000)
BINANCE_ACCOUNT_SYNC_ENABLED = env_bool("BINANCE_ACCOUNT_SYNC_ENABLED", default=False)
BINANCE_ACCOUNT_SYNC_TTL_SECONDS = env_int("BINANCE_ACCOUNT_SYNC_TTL_SECONDS", default=1800)
BINANCE_ACCOUNT_SYNC_SYMBOLS = csv_env("BINANCE_ACCOUNT_SYNC_SYMBOLS", default=["BTCUSDT"])
BINANCE_ACCOUNT_SYNC_CONSECUTIVE_FAILURE_ALERT_THRESHOLD = env_int(
    "BINANCE_ACCOUNT_SYNC_CONSECUTIVE_FAILURE_ALERT_THRESHOLD",
    default=3,
)
BINANCE_ACCOUNT_SYNC_OPS_REFRESH_COOLDOWN_SECONDS = env_int(
    "BINANCE_ACCOUNT_SYNC_OPS_REFRESH_COOLDOWN_SECONDS",
    default=60,
)
PRICE_SNAPSHOT_ENABLED = env_bool("PRICE_SNAPSHOT_ENABLED", default=False)
PRICE_SNAPSHOT_TTL_SECONDS = env_int("PRICE_SNAPSHOT_TTL_SECONDS", default=600)
PRICE_SNAPSHOT_REDIS_CACHE_ENABLED = env_bool("PRICE_SNAPSHOT_REDIS_CACHE_ENABLED", default=True)
PRICE_SNAPSHOT_REDIS_KEY_PREFIX = env_str("PRICE_SNAPSHOT_REDIS_KEY_PREFIX", default="price_snapshot")
PRICE_SNAPSHOT_MAX_DECIMAL_PLACES = env_int("PRICE_SNAPSHOT_MAX_DECIMAL_PLACES", default=18)
ORDER_PLAN_ENABLED = env_bool("ORDER_PLAN_ENABLED", default=False)
ORDER_PLAN_SUPPORTED_MARKET_TYPES = csv_env(
    "ORDER_PLAN_SUPPORTED_MARKET_TYPES",
    default=["usds_m_futures", "coin_m_futures"],
)
ORDER_PLAN_TARGET_NOTIONAL_BASIS = env_str("ORDER_PLAN_TARGET_NOTIONAL_BASIS", default="current_equity")
ORDER_PLAN_MAX_TARGET_NOTIONAL_TO_EQUITY_RATIO = env_decimal(
    "ORDER_PLAN_MAX_TARGET_NOTIONAL_TO_EQUITY_RATIO",
    default="3.0",
)
ORDER_PLAN_MIN_REBALANCE_NOTIONAL = env_decimal("ORDER_PLAN_MIN_REBALANCE_NOTIONAL", default="20")
ORDER_PLAN_SUPPORTED_POSITION_MODE = env_str("ORDER_PLAN_SUPPORTED_POSITION_MODE", default="one_way")
ORDER_PLAN_SUPPORTED_ORDER_TYPE = env_str("ORDER_PLAN_SUPPORTED_ORDER_TYPE", default="MARKET")
RISK_CHECK_ENABLED = env_bool("RISK_CHECK_ENABLED", default=False)
RISK_CHECK_RULE_SET = env_str("RISK_CHECK_RULE_SET", default="p0_default")
RISK_CHECK_MARGIN_BUFFER_RATIO = env_decimal("RISK_CHECK_MARGIN_BUFFER_RATIO", default="0.05")
RISK_CHECK_RULE_FAILURE_MODE = env_str("RISK_CHECK_RULE_FAILURE_MODE", default="fail_closed")
RISK_CHECK_APPROVED_INTENT_TTL_SECONDS = env_int("RISK_CHECK_APPROVED_INTENT_TTL_SECONDS", default=120)
EXECUTION_PREPARATION_ENABLED = env_bool("EXECUTION_PREPARATION_ENABLED", default=False)
EXECUTION_PREPARATION_MAX_PRICE_DEVIATION_BPS = env_int("EXECUTION_PREPARATION_MAX_PRICE_DEVIATION_BPS", default=100)
PREPARED_ORDER_INTENT_TTL_SECONDS = env_int("PREPARED_ORDER_INTENT_TTL_SECONDS", default=30)
EXECUTION_PREPARATION_SUPPORTED_ORDER_TYPES = csv_env(
    "EXECUTION_PREPARATION_SUPPORTED_ORDER_TYPES",
    default=["MARKET"],
)
EXECUTION_PREPARATION_SUPPORTED_POSITION_MODE = env_str("EXECUTION_PREPARATION_SUPPORTED_POSITION_MODE", default="one_way")
ORDER_STATUS_SYNC_ENABLED = env_bool("ORDER_STATUS_SYNC_ENABLED", default=False)
ORDER_STATUS_POLL_INTERVAL_SECONDS = env_int("ORDER_STATUS_POLL_INTERVAL_SECONDS", default=2)
ORDER_STATUS_POLL_MAX_DURATION_SECONDS = env_int("ORDER_STATUS_POLL_MAX_DURATION_SECONDS", default=30)
ORDER_STATUS_RECOVERY_WINDOW_SECONDS = env_int("ORDER_STATUS_RECOVERY_WINDOW_SECONDS", default=86400)
FILL_SYNC_ENABLED = env_bool("FILL_SYNC_ENABLED", default=False)
FILL_SYNC_PAGE_SIZE = env_int("FILL_SYNC_PAGE_SIZE", default=100)
FILL_SYNC_MAX_PAGES = env_int("FILL_SYNC_MAX_PAGES", default=10)
FILL_SYNC_RECOVERY_WINDOW_SECONDS = env_int("FILL_SYNC_RECOVERY_WINDOW_SECONDS", default=86400)
EXTERNAL_REQUEST_TIMEOUT_SECONDS = env_int("EXTERNAL_REQUEST_TIMEOUT_SECONDS", default=10)
SAFE_READ_MAX_TECHNICAL_RETRIES = env_int("SAFE_READ_MAX_TECHNICAL_RETRIES", default=2)

DEEPSEEK_GATEWAY_ENABLED = env_bool("DEEPSEEK_GATEWAY_ENABLED", default=False)
DEEPSEEK_API_KEY = env_str("DEEPSEEK_API_KEY", default="")
DEEPSEEK_BASE_URL = env_str("DEEPSEEK_BASE_URL", default="")
DEEPSEEK_API_FORMAT = env_str("DEEPSEEK_API_FORMAT", default="openai_chat_completions")
DEEPSEEK_DEFAULT_MODEL_PROFILE = env_str("DEEPSEEK_DEFAULT_MODEL_PROFILE", default="default_review")
DEEPSEEK_DEFAULT_MODEL = env_str("DEEPSEEK_DEFAULT_MODEL", default="deepseek-chat")
DEEPSEEK_REVIEW_MODEL = env_str("DEEPSEEK_REVIEW_MODEL", default=DEEPSEEK_DEFAULT_MODEL)
DEEPSEEK_MODEL_PROFILE_ENABLED = env_bool("DEEPSEEK_MODEL_PROFILE_ENABLED", default=True)
DEEPSEEK_JSON_OUTPUT_ENABLED = env_bool("DEEPSEEK_JSON_OUTPUT_ENABLED", default=True)
DEEPSEEK_REASONING_ENABLED = env_bool("DEEPSEEK_REASONING_ENABLED", default=False)
DEEPSEEK_REASONING_EFFORT = env_str("DEEPSEEK_REASONING_EFFORT", default="")
DEEPSEEK_MAX_INPUT_TOKENS = env_int("DEEPSEEK_MAX_INPUT_TOKENS", default=16000)
DEEPSEEK_MAX_OUTPUT_TOKENS = env_int("DEEPSEEK_MAX_OUTPUT_TOKENS", default=4096)
DEEPSEEK_TEMPERATURE = env_decimal("DEEPSEEK_TEMPERATURE", default="0.2")
DEEPSEEK_TOP_P = env_decimal("DEEPSEEK_TOP_P", default="1.0")
DEEPSEEK_CONNECT_TIMEOUT_SECONDS = env_int("DEEPSEEK_CONNECT_TIMEOUT_SECONDS", default=10)
DEEPSEEK_READ_TIMEOUT_SECONDS = env_int("DEEPSEEK_READ_TIMEOUT_SECONDS", default=30)
DEEPSEEK_MAX_RETRIES = env_int("DEEPSEEK_MAX_RETRIES", default=0)
DEEPSEEK_RETRY_BACKOFF_MS = env_int("DEEPSEEK_RETRY_BACKOFF_MS", default=0)
DEEPSEEK_MAX_CONCURRENCY = env_int("DEEPSEEK_MAX_CONCURRENCY", default=1)
DEEPSEEK_RATE_LIMIT_PER_MINUTE = env_int("DEEPSEEK_RATE_LIMIT_PER_MINUTE", default=6)
DEEPSEEK_COOLDOWN_SECONDS = env_int("DEEPSEEK_COOLDOWN_SECONDS", default=60)

AI_REVIEW_MAX_RUNS_PER_REQUEST = env_int("AI_REVIEW_MAX_RUNS_PER_REQUEST", default=100)
AI_REVIEW_MAX_PACKAGE_BYTES = env_int("AI_REVIEW_MAX_PACKAGE_BYTES", default=200000)
AI_REVIEW_DATA_SCHEMA_VERSION = env_str("AI_REVIEW_DATA_SCHEMA_VERSION", default="1.0")
AI_REVIEW_SANITIZATION_VERSION = env_str("AI_REVIEW_SANITIZATION_VERSION", default="1.0")
AI_REVIEW_PROMPT_VERSION = env_str("AI_REVIEW_PROMPT_VERSION", default="p0_v1")
AI_REVIEW_PROMPT_SCHEMA_VERSION = env_str("AI_REVIEW_PROMPT_SCHEMA_VERSION", default="1.0")
AI_REVIEW_OUTPUT_SCHEMA_VERSION = env_str("AI_REVIEW_OUTPUT_SCHEMA_VERSION", default="1.0")

NOTIFICATIONS_DELIVERY_ENABLED = env_bool("NOTIFICATIONS_DELIVERY_ENABLED", default=False)
NOTIFICATIONS_DEFAULT_CHANNEL = env_str("NOTIFICATIONS_DEFAULT_CHANNEL", default="console_only")
NOTIFICATIONS_FAKE_DELIVERY_SUCCESS = env_bool("NOTIFICATIONS_FAKE_DELIVERY_SUCCESS", default=TESTING)
RUNTIME_GUARD_ORCHESTRATION_STALE_MINUTES = env_int("RUNTIME_GUARD_ORCHESTRATION_STALE_MINUTES", default=30)
RUNTIME_GUARD_STEP_STALE_MINUTES = env_int("RUNTIME_GUARD_STEP_STALE_MINUTES", default=20)
RUNTIME_GUARD_ACTIVE_LOCK_STALE_MINUTES = env_int("RUNTIME_GUARD_ACTIVE_LOCK_STALE_MINUTES", default=40)
RUNTIME_GUARD_ORDER_STATUS_STALE_MINUTES = env_int("RUNTIME_GUARD_ORDER_STATUS_STALE_MINUTES", default=45)
RUNTIME_GUARD_NOTIFICATION_STALE_MINUTES = env_int("RUNTIME_GUARD_NOTIFICATION_STALE_MINUTES", default=10)

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
