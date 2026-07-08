from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from apps.strategy_calculator.contracts import CalculationStatus, CalculatorInput, CalculatorType
from apps.strategy_calculator.feature_layer import PivotSupportResistanceFeatureCalculator
from apps.strategy_calculator.utils import thaw_value


def _bars(count: int, *, start_close: Decimal = Decimal("100")) -> list[dict[str, str]]:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    bars: list[dict[str, str]] = []
    for idx in range(count):
        close = start_close + Decimal(idx % 3) / Decimal("10")
        open_time = start + timedelta(hours=4 * idx)
        bars.append(
            {
                "open_time_utc": open_time.isoformat(),
                "close_time_utc": (open_time + timedelta(hours=4)).isoformat(),
                "open": str(close),
                "high": str(close + Decimal("2")),
                "low": str(close - Decimal("2")),
                "close": str(close),
                "volume": "10",
            }
        )
    return bars


def _input(params: dict[str, object], bars_4h: list[dict[str, str]]) -> CalculatorInput:
    return CalculatorInput(
        calculator_type=CalculatorType.FEATURE_LAYER,
        input_schema_version="1.0",
        output_schema_version="1.0",
        business_time_utc=datetime(2026, 1, 2, tzinfo=UTC),
        frozen_params=params,
        values={
            "market_snapshot": {
                "analysis_close_time_utc": datetime(2026, 1, 2, tzinfo=UTC).isoformat(),
                "4h": bars_4h,
                "1d": bars_4h,
            }
        },
    )


def _value(params: dict[str, object], bars_4h: list[dict[str, str]]) -> object:
    output = PivotSupportResistanceFeatureCalculator().calculate(_input(params, bars_4h))
    assert output.calculation_status == CalculationStatus.SUCCEEDED
    return thaw_value(output.values)["value"]


def _common_params(*, side: str, metric: str) -> dict[str, object]:
    return {
        "operation": "pivot_zone_metric",
        "timeframe": "4h",
        "window": 30,
        "side": side,
        "metric": metric,
        "pivot_left": 1,
        "pivot_right": 1,
        "reaction_window": 2,
        "atr_window": 3,
        "min_reaction_atr_multiple": "0.5",
        "min_reaction_pct": "0.04",
        "min_spacing_bars": 2,
        "cluster_atr_multiple": "0.5",
        "cluster_pct": "0.02",
        "max_zone_atr_multiple": "2",
        "max_zone_width_pct": "0.04",
        "min_zone_atr_multiple": "0.2",
        "min_zone_width_pct": "0.005",
        "min_touch_count": 1,
        "confirm_bars": 2,
        "invalidation_bars": 3,
        "confirm_atr_multiple": "0.5",
        "confirm_pct": "0.005",
    }


def test_pivot_support_resistance_finds_narrow_support_zone() -> None:
    bars = _bars(30)
    bars[5]["low"] = "95"
    bars[6]["close"] = "101"
    bars[12]["low"] = "96"
    bars[13]["close"] = "102"
    bars[-1]["close"] = "104"
    bars[-1]["low"] = "103"

    lower = _value(_common_params(side="support", metric="lower"), bars)
    upper = _value(_common_params(side="support", metric="upper"), bars)
    width_pct = _value(_common_params(side="support", metric="width_pct"), bars)
    touch_count = _value(_common_params(side="support", metric="touch_count"), bars)
    status = _value(_common_params(side="support", metric="status"), bars)

    assert isinstance(lower, Decimal)
    assert isinstance(upper, Decimal)
    assert lower <= Decimal("95") <= upper
    assert lower <= Decimal("96") <= upper
    assert width_pct <= Decimal("0.04")
    assert touch_count >= Decimal("2")
    assert status == "active"


def test_pivot_support_resistance_finds_resistance_zone() -> None:
    bars = _bars(30)
    bars[8]["high"] = "110"
    bars[9]["close"] = "103"
    bars[16]["high"] = "111"
    bars[17]["close"] = "104"
    bars[-1]["close"] = "104"

    lower = _value(_common_params(side="resistance", metric="lower"), bars)
    upper = _value(_common_params(side="resistance", metric="upper"), bars)
    distance = _value(_common_params(side="resistance", metric="distance_pct"), bars)
    status = _value(_common_params(side="resistance", metric="status"), bars)

    assert isinstance(lower, Decimal)
    assert isinstance(upper, Decimal)
    assert lower <= Decimal("110") <= upper
    assert lower <= Decimal("111") <= upper
    assert distance > Decimal("0")
    assert status == "active"


def test_pivot_support_resistance_returns_empty_values_when_no_zone() -> None:
    bars = _bars(30)

    lower = _value(_common_params(side="support", metric="lower"), bars)
    touch_count = _value(_common_params(side="support", metric="touch_count"), bars)
    status = _value(_common_params(side="support", metric="status"), bars)

    assert lower is None
    assert touch_count == Decimal("0")
    assert status == "none"
