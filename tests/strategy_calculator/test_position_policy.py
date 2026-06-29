from __future__ import annotations

from apps.strategy_calculator.contracts import CalculatorInput, CalculatorType
from apps.strategy_calculator.decision_policy import PositionPolicyCalculator
from apps.strategy_calculator.utils import thaw_value


def _input(
    *,
    direction: str,
    strength: str = "0.80",
    confidence: str = "0.60",
    params: dict[str, object] | None = None,
) -> CalculatorInput:
    return CalculatorInput(
        calculator_type=CalculatorType.DECISION_POLICY,
        input_schema_version="1.0",
        output_schema_version="1.0",
        frozen_params=params or {},
        values={
            "strategy_direction": direction,
            "strategy_strength": strength,
            "strategy_confidence": confidence,
        },
    )


def test_position_policy_maps_bullish_signal_to_positive_target_position() -> None:
    output = PositionPolicyCalculator().calculate(_input(direction="bullish", strength="0.80", confidence="0.60"))

    values = thaw_value(output.values)
    assert values["target_intent"] == "TARGET_POSITION"
    assert values["target_position_ratio"] == "0.1667"
    assert values["target_confidence"] == "0.60"


def test_position_policy_maps_bearish_signal_to_negative_target_position() -> None:
    output = PositionPolicyCalculator().calculate(_input(direction="bearish", strength="0.80", confidence="0.60"))

    values = thaw_value(output.values)
    assert values["target_intent"] == "TARGET_POSITION"
    assert values["target_position_ratio"] == "-0.1667"


def test_position_policy_returns_no_trade_for_neutral_or_weak_signal() -> None:
    neutral = PositionPolicyCalculator().calculate(_input(direction="neutral"))
    weak = PositionPolicyCalculator().calculate(_input(direction="bullish", strength="0.54", confidence="0.90"))

    assert thaw_value(neutral.values)["target_intent"] == "NO_TRADE"
    assert thaw_value(weak.values)["target_intent"] == "NO_TRADE"


def test_position_policy_rejects_invalid_direction_and_invalid_params() -> None:
    invalid_direction = PositionPolicyCalculator().calculate(_input(direction="enter_long"))
    invalid_params = PositionPolicyCalculator().calculate(
        _input(direction="bullish", params={"strength_mapping_method": "stepped"})
    )

    assert invalid_direction.error_code == "position_policy_direction_invalid"
    assert invalid_params.error_code == "position_policy_params_invalid"
