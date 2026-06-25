from __future__ import annotations

from datetime import timedelta

import apps.binance_gateway.order_status as order_status_gateway
import pytest
from django.utils import timezone

from apps.alerts.models import AlertEvent, AlertSeverity
from apps.binance_gateway.order_submission import FakeBinanceOrderSubmissionGateway
from apps.binance_gateway.order_status import FakeBinanceOrderStatusGateway, HttpBinanceOrderStatusGateway
from apps.binance_gateway.types import ERROR_BINANCE_REJECTED, ERROR_TIMEOUT, MARKET_TYPE_USDS_M, BinanceGatewayCallContext
from apps.execution.models import OrderSubmissionAttempt, OrderSubmissionAttemptStatus
from apps.order_plan.models import ActiveLockStatus, OrderPlanActiveLock
from apps.order_status_sync.models import OrderStatusSyncRecord
from apps.order_status_sync.services.status_sync import poll_order_status
from tests.test_execution_order_submission_stage5 import _gateway_result, _prepared, _submit


pytestmark = pytest.mark.django_db


def _enable(settings) -> None:
    settings.ORDER_STATUS_SYNC_ENABLED = True
    settings.ORDER_STATUS_POLL_INTERVAL_SECONDS = 2
    settings.ORDER_STATUS_POLL_MAX_DURATION_SECONDS = 30


def _make_due(attempt: OrderSubmissionAttempt) -> OrderSubmissionAttempt:
    OrderSubmissionAttempt.objects.filter(id=attempt.id).update(finished_at_utc=timezone.now() - timedelta(seconds=2))
    attempt.refresh_from_db()
    return attempt


def _poll(attempt: OrderSubmissionAttempt, gateway: FakeBinanceOrderStatusGateway, *, key: str):
    return poll_order_status(
        order_submission_attempt_id=attempt.id,
        business_request_key=f"order-status-{key}",
        poll_sequence=1,
        trace_id=f"trace-order-status-{key}",
        trigger_source="test",
        gateway=gateway,
    )


def test_terminal_order_status_creates_record_and_does_not_release_lock(settings) -> None:
    _enable(settings)
    prepared = _prepared(settings, key="status-terminal")
    submit_result = _submit(prepared, FakeBinanceOrderSubmissionGateway(), key="status-terminal")
    attempt = _make_due(OrderSubmissionAttempt.objects.get(id=submit_result.data["order_submission_attempt_id"]))
    gateway = FakeBinanceOrderStatusGateway(
        payload={
            "symbol": attempt.symbol,
            "orderId": attempt.exchange_order_id,
            "clientOrderId": attempt.client_order_id,
            "status": "FILLED",
        }
    )

    result = _poll(attempt, gateway, key="terminal")

    record = OrderStatusSyncRecord.objects.get()
    attempt.refresh_from_db()
    assert result.status == "succeeded"
    assert result.data["allows_fill_sync"] is True
    assert result.data["flow_action"] == "CONTINUE"
    assert record.query_outcome == "found"
    assert record.is_terminal_status is True
    assert record.submission_resolution_status == "terminal_confirmed"
    assert attempt.status == OrderSubmissionAttemptStatus.ACCEPTED
    assert OrderPlanActiveLock.objects.get(id=attempt.active_lock_id).status == ActiveLockStatus.ACTIVE
    assert gateway.calls[0]["call_context"].business_object_type == "OrderSubmissionAttempt"
    assert AlertEvent.objects.filter(source_module="OrderStatusSync", event_type="order_status_sync_terminal").count() == 1


def test_non_terminal_status_waits_for_next_poll_without_fill_sync(settings) -> None:
    _enable(settings)
    prepared = _prepared(settings, key="status-new")
    submit_result = _submit(prepared, FakeBinanceOrderSubmissionGateway(), key="status-new")
    attempt = _make_due(OrderSubmissionAttempt.objects.get(id=submit_result.data["order_submission_attempt_id"]))
    gateway = FakeBinanceOrderStatusGateway(
        payload={"symbol": attempt.symbol, "orderId": attempt.exchange_order_id, "clientOrderId": attempt.client_order_id, "status": "NEW"}
    )

    result = _poll(attempt, gateway, key="new")

    record = OrderStatusSyncRecord.objects.get()
    assert result.status == "no_action"
    assert result.data["flow_action"] == "WAIT"
    assert result.data["allows_fill_sync"] is False
    assert record.query_outcome == "found"
    assert record.is_terminal_status is False
    assert record.submission_resolution_status == "order_found"
    assert OrderPlanActiveLock.objects.get(id=attempt.active_lock_id).status == ActiveLockStatus.ACTIVE


def test_same_poll_sequence_replays_existing_record_without_second_gateway_call(settings) -> None:
    _enable(settings)
    prepared = _prepared(settings, key="status-replay")
    submit_result = _submit(prepared, FakeBinanceOrderSubmissionGateway(), key="status-replay")
    attempt = _make_due(OrderSubmissionAttempt.objects.get(id=submit_result.data["order_submission_attempt_id"]))
    first_gateway = FakeBinanceOrderStatusGateway(
        payload={"symbol": attempt.symbol, "orderId": attempt.exchange_order_id, "clientOrderId": attempt.client_order_id, "status": "NEW"}
    )
    second_gateway = FakeBinanceOrderStatusGateway(payload={"symbol": attempt.symbol, "status": "FILLED"})

    first = _poll(attempt, first_gateway, key="replay")
    second = _poll(attempt, second_gateway, key="replay")

    assert first.data["order_status_sync_record_id"] == second.data["order_status_sync_record_id"]
    assert second.reason_code == "order_status_sync_idempotent_replay"
    assert OrderStatusSyncRecord.objects.count() == 1
    assert len(first_gateway.calls) == 1
    assert second_gateway.calls == []


def test_rejected_submission_is_not_queryable_and_does_not_call_gateway(settings) -> None:
    _enable(settings)
    prepared = _prepared(settings, key="status-rejected")
    submit_result = _submit(
        prepared,
        FakeBinanceOrderSubmissionGateway(
            result=_gateway_result(
                success=False,
                request_sent=True,
                response_received=True,
                error_category=ERROR_BINANCE_REJECTED,
                payload={"code": "-2019", "msg": "Margin is insufficient."},
            )
        ),
        key="status-rejected",
    )
    attempt = _make_due(OrderSubmissionAttempt.objects.get(id=submit_result.data["order_submission_attempt_id"]))
    gateway = FakeBinanceOrderStatusGateway()

    result = _poll(attempt, gateway, key="rejected")

    record = OrderStatusSyncRecord.objects.get()
    assert result.status == "blocked"
    assert record.query_outcome == "blocked_before_query"
    assert record.reason_code == "submission_status_not_queryable"
    assert gateway.calls == []


def test_unknown_submission_not_found_stays_unresolved_and_keeps_lock(settings) -> None:
    _enable(settings)
    prepared = _prepared(settings, key="status-not-found")
    submit_result = _submit(
        prepared,
        FakeBinanceOrderSubmissionGateway(result=_gateway_result(success=False, request_sent=True, response_received=False, error_category=ERROR_TIMEOUT)),
        key="status-not-found",
    )
    attempt = _make_due(OrderSubmissionAttempt.objects.get(id=submit_result.data["order_submission_attempt_id"]))
    gateway = FakeBinanceOrderStatusGateway(not_found=True)

    result = _poll(attempt, gateway, key="not-found")

    record = OrderStatusSyncRecord.objects.get()
    attempt.refresh_from_db()
    assert result.status == "unknown"
    assert result.data["allows_fill_sync"] is False
    assert record.query_outcome == "not_found"
    assert record.submission_resolution_status == "unresolved"
    assert attempt.status == OrderSubmissionAttemptStatus.UNKNOWN
    assert OrderPlanActiveLock.objects.get(id=attempt.active_lock_id).status == ActiveLockStatus.ACTIVE


def test_unknown_exchange_status_is_critical_and_not_terminal(settings) -> None:
    _enable(settings)
    prepared = _prepared(settings, key="status-unknown-exchange")
    submit_result = _submit(prepared, FakeBinanceOrderSubmissionGateway(), key="status-unknown-exchange")
    attempt = _make_due(OrderSubmissionAttempt.objects.get(id=submit_result.data["order_submission_attempt_id"]))
    gateway = FakeBinanceOrderStatusGateway(
        payload={"symbol": attempt.symbol, "orderId": attempt.exchange_order_id, "clientOrderId": attempt.client_order_id, "status": "PENDING_NEW"}
    )

    result = _poll(attempt, gateway, key="unknown-exchange")

    record = OrderStatusSyncRecord.objects.get()
    alert = AlertEvent.objects.get(source_module="OrderStatusSync", event_type="order_status_sync_unknown_status")
    assert result.status == "unknown"
    assert record.query_outcome == "unknown"
    assert record.reason_code == "unsupported_exchange_status"
    assert record.is_terminal_status is False
    assert alert.severity == AlertSeverity.CRITICAL


def test_poll_before_due_time_does_not_create_record_or_call_gateway(settings) -> None:
    _enable(settings)
    prepared = _prepared(settings, key="status-not-due")
    submit_result = _submit(prepared, FakeBinanceOrderSubmissionGateway(), key="status-not-due")
    attempt = OrderSubmissionAttempt.objects.get(id=submit_result.data["order_submission_attempt_id"])
    gateway = FakeBinanceOrderStatusGateway()

    result = _poll(attempt, gateway, key="not-due")

    assert result.status == "no_action"
    assert result.reason_code == "poll_not_due"
    assert result.data["flow_action"] == "WAIT"
    assert OrderStatusSyncRecord.objects.count() == 0
    assert gateway.calls == []


def test_polling_timeout_writes_alert_without_fake_record_or_gateway(settings) -> None:
    _enable(settings)
    prepared = _prepared(settings, key="status-timeout")
    submit_result = _submit(prepared, FakeBinanceOrderSubmissionGateway(), key="status-timeout")
    attempt = _make_due(OrderSubmissionAttempt.objects.get(id=submit_result.data["order_submission_attempt_id"]))
    gateway = FakeBinanceOrderStatusGateway()

    result = poll_order_status(
        order_submission_attempt_id=attempt.id,
        business_request_key="order-status-timeout",
        poll_sequence=16,
        trace_id="trace-order-status-timeout",
        trigger_source="test",
        gateway=gateway,
    )

    assert result.status == "unknown"
    assert result.reason_code == "polling_timeout"
    assert result.data["flow_action"] == "STOP"
    assert OrderStatusSyncRecord.objects.count() == 0
    assert gateway.calls == []
    assert AlertEvent.objects.filter(source_module="OrderStatusSync", event_type="order_status_polling_timeout").count() == 1


def test_existing_in_progress_poll_waits_without_idempotent_replay_alert(settings) -> None:
    _enable(settings)
    prepared = _prepared(settings, key="status-in-progress")
    submit_result = _submit(prepared, FakeBinanceOrderSubmissionGateway(), key="status-in-progress")
    attempt = _make_due(OrderSubmissionAttempt.objects.get(id=submit_result.data["order_submission_attempt_id"]))
    first_gateway = FakeBinanceOrderStatusGateway(
        payload={"symbol": attempt.symbol, "orderId": attempt.exchange_order_id, "clientOrderId": attempt.client_order_id, "status": "NEW"}
    )
    first = _poll(attempt, first_gateway, key="in-progress")
    OrderStatusSyncRecord.objects.filter(id=first.data["order_status_sync_record_id"]).update(query_finished_at_utc=None)
    second_gateway = FakeBinanceOrderStatusGateway(payload={"symbol": attempt.symbol, "status": "FILLED"})

    second = _poll(attempt, second_gateway, key="in-progress")

    assert second.status == "no_action"
    assert second.reason_code == "poll_in_progress"
    assert second.data["flow_action"] == "WAIT"
    assert second_gateway.calls == []
    assert AlertEvent.objects.filter(source_module="OrderStatusSync", event_type="order_status_sync_idempotent_replay").count() == 0


def test_http_order_status_gateway_regenerates_signed_url_for_safe_read_retry(settings, monkeypatch) -> None:
    settings.BINANCE_GATEWAY_ENABLED = True
    settings.BINANCE_ORDER_STATUS_QUERY_ENABLED = True
    settings.ALLOW_REAL_EXTERNAL_SERVICES = True
    settings.ACTIVE_ACCOUNT_DOMAIN = "default"
    settings.BINANCE_USDS_M_BASE_URL = "https://example.invalid"
    settings.BINANCE_USDS_M_READ_API_KEY = "read-key"
    settings.BINANCE_USDS_M_READ_API_SECRET = "read-secret"
    settings.BINANCE_SAFE_READ_MAX_ATTEMPTS = 2
    build_calls: list[str] = []
    opened_urls: list[str] = []

    def fake_build(**kwargs):
        build_calls.append(kwargs["client_order_id"])
        return f"https://example.invalid/order?attempt={len(build_calls)}"

    class FakeResponse:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return b'{"symbol":"BTCUSDT","orderId":123,"clientOrderId":"cid-1","status":"NEW"}'

    def fake_urlopen(request, timeout):
        opened_urls.append(request.full_url)
        if len(opened_urls) == 1:
            raise TimeoutError("temporary timeout")
        return FakeResponse()

    monkeypatch.setattr(order_status_gateway, "build_signed_order_status_url", fake_build)
    monkeypatch.setattr(order_status_gateway.urllib.request, "urlopen", fake_urlopen)

    result = HttpBinanceOrderStatusGateway().query_order(
        market_type=MARKET_TYPE_USDS_M,
        symbol="BTCUSDT",
        client_order_id="cid-1",
        call_context=BinanceGatewayCallContext(
            trace_id="trace-gateway-retry",
            trigger_source="test",
            operation="query_order",
            market_type=MARKET_TYPE_USDS_M,
            account_domain="default",
            symbol="BTCUSDT",
        ),
    )

    assert result.success is True
    assert result.attempt_count == 2
    assert len(build_calls) == 2
    assert opened_urls == ["https://example.invalid/order?attempt=1", "https://example.invalid/order?attempt=2"]
