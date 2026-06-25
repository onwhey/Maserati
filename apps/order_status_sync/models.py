"""OrderStatusSync 模块：定义订单状态查询事实；读写 MySQL；不访问 Redis；不直接访问外部服务；不发送 Hermes；不调用大模型；不提交订单；不允许真实交易执行。"""

from __future__ import annotations

from django.db import models


class OrderStatusQueryOutcome(models.TextChoices):
    FOUND = "found", "查询到订单"
    NOT_FOUND = "not_found", "交易所明确未找到订单"
    UNKNOWN = "unknown", "查询结果未知"
    FAILED_BEFORE_QUERY = "failed_before_query", "查询前失败"
    BLOCKED_BEFORE_QUERY = "blocked_before_query", "查询前阻断"


class OrderStatusSubmissionResolution(models.TextChoices):
    UNRESOLVED = "unresolved", "仍未确认"
    ORDER_FOUND = "order_found", "已确认订单存在"
    TERMINAL_CONFIRMED = "terminal_confirmed", "已确认订单终态"
    NOT_QUERYABLE = "not_queryable", "不允许查询"


class OrderStatusSyncRecord(models.Model):
    order_status_sync_key = models.CharField("订单状态查询幂等键", max_length=191, unique=True)
    order_submission_attempt = models.ForeignKey(
        "execution.OrderSubmissionAttempt",
        on_delete=models.PROTECT,
        related_name="order_status_sync_records",
    )
    prepared_order_intent = models.ForeignKey(
        "execution_preparation.PreparedOrderIntent",
        on_delete=models.PROTECT,
        related_name="order_status_sync_records",
    )
    order_plan = models.ForeignKey(
        "order_plan.OrderPlan",
        on_delete=models.PROTECT,
        related_name="order_status_sync_records",
    )
    active_lock = models.ForeignKey(
        "order_plan.OrderPlanActiveLock",
        on_delete=models.PROTECT,
        related_name="order_status_sync_records",
    )
    business_request_key = models.CharField("业务幂等键", max_length=191)
    exchange = models.CharField("交易所", max_length=40, default="binance")
    market_type = models.CharField("市场类型", max_length=40)
    account_domain = models.CharField("账户域", max_length=120)
    endpoint_family = models.CharField("Gateway endpoint family", max_length=40, blank=True)
    symbol = models.CharField("交易品种", max_length=40)
    query_identifier_type = models.CharField("查询编号类型", max_length=40)
    client_order_id = models.CharField("Binance clientOrderId", max_length=120, blank=True)
    exchange_order_id_requested = models.CharField("请求使用的交易所订单 ID", max_length=120, blank=True)
    poll_mode = models.CharField("轮询模式", max_length=40, default="immediate")
    poll_sequence = models.PositiveIntegerField("逻辑轮询序号")
    polling_started_at_utc = models.DateTimeField("轮询开始 UTC 时间")
    polling_deadline_utc = models.DateTimeField("轮询截止 UTC 时间")
    scheduled_at_utc = models.DateTimeField("本轮计划 UTC 时间")
    query_started_at_utc = models.DateTimeField("查询开始 UTC 时间")
    query_finished_at_utc = models.DateTimeField("查询完成 UTC 时间", null=True, blank=True)
    query_outcome = models.CharField("查询结果", max_length=40, choices=OrderStatusQueryOutcome.choices)
    reason_code = models.CharField("原因代码", max_length=120)
    reason_message = models.CharField("原因说明", max_length=500, blank=True)
    request_sent = models.BooleanField("请求是否已发出", default=False)
    response_received = models.BooleanField("是否收到响应", default=False)
    gateway_attempt_count = models.PositiveIntegerField("Gateway 技术尝试次数", default=0)
    gateway_latency_ms = models.PositiveIntegerField("Gateway 延迟毫秒", default=0)
    http_status = models.IntegerField("HTTP 状态码", null=True, blank=True)
    binance_error_code = models.CharField("Binance 错误码", max_length=80, blank=True)
    sanitized_error_message = models.CharField("脱敏错误摘要", max_length=500, blank=True)
    exchange_order_id_returned = models.CharField("返回的交易所订单 ID", max_length=120, blank=True)
    exchange_client_order_id_returned = models.CharField("返回的 clientOrderId", max_length=120, blank=True)
    exchange_status = models.CharField("交易所订单状态", max_length=80, blank=True)
    exchange_status_observed_at_utc = models.DateTimeField("状态观测 UTC 时间", null=True, blank=True)
    is_recognized_status = models.BooleanField("是否识别交易所状态", default=False)
    is_terminal_status = models.BooleanField("是否明确终态", default=False)
    terminal_policy_version = models.CharField("终态识别规则版本", max_length=40, default="1.0")
    submission_resolution_status = models.CharField(
        "提交结果解析状态",
        max_length=40,
        choices=OrderStatusSubmissionResolution.choices,
        default=OrderStatusSubmissionResolution.UNRESOLVED,
    )
    sanitized_response = models.JSONField("脱敏交易所响应", default=dict, blank=True)
    response_hash = models.CharField("交易所响应 hash", max_length=80, blank=True)
    rate_limit_metadata = models.JSONField("限频元数据", default=dict, blank=True)
    alert_event_ids = models.JSONField("AlertEvent ID", default=list, blank=True)
    trace_id = models.CharField("技术追踪 ID", max_length=80)
    trigger_source = models.CharField("触发来源", max_length=80)
    created_at_utc = models.DateTimeField("创建 UTC 时间", auto_now_add=True)
    updated_at_utc = models.DateTimeField("更新 UTC 时间", auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["order_submission_attempt", "poll_mode", "poll_sequence"],
                name="uniq_order_status_sync_attempt_mode_sequence",
            )
        ]
        indexes = [
            models.Index(fields=["order_submission_attempt", "poll_mode", "poll_sequence"]),
            models.Index(fields=["query_outcome", "created_at_utc"]),
            models.Index(fields=["is_terminal_status", "created_at_utc"]),
            models.Index(fields=["market_type", "account_domain", "symbol"]),
            models.Index(fields=["trace_id"]),
        ]

    def __str__(self) -> str:
        return f"OrderStatusSyncRecord<{self.order_submission_attempt_id}:{self.poll_mode}:{self.poll_sequence}>"
