"""Audit 模块：提供审计写入服务；写数据库，不访问外部服务，不涉及交易执行。"""

from __future__ import annotations

from typing import Any

from apps.foundation.redaction import sanitize_mapping

from .models import AuditRecord


def record_audit(
    *,
    operator_id: str,
    operation_type: str,
    target_object_type: str,
    target_object_id: str,
    before_state_summary: dict[str, Any],
    after_state_summary: dict[str, Any],
    reason: str,
    evidence: dict[str, Any],
    result: str,
    trace_id: str,
    trigger_source: str,
) -> AuditRecord:
    return AuditRecord.objects.create(
        operator_id=operator_id,
        operation_type=operation_type,
        target_object_type=target_object_type,
        target_object_id=target_object_id,
        before_state_summary=sanitize_mapping(before_state_summary),
        after_state_summary=sanitize_mapping(after_state_summary),
        reason=reason,
        evidence=sanitize_mapping(evidence),
        result=result,
        trace_id=trace_id,
        trigger_source=trigger_source,
    )

