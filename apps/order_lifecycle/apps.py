"""OrderLifecycle 模块：注册既有订单生命周期同步 app；不承载业务逻辑。"""

from __future__ import annotations

from django.apps import AppConfig


class OrderLifecycleConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.order_lifecycle"
    verbose_name = "Order Lifecycle"
