"""FillSync 模块：记录成交同步 AlertEvent；写 MySQL；不访问外部服务；不发送 Hermes；不调用大模型；不提交订单。"""

from __future__ import annotations

import logging
from typing import Any

from django.db import DatabaseError

from apps.alerts.models import AlertSeverity
from apps.alerts.services import record_alert_event
from apps.foundation.idempotency import build_idempotency_key

from ..models import FillSyncResult


logger = logging.getLogger(__name__)


def record_fill_sync_alert(
    result: FillSyncResult,
    event_type: str,
    *,
    severity: str | None = None,
    payload_summary: dict[str, Any] | None = None,
) -> int | None:
    selected_severity = severity or _severity(result, event_type)
    try:
        alert = record_alert_event(
            event_key=build_idempotency_key(
                "fill_sync",
                event_type,
                result.order_submission_attempt_id,
                result.terminal_order_status_sync_record_id,
                result.sync_sequence,
                result.reason_code,
            ),
            source_module="FillSync",
            event_type=event_type,
            event_category="fill_sync",
            severity=selected_severity,
            title_zh=_title(event_type),
            message_zh=result.reason_message or result.reason_code,
            trace_id=result.trace_id,
            trigger_source=result.trigger_source,
            related_object_type="FillSyncResult",
            related_object_id=str(result.id),
            business_status=result.status,
            reason_code=result.reason_code,
            reason_message=result.reason_message,
            payload_summary={
                "business_request_key": result.business_request_key,
                "order_submission_attempt_id": result.order_submission_attempt_id,
                "terminal_order_status_sync_record_id": result.terminal_order_status_sync_record_id,
                "active_lock_id": result.active_lock_id,
                "market_type": result.market_type,
                "account_domain": result.account_domain,
                "symbol": result.symbol,
                "exchange_order_id": result.exchange_order_id,
                "terminal_exchange_status": result.terminal_exchange_status,
                "returned_fill_count": result.returned_fill_count,
                "inserted_fill_count": result.inserted_fill_count,
                "duplicate_fill_count": result.duplicate_fill_count,
                "conflict_fill_count": result.conflict_fill_count,
                **(payload_summary or {}),
            },
            delivery_enabled=False,
        )
        return alert.id
    except DatabaseError:
        logger.exception("FillSync AlertEvent 写入失败 result_id=%s event_type=%s", result.id, event_type)
        return None


def _severity(result: FillSyncResult, event_type: str) -> str:
    if event_type in {"fill_sync_conflict", "fill_sync_identity_mismatch"}:
        return AlertSeverity.CRITICAL
    if result.status in {"unknown", "failed_before_query", "incomplete"}:
        return AlertSeverity.HIGH
    if result.status == "blocked_before_query":
        return AlertSeverity.WARNING
    return AlertSeverity.INFO


def _title(event_type: str) -> str:
    labels = {
        "fill_sync_synced": "成交同步完成",
        "fill_sync_synced_empty": "成交同步确认无成交",
        "fill_sync_incomplete": "成交同步证据不完整",
        "fill_sync_unknown": "成交同步结果未知",
        "fill_sync_failed_before_query": "成交查询前失败",
        "fill_sync_blocked_before_query": "成交查询前阻断",
        "fill_sync_conflict": "成交同步发现成交冲突",
        "fill_sync_identity_mismatch": "成交同步发现身份不一致",
        "fill_sync_idempotent_replay": "成交同步幂等重放",
    }
    return labels.get(event_type, "成交同步事件")
