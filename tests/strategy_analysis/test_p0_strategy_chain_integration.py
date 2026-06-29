from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from io import StringIO

import pytest
from django.core.management import call_command
from django.utils import timezone

from apps.order_plan.models import CandidateIntentRole, CandidateOrderIntent, OrderPlan, OrderPlanStatus
from apps.runtime_config.models import RuntimeTradingConfig
from apps.strategy_analysis.definition_hashes import (
    atomic_signal_dependency_hash,
    domain_atomic_membership_hash,
    market_regime_domain_membership_hash,
    strategy_definition_dependency_hash,
)
from apps.strategy_analysis.models import (
    AnalysisObjectStatus,
    AtomicSignalDefinition,
    AtomicSignalSet,
    DecisionPolicyDefinition,
    DecisionSnapshot,
    DomainSignalDefinition,
    DomainSignalSet,
    FeatureDefinition,
    FeatureSet,
    FeatureValue,
    MarketRegimeDefinition,
    MarketRegimeSnapshot,
    ReleaseAction,
    ReleaseApprovalStatus,
    ReleaseItemComponentType,
    StrategyAnalysisRelease,
    StrategyAnalysisReleaseActivation,
    StrategyAnalysisReleaseApproval,
    StrategyAnalysisReleaseItem,
    StrategyDefinition,
    StrategyRouteDecision,
    StrategyRoutePolicy,
    StrategyRouteRule,
    StrategySignal,
    StrategySignalQualityResult,
    StrategySignalQualityRuleSet,
    StrategySignalQualityStatus,
    StrategySignalQualityValidationMode,
)
from apps.strategy_analysis.services.atomic_signal import build_atomic_signals
from apps.strategy_analysis.services.decision_snapshot import build_decision_snapshot
from apps.strategy_analysis.services.domain_signal import build_domain_signals
from apps.strategy_analysis.services.market_regime import classify_for_strategy_routing
from apps.strategy_analysis.services.release import calculate_definition_set_hash, calculate_release_hash
from apps.strategy_analysis.services.strategy_routing import route_for_strategy_signal
from apps.strategy_analysis.services.strategy_signal import generate_strategy_signal
from apps.strategy_analysis.services.strategy_signal_quality import validate_strategy_signal
from apps.strategy_analysis.definition_hashes import strategy_signal_quality_rule_set_hash
from apps.strategy_calculator.utils import stable_hash
from tests.strategy_analysis.test_release_and_feature_layer import create_market_snapshot
from tests.test_order_plan_stage4 import _account_facts, _enable_runtime_permission, _price, _run


pytestmark = pytest.mark.django_db


def _seed_default_definitions() -> None:
    for command_name in (
        "seed_feature_definitions",
        "seed_atomic_signal_definitions",
        "seed_domain_signal_definitions",
        "seed_market_regime_definitions",
        "seed_strategy_definitions",
        "seed_strategy_routing",
        "seed_decision_policy_definitions",
    ):
        call_command(command_name, stdout=StringIO())


def _create_quality_rule_set() -> StrategySignalQualityRuleSet:
    params: dict[str, object] = {}
    params_hash = stable_hash(params)
    rule_set_hash = strategy_signal_quality_rule_set_hash(
        rule_set_code="default_strategy_signal_quality",
        rule_set_version="1.0.0",
        quality_schema_version="1.0",
        max_staleness_seconds=0,
        warning_blocks_decision=False,
        fail_alert_enabled=True,
        warning_alert_enabled=False,
        consecutive_failure_threshold=0,
        params_hash=params_hash,
    )
    return StrategySignalQualityRuleSet.objects.create(
        rule_set_code="default_strategy_signal_quality",
        rule_set_version="1.0.0",
        display_name="默认策略信号质量规则",
        quality_schema_version="1.0",
        max_staleness_seconds=0,
        warning_blocks_decision=False,
        fail_alert_enabled=True,
        warning_alert_enabled=False,
        consecutive_failure_threshold=0,
        params=params,
        params_hash=params_hash,
        rule_set_hash=rule_set_hash,
        status="active",
        enabled=True,
    )


def _add_release_item(
    release: StrategyAnalysisRelease,
    *,
    component_type: str,
    component_object_id: int,
    component_code: str,
    definition_hash: str,
    algorithm_name: str = "",
    algorithm_version: str = "",
    params_hash: str = "",
    dependency_hash: str = "",
    payload_summary: dict | None = None,
    sort_order: int = 0,
) -> None:
    StrategyAnalysisReleaseItem.objects.create(
        release=release,
        component_type=component_type,
        component_object_id=component_object_id,
        component_code=component_code,
        definition_hash=definition_hash,
        algorithm_name=algorithm_name,
        algorithm_version=algorithm_version,
        params_hash=params_hash,
        dependency_hash=dependency_hash,
        payload_summary=payload_summary or {},
        sort_order=sort_order,
    )


def _create_default_release() -> StrategyAnalysisRelease:
    quality_rule_set = _create_quality_rule_set()
    release = StrategyAnalysisRelease.objects.create(release_code="p0-default-chain-release", created_by="test")

    sort_order = 0
    for definition in FeatureDefinition.objects.order_by("feature_code", "definition_version"):
        sort_order += 10
        _add_release_item(
            release,
            component_type=ReleaseItemComponentType.FEATURE_DEFINITION,
            component_object_id=definition.id,
            component_code=definition.feature_code,
            definition_hash=definition.definition_hash,
            algorithm_name=definition.algorithm_name,
            algorithm_version=definition.algorithm_version,
            params_hash=definition.params_hash,
            sort_order=sort_order,
        )

    for definition in AtomicSignalDefinition.objects.order_by("signal_code"):
        sort_order += 10
        dependencies = definition.depends_on_feature_codes
        _add_release_item(
            release,
            component_type=ReleaseItemComponentType.ATOMIC_SIGNAL_DEFINITION,
            component_object_id=definition.id,
            component_code=definition.signal_code,
            definition_hash=definition.definition_hash,
            algorithm_name=definition.algorithm_name,
            algorithm_version=definition.algorithm_version,
            params_hash=definition.params_hash,
            dependency_hash=atomic_signal_dependency_hash(dependencies),
            payload_summary={"depends_on_feature_codes": dependencies},
            sort_order=sort_order,
        )

    for definition in DomainSignalDefinition.objects.order_by("domain_code"):
        sort_order += 10
        payload = {
            "allowed_atomic_signal_codes": definition.allowed_atomic_signal_codes,
            "required_atomic_signal_codes": definition.required_atomic_signal_codes,
        }
        _add_release_item(
            release,
            component_type=ReleaseItemComponentType.DOMAIN_SIGNAL_DEFINITION,
            component_object_id=definition.id,
            component_code=definition.domain_code,
            definition_hash=definition.definition_hash,
            algorithm_name=definition.algorithm_name,
            algorithm_version=definition.algorithm_version,
            params_hash=definition.params_hash,
            dependency_hash=domain_atomic_membership_hash(payload),
            payload_summary=payload,
            sort_order=sort_order,
        )

    regime_definition = MarketRegimeDefinition.objects.get(definition_code="context_structure_regime_v1")
    payload = {
        "allowed_domain_codes": regime_definition.allowed_domain_codes,
        "required_domain_codes": regime_definition.required_domain_codes,
        "allowed_regime_codes": regime_definition.allowed_regime_codes,
    }
    _add_release_item(
        release,
        component_type=ReleaseItemComponentType.MARKET_REGIME_DEFINITION,
        component_object_id=regime_definition.id,
        component_code=regime_definition.definition_code,
        definition_hash=regime_definition.definition_hash,
        algorithm_name=regime_definition.algorithm_name,
        algorithm_version=regime_definition.algorithm_version,
        params_hash=regime_definition.params_hash,
        dependency_hash=market_regime_domain_membership_hash(payload),
        payload_summary=payload,
        sort_order=10_000,
    )

    policy = StrategyRoutePolicy.objects.get(policy_code="context_structure_strategy_routing", policy_version="v1")
    _add_release_item(
        release,
        component_type=ReleaseItemComponentType.STRATEGY_ROUTE_POLICY,
        component_object_id=policy.id,
        component_code=policy.policy_code,
        definition_hash=policy.definition_hash,
        dependency_hash=policy.rule_set_hash,
        sort_order=11_000,
    )
    for rule in StrategyRouteRule.objects.filter(strategy_route_policy=policy).order_by("priority", "rule_code"):
        _add_release_item(
            release,
            component_type=ReleaseItemComponentType.STRATEGY_ROUTE_RULE,
            component_object_id=rule.id,
            component_code=rule.rule_code,
            definition_hash=rule.rule_hash,
            sort_order=12_000 + rule.priority,
        )

    for definition in StrategyDefinition.objects.order_by("strategy_code", "strategy_version"):
        payload = {
            "allowed_domain_codes": definition.allowed_domain_codes,
            "required_domain_codes": definition.required_domain_codes,
        }
        _add_release_item(
            release,
            component_type=ReleaseItemComponentType.STRATEGY_DEFINITION,
            component_object_id=definition.id,
            component_code=definition.strategy_code,
            definition_hash=definition.definition_hash,
            algorithm_name=definition.algorithm_name,
            algorithm_version=definition.algorithm_version,
            params_hash=definition.params_hash,
            dependency_hash=strategy_definition_dependency_hash(payload),
            payload_summary=payload,
            sort_order=13_000,
        )

    _add_release_item(
        release,
        component_type=ReleaseItemComponentType.STRATEGY_SIGNAL_QUALITY_RULE_SET,
        component_object_id=quality_rule_set.id,
        component_code=quality_rule_set.rule_set_code,
        definition_hash=quality_rule_set.rule_set_hash,
        params_hash=quality_rule_set.params_hash,
        payload_summary={
            "quality_schema_version": quality_rule_set.quality_schema_version,
            "max_staleness_seconds": quality_rule_set.max_staleness_seconds,
            "warning_blocks_decision": quality_rule_set.warning_blocks_decision,
        },
        sort_order=14_000,
    )

    decision_policy = DecisionPolicyDefinition.objects.get(policy_code="position_policy", policy_version="v1")
    _add_release_item(
        release,
        component_type=ReleaseItemComponentType.DECISION_POLICY_DEFINITION,
        component_object_id=decision_policy.id,
        component_code=decision_policy.policy_code,
        definition_hash=decision_policy.definition_hash,
        algorithm_name=decision_policy.algorithm_name,
        algorithm_version=decision_policy.algorithm_version,
        params_hash=decision_policy.params_hash,
        sort_order=15_000,
    )

    release.release_hash = calculate_release_hash(release)
    release.approval_status = ReleaseApprovalStatus.APPROVED
    release.is_active = True
    release.active_slot = 1
    release.approved_at_utc = timezone.now()
    release.activated_at_utc = timezone.now()
    release.save(
        update_fields=[
            "release_hash",
            "approval_status",
            "is_active",
            "active_slot",
            "approved_at_utc",
            "activated_at_utc",
            "updated_at_utc",
        ]
    )
    StrategyAnalysisReleaseApproval.objects.create(
        release=release,
        release_hash=release.release_hash,
        action=ReleaseAction.APPROVE,
        validation_evidence_refs=["p0-default-chain-integration-test"],
        reason="P0 default chain integration test",
        operator_id="tester",
        trace_id="trace-p0-chain",
        trigger_source="test",
    )
    StrategyAnalysisReleaseActivation.objects.create(
        release=release,
        release_hash=release.release_hash,
        action=ReleaseAction.ACTIVATE,
        operator_id="tester",
        reason="P0 default chain integration test",
        trace_id="trace-p0-chain",
        trigger_source="test",
    )
    return release


def _feature_overrides() -> dict[str, Decimal]:
    return {
        "close_vs_sma_pct_1d_200": Decimal("0.03"),
        "close_vs_sma_pct_1d_365": Decimal("0.03"),
        "slope_sma_1d_200": Decimal("0.004"),
        "slope_sma_1d_365": Decimal("0.004"),
        "return_pct_1d_365": Decimal("0.20"),
        "range_position_pct_1d_365": Decimal("0.50"),
        "sma_spread_pct_1d_20_60": Decimal("0.006"),
        "sma_spread_pct_1d_60_120": Decimal("0.006"),
        "slope_sma_1d_120_lag10": Decimal("0.004"),
        "close_vs_sma_pct_1d_60": Decimal("0.01"),
        "higher_high_count_1d_60_block20": Decimal("2"),
        "higher_low_count_1d_60_block20": Decimal("2"),
        "sma_spread_pct_4h_20_60": Decimal("-0.006"),
        "sma_spread_pct_4h_60_120": Decimal("-0.006"),
        "slope_sma_4h_60_lag12": Decimal("-0.004"),
        "close_vs_sma_pct_4h_60": Decimal("-0.01"),
        "lower_high_count_4h_60_block20": Decimal("2"),
        "lower_low_count_4h_60_block20": Decimal("2"),
        "return_pct_1d_7": Decimal("-0.04"),
        "return_delta_pct_1d_7": Decimal("0.02"),
        "close_location_avg_pct_1d_3": Decimal("0.30"),
        "return_pct_4h_24": Decimal("-0.02"),
        "return_delta_pct_4h_24": Decimal("0.01"),
        "close_location_avg_pct_4h_12": Decimal("0.35"),
        "atr_percentile_1d_120": Decimal("0.50"),
        "atr_percentile_4h_120": Decimal("0.50"),
        "realized_vol_percentile_4h_120": Decimal("0.50"),
        "volatility_ratio_4h_20_to_60": Decimal("1.00"),
        "structure_major_support_lower_1d_365": Decimal("49000"),
        "structure_major_support_upper_1d_365": Decimal("50000"),
        "structure_major_resistance_lower_1d_365": Decimal("59000"),
        "structure_major_resistance_upper_1d_365": Decimal("60000"),
        "structure_major_support_touch_count_1d_365": Decimal("2"),
        "structure_major_resistance_touch_count_1d_365": Decimal("2"),
        "structure_major_support_score_1d_365": Decimal("1"),
        "structure_major_resistance_score_1d_365": Decimal("1"),
        "structure_major_range_width_pct_1d_365": Decimal("0.18"),
        "structure_major_range_position_pct_1d_365": Decimal("0.20"),
        "structure_major_distance_to_support_upper_pct_1d_365": Decimal("0.005"),
        "structure_major_distance_to_resistance_lower_pct_1d_365": Decimal("0.18"),
        "structure_major_breakout_above_resistance_pct_1d_365": Decimal("0"),
        "structure_major_breakdown_below_support_pct_1d_365": Decimal("0"),
        "structure_minor_support_lower_4h_120": Decimal("49500"),
        "structure_minor_support_upper_4h_120": Decimal("50000"),
        "structure_minor_resistance_lower_4h_120": Decimal("55000"),
        "structure_minor_resistance_upper_4h_120": Decimal("55500"),
        "structure_minor_support_touch_count_4h_120": Decimal("2"),
        "structure_minor_resistance_touch_count_4h_120": Decimal("2"),
        "structure_minor_support_score_4h_120": Decimal("1"),
        "structure_minor_resistance_score_4h_120": Decimal("1"),
        "structure_minor_range_width_pct_4h_120": Decimal("0.10"),
        "structure_minor_range_position_pct_4h_120": Decimal("0.20"),
        "structure_minor_distance_to_support_upper_pct_4h_120": Decimal("0.003"),
        "structure_minor_distance_to_resistance_lower_pct_4h_120": Decimal("0.10"),
        "structure_minor_breakout_above_resistance_pct_4h_120": Decimal("0"),
        "structure_minor_breakdown_below_support_pct_4h_120": Decimal("0"),
        "risk_latest_body_return_pct_4h": Decimal("0"),
        "candle_body_ratio_4h_latest": Decimal("0.20"),
        "risk_latest_close_location_ratio_4h": Decimal("0.50"),
        "upper_shadow_ratio_4h_latest": Decimal("0.10"),
        "lower_shadow_ratio_4h_latest": Decimal("0.10"),
        "risk_consecutive_large_bear_body_count_4h_20": Decimal("0"),
        "risk_consecutive_large_bull_body_count_4h_20": Decimal("0"),
        "risk_cumulative_return_pct_4h_3": Decimal("0"),
        "risk_latest_from_intrabar_high_reversal_pct_4h": Decimal("0"),
        "risk_latest_from_intrabar_low_recovery_pct_4h": Decimal("0"),
    }


def _create_feature_set_with_values(release: StrategyAnalysisRelease) -> FeatureSet:
    snapshot = create_market_snapshot()
    now = timezone.now()
    snapshot.analysis_close_time_utc = now
    snapshot.analysis_reference_time_utc = now
    snapshot.latest_4h_open_time_utc = now - timedelta(hours=4)
    snapshot.latest_1d_open_time_utc = now - timedelta(days=1)
    snapshot.end_4h_open_time_utc = snapshot.latest_4h_open_time_utc
    snapshot.end_1d_open_time_utc = snapshot.latest_1d_open_time_utc
    snapshot.save(
        update_fields=[
            "analysis_close_time_utc",
            "analysis_reference_time_utc",
            "latest_4h_open_time_utc",
            "latest_1d_open_time_utc",
            "end_4h_open_time_utc",
            "end_1d_open_time_utc",
        ]
    )
    feature_items = tuple(
        release.items.filter(component_type=ReleaseItemComponentType.FEATURE_DEFINITION).order_by(
            "sort_order", "component_code", "id"
        )
    )
    feature_set = FeatureSet.objects.create(
        feature_set_key=stable_hash({"feature_set": "p0-default-chain", "release_hash": release.release_hash}),
        business_request_key="p0-default-chain-feature-set",
        market_snapshot=snapshot,
        strategy_analysis_release=release,
        release_hash=release.release_hash,
        status=AnalysisObjectStatus.CREATED,
        is_usable=True,
        allows_atomic_signal=True,
        feature_schema_version="1.0",
        definition_set_hash=calculate_definition_set_hash(feature_items),
        feature_count=len(feature_items),
        trace_id="trace-p0-chain",
        trigger_source="test",
    )
    overrides = _feature_overrides()
    definitions = FeatureDefinition.objects.order_by("feature_code", "definition_version")
    FeatureValue.objects.bulk_create(
        [
            FeatureValue(
                feature_set=feature_set,
                feature_definition=definition,
                feature_code=definition.feature_code,
                feature_definition_hash=definition.definition_hash,
                algorithm_name=definition.algorithm_name,
                algorithm_version=definition.algorithm_version,
                params_hash=definition.params_hash,
                value_type=definition.value_type,
                numeric_value=overrides.get(definition.feature_code, Decimal("0")),
                output_schema_version=definition.output_schema_version,
                evidence={"source": "p0_default_chain_test"},
                status=AnalysisObjectStatus.CREATED,
                is_valid=True,
            )
            for definition in definitions
        ]
    )
    return feature_set


def _definition_set_hash(release: StrategyAnalysisRelease, component_type: str) -> str:
    return calculate_definition_set_hash(tuple(release.items.filter(component_type=component_type)))


def _assert_zone(zone: dict[str, object], *, lower: str, upper: str) -> None:
    assert Decimal(str(zone["lower"])) == Decimal(lower)
    assert Decimal(str(zone["upper"])) == Decimal(upper)


def test_p0_default_chain_reaches_limit_order_plan_from_feature_values(settings) -> None:
    _seed_default_definitions()
    release = _create_default_release()
    feature_set = _create_feature_set_with_values(release)

    atomic_result = build_atomic_signals(
        feature_set_id=feature_set.id,
        strategy_analysis_release_id=release.id,
        release_hash=release.release_hash,
        expected_definition_set_hash=_definition_set_hash(release, ReleaseItemComponentType.ATOMIC_SIGNAL_DEFINITION),
        business_request_key="p0-default-chain-atomic",
        trace_id="trace-p0-chain",
        trigger_source="test",
    )
    assert atomic_result.status == "succeeded", atomic_result
    atomic_set = AtomicSignalSet.objects.get(id=atomic_result.data["atomic_signal_set_id"])

    domain_result = build_domain_signals(
        atomic_signal_set_id=atomic_set.id,
        strategy_analysis_release_id=release.id,
        release_hash=release.release_hash,
        expected_definition_set_hash=_definition_set_hash(release, ReleaseItemComponentType.DOMAIN_SIGNAL_DEFINITION),
        business_request_key="p0-default-chain-domain",
        trace_id="trace-p0-chain",
        trigger_source="test",
    )
    assert domain_result.status == "succeeded", domain_result
    domain_set = DomainSignalSet.objects.get(id=domain_result.data["domain_signal_set_id"])

    regime_definition = MarketRegimeDefinition.objects.get(definition_code="context_structure_regime_v1")
    regime_result = classify_for_strategy_routing(
        domain_signal_set_id=domain_set.id,
        strategy_analysis_release_id=release.id,
        strategy_analysis_release_hash=release.release_hash,
        expected_market_regime_definition_hash=regime_definition.definition_hash,
        business_request_key="p0-default-chain-regime",
        trace_id="trace-p0-chain",
        trigger_source="test",
    )
    assert regime_result.status == "succeeded", regime_result
    regime = MarketRegimeSnapshot.objects.get(id=regime_result.data["market_regime_snapshot_id"])
    assert regime.regime_code == "bullish_pullback"

    strategy_definition_hash = _definition_set_hash(release, ReleaseItemComponentType.STRATEGY_DEFINITION)
    route_policy = StrategyRoutePolicy.objects.get(policy_code="context_structure_strategy_routing", policy_version="v1")
    route_result = route_for_strategy_signal(
        market_regime_snapshot_id=regime.id,
        strategy_analysis_release_id=release.id,
        strategy_analysis_release_hash=release.release_hash,
        expected_strategy_route_policy_hash=route_policy.definition_hash,
        expected_strategy_definition_set_hash=strategy_definition_hash,
        business_request_key="p0-default-chain-route",
        trace_id="trace-p0-chain",
        trigger_source="test",
    )
    assert route_result.status == "succeeded", route_result
    route = StrategyRouteDecision.objects.get(id=route_result.data["strategy_route_decision_id"])
    assert route.selected_strategy_definition.strategy_code == "long_pullback_support"

    signal_result = generate_strategy_signal(
        strategy_route_decision_id=route.id,
        strategy_analysis_release_id=release.id,
        strategy_analysis_release_hash=release.release_hash,
        expected_strategy_definition_hash=route.selected_strategy_definition.definition_hash,
        business_request_key="p0-default-chain-signal",
        trace_id="trace-p0-chain",
        trigger_source="test",
    )
    assert signal_result.status == "succeeded", signal_result
    signal = StrategySignal.objects.get(id=signal_result.data["strategy_signal_id"])
    assert signal.direction == "bullish"
    _assert_zone(signal.trade_price_condition["acceptable_price_zone"], lower="49000", upper="50000")

    quality_rule_set = StrategySignalQualityRuleSet.objects.get(rule_set_code="default_strategy_signal_quality")
    quality_result = validate_strategy_signal(
        strategy_signal_id=signal.id,
        strategy_analysis_release_id=release.id,
        strategy_analysis_release_hash=release.release_hash,
        expected_quality_rule_set_hash=quality_rule_set.rule_set_hash,
        business_request_key="p0-default-chain-quality",
        validation_mode=StrategySignalQualityValidationMode.LIVE,
        trace_id="trace-p0-chain",
        trigger_source="test",
    )
    assert quality_result.status == "succeeded", quality_result
    quality = StrategySignalQualityResult.objects.get(id=quality_result.data["quality_result_id"])
    assert quality.quality_status == StrategySignalQualityStatus.PASSED
    assert quality.allows_decision_snapshot is True

    decision_result = build_decision_snapshot(
        strategy_signal_quality_result_id=quality.id,
        strategy_analysis_release_id=release.id,
        strategy_analysis_release_hash=release.release_hash,
        business_request_key="p0-default-chain-decision",
        trace_id="trace-p0-chain",
        trigger_source="test",
    )
    assert decision_result.status == "succeeded", decision_result
    decision = DecisionSnapshot.objects.get(id=decision_result.data["decision_snapshot_id"])
    assert decision.allows_order_plan is True, {
        "signal_strength": str(signal.strength),
        "signal_confidence": str(signal.confidence),
        "target_intent": decision.target_intent,
        "target_position_ratio": str(decision.target_position_ratio),
        "target_reason_code": decision.target_reason_code,
        "blocked_reason": decision.blocked_reason,
        "expires_at_utc": decision.expires_at_utc.isoformat() if decision.expires_at_utc else None,
        "created_at_utc": decision.created_at_utc.isoformat() if decision.created_at_utc else None,
        "calculation_snapshot": decision.decision_calculation_snapshot,
    }
    _assert_zone(decision.frozen_trade_price_condition["acceptable_price_zone"], lower="49000", upper="50000")

    settings.ORDER_PLAN_SUPPORTED_ORDER_TYPES = ["MARKET", "LIMIT"]
    _enable_runtime_permission(settings)
    account = _account_facts(position="0", order_types=["MARKET", "LIMIT"])
    price = _price(value="51000")
    order_plan_result = _run(
        decision=decision,
        account=account,
        price=price,
        key="p0-default-chain-order-plan",
    )
    assert order_plan_result.status == "succeeded", order_plan_result
    plan = OrderPlan.objects.get(id=order_plan_result.data["order_plan_id"])
    assert plan.status == OrderPlanStatus.CREATED
    candidate = CandidateOrderIntent.objects.get(order_plan=plan, intent_role=CandidateIntentRole.PRIMARY)
    assert candidate.order_type == "LIMIT"
    assert candidate.limit_price == Decimal("50000")

    RuntimeTradingConfig.objects.all().delete()
