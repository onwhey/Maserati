from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from apps.strategy_calculator.contracts import CalculationStatus, CalculatorInput, CalculatorType
from apps.strategy_calculator.market_regime.context_structure_regime import (
    ContextStructureRegimeCalculator,
    ContextStructureRegimeV2Calculator,
    ContextStructureRegimeV3Calculator,
    ContextStructureRegimeV4Calculator,
    ContextStructureRegimeV5Calculator,
    ContextStructureRegimeV6Calculator,
    REGIME_CODES,
    REQUIRED_DOMAIN_CODES,
)


def domain_value(value_id: int, code: str, direction: str, state_code: str, strength: str = "0.8") -> dict:
    return {
        "domain_signal_value_id": value_id,
        "domain_code": code,
        "direction": direction,
        "state_code": state_code,
        "strength": Decimal(strength),
        "coverage_ratio": Decimal("1"),
        "agreement_ratio": Decimal("1"),
        "definition_hash": f"hash-{code}",
        "evidence_items": [{"domain_code": code}],
    }


def structure_evidence_item(
    *,
    major: dict | None = None,
    minor: dict | None = None,
    primary_state_zh: str = "结构证据测试",
) -> dict:
    return {
        "summary": {
            "structure_evidence": {
                "major": {
                    "support_holds": False,
                    "resistance_holds": False,
                    "support_testing": False,
                    "resistance_testing": False,
                    "near_support": False,
                    "near_resistance": False,
                    "between_support_resistance": False,
                    "support_breakdown_candidate": False,
                    "support_breakdown_confirmed": False,
                    "resistance_breakout_candidate": False,
                    "resistance_breakout_confirmed": False,
                    **(major or {}),
                },
                "minor": {
                    "support_holds": False,
                    "resistance_holds": False,
                    "support_testing": False,
                    "resistance_testing": False,
                    "near_support": False,
                    "near_resistance": False,
                    "between_support_resistance": False,
                    "support_breakdown_candidate": False,
                    "support_breakdown_confirmed": False,
                    "resistance_breakout_candidate": False,
                    "resistance_breakout_confirmed": False,
                    **(minor or {}),
                },
                "primary_state_zh": primary_state_zh,
                "facts_zh": [primary_state_zh],
            }
        }
    }


def calculate(*, overrides: dict[str, dict] | None = None, params: dict | None = None, calculator=None):
    facts = {
        "market_context": domain_value(1, "market_context", "bullish", "market_context_high_zone"),
        "trend": domain_value(2, "trend", "bullish", "trend_1d_bullish_4h_aligned"),
        "momentum": domain_value(3, "momentum", "bullish", "momentum_bullish_strengthening"),
        "volatility": domain_value(4, "volatility", "none", "volatility_normal"),
        "structure": domain_value(5, "structure", "neutral", "structure_major_range_middle_minor_range_middle"),
        "risk_state": domain_value(6, "risk_state", "none", "risk_clear"),
    }
    for code, patch in (overrides or {}).items():
        facts[code] = {**facts[code], **patch}
    input_dto = CalculatorInput(
        calculator_type=CalculatorType.MARKET_REGIME,
        input_schema_version="1.0",
        output_schema_version="1.0",
        business_time_utc=datetime(2026, 1, 1, tzinfo=UTC),
        frozen_params=params or {"min_regime_score": "0.55", "min_classification_margin": "0.10"},
        values={
            "domain_values": [facts[code] for code in REQUIRED_DOMAIN_CODES],
            "allowed_domain_codes": list(REQUIRED_DOMAIN_CODES),
            "required_domain_codes": list(REQUIRED_DOMAIN_CODES),
            "allowed_regime_codes": list(REGIME_CODES),
        },
    )
    return (calculator or ContextStructureRegimeCalculator()).calculate(input_dto)


def test_context_structure_regime_outputs_bullish_trend_continuation_with_complete_scores() -> None:
    output = calculate()

    assert output.calculation_status == CalculationStatus.SUCCEEDED
    assert output.values["regime_code"] == "bullish_trend_continuation"
    assert set(output.values["regime_scores"]) == set(REGIME_CODES)
    assert tuple(output.values["used_domain_signal_value_ids"]) == (1, 2, 3, 4, 5, 6)
    assert "不生成策略、目标仓位或订单动作" in output.values["evidence_text_zh"]


def test_context_structure_regime_prioritizes_high_risk_environment() -> None:
    output = calculate(
        overrides={
            "risk_state": {
                "state_code": "risk_high_signal_unreliable",
                "strength": Decimal("1"),
            }
        }
    )

    assert output.calculation_status == CalculationStatus.SUCCEEDED
    assert output.values["regime_code"] == "high_risk_environment"
    assert output.values["regime_scores"]["high_risk_environment"] == Decimal("1.0000")


def test_context_structure_regime_prioritizes_bullish_breakout_over_continuation() -> None:
    output = calculate(
        overrides={
            "structure": {
                "direction": "bullish",
                "state_code": "structure_major_breakout_up",
                "strength": Decimal("0.9"),
            }
        }
    )

    assert output.calculation_status == CalculationStatus.SUCCEEDED
    assert output.values["regime_code"] == "bullish_breakout"
    assert output.values["regime_scores"]["bullish_breakout"] > output.values["regime_scores"][
        "bullish_trend_continuation"
    ]


def test_context_structure_regime_distinguishes_bullish_high_range_from_neutral_range() -> None:
    output = calculate(
        overrides={
            "trend": {
                "direction": "neutral",
                "state_code": "trend_unclear",
            },
            "momentum": {
                "direction": "bullish",
                "state_code": "momentum_bullish_exhausting",
            },
            "volatility": {
                "state_code": "volatility_high",
            },
            "structure": {
                "state_code": "structure_major_near_resistance_minor_aligned",
            },
        }
    )

    assert output.calculation_status == CalculationStatus.SUCCEEDED
    assert output.values["regime_code"] == "bullish_high_range"
    assert output.values["regime_scores"]["neutral_range"] <= Decimal("0.5000")


def test_context_structure_regime_outputs_neutral_range_only_when_context_is_neutral() -> None:
    output = calculate(
        overrides={
            "market_context": {
                "direction": "neutral",
                "state_code": "market_context_neutral",
            },
            "trend": {
                "direction": "neutral",
                "state_code": "trend_unclear",
            },
            "momentum": {
                "direction": "neutral",
                "state_code": "momentum_neutral_choppy",
            },
            "structure": {
                "state_code": "structure_major_range_middle_minor_range_middle",
            },
        }
    )

    assert output.calculation_status == CalculationStatus.SUCCEEDED
    assert output.values["regime_code"] == "neutral_range"


def test_context_structure_regime_rejects_incomplete_domain_inputs() -> None:
    input_dto = CalculatorInput(
        calculator_type=CalculatorType.MARKET_REGIME,
        input_schema_version="1.0",
        output_schema_version="1.0",
        values={
            "domain_values": [],
            "allowed_regime_codes": list(REGIME_CODES),
        },
    )

    output = ContextStructureRegimeCalculator().calculate(input_dto)

    assert output.calculation_status == CalculationStatus.FAILED
    assert output.error_code == "context_structure_regime_required_domain_missing"


def test_context_structure_regime_v2_selects_bearish_rebound_in_same_family_transition() -> None:
    output = calculate(
        calculator=ContextStructureRegimeV2Calculator(),
        params={
            "min_regime_score": "0.50",
            "min_classification_margin": "0.05",
            "transition_floor_score": "0.50",
        },
        overrides={
            "market_context": {
                "direction": "bearish",
                "state_code": "market_context_deep_drawdown",
            },
            "trend": {
                "direction": "neutral",
                "state_code": "trend_1d_neutral_4h_bullish",
            },
            "momentum": {
                "direction": "bullish",
                "state_code": "momentum_bullish_strengthening",
            },
            "volatility": {
                "state_code": "volatility_low",
            },
            "structure": {
                "direction": "neutral",
                "state_code": "structure_major_near_resistance_minor_unclear",
            },
        },
    )

    assert output.calculation_status == CalculationStatus.SUCCEEDED
    assert output.values["regime_code"] == "bearish_rebound"
    assert output.evidence_items[0]["type"] == "context_structure_regime_v2"


def test_context_structure_regime_v2_keeps_unclear_when_risk_is_unclear() -> None:
    output = calculate(
        calculator=ContextStructureRegimeV2Calculator(),
        overrides={
            "risk_state": {
                "state_code": "risk_unclear",
                "strength": Decimal("1"),
            }
        },
    )

    assert output.calculation_status == CalculationStatus.SUCCEEDED
    assert output.values["regime_code"] == "unclear_environment"


def test_context_structure_regime_v3_preserves_bearish_rebound_recognition() -> None:
    output = calculate(
        calculator=ContextStructureRegimeV3Calculator(),
        params={
            "min_regime_score": "0.50",
            "min_classification_margin": "0.05",
            "transition_floor_score": "0.50",
        },
        overrides={
            "market_context": {
                "direction": "bearish",
                "state_code": "market_context_deep_drawdown",
            },
            "trend": {
                "direction": "neutral",
                "state_code": "trend_1d_neutral_4h_bullish",
            },
            "momentum": {
                "direction": "bullish",
                "state_code": "momentum_bullish_strengthening",
            },
            "volatility": {
                "state_code": "volatility_low",
            },
            "structure": {
                "direction": "neutral",
                "state_code": "structure_major_near_resistance_minor_unclear",
            },
        },
    )

    assert output.calculation_status == CalculationStatus.SUCCEEDED
    assert output.values["regime_code"] == "bearish_rebound"
    assert output.evidence_items[0]["type"] == "context_structure_regime_v3"


def test_context_structure_regime_v3_does_not_force_bullish_continuation_after_primary_trend_turns_bearish() -> None:
    output = calculate(
        calculator=ContextStructureRegimeV3Calculator(),
        params={
            "min_regime_score": "0.50",
            "min_classification_margin": "0.05",
            "transition_floor_score": "0.50",
        },
        overrides={
            "market_context": {
                "direction": "bullish",
                "state_code": "market_context_high_zone",
            },
            "trend": {
                "direction": "bearish",
                "state_code": "trend_1d_bearish_4h_rebound",
            },
            "momentum": {
                "direction": "bullish",
                "state_code": "momentum_bullish_strengthening",
            },
            "volatility": {
                "state_code": "volatility_high",
            },
            "structure": {
                "direction": "neutral",
                "state_code": "structure_major_near_resistance_minor_unclear",
            },
        },
    )

    assert output.calculation_status == CalculationStatus.SUCCEEDED
    assert output.values["regime_code"] == "bullish_top_reversal_candidate"
    assert output.values["regime_scores"]["bullish_trend_continuation"] <= Decimal("0.3500")
    assert output.evidence_items[0]["type"] == "context_structure_regime_v3"


def test_context_structure_regime_v4_requires_structure_evidence() -> None:
    output = calculate(
        calculator=ContextStructureRegimeV4Calculator(),
        params={
            "min_regime_score": "0.50",
            "min_classification_margin": "0.05",
            "transition_floor_score": "0.50",
        },
    )

    assert output.calculation_status == CalculationStatus.FAILED
    assert output.error_code == "market_regime_structure_evidence_missing"


def test_context_structure_regime_v4_uses_support_holds_for_bullish_pullback() -> None:
    output = calculate(
        calculator=ContextStructureRegimeV4Calculator(),
        params={
            "min_regime_score": "0.50",
            "min_classification_margin": "0.05",
            "transition_floor_score": "0.50",
        },
        overrides={
            "trend": {
                "direction": "neutral",
                "state_code": "trend_1d_bullish_4h_bearish",
            },
            "momentum": {
                "direction": "bearish",
                "state_code": "momentum_bearish_present",
            },
            "structure": {
                "direction": "neutral",
                "state_code": "structure_major_near_support_minor_unclear",
                "evidence_items": [
                    structure_evidence_item(
                        major={"support_holds": True},
                        primary_state_zh="1d 大结构支撑仍有效",
                    )
                ],
            },
        },
    )

    assert output.calculation_status == CalculationStatus.SUCCEEDED
    assert output.values["regime_code"] == "bullish_pullback"
    assert output.values["regime_scores"]["bullish_pullback"] > output.values["regime_scores"][
        "bullish_top_reversal_candidate"
    ]
    assert output.evidence_items[0]["type"] == "context_structure_regime_v4"
    assert output.evidence_items[0]["structure_evidence"]["major"]["support_holds"] is True


def test_context_structure_regime_v4_uses_support_breakdown_to_weaken_bullish_context() -> None:
    output = calculate(
        calculator=ContextStructureRegimeV4Calculator(),
        params={
            "min_regime_score": "0.50",
            "min_classification_margin": "0.05",
            "transition_floor_score": "0.50",
        },
        overrides={
            "trend": {
                "direction": "bearish",
                "state_code": "trend_1d_bearish_4h_rebound",
            },
            "momentum": {
                "direction": "bearish",
                "state_code": "momentum_bearish_strengthening",
            },
            "volatility": {
                "state_code": "volatility_high",
            },
            "structure": {
                "direction": "bearish",
                "state_code": "structure_major_breakdown_down",
                "evidence_items": [
                    structure_evidence_item(
                        major={"support_breakdown_candidate": True},
                        primary_state_zh="1d 大结构支撑跌破候选",
                    )
                ],
            },
        },
    )

    assert output.calculation_status == CalculationStatus.SUCCEEDED
    assert output.values["regime_code"] == "bullish_top_reversal_candidate"
    assert output.values["regime_scores"]["bullish_trend_continuation"] <= Decimal("0.4200")


def test_context_structure_regime_v4_uses_resistance_holds_for_bearish_rebound() -> None:
    output = calculate(
        calculator=ContextStructureRegimeV4Calculator(),
        params={
            "min_regime_score": "0.50",
            "min_classification_margin": "0.05",
            "transition_floor_score": "0.50",
        },
        overrides={
            "market_context": {
                "direction": "bearish",
                "state_code": "market_context_deep_drawdown",
            },
            "trend": {
                "direction": "neutral",
                "state_code": "trend_1d_bearish_4h_bullish",
            },
            "momentum": {
                "direction": "bullish",
                "state_code": "momentum_bullish_strengthening",
            },
            "structure": {
                "direction": "neutral",
                "state_code": "structure_major_near_resistance_minor_unclear",
                "evidence_items": [
                    structure_evidence_item(
                        major={"resistance_holds": True},
                        primary_state_zh="1d 大结构压力仍有效",
                    )
                ],
            },
        },
    )

    assert output.calculation_status == CalculationStatus.SUCCEEDED
    assert output.values["regime_code"] == "bearish_rebound"
    assert output.values["regime_scores"]["bearish_rebound"] > output.values["regime_scores"][
        "bearish_trend_continuation"
    ]


def test_context_structure_regime_v4_uses_resistance_breakout_to_weaken_bearish_context() -> None:
    output = calculate(
        calculator=ContextStructureRegimeV4Calculator(),
        params={
            "min_regime_score": "0.50",
            "min_classification_margin": "0.05",
            "transition_floor_score": "0.50",
        },
        overrides={
            "market_context": {
                "direction": "bearish",
                "state_code": "market_context_deep_drawdown",
            },
            "trend": {
                "direction": "bullish",
                "state_code": "trend_1d_neutral_4h_bullish",
            },
            "momentum": {
                "direction": "bullish",
                "state_code": "momentum_bullish_strengthening",
            },
            "structure": {
                "direction": "bullish",
                "state_code": "structure_major_breakout_up",
                "evidence_items": [
                    structure_evidence_item(
                        major={"resistance_breakout_candidate": True},
                        primary_state_zh="1d 大结构压力突破候选",
                    )
                ],
            },
        },
    )

    assert output.calculation_status == CalculationStatus.SUCCEEDED
    assert output.values["regime_code"] == "bullish_breakout"
    assert output.values["regime_scores"]["bearish_trend_continuation"] <= Decimal("0.4200")


def test_context_structure_regime_v5_requires_structure_evidence() -> None:
    output = calculate(
        calculator=ContextStructureRegimeV5Calculator(),
        params={
            "min_regime_score": "0.50",
            "min_classification_margin": "0.05",
            "transition_floor_score": "0.50",
        },
    )

    assert output.calculation_status == CalculationStatus.FAILED
    assert output.error_code == "market_regime_structure_evidence_missing"


def test_context_structure_regime_v5_keeps_bullish_pullback_when_support_holds() -> None:
    output = calculate(
        calculator=ContextStructureRegimeV5Calculator(),
        params={
            "min_regime_score": "0.50",
            "min_classification_margin": "0.05",
            "transition_floor_score": "0.50",
        },
        overrides={
            "trend": {
                "direction": "neutral",
                "state_code": "trend_1d_bullish_4h_bearish",
            },
            "momentum": {
                "direction": "bearish",
                "state_code": "momentum_bearish_present",
            },
            "structure": {
                "direction": "neutral",
                "state_code": "structure_major_near_support_minor_unclear",
                "evidence_items": [
                    structure_evidence_item(
                        major={"support_holds": True},
                        primary_state_zh="1d 大结构支撑仍有效",
                    )
                ],
            },
        },
    )

    assert output.calculation_status == CalculationStatus.SUCCEEDED
    assert output.values["regime_code"] == "bullish_pullback"
    assert output.evidence_items[0]["type"] == "context_structure_regime_v5"
    assert output.evidence_items[0]["structure_phase"]["bullish_structure_maintained"] is True


def test_context_structure_regime_v5_treats_support_breakdown_candidate_as_pressure_before_confirmation() -> None:
    output = calculate(
        calculator=ContextStructureRegimeV5Calculator(),
        params={
            "min_regime_score": "0.50",
            "min_classification_margin": "0.05",
            "transition_floor_score": "0.50",
        },
        overrides={
            "trend": {
                "direction": "neutral",
                "state_code": "trend_1d_bullish_4h_bearish",
            },
            "momentum": {
                "direction": "bearish",
                "state_code": "momentum_bearish_present",
            },
            "volatility": {
                "state_code": "volatility_high",
            },
            "structure": {
                "direction": "neutral",
                "state_code": "structure_major_near_support_minor_unclear",
                "evidence_items": [
                    structure_evidence_item(
                        major={"support_breakdown_candidate": True},
                        primary_state_zh="1d 大结构支撑跌破候选",
                    )
                ],
            },
        },
    )

    assert output.calculation_status == CalculationStatus.SUCCEEDED
    assert output.values["regime_code"] == "bullish_top_reversal_candidate"
    assert output.values["regime_code"] != "bearish_breakdown"
    assert output.evidence_items[0]["structure_phase"]["bullish_structure_breakdown_candidate"] is True


def test_context_structure_regime_v5_allows_confirmed_support_breakdown_to_bearish_breakdown() -> None:
    output = calculate(
        calculator=ContextStructureRegimeV5Calculator(),
        params={
            "min_regime_score": "0.50",
            "min_classification_margin": "0.05",
            "transition_floor_score": "0.50",
        },
        overrides={
            "trend": {
                "direction": "bearish",
                "state_code": "trend_1d_bearish_4h_aligned",
            },
            "momentum": {
                "direction": "bearish",
                "state_code": "momentum_bearish_strengthening",
            },
            "volatility": {
                "state_code": "volatility_high",
            },
            "structure": {
                "direction": "bearish",
                "state_code": "structure_major_breakdown_down",
                "evidence_items": [
                    structure_evidence_item(
                        major={"support_breakdown_candidate": True},
                        primary_state_zh="1d 大结构支撑确认跌破",
                    )
                ],
            },
        },
    )

    assert output.calculation_status == CalculationStatus.SUCCEEDED
    assert output.values["regime_code"] == "bearish_breakdown"
    assert output.evidence_items[0]["structure_phase"]["bullish_structure_broken"] is True


def test_context_structure_regime_v5_keeps_bearish_rebound_when_resistance_holds() -> None:
    output = calculate(
        calculator=ContextStructureRegimeV5Calculator(),
        params={
            "min_regime_score": "0.50",
            "min_classification_margin": "0.05",
            "transition_floor_score": "0.50",
        },
        overrides={
            "market_context": {
                "direction": "bearish",
                "state_code": "market_context_deep_drawdown",
            },
            "trend": {
                "direction": "neutral",
                "state_code": "trend_1d_bearish_4h_bullish",
            },
            "momentum": {
                "direction": "bullish",
                "state_code": "momentum_bullish_strengthening",
            },
            "structure": {
                "direction": "neutral",
                "state_code": "structure_major_near_resistance_minor_unclear",
                "evidence_items": [
                    structure_evidence_item(
                        major={"resistance_holds": True},
                        primary_state_zh="1d 大结构压力仍有效",
                    )
                ],
            },
        },
    )

    assert output.calculation_status == CalculationStatus.SUCCEEDED
    assert output.values["regime_code"] == "bearish_rebound"
    assert output.evidence_items[0]["structure_phase"]["bearish_structure_maintained"] is True


def test_context_structure_regime_v5_allows_confirmed_resistance_breakout_to_bullish_breakout() -> None:
    output = calculate(
        calculator=ContextStructureRegimeV5Calculator(),
        params={
            "min_regime_score": "0.50",
            "min_classification_margin": "0.05",
            "transition_floor_score": "0.50",
        },
        overrides={
            "market_context": {
                "direction": "bearish",
                "state_code": "market_context_deep_drawdown",
            },
            "trend": {
                "direction": "bullish",
                "state_code": "trend_1d_bullish_4h_aligned",
            },
            "momentum": {
                "direction": "bullish",
                "state_code": "momentum_bullish_strengthening",
            },
            "structure": {
                "direction": "bullish",
                "state_code": "structure_major_breakout_up",
                "evidence_items": [
                    structure_evidence_item(
                        major={"resistance_breakout_candidate": True},
                        primary_state_zh="1d 大结构压力确认突破",
                    )
                ],
            },
        },
    )

    assert output.calculation_status == CalculationStatus.SUCCEEDED
    assert output.values["regime_code"] == "bullish_breakout"
    assert output.evidence_items[0]["structure_phase"]["bearish_structure_repaired"] is True


def test_context_structure_regime_v6_requires_structure_evidence() -> None:
    output = calculate(
        calculator=ContextStructureRegimeV6Calculator(),
        params={
            "min_regime_score": "0.50",
            "min_classification_margin": "0.05",
        },
    )

    assert output.calculation_status == CalculationStatus.FAILED
    assert output.error_code == "market_regime_structure_evidence_missing"


def test_context_structure_regime_v6_treats_bullish_pressure_as_structure_pressure_not_pullback() -> None:
    output = calculate(
        calculator=ContextStructureRegimeV6Calculator(),
        params={
            "min_regime_score": "0.50",
            "min_classification_margin": "0.05",
        },
        overrides={
            "trend": {
                "direction": "bullish",
                "state_code": "trend_1d_bullish_4h_aligned",
            },
            "momentum": {
                "direction": "neutral",
                "state_code": "momentum_neutral_choppy",
            },
            "structure": {
                "direction": "neutral",
                "state_code": "structure_pivot_major_resistance_holds",
                "evidence_items": [
                    structure_evidence_item(
                        major={"resistance_holds": True},
                        primary_state_zh="1d 大结构压力压住",
                    )
                ],
            },
        },
    )

    assert output.calculation_status == CalculationStatus.SUCCEEDED
    assert output.values["regime_code"] in {"bullish_top_reversal_candidate", "bullish_high_range"}
    assert output.values["regime_code"] != "bullish_pullback"
    assert output.evidence_items[0]["type"] == "context_structure_regime_v6"
    assert output.evidence_items[0]["structure_context"]["resistance_active"] is True


def test_context_structure_regime_v6_treats_bearish_support_as_low_range_not_trend_continuation() -> None:
    output = calculate(
        calculator=ContextStructureRegimeV6Calculator(),
        params={
            "min_regime_score": "0.50",
            "min_classification_margin": "0.05",
        },
        overrides={
            "market_context": {
                "direction": "bearish",
                "state_code": "market_context_deep_drawdown",
            },
            "trend": {
                "direction": "bearish",
                "state_code": "trend_1d_bearish_4h_aligned",
            },
            "momentum": {
                "direction": "neutral",
                "state_code": "momentum_neutral_choppy",
            },
            "structure": {
                "direction": "neutral",
                "state_code": "structure_pivot_major_support_holds",
                "evidence_items": [
                    structure_evidence_item(
                        major={"support_holds": True},
                        primary_state_zh="1d 大结构支撑守住",
                    )
                ],
            },
        },
    )

    assert output.calculation_status == CalculationStatus.SUCCEEDED
    assert output.values["regime_code"] in {"bearish_low_range", "bearish_bottom_reversal_candidate"}
    assert output.values["regime_code"] != "bearish_trend_continuation"
    assert output.evidence_items[0]["structure_context"]["support_active"] is True


def test_context_structure_regime_v6_does_not_treat_support_breakdown_candidate_as_confirmed_breakdown() -> None:
    output = calculate(
        calculator=ContextStructureRegimeV6Calculator(),
        params={
            "min_regime_score": "0.50",
            "min_classification_margin": "0.05",
        },
        overrides={
            "trend": {
                "direction": "bearish",
                "state_code": "trend_1d_bearish_4h_aligned",
            },
            "momentum": {
                "direction": "bearish",
                "state_code": "momentum_bearish_strengthening",
            },
            "structure": {
                "direction": "bearish",
                "state_code": "structure_pivot_major_support_breakdown_candidate",
                "evidence_items": [
                    structure_evidence_item(
                        major={"support_breakdown_candidate": True},
                        primary_state_zh="1d 大结构支撑跌破候选",
                    )
                ],
            },
        },
    )

    assert output.calculation_status == CalculationStatus.SUCCEEDED
    assert output.values["regime_code"] != "bearish_breakdown"
    assert output.evidence_items[0]["structure_context"]["support_breakdown_candidate"] is True


def test_context_structure_regime_v6_allows_confirmed_support_breakdown_to_bearish_breakdown() -> None:
    output = calculate(
        calculator=ContextStructureRegimeV6Calculator(),
        params={
            "min_regime_score": "0.50",
            "min_classification_margin": "0.05",
        },
        overrides={
            "trend": {
                "direction": "bearish",
                "state_code": "trend_1d_bearish_4h_aligned",
            },
            "momentum": {
                "direction": "bearish",
                "state_code": "momentum_bearish_strengthening",
            },
            "structure": {
                "direction": "bearish",
                "state_code": "structure_pivot_major_support_breakdown_confirmed",
                "evidence_items": [
                    structure_evidence_item(
                        major={"support_breakdown_confirmed": True},
                        primary_state_zh="1d 大结构确认跌破支撑",
                    )
                ],
            },
        },
    )

    assert output.calculation_status == CalculationStatus.SUCCEEDED
    assert output.values["regime_code"] == "bearish_breakdown"
    assert output.evidence_items[0]["structure_context"]["support_breakdown_confirmed"] is True


def test_context_structure_regime_v6_allows_confirmed_resistance_breakout_to_bullish_breakout() -> None:
    output = calculate(
        calculator=ContextStructureRegimeV6Calculator(),
        params={
            "min_regime_score": "0.50",
            "min_classification_margin": "0.05",
        },
        overrides={
            "market_context": {
                "direction": "bearish",
                "state_code": "market_context_deep_drawdown",
            },
            "trend": {
                "direction": "bullish",
                "state_code": "trend_1d_bullish_4h_aligned",
            },
            "momentum": {
                "direction": "bullish",
                "state_code": "momentum_bullish_strengthening",
            },
            "structure": {
                "direction": "bullish",
                "state_code": "structure_pivot_major_resistance_breakout_confirmed",
                "evidence_items": [
                    structure_evidence_item(
                        major={"resistance_breakout_confirmed": True},
                        primary_state_zh="1d 大结构确认突破压力",
                    )
                ],
            },
        },
    )

    assert output.calculation_status == CalculationStatus.SUCCEEDED
    assert output.values["regime_code"] == "bullish_breakout"
    assert output.evidence_items[0]["structure_context"]["resistance_breakout_confirmed"] is True
