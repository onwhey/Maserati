from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from apps.strategy_calculator.contracts import CalculatorInput, CalculatorType
from apps.strategy_calculator.domain_signal import RiskStateAggregationV2Calculator


def _input(*, params: dict, atomic_values: list[dict]) -> CalculatorInput:
    return CalculatorInput(
        calculator_type=CalculatorType.DOMAIN_SIGNAL,
        input_schema_version="1.0",
        output_schema_version="1.0",
        business_time_utc=datetime(2026, 1, 1, tzinfo=UTC),
        frozen_params=params,
        values={
            "domain_code": "risk_state",
            "output_mode": "state",
            "atomic_values": atomic_values,
        },
    )


def _atomic(
    signal_code: str,
    *,
    active: bool = True,
    category: str = "signal_reliability_risk",
    direction: str = "two_sided",
    severity: str = "elevated",
) -> dict:
    return {
        "atomic_signal_value_id": abs(hash(signal_code)) % 100000,
        "signal_code": signal_code,
        "direction": "neutral",
        "strength": Decimal("1") if active else Decimal("0"),
        "is_valid": True,
        "status": "created",
        "value_bool": None,
        "value_decimal": None,
        "value_text": "",
        "value_json": {
            "condition_met": active,
            "risk_category": category,
            "risk_direction": direction,
            "risk_severity": severity if active else "none",
        },
        "evidence_items": [],
    }


def test_risk_state_v2_scores_false_breakout_as_signal_distortion() -> None:
    calculator = RiskStateAggregationV2Calculator()
    params = {
        "domain_type": "risk_state",
        "allowed_atomic_signal_codes": ["risk_false_breakout_rejection"],
        "required_atomic_signal_codes": [],
    }

    output = calculator.calculate(
        _input(
            params=params,
            atomic_values=[
                _atomic(
                    "risk_false_breakout_rejection",
                    category="false_breakout_risk",
                    direction="upside",
                    severity="high",
                )
            ],
        )
    )

    summary = output.evidence_items[0]["summary"]
    assert output.values["state_code"] == "risk_high_signal_unreliable"
    assert output.values["strength"] == Decimal("1")
    assert summary["risk_score"] == 100
    assert summary["market_event_score"] == 100
    assert summary["signal_distortion_score"] == 100
    assert summary["primary_risk_event"] == "false_breakout_distortion_event"
    assert "false_breakout_risk" in summary["risk_effect_tags"]


def test_risk_state_v2_marks_opposite_false_breaks_as_unclear_when_not_high() -> None:
    calculator = RiskStateAggregationV2Calculator()
    params = {
        "domain_type": "risk_state",
        "allowed_atomic_signal_codes": ["risk_false_breakout_rejection", "risk_false_breakdown_reclaim"],
        "required_atomic_signal_codes": [],
    }

    output = calculator.calculate(
        _input(
            params=params,
            atomic_values=[
                _atomic(
                    "risk_false_breakout_rejection",
                    category="false_breakout_risk",
                    direction="upside",
                    severity="elevated",
                ),
                _atomic(
                    "risk_false_breakdown_reclaim",
                    category="false_breakdown_risk",
                    direction="downside",
                    severity="elevated",
                ),
            ],
        )
    )

    summary = output.evidence_items[0]["summary"]
    assert output.values["state_code"] == "risk_unclear"
    assert summary["risk_score"] == 55
    assert summary["direction_stability_score"] == 25


def test_risk_state_v2_treats_intrabar_extreme_range_as_market_shock_event() -> None:
    calculator = RiskStateAggregationV2Calculator()
    params = {
        "domain_type": "risk_state",
        "allowed_atomic_signal_codes": ["risk_intrabar_extreme_range"],
        "required_atomic_signal_codes": [],
    }

    output = calculator.calculate(
        _input(
            params=params,
            atomic_values=[
                _atomic(
                    "risk_intrabar_extreme_range",
                    category="signal_reliability_risk",
                    direction="two_sided",
                    severity="high",
                )
            ],
        )
    )

    summary = output.evidence_items[0]["summary"]
    assert output.values["state_code"] == "risk_high_signal_unreliable"
    assert summary["risk_score"] == 100
    assert summary["market_event_score"] == 100
    assert summary["primary_risk_event"] == "intrabar_extreme_range_event"
    assert summary["risk_event_phase"] == "shock_active"
    assert summary["directional_exposure"]["dominant_exposed_position"] == "none"
    assert "intrabar_extreme_range" in summary["risk_effect_tags"]
    assert "market_shock" in summary["risk_effect_tags"]
    assert "two_sided_instability" in summary["risk_effect_tags"]


def test_risk_state_v2_keeps_directional_exposure_separate_from_signal_distortion() -> None:
    calculator = RiskStateAggregationV2Calculator()
    params = {
        "domain_type": "risk_state",
        "allowed_atomic_signal_codes": ["risk_long_exposure_shock_down"],
        "required_atomic_signal_codes": [],
    }

    output = calculator.calculate(
        _input(
            params=params,
            atomic_values=[
                _atomic(
                    "risk_long_exposure_shock_down",
                    category="long_exposure_risk",
                    direction="downside",
                    severity="high",
                )
            ],
        )
    )

    summary = output.evidence_items[0]["summary"]
    assert output.values["state_code"] == "risk_elevated_classifiable"
    assert summary["risk_score"] == 100
    assert summary["signal_distortion_score"] == 0
    assert summary["directional_exposure_score"] == 100
    assert summary["directional_exposure"]["dominant_exposed_position"] == "long_position"
    assert summary["primary_risk_event"] == "long_exposure_risk"
    assert "directional_exposure" in summary["risk_effect_tags"]
