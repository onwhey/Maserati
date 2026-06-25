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


class NotificationDeliveryStatus(models.TextChoices):
    PENDING = "pending", "待投递"
    SENDING = "sending", "投递中"
    SENT = "sent", "已投递"
    FAILED = "failed", "投递失败"
    SUPPRESSED = "suppressed", "已抑制"
    ABANDONED = "abandoned", "已放弃"


class NotificationRoute(models.Model):
    route_code = models.CharField("路由代码", max_length=120)
    route_version = models.CharField("路由版本", max_length=40, default="1.0")
    source_module = models.CharField("来源模块", max_length=80, blank=True)
    event_category = models.CharField("事件分类", max_length=80, blank=True)
    event_type = models.CharField("事件类型", max_length=120, blank=True)
    min_severity = models.CharField("最低严重级别", max_length=20, choices=AlertSeverity.choices, default=AlertSeverity.INFO)
    channel = models.CharField("通知渠道", max_length=80, default="hermes")
    template_code = models.CharField("模板代码", max_length=120, blank=True)
    template_version = models.CharField("模板版本", max_length=40, blank=True)
    enabled = models.BooleanField("是否启用", default=True)
    cooldown_seconds = models.PositiveIntegerField("冷却秒数", default=0)
    max_attempts = models.PositiveIntegerField("最大投递次数", default=1)
    retry_policy = models.JSONField("重试策略", default=dict, blank=True)
    route_hash = models.CharField("路由指纹", max_length=80, blank=True)
    created_at_utc = models.DateTimeField("创建 UTC 时间", auto_now_add=True)
    updated_at_utc = models.DateTimeField("更新 UTC 时间", auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["route_code", "route_version"], name="uniq_notification_route_version")
        ]
        indexes = [
            models.Index(fields=["enabled", "event_category", "event_type"]),
            models.Index(fields=["source_module", "enabled"]),
        ]


class NotificationTemplate(models.Model):
    template_code = models.CharField("模板代码", max_length=120)
    template_version = models.CharField("模板版本", max_length=40, default="1.0")
    channel = models.CharField("通知渠道", max_length=80, default="hermes")
    language = models.CharField("语言", max_length=20, default="zh")
    title_template = models.CharField("标题模板", max_length=300)
    body_template = models.TextField("正文模板")
    max_length = models.PositiveIntegerField("最大长度", default=4000)
    enabled = models.BooleanField("是否启用", default=True)
    template_hash = models.CharField("模板指纹", max_length=80, blank=True)
    created_at_utc = models.DateTimeField("创建 UTC 时间", auto_now_add=True)
    updated_at_utc = models.DateTimeField("更新 UTC 时间", auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["template_code", "template_version"], name="uniq_notification_template_version")
        ]
        indexes = [
            models.Index(fields=["enabled", "channel"]),
        ]


class NotificationDeliveryAttempt(models.Model):
    delivery_attempt_key = models.CharField("投递尝试幂等键", max_length=191, unique=True)
    alert_event = models.ForeignKey(AlertEvent, on_delete=models.CASCADE, related_name="delivery_attempts")
    channel = models.CharField("通知渠道", max_length=80)
    route_code = models.CharField("路由代码", max_length=120, blank=True)
    template_code = models.CharField("模板代码", max_length=120, blank=True)
    template_version = models.CharField("模板版本", max_length=40, blank=True)
    route_config_hash = models.CharField("路由配置指纹", max_length=80, blank=True)
    template_hash = models.CharField("模板指纹", max_length=80, blank=True)
    delivery_status = models.CharField(
        "投递状态",
        max_length=40,
        choices=NotificationDeliveryStatus.choices,
        default=NotificationDeliveryStatus.PENDING,
    )
    attempt_sequence = models.PositiveIntegerField("尝试序号", default=1)
    provider_idempotency_key = models.CharField("供应商幂等键", max_length=191, blank=True)
    provider_message_id = models.CharField("供应商消息 ID", max_length=191, blank=True)
    request_sent = models.BooleanField("是否已发出请求", default=False)
    http_status = models.IntegerField("HTTP 状态码", null=True, blank=True)
    provider_error_code = models.CharField("供应商错误码", max_length=120, blank=True)
    error_code = models.CharField("错误码", max_length=120, blank=True)
    error_message = models.CharField("错误说明", max_length=500, blank=True)
    retryable = models.BooleanField("是否可重试", default=False)
    next_retry_at_utc = models.DateTimeField("下次重试 UTC 时间", null=True, blank=True)
    claimed_at_utc = models.DateTimeField("领取 UTC 时间", null=True, blank=True)
    started_at_utc = models.DateTimeField("开始 UTC 时间", null=True, blank=True)
    finished_at_utc = models.DateTimeField("结束 UTC 时间", null=True, blank=True)
    duration_ms = models.PositiveIntegerField("耗时毫秒", null=True, blank=True)
    sanitized_request_summary = models.JSONField("脱敏请求摘要", default=dict, blank=True)
    sanitized_response_summary = models.JSONField("脱敏响应摘要", default=dict, blank=True)
    trace_id = models.CharField("技术追踪 ID", max_length=80)
    created_at_utc = models.DateTimeField("创建 UTC 时间", auto_now_add=True)
    updated_at_utc = models.DateTimeField("更新 UTC 时间", auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["alert_event", "route_code", "channel", "attempt_sequence"],
                name="uniq_notification_attempt_sequence",
            )
        ]
        indexes = [
            models.Index(fields=["delivery_status", "created_at_utc"]),
            models.Index(fields=["alert_event", "delivery_status"]),
            models.Index(fields=["trace_id"]),
        ]


class NotificationSuppression(models.Model):
    alert_event = models.ForeignKey(AlertEvent, on_delete=models.CASCADE, related_name="suppressions")
    suppression_type = models.CharField("抑制类型", max_length=80)
    dedupe_key = models.CharField("去重键", max_length=255, blank=True)
    cooldown_key = models.CharField("冷却键", max_length=255, blank=True)
    window_start_utc = models.DateTimeField("窗口开始 UTC 时间", null=True, blank=True)
    window_end_utc = models.DateTimeField("窗口结束 UTC 时间", null=True, blank=True)
    reason_code = models.CharField("原因代码", max_length=120)
    trace_id = models.CharField("技术追踪 ID", max_length=80)
    created_at_utc = models.DateTimeField("创建 UTC 时间", auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["alert_event", "reason_code"]),
            models.Index(fields=["suppression_type", "created_at_utc"]),
            models.Index(fields=["trace_id"]),
        ]
