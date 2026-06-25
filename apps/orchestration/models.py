"""PipelineOrchestrator 模块：定义编排运行事实；读写 MySQL；不访问 Redis；不访问外部服务；不发送 Hermes；不调用大模型；不直接执行交易。"""

from __future__ import annotations

from django.db import models


class OrchestrationRunStatus(models.TextChoices):
    CREATED = "created", "已创建"
    RUNNING = "running", "运行中"
    WAITING = "waiting", "等待中"
    COMPLETED = "completed", "已完成"
    COMPLETED_NO_ACTION = "completed_no_action", "无动作完成"
    BLOCKED = "blocked", "受控阻断"
    UNKNOWN = "unknown", "未知结束"
    FAILED = "failed", "失败"
    STALE_INTERRUPTED = "stale_interrupted", "过期中断"


class OrchestrationFinalOutcome(models.TextChoices):
    NONE = "", "未结束"
    SUCCEEDED = "succeeded", "成功"
    NO_ACTION = "no_action", "无动作"
    BLOCKED = "blocked", "阻断"
    UNKNOWN = "unknown", "未知"
    FAILED = "failed", "失败"
    STALE_INTERRUPTED = "stale_interrupted", "过期中断"


class OrchestrationStepRunStatus(models.TextChoices):
    CREATED = "created", "已创建"
    RUNNING = "running", "运行中"
    WAITING = "waiting", "等待中"
    SUCCEEDED = "succeeded", "成功"
    NO_ACTION = "no_action", "无动作"
    BLOCKED = "blocked", "阻断"
    UNKNOWN = "unknown", "未知"
    FAILED = "failed", "失败"
    SKIPPED = "skipped", "跳过"


class OrchestrationTriggerMode(models.TextChoices):
    AUTOMATIC = "automatic", "自动"
    MANUAL_DIAGNOSTIC = "manual_diagnostic", "人工诊断"
    MANUAL_RECOVERY = "manual_recovery", "人工恢复"


class OrchestrationObjectRole(models.TextChoices):
    PRIMARY = "primary", "主对象"
    INPUT = "input", "输入对象"
    OUTPUT = "output", "输出对象"
    RELATED = "related", "相关对象"
    AUDIT = "audit", "审计对象"


class OrchestrationRun(models.Model):
    run_key = models.CharField("编排运行幂等键", max_length=191, unique=True)
    pipeline_code = models.CharField("流水线代码", max_length=80)
    registry_version = models.CharField("Registry 版本", max_length=80)
    registry_hash = models.CharField("Registry 指纹", max_length=80)
    strategy_analysis_release_id = models.PositiveBigIntegerField("冻结策略版本包 ID", null=True, blank=True)
    strategy_analysis_release_hash = models.CharField("冻结策略版本包指纹", max_length=80, blank=True)
    strategy_analysis_release_freeze_status = models.CharField("策略版本冻结状态", max_length=40, blank=True)
    strategy_analysis_release_freeze_reason_code = models.CharField("策略版本冻结原因", max_length=120, blank=True)
    run_config_snapshot_hash = models.CharField("运行配置快照指纹", max_length=80, blank=True)
    scheduled_for_utc = models.DateTimeField("计划 UTC 时间")
    cycle_kind = models.CharField("周期类型", max_length=80)
    trigger_mode = models.CharField("触发模式", max_length=40, choices=OrchestrationTriggerMode.choices)
    trigger_source = models.CharField("触发来源", max_length=80)
    status = models.CharField("运行状态", max_length=40, choices=OrchestrationRunStatus.choices)
    final_outcome = models.CharField("最终结果", max_length=40, choices=OrchestrationFinalOutcome.choices, blank=True)
    reason_code = models.CharField("原因代码", max_length=120, blank=True)
    reason_message = models.CharField("原因说明", max_length=500, blank=True)
    current_step_code = models.CharField("当前步骤", max_length=80, blank=True)
    last_completed_step_code = models.CharField("最后完成步骤", max_length=80, blank=True)
    last_stopped_step_code = models.CharField("停止步骤", max_length=80, blank=True)
    needs_manual_attention = models.BooleanField("是否需要人工关注", default=False)
    trace_id = models.CharField("技术追踪 ID", max_length=80)
    started_at_utc = models.DateTimeField("开始 UTC 时间", null=True, blank=True)
    waiting_since_utc = models.DateTimeField("等待开始 UTC 时间", null=True, blank=True)
    finished_at_utc = models.DateTimeField("完成 UTC 时间", null=True, blank=True)
    created_at_utc = models.DateTimeField("创建 UTC 时间", auto_now_add=True)
    updated_at_utc = models.DateTimeField("更新 UTC 时间", auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["pipeline_code", "scheduled_for_utc", "cycle_kind", "trigger_mode"],
                name="uniq_orchestration_run_schedule",
            )
        ]
        indexes = [
            models.Index(fields=["status", "updated_at_utc"]),
            models.Index(fields=["pipeline_code", "scheduled_for_utc"]),
            models.Index(fields=["trace_id"]),
        ]


class OrchestrationRunConfigSnapshot(models.Model):
    orchestration_run = models.OneToOneField(
        OrchestrationRun,
        on_delete=models.CASCADE,
        related_name="config_snapshot",
    )
    registry_version = models.CharField("Registry 版本", max_length=80)
    registry_hash = models.CharField("Registry 指纹", max_length=80)
    strategy_analysis_release_id = models.PositiveBigIntegerField("冻结策略版本包 ID", null=True, blank=True)
    strategy_analysis_release_hash = models.CharField("冻结策略版本包指纹", max_length=80, blank=True)
    adapter_versions = models.JSONField("Adapter 版本", default=dict)
    result_mapping_versions = models.JSONField("结果映射版本", default=dict)
    config_snapshot = models.JSONField("运行配置快照", default=dict)
    snapshot_hash = models.CharField("快照指纹", max_length=80)
    created_at_utc = models.DateTimeField("创建 UTC 时间", auto_now_add=True)


class OrchestrationStepRun(models.Model):
    orchestration_run = models.ForeignKey(OrchestrationRun, on_delete=models.CASCADE, related_name="step_runs")
    step_code = models.CharField("步骤代码", max_length=80)
    module_code = models.CharField("模块代码", max_length=80)
    adapter_code = models.CharField("Adapter 代码", max_length=120)
    adapter_version = models.CharField("Adapter 版本", max_length=80)
    result_mapping_version = models.CharField("结果映射版本", max_length=80)
    execution_sequence = models.PositiveIntegerField("执行序号")
    business_request_key = models.CharField("业务幂等键", max_length=191, unique=True)
    status = models.CharField("步骤状态", max_length=40, choices=OrchestrationStepRunStatus.choices)
    normalized_status = models.CharField("统一业务状态", max_length=40, blank=True)
    flow_action = models.CharField("流程动作", max_length=40, blank=True)
    reason_code = models.CharField("原因代码", max_length=120, blank=True)
    reason_message = models.CharField("原因说明", max_length=500, blank=True)
    raw_business_status = models.CharField("原始业务状态", max_length=80, blank=True)
    raw_result_summary = models.JSONField("脱敏原始结果摘要", default=dict, blank=True)
    raw_result_hash = models.CharField("原始结果指纹", max_length=80, blank=True)
    primary_object_type = models.CharField("主对象类型", max_length=120, blank=True)
    primary_object_id = models.CharField("主对象 ID", max_length=120, blank=True)
    resume_token = models.CharField("恢复令牌", max_length=191, unique=True, null=True, blank=True)
    resume_step_code = models.CharField("恢复步骤", max_length=80, blank=True)
    waiting_object_type = models.CharField("等待对象类型", max_length=120, blank=True)
    waiting_object_id = models.CharField("等待对象 ID", max_length=120, blank=True)
    next_check_at_utc = models.DateTimeField("下次检查 UTC 时间", null=True, blank=True)
    needs_manual_attention = models.BooleanField("是否需要人工关注", default=False)
    trace_id = models.CharField("技术追踪 ID", max_length=80)
    started_at_utc = models.DateTimeField("开始 UTC 时间", null=True, blank=True)
    waiting_since_utc = models.DateTimeField("等待开始 UTC 时间", null=True, blank=True)
    finished_at_utc = models.DateTimeField("完成 UTC 时间", null=True, blank=True)
    last_status_updated_at_utc = models.DateTimeField("最后状态更新时间", null=True, blank=True)
    created_at_utc = models.DateTimeField("创建 UTC 时间", auto_now_add=True)
    updated_at_utc = models.DateTimeField("更新 UTC 时间", auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["orchestration_run", "step_code", "execution_sequence"],
                name="uniq_orchestration_step_sequence",
            )
        ]
        indexes = [
            models.Index(fields=["orchestration_run", "execution_sequence"]),
            models.Index(fields=["status", "updated_at_utc"]),
            models.Index(fields=["step_code", "status"]),
            models.Index(fields=["trace_id"]),
        ]


class OrchestrationBusinessObjectLink(models.Model):
    orchestration_run = models.ForeignKey(OrchestrationRun, on_delete=models.CASCADE, related_name="business_object_links")
    step_run = models.ForeignKey(OrchestrationStepRun, on_delete=models.CASCADE, related_name="business_object_links")
    step_code = models.CharField("步骤代码", max_length=80)
    module_code = models.CharField("模块代码", max_length=80)
    object_role = models.CharField("对象角色", max_length=40, choices=OrchestrationObjectRole.choices)
    object_type = models.CharField("对象类型", max_length=120)
    object_id = models.CharField("对象 ID", max_length=120)
    object_label = models.CharField("对象标签", max_length=200, blank=True)
    ref_strategy = models.CharField("引用策略", max_length=40, default="explicit_refs")
    trace_id = models.CharField("技术追踪 ID", max_length=80)
    created_at_utc = models.DateTimeField("创建 UTC 时间", auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["step_run", "object_role", "object_type", "object_id"],
                name="uniq_orchestration_object_link",
            )
        ]
        indexes = [
            models.Index(fields=["orchestration_run", "step_code"]),
            models.Index(fields=["object_type", "object_id"]),
            models.Index(fields=["step_code", "object_type"]),
            models.Index(fields=["trace_id"]),
        ]
