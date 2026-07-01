from __future__ import annotations

import json
from io import StringIO
from typing import Any

import pytest
from django.core.management import call_command

from apps.foundation.results import ResultStatus, ServiceResult
from apps.strategy_analysis.models import (
    FeatureDefinition,
    ReleaseItemComponentType,
    StrategyAnalysisRelease,
    StrategyAnalysisReleaseItem,
)
from apps.strategy_analysis.services.release import calculate_definition_set_hash
from apps.strategy_calculator.utils import stable_hash
from tests.strategy_analysis.test_strategy_signal import selected_fixture
from tests.strategy_analysis.test_strategy_signal_quality import create_quality_rule_set


@pytest.mark.django_db
def test_build_feature_layer_command_infers_feature_definition_set_hash(monkeypatch) -> None:
    feature = FeatureDefinition.objects.create(
        feature_code="command_test_feature",
        definition_version="1.0.0",
        definition_hash=stable_hash({"feature": "command_test_feature"}),
        algorithm_name="kline_price_features",
        algorithm_version="1.0.0",
        params={"operation": "latest_close", "timeframe": "4h"},
        params_hash=stable_hash({"operation": "latest_close", "timeframe": "4h"}),
        value_type="decimal",
        input_timeframes=["4h"],
        output_schema_version="1.0",
    )
    release = StrategyAnalysisRelease.objects.create(
        release_code="command_feature_release",
        release_hash="command-feature-release-hash",
    )
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
    expected_hash = calculate_definition_set_hash(
        release.items.filter(component_type=ReleaseItemComponentType.FEATURE_DEFINITION)
    )
    captured: dict[str, Any] = {}

    def fake_build_feature_set(**kwargs):
        captured.update(kwargs)
        return ServiceResult(
            ResultStatus.SUCCEEDED,
            "feature_set_created",
            "ok",
            kwargs["trace_id"],
            kwargs["trigger_source"],
            {"feature_set_id": 123},
        )

    monkeypatch.setattr(
        "apps.strategy_analysis.management.commands.build_feature_layer.build_feature_set",
        fake_build_feature_set,
    )

    out = StringIO()
    call_command(
        "build_feature_layer",
        market_snapshot_id=1,
        strategy_analysis_release_id=release.id,
        strategy_analysis_release_hash=release.release_hash,
        business_request_key="feature-command",
        trace_id="trace-feature-command",
        stdout=out,
    )

    payload = json.loads(out.getvalue())
    assert payload["reason_code"] == "feature_set_created"
    assert captured["expected_definition_set_hash"] == expected_hash
    assert captured["market_snapshot_id"] == 1
    assert captured["strategy_analysis_release_id"] == release.id


@pytest.mark.django_db
def test_generate_strategy_signal_command_infers_selected_strategy_definition_hash(monkeypatch) -> None:
    fixture = selected_fixture()
    captured: dict[str, Any] = {}

    def fake_generate_strategy_signal(**kwargs):
        captured.update(kwargs)
        return ServiceResult(
            ResultStatus.SUCCEEDED,
            "strategy_signal_created",
            "ok",
            kwargs["trace_id"],
            kwargs["trigger_source"],
            {"strategy_signal_id": 456},
        )

    monkeypatch.setattr(
        "apps.strategy_analysis.management.commands.generate_strategy_signal.generate_strategy_signal",
        fake_generate_strategy_signal,
    )

    out = StringIO()
    call_command(
        "generate_strategy_signal",
        strategy_route_decision_id=fixture["decision"].id,
        strategy_analysis_release_id=fixture["release"].id,
        strategy_analysis_release_hash=fixture["release"].release_hash,
        business_request_key="strategy-signal-command",
        trace_id="trace-signal-command",
        stdout=out,
    )

    payload = json.loads(out.getvalue())
    assert payload["reason_code"] == "strategy_signal_created"
    assert captured["expected_strategy_definition_hash"] == fixture["primary"].definition_hash
    assert captured["strategy_route_decision_id"] == fixture["decision"].id


@pytest.mark.django_db
def test_validate_strategy_signal_command_infers_single_quality_rule_set_hash(monkeypatch) -> None:
    rule_set = create_quality_rule_set()
    release = StrategyAnalysisRelease.objects.create(
        release_code="command_quality_release",
        release_hash="command-quality-release-hash",
    )
    StrategyAnalysisReleaseItem.objects.create(
        release=release,
        component_type=ReleaseItemComponentType.STRATEGY_SIGNAL_QUALITY_RULE_SET,
        component_object_id=rule_set.id,
        component_code=rule_set.rule_set_code,
        definition_hash=rule_set.rule_set_hash,
        params_hash=rule_set.params_hash,
    )
    captured: dict[str, Any] = {}

    def fake_validate_strategy_signal(**kwargs):
        captured.update(kwargs)
        return ServiceResult(
            ResultStatus.SUCCEEDED,
            "strategy_signal_quality_created",
            "ok",
            kwargs["trace_id"],
            kwargs["trigger_source"],
            {"quality_result_id": 789},
        )

    monkeypatch.setattr(
        "apps.strategy_analysis.management.commands.validate_strategy_signal.validate_strategy_signal",
        fake_validate_strategy_signal,
    )

    out = StringIO()
    call_command(
        "validate_strategy_signal",
        strategy_signal_id=1,
        strategy_analysis_release_id=release.id,
        strategy_analysis_release_hash=release.release_hash,
        business_request_key="quality-command",
        trace_id="trace-quality-command",
        stdout=out,
    )

    payload = json.loads(out.getvalue())
    assert payload["reason_code"] == "strategy_signal_quality_created"
    assert captured["expected_quality_rule_set_hash"] == rule_set.rule_set_hash
    assert captured["strategy_signal_id"] == 1
