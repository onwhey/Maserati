"""RiskCheck 模块：提供编排调用适配器；不实现风控规则；不访问外部服务；不提交订单；不允许真实交易。"""

from __future__ import annotations

from datetime import datetime

from apps.foundation.results import ResultStatus, ServiceResult

from .services.check import run_risk_check


def run_risk_check_step(
    *,
    business_request_key: str,
    order_plan_id: int,
    candidate_order_intent_id: int,
    binance_sync_run_id: int,
    price_snapshot_id: int,
    active_lock_id: int,
    reference_time_utc: datetime,
    risk_rule_set: str | None,
    trace_id: str,
    trigger_source: str,
) -> ServiceResult:
    result = run_risk_check(
        business_request_key=business_request_key,
        order_plan_id=order_plan_id,
        candidate_order_intent_id=candidate_order_intent_id,
        binance_sync_run_id=binance_sync_run_id,
        price_snapshot_id=price_snapshot_id,
        active_lock_id=active_lock_id,
        reference_time_utc=reference_time_utc,
        risk_rule_set=risk_rule_set,
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
