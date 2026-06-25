"""OrderPlan 模块：执行纯 Decimal 仓位换算和订单组件计算；不读写数据库；不访问 Redis 或外部服务；不发送 Hermes；不调用大模型；不提交订单；不允许真实交易。"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_DOWN
from typing import Any

from apps.binance_gateway.types import MARKET_TYPE_COIN_M, MARKET_TYPE_USDS_M


ZERO = Decimal("0")
ONE = Decimal("1")


class OrderPlanCalculationError(ValueError):
    def __init__(self, reason_code: str, message: str) -> None:
        super().__init__(message)
        self.reason_code = reason_code
        self.message = message


@dataclass(frozen=True)
class TradingRule:
    step_size: Decimal
    min_quantity: Decimal
    max_quantity: Decimal
    min_notional: Decimal
    quantity_precision: int
    contract_size: Decimal | None
    base_asset: str


@dataclass(frozen=True)
class IntentDraft:
    intent_role: str
    plan_type: str
    side: str
    exchange_reduce_only: bool
    requested_size: Decimal
    requested_notional: Decimal
    requested_size_unit: str
    closing_size: Decimal
    opening_size: Decimal
    residual_position_size: Decimal
    order_components: list[dict[str, Any]]


@dataclass(frozen=True)
class PlanDraft:
    current_equity: Decimal
    current_signed_size: Decimal
    raw_target_signed_size: Decimal
    target_signed_size: Decimal
    delta_signed_size: Decimal
    target_notional: Decimal
    normalized_order_notional: Decimal
    status: str
    reason_code: str
    primary: IntentDraft | None
    fallback: IntentDraft | None


def finite_decimal(value: Any, *, reason_code: str, field_name: str) -> Decimal:
    try:
        decimal = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise OrderPlanCalculationError(reason_code, f"{field_name} 不是合法 Decimal") from exc
    if not decimal.is_finite():
        raise OrderPlanCalculationError(reason_code, f"{field_name} 必须是有限 Decimal")
    return decimal


def floor_to_step(value: Decimal, step_size: Decimal) -> Decimal:
    if step_size <= ZERO:
        raise OrderPlanCalculationError("symbol_rule_step_size_invalid", "交易规则 step_size 必须大于零")
    sign = Decimal("-1") if value < ZERO else ONE
    units = (abs(value) / step_size).to_integral_value(rounding=ROUND_DOWN)
    result = sign * units * step_size
    return ZERO if result == ZERO else result


def build_trading_rule(
    *,
    step_size: Any,
    min_quantity: Any,
    max_quantity: Any,
    min_notional: Any,
    quantity_precision: int | None,
    contract_size: Any,
    base_asset: str,
    market_type: str,
) -> TradingRule:
    if quantity_precision is None or quantity_precision < 0:
        raise OrderPlanCalculationError("symbol_rule_quantity_precision_invalid", "交易规则缺少合法 quantity_precision")
    step = finite_decimal(step_size, reason_code="symbol_rule_step_size_invalid", field_name="step_size")
    minimum = finite_decimal(min_quantity, reason_code="symbol_rule_min_quantity_invalid", field_name="min_quantity")
    maximum = finite_decimal(max_quantity, reason_code="symbol_rule_max_quantity_invalid", field_name="max_quantity")
    minimum_notional = finite_decimal(
        min_notional,
        reason_code="symbol_rule_min_notional_invalid",
        field_name="min_notional",
    )
    if step <= ZERO or minimum < ZERO or maximum <= ZERO or minimum_notional < ZERO or minimum > maximum:
        raise OrderPlanCalculationError("symbol_rule_invalid", "交易规则数量或名义边界非法")
    if _decimal_places(step) > quantity_precision:
        raise OrderPlanCalculationError("symbol_rule_precision_mismatch", "step_size 超出 quantity_precision 可表达范围")
    normalized_contract_size: Decimal | None = None
    if market_type == MARKET_TYPE_COIN_M:
        normalized_contract_size = finite_decimal(
            contract_size,
            reason_code="coin_m_contract_size_missing",
            field_name="contract_size",
        )
        if normalized_contract_size <= ZERO:
            raise OrderPlanCalculationError("coin_m_contract_size_missing", "COIN-M 缺少有效 contract_size")
    return TradingRule(
        step_size=step,
        min_quantity=minimum,
        max_quantity=maximum,
        min_notional=minimum_notional,
        quantity_precision=quantity_precision,
        contract_size=normalized_contract_size,
        base_asset=base_asset.upper(),
    )


def calculate_order_plan(
    *,
    market_type: str,
    target_position_ratio: Any,
    current_equity: Any,
    current_signed_size: Any,
    mark_price: Any,
    max_target_notional_to_equity_ratio: Any,
    min_rebalance_notional: Any,
    rule: TradingRule,
) -> PlanDraft:
    if market_type not in {MARKET_TYPE_USDS_M, MARKET_TYPE_COIN_M}:
        raise OrderPlanCalculationError("market_type_not_supported", "OrderPlan 不支持当前市场类型")
    ratio = finite_decimal(target_position_ratio, reason_code="target_position_ratio_invalid", field_name="target_position_ratio")
    equity = finite_decimal(current_equity, reason_code="current_equity_invalid", field_name="current_equity")
    current = finite_decimal(current_signed_size, reason_code="current_position_invalid", field_name="current_signed_size")
    price = finite_decimal(mark_price, reason_code="mark_price_invalid", field_name="mark_price")
    maximum_ratio = finite_decimal(
        max_target_notional_to_equity_ratio,
        reason_code="order_plan_config_invalid",
        field_name="max_target_notional_to_equity_ratio",
    )
    minimum_rebalance = finite_decimal(
        min_rebalance_notional,
        reason_code="order_plan_config_invalid",
        field_name="min_rebalance_notional",
    )
    if ratio < -ONE or ratio > ONE:
        raise OrderPlanCalculationError("target_position_ratio_out_of_range", "目标仓位比例必须位于 [-1, 1]")
    if price <= ZERO or maximum_ratio <= ZERO or minimum_rebalance < ZERO:
        raise OrderPlanCalculationError("order_plan_input_invalid", "权益、价格或 OrderPlan 配置非法")
    if ratio != ZERO and equity <= ZERO:
        raise OrderPlanCalculationError("current_equity_invalid", "非零目标仓位要求当前账户权益大于零")

    equity_notional = equity if market_type == MARKET_TYPE_USDS_M else equity * price
    target_notional = ZERO if ratio == ZERO else equity_notional * maximum_ratio * abs(ratio)
    denominator = price if market_type == MARKET_TYPE_USDS_M else rule.contract_size
    if denominator is None or denominator <= ZERO:
        raise OrderPlanCalculationError("coin_m_contract_size_missing", "COIN-M 缺少有效 contract_size")
    raw_abs_target = target_notional / denominator
    raw_target = _sign(ratio) * raw_abs_target
    target = floor_to_step(raw_target, rule.step_size)
    if market_type == MARKET_TYPE_COIN_M and target != target.to_integral_value():
        raise OrderPlanCalculationError("coin_m_contracts_not_integer", "COIN-M 目标合约张数必须为整数")

    normalized_target_notional = _notional(market_type, abs(target), price, rule)
    delta = target - current
    if delta == ZERO:
        return _no_order(equity, current, raw_target, target, delta, normalized_target_notional, "target_already_reached")

    primary, fallback = _build_intents(
        market_type=market_type,
        current=current,
        target=target,
        delta=delta,
        mark_price=price,
        rule=rule,
    )
    if primary.requested_size <= ZERO:
        return _no_order(equity, current, raw_target, target, delta, normalized_target_notional, "normalized_delta_zero")
    _validate_maximum(primary, rule)
    small_reason = _minimum_reason(primary, rule, minimum_rebalance)
    if small_reason:
        if primary.exchange_reduce_only and small_reason in {
            "below_exchange_min_quantity",
            "below_exchange_min_notional",
        }:
            raise OrderPlanCalculationError(
                "reduce_only_quantity_invalid",
                f"只减仓订单不满足交易所最小交易规则：{small_reason}",
            )
        return _no_order(
            equity,
            current,
            raw_target,
            target,
            delta,
            normalized_target_notional,
            small_reason,
            normalized_order_notional=primary.requested_notional,
        )
    if fallback is not None:
        _validate_maximum(fallback, rule)
        fallback_small_reason = _minimum_reason(fallback, rule, ZERO)
        if fallback_small_reason:
            raise OrderPlanCalculationError(
                "fallback_reduce_only_invalid",
                f"净额反手后备减仓意图不满足交易规则：{fallback_small_reason}",
            )
    return PlanDraft(
        current_equity=equity,
        current_signed_size=current,
        raw_target_signed_size=raw_target,
        target_signed_size=target,
        delta_signed_size=delta,
        target_notional=normalized_target_notional,
        normalized_order_notional=primary.requested_notional,
        status="created",
        reason_code="order_plan_created",
        primary=primary,
        fallback=fallback,
    )


def _build_intents(
    *,
    market_type: str,
    current: Decimal,
    target: Decimal,
    delta: Decimal,
    mark_price: Decimal,
    rule: TradingRule,
) -> tuple[IntentDraft, IntentDraft | None]:
    requested_unit = rule.base_asset or "base_asset"
    if market_type == MARKET_TYPE_COIN_M:
        requested_unit = "contracts"
        if current != current.to_integral_value():
            raise OrderPlanCalculationError("position_quantity_not_aligned", "COIN-M 当前持仓张数不是整数")

    reversing = current != ZERO and target != ZERO and _sign(current) != _sign(target)
    if reversing:
        closing = floor_to_step(abs(current), rule.step_size)
        residual = abs(current) - closing
        if residual != ZERO:
            raise OrderPlanCalculationError("position_quantity_not_aligned", "当前持仓无法按交易规则完整关闭，禁止净额反手")
        opening = abs(target)
        requested = closing + opening
        plan_type = "netting_reverse_long_to_short" if current > ZERO else "netting_reverse_short_to_long"
        side = "SELL" if current > ZERO else "BUY"
        primary_components = [
            _component(0, "close_existing_position", "close_long" if current > ZERO else "close_short", side, closing, requested_unit, _notional(market_type, closing, mark_price, rule), "reduce_risk", True),
            _component(1, "open_new_position", "open_short" if target < ZERO else "open_long", side, opening, requested_unit, _notional(market_type, opening, mark_price, rule), "increase_risk", False),
        ]
        primary = _intent(
            role="primary",
            plan_type=plan_type,
            side=side,
            reduce_only=False,
            requested=requested,
            unit=requested_unit,
            closing=closing,
            opening=opening,
            residual=ZERO,
            components=primary_components,
            market_type=market_type,
            mark_price=mark_price,
            rule=rule,
        )
        fallback = _intent(
            role="fallback_reduce_only",
            plan_type="close_long" if current > ZERO else "close_short",
            side=side,
            reduce_only=True,
            requested=closing,
            unit=requested_unit,
            closing=closing,
            opening=ZERO,
            residual=ZERO,
            components=[primary_components[0]],
            market_type=market_type,
            mark_price=mark_price,
            rule=rule,
        )
        return primary, fallback

    requested = floor_to_step(abs(delta), rule.step_size)
    residual = abs(delta) - requested
    side = "BUY" if delta > ZERO else "SELL"
    plan_type, component_type, position_effect, risk_effect, reduce_only = _same_side_semantics(current, target)
    if reduce_only and requested == ZERO and current != target:
        raise OrderPlanCalculationError("reduce_only_quantity_invalid", "当前仓位差额无法形成合法只减仓数量")
    if reduce_only and target == ZERO and residual > ZERO:
        plan_type = "reduce_long" if current > ZERO else "reduce_short"
        component_type = "reduce_existing_position"
        position_effect = plan_type
    if reduce_only and requested > abs(current):
        raise OrderPlanCalculationError("reduce_only_quantity_invalid", "只减仓数量不得超过当前持仓")
    components = [
        _component(
            0,
            component_type,
            position_effect,
            side,
            requested,
            requested_unit,
            _notional(market_type, requested, mark_price, rule),
            risk_effect,
            reduce_only,
        )
    ]
    return (
        _intent(
            role="primary",
            plan_type=plan_type,
            side=side,
            reduce_only=reduce_only,
            requested=requested,
            unit=requested_unit,
            closing=requested if reduce_only else ZERO,
            opening=ZERO if reduce_only else requested,
            residual=residual,
            components=components,
            market_type=market_type,
            mark_price=mark_price,
            rule=rule,
        ),
        None,
    )


def _same_side_semantics(current: Decimal, target: Decimal) -> tuple[str, str, str, str, bool]:
    if current == ZERO:
        if target > ZERO:
            return "open_long", "open_new_position", "open_long", "increase_risk", False
        return "open_short", "open_new_position", "open_short", "increase_risk", False
    if target == ZERO:
        if current > ZERO:
            return "close_long", "close_existing_position", "close_long", "reduce_risk", True
        return "close_short", "close_existing_position", "close_short", "reduce_risk", True
    if abs(target) > abs(current):
        if target > ZERO:
            return "increase_long", "increase_existing_position", "increase_long", "increase_risk", False
        return "increase_short", "increase_existing_position", "increase_short", "increase_risk", False
    if current > ZERO:
        return "reduce_long", "reduce_existing_position", "reduce_long", "reduce_risk", True
    return "reduce_short", "reduce_existing_position", "reduce_short", "reduce_risk", True


def _intent(
    *,
    role: str,
    plan_type: str,
    side: str,
    reduce_only: bool,
    requested: Decimal,
    unit: str,
    closing: Decimal,
    opening: Decimal,
    residual: Decimal,
    components: list[dict[str, Any]],
    market_type: str,
    mark_price: Decimal,
    rule: TradingRule,
) -> IntentDraft:
    return IntentDraft(
        intent_role=role,
        plan_type=plan_type,
        side=side,
        exchange_reduce_only=reduce_only,
        requested_size=requested,
        requested_notional=_notional(market_type, requested, mark_price, rule),
        requested_size_unit=unit,
        closing_size=closing,
        opening_size=opening,
        residual_position_size=residual,
        order_components=components,
    )


def _component(
    index: int,
    component_type: str,
    position_effect: str,
    side: str,
    size: Decimal,
    size_unit: str,
    notional: Decimal,
    risk_effect: str,
    is_risk_reducing: bool,
) -> dict[str, Any]:
    return {
        "component_index": index,
        "component_type": component_type,
        "position_effect": position_effect,
        "side": side,
        "size": str(size),
        "size_unit": size_unit,
        "notional": str(notional),
        "risk_effect": risk_effect,
        "is_risk_reducing": is_risk_reducing,
    }


def _notional(market_type: str, size: Decimal, mark_price: Decimal, rule: TradingRule) -> Decimal:
    if market_type == MARKET_TYPE_USDS_M:
        return size * mark_price
    assert rule.contract_size is not None
    return size * rule.contract_size


def _minimum_reason(intent: IntentDraft, rule: TradingRule, min_rebalance_notional: Decimal) -> str:
    if intent.requested_size < rule.min_quantity:
        return "below_exchange_min_quantity"
    if intent.requested_notional < rule.min_notional:
        return "below_exchange_min_notional"
    if intent.requested_notional < min_rebalance_notional:
        return "below_min_rebalance_notional"
    return ""


def _validate_maximum(intent: IntentDraft, rule: TradingRule) -> None:
    if intent.requested_size > rule.max_quantity:
        raise OrderPlanCalculationError("above_exchange_max_quantity", "候选订单数量超过交易所最大数量")


def _no_order(
    equity: Decimal,
    current: Decimal,
    raw_target: Decimal,
    target: Decimal,
    delta: Decimal,
    target_notional: Decimal,
    reason_code: str,
    *,
    normalized_order_notional: Decimal = ZERO,
) -> PlanDraft:
    return PlanDraft(
        current_equity=equity,
        current_signed_size=current,
        raw_target_signed_size=raw_target,
        target_signed_size=target,
        delta_signed_size=delta,
        target_notional=target_notional,
        normalized_order_notional=normalized_order_notional,
        status="no_order_required",
        reason_code=reason_code,
        primary=None,
        fallback=None,
    )


def _sign(value: Decimal) -> Decimal:
    if value > ZERO:
        return ONE
    if value < ZERO:
        return Decimal("-1")
    return ZERO


def _decimal_places(value: Decimal) -> int:
    exponent = value.normalize().as_tuple().exponent
    return max(0, -int(exponent))
