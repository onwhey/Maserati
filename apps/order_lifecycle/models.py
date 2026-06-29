"""OrderLifecycle 模块：定义 LIMIT 订单周期收尾撤单事实；读写 MySQL；不访问 Redis；不直接访问外部服务；不发送 Hermes；不调用大模型；涉及既有订单撤单审计；不允许提交新订单。"""

from __future__ import annotations

from django.db import models


class OrderCancelAttemptStatus(models.TextChoices):
    CANCELING = "canceling", "撤单中"
    ACCEPTED = "accepted", "撤单请求已被交易所接受"
    NOT_FOUND = "not_found", "交易所明确未找到订单"
    UNKNOWN = "unknown", "撤单结果未知"
    FAILED_BEFORE_CANCEL = "failed_before_cancel", "撤单前失败"
    BLOCKED_BEFORE_CANCEL = "blocked_before_cancel", "撤单前阻断"


class OrderCancelAttempt(models.Model):
    order_cancel_attempt_key = models.CharField("撤单尝试幂等键", max_length=191, unique=True)
    order_submission_attempt = models.ForeignKey(
        "execution.OrderSubmissionAttempt",
        on_delete=models.PROTECT,
        related_name="order_cancel_attempts",
    )
    prepared_order_intent = models.ForeignKey(
        "execution_preparation.PreparedOrderIntent",
        on_delete=models.PROTECT,
        related_name="order_cancel_attempts",
    )
    order_plan = models.ForeignKey(
        "order_plan.OrderPlan",
        on_delete=models.PROTECT,
        related_name="order_cancel_attempts",
    )
    active_lock = models.ForeignKey(
        "order_plan.OrderPlanActiveLock",
        on_delete=models.PROTECT,
        related_name="order_cancel_attempts",
    )
    business_request_key = models.CharField("业务幂等键", max_length=191)
    exchange = models.CharField("交易所", max_length=40, default="binance")
    market_type = models.CharField("市场类型", max_length=40)
    account_domain = models.CharField("账户域", max_length=120)
    endpoint_family = models.CharField("Gateway endpoint family", max_length=40, blank=True)
    symbol = models.CharField("交易品种", max_length=40)
    client_order_id = models.CharField("Binance clientOrderId", max_length=120, blank=True)
    exchange_order_id = models.CharField("交易所订单 ID", max_length=120, blank=True)
    closeout_time_utc = models.DateTimeField("收尾 UTC 时间")
    limit_valid_until_utc = models.DateTimeField("LIMIT 有效截止 UTC 时间")
    cancel_reason_code = models.CharField("撤单原因代码", max_length=120)
    cancel_status = models.CharField("撤单状态", max_length=40, choices=OrderCancelAttemptStatus.choices)
    reason_code = models.CharField("结果原因代码", max_length=120, blank=True)
    request_sent = models.BooleanField("请求是否已发出", default=False)
    response_received = models.BooleanField("是否收到响应", default=False)
    gateway_attempt_count = models.PositiveIntegerField("Gateway 技术尝试次数", default=0)
    cancel_request = models.JSONField("冻结撤单请求", default=dict, blank=True)
    request_payload_hash = models.CharField("撤单请求 hash", max_length=80, blank=True)
    http_status = models.IntegerField("HTTP 状态码", null=True, blank=True)
    binance_error_code = models.CharField("Binance 错误码", max_length=80, blank=True)
    sanitized_error_message = models.CharField("脱敏错误摘要", max_length=500, blank=True)
    sanitized_response = models.JSONField("脱敏交易所响应", default=dict, blank=True)
    response_hash = models.CharField("交易所响应 hash", max_length=80, blank=True)
    reason_message = models.CharField("原因说明", max_length=500, blank=True)
    rate_limit_metadata = models.JSONField("限频元数据", default=dict, blank=True)
    alert_event_ids = models.JSONField("AlertEvent ID", default=list, blank=True)
    trace_id = models.CharField("技术追踪 ID", max_length=80)
    trigger_source = models.CharField("触发来源", max_length=80)
    started_at_utc = models.DateTimeField("开始 UTC 时间")
    finished_at_utc = models.DateTimeField("完成 UTC 时间", null=True, blank=True)
    created_at_utc = models.DateTimeField("创建 UTC 时间", auto_now_add=True)
    updated_at_utc = models.DateTimeField("更新 UTC 时间", auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["order_submission_attempt", "closeout_time_utc", "cancel_reason_code"],
                name="uniq_order_cancel_attempt_closeout_reason",
            )
        ]
        indexes = [
            models.Index(fields=["order_submission_attempt", "cancel_status"]),
            models.Index(fields=["cancel_status", "created_at_utc"]),
            models.Index(fields=["market_type", "account_domain", "symbol"]),
            models.Index(fields=["active_lock"]),
            models.Index(fields=["trace_id"]),
        ]

    def __str__(self) -> str:
        return f"OrderCancelAttempt<{self.order_submission_attempt_id}:{self.cancel_status}>"
