"""ExecutionPreparation 模块：执行 ApprovedOrderIntent 的最终准备检查并生成 PreparedOrderIntent；读写 MySQL；通过 BinanceGateway 查询公共盘口；不提交订单；不允许真实交易。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from django.conf import settings
from django.db import DatabaseError, IntegrityError, transaction
from django.utils import timezone

from apps.binance_account_sync.models import BinancePositionMode, BinanceSyncPurpose, BinanceSyncStatus
from apps.binance_account_sync.selectors import verify_trade_preparation_snapshot_set
from apps.binance_account_sync.services.hashing import stable_hash
from apps.binance_gateway.public_market import PublicMarketGateway, get_public_market_gateway
from apps.binance_gateway.types import (
    MARKET_TYPE_COIN_M,
    MARKET_TYPE_USDS_M,
    BinanceGatewayCallContext,
    BinanceGatewayResult,
)
from apps.foundation.results import ResultStatus, ServiceResult
from apps.order_plan.models import ActiveLockStatus, OrderPlanActiveLock, OrderPlanStatus
from apps.order_plan.services.active_lock import release_for_pre_execution_stop
from apps.order_plan.services.hashing import decimal_hash_value
from apps.price_snapshot.models import PriceType
from apps.price_snapshot.services.snapshot import compute_price_snapshot_hash, price_snapshot_hash_payload
from apps.risk_check.models import ApprovedOrderIntent, ApprovedOrderIntentStatus, RiskCheckStatus

from ..models import ExecutionPreparationResult, ExecutionPreparationStatus, PreparedOrderIntent, PreparedOrderIntentStatus
from .alerts import record_execution_preparation_alert
from .hashing import (
    execution_preparation_key_hash,
    prepared_order_evidence_hash,
    prepared_order_idempotency_hash,
    prepared_order_intent_key_hash,
)


MAX_KEY_LENGTH = 191
MAX_TRACE_FIELD_LENGTH = 80
ZERO = Decimal("0")


class PreparationBlocked(Exception):
    """执行准备生成前发现业务链路已不可继续。"""

    def __init__(self, reason_code: str, message: str) -> None:
        super().__init__(message)
        self.reason_code = reason_code
        self.message = message


@dataclass(frozen=True)
class PreparationContext:
    approved: ApprovedOrderIntent

    @property
    def risk_check_result(self):
        return self.approved.risk_check_result

    @property
    def candidate(self):
        return self.approved.candidate_order_intent

    @property
    def order_plan(self):
        return self.approved.order_plan

    @property
    def sync_run(self):
        return self.approved.binance_sync_run

    @property
    def price_snapshot(self):
        return self.approved.price_snapshot

    @property
    def active_lock(self):
        return self.approved.active_lock

    @property
    def account_snapshot(self):
        return self.risk_check_result.account_snapshot

    @property
    def position_snapshot(self):
        return self.risk_check_result.position_snapshot

    @property
    def symbol_rule_snapshot(self):
        return self.risk_check_result.symbol_rule_snapshot


@dataclass(frozen=True)
class LiveBookTicker:
    best_bid_price: Decimal
    best_bid_quantity: Decimal
    best_ask_price: Decimal
    best_ask_quantity: Decimal
    selected_live_price: Decimal
    selected_live_price_side: str
    requested_at_utc: datetime
    observed_at_utc: datetime
    gateway_metadata: dict[str, Any]


def prepare_execution(
    *,
    approved_order_intent_id: int,
    business_request_key: str,
    reference_time_utc: datetime,
    trace_id: str,
    trigger_source: str,
    gateway: PublicMarketGateway | None = None,
) -> ServiceResult:
    request_error = _request_error(
        approved_order_intent_id=approved_order_intent_id,
        business_request_key=business_request_key,
        reference_time_utc=reference_time_utc,
        trace_id=trace_id,
        trigger_source=trigger_source,
    )
    if request_error == "trace_context_missing":
        return _failed_without_result(request_error, "ExecutionPreparation 缺少技术追踪上下文", business_request_key, trace_id, trigger_source)
    if request_error:
        return _blocked_without_result(request_error, "ExecutionPreparation 请求合同不完整", business_request_key, trace_id, trigger_source)

    reference_time = reference_time_utc.astimezone(UTC)
    try:
        context = _load_context(approved_order_intent_id)
    except ApprovedOrderIntent.DoesNotExist:
        return _blocked_without_result("approved_order_intent_not_found", "ApprovedOrderIntent 不存在", business_request_key, trace_id, trigger_source)
    except DatabaseError as exc:
        return _failed_without_result("internal_error", type(exc).__name__, business_request_key, trace_id, trigger_source)

    config, config_error = _load_config()
    try:
        result_or_existing = _claim_preparation_result(
            context=context,
            business_request_key=business_request_key,
            reference_time_utc=reference_time,
            config=config,
            trace_id=trace_id,
            trigger_source=trigger_source,
        )
    except DatabaseError as exc:
        return _failed_without_result("internal_error", type(exc).__name__, business_request_key, trace_id, trigger_source)
    if isinstance(result_or_existing, ServiceResult):
        return result_or_existing
    result = result_or_existing

    try:
        if config_error:
            return _finalize_blocked(
                result=result,
                context=context,
                reason_code=config_error,
                message="ExecutionPreparation 配置不可用",
                trace_id=trace_id,
                trigger_source=trigger_source,
            )

        precheck_error = _pre_gateway_error(context=context, reference_time_utc=reference_time)
        if precheck_error:
            return _finalize_blocked(
                result=result,
                context=context,
                reason_code=precheck_error[0],
                message=precheck_error[1],
                trace_id=trace_id,
                trigger_source=trigger_source,
            )

        requested_at = timezone.now()
        gateway_result = (gateway or get_public_market_gateway()).get_book_ticker(
            market_type=context.approved.market_type,
            symbol=context.approved.symbol,
            call_context=BinanceGatewayCallContext(
                trace_id=trace_id,
                trigger_source=trigger_source,
                operation="get_book_ticker",
                market_type=context.approved.market_type,
                account_domain=context.approved.account_domain,
                symbol=context.approved.symbol,
                business_object_type="ApprovedOrderIntent",
                business_object_id=str(context.approved.id),
                request_time_utc=requested_at,
            ),
        )
        received_at = timezone.now()
        live_result = _extract_live_ticker(
            context=context,
            gateway_result=gateway_result,
            requested_at_utc=gateway_result.request_started_at_utc or requested_at,
            observed_at_utc=gateway_result.request_finished_at_utc or received_at,
        )
        if isinstance(live_result, tuple):
            return _finalize_blocked(
                result=result,
                context=context,
                reason_code=live_result[0],
                message=live_result[1],
                trace_id=trace_id,
                trigger_source=trigger_source,
                live_price=None,
                gateway_result=gateway_result,
            )
        live_price = live_result

        price_deviation_ratio = abs(live_price.selected_live_price - context.price_snapshot.mark_price) / context.price_snapshot.mark_price
        price_deviation_bps = price_deviation_ratio * Decimal("10000")
        limit_bps = Decimal(str(config["max_price_deviation_bps"]))
        if price_deviation_bps > limit_bps:
            return _finalize_blocked(
                result=result,
                context=context,
                reason_code="live_price_deviation_exceeded",
                message="执行前盘口价格与本轮 mark price 偏差超过允许阈值",
                trace_id=trace_id,
                trigger_source=trigger_source,
                live_price=live_price,
                gateway_result=gateway_result,
                price_deviation_ratio=price_deviation_ratio,
                price_deviation_bps=price_deviation_bps,
            )

        post_price_error = _post_price_error(context=context, live_price=live_price)
        if post_price_error:
            return _finalize_blocked(
                result=result,
                context=context,
                reason_code=post_price_error[0],
                message=post_price_error[1],
                trace_id=trace_id,
                trigger_source=trigger_source,
                live_price=live_price,
                gateway_result=gateway_result,
                price_deviation_ratio=price_deviation_ratio,
                price_deviation_bps=price_deviation_bps,
            )

        return _finalize_prepared(
            result=result,
            context=context,
            config=config,
            reference_time_utc=reference_time,
            live_price=live_price,
            gateway_result=gateway_result,
            price_deviation_ratio=price_deviation_ratio,
            price_deviation_bps=price_deviation_bps,
            trace_id=trace_id,
            trigger_source=trigger_source,
        )
    except DatabaseError as exc:
        return _finalize_failed(result=result, context=context, reason_code="internal_error", message=type(exc).__name__, trace_id=trace_id, trigger_source=trigger_source)
    except Exception as exc:
        return _finalize_failed(result=result, context=context, reason_code="internal_error", message=type(exc).__name__, trace_id=trace_id, trigger_source=trigger_source)


def _load_context(approved_order_intent_id: int) -> PreparationContext:
    approved = (
        ApprovedOrderIntent.objects.select_related(
            "risk_check_result",
            "candidate_order_intent",
            "order_plan",
            "binance_sync_run",
            "price_snapshot",
            "active_lock",
            "risk_check_result__account_snapshot",
            "risk_check_result__position_snapshot",
            "risk_check_result__symbol_rule_snapshot",
        )
        .get(id=approved_order_intent_id)
    )
    return PreparationContext(approved=approved)


def _claim_preparation_result(
    *,
    context: PreparationContext,
    business_request_key: str,
    reference_time_utc: datetime,
    config: dict[str, Any],
    trace_id: str,
    trigger_source: str,
) -> ExecutionPreparationResult | ServiceResult:
    existing = ExecutionPreparationResult.objects.filter(approved_order_intent=context.approved).first()
    if existing is not None:
        return _result_from_preparation(existing, trace_id=trace_id, trigger_source=trigger_source, replay=True)
    key = _execution_preparation_key(context=context, business_request_key=business_request_key, config=config)
    try:
        with transaction.atomic():
            approved = ApprovedOrderIntent.objects.select_for_update().get(id=context.approved.id)
            existing = ExecutionPreparationResult.objects.select_for_update().filter(approved_order_intent=approved).first()
            if existing is not None:
                return _result_from_preparation(existing, trace_id=trace_id, trigger_source=trigger_source, replay=True)
            now = timezone.now()
            return ExecutionPreparationResult.objects.create(
                business_request_key=business_request_key,
                execution_preparation_key=key,
                status=ExecutionPreparationStatus.PREPARING,
                reason_code="execution_preparation_preparing",
                reason_message="ExecutionPreparation 已取得唯一准备资格，正在执行检查。",
                approved_order_intent=context.approved,
                risk_check_result=context.risk_check_result,
                candidate_order_intent=context.candidate,
                order_plan=context.order_plan,
                active_lock=context.active_lock,
                price_snapshot=context.price_snapshot,
                binance_sync_run=context.sync_run,
                account_snapshot=context.account_snapshot,
                position_snapshot=context.position_snapshot,
                symbol_rule_snapshot=context.symbol_rule_snapshot,
                price_snapshot_hash=context.price_snapshot.price_snapshot_hash,
                binance_snapshot_set_hash=context.sync_run.snapshot_set_hash,
                reference_mark_price=context.price_snapshot.mark_price,
                price_deviation_limit_bps=Decimal(str(config.get("max_price_deviation_bps", 100))),
                config_snapshot=config,
                input_hash=_input_hash(context=context, reference_time_utc=reference_time_utc, config=config),
                evidence={"reference_time_utc": reference_time_utc.isoformat()},
                trace_id=trace_id,
                trigger_source=trigger_source,
                started_at_utc=now,
            )
    except IntegrityError:
        existing = ExecutionPreparationResult.objects.filter(approved_order_intent=context.approved).first()
        if existing is not None:
            return _result_from_preparation(existing, trace_id=trace_id, trigger_source=trigger_source, replay=True)
        return _failed_without_result("internal_error", "ExecutionPreparation 唯一约束冲突且无法恢复", business_request_key, trace_id, trigger_source)


def _pre_gateway_error(*, context: PreparationContext, reference_time_utc: datetime) -> tuple[str, str] | None:
    approved = context.approved
    risk = context.risk_check_result
    candidate = context.candidate
    plan = context.order_plan
    price = context.price_snapshot
    sync_run = context.sync_run
    active_lock = context.active_lock

    if approved.status != ApprovedOrderIntentStatus.APPROVED:
        return "approved_order_intent_not_ready", "ApprovedOrderIntent 当前状态不允许进入执行准备"
    if reference_time_utc >= approved.expires_at_utc:
        return "approved_order_intent_expired", "ApprovedOrderIntent 已过期"
    if risk.status != RiskCheckStatus.ALLOW or not risk.allows_downstream or risk.selected_candidate_order_intent_id != candidate.id:
        return "source_chain_mismatch", "RiskCheckResult 未批准当前候选订单意图"
    if (
        approved.risk_check_result_id != risk.id
        or approved.candidate_order_intent_id != candidate.id
        or approved.order_plan_id != plan.id
        or approved.price_snapshot_id != price.id
        or approved.binance_sync_run_id != sync_run.id
        or approved.active_lock_id != active_lock.id
    ):
        return "source_chain_mismatch", "ApprovedOrderIntent 上游业务链不一致"
    if candidate.order_plan_id != plan.id or candidate.price_snapshot_id != price.id or candidate.binance_sync_run_id != sync_run.id:
        return "source_chain_mismatch", "CandidateOrderIntent 上游业务链不一致"
    if risk.order_plan_id != plan.id or risk.price_snapshot_id != price.id or risk.binance_sync_run_id != sync_run.id:
        return "source_chain_mismatch", "RiskCheckResult 上游业务链不一致"
    if _market_identity_mismatch(context):
        return "market_identity_mismatch", "执行准备输入的市场身份不一致"
    if _reference_before_source_fact(context, reference_time_utc):
        return "reference_time_before_source_fact", "reference_time_utc 早于已绑定上游事实"
    price_error = _price_snapshot_error(context, reference_time_utc)
    if price_error:
        return price_error
    sync_error = _sync_run_error(context, reference_time_utc)
    if sync_error:
        return sync_error
    lock_error = _active_lock_error(context)
    if lock_error:
        return lock_error
    contract_error = _order_contract_error(context)
    if contract_error:
        return contract_error
    return None


def _post_price_error(*, context: PreparationContext, live_price: LiveBookTicker) -> tuple[str, str] | None:
    reduce_only_error = _reduce_only_error(context)
    if reduce_only_error:
        return reduce_only_error
    rule_error = _symbol_rule_error(context, live_price)
    if rule_error:
        return rule_error
    return None


def _market_identity_mismatch(context: PreparationContext) -> bool:
    expected = (
        context.approved.exchange.lower(),
        context.approved.market_type,
        context.approved.account_domain,
        context.approved.symbol,
    )
    identities = [
        (context.order_plan.exchange.lower(), context.order_plan.market_type, context.order_plan.account_domain, context.order_plan.symbol),
        ("binance", context.candidate.market_type, context.candidate.account_domain, context.candidate.symbol),
        (context.price_snapshot.exchange.lower(), context.price_snapshot.market_type, context.price_snapshot.account_domain, context.price_snapshot.symbol),
        (context.sync_run.exchange.lower(), context.sync_run.market_type, context.sync_run.account_domain, context.approved.symbol),
        (context.active_lock.exchange.lower(), context.active_lock.market_type, context.active_lock.account_domain, context.active_lock.symbol),
        ("binance", context.position_snapshot.market_type, context.position_snapshot.account_domain, context.position_snapshot.symbol),
        ("binance", context.symbol_rule_snapshot.market_type, context.symbol_rule_snapshot.account_domain, context.symbol_rule_snapshot.symbol),
    ]
    return any(item != expected for item in identities)


def _reference_before_source_fact(context: PreparationContext, reference_time_utc: datetime) -> bool:
    facts = [
        context.approved.created_at_utc,
        context.risk_check_result.created_at_utc,
        context.price_snapshot.as_of_utc,
    ]
    if context.sync_run.finished_at_utc is not None:
        facts.append(context.sync_run.finished_at_utc)
    return any(reference_time_utc < _ensure_utc(item) for item in facts)


def _price_snapshot_error(context: PreparationContext, reference_time_utc: datetime) -> tuple[str, str] | None:
    price = context.price_snapshot
    if price.price_type != PriceType.MARK_PRICE or price.mark_price <= ZERO:
        return "price_snapshot_invalid", "PriceSnapshot 不是可消费的 mark price"
    if reference_time_utc > price.expires_at_utc:
        return "price_snapshot_expired", "PriceSnapshot 已过期"
    payload = price_snapshot_hash_payload(
        business_request_key=price.business_request_key,
        exchange=price.exchange,
        market_type=price.market_type,
        account_domain=price.account_domain,
        symbol=price.symbol,
        price_type=price.price_type,
        mark_price=price.mark_price,
        price_unit=price.price_unit,
        source=price.source,
        source_operation=price.source_operation,
        source_update_time_utc=price.source_update_time_utc,
        as_of_utc=price.as_of_utc,
        expires_at_utc=price.expires_at_utc,
    )
    if compute_price_snapshot_hash(payload) != price.price_snapshot_hash:
        return "price_snapshot_invalid", "PriceSnapshot 指纹校验失败"
    if context.approved.price_snapshot_hash != price.price_snapshot_hash or context.risk_check_result.price_snapshot_hash != price.price_snapshot_hash:
        return "price_snapshot_identity_mismatch", "上游记录的 PriceSnapshot hash 不一致"
    return None


def _sync_run_error(context: PreparationContext, reference_time_utc: datetime) -> tuple[str, str] | None:
    sync_run = context.sync_run
    if sync_run.status != BinanceSyncStatus.SUCCEEDED or sync_run.sync_purpose != BinanceSyncPurpose.TRADE_PREPARATION:
        return "binance_sync_run_not_consumable", "BinanceSyncRun 不可供执行准备消费"
    if sync_run.expires_at_utc is None or reference_time_utc > sync_run.expires_at_utc:
        return "binance_sync_run_expired", "BinanceSyncRun 已过期"
    if not sync_run.snapshot_set_hash or context.approved.binance_snapshot_set_hash != sync_run.snapshot_set_hash:
        return "binance_sync_run_not_consumable", "账户快照集合 hash 缺失或不一致"
    integrity = verify_trade_preparation_snapshot_set(
        sync_run_id=sync_run.id,
        trace_id=context.approved.trace_id,
        trigger_source=context.approved.trigger_source,
    )
    if integrity.status != ResultStatus.SUCCEEDED:
        return integrity.reason_code, integrity.message
    return None


def _active_lock_error(context: PreparationContext) -> tuple[str, str] | None:
    lock = context.active_lock
    if lock.status != ActiveLockStatus.ACTIVE:
        return "active_lock_not_active", "ActiveLock 不是 active 状态"
    if lock.current_order_plan_id != context.order_plan.id:
        return "active_chain_conflict", "ActiveLock 未绑定当前 OrderPlan"
    return None


def _order_contract_error(context: PreparationContext) -> tuple[str, str] | None:
    approved = context.approved
    if approved.order_type not in _supported_order_types():
        return "unsupported_order_type", "当前仅支持 MARKET 订单进入执行准备"
    if approved.position_side != "BOTH":
        return "unsupported_position_mode", "当前仅支持 One-Way / BOTH 持仓语义"
    if context.candidate.position_mode != BinancePositionMode.ONE_WAY or context.order_plan.position_mode != BinancePositionMode.ONE_WAY:
        return "unsupported_position_mode", "当前仅支持 One-Way Mode"
    if approved.side not in {"BUY", "SELL"}:
        return "unsupported_order_side", "订单方向必须是 BUY 或 SELL"
    if approved.market_type == MARKET_TYPE_USDS_M and not approved.requested_size_unit:
        return "unsupported_quantity_unit", "USDS-M 必须具备基础资产数量单位"
    if approved.market_type == MARKET_TYPE_COIN_M and approved.requested_size_unit != "contracts":
        return "unsupported_quantity_unit", "COIN-M 必须使用 contracts 数量单位"
    if approved.requested_size <= ZERO:
        return "exchange_rule_violation", "冻结数量必须大于零"
    return None


def _extract_live_ticker(
    *,
    context: PreparationContext,
    gateway_result: BinanceGatewayResult,
    requested_at_utc: datetime,
    observed_at_utc: datetime,
) -> LiveBookTicker | tuple[str, str]:
    metadata = _gateway_metadata(gateway_result)
    if not gateway_result.success or not gateway_result.response_received:
        return "live_price_unavailable", "Binance book ticker 请求未成功返回"
    if gateway_result.market_type != context.approved.market_type:
        return "live_price_market_identity_mismatch", "Gateway 返回市场类型与 ApprovedOrderIntent 不一致"
    payload = _ticker_payload(gateway_result.payload, context.approved.symbol)
    if payload is None:
        return "live_price_market_identity_mismatch", "Gateway 返回 symbol 与 ApprovedOrderIntent 不一致"
    try:
        bid_price = _positive_decimal(payload.get("bidPrice"))
        bid_quantity = _positive_decimal(payload.get("bidQty") or payload.get("bidQuantity"))
        ask_price = _positive_decimal(payload.get("askPrice"))
        ask_quantity = _positive_decimal(payload.get("askQty") or payload.get("askQuantity"))
    except (InvalidOperation, ValueError):
        return "live_price_invalid", "book ticker bid / ask 缺失或不合法"
    if ask_price < bid_price:
        return "live_price_invalid", "book ticker ask 小于 bid"
    if context.approved.side == "BUY":
        selected = ask_price
        selected_side = "ask"
    elif context.approved.side == "SELL":
        selected = bid_price
        selected_side = "bid"
    else:
        return "unsupported_order_side", "订单方向必须是 BUY 或 SELL"
    return LiveBookTicker(
        best_bid_price=bid_price,
        best_bid_quantity=bid_quantity,
        best_ask_price=ask_price,
        best_ask_quantity=ask_quantity,
        selected_live_price=selected,
        selected_live_price_side=selected_side,
        requested_at_utc=_ensure_utc(requested_at_utc),
        observed_at_utc=_ensure_utc(observed_at_utc),
        gateway_metadata=metadata,
    )


def _ticker_payload(payload: Any, symbol: str) -> dict[str, Any] | None:
    if isinstance(payload, dict) and str(payload.get("symbol") or "").upper() == symbol:
        return payload
    if isinstance(payload, list):
        for item in payload:
            if isinstance(item, dict) and str(item.get("symbol") or "").upper() == symbol:
                return item
    return None


def _reduce_only_error(context: PreparationContext) -> tuple[str, str] | None:
    if not context.approved.exchange_reduce_only:
        return None
    amount = context.position_snapshot.position_amount
    if amount is None or amount == ZERO:
        return "reduce_only_invalid", "reduce-only 订单缺少可减少持仓"
    if context.approved.requested_size > abs(amount):
        return "reduce_only_invalid", "reduce-only 数量大于已绑定持仓数量"
    if amount > ZERO and context.approved.side != "SELL":
        return "reduce_only_invalid", "多头持仓只能用 SELL reduce-only 减少"
    if amount < ZERO and context.approved.side != "BUY":
        return "reduce_only_invalid", "空头持仓只能用 BUY reduce-only 减少"
    return None


def _symbol_rule_error(context: PreparationContext, live_price: LiveBookTicker) -> tuple[str, str] | None:
    rule = context.symbol_rule_snapshot
    quantity = context.approved.requested_size
    if rule.supported_order_types and context.approved.order_type not in rule.supported_order_types:
        return "unsupported_order_type", "交易规则不支持当前订单类型"
    if rule.step_size is None or rule.step_size <= ZERO or rule.min_quantity is None or rule.quantity_precision is None:
        return "symbol_rule_unavailable", "交易规则数量字段缺失"
    if quantity < rule.min_quantity:
        return "exchange_rule_violation", "冻结数量低于交易所最小数量"
    if rule.max_quantity is not None and quantity > rule.max_quantity:
        return "exchange_rule_violation", "冻结数量超过交易所最大数量"
    if quantity % rule.step_size != ZERO:
        return "exchange_rule_violation", "冻结数量不符合 step_size"
    if not _decimal_places_allowed(quantity, rule.quantity_precision):
        return "exchange_rule_violation", "冻结数量精度超过交易规则"
    notional = _estimated_notional(context, live_price)
    if notional is None:
        return "symbol_rule_unavailable", "交易规则无法估算当前名义价值"
    if rule.min_notional is not None and notional < rule.min_notional:
        return "exchange_rule_violation", "当前盘口估算名义价值低于交易所最小值"
    max_notional = _max_notional_from_rule(rule.raw_filters)
    if max_notional is not None and notional > max_notional:
        return "exchange_rule_violation", "当前盘口估算名义价值超过交易所最大值"
    return None


def _estimated_notional(context: PreparationContext, live_price: LiveBookTicker) -> Decimal | None:
    if context.approved.market_type == MARKET_TYPE_USDS_M:
        return context.approved.requested_size * live_price.selected_live_price
    if context.approved.market_type == MARKET_TYPE_COIN_M:
        contract_size = context.symbol_rule_snapshot.contract_size
        if contract_size is None or contract_size <= ZERO:
            return None
        return context.approved.requested_size * contract_size
    return None


def _finalize_prepared(
    *,
    result: ExecutionPreparationResult,
    context: PreparationContext,
    config: dict[str, Any],
    reference_time_utc: datetime,
    live_price: LiveBookTicker,
    gateway_result: BinanceGatewayResult,
    price_deviation_ratio: Decimal,
    price_deviation_bps: Decimal,
    trace_id: str,
    trigger_source: str,
) -> ServiceResult:
    prepared_at = timezone.now()
    expires_at = min(
        live_price.observed_at_utc + timedelta(seconds=int(config["prepared_order_intent_ttl_seconds"])),
        context.approved.expires_at_utc,
        context.price_snapshot.expires_at_utc,
        context.sync_run.expires_at_utc,
    )
    if expires_at <= prepared_at:
        return _finalize_blocked(
            result=result,
            context=context,
            reason_code="prepared_order_intent_expired",
            message="执行准备完成时待提交请求已无有效窗口",
            trace_id=trace_id,
            trigger_source=trigger_source,
            live_price=live_price,
            gateway_result=gateway_result,
            price_deviation_ratio=price_deviation_ratio,
            price_deviation_bps=price_deviation_bps,
        )

    evidence = _evidence(
        context=context,
        live_price=live_price,
        gateway_result=gateway_result,
        price_deviation_ratio=price_deviation_ratio,
        price_deviation_bps=price_deviation_bps,
        config=config,
    )
    prepared_key = prepared_order_intent_key_hash({"approved_order_intent_id": context.approved.id})[:MAX_KEY_LENGTH]
    idempotency_key = _prepared_idempotency_key(context=context, result=result)
    client_order_id = _client_order_id(context)
    try:
        with transaction.atomic():
            result = ExecutionPreparationResult.objects.select_for_update().get(id=result.id)
            if result.status != ExecutionPreparationStatus.PREPARING:
                return _result_from_preparation(result, trace_id=trace_id, trigger_source=trigger_source, replay=True)
            try:
                active_lock = OrderPlanActiveLock.objects.select_for_update().get(id=context.active_lock.id)
            except OrderPlanActiveLock.DoesNotExist as exc:
                raise PreparationBlocked("active_lock_missing", "ActiveLock 不存在，不能生成 PreparedOrderIntent") from exc
            if active_lock.status != ActiveLockStatus.ACTIVE:
                raise PreparationBlocked("active_lock_not_active", "生成 PreparedOrderIntent 前 ActiveLock 已不再 active")
            if active_lock.current_order_plan_id != context.order_plan.id:
                raise PreparationBlocked("active_chain_conflict", "生成 PreparedOrderIntent 前 ActiveLock 已不再绑定当前 OrderPlan")
            prepared = PreparedOrderIntent.objects.create(
                prepared_order_intent_key=prepared_key,
                execution_preparation_result=result,
                source_approved_order_intent=context.approved,
                source_risk_check_result=context.risk_check_result,
                source_candidate_order_intent=context.candidate,
                source_order_plan=context.order_plan,
                exchange=context.approved.exchange,
                market_type=context.approved.market_type,
                account_domain=context.approved.account_domain,
                symbol=context.approved.symbol,
                position_mode=context.candidate.position_mode,
                position_side=context.approved.position_side,
                side=context.approved.side,
                order_type=context.approved.order_type,
                quantity=context.approved.requested_size,
                quantity_unit=context.approved.requested_size_unit,
                reduce_only=context.approved.exchange_reduce_only,
                time_in_force="",
                client_order_id=client_order_id,
                idempotency_key=idempotency_key,
                price_snapshot=context.price_snapshot,
                reference_mark_price=context.price_snapshot.mark_price,
                selected_live_price=live_price.selected_live_price,
                price_deviation_bps=price_deviation_bps,
                binance_sync_run=context.sync_run,
                account_snapshot=context.account_snapshot,
                position_snapshot=context.position_snapshot,
                symbol_rule_snapshot=context.symbol_rule_snapshot,
                prepared_at_utc=prepared_at,
                expires_at_utc=expires_at,
                status=PreparedOrderIntentStatus.PREPARED,
                trigger_source=trigger_source,
                config_snapshot=config,
                evidence_hash=prepared_order_evidence_hash(evidence),
            )
            _update_result(
                result,
                status=ExecutionPreparationStatus.PREPARED,
                reason_code="execution_preparation_prepared",
                message="执行前检查通过，PreparedOrderIntent 已生成。",
                live_price=live_price,
                gateway_result=gateway_result,
                price_deviation_ratio=price_deviation_ratio,
                price_deviation_bps=price_deviation_bps,
                evidence=evidence,
            )
            context.approved.status = ApprovedOrderIntentStatus.EXECUTION_PREPARED
            context.approved.save(update_fields=["status"])
        _record_result_alert(result, context, prepared, "execution_preparation_prepared", trace_id, trigger_source)
        return _result_from_preparation(result, trace_id=trace_id, trigger_source=trigger_source)
    except PreparationBlocked as exc:
        return _finalize_blocked(
            result=result,
            context=context,
            reason_code=exc.reason_code,
            message=exc.message,
            trace_id=trace_id,
            trigger_source=trigger_source,
            live_price=live_price,
            gateway_result=gateway_result,
            price_deviation_ratio=price_deviation_ratio,
            price_deviation_bps=price_deviation_bps,
        )
    except IntegrityError:
        result.refresh_from_db()
        if result.status == ExecutionPreparationStatus.PREPARED and _prepared_for_result(result) is not None:
            return _result_from_preparation(result, trace_id=trace_id, trigger_source=trigger_source, replay=True)
        return _finalize_failed(result=result, context=context, reason_code="prepared_request_conflict", message="PreparedOrderIntent 唯一约束冲突", trace_id=trace_id, trigger_source=trigger_source)
    except DatabaseError as exc:
        return _finalize_failed(result=result, context=context, reason_code="internal_error", message=type(exc).__name__, trace_id=trace_id, trigger_source=trigger_source)


def _finalize_blocked(
    *,
    result: ExecutionPreparationResult,
    context: PreparationContext,
    reason_code: str,
    message: str,
    trace_id: str,
    trigger_source: str,
    live_price: LiveBookTicker | None = None,
    gateway_result: BinanceGatewayResult | None = None,
    price_deviation_ratio: Decimal | None = None,
    price_deviation_bps: Decimal | None = None,
) -> ServiceResult:
    _update_result(
        result,
        status=ExecutionPreparationStatus.BLOCKED,
        reason_code=reason_code,
        message=message,
        live_price=live_price,
        gateway_result=gateway_result,
        price_deviation_ratio=price_deviation_ratio,
        price_deviation_bps=price_deviation_bps,
        evidence={"blocked_reason": reason_code},
    )
    context.approved.status = ApprovedOrderIntentStatus.PREPARATION_BLOCKED
    context.approved.save(update_fields=["status"])
    context.order_plan.status = OrderPlanStatus.PREPARATION_BLOCKED
    context.order_plan.reason_code = reason_code
    context.order_plan.allows_downstream = False
    context.order_plan.save(update_fields=["status", "reason_code", "allows_downstream"])
    release_for_pre_execution_stop(
        active_lock_id=context.active_lock.id,
        order_plan_id=context.order_plan.id,
        source_module="ExecutionPreparation",
        source_object_id=result.id,
        reason_code=f"execution_preparation_{reason_code}",
        evidence={"execution_preparation_result_id": result.id, "reason_code": reason_code},
        trace_id=trace_id,
        trigger_source=trigger_source,
    )
    event_type = _blocked_event_type(reason_code)
    _record_result_alert(result, context, None, event_type, trace_id, trigger_source)
    return _result_from_preparation(result, trace_id=trace_id, trigger_source=trigger_source)


def _finalize_failed(
    *,
    result: ExecutionPreparationResult,
    context: PreparationContext,
    reason_code: str,
    message: str,
    trace_id: str,
    trigger_source: str,
) -> ServiceResult:
    _update_result(
        result,
        status=ExecutionPreparationStatus.FAILED,
        reason_code=reason_code,
        message=message,
        evidence={"failed_reason": reason_code},
    )
    context.approved.status = ApprovedOrderIntentStatus.PREPARATION_FAILED
    context.approved.save(update_fields=["status"])
    context.order_plan.status = OrderPlanStatus.PREPARATION_FAILED
    context.order_plan.reason_code = reason_code
    context.order_plan.allows_downstream = False
    context.order_plan.save(update_fields=["status", "reason_code", "allows_downstream"])
    _record_result_alert(result, context, None, "execution_preparation_failed", trace_id, trigger_source)
    return _result_from_preparation(result, trace_id=trace_id, trigger_source=trigger_source)


def _update_result(
    result: ExecutionPreparationResult,
    *,
    status: str,
    reason_code: str,
    message: str,
    live_price: LiveBookTicker | None = None,
    gateway_result: BinanceGatewayResult | None = None,
    price_deviation_ratio: Decimal | None = None,
    price_deviation_bps: Decimal | None = None,
    evidence: dict[str, Any] | None = None,
) -> None:
    result.status = status
    result.reason_code = reason_code
    result.reason_message = message
    result.finished_at_utc = timezone.now()
    result.evidence = _json_ready(evidence or {})
    if gateway_result is not None:
        result.gateway_result_metadata = _gateway_metadata(gateway_result)
    if live_price is not None:
        result.best_bid_price = live_price.best_bid_price
        result.best_bid_quantity = live_price.best_bid_quantity
        result.best_ask_price = live_price.best_ask_price
        result.best_ask_quantity = live_price.best_ask_quantity
        result.selected_live_price = live_price.selected_live_price
        result.selected_live_price_side = live_price.selected_live_price_side
        result.live_price_requested_at_utc = live_price.requested_at_utc
        result.live_price_observed_at_utc = live_price.observed_at_utc
    result.price_deviation_ratio = price_deviation_ratio
    result.price_deviation_bps = price_deviation_bps
    result.save()


def _record_result_alert(
    result: ExecutionPreparationResult,
    context: PreparationContext,
    prepared: PreparedOrderIntent | None,
    event_type: str,
    trace_id: str,
    trigger_source: str,
) -> None:
    alert_id = record_execution_preparation_alert(
        event_type=event_type,
        business_request_key=result.business_request_key,
        trace_id=trace_id,
        trigger_source=trigger_source,
        status=result.status,
        reason_code=result.reason_code,
        message=result.reason_message,
        execution_preparation_result_id=result.id,
        prepared_order_intent_id=prepared.id if prepared else None,
        payload_summary={
            "approved_order_intent_id": context.approved.id,
            "order_plan_id": context.order_plan.id,
            "candidate_order_intent_id": context.candidate.id,
            "risk_check_result_id": context.risk_check_result.id,
            "active_lock_id": context.active_lock.id,
            "symbol": context.approved.symbol,
            "market_type": context.approved.market_type,
            "account_domain": context.approved.account_domain,
            "price_snapshot_id": context.price_snapshot.id,
            "binance_sync_run_id": context.sync_run.id,
            "selected_live_price": str(result.selected_live_price or ""),
            "selected_live_price_side": result.selected_live_price_side,
            "price_deviation_bps": str(result.price_deviation_bps or ""),
            "price_deviation_limit_bps": str(result.price_deviation_limit_bps or ""),
            "client_order_id": prepared.client_order_id if prepared else "",
            "idempotency_key": prepared.idempotency_key if prepared else "",
            "config_snapshot": result.config_snapshot,
        },
    )
    if alert_id is not None:
        result.alert_event_ids = [*result.alert_event_ids, alert_id]
        result.save(update_fields=["alert_event_ids", "updated_at_utc"])


def _result_from_preparation(result: ExecutionPreparationResult, *, trace_id: str, trigger_source: str, replay: bool = False) -> ServiceResult:
    prepared = _prepared_for_result(result) if result.status == ExecutionPreparationStatus.PREPARED else None
    result, prepared = _expire_prepared_if_needed(result=result, prepared=prepared, trace_id=trace_id, trigger_source=trigger_source)
    if replay:
        _record_replay_alert(result, prepared, trace_id, trigger_source)
    allows_downstream = _prepared_still_submittable(result, prepared)
    status = ResultStatus.SUCCEEDED if allows_downstream else ResultStatus.BLOCKED
    if result.status == ExecutionPreparationStatus.FAILED:
        status = ResultStatus.FAILED
    if result.status == ExecutionPreparationStatus.PREPARED and prepared is None:
        status = ResultStatus.FAILED
    response_reason_code = "execution_preparation_idempotent_replay" if replay and allows_downstream else result.reason_code
    response_message = "ExecutionPreparation 已完成" if not replay else "ExecutionPreparation 幂等重放返回既有结果"
    if replay and not allows_downstream:
        response_message = "ExecutionPreparation 幂等重放返回既有终态结果"
    return ServiceResult(
        status,
        response_reason_code,
        response_message,
        trace_id,
        trigger_source,
        {
            "execution_preparation_result_id": result.id,
            "execution_preparation_status": result.status,
            "prepared_order_intent_id": prepared.id if prepared is not None else None,
            "approved_order_intent_id": result.approved_order_intent_id,
            "order_plan_id": result.order_plan_id,
            "active_lock_id": result.active_lock_id,
            "allows_downstream": allows_downstream,
            "flow_action": "CONTINUE" if allows_downstream else "STOP",
        },
    )


def _prepared_for_result(result: ExecutionPreparationResult) -> PreparedOrderIntent | None:
    try:
        return result.prepared_order_intent
    except PreparedOrderIntent.DoesNotExist:
        return None


def _prepared_still_submittable(result: ExecutionPreparationResult, prepared: PreparedOrderIntent | None) -> bool:
    return (
        result.status == ExecutionPreparationStatus.PREPARED
        and prepared is not None
        and prepared.status == PreparedOrderIntentStatus.PREPARED
        and timezone.now() < prepared.expires_at_utc
    )


def _expire_prepared_if_needed(
    *,
    result: ExecutionPreparationResult,
    prepared: PreparedOrderIntent | None,
    trace_id: str,
    trigger_source: str,
) -> tuple[ExecutionPreparationResult, PreparedOrderIntent | None]:
    if (
        result.status != ExecutionPreparationStatus.PREPARED
        or prepared is None
        or prepared.status != PreparedOrderIntentStatus.PREPARED
        or timezone.now() < prepared.expires_at_utc
    ):
        return result, prepared

    with transaction.atomic():
        locked_result = ExecutionPreparationResult.objects.select_for_update().get(id=result.id)
        locked_prepared = PreparedOrderIntent.objects.select_for_update().get(id=prepared.id)
        if (
            locked_result.status != ExecutionPreparationStatus.PREPARED
            or locked_prepared.status != PreparedOrderIntentStatus.PREPARED
            or timezone.now() < locked_prepared.expires_at_utc
        ):
            return locked_result, _prepared_for_result(locked_result)
        now = timezone.now()
        locked_prepared.status = PreparedOrderIntentStatus.EXPIRED
        locked_prepared.save(update_fields=["status", "updated_at_utc"])

        locked_result.status = ExecutionPreparationStatus.EXPIRED
        locked_result.reason_code = "prepared_order_intent_expired"
        locked_result.reason_message = "PreparedOrderIntent 已超过有效期，不能继续进入 Execution。"
        locked_result.finished_at_utc = now
        locked_result.evidence = _json_ready(
            {
                **(locked_result.evidence or {}),
                "expired_at_utc": now,
                "prepared_order_intent_id": locked_prepared.id,
            }
        )
        locked_result.save(update_fields=["status", "reason_code", "reason_message", "finished_at_utc", "evidence", "updated_at_utc"])

        approved = ApprovedOrderIntent.objects.select_for_update().get(id=locked_result.approved_order_intent_id)
        if approved.status == ApprovedOrderIntentStatus.EXECUTION_PREPARED:
            approved.status = ApprovedOrderIntentStatus.PREPARATION_EXPIRED
            approved.save(update_fields=["status"])
        order_plan = approved.order_plan
        order_plan.status = OrderPlanStatus.PREPARATION_EXPIRED
        order_plan.reason_code = "prepared_order_intent_expired"
        order_plan.allows_downstream = False
        order_plan.save(update_fields=["status", "reason_code", "allows_downstream"])

    context = _load_context(locked_result.approved_order_intent_id)
    release_for_pre_execution_stop(
        active_lock_id=locked_result.active_lock_id,
        order_plan_id=locked_result.order_plan_id,
        source_module="ExecutionPreparation",
        source_object_id=locked_result.id,
        reason_code="execution_preparation_prepared_order_intent_expired",
        evidence={"execution_preparation_result_id": locked_result.id, "prepared_order_intent_id": locked_prepared.id},
        trace_id=trace_id,
        trigger_source=trigger_source,
    )
    _record_result_alert(locked_result, context, locked_prepared, "execution_preparation_expired", trace_id, trigger_source)
    return locked_result, locked_prepared


def _record_replay_alert(result: ExecutionPreparationResult, prepared: PreparedOrderIntent | None, trace_id: str, trigger_source: str) -> None:
    record_execution_preparation_alert(
        event_type="execution_preparation_idempotent_replay",
        business_request_key=result.business_request_key,
        trace_id=trace_id,
        trigger_source=trigger_source,
        status=result.status,
        reason_code="execution_preparation_idempotent_replay",
        message="ExecutionPreparation 幂等重放返回既有执行准备结果，未重新查询盘口。",
        execution_preparation_result_id=result.id,
        prepared_order_intent_id=prepared.id if prepared else None,
    )


def _request_error(**values: Any) -> str:
    if not values["trace_id"] or not values["trigger_source"]:
        return "trace_context_missing"
    if len(values["trace_id"]) > MAX_TRACE_FIELD_LENGTH or len(values["trigger_source"]) > MAX_TRACE_FIELD_LENGTH:
        return "trace_context_missing"
    if not isinstance(values["approved_order_intent_id"], int) or values["approved_order_intent_id"] <= 0:
        return "approved_order_intent_id_invalid"
    key = values["business_request_key"]
    if not isinstance(key, str) or not key.strip() or len(key) > MAX_KEY_LENGTH:
        return "business_request_key_invalid"
    reference_time = values["reference_time_utc"]
    if not isinstance(reference_time, datetime) or reference_time.tzinfo is None:
        return "reference_time_utc_invalid"
    return ""


def _load_config() -> tuple[dict[str, Any], str]:
    if not getattr(settings, "EXECUTION_PREPARATION_ENABLED", False):
        return {}, "execution_preparation_disabled"
    max_bps = getattr(settings, "EXECUTION_PREPARATION_MAX_PRICE_DEVIATION_BPS", None)
    ttl = getattr(settings, "PREPARED_ORDER_INTENT_TTL_SECONDS", None)
    supported_order_types = set(getattr(settings, "EXECUTION_PREPARATION_SUPPORTED_ORDER_TYPES", ["MARKET"]))
    supported_position_mode = str(getattr(settings, "EXECUTION_PREPARATION_SUPPORTED_POSITION_MODE", "one_way"))
    if not isinstance(max_bps, int | Decimal) or Decimal(str(max_bps)) < ZERO:
        return {}, "execution_preparation_config_invalid"
    if not isinstance(ttl, int) or ttl <= 0:
        return {}, "execution_preparation_config_invalid"
    if "MARKET" not in supported_order_types or supported_position_mode != BinancePositionMode.ONE_WAY:
        return {}, "execution_preparation_config_invalid"
    config = {
        "schema_version": "1.0",
        "max_price_deviation_bps": str(Decimal(str(max_bps))),
        "prepared_order_intent_ttl_seconds": ttl,
        "supported_order_types": sorted(supported_order_types),
        "supported_position_mode": supported_position_mode,
    }
    config["config_hash"] = stable_hash(config)
    return config, ""


def _supported_order_types() -> set[str]:
    return set(getattr(settings, "EXECUTION_PREPARATION_SUPPORTED_ORDER_TYPES", ["MARKET"]))


def _execution_preparation_key(*, context: PreparationContext, business_request_key: str, config: dict[str, Any]) -> str:
    return execution_preparation_key_hash(
        {
            "business_request_key": business_request_key,
            "approved_order_intent_id": context.approved.id,
            "risk_check_result_id": context.risk_check_result.id,
            "candidate_order_intent_id": context.candidate.id,
            "order_plan_id": context.order_plan.id,
            "config_hash": config.get("config_hash", ""),
        }
    )[:MAX_KEY_LENGTH]


def _input_hash(*, context: PreparationContext, reference_time_utc: datetime, config: dict[str, Any]) -> str:
    return stable_hash(
        {
            "approved_order_intent_id": context.approved.id,
            "candidate_intent_hash": context.approved.candidate_intent_hash,
            "risk_check_hash": context.approved.risk_check_hash,
            "price_snapshot_hash": context.price_snapshot.price_snapshot_hash,
            "binance_snapshot_set_hash": context.sync_run.snapshot_set_hash,
            "reference_time_utc": reference_time_utc.isoformat(),
            "config_hash": config.get("config_hash", ""),
        }
    )


def _prepared_idempotency_key(*, context: PreparationContext, result: ExecutionPreparationResult) -> str:
    return prepared_order_idempotency_hash(
        {
            "business_request_key": result.business_request_key,
            "approved_order_intent_id": context.approved.id,
            "risk_check_result_id": context.risk_check_result.id,
            "candidate_order_intent_id": context.candidate.id,
            "order_plan_id": context.order_plan.id,
            "price_snapshot_id": context.price_snapshot.id,
            "binance_sync_run_id": context.sync_run.id,
            "symbol": context.approved.symbol,
            "market_type": context.approved.market_type,
            "account_domain": context.approved.account_domain,
            "side": context.approved.side,
            "position_side": context.approved.position_side,
            "quantity": decimal_hash_value(context.approved.requested_size),
            "quantity_unit": context.approved.requested_size_unit,
            "reduce_only": context.approved.exchange_reduce_only,
            "order_type": context.approved.order_type,
        }
    )[:MAX_KEY_LENGTH]


def _client_order_id(context: PreparationContext) -> str:
    return f"tc-{stable_hash({'approved_order_intent_id': context.approved.id, 'candidate_intent_hash': context.approved.candidate_intent_hash})[:29]}"


def _evidence(
    *,
    context: PreparationContext,
    live_price: LiveBookTicker,
    gateway_result: BinanceGatewayResult,
    price_deviation_ratio: Decimal,
    price_deviation_bps: Decimal,
    config: dict[str, Any],
) -> dict[str, Any]:
    return _json_ready(
        {
            "price_snapshot_id": context.price_snapshot.id,
            "price_snapshot_hash": context.price_snapshot.price_snapshot_hash,
            "reference_mark_price": context.price_snapshot.mark_price,
            "mark_price_observed_at_utc": context.price_snapshot.as_of_utc,
            "mark_price_expires_at_utc": context.price_snapshot.expires_at_utc,
            "best_bid_price": live_price.best_bid_price,
            "best_bid_quantity": live_price.best_bid_quantity,
            "best_ask_price": live_price.best_ask_price,
            "best_ask_quantity": live_price.best_ask_quantity,
            "selected_live_price": live_price.selected_live_price,
            "selected_live_price_side": live_price.selected_live_price_side,
            "live_price_requested_at_utc": live_price.requested_at_utc,
            "live_price_observed_at_utc": live_price.observed_at_utc,
            "price_deviation_ratio": price_deviation_ratio,
            "price_deviation_bps": price_deviation_bps,
            "price_deviation_limit_bps": config["max_price_deviation_bps"],
            "gateway_result_metadata": _gateway_metadata(gateway_result),
        }
    )


def _gateway_metadata(result: BinanceGatewayResult) -> dict[str, Any]:
    return _json_ready(
        {
            "operation": result.operation,
            "market_type": result.market_type,
            "endpoint_family": result.endpoint_family,
            "success": result.success,
            "response_received": result.response_received,
            "request_sent": result.request_sent,
            "http_status": result.http_status,
            "error_category": result.error_category,
            "sanitized_error_message": result.sanitized_error_message,
            "request_started_at_utc": result.request_started_at_utc,
            "request_finished_at_utc": result.request_finished_at_utc,
            "latency_ms": result.latency_ms,
            "attempt_count": result.attempt_count,
            "rate_limit_metadata": result.rate_limit_metadata,
            "trace_id": result.trace_id,
        }
    )


def _max_notional_from_rule(raw_filters: Any) -> Decimal | None:
    if not isinstance(raw_filters, list):
        return None
    for item in raw_filters:
        if not isinstance(item, dict) or item.get("filterType") not in {"MAX_NOTIONAL", "NOTIONAL"}:
            continue
        for key in ("maxNotional", "notionalCap"):
            value = item.get(key)
            if value not in (None, ""):
                parsed = Decimal(str(value))
                if parsed > ZERO:
                    return parsed
    return None


def _positive_decimal(value: Any) -> Decimal:
    if value in (None, ""):
        raise ValueError("decimal_missing")
    parsed = Decimal(str(value))
    if not parsed.is_finite() or parsed <= ZERO:
        raise ValueError("decimal_invalid")
    return parsed


def _decimal_places_allowed(value: Decimal, precision: int | None) -> bool:
    if precision is None or precision < 0:
        return False
    exponent = value.normalize().as_tuple().exponent
    places = abs(exponent) if exponent < 0 else 0
    return places <= precision


def _blocked_event_type(reason_code: str) -> str:
    if reason_code == "live_price_unavailable":
        return "execution_preparation_live_price_unavailable"
    if reason_code == "live_price_deviation_exceeded":
        return "execution_preparation_price_deviation_exceeded"
    if reason_code == "reduce_only_invalid":
        return "execution_preparation_reduce_only_invalid"
    if reason_code == "exchange_rule_violation":
        return "execution_preparation_exchange_rule_violation"
    return "execution_preparation_blocked"


def _blocked_without_result(reason_code: str, message: str, business_request_key: str, trace_id: str, trigger_source: str) -> ServiceResult:
    record_execution_preparation_alert(
        event_type="execution_preparation_blocked",
        business_request_key=business_request_key or "invalid-execution-preparation-request",
        trace_id=trace_id,
        trigger_source=trigger_source,
        status=ExecutionPreparationStatus.BLOCKED,
        reason_code=reason_code,
        message=message,
    )
    return ServiceResult(ResultStatus.BLOCKED, reason_code, message, trace_id, trigger_source, _empty_result_data())


def _failed_without_result(reason_code: str, message: str, business_request_key: str, trace_id: str, trigger_source: str) -> ServiceResult:
    record_execution_preparation_alert(
        event_type="execution_preparation_failed",
        business_request_key=business_request_key or "invalid-execution-preparation-request",
        trace_id=trace_id,
        trigger_source=trigger_source,
        status=ExecutionPreparationStatus.FAILED,
        reason_code=reason_code,
        message=message,
    )
    return ServiceResult(ResultStatus.FAILED, reason_code, message, trace_id, trigger_source, _empty_result_data())


def _empty_result_data() -> dict[str, Any]:
    return {
        "execution_preparation_result_id": None,
        "prepared_order_intent_id": None,
        "allows_downstream": False,
        "flow_action": "STOP",
    }


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _json_ready(value: Any) -> Any:
    if isinstance(value, Decimal):
        return decimal_hash_value(value)
    if isinstance(value, datetime):
        return _ensure_utc(value).isoformat()
    if isinstance(value, dict):
        return {str(key): _json_ready(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_json_ready(item) for item in value]
    return value
