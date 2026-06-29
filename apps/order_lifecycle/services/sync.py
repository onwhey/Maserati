"""OrderLifecycle 模块：串联既有订单状态与成交同步；只读取既有 OrderSubmissionAttempt，实际状态和成交事实由下游 service 写库；不访问 Redis；通过 OrderStatusSync / FillSync 间接只读访问 Binance；不发送 Hermes；不调用大模型；不提交订单；不允许新增真实交易。"""

from __future__ import annotations

from typing import Any

from django.db import DatabaseError

from apps.execution.models import OrderSubmissionAttempt, OrderSubmissionAttemptStatus
from apps.fill_sync.services.sync import sync_order_fills
from apps.foundation.results import ResultStatus, ServiceResult
from apps.order_status_sync.services.status_sync import POLL_MODE_CLOSEOUT, poll_order_status


MAX_KEY_LENGTH = 191
MAX_TRACE_FIELD_LENGTH = 80
MAX_CHILD_KEY_SUFFIX_LENGTH = 25

LIFECYCLE_QUERYABLE_STATUSES = {
    OrderSubmissionAttemptStatus.ACCEPTED,
    OrderSubmissionAttemptStatus.UNKNOWN,
}


def sync_order_lifecycle(
    *,
    order_submission_attempt_id: int,
    business_request_key: str,
    poll_sequence: int,
    trace_id: str,
    trigger_source: str,
    poll_mode: str = POLL_MODE_CLOSEOUT,
    order_status_gateway: Any | None = None,
    fill_query_gateway: Any | None = None,
) -> ServiceResult:
    request_error = _request_error(
        order_submission_attempt_id=order_submission_attempt_id,
        business_request_key=business_request_key,
        poll_sequence=poll_sequence,
        trace_id=trace_id,
        trigger_source=trigger_source,
    )
    if request_error:
        return _result(
            ResultStatus.BLOCKED,
            request_error,
            "OrderLifecycleSync 请求合同不完整。",
            trace_id,
            trigger_source,
            lifecycle_action="STOP",
            order_submission_attempt_id=order_submission_attempt_id if isinstance(order_submission_attempt_id, int) else None,
        )
    normalized_key = business_request_key.strip()

    try:
        attempt = _get_attempt(order_submission_attempt_id)
    except OrderSubmissionAttempt.DoesNotExist:
        return _result(
            ResultStatus.BLOCKED,
            "order_submission_attempt_not_found",
            "OrderSubmissionAttempt 不存在，无法进入订单生命周期同步。",
            trace_id,
            trigger_source,
            lifecycle_action="STOP",
            order_submission_attempt_id=order_submission_attempt_id,
        )
    except DatabaseError as exc:
        return _result(
            ResultStatus.FAILED,
            "internal_error",
            type(exc).__name__,
            trace_id,
            trigger_source,
            lifecycle_action="FAIL",
            order_submission_attempt_id=order_submission_attempt_id,
        )

    if attempt.status not in LIFECYCLE_QUERYABLE_STATUSES:
        return _result(
            ResultStatus.NO_ACTION,
            "order_lifecycle_sync_not_required",
            "当前订单提交结果不需要进入订单生命周期同步。",
            trace_id,
            trigger_source,
            lifecycle_action="COMPLETE",
            order_submission_attempt_id=attempt.id,
            data={"attempt_status": attempt.status, "requires_order_status_sync": False},
        )

    status_result = poll_order_status(
        order_submission_attempt_id=attempt.id,
        business_request_key=f"{normalized_key}:status",
        poll_sequence=poll_sequence,
        trace_id=trace_id,
        trigger_source=trigger_source,
        gateway=order_status_gateway,
        poll_mode=poll_mode,
    )
    if not status_result.data.get("allows_fill_sync"):
        return _status_only_result(status_result=status_result, attempt_id=attempt.id, poll_sequence=poll_sequence)

    terminal_record_id = status_result.data.get("order_status_sync_record_id")
    if not isinstance(terminal_record_id, int) or terminal_record_id <= 0:
        return _result(
            ResultStatus.FAILED,
            "terminal_order_status_record_missing",
            "OrderStatusSync 已允许成交同步，但缺少终态状态记录 ID。",
            trace_id,
            trigger_source,
            lifecycle_action="FAIL",
            order_submission_attempt_id=attempt.id,
            data={"order_status_result": _compact_result(status_result)},
        )

    fill_result = sync_order_fills(
        order_submission_attempt_id=attempt.id,
        terminal_order_status_sync_record_id=terminal_record_id,
        business_request_key=f"{normalized_key}:fill:{terminal_record_id}",
        trace_id=trace_id,
        trigger_source=trigger_source,
        gateway=fill_query_gateway,
    )
    return _fill_result(status_result=status_result, fill_result=fill_result, attempt_id=attempt.id)


def _get_attempt(order_submission_attempt_id: int) -> OrderSubmissionAttempt:
    return OrderSubmissionAttempt.objects.only("id", "status").get(id=order_submission_attempt_id)


def _status_only_result(*, status_result: ServiceResult, attempt_id: int, poll_sequence: int) -> ServiceResult:
    action = _action_from_status_result(status_result)
    data = {
        "order_submission_attempt_id": attempt_id,
        "order_status_result": _compact_result(status_result),
        "order_status_sync_record_id": status_result.data.get("order_status_sync_record_id"),
        "allows_next_poll": bool(status_result.data.get("allows_next_poll")),
        "next_poll_sequence": poll_sequence + 1 if status_result.data.get("allows_next_poll") else None,
    }
    return _result(
        status_result.status,
        status_result.reason_code,
        status_result.message,
        status_result.trace_id,
        status_result.trigger_source,
        lifecycle_action=action,
        order_submission_attempt_id=attempt_id,
        data=data,
    )


def _fill_result(*, status_result: ServiceResult, fill_result: ServiceResult, attempt_id: int) -> ServiceResult:
    action = _action_from_fill_result(fill_result)
    data = {
        "order_submission_attempt_id": attempt_id,
        "order_status_result": _compact_result(status_result),
        "fill_sync_result": _compact_result(fill_result),
        "order_status_sync_record_id": status_result.data.get("order_status_sync_record_id"),
        "fill_sync_result_id": fill_result.data.get("fill_sync_result_id"),
        "allows_active_lock_finalization": bool(fill_result.data.get("allows_active_lock_finalization")),
    }
    return _result(
        fill_result.status,
        fill_result.reason_code,
        fill_result.message,
        fill_result.trace_id,
        fill_result.trigger_source,
        lifecycle_action=action,
        order_submission_attempt_id=attempt_id,
        data=data,
    )


def _action_from_status_result(result: ServiceResult) -> str:
    flow_action = str(result.data.get("flow_action") or "")
    if flow_action == "WAIT":
        return "WAIT"
    if result.status == ResultStatus.FAILED:
        return "FAIL"
    if result.status in {ResultStatus.BLOCKED, ResultStatus.DENIED}:
        return "STOP"
    return "STOP"


def _action_from_fill_result(result: ServiceResult) -> str:
    if result.status == ResultStatus.FAILED:
        return "FAIL"
    if result.status in {ResultStatus.BLOCKED, ResultStatus.DENIED}:
        return "STOP"
    return "COMPLETE"


def _compact_result(result: ServiceResult) -> dict[str, Any]:
    return {
        "status": result.status.value,
        "reason_code": result.reason_code,
        "data": result.data,
    }


def _result(
    status: ResultStatus,
    reason_code: str,
    message: str,
    trace_id: str,
    trigger_source: str,
    *,
    lifecycle_action: str,
    order_submission_attempt_id: int | None,
    data: dict[str, Any] | None = None,
) -> ServiceResult:
    payload = {
        "order_submission_attempt_id": order_submission_attempt_id,
        "lifecycle_action": lifecycle_action,
    }
    if data:
        payload.update(data)
    return ServiceResult(status, reason_code, message, trace_id, trigger_source, payload)


def _request_error(
    *,
    order_submission_attempt_id: int,
    business_request_key: str,
    poll_sequence: int,
    trace_id: str,
    trigger_source: str,
) -> str:
    if not isinstance(order_submission_attempt_id, int) or order_submission_attempt_id <= 0:
        return "order_submission_attempt_id_invalid"
    if not isinstance(poll_sequence, int) or poll_sequence <= 0:
        return "poll_sequence_invalid"
    if not isinstance(business_request_key, str):
        return "business_request_key_invalid"
    normalized_key = business_request_key.strip()
    if not normalized_key or len(normalized_key) > MAX_KEY_LENGTH - MAX_CHILD_KEY_SUFFIX_LENGTH:
        return "business_request_key_invalid"
    if not trace_id or not trigger_source or len(trace_id) > MAX_TRACE_FIELD_LENGTH or len(trigger_source) > MAX_TRACE_FIELD_LENGTH:
        return "trace_context_missing"
    return ""
