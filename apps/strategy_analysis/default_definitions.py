"""StrategyAnalysis 模块：FeatureDefinition 默认登记模板。

负责：提供受代码管理的默认 FeatureDefinition 清单，供 seed_feature_definitions 写入数据库。
不负责：计算 FeatureSet、生成 FeatureValue、选择 StrategyAnalysisRelease、生成信号或交易动作。
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
from typing import Any

from apps.strategy_analysis.models import FeatureValueType


@dataclass(frozen=True)
class FeatureDefinitionTemplate:
    feature_code: str
    params: dict[str, Any]
    input_timeframes: tuple[str, ...]
    display_name: str = ""
    description: str = ""
    definition_version: str = "1.0.0"
    algorithm_name: str = "kline_price_features"
    algorithm_version: str = "1.0.0"
    value_type: str = FeatureValueType.DECIMAL
    output_schema_version: str = "1.0"


def _feature(
    feature_code: str,
    *,
    operation: str,
    timeframe: str,
    display_name: str | None = None,
    description: str | None = None,
    input_timeframes: tuple[str, ...] | None = None,
    **params: Any,
) -> FeatureDefinitionTemplate:
    frozen_params = {
        "operation": operation,
        "timeframe": timeframe,
        **params,
    }
    return FeatureDefinitionTemplate(
        feature_code=feature_code,
        display_name=display_name or feature_code,
        description=description or f"{feature_code} 默认特征定义。",
        params=frozen_params,
        input_timeframes=input_timeframes or (timeframe,),
    )


def _structure_metric(feature_code: str, *, timeframe: str, window: int, metric: str, nullable: bool) -> FeatureDefinitionTemplate:
    is_major = timeframe == "1d"
    return _feature(
        feature_code,
        operation="structure_zone_metric",
        timeframe=timeframe,
        window=window,
        metric=metric,
        nullable=nullable,
        swing_left_right=3 if is_major else 2,
        default_min_half_width_pct="0.012" if is_major else "0.006",
        confirmation_window=3,
        min_reaction_pct="0.015" if is_major else "0.008",
        min_touch_count=1,
        min_zone_score="0",
    )


DEFAULT_FEATURE_DEFINITIONS: tuple[FeatureDefinitionTemplate, ...] = (
    _feature("latest_close_1d", operation="latest_close", timeframe="1d", description="最新 1d 已收盘 K 线收盘价。"),
    _feature("latest_close_4h", operation="latest_close", timeframe="4h", description="最新 4h 已收盘 K 线收盘价。"),
    _feature("latest_volume_4h", operation="latest_volume", timeframe="4h", description="最新 4h 已收盘 K 线成交量。"),
    _feature("atr_1d_14", operation="atr", timeframe="1d", window=14, description="最近 14 根 1d 的绝对 ATR。"),
    _feature("atr_4h_14", operation="atr", timeframe="4h", window=14, description="最近 14 根 4h 的绝对 ATR。"),
    _feature("range_1d_60_high", operation="rolling_high", timeframe="1d", window=60),
    _feature("range_1d_60_low", operation="rolling_low", timeframe="1d", window=60),
    _feature("range_4h_60_high", operation="rolling_high", timeframe="4h", window=60),
    _feature("range_4h_60_low", operation="rolling_low", timeframe="4h", window=60),
    _feature("return_1d_1", operation="latest_close_return_pct", timeframe="1d"),
    _feature("return_4h_1", operation="latest_close_return_pct", timeframe="4h"),
    _feature("volume_sma_4h_20", operation="volume_sma", timeframe="4h", window=20),
    # market_context：长期背景事实
    _feature("sma_1d_120", operation="sma", timeframe="1d", window=120),
    _feature("sma_1d_200", operation="sma", timeframe="1d", window=200),
    _feature("sma_1d_365", operation="sma", timeframe="1d", window=365),
    _feature("close_vs_sma_pct_1d_120", operation="close_vs_sma_pct", timeframe="1d", window=120),
    _feature("close_vs_sma_pct_1d_200", operation="close_vs_sma_pct", timeframe="1d", window=200),
    _feature("close_vs_sma_pct_1d_365", operation="close_vs_sma_pct", timeframe="1d", window=365),
    _feature("slope_sma_1d_120", operation="slope_sma", timeframe="1d", window=120, lag=20),
    _feature("slope_sma_1d_200", operation="slope_sma", timeframe="1d", window=200, lag=20),
    _feature("slope_sma_1d_365", operation="slope_sma", timeframe="1d", window=365, lag=20),
    _feature("rolling_high_1d_365", operation="rolling_high", timeframe="1d", window=365),
    _feature("rolling_low_1d_365", operation="rolling_low", timeframe="1d", window=365),
    _feature("range_position_pct_1d_365", operation="range_position_pct", timeframe="1d", window=365),
    _feature("drawdown_from_high_pct_1d_365", operation="drawdown_from_high_pct", timeframe="1d", window=365),
    _feature("drawdown_duration_days_1d_365", operation="drawdown_duration_bars", timeframe="1d", window=365),
    _feature("drawdown_low_since_high_1d_365", operation="drawdown_low_since_high", timeframe="1d", window=365),
    _feature("rebound_from_drawdown_low_pct_1d_365", operation="rebound_from_drawdown_low_pct", timeframe="1d", window=365),
    _feature("rebound_duration_days_1d_365", operation="rebound_duration_bars", timeframe="1d", window=365),
    _feature("recovery_ratio_from_drawdown_1d_365", operation="recovery_ratio_from_drawdown", timeframe="1d", window=365),
    _feature("return_pct_1d_365", operation="return_pct", timeframe="1d", window=365),
    # trend：1d 主趋势与 4h 短周期趋势状态
    _feature("sma_1d_20", operation="sma", timeframe="1d", window=20),
    _feature("sma_1d_60", operation="sma", timeframe="1d", window=60),
    _feature("sma_4h_20", operation="sma", timeframe="4h", window=20),
    _feature("sma_4h_60", operation="sma", timeframe="4h", window=60),
    _feature("sma_4h_120", operation="sma", timeframe="4h", window=120),
    _feature("close_vs_sma_pct_1d_20", operation="close_vs_sma_pct", timeframe="1d", window=20),
    _feature("close_vs_sma_pct_1d_60", operation="close_vs_sma_pct", timeframe="1d", window=60),
    _feature("close_vs_sma_pct_4h_20", operation="close_vs_sma_pct", timeframe="4h", window=20),
    _feature("close_vs_sma_pct_4h_60", operation="close_vs_sma_pct", timeframe="4h", window=60),
    _feature("close_vs_sma_pct_4h_120", operation="close_vs_sma_pct", timeframe="4h", window=120),
    _feature("slope_sma_1d_20_lag10", operation="slope_sma", timeframe="1d", window=20, lag=10),
    _feature("slope_sma_1d_60_lag10", operation="slope_sma", timeframe="1d", window=60, lag=10),
    _feature("slope_sma_1d_120_lag10", operation="slope_sma", timeframe="1d", window=120, lag=10),
    _feature("slope_sma_4h_20_lag12", operation="slope_sma", timeframe="4h", window=20, lag=12),
    _feature("slope_sma_4h_60_lag12", operation="slope_sma", timeframe="4h", window=60, lag=12),
    _feature("slope_sma_4h_120_lag12", operation="slope_sma", timeframe="4h", window=120, lag=12),
    _feature("sma_spread_pct_1d_20_60", operation="sma_spread_pct", timeframe="1d", fast_window=20, slow_window=60),
    _feature("sma_spread_pct_1d_60_120", operation="sma_spread_pct", timeframe="1d", fast_window=60, slow_window=120),
    _feature("sma_spread_pct_4h_20_60", operation="sma_spread_pct", timeframe="4h", fast_window=20, slow_window=60),
    _feature("sma_spread_pct_4h_60_120", operation="sma_spread_pct", timeframe="4h", fast_window=60, slow_window=120),
    _feature("rolling_high_1d_60", operation="rolling_high", timeframe="1d", window=60),
    _feature("rolling_low_1d_60", operation="rolling_low", timeframe="1d", window=60),
    _feature("rolling_high_4h_60", operation="rolling_high", timeframe="4h", window=60),
    _feature("rolling_low_4h_60", operation="rolling_low", timeframe="4h", window=60),
    _feature("distance_from_rolling_high_pct_1d_60", operation="distance_from_rolling_high_pct", timeframe="1d", window=60),
    _feature("distance_from_rolling_low_pct_1d_60", operation="distance_from_rolling_low_pct", timeframe="1d", window=60),
    _feature("distance_from_rolling_high_pct_4h_60", operation="distance_from_rolling_high_pct", timeframe="4h", window=60),
    _feature("distance_from_rolling_low_pct_4h_60", operation="distance_from_rolling_low_pct", timeframe="4h", window=60),
    _feature("higher_high_count_1d_60_block20", operation="higher_high_count", timeframe="1d", window=60, block_size=20),
    _feature("higher_low_count_1d_60_block20", operation="higher_low_count", timeframe="1d", window=60, block_size=20),
    _feature("lower_high_count_1d_60_block20", operation="lower_high_count", timeframe="1d", window=60, block_size=20),
    _feature("lower_low_count_1d_60_block20", operation="lower_low_count", timeframe="1d", window=60, block_size=20),
    _feature("higher_high_count_4h_60_block20", operation="higher_high_count", timeframe="4h", window=60, block_size=20),
    _feature("higher_low_count_4h_60_block20", operation="higher_low_count", timeframe="4h", window=60, block_size=20),
    _feature("lower_high_count_4h_60_block20", operation="lower_high_count", timeframe="4h", window=60, block_size=20),
    _feature("lower_low_count_4h_60_block20", operation="lower_low_count", timeframe="4h", window=60, block_size=20),
    # momentum：价格推进事实
    _feature("return_pct_1d_3", operation="return_pct", timeframe="1d", window=3),
    _feature("return_pct_1d_7", operation="return_pct", timeframe="1d", window=7),
    _feature("return_pct_4h_12", operation="return_pct", timeframe="4h", window=12),
    _feature("return_pct_4h_24", operation="return_pct", timeframe="4h", window=24),
    _feature("previous_return_pct_1d_3", operation="previous_return_pct", timeframe="1d", window=3),
    _feature("previous_return_pct_1d_7", operation="previous_return_pct", timeframe="1d", window=7),
    _feature("previous_return_pct_4h_12", operation="previous_return_pct", timeframe="4h", window=12),
    _feature("previous_return_pct_4h_24", operation="previous_return_pct", timeframe="4h", window=24),
    _feature("return_delta_pct_1d_3", operation="return_delta_pct", timeframe="1d", window=3),
    _feature("return_delta_pct_1d_7", operation="return_delta_pct", timeframe="1d", window=7),
    _feature("return_delta_pct_4h_12", operation="return_delta_pct", timeframe="4h", window=12),
    _feature("return_delta_pct_4h_24", operation="return_delta_pct", timeframe="4h", window=24),
    _feature("up_bar_ratio_1d_7", operation="up_bar_ratio", timeframe="1d", window=7),
    _feature("down_bar_ratio_1d_7", operation="down_bar_ratio", timeframe="1d", window=7),
    _feature("up_bar_ratio_4h_24", operation="up_bar_ratio", timeframe="4h", window=24),
    _feature("down_bar_ratio_4h_24", operation="down_bar_ratio", timeframe="4h", window=24),
    _feature("consecutive_up_count_1d_7", operation="consecutive_up_count", timeframe="1d", window=7),
    _feature("consecutive_down_count_1d_7", operation="consecutive_down_count", timeframe="1d", window=7),
    _feature("consecutive_up_count_4h_24", operation="consecutive_up_count", timeframe="4h", window=24),
    _feature("consecutive_down_count_4h_24", operation="consecutive_down_count", timeframe="4h", window=24),
    _feature("movement_efficiency_1d_7", operation="movement_efficiency", timeframe="1d", window=7),
    _feature("movement_efficiency_4h_24", operation="movement_efficiency", timeframe="4h", window=24),
    _feature("close_location_pct_1d_latest", operation="close_location_pct_latest", timeframe="1d"),
    _feature("close_location_pct_4h_latest", operation="close_location_pct_latest", timeframe="4h"),
    _feature("close_location_avg_pct_1d_3", operation="close_location_avg_pct", timeframe="1d", window=3),
    _feature("close_location_avg_pct_4h_12", operation="close_location_avg_pct", timeframe="4h", window=12),
    # volatility：波动事实
    _feature("atr_pct_1d_14", operation="atr_pct", timeframe="1d", window=14),
    _feature("atr_pct_4h_14", operation="atr_pct", timeframe="4h", window=14),
    _feature("realized_vol_pct_1d_20", operation="realized_vol_pct", timeframe="1d", window=20),
    _feature("realized_vol_pct_4h_20", operation="realized_vol_pct", timeframe="4h", window=20),
    _feature("realized_vol_pct_4h_60", operation="realized_vol_pct", timeframe="4h", window=60),
    _feature("atr_percentile_1d_120", operation="atr_percentile", timeframe="1d", atr_window=14, reference_window=120),
    _feature("atr_percentile_4h_120", operation="atr_percentile", timeframe="4h", atr_window=14, reference_window=120),
    _feature("realized_vol_percentile_4h_120", operation="realized_vol_percentile", timeframe="4h", vol_window=20, reference_window=120),
    _feature("candle_range_pct_1d_latest", operation="candle_range_pct_latest", timeframe="1d"),
    _feature("candle_range_pct_4h_latest", operation="candle_range_pct_latest", timeframe="4h"),
    _feature("candle_body_pct_4h_latest", operation="candle_body_pct_latest", timeframe="4h"),
    _feature("candle_body_ratio_4h_latest", operation="candle_body_ratio_latest", timeframe="4h"),
    _feature("upper_shadow_ratio_4h_latest", operation="upper_shadow_ratio_latest", timeframe="4h"),
    _feature("lower_shadow_ratio_4h_latest", operation="lower_shadow_ratio_latest", timeframe="4h"),
    _feature("range_width_pct_1d_60", operation="range_width_pct", timeframe="1d", window=60),
    _feature("range_width_pct_4h_120", operation="range_width_pct", timeframe="4h", window=120),
    _feature("volatility_ratio_4h_20_to_60", operation="volatility_ratio", timeframe="4h", short_window=20, long_window=60),
    # risk_state：异常行情风险事实所需的基础数值
    _feature("risk_latest_close_return_pct_4h", operation="latest_close_return_pct", timeframe="4h"),
    _feature("risk_latest_body_return_pct_4h", operation="latest_body_return_pct", timeframe="4h"),
    _feature("risk_latest_abs_body_return_pct_4h", operation="latest_abs_body_return_pct", timeframe="4h"),
    _feature("risk_latest_close_location_ratio_4h", operation="latest_close_location_ratio", timeframe="4h"),
    _feature("risk_latest_close_near_high_distance_pct_4h", operation="latest_close_near_high_distance_pct", timeframe="4h"),
    _feature("risk_latest_close_near_low_distance_pct_4h", operation="latest_close_near_low_distance_pct", timeframe="4h"),
    _feature("risk_consecutive_large_bear_body_count_4h_20", operation="consecutive_large_bear_body_count", timeframe="4h", window=20),
    _feature("risk_consecutive_large_bull_body_count_4h_20", operation="consecutive_large_bull_body_count", timeframe="4h", window=20),
    _feature("risk_large_body_same_direction_count_4h_6", operation="large_body_same_direction_count", timeframe="4h", window=6),
    _feature("risk_cumulative_return_pct_4h_3", operation="cumulative_return_pct", timeframe="4h", window=3),
    _feature("risk_cumulative_return_pct_4h_6", operation="cumulative_return_pct", timeframe="4h", window=6),
    _feature("risk_max_single_body_return_pct_4h_20", operation="max_single_body_return_pct", timeframe="4h", window=20),
    _feature("risk_min_single_body_return_pct_4h_20", operation="min_single_body_return_pct", timeframe="4h", window=20),
    _feature("risk_latest_from_intrabar_high_reversal_pct_4h", operation="from_intrabar_high_reversal_pct", timeframe="4h"),
    _feature("risk_latest_from_intrabar_low_recovery_pct_4h", operation="from_intrabar_low_recovery_pct", timeframe="4h"),
    _feature("risk_two_bar_opposite_reversal_pct_4h", operation="two_bar_opposite_reversal_pct", timeframe="4h"),
    # structure：支撑压力、区间和位置事实
    _feature("structure_major_latest_close_1d", operation="latest_close", timeframe="1d"),
    _feature("structure_minor_latest_close_4h", operation="latest_close", timeframe="4h"),
    _structure_metric("structure_major_support_lower_1d_365", timeframe="1d", window=365, metric="support_lower", nullable=True),
    _structure_metric("structure_major_support_upper_1d_365", timeframe="1d", window=365, metric="support_upper", nullable=True),
    _structure_metric("structure_major_resistance_lower_1d_365", timeframe="1d", window=365, metric="resistance_lower", nullable=True),
    _structure_metric("structure_major_resistance_upper_1d_365", timeframe="1d", window=365, metric="resistance_upper", nullable=True),
    _structure_metric("structure_major_support_touch_count_1d_365", timeframe="1d", window=365, metric="support_touch_count", nullable=False),
    _structure_metric("structure_major_resistance_touch_count_1d_365", timeframe="1d", window=365, metric="resistance_touch_count", nullable=False),
    _structure_metric("structure_major_support_score_1d_365", timeframe="1d", window=365, metric="support_score", nullable=False),
    _structure_metric("structure_major_resistance_score_1d_365", timeframe="1d", window=365, metric="resistance_score", nullable=False),
    _structure_metric("structure_minor_support_lower_4h_120", timeframe="4h", window=120, metric="support_lower", nullable=True),
    _structure_metric("structure_minor_support_upper_4h_120", timeframe="4h", window=120, metric="support_upper", nullable=True),
    _structure_metric("structure_minor_resistance_lower_4h_120", timeframe="4h", window=120, metric="resistance_lower", nullable=True),
    _structure_metric("structure_minor_resistance_upper_4h_120", timeframe="4h", window=120, metric="resistance_upper", nullable=True),
    _structure_metric("structure_minor_support_touch_count_4h_120", timeframe="4h", window=120, metric="support_touch_count", nullable=False),
    _structure_metric("structure_minor_resistance_touch_count_4h_120", timeframe="4h", window=120, metric="resistance_touch_count", nullable=False),
    _structure_metric("structure_minor_support_score_4h_120", timeframe="4h", window=120, metric="support_score", nullable=False),
    _structure_metric("structure_minor_resistance_score_4h_120", timeframe="4h", window=120, metric="resistance_score", nullable=False),
    _structure_metric("structure_major_distance_to_support_upper_pct_1d_365", timeframe="1d", window=365, metric="distance_to_support_upper_pct", nullable=True),
    _structure_metric("structure_major_distance_to_resistance_lower_pct_1d_365", timeframe="1d", window=365, metric="distance_to_resistance_lower_pct", nullable=True),
    _structure_metric("structure_major_range_position_pct_1d_365", timeframe="1d", window=365, metric="range_position_pct", nullable=True),
    _structure_metric("structure_major_range_width_pct_1d_365", timeframe="1d", window=365, metric="range_width_pct", nullable=True),
    _structure_metric("structure_minor_distance_to_support_upper_pct_4h_120", timeframe="4h", window=120, metric="distance_to_support_upper_pct", nullable=True),
    _structure_metric("structure_minor_distance_to_resistance_lower_pct_4h_120", timeframe="4h", window=120, metric="distance_to_resistance_lower_pct", nullable=True),
    _structure_metric("structure_minor_range_position_pct_4h_120", timeframe="4h", window=120, metric="range_position_pct", nullable=True),
    _structure_metric("structure_minor_range_width_pct_4h_120", timeframe="4h", window=120, metric="range_width_pct", nullable=True),
    _structure_metric("structure_major_breakout_above_resistance_pct_1d_365", timeframe="1d", window=365, metric="breakout_above_resistance_pct", nullable=True),
    _structure_metric("structure_major_breakdown_below_support_pct_1d_365", timeframe="1d", window=365, metric="breakdown_below_support_pct", nullable=True),
    _structure_metric("structure_minor_breakout_above_resistance_pct_4h_120", timeframe="4h", window=120, metric="breakout_above_resistance_pct", nullable=True),
    _structure_metric("structure_minor_breakdown_below_support_pct_4h_120", timeframe="4h", window=120, metric="breakdown_below_support_pct", nullable=True),
)


def _assert_unique_feature_codes() -> None:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for template in DEFAULT_FEATURE_DEFINITIONS:
        if template.feature_code in seen:
            duplicates.add(template.feature_code)
        seen.add(template.feature_code)
    if duplicates:
        raise RuntimeError(f"DEFAULT_FEATURE_DEFINITIONS 存在重复 feature_code：{','.join(sorted(duplicates))}")


_assert_unique_feature_codes()
