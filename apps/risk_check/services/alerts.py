"""RiskCheck 模块：记录风控审批告警事实；写 MySQL；不访问外部服务；不发送 Hermes；不涉及交易执行。"""

from __future__ import annotations

import logging
from typing import Any

from django.db import DatabaseError

from apps.alerts.models import AlertSeverity
from apps.alerts.services import record_alert_event
from apps.foundation.idempotency import build_idempotency_key


logger = logging.getLogger(__name__)


def record_risk_check_alert(
    *,
    event_type: str,
    business_request_key: str,
    trace_id: str,
    trigger_source: str,
    status: str,
    reason_code: str,
    message: str,
    risk_check_result_id: int | None = None,
    payload_summary: dict[str, Any] | None = None,
    severity: str | None = None,
) -> int | None:
    selected_severity = severity or _severity(status)
    try:
        alert = record_alert_event(
            event_key=build_idempotency_key(
                "risk_check",
                event_type,
                business_request_key,
                risk_check_result_id or "none",
                reason_code,
            ),
            source_module="RiskCheck",
            event_type=event_type,
            event_category="risk_check",
            severity=selected_severity,
            title_zh=_title(event_type, status),
            message_zh=message,
            trace_id=trace_id,
            trigger_source=trigger_source,
            related_object_type="RiskCheckResult" if risk_check_result_id else "",
            related_object_id=str(risk_check_result_id or ""),
            business_status=status,
            reason_code=reason_code,
            payload_summary={"business_request_key": business_request_key, **(payload_summary or {})},
            delivery_enabled=False,
        )
        return alert.id
    except DatabaseError:
        logger.exception(
            "RiskCheck AlertEvent 写入失败 event_type=%s business_request_key=%s",
            event_type,
            business_request_key,
        )
        return None


def _severity(status: str) -> str:
    if status == "FAILED":
        return AlertSeverity.HIGH
    if status in {"DENY", "BLOCKED"}:
        return AlertSeverity.WARNING
    return AlertSeverity.INFO


def _title(event_type: str, status: str) -> str:
    labels = {
        "risk_check_allow": "RiskCheck 审批通过",
        "risk_check_deny": "RiskCheck 明确拒绝",
        "risk_check_blocked": "RiskCheck 已阻断",
        "risk_check_failed": "RiskCheck 失败",
        "fallback_reduce_only_selected": "RiskCheck 选择只减仓后备意图",
        "approved_order_intent_generated": "风控通过订单意图已生成",
    }
    return labels.get(event_type, f"RiskCheck {status}")
