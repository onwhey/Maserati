"""OrderStatusSync 模块：记录订单状态查询 AlertEvent；写 MySQL；不访问外部服务；不发送 Hermes；不调用大模型；不提交订单。"""

from __future__ import annotations

import logging
from typing import Any

from django.db import DatabaseError

from apps.alerts.models import AlertSeverity
from apps.alerts.services import record_alert_event
from apps.foundation.idempotency import build_idempotency_key

from ..models import OrderStatusSyncRecord


logger = logging.getLogger(__name__)


def record_order_status_sync_alert(record: OrderStatusSyncRecord, event_type: str, *, severity: str | None = None) -> int | None:
    selected_severity = severity or _severity(record, event_type)
    try:
        alert = record_alert_event(
            event_key=build_idempotency_key(
                "order_status_sync",
                event_type,
                record.order_submission_attempt_id,
                record.poll_mode,
                record.poll_sequence,
                record.reason_code,
            ),
            source_module="OrderStatusSync",
            event_type=event_type,
            event_category="order_status",
            severity=selected_severity,
            title_zh=_title(event_type),
            message_zh=record.reason_message or record.reason_code,
            trace_id=record.trace_id,
            trigger_source=record.trigger_source,
            related_object_type="OrderStatusSyncRecord",
            related_object_id=str(record.id),
            business_status=record.query_outcome,
            reason_code=record.reason_code,
            reason_message=record.reason_message,
            payload_summary=_payload(record),
            delivery_enabled=False,
        )
        return alert.id
    except DatabaseError:
        logger.exception("OrderStatusSync AlertEvent 写入失败 record_id=%s", record.id)
        return None


def record_order_status_timeout_alert(
    *,
    order_submission_attempt_id: int,
    business_request_key: str,
    poll_mode: str,
    poll_sequence: int,
    polling_deadline_utc: str,
    trace_id: str,
    trigger_source: str,
) -> int | None:
    try:
        alert = record_alert_event(
            event_key=build_idempotency_key(
                "order_status_sync",
                "order_status_polling_timeout",
                order_submission_attempt_id,
                poll_mode,
                poll_sequence,
            ),
            source_module="OrderStatusSync",
            event_type="order_status_polling_timeout",
            event_category="order_status",
            severity=AlertSeverity.HIGH,
            title_zh="订单状态立即轮询超时",
            message_zh="订单状态立即轮询窗口已结束，未确认明确终态。",
            trace_id=trace_id,
            trigger_source=trigger_source,
            related_object_type="OrderSubmissionAttempt",
            related_object_id=str(order_submission_attempt_id),
            business_status="polling_timeout",
            reason_code="polling_timeout",
            reason_message="订单状态立即轮询窗口已结束，未确认明确终态。",
            payload_summary={
                "business_request_key": business_request_key,
                "poll_mode": poll_mode,
                "poll_sequence": poll_sequence,
                "polling_deadline_utc": polling_deadline_utc,
            },
            delivery_enabled=False,
        )
        return alert.id
    except DatabaseError:
        logger.exception(
            "OrderStatusSync timeout AlertEvent 写入失败 attempt_id=%s poll_sequence=%s",
            order_submission_attempt_id,
            poll_sequence,
        )
        return None


def _severity(record: OrderStatusSyncRecord, event_type: str) -> str:
    if event_type in {"order_status_sync_unknown_status", "order_status_sync_identity_mismatch"}:
        return AlertSeverity.CRITICAL
    if record.query_outcome in {"unknown", "not_found", "failed_before_query"}:
        return AlertSeverity.HIGH
    if record.query_outcome == "blocked_before_query":
        return AlertSeverity.WARNING
    return AlertSeverity.INFO


def _title(event_type: str) -> str:
    labels = {
        "order_status_sync_found": "订单状态查询已找到交易所订单",
        "order_status_sync_terminal": "订单状态查询确认交易所终态",
        "order_status_sync_not_found": "订单状态查询明确未找到订单",
        "order_status_sync_unknown": "订单状态查询结果未知",
        "order_status_sync_blocked_before_query": "订单状态查询前被阻断",
        "order_status_sync_failed_before_query": "订单状态查询前失败",
        "order_status_sync_unknown_status": "订单状态查询遇到未知交易所状态",
        "order_status_sync_identity_mismatch": "订单状态查询返回身份不一致",
        "order_status_sync_idempotent_replay": "订单状态查询幂等重放",
    }
    return labels.get(event_type, "订单状态查询事件")


def _payload(record: OrderStatusSyncRecord) -> dict[str, Any]:
    return {
        "order_submission_attempt_id": record.order_submission_attempt_id,
        "prepared_order_intent_id": record.prepared_order_intent_id,
        "order_plan_id": record.order_plan_id,
        "active_lock_id": record.active_lock_id,
        "market_type": record.market_type,
        "account_domain": record.account_domain,
        "symbol": record.symbol,
        "poll_mode": record.poll_mode,
        "poll_sequence": record.poll_sequence,
        "query_identifier_type": record.query_identifier_type,
        "client_order_id": record.client_order_id,
        "exchange_order_id_requested": record.exchange_order_id_requested,
        "exchange_order_id_returned": record.exchange_order_id_returned,
        "exchange_status": record.exchange_status,
        "is_terminal_status": record.is_terminal_status,
        "submission_resolution_status": record.submission_resolution_status,
    }
