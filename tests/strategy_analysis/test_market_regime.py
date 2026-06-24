from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from django.db import DataError

from apps.alerts.models import AlertEvent
from apps.market_data.models import DataQualityResult, MarketSnapshot
from apps.strategy_analysis.definition_hashes import (
    domain_atomic_membership_hash,
    domain_signal_definition_hash,
    market_regime_definition_hash,
    market_regime_domain_membership_hash,
    normalize_atomic_signal_codes,
    normalize_domain_codes,
    normalize_regime_codes,
)
from apps.strategy_analysis.models import (
    AnalysisObjectStatus,
    AtomicSignalDirection,
    AtomicSignalSet,
    DefinitionLifecycleStatus,
    DomainSignalDefinition,
    DomainSignalOutputMode,
    DomainSignalSet,
    DomainSignalValue,
    FeatureSet,
    MarketRegimeDefinition,
    MarketRegimeSnapshot,
    ReleaseAction,
    ReleaseApprovalStatus,
    ReleaseItemComponentType,
    StrategyAnalysisRelease,
    StrategyAnalysisReleaseActivation,
    StrategyAnalysisReleaseApproval,
    StrategyAnalysisReleaseItem,
)
from apps.strategy_analysis.services.market_regime import classify_for_strategy_routing
from apps.strategy_analysis.services import market_regime as market_regime_service
from apps.strategy_analysis.services.release import calculate_release_hash
from apps.strategy_calculator.contracts import CalculatorInput, CalculatorMetadata, CalculatorOutput, CalculatorType
from apps.strategy_calculator.registry import CalculatorRegistry
from apps.strategy_calculator.utils import stable_hash


def utc(hour: int = 0) -> datetime:
    return datetime(2026, 1, 1, hour, tzinfo=UTC)


class FakeMarketRegimeCalculator:
    metadata = CalculatorMetadata(
        algorithm_name="test_market_regime",
        algorithm_version="1.0.0",
        calculator_type=CalculatorType.MARKET_REGIME,
        input_schema_version="1.0",
        output_schema_version="1.0",
        deterministic=True,
        supports_dry_run=True,
        algorithm_requirement_document_path="docs/requirements/market_regime/test_market_regime.md",
        implementation_document_path="docs/implementation/market_regime/test_market_regime__1.0.0.md",
    )

    def __init__(
        self,
        *,
        invalid_code: bool = False,
        unexpected_error: bool = False,
        empty_evidence: bool = False,
    ) -> None:
        self.invalid_code = invalid_code
        self.unexpected_error = unexpected_error
        self.empty_evidence = empty_evidence

    def calculate(self, calculation_input: CalculatorInput) -> CalculatorOutput:
        if self.unexpected_error:
            raise RuntimeError("unexpected calculator failure")
        values = dict(calculation_input.values)
        domain_values = list(values["domain_values"])
        used_ids = [item["domain_signal_value_id"] for item in domain_values]
        regime_code = "not_allowed" if self.invalid_code else "trend_up"
        return CalculatorOutput.succeeded(
            output_schema_version="1.0",
            values={
                "regime_code": regime_code,
                "regime_scores": {
                    "trend_up": Decimal("0.8"),
                    "mixed": Decimal("0.2"),
                },
                "regime_confidence": Decimal("0.8"),
                "classification_margin": Decimal("0.6"),
                "used_domain_signal_value_ids": used_ids,
                "evidence_text_zh": "测试算法根据趋势、动量和波动领域事实归类为 trend_up。",
            },
            evidence_items=(
                ()
                if self.empty_evidence
                else ({"used_domain_signal_value_ids": used_ids, "regime_code": regime_code},)
            ),
        )


class NoDryRunMarketRegimeCalculator(FakeMarketRegimeCalculator):
    metadata = CalculatorMetadata(
        algorithm_name="test_market_regime",
        algorithm_version="1.0.0",
        calculator_type=CalculatorType.MARKET_REGIME,
        input_schema_version="1.0",
        output_schema_version="1.0",
        deterministic=True,
        supports_dry_run=False,
        algorithm_requirement_document_path="docs/requirements/market_regime/test_market_regime.md",
        implementation_document_path="docs/implementation/market_regime/test_market_regime__1.0.0.md",
    )


def registry(
    *,
    invalid_code: bool = False,
    empty: bool = False,
    unexpected_error: bool = False,
    empty_evidence: bool = False,
    supports_dry_run: bool = True,
) -> CalculatorRegistry:
    result = CalculatorRegistry()
    if not empty:
        calculator_class = FakeMarketRegimeCalculator if supports_dry_run else NoDryRunMarketRegimeCalculator
        result.register(
            calculator_class(
                invalid_code=invalid_code,
                unexpected_error=unexpected_error,
                empty_evidence=empty_evidence,
            )
        )
    return result


def market_snapshot() -> MarketSnapshot:
    quality_4h = DataQualityResult.objects.create(
        business_request_key="regime-quality-4h",
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
        business_request_key="regime-quality-1d",
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
        business_request_key="regime-snapshot",
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


def domain_definition(domain_code: str) -> DomainSignalDefinition:
    atomic_code = f"atomic_{domain_code}"
    params_hash = stable_hash({})
    atomic_codes = normalize_atomic_signal_codes([atomic_code])
    definition_hash = domain_signal_definition_hash(
        domain_code=domain_code,
        output_mode=DomainSignalOutputMode.DIRECTIONAL,
        algorithm_name="test_domain",
        algorithm_version="1.0.0",
        params_hash=params_hash,
        is_required=True,
        allowed_atomic_signal_codes=atomic_codes,
        required_atomic_signal_codes=atomic_codes,
        minimum_coverage_ratio="1",
        agreement_threshold=None,
    )
    return DomainSignalDefinition.objects.create(
        domain_code=domain_code,
        output_mode=DomainSignalOutputMode.DIRECTIONAL,
        algorithm_name="test_domain",
        algorithm_version="1.0.0",
        params={},
        params_hash=params_hash,
        definition_hash=definition_hash,
        status=DefinitionLifecycleStatus.ACTIVE,
        enabled=True,
        is_required=True,
        allowed_atomic_signal_codes=list(atomic_codes),
        required_atomic_signal_codes=list(atomic_codes),
        minimum_coverage_ratio="1",
        agreement_threshold=None,
    )


def market_regime_definition() -> MarketRegimeDefinition:
    params_hash = stable_hash({})
    allowed_domains = normalize_domain_codes(["trend", "momentum", "volatility"])
    required_domains = normalize_domain_codes(["trend", "momentum", "volatility"])
    allowed_regimes = normalize_regime_codes(["trend_up", "mixed"])
    definition_hash = market_regime_definition_hash(
        definition_code="test_regime_definition",
        algorithm_name="test_market_regime",
        algorithm_version="1.0.0",
        input_schema_version="1.0",
        output_schema_version="1.0",
        params_hash=params_hash,
        allowed_domain_codes=allowed_domains,
        required_domain_codes=required_domains,
        allowed_regime_codes=allowed_regimes,
    )
    return MarketRegimeDefinition.objects.create(
        definition_code="test_regime_definition",
        algorithm_name="test_market_regime",
        algorithm_version="1.0.0",
        input_schema_version="1.0",
        output_schema_version="1.0",
        params={},
        params_hash=params_hash,
        definition_hash=definition_hash,
        allowed_domain_codes=list(allowed_domains),
        required_domain_codes=list(required_domains),
        allowed_regime_codes=list(allowed_regimes),
        status=DefinitionLifecycleStatus.ACTIVE,
        enabled=True,
    )


def build_fixture(
    *,
    include_market_regime_definition: bool = True,
    missing_domain_value: str | None = None,
) -> tuple[DomainSignalSet, StrategyAnalysisRelease, MarketRegimeDefinition | None]:
    snapshot = market_snapshot()
    release = StrategyAnalysisRelease.objects.create(release_code="regime-release")
    domain_definitions = {code: domain_definition(code) for code in ("trend", "momentum", "volatility")}
    for code, definition in domain_definitions.items():
        atomic_code = f"atomic_{code}"
        payload = {
            "allowed_atomic_signal_codes": [atomic_code],
            "required_atomic_signal_codes": [atomic_code],
        }
        StrategyAnalysisReleaseItem.objects.create(
            release=release,
            component_type=ReleaseItemComponentType.DOMAIN_SIGNAL_DEFINITION,
            component_object_id=definition.id,
            component_code=definition.domain_code,
            definition_hash=definition.definition_hash,
            algorithm_name=definition.algorithm_name,
            algorithm_version=definition.algorithm_version,
            params_hash=definition.params_hash,
            dependency_hash=domain_atomic_membership_hash(payload),
            payload_summary=payload,
        )
    regime_definition = market_regime_definition() if include_market_regime_definition else None
    if regime_definition is not None:
        payload = {
            "allowed_domain_codes": regime_definition.allowed_domain_codes,
            "required_domain_codes": regime_definition.required_domain_codes,
            "allowed_regime_codes": regime_definition.allowed_regime_codes,
        }
        StrategyAnalysisReleaseItem.objects.create(
            release=release,
            component_type=ReleaseItemComponentType.MARKET_REGIME_DEFINITION,
            component_object_id=regime_definition.id,
            component_code=regime_definition.definition_code,
            definition_hash=regime_definition.definition_hash,
            algorithm_name=regime_definition.algorithm_name,
            algorithm_version=regime_definition.algorithm_version,
            params_hash=regime_definition.params_hash,
            dependency_hash=market_regime_domain_membership_hash(payload),
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
        reason="MarketRegime fixture",
        operator_id="tester",
        trace_id="trace",
        trigger_source="test",
    )
    StrategyAnalysisReleaseActivation.objects.create(
        release=release,
        release_hash=release.release_hash,
        action=ReleaseAction.ACTIVATE,
        operator_id="tester",
        reason="MarketRegime fixture",
        trace_id="trace",
        trigger_source="test",
    )
    feature_set = FeatureSet.objects.create(
        feature_set_key=stable_hash({"feature_set": "regime"}),
        business_request_key="regime-feature-set",
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
        atomic_signal_set_key=stable_hash({"atomic_set": "regime"}),
        business_request_key="regime-atomic-set",
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
        definition_set_hash=stable_hash({"atomic": []}),
        status=AnalysisObjectStatus.CREATED,
        is_usable=True,
        allows_domain_signal=True,
        selected_definition_count=0,
        computed_count=0,
        valid_count=0,
        invalid_count=0,
        failed_count=0,
        required_failed_count=0,
        failure_ratio=Decimal("0"),
        failure_block_ratio=Decimal("0.3"),
        trace_id="trace",
        trigger_source="test",
        finished_at_utc=utc(8),
    )
    domain_set = DomainSignalSet.objects.create(
        domain_signal_set_key=stable_hash({"domain_set": "regime"}),
        business_request_key="regime-domain-set",
        atomic_signal_set=atomic_set,
        atomic_signal_set_key=atomic_set.atomic_signal_set_key,
        strategy_analysis_release=release,
        release_hash=release.release_hash,
        market_snapshot=snapshot,
        exchange=snapshot.exchange,
        market_type=snapshot.market_type,
        symbol=snapshot.symbol,
        analysis_close_time_utc=snapshot.analysis_close_time_utc,
        domain_schema_version="1.0",
        definition_set_hash=stable_hash({"domain": list(domain_definitions)}),
        status=AnalysisObjectStatus.CREATED,
        is_usable=True,
        allows_market_regime=True,
        selected_definition_count=3,
        computed_count=3,
        valid_count=3,
        invalid_count=0,
        required_failed_count=0,
        trace_id="trace",
        trigger_source="test",
        finished_at_utc=utc(8),
    )
    for code, definition in domain_definitions.items():
        if code == missing_domain_value:
            continue
        DomainSignalValue.objects.create(
            domain_signal_set=domain_set,
            domain_signal_definition=definition,
            domain_code=code,
            output_mode=definition.output_mode,
            direction=AtomicSignalDirection.BULLISH,
            state_code="",
            strength=Decimal("0.8"),
            coverage_ratio=Decimal("1"),
            agreement_ratio=None,
            status=AnalysisObjectStatus.CREATED,
            is_valid=True,
            definition_status=definition.status,
            definition_enabled=definition.enabled,
            algorithm_name=definition.algorithm_name,
            algorithm_version=definition.algorithm_version,
            params_hash=definition.params_hash,
            definition_hash=definition.definition_hash,
            used_atomic_signal_codes=[f"atomic_{code}"],
            used_atomic_signal_value_ids=[1],
            evidence_items=[{"domain_code": code}],
            evidence_text_zh="测试领域事实",
        )
    return domain_set, release, regime_definition


def run_service(
    domain_set: DomainSignalSet,
    release: StrategyAnalysisRelease,
    definition: MarketRegimeDefinition | None,
    *,
    key: str = "regime-build",
    dry_run: bool = False,
    custom_registry: CalculatorRegistry | None = None,
):
    return classify_for_strategy_routing(
        domain_signal_set_id=domain_set.id,
        strategy_analysis_release_id=release.id,
        strategy_analysis_release_hash=release.release_hash,
        expected_market_regime_definition_hash=definition.definition_hash if definition else "",
        business_request_key=key,
        trace_id="trace",
        trigger_source="test",
        dry_run=dry_run,
        registry=custom_registry or registry(),
    )


@pytest.mark.django_db
def test_market_regime_creates_snapshot_from_domain_signal_set() -> None:
    domain_set, release, definition = build_fixture()

    result = run_service(domain_set, release, definition)

    assert result.status == "succeeded"
    snapshot = MarketRegimeSnapshot.objects.get()
    assert snapshot.regime_code == "trend_up"
    assert snapshot.is_usable is True
    assert snapshot.allows_strategy_routing is True
    assert snapshot.domain_signal_set_id == domain_set.id
    assert sorted(snapshot.used_domain_signal_codes) == ["momentum", "trend", "volatility"]
    assert {item["evidence_type"] for item in snapshot.evidence_items} == {
        "domain_signal_value",
        "market_regime_classification",
        "calculator_output",
    }
    assert AlertEvent.objects.count() == 0


@pytest.mark.django_db
def test_market_regime_is_idempotent_by_business_request_key() -> None:
    domain_set, release, definition = build_fixture()

    first = run_service(domain_set, release, definition)
    second = run_service(domain_set, release, definition)

    assert first.status == "succeeded"
    assert second.status == "succeeded"
    assert MarketRegimeSnapshot.objects.count() == 1


@pytest.mark.django_db
def test_market_regime_blocks_when_business_request_key_points_to_another_input() -> None:
    domain_set, release, definition = build_fixture()
    first = run_service(domain_set, release, definition)

    conflict = classify_for_strategy_routing(
        domain_signal_set_id=domain_set.id + 999,
        strategy_analysis_release_id=release.id,
        strategy_analysis_release_hash=release.release_hash,
        expected_market_regime_definition_hash=definition.definition_hash,
        business_request_key="regime-build",
        trace_id="trace",
        trigger_source="test",
        registry=registry(),
    )

    assert first.status == "succeeded"
    assert conflict.status == "blocked"
    assert conflict.reason_code == "market_regime_idempotency_conflict"
    assert MarketRegimeSnapshot.objects.count() == 1
    assert AlertEvent.objects.filter(reason_code="market_regime_idempotency_conflict").exists()


@pytest.mark.django_db
def test_market_regime_blocks_without_definition_in_release() -> None:
    domain_set, release, definition = build_fixture(include_market_regime_definition=False)

    result = run_service(domain_set, release, definition)

    assert result.status == "blocked"
    assert result.reason_code == "market_regime_definition_unavailable"
    assert MarketRegimeSnapshot.objects.count() == 0
    assert AlertEvent.objects.filter(event_type="market_regime_blocked").exists()


@pytest.mark.django_db
def test_market_regime_blocks_when_required_domain_value_missing() -> None:
    domain_set, release, definition = build_fixture(missing_domain_value="volatility")

    result = run_service(domain_set, release, definition)

    assert result.status == "blocked"
    assert result.reason_code == "market_regime_required_domain_missing"
    assert MarketRegimeSnapshot.objects.count() == 0


@pytest.mark.django_db
def test_market_regime_blocks_when_calculator_is_not_registered() -> None:
    domain_set, release, definition = build_fixture()

    result = run_service(domain_set, release, definition, custom_registry=registry(empty=True))

    assert result.status == "blocked"
    assert result.reason_code == "market_regime_calculator_missing"
    assert MarketRegimeSnapshot.objects.count() == 0


@pytest.mark.django_db
def test_market_regime_dry_run_does_not_write_snapshot_or_alert() -> None:
    domain_set, release, definition = build_fixture()

    result = run_service(domain_set, release, definition, key="regime-dry-run", dry_run=True)

    assert result.status == "succeeded"
    assert result.data["persisted"] is False
    assert MarketRegimeSnapshot.objects.count() == 0
    assert AlertEvent.objects.count() == 0


@pytest.mark.django_db
def test_market_regime_dry_run_never_reuses_formal_snapshot() -> None:
    domain_set, release, definition = build_fixture()
    formal = run_service(domain_set, release, definition)

    dry_run = run_service(domain_set, release, definition, dry_run=True)

    assert formal.status == "succeeded"
    assert dry_run.status == "succeeded"
    assert dry_run.data["persisted"] is False
    assert dry_run.data["allows_strategy_routing"] is False
    assert MarketRegimeSnapshot.objects.count() == 1


@pytest.mark.django_db
def test_market_regime_blocks_dry_run_when_calculator_does_not_support_it() -> None:
    domain_set, release, definition = build_fixture()

    result = run_service(
        domain_set,
        release,
        definition,
        key="regime-dry-run-unsupported",
        dry_run=True,
        custom_registry=registry(supports_dry_run=False),
    )

    assert result.status == "blocked"
    assert result.reason_code == "market_regime_calculator_dry_run_unsupported"
    assert MarketRegimeSnapshot.objects.count() == 0
    assert AlertEvent.objects.count() == 0


@pytest.mark.django_db
def test_market_regime_invalid_calculator_output_persists_failed_snapshot() -> None:
    domain_set, release, definition = build_fixture()

    result = run_service(
        domain_set,
        release,
        definition,
        key="regime-invalid-output",
        custom_registry=registry(invalid_code=True),
    )

    assert result.status == "failed"
    snapshot = MarketRegimeSnapshot.objects.get()
    assert snapshot.status == AnalysisObjectStatus.FAILED
    assert snapshot.allows_strategy_routing is False
    assert snapshot.error_code == "market_regime_output_invalid"
    assert AlertEvent.objects.filter(event_type="market_regime_failed").exists()


@pytest.mark.django_db
def test_market_regime_unexpected_calculator_error_is_persisted_as_failed() -> None:
    domain_set, release, definition = build_fixture()

    result = run_service(
        domain_set,
        release,
        definition,
        key="regime-unexpected-error",
        custom_registry=registry(unexpected_error=True),
    )

    assert result.status == "failed"
    snapshot = MarketRegimeSnapshot.objects.get()
    assert snapshot.error_code == "market_regime_calculator_unexpected_error"
    assert snapshot.allows_strategy_routing is False
    assert AlertEvent.objects.filter(reason_code="market_regime_calculator_unexpected_error").exists()


@pytest.mark.django_db
def test_market_regime_empty_calculator_evidence_is_rejected() -> None:
    domain_set, release, definition = build_fixture()

    result = run_service(
        domain_set,
        release,
        definition,
        key="regime-empty-evidence",
        custom_registry=registry(empty_evidence=True),
    )

    assert result.status == "failed"
    snapshot = MarketRegimeSnapshot.objects.get()
    assert snapshot.error_code == "market_regime_output_invalid"
    assert snapshot.allows_strategy_routing is False


@pytest.mark.django_db
def test_market_regime_known_database_data_error_is_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    domain_set, release, definition = build_fixture()

    def raise_data_error(**_kwargs):
        raise DataError("invalid persisted value")

    monkeypatch.setattr(market_regime_service, "_persist_snapshot", raise_data_error)

    result = run_service(domain_set, release, definition, key="regime-data-error")

    assert result.status == "failed"
    assert result.reason_code == "market_regime_persist_failed"
    assert MarketRegimeSnapshot.objects.count() == 0
    assert AlertEvent.objects.filter(reason_code="market_regime_persist_failed").exists()


@pytest.mark.parametrize(
    ("normalizer", "values"),
    [
        (normalize_domain_codes, ["trend", "trend"]),
        (normalize_domain_codes, ["trend", "liquidity"]),
        (normalize_regime_codes, ["trend_up", "trend_up"]),
    ],
)
def test_market_regime_definition_codes_reject_duplicates_and_non_formal_domains(normalizer, values) -> None:
    with pytest.raises(ValueError):
        normalizer(values)
