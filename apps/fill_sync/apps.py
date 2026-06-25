"""FillSync 模块：Django app 注册；不读写业务事实本身；不访问外部服务；不发送 Hermes；不提交订单。"""

from __future__ import annotations

from django.apps import AppConfig


class FillSyncConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.fill_sync"
    verbose_name = "FillSync"
