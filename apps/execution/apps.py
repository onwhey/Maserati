"""Execution 模块：Django app 注册；不读写数据库；不访问外部服务；涉及交易执行模块注册。"""

from __future__ import annotations

from django.apps import AppConfig


class ExecutionConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.execution"
    verbose_name = "Execution"

