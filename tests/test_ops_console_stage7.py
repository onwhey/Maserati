from __future__ import annotations

from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import Client, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.alerts.models import AlertEvent
from apps.alerts.services import record_alert_event
from apps.audit.models import AuditRecord
from apps.binance_account_sync.models import (
    BinanceAccountSnapshot,
    BinanceBalanceSnapshot,
    BinancePositionMode,
    BinancePositionSnapshot,
    BinanceSymbolRuleSnapshot,
    BinanceSyncPurpose,
    BinanceSyncRun,
    BinanceSyncStatus,
)
from apps.execution.models import OrderSubmissionAttempt
from apps.orchestration.models import (
    OrchestrationBusinessObjectLink,
    OrchestrationObjectRole,
    OrchestrationRun,
    OrchestrationRunStatus,
    OrchestrationStepRun,
    OrchestrationStepRunStatus,
    OrchestrationTriggerMode,
)
from apps.runtime_config.models import RuntimeTradingConfig
from apps.runtime_guard.models import RuntimeGuardIssue, RuntimeGuardIssueSeverity, RuntimeGuardIssueStatus
from tests.test_execution_order_submission_stage5 import _prepared, _submit
from apps.binance_gateway.order_submission import FakeBinanceOrderSubmissionGateway
from apps.binance_gateway.types import MARKET_TYPE_USDS_M


pytestmark = pytest.mark.django_db


def _client_with_group(group_name: str) -> Client:
    user_model = get_user_model()
    user = user_model.objects.create_user(username=f"user-{group_name}", password="pass")
    group, _ = Group.objects.get_or_create(name=group_name)
    user.groups.add(group)
    client = Client()
    assert client.login(username=f"user-{group_name}", password="pass")
    return client


def test_ops_console_api_requires_login_and_backend_permission() -> None:
    anonymous = Client()
    response = anonymous.get(reverse("ops_console:dashboard"))
    assert response.status_code == 401
    assert response.json()["reason_code"] == "ops_console_login_required"

    user_model = get_user_model()
    user_model.objects.create_user(username="plain", password="pass")
    plain = Client()
    assert plain.login(username="plain", password="pass")
    response = plain.get(reverse("ops_console:dashboard"))
    assert response.status_code == 403
    assert response.json()["reason_code"] == "ops_console_permission_denied"


@override_settings(DEPLOYMENT_REAL_TRADING_ENABLED=True)
def test_real_trading_query_is_read_only_and_honors_runtime_config() -> None:
    RuntimeTradingConfig.objects.create(
        config_key="default",
        runtime_real_trading_permission=False,
        updated_by="tester",
        updated_reason="keep disabled",
    )
    client = _client_with_group("readonly")

    response = client.get(reverse("ops_console:real_trading"))

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["deployment_real_trading_permission"] is True
    assert data["runtime_real_trading_permission"] is False
    assert data["effective_real_trading_permission"] is False
    assert RuntimeTradingConfig.objects.get(config_key="default").runtime_real_trading_permission is False


def _run_with_step_and_link() -> OrchestrationRun:
    run = OrchestrationRun.objects.create(
        run_key="ops-run-1",
        pipeline_code="main_trading_pipeline",
        registry_version="p0.1",
        registry_hash="hash",
        scheduled_for_utc=timezone.now(),
        cycle_kind="4h",
        trigger_mode=OrchestrationTriggerMode.AUTOMATIC,
        trigger_source="test",
        status=OrchestrationRunStatus.RUNNING,
        current_step_code="order_submission",
        trace_id="trace-ops-run",
    )
    step = OrchestrationStepRun.objects.create(
        orchestration_run=run,
        step_code="order_submission",
        module_code="execution",
        adapter_code="OrderSubmissionStepAdapter",
        adapter_version="1.0",
        result_mapping_version="1.0",
        execution_sequence=1,
        business_request_key="ops-step-1",
        status=OrchestrationStepRunStatus.SUCCEEDED,
        normalized_status="SUCCEEDED",
        flow_action="CONTINUE",
        reason_code="order_submitted",
        primary_object_type="OrderSubmissionAttempt",
        primary_object_id="1",
        trace_id=run.trace_id,
    )
    OrchestrationBusinessObjectLink.objects.create(
        orchestration_run=run,
        step_run=step,
        step_code=step.step_code,
        module_code=step.module_code,
        object_role=OrchestrationObjectRole.PRIMARY,
        object_type="OrderSubmissionAttempt",
        object_id="1",
        object_label="attempt-1",
        trace_id=run.trace_id,
    )
    RuntimeGuardIssue.objects.create(
        issue_key="ops-run-issue",
        issue_type="orchestration_run_stale",
        severity=RuntimeGuardIssueSeverity.HIGH,
        status=RuntimeGuardIssueStatus.OPEN,
        first_seen_at_utc=timezone.now(),
        last_seen_at_utc=timezone.now(),
        related_object_type="OrchestrationRun",
        related_object_id=str(run.id),
        related_trace_id=run.trace_id,
        description_zh="编排运行需要关注",
    )
    record_alert_event(
        event_key="ops-run-alert",
        source_module="orchestration",
        event_type="run_attention",
        event_category="orchestration",
        severity="warning",
        title_zh="编排关注",
        message_zh="测试告警",
        trace_id=run.trace_id,
        trigger_source="test",
        related_object_type="OrchestrationRun",
        related_object_id=str(run.id),
        delivery_enabled=False,
    )
    return run


def test_runs_list_and_detail_use_orchestration_facts() -> None:
    run = _run_with_step_and_link()
    client = _client_with_group("readonly")

    list_response = client.get(reverse("ops_console:runs"), {"limit": "500"})
    detail_response = client.get(reverse("ops_console:run_detail", kwargs={"run_id": run.id}))

    assert list_response.status_code == 200
    list_data = list_response.json()["data"]
    assert list_data["pagination"]["limit"] == 100
    assert list_data["items"][0]["has_order_submission"] is True
    assert detail_response.status_code == 200
    detail = detail_response.json()["data"]
    assert detail["id"] == run.id
    assert detail["steps"][0]["step_code"] == "order_submission"
    assert detail["related_alerts"][0]["event_type"] == "run_attention"
    assert detail["related_runtime_guard_issues"][0]["issue_type"] == "orchestration_run_stale"


def test_run_detail_does_not_link_unrelated_empty_trace_alerts() -> None:
    run = OrchestrationRun.objects.create(
        run_key="ops-run-empty-trace",
        pipeline_code="main_trading_pipeline",
        registry_version="p0.1",
        registry_hash="hash",
        scheduled_for_utc=timezone.now(),
        cycle_kind="4h",
        trigger_mode=OrchestrationTriggerMode.AUTOMATIC,
        trigger_source="test",
        status=OrchestrationRunStatus.COMPLETED,
        trace_id="",
    )
    record_alert_event(
        event_key="ops-unrelated-empty-trace-alert",
        source_module="runtime_guard",
        event_type="unrelated",
        event_category="runtime_guard",
        severity="warning",
        title_zh="unrelated",
        message_zh="unrelated",
        trace_id="",
        trigger_source="test",
        related_object_type="OtherObject",
        related_object_id="999",
        delivery_enabled=False,
    )
    RuntimeGuardIssue.objects.create(
        issue_key="ops-unrelated-empty-trace-issue",
        issue_type="unrelated",
        severity=RuntimeGuardIssueSeverity.HIGH,
        status=RuntimeGuardIssueStatus.OPEN,
        first_seen_at_utc=timezone.now(),
        last_seen_at_utc=timezone.now(),
        related_object_type="OtherObject",
        related_object_id="999",
        related_trace_id="",
        description_zh="unrelated",
    )
    client = _client_with_group("readonly")

    response = client.get(reverse("ops_console:run_detail", kwargs={"run_id": run.id}))

    assert response.status_code == 200
    data = response.json()["data"]
    assert all(alert["event_type"] != "unrelated" for alert in data["related_alerts"])
    assert all(issue["issue_type"] != "unrelated" for issue in data["related_runtime_guard_issues"])


def test_order_detail_is_read_only_and_expands_existing_order_chain(settings) -> None:
    prepared = _prepared(settings, key="ops-order")
    submit_result = _submit(prepared, FakeBinanceOrderSubmissionGateway(), key="ops-order")
    attempt_id = submit_result.data["order_submission_attempt_id"]
    before_count = OrderSubmissionAttempt.objects.count()
    client = _client_with_group("readonly")

    response = client.get(reverse("ops_console:order_detail", kwargs={"attempt_id": attempt_id}))

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["order_submission_attempt"]["id"] == attempt_id
    assert data["prepared_order_intent"]["id"] == prepared.id
    assert data["order_plan"]["id"] == prepared.source_order_plan_id
    assert OrderSubmissionAttempt.objects.count() == before_count


def test_order_detail_does_not_link_unrelated_empty_trace_alerts(settings) -> None:
    prepared = _prepared(settings, key="ops-order-empty-trace")
    submit_result = _submit(prepared, FakeBinanceOrderSubmissionGateway(), key="ops-order-empty-trace")
    attempt = OrderSubmissionAttempt.objects.get(id=submit_result.data["order_submission_attempt_id"])
    attempt.trace_id = ""
    attempt.save(update_fields=["trace_id", "updated_at_utc"])
    record_alert_event(
        event_key="ops-order-unrelated-empty-trace-alert",
        source_module="runtime_guard",
        event_type="unrelated",
        event_category="runtime_guard",
        severity="warning",
        title_zh="unrelated",
        message_zh="unrelated",
        trace_id="",
        trigger_source="test",
        related_object_type="OtherObject",
        related_object_id="999",
        delivery_enabled=False,
    )
    RuntimeGuardIssue.objects.create(
        issue_key="ops-order-unrelated-empty-trace-issue",
        issue_type="unrelated",
        severity=RuntimeGuardIssueSeverity.HIGH,
        status=RuntimeGuardIssueStatus.OPEN,
        first_seen_at_utc=timezone.now(),
        last_seen_at_utc=timezone.now(),
        related_object_type="OtherObject",
        related_object_id="999",
        related_trace_id="",
        description_zh="unrelated",
    )
    client = _client_with_group("readonly")

    response = client.get(reverse("ops_console:order_detail", kwargs={"attempt_id": attempt.id}))

    assert response.status_code == 200
    data = response.json()["data"]
    assert all(alert["event_type"] != "unrelated" for alert in data["related_alerts"])
    assert all(issue["issue_type"] != "unrelated" for issue in data["related_runtime_guard_issues"])


def test_account_overview_reads_only_ops_display_snapshot(settings) -> None:
    now = timezone.now()
    sync_run = BinanceSyncRun.objects.create(
        business_request_key="ops-display-account",
        market_type=MARKET_TYPE_USDS_M,
        account_domain=settings.ACTIVE_ACCOUNT_DOMAIN,
        sync_purpose=BinanceSyncPurpose.OPS_DISPLAY,
        requested_symbols=[settings.ACTIVE_SYMBOL],
        status=BinanceSyncStatus.SUCCEEDED,
        started_at_utc=now,
        finished_at_utc=now,
        as_of_utc=now,
        position_mode=BinancePositionMode.ONE_WAY,
        snapshot_set_hash="hash",
        trace_id="trace-ops-account",
        trigger_source="test",
    )
    BinanceSyncRun.objects.create(
        business_request_key="trade-preparation-account",
        market_type=settings.ACTIVE_MARKET_TYPE,
        account_domain=settings.ACTIVE_ACCOUNT_DOMAIN,
        sync_purpose=BinanceSyncPurpose.TRADE_PREPARATION,
        requested_symbols=[settings.ACTIVE_SYMBOL],
        status=BinanceSyncStatus.SUCCEEDED,
        trace_id="trace-trade-account",
        trigger_source="test",
    )
    BinanceAccountSnapshot.objects.create(
        sync_run=sync_run,
        market_type=sync_run.market_type,
        account_domain=sync_run.account_domain,
        position_mode=BinancePositionMode.ONE_WAY,
        total_wallet_balance=Decimal("1000"),
        total_margin_balance=Decimal("1000"),
        available_balance=Decimal("900"),
        native_asset="USDT",
        as_of_utc=now,
        source_operation="account_info",
        snapshot_hash="account-hash",
    )
    BinanceBalanceSnapshot.objects.create(
        sync_run=sync_run,
        market_type=sync_run.market_type,
        account_domain=sync_run.account_domain,
        asset="USDT",
        wallet_balance=Decimal("1000"),
        available_balance=Decimal("900"),
        source_operation="account_info",
        snapshot_hash="balance-hash",
    )
    BinancePositionSnapshot.objects.create(
        sync_run=sync_run,
        market_type=sync_run.market_type,
        account_domain=sync_run.account_domain,
        symbol=settings.ACTIVE_SYMBOL,
        normalized_position_side="BOTH",
        position_amount=Decimal("0.1"),
        entry_price=Decimal("50000"),
        mark_price=Decimal("51000"),
        position_mode_observed=BinancePositionMode.ONE_WAY,
        source_operation="position_risk",
        snapshot_hash="position-hash",
    )
    BinanceSymbolRuleSnapshot.objects.create(
        sync_run=sync_run,
        market_type=sync_run.market_type,
        account_domain=sync_run.account_domain,
        symbol=settings.ACTIVE_SYMBOL,
        min_quantity=Decimal("0.001"),
        min_notional=Decimal("5"),
        source_operation="exchange_info",
        snapshot_hash="rule-hash",
    )
    client = _client_with_group("readonly")

    response = client.get(reverse("ops_console:account_overview"))

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["sync_run"]["id"] == sync_run.id
    assert data["sync_run"]["sync_purpose"] == BinanceSyncPurpose.OPS_DISPLAY
    assert data["account_snapshot"]["available_balance"] == "900.000000000000000000"
    assert data["positions"][0]["symbol"] == settings.ACTIVE_SYMBOL


def test_alert_issue_and_audit_queries_are_sanitized() -> None:
    alert = record_alert_event(
        event_key="ops-alert",
        source_module="runtime_guard",
        event_type="active_lock_stale",
        event_category="runtime_guard",
        severity="high",
        title_zh="锁需要关注",
        message_zh="测试告警",
        trace_id="trace-ops-alert",
        trigger_source="test",
        payload_summary={"api_key": "secret-value", "safe": "visible"},
        delivery_enabled=False,
    )
    issue = RuntimeGuardIssue.objects.create(
        issue_key="ops-issue",
        issue_type="active_lock_stale",
        severity=RuntimeGuardIssueSeverity.HIGH,
        status=RuntimeGuardIssueStatus.OPEN,
        first_seen_at_utc=timezone.now(),
        last_seen_at_utc=timezone.now(),
        related_object_type="OrderPlanActiveLock",
        related_object_id="9",
        related_trace_id="trace-lock",
        description_zh="锁需要关注",
        evidence={"token": "secret", "safe": "visible"},
        alert_event_id=alert.id,
    )
    AuditRecord.objects.create(
        operator_id="operator",
        operation_type="runtime_real_trading_permission_changed",
        target_object_type="RuntimeTradingConfig",
        target_object_id="1",
        before_state_summary={"api_key": "secret", "enabled": False},
        after_state_summary={"enabled": True},
        reason="test",
        evidence={"password": "secret", "safe": "visible"},
        result="succeeded",
        trace_id="trace-audit",
        trigger_source="test",
    )
    client = _client_with_group("readonly")

    alert_response = client.get(reverse("ops_console:alert_detail", kwargs={"alert_id": alert.id}))
    issue_response = client.get(reverse("ops_console:runtime_guard_issue_detail", kwargs={"issue_id": issue.id}))
    audit_response = client.get(reverse("ops_console:audit_log"))

    assert alert_response.status_code == 200
    assert alert_response.json()["data"]["payload_summary"]["api_key"] == "[REDACTED]"
    assert issue_response.status_code == 200
    assert issue_response.json()["data"]["evidence"]["token"] == "[REDACTED]"
    assert audit_response.status_code == 200
    item = audit_response.json()["data"]["items"][0]
    assert item["before_state_summary"]["api_key"] == "[REDACTED]"
    assert item["evidence"]["password"] == "[REDACTED]"
