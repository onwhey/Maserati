"""项目底座模块：提供基础健康检查服务；只读数据库和 Redis，不访问外部服务，不涉及交易执行。"""

from __future__ import annotations

from dataclasses import dataclass

from django.conf import settings
from django.core import checks
from django.db import connection
from django.db.migrations.executor import MigrationExecutor


@dataclass(frozen=True)
class HealthCheckItem:
    name: str
    passed: bool
    message: str


def check_django_system() -> HealthCheckItem:
    errors = checks.run_checks()
    if errors:
        return HealthCheckItem("django_system_check", False, f"发现 {len(errors)} 个 system check 问题")
    return HealthCheckItem("django_system_check", True, "Django system check 通过")


def check_database_connection() -> HealthCheckItem:
    try:
        connection.ensure_connection()
    except Exception as exc:
        return HealthCheckItem("database_connection", False, f"数据库连接失败：{exc.__class__.__name__}")
    return HealthCheckItem("database_connection", True, "数据库连接正常")


def check_migrations_applied() -> HealthCheckItem:
    try:
        executor = MigrationExecutor(connection)
        pending = executor.migration_plan(executor.loader.graph.leaf_nodes())
    except Exception as exc:
        return HealthCheckItem("database_migrations", False, f"迁移状态检查失败：{exc.__class__.__name__}")
    if pending:
        return HealthCheckItem("database_migrations", False, f"存在 {len(pending)} 个未应用迁移")
    return HealthCheckItem("database_migrations", True, "数据库迁移已全部应用")


def check_redis_configuration() -> HealthCheckItem:
    redis_url = getattr(settings, "REDIS_URL", "")
    if not redis_url:
        return HealthCheckItem("redis_configuration", False, "REDIS_URL 未配置")
    return HealthCheckItem("redis_configuration", True, "Redis 配置已读取")


def check_redis_connection() -> HealthCheckItem:
    try:
        from django_redis import get_redis_connection

        get_redis_connection("default").ping()
    except Exception as exc:
        return HealthCheckItem("redis_connection", False, f"Redis 连接失败：{exc.__class__.__name__}")
    return HealthCheckItem("redis_connection", True, "Redis 连接正常")


def check_celery_app() -> HealthCheckItem:
    try:
        from config.celery import app

        timezone = app.conf.timezone
    except Exception as exc:
        return HealthCheckItem("celery_app", False, f"Celery app 加载失败：{exc.__class__.__name__}")
    if timezone != "UTC":
        return HealthCheckItem("celery_app", False, f"Celery timezone 不是 UTC：{timezone}")
    return HealthCheckItem("celery_app", True, "Celery app 可加载且使用 UTC")


def check_real_trading_default_safe() -> HealthCheckItem:
    if settings.DEPLOYMENT_REAL_TRADING_ENABLED:
        return HealthCheckItem("real_trading_hard_permission", False, "部署级真实交易硬权限已开启")
    return HealthCheckItem("real_trading_hard_permission", True, "部署级真实交易硬权限关闭")


def run_foundation_health_checks(*, check_redis_ping: bool = True) -> list[HealthCheckItem]:
    items = [
        check_django_system(),
        check_database_connection(),
        check_migrations_applied(),
        check_redis_configuration(),
        check_celery_app(),
        check_real_trading_default_safe(),
    ]
    if check_redis_ping:
        items.append(check_redis_connection())
    return items

