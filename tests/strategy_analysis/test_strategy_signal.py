from __future__ import annotations

from typing import Any

import pytest

from apps.alerts.models import AlertEvent
from apps.strategy_analysis.models import (
    AnalysisObjectStatus,
    DefinitionLifecycleStatus,
    DomainSignalValue,
    StrategyRouteAction,
    StrategyRouteDecision,
    StrategySignal,
    StrategySignalDirection,
)
from apps.strategy_analysis.services.strategy_signal import generate_strategy_signal
from apps.strategy_calculator.contracts import (
    CalculatorInput,
    CalculatorMetadata,
    CalculatorOutput,
    CalculatorType,
)
from apps.strategy_calculator.registry import CalculatorRegistry
from apps.strategy_calculator.utils import thaw_value
from tests.strategy_analysis.test_strategy_routing import build_routing_fixture, run_route


class FakeStrategySignalCalculator:
    metadata = CalculatorMetadata(
        algorithm_name="test_strategy_signal",
        algorithm_version="1.0.0",
        calculator_type=CalculatorType.STRATEGY_SIGNAL,
        input_schema_version="1.0",
        output_schema_version="1.0",
        deterministic=True,
        supports_dry_run=True,
        algorithm_requirement_document_path="docs/requirements/strategy/test_strategy.md",
        implementation_document_path="docs/implementation/strategy_signal/test_strategy__1.0.0.md",
        uses_input_weights=False,
    )

    def __init__(
        self,
        *,
        direction: str = StrategySignalDirection.BULLISH,
        failed: bool = False,
        invalid_weights: bool = False,
        unexpected_error: bool = False,
        failure_code: str = "test_strategy_calculation_failed",
        failure_message: str = "测试策略计算失败",
        evidence_text_zh: str = "测试策略基于已允许的领域事实形成标准化判断。",
        trade_price_condition: dict[str, Any] | None = None,
    ) -> None:
        self.direction = direction
        self.failed = failed
        self.invalid_weights = invalid_weights
        self.unexpected_error = unexpected_error
        self.failure_code = failure_code
        self.failure_message = failure_message
        self.evidence_text_zh = evidence_text_zh
        self.trade_price_condition = trade_price_condition
        self.calls = 0
        self.last_input: CalculatorInput | None = None

    def calculate(self, calculation_input: CalculatorInput) -> CalculatorOutput:
        self.calls += 1
        self.last_input = calculation_input
        if self.unexpected_error:
            raise RuntimeError("unexpected strategy failure")
        if self.failed:
            return CalculatorOutput.failed(
                output_schema_version="1.0",
                error_code=self.failure_code,
                error_message=self.failure_message,
            )
        values = thaw_value(calculation_input.values)
        domain_values = values["domain_values"]
        refs = [
            {
                "domain_code": value["domain_code"],
                "domain_signal_value_id": value["domain_signal_value_id"],
            }
            for value in domain_values
        ]
        weights: dict[str, str] = {"trend": "1"} if self.invalid_weights else {}
        output_values: dict[str, Any] = {
            "direction": self.direction,
            "strength": "0.7",
            "confidence": "0.6",
            "confidence_semantics": "strategy_score",
            "prediction_horizon": "4h",
            "used_domain_signal_value_refs": refs,
            "actual_input_weights": weights,
            "aggregation_snapshot": {
                "input_domain_codes": [value["domain_code"] for value in domain_values],
                "final_direction": self.direction,
                "final_strength": "0.7",
                "final_confidence": "0.6",
            },
            "conflict_snapshot": {
                "has_conflict": self.direction == StrategySignalDirection.NEUTRAL,
                "conflicting_domain_codes": [],
                "effect": "none",
            },
            "evidence_text_zh": self.evidence_text_zh,
        }
        if self.trade_price_condition is not None:
            output_values["trade_price_condition"] = self.trade_price_condition
        return CalculatorOutput.succeeded(
            output_schema_version="1.0",
            values=output_values,
            evidence_items=(
                {
                    "type": "test_strategy_evidence",
                    "used_domain_signal_value_ids": [ref["domain_signal_value_id"] for ref in refs],
                },
            ),
            calculation_summary={"input_count": len(refs)},
        )


def signal_registry(calculator: FakeStrategySignalCalculator | None = None) -> tuple[CalculatorRegistry, FakeStrategySignalCalculator]:
    calculator = calculator or FakeStrategySignalCalculator()
    registry = CalculatorRegistry()
    registry.register(calculator)
    return registry, calculator


def selected_fixture() -> dict[str, Any]:
    fixture = build_routing_fixture()
    route_result = run_route(fixture)
    assert route_result.status == "succeeded"
    fixture["decision"] = StrategyRouteDecision.objects.get(id=route_result.data["strategy_route_decision_id"])
    return fixture


def run_signal(
    fixture: dict[str, Any],
    *,
    registry: CalculatorRegistry,
    key: str = "strategy-signal-request",
    dry_run: bool = False,
    decision_id: int | None = None,
):
    return generate_strategy_signal(
        strategy_route_decision_id=decision_id or fixture["decision"].id,
        strategy_analysis_release_id=fixture["release"].id,
        strategy_analysis_release_hash=fixture["release"].release_hash,
        expected_strategy_definition_hash=fixture["primary"].definition_hash,
        business_request_key=key,
        trace_id="trace",
        trigger_source="test",
        dry_run=dry_run,
        registry=registry,
    )


@pytest.mark.django_db
def test_strategy_signal_executes_only_selected_strategy_and_persists_standard_output() -> None:
    fixture = selected_fixture()
    registry, calculator = signal_registry()

    result = run_signal(fixture, registry=registry)

    assert result.status == "succeeded"
    signal = StrategySignal.objects.get()
    assert signal.strategy_route_decision_id == fixture["decision"].id
    assert signal.strategy_definition_id == fixture["primary"].id
    assert signal.market_regime_snapshot_id == fixture["snapshot_id"]
    assert signal.domain_signal_set_id == signal.market_regime_snapshot.domain_signal_set_id
    assert signal.direction == StrategySignalDirection.BULLISH
    assert str(signal.strength) == "0.700000000000000000"
    assert str(signal.confidence) == "0.600000000000000000"
    assert signal.confidence_semantics == "strategy_score"
    assert signal.prediction_horizon == "4h"
    assert signal.trade_price_condition == {}
    assert signal.status == AnalysisObjectStatus.CREATED
    assert signal.is_usable is True
    assert signal.allows_strategy_signal_quality is True
    assert calculator.calls == 1
    assert AlertEvent.objects.filter(source_module="StrategySignal").count() == 0


@pytest.mark.django_db
def test_strategy_signal_calculator_receives_only_allowed_domains_and_no_market_regime() -> None:
    fixture = selected_fixture()
    registry, calculator = signal_registry()

    run_signal(fixture, registry=registry)

    assert calculator.last_input is not None
    payload = thaw_value(calculator.last_input.values)
    assert [value["domain_code"] for value in payload["domain_values"]] == ["trend"]
    assert "market_regime_snapshot" not in payload
    assert "regime_code" not in payload
    assert "market_regime_snapshot_id" not in thaw_value(calculator.last_input.upstream_refs)


@pytest.mark.django_db
def test_strategy_signal_normal_neutral_is_created_and_consumable() -> None:
    fixture = selected_fixture()
    registry, _calculator = signal_registry(FakeStrategySignalCalculator(direction=StrategySignalDirection.NEUTRAL))

    result = run_signal(fixture, registry=registry)

    signal = StrategySignal.objects.get()
    assert result.status == "succeeded"
    assert signal.direction == StrategySignalDirection.NEUTRAL
    assert signal.is_usable is True
    assert signal.allows_strategy_signal_quality is True
    assert AlertEvent.objects.filter(source_module="StrategySignal").count() == 0


@pytest.mark.django_db
def test_no_strategy_route_is_blocked_without_calling_calculator() -> None:
    fixture = build_routing_fixture(
        rule_specs=[
            {
                "code": "explicit_no_strategy",
                "priority": 1,
                "action": StrategyRouteAction.NO_STRATEGY,
                "conditions": {},
                "strategy": None,
            }
        ]
    )
    route_result = run_route(fixture)
    fixture["decision"] = StrategyRouteDecision.objects.get(id=route_result.data["strategy_route_decision_id"])
    registry, calculator = signal_registry()

    result = run_signal(fixture, registry=registry)

    assert result.status == "blocked"
    assert result.reason_code == "strategy_route_decision_not_consumable"
    assert calculator.calls == 0
    assert StrategySignal.objects.count() == 0
    assert AlertEvent.objects.filter(source_module="StrategySignal").count() == 1


@pytest.mark.django_db
def test_required_domain_missing_blocks_before_calculator() -> None:
    fixture = selected_fixture()
    DomainSignalValue.objects.filter(
        domain_signal_set=fixture["decision"].market_regime_snapshot.domain_signal_set,
        domain_code="trend",
    ).delete()
    registry, calculator = signal_registry()

    result = run_signal(fixture, registry=registry)

    assert result.status == "blocked"
    assert result.reason_code == "strategy_required_domain_missing"
    assert calculator.calls == 0
    assert StrategySignal.objects.count() == 0


@pytest.mark.django_db
def test_upstream_consumption_flags_must_still_allow_strategy_signal() -> None:
    fixture = selected_fixture()
    snapshot = fixture["decision"].market_regime_snapshot
    snapshot.allows_strategy_routing = False
    snapshot.save(update_fields=["allows_strategy_routing"])
    registry, calculator = signal_registry()

    result = run_signal(fixture, registry=registry)

    assert result.status == "blocked"
    assert result.reason_code == "strategy_upstream_chain_invalid"
    assert calculator.calls == 0
    assert StrategySignal.objects.count() == 0


@pytest.mark.django_db
def test_domain_set_consumption_flag_must_still_allow_market_regime_chain() -> None:
    fixture = selected_fixture()
    domain_set = fixture["decision"].market_regime_snapshot.domain_signal_set
    domain_set.allows_market_regime = False
    domain_set.save(update_fields=["allows_market_regime", "updated_at_utc"])
    registry, calculator = signal_registry()

    result = run_signal(fixture, registry=registry)

    assert result.status == "blocked"
    assert result.reason_code == "strategy_upstream_chain_invalid"
    assert calculator.calls == 0
    assert StrategySignal.objects.count() == 0


@pytest.mark.django_db
def test_disabled_selected_definition_blocks_before_calculator() -> None:
    fixture = selected_fixture()
    fixture["primary"].status = DefinitionLifecycleStatus.DISABLED
    fixture["primary"].enabled = False
    fixture["primary"].save(update_fields=["status", "enabled", "updated_at_utc"])
    registry, calculator = signal_registry()

    result = run_signal(fixture, registry=registry)

    assert result.status == "blocked"
    assert result.reason_code == "strategy_definition_not_selectable"
    assert calculator.calls == 0
    assert StrategySignal.objects.count() == 0


@pytest.mark.django_db
def test_missing_exact_calculator_blocks_without_signal() -> None:
    fixture = selected_fixture()

    result = run_signal(fixture, registry=CalculatorRegistry())

    assert result.status == "blocked"
    assert result.reason_code == "strategy_definition_or_calculator_invalid"
    assert StrategySignal.objects.count() == 0


@pytest.mark.django_db
def test_calculator_failed_persists_non_consumable_failed_signal() -> None:
    fixture = selected_fixture()
    registry, calculator = signal_registry(FakeStrategySignalCalculator(failed=True))

    result = run_signal(fixture, registry=registry)

    signal = StrategySignal.objects.get()
    assert result.status == "failed"
    assert signal.status == AnalysisObjectStatus.FAILED
    assert signal.direction == StrategySignalDirection.NONE
    assert signal.is_usable is False
    assert signal.allows_strategy_signal_quality is False
    assert signal.error_code == "test_strategy_calculation_failed"
    assert calculator.calls == 1
    assert AlertEvent.objects.filter(source_module="StrategySignal", event_type="strategy_signal_failed").count() == 1


@pytest.mark.django_db
def test_long_calculator_failure_text_is_trimmed_and_still_persisted_as_failed() -> None:
    fixture = selected_fixture()
    registry, _calculator = signal_registry(
        FakeStrategySignalCalculator(
            failed=True,
            failure_code="x" * 200,
            failure_message="y" * 800,
        )
    )

    result = run_signal(fixture, registry=registry)

    signal = StrategySignal.objects.get()
    assert result.status == "failed"
    assert signal.status == AnalysisObjectStatus.FAILED
    assert len(signal.error_code) <= 120
    assert len(signal.error_message) <= 500


@pytest.mark.django_db
def test_invalid_output_is_failed_not_neutral() -> None:
    fixture = selected_fixture()
    registry, _calculator = signal_registry(FakeStrategySignalCalculator(direction="enter_long"))

    result = run_signal(fixture, registry=registry)

    signal = StrategySignal.objects.get()
    assert result.status == "failed"
    assert signal.direction == StrategySignalDirection.NONE
    assert signal.error_code == "strategy_signal_output_invalid"
    assert signal.allows_strategy_signal_quality is False


@pytest.mark.django_db
def test_overlong_evidence_text_is_failed_not_database_error() -> None:
    fixture = selected_fixture()
    registry, _calculator = signal_registry(FakeStrategySignalCalculator(evidence_text_zh="证据" * 600))

    result = run_signal(fixture, registry=registry)

    signal = StrategySignal.objects.get()
    assert result.status == "failed"
    assert signal.error_code == "strategy_signal_output_invalid"
    assert signal.direction == StrategySignalDirection.NONE


@pytest.mark.django_db
def test_unexpected_calculator_error_is_persisted_as_failed() -> None:
    fixture = selected_fixture()
    registry, _calculator = signal_registry(FakeStrategySignalCalculator(unexpected_error=True))

    result = run_signal(fixture, registry=registry)

    signal = StrategySignal.objects.get()
    assert result.status == "failed"
    assert signal.error_code == "strategy_signal_calculator_unexpected_error"
    assert signal.direction == StrategySignalDirection.NONE


@pytest.mark.django_db
def test_request_identity_text_lengths_are_blocked_before_calculator() -> None:
    fixture = selected_fixture()
    registry, calculator = signal_registry()

    result = run_signal(fixture, registry=registry, key="x" * 192)

    assert result.status == "blocked"
    assert result.reason_code == "strategy_signal_request_invalid"
    assert calculator.calls == 0
    assert StrategySignal.objects.count() == 0


@pytest.mark.django_db
def test_hidden_weights_are_rejected_when_definition_disables_weights() -> None:
    fixture = selected_fixture()
    registry, _calculator = signal_registry(FakeStrategySignalCalculator(invalid_weights=True))

    result = run_signal(fixture, registry=registry)

    signal = StrategySignal.objects.get()
    assert result.status == "failed"
    assert signal.error_code == "strategy_signal_output_invalid"
    assert signal.actual_input_weights == {}


@pytest.mark.django_db
def test_strategy_signal_persists_standard_trade_price_condition() -> None:
    condition = {
        "condition_type": "near_support_only",
        "reference_price_zone": "支撑区附近",
        "acceptable_price_zone": {"lower": "49000", "upper": "50000"},
        "support_or_resistance_refs": ["structure.support.primary"],
        "allow_chasing": False,
        "reason_code": "long_pullback_support_entry",
        "reason_summary_zh": "只在支撑区附近考虑执行。",
    }
    fixture = selected_fixture()
    registry, _calculator = signal_registry(FakeStrategySignalCalculator(trade_price_condition=condition))

    result = run_signal(fixture, registry=registry)

    signal = StrategySignal.objects.get()
    assert result.status == "succeeded"
    assert signal.trade_price_condition == condition


@pytest.mark.django_db
def test_invalid_trade_price_condition_is_failed_signal() -> None:
    fixture = selected_fixture()
    registry, _calculator = signal_registry(
        FakeStrategySignalCalculator(trade_price_condition={"condition_type": "near_support_only"})
    )

    result = run_signal(fixture, registry=registry)

    signal = StrategySignal.objects.get()
    assert result.status == "failed"
    assert signal.error_code == "strategy_signal_output_invalid"
    assert signal.trade_price_condition == {}


@pytest.mark.django_db
def test_strategy_signal_is_idempotent_without_recalculation() -> None:
    fixture = selected_fixture()
    registry, calculator = signal_registry()

    first = run_signal(fixture, registry=registry)
    second = run_signal(fixture, registry=registry)

    assert first.data["strategy_signal_id"] == second.data["strategy_signal_id"]
    assert StrategySignal.objects.count() == 1
    assert calculator.calls == 1


@pytest.mark.django_db
def test_business_request_key_conflict_is_blocked_before_loading_other_decision() -> None:
    fixture = selected_fixture()
    registry, _calculator = signal_registry()
    first = run_signal(fixture, registry=registry)
    assert first.status == "succeeded"

    result = run_signal(fixture, registry=registry, decision_id=fixture["decision"].id + 999)

    assert result.status == "blocked"
    assert result.reason_code == "strategy_signal_idempotency_conflict"
    assert StrategySignal.objects.count() == 1


@pytest.mark.django_db
def test_dry_run_uses_same_calculator_but_never_persists_or_allows_downstream() -> None:
    fixture = selected_fixture()
    registry, calculator = signal_registry()

    result = run_signal(fixture, registry=registry, dry_run=True)

    assert result.status == "succeeded"
    assert result.data["persisted"] is False
    assert result.data["allows_strategy_signal_quality"] is False
    assert result.data["direction"] == StrategySignalDirection.BULLISH
    assert calculator.calls == 1
    assert StrategySignal.objects.count() == 0
    assert AlertEvent.objects.filter(source_module="StrategySignal").count() == 0
