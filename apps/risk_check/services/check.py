"""RiskCheck 模块：审批 CandidateOrderIntent 并生成 RiskCheckResult / ApprovedOrderIntent；读写 MySQL；不访问 Redis；不访问 Binance；不发送 Hermes；不调用大模型；不提交订单；不允许真实交易。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

from django.conf import settings
from django.db import DatabaseError, IntegrityError, transaction
from django.utils import timezone

from apps.binance_account_sync.models import (
    BinanceAccountSnapshot,
    BinanceBalanceSnapshot,
    BinancePositionSnapshot,
    BinanceSymbolRuleSnapshot,
    BinanceSyncRun,
)
from apps.binance_account_sync.selectors import verify_trade_preparation_snapshot_set
from apps.binance_account_sync.services.hashing import stable_hash
from apps.foundation.results import ResultStatus, ServiceResult
from apps.order_plan.models import CandidateOrderIntent, CandidateIntentRole, CandidateIntentStatus, OrderPlan, OrderPlanActiveLock
from apps.order_plan.services.active_lock import release_for_pre_execution_stop
from apps.price_snapshot.models import PriceSnapshot
from apps.price_snapshot.services.snapshot import compute_price_snapshot_hash, price_snapshot_hash_payload

from ..domain import RiskCheckContext, RuleEngineSummary
from ..models import (
    ApprovedOrderIntent,
    ApprovedOrderIntentStatus,
    RiskCheckIssue,
    RiskCheckResult,
    RiskCheckStatus,
    RiskRuleDefinition,
    RiskRuleResult,
    RiskRuleResultStatus,
)
from .alerts import record_risk_check_alert
from .hashing import approved_order_intent_hash, risk_check_key_hash, risk_check_result_hash, risk_rule_set_hash
from .rule_definitions import BUILTIN_RULE_CODES, ensure_builtin_rule_set, load_active_rule_definitions
from .rule_engine import RuleEngine
from .rule_registry import RiskRuleRegistry, default_registry


@dataclass(frozen=True)
class RiskCheckLoadedContext:
    order_plan: OrderPlan
    primary_candidate: CandidateOrderIntent
    fallback_candidate: CandidateOrderIntent | None
    active_lock: OrderPlanActiveLock
    sync_run: BinanceSyncRun
    account_snapshot: BinanceAccountSnapshot
    balance_snapshot: BinanceBalanceSnapshot
    position_snapshot: BinancePositionSnapshot
    symbol_rule_snapshot: BinanceSymbolRuleSnapshot
    price_snapshot: PriceSnapshot
    snapshot_integrity_reason: str
    price_integrity_reason: str


def run_risk_check(
    *,
    business_request_key: str,
    order_plan_id: int,
    candidate_order_intent_id: int,
    binance_sync_run_id: int,
    price_snapshot_id: int,
    active_lock_id: int,
    reference_time_utc: datetime,
    risk_rule_set: str | None = None,
    trace_id: str,
    trigger_source: str,
    dry_run: bool = False,
    registry: RiskRuleRegistry | None = None,
) -> ServiceResult:
    request_error = _request_error(
        business_request_key=business_request_key,
        order_plan_id=order_plan_id,
        candidate_order_intent_id=candidate_order_intent_id,
        binance_sync_run_id=binance_sync_run_id,
        price_snapshot_id=price_snapshot_id,
        active_lock_id=active_lock_id,
        reference_time_utc=reference_time_utc,
        trace_id=trace_id,
        trigger_source=trigger_source,
    )
    if request_error:
        return _blocked_without_result(request_error, "RiskCheck 请求合同不完整", business_request_key, trace_id, trigger_source)
    reference_time = reference_time_utc.astimezone(UTC)
    config, config_error = _load_config(risk_rule_set=risk_rule_set)
    if config_error:
        return _blocked_without_result(config_error, "RiskCheck 配置不可用", business_request_key, trace_id, trigger_source)

    try:
        loaded = _load_context(
            order_plan_id=order_plan_id,
            candidate_order_intent_id=candidate_order_intent_id,
            binance_sync_run_id=binance_sync_run_id,
            price_snapshot_id=price_snapshot_id,
            active_lock_id=active_lock_id,
            trace_id=trace_id,
            trigger_source=trigger_source,
        )
    except DatabaseError as exc:
        return _failed_without_result(business_request_key, trace_id, trigger_source, type(exc).__name__)
    if isinstance(loaded, str):
        return _blocked_without_result(loaded, "RiskCheck 上游对象不可读取或直接输入不一致", business_request_key, trace_id, trigger_source)

    if not dry_run:
        existing_for_candidate = (
            RiskCheckResult.objects.filter(primary_candidate_order_intent=loaded.primary_candidate)
            .order_by("id")
            .first()
        )
        if existing_for_candidate is not None:
            return _result_from_risk_check(existing_for_candidate, trace_id=trace_id, trigger_source=trigger_source)

    if loaded.primary_candidate.intent_role != CandidateIntentRole.PRIMARY:
        return _blocked_without_result(
            "risk_check_entry_candidate_not_primary",
            "RiskCheck 正式入口必须从 primary 候选订单开始",
            business_request_key,
            trace_id,
            trigger_source,
        )

    if dry_run:
        definitions, rule_set_hash_value = _virtual_builtin_definitions(config["risk_rule_set"])
    else:
        ensure_builtin_rule_set(config["risk_rule_set"])
        rule_set, definitions = load_active_rule_definitions(config["risk_rule_set"])
        if rule_set is None or not definitions:
            return _persist_blocked_context_result(
                loaded=loaded,
                config=config,
                business_request_key=business_request_key,
                reference_time_utc=reference_time,
                reason_code="risk_rule_set_empty",
                message="当前风控规则集不可用",
                trace_id=trace_id,
                trigger_source=trigger_source,
            )
        rule_set_hash_value = rule_set.rule_set_hash

    risk_check_key = _risk_check_key(
        business_request_key=business_request_key,
        loaded=loaded,
        rule_set_hash_value=rule_set_hash_value,
        config=config,
    )
    if not dry_run:
        existing = RiskCheckResult.objects.filter(risk_check_key=risk_check_key).first()
        if existing is not None:
            return _result_from_risk_check(existing, trace_id=trace_id, trigger_source=trigger_source)

    registry = registry or default_registry()
    primary_context = _context_from_loaded(
        loaded=loaded,
        candidate=loaded.primary_candidate,
        reference_time_utc=reference_time,
        config=config,
    )
    primary_summary = RuleEngine(registry).evaluate(context=primary_context, definitions=definitions)
    selected_context = primary_context
    selected_summary = primary_summary
    fallback_summary = None
    if _should_attempt_fallback(primary_context, primary_summary) and loaded.fallback_candidate is not None:
        fallback_context = _context_from_loaded(
            loaded=loaded,
            candidate=loaded.fallback_candidate,
            reference_time_utc=reference_time,
            config=config,
        )
        fallback_summary = RuleEngine(registry).evaluate(context=fallback_context, definitions=definitions)
        if fallback_summary.final_status == RiskCheckStatus.ALLOW:
            selected_context = fallback_context
            selected_summary = fallback_summary
        else:
            selected_summary = fallback_summary
            selected_context = fallback_context

    all_evaluations = primary_summary.evaluations
    if fallback_summary is not None:
        all_evaluations = [
            *[_with_candidate_role(item, CandidateIntentRole.PRIMARY) for item in primary_summary.evaluations],
            *[_with_candidate_role(item, CandidateIntentRole.FALLBACK_REDUCE_ONLY) for item in fallback_summary.evaluations],
        ]
    if dry_run:
        return ServiceResult(
            _service_status(selected_summary.final_status),
            selected_summary.reason_code,
            selected_summary.message_zh,
            trace_id,
            trigger_source,
            {
                "dry_run": True,
                "risk_check_status": selected_summary.final_status,
                "selected_intent_role": selected_context.candidate.intent_role if selected_summary.final_status == RiskCheckStatus.ALLOW else "",
                "checked_rules": [_evaluation_summary(item) for item in all_evaluations],
                "approved_order_intent_id": None,
            },
        )

    return _persist_risk_check(
        loaded=loaded,
        selected_context=selected_context,
        selected_summary=selected_summary,
        all_evaluations=all_evaluations,
        config=config,
        risk_check_key=risk_check_key,
        rule_set_hash_value=rule_set_hash_value,
        business_request_key=business_request_key,
        reference_time_utc=reference_time,
        trace_id=trace_id,
        trigger_source=trigger_source,
        fallback_selected=fallback_summary is not None and selected_summary.final_status == RiskCheckStatus.ALLOW and selected_context.candidate.intent_role == CandidateIntentRole.FALLBACK_REDUCE_ONLY,
    )


def _load_context(
    *,
    order_plan_id: int,
    candidate_order_intent_id: int,
    binance_sync_run_id: int,
    price_snapshot_id: int,
    active_lock_id: int,
    trace_id: str,
    trigger_source: str,
) -> RiskCheckLoadedContext | str:
    try:
        plan = OrderPlan.objects.get(id=order_plan_id)
        primary = CandidateOrderIntent.objects.get(id=candidate_order_intent_id)
        sync_run = BinanceSyncRun.objects.get(id=binance_sync_run_id)
        price_snapshot = PriceSnapshot.objects.get(id=price_snapshot_id)
        active_lock = OrderPlanActiveLock.objects.get(id=active_lock_id)
    except OrderPlan.DoesNotExist:
        return "order_plan_not_found"
    except CandidateOrderIntent.DoesNotExist:
        return "candidate_order_intent_not_found"
    except BinanceSyncRun.DoesNotExist:
        return "binance_sync_run_not_found"
    except PriceSnapshot.DoesNotExist:
        return "price_snapshot_not_found"
    except OrderPlanActiveLock.DoesNotExist:
        return "active_lock_not_found"
    if (
        plan.binance_sync_run_id != sync_run.id
        or plan.price_snapshot_id != price_snapshot.id
        or plan.active_lock_id != active_lock.id
        or primary.order_plan_id != plan.id
    ):
        return "risk_check_direct_input_mismatch"
    fallback = CandidateOrderIntent.objects.filter(
        order_plan=plan,
        intent_role=CandidateIntentRole.FALLBACK_REDUCE_ONLY,
    ).first()
    snapshot_reason = ""
    integrity = verify_trade_preparation_snapshot_set(
        sync_run_id=sync_run.id,
        trace_id=trace_id,
        trigger_source=trigger_source,
    )
    if integrity.status != ResultStatus.SUCCEEDED:
        snapshot_reason = integrity.reason_code
    return RiskCheckLoadedContext(
        order_plan=plan,
        primary_candidate=primary,
        fallback_candidate=fallback,
        active_lock=active_lock,
        sync_run=sync_run,
        account_snapshot=plan.account_snapshot,
        balance_snapshot=plan.balance_snapshot,
        position_snapshot=plan.position_snapshot,
        symbol_rule_snapshot=plan.symbol_rule_snapshot,
        price_snapshot=price_snapshot,
        snapshot_integrity_reason=snapshot_reason,
        price_integrity_reason=_price_integrity_reason(price_snapshot),
    )


def _context_from_loaded(
    *,
    loaded: RiskCheckLoadedContext,
    candidate: CandidateOrderIntent,
    reference_time_utc: datetime,
    config: dict[str, Any],
) -> RiskCheckContext:
    return RiskCheckContext(
        order_plan=loaded.order_plan,
        candidate=candidate,
        primary_candidate=loaded.primary_candidate,
        fallback_candidate=loaded.fallback_candidate,
        active_lock=loaded.active_lock,
        sync_run=loaded.sync_run,
        account_snapshot=loaded.account_snapshot,
        balance_snapshot=loaded.balance_snapshot,
        position_snapshot=loaded.position_snapshot,
        symbol_rule_snapshot=loaded.symbol_rule_snapshot,
        price_snapshot=loaded.price_snapshot,
        reference_time_utc=reference_time_utc,
        risk_config=config,
        snapshot_integrity_reason=loaded.snapshot_integrity_reason,
        price_integrity_reason=loaded.price_integrity_reason,
    )


def _persist_risk_check(
    *,
    loaded: RiskCheckLoadedContext,
    selected_context: RiskCheckContext,
    selected_summary: RuleEngineSummary,
    all_evaluations: list,
    config: dict[str, Any],
    risk_check_key: str,
    rule_set_hash_value: str,
    business_request_key: str,
    reference_time_utc: datetime,
    trace_id: str,
    trigger_source: str,
    fallback_selected: bool,
) -> ServiceResult:
    try:
        with transaction.atomic():
            existing = RiskCheckResult.objects.select_for_update().filter(risk_check_key=risk_check_key).first()
            if existing is not None:
                return _result_from_risk_check(existing, trace_id=trace_id, trigger_source=trigger_source)
            status = selected_summary.final_status
            selected_candidate = selected_context.candidate if status == RiskCheckStatus.ALLOW else None
            result = RiskCheckResult.objects.create(
                business_request_key=business_request_key,
                risk_check_key=risk_check_key,
                status=status,
                is_usable=status == RiskCheckStatus.ALLOW,
                allows_downstream=status == RiskCheckStatus.ALLOW,
                selected_candidate_order_intent=selected_candidate,
                selected_intent_role=selected_candidate.intent_role if selected_candidate is not None else "",
                order_plan=loaded.order_plan,
                primary_candidate_order_intent=loaded.primary_candidate,
                fallback_candidate_order_intent=loaded.fallback_candidate,
                binance_sync_run=loaded.sync_run,
                binance_snapshot_set_hash=loaded.sync_run.snapshot_set_hash,
                account_snapshot=loaded.account_snapshot,
                balance_snapshot=loaded.balance_snapshot,
                position_snapshot=loaded.position_snapshot,
                symbol_rule_snapshot=loaded.symbol_rule_snapshot,
                price_snapshot=loaded.price_snapshot,
                price_snapshot_hash=loaded.price_snapshot.price_snapshot_hash,
                active_lock=loaded.active_lock,
                rule_set_hash=rule_set_hash_value,
                checked_rules=[_evaluation_summary(item) for item in all_evaluations],
                risk_measures=_risk_measures(selected_context),
                risk_config_snapshot=config,
                input_snapshot=_input_snapshot(loaded),
                risk_snapshot={
                    "status": status,
                    "reason_code": selected_summary.reason_code,
                    "selected_intent_role": selected_candidate.intent_role if selected_candidate else "",
                },
                evidence_items=[item.evidence for item in all_evaluations if item.status != RiskRuleResultStatus.PASS],
                evidence_text_zh=selected_summary.message_zh,
                reason_code=selected_summary.reason_code,
                trace_id=trace_id,
                trigger_source=trigger_source,
            )
            rule_result_by_code = _persist_rule_results(result, all_evaluations)
            _persist_issues(result, rule_result_by_code, all_evaluations)
            approved = None
            if status == RiskCheckStatus.ALLOW and selected_candidate is not None:
                approved = _create_approved_order_intent(
                    result=result,
                    context=selected_context,
                    config=config,
                    rule_set_hash_value=rule_set_hash_value,
                    reference_time_utc=reference_time_utc,
                    trace_id=trace_id,
                    trigger_source=trigger_source,
                )
                selected_candidate.status = CandidateIntentStatus.APPROVED
                selected_candidate.reason_code = "risk_check_allowed"
                selected_candidate.save(update_fields=["status", "reason_code"])
                if fallback_selected:
                    loaded.primary_candidate.status = CandidateIntentStatus.DENIED
                    loaded.primary_candidate.reason_code = "primary_not_approved_fallback_selected"
                    loaded.primary_candidate.save(update_fields=["status", "reason_code"])
            else:
                _mark_candidates_not_approved(loaded=loaded, status=status, reason_code=selected_summary.reason_code)

        _post_persist_side_effects(
            result=result,
            approved=approved,
            status=status,
            reason_code=selected_summary.reason_code,
            message=selected_summary.message_zh,
            fallback_selected=fallback_selected,
            trace_id=trace_id,
            trigger_source=trigger_source,
        )
        return _result_from_risk_check(result, trace_id=trace_id, trigger_source=trigger_source)
    except IntegrityError:
        existing = RiskCheckResult.objects.filter(risk_check_key=risk_check_key).first()
        if existing is not None:
            return _result_from_risk_check(existing, trace_id=trace_id, trigger_source=trigger_source)
        return _failed_without_result(business_request_key, trace_id, trigger_source, "IntegrityError")
    except DatabaseError as exc:
        return _failed_without_result(business_request_key, trace_id, trigger_source, type(exc).__name__)


def _persist_blocked_context_result(
    *,
    loaded: RiskCheckLoadedContext,
    config: dict[str, Any],
    business_request_key: str,
    reference_time_utc: datetime,
    reason_code: str,
    message: str,
    trace_id: str,
    trigger_source: str,
) -> ServiceResult:
    rule_set_hash_value = risk_rule_set_hash({"rule_set_code": config["risk_rule_set"], "definitions": []})
    risk_check_key = _risk_check_key(
        business_request_key=business_request_key,
        loaded=loaded,
        rule_set_hash_value=rule_set_hash_value,
        config=config,
    )
    summary = RuleEngineSummary(RiskCheckStatus.BLOCKED, reason_code, message, [])
    return _persist_risk_check(
        loaded=loaded,
        selected_context=_context_from_loaded(loaded=loaded, candidate=loaded.primary_candidate, reference_time_utc=reference_time_utc, config=config),
        selected_summary=summary,
        all_evaluations=[],
        config=config,
        risk_check_key=risk_check_key,
        rule_set_hash_value=rule_set_hash_value,
        business_request_key=business_request_key,
        reference_time_utc=reference_time_utc,
        trace_id=trace_id,
        trigger_source=trigger_source,
        fallback_selected=False,
    )


def _post_persist_side_effects(
    *,
    result: RiskCheckResult,
    approved: ApprovedOrderIntent | None,
    status: str,
    reason_code: str,
    message: str,
    fallback_selected: bool,
    trace_id: str,
    trigger_source: str,
) -> None:
    alert_ids = []
    event_type = {
        RiskCheckStatus.ALLOW: "risk_check_allow",
        RiskCheckStatus.DENY: "risk_check_deny",
        RiskCheckStatus.BLOCKED: "risk_check_blocked",
        RiskCheckStatus.FAILED: "risk_check_failed",
    }[status]
    alert_id = record_risk_check_alert(
        event_type=event_type,
        business_request_key=result.business_request_key,
        trace_id=trace_id,
        trigger_source=trigger_source,
        status=status,
        reason_code=reason_code,
        message=message,
        risk_check_result_id=result.id,
        payload_summary={
            "order_plan_id": result.order_plan_id,
            "primary_candidate_order_intent_id": result.primary_candidate_order_intent_id,
            "selected_candidate_order_intent_id": result.selected_candidate_order_intent_id,
        },
    )
    if alert_id is not None:
        alert_ids.append(alert_id)
    if fallback_selected:
        fallback_alert = record_risk_check_alert(
            event_type="fallback_reduce_only_selected",
            business_request_key=result.business_request_key,
            trace_id=trace_id,
            trigger_source=trigger_source,
            status=status,
            reason_code="fallback_reduce_only_selected",
            message="完整反手未获批准，风控仅批准 OrderPlan 预生成的只减仓后备意图。",
            risk_check_result_id=result.id,
            payload_summary={"fallback_candidate_order_intent_id": result.selected_candidate_order_intent_id},
        )
        if fallback_alert is not None:
            alert_ids.append(fallback_alert)
    if approved is not None:
        approved_alert = record_risk_check_alert(
            event_type="approved_order_intent_generated",
            business_request_key=result.business_request_key,
            trace_id=trace_id,
            trigger_source=trigger_source,
            status=status,
            reason_code="approved_order_intent_generated",
            message="RiskCheck 已生成不可直接提交的 ApprovedOrderIntent，等待 ExecutionPreparation。",
            risk_check_result_id=result.id,
            payload_summary={"approved_order_intent_id": approved.id},
        )
        if approved_alert is not None:
            alert_ids.append(approved_alert)
    if status != RiskCheckStatus.ALLOW:
        release_for_pre_execution_stop(
            active_lock_id=result.active_lock_id,
            order_plan_id=result.order_plan_id,
            source_module="RiskCheck",
            source_object_id=result.id,
            reason_code=f"risk_check_{status.lower()}",
            evidence={"risk_check_result_id": result.id, "risk_check_status": status},
            trace_id=trace_id,
            trigger_source=trigger_source,
        )
    if alert_ids:
        RiskCheckResult.objects.filter(id=result.id).update(alert_event_ids=alert_ids)


def _persist_rule_results(result: RiskCheckResult, evaluations: list) -> dict[int, RiskRuleResult]:
    persisted = {}
    definitions = {
        item.definition_hash: item
        for item in RiskRuleDefinition.objects.filter(definition_hash__in={evaluation.definition_hash for evaluation in evaluations})
    }
    for evaluation in evaluations:
        definition = definitions.get(evaluation.definition_hash)
        if definition is None:
            continue
        persisted[id(evaluation)] = RiskRuleResult.objects.create(
            risk_check_result=result,
            rule_definition=definition,
            rule_code=evaluation.rule_code,
            rule_version=evaluation.rule_version,
            status=evaluation.status,
            severity=evaluation.severity,
            reason_code=evaluation.reason_code,
            message_zh=evaluation.message_zh,
            risk_measures=evaluation.risk_measures,
            evidence=evaluation.evidence,
            definition_hash=evaluation.definition_hash,
            params_hash=evaluation.params_hash,
            started_at_utc=evaluation.started_at_utc,
            finished_at_utc=evaluation.finished_at_utc,
        )
    return persisted


def _persist_issues(result: RiskCheckResult, rule_results: dict[int, RiskRuleResult], evaluations: list) -> None:
    for evaluation in evaluations:
        if evaluation.status == RiskRuleResultStatus.PASS:
            continue
        RiskCheckIssue.objects.create(
            risk_check_result=result,
            rule_result=rule_results.get(id(evaluation)),
            issue_code=evaluation.reason_code,
            severity=evaluation.severity,
            message_zh=evaluation.message_zh,
            evidence=evaluation.evidence,
        )


def _create_approved_order_intent(
    *,
    result: RiskCheckResult,
    context: RiskCheckContext,
    config: dict[str, Any],
    rule_set_hash_value: str,
    reference_time_utc: datetime,
    trace_id: str,
    trigger_source: str,
) -> ApprovedOrderIntent:
    candidate = context.candidate
    expires_at = reference_time_utc + timedelta(seconds=int(config["approved_intent_ttl_seconds"]))
    risk_hash = risk_check_result_hash(
        {
            "risk_check_result_id": result.id,
            "risk_check_key": result.risk_check_key,
            "status": result.status,
            "selected_candidate_order_intent_id": candidate.id,
            "rule_set_hash": rule_set_hash_value,
            "candidate_intent_hash": candidate.intent_hash,
        }
    )
    approved_hash = approved_order_intent_hash(
        {
            "risk_check_hash": risk_hash,
            "candidate_intent_hash": candidate.intent_hash,
            "side": candidate.side,
            "requested_size": str(candidate.requested_size),
            "exchange_reduce_only": candidate.exchange_reduce_only,
            "order_type": candidate.order_type,
            "time_in_force": candidate.time_in_force,
            "limit_price": str(candidate.limit_price) if candidate.limit_price is not None else "",
            "limit_valid_until_utc": candidate.limit_valid_until_utc.isoformat() if candidate.limit_valid_until_utc else "",
            "price_condition_hash": candidate.price_condition_hash,
            "expires_at_utc": expires_at.isoformat(),
        }
    )
    return ApprovedOrderIntent.objects.create(
        business_request_key=result.business_request_key,
        risk_check_result=result,
        candidate_order_intent=candidate,
        order_plan=context.order_plan,
        binance_sync_run=context.sync_run,
        price_snapshot=context.price_snapshot,
        active_lock=context.active_lock,
        exchange=context.order_plan.exchange,
        market_type=candidate.market_type,
        account_domain=candidate.account_domain,
        symbol=candidate.symbol,
        side=candidate.side,
        position_side=candidate.position_side,
        order_type=candidate.order_type,
        time_in_force=candidate.time_in_force,
        limit_price=candidate.limit_price,
        limit_valid_until_utc=candidate.limit_valid_until_utc,
        price_condition_hash=candidate.price_condition_hash,
        price_condition_evidence=candidate.price_condition_evidence,
        exchange_reduce_only=candidate.exchange_reduce_only,
        requested_size=candidate.requested_size,
        requested_notional=candidate.requested_notional,
        requested_size_unit=candidate.requested_size_unit,
        selected_intent_role=candidate.intent_role,
        order_components=candidate.order_components,
        candidate_intent_hash=candidate.intent_hash,
        risk_check_hash=risk_hash,
        rule_set_hash=rule_set_hash_value,
        price_snapshot_hash=context.price_snapshot.price_snapshot_hash,
        binance_snapshot_set_hash=context.sync_run.snapshot_set_hash,
        status=ApprovedOrderIntentStatus.APPROVED,
        expires_at_utc=expires_at,
        evidence={
            "risk_check_result_id": result.id,
            "approved_order_intent_hash": approved_hash,
            "risk_measures": result.risk_measures,
        },
        trace_id=trace_id,
        trigger_source=trigger_source,
    )


def _mark_candidates_not_approved(*, loaded: RiskCheckLoadedContext, status: str, reason_code: str) -> None:
    target_status = CandidateIntentStatus.DENIED if status == RiskCheckStatus.DENY else CandidateIntentStatus.BLOCKED
    for candidate in [loaded.primary_candidate, loaded.fallback_candidate]:
        if candidate is None or candidate.status != CandidateIntentStatus.PENDING_RISK_CHECK:
            continue
        candidate.status = target_status
        candidate.reason_code = reason_code
        candidate.save(update_fields=["status", "reason_code"])


def _should_attempt_fallback(context: RiskCheckContext, summary: RuleEngineSummary) -> bool:
    if summary.final_status == RiskCheckStatus.ALLOW or summary.final_status == RiskCheckStatus.FAILED:
        return False
    if context.fallback_candidate is None or not context.has_increase_risk_component:
        return False
    non_pass = [item for item in summary.evaluations if item.status != RiskRuleResultStatus.PASS]
    return bool(non_pass) and all(item.evidence.get("fallback_can_be_checked") for item in non_pass)


def _risk_measures(context: RiskCheckContext) -> dict[str, Any]:
    opening = context.candidate.opening_size
    leverage = context.position_snapshot.observed_exchange_leverage
    margin_required = ""
    if leverage and leverage > 0 and opening > 0:
        if context.order_plan.market_type == "usds_m_futures":
            margin_required = str((opening * context.price_snapshot.mark_price) / leverage)
        elif context.symbol_rule_snapshot.contract_size and context.price_snapshot.mark_price > 0:
            margin_required = str((opening * context.symbol_rule_snapshot.contract_size) / context.price_snapshot.mark_price / leverage)
    measures = {
        "current_equity": str(context.order_plan.current_equity),
        "available_balance": str(context.balance_snapshot.available_balance) if context.balance_snapshot.available_balance is not None else "",
        "order_notional": str(context.candidate.requested_notional),
        "requested_size": str(context.candidate.requested_size),
        "margin_required_total": margin_required,
        "margin_required_by_component": [],
        "observed_exchange_leverage": str(leverage) if leverage is not None else "",
        "estimated_leverage_after_order": "",
        "is_risk_reducing_total": context.is_risk_reducing_total,
        "has_increase_risk_component": context.has_increase_risk_component,
        "price_snapshot_id": context.price_snapshot.id,
        "mark_price": str(context.price_snapshot.mark_price),
        "market_type": context.order_plan.market_type,
        "margin_asset": context.symbol_rule_snapshot.margin_asset or context.symbol_rule_snapshot.settlement_asset,
    }
    if context.order_plan.market_type == "coin_m_futures":
        measures.update(
            {
                "contract_size": str(context.symbol_rule_snapshot.contract_size or ""),
                "current_equity_native": str(context.order_plan.current_equity),
                "current_equity_usd": str(context.order_plan.current_equity * context.price_snapshot.mark_price),
                "margin_required_native": margin_required,
                "available_balance_native": str(context.balance_snapshot.available_balance) if context.balance_snapshot.available_balance is not None else "",
            }
        )
    return measures


def _input_snapshot(loaded: RiskCheckLoadedContext) -> dict[str, Any]:
    return {
        "order_plan_id": loaded.order_plan.id,
        "primary_candidate_order_intent_id": loaded.primary_candidate.id,
        "fallback_candidate_order_intent_id": loaded.fallback_candidate.id if loaded.fallback_candidate else None,
        "binance_sync_run_id": loaded.sync_run.id,
        "price_snapshot_id": loaded.price_snapshot.id,
        "active_lock_id": loaded.active_lock.id,
        "snapshot_set_hash": loaded.sync_run.snapshot_set_hash,
        "price_snapshot_hash": loaded.price_snapshot.price_snapshot_hash,
    }


def _evaluation_summary(evaluation) -> dict[str, Any]:
    return {
        "rule_code": evaluation.rule_code,
        "rule_version": evaluation.rule_version,
        "status": str(evaluation.status),
        "reason_code": evaluation.reason_code,
        "message_zh": evaluation.message_zh,
        "evidence": evaluation.evidence,
    }


def _with_candidate_role(evaluation, role: str):
    return SimpleNamespace(
        rule_code=evaluation.rule_code,
        rule_version=evaluation.rule_version,
        status=evaluation.status,
        severity=evaluation.severity,
        reason_code=evaluation.reason_code,
        message_zh=evaluation.message_zh,
        risk_measures=evaluation.risk_measures,
        evidence={**evaluation.evidence, "candidate_role": role},
        definition_hash=evaluation.definition_hash,
        params_hash=evaluation.params_hash,
        started_at_utc=evaluation.started_at_utc,
        finished_at_utc=evaluation.finished_at_utc,
    )


def _risk_check_key(
    *,
    business_request_key: str,
    loaded: RiskCheckLoadedContext,
    rule_set_hash_value: str,
    config: dict[str, Any],
) -> str:
    return risk_check_key_hash(
        {
            "business_request_key": business_request_key,
            "candidate_order_intent_id": loaded.primary_candidate.id,
            "candidate_intent_hash": loaded.primary_candidate.intent_hash,
            "order_plan_id": loaded.order_plan.id,
            "binance_sync_run_id": loaded.sync_run.id,
            "binance_snapshot_set_hash": loaded.sync_run.snapshot_set_hash,
            "price_snapshot_id": loaded.price_snapshot.id,
            "price_snapshot_hash": loaded.price_snapshot.price_snapshot_hash,
            "rule_set_hash": rule_set_hash_value,
            "risk_config_hash": config["risk_config_hash"],
        }
    )[:191]


def _price_integrity_reason(price: PriceSnapshot) -> str:
    payload = price_snapshot_hash_payload(
        business_request_key=price.business_request_key,
        exchange=price.exchange,
        market_type=price.market_type,
        account_domain=price.account_domain,
        symbol=price.symbol,
        price_type=price.price_type,
        mark_price=price.mark_price,
        price_unit=price.price_unit,
        source=price.source,
        source_operation=price.source_operation,
        source_update_time_utc=price.source_update_time_utc,
        as_of_utc=price.as_of_utc,
        expires_at_utc=price.expires_at_utc,
    )
    if compute_price_snapshot_hash(payload) != price.price_snapshot_hash:
        return "price_snapshot_hash_mismatch"
    return ""


def _load_config(*, risk_rule_set: str | None) -> tuple[dict[str, Any], str]:
    if not getattr(settings, "RISK_CHECK_ENABLED", False):
        return {}, "risk_check_disabled"
    rule_set = (risk_rule_set or getattr(settings, "RISK_CHECK_RULE_SET", "")).strip()
    buffer_ratio = getattr(settings, "RISK_CHECK_MARGIN_BUFFER_RATIO", None)
    ttl = getattr(settings, "RISK_CHECK_APPROVED_INTENT_TTL_SECONDS", None)
    failure_mode = getattr(settings, "RISK_CHECK_RULE_FAILURE_MODE", "")
    if not rule_set or not isinstance(buffer_ratio, Decimal) or buffer_ratio < 0 or not isinstance(ttl, int) or ttl <= 0 or failure_mode != "fail_closed":
        return {}, "risk_check_config_invalid"
    config = {
        "schema_version": "1.0",
        "risk_rule_set": rule_set,
        "margin_buffer_ratio": str(buffer_ratio),
        "rule_failure_mode": failure_mode,
        "approved_intent_ttl_seconds": ttl,
    }
    config["risk_config_hash"] = stable_hash(config)
    return config, ""


def _virtual_builtin_definitions(rule_set_code: str):
    definitions = []
    for order, rule_code in enumerate(BUILTIN_RULE_CODES, start=10):
        params_hash = stable_hash({})
        definitions.append(
            SimpleNamespace(
                risk_rule_set_id=None,
                rule_code=rule_code,
                rule_version="1.0",
                algorithm_name=rule_code,
                algorithm_version="1.0",
                params={},
                params_hash=params_hash,
                definition_hash=stable_hash({"rule_set_code": rule_set_code, "rule_code": rule_code, "rule_version": "1.0"}),
                status="active",
                enabled=True,
                severity="warning",
                execution_order=order,
                applicable_market_types=["usds_m_futures", "coin_m_futures"],
            )
        )
    rule_set_value = risk_rule_set_hash(
        {
            "rule_set_code": rule_set_code,
            "definitions": [
                {
                    "rule_code": item.rule_code,
                    "rule_version": item.rule_version,
                    "definition_hash": item.definition_hash,
                    "params_hash": item.params_hash,
                    "execution_order": item.execution_order,
                }
                for item in definitions
            ],
        }
    )
    return definitions, rule_set_value


def _request_error(**values: Any) -> str:
    key = values["business_request_key"]
    if not isinstance(key, str) or not key.strip() or len(key) > 191:
        return "business_request_key_invalid"
    for field_name in ("order_plan_id", "candidate_order_intent_id", "binance_sync_run_id", "price_snapshot_id", "active_lock_id"):
        if not isinstance(values[field_name], int) or values[field_name] <= 0:
            return f"{field_name}_invalid"
    reference_time = values["reference_time_utc"]
    if not isinstance(reference_time, datetime) or reference_time.tzinfo is None:
        return "reference_time_utc_invalid"
    if not values["trace_id"] or not values["trigger_source"]:
        return "trace_context_required"
    return ""


def _blocked_without_result(reason_code: str, message: str, business_request_key: str, trace_id: str, trigger_source: str) -> ServiceResult:
    record_risk_check_alert(
        event_type="risk_check_blocked",
        business_request_key=business_request_key or "invalid-risk-check-request",
        trace_id=trace_id,
        trigger_source=trigger_source,
        status=RiskCheckStatus.BLOCKED,
        reason_code=reason_code,
        message=message,
    )
    return ServiceResult(ResultStatus.BLOCKED, reason_code, message, trace_id, trigger_source, _empty_result_data())


def _failed_without_result(business_request_key: str, trace_id: str, trigger_source: str, error_type: str) -> ServiceResult:
    record_risk_check_alert(
        event_type="risk_check_failed",
        business_request_key=business_request_key or "invalid-risk-check-request",
        trace_id=trace_id,
        trigger_source=trigger_source,
        status=RiskCheckStatus.FAILED,
        reason_code="risk_check_failed",
        message="RiskCheck 数据库或系统异常，未形成可供下游消费的审批结果。",
        payload_summary={"error_type": error_type},
    )
    return ServiceResult(ResultStatus.FAILED, "risk_check_failed", "RiskCheck 失败", trace_id, trigger_source, _empty_result_data())


def _result_from_risk_check(result: RiskCheckResult, *, trace_id: str, trigger_source: str) -> ServiceResult:
    approved = getattr(result, "approved_order_intent", None) if result.status == RiskCheckStatus.ALLOW else None
    return ServiceResult(
        _service_status(result.status),
        result.reason_code,
        "RiskCheck 已完成",
        trace_id,
        trigger_source,
        {
            "risk_check_result_id": result.id,
            "risk_check_status": result.status,
            "allows_downstream": result.allows_downstream,
            "selected_candidate_order_intent_id": result.selected_candidate_order_intent_id,
            "selected_intent_role": result.selected_intent_role,
            "approved_order_intent_id": approved.id if approved is not None else None,
            "order_plan_id": result.order_plan_id,
            "active_lock_id": result.active_lock_id,
            "flow_action": "CONTINUE" if result.allows_downstream else "STOP",
        },
    )


def _service_status(status: str) -> ResultStatus:
    if status == RiskCheckStatus.ALLOW:
        return ResultStatus.SUCCEEDED
    if status == RiskCheckStatus.DENY:
        return ResultStatus.DENIED
    if status == RiskCheckStatus.BLOCKED:
        return ResultStatus.BLOCKED
    return ResultStatus.FAILED


def _empty_result_data() -> dict[str, Any]:
    return {
        "risk_check_result_id": None,
        "approved_order_intent_id": None,
        "selected_candidate_order_intent_id": None,
        "allows_downstream": False,
        "flow_action": "STOP",
    }
