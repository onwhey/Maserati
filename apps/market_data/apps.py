"""MarketData 模块：Django app 注册；不访问外部服务，不发送 Hermes，不涉及交易执行。"""

from __future__ import annotations

from django.apps import AppConfig


class MarketDataConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.market_data"
    verbose_name = "Market Data"

