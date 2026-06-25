"""OrderPlan 模块：校验明确业务事实并生成 OrderPlan、候选意图和 ActiveLock；读写 MySQL；不访问 Redis 之外的上游价格缓存；不访问 Binance；不发送 Hermes；不调用大模型；不提交订单；不允许真实交易。"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from django.conf import settings
from django.db import DatabaseError, IntegrityError, transaction

from apps.binance_account_sync.models import (
    BinanceAccountSnapshot,
    BinanceBalanceSnapshot,
    BinancePositionMode,
    BinancePositionSnapshot,
    BinanceSymbolRuleSnapshot,
    BinanceSyncPurpose,
    BinanceSyncRun,
    BinanceSyncStatus,
)
from apps.binance_account_sync.selectors import (
    get_account_snapshot,
    get_balance_snapshot_for_asset,
    get_position_snapshot,
    get_symbol_rule_snapshot,
    verify_trade_preparation_snapshot_set,
)
from apps.binance_account_sync.services.hashing import stable_hash
from apps.binance_gateway.types import MARKET_TYPE_COIN_M, MARKET_TYPE_USDS_M, normalize_active_market_type
from apps.foundation.results import ResultStatus, ServiceResult
from apps.price_snapshot.models import PriceSnapshot
from apps.price_snapshot.selectors import load_price_snapshot_for_trading
from apps.price_snapshot.services.snapshot import compute_price_snapshot_hash, price_snapshot_hash_payload
from apps.strategy_analysis.models import AnalysisObjectStatus, DecisionSnapshot, DecisionTargetIntent

from ..domain import (
    IntentDraft,
    OrderPlanCalculationError,
    PlanDraft,
    TradingRule,
    build_trading_rule,
    calculate_order_plan,
)
from ..models import CandidateOrderIntent, CandidateIntentStatus, OrderPlan, OrderPlanStatus
from .active_lock import acquire_for_order_plan
from .alerts import record_order_plan_alert
from .hashing import candidate_intent_hash, decimal_hash_value, order_plan_hash


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class OrderPlanContext:
    decision_snapshot: DecisionSnapshot
    sync_run: BinanceSyncRun
    account_snapshot: BinanceAccountSnapshot
    balance_snapshot: BinanceBalanceSnapshot
    position_snapshot: BinancePositionSnapshot
    symbol_rule_snapshot: BinanceSymbolRuleSnapshot
    price_snapshot: PriceSnapshot


@dataclass(frozen=True)
class ContextLoadBlocked:
    reason_code: str
    message: str
    context: OrderPlanContext | None = None


def create_order_plan(
    *,
    business_request_key: str,
    decision_snapshot_id: int,
    binance_sync_run_id: int,
    price_snapshot_id: int,
    reference_time_utc: datetime,
    trace_id: str,
    trigger_source: str,
) -> ServiceResult:
    request_error = _request_error(
        business_request_key=business_request_key,
        decision_snapshot_id=decision_snapshot_id,
        binance_sync_run_id=binance_sync_run_id,
        price_snapshot_id=price_snapshot_id,
        reference_time_utc=reference_time_utc,
        trace_id=trace_id,
        trigger_source=trigger_source,
    )
    if request_error:
        return _blocked_without_plan(
            reason_code=request_error,
            message="OrderPlan 请求合同不完整",
            business_request_key=business_request_key or "invalid-order-plan-request",
            trace_id=trace_id,
            trigger_source=trigger_source,
        )
    reference_time = _ensure_utc(reference_time_utc)
    config, config_error = _load_config()
    if config_error:
        return _blocked_without_plan(
            reason_code=config_error,
            message="OrderPlan 配置不可用",
            business_request_key=business_request_key,
            trace_id=trace_id,
            trigger_source=trigger_source,
        )

    try:
        existing = OrderPlan.objects.filter(business_request_key=business_request_key).first()
    except DatabaseError as exc:
        return _failed_persist_result(
            business_request_key=business_request_key,
            trace_id=trace_id,
            trigger_source=trigger_source,
            error_type=type(exc).__name__,
        )
    if existing is not None:
        if not _existing_matches(
            existing,
            decision_snapshot_id=decision_snapshot_id,
            binance_sync_run_id=binance_sync_run_id,
            price_snapshot_id=price_snapshot_id,
            config=config,
        ):
            return _blocked_without_plan(
                reason_code="order_plan_input_conflict",
                message="business_request_key 已绑定另一组 OrderPlan 输入",
                business_request_key=business_request_key,
                trace_id=trace_id,
                trigger_source=trigger_source,
            )
        try:
            replay_error = _existing_integrity_error(
                existing,
                trace_id=trace_id,
                trigger_source=trigger_source,
            )
        except DatabaseError as exc:
            return _failed_persist_result(
                business_request_key=business_request_key,
                trace_id=trace_id,
                trigger_source=trigger_source,
                error_type=type(exc).__name__,
            )
        if replay_error:
            return _blocked_without_plan(
                reason_code=replay_error,
                message="既有 OrderPlan 的上游事实已无法通过完整性复核",
                business_request_key=business_request_key,
                trace_id=trace_id,
                trigger_source=trigger_source,
            )
        return _result_from_plan(existing, trace_id=trace_id, trigger_source=trigger_source)

    try:
        context_result = _load_context(
            decision_snapshot_id=decision_snapshot_id,
            binance_sync_run_id=binance_sync_run_id,
            price_snapshot_id=price_snapshot_id,
            reference_time_utc=reference_time,
            trace_id=trace_id,
            trigger_source=trigger_source,
        )
    except DatabaseError as exc:
        return _failed_persist_result(
            business_request_key=business_request_key,
            trace_id=trace_id,
            trigger_source=trigger_source,
            error_type=type(exc).__name__,
        )
    if isinstance(context_result, ContextLoadBlocked):
        if context_result.context is not None:
            return _persist_calculation_block(
                context=context_result.context,
                config=config,
                business_request_key=business_request_key,
                reason_code=context_result.reason_code,
                message=context_result.message,
                trace_id=trace_id,
                trigger_source=trigger_source,
            )
        return _blocked_without_plan(
            reason_code=context_result.reason_code,
            message=context_result.message,
            business_request_key=business_request_key,
            trace_id=trace_id,
            trigger_source=trigger_source,
        )
    context = context_result
    try:
        rule = _trading_rule(context)
        draft = calculate_order_plan(
            market_type=context.sync_run.market_type,
            target_position_ratio=context.decision_snapshot.target_position_ratio,
            current_equity=_current_equity(context),
            current_signed_size=context.position_snapshot.position_amount,
            mark_price=context.price_snapshot.mark_price,
            max_target_notional_to_equity_ratio=config["max_target_notional_to_equity_ratio"],
            min_rebalance_notional=config["min_rebalance_notional"],
            rule=rule,
        )
    except OrderPlanCalculationError as exc:
        return _persist_calculation_block(
            context=context,
            config=config,
            business_request_key=business_request_key,
            reason_code=exc.reason_code,
            message=exc.message,
            trace_id=trace_id,
            trigger_source=trigger_source,
        )

    return _persist_order_plan(
        context=context,
        draft=draft,
        config=config,
        business_request_key=business_request_key,
        decision_snapshot_id=decision_snapshot_id,
        binance_sync_run_id=binance_sync_run_id,
        price_snapshot_id=price_snapshot_id,
        trace_id=trace_id,
        trigger_source=trigger_source,
    )


def _persist_order_plan(
    *,
    context: OrderPlanContext,
    draft: PlanDraft,
    config: dict[str, Any],
    business_request_key: str,
    decision_snapshot_id: int,
    binance_sync_run_id: int,
    price_snapshot_id: int,
    trace_id: str,
    trigger_source: str,
) -> ServiceResult:
    try:
        with transaction.atomic():
            existing = OrderPlan.objects.select_for_update().filter(business_request_key=business_request_key).first()
            if existing is not None:
                if not _existing_matches(
                    existing,
                    decision_snapshot_id=decision_snapshot_id,
                    binance_sync_run_id=binance_sync_run_id,
                    price_snapshot_id=price_snapshot_id,
                    config=config,
                ):
                    raise OrderPlanCalculationError("order_plan_input_conflict", "并发请求绑定了另一组 OrderPlan 输入")
                return _result_from_plan(existing, trace_id=trace_id, trigger_source=trigger_source)
            plan = _create_plan_model(
                context=context,
                draft=draft,
                config=config,
                business_request_key=business_request_key,
                trace_id=trace_id,
                trigger_source=trigger_source,
            )
            if draft.status == OrderPlanStatus.NO_ORDER_REQUIRED:
                _write_plan_outcome_alert(plan)
                return _result_from_plan(plan, trace_id=trace_id, trigger_source=trigger_source)
            return _acquire_lock_and_create_candidates(
                plan=plan,
                context=context,
                draft=draft,
                trace_id=trace_id,
                trigger_source=trigger_source,
            )
    except OrderPlanCalculationError as exc:
        return _blocked_without_plan(
            reason_code=exc.reason_code,
            message=exc.message,
            business_request_key=business_request_key,
            trace_id=trace_id,
            trigger_source=trigger_source,
        )
    except IntegrityError:
        concurrent = OrderPlan.objects.filter(business_request_key=business_request_key).first()
        if concurrent is not None:
            if _existing_matches(
                concurrent,
                decision_snapshot_id=decision_snapshot_id,
                binance_sync_run_id=binance_sync_run_id,
                price_snapshot_id=price_snapshot_id,
                config=config,
            ):
                return _result_from_plan(concurrent, trace_id=trace_id, trigger_source=trigger_source)
            return _blocked_without_plan(
                reason_code="order_plan_input_conflict",
                message="并发请求已使用相同 business_request_key 创建另一份 OrderPlan",
                business_request_key=business_request_key,
                trace_id=trace_id,
                trigger_source=trigger_source,
            )
        return _failed_persist_result(
            business_request_key=business_request_key,
            trace_id=trace_id,
            trigger_source=trigger_source,
            error_type="IntegrityError",
        )
    except DatabaseError as exc:
        logger.exception("OrderPlan 写入失败 business_request_key=%s", business_request_key)
        return _failed_persist_result(
            business_request_key=business_request_key,
            trace_id=trace_id,
            trigger_source=trigger_source,
            error_type=type(exc).__name__,
        )


def _acquire_lock_and_create_candidates(
    *,
    plan: OrderPlan,
    context: OrderPlanContext,
    draft: PlanDraft,
    trace_id: str,
    trigger_source: str,
) -> ServiceResult:
    lock_result = acquire_for_order_plan(order_plan=plan, trace_id=trace_id, trigger_source=trigger_source)
    if not lock_result.acquired:
        _block_plan_for_lock(
            plan,
            reason_code=lock_result.reason_code,
            conflicting_lock_id=lock_result.active_lock.id,
        )
        return _result_from_plan(plan, trace_id=trace_id, trigger_source=trigger_source)
    plan.active_lock = lock_result.active_lock
    plan.save(update_fields=["active_lock"])
    assert draft.primary is not None
    primary = _create_candidate(plan=plan, context=context, draft=draft.primary, trace_id=trace_id)
    fallback = None
    if draft.fallback is not None:
        fallback = _create_candidate(plan=plan, context=context, draft=draft.fallback, trace_id=trace_id)
    _write_candidate_alert(plan=plan, candidate=primary)
    if fallback is not None:
        _write_candidate_alert(plan=plan, candidate=fallback)
    return _result_from_plan(plan, trace_id=trace_id, trigger_source=trigger_source)


def _load_context(
    *,
    decision_snapshot_id: int,
    binance_sync_run_id: int,
    price_snapshot_id: int,
    reference_time_utc: datetime,
    trace_id: str,
    trigger_source: str,
) -> OrderPlanContext | ContextLoadBlocked:
    try:
        decision = DecisionSnapshot.objects.get(id=decision_snapshot_id)
    except DecisionSnapshot.DoesNotExist:
        return ContextLoadBlocked("decision_snapshot_not_found", "DecisionSnapshot 不存在")
    try:
        sync_run = BinanceSyncRun.objects.get(id=binance_sync_run_id)
        price_snapshot = PriceSnapshot.objects.get(id=price_snapshot_id)
    except BinanceSyncRun.DoesNotExist:
        return ContextLoadBlocked("binance_sync_run_not_found", "BinanceSyncRun 不存在")
    except PriceSnapshot.DoesNotExist:
        return ContextLoadBlocked("price_snapshot_not_found", "PriceSnapshot 不存在")
    identity_error = _top_level_identity_error(sync_run, price_snapshot)
    if identity_error:
        return ContextLoadBlocked(identity_error, "账户事实与价格事实市场身份不一致")
    try:
        account_snapshot = get_account_snapshot(sync_run.id)
        position_snapshot = get_position_snapshot(sync_run.id, price_snapshot.symbol)
        symbol_rule_snapshot = get_symbol_rule_snapshot(sync_run.id, price_snapshot.symbol)
        required_asset = _required_balance_asset(sync_run.market_type, symbol_rule_snapshot)
        balance_snapshot = get_balance_snapshot_for_asset(sync_run.id, required_asset)
    except BinanceAccountSnapshot.DoesNotExist:
        return ContextLoadBlocked("account_snapshot_missing", "账户快照不存在")
    except BinancePositionSnapshot.DoesNotExist:
        return ContextLoadBlocked("position_snapshot_missing", "目标持仓快照不存在")
    except BinanceSymbolRuleSnapshot.DoesNotExist:
        return ContextLoadBlocked("symbol_rule_snapshot_missing", "目标交易规则快照不存在")
    except BinanceBalanceSnapshot.DoesNotExist:
        return ContextLoadBlocked("balance_snapshot_missing", "目标保证金或结算资产余额快照不存在")
    context = OrderPlanContext(
        decision_snapshot=decision,
        sync_run=sync_run,
        account_snapshot=account_snapshot,
        balance_snapshot=balance_snapshot,
        position_snapshot=position_snapshot,
        symbol_rule_snapshot=symbol_rule_snapshot,
        price_snapshot=price_snapshot,
    )
    decision_error = _decision_error(decision, reference_time_utc)
    if decision_error:
        return ContextLoadBlocked(decision_error, "DecisionSnapshot 不可供 OrderPlan 消费", context)
    sync_error = _sync_run_error(sync_run, reference_time_utc, price_snapshot.symbol)
    if sync_error:
        return ContextLoadBlocked(sync_error, "BinanceSyncRun 不可供 OrderPlan 消费", context)
    child_error = _child_fact_error(context)
    if child_error:
        return ContextLoadBlocked(child_error, "账户子快照身份或指纹不可用", context)
    integrity_result = verify_trade_preparation_snapshot_set(
        sync_run_id=sync_run.id,
        trace_id=trace_id,
        trigger_source=trigger_source,
    )
    if integrity_result.status != ResultStatus.SUCCEEDED:
        return ContextLoadBlocked(integrity_result.reason_code, integrity_result.message, context)
    price_model_error = _price_model_error(price_snapshot)
    if price_model_error:
        return ContextLoadBlocked(price_model_error, "PriceSnapshot MySQL 事实指纹不一致", context)
    price_result = load_price_snapshot_for_trading(
        price_snapshot_id=price_snapshot.id,
        reference_time_utc=reference_time_utc,
        expected_market_type=sync_run.market_type,
        expected_account_domain=sync_run.account_domain,
        expected_symbol=price_snapshot.symbol,
        trace_id=trace_id,
        trigger_source=trigger_source,
    )
    if price_result.status != ResultStatus.SUCCEEDED:
        return ContextLoadBlocked(price_result.reason_code, price_result.message, context)
    if (
        price_result.data.get("price_snapshot_hash") != price_snapshot.price_snapshot_hash
        or Decimal(str(price_result.data.get("mark_price"))) != price_snapshot.mark_price
    ):
        return ContextLoadBlocked(
            "price_snapshot_cache_database_mismatch",
            "PriceSnapshot 缓存摘要与 MySQL 事实不一致",
            context,
        )
    return context


def _decision_error(decision: DecisionSnapshot, reference_time_utc: datetime) -> str:
    if decision.status != AnalysisObjectStatus.CREATED or not decision.is_usable:
        return "decision_snapshot_not_usable"
    if decision.target_intent != DecisionTargetIntent.TARGET_POSITION or not decision.allows_order_plan:
        return "decision_snapshot_not_orderable"
    if decision.target_position_ratio is None:
        return "target_position_ratio_missing"
    if decision.expires_at_utc is None or reference_time_utc > decision.expires_at_utc:
        return "decision_snapshot_expired"
    return ""


def _sync_run_error(sync_run: BinanceSyncRun, reference_time_utc: datetime, symbol: str) -> str:
    if sync_run.status != BinanceSyncStatus.SUCCEEDED:
        return "binance_sync_run_not_succeeded"
    if sync_run.sync_purpose != BinanceSyncPurpose.TRADE_PREPARATION:
        return "binance_sync_run_not_trade_preparation"
    if sync_run.position_mode != BinancePositionMode.ONE_WAY:
        return "position_mode_not_supported"
    if sync_run.expires_at_utc is None or reference_time_utc > sync_run.expires_at_utc:
        return "binance_sync_run_expired"
    if symbol not in {str(item).upper() for item in sync_run.requested_symbols}:
        return "symbol_not_in_sync_run"
    if not sync_run.snapshot_set_hash:
        return "snapshot_set_hash_missing"
    return ""


def _top_level_identity_error(sync_run: BinanceSyncRun, price_snapshot: PriceSnapshot) -> str:
    if sync_run.exchange.lower() != "binance":
        return "exchange_not_supported"
    if sync_run.market_type not in {MARKET_TYPE_USDS_M, MARKET_TYPE_COIN_M}:
        return "market_type_not_supported"
    if sync_run.exchange.lower() != price_snapshot.exchange.lower():
        return "exchange_identity_mismatch"
    if sync_run.market_type != price_snapshot.market_type:
        return "market_type_identity_mismatch"
    if sync_run.account_domain != price_snapshot.account_domain:
        return "account_domain_identity_mismatch"
    return ""


def _required_balance_asset(market_type: str, rule: BinanceSymbolRuleSnapshot) -> str:
    if market_type == MARKET_TYPE_COIN_M:
        return str(rule.settlement_asset or rule.margin_asset).upper()
    return str(rule.margin_asset or rule.quote_asset).upper()


def _price_model_error(snapshot: PriceSnapshot) -> str:
    expected_hash = compute_price_snapshot_hash(
        price_snapshot_hash_payload(
            business_request_key=snapshot.business_request_key,
            exchange=snapshot.exchange,
            market_type=snapshot.market_type,
            account_domain=snapshot.account_domain,
            symbol=snapshot.symbol,
            price_type=snapshot.price_type,
            mark_price=snapshot.mark_price,
            price_unit=snapshot.price_unit,
            source=snapshot.source,
            source_operation=snapshot.source_operation,
            source_update_time_utc=snapshot.source_update_time_utc,
            as_of_utc=snapshot.as_of_utc,
            expires_at_utc=snapshot.expires_at_utc,
        )
    )
    return "" if expected_hash == snapshot.price_snapshot_hash else "price_snapshot_hash_mismatch"


def _child_fact_error(context: OrderPlanContext) -> str:
    identity = (context.sync_run.market_type, context.sync_run.account_domain)
    for snapshot in (
        context.account_snapshot,
        context.balance_snapshot,
        context.position_snapshot,
        context.symbol_rule_snapshot,
    ):
        if (snapshot.market_type, snapshot.account_domain) != identity:
            return "account_child_identity_mismatch"
        if not snapshot.snapshot_hash:
            return "account_child_hash_missing"
    if context.account_snapshot.position_mode != BinancePositionMode.ONE_WAY:
        return "position_mode_not_supported"
    if context.position_snapshot.position_mode_observed != BinancePositionMode.ONE_WAY:
        return "position_mode_not_supported"
    if context.position_snapshot.symbol != context.price_snapshot.symbol:
        return "position_symbol_mismatch"
    if context.symbol_rule_snapshot.symbol != context.price_snapshot.symbol:
        return "symbol_rule_symbol_mismatch"
    if "MARKET" not in {str(item).upper() for item in context.symbol_rule_snapshot.supported_order_types}:
        return "market_order_not_supported"
    return ""


def _current_equity(context: OrderPlanContext) -> Decimal:
    equity = context.account_snapshot.total_margin_balance
    if equity is None:
        raise OrderPlanCalculationError("current_equity_missing", "账户快照缺少包含未实现盈亏的 margin balance")
    return equity


def _trading_rule(context: OrderPlanContext) -> TradingRule:
    rule = context.symbol_rule_snapshot
    return build_trading_rule(
        step_size=rule.step_size,
        min_quantity=rule.min_quantity,
        max_quantity=rule.max_quantity,
        min_notional=rule.min_notional,
        quantity_precision=rule.quantity_precision,
        contract_size=rule.contract_size,
        base_asset=rule.base_asset,
        market_type=context.sync_run.market_type,
    )


def _create_plan_model(
    *,
    context: OrderPlanContext,
    draft: PlanDraft,
    config: dict[str, Any],
    business_request_key: str,
    trace_id: str,
    trigger_source: str,
) -> OrderPlan:
    plan_hash = _build_plan_hash(context=context, draft=draft, config=config, business_request_key=business_request_key)
    return OrderPlan.objects.create(
        business_request_key=business_request_key,
        decision_snapshot=context.decision_snapshot,
        binance_sync_run=context.sync_run,
        account_snapshot=context.account_snapshot,
        balance_snapshot=context.balance_snapshot,
        position_snapshot=context.position_snapshot,
        symbol_rule_snapshot=context.symbol_rule_snapshot,
        price_snapshot=context.price_snapshot,
        exchange=context.sync_run.exchange,
        market_type=context.sync_run.market_type,
        account_domain=context.sync_run.account_domain,
        symbol=context.price_snapshot.symbol,
        position_mode=context.sync_run.position_mode,
        target_position_ratio=context.decision_snapshot.target_position_ratio,
        current_equity=draft.current_equity,
        current_signed_size=draft.current_signed_size,
        raw_target_signed_size=draft.raw_target_signed_size,
        target_signed_size=draft.target_signed_size,
        delta_signed_size=draft.delta_signed_size,
        mark_price=context.price_snapshot.mark_price,
        target_notional=draft.target_notional,
        normalized_order_notional=draft.normalized_order_notional,
        min_rebalance_notional=config["min_rebalance_notional"],
        max_target_notional_to_equity_ratio=config["max_target_notional_to_equity_ratio"],
        status=draft.status,
        reason_code=draft.reason_code,
        allows_downstream=draft.status == OrderPlanStatus.CREATED,
        config_snapshot=config,
        calculation_evidence=_calculation_evidence(context=context, draft=draft),
        order_plan_hash=plan_hash,
        trace_id=trace_id,
        trigger_source=trigger_source,
    )


def _create_candidate(
    *,
    plan: OrderPlan,
    context: OrderPlanContext,
    draft: IntentDraft,
    trace_id: str,
) -> CandidateOrderIntent:
    payload = {
        "order_plan_hash": plan.order_plan_hash,
        "intent_role": draft.intent_role,
        "plan_type": draft.plan_type,
        "side": draft.side,
        "exchange_reduce_only": draft.exchange_reduce_only,
        "requested_size": decimal_hash_value(draft.requested_size),
        "requested_notional": decimal_hash_value(draft.requested_notional),
        "requested_size_unit": draft.requested_size_unit,
        "order_components": draft.order_components,
        "price_snapshot_hash": context.price_snapshot.price_snapshot_hash,
        "snapshot_set_hash": context.sync_run.snapshot_set_hash,
    }
    return CandidateOrderIntent.objects.create(
        order_plan=plan,
        intent_role=draft.intent_role,
        symbol=plan.symbol,
        market_type=plan.market_type,
        account_domain=plan.account_domain,
        position_mode=plan.position_mode,
        order_type="MARKET",
        plan_type=draft.plan_type,
        side=draft.side,
        position_side="BOTH",
        exchange_reduce_only=draft.exchange_reduce_only,
        requested_size=draft.requested_size,
        requested_notional=draft.requested_notional,
        requested_size_unit=draft.requested_size_unit,
        price_snapshot=context.price_snapshot,
        reference_mark_price=context.price_snapshot.mark_price,
        binance_sync_run=context.sync_run,
        current_position_snapshot=context.position_snapshot,
        symbol_rule_snapshot=context.symbol_rule_snapshot,
        current_position_signed_size=plan.current_signed_size,
        target_position_signed_size=plan.target_signed_size,
        delta_signed_size=plan.delta_signed_size,
        closing_size=draft.closing_size,
        opening_size=draft.opening_size,
        residual_position_size=draft.residual_position_size,
        order_components=draft.order_components,
        status=CandidateIntentStatus.PENDING_RISK_CHECK,
        reason_code="candidate_intent_generated",
        evidence={
            "decision_snapshot_id": context.decision_snapshot.id,
            "binance_sync_run_id": context.sync_run.id,
            "price_snapshot_id": context.price_snapshot.id,
            "order_plan_hash": plan.order_plan_hash,
        },
        intent_hash=candidate_intent_hash(payload),
        trace_id=trace_id,
    )


def _persist_calculation_block(
    *,
    context: OrderPlanContext,
    config: dict[str, Any],
    business_request_key: str,
    reason_code: str,
    message: str,
    trace_id: str,
    trigger_source: str,
) -> ServiceResult:
    zero = Decimal("0")
    blocked_draft = PlanDraft(
        current_equity=context.account_snapshot.total_margin_balance or zero,
        current_signed_size=context.position_snapshot.position_amount or zero,
        raw_target_signed_size=zero,
        target_signed_size=zero,
        delta_signed_size=zero,
        target_notional=zero,
        normalized_order_notional=zero,
        status=OrderPlanStatus.BLOCKED,
        reason_code=reason_code,
        primary=None,
        fallback=None,
    )
    try:
        with transaction.atomic():
            existing = OrderPlan.objects.select_for_update().filter(business_request_key=business_request_key).first()
            if existing is not None:
                if not _existing_matches(
                    existing,
                    decision_snapshot_id=context.decision_snapshot.id,
                    binance_sync_run_id=context.sync_run.id,
                    price_snapshot_id=context.price_snapshot.id,
                    config=config,
                ):
                    return _blocked_without_plan(
                        reason_code="order_plan_input_conflict",
                        message="business_request_key 已由另一组 OrderPlan 输入占用",
                        business_request_key=business_request_key,
                        trace_id=trace_id,
                        trigger_source=trigger_source,
                    )
                return _result_from_plan(existing, trace_id=trace_id, trigger_source=trigger_source)
            plan = _create_plan_model(
                context=context,
                draft=blocked_draft,
                config=config,
                business_request_key=business_request_key,
                trace_id=trace_id,
                trigger_source=trigger_source,
            )
            record_order_plan_alert(
                event_type="order_plan_blocked",
                business_request_key=business_request_key,
                trace_id=trace_id,
                trigger_source=trigger_source,
                status=OrderPlanStatus.BLOCKED,
                reason_code=reason_code,
                message=message,
                order_plan_id=plan.id,
            )
            _write_candidate_not_created_alert(plan=plan, event_type="candidate_order_intent_blocked")
            return _result_from_plan(plan, trace_id=trace_id, trigger_source=trigger_source)
    except IntegrityError:
        concurrent = OrderPlan.objects.filter(business_request_key=business_request_key).first()
        if concurrent is not None and _existing_matches(
            concurrent,
            decision_snapshot_id=context.decision_snapshot.id,
            binance_sync_run_id=context.sync_run.id,
            price_snapshot_id=context.price_snapshot.id,
            config=config,
        ):
            return _result_from_plan(concurrent, trace_id=trace_id, trigger_source=trigger_source)
        return _blocked_without_plan(
            reason_code="order_plan_input_conflict",
            message="并发请求已使用相同 business_request_key 创建另一份 OrderPlan",
            business_request_key=business_request_key,
            trace_id=trace_id,
            trigger_source=trigger_source,
        )
    except DatabaseError as exc:
        return _failed_persist_result(
            business_request_key=business_request_key,
            trace_id=trace_id,
            trigger_source=trigger_source,
            error_type=type(exc).__name__,
        )


def _block_plan_for_lock(plan: OrderPlan, *, reason_code: str, conflicting_lock_id: int) -> None:
    plan.status = OrderPlanStatus.BLOCKED
    plan.reason_code = reason_code
    plan.allows_downstream = False
    plan.save(update_fields=["status", "reason_code", "allows_downstream"])
    record_order_plan_alert(
        event_type="order_plan_blocked",
        business_request_key=plan.business_request_key,
        trace_id=plan.trace_id,
        trigger_source=plan.trigger_source,
        status=plan.status,
        reason_code=reason_code,
        message="OrderPlan 因同一交易身份的 ActiveLock 状态被阻断。",
        order_plan_id=plan.id,
        payload_summary={"symbol": plan.symbol, "active_lock_id": conflicting_lock_id},
    )
    _write_candidate_not_created_alert(plan=plan, event_type="candidate_order_intent_blocked")


def _load_config() -> tuple[dict[str, Any], str]:
    if not getattr(settings, "ORDER_PLAN_ENABLED", False):
        return {}, "order_plan_disabled"
    supported = {
        normalize_active_market_type(item)
        for item in getattr(settings, "ORDER_PLAN_SUPPORTED_MARKET_TYPES", [])
    }
    maximum_ratio = getattr(settings, "ORDER_PLAN_MAX_TARGET_NOTIONAL_TO_EQUITY_RATIO", None)
    minimum_notional = getattr(settings, "ORDER_PLAN_MIN_REBALANCE_NOTIONAL", None)
    if (
        supported != {MARKET_TYPE_USDS_M, MARKET_TYPE_COIN_M}
        or getattr(settings, "ORDER_PLAN_TARGET_NOTIONAL_BASIS", "") != "current_equity"
        or getattr(settings, "ORDER_PLAN_SUPPORTED_POSITION_MODE", "") != "one_way"
        or getattr(settings, "ORDER_PLAN_SUPPORTED_ORDER_TYPE", "") != "MARKET"
        or not isinstance(maximum_ratio, Decimal)
        or not isinstance(minimum_notional, Decimal)
        or not maximum_ratio.is_finite()
        or not minimum_notional.is_finite()
        or maximum_ratio <= 0
        or minimum_notional < 0
    ):
        return {}, "order_plan_config_invalid"
    config = {
        "schema_version": "1.0",
        "supported_market_types": sorted(supported),
        "target_notional_basis": "current_equity",
        "max_target_notional_to_equity_ratio": maximum_ratio,
        "min_rebalance_notional": minimum_notional,
        "supported_position_mode": "one_way",
        "supported_order_type": "MARKET",
    }
    config["config_hash"] = stable_hash({key: str(value) if isinstance(value, Decimal) else value for key, value in config.items()})
    config["max_target_notional_to_equity_ratio"] = str(maximum_ratio)
    config["min_rebalance_notional"] = str(minimum_notional)
    return config, ""


def _existing_matches(
    plan: OrderPlan,
    *,
    decision_snapshot_id: int,
    binance_sync_run_id: int,
    price_snapshot_id: int,
    config: dict[str, Any],
) -> bool:
    return (
        plan.decision_snapshot_id == decision_snapshot_id
        and plan.binance_sync_run_id == binance_sync_run_id
        and plan.price_snapshot_id == price_snapshot_id
        and plan.config_snapshot.get("config_hash") == config.get("config_hash")
    )


def _existing_integrity_error(
    plan: OrderPlan,
    *,
    trace_id: str,
    trigger_source: str,
) -> str:
    if plan.decision_snapshot.target_position_ratio != plan.target_position_ratio:
        return "decision_snapshot_changed_after_order_plan"
    decision = plan.decision_snapshot
    if (
        plan.calculation_evidence.get("target_intent") != decision.target_intent
        or plan.calculation_evidence.get("decision_policy_code") != decision.policy_code
        or plan.calculation_evidence.get("decision_policy_version") != decision.policy_version
        or plan.calculation_evidence.get("decision_definition_hash") != decision.definition_hash
        or plan.calculation_evidence.get("decision_release_hash") != decision.release_hash
        or plan.calculation_evidence.get("decision_is_usable") is not decision.is_usable
        or plan.calculation_evidence.get("decision_allows_order_plan") is not decision.allows_order_plan
    ):
        return "decision_snapshot_changed_after_order_plan"
    if plan.binance_sync_run.snapshot_set_hash != plan.calculation_evidence.get("snapshot_set_hash"):
        return "snapshot_set_hash_mismatch"
    if plan.price_snapshot.price_snapshot_hash != plan.calculation_evidence.get("price_snapshot_hash"):
        return "price_snapshot_hash_mismatch"
    integrity_result = verify_trade_preparation_snapshot_set(
        sync_run_id=plan.binance_sync_run_id,
        trace_id=trace_id,
        trigger_source=trigger_source,
    )
    if integrity_result.status != ResultStatus.SUCCEEDED:
        return integrity_result.reason_code
    return _price_model_error(plan.price_snapshot)


def _build_plan_hash(
    *,
    context: OrderPlanContext,
    draft: PlanDraft,
    config: dict[str, Any],
    business_request_key: str,
) -> str:
    return order_plan_hash(
        {
            "business_request_key": business_request_key,
            "decision_snapshot_id": context.decision_snapshot.id,
            "decision_definition_hash": context.decision_snapshot.definition_hash,
            "decision_release_hash": context.decision_snapshot.release_hash,
            "binance_sync_run_id": context.sync_run.id,
            "snapshot_set_hash": context.sync_run.snapshot_set_hash,
            "price_snapshot_id": context.price_snapshot.id,
            "price_snapshot_hash": context.price_snapshot.price_snapshot_hash,
            "market_type": context.sync_run.market_type,
            "account_domain": context.sync_run.account_domain,
            "symbol": context.price_snapshot.symbol,
            "target_position_ratio": str(context.decision_snapshot.target_position_ratio),
            "current_equity": str(draft.current_equity),
            "current_signed_size": str(draft.current_signed_size),
            "target_signed_size": str(draft.target_signed_size),
            "delta_signed_size": str(draft.delta_signed_size),
            "mark_price": str(context.price_snapshot.mark_price),
            "config_hash": config["config_hash"],
        }
    )


def _calculation_evidence(*, context: OrderPlanContext, draft: PlanDraft) -> dict[str, Any]:
    return {
        "decision_snapshot_id": context.decision_snapshot.id,
        "target_intent": context.decision_snapshot.target_intent,
        "decision_policy_code": context.decision_snapshot.policy_code,
        "decision_policy_version": context.decision_snapshot.policy_version,
        "decision_definition_hash": context.decision_snapshot.definition_hash,
        "decision_release_hash": context.decision_snapshot.release_hash,
        "decision_is_usable": context.decision_snapshot.is_usable,
        "decision_allows_order_plan": context.decision_snapshot.allows_order_plan,
        "account_snapshot_id": context.account_snapshot.id,
        "balance_snapshot_id": context.balance_snapshot.id,
        "position_snapshot_id": context.position_snapshot.id,
        "symbol_rule_snapshot_id": context.symbol_rule_snapshot.id,
        "snapshot_set_hash": context.sync_run.snapshot_set_hash,
        "price_snapshot_hash": context.price_snapshot.price_snapshot_hash,
        "current_equity": str(draft.current_equity),
        "raw_target_signed_size": str(draft.raw_target_signed_size),
        "target_signed_size": str(draft.target_signed_size),
        "delta_signed_size": str(draft.delta_signed_size),
        "target_notional": str(draft.target_notional),
        "normalized_order_notional": str(draft.normalized_order_notional),
    }


def _write_plan_outcome_alert(plan: OrderPlan) -> None:
    record_order_plan_alert(
        event_type="order_plan_no_order_required",
        business_request_key=plan.business_request_key,
        trace_id=plan.trace_id,
        trigger_source=plan.trigger_source,
        status=plan.status,
        reason_code=plan.reason_code,
        message="目标仓位与当前仓位无需形成合法候选订单，本轮订单链正常结束。",
        order_plan_id=plan.id,
        payload_summary={"symbol": plan.symbol, "normalized_order_notional": str(plan.normalized_order_notional)},
    )
    _write_candidate_not_created_alert(plan=plan, event_type="candidate_order_intent_skipped")


def _write_candidate_alert(*, plan: OrderPlan, candidate: CandidateOrderIntent) -> None:
    record_order_plan_alert(
        event_type="candidate_order_intent_generated",
        business_request_key=plan.business_request_key,
        trace_id=plan.trace_id,
        trigger_source=plan.trigger_source,
        status=plan.status,
        reason_code=f"candidate_{candidate.intent_role}_generated",
        message="OrderPlan 已生成不可直接提交的候选订单意图，等待 RiskCheck 审批。",
        order_plan_id=plan.id,
        payload_summary={
            "candidate_order_intent_id": candidate.id,
            "intent_role": candidate.intent_role,
            "side": candidate.side,
            "requested_size": str(candidate.requested_size),
            "exchange_reduce_only": candidate.exchange_reduce_only,
        },
    )


def _write_candidate_not_created_alert(*, plan: OrderPlan, event_type: str) -> None:
    record_order_plan_alert(
        event_type=event_type,
        business_request_key=plan.business_request_key,
        trace_id=plan.trace_id,
        trigger_source=plan.trigger_source,
        status=plan.status,
        reason_code=plan.reason_code,
        message="本轮没有生成 CandidateOrderIntent。",
        order_plan_id=plan.id,
        payload_summary={"symbol": plan.symbol},
    )


def _result_from_plan(plan: OrderPlan, *, trace_id: str, trigger_source: str) -> ServiceResult:
    candidates = list(plan.candidate_intents.order_by("id").values_list("id", "intent_role"))
    status = ResultStatus.SUCCEEDED
    if plan.status == OrderPlanStatus.NO_ORDER_REQUIRED:
        status = ResultStatus.NO_ACTION
    elif plan.status == OrderPlanStatus.BLOCKED:
        status = ResultStatus.BLOCKED
    elif plan.status == OrderPlanStatus.FAILED:
        status = ResultStatus.FAILED
    data = {
        "order_plan_id": plan.id,
        "order_plan_status": plan.status,
        "allows_downstream": plan.allows_downstream,
        "active_lock_id": plan.active_lock_id,
        "candidate_order_intent_ids": [item[0] for item in candidates],
        "primary_candidate_order_intent_id": next((item[0] for item in candidates if item[1] == "primary"), None),
        "fallback_candidate_order_intent_id": next((item[0] for item in candidates if item[1] == "fallback_reduce_only"), None),
        "business_request_key": plan.business_request_key,
        "market_type": plan.market_type,
        "account_domain": plan.account_domain,
        "symbol": plan.symbol,
        "order_plan_hash": plan.order_plan_hash,
    }
    return ServiceResult(status, plan.reason_code, "OrderPlan 已完成", trace_id, trigger_source, data)


def _blocked_without_plan(
    *,
    reason_code: str,
    message: str,
    business_request_key: str,
    trace_id: str,
    trigger_source: str,
) -> ServiceResult:
    record_order_plan_alert(
        event_type="order_plan_blocked",
        business_request_key=business_request_key,
        trace_id=trace_id,
        trigger_source=trigger_source,
        status=OrderPlanStatus.BLOCKED,
        reason_code=reason_code,
        message=message,
    )
    return ServiceResult(ResultStatus.BLOCKED, reason_code, message, trace_id, trigger_source, _empty_result_data())


def _failed_persist_result(
    *,
    business_request_key: str,
    trace_id: str,
    trigger_source: str,
    error_type: str,
) -> ServiceResult:
    record_order_plan_alert(
        event_type="order_plan_failed",
        business_request_key=business_request_key,
        trace_id=trace_id,
        trigger_source=trigger_source,
        status=OrderPlanStatus.FAILED,
        reason_code="order_plan_persist_failed",
        message="OrderPlan 数据库事务失败，没有形成可供下游消费的候选订单链路。",
        payload_summary={"error_type": error_type},
    )
    return ServiceResult(
        ResultStatus.FAILED,
        "order_plan_persist_failed",
        "OrderPlan 数据库写入失败",
        trace_id,
        trigger_source,
        _empty_result_data(),
    )


def _request_error(**values: Any) -> str:
    key = values["business_request_key"]
    if not isinstance(key, str) or not key.strip() or len(key) > 191:
        return "business_request_key_invalid"
    for field_name in ("decision_snapshot_id", "binance_sync_run_id", "price_snapshot_id"):
        if not isinstance(values[field_name], int) or values[field_name] <= 0:
            return f"{field_name}_invalid"
    reference_time = values["reference_time_utc"]
    if not isinstance(reference_time, datetime) or reference_time.tzinfo is None:
        return "reference_time_utc_invalid"
    if not values["trace_id"] or not values["trigger_source"]:
        return "trace_context_required"
    return ""


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("reference_time_utc 必须带 UTC 时区")
    return value.astimezone(UTC)


def _empty_result_data() -> dict[str, Any]:
    return {
        "order_plan_id": None,
        "active_lock_id": None,
        "candidate_order_intent_ids": [],
        "primary_candidate_order_intent_id": None,
        "fallback_candidate_order_intent_id": None,
        "allows_downstream": False,
    }
