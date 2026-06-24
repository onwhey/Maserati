"""StrategyRouting 模块：由 MarketRegimeSnapshot 生成 StrategyRouteDecision。

负责：读取冻结 Policy、Rule 与 StrategyDefinition，执行固定条件匹配，写 StrategyRouteDecision 和必要 AlertEvent。
不负责：执行策略 calculator、计算策略方向/权重/仓位、访问 Redis 或外部服务、发送 Hermes、交易执行或真实交易。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from time import perf_counter
from typing import Any

from django.conf import settings
from django.core.exceptions import ObjectDoesNotExist
from django.db import DataError, DatabaseError, IntegrityError, transaction
from django.utils import timezone

from apps.alerts.models import AlertSeverity
from apps.alerts.services import record_alert_event
from apps.foundation.idempotency import build_idempotency_key
from apps.foundation.results import ResultStatus, ServiceResult
from apps.strategy_calculator.contracts import CalculatorType
from apps.strategy_calculator.errors import StrategyCalculatorError
from apps.strategy_calculator.registry import CalculatorRegistry, default_registry
from apps.strategy_calculator.utils import stable_hash

from ..definition_hashes import (
    STRATEGY_ROUTE_CONDITION_SCHEMA_VERSION,
    normalize_domain_codes,
    normalize_route_conditions,
    strategy_definition_dependency_hash,
    strategy_definition_hash,
    strategy_route_policy_hash,
    strategy_route_rule_hash,
    strategy_route_rule_set_hash,
)
from ..models import (
    AnalysisObjectStatus,
    DefinitionLifecycleStatus,
    MarketRegimeSnapshot,
    ReleaseItemComponentType,
    StrategyDefinition,
    StrategyRouteAction,
    StrategyRouteDecision,
    StrategyRouteFallbackPolicy,
    StrategyRouteOutcome,
    StrategyRoutePolicy,
    StrategyRouteRule,
)
from .release import FrozenReleaseSlice, resolve_frozen_slice


logger = logging.getLogger(__name__)


class RoutingDataError(ValueError):
    """表示冻结输入不满足路由数据合同。"""


@dataclass(frozen=True)
class RoutingContext:
    policy_slice: FrozenReleaseSlice
    rule_slice: FrozenReleaseSlice
    strategy_slice: FrozenReleaseSlice
    policy: StrategyRoutePolicy
    rules: tuple[StrategyRouteRule, ...]
    normalized_conditions: dict[int, dict[str, Any]]
    strategies: dict[int, StrategyDefinition]


@dataclass(frozen=True)
class RouteDraft:
    status: str
    route_outcome: str
    matched_rule: StrategyRouteRule | None
    selected_strategy: StrategyDefinition | None
    fallback_used: bool
    fallback_reason: str
    is_usable: bool
    allows_strategy_signal: bool
    matched_conditions: dict[str, Any]
    selection_reason: str
    evidence_items: list[dict[str, Any]]
    evidence_text_zh: str
    payload_summary: dict[str, Any]
    error_code: str = ""
    error_message: str = ""
    latency_ms: int = 0


def _result_with_alert(
    *,
    status: ResultStatus,
    reason_code: str,
    message: str,
    business_request_key: str,
    trace_id: str,
    trigger_source: str,
    dry_run: bool,
    payload_summary: dict[str, Any] | None = None,
) -> ServiceResult:
    data = dict(payload_summary or {})
    data.update(
        {
            "strategy_route_decision_id": None,
            "strategy_route_decision_key": None,
            "matched_route_rule_id": None,
            "route_outcome": "",
            "selected_strategy_definition_id": None,
            "fallback_used": False,
            "is_usable": False,
            "allows_strategy_signal": False,
            "error_code": reason_code,
            "error_message": message,
            "persisted": False,
        }
    )
    if not dry_run:
        event_type = "strategy_routing_blocked"
        severity = AlertSeverity.WARNING
        if status == ResultStatus.FAILED:
            event_type = "strategy_routing_failed"
            severity = AlertSeverity.HIGH
        elif status == ResultStatus.UNKNOWN:
            event_type = "strategy_routing_unknown"
            severity = AlertSeverity.HIGH
        try:
            record_alert_event(
                event_key=build_idempotency_key(event_type, business_request_key, reason_code),
                source_module="StrategyRouting",
                event_type=event_type,
                event_category="strategy_analysis",
                severity=severity,
                title_zh=f"StrategyRouting：{reason_code}",
                message_zh=message,
                trace_id=trace_id,
                trigger_source=trigger_source,
                business_status=status.value,
                reason_code=reason_code,
                payload_summary=data,
            )
        except DatabaseError:
            logger.exception("StrategyRouting AlertEvent 写入失败 reason_code=%s trace_id=%s", reason_code, trace_id)
    return ServiceResult(status, reason_code, message, trace_id, trigger_source, data)


def _validate_request(
    *,
    market_regime_snapshot_id: int,
    strategy_analysis_release_id: int,
    strategy_analysis_release_hash: str,
    business_request_key: str,
    trace_id: str,
    trigger_source: str,
) -> tuple[str, str]:
    if market_regime_snapshot_id <= 0 or strategy_analysis_release_id <= 0:
        return "strategy_routing_request_invalid", "MarketRegimeSnapshot 和版本包 ID 必须是正整数"
    required = {
        "strategy_analysis_release_hash": strategy_analysis_release_hash,
        "business_request_key": business_request_key,
        "trace_id": trace_id,
        "trigger_source": trigger_source,
    }
    missing = [name for name, value in required.items() if not str(value).strip()]
    if missing:
        return "strategy_routing_request_invalid", f"StrategyRouting 请求缺少必要字段：{','.join(missing)}"
    return "", ""


def _load_regime_snapshot(
    *,
    snapshot_id: int,
    release_id: int,
    release_hash: str,
) -> tuple[MarketRegimeSnapshot | None, str]:
    snapshot = MarketRegimeSnapshot.objects.select_related(
        "market_regime_definition",
        "strategy_analysis_release",
    ).filter(id=snapshot_id).first()
    if snapshot is None:
        return None, "market_regime_snapshot_not_found"
    if (
        snapshot.status != AnalysisObjectStatus.CREATED
        or not snapshot.is_usable
        or not snapshot.allows_strategy_routing
    ):
        return None, "market_regime_snapshot_not_usable"
    if snapshot.strategy_analysis_release_id != release_id or snapshot.release_hash != release_hash:
        return None, "strategy_routing_release_mismatch"
    definition = snapshot.market_regime_definition
    if definition.status != DefinitionLifecycleStatus.ACTIVE or not definition.enabled:
        return None, "market_regime_definition_not_selectable"
    return snapshot, ""


def _strategy_identity_valid(definition: StrategyDefinition, item: Any) -> bool:
    try:
        allowed = normalize_domain_codes(definition.allowed_domain_codes)
        required = normalize_domain_codes(definition.required_domain_codes, allow_empty=True)
        params_hash = stable_hash(definition.params)
        definition_hash = strategy_definition_hash(
            strategy_code=definition.strategy_code,
            strategy_version=definition.strategy_version,
            algorithm_name=definition.algorithm_name,
            algorithm_version=definition.algorithm_version,
            input_schema_version=definition.input_schema_version,
            output_schema_version=definition.output_schema_version,
            params_hash=params_hash,
            allowed_domain_codes=allowed,
            required_domain_codes=required,
            uses_input_weights=definition.uses_input_weights,
            domain_input_weights=definition.domain_input_weights,
            prediction_horizon=definition.prediction_horizon,
        )
        dependency_hash = strategy_definition_dependency_hash(
            {"allowed_domain_codes": list(allowed), "required_domain_codes": list(required)}
        )
        item_dependency_hash = strategy_definition_dependency_hash(item.payload_summary or {})
    except ValueError:
        return False
    return (
        item.component_code == definition.strategy_code
        and item.algorithm_name == definition.algorithm_name
        and item.algorithm_version == definition.algorithm_version
        and definition.params_hash == params_hash
        and item.params_hash == params_hash
        and definition.definition_hash == definition_hash
        and item.definition_hash == definition_hash
        and item.dependency_hash == dependency_hash
        and item.dependency_hash == item_dependency_hash
    )


def _load_strategy_slice(
    *,
    release_id: int,
    release_hash: str,
    expected_definition_set_hash: str,
) -> tuple[FrozenReleaseSlice | None, dict[int, StrategyDefinition] | None, str]:
    try:
        strategy_slice = resolve_frozen_slice(
            release_id=release_id,
            release_hash=release_hash,
            component_type=ReleaseItemComponentType.STRATEGY_DEFINITION,
            expected_definition_set_hash=expected_definition_set_hash,
        )
    except (ObjectDoesNotExist, ValueError):
        return None, None, "strategy_definition_slice_invalid"
    if not strategy_slice.items or any(item.component_object_id is None for item in strategy_slice.items):
        return None, None, "strategy_definition_slice_empty"
    definitions = {
        definition.id: definition
        for definition in StrategyDefinition.objects.filter(
            id__in=[item.component_object_id for item in strategy_slice.items]
        )
    }
    if len(definitions) != len(strategy_slice.items):
        return None, None, "strategy_definition_missing"
    release_domain_codes = set(
        strategy_slice.release.items.filter(
            component_type=ReleaseItemComponentType.DOMAIN_SIGNAL_DEFINITION
        ).values_list("component_code", flat=True)
    )
    for item in strategy_slice.items:
        definition = definitions.get(item.component_object_id)
        if definition is None or not _strategy_identity_valid(definition, item):
            return None, None, "strategy_definition_identity_mismatch"
        try:
            allowed_domains = set(normalize_domain_codes(definition.allowed_domain_codes))
        except ValueError:
            return None, None, "strategy_definition_domain_membership_invalid"
        if not allowed_domains.issubset(release_domain_codes):
            return None, None, "strategy_definition_domain_membership_invalid"
    return strategy_slice, definitions, ""


def _rule_identity(
    rule: StrategyRouteRule,
    *,
    allowed_regime_codes: list[str],
) -> tuple[dict[str, Any], str]:
    conditions = normalize_route_conditions(rule.match_conditions, allowed_regime_codes=allowed_regime_codes)
    rule_hash = strategy_route_rule_hash(
        policy_id=rule.strategy_route_policy_id,
        rule_code=rule.rule_code,
        priority=rule.priority,
        action=rule.action,
        match_conditions=conditions,
        selected_strategy_definition_id=rule.selected_strategy_definition_id,
        valid_from_utc=rule.valid_from_utc,
        valid_to_utc=rule.valid_to_utc,
        allowed_regime_codes=allowed_regime_codes,
    )
    return conditions, rule_hash


def _load_policy_and_rules(
    *,
    release_id: int,
    release_hash: str,
    expected_policy_hash: str,
    allowed_regime_codes: list[str],
    strategy_ids: set[int],
) -> tuple[FrozenReleaseSlice | None, FrozenReleaseSlice | None, StrategyRoutePolicy | None, tuple[StrategyRouteRule, ...] | None, dict[int, dict[str, Any]] | None, str]:
    try:
        policy_slice = resolve_frozen_slice(
            release_id=release_id,
            release_hash=release_hash,
            component_type=ReleaseItemComponentType.STRATEGY_ROUTE_POLICY,
        )
        rule_slice = resolve_frozen_slice(
            release_id=release_id,
            release_hash=release_hash,
            component_type=ReleaseItemComponentType.STRATEGY_ROUTE_RULE,
        )
    except (ObjectDoesNotExist, ValueError):
        return None, None, None, None, None, "strategy_route_release_slice_invalid"
    if len(policy_slice.items) != 1 or not rule_slice.items:
        return None, None, None, None, None, "strategy_route_policy_unavailable"
    policy_item = policy_slice.items[0]
    if policy_item.component_object_id is None:
        return None, None, None, None, None, "strategy_route_policy_object_missing"
    policy = StrategyRoutePolicy.objects.filter(id=policy_item.component_object_id).first()
    if policy is None or policy.status != DefinitionLifecycleStatus.ACTIVE or not policy.enabled:
        return None, None, None, None, None, "strategy_route_policy_not_selectable"
    if policy.condition_schema_version != STRATEGY_ROUTE_CONDITION_SCHEMA_VERSION:
        return None, None, None, None, None, "strategy_route_condition_schema_unsupported"
    rule_ids = [item.component_object_id for item in rule_slice.items if item.component_object_id is not None]
    if len(rule_ids) != len(rule_slice.items):
        return None, None, None, None, None, "strategy_route_rule_object_missing"
    rules_by_id = {
        rule.id: rule
        for rule in StrategyRouteRule.objects.select_related("selected_strategy_definition").filter(id__in=rule_ids)
    }
    if len(rules_by_id) != len(rule_slice.items):
        return None, None, None, None, None, "strategy_route_rule_missing"
    if set(policy.rules.values_list("id", flat=True)) != set(rule_ids):
        return None, None, None, None, None, "strategy_route_rule_set_mismatch"
    conditions_by_id: dict[int, dict[str, Any]] = {}
    rules: list[StrategyRouteRule] = []
    rule_payloads: list[dict[str, Any]] = []
    try:
        for item in rule_slice.items:
            rule = rules_by_id[item.component_object_id]
            if rule.strategy_route_policy_id != policy.id:
                return None, None, None, None, None, "strategy_route_rule_policy_mismatch"
            if rule.status != DefinitionLifecycleStatus.ACTIVE or not rule.enabled:
                return None, None, None, None, None, "strategy_route_rule_not_selectable"
            conditions, rule_hash = _rule_identity(rule, allowed_regime_codes=allowed_regime_codes)
            if item.component_code != rule.rule_code or item.definition_hash != rule_hash or rule.rule_hash != rule_hash:
                return None, None, None, None, None, "strategy_route_rule_identity_mismatch"
            if rule.selected_strategy_definition_id is not None and rule.selected_strategy_definition_id not in strategy_ids:
                return None, None, None, None, None, "strategy_route_rule_target_outside_release"
            conditions_by_id[rule.id] = conditions
            rules.append(rule)
            rule_payloads.append(
                {"rule_id": rule.id, "rule_code": rule.rule_code, "priority": rule.priority, "rule_hash": rule_hash}
            )
        rule_set_hash = strategy_route_rule_set_hash(rule_payloads)
        policy_hash = strategy_route_policy_hash(
            policy_code=policy.policy_code,
            policy_version=policy.policy_version,
            condition_schema_version=policy.condition_schema_version,
            rule_set_hash=rule_set_hash,
            fallback_policy=policy.fallback_policy,
            fallback_strategy_definition_id=policy.fallback_strategy_definition_id,
        )
    except ValueError:
        return None, None, None, None, None, "strategy_route_configuration_invalid"
    if policy.fallback_strategy_definition_id is not None and policy.fallback_strategy_definition_id not in strategy_ids:
        return None, None, None, None, None, "fallback_strategy_outside_release"
    if (
        policy_item.component_code != policy.policy_code
        or policy.rule_set_hash != rule_set_hash
        or policy_item.dependency_hash != rule_set_hash
        or policy.definition_hash != policy_hash
        or policy_item.definition_hash != policy_hash
        or (expected_policy_hash and policy_hash != expected_policy_hash)
    ):
        return None, None, None, None, None, "strategy_route_policy_identity_mismatch"
    return policy_slice, rule_slice, policy, tuple(rules), conditions_by_id, ""


def _load_routing_context(
    *,
    snapshot: MarketRegimeSnapshot,
    release_id: int,
    release_hash: str,
    expected_policy_hash: str,
    expected_strategy_definition_set_hash: str,
) -> tuple[RoutingContext | None, str]:
    strategy_slice, strategies, error = _load_strategy_slice(
        release_id=release_id,
        release_hash=release_hash,
        expected_definition_set_hash=expected_strategy_definition_set_hash,
    )
    if error or strategy_slice is None or strategies is None:
        return None, error
    result = _load_policy_and_rules(
        release_id=release_id,
        release_hash=release_hash,
        expected_policy_hash=expected_policy_hash,
        allowed_regime_codes=list(snapshot.market_regime_definition.allowed_regime_codes),
        strategy_ids=set(strategies),
    )
    policy_slice, rule_slice, policy, rules, conditions, error = result
    if error or policy_slice is None or rule_slice is None or policy is None or rules is None or conditions is None:
        return None, error
    return RoutingContext(policy_slice, rule_slice, strategy_slice, policy, rules, conditions, strategies), ""


def _decimal(value: Any, *, field_name: str) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise RoutingDataError(f"{field_name} 不是合法 Decimal") from exc
    if not result.is_finite():
        raise RoutingDataError(f"{field_name} 必须是有限数值")
    return result


def _match_rule(
    *,
    rule: StrategyRouteRule,
    conditions: dict[str, Any],
    snapshot: MarketRegimeSnapshot,
) -> tuple[bool, dict[str, Any]]:
    evidence: dict[str, Any] = {
        "rule_id": rule.id,
        "rule_code": rule.rule_code,
        "rule_hash": rule.rule_hash,
        "rule_status": rule.status,
        "rule_enabled": rule.enabled,
        "priority": rule.priority,
        "action": rule.action,
        "valid_from_utc": rule.valid_from_utc.isoformat() if rule.valid_from_utc else None,
        "valid_to_utc": rule.valid_to_utc.isoformat() if rule.valid_to_utc else None,
        "checks": [],
    }
    if rule.valid_from_utc is not None and snapshot.analysis_close_time_utc < rule.valid_from_utc:
        evidence["checks"].append({"condition": "valid_from_utc", "matched": False})
        return False, evidence
    if rule.valid_to_utc is not None and snapshot.analysis_close_time_utc >= rule.valid_to_utc:
        evidence["checks"].append({"condition": "valid_to_utc", "matched": False})
        return False, evidence
    if "regime_codes" in conditions:
        matched = snapshot.regime_code in conditions["regime_codes"]
        evidence["checks"].append({"condition": "regime_codes", "actual": snapshot.regime_code, "matched": matched})
        if not matched:
            return False, evidence
    if "minimum_regime_confidence" in conditions:
        if snapshot.regime_confidence is None:
            raise RoutingDataError("MarketRegimeSnapshot 缺少 regime_confidence")
        threshold = _decimal(conditions["minimum_regime_confidence"], field_name="minimum_regime_confidence")
        matched = snapshot.regime_confidence >= threshold
        evidence["checks"].append(
            {"condition": "minimum_regime_confidence", "actual": str(snapshot.regime_confidence), "threshold": str(threshold), "matched": matched}
        )
        if not matched:
            return False, evidence
    if "minimum_classification_margin" in conditions:
        if snapshot.classification_margin is None:
            raise RoutingDataError("MarketRegimeSnapshot 缺少 classification_margin")
        threshold = _decimal(conditions["minimum_classification_margin"], field_name="minimum_classification_margin")
        matched = snapshot.classification_margin >= threshold
        evidence["checks"].append(
            {"condition": "minimum_classification_margin", "actual": str(snapshot.classification_margin), "threshold": str(threshold), "matched": matched}
        )
        if not matched:
            return False, evidence
    for code, raw_threshold in conditions.get("regime_score_thresholds", {}).items():
        if code not in snapshot.regime_scores:
            raise RoutingDataError(f"MarketRegimeSnapshot 缺少环境评分：{code}")
        score = _decimal(snapshot.regime_scores[code], field_name=f"regime_scores.{code}")
        threshold = _decimal(raw_threshold, field_name=f"regime_score_thresholds.{code}")
        matched = score >= threshold
        evidence["checks"].append(
            {"condition": f"regime_score_thresholds.{code}", "actual": str(score), "threshold": str(threshold), "matched": matched}
        )
        if not matched:
            return False, evidence
    evidence["matched"] = True
    return True, evidence


def _strategy_executable(
    definition: StrategyDefinition,
    *,
    registry: CalculatorRegistry,
) -> tuple[bool, str]:
    if definition.status != DefinitionLifecycleStatus.ACTIVE or not definition.enabled:
        return False, "strategy_definition_not_selectable"
    try:
        calculator = registry.resolve(
            calculator_type=CalculatorType.STRATEGY_SIGNAL,
            algorithm_name=definition.algorithm_name,
            algorithm_version=definition.algorithm_version,
        )
    except StrategyCalculatorError:
        return False, "strategy_calculator_missing"
    if (
        calculator.metadata.input_schema_version != definition.input_schema_version
        or calculator.metadata.output_schema_version != definition.output_schema_version
        or calculator.metadata.uses_input_weights != definition.uses_input_weights
    ):
        return False, "strategy_calculator_contract_mismatch"
    return True, ""


def _created_draft(
    *,
    context: RoutingContext,
    matched_rule: StrategyRouteRule,
    matched_conditions: dict[str, Any],
    registry: CalculatorRegistry,
    latency_ms: int,
) -> tuple[RouteDraft | None, str]:
    if matched_rule.action == StrategyRouteAction.NO_STRATEGY:
        reason = f"规则 {matched_rule.rule_code} 明确要求本轮不选择策略。"
        return RouteDraft(
            status=AnalysisObjectStatus.CREATED,
            route_outcome=StrategyRouteOutcome.NO_STRATEGY,
            matched_rule=matched_rule,
            selected_strategy=None,
            fallback_used=False,
            fallback_reason="",
            is_usable=True,
            allows_strategy_signal=False,
            matched_conditions=matched_conditions,
            selection_reason=reason,
            evidence_items=[matched_conditions],
            evidence_text_zh=reason,
            payload_summary={"route_outcome": StrategyRouteOutcome.NO_STRATEGY},
            latency_ms=latency_ms,
        ), ""
    primary = context.strategies.get(matched_rule.selected_strategy_definition_id)
    if primary is None:
        return None, "selected_strategy_outside_release"
    executable, unavailable_reason = _strategy_executable(primary, registry=registry)
    selected = primary
    fallback_used = False
    fallback_reason = ""
    if not executable:
        policy = context.policy
        if policy.fallback_policy != StrategyRouteFallbackPolicy.EXPLICIT:
            return None, unavailable_reason
        fallback = context.strategies.get(policy.fallback_strategy_definition_id)
        if fallback is None:
            return None, "fallback_strategy_outside_release"
        fallback_executable, fallback_error = _strategy_executable(fallback, registry=registry)
        if not fallback_executable:
            return None, f"fallback_{fallback_error}"
        selected = fallback
        fallback_used = True
        fallback_reason = f"原策略不可执行：{unavailable_reason}；使用 Policy 明确 fallback。"
    reason = f"规则 {matched_rule.rule_code} 选择策略 {selected.strategy_code} {selected.strategy_version}。"
    return RouteDraft(
        status=AnalysisObjectStatus.CREATED,
        route_outcome=StrategyRouteOutcome.SELECTED,
        matched_rule=matched_rule,
        selected_strategy=selected,
        fallback_used=fallback_used,
        fallback_reason=fallback_reason,
        is_usable=True,
        allows_strategy_signal=True,
        matched_conditions=matched_conditions,
        selection_reason=reason,
        evidence_items=[
            matched_conditions,
            {
                "evidence_type": "strategy_selection",
                "selected_strategy_definition_id": selected.id,
                "fallback_used": fallback_used,
                "fallback_reason": fallback_reason,
            },
        ],
        evidence_text_zh=reason + (f" {fallback_reason}" if fallback_reason else ""),
        payload_summary={
            "route_outcome": StrategyRouteOutcome.SELECTED,
            "selected_strategy_definition_id": selected.id,
            "fallback_used": fallback_used,
        },
        latency_ms=latency_ms,
    ), ""


def _evaluate_route(
    *,
    context: RoutingContext,
    snapshot: MarketRegimeSnapshot,
    registry: CalculatorRegistry,
) -> tuple[RouteDraft | None, str, list[dict[str, Any]]]:
    start = perf_counter()
    matched: list[tuple[StrategyRouteRule, dict[str, Any]]] = []
    all_evidence: list[dict[str, Any]] = []
    for rule in context.rules:
        is_match, evidence = _match_rule(
            rule=rule,
            conditions=context.normalized_conditions[rule.id],
            snapshot=snapshot,
        )
        all_evidence.append(evidence)
        if is_match:
            matched.append((rule, evidence))
    if not matched:
        return None, "strategy_route_no_match", all_evidence
    highest_priority = min(rule.priority for rule, _evidence in matched)
    highest = [(rule, evidence) for rule, evidence in matched if rule.priority == highest_priority]
    if len(highest) != 1:
        return None, "strategy_route_rule_conflict", all_evidence
    rule, evidence = highest[0]
    matched_evidence = {**evidence, "checks": list(evidence.get("checks", [])), "all_rule_evidence": all_evidence}
    draft, error = _created_draft(
        context=context,
        matched_rule=rule,
        matched_conditions=matched_evidence,
        registry=registry,
        latency_ms=int((perf_counter() - start) * 1000),
    )
    return draft, error, all_evidence


def _decision_key(*, snapshot_id: int, schema_version: str, definition_hash: str) -> str:
    return stable_hash(
        {
            "market_regime_snapshot_id": snapshot_id,
            "strategy_route_schema_version": schema_version,
            "definition_hash": definition_hash,
        }
    )


def _persist_decision(
    *,
    snapshot: MarketRegimeSnapshot,
    context: RoutingContext,
    draft: RouteDraft,
    business_request_key: str,
    decision_key: str,
    trace_id: str,
    trigger_source: str,
) -> StrategyRouteDecision:
    return StrategyRouteDecision.objects.create(
        strategy_route_decision_key=decision_key,
        business_request_key=business_request_key,
        market_regime_snapshot=snapshot,
        strategy_route_policy=context.policy,
        strategy_analysis_release=context.policy_slice.release,
        release_hash=context.policy_slice.release.release_hash,
        matched_strategy_route_rule=draft.matched_rule,
        selected_strategy_definition=draft.selected_strategy,
        strategy_route_schema_version=settings.STRATEGY_ROUTE_SCHEMA_VERSION,
        route_outcome=draft.route_outcome,
        matched_conditions=draft.matched_conditions,
        selection_reason=draft.selection_reason,
        fallback_used=draft.fallback_used,
        fallback_reason=draft.fallback_reason,
        status=draft.status,
        is_usable=draft.is_usable,
        allows_strategy_signal=draft.allows_strategy_signal,
        policy_status=context.policy.status,
        policy_enabled=context.policy.enabled,
        policy_version=context.policy.policy_version,
        condition_schema_version=context.policy.condition_schema_version,
        rule_set_hash=context.policy.rule_set_hash,
        definition_hash=context.policy.definition_hash,
        eligible_strategy_definition_ids=sorted(context.strategies),
        evidence_items=draft.evidence_items,
        evidence_text_zh=draft.evidence_text_zh,
        payload_summary=draft.payload_summary,
        error_code=draft.error_code,
        error_message=draft.error_message,
        analysis_close_time_utc=snapshot.analysis_close_time_utc,
        trace_id=trace_id,
        trigger_source=trigger_source,
        calculated_at_utc=timezone.now(),
        latency_ms=draft.latency_ms,
    )


def _decision_matches_request(
    decision: StrategyRouteDecision,
    *,
    snapshot_id: int,
    release_id: int,
    release_hash: str,
    expected_policy_hash: str,
) -> bool:
    return (
        decision.market_regime_snapshot_id == snapshot_id
        and decision.strategy_analysis_release_id == release_id
        and decision.release_hash == release_hash
        and (not expected_policy_hash or decision.definition_hash == expected_policy_hash)
    )


def _decision_result(
    decision: StrategyRouteDecision,
    *,
    trace_id: str,
    trigger_source: str,
) -> ServiceResult:
    status = ResultStatus.SUCCEEDED if decision.status == AnalysisObjectStatus.CREATED else ResultStatus.FAILED
    if decision.status == AnalysisObjectStatus.UNKNOWN:
        status = ResultStatus.UNKNOWN
    return ServiceResult(
        status,
        "strategy_route_decision_created" if status == ResultStatus.SUCCEEDED else decision.error_code,
        "StrategyRouteDecision 已生成" if status == ResultStatus.SUCCEEDED else decision.error_message,
        trace_id,
        trigger_source,
        {
            "strategy_route_decision_id": decision.id,
            "strategy_route_decision_key": decision.strategy_route_decision_key,
            "market_regime_snapshot_id": decision.market_regime_snapshot_id,
            "strategy_route_policy_id": decision.strategy_route_policy_id,
            "strategy_analysis_release_id": decision.strategy_analysis_release_id,
            "strategy_analysis_release_hash": decision.release_hash,
            "matched_route_rule_id": decision.matched_strategy_route_rule_id,
            "route_outcome": decision.route_outcome,
            "selected_strategy_definition_id": decision.selected_strategy_definition_id,
            "fallback_used": decision.fallback_used,
            "is_usable": decision.is_usable,
            "allows_strategy_signal": decision.allows_strategy_signal,
            "error_code": decision.error_code,
            "error_message": decision.error_message,
            "persisted": True,
        },
    )


def _persist_or_recover(
    *,
    snapshot: MarketRegimeSnapshot,
    context: RoutingContext,
    draft: RouteDraft,
    business_request_key: str,
    decision_key: str,
    trace_id: str,
    trigger_source: str,
) -> tuple[StrategyRouteDecision | None, ServiceResult | None]:
    try:
        with transaction.atomic():
            decision = _persist_decision(
                snapshot=snapshot,
                context=context,
                draft=draft,
                business_request_key=business_request_key,
                decision_key=decision_key,
                trace_id=trace_id,
                trigger_source=trigger_source,
            )
            if draft.status == AnalysisObjectStatus.FAILED:
                record_alert_event(
                    event_key=build_idempotency_key("strategy_routing_failed", business_request_key, draft.error_code),
                    source_module="StrategyRouting",
                    event_type="strategy_routing_failed",
                    event_category="strategy_analysis",
                    severity=AlertSeverity.HIGH,
                    title_zh="StrategyRouting 失败",
                    message_zh=draft.error_message,
                    trace_id=trace_id,
                    trigger_source=trigger_source,
                    related_object_type="StrategyRouteDecision",
                    related_object_id=str(decision.id),
                    business_status=draft.status,
                    reason_code=draft.error_code,
                    payload_summary=draft.payload_summary,
                )
        return decision, None
    except IntegrityError:
        try:
            by_request = StrategyRouteDecision.objects.filter(business_request_key=business_request_key).first()
            by_key = StrategyRouteDecision.objects.filter(strategy_route_decision_key=decision_key).first()
        except DatabaseError:
            return None, _result_with_alert(
                status=ResultStatus.UNKNOWN,
                reason_code="strategy_routing_persist_unknown",
                message="StrategyRouteDecision 写入结果无法确认",
                business_request_key=business_request_key,
                trace_id=trace_id,
                trigger_source=trigger_source,
                dry_run=False,
            )
        if by_request is not None:
            if not _decision_matches_request(
                by_request,
                snapshot_id=snapshot.id,
                release_id=context.policy_slice.release.id,
                release_hash=context.policy_slice.release.release_hash,
                expected_policy_hash=context.policy.definition_hash,
            ):
                return None, _result_with_alert(
                    status=ResultStatus.BLOCKED,
                    reason_code="strategy_routing_idempotency_conflict",
                    message="business_request_key 已被另一份路由请求使用",
                    business_request_key=business_request_key,
                    trace_id=trace_id,
                    trigger_source=trigger_source,
                    dry_run=False,
                )
            return by_request, None
        if by_key is not None:
            return by_key, None
        return None, _result_with_alert(
            status=ResultStatus.FAILED,
            reason_code="strategy_routing_persist_failed",
            message="StrategyRouteDecision 写入被数据库明确拒绝",
            business_request_key=business_request_key,
            trace_id=trace_id,
            trigger_source=trigger_source,
            dry_run=False,
        )
    except DataError as exc:
        return None, _result_with_alert(
            status=ResultStatus.FAILED,
            reason_code="strategy_routing_persist_failed",
            message=f"StrategyRouteDecision 数据不满足存储合同：{exc}",
            business_request_key=business_request_key,
            trace_id=trace_id,
            trigger_source=trigger_source,
            dry_run=False,
        )
    except DatabaseError:
        logger.exception("StrategyRouteDecision 写入失败 trace_id=%s", trace_id)
        return None, _result_with_alert(
            status=ResultStatus.UNKNOWN,
            reason_code="strategy_routing_persist_unknown",
            message="StrategyRouteDecision 写入结果无法确认",
            business_request_key=business_request_key,
            trace_id=trace_id,
            trigger_source=trigger_source,
            dry_run=False,
        )


def route_for_strategy_signal(
    *,
    market_regime_snapshot_id: int,
    strategy_analysis_release_id: int,
    strategy_analysis_release_hash: str,
    expected_strategy_route_policy_hash: str = "",
    expected_strategy_definition_set_hash: str = "",
    business_request_key: str,
    trace_id: str,
    trigger_source: str,
    dry_run: bool = False,
    registry: CalculatorRegistry = default_registry,
) -> ServiceResult:
    error, message = _validate_request(
        market_regime_snapshot_id=market_regime_snapshot_id,
        strategy_analysis_release_id=strategy_analysis_release_id,
        strategy_analysis_release_hash=strategy_analysis_release_hash,
        business_request_key=business_request_key,
        trace_id=trace_id,
        trigger_source=trigger_source,
    )
    if error:
        return _result_with_alert(
            status=ResultStatus.BLOCKED,
            reason_code=error,
            message=message,
            business_request_key=business_request_key or "invalid-strategy-routing-request",
            trace_id=trace_id,
            trigger_source=trigger_source,
            dry_run=dry_run,
        )
    if not dry_run:
        existing = StrategyRouteDecision.objects.filter(business_request_key=business_request_key).first()
        if existing is not None:
            if not _decision_matches_request(
                existing,
                snapshot_id=market_regime_snapshot_id,
                release_id=strategy_analysis_release_id,
                release_hash=strategy_analysis_release_hash,
                expected_policy_hash=expected_strategy_route_policy_hash,
            ):
                return _result_with_alert(
                    status=ResultStatus.BLOCKED,
                    reason_code="strategy_routing_idempotency_conflict",
                    message="business_request_key 已被另一份路由请求使用",
                    business_request_key=business_request_key,
                    trace_id=trace_id,
                    trigger_source=trigger_source,
                    dry_run=False,
                )
            return _decision_result(existing, trace_id=trace_id, trigger_source=trigger_source)
    snapshot, error = _load_regime_snapshot(
        snapshot_id=market_regime_snapshot_id,
        release_id=strategy_analysis_release_id,
        release_hash=strategy_analysis_release_hash,
    )
    if snapshot is None:
        return _result_with_alert(
            status=ResultStatus.BLOCKED,
            reason_code=error,
            message="MarketRegimeSnapshot 不满足正式路由条件",
            business_request_key=business_request_key,
            trace_id=trace_id,
            trigger_source=trigger_source,
            dry_run=dry_run,
        )
    context, error = _load_routing_context(
        snapshot=snapshot,
        release_id=strategy_analysis_release_id,
        release_hash=strategy_analysis_release_hash,
        expected_policy_hash=expected_strategy_route_policy_hash,
        expected_strategy_definition_set_hash=expected_strategy_definition_set_hash,
    )
    if context is None:
        return _result_with_alert(
            status=ResultStatus.BLOCKED,
            reason_code=error,
            message="StrategyRouting 冻结配置不完整或身份不一致",
            business_request_key=business_request_key,
            trace_id=trace_id,
            trigger_source=trigger_source,
            dry_run=dry_run,
        )
    decision_key = _decision_key(
        snapshot_id=snapshot.id,
        schema_version=settings.STRATEGY_ROUTE_SCHEMA_VERSION,
        definition_hash=context.policy.definition_hash,
    )
    if not dry_run:
        existing_by_key = StrategyRouteDecision.objects.filter(strategy_route_decision_key=decision_key).first()
        if existing_by_key is not None:
            return _decision_result(existing_by_key, trace_id=trace_id, trigger_source=trigger_source)
    try:
        draft, error, evidence = _evaluate_route(context=context, snapshot=snapshot, registry=registry)
    except (RoutingDataError, InvalidOperation, TypeError, ValueError) as exc:
        draft = RouteDraft(
            status=AnalysisObjectStatus.FAILED,
            route_outcome="",
            matched_rule=None,
            selected_strategy=None,
            fallback_used=False,
            fallback_reason="",
            is_usable=False,
            allows_strategy_signal=False,
            matched_conditions={},
            selection_reason="StrategyRouting 规则计算失败。",
            evidence_items=[],
            evidence_text_zh="StrategyRouting 规则计算失败。",
            payload_summary={"error": str(exc)},
            error_code="strategy_route_output_invalid",
            error_message=str(exc),
        )
        error = ""
        evidence = []
    except Exception as exc:
        logger.exception("StrategyRouting 规则匹配出现未预期异常")
        draft = RouteDraft(
            status=AnalysisObjectStatus.FAILED,
            route_outcome="",
            matched_rule=None,
            selected_strategy=None,
            fallback_used=False,
            fallback_reason="",
            is_usable=False,
            allows_strategy_signal=False,
            matched_conditions={},
            selection_reason="StrategyRouting 出现未预期异常。",
            evidence_items=[],
            evidence_text_zh="StrategyRouting 出现未预期异常。",
            payload_summary={"exception_type": type(exc).__name__},
            error_code="strategy_routing_unexpected_error",
            error_message=f"{type(exc).__name__}: {exc}",
        )
        error = ""
        evidence = []
    if draft is None:
        return _result_with_alert(
            status=ResultStatus.BLOCKED,
            reason_code=error,
            message="StrategyRouting 无法形成唯一、可执行的路由结果",
            business_request_key=business_request_key,
            trace_id=trace_id,
            trigger_source=trigger_source,
            dry_run=dry_run,
            payload_summary={"rule_evidence": evidence},
        )
    if dry_run:
        return ServiceResult(
            ResultStatus.SUCCEEDED if draft.status == AnalysisObjectStatus.CREATED else ResultStatus.FAILED,
            "strategy_routing_dry_run",
            "StrategyRouting dry-run 已完成，未写入正式业务对象",
            trace_id,
            trigger_source,
            {
                "persisted": False,
                "route_outcome": draft.route_outcome,
                "selected_strategy_definition_id": draft.selected_strategy.id if draft.selected_strategy else None,
                "fallback_used": draft.fallback_used,
                "is_usable": draft.is_usable,
                "allows_strategy_signal": False,
                "error_code": draft.error_code,
                "error_message": draft.error_message,
            },
        )
    decision, persist_result = _persist_or_recover(
        snapshot=snapshot,
        context=context,
        draft=draft,
        business_request_key=business_request_key,
        decision_key=decision_key,
        trace_id=trace_id,
        trigger_source=trigger_source,
    )
    if persist_result is not None:
        return persist_result
    assert decision is not None
    return _decision_result(decision, trace_id=trace_id, trigger_source=trigger_source)
