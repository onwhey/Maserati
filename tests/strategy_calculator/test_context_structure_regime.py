from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from apps.strategy_calculator.contracts import CalculationStatus, CalculatorInput, CalculatorType
from apps.strategy_calculator.market_regime.context_structure_regime import (
    ContextStructureRegimeCalculator,
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


def calculate(*, overrides: dict[str, dict] | None = None, params: dict | None = None):
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
    return ContextStructureRegimeCalculator().calculate(input_dto)


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
