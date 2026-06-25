"""OpsConsole 模块：只读聚合查询；只读 MySQL，不访问 Redis，不访问外部服务，不发送 Hermes，不调用大模型，不涉及交易执行。"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from decimal import Decimal
from typing import Any

from django.conf import settings
from django.core.exceptions import ObjectDoesNotExist
from django.db.models import Q, QuerySet

from apps.alerts.models import AlertEvent, NotificationDeliveryAttempt, NotificationSuppression
from apps.audit.models import AuditRecord
from apps.binance_account_sync.models import (
    BinanceAccountSnapshot,
    BinanceBalanceSnapshot,
    BinancePositionSnapshot,
    BinanceSymbolRuleSnapshot,
    BinanceSyncPurpose,
    BinanceSyncRun,
)
from apps.binance_gateway.types import normalize_active_market_type
from apps.execution.models import OrderSubmissionAttempt
from apps.fill_sync.models import FillSyncResult, OrderFillSummary, TradeFill
from apps.foundation.redaction import sanitize_mapping, sanitize_value
from apps.orchestration.models import OrchestrationBusinessObjectLink, OrchestrationRun
from apps.orchestration.selectors.detail import orchestration_run_detail
from apps.order_plan.models import ActiveLockStatus, OrderPlanActiveLock
from apps.order_status_sync.models import OrderStatusSyncRecord
from apps.runtime_config.models import RuntimeTradingConfig
from apps.runtime_config.services import get_effective_real_trading_permission
from apps.runtime_guard.models import RuntimeGuardIssue, RuntimeGuardIssueStatus


DEFAULT_LIMIT = 20
MAX_LIMIT = 100


class OpsConsoleObjectNotFound(LookupError):
    pass


def _int_param(params: Mapping[str, Any], name: str, *, default: int, min_value: int = 1, max_value: int = MAX_LIMIT) -> int:
    raw = params.get(name)
    if raw in (None, ""):
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return default
    return max(min_value, min(value, max_value))


def _limit(params: Mapping[str, Any]) -> int:
    return _int_param(params, "limit", default=DEFAULT_LIMIT)


def _offset(params: Mapping[str, Any]) -> int:
    return _int_param(params, "offset", default=0, min_value=0, max_value=10000)


def _dt(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _clean(value: Any, *, depth: int = 0) -> Any:
    if depth > 3:
        return "[TRUNCATED]"
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return _dt(value)
    if isinstance(value, Mapping):
        cleaned = {str(k): _clean(v, depth=depth + 1) for k, v in list(value.items())[:40]}
        return sanitize_mapping(cleaned)
    if isinstance(value, list):
        return [_clean(item, depth=depth + 1) for item in value[:30]]
    if isinstance(value, str):
        return sanitize_value(value[:1000])
    return value


def _model_summary(obj: Any, fields: tuple[str, ...]) -> dict[str, Any] | None:
    if obj is None:
        return None
    return {field: _clean(getattr(obj, field, None)) for field in fields}


def _paginated(queryset: QuerySet[Any], params: Mapping[str, Any]) -> tuple[list[Any], dict[str, int]]:
    limit = _limit(params)
    offset = _offset(params)
    total = queryset.count()
    rows = list(queryset[offset : offset + limit])
    return rows, {"limit": limit, "offset": offset, "total": total}


def _object_link_flags(links: list[OrchestrationBusinessObjectLink]) -> dict[str, bool]:
    object_types = {link.object_type for link in links}
    return {
        "has_order_plan": "OrderPlan" in object_types,
        "has_order_submission": "OrderSubmissionAttempt" in object_types,
        "has_order_status_sync": "OrderStatusSyncRecord" in object_types,
        "has_fill_sync": "FillSyncResult" in object_types or "OrderFillSummary" in object_types or "TradeFill" in object_types,
        "has_performance_metrics": "OrchestrationRunPerformance" in object_types,
    }


def _related_object_or_trace_query(
    *,
    related_object_type: str,
    related_object_id: int | str,
    trace_lookup: str,
    trace_id: str | None,
) -> Q:
    query = Q(related_object_type=related_object_type, related_object_id=str(related_object_id))
    if trace_id:
        query |= Q(**{trace_lookup: trace_id})
    return query


def _run_row(run: OrchestrationRun, links: list[OrchestrationBusinessObjectLink] | None = None) -> dict[str, Any]:
    links = links if links is not None else list(run.business_object_links.all())
    row = {
        "id": run.id,
        "run_key": run.run_key,
        "pipeline_code": run.pipeline_code,
        "scheduled_for_utc": _dt(run.scheduled_for_utc),
        "cycle_kind": run.cycle_kind,
        "trigger_mode": run.trigger_mode,
        "trigger_source": run.trigger_source,
        "status": run.status,
        "final_outcome": run.final_outcome,
        "reason_code": run.reason_code,
        "current_step_code": run.current_step_code,
        "last_completed_step_code": run.last_completed_step_code,
        "needs_manual_attention": run.needs_manual_attention,
        "trace_id": run.trace_id,
        "started_at_utc": _dt(run.started_at_utc),
        "finished_at_utc": _dt(run.finished_at_utc),
    }
    row.update(_object_link_flags(links))
    return row


def dashboard_summary() -> dict[str, Any]:
    latest_trade_sync = (
        BinanceSyncRun.objects.filter(sync_purpose=BinanceSyncPurpose.TRADE_PREPARATION)
        .order_by("-started_at_utc", "-id")
        .first()
    )
    latest_ops_sync = (
        BinanceSyncRun.objects.filter(sync_purpose=BinanceSyncPurpose.OPS_DISPLAY)
        .order_by("-started_at_utc", "-id")
        .first()
    )
    return {
        "recent_runs": [
            _run_row(run, list(run.business_object_links.all()))
            for run in OrchestrationRun.objects.prefetch_related("business_object_links").order_by("-scheduled_for_utc", "-id")[:5]
        ],
        "latest_alerts": [
            _alert_row(alert)
            for alert in AlertEvent.objects.order_by("-event_time_utc", "-id")[:5]
        ],
        "open_runtime_guard_issue_count": RuntimeGuardIssue.objects.filter(status=RuntimeGuardIssueStatus.OPEN).count(),
        "active_lock_count": OrderPlanActiveLock.objects.filter(status=ActiveLockStatus.ACTIVE).count(),
        "latest_trade_preparation_account_sync": _sync_run_row(latest_trade_sync),
        "latest_ops_display_account_sync": _sync_run_row(latest_ops_sync),
        "real_trading": real_trading_status(),
        "performance_metrics": {
            "available": False,
            "reason_code": "performance_metrics_not_implemented_in_current_codebase",
        },
    }


def list_runs(params: Mapping[str, Any]) -> dict[str, Any]:
    queryset = OrchestrationRun.objects.prefetch_related("business_object_links").order_by("-scheduled_for_utc", "-id")
    if status := params.get("status"):
        queryset = queryset.filter(status=status)
    if trigger_mode := params.get("trigger_mode"):
        queryset = queryset.filter(trigger_mode=trigger_mode)
    if params.get("needs_manual_attention") in {"1", "true", "True"}:
        queryset = queryset.filter(needs_manual_attention=True)
    if params.get("has_order") in {"1", "true", "True"}:
        queryset = queryset.filter(business_object_links__object_type="OrderPlan").distinct()
    rows, pagination = _paginated(queryset, params)
    return {
        "items": [_run_row(run, list(run.business_object_links.all())) for run in rows],
        "pagination": pagination,
    }


def get_run_detail(run_id: int) -> dict[str, Any]:
    try:
        detail = orchestration_run_detail(run_id)
    except ObjectDoesNotExist as exc:
        raise OpsConsoleObjectNotFound(f"OrchestrationRun {run_id} not found") from exc
    run = OrchestrationRun.objects.get(id=run_id)
    detail["related_alerts"] = [
        _alert_row(alert)
        for alert in AlertEvent.objects.filter(
            _related_object_or_trace_query(
                related_object_type="OrchestrationRun",
                related_object_id=run.id,
                trace_lookup="trace_id",
                trace_id=run.trace_id,
            )
        ).order_by("-event_time_utc", "-id")[:20]
    ]
    detail["related_runtime_guard_issues"] = [
        _issue_row(issue)
        for issue in RuntimeGuardIssue.objects.filter(
            _related_object_or_trace_query(
                related_object_type="OrchestrationRun",
                related_object_id=run.id,
                trace_lookup="related_trace_id",
                trace_id=run.trace_id,
            )
        ).order_by("-last_seen_at_utc", "-id")[:20]
    ]
    return detail


def _attempt_queryset() -> QuerySet[OrderSubmissionAttempt]:
    return OrderSubmissionAttempt.objects.select_related(
        "prepared_order_intent",
        "execution_preparation_result",
        "approved_order_intent",
        "risk_check_result",
        "candidate_order_intent",
        "order_plan",
        "active_lock",
    )


def _attempt_row(attempt: OrderSubmissionAttempt) -> dict[str, Any]:
    return _model_summary(
        attempt,
        (
            "id",
            "status",
            "reason_code",
            "exchange",
            "market_type",
            "account_domain",
            "symbol",
            "side",
            "position_side",
            "order_type",
            "quantity",
            "quantity_unit",
            "reduce_only",
            "client_order_id",
            "exchange_order_id",
            "exchange_status",
            "request_sent",
            "response_received",
            "trace_id",
            "submitted_at_utc",
            "finished_at_utc",
            "created_at_utc",
        ),
    ) or {}


def list_orders(params: Mapping[str, Any]) -> dict[str, Any]:
    queryset = _attempt_queryset().order_by("-created_at_utc", "-id")
    for field in ("status", "market_type", "account_domain", "symbol"):
        if value := params.get(field):
            queryset = queryset.filter(**{field: value})
    rows, pagination = _paginated(queryset, params)
    return {"items": [_attempt_row(attempt) for attempt in rows], "pagination": pagination}


def get_order_detail(attempt_id: int) -> dict[str, Any]:
    try:
        attempt = _attempt_queryset().get(id=attempt_id)
    except ObjectDoesNotExist as exc:
        raise OpsConsoleObjectNotFound(f"OrderSubmissionAttempt {attempt_id} not found") from exc

    status_records = OrderStatusSyncRecord.objects.filter(order_submission_attempt=attempt).order_by("poll_sequence", "id")
    fill_results = FillSyncResult.objects.filter(order_submission_attempt=attempt).order_by("sync_sequence", "id")
    trade_fills = TradeFill.objects.filter(order_submission_attempt=attempt).order_by("trade_time_utc", "id")
    try:
        fill_summary = attempt.order_fill_summary
    except ObjectDoesNotExist:
        fill_summary = None

    related_object_ids = [
        str(value)
        for value in (
            attempt.id,
            attempt.prepared_order_intent_id,
            attempt.approved_order_intent_id,
            attempt.risk_check_result_id,
            attempt.candidate_order_intent_id,
            attempt.order_plan_id,
        )
        if value is not None
    ]
    related_run_links = OrchestrationBusinessObjectLink.objects.filter(
        object_type__in=[
            "OrderSubmissionAttempt",
            "PreparedOrderIntent",
            "ApprovedOrderIntent",
            "RiskCheckResult",
            "CandidateOrderIntent",
            "OrderPlan",
        ],
        object_id__in=related_object_ids,
    ).select_related("orchestration_run")

    return {
        "order_submission_attempt": _attempt_row(attempt),
        "prepared_order_intent": _model_summary(
            attempt.prepared_order_intent,
            ("id", "status", "market_type", "account_domain", "symbol", "side", "quantity", "client_order_id", "expires_at_utc"),
        ),
        "approved_order_intent": _model_summary(
            attempt.approved_order_intent,
            ("id", "status", "reason_code", "market_type", "account_domain", "symbol", "side", "approved_quantity", "expires_at_utc"),
        ),
        "risk_check_result": _model_summary(
            attempt.risk_check_result,
            ("id", "status", "decision", "reason_code", "market_type", "account_domain", "symbol", "created_at_utc"),
        ),
        "candidate_order_intent": _model_summary(
            attempt.candidate_order_intent,
            ("id", "status", "intent_role", "plan_type", "side", "requested_size", "requested_notional", "reason_code"),
        ),
        "order_plan": _model_summary(
            attempt.order_plan,
            ("id", "status", "reason_code", "market_type", "account_domain", "symbol", "target_position_ratio", "created_at_utc"),
        ),
        "active_lock": _model_summary(
            attempt.active_lock,
            ("id", "status", "market_type", "account_domain", "symbol", "reason_code", "updated_at_utc"),
        ),
        "order_status_sync_records": [
            _model_summary(
                record,
                (
                    "id",
                    "query_outcome",
                    "poll_mode",
                    "poll_sequence",
                    "exchange_status",
                    "is_terminal_status",
                    "submission_resolution_status",
                    "reason_code",
                    "created_at_utc",
                ),
            )
            for record in status_records
        ],
        "fill_sync_results": [
            _model_summary(
                result,
                ("id", "sync_sequence", "sync_mode", "status", "reason_code", "returned_fill_count", "inserted_fill_count", "created_at_utc"),
            )
            for result in fill_results
        ],
        "order_fill_summary": _model_summary(
            fill_summary,
            ("id", "status", "reason_code", "fill_count", "total_quantity", "average_price", "created_at_utc"),
        ),
        "trade_fills": [
            _model_summary(fill, ("id", "exchange_trade_id", "price", "quantity", "commission", "commission_asset", "realized_pnl", "trade_time_utc"))
            for fill in trade_fills[:100]
        ],
        "related_orchestration_runs": [
            {
                "id": link.orchestration_run_id,
                "run_key": link.orchestration_run.run_key,
                "object_type": link.object_type,
                "object_id": link.object_id,
                "step_code": link.step_code,
            }
            for link in related_run_links[:50]
        ],
        "related_alerts": [
            _alert_row(alert)
            for alert in AlertEvent.objects.filter(
                _related_object_or_trace_query(
                    related_object_type="OrderSubmissionAttempt",
                    related_object_id=attempt.id,
                    trace_lookup="trace_id",
                    trace_id=attempt.trace_id,
                )
            ).order_by("-event_time_utc", "-id")[:20]
        ],
        "related_runtime_guard_issues": [
            _issue_row(issue)
            for issue in RuntimeGuardIssue.objects.filter(
                _related_object_or_trace_query(
                    related_object_type="OrderSubmissionAttempt",
                    related_object_id=attempt.id,
                    trace_lookup="related_trace_id",
                    trace_id=attempt.trace_id,
                )
            ).order_by("-last_seen_at_utc", "-id")[:20]
        ],
    }


def _sync_run_row(run: BinanceSyncRun | None) -> dict[str, Any] | None:
    return _model_summary(
        run,
        (
            "id",
            "business_request_key",
            "market_type",
            "account_domain",
            "sync_purpose",
            "requested_symbols",
            "status",
            "started_at_utc",
            "finished_at_utc",
            "as_of_utc",
            "expires_at_utc",
            "position_mode",
            "error_code",
            "error_message",
            "trace_id",
        ),
    )


def account_overview() -> dict[str, Any]:
    active_market_type = normalize_active_market_type(getattr(settings, "ACTIVE_MARKET_TYPE", ""))
    run = (
        BinanceSyncRun.objects.filter(
            sync_purpose=BinanceSyncPurpose.OPS_DISPLAY,
            market_type=active_market_type,
            account_domain=getattr(settings, "ACTIVE_ACCOUNT_DOMAIN", ""),
        )
        .order_by("-started_at_utc", "-id")
        .first()
    )
    if run is None:
        return {
            "sync_run": None,
            "reason_code": "ops_display_snapshot_not_found",
            "account_snapshot": None,
            "balances": [],
            "positions": [],
            "symbol_rules": [],
        }

    account = BinanceAccountSnapshot.objects.filter(sync_run=run).first()
    return {
        "sync_run": _sync_run_row(run),
        "reason_code": "ok",
        "account_snapshot": _model_summary(
            account,
            (
                "id",
                "market_type",
                "account_domain",
                "fee_tier",
                "can_trade",
                "position_mode",
                "total_wallet_balance",
                "total_unrealized_profit",
                "total_margin_balance",
                "available_balance",
                "native_asset",
                "as_of_utc",
            ),
        ),
        "balances": [
            _model_summary(balance, ("id", "asset", "wallet_balance", "available_balance", "cross_unrealized_pnl", "update_time_utc"))
            for balance in BinanceBalanceSnapshot.objects.filter(sync_run=run).order_by("asset")[:50]
        ],
        "positions": [
            _model_summary(
                position,
                (
                    "id",
                    "symbol",
                    "normalized_position_side",
                    "position_amount",
                    "entry_price",
                    "mark_price",
                    "unrealized_pnl",
                    "notional",
                    "margin_asset",
                    "margin_mode",
                    "update_time_utc",
                ),
            )
            for position in BinancePositionSnapshot.objects.filter(sync_run=run).order_by("symbol", "normalized_position_side")[:50]
        ],
        "symbol_rules": [
            _model_summary(rule, ("id", "symbol", "contract_status", "quantity_precision", "tick_size", "step_size", "min_quantity", "min_notional"))
            for rule in BinanceSymbolRuleSnapshot.objects.filter(sync_run=run).order_by("symbol")[:50]
        ],
    }


def _issue_row(issue: RuntimeGuardIssue) -> dict[str, Any]:
    return _model_summary(
        issue,
        (
            "id",
            "issue_key",
            "issue_type",
            "severity",
            "status",
            "needs_manual_attention",
            "related_object_type",
            "related_object_id",
            "related_trace_id",
            "description_zh",
            "first_seen_at_utc",
            "last_seen_at_utc",
            "occurrence_count",
            "alert_event_id",
        ),
    ) or {}


def list_runtime_guard_issues(params: Mapping[str, Any]) -> dict[str, Any]:
    queryset = RuntimeGuardIssue.objects.order_by("-last_seen_at_utc", "-id")
    for field in ("status", "severity", "issue_type", "related_object_type", "related_object_id"):
        if value := params.get(field):
            queryset = queryset.filter(**{field: value})
    rows, pagination = _paginated(queryset, params)
    return {"items": [_issue_row(issue) for issue in rows], "pagination": pagination}


def get_runtime_guard_issue_detail(issue_id: int) -> dict[str, Any]:
    try:
        issue = RuntimeGuardIssue.objects.get(id=issue_id)
    except ObjectDoesNotExist as exc:
        raise OpsConsoleObjectNotFound(f"RuntimeGuardIssue {issue_id} not found") from exc
    return {
        "issue": _issue_row(issue),
        "evidence": _clean(issue.evidence),
        "related_alert": _alert_row(AlertEvent.objects.filter(id=issue.alert_event_id).first()) if issue.alert_event_id else None,
    }


def _alert_row(alert: AlertEvent | None) -> dict[str, Any] | None:
    return _model_summary(
        alert,
        (
            "id",
            "event_key",
            "source_module",
            "event_type",
            "event_category",
            "severity",
            "title_zh",
            "message_zh",
            "business_status",
            "reason_code",
            "related_object_type",
            "related_object_id",
            "trace_id",
            "event_time_utc",
            "delivery_enabled",
        ),
    )


def list_alerts(params: Mapping[str, Any]) -> dict[str, Any]:
    queryset = AlertEvent.objects.order_by("-event_time_utc", "-id")
    for field in ("severity", "source_module", "event_type", "trace_id", "related_object_type", "related_object_id"):
        if value := params.get(field):
            queryset = queryset.filter(**{field: value})
    rows, pagination = _paginated(queryset, params)
    return {"items": [_alert_row(alert) for alert in rows], "pagination": pagination}


def get_alert_detail(alert_id: int) -> dict[str, Any]:
    try:
        alert = AlertEvent.objects.get(id=alert_id)
    except ObjectDoesNotExist as exc:
        raise OpsConsoleObjectNotFound(f"AlertEvent {alert_id} not found") from exc
    return {
        "alert": _alert_row(alert),
        "payload_summary": _clean(alert.payload_summary),
        "evidence_refs": _clean(alert.evidence_refs),
        "delivery_attempts": [
            _model_summary(
                attempt,
                (
                    "id",
                    "channel",
                    "route_code",
                    "template_code",
                    "delivery_status",
                    "attempt_sequence",
                    "request_sent",
                    "http_status",
                    "error_code",
                    "retryable",
                    "next_retry_at_utc",
                    "created_at_utc",
                    "updated_at_utc",
                ),
            )
            for attempt in NotificationDeliveryAttempt.objects.filter(alert_event=alert).order_by("attempt_sequence", "id")
        ],
        "suppressions": [
            _model_summary(
                suppression,
                ("id", "suppression_type", "reason_code", "dedupe_key", "cooldown_key", "window_start_utc", "window_end_utc", "created_at_utc"),
            )
            for suppression in NotificationSuppression.objects.filter(alert_event=alert).order_by("id")
        ],
    }


def real_trading_status() -> dict[str, Any]:
    effective = get_effective_real_trading_permission()
    config = RuntimeTradingConfig.objects.filter(config_key="default").first()
    return {
        "deployment_real_trading_permission": effective.deployment_allowed,
        "runtime_real_trading_permission": effective.runtime_allowed,
        "effective_real_trading_permission": effective.effective_allowed,
        "fail_closed": effective.fail_closed,
        "reason_code": effective.reason_code,
        "active_exchange": getattr(settings, "ACTIVE_EXCHANGE", ""),
        "active_market_type": getattr(settings, "ACTIVE_MARKET_TYPE", ""),
        "normalized_active_market_type": normalize_active_market_type(getattr(settings, "ACTIVE_MARKET_TYPE", "")),
        "active_account_domain": getattr(settings, "ACTIVE_ACCOUNT_DOMAIN", ""),
        "active_symbol": getattr(settings, "ACTIVE_SYMBOL", ""),
        "runtime_config": _model_summary(config, ("id", "config_key", "updated_by", "updated_reason", "updated_at_utc")),
    }


def list_audit_log(params: Mapping[str, Any]) -> dict[str, Any]:
    queryset = AuditRecord.objects.order_by("-created_at_utc", "-id")
    for field in ("operator_id", "operation_type", "target_object_type", "target_object_id", "trace_id"):
        if value := params.get(field):
            queryset = queryset.filter(**{field: value})
    rows, pagination = _paginated(queryset, params)
    return {
        "items": [
            {
                "id": record.id,
                "operator_id": record.operator_id,
                "operation_type": record.operation_type,
                "target_object_type": record.target_object_type,
                "target_object_id": record.target_object_id,
                "before_state_summary": _clean(record.before_state_summary),
                "after_state_summary": _clean(record.after_state_summary),
                "reason": record.reason,
                "evidence": _clean(record.evidence),
                "result": record.result,
                "trace_id": record.trace_id,
                "trigger_source": record.trigger_source,
                "created_at_utc": _dt(record.created_at_utc),
            }
            for record in rows
        ],
        "pagination": pagination,
    }
