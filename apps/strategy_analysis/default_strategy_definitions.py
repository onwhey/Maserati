"""StrategySignal 模块：默认 StrategyDefinition 登记模板。
负责：提供 P0 趋势策略和显式不交易策略定义模板，供 seed_strategy_definitions 写入数据库。
不负责：执行策略算法、选择策略、生成目标仓位或订单动作。
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


REQUIRED_STRATEGY_DOMAIN_CODES: tuple[str, ...] = (
    "market_context",
    "trend",
    "momentum",
    "volatility",
    "structure",
    "risk_state",
)
P0_PREDICTION_HORIZON = "next_1_to_3_closed_4h"


@dataclass(frozen=True)
class StrategyDefinitionTemplate:
    strategy_code: str
    strategy_version: str
    display_name: str
    description: str
    algorithm_name: str
    algorithm_version: str
    input_schema_version: str
    output_schema_version: str
    params: dict[str, Any]
    allowed_domain_codes: tuple[str, ...]
    required_domain_codes: tuple[str, ...]
    uses_input_weights: bool
    domain_input_weights: dict[str, Any]
    prediction_horizon: str


def _template(
    strategy_code: str,
    display_name: str,
    description: str,
    *,
    algorithm_name: str | None = None,
    params: dict[str, Any] | None = None,
) -> StrategyDefinitionTemplate:
    return StrategyDefinitionTemplate(
        strategy_code=strategy_code,
        strategy_version="v1",
        display_name=display_name,
        description=description,
        algorithm_name=algorithm_name or strategy_code,
        algorithm_version="v1",
        input_schema_version="1.0",
        output_schema_version="1.0",
        params=params or {
            "min_strength": "0.55",
            "min_confidence": "0.55",
            "prediction_horizon": P0_PREDICTION_HORIZON,
        },
        allowed_domain_codes=REQUIRED_STRATEGY_DOMAIN_CODES,
        required_domain_codes=REQUIRED_STRATEGY_DOMAIN_CODES,
        uses_input_weights=False,
        domain_input_weights={},
        prediction_horizon=P0_PREDICTION_HORIZON,
    )


def _no_trade_template(
    strategy_code: str,
    display_name: str,
    description: str,
    *,
    reason_code: str,
    reason_summary: str,
) -> StrategyDefinitionTemplate:
    return _template(
        strategy_code,
        display_name,
        description,
        algorithm_name="no_trade_strategy",
        params={
            "prediction_horizon": P0_PREDICTION_HORIZON,
            "template_label_zh": "标准趋势",
            "no_trade_reason_code": reason_code,
            "no_trade_reason_summary_zh": reason_summary,
        },
    )


DEFAULT_STRATEGY_DEFINITIONS: tuple[StrategyDefinitionTemplate, ...] = (
    _template(
        "long_trend_following",
        "多头趋势跟随 v1",
        "用于多头趋势延续或有效向上突破环境，只输出 bullish / neutral 策略判断，不生成目标仓位或订单。",
    ),
    _template(
        "long_pullback_support",
        "多头回调支撑 v1",
        "用于大背景偏多下的回调或高位区间支撑侧环境，只输出 bullish / neutral 策略判断。",
    ),
    _template(
        "short_trend_following",
        "空头趋势跟随 v1",
        "用于空头趋势延续或有效向下跌破环境，只输出 bearish / neutral 策略判断，不生成目标仓位或订单。",
    ),
    _template(
        "short_rebound_pressure",
        "空头反弹压制 v1",
        "用于大背景偏空下的反弹或低位区间压力侧环境，只输出 bearish / neutral 策略判断。",
    ),
    _no_trade_template(
        "standard_trend__top_reversal_unconfirmed_no_trade",
        "【标准趋势】顶部反转未确认不交易 v1",
        "用于多头顶部反转候选但尚未确认的环境；策略层明确输出 neutral，不形成目标仓位或订单。",
        reason_code="top_reversal_unconfirmed_no_trade",
        reason_summary="顶部反转只是候选事实，标准趋势模板不抢顶部反转，也不继续追多。",
    ),
    _no_trade_template(
        "standard_trend__bottom_reversal_unconfirmed_no_trade",
        "【标准趋势】底部反转未确认不交易 v1",
        "用于空头底部反转候选但尚未确认的环境；策略层明确输出 neutral，不形成目标仓位或订单。",
        reason_code="bottom_reversal_unconfirmed_no_trade",
        reason_summary="底部反转只是候选事实，标准趋势模板不抢底部反转，也不继续追空。",
    ),
    _no_trade_template(
        "standard_trend__neutral_range_no_trade",
        "【标准趋势】无方向区间不交易 v1",
        "用于无方向震荡环境；策略层明确输出 neutral，不形成目标仓位或订单。",
        reason_code="neutral_range_no_trade",
        reason_summary="市场处于无方向区间，标准趋势模板没有明确顺势逻辑。",
    ),
    _no_trade_template(
        "standard_trend__high_risk_environment_no_trade",
        "【标准趋势】高风险环境不交易 v1",
        "用于高风险或信号失真的环境；策略层明确输出 neutral，不形成目标仓位或订单。",
        reason_code="high_risk_environment_no_trade",
        reason_summary="当前风险状态会降低策略信号可靠性，标准趋势模板不在该环境主动交易。",
    ),
    _no_trade_template(
        "standard_trend__unclear_environment_no_trade",
        "【标准趋势】不明确环境不交易 v1",
        "用于市场环境无法清晰分类的环境；策略层明确输出 neutral，不形成目标仓位或订单。",
        reason_code="unclear_environment_no_trade",
        reason_summary="市场事实不足以支持标准趋势模板选择方向，策略明确不交易。",
    ),
)
