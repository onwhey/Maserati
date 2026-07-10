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
    feature_values: dict[str, str] | None = None,
    payload_extra: dict | None = None,
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
            "feature_values": {
                code: {"feature_value_id": index + 1, "value": value, "value_type": "decimal"}
                for index, (code, value) in enumerate((feature_values or {}).items())
            },
            **(payload_extra or {}),
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
    assert summary["risk_direction_scores"] == {"upside": 55, "downside": 55, "two_sided": 0}


def test_risk_state_v2_merges_multiple_same_direction_risks_without_marking_unclear() -> None:
    calculator = RiskStateAggregationV2Calculator()
    params = {
        "domain_type": "risk_state",
        "allowed_atomic_signal_codes": [
            "risk_down_body_shock",
            "risk_long_exposure_shock_down",
            "risk_short_chase_after_down_shock",
        ],
        "required_atomic_signal_codes": [],
    }

    output = calculator.calculate(
        _input(
            params=params,
            atomic_values=[
                _atomic(
                    "risk_down_body_shock",
                    category="signal_reliability_risk",
                    direction="downside",
                    severity="elevated",
                ),
                _atomic(
                    "risk_long_exposure_shock_down",
                    category="long_exposure_risk",
                    direction="downside",
                    severity="high",
                ),
                _atomic(
                    "risk_short_chase_after_down_shock",
                    category="short_chase_risk",
                    direction="downside",
                    severity="elevated",
                ),
            ],
        )
    )

    summary = output.evidence_items[0]["summary"]
    assert output.values["state_code"] == "risk_elevated_classifiable"
    assert summary["risk_score"] == 100
    assert summary["primary_risk_event"] == "extreme_down_shock"
    assert summary["risk_direction_scores"] == {"upside": 0, "downside": 100, "two_sided": 0}


def test_risk_state_v2_marks_equal_high_opposite_directions_as_unclear() -> None:
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
                    severity="high",
                ),
                _atomic(
                    "risk_false_breakdown_reclaim",
                    category="false_breakdown_risk",
                    direction="downside",
                    severity="high",
                ),
            ],
        )
    )

    summary = output.evidence_items[0]["summary"]
    assert output.values["state_code"] == "risk_unclear"
    assert summary["risk_score"] == 100
    assert summary["signal_distortion_score"] == 100
    assert summary["risk_direction_scores"] == {"upside": 100, "downside": 100, "two_sided": 0}


def test_risk_state_v2_keeps_stronger_opposite_direction_as_high_unreliable() -> None:
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
                    severity="high",
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
    assert output.values["state_code"] == "risk_high_signal_unreliable"
    assert summary["risk_direction_scores"] == {"upside": 100, "downside": 55, "two_sided": 0}


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


def test_risk_state_v2_treats_elevated_body_shock_as_active_market_shock() -> None:
    calculator = RiskStateAggregationV2Calculator()

    for signal_code, direction, primary_event, direction_tag in (
        ("risk_down_body_shock", "downside", "extreme_down_shock", "downside_shock"),
        ("risk_up_body_shock", "upside", "extreme_up_shock", "upside_shock"),
    ):
        params = {
            "domain_type": "risk_state",
            "allowed_atomic_signal_codes": [signal_code],
            "required_atomic_signal_codes": [],
        }
        output = calculator.calculate(
            _input(
                params=params,
                atomic_values=[
                    _atomic(
                        signal_code,
                        category="signal_reliability_risk",
                        direction=direction,
                        severity="elevated",
                    )
                ],
            )
        )

        summary = output.evidence_items[0]["summary"]
        assert output.values["state_code"] == "risk_elevated_classifiable"
        assert summary["risk_score"] == 55
        assert summary["signal_distortion_score"] == 55
        assert summary["primary_risk_event"] == primary_event
        assert summary["risk_event_phase"] == "shock_active"
        assert "body_shock" in summary["risk_effect_tags"]
        assert "market_shock" in summary["risk_effect_tags"]
        assert direction_tag in summary["risk_effect_tags"]
        assert "two_sided_instability" not in summary["risk_effect_tags"]


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


def test_risk_state_v2_keeps_recent_shock_in_observation_phase() -> None:
    calculator = RiskStateAggregationV2Calculator()
    params = {
        "domain_type": "risk_state",
        "allowed_atomic_signal_codes": ["risk_post_shock_observation"],
        "required_atomic_signal_codes": [],
    }

    output = calculator.calculate(
        _input(
            params=params,
            atomic_values=[
                _atomic(
                    "risk_post_shock_observation",
                    severity="high",
                    feature_values={"risk_bars_since_market_shock_4h_6": "2"},
                    payload_extra={"risk_event_type": "post_shock_observation", "observation_window_bars": 6},
                )
            ],
        )
    )

    summary = output.evidence_items[0]["summary"]
    assert output.values["state_code"] == "risk_high_signal_unreliable"
    assert summary["primary_risk_event"] == "post_shock_observation"
    assert summary["risk_event_phase"] == "post_shock_observation"
    assert summary["post_shock_observation_bars_remaining"] == 4
    assert "post_shock_observation" in summary["risk_effect_tags"]


def test_risk_state_v2_marks_late_observation_as_cooling() -> None:
    calculator = RiskStateAggregationV2Calculator()
    params = {
        "domain_type": "risk_state",
        "allowed_atomic_signal_codes": ["risk_post_shock_observation"],
        "required_atomic_signal_codes": [],
    }

    output = calculator.calculate(
        _input(
            params=params,
            atomic_values=[
                _atomic(
                    "risk_post_shock_observation",
                    severity="elevated",
                    feature_values={"risk_bars_since_market_shock_4h_6": "5"},
                    payload_extra={"risk_event_type": "post_shock_observation", "observation_window_bars": 6},
                )
            ],
        )
    )

    summary = output.evidence_items[0]["summary"]
    assert output.values["state_code"] == "risk_elevated_classifiable"
    assert summary["risk_event_phase"] == "cooling"
    assert summary["post_shock_observation_bars_remaining"] == 1


def test_risk_state_v2_reports_high_volatility_without_direction() -> None:
    calculator = RiskStateAggregationV2Calculator()
    params = {
        "domain_type": "risk_state",
        "allowed_atomic_signal_codes": ["risk_high_volatility_no_direction"],
        "required_atomic_signal_codes": [],
    }

    output = calculator.calculate(
        _input(
            params=params,
            atomic_values=[
                _atomic(
                    "risk_high_volatility_no_direction",
                    category="market_disorder_risk",
                    severity="high",
                    feature_values={
                        "risk_direction_flip_count_4h_8": "6",
                        "risk_movement_efficiency_4h_8": "0.15",
                    },
                    payload_extra={"risk_event_type": "high_volatility_no_direction"},
                )
            ],
        )
    )

    summary = output.evidence_items[0]["summary"]
    assert output.values["state_code"] == "risk_high_signal_unreliable"
    assert summary["primary_risk_event"] == "high_volatility_no_direction"
    assert summary["direction_stability_score"] == 14
    assert "high_volatility_no_direction" in summary["risk_effect_tags"]
    assert "direction_instability" in summary["risk_effect_tags"]
