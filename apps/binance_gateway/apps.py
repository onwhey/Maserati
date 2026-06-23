"""BinanceGateway 模块：Django app 注册；不读写数据库，不访问外部服务，不涉及交易执行。"""

from __future__ import annotations

from django.apps import AppConfig


class BinanceGatewayConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.binance_gateway"
    verbose_name = "Binance Gateway"

