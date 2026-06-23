"""StrategyAnalysis 模块：定义版本包与 FeatureLayer 事实；读写数据库，不访问 Redis 或外部服务，不涉及交易执行。"""

from __future__ import annotations

from django.db import models
from django.utils import timezone


class ReleaseApprovalStatus(models.TextChoices):
    DRAFT = "draft", "草稿"
    VALIDATING = "validating", "待验证"
    APPROVED = "approved", "已批准"
    REJECTED = "rejected", "已拒绝"
    INVALIDATED = "invalidated", "已失效"


class ReleaseAction(models.TextChoices):
    APPROVE = "approve", "批准"
    REJECT = "reject", "拒绝"
    INVALIDATE = "invalidate", "失效"
    ACTIVATE = "activate", "启用"
    DEACTIVATE = "deactivate", "停用"
    ROLLBACK = "rollback", "回滚"


class ReleaseItemComponentType(models.TextChoices):
    FEATURE_DEFINITION = "feature_definition", "特征定义"
    ATOMIC_SIGNAL_DEFINITION = "atomic_signal_definition", "原子信号定义"
    DOMAIN_SIGNAL_DEFINITION = "domain_signal_definition", "领域定义"
    MARKET_REGIME_DEFINITION = "market_regime_definition", "市场环境定义"
    STRATEGY_ROUTE_POLICY = "strategy_route_policy", "策略路由策略"
    STRATEGY_ROUTE_RULE = "strategy_route_rule", "策略路由规则"
    STRATEGY_DEFINITION = "strategy_definition", "策略定义"
    STRATEGY_SIGNAL_QUALITY_RULE_SET = "strategy_signal_quality_rule_set", "策略信号质量规则集"
    DECISION_POLICY_DEFINITION = "decision_policy_definition", "目标仓位决策定义"


class AnalysisObjectStatus(models.TextChoices):
    CREATED = "created", "已创建"
    BLOCKED = "blocked", "阻断"
    FAILED = "failed", "失败"
    UNKNOWN = "unknown", "未知"


class FeatureValueType(models.TextChoices):
    DECIMAL = "decimal", "数值"
    BOOLEAN = "boolean", "布尔"
    TEXT = "text", "文本"


class DefinitionLifecycleStatus(models.TextChoices):
    DRAFT = "draft", "草稿"
    ACTIVE = "active", "可用"
    DEPRECATED = "deprecated", "已弃用"
    RETIRED = "retired", "已退役"
    DISABLED = "disabled", "已禁用"


class AtomicSignalDirection(models.TextChoices):
    BULLISH = "bullish", "偏多"
    BEARISH = "bearish", "偏空"
    NEUTRAL = "neutral", "中性"
    NONE = "none", "无方向"


class AtomicSignalOutputType(models.TextChoices):
    BOOLEAN = "bool", "布尔"
    DECIMAL = "decimal", "数值"
    TEXT = "text", "文本"
    JSON = "json", "结构化数据"


class AtomicSignalSetStatus(models.TextChoices):
    CREATED = "created", "已创建"
    FAILED = "failed", "失败"
    UNKNOWN = "unknown", "未知"


class AtomicSignalValueStatus(models.TextChoices):
    CREATED = "created", "已创建"
    FAILED = "failed", "失败"


class StrategyAnalysisRelease(models.Model):
    release_code = models.CharField("版本包代码", max_length=120, unique=True)
    display_name = models.CharField("展示名称", max_length=200, blank=True)
    description = models.TextField("说明", blank=True)
    release_hash = models.CharField("版本包指纹", max_length=80, blank=True, db_index=True)
    approval_status = models.CharField(
        "批准状态",
        max_length=40,
        choices=ReleaseApprovalStatus.choices,
        default=ReleaseApprovalStatus.DRAFT,
    )
    is_active = models.BooleanField("是否当前启用", default=False, db_index=True)
    active_slot = models.PositiveSmallIntegerField("唯一启用槽位", null=True, blank=True, unique=True, editable=False)
    validation_evidence_count = models.PositiveIntegerField("验证证据数量", default=0)
    approved_at_utc = models.DateTimeField("批准 UTC 时间", null=True, blank=True)
    activated_at_utc = models.DateTimeField("启用 UTC 时间", null=True, blank=True)
    deactivated_at_utc = models.DateTimeField("停用 UTC 时间", null=True, blank=True)
    created_by = models.CharField("创建人", max_length=120, blank=True)
    approved_by = models.CharField("批准人", max_length=120, blank=True)
    activated_by = models.CharField("启用人", max_length=120, blank=True)
    created_at_utc = models.DateTimeField("创建 UTC 时间", auto_now_add=True)
    updated_at_utc = models.DateTimeField("更新 UTC 时间", auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["approval_status", "is_active"]),
            models.Index(fields=["release_hash"]),
        ]


class StrategyAnalysisReleaseItem(models.Model):
    release = models.ForeignKey(StrategyAnalysisRelease, on_delete=models.CASCADE, related_name="items")
    component_type = models.CharField("组件类型", max_length=80, choices=ReleaseItemComponentType.choices)
    component_object_id = models.PositiveBigIntegerField("组件对象 ID", null=True, blank=True)
    component_code = models.CharField("组件代码", max_length=160)
    definition_hash = models.CharField("定义指纹", max_length=80)
    algorithm_name = models.CharField("算法名称", max_length=120, blank=True)
    algorithm_version = models.CharField("算法版本", max_length=80, blank=True)
    params_hash = models.CharField("参数指纹", max_length=80, blank=True)
    dependency_hash = models.CharField("依赖指纹", max_length=80, blank=True)
    expected_definition_set_hash = models.CharField("模块定义集指纹", max_length=80, blank=True)
    sort_order = models.PositiveIntegerField("排序", default=0)
    payload_summary = models.JSONField("冻结摘要", default=dict, blank=True)
    created_at_utc = models.DateTimeField("创建 UTC 时间", auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["release", "component_type", "component_code"],
                name="uniq_strategy_release_item_component",
            )
        ]
        indexes = [
            models.Index(fields=["component_type", "component_code"]),
            models.Index(fields=["release", "component_type", "sort_order"]),
        ]


class StrategyAnalysisReleaseValidationEvidence(models.Model):
    release = models.ForeignKey(StrategyAnalysisRelease, on_delete=models.CASCADE, related_name="validation_evidence")
    release_hash = models.CharField("版本包指纹", max_length=80)
    evidence_type = models.CharField("证据类型", max_length=80)
    evidence_ref = models.CharField("证据引用", max_length=255)
    summary = models.TextField("摘要", blank=True)
    created_by = models.CharField("创建人", max_length=120, blank=True)
    created_at_utc = models.DateTimeField("创建 UTC 时间", auto_now_add=True)


class StrategyAnalysisReleaseApproval(models.Model):
    release = models.ForeignKey(StrategyAnalysisRelease, on_delete=models.CASCADE, related_name="approvals")
    release_hash = models.CharField("版本包指纹", max_length=80)
    action = models.CharField("动作", max_length=40, choices=ReleaseAction.choices)
    validation_evidence_refs = models.JSONField("验证证据引用", default=list, blank=True)
    reason = models.CharField("原因", max_length=500)
    operator_id = models.CharField("操作者", max_length=120)
    operated_at_utc = models.DateTimeField("操作 UTC 时间", default=timezone.now)
    trace_id = models.CharField("追踪 ID", max_length=80)
    trigger_source = models.CharField("触发来源", max_length=80)


class StrategyAnalysisReleaseActivation(models.Model):
    release = models.ForeignKey(StrategyAnalysisRelease, on_delete=models.CASCADE, related_name="activations")
    release_hash = models.CharField("版本包指纹", max_length=80)
    action = models.CharField("动作", max_length=40, choices=ReleaseAction.choices)
    previous_release = models.ForeignKey(
        StrategyAnalysisRelease,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="replaced_by_activations",
    )
    operator_id = models.CharField("操作者", max_length=120)
    reason = models.CharField("原因", max_length=500)
    operated_at_utc = models.DateTimeField("操作 UTC 时间", default=timezone.now)
    trace_id = models.CharField("追踪 ID", max_length=80)
    trigger_source = models.CharField("触发来源", max_length=80)


class FeatureDefinition(models.Model):
    feature_code = models.CharField("特征代码", max_length=120)
    definition_version = models.CharField("定义版本", max_length=80, default="1.0.0")
    display_name = models.CharField("展示名称", max_length=200, blank=True)
    description = models.TextField("说明", blank=True)
    definition_hash = models.CharField("定义指纹", max_length=80)
    algorithm_name = models.CharField("算法名称", max_length=120)
    algorithm_version = models.CharField("算法版本", max_length=80)
    params = models.JSONField("参数", default=dict, blank=True)
    params_hash = models.CharField("参数指纹", max_length=80)
    value_type = models.CharField("值类型", max_length=40, choices=FeatureValueType.choices, default=FeatureValueType.DECIMAL)
    input_timeframes = models.JSONField("输入周期", default=list, blank=True)
    output_schema_version = models.CharField("输出 schema 版本", max_length=80, default="1.0")
    is_enabled = models.BooleanField("是否可被版本包选择", default=True)
    created_at_utc = models.DateTimeField("创建 UTC 时间", auto_now_add=True)
    updated_at_utc = models.DateTimeField("更新 UTC 时间", auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["feature_code", "definition_version"], name="uniq_feature_definition_version")
        ]
        indexes = [
            models.Index(fields=["feature_code", "definition_version"]),
            models.Index(fields=["algorithm_name", "algorithm_version"]),
        ]


class FeatureSet(models.Model):
    feature_set_key = models.CharField("特征集合稳定键", max_length=80, unique=True)
    business_request_key = models.CharField("业务幂等键", max_length=191, unique=True)
    market_snapshot = models.ForeignKey("market_data.MarketSnapshot", on_delete=models.PROTECT, related_name="feature_sets")
    strategy_analysis_release = models.ForeignKey(StrategyAnalysisRelease, on_delete=models.PROTECT, related_name="feature_sets")
    release_hash = models.CharField("版本包指纹", max_length=80)
    status = models.CharField("状态", max_length=40, choices=AnalysisObjectStatus.choices, default=AnalysisObjectStatus.CREATED)
    reason_code = models.CharField("原因代码", max_length=120, blank=True)
    is_usable = models.BooleanField("是否可用", default=True)
    allows_atomic_signal = models.BooleanField("允许原子信号消费", default=True)
    feature_schema_version = models.CharField("特征 schema 版本", max_length=40, default="1.0")
    definition_set_hash = models.CharField("特征定义集指纹", max_length=80)
    feature_count = models.PositiveIntegerField("特征数量", default=0)
    trace_id = models.CharField("追踪 ID", max_length=80)
    trigger_source = models.CharField("触发来源", max_length=80)
    created_at_utc = models.DateTimeField("创建 UTC 时间", auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["market_snapshot", "status"]),
            models.Index(fields=["release_hash", "definition_set_hash"]),
            models.Index(fields=["trace_id"]),
        ]


class FeatureValue(models.Model):
    feature_set = models.ForeignKey(FeatureSet, on_delete=models.CASCADE, related_name="values")
    feature_definition = models.ForeignKey(FeatureDefinition, on_delete=models.PROTECT, related_name="values")
    feature_code = models.CharField("特征代码", max_length=120)
    feature_definition_hash = models.CharField("特征定义指纹", max_length=80)
    algorithm_name = models.CharField("算法名称", max_length=120)
    algorithm_version = models.CharField("算法版本", max_length=80)
    params_hash = models.CharField("参数指纹", max_length=80)
    value_type = models.CharField("值类型", max_length=40, choices=FeatureValueType.choices)
    numeric_value = models.DecimalField("数值", max_digits=38, decimal_places=18, null=True, blank=True)
    bool_value = models.BooleanField("布尔值", null=True, blank=True)
    text_value = models.CharField("文本值", max_length=255, blank=True)
    output_schema_version = models.CharField("输出 schema 版本", max_length=80)
    evidence = models.JSONField("证据摘要", default=dict, blank=True)
    status = models.CharField("状态", max_length=40, choices=AnalysisObjectStatus.choices, default=AnalysisObjectStatus.CREATED)
    is_valid = models.BooleanField("是否为有效特征值", default=True)
    error_code = models.CharField("错误代码", max_length=120, blank=True)
    error_message = models.CharField("错误摘要", max_length=500, blank=True)
    created_at_utc = models.DateTimeField("创建 UTC 时间", auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["feature_set", "feature_code"], name="uniq_feature_value_in_set")
        ]
        indexes = [
            models.Index(fields=["feature_code", "status"]),
        ]


class AtomicSignalDefinition(models.Model):
    signal_code = models.CharField("原子信号代码", max_length=160)
    display_name = models.CharField("展示名称", max_length=200, blank=True)
    description = models.TextField("说明", blank=True)
    category = models.CharField("分类", max_length=80, blank=True)
    default_direction = models.CharField("条件成立默认方向", max_length=20, choices=AtomicSignalDirection.choices)
    algorithm_name = models.CharField("算法名称", max_length=120)
    algorithm_version = models.CharField("算法版本", max_length=80)
    params = models.JSONField("参数", default=dict)
    params_hash = models.CharField("参数指纹", max_length=80)
    definition_hash = models.CharField("定义指纹", max_length=80)
    status = models.CharField(
        "生命周期状态",
        max_length=40,
        choices=DefinitionLifecycleStatus.choices,
        default=DefinitionLifecycleStatus.DRAFT,
    )
    enabled = models.BooleanField("是否可用", default=False)
    is_required = models.BooleanField("失败是否阻断集合", default=False)
    depends_on_feature_codes = models.JSONField("依赖特征代码", default=list)
    output_type = models.CharField("输出类型", max_length=40, choices=AtomicSignalOutputType.choices)
    created_at_utc = models.DateTimeField("创建 UTC 时间", auto_now_add=True)
    updated_at_utc = models.DateTimeField("更新 UTC 时间", auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["signal_code", "definition_hash"],
                name="uniq_atomic_signal_definition_identity",
            )
        ]
        indexes = [
            models.Index(fields=["signal_code", "status", "enabled"]),
            models.Index(fields=["algorithm_name", "algorithm_version"]),
        ]


class AtomicSignalSet(models.Model):
    atomic_signal_set_key = models.CharField("原子信号集合稳定键", max_length=80, unique=True)
    business_request_key = models.CharField("业务幂等键", max_length=191, unique=True)
    feature_set = models.ForeignKey(FeatureSet, on_delete=models.PROTECT, related_name="atomic_signal_sets")
    feature_set_key = models.CharField("特征集合稳定键", max_length=80)
    strategy_analysis_release = models.ForeignKey(
        StrategyAnalysisRelease,
        on_delete=models.PROTECT,
        related_name="atomic_signal_sets",
    )
    release_hash = models.CharField("版本包指纹", max_length=80)
    market_snapshot = models.ForeignKey(
        "market_data.MarketSnapshot",
        on_delete=models.PROTECT,
        related_name="atomic_signal_sets",
    )
    exchange = models.CharField("交易所", max_length=40)
    market_type = models.CharField("市场类型", max_length=40)
    symbol = models.CharField("交易品种", max_length=40)
    analysis_close_time_utc = models.DateTimeField("分析收盘边界")
    signal_schema_version = models.CharField("信号 schema 版本", max_length=40)
    definition_set_hash = models.CharField("原子信号定义集指纹", max_length=80)
    status = models.CharField("状态", max_length=40, choices=AtomicSignalSetStatus.choices)
    is_usable = models.BooleanField("是否可用", default=False)
    allows_domain_signal = models.BooleanField("允许领域层消费", default=False)
    selected_definition_count = models.PositiveIntegerField("选择定义数量", default=0)
    computed_count = models.PositiveIntegerField("完成计算数量", default=0)
    valid_count = models.PositiveIntegerField("有效数量", default=0)
    invalid_count = models.PositiveIntegerField("无效数量", default=0)
    failed_count = models.PositiveIntegerField("失败数量", default=0)
    required_failed_count = models.PositiveIntegerField("必需信号失败数量", default=0)
    failure_ratio = models.DecimalField("失败比例", max_digits=10, decimal_places=8, default=0)
    failure_block_ratio = models.DecimalField("失败阻断比例", max_digits=10, decimal_places=8)
    payload_summary = models.JSONField("摘要", default=dict, blank=True)
    error_code = models.CharField("错误代码", max_length=120, blank=True)
    error_message = models.CharField("错误摘要", max_length=500, blank=True)
    trace_id = models.CharField("追踪 ID", max_length=80)
    trigger_source = models.CharField("触发来源", max_length=80)
    started_at_utc = models.DateTimeField("开始 UTC 时间", default=timezone.now)
    finished_at_utc = models.DateTimeField("结束 UTC 时间", null=True, blank=True)
    created_at_utc = models.DateTimeField("创建 UTC 时间", auto_now_add=True)
    updated_at_utc = models.DateTimeField("更新 UTC 时间", auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["feature_set", "status"]),
            models.Index(fields=["release_hash", "definition_set_hash"]),
            models.Index(fields=["trace_id"]),
        ]


class AtomicSignalValue(models.Model):
    atomic_signal_set = models.ForeignKey(AtomicSignalSet, on_delete=models.CASCADE, related_name="values")
    atomic_signal_definition = models.ForeignKey(
        AtomicSignalDefinition,
        on_delete=models.PROTECT,
        related_name="values",
    )
    signal_code = models.CharField("原子信号代码", max_length=160)
    direction = models.CharField("市场倾向", max_length=20, choices=AtomicSignalDirection.choices)
    strength = models.DecimalField("强度", max_digits=20, decimal_places=18)
    confidence = models.DecimalField("置信度", max_digits=20, decimal_places=18, null=True, blank=True)
    status = models.CharField("状态", max_length=40, choices=AtomicSignalValueStatus.choices)
    is_valid = models.BooleanField("是否有效", default=False)
    definition_status = models.CharField("计算时定义状态", max_length=40)
    definition_enabled = models.BooleanField("计算时定义开关")
    algorithm_name = models.CharField("算法名称", max_length=120)
    algorithm_version = models.CharField("算法版本", max_length=80)
    params_hash = models.CharField("参数指纹", max_length=80)
    definition_hash = models.CharField("定义指纹", max_length=80)
    output_type = models.CharField("输出类型", max_length=40, choices=AtomicSignalOutputType.choices)
    value_bool = models.BooleanField("布尔结果", null=True, blank=True)
    value_decimal = models.DecimalField("数值结果", max_digits=38, decimal_places=18, null=True, blank=True)
    value_text = models.CharField("文本结果", max_length=500, blank=True)
    value_json = models.JSONField("结构化结果", null=True, blank=True)
    evidence_items = models.JSONField("机器可读证据", default=list)
    evidence_text_zh = models.CharField("中文证据", max_length=1000)
    used_feature_codes = models.JSONField("使用的特征代码", default=list)
    used_feature_value_ids = models.JSONField("使用的特征值 ID", default=list)
    error_code = models.CharField("错误代码", max_length=120, blank=True)
    error_message = models.CharField("错误摘要", max_length=500, blank=True)
    calculated_at_utc = models.DateTimeField("计算 UTC 时间", default=timezone.now)
    latency_ms = models.PositiveIntegerField("计算耗时毫秒", default=0)
    created_at_utc = models.DateTimeField("创建 UTC 时间", auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["atomic_signal_set", "signal_code"],
                name="uniq_atomic_signal_value_in_set",
            )
        ]
        indexes = [
            models.Index(fields=["signal_code", "status", "is_valid"]),
        ]
