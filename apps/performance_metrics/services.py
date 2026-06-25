"""PerformanceMetrics 模块：后置账户绩效复盘计算服务。

负责：扫描相邻自动编排账户边界，读取已落库账户/持仓/成交事实，写入绩效复盘结果。
不负责：请求 Binance、查询订单状态、同步成交、修改订单链路、释放锁、生成交易信号。
读写数据库：读取已落库事实，写 OrchestrationRunPerformance、AuditRecord、AlertEvent。
访问 Redis：不涉及。
访问外部服务：不涉及。
发送 Hermes：不涉及。
调用大模型：不涉及。
涉及交易执行：不涉及。
允许真实交易：不允许。
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.alerts.models import AlertSeverity
from apps.alerts.services import record_alert_event
from apps.audit.services import record_audit
from apps.binance_account_sync.models import (
    BinanceAccountSnapshot,
    BinancePositionSnapshot,
    BinanceSyncPurpose,
    BinanceSyncRun,
    BinanceSyncStatus,
)
from apps.execution.models import OrderSubmissionAttempt
from apps.fill_sync.models import TradeFill
from apps.foundation.results import ResultStatus, ServiceResult
from apps.orchestration.models import (
    OrchestrationBusinessObjectLink,
    OrchestrationRun,
    OrchestrationRunStatus,
    OrchestrationTriggerMode,
)
from apps.order_status_sync.models import OrderStatusSyncRecord
from apps.runtime_guard.models import RuntimeGuardIssue

from .models import OrchestrationRunPerformance, PerformanceCalculationStatus


FORMULA_VERSION = "p0_position_quantity_delta_v1"
TRIGGER_SOURCE_BACKFILL = "ops_console_performance_backfill"


@dataclass(frozen=True)
class BoundaryPair:
    start_run: OrchestrationRun
    end_run: OrchestrationRun


@dataclass(frozen=True)
class BoundaryFacts:
    run: OrchestrationRun
    sync_run: BinanceSyncRun | None
    account_snapshot: BinanceAccountSnapshot | None
    position_snapshot: BinancePositionSnapshot | None
    reason_code: str
    reason_message: str


def preview_missing_closed_period_performance(*, reference_time_utc: datetime | None = None) -> dict[str, Any]:
    now = _ensure_utc(reference_time_utc or timezone.now())
    items: list[dict[str, Any]] = []
    scanned = 0
    existing = 0
    calculable = 0
    blocked_by_reason: dict[str, int] = {}
    for pair in _closed_boundary_pairs(now):
        scanned += 1
        item = _preview_pair(pair)
        if item["already_exists"]:
            existing += 1
        elif item["calculable"]:
            calculable += 1
        else:
            reason = str(item["reason_code"])
            blocked_by_reason[reason] = blocked_by_reason.get(reason, 0) + 1
        items.append(item)
    missing = max(0, scanned - existing)
    return {
        "scanned_period_count": scanned,
        "existing_period_count": existing,
        "missing_period_count": missing,
        "calculable_missing_period_count": calculable,
        "not_calculable_reason_counts": blocked_by_reason,
        "items": items[:100],
    }


def backfill_missing_closed_period_performance(
    *,
    operator_id: str,
    reason: str,
    trace_id: str,
    reference_time_utc: datetime | None = None,
) -> ServiceResult:
    now = _ensure_utc(reference_time_utc or timezone.now())
    if not reason.strip():
        return ServiceResult(
            status=ResultStatus.BLOCKED,
            reason_code="performance_backfill_reason_required",
            message="绩效补算需要记录人工原因。",
            trace_id=trace_id,
            trigger_source=TRIGGER_SOURCE_BACKFILL,
        )

    calculated = 0
    existing = 0
    skipped = 0
    failed = 0
    written_ids: list[int] = []
    skipped_items: list[dict[str, Any]] = []
    for pair in _closed_boundary_pairs(now):
        try:
            result = calculate_period_performance(
                start_orchestration_run_id=pair.start_run.id,
                end_orchestration_run_id=pair.end_run.id,
                operator_id=operator_id,
                trace_id=trace_id,
                trigger_source=TRIGGER_SOURCE_BACKFILL,
            )
        except Exception as exc:  # noqa: BLE001 - 补算不能让单个周期阻断整批扫描。
            failed += 1
            skipped_items.append(
                {
                    "start_orchestration_run_id": pair.start_run.id,
                    "end_orchestration_run_id": pair.end_run.id,
                    "reason_code": "performance_period_failed",
                    "message": str(exc)[:300],
                }
            )
            continue
        if result.status == ResultStatus.SUCCEEDED:
            calculated += 1
            if performance_id := result.data.get("performance_id"):
                written_ids.append(int(performance_id))
        elif result.reason_code == "performance_period_already_exists":
            existing += 1
        else:
            skipped += 1
            skipped_items.append(result.data)

    audit = record_audit(
        operator_id=operator_id,
        operation_type="performance_metrics_backfill",
        target_object_type="OrchestrationRunPerformance",
        target_object_id="",
        before_state_summary={},
        after_state_summary={
            "calculated_count": calculated,
            "existing_count": existing,
            "skipped_count": skipped,
            "failed_count": failed,
            "written_ids": written_ids[:50],
        },
        reason=reason.strip()[:500],
        evidence={"skipped_items": skipped_items[:50]},
        result="succeeded" if failed == 0 else "partial_failed",
        trace_id=trace_id,
        trigger_source=TRIGGER_SOURCE_BACKFILL,
    )
    return ServiceResult(
        status=ResultStatus.SUCCEEDED if failed == 0 else ResultStatus.UNKNOWN,
        reason_code="performance_backfill_completed" if failed == 0 else "performance_backfill_partial_failed",
        message="绩效一键补算已完成。",
        trace_id=trace_id,
        trigger_source=TRIGGER_SOURCE_BACKFILL,
        data={
            "audit_record_id": audit.id,
            "calculated_count": calculated,
            "existing_count": existing,
            "skipped_count": skipped,
            "failed_count": failed,
            "written_ids": written_ids,
            "skipped_items": skipped_items[:100],
        },
    )


def calculate_period_performance(
    *,
    start_orchestration_run_id: int,
    end_orchestration_run_id: int,
    operator_id: str = "",
    trace_id: str = "",
    trigger_source: str = TRIGGER_SOURCE_BACKFILL,
) -> ServiceResult:
    start_run = OrchestrationRun.objects.get(id=start_orchestration_run_id)
    end_run = OrchestrationRun.objects.get(id=end_orchestration_run_id)
    start_facts = _boundary_facts(start_run, None, None, None)
    end_facts = _boundary_facts(end_run, None, None, None)
    if start_facts.sync_run is None or end_facts.sync_run is None:
        reason_code = start_facts.reason_code if start_facts.sync_run is None else end_facts.reason_code
        return _blocked_result(
            reason_code=reason_code,
            message="相邻编排边界缺少 trade_preparation 账户快照，不能补算绩效。",
            trace_id=trace_id,
            trigger_source=trigger_source,
            start_run=start_run,
            end_run=end_run,
        )

    if _identity_mismatch(start_facts.sync_run, end_facts.sync_run):
        return _blocked_result(
            reason_code="performance_market_identity_mismatch",
            message="相邻边界的市场、账户或交易品种不一致，不能混算绩效。",
            trace_id=trace_id,
            trigger_source=trigger_source,
            start_run=start_run,
            end_run=end_run,
        )

    market_type = start_facts.sync_run.market_type
    account_domain = start_facts.sync_run.account_domain
    symbol = _sync_symbol(start_facts.sync_run)
    existing = OrchestrationRunPerformance.objects.filter(
        start_orchestration_run=start_run,
        end_orchestration_run=end_run,
        market_type=market_type,
        account_domain=account_domain,
        symbol=symbol,
    ).first()
    if existing is not None:
        return ServiceResult(
            status=ResultStatus.NO_ACTION,
            reason_code="performance_period_already_exists",
            message="该相邻编排周期已经存在绩效复盘结果。",
            trace_id=trace_id,
            trigger_source=trigger_source,
            data={"performance_id": existing.id},
        )

    now = timezone.now()
    missing_reason = _missing_boundary_reason(start_facts, end_facts)
    if missing_reason:
        performance = _create_insufficient_record(
            start_facts=start_facts,
            end_facts=end_facts,
            reason_code=missing_reason,
            trace_id=trace_id,
            trigger_source=trigger_source,
            operator_id=operator_id,
            calculated_at_utc=now,
        )
        _record_performance_alert(performance)
        return ServiceResult(
            status=ResultStatus.SKIPPED,
            reason_code=missing_reason,
            message="相邻边界事实不完整，已记录不可计算结果。",
            trace_id=trace_id,
            trigger_source=trigger_source,
            data={"performance_id": performance.id, "start_orchestration_run_id": start_run.id, "end_orchestration_run_id": end_run.id},
        )

    performance = _create_calculated_record(
        start_facts=start_facts,
        end_facts=end_facts,
        trace_id=trace_id,
        trigger_source=trigger_source,
        operator_id=operator_id,
        calculated_at_utc=now,
    )
    _record_performance_alert(performance)
    return ServiceResult(
        status=ResultStatus.SUCCEEDED,
        reason_code="performance_period_calculated",
        message="相邻编排周期绩效复盘已计算。",
        trace_id=trace_id,
        trigger_source=trigger_source,
        data={"performance_id": performance.id, "start_orchestration_run_id": start_run.id, "end_orchestration_run_id": end_run.id},
    )


def _closed_boundary_pairs(reference_time_utc: datetime) -> list[BoundaryPair]:
    runs = list(
        OrchestrationRun.objects.filter(
            trigger_mode=OrchestrationTriggerMode.AUTOMATIC,
            status__in=_CLOSED_RUN_STATUSES,
            scheduled_for_utc__lte=reference_time_utc,
        ).order_by("scheduled_for_utc", "id")
    )
    return [BoundaryPair(start_run=runs[index], end_run=runs[index + 1]) for index in range(max(0, len(runs) - 1))]


def _preview_pair(pair: BoundaryPair) -> dict[str, Any]:
    start_facts = _boundary_facts(pair.start_run, None, None, None)
    end_facts = _boundary_facts(pair.end_run, None, None, None)
    base = {
        "start_orchestration_run_id": pair.start_run.id,
        "end_orchestration_run_id": pair.end_run.id,
        "period_start_utc": _dt(_period_time(pair.start_run, start_facts.sync_run)),
        "period_end_utc": _dt(_period_time(pair.end_run, end_facts.sync_run)),
        "already_exists": False,
        "calculable": False,
        "reason_code": "",
    }
    if start_facts.sync_run is None:
        return base | {"reason_code": start_facts.reason_code}
    if end_facts.sync_run is None:
        return base | {"reason_code": end_facts.reason_code}
    market_type = start_facts.sync_run.market_type
    account_domain = start_facts.sync_run.account_domain
    symbol = _sync_symbol(start_facts.sync_run)
    exists = OrchestrationRunPerformance.objects.filter(
        start_orchestration_run=pair.start_run,
        end_orchestration_run=pair.end_run,
        market_type=market_type,
        account_domain=account_domain,
        symbol=symbol,
    ).exists()
    if exists:
        return base | {
            "market_type": market_type,
            "account_domain": account_domain,
            "symbol": symbol,
            "already_exists": True,
            "reason_code": "performance_period_already_exists",
        }
    if _identity_mismatch(start_facts.sync_run, end_facts.sync_run):
        return base | {
            "market_type": market_type,
            "account_domain": account_domain,
            "symbol": symbol,
            "reason_code": "performance_market_identity_mismatch",
        }
    missing_reason = _missing_boundary_reason(start_facts, end_facts)
    return base | {
        "market_type": market_type,
        "account_domain": account_domain,
        "symbol": symbol,
        "calculable": not bool(missing_reason),
        "reason_code": missing_reason or "performance_period_calculable",
    }


def _boundary_facts(
    run: OrchestrationRun,
    sync_run: BinanceSyncRun | None,
    account_snapshot: BinanceAccountSnapshot | None,
    position_snapshot: BinancePositionSnapshot | None,
) -> BoundaryFacts:
    sync = sync_run or _trade_preparation_sync_for_run(run)
    if sync is None:
        return BoundaryFacts(run, None, None, None, "performance_trade_preparation_sync_missing", "编排边界没有绑定成功的 trade_preparation 账户同步。")
    account = account_snapshot or BinanceAccountSnapshot.objects.filter(sync_run=sync).first()
    symbol = _sync_symbol(sync)
    position = position_snapshot or (
        BinancePositionSnapshot.objects.filter(sync_run=sync, symbol=symbol).order_by("normalized_position_side", "id").first()
    )
    return BoundaryFacts(run, sync, account, position, "ok", "")


def _trade_preparation_sync_for_run(run: OrchestrationRun) -> BinanceSyncRun | None:
    object_ids = [
        int(value)
        for value in OrchestrationBusinessObjectLink.objects.filter(
            orchestration_run=run,
            object_type="BinanceSyncRun",
        ).values_list("object_id", flat=True)
        if str(value).isdigit()
    ]
    if not object_ids:
        return None
    return (
        BinanceSyncRun.objects.filter(
            id__in=object_ids,
            sync_purpose=BinanceSyncPurpose.TRADE_PREPARATION,
            status=BinanceSyncStatus.SUCCEEDED,
        )
        .order_by("-started_at_utc", "-id")
        .first()
    )


def _identity_mismatch(start_sync: BinanceSyncRun, end_sync: BinanceSyncRun) -> bool:
    return (
        start_sync.exchange != end_sync.exchange
        or start_sync.market_type != end_sync.market_type
        or start_sync.account_domain != end_sync.account_domain
        or _sync_symbol(start_sync) != _sync_symbol(end_sync)
    )


def _missing_boundary_reason(start_facts: BoundaryFacts, end_facts: BoundaryFacts) -> str:
    if start_facts.account_snapshot is None:
        return "performance_start_account_snapshot_missing"
    if end_facts.account_snapshot is None:
        return "performance_end_account_snapshot_missing"
    if start_facts.position_snapshot is None:
        return "performance_start_position_snapshot_missing"
    if end_facts.position_snapshot is None:
        return "performance_end_position_snapshot_missing"
    if start_facts.position_snapshot.mark_price is None:
        return "performance_start_mark_price_missing"
    if end_facts.position_snapshot.mark_price is None:
        return "performance_end_mark_price_missing"
    return ""


def _create_insufficient_record(
    *,
    start_facts: BoundaryFacts,
    end_facts: BoundaryFacts,
    reason_code: str,
    trace_id: str,
    trigger_source: str,
    operator_id: str,
    calculated_at_utc: datetime,
) -> OrchestrationRunPerformance:
    assert start_facts.sync_run is not None
    assert end_facts.sync_run is not None
    payload = _base_payload(
        start_facts=start_facts,
        end_facts=end_facts,
        trace_id=trace_id,
        trigger_source=trigger_source,
        operator_id=operator_id,
        calculated_at_utc=calculated_at_utc,
    )
    payload.update(
        {
            "calculation_status": PerformanceCalculationStatus.INSUFFICIENT_SNAPSHOT,
            "reason_code": reason_code,
            "reason_message": "相邻账户边界事实不完整，不能计算周期绩效。",
            "input_refs_hash": _stable_hash(_input_refs(start_facts, end_facts, [])),
            "result_hash": _stable_hash({"status": PerformanceCalculationStatus.INSUFFICIENT_SNAPSHOT, "reason_code": reason_code}),
        }
    )
    with transaction.atomic():
        return OrchestrationRunPerformance.objects.create(**payload)


def _create_calculated_record(
    *,
    start_facts: BoundaryFacts,
    end_facts: BoundaryFacts,
    trace_id: str,
    trigger_source: str,
    operator_id: str,
    calculated_at_utc: datetime,
) -> OrchestrationRunPerformance:
    assert start_facts.sync_run is not None
    assert end_facts.sync_run is not None
    assert start_facts.position_snapshot is not None
    assert end_facts.position_snapshot is not None
    period_start = _period_time(start_facts.run, start_facts.sync_run)
    period_end = _period_time(end_facts.run, end_facts.sync_run)
    linked_attempt_ids = _linked_attempt_ids(start_facts.run)
    fills = _period_fills(
        attempt_ids=linked_attempt_ids,
        period_start_utc=period_start,
        period_end_utc=period_end,
        market_type=start_facts.sync_run.market_type,
        account_domain=start_facts.sync_run.account_domain,
        symbol=_sync_symbol(start_facts.sync_run),
    )
    net_fill_quantity = _net_fill_quantity(fills)
    start_quantity = _decimal_or_zero(start_facts.position_snapshot.position_amount)
    end_quantity = _decimal_or_zero(end_facts.position_snapshot.position_amount)
    cycle_floating_pnl = end_quantity - start_quantity - net_fill_quantity
    cycle_pct = cycle_floating_pnl / abs(start_quantity) if start_quantity != 0 else None
    realized = _sum_decimal(fill.realized_pnl for fill in fills)
    commission = _sum_decimal(fill.commission for fill in fills)
    context = _context_flags(start_facts.run, linked_attempt_ids)
    latest_attempt = OrderSubmissionAttempt.objects.filter(id__in=linked_attempt_ids).order_by("-created_at_utc", "-id").first()
    latest_status = (
        OrderStatusSyncRecord.objects.filter(order_submission_attempt_id__in=linked_attempt_ids, is_terminal_status=True)
        .order_by("-created_at_utc", "-id")
        .first()
    )
    payload = _base_payload(
        start_facts=start_facts,
        end_facts=end_facts,
        trace_id=trace_id,
        trigger_source=trigger_source,
        operator_id=operator_id,
        calculated_at_utc=calculated_at_utc,
    )
    payload.update(
        {
            "start_position_quantity": start_quantity,
            "end_position_quantity": end_quantity,
            "net_fill_quantity": net_fill_quantity,
            "cycle_floating_pnl": cycle_floating_pnl,
            "cycle_floating_pnl_pct": cycle_pct,
            "order_realized_pnl": realized,
            "order_commission": commission,
            "order_net_realized_pnl": realized - commission,
            "calculation_status": PerformanceCalculationStatus.CALCULATED,
            "reason_code": "performance_period_calculated",
            "reason_message": "相邻四小时账户边界绩效复盘已计算。",
            "input_refs_hash": _stable_hash(_input_refs(start_facts, end_facts, fills)),
            "result_hash": _stable_hash(
                {
                    "formula_version": FORMULA_VERSION,
                    "start_quantity": start_quantity,
                    "end_quantity": end_quantity,
                    "net_fill_quantity": net_fill_quantity,
                    "cycle_floating_pnl": cycle_floating_pnl,
                    "cycle_floating_pnl_pct": cycle_pct,
                    "realized": realized,
                    "commission": commission,
                }
            ),
            "has_decision_snapshot": context["has_decision_snapshot"],
            "has_order_plan": context["has_order_plan"],
            "has_candidate_order_intent": context["has_candidate_order_intent"],
            "has_risk_check": context["has_risk_check"],
            "has_approved_order_intent": context["has_approved_order_intent"],
            "has_execution_preparation": context["has_execution_preparation"],
            "has_order_submission": context["has_order_submission"],
            "has_terminal_order_status": latest_status is not None or context["has_terminal_order_status"],
            "has_fill": bool(fills) or context["has_fill"],
            "order_submission_status": latest_attempt.status if latest_attempt else "",
            "terminal_exchange_order_status": latest_status.exchange_status if latest_status else "",
            "related_alert_count": _related_alert_count(start_facts.run, linked_attempt_ids),
            "related_runtime_guard_issue_count": _related_guard_issue_count(start_facts.run, linked_attempt_ids),
        }
    )
    with transaction.atomic():
        return OrchestrationRunPerformance.objects.create(**payload)


def _base_payload(
    *,
    start_facts: BoundaryFacts,
    end_facts: BoundaryFacts,
    trace_id: str,
    trigger_source: str,
    operator_id: str,
    calculated_at_utc: datetime,
) -> dict[str, Any]:
    assert start_facts.sync_run is not None
    assert end_facts.sync_run is not None
    return {
        "start_orchestration_run": start_facts.run,
        "end_orchestration_run": end_facts.run,
        "period_start_utc": _period_time(start_facts.run, start_facts.sync_run),
        "period_end_utc": _period_time(end_facts.run, end_facts.sync_run),
        "exchange": start_facts.sync_run.exchange,
        "market_type": start_facts.sync_run.market_type,
        "account_domain": start_facts.sync_run.account_domain,
        "symbol": _sync_symbol(start_facts.sync_run),
        "start_binance_sync_run": start_facts.sync_run,
        "end_binance_sync_run": end_facts.sync_run,
        "start_account_snapshot": start_facts.account_snapshot,
        "end_account_snapshot": end_facts.account_snapshot,
        "start_position_snapshot": start_facts.position_snapshot,
        "end_position_snapshot": end_facts.position_snapshot,
        "formula_version": FORMULA_VERSION,
        "start_mark_price": getattr(start_facts.position_snapshot, "mark_price", None),
        "end_mark_price": getattr(end_facts.position_snapshot, "mark_price", None),
        "start_unrealized_pnl": getattr(start_facts.position_snapshot, "unrealized_pnl", None),
        "end_unrealized_pnl": getattr(end_facts.position_snapshot, "unrealized_pnl", None),
        "start_notional": getattr(start_facts.position_snapshot, "notional", None),
        "end_notional": getattr(end_facts.position_snapshot, "notional", None),
        "trace_id": trace_id or start_facts.run.trace_id or end_facts.run.trace_id,
        "trigger_source": trigger_source,
        "operator_id": operator_id,
        "calculated_at_utc": calculated_at_utc,
    }


def _linked_attempt_ids(run: OrchestrationRun) -> list[int]:
    values = OrchestrationBusinessObjectLink.objects.filter(
        orchestration_run=run,
        object_type="OrderSubmissionAttempt",
    ).values_list("object_id", flat=True)
    return sorted({int(value) for value in values if str(value).isdigit()})


def _period_fills(
    *,
    attempt_ids: list[int],
    period_start_utc: datetime,
    period_end_utc: datetime,
    market_type: str,
    account_domain: str,
    symbol: str,
) -> list[TradeFill]:
    if not attempt_ids:
        return []
    return list(
        TradeFill.objects.filter(
            order_submission_attempt_id__in=attempt_ids,
            market_type=market_type,
            account_domain=account_domain,
            symbol=symbol,
            trade_time_utc__gte=period_start_utc,
            trade_time_utc__lt=period_end_utc,
        ).order_by("trade_time_utc", "id")
    )


def _net_fill_quantity(fills: list[TradeFill]) -> Decimal:
    total = Decimal("0")
    for fill in fills:
        quantity = _decimal_or_zero(fill.quantity)
        side = fill.side.upper()
        if side == "BUY":
            total += quantity
        elif side == "SELL":
            total -= quantity
    return total


def _context_flags(run: OrchestrationRun, attempt_ids: list[int]) -> dict[str, bool]:
    object_types = set(
        OrchestrationBusinessObjectLink.objects.filter(orchestration_run=run).values_list("object_type", flat=True)
    )
    return {
        "has_decision_snapshot": "DecisionSnapshot" in object_types,
        "has_order_plan": "OrderPlan" in object_types,
        "has_candidate_order_intent": "CandidateOrderIntent" in object_types,
        "has_risk_check": "RiskCheckResult" in object_types,
        "has_approved_order_intent": "ApprovedOrderIntent" in object_types,
        "has_execution_preparation": "PreparedOrderIntent" in object_types or "ExecutionPreparationResult" in object_types,
        "has_order_submission": "OrderSubmissionAttempt" in object_types or bool(attempt_ids),
        "has_terminal_order_status": "OrderStatusSyncRecord" in object_types,
        "has_fill": bool(object_types & {"TradeFill", "FillSyncResult", "OrderFillSummary"}),
    }


def _related_alert_count(run: OrchestrationRun, attempt_ids: list[int]) -> int:
    query = Q(related_object_type="OrchestrationRun", related_object_id=str(run.id))
    if run.trace_id:
        query |= Q(trace_id=run.trace_id)
    if attempt_ids:
        query |= Q(related_object_type="OrderSubmissionAttempt", related_object_id__in=[str(value) for value in attempt_ids])
    from apps.alerts.models import AlertEvent

    return AlertEvent.objects.filter(query).count()


def _related_guard_issue_count(run: OrchestrationRun, attempt_ids: list[int]) -> int:
    query = Q(related_object_type="OrchestrationRun", related_object_id=str(run.id))
    if run.trace_id:
        query |= Q(related_trace_id=run.trace_id)
    if attempt_ids:
        query |= Q(related_object_type="OrderSubmissionAttempt", related_object_id__in=[str(value) for value in attempt_ids])
    return RuntimeGuardIssue.objects.filter(query).count()


def _record_performance_alert(performance: OrchestrationRunPerformance) -> None:
    severity = AlertSeverity.INFO if performance.calculation_status == PerformanceCalculationStatus.CALCULATED else AlertSeverity.WARNING
    record_alert_event(
        event_key=_stable_hash(
            {
                "kind": "orchestration_run_performance",
                "performance_id": performance.id,
                "status": performance.calculation_status,
                "result_hash": performance.result_hash,
            }
        ),
        source_module="performance_metrics",
        event_type=f"performance_metrics_{performance.calculation_status}",
        event_category="performance_metrics",
        severity=severity,
        title_zh="绩效复盘结果",
        message_zh=performance.reason_message,
        trace_id=performance.trace_id,
        trigger_source=performance.trigger_source,
        related_object_type="OrchestrationRunPerformance",
        related_object_id=str(performance.id),
        business_status=performance.calculation_status,
        reason_code=performance.reason_code,
        payload_summary={
            "start_orchestration_run_id": performance.start_orchestration_run_id,
            "end_orchestration_run_id": performance.end_orchestration_run_id,
            "market_type": performance.market_type,
            "account_domain": performance.account_domain,
            "symbol": performance.symbol,
            "cycle_floating_pnl": str(performance.cycle_floating_pnl),
        },
        delivery_enabled=False,
    )


def _input_refs(start_facts: BoundaryFacts, end_facts: BoundaryFacts, fills: list[TradeFill]) -> dict[str, Any]:
    return {
        "start_orchestration_run_id": start_facts.run.id,
        "end_orchestration_run_id": end_facts.run.id,
        "start_binance_sync_run_id": getattr(start_facts.sync_run, "id", None),
        "end_binance_sync_run_id": getattr(end_facts.sync_run, "id", None),
        "start_account_snapshot_id": getattr(start_facts.account_snapshot, "id", None),
        "end_account_snapshot_id": getattr(end_facts.account_snapshot, "id", None),
        "start_position_snapshot_id": getattr(start_facts.position_snapshot, "id", None),
        "end_position_snapshot_id": getattr(end_facts.position_snapshot, "id", None),
        "fill_ids": [fill.id for fill in fills],
    }


def _sync_symbol(sync_run: BinanceSyncRun) -> str:
    symbols = sync_run.requested_symbols or []
    return str(symbols[0]) if symbols else ""


def _period_time(run: OrchestrationRun, sync_run: BinanceSyncRun | None) -> datetime:
    value = getattr(sync_run, "as_of_utc", None) or run.scheduled_for_utc
    return _ensure_utc(value)


def _decimal_or_zero(value: Decimal | None) -> Decimal:
    return value if value is not None else Decimal("0")


def _sum_decimal(values: Any) -> Decimal:
    total = Decimal("0")
    for value in values:
        if value is not None:
            total += value
    return total


def _blocked_result(
    *,
    reason_code: str,
    message: str,
    trace_id: str,
    trigger_source: str,
    start_run: OrchestrationRun,
    end_run: OrchestrationRun,
) -> ServiceResult:
    return ServiceResult(
        status=ResultStatus.SKIPPED,
        reason_code=reason_code,
        message=message,
        trace_id=trace_id,
        trigger_source=trigger_source,
        data={"start_orchestration_run_id": start_run.id, "end_orchestration_run_id": end_run.id, "reason_code": reason_code},
    )


def _dt(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _stable_hash(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


_CLOSED_RUN_STATUSES = {
    OrchestrationRunStatus.COMPLETED,
    OrchestrationRunStatus.COMPLETED_NO_ACTION,
    OrchestrationRunStatus.BLOCKED,
    OrchestrationRunStatus.UNKNOWN,
    OrchestrationRunStatus.FAILED,
    OrchestrationRunStatus.STALE_INTERRUPTED,
}
