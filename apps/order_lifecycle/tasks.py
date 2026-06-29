"""OrderLifecycle Celery tasks.

Module: OrderLifecycle
Responsibility: asynchronous entry point for closeout-time existing order cancel and status/fill sync.
Not responsible for business logic, order submission, lock release, Binance direct calls, DeepSeek, or Hermes delivery.
Database: delegates to OrderLifecycle service, which persists OrderCancelAttempt and delegates status/fill persistence.
Redis: may be used by Celery broker only.
External services: no direct access; delegated services may query Binance through BinanceGateway.
Real trading: never submits a new real order and never retries order submission.
"""

from __future__ import annotations

import uuid

from config.celery import app

from .services.closeout import DEFAULT_CANCEL_REASON, closeout_limit_order
from .services.pipeline import run_order_lifecycle_pipeline


@app.task(name="order_lifecycle.sync_order", max_retries=0)
def sync_order_lifecycle_task(
    *,
    order_submission_attempt_id: int,
    business_request_key: str,
    poll_sequence: int | None = None,
    trace_id: str = "",
    trigger_source: str = "order_lifecycle_task",
) -> dict[str, object]:
    result = run_order_lifecycle_pipeline(
        order_submission_attempt_id=order_submission_attempt_id,
        business_request_key=business_request_key,
        poll_sequence=poll_sequence,
        trace_id=trace_id or uuid.uuid4().hex,
        trigger_source=trigger_source,
    )
    return {
        "status": result.status.value,
        "reason_code": result.reason_code,
        "message": result.message,
        "trace_id": result.trace_id,
        "trigger_source": result.trigger_source,
        "lifecycle_action": result.data.get("lifecycle_action"),
        "order_submission_attempt_id": result.data.get("order_submission_attempt_id"),
        "pipeline_action": result.data.get("pipeline_action"),
        "poll_sequence": result.data.get("poll_sequence"),
        "poll_mode": result.data.get("poll_mode"),
        "order_status_sync_record_id": result.data.get("order_status_sync_record_id"),
        "fill_sync_result_id": result.data.get("fill_sync_result_id"),
        "next_poll_sequence": result.data.get("next_poll_sequence"),
        "scheduled_next_poll": result.data.get("scheduled_next_poll", False),
    }


@app.task(name="order_lifecycle.closeout_limit_order", max_retries=0)
def closeout_limit_order_task(
    *,
    order_submission_attempt_id: int,
    business_request_key: str,
    closeout_time_utc: str,
    trace_id: str = "",
    trigger_source: str = "order_cycle_closeout_task",
    cancel_reason_code: str = DEFAULT_CANCEL_REASON,
) -> dict[str, object]:
    from django.utils.dateparse import parse_datetime

    parsed_closeout_time = parse_datetime(closeout_time_utc)
    result = closeout_limit_order(
        order_submission_attempt_id=order_submission_attempt_id,
        business_request_key=business_request_key,
        closeout_time_utc=parsed_closeout_time if parsed_closeout_time is not None else closeout_time_utc,  # type: ignore[arg-type]
        trace_id=trace_id or uuid.uuid4().hex,
        trigger_source=trigger_source,
        cancel_reason_code=cancel_reason_code,
    )
    return {
        "status": result.status.value,
        "reason_code": result.reason_code,
        "message": result.message,
        "trace_id": result.trace_id,
        "trigger_source": result.trigger_source,
        "closeout_action": result.data.get("closeout_action"),
        "order_submission_attempt_id": result.data.get("order_submission_attempt_id"),
        "order_cancel_attempt_id": result.data.get("order_cancel_attempt_id"),
        "order_status_sync_record_id": result.data.get("order_status_sync_record_id"),
        "fill_sync_result_id": result.data.get("fill_sync_result_id"),
    }
