"""StrategyRouting 模块：默认路由 Policy / Rule 登记模板。
负责：提供代码内置的市场环境到策略定义的路由模板，供 seed_strategy_routing 写入数据库。
不负责：创建 StrategyDefinition、执行 StrategySignal 算法、生成目标仓位或订单动作。
读写数据库：不涉及。
访问 Redis：不涉及。
访问外部服务：不涉及。
发送 Hermes：不涉及。
调用大模型：不涉及。
涉及交易执行：不涉及。
允许真实交易：否。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from apps.strategy_analysis.market_regime_catalog import market_regime_display_name
from apps.strategy_analysis.models import StrategyRouteAction, StrategyRouteFallbackPolicy


@dataclass(frozen=True)
class StrategyRoutePolicyTemplate:
    policy_code: str
    policy_version: str
    display_name: str
    description: str
    condition_schema_version: str
    fallback_policy: str
    fallback_strategy: tuple[str, str] | None = None


@dataclass(frozen=True)
class StrategyRouteRuleTemplate:
    rule_code: str
    display_name: str
    description: str
    priority: int
    action: str
    match_conditions: dict[str, Any]
    selected_strategy: tuple[str, str] | None = None


def _rule_display_name(regime_code: str) -> str:
    return f"{market_regime_display_name(regime_code)}接线规则"


def _rule_description(regime_code: str) -> str:
    return f"匹配市场环境：{market_regime_display_name(regime_code)}；命中后交给本规则绑定的策略处理。"


DEFAULT_STRATEGY_ROUTE_POLICY = StrategyRoutePolicyTemplate(
    policy_code="context_structure_strategy_routing",
    policy_version="v2",
    display_name="大背景结构策略路由 v2",
    description=(
        "基于 context_structure_regime_v1 输出的市场环境，在已批准的 StrategyDefinition 中选择"
        "对应策略；普通不交易场景也必须选择显式不交易策略，由 StrategySignal 输出 neutral。"
        "本 Policy 只做策略选择，不执行策略算法，不生成目标仓位或订单。"
    ),
    condition_schema_version="1.0",
    fallback_policy=StrategyRouteFallbackPolicy.NONE,
)


DEFAULT_STRATEGY_ROUTE_RULES: tuple[StrategyRouteRuleTemplate, ...] = (
    StrategyRouteRuleTemplate(
        rule_code="bullish_trend_continuation_to_long_trend_following",
        display_name=_rule_display_name("bullish_trend_continuation"),
        description=_rule_description("bullish_trend_continuation"),
        priority=10,
        action=StrategyRouteAction.SELECT_STRATEGY,
        match_conditions={"regime_codes": ["bullish_trend_continuation"]},
        selected_strategy=("long_trend_following", "v1"),
    ),
    StrategyRouteRuleTemplate(
        rule_code="bullish_breakout_to_long_trend_following",
        display_name=_rule_display_name("bullish_breakout"),
        description=_rule_description("bullish_breakout"),
        priority=20,
        action=StrategyRouteAction.SELECT_STRATEGY,
        match_conditions={"regime_codes": ["bullish_breakout"]},
        selected_strategy=("long_trend_following", "v1"),
    ),
    StrategyRouteRuleTemplate(
        rule_code="bullish_pullback_to_long_pullback_support",
        display_name=_rule_display_name("bullish_pullback"),
        description=_rule_description("bullish_pullback"),
        priority=30,
        action=StrategyRouteAction.SELECT_STRATEGY,
        match_conditions={"regime_codes": ["bullish_pullback"]},
        selected_strategy=("long_pullback_support", "v1"),
    ),
    StrategyRouteRuleTemplate(
        rule_code="bullish_high_range_to_long_pullback_support",
        display_name=_rule_display_name("bullish_high_range"),
        description=_rule_description("bullish_high_range"),
        priority=40,
        action=StrategyRouteAction.SELECT_STRATEGY,
        match_conditions={"regime_codes": ["bullish_high_range"]},
        selected_strategy=("long_pullback_support", "v1"),
    ),
    StrategyRouteRuleTemplate(
        rule_code="bearish_trend_continuation_to_short_trend_following",
        display_name=_rule_display_name("bearish_trend_continuation"),
        description=_rule_description("bearish_trend_continuation"),
        priority=50,
        action=StrategyRouteAction.SELECT_STRATEGY,
        match_conditions={"regime_codes": ["bearish_trend_continuation"]},
        selected_strategy=("short_trend_following", "v1"),
    ),
    StrategyRouteRuleTemplate(
        rule_code="bearish_breakdown_to_short_trend_following",
        display_name=_rule_display_name("bearish_breakdown"),
        description=_rule_description("bearish_breakdown"),
        priority=60,
        action=StrategyRouteAction.SELECT_STRATEGY,
        match_conditions={"regime_codes": ["bearish_breakdown"]},
        selected_strategy=("short_trend_following", "v1"),
    ),
    StrategyRouteRuleTemplate(
        rule_code="bearish_rebound_to_short_rebound_pressure",
        display_name=_rule_display_name("bearish_rebound"),
        description=_rule_description("bearish_rebound"),
        priority=70,
        action=StrategyRouteAction.SELECT_STRATEGY,
        match_conditions={"regime_codes": ["bearish_rebound"]},
        selected_strategy=("short_rebound_pressure", "v1"),
    ),
    StrategyRouteRuleTemplate(
        rule_code="bearish_low_range_to_short_rebound_pressure",
        display_name=_rule_display_name("bearish_low_range"),
        description=_rule_description("bearish_low_range"),
        priority=80,
        action=StrategyRouteAction.SELECT_STRATEGY,
        match_conditions={"regime_codes": ["bearish_low_range"]},
        selected_strategy=("short_rebound_pressure", "v1"),
    ),
    StrategyRouteRuleTemplate(
        rule_code="bullish_top_reversal_candidate_to_standard_no_trade",
        display_name=_rule_display_name("bullish_top_reversal_candidate"),
        description=_rule_description("bullish_top_reversal_candidate"),
        priority=90,
        action=StrategyRouteAction.SELECT_STRATEGY,
        match_conditions={"regime_codes": ["bullish_top_reversal_candidate"]},
        selected_strategy=("standard_trend__top_reversal_unconfirmed_no_trade", "v1"),
    ),
    StrategyRouteRuleTemplate(
        rule_code="bearish_bottom_reversal_candidate_to_standard_no_trade",
        display_name=_rule_display_name("bearish_bottom_reversal_candidate"),
        description=_rule_description("bearish_bottom_reversal_candidate"),
        priority=100,
        action=StrategyRouteAction.SELECT_STRATEGY,
        match_conditions={"regime_codes": ["bearish_bottom_reversal_candidate"]},
        selected_strategy=("standard_trend__bottom_reversal_unconfirmed_no_trade", "v1"),
    ),
    StrategyRouteRuleTemplate(
        rule_code="neutral_range_to_standard_no_trade",
        display_name=_rule_display_name("neutral_range"),
        description=_rule_description("neutral_range"),
        priority=110,
        action=StrategyRouteAction.SELECT_STRATEGY,
        match_conditions={"regime_codes": ["neutral_range"]},
        selected_strategy=("standard_trend__neutral_range_no_trade", "v1"),
    ),
    StrategyRouteRuleTemplate(
        rule_code="high_risk_environment_to_standard_no_trade",
        display_name=_rule_display_name("high_risk_environment"),
        description=_rule_description("high_risk_environment"),
        priority=120,
        action=StrategyRouteAction.SELECT_STRATEGY,
        match_conditions={"regime_codes": ["high_risk_environment"]},
        selected_strategy=("standard_trend__high_risk_environment_no_trade", "v1"),
    ),
    StrategyRouteRuleTemplate(
        rule_code="unclear_environment_to_standard_no_trade",
        display_name=_rule_display_name("unclear_environment"),
        description=_rule_description("unclear_environment"),
        priority=130,
        action=StrategyRouteAction.SELECT_STRATEGY,
        match_conditions={"regime_codes": ["unclear_environment"]},
        selected_strategy=("standard_trend__unclear_environment_no_trade", "v1"),
    ),
)
