from __future__ import annotations

from datetime import UTC, datetime

import pytest

from apps.foundation.results import ResultStatus, ServiceResult
from apps.orchestration.adapters.base import BusinessObjectRef, OrchestrationStepResult, StepContext, result_hash
from apps.orchestration.adapters.business import OrderSubmissionStepAdapter
from apps.orchestration.adapters.registry import default_adapter_registry
from apps.orchestration.models import (
    OrchestrationBusinessObjectLink,
    OrchestrationRun,
    OrchestrationRunStatus,
    OrchestrationStepRun,
)
from apps.orchestration.registry.definitions import FORMAL_STEPS, ordered_step_codes, validate_registry
from apps.orchestration.services.orchestrator import (
    drive_orchestration_run,
    resume_waiting_orchestration_step,
    start_or_get_orchestration_run,
)


class FakeOutputAdapter:
    adapter_code = "BinanceAccountSyncStepAdapter"
    adapter_version = "1.0"
    module_code = "binance_account_sync"

    def execute(self, context: StepContext) -> OrchestrationStepResult:
        summary = {"status": "succeeded", "binance_sync_run_id": 101}
        ref = BusinessObjectRef(object_type="BinanceSyncRun", object_id="101", role="primary")
        return OrchestrationStepResult(
            step_code=context.step_code,
            module_code=self.module_code,
            adapter_code=self.adapter_code,
            adapter_version=self.adapter_version,
            normalized_status="SUCCEEDED",
            flow_action="CONTINUE",
            reason_code="fake_sync_done",
            message_zh="账户快照已同步",
            primary_object_ref=ref,
            business_object_refs=(ref,),
            raw_business_status="succeeded",
            raw_result_summary=summary,
            raw_result_hash=result_hash(summary),
            needs_manual_attention=False,
        )


class FakeNoActionAdapter:
    adapter_code = "DataCollectionStepAdapter"
    adapter_version = "1.0"
    module_code = "market_data"

    def execute(self, context: StepContext) -> OrchestrationStepResult:
        summary = {"status": "no_action"}
        return OrchestrationStepResult(
            step_code=context.step_code,
            module_code=self.module_code,
            adapter_code=self.adapter_code,
            adapter_version=self.adapter_version,
            normalized_status="NO_ACTION",
            flow_action="COMPLETE",
            reason_code="fake_no_action",
            message_zh="测试链路正常结束",
            primary_object_ref=None,
            business_object_refs=(),
            raw_business_status="no_action",
            raw_result_summary=summary,
            raw_result_hash=result_hash(summary),
            needs_manual_attention=False,
        )


class FakeResumeNoActionAdapter(FakeNoActionAdapter):
    adapter_code = "BinanceAccountSyncStepAdapter"
    module_code = "binance_account_sync"


class FakeWaitAdapter:
    adapter_code = "BinanceAccountSyncStepAdapter"
    adapter_version = "1.0"
    module_code = "binance_account_sync"

    def execute(self, context: StepContext) -> OrchestrationStepResult:
        summary = {"status": "waiting"}
        return OrchestrationStepResult(
            step_code=context.step_code,
            module_code=self.module_code,
            adapter_code=self.adapter_code,
            adapter_version=self.adapter_version,
            normalized_status="UNKNOWN",
            flow_action="WAIT",
            reason_code="fake_wait",
            message_zh="等待外部状态",
            primary_object_ref=None,
            business_object_refs=(),
            raw_business_status="waiting",
            raw_result_summary=summary,
            raw_result_hash=result_hash(summary),
            needs_manual_attention=False,
            resume_token="resume-token-1",
            resume_step_code=context.step_code,
        )


class AdapterThatMustNotRun:
    adapter_code = "BinanceAccountSyncStepAdapter"
    adapter_version = "1.0"
    module_code = "binance_account_sync"

    def execute(self, context: StepContext) -> OrchestrationStepResult:
        raise AssertionError("waiting run must be resumed through resume token")


@pytest.mark.django_db
def test_registry_contains_formal_pipeline_order() -> None:
    validate_registry(FORMAL_STEPS)
    assert ordered_step_codes()[:4] == (
        "binance_account_sync",
        "data_collection",
        "data_quality",
        "data_backfill",
    )
    assert ordered_step_codes()[-1] == "order_submission"
    assert "order_status_sync" not in ordered_step_codes()
    assert "fill_sync" not in ordered_step_codes()
    assert "OrderStatusSyncStepAdapter" not in default_adapter_registry()
    assert "FillSyncStepAdapter" not in default_adapter_registry()


@pytest.mark.parametrize(
    ("service_status", "order_submission_status", "expected_normalized_status"),
    (
        (ResultStatus.SUCCEEDED, "accepted", "SUCCEEDED"),
        (ResultStatus.UNKNOWN, "unknown", "UNKNOWN"),
    ),
)
def test_order_submission_adapter_maps_lifecycle_required_result_to_main_run_complete(
    monkeypatch: pytest.MonkeyPatch,
    service_status: str,
    order_submission_status: str,
    expected_normalized_status: str,
) -> None:
    def fake_submit_prepared_order(**_kwargs: object) -> ServiceResult:
        return ServiceResult(
            service_status,
            f"order_submission_{order_submission_status}",
            "订单提交事实已形成。",
            "trace-adapter",
            "test",
            {
                "order_submission_attempt_id": 123,
                "prepared_order_intent_id": 456,
                "order_submission_status": order_submission_status,
                "allows_order_status_sync": True,
            },
        )

    monkeypatch.setattr("apps.execution.services.submission.submit_prepared_order", fake_submit_prepared_order)

    result = OrderSubmissionStepAdapter().execute(
        StepContext(
            orchestration_run_id=1,
            step_run_id=1,
            step_code="order_submission",
            business_request_key="test-order-submission-adapter",
            trace_id="trace-adapter",
            trigger_source="test",
            reference_time_utc=datetime(2026, 1, 1, 0, 0, tzinfo=UTC),
            object_links={"PreparedOrderIntent": [BusinessObjectRef("PreparedOrderIntent", "456")]},
        )
    )

    assert result.normalized_status == expected_normalized_status
    assert result.flow_action == "COMPLETE"
    assert result.primary_object_ref is not None
    assert result.primary_object_ref.object_type == "OrderSubmissionAttempt"


@pytest.mark.django_db
def test_start_or_get_run_is_idempotent() -> None:
    scheduled = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
    first = start_or_get_orchestration_run(scheduled_for_utc=scheduled, trace_id="trace-a")
    second = start_or_get_orchestration_run(scheduled_for_utc=scheduled, trace_id="trace-b")

    assert first.id == second.id
    assert OrchestrationRun.objects.count() == 1
    assert first.config_snapshot.snapshot_hash


@pytest.mark.django_db
def test_drive_run_records_steps_and_business_object_links() -> None:
    run = start_or_get_orchestration_run(
        scheduled_for_utc=datetime(2026, 1, 1, 4, 0, tzinfo=UTC),
        trace_id="trace-drive",
    )

    summary = drive_orchestration_run(
        orchestration_run_id=run.id,
        adapter_registry={
            "BinanceAccountSyncStepAdapter": FakeOutputAdapter(),
            "DataCollectionStepAdapter": FakeNoActionAdapter(),
        },
    )

    run.refresh_from_db()
    assert summary.status == OrchestrationRunStatus.COMPLETED_NO_ACTION
    assert summary.executed_step_count == 2
    assert list(OrchestrationStepRun.objects.filter(orchestration_run=run).order_by("execution_sequence").values_list("step_code", flat=True)) == [
        "binance_account_sync",
        "data_collection",
    ]
    assert OrchestrationBusinessObjectLink.objects.filter(
        orchestration_run=run,
        object_type="BinanceSyncRun",
        object_id="101",
    ).exists()


@pytest.mark.django_db
def test_resume_waiting_step_consumes_waiting_step_once() -> None:
    run = start_or_get_orchestration_run(
        scheduled_for_utc=datetime(2026, 1, 1, 8, 0, tzinfo=UTC),
        trace_id="trace-wait",
    )
    waiting_summary = drive_orchestration_run(
        orchestration_run_id=run.id,
        adapter_registry={"BinanceAccountSyncStepAdapter": FakeWaitAdapter()},
    )
    assert waiting_summary.status == OrchestrationRunStatus.WAITING

    resumed_summary = resume_waiting_orchestration_step(
        resume_token="resume-token-1",
        trace_id="trace-resume",
        adapter_registry={"BinanceAccountSyncStepAdapter": FakeResumeNoActionAdapter()},
    )

    run.refresh_from_db()
    step = OrchestrationStepRun.objects.get(orchestration_run=run, step_code="binance_account_sync")
    assert resumed_summary.status == OrchestrationRunStatus.COMPLETED_NO_ACTION
    assert step.resume_token is None


@pytest.mark.django_db
def test_normal_driver_does_not_reexecute_waiting_run() -> None:
    run = start_or_get_orchestration_run(
        scheduled_for_utc=datetime(2026, 1, 1, 12, 0, tzinfo=UTC),
        trace_id="trace-wait-normal-driver",
    )
    drive_orchestration_run(
        orchestration_run_id=run.id,
        adapter_registry={"BinanceAccountSyncStepAdapter": FakeWaitAdapter()},
    )

    summary = drive_orchestration_run(
        orchestration_run_id=run.id,
        adapter_registry={"BinanceAccountSyncStepAdapter": AdapterThatMustNotRun()},
    )

    assert summary.status == OrchestrationRunStatus.WAITING
    assert summary.reason_code == "orchestration_waiting_for_resume"
