from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from apps.strategy_calculator.contracts import CalculatorInput, CalculatorType
from apps.strategy_calculator.domain_signal import (
    GroupedAtomicAggregationCalculator,
    GroupedAtomicAggregationV2Calculator,
    GroupedAtomicAggregationV3Calculator,
)


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


def _atomic(
    signal_code: str,
    *,
    active: bool = True,
    direction: str = "neutral",
    value_json: dict | None = None,
    evidence_items: list[dict] | None = None,
) -> dict:
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
        "evidence_items": evidence_items or [],
    }


def _pivot_evidence(*, side: str, timeframe: str = "1d", window: str = "365") -> list[dict]:
    prefix = f"structure_pivot_{side}"
    suffix = f"{timeframe}_{window}"
    return [
        {
            "evidence_type": "structure_pivot_atomic_condition",
            "used_features": [
                {"feature_code": f"{prefix}_lower_{suffix}", "observed_value": "70000"},
                {"feature_code": f"{prefix}_upper_{suffix}", "observed_value": "72000"},
                {"feature_code": f"{prefix}_core_{suffix}", "observed_value": "71000"},
                {"feature_code": f"{prefix}_strength_{suffix}", "observed_value": "0.8"},
                {"feature_code": f"{prefix}_status_{suffix}", "observed_value": "hold"},
                {"feature_code": f"structure_pivot_distance_to_{side}_pct_{suffix}", "observed_value": "0.01"},
            ],
        }
    ]


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
            "structure_historical_major_zone_valid",
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
    assert output.values["coverage_ratio"] == Decimal("1")
    assert summary["support_zone"] == {"lower": "49000", "upper": "50000"}
    assert summary["resistance_zone"] == {"lower": "59000", "upper": "60000"}
    assert summary["current_zone_position"] == "near_support"
    assert "historical_major_reference" not in summary


def test_grouped_atomic_structure_keeps_selected_invalid_historical_reference_as_optional_block() -> None:
    calculator = GroupedAtomicAggregationCalculator()
    params = {
        "domain_type": "structure",
        "allowed_atomic_signal_codes": [
            "structure_major_near_support",
            "structure_minor_range_middle",
            "structure_historical_major_zone_valid",
        ],
        "required_atomic_signal_codes": [],
    }

    output = calculator.calculate(
        _input(
            domain_code="structure",
            output_mode="state",
            params=params,
            atomic_values=[
                _atomic("structure_major_near_support"),
                _atomic("structure_minor_range_middle"),
                _atomic("structure_historical_major_zone_valid", active=False),
            ],
        )
    )

    summary = output.evidence_items[0]["summary"]
    reference = summary["historical_major_reference"]
    assert output.values["state_code"] == "structure_major_near_support_minor_range_middle"
    assert reference["is_valid"] is False
    assert reference["reason_code"] == "historical_major_reference_invalid_or_missing"
    assert reference["zone"] is None
    assert reference["should_mention_in_evidence"] is False
    assert "720 天历史大结构参考位" not in output.values["evidence_text_zh"]


def test_grouped_atomic_structure_keeps_far_historical_reference_out_of_evidence_text() -> None:
    calculator = GroupedAtomicAggregationCalculator()
    params = {
        "domain_type": "structure",
        "allowed_atomic_signal_codes": [
            "structure_major_lower_half",
            "structure_minor_range_middle",
            "structure_historical_major_zone_valid",
            "structure_historical_major_near_zone",
            "structure_historical_major_support_like",
            "structure_historical_major_resistance_like",
            "structure_historical_major_role_flip_candidate",
            "structure_historical_major_far_from_zone",
        ],
        "required_atomic_signal_codes": [],
    }
    historical_snapshot = {
        "condition_met": True,
        "feature_values": {
            "structure_historical_major_zone_lower_1d_720": {
                "feature_value_id": 11,
                "value": "54000",
                "value_type": "decimal",
            },
            "structure_historical_major_zone_upper_1d_720": {
                "feature_value_id": 12,
                "value": "63000",
                "value_type": "decimal",
            },
            "structure_historical_major_zone_role_1d_720": {
                "feature_value_id": 13,
                "value": "support_like",
                "value_type": "text",
            },
            "structure_historical_major_distance_to_zone_pct_1d_720": {
                "feature_value_id": 14,
                "value": "0.39",
                "value_type": "decimal",
            },
            "structure_historical_major_zone_test_count_1d_720": {
                "feature_value_id": 15,
                "value": "106",
                "value_type": "integer",
            },
        },
    }

    output = calculator.calculate(
        _input(
            domain_code="structure",
            output_mode="state",
            params=params,
            atomic_values=[
                _atomic("structure_major_lower_half"),
                _atomic("structure_minor_range_middle"),
                _atomic("structure_historical_major_zone_valid", value_json=historical_snapshot),
                _atomic("structure_historical_major_near_zone", value_json={"condition_met": False}),
                _atomic("structure_historical_major_support_like", value_json={"condition_met": True}),
                _atomic("structure_historical_major_resistance_like", value_json={"condition_met": False}),
                _atomic("structure_historical_major_role_flip_candidate", value_json={"condition_met": False}),
                _atomic("structure_historical_major_far_from_zone", value_json={"condition_met": True}),
            ],
        )
    )

    summary = output.evidence_items[0]["summary"]
    reference = summary["historical_major_reference"]
    assert output.values["state_code"] == "structure_major_lower_half_minor_range_middle"
    assert reference["is_valid"] is True
    assert reference["is_far"] is True
    assert reference["role_zh"] == "更像长周期支撑"
    assert reference["zone"] == {"lower": "54000", "upper": "63000"}
    assert reference["should_mention_in_evidence"] is False
    assert "720 天历史大结构参考位" not in output.values["evidence_text_zh"]


def test_grouped_atomic_structure_mentions_near_historical_reference_without_changing_state() -> None:
    calculator = GroupedAtomicAggregationCalculator()
    params = {
        "domain_type": "structure",
        "allowed_atomic_signal_codes": [
            "structure_major_lower_half",
            "structure_minor_range_middle",
            "structure_historical_major_zone_valid",
            "structure_historical_major_near_zone",
            "structure_historical_major_support_like",
            "structure_historical_major_resistance_like",
            "structure_historical_major_role_flip_candidate",
            "structure_historical_major_far_from_zone",
        ],
        "required_atomic_signal_codes": [],
    }
    historical_snapshot = {
        "condition_met": True,
        "feature_values": {
            "structure_historical_major_zone_lower_1d_720": {
                "feature_value_id": 21,
                "value": "58000",
                "value_type": "decimal",
            },
            "structure_historical_major_zone_upper_1d_720": {
                "feature_value_id": 22,
                "value": "74000",
                "value_type": "decimal",
            },
            "structure_historical_major_zone_role_1d_720": {
                "feature_value_id": 23,
                "value": "support_like",
                "value_type": "text",
            },
            "structure_historical_major_distance_to_zone_pct_1d_720": {
                "feature_value_id": 24,
                "value": "0.02",
                "value_type": "decimal",
            },
        },
    }

    output = calculator.calculate(
        _input(
            domain_code="structure",
            output_mode="state",
            params=params,
            atomic_values=[
                _atomic("structure_major_lower_half"),
                _atomic("structure_minor_range_middle"),
                _atomic("structure_historical_major_zone_valid", value_json=historical_snapshot),
                _atomic("structure_historical_major_near_zone", value_json={"condition_met": True}),
                _atomic("structure_historical_major_support_like", value_json={"condition_met": True}),
                _atomic("structure_historical_major_resistance_like", value_json={"condition_met": False}),
                _atomic("structure_historical_major_role_flip_candidate", value_json={"condition_met": False}),
                _atomic("structure_historical_major_far_from_zone", value_json={"condition_met": False}),
            ],
        )
    )

    summary = output.evidence_items[0]["summary"]
    reference = summary["historical_major_reference"]
    assert output.values["direction"] == "neutral"
    assert output.values["state_code"] == "structure_major_lower_half_minor_range_middle"
    assert reference["is_valid"] is True
    assert reference["is_near"] is True
    assert reference["should_mention_in_evidence"] is True
    assert "720 天历史大结构参考位" in output.values["evidence_text_zh"]
    assert "长周期支撑" in output.values["evidence_text_zh"]


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


def test_grouped_atomic_structure_v2_outputs_major_support_breakdown_confirmed() -> None:
    calculator = GroupedAtomicAggregationV2Calculator()
    params = {
        "domain_type": "structure",
        "allowed_atomic_signal_codes": [
            "structure_major_support_breakdown_candidate",
            "structure_major_support_breakdown_confirmed",
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
                _atomic("structure_major_support_breakdown_candidate", direction="bearish"),
                _atomic("structure_major_support_breakdown_confirmed", direction="bearish"),
                _atomic("structure_minor_range_middle"),
            ],
        )
    )

    summary = output.evidence_items[0]["summary"]
    semantic = summary["structure_state_v2"]
    assert output.values["direction"] == "bearish"
    assert output.values["state_code"] == "structure_major_support_breakdown_confirmed"
    assert output.values["strength"] == Decimal("0.90")
    assert semantic["state_zh"] == "1d 大支撑确认跌破"
    assert semantic["trigger_signal_code"] == "structure_major_support_breakdown_confirmed"
    assert summary["legacy_state_code"] == "structure_major_breakdown_down"


def test_grouped_atomic_structure_v2_outputs_major_resistance_holds_without_trade_action() -> None:
    calculator = GroupedAtomicAggregationV2Calculator()
    params = {
        "domain_type": "structure",
        "allowed_atomic_signal_codes": [
            "structure_major_resistance_holds",
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
                _atomic("structure_major_resistance_holds"),
                _atomic("structure_minor_range_middle"),
            ],
        )
    )

    summary = output.evidence_items[0]["summary"]
    semantic = summary["structure_state_v2"]
    assert output.values["direction"] == "neutral"
    assert output.values["state_code"] == "structure_major_resistance_holds"
    assert semantic["state_zh"] == "1d 大压力压住"
    assert "不输出交易动作" in output.values["evidence_text_zh"]



def test_grouped_atomic_structure_v2_records_support_resistance_context_without_changing_primary_state() -> None:
    calculator = GroupedAtomicAggregationV2Calculator()
    params = {
        "domain_type": "structure",
        "allowed_atomic_signal_codes": [
            "structure_major_support_holds",
            "structure_major_resistance_holds",
            "structure_minor_support_holds",
            "structure_minor_resistance_holds",
        ],
        "required_atomic_signal_codes": [],
    }

    output = calculator.calculate(
        _input(
            domain_code="structure",
            output_mode="state",
            params=params,
            atomic_values=[
                _atomic("structure_major_support_holds"),
                _atomic("structure_major_resistance_holds"),
                _atomic("structure_minor_support_holds"),
                _atomic("structure_minor_resistance_holds"),
            ],
        )
    )

    summary = output.evidence_items[0]["summary"]
    context = summary["support_resistance_context"]
    assert output.values["state_code"] == "structure_major_support_holds"
    assert context["has_major_support"] is True
    assert context["has_major_resistance"] is True
    assert context["has_minor_support"] is True
    assert context["has_minor_resistance"] is True
    assert context["major_support_resistance_conflict"] is True
    assert context["minor_support_resistance_conflict"] is True
    assert context["any_support_resistance_conflict"] is True
    assert list(context["active_context_signal_codes"]) == [
        "structure_major_support_holds",
        "structure_major_resistance_holds",
        "structure_minor_support_holds",
        "structure_minor_resistance_holds",
    ]
    assert "\u8865\u5145\u4e8b\u5b9e" in output.values["evidence_text_zh"]
    assert "\u4e0d\u662f\u5355\u8fb9\u7ed3\u6784" in output.values["evidence_text_zh"]


def test_grouped_atomic_structure_v3_outputs_between_support_resistance_when_both_sides_exist() -> None:
    calculator = GroupedAtomicAggregationV3Calculator()
    params = {
        "domain_type": "structure",
        "allowed_atomic_signal_codes": [
            "structure_pivot_major_support_holds",
            "structure_pivot_major_resistance_holds",
            "structure_pivot_major_between_support_resistance",
            "structure_pivot_minor_unclear",
        ],
        "required_atomic_signal_codes": [],
    }

    output = calculator.calculate(
        _input(
            domain_code="structure",
            output_mode="directional",
            params=params,
            atomic_values=[
                _atomic("structure_pivot_major_support_holds", evidence_items=_pivot_evidence(side="support")),
                _atomic("structure_pivot_major_resistance_holds", evidence_items=_pivot_evidence(side="resistance")),
                _atomic("structure_pivot_major_between_support_resistance"),
                _atomic("structure_pivot_minor_unclear"),
            ],
        )
    )

    summary = output.evidence_items[0]["summary"]
    evidence = summary["structure_evidence"]
    assert output.values["direction"] == "neutral"
    assert output.values["state_code"] == "structure_pivot_major_between_support_resistance"
    assert summary["current_zone_position"] == "between_support_resistance"
    assert evidence["major"]["support_holds"] is True
    assert evidence["major"]["resistance_holds"] is True
    assert evidence["major"]["between_support_resistance"] is True
    assert summary["support_zone"] == {
        "lower": "70000",
        "upper": "72000",
        "core": "71000",
        "strength": "0.8",
        "status": "hold",
        "distance_pct": "0.01",
    }
    assert summary["resistance_zone"]["lower"] == "70000"


def test_grouped_atomic_structure_v3_outputs_confirmed_breakdown_as_directional_fact() -> None:
    calculator = GroupedAtomicAggregationV3Calculator()
    params = {
        "domain_type": "structure",
        "allowed_atomic_signal_codes": [
            "structure_pivot_major_support_breakdown_confirmed",
            "structure_pivot_minor_unclear",
        ],
        "required_atomic_signal_codes": [],
    }

    output = calculator.calculate(
        _input(
            domain_code="structure",
            output_mode="directional",
            params=params,
            atomic_values=[
                _atomic("structure_pivot_major_support_breakdown_confirmed", direction="bearish"),
                _atomic("structure_pivot_minor_unclear"),
            ],
        )
    )

    evidence = output.evidence_items[0]["summary"]["structure_evidence"]
    assert output.values["direction"] == "bearish"
    assert output.values["state_code"] == "structure_pivot_major_support_breakdown_confirmed"
    assert output.values["strength"] == Decimal("0.85")
    assert evidence["major"]["support_breakdown_confirmed"] is True


def test_grouped_atomic_structure_v3_keeps_breakdown_candidate_neutral() -> None:
    calculator = GroupedAtomicAggregationV3Calculator()
    params = {
        "domain_type": "structure",
        "allowed_atomic_signal_codes": [
            "structure_pivot_major_support_breakdown_candidate",
            "structure_pivot_minor_unclear",
        ],
        "required_atomic_signal_codes": [],
    }

    output = calculator.calculate(
        _input(
            domain_code="structure",
            output_mode="directional",
            params=params,
            atomic_values=[
                _atomic("structure_pivot_major_support_breakdown_candidate", direction="bearish"),
                _atomic("structure_pivot_minor_unclear"),
            ],
        )
    )

    evidence = output.evidence_items[0]["summary"]["structure_evidence"]
    assert output.values["direction"] == "neutral"
    assert output.values["state_code"] == "structure_pivot_major_support_breakdown_candidate"
    assert output.values["strength"] == Decimal("0.65")
    assert evidence["major"]["support_breakdown_candidate"] is True


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


def test_grouped_atomic_structure_outputs_interpretable_support_and_pressure_evidence() -> None:
    calculator = GroupedAtomicAggregationCalculator()
    params = {
        "domain_type": "structure",
        "allowed_atomic_signal_codes": [
            "structure_major_support_valid",
            "structure_major_near_support",
            "structure_minor_resistance_valid",
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
                _atomic("structure_major_support_valid"),
                _atomic("structure_major_near_support"),
                _atomic("structure_minor_resistance_valid"),
                _atomic("structure_minor_near_resistance"),
            ],
        )
    )

    evidence = output.evidence_items[0]["summary"]["structure_evidence"]
    assert output.values["state_code"] == "structure_major_near_support_minor_near_resistance"
    assert evidence["primary_state_zh"] == "大结构靠近支撑"
    assert evidence["major"]["support_holds"] is True
    assert evidence["minor"]["resistance_holds"] is True
    assert list(evidence["facts_zh"]) == ["1d 大结构支撑仍有效", "4h 小结构压力仍有效"]


def test_grouped_atomic_structure_outputs_break_candidates_as_facts_without_changing_state_contract() -> None:
    calculator = GroupedAtomicAggregationCalculator()
    params = {
        "domain_type": "structure",
        "allowed_atomic_signal_codes": [
            "structure_major_breakdown_down",
            "structure_minor_breakout_up",
        ],
        "required_atomic_signal_codes": [],
    }

    output = calculator.calculate(
        _input(
            domain_code="structure",
            output_mode="state",
            params=params,
            atomic_values=[
                _atomic("structure_major_breakdown_down"),
                _atomic("structure_minor_breakout_up"),
            ],
        )
    )

    evidence = output.evidence_items[0]["summary"]["structure_evidence"]
    assert output.values["direction"] == "bearish"
    assert output.values["state_code"] == "structure_major_breakdown_down"
    assert evidence["primary_state_zh"] == "大结构支撑跌破候选"
    assert evidence["major"]["support_breakdown_candidate"] is True
    assert evidence["minor"]["resistance_breakout_candidate"] is True
    assert list(evidence["facts_zh"]) == ["1d 大结构支撑跌破候选", "4h 小结构压力突破候选"]


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
