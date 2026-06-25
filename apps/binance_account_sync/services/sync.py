"""BinanceAccountSync 模块：同步账户、余额、持仓和交易规则快照；读写数据库；不访问 Redis；通过 BinanceGateway 访问 Binance；不发送 Hermes；不调用大模型；不涉及交易执行；不允许真实交易。"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from django.conf import settings
from django.db import DatabaseError, IntegrityError, transaction
from django.utils import timezone

from apps.audit.services import record_audit
from apps.binance_gateway.account_read import AccountReadGateway, get_account_read_gateway
from apps.binance_gateway.public_market import PublicMarketGateway, get_public_market_gateway
from apps.binance_gateway.types import BinanceGatewayCallContext, BinanceGatewayResult, normalize_active_market_type
from apps.foundation.redaction import sanitize_mapping
from apps.foundation.results import ResultStatus, ServiceResult

from ..models import (
    BinanceAccountSnapshot,
    BinanceBalanceSnapshot,
    BinancePositionMode,
    BinancePositionSnapshot,
    BinanceSymbolRuleSnapshot,
    BinanceSyncPurpose,
    BinanceSyncRun,
    BinanceSyncStatus,
)
from .alerts import failed_severity_for_purpose, record_account_sync_alert
from .hashing import stable_hash


logger = logging.getLogger(__name__)

MAX_ERROR_MESSAGE_LENGTH = 500
ZERO = Decimal("0")


@dataclass(frozen=True)
class SyncRequest:
    business_request_key: str
    sync_purpose: str
    market_type: str
    account_domain: str
    symbols: tuple[str, ...]
    trace_id: str
    trigger_source: str
    operator_id: str = ""


@dataclass(frozen=True)
class GatewayPayloads:
    account: dict[str, Any]
    balances: list[dict[str, Any]]
    positions: list[dict[str, Any]]
    symbol_rules: dict[str, dict[str, Any]]
    gateway_summary: dict[str, Any]


@dataclass(frozen=True)
class SnapshotDraft:
    account: dict[str, Any]
    balances: list[dict[str, Any]]
    positions: list[dict[str, Any]]
    rules: list[dict[str, Any]]
    position_mode: str
    snapshot_set_hash: str


def sync_for_trade_preparation(
    *,
    business_request_key: str,
    market_type: str,
    account_domain: str,
    symbols: list[str] | tuple[str, ...] | None,
    trace_id: str,
    trigger_source: str,
    account_gateway: AccountReadGateway | None = None,
    market_gateway: PublicMarketGateway | None = None,
) -> ServiceResult:
    request = SyncRequest(
        business_request_key=business_request_key,
        sync_purpose=BinanceSyncPurpose.TRADE_PREPARATION,
        market_type=normalize_active_market_type(market_type),
        account_domain=account_domain,
        symbols=normalize_symbols(symbols),
        trace_id=trace_id,
        trigger_source=trigger_source,
    )
    return run_account_sync(request=request, account_gateway=account_gateway, market_gateway=market_gateway)


def refresh_for_ops_console(
    *,
    operator_id: str,
    trace_id: str,
    reason: str = "OpsConsole 一键刷新当前 active domain 账户展示事实",
    trigger_source: str = "ui_one_click",
    account_gateway: AccountReadGateway | None = None,
    market_gateway: PublicMarketGateway | None = None,
) -> ServiceResult:
    market_type = active_market_type()
    account_domain = getattr(settings, "ACTIVE_ACCOUNT_DOMAIN", "")
    request = SyncRequest(
        business_request_key=f"ops_display:{trace_id}",
        sync_purpose=BinanceSyncPurpose.OPS_DISPLAY,
        market_type=market_type,
        account_domain=account_domain,
        symbols=normalize_symbols(None),
        trace_id=trace_id,
        trigger_source=trigger_source,
        operator_id=operator_id,
    )
    result = run_account_sync(request=request, account_gateway=account_gateway, market_gateway=market_gateway)
    record_audit(
        operator_id=operator_id,
        operation_type="binance_account_sync_ops_refresh",
        target_object_type="BinanceSyncRun",
        target_object_id=str(result.data.get("binance_sync_run_id") or ""),
        before_state_summary={},
        after_state_summary=result.data,
        reason=reason.strip()[:500] or "OpsConsole 一键刷新当前 active domain 账户展示事实",
        evidence={"sync_purpose": BinanceSyncPurpose.OPS_DISPLAY, "trace_id": trace_id},
        result=result.status.value,
        trace_id=trace_id,
        trigger_source=trigger_source,
    )
    return result


def run_account_sync(
    *,
    request: SyncRequest,
    account_gateway: AccountReadGateway | None = None,
    market_gateway: PublicMarketGateway | None = None,
) -> ServiceResult:
    validation_error = validate_request(request)
    if validation_error:
        return blocked_without_run(request=request, reason_code=validation_error)

    existing = BinanceSyncRun.objects.filter(
        business_request_key=request.business_request_key,
        market_type=request.market_type,
        account_domain=request.account_domain,
        sync_purpose=request.sync_purpose,
    ).first()
    if existing is not None:
        return result_from_run(existing)

    if not getattr(settings, "BINANCE_ACCOUNT_SYNC_ENABLED", False):
        run = create_failed_run(request=request, reason_code="account_sync_disabled", message="Binance Account Sync 部署级开关未开启")
        return result_from_run(run)

    run, created = create_running_run(request)
    if not created:
        return result_from_run(run)
    payloads = fetch_gateway_payloads(
        run=run,
        request=request,
        account_gateway=account_gateway or get_account_read_gateway(),
        market_gateway=market_gateway or get_public_market_gateway(),
    )
    if isinstance(payloads, ServiceResult):
        return payloads
    try:
        draft = build_snapshot_draft(request=request, payloads=payloads, as_of_utc=timezone.now())
        publish_snapshot_set(run=run, request=request, payloads=payloads, draft=draft)
    except (ValueError, TypeError, InvalidOperation) as exc:
        logger.warning("BinanceAccountSync 标准化失败: %s", exc)
        return fail_run(run, "snapshot_normalization_failed", str(exc))
    except (DatabaseError, IntegrityError) as exc:
        logger.exception("BinanceAccountSync 快照写入失败 run_id=%s", run.id)
        return fail_run(run, "snapshot_persist_failed", str(exc))
    return result_from_run(BinanceSyncRun.objects.get(id=run.id))


def normalize_symbols(symbols: list[str] | tuple[str, ...] | None) -> tuple[str, ...]:
    raw = symbols if symbols is not None else getattr(settings, "BINANCE_ACCOUNT_SYNC_SYMBOLS", [])
    normalized = tuple(dict.fromkeys(str(item).strip().upper() for item in raw if str(item).strip()))
    return normalized


def active_market_type() -> str:
    return normalize_active_market_type(getattr(settings, "ACTIVE_MARKET_TYPE", ""))


def validate_request(request: SyncRequest) -> str:
    if not request.business_request_key or len(request.business_request_key) > 191:
        return "invalid_business_request_key"
    if request.sync_purpose not in set(BinanceSyncPurpose.values):
        return "invalid_sync_purpose"
    if request.market_type != active_market_type():
        return "market_type_mismatch"
    if request.account_domain != getattr(settings, "ACTIVE_ACCOUNT_DOMAIN", ""):
        return "account_domain_mismatch"
    if not request.symbols:
        return "symbols_required"
    if not request.trace_id or not request.trigger_source:
        return "trace_context_required"
    if request.sync_purpose == BinanceSyncPurpose.OPS_DISPLAY and not request.operator_id:
        return "operator_required"
    return ""


def create_running_run(request: SyncRequest) -> tuple[BinanceSyncRun, bool]:
    return BinanceSyncRun.objects.get_or_create(
        business_request_key=request.business_request_key,
        market_type=request.market_type,
        account_domain=request.account_domain,
        sync_purpose=request.sync_purpose,
        defaults={
            "requested_symbols": list(request.symbols),
            "trace_id": request.trace_id,
            "trigger_source": request.trigger_source,
            "operator_id": request.operator_id,
        },
    )


def create_failed_run(*, request: SyncRequest, reason_code: str, message: str) -> BinanceSyncRun:
    run, created = create_running_run(request)
    if not created:
        return run
    run.status = BinanceSyncStatus.FAILED
    run.error_code = reason_code
    run.error_message = limited_text(message)
    run.finished_at_utc = timezone.now()
    run.save(update_fields=["status", "error_code", "error_message", "finished_at_utc"])
    write_failure_alert(run, reason_code=reason_code, message=message)
    return run


def fetch_gateway_payloads(
    *,
    run: BinanceSyncRun,
    request: SyncRequest,
    account_gateway: AccountReadGateway,
    market_gateway: PublicMarketGateway,
) -> GatewayPayloads | ServiceResult:
    account_result = account_gateway.get_account(
        market_type=request.market_type,
        account_domain=request.account_domain,
        call_context=gateway_context(run, request, "get_account"),
    )
    if not account_result.success:
        return fail_run_from_gateway(run, "gateway_account_failed", account_result)
    balances_result = account_gateway.get_balances(
        market_type=request.market_type,
        account_domain=request.account_domain,
        call_context=gateway_context(run, request, "get_balances"),
    )
    if not balances_result.success:
        return fail_run_from_gateway(run, "gateway_balances_failed", balances_result)
    position_payload = fetch_positions(run=run, request=request, gateway=account_gateway)
    if isinstance(position_payload, ServiceResult):
        return position_payload
    positions, position_summary = position_payload
    rule_payload = fetch_symbol_rules(run=run, request=request, gateway=market_gateway)
    if isinstance(rule_payload, ServiceResult):
        return rule_payload
    rules, rule_summary = rule_payload
    summary = {
        "get_account": result_summary(account_result),
        "get_balances": result_summary(balances_result),
        "get_positions": position_summary,
        "get_symbol_exchange_info": rule_summary,
    }
    return GatewayPayloads(
        account=ensure_mapping(account_result.payload, "account payload"),
        balances=ensure_list_of_mappings(balances_result.payload, "balances payload"),
        positions=positions,
        symbol_rules=rules,
        gateway_summary=summary,
    )


def fetch_positions(
    *,
    run: BinanceSyncRun,
    request: SyncRequest,
    gateway: AccountReadGateway,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]] | ServiceResult:
    positions: list[dict[str, Any]] = []
    summaries: list[dict[str, Any]] = []
    for symbol in request.symbols:
        result = gateway.get_positions(
            market_type=request.market_type,
            account_domain=request.account_domain,
            symbol=symbol,
            call_context=gateway_context(run, request, "get_positions", symbol=symbol),
        )
        if not result.success:
            return fail_run_from_gateway(run, "gateway_positions_failed", result)
        payload = result.payload
        if isinstance(payload, dict):
            payload = [payload]
        symbol_positions = [item for item in ensure_list_of_mappings(payload, "positions payload") if item.get("symbol") == symbol]
        positions.extend(symbol_positions or [zero_position_payload(symbol)])
        summaries.append({"symbol": symbol, **result_summary(result), "item_count": len(symbol_positions)})
    return positions, summaries


def fetch_symbol_rules(
    *,
    run: BinanceSyncRun,
    request: SyncRequest,
    gateway: PublicMarketGateway,
) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]] | ServiceResult:
    rules: dict[str, dict[str, Any]] = {}
    summaries: list[dict[str, Any]] = []
    for symbol in request.symbols:
        result = gateway.get_symbol_exchange_info(
            market_type=request.market_type,
            symbol=symbol,
            call_context=gateway_context(run, request, "get_symbol_exchange_info", symbol=symbol),
        )
        if not result.success:
            return fail_run_from_gateway(run, "gateway_symbol_rule_failed", result)
        rules[symbol] = extract_symbol_info(result.payload, symbol)
        summaries.append({"symbol": symbol, **result_summary(result)})
    return rules, summaries


def gateway_context(run: BinanceSyncRun, request: SyncRequest, operation: str, *, symbol: str = "") -> BinanceGatewayCallContext:
    return BinanceGatewayCallContext(
        trace_id=request.trace_id,
        trigger_source=request.trigger_source,
        operation=operation,
        market_type=request.market_type,
        symbol=symbol,
        account_domain=request.account_domain,
        business_object_type="BinanceSyncRun",
        business_object_id=str(run.id),
        request_time_utc=timezone.now(),
    )


def build_snapshot_draft(*, request: SyncRequest, payloads: GatewayPayloads, as_of_utc: datetime) -> SnapshotDraft:
    position_mode = infer_position_mode(payloads.positions)
    rules = [normalize_symbol_rule(request, symbol, payload, as_of_utc) for symbol, payload in payloads.symbol_rules.items()]
    balances = [normalize_balance(request, item) for item in payloads.balances]
    positions = [normalize_position(request, item, position_mode) for item in payloads.positions]
    ensure_required_balance_assets(balances=balances, rules=rules)
    account = normalize_account(request, payloads.account, position_mode, as_of_utc)
    account["snapshot_hash"] = snapshot_hash("account", account)
    for collection_name, collection in (("balance", balances), ("position", positions), ("rule", rules)):
        for item in collection:
            item["snapshot_hash"] = snapshot_hash(collection_name, item)
    set_hash = stable_hash(
        {
            "sync_purpose": request.sync_purpose,
            "business_request_key": request.business_request_key,
            "market_type": request.market_type,
            "account_domain": request.account_domain,
            "position_mode": position_mode,
            "account": account["snapshot_hash"],
            "balances": sorted(item["snapshot_hash"] for item in balances),
            "positions": sorted(item["snapshot_hash"] for item in positions),
            "rules": sorted(item["snapshot_hash"] for item in rules),
        }
    )
    return SnapshotDraft(account=account, balances=balances, positions=positions, rules=rules, position_mode=position_mode, snapshot_set_hash=set_hash)


def normalize_account(request: SyncRequest, payload: dict[str, Any], position_mode: str, as_of_utc: datetime) -> dict[str, Any]:
    return {
        "market_type": request.market_type,
        "account_domain": request.account_domain,
        "fee_tier": optional_int(payload.get("feeTier")),
        "can_trade": optional_bool(payload.get("canTrade")),
        "can_deposit": optional_bool(payload.get("canDeposit")),
        "can_withdraw": optional_bool(payload.get("canWithdraw")),
        "position_mode": position_mode,
        "total_wallet_balance": optional_decimal(first_value(payload, "totalWalletBalance", "totalWalletBalanceOfBtc")),
        "total_unrealized_profit": optional_decimal(first_value(payload, "totalUnrealizedProfit", "totalUnrealizedPnL")),
        "total_margin_balance": optional_decimal(first_value(payload, "totalMarginBalance", "totalMarginBalanceOfBtc")),
        "available_balance": optional_decimal(first_value(payload, "availableBalance", "availableBalanceOfBtc")),
        "max_withdraw_amount": optional_decimal(first_value(payload, "maxWithdrawAmount", "maxWithdrawAmountOfBtc")),
        "native_asset": str(first_value(payload, "asset", "marginAsset", default="")),
        "as_of_utc": as_of_utc,
        "source_operation": "get_account",
        "raw_payload": sanitize_mapping(payload),
    }


def normalize_balance(request: SyncRequest, payload: dict[str, Any]) -> dict[str, Any]:
    asset = str(first_value(payload, "asset", "marginAsset", default="")).upper()
    if not asset:
        raise ValueError("balance payload 缺少 asset")
    return {
        "market_type": request.market_type,
        "account_domain": request.account_domain,
        "asset": asset,
        "wallet_balance": optional_decimal(first_value(payload, "balance", "walletBalance")),
        "cross_wallet_balance": optional_decimal(payload.get("crossWalletBalance")),
        "cross_unrealized_pnl": optional_decimal(first_value(payload, "crossUnPnl", "crossUnrealizedPnl")),
        "available_balance": optional_decimal(payload.get("availableBalance")),
        "max_withdraw_amount": optional_decimal(payload.get("maxWithdrawAmount")),
        "margin_available": optional_bool(payload.get("marginAvailable")),
        "update_time_utc": utc_from_millis(payload.get("updateTime")),
        "source_operation": "get_balances",
        "raw_payload": sanitize_mapping(payload),
    }


def normalize_position(request: SyncRequest, payload: dict[str, Any], position_mode: str) -> dict[str, Any]:
    symbol = str(payload.get("symbol") or "").upper()
    if not symbol:
        raise ValueError("position payload 缺少 symbol")
    raw_side = str(first_value(payload, "positionSide", "side", default="BOTH") or "BOTH").upper()
    return {
        "market_type": request.market_type,
        "account_domain": request.account_domain,
        "symbol": symbol,
        "raw_position_side": raw_side,
        "normalized_position_side": normalize_position_side(raw_side),
        "position_amount": optional_decimal(first_value(payload, "positionAmt", "positionAmount", "positionAmtInBaseAsset")),
        "entry_price": optional_decimal(payload.get("entryPrice")),
        "break_even_price": optional_decimal(payload.get("breakEvenPrice")),
        "mark_price": optional_decimal(payload.get("markPrice")),
        "unrealized_pnl": optional_decimal(first_value(payload, "unRealizedProfit", "unrealizedProfit", "unrealizedPnl")),
        "liquidation_price": optional_decimal(payload.get("liquidationPrice")),
        "isolated_margin": optional_decimal(payload.get("isolatedMargin")),
        "notional": optional_decimal(first_value(payload, "notional", "notionalValue")),
        "margin_asset": str(payload.get("marginAsset") or ""),
        "margin_mode": margin_mode(payload),
        "position_mode_observed": position_mode,
        "observed_exchange_leverage": positive_decimal_or_none(payload.get("leverage")),
        "update_time_utc": utc_from_millis(payload.get("updateTime")),
        "source_operation": "get_positions",
        "raw_payload": sanitize_mapping(payload),
    }


def normalize_symbol_rule(request: SyncRequest, symbol: str, payload: dict[str, Any], as_of_utc: datetime) -> dict[str, Any]:
    filters = payload.get("filters") if isinstance(payload.get("filters"), list) else []
    price_filter = filter_by_type(filters, "PRICE_FILTER")
    lot_filter = filter_by_type(filters, "LOT_SIZE") or filter_by_type(filters, "MARKET_LOT_SIZE")
    min_notional_filter = filter_by_type(filters, "MIN_NOTIONAL") or filter_by_type(filters, "NOTIONAL")
    contract_size = optional_decimal(payload.get("contractSize"))
    if request.market_type == "coin_m_futures" and (contract_size is None or contract_size <= ZERO):
        contract_size = None
    return {
        "market_type": request.market_type,
        "account_domain": request.account_domain,
        "symbol": str(payload.get("symbol") or symbol).upper(),
        "contract_status": str(first_value(payload, "status", "contractStatus", default="")),
        "base_asset": str(payload.get("baseAsset") or ""),
        "quote_asset": str(payload.get("quoteAsset") or ""),
        "margin_asset": str(first_value(payload, "marginAsset", "settleAsset", default="")),
        "settlement_asset": str(first_value(payload, "settleAsset", "marginAsset", default="")),
        "contract_type": str(payload.get("contractType") or ""),
        "price_precision": optional_int(payload.get("pricePrecision")),
        "quantity_precision": optional_int(first_value(payload, "quantityPrecision", "baseAssetPrecision")),
        "tick_size": optional_decimal(price_filter.get("tickSize")),
        "step_size": optional_decimal(lot_filter.get("stepSize")),
        "min_price": optional_decimal(price_filter.get("minPrice")),
        "max_price": optional_decimal(price_filter.get("maxPrice")),
        "min_quantity": optional_decimal(lot_filter.get("minQty")),
        "max_quantity": optional_decimal(lot_filter.get("maxQty")),
        "min_notional": optional_decimal(first_value(min_notional_filter, "notional", "minNotional")),
        "contract_size": contract_size,
        "supported_order_types": payload.get("orderTypes") if isinstance(payload.get("orderTypes"), list) else [],
        "raw_filters": filters,
        "source_operation": "get_symbol_exchange_info",
        "raw_payload": sanitize_mapping({**payload, "_as_of_utc": as_of_utc.isoformat()}),
    }


def publish_snapshot_set(
    *,
    run: BinanceSyncRun,
    request: SyncRequest,
    payloads: GatewayPayloads,
    draft: SnapshotDraft,
) -> None:
    as_of_utc = draft.account["as_of_utc"]
    expires_at = as_of_utc + timedelta(seconds=int(getattr(settings, "BINANCE_ACCOUNT_SYNC_TTL_SECONDS", 1800)))
    with transaction.atomic():
        BinanceAccountSnapshot.objects.create(sync_run=run, **draft.account)
        BinanceBalanceSnapshot.objects.bulk_create([BinanceBalanceSnapshot(sync_run=run, **item) for item in draft.balances])
        BinancePositionSnapshot.objects.bulk_create([BinancePositionSnapshot(sync_run=run, **item) for item in draft.positions])
        BinanceSymbolRuleSnapshot.objects.bulk_create([BinanceSymbolRuleSnapshot(sync_run=run, **item) for item in draft.rules])
        run.status = BinanceSyncStatus.SUCCEEDED
        run.position_mode = draft.position_mode
        run.snapshot_set_hash = draft.snapshot_set_hash
        run.gateway_call_summary = payloads.gateway_summary
        run.as_of_utc = as_of_utc
        run.expires_at_utc = expires_at
        run.finished_at_utc = timezone.now()
        run.save(update_fields=[
            "status",
            "position_mode",
            "snapshot_set_hash",
            "gateway_call_summary",
            "as_of_utc",
            "expires_at_utc",
            "finished_at_utc",
        ])


def result_from_run(run: BinanceSyncRun) -> ServiceResult:
    status = ResultStatus.SUCCEEDED
    reason = "binance_account_sync_succeeded"
    message = "Binance Account Sync 已成功"
    if run.status == BinanceSyncStatus.RUNNING:
        status = ResultStatus.BLOCKED
        reason = "binance_account_sync_running"
        message = "Binance Account Sync 正在运行，重复请求未启动第二次同步"
    elif run.status == BinanceSyncStatus.FAILED:
        status = ResultStatus.FAILED
        reason = run.error_code or "binance_account_sync_failed"
        message = run.error_message or "Binance Account Sync 失败"
    return ServiceResult(status, reason, message, run.trace_id, run.trigger_source, model_data(run))


def model_data(run: BinanceSyncRun) -> dict[str, Any]:
    return {
        "binance_sync_run_id": run.id,
        "business_request_key": run.business_request_key,
        "sync_purpose": run.sync_purpose,
        "status": run.status,
        "market_type": run.market_type,
        "account_domain": run.account_domain,
        "requested_symbols": run.requested_symbols,
        "position_mode": run.position_mode,
        "snapshot_set_hash": run.snapshot_set_hash,
        "as_of_utc": run.as_of_utc.isoformat() if run.as_of_utc else "",
        "expires_at_utc": run.expires_at_utc.isoformat() if run.expires_at_utc else "",
        "error_code": run.error_code,
        "error_message": run.error_message,
    }


def fail_run_from_gateway(run: BinanceSyncRun, reason_code: str, gateway_result: BinanceGatewayResult) -> ServiceResult:
    message = gateway_result.sanitized_error_message or gateway_result.error_category or reason_code
    payload = {
        "operation": gateway_result.operation,
        "market_type": gateway_result.market_type,
        "request_sent": gateway_result.request_sent,
        "response_received": gateway_result.response_received,
        "http_status": gateway_result.http_status,
        "error_category": gateway_result.error_category,
    }
    return fail_run(run, reason_code, message, payload_summary=payload)


def fail_run(
    run: BinanceSyncRun,
    reason_code: str,
    message: str,
    *,
    payload_summary: dict[str, Any] | None = None,
) -> ServiceResult:
    run.status = BinanceSyncStatus.FAILED
    run.error_code = reason_code
    run.error_message = limited_text(message)
    run.finished_at_utc = timezone.now()
    run.gateway_call_summary = payload_summary or run.gateway_call_summary
    run.save(update_fields=["status", "error_code", "error_message", "finished_at_utc", "gateway_call_summary"])
    write_failure_alert(run, reason_code=reason_code, message=message, payload_summary=payload_summary)
    return result_from_run(run)


def blocked_without_run(*, request: SyncRequest, reason_code: str) -> ServiceResult:
    record_account_sync_alert(
        event_type="binance_account_sync_blocked",
        severity="warning",
        title_zh="Binance Account Sync 请求被阻断",
        message_zh=f"账户同步请求未通过前置校验：{reason_code}",
        trace_id=request.trace_id or "missing-trace",
        trigger_source=request.trigger_source or "unknown",
        business_status=ResultStatus.BLOCKED.value,
        reason_code=reason_code,
        payload_summary={
            "business_request_key": request.business_request_key,
            "sync_purpose": request.sync_purpose,
            "market_type": request.market_type,
            "account_domain": request.account_domain,
        },
    )
    return ServiceResult(
        ResultStatus.BLOCKED,
        reason_code,
        "Binance Account Sync 请求被阻断",
        request.trace_id,
        request.trigger_source,
        {"binance_sync_run_id": None, "persisted": False},
    )


def write_failure_alert(
    run: BinanceSyncRun,
    *,
    reason_code: str,
    message: str,
    payload_summary: dict[str, Any] | None = None,
) -> None:
    record_account_sync_alert(
        event_type="binance_account_sync_failed",
        severity=failed_severity_for_purpose(run.sync_purpose),
        title_zh="Binance Account Sync 失败",
        message_zh=limited_text(message),
        trace_id=run.trace_id,
        trigger_source=run.trigger_source,
        business_status=run.status,
        reason_code=reason_code,
        related_object_id=str(run.id),
        payload_summary={**model_data(run), **(payload_summary or {})},
    )


def ensure_mapping(payload: Any, label: str) -> dict[str, Any]:
    if isinstance(payload, dict):
        return payload
    raise ValueError(f"{label} 必须是对象")


def ensure_list_of_mappings(payload: Any, label: str) -> list[dict[str, Any]]:
    if not isinstance(payload, list):
        raise ValueError(f"{label} 必须是数组")
    if not all(isinstance(item, dict) for item in payload):
        raise ValueError(f"{label} 只能包含对象")
    return payload


def extract_symbol_info(payload: Any, symbol: str) -> dict[str, Any]:
    if isinstance(payload, dict) and isinstance(payload.get("symbols"), list):
        for item in payload["symbols"]:
            if isinstance(item, dict) and item.get("symbol") == symbol:
                return item
        raise ValueError(f"exchangeInfo 未返回目标 symbol：{symbol}")
    if isinstance(payload, dict) and payload.get("symbol") == symbol:
        return payload
    raise ValueError("symbol exchange info payload 格式非法")


def zero_position_payload(symbol: str) -> dict[str, Any]:
    return {
        "symbol": symbol,
        "positionSide": "BOTH",
        "positionAmt": "0",
        "entryPrice": "0",
        "breakEvenPrice": "0",
        "markPrice": "0",
        "unRealizedProfit": "0",
        "liquidationPrice": "0",
        "isolatedMargin": "0",
        "notional": "0",
        "marginAsset": "",
        "isolated": False,
        "leverage": "",
        "updateTime": 0,
    }


def infer_position_mode(positions: list[dict[str, Any]]) -> str:
    sides = {str(item.get("positionSide") or "BOTH").upper() for item in positions}
    if {"LONG", "SHORT"} & sides:
        return BinancePositionMode.HEDGE
    if sides and sides <= {"BOTH"}:
        return BinancePositionMode.ONE_WAY
    return BinancePositionMode.UNKNOWN


def normalize_position_side(raw_side: str) -> str:
    side = raw_side.upper()
    if side in {"BOTH", "LONG", "SHORT"}:
        return side
    return "UNKNOWN"


def margin_mode(payload: dict[str, Any]) -> str:
    if str(payload.get("marginType") or "").strip():
        return str(payload.get("marginType")).lower()
    isolated = payload.get("isolated")
    if isinstance(isolated, bool):
        return "isolated" if isolated else "cross"
    if str(isolated).lower() in {"true", "1"}:
        return "isolated"
    if str(isolated).lower() in {"false", "0"}:
        return "cross"
    return ""


def ensure_required_balance_assets(*, balances: list[dict[str, Any]], rules: list[dict[str, Any]]) -> None:
    assets = {item["asset"] for item in balances}
    required = {str(rule.get("margin_asset") or rule.get("settlement_asset") or "").upper() for rule in rules}
    required.discard("")
    missing = sorted(required - assets)
    if missing:
        raise ValueError(f"缺少目标交易上下文所需余额资产：{','.join(missing)}")


def snapshot_hash(kind: str, payload: dict[str, Any]) -> str:
    clean = {key: value for key, value in payload.items() if key not in {"raw_payload", "snapshot_hash"}}
    return stable_hash({"kind": kind, **clean})


def result_summary(result: BinanceGatewayResult) -> dict[str, Any]:
    return {
        "success": result.success,
        "operation": result.operation,
        "request_sent": result.request_sent,
        "response_received": result.response_received,
        "http_status": result.http_status,
        "attempt_count": result.attempt_count,
        "error_category": result.error_category,
    }


def first_value(payload: dict[str, Any], *keys: str, default: Any = None) -> Any:
    for key in keys:
        value = payload.get(key)
        if value not in (None, ""):
            return value
    return default


def optional_decimal(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    decimal = Decimal(str(value))
    if not decimal.is_finite():
        return None
    return decimal


def positive_decimal_or_none(value: Any) -> Decimal | None:
    decimal = optional_decimal(value)
    if decimal is None or decimal <= ZERO:
        return None
    return decimal


def optional_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    return int(value)


def optional_bool(value: Any) -> bool | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return value
    normalized = str(value).strip().lower()
    if normalized in {"true", "1", "yes", "y"}:
        return True
    if normalized in {"false", "0", "no", "n"}:
        return False
    return None


def utc_from_millis(value: Any) -> datetime | None:
    if value in (None, "", 0, "0"):
        return None
    return datetime.fromtimestamp(int(value) / 1000, tz=UTC)


def filter_by_type(filters: list[Any], filter_type: str) -> dict[str, Any]:
    for item in filters:
        if isinstance(item, dict) and item.get("filterType") == filter_type:
            return item
    return {}


def limited_text(value: Any) -> str:
    text = str(value or "").strip()
    if len(text) <= MAX_ERROR_MESSAGE_LENGTH:
        return text
    return text[: MAX_ERROR_MESSAGE_LENGTH - 1] + "…"
