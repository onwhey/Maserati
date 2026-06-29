"""OrderLifecycle 模块：独立订单生命周期管线入口。

负责什么：对已提交订单显式运行状态同步与成交同步。
不负责什么：不提交新订单、不撤单、不改单、不追单、不直接释放 ActiveLock、不承载主交易编排。
是否读写数据库：通过 OrderStatusSync / FillSync 间接读写 MySQL。
是否访问 Redis：不直接访问 Redis。
是否访问外部服务：不直接访问外部服务，通过 OrderStatusSync / FillSync 间接调用 BinanceGateway。
是否发送 Hermes：不发送 Hermes。
是否调用大模型：不调用大模型。
是否涉及交易执行：只跟踪既有订单，不产生新的交易执行。
是否允许真实交易：不允许提交真实交易订单。
"""

from __future__ import annotations

from typing import Any

from apps.foundation.results import ResultStatus, ServiceResult
from apps.order_status_sync.models import OrderStatusSyncRecord
from apps.order_status_sync.services.status_sync import POLL_MODE_CLOSEOUT

from .sync import MAX_KEY_LENGTH, sync_order_lifecycle


MAX_PIPELINE_KEY_SUFFIX_LENGTH = 30


def run_order_lifecycle_pipeline(
    *,
    order_submission_attempt_id: int,
    business_request_key: str,
    trace_id: str,
    trigger_source: str,
    poll_sequence: int | None = None,
    poll_mode: str = POLL_MODE_CLOSEOUT,
    order_status_gateway: Any | None = None,
    fill_query_gateway: Any | None = None,
) -> ServiceResult:
    """Run the independent order lifecycle branch for one existing submission attempt."""

    request_error = _request_error(
        order_submission_attempt_id=order_submission_attempt_id,
        business_request_key=business_request_key,
        trace_id=trace_id,
        trigger_source=trigger_source,
        poll_sequence=poll_sequence,
    )
    if request_error:
        return ServiceResult(
            ResultStatus.BLOCKED,
            request_error,
            "OrderLifecyclePipeline 请求合同不完整。",
            trace_id,
            trigger_source,
            {
                "pipeline_action": "STOP",
                "lifecycle_action": "STOP",
                "order_submission_attempt_id": order_submission_attempt_id if isinstance(order_submission_attempt_id, int) else None,
                "order_status_sync_record_id": None,
                "fill_sync_result_id": None,
            },
        )

    normalized_key = business_request_key.strip()
    normalized_sequence = poll_sequence or next_lifecycle_poll_sequence(
        order_submission_attempt_id=order_submission_attempt_id,
        poll_mode=poll_mode,
    )
    lifecycle_result = sync_order_lifecycle(
        order_submission_attempt_id=order_submission_attempt_id,
        business_request_key=_child_key(normalized_key),
        poll_sequence=normalized_sequence,
        trace_id=trace_id,
        trigger_source=trigger_source,
        poll_mode=poll_mode,
        order_status_gateway=order_status_gateway,
        fill_query_gateway=fill_query_gateway,
    )
    return _pipeline_result(
        lifecycle_result=lifecycle_result,
        poll_sequence=normalized_sequence,
        poll_mode=poll_mode,
    )


def next_lifecycle_poll_sequence(*, order_submission_attempt_id: int, poll_mode: str = POLL_MODE_CLOSEOUT) -> int:
    latest = (
        OrderStatusSyncRecord.objects.filter(order_submission_attempt_id=order_submission_attempt_id, poll_mode=poll_mode)
        .order_by("-poll_sequence", "-id")
        .first()
    )
    if latest is None:
        return 1
    if latest.query_finished_at_utc is None:
        return latest.poll_sequence
    return latest.poll_sequence + 1


def _pipeline_result(*, lifecycle_result: ServiceResult, poll_sequence: int, poll_mode: str) -> ServiceResult:
    data = dict(lifecycle_result.data)
    lifecycle_action = str(data.get("lifecycle_action") or "STOP")
    data.update(
        {
            "pipeline_action": _pipeline_action(lifecycle_result, lifecycle_action),
            "lifecycle_action": lifecycle_action,
            "poll_sequence": poll_sequence,
            "poll_mode": poll_mode,
            "scheduled_next_poll": False,
        }
    )
    return ServiceResult(
        lifecycle_result.status,
        lifecycle_result.reason_code,
        lifecycle_result.message,
        lifecycle_result.trace_id,
        lifecycle_result.trigger_source,
        data,
    )


def _pipeline_action(result: ServiceResult, lifecycle_action: str) -> str:
    if result.status == ResultStatus.FAILED or lifecycle_action == "FAIL":
        return "FAIL"
    if lifecycle_action == "WAIT":
        return "WAIT"
    if lifecycle_action == "COMPLETE":
        return "COMPLETE"
    return "STOP"


def _child_key(business_request_key: str) -> str:
    max_base_length = MAX_KEY_LENGTH - MAX_PIPELINE_KEY_SUFFIX_LENGTH
    return f"{business_request_key[:max_base_length]}:lifecycle"


def _request_error(
    *,
    order_submission_attempt_id: int,
    business_request_key: str,
    trace_id: str,
    trigger_source: str,
    poll_sequence: int | None,
) -> str:
    if not isinstance(order_submission_attempt_id, int) or order_submission_attempt_id <= 0:
        return "order_submission_attempt_id_invalid"
    if not isinstance(business_request_key, str) or not business_request_key.strip():
        return "business_request_key_invalid"
    if len(business_request_key.strip()) > MAX_KEY_LENGTH:
        return "business_request_key_invalid"
    if not trace_id or not trigger_source:
        return "trace_context_missing"
    if poll_sequence is not None and (not isinstance(poll_sequence, int) or poll_sequence <= 0):
        return "poll_sequence_invalid"
    return ""
