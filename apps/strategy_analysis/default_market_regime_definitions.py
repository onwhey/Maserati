"""StrategyAnalysis 模块：MarketRegimeDefinition 默认登记模板。
负责：提供受代码管理的市场环境定义清单，供 seed_market_regime_definitions 写入数据库。
不负责：计算 MarketRegimeSnapshot、选择策略、生成交易信号或订单动作。
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

from apps.strategy_calculator.market_regime.context_structure_regime import REGIME_CODES, REQUIRED_DOMAIN_CODES


@dataclass(frozen=True)
class MarketRegimeDefinitionTemplate:
    definition_code: str
    display_name: str
    description: str
    algorithm_name: str
    algorithm_version: str
    input_schema_version: str
    output_schema_version: str
    params: dict[str, Any]
    allowed_domain_codes: tuple[str, ...]
    required_domain_codes: tuple[str, ...]
    allowed_regime_codes: tuple[str, ...]


DEFAULT_MARKET_REGIME_DEFINITIONS: tuple[MarketRegimeDefinitionTemplate, ...] = (
    MarketRegimeDefinitionTemplate(
        definition_code="context_structure_regime_v1",
        display_name="大背景结构市场环境 v1",
        description=(
            "综合 market_context、trend、momentum、volatility、structure、risk_state 六个领域事实，"
            "识别当前市场环境。该定义只输出市场环境，不选择策略、不生成目标仓位或订单动作。"
        ),
        algorithm_name="context_structure_regime",
        algorithm_version="v1",
        input_schema_version="1.0",
        output_schema_version="1.0",
        params={
            "min_regime_score": "0.55",
            "min_classification_margin": "0.10",
        },
        allowed_domain_codes=REQUIRED_DOMAIN_CODES,
        required_domain_codes=REQUIRED_DOMAIN_CODES,
        allowed_regime_codes=REGIME_CODES,
    ),
)
