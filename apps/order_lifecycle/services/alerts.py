"""OrderLifecycle 模块：记录订单周期收尾撤单 AlertEvent；写 MySQL；不访问外部服务；不发送 Hermes；不调用大模型；不提交订单。"""

from __future__ import annotations

import logging
from typing import Any

from django.db import DatabaseError

from apps.alerts.models import AlertSeverity
from apps.alerts.services import record_alert_event
from apps.foundation.idempotency import build_idempotency_key

from ..models import OrderCancelAttempt


logger = logging.getLogger(__name__)


def record_order_cancel_alert(
    attempt: OrderCancelAttempt,
    event_type: str,
    *,
    severity: str | None = None,
    payload_summary: dict[str, Any] | None = None,
) -> int | None:
    selected_severity = severity or _severity(attempt, event_type)
    try:
        alert = record_alert_event(
            event_key=build_idempotency_key(
                "order_cycle_closeout",
                event_type,
                attempt.order_submission_attempt_id,
                attempt.closeout_time_utc.isoformat(),
                attempt.cancel_reason_code,
                attempt.cancel_status,
            ),
            source_module="OrderCycleCloseout",
            event_type=event_type,
            event_category="order_cancel",
            severity=selected_severity,
            title_zh=_title(event_type),
            message_zh=attempt.reason_message or attempt.cancel_reason_code,
            trace_id=attempt.trace_id,
            trigger_source=attempt.trigger_source,
            related_object_type="OrderCancelAttempt",
            related_object_id=str(attempt.id),
            business_status=attempt.cancel_status,
            reason_code=attempt.reason_code or attempt.cancel_reason_code,
            reason_message=attempt.reason_message,
            payload_summary={
                "business_request_key": attempt.business_request_key,
                "order_submission_attempt_id": attempt.order_submission_attempt_id,
                "prepared_order_intent_id": attempt.prepared_order_intent_id,
                "order_plan_id": attempt.order_plan_id,
                "active_lock_id": attempt.active_lock_id,
                "market_type": attempt.market_type,
                "account_domain": attempt.account_domain,
                "symbol": attempt.symbol,
                "client_order_id": attempt.client_order_id,
                "exchange_order_id": attempt.exchange_order_id,
                "cancel_reason_code": attempt.cancel_reason_code,
                "reason_code": attempt.reason_code,
                "request_sent": attempt.request_sent,
                "response_received": attempt.response_received,
                **(payload_summary or {}),
            },
            delivery_enabled=False,
        )
        return alert.id
    except DatabaseError:
        logger.exception("OrderCycleCloseout AlertEvent 写入失败 attempt_id=%s event_type=%s", attempt.id, event_type)
        return None


def _severity(attempt: OrderCancelAttempt, event_type: str) -> str:
    if event_type == "order_cancel_gateway_contract_violation":
        return AlertSeverity.CRITICAL
    if attempt.cancel_status in {"unknown", "not_found"}:
        return AlertSeverity.HIGH
    if attempt.cancel_status in {"blocked_before_cancel", "failed_before_cancel"}:
        return AlertSeverity.WARNING
    return AlertSeverity.INFO


def _title(event_type: str) -> str:
    labels = {
        "order_cancel_accepted": "限价单周期收尾撤单已被交易所接受",
        "order_cancel_not_found": "限价单周期收尾撤单未找到订单",
        "order_cancel_unknown": "限价单周期收尾撤单结果未知",
        "order_cancel_blocked_before_cancel": "限价单周期收尾撤单前被阻断",
        "order_cancel_failed_before_cancel": "限价单周期收尾撤单前失败",
        "order_cancel_idempotent_replay": "限价单周期收尾撤单幂等重放",
        "order_cancel_gateway_contract_violation": "限价单周期收尾撤单 Gateway 合同异常",
    }
    return labels.get(event_type, "限价单周期收尾撤单事件")
