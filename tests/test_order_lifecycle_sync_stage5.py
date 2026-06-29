from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.binance_gateway.fill_query import FakeBinanceFillQueryGateway
from apps.binance_gateway.order_status import FakeBinanceOrderStatusGateway
from apps.binance_gateway.order_submission import FakeBinanceOrderSubmissionGateway
from apps.execution.models import OrderSubmissionAttempt, OrderSubmissionAttemptStatus
from apps.fill_sync.models import FillSyncResult, OrderFillSummary, TradeFill
from apps.foundation.results import ResultStatus, ServiceResult
from apps.order_lifecycle.services.sync import sync_order_lifecycle
from apps.order_lifecycle.tasks import sync_order_lifecycle_task
from apps.order_plan.models import ActiveLockStatus, OrderPlanActiveLock
from apps.order_status_sync.models import OrderStatusSyncRecord
from tests.test_execution_order_submission_stage5 import _prepared, _submit
from tests.test_fill_sync_stage5 import _enable, _fill, _make_due


pytestmark = pytest.mark.django_db


def test_order_lifecycle_sync_terminal_status_then_fill_sync_releases_lock(settings) -> None:
    _enable(settings)
    prepared = _prepared(settings, key="lifecycle-success")
    submit_result = _submit(prepared, FakeBinanceOrderSubmissionGateway(), key="lifecycle-success")
    attempt = _make_due(OrderSubmissionAttempt.objects.get(id=submit_result.data["order_submission_attempt_id"]))
    status_gateway = FakeBinanceOrderStatusGateway(
        payload={
            "symbol": attempt.symbol,
            "orderId": attempt.exchange_order_id,
            "clientOrderId": attempt.client_order_id,
            "status": "FILLED",
            "executedQty": "0.01",
            "cumQuote": "500",
        }
    )
    fill_gateway = FakeBinanceFillQueryGateway(pages=[{"fills": [_fill(attempt)], "pagination_complete": True}])

    result = sync_order_lifecycle(
        order_submission_attempt_id=attempt.id,
        business_request_key="order-lifecycle-success",
        poll_sequence=1,
        trace_id="trace-order-lifecycle-success",
        trigger_source="test",
        order_status_gateway=status_gateway,
        fill_query_gateway=fill_gateway,
    )

    assert result.status == "succeeded"
    assert result.data["lifecycle_action"] == "COMPLETE"
    assert result.data["order_status_sync_record_id"] == OrderStatusSyncRecord.objects.get().id
    assert result.data["fill_sync_result_id"] == FillSyncResult.objects.get().id
    assert TradeFill.objects.count() == 1
    assert OrderFillSummary.objects.get().status == "complete"
    assert OrderPlanActiveLock.objects.get(id=attempt.active_lock_id).status == ActiveLockStatus.RELEASED
    assert len(status_gateway.calls) == 1
    assert len(fill_gateway.calls) == 1


def test_order_lifecycle_sync_non_terminal_status_stops_without_fill_sync(settings) -> None:
    _enable(settings)
    prepared = _prepared(settings, key="lifecycle-wait")
    submit_result = _submit(prepared, FakeBinanceOrderSubmissionGateway(), key="lifecycle-wait")
    attempt = _make_due(OrderSubmissionAttempt.objects.get(id=submit_result.data["order_submission_attempt_id"]))
    status_gateway = FakeBinanceOrderStatusGateway(
        payload={
            "symbol": attempt.symbol,
            "orderId": attempt.exchange_order_id,
            "clientOrderId": attempt.client_order_id,
            "status": "NEW",
        }
    )
    fill_gateway = FakeBinanceFillQueryGateway(pages=[{"fills": [_fill(attempt)], "pagination_complete": True}])

    result = sync_order_lifecycle(
        order_submission_attempt_id=attempt.id,
        business_request_key="order-lifecycle-wait",
        poll_sequence=1,
        trace_id="trace-order-lifecycle-wait",
        trigger_source="test",
        order_status_gateway=status_gateway,
        fill_query_gateway=fill_gateway,
    )

    assert result.status == "no_action"
    assert result.data["lifecycle_action"] == "STOP"
    assert result.data["next_poll_sequence"] is None
    assert OrderStatusSyncRecord.objects.get().is_terminal_status is False
    assert FillSyncResult.objects.count() == 0
    assert TradeFill.objects.count() == 0
    assert OrderPlanActiveLock.objects.get(id=attempt.active_lock_id).status == ActiveLockStatus.ACTIVE
    assert len(status_gateway.calls) == 1
    assert fill_gateway.calls == []


def test_order_lifecycle_sync_rejected_attempt_is_complete_without_status_query(settings) -> None:
    _enable(settings)
    prepared = _prepared(settings, key="lifecycle-rejected")
    submit_result = _submit(prepared, FakeBinanceOrderSubmissionGateway(), key="lifecycle-rejected")
    attempt = _make_due(OrderSubmissionAttempt.objects.get(id=submit_result.data["order_submission_attempt_id"]))
    OrderSubmissionAttempt.objects.filter(id=attempt.id).update(status=OrderSubmissionAttemptStatus.REJECTED)
    status_gateway = FakeBinanceOrderStatusGateway(payload={"symbol": attempt.symbol, "status": "FILLED"})
    fill_gateway = FakeBinanceFillQueryGateway(pages=[{"fills": [_fill(attempt)], "pagination_complete": True}])

    result = sync_order_lifecycle(
        order_submission_attempt_id=attempt.id,
        business_request_key="order-lifecycle-rejected",
        poll_sequence=1,
        trace_id="trace-order-lifecycle-rejected",
        trigger_source="test",
        order_status_gateway=status_gateway,
        fill_query_gateway=fill_gateway,
    )

    assert result.status == "no_action"
    assert result.data["lifecycle_action"] == "COMPLETE"
    assert result.data["requires_order_status_sync"] is False
    assert OrderStatusSyncRecord.objects.count() == 0
    assert FillSyncResult.objects.count() == 0
    assert status_gateway.calls == []
    assert fill_gateway.calls == []


def test_order_lifecycle_sync_closeout_can_query_after_immediate_window(settings) -> None:
    _enable(settings)
    prepared = _prepared(settings, key="lifecycle-closeout-late")
    submit_result = _submit(
        prepared,
        FakeBinanceOrderSubmissionGateway(),
        key="lifecycle-closeout-late",
    )
    attempt = OrderSubmissionAttempt.objects.get(
        id=submit_result.data["order_submission_attempt_id"],
    )
    OrderSubmissionAttempt.objects.filter(id=attempt.id).update(
        finished_at_utc=timezone.now() - timedelta(hours=3, minutes=55),
    )
    attempt.refresh_from_db()
    status_gateway = FakeBinanceOrderStatusGateway(
        payload={
            "symbol": attempt.symbol,
            "orderId": attempt.exchange_order_id,
            "clientOrderId": attempt.client_order_id,
            "status": "FILLED",
            "executedQty": "0.01",
            "cumQuote": "500",
        },
    )
    fill_gateway = FakeBinanceFillQueryGateway(
        pages=[{"fills": [_fill(attempt)], "pagination_complete": True}],
    )

    result = sync_order_lifecycle(
        order_submission_attempt_id=attempt.id,
        business_request_key="order-lifecycle-closeout-late",
        poll_sequence=1,
        trace_id="trace-order-lifecycle-closeout-late",
        trigger_source="test",
        order_status_gateway=status_gateway,
        fill_query_gateway=fill_gateway,
    )

    record = OrderStatusSyncRecord.objects.get()
    assert result.status == "succeeded"
    assert record.poll_mode == "closeout"
    assert record.query_outcome == "found"
    assert len(status_gateway.calls) == 1
    assert len(fill_gateway.calls) == 1


def test_order_lifecycle_task_does_not_schedule_next_poll_without_retrying_submission(settings, monkeypatch) -> None:
    settings.ORDER_STATUS_POLL_INTERVAL_SECONDS = 2
    scheduled_calls: list[dict[str, object]] = []

    def fake_run_order_lifecycle_pipeline(**kwargs):
        assert kwargs["poll_sequence"] == 1
        return ServiceResult(
            ResultStatus.NO_ACTION,
            "poll_not_due",
            "状态轮询尚未到下一轮。",
            kwargs["trace_id"],
            kwargs["trigger_source"],
            {
                "order_submission_attempt_id": kwargs["order_submission_attempt_id"],
                "lifecycle_action": "WAIT",
                "next_poll_sequence": 2,
                "order_status_sync_record_id": None,
            },
        )

    def fake_apply_async(*, kwargs, countdown):
        scheduled_calls.append({"kwargs": kwargs, "countdown": countdown})

    monkeypatch.setattr("apps.order_lifecycle.tasks.run_order_lifecycle_pipeline", fake_run_order_lifecycle_pipeline)
    monkeypatch.setattr(sync_order_lifecycle_task, "apply_async", fake_apply_async)

    result = sync_order_lifecycle_task(
        order_submission_attempt_id=101,
        business_request_key="order-lifecycle-task",
        poll_sequence=1,
        trace_id="trace-order-lifecycle-task",
        trigger_source="test",
    )

    assert result["status"] == "no_action"
    assert result["lifecycle_action"] == "WAIT"
    assert result["scheduled_next_poll"] is False
    assert scheduled_calls == []
