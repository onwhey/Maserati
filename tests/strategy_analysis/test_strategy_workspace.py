from __future__ import annotations

import pytest

from apps.foundation.results import ResultStatus
from apps.strategy_analysis.models import (
    AtomicSignalDefinition,
    AtomicSignalDirection,
    AtomicSignalOutputType,
    DefinitionLifecycleStatus,
    FeatureDefinition,
    ReleaseItemComponentType,
    StrategyAnalysisReleaseItem,
    StrategyAnalysisWorkspaceItem,
)
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
