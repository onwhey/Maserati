"""ExecutionPreparation 模块：定义执行前检查结果和待提交订单请求；读写 MySQL；不访问 Redis；不访问 Binance；不发送 Hermes；不调用大模型；只准备不提交；不允许真实交易。"""

from __future__ import annotations

from django.db import models


class ExecutionPreparationStatus(models.TextChoices):
    PREPARING = "PREPARING", "准备中"
    PREPARED = "PREPARED", "已准备"
    BLOCKED = "BLOCKED", "已阻断"
    FAILED = "FAILED", "失败"
    EXPIRED = "EXPIRED", "已过期"


class PreparedOrderIntentStatus(models.TextChoices):
    PREPARED = "prepared", "待提交"
    EXPIRED = "expired", "已过期"
    CONSUMED = "consumed", "已进入执行"


class ExecutionPreparationResult(models.Model):
    business_request_key = models.CharField("业务幂等键", max_length=191)
    execution_preparation_key = models.CharField("执行准备幂等键", max_length=191, unique=True)
    status = models.CharField("执行准备状态", max_length=40, choices=ExecutionPreparationStatus.choices)
    reason_code = models.CharField("原因代码", max_length=120)
    reason_message = models.CharField("原因说明", max_length=500, blank=True)

    approved_order_intent = models.OneToOneField(
        "risk_check.ApprovedOrderIntent",
        on_delete=models.PROTECT,
        related_name="execution_preparation_result",
    )
    risk_check_result = models.ForeignKey(
        "risk_check.RiskCheckResult",
        on_delete=models.PROTECT,
        related_name="execution_preparation_results",
    )
    candidate_order_intent = models.ForeignKey(
        "order_plan.CandidateOrderIntent",
        on_delete=models.PROTECT,
        related_name="execution_preparation_results",
    )
    order_plan = models.ForeignKey(
        "order_plan.OrderPlan",
        on_delete=models.PROTECT,
        related_name="execution_preparation_results",
    )
    active_lock = models.ForeignKey(
        "order_plan.OrderPlanActiveLock",
        on_delete=models.PROTECT,
        related_name="execution_preparation_results",
    )
    price_snapshot = models.ForeignKey(
        "price_snapshot.PriceSnapshot",
        on_delete=models.PROTECT,
        related_name="execution_preparation_results",
    )
    binance_sync_run = models.ForeignKey(
        "binance_account_sync.BinanceSyncRun",
        on_delete=models.PROTECT,
        related_name="execution_preparation_results",
    )
    account_snapshot = models.ForeignKey(
        "binance_account_sync.BinanceAccountSnapshot",
        on_delete=models.PROTECT,
        related_name="execution_preparation_results",
    )
    position_snapshot = models.ForeignKey(
        "binance_account_sync.BinancePositionSnapshot",
        on_delete=models.PROTECT,
        related_name="execution_preparation_results",
    )
    symbol_rule_snapshot = models.ForeignKey(
        "binance_account_sync.BinanceSymbolRuleSnapshot",
        on_delete=models.PROTECT,
        related_name="execution_preparation_results",
    )

    price_snapshot_hash = models.CharField("价格快照 hash", max_length=80)
    binance_snapshot_set_hash = models.CharField("账户快照集合 hash", max_length=80)
    reference_mark_price = models.DecimalField("参考 mark price", max_digits=38, decimal_places=18, null=True, blank=True)
    best_bid_price = models.DecimalField("最优买价", max_digits=38, decimal_places=18, null=True, blank=True)
    best_bid_quantity = models.DecimalField("最优买量", max_digits=38, decimal_places=18, null=True, blank=True)
    best_ask_price = models.DecimalField("最优卖价", max_digits=38, decimal_places=18, null=True, blank=True)
    best_ask_quantity = models.DecimalField("最优卖量", max_digits=38, decimal_places=18, null=True, blank=True)
    selected_live_price = models.DecimalField("执行侧参考盘口价", max_digits=38, decimal_places=18, null=True, blank=True)
    selected_live_price_side = models.CharField("选中盘口侧", max_length=20, blank=True)
    price_deviation_ratio = models.DecimalField("价格偏差比例", max_digits=30, decimal_places=18, null=True, blank=True)
    price_deviation_bps = models.DecimalField("价格偏差 bps", max_digits=30, decimal_places=12, null=True, blank=True)
    price_deviation_limit_bps = models.DecimalField("价格偏差上限 bps", max_digits=30, decimal_places=12, null=True, blank=True)
    live_price_requested_at_utc = models.DateTimeField("盘口请求 UTC 时间", null=True, blank=True)
    live_price_observed_at_utc = models.DateTimeField("盘口观测 UTC 时间", null=True, blank=True)

    gateway_result_metadata = models.JSONField("Gateway 结果元数据", default=dict, blank=True)
    config_snapshot = models.JSONField("配置快照", default=dict)
    input_hash = models.CharField("输入 hash", max_length=80)
    evidence = models.JSONField("执行准备证据", default=dict, blank=True)
    alert_event_ids = models.JSONField("AlertEvent ID", default=list, blank=True)
    trace_id = models.CharField("技术追踪 ID", max_length=80)
    trigger_source = models.CharField("触发来源", max_length=80)
    started_at_utc = models.DateTimeField("开始 UTC 时间")
    finished_at_utc = models.DateTimeField("完成 UTC 时间", null=True, blank=True)
    created_at_utc = models.DateTimeField("创建 UTC 时间", auto_now_add=True)
    updated_at_utc = models.DateTimeField("更新 UTC 时间", auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["status", "created_at_utc"]),
            models.Index(fields=["order_plan"]),
            models.Index(fields=["risk_check_result"]),
            models.Index(fields=["candidate_order_intent"]),
            models.Index(fields=["trace_id"]),
        ]


class PreparedOrderIntent(models.Model):
    prepared_order_intent_key = models.CharField("待提交请求幂等键", max_length=191, unique=True)
    execution_preparation_result = models.OneToOneField(
        ExecutionPreparationResult,
        on_delete=models.PROTECT,
        related_name="prepared_order_intent",
    )
    source_approved_order_intent = models.OneToOneField(
        "risk_check.ApprovedOrderIntent",
        on_delete=models.PROTECT,
        related_name="prepared_order_intent",
    )
    source_risk_check_result = models.ForeignKey(
        "risk_check.RiskCheckResult",
        on_delete=models.PROTECT,
        related_name="prepared_order_intents",
    )
    source_candidate_order_intent = models.ForeignKey(
        "order_plan.CandidateOrderIntent",
        on_delete=models.PROTECT,
        related_name="prepared_order_intents",
    )
    source_order_plan = models.ForeignKey(
        "order_plan.OrderPlan",
        on_delete=models.PROTECT,
        related_name="prepared_order_intents",
    )
    exchange = models.CharField("交易所", max_length=40, default="binance")
    market_type = models.CharField("市场类型", max_length=40)
    account_domain = models.CharField("账户域", max_length=120)
    symbol = models.CharField("交易品种", max_length=40)
    position_mode = models.CharField("持仓模式", max_length=40)
    position_side = models.CharField("持仓方向", max_length=20)
    side = models.CharField("订单方向", max_length=10)
    order_type = models.CharField("订单类型", max_length=40)
    quantity = models.DecimalField("冻结数量", max_digits=38, decimal_places=18)
    quantity_unit = models.CharField("数量单位", max_length=40)
    reduce_only = models.BooleanField("reduceOnly")
    time_in_force = models.CharField("timeInForce", max_length=40, blank=True)
    client_order_id = models.CharField("Binance clientOrderId", max_length=36, unique=True)
    idempotency_key = models.CharField("订单提交幂等键", max_length=191, unique=True)
    price_snapshot = models.ForeignKey(
        "price_snapshot.PriceSnapshot",
        on_delete=models.PROTECT,
        related_name="prepared_order_intents",
    )
    reference_mark_price = models.DecimalField("参考 mark price", max_digits=38, decimal_places=18)
    selected_live_price = models.DecimalField("执行侧参考盘口价", max_digits=38, decimal_places=18)
    price_deviation_bps = models.DecimalField("价格偏差 bps", max_digits=30, decimal_places=12)
    binance_sync_run = models.ForeignKey(
        "binance_account_sync.BinanceSyncRun",
        on_delete=models.PROTECT,
        related_name="prepared_order_intents",
    )
    account_snapshot = models.ForeignKey(
        "binance_account_sync.BinanceAccountSnapshot",
        on_delete=models.PROTECT,
        related_name="prepared_order_intents",
    )
    position_snapshot = models.ForeignKey(
        "binance_account_sync.BinancePositionSnapshot",
        on_delete=models.PROTECT,
        related_name="prepared_order_intents",
    )
    symbol_rule_snapshot = models.ForeignKey(
        "binance_account_sync.BinanceSymbolRuleSnapshot",
        on_delete=models.PROTECT,
        related_name="prepared_order_intents",
    )
    prepared_at_utc = models.DateTimeField("准备完成 UTC 时间")
    expires_at_utc = models.DateTimeField("过期 UTC 时间")
    status = models.CharField(
        "状态",
        max_length=40,
        choices=PreparedOrderIntentStatus.choices,
        default=PreparedOrderIntentStatus.PREPARED,
    )
    trigger_source = models.CharField("触发来源", max_length=80)
    config_snapshot = models.JSONField("配置快照", default=dict)
    evidence_hash = models.CharField("证据 hash", max_length=80)
    created_at_utc = models.DateTimeField("创建 UTC 时间", auto_now_add=True)
    updated_at_utc = models.DateTimeField("更新 UTC 时间", auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["status", "expires_at_utc"]),
            models.Index(fields=["market_type", "account_domain", "symbol"]),
            models.Index(fields=["source_order_plan"]),
            models.Index(fields=["client_order_id"]),
        ]
