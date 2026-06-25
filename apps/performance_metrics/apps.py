"""PerformanceMetrics 模块：注册后置绩效复盘 app，不承载计算逻辑。"""

from __future__ import annotations

from django.apps import AppConfig


class PerformanceMetricsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.performance_metrics"
    verbose_name = "Performance Metrics"

