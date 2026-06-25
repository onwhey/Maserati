"""OrderPlan 模块：记录订单计划与 ActiveLock 告警事实；写 MySQL；不访问外部服务；不发送 Hermes；不涉及交易执行。"""

from __future__ import annotations

import logging
from typing import Any

from django.db import DatabaseError

from apps.alerts.models import AlertSeverity
from apps.alerts.services import record_alert_event
from apps.foundation.idempotency import build_idempotency_key


logger = logging.getLogger(__name__)


def record_order_plan_alert(
    *,
    event_type: str,
    business_request_key: str,
    trace_id: str,
    trigger_source: str,
    status: str,
    reason_code: str,
    message: str,
    order_plan_id: int | None = None,
    payload_summary: dict[str, Any] | None = None,
    severity: str | None = None,
) -> None:
    selected_severity = severity or _severity(status)
    try:
        record_alert_event(
            event_key=build_idempotency_key(
                "order_plan",
                event_type,
                business_request_key,
                order_plan_id or "none",
                reason_code,
            ),
            source_module="OrderPlan",
            event_type=event_type,
            event_category="trading_plan",
            severity=selected_severity,
            title_zh=_title(event_type, status),
            message_zh=message,
            trace_id=trace_id,
            trigger_source=trigger_source,
            related_object_type="OrderPlan" if order_plan_id else "",
            related_object_id=str(order_plan_id or ""),
            business_status=status,
            reason_code=reason_code,
            payload_summary={"business_request_key": business_request_key, **(payload_summary or {})},
            delivery_enabled=False,
        )
    except DatabaseError:
        logger.exception(
            "OrderPlan AlertEvent 写入失败 event_type=%s business_request_key=%s",
            event_type,
            business_request_key,
        )


def _severity(status: str) -> str:
    if status == "failed":
        return AlertSeverity.HIGH
    if status == "blocked":
        return AlertSeverity.WARNING
    return AlertSeverity.INFO


def _title(event_type: str, status: str) -> str:
    labels = {
        "order_plan_no_order_required": "OrderPlan 无需调仓",
        "order_plan_blocked": "OrderPlan 已阻断",
        "order_plan_failed": "OrderPlan 失败",
        "candidate_order_intent_generated": "候选订单意图已生成",
        "candidate_order_intent_skipped": "候选订单意图无需生成",
        "candidate_order_intent_blocked": "候选订单意图生成已阻断",
        "active_lock_acquired": "订单链路保护锁已取得",
        "active_lock_conflict": "订单链路保护锁冲突",
        "real_trading_permission_closed": "真实交易权限关闭",
        "real_trading_permission_unreadable": "真实交易权限不可读取",
        "active_market_identity_mismatch": "交易市场身份不一致",
    }
    return labels.get(event_type, f"OrderPlan {status}")
