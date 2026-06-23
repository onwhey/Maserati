import pytest

from apps.alerts.models import AlertEvent, AlertSeverity
from apps.alerts.services import record_alert_event
from apps.audit.models import AuditRecord
from apps.audit.services import record_audit
from apps.runtime_config.services import (
    get_effective_real_trading_permission,
    get_or_create_runtime_trading_config,
    set_runtime_real_trading_permission,
)


@pytest.mark.django_db
def test_record_alert_event_is_idempotent() -> None:
    first = record_alert_event(
        event_key="test:event:1",
        source_module="foundation_test",
        event_type="foundation_test_event",
        event_category="system_security",
        severity=AlertSeverity.INFO,
        title_zh="测试事件",
        message_zh="测试事件摘要",
        trace_id="trace_test",
        trigger_source="test",
        payload_summary={"secret": "hidden"},
    )
    second = record_alert_event(
        event_key="test:event:1",
        source_module="foundation_test",
        event_type="foundation_test_event",
        event_category="system_security",
        severity=AlertSeverity.INFO,
        title_zh="测试事件",
        message_zh="测试事件摘要",
        trace_id="trace_test",
        trigger_source="test",
    )
    assert first.id == second.id
    assert AlertEvent.objects.count() == 1
    assert first.payload_summary["secret"] == "[REDACTED]"


@pytest.mark.django_db
def test_record_audit_sanitizes_evidence() -> None:
    audit = record_audit(
        operator_id="operator-1",
        operation_type="test_operation",
        target_object_type="TestObject",
        target_object_id="1",
        before_state_summary={"enabled": False},
        after_state_summary={"enabled": True},
        reason="测试",
        evidence={"token": "secret-token"},
        result="succeeded",
        trace_id="trace_test",
        trigger_source="test",
    )
    assert audit.evidence["token"] == "[REDACTED]"
    assert AuditRecord.objects.count() == 1


@pytest.mark.django_db
def test_effective_real_trading_permission_fail_closed_by_default() -> None:
    config = get_or_create_runtime_trading_config()
    assert config.runtime_real_trading_permission is False
    permission = get_effective_real_trading_permission()
    assert permission.effective_allowed is False
    assert permission.fail_closed is False


@pytest.mark.django_db
def test_runtime_permission_change_writes_audit_and_alert() -> None:
    set_runtime_real_trading_permission(
        enabled=True,
        operator_id="operator-1",
        reason="阶段 0 测试",
        evidence={"secret": "must-not-leak"},
        trace_id="trace_test",
        trigger_source="test",
    )
    assert AuditRecord.objects.count() == 1
    assert AlertEvent.objects.count() == 1
    permission = get_effective_real_trading_permission()
    assert permission.runtime_allowed is True
    assert permission.effective_allowed is False

