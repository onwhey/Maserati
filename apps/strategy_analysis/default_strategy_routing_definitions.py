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
        display_name="多头趋势延续",
        description="当系统识别为多头趋势延续环境时，将该市场环境交给右侧绑定的策略处理。",
        priority=10,
        action=StrategyRouteAction.SELECT_STRATEGY,
        match_conditions={"regime_codes": ["bullish_trend_continuation"]},
        selected_strategy=("long_trend_following", "v1"),
    ),
    StrategyRouteRuleTemplate(
        rule_code="bullish_breakout_to_long_trend_following",
        display_name="多头向上突破",
        description="当系统识别为多头向上突破环境时，将该市场环境交给右侧绑定的策略处理。",
        priority=20,
        action=StrategyRouteAction.SELECT_STRATEGY,
        match_conditions={"regime_codes": ["bullish_breakout"]},
        selected_strategy=("long_trend_following", "v1"),
    ),
    StrategyRouteRuleTemplate(
        rule_code="bullish_pullback_to_long_pullback_support",
        display_name="多头回调",
        description="当系统识别为多头回调环境时，将该市场环境交给右侧绑定的策略处理。",
        priority=30,
        action=StrategyRouteAction.SELECT_STRATEGY,
        match_conditions={"regime_codes": ["bullish_pullback"]},
        selected_strategy=("long_pullback_support", "v1"),
    ),
    StrategyRouteRuleTemplate(
        rule_code="bullish_high_range_to_long_pullback_support",
        display_name="多头高位震荡",
        description="当系统识别为多头高位震荡环境时，将该市场环境交给右侧绑定的策略处理。",
        priority=40,
        action=StrategyRouteAction.SELECT_STRATEGY,
        match_conditions={"regime_codes": ["bullish_high_range"]},
        selected_strategy=("long_pullback_support", "v1"),
    ),
    StrategyRouteRuleTemplate(
        rule_code="bearish_trend_continuation_to_short_trend_following",
        display_name="空头趋势延续",
        description="当系统识别为空头趋势延续环境时，将该市场环境交给右侧绑定的策略处理。",
        priority=50,
        action=StrategyRouteAction.SELECT_STRATEGY,
        match_conditions={"regime_codes": ["bearish_trend_continuation"]},
        selected_strategy=("short_trend_following", "v1"),
    ),
    StrategyRouteRuleTemplate(
        rule_code="bearish_breakdown_to_short_trend_following",
        display_name="空头向下跌破",
        description="当系统识别为空头向下跌破环境时，将该市场环境交给右侧绑定的策略处理。",
        priority=60,
        action=StrategyRouteAction.SELECT_STRATEGY,
        match_conditions={"regime_codes": ["bearish_breakdown"]},
        selected_strategy=("short_trend_following", "v1"),
    ),
    StrategyRouteRuleTemplate(
        rule_code="bearish_rebound_to_short_rebound_pressure",
        display_name="空头反弹",
        description="当系统识别为空头反弹环境时，将该市场环境交给右侧绑定的策略处理。",
        priority=70,
        action=StrategyRouteAction.SELECT_STRATEGY,
        match_conditions={"regime_codes": ["bearish_rebound"]},
        selected_strategy=("short_rebound_pressure", "v1"),
    ),
    StrategyRouteRuleTemplate(
        rule_code="bearish_low_range_to_short_rebound_pressure",
        display_name="空头低位震荡",
        description="当系统识别为空头低位震荡环境时，将该市场环境交给右侧绑定的策略处理。",
        priority=80,
        action=StrategyRouteAction.SELECT_STRATEGY,
        match_conditions={"regime_codes": ["bearish_low_range"]},
        selected_strategy=("short_rebound_pressure", "v1"),
    ),
    StrategyRouteRuleTemplate(
        rule_code="bullish_top_reversal_candidate_to_standard_no_trade",
        display_name="多头顶部反转候选",
        description="当系统识别为多头顶部反转候选环境时，将该市场环境交给右侧绑定的策略处理。",
        priority=90,
        action=StrategyRouteAction.SELECT_STRATEGY,
        match_conditions={"regime_codes": ["bullish_top_reversal_candidate"]},
        selected_strategy=("standard_trend__top_reversal_unconfirmed_no_trade", "v1"),
    ),
    StrategyRouteRuleTemplate(
        rule_code="bearish_bottom_reversal_candidate_to_standard_no_trade",
        display_name="空头底部反转候选",
        description="当系统识别为空头底部反转候选环境时，将该市场环境交给右侧绑定的策略处理。",
        priority=100,
        action=StrategyRouteAction.SELECT_STRATEGY,
        match_conditions={"regime_codes": ["bearish_bottom_reversal_candidate"]},
        selected_strategy=("standard_trend__bottom_reversal_unconfirmed_no_trade", "v1"),
    ),
    StrategyRouteRuleTemplate(
        rule_code="neutral_range_to_standard_no_trade",
        display_name="无方向震荡",
        description="当系统识别为无方向震荡环境时，将该市场环境交给右侧绑定的策略处理。",
        priority=110,
        action=StrategyRouteAction.SELECT_STRATEGY,
        match_conditions={"regime_codes": ["neutral_range"]},
        selected_strategy=("standard_trend__neutral_range_no_trade", "v1"),
    ),
    StrategyRouteRuleTemplate(
        rule_code="high_risk_environment_to_standard_no_trade",
        display_name="高风险环境",
        description="当系统识别为高风险环境时，将该市场环境交给右侧绑定的策略处理。",
        priority=120,
        action=StrategyRouteAction.SELECT_STRATEGY,
        match_conditions={"regime_codes": ["high_risk_environment"]},
        selected_strategy=("standard_trend__high_risk_environment_no_trade", "v1"),
    ),
    StrategyRouteRuleTemplate(
        rule_code="unclear_environment_to_standard_no_trade",
        display_name="不明确环境",
        description="当系统识别为不明确环境时，将该市场环境交给右侧绑定的策略处理。",
        priority=130,
        action=StrategyRouteAction.SELECT_STRATEGY,
        match_conditions={"regime_codes": ["unclear_environment"]},
        selected_strategy=("standard_trend__unclear_environment_no_trade", "v1"),
    ),
)
