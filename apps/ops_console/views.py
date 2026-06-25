"""OpsConsole 模块：Django JSON API 入口；只调用 selector，不访问外部服务，不发送 Hermes，不调用大模型，不涉及交易执行。"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from django.http import HttpRequest, JsonResponse

from apps.performance_metrics.selectors import get_performance_record, list_performance_records
from apps.performance_metrics.services import backfill_missing_closed_period_performance, preview_missing_closed_period_performance

from .permissions import require_ops_permission
from .responses import error_response, ok_response
from .selectors import (
    OpsConsoleObjectNotFound,
    account_overview,
    dashboard_summary,
    get_alert_detail,
    get_order_detail,
    get_run_detail,
    get_runtime_guard_issue_detail,
    list_alerts,
    list_audit_log,
    list_orders,
    list_runtime_guard_issues,
    list_runs,
    real_trading_status,
)


def _handle_selector(selector: Callable[..., Any], *args: Any, **kwargs: Any) -> JsonResponse:
    try:
        return ok_response(selector(*args, **kwargs))
    except OpsConsoleObjectNotFound:
        return error_response(
            reason_code="ops_console_object_not_found",
            message_zh="请求查看的对象不存在。",
            status=404,
        )


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


@require_ops_permission("view_ops_console")
def account_overview_view(_request: HttpRequest) -> JsonResponse:
    return _handle_selector(account_overview)


@require_ops_permission("view_ops_console")
def runtime_guard_issues_view(request: HttpRequest) -> JsonResponse:
    return _handle_selector(list_runtime_guard_issues, request.GET)


@require_ops_permission("view_ops_console")
def runtime_guard_issue_detail_view(_request: HttpRequest, issue_id: int) -> JsonResponse:
    return _handle_selector(get_runtime_guard_issue_detail, issue_id)


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
