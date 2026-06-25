from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from apps.alerts.models import AlertEvent
from apps.audit.models import AuditRecord
from apps.binance_account_sync.models import (
    BinanceAccountSnapshot,
    BinancePositionMode,
    BinancePositionSnapshot,
    BinanceSyncPurpose,
    BinanceSyncRun,
    BinanceSyncStatus,
)
from apps.binance_gateway.order_submission import FakeBinanceOrderSubmissionGateway
from apps.binance_gateway.types import MARKET_TYPE_USDS_M
from apps.fill_sync.models import FillSyncMode, FillSyncResult, FillSyncResultStatus, TradeFill
from apps.orchestration.models import (
    OrchestrationBusinessObjectLink,
    OrchestrationObjectRole,
    OrchestrationRun,
    OrchestrationRunStatus,
    OrchestrationStepRun,
    OrchestrationStepRunStatus,
    OrchestrationTriggerMode,
)
from apps.order_status_sync.models import (
    OrderStatusQueryOutcome,
    OrderStatusSubmissionResolution,
    OrderStatusSyncRecord,
)
from apps.performance_metrics.models import OrchestrationRunPerformance, PerformanceCalculationStatus
from apps.performance_metrics.services import backfill_missing_closed_period_performance, preview_missing_closed_period_performance
from tests.test_execution_order_submission_stage5 import _prepared, _submit


pytestmark = pytest.mark.django_db


def _client_with_group(group_name: str) -> Client:
    user_model = get_user_model()
    user = user_model.objects.create_user(username=f"perf-{group_name}", password="pass")
    group, _ = Group.objects.get_or_create(name=group_name)
    user.groups.add(group)
    client = Client()
    assert client.login(username=f"perf-{group_name}", password="pass")
    return client


def _boundary(
    *,
    key: str,
    scheduled_at,
    position: str | None,
    purpose: str = BinanceSyncPurpose.TRADE_PREPARATION,
) -> OrchestrationRun:
    run = OrchestrationRun.objects.create(
        run_key=f"perf-run-{key}",
        pipeline_code="main_trading_pipeline",
        registry_version="p0.1",
        registry_hash="hash",
        scheduled_for_utc=scheduled_at,
        cycle_kind="4h",
        trigger_mode=OrchestrationTriggerMode.AUTOMATIC,
        trigger_source="test",
        status=OrchestrationRunStatus.COMPLETED,
        final_outcome="succeeded",
        trace_id=f"trace-perf-run-{key}",
        finished_at_utc=scheduled_at + timedelta(minutes=5),
    )
    step = OrchestrationStepRun.objects.create(
        orchestration_run=run,
        step_code="binance_account_sync",
        module_code="binance_account_sync",
        adapter_code="BinanceAccountSyncStepAdapter",
        adapter_version="1.0",
        result_mapping_version="1.0",
        execution_sequence=1,
        business_request_key=f"perf-step-{key}",
        status=OrchestrationStepRunStatus.SUCCEEDED,
        normalized_status="SUCCEEDED",
        flow_action="CONTINUE",
        reason_code="account_sync_done",
        trace_id=run.trace_id,
        finished_at_utc=scheduled_at + timedelta(minutes=1),
        last_status_updated_at_utc=scheduled_at + timedelta(minutes=1),
    )
    sync_run = BinanceSyncRun.objects.create(
        business_request_key=f"perf-sync-{key}",
        market_type=MARKET_TYPE_USDS_M,
        account_domain="default",
        sync_purpose=purpose,
        requested_symbols=["BTCUSDT"],
        status=BinanceSyncStatus.SUCCEEDED,
        started_at_utc=scheduled_at,
        finished_at_utc=scheduled_at + timedelta(minutes=1),
        as_of_utc=scheduled_at,
        position_mode=BinancePositionMode.ONE_WAY,
        snapshot_set_hash=f"snapshot-{key}",
        trace_id=f"trace-perf-sync-{key}",
        trigger_source="test",
    )
    BinanceAccountSnapshot.objects.create(
        sync_run=sync_run,
        market_type=sync_run.market_type,
        account_domain=sync_run.account_domain,
        position_mode=BinancePositionMode.ONE_WAY,
        total_wallet_balance=Decimal("1000"),
        total_unrealized_profit=Decimal("0"),
        total_margin_balance=Decimal("1000"),
        available_balance=Decimal("900"),
        native_asset="USDT",
        as_of_utc=scheduled_at,
        source_operation="account_info",
        snapshot_hash=f"account-{key}",
    )
    position_amount = Decimal(position) if position is not None else None
    BinancePositionSnapshot.objects.create(
        sync_run=sync_run,
        market_type=sync_run.market_type,
        account_domain=sync_run.account_domain,
        symbol="BTCUSDT",
        normalized_position_side="BOTH",
        position_amount=position_amount,
        entry_price=Decimal("50000"),
        mark_price=Decimal("51000"),
        unrealized_pnl=Decimal("0"),
        notional=position_amount * Decimal("51000") if position_amount is not None else None,
        position_mode_observed=BinancePositionMode.ONE_WAY,
        source_operation="position_risk",
        snapshot_hash=f"position-{key}",
    )
    OrchestrationBusinessObjectLink.objects.create(
        orchestration_run=run,
        step_run=step,
        step_code=step.step_code,
        module_code=step.module_code,
        object_role=OrchestrationObjectRole.PRIMARY,
        object_type="BinanceSyncRun",
        object_id=str(sync_run.id),
        object_label=f"sync-{key}",
        trace_id=run.trace_id,
    )
    return run


def _link_attempt(run: OrchestrationRun, attempt_id: int) -> None:
    step = run.step_runs.get(step_code="binance_account_sync")
    OrchestrationBusinessObjectLink.objects.create(
        orchestration_run=run,
        step_run=step,
        step_code="order_submission",
        module_code="execution",
        object_role=OrchestrationObjectRole.RELATED,
        object_type="OrderSubmissionAttempt",
        object_id=str(attempt_id),
        object_label=f"attempt-{attempt_id}",
        trace_id=run.trace_id,
    )


def _record_terminal_fill(attempt, *, trade_time, quantity: str = "0.1", side: str = "BUY") -> TradeFill:
    now = timezone.now()
    record = OrderStatusSyncRecord.objects.create(
        order_status_sync_key=f"perf-order-status-{attempt.id}",
        order_submission_attempt=attempt,
        prepared_order_intent=attempt.prepared_order_intent,
        order_plan=attempt.order_plan,
        active_lock=attempt.active_lock,
        business_request_key=f"perf-order-status-{attempt.id}",
        market_type=attempt.market_type,
        account_domain=attempt.account_domain,
        endpoint_family=attempt.endpoint_family,
        symbol=attempt.symbol,
        query_identifier_type="client_order_id",
        client_order_id=attempt.client_order_id,
        poll_sequence=1,
        polling_started_at_utc=now,
        polling_deadline_utc=now + timedelta(seconds=30),
        scheduled_at_utc=now,
        query_started_at_utc=now,
        query_finished_at_utc=now,
        query_outcome=OrderStatusQueryOutcome.FOUND,
        reason_code="terminal_confirmed",
        request_sent=True,
        response_received=True,
        exchange_order_id_returned=attempt.exchange_order_id,
        exchange_client_order_id_returned=attempt.client_order_id,
        exchange_status="FILLED",
        exchange_status_observed_at_utc=now,
        is_recognized_status=True,
        is_terminal_status=True,
        submission_resolution_status=OrderStatusSubmissionResolution.TERMINAL_CONFIRMED,
        response_hash=f"status-hash-{attempt.id}",
        trace_id="trace-perf-status",
        trigger_source="test",
    )
    fill_result = FillSyncResult.objects.create(
        fill_sync_result_key=f"perf-fill-sync-{attempt.id}",
        sync_sequence=1,
        sync_mode=FillSyncMode.NORMAL,
        status=FillSyncResultStatus.SYNCED,
        reason_code="fills_synced",
        order_submission_attempt=attempt,
        terminal_order_status_sync_record=record,
        prepared_order_intent=attempt.prepared_order_intent,
        order_plan=attempt.order_plan,
        active_lock=attempt.active_lock,
        business_request_key=f"perf-fill-sync-{attempt.id}",
        market_type=attempt.market_type,
        account_domain=attempt.account_domain,
        endpoint_family=attempt.endpoint_family,
        symbol=attempt.symbol,
        client_order_id=attempt.client_order_id,
        exchange_order_id=attempt.exchange_order_id,
        terminal_exchange_status="FILLED",
        terminal_executed_quantity=Decimal(quantity),
        terminal_cumulative_quote_quantity=Decimal(quantity) * Decimal("50000"),
        page_count=1,
        pagination_complete=True,
        returned_fill_count=1,
        inserted_fill_count=1,
        sync_started_at_utc=now,
        sync_finished_at_utc=now,
        input_hash=f"fill-input-{attempt.id}",
        trace_id="trace-perf-fill",
        trigger_source="test",
    )
    return TradeFill.objects.create(
        order_submission_attempt=attempt,
        terminal_order_status_sync_record=record,
        first_seen_fill_sync_result=fill_result,
        market_type=attempt.market_type,
        account_domain=attempt.account_domain,
        endpoint_family=attempt.endpoint_family,
        symbol=attempt.symbol,
        client_order_id=attempt.client_order_id,
        exchange_order_id=attempt.exchange_order_id,
        exchange_trade_id=f"perf-trade-{attempt.id}",
        side=side,
        position_side=attempt.position_side,
        price=Decimal("50000"),
        quantity=Decimal(quantity),
        quantity_unit=attempt.quantity_unit,
        quote_quantity=Decimal(quantity) * Decimal("50000"),
        base_quantity=Decimal(quantity),
        commission=Decimal("1"),
        commission_asset="USDT",
        realized_pnl=Decimal("5"),
        realized_pnl_asset="USDT",
        is_buyer=side == "BUY",
        is_maker=False,
        trade_time_utc=trade_time,
        raw_fill_hash=f"raw-fill-{attempt.id}",
        trigger_source="test",
    )


def test_backfill_uses_trade_preparation_boundaries_and_basic_position_delta() -> None:
    now = timezone.now().replace(minute=5, second=0, microsecond=0)
    _boundary(key="00", scheduled_at=now - timedelta(hours=8), position="0.2")
    _boundary(key="04", scheduled_at=now - timedelta(hours=4), position="0.21")

    result = backfill_missing_closed_period_performance(operator_id="tester", reason="补算测试", trace_id="trace-perf-backfill")

    performance = OrchestrationRunPerformance.objects.get()
    assert result.status == "succeeded"
    assert performance.calculation_status == PerformanceCalculationStatus.CALCULATED
    assert performance.cycle_floating_pnl == Decimal("0.010000000000000000")
    assert performance.net_fill_quantity == Decimal("0")
    assert performance.start_position_quantity == Decimal("0.200000000000000000")
    assert performance.end_position_quantity == Decimal("0.210000000000000000")
    assert performance.period_start_utc.minute == 0
    assert performance.period_end_utc.minute == 0
    assert AlertEvent.objects.filter(source_module="performance_metrics").count() == 1
    assert AuditRecord.objects.filter(operation_type="performance_metrics_backfill").count() == 1


def test_backfill_subtracts_net_fills_from_period_position_change(settings) -> None:
    now = timezone.now()
    start = _boundary(key="fill-00", scheduled_at=now - timedelta(hours=8), position="0")
    _boundary(key="fill-04", scheduled_at=now - timedelta(hours=4), position="0.2")
    prepared = _prepared(settings, key="perf-fill")
    submit_result = _submit(prepared, FakeBinanceOrderSubmissionGateway(), key="perf-fill")
    attempt_id = submit_result.data["order_submission_attempt_id"]
    attempt = prepared.order_submission_attempt
    _link_attempt(start, attempt_id)
    _record_terminal_fill(attempt, trade_time=start.scheduled_for_utc + timedelta(minutes=5), quantity="0.1", side="BUY")

    result = backfill_missing_closed_period_performance(operator_id="tester", reason="补算成交测试", trace_id="trace-perf-fill")

    performance = OrchestrationRunPerformance.objects.get()
    assert result.status == "succeeded"
    assert performance.end_position_quantity == Decimal("0.200000000000000000")
    assert performance.net_fill_quantity == Decimal("0.100000000000000000")
    assert performance.cycle_floating_pnl == Decimal("0.100000000000000000")
    assert performance.order_realized_pnl == Decimal("5.000000000000000000")
    assert performance.order_commission == Decimal("1.000000000000000000")
    assert performance.has_order_submission is True
    assert performance.has_terminal_order_status is True
    assert performance.has_fill is True


def test_ops_display_sync_is_not_used_for_performance_boundary() -> None:
    now = timezone.now()
    _boundary(key="ops-00", scheduled_at=now - timedelta(hours=8), position="0.1", purpose=BinanceSyncPurpose.OPS_DISPLAY)
    _boundary(key="ops-04", scheduled_at=now - timedelta(hours=4), position="0.2")

    preview = preview_missing_closed_period_performance(reference_time_utc=now)
    result = backfill_missing_closed_period_performance(operator_id="tester", reason="补算测试", trace_id="trace-perf-ops")

    assert preview["calculable_missing_period_count"] == 0
    assert preview["not_calculable_reason_counts"]["performance_trade_preparation_sync_missing"] == 1
    assert result.data["skipped_count"] == 1
    assert OrchestrationRunPerformance.objects.count() == 0


def test_non_adjacent_four_hour_boundaries_are_not_calculated() -> None:
    now = timezone.now()
    _boundary(key="gap-00", scheduled_at=now - timedelta(hours=12), position="0.1")
    _boundary(key="gap-08", scheduled_at=now - timedelta(hours=4), position="0.2")

    preview = preview_missing_closed_period_performance(reference_time_utc=now)
    result = backfill_missing_closed_period_performance(operator_id="tester", reason="补算测试", trace_id="trace-perf-gap")

    assert preview["calculable_missing_period_count"] == 0
    assert preview["not_calculable_reason_counts"]["performance_period_boundary_not_adjacent"] == 1
    assert result.data["skipped_count"] == 1
    assert OrchestrationRunPerformance.objects.count() == 0


def test_missing_position_quantity_is_recorded_as_insufficient_instead_of_zero() -> None:
    now = timezone.now()
    _boundary(key="missing-position-00", scheduled_at=now - timedelta(hours=8), position=None)
    _boundary(key="missing-position-04", scheduled_at=now - timedelta(hours=4), position="0.2")

    result = backfill_missing_closed_period_performance(
        operator_id="tester",
        reason="补算测试",
        trace_id="trace-perf-missing-position",
    )

    performance = OrchestrationRunPerformance.objects.get()
    assert result.data["skipped_count"] == 1
    assert performance.calculation_status == PerformanceCalculationStatus.INSUFFICIENT_SNAPSHOT
    assert performance.reason_code == "performance_start_position_quantity_missing"
    assert performance.cycle_floating_pnl is None


def test_backfill_is_idempotent() -> None:
    now = timezone.now()
    _boundary(key="idem-00", scheduled_at=now - timedelta(hours=8), position="0.2")
    _boundary(key="idem-04", scheduled_at=now - timedelta(hours=4), position="0.21")

    first = backfill_missing_closed_period_performance(operator_id="tester", reason="第一次", trace_id="trace-perf-idem-1")
    second = backfill_missing_closed_period_performance(operator_id="tester", reason="第二次", trace_id="trace-perf-idem-2")

    assert first.data["calculated_count"] == 1
    assert second.data["existing_count"] == 1
    assert second.data["calculated_count"] == 0
    assert OrchestrationRunPerformance.objects.count() == 1


def test_ops_console_performance_preview_and_backfill_permissions() -> None:
    now = timezone.now()
    _boundary(key="api-00", scheduled_at=now - timedelta(hours=8), position="0.2")
    _boundary(key="api-04", scheduled_at=now - timedelta(hours=4), position="0.21")

    readonly = _client_with_group("readonly")
    operator = _client_with_group("ops_operator")

    preview_response = readonly.get(reverse("ops_console:performance_preview"))
    denied_response = readonly.post(
        reverse("ops_console:performance_backfill"),
        data={"confirm_write": True, "reason": "readonly denied"},
        content_type="application/json",
    )
    backfill_response = operator.post(
        reverse("ops_console:performance_backfill"),
        data={"confirm_write": True, "reason": "后台一键补算"},
        content_type="application/json",
    )
    list_response = readonly.get(reverse("ops_console:performance_records"))

    assert preview_response.status_code == 200
    assert preview_response.json()["data"]["calculable_missing_period_count"] == 1
    assert denied_response.status_code == 403
    assert backfill_response.status_code == 200
    assert backfill_response.json()["data"]["calculated_count"] == 1
    assert list_response.status_code == 200
    assert list_response.json()["data"]["items"][0]["cycle_floating_pnl"] == "0.010000000000000000"
