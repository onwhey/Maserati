"""BinanceAccountSync 模块：写入账户同步相关 AlertEvent；写数据库；不访问 Redis；不访问外部服务；不发送 Hermes；不调用大模型；不涉及交易执行；不允许真实交易。"""

from __future__ import annotations

from typing import Any

from apps.alerts.models import AlertSeverity
from apps.alerts.services import record_alert_event
from apps.foundation.idempotency import build_idempotency_key


def record_account_sync_alert(
    *,
    event_type: str,
    severity: str,
    title_zh: str,
    message_zh: str,
    trace_id: str,
    trigger_source: str,
    business_status: str,
    reason_code: str,
    related_object_id: str = "",
    payload_summary: dict[str, Any] | None = None,
) -> None:
    record_alert_event(
        event_key=build_idempotency_key("binance_account_sync", event_type, related_object_id, reason_code, trace_id),
        source_module="BinanceAccountSync",
        event_type=event_type,
        event_category="account_fact_sync",
        severity=severity,
        title_zh=title_zh,
        message_zh=message_zh,
        trace_id=trace_id,
        trigger_source=trigger_source,
        related_object_type="BinanceSyncRun" if related_object_id else "",
        related_object_id=related_object_id,
        business_status=business_status,
        reason_code=reason_code,
        payload_summary=payload_summary or {},
        delivery_enabled=False,
    )


def failed_severity_for_purpose(sync_purpose: str) -> str:
    if sync_purpose == "trade_preparation":
        return AlertSeverity.HIGH
    return AlertSeverity.WARNING

