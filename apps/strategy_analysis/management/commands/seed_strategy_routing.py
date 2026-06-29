"""StrategyRouting 模块：幂等初始化默认 StrategyRoutePolicy / StrategyRouteRule。
负责：读取默认路由模板，把 Policy / Rule 写入数据库，并校验所需 StrategyDefinition 已存在。
不负责：创建 StrategyDefinition、执行 StrategySignal 算法、生成目标仓位或订单动作。
读写数据库：读取 StrategyDefinition，写入 StrategyRoutePolicy / StrategyRouteRule。
访问 Redis：不涉及。
访问外部服务：不涉及。
发送 Hermes：不涉及。
调用大模型：不涉及。
涉及交易执行：不涉及。
允许真实交易：否。
"""

from __future__ import annotations

from dataclasses import dataclass

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.strategy_analysis.default_market_regime_definitions import DEFAULT_MARKET_REGIME_DEFINITIONS
from apps.strategy_analysis.default_strategy_routing_definitions import (
    DEFAULT_STRATEGY_ROUTE_POLICY,
    DEFAULT_STRATEGY_ROUTE_RULES,
    StrategyRouteRuleTemplate,
)
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


@dataclass(frozen=True)
class SeededRouteRule:
    rule: StrategyRouteRule
    created: bool


class Command(BaseCommand):
    help = "幂等初始化默认 StrategyRoutePolicy / StrategyRouteRule"

    def handle(self, *args, **options):
        strategy_definitions = _load_required_strategy_definitions()
        allowed_regime_codes = normalize_regime_codes(DEFAULT_MARKET_REGIME_DEFINITIONS[0].allowed_regime_codes)
        with transaction.atomic():
            policy, policy_created = _seed_policy()
            seeded_rules = [
                _seed_rule(
                    policy=policy,
                    template=template,
                    strategy_definitions=strategy_definitions,
                    allowed_regime_codes=allowed_regime_codes,
                )
                for template in DEFAULT_STRATEGY_ROUTE_RULES
            ]
            _assert_no_extra_rules(policy=policy)
            _refresh_policy_hashes(policy=policy, seeded_rules=seeded_rules)
        self.stdout.write(
            self.style.SUCCESS(
                "StrategyRouting seed completed: "
                f"policy_created={int(policy_created)} "
                f"rules_created={sum(1 for item in seeded_rules if item.created)} "
                f"rules_existing={sum(1 for item in seeded_rules if not item.created)}"
            )
        )


def _load_required_strategy_definitions() -> dict[tuple[str, str], StrategyDefinition]:
    required = sorted(
        {
            template.selected_strategy
            for template in DEFAULT_STRATEGY_ROUTE_RULES
            if template.action == StrategyRouteAction.SELECT_STRATEGY
        }
    )
    found = {
        (definition.strategy_code, definition.strategy_version): definition
        for definition in StrategyDefinition.objects.filter(
            status=DefinitionLifecycleStatus.ACTIVE,
            enabled=True,
        )
    }
    missing = [f"{code}/{version}" for code, version in required if (code, version) not in found]
    if missing:
        raise CommandError(
            "默认 StrategyRouting 依赖的 StrategyDefinition 尚未全部可用，"
            "请先完成策略定义登记："
            + ", ".join(missing)
        )
    return {identity: found[identity] for identity in required}


def _seed_policy() -> tuple[StrategyRoutePolicy, bool]:
    fallback_definition = None
    if DEFAULT_STRATEGY_ROUTE_POLICY.fallback_policy != StrategyRouteFallbackPolicy.NONE:
        raise CommandError("当前默认 StrategyRouting 不允许配置 fallback")
    policy, created = StrategyRoutePolicy.objects.get_or_create(
        policy_code=DEFAULT_STRATEGY_ROUTE_POLICY.policy_code,
        policy_version=DEFAULT_STRATEGY_ROUTE_POLICY.policy_version,
        defaults={
            "display_name": DEFAULT_STRATEGY_ROUTE_POLICY.display_name,
            "description": DEFAULT_STRATEGY_ROUTE_POLICY.description,
            "condition_schema_version": DEFAULT_STRATEGY_ROUTE_POLICY.condition_schema_version,
            "rule_set_hash": "pending",
            "definition_hash": "pending",
            "fallback_policy": DEFAULT_STRATEGY_ROUTE_POLICY.fallback_policy,
            "fallback_strategy_definition": fallback_definition,
            "status": DefinitionLifecycleStatus.ACTIVE,
            "enabled": True,
        },
    )
    _assert_policy_identity(policy)
    StrategyRoutePolicy.objects.filter(id=policy.id).update(
        display_name=DEFAULT_STRATEGY_ROUTE_POLICY.display_name,
        description=DEFAULT_STRATEGY_ROUTE_POLICY.description,
    )
    policy.display_name = DEFAULT_STRATEGY_ROUTE_POLICY.display_name
    policy.description = DEFAULT_STRATEGY_ROUTE_POLICY.description
    return policy, created


def _assert_policy_identity(policy: StrategyRoutePolicy) -> None:
    identity_matches = (
        policy.condition_schema_version == DEFAULT_STRATEGY_ROUTE_POLICY.condition_schema_version
        and policy.fallback_policy == DEFAULT_STRATEGY_ROUTE_POLICY.fallback_policy
        and policy.fallback_strategy_definition_id is None
    )
    if not identity_matches:
        raise CommandError("已有 StrategyRoutePolicy 身份字段与默认路由模板冲突，拒绝覆盖")


def _seed_rule(
    *,
    policy: StrategyRoutePolicy,
    template: StrategyRouteRuleTemplate,
    strategy_definitions: dict[tuple[str, str], StrategyDefinition],
    allowed_regime_codes: tuple[str, ...],
) -> SeededRouteRule:
    selected_strategy = _resolve_selected_strategy(template, strategy_definitions)
    expected_hash = strategy_route_rule_hash(
        policy_id=policy.id,
        rule_code=template.rule_code,
        priority=template.priority,
        action=template.action,
        match_conditions=template.match_conditions,
        selected_strategy_definition_id=selected_strategy.id if selected_strategy else None,
        valid_from_utc=None,
        valid_to_utc=None,
        allowed_regime_codes=allowed_regime_codes,
    )
    rule, created = StrategyRouteRule.objects.get_or_create(
        strategy_route_policy=policy,
        rule_code=template.rule_code,
        defaults={
            "display_name": template.display_name,
            "description": template.description,
            "priority": template.priority,
            "action": template.action,
            "match_conditions": template.match_conditions,
            "selected_strategy_definition": selected_strategy,
            "status": DefinitionLifecycleStatus.ACTIVE,
            "enabled": True,
            "rule_hash": expected_hash,
        },
    )
    _assert_rule_identity(rule, template=template, selected_strategy=selected_strategy, expected_hash=expected_hash)
    StrategyRouteRule.objects.filter(id=rule.id).update(
        display_name=template.display_name,
        description=template.description,
        rule_hash=expected_hash,
    )
    rule.display_name = template.display_name
    rule.description = template.description
    rule.rule_hash = expected_hash
    return SeededRouteRule(rule=rule, created=created)


def _resolve_selected_strategy(
    template: StrategyRouteRuleTemplate,
    strategy_definitions: dict[tuple[str, str], StrategyDefinition],
) -> StrategyDefinition | None:
    if template.action == StrategyRouteAction.NO_STRATEGY:
        if template.selected_strategy is not None:
            raise CommandError(f"{template.rule_code} 为 no_strategy，不得绑定 StrategyDefinition")
        return None
    if template.action != StrategyRouteAction.SELECT_STRATEGY:
        raise CommandError(f"{template.rule_code} action 非法：{template.action}")
    if template.selected_strategy is None:
        raise CommandError(f"{template.rule_code} select_strategy 必须绑定 StrategyDefinition")
    return strategy_definitions[template.selected_strategy]


def _assert_rule_identity(
    rule: StrategyRouteRule,
    *,
    template: StrategyRouteRuleTemplate,
    selected_strategy: StrategyDefinition | None,
    expected_hash: str,
) -> None:
    identity_matches = (
        rule.priority == template.priority
        and rule.action == template.action
        and rule.match_conditions == template.match_conditions
        and rule.selected_strategy_definition_id == (selected_strategy.id if selected_strategy else None)
        and rule.valid_from_utc is None
        and rule.valid_to_utc is None
        and rule.rule_hash in {expected_hash, "pending"}
    )
    if not identity_matches:
        raise CommandError(f"已有 StrategyRouteRule 身份字段与默认路由模板冲突，拒绝覆盖：{template.rule_code}")


def _assert_no_extra_rules(*, policy: StrategyRoutePolicy) -> None:
    expected_codes = {template.rule_code for template in DEFAULT_STRATEGY_ROUTE_RULES}
    actual_codes = set(policy.rules.values_list("rule_code", flat=True))
    extra_codes = sorted(actual_codes - expected_codes)
    if extra_codes:
        raise CommandError(
            "已有 StrategyRoutePolicy 下存在非默认 StrategyRouteRule，默认 seed 拒绝覆盖："
            + ", ".join(extra_codes)
        )


def _refresh_policy_hashes(*, policy: StrategyRoutePolicy, seeded_rules: list[SeededRouteRule]) -> None:
    rule_payloads = [
        {
            "rule_id": seeded.rule.id,
            "rule_code": seeded.rule.rule_code,
            "priority": seeded.rule.priority,
            "rule_hash": seeded.rule.rule_hash,
        }
        for seeded in seeded_rules
    ]
    rule_set_hash = strategy_route_rule_set_hash(rule_payloads)
    definition_hash = strategy_route_policy_hash(
        policy_code=policy.policy_code,
        policy_version=policy.policy_version,
        condition_schema_version=policy.condition_schema_version,
        rule_set_hash=rule_set_hash,
        fallback_policy=policy.fallback_policy,
        fallback_strategy_definition_id=policy.fallback_strategy_definition_id,
    )
    if policy.rule_set_hash not in {"pending", rule_set_hash} or policy.definition_hash not in {"pending", definition_hash}:
        raise CommandError("已有 StrategyRoutePolicy 指纹与默认路由模板冲突，拒绝覆盖")
    StrategyRoutePolicy.objects.filter(id=policy.id).update(
        rule_set_hash=rule_set_hash,
        definition_hash=definition_hash,
    )
