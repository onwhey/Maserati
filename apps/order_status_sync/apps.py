from __future__ import annotations

from django.apps import AppConfig


class OrderStatusSyncConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.order_status_sync"
    verbose_name = "Order Status Sync"
