from __future__ import annotations

import pytest

from apps.binance_gateway.fill_query import FakeBinanceFillQueryGateway
from apps.binance_gateway.order_status import FakeBinanceOrderStatusGateway
from apps.binance_gateway.order_submission import FakeBinanceOrderSubmissionGateway
from apps.execution.models import OrderSubmissionAttempt
from apps.fill_sync.models import FillSyncResult, TradeFill
from apps.order_lifecycle.services.pipeline import run_order_lifecycle_pipeline
from apps.order_plan.models import ActiveLockStatus, OrderPlanActiveLock
from apps.order_status_sync.models import OrderStatusSyncRecord
from tests.test_execution_order_submission_stage5 import _prepared, _submit
from tests.test_fill_sync_stage5 import _enable, _fill, _make_due


pytestmark = pytest.mark.django_db


def test_order_lifecycle_pipeline_runs_status_then_fill_sync_with_auto_sequence(settings) -> None:
    _enable(settings)
    prepared = _prepared(settings, key="lifecycle-pipeline-success")
    submit_result = _submit(prepared, FakeBinanceOrderSubmissionGateway(), key="lifecycle-pipeline-success")
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

    result = run_order_lifecycle_pipeline(
        order_submission_attempt_id=attempt.id,
        business_request_key="order-lifecycle-pipeline-success",
        trace_id="trace-order-lifecycle-pipeline-success",
        trigger_source="test",
        order_status_gateway=status_gateway,
        fill_query_gateway=fill_gateway,
    )

    assert result.status == "succeeded"
    assert result.data["pipeline_action"] == "COMPLETE"
    assert result.data["lifecycle_action"] == "COMPLETE"
    assert result.data["poll_sequence"] == 1
    assert result.data["poll_mode"] == "closeout"
    assert result.data["scheduled_next_poll"] is False
    assert OrderStatusSyncRecord.objects.get().poll_sequence == 1
    assert FillSyncResult.objects.count() == 1
    assert TradeFill.objects.count() == 1
    assert OrderPlanActiveLock.objects.get(id=attempt.active_lock_id).status == ActiveLockStatus.RELEASED


def test_order_lifecycle_pipeline_uses_next_sequence_for_followup_check(settings) -> None:
    _enable(settings)
    prepared = _prepared(settings, key="lifecycle-pipeline-followup")
    submit_result = _submit(prepared, FakeBinanceOrderSubmissionGateway(), key="lifecycle-pipeline-followup")
    attempt = _make_due(OrderSubmissionAttempt.objects.get(id=submit_result.data["order_submission_attempt_id"]))
    first_status_gateway = FakeBinanceOrderStatusGateway(
        payload={
            "symbol": attempt.symbol,
            "orderId": attempt.exchange_order_id,
            "clientOrderId": attempt.client_order_id,
            "status": "NEW",
        }
    )
    second_status_gateway = FakeBinanceOrderStatusGateway(
        payload={
            "symbol": attempt.symbol,
            "orderId": attempt.exchange_order_id,
            "clientOrderId": attempt.client_order_id,
            "status": "CANCELED",
            "executedQty": "0",
            "cumQuote": "0",
        }
    )

    first = run_order_lifecycle_pipeline(
        order_submission_attempt_id=attempt.id,
        business_request_key="order-lifecycle-pipeline-followup",
        trace_id="trace-order-lifecycle-pipeline-followup-1",
        trigger_source="test",
        order_status_gateway=first_status_gateway,
        fill_query_gateway=FakeBinanceFillQueryGateway(),
    )
    second = run_order_lifecycle_pipeline(
        order_submission_attempt_id=attempt.id,
        business_request_key="order-lifecycle-pipeline-followup",
        trace_id="trace-order-lifecycle-pipeline-followup-2",
        trigger_source="test",
        order_status_gateway=second_status_gateway,
        fill_query_gateway=FakeBinanceFillQueryGateway(),
    )

    assert first.status == "no_action"
    assert first.data["pipeline_action"] == "STOP"
    assert first.data["poll_sequence"] == 1
    assert second.status == "succeeded"
    assert second.data["pipeline_action"] == "COMPLETE"
    assert second.data["poll_sequence"] == 2
    assert list(OrderStatusSyncRecord.objects.order_by("poll_sequence").values_list("poll_sequence", flat=True)) == [1, 2]
    assert FillSyncResult.objects.count() == 1
    assert TradeFill.objects.count() == 0
    assert OrderPlanActiveLock.objects.get(id=attempt.active_lock_id).status == ActiveLockStatus.RELEASED


def test_order_lifecycle_pipeline_never_resubmits_order(settings) -> None:
    _enable(settings)
    prepared = _prepared(settings, key="lifecycle-pipeline-no-resubmit")
    submit_result = _submit(prepared, FakeBinanceOrderSubmissionGateway(), key="lifecycle-pipeline-no-resubmit")
    attempt = _make_due(OrderSubmissionAttempt.objects.get(id=submit_result.data["order_submission_attempt_id"]))
    status_gateway = FakeBinanceOrderStatusGateway(
        payload={
            "symbol": attempt.symbol,
            "orderId": attempt.exchange_order_id,
            "clientOrderId": attempt.client_order_id,
            "status": "NEW",
        }
    )

    result = run_order_lifecycle_pipeline(
        order_submission_attempt_id=attempt.id,
        business_request_key="order-lifecycle-pipeline-no-resubmit",
        trace_id="trace-order-lifecycle-pipeline-no-resubmit",
        trigger_source="test",
        order_status_gateway=status_gateway,
        fill_query_gateway=FakeBinanceFillQueryGateway(),
    )

    assert result.status == "no_action"
    assert OrderSubmissionAttempt.objects.count() == 1
    assert OrderStatusSyncRecord.objects.count() == 1
    assert FillSyncResult.objects.count() == 0
