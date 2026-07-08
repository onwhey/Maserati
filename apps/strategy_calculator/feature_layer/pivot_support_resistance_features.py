"""FeatureLayer 模块：pivot_support_resistance_features/1.0.0 拐点型支撑压力 calculator。

负责：基于 MarketSnapshot 冻结的已收盘 1d / 4h K 线识别有效局部高低点，并输出窄支撑区/压力区特征。
不负责：生成原子信号、领域信号、市场环境、策略信号、目标仓位、订单意图或交易动作。
读写数据库：不涉及。
访问 Redis：不涉及。
访问外部服务：不涉及。
发送 Hermes：不涉及。
调用大模型：不涉及。
涉及交易执行：不涉及。
允许真实交易：否。
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from statistics import median
from typing import Any, Callable, Mapping

from ..contracts import CalculatorInput, CalculatorMetadata, CalculatorOutput, CalculatorType
from .kline_price_features import FeatureCalculationError, KlineBar, _bars_for_timeframe, _mean, _safe_div, _tail, _true_range


@dataclass(frozen=True)
class PivotPoint:
    index: int
    price: Decimal
    reaction_pct: Decimal


@dataclass(frozen=True)
class PivotZone:
    role: str
    lower: Decimal
    upper: Decimal
    core: Decimal
    width_pct: Decimal
    touch_count: int
    strength: Decimal
    status: str
    distance_pct: Decimal
    distance_atr: Decimal
    first_touch_index: int
    last_touch_index: int


class PivotSupportResistanceFeatureCalculator:
    metadata = CalculatorMetadata(
        algorithm_name="pivot_support_resistance_features",
        algorithm_version="1.0.0",
        calculator_type=CalculatorType.FEATURE_LAYER,
        input_schema_version="1.0",
        output_schema_version="1.0",
        deterministic=True,
        supports_dry_run=True,
        algorithm_requirement_document_path="docs/requirements/feature_layer/support_resistance_level_features.md",
        implementation_document_path="docs/plans/structure_pivot_support_resistance_implementation_slice.md",
    )

    def calculate(self, calculation_input: CalculatorInput) -> CalculatorOutput:
        params = dict(calculation_input.frozen_params)
        values = dict(calculation_input.values)
        operation = str(params.get("operation") or "").strip()
        if operation != "pivot_zone_metric":
            return self._failed("feature_operation_unsupported", f"不支持的 Feature operation：{operation}")
        try:
            market_snapshot = values.get("market_snapshot")
            if not isinstance(market_snapshot, Mapping):
                raise FeatureCalculationError("market_snapshot_missing", "缺少 MarketSnapshot K 线输入")
            timeframe = str(params.get("timeframe") or "").strip()
            bars = _bars_for_timeframe(market_snapshot, timeframe)
            value = self._pivot_zone_metric(bars=bars, params=params)
        except FeatureCalculationError as exc:
            return self._failed(exc.error_code, exc.message)
        return CalculatorOutput.succeeded(
            output_schema_version=self.metadata.output_schema_version,
            values={"value": value},
            evidence_items=(
                {
                    "algorithm": self.metadata.algorithm_name,
                    "algorithm_version": self.metadata.algorithm_version,
                    "operation": operation,
                    "timeframe": params.get("timeframe"),
                    "window": params.get("window"),
                    "side": params.get("side"),
                    "metric": params.get("metric"),
                    "value": "" if value is None else str(value),
                },
            ),
            calculation_summary={
                "operation": operation,
                "timeframe": params.get("timeframe"),
                "window": params.get("window"),
                "input_count": len(bars),
            },
        )

    def _pivot_zone_metric(self, *, bars: list[KlineBar], params: dict[str, Any]) -> Decimal | str | None:
        metric = str(params.get("metric") or "").strip()
        side = str(params.get("side") or "").strip()
        if side not in {"support", "resistance"}:
            raise FeatureCalculationError("feature_params_invalid", "side 只支持 support/resistance")
        if not metric:
            raise FeatureCalculationError("feature_params_invalid", "参数 metric 不能为空")
        zone = _build_pivot_zone(bars=bars, params=params, side=side)
        if zone is None:
            return _empty_metric_value(metric)
        handlers: dict[str, Callable[[PivotZone], Decimal | str]] = {
            "lower": lambda item: item.lower,
            "upper": lambda item: item.upper,
            "core": lambda item: item.core,
            "width_pct": lambda item: item.width_pct,
            "touch_count": lambda item: Decimal(item.touch_count),
            "strength": lambda item: item.strength,
            "status": lambda item: item.status,
            "distance_pct": lambda item: item.distance_pct,
            "distance_atr": lambda item: item.distance_atr,
        }
        handler = handlers.get(metric)
        if handler is None:
            raise FeatureCalculationError("feature_params_invalid", f"不支持的 pivot zone metric：{metric}")
        return handler(zone)

    @classmethod
    def _failed(cls, error_code: str, error_message: str) -> CalculatorOutput:
        return CalculatorOutput.failed(
            output_schema_version=cls.metadata.output_schema_version,
            error_code=error_code,
            error_message=error_message,
        )


def _empty_metric_value(metric: str) -> Decimal | str | None:
    if metric == "status":
        return "none"
    if metric in {"touch_count", "strength"}:
        return Decimal("0")
    return None


def _build_pivot_zone(*, bars: list[KlineBar], params: dict[str, Any], side: str) -> PivotZone | None:
    window = _positive_int(params, "window")
    source = _tail(bars, window)
    current = source[-1]
    reference = source[:-1]
    pivot_left = _positive_int(params, "pivot_left")
    pivot_right = _positive_int(params, "pivot_right")
    if len(reference) < pivot_left + pivot_right + 1:
        raise FeatureCalculationError("pivot_reference_window_insufficient", "拐点支撑压力参考窗口不足")
    atr = _atr(source, _positive_int(params, "atr_window"))
    pivots = _validated_pivots(reference=reference, side=side, atr=atr, params=params)
    if not pivots:
        return None
    zones = _pivot_zones(reference=reference, current=current, pivots=pivots, side=side, atr=atr, params=params)
    if not zones:
        return None
    return min(zones, key=lambda zone: (abs(zone.distance_pct), Decimal("1") - zone.strength))


def _validated_pivots(
    *,
    reference: list[KlineBar],
    side: str,
    atr: Decimal,
    params: dict[str, Any],
) -> list[PivotPoint]:
    pivot_left = _positive_int(params, "pivot_left")
    pivot_right = _positive_int(params, "pivot_right")
    reaction_window = _positive_int(params, "reaction_window")
    raw: list[PivotPoint] = []
    for idx in range(pivot_left, len(reference) - pivot_right):
        if not _is_pivot(reference=reference, side=side, idx=idx, pivot_left=pivot_left, pivot_right=pivot_right):
            continue
        reaction = _pivot_reaction_pct(reference=reference, side=side, idx=idx, reaction_window=reaction_window)
        if reaction >= _reaction_threshold_pct(price=_pivot_price(reference[idx], side), atr=atr, params=params):
            raw.append(PivotPoint(index=idx, price=_pivot_price(reference[idx], side), reaction_pct=reaction))
    return _space_pivots(raw, _positive_int(params, "min_spacing_bars"))


def _is_pivot(*, reference: list[KlineBar], side: str, idx: int, pivot_left: int, pivot_right: int) -> bool:
    bar = reference[idx]
    left = reference[idx - pivot_left : idx]
    right = reference[idx + 1 : idx + 1 + pivot_right]
    if side == "support":
        return bar.low <= min(item.low for item in left) and bar.low <= min(item.low for item in right)
    return bar.high >= max(item.high for item in left) and bar.high >= max(item.high for item in right)


def _pivot_reaction_pct(*, reference: list[KlineBar], side: str, idx: int, reaction_window: int) -> Decimal:
    bar = reference[idx]
    future = reference[idx + 1 : idx + 1 + reaction_window]
    if not future:
        return Decimal("0")
    if side == "support":
        return _safe_div(max(item.close for item in future) - bar.low, bar.low, "support_pivot_low_non_positive")
    return _safe_div(bar.high - min(item.close for item in future), bar.high, "resistance_pivot_high_non_positive")


def _space_pivots(pivots: list[PivotPoint], min_spacing_bars: int) -> list[PivotPoint]:
    spaced: list[PivotPoint] = []
    for pivot in sorted(pivots, key=lambda item: item.index):
        if spaced and pivot.index - spaced[-1].index < min_spacing_bars:
            if pivot.reaction_pct > spaced[-1].reaction_pct:
                spaced[-1] = pivot
            continue
        spaced.append(pivot)
    return spaced


def _pivot_zones(
    *,
    reference: list[KlineBar],
    current: KlineBar,
    pivots: list[PivotPoint],
    side: str,
    atr: Decimal,
    params: dict[str, Any],
) -> list[PivotZone]:
    clusters = _cluster_pivots(pivots=pivots, atr=atr, params=params)
    zones: list[PivotZone] = []
    for cluster in clusters:
        zone = _zone_from_cluster(reference=reference, current=current, cluster=cluster, side=side, atr=atr, params=params)
        if zone is not None:
            zones.append(zone)
    return zones


def _cluster_pivots(*, pivots: list[PivotPoint], atr: Decimal, params: dict[str, Any]) -> list[list[PivotPoint]]:
    clusters: list[list[PivotPoint]] = []
    for pivot in sorted(pivots, key=lambda item: item.price):
        placed = False
        for cluster in clusters:
            core = Decimal(str(median([item.price for item in cluster])))
            if abs(pivot.price - core) / core <= _cluster_tolerance_pct(price=core, atr=atr, params=params):
                cluster.append(pivot)
                placed = True
                break
        if not placed:
            clusters.append([pivot])
    return clusters


def _zone_from_cluster(
    *,
    reference: list[KlineBar],
    current: KlineBar,
    cluster: list[PivotPoint],
    side: str,
    atr: Decimal,
    params: dict[str, Any],
) -> PivotZone | None:
    prices = [pivot.price for pivot in cluster]
    core = Decimal(str(median(prices)))
    lower, upper = _zone_bounds(prices=prices, core=core, atr=atr, params=params)
    width_pct = _safe_div(upper - lower, core, "pivot_zone_core_non_positive")
    if width_pct > _max_zone_width_pct(price=core, atr=atr, params=params):
        return None
    touch_count, avg_reaction, first_idx, last_idx = _touch_stats(
        reference=reference,
        side=side,
        lower=lower,
        upper=upper,
        atr=atr,
        params=params,
    )
    if touch_count < int(params.get("min_touch_count") or 1):
        return None
    strength = _zone_strength(
        touch_count=touch_count,
        avg_reaction=avg_reaction,
        last_touch_index=last_idx,
        reference_count=len(reference),
        width_pct=width_pct,
        max_width_pct=_max_zone_width_pct(price=core, atr=atr, params=params),
        params=params,
    )
    status = _zone_status(current=current, previous=reference, side=side, lower=lower, upper=upper, atr=atr, params=params)
    distance_pct, distance_atr = _zone_distance(current=current.close, side=side, lower=lower, upper=upper, atr=atr)
    return PivotZone(
        role=side,
        lower=lower,
        upper=upper,
        core=core,
        width_pct=width_pct,
        touch_count=touch_count,
        strength=strength,
        status=status,
        distance_pct=distance_pct,
        distance_atr=distance_atr,
        first_touch_index=first_idx,
        last_touch_index=last_idx,
    )


def _zone_bounds(*, prices: list[Decimal], core: Decimal, atr: Decimal, params: dict[str, Any]) -> tuple[Decimal, Decimal]:
    min_width_pct = _min_zone_width_pct(price=core, atr=atr, params=params)
    half_width_pct = min_width_pct / Decimal("2")
    lower = min(min(prices), core * (Decimal("1") - half_width_pct))
    upper = max(max(prices), core * (Decimal("1") + half_width_pct))
    return lower, upper


def _touch_stats(
    *,
    reference: list[KlineBar],
    side: str,
    lower: Decimal,
    upper: Decimal,
    atr: Decimal,
    params: dict[str, Any],
) -> tuple[int, Decimal, int, int]:
    reaction_window = _positive_int(params, "reaction_window")
    reactions: list[Decimal] = []
    first_idx = -1
    last_idx = -1
    for idx, bar in enumerate(reference):
        future = reference[idx + 1 : idx + 1 + reaction_window]
        if not future:
            continue
        price = bar.low if side == "support" else bar.high
        if not lower <= price <= upper:
            continue
        reaction = _pivot_reaction_pct(reference=reference, side=side, idx=idx, reaction_window=reaction_window)
        if reaction < _reaction_threshold_pct(price=price, atr=atr, params=params):
            continue
        reactions.append(reaction)
        if first_idx < 0:
            first_idx = idx
        last_idx = idx
    return len(reactions), _mean(reactions) if reactions else Decimal("0"), first_idx, last_idx


def _zone_status(
    *,
    current: KlineBar,
    previous: list[KlineBar],
    side: str,
    lower: Decimal,
    upper: Decimal,
    atr: Decimal,
    params: dict[str, Any],
) -> str:
    threshold = _confirm_threshold(price=current.close, atr=atr, params=params)
    closes = [bar.close for bar in [*previous, current]]
    confirm_bars = _positive_int(params, "confirm_bars")
    invalidation_bars = _positive_int(params, "invalidation_bars")
    if side == "support":
        if _all_last(closes, invalidation_bars, lambda close: close < lower * (Decimal("1") - threshold)):
            return "invalidated"
        if _all_last(closes, confirm_bars, lambda close: close < lower * (Decimal("1") - threshold)):
            return "breakdown_confirmed"
        if current.close < lower:
            return "breakdown_candidate"
        if current.low <= upper and current.close >= upper:
            return "hold"
        if current.low <= upper:
            return "testing"
        return "active"
    if _all_last(closes, invalidation_bars, lambda close: close > upper * (Decimal("1") + threshold)):
        return "invalidated"
    if _all_last(closes, confirm_bars, lambda close: close > upper * (Decimal("1") + threshold)):
        return "breakout_confirmed"
    if current.close > upper:
        return "breakout_candidate"
    if current.high >= lower and current.close <= lower:
        return "hold"
    if current.high >= lower:
        return "testing"
    return "active"


def _zone_distance(*, current: Decimal, side: str, lower: Decimal, upper: Decimal, atr: Decimal) -> tuple[Decimal, Decimal]:
    if lower <= current <= upper:
        return Decimal("0"), Decimal("0")
    if side == "support":
        raw = current - upper if current > upper else current - lower
    else:
        raw = lower - current if current < lower else upper - current
    return _safe_div(raw, current, "latest_close_non_positive"), _safe_div(raw, atr, "atr_non_positive")


def _zone_strength(
    *,
    touch_count: int,
    avg_reaction: Decimal,
    last_touch_index: int,
    reference_count: int,
    width_pct: Decimal,
    max_width_pct: Decimal,
    params: dict[str, Any],
) -> Decimal:
    if touch_count <= 0 or last_touch_index < 0 or reference_count <= 1:
        return Decimal("0")
    touch_score = min(Decimal(touch_count), Decimal("5")) / Decimal("5")
    recency_score = Decimal(last_touch_index) / Decimal(reference_count - 1)
    reaction_floor = Decimal(str(params.get("min_reaction_pct", "0.01")))
    reaction_score = min(_safe_div(avg_reaction, reaction_floor * Decimal("3"), "reaction_floor_non_positive"), Decimal("1"))
    width_penalty = min(_safe_div(width_pct, max_width_pct, "max_width_non_positive"), Decimal("1")) * Decimal("0.15")
    score = Decimal("0.45") * touch_score + Decimal("0.30") * recency_score + Decimal("0.25") * reaction_score - width_penalty
    return max(score, Decimal("0"))


def _all_last(values: list[Decimal], count: int, predicate: Callable[[Decimal], bool]) -> bool:
    if len(values) < count:
        return False
    return all(predicate(value) for value in values[-count:])


def _atr(bars: list[KlineBar], window: int) -> Decimal:
    target = _tail(bars, window + 1)
    true_ranges = [_true_range(target[idx], target[idx - 1].close) for idx in range(1, len(target))]
    atr = _mean(true_ranges)
    if atr <= 0:
        raise FeatureCalculationError("atr_non_positive", "ATR 必须大于 0")
    return atr


def _pivot_price(bar: KlineBar, side: str) -> Decimal:
    return bar.low if side == "support" else bar.high


def _reaction_threshold_pct(*, price: Decimal, atr: Decimal, params: dict[str, Any]) -> Decimal:
    atr_multiple = Decimal(str(params.get("min_reaction_atr_multiple", "1.5")))
    min_reaction_pct = Decimal(str(params.get("min_reaction_pct", "0.012")))
    return max(min_reaction_pct, _safe_div(atr * atr_multiple, price, "pivot_price_non_positive"))


def _cluster_tolerance_pct(*, price: Decimal, atr: Decimal, params: dict[str, Any]) -> Decimal:
    atr_multiple = Decimal(str(params.get("cluster_atr_multiple", "0.6")))
    min_pct = Decimal(str(params.get("cluster_pct", "0.005")))
    return max(min_pct, _safe_div(atr * atr_multiple, price, "pivot_price_non_positive"))


def _min_zone_width_pct(*, price: Decimal, atr: Decimal, params: dict[str, Any]) -> Decimal:
    atr_multiple = Decimal(str(params.get("min_zone_atr_multiple", "0.25")))
    min_pct = Decimal(str(params.get("min_zone_width_pct", "0.003")))
    return max(min_pct, _safe_div(atr * atr_multiple, price, "pivot_price_non_positive"))


def _max_zone_width_pct(*, price: Decimal, atr: Decimal, params: dict[str, Any]) -> Decimal:
    atr_multiple = Decimal(str(params.get("max_zone_atr_multiple", "1.2")))
    max_pct = Decimal(str(params.get("max_zone_width_pct", "0.02")))
    return min(max_pct, _safe_div(atr * atr_multiple, price, "pivot_price_non_positive"))


def _confirm_threshold(*, price: Decimal, atr: Decimal, params: dict[str, Any]) -> Decimal:
    atr_multiple = Decimal(str(params.get("confirm_atr_multiple", "0.5")))
    min_pct = Decimal(str(params.get("confirm_pct", "0.005")))
    return max(min_pct, _safe_div(atr * atr_multiple, price, "latest_close_non_positive"))


def _positive_int(params: dict[str, Any], field_name: str) -> int:
    try:
        value = int(params[field_name])
    except (KeyError, TypeError, ValueError) as exc:
        raise FeatureCalculationError("feature_params_invalid", f"参数 {field_name} 必须是正整数") from exc
    if value <= 0:
        raise FeatureCalculationError("feature_params_invalid", f"参数 {field_name} 必须是正整数")
    return value

