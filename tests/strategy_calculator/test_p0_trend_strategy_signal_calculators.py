from __future__ import annotations

from apps.strategy_analysis.models import StrategySignalDirection
from apps.strategy_calculator.contracts import CalculatorInput, CalculatorType
from apps.strategy_calculator.strategy_signal import (
    LongPullbackSupportCalculator,
    LongTrendFollowingCalculator,
    ShortReboundPressureCalculator,
    ShortTrendFollowingCalculator,
)
from apps.strategy_calculator.utils import stable_hash, thaw_value


REQUIRED_DOMAIN_CODES = ("market_context", "trend", "momentum", "volatility", "structure", "risk_state")
PARAMS = {
    "min_strength": "0.55",
    "min_confidence": "0.55",
    "prediction_horizon": "next_1_to_3_closed_4h",
}


def domain_fact(
    domain_code: str,
    direction: str,
    state_code: str,
    *,
    strength: str = "0.80",
    value_id: int = 1,
    payload_summary: dict | None = None,
) -> dict:
    data = {
        "domain_signal_value_id": value_id,
        "domain_code": domain_code,
        "direction": direction,
        "state_code": state_code,
        "strength": strength,
        "coverage_ratio": "1",
        "agreement_ratio": "0.80",
        "definition_hash": f"hash_{domain_code}",
    }
    if payload_summary is not None:
        data["payload_summary"] = payload_summary
    return data


def calculator_input(strategy_code: str, domain_values: list[dict]) -> CalculatorInput:
    return CalculatorInput(
        calculator_type=CalculatorType.STRATEGY_SIGNAL,
        input_schema_version="1.0",
        output_schema_version="1.0",
        frozen_params=PARAMS,
        params_hash=stable_hash(PARAMS),
        values={
            "strategy_definition": {
                "strategy_code": strategy_code,
                "strategy_version": "v1",
                "definition_hash": f"hash_{strategy_code}",
                "allowed_domain_codes": list(REQUIRED_DOMAIN_CODES),
                "required_domain_codes": list(REQUIRED_DOMAIN_CODES),
                "uses_input_weights": False,
                "domain_input_weights": {},
                "prediction_horizon": "next_1_to_3_closed_4h",
            },
            "domain_values": domain_values,
        },
    )


def base_long_facts(*, risk_state: str = "risk_clear") -> list[dict]:
    return [
        domain_fact("market_context", "bullish", "market_context_bullish", value_id=1),
        domain_fact("trend", "bullish", "trend_1d_bullish_4h_aligned", value_id=2),
        domain_fact("momentum", "bullish", "momentum_bullish_strengthening", value_id=3),
        domain_fact("volatility", "neutral", "volatility_normal", value_id=4),
        domain_fact("structure", "bullish", "structure_major_breakout_up", value_id=5),
        domain_fact("risk_state", "neutral", risk_state, value_id=6),
    ]


def base_short_facts(*, risk_state: str = "risk_clear") -> list[dict]:
    return [
        domain_fact("market_context", "bearish", "market_context_bearish", value_id=1),
        domain_fact("trend", "bearish", "trend_1d_bearish_4h_aligned", value_id=2),
        domain_fact("momentum", "bearish", "momentum_bearish_strengthening", value_id=3),
        domain_fact("volatility", "neutral", "volatility_normal", value_id=4),
        domain_fact("structure", "bearish", "structure_major_breakdown_down", value_id=5),
        domain_fact("risk_state", "neutral", risk_state, value_id=6),
    ]


def test_long_trend_following_outputs_bullish_for_aligned_breakout() -> None:
    calculator = LongTrendFollowingCalculator()

    output = calculator.calculate(calculator_input("long_trend_following", base_long_facts()))
    values = thaw_value(output.values)

    assert values["direction"] == StrategySignalDirection.BULLISH
    assert values["prediction_horizon"] == "next_1_to_3_closed_4h"
    assert values["trade_price_condition"]["condition_type"] == "breakout_continuation_price_zone"
    assert values["aggregation_snapshot"]["final_direction"] == values["direction"]
    assert values["aggregation_snapshot"]["final_strength"] == str(values["strength"])
    assert values["aggregation_snapshot"]["final_confidence"] == str(values["confidence"])
    assert len(values["used_domain_signal_value_refs"]) == 6


def test_long_trend_following_neutralizes_high_risk() -> None:
    calculator = LongTrendFollowingCalculator()

    output = calculator.calculate(
        calculator_input("long_trend_following", base_long_facts(risk_state="risk_high_signal_unreliable"))
    )
    values = thaw_value(output.values)

    assert values["direction"] == StrategySignalDirection.NEUTRAL
    assert values["conflict_snapshot"]["has_conflict"] is True


def test_long_trend_following_keeps_trend_but_waits_support_when_minor_structure_conflicts() -> None:
    calculator = LongTrendFollowingCalculator()
    facts = base_long_facts()
    facts[4] = domain_fact(
        "structure",
        "neutral",
        "structure_major_upper_half_minor_conflicted",
        value_id=5,
        strength="0.55",
        payload_summary={"support_zone": {"lower": "60000", "upper": "61000"}},
    )

    output = calculator.calculate(calculator_input("long_trend_following", facts))
    values = thaw_value(output.values)

    assert values["direction"] == StrategySignalDirection.BULLISH
    assert values["trade_price_condition"]["condition_type"] == "trend_minor_conflict_support_price_zone"
    assert values["trade_price_condition"]["acceptable_price_zone"] == {"lower": "60000", "upper": "61000"}
    assert values["trade_price_condition"]["allow_chasing"] is False
    assert "structure_minor_conflicted_wait_support" in values["conflict_snapshot"]["warnings"]
    assert values["aggregation_snapshot"]["component_scores"]["structure"] == "0.45"


def test_long_trend_following_neutralizes_when_major_structure_conflicts() -> None:
    calculator = LongTrendFollowingCalculator()
    facts = base_long_facts()
    facts[4] = domain_fact("structure", "neutral", "structure_major_conflicted", value_id=5, strength="0")

    output = calculator.calculate(calculator_input("long_trend_following", facts))
    values = thaw_value(output.values)

    assert values["direction"] == StrategySignalDirection.NEUTRAL
    assert values["conflict_snapshot"]["has_conflict"] is True
    assert "structure_major_conflicted_for_long_trend" in values["conflict_snapshot"]["blockers"]


def test_long_pullback_support_outputs_bullish_near_support_with_weakening_pullback() -> None:
    calculator = LongPullbackSupportCalculator()
    facts = [
        domain_fact("market_context", "bullish", "market_context_bullish", value_id=1),
        domain_fact("trend", "bullish", "trend_1d_bullish_4h_pullback", value_id=2),
        domain_fact("momentum", "bearish", "momentum_bearish_exhausting", value_id=3),
        domain_fact("volatility", "neutral", "volatility_normal", value_id=4),
        domain_fact("structure", "bullish", "structure_major_near_support_minor_aligned", value_id=5),
        domain_fact("risk_state", "neutral", "risk_clear", value_id=6),
    ]

    output = calculator.calculate(calculator_input("long_pullback_support", facts))
    values = thaw_value(output.values)

    assert values["direction"] == StrategySignalDirection.BULLISH
    assert values["trade_price_condition"]["condition_type"] == "pullback_support_price_zone"


def test_long_pullback_support_uses_structure_support_zone_when_available() -> None:
    calculator = LongPullbackSupportCalculator()
    facts = [
        domain_fact("market_context", "bullish", "market_context_bullish", value_id=1),
        domain_fact("trend", "bullish", "trend_1d_bullish_4h_pullback", value_id=2),
        domain_fact("momentum", "bearish", "momentum_bearish_exhausting", value_id=3),
        domain_fact("volatility", "neutral", "volatility_normal", value_id=4),
        domain_fact(
            "structure",
            "bullish",
            "structure_major_near_support_minor_aligned",
            value_id=5,
            payload_summary={"support_zone": {"lower": "49000", "upper": "50000"}},
        ),
        domain_fact("risk_state", "neutral", "risk_clear", value_id=6),
    ]

    output = calculator.calculate(calculator_input("long_pullback_support", facts))
    values = thaw_value(output.values)

    assert values["direction"] == StrategySignalDirection.BULLISH
    assert values["trade_price_condition"]["acceptable_price_zone"] == {"lower": "49000", "upper": "50000"}


def test_short_trend_following_outputs_bearish_for_aligned_breakdown() -> None:
    calculator = ShortTrendFollowingCalculator()

    output = calculator.calculate(calculator_input("short_trend_following", base_short_facts()))
    values = thaw_value(output.values)

    assert values["direction"] == StrategySignalDirection.BEARISH
    assert values["trade_price_condition"]["condition_type"] == "breakdown_continuation_price_zone"


def test_short_trend_following_keeps_trend_but_waits_pressure_when_minor_structure_conflicts() -> None:
    calculator = ShortTrendFollowingCalculator()
    facts = base_short_facts()
    facts[4] = domain_fact(
        "structure",
        "neutral",
        "structure_major_lower_half_minor_conflicted",
        value_id=5,
        strength="0.55",
        payload_summary={"resistance_zone": {"lower": "63000", "upper": "64000"}},
    )

    output = calculator.calculate(calculator_input("short_trend_following", facts))
    values = thaw_value(output.values)

    assert values["direction"] == StrategySignalDirection.BEARISH
    assert values["trade_price_condition"]["condition_type"] == "trend_minor_conflict_resistance_price_zone"
    assert values["trade_price_condition"]["acceptable_price_zone"] == {"lower": "63000", "upper": "64000"}
    assert values["trade_price_condition"]["allow_chasing"] is False
    assert "structure_minor_conflicted_wait_pressure" in values["conflict_snapshot"]["warnings"]
    assert values["aggregation_snapshot"]["component_scores"]["structure"] == "0.45"


def test_short_trend_following_neutralizes_when_major_structure_conflicts() -> None:
    calculator = ShortTrendFollowingCalculator()
    facts = base_short_facts()
    facts[4] = domain_fact("structure", "neutral", "structure_major_conflicted", value_id=5, strength="0")

    output = calculator.calculate(calculator_input("short_trend_following", facts))
    values = thaw_value(output.values)

    assert values["direction"] == StrategySignalDirection.NEUTRAL
    assert values["conflict_snapshot"]["has_conflict"] is True
    assert "structure_major_conflicted_for_short_trend" in values["conflict_snapshot"]["blockers"]


def test_short_rebound_pressure_outputs_bearish_near_resistance_with_weakening_rebound() -> None:
    calculator = ShortReboundPressureCalculator()
    facts = [
        domain_fact("market_context", "bearish", "market_context_bearish", value_id=1),
        domain_fact("trend", "bearish", "trend_1d_bearish_4h_rebound", value_id=2),
        domain_fact("momentum", "bullish", "momentum_bullish_exhausting", value_id=3),
        domain_fact("volatility", "neutral", "volatility_normal", value_id=4),
        domain_fact("structure", "bearish", "structure_major_near_resistance_minor_aligned", value_id=5),
        domain_fact("risk_state", "neutral", "risk_clear", value_id=6),
    ]

    output = calculator.calculate(calculator_input("short_rebound_pressure", facts))
    values = thaw_value(output.values)

    assert values["direction"] == StrategySignalDirection.BEARISH
    assert values["trade_price_condition"]["condition_type"] == "rebound_pressure_price_zone"
