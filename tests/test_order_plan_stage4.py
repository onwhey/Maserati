from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest
from django.core.cache import cache
from django.db import DatabaseError
from django.utils import timezone

from apps.alerts.models import AlertEvent
from apps.binance_account_sync.models import (
    BinanceSyncPurpose,
    BinanceSyncRun,
)
from apps.binance_account_sync.services.sync import (
    GatewayPayloads,
    SyncRequest,
    build_snapshot_draft,
    publish_snapshot_set,
)
from apps.order_plan.adapters import run_order_plan_step
from apps.order_plan.services.plan import create_order_plan
from apps.order_plan.services import alerts as order_plan_alerts
from apps.order_plan.models import (
    ActiveLockStatus,
    CandidateOrderIntent,
    CandidateIntentRole,
    OrderPlan,
    OrderPlanActiveLock,
    OrderPlanStatus,
)
from apps.price_snapshot.models import PriceSnapshot, PriceType
from apps.price_snapshot.services.snapshot import (
    cache_price_snapshot,
    compute_price_snapshot_hash,
    price_snapshot_hash_payload,
)
from apps.runtime_config.models import RuntimeTradingConfig
from apps.strategy_analysis.models import DecisionSnapshot, DecisionTargetIntent
from tests.strategy_analysis.test_decision_snapshot import (
    FakeDecisionPolicyCalculator,
    build_decision_fixture,
    decision_registry,
    run_decision,
)


pytestmark = pytest.mark.django_db


def _decision(*, ratio: str, key: str) -> DecisionSnapshot:
    fixture, _rule_set, _signal, quality, _policy = build_decision_fixture()
    registry, _calculator = decision_registry(
        FakeDecisionPolicyCalculator(
            target_intent=DecisionTargetIntent.TARGET_POSITION,
            target_position_ratio=ratio,
        )
    )
    result = run_decision(
        quality=quality,
        release=fixture["release"],
        registry=registry,
        key=key,
    )
    assert result.status == "succeeded"
    return DecisionSnapshot.objects.get(id=result.data["decision_snapshot_id"])


def _non_orderable_decision(*, target_intent: str, key: str) -> DecisionSnapshot:
    fixture, _rule_set, _signal, quality, _policy = build_decision_fixture()
    registry, _calculator = decision_registry(
        FakeDecisionPolicyCalculator(target_intent=target_intent)
    )
    result = run_decision(
        quality=quality,
        release=fixture["release"],
        registry=registry,
        key=key,
    )
    assert result.status == "succeeded"
    return DecisionSnapshot.objects.get(id=result.data["decision_snapshot_id"])


def _account_facts(
    *,
    market_type: str = "usds_m_futures",
    account_domain: str = "default",
    symbol: str = "BTCUSDT",
    position: str = "0",
    equity: str = "1000",
    contract_size: str | None = None,
    step_size: str = "0.001",
    order_types: list[str] | None = None,
) -> BinanceSyncRun:
    now = timezone.now()
    asset = "USDT" if market_type == "usds_m_futures" else "BTC"
    request_key = f"account-{BinanceSyncRun.objects.count() + 1}"
    run = BinanceSyncRun.objects.create(
        business_request_key=request_key,
        market_type=market_type,
        account_domain=account_domain,
        sync_purpose=BinanceSyncPurpose.TRADE_PREPARATION,
        requested_symbols=[symbol],
        trace_id="trace-account",
        trigger_source="test",
    )
    request = SyncRequest(
        business_request_key=request_key,
        sync_purpose=BinanceSyncPurpose.TRADE_PREPARATION,
        market_type=market_type,
        account_domain=account_domain,
        symbols=(symbol,),
        trace_id="trace-account",
        trigger_source="test",
    )
    rule_payload = {
        "symbol": symbol,
        "status": "TRADING",
        "baseAsset": "BTC",
        "quoteAsset": "USDT" if market_type == "usds_m_futures" else "USD",
        "marginAsset": asset,
        "settleAsset": asset,
        "quantityPrecision": 3 if market_type == "usds_m_futures" else 0,
        "contractSize": contract_size,
        "orderTypes": order_types or ["MARKET"],
        "filters": [
            {
                "filterType": "LOT_SIZE",
                "stepSize": step_size,
                "minQty": step_size,
                "maxQty": "10000",
            },
            {"filterType": "MIN_NOTIONAL", "notional": "5"},
        ],
    }
    payloads = GatewayPayloads(
        account={
            "totalMarginBalance": equity,
            "availableBalance": equity,
            "asset": asset,
        },
        balances=[{"asset": asset, "balance": equity, "availableBalance": equity}],
        positions=[{"symbol": symbol, "positionSide": "BOTH", "positionAmt": position}],
        symbol_rules={symbol: rule_payload},
        gateway_summary={},
    )
    draft = build_snapshot_draft(request=request, payloads=payloads, as_of_utc=now)
    publish_snapshot_set(run=run, request=request, payloads=payloads, draft=draft)
    run.refresh_from_db()
    return run


def _price(
    *,
    market_type: str = "usds_m_futures",
    account_domain: str = "default",
    symbol: str = "BTCUSDT",
    value: str = "50000",
    expired: bool = False,
) -> PriceSnapshot:
    now = timezone.now()
    as_of = now - timedelta(minutes=20) if expired else now
    expires_at = as_of + timedelta(minutes=10)
    payload = price_snapshot_hash_payload(
        business_request_key=f"price-{PriceSnapshot.objects.count() + 1}",
        exchange="binance",
        market_type=market_type,
        account_domain=account_domain,
        symbol=symbol,
        price_type=PriceType.MARK_PRICE,
        mark_price=Decimal(value),
        price_unit="USDT" if market_type == "usds_m_futures" else "USD",
        source="binance_rest",
        source_operation="get_mark_price",
        source_update_time_utc=as_of,
        as_of_utc=as_of,
        expires_at_utc=expires_at,
    )
    return PriceSnapshot.objects.create(
        business_request_key=payload["business_request_key"],
        exchange="binance",
        market_type=market_type,
        account_domain=account_domain,
        symbol=symbol,
        price_type=PriceType.MARK_PRICE,
        mark_price=Decimal(value),
        price_unit=payload["price_unit"],
        source="binance_rest",
        source_operation="get_mark_price",
        source_update_time_utc=as_of,
        requested_at_utc=now,
        received_at_utc=now,
        as_of_utc=as_of,
        expires_at_utc=expires_at,
        price_snapshot_hash=compute_price_snapshot_hash(payload),
        trace_id="trace-price",
        trigger_source="test",
    )


def _enable_runtime_permission(settings, *, market_type: str = "USDS-M") -> None:
    settings.DEPLOYMENT_REAL_TRADING_ENABLED = True
    settings.ACTIVE_EXCHANGE = "Binance"
    settings.ACTIVE_MARKET_TYPE = market_type
    settings.ACTIVE_ACCOUNT_DOMAIN = "default"
    settings.ACTIVE_SYMBOL = "BTCUSDT"
    settings.ORDER_PLAN_ENABLED = True
    settings.PRICE_SNAPSHOT_REDIS_CACHE_ENABLED = False
    RuntimeTradingConfig.objects.create(
        config_key="default",
        runtime_real_trading_permission=True,
    )


def _run(*, decision: DecisionSnapshot, account: BinanceSyncRun, price: PriceSnapshot, key: str):
    return run_order_plan_step(
        business_request_key=key,
        decision_snapshot_id=decision.id,
        binance_sync_run_id=account.id,
        price_snapshot_id=price.id,
        reference_time_utc=timezone.now(),
        trace_id=f"trace-{key}",
        trigger_source="test",
    )


def test_permission_closed_does_not_create_plan_candidate_or_lock(settings) -> None:
    settings.DEPLOYMENT_REAL_TRADING_ENABLED = False
    decision = _decision(ratio="0.5", key="decision-permission-closed")
    account = _account_facts()
    price = _price()

    result = _run(decision=decision, account=account, price=price, key="plan-permission-closed")

    assert result.status == "no_action"
    assert result.reason_code == "real_trading_not_allowed"
    assert result.data["flow_action"] == "COMPLETE"
    assert OrderPlan.objects.count() == 0
    assert CandidateOrderIntent.objects.count() == 0
    assert OrderPlanActiveLock.objects.count() == 0


def test_usds_m_creates_plan_primary_candidate_and_active_lock(settings) -> None:
    _enable_runtime_permission(settings)
    decision = _decision(ratio="0.5", key="decision-usds")
    account = _account_facts(position="0.01")
    price = _price(value="50000")

    result = _run(decision=decision, account=account, price=price, key="plan-usds")

    plan = OrderPlan.objects.get()
    candidate = CandidateOrderIntent.objects.get()
    lock = OrderPlanActiveLock.objects.get()
    assert result.status == "succeeded"
    assert result.data["flow_action"] == "CONTINUE"
    assert plan.status == OrderPlanStatus.CREATED
    assert plan.current_equity == Decimal("1000")
    assert plan.target_notional == Decimal("1500")
    assert plan.target_signed_size == Decimal("0.03")
    assert plan.delta_signed_size == Decimal("0.02")
    assert candidate.intent_role == CandidateIntentRole.PRIMARY
    assert candidate.side == "BUY"
    assert candidate.requested_size == Decimal("0.02")
    assert candidate.exchange_reduce_only is False
    assert lock.status == ActiveLockStatus.ACTIVE
    assert lock.current_order_plan_id == plan.id
    assert plan.active_lock_id == lock.id
    assert AlertEvent.objects.filter(source_module="OrderPlan", event_type="candidate_order_intent_generated").count() == 1


def test_order_plan_generates_limit_candidate_from_frozen_trade_price_condition(settings) -> None:
    _enable_runtime_permission(settings)
    settings.ORDER_PLAN_SUPPORTED_ORDER_TYPES = ["MARKET", "LIMIT"]
    valid_until = timezone.now() + timedelta(hours=3, minutes=50)
    decision = _decision(ratio="0.5", key="decision-limit")
    decision.decision_calculation_snapshot = {
        "frozen_trade_price_condition": {
            "order_type": "LIMIT",
            "limit_price": "49000",
            "limit_valid_until_utc": valid_until.isoformat(),
            "time_in_force": "GTC",
            "price_condition_hash": "limit-condition-hash",
        }
    }
    decision.save(update_fields=["decision_calculation_snapshot", "updated_at_utc"])
    account = _account_facts(position="0", order_types=["MARKET", "LIMIT"])
    price = _price(value="50000")

    result = _run(decision=decision, account=account, price=price, key="plan-limit")

    candidate = CandidateOrderIntent.objects.get()
    assert result.status == "succeeded"
    assert candidate.order_type == "LIMIT"
    assert candidate.limit_price == Decimal("49000")
    assert candidate.limit_valid_until_utc == valid_until
    assert candidate.time_in_force == "GTC"
    assert candidate.price_condition_hash == "limit-condition-hash"


def test_standard_strategy_price_condition_without_executable_price_does_not_chase_market(settings) -> None:
    _enable_runtime_permission(settings)
    decision = _decision(ratio="0.5", key="decision-text-price-condition")
    decision.frozen_trade_price_condition = {
        "condition_type": "near_support_only",
        "reference_price_zone": "支撑区附近",
        "acceptable_price_zone": "支撑区附近",
        "support_or_resistance_refs": ["structure.support.primary"],
        "allow_chasing": False,
        "reason_code": "long_pullback_support_entry",
        "reason_summary_zh": "只在支撑区附近考虑执行。",
    }
    decision.save(update_fields=["frozen_trade_price_condition", "updated_at_utc"])
    account = _account_facts(position="0")
    price = _price(value="50000")

    result = _run(decision=decision, account=account, price=price, key="plan-text-price-condition")

    plan = OrderPlan.objects.get()
    assert result.status == "no_action"
    assert result.reason_code == "price_condition_not_actionable"
    assert plan.status == OrderPlanStatus.NO_ORDER_REQUIRED
    assert CandidateOrderIntent.objects.count() == 0
    assert OrderPlanActiveLock.objects.count() == 0


def test_standard_strategy_price_condition_allows_market_only_when_chasing_allowed_and_price_in_zone(settings) -> None:
    _enable_runtime_permission(settings)
    decision = _decision(ratio="0.5", key="decision-actionable-price-condition")
    decision.frozen_trade_price_condition = {
        "condition_type": "near_support_only",
        "reference_price_zone": "支撑区附近",
        "acceptable_price_zone": {"lower": "49000", "upper": "51000"},
        "support_or_resistance_refs": ["structure.support.primary"],
        "allow_chasing": True,
        "reason_code": "long_pullback_support_entry",
        "reason_summary_zh": "允许价格仍在可接受区间时执行。",
    }
    decision.save(update_fields=["frozen_trade_price_condition", "updated_at_utc"])
    account = _account_facts(position="0")
    price = _price(value="50000")

    result = _run(decision=decision, account=account, price=price, key="plan-actionable-price-condition")

    candidate = CandidateOrderIntent.objects.get()
    assert result.status == "succeeded"
    assert candidate.order_type == "MARKET"
    assert candidate.price_condition_evidence["condition_type"] == "near_support_only"


def test_order_plan_is_idempotent_and_does_not_duplicate_lock_or_candidate(settings) -> None:
    _enable_runtime_permission(settings)
    decision = _decision(ratio="0.5", key="decision-idempotent")
    account = _account_facts(position="0")
    price = _price()

    first = _run(decision=decision, account=account, price=price, key="plan-idempotent")
    second = _run(decision=decision, account=account, price=price, key="plan-idempotent")

    assert first.status == "succeeded"
    assert second.status == "succeeded"
    assert first.data["order_plan_id"] == second.data["order_plan_id"]
    assert OrderPlan.objects.count() == 1
    assert CandidateOrderIntent.objects.count() == 1
    assert OrderPlanActiveLock.objects.count() == 1


def test_idempotent_replay_blocks_when_bound_position_fact_was_tampered(settings) -> None:
    _enable_runtime_permission(settings)
    decision = _decision(ratio="0.5", key="decision-replay-tamper")
    account = _account_facts(position="0")
    price = _price()
    first = _run(decision=decision, account=account, price=price, key="plan-replay-tamper")
    account.position_snapshots.update(position_amount=Decimal("1"))

    replay = _run(decision=decision, account=account, price=price, key="plan-replay-tamper")

    assert first.status == "succeeded"
    assert replay.status == "blocked"
    assert replay.reason_code == "position_snapshot_hash_mismatch"
    assert OrderPlan.objects.count() == 1
    assert CandidateOrderIntent.objects.count() == 1


def test_idempotent_replay_blocks_when_decision_fact_was_changed(settings) -> None:
    _enable_runtime_permission(settings)
    decision = _decision(ratio="0.5", key="decision-replay-change")
    account = _account_facts(position="0")
    price = _price()
    first = _run(decision=decision, account=account, price=price, key="plan-replay-change")
    DecisionSnapshot.objects.filter(id=decision.id).update(target_position_ratio=Decimal("0.4"))

    replay = _run(decision=decision, account=account, price=price, key="plan-replay-change")

    assert first.status == "succeeded"
    assert replay.status == "blocked"
    assert replay.reason_code == "decision_snapshot_changed_after_order_plan"
    assert OrderPlan.objects.count() == 1


def test_zero_target_and_zero_position_needs_no_order_and_no_lock(settings) -> None:
    _enable_runtime_permission(settings)
    decision = _decision(ratio="0", key="decision-no-order")
    account = _account_facts(position="0")
    price = _price()

    result = _run(decision=decision, account=account, price=price, key="plan-no-order")

    plan = OrderPlan.objects.get()
    assert result.status == "no_action"
    assert result.data["flow_action"] == "COMPLETE"
    assert plan.status == OrderPlanStatus.NO_ORDER_REQUIRED
    assert CandidateOrderIntent.objects.count() == 0
    assert OrderPlanActiveLock.objects.count() == 0
    assert AlertEvent.objects.filter(
        source_module="OrderPlan",
        event_type="candidate_order_intent_skipped",
    ).count() == 1


def test_active_lock_blocks_next_conflicting_plan(settings) -> None:
    _enable_runtime_permission(settings)
    decision = _decision(ratio="0.5", key="decision-lock")
    account = _account_facts(position="0")
    price = _price()

    first = _run(decision=decision, account=account, price=price, key="plan-lock-one")
    second = _run(decision=decision, account=account, price=price, key="plan-lock-two")

    assert first.status == "succeeded"
    assert second.status == "blocked"
    assert second.reason_code == "active_lock_conflict"
    assert OrderPlan.objects.count() == 2
    assert OrderPlan.objects.get(business_request_key="plan-lock-two").status == OrderPlanStatus.BLOCKED
    assert CandidateOrderIntent.objects.count() == 1
    assert OrderPlanActiveLock.objects.count() == 1
    assert AlertEvent.objects.filter(
        source_module="OrderPlan",
        event_type="candidate_order_intent_blocked",
        related_object_id=str(OrderPlan.objects.get(business_request_key="plan-lock-two").id),
    ).exists()


def test_netting_reverse_creates_primary_and_prebuilt_reduce_only_fallback(settings) -> None:
    _enable_runtime_permission(settings)
    decision = _decision(ratio="-0.5", key="decision-reverse")
    account = _account_facts(position="0.01")
    price = _price()

    result = _run(decision=decision, account=account, price=price, key="plan-reverse")

    primary = CandidateOrderIntent.objects.get(intent_role=CandidateIntentRole.PRIMARY)
    fallback = CandidateOrderIntent.objects.get(intent_role=CandidateIntentRole.FALLBACK_REDUCE_ONLY)
    assert result.status == "succeeded"
    assert primary.plan_type == "netting_reverse_long_to_short"
    assert primary.side == "SELL"
    assert primary.requested_size == Decimal("0.04")
    assert primary.closing_size == Decimal("0.01")
    assert primary.opening_size == Decimal("0.03")
    assert primary.exchange_reduce_only is False
    assert len(primary.order_components) == 2
    assert fallback.requested_size == Decimal("0.01")
    assert fallback.opening_size == 0
    assert fallback.exchange_reduce_only is True
    assert all(item["risk_effect"] == "reduce_risk" for item in fallback.order_components)


def test_coin_m_uses_contract_size_and_integer_contracts(settings) -> None:
    _enable_runtime_permission(settings, market_type="COIN-M")
    decision = _decision(ratio="0.5", key="decision-coin")
    account = _account_facts(
        market_type="coin_m_futures",
        position="10",
        equity="0.1",
        contract_size="100",
        step_size="1",
    )
    price = _price(market_type="coin_m_futures", value="50000")

    result = _run(decision=decision, account=account, price=price, key="plan-coin")

    plan = OrderPlan.objects.get()
    candidate = CandidateOrderIntent.objects.get()
    assert result.status == "succeeded"
    assert plan.target_notional == Decimal("7500")
    assert plan.target_signed_size == Decimal("75")
    assert candidate.requested_size == Decimal("65")
    assert candidate.requested_notional == Decimal("6500")
    assert candidate.requested_size_unit == "contracts"


def test_stale_price_blocks_without_refresh_or_candidate(settings) -> None:
    _enable_runtime_permission(settings)
    decision = _decision(ratio="0.5", key="decision-stale-price")
    account = _account_facts(position="0")
    price = _price(expired=True)

    result = _run(decision=decision, account=account, price=price, key="plan-stale-price")

    assert result.status == "blocked"
    assert result.reason_code == "price_snapshot_stale"
    assert OrderPlan.objects.get().status == OrderPlanStatus.BLOCKED
    assert CandidateOrderIntent.objects.count() == 0
    assert OrderPlanActiveLock.objects.count() == 0


@pytest.mark.parametrize("target_intent", [DecisionTargetIntent.NO_TRADE, DecisionTargetIntent.NO_TARGET_CHANGE])
def test_non_orderable_decision_is_blocked_without_candidate_or_lock(settings, target_intent) -> None:
    _enable_runtime_permission(settings)
    decision = _non_orderable_decision(target_intent=target_intent, key=f"decision-{target_intent}")
    account = _account_facts()
    price = _price()

    result = _run(decision=decision, account=account, price=price, key=f"plan-{target_intent}")

    assert result.status == "blocked"
    assert result.reason_code == "decision_snapshot_not_orderable"
    assert OrderPlan.objects.get().target_position_ratio is None
    assert CandidateOrderIntent.objects.count() == 0
    assert OrderPlanActiveLock.objects.count() == 0


def test_snapshot_set_hash_mismatch_is_blocked(settings) -> None:
    _enable_runtime_permission(settings)
    decision = _decision(ratio="0.5", key="decision-bad-account-hash")
    account = _account_facts()
    account.snapshot_set_hash = "tampered"
    account.save(update_fields=["snapshot_set_hash"])
    price = _price()

    result = _run(decision=decision, account=account, price=price, key="plan-bad-account-hash")

    assert result.status == "blocked"
    assert result.reason_code == "snapshot_set_hash_mismatch"
    assert OrderPlan.objects.get().status == OrderPlanStatus.BLOCKED
    assert CandidateOrderIntent.objects.count() == 0
    assert OrderPlanActiveLock.objects.count() == 0


def test_tampered_position_fact_is_blocked_by_child_hash_verification(settings) -> None:
    _enable_runtime_permission(settings)
    decision = _decision(ratio="0.5", key="decision-tampered-position")
    account = _account_facts(position="0")
    account.position_snapshots.update(position_amount=Decimal("1"))
    price = _price()

    result = _run(decision=decision, account=account, price=price, key="plan-tampered-position")

    assert result.status == "blocked"
    assert result.reason_code == "position_snapshot_hash_mismatch"
    assert OrderPlan.objects.get().status == OrderPlanStatus.BLOCKED
    assert CandidateOrderIntent.objects.count() == 0


def test_cache_and_mysql_price_mismatch_is_blocked(settings) -> None:
    _enable_runtime_permission(settings)
    settings.PRICE_SNAPSHOT_REDIS_CACHE_ENABLED = True
    cache.clear()
    decision = _decision(ratio="0.5", key="decision-price-cache-mismatch")
    account = _account_facts(position="0")
    price = _price(value="50000")
    cache_price_snapshot(price, trace_id="trace-cache", trigger_source="test")
    PriceSnapshot.objects.filter(id=price.id).update(mark_price=Decimal("60000"))

    result = _run(decision=decision, account=account, price=price, key="plan-price-cache-mismatch")

    assert result.status == "blocked"
    assert result.reason_code == "price_snapshot_hash_mismatch"
    assert OrderPlan.objects.get().status == OrderPlanStatus.BLOCKED
    assert CandidateOrderIntent.objects.count() == 0
    cache.clear()


def test_cached_price_cannot_hide_tampered_mysql_expiry(settings) -> None:
    _enable_runtime_permission(settings)
    settings.PRICE_SNAPSHOT_REDIS_CACHE_ENABLED = True
    cache.clear()
    decision = _decision(ratio="0.5", key="decision-price-expiry-mismatch")
    account = _account_facts(position="0")
    price = _price(value="50000")
    cache_price_snapshot(price, trace_id="trace-cache-expiry", trigger_source="test")
    PriceSnapshot.objects.filter(id=price.id).update(expires_at_utc=timezone.now() - timedelta(seconds=1))

    result = _run(decision=decision, account=account, price=price, key="plan-price-expiry-mismatch")

    assert result.status == "blocked"
    assert result.reason_code == "price_snapshot_hash_mismatch"
    assert CandidateOrderIntent.objects.count() == 0
    assert OrderPlanActiveLock.objects.count() == 0
    cache.clear()


def test_coin_m_without_contract_size_is_blocked(settings) -> None:
    _enable_runtime_permission(settings, market_type="COIN-M")
    decision = _decision(ratio="0.5", key="decision-coin-no-contract")
    account = _account_facts(
        market_type="coin_m_futures",
        position="0",
        equity="0.1",
        contract_size=None,
        step_size="1",
    )
    price = _price(market_type="coin_m_futures")

    result = _run(decision=decision, account=account, price=price, key="plan-coin-no-contract")

    assert result.status == "blocked"
    assert result.reason_code == "coin_m_contract_size_missing"
    assert OrderPlan.objects.get().status == OrderPlanStatus.BLOCKED
    assert CandidateOrderIntent.objects.count() == 0


def test_small_rebalance_is_no_action_without_lock(settings) -> None:
    _enable_runtime_permission(settings)
    settings.ORDER_PLAN_MIN_REBALANCE_NOTIONAL = Decimal("2000")
    decision = _decision(ratio="0.5", key="decision-small-rebalance")
    account = _account_facts(position="0")
    price = _price()

    result = _run(decision=decision, account=account, price=price, key="plan-small-rebalance")

    assert result.status == "no_action"
    assert result.reason_code == "below_min_rebalance_notional"
    assert OrderPlan.objects.get().status == OrderPlanStatus.NO_ORDER_REQUIRED
    assert CandidateOrderIntent.objects.count() == 0
    assert OrderPlanActiveLock.objects.count() == 0


def test_target_notional_is_recomputed_after_target_size_rounding(settings) -> None:
    _enable_runtime_permission(settings)
    decision = _decision(ratio="0.333333333333333333", key="decision-rounded-target")
    account = _account_facts(position="0")
    price = _price(value="70000")

    result = _run(decision=decision, account=account, price=price, key="plan-rounded-target")

    plan = OrderPlan.objects.get()
    assert result.status == "succeeded"
    assert plan.target_signed_size == Decimal("0.014")
    assert plan.target_notional == Decimal("980")
    assert plan.target_notional == plan.target_signed_size * plan.mark_price


def test_untradable_tiny_close_is_blocked_instead_of_reported_as_no_action(settings) -> None:
    _enable_runtime_permission(settings)
    decision = _decision(ratio="0", key="decision-tiny-close")
    account = _account_facts(position="0.0005", step_size="0.001")
    price = _price()

    result = _run(decision=decision, account=account, price=price, key="plan-tiny-close")

    assert result.status == "blocked"
    assert result.reason_code == "reduce_only_quantity_invalid"
    assert OrderPlan.objects.get().status == OrderPlanStatus.BLOCKED
    assert CandidateOrderIntent.objects.count() == 0
    assert OrderPlanActiveLock.objects.count() == 0


def test_reduce_only_below_exchange_min_notional_is_blocked(settings) -> None:
    _enable_runtime_permission(settings)
    decision = _decision(ratio="0", key="decision-small-close-notional")
    account = _account_facts(position="0.001", step_size="0.001")
    price = _price(value="1000")

    result = _run(decision=decision, account=account, price=price, key="plan-small-close-notional")

    assert result.status == "blocked"
    assert result.reason_code == "reduce_only_quantity_invalid"
    assert OrderPlan.objects.get().status == OrderPlanStatus.BLOCKED
    assert CandidateOrderIntent.objects.count() == 0
    assert OrderPlanActiveLock.objects.count() == 0


def test_legal_partial_close_with_residual_is_labeled_as_reduce_not_close(settings) -> None:
    _enable_runtime_permission(settings)
    decision = _decision(ratio="0", key="decision-residual-close")
    account = _account_facts(position="0.0105", step_size="0.001")
    price = _price(value="50000")

    result = _run(decision=decision, account=account, price=price, key="plan-residual-close")

    candidate = CandidateOrderIntent.objects.get()
    assert result.status == "succeeded"
    assert candidate.plan_type == "reduce_long"
    assert candidate.order_components[0]["position_effect"] == "reduce_long"
    assert candidate.requested_size == Decimal("0.010")
    assert candidate.residual_position_size == Decimal("0.0005")
    assert candidate.exchange_reduce_only is True


def test_zero_equity_still_allows_target_zero_to_close_existing_position(settings) -> None:
    _enable_runtime_permission(settings)
    decision = _decision(ratio="0", key="decision-zero-equity-close")
    account = _account_facts(position="0.01", equity="0")
    price = _price(value="50000")

    result = _run(decision=decision, account=account, price=price, key="plan-zero-equity-close")

    candidate = CandidateOrderIntent.objects.get()
    assert result.status == "succeeded"
    assert candidate.plan_type == "close_long"
    assert candidate.side == "SELL"
    assert candidate.exchange_reduce_only is True
    assert candidate.requested_size == Decimal("0.01")


def test_step_size_finer_than_quantity_precision_is_blocked(settings) -> None:
    _enable_runtime_permission(settings)
    decision = _decision(ratio="0.5", key="decision-precision-mismatch")
    account = _account_facts(position="0", step_size="0.0001")
    price = _price()

    result = _run(decision=decision, account=account, price=price, key="plan-precision-mismatch")

    assert result.status == "blocked"
    assert result.reason_code == "symbol_rule_precision_mismatch"
    assert CandidateOrderIntent.objects.count() == 0


def test_service_rejects_unknown_market_type_without_treating_it_as_coin_m(settings) -> None:
    settings.ORDER_PLAN_ENABLED = True
    settings.PRICE_SNAPSHOT_REDIS_CACHE_ENABLED = False
    decision = _decision(ratio="0.5", key="decision-unknown-market")
    account = _account_facts(market_type="unknown_futures")
    price = _price(market_type="unknown_futures")

    result = create_order_plan(
        business_request_key="plan-unknown-market",
        decision_snapshot_id=decision.id,
        binance_sync_run_id=account.id,
        price_snapshot_id=price.id,
        reference_time_utc=timezone.now(),
        trace_id="trace-unknown-market",
        trigger_source="test",
    )

    assert result.status == "blocked"
    assert result.reason_code == "market_type_not_supported"
    assert OrderPlan.objects.count() == 0


def test_alert_write_failure_does_not_roll_back_order_plan_facts(settings, monkeypatch) -> None:
    _enable_runtime_permission(settings)
    decision = _decision(ratio="0.5", key="decision-alert-failure")
    account = _account_facts(position="0")
    price = _price()

    def fail_alert_write(**_kwargs):
        raise DatabaseError("test alert database failure")

    monkeypatch.setattr(order_plan_alerts, "record_alert_event", fail_alert_write)
    result = _run(decision=decision, account=account, price=price, key="plan-alert-failure")

    assert result.status == "succeeded"
    assert OrderPlan.objects.get().status == OrderPlanStatus.CREATED
    assert CandidateOrderIntent.objects.count() == 1
    assert OrderPlanActiveLock.objects.get().status == ActiveLockStatus.ACTIVE


def test_adapter_blocks_active_market_mismatch_before_order_plan(settings) -> None:
    _enable_runtime_permission(settings, market_type="USDS-M")
    decision = _decision(ratio="0.5", key="decision-market-mismatch")
    account = _account_facts(
        market_type="coin_m_futures",
        equity="0.1",
        contract_size="100",
        step_size="1",
    )
    price = _price(market_type="coin_m_futures")

    result = _run(decision=decision, account=account, price=price, key="plan-market-mismatch")

    assert result.status == "blocked"
    assert result.reason_code == "active_market_identity_mismatch"
    assert OrderPlan.objects.count() == 0
    assert CandidateOrderIntent.objects.count() == 0
    assert OrderPlanActiveLock.objects.count() == 0


def test_same_business_key_with_different_price_is_blocked_as_input_conflict(settings) -> None:
    _enable_runtime_permission(settings)
    decision = _decision(ratio="0.5", key="decision-input-conflict")
    account = _account_facts()
    first_price = _price(value="50000")
    second_price = _price(value="51000")

    first = _run(decision=decision, account=account, price=first_price, key="plan-input-conflict")
    second = _run(decision=decision, account=account, price=second_price, key="plan-input-conflict")

    assert first.status == "succeeded"
    assert second.status == "blocked"
    assert second.reason_code == "order_plan_input_conflict"
    assert OrderPlan.objects.count() == 1
    assert CandidateOrderIntent.objects.count() == 1


def test_failed_active_lock_blocks_new_plan(settings) -> None:
    _enable_runtime_permission(settings)
    decision = _decision(ratio="0.5", key="decision-failed-lock")
    account = _account_facts()
    price = _price()
    first = _run(decision=decision, account=account, price=price, key="plan-before-failed-lock")
    lock = OrderPlanActiveLock.objects.get()
    lock.status = ActiveLockStatus.FAILED
    lock.reason_code = "manual_test_failed_state"
    lock.save(update_fields=["status", "reason_code", "updated_at_utc"])

    second = _run(decision=decision, account=account, price=price, key="plan-after-failed-lock")

    assert first.status == "succeeded"
    assert second.status == "blocked"
    assert second.reason_code == "active_lock_failed"
    assert CandidateOrderIntent.objects.count() == 1
    lock.refresh_from_db()
    assert lock.status == ActiveLockStatus.FAILED
