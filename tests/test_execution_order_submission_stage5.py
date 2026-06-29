from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.alerts.models import AlertEvent, AlertSeverity
from apps.binance_gateway.order_submission import FakeBinanceOrderSubmissionGateway, HttpBinanceOrderSubmissionGateway
from apps.binance_gateway.types import (
    ERROR_BINANCE_REJECTED,
    ERROR_GATEWAY_DISABLED,
    ERROR_TIMEOUT,
    MARKET_TYPE_USDS_M,
    BinanceGatewayCallContext,
    BinanceGatewayResult,
    endpoint_family_for_market,
)
from apps.execution.models import OrderSubmissionAttempt, OrderSubmissionAttemptStatus
from apps.execution.services.submission import submit_prepared_order
from apps.execution_preparation.models import PreparedOrderIntent, PreparedOrderIntentStatus
from apps.order_plan.models import ActiveLockStatus, OrderPlanActiveLock
from tests.test_execution_preparation_stage4 import _approved, _gateway, _prepare


pytestmark = pytest.mark.django_db


def _prepared(settings, *, key: str = "submission", limit_condition: dict | None = None) -> PreparedOrderIntent:
    approved = _approved(settings, ratio="0.5", price_value="50000", key=key, limit_condition=limit_condition)
    result = _prepare(approved, _gateway(bid="49990", ask="50010"), key=key)
    assert result.status == "succeeded"
    return PreparedOrderIntent.objects.get()


def _submit(prepared: PreparedOrderIntent, gateway: FakeBinanceOrderSubmissionGateway, *, key: str = "submission"):
    return submit_prepared_order(
        prepared_order_intent_id=prepared.id,
        business_request_key=f"order-submission-{key}",
        trace_id=f"trace-order-submission-{key}",
        trigger_source="test",
        gateway=gateway,
    )


def _gateway_result(
    *,
    success: bool,
    request_sent: bool,
    response_received: bool,
    error_category: str = "",
    attempt_count: int = 1,
    payload: dict | None = None,
):
    return BinanceGatewayResult(
        operation="submit_order",
        market_type=MARKET_TYPE_USDS_M,
        endpoint_family=endpoint_family_for_market(MARKET_TYPE_USDS_M),
        success=success,
        payload=payload,
        request_sent=request_sent,
        response_received=response_received,
        error_category=error_category,
        sanitized_error_message=error_category,
        attempt_count=attempt_count,
        trace_id="trace-order-submission",
    )


def test_submit_prepared_order_accepts_once_and_keeps_active_lock(settings) -> None:
    prepared = _prepared(settings, key="accepted")
    gateway = FakeBinanceOrderSubmissionGateway()

    result = _submit(prepared, gateway, key="accepted")

    attempt = OrderSubmissionAttempt.objects.get()
    prepared.refresh_from_db()
    lock = OrderPlanActiveLock.objects.get(id=attempt.active_lock_id)
    assert result.status == "succeeded"
    assert result.data["order_submission_attempt_id"] == attempt.id
    assert attempt.status == OrderSubmissionAttemptStatus.ACCEPTED
    assert "flow_action" not in result.data
    assert attempt.request_sent is True
    assert attempt.response_received is True
    assert attempt.gateway_attempt_count == 1
    assert attempt.exchange_order_id == "123456"
    assert attempt.exchange_client_order_id == prepared.client_order_id
    assert prepared.status == PreparedOrderIntentStatus.SUBMITTED
    assert lock.status == ActiveLockStatus.ACTIVE
    assert len(gateway.calls) == 1

    frozen = gateway.calls[0]["frozen_order_request"]
    assert frozen["newClientOrderId"] == prepared.client_order_id
    assert frozen["type"] == "MARKET"
    assert "price" not in frozen
    assert "stopPrice" not in frozen
    assert "timeInForce" not in frozen
    assert "idempotency_key" not in frozen
    assert gateway.calls[0]["call_context"].metadata["order_submission_attempt_id"] == attempt.id
    assert AlertEvent.objects.filter(source_module="Execution", event_type="order_submission_accepted").count() == 1


def test_submit_limit_order_sends_frozen_price_and_time_in_force(settings) -> None:
    valid_until = timezone.now() + timedelta(hours=3, minutes=50)
    prepared = _prepared(
        settings,
        key="limit-accepted",
        limit_condition={
            "order_type": "LIMIT",
            "limit_price": "49000",
            "limit_valid_until_utc": valid_until.isoformat(),
            "time_in_force": "GTC",
            "price_condition_hash": "limit-condition-hash",
        },
    )
    gateway = FakeBinanceOrderSubmissionGateway()

    result = _submit(prepared, gateway, key="limit-accepted")

    attempt = OrderSubmissionAttempt.objects.get()
    frozen = gateway.calls[0]["frozen_order_request"]
    assert result.status == "succeeded"
    assert len(gateway.calls) == 1
    assert attempt.order_type == "LIMIT"
    assert attempt.time_in_force == "GTC"
    assert attempt.limit_price == Decimal("49000")
    assert attempt.limit_valid_until_utc == valid_until
    assert attempt.price_condition_hash == "limit-condition-hash"
    assert attempt.order_notional == prepared.quantity * Decimal("49000")
    assert frozen["type"] == "LIMIT"
    assert frozen["price"] == "49000"
    assert frozen["timeInForce"] == "GTC"
    assert "idempotency_key" not in frozen
    assert "stopPrice" not in frozen


def test_submit_replay_returns_existing_attempt_without_second_gateway_call(settings) -> None:
    prepared = _prepared(settings, key="replay")
    first_gateway = FakeBinanceOrderSubmissionGateway()
    second_gateway = FakeBinanceOrderSubmissionGateway()

    first = _submit(prepared, first_gateway, key="replay")
    second = _submit(prepared, second_gateway, key="replay-second")

    assert first.status == "succeeded"
    assert second.status == "succeeded"
    assert first.data["order_submission_attempt_id"] == second.data["order_submission_attempt_id"]
    assert OrderSubmissionAttempt.objects.count() == 1
    assert len(first_gateway.calls) == 1
    assert second_gateway.calls == []
    assert AlertEvent.objects.filter(source_module="Execution", event_type="order_submission_idempotent_replay").count() == 1


def test_expired_prepared_order_blocks_before_submit_and_releases_lock(settings) -> None:
    prepared = _prepared(settings, key="expired")
    PreparedOrderIntent.objects.filter(id=prepared.id).update(expires_at_utc=timezone.now() - timedelta(seconds=1))
    prepared.refresh_from_db()
    gateway = FakeBinanceOrderSubmissionGateway()

    result = _submit(prepared, gateway, key="expired")

    attempt = OrderSubmissionAttempt.objects.get()
    prepared.refresh_from_db()
    lock = OrderPlanActiveLock.objects.get(id=attempt.active_lock_id)
    assert result.status == "blocked"
    assert attempt.status == OrderSubmissionAttemptStatus.BLOCKED_BEFORE_SUBMIT
    assert attempt.request_sent is False
    assert gateway.calls == []
    assert prepared.status == PreparedOrderIntentStatus.SUBMISSION_BLOCKED
    assert lock.status == ActiveLockStatus.RELEASED
    assert AlertEvent.objects.filter(source_module="Execution", event_type="order_submission_blocked_before_submit").count() == 1


def test_explicit_binance_rejection_releases_lock(settings) -> None:
    prepared = _prepared(settings, key="rejected")
    gateway = FakeBinanceOrderSubmissionGateway(
        result=_gateway_result(
            success=False,
            request_sent=True,
            response_received=True,
            error_category=ERROR_BINANCE_REJECTED,
            payload={"code": "-2019", "msg": "Margin is insufficient."},
        )
    )

    result = _submit(prepared, gateway, key="rejected")

    attempt = OrderSubmissionAttempt.objects.get()
    prepared.refresh_from_db()
    lock = OrderPlanActiveLock.objects.get(id=attempt.active_lock_id)
    assert result.status == "blocked"
    assert attempt.status == OrderSubmissionAttemptStatus.REJECTED
    assert attempt.request_sent is True
    assert attempt.response_received is True
    assert prepared.status == PreparedOrderIntentStatus.SUBMISSION_REJECTED
    assert lock.status == ActiveLockStatus.RELEASED
    assert AlertEvent.objects.filter(source_module="Execution", event_type="order_submission_rejected").count() == 1


def test_unknown_submission_keeps_active_lock_for_order_status_sync(settings) -> None:
    prepared = _prepared(settings, key="unknown")
    gateway = FakeBinanceOrderSubmissionGateway(
        result=_gateway_result(
            success=False,
            request_sent=True,
            response_received=False,
            error_category=ERROR_TIMEOUT,
        )
    )

    result = _submit(prepared, gateway, key="unknown")

    attempt = OrderSubmissionAttempt.objects.get()
    prepared.refresh_from_db()
    lock = OrderPlanActiveLock.objects.get(id=attempt.active_lock_id)
    assert result.status == "unknown"
    assert result.data["allows_order_status_sync"] is True
    assert "flow_action" not in result.data
    assert attempt.status == OrderSubmissionAttemptStatus.UNKNOWN
    assert prepared.status == PreparedOrderIntentStatus.SUBMISSION_UNKNOWN
    assert lock.status == ActiveLockStatus.ACTIVE
    assert AlertEvent.objects.filter(source_module="Execution", event_type="order_submission_unknown").count() == 1


def test_gateway_contract_violation_is_unknown_and_critical(settings) -> None:
    prepared = _prepared(settings, key="contract-violation")
    gateway = FakeBinanceOrderSubmissionGateway(
        result=_gateway_result(
            success=True,
            request_sent=True,
            response_received=True,
            attempt_count=2,
            payload={"orderId": 999, "clientOrderId": prepared.client_order_id, "status": "NEW"},
        )
    )

    result = _submit(prepared, gateway, key="contract-violation")

    attempt = OrderSubmissionAttempt.objects.get()
    alert = AlertEvent.objects.get(source_module="Execution", event_type="order_submission_gateway_contract_violation")
    assert result.status == "unknown"
    assert attempt.status == OrderSubmissionAttemptStatus.UNKNOWN
    assert attempt.reason_code == "gateway_contract_violation"
    assert alert.severity == AlertSeverity.CRITICAL
    assert OrderPlanActiveLock.objects.get(id=attempt.active_lock_id).status == ActiveLockStatus.ACTIVE


def test_gateway_before_send_failure_marks_failed_before_submit_and_releases_lock(settings) -> None:
    prepared = _prepared(settings, key="gateway-disabled")
    gateway = FakeBinanceOrderSubmissionGateway(
        result=_gateway_result(
            success=False,
            request_sent=False,
            response_received=False,
            error_category=ERROR_GATEWAY_DISABLED,
            attempt_count=0,
        )
    )

    result = _submit(prepared, gateway, key="gateway-disabled")

    attempt = OrderSubmissionAttempt.objects.get()
    prepared.refresh_from_db()
    assert result.status == "failed"
    assert attempt.status == OrderSubmissionAttemptStatus.FAILED_BEFORE_SUBMIT
    assert attempt.request_sent is False
    assert prepared.status == PreparedOrderIntentStatus.SUBMISSION_FAILED
    assert OrderPlanActiveLock.objects.get(id=attempt.active_lock_id).status == ActiveLockStatus.RELEASED
    assert AlertEvent.objects.filter(source_module="Execution", event_type="order_submission_failed_before_submit").count() == 1


def test_http_gateway_unexpected_send_error_is_conservative_unknown_boundary(settings, monkeypatch) -> None:
    settings.BINANCE_GATEWAY_ENABLED = True
    settings.BINANCE_ORDER_SUBMISSION_ENABLED = True
    settings.ALLOW_REAL_EXTERNAL_SERVICES = True
    settings.DEPLOYMENT_REAL_TRADING_ENABLED = True
    settings.ACTIVE_MARKET_TYPE = "USDS-M"
    settings.ACTIVE_ACCOUNT_DOMAIN = "default"
    settings.BINANCE_USDS_M_BASE_URL = "https://example.invalid"
    settings.BINANCE_USDS_M_TRADE_API_KEY = "test-key"
    settings.BINANCE_USDS_M_TRADE_API_SECRET = "test-secret"
    calls = {"count": 0}

    def explode(*args, **kwargs):
        calls["count"] += 1
        raise RuntimeError("socket exploded")

    monkeypatch.setattr("apps.binance_gateway.order_submission.urllib.request.urlopen", explode)

    result = HttpBinanceOrderSubmissionGateway().submit_order(
        market_type=MARKET_TYPE_USDS_M,
        frozen_order_request={
            "symbol": "BTCUSDT",
            "side": "BUY",
            "type": "MARKET",
            "quantity": "0.01",
            "newClientOrderId": "tc-test-client-order",
            "reduceOnly": False,
        },
        call_context=BinanceGatewayCallContext(
            trace_id="trace-http-gateway",
            trigger_source="test",
            operation="submit_order",
            market_type=MARKET_TYPE_USDS_M,
            account_domain="default",
            symbol="BTCUSDT",
        ),
    )

    assert calls["count"] == 1
    assert result.success is False
    assert result.request_sent is True
    assert result.response_received is False
    assert result.attempt_count == 1
