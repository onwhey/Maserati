from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from django.db import IntegrityError, transaction

from apps.foundation.idempotency import build_idempotency_key
from apps.foundation.results import ResultStatus
from apps.market_data.domain import DATA_SOURCE_BINANCE_REST
from apps.market_data.models import DataQualityResult, Kline, MarketSnapshot
from apps.strategy_analysis.models import (
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
from apps.strategy_analysis.services.feature_layer import build_feature_set
from apps.strategy_analysis.services.release import (
    approve_release,
    calculate_definition_set_hash,
    calculate_release_hash,
    create_validation_evidence,
    freeze_release_for_validation,
)
from apps.strategy_calculator.contracts import CalculatorInput, CalculatorMetadata, CalculatorOutput, CalculatorType
from apps.strategy_calculator.registry import CalculatorRegistry
from apps.strategy_calculator.utils import stable_hash


def dt(year: int, month: int, day: int, hour: int = 0) -> datetime:
    return datetime(year, month, day, hour, tzinfo=UTC)


class FakeCalculator:
    def __init__(self, calculator_type: CalculatorType, name: str) -> None:
        self.metadata = CalculatorMetadata(
            algorithm_name=name,
            algorithm_version="1.0.0",
            calculator_type=calculator_type,
            input_schema_version="1.0",
            output_schema_version="1.0",
            deterministic=True,
            supports_dry_run=True,
            algorithm_requirement_document_path=f"docs/requirements/{calculator_type}/{name}.md",
            implementation_document_path=f"docs/implementation/{calculator_type}/{name}__1.0.0.md",
        )

    def calculate(self, calculation_input: CalculatorInput) -> CalculatorOutput:
        return CalculatorOutput.succeeded(
            output_schema_version="1.0",
            values={"value": Decimal("123.45")},
            evidence_items=({"calculator": self.metadata.algorithm_name},),
        )


def register_required_calculators() -> CalculatorRegistry:
    registry = CalculatorRegistry()
    registry.register(FakeCalculator(CalculatorType.FEATURE_LAYER, "fake_feature"))
    registry.register(FakeCalculator(CalculatorType.ATOMIC_SIGNAL, "fake_atomic"))
    registry.register(FakeCalculator(CalculatorType.DOMAIN_SIGNAL, "fake_domain"))
    registry.register(FakeCalculator(CalculatorType.MARKET_REGIME, "fake_regime"))
    registry.register(FakeCalculator(CalculatorType.STRATEGY_SIGNAL, "fake_strategy"))
    registry.register(FakeCalculator(CalculatorType.DECISION_POLICY, "fake_decision"))
    return registry


def create_kline(open_time: datetime, timeframe: str = "4h") -> Kline:
    delta = timedelta(hours=4) if timeframe == "4h" else timedelta(days=1)
    return Kline.objects.create(
        exchange="binance",
        market_type="usds_m_futures",
        symbol="BTCUSDT",
        timeframe=timeframe,
        open_time_utc=open_time,
        close_time_utc=open_time + delta,
        open_price="100",
        high_price="110",
        low_price="90",
        close_price="105",
        volume="1.5",
        quote_volume="150",
        trade_count=10,
        data_source=DATA_SOURCE_BINANCE_REST,
    )


def quality_pass(timeframe: str, start_open: datetime, end_open: datetime, count: int) -> DataQualityResult:
    return DataQualityResult.objects.create(
        business_request_key=build_idempotency_key("quality", timeframe, start_open.isoformat(), end_open.isoformat()),
        trace_id="trace_quality",
        trigger_source="test",
        exchange="binance",
        market_type="usds_m_futures",
        symbol="BTCUSDT",
        timeframe=timeframe,
        status="PASS",
        check_start_open_time_utc=start_open,
        check_end_open_time_utc=end_open,
        expected_count=count,
        actual_count=count,
        allows_downstream=True,
        coverage_start_open_time_utc=start_open,
        coverage_end_open_time_utc=end_open,
    )


def create_market_snapshot() -> MarketSnapshot:
    create_kline(dt(2026, 1, 1, 4))
    create_kline(dt(2026, 1, 1, 8))
    create_kline(dt(2025, 12, 30), timeframe="1d")
    create_kline(dt(2025, 12, 31), timeframe="1d")
    quality_4h = quality_pass("4h", dt(2026, 1, 1, 4), dt(2026, 1, 1, 8), 2)
    quality_1d = quality_pass("1d", dt(2025, 12, 30), dt(2025, 12, 31), 2)
    return MarketSnapshot.objects.create(
        business_request_key="snapshot:strategy-analysis",
        exchange="binance",
        market_type="usds_m_futures",
        symbol="BTCUSDT",
        base_timeframe="4h",
        higher_timeframe="1d",
        analysis_close_time_utc=dt(2026, 1, 1, 12),
        analysis_reference_time_utc=dt(2026, 1, 1, 13),
        latest_4h_open_time_utc=dt(2026, 1, 1, 8),
        latest_1d_open_time_utc=dt(2025, 12, 31),
        lookback_4h_count=2,
        lookback_1d_count=2,
        actual_4h_count=2,
        actual_1d_count=2,
        start_4h_open_time_utc=dt(2026, 1, 1, 4),
        end_4h_open_time_utc=dt(2026, 1, 1, 8),
        start_1d_open_time_utc=dt(2025, 12, 30),
        end_1d_open_time_utc=dt(2025, 12, 31),
        data_quality_result_4h=quality_4h,
        data_quality_result_1d=quality_1d,
        trace_id="trace_snapshot",
        trigger_source="test",
    )


def create_full_release() -> tuple[StrategyAnalysisRelease, FeatureDefinition]:
    feature = FeatureDefinition.objects.create(
        feature_code="test_feature",
        definition_version="1.0.0",
        definition_hash=stable_hash({"feature": "test_feature"}),
        algorithm_name="fake_feature",
        algorithm_version="1.0.0",
        params={},
        params_hash=stable_hash({}),
        value_type="decimal",
        input_timeframes=["4h"],
        output_schema_version="1.0",
    )
    release = StrategyAnalysisRelease.objects.create(release_code="release_test", created_by="test")
    StrategyAnalysisReleaseItem.objects.create(
        release=release,
        component_type=ReleaseItemComponentType.FEATURE_DEFINITION,
        component_object_id=feature.id,
        component_code=feature.feature_code,
        definition_hash=feature.definition_hash,
        algorithm_name=feature.algorithm_name,
        algorithm_version=feature.algorithm_version,
        params_hash=feature.params_hash,
    )
    for code in ("atomic_1",):
        StrategyAnalysisReleaseItem.objects.create(
            release=release,
            component_type=ReleaseItemComponentType.ATOMIC_SIGNAL_DEFINITION,
            component_object_id=100,
            component_code=code,
            definition_hash=stable_hash({"atomic": code}),
            algorithm_name="fake_atomic",
            algorithm_version="1.0.0",
            params_hash=stable_hash({}),
        )
    for code in ("trend", "momentum", "volatility"):
        StrategyAnalysisReleaseItem.objects.create(
            release=release,
            component_type=ReleaseItemComponentType.DOMAIN_SIGNAL_DEFINITION,
            component_object_id=200,
            component_code=code,
            definition_hash=stable_hash({"domain": code}),
            algorithm_name="fake_domain",
            algorithm_version="1.0.0",
            params_hash=stable_hash({}),
        )
    StrategyAnalysisReleaseItem.objects.create(
        release=release,
        component_type=ReleaseItemComponentType.MARKET_REGIME_DEFINITION,
        component_object_id=300,
        component_code="regime_default",
        definition_hash=stable_hash({"regime": "default"}),
        algorithm_name="fake_regime",
        algorithm_version="1.0.0",
        params_hash=stable_hash({}),
    )
    StrategyAnalysisReleaseItem.objects.create(
        release=release,
        component_type=ReleaseItemComponentType.STRATEGY_ROUTE_POLICY,
        component_object_id=400,
        component_code="route_policy_default",
        definition_hash=stable_hash({"route_policy": "default"}),
    )
    StrategyAnalysisReleaseItem.objects.create(
        release=release,
        component_type=ReleaseItemComponentType.STRATEGY_ROUTE_RULE,
        component_object_id=401,
        component_code="route_rule_default",
        definition_hash=stable_hash({"route_rule": "default"}),
    )
    StrategyAnalysisReleaseItem.objects.create(
        release=release,
        component_type=ReleaseItemComponentType.STRATEGY_DEFINITION,
        component_object_id=500,
        component_code="strategy_default",
        definition_hash=stable_hash({"strategy": "default"}),
        algorithm_name="fake_strategy",
        algorithm_version="1.0.0",
        params_hash=stable_hash({}),
    )
    StrategyAnalysisReleaseItem.objects.create(
        release=release,
        component_type=ReleaseItemComponentType.STRATEGY_SIGNAL_QUALITY_RULE_SET,
        component_object_id=600,
        component_code="quality_default",
        definition_hash=stable_hash({"quality": "default"}),
    )
    StrategyAnalysisReleaseItem.objects.create(
        release=release,
        component_type=ReleaseItemComponentType.DECISION_POLICY_DEFINITION,
        component_object_id=700,
        component_code="decision_default",
        definition_hash=stable_hash({"decision": "default"}),
        algorithm_name="fake_decision",
        algorithm_version="1.0.0",
        params_hash=stable_hash({}),
    )
    return release, feature


def create_frozen_feature_release_fixture(*, active: bool = True) -> tuple[StrategyAnalysisRelease, FeatureDefinition]:
    feature = FeatureDefinition.objects.create(
        feature_code="test_feature",
        definition_version="1.0.0",
        definition_hash=stable_hash({"feature": "test_feature"}),
        algorithm_name="fake_feature",
        algorithm_version="1.0.0",
        params={},
        params_hash=stable_hash({}),
        value_type="decimal",
        input_timeframes=["4h"],
        output_schema_version="1.0",
    )
    release = StrategyAnalysisRelease.objects.create(release_code=f"feature_fixture_{'active' if active else 'inactive'}")
    StrategyAnalysisReleaseItem.objects.create(
        release=release,
        component_type=ReleaseItemComponentType.FEATURE_DEFINITION,
        component_object_id=feature.id,
        component_code=feature.feature_code,
        definition_hash=feature.definition_hash,
        algorithm_name=feature.algorithm_name,
        algorithm_version=feature.algorithm_version,
        params_hash=feature.params_hash,
    )
    release.release_hash = calculate_release_hash(release)
    release.approval_status = ReleaseApprovalStatus.APPROVED
    release.is_active = active
    release.active_slot = 1 if active else None
    release.save(update_fields=["release_hash", "approval_status", "is_active", "active_slot", "updated_at_utc"])
    StrategyAnalysisReleaseApproval.objects.create(
        release=release,
        release_hash=release.release_hash,
        action=ReleaseAction.APPROVE,
        validation_evidence_refs=["test-fixture"],
        reason="isolated FeatureLayer contract fixture",
        operator_id="tester",
        trace_id="trace_release",
        trigger_source="test",
    )
    StrategyAnalysisReleaseActivation.objects.create(
        release=release,
        release_hash=release.release_hash,
        action=ReleaseAction.ACTIVATE,
        operator_id="tester",
        reason="isolated FeatureLayer contract fixture",
        trace_id="trace_release",
        trigger_source="test",
    )
    return release, feature


@pytest.mark.django_db
def test_release_requires_validation_evidence_before_approval() -> None:
    registry = register_required_calculators()
    release, _feature = create_full_release()
    freeze_release_for_validation(release_id=release.id, trace_id="trace_release", trigger_source="test")

    result = approve_release(
        release_id=release.id,
        operator_id="tester",
        reason="test approval",
        trace_id="trace_release",
        trigger_source="test",
        registry=registry,
    )

    assert result.status == ResultStatus.BLOCKED
    assert result.reason_code == "validation_evidence_missing"


@pytest.mark.django_db
def test_release_rejects_fake_component_objects() -> None:
    registry = register_required_calculators()
    release, _feature = create_full_release()
    freeze_release_for_validation(release_id=release.id, trace_id="trace_release", trigger_source="test")
    create_validation_evidence(
        release_id=release.id,
        evidence_type="test_result",
        evidence_ref="pytest",
        summary="test evidence",
        created_by="tester",
        trace_id="trace_release",
        trigger_source="test",
    )

    approved = approve_release(
        release_id=release.id,
        operator_id="tester",
        reason="test approval",
        trace_id="trace_release",
        trigger_source="test",
        registry=registry,
    )
    assert approved.status == ResultStatus.BLOCKED
    assert approved.reason_code == "release_integrity_failed"
    assert any("指向的真实定义不存在" in error or "缺少真实组件对象" in error for error in approved.data["errors"])
    release.refresh_from_db()
    assert release.is_active is False


@pytest.mark.django_db
def test_feature_layer_blocks_when_release_not_approved() -> None:
    registry = register_required_calculators()
    snapshot = create_market_snapshot()
    release, _feature = create_full_release()

    result = build_feature_set(
        market_snapshot_id=snapshot.id,
        strategy_analysis_release_id=release.id,
        release_hash="not-frozen",
        expected_definition_set_hash="",
        business_request_key="feature-set:not-active",
        trace_id="trace_feature",
        trigger_source="test",
        registry=registry,
    )

    assert result.status == ResultStatus.BLOCKED
    assert FeatureSet.objects.count() == 0


@pytest.mark.django_db
def test_feature_layer_uses_only_release_feature_slice_and_writes_feature_values() -> None:
    registry = register_required_calculators()
    snapshot = create_market_snapshot()
    release, _feature = create_frozen_feature_release_fixture()
    feature_items = tuple(release.items.filter(component_type=ReleaseItemComponentType.FEATURE_DEFINITION))

    result = build_feature_set(
        market_snapshot_id=snapshot.id,
        strategy_analysis_release_id=release.id,
        release_hash=release.release_hash,
        expected_definition_set_hash=calculate_definition_set_hash(feature_items),
        business_request_key="feature-set:create",
        trace_id="trace_feature",
        trigger_source="test",
        registry=registry,
    )

    assert result.status == ResultStatus.SUCCEEDED
    assert FeatureSet.objects.count() == 1
    assert FeatureValue.objects.get().numeric_value == Decimal("123.450000000000000000")


@pytest.mark.django_db
def test_feature_layer_dry_run_does_not_write_business_objects() -> None:
    registry = register_required_calculators()
    snapshot = create_market_snapshot()
    release, _feature = create_frozen_feature_release_fixture()
    feature_items = tuple(release.items.filter(component_type=ReleaseItemComponentType.FEATURE_DEFINITION))

    result = build_feature_set(
        market_snapshot_id=snapshot.id,
        strategy_analysis_release_id=release.id,
        release_hash=release.release_hash,
        expected_definition_set_hash=calculate_definition_set_hash(feature_items),
        business_request_key="feature-set:dry-run",
        trace_id="trace_feature",
        trigger_source="test",
        dry_run=True,
        registry=registry,
    )

    assert result.status == ResultStatus.SUCCEEDED
    assert result.data["persisted"] is False
    assert FeatureSet.objects.count() == 0
    assert FeatureValue.objects.count() == 0


@pytest.mark.django_db
def test_frozen_release_remains_consumable_after_background_switch() -> None:
    registry = register_required_calculators()
    snapshot = create_market_snapshot()
    release, _feature = create_frozen_feature_release_fixture(active=False)
    feature_items = tuple(release.items.filter(component_type=ReleaseItemComponentType.FEATURE_DEFINITION))

    result = build_feature_set(
        market_snapshot_id=snapshot.id,
        strategy_analysis_release_id=release.id,
        release_hash=release.release_hash,
        expected_definition_set_hash=calculate_definition_set_hash(feature_items),
        business_request_key="feature-set:frozen-inactive",
        trace_id="trace_feature",
        trigger_source="test",
        registry=registry,
    )

    assert result.status == ResultStatus.SUCCEEDED
    assert FeatureSet.objects.get().strategy_analysis_release_id == release.id


@pytest.mark.django_db
def test_feature_layer_rejects_kline_window_changed_after_snapshot() -> None:
    registry = register_required_calculators()
    snapshot = create_market_snapshot()
    release, _feature = create_frozen_feature_release_fixture()
    feature_items = tuple(release.items.filter(component_type=ReleaseItemComponentType.FEATURE_DEFINITION))
    Kline.objects.filter(timeframe="4h").order_by("open_time_utc").first().delete()

    result = build_feature_set(
        market_snapshot_id=snapshot.id,
        strategy_analysis_release_id=release.id,
        release_hash=release.release_hash,
        expected_definition_set_hash=calculate_definition_set_hash(feature_items),
        business_request_key="feature-set:window-mismatch",
        trace_id="trace_feature",
        trigger_source="test",
        registry=registry,
    )

    assert result.status == ResultStatus.FAILED
    assert result.reason_code == "4h_kline_count_mismatch"
    assert FeatureSet.objects.count() == 0


@pytest.mark.django_db
def test_feature_layer_rejects_params_changed_without_new_hash() -> None:
    registry = register_required_calculators()
    snapshot = create_market_snapshot()
    release, feature = create_frozen_feature_release_fixture()
    feature_items = tuple(release.items.filter(component_type=ReleaseItemComponentType.FEATURE_DEFINITION))
    FeatureDefinition.objects.filter(id=feature.id).update(params={"window": 20})

    result = build_feature_set(
        market_snapshot_id=snapshot.id,
        strategy_analysis_release_id=release.id,
        release_hash=release.release_hash,
        expected_definition_set_hash=calculate_definition_set_hash(feature_items),
        business_request_key="feature-set:params-mismatch",
        trace_id="trace_feature",
        trigger_source="test",
        registry=registry,
    )

    assert result.status == ResultStatus.BLOCKED
    assert result.reason_code == "feature_definition_identity_mismatch"
    assert FeatureSet.objects.count() == 0


@pytest.mark.django_db
def test_database_prevents_two_active_releases() -> None:
    StrategyAnalysisRelease.objects.create(
        release_code="active_one",
        approval_status=ReleaseApprovalStatus.APPROVED,
        is_active=True,
        active_slot=1,
    )

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            StrategyAnalysisRelease.objects.create(
                release_code="active_two",
                approval_status=ReleaseApprovalStatus.APPROVED,
                is_active=True,
                active_slot=1,
            )
