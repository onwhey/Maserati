from __future__ import annotations

from datetime import UTC, datetime

import pytest

from apps.alerts.models import AlertEvent
from apps.strategy_analysis.definition_hashes import (
    normalize_domain_codes,
    strategy_definition_dependency_hash,
    strategy_definition_hash,
    strategy_route_policy_hash,
    strategy_route_rule_hash,
    strategy_route_rule_set_hash,
)
from apps.strategy_analysis.models import (
    DefinitionLifecycleStatus,
    MarketRegimeSnapshot,
    ReleaseItemComponentType,
    StrategyAnalysisRelease,
    StrategyAnalysisReleaseActivation,
    StrategyAnalysisReleaseApproval,
    StrategyAnalysisReleaseItem,
    StrategyDefinition,
    StrategyRouteAction,
    StrategyRouteDecision,
    StrategyRouteFallbackPolicy,
    StrategyRouteOutcome,
    StrategyRoutePolicy,
    StrategyRouteRule,
)
from apps.strategy_analysis.services.market_regime import classify_for_strategy_routing
from apps.strategy_analysis.services.release import calculate_definition_set_hash, calculate_release_hash
from apps.strategy_analysis.services.strategy_routing import route_for_strategy_signal
from apps.strategy_calculator.contracts import CalculatorInput, CalculatorMetadata, CalculatorOutput, CalculatorType
from apps.strategy_calculator.registry import CalculatorRegistry
from apps.strategy_calculator.utils import stable_hash
from tests.strategy_analysis.test_market_regime import build_fixture as build_market_fixture
from tests.strategy_analysis.test_market_regime import registry as market_regime_registry


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
    )

    def calculate(self, calculation_input: CalculatorInput) -> CalculatorOutput:
        raise AssertionError("StrategyRouting 不得执行 StrategySignal calculator")


def strategy_registry() -> CalculatorRegistry:
    result = CalculatorRegistry()
    result.register(FakeStrategySignalCalculator())
    return result


def create_strategy(code: str, version: str = "1.0.0") -> StrategyDefinition:
    params_hash = stable_hash({})
    allowed = normalize_domain_codes(["trend"])
    required = normalize_domain_codes(["trend"])
    definition_hash = strategy_definition_hash(
        strategy_code=code,
        strategy_version=version,
        algorithm_name="test_strategy_signal",
        algorithm_version="1.0.0",
        input_schema_version="1.0",
        output_schema_version="1.0",
        params_hash=params_hash,
        allowed_domain_codes=allowed,
        required_domain_codes=required,
        uses_input_weights=False,
        domain_input_weights={},
        prediction_horizon="4h",
    )
    return StrategyDefinition.objects.create(
        strategy_code=code,
        strategy_version=version,
        algorithm_name="test_strategy_signal",
        algorithm_version="1.0.0",
        input_schema_version="1.0",
        output_schema_version="1.0",
        params={},
        params_hash=params_hash,
        definition_hash=definition_hash,
        allowed_domain_codes=list(allowed),
        required_domain_codes=list(required),
        uses_input_weights=False,
        domain_input_weights={},
        prediction_horizon="4h",
        status=DefinitionLifecycleStatus.ACTIVE,
        enabled=True,
    )


def add_strategy_item(release: StrategyAnalysisRelease, definition: StrategyDefinition, sort_order: int) -> None:
    payload = {
        "allowed_domain_codes": definition.allowed_domain_codes,
        "required_domain_codes": definition.required_domain_codes,
    }
    StrategyAnalysisReleaseItem.objects.create(
        release=release,
        component_type=ReleaseItemComponentType.STRATEGY_DEFINITION,
        component_object_id=definition.id,
        component_code=definition.strategy_code,
        definition_hash=definition.definition_hash,
        algorithm_name=definition.algorithm_name,
        algorithm_version=definition.algorithm_version,
        params_hash=definition.params_hash,
        dependency_hash=strategy_definition_dependency_hash(payload),
        payload_summary=payload,
        sort_order=sort_order,
    )


def utc(hour: int) -> datetime:
    return datetime(2026, 1, 1, hour, tzinfo=UTC)


def build_routing_fixture(
    *,
    rule_specs: list[dict] | None = None,
    fallback_policy: str = StrategyRouteFallbackPolicy.NONE,
    include_policy_item: bool = True,
):
    domain_set, release, regime_definition = build_market_fixture()
    assert regime_definition is not None
    primary = create_strategy("trend_following")
    fallback = create_strategy("fallback_trend")
    add_strategy_item(release, primary, 10)
    add_strategy_item(release, fallback, 20)
    fallback_definition = fallback if fallback_policy == StrategyRouteFallbackPolicy.EXPLICIT else None
    policy = StrategyRoutePolicy.objects.create(
        policy_code="test_route_policy",
        policy_version="1.0.0",
        condition_schema_version="1.0",
        rule_set_hash="pending",
        definition_hash="pending",
        fallback_policy=fallback_policy,
        fallback_strategy_definition=fallback_definition,
        status=DefinitionLifecycleStatus.ACTIVE,
        enabled=True,
    )
    specs = rule_specs or [
        {
            "code": "select_trend",
            "priority": 10,
            "action": StrategyRouteAction.SELECT_STRATEGY,
            "conditions": {"regime_codes": ["trend_up"]},
            "strategy": primary,
        }
    ]
    rules: list[StrategyRouteRule] = []
    rule_payloads: list[dict] = []
    for spec in specs:
        strategy = spec.get("strategy")
        if strategy == "primary":
            strategy = primary
        elif strategy == "fallback":
            strategy = fallback
        rule = StrategyRouteRule.objects.create(
            strategy_route_policy=policy,
            rule_code=spec["code"],
            priority=spec["priority"],
            action=spec["action"],
            match_conditions=spec.get("conditions", {}),
            selected_strategy_definition=strategy,
            status=DefinitionLifecycleStatus.ACTIVE,
            enabled=True,
            valid_from_utc=spec.get("valid_from"),
            valid_to_utc=spec.get("valid_to"),
            rule_hash="pending",
        )
        rule.rule_hash = strategy_route_rule_hash(
            policy_id=policy.id,
            rule_code=rule.rule_code,
            priority=rule.priority,
            action=rule.action,
            match_conditions=rule.match_conditions,
            selected_strategy_definition_id=rule.selected_strategy_definition_id,
            valid_from_utc=rule.valid_from_utc,
            valid_to_utc=rule.valid_to_utc,
            allowed_regime_codes=regime_definition.allowed_regime_codes,
        )
        rule.save(update_fields=["rule_hash", "updated_at_utc"])
        rules.append(rule)
        rule_payloads.append(
            {"rule_id": rule.id, "rule_code": rule.rule_code, "priority": rule.priority, "rule_hash": rule.rule_hash}
        )
        StrategyAnalysisReleaseItem.objects.create(
            release=release,
            component_type=ReleaseItemComponentType.STRATEGY_ROUTE_RULE,
            component_object_id=rule.id,
            component_code=rule.rule_code,
            definition_hash=rule.rule_hash,
            sort_order=rule.priority,
        )
    policy.rule_set_hash = strategy_route_rule_set_hash(rule_payloads)
    policy.definition_hash = strategy_route_policy_hash(
        policy_code=policy.policy_code,
        policy_version=policy.policy_version,
        condition_schema_version=policy.condition_schema_version,
        rule_set_hash=policy.rule_set_hash,
        fallback_policy=policy.fallback_policy,
        fallback_strategy_definition_id=policy.fallback_strategy_definition_id,
    )
    policy.save(update_fields=["rule_set_hash", "definition_hash", "updated_at_utc"])
    if include_policy_item:
        StrategyAnalysisReleaseItem.objects.create(
            release=release,
            component_type=ReleaseItemComponentType.STRATEGY_ROUTE_POLICY,
            component_object_id=policy.id,
            component_code=policy.policy_code,
            definition_hash=policy.definition_hash,
            dependency_hash=policy.rule_set_hash,
        )
    release.release_hash = calculate_release_hash(release)
    release.save(update_fields=["release_hash", "updated_at_utc"])
    StrategyAnalysisReleaseApproval.objects.filter(release=release).update(release_hash=release.release_hash)
    StrategyAnalysisReleaseActivation.objects.filter(release=release).update(release_hash=release.release_hash)
    domain_set.release_hash = release.release_hash
    domain_set.save(update_fields=["release_hash", "updated_at_utc"])
    market_result = classify_for_strategy_routing(
        domain_signal_set_id=domain_set.id,
        strategy_analysis_release_id=release.id,
        strategy_analysis_release_hash=release.release_hash,
        expected_market_regime_definition_hash=regime_definition.definition_hash,
        business_request_key="routing-market-regime",
        trace_id="trace",
        trigger_source="test",
        registry=market_regime_registry(),
    )
    assert market_result.status == "succeeded"
    snapshot_id = market_result.data["market_regime_snapshot_id"]
    strategy_items = release.items.filter(component_type=ReleaseItemComponentType.STRATEGY_DEFINITION)
    return {
        "snapshot_id": snapshot_id,
        "release": release,
        "policy": policy,
        "rules": rules,
        "primary": primary,
        "fallback": fallback,
        "strategy_set_hash": calculate_definition_set_hash(strategy_items),
    }


def run_route(fixture: dict, *, key: str = "route-request", dry_run: bool = False):
    return route_for_strategy_signal(
        market_regime_snapshot_id=fixture["snapshot_id"],
        strategy_analysis_release_id=fixture["release"].id,
        strategy_analysis_release_hash=fixture["release"].release_hash,
        expected_strategy_route_policy_hash=fixture["policy"].definition_hash,
        expected_strategy_definition_set_hash=fixture["strategy_set_hash"],
        business_request_key=key,
        trace_id="trace",
        trigger_source="test",
        dry_run=dry_run,
        registry=strategy_registry(),
    )


@pytest.mark.django_db
def test_strategy_routing_selects_registered_strategy() -> None:
    fixture = build_routing_fixture()

    result = run_route(fixture)

    assert result.status == "succeeded"
    decision = StrategyRouteDecision.objects.get()
    assert decision.route_outcome == StrategyRouteOutcome.SELECTED
    assert decision.selected_strategy_definition_id == fixture["primary"].id
    assert decision.allows_strategy_signal is True
    assert decision.matched_strategy_route_rule_id == fixture["rules"][0].id
    assert decision.matched_conditions["rule_status"] == DefinitionLifecycleStatus.ACTIVE
    assert decision.matched_conditions["rule_enabled"] is True
    assert decision.matched_conditions["rule_hash"] == fixture["rules"][0].rule_hash
    assert AlertEvent.objects.filter(source_module="StrategyRouting").count() == 0


@pytest.mark.django_db
def test_strategy_routing_explicit_no_strategy_is_normal_result() -> None:
    fixture = build_routing_fixture(
        rule_specs=[
            {
                "code": "no_strategy_for_mixed",
                "priority": 1,
                "action": StrategyRouteAction.NO_STRATEGY,
                "conditions": {},
                "strategy": None,
            }
        ]
    )

    result = run_route(fixture)

    decision = StrategyRouteDecision.objects.get()
    assert result.status == "succeeded"
    assert decision.route_outcome == StrategyRouteOutcome.NO_STRATEGY
    assert decision.selected_strategy_definition_id is None
    assert decision.is_usable is True
    assert decision.allows_strategy_signal is False
    assert AlertEvent.objects.filter(source_module="StrategyRouting").count() == 0


@pytest.mark.django_db
def test_strategy_routing_uses_smallest_matching_priority() -> None:
    fixture = build_routing_fixture(
        rule_specs=[
            {"code": "low", "priority": 20, "action": StrategyRouteAction.NO_STRATEGY, "conditions": {}, "strategy": None},
            {"code": "high", "priority": 5, "action": StrategyRouteAction.SELECT_STRATEGY, "conditions": {}, "strategy": "primary"},
        ]
    )

    result = run_route(fixture)

    assert result.status == "succeeded"
    decision = StrategyRouteDecision.objects.get()
    assert decision.matched_strategy_route_rule.rule_code == "high"
    assert decision.selected_strategy_definition_id == fixture["primary"].id


@pytest.mark.django_db
def test_strategy_routing_minimum_conditions_are_inclusive_and_combined_with_and() -> None:
    fixture = build_routing_fixture(
        rule_specs=[
            {
                "code": "all_thresholds",
                "priority": 1,
                "action": StrategyRouteAction.SELECT_STRATEGY,
                "conditions": {
                    "regime_codes": ["trend_up"],
                    "minimum_regime_confidence": "0.8",
                    "minimum_classification_margin": "0.6",
                    "regime_score_thresholds": {"trend_up": "0.8", "mixed": "0.2"},
                },
                "strategy": "primary",
            }
        ]
    )

    result = run_route(fixture)

    assert result.status == "succeeded"
    assert StrategyRouteDecision.objects.get().selected_strategy_definition_id == fixture["primary"].id


@pytest.mark.django_db
def test_strategy_routing_same_priority_conflict_is_blocked() -> None:
    fixture = build_routing_fixture(
        rule_specs=[
            {"code": "one", "priority": 1, "action": StrategyRouteAction.NO_STRATEGY, "conditions": {}, "strategy": None},
            {"code": "two", "priority": 1, "action": StrategyRouteAction.NO_STRATEGY, "conditions": {}, "strategy": None},
        ]
    )

    result = run_route(fixture)

    assert result.status == "blocked"
    assert result.reason_code == "strategy_route_rule_conflict"
    assert StrategyRouteDecision.objects.count() == 0


@pytest.mark.django_db
def test_strategy_routing_no_match_is_blocked_not_no_strategy() -> None:
    fixture = build_routing_fixture(
        rule_specs=[
            {"code": "mixed_only", "priority": 1, "action": StrategyRouteAction.NO_STRATEGY, "conditions": {"regime_codes": ["mixed"]}, "strategy": None}
        ]
    )

    result = run_route(fixture)

    assert result.status == "blocked"
    assert result.reason_code == "strategy_route_no_match"
    assert result.data["persisted"] is False
    assert result.data["strategy_route_decision_id"] is None
    assert result.data["allows_strategy_signal"] is False
    assert result.data["error_code"] == "strategy_route_no_match"
    assert StrategyRouteDecision.objects.count() == 0


@pytest.mark.django_db
def test_strategy_routing_uses_explicit_fallback_only_for_unavailable_target() -> None:
    fixture = build_routing_fixture(fallback_policy=StrategyRouteFallbackPolicy.EXPLICIT)
    fixture["primary"].enabled = False
    fixture["primary"].save(update_fields=["enabled", "updated_at_utc"])

    result = run_route(fixture)

    decision = StrategyRouteDecision.objects.get()
    assert result.status == "succeeded"
    assert decision.selected_strategy_definition_id == fixture["fallback"].id
    assert decision.fallback_used is True
    assert decision.fallback_reason


@pytest.mark.django_db
def test_strategy_routing_unavailable_target_without_fallback_is_blocked() -> None:
    fixture = build_routing_fixture()
    fixture["primary"].enabled = False
    fixture["primary"].save(update_fields=["enabled", "updated_at_utc"])

    result = run_route(fixture)

    assert result.status == "blocked"
    assert result.reason_code == "strategy_definition_not_selectable"
    assert StrategyRouteDecision.objects.count() == 0


@pytest.mark.django_db
def test_strategy_routing_dry_run_does_not_write_or_reuse_formal_decision() -> None:
    fixture = build_routing_fixture()
    formal = run_route(fixture)

    dry_run = run_route(fixture, dry_run=True)

    assert formal.status == "succeeded"
    assert dry_run.status == "succeeded"
    assert dry_run.data["persisted"] is False
    assert dry_run.data["allows_strategy_signal"] is False
    assert StrategyRouteDecision.objects.count() == 1


@pytest.mark.django_db
def test_strategy_routing_is_idempotent() -> None:
    fixture = build_routing_fixture()

    first = run_route(fixture)
    second = run_route(fixture)

    assert first.status == "succeeded"
    assert second.status == "succeeded"
    assert StrategyRouteDecision.objects.count() == 1


@pytest.mark.django_db
def test_strategy_routing_blocks_when_release_has_no_policy() -> None:
    fixture = build_routing_fixture(include_policy_item=False)

    result = run_route(fixture)

    assert result.status == "blocked"
    assert result.reason_code == "strategy_route_policy_unavailable"


@pytest.mark.django_db
def test_strategy_routing_missing_required_score_creates_failed_decision() -> None:
    fixture = build_routing_fixture(
        rule_specs=[
            {
                "code": "needs_mixed_score",
                "priority": 1,
                "action": StrategyRouteAction.SELECT_STRATEGY,
                "conditions": {"regime_score_thresholds": {"mixed": "0.1"}},
                "strategy": "primary",
            }
        ]
    )
    snapshot = MarketRegimeSnapshot.objects.get(id=fixture["snapshot_id"])
    snapshot.regime_scores = {"trend_up": "0.8"}
    snapshot.save(update_fields=["regime_scores"])

    result = run_route(fixture)

    assert result.status == "failed"
    decision = StrategyRouteDecision.objects.get()
    assert decision.error_code == "strategy_route_output_invalid"
    assert decision.allows_strategy_signal is False
    assert result.data["error_code"] == "strategy_route_output_invalid"
    assert result.data["error_message"]
    assert result.data["persisted"] is True


@pytest.mark.django_db
def test_strategy_routing_rule_window_uses_snapshot_business_time() -> None:
    fixture = build_routing_fixture(
        rule_specs=[
            {
                "code": "expired",
                "priority": 1,
                "action": StrategyRouteAction.NO_STRATEGY,
                "conditions": {},
                "strategy": None,
                "valid_from": utc(0),
                "valid_to": utc(4),
            }
        ]
    )

    result = run_route(fixture)

    assert result.status == "blocked"
    assert result.reason_code == "strategy_route_no_match"


@pytest.mark.django_db
def test_strategy_routing_unknown_condition_field_is_blocked() -> None:
    fixture = build_routing_fixture()
    rule = fixture["rules"][0]
    rule.match_conditions = {"unknown_market_field": "x"}
    rule.save(update_fields=["match_conditions", "updated_at_utc"])

    result = run_route(fixture)

    assert result.status == "blocked"
    assert result.reason_code == "strategy_route_configuration_invalid"
    assert StrategyRouteDecision.objects.count() == 0


@pytest.mark.django_db
def test_strategy_routing_non_string_condition_field_is_blocked_not_crashed() -> None:
    fixture = build_routing_fixture()
    rule = fixture["rules"][0]
    rule.match_conditions = {1: "x"}
    rule.save(update_fields=["match_conditions", "updated_at_utc"])

    result = run_route(fixture)

    assert result.status == "blocked"
    assert result.reason_code == "strategy_route_configuration_invalid"
    assert result.data["persisted"] is False


@pytest.mark.django_db
def test_strategy_routing_disabled_frozen_rule_blocks_entire_route() -> None:
    fixture = build_routing_fixture()
    rule = fixture["rules"][0]
    rule.enabled = False
    rule.save(update_fields=["enabled", "updated_at_utc"])

    result = run_route(fixture)

    assert result.status == "blocked"
    assert result.reason_code == "strategy_route_rule_not_selectable"


@pytest.mark.django_db
def test_strategy_routing_fallback_does_not_handle_no_match() -> None:
    fixture = build_routing_fixture(
        fallback_policy=StrategyRouteFallbackPolicy.EXPLICIT,
        rule_specs=[
            {
                "code": "mixed_only",
                "priority": 1,
                "action": StrategyRouteAction.SELECT_STRATEGY,
                "conditions": {"regime_codes": ["mixed"]},
                "strategy": "primary",
            }
        ],
    )

    result = run_route(fixture)

    assert result.status == "blocked"
    assert result.reason_code == "strategy_route_no_match"
    assert StrategyRouteDecision.objects.count() == 0


@pytest.mark.django_db
def test_strategy_routing_business_request_key_conflict_is_blocked() -> None:
    fixture = build_routing_fixture()
    first = run_route(fixture)

    conflict = route_for_strategy_signal(
        market_regime_snapshot_id=fixture["snapshot_id"] + 999,
        strategy_analysis_release_id=fixture["release"].id,
        strategy_analysis_release_hash=fixture["release"].release_hash,
        expected_strategy_route_policy_hash=fixture["policy"].definition_hash,
        expected_strategy_definition_set_hash=fixture["strategy_set_hash"],
        business_request_key="route-request",
        trace_id="trace",
        trigger_source="test",
        registry=strategy_registry(),
    )

    assert first.status == "succeeded"
    assert conflict.status == "blocked"
    assert conflict.reason_code == "strategy_routing_idempotency_conflict"
    assert StrategyRouteDecision.objects.count() == 1


@pytest.mark.django_db
def test_strategy_routing_blocked_dry_run_explicitly_reports_not_persisted() -> None:
    fixture = build_routing_fixture(
        rule_specs=[
            {
                "code": "mixed_only",
                "priority": 1,
                "action": StrategyRouteAction.NO_STRATEGY,
                "conditions": {"regime_codes": ["mixed"]},
                "strategy": None,
            }
        ]
    )

    result = run_route(fixture, key="route-dry-run-no-match", dry_run=True)

    assert result.status == "blocked"
    assert result.data["persisted"] is False
    assert result.data["allows_strategy_signal"] is False
    assert StrategyRouteDecision.objects.count() == 0
    assert AlertEvent.objects.filter(source_module="StrategyRouting").count() == 0


def test_strategy_routing_hash_contract_rejects_blank_identity_fields() -> None:
    with pytest.raises(ValueError):
        strategy_definition_hash(
            strategy_code="",
            strategy_version="1.0.0",
            algorithm_name="test_strategy_signal",
            algorithm_version="1.0.0",
            input_schema_version="1.0",
            output_schema_version="1.0",
            params_hash=stable_hash({}),
            allowed_domain_codes=["trend"],
            required_domain_codes=["trend"],
            uses_input_weights=False,
            domain_input_weights={},
            prediction_horizon="4h",
        )
    with pytest.raises(ValueError):
        strategy_route_rule_hash(
            policy_id=1,
            rule_code="",
            priority=0,
            action=StrategyRouteAction.NO_STRATEGY,
            match_conditions={},
            selected_strategy_definition_id=None,
            valid_from_utc=None,
            valid_to_utc=None,
            allowed_regime_codes=["trend_up"],
        )
    with pytest.raises(ValueError):
        strategy_route_policy_hash(
            policy_code="",
            policy_version="1.0.0",
            condition_schema_version="1.0",
            rule_set_hash=stable_hash({"rules": []}),
            fallback_policy=StrategyRouteFallbackPolicy.NONE,
            fallback_strategy_definition_id=None,
        )
