from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.alerts.models import AlertEvent
from apps.binance_account_sync.models import BinanceSyncPurpose, BinanceSyncRun
from apps.binance_account_sync.services.sync import GatewayPayloads, SyncRequest, build_snapshot_draft, publish_snapshot_set
from apps.order_plan.models import ActiveLockStatus, CandidateOrderIntent, CandidateIntentRole, CandidateIntentStatus, OrderPlanActiveLock
from apps.order_plan.adapters import run_order_plan_step
from apps.risk_check.models import ApprovedOrderIntent, RiskCheckIssue, RiskCheckResult, RiskCheckStatus, RiskRuleResult
from apps.risk_check.services.check import run_risk_check
from tests.test_order_plan_stage4 import _decision, _price


pytestmark = pytest.mark.django_db


def _enable_stage4(settings, *, market_type: str = "USDS-M") -> None:
    settings.DEPLOYMENT_REAL_TRADING_ENABLED = True
    settings.ACTIVE_EXCHANGE = "Binance"
    settings.ACTIVE_MARKET_TYPE = market_type
    settings.ACTIVE_ACCOUNT_DOMAIN = "default"
    settings.ACTIVE_SYMBOL = "BTCUSDT"
    settings.PRICE_SNAPSHOT_REDIS_CACHE_ENABLED = False
    settings.ORDER_PLAN_ENABLED = True
    settings.RISK_CHECK_ENABLED = True
    settings.RISK_CHECK_RULE_SET = "p0_default"
    settings.RISK_CHECK_MARGIN_BUFFER_RATIO = Decimal("0.05")
    settings.RISK_CHECK_RULE_FAILURE_MODE = "fail_closed"
    settings.RISK_CHECK_APPROVED_INTENT_TTL_SECONDS = 120
    from apps.runtime_config.models import RuntimeTradingConfig

    RuntimeTradingConfig.objects.create(
        config_key="default",
        runtime_real_trading_permission=True,
    )


def _account_facts(
    *,
    market_type: str = "usds_m_futures",
    account_domain: str = "default",
    symbol: str = "BTCUSDT",
    position: str = "0",
    equity: str = "1000",
    available: str | None = None,
    leverage: str | None = "20",
    contract_size: str | None = None,
    step_size: str = "0.001",
    max_qty: str = "10000",
    max_notional: str | None = None,
    order_types: list[str] | None = None,
) -> BinanceSyncRun:
    now = timezone.now()
    asset = "USDT" if market_type == "usds_m_futures" else "BTC"
    available_value = equity if available is None else available
    request_key = f"risk-account-{BinanceSyncRun.objects.count() + 1}"
    run = BinanceSyncRun.objects.create(
        business_request_key=request_key,
        market_type=market_type,
        account_domain=account_domain,
        sync_purpose=BinanceSyncPurpose.TRADE_PREPARATION,
        requested_symbols=[symbol],
        trace_id="trace-risk-account",
        trigger_source="test",
    )
    request = SyncRequest(
        business_request_key=request_key,
        sync_purpose=BinanceSyncPurpose.TRADE_PREPARATION,
        market_type=market_type,
        account_domain=account_domain,
        symbols=(symbol,),
        trace_id="trace-risk-account",
        trigger_source="test",
    )
    filters = [
        {
            "filterType": "LOT_SIZE",
            "stepSize": step_size,
            "minQty": step_size,
            "maxQty": max_qty,
        },
        {"filterType": "MIN_NOTIONAL", "notional": "5"},
    ]
    if max_notional is not None:
        filters.append({"filterType": "MAX_NOTIONAL", "maxNotional": max_notional})
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
        "filters": filters,
    }
    position_payload = {"symbol": symbol, "positionSide": "BOTH", "positionAmt": position}
    if leverage is not None:
        position_payload["leverage"] = leverage
    payloads = GatewayPayloads(
        account={
            "totalMarginBalance": equity,
            "availableBalance": available_value,
            "asset": asset,
        },
        balances=[{"asset": asset, "balance": equity, "availableBalance": available_value}],
        positions=[position_payload],
        symbol_rules={symbol: rule_payload},
        gateway_summary={},
    )
    draft = build_snapshot_draft(request=request, payloads=payloads, as_of_utc=now)
    publish_snapshot_set(run=run, request=request, payloads=payloads, draft=draft)
    run.refresh_from_db()
    return run


def _order_plan(*, settings, ratio: str, account: BinanceSyncRun, price, key: str, decision_calculation_snapshot: dict | None = None):
    _enable_stage4(settings, market_type="COIN-M" if account.market_type == "coin_m_futures" else "USDS-M")
    decision = _decision(ratio=ratio, key=f"decision-{key}")
    if decision_calculation_snapshot is not None:
        decision.decision_calculation_snapshot = decision_calculation_snapshot
        decision.save(update_fields=["decision_calculation_snapshot", "updated_at_utc"])
    return run_order_plan_step(
        business_request_key=f"plan-{key}",
        decision_snapshot_id=decision.id,
        binance_sync_run_id=account.id,
        price_snapshot_id=price.id,
        reference_time_utc=timezone.now(),
        trace_id=f"trace-plan-{key}",
        trigger_source="test",
    )


def _risk_check(*, key: str, rule_set: str | None = "p0_default", dry_run: bool = False):
    candidate = CandidateOrderIntent.objects.get(intent_role=CandidateIntentRole.PRIMARY)
    plan = candidate.order_plan
    return run_risk_check(
        business_request_key=f"risk-{key}",
        order_plan_id=plan.id,
        candidate_order_intent_id=candidate.id,
        binance_sync_run_id=plan.binance_sync_run_id,
        price_snapshot_id=plan.price_snapshot_id,
        active_lock_id=plan.active_lock_id,
        reference_time_utc=timezone.now(),
        risk_rule_set=rule_set,
        trace_id=f"trace-risk-{key}",
        trigger_source="test",
        dry_run=dry_run,
    )


def test_risk_check_allow_creates_approved_order_intent_and_keeps_lock_active(settings) -> None:
    account = _account_facts(position="0", equity="1000", available="1000", leverage="20")
    price = _price(value="50000")
    plan_result = _order_plan(settings=settings, ratio="0.5", account=account, price=price, key="allow")

    result = _risk_check(key="allow")

    approved = ApprovedOrderIntent.objects.get()
    candidate = CandidateOrderIntent.objects.get()
    lock = OrderPlanActiveLock.objects.get()
    assert plan_result.status == "succeeded"
    assert result.status == "succeeded"
    assert result.data["approved_order_intent_id"] == approved.id
    assert RiskCheckResult.objects.get().status == RiskCheckStatus.ALLOW
    assert approved.candidate_order_intent_id == candidate.id
    assert approved.side == candidate.side
    assert approved.requested_size == candidate.requested_size
    assert approved.exchange_reduce_only == candidate.exchange_reduce_only
    assert candidate.status == CandidateIntentStatus.APPROVED
    assert lock.status == ActiveLockStatus.ACTIVE
    assert AlertEvent.objects.filter(source_module="RiskCheck", event_type="approved_order_intent_generated").count() == 1


def test_risk_check_allows_limit_candidate_and_preserves_frozen_price_condition(settings) -> None:
    _enable_stage4(settings)
    settings.ORDER_PLAN_SUPPORTED_ORDER_TYPES = ["MARKET", "LIMIT"]
    valid_until = timezone.now() + timedelta(hours=3, minutes=50)
    decision = _decision(ratio="0.5", key="decision-risk-limit")
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
    account = _account_facts(position="0", equity="1000", available="1000", leverage="20", order_types=["MARKET", "LIMIT"])
    price = _price(value="50000")
    plan_result = run_order_plan_step(
        business_request_key="plan-risk-limit",
        decision_snapshot_id=decision.id,
        binance_sync_run_id=account.id,
        price_snapshot_id=price.id,
        reference_time_utc=timezone.now(),
        trace_id="trace-plan-risk-limit",
        trigger_source="test",
    )

    result = _risk_check(key="limit")

    approved = ApprovedOrderIntent.objects.get()
    candidate = CandidateOrderIntent.objects.get(intent_role=CandidateIntentRole.PRIMARY)
    assert plan_result.status == "succeeded"
    assert result.status == "succeeded"
    assert approved.order_type == "LIMIT"
    assert approved.time_in_force == "GTC"
    assert approved.limit_price == Decimal("49000")
    assert approved.limit_valid_until_utc == valid_until
    assert approved.price_condition_hash == "limit-condition-hash"
    assert approved.price_condition_evidence == candidate.price_condition_evidence


def test_risk_check_is_idempotent_without_duplicate_approved_or_alerts(settings) -> None:
    account = _account_facts(position="0", equity="1000", available="1000", leverage="20")
    price = _price(value="50000")
    _order_plan(settings=settings, ratio="0.5", account=account, price=price, key="idempotent")

    first = _risk_check(key="idempotent")
    second = _risk_check(key="idempotent")

    assert first.status == "succeeded"
    assert second.status == "succeeded"
    assert first.data["risk_check_result_id"] == second.data["risk_check_result_id"]
    assert RiskCheckResult.objects.count() == 1
    assert ApprovedOrderIntent.objects.count() == 1
    assert AlertEvent.objects.filter(source_module="RiskCheck", event_type="risk_check_allow").count() == 1


def test_processed_candidate_cannot_be_rechecked_with_different_business_key(settings) -> None:
    account = _account_facts(position="0", equity="1000", available="1000", leverage="20")
    price = _price(value="50000")
    _order_plan(settings=settings, ratio="0.5", account=account, price=price, key="processed-candidate")
    first = _risk_check(key="processed-candidate")
    candidate = CandidateOrderIntent.objects.get(intent_role=CandidateIntentRole.PRIMARY)
    plan = candidate.order_plan

    second = run_risk_check(
        business_request_key="risk-processed-candidate-alt-key",
        order_plan_id=plan.id,
        candidate_order_intent_id=candidate.id,
        binance_sync_run_id=plan.binance_sync_run_id,
        price_snapshot_id=plan.price_snapshot_id,
        active_lock_id=plan.active_lock_id,
        reference_time_utc=timezone.now(),
        risk_rule_set="p0_default",
        trace_id="trace-risk-processed-candidate-alt-key",
        trigger_source="test",
    )

    assert first.status == "succeeded"
    assert second.status == "succeeded"
    assert second.data["risk_check_result_id"] == first.data["risk_check_result_id"]
    assert RiskCheckResult.objects.count() == 1
    assert ApprovedOrderIntent.objects.count() == 1
    assert OrderPlanActiveLock.objects.get().status == ActiveLockStatus.ACTIVE


def test_margin_insufficient_denies_without_shrinking_order_and_releases_lock(settings) -> None:
    account = _account_facts(position="0", equity="1000", available="10", leverage="20")
    price = _price(value="50000")
    _order_plan(settings=settings, ratio="0.5", account=account, price=price, key="deny-margin")
    candidate_before = CandidateOrderIntent.objects.get()

    result = _risk_check(key="deny-margin")

    candidate_after = CandidateOrderIntent.objects.get()
    lock = OrderPlanActiveLock.objects.get()
    assert result.status == "denied"
    assert result.reason_code == "available_margin_insufficient"
    assert RiskCheckResult.objects.get().status == RiskCheckStatus.DENY
    assert ApprovedOrderIntent.objects.count() == 0
    assert candidate_after.requested_size == candidate_before.requested_size
    assert candidate_after.side == candidate_before.side
    assert candidate_after.exchange_reduce_only == candidate_before.exchange_reduce_only
    assert candidate_after.status == CandidateIntentStatus.DENIED
    assert lock.status == ActiveLockStatus.RELEASED


def test_reverse_primary_denied_can_select_prebuilt_reduce_only_fallback(settings) -> None:
    account = _account_facts(position="0.01", equity="1000", available="1", leverage="20")
    price = _price(value="50000")
    _order_plan(settings=settings, ratio="-0.5", account=account, price=price, key="fallback")

    result = _risk_check(key="fallback")

    primary = CandidateOrderIntent.objects.get(intent_role=CandidateIntentRole.PRIMARY)
    fallback = CandidateOrderIntent.objects.get(intent_role=CandidateIntentRole.FALLBACK_REDUCE_ONLY)
    approved = ApprovedOrderIntent.objects.get()
    lock = OrderPlanActiveLock.objects.get()
    assert result.status == "succeeded"
    assert result.data["selected_intent_role"] == CandidateIntentRole.FALLBACK_REDUCE_ONLY
    assert approved.candidate_order_intent_id == fallback.id
    assert primary.status == CandidateIntentStatus.DENIED
    assert fallback.status == CandidateIntentStatus.APPROVED
    assert fallback.exchange_reduce_only is True
    assert lock.status == ActiveLockStatus.ACTIVE
    assert AlertEvent.objects.filter(source_module="RiskCheck", event_type="fallback_reduce_only_selected").count() == 1


def test_fallback_issue_links_to_the_exact_failed_rule_result(settings) -> None:
    account = _account_facts(position="0.01", equity="1000", available="1", leverage="20")
    price = _price(value="50000")
    _order_plan(settings=settings, ratio="-0.5", account=account, price=price, key="fallback-issue-link")

    result = _risk_check(key="fallback-issue-link")

    issue = RiskCheckIssue.objects.get(issue_code="available_margin_insufficient")
    assert result.status == "succeeded"
    assert issue.rule_result is not None
    assert issue.rule_result.status == "DENY"
    assert issue.rule_result.reason_code == "available_margin_insufficient"
    assert issue.rule_result.evidence["candidate_role"] == CandidateIntentRole.PRIMARY


def test_missing_leverage_blocks_increase_risk_and_releases_lock(settings) -> None:
    account = _account_facts(position="0", equity="1000", available="1000", leverage=None)
    price = _price(value="50000")
    _order_plan(settings=settings, ratio="0.5", account=account, price=price, key="missing-leverage")

    result = _risk_check(key="missing-leverage")

    assert result.status == "blocked"
    assert result.reason_code == "observed_exchange_leverage_missing"
    assert ApprovedOrderIntent.objects.count() == 0
    assert OrderPlanActiveLock.objects.get().status == ActiveLockStatus.RELEASED


def test_reduce_only_close_does_not_require_leverage(settings) -> None:
    account = _account_facts(position="0.01", equity="1000", available="1000", leverage=None)
    price = _price(value="50000")
    _order_plan(settings=settings, ratio="0", account=account, price=price, key="reduce-no-leverage")

    result = _risk_check(key="reduce-no-leverage")

    candidate = CandidateOrderIntent.objects.get()
    assert result.status == "succeeded"
    assert candidate.exchange_reduce_only is True
    assert ApprovedOrderIntent.objects.get().candidate_order_intent_id == candidate.id
    assert OrderPlanActiveLock.objects.get().status == ActiveLockStatus.ACTIVE


def test_stale_price_blocks_and_does_not_refresh(settings) -> None:
    account = _account_facts(position="0", equity="1000", available="1000", leverage="20")
    price = _price(value="50000")
    _order_plan(settings=settings, ratio="0.5", account=account, price=price, key="stale-price")
    PriceSnapshot = type(price)
    PriceSnapshot.objects.filter(id=price.id).update(expires_at_utc=timezone.now() - timedelta(seconds=1))

    result = _risk_check(key="stale-price")

    assert result.status == "blocked"
    assert result.reason_code == "price_snapshot_hash_mismatch"
    assert ApprovedOrderIntent.objects.count() == 0
    assert OrderPlanActiveLock.objects.get().status == ActiveLockStatus.RELEASED


def test_candidate_hash_tamper_blocks_without_approving(settings) -> None:
    account = _account_facts(position="0", equity="1000", available="1000", leverage="20")
    price = _price(value="50000")
    _order_plan(settings=settings, ratio="0.5", account=account, price=price, key="hash-tamper")
    CandidateOrderIntent.objects.update(requested_size=Decimal("0.021"))

    result = _risk_check(key="hash-tamper")

    assert result.status == "blocked"
    assert result.reason_code == "candidate_intent_hash_mismatch"
    assert ApprovedOrderIntent.objects.count() == 0
    assert OrderPlanActiveLock.objects.get().status == ActiveLockStatus.RELEASED


def test_dry_run_executes_rules_but_writes_no_risk_facts_or_alerts(settings) -> None:
    account = _account_facts(position="0", equity="1000", available="1000", leverage="20")
    price = _price(value="50000")
    _order_plan(settings=settings, ratio="0.5", account=account, price=price, key="dry-run")
    alert_count = AlertEvent.objects.count()

    result = _risk_check(key="dry-run", dry_run=True)

    assert result.status == "succeeded"
    assert result.data["dry_run"] is True
    assert RiskCheckResult.objects.count() == 0
    assert RiskRuleResult.objects.count() == 0
    assert ApprovedOrderIntent.objects.count() == 0
    assert AlertEvent.objects.count() == alert_count
    assert OrderPlanActiveLock.objects.get().status == ActiveLockStatus.ACTIVE


def test_rule_registry_missing_plugin_blocks(settings) -> None:
    from apps.risk_check.services.rule_registry import RiskRuleRegistry

    account = _account_facts(position="0", equity="1000", available="1000", leverage="20")
    price = _price(value="50000")
    _order_plan(settings=settings, ratio="0.5", account=account, price=price, key="missing-plugin")
    candidate = CandidateOrderIntent.objects.get()
    plan = candidate.order_plan

    result = run_risk_check(
        business_request_key="risk-missing-plugin",
        order_plan_id=plan.id,
        candidate_order_intent_id=candidate.id,
        binance_sync_run_id=plan.binance_sync_run_id,
        price_snapshot_id=plan.price_snapshot_id,
        active_lock_id=plan.active_lock_id,
        reference_time_utc=timezone.now(),
        risk_rule_set="p0_default",
        trace_id="trace-risk-missing-plugin",
        trigger_source="test",
        registry=RiskRuleRegistry(),
    )

    assert result.status == "blocked"
    assert result.reason_code == "risk_rule_plugin_missing"
    assert ApprovedOrderIntent.objects.count() == 0
