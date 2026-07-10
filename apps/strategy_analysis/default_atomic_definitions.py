"""StrategyAnalysis 模块：AtomicSignalDefinition 默认登记模板。

负责：提供受代码管理的默认原子信号定义清单，供 seed_atomic_signal_definitions 写入数据库。
不负责：计算 Feature、生成 AtomicSignalSet、聚合 DomainSignal、选择策略或生成订单动作。
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
from typing import Any, Iterable, Mapping

from apps.strategy_analysis.definition_hashes import normalize_feature_codes
from apps.strategy_analysis.models import AtomicSignalDirection, AtomicSignalOutputType


STRUCTURE_ZONE_FEATURE_CODES: tuple[str, ...] = (
    "structure_major_support_lower_1d_365",
    "structure_major_support_upper_1d_365",
    "structure_major_resistance_lower_1d_365",
    "structure_major_resistance_upper_1d_365",
    "structure_minor_support_lower_4h_120",
    "structure_minor_support_upper_4h_120",
    "structure_minor_resistance_lower_4h_120",
    "structure_minor_resistance_upper_4h_120",
)

HISTORICAL_MAJOR_STRUCTURE_FEATURE_CODES: tuple[str, ...] = (
    "structure_historical_major_zone_lower_1d_720",
    "structure_historical_major_zone_upper_1d_720",
    "structure_historical_major_zone_origin_type_1d_720",
    "structure_historical_major_zone_covered_bars_1d_720",
    "structure_historical_major_zone_test_count_1d_720",
    "structure_historical_major_zone_last_reaction_at_utc_1d_720",
    "structure_historical_major_zone_last_reaction_pct_1d_720",
    "structure_historical_major_zone_role_1d_720",
    "structure_historical_major_distance_to_zone_pct_1d_720",
)


def _pivot_structure_feature_codes(*, timeframe: str, window: int, side: str) -> tuple[str, ...]:
    suffix = f"{timeframe}_{window}"
    prefix = f"structure_pivot_{side}"
    return (
        f"{prefix}_lower_{suffix}",
        f"{prefix}_upper_{suffix}",
        f"{prefix}_core_{suffix}",
        f"{prefix}_strength_{suffix}",
        f"{prefix}_status_{suffix}",
        f"structure_pivot_distance_to_{side}_pct_{suffix}",
        f"structure_pivot_distance_to_{side}_atr_{suffix}",
    )


def _pivot_structure_context_feature_codes(*, timeframe: str, window: int) -> tuple[str, ...]:
    return (
        *_pivot_structure_feature_codes(timeframe=timeframe, window=window, side="support"),
        *_pivot_structure_feature_codes(timeframe=timeframe, window=window, side="resistance"),
    )


@dataclass(frozen=True)
class AtomicSignalDefinitionTemplate:
    signal_code: str
    display_name: str
    description: str
    category: str
    default_direction: str
    algorithm_name: str
    algorithm_version: str
    params: dict[str, Any]
    output_type: str = AtomicSignalOutputType.BOOLEAN
    is_required: bool = False

    @property
    def depends_on_feature_codes(self) -> tuple[str, ...]:
        return normalize_feature_codes(_feature_codes_from_params(self.params))


def _c(
    feature_code: str,
    operator: str,
    value: str | int | None = None,
    *,
    right_feature_code: str | None = None,
    right_multiplier: str | None = None,
) -> dict[str, Any]:
    condition: dict[str, Any] = {"feature_code": feature_code, "operator": operator}
    if value is not None:
        condition["value"] = str(value)
    if right_feature_code:
        condition["right_feature_code"] = right_feature_code
    if right_multiplier:
        condition["right_multiplier"] = str(right_multiplier)
    return condition


def _atomic(
    signal_code: str,
    *,
    category: str,
    direction: str,
    conditions: Iterable[Mapping[str, Any]],
    label_zh: str,
    aggregation: str = "all",
    output_type: str = AtomicSignalOutputType.BOOLEAN,
    extra_params: Mapping[str, Any] | None = None,
    algorithm_name: str = "atomic_condition",
    algorithm_version: str = "1.0.0",
    is_required: bool = False,
) -> AtomicSignalDefinitionTemplate:
    merged_extra_params = dict(extra_params or {})
    if category == "structure":
        json_payload = dict(merged_extra_params.pop("json_payload", {}) or {})
        json_payload.setdefault("structure_signal_family", "zone_snapshot")
        merged_extra_params = {
            "value_mode": "json",
            "json_payload": json_payload,
            "include_feature_values": list(STRUCTURE_ZONE_FEATURE_CODES),
            **merged_extra_params,
        }
        output_type = AtomicSignalOutputType.JSON
    params = {
        "conditions": [dict(condition) for condition in conditions],
        "aggregation": aggregation,
        "label_zh": label_zh,
        "evidence_type": f"{category}_atomic_condition",
    }
    if merged_extra_params:
        params.update(merged_extra_params)
    return AtomicSignalDefinitionTemplate(
        signal_code=signal_code,
        display_name=label_zh,
        description=f"{label_zh}。该定义只表达市场事实，不生成交易动作。",
        category=category,
        default_direction=direction,
        algorithm_name=algorithm_name,
        algorithm_version=algorithm_version,
        params=params,
        output_type=output_type,
        is_required=is_required,
    )


def _historical_structure_atomic(
    signal_code: str,
    *,
    conditions: Iterable[Mapping[str, Any]],
    label_zh: str,
    aggregation: str = "all",
    extra_params: Mapping[str, Any] | None = None,
) -> AtomicSignalDefinitionTemplate:
    payload = {
        "structure_signal_family": "historical_major_zone",
        "historical_structure_signal": signal_code,
    }
    merged_extra_params = {
        "include_feature_values": list(HISTORICAL_MAJOR_STRUCTURE_FEATURE_CODES),
        "json_payload": payload,
        **dict(extra_params or {}),
    }
    return _atomic(
        signal_code,
        category="structure",
        direction=AtomicSignalDirection.NEUTRAL,
        conditions=conditions,
        label_zh=label_zh,
        aggregation=aggregation,
        extra_params=merged_extra_params,
    )


def _pivot_structure_atomic(
    signal_code: str,
    *,
    level: str,
    timeframe: str,
    window: int,
    side: str,
    condition: str,
    label_zh: str,
    direction: str = AtomicSignalDirection.NEUTRAL,
    near_threshold: str | None = None,
) -> AtomicSignalDefinitionTemplate:
    include_feature_values = (
        _pivot_structure_context_feature_codes(timeframe=timeframe, window=window)
        if side == "both"
        else _pivot_structure_feature_codes(timeframe=timeframe, window=window, side=side)
    )
    params: dict[str, Any] = {
        "condition": condition,
        "level": level,
        "timeframe": timeframe,
        "window": window,
        "side": side,
        "label_zh": label_zh,
        "include_feature_values": list(include_feature_values),
        "evidence_type": "structure_pivot_atomic_condition",
    }
    if near_threshold is not None:
        params["near_threshold"] = str(near_threshold)
    return AtomicSignalDefinitionTemplate(
        signal_code=signal_code,
        display_name=label_zh,
        description=f"{label_zh}。该定义只表达拐点型支撑压力结构事实，不生成交易动作。",
        category="structure",
        default_direction=direction,
        algorithm_name="pivot_structure_atomic",
        algorithm_version="1.0.0",
        params=params,
        output_type=AtomicSignalOutputType.BOOLEAN,
    )


def _pivot_structure_group(*, level: str, timeframe: str, window: int, near_threshold: str) -> tuple[AtomicSignalDefinitionTemplate, ...]:
    prefix = f"structure_pivot_{level}"
    label_prefix = "1d 大" if level == "major" else "4h 小"
    return (
        _pivot_structure_atomic(f"{prefix}_support_valid", level=level, timeframe=timeframe, window=window, side="support", condition="valid", label_zh=f"{label_prefix}拐点支撑有效"),
        _pivot_structure_atomic(f"{prefix}_near_support", level=level, timeframe=timeframe, window=window, side="support", condition="near", label_zh=f"{label_prefix}靠近拐点支撑", near_threshold=near_threshold),
        _pivot_structure_atomic(f"{prefix}_support_testing", level=level, timeframe=timeframe, window=window, side="support", condition="testing", label_zh=f"{label_prefix}拐点支撑测试中"),
        _pivot_structure_atomic(f"{prefix}_support_holds", level=level, timeframe=timeframe, window=window, side="support", condition="holds", label_zh=f"{label_prefix}拐点支撑守住"),
        _pivot_structure_atomic(f"{prefix}_support_breakdown_candidate", level=level, timeframe=timeframe, window=window, side="support", condition="breakdown_candidate", label_zh=f"{label_prefix}拐点支撑跌破候选", direction=AtomicSignalDirection.BEARISH),
        _pivot_structure_atomic(f"{prefix}_support_breakdown_confirmed", level=level, timeframe=timeframe, window=window, side="support", condition="breakdown_confirmed", label_zh=f"{label_prefix}拐点支撑确认跌破", direction=AtomicSignalDirection.BEARISH),
        _pivot_structure_atomic(f"{prefix}_resistance_valid", level=level, timeframe=timeframe, window=window, side="resistance", condition="valid", label_zh=f"{label_prefix}拐点压力有效"),
        _pivot_structure_atomic(f"{prefix}_near_resistance", level=level, timeframe=timeframe, window=window, side="resistance", condition="near", label_zh=f"{label_prefix}靠近拐点压力", near_threshold=near_threshold),
        _pivot_structure_atomic(f"{prefix}_resistance_testing", level=level, timeframe=timeframe, window=window, side="resistance", condition="testing", label_zh=f"{label_prefix}拐点压力测试中"),
        _pivot_structure_atomic(f"{prefix}_resistance_holds", level=level, timeframe=timeframe, window=window, side="resistance", condition="holds", label_zh=f"{label_prefix}拐点压力压住"),
        _pivot_structure_atomic(f"{prefix}_resistance_breakout_candidate", level=level, timeframe=timeframe, window=window, side="resistance", condition="breakout_candidate", label_zh=f"{label_prefix}拐点压力突破候选", direction=AtomicSignalDirection.BULLISH),
        _pivot_structure_atomic(f"{prefix}_resistance_breakout_confirmed", level=level, timeframe=timeframe, window=window, side="resistance", condition="breakout_confirmed", label_zh=f"{label_prefix}拐点压力确认突破", direction=AtomicSignalDirection.BULLISH),
        _pivot_structure_atomic(f"{prefix}_between_support_resistance", level=level, timeframe=timeframe, window=window, side="both", condition="between", label_zh=f"{label_prefix}拐点支撑压力夹层"),
        _pivot_structure_atomic(f"{prefix}_unclear", level=level, timeframe=timeframe, window=window, side="both", condition="unclear", label_zh=f"{label_prefix}拐点结构不明确"),
    )


def _legacy_sma_atomic() -> AtomicSignalDefinitionTemplate:
    return AtomicSignalDefinitionTemplate(
        signal_code="sma_4h_20_above_sma_4h_60",
        display_name="4h SMA20 高于 4h SMA60",
        description="流程验证阶段默认趋势原子信号，只表达 SMA20 是否高于 SMA60。",
        category="trend",
        default_direction=AtomicSignalDirection.BULLISH,
        algorithm_name="feature_compare",
        algorithm_version="1.0.0",
        params={
            "left_feature_code": "sma_4h_20",
            "operator": "gt",
            "right_feature_code": "sma_4h_60",
        },
        output_type=AtomicSignalOutputType.BOOLEAN,
        is_required=True,
    )


def _risk(
    signal_code: str,
    *,
    risk_category: str,
    risk_direction: str,
    conditions: Iterable[Mapping[str, Any]],
    label_zh: str,
    severity_conditions: Iterable[Mapping[str, Any]] = (),
    include_feature_values: Iterable[str] = (),
    aggregation: str = "all",
) -> AtomicSignalDefinitionTemplate:
    extra_params: dict[str, Any] = {
        "value_mode": "json",
        "base_severity": "elevated",
        "high_severity": "high",
        "json_payload": {
            "risk_category": risk_category,
            "risk_direction": risk_direction,
            "risk_severity": "none",
        },
        "severity_conditions": [dict(condition) for condition in severity_conditions],
    }
    included = [str(code) for code in include_feature_values if str(code).strip()]
    if included:
        extra_params["include_feature_values"] = included
    return _atomic(
        signal_code,
        category="risk_state",
        direction=AtomicSignalDirection.NEUTRAL,
        conditions=conditions,
        label_zh=label_zh,
        aggregation=aggregation,
        output_type=AtomicSignalOutputType.JSON,
        extra_params=extra_params,
    )


def _market_context() -> tuple[AtomicSignalDefinitionTemplate, ...]:
    return (
        _atomic(
            "market_context_price_above_sma_1d_200",
            category="market_context",
            direction=AtomicSignalDirection.BULLISH,
            conditions=[_c("close_vs_sma_pct_1d_200", "gte", "0.02")],
            label_zh="当前价格明显高于 200 日均线",
        ),
        _atomic(
            "market_context_price_below_sma_1d_200",
            category="market_context",
            direction=AtomicSignalDirection.BEARISH,
            conditions=[_c("close_vs_sma_pct_1d_200", "lte", "-0.02")],
            label_zh="当前价格明显低于 200 日均线",
        ),
        _atomic(
            "market_context_price_above_sma_1d_365",
            category="market_context",
            direction=AtomicSignalDirection.BULLISH,
            conditions=[_c("close_vs_sma_pct_1d_365", "gte", "0.02")],
            label_zh="当前价格明显高于 365 日均线",
        ),
        _atomic(
            "market_context_price_below_sma_1d_365",
            category="market_context",
            direction=AtomicSignalDirection.BEARISH,
            conditions=[_c("close_vs_sma_pct_1d_365", "lte", "-0.02")],
            label_zh="当前价格明显低于 365 日均线",
        ),
        _atomic(
            "market_context_sma_1d_200_rising",
            category="market_context",
            direction=AtomicSignalDirection.BULLISH,
            conditions=[_c("slope_sma_1d_200", "gte", "0.003")],
            label_zh="200 日均线明显上行",
        ),
        _atomic(
            "market_context_sma_1d_200_falling",
            category="market_context",
            direction=AtomicSignalDirection.BEARISH,
            conditions=[_c("slope_sma_1d_200", "lte", "-0.003")],
            label_zh="200 日均线明显下行",
        ),
        _atomic(
            "market_context_sma_1d_365_rising",
            category="market_context",
            direction=AtomicSignalDirection.BULLISH,
            conditions=[_c("slope_sma_1d_365", "gte", "0.003")],
            label_zh="365 日均线明显上行",
        ),
        _atomic(
            "market_context_sma_1d_365_falling",
            category="market_context",
            direction=AtomicSignalDirection.BEARISH,
            conditions=[_c("slope_sma_1d_365", "lte", "-0.003")],
            label_zh="365 日均线明显下行",
        ),
        _atomic(
            "market_context_in_365d_high_zone",
            category="market_context",
            direction=AtomicSignalDirection.NEUTRAL,
            conditions=[_c("range_position_pct_1d_365", "gte", "0.75")],
            label_zh="当前位于最近 365 日区间高位",
        ),
        _atomic(
            "market_context_in_365d_low_zone",
            category="market_context",
            direction=AtomicSignalDirection.NEUTRAL,
            conditions=[_c("range_position_pct_1d_365", "lte", "0.25")],
            label_zh="当前位于最近 365 日区间低位",
        ),
        _atomic(
            "market_context_moderate_drawdown_from_365d_high",
            category="market_context",
            direction=AtomicSignalDirection.NEUTRAL,
            conditions=[
                _c("drawdown_from_high_pct_1d_365", "gte", "0.08"),
                _c("drawdown_from_high_pct_1d_365", "lt", "0.30"),
            ],
            label_zh="当前从 365 日高点出现中等回撤",
        ),
        _atomic(
            "market_context_deep_drawdown_from_365d_high",
            category="market_context",
            direction=AtomicSignalDirection.BEARISH,
            conditions=[_c("drawdown_from_high_pct_1d_365", "gte", "0.30")],
            label_zh="当前从 365 日高点出现深度回撤",
        ),
        _atomic(
            "market_context_material_rebound_from_drawdown_low",
            category="market_context",
            direction=AtomicSignalDirection.NEUTRAL,
            conditions=[_c("rebound_from_drawdown_low_pct_1d_365", "gte", "0.15")],
            label_zh="当前从回撤低点明显反弹",
        ),
        _atomic(
            "market_context_high_recovery_from_drawdown",
            category="market_context",
            direction=AtomicSignalDirection.NEUTRAL,
            conditions=[_c("recovery_ratio_from_drawdown_1d_365", "gte", "0.60")],
            label_zh="当前已收复前一段回撤的大部分空间",
        ),
        _atomic(
            "market_context_low_recovery_from_drawdown",
            category="market_context",
            direction=AtomicSignalDirection.NEUTRAL,
            conditions=[_c("recovery_ratio_from_drawdown_1d_365", "lte", "0.35")],
            label_zh="当前只收复前一段回撤的小部分空间",
        ),
        _atomic(
            "market_context_positive_365d_return",
            category="market_context",
            direction=AtomicSignalDirection.BULLISH,
            conditions=[_c("return_pct_1d_365", "gte", "0.10")],
            label_zh="最近 365 日收益明显为正",
        ),
        _atomic(
            "market_context_negative_365d_return",
            category="market_context",
            direction=AtomicSignalDirection.BEARISH,
            conditions=[_c("return_pct_1d_365", "lte", "-0.10")],
            label_zh="最近 365 日收益明显为负",
        ),
    )


def _trend() -> tuple[AtomicSignalDefinitionTemplate, ...]:
    return (
        _legacy_sma_atomic(),
        _atomic(
            "trend_1d_ma_bullish_alignment",
            category="trend",
            direction=AtomicSignalDirection.BULLISH,
            conditions=[_c("sma_spread_pct_1d_20_60", "gte", "0.003"), _c("sma_spread_pct_1d_60_120", "gte", "0.003")],
            label_zh="1d 均线呈偏多排列",
        ),
        _atomic(
            "trend_1d_ma_bearish_alignment",
            category="trend",
            direction=AtomicSignalDirection.BEARISH,
            conditions=[_c("sma_spread_pct_1d_20_60", "lte", "-0.003"), _c("sma_spread_pct_1d_60_120", "lte", "-0.003")],
            label_zh="1d 均线呈偏空排列",
        ),
        _atomic(
            "trend_1d_slow_slope_rising",
            category="trend",
            direction=AtomicSignalDirection.BULLISH,
            conditions=[_c("slope_sma_1d_120_lag10", "gte", "0.003")],
            label_zh="1d 120 日均线明显上行",
        ),
        _atomic(
            "trend_1d_slow_slope_falling",
            category="trend",
            direction=AtomicSignalDirection.BEARISH,
            conditions=[_c("slope_sma_1d_120_lag10", "lte", "-0.003")],
            label_zh="1d 120 日均线明显下行",
        ),
        _atomic(
            "trend_1d_price_above_medium_ma",
            category="trend",
            direction=AtomicSignalDirection.BULLISH,
            conditions=[_c("close_vs_sma_pct_1d_60", "gte", "0.005")],
            label_zh="1d 收盘价明显位于 60 日均线上方",
        ),
        _atomic(
            "trend_1d_price_below_medium_ma",
            category="trend",
            direction=AtomicSignalDirection.BEARISH,
            conditions=[_c("close_vs_sma_pct_1d_60", "lte", "-0.005")],
            label_zh="1d 收盘价明显位于 60 日均线下方",
        ),
        _atomic(
            "trend_1d_block_structure_rising",
            category="trend",
            direction=AtomicSignalDirection.BULLISH,
            conditions=[_c("higher_high_count_1d_60_block20", "gte", "2"), _c("higher_low_count_1d_60_block20", "gte", "2")],
            label_zh="1d 分块高低点连续抬高",
        ),
        _atomic(
            "trend_1d_block_structure_falling",
            category="trend",
            direction=AtomicSignalDirection.BEARISH,
            conditions=[_c("lower_high_count_1d_60_block20", "gte", "2"), _c("lower_low_count_1d_60_block20", "gte", "2")],
            label_zh="1d 分块高低点连续降低",
        ),
        _atomic(
            "trend_4h_ma_bullish_alignment",
            category="trend",
            direction=AtomicSignalDirection.BULLISH,
            conditions=[_c("sma_spread_pct_4h_20_60", "gte", "0.003"), _c("sma_spread_pct_4h_60_120", "gte", "0.003")],
            label_zh="4h 均线呈偏多排列",
        ),
        _atomic(
            "trend_4h_ma_bearish_alignment",
            category="trend",
            direction=AtomicSignalDirection.BEARISH,
            conditions=[_c("sma_spread_pct_4h_20_60", "lte", "-0.003"), _c("sma_spread_pct_4h_60_120", "lte", "-0.003")],
            label_zh="4h 均线呈偏空排列",
        ),
        _atomic(
            "trend_4h_medium_slope_rising",
            category="trend",
            direction=AtomicSignalDirection.BULLISH,
            conditions=[_c("slope_sma_4h_60_lag12", "gte", "0.003")],
            label_zh="4h 60 均线明显上行",
        ),
        _atomic(
            "trend_4h_medium_slope_falling",
            category="trend",
            direction=AtomicSignalDirection.BEARISH,
            conditions=[_c("slope_sma_4h_60_lag12", "lte", "-0.003")],
            label_zh="4h 60 均线明显下行",
        ),
        _atomic(
            "trend_4h_price_above_medium_ma",
            category="trend",
            direction=AtomicSignalDirection.BULLISH,
            conditions=[_c("close_vs_sma_pct_4h_60", "gte", "0.005")],
            label_zh="4h 收盘价明显位于 60 根 4h 均线上方",
        ),
        _atomic(
            "trend_4h_price_below_medium_ma",
            category="trend",
            direction=AtomicSignalDirection.BEARISH,
            conditions=[_c("close_vs_sma_pct_4h_60", "lte", "-0.005")],
            label_zh="4h 收盘价明显位于 60 根 4h 均线下方",
        ),
        _atomic(
            "trend_4h_block_structure_rising",
            category="trend",
            direction=AtomicSignalDirection.BULLISH,
            conditions=[_c("higher_high_count_4h_60_block20", "gte", "2"), _c("higher_low_count_4h_60_block20", "gte", "2")],
            label_zh="4h 分块高低点连续抬高",
        ),
        _atomic(
            "trend_4h_block_structure_falling",
            category="trend",
            direction=AtomicSignalDirection.BEARISH,
            conditions=[_c("lower_high_count_4h_60_block20", "gte", "2"), _c("lower_low_count_4h_60_block20", "gte", "2")],
            label_zh="4h 分块高低点连续降低",
        ),
    )


def _momentum() -> tuple[AtomicSignalDefinitionTemplate, ...]:
    return (
        _atomic("momentum_1d_bullish_push_exists", category="momentum", direction=AtomicSignalDirection.BULLISH, conditions=[_c("return_pct_1d_7", "gte", "0.03")], label_zh="1d 存在明显多头推进"),
        _atomic("momentum_1d_bearish_push_exists", category="momentum", direction=AtomicSignalDirection.BEARISH, conditions=[_c("return_pct_1d_7", "lte", "-0.03")], label_zh="1d 存在明显空头推进"),
        _atomic("momentum_1d_bullish_push_strengthening", category="momentum", direction=AtomicSignalDirection.BULLISH, conditions=[_c("return_pct_1d_7", "gte", "0.03"), _c("return_delta_pct_1d_7", "gte", "0.015")], label_zh="1d 多头推进增强"),
        _atomic("momentum_1d_bearish_push_strengthening", category="momentum", direction=AtomicSignalDirection.BEARISH, conditions=[_c("return_pct_1d_7", "lte", "-0.03"), _c("return_delta_pct_1d_7", "lte", "-0.015")], label_zh="1d 空头推进增强"),
        _atomic("momentum_1d_bullish_push_exhausting", category="momentum", direction=AtomicSignalDirection.NEUTRAL, conditions=[_c("return_pct_1d_7", "gte", "0.03"), _c("return_delta_pct_1d_7", "lte", "-0.015")], label_zh="1d 多头推进衰竭"),
        _atomic("momentum_1d_bearish_push_exhausting", category="momentum", direction=AtomicSignalDirection.NEUTRAL, conditions=[_c("return_pct_1d_7", "lte", "-0.03"), _c("return_delta_pct_1d_7", "gte", "0.015")], label_zh="1d 空头推进衰竭"),
        _atomic("momentum_1d_bullish_continuity_good", category="momentum", direction=AtomicSignalDirection.BULLISH, conditions=[_c("up_bar_ratio_1d_7", "gte", "0.60"), _c("consecutive_up_count_1d_7", "gte", "3")], label_zh="1d 上涨连续性较好", aggregation="any"),
        _atomic("momentum_1d_bearish_continuity_good", category="momentum", direction=AtomicSignalDirection.BEARISH, conditions=[_c("down_bar_ratio_1d_7", "gte", "0.60"), _c("consecutive_down_count_1d_7", "gte", "3")], label_zh="1d 下跌连续性较好", aggregation="any"),
        _atomic("momentum_1d_movement_efficiency_high", category="momentum", direction=AtomicSignalDirection.NEUTRAL, conditions=[_c("movement_efficiency_1d_7", "gte", "0.55")], label_zh="1d 推进较顺畅"),
        _atomic("momentum_1d_movement_efficiency_low", category="momentum", direction=AtomicSignalDirection.NEUTRAL, conditions=[_c("movement_efficiency_1d_7", "lte", "0.30")], label_zh="1d 推进拉扯严重"),
        _atomic("momentum_1d_close_strength_bullish", category="momentum", direction=AtomicSignalDirection.BULLISH, conditions=[_c("close_location_avg_pct_1d_3", "gte", "0.65")], label_zh="1d 收盘偏强"),
        _atomic("momentum_1d_close_strength_bearish", category="momentum", direction=AtomicSignalDirection.BEARISH, conditions=[_c("close_location_avg_pct_1d_3", "lte", "0.35")], label_zh="1d 收盘偏弱"),
        _atomic("momentum_4h_bullish_push_exists", category="momentum", direction=AtomicSignalDirection.BULLISH, conditions=[_c("return_pct_4h_24", "gte", "0.02")], label_zh="4h 存在明显多头推进"),
        _atomic("momentum_4h_bearish_push_exists", category="momentum", direction=AtomicSignalDirection.BEARISH, conditions=[_c("return_pct_4h_24", "lte", "-0.02")], label_zh="4h 存在明显空头推进"),
        _atomic("momentum_4h_bullish_push_strengthening", category="momentum", direction=AtomicSignalDirection.BULLISH, conditions=[_c("return_pct_4h_24", "gte", "0.02"), _c("return_delta_pct_4h_24", "gte", "0.01")], label_zh="4h 多头推进增强"),
        _atomic("momentum_4h_bearish_push_strengthening", category="momentum", direction=AtomicSignalDirection.BEARISH, conditions=[_c("return_pct_4h_24", "lte", "-0.02"), _c("return_delta_pct_4h_24", "lte", "-0.01")], label_zh="4h 空头推进增强"),
        _atomic("momentum_4h_bullish_push_exhausting", category="momentum", direction=AtomicSignalDirection.NEUTRAL, conditions=[_c("return_pct_4h_24", "gte", "0.02"), _c("return_delta_pct_4h_24", "lte", "-0.01")], label_zh="4h 多头推进衰竭"),
        _atomic("momentum_4h_bearish_push_exhausting", category="momentum", direction=AtomicSignalDirection.NEUTRAL, conditions=[_c("return_pct_4h_24", "lte", "-0.02"), _c("return_delta_pct_4h_24", "gte", "0.01")], label_zh="4h 空头推进衰竭"),
        _atomic("momentum_4h_bullish_continuity_good", category="momentum", direction=AtomicSignalDirection.BULLISH, conditions=[_c("up_bar_ratio_4h_24", "gte", "0.60"), _c("consecutive_up_count_4h_24", "gte", "4")], label_zh="4h 上涨连续性较好", aggregation="any"),
        _atomic("momentum_4h_bearish_continuity_good", category="momentum", direction=AtomicSignalDirection.BEARISH, conditions=[_c("down_bar_ratio_4h_24", "gte", "0.60"), _c("consecutive_down_count_4h_24", "gte", "4")], label_zh="4h 下跌连续性较好", aggregation="any"),
        _atomic("momentum_4h_movement_efficiency_high", category="momentum", direction=AtomicSignalDirection.NEUTRAL, conditions=[_c("movement_efficiency_4h_24", "gte", "0.55")], label_zh="4h 推进较顺畅"),
        _atomic("momentum_4h_movement_efficiency_low", category="momentum", direction=AtomicSignalDirection.NEUTRAL, conditions=[_c("movement_efficiency_4h_24", "lte", "0.30")], label_zh="4h 推进拉扯严重"),
        _atomic("momentum_4h_close_strength_bullish", category="momentum", direction=AtomicSignalDirection.BULLISH, conditions=[_c("close_location_avg_pct_4h_12", "gte", "0.65")], label_zh="4h 收盘偏强"),
        _atomic("momentum_4h_close_strength_bearish", category="momentum", direction=AtomicSignalDirection.BEARISH, conditions=[_c("close_location_avg_pct_4h_12", "lte", "0.35")], label_zh="4h 收盘偏弱"),
    )


def _volatility() -> tuple[AtomicSignalDefinitionTemplate, ...]:
    return (
        _atomic("volatility_1d_atr_low_percentile", category="volatility", direction=AtomicSignalDirection.NEUTRAL, conditions=[_c("atr_percentile_1d_120", "lte", "0.20")], label_zh="1d ATR 处于低分位"),
        _atomic("volatility_1d_atr_high_percentile", category="volatility", direction=AtomicSignalDirection.NEUTRAL, conditions=[_c("atr_percentile_1d_120", "gte", "0.80")], label_zh="1d ATR 处于高分位"),
        _atomic("volatility_1d_atr_extreme_percentile", category="volatility", direction=AtomicSignalDirection.NEUTRAL, conditions=[_c("atr_percentile_1d_120", "gte", "0.95")], label_zh="1d ATR 处于极高分位"),
        _atomic("volatility_4h_atr_low_percentile", category="volatility", direction=AtomicSignalDirection.NEUTRAL, conditions=[_c("atr_percentile_4h_120", "lte", "0.20")], label_zh="4h ATR 处于低分位"),
        _atomic("volatility_4h_atr_high_percentile", category="volatility", direction=AtomicSignalDirection.NEUTRAL, conditions=[_c("atr_percentile_4h_120", "gte", "0.80")], label_zh="4h ATR 处于高分位"),
        _atomic("volatility_4h_atr_extreme_percentile", category="volatility", direction=AtomicSignalDirection.NEUTRAL, conditions=[_c("atr_percentile_4h_120", "gte", "0.95")], label_zh="4h ATR 处于极高分位"),
        _atomic("volatility_4h_realized_vol_low_percentile", category="volatility", direction=AtomicSignalDirection.NEUTRAL, conditions=[_c("realized_vol_percentile_4h_120", "lte", "0.20")], label_zh="4h 已实现波动率处于低分位"),
        _atomic("volatility_4h_realized_vol_high_percentile", category="volatility", direction=AtomicSignalDirection.NEUTRAL, conditions=[_c("realized_vol_percentile_4h_120", "gte", "0.80")], label_zh="4h 已实现波动率处于高分位"),
        _atomic("volatility_4h_compression", category="volatility", direction=AtomicSignalDirection.NEUTRAL, conditions=[_c("volatility_ratio_4h_20_to_60", "lte", "0.70")], label_zh="4h 波动存在压缩"),
        _atomic("volatility_4h_expansion", category="volatility", direction=AtomicSignalDirection.NEUTRAL, conditions=[_c("volatility_ratio_4h_20_to_60", "gte", "1.30")], label_zh="4h 波动存在扩张"),
        _atomic("volatility_1d_latest_candle_range_large", category="volatility", direction=AtomicSignalDirection.NEUTRAL, conditions=[_c("candle_range_pct_1d_latest", "gte", right_feature_code="atr_pct_1d_14", right_multiplier="2.00")], label_zh="最新 1d K 线振幅明显大于常态"),
        _atomic("volatility_4h_latest_candle_range_large", category="volatility", direction=AtomicSignalDirection.NEUTRAL, conditions=[_c("candle_range_pct_4h_latest", "gte", right_feature_code="atr_pct_4h_14", right_multiplier="2.00")], label_zh="最新 4h K 线振幅明显大于常态"),
        _atomic("volatility_4h_latest_large_body", category="volatility", direction=AtomicSignalDirection.NEUTRAL, conditions=[_c("candle_body_ratio_4h_latest", "gte", "0.70"), _c("candle_range_pct_4h_latest", "gte", right_feature_code="atr_pct_4h_14")], label_zh="最新 4h K 线为实体主导的大波动 K 线"),
        _atomic("volatility_4h_latest_upper_shadow_dominant", category="volatility", direction=AtomicSignalDirection.NEUTRAL, conditions=[_c("upper_shadow_ratio_4h_latest", "gte", "0.60")], label_zh="最新 4h K 线上影线主导"),
        _atomic("volatility_4h_latest_lower_shadow_dominant", category="volatility", direction=AtomicSignalDirection.NEUTRAL, conditions=[_c("lower_shadow_ratio_4h_latest", "gte", "0.60")], label_zh="最新 4h K 线下影线主导"),
        _atomic("volatility_1d_range_wide", category="volatility", direction=AtomicSignalDirection.NEUTRAL, conditions=[_c("range_width_pct_1d_60", "gte", "0.25")], label_zh="1d 行情高低区间偏宽"),
        _atomic("volatility_1d_range_narrow", category="volatility", direction=AtomicSignalDirection.NEUTRAL, conditions=[_c("range_width_pct_1d_60", "lte", "0.10")], label_zh="1d 行情高低区间偏窄"),
        _atomic("volatility_4h_range_wide", category="volatility", direction=AtomicSignalDirection.NEUTRAL, conditions=[_c("range_width_pct_4h_120", "gte", "0.12")], label_zh="4h 行情高低区间偏宽"),
        _atomic("volatility_4h_range_narrow", category="volatility", direction=AtomicSignalDirection.NEUTRAL, conditions=[_c("range_width_pct_4h_120", "lte", "0.04")], label_zh="4h 行情高低区间偏窄"),
    )


def _structure() -> tuple[AtomicSignalDefinitionTemplate, ...]:
    major_support = "structure_major_support_upper_1d_365"
    major_resistance = "structure_major_resistance_lower_1d_365"
    minor_support = "structure_minor_support_upper_4h_120"
    minor_resistance = "structure_minor_resistance_lower_4h_120"
    return (
        _atomic("structure_major_near_support", category="structure", direction=AtomicSignalDirection.NEUTRAL, conditions=[_c(major_support, "is_not_null"), _c("structure_major_distance_to_support_upper_pct_1d_365", "gte", "0"), _c("structure_major_distance_to_support_upper_pct_1d_365", "lte", "0.025")], label_zh="当前靠近 1d 大支撑区"),
        _atomic("structure_major_near_resistance", category="structure", direction=AtomicSignalDirection.NEUTRAL, conditions=[_c(major_resistance, "is_not_null"), _c("structure_major_distance_to_resistance_lower_pct_1d_365", "gte", "0"), _c("structure_major_distance_to_resistance_lower_pct_1d_365", "lte", "0.025")], label_zh="当前靠近 1d 大压力区"),
        _atomic("structure_major_range_middle", category="structure", direction=AtomicSignalDirection.NEUTRAL, conditions=[_c("structure_major_range_position_pct_1d_365", "gt", "0.25"), _c("structure_major_range_position_pct_1d_365", "lt", "0.75")], label_zh="当前处于 1d 大区间中部"),
        _atomic("structure_major_lower_half", category="structure", direction=AtomicSignalDirection.NEUTRAL, conditions=[_c("structure_major_range_position_pct_1d_365", "lte", "0.50")], label_zh="当前处于 1d 大区间下半部"),
        _atomic("structure_major_upper_half", category="structure", direction=AtomicSignalDirection.NEUTRAL, conditions=[_c("structure_major_range_position_pct_1d_365", "gte", "0.50")], label_zh="当前处于 1d 大区间上半部"),
        _atomic("structure_minor_near_support", category="structure", direction=AtomicSignalDirection.NEUTRAL, conditions=[_c(minor_support, "is_not_null"), _c("structure_minor_distance_to_support_upper_pct_4h_120", "gte", "0"), _c("structure_minor_distance_to_support_upper_pct_4h_120", "lte", "0.010")], label_zh="当前靠近 4h 小支撑区"),
        _atomic("structure_minor_near_resistance", category="structure", direction=AtomicSignalDirection.NEUTRAL, conditions=[_c(minor_resistance, "is_not_null"), _c("structure_minor_distance_to_resistance_lower_pct_4h_120", "gte", "0"), _c("structure_minor_distance_to_resistance_lower_pct_4h_120", "lte", "0.010")], label_zh="当前靠近 4h 小压力区"),
        _atomic("structure_minor_range_middle", category="structure", direction=AtomicSignalDirection.NEUTRAL, conditions=[_c("structure_minor_range_position_pct_4h_120", "gt", "0.25"), _c("structure_minor_range_position_pct_4h_120", "lt", "0.75")], label_zh="当前处于 4h 小区间中部"),
        _atomic("structure_minor_lower_half", category="structure", direction=AtomicSignalDirection.NEUTRAL, conditions=[_c("structure_minor_range_position_pct_4h_120", "lte", "0.50")], label_zh="当前处于 4h 小区间下半部"),
        _atomic("structure_minor_upper_half", category="structure", direction=AtomicSignalDirection.NEUTRAL, conditions=[_c("structure_minor_range_position_pct_4h_120", "gte", "0.50")], label_zh="当前处于 4h 小区间上半部"),
        _atomic("structure_major_support_valid", category="structure", direction=AtomicSignalDirection.NEUTRAL, conditions=[_c("structure_major_support_lower_1d_365", "is_not_null"), _c(major_support, "is_not_null"), _c("structure_major_support_touch_count_1d_365", "gte", "2"), _c("structure_major_support_score_1d_365", "gt", "0")], label_zh="1d 大支撑区具备基本有效性"),
        _atomic("structure_major_resistance_valid", category="structure", direction=AtomicSignalDirection.NEUTRAL, conditions=[_c(major_resistance, "is_not_null"), _c("structure_major_resistance_upper_1d_365", "is_not_null"), _c("structure_major_resistance_touch_count_1d_365", "gte", "2"), _c("structure_major_resistance_score_1d_365", "gt", "0")], label_zh="1d 大压力区具备基本有效性"),
        _atomic("structure_minor_support_valid", category="structure", direction=AtomicSignalDirection.NEUTRAL, conditions=[_c("structure_minor_support_lower_4h_120", "is_not_null"), _c(minor_support, "is_not_null"), _c("structure_minor_support_touch_count_4h_120", "gte", "2"), _c("structure_minor_support_score_4h_120", "gt", "0")], label_zh="4h 小支撑区具备基本有效性"),
        _atomic("structure_minor_resistance_valid", category="structure", direction=AtomicSignalDirection.NEUTRAL, conditions=[_c(minor_resistance, "is_not_null"), _c("structure_minor_resistance_upper_4h_120", "is_not_null"), _c("structure_minor_resistance_touch_count_4h_120", "gte", "2"), _c("structure_minor_resistance_score_4h_120", "gt", "0")], label_zh="4h 小压力区具备基本有效性"),
        _atomic("structure_major_range_valid", category="structure", direction=AtomicSignalDirection.NEUTRAL, conditions=[_c("structure_major_support_lower_1d_365", "is_not_null"), _c(major_support, "is_not_null"), _c(major_resistance, "is_not_null"), _c("structure_major_resistance_upper_1d_365", "is_not_null"), _c("structure_major_support_touch_count_1d_365", "gte", "2"), _c("structure_major_resistance_touch_count_1d_365", "gte", "2"), _c("structure_major_support_score_1d_365", "gt", "0"), _c("structure_major_resistance_score_1d_365", "gt", "0"), _c(major_support, "lt", right_feature_code=major_resistance), _c("structure_major_range_width_pct_1d_365", "gt", "0"), _c("structure_major_range_width_pct_1d_365", "lte", "0.45")], label_zh="1d 大支撑压力区间具备基本可解释性"),
        _atomic("structure_minor_range_valid", category="structure", direction=AtomicSignalDirection.NEUTRAL, conditions=[_c("structure_minor_support_lower_4h_120", "is_not_null"), _c(minor_support, "is_not_null"), _c(minor_resistance, "is_not_null"), _c("structure_minor_resistance_upper_4h_120", "is_not_null"), _c("structure_minor_support_touch_count_4h_120", "gte", "2"), _c("structure_minor_resistance_touch_count_4h_120", "gte", "2"), _c("structure_minor_support_score_4h_120", "gt", "0"), _c("structure_minor_resistance_score_4h_120", "gt", "0"), _c(minor_support, "lt", right_feature_code=minor_resistance), _c("structure_minor_range_width_pct_4h_120", "gt", "0"), _c("structure_minor_range_width_pct_4h_120", "lte", "0.20")], label_zh="4h 小支撑压力区间具备基本可解释性"),
        _atomic("structure_major_breakout_up", category="structure", direction=AtomicSignalDirection.BULLISH, conditions=[_c("structure_major_breakout_above_resistance_pct_1d_365", "gte", "0.008")], label_zh="当前收盘突破 1d 大压力区"),
        _atomic("structure_major_breakdown_down", category="structure", direction=AtomicSignalDirection.BEARISH, conditions=[_c("structure_major_breakdown_below_support_pct_1d_365", "gte", "0.008")], label_zh="当前收盘跌破 1d 大支撑区"),
        _atomic("structure_minor_breakout_up", category="structure", direction=AtomicSignalDirection.BULLISH, conditions=[_c("structure_minor_breakout_above_resistance_pct_4h_120", "gte", "0.004")], label_zh="当前收盘突破 4h 小压力区"),
        _atomic("structure_minor_breakdown_down", category="structure", direction=AtomicSignalDirection.BEARISH, conditions=[_c("structure_minor_breakdown_below_support_pct_4h_120", "gte", "0.004")], label_zh="当前收盘跌破 4h 小支撑区"),
        _atomic("structure_major_support_holds", category="structure", direction=AtomicSignalDirection.NEUTRAL, conditions=[_c("structure_major_support_lower_1d_365", "is_not_null"), _c(major_support, "is_not_null"), _c("structure_major_support_score_1d_365", "gt", "0"), _c("structure_major_distance_to_support_upper_pct_1d_365", "lte", "0.035"), _c("structure_major_breakdown_below_support_pct_1d_365", "lte", "0")], label_zh="1d 大支撑仍然有效"),
        _atomic("structure_major_resistance_holds", category="structure", direction=AtomicSignalDirection.NEUTRAL, conditions=[_c(major_resistance, "is_not_null"), _c("structure_major_resistance_upper_1d_365", "is_not_null"), _c("structure_major_resistance_score_1d_365", "gt", "0"), _c("structure_major_distance_to_resistance_lower_pct_1d_365", "lte", "0.035"), _c("structure_major_breakout_above_resistance_pct_1d_365", "lte", "0")], label_zh="1d 大压力仍然有效"),
        _atomic("structure_minor_support_holds", category="structure", direction=AtomicSignalDirection.NEUTRAL, conditions=[_c("structure_minor_support_lower_4h_120", "is_not_null"), _c(minor_support, "is_not_null"), _c("structure_minor_support_score_4h_120", "gt", "0"), _c("structure_minor_distance_to_support_upper_pct_4h_120", "lte", "0.015"), _c("structure_minor_breakdown_below_support_pct_4h_120", "lte", "0")], label_zh="4h 小支撑仍然有效"),
        _atomic("structure_minor_resistance_holds", category="structure", direction=AtomicSignalDirection.NEUTRAL, conditions=[_c(minor_resistance, "is_not_null"), _c("structure_minor_resistance_upper_4h_120", "is_not_null"), _c("structure_minor_resistance_score_4h_120", "gt", "0"), _c("structure_minor_distance_to_resistance_lower_pct_4h_120", "lte", "0.015"), _c("structure_minor_breakout_above_resistance_pct_4h_120", "lte", "0")], label_zh="4h 小压力仍然有效"),
        _atomic("structure_major_support_breakdown_candidate", category="structure", direction=AtomicSignalDirection.BEARISH, conditions=[_c("structure_major_breakdown_below_support_pct_1d_365", "gte", "0.008")], label_zh="1d 大支撑跌破候选"),
        _atomic("structure_major_support_breakdown_confirmed", category="structure", direction=AtomicSignalDirection.BEARISH, conditions=[_c("structure_major_breakdown_below_support_pct_1d_365", "gte", "0.020")], label_zh="1d 大支撑跌破幅度达到确认阈值"),
        _atomic("structure_minor_support_breakdown_candidate", category="structure", direction=AtomicSignalDirection.BEARISH, conditions=[_c("structure_minor_breakdown_below_support_pct_4h_120", "gte", "0.004")], label_zh="4h 小支撑跌破候选"),
        _atomic("structure_minor_support_breakdown_confirmed", category="structure", direction=AtomicSignalDirection.BEARISH, conditions=[_c("structure_minor_breakdown_below_support_pct_4h_120", "gte", "0.010")], label_zh="4h 小支撑跌破幅度达到确认阈值"),
        _atomic("structure_major_resistance_breakout_candidate", category="structure", direction=AtomicSignalDirection.BULLISH, conditions=[_c("structure_major_breakout_above_resistance_pct_1d_365", "gte", "0.008")], label_zh="1d 大压力突破候选"),
        _atomic("structure_major_resistance_breakout_confirmed", category="structure", direction=AtomicSignalDirection.BULLISH, conditions=[_c("structure_major_breakout_above_resistance_pct_1d_365", "gte", "0.020")], label_zh="1d 大压力突破幅度达到确认阈值"),
        _atomic("structure_minor_resistance_breakout_candidate", category="structure", direction=AtomicSignalDirection.BULLISH, conditions=[_c("structure_minor_breakout_above_resistance_pct_4h_120", "gte", "0.004")], label_zh="4h 小压力突破候选"),
        _atomic("structure_minor_resistance_breakout_confirmed", category="structure", direction=AtomicSignalDirection.BULLISH, conditions=[_c("structure_minor_breakout_above_resistance_pct_4h_120", "gte", "0.010")], label_zh="4h 小压力突破幅度达到确认阈值"),
        _atomic("structure_major_unclear", category="structure", direction=AtomicSignalDirection.NEUTRAL, conditions=[_c("structure_major_support_lower_1d_365", "is_null"), _c(major_support, "is_null"), _c(major_resistance, "is_null"), _c("structure_major_resistance_upper_1d_365", "is_null"), _c("structure_major_range_width_pct_1d_365", "is_null"), _c(major_support, "gte", right_feature_code=major_resistance)], label_zh="1d 大结构缺少可用支撑或压力", aggregation="any"),
        _atomic("structure_minor_unclear", category="structure", direction=AtomicSignalDirection.NEUTRAL, conditions=[_c("structure_minor_support_lower_4h_120", "is_null"), _c(minor_support, "is_null"), _c(minor_resistance, "is_null"), _c("structure_minor_resistance_upper_4h_120", "is_null"), _c("structure_minor_range_width_pct_4h_120", "is_null"), _c(minor_support, "gte", right_feature_code=minor_resistance)], label_zh="4h 小结构缺少可用支撑或压力", aggregation="any"),
        *_pivot_structure_group(level="major", timeframe="1d", window=365, near_threshold="0.025"),
        *_pivot_structure_group(level="minor", timeframe="4h", window=120, near_threshold="0.010"),
        _historical_structure_atomic(
            "structure_historical_major_zone_valid",
            conditions=[
                _c("structure_historical_major_zone_lower_1d_720", "is_not_null"),
                _c("structure_historical_major_zone_upper_1d_720", "is_not_null"),
                _c("structure_historical_major_zone_test_count_1d_720", "gte", "2"),
                _c("structure_historical_major_zone_covered_bars_1d_720", "gte", "60"),
                _c("structure_historical_major_zone_last_reaction_pct_1d_720", "gte", "0.03"),
            ],
            label_zh="1d 历史大结构区具备基本解释力",
        ),
        _historical_structure_atomic(
            "structure_historical_major_near_zone",
            conditions=[
                _c("structure_historical_major_zone_lower_1d_720", "is_not_null"),
                _c("structure_historical_major_zone_upper_1d_720", "is_not_null"),
                _c("structure_historical_major_distance_to_zone_pct_1d_720", "is_not_null"),
                _c("structure_historical_major_distance_to_zone_pct_1d_720", "lte", "0.03"),
            ],
            label_zh="当前价格接近 1d 历史大结构区",
        ),
        _historical_structure_atomic(
            "structure_historical_major_support_like",
            conditions=[
                _c("structure_historical_major_zone_lower_1d_720", "is_not_null"),
                _c("structure_historical_major_zone_upper_1d_720", "is_not_null"),
                _c("structure_historical_major_zone_covered_bars_1d_720", "gte", "60"),
                _c("structure_historical_major_zone_role_1d_720", "text_eq", "support_like"),
                _c("structure_historical_major_zone_test_count_1d_720", "gte", "2"),
                _c("structure_historical_major_zone_last_reaction_pct_1d_720", "gte", "0.03"),
            ],
            label_zh="1d 历史大结构区当前更像支撑",
        ),
        _historical_structure_atomic(
            "structure_historical_major_resistance_like",
            conditions=[
                _c("structure_historical_major_zone_lower_1d_720", "is_not_null"),
                _c("structure_historical_major_zone_upper_1d_720", "is_not_null"),
                _c("structure_historical_major_zone_covered_bars_1d_720", "gte", "60"),
                _c("structure_historical_major_zone_role_1d_720", "text_eq", "resistance_like"),
                _c("structure_historical_major_zone_test_count_1d_720", "gte", "2"),
                _c("structure_historical_major_zone_last_reaction_pct_1d_720", "gte", "0.03"),
            ],
            label_zh="1d 历史大结构区当前更像压力",
        ),
        _historical_structure_atomic(
            "structure_historical_major_role_flip_candidate",
            conditions=[
                _c("structure_historical_major_zone_lower_1d_720", "is_not_null"),
                _c("structure_historical_major_zone_upper_1d_720", "is_not_null"),
                _c("structure_historical_major_zone_test_count_1d_720", "gte", "2"),
                _c("structure_historical_major_zone_role_1d_720", "text_eq", "role_flip_candidate"),
                _c("structure_historical_major_distance_to_zone_pct_1d_720", "is_not_null"),
                _c("structure_historical_major_distance_to_zone_pct_1d_720", "lte", "0.01"),
            ],
            label_zh="当前位于 1d 历史大结构区内部，具备角色互换观察价值",
        ),
        _historical_structure_atomic(
            "structure_historical_major_far_from_zone",
            conditions=[
                _c("structure_historical_major_zone_lower_1d_720", "is_not_null"),
                _c("structure_historical_major_zone_upper_1d_720", "is_not_null"),
                _c("structure_historical_major_distance_to_zone_pct_1d_720", "is_not_null"),
                _c("structure_historical_major_distance_to_zone_pct_1d_720", "gte", "0.12"),
            ],
            label_zh="当前价格明显远离 1d 历史大结构区",
        ),
    )


def _risk_state() -> tuple[AtomicSignalDefinitionTemplate, ...]:
    return (
        _risk("risk_long_exposure_shock_down", risk_category="long_exposure_risk", risk_direction="downside", conditions=[_c("risk_latest_body_return_pct_4h", "lte", "-0.04"), _c("candle_body_ratio_4h_latest", "gte", "0.60"), _c("risk_latest_close_location_ratio_4h", "lte", "0.35")], label_zh="下行冲击下的多头暴露风险", severity_conditions=[_c("risk_latest_body_return_pct_4h", "lte", "-0.07"), _c("atr_percentile_4h_120", "gte", "0.95"), _c("structure_major_breakdown_below_support_pct_1d_365", "gt", "0")]),
        _risk("risk_short_exposure_shock_up", risk_category="short_exposure_risk", risk_direction="upside", conditions=[_c("risk_latest_body_return_pct_4h", "gte", "0.04"), _c("candle_body_ratio_4h_latest", "gte", "0.60"), _c("risk_latest_close_location_ratio_4h", "gte", "0.65")], label_zh="上行冲击下的空头暴露风险", severity_conditions=[_c("risk_latest_body_return_pct_4h", "gte", "0.07"), _c("atr_percentile_4h_120", "gte", "0.95"), _c("structure_major_breakout_above_resistance_pct_1d_365", "gt", "0")]),
        _risk(
            "risk_intrabar_extreme_range",
            risk_category="signal_reliability_risk",
            risk_direction="two_sided",
            conditions=[_c("candle_range_pct_4h_latest", "gte", "0.07")],
            label_zh="单根 4h 极端振幅事件",
            severity_conditions=[_c("candle_range_pct_4h_latest", "gte", "0.07")],
            include_feature_values=["candle_range_pct_4h_latest"],
        ),
        _risk("risk_short_chase_after_down_shock", risk_category="short_chase_risk", risk_direction="downside", conditions=[_c("risk_latest_body_return_pct_4h", "lte", "-0.04"), _c("atr_percentile_4h_120", "gte", "0.80"), _c("risk_latest_close_location_ratio_4h", "lte", "0.35")], label_zh="急跌后的追空风险", severity_conditions=[_c("risk_latest_body_return_pct_4h", "lte", "-0.07"), _c("risk_consecutive_large_bear_body_count_4h_20", "gte", "3")]),
        _risk("risk_long_chase_after_up_shock", risk_category="long_chase_risk", risk_direction="upside", conditions=[_c("risk_latest_body_return_pct_4h", "gte", "0.04"), _c("atr_percentile_4h_120", "gte", "0.80"), _c("risk_latest_close_location_ratio_4h", "gte", "0.65")], label_zh="急涨后的追多风险", severity_conditions=[_c("risk_latest_body_return_pct_4h", "gte", "0.07"), _c("risk_consecutive_large_bull_body_count_4h_20", "gte", "3")]),
        _risk("risk_false_breakout_rejection", risk_category="false_breakout_risk", risk_direction="upside", conditions=[_c("structure_minor_breakout_above_resistance_pct_4h_120", "gt", "0"), _c("upper_shadow_ratio_4h_latest", "gte", "0.45"), _c("risk_latest_close_location_ratio_4h", "lte", "0.55")], label_zh="向上突破快速失败风险", severity_conditions=[_c("atr_percentile_4h_120", "gte", "0.95"), _c("risk_latest_from_intrabar_high_reversal_pct_4h", "gte", "0.025")]),
        _risk("risk_false_breakdown_reclaim", risk_category="false_breakdown_risk", risk_direction="downside", conditions=[_c("structure_minor_breakdown_below_support_pct_4h_120", "gt", "0"), _c("lower_shadow_ratio_4h_latest", "gte", "0.45"), _c("risk_latest_close_location_ratio_4h", "gte", "0.45")], label_zh="向下跌破快速收回风险", severity_conditions=[_c("atr_percentile_4h_120", "gte", "0.95"), _c("risk_latest_from_intrabar_low_recovery_pct_4h", "gte", "0.025")]),
        _risk("risk_consecutive_down_disorder", risk_category="market_disorder_risk", risk_direction="downside", conditions=[_c("risk_consecutive_large_bear_body_count_4h_20", "gte", "3"), _c("risk_cumulative_return_pct_4h_3", "lte", "-0.08")], label_zh="连续急跌导致市场扰动", severity_conditions=[_c("atr_percentile_4h_120", "gte", "0.95"), _c("realized_vol_percentile_4h_120", "gte", "0.95")], aggregation="any"),
        _risk("risk_consecutive_up_disorder", risk_category="market_disorder_risk", risk_direction="upside", conditions=[_c("risk_consecutive_large_bull_body_count_4h_20", "gte", "3"), _c("risk_cumulative_return_pct_4h_3", "gte", "0.08")], label_zh="连续急涨导致市场扰动", severity_conditions=[_c("atr_percentile_4h_120", "gte", "0.95"), _c("realized_vol_percentile_4h_120", "gte", "0.95")], aggregation="any"),
        _risk("risk_two_sided_whipsaw", risk_category="signal_reliability_risk", risk_direction="two_sided", conditions=[_c("upper_shadow_ratio_4h_latest", "gte", "0.45"), _c("lower_shadow_ratio_4h_latest", "gte", "0.35"), _c("atr_percentile_4h_120", "gte", "0.80")], label_zh="双向剧烈扫动风险", severity_conditions=[_c("atr_percentile_4h_120", "gte", "0.95"), _c("realized_vol_percentile_4h_120", "gte", "0.95")]),
    )


def _feature_codes_from_params(params: Mapping[str, Any]) -> set[str]:
    codes: set[str] = set()
    if "left_feature_code" in params:
        codes.add(str(params["left_feature_code"]))
    if "right_feature_code" in params:
        codes.add(str(params["right_feature_code"]))
    include_feature_values = params.get("include_feature_values")
    if isinstance(include_feature_values, (list, tuple)):
        for item in include_feature_values:
            if str(item).strip():
                codes.add(str(item))
    for field in ("conditions", "severity_conditions"):
        value = params.get(field, [])
        if not isinstance(value, list):
            continue
        for item in value:
            if not isinstance(item, Mapping):
                continue
            feature_code = item.get("feature_code")
            right_feature_code = item.get("right_feature_code")
            if feature_code:
                codes.add(str(feature_code))
            if right_feature_code:
                codes.add(str(right_feature_code))
    return codes


DEFAULT_ATOMIC_SIGNAL_DEFINITIONS: tuple[AtomicSignalDefinitionTemplate, ...] = (
    *_market_context(),
    *_trend(),
    *_momentum(),
    *_volatility(),
    *_structure(),
    *_risk_state(),
)


def _assert_unique_signal_codes() -> None:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for template in DEFAULT_ATOMIC_SIGNAL_DEFINITIONS:
        if template.signal_code in seen:
            duplicates.add(template.signal_code)
        seen.add(template.signal_code)
    if duplicates:
        raise RuntimeError(f"DEFAULT_ATOMIC_SIGNAL_DEFINITIONS 存在重复 signal_code：{','.join(sorted(duplicates))}")


_assert_unique_signal_codes()
