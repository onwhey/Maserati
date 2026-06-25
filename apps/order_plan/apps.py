"""OrderPlan 模块：声明 Django app；不读写业务数据；不访问外部服务；不执行真实交易。"""

from __future__ import annotations

from django.apps import AppConfig


class OrderPlanConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.order_plan"
    verbose_name = "OrderPlan"

