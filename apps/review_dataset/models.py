"""ReviewDataset 模块：定义离线复盘数据集索引与导出记录。

负责：保存已落库事实的复盘数据索引、导出请求和导出清单。
不负责：计算策略优劣、调用大模型、请求 Binance、生成交易信号、修改交易链路。
读写数据库：写 ReviewDatasetRecord / ReviewDatasetExport，读取已落库事实由 service 完成。
访问 Redis：不涉及。
访问外部服务：不涉及。
发送 Hermes：不涉及；只允许通过 AlertEvent 记录导出事件。
调用大模型：不涉及。
涉及交易执行：不涉及。
允许真实交易：不允许。
"""

from __future__ import annotations

from django.db import models


class ReviewDatasetBuildStatus(models.TextChoices):
    BUILT = "built", "已生成"
    PARTIAL = "partial", "部分生成"
    BLOCKED = "blocked", "已阻断"
    FAILED = "failed", "生成失败"


class ReviewDatasetExportStatus(models.TextChoices):
    CREATED = "created", "已创建"
    BUILT = "built", "已生成"
    BLOCKED = "blocked", "已阻断"
    FAILED = "failed", "生成失败"


class ReviewDatasetRecord(models.Model):
    subject_orchestration_run = models.ForeignKey(
        "orchestration.OrchestrationRun",
        on_delete=models.PROTECT,
        related_name="review_dataset_subject_records",
    )
    start_boundary_orchestration_run = models.ForeignKey(
        "orchestration.OrchestrationRun",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="review_dataset_start_boundary_records",
    )
    end_boundary_orchestration_run = models.ForeignKey(
        "orchestration.OrchestrationRun",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="review_dataset_end_boundary_records",
    )
    cleanup_orchestration_run = models.ForeignKey(
        "orchestration.OrchestrationRun",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="review_dataset_cleanup_records",
    )
    period_start_utc = models.DateTimeField("周期开始 UTC")
    period_end_utc = models.DateTimeField("周期结束 UTC")
    exchange = models.CharField("交易所", max_length=40, default="binance")
    market_type = models.CharField("市场类型", max_length=40)
    account_domain = models.CharField("账户域", max_length=120)
    symbol = models.CharField("交易品种", max_length=40)
    dataset_schema_version = models.CharField("数据集 schema 版本", max_length=40, default="1.0")
    build_status = models.CharField(
        "生成状态",
        max_length=40,
        choices=ReviewDatasetBuildStatus.choices,
        default=ReviewDatasetBuildStatus.BUILT,
    )
    reason_code = models.CharField("原因代码", max_length=120)
    reason_message = models.CharField("原因说明", max_length=500, blank=True)
    input_refs_hash = models.CharField("输入事实引用 hash", max_length=80)
    record_content_hash = models.CharField("记录内容 hash", max_length=80)
    object_counts = models.JSONField("对象计数", default=dict, blank=True)
    object_refs = models.JSONField("对象引用", default=dict, blank=True)
    summary = models.JSONField("脱敏摘要", default=dict, blank=True)
    missing_facts = models.JSONField("缺失事实", default=list, blank=True)
    trace_id = models.CharField("技术追踪 ID", max_length=80)
    trigger_source = models.CharField("触发来源", max_length=80)
    operator_id = models.CharField("操作者 ID", max_length=120, blank=True)
    built_at_utc = models.DateTimeField("生成 UTC 时间")
    created_at_utc = models.DateTimeField("创建 UTC 时间", auto_now_add=True)
    updated_at_utc = models.DateTimeField("更新 UTC 时间", auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["subject_orchestration_run", "dataset_schema_version", "input_refs_hash"],
                name="uniq_review_dataset_record_input",
            )
        ]
        indexes = [
            models.Index(fields=["period_start_utc", "period_end_utc"]),
            models.Index(fields=["market_type", "account_domain", "symbol"]),
            models.Index(fields=["build_status", "built_at_utc"]),
            models.Index(fields=["trace_id"]),
        ]

    def __str__(self) -> str:
        return f"ReviewDatasetRecord<{self.subject_orchestration_run_id}:{self.symbol}>"


class ReviewDatasetExport(models.Model):
    export_key = models.CharField("导出幂等键", max_length=191, unique=True)
    status = models.CharField(
        "导出状态",
        max_length=40,
        choices=ReviewDatasetExportStatus.choices,
        default=ReviewDatasetExportStatus.CREATED,
    )
    range_selector = models.JSONField("导出范围", default=dict, blank=True)
    filters = models.JSONField("导出过滤条件", default=dict, blank=True)
    export_format = models.CharField("导出格式", max_length=20, default="json")
    dataset_schema_version = models.CharField("数据集 schema 版本", max_length=40, default="1.0")
    record_count = models.PositiveIntegerField("记录数量", default=0)
    file_count = models.PositiveIntegerField("文件数量", default=0)
    row_counts = models.JSONField("行数统计", default=dict, blank=True)
    file_list = models.JSONField("文件清单", default=list, blank=True)
    manifest = models.JSONField("导出清单", default=dict, blank=True)
    content_hash = models.CharField("导出内容 hash", max_length=80, blank=True)
    storage_ref = models.CharField("导出存储引用", max_length=500, blank=True)
    reason_code = models.CharField("原因代码", max_length=120)
    reason_message = models.CharField("原因说明", max_length=500, blank=True)
    requested_by = models.CharField("请求人", max_length=120)
    reason = models.CharField("操作原因", max_length=500)
    trace_id = models.CharField("技术追踪 ID", max_length=80)
    trigger_source = models.CharField("触发来源", max_length=80)
    created_at_utc = models.DateTimeField("创建 UTC 时间", auto_now_add=True)
    updated_at_utc = models.DateTimeField("更新 UTC 时间", auto_now=True)
    completed_at_utc = models.DateTimeField("完成 UTC 时间", null=True, blank=True)
    downloaded_at_utc = models.DateTimeField("最近下载 UTC 时间", null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["status", "created_at_utc"]),
            models.Index(fields=["dataset_schema_version", "created_at_utc"]),
            models.Index(fields=["trace_id"]),
        ]

    def __str__(self) -> str:
        return f"ReviewDatasetExport<{self.export_key}:{self.status}>"
