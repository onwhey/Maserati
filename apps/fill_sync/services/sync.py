"""FillSync 模块：同步终态订单成交事实；读写 MySQL；通过 BinanceGateway 只读查询成交；不访问 Redis；不发送 Hermes；不调用大模型；不提交订单；不修改账户快照。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from django.conf import settings
from django.db import DatabaseError, IntegrityError, transaction
from django.utils import timezone

from apps.audit.services import record_audit
from apps.binance_gateway.fill_query import BinanceFillQueryGateway, get_fill_query_gateway
from apps.binance_gateway.types import (
    MARKET_TYPE_COIN_M,
    MARKET_TYPE_USDS_M,
    BinanceGatewayCallContext,
    BinanceGatewayResult,
)
from apps.execution.models import OrderSubmissionAttempt
from apps.foundation.redaction import sanitize_mapping
from apps.foundation.results import ResultStatus, ServiceResult
from apps.order_plan.models import ActiveLockStatus
from apps.order_plan.services.active_lock import finalize_after_fill_sync
from apps.order_status_sync.models import OrderStatusQueryOutcome, OrderStatusSyncRecord

from ..models import (
    FillSyncMode,
    FillSyncResult,
    FillSyncResultStatus,
    OrderFillSummary,
    OrderFillSummaryStatus,
    TradeFill,
)
from .alerts import record_fill_sync_alert
from .hashing import fill_sync_input_hash, fill_sync_result_key_hash, order_fill_summary_hash, trade_fill_hash


MAX_KEY_LENGTH = 191
MAX_TRACE_FIELD_LENGTH = 80
ZERO = Decimal("0")
TERMINAL_STATUSES = {"FILLED", "CANCELED", "REJECTED", "EXPIRED", "EXPIRED_IN_MATCH"}


@dataclass(frozen=True)
class SyncClaim:
    result: FillSyncResult | None
    should_call_gateway: bool
    replay: bool = False
    service_result: ServiceResult | None = None


@dataclass
class PageStats:
    page_count: int = 0
    gateway_attempt_count_total: int = 0
    returned_fill_count: int = 0
    inserted_fill_count: int = 0
    duplicate_fill_count: int = 0
    conflict_fill_count: int = 0
    pagination_complete: bool = False
    reason_code: str = "fill_sync_synced"
    reason_message: str = "成交同步完成。"
    status: str = FillSyncResultStatus.SYNCED
    evidence: dict[str, Any] | None = None


def sync_order_fills(
    *,
    order_submission_attempt_id: int,
    terminal_order_status_sync_record_id: int,
    business_request_key: str,
    trace_id: str,
    trigger_source: str,
    gateway: BinanceFillQueryGateway | None = None,
    sync_mode: str = FillSyncMode.NORMAL,
) -> ServiceResult:
    request_error = _request_error(
        order_submission_attempt_id=order_submission_attempt_id,
        terminal_order_status_sync_record_id=terminal_order_status_sync_record_id,
        business_request_key=business_request_key,
        trace_id=trace_id,
        trigger_source=trigger_source,
    )
    if request_error:
        return _result_without_sync(request_error, "FillSync 请求合同不完整。", trace_id, trigger_source)
    try:
        claim = _claim_fill_sync_result(
            order_submission_attempt_id=order_submission_attempt_id,
            terminal_order_status_sync_record_id=terminal_order_status_sync_record_id,
            business_request_key=business_request_key,
            trace_id=trace_id,
            trigger_source=trigger_source,
            sync_mode=sync_mode,
        )
    except OrderSubmissionAttempt.DoesNotExist:
        return _result_without_sync("order_submission_attempt_not_found", "OrderSubmissionAttempt 不存在。", trace_id, trigger_source)
    except OrderStatusSyncRecord.DoesNotExist:
        return _result_without_sync("terminal_order_status_record_not_found", "终态 OrderStatusSyncRecord 不存在。", trace_id, trigger_source)
    except DatabaseError as exc:
        return _result_without_sync("internal_error", type(exc).__name__, trace_id, trigger_source, failed=True)

    if claim.service_result is not None:
        return claim.service_result
    if claim.result is None:
        return _result_without_sync("fill_sync_claim_failed", "未能创建成交同步结果。", trace_id, trigger_source, failed=True)
    if claim.replay or not claim.should_call_gateway:
        if claim.replay:
            _record_result_alert(claim.result, "fill_sync_idempotent_replay")
            return _service_result_from_result(claim.result, replay=True)
        _record_result_alert(claim.result, _event_type_for_result(claim.result))
        return _service_result_from_result(claim.result)

    stats = _query_and_persist_fills(claim.result, gateway or get_fill_query_gateway())
    result = _finalize_result_from_stats(claim.result.id, stats)
    summary = _recompute_order_fill_summary(result)
    _finalize_lock_if_safe(result, summary)
    result.refresh_from_db()
    _record_result_alert(result, _event_type_for_result(result))
    return _service_result_from_result(result)


def recover_order_fills(
    *,
    order_submission_attempt_id: int,
    terminal_order_status_sync_record_id: int,
    operator_id: str,
    reason: str,
    trace_id: str,
    trigger_source: str = "ops_console_fill_sync_recovery",
    gateway: BinanceFillQueryGateway | None = None,
) -> ServiceResult:
    reason = reason.strip()
    if not reason:
        return _result_without_sync("fill_sync_recovery_reason_required", "成交受控补同步需要记录人工原因。", trace_id, trigger_source)
    if not operator_id:
        return _result_without_sync("operator_required", "成交受控补同步需要记录操作者。", trace_id, trigger_source)
    if _has_complete_summary(order_submission_attempt_id):
        result = ServiceResult(
            ResultStatus.NO_ACTION,
            "fill_summary_already_complete",
            "订单成交汇总已经完整，不重复发起成交补同步。",
            trace_id,
            trigger_source,
            {
                "order_submission_attempt_id": order_submission_attempt_id,
                "terminal_order_status_sync_record_id": terminal_order_status_sync_record_id,
                "fill_sync_result_id": None,
                "allows_active_lock_finalization": False,
                "flow_action": "STOP",
            },
        )
    else:
        result = sync_order_fills(
            order_submission_attempt_id=order_submission_attempt_id,
            terminal_order_status_sync_record_id=terminal_order_status_sync_record_id,
            business_request_key=f"ops_fill_sync_recovery:{order_submission_attempt_id}:{terminal_order_status_sync_record_id}:{trace_id}",
            trace_id=trace_id,
            trigger_source=trigger_source,
            gateway=gateway,
            sync_mode=FillSyncMode.RECOVERY,
        )

    audit = record_audit(
        operator_id=operator_id,
        operation_type="fill_sync_controlled_resync",
        target_object_type="OrderSubmissionAttempt",
        target_object_id=str(order_submission_attempt_id),
        before_state_summary={
            "terminal_order_status_sync_record_id": terminal_order_status_sync_record_id,
            "has_complete_summary": _has_complete_summary(order_submission_attempt_id),
        },
        after_state_summary=result.data,
        reason=reason[:500],
        evidence={"sync_mode": FillSyncMode.RECOVERY, "trace_id": trace_id},
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


def _claim_fill_sync_result(
    *,
    order_submission_attempt_id: int,
    terminal_order_status_sync_record_id: int,
    business_request_key: str,
    trace_id: str,
    trigger_source: str,
    sync_mode: str,
) -> SyncClaim:
    now = timezone.now()
    with transaction.atomic():
        attempt = _locked_attempt(order_submission_attempt_id)
        terminal = _locked_terminal_record(terminal_order_status_sync_record_id)
        existing = FillSyncResult.objects.select_for_update().filter(
            fill_sync_result_key=_result_key(attempt.id, terminal.id, business_request_key)
        ).first()
        if existing is not None:
            if existing.sync_finished_at_utc is None and existing.status == FillSyncResultStatus.SYNCING:
                return SyncClaim(existing, should_call_gateway=False, service_result=_in_progress_result(existing))
            return SyncClaim(existing, should_call_gateway=False, replay=True)

        pre_error = _pre_query_error(attempt, terminal, now, sync_mode=sync_mode)
        status = _status_for_pre_error(pre_error)
        sequence = (
            FillSyncResult.objects.select_for_update()
            .filter(order_submission_attempt=attempt, terminal_order_status_sync_record=terminal)
            .count()
            + 1
        )
        result = FillSyncResult.objects.create(
            fill_sync_result_key=_result_key(attempt.id, terminal.id, business_request_key),
            sync_sequence=sequence,
            sync_mode=sync_mode,
            status=FillSyncResultStatus.SYNCING if not pre_error else status,
            reason_code="fill_sync_claimed" if not pre_error else pre_error,
            reason_message="FillSync 已取得本次成交同步资格。" if not pre_error else _reason_message(pre_error),
            order_submission_attempt=attempt,
            terminal_order_status_sync_record=terminal,
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
            exchange_order_id=_exchange_order_id(attempt, terminal),
            terminal_exchange_status=terminal.exchange_status,
            terminal_executed_quantity=_terminal_quantity(terminal),
            terminal_cumulative_quote_quantity=_terminal_quote_quantity(terminal),
            sync_started_at_utc=now,
            sync_finished_at_utc=now if pre_error else None,
            config_snapshot=_config_snapshot(),
            input_hash=_input_hash(attempt, terminal),
            evidence={"pre_query_error": pre_error} if pre_error else {},
            trace_id=trace_id,
            trigger_source=trigger_source,
        )
        return SyncClaim(result, should_call_gateway=not bool(pre_error))


def _locked_attempt(order_submission_attempt_id: int) -> OrderSubmissionAttempt:
    return (
        OrderSubmissionAttempt.objects.select_for_update()
        .select_related("prepared_order_intent", "order_plan", "active_lock")
        .get(id=order_submission_attempt_id)
    )


def _locked_terminal_record(terminal_order_status_sync_record_id: int) -> OrderStatusSyncRecord:
    return (
        OrderStatusSyncRecord.objects.select_for_update()
        .select_related("order_submission_attempt", "prepared_order_intent", "order_plan", "active_lock")
        .get(id=terminal_order_status_sync_record_id)
    )


def _pre_query_error(attempt: OrderSubmissionAttempt, terminal: OrderStatusSyncRecord, now: datetime, *, sync_mode: str) -> str:
    if not getattr(settings, "FILL_SYNC_ENABLED", False):
        return "fill_sync_disabled"
    if terminal.order_submission_attempt_id != attempt.id:
        return "terminal_record_attempt_mismatch"
    if terminal.query_outcome != OrderStatusQueryOutcome.FOUND:
        return "terminal_record_not_found_outcome"
    if not terminal.is_terminal_status:
        return "terminal_record_not_terminal"
    if terminal.exchange_status not in TERMINAL_STATUSES:
        return "unsupported_terminal_exchange_status"
    if _market_identity_mismatch(attempt, terminal):
        return "market_identity_mismatch"
    if not _exchange_order_id(attempt, terminal):
        return "missing_exchange_order_id"
    if attempt.finished_at_utc and now < _ensure_utc(attempt.finished_at_utc):
        return "sync_time_before_order_submission_fact"
    if terminal.query_finished_at_utc and now < _ensure_utc(terminal.query_finished_at_utc):
        return "sync_time_before_terminal_status_fact"
    if sync_mode == FillSyncMode.RECOVERY:
        recovery_error = _recovery_pre_query_error(attempt, terminal, now)
        if recovery_error:
            return recovery_error
    latest_finished = (
        FillSyncResult.objects.filter(order_submission_attempt=attempt, sync_finished_at_utc__isnull=False)
        .order_by("-sync_finished_at_utc")
        .first()
    )
    if latest_finished is not None and now < _ensure_utc(latest_finished.sync_finished_at_utc):
        return "sync_time_before_existing_fill_sync_fact"
    return ""


def _recovery_pre_query_error(attempt: OrderSubmissionAttempt, terminal: OrderStatusSyncRecord, now: datetime) -> str:
    if attempt.active_lock_id is None or attempt.active_lock.status != ActiveLockStatus.ACTIVE:
        return "active_lock_not_active_for_recovery"
    if _has_complete_summary(attempt.id):
        return "fill_summary_already_complete"
    recovery_window = max(0, int(getattr(settings, "FILL_SYNC_RECOVERY_WINDOW_SECONDS", 86400)))
    terminal_time = terminal.query_finished_at_utc or terminal.updated_at_utc
    if terminal_time and now > _ensure_utc(terminal_time) + timedelta(seconds=recovery_window):
        return "fill_sync_recovery_out_of_window"
    return ""


def _has_complete_summary(order_submission_attempt_id: int) -> bool:
    return OrderFillSummary.objects.filter(
        order_submission_attempt_id=order_submission_attempt_id,
        status__in=[OrderFillSummaryStatus.COMPLETE, OrderFillSummaryStatus.EMPTY],
    ).exists()


def _market_identity_mismatch(attempt: OrderSubmissionAttempt, terminal: OrderStatusSyncRecord) -> bool:
    return any(
        [
            attempt.exchange.lower() != terminal.exchange.lower(),
            attempt.market_type != terminal.market_type,
            attempt.account_domain != terminal.account_domain,
            attempt.symbol != terminal.symbol,
            attempt.order_plan_id != terminal.order_plan_id,
            attempt.active_lock_id != terminal.active_lock_id,
        ]
    )


def _query_and_persist_fills(result: FillSyncResult, gateway: BinanceFillQueryGateway) -> PageStats:
    stats = PageStats(evidence={"pages": []})
    cursor: str | None = None
    seen_cursors: set[str] = set()
    page_size = max(1, int(getattr(settings, "FILL_SYNC_PAGE_SIZE", 100)))
    max_pages = max(1, int(getattr(settings, "FILL_SYNC_MAX_PAGES", 10)))

    for page_sequence in range(1, max_pages + 1):
        if cursor and cursor in seen_cursors:
            stats.status = FillSyncResultStatus.INCOMPLETE
            stats.reason_code = "pagination_cursor_loop"
            stats.reason_message = "成交查询分页游标循环，成交证据不完整。"
            break
        if cursor:
            seen_cursors.add(cursor)
        gateway_result = _call_gateway(result, gateway, page_sequence=page_sequence, page_cursor=cursor, page_size=page_size)
        stats.page_count += 1
        stats.gateway_attempt_count_total += int(gateway_result.attempt_count or 0)
        page_evidence = _page_evidence(page_sequence, cursor, gateway_result)
        stats.evidence["pages"].append(page_evidence)
        if not gateway_result.success or not gateway_result.request_sent or not gateway_result.response_received:
            stats.status = FillSyncResultStatus.FAILED_BEFORE_QUERY if not gateway_result.request_sent else FillSyncResultStatus.UNKNOWN
            stats.reason_code = "fill_query_failed_before_send" if not gateway_result.request_sent else "fill_query_unknown"
            stats.reason_message = gateway_result.sanitized_error_message or _reason_message(stats.reason_code)
            break
        page_payload = gateway_result.payload if isinstance(gateway_result.payload, dict) else {}
        fills = page_payload.get("fills")
        if not isinstance(fills, list):
            stats.status = FillSyncResultStatus.UNKNOWN
            stats.reason_code = "fill_query_response_schema_error"
            stats.reason_message = "成交查询响应结构不符合约定。"
            break
        page_write = _persist_page_fills(result, fills)
        stats.returned_fill_count += page_write["returned"]
        stats.inserted_fill_count += page_write["inserted"]
        stats.duplicate_fill_count += page_write["duplicate"]
        stats.conflict_fill_count += page_write["conflict"]
        if page_write["conflict"]:
            stats.status = FillSyncResultStatus.INCOMPLETE
            stats.reason_code = page_write["reason_code"]
            stats.reason_message = _reason_message(page_write["reason_code"])
            stats.evidence.setdefault("conflicts", []).extend(page_write["conflicts"])
            break
        if page_payload.get("pagination_complete") is True:
            stats.pagination_complete = True
            break
        next_cursor = str(page_payload.get("next_page_cursor") or "").strip()
        if not next_cursor:
            stats.status = FillSyncResultStatus.INCOMPLETE
            stats.reason_code = "pagination_not_complete_without_cursor"
            stats.reason_message = "成交查询未确认分页完整，且没有下一页游标。"
            break
        cursor = next_cursor
    else:
        stats.status = FillSyncResultStatus.INCOMPLETE
        stats.reason_code = "pagination_max_pages_reached"
        stats.reason_message = "成交查询达到最大分页数，仍未确认分页完整。"

    return stats


def _call_gateway(
    result: FillSyncResult,
    gateway: BinanceFillQueryGateway,
    *,
    page_sequence: int,
    page_cursor: str | None,
    page_size: int,
) -> BinanceGatewayResult:
    try:
        return gateway.query_order_fills(
            market_type=result.market_type,
            symbol=result.symbol,
            exchange_order_id=result.exchange_order_id,
            page_cursor=page_cursor,
            page_size=page_size,
            call_context=BinanceGatewayCallContext(
                trace_id=result.trace_id,
                trigger_source=result.trigger_source,
                operation="query_order_fills",
                market_type=result.market_type,
                account_domain=result.account_domain,
                symbol=result.symbol,
                business_object_type="OrderSubmissionAttempt",
                business_object_id=str(result.order_submission_attempt_id),
                request_time_utc=timezone.now(),
                metadata={
                    "order_submission_attempt_id": result.order_submission_attempt_id,
                    "terminal_order_status_sync_record_id": result.terminal_order_status_sync_record_id,
                    "fill_sync_result_id": result.id,
                    "exchange_order_id": result.exchange_order_id,
                    "page_sequence": page_sequence,
                    "page_cursor": page_cursor or "",
                    "page_size": page_size,
                },
            ),
        )
    except Exception as exc:
        now = timezone.now()
        return BinanceGatewayResult(
            operation="query_order_fills",
            market_type=result.market_type,
            endpoint_family=result.endpoint_family,
            success=False,
            request_sent=True,
            response_received=False,
            error_category="gateway_failed",
            sanitized_error_message=type(exc).__name__,
            request_started_at_utc=now,
            request_finished_at_utc=now,
            attempt_count=1,
            trace_id=result.trace_id,
        )


def _persist_page_fills(result: FillSyncResult, fills: list[Any]) -> dict[str, Any]:
    returned = len(fills)
    inserted = duplicate = conflict = 0
    conflicts: list[dict[str, Any]] = []
    with transaction.atomic():
        locked_result = FillSyncResult.objects.select_for_update().get(id=result.id)
        for raw in fills:
            normalized = _normalize_raw_fill(locked_result, raw)
            if normalized["reason_code"]:
                conflict += 1
                conflicts.append(normalized["evidence"])
                continue
            trade_identity_hash = _trade_identity_hash(locked_result, normalized["exchange_trade_id"])
            existing = TradeFill.objects.select_for_update().filter(trade_identity_hash=trade_identity_hash).first()
            if existing is not None:
                if existing.raw_fill_hash == normalized["raw_fill_hash"]:
                    duplicate += 1
                else:
                    conflict += 1
                    conflicts.append(
                        {
                            "reason_code": "trade_fill_payload_conflict",
                            "exchange_trade_id": normalized["exchange_trade_id"],
                            "existing_trade_fill_id": existing.id,
                        }
                    )
                continue
            try:
                TradeFill.objects.create(
                    order_submission_attempt=locked_result.order_submission_attempt,
                    terminal_order_status_sync_record=locked_result.terminal_order_status_sync_record,
                    first_seen_fill_sync_result=locked_result,
                    exchange=locked_result.exchange,
                    market_type=locked_result.market_type,
                    account_domain=locked_result.account_domain,
                    endpoint_family=locked_result.endpoint_family,
                    symbol=locked_result.symbol,
                    client_order_id=locked_result.client_order_id,
                    exchange_order_id=locked_result.exchange_order_id,
                    exchange_trade_id=normalized["exchange_trade_id"],
                    trade_identity_hash=trade_identity_hash,
                    side=normalized["side"],
                    position_side=normalized["position_side"],
                    price=normalized["price"],
                    quantity=normalized["quantity"],
                    quantity_unit=normalized["quantity_unit"],
                    contract_size=normalized["contract_size"],
                    quote_quantity=normalized["quote_quantity"],
                    base_quantity=normalized["base_quantity"],
                    commission=normalized["commission"],
                    commission_asset=normalized["commission_asset"],
                    realized_pnl=normalized["realized_pnl"],
                    realized_pnl_asset=normalized["realized_pnl_asset"],
                    is_buyer=normalized["is_buyer"],
                    is_maker=normalized["is_maker"],
                    trade_time_utc=normalized["trade_time_utc"],
                    sanitized_raw_fill=normalized["sanitized_raw_fill"],
                    raw_fill_hash=normalized["raw_fill_hash"],
                    trigger_source=locked_result.trigger_source,
                )
                inserted += 1
            except IntegrityError:
                duplicate += 1
    reason_code = ""
    if conflict:
        reason_code = conflicts[0].get("reason_code") or "trade_fill_conflict"
    return {
        "returned": returned,
        "inserted": inserted,
        "duplicate": duplicate,
        "conflict": conflict,
        "conflicts": conflicts,
        "reason_code": reason_code,
    }


def _normalize_raw_fill(result: FillSyncResult, raw: Any) -> dict[str, Any]:
    sanitized = sanitize_mapping(raw if isinstance(raw, dict) else {"raw": raw})
    invalid = _invalid_raw_fill_reason(result, sanitized)
    if invalid:
        return {
            "reason_code": invalid,
            "evidence": {
                "reason_code": invalid,
                "raw_fill": sanitized,
            },
        }
    price = _decimal(sanitized.get("price"))
    quantity = _decimal(sanitized.get("qty") or sanitized.get("quantity"))
    contract_size = _coin_contract_size(result) if result.market_type == MARKET_TYPE_COIN_M else None
    quote_quantity = _decimal(sanitized.get("quoteQty") or sanitized.get("quote_quantity"))
    base_quantity = _decimal(sanitized.get("baseQty") or sanitized.get("base_quantity"))
    if result.market_type == MARKET_TYPE_USDS_M:
        quantity_unit = "base"
        base_quantity = base_quantity or quantity
        quote_quantity = quote_quantity or price * quantity
    elif result.market_type == MARKET_TYPE_COIN_M:
        quantity_unit = "contracts"
    else:
        quantity_unit = "unknown"
    commission = _decimal(sanitized.get("commission"))
    realized_pnl = _decimal(sanitized.get("realizedPnl") or sanitized.get("realized_pnl"))
    return {
        "reason_code": "",
        "exchange_trade_id": str(sanitized.get("id") or sanitized.get("tradeId") or sanitized.get("trade_id")),
        "side": str(sanitized.get("side") or result.order_submission_attempt.side).upper(),
        "position_side": str(sanitized.get("positionSide") or result.order_submission_attempt.position_side or "BOTH").upper(),
        "price": price,
        "quantity": quantity,
        "quantity_unit": quantity_unit,
        "contract_size": contract_size,
        "quote_quantity": quote_quantity,
        "base_quantity": base_quantity,
        "commission": commission,
        "commission_asset": str(sanitized.get("commissionAsset") or sanitized.get("commission_asset") or ""),
        "realized_pnl": realized_pnl,
        "realized_pnl_asset": _realized_pnl_asset(result, sanitized),
        "is_buyer": _optional_bool(sanitized.get("buyer") if "buyer" in sanitized else sanitized.get("isBuyer")),
        "is_maker": _optional_bool(sanitized.get("maker") if "maker" in sanitized else sanitized.get("isMaker")),
        "trade_time_utc": _time_from_millis(sanitized.get("time")),
        "sanitized_raw_fill": sanitized,
        "raw_fill_hash": trade_fill_hash(sanitized),
    }


def _invalid_raw_fill_reason(result: FillSyncResult, fill: dict[str, Any]) -> str:
    returned_symbol = str(fill.get("symbol") or "").upper()
    if not returned_symbol:
        return "trade_fill_symbol_missing"
    if returned_symbol != result.symbol.upper():
        return "trade_fill_symbol_mismatch"
    returned_order_id = str(fill.get("orderId") or fill.get("order_id") or "")
    if not returned_order_id:
        return "trade_fill_order_id_missing"
    if returned_order_id != result.exchange_order_id:
        return "trade_fill_order_id_mismatch"
    if not str(fill.get("id") or fill.get("tradeId") or fill.get("trade_id") or ""):
        return "trade_fill_id_missing"
    price = _decimal(fill.get("price"))
    quantity = _decimal(fill.get("qty") or fill.get("quantity"))
    if price <= ZERO:
        return "trade_fill_price_invalid"
    if quantity <= ZERO:
        return "trade_fill_quantity_invalid"
    if result.market_type == MARKET_TYPE_COIN_M:
        contract_size = _coin_contract_size(result)
        if contract_size is None or contract_size <= ZERO:
            return "coin_m_contract_size_missing"
        base_quantity = _decimal(fill.get("baseQty") or fill.get("base_quantity"))
        if base_quantity <= ZERO:
            return "coin_m_base_quantity_missing"
    if _time_from_millis(fill.get("time")) is None:
        return "trade_fill_time_invalid"
    side = str(fill.get("side") or result.order_submission_attempt.side or "").upper()
    if side not in {"BUY", "SELL"}:
        return "trade_fill_side_invalid"
    position_side = str(fill.get("positionSide") or result.order_submission_attempt.position_side or "BOTH").upper()
    if position_side not in {"BOTH", "LONG", "SHORT"}:
        return "trade_fill_position_side_invalid"
    return ""


def _trade_identity_hash(result: FillSyncResult, exchange_trade_id: str) -> str:
    return trade_fill_hash(
        {
            "exchange": result.exchange,
            "market_type": result.market_type,
            "account_domain": result.account_domain,
            "symbol": result.symbol,
            "exchange_order_id": result.exchange_order_id,
            "exchange_trade_id": exchange_trade_id,
        }
    )


def _finalize_result_from_stats(result_id: int, stats: PageStats) -> FillSyncResult:
    with transaction.atomic():
        result = FillSyncResult.objects.select_for_update().get(id=result_id)
        result.page_count = stats.page_count
        result.pagination_complete = stats.pagination_complete
        result.gateway_attempt_count_total = stats.gateway_attempt_count_total
        result.returned_fill_count = stats.returned_fill_count
        result.inserted_fill_count = stats.inserted_fill_count
        result.duplicate_fill_count = stats.duplicate_fill_count
        result.conflict_fill_count = stats.conflict_fill_count
        result.evidence = {**(result.evidence or {}), **(stats.evidence or {})}
        result.status = stats.status
        result.reason_code = stats.reason_code
        result.reason_message = stats.reason_message
        result.sync_finished_at_utc = timezone.now()
        result.save()
        return result


def _recompute_order_fill_summary(result: FillSyncResult) -> OrderFillSummary:
    fills = list(TradeFill.objects.filter(order_submission_attempt=result.order_submission_attempt).order_by("trade_time_utc", "id"))
    total_quantity = sum((fill.quantity for fill in fills), ZERO)
    total_quote_quantity = sum((fill.quote_quantity or ZERO for fill in fills), ZERO)
    total_base_quantity = sum((fill.base_quantity or ZERO for fill in fills), ZERO)
    filled_notional_usd = _filled_notional_usd(result.market_type, fills, total_quote_quantity)
    commission_by_asset = _sum_by_asset(fills, value_attr="commission", asset_attr="commission_asset")
    realized_pnl_by_asset = _sum_by_asset(fills, value_attr="realized_pnl", asset_attr="realized_pnl_asset")
    average_price = _average_price(result.market_type, total_quantity, total_quote_quantity, total_base_quantity, filled_notional_usd)
    reconciled = _quantity_reconciled(result.terminal_executed_quantity, total_quantity)
    quote_reconciled = _quote_reconciled(result.terminal_cumulative_quote_quantity, total_quote_quantity)
    status, reason_code = _summary_status(result, fills, reconciled, filled_notional_usd)
    summary_values = {
        "latest_fill_sync_result": result,
        "terminal_order_status_sync_record": result.terminal_order_status_sync_record,
        "status": status,
        "reason_code": reason_code,
        "exchange": result.exchange,
        "market_type": result.market_type,
        "account_domain": result.account_domain,
        "endpoint_family": result.endpoint_family,
        "symbol": result.symbol,
        "client_order_id": result.client_order_id,
        "exchange_order_id": result.exchange_order_id,
        "terminal_exchange_status": result.terminal_exchange_status,
        "fill_count": len(fills),
        "total_quantity": total_quantity,
        "total_quote_quantity": total_quote_quantity,
        "total_base_quantity": total_base_quantity,
        "filled_notional_usd": filled_notional_usd,
        "average_price": average_price,
        "commission_by_asset": commission_by_asset,
        "realized_pnl_by_asset": realized_pnl_by_asset,
        "terminal_executed_quantity": result.terminal_executed_quantity,
        "terminal_cumulative_quote_quantity": result.terminal_cumulative_quote_quantity,
        "quantity_reconciled": reconciled,
        "quote_reconciled": quote_reconciled,
        "identity_reconciled": result.conflict_fill_count == 0,
        "pagination_complete": result.pagination_complete,
        "summary_hash": order_fill_summary_hash(
            {
                "fill_ids": [fill.id for fill in fills],
                "total_quantity": total_quantity,
                "total_quote_quantity": total_quote_quantity,
                "status": status,
                "reason_code": reason_code,
            }
        ),
    }
    with transaction.atomic():
        summary, _created = OrderFillSummary.objects.update_or_create(
            order_submission_attempt=result.order_submission_attempt,
            defaults=summary_values,
        )
        if status == OrderFillSummaryStatus.COMPLETE and result.status != FillSyncResultStatus.SYNCED:
            result.status = FillSyncResultStatus.SYNCED
            result.reason_code = "fill_sync_synced"
            result.reason_message = "成交同步完成。"
            result.save(update_fields=["status", "reason_code", "reason_message", "updated_at_utc"])
        elif status == OrderFillSummaryStatus.EMPTY and result.status != FillSyncResultStatus.SYNCED_EMPTY:
            result.status = FillSyncResultStatus.SYNCED_EMPTY
            result.reason_code = "fill_sync_synced_empty"
            result.reason_message = "成交同步完成，交易所确认该终态订单无成交。"
            result.save(update_fields=["status", "reason_code", "reason_message", "updated_at_utc"])
        elif status == OrderFillSummaryStatus.INCOMPLETE and result.status == FillSyncResultStatus.SYNCED:
            result.status = FillSyncResultStatus.INCOMPLETE
            result.reason_code = reason_code
            result.reason_message = _reason_message(reason_code)
            result.save(update_fields=["status", "reason_code", "reason_message", "updated_at_utc"])
        return summary


def _summary_status(
    result: FillSyncResult,
    fills: list[TradeFill],
    quantity_reconciled: bool,
    filled_notional_usd: Decimal | None,
) -> tuple[str, str]:
    if result.status not in {FillSyncResultStatus.SYNCED, FillSyncResultStatus.SYNCING}:
        return OrderFillSummaryStatus.INCOMPLETE, result.reason_code
    if not result.pagination_complete:
        return OrderFillSummaryStatus.INCOMPLETE, "pagination_incomplete"
    if not fills:
        if result.terminal_exchange_status == "FILLED":
            return OrderFillSummaryStatus.INCOMPLETE, "filled_order_has_no_fills"
        if result.terminal_executed_quantity == ZERO:
            return OrderFillSummaryStatus.EMPTY, "fill_sync_synced_empty"
        return OrderFillSummaryStatus.INCOMPLETE, "terminal_quantity_missing_for_empty_fills"
    if not quantity_reconciled:
        return OrderFillSummaryStatus.INCOMPLETE, "filled_quantity_mismatch"
    if result.market_type == MARKET_TYPE_COIN_M and (filled_notional_usd is None or filled_notional_usd <= ZERO):
        return OrderFillSummaryStatus.INCOMPLETE, "coin_m_notional_calculation_failed"
    if result.market_type == MARKET_TYPE_COIN_M and sum((fill.base_quantity or ZERO for fill in fills), ZERO) <= ZERO:
        return OrderFillSummaryStatus.INCOMPLETE, "coin_m_base_quantity_missing"
    if result.conflict_fill_count:
        return OrderFillSummaryStatus.INCOMPLETE, "trade_fill_conflict"
    return OrderFillSummaryStatus.COMPLETE, "fill_sync_synced"


def _finalize_lock_if_safe(result: FillSyncResult, summary: OrderFillSummary) -> None:
    if result.status not in {FillSyncResultStatus.SYNCED, FillSyncResultStatus.SYNCED_EMPTY}:
        return
    if summary.status not in {OrderFillSummaryStatus.COMPLETE, OrderFillSummaryStatus.EMPTY}:
        return
    release = finalize_after_fill_sync(
        active_lock_id=result.active_lock_id,
        order_plan_id=result.order_plan_id,
        source_module="FillSync",
        source_object_id=result.id,
        reason_code=result.reason_code,
        evidence={
            "fill_sync_result_id": result.id,
            "order_fill_summary_id": summary.id,
            "order_submission_attempt_id": result.order_submission_attempt_id,
            "terminal_order_status_sync_record_id": result.terminal_order_status_sync_record_id,
            "status": result.status,
            "fill_count": summary.fill_count,
            "quantity_reconciled": summary.quantity_reconciled,
            "pagination_complete": summary.pagination_complete,
        },
        trace_id=result.trace_id,
        trigger_source=result.trigger_source,
    )
    summary.lock_finalization_status = release.reason_code
    if release.released:
        summary.lock_finalized_at_utc = timezone.now()
    summary.save(update_fields=["lock_finalization_status", "lock_finalized_at_utc", "updated_at_utc"])


def _service_result_from_result(result: FillSyncResult, *, replay: bool = False) -> ServiceResult:
    status = _service_status(result)
    reason_code = "fill_sync_idempotent_replay" if replay else result.reason_code
    message = "FillSync 幂等重放，未重新调用 Gateway。" if replay else result.reason_message
    return ServiceResult(status, reason_code, message, result.trace_id, result.trigger_source, _result_data(result))


def _service_status(result: FillSyncResult) -> ResultStatus:
    if result.status in {FillSyncResultStatus.SYNCED, FillSyncResultStatus.SYNCED_EMPTY}:
        return ResultStatus.SUCCEEDED
    if result.status == FillSyncResultStatus.INCOMPLETE:
        return ResultStatus.UNKNOWN
    if result.status == FillSyncResultStatus.UNKNOWN:
        return ResultStatus.UNKNOWN
    if result.status == FillSyncResultStatus.FAILED_BEFORE_QUERY:
        return ResultStatus.FAILED
    if result.status == FillSyncResultStatus.BLOCKED_BEFORE_QUERY:
        return ResultStatus.BLOCKED
    return ResultStatus.NO_ACTION


def _result_data(result: FillSyncResult) -> dict[str, Any]:
    return {
        "fill_sync_result_id": result.id,
        "order_submission_attempt_id": result.order_submission_attempt_id,
        "terminal_order_status_sync_record_id": result.terminal_order_status_sync_record_id,
        "fill_sync_status": result.status,
        "returned_fill_count": result.returned_fill_count,
        "inserted_fill_count": result.inserted_fill_count,
        "duplicate_fill_count": result.duplicate_fill_count,
        "conflict_fill_count": result.conflict_fill_count,
        "pagination_complete": result.pagination_complete,
        "allows_active_lock_finalization": result.status in {FillSyncResultStatus.SYNCED, FillSyncResultStatus.SYNCED_EMPTY},
        "flow_action": "COMPLETE" if result.status in {FillSyncResultStatus.SYNCED, FillSyncResultStatus.SYNCED_EMPTY, FillSyncResultStatus.INCOMPLETE, FillSyncResultStatus.UNKNOWN} else "STOP",
    }


def _record_result_alert(result: FillSyncResult, event_type: str) -> None:
    alert_id = record_fill_sync_alert(result, event_type)
    if alert_id is not None and alert_id not in result.alert_event_ids:
        result.alert_event_ids = [*result.alert_event_ids, alert_id]
        result.save(update_fields=["alert_event_ids", "updated_at_utc"])


def _event_type_for_result(result: FillSyncResult) -> str:
    if result.status == FillSyncResultStatus.SYNCED:
        return "fill_sync_synced"
    if result.status == FillSyncResultStatus.SYNCED_EMPTY:
        return "fill_sync_synced_empty"
    if result.reason_code in {"trade_fill_payload_conflict", "trade_fill_conflict"}:
        return "fill_sync_conflict"
    if result.reason_code in {
        "trade_fill_symbol_mismatch",
        "trade_fill_symbol_missing",
        "trade_fill_order_id_mismatch",
        "trade_fill_order_id_missing",
        "market_identity_mismatch",
    }:
        return "fill_sync_identity_mismatch"
    return f"fill_sync_{result.status}"


def _in_progress_result(result: FillSyncResult) -> ServiceResult:
    return ServiceResult(
        ResultStatus.NO_ACTION,
        "fill_sync_in_progress",
        "本次成交同步已经开始但尚未完成，不重复调用 Gateway。",
        result.trace_id,
        result.trigger_source,
        {**_result_data(result), "flow_action": "WAIT"},
    )


def _result_without_sync(reason_code: str, message: str, trace_id: str, trigger_source: str, *, failed: bool = False) -> ServiceResult:
    return ServiceResult(
        ResultStatus.FAILED if failed else ResultStatus.BLOCKED,
        reason_code,
        message,
        trace_id,
        trigger_source,
        {"fill_sync_result_id": None, "allows_active_lock_finalization": False, "flow_action": "STOP"},
    )


def _request_error(**values: Any) -> str:
    if not isinstance(values["order_submission_attempt_id"], int) or values["order_submission_attempt_id"] <= 0:
        return "order_submission_attempt_id_invalid"
    if not isinstance(values["terminal_order_status_sync_record_id"], int) or values["terminal_order_status_sync_record_id"] <= 0:
        return "terminal_order_status_sync_record_id_invalid"
    key = values["business_request_key"]
    if not isinstance(key, str) or not key.strip() or len(key) > MAX_KEY_LENGTH:
        return "business_request_key_invalid"
    if not values["trace_id"] or not values["trigger_source"]:
        return "trace_context_missing"
    if len(values["trace_id"]) > MAX_TRACE_FIELD_LENGTH or len(values["trigger_source"]) > MAX_TRACE_FIELD_LENGTH:
        return "trace_context_missing"
    return ""


def _status_for_pre_error(reason_code: str) -> str:
    if not reason_code:
        return ""
    if reason_code == "fill_sync_recovery_out_of_window":
        return FillSyncResultStatus.RECOVERY_SKIPPED_OUT_OF_WINDOW
    if reason_code in {
        "missing_exchange_order_id",
        "sync_time_before_order_submission_fact",
        "sync_time_before_terminal_status_fact",
        "sync_time_before_existing_fill_sync_fact",
    }:
        return FillSyncResultStatus.FAILED_BEFORE_QUERY
    return FillSyncResultStatus.BLOCKED_BEFORE_QUERY


def _reason_message(reason_code: str) -> str:
    labels = {
        "fill_sync_disabled": "FillSync 部署级开关未开启。",
        "terminal_record_attempt_mismatch": "终态订单状态记录不属于当前 OrderSubmissionAttempt。",
        "terminal_record_not_found_outcome": "终态订单状态记录未确认 found，不能查询成交。",
        "terminal_record_not_terminal": "订单状态尚未确认终态，不能查询成交。",
        "unsupported_terminal_exchange_status": "订单终态不在成交同步允许名单内。",
        "market_identity_mismatch": "成交同步冻结市场身份与订单状态记录不一致。",
        "missing_exchange_order_id": "缺少交易所订单 ID，无法按订单精确查询成交。",
        "sync_time_before_order_submission_fact": "成交同步时间早于订单提交尝试完成事实时间。",
        "sync_time_before_terminal_status_fact": "成交同步时间早于终态订单状态事实时间。",
        "sync_time_before_existing_fill_sync_fact": "成交同步时间早于已有成交同步完成事实时间。",
        "active_lock_not_active_for_recovery": "ActiveLock 未处于 active 状态，不进入成交受控补同步。",
        "fill_summary_already_complete": "订单成交汇总已经完整，不重复发起成交补同步。",
        "fill_sync_recovery_out_of_window": "成交受控补同步已超过恢复窗口，不请求 Binance。",
        "fill_query_failed_before_send": "Gateway 确认成交查询未发出。",
        "fill_query_unknown": "无法确认 Binance 成交查询结果。",
        "fill_query_response_schema_error": "成交查询响应结构不符合约定。",
        "pagination_cursor_loop": "成交查询分页游标循环。",
        "pagination_not_complete_without_cursor": "成交查询分页未完成且没有下一页游标。",
        "pagination_max_pages_reached": "成交查询达到最大分页数仍未完成。",
        "trade_fill_symbol_mismatch": "返回成交的交易品种与订单不一致。",
        "trade_fill_symbol_missing": "返回成交缺少交易品种，无法校验身份。",
        "trade_fill_order_id_mismatch": "返回成交的订单 ID 与目标订单不一致。",
        "trade_fill_order_id_missing": "返回成交缺少订单 ID，无法校验身份。",
        "trade_fill_id_missing": "返回成交缺少交易所成交 ID。",
        "trade_fill_price_invalid": "返回成交价格非法。",
        "trade_fill_quantity_invalid": "返回成交数量非法。",
        "coin_m_contract_size_missing": "COIN-M 成交同步缺少有效合约面值，不能计算名义成交额。",
        "coin_m_base_quantity_missing": "COIN-M 成交同步缺少有效 base 成交数量，不能计算成交均价。",
        "coin_m_notional_calculation_failed": "COIN-M 成交同步无法根据合约张数和合约面值计算名义成交额。",
        "trade_fill_time_invalid": "返回成交时间非法。",
        "trade_fill_side_invalid": "返回成交方向非法。",
        "trade_fill_position_side_invalid": "返回持仓方向非法。",
        "trade_fill_payload_conflict": "同一交易所成交 ID 返回了不同核心内容。",
        "filled_order_has_no_fills": "交易所订单状态为 FILLED，但成交查询没有返回成交。",
        "terminal_quantity_missing_for_empty_fills": "无成交场景缺少明确的终态零成交数量证据。",
        "filled_quantity_mismatch": "成交汇总数量与终态订单累计成交数量不一致。",
        "pagination_incomplete": "成交查询分页不完整。",
        "fill_sync_synced": "成交同步完成。",
        "fill_sync_synced_empty": "成交同步完成，交易所确认该终态订单无成交。",
    }
    return labels.get(reason_code, reason_code)


def _exchange_order_id(attempt: OrderSubmissionAttempt, terminal: OrderStatusSyncRecord) -> str:
    return str(terminal.exchange_order_id_returned or terminal.exchange_order_id_requested or attempt.exchange_order_id or "").strip()


def _terminal_quantity(terminal: OrderStatusSyncRecord) -> Decimal | None:
    payload = terminal.sanitized_response or {}
    return _optional_decimal(
        payload.get("executedQty")
        or payload.get("executed_qty")
        or payload.get("cumQty")
        or payload.get("cum_qty")
        or payload.get("executed_quantity")
    )


def _terminal_quote_quantity(terminal: OrderStatusSyncRecord) -> Decimal | None:
    payload = terminal.sanitized_response or {}
    return _optional_decimal(
        payload.get("cumQuote")
        or payload.get("cum_quote")
        or payload.get("cumQuoteQty")
        or payload.get("cum_quote_qty")
        or payload.get("cumulativeQuoteQty")
    )


def _config_snapshot() -> dict[str, Any]:
    return {
        "fill_sync_enabled": bool(getattr(settings, "FILL_SYNC_ENABLED", False)),
        "fill_sync_page_size": int(getattr(settings, "FILL_SYNC_PAGE_SIZE", 100)),
        "fill_sync_max_pages": int(getattr(settings, "FILL_SYNC_MAX_PAGES", 10)),
        "fill_sync_recovery_window_seconds": int(getattr(settings, "FILL_SYNC_RECOVERY_WINDOW_SECONDS", 86400)),
    }


def _input_hash(attempt: OrderSubmissionAttempt, terminal: OrderStatusSyncRecord) -> str:
    return fill_sync_input_hash(
        {
            "order_submission_attempt_id": attempt.id,
            "terminal_order_status_sync_record_id": terminal.id,
            "exchange": attempt.exchange,
            "market_type": attempt.market_type,
            "account_domain": attempt.account_domain,
            "symbol": attempt.symbol,
            "client_order_id": attempt.client_order_id,
            "exchange_order_id": _exchange_order_id(attempt, terminal),
            "terminal_exchange_status": terminal.exchange_status,
            "terminal_response_hash": terminal.response_hash,
        }
    )


def _result_key(attempt_id: int, terminal_id: int, business_request_key: str) -> str:
    return fill_sync_result_key_hash(
        {
            "order_submission_attempt_id": attempt_id,
            "terminal_order_status_sync_record_id": terminal_id,
            "business_request_key": business_request_key,
        }
    )[:MAX_KEY_LENGTH]


def _page_evidence(page_sequence: int, page_cursor: str | None, result: BinanceGatewayResult) -> dict[str, Any]:
    return {
        "page_sequence": page_sequence,
        "page_cursor": page_cursor or "",
        "success": result.success,
        "request_sent": result.request_sent,
        "response_received": result.response_received,
        "attempt_count": result.attempt_count,
        "http_status": result.http_status,
        "error_category": result.error_category,
    }


def _sum_by_asset(fills: list[TradeFill], *, value_attr: str, asset_attr: str) -> dict[str, str]:
    totals: dict[str, Decimal] = {}
    for fill in fills:
        value = getattr(fill, value_attr) or ZERO
        asset = str(getattr(fill, asset_attr) or "").upper()
        if not asset:
            continue
        totals[asset] = totals.get(asset, ZERO) + value
    return {asset: _decimal_str(total) for asset, total in sorted(totals.items())}


def _coin_contract_size(result: FillSyncResult) -> Decimal | None:
    if result.market_type != MARKET_TYPE_COIN_M:
        return None
    contract_size = result.prepared_order_intent.symbol_rule_snapshot.contract_size
    if contract_size is None or contract_size <= ZERO:
        return None
    return contract_size


def _filled_notional_usd(
    market_type: str,
    fills: list[TradeFill],
    total_quote_quantity: Decimal,
) -> Decimal | None:
    if market_type == MARKET_TYPE_USDS_M:
        return total_quote_quantity
    if market_type == MARKET_TYPE_COIN_M:
        total = ZERO
        for fill in fills:
            if fill.contract_size is None or fill.contract_size <= ZERO:
                return None
            total += fill.quantity * fill.contract_size
        return total
    return None


def _average_price(
    market_type: str,
    total_quantity: Decimal,
    total_quote_quantity: Decimal,
    total_base_quantity: Decimal,
    filled_notional_usd: Decimal | None,
) -> Decimal | None:
    if market_type == MARKET_TYPE_USDS_M and total_quantity > ZERO:
        return total_quote_quantity / total_quantity
    if market_type == MARKET_TYPE_COIN_M and total_base_quantity > ZERO and filled_notional_usd is not None:
        return filled_notional_usd / total_base_quantity
    return None


def _quantity_reconciled(terminal_quantity: Decimal | None, total_quantity: Decimal) -> bool:
    if terminal_quantity is None:
        return False
    return terminal_quantity == total_quantity


def _quote_reconciled(terminal_quote_quantity: Decimal | None, total_quote_quantity: Decimal) -> bool:
    if terminal_quote_quantity is None:
        return False
    return terminal_quote_quantity == total_quote_quantity


def _realized_pnl_asset(result: FillSyncResult, fill: dict[str, Any]) -> str:
    explicit = str(fill.get("realizedPnlAsset") or fill.get("realized_pnl_asset") or "")
    if explicit:
        return explicit
    if result.market_type == MARKET_TYPE_USDS_M:
        return "USDT"
    return str(fill.get("marginAsset") or fill.get("baseAsset") or "")


def _decimal(value: Any) -> Decimal:
    parsed = _optional_decimal(value)
    return parsed if parsed is not None else ZERO


def _optional_decimal(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    if not parsed.is_finite():
        return None
    return parsed


def _optional_bool(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    lowered = str(value).strip().lower()
    if lowered in {"true", "1", "yes"}:
        return True
    if lowered in {"false", "0", "no"}:
        return False
    return None


def _time_from_millis(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    try:
        return datetime.fromtimestamp(int(value) / 1000, tz=UTC)
    except (TypeError, ValueError, OSError):
        return None


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _decimal_str(value: Decimal | None) -> str:
    if value is None:
        return ""
    return format(value.normalize(), "f")
