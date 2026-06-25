"""Execution 模块：提交 PreparedOrderIntent 并保存 OrderSubmissionAttempt；读写 MySQL；不访问 Redis；通过 BinanceGateway 访问 Binance；不发送 Hermes；不调用大模型；涉及真实交易执行。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from django.db import DatabaseError, IntegrityError, transaction
from django.utils import timezone

from apps.binance_account_sync.services.hashing import stable_hash
from apps.binance_gateway.order_submission import BinanceOrderSubmissionGateway, get_order_submission_gateway
from apps.binance_gateway.types import (
    ERROR_BINANCE_REJECTED,
    MARKET_TYPE_COIN_M,
    MARKET_TYPE_USDS_M,
    BinanceGatewayCallContext,
    BinanceGatewayResult,
    endpoint_family_for_market,
)
from apps.execution_preparation.models import (
    ExecutionPreparationResult,
    ExecutionPreparationStatus,
    PreparedOrderIntent,
    PreparedOrderIntentStatus,
)
from apps.execution_preparation.services.hashing import prepared_order_evidence_hash
from apps.foundation.redaction import sanitize_mapping
from apps.foundation.results import ResultStatus, ServiceResult
from apps.order_plan.models import ActiveLockStatus, OrderPlanActiveLock
from apps.order_plan.services.active_lock import release_for_order_submission_stop

from ..models import OrderSubmissionAttempt, OrderSubmissionAttemptStatus
from .alerts import record_execution_alert
from .hashing import order_submission_attempt_key_hash, order_submission_request_hash, order_submission_response_hash


MAX_KEY_LENGTH = 191
MAX_TRACE_FIELD_LENGTH = 80
ZERO = Decimal("0")


@dataclass(frozen=True)
class ClaimOutcome:
    attempt: OrderSubmissionAttempt
    should_call_gateway: bool
    replay: bool = False


def submit_prepared_order(
    *,
    prepared_order_intent_id: int,
    business_request_key: str,
    trace_id: str,
    trigger_source: str,
    gateway: BinanceOrderSubmissionGateway | None = None,
) -> ServiceResult:
    request_error = _request_error(
        prepared_order_intent_id=prepared_order_intent_id,
        business_request_key=business_request_key,
        trace_id=trace_id,
        trigger_source=trigger_source,
    )
    if request_error and request_error != "trace_context_missing":
        return _result_without_attempt(request_error, "Execution 请求合同不完整", business_request_key, trace_id, trigger_source)

    submission_time = timezone.now()
    try:
        claim = _claim_submission_attempt(
            prepared_order_intent_id=prepared_order_intent_id,
            business_request_key=business_request_key,
            submission_time_utc=submission_time,
            trace_id=trace_id,
            trigger_source=trigger_source,
            trace_context_error=request_error,
        )
    except PreparedOrderIntent.DoesNotExist:
        return _result_without_attempt(
            "prepared_order_intent_not_found",
            "PreparedOrderIntent 不存在，无法创建订单提交事实。",
            business_request_key,
            trace_id,
            trigger_source,
        )
    except DatabaseError as exc:
        return _result_without_attempt("internal_error", type(exc).__name__, business_request_key, trace_id, trigger_source, failed=True)

    if claim.replay:
        _record_attempt_alert(claim.attempt, "order_submission_idempotent_replay")
        return _result_from_attempt(claim.attempt, replay=True)

    if not claim.should_call_gateway:
        _release_if_safe(claim.attempt)
        _record_attempt_alert(claim.attempt, _event_type_for_attempt(claim.attempt))
        return _result_from_attempt(claim.attempt)

    gateway_result = _call_gateway_once(claim.attempt, gateway or get_order_submission_gateway())
    try:
        finalized = _finalize_gateway_result(claim.attempt.id, gateway_result)
    except DatabaseError as exc:
        finalized = _mark_unknown_after_result_failure(claim.attempt.id, type(exc).__name__)
    _release_if_safe(finalized)
    _record_attempt_alert(finalized, _event_type_for_attempt(finalized))
    return _result_from_attempt(finalized)


def _claim_submission_attempt(
    *,
    prepared_order_intent_id: int,
    business_request_key: str,
    submission_time_utc: datetime,
    trace_id: str,
    trigger_source: str,
    trace_context_error: str,
) -> ClaimOutcome:
    with transaction.atomic():
        prepared = _locked_prepared(prepared_order_intent_id)
        existing = OrderSubmissionAttempt.objects.select_for_update().filter(prepared_order_intent=prepared).first()
        if existing is not None:
            return ClaimOutcome(existing, should_call_gateway=False, replay=True)

        pre_error = trace_context_error or _pre_submit_error(prepared, submission_time_utc)
        frozen_request = _frozen_order_request(prepared)
        attempt = OrderSubmissionAttempt.objects.create(
            order_submission_attempt_key=_attempt_key(prepared, business_request_key),
            prepared_order_intent=prepared,
            execution_preparation_result=prepared.execution_preparation_result,
            approved_order_intent=prepared.source_approved_order_intent,
            risk_check_result=prepared.source_risk_check_result,
            candidate_order_intent=prepared.source_candidate_order_intent,
            order_plan=prepared.source_order_plan,
            active_lock=prepared.execution_preparation_result.active_lock,
            business_request_key=business_request_key,
            exchange=prepared.exchange,
            market_type=prepared.market_type,
            account_domain=prepared.account_domain,
            endpoint_family=endpoint_family_for_market(prepared.market_type),
            symbol=prepared.symbol,
            side=prepared.side,
            position_side=prepared.position_side,
            position_mode=prepared.position_mode,
            order_type=prepared.order_type,
            quantity=prepared.quantity,
            quantity_unit=prepared.quantity_unit,
            reduce_only=prepared.reduce_only,
            order_notional=_order_notional(prepared),
            client_order_id=prepared.client_order_id,
            idempotency_key=prepared.idempotency_key,
            frozen_order_request=frozen_request,
            request_payload_hash=order_submission_request_hash(frozen_request),
            status=OrderSubmissionAttemptStatus.SUBMITTING if not pre_error else _pre_submit_status(pre_error),
            request_sent=False,
            response_received=False,
            gateway_attempt_count=0,
            reason_code="order_submission_claimed" if not pre_error else pre_error,
            reason_message="Execution 已取得唯一订单提交资格。" if not pre_error else _reason_message(pre_error),
            trace_id=trace_id,
            trigger_source=trigger_source,
            claimed_at_utc=submission_time_utc,
            finished_at_utc=None if not pre_error else submission_time_utc,
        )
        if pre_error:
            prepared.status = _prepared_status_for_attempt(attempt.status)
            prepared.save(update_fields=["status", "updated_at_utc"])
        return ClaimOutcome(attempt, should_call_gateway=not bool(pre_error))


def _locked_prepared(prepared_order_intent_id: int) -> PreparedOrderIntent:
    return (
        PreparedOrderIntent.objects.select_for_update()
        .select_related(
            "execution_preparation_result",
            "execution_preparation_result__active_lock",
            "source_approved_order_intent",
            "source_risk_check_result",
            "source_candidate_order_intent",
            "source_order_plan",
            "price_snapshot",
            "binance_sync_run",
            "symbol_rule_snapshot",
        )
        .get(id=prepared_order_intent_id)
    )


def _pre_submit_error(prepared: PreparedOrderIntent, submission_time_utc: datetime) -> str:
    result = prepared.execution_preparation_result
    if prepared.status != PreparedOrderIntentStatus.PREPARED:
        return "prepared_order_intent_not_ready"
    if submission_time_utc >= _ensure_utc(prepared.expires_at_utc):
        return "prepared_order_intent_expired"
    if submission_time_utc < _ensure_utc(prepared.prepared_at_utc) or (
        result.finished_at_utc is not None and submission_time_utc < _ensure_utc(result.finished_at_utc)
    ):
        return "submission_time_before_source_fact"
    if result.status != ExecutionPreparationStatus.PREPARED:
        return "execution_preparation_not_prepared"
    if _source_chain_mismatch(prepared):
        return "source_chain_mismatch"
    if _market_identity_mismatch(prepared):
        return "market_identity_mismatch"
    if _active_lock_error(prepared):
        return _active_lock_error(prepared)
    if _order_contract_error(prepared):
        return _order_contract_error(prepared)
    if prepared.evidence_hash != prepared_order_evidence_hash(result.evidence or {}):
        return "frozen_evidence_mismatch"
    return ""


def _source_chain_mismatch(prepared: PreparedOrderIntent) -> bool:
    result = prepared.execution_preparation_result
    return any(
        [
            result.approved_order_intent_id != prepared.source_approved_order_intent_id,
            result.risk_check_result_id != prepared.source_risk_check_result_id,
            result.candidate_order_intent_id != prepared.source_candidate_order_intent_id,
            result.order_plan_id != prepared.source_order_plan_id,
            result.price_snapshot_id != prepared.price_snapshot_id,
            result.binance_sync_run_id != prepared.binance_sync_run_id,
            prepared.source_approved_order_intent.risk_check_result_id != prepared.source_risk_check_result_id,
            prepared.source_approved_order_intent.candidate_order_intent_id != prepared.source_candidate_order_intent_id,
            prepared.source_approved_order_intent.order_plan_id != prepared.source_order_plan_id,
        ]
    )


def _market_identity_mismatch(prepared: PreparedOrderIntent) -> bool:
    expected = (prepared.exchange.lower(), prepared.market_type, prepared.account_domain, prepared.symbol)
    identities = [
        (prepared.source_order_plan.exchange.lower(), prepared.source_order_plan.market_type, prepared.source_order_plan.account_domain, prepared.source_order_plan.symbol),
        ("binance", prepared.source_candidate_order_intent.market_type, prepared.source_candidate_order_intent.account_domain, prepared.source_candidate_order_intent.symbol),
        (prepared.source_approved_order_intent.exchange.lower(), prepared.source_approved_order_intent.market_type, prepared.source_approved_order_intent.account_domain, prepared.source_approved_order_intent.symbol),
        (prepared.price_snapshot.exchange.lower(), prepared.price_snapshot.market_type, prepared.price_snapshot.account_domain, prepared.price_snapshot.symbol),
        (prepared.binance_sync_run.exchange.lower(), prepared.binance_sync_run.market_type, prepared.binance_sync_run.account_domain, prepared.symbol),
        ("binance", prepared.symbol_rule_snapshot.market_type, prepared.symbol_rule_snapshot.account_domain, prepared.symbol_rule_snapshot.symbol),
    ]
    lock = prepared.execution_preparation_result.active_lock
    identities.append((lock.exchange.lower(), lock.market_type, lock.account_domain, lock.symbol))
    return any(identity != expected for identity in identities)


def _active_lock_error(prepared: PreparedOrderIntent) -> str:
    lock = prepared.execution_preparation_result.active_lock
    if lock.status != ActiveLockStatus.ACTIVE:
        return "active_lock_not_active"
    if lock.current_order_plan_id != prepared.source_order_plan_id:
        return "active_lock_mismatch"
    return ""


def _order_contract_error(prepared: PreparedOrderIntent) -> str:
    if prepared.order_type != "MARKET":
        return "unsupported_order_type"
    if prepared.position_mode != "one_way":
        return "unsupported_position_mode"
    if prepared.position_side != "BOTH":
        return "unsupported_position_side"
    if prepared.side not in {"BUY", "SELL"} or prepared.quantity <= ZERO or not prepared.client_order_id or not prepared.idempotency_key:
        return "invalid_frozen_order_request"
    if prepared.market_type == MARKET_TYPE_USDS_M and not prepared.quantity_unit:
        return "unsupported_quantity_unit"
    if prepared.market_type == MARKET_TYPE_COIN_M and prepared.quantity_unit != "contracts":
        return "unsupported_quantity_unit"
    if prepared.market_type == MARKET_TYPE_COIN_M and (prepared.symbol_rule_snapshot.contract_size is None or prepared.symbol_rule_snapshot.contract_size <= ZERO):
        return "invalid_frozen_order_request"
    return ""


def _call_gateway_once(attempt: OrderSubmissionAttempt, gateway: BinanceOrderSubmissionGateway) -> BinanceGatewayResult:
    try:
        return gateway.submit_order(
            market_type=attempt.market_type,
            frozen_order_request=dict(attempt.frozen_order_request),
            call_context=BinanceGatewayCallContext(
                trace_id=attempt.trace_id,
                trigger_source=attempt.trigger_source,
                operation="submit_order",
                market_type=attempt.market_type,
                account_domain=attempt.account_domain,
                symbol=attempt.symbol,
                business_object_type="PreparedOrderIntent",
                business_object_id=str(attempt.prepared_order_intent_id),
                request_time_utc=timezone.now(),
                metadata={
                    "order_submission_attempt_id": attempt.id,
                    "client_order_id": attempt.client_order_id,
                    "execution_mode": "real",
                },
            ),
        )
    except Exception as exc:
        now = timezone.now()
        return BinanceGatewayResult(
            operation="submit_order",
            market_type=attempt.market_type,
            endpoint_family=attempt.endpoint_family,
            success=False,
            request_sent=True,
            response_received=False,
            error_category="gateway_failed",
            sanitized_error_message=type(exc).__name__,
            request_started_at_utc=now,
            request_finished_at_utc=now,
            attempt_count=1,
            trace_id=attempt.trace_id,
        )


def _finalize_gateway_result(attempt_id: int, gateway_result: BinanceGatewayResult) -> OrderSubmissionAttempt:
    with transaction.atomic():
        attempt = OrderSubmissionAttempt.objects.select_for_update().select_related("prepared_order_intent").get(id=attempt_id)
        prepared = PreparedOrderIntent.objects.select_for_update().get(id=attempt.prepared_order_intent_id)
        if attempt.status != OrderSubmissionAttemptStatus.SUBMITTING:
            return attempt
        status, reason_code, message = _classify_gateway_result(attempt, gateway_result)
        payload = sanitize_mapping(gateway_result.payload if isinstance(gateway_result.payload, dict) else {"payload": gateway_result.payload})
        attempt.status = status
        attempt.endpoint_family = gateway_result.endpoint_family or attempt.endpoint_family
        attempt.request_sent = bool(gateway_result.request_sent)
        attempt.response_received = bool(gateway_result.response_received)
        attempt.gateway_attempt_count = int(gateway_result.attempt_count or 0)
        attempt.http_status = gateway_result.http_status
        attempt.binance_error_code = str(gateway_result.binance_error_code or "")
        attempt.sanitized_error_message = str(gateway_result.sanitized_error_message or "")[:500]
        attempt.sanitized_exchange_response = payload
        attempt.exchange_response_hash = order_submission_response_hash(payload) if payload else ""
        attempt.exchange_order_id = str(payload.get("orderId") or "")
        attempt.exchange_client_order_id = str(payload.get("clientOrderId") or payload.get("client_order_id") or "")
        attempt.exchange_status = str(payload.get("status") or "")
        attempt.rate_limit_metadata = gateway_result.rate_limit_metadata
        attempt.reason_code = reason_code
        attempt.reason_message = message
        attempt.submitted_at_utc = gateway_result.request_started_at_utc or timezone.now()
        attempt.finished_at_utc = gateway_result.request_finished_at_utc or timezone.now()
        attempt.save()
        prepared.status = _prepared_status_for_attempt(status)
        prepared.save(update_fields=["status", "updated_at_utc"])
        return attempt


def _classify_gateway_result(
    attempt: OrderSubmissionAttempt,
    gateway_result: BinanceGatewayResult,
) -> tuple[str, str, str]:
    if gateway_result.attempt_count > 1:
        return (
            OrderSubmissionAttemptStatus.UNKNOWN,
            "gateway_contract_violation",
            "Gateway 返回的提交尝试次数大于 1，违反订单提交绝不重试合同。",
        )
    payload = gateway_result.payload if isinstance(gateway_result.payload, dict) else {}
    client_id = str(payload.get("clientOrderId") or payload.get("client_order_id") or "")
    has_exchange_identity = bool(payload.get("orderId") or client_id)
    if (
        gateway_result.success
        and gateway_result.request_sent
        and gateway_result.response_received
        and has_exchange_identity
        and (not client_id or client_id == attempt.client_order_id)
    ):
        return OrderSubmissionAttemptStatus.ACCEPTED, "submission_accepted", "Binance 明确接受订单提交请求；这不等于已经成交。"
    if not gateway_result.request_sent:
        return OrderSubmissionAttemptStatus.FAILED_BEFORE_SUBMIT, "submission_failed_before_send", "Gateway 确认订单请求未发出。"
    if gateway_result.response_received and gateway_result.error_category == ERROR_BINANCE_REJECTED:
        return OrderSubmissionAttemptStatus.REJECTED, "submission_rejected", "Binance 明确拒绝订单提交请求。"
    return OrderSubmissionAttemptStatus.UNKNOWN, "submission_unknown", "无法确认 Binance 是否收到或处理订单提交请求。"


def _mark_unknown_after_result_failure(attempt_id: int, message: str) -> OrderSubmissionAttempt:
    with transaction.atomic():
        attempt = OrderSubmissionAttempt.objects.select_for_update().get(id=attempt_id)
        if attempt.status == OrderSubmissionAttemptStatus.SUBMITTING:
            attempt.status = OrderSubmissionAttemptStatus.UNKNOWN
            attempt.request_sent = True
            attempt.response_received = False
            attempt.gateway_attempt_count = max(attempt.gateway_attempt_count, 1)
            attempt.reason_code = "submission_unknown"
            attempt.reason_message = f"提交后结果事务失败，保守标记为 unknown：{message}"
            attempt.finished_at_utc = timezone.now()
            attempt.exception_class = message[:120]
            attempt.save()
            PreparedOrderIntent.objects.filter(id=attempt.prepared_order_intent_id).update(status=PreparedOrderIntentStatus.SUBMISSION_UNKNOWN)
        return attempt


def _release_if_safe(attempt: OrderSubmissionAttempt) -> None:
    if attempt.status not in {
        OrderSubmissionAttemptStatus.REJECTED,
        OrderSubmissionAttemptStatus.BLOCKED_BEFORE_SUBMIT,
        OrderSubmissionAttemptStatus.FAILED_BEFORE_SUBMIT,
    }:
        return
    if attempt.status != OrderSubmissionAttemptStatus.REJECTED and attempt.request_sent:
        return
    release_for_order_submission_stop(
        active_lock_id=attempt.active_lock_id,
        order_plan_id=attempt.order_plan_id,
        source_module="Execution",
        source_object_id=attempt.id,
        reason_code=attempt.reason_code,
        evidence={
            "order_submission_attempt_id": attempt.id,
            "prepared_order_intent_id": attempt.prepared_order_intent_id,
            "request_sent": attempt.request_sent,
            "response_received": attempt.response_received,
            "status": attempt.status,
        },
        trace_id=attempt.trace_id,
        trigger_source=attempt.trigger_source,
    )


def _result_from_attempt(attempt: OrderSubmissionAttempt, *, replay: bool = False) -> ServiceResult:
    status = ResultStatus.BLOCKED
    flow_action = "STOP"
    if attempt.status == OrderSubmissionAttemptStatus.ACCEPTED:
        status = ResultStatus.SUCCEEDED
        flow_action = "CONTINUE"
    elif attempt.status == OrderSubmissionAttemptStatus.UNKNOWN:
        status = ResultStatus.UNKNOWN
        flow_action = "CONTINUE"
    elif attempt.status == OrderSubmissionAttemptStatus.FAILED_BEFORE_SUBMIT:
        status = ResultStatus.FAILED
    elif attempt.status == OrderSubmissionAttemptStatus.SUBMITTING:
        status = ResultStatus.UNKNOWN
        flow_action = "STOP"
    reason_code = "order_submission_idempotent_replay" if replay else attempt.reason_code
    message = "OrderSubmissionAttempt 幂等重放，未重新调用 Gateway。" if replay else attempt.reason_message
    return ServiceResult(
        status,
        reason_code,
        message,
        attempt.trace_id,
        attempt.trigger_source,
        {
            "order_submission_attempt_id": attempt.id,
            "prepared_order_intent_id": attempt.prepared_order_intent_id,
            "order_submission_status": attempt.status,
            "request_sent": attempt.request_sent,
            "response_received": attempt.response_received,
            "gateway_attempt_count": attempt.gateway_attempt_count,
            "exchange_order_id": attempt.exchange_order_id,
            "client_order_id": attempt.client_order_id,
            "active_lock_id": attempt.active_lock_id,
            "allows_order_status_sync": attempt.status in {OrderSubmissionAttemptStatus.ACCEPTED, OrderSubmissionAttemptStatus.UNKNOWN},
            "flow_action": flow_action,
        },
    )


def _record_attempt_alert(attempt: OrderSubmissionAttempt, event_type: str) -> None:
    alert_id = record_execution_alert(
        event_type=event_type,
        business_request_key=attempt.business_request_key,
        trace_id=attempt.trace_id,
        trigger_source=attempt.trigger_source,
        status=attempt.status,
        reason_code=attempt.reason_code,
        message=attempt.reason_message,
        order_submission_attempt_id=attempt.id,
        prepared_order_intent_id=attempt.prepared_order_intent_id,
        payload_summary={
            "prepared_order_intent_id": attempt.prepared_order_intent_id,
            "execution_preparation_result_id": attempt.execution_preparation_result_id,
            "approved_order_intent_id": attempt.approved_order_intent_id,
            "risk_check_result_id": attempt.risk_check_result_id,
            "candidate_order_intent_id": attempt.candidate_order_intent_id,
            "order_plan_id": attempt.order_plan_id,
            "active_lock_id": attempt.active_lock_id,
            "market_type": attempt.market_type,
            "account_domain": attempt.account_domain,
            "endpoint_family": attempt.endpoint_family,
            "symbol": attempt.symbol,
            "side": attempt.side,
            "quantity": _decimal_str(attempt.quantity),
            "quantity_unit": attempt.quantity_unit,
            "reduce_only": attempt.reduce_only,
            "order_notional": _decimal_str(attempt.order_notional),
            "client_order_id": attempt.client_order_id,
            "request_sent": attempt.request_sent,
            "response_received": attempt.response_received,
            "exchange_order_id": attempt.exchange_order_id,
            "exchange_status": attempt.exchange_status,
            "http_status": attempt.http_status,
            "binance_error_code": attempt.binance_error_code,
            "gateway_attempt_count": attempt.gateway_attempt_count,
        },
    )
    if alert_id is not None and alert_id not in attempt.alert_event_ids:
        attempt.alert_event_ids = [*attempt.alert_event_ids, alert_id]
        attempt.save(update_fields=["alert_event_ids", "updated_at_utc"])


def _event_type_for_attempt(attempt: OrderSubmissionAttempt) -> str:
    mapping = {
        OrderSubmissionAttemptStatus.ACCEPTED: "order_submission_accepted",
        OrderSubmissionAttemptStatus.REJECTED: "order_submission_rejected",
        OrderSubmissionAttemptStatus.UNKNOWN: "order_submission_gateway_contract_violation"
        if attempt.reason_code == "gateway_contract_violation"
        else "order_submission_unknown",
        OrderSubmissionAttemptStatus.BLOCKED_BEFORE_SUBMIT: "order_submission_blocked_before_submit",
        OrderSubmissionAttemptStatus.FAILED_BEFORE_SUBMIT: "order_submission_failed_before_submit",
    }
    return mapping.get(attempt.status, "order_submission_unknown")


def _result_without_attempt(
    reason_code: str,
    message: str,
    business_request_key: str,
    trace_id: str,
    trigger_source: str,
    *,
    failed: bool = False,
) -> ServiceResult:
    record_execution_alert(
        event_type="order_submission_failed_before_submit" if failed else "order_submission_blocked_before_submit",
        business_request_key=business_request_key or "invalid-order-submission-request",
        trace_id=trace_id,
        trigger_source=trigger_source,
        status=OrderSubmissionAttemptStatus.FAILED_BEFORE_SUBMIT if failed else OrderSubmissionAttemptStatus.BLOCKED_BEFORE_SUBMIT,
        reason_code=reason_code,
        message=message,
    )
    return ServiceResult(
        ResultStatus.FAILED if failed else ResultStatus.BLOCKED,
        reason_code,
        message,
        trace_id,
        trigger_source,
        {
            "order_submission_attempt_id": None,
            "prepared_order_intent_id": None,
            "allows_order_status_sync": False,
            "flow_action": "STOP",
        },
    )


def _request_error(**values: Any) -> str:
    if not isinstance(values["prepared_order_intent_id"], int) or values["prepared_order_intent_id"] <= 0:
        return "prepared_order_intent_id_invalid"
    key = values["business_request_key"]
    if not isinstance(key, str) or not key.strip() or len(key) > MAX_KEY_LENGTH:
        return "business_request_key_invalid"
    if not values["trace_id"] or not values["trigger_source"]:
        return "trace_context_missing"
    if len(values["trace_id"]) > MAX_TRACE_FIELD_LENGTH or len(values["trigger_source"]) > MAX_TRACE_FIELD_LENGTH:
        return "trace_context_missing"
    return ""


def _pre_submit_status(reason_code: str) -> str:
    if reason_code in {"trace_context_missing", "internal_error"}:
        return OrderSubmissionAttemptStatus.FAILED_BEFORE_SUBMIT
    return OrderSubmissionAttemptStatus.BLOCKED_BEFORE_SUBMIT


def _prepared_status_for_attempt(status: str) -> str:
    mapping = {
        OrderSubmissionAttemptStatus.ACCEPTED: PreparedOrderIntentStatus.SUBMITTED,
        OrderSubmissionAttemptStatus.REJECTED: PreparedOrderIntentStatus.SUBMISSION_REJECTED,
        OrderSubmissionAttemptStatus.UNKNOWN: PreparedOrderIntentStatus.SUBMISSION_UNKNOWN,
        OrderSubmissionAttemptStatus.BLOCKED_BEFORE_SUBMIT: PreparedOrderIntentStatus.SUBMISSION_BLOCKED,
        OrderSubmissionAttemptStatus.FAILED_BEFORE_SUBMIT: PreparedOrderIntentStatus.SUBMISSION_FAILED,
    }
    return mapping.get(status, PreparedOrderIntentStatus.PREPARED)


def _frozen_order_request(prepared: PreparedOrderIntent) -> dict[str, Any]:
    return {
        "symbol": prepared.symbol,
        "side": prepared.side,
        "type": prepared.order_type,
        "quantity": _decimal_str(prepared.quantity),
        "quantity_unit": prepared.quantity_unit,
        "reduceOnly": prepared.reduce_only,
        "positionSide": prepared.position_side,
        "position_mode": prepared.position_mode,
        "newClientOrderId": prepared.client_order_id,
    }


def _order_notional(prepared: PreparedOrderIntent) -> Decimal | None:
    if prepared.market_type == MARKET_TYPE_USDS_M:
        return prepared.quantity * prepared.selected_live_price
    if prepared.market_type == MARKET_TYPE_COIN_M and prepared.symbol_rule_snapshot.contract_size is not None:
        return prepared.quantity * prepared.symbol_rule_snapshot.contract_size
    return None


def _attempt_key(prepared: PreparedOrderIntent, business_request_key: str) -> str:
    return order_submission_attempt_key_hash(
        {
            "business_request_key": business_request_key,
            "prepared_order_intent_id": prepared.id,
            "client_order_id": prepared.client_order_id,
            "idempotency_key": prepared.idempotency_key,
        }
    )[:MAX_KEY_LENGTH]


def _reason_message(reason_code: str) -> str:
    labels = {
        "trace_context_missing": "Execution 缺少技术追踪上下文，不能调用 Gateway。",
        "prepared_order_intent_not_ready": "PreparedOrderIntent 当前状态不允许提交。",
        "prepared_order_intent_expired": "PreparedOrderIntent 已过期，不能提交。",
        "execution_preparation_not_prepared": "ExecutionPreparationResult 未处于 PREPARED。",
        "submission_time_before_source_fact": "提交时间早于上游冻结事实时间。",
        "source_chain_mismatch": "订单提交上游业务链不一致。",
        "market_identity_mismatch": "冻结订单链路市场身份不一致。",
        "active_lock_not_active": "ActiveLock 不处于 active。",
        "active_lock_mismatch": "ActiveLock 未绑定当前 OrderPlan。",
        "unsupported_order_type": "当前只支持 MARKET 订单。",
        "unsupported_position_mode": "当前只支持 One-Way Mode。",
        "unsupported_position_side": "当前只支持 positionSide=BOTH。",
        "unsupported_quantity_unit": "冻结数量单位不符合市场类型。",
        "invalid_frozen_order_request": "冻结订单请求不完整或不合法。",
        "frozen_evidence_mismatch": "PreparedOrderIntent 冻结证据 hash 校验失败。",
    }
    return labels.get(reason_code, reason_code)


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _decimal_str(value: Decimal | None) -> str:
    if value is None:
        return ""
    return format(value.normalize(), "f")
