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


class StrategyAnalysisWorkspaceStatus(models.TextChoices):
    ACTIVE = "active", "可用"
    ARCHIVED = "archived", "已归档"


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


class DomainSignalOutputMode(models.TextChoices):
    DIRECTIONAL = "directional", "方向型"
    STATE = "state", "状态型"


class DomainSignalSetStatus(models.TextChoices):
    CREATED = "created", "已创建"
    FAILED = "failed", "失败"
    UNKNOWN = "unknown", "未知"


class DomainSignalValueStatus(models.TextChoices):
    CREATED = "created", "已创建"
    FAILED = "failed", "失败"


class StrategyRouteAction(models.TextChoices):
    SELECT_STRATEGY = "select_strategy", "选择策略"
    NO_STRATEGY = "no_strategy", "不选择策略"


class StrategyRouteFallbackPolicy(models.TextChoices):
    NONE = "none", "不使用 fallback"
    EXPLICIT = "explicit", "使用明确 fallback"


class StrategyRouteOutcome(models.TextChoices):
    SELECTED = "selected", "已选择策略"
    NO_STRATEGY = "no_strategy", "不选择策略"


class StrategySignalDirection(models.TextChoices):
    BULLISH = "bullish", "偏多"
    BEARISH = "bearish", "偏空"
    NEUTRAL = "neutral", "中性"
    NONE = "none", "无有效方向"


class StrategySignalQualityStatus(models.TextChoices):
    PASSED = "passed", "通过"
    WARNING = "warning", "警告"
    FAILED = "failed", "未通过"


class StrategySignalQualityIssueSeverity(models.TextChoices):
    INFO = "info", "信息"
    WARNING = "warning", "警告"
    ERROR = "error", "错误"
    CRITICAL = "critical", "严重"


class StrategySignalQualityValidationMode(models.TextChoices):
    LIVE = "live", "正式运行"
    REPLAY = "replay", "回放"
    BACKFILL = "backfill", "补算"
    MANUAL = "manual", "人工"


class DecisionTargetIntent(models.TextChoices):
    TARGET_POSITION = "TARGET_POSITION", "目标仓位"
    NO_TARGET_CHANGE = "NO_TARGET_CHANGE", "目标不变"
    NO_TRADE = "NO_TRADE", "本轮不交易"


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


class StrategyAnalysisWorkspace(models.Model):
    workspace_code = models.CharField("配置工作区代码", max_length=120, unique=True)
    display_name = models.CharField("展示名称", max_length=200, blank=True)
    description = models.TextField("说明", blank=True)
    status = models.CharField(
        "状态",
        max_length=40,
        choices=StrategyAnalysisWorkspaceStatus.choices,
        default=StrategyAnalysisWorkspaceStatus.ACTIVE,
    )
    default_slot = models.PositiveSmallIntegerField("默认工作区槽位", null=True, blank=True, unique=True)
    created_by = models.CharField("创建人", max_length=120, blank=True)
    updated_by = models.CharField("最后更新人", max_length=120, blank=True)
    created_at_utc = models.DateTimeField("创建 UTC 时间", auto_now_add=True)
    updated_at_utc = models.DateTimeField("更新 UTC 时间", auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["workspace_code", "status"]),
            models.Index(fields=["default_slot", "status"]),
        ]


class StrategyAnalysisWorkspaceItem(models.Model):
    workspace = models.ForeignKey(StrategyAnalysisWorkspace, on_delete=models.CASCADE, related_name="items")
    component_type = models.CharField("组件类型", max_length=80, choices=ReleaseItemComponentType.choices)
    component_object_id = models.PositiveIntegerField("组件对象 ID")
    component_code = models.CharField("组件代码", max_length=160)
    component_version = models.CharField("组件版本", max_length=80, blank=True)
    definition_hash = models.CharField("定义指纹", max_length=80)
    inclusion_managed = models.BooleanField("是否支持纳入状态", default=True)
    is_included = models.BooleanField("是否纳入当前组合", default=True)
    selection_reason = models.CharField("选择原因", max_length=500, blank=True)
    updated_by = models.CharField("最后更新人", max_length=120, blank=True)
    trace_id = models.CharField("追踪 ID", max_length=80, blank=True)
    trigger_source = models.CharField("触发来源", max_length=80, blank=True)
    created_at_utc = models.DateTimeField("创建 UTC 时间", auto_now_add=True)
    updated_at_utc = models.DateTimeField("更新 UTC 时间", auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["workspace", "component_type", "component_code"],
                name="uniq_strategy_workspace_item_code",
            )
        ]
        indexes = [
            models.Index(fields=["workspace", "component_type", "is_included"]),
            models.Index(fields=["component_type", "component_code"]),
            models.Index(fields=["definition_hash"]),
        ]


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


class DomainSignalDefinition(models.Model):
    domain_code = models.CharField("领域代码", max_length=80)
    display_name = models.CharField("展示名称", max_length=200, blank=True)
    description = models.TextField("说明", blank=True)
    category = models.CharField("分类", max_length=80, blank=True)
    output_mode = models.CharField("输出模式", max_length=40, choices=DomainSignalOutputMode.choices)
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
    is_required = models.BooleanField("失败是否阻断集合", default=True)
    allowed_atomic_signal_codes = models.JSONField("允许原子信号代码", default=list)
    required_atomic_signal_codes = models.JSONField("必需原子信号代码", default=list)
    minimum_coverage_ratio = models.DecimalField("最低覆盖率", max_digits=10, decimal_places=8, default=1)
    agreement_threshold = models.DecimalField("一致性阈值", max_digits=10, decimal_places=8, null=True, blank=True)
    created_at_utc = models.DateTimeField("创建 UTC 时间", auto_now_add=True)
    updated_at_utc = models.DateTimeField("更新 UTC 时间", auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["domain_code", "definition_hash"],
                name="uniq_domain_signal_definition_identity",
            )
        ]
        indexes = [
            models.Index(fields=["domain_code", "status", "enabled"]),
            models.Index(fields=["algorithm_name", "algorithm_version"]),
        ]


class DomainSignalSet(models.Model):
    domain_signal_set_key = models.CharField("领域信号集合稳定键", max_length=80, unique=True)
    business_request_key = models.CharField("业务幂等键", max_length=191, unique=True)
    atomic_signal_set = models.ForeignKey(AtomicSignalSet, on_delete=models.PROTECT, related_name="domain_signal_sets")
    atomic_signal_set_key = models.CharField("原子信号集合稳定键", max_length=80)
    strategy_analysis_release = models.ForeignKey(
        StrategyAnalysisRelease,
        on_delete=models.PROTECT,
        related_name="domain_signal_sets",
    )
    release_hash = models.CharField("版本包指纹", max_length=80)
    market_snapshot = models.ForeignKey(
        "market_data.MarketSnapshot",
        on_delete=models.PROTECT,
        related_name="domain_signal_sets",
    )
    exchange = models.CharField("交易所", max_length=40)
    market_type = models.CharField("市场类型", max_length=40)
    symbol = models.CharField("交易品种", max_length=40)
    analysis_close_time_utc = models.DateTimeField("分析收盘边界")
    domain_schema_version = models.CharField("领域信号 schema 版本", max_length=40)
    definition_set_hash = models.CharField("领域信号定义集指纹", max_length=80)
    status = models.CharField("状态", max_length=40, choices=DomainSignalSetStatus.choices)
    is_usable = models.BooleanField("是否可用", default=False)
    allows_market_regime = models.BooleanField("允许市场环境层消费", default=False)
    selected_definition_count = models.PositiveIntegerField("选择定义数量", default=0)
    computed_count = models.PositiveIntegerField("完成计算数量", default=0)
    valid_count = models.PositiveIntegerField("有效数量", default=0)
    invalid_count = models.PositiveIntegerField("无效数量", default=0)
    required_failed_count = models.PositiveIntegerField("必需领域失败数量", default=0)
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
            models.Index(fields=["atomic_signal_set", "status"]),
            models.Index(fields=["release_hash", "definition_set_hash"]),
            models.Index(fields=["trace_id"]),
        ]


class DomainSignalValue(models.Model):
    domain_signal_set = models.ForeignKey(DomainSignalSet, on_delete=models.CASCADE, related_name="values")
    domain_signal_definition = models.ForeignKey(
        DomainSignalDefinition,
        on_delete=models.PROTECT,
        related_name="values",
    )
    domain_code = models.CharField("领域代码", max_length=80)
    output_mode = models.CharField("输出模式", max_length=40, choices=DomainSignalOutputMode.choices)
    direction = models.CharField("领域方向", max_length=20, choices=AtomicSignalDirection.choices)
    state_code = models.CharField("状态代码", max_length=80, blank=True)
    strength = models.DecimalField("强度", max_digits=20, decimal_places=18)
    coverage_ratio = models.DecimalField("覆盖率", max_digits=20, decimal_places=18)
    agreement_ratio = models.DecimalField("一致性比例", max_digits=20, decimal_places=18, null=True, blank=True)
    status = models.CharField("状态", max_length=40, choices=DomainSignalValueStatus.choices)
    is_valid = models.BooleanField("是否有效", default=False)
    definition_status = models.CharField("计算时定义状态", max_length=40)
    definition_enabled = models.BooleanField("计算时定义开关")
    algorithm_name = models.CharField("算法名称", max_length=120)
    algorithm_version = models.CharField("算法版本", max_length=80)
    params_hash = models.CharField("参数指纹", max_length=80)
    definition_hash = models.CharField("定义指纹", max_length=80)
    used_atomic_signal_codes = models.JSONField("使用的原子信号代码", default=list)
    used_atomic_signal_value_ids = models.JSONField("使用的原子信号值 ID", default=list)
    evidence_items = models.JSONField("机器可读证据", default=list)
    evidence_text_zh = models.CharField("中文证据", max_length=1000)
    error_code = models.CharField("错误代码", max_length=120, blank=True)
    error_message = models.CharField("错误摘要", max_length=500, blank=True)
    calculated_at_utc = models.DateTimeField("计算 UTC 时间", default=timezone.now)
    latency_ms = models.PositiveIntegerField("计算耗时毫秒", default=0)
    created_at_utc = models.DateTimeField("创建 UTC 时间", auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["domain_signal_set", "domain_code"],
                name="uniq_domain_signal_value_in_set",
            )
        ]
        indexes = [
            models.Index(fields=["domain_code", "status", "is_valid"]),
        ]


class MarketRegimeDefinition(models.Model):
    definition_code = models.CharField("市场环境定义代码", max_length=120)
    display_name = models.CharField("展示名称", max_length=200, blank=True)
    description = models.TextField("说明", blank=True)
    algorithm_name = models.CharField("算法名称", max_length=120)
    algorithm_version = models.CharField("算法版本", max_length=80)
    input_schema_version = models.CharField("输入 schema 版本", max_length=40)
    output_schema_version = models.CharField("输出 schema 版本", max_length=40)
    params = models.JSONField("参数", default=dict)
    params_hash = models.CharField("参数指纹", max_length=80)
    definition_hash = models.CharField("定义指纹", max_length=80)
    allowed_domain_codes = models.JSONField("允许领域代码", default=list)
    required_domain_codes = models.JSONField("必须领域代码", default=list)
    allowed_regime_codes = models.JSONField("允许环境分类代码", default=list)
    status = models.CharField(
        "生命周期状态",
        max_length=40,
        choices=DefinitionLifecycleStatus.choices,
        default=DefinitionLifecycleStatus.DRAFT,
    )
    enabled = models.BooleanField("是否可用", default=False)
    created_at_utc = models.DateTimeField("创建 UTC 时间", auto_now_add=True)
    updated_at_utc = models.DateTimeField("更新 UTC 时间", auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["definition_code", "definition_hash"],
                name="uniq_market_regime_definition_identity",
            )
        ]
        indexes = [
            models.Index(fields=["definition_code", "status", "enabled"]),
            models.Index(fields=["algorithm_name", "algorithm_version"]),
        ]


class MarketRegimeSnapshot(models.Model):
    market_regime_snapshot_key = models.CharField("市场环境快照稳定键", max_length=80, unique=True)
    business_request_key = models.CharField("业务幂等键", max_length=191, unique=True)
    domain_signal_set = models.ForeignKey(
        DomainSignalSet,
        on_delete=models.PROTECT,
        related_name="market_regime_snapshots",
    )
    market_regime_definition = models.ForeignKey(
        MarketRegimeDefinition,
        on_delete=models.PROTECT,
        related_name="snapshots",
    )
    strategy_analysis_release = models.ForeignKey(
        StrategyAnalysisRelease,
        on_delete=models.PROTECT,
        related_name="market_regime_snapshots",
    )
    release_hash = models.CharField("版本包指纹", max_length=80)
    market_snapshot = models.ForeignKey(
        "market_data.MarketSnapshot",
        on_delete=models.PROTECT,
        related_name="market_regime_snapshots",
    )
    exchange = models.CharField("交易所", max_length=40)
    market_type = models.CharField("市场类型", max_length=40)
    symbol = models.CharField("交易品种", max_length=40)
    analysis_close_time_utc = models.DateTimeField("分析收盘边界")
    market_regime_schema_version = models.CharField("市场环境 schema 版本", max_length=40)
    definition_set_hash = models.CharField("市场环境定义集指纹", max_length=80)
    regime_code = models.CharField("环境分类代码", max_length=120, blank=True)
    regime_scores = models.JSONField("环境分类评分", default=dict)
    regime_confidence = models.DecimalField("分类明确程度", max_digits=20, decimal_places=18, null=True, blank=True)
    classification_margin = models.DecimalField("分类区分度", max_digits=20, decimal_places=18, null=True, blank=True)
    status = models.CharField("状态", max_length=40, choices=AnalysisObjectStatus.choices)
    is_usable = models.BooleanField("是否可用", default=False)
    allows_strategy_routing = models.BooleanField("允许策略路由消费", default=False)
    definition_status = models.CharField("计算时定义状态", max_length=40)
    definition_enabled = models.BooleanField("计算时定义开关")
    algorithm_name = models.CharField("算法名称", max_length=120)
    algorithm_version = models.CharField("算法版本", max_length=80)
    input_schema_version = models.CharField("输入 schema 版本", max_length=40)
    output_schema_version = models.CharField("输出 schema 版本", max_length=40)
    params_hash = models.CharField("参数指纹", max_length=80)
    definition_hash = models.CharField("定义指纹", max_length=80)
    used_domain_signal_codes = models.JSONField("实际使用领域代码", default=list)
    used_domain_signal_value_ids = models.JSONField("实际使用领域值 ID", default=list)
    evidence_items = models.JSONField("机器可读证据", default=list)
    evidence_text_zh = models.CharField("中文证据", max_length=1000)
    payload_summary = models.JSONField("摘要", default=dict, blank=True)
    error_code = models.CharField("错误代码", max_length=120, blank=True)
    error_message = models.CharField("错误摘要", max_length=500, blank=True)
    trace_id = models.CharField("追踪 ID", max_length=80)
    trigger_source = models.CharField("触发来源", max_length=80)
    calculated_at_utc = models.DateTimeField("计算 UTC 时间", default=timezone.now)
    latency_ms = models.PositiveIntegerField("计算耗时毫秒", default=0)
    created_at_utc = models.DateTimeField("创建 UTC 时间", auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["domain_signal_set", "status"]),
            models.Index(fields=["release_hash", "definition_set_hash"]),
            models.Index(fields=["regime_code", "status", "is_usable"]),
            models.Index(fields=["trace_id"]),
        ]


class StrategyDefinition(models.Model):
    strategy_code = models.CharField("策略代码", max_length=120)
    strategy_version = models.CharField("策略业务版本", max_length=80)
    display_name = models.CharField("展示名称", max_length=200, blank=True)
    description = models.TextField("说明", blank=True)
    algorithm_name = models.CharField("算法名称", max_length=120)
    algorithm_version = models.CharField("算法版本", max_length=80)
    input_schema_version = models.CharField("输入 schema 版本", max_length=40)
    output_schema_version = models.CharField("输出 schema 版本", max_length=40)
    params = models.JSONField("参数", default=dict)
    params_hash = models.CharField("参数指纹", max_length=80)
    definition_hash = models.CharField("定义指纹", max_length=80)
    allowed_domain_codes = models.JSONField("允许领域代码", default=list)
    required_domain_codes = models.JSONField("必须领域代码", default=list)
    uses_input_weights = models.BooleanField("是否使用输入权重", default=False)
    domain_input_weights = models.JSONField("领域输入权重", default=dict)
    prediction_horizon = models.CharField("预测期限", max_length=80)
    status = models.CharField(
        "生命周期状态",
        max_length=40,
        choices=DefinitionLifecycleStatus.choices,
        default=DefinitionLifecycleStatus.DRAFT,
    )
    enabled = models.BooleanField("是否可用", default=False)
    created_at_utc = models.DateTimeField("创建 UTC 时间", auto_now_add=True)
    updated_at_utc = models.DateTimeField("更新 UTC 时间", auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["strategy_code", "strategy_version"],
                name="uniq_strategy_definition_version",
            )
        ]
        indexes = [
            models.Index(fields=["strategy_code", "status", "enabled"]),
            models.Index(fields=["algorithm_name", "algorithm_version"]),
        ]


class StrategyRoutePolicy(models.Model):
    policy_code = models.CharField("路由策略代码", max_length=120)
    display_name = models.CharField("展示名称", max_length=200, blank=True)
    description = models.TextField("说明", blank=True)
    policy_version = models.CharField("路由策略版本", max_length=80)
    condition_schema_version = models.CharField("条件 schema 版本", max_length=40)
    rule_set_hash = models.CharField("规则集合指纹", max_length=80)
    definition_hash = models.CharField("定义指纹", max_length=80)
    fallback_policy = models.CharField(
        "fallback 策略",
        max_length=40,
        choices=StrategyRouteFallbackPolicy.choices,
        default=StrategyRouteFallbackPolicy.NONE,
    )
    fallback_strategy_definition = models.ForeignKey(
        StrategyDefinition,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="fallback_route_policies",
    )
    status = models.CharField(
        "生命周期状态",
        max_length=40,
        choices=DefinitionLifecycleStatus.choices,
        default=DefinitionLifecycleStatus.DRAFT,
    )
    enabled = models.BooleanField("是否可用", default=False)
    created_at_utc = models.DateTimeField("创建 UTC 时间", auto_now_add=True)
    updated_at_utc = models.DateTimeField("更新 UTC 时间", auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["policy_code", "policy_version"],
                name="uniq_strategy_route_policy_version",
            )
        ]
        indexes = [models.Index(fields=["policy_code", "status", "enabled"])]


class StrategyRouteRule(models.Model):
    strategy_route_policy = models.ForeignKey(
        StrategyRoutePolicy,
        on_delete=models.PROTECT,
        related_name="rules",
    )
    rule_code = models.CharField("规则代码", max_length=120)
    display_name = models.CharField("展示名称", max_length=200, blank=True)
    description = models.TextField("说明", blank=True)
    priority = models.PositiveIntegerField("优先级")
    action = models.CharField("动作", max_length=40, choices=StrategyRouteAction.choices)
    match_conditions = models.JSONField("匹配条件", default=dict)
    selected_strategy_definition = models.ForeignKey(
        StrategyDefinition,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="route_rules",
    )
    status = models.CharField(
        "生命周期状态",
        max_length=40,
        choices=DefinitionLifecycleStatus.choices,
        default=DefinitionLifecycleStatus.DRAFT,
    )
    enabled = models.BooleanField("是否可用", default=False)
    valid_from_utc = models.DateTimeField("有效开始 UTC 时间", null=True, blank=True)
    valid_to_utc = models.DateTimeField("有效结束 UTC 时间", null=True, blank=True)
    rule_hash = models.CharField("规则指纹", max_length=80)
    created_at_utc = models.DateTimeField("创建 UTC 时间", auto_now_add=True)
    updated_at_utc = models.DateTimeField("更新 UTC 时间", auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["strategy_route_policy", "rule_code"],
                name="uniq_strategy_route_rule_code",
            )
        ]
        indexes = [
            models.Index(fields=["strategy_route_policy", "priority"]),
            models.Index(fields=["status", "enabled"]),
        ]


class StrategyRouteDecision(models.Model):
    strategy_route_decision_key = models.CharField("策略路由决定稳定键", max_length=80, unique=True)
    business_request_key = models.CharField("业务幂等键", max_length=191, unique=True)
    market_regime_snapshot = models.ForeignKey(
        MarketRegimeSnapshot,
        on_delete=models.PROTECT,
        related_name="strategy_route_decisions",
    )
    strategy_route_policy = models.ForeignKey(
        StrategyRoutePolicy,
        on_delete=models.PROTECT,
        related_name="decisions",
    )
    strategy_analysis_release = models.ForeignKey(
        StrategyAnalysisRelease,
        on_delete=models.PROTECT,
        related_name="strategy_route_decisions",
    )
    release_hash = models.CharField("版本包指纹", max_length=80)
    matched_strategy_route_rule = models.ForeignKey(
        StrategyRouteRule,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="decisions",
    )
    selected_strategy_definition = models.ForeignKey(
        StrategyDefinition,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="route_decisions",
    )
    strategy_route_schema_version = models.CharField("策略路由 schema 版本", max_length=40)
    route_outcome = models.CharField("路由结果", max_length=40, choices=StrategyRouteOutcome.choices, blank=True)
    matched_conditions = models.JSONField("命中条件", default=dict)
    selection_reason = models.CharField("选择原因", max_length=1000)
    fallback_used = models.BooleanField("是否使用 fallback", default=False)
    fallback_reason = models.CharField("fallback 原因", max_length=500, blank=True)
    status = models.CharField("状态", max_length=40, choices=AnalysisObjectStatus.choices)
    is_usable = models.BooleanField("是否可用", default=False)
    allows_strategy_signal = models.BooleanField("允许策略信号消费", default=False)
    policy_status = models.CharField("计算时 Policy 状态", max_length=40)
    policy_enabled = models.BooleanField("计算时 Policy 开关")
    policy_version = models.CharField("Policy 版本", max_length=80)
    condition_schema_version = models.CharField("条件 schema 版本", max_length=40)
    rule_set_hash = models.CharField("规则集合指纹", max_length=80)
    definition_hash = models.CharField("Policy 定义指纹", max_length=80)
    eligible_strategy_definition_ids = models.JSONField("候选策略定义 ID", default=list)
    evidence_items = models.JSONField("机器可读证据", default=list)
    evidence_text_zh = models.CharField("中文证据", max_length=1000)
    payload_summary = models.JSONField("摘要", default=dict, blank=True)
    error_code = models.CharField("错误代码", max_length=120, blank=True)
    error_message = models.CharField("错误摘要", max_length=500, blank=True)
    analysis_close_time_utc = models.DateTimeField("分析收盘边界")
    trace_id = models.CharField("追踪 ID", max_length=80)
    trigger_source = models.CharField("触发来源", max_length=80)
    calculated_at_utc = models.DateTimeField("计算 UTC 时间", default=timezone.now)
    latency_ms = models.PositiveIntegerField("计算耗时毫秒", default=0)
    created_at_utc = models.DateTimeField("创建 UTC 时间", auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["market_regime_snapshot", "status"]),
            models.Index(fields=["release_hash", "definition_hash"]),
            models.Index(fields=["route_outcome", "status", "is_usable"]),
            models.Index(fields=["trace_id"]),
        ]


class StrategySignal(models.Model):
    strategy_signal_key = models.CharField("策略信号稳定键", max_length=80, unique=True)
    business_request_key = models.CharField("业务幂等键", max_length=191, unique=True)
    strategy_route_decision = models.ForeignKey(
        StrategyRouteDecision,
        on_delete=models.PROTECT,
        related_name="strategy_signals",
    )
    strategy_definition = models.ForeignKey(
        StrategyDefinition,
        on_delete=models.PROTECT,
        related_name="strategy_signals",
    )
    strategy_analysis_release = models.ForeignKey(
        StrategyAnalysisRelease,
        on_delete=models.PROTECT,
        related_name="strategy_signals",
    )
    release_hash = models.CharField("版本包指纹", max_length=80)
    domain_signal_set = models.ForeignKey(
        DomainSignalSet,
        on_delete=models.PROTECT,
        related_name="strategy_signals",
    )
    market_regime_snapshot = models.ForeignKey(
        MarketRegimeSnapshot,
        on_delete=models.PROTECT,
        related_name="strategy_signals",
    )
    strategy_signal_schema_version = models.CharField("策略信号 schema 版本", max_length=40)
    strategy_code = models.CharField("策略代码", max_length=120)
    strategy_version = models.CharField("策略业务版本", max_length=80)
    direction = models.CharField("策略方向", max_length=20, choices=StrategySignalDirection.choices)
    strength = models.DecimalField("策略强度", max_digits=20, decimal_places=18, null=True, blank=True)
    confidence = models.DecimalField("策略置信评分", max_digits=20, decimal_places=18, null=True, blank=True)
    confidence_semantics = models.CharField("置信评分语义", max_length=80, blank=True)
    prediction_horizon = models.CharField("预测期限", max_length=80, blank=True)
    status = models.CharField("状态", max_length=40, choices=AnalysisObjectStatus.choices)
    is_usable = models.BooleanField("是否可用", default=False)
    allows_strategy_signal_quality = models.BooleanField("允许策略信号质量层消费", default=False)
    definition_status = models.CharField("计算时 Definition 状态", max_length=40)
    definition_enabled = models.BooleanField("计算时 Definition 开关")
    algorithm_name = models.CharField("算法名称", max_length=120)
    algorithm_version = models.CharField("算法版本", max_length=80)
    input_schema_version = models.CharField("输入 schema 版本", max_length=40)
    output_schema_version = models.CharField("输出 schema 版本", max_length=40)
    params_hash = models.CharField("参数指纹", max_length=80)
    definition_hash = models.CharField("定义指纹", max_length=80)
    used_domain_signal_codes = models.JSONField("实际使用领域代码", default=list)
    used_domain_signal_value_ids = models.JSONField("实际使用领域值 ID", default=list)
    actual_input_weights = models.JSONField("实际输入权重", default=dict)
    trade_price_condition = models.JSONField("策略价格条件", default=dict, blank=True)
    aggregation_snapshot = models.JSONField("聚合摘要", default=dict)
    conflict_snapshot = models.JSONField("冲突摘要", default=dict)
    evidence_items = models.JSONField("机器可读证据", default=list)
    evidence_text_zh = models.CharField("中文证据", max_length=1000)
    payload_summary = models.JSONField("摘要", default=dict, blank=True)
    error_code = models.CharField("错误代码", max_length=120, blank=True)
    error_message = models.CharField("错误摘要", max_length=500, blank=True)
    analysis_close_time_utc = models.DateTimeField("分析收盘边界")
    trace_id = models.CharField("追踪 ID", max_length=80)
    trigger_source = models.CharField("触发来源", max_length=80)
    calculated_at_utc = models.DateTimeField("计算 UTC 时间", default=timezone.now)
    latency_ms = models.PositiveIntegerField("计算耗时毫秒", default=0)
    created_at_utc = models.DateTimeField("创建 UTC 时间", auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["strategy_route_decision", "status"]),
            models.Index(fields=["release_hash", "definition_hash"]),
            models.Index(fields=["direction", "status", "is_usable"]),
            models.Index(fields=["trace_id"]),
        ]


class StrategySignalQualityRuleSet(models.Model):
    rule_set_code = models.CharField("质量规则集代码", max_length=120)
    rule_set_version = models.CharField("质量规则集版本", max_length=80)
    display_name = models.CharField("展示名称", max_length=200, blank=True)
    description = models.TextField("说明", blank=True)
    quality_schema_version = models.CharField("质量 schema 版本", max_length=40)
    max_staleness_seconds = models.PositiveIntegerField("最大允许陈旧秒数", default=0)
    warning_blocks_decision = models.BooleanField("warning 是否阻断 DecisionSnapshot", default=False)
    fail_alert_enabled = models.BooleanField("失败是否写告警", default=True)
    warning_alert_enabled = models.BooleanField("warning 是否写告警", default=False)
    consecutive_failure_threshold = models.PositiveIntegerField("连续失败告警阈值", default=0)
    params = models.JSONField("规则参数", default=dict, blank=True)
    params_hash = models.CharField("规则参数指纹", max_length=80)
    rule_set_hash = models.CharField("质量规则集指纹", max_length=80)
    status = models.CharField(
        "生命周期状态",
        max_length=40,
        choices=DefinitionLifecycleStatus.choices,
        default=DefinitionLifecycleStatus.DRAFT,
    )
    enabled = models.BooleanField("是否可用", default=False)
    created_at_utc = models.DateTimeField("创建 UTC 时间", auto_now_add=True)
    updated_at_utc = models.DateTimeField("更新 UTC 时间", auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["rule_set_code", "rule_set_version"],
                name="uniq_strategy_signal_quality_rule_set_version",
            )
        ]
        indexes = [
            models.Index(fields=["rule_set_code", "status", "enabled"]),
            models.Index(fields=["rule_set_hash"]),
        ]


class StrategySignalQualityResult(models.Model):
    quality_result_key = models.CharField("质量结果稳定键", max_length=80, unique=True)
    business_request_key = models.CharField("业务幂等键", max_length=191, unique=True)
    strategy_signal = models.ForeignKey(
        StrategySignal,
        on_delete=models.PROTECT,
        related_name="quality_results",
    )
    strategy_signal_key = models.CharField("策略信号稳定键", max_length=80)
    strategy_analysis_release = models.ForeignKey(
        StrategyAnalysisRelease,
        on_delete=models.PROTECT,
        related_name="strategy_signal_quality_results",
    )
    release_hash = models.CharField("版本包指纹", max_length=80)
    strategy_signal_quality_rule_set = models.ForeignKey(
        StrategySignalQualityRuleSet,
        on_delete=models.PROTECT,
        related_name="quality_results",
    )
    strategy_route_decision = models.ForeignKey(
        StrategyRouteDecision,
        on_delete=models.PROTECT,
        related_name="strategy_signal_quality_results",
    )
    strategy_definition = models.ForeignKey(
        StrategyDefinition,
        on_delete=models.PROTECT,
        related_name="strategy_signal_quality_results",
    )
    domain_signal_set = models.ForeignKey(
        DomainSignalSet,
        on_delete=models.PROTECT,
        related_name="strategy_signal_quality_results",
    )
    market_regime_snapshot = models.ForeignKey(
        MarketRegimeSnapshot,
        on_delete=models.PROTECT,
        related_name="strategy_signal_quality_results",
    )
    strategy_code = models.CharField("策略代码", max_length=120)
    strategy_version = models.CharField("策略业务版本", max_length=80)
    algorithm_name = models.CharField("算法名称", max_length=120)
    algorithm_version = models.CharField("算法版本", max_length=80)
    quality_schema_version = models.CharField("质量 schema 版本", max_length=40)
    quality_rule_set_version = models.CharField("质量规则集版本", max_length=80)
    quality_rule_set_hash = models.CharField("质量规则集指纹", max_length=80)
    validation_mode = models.CharField(
        "验证模式",
        max_length=40,
        choices=StrategySignalQualityValidationMode.choices,
    )
    reference_time_utc = models.DateTimeField("参考 UTC 时间")
    validation_as_of_utc = models.DateTimeField("验证 UTC 时间")
    market_as_of_utc = models.DateTimeField("市场事实 UTC 时间", null=True, blank=True)
    status = models.CharField("流程状态", max_length=40, choices=AnalysisObjectStatus.choices)
    quality_status = models.CharField(
        "质量状态",
        max_length=40,
        choices=StrategySignalQualityStatus.choices,
        blank=True,
    )
    quality_score = models.DecimalField("质量评分", max_digits=20, decimal_places=18, null=True, blank=True)
    is_usable = models.BooleanField("是否可用", default=False)
    allows_decision_snapshot = models.BooleanField("允许目标仓位决策消费", default=False)
    issue_count = models.PositiveIntegerField("问题数量", default=0)
    warning_count = models.PositiveIntegerField("warning 数量", default=0)
    error_count = models.PositiveIntegerField("error 数量", default=0)
    critical_count = models.PositiveIntegerField("critical 数量", default=0)
    blocked_reason = models.CharField("阻断原因", max_length=120, blank=True)
    error_code = models.CharField("错误代码", max_length=120, blank=True)
    error_message = models.CharField("错误摘要", max_length=500, blank=True)
    check_summary = models.JSONField("检查摘要", default=dict, blank=True)
    summary_text_zh = models.CharField("中文摘要", max_length=1000)
    trace_id = models.CharField("追踪 ID", max_length=80)
    trigger_source = models.CharField("触发来源", max_length=80)
    created_at_utc = models.DateTimeField("创建 UTC 时间", auto_now_add=True)
    updated_at_utc = models.DateTimeField("更新 UTC 时间", auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["strategy_signal", "status"]),
            models.Index(fields=["release_hash", "quality_rule_set_hash"]),
            models.Index(fields=["quality_status", "allows_decision_snapshot"]),
            models.Index(fields=["trace_id"]),
        ]


class StrategySignalQualityIssue(models.Model):
    quality_result = models.ForeignKey(
        StrategySignalQualityResult,
        on_delete=models.CASCADE,
        related_name="issues",
    )
    issue_code = models.CharField("问题代码", max_length=120)
    severity = models.CharField("严重程度", max_length=40, choices=StrategySignalQualityIssueSeverity.choices)
    check_group = models.CharField("检查分组", max_length=120)
    check_name = models.CharField("检查名称", max_length=120)
    field_name = models.CharField("字段名", max_length=120, blank=True)
    message_zh = models.CharField("中文说明", max_length=500)
    details = models.JSONField("问题详情", default=dict, blank=True)
    created_at_utc = models.DateTimeField("创建 UTC 时间", auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["quality_result", "severity"]),
            models.Index(fields=["issue_code", "severity"]),
        ]


class DecisionPolicyDefinition(models.Model):
    policy_code = models.CharField("目标仓位决策规则代码", max_length=120)
    policy_version = models.CharField("目标仓位决策规则版本", max_length=80)
    display_name = models.CharField("展示名称", max_length=200, blank=True)
    description = models.TextField("说明", blank=True)
    algorithm_name = models.CharField("算法名称", max_length=120)
    algorithm_version = models.CharField("算法版本", max_length=80)
    input_schema_version = models.CharField("输入 schema 版本", max_length=40)
    output_schema_version = models.CharField("输出 schema 版本", max_length=40)
    target_schema_version = models.CharField("目标仓位 schema 版本", max_length=40)
    params = models.JSONField("规则参数", default=dict, blank=True)
    params_hash = models.CharField("参数指纹", max_length=80)
    definition_hash = models.CharField("定义指纹", max_length=80)
    status = models.CharField(
        "生命周期状态",
        max_length=40,
        choices=DefinitionLifecycleStatus.choices,
        default=DefinitionLifecycleStatus.DRAFT,
    )
    enabled = models.BooleanField("是否可用", default=False)
    created_at_utc = models.DateTimeField("创建 UTC 时间", auto_now_add=True)
    updated_at_utc = models.DateTimeField("更新 UTC 时间", auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["policy_code", "policy_version"],
                name="uniq_decision_policy_definition_version",
            )
        ]
        indexes = [
            models.Index(fields=["policy_code", "status", "enabled"]),
            models.Index(fields=["definition_hash"]),
            models.Index(fields=["algorithm_name", "algorithm_version"]),
        ]


class DecisionSnapshot(models.Model):
    decision_snapshot_key = models.CharField("目标仓位快照稳定键", max_length=80, unique=True)
    business_request_key = models.CharField("业务幂等键", max_length=191, unique=True)
    strategy_signal_quality_result = models.ForeignKey(
        StrategySignalQualityResult,
        on_delete=models.PROTECT,
        related_name="decision_snapshots",
    )
    strategy_signal = models.ForeignKey(
        StrategySignal,
        on_delete=models.PROTECT,
        related_name="decision_snapshots",
    )
    decision_policy_definition = models.ForeignKey(
        DecisionPolicyDefinition,
        on_delete=models.PROTECT,
        related_name="decision_snapshots",
    )
    strategy_analysis_release = models.ForeignKey(
        StrategyAnalysisRelease,
        on_delete=models.PROTECT,
        related_name="decision_snapshots",
    )
    release_hash = models.CharField("版本包指纹", max_length=80)
    strategy_code = models.CharField("策略代码", max_length=120)
    strategy_version = models.CharField("策略业务版本", max_length=80)
    policy_code = models.CharField("决策规则代码", max_length=120)
    policy_version = models.CharField("决策规则版本", max_length=80)
    algorithm_name = models.CharField("算法名称", max_length=120)
    algorithm_version = models.CharField("算法版本", max_length=80)
    params_hash = models.CharField("参数指纹", max_length=80)
    definition_hash = models.CharField("定义指纹", max_length=80)
    target_schema_version = models.CharField("目标仓位 schema 版本", max_length=40)
    target_intent = models.CharField(
        "目标意图",
        max_length=40,
        choices=DecisionTargetIntent.choices,
        blank=True,
    )
    target_position_ratio = models.DecimalField(
        "目标总仓位比例",
        max_digits=20,
        decimal_places=18,
        null=True,
        blank=True,
    )
    target_confidence = models.DecimalField(
        "目标仓位置信评分",
        max_digits=20,
        decimal_places=18,
        null=True,
        blank=True,
    )
    target_reason_code = models.CharField("目标原因代码", max_length=120, blank=True)
    target_reason_summary_zh = models.CharField("中文原因摘要", max_length=1000, blank=True)
    frozen_trade_price_condition = models.JSONField("冻结策略价格条件", default=dict, blank=True)
    frozen_trade_price_condition_hash = models.CharField("冻结策略价格条件指纹", max_length=80, blank=True)
    decision_calculation_snapshot = models.JSONField("计算快照", default=dict, blank=True)
    input_snapshot = models.JSONField("输入快照", default=dict, blank=True)
    evidence_summary = models.JSONField("证据摘要", default=dict, blank=True)
    market_as_of_utc = models.DateTimeField("市场事实 UTC 时间", null=True, blank=True)
    analysis_close_time_utc = models.DateTimeField("分析收盘边界", null=True, blank=True)
    expires_at_utc = models.DateTimeField("过期 UTC 时间", null=True, blank=True)
    status = models.CharField("流程状态", max_length=40, choices=AnalysisObjectStatus.choices)
    is_usable = models.BooleanField("是否可用", default=False)
    allows_order_plan = models.BooleanField("允许 OrderPlan 消费", default=False)
    blocked_reason = models.CharField("阻断原因", max_length=120, blank=True)
    error_code = models.CharField("错误代码", max_length=120, blank=True)
    error_message = models.CharField("错误摘要", max_length=500, blank=True)
    trace_id = models.CharField("追踪 ID", max_length=80)
    trigger_source = models.CharField("触发来源", max_length=80)
    created_at_utc = models.DateTimeField("创建 UTC 时间", auto_now_add=True)
    updated_at_utc = models.DateTimeField("更新 UTC 时间", auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["strategy_signal_quality_result", "status"]),
            models.Index(fields=["release_hash", "definition_hash"]),
            models.Index(fields=["target_intent", "allows_order_plan"]),
            models.Index(fields=["expires_at_utc"]),
            models.Index(fields=["trace_id"]),
        ]
