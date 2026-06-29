from __future__ import annotations

from io import StringIO

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.strategy_analysis.default_strategy_routing_definitions import (
    DEFAULT_STRATEGY_ROUTE_POLICY,
    DEFAULT_STRATEGY_ROUTE_RULES,
)
from apps.strategy_analysis.definition_hashes import normalize_domain_codes, strategy_definition_hash
from apps.strategy_analysis.models import (
    DefinitionLifecycleStatus,
    StrategyDefinition,
    StrategyRouteAction,
    StrategyRoutePolicy,
    StrategyRouteRule,
)
from apps.strategy_calculator.utils import stable_hash


REQUIRED_DOMAIN_CODES = normalize_domain_codes(
    ["market_context", "trend", "momentum", "volatility", "structure", "risk_state"]
)


def create_strategy_definition(code: str, version: str = "v1") -> StrategyDefinition:
    params_hash = stable_hash({})
    definition_hash = strategy_definition_hash(
        strategy_code=code,
        strategy_version=version,
        algorithm_name=f"{code}_calculator",
        algorithm_version=version,
        input_schema_version="1.0",
        output_schema_version="1.0",
        params_hash=params_hash,
        allowed_domain_codes=REQUIRED_DOMAIN_CODES,
        required_domain_codes=REQUIRED_DOMAIN_CODES,
        uses_input_weights=False,
        domain_input_weights={},
        prediction_horizon="next_1_to_3_closed_4h",
    )
    return StrategyDefinition.objects.create(
        strategy_code=code,
        strategy_version=version,
        display_name=code,
        description=code,
        algorithm_name=f"{code}_calculator",
        algorithm_version=version,
        input_schema_version="1.0",
        output_schema_version="1.0",
        params={},
        params_hash=params_hash,
        definition_hash=definition_hash,
        allowed_domain_codes=list(REQUIRED_DOMAIN_CODES),
        required_domain_codes=list(REQUIRED_DOMAIN_CODES),
        uses_input_weights=False,
        domain_input_weights={},
        prediction_horizon="next_1_to_3_closed_4h",
        status=DefinitionLifecycleStatus.ACTIVE,
        enabled=True,
    )


def create_all_required_strategy_definitions() -> dict[str, StrategyDefinition]:
    codes = sorted({template.selected_strategy[0] for template in DEFAULT_STRATEGY_ROUTE_RULES if template.selected_strategy})
    return {code: create_strategy_definition(code) for code in codes}


@pytest.mark.django_db
def test_seed_strategy_routing_blocks_when_required_strategy_definitions_missing() -> None:
    with pytest.raises(CommandError, match="StrategyDefinition"):
        call_command("seed_strategy_routing", stdout=StringIO())

    assert StrategyRoutePolicy.objects.count() == 0
    assert StrategyRouteRule.objects.count() == 0


@pytest.mark.django_db
def test_seed_strategy_routing_creates_default_policy_and_rules() -> None:
    strategies = create_all_required_strategy_definitions()
    out = StringIO()

    call_command("seed_strategy_routing", stdout=out)

    assert "StrategyRouting seed completed" in out.getvalue()
    policy = StrategyRoutePolicy.objects.get(
        policy_code=DEFAULT_STRATEGY_ROUTE_POLICY.policy_code,
        policy_version=DEFAULT_STRATEGY_ROUTE_POLICY.policy_version,
    )
    assert policy.status == DefinitionLifecycleStatus.ACTIVE
    assert policy.enabled is True
    assert policy.condition_schema_version == DEFAULT_STRATEGY_ROUTE_POLICY.condition_schema_version
    assert policy.rule_set_hash != "pending"
    assert policy.definition_hash != "pending"
    assert policy.rules.count() == len(DEFAULT_STRATEGY_ROUTE_RULES)

    bullish_breakout = policy.rules.get(rule_code="bullish_breakout_to_long_trend_following")
    assert bullish_breakout.action == StrategyRouteAction.SELECT_STRATEGY
    assert bullish_breakout.selected_strategy_definition_id == strategies["long_trend_following"].id
    assert bullish_breakout.match_conditions == {"regime_codes": ["bullish_breakout"]}
    assert bullish_breakout.rule_hash != "pending"

    no_strategy_rule = policy.rules.get(rule_code="neutral_range_no_strategy")
    assert no_strategy_rule.action == StrategyRouteAction.NO_STRATEGY
    assert no_strategy_rule.selected_strategy_definition_id is None


@pytest.mark.django_db
def test_seed_strategy_routing_is_idempotent() -> None:
    create_all_required_strategy_definitions()
    call_command("seed_strategy_routing", stdout=StringIO())
    first_policy_ids = set(StrategyRoutePolicy.objects.values_list("id", flat=True))
    first_rule_ids = set(StrategyRouteRule.objects.values_list("id", flat=True))

    call_command("seed_strategy_routing", stdout=StringIO())

    assert set(StrategyRoutePolicy.objects.values_list("id", flat=True)) == first_policy_ids
    assert set(StrategyRouteRule.objects.values_list("id", flat=True)) == first_rule_ids
    assert StrategyRouteRule.objects.count() == len(DEFAULT_STRATEGY_ROUTE_RULES)


@pytest.mark.django_db
def test_seed_strategy_routing_rejects_existing_rule_identity_conflict() -> None:
    create_all_required_strategy_definitions()
    call_command("seed_strategy_routing", stdout=StringIO())
    StrategyRouteRule.objects.filter(rule_code="bullish_breakout_to_long_trend_following").update(
        action=StrategyRouteAction.NO_STRATEGY,
        selected_strategy_definition=None,
    )

    with pytest.raises(CommandError, match="StrategyRouteRule"):
        call_command("seed_strategy_routing", stdout=StringIO())
