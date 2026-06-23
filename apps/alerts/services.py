"""Notifications 模块：提供 AlertEvent 写入服务；写数据库，不访问外部服务，不发送 Hermes，不涉及交易执行。"""

from __future__ import annotations

from typing import Any

from django.db import transaction

from apps.foundation.redaction import sanitize_mapping

from .models import AlertEvent


def record_alert_event(
    *,
    event_key: str,
    source_module: str,
    event_type: str,
    event_category: str,
    severity: str,
    title_zh: str,
    message_zh: str,
    trace_id: str,
    trigger_source: str,
    related_object_type: str = "",
    related_object_id: str = "",
    related_object_label: str = "",
    business_status: str = "",
    reason_code: str = "",
    reason_message: str = "",
    payload_summary: dict[str, Any] | None = None,
    evidence_refs: list[Any] | None = None,
    is_dry_run: bool = False,
    delivery_enabled: bool = False,
) -> AlertEvent:
    sanitized_payload = sanitize_mapping(payload_summary or {})
    with transaction.atomic():
        event, _created = AlertEvent.objects.get_or_create(
            event_key=event_key,
            defaults={
                "source_module": source_module,
                "event_type": event_type,
                "event_category": event_category,
                "severity": severity,
                "title_zh": title_zh,
                "message_zh": message_zh,
                "trace_id": trace_id,
                "trigger_source": trigger_source,
                "related_object_type": related_object_type,
                "related_object_id": related_object_id,
                "related_object_label": related_object_label,
                "business_status": business_status,
                "reason_code": reason_code,
                "reason_message": reason_message,
                "payload_summary": sanitized_payload,
                "evidence_refs": evidence_refs or [],
                "is_dry_run": is_dry_run,
                "delivery_enabled": delivery_enabled,
            },
        )
    return event
