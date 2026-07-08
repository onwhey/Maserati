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
        display_name="【保守型】大背景结构市场环境 v1",
        description=(
            "综合 market_context、trend、momentum、volatility、structure、risk_state 六个领域事实，"
            "识别当前市场环境。该定义偏保守，遇到大背景、趋势、动能、结构冲突时更倾向输出不明确环境。"
            "该定义只输出市场环境，不选择策略、不生成目标仓位或订单动作。"
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
    MarketRegimeDefinitionTemplate(
        definition_code="context_structure_regime_v2",
        display_name="【敏捷型】大背景结构市场环境 v2",
        description=(
            "综合 market_context、trend、momentum、volatility、structure、risk_state 六个领域事实，"
            "识别当前市场环境。该定义保留大背景约束，但更早承认短周期反弹、回调和同方向家族内的阶段切换，"
            "减少长时间不明确环境。该定义只输出市场环境，不选择策略、不生成目标仓位或订单动作。"
        ),
        algorithm_name="context_structure_regime",
        algorithm_version="v2",
        input_schema_version="1.0",
        output_schema_version="1.0",
        params={
            "min_regime_score": "0.50",
            "min_classification_margin": "0.05",
            "transition_floor_score": "0.50",
        },
        allowed_domain_codes=REQUIRED_DOMAIN_CODES,
        required_domain_codes=REQUIRED_DOMAIN_CODES,
        allowed_regime_codes=REGIME_CODES,
    ),
    MarketRegimeDefinitionTemplate(
        definition_code="context_structure_regime_v3",
        display_name="【均衡型】大背景结构市场环境 v3",
        description=(
            "综合 market_context、trend、momentum、volatility、structure、risk_state 六个领域事实，"
            "识别当前市场环境。该定义继承 v2 对熊市反弹和低位震荡的敏捷识别，同时修正牛市或高位背景下"
            "对转弱、顶部反转候选和深度回调识别过慢的问题。该定义只输出市场环境，不选择策略、"
            "不生成目标仓位或订单动作。"
        ),
        algorithm_name="context_structure_regime",
        algorithm_version="v3",
        input_schema_version="1.0",
        output_schema_version="1.0",
        params={
            "min_regime_score": "0.50",
            "min_classification_margin": "0.05",
            "transition_floor_score": "0.50",
        },
        allowed_domain_codes=REQUIRED_DOMAIN_CODES,
        required_domain_codes=REQUIRED_DOMAIN_CODES,
        allowed_regime_codes=REGIME_CODES,
    ),
    MarketRegimeDefinitionTemplate(
        definition_code="context_structure_regime_v4",
        display_name="【结构增强】大背景结构市场环境 v4",
        description=(
            "综合 market_context、trend、momentum、volatility、structure、risk_state 六个领域事实，"
            "并正式消费 Structure 输出的支撑仍有效、压力仍有效、支撑跌破候选和压力突破候选证据，"
            "识别当前市场环境。该定义保留 v2/v3 已验证的经验，但核心分类逻辑独立维护；"
            "该定义只输出市场环境，不选择策略、不生成目标仓位或订单动作。"
        ),
        algorithm_name="context_structure_regime",
        algorithm_version="v4",
        input_schema_version="1.0",
        output_schema_version="1.0",
        params={
            "min_regime_score": "0.50",
            "min_classification_margin": "0.05",
            "transition_floor_score": "0.50",
        },
        allowed_domain_codes=REQUIRED_DOMAIN_CODES,
        required_domain_codes=REQUIRED_DOMAIN_CODES,
        allowed_regime_codes=REGIME_CODES,
    ),
    MarketRegimeDefinitionTemplate(
        definition_code="context_structure_regime_v5",
        display_name="【结构确认】大背景结构市场环境 v5",
        description=(
            "综合 market_context、trend、momentum、volatility、structure、risk_state 六个领域事实，"
            "并正式消费 Structure 输出的支撑仍有效、压力仍有效、支撑跌破候选和压力突破候选证据。"
            "v5 的重点不是预测反转，而是先判断大背景结构是否保持、受压、破坏候选或确认破坏，"
            "再输出当前市场环境。该定义只输出市场环境，不选择策略、不生成目标仓位或订单动作。"
        ),
        algorithm_name="context_structure_regime",
        algorithm_version="v5",
        input_schema_version="1.0",
        output_schema_version="1.0",
        params={
            "min_regime_score": "0.50",
            "min_classification_margin": "0.05",
            "transition_floor_score": "0.50",
        },
        allowed_domain_codes=REQUIRED_DOMAIN_CODES,
        required_domain_codes=REQUIRED_DOMAIN_CODES,
        allowed_regime_codes=REGIME_CODES,
    ),
    MarketRegimeDefinitionTemplate(
        definition_code="context_structure_regime_v6",
        display_name="【结构位置】大背景结构市场环境 v6",
        description=(
            "综合 market_context、trend、momentum、volatility、structure、risk_state 六个领域事实，"
            "并正式消费 Structure v3 输出的支撑、压力、夹层、突破候选、跌破候选、确认突破和确认跌破证据。"
            "v6 是独立算法，不继承 v5 的业务判断；它只识别市场环境，不选择策略、"
            "不生成目标仓位或订单动作。"
        ),
        algorithm_name="context_structure_regime",
        algorithm_version="v6",
        input_schema_version="1.0",
        output_schema_version="1.0",
        params={
            "min_regime_score": "0.50",
            "min_classification_margin": "0.05",
        },
        allowed_domain_codes=REQUIRED_DOMAIN_CODES,
        required_domain_codes=REQUIRED_DOMAIN_CODES,
        allowed_regime_codes=REGIME_CODES,
    ),
    MarketRegimeDefinitionTemplate(
        definition_code="context_structure_regime_v6_1",
        display_name="【结构稳定】大背景结构市场环境 v6.1",
        description=(
            "综合 market_context、trend、momentum、volatility、structure、risk_state 六个领域事实，"
            "并正式消费 Structure v3 输出的支撑、压力、夹层、突破候选、跌破候选、确认突破和确认跌破证据。"
            "v6.1 在 v6 的客观结构位置基础上增加主环境稳定规则：主环境优先、候选只提醒、确认才切换，"
            "避免同一连续行情内因为候选证据频繁跳变。该定义只输出市场环境，不选择策略、"
            "不生成目标仓位或订单动作。"
        ),
        algorithm_name="context_structure_regime",
        algorithm_version="v6.1",
        input_schema_version="1.0",
        output_schema_version="1.0",
        params={
            "min_regime_score": "0.50",
            "min_classification_margin": "0.05",
        },
        allowed_domain_codes=REQUIRED_DOMAIN_CODES,
        required_domain_codes=REQUIRED_DOMAIN_CODES,
        allowed_regime_codes=REGIME_CODES,
    ),
    MarketRegimeDefinitionTemplate(
        definition_code="context_structure_regime_v7",
        display_name="【状态延续】大背景结构市场环境 v7",
        description=(
            "综合 market_context、trend、momentum、volatility、structure、risk_state 六个领域事实，"
            "并消费上一周期 MarketRegime 确认状态。v7 保留 13 个市场环境口径，但增加确认环境、候选环境、观察中、确认切换机制；"
            "普通波动不会立即改写主环境，只有结构、趋势、动能或风险证据足够一致时才允许切换。"
            "该定义只输出市场环境，不选择策略、不生成目标仓位或订单动作。"
        ),
        algorithm_name="context_structure_regime",
        algorithm_version="v7",
        input_schema_version="1.0",
        output_schema_version="1.0",
        params={
            "min_regime_score": "0.50",
            "min_classification_margin": "0.05",
            "same_family_confirmation_periods": "2",
            "cross_family_confirmation_periods": "3",
            "state_retention_floor": "0.35",
        },
        allowed_domain_codes=REQUIRED_DOMAIN_CODES,
        required_domain_codes=REQUIRED_DOMAIN_CODES,
        allowed_regime_codes=REGIME_CODES,
    ),
)
