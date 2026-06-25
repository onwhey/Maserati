"""OrderPlan 模块：在调用 OrderPlan 前检查真实交易权限和部署市场身份；读 MySQL；不访问 Redis 或外部服务；不发送 Hermes；不调用大模型；不提交订单；不允许真实交易。"""

from __future__ import annotations

from datetime import datetime

from django.conf import settings
from django.db import DatabaseError

from apps.binance_account_sync.models import BinanceSyncRun
from apps.binance_gateway.types import SUPPORTED_MARKET_TYPES, normalize_active_market_type
from apps.foundation.results import ResultStatus, ServiceResult
from apps.price_snapshot.models import PriceSnapshot
from apps.runtime_config.services import get_effective_real_trading_permission

from .models import OrderPlanStatus
from .services.alerts import record_order_plan_alert
from .services.plan import create_order_plan


def run_order_plan_step(
    *,
    business_request_key: str,
    decision_snapshot_id: int,
    binance_sync_run_id: int,
    price_snapshot_id: int,
    reference_time_utc: datetime,
    trace_id: str,
    trigger_source: str,
) -> ServiceResult:
    permission = get_effective_real_trading_permission()
    if permission.fail_closed:
        return _adapter_blocked(
            reason_code=permission.reason_code,
            message="真实交易权限配置不可读取，本轮 fail-closed。",
            business_request_key=business_request_key,
            trace_id=trace_id,
            trigger_source=trigger_source,
            event_type="real_trading_permission_unreadable",
        )
    if not permission.effective_allowed:
        record_order_plan_alert(
            event_type="real_trading_permission_closed",
            business_request_key=business_request_key,
            trace_id=trace_id,
            trigger_source=trigger_source,
            status=ResultStatus.NO_ACTION,
            reason_code="real_trading_not_allowed",
            message="真实交易权限关闭，本轮不调用 OrderPlan，也不取得 ActiveLock。",
            payload_summary={
                "deployment_allowed": permission.deployment_allowed,
                "runtime_allowed": permission.runtime_allowed,
            },
        )
        return ServiceResult(
            ResultStatus.NO_ACTION,
            "real_trading_not_allowed",
            "真实交易权限关闭，本轮订单链正常结束",
            trace_id,
            trigger_source,
            {**_adapter_empty_data(), "flow_action": "COMPLETE"},
        )

    identity = _active_identity()
    if identity is None:
        return _adapter_blocked(
            reason_code="active_market_config_unreadable",
            message="部署级交易市场配置不可读取",
            business_request_key=business_request_key,
            trace_id=trace_id,
            trigger_source=trigger_source,
            event_type="active_market_identity_mismatch",
        )
    try:
        sync_run = BinanceSyncRun.objects.filter(id=binance_sync_run_id).first()
        price_snapshot = PriceSnapshot.objects.filter(id=price_snapshot_id).first()
    except DatabaseError:
        return _adapter_blocked(
            reason_code="order_plan_context_unreadable",
            message="OrderPlan 前置市场事实不可读取，本轮 fail-closed。",
            business_request_key=business_request_key,
            trace_id=trace_id,
            trigger_source=trigger_source,
            event_type="active_market_identity_mismatch",
        )
    if sync_run is not None and price_snapshot is not None:
        exchange, market_type, account_domain, symbol = identity
        if (
            sync_run.exchange.lower() != exchange
            or sync_run.market_type != market_type
            or sync_run.account_domain != account_domain
            or price_snapshot.exchange.lower() != exchange
            or price_snapshot.market_type != market_type
            or price_snapshot.account_domain != account_domain
            or price_snapshot.symbol != symbol
        ):
            return _adapter_blocked(
                reason_code="active_market_identity_mismatch",
                message="本轮账户或价格事实与部署级交易市场身份不一致",
                business_request_key=business_request_key,
                trace_id=trace_id,
                trigger_source=trigger_source,
                event_type="active_market_identity_mismatch",
            )

    result = create_order_plan(
        business_request_key=business_request_key,
        decision_snapshot_id=decision_snapshot_id,
        binance_sync_run_id=binance_sync_run_id,
        price_snapshot_id=price_snapshot_id,
        reference_time_utc=reference_time_utc,
        trace_id=trace_id,
        trigger_source=trigger_source,
    )
    flow_action = "CONTINUE" if result.status == ResultStatus.SUCCEEDED and result.data.get("allows_downstream") else "STOP"
    if result.status == ResultStatus.NO_ACTION:
        flow_action = "COMPLETE"
    return ServiceResult(
        result.status,
        result.reason_code,
        result.message,
        result.trace_id,
        result.trigger_source,
        {**result.data, "flow_action": flow_action},
    )


def _active_identity() -> tuple[str, str, str, str] | None:
    exchange = str(getattr(settings, "ACTIVE_EXCHANGE", "")).strip().lower()
    market_type = normalize_active_market_type(getattr(settings, "ACTIVE_MARKET_TYPE", ""))
    account_domain = str(getattr(settings, "ACTIVE_ACCOUNT_DOMAIN", "")).strip()
    symbol = str(getattr(settings, "ACTIVE_SYMBOL", "")).strip().upper()
    if exchange != "binance" or market_type not in SUPPORTED_MARKET_TYPES or not account_domain or not symbol:
        return None
    return exchange, market_type, account_domain, symbol


def _adapter_blocked(
    *,
    reason_code: str,
    message: str,
    business_request_key: str,
    trace_id: str,
    trigger_source: str,
    event_type: str,
) -> ServiceResult:
    record_order_plan_alert(
        event_type=event_type,
        business_request_key=business_request_key or "invalid-order-plan-request",
        trace_id=trace_id,
        trigger_source=trigger_source,
        status=OrderPlanStatus.BLOCKED,
        reason_code=reason_code,
        message=message,
    )
    return ServiceResult(
        ResultStatus.BLOCKED,
        reason_code,
        message,
        trace_id,
        trigger_source,
        {**_adapter_empty_data(), "flow_action": "STOP"},
    )


def _adapter_empty_data() -> dict[str, object]:
    return {
        "order_plan_id": None,
        "active_lock_id": None,
        "candidate_order_intent_ids": [],
        "allows_downstream": False,
    }
