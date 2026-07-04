"""StrategySignal 模块：显式不交易策略 calculator。
负责：消费领域市场事实，输出策略层明确“不交易”的中性 StrategySignal。
不负责：选择策略、重新计算市场事实、生成目标仓位、订单、风控审批或交易执行。
读写数据库：不涉及。
访问 Redis：不涉及。
访问外部服务：不涉及。
发送 Hermes：不涉及。
调用大模型：不涉及。
涉及交易执行：不涉及。
允许真实交易：否。
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Mapping

from apps.strategy_analysis.models import StrategySignalDirection

from ..contracts import CalculatorInput, CalculatorMetadata, CalculatorOutput, CalculatorType
from ..utils import thaw_value


REQUIRED_DOMAIN_CODES: tuple[str, ...] = (
    "market_context",
    "trend",
    "momentum",
    "volatility",
    "structure",
    "risk_state",
)
PREDICTION_HORIZON = "next_1_to_3_closed_4h"
INPUT_SCHEMA_VERSION = "1.0"
OUTPUT_SCHEMA_VERSION = "1.0"


class NoTradeStrategyCalculator:
    metadata = CalculatorMetadata(
        algorithm_name="no_trade_strategy",
        algorithm_version="v1",
        calculator_type=CalculatorType.STRATEGY_SIGNAL,
        input_schema_version=INPUT_SCHEMA_VERSION,
        output_schema_version=OUTPUT_SCHEMA_VERSION,
        deterministic=True,
        supports_dry_run=True,
        algorithm_requirement_document_path="docs/requirements/strategy_signals/no_trade_strategy_v1.md",
        implementation_document_path="docs/implementation/strategy_signal/no_trade_strategy__v1.md",
        uses_input_weights=False,
    )

    def calculate(self, calculation_input: CalculatorInput) -> CalculatorOutput:
        values = thaw_value(calculation_input.values)
        params = thaw_value(calculation_input.frozen_params)
        definition = values.get("strategy_definition")
        if not isinstance(definition, Mapping):
            return self._failed("strategy_definition_missing", "缺少 StrategyDefinition 输入。")
        strategy_code = str(definition.get("strategy_code") or "").strip()
        strategy_version = str(definition.get("strategy_version") or "").strip()
        if not strategy_code or strategy_version != "v1":
            return self._failed("strategy_definition_mismatch", "StrategyDefinition 与不交易策略算法身份不一致。")
        if definition.get("prediction_horizon") != PREDICTION_HORIZON:
            return self._failed("strategy_prediction_horizon_mismatch", "StrategyDefinition 预测周期与策略算法不一致。")

        facts_result = self._domain_facts(values.get("domain_values"))
        if "error_code" in facts_result:
            return self._failed(str(facts_result["error_code"]), str(facts_result["error_message"]))
        facts: dict[str, dict[str, Any]] = facts_result["facts"]

        reason_code = str(params.get("no_trade_reason_code") or f"{strategy_code}_no_trade").strip()
        reason_summary = str(params.get("no_trade_reason_summary_zh") or "该策略明确选择本周期不交易。").strip()
        template_label = str(params.get("template_label_zh") or "标准趋势").strip()
        used_refs = [
            {"domain_code": code, "domain_signal_value_id": facts[code]["value_id"]}
            for code in REQUIRED_DOMAIN_CODES
        ]
        domain_summary = {
            code: {
                "direction": facts[code]["direction"],
                "state_code": facts[code]["state_code"],
                "strength": facts[code]["strength"],
            }
            for code in REQUIRED_DOMAIN_CODES
        }
        strength = Decimal("0")
        confidence = Decimal("1")
        evidence_text = (
            f"{strategy_code}/v1 已执行：{template_label}模板在当前市场环境下选择不交易。"
            f"{reason_summary}"
            "该结论属于策略层结果，不是 MarketRegime 的交易动作。"
        )
        return CalculatorOutput.succeeded(
            output_schema_version=OUTPUT_SCHEMA_VERSION,
            values={
                "direction": StrategySignalDirection.NEUTRAL,
                "strength": strength,
                "confidence": confidence,
                "confidence_semantics": "explicit_strategy_no_trade",
                "prediction_horizon": PREDICTION_HORIZON,
                "used_domain_signal_value_refs": used_refs,
                "actual_input_weights": {},
                "trade_price_condition": {},
                "aggregation_snapshot": {
                    "strategy_code": strategy_code,
                    "strategy_version": strategy_version,
                    "internal_mode": "explicit_no_trade",
                    "final_direction": StrategySignalDirection.NEUTRAL,
                    "final_strength": str(strength),
                    "final_confidence": str(confidence),
                    "no_trade_reason_code": reason_code,
                    "no_trade_reason_summary_zh": reason_summary,
                    "domain_summary": domain_summary,
                },
                "conflict_snapshot": {
                    "has_conflict": False,
                    "conflicting_domain_codes": [],
                    "effect": "strategy_explicit_no_trade",
                    "blockers": [],
                    "warnings": [],
                    "reason_code": reason_code,
                },
                "evidence_text_zh": evidence_text,
            },
            evidence_items=(
                {
                    "type": "no_trade_strategy_v1",
                    "strategy_code": strategy_code,
                    "strategy_version": strategy_version,
                    "reason_code": reason_code,
                    "reason_summary_zh": reason_summary,
                    "used_domain_signal_value_ids": [facts[code]["value_id"] for code in REQUIRED_DOMAIN_CODES],
                    "domain_summary": domain_summary,
                },
            ),
            calculation_summary={
                "strategy_code": strategy_code,
                "strategy_version": strategy_version,
                "internal_mode": "explicit_no_trade",
                "direction": StrategySignalDirection.NEUTRAL,
                "strength": str(strength),
                "confidence": str(confidence),
                "reason_code": reason_code,
            },
        )

    @classmethod
    def _domain_facts(cls, raw_domain_values: Any) -> dict[str, Any]:
        if not isinstance(raw_domain_values, list | tuple):
            return {"error_code": "strategy_domain_values_missing", "error_message": "缺少领域事实输入。"}
        facts: dict[str, dict[str, Any]] = {}
        for item in raw_domain_values:
            if not isinstance(item, Mapping):
                return {"error_code": "strategy_domain_value_invalid", "error_message": "领域事实输入必须是结构化映射。"}
            code = str(item.get("domain_code") or "").strip()
            if not code:
                continue
            if code in facts:
                return {"error_code": "strategy_domain_value_duplicate", "error_message": f"领域事实重复：{code}"}
            try:
                value_id = int(item.get("domain_signal_value_id"))
            except (TypeError, ValueError):
                return {"error_code": "strategy_domain_value_invalid", "error_message": f"领域事实 ID 非法：{code}"}
            facts[code] = {
                "value_id": value_id,
                "direction": str(item.get("direction") or "neutral"),
                "state_code": str(item.get("state_code") or ""),
                "strength": str(item.get("strength") or "0"),
            }
        missing = sorted(set(REQUIRED_DOMAIN_CODES) - set(facts))
        if missing:
            return {"error_code": "strategy_required_domain_missing", "error_message": f"缺少必需领域：{','.join(missing)}"}
        return {"facts": facts}

    @classmethod
    def _failed(cls, error_code: str, error_message: str) -> CalculatorOutput:
        return CalculatorOutput.failed(
            output_schema_version=OUTPUT_SCHEMA_VERSION,
            error_code=error_code,
            error_message=error_message,
        )
