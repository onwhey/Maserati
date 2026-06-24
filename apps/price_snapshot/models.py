"""PriceSnapshot 模块：定义交易前 mark price 事实；读写数据库；不访问 Redis；不访问外部服务；不发送 Hermes；不调用大模型；不涉及交易执行；不允许真实交易。"""

from __future__ import annotations

from django.core.exceptions import ValidationError
from django.db import models


class PriceType(models.TextChoices):
    MARK_PRICE = "mark_price", "标记价格"


class PriceSnapshot(models.Model):
    business_request_key = models.CharField("业务幂等键", max_length=191, unique=True)
    exchange = models.CharField("交易所", max_length=40, default="binance")
    market_type = models.CharField("市场类型", max_length=40)
    account_domain = models.CharField("账户域", max_length=120)
    symbol = models.CharField("交易品种", max_length=40)
    price_type = models.CharField("价格类型", max_length=40, choices=PriceType.choices, default=PriceType.MARK_PRICE)
    mark_price = models.DecimalField("标记价格", max_digits=38, decimal_places=18)
    price_unit = models.CharField("价格单位", max_length=40)
    source = models.CharField("来源", max_length=80, default="binance_rest")
    source_operation = models.CharField("来源操作", max_length=80, default="get_mark_price")
    source_update_time_utc = models.DateTimeField("Binance 价格更新时间")
    requested_at_utc = models.DateTimeField("请求开始 UTC 时间")
    received_at_utc = models.DateTimeField("收到响应 UTC 时间")
    as_of_utc = models.DateTimeField("价格事实 UTC 时间")
    expires_at_utc = models.DateTimeField("过期 UTC 时间")
    gateway_latency_ms = models.IntegerField("Gateway 延迟毫秒", default=0)
    gateway_attempt_count = models.IntegerField("Gateway 尝试次数", default=0)
    price_snapshot_hash = models.CharField("价格快照 hash", max_length=80)
    raw_payload = models.JSONField("脱敏原始载荷", default=dict, blank=True)
    gateway_call_summary = models.JSONField("Gateway 调用摘要", default=dict, blank=True)
    trace_id = models.CharField("追踪 ID", max_length=80)
    trigger_source = models.CharField("触发来源", max_length=80)
    created_at_utc = models.DateTimeField("创建 UTC 时间", auto_now_add=True)

    IMMUTABLE_FIELDS = {
        "business_request_key",
        "exchange",
        "market_type",
        "account_domain",
        "symbol",
        "price_type",
        "mark_price",
        "price_unit",
        "source",
        "source_operation",
        "source_update_time_utc",
        "requested_at_utc",
        "received_at_utc",
        "as_of_utc",
        "expires_at_utc",
        "price_snapshot_hash",
        "raw_payload",
    }

    class Meta:
        indexes = [
            models.Index(fields=["market_type", "account_domain", "symbol"]),
            models.Index(fields=["expires_at_utc"]),
            models.Index(fields=["trace_id"]),
            models.Index(fields=["price_snapshot_hash"]),
        ]

    def save(self, *args, **kwargs) -> None:
        if self.pk:
            original = type(self).objects.get(pk=self.pk)
            changed = [
                field
                for field in self.IMMUTABLE_FIELDS
                if getattr(original, field) != getattr(self, field)
            ]
            if changed:
                raise ValidationError(f"PriceSnapshot 核心字段不可修改：{','.join(sorted(changed))}")
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.symbol}:{self.price_type}:{self.business_request_key}"
