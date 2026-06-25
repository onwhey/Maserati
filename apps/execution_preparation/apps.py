"""ExecutionPreparation 模块：Django app 声明；不承载业务逻辑。"""

from __future__ import annotations

from django.apps import AppConfig


class ExecutionPreparationConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.execution_preparation"
    verbose_name = "Execution Preparation"
