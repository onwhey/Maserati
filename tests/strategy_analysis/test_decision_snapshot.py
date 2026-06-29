from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest
from django.utils import timezone

from apps.alerts.models import AlertEvent
from apps.strategy_analysis.default_decision_policy_definitions import DEFAULT_DECISION_POLICY_DEFINITIONS
from apps.strategy_analysis.definition_hashes import decision_policy_definition_hash
from apps.strategy_analysis.models import (
    AnalysisObjectStatus,
    DecisionPolicyDefinition,
    DecisionSnapshot,
    DecisionTargetIntent,
    DefinitionLifecycleStatus,
    DomainSignalSet,
    MarketRegimeSnapshot,
    ReleaseItemComponentType,
    StrategyAnalysisRelease,
    StrategyAnalysisReleaseActivation,
    StrategyAnalysisReleaseApproval,
    StrategyAnalysisReleaseItem,
    StrategyRouteDecision,
    StrategySignal,
    StrategySignalDirection,
    StrategySignalQualityResult,
    StrategySignalQualityRuleSet,
)
from apps.strategy_analysis.services.decision_snapshot import build_decision_snapshot
from apps.strategy_analysis.services.release import calculate_release_hash
from apps.strategy_calculator.contracts import CalculatorInput, CalculatorMetadata, CalculatorOutput, CalculatorType
from apps.strategy_calculator.decision_policy import PositionPolicyCalculator
from apps.strategy_calculator.registry import CalculatorRegistry
from apps.strategy_calculator.utils import stable_hash, thaw_value
from tests.strategy_analysis.test_strategy_routing import build_routing_fixture, run_route
from tests.strategy_analysis.test_strategy_signal import FakeStrategySignalCalculator, run_signal, signal_registry
from tests.strategy_analysis.test_strategy_signal_quality import (
    attach_quality_rule_set,
    create_quality_rule_set,
    run_quality,
)


class FakeDecisionPolicyCalculator:
    metadata = CalculatorMetadata(
        algorithm_name="test_decision_policy",
        algorithm_version="1.0.0",
        calculator_type=CalculatorType.DECISION_POLICY,
        input_schema_version="1.0",
        output_schema_version="1.0",
        deterministic=True,
        supports_dry_run=True,
        algorithm_requirement_document_path="docs/requirements/decision_snapshot/test_policy.md",
        implementation_document_path="docs/implementation/decision_snapshot/test_policy__1.0.0.md",
    )

    def __init__(
        self,
        *,
        target_intent: str | None = None,
        target_position_ratio: str | None = None,
        forbidden_output: bool = False,
        failed: bool = False,
        missing_reason: bool = False,
        unexpected_error: bool = False,
    ) -> None:
        self.target_intent = target_intent
        self.target_position_ratio = target_position_ratio
        self.forbidden_output = forbidden_output
        self.failed = failed
        self.missing_reason = missing_reason
        self.unexpected_error = unexpected_error
        self.calls = 0
        self.last_input: CalculatorInput | None = None

    def calculate(self, calculation_input: CalculatorInput) -> CalculatorOutput:
        self.calls += 1
        self.last_input = calculation_input
        if self.unexpected_error:
            raise RuntimeError("unexpected decision policy failure")
        if self.failed:
            return CalculatorOutput.failed(
                output_schema_version="1.0",
                error_code="test_decision_policy_failed",
                error_message="测试目标仓位决策失败",
            )
        values = thaw_value(calculation_input.values)
        direction = values["strategy_direction"]
        if self.target_intent or self.target_position_ratio is not None:
            intent = self.target_intent
            ratio = self.target_position_ratio
            if intent is None:
                intent = DecisionTargetIntent.TARGET_POSITION
        elif direction == StrategySignalDirection.BULLISH:
            intent = DecisionTargetIntent.TARGET_POSITION
            ratio = "0.5"
        elif direction == StrategySignalDirection.BEARISH:
            intent = DecisionTargetIntent.TARGET_POSITION
            ratio = "-0.5"
        else:
            intent = DecisionTargetIntent.NO_TRADE
            ratio = None
        output_values: dict[str, Any] = {
            "target_intent": intent,
            "target_position_ratio": ratio,
            "target_confidence": "0.6",
            "target_reason_code": "" if self.missing_reason else "test_policy_decision",
            "target_reason_summary_zh": "" if self.missing_reason else "测试目标仓位规则只根据标准化策略信号形成目标仓位语义。",
            "decision_calculation_snapshot": {
                "used_strategy_direction": direction,
                "used_strategy_confidence": values["strategy_confidence"],
            },
        }
        if self.forbidden_output:
            output_values["order_quantity"] = "1"
        return CalculatorOutput.succeeded(
            output_schema_version="1.0",
            values=output_values,
            evidence_items=(
                {
                    "type": "test_decision_policy",
                    "strategy_signal_quality_result_id": values["strategy_signal_quality_result_id"],
                },
            ),
            calculation_summary={"intent": intent},
        )


def decision_registry(
    calculator: FakeDecisionPolicyCalculator | None = None,
) -> tuple[CalculatorRegistry, FakeDecisionPolicyCalculator]:
    calculator = calculator or FakeDecisionPolicyCalculator()
    registry = CalculatorRegistry()
    registry.register(calculator)
    return registry, calculator


def create_decision_policy(
    *,
    enabled: bool = True,
    params: dict[str, Any] | None = None,
) -> DecisionPolicyDefinition:
    params = params or {"expires_after_seconds": 999999999}
    params_hash = stable_hash(params)
    definition_hash = decision_policy_definition_hash(
        policy_code="default_decision_policy",
        policy_version="1.0.0",
        algorithm_name="test_decision_policy",
        algorithm_version="1.0.0",
        input_schema_version="1.0",
        output_schema_version="1.0",
        target_schema_version="1.0",
        params_hash=params_hash,
    )
    return DecisionPolicyDefinition.objects.create(
        policy_code="default_decision_policy",
        policy_version="1.0.0",
        display_name="默认测试目标仓位规则",
        algorithm_name="test_decision_policy",
        algorithm_version="1.0.0",
        input_schema_version="1.0",
        output_schema_version="1.0",
        target_schema_version="1.0",
        params=params,
        params_hash=params_hash,
        definition_hash=definition_hash,
        status=DefinitionLifecycleStatus.ACTIVE if enabled else DefinitionLifecycleStatus.DISABLED,
        enabled=enabled,
    )


def create_position_policy_definition() -> DecisionPolicyDefinition:
    template = DEFAULT_DECISION_POLICY_DEFINITIONS[0]
    params_hash = stable_hash(template.params)
    definition_hash = decision_policy_definition_hash(
        policy_code=template.policy_code,
        policy_version=template.policy_version,
        algorithm_name=template.algorithm_name,
        algorithm_version=template.algorithm_version,
        input_schema_version=template.input_schema_version,
        output_schema_version=template.output_schema_version,
        target_schema_version=template.target_schema_version,
        params_hash=params_hash,
    )
    return DecisionPolicyDefinition.objects.create(
        policy_code=template.policy_code,
        policy_version=template.policy_version,
        display_name=template.display_name,
        description=template.description,
        algorithm_name=template.algorithm_name,
        algorithm_version=template.algorithm_version,
        input_schema_version=template.input_schema_version,
        output_schema_version=template.output_schema_version,
        target_schema_version=template.target_schema_version,
        params=template.params,
        params_hash=params_hash,
        definition_hash=definition_hash,
        status=DefinitionLifecycleStatus.ACTIVE,
        enabled=True,
    )


def attach_decision_policy(fixture: dict[str, Any], policy: DecisionPolicyDefinition) -> None:
    release: StrategyAnalysisRelease = fixture["release"]
    StrategyAnalysisReleaseItem.objects.create(
        release=release,
        component_type=ReleaseItemComponentType.DECISION_POLICY_DEFINITION,
        component_object_id=policy.id,
        component_code=policy.policy_code,
        definition_hash=policy.definition_hash,
        algorithm_name=policy.algorithm_name,
        algorithm_version=policy.algorithm_version,
        params_hash=policy.params_hash,
        payload_summary={"target_schema_version": policy.target_schema_version},
        sort_order=950,
    )
    release.release_hash = calculate_release_hash(release)
    release.save(update_fields=["release_hash", "updated_at_utc"])
    StrategyAnalysisReleaseApproval.objects.filter(release=release).update(release_hash=release.release_hash)
    StrategyAnalysisReleaseActivation.objects.filter(release=release).update(release_hash=release.release_hash)
    snapshot = MarketRegimeSnapshot.objects.get(id=fixture["snapshot_id"])
    DomainSignalSet.objects.filter(id=snapshot.domain_signal_set_id).update(release_hash=release.release_hash)
    MarketRegimeSnapshot.objects.filter(id=snapshot.id).update(release_hash=release.release_hash)
    fixture["release"].refresh_from_db()


def build_decision_fixture(
    *,
    strategy_direction: str = StrategySignalDirection.BULLISH,
    policy_enabled: bool = True,
    policy_params: dict[str, Any] | None = None,
    trade_price_condition: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], StrategySignalQualityRuleSet, StrategySignal, StrategySignalQualityResult, DecisionPolicyDefinition]:
    fixture = build_routing_fixture()
    rule_set = create_quality_rule_set()
    attach_quality_rule_set(fixture, rule_set)
    policy = create_decision_policy(enabled=policy_enabled, params=policy_params)
    attach_decision_policy(fixture, policy)
    route_result = run_route(fixture)
    assert route_result.status == "succeeded"
    fixture["decision"] = StrategyRouteDecision.objects.get(id=route_result.data["strategy_route_decision_id"])
    strategy_registry, _strategy_calculator = signal_registry(
        FakeStrategySignalCalculator(
            direction=strategy_direction,
            trade_price_condition=trade_price_condition,
        )
    )
    signal_result = run_signal(fixture, registry=strategy_registry)
    assert signal_result.status == "succeeded"
    signal = StrategySignal.objects.get(id=signal_result.data["strategy_signal_id"])
    quality_result = run_quality(signal=signal, release=fixture["release"], rule_set=rule_set)
    assert quality_result.status == "succeeded"
    quality = StrategySignalQualityResult.objects.get(id=quality_result.data["quality_result_id"])
    return fixture, rule_set, signal, quality, policy


def build_position_policy_decision_fixture(
    *,
    strategy_direction: str = StrategySignalDirection.BULLISH,
    trade_price_condition: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], StrategySignal, StrategySignalQualityResult, DecisionPolicyDefinition]:
    fixture = build_routing_fixture()
    rule_set = create_quality_rule_set()
    attach_quality_rule_set(fixture, rule_set)
    policy = create_position_policy_definition()
    attach_decision_policy(fixture, policy)
    route_result = run_route(fixture)
    assert route_result.status == "succeeded"
    fixture["decision"] = StrategyRouteDecision.objects.get(id=route_result.data["strategy_route_decision_id"])
    strategy_registry, _strategy_calculator = signal_registry(
        FakeStrategySignalCalculator(
            direction=strategy_direction,
            trade_price_condition=trade_price_condition,
        )
    )
    signal_result = run_signal(fixture, registry=strategy_registry)
    assert signal_result.status == "succeeded"
    signal = StrategySignal.objects.get(id=signal_result.data["strategy_signal_id"])
    quality_result = run_quality(signal=signal, release=fixture["release"], rule_set=rule_set)
    assert quality_result.status == "succeeded"
    quality = StrategySignalQualityResult.objects.get(id=quality_result.data["quality_result_id"])
    return fixture, signal, quality, policy


def run_decision(
    *,
    quality: StrategySignalQualityResult,
    release: StrategyAnalysisRelease,
    registry: CalculatorRegistry,
    key: str = "decision-snapshot-request",
    dry_run: bool = False,
):
    return build_decision_snapshot(
        strategy_signal_quality_result_id=quality.id,
        strategy_analysis_release_id=release.id,
        strategy_analysis_release_hash=release.release_hash,
        business_request_key=key,
        trace_id="trace",
        trigger_source="test",
        dry_run=dry_run,
        registry=registry,
    )


@pytest.mark.django_db
def test_decision_snapshot_creates_target_position_after_quality_passed() -> None:
    fixture, _rule_set, _signal, quality, policy = build_decision_fixture()
    registry, calculator = decision_registry()

    result = run_decision(quality=quality, release=fixture["release"], registry=registry)

    snapshot = DecisionSnapshot.objects.get()
    assert result.status == "succeeded"
    assert snapshot.strategy_signal_quality_result_id == quality.id
    assert snapshot.decision_policy_definition_id == policy.id
    assert snapshot.target_intent == DecisionTargetIntent.TARGET_POSITION
    assert str(snapshot.target_position_ratio) == "0.500000000000000000"
    assert snapshot.is_usable is True
    assert snapshot.allows_order_plan is True
    assert calculator.calls == 1
    assert AlertEvent.objects.filter(source_module="DecisionSnapshot").count() == 0


@pytest.mark.django_db
def test_decision_snapshot_consumes_quality_passed_signal_with_position_policy_v1() -> None:
    fixture, signal, quality, policy = build_position_policy_decision_fixture()
    StrategySignalQualityResult.objects.filter(id=quality.id).update(market_as_of_utc=timezone.now())
    quality.refresh_from_db()
    registry = CalculatorRegistry()
    registry.register(PositionPolicyCalculator())

    result = run_decision(quality=quality, release=fixture["release"], registry=registry)

    snapshot = DecisionSnapshot.objects.get()
    assert result.status == "succeeded"
    assert snapshot.strategy_signal_id == signal.id
    assert snapshot.strategy_signal_quality_result_id == quality.id
    assert snapshot.decision_policy_definition_id == policy.id
    assert snapshot.policy_code == "position_policy"
    assert snapshot.policy_version == "v1"
    assert snapshot.target_intent == DecisionTargetIntent.TARGET_POSITION
    assert str(snapshot.target_position_ratio) == "0.100000000000000000"
    assert snapshot.is_usable is True
    assert snapshot.allows_order_plan is True
    assert snapshot.input_snapshot["policy_code"] == "position_policy"
    assert "strategy_code" not in snapshot.input_snapshot


@pytest.mark.django_db
def test_decision_snapshot_supports_bearish_target_position() -> None:
    fixture, _rule_set, _signal, quality, _policy = build_decision_fixture(strategy_direction=StrategySignalDirection.BEARISH)
    registry, _calculator = decision_registry()

    result = run_decision(quality=quality, release=fixture["release"], registry=registry)

    snapshot = DecisionSnapshot.objects.get()
    assert result.status == "succeeded"
    assert snapshot.target_intent == DecisionTargetIntent.TARGET_POSITION
    assert str(snapshot.target_position_ratio) == "-0.500000000000000000"
    assert snapshot.allows_order_plan is True


@pytest.mark.django_db
def test_decision_snapshot_no_trade_does_not_allow_order_plan() -> None:
    fixture, _rule_set, _signal, quality, _policy = build_decision_fixture(strategy_direction=StrategySignalDirection.NEUTRAL)
    registry, _calculator = decision_registry()

    result = run_decision(quality=quality, release=fixture["release"], registry=registry)

    snapshot = DecisionSnapshot.objects.get()
    assert result.status == "succeeded"
    assert snapshot.target_intent == DecisionTargetIntent.NO_TRADE
    assert snapshot.target_position_ratio is None
    assert snapshot.is_usable is True
    assert snapshot.allows_order_plan is False
    assert AlertEvent.objects.filter(source_module="DecisionSnapshot").count() == 0


@pytest.mark.django_db
def test_decision_snapshot_no_target_change_does_not_allow_order_plan() -> None:
    fixture, _rule_set, _signal, quality, _policy = build_decision_fixture()
    registry, _calculator = decision_registry(
        FakeDecisionPolicyCalculator(target_intent=DecisionTargetIntent.NO_TARGET_CHANGE)
    )

    result = run_decision(quality=quality, release=fixture["release"], registry=registry)

    snapshot = DecisionSnapshot.objects.get()
    assert result.status == "succeeded"
    assert snapshot.target_intent == DecisionTargetIntent.NO_TARGET_CHANGE
    assert snapshot.target_position_ratio is None
    assert snapshot.is_usable is True
    assert snapshot.allows_order_plan is False
    assert AlertEvent.objects.filter(source_module="DecisionSnapshot").count() == 0


@pytest.mark.django_db
def test_decision_snapshot_calculator_receives_strategy_signal_not_market_analysis() -> None:
    fixture, _rule_set, signal, quality, _policy = build_decision_fixture()
    registry, calculator = decision_registry()

    run_decision(quality=quality, release=fixture["release"], registry=registry)

    assert calculator.last_input is not None
    payload = thaw_value(calculator.last_input.values)
    refs = thaw_value(calculator.last_input.upstream_refs)
    assert payload["strategy_direction"] == signal.direction
    assert "strategy_code" not in payload
    assert "market_regime_snapshot" not in payload
    assert "domain_signal_values" not in payload
    assert "trade_price_condition" not in payload
    assert "market_regime_snapshot_id" not in refs


@pytest.mark.django_db
def test_decision_snapshot_freezes_strategy_trade_price_condition_without_calculator_consumption() -> None:
    condition = {
        "condition_type": "near_support_only",
        "reference_price_zone": "支撑区附近",
        "acceptable_price_zone": {"lower": "49000", "upper": "50000"},
        "support_or_resistance_refs": ["structure.support.primary"],
        "allow_chasing": False,
        "reason_code": "long_pullback_support_entry",
        "reason_summary_zh": "只在支撑区附近考虑执行。",
    }
    fixture, _rule_set, signal, quality, _policy = build_decision_fixture(trade_price_condition=condition)
    registry, calculator = decision_registry()

    result = run_decision(quality=quality, release=fixture["release"], registry=registry)

    snapshot = DecisionSnapshot.objects.get()
    assert result.status == "succeeded"
    assert signal.trade_price_condition == condition
    assert snapshot.frozen_trade_price_condition == condition
    assert snapshot.frozen_trade_price_condition_hash
    assert snapshot.evidence_summary["has_frozen_trade_price_condition"] is True
    assert calculator.last_input is not None
    assert "trade_price_condition" not in thaw_value(calculator.last_input.values)


@pytest.mark.django_db
def test_decision_snapshot_blocks_when_quality_no_longer_allows_downstream() -> None:
    fixture, _rule_set, _signal, quality, _policy = build_decision_fixture()
    StrategySignalQualityResult.objects.filter(id=quality.id).update(
        status=AnalysisObjectStatus.BLOCKED,
        is_usable=False,
        allows_decision_snapshot=False,
    )
    quality.refresh_from_db()
    registry, calculator = decision_registry()

    result = run_decision(quality=quality, release=fixture["release"], registry=registry)

    assert result.status == "blocked"
    assert result.reason_code == "strategy_signal_quality_not_allowed"
    assert calculator.calls == 0
    assert DecisionSnapshot.objects.count() == 0
    assert AlertEvent.objects.filter(source_module="DecisionSnapshot", event_type="decision_snapshot_blocked").exists()


@pytest.mark.django_db
def test_decision_snapshot_blocks_when_policy_is_disabled() -> None:
    fixture, _rule_set, _signal, quality, _policy = build_decision_fixture(policy_enabled=False)
    registry, calculator = decision_registry()

    result = run_decision(quality=quality, release=fixture["release"], registry=registry)

    assert result.status == "blocked"
    assert result.reason_code == "decision_policy_unavailable"
    assert calculator.calls == 0
    assert DecisionSnapshot.objects.count() == 0


@pytest.mark.django_db
def test_decision_snapshot_rejects_invalid_target_ratio_as_failed_snapshot() -> None:
    fixture, _rule_set, _signal, quality, _policy = build_decision_fixture()
    registry, _calculator = decision_registry(FakeDecisionPolicyCalculator(target_position_ratio="1.5"))

    result = run_decision(quality=quality, release=fixture["release"], registry=registry)

    snapshot = DecisionSnapshot.objects.get()
    assert result.status == "failed"
    assert snapshot.status == AnalysisObjectStatus.FAILED
    assert snapshot.is_usable is False
    assert snapshot.allows_order_plan is False
    assert snapshot.error_code == "decision_policy_output_invalid"
    assert AlertEvent.objects.filter(source_module="DecisionSnapshot", event_type="decision_snapshot_failed").count() == 1


@pytest.mark.django_db
def test_decision_snapshot_calculator_failed_output_is_failed_snapshot() -> None:
    fixture, _rule_set, _signal, quality, _policy = build_decision_fixture()
    registry, _calculator = decision_registry(FakeDecisionPolicyCalculator(failed=True))

    result = run_decision(quality=quality, release=fixture["release"], registry=registry)

    snapshot = DecisionSnapshot.objects.get()
    assert result.status == "failed"
    assert snapshot.status == AnalysisObjectStatus.FAILED
    assert snapshot.error_code == "test_decision_policy_failed"
    assert snapshot.allows_order_plan is False
    assert AlertEvent.objects.filter(source_module="DecisionSnapshot", event_type="decision_snapshot_failed").count() == 1


@pytest.mark.django_db
def test_decision_snapshot_unexpected_calculator_error_is_persisted_as_failed() -> None:
    fixture, _rule_set, _signal, quality, _policy = build_decision_fixture()
    registry, _calculator = decision_registry(FakeDecisionPolicyCalculator(unexpected_error=True))

    result = run_decision(quality=quality, release=fixture["release"], registry=registry)

    snapshot = DecisionSnapshot.objects.get()
    assert result.status == "failed"
    assert snapshot.status == AnalysisObjectStatus.FAILED
    assert snapshot.error_code == "decision_policy_calculator_unexpected_error"
    assert snapshot.allows_order_plan is False
    assert AlertEvent.objects.filter(source_module="DecisionSnapshot", event_type="decision_snapshot_failed").count() == 1


@pytest.mark.django_db
def test_decision_snapshot_rejects_no_trade_with_ratio() -> None:
    fixture, _rule_set, _signal, quality, _policy = build_decision_fixture()
    registry, _calculator = decision_registry(
        FakeDecisionPolicyCalculator(target_intent=DecisionTargetIntent.NO_TRADE, target_position_ratio="0.1")
    )

    result = run_decision(quality=quality, release=fixture["release"], registry=registry)

    snapshot = DecisionSnapshot.objects.get()
    assert result.status == "failed"
    assert snapshot.error_code == "decision_policy_output_invalid"
    assert snapshot.allows_order_plan is False


@pytest.mark.django_db
def test_decision_snapshot_rejects_order_like_calculator_output() -> None:
    fixture, _rule_set, _signal, quality, _policy = build_decision_fixture()
    registry, _calculator = decision_registry(FakeDecisionPolicyCalculator(forbidden_output=True))

    result = run_decision(quality=quality, release=fixture["release"], registry=registry)

    snapshot = DecisionSnapshot.objects.get()
    assert result.status == "failed"
    assert snapshot.error_code == "decision_policy_output_invalid"
    assert snapshot.allows_order_plan is False


@pytest.mark.django_db
def test_decision_snapshot_dry_run_does_not_persist_or_alert() -> None:
    fixture, _rule_set, _signal, quality, _policy = build_decision_fixture()
    registry, calculator = decision_registry()

    result = run_decision(quality=quality, release=fixture["release"], registry=registry, dry_run=True)

    assert result.status == "succeeded"
    assert result.data["persisted"] is False
    assert result.data["allows_order_plan"] is False
    assert calculator.calls == 1
    assert DecisionSnapshot.objects.count() == 0
    assert AlertEvent.objects.filter(source_module="DecisionSnapshot").count() == 0


@pytest.mark.django_db
def test_decision_snapshot_is_idempotent_by_business_request_key() -> None:
    fixture, _rule_set, _signal, quality, _policy = build_decision_fixture()
    registry, calculator = decision_registry()

    first = run_decision(quality=quality, release=fixture["release"], registry=registry)
    second = run_decision(quality=quality, release=fixture["release"], registry=registry)

    assert first.status == "succeeded"
    assert second.status == "succeeded"
    assert first.data["decision_snapshot_id"] == second.data["decision_snapshot_id"]
    assert DecisionSnapshot.objects.count() == 1
    assert calculator.calls == 1


@pytest.mark.django_db
def test_decision_snapshot_blocks_business_request_key_conflict() -> None:
    fixture, _rule_set, _signal, quality, _policy = build_decision_fixture()
    registry, _calculator = decision_registry()
    first = run_decision(quality=quality, release=fixture["release"], registry=registry)

    conflict = build_decision_snapshot(
        strategy_signal_quality_result_id=quality.id + 999,
        strategy_analysis_release_id=fixture["release"].id,
        strategy_analysis_release_hash=fixture["release"].release_hash,
        business_request_key="decision-snapshot-request",
        trace_id="trace",
        trigger_source="test",
        registry=registry,
    )

    assert first.status == "succeeded"
    assert conflict.status == "blocked"
    assert conflict.reason_code == "decision_snapshot_idempotency_conflict"
    assert DecisionSnapshot.objects.count() == 1


@pytest.mark.django_db
def test_decision_snapshot_expired_target_position_does_not_allow_order_plan() -> None:
    fixture, _rule_set, _signal, quality, _policy = build_decision_fixture(policy_params={"expires_after_seconds": 0})
    registry, _calculator = decision_registry()

    result = run_decision(quality=quality, release=fixture["release"], registry=registry)

    snapshot = DecisionSnapshot.objects.get()
    assert result.status == "succeeded"
    assert snapshot.target_intent == DecisionTargetIntent.TARGET_POSITION
    assert snapshot.is_usable is False
    assert snapshot.allows_order_plan is False
    assert snapshot.blocked_reason == "decision_snapshot_expired"
