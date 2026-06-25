"""RiskCheck 模块：实现 P0 基础风控规则插件；不写数据库；不访问 Binance；不生成 ApprovedOrderIntent；不涉及交易执行。"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from apps.binance_account_sync.models import BinancePositionMode, BinanceSyncPurpose, BinanceSyncStatus
from apps.binance_gateway.types import MARKET_TYPE_COIN_M, MARKET_TYPE_USDS_M
from apps.order_plan.models import (
    ActiveLockStatus,
    CandidateIntentRole,
    CandidateIntentStatus,
    OrderPlanStatus,
)
from apps.order_plan.services.hashing import candidate_intent_hash, decimal_hash_value
from apps.price_snapshot.models import PriceType

from ..domain import (
    RiskCheckContext,
    RiskRuleEvaluation,
    component_decimal,
    decimal_is_multiple,
    decimal_or_none,
    decimal_places_allowed,
    total_component_value,
)
from ..models import RiskRuleDefinition, RiskRuleResultStatus


class BaseRiskRulePlugin:
    rule_code = ""

    def pass_result(self, definition: RiskRuleDefinition, message: str = "规则通过") -> RiskRuleEvaluation:
        return RiskRuleEvaluation.pass_result(definition, message)

    def deny(
        self,
        definition: RiskRuleDefinition,
        *,
        reason_code: str,
        message: str,
        evidence: dict[str, Any] | None = None,
        risk_measures: dict[str, Any] | None = None,
        fallback_can_be_checked: bool = False,
    ) -> RiskRuleEvaluation:
        return self._result(
            definition,
            status=RiskRuleResultStatus.DENY,
            reason_code=reason_code,
            message=message,
            evidence=evidence,
            risk_measures=risk_measures,
            fallback_can_be_checked=fallback_can_be_checked,
        )

    def blocked(
        self,
        definition: RiskRuleDefinition,
        *,
        reason_code: str,
        message: str,
        evidence: dict[str, Any] | None = None,
        risk_measures: dict[str, Any] | None = None,
        fallback_can_be_checked: bool = False,
    ) -> RiskRuleEvaluation:
        return self._result(
            definition,
            status=RiskRuleResultStatus.BLOCKED,
            reason_code=reason_code,
            message=message,
            evidence=evidence,
            risk_measures=risk_measures,
            fallback_can_be_checked=fallback_can_be_checked,
        )

    def failed(self, definition: RiskRuleDefinition, *, reason_code: str, message: str) -> RiskRuleEvaluation:
        return self._result(definition, status=RiskRuleResultStatus.FAILED, reason_code=reason_code, message=message)

    def _result(
        self,
        definition: RiskRuleDefinition,
        *,
        status: str,
        reason_code: str,
        message: str,
        evidence: dict[str, Any] | None = None,
        risk_measures: dict[str, Any] | None = None,
        fallback_can_be_checked: bool = False,
    ) -> RiskRuleEvaluation:
        merged_evidence = dict(evidence or {})
        if fallback_can_be_checked:
            merged_evidence["fallback_can_be_checked"] = True
        return RiskRuleEvaluation(
            rule_code=definition.rule_code,
            rule_version=definition.rule_version,
            status=status,
            severity=definition.severity,
            reason_code=reason_code,
            message_zh=message,
            risk_measures=risk_measures or {},
            evidence=merged_evidence,
            definition_hash=definition.definition_hash,
            params_hash=definition.params_hash,
        )


class CandidateIntentValidRule(BaseRiskRulePlugin):
    rule_code = "candidate_intent_valid"

    def evaluate(self, *, context: RiskCheckContext, definition: RiskRuleDefinition) -> RiskRuleEvaluation:
        candidate = context.candidate
        if candidate.status != CandidateIntentStatus.PENDING_RISK_CHECK:
            return self.blocked(definition, reason_code="candidate_not_pending_risk_check", message="候选订单意图不是待风控状态")
        if candidate.intent_role not in {CandidateIntentRole.PRIMARY, CandidateIntentRole.FALLBACK_REDUCE_ONLY}:
            return self.blocked(definition, reason_code="candidate_role_invalid", message="候选订单角色不合法")
        if candidate.side not in {"BUY", "SELL"} or candidate.position_side != "BOTH" or candidate.order_type != "MARKET":
            return self.blocked(definition, reason_code="candidate_order_parameters_invalid", message="候选订单基础参数不合法")
        if candidate.requested_size <= 0 or candidate.requested_notional <= 0:
            return self.blocked(definition, reason_code="candidate_requested_size_invalid", message="候选订单数量或名义价值不合法")
        expected_hash = candidate_intent_hash(_candidate_hash_payload(context, candidate))
        if expected_hash != candidate.intent_hash:
            return self.blocked(definition, reason_code="candidate_intent_hash_mismatch", message="候选订单意图 hash 不一致")
        return self.pass_result(definition)


class OrderPlanValidRule(BaseRiskRulePlugin):
    rule_code = "order_plan_valid"

    def evaluate(self, *, context: RiskCheckContext, definition: RiskRuleDefinition) -> RiskRuleEvaluation:
        plan = context.order_plan
        if plan.status != OrderPlanStatus.CREATED or not plan.allows_downstream:
            return self.blocked(definition, reason_code="order_plan_not_consumable", message="OrderPlan 不允许进入 RiskCheck")
        if plan.active_lock_id != context.active_lock.id:
            return self.blocked(definition, reason_code="order_plan_active_lock_mismatch", message="OrderPlan 绑定的 ActiveLock 不一致")
        return self.pass_result(definition)


class OrderComponentsValidRule(BaseRiskRulePlugin):
    rule_code = "order_components_valid"

    def evaluate(self, *, context: RiskCheckContext, definition: RiskRuleDefinition) -> RiskRuleEvaluation:
        candidate = context.candidate
        components = candidate.order_components or []
        if not isinstance(components, list) or not components:
            return self.blocked(definition, reason_code="order_components_missing", message="候选订单缺少风险组件")
        component_size = total_component_value(components, "size")
        component_notional = total_component_value(components, "notional")
        if component_size is None or component_notional is None:
            return self.blocked(definition, reason_code="order_components_value_invalid", message="订单风险组件数量或名义价值无法解析")
        if component_size != candidate.requested_size or component_notional != candidate.requested_notional:
            return self.blocked(definition, reason_code="order_components_total_mismatch", message="订单组件汇总与候选订单不一致")
        allowed_risk = {"reduce_risk", "increase_risk"}
        allowed_effect = {
            "open_long",
            "open_short",
            "increase_long",
            "increase_short",
            "reduce_long",
            "reduce_short",
            "close_long",
            "close_short",
        }
        for component in components:
            if component.get("side") != candidate.side:
                return self.blocked(definition, reason_code="order_component_side_mismatch", message="订单组件方向与候选订单方向不一致")
            if component.get("risk_effect") not in allowed_risk or component.get("position_effect") not in allowed_effect:
                return self.blocked(definition, reason_code="order_component_semantics_invalid", message="订单组件风险语义不合法")
        if candidate.exchange_reduce_only and any(item.get("risk_effect") != "reduce_risk" for item in components):
            return self.blocked(definition, reason_code="reduce_only_component_mismatch", message="reduce-only 候选订单包含增加风险组件")
        if not candidate.exchange_reduce_only and components and all(item.get("risk_effect") == "reduce_risk" for item in components):
            return self.blocked(definition, reason_code="reduce_risk_candidate_reduce_only_missing", message="纯降低风险订单必须具备 reduce-only 语义")
        return self.pass_result(definition)


class BusinessInputBindingValidRule(BaseRiskRulePlugin):
    rule_code = "business_input_binding_valid"

    def evaluate(self, *, context: RiskCheckContext, definition: RiskRuleDefinition) -> RiskRuleEvaluation:
        candidate = context.candidate
        plan = context.order_plan
        if candidate.order_plan_id != plan.id:
            return self.blocked(definition, reason_code="candidate_order_plan_mismatch", message="候选订单不属于当前 OrderPlan")
        if candidate.binance_sync_run_id != plan.binance_sync_run_id or candidate.price_snapshot_id != plan.price_snapshot_id:
            return self.blocked(definition, reason_code="candidate_fact_binding_mismatch", message="候选订单绑定的账户或价格事实不一致")
        if plan.binance_sync_run_id != context.sync_run.id or plan.price_snapshot_id != context.price_snapshot.id:
            return self.blocked(definition, reason_code="order_plan_fact_binding_mismatch", message="OrderPlan 绑定的账户或价格事实不一致")
        return self.pass_result(definition)


class BinanceSyncRunConsumableRule(BaseRiskRulePlugin):
    rule_code = "binance_sync_run_consumable"

    def evaluate(self, *, context: RiskCheckContext, definition: RiskRuleDefinition) -> RiskRuleEvaluation:
        sync_run = context.sync_run
        if sync_run.status != BinanceSyncStatus.SUCCEEDED:
            return self.blocked(definition, reason_code="binance_sync_run_not_succeeded", message="账户同步批次未成功")
        if sync_run.sync_purpose != BinanceSyncPurpose.TRADE_PREPARATION:
            return self.blocked(definition, reason_code="binance_sync_run_not_trade_preparation", message="风控不能消费后台展示账户批次")
        if sync_run.expires_at_utc is None or context.reference_time_utc > sync_run.expires_at_utc:
            return self.blocked(definition, reason_code="binance_sync_run_expired", message="账户同步批次已过期")
        if not sync_run.snapshot_set_hash:
            return self.blocked(definition, reason_code="snapshot_set_hash_missing", message="账户快照集合 hash 缺失")
        return self.pass_result(definition)


class SnapshotIntegrityRule(BaseRiskRulePlugin):
    rule_code = "snapshot_integrity"

    def evaluate(self, *, context: RiskCheckContext, definition: RiskRuleDefinition) -> RiskRuleEvaluation:
        if context.snapshot_integrity_reason:
            return self.blocked(definition, reason_code=context.snapshot_integrity_reason, message="账户快照集合完整性校验失败")
        if context.price_integrity_reason:
            return self.blocked(definition, reason_code=context.price_integrity_reason, message="价格快照完整性校验失败")
        return self.pass_result(definition)


class MarketIdentityConsistencyRule(BaseRiskRulePlugin):
    rule_code = "market_identity_consistency"

    def evaluate(self, *, context: RiskCheckContext, definition: RiskRuleDefinition) -> RiskRuleEvaluation:
        expected = (
            context.order_plan.exchange.lower(),
            context.order_plan.market_type,
            context.order_plan.account_domain,
            context.order_plan.symbol,
        )
        identities = [
            (
                context.sync_run.exchange.lower(),
                context.sync_run.market_type,
                context.sync_run.account_domain,
                context.order_plan.symbol,
            ),
            (
                context.price_snapshot.exchange.lower(),
                context.price_snapshot.market_type,
                context.price_snapshot.account_domain,
                context.price_snapshot.symbol,
            ),
            (
                context.account_snapshot.sync_run.exchange.lower(),
                context.account_snapshot.market_type,
                context.account_snapshot.account_domain,
                context.order_plan.symbol,
            ),
            (
                context.position_snapshot.sync_run.exchange.lower(),
                context.position_snapshot.market_type,
                context.position_snapshot.account_domain,
                context.position_snapshot.symbol,
            ),
            (
                context.symbol_rule_snapshot.sync_run.exchange.lower(),
                context.symbol_rule_snapshot.market_type,
                context.symbol_rule_snapshot.account_domain,
                context.symbol_rule_snapshot.symbol,
            ),
            (
                "binance",
                context.balance_snapshot.market_type,
                context.balance_snapshot.account_domain,
                context.order_plan.symbol,
            ),
            (
                "binance",
                context.candidate.market_type,
                context.candidate.account_domain,
                context.candidate.symbol,
            ),
            (
                context.active_lock.exchange.lower(),
                context.active_lock.market_type,
                context.active_lock.account_domain,
                context.active_lock.symbol,
            ),
        ]
        if any(item != expected for item in identities):
            return self.blocked(definition, reason_code="market_identity_mismatch", message="风控输入的市场身份不一致")
        return self.pass_result(definition)


class OneWayPositionModeRequiredRule(BaseRiskRulePlugin):
    rule_code = "one_way_position_mode_required"

    def evaluate(self, *, context: RiskCheckContext, definition: RiskRuleDefinition) -> RiskRuleEvaluation:
        if context.sync_run.position_mode != BinancePositionMode.ONE_WAY:
            return self.blocked(definition, reason_code="position_mode_not_supported", message="账户同步批次不是 One-Way 持仓模式")
        if context.account_snapshot.position_mode != BinancePositionMode.ONE_WAY:
            return self.blocked(definition, reason_code="account_position_mode_not_one_way", message="账户快照不是 One-Way 持仓模式")
        if context.position_snapshot.position_mode_observed != BinancePositionMode.ONE_WAY:
            return self.blocked(definition, reason_code="position_snapshot_mode_not_one_way", message="持仓快照不是 One-Way 持仓模式")
        if context.candidate.position_mode != BinancePositionMode.ONE_WAY or context.order_plan.position_mode != BinancePositionMode.ONE_WAY:
            return self.blocked(definition, reason_code="candidate_position_mode_not_one_way", message="订单链持仓模式不是 One-Way")
        return self.pass_result(definition)


class ActiveLockConsistencyRule(BaseRiskRulePlugin):
    rule_code = "active_lock_consistency"

    def evaluate(self, *, context: RiskCheckContext, definition: RiskRuleDefinition) -> RiskRuleEvaluation:
        lock = context.active_lock
        if lock.status != ActiveLockStatus.ACTIVE:
            return self.blocked(definition, reason_code="active_lock_not_active", message="ActiveLock 不是 active 状态")
        if lock.current_order_plan_id != context.order_plan.id:
            return self.blocked(definition, reason_code="active_lock_order_plan_mismatch", message="ActiveLock 未绑定当前 OrderPlan")
        return self.pass_result(definition)


class PriceSnapshotPresentRule(BaseRiskRulePlugin):
    rule_code = "price_snapshot_present"

    def evaluate(self, *, context: RiskCheckContext, definition: RiskRuleDefinition) -> RiskRuleEvaluation:
        price = context.price_snapshot
        if price.price_type != PriceType.MARK_PRICE:
            return self.blocked(definition, reason_code="price_snapshot_type_invalid", message="RiskCheck 只能消费 mark price 快照")
        if price.mark_price <= 0:
            return self.blocked(definition, reason_code="price_snapshot_mark_price_invalid", message="PriceSnapshot 标记价格不合法")
        return self.pass_result(definition)


class PriceSnapshotFreshRule(BaseRiskRulePlugin):
    rule_code = "price_snapshot_fresh"

    def evaluate(self, *, context: RiskCheckContext, definition: RiskRuleDefinition) -> RiskRuleEvaluation:
        if context.price_snapshot.expires_at_utc is None or context.reference_time_utc > context.price_snapshot.expires_at_utc:
            return self.blocked(definition, reason_code="price_snapshot_stale", message="PriceSnapshot 已过期")
        return self.pass_result(definition)


class UsdsMBalanceAvailableRule(BaseRiskRulePlugin):
    rule_code = "usds_m_balance_available"

    def evaluate(self, *, context: RiskCheckContext, definition: RiskRuleDefinition) -> RiskRuleEvaluation:
        if context.order_plan.market_type != MARKET_TYPE_USDS_M:
            return self.pass_result(definition, "非 USDS-M 市场，不适用")
        if context.balance_snapshot.available_balance is None:
            return self.blocked(definition, reason_code="available_balance_missing", message="USDS-M 可用余额缺失", fallback_can_be_checked=True)
        if context.balance_snapshot.available_balance < 0:
            return self.blocked(definition, reason_code="available_balance_invalid", message="USDS-M 可用余额不合法", fallback_can_be_checked=True)
        return self.pass_result(definition)


class CoinMBalanceAvailableRule(BaseRiskRulePlugin):
    rule_code = "coin_m_balance_available"

    def evaluate(self, *, context: RiskCheckContext, definition: RiskRuleDefinition) -> RiskRuleEvaluation:
        if context.order_plan.market_type != MARKET_TYPE_COIN_M:
            return self.pass_result(definition, "非 COIN-M 市场，不适用")
        if not context.symbol_rule_snapshot.settlement_asset and not context.symbol_rule_snapshot.margin_asset:
            return self.blocked(definition, reason_code="coin_m_margin_asset_missing", message="COIN-M 结算或保证金资产缺失", fallback_can_be_checked=True)
        if context.balance_snapshot.available_balance is None:
            return self.blocked(definition, reason_code="available_balance_native_missing", message="COIN-M 可用余额缺失", fallback_can_be_checked=True)
        if context.balance_snapshot.available_balance < 0:
            return self.blocked(definition, reason_code="available_balance_native_invalid", message="COIN-M 可用余额不合法", fallback_can_be_checked=True)
        return self.pass_result(definition)


class SymbolRuleMinNotionalRule(BaseRiskRulePlugin):
    rule_code = "symbol_rule_min_notional"

    def evaluate(self, *, context: RiskCheckContext, definition: RiskRuleDefinition) -> RiskRuleEvaluation:
        min_notional = context.symbol_rule_snapshot.min_notional
        if min_notional is None:
            return self.blocked(definition, reason_code="symbol_rule_min_notional_missing", message="交易规则缺少最小名义价值")
        if context.candidate.requested_notional < min_notional:
            return self.deny(
                definition,
                reason_code="candidate_below_min_notional",
                message="候选订单低于交易所最小名义价值",
                evidence={"requested_notional": str(context.candidate.requested_notional), "min_notional": str(min_notional)},
            )
        return self.pass_result(definition)


class SymbolRuleQuantityStepRule(BaseRiskRulePlugin):
    rule_code = "symbol_rule_quantity_step"

    def evaluate(self, *, context: RiskCheckContext, definition: RiskRuleDefinition) -> RiskRuleEvaluation:
        rule = context.symbol_rule_snapshot
        if rule.step_size is None or rule.step_size <= 0 or rule.min_quantity is None or rule.quantity_precision is None:
            return self.blocked(definition, reason_code="symbol_rule_quantity_fields_missing", message="交易规则数量字段缺失")
        if context.candidate.requested_size < rule.min_quantity:
            return self.deny(definition, reason_code="candidate_below_min_quantity", message="候选订单低于交易所最小数量")
        if not decimal_is_multiple(context.candidate.requested_size, rule.step_size):
            return self.deny(definition, reason_code="candidate_quantity_step_invalid", message="候选订单数量不符合 step_size")
        if not decimal_places_allowed(context.candidate.requested_size, rule.quantity_precision):
            return self.deny(definition, reason_code="candidate_quantity_precision_invalid", message="候选订单数量精度不合法")
        return self.pass_result(definition)


class SymbolRuleMaxQuantityRule(BaseRiskRulePlugin):
    rule_code = "symbol_rule_max_quantity"

    def evaluate(self, *, context: RiskCheckContext, definition: RiskRuleDefinition) -> RiskRuleEvaluation:
        max_quantity = context.symbol_rule_snapshot.max_quantity
        if max_quantity is None:
            return self.blocked(definition, reason_code="symbol_rule_max_quantity_missing", message="交易规则缺少最大数量")
        if context.candidate.requested_size > max_quantity:
            return self.deny(
                definition,
                reason_code="candidate_exceeds_max_quantity",
                message="候选订单超过交易所最大数量",
                fallback_can_be_checked=True,
            )
        return self.pass_result(definition)


class SymbolRuleMaxNotionalRule(BaseRiskRulePlugin):
    rule_code = "symbol_rule_max_notional"

    def evaluate(self, *, context: RiskCheckContext, definition: RiskRuleDefinition) -> RiskRuleEvaluation:
        max_notional = _max_notional_from_rule(context.symbol_rule_snapshot.raw_filters)
        if max_notional is None:
            return self.pass_result(definition, "交易所未提供最大名义价值，不适用")
        if context.candidate.requested_notional > max_notional:
            return self.deny(
                definition,
                reason_code="candidate_exceeds_max_notional",
                message="候选订单超过交易所最大名义价值",
                evidence={"requested_notional": str(context.candidate.requested_notional), "max_notional": str(max_notional)},
                fallback_can_be_checked=True,
            )
        return self.pass_result(definition)


class AvailableMarginCheckRule(BaseRiskRulePlugin):
    rule_code = "available_margin_check"

    def evaluate(self, *, context: RiskCheckContext, definition: RiskRuleDefinition) -> RiskRuleEvaluation:
        if not context.has_increase_risk_component:
            return self.pass_result(definition, "纯降低风险订单不需要新增保证金检查")
        leverage = context.position_snapshot.observed_exchange_leverage
        if leverage is None or leverage <= 0:
            return self.blocked(
                definition,
                reason_code="observed_exchange_leverage_missing",
                message="新增风险订单缺少可验证交易所杠杆",
                fallback_can_be_checked=True,
            )
        margin_required = _margin_required(context)
        if margin_required is None:
            return self.blocked(
                definition,
                reason_code="margin_required_unavailable",
                message="新增保证金估算所需事实缺失",
                fallback_can_be_checked=True,
            )
        available = context.balance_snapshot.available_balance
        if available is None:
            return self.blocked(
                definition,
                reason_code="available_balance_missing",
                message="可用余额缺失，无法审批新增风险",
                fallback_can_be_checked=True,
            )
        buffer_ratio = Decimal(str(context.risk_config["margin_buffer_ratio"]))
        required_with_buffer = margin_required * (Decimal("1") + buffer_ratio)
        measures = {
            "margin_required_total": str(margin_required),
            "margin_required_with_buffer": str(required_with_buffer),
            "available_balance": str(available),
            "observed_exchange_leverage": str(leverage),
        }
        if available < required_with_buffer:
            return self.deny(
                definition,
                reason_code="available_margin_insufficient",
                message="可用余额不足以覆盖新增风险保证金和安全缓冲",
                risk_measures=measures,
                fallback_can_be_checked=True,
            )
        return RiskRuleEvaluation.pass_result(definition, "新增保证金检查通过")


class ReverseFallbackReduceOnlyRule(BaseRiskRulePlugin):
    rule_code = "reverse_fallback_reduce_only"

    def evaluate(self, *, context: RiskCheckContext, definition: RiskRuleDefinition) -> RiskRuleEvaluation:
        if not _is_reverse_candidate(context.primary_candidate):
            return self.pass_result(definition, "非净额反手场景，不适用")
        fallback = context.fallback_candidate
        if fallback is None:
            return self.blocked(definition, reason_code="fallback_reduce_only_missing", message="净额反手缺少预生成 fallback_reduce_only")
        if fallback.order_plan_id != context.order_plan.id or fallback.intent_role != CandidateIntentRole.FALLBACK_REDUCE_ONLY:
            return self.blocked(definition, reason_code="fallback_reduce_only_binding_invalid", message="fallback_reduce_only 绑定不合法")
        if not fallback.exchange_reduce_only:
            return self.blocked(definition, reason_code="fallback_reduce_only_flag_missing", message="fallback_reduce_only 未具备 reduce-only 语义")
        if any(item.get("risk_effect") != "reduce_risk" for item in fallback.order_components or []):
            return self.blocked(definition, reason_code="fallback_reduce_only_component_invalid", message="fallback_reduce_only 包含非降低风险组件")
        return self.pass_result(definition)


def _candidate_hash_payload(context: RiskCheckContext, candidate) -> dict[str, Any]:
    return {
        "order_plan_hash": context.order_plan.order_plan_hash,
        "intent_role": candidate.intent_role,
        "plan_type": candidate.plan_type,
        "side": candidate.side,
        "exchange_reduce_only": candidate.exchange_reduce_only,
        "requested_size": decimal_hash_value(candidate.requested_size),
        "requested_notional": decimal_hash_value(candidate.requested_notional),
        "requested_size_unit": candidate.requested_size_unit,
        "order_components": candidate.order_components,
        "price_snapshot_hash": context.price_snapshot.price_snapshot_hash,
        "snapshot_set_hash": context.sync_run.snapshot_set_hash,
    }


def _max_notional_from_rule(raw_filters: Any) -> Decimal | None:
    if not isinstance(raw_filters, list):
        return None
    for item in raw_filters:
        if not isinstance(item, dict):
            continue
        if item.get("filterType") not in {"MAX_NOTIONAL", "NOTIONAL"}:
            continue
        for key in ("maxNotional", "notionalCap"):
            value = decimal_or_none(item.get(key))
            if value is not None and value > 0:
                return value
    return None


def _margin_required(context: RiskCheckContext) -> Decimal | None:
    opening_size = context.candidate.opening_size
    if opening_size <= 0:
        opening_size = sum(
            component_decimal(item, "size") or Decimal("0")
            for item in context.candidate.order_components
            if item.get("risk_effect") == "increase_risk"
        )
    leverage = context.position_snapshot.observed_exchange_leverage
    if leverage is None or leverage <= 0:
        return None
    if context.order_plan.market_type == MARKET_TYPE_USDS_M:
        return (opening_size * context.price_snapshot.mark_price) / leverage
    if context.order_plan.market_type == MARKET_TYPE_COIN_M:
        contract_size = context.symbol_rule_snapshot.contract_size
        if contract_size is None or contract_size <= 0 or context.price_snapshot.mark_price <= 0:
            return None
        return (opening_size * contract_size) / context.price_snapshot.mark_price / leverage
    return None


def _is_reverse_candidate(candidate) -> bool:
    return candidate.plan_type in {"netting_reverse_long_to_short", "netting_reverse_short_to_long"}


BUILTIN_PLUGINS = [
    CandidateIntentValidRule(),
    OrderPlanValidRule(),
    OrderComponentsValidRule(),
    BusinessInputBindingValidRule(),
    BinanceSyncRunConsumableRule(),
    SnapshotIntegrityRule(),
    MarketIdentityConsistencyRule(),
    OneWayPositionModeRequiredRule(),
    ActiveLockConsistencyRule(),
    PriceSnapshotPresentRule(),
    PriceSnapshotFreshRule(),
    UsdsMBalanceAvailableRule(),
    CoinMBalanceAvailableRule(),
    SymbolRuleMinNotionalRule(),
    SymbolRuleQuantityStepRule(),
    SymbolRuleMaxQuantityRule(),
    SymbolRuleMaxNotionalRule(),
    AvailableMarginCheckRule(),
    ReverseFallbackReduceOnlyRule(),
]
