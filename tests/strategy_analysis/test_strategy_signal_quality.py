from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest

from apps.alerts.models import AlertEvent
from apps.strategy_analysis.definition_hashes import strategy_signal_quality_rule_set_hash
from apps.strategy_analysis.models import (
    AnalysisObjectStatus,
    DomainSignalSet,
    MarketRegimeSnapshot,
    ReleaseItemComponentType,
    StrategyAnalysisRelease,
    StrategyAnalysisReleaseActivation,
    StrategyAnalysisReleaseApproval,
    StrategyAnalysisReleaseItem,
    StrategyRouteDecision,
    StrategySignal,
    StrategySignalQualityIssue,
    StrategySignalQualityRuleSet,
    StrategySignalQualityStatus,
    StrategySignalQualityValidationMode,
)
from apps.strategy_analysis.services.release import calculate_release_hash
from apps.strategy_analysis.services.strategy_signal_quality import validate_strategy_signal
from apps.strategy_calculator.utils import stable_hash
from tests.strategy_analysis.test_strategy_routing import build_routing_fixture, run_route
from tests.strategy_analysis.test_strategy_signal import run_signal, signal_registry


def create_quality_rule_set(
    *,
    max_staleness_seconds: int = 0,
    warning_blocks_decision: bool = False,
    fail_alert_enabled: bool = True,
    warning_alert_enabled: bool = False,
) -> StrategySignalQualityRuleSet:
    params: dict[str, Any] = {}
    params_hash = stable_hash(params)
    rule_set_hash = strategy_signal_quality_rule_set_hash(
        rule_set_code="default_strategy_signal_quality",
        rule_set_version="1.0.0",
        quality_schema_version="1.0",
        max_staleness_seconds=max_staleness_seconds,
        warning_blocks_decision=warning_blocks_decision,
        fail_alert_enabled=fail_alert_enabled,
        warning_alert_enabled=warning_alert_enabled,
        consecutive_failure_threshold=0,
        params_hash=params_hash,
    )
    return StrategySignalQualityRuleSet.objects.create(
        rule_set_code="default_strategy_signal_quality",
        rule_set_version="1.0.0",
        display_name="默认策略信号质量规则",
        quality_schema_version="1.0",
        max_staleness_seconds=max_staleness_seconds,
        warning_blocks_decision=warning_blocks_decision,
        fail_alert_enabled=fail_alert_enabled,
        warning_alert_enabled=warning_alert_enabled,
        consecutive_failure_threshold=0,
        params=params,
        params_hash=params_hash,
        rule_set_hash=rule_set_hash,
        status="active",
        enabled=True,
    )


def attach_quality_rule_set(fixture: dict[str, Any], rule_set: StrategySignalQualityRuleSet) -> None:
    release: StrategyAnalysisRelease = fixture["release"]
    StrategyAnalysisReleaseItem.objects.create(
        release=release,
        component_type=ReleaseItemComponentType.STRATEGY_SIGNAL_QUALITY_RULE_SET,
        component_object_id=rule_set.id,
        component_code=rule_set.rule_set_code,
        definition_hash=rule_set.rule_set_hash,
        params_hash=rule_set.params_hash,
        payload_summary={
            "quality_schema_version": rule_set.quality_schema_version,
            "max_staleness_seconds": rule_set.max_staleness_seconds,
            "warning_blocks_decision": rule_set.warning_blocks_decision,
        },
        sort_order=900,
    )
    release.release_hash = calculate_release_hash(release)
    release.save(update_fields=["release_hash", "updated_at_utc"])
    StrategyAnalysisReleaseApproval.objects.filter(release=release).update(release_hash=release.release_hash)
    StrategyAnalysisReleaseActivation.objects.filter(release=release).update(release_hash=release.release_hash)
    snapshot = MarketRegimeSnapshot.objects.get(id=fixture["snapshot_id"])
    DomainSignalSet.objects.filter(id=snapshot.domain_signal_set_id).update(release_hash=release.release_hash)
    MarketRegimeSnapshot.objects.filter(id=snapshot.id).update(release_hash=release.release_hash)
    fixture["release"].refresh_from_db()


def build_quality_fixture(
    *,
    max_staleness_seconds: int = 0,
    warning_blocks_decision: bool = False,
    fail_alert_enabled: bool = True,
    warning_alert_enabled: bool = False,
) -> tuple[dict[str, Any], StrategySignalQualityRuleSet, StrategySignal]:
    fixture = build_routing_fixture()
    rule_set = create_quality_rule_set(
        max_staleness_seconds=max_staleness_seconds,
        warning_blocks_decision=warning_blocks_decision,
        fail_alert_enabled=fail_alert_enabled,
        warning_alert_enabled=warning_alert_enabled,
    )
    attach_quality_rule_set(fixture, rule_set)
    route_result = run_route(fixture)
    assert route_result.status == "succeeded"
    fixture["decision"] = StrategyRouteDecision.objects.get(id=route_result.data["strategy_route_decision_id"])
    registry, _calculator = signal_registry()
    signal_result = run_signal(fixture, registry=registry)
    assert signal_result.status == "succeeded"
    signal = StrategySignal.objects.get(id=signal_result.data["strategy_signal_id"])
    return fixture, rule_set, signal


def run_quality(
    *,
    signal: StrategySignal,
    release: StrategyAnalysisRelease,
    rule_set: StrategySignalQualityRuleSet,
    key: str = "strategy-signal-quality",
    validation_mode: str = StrategySignalQualityValidationMode.LIVE,
    reference_time_utc=None,
    dry_run: bool = False,
):
    return validate_strategy_signal(
        strategy_signal_id=signal.id,
        strategy_analysis_release_id=release.id,
        strategy_analysis_release_hash=release.release_hash,
        expected_quality_rule_set_hash=rule_set.rule_set_hash,
        business_request_key=key,
        validation_mode=validation_mode,
        reference_time_utc=reference_time_utc,
        dry_run=dry_run,
        trace_id="trace",
        trigger_source="test",
    )


@pytest.mark.django_db
def test_strategy_signal_quality_passes_valid_strategy_signal() -> None:
    fixture, rule_set, signal = build_quality_fixture()

    result = run_quality(signal=signal, release=fixture["release"], rule_set=rule_set)

    assert result.status == "succeeded"
    assert result.data["quality_status"] == StrategySignalQualityStatus.PASSED
    assert result.data["allows_decision_snapshot"] is True
    assert result.data["is_usable"] is True
    assert StrategySignalQualityIssue.objects.count() == 0
    assert AlertEvent.objects.filter(source_module="StrategySignalQuality").count() == 0


@pytest.mark.django_db
def test_strategy_signal_quality_dry_run_does_not_persist_result_or_alert() -> None:
    fixture, rule_set, signal = build_quality_fixture()

    result = run_quality(signal=signal, release=fixture["release"], rule_set=rule_set, dry_run=True)

    assert result.status == "succeeded"
    assert result.data["persisted"] is False
    assert result.data["allows_decision_snapshot"] is False
    assert StrategySignal.objects.count() == 1
    assert StrategySignalQualityIssue.objects.count() == 0
    assert AlertEvent.objects.filter(source_module="StrategySignalQuality").count() == 0


@pytest.mark.django_db
def test_strategy_signal_quality_fails_when_aggregation_no_longer_matches_signal() -> None:
    fixture, rule_set, signal = build_quality_fixture()
    StrategySignal.objects.filter(id=signal.id).update(
        aggregation_snapshot={
            "final_direction": "bearish",
            "final_strength": "0.7",
            "final_confidence": "0.6",
        }
    )
    signal.refresh_from_db()

    result = run_quality(signal=signal, release=fixture["release"], rule_set=rule_set)

    assert result.status == "failed"
    assert result.data["quality_status"] == StrategySignalQualityStatus.FAILED
    assert result.data["allows_decision_snapshot"] is False
    assert StrategySignalQualityIssue.objects.filter(issue_code="strategy_signal_aggregation_mismatch").exists()
    alert = AlertEvent.objects.get(source_module="StrategySignalQuality", event_type="strategy_signal_quality_failed")
    assert "strategy_signal_aggregation_mismatch" in alert.payload_summary["failed_issue_codes"]
    assert alert.payload_summary["strategy_code"] == signal.strategy_code
    assert alert.payload_summary["quality_status"] == StrategySignalQualityStatus.FAILED


@pytest.mark.django_db
def test_strategy_signal_quality_warning_can_still_allow_decision_snapshot() -> None:
    fixture, rule_set, signal = build_quality_fixture(max_staleness_seconds=1)
    reference_time = signal.analysis_close_time_utc + timedelta(seconds=60)

    result = run_quality(
        signal=signal,
        release=fixture["release"],
        rule_set=rule_set,
        reference_time_utc=reference_time,
    )

    assert result.status == "succeeded"
    assert result.data["quality_status"] == StrategySignalQualityStatus.WARNING
    assert result.data["allows_decision_snapshot"] is True
    assert StrategySignalQualityIssue.objects.filter(issue_code="strategy_signal_stale").exists()
    assert AlertEvent.objects.filter(source_module="StrategySignalQuality").count() == 0


@pytest.mark.django_db
def test_strategy_signal_quality_warning_can_block_when_rule_set_requires_it() -> None:
    fixture, rule_set, signal = build_quality_fixture(max_staleness_seconds=1, warning_blocks_decision=True)
    reference_time = signal.analysis_close_time_utc + timedelta(seconds=60)

    result = run_quality(
        signal=signal,
        release=fixture["release"],
        rule_set=rule_set,
        reference_time_utc=reference_time,
    )

    assert result.status == "succeeded"
    assert result.data["quality_status"] == StrategySignalQualityStatus.WARNING
    assert result.data["allows_decision_snapshot"] is False
    assert result.data["is_usable"] is False


@pytest.mark.django_db
def test_strategy_signal_quality_is_idempotent_by_business_request_key() -> None:
    fixture, rule_set, signal = build_quality_fixture()

    first = run_quality(signal=signal, release=fixture["release"], rule_set=rule_set)
    second = run_quality(signal=signal, release=fixture["release"], rule_set=rule_set)

    assert first.status == "succeeded"
    assert second.status == "succeeded"
    assert first.data["quality_result_id"] == second.data["quality_result_id"]
    assert StrategySignalQualityIssue.objects.count() == 0


@pytest.mark.django_db
def test_strategy_signal_quality_blocks_business_request_key_conflict() -> None:
    fixture, rule_set, signal = build_quality_fixture()
    first = run_quality(signal=signal, release=fixture["release"], rule_set=rule_set)

    conflict = validate_strategy_signal(
        strategy_signal_id=signal.id + 999,
        strategy_analysis_release_id=fixture["release"].id,
        strategy_analysis_release_hash=fixture["release"].release_hash,
        expected_quality_rule_set_hash=rule_set.rule_set_hash,
        business_request_key="strategy-signal-quality",
        validation_mode=StrategySignalQualityValidationMode.LIVE,
        trace_id="trace",
        trigger_source="test",
    )

    assert first.status == "succeeded"
    assert conflict.status == "blocked"
    assert conflict.reason_code == "strategy_signal_quality_idempotency_conflict"


@pytest.mark.django_db
def test_strategy_signal_quality_replay_requires_explicit_reference_time() -> None:
    fixture, rule_set, signal = build_quality_fixture()

    result = run_quality(
        signal=signal,
        release=fixture["release"],
        rule_set=rule_set,
        validation_mode=StrategySignalQualityValidationMode.REPLAY,
    )

    assert result.status == "blocked"
    assert result.reason_code == "reference_time_required"
    assert StrategySignalQualityIssue.objects.count() == 0


@pytest.mark.django_db
def test_strategy_signal_quality_blocks_when_rule_set_hash_not_in_release() -> None:
    fixture, rule_set, signal = build_quality_fixture()

    result = validate_strategy_signal(
        strategy_signal_id=signal.id,
        strategy_analysis_release_id=fixture["release"].id,
        strategy_analysis_release_hash=fixture["release"].release_hash,
        expected_quality_rule_set_hash=stable_hash({"wrong": "quality"}),
        business_request_key="wrong-rule-set",
        validation_mode=StrategySignalQualityValidationMode.LIVE,
        trace_id="trace",
        trigger_source="test",
    )

    assert result.status == "blocked"
    assert result.reason_code == "strategy_signal_quality_rule_set_hash_mismatch"


@pytest.mark.django_db
def test_strategy_signal_quality_blocks_non_consumable_strategy_signal() -> None:
    fixture, rule_set, signal = build_quality_fixture()
    StrategySignal.objects.filter(id=signal.id).update(
        status=AnalysisObjectStatus.BLOCKED,
        is_usable=False,
        allows_strategy_signal_quality=False,
    )
    signal.refresh_from_db()

    result = run_quality(signal=signal, release=fixture["release"], rule_set=rule_set)

    assert result.status == "blocked"
    assert result.reason_code == "strategy_signal_not_consumable"
    assert StrategySignalQualityIssue.objects.count() == 0
    assert AlertEvent.objects.filter(source_module="StrategySignalQuality", event_type="strategy_signal_quality_blocked").exists()


@pytest.mark.django_db
def test_strategy_signal_quality_records_issue_for_invalid_used_ref_shape_instead_of_crashing() -> None:
    fixture, rule_set, signal = build_quality_fixture()
    StrategySignal.objects.filter(id=signal.id).update(used_domain_signal_value_ids=[{"bad": "shape"}])
    signal.refresh_from_db()

    result = run_quality(signal=signal, release=fixture["release"], rule_set=rule_set)

    assert result.status == "failed"
    assert result.data["quality_status"] == StrategySignalQualityStatus.FAILED
    assert StrategySignalQualityIssue.objects.filter(issue_code="strategy_signal_domain_value_id_invalid").exists()


@pytest.mark.django_db
def test_strategy_signal_quality_records_issue_for_invalid_weight_shape_instead_of_crashing() -> None:
    fixture, rule_set, signal = build_quality_fixture()
    StrategySignal.objects.filter(id=signal.id).update(actual_input_weights=[])
    signal.refresh_from_db()

    result = run_quality(signal=signal, release=fixture["release"], rule_set=rule_set)

    assert result.status == "failed"
    assert result.data["quality_status"] == StrategySignalQualityStatus.FAILED
    assert StrategySignalQualityIssue.objects.filter(issue_code="strategy_signal_weight_shape_invalid").exists()
