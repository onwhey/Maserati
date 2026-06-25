"""Execution 模块：定义订单提交事实；读写 MySQL；不访问 Redis；不直接访问外部服务；不发送 Hermes；不调用大模型；涉及交易执行；允许记录真实订单提交结果。"""

from __future__ import annotations

from django.db import models


class OrderSubmissionAttemptStatus(models.TextChoices):
    CREATED = "created", "已创建"
    SUBMITTING = "submitting", "提交中"
    ACCEPTED = "accepted", "交易所已接受提交请求"
    REJECTED = "rejected", "交易所明确拒绝"
    UNKNOWN = "unknown", "提交结果未知"
    BLOCKED_BEFORE_SUBMIT = "blocked_before_submit", "提交前阻断"
    FAILED_BEFORE_SUBMIT = "failed_before_submit", "提交前失败"


class OrderSubmissionAttempt(models.Model):
    order_submission_attempt_key = models.CharField("订单提交尝试幂等键", max_length=191, unique=True)
    prepared_order_intent = models.OneToOneField(
        "execution_preparation.PreparedOrderIntent",
        on_delete=models.PROTECT,
        related_name="order_submission_attempt",
    )
    execution_preparation_result = models.ForeignKey(
        "execution_preparation.ExecutionPreparationResult",
        on_delete=models.PROTECT,
        related_name="order_submission_attempts",
    )
    approved_order_intent = models.ForeignKey(
        "risk_check.ApprovedOrderIntent",
        on_delete=models.PROTECT,
        related_name="order_submission_attempts",
    )
    risk_check_result = models.ForeignKey(
        "risk_check.RiskCheckResult",
        on_delete=models.PROTECT,
        related_name="order_submission_attempts",
    )
    candidate_order_intent = models.ForeignKey(
        "order_plan.CandidateOrderIntent",
        on_delete=models.PROTECT,
        related_name="order_submission_attempts",
    )
    order_plan = models.ForeignKey(
        "order_plan.OrderPlan",
        on_delete=models.PROTECT,
        related_name="order_submission_attempts",
    )
    active_lock = models.ForeignKey(
        "order_plan.OrderPlanActiveLock",
        on_delete=models.PROTECT,
        related_name="order_submission_attempts",
    )
    business_request_key = models.CharField("业务幂等键", max_length=191)
    exchange = models.CharField("交易所", max_length=40, default="binance")
    market_type = models.CharField("市场类型", max_length=40)
    account_domain = models.CharField("账户域", max_length=120)
    endpoint_family = models.CharField("Gateway endpoint family", max_length=40, blank=True)
    symbol = models.CharField("交易品种", max_length=40)
    side = models.CharField("订单方向", max_length=10)
    position_side = models.CharField("持仓方向", max_length=20)
    position_mode = models.CharField("持仓模式", max_length=40)
    order_type = models.CharField("订单类型", max_length=40)
    quantity = models.DecimalField("冻结提交数量", max_digits=38, decimal_places=18)
    quantity_unit = models.CharField("数量单位", max_length=40)
    reduce_only = models.BooleanField("reduceOnly")
    order_notional = models.DecimalField("订单名义价值", max_digits=38, decimal_places=18, null=True, blank=True)
    client_order_id = models.CharField("Binance clientOrderId", max_length=36, unique=True)
    idempotency_key = models.CharField("提交幂等键", max_length=191, unique=True)
    frozen_order_request = models.JSONField("冻结订单请求", default=dict)
    request_payload_hash = models.CharField("请求载荷 hash", max_length=80)
    status = models.CharField("提交状态", max_length=40, choices=OrderSubmissionAttemptStatus.choices)
    request_sent = models.BooleanField("请求是否已发出", default=False)
    response_received = models.BooleanField("是否收到响应", default=False)
    gateway_attempt_count = models.PositiveIntegerField("Gateway 技术尝试次数", default=0)
    exchange_order_id = models.CharField("交易所订单 ID", max_length=120, blank=True)
    exchange_client_order_id = models.CharField("交易所 clientOrderId", max_length=120, blank=True)
    exchange_status = models.CharField("交易所响应状态", max_length=80, blank=True)
    sanitized_exchange_response = models.JSONField("脱敏交易所响应", default=dict, blank=True)
    exchange_response_hash = models.CharField("交易所响应 hash", max_length=80, blank=True)
    http_status = models.IntegerField("HTTP 状态码", null=True, blank=True)
    binance_error_code = models.CharField("Binance 错误码", max_length=80, blank=True)
    sanitized_error_message = models.CharField("脱敏错误摘要", max_length=500, blank=True)
    exception_class = models.CharField("异常类型", max_length=120, blank=True)
    reason_code = models.CharField("原因代码", max_length=120)
    reason_message = models.CharField("原因说明", max_length=500, blank=True)
    rate_limit_metadata = models.JSONField("限频元数据", default=dict, blank=True)
    alert_event_ids = models.JSONField("AlertEvent ID", default=list, blank=True)
    trace_id = models.CharField("技术追踪 ID", max_length=80)
    trigger_source = models.CharField("触发来源", max_length=80)
    claimed_at_utc = models.DateTimeField("抢占 UTC 时间")
    submitted_at_utc = models.DateTimeField("提交调用 UTC 时间", null=True, blank=True)
    finished_at_utc = models.DateTimeField("完成 UTC 时间", null=True, blank=True)
    created_at_utc = models.DateTimeField("创建 UTC 时间", auto_now_add=True)
    updated_at_utc = models.DateTimeField("更新 UTC 时间", auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["status", "created_at_utc"]),
            models.Index(fields=["market_type", "account_domain", "symbol"]),
            models.Index(fields=["order_plan"]),
            models.Index(fields=["prepared_order_intent"]),
            models.Index(fields=["client_order_id"]),
            models.Index(fields=["trace_id"]),
        ]
