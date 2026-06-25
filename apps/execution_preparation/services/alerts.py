"""ExecutionPreparation 模块：记录执行前检查 AlertEvent；写 MySQL；不访问外部服务；不发送 Hermes；不涉及交易执行。"""

from __future__ import annotations

import logging
from typing import Any

from django.db import DatabaseError

from apps.alerts.models import AlertSeverity
from apps.alerts.services import record_alert_event
from apps.foundation.idempotency import build_idempotency_key


logger = logging.getLogger(__name__)


def record_execution_preparation_alert(
    *,
    event_type: str,
    business_request_key: str,
    trace_id: str,
    trigger_source: str,
    status: str,
    reason_code: str,
    message: str,
    execution_preparation_result_id: int | None = None,
    prepared_order_intent_id: int | None = None,
    payload_summary: dict[str, Any] | None = None,
    severity: str | None = None,
) -> int | None:
    try:
        alert = record_alert_event(
            event_key=build_idempotency_key(
                "execution_preparation",
                event_type,
                business_request_key,
                execution_preparation_result_id or "none",
                prepared_order_intent_id or "none",
                reason_code,
            ),
            source_module="ExecutionPreparation",
            event_type=event_type,
            event_category="execution_preparation",
            severity=severity or _severity(status),
            title_zh=_title(event_type, status),
            message_zh=message,
            trace_id=trace_id,
            trigger_source=trigger_source,
            related_object_type="ExecutionPreparationResult" if execution_preparation_result_id else "",
            related_object_id=str(execution_preparation_result_id or ""),
            business_status=status,
            reason_code=reason_code,
            payload_summary={
                "business_request_key": business_request_key,
                "prepared_order_intent_id": prepared_order_intent_id,
                **(payload_summary or {}),
            },
            delivery_enabled=False,
        )
        return alert.id
    except DatabaseError:
        logger.exception(
            "ExecutionPreparation AlertEvent 写入失败 event_type=%s business_request_key=%s",
            event_type,
            business_request_key,
        )
        return None


def _severity(status: str) -> str:
    if status == "FAILED":
        return AlertSeverity.HIGH
    if status in {"BLOCKED", "EXPIRED"}:
        return AlertSeverity.WARNING
    return AlertSeverity.INFO


def _title(event_type: str, status: str) -> str:
    labels = {
        "execution_preparation_prepared": "执行前检查通过",
        "execution_preparation_blocked": "执行前检查阻断",
        "execution_preparation_failed": "执行前检查失败",
        "execution_preparation_expired": "待提交请求已过期",
        "execution_preparation_idempotent_replay": "执行前检查幂等重放",
        "execution_preparation_live_price_unavailable": "执行前盘口不可用",
        "execution_preparation_price_deviation_exceeded": "执行前价格偏差超限",
        "execution_preparation_reduce_only_invalid": "执行前 reduce-only 复核失败",
        "execution_preparation_exchange_rule_violation": "执行前交易规则复核失败",
    }
    return labels.get(event_type, f"ExecutionPreparation {status}")
