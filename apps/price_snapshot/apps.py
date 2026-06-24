"""PriceSnapshot 模块：声明 Django app；不读写数据库；不访问 Redis；不访问外部服务；不发送 Hermes；不调用大模型；不涉及交易执行；不允许真实交易。"""

from __future__ import annotations

from django.apps import AppConfig


class PriceSnapshotConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.price_snapshot"
    verbose_name = "PriceSnapshot"
