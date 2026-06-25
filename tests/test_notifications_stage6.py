from __future__ import annotations

import pytest
from django.test import override_settings

from apps.alerts.models import (
    AlertEvent,
    NotificationDeliveryAttempt,
    NotificationDeliveryStatus,
    NotificationRoute,
    NotificationSuppression,
    NotificationTemplate,
)
from apps.alerts.services import deliver_notification_attempt, record_alert_event


@pytest.mark.django_db
def test_alert_event_without_delivery_creates_suppression() -> None:
    event = record_alert_event(
        event_key="stage6-alert-suppressed",
        source_module="order_plan",
        event_type="order_plan_blocked",
        event_category="trading",
        severity="warning",
        title_zh="订单计划阻断",
        message_zh="测试事件",
        trace_id="trace-alert-1",
        trigger_source="test",
        delivery_enabled=False,
    )

    assert AlertEvent.objects.get(id=event.id)
    assert NotificationSuppression.objects.filter(alert_event=event, reason_code="delivery_disabled_by_event").exists()
    assert NotificationDeliveryAttempt.objects.filter(alert_event=event).count() == 0


@pytest.mark.django_db
@override_settings(NOTIFICATIONS_DELIVERY_ENABLED=True)
def test_alert_event_with_route_creates_pending_attempt() -> None:
    NotificationTemplate.objects.create(
        template_code="default_trading",
        template_version="1.0",
        channel="test",
        title_template="{title}",
        body_template="{message}",
    )
    NotificationRoute.objects.create(
        route_code="trading-warning",
        route_version="1.0",
        event_category="trading",
        min_severity="warning",
        channel="test",
        template_code="default_trading",
        template_version="1.0",
        enabled=True,
    )

    event = record_alert_event(
        event_key="stage6-alert-delivery",
        source_module="risk_check",
        event_type="risk_check_blocked",
        event_category="trading",
        severity="warning",
        title_zh="风控阻断",
        message_zh="测试投递事件",
        trace_id="trace-alert-2",
        trigger_source="test",
        delivery_enabled=True,
    )

    attempt = NotificationDeliveryAttempt.objects.get(alert_event=event)
    assert attempt.delivery_status == NotificationDeliveryStatus.PENDING
    assert attempt.sanitized_request_summary["title"] == "风控阻断"


@pytest.mark.django_db
@override_settings(NOTIFICATIONS_DELIVERY_ENABLED=True)
def test_deliver_notification_attempt_marks_sent_idempotently() -> None:
    NotificationTemplate.objects.create(
        template_code="default_runtime",
        template_version="1.0",
        channel="test",
        title_template="{title}",
        body_template="{message}",
    )
    NotificationRoute.objects.create(
        route_code="runtime-warning",
        route_version="1.0",
        event_category="runtime_guard",
        min_severity="info",
        channel="test",
        template_code="default_runtime",
        template_version="1.0",
        enabled=True,
    )
    event = record_alert_event(
        event_key="stage6-alert-send",
        source_module="runtime_guard",
        event_type="orchestration_run_stale",
        event_category="runtime_guard",
        severity="high",
        title_zh="巡检问题",
        message_zh="测试发送",
        trace_id="trace-alert-3",
        trigger_source="test",
        delivery_enabled=True,
    )
    attempt = NotificationDeliveryAttempt.objects.get(alert_event=event)

    first = deliver_notification_attempt(delivery_attempt_id=attempt.id)
    second = deliver_notification_attempt(delivery_attempt_id=attempt.id)
    attempt.refresh_from_db()

    assert first.success is True
    assert second.success is True
    assert attempt.delivery_status == NotificationDeliveryStatus.SENT
    assert NotificationDeliveryAttempt.objects.filter(alert_event=event).count() == 1

