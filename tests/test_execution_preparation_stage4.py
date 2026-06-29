from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest
from django.db import IntegrityError
from django.utils import timezone

from apps.alerts.models import AlertEvent
from apps.binance_gateway.public_market import FakeBinancePublicMarketGateway
from apps.binance_gateway.types import MARKET_TYPE_USDS_M
from apps.execution_preparation.models import (
    ExecutionPreparationResult,
    ExecutionPreparationStatus,
    PreparedOrderIntent,
    PreparedOrderIntentStatus,
)
from apps.execution_preparation.services.preparation import prepare_execution
from apps.order_plan.models import ActiveLockStatus, OrderPlan, OrderPlanActiveLock
from apps.order_plan.services.active_lock import release_for_pre_execution_stop
from apps.risk_check.models import ApprovedOrderIntent, ApprovedOrderIntentStatus
from apps.risk_check.services.check import run_risk_check
from tests.test_order_plan_stage4 import _price
from tests.test_risk_check_stage4 import _account_facts, _order_plan


pytestmark = pytest.mark.django_db


def _enable_execution_preparation(settings) -> None:
    settings.EXECUTION_PREPARATION_ENABLED = True
    settings.EXECUTION_PREPARATION_MAX_PRICE_DEVIATION_BPS = 100
    settings.PREPARED_ORDER_INTENT_TTL_SECONDS = 30
    settings.EXECUTION_PREPARATION_SUPPORTED_ORDER_TYPES = ["MARKET"]
    settings.EXECUTION_PREPARATION_SUPPORTED_POSITION_MODE = "one_way"


def _approved(
    settings,
    *,
    ratio: str = "0.5",
    price_value: str = "50000",
    position: str = "0",
    available: str = "1000",
    key: str = "approved",
    limit_condition: dict | None = None,
):
    _enable_execution_preparation(settings)
    if limit_condition is not None:
        settings.ORDER_PLAN_SUPPORTED_ORDER_TYPES = ["MARKET", "LIMIT"]
        settings.EXECUTION_PREPARATION_SUPPORTED_ORDER_TYPES = ["MARKET", "LIMIT"]
    account = _account_facts(
        position=position,
        equity="1000",
        available=available,
        leverage="20",
        order_types=["MARKET", "LIMIT"] if limit_condition is not None else None,
    )
    price = _price(value=price_value)
    _order_plan(
        settings=settings,
        ratio=ratio,
        account=account,
        price=price,
        key=key,
        decision_calculation_snapshot={"frozen_trade_price_condition": limit_condition} if limit_condition is not None else None,
    )
    candidate = ApprovedOrderIntent.objects.first()
    if candidate is None:
        primary = OrderPlan.objects.get().candidate_intents.get(intent_role="primary")
        plan = primary.order_plan
        run_risk_check(
            business_request_key=f"risk-{key}",
            order_plan_id=plan.id,
            candidate_order_intent_id=primary.id,
            binance_sync_run_id=plan.binance_sync_run_id,
            price_snapshot_id=plan.price_snapshot_id,
            active_lock_id=plan.active_lock_id,
            reference_time_utc=timezone.now(),
            risk_rule_set="p0_default",
            trace_id=f"trace-risk-{key}",
            trigger_source="test",
        )
    return ApprovedOrderIntent.objects.get()


def _gateway(*, bid: str = "49990", ask: str = "50010", symbol: str = "BTCUSDT", fail: bool = False) -> FakeBinancePublicMarketGateway:
    return FakeBinancePublicMarketGateway(
        book_ticker_payload={
            "symbol": symbol,
            "bidPrice": bid,
            "bidQty": "10",
            "askPrice": ask,
            "askQty": "11",
        },
        fail_operation="get_book_ticker" if fail else "",
    )


def _prepare(approved: ApprovedOrderIntent, gateway: FakeBinancePublicMarketGateway, *, key: str = "prepare"):
    return prepare_execution(
        approved_order_intent_id=approved.id,
        business_request_key=f"execution-preparation-{key}",
        reference_time_utc=timezone.now(),
        trace_id=f"trace-execution-preparation-{key}",
        trigger_source="test",
        gateway=gateway,
    )


def test_prepare_buy_uses_best_ask_and_creates_prepared_order(settings) -> None:
    approved = _approved(settings, ratio="0.5", price_value="50000", key="buy")
    gateway = _gateway(bid="49990", ask="50010")

    result = _prepare(approved, gateway, key="buy")

    prepared = PreparedOrderIntent.objects.get()
    prep_result = ExecutionPreparationResult.objects.get()
    approved.refresh_from_db()
    assert result.status == "succeeded"
    assert result.data["prepared_order_intent_id"] == prepared.id
    assert prep_result.status == ExecutionPreparationStatus.PREPARED
    assert prep_result.selected_live_price == Decimal("50010")
    assert prep_result.selected_live_price_side == "ask"
    assert prepared.status == PreparedOrderIntentStatus.PREPARED
    assert prepared.side == "BUY"
    assert prepared.quantity == approved.requested_size
    assert prepared.time_in_force == ""
    assert approved.status == ApprovedOrderIntentStatus.EXECUTION_PREPARED
    assert OrderPlanActiveLock.objects.get().status == ActiveLockStatus.ACTIVE
    assert gateway.calls == [{"operation": "get_book_ticker", "market_type": MARKET_TYPE_USDS_M, "symbol": "BTCUSDT"}]
    assert AlertEvent.objects.filter(source_module="ExecutionPreparation", event_type="execution_preparation_prepared").count() == 1


def test_prepare_limit_order_preserves_frozen_price_condition(settings) -> None:
    valid_until = timezone.now() + timedelta(hours=3, minutes=50)
    approved = _approved(
        settings,
        ratio="0.5",
        price_value="50000",
        key="limit",
        limit_condition={
            "order_type": "LIMIT",
            "limit_price": "49000",
            "limit_valid_until_utc": valid_until.isoformat(),
            "time_in_force": "GTC",
            "price_condition_hash": "limit-condition-hash",
        },
    )
    gateway = _gateway(bid="49990", ask="50010")

    result = _prepare(approved, gateway, key="limit")

    prepared = PreparedOrderIntent.objects.get()
    assert result.status == "succeeded"
    assert prepared.order_type == "LIMIT"
    assert prepared.time_in_force == "GTC"
    assert prepared.limit_price == Decimal("49000")
    assert prepared.limit_valid_until_utc == valid_until
    assert prepared.price_condition_hash == "limit-condition-hash"
    assert prepared.expires_at_utc <= valid_until


def test_price_deviation_equal_one_percent_is_allowed(settings) -> None:
    approved = _approved(settings, ratio="0.5", price_value="50000", key="one-percent")
    gateway = _gateway(bid="50490", ask="50500")

    result = _prepare(approved, gateway, key="one-percent")

    prep_result = ExecutionPreparationResult.objects.get()
    assert result.status == "succeeded"
    assert prep_result.price_deviation_bps == Decimal("100.000000000000")
    assert PreparedOrderIntent.objects.count() == 1


def test_price_deviation_greater_than_one_percent_blocks_and_releases_lock(settings) -> None:
    approved = _approved(settings, ratio="0.5", price_value="50000", key="deviation-block")
    gateway = _gateway(bid="50500", ask="50501")

    result = _prepare(approved, gateway, key="deviation-block")

    prep_result = ExecutionPreparationResult.objects.get()
    approved.refresh_from_db()
    assert result.status == "blocked"
    assert prep_result.status == ExecutionPreparationStatus.BLOCKED
    assert prep_result.reason_code == "live_price_deviation_exceeded"
    assert PreparedOrderIntent.objects.count() == 0
    assert approved.status == ApprovedOrderIntentStatus.PREPARATION_BLOCKED
    assert OrderPlanActiveLock.objects.get().status == ActiveLockStatus.RELEASED
    assert AlertEvent.objects.filter(source_module="ExecutionPreparation", event_type="execution_preparation_price_deviation_exceeded").count() == 1


def test_gateway_failure_blocks_without_prepared_order(settings) -> None:
    approved = _approved(settings, ratio="0.5", price_value="50000", key="gateway-fail")
    gateway = _gateway(fail=True)

    result = _prepare(approved, gateway, key="gateway-fail")

    assert result.status == "blocked"
    assert result.reason_code == "live_price_unavailable"
    assert PreparedOrderIntent.objects.count() == 0
    assert OrderPlanActiveLock.objects.get().status == ActiveLockStatus.RELEASED


def test_prepare_sell_uses_best_bid(settings) -> None:
    approved = _approved(settings, ratio="-0.5", price_value="50000", available="1000", key="sell")
    gateway = _gateway(bid="49980", ask="49990")

    result = _prepare(approved, gateway, key="sell")

    prepared = PreparedOrderIntent.objects.get()
    prep_result = ExecutionPreparationResult.objects.get()
    assert result.status == "succeeded"
    assert prepared.side == "SELL"
    assert prep_result.selected_live_price == Decimal("49980")
    assert prep_result.selected_live_price_side == "bid"


def test_idempotent_replay_returns_same_prepared_order_without_second_book_ticker(settings) -> None:
    approved = _approved(settings, ratio="0.5", price_value="50000", key="idempotent")
    first_gateway = _gateway(bid="49990", ask="50010")
    second_gateway = _gateway(bid="40000", ask="60000")

    first = _prepare(approved, first_gateway, key="idempotent")
    second = _prepare(approved, second_gateway, key="idempotent-second")

    assert first.status == "succeeded"
    assert second.status == "succeeded"
    assert first.data["prepared_order_intent_id"] == second.data["prepared_order_intent_id"]
    assert ExecutionPreparationResult.objects.count() == 1
    assert PreparedOrderIntent.objects.count() == 1
    assert len(first_gateway.calls) == 1
    assert second_gateway.calls == []


def test_idempotent_replay_after_prepared_order_expired_does_not_continue(settings) -> None:
    approved = _approved(settings, ratio="0.5", price_value="50000", key="expired-replay")
    first_gateway = _gateway(bid="49990", ask="50010")
    second_gateway = _gateway(bid="49990", ask="50010")
    first = _prepare(approved, first_gateway, key="expired-replay")
    prepared = PreparedOrderIntent.objects.get()
    PreparedOrderIntent.objects.filter(id=prepared.id).update(expires_at_utc=timezone.now() - timedelta(seconds=1))

    second = _prepare(approved, second_gateway, key="expired-replay-second")

    prep_result = ExecutionPreparationResult.objects.get()
    prepared.refresh_from_db()
    approved.refresh_from_db()
    assert first.status == "succeeded"
    assert second.status == "blocked"
    assert second.reason_code == "prepared_order_intent_expired"
    assert second.data["allows_downstream"] is False
    assert second.data["flow_action"] == "STOP"
    assert prep_result.status == ExecutionPreparationStatus.EXPIRED
    assert prepared.status == PreparedOrderIntentStatus.EXPIRED
    assert approved.status == ApprovedOrderIntentStatus.PREPARATION_EXPIRED
    assert OrderPlan.objects.get().status == "preparation_expired"
    assert OrderPlanActiveLock.objects.get().status == ActiveLockStatus.RELEASED
    assert second_gateway.calls == []


class ExplodingBookTickerGateway(FakeBinancePublicMarketGateway):
    def get_book_ticker(self, **kwargs):
        self.calls.append({"operation": "get_book_ticker", "market_type": kwargs["market_type"], "symbol": kwargs["symbol"]})
        raise RuntimeError("book ticker exploded")


def test_unexpected_gateway_exception_marks_result_failed_and_keeps_lock(settings) -> None:
    approved = _approved(settings, ratio="0.5", price_value="50000", key="gateway-explodes")
    gateway = ExplodingBookTickerGateway(book_ticker_payload={})

    result = _prepare(approved, gateway, key="gateway-explodes")

    prep_result = ExecutionPreparationResult.objects.get()
    approved.refresh_from_db()
    assert result.status == "failed"
    assert result.reason_code == "internal_error"
    assert prep_result.status == ExecutionPreparationStatus.FAILED
    assert PreparedOrderIntent.objects.count() == 0
    assert approved.status == ApprovedOrderIntentStatus.PREPARATION_FAILED
    assert OrderPlan.objects.get().status == "preparation_failed"
    assert OrderPlanActiveLock.objects.get().status == ActiveLockStatus.ACTIVE


def test_prepared_order_unique_conflict_fails_instead_of_replaying_preparing_result(settings, monkeypatch) -> None:
    approved = _approved(settings, ratio="0.5", price_value="50000", key="client-conflict")

    def raise_integrity_error(**kwargs):
        raise IntegrityError("prepared unique conflict")

    monkeypatch.setattr(PreparedOrderIntent.objects, "create", raise_integrity_error)

    result = _prepare(approved, _gateway(), key="client-conflict")

    prep_result = ExecutionPreparationResult.objects.get()
    assert result.status == "failed"
    assert result.reason_code == "prepared_request_conflict"
    assert prep_result.status == ExecutionPreparationStatus.FAILED
    assert PreparedOrderIntent.objects.count() == 0


class ReleasingLockGateway(FakeBinancePublicMarketGateway):
    def __init__(self, *, approved: ApprovedOrderIntent) -> None:
        super().__init__(
            book_ticker_payload={
                "symbol": approved.symbol,
                "bidPrice": "49990",
                "bidQty": "10",
                "askPrice": "50010",
                "askQty": "11",
            }
        )
        self.approved = approved

    def get_book_ticker(self, **kwargs):
        release_for_pre_execution_stop(
            active_lock_id=self.approved.active_lock_id,
            order_plan_id=self.approved.order_plan_id,
            source_module="test",
            source_object_id=self.approved.id,
            reason_code="test_release_before_prepare",
            evidence={"test": "lock released before PreparedOrderIntent create"},
            trace_id="trace-test-lock-release",
            trigger_source="test",
        )
        return super().get_book_ticker(**kwargs)


def test_active_lock_is_checked_again_before_prepared_order_is_created(settings) -> None:
    approved = _approved(settings, ratio="0.5", price_value="50000", key="lock-recheck")
    gateway = ReleasingLockGateway(approved=approved)

    result = _prepare(approved, gateway, key="lock-recheck")

    prep_result = ExecutionPreparationResult.objects.get()
    assert result.status == "blocked"
    assert result.reason_code == "active_lock_not_active"
    assert prep_result.status == ExecutionPreparationStatus.BLOCKED
    assert PreparedOrderIntent.objects.count() == 0
    assert OrderPlanActiveLock.objects.get().status == ActiveLockStatus.RELEASED
