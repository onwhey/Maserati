from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.binance_gateway.fill_query import FakeBinanceFillQueryGateway
from apps.binance_gateway.order_cancel import FakeBinanceOrderCancelGateway
from apps.binance_gateway.order_status import FakeBinanceOrderStatusGateway
from apps.binance_gateway.order_submission import FakeBinanceOrderSubmissionGateway
from apps.binance_gateway.types import (
    ERROR_TIMEOUT,
    MARKET_TYPE_USDS_M,
    BinanceGatewayResult,
    endpoint_family_for_market,
)
from apps.execution.models import OrderSubmissionAttempt
from apps.fill_sync.models import FillSyncResult, OrderFillSummary
from apps.order_lifecycle.models import OrderCancelAttempt
from apps.order_lifecycle.services.closeout import closeout_limit_order
from apps.order_plan.models import ActiveLockStatus, OrderPlanActiveLock
from apps.order_status_sync.models import OrderStatusSyncRecord
from tests.test_execution_order_submission_stage5 import _prepared, _submit
from tests.test_fill_sync_stage5 import _enable


pytestmark = pytest.mark.django_db


def _limit_attempt(settings, *, key: str) -> tuple[OrderSubmissionAttempt, object]:
    valid_until = timezone.now() + timedelta(hours=3, minutes=50)
    prepared = _prepared(
        settings,
        key=key,
        limit_condition={
            "order_type": "LIMIT",
            "limit_price": "49000",
            "limit_valid_until_utc": valid_until.isoformat(),
            "time_in_force": "GTC",
            "price_condition_hash": f"limit-condition-{key}",
        },
    )
    submit_result = _submit(prepared, FakeBinanceOrderSubmissionGateway(), key=key)
    return OrderSubmissionAttempt.objects.get(id=submit_result.data["order_submission_attempt_id"]), valid_until


def _closeout(
    attempt: OrderSubmissionAttempt,
    valid_until,
    cancel_gateway: FakeBinanceOrderCancelGateway,
    *,
    key: str,
    status_gateway: FakeBinanceOrderStatusGateway | None = None,
    fill_gateway: FakeBinanceFillQueryGateway | None = None,
):
    return closeout_limit_order(
        order_submission_attempt_id=attempt.id,
        business_request_key=f"order-cycle-closeout-{key}",
        closeout_time_utc=valid_until + timedelta(minutes=5),
        trace_id=f"trace-order-cycle-closeout-{key}",
        trigger_source="test",
        cancel_gateway=cancel_gateway,
        order_status_gateway=status_gateway
        or FakeBinanceOrderStatusGateway(
            payload={
                "symbol": attempt.symbol,
                "orderId": attempt.exchange_order_id,
                "clientOrderId": attempt.client_order_id,
                "status": "CANCELED",
                "executedQty": "0",
                "cumQuote": "0",
            }
        ),
        fill_query_gateway=fill_gateway or FakeBinanceFillQueryGateway(),
    )


def _unknown_cancel_result() -> BinanceGatewayResult:
    return BinanceGatewayResult(
        operation="cancel_order",
        market_type=MARKET_TYPE_USDS_M,
        endpoint_family=endpoint_family_for_market(MARKET_TYPE_USDS_M),
        success=False,
        request_sent=True,
        response_received=False,
        error_category=ERROR_TIMEOUT,
        sanitized_error_message=ERROR_TIMEOUT,
        attempt_count=1,
        trace_id="trace-order-cycle-closeout",
    )


def test_closeout_expired_limit_order_cancels_then_runs_status_and_fill_sync(settings) -> None:
    _enable(settings)
    attempt, valid_until = _limit_attempt(settings, key="accepted")
    cancel_gateway = FakeBinanceOrderCancelGateway()

    result = _closeout(attempt, valid_until, cancel_gateway, key="accepted")

    cancel = OrderCancelAttempt.objects.get()
    assert result.status == "succeeded"
    assert result.data["closeout_action"] == "CONTINUE_TO_ORDER_LIFECYCLE_SYNC"
    assert cancel.cancel_status == "accepted"
    assert cancel.reason_code == "order_cancel_accepted"
    assert cancel.request_sent is True
    assert len(cancel_gateway.calls) == 1
    assert OrderStatusSyncRecord.objects.get().exchange_status == "CANCELED"
    assert FillSyncResult.objects.get().status == "synced_empty"
    assert OrderFillSummary.objects.get().status == "empty"
    assert OrderPlanActiveLock.objects.get(id=attempt.active_lock_id).status == ActiveLockStatus.RELEASED


def test_closeout_cancel_request_uses_only_cancel_identity(settings) -> None:
    _enable(settings)
    attempt, valid_until = _limit_attempt(settings, key="field-allowlist")
    cancel_gateway = FakeBinanceOrderCancelGateway()

    _closeout(attempt, valid_until, cancel_gateway, key="field-allowlist")

    frozen = cancel_gateway.calls[0]["frozen_cancel_request"]
    assert frozen["symbol"] == attempt.symbol
    assert frozen["origClientOrderId"] == attempt.client_order_id
    assert frozen["orderId"] == attempt.exchange_order_id
    for forbidden in {"quantity", "price", "side", "newClientOrderId", "timeInForce", "leverage", "marginType", "positionMode", "type"}:
        assert forbidden not in frozen


def test_closeout_market_order_is_no_action_without_cancel_attempt(settings) -> None:
    _enable(settings)
    prepared = _prepared(settings, key="market-no-closeout")
    submit_result = _submit(prepared, FakeBinanceOrderSubmissionGateway(), key="market-no-closeout")
    attempt = OrderSubmissionAttempt.objects.get(id=submit_result.data["order_submission_attempt_id"])
    cancel_gateway = FakeBinanceOrderCancelGateway()

    result = closeout_limit_order(
        order_submission_attempt_id=attempt.id,
        business_request_key="order-cycle-closeout-market",
        closeout_time_utc=timezone.now() + timedelta(hours=4),
        trace_id="trace-order-cycle-closeout-market",
        trigger_source="test",
        cancel_gateway=cancel_gateway,
    )

    assert result.status == "no_action"
    assert result.reason_code == "not_limit_order"
    assert OrderCancelAttempt.objects.count() == 0
    assert cancel_gateway.calls == []
    assert OrderPlanActiveLock.objects.get(id=attempt.active_lock_id).status == ActiveLockStatus.ACTIVE


def test_closeout_not_expired_limit_order_does_not_cancel(settings) -> None:
    _enable(settings)
    attempt, valid_until = _limit_attempt(settings, key="not-expired")
    cancel_gateway = FakeBinanceOrderCancelGateway()

    result = closeout_limit_order(
        order_submission_attempt_id=attempt.id,
        business_request_key="order-cycle-closeout-not-expired",
        closeout_time_utc=valid_until - timedelta(seconds=1),
        trace_id="trace-order-cycle-closeout-not-expired",
        trigger_source="test",
        cancel_gateway=cancel_gateway,
    )

    assert result.status == "no_action"
    assert result.reason_code == "limit_order_not_expired"
    assert OrderCancelAttempt.objects.count() == 0
    assert cancel_gateway.calls == []


def test_closeout_is_idempotent_and_does_not_cancel_twice(settings) -> None:
    _enable(settings)
    attempt, valid_until = _limit_attempt(settings, key="idempotent")
    first_gateway = FakeBinanceOrderCancelGateway()
    second_gateway = FakeBinanceOrderCancelGateway()

    first = _closeout(attempt, valid_until, first_gateway, key="idempotent")
    second = _closeout(attempt, valid_until, second_gateway, key="idempotent")

    assert first.status == "succeeded"
    assert second.reason_code == "order_cancel_idempotent_replay"
    assert OrderCancelAttempt.objects.count() == 1
    assert len(first_gateway.calls) == 1
    assert second_gateway.calls == []


def test_unknown_cancel_keeps_lock_and_replay_does_not_retry_cancel(settings) -> None:
    _enable(settings)
    attempt, valid_until = _limit_attempt(settings, key="unknown")
    first_gateway = FakeBinanceOrderCancelGateway(result=_unknown_cancel_result())
    second_gateway = FakeBinanceOrderCancelGateway()
    status_gateway = FakeBinanceOrderStatusGateway(
        payload={
            "symbol": attempt.symbol,
            "orderId": attempt.exchange_order_id,
            "clientOrderId": attempt.client_order_id,
            "status": "NEW",
        }
    )

    first = _closeout(
        attempt,
        valid_until,
        first_gateway,
        key="unknown",
        status_gateway=status_gateway,
        fill_gateway=FakeBinanceFillQueryGateway(),
    )
    second = _closeout(attempt, valid_until, second_gateway, key="unknown")

    cancel = OrderCancelAttempt.objects.get()
    assert first.status == "unknown"
    assert cancel.cancel_status == "unknown"
    assert cancel.reason_code == "order_cancel_unknown"
    assert second.reason_code == "order_cancel_idempotent_replay"
    assert len(first_gateway.calls) == 1
    assert second_gateway.calls == []
    assert OrderStatusSyncRecord.objects.get().is_terminal_status is False
    assert FillSyncResult.objects.count() == 0
    assert OrderPlanActiveLock.objects.get(id=attempt.active_lock_id).status == ActiveLockStatus.ACTIVE
