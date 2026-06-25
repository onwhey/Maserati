"""PerformanceMetrics 模块：后置绩效复盘只读查询。

负责：为后台展示读取 OrchestrationRunPerformance。
不负责：触发补算、请求 Binance、访问 Redis、发送 Hermes、调用大模型或交易执行。
读写数据库：只读数据库。
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from decimal import Decimal
from typing import Any

from django.db.models import QuerySet

from .models import OrchestrationRunPerformance


DEFAULT_LIMIT = 20
MAX_LIMIT = 100


def list_performance_records(params: Mapping[str, Any]) -> dict[str, Any]:
    queryset = OrchestrationRunPerformance.objects.select_related(
        "start_orchestration_run",
        "end_orchestration_run",
        "start_binance_sync_run",
        "end_binance_sync_run",
    ).order_by("-period_end_utc", "-id")
    for field in ("calculation_status", "market_type", "account_domain", "symbol", "reason_code"):
        if value := params.get(field):
            queryset = queryset.filter(**{field: value})
    rows, pagination = _paginated(queryset, params)
    return {"items": [_performance_row(row) for row in rows], "pagination": pagination}


def get_performance_record(performance_id: int) -> dict[str, Any] | None:
    record = (
        OrchestrationRunPerformance.objects.select_related(
            "start_orchestration_run",
            "end_orchestration_run",
            "start_binance_sync_run",
            "end_binance_sync_run",
            "start_account_snapshot",
            "end_account_snapshot",
            "start_position_snapshot",
            "end_position_snapshot",
        )
        .filter(id=performance_id)
        .first()
    )
    if record is None:
        return None
    return _performance_row(record) | {
        "start_account_snapshot_id": record.start_account_snapshot_id,
        "end_account_snapshot_id": record.end_account_snapshot_id,
        "start_position_snapshot_id": record.start_position_snapshot_id,
        "end_position_snapshot_id": record.end_position_snapshot_id,
        "input_refs_hash": record.input_refs_hash,
        "result_hash": record.result_hash,
        "operator_id": record.operator_id,
        "created_at_utc": _clean(record.created_at_utc),
        "updated_at_utc": _clean(record.updated_at_utc),
    }


def latest_performance_summary(limit: int = 5) -> dict[str, Any]:
    rows = list(OrchestrationRunPerformance.objects.order_by("-period_end_utc", "-id")[:limit])
    return {
        "available": True,
        "latest": [_performance_row(row) for row in rows],
        "total_count": OrchestrationRunPerformance.objects.count(),
    }


def _performance_row(record: OrchestrationRunPerformance) -> dict[str, Any]:
    return {
        "id": record.id,
        "start_orchestration_run_id": record.start_orchestration_run_id,
        "end_orchestration_run_id": record.end_orchestration_run_id,
        "period_start_utc": _clean(record.period_start_utc),
        "period_end_utc": _clean(record.period_end_utc),
        "exchange": record.exchange,
        "market_type": record.market_type,
        "account_domain": record.account_domain,
        "symbol": record.symbol,
        "formula_version": record.formula_version,
        "start_position_quantity": _clean(record.start_position_quantity),
        "end_position_quantity": _clean(record.end_position_quantity),
        "net_fill_quantity": _clean(record.net_fill_quantity),
        "cycle_floating_pnl": _clean(record.cycle_floating_pnl),
        "cycle_floating_pnl_pct": _clean(record.cycle_floating_pnl_pct),
        "start_mark_price": _clean(record.start_mark_price),
        "end_mark_price": _clean(record.end_mark_price),
        "order_realized_pnl": _clean(record.order_realized_pnl),
        "order_commission": _clean(record.order_commission),
        "order_net_realized_pnl": _clean(record.order_net_realized_pnl),
        "has_order_submission": record.has_order_submission,
        "has_terminal_order_status": record.has_terminal_order_status,
        "has_fill": record.has_fill,
        "order_submission_status": record.order_submission_status,
        "terminal_exchange_order_status": record.terminal_exchange_order_status,
        "related_alert_count": record.related_alert_count,
        "related_runtime_guard_issue_count": record.related_runtime_guard_issue_count,
        "calculation_status": record.calculation_status,
        "reason_code": record.reason_code,
        "reason_message": record.reason_message,
        "trace_id": record.trace_id,
        "trigger_source": record.trigger_source,
        "calculated_at_utc": _clean(record.calculated_at_utc),
    }


def _paginated(queryset: QuerySet[Any], params: Mapping[str, Any]) -> tuple[list[Any], dict[str, int]]:
    limit = _int_param(params, "limit", default=DEFAULT_LIMIT)
    offset = _int_param(params, "offset", default=0, min_value=0, max_value=10000)
    total = queryset.count()
    rows = list(queryset[offset : offset + limit])
    return rows, {"limit": limit, "offset": offset, "total": total}


def _int_param(params: Mapping[str, Any], name: str, *, default: int, min_value: int = 1, max_value: int = MAX_LIMIT) -> int:
    raw = params.get(name)
    if raw in (None, ""):
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return default
    return max(min_value, min(value, max_value))


def _clean(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    return value
