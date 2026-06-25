"""OpsConsole 模块：提供后台只读查询 API；读数据库，不访问 Redis，不访问外部服务，不发送 Hermes，不调用大模型，不涉及交易执行。"""

from __future__ import annotations

from django.apps import AppConfig


class OpsConsoleConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.ops_console"
    verbose_name = "OpsConsole"

