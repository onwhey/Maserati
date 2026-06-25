"""RuntimeGuard 模块：注册只读巡检 app；不承载巡检规则。"""

from __future__ import annotations

from django.apps import AppConfig


class RuntimeGuardConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.runtime_guard"
    verbose_name = "Runtime Guard"

