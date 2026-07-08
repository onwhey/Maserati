from __future__ import annotations

from io import StringIO

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.audit.models import AuditRecord
from apps.foundation.results import ResultStatus
from apps.strategy_analysis.default_strategy_routing_definitions import (
    DEFAULT_STRATEGY_ROUTE_POLICY,
    DEFAULT_STRATEGY_ROUTE_RULES,
)
from apps.strategy_analysis.definition_hashes import normalize_domain_codes, strategy_definition_hash
from apps.strategy_analysis.market_regime_catalog import market_regime_display_name
from apps.strategy_analysis.models import (
    DefinitionLifecycleStatus,
    ReleaseItemComponentType,
    StrategyAnalysisWorkspaceItem,
    StrategyDefinition,
    StrategyRouteAction,
    StrategyRoutePolicy,
    StrategyRouteRule,
)
from apps.ops_console.selectors import list_strategy_route_policy_builder_options
from apps.strategy_analysis.services.route_policy_builder import create_route_policy_variant, delete_route_policy
from apps.strategy_analysis.services.workspace import (
    _release_selections_from_workspace,
    get_or_create_default_workspace,
    upsert_workspace_item,
)
from apps.strategy_calculator.utils import stable_hash


REQUIRED_DOMAIN_CODES = normalize_domain_codes(
    ["market_context", "trend", "momentum", "volatility", "structure", "risk_state"]
)


def create_strategy_definition(
    code: str,
    version: str = "v1",
    *,
    allowed_domain_codes: tuple[str, ...] | list[str] = REQUIRED_DOMAIN_CODES,
    required_domain_codes: tuple[str, ...] | list[str] = REQUIRED_DOMAIN_CODES,
) -> StrategyDefinition:
    params_hash = stable_hash({})
    definition_hash = strategy_definition_hash(
        strategy_code=code,
        strategy_version=version,
        algorithm_name=f"{code}_calculator",
        algorithm_version=version,
        input_schema_version="1.0",
        output_schema_version="1.0",
        params_hash=params_hash,
        allowed_domain_codes=tuple(allowed_domain_codes),
        required_domain_codes=tuple(required_domain_codes),
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
        allowed_domain_codes=list(allowed_domain_codes),
        required_domain_codes=list(required_domain_codes),
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

    no_trade_rule = policy.rules.get(rule_code="neutral_range_to_standard_no_trade")
    assert no_trade_rule.action == StrategyRouteAction.SELECT_STRATEGY
    assert no_trade_rule.selected_strategy_definition_id == strategies["standard_trend__neutral_range_no_trade"].id


@pytest.mark.django_db
def test_route_policy_builder_options_render_market_regime_from_catalog_not_rule_display_name() -> None:
    create_all_required_strategy_definitions()
    call_command("seed_strategy_routing", stdout=StringIO())
    policy = StrategyRoutePolicy.objects.get(
        policy_code=DEFAULT_STRATEGY_ROUTE_POLICY.policy_code,
        policy_version=DEFAULT_STRATEGY_ROUTE_POLICY.policy_version,
    )
    rule = policy.rules.get(rule_code="bullish_top_reversal_candidate_to_standard_no_trade")
    rule.display_name = "旧规则展示名"
    rule.save(update_fields=["display_name", "updated_at_utc"])

    data = list_strategy_route_policy_builder_options()
    policy_payload = next(item for item in data["policies"] if item["id"] == policy.id)
    rule_payload = next(item for item in policy_payload["rules"] if item["id"] == rule.id)

    assert rule_payload["display_name"] == "旧规则展示名"
    assert rule_payload["market_regime_codes"] == ["bullish_top_reversal_candidate"]
    assert rule_payload["market_regime_display_name"] == market_regime_display_name("bullish_top_reversal_candidate")


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


@pytest.mark.django_db
def test_create_route_policy_variant_rebinds_rule_without_mutating_source() -> None:
    create_all_required_strategy_definitions()
    replacement_strategy = create_strategy_definition("standard_trend__bearish_wait")
    call_command("seed_strategy_routing", stdout=StringIO())
    source_policy = StrategyRoutePolicy.objects.get(
        policy_code=DEFAULT_STRATEGY_ROUTE_POLICY.policy_code,
        policy_version=DEFAULT_STRATEGY_ROUTE_POLICY.policy_version,
    )
    source_rule = source_policy.rules.get(rule_code="bearish_trend_continuation_to_short_trend_following")
    original_strategy_id = source_rule.selected_strategy_definition_id

    result = create_route_policy_variant(
        source_policy_id=source_policy.id,
        policy_version="",
        display_name="自定义等待路由 v1",
        description="测试把下跌延续接到等待策略",
        rule_strategy_bindings={source_rule.id: replacement_strategy.id},
        operator_id="_pytest",
        reason="测试创建自定义路由方案",
        trace_id="trace_route_policy_variant_test",
        trigger_source="pytest",
    )

    assert result.status == ResultStatus.SUCCEEDED
    new_policy = StrategyRoutePolicy.objects.exclude(id=source_policy.id).get()
    assert new_policy.policy_code.startswith("custom_strategy_routing_")
    assert new_policy.policy_code != source_policy.policy_code
    assert new_policy.policy_version == "v1"
    assert new_policy.id != source_policy.id
    assert new_policy.definition_hash != "pending"
    assert new_policy.rules.count() == source_policy.rules.count()
    new_rule = new_policy.rules.get(rule_code=source_rule.rule_code)
    assert new_rule.action == StrategyRouteAction.SELECT_STRATEGY
    assert new_rule.selected_strategy_definition_id == replacement_strategy.id
    source_rule.refresh_from_db()
    assert source_rule.selected_strategy_definition_id == original_strategy_id


@pytest.mark.django_db
def test_select_route_policy_replaces_previous_route_policy_slice() -> None:
    create_all_required_strategy_definitions()
    replacement_strategy = create_strategy_definition("standard_trend__bearish_wait")
    call_command("seed_strategy_routing", stdout=StringIO())
    first_policy = StrategyRoutePolicy.objects.get(
        policy_code=DEFAULT_STRATEGY_ROUTE_POLICY.policy_code,
        policy_version=DEFAULT_STRATEGY_ROUTE_POLICY.policy_version,
    )
    first_rule = first_policy.rules.get(rule_code="bearish_trend_continuation_to_short_trend_following")
    result = create_route_policy_variant(
        source_policy_id=first_policy.id,
        policy_version="",
        display_name="第二套路由方案",
        description="测试策略路由单选替换",
        rule_strategy_bindings={first_rule.id: replacement_strategy.id},
        operator_id="_pytest",
        reason="测试策略路由单选替换",
        trace_id="trace_route_policy_replace_create",
        trigger_source="pytest",
    )
    assert result.status == ResultStatus.SUCCEEDED
    second_policy = StrategyRoutePolicy.objects.exclude(id=first_policy.id).get()

    first_select = upsert_workspace_item(
        component_type=ReleaseItemComponentType.STRATEGY_ROUTE_POLICY,
        component_object_id=first_policy.id,
        is_included=True,
        operator_id="_pytest",
        reason="选择第一套路由方案",
        trace_id="trace_route_policy_replace_first",
        trigger_source="pytest",
    )
    assert first_select.status == ResultStatus.SUCCEEDED

    second_select = upsert_workspace_item(
        component_type=ReleaseItemComponentType.STRATEGY_ROUTE_POLICY,
        component_object_id=second_policy.id,
        is_included=True,
        operator_id="_pytest",
        reason="选择第二套路由方案",
        trace_id="trace_route_policy_replace_second",
        trigger_source="pytest",
    )
    assert second_select.status == ResultStatus.SUCCEEDED

    included_items = StrategyAnalysisWorkspaceItem.objects.filter(is_included=True)
    included_route_policies = included_items.filter(component_type=ReleaseItemComponentType.STRATEGY_ROUTE_POLICY)
    assert included_route_policies.count() == 1
    assert included_route_policies.get().component_object_id == second_policy.id
    assert included_items.filter(component_type=ReleaseItemComponentType.STRATEGY_ROUTE_RULE).count() == second_policy.rules.count()
    assert set(
        included_items.filter(component_type=ReleaseItemComponentType.STRATEGY_DEFINITION).values_list(
            "component_object_id",
            flat=True,
        )
    ) == set(second_policy.rules.values_list("selected_strategy_definition_id", flat=True))


@pytest.mark.django_db
def test_delete_route_policy_removes_unreferenced_policy_rules_and_workspace_slice() -> None:
    create_all_required_strategy_definitions()
    replacement_strategy = create_strategy_definition("standard_trend__bearish_wait")
    call_command("seed_strategy_routing", stdout=StringIO())
    source_policy = StrategyRoutePolicy.objects.get(
        policy_code=DEFAULT_STRATEGY_ROUTE_POLICY.policy_code,
        policy_version=DEFAULT_STRATEGY_ROUTE_POLICY.policy_version,
    )
    source_rule = source_policy.rules.get(rule_code="bearish_trend_continuation_to_short_trend_following")
    create_result = create_route_policy_variant(
        source_policy_id=source_policy.id,
        policy_version="",
        display_name="待删除路由方案",
        description="测试删除路由方案",
        rule_strategy_bindings={source_rule.id: replacement_strategy.id},
        operator_id="_pytest",
        reason="测试创建待删除路由方案",
        trace_id="trace_route_policy_delete_create",
        trigger_source="pytest",
    )
    assert create_result.status == ResultStatus.SUCCEEDED
    policy = StrategyRoutePolicy.objects.exclude(id=source_policy.id).get()
    rule_ids = list(policy.rules.values_list("id", flat=True))

    select_result = upsert_workspace_item(
        component_type=ReleaseItemComponentType.STRATEGY_ROUTE_POLICY,
        component_object_id=policy.id,
        is_included=True,
        operator_id="_pytest",
        reason="测试选择待删除路由方案",
        trace_id="trace_route_policy_delete_select",
        trigger_source="pytest",
    )
    assert select_result.status == ResultStatus.SUCCEEDED
    assert StrategyAnalysisWorkspaceItem.objects.filter(
        component_type=ReleaseItemComponentType.STRATEGY_DEFINITION,
        inclusion_managed=True,
    ).exists()

    delete_result = delete_route_policy(
        route_policy_id=policy.id,
        operator_id="_pytest",
        reason="测试删除路由方案",
        trace_id="trace_route_policy_delete",
        trigger_source="pytest",
    )

    assert delete_result.status == ResultStatus.SUCCEEDED
    assert not StrategyRoutePolicy.objects.filter(id=policy.id).exists()
    assert not StrategyRouteRule.objects.filter(id__in=rule_ids).exists()
    assert not StrategyAnalysisWorkspaceItem.objects.filter(
        component_type__in=(
            ReleaseItemComponentType.STRATEGY_ROUTE_POLICY,
            ReleaseItemComponentType.STRATEGY_ROUTE_RULE,
            ReleaseItemComponentType.STRATEGY_DEFINITION,
        )
    ).exists()
    assert AuditRecord.objects.filter(
        operation_type="strategy_route_policy_delete",
        target_object_id=str(policy.id),
    ).exists()


@pytest.mark.django_db
def test_select_route_policy_auto_includes_rules_and_bound_strategies() -> None:
    create_all_required_strategy_definitions()
    call_command("seed_strategy_routing", stdout=StringIO())
    policy = StrategyRoutePolicy.objects.get(
        policy_code=DEFAULT_STRATEGY_ROUTE_POLICY.policy_code,
        policy_version=DEFAULT_STRATEGY_ROUTE_POLICY.policy_version,
    )

    result = upsert_workspace_item(
        component_type=ReleaseItemComponentType.STRATEGY_ROUTE_POLICY,
        component_object_id=policy.id,
        is_included=True,
        operator_id="_pytest",
        reason="测试纳入路由方案",
        trace_id="trace_workspace_route_policy_test",
        trigger_source="pytest",
    )

    assert result.status == ResultStatus.SUCCEEDED
    included_items = StrategyAnalysisWorkspaceItem.objects.filter(is_included=True)
    assert included_items.filter(component_type=ReleaseItemComponentType.STRATEGY_ROUTE_POLICY).count() == 1
    assert included_items.filter(component_type=ReleaseItemComponentType.STRATEGY_ROUTE_RULE).count() == policy.rules.count()
    included_strategy_codes = set(
        included_items.filter(component_type=ReleaseItemComponentType.STRATEGY_DEFINITION).values_list(
            "component_code",
            flat=True,
        )
    )
    expected_strategy_codes = set(
        policy.rules.exclude(selected_strategy_definition=None).values_list(
            "selected_strategy_definition__strategy_code",
            flat=True,
        )
    )
    assert included_strategy_codes == expected_strategy_codes

    cancel_result = upsert_workspace_item(
        component_type=ReleaseItemComponentType.STRATEGY_ROUTE_POLICY,
        component_object_id=policy.id,
        is_included=False,
        operator_id="_pytest",
        reason="测试取消纳入路由方案",
        trace_id="trace_workspace_route_policy_cancel_test",
        trigger_source="pytest",
    )

    assert cancel_result.status == ResultStatus.SUCCEEDED
    assert StrategyAnalysisWorkspaceItem.objects.filter(
        component_type=ReleaseItemComponentType.STRATEGY_ROUTE_POLICY,
        component_code=policy.policy_code,
        is_included=True,
    ).count() == 0
    assert StrategyAnalysisWorkspaceItem.objects.filter(
        component_type=ReleaseItemComponentType.STRATEGY_ROUTE_RULE,
        is_included=True,
    ).count() == 0


@pytest.mark.django_db
def test_release_selection_ignores_manually_included_strategy_not_bound_by_route_rule() -> None:
    route_bound_strategy = create_strategy_definition("route_bound_strategy", required_domain_codes=())
    manually_selected_strategy = create_strategy_definition("manual_extra_strategy", required_domain_codes=())
    policy = StrategyRoutePolicy.objects.create(
        policy_code="custom_policy",
        policy_version="v1",
        display_name="custom_policy",
        description="custom_policy",
        condition_schema_version="1.0",
        rule_set_hash="rule-set-hash",
        definition_hash="policy-hash",
        status=DefinitionLifecycleStatus.ACTIVE,
        enabled=True,
    )
    rule = StrategyRouteRule.objects.create(
        strategy_route_policy=policy,
        rule_code="route_to_bound_strategy",
        display_name="route_to_bound_strategy",
        description="route_to_bound_strategy",
        priority=10,
        action=StrategyRouteAction.SELECT_STRATEGY,
        match_conditions={"regime_codes": ["custom_regime"]},
        selected_strategy_definition=route_bound_strategy,
        status=DefinitionLifecycleStatus.ACTIVE,
        enabled=True,
        rule_hash="rule-hash",
    )
    result = upsert_workspace_item(
        component_type=ReleaseItemComponentType.STRATEGY_ROUTE_POLICY,
        component_object_id=policy.id,
        is_included=True,
        operator_id="_pytest",
        reason="选择路由方案",
        trace_id="trace_route_bound_release_selection",
        trigger_source="pytest",
    )
    assert result.status == ResultStatus.SUCCEEDED
    workspace = get_or_create_default_workspace(operator_id="_pytest")
    StrategyAnalysisWorkspaceItem.objects.update_or_create(
        workspace=workspace,
        component_type=ReleaseItemComponentType.STRATEGY_DEFINITION,
        component_code=manually_selected_strategy.strategy_code,
        defaults={
            "component_object_id": manually_selected_strategy.id,
            "component_version": manually_selected_strategy.strategy_version,
            "definition_hash": manually_selected_strategy.definition_hash,
            "inclusion_managed": True,
            "is_included": True,
            "selection_reason": "模拟旧版手工纳入策略",
            "updated_by": "_pytest",
            "trace_id": "trace_route_bound_release_selection",
            "trigger_source": "pytest",
        },
    )

    selections, errors = _release_selections_from_workspace(workspace)

    assert errors == []
    strategy_selection_ids = {
        selection.component_object_id
        for selection in selections
        if selection.component_type == ReleaseItemComponentType.STRATEGY_DEFINITION
    }
    assert route_bound_strategy.id in strategy_selection_ids
    assert manually_selected_strategy.id not in strategy_selection_ids
    assert rule.id in {
        selection.component_object_id
        for selection in selections
        if selection.component_type == ReleaseItemComponentType.STRATEGY_ROUTE_RULE
    }
