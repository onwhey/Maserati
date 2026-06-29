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


DEFAULT_STRATEGY_ROUTE_POLICY = StrategyRoutePolicyTemplate(
    policy_code="context_structure_strategy_routing",
    policy_version="v1",
    display_name="大背景结构策略路由 v1",
    description=(
        "基于 context_structure_regime_v1 输出的市场环境，在已批准的 StrategyDefinition 中选择"
        "对应策略；本 Policy 只做策略选择，不执行策略算法，不生成目标仓位或订单。"
    ),
    condition_schema_version="1.0",
    fallback_policy=StrategyRouteFallbackPolicy.NONE,
)


DEFAULT_STRATEGY_ROUTE_RULES: tuple[StrategyRouteRuleTemplate, ...] = (
    StrategyRouteRuleTemplate(
        rule_code="bullish_trend_continuation_to_long_trend_following",
        display_name="多头延续选择多头趋势跟随",
        description="大背景偏多且趋势延续时，选择 long_trend_following/v1。",
        priority=10,
        action=StrategyRouteAction.SELECT_STRATEGY,
        match_conditions={"regime_codes": ["bullish_trend_continuation"]},
        selected_strategy=("long_trend_following", "v1"),
    ),
    StrategyRouteRuleTemplate(
        rule_code="bullish_breakout_to_long_trend_following",
        display_name="向上突破选择多头趋势跟随",
        description="有效向上突破环境下，选择 long_trend_following/v1。",
        priority=20,
        action=StrategyRouteAction.SELECT_STRATEGY,
        match_conditions={"regime_codes": ["bullish_breakout"]},
        selected_strategy=("long_trend_following", "v1"),
    ),
    StrategyRouteRuleTemplate(
        rule_code="bullish_pullback_to_long_pullback_support",
        display_name="多头回调选择支撑回调多头",
        description="大背景偏多但处于回调阶段时，选择 long_pullback_support/v1。",
        priority=30,
        action=StrategyRouteAction.SELECT_STRATEGY,
        match_conditions={"regime_codes": ["bullish_pullback"]},
        selected_strategy=("long_pullback_support", "v1"),
    ),
    StrategyRouteRuleTemplate(
        rule_code="bullish_high_range_to_long_pullback_support",
        display_name="多头高位区间选择支撑回调多头",
        description="多头高位区间震荡时，只允许支撑侧策略 long_pullback_support/v1 继续判断。",
        priority=40,
        action=StrategyRouteAction.SELECT_STRATEGY,
        match_conditions={"regime_codes": ["bullish_high_range"]},
        selected_strategy=("long_pullback_support", "v1"),
    ),
    StrategyRouteRuleTemplate(
        rule_code="bearish_trend_continuation_to_short_trend_following",
        display_name="空头延续选择空头趋势跟随",
        description="大背景偏空且趋势延续时，选择 short_trend_following/v1。",
        priority=50,
        action=StrategyRouteAction.SELECT_STRATEGY,
        match_conditions={"regime_codes": ["bearish_trend_continuation"]},
        selected_strategy=("short_trend_following", "v1"),
    ),
    StrategyRouteRuleTemplate(
        rule_code="bearish_breakdown_to_short_trend_following",
        display_name="向下跌破选择空头趋势跟随",
        description="有效向下跌破环境下，选择 short_trend_following/v1。",
        priority=60,
        action=StrategyRouteAction.SELECT_STRATEGY,
        match_conditions={"regime_codes": ["bearish_breakdown"]},
        selected_strategy=("short_trend_following", "v1"),
    ),
    StrategyRouteRuleTemplate(
        rule_code="bearish_rebound_to_short_rebound_pressure",
        display_name="空头反弹选择压力反弹空头",
        description="大背景偏空但处于反弹阶段时，选择 short_rebound_pressure/v1。",
        priority=70,
        action=StrategyRouteAction.SELECT_STRATEGY,
        match_conditions={"regime_codes": ["bearish_rebound"]},
        selected_strategy=("short_rebound_pressure", "v1"),
    ),
    StrategyRouteRuleTemplate(
        rule_code="bearish_low_range_to_short_rebound_pressure",
        display_name="空头低位区间选择压力反弹空头",
        description="空头低位区间震荡时，只允许压力侧策略 short_rebound_pressure/v1 继续判断。",
        priority=80,
        action=StrategyRouteAction.SELECT_STRATEGY,
        match_conditions={"regime_codes": ["bearish_low_range"]},
        selected_strategy=("short_rebound_pressure", "v1"),
    ),
    StrategyRouteRuleTemplate(
        rule_code="bullish_top_reversal_candidate_no_strategy",
        display_name="多头顶部反转候选不选策略",
        description="顶部反转候选环境仅记录市场环境，不进入 StrategySignal。",
        priority=90,
        action=StrategyRouteAction.NO_STRATEGY,
        match_conditions={"regime_codes": ["bullish_top_reversal_candidate"]},
    ),
    StrategyRouteRuleTemplate(
        rule_code="bearish_bottom_reversal_candidate_no_strategy",
        display_name="空头底部反转候选不选策略",
        description="底部反转候选环境仅记录市场环境，不进入 StrategySignal。",
        priority=100,
        action=StrategyRouteAction.NO_STRATEGY,
        match_conditions={"regime_codes": ["bearish_bottom_reversal_candidate"]},
    ),
    StrategyRouteRuleTemplate(
        rule_code="neutral_range_no_strategy",
        display_name="无方向区间不选策略",
        description="无方向震荡环境下，P0 不选择任何策略。",
        priority=110,
        action=StrategyRouteAction.NO_STRATEGY,
        match_conditions={"regime_codes": ["neutral_range"]},
    ),
    StrategyRouteRuleTemplate(
        rule_code="high_risk_environment_no_strategy",
        display_name="高风险环境不选策略",
        description="高风险环境下，P0 不选择任何策略。",
        priority=120,
        action=StrategyRouteAction.NO_STRATEGY,
        match_conditions={"regime_codes": ["high_risk_environment"]},
    ),
    StrategyRouteRuleTemplate(
        rule_code="unclear_environment_no_strategy",
        display_name="无法分类环境不选策略",
        description="市场环境不明确时，P0 不选择任何策略。",
        priority=130,
        action=StrategyRouteAction.NO_STRATEGY,
        match_conditions={"regime_codes": ["unclear_environment"]},
    ),
)
