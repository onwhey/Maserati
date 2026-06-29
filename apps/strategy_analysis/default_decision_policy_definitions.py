"""DecisionSnapshot 模块：默认 DecisionPolicyDefinition 登记模板。
负责：提供 position_policy/v1 目标仓位映射定义模板，供 seed_decision_policy_definitions 写入数据库。
不负责：执行目标仓位算法、读取策略信号、生成订单、风控审批或交易执行。
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


@dataclass(frozen=True)
class DecisionPolicyDefinitionTemplate:
    policy_code: str
    policy_version: str
    display_name: str
    description: str
    algorithm_name: str
    algorithm_version: str
    input_schema_version: str
    output_schema_version: str
    target_schema_version: str
    params: dict[str, Any]


DEFAULT_DECISION_POLICY_DEFINITIONS: tuple[DecisionPolicyDefinitionTemplate, ...] = (
    DecisionPolicyDefinitionTemplate(
        policy_code="position_policy",
        policy_version="v1",
        display_name="目标仓位映射 v1",
        description=(
            "把已经通过 StrategySignalQuality 放行的标准化 StrategySignal "
            "按 position_policy_v1 规则映射为目标仓位意图；不读取账户、价格、订单或市场环境。"
        ),
        algorithm_name="position_policy",
        algorithm_version="v1",
        input_schema_version="1.0",
        output_schema_version="1.0",
        target_schema_version="1.0",
        params={
            "min_strength_for_target": "0.55",
            "min_confidence_for_target": "0.55",
            "max_abs_target_position_ratio": "0.50",
            "neutral_intent": "NO_TRADE",
            "weak_signal_intent": "NO_TRADE",
            "confidence_multiplier_method": "linear_confidence",
            "strength_mapping_method": "linear_from_threshold_to_max",
            "rounding_decimal_places": 4,
            "expires_after_seconds": 14400,
        },
    ),
)
