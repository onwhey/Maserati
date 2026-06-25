"""AIReview models.

Module: AIReview
Responsibility: persist offline AI review requests, packages, attempts,
reports, findings, and human suggestions.
Not responsible for real-time trading, strategy mutation, risk mutation,
order mutation, account mutation, Binance access, Hermes sending, or direct
DeepSeek HTTP access.
Database: reads/writes AIReview facts and references existing facts.
Redis: not used in models. External services: not used in models.
LLM: not called in models. Trade execution: not involved. Real trading: never.
"""

from __future__ import annotations

from django.db import models


class AIReviewMode(models.TextChoices):
    CYCLE_REVIEW = "cycle_review", "周期复盘"
    ANOMALY_REVIEW = "anomaly_review", "异常复盘"
    ORDER_LIFECYCLE_REVIEW = "order_lifecycle_review", "订单生命周期复盘"
    PERFORMANCE_ATTRIBUTION_REVIEW = "performance_attribution_review", "绩效归因复盘"
    MANUAL_QUESTION_REVIEW = "manual_question_review", "人工问题复盘"


class AIReviewRequestStatus(models.TextChoices):
    CREATED = "created", "已创建"
    PACKAGING = "packaging", "构建数据包中"
    PACKAGED = "packaged", "数据包已构建"
    CALLING_MODEL = "calling_model", "调用模型中"
    COMPLETED = "completed", "已完成"
    BLOCKED = "blocked", "已阻断"
    UNKNOWN = "unknown", "未知"
    FAILED = "failed", "失败"
    CANCELED = "canceled", "已取消"


class AIReviewPackageStatus(models.TextChoices):
    BUILT = "built", "已构建"
    BLOCKED = "blocked", "已阻断"
    FAILED = "failed", "失败"


class AIReviewAttemptStatus(models.TextChoices):
    CALLING = "calling", "调用中"
    SUCCEEDED = "succeeded", "成功"
    FAILED = "failed", "失败"
    UNKNOWN = "unknown", "未知"
    RESPONSE_PARSE_ERROR = "response_parse_error", "响应解析失败"


class AIReviewFindingSeverity(models.TextChoices):
    INFO = "info", "普通"
    WARNING = "warning", "警告"
    HIGH = "high", "高风险"
    CRITICAL = "critical", "严重"


class AIReviewSuggestionStatus(models.TextChoices):
    PENDING_REVIEW = "pending_review", "待人工审核"
    ACCEPTED = "accepted", "已接受"
    REJECTED = "rejected", "已拒绝"
    CONVERTED_TO_TASK = "converted_to_task", "已转人工任务"
    IMPLEMENTED = "implemented", "已人工落地"
    IGNORED = "ignored", "已忽略"


class AIReviewRequest(models.Model):
    request_key = models.CharField("复盘请求幂等键", max_length=191, unique=True)
    review_mode = models.CharField("复盘模式", max_length=80, choices=AIReviewMode.choices)
    status = models.CharField(
        "请求状态",
        max_length=40,
        choices=AIReviewRequestStatus.choices,
        default=AIReviewRequestStatus.CREATED,
    )
    reason_code = models.CharField("原因代码", max_length=120, blank=True)
    reason_message = models.CharField("原因说明", max_length=500, blank=True)
    range_selector = models.JSONField("原始范围选择", default=dict, blank=True)
    filters = models.JSONField("过滤条件", default=dict, blank=True)
    frozen_orchestration_run_ids = models.JSONField("冻结编排运行 ID", default=list, blank=True)
    frozen_range_hash = models.CharField("冻结范围指纹", max_length=80, blank=True)
    manual_question = models.TextField("人工问题", blank=True)
    model_profile_code = models.CharField("模型套餐编号", max_length=120)
    requested_by = models.CharField("请求人", max_length=120)
    prompt_name = models.CharField("Prompt 名称", max_length=120, blank=True)
    prompt_version = models.CharField("Prompt 版本", max_length=80, blank=True)
    prompt_hash = models.CharField("Prompt 指纹", max_length=80, blank=True)
    prompt_schema_version = models.CharField("Prompt schema 版本", max_length=40, blank=True)
    output_schema_version = models.CharField("输出 schema 版本", max_length=40, blank=True)
    active_package = models.ForeignKey(
        "AIReviewPackage",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
    )
    completed_report = models.ForeignKey(
        "AIReviewReport",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
    )
    attempt_count = models.PositiveIntegerField("模型调用尝试次数", default=0)
    input_size_estimate = models.PositiveIntegerField("输入大小估算", default=0)
    input_token_count = models.PositiveIntegerField("输入 token 数", default=0)
    output_token_count = models.PositiveIntegerField("输出 token 数", default=0)
    total_token_count = models.PositiveIntegerField("总 token 数", default=0)
    cost_estimate = models.DecimalField("成本估算", max_digits=20, decimal_places=8, default=0)
    trace_id = models.CharField("技术追踪 ID", max_length=80)
    trigger_source = models.CharField("触发来源", max_length=80)
    created_at_utc = models.DateTimeField("创建 UTC 时间", auto_now_add=True)
    updated_at_utc = models.DateTimeField("更新 UTC 时间", auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["review_mode", "status", "created_at_utc"]),
            models.Index(fields=["requested_by", "created_at_utc"]),
            models.Index(fields=["trace_id"]),
        ]

    def __str__(self) -> str:
        return f"AIReviewRequest<{self.id}:{self.review_mode}:{self.status}>"


class AIReviewPackage(models.Model):
    review_request = models.ForeignKey(AIReviewRequest, on_delete=models.CASCADE, related_name="packages")
    status = models.CharField("数据包状态", max_length=40, choices=AIReviewPackageStatus.choices, default=AIReviewPackageStatus.BUILT)
    package_format = models.CharField("数据包格式", max_length=40, default="json")
    data_schema_version = models.CharField("数据 schema 版本", max_length=40)
    sanitization_version = models.CharField("脱敏版本", max_length=40)
    package_hash = models.CharField("数据包指纹", max_length=80)
    input_refs_hash = models.CharField("输入引用指纹", max_length=80)
    run_count = models.PositiveIntegerField("运行数量", default=0)
    order_count = models.PositiveIntegerField("订单数量", default=0)
    alert_count = models.PositiveIntegerField("告警数量", default=0)
    runtime_issue_count = models.PositiveIntegerField("巡检问题数量", default=0)
    performance_record_count = models.PositiveIntegerField("绩效记录数量", default=0)
    payload_size_bytes = models.PositiveIntegerField("载荷字节数", default=0)
    input_size_estimate = models.PositiveIntegerField("输入大小估算", default=0)
    sanitized = models.BooleanField("是否已脱敏", default=True)
    sanitization_report = models.JSONField("脱敏报告", default=dict, blank=True)
    json_payload = models.JSONField("结构化复盘数据包", default=dict, blank=True)
    markdown_summary = models.TextField("Markdown 摘要", blank=True)
    payload_storage_ref = models.CharField("外部存储引用", max_length=500, blank=True)
    trace_id = models.CharField("技术追踪 ID", max_length=80)
    created_at_utc = models.DateTimeField("创建 UTC 时间", auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["review_request", "package_hash"], name="uniq_ai_review_package_hash")
        ]
        indexes = [
            models.Index(fields=["review_request", "created_at_utc"]),
            models.Index(fields=["package_hash"]),
            models.Index(fields=["trace_id"]),
        ]


class AIReviewAttempt(models.Model):
    review_request = models.ForeignKey(AIReviewRequest, on_delete=models.CASCADE, related_name="attempts")
    review_package = models.ForeignKey(AIReviewPackage, on_delete=models.PROTECT, related_name="attempts")
    attempt_sequence = models.PositiveIntegerField("尝试序号")
    gateway_status = models.CharField("Gateway 状态", max_length=80, blank=True)
    status = models.CharField("尝试状态", max_length=40, choices=AIReviewAttemptStatus.choices)
    request_sent = models.BooleanField("是否发出请求", default=False)
    provider = models.CharField("Provider", max_length=80, default="deepseek")
    provider_request_id = models.CharField("Provider 请求 ID", max_length=191, blank=True)
    model_profile_code = models.CharField("模型套餐编号", max_length=120)
    model_name = models.CharField("模型名称", max_length=120, blank=True)
    sanitized_model_profile_summary = models.JSONField("脱敏模型配置摘要", default=dict, blank=True)
    api_format = models.CharField("API 格式", max_length=80, blank=True)
    prompt_hash = models.CharField("Prompt 指纹", max_length=80)
    input_package_hash = models.CharField("输入数据包指纹", max_length=80)
    idempotency_key = models.CharField("Gateway 幂等键", max_length=191)
    finish_reason = models.CharField("结束原因", max_length=120, blank=True)
    input_token_count = models.PositiveIntegerField("输入 token 数", default=0)
    output_token_count = models.PositiveIntegerField("输出 token 数", default=0)
    total_token_count = models.PositiveIntegerField("总 token 数", default=0)
    attempt_count_in_gateway = models.PositiveIntegerField("Gateway 内部尝试次数", default=0)
    retryable = models.BooleanField("是否可重试", default=False)
    http_status = models.IntegerField("HTTP 状态码", null=True, blank=True)
    provider_error_code = models.CharField("Provider 错误码", max_length=120, blank=True)
    error_code = models.CharField("错误码", max_length=120, blank=True)
    error_message = models.CharField("错误说明", max_length=500, blank=True)
    sanitized_request_summary = models.JSONField("脱敏请求摘要", default=dict, blank=True)
    sanitized_response_summary = models.JSONField("脱敏响应摘要", default=dict, blank=True)
    started_at_utc = models.DateTimeField("开始 UTC 时间", null=True, blank=True)
    finished_at_utc = models.DateTimeField("结束 UTC 时间", null=True, blank=True)
    duration_ms = models.PositiveIntegerField("耗时毫秒", null=True, blank=True)
    trace_id = models.CharField("技术追踪 ID", max_length=80)
    created_at_utc = models.DateTimeField("创建 UTC 时间", auto_now_add=True)
    updated_at_utc = models.DateTimeField("更新 UTC 时间", auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["review_request", "attempt_sequence"], name="uniq_ai_review_attempt_sequence")
        ]
        indexes = [
            models.Index(fields=["review_request", "status"]),
            models.Index(fields=["trace_id"]),
        ]


class AIReviewReport(models.Model):
    review_request = models.OneToOneField(AIReviewRequest, on_delete=models.CASCADE, related_name="report")
    review_attempt = models.OneToOneField(AIReviewAttempt, on_delete=models.PROTECT, related_name="report")
    review_package = models.ForeignKey(AIReviewPackage, on_delete=models.PROTECT, related_name="reports")
    title = models.CharField("标题", max_length=300)
    summary = models.TextField("摘要")
    full_report_markdown = models.TextField("完整报告 Markdown", blank=True)
    structured_report_json = models.JSONField("结构化报告 JSON", default=dict, blank=True)
    review_mode = models.CharField("复盘模式", max_length=80, choices=AIReviewMode.choices)
    model_provider = models.CharField("模型 Provider", max_length=80, default="deepseek")
    model_profile_code = models.CharField("模型套餐编号", max_length=120)
    model_name = models.CharField("模型名称", max_length=120, blank=True)
    prompt_name = models.CharField("Prompt 名称", max_length=120)
    prompt_version = models.CharField("Prompt 版本", max_length=80)
    prompt_hash = models.CharField("Prompt 指纹", max_length=80)
    package_hash = models.CharField("数据包指纹", max_length=80)
    output_hash = models.CharField("输出指纹", max_length=80)
    confidence = models.DecimalField("置信度", max_digits=10, decimal_places=6, default=0)
    data_limitations = models.JSONField("数据限制说明", default=list, blank=True)
    trace_id = models.CharField("技术追踪 ID", max_length=80)
    created_at_utc = models.DateTimeField("创建 UTC 时间", auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["review_mode", "created_at_utc"]),
            models.Index(fields=["trace_id"]),
        ]


class AIReviewFinding(models.Model):
    review_report = models.ForeignKey(AIReviewReport, on_delete=models.CASCADE, related_name="findings")
    finding_type = models.CharField("发现类型", max_length=120)
    severity = models.CharField("严重程度", max_length=20, choices=AIReviewFindingSeverity.choices, default=AIReviewFindingSeverity.INFO)
    title = models.CharField("标题", max_length=300)
    description = models.TextField("描述")
    evidence_refs = models.JSONField("证据引用", default=list, blank=True)
    related_orchestration_run_ids = models.JSONField("相关编排 ID", default=list, blank=True)
    related_order_submission_attempt_ids = models.JSONField("相关订单提交 ID", default=list, blank=True)
    related_object_refs = models.JSONField("相关对象引用", default=list, blank=True)
    confidence = models.DecimalField("置信度", max_digits=10, decimal_places=6, default=0)
    needs_manual_attention = models.BooleanField("是否需要人工关注", default=False)
    trace_id = models.CharField("技术追踪 ID", max_length=80)
    created_at_utc = models.DateTimeField("创建 UTC 时间", auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["review_report", "severity"]),
            models.Index(fields=["finding_type", "severity"]),
            models.Index(fields=["trace_id"]),
        ]


class AIReviewSuggestion(models.Model):
    review_report = models.ForeignKey(AIReviewReport, on_delete=models.CASCADE, related_name="suggestions")
    suggestion_type = models.CharField("建议类型", max_length=120)
    priority = models.CharField("优先级", max_length=40, blank=True)
    title = models.CharField("标题", max_length=300)
    description = models.TextField("描述")
    target_area = models.CharField("目标领域", max_length=120, blank=True)
    target_object_type = models.CharField("目标对象类型", max_length=120, blank=True)
    target_object_id = models.CharField("目标对象 ID", max_length=120, blank=True)
    suggested_action = models.TextField("建议动作", blank=True)
    rationale = models.TextField("理由", blank=True)
    expected_impact = models.TextField("预期影响", blank=True)
    risk_note = models.TextField("风险说明", blank=True)
    status = models.CharField(
        "建议状态",
        max_length=40,
        choices=AIReviewSuggestionStatus.choices,
        default=AIReviewSuggestionStatus.PENDING_REVIEW,
    )
    reviewed_by = models.CharField("审核人", max_length=120, blank=True)
    reviewed_at_utc = models.DateTimeField("审核 UTC 时间", null=True, blank=True)
    decision_note = models.CharField("人工决策说明", max_length=500, blank=True)
    trace_id = models.CharField("技术追踪 ID", max_length=80)
    created_at_utc = models.DateTimeField("创建 UTC 时间", auto_now_add=True)
    updated_at_utc = models.DateTimeField("更新 UTC 时间", auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["status", "created_at_utc"]),
            models.Index(fields=["suggestion_type", "status"]),
            models.Index(fields=["trace_id"]),
        ]
