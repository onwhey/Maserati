from __future__ import annotations

import pytest

from apps.foundation.results import ResultStatus
from apps.strategy_analysis.models import (
    AtomicSignalDefinition,
    AtomicSignalDirection,
    AtomicSignalOutputType,
    DefinitionLifecycleStatus,
    DomainSignalDefinition,
    DomainSignalOutputMode,
    FeatureDefinition,
    MarketRegimeDefinition,
    ReleaseItemComponentType,
    StrategyAnalysisReleaseItem,
    StrategyAnalysisWorkspaceItem,
)
from apps.strategy_analysis.definition_hashes import domain_signal_definition_hash, normalize_atomic_signal_codes
from apps.strategy_analysis.services.workspace import generate_release_from_workspace, upsert_workspace_item
from apps.strategy_calculator.utils import stable_hash


pytestmark = pytest.mark.django_db


def create_feature(code: str) -> FeatureDefinition:
    return FeatureDefinition.objects.create(
        feature_code=code,
        definition_version="1.0.0",
        display_name=code,
        definition_hash=stable_hash({"feature": code}),
        algorithm_name="fake_feature",
        algorithm_version="1.0.0",
        params={},
        params_hash=stable_hash({}),
        value_type="decimal",
        input_timeframes=["4h"],
        output_schema_version="1.0",
    )


def create_atomic(code: str, *, feature_codes: list[str]) -> AtomicSignalDefinition:
    return AtomicSignalDefinition.objects.create(
        signal_code=code,
        display_name=code,
        category="test",
        default_direction=AtomicSignalDirection.BULLISH,
        algorithm_name="fake_atomic",
        algorithm_version="1.0.0",
        params={},
        params_hash=stable_hash({}),
        definition_hash=stable_hash({"atomic": code, "features": feature_codes}),
        status=DefinitionLifecycleStatus.ACTIVE,
        enabled=True,
        is_required=False,
        depends_on_feature_codes=feature_codes,
        output_type=AtomicSignalOutputType.BOOLEAN,
    )


def create_domain(
    code: str,
    *,
    atomic_codes: list[str],
    required_atomic_codes: list[str] | None = None,
) -> DomainSignalDefinition:
    params: dict[str, object] = {}
    params_hash = stable_hash(params)
    allowed_codes = normalize_atomic_signal_codes(atomic_codes)
    raw_required_codes = atomic_codes if required_atomic_codes is None else required_atomic_codes
    required_codes = normalize_atomic_signal_codes(raw_required_codes, allow_empty=True)
    definition_hash = domain_signal_definition_hash(
        domain_code=code,
        output_mode=DomainSignalOutputMode.DIRECTIONAL,
        algorithm_name="fake_domain",
        algorithm_version="1.0.0",
        params_hash=params_hash,
        is_required=True,
        allowed_atomic_signal_codes=allowed_codes,
        required_atomic_signal_codes=required_codes,
        minimum_coverage_ratio="1",
        agreement_threshold=None,
    )
    return DomainSignalDefinition.objects.create(
        domain_code=code,
        display_name=code,
        output_mode=DomainSignalOutputMode.DIRECTIONAL,
        algorithm_name="fake_domain",
        algorithm_version="1.0.0",
        params=params,
        params_hash=params_hash,
        definition_hash=definition_hash,
        status=DefinitionLifecycleStatus.ACTIVE,
        enabled=True,
        is_required=True,
        allowed_atomic_signal_codes=list(allowed_codes),
        required_atomic_signal_codes=list(required_codes),
        minimum_coverage_ratio="1",
        agreement_threshold=None,
    )


def create_market_regime_definition(code: str, *, algorithm_version: str) -> MarketRegimeDefinition:
    return MarketRegimeDefinition.objects.create(
        definition_code=code,
        display_name=code,
        description=f"{code} definition",
        algorithm_name="fake_market_regime",
        algorithm_version=algorithm_version,
        input_schema_version="1.0",
        output_schema_version="1.0",
        params={},
        params_hash=stable_hash({"params": code}),
        definition_hash=stable_hash({"market_regime": code, "algorithm_version": algorithm_version}),
        allowed_domain_codes=["trend"],
        required_domain_codes=["trend"],
        allowed_regime_codes=["bullish_trend_continuation"],
        status=DefinitionLifecycleStatus.ACTIVE,
        enabled=True,
    )


def test_workspace_generates_release_with_features_inferred_from_included_atomics() -> None:
    feature = create_feature("feature_shared")
    create_feature("feature_unused")
    atomic = create_atomic("atomic_uses_feature", feature_codes=["feature_shared"])

    feature_result = upsert_workspace_item(
        component_type=ReleaseItemComponentType.FEATURE_DEFINITION,
        component_object_id=feature.id,
        is_included=True,
        operator_id="tester",
        reason="选择特征版本",
        trace_id="trace-workspace-feature",
        trigger_source="test",
    )
    atomic_result = upsert_workspace_item(
        component_type=ReleaseItemComponentType.ATOMIC_SIGNAL_DEFINITION,
        component_object_id=atomic.id,
        is_included=True,
        operator_id="tester",
        reason="纳入原子信号",
        trace_id="trace-workspace-atomic",
        trigger_source="test",
    )

    assert feature_result.status == ResultStatus.SUCCEEDED
    assert atomic_result.status == ResultStatus.SUCCEEDED
    feature_item = StrategyAnalysisWorkspaceItem.objects.get(component_code="feature_shared")
    assert feature_item.inclusion_managed is False
    assert feature_item.is_included is False

    generate_result = generate_release_from_workspace(
        release_code="workspace-release-1",
        display_name="Workspace Release 1",
        description="generated from workspace",
        operator_id="tester",
        reason="生成发布包",
        trace_id="trace-workspace-generate",
        trigger_source="test",
    )

    assert generate_result.status == ResultStatus.SUCCEEDED
    release_id = generate_result.data["release_id"]
    items = StrategyAnalysisReleaseItem.objects.filter(release_id=release_id).order_by("sort_order")
    assert [(item.component_type, item.component_code) for item in items] == [
        (ReleaseItemComponentType.FEATURE_DEFINITION, "feature_shared"),
        (ReleaseItemComponentType.ATOMIC_SIGNAL_DEFINITION, "atomic_uses_feature"),
    ]


def test_workspace_market_regime_selection_replaces_previous_definition() -> None:
    first = create_market_regime_definition("context_structure_regime_v1", algorithm_version="v1")
    second = create_market_regime_definition("context_structure_regime_v2", algorithm_version="v2")

    first_result = upsert_workspace_item(
        component_type=ReleaseItemComponentType.MARKET_REGIME_DEFINITION,
        component_object_id=first.id,
        is_included=True,
        operator_id="tester",
        reason="select market regime v1",
        trace_id="trace-workspace-market-regime-v1",
        trigger_source="test",
    )
    second_result = upsert_workspace_item(
        component_type=ReleaseItemComponentType.MARKET_REGIME_DEFINITION,
        component_object_id=second.id,
        is_included=True,
        operator_id="tester",
        reason="select market regime v2",
        trace_id="trace-workspace-market-regime-v2",
        trigger_source="test",
    )

    assert first_result.status == ResultStatus.SUCCEEDED
    assert second_result.status == ResultStatus.SUCCEEDED
    items = StrategyAnalysisWorkspaceItem.objects.filter(
        component_type=ReleaseItemComponentType.MARKET_REGIME_DEFINITION
    )
    assert list(items.values_list("component_code", "component_version", "is_included")) == [
        ("context_structure_regime_v2", "v2", True)
    ]


def test_workspace_blocks_release_when_included_atomic_has_no_selected_feature_version() -> None:
    atomic = create_atomic("atomic_missing_feature", feature_codes=["feature_missing"])
    upsert_workspace_item(
        component_type=ReleaseItemComponentType.ATOMIC_SIGNAL_DEFINITION,
        component_object_id=atomic.id,
        is_included=True,
        operator_id="tester",
        reason="纳入原子信号",
        trace_id="trace-workspace-atomic-missing",
        trigger_source="test",
    )

    generate_result = generate_release_from_workspace(
        release_code="workspace-release-missing",
        display_name="Workspace Release Missing",
        description="generated from incomplete workspace",
        operator_id="tester",
        reason="生成发布包",
        trace_id="trace-workspace-generate-missing",
        trigger_source="test",
    )

    assert generate_result.status == ResultStatus.BLOCKED
    assert generate_result.reason_code == "strategy_workspace_dependency_invalid"
    assert "feature_missing" in generate_result.data["errors"][0]


def test_workspace_generates_release_with_atomics_inferred_from_included_domains() -> None:
    kept_feature = create_feature("feature_kept")
    old_feature = create_feature("feature_old_structure")
    kept_atomic = create_atomic("structure_pivot_support_holds", feature_codes=["feature_kept"])
    old_atomic = create_atomic("structure_major_support_holds", feature_codes=["feature_old_structure"])
    domain = create_domain("structure", atomic_codes=["structure_pivot_support_holds"])

    for component_type, component_id in (
        (ReleaseItemComponentType.FEATURE_DEFINITION, kept_feature.id),
        (ReleaseItemComponentType.FEATURE_DEFINITION, old_feature.id),
        (ReleaseItemComponentType.ATOMIC_SIGNAL_DEFINITION, kept_atomic.id),
        (ReleaseItemComponentType.ATOMIC_SIGNAL_DEFINITION, old_atomic.id),
        (ReleaseItemComponentType.DOMAIN_SIGNAL_DEFINITION, domain.id),
    ):
        result = upsert_workspace_item(
            component_type=component_type,
            component_object_id=component_id,
            is_included=True,
            operator_id="tester",
            reason="选择组件版本",
            trace_id="trace-workspace-domain-infer",
            trigger_source="test",
        )
        assert result.status == ResultStatus.SUCCEEDED

    generate_result = generate_release_from_workspace(
        release_code="workspace-release-domain-infer",
        display_name="Workspace Release Domain Infer",
        description="generated from domain-driven workspace",
        operator_id="tester",
        reason="生成发布包",
        trace_id="trace-workspace-domain-infer-generate",
        trigger_source="test",
    )

    assert generate_result.status == ResultStatus.SUCCEEDED
    release_id = generate_result.data["release_id"]
    items = StrategyAnalysisReleaseItem.objects.filter(release_id=release_id).order_by("sort_order")
    assert [(item.component_type, item.component_code) for item in items] == [
        (ReleaseItemComponentType.FEATURE_DEFINITION, "feature_kept"),
        (ReleaseItemComponentType.ATOMIC_SIGNAL_DEFINITION, "structure_pivot_support_holds"),
        (ReleaseItemComponentType.DOMAIN_SIGNAL_DEFINITION, "structure"),
    ]


def test_workspace_blocks_release_when_domain_required_atomic_version_is_not_selected() -> None:
    domain = create_domain("structure", atomic_codes=["structure_pivot_support_holds"])
    result = upsert_workspace_item(
        component_type=ReleaseItemComponentType.DOMAIN_SIGNAL_DEFINITION,
        component_object_id=domain.id,
        is_included=True,
        operator_id="tester",
        reason="选择领域版本",
        trace_id="trace-workspace-domain-missing-atomic",
        trigger_source="test",
    )
    assert result.status == ResultStatus.SUCCEEDED

    generate_result = generate_release_from_workspace(
        release_code="workspace-release-domain-missing-atomic",
        display_name="Workspace Release Domain Missing Atomic",
        description="generated from incomplete domain workspace",
        operator_id="tester",
        reason="生成发布包",
        trace_id="trace-workspace-domain-missing-atomic-generate",
        trigger_source="test",
    )

    assert generate_result.status == ResultStatus.BLOCKED
    assert generate_result.reason_code == "strategy_workspace_dependency_invalid"
    assert "structure_pivot_support_holds" in generate_result.data["errors"][0]


def test_workspace_does_not_block_when_domain_optional_atomic_version_is_not_selected() -> None:
    domain = create_domain(
        "structure",
        atomic_codes=["structure_historical_major_reference_1d_720"],
        required_atomic_codes=[],
    )
    result = upsert_workspace_item(
        component_type=ReleaseItemComponentType.DOMAIN_SIGNAL_DEFINITION,
        component_object_id=domain.id,
        is_included=True,
        operator_id="tester",
        reason="选择领域版本",
        trace_id="trace-workspace-domain-optional-atomic",
        trigger_source="test",
    )
    assert result.status == ResultStatus.SUCCEEDED

    generate_result = generate_release_from_workspace(
        release_code="workspace-release-domain-optional-atomic",
        display_name="Workspace Release Domain Optional Atomic",
        description="generated from optional domain workspace",
        operator_id="tester",
        reason="生成发布包",
        trace_id="trace-workspace-domain-optional-atomic-generate",
        trigger_source="test",
    )

    assert generate_result.status == ResultStatus.SUCCEEDED
    release_id = generate_result.data["release_id"]
    items = StrategyAnalysisReleaseItem.objects.filter(release_id=release_id).order_by("sort_order")
    assert [(item.component_type, item.component_code) for item in items] == [
        (ReleaseItemComponentType.DOMAIN_SIGNAL_DEFINITION, "structure"),
    ]
