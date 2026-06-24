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
    domain_signal_definition_hash,
    normalize_atomic_signal_codes,
)
from apps.strategy_analysis.models import (
    AnalysisObjectStatus,
    AtomicSignalDefinition,
    AtomicSignalDirection,
    AtomicSignalOutputType,
    AtomicSignalSet,
    AtomicSignalValue,
    DefinitionLifecycleStatus,
    DomainSignalDefinition,
    DomainSignalOutputMode,
    DomainSignalSet,
    DomainSignalValue,
    FeatureSet,
    ReleaseAction,
    ReleaseApprovalStatus,
    ReleaseItemComponentType,
    StrategyAnalysisRelease,
    StrategyAnalysisReleaseActivation,
    StrategyAnalysisReleaseApproval,
    StrategyAnalysisReleaseItem,
)
from apps.strategy_analysis.services.domain_signal import build_domain_signals
from apps.strategy_analysis.services.release import calculate_definition_set_hash, calculate_release_hash
from apps.strategy_calculator.contracts import CalculatorInput, CalculatorMetadata, CalculatorOutput, CalculatorType
from apps.strategy_calculator.domain_signal import SingleAtomicPassthroughCalculator
from apps.strategy_calculator.registry import CalculatorRegistry
from apps.strategy_calculator.utils import stable_hash


def utc(hour: int = 0) -> datetime:
    return datetime(2026, 1, 1, hour, tzinfo=UTC)


def registry() -> CalculatorRegistry:
    result = CalculatorRegistry()
    result.register(SingleAtomicPassthroughCalculator())
    return result


class FixedDomainCalculator:
    def __init__(
        self,
        *,
        algorithm_name: str,
        coverage_ratio: Decimal,
        agreement_ratio: Decimal | None,
    ) -> None:
        self.coverage_ratio = coverage_ratio
        self.agreement_ratio = agreement_ratio
        self.metadata = CalculatorMetadata(
            algorithm_name=algorithm_name,
            algorithm_version="1.0.0",
            calculator_type=CalculatorType.DOMAIN_SIGNAL,
            input_schema_version="1.0",
            output_schema_version="1.0",
            deterministic=True,
            supports_dry_run=True,
            algorithm_requirement_document_path="docs/requirements/domain_signals.md",
            implementation_document_path="docs/implementation/domain_signal/test_fixed__1.0.0.md",
        )

    def calculate(self, calculation_input: CalculatorInput) -> CalculatorOutput:
        return CalculatorOutput.succeeded(
            output_schema_version="1.0",
            values={
                "direction": "neutral",
                "state_code": "",
                "strength": Decimal("0.2"),
                "coverage_ratio": self.coverage_ratio,
                "agreement_ratio": self.agreement_ratio,
                "evidence_text_zh": "测试领域 calculator 输出",
            },
            evidence_items=({"calculator": self.metadata.algorithm_name},),
        )


def registry_with(*extra_calculators) -> CalculatorRegistry:
    result = registry()
    for calculator in extra_calculators:
        result.register(calculator)
    return result


def market_snapshot() -> MarketSnapshot:
    quality_4h = DataQualityResult.objects.create(
        business_request_key="domain-quality-4h",
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
        business_request_key="domain-quality-1d",
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
        business_request_key="domain-snapshot",
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


def atomic_definition(signal_code: str) -> AtomicSignalDefinition:
    params = {"code": signal_code}
    params_hash = stable_hash(params)
    dependency = [f"feature_for_{signal_code}"]
    definition_hash = atomic_signal_definition_hash(
        signal_code=signal_code,
        default_direction=AtomicSignalDirection.BULLISH,
        algorithm_name="test_atomic",
        algorithm_version="1.0.0",
        params_hash=params_hash,
        is_required=True,
        depends_on_feature_codes=dependency,
        output_type=AtomicSignalOutputType.BOOLEAN,
    )
    return AtomicSignalDefinition.objects.create(
        signal_code=signal_code,
        default_direction=AtomicSignalDirection.BULLISH,
        algorithm_name="test_atomic",
        algorithm_version="1.0.0",
        params=params,
        params_hash=params_hash,
        definition_hash=definition_hash,
        status=DefinitionLifecycleStatus.ACTIVE,
        enabled=True,
        is_required=True,
        depends_on_feature_codes=dependency,
        output_type=AtomicSignalOutputType.BOOLEAN,
    )


def domain_definition(
    domain_code: str,
    atomic_code: str,
    *,
    output_mode: str = DomainSignalOutputMode.DIRECTIONAL,
) -> DomainSignalDefinition:
    params = {}
    if output_mode == DomainSignalOutputMode.STATE:
        params = {"state_code_when_active": "high", "state_code_when_inactive": "normal"}
    params_hash = stable_hash(params)
    codes = normalize_atomic_signal_codes([atomic_code])
    definition_hash = domain_signal_definition_hash(
        domain_code=domain_code,
        output_mode=output_mode,
        algorithm_name="single_atomic_passthrough",
        algorithm_version="1.0.0",
        params_hash=params_hash,
        is_required=True,
        allowed_atomic_signal_codes=codes,
        required_atomic_signal_codes=codes,
        minimum_coverage_ratio="1",
        agreement_threshold=None,
    )
    return DomainSignalDefinition.objects.create(
        domain_code=domain_code,
        output_mode=output_mode,
        algorithm_name="single_atomic_passthrough",
        algorithm_version="1.0.0",
        params=params,
        params_hash=params_hash,
        definition_hash=definition_hash,
        status=DefinitionLifecycleStatus.ACTIVE,
        enabled=True,
        is_required=True,
        allowed_atomic_signal_codes=list(codes),
        required_atomic_signal_codes=list(codes),
        minimum_coverage_ratio="1",
        agreement_threshold=None,
    )


def build_fixture(*, missing_domain: str | None = None) -> tuple[AtomicSignalSet, StrategyAnalysisRelease]:
    snapshot = market_snapshot()
    release = StrategyAnalysisRelease.objects.create(release_code="domain-release")
    atomic_by_domain = {
        "trend": atomic_definition("atomic_trend"),
        "momentum": atomic_definition("atomic_momentum"),
        "volatility": atomic_definition("atomic_volatility"),
    }
    for definition in atomic_by_domain.values():
        StrategyAnalysisReleaseItem.objects.create(
            release=release,
            component_type=ReleaseItemComponentType.ATOMIC_SIGNAL_DEFINITION,
            component_object_id=definition.id,
            component_code=definition.signal_code,
            definition_hash=definition.definition_hash,
            algorithm_name=definition.algorithm_name,
            algorithm_version=definition.algorithm_version,
            params_hash=definition.params_hash,
            dependency_hash=atomic_signal_dependency_hash(definition.depends_on_feature_codes),
        )
    for domain_code, definition in atomic_by_domain.items():
        if domain_code == missing_domain:
            continue
        output_mode = DomainSignalOutputMode.STATE if domain_code == "volatility" else DomainSignalOutputMode.DIRECTIONAL
        domain = domain_definition(domain_code, definition.signal_code, output_mode=output_mode)
        payload = {
            "allowed_atomic_signal_codes": [definition.signal_code],
            "required_atomic_signal_codes": [definition.signal_code],
        }
        StrategyAnalysisReleaseItem.objects.create(
            release=release,
            component_type=ReleaseItemComponentType.DOMAIN_SIGNAL_DEFINITION,
            component_object_id=domain.id,
            component_code=domain.domain_code,
            definition_hash=domain.definition_hash,
            algorithm_name=domain.algorithm_name,
            algorithm_version=domain.algorithm_version,
            params_hash=domain.params_hash,
            dependency_hash=domain_atomic_membership_hash(payload),
            payload_summary=payload,
        )
    release.release_hash = calculate_release_hash(release)
    release.approval_status = ReleaseApprovalStatus.APPROVED
    release.is_active = True
    release.active_slot = 1
    release.save(update_fields=["release_hash", "approval_status", "is_active", "active_slot", "updated_at_utc"])
    StrategyAnalysisReleaseApproval.objects.create(
        release=release,
        release_hash=release.release_hash,
        action=ReleaseAction.APPROVE,
        validation_evidence_refs=["fixture"],
        reason="DomainSignal fixture",
        operator_id="tester",
        trace_id="trace",
        trigger_source="test",
    )
    StrategyAnalysisReleaseActivation.objects.create(
        release=release,
        release_hash=release.release_hash,
        action=ReleaseAction.ACTIVATE,
        operator_id="tester",
        reason="DomainSignal fixture",
        trace_id="trace",
        trigger_source="test",
    )
    feature_set = FeatureSet.objects.create(
        feature_set_key=stable_hash({"feature_set": "domain"}),
        business_request_key="domain-feature-set",
        market_snapshot=snapshot,
        strategy_analysis_release=release,
        release_hash=release.release_hash,
        status=AnalysisObjectStatus.CREATED,
        is_usable=True,
        allows_atomic_signal=True,
        feature_schema_version="1.0",
        definition_set_hash=stable_hash({"features": []}),
        feature_count=0,
        trace_id="trace",
        trigger_source="test",
    )
    atomic_set = AtomicSignalSet.objects.create(
        atomic_signal_set_key=stable_hash({"atomic_set": "domain"}),
        business_request_key="domain-atomic-set",
        feature_set=feature_set,
        feature_set_key=feature_set.feature_set_key,
        strategy_analysis_release=release,
        release_hash=release.release_hash,
        market_snapshot=snapshot,
        exchange=snapshot.exchange,
        market_type=snapshot.market_type,
        symbol=snapshot.symbol,
        analysis_close_time_utc=snapshot.analysis_close_time_utc,
        signal_schema_version="1.0",
        definition_set_hash=stable_hash({"atomic": list(atomic_by_domain)}),
        status=AnalysisObjectStatus.CREATED,
        is_usable=True,
        allows_domain_signal=True,
        selected_definition_count=3,
        computed_count=3,
        valid_count=3,
        invalid_count=0,
        failed_count=0,
        required_failed_count=0,
        failure_ratio=Decimal("0"),
        failure_block_ratio=Decimal("0.3"),
        trace_id="trace",
        trigger_source="test",
        finished_at_utc=utc(8),
    )
    for definition in atomic_by_domain.values():
        AtomicSignalValue.objects.create(
            atomic_signal_set=atomic_set,
            atomic_signal_definition=definition,
            signal_code=definition.signal_code,
            direction=AtomicSignalDirection.BULLISH,
            strength=Decimal("1"),
            confidence=None,
            status=AnalysisObjectStatus.CREATED,
            is_valid=True,
            definition_status=definition.status,
            definition_enabled=definition.enabled,
            algorithm_name=definition.algorithm_name,
            algorithm_version=definition.algorithm_version,
            params_hash=definition.params_hash,
            definition_hash=definition.definition_hash,
            output_type=definition.output_type,
            value_bool=True,
            evidence_items=[{"signal_code": definition.signal_code}],
            evidence_text_zh="测试原子信号",
            used_feature_codes=[],
            used_feature_value_ids=[],
        )
    return atomic_set, release


def run_service(atomic_set: AtomicSignalSet, release: StrategyAnalysisRelease, *, key: str = "domain-build", dry_run: bool = False):
    domain_items = tuple(
        release.items.filter(component_type=ReleaseItemComponentType.DOMAIN_SIGNAL_DEFINITION)
    )
    return build_domain_signals(
        atomic_signal_set_id=atomic_set.id,
        strategy_analysis_release_id=release.id,
        release_hash=release.release_hash,
        expected_definition_set_hash=calculate_definition_set_hash(domain_items),
        business_request_key=key,
        trace_id="trace",
        trigger_source="test",
        dry_run=dry_run,
        registry=registry(),
    )


def run_service_with_registry(
    atomic_set: AtomicSignalSet,
    release: StrategyAnalysisRelease,
    custom_registry: CalculatorRegistry,
    *,
    key: str = "domain-build",
):
    domain_items = tuple(
        release.items.filter(component_type=ReleaseItemComponentType.DOMAIN_SIGNAL_DEFINITION)
    )
    return build_domain_signals(
        atomic_signal_set_id=atomic_set.id,
        strategy_analysis_release_id=release.id,
        release_hash=release.release_hash,
        expected_definition_set_hash=calculate_definition_set_hash(domain_items),
        business_request_key=key,
        trace_id="trace",
        trigger_source="test",
        registry=custom_registry,
    )


def switch_domain_algorithm(
    *,
    release: StrategyAnalysisRelease,
    atomic_set: AtomicSignalSet,
    domain_code: str,
    algorithm_name: str,
    agreement_threshold: Decimal | None = None,
) -> None:
    domain = DomainSignalDefinition.objects.get(domain_code=domain_code)
    allowed_codes = normalize_atomic_signal_codes(domain.allowed_atomic_signal_codes)
    required_codes = normalize_atomic_signal_codes(domain.required_atomic_signal_codes)
    params_hash = stable_hash(domain.params)
    definition_hash = domain_signal_definition_hash(
        domain_code=domain.domain_code,
        output_mode=domain.output_mode,
        algorithm_name=algorithm_name,
        algorithm_version="1.0.0",
        params_hash=params_hash,
        is_required=domain.is_required,
        allowed_atomic_signal_codes=allowed_codes,
        required_atomic_signal_codes=required_codes,
        minimum_coverage_ratio=domain.minimum_coverage_ratio,
        agreement_threshold=agreement_threshold,
    )
    DomainSignalDefinition.objects.filter(id=domain.id).update(
        algorithm_name=algorithm_name,
        algorithm_version="1.0.0",
        definition_hash=definition_hash,
        agreement_threshold=agreement_threshold,
    )
    payload = {
        "allowed_atomic_signal_codes": list(allowed_codes),
        "required_atomic_signal_codes": list(required_codes),
    }
    release.items.filter(
        component_type=ReleaseItemComponentType.DOMAIN_SIGNAL_DEFINITION,
        component_code=domain_code,
    ).update(
        algorithm_name=algorithm_name,
        algorithm_version="1.0.0",
        definition_hash=definition_hash,
        params_hash=params_hash,
        dependency_hash=domain_atomic_membership_hash(payload),
        payload_summary=payload,
    )
    release.release_hash = calculate_release_hash(release)
    release.save(update_fields=["release_hash", "updated_at_utc"])
    StrategyAnalysisReleaseApproval.objects.filter(release=release).update(release_hash=release.release_hash)
    StrategyAnalysisReleaseActivation.objects.filter(release=release).update(release_hash=release.release_hash)
    atomic_set.release_hash = release.release_hash
    atomic_set.save(update_fields=["release_hash"])


@pytest.mark.django_db
def test_domain_signal_builds_three_formal_domains_from_atomic_set() -> None:
    atomic_set, release = build_fixture()

    result = run_service(atomic_set, release)

    assert result.status.value == "succeeded"
    signal_set = DomainSignalSet.objects.get()
    assert signal_set.atomic_signal_set_id == atomic_set.id
    assert signal_set.allows_market_regime is True
    assert signal_set.computed_count == 3
    assert DomainSignalValue.objects.count() == 3
    assert set(DomainSignalValue.objects.values_list("domain_code", flat=True)) == {"trend", "momentum", "volatility"}
    volatility = DomainSignalValue.objects.get(domain_code="volatility")
    assert volatility.output_mode == DomainSignalOutputMode.STATE
    assert volatility.direction == AtomicSignalDirection.NONE
    assert volatility.state_code == "high"


@pytest.mark.django_db
def test_domain_signal_required_atomic_invalid_fails_set_and_alerts() -> None:
    atomic_set, release = build_fixture()
    AtomicSignalValue.objects.filter(signal_code="atomic_momentum").update(is_valid=False, status=AnalysisObjectStatus.FAILED)

    result = run_service(atomic_set, release)

    assert result.status.value == "failed"
    signal_set = DomainSignalSet.objects.get()
    assert signal_set.status == AnalysisObjectStatus.FAILED
    assert signal_set.allows_market_regime is False
    assert signal_set.required_failed_count == 1
    assert DomainSignalValue.objects.get(domain_code="momentum").is_valid is False
    assert AlertEvent.objects.filter(event_type="domain_signal_set_failed").exists()


@pytest.mark.django_db
def test_domain_signal_low_agreement_does_not_fail_in_service() -> None:
    atomic_set, release = build_fixture()
    switch_domain_algorithm(
        release=release,
        atomic_set=atomic_set,
        domain_code="trend",
        algorithm_name="test_low_agreement",
        agreement_threshold=Decimal("0.9"),
    )
    custom_registry = registry_with(
        FixedDomainCalculator(
            algorithm_name="test_low_agreement",
            coverage_ratio=Decimal("1"),
            agreement_ratio=Decimal("0.1"),
        )
    )

    result = run_service_with_registry(atomic_set, release, custom_registry)

    assert result.status.value == "succeeded"
    trend = DomainSignalValue.objects.get(domain_code="trend")
    assert trend.status == AnalysisObjectStatus.CREATED
    assert trend.is_valid is True
    assert trend.agreement_ratio == Decimal("0.100000000000000000")


@pytest.mark.django_db
def test_domain_signal_rejects_calculator_coverage_mismatch() -> None:
    atomic_set, release = build_fixture()
    switch_domain_algorithm(
        release=release,
        atomic_set=atomic_set,
        domain_code="trend",
        algorithm_name="test_bad_coverage",
    )
    custom_registry = registry_with(
        FixedDomainCalculator(
            algorithm_name="test_bad_coverage",
            coverage_ratio=Decimal("0.5"),
            agreement_ratio=None,
        )
    )

    result = run_service_with_registry(atomic_set, release, custom_registry, key="bad-coverage")

    assert result.status.value == "failed"
    trend = DomainSignalValue.objects.get(domain_code="trend")
    assert trend.status == AnalysisObjectStatus.FAILED
    assert trend.error_code == "domain_signal_contract_invalid"
    assert DomainSignalSet.objects.get().allows_market_regime is False


@pytest.mark.django_db
def test_domain_signal_missing_formal_domain_blocks_without_set() -> None:
    atomic_set, release = build_fixture(missing_domain="volatility")

    result = run_service(atomic_set, release)

    assert result.status.value == "blocked"
    assert result.reason_code == "domain_signal_required_domain_missing"
    assert DomainSignalSet.objects.count() == 0


@pytest.mark.django_db
def test_domain_signal_same_atomic_membership_twice_blocks_without_set() -> None:
    atomic_set, release = build_fixture()
    momentum = DomainSignalDefinition.objects.get(domain_code="momentum")
    duplicate = ["atomic_trend"]
    params_hash = stable_hash(momentum.params)
    new_hash = domain_signal_definition_hash(
        domain_code=momentum.domain_code,
        output_mode=momentum.output_mode,
        algorithm_name=momentum.algorithm_name,
        algorithm_version=momentum.algorithm_version,
        params_hash=params_hash,
        is_required=momentum.is_required,
        allowed_atomic_signal_codes=duplicate,
        required_atomic_signal_codes=duplicate,
        minimum_coverage_ratio=momentum.minimum_coverage_ratio,
        agreement_threshold=momentum.agreement_threshold,
    )
    DomainSignalDefinition.objects.filter(id=momentum.id).update(
        allowed_atomic_signal_codes=duplicate,
        required_atomic_signal_codes=duplicate,
        definition_hash=new_hash,
    )
    payload = {"allowed_atomic_signal_codes": duplicate, "required_atomic_signal_codes": duplicate}
    release.items.filter(component_type=ReleaseItemComponentType.DOMAIN_SIGNAL_DEFINITION, component_code="momentum").update(
        definition_hash=new_hash,
        dependency_hash=domain_atomic_membership_hash(payload),
        payload_summary=payload,
    )
    release.release_hash = calculate_release_hash(release)
    release.save(update_fields=["release_hash", "updated_at_utc"])
    StrategyAnalysisReleaseApproval.objects.filter(release=release).update(release_hash=release.release_hash)
    StrategyAnalysisReleaseActivation.objects.filter(release=release).update(release_hash=release.release_hash)
    atomic_set.release_hash = release.release_hash
    atomic_set.save(update_fields=["release_hash"])

    result = run_service(atomic_set, release)

    assert result.status.value == "blocked"
    assert result.reason_code == "domain_signal_atomic_membership_invalid"
    assert DomainSignalSet.objects.count() == 0


@pytest.mark.django_db
def test_domain_signal_dry_run_does_not_write_business_objects_or_alerts() -> None:
    atomic_set, release = build_fixture()

    result = run_service(atomic_set, release, dry_run=True)

    assert result.status.value == "succeeded"
    assert result.data["persisted"] is False
    assert DomainSignalSet.objects.count() == 0
    assert DomainSignalValue.objects.count() == 0
    assert AlertEvent.objects.count() == 0


@pytest.mark.django_db
def test_domain_signal_dry_run_recalculates_without_reusing_persisted_result() -> None:
    atomic_set, release = build_fixture()

    persisted = run_service(atomic_set, release, key="domain-build")
    dry_run = run_service(atomic_set, release, key="domain-build", dry_run=True)

    assert persisted.status.value == "succeeded"
    assert dry_run.status.value == "succeeded"
    assert dry_run.data["persisted"] is False
    assert "domain_signal_set_id" not in dry_run.data
    assert DomainSignalSet.objects.count() == 1
    assert DomainSignalValue.objects.count() == 3


@pytest.mark.django_db
def test_domain_signal_same_input_identity_is_idempotent() -> None:
    atomic_set, release = build_fixture()

    first = run_service(atomic_set, release, key="domain-first")
    second = run_service(atomic_set, release, key="domain-second")

    assert first.data["domain_signal_set_id"] == second.data["domain_signal_set_id"]
    assert DomainSignalSet.objects.count() == 1


@pytest.mark.django_db
def test_seed_domain_signal_definitions_is_idempotent() -> None:
    atomic_definition("sma_4h_20_above_sma_4h_60")

    call_command("seed_domain_signal_definitions")
    call_command("seed_domain_signal_definitions")

    definition = DomainSignalDefinition.objects.get(domain_code="trend")
    assert DomainSignalDefinition.objects.count() == 1
    assert definition.status == DefinitionLifecycleStatus.ACTIVE
    assert definition.enabled is True
