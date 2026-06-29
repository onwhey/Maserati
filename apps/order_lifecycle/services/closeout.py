"""OrderLifecycle 模块：实现 LIMIT 订单周期收尾撤单；读写 MySQL；不访问 Redis；通过 BinanceOrderCancelGateway 访问 Binance；不发送 Hermes；不调用大模型；只撤销既有订单，不提交新订单。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from django.db import DatabaseError, IntegrityError, transaction
from django.utils import timezone

from apps.binance_account_sync.services.hashing import stable_hash
from apps.binance_gateway.order_cancel import BinanceOrderCancelGateway, get_order_cancel_gateway
from apps.binance_gateway.types import ERROR_ORDER_NOT_FOUND, BinanceGatewayCallContext, BinanceGatewayResult
from apps.execution.models import OrderSubmissionAttempt, OrderSubmissionAttemptStatus
from apps.fill_sync.models import OrderFillSummary
from apps.foundation.redaction import sanitize_mapping
from apps.foundation.results import ResultStatus, ServiceResult
from apps.order_plan.models import ActiveLockStatus
from apps.order_status_sync.models import OrderStatusQueryOutcome, OrderStatusSyncRecord

from ..models import OrderCancelAttempt, OrderCancelAttemptStatus
from .alerts import record_order_cancel_alert
from .pipeline import run_order_lifecycle_pipeline


MAX_KEY_LENGTH = 191
MAX_TRACE_FIELD_LENGTH = 80
DEFAULT_CANCEL_REASON = "limit_order_expired"
ELIGIBLE_SUBMISSION_STATUSES = {OrderSubmissionAttemptStatus.ACCEPTED, OrderSubmissionAttemptStatus.UNKNOWN}
COMPLETE_FILL_SUMMARY_STATUSES = {"complete", "empty"}


@dataclass(frozen=True)
class CloseoutClaim:
    cancel_attempt: OrderCancelAttempt | None = None
    should_call_gateway: bool = False
    replay: bool = False
    result: ServiceResult | None = None


def closeout_limit_order(
    *,
    order_submission_attempt_id: int,
    business_request_key: str,
    closeout_time_utc: datetime,
    trace_id: str,
    trigger_source: str,
    cancel_reason_code: str = DEFAULT_CANCEL_REASON,
    cancel_gateway: BinanceOrderCancelGateway | None = None,
    order_status_gateway: Any | None = None,
    fill_query_gateway: Any | None = None,
) -> ServiceResult:
    request_error = _request_error(
        order_submission_attempt_id=order_submission_attempt_id,
        business_request_key=business_request_key,
        closeout_time_utc=closeout_time_utc,
        trace_id=trace_id,
        trigger_source=trigger_source,
        cancel_reason_code=cancel_reason_code,
    )
    if request_error:
        return _result(
            ResultStatus.BLOCKED,
            request_error,
            "OrderCycleCloseout 请求合同不完整。",
            trace_id,
            trigger_source,
            closeout_action="STOP",
            order_submission_attempt_id=order_submission_attempt_id if isinstance(order_submission_attempt_id, int) else None,
        )

    try:
        claim = _claim_closeout(
            order_submission_attempt_id=order_submission_attempt_id,
            business_request_key=business_request_key.strip(),
            closeout_time_utc=_ensure_utc(closeout_time_utc),
            trace_id=trace_id,
            trigger_source=trigger_source,
            cancel_reason_code=cancel_reason_code.strip(),
        )
    except OrderSubmissionAttempt.DoesNotExist:
        return _result(
            ResultStatus.BLOCKED,
            "order_submission_attempt_not_found",
            "OrderSubmissionAttempt 不存在，无法执行限价单周期收尾。",
            trace_id,
            trigger_source,
            closeout_action="STOP",
            order_submission_attempt_id=order_submission_attempt_id,
        )
    except DatabaseError as exc:
        return _result(
            ResultStatus.FAILED,
            "internal_error",
            type(exc).__name__,
            trace_id,
            trigger_source,
            closeout_action="FAIL",
            order_submission_attempt_id=order_submission_attempt_id,
        )

    if claim.result is not None:
        return claim.result
    if claim.cancel_attempt is None:
        return _result(
            ResultStatus.FAILED,
            "order_cancel_claim_failed",
            "未能创建限价单周期收尾撤单记录。",
            trace_id,
            trigger_source,
            closeout_action="FAIL",
            order_submission_attempt_id=order_submission_attempt_id,
        )
    if claim.replay or not claim.should_call_gateway:
        _record_alert_if_needed(claim.cancel_attempt, replay=claim.replay)
        return _result_from_cancel_attempt(claim.cancel_attempt, replay=claim.replay)

    gateway_result = _call_cancel_gateway(claim.cancel_attempt, cancel_gateway or get_order_cancel_gateway())
    cancel_attempt = _finalize_cancel_result(claim.cancel_attempt.id, gateway_result)
    _record_alert_if_needed(cancel_attempt)
    lifecycle_result = _run_lifecycle_sync_if_needed(
        cancel_attempt,
        order_status_gateway=order_status_gateway,
        fill_query_gateway=fill_query_gateway,
    )
    return _result_from_cancel_attempt(cancel_attempt, lifecycle_result=lifecycle_result)


def _claim_closeout(
    *,
    order_submission_attempt_id: int,
    business_request_key: str,
    closeout_time_utc: datetime,
    trace_id: str,
    trigger_source: str,
    cancel_reason_code: str,
) -> CloseoutClaim:
    now = timezone.now()
    with transaction.atomic():
        attempt = _locked_attempt(order_submission_attempt_id)
        existing = (
            OrderCancelAttempt.objects.select_for_update()
            .filter(
                order_submission_attempt=attempt,
                closeout_time_utc=closeout_time_utc,
                cancel_reason_code=cancel_reason_code,
            )
            .first()
        )
        if existing is not None:
            if existing.finished_at_utc is None and existing.cancel_status == OrderCancelAttemptStatus.CANCELING:
                return CloseoutClaim(result=_cancel_in_progress_result(existing, trace_id, trigger_source))
            return CloseoutClaim(cancel_attempt=existing, replay=True)

        pre_error = _pre_cancel_error(attempt, closeout_time_utc)
        if pre_error.action == "no_action":
            return CloseoutClaim(result=_no_action_result(attempt, pre_error.reason_code, pre_error.message, trace_id, trigger_source))
        if pre_error.action == "sync_existing_terminal":
            return CloseoutClaim(result=_sync_existing_terminal_result(attempt, business_request_key, trace_id, trigger_source))

        cancel_request = _frozen_cancel_request(attempt)
        status = OrderCancelAttemptStatus.CANCELING if not pre_error.reason_code else OrderCancelAttemptStatus.BLOCKED_BEFORE_CANCEL
        record = _create_cancel_attempt(
            attempt=attempt,
            business_request_key=business_request_key,
            closeout_time_utc=closeout_time_utc,
            cancel_reason_code=cancel_reason_code,
            cancel_status=status,
            reason_code=pre_error.reason_code,
            cancel_request=cancel_request,
            reason_message=pre_error.message,
            trace_id=trace_id,
            trigger_source=trigger_source,
            now=now,
            finished_at_utc=now if pre_error.reason_code else None,
        )
        return CloseoutClaim(cancel_attempt=record, should_call_gateway=not pre_error.reason_code)


@dataclass(frozen=True)
class PreCancelError:
    reason_code: str = ""
    message: str = ""
    action: str = "cancel"


def _pre_cancel_error(attempt: OrderSubmissionAttempt, closeout_time_utc: datetime) -> PreCancelError:
    if str(attempt.order_type or "").upper() != "LIMIT":
        return PreCancelError("not_limit_order", "当前订单不是 LIMIT 订单，不需要周期收尾撤单。", "no_action")
    if attempt.status not in ELIGIBLE_SUBMISSION_STATUSES:
        return PreCancelError("submission_status_not_cancelable", "当前订单提交结果不允许周期收尾撤单。", "no_action")
    if not attempt.request_sent:
        return PreCancelError("submission_request_not_sent", "原订单提交请求未发出，不允许周期收尾撤单。", "no_action")
    if attempt.finished_at_utc is None:
        return PreCancelError("submission_not_finished", "原订单提交记录尚未完成，撤单前阻断。")
    if _lock_released_or_missing(attempt):
        return PreCancelError("active_lock_not_active", "ActiveLock 已不处于 active 状态，不执行周期收尾撤单。", "no_action")
    if _complete_fill_summary_exists(attempt):
        return PreCancelError("order_fill_already_complete", "订单成交事实已经完整收尾，不执行周期收尾撤单。", "no_action")
    if _latest_terminal_record(attempt.id) is not None:
        return PreCancelError("order_status_already_terminal", "订单状态已经确认终态，转交订单生命周期同步。", "sync_existing_terminal")
    if attempt.limit_valid_until_utc is None:
        return PreCancelError("limit_valid_until_missing", "LIMIT 订单缺少有效期截止时间，无法安全撤单。")
    if closeout_time_utc < _ensure_utc(attempt.limit_valid_until_utc):
        return PreCancelError("limit_order_not_expired", "LIMIT 订单尚未到达周期收尾时间。", "no_action")
    if not attempt.client_order_id:
        return PreCancelError("client_order_id_missing", "LIMIT 订单缺少 client_order_id，无法按冻结身份撤单。")
    identity_error = _market_identity_error(attempt)
    if identity_error:
        return PreCancelError(identity_error, "订单链路市场身份不一致，撤单前阻断。")
    return PreCancelError()


def _locked_attempt(order_submission_attempt_id: int) -> OrderSubmissionAttempt:
    return (
        OrderSubmissionAttempt.objects.select_for_update()
        .select_related("prepared_order_intent", "order_plan", "active_lock")
        .get(id=order_submission_attempt_id)
    )


def _lock_released_or_missing(attempt: OrderSubmissionAttempt) -> bool:
    return attempt.active_lock_id is None or attempt.active_lock.status != ActiveLockStatus.ACTIVE


def _complete_fill_summary_exists(attempt: OrderSubmissionAttempt) -> bool:
    return OrderFillSummary.objects.filter(order_submission_attempt=attempt, status__in=COMPLETE_FILL_SUMMARY_STATUSES).exists()


def _latest_terminal_record(attempt_id: int) -> OrderStatusSyncRecord | None:
    return (
        OrderStatusSyncRecord.objects.select_for_update()
        .filter(order_submission_attempt_id=attempt_id, query_outcome=OrderStatusQueryOutcome.FOUND, is_terminal_status=True)
        .order_by("-poll_sequence", "-id")
        .first()
    )


def _market_identity_error(attempt: OrderSubmissionAttempt) -> str:
    prepared = attempt.prepared_order_intent
    order_plan = attempt.order_plan
    lock = attempt.active_lock
    identities = [
        (attempt.market_type, attempt.account_domain, attempt.symbol),
        (prepared.market_type, prepared.account_domain, prepared.symbol),
        (order_plan.market_type, order_plan.account_domain, order_plan.symbol),
        (lock.market_type, lock.account_domain, lock.symbol),
    ]
    if len(set(identities)) != 1:
        return "market_identity_mismatch"
    if prepared.id != attempt.prepared_order_intent_id or order_plan.id != attempt.order_plan_id:
        return "order_chain_identity_mismatch"
    if lock.current_order_plan_id != attempt.order_plan_id:
        return "active_lock_order_plan_mismatch"
    return ""


def _frozen_cancel_request(attempt: OrderSubmissionAttempt) -> dict[str, Any]:
    request = {
        "symbol": attempt.symbol,
        "origClientOrderId": attempt.client_order_id,
        "order_submission_attempt_id": attempt.id,
        "prepared_order_intent_id": attempt.prepared_order_intent_id,
        "order_plan_id": attempt.order_plan_id,
        "active_lock_id": attempt.active_lock_id,
        "market_type": attempt.market_type,
        "account_domain": attempt.account_domain,
    }
    if attempt.exchange_order_id:
        request["orderId"] = attempt.exchange_order_id
    return request


def _create_cancel_attempt(
    *,
    attempt: OrderSubmissionAttempt,
    business_request_key: str,
    closeout_time_utc: datetime,
    cancel_reason_code: str,
    cancel_status: str,
    reason_code: str,
    cancel_request: dict[str, Any],
    reason_message: str,
    trace_id: str,
    trigger_source: str,
    now: datetime,
    finished_at_utc: datetime | None,
) -> OrderCancelAttempt:
    try:
        return OrderCancelAttempt.objects.create(
            order_cancel_attempt_key=_cancel_attempt_key(attempt, closeout_time_utc, cancel_reason_code),
            order_submission_attempt=attempt,
            prepared_order_intent=attempt.prepared_order_intent,
            order_plan=attempt.order_plan,
            active_lock=attempt.active_lock,
            business_request_key=business_request_key,
            exchange=attempt.exchange,
            market_type=attempt.market_type,
            account_domain=attempt.account_domain,
            endpoint_family=attempt.endpoint_family,
            symbol=attempt.symbol,
            client_order_id=attempt.client_order_id,
            exchange_order_id=attempt.exchange_order_id,
            closeout_time_utc=closeout_time_utc,
            limit_valid_until_utc=attempt.limit_valid_until_utc or closeout_time_utc,
            cancel_reason_code=cancel_reason_code,
            cancel_status=cancel_status,
            reason_code=reason_code,
            cancel_request=cancel_request,
            request_payload_hash=stable_hash(cancel_request) if cancel_request else "",
            reason_message=reason_message,
            trace_id=trace_id,
            trigger_source=trigger_source,
            started_at_utc=now,
            finished_at_utc=finished_at_utc,
        )
    except IntegrityError:
        return OrderCancelAttempt.objects.get(
            order_submission_attempt=attempt,
            closeout_time_utc=closeout_time_utc,
            cancel_reason_code=cancel_reason_code,
        )


def _call_cancel_gateway(record: OrderCancelAttempt, gateway: BinanceOrderCancelGateway) -> BinanceGatewayResult:
    try:
        return gateway.cancel_order(
            market_type=record.market_type,
            frozen_cancel_request=record.cancel_request,
            call_context=BinanceGatewayCallContext(
                trace_id=record.trace_id,
                trigger_source=record.trigger_source,
                operation="cancel_order",
                market_type=record.market_type,
                account_domain=record.account_domain,
                symbol=record.symbol,
                business_object_type="OrderCancelAttempt",
                business_object_id=str(record.id),
                request_time_utc=timezone.now(),
                metadata={
                    "order_cancel_attempt_id": record.id,
                    "order_submission_attempt_id": record.order_submission_attempt_id,
                    "prepared_order_intent_id": record.prepared_order_intent_id,
                    "active_lock_id": record.active_lock_id,
                    "client_order_id": record.client_order_id,
                    "exchange_order_id": record.exchange_order_id,
                },
            ),
        )
    except Exception as exc:
        now = timezone.now()
        return BinanceGatewayResult(
            operation="cancel_order",
            market_type=record.market_type,
            endpoint_family=record.endpoint_family,
            success=False,
            request_sent=True,
            response_received=False,
            error_category="gateway_failed",
            sanitized_error_message=type(exc).__name__,
            request_started_at_utc=now,
            request_finished_at_utc=now,
            attempt_count=1,
            trace_id=record.trace_id,
        )


def _finalize_cancel_result(record_id: int, gateway_result: BinanceGatewayResult) -> OrderCancelAttempt:
    with transaction.atomic():
        record = OrderCancelAttempt.objects.select_for_update().get(id=record_id)
        if record.finished_at_utc is not None:
            return record
        payload = sanitize_mapping(gateway_result.payload if isinstance(gateway_result.payload, dict) else {"payload": gateway_result.payload})
        classification = _classify_cancel_result(gateway_result)
        record.cancel_status = classification["status"]
        record.reason_code = classification["reason_code"]
        record.reason_message = classification["message"]
        record.request_sent = bool(gateway_result.request_sent)
        record.response_received = bool(gateway_result.response_received)
        record.gateway_attempt_count = int(gateway_result.attempt_count or 0)
        record.http_status = gateway_result.http_status
        record.binance_error_code = str(gateway_result.binance_error_code or "")
        record.sanitized_error_message = str(gateway_result.sanitized_error_message or "")[:500]
        record.sanitized_response = payload
        record.response_hash = stable_hash(payload) if payload else ""
        record.rate_limit_metadata = gateway_result.rate_limit_metadata
        record.finished_at_utc = gateway_result.request_finished_at_utc or timezone.now()
        record.save()
        return record


def _classify_cancel_result(result: BinanceGatewayResult) -> dict[str, str]:
    if result.request_sent and int(result.attempt_count or 0) != 1:
        return {
            "status": OrderCancelAttemptStatus.UNKNOWN,
            "reason_code": "gateway_contract_violation",
            "message": "撤单 Gateway 返回了非单次尝试结果，按未知处理。",
        }
    if result.success and result.request_sent and result.response_received:
        return {
            "status": OrderCancelAttemptStatus.ACCEPTED,
            "reason_code": "order_cancel_accepted",
            "message": "限价单周期收尾撤单请求已被交易所接受。",
        }
    if result.error_category == ERROR_ORDER_NOT_FOUND and result.request_sent and result.response_received:
        return {
            "status": OrderCancelAttemptStatus.NOT_FOUND,
            "reason_code": "order_cancel_not_found",
            "message": "交易所明确未找到目标订单；仍需通过订单状态同步完成后续确认。",
        }
    if not result.request_sent:
        return {
            "status": OrderCancelAttemptStatus.BLOCKED_BEFORE_CANCEL,
            "reason_code": "order_cancel_blocked_before_cancel",
            "message": result.sanitized_error_message or "撤单请求未发出。",
        }
    return {
        "status": OrderCancelAttemptStatus.UNKNOWN,
        "reason_code": "order_cancel_unknown",
        "message": result.sanitized_error_message or "无法确认撤单结果。",
    }


def _run_lifecycle_sync_if_needed(
    record: OrderCancelAttempt,
    *,
    order_status_gateway: Any | None,
    fill_query_gateway: Any | None,
) -> ServiceResult | None:
    if record.cancel_status not in {
        OrderCancelAttemptStatus.ACCEPTED,
        OrderCancelAttemptStatus.NOT_FOUND,
        OrderCancelAttemptStatus.UNKNOWN,
    }:
        return None
    return run_order_lifecycle_pipeline(
        order_submission_attempt_id=record.order_submission_attempt_id,
        business_request_key=f"{record.business_request_key}:lifecycle",
        trace_id=record.trace_id,
        trigger_source=record.trigger_source,
        order_status_gateway=order_status_gateway,
        fill_query_gateway=fill_query_gateway,
    )


def _sync_existing_terminal_result(
    attempt: OrderSubmissionAttempt,
    business_request_key: str,
    trace_id: str,
    trigger_source: str,
) -> ServiceResult:
    lifecycle_result = run_order_lifecycle_pipeline(
        order_submission_attempt_id=attempt.id,
        business_request_key=f"{business_request_key}:already-terminal",
        trace_id=trace_id,
        trigger_source=trigger_source,
    )
    return _result(
        lifecycle_result.status,
        "order_status_already_terminal",
        "订单已存在终态记录，未执行撤单，已转交订单生命周期同步。",
        trace_id,
        trigger_source,
        closeout_action="COMPLETE",
        order_submission_attempt_id=attempt.id,
        data={"lifecycle_result": _compact_result(lifecycle_result)},
    )

def _record_alert_if_needed(record: OrderCancelAttempt, *, replay: bool = False) -> None:
    event_type = _event_type(record, replay=replay)
    alert_id = record_order_cancel_alert(record, event_type)
    if alert_id is not None and alert_id not in record.alert_event_ids:
        record.alert_event_ids = [*record.alert_event_ids, alert_id]
        record.save(update_fields=["alert_event_ids", "updated_at_utc"])


def _event_type(record: OrderCancelAttempt, *, replay: bool) -> str:
    if replay:
        return "order_cancel_idempotent_replay"
    if record.reason_code == "gateway_contract_violation":
        return "order_cancel_gateway_contract_violation"
    return f"order_cancel_{record.cancel_status}"


def _cancel_in_progress_result(record: OrderCancelAttempt, trace_id: str, trigger_source: str) -> ServiceResult:
    return _result(
        ResultStatus.NO_ACTION,
        "order_cancel_in_progress",
        "限价单周期收尾撤单已开始但尚未完成，不重复调用 Gateway。",
        trace_id,
        trigger_source,
        closeout_action="WAIT",
        order_submission_attempt_id=record.order_submission_attempt_id,
        data={"order_cancel_attempt_id": record.id},
    )


def _no_action_result(attempt: OrderSubmissionAttempt, reason_code: str, message: str, trace_id: str, trigger_source: str) -> ServiceResult:
    return _result(
        ResultStatus.NO_ACTION,
        reason_code,
        message,
        trace_id,
        trigger_source,
        closeout_action="COMPLETE",
        order_submission_attempt_id=attempt.id,
        data={"order_cancel_attempt_id": None},
    )


def _result_from_cancel_attempt(
    record: OrderCancelAttempt,
    *,
    replay: bool = False,
    lifecycle_result: ServiceResult | None = None,
) -> ServiceResult:
    status = _service_status(record)
    reason_code = "order_cancel_idempotent_replay" if replay else (record.reason_code or record.cancel_reason_code)
    message = "OrderCycleCloseout 幂等重放，未重新调用 Gateway。" if replay else record.reason_message
    data = {
        "order_cancel_attempt_id": record.id,
        "order_submission_attempt_id": record.order_submission_attempt_id,
        "cancel_status": record.cancel_status,
        "request_sent": record.request_sent,
        "response_received": record.response_received,
        "closeout_action": _closeout_action(record),
    }
    if lifecycle_result is not None:
        data["lifecycle_result"] = _compact_result(lifecycle_result)
        data["order_status_sync_record_id"] = lifecycle_result.data.get("order_status_sync_record_id")
        data["fill_sync_result_id"] = lifecycle_result.data.get("fill_sync_result_id")
    return ServiceResult(status, reason_code, message, record.trace_id, record.trigger_source, data)


def _service_status(record: OrderCancelAttempt) -> ResultStatus:
    if record.cancel_status == OrderCancelAttemptStatus.ACCEPTED:
        return ResultStatus.SUCCEEDED
    if record.cancel_status in {OrderCancelAttemptStatus.NOT_FOUND, OrderCancelAttemptStatus.UNKNOWN}:
        return ResultStatus.UNKNOWN
    if record.cancel_status == OrderCancelAttemptStatus.FAILED_BEFORE_CANCEL:
        return ResultStatus.FAILED
    if record.cancel_status == OrderCancelAttemptStatus.BLOCKED_BEFORE_CANCEL:
        return ResultStatus.BLOCKED
    return ResultStatus.NO_ACTION


def _closeout_action(record: OrderCancelAttempt) -> str:
    if record.cancel_status in {
        OrderCancelAttemptStatus.ACCEPTED,
        OrderCancelAttemptStatus.NOT_FOUND,
        OrderCancelAttemptStatus.UNKNOWN,
    }:
        return "CONTINUE_TO_ORDER_LIFECYCLE_SYNC"
    if record.cancel_status == OrderCancelAttemptStatus.CANCELING:
        return "WAIT"
    return "STOP"


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
    closeout_action: str,
    order_submission_attempt_id: int | None,
    data: dict[str, Any] | None = None,
) -> ServiceResult:
    payload = {
        "order_submission_attempt_id": order_submission_attempt_id,
        "closeout_action": closeout_action,
    }
    if data:
        payload.update(data)
    return ServiceResult(status, reason_code, message, trace_id, trigger_source, payload)


def _cancel_attempt_key(attempt: OrderSubmissionAttempt, closeout_time_utc: datetime, cancel_reason_code: str) -> str:
    return stable_hash(
        {
            "object_type": "order_cancel_attempt",
            "schema_version": "1.0",
            "order_submission_attempt_id": attempt.id,
            "prepared_order_intent_id": attempt.prepared_order_intent_id,
            "active_lock_id": attempt.active_lock_id,
            "limit_valid_until_utc": _ensure_utc(attempt.limit_valid_until_utc).isoformat() if attempt.limit_valid_until_utc else "",
            "closeout_time_utc": closeout_time_utc.isoformat(),
            "cancel_reason_code": cancel_reason_code,
        }
    )[:MAX_KEY_LENGTH]


def _request_error(
    *,
    order_submission_attempt_id: int,
    business_request_key: str,
    closeout_time_utc: datetime,
    trace_id: str,
    trigger_source: str,
    cancel_reason_code: str,
) -> str:
    if not isinstance(order_submission_attempt_id, int) or order_submission_attempt_id <= 0:
        return "order_submission_attempt_id_invalid"
    if not isinstance(business_request_key, str) or not business_request_key.strip() or len(business_request_key) > MAX_KEY_LENGTH - 20:
        return "business_request_key_invalid"
    if not isinstance(closeout_time_utc, datetime):
        return "closeout_time_invalid"
    if not trace_id or not trigger_source or len(trace_id) > MAX_TRACE_FIELD_LENGTH or len(trigger_source) > MAX_TRACE_FIELD_LENGTH:
        return "trace_context_missing"
    if not isinstance(cancel_reason_code, str) or not cancel_reason_code.strip() or len(cancel_reason_code) > 120:
        return "cancel_reason_code_invalid"
    return ""


def _ensure_utc(value: datetime) -> datetime:
    if timezone.is_naive(value):
        return timezone.make_aware(value, UTC)
    return value.astimezone(UTC)
