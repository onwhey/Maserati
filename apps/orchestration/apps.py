"""PipelineOrchestrator 模块：注册编排 app；不承载业务逻辑。"""

from __future__ import annotations

from django.apps import AppConfig


class OrchestrationConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.orchestration"
    verbose_name = "Pipeline Orchestrator"

