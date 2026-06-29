from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.alerts.models import AlertEvent, NotificationSuppression
from apps.audit.models import AuditRecord
from apps.binance_gateway.order_cancel import FakeBinanceOrderCancelGateway
from apps.foundation.results import ResultStatus
from apps.orchestration.models import (
    OrchestrationBusinessObjectLink,
    OrchestrationObjectRole,
    OrchestrationRun,
    OrchestrationRunStatus,
    OrchestrationStepRun,
    OrchestrationStepRunStatus,
    OrchestrationTriggerMode,
)
from apps.review_dataset.models import ReviewDatasetBuildStatus, ReviewDatasetExport, ReviewDatasetRecord
from apps.review_dataset.services import build_review_dataset_records, create_review_dataset_export, preview_review_dataset
from tests.test_fill_sync_stage5 import _enable
from tests.test_order_cycle_closeout_stage5 import _closeout, _limit_attempt


pytestmark = pytest.mark.django_db


def _run(*, key: str, scheduled_for) -> OrchestrationRun:
    run = OrchestrationRun.objects.create(
        run_key=f"review-dataset-run-{key}",
        pipeline_code="main_trading_pipeline",
        registry_version="p0.1",
        registry_hash="hash",
        scheduled_for_utc=scheduled_for,
        cycle_kind="4h",
        trigger_mode=OrchestrationTriggerMode.AUTOMATIC,
        trigger_source="test",
        status=OrchestrationRunStatus.COMPLETED,
        final_outcome="succeeded",
        trace_id=f"trace-review-dataset-{key}",
        finished_at_utc=scheduled_for + timedelta(minutes=5),
    )
    step = OrchestrationStepRun.objects.create(
        orchestration_run=run,
        step_code="decision_snapshot",
        module_code="decision_snapshot",
        adapter_code="DecisionSnapshotStepAdapter",
        adapter_version="1.0",
        result_mapping_version="1.0",
        execution_sequence=1,
        business_request_key=f"review-dataset-step-{key}",
        status=OrchestrationStepRunStatus.SUCCEEDED,
        normalized_status="SUCCEEDED",
        flow_action="CONTINUE",
        reason_code="decision_snapshot_done",
        trace_id=run.trace_id,
    )
    OrchestrationBusinessObjectLink.objects.create(
        orchestration_run=run,
        step_run=step,
        step_code=step.step_code,
        module_code=step.module_code,
        object_role=OrchestrationObjectRole.OUTPUT,
        object_type="DecisionSnapshot",
        object_id=f"decision-{key}",
        object_identity_hash=f"hash-{key}",
        object_label=f"decision-{key}",
        trace_id=run.trace_id,
    )
    return run


def _link(run: OrchestrationRun, *, object_type: str, object_id: int | str, label: str) -> None:
    step = run.step_runs.order_by("execution_sequence").first()
    assert step is not None
    OrchestrationBusinessObjectLink.objects.create(
        orchestration_run=run,
        step_run=step,
        step_code=step.step_code,
        module_code=step.module_code,
        object_role=OrchestrationObjectRole.OUTPUT,
        object_type=object_type,
        object_id=str(object_id),
        object_identity_hash=f"hash-{object_type}-{object_id}",
        object_label=label,
        trace_id=run.trace_id,
    )


def test_preview_review_dataset_is_read_only() -> None:
    run = _run(key="preview", scheduled_for=timezone.now().replace(minute=0, second=0, microsecond=0))

    result = preview_review_dataset(range_selector={"type": "run_ids", "ids": [run.id]}, filters={}, trace_id="trace-preview")

    assert result.status == ResultStatus.SUCCEEDED
    assert result.data["record_count"] == 1
    assert ReviewDatasetRecord.objects.count() == 0
    assert ReviewDatasetExport.objects.count() == 0


def test_create_review_dataset_export_writes_records_audit_alert_and_file(settings, tmp_path) -> None:
    settings.REVIEW_DATASET_EXPORT_DIR = str(tmp_path)
    run = _run(key="export", scheduled_for=timezone.now().replace(minute=0, second=0, microsecond=0))

    result = create_review_dataset_export(
        range_selector={"type": "run_ids", "ids": [run.id]},
        filters={},
        export_format="json",
        operator_id="tester",
        reason="export facts for local review",
        trace_id="trace-review-dataset-export",
    )

    assert result.status == ResultStatus.SUCCEEDED
    record = ReviewDatasetRecord.objects.get(subject_orchestration_run=run)
    export = ReviewDatasetExport.objects.get(id=result.data["export_id"])
    assert record.build_status in {ReviewDatasetBuildStatus.BUILT, ReviewDatasetBuildStatus.PARTIAL}
    assert export.record_count == 1
    assert (tmp_path / f"{export.export_key}.json").exists()
    assert AuditRecord.objects.filter(operation_type="review_dataset_export_create", target_object_id=str(export.id)).exists()
    assert AlertEvent.objects.filter(source_module="review_dataset", related_object_id=str(export.id)).exists()
    assert NotificationSuppression.objects.filter(alert_event__source_module="review_dataset").exists()


def test_create_review_dataset_export_rejects_unknown_format(settings, tmp_path) -> None:
    settings.REVIEW_DATASET_EXPORT_DIR = str(tmp_path)
    run = _run(key="format", scheduled_for=timezone.now().replace(minute=0, second=0, microsecond=0))

    result = create_review_dataset_export(
        range_selector={"type": "run_ids", "ids": [run.id]},
        filters={},
        export_format="xlsx",
        operator_id="tester",
        reason="export facts for local review",
        trace_id="trace-review-dataset-format",
    )

    assert result.status == ResultStatus.BLOCKED
    assert result.reason_code == "review_dataset_export_format_not_allowed"
    assert ReviewDatasetRecord.objects.count() == 0
    assert ReviewDatasetExport.objects.count() == 0


def test_create_review_dataset_export_rejects_missing_run_id(settings, tmp_path) -> None:
    settings.REVIEW_DATASET_EXPORT_DIR = str(tmp_path)
    run = _run(key="missing", scheduled_for=timezone.now().replace(minute=0, second=0, microsecond=0))

    result = create_review_dataset_export(
        range_selector={"type": "run_ids", "ids": [run.id, 999999]},
        filters={},
        export_format="json",
        operator_id="tester",
        reason="export facts for local review",
        trace_id="trace-review-dataset-missing",
    )

    assert result.status == ResultStatus.BLOCKED
    assert result.reason_code == "review_dataset_run_missing"
    assert ReviewDatasetRecord.objects.count() == 0
    assert ReviewDatasetExport.objects.count() == 0


def test_review_dataset_collects_limit_order_closeout_lifecycle_facts(settings) -> None:
    _enable(settings)
    run = _run(key="limit-closeout", scheduled_for=timezone.now().replace(minute=0, second=0, microsecond=0))
    attempt, valid_until = _limit_attempt(settings, key="review-limit-closeout")
    _closeout(attempt, valid_until, FakeBinanceOrderCancelGateway(), key="review-limit-closeout")
    _link(run, object_type="OrderSubmissionAttempt", object_id=attempt.id, label="submitted-limit-order")

    result = build_review_dataset_records(
        range_selector={"type": "run_ids", "ids": [run.id]},
        filters={},
        operator_id="tester",
        reason="collect order lifecycle facts",
        trace_id="trace-review-dataset-limit-closeout",
    )

    assert result.status == ResultStatus.SUCCEEDED
    record = ReviewDatasetRecord.objects.get(subject_orchestration_run=run)
    order_lifecycle = record.summary["order_lifecycle"]
    assert record.object_counts["OrderSubmissionAttempt"] == 1
    assert record.object_counts["OrderCancelAttempt"] == 1
    assert record.object_counts["OrderStatusSyncRecord"] == 1
    assert record.object_counts["FillSyncResult"] == 1
    assert record.object_counts["OrderFillSummary"] == 1
    assert order_lifecycle["order_submission_attempts"][0]["order_type"] == "LIMIT"
    assert order_lifecycle["order_cancel_attempts"][0]["cancel_status"] == "accepted"
    assert order_lifecycle["order_status_sync_records"][0]["exchange_status"] == "CANCELED"
    assert order_lifecycle["fill_sync_results"][0]["status"] == "synced_empty"
    assert order_lifecycle["order_fill_summaries"][0]["lock_finalization_status"] == "active_lock_released"
