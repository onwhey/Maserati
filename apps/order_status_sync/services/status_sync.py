"""OrderStatusSync 模块：查询已存在订单提交尝试的交易所状态；读写 MySQL；不访问 Redis；通过 BinanceGateway 访问 Binance；不发送 Hermes；不调用大模型；不提交订单。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from django.conf import settings
from django.db import DatabaseError, IntegrityError, transaction
from django.utils import timezone

from apps.audit.services import record_audit
from apps.binance_gateway.order_status import BinanceOrderStatusGateway, get_order_status_gateway
from apps.binance_gateway.types import ERROR_ORDER_NOT_FOUND, BinanceGatewayCallContext, BinanceGatewayResult
from apps.execution.models import OrderSubmissionAttempt, OrderSubmissionAttemptStatus
from apps.foundation.redaction import sanitize_mapping
from apps.foundation.results import ResultStatus, ServiceResult
from apps.order_plan.models import ActiveLockStatus

from ..models import OrderStatusQueryOutcome, OrderStatusSubmissionResolution, OrderStatusSyncRecord
from .alerts import record_order_status_sync_alert, record_order_status_timeout_alert
from .hashing import order_status_response_hash, order_status_sync_key_hash


MAX_KEY_LENGTH = 191
MAX_TRACE_FIELD_LENGTH = 80
POLL_MODE_IMMEDIATE = "immediate"
POLL_MODE_RECOVERY = "recovery"
TERMINAL_STATUSES = {"FILLED", "CANCELED", "REJECTED", "EXPIRED", "EXPIRED_IN_MATCH"}
NON_TERMINAL_STATUSES = {"NEW", "PARTIALLY_FILLED"}
QUERYABLE_SUBMISSION_STATUSES = {
    OrderSubmissionAttemptStatus.ACCEPTED,
    OrderSubmissionAttemptStatus.UNKNOWN,
}


@dataclass(frozen=True)
class PollClaim:
    record: OrderStatusSyncRecord | None = None
    should_call_gateway: bool = False
    replay: bool = False
    result: ServiceResult | None = None


@dataclass(frozen=True)
class PollTiming:
    started: datetime
    deadline: datetime
    scheduled: datetime
    interval_seconds: int
    max_duration_seconds: int
    max_poll_sequence: int


def start_order_status_polling(
    *,
    order_submission_attempt_id: int,
    business_request_key: str,
    trace_id: str,
    trigger_source: str,
    gateway: BinanceOrderStatusGateway | None = None,
) -> ServiceResult:
    return poll_order_status(
        order_submission_attempt_id=order_submission_attempt_id,
        business_request_key=business_request_key,
        poll_sequence=1,
        trace_id=trace_id,
        trigger_source=trigger_source,
        gateway=gateway,
    )


def recover_order_status_once(
    *,
    order_submission_attempt_id: int,
    operator_id: str,
    reason: str,
    trace_id: str,
    trigger_source: str = "ops_console_order_status_recovery",
    gateway: BinanceOrderStatusGateway | None = None,
) -> ServiceResult:
    reason = reason.strip()
    if not reason:
        return _result_without_record("order_status_recovery_reason_required", "订单状态受控补查需要记录人工原因。", trace_id, trigger_source)
    if not operator_id:
        return _result_without_record("operator_required", "订单状态受控补查需要记录操作者。", trace_id, trigger_source)
    try:
        with transaction.atomic():
            attempt = _locked_attempt(order_submission_attempt_id)
    except OrderSubmissionAttempt.DoesNotExist:
        return _result_without_record("order_submission_attempt_not_found", "OrderSubmissionAttempt 不存在", trace_id, trigger_source)

    business_request_key = f"ops_order_status_recovery:{order_submission_attempt_id}:{trace_id}"
    existing = (
        OrderStatusSyncRecord.objects.filter(
            order_submission_attempt=attempt,
            poll_mode=POLL_MODE_RECOVERY,
            business_request_key=business_request_key,
        )
        .order_by("-poll_sequence", "-id")
        .first()
    )
    if existing is not None:
        result = _result_from_record(existing, replay=True)
    else:
        result = poll_order_status(
            order_submission_attempt_id=order_submission_attempt_id,
            business_request_key=business_request_key,
            poll_sequence=_next_recovery_sequence(order_submission_attempt_id),
            trace_id=trace_id,
            trigger_source=trigger_source,
            gateway=gateway,
            poll_mode=POLL_MODE_RECOVERY,
        )

    audit = record_audit(
        operator_id=operator_id,
        operation_type="order_status_controlled_recheck",
        target_object_type="OrderSubmissionAttempt",
        target_object_id=str(order_submission_attempt_id),
        before_state_summary={
            "attempt_status": attempt.status,
            "client_order_id": attempt.client_order_id,
            "exchange_order_id": attempt.exchange_order_id,
        },
        after_state_summary=result.data,
        reason=reason[:500],
        evidence={"poll_mode": POLL_MODE_RECOVERY, "trace_id": trace_id},
        result=result.status.value,
        trace_id=trace_id,
        trigger_source=trigger_source,
    )
    return ServiceResult(
        result.status,
        result.reason_code,
        result.message,
        result.trace_id,
        result.trigger_source,
        {**result.data, "audit_record_id": audit.id},
    )


def poll_order_status(
    *,
    order_submission_attempt_id: int,
    business_request_key: str,
    poll_sequence: int,
    trace_id: str,
    trigger_source: str,
    gateway: BinanceOrderStatusGateway | None = None,
    poll_mode: str = POLL_MODE_IMMEDIATE,
) -> ServiceResult:
    request_error = _request_error(order_submission_attempt_id, business_request_key, poll_sequence, trace_id, trigger_source)
    if request_error:
        return _result_without_record(request_error, "OrderStatusSync 请求合同不完整", trace_id, trigger_source)
    try:
        claim = _claim_poll_record(
            order_submission_attempt_id=order_submission_attempt_id,
            business_request_key=business_request_key,
            poll_sequence=poll_sequence,
            poll_mode=poll_mode,
            trace_id=trace_id,
            trigger_source=trigger_source,
        )
    except OrderSubmissionAttempt.DoesNotExist:
        return _result_without_record("order_submission_attempt_not_found", "OrderSubmissionAttempt 不存在", trace_id, trigger_source)
    except DatabaseError as exc:
        return _result_without_record("internal_error", type(exc).__name__, trace_id, trigger_source, failed=True)

    if claim.result is not None:
        return claim.result
    if claim.record is None:
        return _result_without_record("order_status_claim_failed", "未能创建订单状态查询记录", trace_id, trigger_source, failed=True)
    if claim.replay or not claim.should_call_gateway:
        _record_alert_if_needed(claim.record, replay=claim.replay)
        return _result_from_record(claim.record, replay=claim.replay)

    gateway_result = _call_gateway(claim.record, gateway or get_order_status_gateway())
    record = _finalize_gateway_result(claim.record.id, gateway_result)
    _record_alert_if_needed(record)
    return _result_from_record(record)


def _claim_poll_record(
    *,
    order_submission_attempt_id: int,
    business_request_key: str,
    poll_sequence: int,
    poll_mode: str,
    trace_id: str,
    trigger_source: str,
) -> PollClaim:
    now = timezone.now()
    with transaction.atomic():
        attempt = _locked_attempt(order_submission_attempt_id)
        existing = OrderStatusSyncRecord.objects.select_for_update().filter(
            order_submission_attempt=attempt,
            poll_mode=poll_mode,
            poll_sequence=poll_sequence,
        ).first()
        if existing is not None:
            if existing.query_finished_at_utc is None:
                return PollClaim(result=_poll_in_progress_result(existing, trace_id, trigger_source))
            return PollClaim(record=existing, replay=True)

        terminal = _latest_terminal_record(attempt.id)
        if terminal is not None:
            return PollClaim(result=_already_terminal_result(terminal, trace_id, trigger_source))

        pre_error = _pre_query_error(attempt)
        if poll_mode == POLL_MODE_RECOVERY and not pre_error:
            pre_error = _recovery_pre_query_error(attempt, now)
        timing = _poll_timing(attempt, poll_sequence)
        outcome = _outcome_for_pre_error(pre_error)
        if pre_error:
            record = _create_record(
                attempt=attempt,
                business_request_key=business_request_key,
                poll_mode=poll_mode,
                poll_sequence=poll_sequence,
                timing=timing,
                trace_id=trace_id,
                trigger_source=trigger_source,
                query_outcome=outcome,
                reason_code=pre_error,
                reason_message=_reason_message(pre_error),
                query_finished_at_utc=now,
            )
            return PollClaim(record=record, should_call_gateway=False)

        if poll_mode != POLL_MODE_RECOVERY:
            timing_result = _timing_result(attempt, timing, poll_mode, poll_sequence, trace_id, trigger_source)
            if timing_result is not None:
                return PollClaim(result=timing_result)

            previous_result = _previous_poll_result(attempt.id, poll_mode, poll_sequence, trace_id, trigger_source)
            if previous_result is not None:
                return PollClaim(result=previous_result)

        record = _create_record(
            attempt=attempt,
            business_request_key=business_request_key,
            poll_mode=poll_mode,
            poll_sequence=poll_sequence,
            timing=timing,
            trace_id=trace_id,
            trigger_source=trigger_source,
            query_outcome=OrderStatusQueryOutcome.UNKNOWN,
            reason_code="order_status_query_claimed",
            reason_message=_reason_message("order_status_query_claimed"),
            query_finished_at_utc=None,
        )
        return PollClaim(record=record, should_call_gateway=True)


def _locked_attempt(order_submission_attempt_id: int) -> OrderSubmissionAttempt:
    return (
        OrderSubmissionAttempt.objects.select_for_update()
        .select_related("prepared_order_intent", "order_plan", "active_lock")
        .get(id=order_submission_attempt_id)
    )


def _poll_timing(attempt: OrderSubmissionAttempt, poll_sequence: int) -> PollTiming:
    polling_started = _ensure_utc(attempt.finished_at_utc) if attempt.finished_at_utc else timezone.now()
    interval = max(1, int(getattr(settings, "ORDER_STATUS_POLL_INTERVAL_SECONDS", 2)))
    max_duration = max(interval, int(getattr(settings, "ORDER_STATUS_POLL_MAX_DURATION_SECONDS", 30)))
    deadline = polling_started + timedelta(seconds=max_duration)
    scheduled = polling_started + timedelta(seconds=interval * poll_sequence)
    return PollTiming(
        started=polling_started,
        deadline=deadline,
        scheduled=scheduled,
        interval_seconds=interval,
        max_duration_seconds=max_duration,
        max_poll_sequence=max_duration // interval,
    )


def _timing_result(
    attempt: OrderSubmissionAttempt,
    timing: PollTiming,
    poll_mode: str,
    poll_sequence: int,
    trace_id: str,
    trigger_source: str,
) -> ServiceResult | None:
    now = timezone.now()
    if poll_sequence > timing.max_poll_sequence or timing.scheduled > timing.deadline:
        return _polling_timeout_result(attempt, timing, poll_mode, poll_sequence, trace_id, trigger_source)
    if now < timing.scheduled:
        return ServiceResult(
            ResultStatus.NO_ACTION,
            "poll_not_due",
            "本轮订单状态查询尚未到计划时间",
            trace_id,
            trigger_source,
            {"flow_action": "WAIT", "next_poll_at_utc": timing.scheduled.isoformat()},
        )
    if now > timing.deadline:
        return _polling_timeout_result(attempt, timing, poll_mode, poll_sequence, trace_id, trigger_source)
    return None


def _polling_timeout_result(
    attempt: OrderSubmissionAttempt,
    timing: PollTiming,
    poll_mode: str,
    poll_sequence: int,
    trace_id: str,
    trigger_source: str,
) -> ServiceResult:
    record_order_status_timeout_alert(
        order_submission_attempt_id=attempt.id,
        business_request_key=attempt.business_request_key,
        poll_mode=poll_mode,
        poll_sequence=poll_sequence,
        polling_deadline_utc=timing.deadline.isoformat(),
        trace_id=trace_id,
        trigger_source=trigger_source,
    )
    return ServiceResult(
        ResultStatus.UNKNOWN,
        "polling_timeout",
        "订单状态立即轮询窗口已结束，未发起新的查询",
        trace_id,
        trigger_source,
        {
            "order_submission_attempt_id": attempt.id,
            "order_status_sync_record_id": None,
            "flow_action": "STOP",
            "polling_deadline_utc": timing.deadline.isoformat(),
            "allows_fill_sync": False,
        },
    )


def _poll_in_progress_result(record: OrderStatusSyncRecord, trace_id: str, trigger_source: str) -> ServiceResult:
    return ServiceResult(
        ResultStatus.NO_ACTION,
        "poll_in_progress",
        "本轮订单状态查询已经开始但尚未完成，不能重复调用 Gateway。",
        trace_id,
        trigger_source,
        {
            "order_status_sync_record_id": record.id,
            "order_submission_attempt_id": record.order_submission_attempt_id,
            "flow_action": "WAIT",
            "allows_fill_sync": False,
        },
    )


def _previous_poll_result(
    attempt_id: int,
    poll_mode: str,
    poll_sequence: int,
    trace_id: str,
    trigger_source: str,
) -> ServiceResult | None:
    if poll_sequence <= 1:
        return None
    previous = OrderStatusSyncRecord.objects.filter(
        order_submission_attempt_id=attempt_id,
        poll_mode=poll_mode,
        poll_sequence=poll_sequence - 1,
    ).first()
    if previous is None:
        return ServiceResult(ResultStatus.NO_ACTION, "previous_poll_missing", "上一轮订单状态查询尚不存在", trace_id, trigger_source, {"flow_action": "WAIT"})
    if previous.query_finished_at_utc is None:
        return ServiceResult(ResultStatus.NO_ACTION, "previous_poll_in_progress", "上一轮订单状态查询尚未完成", trace_id, trigger_source, {"flow_action": "WAIT"})
    return None


def _pre_query_error(attempt: OrderSubmissionAttempt) -> str:
    if not getattr(settings, "ORDER_STATUS_SYNC_ENABLED", False):
        return "order_status_sync_disabled"
    if attempt.status not in QUERYABLE_SUBMISSION_STATUSES:
        return "submission_status_not_queryable"
    if attempt.finished_at_utc is None:
        return "submission_not_finished"
    if not attempt.market_type or not attempt.account_domain or not attempt.symbol:
        return "market_identity_missing"
    if not attempt.client_order_id and not attempt.exchange_order_id:
        return "query_identifier_missing"
    return ""


def _recovery_pre_query_error(attempt: OrderSubmissionAttempt, now: datetime) -> str:
    if attempt.active_lock_id is None or attempt.active_lock.status != ActiveLockStatus.ACTIVE:
        return "active_lock_not_active_for_recovery"
    recovery_window = max(0, int(getattr(settings, "ORDER_STATUS_RECOVERY_WINDOW_SECONDS", 86400)))
    if now > _ensure_utc(attempt.finished_at_utc) + timedelta(seconds=recovery_window):
        return "order_status_recovery_out_of_window"
    return ""


def _create_record(
    *,
    attempt: OrderSubmissionAttempt,
    business_request_key: str,
    poll_mode: str,
    poll_sequence: int,
    timing: PollTiming,
    trace_id: str,
    trigger_source: str,
    query_outcome: str,
    reason_code: str,
    reason_message: str,
    query_finished_at_utc: datetime | None,
) -> OrderStatusSyncRecord:
    identifier_type, client_id, exchange_id = _query_identifier(attempt)
    try:
        return OrderStatusSyncRecord.objects.create(
            order_status_sync_key=_record_key(attempt, poll_mode, poll_sequence),
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
            query_identifier_type=identifier_type,
            client_order_id=client_id,
            exchange_order_id_requested=exchange_id,
            poll_mode=poll_mode,
            poll_sequence=poll_sequence,
            polling_started_at_utc=timing.started,
            polling_deadline_utc=timing.deadline,
            scheduled_at_utc=timing.scheduled,
            query_started_at_utc=timezone.now(),
            query_finished_at_utc=query_finished_at_utc,
            query_outcome=query_outcome,
            reason_code=reason_code,
            reason_message=reason_message,
            trace_id=trace_id,
            trigger_source=trigger_source,
        )
    except IntegrityError:
        return OrderStatusSyncRecord.objects.get(order_submission_attempt=attempt, poll_mode=poll_mode, poll_sequence=poll_sequence)


def _call_gateway(record: OrderStatusSyncRecord, gateway: BinanceOrderStatusGateway) -> BinanceGatewayResult:
    try:
        return gateway.query_order(
            market_type=record.market_type,
            symbol=record.symbol,
            client_order_id=record.client_order_id or None,
            exchange_order_id=record.exchange_order_id_requested or None,
            call_context=BinanceGatewayCallContext(
                trace_id=record.trace_id,
                trigger_source=record.trigger_source,
                operation="query_order",
                market_type=record.market_type,
                account_domain=record.account_domain,
                symbol=record.symbol,
                business_object_type="OrderSubmissionAttempt",
                business_object_id=str(record.order_submission_attempt_id),
                request_time_utc=timezone.now(),
                metadata={
                    "order_status_sync_record_id": record.id,
                    "poll_mode": record.poll_mode,
                    "poll_sequence": record.poll_sequence,
                    "client_order_id": record.client_order_id,
                    "exchange_order_id": record.exchange_order_id_requested,
                },
            ),
        )
    except Exception as exc:
        now = timezone.now()
        return BinanceGatewayResult(
            operation="query_order",
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


def _finalize_gateway_result(record_id: int, gateway_result: BinanceGatewayResult) -> OrderStatusSyncRecord:
    with transaction.atomic():
        record = OrderStatusSyncRecord.objects.select_for_update().get(id=record_id)
        if record.query_finished_at_utc is not None:
            return record
        payload = sanitize_mapping(gateway_result.payload if isinstance(gateway_result.payload, dict) else {"payload": gateway_result.payload})
        classification = _classify_gateway_result(record, gateway_result, payload)
        record.query_outcome = classification["query_outcome"]
        record.reason_code = classification["reason_code"]
        record.reason_message = classification["reason_message"]
        record.request_sent = bool(gateway_result.request_sent)
        record.response_received = bool(gateway_result.response_received)
        record.gateway_attempt_count = int(gateway_result.attempt_count or 0)
        record.gateway_latency_ms = int(gateway_result.latency_ms or 0)
        record.http_status = gateway_result.http_status
        record.binance_error_code = str(gateway_result.binance_error_code or "")
        record.sanitized_error_message = str(gateway_result.sanitized_error_message or "")[:500]
        record.exchange_order_id_returned = str(payload.get("orderId") or "")
        record.exchange_client_order_id_returned = str(payload.get("clientOrderId") or payload.get("client_order_id") or "")
        record.exchange_status = str(payload.get("status") or "").upper()
        record.exchange_status_observed_at_utc = gateway_result.request_finished_at_utc or timezone.now()
        record.is_recognized_status = bool(classification["is_recognized_status"])
        record.is_terminal_status = bool(classification["is_terminal_status"])
        record.submission_resolution_status = classification["submission_resolution_status"]
        record.sanitized_response = payload
        record.response_hash = order_status_response_hash(payload) if payload else ""
        record.rate_limit_metadata = gateway_result.rate_limit_metadata
        record.query_finished_at_utc = gateway_result.request_finished_at_utc or timezone.now()
        record.save()
        return record


def _classify_gateway_result(record: OrderStatusSyncRecord, result: BinanceGatewayResult, payload: dict[str, Any]) -> dict[str, Any]:
    if result.success and result.request_sent and result.response_received:
        return _classify_found_payload(record, payload)
    if result.error_category == ERROR_ORDER_NOT_FOUND and result.request_sent and result.response_received:
        return _classification("not_found", "order_status_not_found", "Binance 明确未找到目标订单。")
    if not result.request_sent:
        return _classification("failed_before_query", "order_status_failed_before_send", "Gateway 确认订单状态查询未发出。")
    return _classification("unknown", "order_status_unknown", "无法确认交易所订单状态查询结果。")


def _classify_found_payload(record: OrderStatusSyncRecord, payload: dict[str, Any]) -> dict[str, Any]:
    if not _identity_matches(record, payload):
        return _classification("unknown", "response_identity_mismatch", "订单状态查询响应身份与原提交记录不一致。")
    exchange_status = str(payload.get("status") or "").upper()
    if exchange_status in TERMINAL_STATUSES:
        return _classification("found", f"exchange_status_{exchange_status.lower()}", "订单状态查询确认交易所订单终态。", True, True)
    if exchange_status in NON_TERMINAL_STATUSES:
        return _classification("found", f"exchange_status_{exchange_status.lower()}", "订单仍处于交易所非终态。", True, False)
    return _classification("unknown", "unsupported_exchange_status", "交易所返回了当前系统未识别的订单状态。", False, False)


def _classification(
    query_outcome: str,
    reason_code: str,
    reason_message: str,
    is_recognized_status: bool = False,
    is_terminal_status: bool = False,
) -> dict[str, Any]:
    if query_outcome == "found" and is_terminal_status:
        resolution = OrderStatusSubmissionResolution.TERMINAL_CONFIRMED
    elif query_outcome == "found":
        resolution = OrderStatusSubmissionResolution.ORDER_FOUND
    else:
        resolution = OrderStatusSubmissionResolution.UNRESOLVED
    return {
        "query_outcome": query_outcome,
        "reason_code": reason_code,
        "reason_message": reason_message,
        "is_recognized_status": is_recognized_status,
        "is_terminal_status": is_terminal_status,
        "submission_resolution_status": resolution,
    }


def _identity_matches(record: OrderStatusSyncRecord, payload: dict[str, Any]) -> bool:
    returned_symbol = str(payload.get("symbol") or "").upper()
    if returned_symbol and returned_symbol != record.symbol.upper():
        return False
    returned_client_id = str(payload.get("clientOrderId") or payload.get("client_order_id") or "")
    if record.client_order_id and returned_client_id and returned_client_id != record.client_order_id:
        return False
    returned_order_id = str(payload.get("orderId") or "")
    if record.exchange_order_id_requested and returned_order_id and returned_order_id != record.exchange_order_id_requested:
        return False
    return bool(returned_symbol or returned_client_id or returned_order_id)


def _result_from_record(record: OrderStatusSyncRecord, *, replay: bool = False) -> ServiceResult:
    status = _service_status(record)
    flow_action = _flow_action(record)
    reason_code = "order_status_sync_idempotent_replay" if replay else record.reason_code
    message = "OrderStatusSync 幂等重放，未重新调用 Gateway。" if replay else record.reason_message
    return ServiceResult(status, reason_code, message, record.trace_id, record.trigger_source, _record_data(record, flow_action))


def _record_data(record: OrderStatusSyncRecord, flow_action: str) -> dict[str, Any]:
    return {
        "order_status_sync_record_id": record.id,
        "order_submission_attempt_id": record.order_submission_attempt_id,
        "query_outcome": record.query_outcome,
        "exchange_status": record.exchange_status,
        "is_terminal_status": record.is_terminal_status,
        "submission_resolution_status": record.submission_resolution_status,
        "allows_fill_sync": record.query_outcome == OrderStatusQueryOutcome.FOUND and record.is_terminal_status,
        "allows_next_poll": _allows_next_poll(record),
        "active_lock_id": record.active_lock_id,
        "flow_action": flow_action,
    }


def _service_status(record: OrderStatusSyncRecord) -> ResultStatus:
    if record.query_outcome == OrderStatusQueryOutcome.FOUND and record.is_terminal_status:
        return ResultStatus.SUCCEEDED
    if record.query_outcome in {OrderStatusQueryOutcome.UNKNOWN, OrderStatusQueryOutcome.NOT_FOUND}:
        return ResultStatus.UNKNOWN
    if record.query_outcome == OrderStatusQueryOutcome.FAILED_BEFORE_QUERY:
        return ResultStatus.FAILED
    if record.query_outcome == OrderStatusQueryOutcome.BLOCKED_BEFORE_QUERY:
        return ResultStatus.BLOCKED
    return ResultStatus.NO_ACTION


def _flow_action(record: OrderStatusSyncRecord) -> str:
    if record.query_outcome == OrderStatusQueryOutcome.FOUND and record.is_terminal_status:
        return "CONTINUE"
    if record.poll_mode == POLL_MODE_RECOVERY:
        return "STOP"
    if _allows_next_poll(record):
        return "WAIT"
    return "STOP"


def _allows_next_poll(record: OrderStatusSyncRecord) -> bool:
    if record.poll_mode == POLL_MODE_RECOVERY:
        return False
    return (
        record.query_outcome in {OrderStatusQueryOutcome.FOUND, OrderStatusQueryOutcome.UNKNOWN, OrderStatusQueryOutcome.NOT_FOUND}
        and not record.is_terminal_status
        and record.scheduled_at_utc < record.polling_deadline_utc
    )


def _record_alert_if_needed(record: OrderStatusSyncRecord, *, replay: bool = False) -> None:
    event_type = _event_type(record, replay=replay)
    alert_id = record_order_status_sync_alert(record, event_type)
    if alert_id is not None and alert_id not in record.alert_event_ids:
        record.alert_event_ids = [*record.alert_event_ids, alert_id]
        record.save(update_fields=["alert_event_ids", "updated_at_utc"])


def _event_type(record: OrderStatusSyncRecord, *, replay: bool) -> str:
    if replay:
        return "order_status_sync_idempotent_replay"
    if record.reason_code == "unsupported_exchange_status":
        return "order_status_sync_unknown_status"
    if record.reason_code == "response_identity_mismatch":
        return "order_status_sync_identity_mismatch"
    if record.query_outcome == OrderStatusQueryOutcome.FOUND and record.is_terminal_status:
        return "order_status_sync_terminal"
    if record.query_outcome == OrderStatusQueryOutcome.FOUND:
        return "order_status_sync_found"
    return f"order_status_sync_{record.query_outcome}"


def _already_terminal_result(record: OrderStatusSyncRecord, trace_id: str, trigger_source: str) -> ServiceResult:
    data = _record_data(record, "CONTINUE")
    data["already_terminal_record_id"] = record.id
    return ServiceResult(ResultStatus.SUCCEEDED, "order_status_already_terminal", "订单状态已经确认终态，不再查询。", trace_id, trigger_source, data)


def _latest_terminal_record(attempt_id: int) -> OrderStatusSyncRecord | None:
    return (
        OrderStatusSyncRecord.objects.select_for_update()
        .filter(order_submission_attempt_id=attempt_id, query_outcome=OrderStatusQueryOutcome.FOUND, is_terminal_status=True)
        .order_by("-poll_sequence", "-id")
        .first()
    )


def _query_identifier(attempt: OrderSubmissionAttempt) -> tuple[str, str, str]:
    if attempt.client_order_id:
        return "client_order_id", attempt.client_order_id, ""
    if attempt.exchange_order_id:
        return "exchange_order_id", "", attempt.exchange_order_id
    return "missing", "", ""


def _outcome_for_pre_error(reason_code: str) -> str:
    if not reason_code:
        return ""
    if reason_code in {"query_identifier_missing", "market_identity_missing", "submission_not_finished"}:
        return OrderStatusQueryOutcome.FAILED_BEFORE_QUERY
    return OrderStatusQueryOutcome.BLOCKED_BEFORE_QUERY


def _record_key(attempt: OrderSubmissionAttempt, poll_mode: str, poll_sequence: int) -> str:
    return order_status_sync_key_hash(
        {
            "order_submission_attempt_id": attempt.id,
            "business_request_key": attempt.business_request_key,
            "poll_mode": poll_mode,
            "poll_sequence": poll_sequence,
        }
    )[:MAX_KEY_LENGTH]


def _next_recovery_sequence(order_submission_attempt_id: int) -> int:
    latest = (
        OrderStatusSyncRecord.objects.filter(order_submission_attempt_id=order_submission_attempt_id, poll_mode=POLL_MODE_RECOVERY)
        .order_by("-poll_sequence", "-id")
        .first()
    )
    if latest is None:
        return 1
    if latest.query_finished_at_utc is None:
        return latest.poll_sequence
    return latest.poll_sequence + 1


def _request_error(order_submission_attempt_id: int, business_request_key: str, poll_sequence: int, trace_id: str, trigger_source: str) -> str:
    if not isinstance(order_submission_attempt_id, int) or order_submission_attempt_id <= 0:
        return "order_submission_attempt_id_invalid"
    if not isinstance(poll_sequence, int) or poll_sequence <= 0:
        return "poll_sequence_invalid"
    if not isinstance(business_request_key, str) or not business_request_key.strip() or len(business_request_key) > MAX_KEY_LENGTH:
        return "business_request_key_invalid"
    if not trace_id or not trigger_source or len(trace_id) > MAX_TRACE_FIELD_LENGTH or len(trigger_source) > MAX_TRACE_FIELD_LENGTH:
        return "trace_context_missing"
    return ""


def _result_without_record(reason_code: str, message: str, trace_id: str, trigger_source: str, *, failed: bool = False) -> ServiceResult:
    return ServiceResult(
        ResultStatus.FAILED if failed else ResultStatus.BLOCKED,
        reason_code,
        message,
        trace_id,
        trigger_source,
        {"order_status_sync_record_id": None, "allows_fill_sync": False, "flow_action": "STOP"},
    )


def _reason_message(reason_code: str) -> str:
    labels = {
        "order_status_query_claimed": "OrderStatusSync 已取得本轮查询资格。",
        "order_status_sync_disabled": "OrderStatusSync 部署级开关未开启。",
        "submission_status_not_queryable": "当前提交结果不允许进入订单状态查询。",
        "submission_not_finished": "订单提交尝试尚未完成，不能查询交易所状态。",
        "market_identity_missing": "订单提交记录缺少冻结市场身份。",
        "query_identifier_missing": "订单提交记录缺少 client order id 和 exchange order id。",
        "active_lock_not_active_for_recovery": "ActiveLock 未处于 active 状态，不进入受控补查。",
        "order_status_recovery_out_of_window": "订单状态受控补查已超过恢复窗口，不请求 Binance。",
    }
    return labels.get(reason_code, reason_code)


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
