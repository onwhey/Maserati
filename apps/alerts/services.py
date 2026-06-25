"""Notifications 模块：提供 AlertEvent 写入服务；写数据库，不访问外部服务，不发送 Hermes，不涉及交易执行。"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.foundation.redaction import sanitize_mapping

from .channels import DeliveryResponse, DisabledNotificationChannel, InMemorySuccessChannel, NotificationChannel
from .models import (
    AlertEvent,
    NotificationDeliveryAttempt,
    NotificationDeliveryStatus,
    NotificationRoute,
    NotificationSuppression,
    NotificationTemplate,
)


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
        event, created = AlertEvent.objects.get_or_create(
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
        if created:
            route_alert_event(event)
    return event


def route_alert_event(event: AlertEvent) -> None:
    if not event.delivery_enabled:
        _create_suppression(event, "delivery_disabled", "delivery_disabled_by_event")
        return
    if not getattr(settings, "NOTIFICATIONS_DELIVERY_ENABLED", False):
        _create_suppression(event, "delivery_disabled", "external_delivery_disabled")
        return
    route = _matching_route(event)
    if route is None:
        _create_suppression(event, "route_missing", "notification_route_not_found")
        return
    template = _matching_template(route)
    if template is None:
        _create_suppression(event, "template_missing", "notification_template_not_found")
        return
    key = _stable_hash({"alert_event_id": event.id, "route": route.route_code, "channel": route.channel, "attempt": 1})
    NotificationDeliveryAttempt.objects.get_or_create(
        delivery_attempt_key=key,
        defaults={
            "alert_event": event,
            "channel": route.channel,
            "route_code": route.route_code,
            "template_code": template.template_code,
            "template_version": template.template_version,
            "route_config_hash": _route_hash(route),
            "template_hash": _template_hash(template),
            "delivery_status": NotificationDeliveryStatus.PENDING,
            "attempt_sequence": 1,
            "provider_idempotency_key": key,
            "trace_id": event.trace_id,
            "sanitized_request_summary": _render_template(event, template),
        },
    )


def deliver_notification_attempt(
    *,
    delivery_attempt_id: int,
    channel: NotificationChannel | None = None,
) -> DeliveryResponse:
    now = timezone.now()
    with transaction.atomic():
        attempt = NotificationDeliveryAttempt.objects.select_for_update().get(id=delivery_attempt_id)
        if attempt.delivery_status == NotificationDeliveryStatus.SENT:
            return DeliveryResponse(success=True, provider_message_id=attempt.provider_message_id)
        if attempt.delivery_status not in {NotificationDeliveryStatus.PENDING, NotificationDeliveryStatus.FAILED}:
            return DeliveryResponse(success=False, error_code="attempt_not_deliverable", error_message="投递尝试当前状态不可投递")
        attempt.delivery_status = NotificationDeliveryStatus.SENDING
        attempt.claimed_at_utc = now
        attempt.started_at_utc = now
        attempt.save(update_fields=["delivery_status", "claimed_at_utc", "started_at_utc", "updated_at_utc"])

    payload = attempt.sanitized_request_summary or {}
    sender = channel or _default_channel(attempt.channel)
    response = sender.send(
        title=str(payload.get("title", "")),
        body=str(payload.get("body", "")),
        idempotency_key=attempt.provider_idempotency_key or attempt.delivery_attempt_key,
    )
    finished = timezone.now()
    attempt.delivery_status = NotificationDeliveryStatus.SENT if response.success else NotificationDeliveryStatus.FAILED
    attempt.request_sent = True
    attempt.provider_message_id = response.provider_message_id
    attempt.http_status = response.http_status
    attempt.error_code = response.error_code
    attempt.error_message = response.error_message[:500]
    attempt.retryable = response.retryable
    attempt.finished_at_utc = finished
    if attempt.started_at_utc:
        attempt.duration_ms = max(0, int((finished - attempt.started_at_utc).total_seconds() * 1000))
    attempt.sanitized_response_summary = {
        "success": response.success,
        "provider_message_id": response.provider_message_id,
        "error_code": response.error_code,
    }
    attempt.save()
    return response


def scan_pending_delivery_attempts(*, limit: int = 50) -> list[int]:
    return list(
        NotificationDeliveryAttempt.objects.filter(delivery_status=NotificationDeliveryStatus.PENDING)
        .order_by("created_at_utc")
        .values_list("id", flat=True)[:limit]
    )


def _matching_route(event: AlertEvent) -> NotificationRoute | None:
    candidates = NotificationRoute.objects.filter(enabled=True).order_by("-event_type", "-event_category", "-source_module", "id")
    for route in candidates:
        if route.source_module and route.source_module != event.source_module:
            continue
        if route.event_category and route.event_category != event.event_category:
            continue
        if route.event_type and route.event_type != event.event_type:
            continue
        if _severity_rank(event.severity) < _severity_rank(route.min_severity):
            continue
        return route
    return None


def _matching_template(route: NotificationRoute) -> NotificationTemplate | None:
    if not route.template_code:
        return None
    query = NotificationTemplate.objects.filter(
        enabled=True,
        template_code=route.template_code,
        channel=route.channel,
    )
    if route.template_version:
        query = query.filter(template_version=route.template_version)
    return query.order_by("-template_version", "-id").first()


def _create_suppression(event: AlertEvent, suppression_type: str, reason_code: str) -> None:
    NotificationSuppression.objects.get_or_create(
        alert_event=event,
        suppression_type=suppression_type,
        reason_code=reason_code,
        defaults={
            "dedupe_key": event.dedupe_key,
            "cooldown_key": event.cooldown_key,
            "trace_id": event.trace_id,
        },
    )


def _render_template(event: AlertEvent, template: NotificationTemplate) -> dict[str, str]:
    values = {
        "title": event.title_zh,
        "message": event.message_zh,
        "source_module": event.source_module,
        "event_type": event.event_type,
        "severity": event.severity,
        "reason_code": event.reason_code,
        "related_object_type": event.related_object_type,
        "related_object_id": event.related_object_id,
    }
    title = _format_template(template.title_template, values)[:300]
    body = _format_template(template.body_template, values)[: template.max_length]
    return {"title": title, "body": body}


def _format_template(template: str, values: dict[str, str]) -> str:
    result = template
    for key, value in values.items():
        result = result.replace("{" + key + "}", str(value))
    return result


def _default_channel(channel: str) -> NotificationChannel:
    if getattr(settings, "NOTIFICATIONS_FAKE_DELIVERY_SUCCESS", False):
        return InMemorySuccessChannel()
    return DisabledNotificationChannel()


def _severity_rank(value: str) -> int:
    return {"info": 10, "warning": 20, "high": 30, "critical": 40}.get(value, 0)


def _route_hash(route: NotificationRoute) -> str:
    return _stable_hash(
        {
            "route_code": route.route_code,
            "route_version": route.route_version,
            "source_module": route.source_module,
            "event_category": route.event_category,
            "event_type": route.event_type,
            "channel": route.channel,
            "template_code": route.template_code,
            "template_version": route.template_version,
            "cooldown_seconds": route.cooldown_seconds,
            "max_attempts": route.max_attempts,
        }
    )


def _template_hash(template: NotificationTemplate) -> str:
    return _stable_hash(
        {
            "template_code": template.template_code,
            "template_version": template.template_version,
            "channel": template.channel,
            "language": template.language,
            "title_template": template.title_template,
            "body_template": template.body_template,
        }
    )


def _stable_hash(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()
