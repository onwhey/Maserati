"""ExecutionPreparation 模块：提供编排调用适配器；不实现 price guard；不直接访问 Binance；不提交订单；不允许真实交易。"""

from __future__ import annotations

from datetime import datetime

from apps.foundation.results import ResultStatus, ServiceResult

from .services.preparation import prepare_execution


def run_execution_preparation_step(
    *,
    approved_order_intent_id: int,
    business_request_key: str,
    reference_time_utc: datetime,
    trace_id: str,
    trigger_source: str,
) -> ServiceResult:
    result = prepare_execution(
        approved_order_intent_id=approved_order_intent_id,
        business_request_key=business_request_key,
        reference_time_utc=reference_time_utc,
        trace_id=trace_id,
        trigger_source=trigger_source,
    )
    flow_action = "CONTINUE" if result.status == ResultStatus.SUCCEEDED and result.data.get("allows_downstream") else "STOP"
    return ServiceResult(
        result.status,
        result.reason_code,
        result.message,
        result.trace_id,
        result.trigger_source,
        {**result.data, "flow_action": flow_action},
    )
