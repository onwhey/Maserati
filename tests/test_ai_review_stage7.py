from __future__ import annotations

import json
from datetime import timedelta

import pytest
from django.utils import timezone

from apps.ai_review.models import (
    AIReviewAttemptStatus,
    AIReviewMode,
    AIReviewRequest,
    AIReviewRequestStatus,
    AIReviewSuggestion,
    AIReviewSuggestionStatus,
)
from apps.ai_review.services import (
    build_review_package,
    create_review_request,
    run_ai_review,
    update_suggestion_status,
)
from apps.alerts.models import AlertEvent, NotificationSuppression
from apps.audit.models import AuditRecord
from apps.deepseek_gateway.review import FakeDeepSeekReviewGateway
from apps.deepseek_gateway.types import ERROR_UNKNOWN_AFTER_SEND, STATUS_UNKNOWN_AFTER_SEND
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


pytestmark = pytest.mark.django_db


def _run(*, key: str, scheduled_for, status: str = OrchestrationRunStatus.COMPLETED) -> OrchestrationRun:
    run = OrchestrationRun.objects.create(
        run_key=f"ai-review-run-{key}",
        pipeline_code="main_trading_pipeline",
        registry_version="p0.1",
        registry_hash="hash",
        scheduled_for_utc=scheduled_for,
        cycle_kind="4h",
        trigger_mode=OrchestrationTriggerMode.AUTOMATIC,
        trigger_source="test",
        status=status,
        final_outcome="succeeded" if status == OrchestrationRunStatus.COMPLETED else "blocked",
        reason_code="" if status == OrchestrationRunStatus.COMPLETED else "test_blocked",
        trace_id=f"trace-ai-review-{key}",
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
        business_request_key=f"ai-review-step-{key}",
        status=OrchestrationStepRunStatus.SUCCEEDED,
        normalized_status="SUCCEEDED",
        flow_action="CONTINUE",
        reason_code="decision_snapshot_done",
        trace_id=run.trace_id,
        finished_at_utc=scheduled_for + timedelta(minutes=3),
        last_status_updated_at_utc=scheduled_for + timedelta(minutes=3),
    )
    OrchestrationBusinessObjectLink.objects.create(
        orchestration_run=run,
        step_run=step,
        step_code=step.step_code,
        module_code=step.module_code,
        object_role=OrchestrationObjectRole.OUTPUT,
        object_type="DecisionSnapshot",
        object_id=f"decision-{key}",
        object_label=f"decision-{key}",
        trace_id=run.trace_id,
    )
    return run


def _request(*, request_key: str = "ai-review-request-1", manual_question: str = ""):
    now = timezone.now()
    first = _run(key=f"{request_key}-1", scheduled_for=now - timedelta(hours=8))
    second = _run(key=f"{request_key}-2", scheduled_for=now - timedelta(hours=4), status=OrchestrationRunStatus.BLOCKED)
    return create_review_request(
        review_mode=AIReviewMode.CYCLE_REVIEW,
        range_selector={"type": "run_ids", "ids": [first.id, second.id]},
        filters={},
        manual_question=manual_question,
        model_profile_code="default_review",
        requested_by="tester",
        request_key=request_key,
        trace_id=f"trace-{request_key}",
        trigger_source="test",
    )


def test_create_review_request_freezes_run_range_and_is_idempotent() -> None:
    result = _request(request_key="ai-review-create")

    assert result.status == ResultStatus.SUCCEEDED
    request = AIReviewRequest.objects.get(id=result.data["ai_review_request_id"])
    assert request.status == AIReviewRequestStatus.CREATED
    assert len(request.frozen_orchestration_run_ids) == 2
    assert AuditRecord.objects.filter(target_object_type="AIReviewRequest", target_object_id=str(request.id)).exists()
    assert AlertEvent.objects.filter(source_module="ai_review", related_object_id=str(request.id)).exists()
    assert NotificationSuppression.objects.filter(alert_event__source_module="ai_review").exists()

    duplicate = create_review_request(
        review_mode=AIReviewMode.CYCLE_REVIEW,
        range_selector={"type": "run_ids", "ids": request.frozen_orchestration_run_ids},
        filters={},
        manual_question="",
        model_profile_code="default_review",
        requested_by="tester",
        request_key="ai-review-create",
        trace_id="trace-ai-review-create",
        trigger_source="test",
    )

    assert duplicate.status == ResultStatus.SUCCEEDED
    assert duplicate.data["ai_review_request_id"] == request.id
    assert duplicate.data["idempotent"] is True


def test_manual_question_review_requires_question() -> None:
    result = create_review_request(
        review_mode=AIReviewMode.MANUAL_QUESTION_REVIEW,
        range_selector={"type": "recent_runs", "limit": 20},
        filters={},
        manual_question="",
        model_profile_code="default_review",
        requested_by="tester",
        request_key="ai-review-manual-missing",
        trace_id="trace-ai-review-manual-missing",
        trigger_source="test",
    )

    assert result.status == ResultStatus.BLOCKED
    request = AIReviewRequest.objects.get(id=result.data["ai_review_request_id"])
    assert request.status == AIReviewRequestStatus.BLOCKED
    assert request.reason_code == "manual_question_required"


def test_create_review_request_blocks_missing_request_key_without_exception() -> None:
    result = create_review_request(
        review_mode=AIReviewMode.CYCLE_REVIEW,
        range_selector={"type": "recent_runs", "limit": 20},
        filters={},
        manual_question="",
        model_profile_code="default_review",
        requested_by="tester",
        request_key=None,  # type: ignore[arg-type]
        trace_id="trace-ai-review-empty-key",
        trigger_source="test",
    )

    assert result.status == ResultStatus.BLOCKED
    assert result.reason_code == "ai_review_request_key_required"
    assert AIReviewRequest.objects.count() == 0


def test_create_review_request_blocks_invalid_range_selector_without_exception() -> None:
    result = create_review_request(
        review_mode=AIReviewMode.CYCLE_REVIEW,
        range_selector=["not-a-dict"],  # type: ignore[arg-type]
        filters={},
        manual_question="",
        model_profile_code="default_review",
        requested_by="tester",
        request_key="ai-review-invalid-range",
        trace_id="trace-ai-review-invalid-range",
        trigger_source="test",
    )

    request = AIReviewRequest.objects.get(id=result.data["ai_review_request_id"])
    assert result.status == ResultStatus.BLOCKED
    assert request.status == AIReviewRequestStatus.BLOCKED
    assert request.reason_code == "invalid_review_range"


def test_create_review_request_blocks_invalid_recent_limit_without_exception() -> None:
    result = create_review_request(
        review_mode=AIReviewMode.CYCLE_REVIEW,
        range_selector={"type": "recent_runs", "limit": "bad-limit"},
        filters={},
        manual_question="",
        model_profile_code="default_review",
        requested_by="tester",
        request_key="ai-review-invalid-limit",
        trace_id="trace-ai-review-invalid-limit",
        trigger_source="test",
    )

    request = AIReviewRequest.objects.get(id=result.data["ai_review_request_id"])
    assert result.status == ResultStatus.BLOCKED
    assert request.status == AIReviewRequestStatus.BLOCKED
    assert request.reason_code == "invalid_review_range"


def test_build_review_package_sanitizes_payload_and_reuses_existing_package() -> None:
    result = _request(request_key="ai-review-package", manual_question="api_key=secret-token")
    request_id = result.data["ai_review_request_id"]

    package_result = build_review_package(ai_review_request_id=request_id, trace_id="trace-package", trigger_source="test")
    second_result = build_review_package(ai_review_request_id=request_id, trace_id="trace-package", trigger_source="test")

    assert package_result.status == ResultStatus.SUCCEEDED
    assert second_result.status == ResultStatus.SUCCEEDED
    request = AIReviewRequest.objects.get(id=request_id)
    package = request.active_package
    assert package is not None
    payload_text = json.dumps(package.json_payload, ensure_ascii=False)
    assert "secret-token" not in payload_text
    assert package.run_count == 2
    assert package.sanitized is True


def test_run_ai_review_with_fake_gateway_persists_report_findings_and_suggestions() -> None:
    request_result = _request(request_key="ai-review-run")
    request_id = request_result.data["ai_review_request_id"]
    output = json.dumps(
        {
            "report_title": "周期复盘",
            "executive_summary": "本轮数据完整，存在一个人工关注点。",
            "confidence": "0.8",
            "key_findings": [
                {
                    "finding_type": "runtime",
                    "severity": "warning",
                    "title": "存在阻断运行",
                    "description": "有一轮编排被阻断，需要人工查看。",
                    "related_run_ids": [AIReviewRequest.objects.get(id=request_id).frozen_orchestration_run_ids[-1]],
                    "confidence": "0.7",
                }
            ],
            "suggestions": [
                {
                    "suggestion_type": "manual_follow_up",
                    "priority": "medium",
                    "title": "人工检查阻断原因",
                    "description": "只作为人工复盘建议，不自动执行。",
                    "suggested_action": "查看阻断步骤的业务对象。",
                    "rationale": "防止同类阻断重复出现。",
                }
            ],
            "data_limitations": ["仅基于已落库事实"],
        },
        ensure_ascii=False,
    )
    gateway = FakeDeepSeekReviewGateway(output_text=output)

    result = run_ai_review(ai_review_request_id=request_id, gateway=gateway, trace_id="trace-run-ai-review", trigger_source="test")

    assert result.status == ResultStatus.SUCCEEDED
    request = AIReviewRequest.objects.get(id=request_id)
    assert request.status == AIReviewRequestStatus.COMPLETED
    assert request.completed_report is not None
    assert request.completed_report.findings.count() == 1
    assert request.completed_report.suggestions.count() == 1
    assert request.attempts.get().status == AIReviewAttemptStatus.SUCCEEDED
    assert gateway.calls[0]["context"].caller_module == "AIReviewService"
    assert gateway.calls[0]["context"].model_profile_code == "default_review"


def test_run_ai_review_marks_unknown_after_send_without_creating_report() -> None:
    request_result = _request(request_key="ai-review-unknown")
    gateway = FakeDeepSeekReviewGateway(fail_status=STATUS_UNKNOWN_AFTER_SEND, fail_error_category=ERROR_UNKNOWN_AFTER_SEND)

    result = run_ai_review(
        ai_review_request_id=request_result.data["ai_review_request_id"],
        gateway=gateway,
        trace_id="trace-ai-review-unknown",
        trigger_source="test",
    )

    request = AIReviewRequest.objects.get(id=request_result.data["ai_review_request_id"])
    assert result.status == ResultStatus.UNKNOWN
    assert request.status == AIReviewRequestStatus.UNKNOWN
    assert request.completed_report is None
    assert request.attempts.get().status == AIReviewAttemptStatus.UNKNOWN


def test_run_ai_review_fails_on_unparseable_model_output_without_report() -> None:
    request_result = _request(request_key="ai-review-parse-fail")

    result = run_ai_review(
        ai_review_request_id=request_result.data["ai_review_request_id"],
        gateway=FakeDeepSeekReviewGateway(output_text="not-json"),
        trace_id="trace-ai-review-parse-fail",
        trigger_source="test",
    )

    request = AIReviewRequest.objects.get(id=request_result.data["ai_review_request_id"])
    assert result.status == ResultStatus.FAILED
    assert request.status == AIReviewRequestStatus.FAILED
    assert request.completed_report is None
    assert request.attempts.get().status == AIReviewAttemptStatus.RESPONSE_PARSE_ERROR


def test_run_ai_review_gateway_exception_does_not_leave_request_calling() -> None:
    class RaisingGateway:
        def generate_review_completion(self, **kwargs):
            raise RuntimeError("gateway exploded")

    request_result = _request(request_key="ai-review-gateway-exception")

    result = run_ai_review(
        ai_review_request_id=request_result.data["ai_review_request_id"],
        gateway=RaisingGateway(),
        trace_id="trace-ai-review-gateway-exception",
        trigger_source="test",
    )

    request = AIReviewRequest.objects.get(id=request_result.data["ai_review_request_id"])
    assert result.status == ResultStatus.FAILED
    assert request.status == AIReviewRequestStatus.FAILED
    assert request.reason_code == "deepseek_gateway_exception"
    assert request.attempts.get().status == AIReviewAttemptStatus.FAILED


def test_update_suggestion_status_records_human_decision_only() -> None:
    request_result = _request(request_key="ai-review-suggestion")
    output = json.dumps(
        {
            "report_title": "复盘",
            "executive_summary": "summary",
            "suggestions": [{"suggestion_type": "manual_task", "title": "人工处理", "description": "desc"}],
        },
        ensure_ascii=False,
    )
    run_ai_review(
        ai_review_request_id=request_result.data["ai_review_request_id"],
        gateway=FakeDeepSeekReviewGateway(output_text=output),
        trace_id="trace-ai-review-suggestion",
        trigger_source="test",
    )
    suggestion = AIReviewSuggestion.objects.get()

    result = update_suggestion_status(
        suggestion_id=suggestion.id,
        new_status=AIReviewSuggestionStatus.ACCEPTED,
        operator_id="tester",
        decision_note="确认作为人工任务处理",
        trace_id="trace-ai-review-suggestion-status",
        trigger_source="test",
    )

    suggestion.refresh_from_db()
    assert result.status == ResultStatus.SUCCEEDED
    assert suggestion.status == AIReviewSuggestionStatus.ACCEPTED
    assert suggestion.reviewed_by == "tester"
    assert AuditRecord.objects.filter(target_object_type="AIReviewSuggestion", target_object_id=str(suggestion.id)).exists()
