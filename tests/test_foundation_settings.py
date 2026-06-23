import logging
import os
import subprocess
import sys

from django.conf import settings

from apps.foundation.context import ensure_context, make_trace_id
from apps.foundation.idempotency import assert_not_trace_id, build_idempotency_key
from apps.foundation.redaction import sanitize_mapping


def test_settings_use_utc() -> None:
    assert settings.USE_TZ is True
    assert settings.TIME_ZONE == "UTC"
    assert settings.CELERY_TIMEZONE == "UTC"


def test_real_trading_default_closed() -> None:
    assert settings.DEPLOYMENT_REAL_TRADING_ENABLED is False
    assert settings.ALLOW_REAL_EXTERNAL_SERVICES is False


def test_celery_app_loads_with_utc_timezone() -> None:
    from config.celery import app

    assert app.main == "the_cypto"
    assert app.conf.timezone == "UTC"


def test_trace_id_generation_and_context() -> None:
    trace_id = make_trace_id()
    context = ensure_context(trace_id=trace_id, trigger_source="test")
    assert context.trace_id == trace_id
    assert context.trigger_source == "test"


def test_idempotency_key_is_not_trace_id() -> None:
    trace_id = make_trace_id()
    key = build_idempotency_key("module", "object", "action")
    assert key != trace_id
    assert_not_trace_id(key, trace_id)


def test_sensitive_mapping_is_redacted() -> None:
    sanitized = sanitize_mapping(
        {
            "api_key": "real-key",
            "nested": {"Authorization": "Bearer secret-token"},
            "message": "signature=abc123",
        }
    )
    assert sanitized["api_key"] == "[REDACTED]"
    assert sanitized["nested"]["Authorization"] == "[REDACTED]"
    assert "abc123" not in sanitized["message"]


def test_logging_filter_redacts_sensitive_text(caplog) -> None:
    logger = logging.getLogger("tests.redaction")
    with caplog.at_level(logging.INFO):
        logger.info("api_key=abc123")
    assert "abc123" not in caplog.text


def test_non_test_settings_missing_required_env_fails_clearly(tmp_path) -> None:
    env = os.environ.copy()
    env["DJANGO_ENV_FILE"] = str(tmp_path / "missing.env")
    for key in (
        "APP_ENV",
        "DJANGO_SECRET_KEY",
        "MYSQL_HOST",
        "MYSQL_DATABASE",
        "MYSQL_USER",
        "MYSQL_PASSWORD",
        "REDIS_URL",
        "CELERY_BROKER_URL",
        "CELERY_RESULT_BACKEND",
    ):
        env.pop(key, None)

    completed = subprocess.run(
        [sys.executable, "-c", "import config.settings"],
        cwd=settings.BASE_DIR,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode != 0
    assert "缺少必要环境变量" in completed.stderr
