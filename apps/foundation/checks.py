"""项目底座模块：Django system checks；不写数据库，不访问外部服务，不涉及交易执行。"""

from __future__ import annotations

from django.conf import settings
from django.core.checks import Error, Warning, register


@register()
def foundation_settings_check(app_configs, **kwargs):
    issues = []

    if not settings.USE_TZ:
        issues.append(Error("USE_TZ 必须为 True", id="foundation.E001"))

    if settings.TIME_ZONE != "UTC":
        issues.append(Error("TIME_ZONE 必须为 UTC", id="foundation.E002"))

    if settings.CELERY_TIMEZONE != "UTC":
        issues.append(Error("Celery timezone 必须为 UTC", id="foundation.E003"))

    db_engine = settings.DATABASES["default"]["ENGINE"]
    if not settings.TESTING and db_engine != "django.db.backends.mysql":
        issues.append(Error("正式 settings 必须使用 MySQL，不得使用 SQLite 作为正式默认数据库", id="foundation.E004"))

    if settings.ACTIVE_EXCHANGE != "Binance":
        issues.append(Error("当前阶段 active exchange 只允许 Binance", id="foundation.E005"))

    if settings.ACTIVE_MARKET_TYPE not in {"USDS-M", "COIN-M"}:
        issues.append(Error("ACTIVE_MARKET_TYPE 只允许 USDS-M 或 COIN-M", id="foundation.E006"))

    if not settings.ACTIVE_ACCOUNT_DOMAIN:
        issues.append(Error("ACTIVE_ACCOUNT_DOMAIN 不能为空", id="foundation.E007"))

    if not settings.ACTIVE_SYMBOL:
        issues.append(Error("ACTIVE_SYMBOL 不能为空", id="foundation.E008"))

    if settings.DEPLOYMENT_REAL_TRADING_ENABLED and settings.TESTING:
        issues.append(Error("测试环境不得开启部署级真实交易权限", id="foundation.E009"))

    if settings.DEPLOYMENT_REAL_TRADING_ENABLED and not settings.ALLOW_REAL_EXTERNAL_SERVICES:
        issues.append(Warning("真实交易硬权限开启，但真实外部服务适配器仍关闭", id="foundation.W001"))

    return issues

