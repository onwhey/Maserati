"""StrategyAnalysis 模块：DomainSignalDefinition 默认登记模板。
负责：提供受代码管理的领域定义清单，供 seed_domain_signal_definitions 写入数据库。
不负责：计算 DomainSignalSet、读取 AtomicSignalValue、识别 MarketRegime、选择策略或生成订单动作。
读写数据库：不涉及。访问 Redis：不涉及。访问外部服务：不涉及。发送 Hermes：不涉及。
调用大模型：不涉及。涉及交易执行：不涉及。允许真实交易：否。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from apps.strategy_analysis.default_atomic_definitions import DEFAULT_ATOMIC_SIGNAL_DEFINITIONS
from apps.strategy_analysis.definition_hashes import normalize_atomic_signal_codes
from apps.strategy_analysis.models import DomainSignalOutputMode


@dataclass(frozen=True)
class DomainSignalDefinitionTemplate:
    domain_code: str
    display_name: str
    description: str
    category: str
    output_mode: str
    algorithm_name: str
    algorithm_version: str
    params: dict[str, Any]
    minimum_coverage_ratio: str = "0.70"
    agreement_threshold: str | None = None
    is_required: bool = True

    @property
    def allowed_atomic_signal_codes(self) -> tuple[str, ...]:
        return normalize_atomic_signal_codes(self.params["allowed_atomic_signal_codes"])

    @property
    def required_atomic_signal_codes(self) -> tuple[str, ...]:
        return normalize_atomic_signal_codes(self.params.get("required_atomic_signal_codes", []), allow_empty=True)


def _codes(category: str) -> list[str]:
    return sorted(template.signal_code for template in DEFAULT_ATOMIC_SIGNAL_DEFINITIONS if template.category == category)


def _base_params(domain_type: str, *, required: list[str] | None = None) -> dict[str, Any]:
    return {
        "domain_type": domain_type,
        "allowed_atomic_signal_codes": _codes(domain_type),
        "required_atomic_signal_codes": required or [],
    }


def _market_context() -> DomainSignalDefinitionTemplate:
    params = {
        **_base_params("market_context"),
        "bullish_group": [
            "market_context_price_above_sma_1d_200",
            "market_context_price_above_sma_1d_365",
            "market_context_sma_1d_200_rising",
            "market_context_sma_1d_365_rising",
            "market_context_positive_365d_return",
        ],
        "bearish_group": [
            "market_context_price_below_sma_1d_200",
            "market_context_price_below_sma_1d_365",
            "market_context_sma_1d_200_falling",
            "market_context_sma_1d_365_falling",
            "market_context_negative_365d_return",
            "market_context_deep_drawdown_from_365d_high",
        ],
        "state_signals": {
            "market_context_in_365d_high_zone": "high_zone",
            "market_context_in_365d_low_zone": "low_zone",
            "market_context_moderate_drawdown_from_365d_high": "moderate_drawdown",
            "market_context_deep_drawdown_from_365d_high": "deep_drawdown",
            "market_context_material_rebound_from_drawdown_low": "material_rebound",
            "market_context_high_recovery_from_drawdown": "high_recovery",
            "market_context_low_recovery_from_drawdown": "low_recovery",
        },
        "state_priority": [
            "deep_drawdown",
            "moderate_drawdown",
            "material_rebound",
            "high_recovery",
            "low_recovery",
            "high_zone",
            "low_zone",
        ],
        "min_direction_gap": 2,
        "strong_direction_gap": 4,
    }
    return DomainSignalDefinitionTemplate(
        domain_code="market_context",
        display_name="市场大背景领域",
        description="聚合长期均线、年度区间、回撤和修复类原子信号，形成市场大背景事实。",
        category="market_context",
        output_mode=DomainSignalOutputMode.DIRECTIONAL,
        algorithm_name="grouped_atomic_aggregation",
        algorithm_version="1.0.0",
        params=params,
    )


def _trend() -> DomainSignalDefinitionTemplate:
    params = {
        **_base_params("trend"),
        "primary_bullish_group": [
            "trend_1d_ma_bullish_alignment",
            "trend_1d_slow_slope_rising",
            "trend_1d_price_above_medium_ma",
            "trend_1d_block_structure_rising",
        ],
        "primary_bearish_group": [
            "trend_1d_ma_bearish_alignment",
            "trend_1d_slow_slope_falling",
            "trend_1d_price_below_medium_ma",
            "trend_1d_block_structure_falling",
        ],
        "short_cycle_bullish_group": [
            "trend_4h_ma_bullish_alignment",
            "trend_4h_medium_slope_rising",
            "trend_4h_price_above_medium_ma",
            "trend_4h_block_structure_rising",
        ],
        "short_cycle_bearish_group": [
            "trend_4h_ma_bearish_alignment",
            "trend_4h_medium_slope_falling",
            "trend_4h_price_below_medium_ma",
            "trend_4h_block_structure_falling",
        ],
        "primary_min_gap": 2,
        "short_cycle_min_gap": 2,
        "strong_primary_gap": 4,
        "state_code_map": {
            "bullish:bullish": "trend_1d_bullish_4h_aligned",
            "bullish:bearish": "trend_1d_bullish_4h_pullback",
            "bullish:neutral": "trend_1d_bullish_4h_unclear",
            "bearish:bearish": "trend_1d_bearish_4h_aligned",
            "bearish:bullish": "trend_1d_bearish_4h_rebound",
            "bearish:neutral": "trend_1d_bearish_4h_unclear",
            "neutral:bullish": "trend_1d_neutral_4h_bullish",
            "neutral:bearish": "trend_1d_neutral_4h_bearish",
            "neutral:neutral": "trend_unclear",
        },
    }
    return DomainSignalDefinitionTemplate(
        domain_code="trend",
        display_name="趋势领域",
        description="以 1d 为主、4h 为辅助，聚合趋势方向和趋势清晰度事实。",
        category="trend",
        output_mode=DomainSignalOutputMode.DIRECTIONAL,
        algorithm_name="grouped_atomic_aggregation",
        algorithm_version="1.0.0",
        params=params,
    )


def _momentum() -> DomainSignalDefinitionTemplate:
    params = {
        **_base_params("momentum"),
        "primary_bullish_group": [
            "momentum_1d_bullish_push_exists",
            "momentum_1d_bullish_push_strengthening",
            "momentum_1d_bullish_continuity_good",
            "momentum_1d_close_strength_bullish",
        ],
        "primary_bearish_group": [
            "momentum_1d_bearish_push_exists",
            "momentum_1d_bearish_push_strengthening",
            "momentum_1d_bearish_continuity_good",
            "momentum_1d_close_strength_bearish",
        ],
        "short_cycle_bullish_group": [
            "momentum_4h_bullish_push_exists",
            "momentum_4h_bullish_push_strengthening",
            "momentum_4h_bullish_continuity_good",
            "momentum_4h_close_strength_bullish",
        ],
        "short_cycle_bearish_group": [
            "momentum_4h_bearish_push_exists",
            "momentum_4h_bearish_push_strengthening",
            "momentum_4h_bearish_continuity_good",
            "momentum_4h_close_strength_bearish",
        ],
        "state_signals": {
            "momentum_1d_bullish_push_strengthening": "bullish_strengthening",
            "momentum_1d_bearish_push_strengthening": "bearish_strengthening",
            "momentum_1d_bullish_push_exhausting": "bullish_exhausting",
            "momentum_1d_bearish_push_exhausting": "bearish_exhausting",
            "momentum_1d_movement_efficiency_low": "movement_efficiency_low",
            "momentum_1d_movement_efficiency_high": "movement_efficiency_high",
            "momentum_4h_bullish_push_strengthening": "short_cycle_bullish_strengthening",
            "momentum_4h_bearish_push_strengthening": "short_cycle_bearish_strengthening",
            "momentum_4h_bullish_push_exhausting": "short_cycle_bullish_exhausting",
            "momentum_4h_bearish_push_exhausting": "short_cycle_bearish_exhausting",
        },
        "primary_min_gap": 2,
        "short_cycle_min_gap": 2,
        "strong_primary_gap": 4,
    }
    return DomainSignalDefinitionTemplate(
        domain_code="momentum",
        display_name="动能领域",
        description="聚合 1d 主推动力和 4h 辅助推动力，形成动能方向、增强或衰竭事实。",
        category="momentum",
        output_mode=DomainSignalOutputMode.DIRECTIONAL,
        algorithm_name="grouped_atomic_aggregation",
        algorithm_version="1.0.0",
        params=params,
    )


def _volatility() -> DomainSignalDefinitionTemplate:
    params = {
        **_base_params("volatility"),
        "low_volatility_group": [
            "volatility_1d_atr_low_percentile",
            "volatility_4h_atr_low_percentile",
            "volatility_4h_realized_vol_low_percentile",
            "volatility_4h_compression",
            "volatility_1d_range_narrow",
            "volatility_4h_range_narrow",
        ],
        "high_volatility_group": [
            "volatility_1d_atr_high_percentile",
            "volatility_4h_atr_high_percentile",
            "volatility_4h_realized_vol_high_percentile",
            "volatility_4h_expansion",
            "volatility_1d_range_wide",
            "volatility_4h_range_wide",
        ],
        "extreme_volatility_group": [
            "volatility_1d_atr_extreme_percentile",
            "volatility_4h_atr_extreme_percentile",
            "volatility_1d_latest_candle_range_large",
            "volatility_4h_latest_candle_range_large",
            "volatility_4h_latest_large_body",
        ],
        "state_signals": {
            "volatility_4h_latest_upper_shadow_dominant": "latest_4h_upper_shadow_dominant",
            "volatility_4h_latest_lower_shadow_dominant": "latest_4h_lower_shadow_dominant",
        },
        "low_min_count": 2,
        "high_min_count": 2,
        "extreme_min_count": 1,
        "strong_state_denominator": 4,
    }
    return DomainSignalDefinitionTemplate(
        domain_code="volatility",
        display_name="波动领域",
        description="聚合低波动、高波动、极高波动、压缩扩张和最新 K 线形态事实。",
        category="volatility",
        output_mode=DomainSignalOutputMode.STATE,
        algorithm_name="grouped_atomic_aggregation",
        algorithm_version="1.0.0",
        params=params,
    )


def _structure() -> DomainSignalDefinitionTemplate:
    params = {
        **_base_params("structure"),
        "clear_state_strength": "0.80",
        "minor_only_strength_cap": "0.50",
        "unclear_strength": "0",
    }
    return DomainSignalDefinitionTemplate(
        domain_code="structure",
        display_name="结构领域",
        description="聚合 1d 大结构和 4h 小结构，形成支撑、压力、区间、突破和跌破事实。",
        category="structure",
        output_mode=DomainSignalOutputMode.DIRECTIONAL,
        algorithm_name="grouped_atomic_aggregation",
        algorithm_version="1.0.0",
        params=params,
    )


def _risk_state() -> DomainSignalDefinitionTemplate:
    return DomainSignalDefinitionTemplate(
        domain_code="risk_state",
        display_name="市场风险状态领域",
        description="聚合冲击、假突破、追单和市场扰动类原子事实，形成非交易动作的风险状态。",
        category="risk_state",
        output_mode=DomainSignalOutputMode.STATE,
        algorithm_name="grouped_atomic_aggregation",
        algorithm_version="1.0.0",
        params=_base_params("risk_state"),
    )


DEFAULT_DOMAIN_SIGNAL_DEFINITIONS: tuple[DomainSignalDefinitionTemplate, ...] = (
    _market_context(),
    _trend(),
    _momentum(),
    _volatility(),
    _structure(),
    _risk_state(),
)


def _assert_templates() -> None:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for template in DEFAULT_DOMAIN_SIGNAL_DEFINITIONS:
        if template.domain_code in seen:
            duplicates.add(template.domain_code)
        seen.add(template.domain_code)
        if not template.allowed_atomic_signal_codes:
            raise RuntimeError(f"{template.domain_code} 缺少 allowed_atomic_signal_codes")
    if duplicates:
        raise RuntimeError(f"DEFAULT_DOMAIN_SIGNAL_DEFINITIONS 存在重复 domain_code：{','.join(sorted(duplicates))}")


_assert_templates()
