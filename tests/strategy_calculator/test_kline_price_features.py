from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from apps.strategy_calculator.contracts import CalculationStatus, CalculatorInput, CalculatorType
from apps.strategy_calculator.feature_layer import KlinePriceFeatureCalculator
from apps.strategy_calculator.utils import thaw_value


def _bars(count: int, *, start_close: Decimal = Decimal("100"), step: Decimal = Decimal("1")) -> list[dict[str, str]]:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    bars: list[dict[str, str]] = []
    for idx in range(count):
        close = start_close + step * Decimal(idx)
        open_price = close - Decimal("0.5")
        high = close + Decimal("1")
        low = close - Decimal("1")
        open_time = start + timedelta(hours=4 * idx)
        bars.append(
            {
                "open_time_utc": open_time.isoformat(),
                "close_time_utc": (open_time + timedelta(hours=4)).isoformat(),
                "open": str(open_price),
                "high": str(high),
                "low": str(low),
                "close": str(close),
                "volume": str(Decimal("10") + Decimal(idx)),
            }
        )
    return bars


def _input(params: dict[str, object], *, bars_4h: list[dict[str, str]] | None = None) -> CalculatorInput:
    return CalculatorInput(
        calculator_type=CalculatorType.FEATURE_LAYER,
        input_schema_version="1.0",
        output_schema_version="1.0",
        business_time_utc=datetime(2026, 1, 2, tzinfo=UTC),
        frozen_params=params,
        values={
            "market_snapshot": {
                "analysis_close_time_utc": datetime(2026, 1, 2, tzinfo=UTC).isoformat(),
                "4h": bars_4h or _bars(10),
                "1d": _bars(10),
            }
        },
    )


def _value(params: dict[str, object], *, bars_4h: list[dict[str, str]] | None = None) -> Decimal:
    output = KlinePriceFeatureCalculator().calculate(_input(params, bars_4h=bars_4h))
    assert output.calculation_status == CalculationStatus.SUCCEEDED
    return thaw_value(output.values)["value"]


def test_kline_price_features_calculates_sma_and_distance() -> None:
    sma = _value({"operation": "sma", "timeframe": "4h", "window": 3})
    distance = _value({"operation": "close_vs_sma_pct", "timeframe": "4h", "window": 3})
    volume_sma = _value({"operation": "volume_sma", "timeframe": "4h", "window": 3})

    assert sma == Decimal("108")
    assert distance == Decimal("1") / Decimal("108")
    assert volume_sma == Decimal("18")


def test_kline_price_features_calculates_slope_and_return_delta() -> None:
    slope = _value({"operation": "slope_sma", "timeframe": "4h", "window": 3, "lag": 2})
    delta = _value({"operation": "return_delta_pct", "timeframe": "4h", "window": 3})

    assert slope == Decimal("2") / Decimal("106")
    assert delta == (Decimal("109") - Decimal("107")) / Decimal("107") - (Decimal("106") - Decimal("104")) / Decimal("104")


def test_kline_price_features_calculates_atr_and_candle_shape() -> None:
    atr = _value({"operation": "atr", "timeframe": "4h", "window": 3})
    atr_pct = _value({"operation": "atr_pct", "timeframe": "4h", "window": 3})
    body_ratio = _value({"operation": "candle_body_ratio_latest", "timeframe": "4h"})

    assert atr == Decimal("2")
    assert atr_pct == Decimal("2") / Decimal("109")
    assert body_ratio == Decimal("0.5") / Decimal("2")


def test_kline_price_features_calculates_block_structure_counts() -> None:
    bars = _bars(60, start_close=Decimal("100"), step=Decimal("0"))
    for idx in range(20):
        bars[idx]["high"] = "105"
        bars[idx]["low"] = "95"
    for idx in range(20, 40):
        bars[idx]["high"] = "110"
        bars[idx]["low"] = "97"
    for idx in range(40, 60):
        bars[idx]["high"] = "115"
        bars[idx]["low"] = "99"

    higher_high = _value({"operation": "higher_high_count", "timeframe": "4h", "window": 60, "block_size": 20}, bars_4h=bars)
    higher_low = _value({"operation": "higher_low_count", "timeframe": "4h", "window": 60, "block_size": 20}, bars_4h=bars)
    lower_high = _value({"operation": "lower_high_count", "timeframe": "4h", "window": 60, "block_size": 20}, bars_4h=bars)

    assert higher_high == Decimal("2")
    assert higher_low == Decimal("2")
    assert lower_high == Decimal("0")


def test_kline_price_features_calculates_risk_state_large_body_count() -> None:
    bars = _bars(20, start_close=Decimal("100"), step=Decimal("0"))
    bars[-3]["open"] = "100"
    bars[-3]["close"] = "97"
    bars[-2]["open"] = "97"
    bars[-2]["close"] = "94"
    bars[-1]["open"] = "94"
    bars[-1]["close"] = "91"

    count = _value(
        {"operation": "consecutive_large_bear_body_count", "timeframe": "4h", "window": 20},
        bars_4h=bars,
    )

    assert count == Decimal("3")


def test_kline_price_features_calculates_structure_zone_metrics() -> None:
    bars = _bars(20, start_close=Decimal("100"), step=Decimal("0.2"))
    bars[4]["low"] = "95"
    bars[5]["close"] = "101"
    bars[7]["high"] = "110"
    bars[8]["close"] = "104"
    bars[10]["low"] = "96"
    bars[11]["close"] = "101"
    bars[14]["high"] = "111"
    bars[15]["close"] = "104"
    bars[-1]["close"] = "104"

    common = {
        "operation": "structure_zone_metric",
        "timeframe": "4h",
        "window": 20,
        "swing_left_right": 1,
        "default_min_half_width_pct": "0.02",
        "confirmation_window": 1,
        "min_reaction_pct": "0.01",
        "min_touch_count": 1,
        "min_zone_score": "0",
    }
    support_touch_count = _value({**common, "metric": "support_touch_count"}, bars_4h=bars)
    resistance_touch_count = _value({**common, "metric": "resistance_touch_count"}, bars_4h=bars)
    range_position = _value({**common, "metric": "range_position_pct", "nullable": True}, bars_4h=bars)

    assert support_touch_count >= Decimal("2")
    assert resistance_touch_count >= Decimal("2")
    assert range_position is not None


def test_kline_price_features_fails_when_window_is_insufficient() -> None:
    output = KlinePriceFeatureCalculator().calculate(
        _input({"operation": "sma", "timeframe": "4h", "window": 20})
    )

    assert output.calculation_status == CalculationStatus.FAILED
    assert output.error_code == "feature_insufficient_window"
