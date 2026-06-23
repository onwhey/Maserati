"""MarketData 模块：行情链路 AlertEvent 写入；写数据库，不访问外部服务，不发送 Hermes，不涉及交易执行。"""

from __future__ import annotations

from typing import Any

from apps.alerts.models import AlertSeverity
from apps.alerts.services import record_alert_event
from apps.foundation.idempotency import build_idempotency_key


def record_market_data_alert(
    *,
    source_module: str,
    event_type: str,
    severity: str,
    title_zh: str,
    message_zh: str,
    trace_id: str,
    trigger_source: str,
    business_status: str,
    reason_code: str,
    related_object_type: str = "",
    related_object_id: str = "",
    payload_summary: dict[str, Any] | None = None,
) -> None:
    event_key = build_idempotency_key(
        "market_data_alert",
        source_module,
        event_type,
        related_object_type,
        related_object_id,
        business_status,
        reason_code,
        trace_id,
    )
    record_alert_event(
        event_key=event_key,
        source_module=source_module,
        event_type=event_type,
        event_category="market_data",
        severity=severity or AlertSeverity.WARNING,
        title_zh=title_zh,
        message_zh=message_zh,
        trace_id=trace_id,
        trigger_source=trigger_source,
        related_object_type=related_object_type,
        related_object_id=related_object_id,
        business_status=business_status,
        reason_code=reason_code,
        payload_summary=payload_summary or {},
    )

