"""FeatureLayer 模块：kline_price_features/1.0.0 K 线价格特征 calculator。

负责：基于 MarketSnapshot 冻结的 1d / 4h 已收盘 K 线计算可复用价格特征。
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
from decimal import Decimal, InvalidOperation
from statistics import median
from typing import Any, Callable, Mapping, Sequence

from ..contracts import CalculatorInput, CalculatorMetadata, CalculatorOutput, CalculatorType


@dataclass(frozen=True)
class KlineBar:
    open_time_utc: str
    close_time_utc: str
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal


@dataclass(frozen=True)
class StructureZone:
    lower: Decimal
    upper: Decimal
    center: Decimal
    touch_count: int
    score: Decimal
    last_touch_index: int


@dataclass(frozen=True)
class StructureSnapshot:
    latest_close: Decimal
    support: StructureZone | None
    resistance: StructureZone | None


class KlinePriceFeatureCalculator:
    metadata = CalculatorMetadata(
        algorithm_name="kline_price_features",
        algorithm_version="1.0.0",
        calculator_type=CalculatorType.FEATURE_LAYER,
        input_schema_version="1.0",
        output_schema_version="1.0",
        deterministic=True,
        supports_dry_run=True,
        algorithm_requirement_document_path="docs/requirements/feature_layer.md",
        implementation_document_path="docs/implementation/feature_layer/kline_price_features__1.0.0.md",
    )

    def calculate(self, calculation_input: CalculatorInput) -> CalculatorOutput:
        params = dict(calculation_input.frozen_params)
        values = dict(calculation_input.values)
        operation = str(params.get("operation") or "").strip()
        if not operation:
            return self._failed("feature_operation_missing", "FeatureDefinition.params.operation 不能为空")
        try:
            market_snapshot = values.get("market_snapshot")
            if not isinstance(market_snapshot, Mapping):
                raise FeatureCalculationError("market_snapshot_missing", "缺少 MarketSnapshot K 线输入")
            timeframe = str(params.get("timeframe") or "").strip()
            bars = _bars_for_timeframe(market_snapshot, timeframe)
            value = self._dispatch(operation=operation, bars=bars, params=params)
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
                    "lag": params.get("lag"),
                    "value": str(value),
                },
            ),
            calculation_summary={
                "operation": operation,
                "timeframe": params.get("timeframe"),
                "input_count": len(bars),
            },
        )

    def _dispatch(self, *, operation: str, bars: list[KlineBar], params: dict[str, Any]) -> Decimal:
        handlers: dict[str, Callable[[list[KlineBar], dict[str, Any]], Decimal]] = {
            "latest_close": self._latest_close,
            "latest_volume": self._latest_volume,
            "volume_sma": self._volume_sma,
            "sma": self._sma,
            "close_vs_sma_pct": self._close_vs_sma_pct,
            "slope_sma": self._slope_sma,
            "sma_spread_pct": self._sma_spread_pct,
            "rolling_high": self._rolling_high,
            "rolling_low": self._rolling_low,
            "distance_from_rolling_high_pct": self._distance_from_rolling_high_pct,
            "distance_from_rolling_low_pct": self._distance_from_rolling_low_pct,
            "range_position_pct": self._range_position_pct,
            "drawdown_from_high_pct": self._drawdown_from_high_pct,
            "drawdown_duration_bars": self._drawdown_duration_bars,
            "drawdown_low_since_high": self._drawdown_low_since_high,
            "rebound_from_drawdown_low_pct": self._rebound_from_drawdown_low_pct,
            "rebound_duration_bars": self._rebound_duration_bars,
            "recovery_ratio_from_drawdown": self._recovery_ratio_from_drawdown,
            "return_pct": self._return_pct,
            "previous_return_pct": self._previous_return_pct,
            "return_delta_pct": self._return_delta_pct,
            "up_bar_ratio": self._up_bar_ratio,
            "down_bar_ratio": self._down_bar_ratio,
            "consecutive_up_count": self._consecutive_up_count,
            "consecutive_down_count": self._consecutive_down_count,
            "movement_efficiency": self._movement_efficiency,
            "close_location_pct_latest": self._close_location_pct_latest,
            "close_location_avg_pct": self._close_location_avg_pct,
            "atr": self._atr,
            "atr_pct": self._atr_pct,
            "realized_vol_pct": self._realized_vol_pct,
            "atr_percentile": self._atr_percentile,
            "realized_vol_percentile": self._realized_vol_percentile,
            "candle_range_pct_latest": self._candle_range_pct_latest,
            "candle_body_pct_latest": self._candle_body_pct_latest,
            "candle_body_ratio_latest": self._candle_body_ratio_latest,
            "upper_shadow_ratio_latest": self._upper_shadow_ratio_latest,
            "lower_shadow_ratio_latest": self._lower_shadow_ratio_latest,
            "range_width_pct": self._range_width_pct,
            "volatility_ratio": self._volatility_ratio,
            "latest_close_return_pct": self._latest_close_return_pct,
            "latest_body_return_pct": self._latest_body_return_pct,
            "latest_abs_body_return_pct": self._latest_abs_body_return_pct,
            "latest_close_location_ratio": self._close_location_pct_latest,
            "latest_close_near_high_distance_pct": self._latest_close_near_high_distance_pct,
            "latest_close_near_low_distance_pct": self._latest_close_near_low_distance_pct,
            "consecutive_large_bear_body_count": self._consecutive_large_bear_body_count,
            "consecutive_large_bull_body_count": self._consecutive_large_bull_body_count,
            "large_body_same_direction_count": self._large_body_same_direction_count,
            "cumulative_return_pct": self._cumulative_return_pct,
            "max_single_body_return_pct": self._max_single_body_return_pct,
            "min_single_body_return_pct": self._min_single_body_return_pct,
            "from_intrabar_high_reversal_pct": self._from_intrabar_high_reversal_pct,
            "from_intrabar_low_recovery_pct": self._from_intrabar_low_recovery_pct,
            "two_bar_opposite_reversal_pct": self._two_bar_opposite_reversal_pct,
            "higher_high_count": self._higher_high_count,
            "higher_low_count": self._higher_low_count,
            "lower_high_count": self._lower_high_count,
            "lower_low_count": self._lower_low_count,
            "structure_zone_metric": self._structure_zone_metric,
        }
        handler = handlers.get(operation)
        if handler is None:
            raise FeatureCalculationError("feature_operation_unsupported", f"不支持的 Feature operation：{operation}")
        return handler(bars, params)

    @staticmethod
    def _latest_close(bars: list[KlineBar], _params: dict[str, Any]) -> Decimal:
        return _latest(bars).close

    @staticmethod
    def _latest_volume(bars: list[KlineBar], _params: dict[str, Any]) -> Decimal:
        return _latest(bars).volume

    @staticmethod
    def _volume_sma(bars: list[KlineBar], params: dict[str, Any]) -> Decimal:
        return _mean([bar.volume for bar in _tail(bars, _positive_int(params, "window"))])

    @staticmethod
    def _sma(bars: list[KlineBar], params: dict[str, Any]) -> Decimal:
        window_bars = _tail(bars, _positive_int(params, "window"))
        return _mean([_field_value(bar, params.get("price_field") or "close") for bar in window_bars])

    def _close_vs_sma_pct(self, bars: list[KlineBar], params: dict[str, Any]) -> Decimal:
        sma = self._sma(bars, params)
        return _safe_div(_latest(bars).close - sma, sma, "sma_non_positive")

    def _slope_sma(self, bars: list[KlineBar], params: dict[str, Any]) -> Decimal:
        window = _positive_int(params, "window")
        lag = _positive_int(params, "lag")
        _require_count(bars, window + lag)
        current = self._sma(bars, {"window": window, "price_field": params.get("price_field") or "close"})
        lagged = self._sma(bars[:-lag], {"window": window, "price_field": params.get("price_field") or "close"})
        return _safe_div(current - lagged, lagged, "lagged_sma_non_positive")

    def _sma_spread_pct(self, bars: list[KlineBar], params: dict[str, Any]) -> Decimal:
        fast = self._sma(bars, {"window": _positive_int(params, "fast_window")})
        slow = self._sma(bars, {"window": _positive_int(params, "slow_window")})
        return _safe_div(fast - slow, slow, "slow_sma_non_positive")

    @staticmethod
    def _rolling_high(bars: list[KlineBar], params: dict[str, Any]) -> Decimal:
        return max(bar.high for bar in _window_for_reference(bars, params))

    @staticmethod
    def _rolling_low(bars: list[KlineBar], params: dict[str, Any]) -> Decimal:
        return min(bar.low for bar in _window_for_reference(bars, params))

    def _distance_from_rolling_high_pct(self, bars: list[KlineBar], params: dict[str, Any]) -> Decimal:
        rolling_high = self._rolling_high(bars, params)
        return _safe_div(_latest(bars).close - rolling_high, rolling_high, "rolling_high_non_positive")

    def _distance_from_rolling_low_pct(self, bars: list[KlineBar], params: dict[str, Any]) -> Decimal:
        rolling_low = self._rolling_low(bars, params)
        return _safe_div(_latest(bars).close - rolling_low, rolling_low, "rolling_low_non_positive")

    def _range_position_pct(self, bars: list[KlineBar], params: dict[str, Any]) -> Decimal:
        high = self._rolling_high(bars, params)
        low = self._rolling_low(bars, params)
        return _safe_div(_latest(bars).close - low, high - low, "range_width_non_positive")

    def _drawdown_from_high_pct(self, bars: list[KlineBar], params: dict[str, Any]) -> Decimal:
        high = self._rolling_high(bars, params)
        return _safe_div(high - _latest(bars).close, high, "rolling_high_non_positive")

    def _drawdown_duration_bars(self, bars: list[KlineBar], params: dict[str, Any]) -> Decimal:
        window_bars = _window_for_reference(bars, params)
        high = max(bar.high for bar in window_bars)
        index = max(idx for idx, bar in enumerate(window_bars) if bar.high == high)
        return Decimal(len(window_bars) - 1 - index)

    def _drawdown_low_since_high(self, bars: list[KlineBar], params: dict[str, Any]) -> Decimal:
        after_high = self._bars_since_rolling_high(bars, params)
        return min(bar.low for bar in after_high)

    def _rebound_from_drawdown_low_pct(self, bars: list[KlineBar], params: dict[str, Any]) -> Decimal:
        low = self._drawdown_low_since_high(bars, params)
        return _safe_div(_latest(bars).close - low, low, "drawdown_low_non_positive")

    def _rebound_duration_bars(self, bars: list[KlineBar], params: dict[str, Any]) -> Decimal:
        after_high = self._bars_since_rolling_high(bars, params)
        low = min(bar.low for bar in after_high)
        index = max(idx for idx, bar in enumerate(after_high) if bar.low == low)
        return Decimal(len(after_high) - 1 - index)

    def _recovery_ratio_from_drawdown(self, bars: list[KlineBar], params: dict[str, Any]) -> Decimal:
        high = self._rolling_high(bars, params)
        low = self._drawdown_low_since_high(bars, params)
        if high == low and _latest(bars).close >= high:
            return Decimal("1")
        return _safe_div(_latest(bars).close - low, high - low, "drawdown_range_non_positive")

    @staticmethod
    def _return_pct(bars: list[KlineBar], params: dict[str, Any]) -> Decimal:
        window = _tail(bars, _positive_int(params, "window"))
        return _safe_div(window[-1].close - window[0].close, window[0].close, "first_close_non_positive")

    @staticmethod
    def _previous_return_pct(bars: list[KlineBar], params: dict[str, Any]) -> Decimal:
        window = _positive_int(params, "window")
        _require_count(bars, window * 2)
        previous = bars[-window * 2 : -window]
        return _safe_div(previous[-1].close - previous[0].close, previous[0].close, "first_close_non_positive")

    def _return_delta_pct(self, bars: list[KlineBar], params: dict[str, Any]) -> Decimal:
        return self._return_pct(bars, params) - self._previous_return_pct(bars, params)

    @staticmethod
    def _up_bar_ratio(bars: list[KlineBar], params: dict[str, Any]) -> Decimal:
        window = _tail(bars, _positive_int(params, "window"))
        return Decimal(sum(1 for bar in window if bar.close > bar.open)) / Decimal(len(window))

    @staticmethod
    def _down_bar_ratio(bars: list[KlineBar], params: dict[str, Any]) -> Decimal:
        window = _tail(bars, _positive_int(params, "window"))
        return Decimal(sum(1 for bar in window if bar.close < bar.open)) / Decimal(len(window))

    @staticmethod
    def _consecutive_up_count(bars: list[KlineBar], params: dict[str, Any]) -> Decimal:
        return Decimal(_consecutive_count(_tail(bars, _positive_int(params, "window")), lambda bar: bar.close > bar.open))

    @staticmethod
    def _consecutive_down_count(bars: list[KlineBar], params: dict[str, Any]) -> Decimal:
        return Decimal(_consecutive_count(_tail(bars, _positive_int(params, "window")), lambda bar: bar.close < bar.open))

    @staticmethod
    def _movement_efficiency(bars: list[KlineBar], params: dict[str, Any]) -> Decimal:
        window = _tail(bars, _positive_int(params, "window"))
        net_move = abs(window[-1].close - window[0].close)
        path_move = sum(abs(window[idx].close - window[idx - 1].close) for idx in range(1, len(window)))
        return _safe_div(net_move, path_move, "path_move_non_positive")

    @staticmethod
    def _close_location_pct_latest(bars: list[KlineBar], _params: dict[str, Any]) -> Decimal:
        return _close_location(_latest(bars))

    @staticmethod
    def _close_location_avg_pct(bars: list[KlineBar], params: dict[str, Any]) -> Decimal:
        return _mean([_close_location(bar) for bar in _tail(bars, _positive_int(params, "window"))])

    @staticmethod
    def _atr(bars: list[KlineBar], params: dict[str, Any]) -> Decimal:
        window = _positive_int(params, "window")
        target = _tail(bars, window + 1)
        true_ranges = [_true_range(target[idx], target[idx - 1].close) for idx in range(1, len(target))]
        return _mean(true_ranges)

    @staticmethod
    def _atr_pct(bars: list[KlineBar], params: dict[str, Any]) -> Decimal:
        window = _positive_int(params, "window")
        target = _tail(bars, window + 1)
        true_ranges = [_true_range(target[idx], target[idx - 1].close) for idx in range(1, len(target))]
        return _safe_div(_mean(true_ranges), target[-1].close, "latest_close_non_positive")

    @staticmethod
    def _realized_vol_pct(bars: list[KlineBar], params: dict[str, Any]) -> Decimal:
        returns = _close_returns(_tail(bars, _positive_int(params, "window") + 1))
        return _population_stddev(returns)

    @staticmethod
    def _atr_percentile(bars: list[KlineBar], params: dict[str, Any]) -> Decimal:
        atr_window = int(params.get("atr_window") or 14)
        reference_window = _positive_int(params, "reference_window")
        _require_count(bars, atr_window + reference_window)
        series = [_atr_pct_at(bars[:idx], atr_window) for idx in range(atr_window + 1, len(bars) + 1)]
        reference = series[-reference_window:]
        current = reference[-1]
        return Decimal(sum(1 for value in reference if value <= current)) / Decimal(len(reference))

    @staticmethod
    def _realized_vol_percentile(bars: list[KlineBar], params: dict[str, Any]) -> Decimal:
        vol_window = int(params.get("vol_window") or 20)
        reference_window = _positive_int(params, "reference_window")
        _require_count(bars, vol_window + reference_window)
        series = [_realized_vol_at(bars[:idx], vol_window) for idx in range(vol_window + 1, len(bars) + 1)]
        reference = series[-reference_window:]
        current = reference[-1]
        return Decimal(sum(1 for value in reference if value <= current)) / Decimal(len(reference))

    @staticmethod
    def _candle_range_pct_latest(bars: list[KlineBar], _params: dict[str, Any]) -> Decimal:
        bar = _latest(bars)
        return _safe_div(bar.high - bar.low, bar.close, "latest_close_non_positive")

    @staticmethod
    def _candle_body_pct_latest(bars: list[KlineBar], _params: dict[str, Any]) -> Decimal:
        bar = _latest(bars)
        return _safe_div(abs(bar.close - bar.open), bar.close, "latest_close_non_positive")

    @staticmethod
    def _candle_body_ratio_latest(bars: list[KlineBar], _params: dict[str, Any]) -> Decimal:
        bar = _latest(bars)
        return _safe_div(abs(bar.close - bar.open), bar.high - bar.low, "candle_range_non_positive")

    @staticmethod
    def _upper_shadow_ratio_latest(bars: list[KlineBar], _params: dict[str, Any]) -> Decimal:
        bar = _latest(bars)
        return _safe_div(bar.high - max(bar.open, bar.close), bar.high - bar.low, "candle_range_non_positive")

    @staticmethod
    def _lower_shadow_ratio_latest(bars: list[KlineBar], _params: dict[str, Any]) -> Decimal:
        bar = _latest(bars)
        return _safe_div(min(bar.open, bar.close) - bar.low, bar.high - bar.low, "candle_range_non_positive")

    def _range_width_pct(self, bars: list[KlineBar], params: dict[str, Any]) -> Decimal:
        high = self._rolling_high(bars, params)
        low = self._rolling_low(bars, params)
        return _safe_div(high - low, _latest(bars).close, "latest_close_non_positive")

    def _volatility_ratio(self, bars: list[KlineBar], params: dict[str, Any]) -> Decimal:
        numerator = self._realized_vol_pct(bars, {"window": _positive_int(params, "short_window")})
        denominator = self._realized_vol_pct(bars, {"window": _positive_int(params, "long_window")})
        return _safe_div(numerator, denominator, "long_volatility_non_positive")

    @staticmethod
    def _latest_close_return_pct(bars: list[KlineBar], _params: dict[str, Any]) -> Decimal:
        _require_count(bars, 2)
        return _safe_div(bars[-1].close - bars[-2].close, bars[-2].close, "previous_close_non_positive")

    @staticmethod
    def _latest_body_return_pct(bars: list[KlineBar], _params: dict[str, Any]) -> Decimal:
        bar = _latest(bars)
        return _safe_div(bar.close - bar.open, bar.open, "latest_open_non_positive")

    def _latest_abs_body_return_pct(self, bars: list[KlineBar], params: dict[str, Any]) -> Decimal:
        return abs(self._latest_body_return_pct(bars, params))

    @staticmethod
    def _latest_close_near_high_distance_pct(bars: list[KlineBar], _params: dict[str, Any]) -> Decimal:
        bar = _latest(bars)
        return _safe_div(bar.high - bar.close, bar.high, "latest_high_non_positive")

    @staticmethod
    def _latest_close_near_low_distance_pct(bars: list[KlineBar], _params: dict[str, Any]) -> Decimal:
        bar = _latest(bars)
        return _safe_div(bar.close - bar.low, bar.low, "latest_low_non_positive")

    def _consecutive_large_bear_body_count(self, bars: list[KlineBar], params: dict[str, Any]) -> Decimal:
        return Decimal(_consecutive_count(_tail(bars, _positive_int(params, "window")), lambda bar: self._is_large_body(bar, bars) and bar.close < bar.open))

    def _consecutive_large_bull_body_count(self, bars: list[KlineBar], params: dict[str, Any]) -> Decimal:
        return Decimal(_consecutive_count(_tail(bars, _positive_int(params, "window")), lambda bar: self._is_large_body(bar, bars) and bar.close > bar.open))

    def _large_body_same_direction_count(self, bars: list[KlineBar], params: dict[str, Any]) -> Decimal:
        window = _tail(bars, _positive_int(params, "window"))
        bull = sum(1 for bar in window if self._is_large_body(bar, bars) and bar.close > bar.open)
        bear = sum(1 for bar in window if self._is_large_body(bar, bars) and bar.close < bar.open)
        return Decimal(max(bull, bear))

    @staticmethod
    def _cumulative_return_pct(bars: list[KlineBar], params: dict[str, Any]) -> Decimal:
        window = _positive_int(params, "window")
        target = _tail(bars, window + 1)
        return _safe_div(target[-1].close - target[0].close, target[0].close, "first_close_non_positive")

    @staticmethod
    def _max_single_body_return_pct(bars: list[KlineBar], params: dict[str, Any]) -> Decimal:
        return max(_body_return(bar) for bar in _tail(bars, _positive_int(params, "window")))

    @staticmethod
    def _min_single_body_return_pct(bars: list[KlineBar], params: dict[str, Any]) -> Decimal:
        return min(_body_return(bar) for bar in _tail(bars, _positive_int(params, "window")))

    @staticmethod
    def _from_intrabar_high_reversal_pct(bars: list[KlineBar], _params: dict[str, Any]) -> Decimal:
        bar = _latest(bars)
        return _safe_div(bar.high - bar.close, bar.high, "latest_high_non_positive")

    @staticmethod
    def _from_intrabar_low_recovery_pct(bars: list[KlineBar], _params: dict[str, Any]) -> Decimal:
        bar = _latest(bars)
        return _safe_div(bar.close - bar.low, bar.low, "latest_low_non_positive")

    @staticmethod
    def _two_bar_opposite_reversal_pct(bars: list[KlineBar], _params: dict[str, Any]) -> Decimal:
        _require_count(bars, 2)
        previous = bars[-2]
        current = bars[-1]
        previous_body = _body_return(previous)
        current_body = _body_return(current)
        if previous_body == 0 or current_body == 0 or (previous_body > 0) == (current_body > 0):
            return Decimal("0")
        return min(abs(previous_body), abs(current_body))

    @staticmethod
    def _higher_high_count(bars: list[KlineBar], params: dict[str, Any]) -> Decimal:
        blocks = _fixed_blocks(bars, params)
        highs = [max(bar.high for bar in block) for block in blocks]
        return Decimal(sum(1 for idx in range(1, len(highs)) if highs[idx] > highs[idx - 1]))

    @staticmethod
    def _higher_low_count(bars: list[KlineBar], params: dict[str, Any]) -> Decimal:
        blocks = _fixed_blocks(bars, params)
        lows = [min(bar.low for bar in block) for block in blocks]
        return Decimal(sum(1 for idx in range(1, len(lows)) if lows[idx] > lows[idx - 1]))

    @staticmethod
    def _lower_high_count(bars: list[KlineBar], params: dict[str, Any]) -> Decimal:
        blocks = _fixed_blocks(bars, params)
        highs = [max(bar.high for bar in block) for block in blocks]
        return Decimal(sum(1 for idx in range(1, len(highs)) if highs[idx] < highs[idx - 1]))

    @staticmethod
    def _lower_low_count(bars: list[KlineBar], params: dict[str, Any]) -> Decimal:
        blocks = _fixed_blocks(bars, params)
        lows = [min(bar.low for bar in block) for block in blocks]
        return Decimal(sum(1 for idx in range(1, len(lows)) if lows[idx] < lows[idx - 1]))

    def _structure_zone_metric(self, bars: list[KlineBar], params: dict[str, Any]) -> Decimal | None:
        metric = str(params.get("metric") or "").strip()
        if not metric:
            raise FeatureCalculationError("feature_params_invalid", "参数 metric 不能为空")
        snapshot = _build_structure_snapshot(bars, params)
        latest_close = snapshot.latest_close
        support = snapshot.support
        resistance = snapshot.resistance
        if metric == "support_lower":
            return support.lower if support else None
        if metric == "support_upper":
            return support.upper if support else None
        if metric == "resistance_lower":
            return resistance.lower if resistance else None
        if metric == "resistance_upper":
            return resistance.upper if resistance else None
        if metric == "support_touch_count":
            return Decimal(support.touch_count if support else 0)
        if metric == "resistance_touch_count":
            return Decimal(resistance.touch_count if resistance else 0)
        if metric == "support_score":
            return support.score if support else Decimal("0")
        if metric == "resistance_score":
            return resistance.score if resistance else Decimal("0")
        if metric == "distance_to_support_upper_pct":
            return _safe_div(latest_close - support.upper, latest_close, "latest_close_non_positive") if support else None
        if metric == "distance_to_resistance_lower_pct":
            return _safe_div(resistance.lower - latest_close, latest_close, "latest_close_non_positive") if resistance else None
        if metric == "range_position_pct":
            if support is None or resistance is None or support.upper >= resistance.lower:
                return None
            return _safe_div(latest_close - support.upper, resistance.lower - support.upper, "structure_range_width_non_positive")
        if metric == "range_width_pct":
            if support is None or resistance is None or support.upper >= resistance.lower:
                return None
            return _safe_div(resistance.lower - support.upper, latest_close, "latest_close_non_positive")
        if metric == "breakout_above_resistance_pct":
            return _safe_div(latest_close - resistance.upper, latest_close, "latest_close_non_positive") if resistance else None
        if metric == "breakdown_below_support_pct":
            return _safe_div(support.lower - latest_close, latest_close, "latest_close_non_positive") if support else None
        raise FeatureCalculationError("feature_params_invalid", f"不支持的 structure metric：{metric}")

    def _bars_since_rolling_high(self, bars: list[KlineBar], params: dict[str, Any]) -> list[KlineBar]:
        window_bars = _window_for_reference(bars, params)
        high = max(bar.high for bar in window_bars)
        index = max(idx for idx, bar in enumerate(window_bars) if bar.high == high)
        return window_bars[index:]

    def _is_large_body(self, bar: KlineBar, all_bars: list[KlineBar]) -> bool:
        body_abs = abs(_body_return(bar))
        history = _tail(all_bars, min(len(all_bars), 60))
        median_body = median(abs(_body_return(item)) for item in history)
        threshold = max(Decimal("0.018"), Decimal("1.2") * Decimal(str(median_body)))
        return body_abs >= threshold

    @classmethod
    def _failed(cls, error_code: str, error_message: str) -> CalculatorOutput:
        return CalculatorOutput.failed(
            output_schema_version=cls.metadata.output_schema_version,
            error_code=error_code,
            error_message=error_message,
        )


class FeatureCalculationError(Exception):
    def __init__(self, error_code: str, message: str) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.message = message


def _bars_for_timeframe(market_snapshot: dict[str, Any], timeframe: str) -> list[KlineBar]:
    raw_bars = market_snapshot.get(timeframe)
    if not isinstance(raw_bars, Sequence) or isinstance(raw_bars, str | bytes):
        raise FeatureCalculationError("feature_timeframe_missing", f"缺少 {timeframe} K 线窗口")
    bars: list[KlineBar] = []
    for raw in raw_bars:
        if not isinstance(raw, Mapping):
            raise FeatureCalculationError("feature_kline_payload_invalid", "K 线输入格式非法")
        bars.append(
            KlineBar(
                open_time_utc=str(raw.get("open_time_utc")),
                close_time_utc=str(raw.get("close_time_utc")),
                open=_decimal(raw.get("open"), "open"),
                high=_decimal(raw.get("high"), "high"),
                low=_decimal(raw.get("low"), "low"),
                close=_decimal(raw.get("close"), "close"),
                volume=_decimal(raw.get("volume", "0"), "volume"),
            )
        )
    if not bars:
        raise FeatureCalculationError("feature_kline_window_empty", "K 线窗口为空")
    return bars


def _decimal(value: Any, field_name: str) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise FeatureCalculationError("feature_kline_value_invalid", f"K 线字段 {field_name} 不是合法 Decimal") from exc
    if not result.is_finite():
        raise FeatureCalculationError("feature_kline_value_invalid", f"K 线字段 {field_name} 必须是有限 Decimal")
    return result


def _positive_int(params: dict[str, Any], field_name: str) -> int:
    try:
        value = int(params[field_name])
    except (KeyError, TypeError, ValueError) as exc:
        raise FeatureCalculationError("feature_params_invalid", f"参数 {field_name} 必须是正整数") from exc
    if value <= 0:
        raise FeatureCalculationError("feature_params_invalid", f"参数 {field_name} 必须是正整数")
    return value


def _require_count(bars: Sequence[KlineBar], count: int) -> None:
    if len(bars) < count:
        raise FeatureCalculationError("feature_insufficient_window", f"K 线数量不足，至少需要 {count} 根")


def _tail(bars: list[KlineBar], count: int) -> list[KlineBar]:
    _require_count(bars, count)
    return bars[-count:]


def _fixed_blocks(bars: list[KlineBar], params: dict[str, Any]) -> list[list[KlineBar]]:
    window = _positive_int(params, "window")
    block_size = _positive_int(params, "block_size")
    if window % block_size != 0:
        raise FeatureCalculationError("feature_params_invalid", "window 必须能被 block_size 整除")
    target = _tail(bars, window)
    return [target[idx : idx + block_size] for idx in range(0, len(target), block_size)]


def _latest(bars: list[KlineBar]) -> KlineBar:
    _require_count(bars, 1)
    return bars[-1]


def _field_value(bar: KlineBar, field_name: Any) -> Decimal:
    if field_name not in {"open", "high", "low", "close"}:
        raise FeatureCalculationError("feature_params_invalid", "price_field 只支持 open/high/low/close")
    return getattr(bar, str(field_name))


def _window_for_reference(bars: list[KlineBar], params: dict[str, Any]) -> list[KlineBar]:
    source = bars[:-1] if bool(params.get("exclude_latest")) else bars
    return _tail(source, _positive_int(params, "window"))


def _mean(values: Sequence[Decimal]) -> Decimal:
    if not values:
        raise FeatureCalculationError("feature_empty_calculation_window", "计算窗口为空")
    return sum(values, Decimal("0")) / Decimal(len(values))


def _safe_div(numerator: Decimal, denominator: Decimal, error_code: str) -> Decimal:
    if denominator <= 0:
        raise FeatureCalculationError(error_code, "计算分母必须大于 0")
    return numerator / denominator


def _consecutive_count(bars: list[KlineBar], predicate: Callable[[KlineBar], bool]) -> int:
    count = 0
    for bar in reversed(bars):
        if not predicate(bar):
            break
        count += 1
    return count


def _close_location(bar: KlineBar) -> Decimal:
    return _safe_div(bar.close - bar.low, bar.high - bar.low, "candle_range_non_positive")


def _true_range(bar: KlineBar, previous_close: Decimal) -> Decimal:
    return max(bar.high - bar.low, abs(bar.high - previous_close), abs(bar.low - previous_close))


def _close_returns(bars: list[KlineBar]) -> list[Decimal]:
    _require_count(bars, 2)
    returns: list[Decimal] = []
    for idx in range(1, len(bars)):
        returns.append(_safe_div(bars[idx].close - bars[idx - 1].close, bars[idx - 1].close, "previous_close_non_positive"))
    return returns


def _population_stddev(values: Sequence[Decimal]) -> Decimal:
    mean = _mean(values)
    variance = sum((value - mean) ** 2 for value in values) / Decimal(len(values))
    return variance.sqrt()


def _atr_pct_at(bars: list[KlineBar], window: int) -> Decimal:
    target = _tail(bars, window + 1)
    true_ranges = [_true_range(target[idx], target[idx - 1].close) for idx in range(1, len(target))]
    return _safe_div(_mean(true_ranges), target[-1].close, "latest_close_non_positive")


def _realized_vol_at(bars: list[KlineBar], window: int) -> Decimal:
    return _population_stddev(_close_returns(_tail(bars, window + 1)))


def _body_return(bar: KlineBar) -> Decimal:
    return _safe_div(bar.close - bar.open, bar.open, "bar_open_non_positive")


def _build_structure_snapshot(bars: list[KlineBar], params: dict[str, Any]) -> StructureSnapshot:
    window = _positive_int(params, "window")
    source = _tail(bars, window)
    latest_close = source[-1].close
    reference = source[:-1]
    swing_left_right = _positive_int(params, "swing_left_right")
    if len(reference) < swing_left_right * 2 + 1:
        raise FeatureCalculationError("structure_insufficient_reference_window", "结构参考窗口不足")
    half_width = _structure_zone_half_width(source, params)
    min_touch_count = int(params.get("min_touch_count") or 1)
    min_zone_score = Decimal(str(params.get("min_zone_score", "0")))
    support_zones = _structure_zones(
        reference=reference,
        side="support",
        swing_left_right=swing_left_right,
        half_width_pct=half_width,
        params=params,
    )
    resistance_zones = _structure_zones(
        reference=reference,
        side="resistance",
        swing_left_right=swing_left_right,
        half_width_pct=half_width,
        params=params,
    )
    support = _nearest_support(
        zones=[zone for zone in support_zones if zone.touch_count >= min_touch_count and zone.score >= min_zone_score],
        latest_close=latest_close,
    )
    resistance = _nearest_resistance(
        zones=[zone for zone in resistance_zones if zone.touch_count >= min_touch_count and zone.score >= min_zone_score],
        latest_close=latest_close,
    )
    return StructureSnapshot(latest_close=latest_close, support=support, resistance=resistance)


def _structure_zone_half_width(bars: list[KlineBar], params: dict[str, Any]) -> Decimal:
    default_min_half_width_pct = Decimal(str(params.get("default_min_half_width_pct", "0.006")))
    ranges = [_safe_div(bar.high - bar.low, bar.close, "latest_close_non_positive") for bar in bars]
    return max(default_min_half_width_pct, Decimal(str(median(ranges))))


def _structure_zones(
    *,
    reference: list[KlineBar],
    side: str,
    swing_left_right: int,
    half_width_pct: Decimal,
    params: dict[str, Any],
) -> list[StructureZone]:
    candidates = _swing_candidates(reference=reference, side=side, swing_left_right=swing_left_right)
    if not candidates:
        return []
    clusters: list[list[tuple[int, Decimal]]] = []
    for candidate in sorted(candidates, key=lambda item: item[1]):
        placed = False
        for cluster in clusters:
            center = Decimal(str(median([price for _, price in cluster])))
            if abs(candidate[1] - center) / center <= half_width_pct:
                cluster.append(candidate)
                placed = True
                break
        if not placed:
            clusters.append([candidate])
    zones: list[StructureZone] = []
    for cluster in clusters:
        prices = [price for _, price in cluster]
        center = Decimal(str(median(prices)))
        lower = min(prices) * (Decimal("1") - half_width_pct)
        upper = max(prices) * (Decimal("1") + half_width_pct)
        touch_count, avg_reaction, last_touch_index = _zone_touch_stats(
            reference=reference,
            side=side,
            lower=lower,
            upper=upper,
            params=params,
        )
        score = _zone_score(
            touch_count=touch_count,
            avg_reaction=avg_reaction,
            last_touch_index=last_touch_index,
            reference_count=len(reference),
            params=params,
        )
        zones.append(
            StructureZone(
                lower=lower,
                upper=upper,
                center=center,
                touch_count=touch_count,
                score=score,
                last_touch_index=last_touch_index,
            )
        )
    return zones


def _swing_candidates(*, reference: list[KlineBar], side: str, swing_left_right: int) -> list[tuple[int, Decimal]]:
    candidates: list[tuple[int, Decimal]] = []
    for idx in range(swing_left_right, len(reference) - swing_left_right):
        bar = reference[idx]
        left = reference[idx - swing_left_right : idx]
        right = reference[idx + 1 : idx + 1 + swing_left_right]
        if side == "support":
            if bar.low <= min(item.low for item in left) and bar.low <= min(item.low for item in right):
                candidates.append((idx, bar.low))
        elif side == "resistance":
            if bar.high >= max(item.high for item in left) and bar.high >= max(item.high for item in right):
                candidates.append((idx, bar.high))
        else:
            raise FeatureCalculationError("feature_params_invalid", "structure side 只支持 support/resistance")
    return candidates


def _zone_touch_stats(
    *,
    reference: list[KlineBar],
    side: str,
    lower: Decimal,
    upper: Decimal,
    params: dict[str, Any],
) -> tuple[int, Decimal, int]:
    confirmation_window = int(params.get("confirmation_window") or 3)
    min_reaction_pct = Decimal(str(params.get("min_reaction_pct", "0.015")))
    reactions: list[Decimal] = []
    last_touch_index = -1
    for idx, bar in enumerate(reference):
        future = reference[idx + 1 : idx + 1 + confirmation_window]
        if not future:
            continue
        if side == "support" and lower <= bar.low <= upper:
            reaction = _safe_div(max(item.close for item in future) - bar.low, bar.low, "support_touch_low_non_positive")
            if reaction >= min_reaction_pct:
                reactions.append(reaction)
                last_touch_index = idx
        if side == "resistance" and lower <= bar.high <= upper:
            reaction = _safe_div(bar.high - min(item.close for item in future), bar.high, "resistance_touch_high_non_positive")
            if reaction >= min_reaction_pct:
                reactions.append(reaction)
                last_touch_index = idx
    return len(reactions), _mean(reactions) if reactions else Decimal("0"), last_touch_index


def _zone_score(
    *,
    touch_count: int,
    avg_reaction: Decimal,
    last_touch_index: int,
    reference_count: int,
    params: dict[str, Any],
) -> Decimal:
    if touch_count <= 0 or last_touch_index < 0 or reference_count <= 1:
        return Decimal("0")
    min_reaction_pct = Decimal(str(params.get("min_reaction_pct", "0.015")))
    touch_count_score = min(Decimal(touch_count), Decimal("5")) / Decimal("5")
    recency_score = Decimal(last_touch_index) / Decimal(reference_count - 1)
    reaction_score = min(_safe_div(avg_reaction, min_reaction_pct * Decimal("3"), "min_reaction_non_positive"), Decimal("1"))
    return Decimal("0.45") * touch_count_score + Decimal("0.30") * recency_score + Decimal("0.25") * reaction_score


def _nearest_support(*, zones: list[StructureZone], latest_close: Decimal) -> StructureZone | None:
    candidates = [zone for zone in zones if zone.upper <= latest_close or zone.lower <= latest_close <= zone.upper]
    if not candidates:
        return None
    return min(candidates, key=lambda zone: abs(latest_close - zone.upper))


def _nearest_resistance(*, zones: list[StructureZone], latest_close: Decimal) -> StructureZone | None:
    candidates = [zone for zone in zones if zone.lower >= latest_close or zone.lower <= latest_close <= zone.upper]
    if not candidates:
        return None
    return min(candidates, key=lambda zone: abs(zone.lower - latest_close))
