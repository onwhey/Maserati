"""OrderPlan 模块：定义订单计划、候选订单意图和 ActiveLock 事实；读写 MySQL；不访问 Redis 或外部服务；不发送 Hermes；不调用大模型；不提交订单；不允许真实交易。"""

from __future__ import annotations

from django.db import models


class OrderPlanStatus(models.TextChoices):
    CREATED = "created", "已创建"
    NO_ORDER_REQUIRED = "no_order_required", "无需调仓"
    BLOCKED = "blocked", "已阻断"
    FAILED = "failed", "失败"
    PREPARATION_BLOCKED = "preparation_blocked", "执行准备阻断"
    PREPARATION_FAILED = "preparation_failed", "执行准备失败"
    PREPARATION_EXPIRED = "preparation_expired", "执行准备过期"


class CandidateIntentRole(models.TextChoices):
    PRIMARY = "primary", "主候选意图"
    FALLBACK_REDUCE_ONLY = "fallback_reduce_only", "只减仓后备意图"


class CandidateIntentStatus(models.TextChoices):
    PENDING_RISK_CHECK = "pending_risk_check", "等待风控"
    APPROVED = "approved", "已通过风控"
    DENIED = "denied", "风控拒绝"
    BLOCKED = "blocked", "风控阻断"
    CANCELED = "canceled", "已取消"


class ActiveLockStatus(models.TextChoices):
    ACTIVE = "active", "保护中"
    RELEASED = "released", "已释放"
    FAILED = "failed", "收尾异常"


class OrderPlan(models.Model):
    business_request_key = models.CharField("业务幂等键", max_length=191, unique=True)
    decision_snapshot = models.ForeignKey(
        "strategy_analysis.DecisionSnapshot",
        on_delete=models.PROTECT,
        related_name="order_plans",
    )
    binance_sync_run = models.ForeignKey(
        "binance_account_sync.BinanceSyncRun",
        on_delete=models.PROTECT,
        related_name="order_plans",
    )
    account_snapshot = models.ForeignKey(
        "binance_account_sync.BinanceAccountSnapshot",
        on_delete=models.PROTECT,
        related_name="order_plans",
    )
    balance_snapshot = models.ForeignKey(
        "binance_account_sync.BinanceBalanceSnapshot",
        on_delete=models.PROTECT,
        related_name="order_plans",
    )
    position_snapshot = models.ForeignKey(
        "binance_account_sync.BinancePositionSnapshot",
        on_delete=models.PROTECT,
        related_name="order_plans",
    )
    symbol_rule_snapshot = models.ForeignKey(
        "binance_account_sync.BinanceSymbolRuleSnapshot",
        on_delete=models.PROTECT,
        related_name="order_plans",
    )
    price_snapshot = models.ForeignKey(
        "price_snapshot.PriceSnapshot",
        on_delete=models.PROTECT,
        related_name="order_plans",
    )
    active_lock = models.ForeignKey(
        "OrderPlanActiveLock",
        on_delete=models.PROTECT,
        related_name="order_plans",
        null=True,
        blank=True,
    )
    exchange = models.CharField("交易所", max_length=40, default="binance")
    market_type = models.CharField("市场类型", max_length=40)
    account_domain = models.CharField("账户域", max_length=120)
    symbol = models.CharField("交易品种", max_length=40)
    position_mode = models.CharField("持仓模式", max_length=40)
    target_position_ratio = models.DecimalField(
        "目标总仓位比例",
        max_digits=20,
        decimal_places=18,
        null=True,
        blank=True,
    )
    current_equity = models.DecimalField("当前账户权益", max_digits=38, decimal_places=18)
    current_signed_size = models.DecimalField("当前有符号仓位", max_digits=38, decimal_places=18)
    raw_target_signed_size = models.DecimalField("原始目标有符号仓位", max_digits=38, decimal_places=18)
    target_signed_size = models.DecimalField("规范化目标有符号仓位", max_digits=38, decimal_places=18)
    delta_signed_size = models.DecimalField("有符号调仓差额", max_digits=38, decimal_places=18)
    mark_price = models.DecimalField("绑定标记价格", max_digits=38, decimal_places=18)
    target_notional = models.DecimalField("目标名义价值", max_digits=38, decimal_places=18)
    normalized_order_notional = models.DecimalField("规范化订单名义价值", max_digits=38, decimal_places=18)
    min_rebalance_notional = models.DecimalField("最小调仓名义阈值", max_digits=38, decimal_places=18)
    max_target_notional_to_equity_ratio = models.DecimalField(
        "目标名义相对权益上限比例",
        max_digits=20,
        decimal_places=18,
    )
    status = models.CharField("状态", max_length=40, choices=OrderPlanStatus.choices)
    reason_code = models.CharField("原因代码", max_length=120, blank=True)
    allows_downstream = models.BooleanField("是否允许进入风控", default=False)
    config_snapshot = models.JSONField("配置快照", default=dict)
    calculation_evidence = models.JSONField("计算证据", default=dict)
    order_plan_hash = models.CharField("订单计划指纹", max_length=80)
    trace_id = models.CharField("技术追踪 ID", max_length=80)
    trigger_source = models.CharField("触发来源", max_length=80)
    created_at_utc = models.DateTimeField("创建 UTC 时间", auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["market_type", "account_domain", "symbol", "status"]),
            models.Index(fields=["decision_snapshot"]),
            models.Index(fields=["binance_sync_run"]),
            models.Index(fields=["price_snapshot"]),
            models.Index(fields=["trace_id"]),
            models.Index(fields=["order_plan_hash"]),
        ]


class OrderPlanActiveLock(models.Model):
    exchange = models.CharField("交易所", max_length=40, default="binance")
    market_type = models.CharField("市场类型", max_length=40)
    account_domain = models.CharField("账户域", max_length=120)
    symbol = models.CharField("交易品种", max_length=40)
    status = models.CharField("锁状态", max_length=40, choices=ActiveLockStatus.choices)
    current_order_plan = models.ForeignKey(
        OrderPlan,
        on_delete=models.PROTECT,
        related_name="held_active_locks",
        null=True,
        blank=True,
    )
    acquired_at_utc = models.DateTimeField("取得 UTC 时间", null=True, blank=True)
    released_at_utc = models.DateTimeField("释放 UTC 时间", null=True, blank=True)
    failed_at_utc = models.DateTimeField("异常 UTC 时间", null=True, blank=True)
    reason_code = models.CharField("当前原因代码", max_length=120, blank=True)
    version = models.PositiveBigIntegerField("状态版本", default=1)
    created_at_utc = models.DateTimeField("创建 UTC 时间", auto_now_add=True)
    updated_at_utc = models.DateTimeField("更新 UTC 时间", auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["exchange", "market_type", "account_domain", "symbol"],
                name="uniq_order_plan_active_lock_identity",
            )
        ]
        indexes = [
            models.Index(fields=["status", "updated_at_utc"]),
            models.Index(fields=["current_order_plan"]),
        ]


class OrderPlanActiveLockEvent(models.Model):
    event_key = models.CharField("锁事件幂等键", max_length=191, unique=True)
    active_lock = models.ForeignKey(
        OrderPlanActiveLock,
        on_delete=models.PROTECT,
        related_name="events",
    )
    order_plan = models.ForeignKey(
        OrderPlan,
        on_delete=models.PROTECT,
        related_name="active_lock_events",
        null=True,
        blank=True,
    )
    event_type = models.CharField("事件类型", max_length=80)
    from_status = models.CharField("原状态", max_length=40, blank=True)
    to_status = models.CharField("新状态", max_length=40)
    reason_code = models.CharField("原因代码", max_length=120)
    evidence = models.JSONField("收尾或取得证据", default=dict)
    operator_id = models.CharField("人工操作人", max_length=120, blank=True)
    trace_id = models.CharField("技术追踪 ID", max_length=80)
    trigger_source = models.CharField("触发来源", max_length=80)
    created_at_utc = models.DateTimeField("创建 UTC 时间", auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["active_lock", "created_at_utc"]),
            models.Index(fields=["order_plan"]),
            models.Index(fields=["trace_id"]),
        ]


class CandidateOrderIntent(models.Model):
    time_in_force = models.CharField("timeInForce", max_length=40, blank=True)
    limit_price = models.DecimalField("LIMIT price", max_digits=38, decimal_places=18, null=True, blank=True)
    limit_valid_until_utc = models.DateTimeField("LIMIT valid until UTC", null=True, blank=True)
    price_condition_hash = models.CharField("price condition hash", max_length=80, blank=True)
    price_condition_evidence = models.JSONField("price condition evidence", default=dict, blank=True)
    order_plan = models.ForeignKey(OrderPlan, on_delete=models.PROTECT, related_name="candidate_intents")
    intent_role = models.CharField("候选意图角色", max_length=40, choices=CandidateIntentRole.choices)
    symbol = models.CharField("交易品种", max_length=40)
    market_type = models.CharField("市场类型", max_length=40)
    account_domain = models.CharField("账户域", max_length=120)
    position_mode = models.CharField("持仓模式", max_length=40)
    order_type = models.CharField("订单类型", max_length=40, default="MARKET")
    plan_type = models.CharField("仓位转换类型", max_length=80)
    side = models.CharField("订单方向", max_length=10)
    position_side = models.CharField("持仓方向", max_length=20, default="BOTH")
    exchange_reduce_only = models.BooleanField("交易所 reduceOnly", default=False)
    requested_size = models.DecimalField("请求数量", max_digits=38, decimal_places=18)
    requested_notional = models.DecimalField("请求名义价值", max_digits=38, decimal_places=18)
    requested_size_unit = models.CharField("请求数量单位", max_length=40)
    price_snapshot = models.ForeignKey(
        "price_snapshot.PriceSnapshot",
        on_delete=models.PROTECT,
        related_name="candidate_order_intents",
    )
    reference_mark_price = models.DecimalField("参考标记价格", max_digits=38, decimal_places=18)
    binance_sync_run = models.ForeignKey(
        "binance_account_sync.BinanceSyncRun",
        on_delete=models.PROTECT,
        related_name="candidate_order_intents",
    )
    current_position_snapshot = models.ForeignKey(
        "binance_account_sync.BinancePositionSnapshot",
        on_delete=models.PROTECT,
        related_name="candidate_order_intents",
    )
    symbol_rule_snapshot = models.ForeignKey(
        "binance_account_sync.BinanceSymbolRuleSnapshot",
        on_delete=models.PROTECT,
        related_name="candidate_order_intents",
    )
    current_position_signed_size = models.DecimalField("当前有符号仓位", max_digits=38, decimal_places=18)
    target_position_signed_size = models.DecimalField("目标有符号仓位", max_digits=38, decimal_places=18)
    delta_signed_size = models.DecimalField("有符号调仓差额", max_digits=38, decimal_places=18)
    closing_size = models.DecimalField("平旧仓数量", max_digits=38, decimal_places=18, default=0)
    opening_size = models.DecimalField("开新仓数量", max_digits=38, decimal_places=18, default=0)
    residual_position_size = models.DecimalField("不可交易残余仓位", max_digits=38, decimal_places=18, default=0)
    order_components = models.JSONField("订单风险组件", default=list)
    status = models.CharField(
        "状态",
        max_length=40,
        choices=CandidateIntentStatus.choices,
        default=CandidateIntentStatus.PENDING_RISK_CHECK,
    )
    reason_code = models.CharField("原因代码", max_length=120, blank=True)
    evidence = models.JSONField("证据", default=dict)
    intent_hash = models.CharField("候选意图指纹", max_length=80)
    trace_id = models.CharField("技术追踪 ID", max_length=80)
    created_at_utc = models.DateTimeField("创建 UTC 时间", auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["order_plan", "intent_role"],
                name="uniq_candidate_intent_role_per_plan",
            )
        ]
        indexes = [
            models.Index(fields=["status", "created_at_utc"]),
            models.Index(fields=["market_type", "account_domain", "symbol"]),
            models.Index(fields=["intent_hash"]),
            models.Index(fields=["trace_id"]),
        ]
