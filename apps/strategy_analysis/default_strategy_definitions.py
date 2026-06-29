"""StrategySignal 模块：默认 StrategyDefinition 登记模板。
负责：提供 P0 四个策略定义模板，供 seed_strategy_definitions 写入数据库。
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


def _template(strategy_code: str, display_name: str, description: str) -> StrategyDefinitionTemplate:
    return StrategyDefinitionTemplate(
        strategy_code=strategy_code,
        strategy_version="v1",
        display_name=display_name,
        description=description,
        algorithm_name=strategy_code,
        algorithm_version="v1",
        input_schema_version="1.0",
        output_schema_version="1.0",
        params={
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
)
