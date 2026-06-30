"""StrategySignalQuality 模块：默认 StrategySignalQualityRuleSet 登记模板。
负责：提供 P0 策略信号质量规则集模板，供 seed_strategy_signal_quality_rule_sets 写入数据库。
不负责：执行质量检查、修改 StrategySignal、生成目标仓位、创建订单、风控审批或交易执行。
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
class StrategySignalQualityRuleSetTemplate:
    rule_set_code: str
    rule_set_version: str
    display_name: str
    description: str
    quality_schema_version: str
    max_staleness_seconds: int
    warning_blocks_decision: bool
    fail_alert_enabled: bool
    warning_alert_enabled: bool
    consecutive_failure_threshold: int
    params: dict[str, Any]


DEFAULT_STRATEGY_SIGNAL_QUALITY_RULE_SETS: tuple[StrategySignalQualityRuleSetTemplate, ...] = (
    StrategySignalQualityRuleSetTemplate(
        rule_set_code="default_strategy_signal_quality",
        rule_set_version="1.0.0",
        display_name="P0 基础策略信号质量规则",
        description=(
            "检查 StrategySignal 是否具备进入 DecisionSnapshot 的基础合同条件："
            "结构字段完整、版本包身份一致、领域输入可追溯、聚合快照自洽、"
            "价格条件结构合法、证据覆盖实际输入，以及市场事实时效未明显过旧。"
            "P0 版本只把硬合同错误作为阻断，陈旧信号先记为 warning 且默认不阻断。"
        ),
        quality_schema_version="1.0",
        max_staleness_seconds=21600,
        warning_blocks_decision=False,
        fail_alert_enabled=True,
        warning_alert_enabled=False,
        consecutive_failure_threshold=0,
        params={
            "contract_checks": [
                "signal_contract",
                "lineage_contract",
                "domain_value_refs",
                "market_regime_snapshot",
                "trade_price_condition",
                "evidence_refs",
                "staleness",
            ],
            "staleness_severity": "warning",
            "p0_blocks_only_error_or_critical": True,
        },
    ),
)
