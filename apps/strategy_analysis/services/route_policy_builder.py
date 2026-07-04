"""StrategyAnalysis 模块：策略路由方案组装服务。

负责：基于既有 StrategyRoutePolicy 复制生成新的路由方案，并为每条规则绑定具体 StrategyDefinition。
不负责：执行 StrategySignal 算法、生成目标仓位、生成订单、审批风控或提交交易。
读写数据库：读取 StrategyRoutePolicy / StrategyRouteRule / StrategyDefinition，写入新的 Policy / Rule 与审计记录。
访问 Redis：不涉及。
访问外部服务：不涉及。
发送 Hermes：不涉及。
调用大模型：不涉及。
涉及交易执行：不涉及。
允许真实交易：否。
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from django.core.exceptions import ObjectDoesNotExist
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.audit.services import record_audit
from apps.foundation.results import ResultStatus, ServiceResult
from apps.strategy_analysis.default_market_regime_definitions import DEFAULT_MARKET_REGIME_DEFINITIONS
from apps.strategy_analysis.definition_hashes import (
    normalize_regime_codes,
    strategy_route_policy_hash,
    strategy_route_rule_hash,
    strategy_route_rule_set_hash,
)
from apps.strategy_analysis.models import (
    DefinitionLifecycleStatus,
    StrategyDefinition,
    StrategyRouteAction,
    StrategyRouteFallbackPolicy,
    StrategyRoutePolicy,
    StrategyRouteRule,
)


def _allowed_regime_codes() -> tuple[str, ...]:
    return normalize_regime_codes(DEFAULT_MARKET_REGIME_DEFINITIONS[0].allowed_regime_codes)


def _text(value: str, *, field_name: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise ValueError(f"{field_name} 不能为空")
    return cleaned


def _strategy_by_id(strategy_id: int, *, strategies: Mapping[int, StrategyDefinition]) -> StrategyDefinition:
    strategy = strategies.get(strategy_id)
    if strategy is None:
        raise ValueError(f"策略定义不可用：{strategy_id}")
    return strategy


def _next_auto_policy_identity() -> tuple[str, str]:
    base = f"custom_strategy_routing_{timezone.now().strftime('%Y%m%d%H%M%S')}"
    version = "v1"
    if not StrategyRoutePolicy.objects.filter(policy_code=base, policy_version=version).exists():
        return base, version
    for index in range(2, 100):
        candidate = f"{base}_{index}"
        if not StrategyRoutePolicy.objects.filter(policy_code=candidate, policy_version=version).exists():
            return candidate, version
    raise ValueError("无法生成唯一的路由方案身份")


def _record_builder_audit(
    *,
    operator_id: str,
    source_policy: StrategyRoutePolicy,
    new_policy: StrategyRoutePolicy,
    reason: str,
    rule_bindings: dict[int, int],
    trace_id: str,
    trigger_source: str,
) -> None:
    if not operator_id:
        return
    record_audit(
        operator_id=operator_id,
        operation_type="strategy_route_policy_variant_create",
        target_object_type="StrategyRoutePolicy",
        target_object_id=str(new_policy.id),
        before_state_summary={
            "source_policy_id": source_policy.id,
            "source_policy_code": source_policy.policy_code,
            "source_policy_version": source_policy.policy_version,
        },
        after_state_summary={
            "policy_id": new_policy.id,
            "policy_code": new_policy.policy_code,
            "policy_version": new_policy.policy_version,
            "rule_count": new_policy.rules.count(),
        },
        reason=reason,
        evidence={"rule_bindings": rule_bindings},
        result="succeeded",
        trace_id=trace_id,
        trigger_source=trigger_source,
    )


def create_route_policy_variant(
    *,
    source_policy_id: int,
    policy_version: str,
    display_name: str,
    description: str,
    rule_strategy_bindings: Mapping[int | str, int | str],
    operator_id: str,
    reason: str,
    trace_id: str,
    trigger_source: str,
) -> ServiceResult:
    """复制已有路由方案，并把每条规则重新绑定到策略插件。"""

    try:
        cleaned_display_name = _text(display_name, field_name="展示名称")
    except ValueError as exc:
        return ServiceResult(ResultStatus.BLOCKED, "route_policy_input_invalid", str(exc), trace_id, trigger_source)
    cleaned_reason = reason.strip() or "后台创建策略路由方案"

    try:
        normalized_bindings = {
            int(rule_id): int(strategy_id)
            for rule_id, strategy_id in rule_strategy_bindings.items()
            if int(rule_id) > 0 and int(strategy_id) > 0
        }
    except (TypeError, ValueError):
        return ServiceResult(
            ResultStatus.BLOCKED,
            "route_policy_rule_binding_invalid",
            "路由规则绑定参数不合法",
            trace_id,
            trigger_source,
        )

    try:
        source_policy = StrategyRoutePolicy.objects.prefetch_related("rules").get(id=source_policy_id)
    except ObjectDoesNotExist:
        return ServiceResult(
            ResultStatus.BLOCKED,
            "route_policy_source_not_found",
            "源路由方案不存在",
            trace_id,
            trigger_source,
        )

    if source_policy.status != DefinitionLifecycleStatus.ACTIVE or not source_policy.enabled:
        return ServiceResult(
            ResultStatus.BLOCKED,
            "route_policy_source_not_selectable",
            "源路由方案当前不可用",
            trace_id,
            trigger_source,
        )

    try:
        cleaned_policy_code, cleaned_policy_version = _next_auto_policy_identity()
    except ValueError as exc:
        return ServiceResult(ResultStatus.BLOCKED, "route_policy_input_invalid", str(exc), trace_id, trigger_source)

    if StrategyRoutePolicy.objects.filter(
        policy_code=cleaned_policy_code,
        policy_version=cleaned_policy_version,
    ).exists():
        return ServiceResult(
            ResultStatus.BLOCKED,
            "route_policy_version_exists",
            "同代码、同版本的路由方案已经存在",
            trace_id,
            trigger_source,
        )

    source_rules = list(source_policy.rules.order_by("priority", "rule_code", "id"))
    if not source_rules:
        return ServiceResult(
            ResultStatus.BLOCKED,
            "route_policy_source_has_no_rules",
            "源路由方案没有可复制的规则",
            trace_id,
            trigger_source,
        )

    strategy_ids = {
        int(strategy_id)
        for strategy_id in normalized_bindings.values()
    } | {
        rule.selected_strategy_definition_id
        for rule in source_rules
        if rule.selected_strategy_definition_id is not None
    }
    strategies = {
        strategy.id: strategy
        for strategy in StrategyDefinition.objects.filter(
            id__in=strategy_ids,
            status=DefinitionLifecycleStatus.ACTIVE,
            enabled=True,
        )
    }

    selected_by_rule: dict[int, StrategyDefinition] = {}
    try:
        for rule in source_rules:
            selected_id = normalized_bindings.get(rule.id) or rule.selected_strategy_definition_id
            if selected_id is None:
                raise ValueError(f"规则 {rule.rule_code} 尚未绑定策略")
            selected_by_rule[rule.id] = _strategy_by_id(selected_id, strategies=strategies)
    except ValueError as exc:
        return ServiceResult(ResultStatus.BLOCKED, "route_policy_rule_binding_invalid", str(exc), trace_id, trigger_source)

    allowed_regime_codes = _allowed_regime_codes()

    try:
        with transaction.atomic():
            new_policy = StrategyRoutePolicy.objects.create(
                policy_code=cleaned_policy_code,
                policy_version=cleaned_policy_version,
                display_name=cleaned_display_name,
                description=description.strip(),
                condition_schema_version=source_policy.condition_schema_version,
                rule_set_hash="pending",
                definition_hash="pending",
                fallback_policy=StrategyRouteFallbackPolicy.NONE,
                fallback_strategy_definition=None,
                status=DefinitionLifecycleStatus.ACTIVE,
                enabled=True,
            )
            new_rules: list[StrategyRouteRule] = []
            for source_rule in source_rules:
                selected_strategy = selected_by_rule[source_rule.id]
                rule_hash = strategy_route_rule_hash(
                    policy_id=new_policy.id,
                    rule_code=source_rule.rule_code,
                    priority=source_rule.priority,
                    action=StrategyRouteAction.SELECT_STRATEGY,
                    match_conditions=source_rule.match_conditions,
                    selected_strategy_definition_id=selected_strategy.id,
                    valid_from_utc=source_rule.valid_from_utc,
                    valid_to_utc=source_rule.valid_to_utc,
                    allowed_regime_codes=allowed_regime_codes,
                )
                new_rules.append(
                    StrategyRouteRule.objects.create(
                        strategy_route_policy=new_policy,
                        rule_code=source_rule.rule_code,
                        display_name=source_rule.display_name,
                        description=source_rule.description,
                        priority=source_rule.priority,
                        action=StrategyRouteAction.SELECT_STRATEGY,
                        match_conditions=source_rule.match_conditions,
                        selected_strategy_definition=selected_strategy,
                        status=DefinitionLifecycleStatus.ACTIVE,
                        enabled=True,
                        valid_from_utc=source_rule.valid_from_utc,
                        valid_to_utc=source_rule.valid_to_utc,
                        rule_hash=rule_hash,
                    )
                )

            rule_payloads = [
                {
                    "rule_id": rule.id,
                    "rule_code": rule.rule_code,
                    "priority": rule.priority,
                    "rule_hash": rule.rule_hash,
                }
                for rule in new_rules
            ]
            rule_set_hash = strategy_route_rule_set_hash(rule_payloads)
            definition_hash = strategy_route_policy_hash(
                policy_code=new_policy.policy_code,
                policy_version=new_policy.policy_version,
                condition_schema_version=new_policy.condition_schema_version,
                rule_set_hash=rule_set_hash,
                fallback_policy=new_policy.fallback_policy,
                fallback_strategy_definition_id=new_policy.fallback_strategy_definition_id,
            )
            StrategyRoutePolicy.objects.filter(id=new_policy.id).update(
                rule_set_hash=rule_set_hash,
                definition_hash=definition_hash,
            )
            new_policy.rule_set_hash = rule_set_hash
            new_policy.definition_hash = definition_hash

        _record_builder_audit(
            operator_id=operator_id,
            source_policy=source_policy,
            new_policy=new_policy,
            reason=cleaned_reason,
            rule_bindings={rule_id: strategy.id for rule_id, strategy in selected_by_rule.items()},
            trace_id=trace_id,
            trigger_source=trigger_source,
        )
    except IntegrityError:
        return ServiceResult(
            ResultStatus.BLOCKED,
            "route_policy_version_exists",
            "同代码、同版本的路由方案已经存在",
            trace_id,
            trigger_source,
        )
    except ValueError as exc:
        return ServiceResult(ResultStatus.BLOCKED, "route_policy_configuration_invalid", str(exc), trace_id, trigger_source)

    return ServiceResult(
        ResultStatus.SUCCEEDED,
        "route_policy_variant_created",
        "策略路由方案已创建",
        trace_id,
        trigger_source,
        {
            "route_policy_id": new_policy.id,
            "policy_code": new_policy.policy_code,
            "policy_version": new_policy.policy_version,
            "rule_count": len(new_rules),
        },
    )
