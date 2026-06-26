"""OpsConsole 模块：Django JSON API 入口；调用 selector 与受控业务 service，不直接访问外部服务，不发送 Hermes，不直接调用大模型，不提交订单。"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from django.contrib.auth import authenticate, login, logout
from django.core.exceptions import ObjectDoesNotExist
from django.http import HttpRequest, JsonResponse
from django.middleware.csrf import get_token
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_POST

from apps.ai_review.services import build_review_package, create_review_request, run_ai_review, update_suggestion_status
from apps.binance_account_sync.services.sync import refresh_for_ops_console
from apps.fill_sync.services.sync import recover_order_fills
from apps.order_plan.services.active_lock import manual_closeout_active_lock
from apps.order_status_sync.services.status_sync import recover_order_status_once
from apps.performance_metrics.selectors import get_performance_record, list_performance_records
from apps.performance_metrics.services import backfill_missing_closed_period_performance, preview_missing_closed_period_performance
from apps.runtime_guard.services.guard import update_runtime_guard_issue_status

from .permissions import has_ops_permission, require_ops_permission
from .responses import error_response, ok_response
from .selectors import (
    OpsConsoleObjectNotFound,
    account_overview,
    dashboard_summary,
    get_alert_detail,
    get_ai_review_detail,
    get_order_detail,
    get_run_detail,
    get_runtime_guard_issue_detail,
    list_ai_review_requests,
    list_alerts,
    list_audit_log,
    list_orders,
    list_runtime_guard_issues,
    list_runs,
    real_trading_status,
)


def _json_object_body(request: HttpRequest) -> tuple[dict[str, Any] | None, JsonResponse | None]:
    try:
        body = json.loads(request.body.decode("utf-8") or "{}")
    except json.JSONDecodeError:
        return None, error_response(
            reason_code="ops_console_invalid_json",
            message_zh="请求体不是合法 JSON。",
            status=400,
        )
    if not isinstance(body, dict):
        return None, error_response(
            reason_code="ops_console_invalid_json_object",
            message_zh="请求体必须是 JSON object。",
            status=400,
        )
    return body, None


def _handle_selector(selector: Callable[..., Any], *args: Any, **kwargs: Any) -> JsonResponse:
    try:
        return ok_response(selector(*args, **kwargs))
    except OpsConsoleObjectNotFound:
        return error_response(
            reason_code="ops_console_object_not_found",
            message_zh="请求查看的对象不存在。",
            status=404,
        )


def _service_response(result: Any) -> JsonResponse:
    return ok_response(
        {
            "status": str(result.status),
            "reason_code": result.reason_code,
            "message": result.message,
            **result.data,
        },
        reason_code=result.reason_code,
    )


def _operator_id(request: HttpRequest) -> str:
    return str(getattr(request.user, "username", "") or request.user.id)


def _user_summary(user: Any) -> dict[str, Any]:
    return {
        "id": user.id,
        "username": getattr(user, "username", ""),
        "is_superuser": getattr(user, "is_superuser", False),
        "groups": list(user.groups.order_by("name").values_list("name", flat=True)),
    }


@csrf_exempt
@sensitive_post_parameters("password")
@require_POST
def auth_login_view(request: HttpRequest) -> JsonResponse:
    body, error = _json_object_body(request)
    if error is not None:
        return error
    assert body is not None
    username = str(body.get("username", "")).strip()
    password = str(body.get("password", ""))
    if not username or not password:
        return error_response(
            reason_code="ops_console_login_credentials_required",
            message_zh="请输入用户名和密码。",
            status=400,
        )

    user = authenticate(request, username=username, password=password)
    if user is None:
        return error_response(
            reason_code="ops_console_login_failed",
            message_zh="用户名或密码错误。",
            status=401,
        )
    if not has_ops_permission(user, "view_ops_console"):
        return error_response(
            reason_code="ops_console_permission_denied",
            message_zh="当前用户没有访问 OpsConsole 的权限。",
            status=403,
        )

    login(request, user)
    get_token(request)
    return ok_response(_user_summary(user), reason_code="ops_console_login_succeeded")


@require_POST
def auth_logout_view(request: HttpRequest) -> JsonResponse:
    if not request.user.is_authenticated:
        return error_response(
            reason_code="ops_console_login_required",
            message_zh="OpsConsole API 需要先登录。",
            status=401,
        )
    logout(request)
    return ok_response({"logged_out": True}, reason_code="ops_console_logout_succeeded")


@require_ops_permission("view_ops_console")
def auth_me_view(request: HttpRequest) -> JsonResponse:
    return ok_response(_user_summary(request.user), reason_code="ops_console_authenticated")


def _confirm_write_error(body: dict[str, Any], *, message_zh: str) -> JsonResponse | None:
    if body.get("confirm_write") is not True:
        return error_response(
            reason_code="ops_console_confirm_write_required",
            message_zh=message_zh,
            status=400,
        )
    return None


def _reason_or_error(body: dict[str, Any], *, message_zh: str) -> tuple[str, JsonResponse | None]:
    reason = str(body.get("reason", "")).strip()
    if not reason:
        return "", error_response(
            reason_code="ops_console_reason_required",
            message_zh=message_zh,
            status=400,
        )
    return reason, None


def _int_body_value(body: dict[str, Any], name: str) -> int | None:
    try:
        value = int(body.get(name))
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


@require_ops_permission("view_ops_console")
def dashboard_view(_request: HttpRequest) -> JsonResponse:
    return _handle_selector(dashboard_summary)


@require_ops_permission("view_ops_console")
def runs_view(request: HttpRequest) -> JsonResponse:
    return _handle_selector(list_runs, request.GET)


@require_ops_permission("view_ops_console")
def run_detail_view(_request: HttpRequest, run_id: int) -> JsonResponse:
    return _handle_selector(get_run_detail, run_id)


@require_ops_permission("view_ops_console")
def orders_view(request: HttpRequest) -> JsonResponse:
    return _handle_selector(list_orders, request.GET)


@require_ops_permission("view_ops_console")
def order_detail_view(_request: HttpRequest, attempt_id: int) -> JsonResponse:
    return _handle_selector(get_order_detail, attempt_id)


@require_ops_permission("controlled_order_status_recheck", methods=("POST",))
def order_status_recheck_view(request: HttpRequest, attempt_id: int) -> JsonResponse:
    body, error = _json_object_body(request)
    if error is not None:
        return error
    assert body is not None
    if confirm_error := _confirm_write_error(body, message_zh="订单状态受控补查会请求 Binance 并写入查询事实，必须显式 confirm_write=true。"):
        return confirm_error
    reason, reason_error = _reason_or_error(body, message_zh="订单状态受控补查需要填写原因。")
    if reason_error is not None:
        return reason_error
    result = recover_order_status_once(
        order_submission_attempt_id=attempt_id,
        operator_id=_operator_id(request),
        reason=reason,
        trace_id=str(body.get("trace_id", "")).strip() or f"ops-order-status-recheck-{request.user.id}",
        trigger_source="ops_console_order_status_recovery",
    )
    return _service_response(result)


@require_ops_permission("controlled_fill_sync", methods=("POST",))
def fill_sync_resync_view(request: HttpRequest, attempt_id: int) -> JsonResponse:
    body, error = _json_object_body(request)
    if error is not None:
        return error
    assert body is not None
    if confirm_error := _confirm_write_error(body, message_zh="成交受控补同步会请求 Binance 并写入成交事实，必须显式 confirm_write=true。"):
        return confirm_error
    reason, reason_error = _reason_or_error(body, message_zh="成交受控补同步需要填写原因。")
    if reason_error is not None:
        return reason_error
    terminal_record_id = _int_body_value(body, "terminal_order_status_sync_record_id")
    if terminal_record_id is None:
        return error_response(
            reason_code="terminal_order_status_sync_record_id_required",
            message_zh="成交受控补同步必须指定明确的终态 OrderStatusSyncRecord。",
            status=400,
        )
    result = recover_order_fills(
        order_submission_attempt_id=attempt_id,
        terminal_order_status_sync_record_id=terminal_record_id,
        operator_id=_operator_id(request),
        reason=reason,
        trace_id=str(body.get("trace_id", "")).strip() or f"ops-fill-sync-{request.user.id}",
        trigger_source="ops_console_fill_sync_recovery",
    )
    return _service_response(result)


@require_ops_permission("manual_active_lock_closeout", methods=("POST",))
def active_lock_closeout_view(request: HttpRequest, active_lock_id: int) -> JsonResponse:
    body, error = _json_object_body(request)
    if error is not None:
        return error
    assert body is not None
    if confirm_error := _confirm_write_error(body, message_zh="ActiveLock 人工收尾会改变锁状态，必须显式 confirm_write=true。"):
        return confirm_error
    reason, reason_error = _reason_or_error(body, message_zh="ActiveLock 人工收尾需要填写原因。")
    if reason_error is not None:
        return reason_error
    evidence = body.get("evidence", {})
    if not isinstance(evidence, dict) or not evidence:
        return error_response(
            reason_code="active_lock_closeout_evidence_required",
            message_zh="ActiveLock 人工收尾必须提交结构化证据。",
            status=400,
        )
    result = manual_closeout_active_lock(
        active_lock_id=active_lock_id,
        operator_id=_operator_id(request),
        reason=reason,
        evidence=evidence,
        trace_id=str(body.get("trace_id", "")).strip() or f"ops-active-lock-closeout-{request.user.id}",
        trigger_source="ops_console_active_lock_closeout",
    )
    return _service_response(result)


@require_ops_permission("view_ops_console")
def account_overview_view(_request: HttpRequest) -> JsonResponse:
    return _handle_selector(account_overview)


@require_ops_permission("refresh_account_overview", methods=("POST",))
def account_overview_refresh_view(request: HttpRequest) -> JsonResponse:
    body, error = _json_object_body(request)
    if error is not None:
        return error
    assert body is not None
    if confirm_error := _confirm_write_error(body, message_zh="刷新账户展示会请求 Binance 并写入 ops_display 快照，必须显式 confirm_write=true。"):
        return confirm_error
    reason, reason_error = _reason_or_error(body, message_zh="刷新账户展示需要填写操作原因。")
    if reason_error is not None:
        return reason_error
    result = refresh_for_ops_console(
        operator_id=_operator_id(request),
        reason=reason,
        trace_id=str(body.get("trace_id", "")).strip() or f"ops-account-refresh-{request.user.id}",
        trigger_source="ops_console_account_refresh",
    )
    return _service_response(result)


@require_ops_permission("view_ops_console")
def runtime_guard_issues_view(request: HttpRequest) -> JsonResponse:
    return _handle_selector(list_runtime_guard_issues, request.GET)


@require_ops_permission("view_ops_console")
def runtime_guard_issue_detail_view(_request: HttpRequest, issue_id: int) -> JsonResponse:
    return _handle_selector(get_runtime_guard_issue_detail, issue_id)


@require_ops_permission("manage_runtime_guard_issue", methods=("POST",))
def runtime_guard_issue_status_view(request: HttpRequest, issue_id: int) -> JsonResponse:
    body, error = _json_object_body(request)
    if error is not None:
        return error
    assert body is not None
    if confirm_error := _confirm_write_error(body, message_zh="RuntimeGuardIssue 状态操作会写入人工审计，必须显式 confirm_write=true。"):
        return confirm_error
    reason, reason_error = _reason_or_error(body, message_zh="RuntimeGuardIssue 状态操作需要填写原因。")
    if reason_error is not None:
        return reason_error
    try:
        result = update_runtime_guard_issue_status(
            issue_id=issue_id,
            new_status=str(body.get("new_status", "")),
            operator_id=_operator_id(request),
            reason=reason,
            trace_id=str(body.get("trace_id", "")).strip() or f"ops-runtime-guard-issue-{request.user.id}",
            trigger_source="ops_console_runtime_guard_issue",
        )
    except ObjectDoesNotExist:
        return error_response(
            reason_code="ops_console_object_not_found",
            message_zh="请求操作的 RuntimeGuardIssue 不存在。",
            status=404,
        )
    return _service_response(result)


@require_ops_permission("view_ops_console")
def alerts_view(request: HttpRequest) -> JsonResponse:
    return _handle_selector(list_alerts, request.GET)


@require_ops_permission("view_ops_console")
def alert_detail_view(_request: HttpRequest, alert_id: int) -> JsonResponse:
    return _handle_selector(get_alert_detail, alert_id)


@require_ops_permission("view_ops_console")
def real_trading_view(_request: HttpRequest) -> JsonResponse:
    return _handle_selector(real_trading_status)


@require_ops_permission("view_ops_console")
def audit_log_view(request: HttpRequest) -> JsonResponse:
    return _handle_selector(list_audit_log, request.GET)


@require_ops_permission("view_ops_console")
def performance_records_view(request: HttpRequest) -> JsonResponse:
    return _handle_selector(list_performance_records, request.GET)


@require_ops_permission("view_ops_console")
def performance_record_detail_view(_request: HttpRequest, performance_id: int) -> JsonResponse:
    record = get_performance_record(performance_id)
    if record is None:
        return error_response(
            reason_code="ops_console_object_not_found",
            message_zh="请求查看的绩效复盘结果不存在。",
            status=404,
        )
    return ok_response(record)


@require_ops_permission("view_ops_console")
def performance_preview_view(_request: HttpRequest) -> JsonResponse:
    return ok_response(preview_missing_closed_period_performance())


@require_ops_permission("backfill_performance_metrics", methods=("POST",))
def performance_backfill_view(request: HttpRequest) -> JsonResponse:
    try:
        body = json.loads(request.body.decode("utf-8") or "{}")
    except json.JSONDecodeError:
        return error_response(
            reason_code="ops_console_invalid_json",
            message_zh="请求体不是合法 JSON。",
            status=400,
        )
    if body.get("confirm_write") is not True:
        return error_response(
            reason_code="performance_backfill_confirm_write_required",
            message_zh="绩效补算会写入复盘结果，必须显式 confirm_write=true。",
            status=400,
        )
    reason = str(body.get("reason", "")).strip()
    if not reason:
        return error_response(
            reason_code="performance_backfill_reason_required",
            message_zh="绩效补算需要填写操作原因。",
            status=400,
        )
    trace_id = str(body.get("trace_id", "")).strip() or f"ops-performance-{request.user.id}"
    result = backfill_missing_closed_period_performance(
        operator_id=str(getattr(request.user, "username", "") or request.user.id),
        reason=reason,
        trace_id=trace_id,
    )
    return ok_response(
        {
            "status": str(result.status),
            "reason_code": result.reason_code,
            "message": result.message,
            **result.data,
        },
        reason_code=result.reason_code,
    )


@require_ops_permission("view_ops_console")
def ai_review_requests_view(request: HttpRequest) -> JsonResponse:
    return _handle_selector(list_ai_review_requests, request.GET)


@require_ops_permission("view_ops_console")
def ai_review_request_detail_view(_request: HttpRequest, request_id: int) -> JsonResponse:
    return _handle_selector(get_ai_review_detail, request_id)


@require_ops_permission("manage_ai_review", methods=("POST",))
def ai_review_create_request_view(request: HttpRequest) -> JsonResponse:
    body, error = _json_object_body(request)
    if error is not None:
        return error
    assert body is not None
    result = create_review_request(
        review_mode=str(body.get("review_mode", "")),
        range_selector=body.get("range_selector", {}),
        filters=body.get("filters", {}),
        manual_question=str(body.get("manual_question", "")),
        model_profile_code=str(body.get("model_profile_code", "")),
        requested_by=_operator_id(request),
        request_key=str(body.get("request_key", "")),
        trace_id=str(body.get("trace_id", "")).strip() or f"ops-ai-review-{request.user.id}",
        trigger_source="ops_console_ai_review",
    )
    return _service_response(result)


@require_ops_permission("manage_ai_review", methods=("POST",))
def ai_review_build_package_view(request: HttpRequest, request_id: int) -> JsonResponse:
    body, error = _json_object_body(request)
    if error is not None:
        return error
    assert body is not None
    try:
        result = build_review_package(
            ai_review_request_id=request_id,
            trace_id=str(body.get("trace_id", "")).strip(),
            trigger_source="ops_console_ai_review",
        )
    except ObjectDoesNotExist:
        return error_response(
            reason_code="ops_console_object_not_found",
            message_zh="请求操作的 AIReviewRequest 不存在。",
            status=404,
        )
    return _service_response(result)


@require_ops_permission("manage_ai_review", methods=("POST",))
def ai_review_run_view(request: HttpRequest, request_id: int) -> JsonResponse:
    body, error = _json_object_body(request)
    if error is not None:
        return error
    assert body is not None
    try:
        result = run_ai_review(
            ai_review_request_id=request_id,
            trace_id=str(body.get("trace_id", "")).strip(),
            trigger_source="ops_console_ai_review",
        )
    except ObjectDoesNotExist:
        return error_response(
            reason_code="ops_console_object_not_found",
            message_zh="请求操作的 AIReviewRequest 不存在。",
            status=404,
        )
    return _service_response(result)


@require_ops_permission("manage_ai_review", methods=("POST",))
def ai_review_update_suggestion_view(request: HttpRequest, suggestion_id: int) -> JsonResponse:
    body, error = _json_object_body(request)
    if error is not None:
        return error
    assert body is not None
    try:
        result = update_suggestion_status(
            suggestion_id=suggestion_id,
            new_status=str(body.get("new_status", "")),
            operator_id=_operator_id(request),
            decision_note=str(body.get("decision_note", "")),
            trace_id=str(body.get("trace_id", "")).strip() or f"ops-ai-review-suggestion-{request.user.id}",
            trigger_source="ops_console_ai_review",
        )
    except ObjectDoesNotExist:
        return error_response(
            reason_code="ops_console_object_not_found",
            message_zh="请求操作的 AIReviewSuggestion 不存在。",
            status=404,
        )
    return _service_response(result)
