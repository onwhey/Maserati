from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from apps.strategy_calculator.contracts import (
    CalculationStatus,
    CalculatorInput,
    CalculatorMetadata,
    CalculatorOutput,
    CalculatorType,
)
from apps.strategy_calculator.errors import CalculatorNotFoundError, DuplicateCalculatorError, InvalidCalculatorContractError
from apps.strategy_calculator.registry import CalculatorRegistry


class ConstantCalculator:
    def __init__(self, *, name: str = "constant_feature", version: str = "1.0.0") -> None:
        self.metadata = CalculatorMetadata(
            algorithm_name=name,
            algorithm_version=version,
            calculator_type=CalculatorType.FEATURE_LAYER,
            input_schema_version="1.0",
            output_schema_version="1.0",
            deterministic=True,
            supports_dry_run=True,
            algorithm_requirement_document_path="docs/requirements/feature_layer/constant_feature.md",
            implementation_document_path="docs/implementation/feature_layer/constant_feature__1.0.0.md",
        )

    def calculate(self, calculation_input: CalculatorInput) -> CalculatorOutput:
        return CalculatorOutput.succeeded(
            output_schema_version=self.metadata.output_schema_version,
            values={"value": Decimal("1.25")},
            evidence_items=({"source": "test"},),
        )


def test_registry_resolves_exact_algorithm_identity() -> None:
    registry = CalculatorRegistry()
    calculator = ConstantCalculator()
    registry.register(calculator)

    resolved = registry.resolve(
        calculator_type=CalculatorType.FEATURE_LAYER,
        algorithm_name="constant_feature",
        algorithm_version="1.0.0",
    )

    assert resolved is calculator


def test_registry_does_not_fallback_to_other_version() -> None:
    registry = CalculatorRegistry()
    registry.register(ConstantCalculator(version="1.0.0"))

    with pytest.raises(CalculatorNotFoundError):
        registry.resolve(
            calculator_type=CalculatorType.FEATURE_LAYER,
            algorithm_name="constant_feature",
            algorithm_version="2.0.0",
        )


def test_registry_rejects_duplicate_algorithm_identity() -> None:
    registry = CalculatorRegistry()
    registry.register(ConstantCalculator())

    with pytest.raises(DuplicateCalculatorError):
        registry.register(ConstantCalculator())


def test_calculator_input_freezes_nested_params() -> None:
    calculation_input = CalculatorInput(
        calculator_type=CalculatorType.FEATURE_LAYER,
        input_schema_version="1.0",
        output_schema_version="1.0",
        frozen_params={"window": 20},
        values={"items": [1, 2, 3]},
    )

    with pytest.raises(TypeError):
        calculation_input.frozen_params["window"] = 60
    with pytest.raises(FrozenInstanceError):
        calculation_input.params_hash = "changed"


def test_calculator_output_rejects_nan_and_failed_without_error_code() -> None:
    with pytest.raises(InvalidCalculatorContractError):
        CalculatorOutput.succeeded(output_schema_version="1.0", values={"value": float("nan")})

    with pytest.raises(InvalidCalculatorContractError):
        CalculatorOutput(
            calculation_status=CalculationStatus.FAILED,
            output_schema_version="1.0",
        )


def test_calculator_input_rejects_non_utc_time_and_non_data_object() -> None:
    with pytest.raises(InvalidCalculatorContractError):
        CalculatorInput(
            calculator_type=CalculatorType.FEATURE_LAYER,
            input_schema_version="1.0",
            output_schema_version="1.0",
            business_time_utc=datetime(2026, 1, 1, tzinfo=timezone(timedelta(hours=8))),
        )

    with pytest.raises(InvalidCalculatorContractError):
        CalculatorInput(
            calculator_type=CalculatorType.FEATURE_LAYER,
            input_schema_version="1.0",
            output_schema_version="1.0",
            values={"forbidden": object()},
        )


def test_calculator_input_rejects_params_hash_mismatch() -> None:
    with pytest.raises(InvalidCalculatorContractError):
        CalculatorInput(
            calculator_type=CalculatorType.FEATURE_LAYER,
            input_schema_version="1.0",
            output_schema_version="1.0",
            business_time_utc=datetime(2026, 1, 1, tzinfo=UTC),
            frozen_params={"window": 20},
            params_hash="stale-hash",
        )


def test_registry_becomes_read_only_after_first_resolution() -> None:
    registry = CalculatorRegistry()
    registry.register(ConstantCalculator())
    registry.resolve(
        calculator_type=CalculatorType.FEATURE_LAYER,
        algorithm_name="constant_feature",
        algorithm_version="1.0.0",
    )

    with pytest.raises(InvalidCalculatorContractError):
        registry.register(ConstantCalculator(name="late_calculator"))
