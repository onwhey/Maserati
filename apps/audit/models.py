"""Audit 模块：定义人工操作和高风险变更审计；读写数据库，不访问外部服务，不涉及交易执行。"""

from __future__ import annotations

from django.db import models


class AuditRecord(models.Model):
    operator_id = models.CharField("操作者 ID", max_length=120)
    operation_type = models.CharField("操作类型", max_length=120)
    target_object_type = models.CharField("目标对象类型", max_length=120)
    target_object_id = models.CharField("目标对象 ID", max_length=120, blank=True)
    before_state_summary = models.JSONField("修改前状态摘要", default=dict, blank=True)
    after_state_summary = models.JSONField("修改后状态摘要", default=dict, blank=True)
    reason = models.CharField("操作原因", max_length=500)
    evidence = models.JSONField("操作证据", default=dict, blank=True)
    result = models.CharField("操作结果", max_length=80)
    trace_id = models.CharField("技术追踪 ID", max_length=80)
    trigger_source = models.CharField("触发来源", max_length=80)
    created_at_utc = models.DateTimeField("创建 UTC 时间", auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["operator_id", "created_at_utc"]),
            models.Index(fields=["target_object_type", "target_object_id"]),
            models.Index(fields=["trace_id"]),
        ]
        verbose_name = "审计记录"
        verbose_name_plural = "审计记录"

    def __str__(self) -> str:
        return f"{self.operation_type}:{self.target_object_type}:{self.target_object_id}"

