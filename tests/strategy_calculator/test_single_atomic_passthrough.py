from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from apps.strategy_calculator.contracts import CalculatorInput, CalculatorType
from apps.strategy_calculator.domain_signal import SingleAtomicPassthroughCalculator


def calculator_input(*, output_mode: str = "directional", direction: str = "bullish") -> CalculatorInput:
    return CalculatorInput(
        calculator_type=CalculatorType.DOMAIN_SIGNAL,
        input_schema_version="1.0",
        output_schema_version="1.0",
        upstream_refs={"atomic_signal_set_id": 1, "atomic_signal_value_ids": [10]},
        business_time_utc=datetime(2026, 1, 1, 8, tzinfo=UTC),
        market_identity={"exchange": "binance", "market_type": "usds_m_futures", "symbol": "BTCUSDT"},
        frozen_params={"state_code_when_active": "high", "state_code_when_inactive": "normal"},
        values={
            "domain_code": "trend",
            "output_mode": output_mode,
            "atomic_values": [
                {
                    "atomic_signal_value_id": 10,
                    "signal_code": "atomic_trend",
                    "direction": direction,
                    "strength": Decimal("0.8"),
                    "is_valid": True,
                }
            ],
        },
        evidence_summary={"definition_hash": "hash"},
    )


def test_single_atomic_passthrough_directional_contract() -> None:
    output = SingleAtomicPassthroughCalculator().calculate(calculator_input())

    assert output.calculation_status == "succeeded"
    assert output.values["direction"] == "bullish"
    assert output.values["state_code"] == ""
    assert output.values["strength"] == Decimal("0.8")
    assert output.values["coverage_ratio"] == Decimal("1")
    assert output.values["agreement_ratio"] is None
    assert output.evidence_items


def test_single_atomic_passthrough_state_contract() -> None:
    output = SingleAtomicPassthroughCalculator().calculate(calculator_input(output_mode="state", direction="bearish"))

    assert output.calculation_status == "succeeded"
    assert output.values["direction"] == "none"
    assert output.values["state_code"] == "high"


def test_single_atomic_passthrough_requires_one_valid_atomic_input() -> None:
    bad_input = CalculatorInput(
        calculator_type=CalculatorType.DOMAIN_SIGNAL,
        input_schema_version="1.0",
        output_schema_version="1.0",
        values={"domain_code": "trend", "output_mode": "directional", "atomic_values": []},
    )

    output = SingleAtomicPassthroughCalculator().calculate(bad_input)

    assert output.calculation_status == "failed"
    assert output.error_code == "single_atomic_input_required"
