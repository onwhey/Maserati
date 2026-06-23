"""Notifications 模块：定义 AlertEvent 事实；读写数据库，不访问外部服务，不发送 Hermes，不涉及交易执行。"""

from __future__ import annotations

from django.db import models
from django.utils import timezone


class AlertSeverity(models.TextChoices):
    INFO = "info", "普通"
    WARNING = "warning", "警告"
    HIGH = "high", "高风险"
    CRITICAL = "critical", "严重"


class AlertEvent(models.Model):
    event_key = models.CharField("事件幂等键", max_length=191, unique=True)
    source_module = models.CharField("来源模块", max_length=80)
    event_type = models.CharField("事件类型", max_length=120)
    event_category = models.CharField("事件分类", max_length=80)
    severity = models.CharField("严重级别", max_length=20, choices=AlertSeverity.choices)
    title_zh = models.CharField("中文标题", max_length=200)
    message_zh = models.TextField("中文摘要")
    business_status = models.CharField("业务状态", max_length=80, blank=True)
    reason_code = models.CharField("原因代码", max_length=120, blank=True)
    reason_message = models.CharField("原因说明", max_length=500, blank=True)
    related_object_type = models.CharField("关联对象类型", max_length=120, blank=True)
    related_object_id = models.CharField("关联对象 ID", max_length=120, blank=True)
    related_object_label = models.CharField("关联对象标签", max_length=200, blank=True)
    correlation_key = models.CharField("关联键", max_length=255, blank=True)
    dedupe_key = models.CharField("去重键", max_length=255, blank=True)
    cooldown_key = models.CharField("冷却键", max_length=255, blank=True)
    trace_id = models.CharField("技术追踪 ID", max_length=80)
    trigger_source = models.CharField("触发来源", max_length=80)
    event_time_utc = models.DateTimeField("事件 UTC 时间", default=timezone.now)
    payload_summary = models.JSONField("脱敏载荷摘要", default=dict, blank=True)
    evidence_refs = models.JSONField("证据引用", default=list, blank=True)
    is_dry_run = models.BooleanField("是否 dry-run", default=False)
    delivery_enabled = models.BooleanField("是否允许外部投递", default=False)
    created_at_utc = models.DateTimeField("创建 UTC 时间", auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["source_module", "event_type"]),
            models.Index(fields=["severity", "created_at_utc"]),
            models.Index(fields=["trace_id"]),
            models.Index(fields=["related_object_type", "related_object_id"]),
        ]
        verbose_name = "告警事件"
        verbose_name_plural = "告警事件"

    def __str__(self) -> str:
        return f"{self.event_type}:{self.event_key}"
