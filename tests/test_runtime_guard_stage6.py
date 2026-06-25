from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.alerts.models import AlertEvent
from apps.orchestration.models import OrchestrationRun, OrchestrationRunStatus, OrchestrationTriggerMode
from apps.runtime_guard.checks.default import IssueDraft
from apps.runtime_guard.models import RuntimeGuardIssue, RuntimeGuardRun
from apps.runtime_guard.services.guard import run_runtime_guard


@pytest.mark.django_db
def test_runtime_guard_dry_run_does_not_write() -> None:
    draft = IssueDraft(
        issue_type="orchestration_run_stale",
        severity="high",
        related_object_type="OrchestrationRun",
        related_object_id="1",
        related_trace_id="trace-guard",
        description_zh="测试问题",
    )

    summary = run_runtime_guard(
        trace_id="trace-guard",
        trigger_source="test",
        dry_run=True,
        confirm_write=False,
        issue_drafts=[draft],
    )

    assert summary.dry_run is True
    assert summary.checked_item_count == 1
    assert RuntimeGuardRun.objects.count() == 0
    assert RuntimeGuardIssue.objects.count() == 0


@pytest.mark.django_db
def test_runtime_guard_confirm_write_records_issue_and_alert_without_mutating_source() -> None:
    run = OrchestrationRun.objects.create(
        run_key="stale-run",
        pipeline_code="main_trading_pipeline",
        registry_version="p0.1",
        registry_hash="hash",
        scheduled_for_utc=timezone.now() - timedelta(hours=1),
        cycle_kind="4h",
        trigger_mode=OrchestrationTriggerMode.AUTOMATIC,
        trigger_source="test",
        status=OrchestrationRunStatus.RUNNING,
        trace_id="trace-stale-run",
    )
    old_updated = run.updated_at_utc
    draft = IssueDraft(
        issue_type="orchestration_run_stale",
        severity="high",
        related_object_type="OrchestrationRun",
        related_object_id=str(run.id),
        related_trace_id=run.trace_id,
        description_zh="编排运行卡住",
        evidence={"status": run.status},
    )

    summary = run_runtime_guard(
        trace_id="trace-guard-write",
        trigger_source="test",
        dry_run=False,
        confirm_write=True,
        issue_drafts=[draft],
    )
    run.refresh_from_db()

    assert summary.created_issue_count == 1
    assert RuntimeGuardIssue.objects.filter(issue_type="orchestration_run_stale", related_object_id=str(run.id)).exists()
    assert AlertEvent.objects.filter(source_module="runtime_guard", related_object_type="OrchestrationRun").exists()
    assert run.status == OrchestrationRunStatus.RUNNING
    assert run.updated_at_utc == old_updated


@pytest.mark.django_db
def test_runtime_guard_repeated_issue_updates_existing_record() -> None:
    draft = IssueDraft(
        issue_type="active_lock_stale",
        severity="critical",
        related_object_type="OrderPlanActiveLock",
        related_object_id="9",
        related_trace_id="trace-lock",
        description_zh="锁卡住",
    )

    first = run_runtime_guard(trace_id="trace-1", trigger_source="test", dry_run=False, confirm_write=True, issue_drafts=[draft])
    second = run_runtime_guard(trace_id="trace-2", trigger_source="test", dry_run=False, confirm_write=True, issue_drafts=[draft])
    issue = RuntimeGuardIssue.objects.get(issue_type="active_lock_stale")

    assert first.created_issue_count == 1
    assert second.updated_issue_count == 1
    assert RuntimeGuardIssue.objects.count() == 1
    assert issue.occurrence_count == 2
    assert AlertEvent.objects.filter(source_module="runtime_guard", event_type="active_lock_stale").count() == 1
