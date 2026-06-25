"""AIReview services.

Module: AIReview
Responsibility: create offline review requests, freeze review ranges, build
sanitized packages, call DeepSeekGateway through its restricted interface,
persist reports/findings/suggestions, and update human suggestion status.
Not responsible for real-time trading, strategy mutation, order mutation,
account mutation, Binance access, direct DeepSeek HTTP access, Hermes sending,
or RuntimeGuard scanning.
Database: reads existing facts and writes AIReview/Audit/Alert facts.
Redis: not used. External services: only via injected DeepSeekGateway.
LLM: only through DeepSeekGateway for offline review. Real trading: never.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.alerts.models import AlertSeverity
from apps.alerts.services import record_alert_event
from apps.audit.services import record_audit
from apps.deepseek_gateway.review import DeepSeekReviewGateway, HttpDeepSeekReviewGateway
from apps.deepseek_gateway.types import (
    CALLER_AI_REVIEW_SERVICE,
    PURPOSE_AI_REVIEW,
    STATUS_SUCCEEDED,
    STATUS_TIMEOUT,
    STATUS_UNKNOWN_AFTER_SEND,
    DeepSeekGatewayCallContext,
    DeepSeekGatewayResult,
)
from apps.execution.models import OrderSubmissionAttempt
from apps.fill_sync.models import OrderFillSummary, TradeFill
from apps.foundation.redaction import sanitize_mapping, sanitize_value
from apps.foundation.results import ResultStatus, ServiceResult
from apps.orchestration.models import (
    OrchestrationBusinessObjectLink,
    OrchestrationRun,
    OrchestrationRunStatus,
    OrchestrationStepRun,
    OrchestrationTriggerMode,
)
from apps.performance_metrics.models import OrchestrationRunPerformance
from apps.runtime_guard.models import RuntimeGuardIssue

from .models import (
    AIReviewAttempt,
    AIReviewAttemptStatus,
    AIReviewFinding,
    AIReviewFindingSeverity,
    AIReviewMode,
    AIReviewPackage,
    AIReviewPackageStatus,
    AIReviewReport,
    AIReviewRequest,
    AIReviewRequestStatus,
    AIReviewSuggestion,
    AIReviewSuggestionStatus,
)


TRIGGER_SOURCE_OPS_CONSOLE = "ops_console_ai_review"
SOURCE_MODULE = "ai_review"
PROMPT_NAME_PREFIX = "ai_review"

RECENT_RUN_SELECTOR = "recent_runs"
RUN_IDS_SELECTOR = "run_ids"
UTC_TIME_RANGE_SELECTOR = "utc_time_range"
ALLOWED_RECENT_LIMITS = {20, 50, 100}
PROBLEM_RUN_STATUSES = {
    OrchestrationRunStatus.BLOCKED,
    OrchestrationRunStatus.UNKNOWN,
    OrchestrationRunStatus.FAILED,
    OrchestrationRunStatus.STALE_INTERRUPTED,
}
VALID_SUGGESTION_STATUSES = {choice.value for choice in AIReviewSuggestionStatus}


@dataclass(frozen=True)
class FrozenRange:
    run_ids: list[int]
    reason_code: str = ""
    reason_message: str = ""


def create_review_request(
    *,
    review_mode: str,
    range_selector: dict[str, Any],
    filters: dict[str, Any] | None,
    manual_question: str,
    model_profile_code: str,
    requested_by: str,
    request_key: str,
    trace_id: str,
    trigger_source: str = TRIGGER_SOURCE_OPS_CONSOLE,
) -> ServiceResult:
    normalized_request_key = str(request_key or "").strip()
    normalized_range_selector = range_selector if isinstance(range_selector, dict) else {}
    normalized_filters = filters if isinstance(filters, dict) else {}
    if not normalized_request_key:
        return _service_blocked("ai_review_request_key_required", "AIReview 请求必须提供 request_key。", trace_id, trigger_source)
    existing = AIReviewRequest.objects.filter(request_key=normalized_request_key).first()
    if existing is not None:
        return ServiceResult(
            status=_result_status_for_request(existing),
            reason_code="ai_review_request_already_exists",
            message="相同 request_key 的 AIReviewRequest 已存在。",
            trace_id=trace_id,
            trigger_source=trigger_source,
            data={"ai_review_request_id": existing.id, "idempotent": True, "request_status": existing.status},
        )

    normalized_mode = str(review_mode or "").strip()
    normalized_profile = str(model_profile_code or "").strip()
    normalized_question = str(manual_question or "").strip()
    frozen_range = FrozenRange(run_ids=[])
    status = AIReviewRequestStatus.CREATED
    reason_code = ""
    reason_message = ""
    if normalized_mode not in {choice.value for choice in AIReviewMode}:
        status = AIReviewRequestStatus.BLOCKED
        reason_code = "invalid_review_mode"
        reason_message = "未知 review_mode，AIReview 已阻断。"
    elif normalized_mode == AIReviewMode.MANUAL_QUESTION_REVIEW and not normalized_question:
        status = AIReviewRequestStatus.BLOCKED
        reason_code = "manual_question_required"
        reason_message = "manual_question_review 必须提供明确人工问题。"
    elif not normalized_profile:
        status = AIReviewRequestStatus.BLOCKED
        reason_code = "model_profile_code_required"
        reason_message = "AIReview 必须选择受控 model_profile_code。"
    else:
        frozen_range = freeze_review_range(range_selector=range_selector, filters=filters or {})
        if frozen_range.reason_code:
            status = AIReviewRequestStatus.BLOCKED
            reason_code = frozen_range.reason_code
            reason_message = frozen_range.reason_message

    prompt = prompt_metadata(normalized_mode or "unknown")
    try:
        with transaction.atomic():
            request = AIReviewRequest.objects.create(
                request_key=normalized_request_key,
                review_mode=normalized_mode if normalized_mode in {choice.value for choice in AIReviewMode} else AIReviewMode.CYCLE_REVIEW,
                status=status,
                reason_code=reason_code,
                reason_message=reason_message,
                range_selector=sanitize_mapping(normalized_range_selector),
                filters=sanitize_mapping(normalized_filters),
                frozen_orchestration_run_ids=frozen_range.run_ids,
                frozen_range_hash=stable_hash({"run_ids": frozen_range.run_ids, "filters": normalized_filters}),
                manual_question=normalized_question[:4000],
                model_profile_code=normalized_profile or getattr(settings, "DEEPSEEK_DEFAULT_MODEL_PROFILE", "default_review"),
                requested_by=str(requested_by or "")[:120],
                prompt_name=prompt["prompt_name"],
                prompt_version=prompt["prompt_version"],
                prompt_hash=prompt["prompt_hash"],
                prompt_schema_version=prompt["prompt_schema_version"],
                output_schema_version=prompt["output_schema_version"],
                trace_id=trace_id,
                trigger_source=trigger_source,
            )
            record_audit(
                operator_id=str(requested_by or "")[:120],
                operation_type="ai_review_request_create",
                target_object_type="AIReviewRequest",
                target_object_id=str(request.id),
                before_state_summary={},
                after_state_summary={
                    "review_mode": request.review_mode,
                    "status": request.status,
                    "frozen_run_count": len(frozen_range.run_ids),
                    "reason_code": request.reason_code,
                },
                reason="创建离线 AI 复盘请求。",
                evidence={"request_key": request.request_key},
                result="succeeded" if status != AIReviewRequestStatus.BLOCKED else "blocked",
                trace_id=trace_id,
                trigger_source=trigger_source,
            )
            _alert(
                event_type="ai_review_requested",
                request=request,
                severity=AlertSeverity.INFO,
                reason_code=reason_code,
                message="AIReview 请求已创建。" if status != AIReviewRequestStatus.BLOCKED else "AIReview 请求已阻断。",
                payload={"review_mode": request.review_mode, "status": request.status, "run_count": len(frozen_range.run_ids)},
            )
    except IntegrityError:
        request = AIReviewRequest.objects.get(request_key=normalized_request_key)
        return ServiceResult(
            status=_result_status_for_request(request),
            reason_code="ai_review_request_already_exists",
            message="相同 request_key 的 AIReviewRequest 已存在。",
            trace_id=trace_id,
            trigger_source=trigger_source,
            data={"ai_review_request_id": request.id, "idempotent": True, "request_status": request.status},
        )

    return ServiceResult(
        status=_result_status_for_request(request),
        reason_code=reason_code or "ai_review_request_created",
        message=reason_message or "AIReview 请求已创建。",
        trace_id=trace_id,
        trigger_source=trigger_source,
        data={"ai_review_request_id": request.id, "request_status": request.status, "frozen_run_ids": frozen_range.run_ids},
    )


def build_review_package(*, ai_review_request_id: int, trace_id: str = "", trigger_source: str = TRIGGER_SOURCE_OPS_CONSOLE) -> ServiceResult:
    request = AIReviewRequest.objects.get(id=ai_review_request_id)
    effective_trace_id = trace_id or request.trace_id
    if request.status == AIReviewRequestStatus.BLOCKED:
        return _request_result(request, ResultStatus.BLOCKED, request.reason_code or "ai_review_request_blocked", request.reason_message)
    if not request.frozen_orchestration_run_ids:
        _mark_request_blocked(request, "empty_review_range", "复盘范围为空，不能构建数据包。")
        return _request_result(request, ResultStatus.BLOCKED, "empty_review_range", "复盘范围为空，不能构建数据包。")

    existing = request.packages.order_by("-created_at_utc").first()
    if existing is not None and existing.status == AIReviewPackageStatus.BUILT:
        request.active_package = existing
        if request.status not in {AIReviewRequestStatus.COMPLETED, AIReviewRequestStatus.UNKNOWN, AIReviewRequestStatus.FAILED}:
            request.status = AIReviewRequestStatus.PACKAGED
        request.save(update_fields=["active_package", "status", "updated_at_utc"])
        return _request_result(
            request,
            ResultStatus.SUCCEEDED,
            "ai_review_package_already_exists",
            "AIReviewPackage 已存在，已复用。",
            {"ai_review_package_id": existing.id},
        )

    request.status = AIReviewRequestStatus.PACKAGING
    request.save(update_fields=["status", "updated_at_utc"])
    try:
        payload = build_package_payload(request)
        sanitized_payload = sanitize_mapping(payload)
        payload_bytes = json_bytes(sanitized_payload)
        max_bytes = int(getattr(settings, "AI_REVIEW_MAX_PACKAGE_BYTES", 200000))
        if len(payload_bytes) > max_bytes:
            _mark_request_blocked(request, "review_package_too_large", "AIReviewPackage 超过大小上限，建议缩小复盘范围或使用摘要模式。")
            _alert(
                event_type="ai_review_package_blocked",
                request=request,
                severity=AlertSeverity.WARNING,
                reason_code="review_package_too_large",
                message="AIReviewPackage 过大，已阻断。",
                payload={"payload_size_bytes": len(payload_bytes), "max_bytes": max_bytes},
            )
            return _request_result(request, ResultStatus.BLOCKED, "review_package_too_large", request.reason_message)

        package_hash = stable_hash(sanitized_payload)
        input_refs_hash = stable_hash({"run_ids": request.frozen_orchestration_run_ids, "range_hash": request.frozen_range_hash})
        with transaction.atomic():
            package, _created = AIReviewPackage.objects.get_or_create(
                review_request=request,
                package_hash=package_hash,
                defaults={
                    "status": AIReviewPackageStatus.BUILT,
                    "package_format": "json",
                    "data_schema_version": getattr(settings, "AI_REVIEW_DATA_SCHEMA_VERSION", "1.0"),
                    "sanitization_version": getattr(settings, "AI_REVIEW_SANITIZATION_VERSION", "1.0"),
                    "input_refs_hash": input_refs_hash,
                    "run_count": len(sanitized_payload["orchestration_runs"]),
                    "order_count": int(sanitized_payload["counts"]["orders"]),
                    "alert_count": int(sanitized_payload["counts"]["alerts"]),
                    "runtime_issue_count": int(sanitized_payload["counts"]["runtime_issues"]),
                    "performance_record_count": int(sanitized_payload["counts"]["performance_records"]),
                    "payload_size_bytes": len(payload_bytes),
                    "input_size_estimate": len(payload_bytes),
                    "sanitized": True,
                    "sanitization_report": {"version": getattr(settings, "AI_REVIEW_SANITIZATION_VERSION", "1.0"), "sensitive_values_removed": True},
                    "json_payload": sanitized_payload,
                    "markdown_summary": package_markdown_summary(sanitized_payload),
                    "trace_id": effective_trace_id,
                },
            )
            request.active_package = package
            request.status = AIReviewRequestStatus.PACKAGED
            request.input_size_estimate = package.input_size_estimate
            request.reason_code = ""
            request.reason_message = ""
            request.save(update_fields=["active_package", "status", "input_size_estimate", "reason_code", "reason_message", "updated_at_utc"])
            _alert(
                event_type="ai_review_package_built",
                request=request,
                severity=AlertSeverity.INFO,
                reason_code="ai_review_package_built",
                message="AIReviewPackage 已构建。",
                payload={"package_id": package.id, "run_count": package.run_count, "payload_size_bytes": package.payload_size_bytes},
            )
    except Exception as exc:  # noqa: BLE001 - package build failure must be isolated from trading flow.
        request.status = AIReviewRequestStatus.FAILED
        request.reason_code = "ai_review_package_build_failed"
        request.reason_message = type(exc).__name__[:500]
        request.save(update_fields=["status", "reason_code", "reason_message", "updated_at_utc"])
        _alert(
            event_type="ai_review_package_failed",
            request=request,
            severity=AlertSeverity.WARNING,
            reason_code=request.reason_code,
            message="AIReviewPackage 构建失败。",
            payload={"error": type(exc).__name__},
        )
        return _request_result(request, ResultStatus.FAILED, request.reason_code, request.reason_message)

    return _request_result(
        request,
        ResultStatus.SUCCEEDED,
        "ai_review_package_built",
        "AIReviewPackage 已构建。",
        {"ai_review_package_id": package.id, "package_hash": package.package_hash},
    )


def run_ai_review(
    *,
    ai_review_request_id: int,
    gateway: DeepSeekReviewGateway | None = None,
    trace_id: str = "",
    trigger_source: str = TRIGGER_SOURCE_OPS_CONSOLE,
) -> ServiceResult:
    request = AIReviewRequest.objects.get(id=ai_review_request_id)
    if request.status == AIReviewRequestStatus.COMPLETED:
        return _request_result(request, ResultStatus.NO_ACTION, "ai_review_already_completed", "AIReviewRequest 已完成。")
    if request.status == AIReviewRequestStatus.UNKNOWN:
        return _request_result(request, ResultStatus.BLOCKED, "ai_review_unknown_not_retriable", "未知状态的 AIReviewRequest 不自动重试。")
    if request.status in {AIReviewRequestStatus.BLOCKED, AIReviewRequestStatus.FAILED, AIReviewRequestStatus.CANCELED}:
        return _request_result(request, _result_status_for_request(request), request.reason_code, request.reason_message)

    package = request.active_package
    if package is None:
        package_result = build_review_package(ai_review_request_id=request.id, trace_id=trace_id or request.trace_id, trigger_source=trigger_source)
        if package_result.status != ResultStatus.SUCCEEDED:
            return package_result
        request.refresh_from_db()
        package = request.active_package
    if package is None:
        return _request_result(request, ResultStatus.FAILED, "ai_review_package_missing", "AIReviewPackage 缺失。")

    with transaction.atomic():
        locked_request = AIReviewRequest.objects.select_for_update().get(id=request.id)
        if locked_request.status == AIReviewRequestStatus.CALLING_MODEL:
            return _request_result(locked_request, ResultStatus.BLOCKED, "ai_review_request_already_calling", "AIReviewRequest 正在调用模型。")
        sequence = (locked_request.attempts.order_by("-attempt_sequence").values_list("attempt_sequence", flat=True).first() or 0) + 1
        attempt = AIReviewAttempt.objects.create(
            review_request=locked_request,
            review_package=package,
            attempt_sequence=sequence,
            gateway_status="not_called",
            status=AIReviewAttemptStatus.CALLING,
            provider="deepseek",
            model_profile_code=locked_request.model_profile_code,
            prompt_hash=locked_request.prompt_hash,
            input_package_hash=package.package_hash,
            idempotency_key=stable_hash({"request_id": locked_request.id, "package_hash": package.package_hash, "attempt": sequence}),
            started_at_utc=timezone.now(),
            trace_id=trace_id or locked_request.trace_id,
        )
        locked_request.status = AIReviewRequestStatus.CALLING_MODEL
        locked_request.attempt_count = sequence
        locked_request.save(update_fields=["status", "attempt_count", "updated_at_utc"])

    messages = build_prompt_messages(request=locked_request, package=package)
    try:
        gateway_result = (gateway or HttpDeepSeekReviewGateway()).generate_review_completion(
            context=DeepSeekGatewayCallContext(
                purpose=PURPOSE_AI_REVIEW,
                caller_module=CALLER_AI_REVIEW_SERVICE,
                review_mode=locked_request.review_mode,
                input_package_hash=package.package_hash,
                prompt_hash=locked_request.prompt_hash,
                model_profile_code=locked_request.model_profile_code,
                idempotency_key=attempt.idempotency_key,
                trace_id=trace_id or locked_request.trace_id,
                trigger_source=trigger_source,
                operator_id=locked_request.requested_by,
                business_object_type="AIReviewRequest",
                business_object_id=str(locked_request.id),
            ),
            model_profile_code=locked_request.model_profile_code,
            messages=messages,
            response_format={"type": "json_object"},
            max_output_tokens=int(getattr(settings, "DEEPSEEK_MAX_OUTPUT_TOKENS", 4096)),
        )
    except Exception as exc:  # noqa: BLE001 - unexpected gateway errors must not leave AIReview stuck in calling_model.
        with transaction.atomic():
            failed_request = AIReviewRequest.objects.select_for_update().get(id=locked_request.id)
            failed_attempt = AIReviewAttempt.objects.select_for_update().get(id=attempt.id)
            failed_attempt.status = AIReviewAttemptStatus.FAILED
            failed_attempt.gateway_status = "gateway_exception"
            failed_attempt.error_code = "deepseek_gateway_exception"
            failed_attempt.error_message = type(exc).__name__[:500]
            failed_attempt.finished_at_utc = timezone.now()
            if failed_attempt.started_at_utc:
                failed_attempt.duration_ms = max(0, int((failed_attempt.finished_at_utc - failed_attempt.started_at_utc).total_seconds() * 1000))
            failed_attempt.save()
            failed_request.status = AIReviewRequestStatus.FAILED
            failed_request.reason_code = "deepseek_gateway_exception"
            failed_request.reason_message = type(exc).__name__[:500]
            failed_request.save(update_fields=["status", "reason_code", "reason_message", "updated_at_utc"])
            _alert(
                "ai_review_failed",
                failed_request,
                AlertSeverity.WARNING,
                failed_request.reason_code,
                "DeepSeekGateway 调用异常，AIReview 已失败收尾。",
                {"attempt_id": failed_attempt.id, "error": type(exc).__name__},
            )
        return _request_result(failed_request, ResultStatus.FAILED, failed_request.reason_code, failed_request.reason_message, {"ai_review_attempt_id": failed_attempt.id})
    return persist_gateway_result(request_id=locked_request.id, attempt_id=attempt.id, gateway_result=gateway_result, trigger_source=trigger_source)


def persist_gateway_result(
    *,
    request_id: int,
    attempt_id: int,
    gateway_result: DeepSeekGatewayResult,
    trigger_source: str,
) -> ServiceResult:
    with transaction.atomic():
        request = AIReviewRequest.objects.select_for_update().get(id=request_id)
        attempt = AIReviewAttempt.objects.select_for_update().get(id=attempt_id)
        package = attempt.review_package
        usage = gateway_result.token_usage or {}
        attempt.gateway_status = gateway_result.status
        attempt.request_sent = gateway_result.request_sent
        attempt.http_status = gateway_result.http_status
        attempt.retryable = gateway_result.retryable
        attempt.attempt_count_in_gateway = gateway_result.attempt_count
        attempt.input_token_count = int(usage.get("prompt_tokens") or usage.get("input_tokens") or 0)
        attempt.output_token_count = int(usage.get("completion_tokens") or usage.get("output_tokens") or 0)
        attempt.total_token_count = int(usage.get("total_tokens") or 0)
        attempt.error_code = gateway_result.error_category[:120]
        attempt.error_message = gateway_result.sanitized_error_message[:500]
        attempt.sanitized_model_profile_summary = gateway_result.profile_summary
        attempt.api_format = str(gateway_result.profile_summary.get("api_format", ""))[:80]
        attempt.sanitized_request_summary = gateway_result.sanitized_request_summary
        attempt.sanitized_response_summary = gateway_result.sanitized_response_summary
        attempt.finished_at_utc = timezone.now()
        if attempt.started_at_utc:
            attempt.duration_ms = max(0, int((attempt.finished_at_utc - attempt.started_at_utc).total_seconds() * 1000))

        if gateway_result.success and gateway_result.status == STATUS_SUCCEEDED:
            parsed = parse_model_output(gateway_result.output_text)
            if parsed is None:
                attempt.status = AIReviewAttemptStatus.RESPONSE_PARSE_ERROR
                request.status = AIReviewRequestStatus.FAILED
                request.reason_code = "ai_review_output_parse_failed"
                request.reason_message = "模型输出不是可解析的结构化 JSON，未创建报告。"
                attempt.save()
                request.save(update_fields=["status", "reason_code", "reason_message", "updated_at_utc"])
                _alert("ai_review_failed", request, AlertSeverity.WARNING, request.reason_code, request.reason_message, {"attempt_id": attempt.id})
                return _request_result(request, ResultStatus.FAILED, request.reason_code, request.reason_message)

            attempt.status = AIReviewAttemptStatus.SUCCEEDED
            report = create_report_from_output(request=request, attempt=attempt, package=package, parsed=parsed, raw_output=gateway_result.output_text)
            request.status = AIReviewRequestStatus.COMPLETED
            request.completed_report = report
            request.reason_code = ""
            request.reason_message = ""
            request.input_token_count = attempt.input_token_count
            request.output_token_count = attempt.output_token_count
            request.total_token_count = attempt.total_token_count
            request.save(
                update_fields=[
                    "status",
                    "completed_report",
                    "reason_code",
                    "reason_message",
                    "input_token_count",
                    "output_token_count",
                    "total_token_count",
                    "updated_at_utc",
                ]
            )
            attempt.save()
            _alert("ai_review_completed", request, AlertSeverity.INFO, "ai_review_completed", "AIReview 已完成。", {"report_id": report.id, "attempt_id": attempt.id})
            return _request_result(
                request,
                ResultStatus.SUCCEEDED,
                "ai_review_completed",
                "AIReview 已完成。",
                {"ai_review_report_id": report.id, "ai_review_attempt_id": attempt.id},
            )

        if gateway_result.status == STATUS_UNKNOWN_AFTER_SEND or (gateway_result.status == STATUS_TIMEOUT and gateway_result.request_sent):
            attempt.status = AIReviewAttemptStatus.UNKNOWN
            request.status = AIReviewRequestStatus.UNKNOWN
            request.reason_code = "deepseek_gateway_unknown"
            request.reason_message = "DeepSeekGateway 请求已发送或无法确认是否发送，结果未知，不自动重试。"
            result_status = ResultStatus.UNKNOWN
            event_type = "ai_review_unknown"
            severity = AlertSeverity.WARNING
        else:
            attempt.status = AIReviewAttemptStatus.FAILED
            request.status = AIReviewRequestStatus.FAILED
            request.reason_code = gateway_result.error_category or "deepseek_gateway_failed"
            request.reason_message = gateway_result.sanitized_error_message or "DeepSeekGateway 调用失败。"
            result_status = ResultStatus.FAILED
            event_type = "ai_review_failed"
            severity = AlertSeverity.WARNING
        attempt.save()
        request.save(update_fields=["status", "reason_code", "reason_message", "updated_at_utc"])
        _alert(event_type, request, severity, request.reason_code, request.reason_message, {"attempt_id": attempt.id, "gateway_status": gateway_result.status})
        return _request_result(request, result_status, request.reason_code, request.reason_message, {"ai_review_attempt_id": attempt.id})


def update_suggestion_status(
    *,
    suggestion_id: int,
    new_status: str,
    operator_id: str,
    decision_note: str,
    trace_id: str,
    trigger_source: str = TRIGGER_SOURCE_OPS_CONSOLE,
) -> ServiceResult:
    normalized_status = str(new_status or "").strip()
    normalized_note = str(decision_note or "").strip()
    if normalized_status not in VALID_SUGGESTION_STATUSES:
        return _service_blocked("invalid_suggestion_status", "未知 AIReviewSuggestion 状态。", trace_id, trigger_source)
    if normalized_status != AIReviewSuggestionStatus.PENDING_REVIEW and not normalized_note:
        return _service_blocked("suggestion_decision_note_required", "更新建议状态必须填写人工决策说明。", trace_id, trigger_source)
    suggestion = AIReviewSuggestion.objects.select_related("review_report__review_request").get(id=suggestion_id)
    before = {"status": suggestion.status, "decision_note": suggestion.decision_note}
    suggestion.status = normalized_status
    suggestion.reviewed_by = str(operator_id or "")[:120]
    suggestion.reviewed_at_utc = timezone.now()
    suggestion.decision_note = normalized_note[:500]
    suggestion.trace_id = trace_id or suggestion.trace_id
    suggestion.save(update_fields=["status", "reviewed_by", "reviewed_at_utc", "decision_note", "trace_id", "updated_at_utc"])
    record_audit(
        operator_id=str(operator_id or "")[:120],
        operation_type="ai_review_suggestion_status_update",
        target_object_type="AIReviewSuggestion",
        target_object_id=str(suggestion.id),
        before_state_summary=before,
        after_state_summary={"status": suggestion.status, "decision_note": suggestion.decision_note},
        reason=normalized_note or "更新 AIReviewSuggestion 状态。",
        evidence={"review_report_id": suggestion.review_report_id},
        result="succeeded",
        trace_id=trace_id,
        trigger_source=trigger_source,
    )
    _alert(
        "ai_review_suggestion_status_changed",
        suggestion.review_report.review_request,
        AlertSeverity.INFO,
        "ai_review_suggestion_status_changed",
        "AIReviewSuggestion 人工状态已更新。",
        {"suggestion_id": suggestion.id, "status": suggestion.status},
    )
    return ServiceResult(
        status=ResultStatus.SUCCEEDED,
        reason_code="ai_review_suggestion_status_updated",
        message="AIReviewSuggestion 状态已更新；不会自动执行建议内容。",
        trace_id=trace_id,
        trigger_source=trigger_source,
        data={"suggestion_id": suggestion.id, "status": suggestion.status},
    )


def freeze_review_range(*, range_selector: dict[str, Any], filters: dict[str, Any]) -> FrozenRange:
    if not isinstance(range_selector, dict):
        return FrozenRange([], "invalid_review_range", "复盘范围选择器必须是对象。")
    if not isinstance(filters, dict):
        return FrozenRange([], "invalid_review_filter", "复盘过滤条件必须是对象。")
    selector_type = str((range_selector or {}).get("type", RECENT_RUN_SELECTOR))
    include_manual = bool((range_selector or {}).get("include_manual_diagnostic", False))
    max_runs = int(getattr(settings, "AI_REVIEW_MAX_RUNS_PER_REQUEST", 100))
    query = OrchestrationRun.objects.all()
    if not include_manual:
        query = query.filter(trigger_mode=OrchestrationTriggerMode.AUTOMATIC)

    if selector_type == RECENT_RUN_SELECTOR:
        try:
            limit = int((range_selector or {}).get("limit", 20))
        except (TypeError, ValueError):
            return FrozenRange([], "invalid_review_range", "最近运行范围 limit 必须是数字。")
        if limit not in ALLOWED_RECENT_LIMITS:
            return FrozenRange([], "invalid_review_range", "最近运行范围只允许 20、50 或 100。")
        if limit > max_runs:
            return FrozenRange([], "review_range_too_large", "复盘范围超过最大 run 数。")
        query = query.order_by("-scheduled_for_utc", "-id")[:limit]
        run_ids = sorted([run.id for run in query])
    elif selector_type == RUN_IDS_SELECTOR:
        raw_ids = (range_selector or {}).get("ids", [])
        if not isinstance(raw_ids, list):
            return FrozenRange([], "invalid_review_range", "显式 run_ids 范围必须是列表。")
        parsed_ids: set[int] = set()
        for item in raw_ids:
            try:
                parsed_id = int(str(item).strip())
            except (TypeError, ValueError):
                return FrozenRange([], "invalid_review_range", "显式 run_ids 只能包含正整数。")
            if parsed_id <= 0:
                return FrozenRange([], "invalid_review_range", "显式 run_ids 只能包含正整数。")
            parsed_ids.add(parsed_id)
        unique_ids = sorted(parsed_ids)
        if len(unique_ids) > max_runs:
            return FrozenRange([], "review_range_too_large", "复盘范围超过最大 run 数。")
        run_ids = list(query.filter(id__in=unique_ids).order_by("scheduled_for_utc", "id").values_list("id", flat=True))
    elif selector_type == UTC_TIME_RANGE_SELECTOR:
        start = parse_utc((range_selector or {}).get("start_utc"))
        end = parse_utc((range_selector or {}).get("end_utc"))
        if start is None or end is None or start >= end:
            return FrozenRange([], "invalid_review_time_range", "UTC 时间范围不合法。")
        run_ids = list(query.filter(scheduled_for_utc__gte=start, scheduled_for_utc__lt=end).order_by("scheduled_for_utc", "id").values_list("id", flat=True)[:max_runs])
    else:
        return FrozenRange([], "invalid_review_range", "未知复盘范围选择器。")

    run_ids = apply_run_filters(run_ids, filters or {})
    if not run_ids:
        return FrozenRange([], "empty_review_range", "复盘范围为空。")
    if len(run_ids) > max_runs:
        return FrozenRange([], "review_range_too_large", "复盘范围超过最大 run 数。")
    return FrozenRange(run_ids)


def apply_run_filters(run_ids: list[int], filters: dict[str, Any]) -> list[int]:
    if not filters:
        return run_ids
    query = OrchestrationRun.objects.filter(id__in=run_ids)
    if filters.get("only_problem_runs"):
        query = query.filter(status__in=PROBLEM_RUN_STATUSES)
    if filters.get("only_with_runtime_guard_issue"):
        trace_ids = list(query.values_list("trace_id", flat=True))
        issue_trace_ids = set(RuntimeGuardIssue.objects.filter(related_trace_id__in=trace_ids).values_list("related_trace_id", flat=True))
        query = query.filter(trace_id__in=issue_trace_ids)
    if filters.get("only_with_orders"):
        run_ids_with_order_links = OrchestrationBusinessObjectLink.objects.filter(
            orchestration_run_id__in=run_ids,
            object_type__in=["OrderSubmissionAttempt", "CandidateOrderIntent", "ApprovedOrderIntent", "PreparedOrderIntent"],
        ).values_list("orchestration_run_id", flat=True)
        query = query.filter(id__in=list(run_ids_with_order_links))
    return list(query.order_by("scheduled_for_utc", "id").values_list("id", flat=True))


def build_package_payload(request: AIReviewRequest) -> dict[str, Any]:
    runs = list(OrchestrationRun.objects.filter(id__in=request.frozen_orchestration_run_ids).order_by("scheduled_for_utc", "id"))
    run_ids = [run.id for run in runs]
    step_runs = OrchestrationStepRun.objects.filter(orchestration_run_id__in=run_ids).order_by("orchestration_run_id", "execution_sequence")
    links = OrchestrationBusinessObjectLink.objects.filter(orchestration_run_id__in=run_ids).order_by("orchestration_run_id", "step_code", "id")
    trace_ids = [run.trace_id for run in runs]
    performances = OrchestrationRunPerformance.objects.filter(end_orchestration_run_id__in=run_ids).order_by("period_end_utc")
    runtime_issues = RuntimeGuardIssue.objects.filter(related_trace_id__in=trace_ids).order_by("created_at_utc")
    alerts = _alert_query_for_runs(runs)
    order_ids = _order_attempt_ids_from_links(links)
    order_attempts = OrderSubmissionAttempt.objects.filter(id__in=order_ids).order_by("id") if order_ids else OrderSubmissionAttempt.objects.none()
    fills = TradeFill.objects.filter(order_submission_attempt_id__in=order_ids).order_by("id") if order_ids else TradeFill.objects.none()
    summaries = OrderFillSummary.objects.filter(order_submission_attempt_id__in=order_ids).order_by("id") if order_ids else OrderFillSummary.objects.none()
    return {
        "request": {
            "id": request.id,
            "request_key": request.request_key,
            "review_mode": request.review_mode,
            "manual_question": request.manual_question,
            "model_profile_code": request.model_profile_code,
            "created_at_utc": request.created_at_utc.isoformat() if request.created_at_utc else "",
        },
        "range": {
            "selector": request.range_selector,
            "filters": request.filters,
            "frozen_orchestration_run_ids": run_ids,
            "frozen_range_hash": request.frozen_range_hash,
        },
        "orchestration_runs": [_run_summary(run) for run in runs],
        "step_runs": [_step_summary(step) for step in step_runs],
        "business_object_links": [_link_summary(link) for link in links],
        "orders": [_order_summary(order) for order in order_attempts],
        "fills": [_fill_summary(fill) for fill in fills],
        "fill_summaries": [_fill_summary_summary(summary) for summary in summaries],
        "performance_records": [_performance_summary(performance) for performance in performances],
        "runtime_issues": [_runtime_issue_summary(issue) for issue in runtime_issues],
        "alerts": [_alert_summary(alert) for alert in alerts],
        "counts": {
            "runs": len(runs),
            "steps": step_runs.count(),
            "business_object_links": links.count(),
            "orders": order_attempts.count(),
            "fills": fills.count(),
            "performance_records": performances.count(),
            "runtime_issues": runtime_issues.count(),
            "alerts": alerts.count(),
        },
    }


def build_prompt_messages(*, request: AIReviewRequest, package: AIReviewPackage) -> list[dict[str, str]]:
    system = (
        "你是离线交易系统复盘助手。只能基于输入数据包做复盘分析；"
        "不得输出可直接执行的实时交易指令；不得要求绕过风控；"
        "所有建议必须进入人工审核。请只输出 JSON。"
    )
    user = json.dumps(
        {
            "review_mode": request.review_mode,
            "manual_question": request.manual_question,
            "expected_output": {
                "report_title": "string",
                "executive_summary": "string",
                "key_findings": "list",
                "suggestions": "list",
                "data_limitations": "list",
                "confidence": "0-1",
            },
            "package": package.json_payload,
        },
        ensure_ascii=False,
        sort_keys=True,
        default=str,
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def parse_model_output(output_text: str) -> dict[str, Any] | None:
    try:
        parsed = json.loads(output_text)
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, dict):
        return None
    if not (parsed.get("report_title") or parsed.get("title")):
        return None
    if not (parsed.get("executive_summary") or parsed.get("summary")):
        return None
    return sanitize_mapping(parsed)


def create_report_from_output(*, request: AIReviewRequest, attempt: AIReviewAttempt, package: AIReviewPackage, parsed: dict[str, Any], raw_output: str) -> AIReviewReport:
    if hasattr(request, "report"):
        return request.report
    report = AIReviewReport.objects.create(
        review_request=request,
        review_attempt=attempt,
        review_package=package,
        title=str(parsed.get("report_title") or parsed.get("title") or "AIReview Report")[:300],
        summary=str(parsed.get("executive_summary") or parsed.get("summary") or "")[:4000],
        full_report_markdown=str(parsed.get("full_report_markdown") or parsed.get("markdown") or parsed.get("executive_summary") or ""),
        structured_report_json=parsed,
        review_mode=request.review_mode,
        model_provider="deepseek",
        model_profile_code=request.model_profile_code,
        model_name="",
        prompt_name=request.prompt_name,
        prompt_version=request.prompt_version,
        prompt_hash=request.prompt_hash,
        package_hash=package.package_hash,
        output_hash=stable_hash({"output": raw_output}),
        confidence=decimal_from_value(parsed.get("confidence")),
        data_limitations=normalize_list(parsed.get("data_limitations")),
        trace_id=request.trace_id,
    )
    for item in normalize_list(parsed.get("key_findings") or parsed.get("findings")):
        create_finding(report=report, item=item)
    for item in normalize_list(parsed.get("suggestions")):
        create_suggestion(report=report, item=item)
    return report


def create_finding(*, report: AIReviewReport, item: Any) -> None:
    payload = item if isinstance(item, dict) else {"description": str(item)}
    severity = str(payload.get("severity") or AIReviewFindingSeverity.INFO)
    if severity not in {choice.value for choice in AIReviewFindingSeverity}:
        severity = AIReviewFindingSeverity.INFO
    AIReviewFinding.objects.create(
        review_report=report,
        finding_type=str(payload.get("finding_type") or "other")[:120],
        severity=severity,
        title=str(payload.get("title") or payload.get("finding_type") or "AIReview finding")[:300],
        description=str(payload.get("description") or "")[:4000],
        evidence_refs=normalize_list(payload.get("evidence_refs")),
        related_orchestration_run_ids=normalize_list(payload.get("related_run_ids") or payload.get("related_orchestration_run_ids")),
        related_order_submission_attempt_ids=normalize_list(payload.get("related_order_ids") or payload.get("related_order_submission_attempt_ids")),
        related_object_refs=normalize_list(payload.get("related_object_refs")),
        confidence=decimal_from_value(payload.get("confidence")),
        needs_manual_attention=bool(payload.get("needs_manual_attention") or severity in {AIReviewFindingSeverity.HIGH, AIReviewFindingSeverity.CRITICAL}),
        trace_id=report.trace_id,
    )


def create_suggestion(*, report: AIReviewReport, item: Any) -> None:
    payload = item if isinstance(item, dict) else {"description": str(item)}
    AIReviewSuggestion.objects.create(
        review_report=report,
        suggestion_type=str(payload.get("suggestion_type") or "other")[:120],
        priority=str(payload.get("priority") or "")[:40],
        title=str(payload.get("title") or payload.get("suggestion_type") or "AIReview suggestion")[:300],
        description=str(payload.get("description") or "")[:4000],
        target_area=str(payload.get("target_area") or "")[:120],
        target_object_type=str(payload.get("target_object_type") or "")[:120],
        target_object_id=str(payload.get("target_object_id") or "")[:120],
        suggested_action=str(payload.get("suggested_action") or "")[:4000],
        rationale=str(payload.get("rationale") or "")[:4000],
        expected_impact=str(payload.get("expected_impact") or "")[:4000],
        risk_note=str(payload.get("risk_note") or "")[:4000],
        status=AIReviewSuggestionStatus.PENDING_REVIEW,
        trace_id=report.trace_id,
    )


def prompt_metadata(review_mode: str) -> dict[str, str]:
    prompt_version = getattr(settings, "AI_REVIEW_PROMPT_VERSION", "p0_v1")
    prompt_schema_version = getattr(settings, "AI_REVIEW_PROMPT_SCHEMA_VERSION", "1.0")
    output_schema_version = getattr(settings, "AI_REVIEW_OUTPUT_SCHEMA_VERSION", "1.0")
    prompt_name = f"{PROMPT_NAME_PREFIX}_{review_mode}"
    prompt_summary = {
        "prompt_name": prompt_name,
        "prompt_version": prompt_version,
        "prompt_schema_version": prompt_schema_version,
        "output_schema_version": output_schema_version,
        "review_mode": review_mode,
        "rules": [
            "offline_review_only",
            "no_realtime_trade_instruction",
            "human_review_required_for_suggestions",
        ],
    }
    return {
        "prompt_name": prompt_name,
        "prompt_version": prompt_version,
        "prompt_schema_version": prompt_schema_version,
        "output_schema_version": output_schema_version,
        "prompt_hash": stable_hash(prompt_summary),
    }


def package_markdown_summary(payload: dict[str, Any]) -> str:
    return "\n".join(
        [
            f"# AIReview Package",
            f"- review_mode: {payload['request']['review_mode']}",
            f"- run_count: {payload['counts']['runs']}",
            f"- order_count: {payload['counts']['orders']}",
            f"- alert_count: {payload['counts']['alerts']}",
            f"- runtime_issue_count: {payload['counts']['runtime_issues']}",
            f"- performance_record_count: {payload['counts']['performance_records']}",
        ]
    )


def _run_summary(run: OrchestrationRun) -> dict[str, Any]:
    return {
        "id": run.id,
        "run_key": run.run_key,
        "pipeline_code": run.pipeline_code,
        "scheduled_for_utc": run.scheduled_for_utc.isoformat(),
        "cycle_kind": run.cycle_kind,
        "trigger_mode": run.trigger_mode,
        "status": run.status,
        "final_outcome": run.final_outcome,
        "reason_code": run.reason_code,
        "current_step_code": run.current_step_code,
        "last_completed_step_code": run.last_completed_step_code,
        "last_stopped_step_code": run.last_stopped_step_code,
        "needs_manual_attention": run.needs_manual_attention,
        "trace_id": run.trace_id,
    }


def _step_summary(step: OrchestrationStepRun) -> dict[str, Any]:
    return {
        "id": step.id,
        "orchestration_run_id": step.orchestration_run_id,
        "step_code": step.step_code,
        "module_code": step.module_code,
        "execution_sequence": step.execution_sequence,
        "status": step.status,
        "normalized_status": step.normalized_status,
        "flow_action": step.flow_action,
        "reason_code": step.reason_code,
        "primary_object_type": step.primary_object_type,
        "primary_object_id": step.primary_object_id,
        "needs_manual_attention": step.needs_manual_attention,
    }


def _link_summary(link: OrchestrationBusinessObjectLink) -> dict[str, Any]:
    return {
        "id": link.id,
        "orchestration_run_id": link.orchestration_run_id,
        "step_code": link.step_code,
        "module_code": link.module_code,
        "object_role": link.object_role,
        "object_type": link.object_type,
        "object_id": link.object_id,
        "object_label": link.object_label,
    }


def _order_summary(order: OrderSubmissionAttempt) -> dict[str, Any]:
    return {
        "id": order.id,
        "status": getattr(order, "status", ""),
        "exchange_order_id": getattr(order, "exchange_order_id", ""),
        "client_order_id": getattr(order, "client_order_id", ""),
        "symbol": getattr(order, "symbol", ""),
        "side": getattr(order, "side", ""),
        "quantity": str(getattr(order, "quantity", "")),
        "trace_id": getattr(order, "trace_id", ""),
    }


def _fill_summary(fill: TradeFill) -> dict[str, Any]:
    return {
        "id": fill.id,
        "order_submission_attempt_id": fill.order_submission_attempt_id,
        "exchange_trade_id": getattr(fill, "exchange_trade_id", ""),
        "price": str(getattr(fill, "price", "")),
        "quantity": str(getattr(fill, "quantity", "")),
        "commission": str(getattr(fill, "commission", "")),
    }


def _fill_summary_summary(summary: OrderFillSummary) -> dict[str, Any]:
    return {
        "id": summary.id,
        "order_submission_attempt_id": summary.order_submission_attempt_id,
        "fill_count": getattr(summary, "fill_count", 0),
        "total_quantity": str(getattr(summary, "total_quantity", "")),
        "total_quote_quantity": str(getattr(summary, "total_quote_quantity", "")),
        "average_price": str(getattr(summary, "average_price", "")),
    }


def _performance_summary(performance: OrchestrationRunPerformance) -> dict[str, Any]:
    return {
        "id": performance.id,
        "start_orchestration_run_id": performance.start_orchestration_run_id,
        "end_orchestration_run_id": performance.end_orchestration_run_id,
        "period_start_utc": performance.period_start_utc.isoformat(),
        "period_end_utc": performance.period_end_utc.isoformat(),
        "cycle_floating_pnl": str(performance.cycle_floating_pnl),
        "cycle_floating_pnl_pct": str(performance.cycle_floating_pnl_pct),
        "calculation_status": performance.calculation_status,
        "reason_code": performance.reason_code,
    }


def _runtime_issue_summary(issue: RuntimeGuardIssue) -> dict[str, Any]:
    return {
        "id": issue.id,
        "issue_type": issue.issue_type,
        "severity": issue.severity,
        "status": issue.status,
        "related_object_type": issue.related_object_type,
        "related_object_id": issue.related_object_id,
        "related_trace_id": issue.related_trace_id,
        "description_zh": issue.description_zh,
        "needs_manual_attention": issue.needs_manual_attention,
    }


def _alert_summary(alert: Any) -> dict[str, Any]:
    return {
        "id": alert.id,
        "event_type": alert.event_type,
        "event_category": alert.event_category,
        "severity": alert.severity,
        "business_status": alert.business_status,
        "reason_code": alert.reason_code,
        "related_object_type": alert.related_object_type,
        "related_object_id": alert.related_object_id,
        "trace_id": alert.trace_id,
    }


def _alert_query_for_runs(runs: list[OrchestrationRun]):
    from apps.alerts.models import AlertEvent

    trace_ids = [run.trace_id for run in runs]
    return AlertEvent.objects.filter(trace_id__in=trace_ids).order_by("created_at_utc")


def _order_attempt_ids_from_links(links) -> list[int]:
    order_ids: list[int] = []
    for link in links:
        if link.object_type == "OrderSubmissionAttempt" and str(link.object_id).isdigit():
            order_ids.append(int(link.object_id))
    return sorted(set(order_ids))


def parse_utc(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(UTC)


def stable_hash(payload: Any) -> str:
    return hashlib.sha256(json_bytes(payload)).hexdigest()


def json_bytes(payload: Any) -> bytes:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")


def decimal_from_value(value: Any) -> Decimal:
    try:
        decimal_value = Decimal(str(value if value is not None else "0"))
    except (InvalidOperation, ValueError):
        return Decimal("0")
    if not decimal_value.is_finite():
        return Decimal("0")
    if decimal_value < 0:
        return Decimal("0")
    if decimal_value > 1:
        return Decimal("1")
    return decimal_value


def normalize_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return [sanitize_value(item) for item in value]
    if value is None or value == "":
        return []
    return [sanitize_value(value)]


def _mark_request_blocked(request: AIReviewRequest, reason_code: str, reason_message: str) -> None:
    request.status = AIReviewRequestStatus.BLOCKED
    request.reason_code = reason_code
    request.reason_message = reason_message[:500]
    request.save(update_fields=["status", "reason_code", "reason_message", "updated_at_utc"])


def _request_result(
    request: AIReviewRequest,
    status: ResultStatus,
    reason_code: str,
    message: str,
    data: dict[str, Any] | None = None,
) -> ServiceResult:
    return ServiceResult(
        status=status,
        reason_code=reason_code,
        message=message,
        trace_id=request.trace_id,
        trigger_source=request.trigger_source,
        data={"ai_review_request_id": request.id, "request_status": request.status, **(data or {})},
    )


def _result_status_for_request(request: AIReviewRequest) -> ResultStatus:
    if request.status == AIReviewRequestStatus.COMPLETED:
        return ResultStatus.SUCCEEDED
    if request.status == AIReviewRequestStatus.BLOCKED:
        return ResultStatus.BLOCKED
    if request.status == AIReviewRequestStatus.UNKNOWN:
        return ResultStatus.UNKNOWN
    if request.status in {AIReviewRequestStatus.FAILED, AIReviewRequestStatus.CANCELED}:
        return ResultStatus.FAILED
    return ResultStatus.SUCCEEDED


def _service_blocked(reason_code: str, message: str, trace_id: str, trigger_source: str) -> ServiceResult:
    return ServiceResult(status=ResultStatus.BLOCKED, reason_code=reason_code, message=message, trace_id=trace_id, trigger_source=trigger_source)


def _alert(
    event_type: str,
    request: AIReviewRequest,
    severity: str,
    reason_code: str,
    message: str,
    payload: dict[str, Any],
) -> None:
    record_alert_event(
        event_key=stable_hash({"source": SOURCE_MODULE, "event_type": event_type, "request_id": request.id, "reason": reason_code, "payload": payload}),
        source_module=SOURCE_MODULE,
        event_type=event_type,
        event_category="ai_review",
        severity=severity,
        title_zh="AIReview 离线复盘事件",
        message_zh=message,
        trace_id=request.trace_id,
        trigger_source=request.trigger_source,
        related_object_type="AIReviewRequest",
        related_object_id=str(request.id),
        business_status=request.status,
        reason_code=reason_code,
        reason_message=message[:500],
        payload_summary=payload,
        evidence_refs=[],
        delivery_enabled=False,
    )
