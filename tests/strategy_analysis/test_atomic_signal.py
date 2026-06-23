from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from django.core.management import call_command

from apps.alerts.models import AlertEvent
from apps.market_data.models import DataQualityResult, MarketSnapshot
from apps.strategy_analysis.definition_hashes import (
    atomic_signal_definition_hash,
    atomic_signal_dependency_hash,
    domain_atomic_membership_hash,
)
from apps.strategy_analysis.models import (
    AnalysisObjectStatus,
    AtomicSignalDefinition,
    AtomicSignalDirection,
    AtomicSignalOutputType,
    AtomicSignalSet,
    AtomicSignalValue,
    DefinitionLifecycleStatus,
    FeatureDefinition,
    FeatureSet,
    FeatureValue,
    ReleaseAction,
    ReleaseApprovalStatus,
    ReleaseItemComponentType,
    StrategyAnalysisRelease,
    StrategyAnalysisReleaseActivation,
    StrategyAnalysisReleaseApproval,
    StrategyAnalysisReleaseItem,
)
from apps.strategy_analysis.services.atomic_signal import build_atomic_signals
from apps.strategy_analysis.services.release import calculate_definition_set_hash, calculate_release_hash
from apps.strategy_calculator.atomic_signal import FeatureCompareCalculator
from apps.strategy_calculator.registry import CalculatorRegistry
from apps.strategy_calculator.utils import stable_hash


def utc(hour: int = 0) -> datetime:
    return datetime(2026, 1, 1, hour, tzinfo=UTC)


def registry() -> CalculatorRegistry:
    result = CalculatorRegistry()
    result.register(FeatureCompareCalculator())
    return result


def market_snapshot() -> MarketSnapshot:
    quality_4h = DataQualityResult.objects.create(
        business_request_key="atomic-quality-4h",
        trace_id="trace",
        trigger_source="test",
        exchange="binance",
        market_type="usds_m_futures",
        symbol="BTCUSDT",
        timeframe="4h",
        status="PASS",
        check_start_open_time_utc=utc(0),
        check_end_open_time_utc=utc(4),
        expected_count=2,
        actual_count=2,
        allows_downstream=True,
    )
    quality_1d = DataQualityResult.objects.create(
        business_request_key="atomic-quality-1d",
        trace_id="trace",
        trigger_source="test",
        exchange="binance",
        market_type="usds_m_futures",
        symbol="BTCUSDT",
        timeframe="1d",
        status="PASS",
        check_start_open_time_utc=utc(0),
        check_end_open_time_utc=utc(0),
        expected_count=1,
        actual_count=1,
        allows_downstream=True,
    )
    return MarketSnapshot.objects.create(
        business_request_key="atomic-snapshot",
        exchange="binance",
        market_type="usds_m_futures",
        symbol="BTCUSDT",
        base_timeframe="4h",
        higher_timeframe="1d",
        analysis_close_time_utc=utc(8),
        analysis_reference_time_utc=utc(9),
        latest_4h_open_time_utc=utc(4),
        latest_1d_open_time_utc=utc(0),
        lookback_4h_count=2,
        lookback_1d_count=1,
        actual_4h_count=2,
        actual_1d_count=1,
        start_4h_open_time_utc=utc(0),
        end_4h_open_time_utc=utc(4),
        start_1d_open_time_utc=utc(0),
        end_1d_open_time_utc=utc(0),
        data_quality_result_4h=quality_4h,
        data_quality_result_1d=quality_1d,
        trace_id="trace",
        trigger_source="test",
    )


def feature_definition(code: str) -> FeatureDefinition:
    return FeatureDefinition.objects.create(
        feature_code=code,
        definition_version="1.0.0",
        definition_hash=stable_hash({"feature": code}),
        algorithm_name="test_feature",
        algorithm_version="1.0.0",
        params={},
        params_hash=stable_hash({}),
        value_type="decimal",
        input_timeframes=["4h"],
        output_schema_version="1.0",
    )


def build_fixture(
    *,
    left: str = "110",
    right: str = "100",
    atomic_required: bool = True,
    release_active: bool = True,
) -> tuple[FeatureSet, StrategyAnalysisRelease, AtomicSignalDefinition]:
    snapshot = market_snapshot()
    left_definition = feature_definition("sma_4h_20")
    right_definition = feature_definition("sma_4h_60")
    params = {
        "left_feature_code": "sma_4h_20",
        "operator": "gt",
        "right_feature_code": "sma_4h_60",
    }
    params_hash = stable_hash(params)
    dependencies = ["sma_4h_20", "sma_4h_60"]
    definition_hash = atomic_signal_definition_hash(
        signal_code="sma_4h_20_above_sma_4h_60",
        default_direction=AtomicSignalDirection.BULLISH,
        algorithm_name="feature_compare",
        algorithm_version="1.0.0",
        params_hash=params_hash,
        is_required=atomic_required,
        depends_on_feature_codes=dependencies,
        output_type=AtomicSignalOutputType.BOOLEAN,
    )
    atomic_definition = AtomicSignalDefinition.objects.create(
        signal_code="sma_4h_20_above_sma_4h_60",
        default_direction=AtomicSignalDirection.BULLISH,
        algorithm_name="feature_compare",
        algorithm_version="1.0.0",
        params=params,
        params_hash=params_hash,
        definition_hash=definition_hash,
        status=DefinitionLifecycleStatus.ACTIVE,
        enabled=True,
        is_required=atomic_required,
        depends_on_feature_codes=dependencies,
        output_type=AtomicSignalOutputType.BOOLEAN,
    )
    release = StrategyAnalysisRelease.objects.create(release_code="atomic-release")
    for definition in (left_definition, right_definition):
        StrategyAnalysisReleaseItem.objects.create(
            release=release,
            component_type=ReleaseItemComponentType.FEATURE_DEFINITION,
            component_object_id=definition.id,
            component_code=definition.feature_code,
            definition_hash=definition.definition_hash,
            algorithm_name=definition.algorithm_name,
            algorithm_version=definition.algorithm_version,
            params_hash=definition.params_hash,
        )
    StrategyAnalysisReleaseItem.objects.create(
        release=release,
        component_type=ReleaseItemComponentType.ATOMIC_SIGNAL_DEFINITION,
        component_object_id=atomic_definition.id,
        component_code=atomic_definition.signal_code,
        definition_hash=atomic_definition.definition_hash,
        algorithm_name=atomic_definition.algorithm_name,
        algorithm_version=atomic_definition.algorithm_version,
        params_hash=atomic_definition.params_hash,
        dependency_hash=atomic_signal_dependency_hash(dependencies),
    )
    domain_payload = {
        "allowed_atomic_signal_codes": [atomic_definition.signal_code],
        "required_atomic_signal_codes": [atomic_definition.signal_code],
    }
    StrategyAnalysisReleaseItem.objects.create(
        release=release,
        component_type=ReleaseItemComponentType.DOMAIN_SIGNAL_DEFINITION,
        component_object_id=999,
        component_code="trend",
        definition_hash=stable_hash({"domain": "trend"}),
        dependency_hash=domain_atomic_membership_hash(domain_payload),
        payload_summary=domain_payload,
    )
    release.release_hash = calculate_release_hash(release)
    release.approval_status = ReleaseApprovalStatus.APPROVED
    release.is_active = release_active
    release.active_slot = 1 if release_active else None
    release.save(update_fields=["release_hash", "approval_status", "is_active", "active_slot", "updated_at_utc"])
    StrategyAnalysisReleaseApproval.objects.create(
        release=release,
        release_hash=release.release_hash,
        action=ReleaseAction.APPROVE,
        validation_evidence_refs=["fixture"],
        reason="AtomicSignal service fixture",
        operator_id="tester",
        trace_id="trace",
        trigger_source="test",
    )
    StrategyAnalysisReleaseActivation.objects.create(
        release=release,
        release_hash=release.release_hash,
        action=ReleaseAction.ACTIVATE,
        operator_id="tester",
        reason="AtomicSignal service fixture",
        trace_id="trace",
        trigger_source="test",
    )
    feature_set = FeatureSet.objects.create(
        feature_set_key=stable_hash({"feature_set": "atomic"}),
        business_request_key="atomic-feature-set",
        market_snapshot=snapshot,
        strategy_analysis_release=release,
        release_hash=release.release_hash,
        status=AnalysisObjectStatus.CREATED,
        is_usable=True,
        allows_atomic_signal=True,
        feature_schema_version="1.0",
        definition_set_hash=stable_hash({"features": dependencies}),
        feature_count=2,
        trace_id="trace",
        trigger_source="test",
    )
    FeatureValue.objects.create(
        feature_set=feature_set,
        feature_definition=left_definition,
        feature_code=left_definition.feature_code,
        feature_definition_hash=left_definition.definition_hash,
        algorithm_name=left_definition.algorithm_name,
        algorithm_version=left_definition.algorithm_version,
        params_hash=left_definition.params_hash,
        value_type="decimal",
        numeric_value=left,
        output_schema_version="1.0",
        status=AnalysisObjectStatus.CREATED,
        is_valid=True,
    )
    FeatureValue.objects.create(
        feature_set=feature_set,
        feature_definition=right_definition,
        feature_code=right_definition.feature_code,
        feature_definition_hash=right_definition.definition_hash,
        algorithm_name=right_definition.algorithm_name,
        algorithm_version=right_definition.algorithm_version,
        params_hash=right_definition.params_hash,
        value_type="decimal",
        numeric_value=right,
        output_schema_version="1.0",
        status=AnalysisObjectStatus.CREATED,
        is_valid=True,
    )
    return feature_set, release, atomic_definition


def run_service(feature_set: FeatureSet, release: StrategyAnalysisRelease, *, key: str = "atomic-build", dry_run: bool = False):
    atomic_items = tuple(
        release.items.filter(component_type=ReleaseItemComponentType.ATOMIC_SIGNAL_DEFINITION)
    )
    return build_atomic_signals(
        feature_set_id=feature_set.id,
        strategy_analysis_release_id=release.id,
        release_hash=release.release_hash,
        expected_definition_set_hash=calculate_definition_set_hash(atomic_items),
        business_request_key=key,
        trace_id="trace",
        trigger_source="test",
        dry_run=dry_run,
        registry=registry(),
    )


@pytest.mark.django_db
def test_atomic_signal_builds_bullish_value_from_feature_set() -> None:
    feature_set, release, _definition = build_fixture()

    result = run_service(feature_set, release)

    assert result.status.value == "succeeded"
    signal_set = AtomicSignalSet.objects.get()
    value = AtomicSignalValue.objects.get()
    assert signal_set.status == AnalysisObjectStatus.CREATED
    assert signal_set.allows_domain_signal is True
    assert value.direction == AtomicSignalDirection.BULLISH
    assert value.strength == Decimal("1")
    assert value.confidence is None
    assert value.used_feature_value_ids == list(feature_set.values.order_by("feature_code").values_list("id", flat=True))


@pytest.mark.django_db
def test_atomic_signal_condition_false_is_valid_neutral() -> None:
    feature_set, release, _definition = build_fixture(left="90", right="100")

    result = run_service(feature_set, release)

    assert result.status.value == "succeeded"
    value = AtomicSignalValue.objects.get()
    assert value.status == AnalysisObjectStatus.CREATED
    assert value.is_valid is True
    assert value.direction == AtomicSignalDirection.NEUTRAL
    assert value.strength == Decimal("0")


@pytest.mark.django_db
def test_atomic_signal_missing_declared_feature_blocks_without_set() -> None:
    feature_set, release, _definition = build_fixture()
    feature_set.values.filter(feature_code="sma_4h_60").delete()
    FeatureSet.objects.filter(id=feature_set.id).update(feature_count=1)

    result = run_service(feature_set, release)

    assert result.status.value == "blocked"
    assert result.reason_code == "atomic_signal_feature_value_missing"
    assert AtomicSignalSet.objects.count() == 0


@pytest.mark.django_db
def test_atomic_signal_invalid_optional_value_hits_failure_ratio() -> None:
    feature_set, release, _definition = build_fixture(atomic_required=False)
    feature_set.values.filter(feature_code="sma_4h_60").update(is_valid=False)

    result = run_service(feature_set, release)

    assert result.status.value == "failed"
    signal_set = AtomicSignalSet.objects.get()
    value = AtomicSignalValue.objects.get()
    assert signal_set.failure_ratio == Decimal("1")
    assert signal_set.error_code == "atomic_signal_failure_ratio_exceeded"
    assert signal_set.allows_domain_signal is False
    assert value.status == AnalysisObjectStatus.FAILED
    assert value.direction == AtomicSignalDirection.NEUTRAL
    assert AlertEvent.objects.filter(event_type="atomic_signal_set_failed").exists()


@pytest.mark.django_db
def test_atomic_signal_dry_run_does_not_write_business_objects_or_alerts() -> None:
    feature_set, release, _definition = build_fixture()

    result = run_service(feature_set, release, dry_run=True)

    assert result.status.value == "succeeded"
    assert result.data["persisted"] is False
    assert AtomicSignalSet.objects.count() == 0
    assert AtomicSignalValue.objects.count() == 0
    assert AlertEvent.objects.count() == 0


@pytest.mark.django_db
def test_atomic_signal_keeps_frozen_release_after_background_switch() -> None:
    feature_set, release, _definition = build_fixture(release_active=False)

    result = run_service(feature_set, release)

    assert result.status.value == "succeeded"


@pytest.mark.django_db
def test_atomic_signal_same_input_identity_is_idempotent() -> None:
    feature_set, release, _definition = build_fixture()

    first = run_service(feature_set, release, key="atomic-first")
    second = run_service(feature_set, release, key="atomic-second")

    assert first.data["atomic_signal_set_id"] == second.data["atomic_signal_set_id"]
    assert AtomicSignalSet.objects.count() == 1


@pytest.mark.django_db
def test_seed_atomic_signal_definitions_is_idempotent() -> None:
    feature_definition("sma_4h_20")
    feature_definition("sma_4h_60")

    call_command("seed_atomic_signal_definitions")
    call_command("seed_atomic_signal_definitions")

    definition = AtomicSignalDefinition.objects.get(signal_code="sma_4h_20_above_sma_4h_60")
    assert AtomicSignalDefinition.objects.count() == 1
    assert definition.status == DefinitionLifecycleStatus.ACTIVE
    assert definition.enabled is True
