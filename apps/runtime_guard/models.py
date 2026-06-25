"""RuntimeGuard models.

Module: RuntimeGuard
Responsibility: persist read-only guard scan runs and issues.
Not responsible for recovery, business mutation, lock release, Binance, DeepSeek,
Hermes sending, or trade execution.
Database: writes guard audit facts only. Redis: not used.
"""

from __future__ import annotations

from django.db import models


class RuntimeGuardRunStatus(models.TextChoices):
    RUNNING = "running", "运行中"
    SUCCEEDED = "succeeded", "已完成"
    PARTIAL_FAILED = "partial_failed", "部分失败"
    FAILED = "failed", "失败"


class RuntimeGuardIssueStatus(models.TextChoices):
    OPEN = "open", "未解决"
    ACKNOWLEDGED = "acknowledged", "已确认"
    RESOLVED = "resolved", "已解决"
    IGNORED = "ignored", "已忽略"


class RuntimeGuardIssueSeverity(models.TextChoices):
    INFO = "info", "普通"
    WARNING = "warning", "警告"
    HIGH = "high", "高风险"
    CRITICAL = "critical", "严重"


class RuntimeGuardRun(models.Model):
    run_key = models.CharField("巡检运行幂等键", max_length=191, unique=True)
    status = models.CharField("运行状态", max_length=40, choices=RuntimeGuardRunStatus.choices)
    trigger_source = models.CharField("触发来源", max_length=80)
    trace_id = models.CharField("技术追踪 ID", max_length=80)
    started_at_utc = models.DateTimeField("开始 UTC 时间")
    finished_at_utc = models.DateTimeField("结束 UTC 时间", null=True, blank=True)
    checked_item_count = models.PositiveIntegerField("检查对象数量", default=0)
    created_issue_count = models.PositiveIntegerField("新增问题数量", default=0)
    updated_issue_count = models.PositiveIntegerField("更新问题数量", default=0)
    alert_event_count = models.PositiveIntegerField("告警事件数量", default=0)
    error_count = models.PositiveIntegerField("错误数量", default=0)
    reason_code = models.CharField("原因代码", max_length=120, blank=True)
    reason_message = models.CharField("原因说明", max_length=500, blank=True)
    created_at_utc = models.DateTimeField("创建 UTC 时间", auto_now_add=True)
    updated_at_utc = models.DateTimeField("更新 UTC 时间", auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["status", "started_at_utc"]),
            models.Index(fields=["trace_id"]),
        ]


class RuntimeGuardIssue(models.Model):
    issue_key = models.CharField("问题幂等键", max_length=191, unique=True)
    issue_type = models.CharField("问题类型", max_length=120)
    severity = models.CharField("严重级别", max_length=20, choices=RuntimeGuardIssueSeverity.choices)
    status = models.CharField("问题状态", max_length=40, choices=RuntimeGuardIssueStatus.choices, default=RuntimeGuardIssueStatus.OPEN)
    first_seen_at_utc = models.DateTimeField("首次发现 UTC 时间")
    last_seen_at_utc = models.DateTimeField("最近发现 UTC 时间")
    occurrence_count = models.PositiveIntegerField("出现次数", default=1)
    resolved_at_utc = models.DateTimeField("解决 UTC 时间", null=True, blank=True)
    related_object_type = models.CharField("关联对象类型", max_length=120, blank=True)
    related_object_id = models.CharField("关联对象 ID", max_length=120, blank=True)
    related_trace_id = models.CharField("关联 trace_id", max_length=80, blank=True)
    description_zh = models.CharField("中文说明", max_length=500)
    evidence = models.JSONField("证据摘要", default=dict, blank=True)
    needs_manual_attention = models.BooleanField("是否需要人工关注", default=True)
    alert_event_id = models.PositiveBigIntegerField("AlertEvent ID", null=True, blank=True)
    last_alerted_at_utc = models.DateTimeField("最近告警 UTC 时间", null=True, blank=True)
    acknowledged_at_utc = models.DateTimeField("确认 UTC 时间", null=True, blank=True)
    acknowledged_by = models.CharField("确认人", max_length=120, blank=True)
    resolution_note = models.CharField("解决说明", max_length=500, blank=True)
    created_at_utc = models.DateTimeField("创建 UTC 时间", auto_now_add=True)
    updated_at_utc = models.DateTimeField("更新 UTC 时间", auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["status", "severity"]),
            models.Index(fields=["issue_type", "status"]),
            models.Index(fields=["related_object_type", "related_object_id"]),
            models.Index(fields=["related_trace_id"]),
        ]

