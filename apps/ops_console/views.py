"""OpsConsole 模块：Django JSON API 入口；调用 selector 与受控业务 service，不直接访问外部服务，不发送 Hermes，不直接调用大模型，不提交订单。"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from django.contrib.auth import authenticate, login, logout
from django.core.exceptions import ObjectDoesNotExist
from django.http import HttpRequest, JsonResponse
from django.middleware.csrf import get_token
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_POST

from apps.binance_account_sync.services.sync import refresh_for_ops_console
from apps.fill_sync.services.sync import recover_order_fills
from apps.order_plan.services.active_lock import manual_closeout_active_lock
from apps.order_status_sync.services.status_sync import recover_order_status_once
from apps.review_dataset.services import (
    create_review_dataset_export,
    mark_review_dataset_export_downloaded,
    preview_review_dataset,
)
from apps.runtime_guard.services.guard import update_runtime_guard_issue_status
from apps.strategy_analysis.services.release import (
    activate_release,
    approve_release,
    copy_release_to_draft,
    create_draft_release,
    create_validation_evidence,
    freeze_release_for_validation,
    invalidate_release,
    prevalidate_release,
    reject_release,
    remove_release_item,
    rollback_to_release,
    update_draft_release_metadata,
    upsert_release_item,
)
from apps.strategy_analysis.services.backtest import create_strategy_backtest_run
from apps.strategy_analysis.services.workspace import (
    generate_release_from_workspace,
    remove_workspace_item,
    upsert_workspace_item,
)

from .permissions import has_ops_permission, require_ops_permission
from .responses import error_response, ok_response
from .selectors import (
    account_overview,
    dashboard_summary,
    get_alert_detail,
    get_order_detail,
    get_review_dataset_export_detail,
    get_review_dataset_record_detail,
    get_run_detail,
    get_runtime_guard_issue_detail,
    get_strategy_backtest_run_detail,
    list_alerts,
    list_audit_log,
    list_orders,
    list_review_dataset_exports,
    list_review_dataset_records,
    list_runtime_guard_issues,
    list_runs,
    get_strategy_workspace,
    list_strategy_backtest_runs,
    list_strategy_backtest_period_results,
    list_strategy_release_components,
    list_strategy_releases,
    list_strategy_workspace_components,
    real_trading_status,
    get_current_strategy_release,
    get_strategy_release_detail,
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
    except LookupError:
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


def _positive_int_body_value(body: dict[str, Any], name: str, *, default: int) -> tuple[int | None, JsonResponse | None]:
    raw = body.get(name, default)
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return None, error_response(
            reason_code=f"{name}_invalid",
            message_zh=f"{name} 必须是正整数。",
            status=400,
        )
    if value <= 0:
        return None, error_response(
            reason_code=f"{name}_invalid",
            message_zh=f"{name} 必须是正整数。",
            status=400,
        )
    return value, None


def _decimal_body_value(body: dict[str, Any], name: str, *, default: str) -> tuple[Decimal | None, JsonResponse | None]:
    raw = str(body.get(name, default)).strip() or default
    try:
        return Decimal(raw), None
    except InvalidOperation:
        return None, error_response(
            reason_code=f"{name}_invalid",
            message_zh=f"{name} 必须是合法数字。",
            status=400,
        )


def _datetime_body_value(body: dict[str, Any], name: str) -> tuple[datetime | None, JsonResponse | None]:
    raw = str(body.get(name, "")).strip()
    if not raw:
        return None, error_response(
            reason_code=f"{name}_required",
            message_zh=f"{name} 必须填写。",
            status=400,
        )
    try:
        value = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None, error_response(
            reason_code=f"{name}_invalid",
            message_zh=f"{name} 必须是合法 UTC ISO 时间。",
            status=400,
        )
    if value.tzinfo is None:
        return None, error_response(
            reason_code=f"{name}_timezone_required",
            message_zh=f"{name} 必须带 UTC 时区，例如 2026-02-20T00:00:00+00:00。",
            status=400,
        )
    return value, None


def _trace_id(body: dict[str, Any], request: HttpRequest, operation: str) -> str:
    return str(body.get("trace_id", "")).strip() or f"ops-{operation}-{request.user.id}"


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


@require_ops_permission("view_strategy_release")
def strategy_releases_view(request: HttpRequest) -> JsonResponse:
    return _handle_selector(list_strategy_releases, request.GET)


@require_ops_permission("view_strategy_release")
def strategy_release_current_view(_request: HttpRequest) -> JsonResponse:
    return _handle_selector(get_current_strategy_release)


@require_ops_permission("run_strategy_backtest")
def strategy_backtest_runs_view(request: HttpRequest) -> JsonResponse:
    return _handle_selector(list_strategy_backtest_runs, request.GET)


@require_ops_permission("run_strategy_backtest")
def strategy_backtest_run_detail_view(_request: HttpRequest, run_id: int) -> JsonResponse:
    return _handle_selector(get_strategy_backtest_run_detail, run_id)


@require_ops_permission("run_strategy_backtest")
def strategy_backtest_period_results_view(request: HttpRequest, run_id: int) -> JsonResponse:
    return _handle_selector(list_strategy_backtest_period_results, run_id, request.GET)


@require_ops_permission("run_strategy_backtest", methods=("POST",))
def strategy_backtest_run_create_view(request: HttpRequest) -> JsonResponse:
    body, error = _json_object_body(request)
    if error is not None:
        return error
    assert body is not None

    release_id = _int_body_value(body, "strategy_analysis_release_id")
    if release_id is None:
        return error_response(
            reason_code="strategy_analysis_release_id_required",
            message_zh="必须选择明确的策略版本包。",
            status=400,
        )

    start, start_error = _datetime_body_value(body, "start_analysis_close_time_utc")
    if start_error is not None:
        return start_error
    end, end_error = _datetime_body_value(body, "end_analysis_close_time_utc")
    if end_error is not None:
        return end_error
    initial_equity, initial_error = _decimal_body_value(body, "initial_equity", default="10000")
    if initial_error is not None:
        return initial_error
    fee_rate, fee_error = _decimal_body_value(body, "fee_rate", default="0.0004")
    if fee_error is not None:
        return fee_error
    leverage, leverage_error = _decimal_body_value(body, "leverage", default="1")
    if leverage_error is not None:
        return leverage_error
    lookback_4h_count, lookback_4h_error = _positive_int_body_value(body, "lookback_4h_count", default=500)
    if lookback_4h_error is not None:
        return lookback_4h_error
    lookback_1d_count, lookback_1d_error = _positive_int_body_value(body, "lookback_1d_count", default=500)
    if lookback_1d_error is not None:
        return lookback_1d_error

    result = create_strategy_backtest_run(
        start_analysis_close_time_utc=start,
        end_analysis_close_time_utc=end,
        strategy_analysis_release_id=release_id,
        strategy_analysis_release_hash=str(body.get("strategy_analysis_release_hash", "")).strip(),
        lookback_4h_count=lookback_4h_count,
        lookback_1d_count=lookback_1d_count,
        initial_equity=initial_equity,
        fee_rate=fee_rate,
        leverage=leverage,
        no_target_policy=str(body.get("no_target_policy", "hold")).strip() or "hold",
        business_request_prefix=str(body.get("business_request_prefix", "")).strip() or "ops-strategy-backtest",
        requested_by=_operator_id(request),
        trace_id=_trace_id(body, request, "strategy-backtest"),
        trigger_source="ops_console_strategy_backtest",
    )
    return _service_response(result)


@require_ops_permission("view_strategy_release")
def strategy_release_detail_view(_request: HttpRequest, release_id: int) -> JsonResponse:
    return _handle_selector(get_strategy_release_detail, release_id)


@require_ops_permission("view_strategy_release")
def strategy_release_components_view(request: HttpRequest) -> JsonResponse:
    return _handle_selector(list_strategy_release_components, request.GET)


@require_ops_permission("view_strategy_release")
def strategy_workspace_view(_request: HttpRequest) -> JsonResponse:
    return _handle_selector(get_strategy_workspace)


@require_ops_permission("view_strategy_release")
def strategy_workspace_components_view(request: HttpRequest) -> JsonResponse:
    return _handle_selector(list_strategy_workspace_components, request.GET)


@require_ops_permission("edit_strategy_release", methods=("POST",))
def strategy_workspace_item_upsert_view(request: HttpRequest) -> JsonResponse:
    body, error = _json_object_body(request)
    if error is not None:
        return error
    assert body is not None
    if confirm_error := _confirm_write_error(body, message_zh="更新当前策略配置会写入数据库，必须显式 confirm_write=true。"):
        return confirm_error
    reason, reason_error = _reason_or_error(body, message_zh="更新当前策略配置需要填写原因。")
    if reason_error is not None:
        return reason_error
    component_object_id = _int_body_value(body, "component_object_id")
    if component_object_id is None:
        return error_response(
            reason_code="component_object_id_required",
            message_zh="必须选择明确的组件对象 ID。",
            status=400,
        )
    result = upsert_workspace_item(
        component_type=str(body.get("component_type", "")).strip(),
        component_object_id=component_object_id,
        is_included=body.get("is_included") is True,
        operator_id=_operator_id(request),
        reason=reason,
        trace_id=_trace_id(body, request, "strategy-workspace-item-upsert"),
        trigger_source="ops_console_strategy_workspace",
    )
    return _service_response(result)


@require_ops_permission("edit_strategy_release", methods=("POST",))
def strategy_workspace_item_remove_view(request: HttpRequest) -> JsonResponse:
    body, error = _json_object_body(request)
    if error is not None:
        return error
    assert body is not None
    if confirm_error := _confirm_write_error(body, message_zh="移除当前策略配置项会写入数据库，必须显式 confirm_write=true。"):
        return confirm_error
    reason, reason_error = _reason_or_error(body, message_zh="移除当前策略配置项需要填写原因。")
    if reason_error is not None:
        return reason_error
    item_id = _int_body_value(body, "item_id")
    if item_id is None:
        return error_response(
            reason_code="workspace_item_id_required",
            message_zh="必须选择明确的工作区配置项 ID。",
            status=400,
        )
    result = remove_workspace_item(
        item_id=item_id,
        operator_id=_operator_id(request),
        reason=reason,
        trace_id=_trace_id(body, request, "strategy-workspace-item-remove"),
        trigger_source="ops_console_strategy_workspace",
    )
    return _service_response(result)


@require_ops_permission("edit_strategy_release", methods=("POST",))
def strategy_workspace_generate_release_view(request: HttpRequest) -> JsonResponse:
    body, error = _json_object_body(request)
    if error is not None:
        return error
    assert body is not None
    if confirm_error := _confirm_write_error(body, message_zh="从当前配置生成策略版本包草稿会写入数据库，必须显式 confirm_write=true。"):
        return confirm_error
    reason, reason_error = _reason_or_error(body, message_zh="生成策略版本包草稿需要填写原因。")
    if reason_error is not None:
        return reason_error
    result = generate_release_from_workspace(
        release_code=str(body.get("release_code", "")).strip(),
        display_name=str(body.get("display_name", "")).strip(),
        description=str(body.get("description", "")).strip(),
        operator_id=_operator_id(request),
        reason=reason,
        trace_id=_trace_id(body, request, "strategy-workspace-generate-release"),
        trigger_source="ops_console_strategy_workspace",
    )
    return _service_response(result)


@require_ops_permission("edit_strategy_release", methods=("POST",))
def strategy_release_create_draft_view(request: HttpRequest) -> JsonResponse:
    body, error = _json_object_body(request)
    if error is not None:
        return error
    assert body is not None
    if confirm_error := _confirm_write_error(body, message_zh="创建策略版本包草稿会写入数据库，必须显式 confirm_write=true。"):
        return confirm_error
    reason, reason_error = _reason_or_error(body, message_zh="创建策略版本包草稿需要填写原因。")
    if reason_error is not None:
        return reason_error
    result = create_draft_release(
        release_code=str(body.get("release_code", "")).strip(),
        display_name=str(body.get("display_name", "")).strip(),
        description=str(body.get("description", "")).strip(),
        operator_id=_operator_id(request),
        reason=reason,
        trace_id=_trace_id(body, request, "strategy-release-create-draft"),
        trigger_source="ops_console_strategy_release",
    )
    return _service_response(result)


@require_ops_permission("edit_strategy_release", methods=("POST",))
def strategy_release_copy_draft_view(request: HttpRequest, release_id: int) -> JsonResponse:
    body, error = _json_object_body(request)
    if error is not None:
        return error
    assert body is not None
    if confirm_error := _confirm_write_error(body, message_zh="复制策略版本包会写入新草稿，必须显式 confirm_write=true。"):
        return confirm_error
    reason, reason_error = _reason_or_error(body, message_zh="复制策略版本包需要填写原因。")
    if reason_error is not None:
        return reason_error
    result = copy_release_to_draft(
        source_release_id=release_id,
        release_code=str(body.get("release_code", "")).strip(),
        display_name=str(body.get("display_name", "")).strip(),
        description=str(body.get("description", "")).strip(),
        operator_id=_operator_id(request),
        reason=reason,
        trace_id=_trace_id(body, request, "strategy-release-copy-draft"),
        trigger_source="ops_console_strategy_release",
    )
    return _service_response(result)


@require_ops_permission("edit_strategy_release", methods=("POST",))
def strategy_release_update_draft_view(request: HttpRequest, release_id: int) -> JsonResponse:
    body, error = _json_object_body(request)
    if error is not None:
        return error
    assert body is not None
    if confirm_error := _confirm_write_error(body, message_zh="更新策略版本包草稿会写入数据库，必须显式 confirm_write=true。"):
        return confirm_error
    reason, reason_error = _reason_or_error(body, message_zh="更新策略版本包草稿需要填写原因。")
    if reason_error is not None:
        return reason_error
    result = update_draft_release_metadata(
        release_id=release_id,
        display_name=str(body.get("display_name", "")).strip(),
        description=str(body.get("description", "")).strip(),
        operator_id=_operator_id(request),
        reason=reason,
        trace_id=_trace_id(body, request, "strategy-release-update-draft"),
        trigger_source="ops_console_strategy_release",
    )
    return _service_response(result)


@require_ops_permission("edit_strategy_release", methods=("POST",))
def strategy_release_item_upsert_view(request: HttpRequest, release_id: int) -> JsonResponse:
    body, error = _json_object_body(request)
    if error is not None:
        return error
    assert body is not None
    if confirm_error := _confirm_write_error(body, message_zh="写入策略版本包组件会修改草稿，必须显式 confirm_write=true。"):
        return confirm_error
    reason, reason_error = _reason_or_error(body, message_zh="写入策略版本包组件需要填写原因。")
    if reason_error is not None:
        return reason_error
    component_object_id = _int_body_value(body, "component_object_id")
    if component_object_id is None:
        return error_response(
            reason_code="component_object_id_required",
            message_zh="必须选择明确的组件对象 ID。",
            status=400,
        )
    result = upsert_release_item(
        release_id=release_id,
        component_type=str(body.get("component_type", "")).strip(),
        component_object_id=component_object_id,
        operator_id=_operator_id(request),
        reason=reason,
        trace_id=_trace_id(body, request, "strategy-release-item-upsert"),
        trigger_source="ops_console_strategy_release",
    )
    return _service_response(result)


@require_ops_permission("edit_strategy_release", methods=("POST",))
def strategy_release_item_remove_view(request: HttpRequest, release_id: int) -> JsonResponse:
    body, error = _json_object_body(request)
    if error is not None:
        return error
    assert body is not None
    if confirm_error := _confirm_write_error(body, message_zh="移除策略版本包组件会修改草稿，必须显式 confirm_write=true。"):
        return confirm_error
    reason, reason_error = _reason_or_error(body, message_zh="移除策略版本包组件需要填写原因。")
    if reason_error is not None:
        return reason_error
    item_id = _int_body_value(body, "item_id")
    if item_id is None:
        return error_response(reason_code="release_item_id_required", message_zh="必须指定明确的 ReleaseItem ID。", status=400)
    result = remove_release_item(
        release_id=release_id,
        item_id=item_id,
        operator_id=_operator_id(request),
        reason=reason,
        trace_id=_trace_id(body, request, "strategy-release-item-remove"),
        trigger_source="ops_console_strategy_release",
    )
    return _service_response(result)


@require_ops_permission("view_strategy_release", methods=("POST",))
def strategy_release_prevalidate_view(request: HttpRequest, release_id: int) -> JsonResponse:
    body, error = _json_object_body(request)
    if error is not None:
        return error
    assert body is not None
    result = prevalidate_release(
        release_id=release_id,
        trace_id=_trace_id(body, request, "strategy-release-prevalidate"),
        trigger_source="ops_console_strategy_release",
    )
    return _service_response(result)


@require_ops_permission("edit_strategy_release", methods=("POST",))
def strategy_release_freeze_view(request: HttpRequest, release_id: int) -> JsonResponse:
    body, error = _json_object_body(request)
    if error is not None:
        return error
    assert body is not None
    if confirm_error := _confirm_write_error(body, message_zh="冻结后版本包组件不可原地修改，必须显式 confirm_write=true。"):
        return confirm_error
    reason, reason_error = _reason_or_error(body, message_zh="冻结策略版本包需要填写原因。")
    if reason_error is not None:
        return reason_error
    result = freeze_release_for_validation(
        release_id=release_id,
        operator_id=_operator_id(request),
        reason=reason,
        trace_id=_trace_id(body, request, "strategy-release-freeze"),
        trigger_source="ops_console_strategy_release",
    )
    return _service_response(result)


@require_ops_permission("edit_strategy_release", methods=("POST",))
def strategy_release_validation_evidence_view(request: HttpRequest, release_id: int) -> JsonResponse:
    body, error = _json_object_body(request)
    if error is not None:
        return error
    assert body is not None
    if confirm_error := _confirm_write_error(body, message_zh="登记验证证据会写入数据库，必须显式 confirm_write=true。"):
        return confirm_error
    reason, reason_error = _reason_or_error(body, message_zh="登记验证证据需要填写原因。")
    if reason_error is not None:
        return reason_error
    result = create_validation_evidence(
        release_id=release_id,
        evidence_type=str(body.get("evidence_type", "")).strip(),
        evidence_ref=str(body.get("evidence_ref", "")).strip(),
        summary=str(body.get("summary", "")).strip(),
        created_by=_operator_id(request),
        reason=reason,
        trace_id=_trace_id(body, request, "strategy-release-evidence"),
        trigger_source="ops_console_strategy_release",
    )
    return _service_response(result)


@require_ops_permission("approve_strategy_release", methods=("POST",))
def strategy_release_approve_view(request: HttpRequest, release_id: int) -> JsonResponse:
    body, error = _json_object_body(request)
    if error is not None:
        return error
    assert body is not None
    if confirm_error := _confirm_write_error(body, message_zh="批准策略版本包会允许后续启用，必须显式 confirm_write=true。"):
        return confirm_error
    reason, reason_error = _reason_or_error(body, message_zh="批准策略版本包需要填写原因。")
    if reason_error is not None:
        return reason_error
    result = approve_release(
        release_id=release_id,
        operator_id=_operator_id(request),
        reason=reason,
        trace_id=_trace_id(body, request, "strategy-release-approve"),
        trigger_source="ops_console_strategy_release",
    )
    return _service_response(result)


@require_ops_permission("approve_strategy_release", methods=("POST",))
def strategy_release_reject_view(request: HttpRequest, release_id: int) -> JsonResponse:
    body, error = _json_object_body(request)
    if error is not None:
        return error
    assert body is not None
    if confirm_error := _confirm_write_error(body, message_zh="拒绝策略版本包会结束本次验证流程，必须显式 confirm_write=true。"):
        return confirm_error
    reason, reason_error = _reason_or_error(body, message_zh="拒绝策略版本包需要填写原因。")
    if reason_error is not None:
        return reason_error
    result = reject_release(
        release_id=release_id,
        operator_id=_operator_id(request),
        reason=reason,
        trace_id=_trace_id(body, request, "strategy-release-reject"),
        trigger_source="ops_console_strategy_release",
    )
    return _service_response(result)


@require_ops_permission("approve_strategy_release", methods=("POST",))
def strategy_release_invalidate_view(request: HttpRequest, release_id: int) -> JsonResponse:
    body, error = _json_object_body(request)
    if error is not None:
        return error
    assert body is not None
    if confirm_error := _confirm_write_error(body, message_zh="失效策略版本包会阻止后续继续使用，必须显式 confirm_write=true。"):
        return confirm_error
    reason, reason_error = _reason_or_error(body, message_zh="失效策略版本包需要填写原因。")
    if reason_error is not None:
        return reason_error
    result = invalidate_release(
        release_id=release_id,
        operator_id=_operator_id(request),
        reason=reason,
        trace_id=_trace_id(body, request, "strategy-release-invalidate"),
        trigger_source="ops_console_strategy_release",
    )
    return _service_response(result)


@require_ops_permission("activate_strategy_release", methods=("POST",))
def strategy_release_activate_view(request: HttpRequest, release_id: int) -> JsonResponse:
    body, error = _json_object_body(request)
    if error is not None:
        return error
    assert body is not None
    if confirm_error := _confirm_write_error(body, message_zh="启用策略版本包会影响后续新编排，必须显式 confirm_write=true。"):
        return confirm_error
    reason, reason_error = _reason_or_error(body, message_zh="启用策略版本包需要填写原因。")
    if reason_error is not None:
        return reason_error
    result = activate_release(
        release_id=release_id,
        operator_id=_operator_id(request),
        reason=reason,
        trace_id=_trace_id(body, request, "strategy-release-activate"),
        trigger_source="ops_console_strategy_release",
    )
    return _service_response(result)


@require_ops_permission("activate_strategy_release", methods=("POST",))
def strategy_release_rollback_view(request: HttpRequest, release_id: int) -> JsonResponse:
    body, error = _json_object_body(request)
    if error is not None:
        return error
    assert body is not None
    if confirm_error := _confirm_write_error(body, message_zh="回滚策略版本包会影响后续新编排，必须显式 confirm_write=true。"):
        return confirm_error
    reason, reason_error = _reason_or_error(body, message_zh="回滚策略版本包需要填写原因。")
    if reason_error is not None:
        return reason_error
    result = rollback_to_release(
        release_id=release_id,
        operator_id=_operator_id(request),
        reason=reason,
        trace_id=_trace_id(body, request, "strategy-release-rollback"),
        trigger_source="ops_console_strategy_release",
    )
    return _service_response(result)


@require_ops_permission("view_ops_console")
def review_dataset_records_view(request: HttpRequest) -> JsonResponse:
    return _handle_selector(list_review_dataset_records, request.GET)


@require_ops_permission("view_ops_console")
def review_dataset_record_detail_view(_request: HttpRequest, record_id: int) -> JsonResponse:
    return _handle_selector(get_review_dataset_record_detail, record_id)


@require_ops_permission("view_ops_console")
def review_dataset_exports_view(request: HttpRequest) -> JsonResponse:
    return _handle_selector(list_review_dataset_exports, request.GET)


@require_ops_permission("view_ops_console")
def review_dataset_export_detail_view(_request: HttpRequest, export_id: int) -> JsonResponse:
    return _handle_selector(get_review_dataset_export_detail, export_id)


@require_ops_permission("view_ops_console", methods=("POST",))
def review_dataset_preview_view(request: HttpRequest) -> JsonResponse:
    body, error = _json_object_body(request)
    if error is not None:
        return error
    assert body is not None
    result = preview_review_dataset(
        range_selector=body.get("range_selector", {}),
        filters=body.get("filters", {}),
        trace_id=str(body.get("trace_id", "")).strip() or f"ops-review-dataset-preview-{request.user.id}",
        trigger_source="ops_console_review_dataset",
    )
    return _service_response(result)


@require_ops_permission("manage_review_dataset", methods=("POST",))
def review_dataset_export_create_view(request: HttpRequest) -> JsonResponse:
    body, error = _json_object_body(request)
    if error is not None:
        return error
    assert body is not None
    if confirm_error := _confirm_write_error(body, message_zh="ReviewDataset 导出会写入导出记录、审计和导出文件，必须显式 confirm_write=true。"):
        return confirm_error
    reason, reason_error = _reason_or_error(body, message_zh="ReviewDataset 导出需要填写操作原因。")
    if reason_error is not None:
        return reason_error
    result = create_review_dataset_export(
        range_selector=body.get("range_selector", {}),
        filters=body.get("filters", {}),
        export_format=str(body.get("export_format", "json")),
        operator_id=_operator_id(request),
        reason=reason,
        trace_id=str(body.get("trace_id", "")).strip() or f"ops-review-dataset-export-{request.user.id}",
        trigger_source="ops_console_review_dataset",
    )
    return _service_response(result)


@require_ops_permission("manage_review_dataset", methods=("POST",))
def review_dataset_export_download_mark_view(request: HttpRequest, export_id: int) -> JsonResponse:
    body, error = _json_object_body(request)
    if error is not None:
        return error
    assert body is not None
    try:
        result = mark_review_dataset_export_downloaded(
            export_id=export_id,
            operator_id=_operator_id(request),
            trace_id=str(body.get("trace_id", "")).strip() or f"ops-review-dataset-download-{request.user.id}",
            trigger_source="ops_console_review_dataset",
        )
    except ObjectDoesNotExist:
        return error_response(
            reason_code="ops_console_object_not_found",
            message_zh="请求操作的 ReviewDatasetExport 不存在。",
            status=404,
        )
    return _service_response(result)
