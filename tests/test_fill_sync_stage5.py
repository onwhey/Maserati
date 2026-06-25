from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.alerts.models import AlertEvent
from apps.binance_gateway.fill_query import FakeBinanceFillQueryGateway
from apps.binance_gateway.order_status import FakeBinanceOrderStatusGateway
from apps.binance_gateway.order_submission import FakeBinanceOrderSubmissionGateway
from apps.binance_gateway.public_market import FakeBinancePublicMarketGateway
from apps.execution.models import OrderSubmissionAttempt
from apps.execution_preparation.models import PreparedOrderIntent
from apps.execution_preparation.services.preparation import prepare_execution
from apps.fill_sync.models import FillSyncResult, OrderFillSummary, TradeFill
from apps.fill_sync.services.sync import sync_order_fills
from apps.order_plan.models import ActiveLockStatus, OrderPlanActiveLock
from apps.risk_check.models import ApprovedOrderIntent
from apps.order_status_sync.models import OrderStatusSyncRecord
from apps.order_status_sync.services.status_sync import poll_order_status
from tests.test_order_plan_stage4 import _price
from tests.test_execution_order_submission_stage5 import _prepared, _submit
from tests.test_risk_check_stage4 import _account_facts, _order_plan, _risk_check


pytestmark = pytest.mark.django_db


def _enable(settings) -> None:
    settings.ORDER_STATUS_SYNC_ENABLED = True
    settings.FILL_SYNC_ENABLED = True
    settings.FILL_SYNC_PAGE_SIZE = 100
    settings.FILL_SYNC_MAX_PAGES = 10
    settings.ORDER_STATUS_POLL_INTERVAL_SECONDS = 2
    settings.ORDER_STATUS_POLL_MAX_DURATION_SECONDS = 30


def _enable_execution_preparation(settings) -> None:
    settings.EXECUTION_PREPARATION_ENABLED = True
    settings.EXECUTION_PREPARATION_MAX_PRICE_DEVIATION_BPS = 100
    settings.PREPARED_ORDER_INTENT_TTL_SECONDS = 30
    settings.EXECUTION_PREPARATION_SUPPORTED_ORDER_TYPES = ["MARKET"]
    settings.EXECUTION_PREPARATION_SUPPORTED_POSITION_MODE = "one_way"


def _make_due(attempt: OrderSubmissionAttempt) -> OrderSubmissionAttempt:
    OrderSubmissionAttempt.objects.filter(id=attempt.id).update(finished_at_utc=timezone.now() - timedelta(seconds=2))
    attempt.refresh_from_db()
    return attempt


def _terminal_attempt(
    settings,
    *,
    key: str,
    status: str = "FILLED",
    executed_qty: str = "0.01",
    cum_quote: str = "500",
) -> tuple[OrderSubmissionAttempt, OrderStatusSyncRecord]:
    _enable(settings)
    prepared = _prepared(settings, key=f"fill-{key}")
    submit_result = _submit(prepared, FakeBinanceOrderSubmissionGateway(), key=f"fill-{key}")
    attempt = _make_due(OrderSubmissionAttempt.objects.get(id=submit_result.data["order_submission_attempt_id"]))
    order_status_gateway = FakeBinanceOrderStatusGateway(
        payload={
            "symbol": attempt.symbol,
            "orderId": attempt.exchange_order_id,
            "clientOrderId": attempt.client_order_id,
            "status": status,
            "executedQty": executed_qty,
            "cumQuote": cum_quote,
        }
    )
    status_result = poll_order_status(
        order_submission_attempt_id=attempt.id,
        business_request_key=f"order-status-fill-{key}",
        poll_sequence=1,
        trace_id=f"trace-order-status-fill-{key}",
        trigger_source="test",
        gateway=order_status_gateway,
    )
    assert status_result.data["allows_fill_sync"] is True
    return attempt, OrderStatusSyncRecord.objects.get(order_submission_attempt=attempt)


def _coin_prepared(settings, *, key: str) -> PreparedOrderIntent:
    _enable(settings)
    _enable_execution_preparation(settings)
    account = _account_facts(
        market_type="coin_m_futures",
        position="0",
        equity="0.1",
        available="0.1",
        leverage="20",
        contract_size="100",
        step_size="1",
    )
    price = _price(market_type="coin_m_futures", value="50000")
    plan_result = _order_plan(settings=settings, ratio="0.1", account=account, price=price, key=f"coin-{key}")
    assert plan_result.status == "succeeded"
    risk_result = _risk_check(key=f"coin-{key}")
    assert risk_result.status == "succeeded"
    approved = ApprovedOrderIntent.objects.get()
    preparation_gateway = FakeBinancePublicMarketGateway(
        book_ticker_payload={
            "symbol": "BTCUSDT",
            "bidPrice": "49990",
            "bidQty": "10",
            "askPrice": "50010",
            "askQty": "10",
        }
    )
    preparation_result = prepare_execution(
        approved_order_intent_id=approved.id,
        business_request_key=f"execution-preparation-coin-{key}",
        reference_time_utc=timezone.now(),
        trace_id=f"trace-execution-preparation-coin-{key}",
        trigger_source="test",
        gateway=preparation_gateway,
    )
    assert preparation_result.status == "succeeded"
    return PreparedOrderIntent.objects.get()


def _coin_terminal_attempt(settings, *, key: str) -> tuple[OrderSubmissionAttempt, OrderStatusSyncRecord]:
    prepared = _coin_prepared(settings, key=key)
    submit_result = _submit(prepared, FakeBinanceOrderSubmissionGateway(), key=f"coin-{key}")
    attempt = _make_due(OrderSubmissionAttempt.objects.get(id=submit_result.data["order_submission_attempt_id"]))
    order_status_gateway = FakeBinanceOrderStatusGateway(
        payload={
            "symbol": attempt.symbol,
            "orderId": attempt.exchange_order_id,
            "clientOrderId": attempt.client_order_id,
            "status": "FILLED",
            "executedQty": str(attempt.quantity),
            "cumQuote": "0",
        }
    )
    status_result = poll_order_status(
        order_submission_attempt_id=attempt.id,
        business_request_key=f"order-status-fill-coin-{key}",
        poll_sequence=1,
        trace_id=f"trace-order-status-fill-coin-{key}",
        trigger_source="test",
        gateway=order_status_gateway,
    )
    assert status_result.data["allows_fill_sync"] is True
    return attempt, OrderStatusSyncRecord.objects.get(order_submission_attempt=attempt)


def _fill(attempt: OrderSubmissionAttempt, *, trade_id: str = "9001", price: str = "50000", qty: str = "0.01") -> dict:
    return {
        "symbol": attempt.symbol,
        "orderId": attempt.exchange_order_id,
        "id": trade_id,
        "side": attempt.side,
        "positionSide": attempt.position_side,
        "price": price,
        "qty": qty,
        "quoteQty": str(Decimal(price) * Decimal(qty)),
        "commission": "0.1",
        "commissionAsset": "USDT",
        "realizedPnl": "0",
        "time": int(timezone.now().timestamp() * 1000),
        "buyer": True,
        "maker": False,
    }


def _coin_fill(attempt: OrderSubmissionAttempt, *, trade_id: str = "coin-9001", base_qty: str = "0.01") -> dict:
    return {
        "symbol": attempt.symbol,
        "orderId": attempt.exchange_order_id,
        "id": trade_id,
        "side": attempt.side,
        "positionSide": attempt.position_side,
        "price": "50000",
        "qty": str(attempt.quantity),
        "baseQty": base_qty,
        "commission": "0.00001",
        "commissionAsset": "BTC",
        "realizedPnl": "0",
        "time": int(timezone.now().timestamp() * 1000),
        "buyer": True,
        "maker": False,
    }


def _sync(attempt: OrderSubmissionAttempt, terminal: OrderStatusSyncRecord, gateway: FakeBinanceFillQueryGateway, *, key: str):
    return sync_order_fills(
        order_submission_attempt_id=attempt.id,
        terminal_order_status_sync_record_id=terminal.id,
        business_request_key=f"fill-sync-{key}",
        trace_id=f"trace-fill-sync-{key}",
        trigger_source="test",
        gateway=gateway,
    )


def test_fill_sync_records_trade_fill_summary_and_releases_lock(settings) -> None:
    attempt, terminal = _terminal_attempt(settings, key="success")
    gateway = FakeBinanceFillQueryGateway(pages=[{"fills": [_fill(attempt)], "pagination_complete": True}])

    result = _sync(attempt, terminal, gateway, key="success")

    sync_result = FillSyncResult.objects.get()
    fill = TradeFill.objects.get()
    summary = OrderFillSummary.objects.get()
    lock = OrderPlanActiveLock.objects.get(id=attempt.active_lock_id)
    assert result.status == "succeeded"
    assert result.data["allows_active_lock_finalization"] is True
    assert sync_result.status == "synced"
    assert sync_result.returned_fill_count == 1
    assert sync_result.inserted_fill_count == 1
    assert fill.exchange_trade_id == "9001"
    assert fill.quantity == Decimal("0.01")
    assert summary.status == "complete"
    assert summary.total_quantity == Decimal("0.01")
    assert summary.average_price == Decimal("50000")
    assert summary.quantity_reconciled is True
    assert lock.status == ActiveLockStatus.RELEASED
    assert gateway.calls[0]["call_context"].metadata["fill_sync_result_id"] == sync_result.id
    assert AlertEvent.objects.filter(source_module="FillSync", event_type="fill_sync_synced").count() == 1


def test_fill_sync_duplicate_resync_does_not_double_count(settings) -> None:
    attempt, terminal = _terminal_attempt(settings, key="duplicate")
    first_gateway = FakeBinanceFillQueryGateway(pages=[{"fills": [_fill(attempt)], "pagination_complete": True}])
    second_gateway = FakeBinanceFillQueryGateway(pages=[{"fills": [_fill(attempt)], "pagination_complete": True}])

    _sync(attempt, terminal, first_gateway, key="duplicate-a")
    second = _sync(attempt, terminal, second_gateway, key="duplicate-b")

    latest = FillSyncResult.objects.order_by("-sync_sequence").first()
    summary = OrderFillSummary.objects.get(order_submission_attempt=attempt)
    assert second.status == "succeeded"
    assert TradeFill.objects.count() == 1
    assert latest.duplicate_fill_count == 1
    assert latest.inserted_fill_count == 0
    assert summary.total_quantity == Decimal("0.01")


def test_fill_sync_same_trade_id_with_different_payload_is_incomplete(settings) -> None:
    attempt, terminal = _terminal_attempt(settings, key="conflict")
    first_gateway = FakeBinanceFillQueryGateway(pages=[{"fills": [_fill(attempt)], "pagination_complete": True}])
    conflict_gateway = FakeBinanceFillQueryGateway(pages=[{"fills": [_fill(attempt, price="50100")], "pagination_complete": True}])

    _sync(attempt, terminal, first_gateway, key="conflict-a")
    result = _sync(attempt, terminal, conflict_gateway, key="conflict-b")

    latest = FillSyncResult.objects.order_by("-sync_sequence").first()
    assert result.status == "unknown"
    assert latest.status == "incomplete"
    assert latest.conflict_fill_count == 1
    assert TradeFill.objects.count() == 1
    assert AlertEvent.objects.filter(source_module="FillSync", event_type="fill_sync_conflict").count() == 1


def test_filled_order_with_zero_fills_is_incomplete_and_keeps_lock(settings) -> None:
    attempt, terminal = _terminal_attempt(settings, key="filled-empty", executed_qty="0", cum_quote="0")
    gateway = FakeBinanceFillQueryGateway(pages=[{"fills": [], "pagination_complete": True}])

    result = _sync(attempt, terminal, gateway, key="filled-empty")

    sync_result = FillSyncResult.objects.get()
    summary = OrderFillSummary.objects.get()
    assert result.status == "unknown"
    assert sync_result.status == "incomplete"
    assert sync_result.reason_code == "filled_order_has_no_fills"
    assert summary.status == "incomplete"
    assert OrderPlanActiveLock.objects.get(id=attempt.active_lock_id).status == ActiveLockStatus.ACTIVE


def test_canceled_zero_fill_order_syncs_empty_and_releases_lock(settings) -> None:
    attempt, terminal = _terminal_attempt(settings, key="canceled-empty", status="CANCELED", executed_qty="0", cum_quote="0")
    gateway = FakeBinanceFillQueryGateway(pages=[{"fills": [], "pagination_complete": True}])

    result = _sync(attempt, terminal, gateway, key="canceled-empty")

    sync_result = FillSyncResult.objects.get()
    summary = OrderFillSummary.objects.get()
    assert result.status == "succeeded"
    assert sync_result.status == "synced_empty"
    assert summary.status == "empty"
    assert OrderPlanActiveLock.objects.get(id=attempt.active_lock_id).status == ActiveLockStatus.RELEASED


def test_fill_sync_non_terminal_record_is_blocked_without_gateway(settings) -> None:
    _enable(settings)
    prepared = _prepared(settings, key="fill-non-terminal")
    submit_result = _submit(prepared, FakeBinanceOrderSubmissionGateway(), key="fill-non-terminal")
    attempt = _make_due(OrderSubmissionAttempt.objects.get(id=submit_result.data["order_submission_attempt_id"]))
    order_status_gateway = FakeBinanceOrderStatusGateway(
        payload={"symbol": attempt.symbol, "orderId": attempt.exchange_order_id, "clientOrderId": attempt.client_order_id, "status": "NEW"}
    )
    poll_order_status(
        order_submission_attempt_id=attempt.id,
        business_request_key="order-status-fill-non-terminal",
        poll_sequence=1,
        trace_id="trace-order-status-fill-non-terminal",
        trigger_source="test",
        gateway=order_status_gateway,
    )
    terminal = OrderStatusSyncRecord.objects.get(order_submission_attempt=attempt)
    fill_gateway = FakeBinanceFillQueryGateway(pages=[{"fills": [_fill(attempt)], "pagination_complete": True}])

    result = _sync(attempt, terminal, fill_gateway, key="non-terminal")

    sync_result = FillSyncResult.objects.get()
    assert result.status == "blocked"
    assert sync_result.status == "blocked_before_query"
    assert sync_result.reason_code == "terminal_record_not_terminal"
    assert fill_gateway.calls == []
    assert TradeFill.objects.count() == 0
    assert OrderPlanActiveLock.objects.get(id=attempt.active_lock_id).status == ActiveLockStatus.ACTIVE


def test_fill_sync_missing_exchange_order_id_fails_before_query(settings) -> None:
    attempt, terminal = _terminal_attempt(settings, key="missing-order-id")
    OrderSubmissionAttempt.objects.filter(id=attempt.id).update(exchange_order_id="")
    OrderStatusSyncRecord.objects.filter(id=terminal.id).update(exchange_order_id_returned="", exchange_order_id_requested="")
    attempt.refresh_from_db()
    terminal.refresh_from_db()
    gateway = FakeBinanceFillQueryGateway(pages=[{"fills": [_fill(attempt)], "pagination_complete": True}])

    result = _sync(attempt, terminal, gateway, key="missing-order-id")

    sync_result = FillSyncResult.objects.get()
    assert result.status == "failed"
    assert sync_result.status == "failed_before_query"
    assert sync_result.reason_code == "missing_exchange_order_id"
    assert gateway.calls == []
    assert OrderPlanActiveLock.objects.get(id=attempt.active_lock_id).status == ActiveLockStatus.ACTIVE


def test_fill_sync_before_order_submission_finished_time_fails_without_gateway(settings) -> None:
    attempt, terminal = _terminal_attempt(settings, key="future-submission-fact")
    OrderSubmissionAttempt.objects.filter(id=attempt.id).update(finished_at_utc=timezone.now() + timedelta(seconds=10))
    attempt.refresh_from_db()
    gateway = FakeBinanceFillQueryGateway(pages=[{"fills": [_fill(attempt)], "pagination_complete": True}])

    result = _sync(attempt, terminal, gateway, key="future-submission-fact")

    sync_result = FillSyncResult.objects.get()
    assert result.status == "failed"
    assert sync_result.status == "failed_before_query"
    assert sync_result.reason_code == "sync_time_before_order_submission_fact"
    assert gateway.calls == []
    assert TradeFill.objects.count() == 0
    assert OrderPlanActiveLock.objects.get(id=attempt.active_lock_id).status == ActiveLockStatus.ACTIVE


def test_coin_m_fill_sync_uses_contract_size_for_notional_and_average_price(settings) -> None:
    attempt, terminal = _coin_terminal_attempt(settings, key="coin-success")
    gateway = FakeBinanceFillQueryGateway(pages=[{"fills": [_coin_fill(attempt)], "pagination_complete": True}])

    result = _sync(attempt, terminal, gateway, key="coin-success")

    sync_result = FillSyncResult.objects.get()
    fill = TradeFill.objects.get()
    summary = OrderFillSummary.objects.get()
    expected_notional = attempt.quantity * Decimal("100")
    assert result.status == "succeeded"
    assert sync_result.status == "synced"
    assert fill.quantity_unit == "contracts"
    assert fill.quantity == attempt.quantity
    assert fill.contract_size == Decimal("100")
    assert fill.base_quantity == Decimal("0.01")
    assert summary.status == "complete"
    assert summary.total_quantity == attempt.quantity
    assert summary.total_base_quantity == Decimal("0.01")
    assert summary.filled_notional_usd == expected_notional
    assert summary.average_price == expected_notional / Decimal("0.01")
    assert summary.quantity_reconciled is True
    assert OrderPlanActiveLock.objects.get(id=attempt.active_lock_id).status == ActiveLockStatus.RELEASED


def test_coin_m_fill_without_base_quantity_is_incomplete_and_keeps_lock(settings) -> None:
    attempt, terminal = _coin_terminal_attempt(settings, key="coin-missing-base")
    raw_fill = _coin_fill(attempt)
    raw_fill.pop("baseQty")
    gateway = FakeBinanceFillQueryGateway(pages=[{"fills": [raw_fill], "pagination_complete": True}])

    result = _sync(attempt, terminal, gateway, key="coin-missing-base")

    sync_result = FillSyncResult.objects.get()
    summary = OrderFillSummary.objects.get()
    assert result.status == "unknown"
    assert sync_result.status == "incomplete"
    assert sync_result.reason_code == "coin_m_base_quantity_missing"
    assert sync_result.conflict_fill_count == 1
    assert TradeFill.objects.count() == 0
    assert summary.status == "incomplete"
    assert OrderPlanActiveLock.objects.get(id=attempt.active_lock_id).status == ActiveLockStatus.ACTIVE
