"""Execution 模块：记录订单提交告警事实；写 MySQL；不访问外部服务；不发送 Hermes；不调用大模型；涉及交易执行审计。"""

from __future__ import annotations

import logging
from typing import Any

from django.db import DatabaseError

from apps.alerts.models import AlertSeverity
from apps.alerts.services import record_alert_event
from apps.foundation.idempotency import build_idempotency_key


logger = logging.getLogger(__name__)


def record_execution_alert(
    *,
    event_type: str,
    business_request_key: str,
    trace_id: str,
    trigger_source: str,
    status: str,
    reason_code: str,
    message: str,
    order_submission_attempt_id: int | None = None,
    prepared_order_intent_id: int | None = None,
    payload_summary: dict[str, Any] | None = None,
    severity: str | None = None,
) -> int | None:
    selected_severity = severity or _severity(event_type, status)
    try:
        alert = record_alert_event(
            event_key=build_idempotency_key(
                "execution",
                event_type,
                business_request_key,
                order_submission_attempt_id or prepared_order_intent_id or "none",
                reason_code,
            ),
            source_module="Execution",
            event_type=event_type,
            event_category="order_submission",
            severity=selected_severity,
            title_zh=_title(event_type, status),
            message_zh=message,
            trace_id=trace_id,
            trigger_source=trigger_source,
            related_object_type="OrderSubmissionAttempt" if order_submission_attempt_id else "PreparedOrderIntent",
            related_object_id=str(order_submission_attempt_id or prepared_order_intent_id or ""),
            business_status=status,
            reason_code=reason_code,
            reason_message=message,
            payload_summary={"business_request_key": business_request_key, **(payload_summary or {})},
            delivery_enabled=False,
        )
        return alert.id
    except DatabaseError:
        logger.exception(
            "Execution AlertEvent 写入失败 event_type=%s business_request_key=%s",
            event_type,
            business_request_key,
        )
        return None


def _severity(event_type: str, status: str) -> str:
    if event_type == "order_submission_gateway_contract_violation":
        return AlertSeverity.CRITICAL
    if status == "unknown":
        return AlertSeverity.HIGH
    if status in {"rejected", "blocked_before_submit", "failed_before_submit"}:
        return AlertSeverity.WARNING
    return AlertSeverity.INFO


def _title(event_type: str, status: str) -> str:
    labels = {
        "order_submission_accepted": "订单提交请求已被交易所接受",
        "order_submission_rejected": "订单提交请求被交易所明确拒绝",
        "order_submission_unknown": "订单提交结果未知",
        "order_submission_blocked_before_submit": "订单提交前已阻断",
        "order_submission_failed_before_submit": "订单提交前失败",
        "order_submission_idempotent_replay": "订单提交幂等重放",
        "order_submission_gateway_contract_violation": "订单提交 Gateway 合同异常",
    }
    return labels.get(event_type, f"Execution {status}")

