from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from apps.strategy_calculator.contracts import CalculatorInput, CalculatorType
from apps.strategy_calculator.domain_signal import GroupedAtomicAggregationCalculator


def _input(*, domain_code: str, output_mode: str, params: dict, atomic_values: list[dict]) -> CalculatorInput:
    return CalculatorInput(
        calculator_type=CalculatorType.DOMAIN_SIGNAL,
        input_schema_version="1.0",
        output_schema_version="1.0",
        business_time_utc=datetime(2026, 1, 1, tzinfo=UTC),
        frozen_params=params,
        values={
            "domain_code": domain_code,
            "output_mode": output_mode,
            "atomic_values": atomic_values,
        },
    )


def _atomic(signal_code: str, *, active: bool = True, direction: str = "neutral", value_json: dict | None = None) -> dict:
    return {
        "atomic_signal_value_id": abs(hash(signal_code)) % 100000,
        "signal_code": signal_code,
        "direction": direction,
        "strength": Decimal("1") if active else Decimal("0"),
        "is_valid": True,
        "status": "created",
        "value_bool": active if value_json is None else None,
        "value_decimal": None,
        "value_text": "",
        "value_json": value_json,
    }


def test_grouped_atomic_trend_uses_1d_as_primary_and_4h_as_auxiliary() -> None:
    calculator = GroupedAtomicAggregationCalculator()
    params = {
        "domain_type": "trend",
        "allowed_atomic_signal_codes": ["a", "b", "c", "d"],
        "required_atomic_signal_codes": [],
        "primary_bullish_group": ["a", "b"],
        "primary_bearish_group": [],
        "short_cycle_bullish_group": [],
        "short_cycle_bearish_group": ["c", "d"],
        "primary_min_gap": 2,
        "short_cycle_min_gap": 2,
        "strong_primary_gap": 4,
        "state_code_map": {"bullish:bearish": "trend_1d_bullish_4h_pullback"},
    }

    output = calculator.calculate(
        _input(
            domain_code="trend",
            output_mode="directional",
            params=params,
            atomic_values=[_atomic("a", direction="bullish"), _atomic("b", direction="bullish"), _atomic("c"), _atomic("d")],
        )
    )

    assert output.values["direction"] == "bullish"
    assert output.values["state_code"] == "trend_1d_bullish_4h_pullback"
    assert output.values["strength"] == Decimal("0.5")
    assert output.values["coverage_ratio"] == Decimal("1")


def test_grouped_atomic_volatility_outputs_state_without_direction() -> None:
    calculator = GroupedAtomicAggregationCalculator()
    params = {
        "domain_type": "volatility",
        "allowed_atomic_signal_codes": ["low1", "low2", "compression", "shadow"],
        "required_atomic_signal_codes": [],
        "low_volatility_group": ["low1", "low2", "compression"],
        "high_volatility_group": [],
        "extreme_volatility_group": [],
        "state_signals": {"shadow": "latest_4h_lower_shadow_dominant"},
        "low_min_count": 2,
        "high_min_count": 2,
        "extreme_min_count": 1,
        "strong_state_denominator": 4,
    }

    output = calculator.calculate(
        _input(
            domain_code="volatility",
            output_mode="state",
            params=params,
            atomic_values=[_atomic("low1"), _atomic("low2"), _atomic("compression"), _atomic("shadow")],
        )
    )

    assert output.values["direction"] == "none"
    assert output.values["state_code"] == "volatility_low"
    assert output.values["agreement_ratio"] == Decimal("0")


def test_grouped_atomic_structure_carries_support_and_resistance_zones_in_summary() -> None:
    calculator = GroupedAtomicAggregationCalculator()
    params = {
        "domain_type": "structure",
        "allowed_atomic_signal_codes": [
            "structure_major_near_support",
            "structure_minor_range_middle",
        ],
        "required_atomic_signal_codes": [],
    }
    zone_snapshot = {
        "condition_met": True,
        "feature_values": {
            "structure_major_support_lower_1d_365": {"feature_value_id": 1, "value": "49000", "value_type": "decimal"},
            "structure_major_support_upper_1d_365": {"feature_value_id": 2, "value": "50000", "value_type": "decimal"},
            "structure_major_resistance_lower_1d_365": {"feature_value_id": 3, "value": "59000", "value_type": "decimal"},
            "structure_major_resistance_upper_1d_365": {"feature_value_id": 4, "value": "60000", "value_type": "decimal"},
        },
    }

    output = calculator.calculate(
        _input(
            domain_code="structure",
            output_mode="state",
            params=params,
            atomic_values=[
                _atomic("structure_major_near_support", value_json=zone_snapshot),
                _atomic("structure_minor_range_middle"),
            ],
        )
    )

    summary = output.evidence_items[0]["summary"]
    assert output.values["state_code"] == "structure_major_near_support_minor_range_middle"
    assert summary["support_zone"] == {"lower": "49000", "upper": "50000"}
    assert summary["resistance_zone"] == {"lower": "59000", "upper": "60000"}
    assert summary["current_zone_position"] == "near_support"


def test_grouped_atomic_structure_records_minor_conflict_as_market_fact() -> None:
    calculator = GroupedAtomicAggregationCalculator()
    params = {
        "domain_type": "structure",
        "allowed_atomic_signal_codes": [
            "structure_major_lower_half",
            "structure_minor_near_support",
            "structure_minor_near_resistance",
        ],
        "required_atomic_signal_codes": [],
    }

    output = calculator.calculate(
        _input(
            domain_code="structure",
            output_mode="state",
            params=params,
            atomic_values=[
                _atomic("structure_major_lower_half"),
                _atomic("structure_minor_near_support"),
                _atomic("structure_minor_near_resistance"),
            ],
        )
    )

    summary = output.evidence_items[0]["summary"]
    assert output.error_code == ""
    assert output.values["direction"] == "neutral"
    assert output.values["state_code"] == "structure_major_lower_half_minor_conflicted"
    assert output.values["strength"] == Decimal("0.55")
    assert output.values["agreement_ratio"] == Decimal("0")
    assert summary["major_structure"] == "lower_half"
    assert summary["minor_structure"] == "conflicted"
    assert summary["minor_conflict"] is True
    assert summary["current_zone_position"] == "conflicted"
    assert "structure_minor_state_conflict_detected" in output.evidence_items[0]["state_tags"]


def test_grouped_atomic_structure_records_major_conflict_as_unclear_fact() -> None:
    calculator = GroupedAtomicAggregationCalculator()
    params = {
        "domain_type": "structure",
        "allowed_atomic_signal_codes": [
            "structure_major_breakout_up",
            "structure_major_breakdown_down",
            "structure_minor_range_middle",
        ],
        "required_atomic_signal_codes": [],
    }

    output = calculator.calculate(
        _input(
            domain_code="structure",
            output_mode="state",
            params=params,
            atomic_values=[
                _atomic("structure_major_breakout_up"),
                _atomic("structure_major_breakdown_down"),
                _atomic("structure_minor_range_middle"),
            ],
        )
    )

    summary = output.evidence_items[0]["summary"]
    assert output.error_code == ""
    assert output.values["direction"] == "neutral"
    assert output.values["state_code"] == "structure_major_conflicted"
    assert output.values["strength"] == Decimal("0")
    assert summary["major_structure"] == "conflicted"
    assert summary["major_conflict"] is True
    assert summary["current_zone_position"] == "conflicted"
    assert "structure_major_state_conflict_detected" in output.evidence_items[0]["state_tags"]


def test_grouped_atomic_risk_distinguishes_classifiable_risk_from_unreliable_signal() -> None:
    calculator = GroupedAtomicAggregationCalculator()
    params = {
        "domain_type": "risk_state",
        "allowed_atomic_signal_codes": ["shock_down", "whipsaw"],
        "required_atomic_signal_codes": [],
    }

    classifiable = calculator.calculate(
        _input(
            domain_code="risk_state",
            output_mode="state",
            params=params,
            atomic_values=[
                _atomic(
                    "shock_down",
                    value_json={
                        "condition_met": True,
                        "risk_category": "long_exposure_risk",
                        "risk_direction": "downside",
                        "risk_severity": "high",
                    },
                ),
                _atomic("whipsaw", active=False),
            ],
        )
    )
    unreliable = calculator.calculate(
        _input(
            domain_code="risk_state",
            output_mode="state",
            params=params,
            atomic_values=[
                _atomic("shock_down", active=False),
                _atomic(
                    "whipsaw",
                    value_json={
                        "condition_met": True,
                        "risk_category": "signal_reliability_risk",
                        "risk_direction": "two_sided",
                        "risk_severity": "high",
                    },
                ),
            ],
        )
    )

    assert classifiable.values["state_code"] == "risk_elevated_classifiable"
    assert unreliable.values["state_code"] == "risk_high_signal_unreliable"
