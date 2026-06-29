"""RiskCheck 模块：定义风控规则、审批结果和 ApprovedOrderIntent 事实；读写 MySQL；不访问 Redis；不访问 Binance；不发送 Hermes；不调用大模型；审批但不提交订单；不允许真实交易。"""

from __future__ import annotations

from django.db import models


class RiskRuleSetStatus(models.TextChoices):
    ACTIVE = "active", "启用"
    DISABLED = "disabled", "停用"


class RiskRuleDefinitionStatus(models.TextChoices):
    DRAFT = "draft", "草稿"
    ACTIVE = "active", "启用"
    DEPRECATED = "deprecated", "已废弃"
    RETIRED = "retired", "已退役"
    DISABLED = "disabled", "停用"


class RiskRuleResultStatus(models.TextChoices):
    PASS = "PASS", "通过"
    DENY = "DENY", "拒绝"
    BLOCKED = "BLOCKED", "阻断"
    FAILED = "FAILED", "失败"


class RiskCheckStatus(models.TextChoices):
    ALLOW = "ALLOW", "允许"
    DENY = "DENY", "拒绝"
    BLOCKED = "BLOCKED", "阻断"
    FAILED = "FAILED", "失败"


class ApprovedOrderIntentStatus(models.TextChoices):
    APPROVED = "approved", "已审批通过"
    EXPIRED = "expired", "已过期"
    CANCELED = "canceled", "已取消"
    CONSUMED = "consumed", "已进入执行准备"
    EXECUTION_PREPARED = "execution_prepared", "执行准备完成"
    PREPARATION_BLOCKED = "preparation_blocked", "执行准备阻断"
    PREPARATION_FAILED = "preparation_failed", "执行准备失败"
    PREPARATION_EXPIRED = "preparation_expired", "执行准备过期"


class RiskRuleSet(models.Model):
    rule_set_code = models.CharField("规则集代码", max_length=120, unique=True)
    description_zh = models.CharField("中文说明", max_length=300, blank=True)
    status = models.CharField("状态", max_length=40, choices=RiskRuleSetStatus.choices, default=RiskRuleSetStatus.ACTIVE)
    enabled = models.BooleanField("是否启用", default=True)
    rule_set_hash = models.CharField("规则集 hash", max_length=80, blank=True)
    created_at_utc = models.DateTimeField("创建 UTC 时间", auto_now_add=True)
    updated_at_utc = models.DateTimeField("更新 UTC 时间", auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["status", "enabled"]),
            models.Index(fields=["rule_set_hash"]),
        ]


class RiskRuleDefinition(models.Model):
    risk_rule_set = models.ForeignKey(RiskRuleSet, on_delete=models.PROTECT, related_name="rule_definitions")
    rule_code = models.CharField("规则代码", max_length=120)
    rule_version = models.CharField("规则版本", max_length=40)
    algorithm_name = models.CharField("算法名称", max_length=120)
    algorithm_version = models.CharField("算法版本", max_length=40)
    params = models.JSONField("规则参数", default=dict, blank=True)
    params_hash = models.CharField("参数 hash", max_length=80)
    definition_hash = models.CharField("定义 hash", max_length=80)
    status = models.CharField(
        "状态",
        max_length=40,
        choices=RiskRuleDefinitionStatus.choices,
        default=RiskRuleDefinitionStatus.ACTIVE,
    )
    enabled = models.BooleanField("是否启用", default=True)
    severity = models.CharField("严重级别", max_length=40, default="warning")
    execution_order = models.PositiveIntegerField("执行顺序", default=100)
    applicable_market_types = models.JSONField("适用市场类型", default=list)
    description_zh = models.CharField("中文说明", max_length=300, blank=True)
    created_at_utc = models.DateTimeField("创建 UTC 时间", auto_now_add=True)
    updated_at_utc = models.DateTimeField("更新 UTC 时间", auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["risk_rule_set", "rule_code", "rule_version"],
                name="uniq_risk_rule_definition_version",
            )
        ]
        indexes = [
            models.Index(fields=["rule_code", "status", "enabled"]),
            models.Index(fields=["execution_order"]),
            models.Index(fields=["definition_hash"]),
        ]


class RiskCheckResult(models.Model):
    business_request_key = models.CharField("业务幂等键", max_length=191)
    risk_check_key = models.CharField("风控幂等键", max_length=191, unique=True)
    status = models.CharField("风控状态", max_length=40, choices=RiskCheckStatus.choices)
    is_usable = models.BooleanField("是否可用", default=False)
    allows_downstream = models.BooleanField("是否允许进入执行准备", default=False)
    selected_candidate_order_intent = models.ForeignKey(
        "order_plan.CandidateOrderIntent",
        on_delete=models.PROTECT,
        related_name="selected_by_risk_checks",
        null=True,
        blank=True,
    )
    selected_intent_role = models.CharField("选中候选角色", max_length=40, blank=True)
    order_plan = models.ForeignKey("order_plan.OrderPlan", on_delete=models.PROTECT, related_name="risk_check_results")
    primary_candidate_order_intent = models.ForeignKey(
        "order_plan.CandidateOrderIntent",
        on_delete=models.PROTECT,
        related_name="primary_risk_check_results",
    )
    fallback_candidate_order_intent = models.ForeignKey(
        "order_plan.CandidateOrderIntent",
        on_delete=models.PROTECT,
        related_name="fallback_risk_check_results",
        null=True,
        blank=True,
    )
    binance_sync_run = models.ForeignKey(
        "binance_account_sync.BinanceSyncRun",
        on_delete=models.PROTECT,
        related_name="risk_check_results",
    )
    binance_snapshot_set_hash = models.CharField("账户快照集合 hash", max_length=80)
    account_snapshot = models.ForeignKey(
        "binance_account_sync.BinanceAccountSnapshot",
        on_delete=models.PROTECT,
        related_name="risk_check_results",
    )
    balance_snapshot = models.ForeignKey(
        "binance_account_sync.BinanceBalanceSnapshot",
        on_delete=models.PROTECT,
        related_name="risk_check_results",
    )
    position_snapshot = models.ForeignKey(
        "binance_account_sync.BinancePositionSnapshot",
        on_delete=models.PROTECT,
        related_name="risk_check_results",
    )
    symbol_rule_snapshot = models.ForeignKey(
        "binance_account_sync.BinanceSymbolRuleSnapshot",
        on_delete=models.PROTECT,
        related_name="risk_check_results",
    )
    price_snapshot = models.ForeignKey(
        "price_snapshot.PriceSnapshot",
        on_delete=models.PROTECT,
        related_name="risk_check_results",
    )
    price_snapshot_hash = models.CharField("价格快照 hash", max_length=80)
    active_lock = models.ForeignKey("order_plan.OrderPlanActiveLock", on_delete=models.PROTECT, related_name="risk_check_results")
    rule_set_hash = models.CharField("规则集 hash", max_length=80)
    checked_rules = models.JSONField("已检查规则", default=list)
    risk_measures = models.JSONField("风险度量", default=dict)
    risk_config_snapshot = models.JSONField("风控配置快照", default=dict)
    input_snapshot = models.JSONField("输入快照", default=dict)
    risk_snapshot = models.JSONField("风控结果快照", default=dict)
    evidence_items = models.JSONField("证据条目", default=list)
    evidence_text_zh = models.TextField("中文证据摘要", blank=True)
    reason_code = models.CharField("原因代码", max_length=120)
    error_code = models.CharField("错误代码", max_length=120, blank=True)
    error_message = models.CharField("错误摘要", max_length=500, blank=True)
    alert_event_ids = models.JSONField("AlertEvent ID", default=list, blank=True)
    trace_id = models.CharField("技术追踪 ID", max_length=80)
    trigger_source = models.CharField("触发来源", max_length=80)
    created_at_utc = models.DateTimeField("创建 UTC 时间", auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["status", "created_at_utc"]),
            models.Index(fields=["order_plan"]),
            models.Index(fields=["primary_candidate_order_intent"]),
            models.Index(fields=["selected_candidate_order_intent"]),
            models.Index(fields=["trace_id"]),
            models.Index(fields=["rule_set_hash"]),
        ]


class RiskRuleResult(models.Model):
    risk_check_result = models.ForeignKey(RiskCheckResult, on_delete=models.PROTECT, related_name="rule_results")
    rule_definition = models.ForeignKey(RiskRuleDefinition, on_delete=models.PROTECT, related_name="rule_results")
    rule_code = models.CharField("规则代码", max_length=120)
    rule_version = models.CharField("规则版本", max_length=40)
    status = models.CharField("结果", max_length=40, choices=RiskRuleResultStatus.choices)
    severity = models.CharField("严重级别", max_length=40)
    reason_code = models.CharField("原因代码", max_length=120)
    message_zh = models.CharField("中文说明", max_length=500)
    risk_measures = models.JSONField("风险度量", default=dict, blank=True)
    evidence = models.JSONField("证据", default=dict, blank=True)
    definition_hash = models.CharField("定义 hash", max_length=80)
    params_hash = models.CharField("参数 hash", max_length=80)
    started_at_utc = models.DateTimeField("开始 UTC 时间")
    finished_at_utc = models.DateTimeField("完成 UTC 时间")

    class Meta:
        indexes = [
            models.Index(fields=["risk_check_result", "status"]),
            models.Index(fields=["rule_code"]),
        ]


class RiskCheckIssue(models.Model):
    risk_check_result = models.ForeignKey(RiskCheckResult, on_delete=models.PROTECT, related_name="issues")
    rule_result = models.ForeignKey(
        RiskRuleResult,
        on_delete=models.PROTECT,
        related_name="issues",
        null=True,
        blank=True,
    )
    issue_code = models.CharField("问题代码", max_length=120)
    severity = models.CharField("严重级别", max_length=40)
    message_zh = models.CharField("中文说明", max_length=500)
    evidence = models.JSONField("证据", default=dict, blank=True)
    created_at_utc = models.DateTimeField("创建 UTC 时间", auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["risk_check_result", "issue_code"]),
            models.Index(fields=["severity", "created_at_utc"]),
        ]


class ApprovedOrderIntent(models.Model):
    time_in_force = models.CharField("timeInForce", max_length=40, blank=True)
    limit_price = models.DecimalField("LIMIT price", max_digits=38, decimal_places=18, null=True, blank=True)
    limit_valid_until_utc = models.DateTimeField("LIMIT valid until UTC", null=True, blank=True)
    price_condition_hash = models.CharField("price condition hash", max_length=80, blank=True)
    price_condition_evidence = models.JSONField("price condition evidence", default=dict, blank=True)
    business_request_key = models.CharField("业务幂等键", max_length=191)
    risk_check_result = models.OneToOneField(
        RiskCheckResult,
        on_delete=models.PROTECT,
        related_name="approved_order_intent",
    )
    candidate_order_intent = models.OneToOneField(
        "order_plan.CandidateOrderIntent",
        on_delete=models.PROTECT,
        related_name="approved_order_intent",
    )
    order_plan = models.ForeignKey("order_plan.OrderPlan", on_delete=models.PROTECT, related_name="approved_order_intents")
    binance_sync_run = models.ForeignKey(
        "binance_account_sync.BinanceSyncRun",
        on_delete=models.PROTECT,
        related_name="approved_order_intents",
    )
    price_snapshot = models.ForeignKey(
        "price_snapshot.PriceSnapshot",
        on_delete=models.PROTECT,
        related_name="approved_order_intents",
    )
    active_lock = models.ForeignKey("order_plan.OrderPlanActiveLock", on_delete=models.PROTECT, related_name="approved_order_intents")
    exchange = models.CharField("交易所", max_length=40, default="binance")
    market_type = models.CharField("市场类型", max_length=40)
    account_domain = models.CharField("账户域", max_length=120)
    symbol = models.CharField("交易品种", max_length=40)
    side = models.CharField("订单方向", max_length=10)
    position_side = models.CharField("持仓方向", max_length=20)
    order_type = models.CharField("订单类型", max_length=40)
    exchange_reduce_only = models.BooleanField("交易所 reduceOnly")
    requested_size = models.DecimalField("审批通过数量", max_digits=38, decimal_places=18)
    requested_notional = models.DecimalField("审批通过名义价值", max_digits=38, decimal_places=18)
    requested_size_unit = models.CharField("数量单位", max_length=40)
    selected_intent_role = models.CharField("选中候选角色", max_length=40)
    order_components = models.JSONField("冻结订单组件", default=list)
    candidate_intent_hash = models.CharField("候选意图 hash", max_length=80)
    risk_check_hash = models.CharField("风控结果 hash", max_length=80)
    rule_set_hash = models.CharField("规则集 hash", max_length=80)
    price_snapshot_hash = models.CharField("价格快照 hash", max_length=80)
    binance_snapshot_set_hash = models.CharField("账户快照集合 hash", max_length=80)
    status = models.CharField(
        "状态",
        max_length=40,
        choices=ApprovedOrderIntentStatus.choices,
        default=ApprovedOrderIntentStatus.APPROVED,
    )
    expires_at_utc = models.DateTimeField("过期 UTC 时间")
    evidence = models.JSONField("审批证据", default=dict, blank=True)
    trace_id = models.CharField("技术追踪 ID", max_length=80)
    trigger_source = models.CharField("触发来源", max_length=80)
    created_at_utc = models.DateTimeField("创建 UTC 时间", auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["status", "expires_at_utc"]),
            models.Index(fields=["market_type", "account_domain", "symbol"]),
            models.Index(fields=["trace_id"]),
            models.Index(fields=["risk_check_hash"]),
        ]
