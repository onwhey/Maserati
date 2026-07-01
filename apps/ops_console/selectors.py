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
from apps.review_dataset.selectors import (
    get_review_dataset_export_detail,
    get_review_dataset_record_detail,
    latest_review_dataset_summary,
    list_review_dataset_exports,
    list_review_dataset_records,
)
from apps.runtime_config.models import RuntimeTradingConfig
from apps.runtime_config.services import get_effective_real_trading_permission
from apps.runtime_guard.models import RuntimeGuardIssue, RuntimeGuardIssueStatus
from apps.strategy_analysis.models import (
    AtomicSignalDefinition,
    DecisionPolicyDefinition,
    DefinitionLifecycleStatus,
    DomainSignalDefinition,
    FeatureDefinition,
    MarketRegimeDefinition,
    ReleaseItemComponentType,
    StrategyAnalysisRelease,
    StrategyAnalysisReleaseActivation,
    StrategyAnalysisReleaseApproval,
    StrategyAnalysisReleaseItem,
    StrategyAnalysisReleaseValidationEvidence,
    StrategyAnalysisWorkspace,
    StrategyAnalysisWorkspaceItem,
    StrategyDefinition,
    StrategyRoutePolicy,
    StrategyRouteRule,
    StrategySignalQualityRuleSet,
)


DEFAULT_LIMIT = 20
MAX_LIMIT = 100

STRATEGY_COMPONENT_MODELS: dict[str, type[Any]] = {
    ReleaseItemComponentType.FEATURE_DEFINITION: FeatureDefinition,
    ReleaseItemComponentType.ATOMIC_SIGNAL_DEFINITION: AtomicSignalDefinition,
    ReleaseItemComponentType.DOMAIN_SIGNAL_DEFINITION: DomainSignalDefinition,
    ReleaseItemComponentType.MARKET_REGIME_DEFINITION: MarketRegimeDefinition,
    ReleaseItemComponentType.STRATEGY_ROUTE_POLICY: StrategyRoutePolicy,
    ReleaseItemComponentType.STRATEGY_ROUTE_RULE: StrategyRouteRule,
    ReleaseItemComponentType.STRATEGY_DEFINITION: StrategyDefinition,
    ReleaseItemComponentType.STRATEGY_SIGNAL_QUALITY_RULE_SET: StrategySignalQualityRuleSet,
    ReleaseItemComponentType.DECISION_POLICY_DEFINITION: DecisionPolicyDefinition,
}


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


def _decimal_text(value: Decimal) -> str:
    normalized = value.normalize()
    if normalized.is_zero():
        return "0"
    return format(normalized, "f")


def _clean(value: Any, *, depth: int = 0) -> Any:
    if depth > 3:
        return "[TRUNCATED]"
    if isinstance(value, Decimal):
        return _decimal_text(value)
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
        "has_review_dataset": "ReviewDatasetRecord" in object_types,
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
        "review_dataset": latest_review_dataset_summary(),
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


def _release_row(release: StrategyAnalysisRelease | None) -> dict[str, Any] | None:
    return _model_summary(
        release,
        (
            "id",
            "release_code",
            "display_name",
            "description",
            "release_hash",
            "approval_status",
            "is_active",
            "active_slot",
            "validation_evidence_count",
            "created_by",
            "approved_by",
            "activated_by",
            "approved_at_utc",
            "activated_at_utc",
            "deactivated_at_utc",
            "created_at_utc",
            "updated_at_utc",
        ),
    )


def _release_item_row(item: StrategyAnalysisReleaseItem) -> dict[str, Any]:
    return _model_summary(
        item,
        (
            "id",
            "component_type",
            "component_object_id",
            "component_code",
            "definition_hash",
            "algorithm_name",
            "algorithm_version",
            "params_hash",
            "dependency_hash",
            "expected_definition_set_hash",
            "sort_order",
            "payload_summary",
            "created_at_utc",
        ),
    ) or {}


def list_strategy_releases(params: Mapping[str, Any]) -> dict[str, Any]:
    queryset = StrategyAnalysisRelease.objects.order_by("-updated_at_utc", "-id")
    for field in ("approval_status", "release_code"):
        if value := params.get(field):
            queryset = queryset.filter(**{field: value})
    if params.get("is_active") in {"1", "true", "True"}:
        queryset = queryset.filter(is_active=True)
    rows, pagination = _paginated(queryset, params)
    return {"items": [_release_row(release) for release in rows], "pagination": pagination}


def get_current_strategy_release() -> dict[str, Any]:
    release = StrategyAnalysisRelease.objects.filter(is_active=True, active_slot=1).order_by("-activated_at_utc", "-id").first()
    return {"release": _release_row(release)}


def get_strategy_release_detail(release_id: int) -> dict[str, Any]:
    try:
        release = StrategyAnalysisRelease.objects.prefetch_related("items").get(id=release_id)
    except ObjectDoesNotExist as exc:
        raise OpsConsoleObjectNotFound(f"StrategyAnalysisRelease {release_id} not found") from exc
    evidence = StrategyAnalysisReleaseValidationEvidence.objects.filter(release=release).order_by("-created_at_utc", "-id")
    approvals = StrategyAnalysisReleaseApproval.objects.filter(release=release).order_by("-operated_at_utc", "-id")
    activations = StrategyAnalysisReleaseActivation.objects.filter(release=release).order_by("-operated_at_utc", "-id")
    return {
        "release": _release_row(release),
        "items": [_release_item_row(item) for item in release.items.order_by("component_type", "sort_order", "component_code", "id")],
        "validation_evidence": [
            _model_summary(item, ("id", "release_hash", "evidence_type", "evidence_ref", "summary", "created_by", "created_at_utc"))
            for item in evidence[:50]
        ],
        "approvals": [
            _model_summary(
                item,
                ("id", "release_hash", "action", "validation_evidence_refs", "reason", "operator_id", "operated_at_utc", "trace_id"),
            )
            for item in approvals[:50]
        ],
        "activations": [
            _model_summary(item, ("id", "release_hash", "action", "previous_release_id", "operator_id", "reason", "operated_at_utc", "trace_id"))
            for item in activations[:50]
        ],
        "related_alerts": [
            _alert_row(alert)
            for alert in AlertEvent.objects.filter(
                related_object_type="StrategyAnalysisRelease",
                related_object_id=str(release.id),
            ).order_by("-event_time_utc", "-id")[:20]
        ],
    }


def _definition_enabled_filter(model: type[Any]) -> QuerySet[Any]:
    queryset = model.objects.all()
    if model is FeatureDefinition:
        return queryset.filter(is_enabled=True)
    if hasattr(model, "status") and hasattr(model, "enabled"):
        return queryset.filter(status=DefinitionLifecycleStatus.ACTIVE, enabled=True)
    return queryset


def _component_row(component_type: str, component: Any) -> dict[str, Any]:
    code_fields = {
        ReleaseItemComponentType.FEATURE_DEFINITION: ("feature_code", "definition_version", "definition_hash"),
        ReleaseItemComponentType.ATOMIC_SIGNAL_DEFINITION: ("signal_code", "", "definition_hash"),
        ReleaseItemComponentType.DOMAIN_SIGNAL_DEFINITION: ("domain_code", "", "definition_hash"),
        ReleaseItemComponentType.MARKET_REGIME_DEFINITION: ("definition_code", "", "definition_hash"),
        ReleaseItemComponentType.STRATEGY_ROUTE_POLICY: ("policy_code", "policy_version", "definition_hash"),
        ReleaseItemComponentType.STRATEGY_ROUTE_RULE: ("rule_code", "", "rule_hash"),
        ReleaseItemComponentType.STRATEGY_DEFINITION: ("strategy_code", "strategy_version", "definition_hash"),
        ReleaseItemComponentType.STRATEGY_SIGNAL_QUALITY_RULE_SET: ("rule_set_code", "rule_set_version", "rule_set_hash"),
        ReleaseItemComponentType.DECISION_POLICY_DEFINITION: ("policy_code", "policy_version", "definition_hash"),
    }
    code_field, version_field, hash_field = code_fields[component_type]
    return {
        "component_type": component_type,
        "component_object_id": component.id,
        "component_code": getattr(component, code_field),
        "version": getattr(component, version_field, "") if version_field else "",
        "display_name": getattr(component, "display_name", ""),
        "description": getattr(component, "description", ""),
        "definition_hash": getattr(component, hash_field),
        "algorithm_name": getattr(component, "algorithm_name", ""),
        "algorithm_version": getattr(component, "algorithm_version", ""),
        "params_hash": getattr(component, "params_hash", ""),
        "enabled": getattr(component, "enabled", getattr(component, "is_enabled", True)),
        "status": getattr(component, "status", "enabled"),
    }


def list_strategy_release_components(params: Mapping[str, Any]) -> dict[str, Any]:
    requested_type = params.get("component_type")
    rows: list[dict[str, Any]] = []
    for component_type, model in STRATEGY_COMPONENT_MODELS.items():
        if requested_type and requested_type != component_type:
            continue
        queryset = _definition_enabled_filter(model).order_by("id")[:200]
        rows.extend(_component_row(component_type, component) for component in queryset)
    return {"items": rows, "pagination": {"limit": len(rows), "offset": 0, "total": len(rows)}}


def _strategy_workspace_row(workspace: StrategyAnalysisWorkspace | None) -> dict[str, Any] | None:
    if workspace is None:
        return None
    return _model_summary(
        workspace,
        (
            "id",
            "workspace_code",
            "display_name",
            "description",
            "status",
            "default_slot",
            "created_by",
            "updated_by",
            "created_at_utc",
            "updated_at_utc",
        ),
    )


def _strategy_workspace_item_row(item: StrategyAnalysisWorkspaceItem) -> dict[str, Any]:
    return _model_summary(
        item,
        (
            "id",
            "component_type",
            "component_object_id",
            "component_code",
            "component_version",
            "definition_hash",
            "inclusion_managed",
            "is_included",
            "selection_reason",
            "updated_by",
            "updated_at_utc",
        ),
    )


def get_strategy_workspace() -> dict[str, Any]:
    workspace = StrategyAnalysisWorkspace.objects.filter(default_slot=1).order_by("-id").first()
    items = []
    if workspace is not None:
        items = [
            _strategy_workspace_item_row(item)
            for item in workspace.items.order_by("component_type", "component_code", "id")
        ]
    return {"workspace": _strategy_workspace_row(workspace), "items": items}


def list_strategy_workspace_components(params: Mapping[str, Any]) -> dict[str, Any]:
    workspace = StrategyAnalysisWorkspace.objects.filter(default_slot=1).order_by("-id").first()
    workspace_items: dict[tuple[str, str], StrategyAnalysisWorkspaceItem] = {}
    if workspace is not None:
        workspace_items = {
            (item.component_type, item.component_code): item
            for item in workspace.items.order_by("component_type", "component_code", "id")
        }

    requested_type = params.get("component_type")
    rows: list[dict[str, Any]] = []
    for component_type, model in STRATEGY_COMPONENT_MODELS.items():
        if requested_type and requested_type != component_type:
            continue
        queryset = _definition_enabled_filter(model).order_by("id")[:300]
        for component in queryset:
            row = _component_row(component_type, component)
            workspace_item = workspace_items.get((component_type, row["component_code"]))
            row.update(
                {
                    "workspace_item_id": workspace_item.id if workspace_item else None,
                    "workspace_selected_component_object_id": workspace_item.component_object_id if workspace_item else None,
                    "workspace_selected_version": workspace_item.component_version if workspace_item else "",
                    "workspace_is_selected_version": bool(
                        workspace_item and workspace_item.component_object_id == row["component_object_id"]
                    ),
                    "workspace_inclusion_managed": workspace_item.inclusion_managed if workspace_item else component_type != ReleaseItemComponentType.FEATURE_DEFINITION,
                    "workspace_is_included": workspace_item.is_included if workspace_item else False,
                    "workspace_selection_reason": workspace_item.selection_reason if workspace_item else "",
                }
            )
            rows.append(row)

    return {
        "workspace": _strategy_workspace_row(workspace),
        "items": rows,
        "pagination": {"limit": len(rows), "offset": 0, "total": len(rows)},
    }
