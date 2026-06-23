from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from apps.strategy_calculator.atomic_signal import FeatureCompareCalculator
from apps.strategy_calculator.contracts import CalculationStatus, CalculatorInput, CalculatorType


def calculation_input(*, left: str, right: str) -> CalculatorInput:
    return CalculatorInput(
        calculator_type=CalculatorType.ATOMIC_SIGNAL,
        input_schema_version="1.0",
        output_schema_version="1.0",
        business_time_utc=datetime(2026, 1, 1, tzinfo=UTC),
        frozen_params={
            "left_feature_code": "sma_4h_20",
            "operator": "gt",
            "right_feature_code": "sma_4h_60",
        },
        values={
            "signal_code": "sma_4h_20_above_sma_4h_60",
            "default_direction": "bullish",
            "feature_values": {
                "sma_4h_20": {"feature_value_id": 1, "value": left, "value_type": "decimal"},
                "sma_4h_60": {"feature_value_id": 2, "value": right, "value_type": "decimal"},
            },
        },
    )


def test_feature_compare_outputs_bullish_when_condition_matches() -> None:
    output = FeatureCompareCalculator().calculate(calculation_input(left="110", right="100"))

    assert output.calculation_status == CalculationStatus.SUCCEEDED
    assert output.values["value"] is True
    assert output.values["direction"] == "bullish"
    assert output.values["strength"] == Decimal("1")
    assert output.values["confidence"] is None


def test_feature_compare_outputs_neutral_when_condition_does_not_match() -> None:
    output = FeatureCompareCalculator().calculate(calculation_input(left="90", right="100"))

    assert output.calculation_status == CalculationStatus.SUCCEEDED
    assert output.values["value"] is False
    assert output.values["direction"] == "neutral"
    assert output.values["strength"] == Decimal("0")


def test_feature_compare_fails_without_declared_feature() -> None:
    source = calculation_input(left="110", right="100")
    broken = CalculatorInput(
        calculator_type=CalculatorType.ATOMIC_SIGNAL,
        input_schema_version="1.0",
        output_schema_version="1.0",
        business_time_utc=source.business_time_utc,
        frozen_params=source.frozen_params,
        values={
            "signal_code": "sma_4h_20_above_sma_4h_60",
            "default_direction": "bullish",
            "feature_values": {
                "sma_4h_20": {"feature_value_id": 1, "value": "110", "value_type": "decimal"},
            },
        },
    )

    output = FeatureCompareCalculator().calculate(broken)

    assert output.calculation_status == CalculationStatus.FAILED
    assert output.error_code == "right_feature_missing"
