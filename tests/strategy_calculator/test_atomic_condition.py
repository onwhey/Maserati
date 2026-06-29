from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from apps.strategy_calculator.atomic_signal import AtomicConditionCalculator
from apps.strategy_calculator.contracts import CalculationStatus, CalculatorInput, CalculatorType


def calculation_input(*, params: dict, feature_values: dict, default_direction: str = "bullish") -> CalculatorInput:
    return CalculatorInput(
        calculator_type=CalculatorType.ATOMIC_SIGNAL,
        input_schema_version="1.0",
        output_schema_version="1.0",
        business_time_utc=datetime(2026, 1, 1, tzinfo=UTC),
        frozen_params=params,
        values={
            "signal_code": "test_signal",
            "default_direction": default_direction,
            "feature_values": feature_values,
        },
    )


def test_atomic_condition_outputs_default_direction_when_all_conditions_match() -> None:
    output = AtomicConditionCalculator().calculate(
        calculation_input(
            params={
                "conditions": [
                    {"feature_code": "return_pct_1d_7", "operator": "gte", "value": "0.03"},
                    {"feature_code": "return_delta_pct_1d_7", "operator": "gte", "value": "0.015"},
                ],
                "label_zh": "1d 多头推进增强",
            },
            feature_values={
                "return_pct_1d_7": {"feature_value_id": 1, "value": "0.05", "value_type": "decimal"},
                "return_delta_pct_1d_7": {"feature_value_id": 2, "value": "0.02", "value_type": "decimal"},
            },
        )
    )

    assert output.calculation_status == CalculationStatus.SUCCEEDED
    assert output.values["value"] is True
    assert output.values["direction"] == "bullish"
    assert output.values["strength"] == Decimal("1")
    assert output.values["confidence"] is None
    assert output.evidence_items[0]["condition_result"] is True


def test_atomic_condition_null_numeric_condition_is_false_but_valid() -> None:
    output = AtomicConditionCalculator().calculate(
        calculation_input(
            params={
                "conditions": [{"feature_code": "structure_major_range_width_pct_1d_365", "operator": "gt", "value": "0"}],
                "label_zh": "1d 大区间宽度有效",
            },
            feature_values={
                "structure_major_range_width_pct_1d_365": {
                    "feature_value_id": 1,
                    "value": None,
                    "value_type": "decimal",
                },
            },
            default_direction="neutral",
        )
    )

    assert output.calculation_status == CalculationStatus.SUCCEEDED
    assert output.values["value"] is False
    assert output.values["direction"] == "neutral"
    assert output.values["strength"] == Decimal("0")


def test_atomic_condition_is_null_condition_matches_nullable_feature() -> None:
    output = AtomicConditionCalculator().calculate(
        calculation_input(
            params={
                "conditions": [{"feature_code": "structure_major_support_upper_1d_365", "operator": "is_null"}],
                "label_zh": "1d 大结构缺少支撑区",
            },
            feature_values={
                "structure_major_support_upper_1d_365": {
                    "feature_value_id": 1,
                    "value": None,
                    "value_type": "decimal",
                },
            },
            default_direction="neutral",
        )
    )

    assert output.calculation_status == CalculationStatus.SUCCEEDED
    assert output.values["value"] is True
    assert output.values["direction"] == "neutral"
    assert output.values["strength"] == Decimal("1")


def test_atomic_condition_right_feature_null_makes_numeric_condition_false() -> None:
    output = AtomicConditionCalculator().calculate(
        calculation_input(
            params={
                "conditions": [
                    {
                        "feature_code": "structure_major_support_upper_1d_365",
                        "operator": "gte",
                        "right_feature_code": "structure_major_resistance_lower_1d_365",
                    }
                ],
                "label_zh": "1d 大结构边界异常",
            },
            feature_values={
                "structure_major_support_upper_1d_365": {
                    "feature_value_id": 1,
                    "value": "60000",
                    "value_type": "decimal",
                },
                "structure_major_resistance_lower_1d_365": {
                    "feature_value_id": 2,
                    "value": None,
                    "value_type": "decimal",
                },
            },
            default_direction="neutral",
        )
    )

    assert output.calculation_status == CalculationStatus.SUCCEEDED
    assert output.values["value"] is False
    assert output.values["strength"] == Decimal("0")


def test_atomic_condition_supports_right_feature_multiplier() -> None:
    output = AtomicConditionCalculator().calculate(
        calculation_input(
            params={
                "conditions": [
                    {
                        "feature_code": "candle_range_pct_4h_latest",
                        "operator": "gte",
                        "right_feature_code": "atr_pct_4h_14",
                        "right_multiplier": "2",
                    }
                ],
                "label_zh": "最新 4h K 线振幅明显大于常态",
            },
            feature_values={
                "candle_range_pct_4h_latest": {"feature_value_id": 1, "value": "0.08", "value_type": "decimal"},
                "atr_pct_4h_14": {"feature_value_id": 2, "value": "0.03", "value_type": "decimal"},
            },
            default_direction="neutral",
        )
    )

    assert output.calculation_status == CalculationStatus.SUCCEEDED
    assert output.values["value"] is True
    assert output.evidence_items[0]["conditions"][0]["right_value"] == "0.06"


def test_atomic_condition_json_risk_value_marks_high_severity() -> None:
    output = AtomicConditionCalculator().calculate(
        calculation_input(
            params={
                "conditions": [{"feature_code": "risk_latest_body_return_pct_4h", "operator": "lte", "value": "-0.04"}],
                "severity_conditions": [{"feature_code": "risk_latest_body_return_pct_4h", "operator": "lte", "value": "-0.07"}],
                "value_mode": "json",
                "base_severity": "elevated",
                "high_severity": "high",
                "json_payload": {
                    "risk_category": "long_exposure_risk",
                    "risk_direction": "downside",
                    "risk_severity": "none",
                },
                "label_zh": "下行冲击下的多头暴露风险",
            },
            feature_values={
                "risk_latest_body_return_pct_4h": {"feature_value_id": 1, "value": "-0.08", "value_type": "decimal"},
            },
            default_direction="neutral",
        )
    )

    assert output.calculation_status == CalculationStatus.SUCCEEDED
    assert output.values["value"]["condition_met"] is True
    assert output.values["value"]["risk_severity"] == "high"
    assert output.values["direction"] == "neutral"


def test_atomic_condition_json_value_can_include_feature_value_snapshot() -> None:
    output = AtomicConditionCalculator().calculate(
        calculation_input(
            params={
                "conditions": [{"feature_code": "structure_major_support_upper_1d_365", "operator": "is_not_null"}],
                "value_mode": "json",
                "json_payload": {"structure_signal_family": "zone_snapshot"},
                "include_feature_values": [
                    "structure_major_support_lower_1d_365",
                    "structure_major_support_upper_1d_365",
                ],
                "label_zh": "1d 大支撑区具备基本事实",
            },
            feature_values={
                "structure_major_support_lower_1d_365": {
                    "feature_value_id": 1,
                    "value": "49000",
                    "value_type": "decimal",
                },
                "structure_major_support_upper_1d_365": {
                    "feature_value_id": 2,
                    "value": "50000",
                    "value_type": "decimal",
                },
            },
            default_direction="neutral",
        )
    )

    assert output.calculation_status == CalculationStatus.SUCCEEDED
    assert output.values["value"]["condition_met"] is True
    assert output.values["value"]["feature_values"]["structure_major_support_lower_1d_365"]["value"] == "49000"
    assert output.values["value"]["feature_values"]["structure_major_support_upper_1d_365"]["feature_value_id"] == 2
