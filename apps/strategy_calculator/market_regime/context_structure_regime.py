"""MarketRegime 模块：context_structure_regime/v1 市场环境分类 calculator。
负责：消费六个 DomainSignalValue 的领域事实，输出可解释的市场环境分类、评分和证据。
不负责：计算特征、读取原子信号、选择策略、生成交易信号、生成目标仓位或订单动作。
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
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any, Mapping

from ..contracts import CalculatorInput, CalculatorMetadata, CalculatorOutput, CalculatorType


REGIME_CODES: tuple[str, ...] = (
    "high_risk_environment",
    "bullish_trend_continuation",
    "bullish_breakout",
    "bullish_pullback",
    "bullish_high_range",
    "bullish_top_reversal_candidate",
    "bearish_trend_continuation",
    "bearish_breakdown",
    "bearish_rebound",
    "bearish_low_range",
    "bearish_bottom_reversal_candidate",
    "neutral_range",
    "unclear_environment",
)

REQUIRED_DOMAIN_CODES: tuple[str, ...] = (
    "market_context",
    "trend",
    "momentum",
    "volatility",
    "structure",
    "risk_state",
)


@dataclass(frozen=True)
class DomainFact:
    value_id: int
    domain_code: str
    direction: str
    state_code: str
    strength: Decimal
    coverage_ratio: Decimal
    agreement_ratio: Decimal | None
    evidence_items: tuple[Mapping[str, Any], ...]


@dataclass(frozen=True)
class ClassificationResult:
    regime_code: str
    scores: dict[str, Decimal]
    confidence: Decimal
    margin: Decimal
    decision_reason: str
    competitors: tuple[tuple[str, Decimal], ...]


class ContextStructureRegimeCalculator:
    metadata = CalculatorMetadata(
        algorithm_name="context_structure_regime",
        algorithm_version="v1",
        calculator_type=CalculatorType.MARKET_REGIME,
        input_schema_version="1.0",
        output_schema_version="1.0",
        deterministic=True,
        supports_dry_run=True,
        algorithm_requirement_document_path="docs/requirements/market_regime/context_structure_regime_v1.md",
        implementation_document_path="docs/implementation/market_regime/context_structure_regime__v1.md",
    )
    evidence_type = "context_structure_regime_v1"

    def calculate(self, calculation_input: CalculatorInput) -> CalculatorOutput:
        values = dict(calculation_input.values)
        params = dict(calculation_input.frozen_params)
        allowed_regime_codes = self._string_tuple(values.get("allowed_regime_codes"))
        if set(allowed_regime_codes) != set(REGIME_CODES):
            return self._failed(
                "context_structure_regime_allowed_codes_invalid",
                f"context_structure_regime/{self.metadata.algorithm_version} 必须使用文档登记的完整 regime_code 集合。",
            )
        domain_values = values.get("domain_values")
        if not isinstance(domain_values, (list, tuple)):
            return self._failed("context_structure_regime_domain_values_missing", "缺少领域事实输入。")
        facts_result = self._facts_by_domain(domain_values)
        if "error_code" in facts_result:
            return self._failed(str(facts_result["error_code"]), str(facts_result["error_message"]))
        facts: dict[str, DomainFact] = facts_result["facts"]
        classification = self._classify(facts=facts, params=params)
        used_ids = [facts[code].value_id for code in REQUIRED_DOMAIN_CODES]
        return CalculatorOutput.succeeded(
            output_schema_version=self.metadata.output_schema_version,
            values={
                "regime_code": classification.regime_code,
                "regime_scores": classification.scores,
                "regime_confidence": classification.confidence,
                "classification_margin": classification.margin,
                "used_domain_signal_value_ids": used_ids,
                "evidence_text_zh": self._evidence_text(facts=facts, classification=classification),
            },
            evidence_items=(
                {
                    "type": self.evidence_type,
                    "selected_regime_code": classification.regime_code,
                    "decision_reason": classification.decision_reason,
                    "competitors": [
                        {"regime_code": code, "score": str(score)} for code, score in classification.competitors
                    ],
                    "domain_summary": {
                        code: {
                            "direction": facts[code].direction,
                            "state_code": facts[code].state_code,
                            "strength": str(facts[code].strength),
                        }
                        for code in REQUIRED_DOMAIN_CODES
                    },
                },
            ),
            calculation_summary={
                "selected_regime_code": classification.regime_code,
                "decision_reason": classification.decision_reason,
                "used_domain_count": len(used_ids),
            },
        )

    def _classify(self, *, facts: dict[str, DomainFact], params: Mapping[str, Any]) -> ClassificationResult:
        scores = {code: Decimal("0") for code in REGIME_CODES}
        risk = facts["risk_state"]
        self._score_regular_candidates(scores=scores, facts=facts)
        if risk.state_code == "risk_high_signal_unreliable":
            scores["high_risk_environment"] = Decimal("1.00")
            return self._select(
                regime_code="high_risk_environment",
                scores=scores,
                decision_reason="risk_state 明确提示普通环境分类可靠性显著下降，优先归为高风险环境。",
            )
        if risk.state_code == "risk_unclear":
            scores["unclear_environment"] = max(scores["unclear_environment"], Decimal("0.80"))
            return self._select(
                regime_code="unclear_environment",
                scores=scores,
                decision_reason="risk_state 本身不明确，不能伪装成普通多头、空头或震荡环境。",
            )

        ordered = self._ordered_scores(scores)
        top_code, top_score = ordered[0]
        second_score = ordered[1][1] if len(ordered) > 1 else Decimal("0")
        priority_code = self._priority_regime_code(scores=scores, facts=facts, top_code=top_code)
        if priority_code:
            return self._select(
                regime_code=priority_code,
                scores=scores,
                decision_reason=f"{priority_code} 满足专门优先级规则，优先于同方向普通趋势环境。",
            )
        min_score = self._decimal_param(params, "min_regime_score", Decimal("0.55"))
        min_margin = self._decimal_param(params, "min_classification_margin", Decimal("0.10"))
        if top_score < min_score:
            scores["unclear_environment"] = max(scores["unclear_environment"], top_score)
            return self._select(
                regime_code="unclear_environment",
                scores=scores,
                decision_reason="最高候选分数不足，输出不明确环境。",
            )
        if top_score - second_score < min_margin:
            scores["unclear_environment"] = max(scores["unclear_environment"], top_score)
            return self._select(
                regime_code="unclear_environment",
                scores=scores,
                decision_reason="主要候选之间差距过小，输出不明确环境。",
            )
        return self._select(
            regime_code=top_code,
            scores=scores,
            decision_reason="普通候选分数满足最低分与最小差距要求。",
        )

    def _priority_regime_code(
        self,
        *,
        scores: Mapping[str, Decimal],
        facts: dict[str, DomainFact],
        top_code: str,
    ) -> str:
        structure = facts["structure"]
        if (
            top_code == "bullish_breakout"
            and scores["bullish_breakout"] >= Decimal("0.68")
            and self._structure_break(structure, "bullish")
        ):
            return "bullish_breakout"
        if (
            top_code == "bearish_breakdown"
            and scores["bearish_breakdown"] >= Decimal("0.68")
            and self._structure_break(structure, "bearish")
        ):
            return "bearish_breakdown"
        return ""

    def _score_regular_candidates(self, *, scores: dict[str, Decimal], facts: dict[str, DomainFact]) -> None:
        context = facts["market_context"]
        trend = facts["trend"]
        momentum = facts["momentum"]
        volatility = facts["volatility"]
        structure = facts["structure"]
        risk = facts["risk_state"]
        risk_ok_bonus = Decimal("0.05") if risk.state_code in {"risk_clear", "risk_elevated_classifiable"} else Decimal("0")
        volatility_drag = Decimal("0.08") if volatility.state_code == "volatility_extreme" else Decimal("0")

        scores["bullish_trend_continuation"] = self._cap(
            self._context_bonus(context, "bullish")
            + self._trend_bonus(trend, "bullish", aligned=True)
            + self._momentum_bonus(momentum, "bullish")
            + self._structure_not_broken_bonus(structure, "bullish")
            + risk_ok_bonus
            - volatility_drag
        )
        scores["bullish_breakout"] = self._cap(
            self._context_not_opposite_bonus(context, "bullish")
            + self._structure_break_bonus(structure, "bullish")
            + self._momentum_bonus(momentum, "bullish")
            + self._trend_bonus(trend, "bullish", aligned=False)
            + risk_ok_bonus
            - volatility_drag
        )
        if not self._structure_break(structure, "bullish"):
            scores["bullish_breakout"] = min(scores["bullish_breakout"], Decimal("0.45"))

        scores["bullish_pullback"] = self._cap(
            self._context_bonus(context, "bullish")
            + self._trend_primary_bonus(trend, "bullish")
            + self._short_cycle_counter_bonus(trend, momentum, "bullish")
            + self._structure_zone_bonus(structure, "support")
            + risk_ok_bonus
        )
        scores["bullish_high_range"] = self._cap(
            self._context_bonus(context, "bullish")
            + self._context_zone_bonus(context, "high")
            + self._structure_range_bonus(structure, "resistance")
            + self._progress_slow_bonus(trend, momentum)
            + self._range_volatility_bonus(volatility)
            + risk_ok_bonus
        )
        if context.direction != "bullish":
            scores["bullish_high_range"] = min(scores["bullish_high_range"], Decimal("0.45"))

        scores["bullish_top_reversal_candidate"] = self._cap(
            self._context_bonus(context, "bullish")
            + self._context_zone_bonus(context, "high")
            + self._structure_zone_bonus(structure, "resistance")
            + self._minor_break_bonus(structure, "bearish")
            + self._momentum_reversal_bonus(momentum, "bearish")
            + risk_ok_bonus
        )

        scores["bearish_trend_continuation"] = self._cap(
            self._context_bonus(context, "bearish")
            + self._trend_bonus(trend, "bearish", aligned=True)
            + self._momentum_bonus(momentum, "bearish")
            + self._structure_not_broken_bonus(structure, "bearish")
            + risk_ok_bonus
            - volatility_drag
        )
        scores["bearish_breakdown"] = self._cap(
            self._context_not_opposite_bonus(context, "bearish")
            + self._structure_break_bonus(structure, "bearish")
            + self._momentum_bonus(momentum, "bearish")
            + self._trend_bonus(trend, "bearish", aligned=False)
            + risk_ok_bonus
            - volatility_drag
        )
        if not self._structure_break(structure, "bearish"):
            scores["bearish_breakdown"] = min(scores["bearish_breakdown"], Decimal("0.45"))

        scores["bearish_rebound"] = self._cap(
            self._context_bonus(context, "bearish")
            + self._trend_primary_bonus(trend, "bearish")
            + self._short_cycle_counter_bonus(trend, momentum, "bearish")
            + self._structure_zone_bonus(structure, "resistance")
            + risk_ok_bonus
        )
        scores["bearish_low_range"] = self._cap(
            self._context_bonus(context, "bearish")
            + self._context_zone_bonus(context, "low")
            + self._structure_range_bonus(structure, "support")
            + self._progress_slow_bonus(trend, momentum)
            + self._range_volatility_bonus(volatility)
            + risk_ok_bonus
        )
        if context.direction != "bearish":
            scores["bearish_low_range"] = min(scores["bearish_low_range"], Decimal("0.45"))

        scores["bearish_bottom_reversal_candidate"] = self._cap(
            self._context_bonus(context, "bearish")
            + self._context_zone_bonus(context, "low")
            + self._structure_zone_bonus(structure, "support")
            + self._minor_break_bonus(structure, "bullish")
            + self._momentum_reversal_bonus(momentum, "bullish")
            + risk_ok_bonus
        )

        scores["neutral_range"] = self._cap(
            (Decimal("0.30") if context.direction == "neutral" else Decimal("0"))
            + (Decimal("0.20") if trend.direction == "neutral" else Decimal("0"))
            + self._structure_range_bonus(structure, "middle")
            + self._range_volatility_bonus(volatility)
            + risk_ok_bonus
        )
        if context.direction != "neutral":
            scores["neutral_range"] = min(scores["neutral_range"], Decimal("0.50"))

        scores["unclear_environment"] = max(
            Decimal("0.25"),
            self._conflict_score(context=context, trend=trend, momentum=momentum, structure=structure),
        )

    @staticmethod
    def _context_bonus(context: DomainFact, direction: str) -> Decimal:
        return Decimal("0.28") if context.direction == direction else Decimal("0")

    @staticmethod
    def _context_not_opposite_bonus(context: DomainFact, direction: str) -> Decimal:
        opposite = "bearish" if direction == "bullish" else "bullish"
        if context.direction == direction:
            return Decimal("0.22")
        return Decimal("0.10") if context.direction != opposite else Decimal("0")

    @staticmethod
    def _context_zone_bonus(context: DomainFact, zone: str) -> Decimal:
        return Decimal("0.12") if zone in context.state_code else Decimal("0")

    @staticmethod
    def _trend_bonus(trend: DomainFact, direction: str, *, aligned: bool) -> Decimal:
        if trend.direction != direction:
            return Decimal("0")
        if aligned and "aligned" in trend.state_code:
            return Decimal("0.25")
        return Decimal("0.16")

    @staticmethod
    def _trend_primary_bonus(trend: DomainFact, direction: str) -> Decimal:
        return Decimal("0.22") if trend.direction == direction else Decimal("0")

    @staticmethod
    def _momentum_bonus(momentum: DomainFact, direction: str) -> Decimal:
        if momentum.direction != direction:
            return Decimal("0")
        if "exhausting" in momentum.state_code:
            return Decimal("0.08")
        if "strengthening" in momentum.state_code:
            return Decimal("0.22")
        return Decimal("0.18")

    @staticmethod
    def _momentum_reversal_bonus(momentum: DomainFact, direction: str) -> Decimal:
        if momentum.direction == direction:
            return Decimal("0.20")
        if "exhausting" in momentum.state_code:
            return Decimal("0.16")
        return Decimal("0")

    @staticmethod
    def _short_cycle_counter_bonus(trend: DomainFact, momentum: DomainFact, primary_direction: str) -> Decimal:
        opposite = "bearish" if primary_direction == "bullish" else "bullish"
        if opposite in trend.state_code or momentum.direction == opposite or "exhausting" in momentum.state_code:
            return Decimal("0.20")
        return Decimal("0")

    @staticmethod
    def _progress_slow_bonus(trend: DomainFact, momentum: DomainFact) -> Decimal:
        if trend.direction == "neutral" or "unclear" in trend.state_code:
            return Decimal("0.12")
        if "exhausting" in momentum.state_code or "choppy" in momentum.state_code:
            return Decimal("0.12")
        return Decimal("0")

    @staticmethod
    def _structure_break(structure: DomainFact, direction: str) -> bool:
        token = "breakout_up" if direction == "bullish" else "breakdown_down"
        return token in structure.state_code

    def _structure_break_bonus(self, structure: DomainFact, direction: str) -> Decimal:
        return Decimal("0.30") if self._structure_break(structure, direction) else Decimal("0")

    @staticmethod
    def _minor_break_bonus(structure: DomainFact, direction: str) -> Decimal:
        token = "minor_breakout" if direction == "bullish" else "minor_breakdown"
        return Decimal("0.18") if token in structure.state_code else Decimal("0")

    @staticmethod
    def _structure_not_broken_bonus(structure: DomainFact, direction: str) -> Decimal:
        opposite = "breakdown_down" if direction == "bullish" else "breakout_up"
        return Decimal("0.10") if opposite not in structure.state_code else Decimal("0")

    @staticmethod
    def _structure_zone_bonus(structure: DomainFact, zone: str) -> Decimal:
        if zone == "support":
            return Decimal("0.20") if "support" in structure.state_code or "lower_half" in structure.state_code else Decimal("0")
        if zone == "resistance":
            return Decimal("0.20") if "resistance" in structure.state_code or "upper_half" in structure.state_code else Decimal("0")
        return Decimal("0")

    @staticmethod
    def _structure_range_bonus(structure: DomainFact, preferred_zone: str) -> Decimal:
        state = structure.state_code
        base = Decimal("0.16") if "range" in state or "near_" in state else Decimal("0")
        if preferred_zone == "support" and ("support" in state or "lower_half" in state):
            base += Decimal("0.08")
        elif preferred_zone == "resistance" and ("resistance" in state or "upper_half" in state):
            base += Decimal("0.08")
        elif preferred_zone == "middle" and ("range_middle" in state or "range" in state):
            base += Decimal("0.08")
        return min(Decimal("0.24"), base)

    @staticmethod
    def _range_volatility_bonus(volatility: DomainFact) -> Decimal:
        if volatility.state_code in {"volatility_high", "volatility_mixed", "volatility_low_compression"}:
            return Decimal("0.10")
        if volatility.state_code in {"volatility_normal", "volatility_low"}:
            return Decimal("0.08")
        return Decimal("0")

    @staticmethod
    def _conflict_score(
        *,
        context: DomainFact,
        trend: DomainFact,
        momentum: DomainFact,
        structure: DomainFact,
    ) -> Decimal:
        score = Decimal("0.25")
        if context.direction in {"bullish", "bearish"} and trend.direction not in {context.direction, "neutral"}:
            score += Decimal("0.20")
        if trend.direction in {"bullish", "bearish"} and momentum.direction not in {trend.direction, "neutral"}:
            score += Decimal("0.15")
        if ("breakout_up" in structure.state_code and context.direction == "bearish") or (
            "breakdown_down" in structure.state_code and context.direction == "bullish"
        ):
            score += Decimal("0.20")
        return min(Decimal("0.85"), score)

    def _select(self, *, regime_code: str, scores: dict[str, Decimal], decision_reason: str) -> ClassificationResult:
        rounded_scores = {code: self._round_score(score) for code, score in scores.items()}
        ordered = self._ordered_scores(rounded_scores)
        selected_score = rounded_scores[regime_code]
        second_score = max((score for code, score in ordered if code != regime_code), default=Decimal("0"))
        margin = self._round_score(selected_score - second_score)
        return ClassificationResult(
            regime_code=regime_code,
            scores=rounded_scores,
            confidence=self._round_score(selected_score),
            margin=margin,
            decision_reason=decision_reason,
            competitors=tuple(ordered[:3]),
        )

    @staticmethod
    def _ordered_scores(scores: Mapping[str, Decimal]) -> list[tuple[str, Decimal]]:
        priority = {code: index for index, code in enumerate(REGIME_CODES)}
        return sorted(scores.items(), key=lambda item: (item[1], -priority[item[0]]), reverse=True)

    def _facts_by_domain(self, domain_values: list[Any] | tuple[Any, ...]) -> dict[str, Any]:
        facts: dict[str, DomainFact] = {}
        for item in domain_values:
            if not isinstance(item, Mapping):
                return {"error_code": "context_structure_regime_domain_value_invalid", "error_message": "领域事实必须是结构化对象。"}
            try:
                fact = DomainFact(
                    value_id=int(item["domain_signal_value_id"]),
                    domain_code=str(item["domain_code"]),
                    direction=str(item.get("direction") or "none"),
                    state_code=str(item.get("state_code") or ""),
                    strength=self._decimal_ratio(item.get("strength")),
                    coverage_ratio=self._decimal_ratio(item.get("coverage_ratio")),
                    agreement_ratio=self._decimal_ratio(item.get("agreement_ratio"), allow_none=True),
                    evidence_items=self._evidence_tuple(item.get("evidence_items")),
                )
            except (KeyError, TypeError, ValueError) as exc:
                return {
                    "error_code": "context_structure_regime_domain_value_invalid",
                    "error_message": f"领域事实字段不合法：{exc}",
                }
            if fact.domain_code in facts:
                return {"error_code": "context_structure_regime_domain_duplicate", "error_message": "领域事实重复。"}
            facts[fact.domain_code] = fact
        missing = [code for code in REQUIRED_DOMAIN_CODES if code not in facts]
        if missing:
            return {
                "error_code": "context_structure_regime_required_domain_missing",
                "error_message": f"缺少必要领域事实：{','.join(missing)}",
            }
        return {"facts": facts}

    @staticmethod
    def _evidence_text(*, facts: dict[str, DomainFact], classification: ClassificationResult) -> str:
        competitors = "、".join(f"{code}={score}" for code, score in classification.competitors if code != classification.regime_code)
        return (
            f"MarketRegime 已将本轮六个领域事实归类为 {classification.regime_code}。"
            f"市场大背景={facts['market_context'].direction}/{facts['market_context'].state_code}；"
            f"趋势={facts['trend'].direction}/{facts['trend'].state_code}；"
            f"动能={facts['momentum'].direction}/{facts['momentum'].state_code}；"
            f"波动={facts['volatility'].state_code}；"
            f"结构={facts['structure'].direction}/{facts['structure'].state_code}；"
            f"风险={facts['risk_state'].state_code}。"
            f"选择原因：{classification.decision_reason}"
            f"主要竞争候选：{competitors or '无'}。该结论只描述市场环境，不生成策略、目标仓位或订单动作。"
        )

    def _failed(self, error_code: str, error_message: str) -> CalculatorOutput:
        return CalculatorOutput.failed(
            output_schema_version=self.metadata.output_schema_version,
            error_code=error_code,
            error_message=error_message,
        )

    @staticmethod
    def _string_tuple(value: Any) -> tuple[str, ...]:
        if not isinstance(value, (list, tuple)):
            return ()
        return tuple(str(item) for item in value if str(item).strip())

    @staticmethod
    def _evidence_tuple(value: Any) -> tuple[Mapping[str, Any], ...]:
        if not isinstance(value, (list, tuple)):
            return ()
        return tuple(item for item in value if isinstance(item, Mapping))

    @staticmethod
    def _decimal_param(params: Mapping[str, Any], key: str, default: Decimal) -> Decimal:
        try:
            value = Decimal(str(params.get(key, default)))
        except (InvalidOperation, TypeError, ValueError):
            return default
        if not value.is_finite() or value < 0 or value > 1:
            return default
        return value

    @staticmethod
    def _decimal_ratio(value: Any, *, allow_none: bool = False) -> Decimal | None:
        if value is None:
            if allow_none:
                return None
            raise ValueError("ratio is required")
        try:
            result = Decimal(str(value))
        except (InvalidOperation, TypeError, ValueError) as exc:
            raise ValueError("ratio invalid") from exc
        if not result.is_finite() or result < 0 or result > 1:
            raise ValueError("ratio must be 0..1")
        return result

    @staticmethod
    def _round_score(value: Decimal) -> Decimal:
        return value.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)

    @classmethod
    def _cap(cls, value: Decimal) -> Decimal:
        return cls._round_score(max(Decimal("0"), min(Decimal("1"), value)))


class ContextStructureRegimeV2Calculator(ContextStructureRegimeCalculator):
    """MarketRegime 模块：context_structure_regime/v2 市场环境分类 calculator。

    负责：复用六个领域事实，输出更敏捷但仍不越权的市场环境分类。
    不负责：计算特征、读取原子信号、选择策略、生成交易信号、生成目标仓位或订单动作。
    读写数据库：不涉及。
    访问 Redis：不涉及。
    访问外部服务：不涉及。
    发送 Hermes：不涉及。
    调用大模型：不涉及。
    涉及交易执行：不涉及。
    允许真实交易：否。
    """

    metadata = CalculatorMetadata(
        algorithm_name="context_structure_regime",
        algorithm_version="v2",
        calculator_type=CalculatorType.MARKET_REGIME,
        input_schema_version="1.0",
        output_schema_version="1.0",
        deterministic=True,
        supports_dry_run=True,
        algorithm_requirement_document_path="docs/requirements/market_regime/context_structure_regime_v2.md",
        implementation_document_path="docs/implementation/market_regime/context_structure_regime__v2.md",
    )
    evidence_type = "context_structure_regime_v2"

    def _classify(self, *, facts: dict[str, DomainFact], params: Mapping[str, Any]) -> ClassificationResult:
        scores = {code: Decimal("0") for code in REGIME_CODES}
        risk = facts["risk_state"]
        self._score_regular_candidates(scores=scores, facts=facts)
        if risk.state_code == "risk_high_signal_unreliable":
            scores["high_risk_environment"] = Decimal("1.00")
            return self._select(
                regime_code="high_risk_environment",
                scores=scores,
                decision_reason="risk_state 明确提示普通环境分类可靠性显著下降，优先归为高风险环境。",
            )
        if risk.state_code == "risk_unclear":
            scores["unclear_environment"] = max(scores["unclear_environment"], Decimal("0.80"))
            return self._select(
                regime_code="unclear_environment",
                scores=scores,
                decision_reason="risk_state 本身不明确，不能伪装成普通多头、空头或震荡环境。",
            )

        ordered = self._ordered_scores(scores)
        top_code, top_score = ordered[0]
        second_code, second_score = ordered[1] if len(ordered) > 1 else ("", Decimal("0"))
        priority_code = self._priority_regime_code(scores=scores, facts=facts, top_code=top_code)
        if priority_code:
            return self._select(
                regime_code=priority_code,
                scores=scores,
                decision_reason=f"{priority_code} 满足专门优先级规则，优先于同方向普通趋势环境。",
            )

        min_score = self._decimal_param(params, "min_regime_score", Decimal("0.50"))
        min_margin = self._decimal_param(params, "min_classification_margin", Decimal("0.05"))
        transition_floor = self._decimal_param(params, "transition_floor_score", Decimal("0.50"))
        if top_score < min_score:
            transition_code = self._transition_regime_code(scores=scores, facts=facts, floor=transition_floor)
            if transition_code:
                return self._select(
                    regime_code=transition_code,
                    scores=scores,
                    decision_reason=(
                        "v2 在大背景和风险清晰时，允许已持续出现的短周期反弹/回调先形成具体环境，"
                        "不因普通候选总分略低而长期停放在不明确环境。"
                    ),
                )
            scores["unclear_environment"] = max(scores["unclear_environment"], top_score)
            return self._select(
                regime_code="unclear_environment",
                scores=scores,
                decision_reason="最高候选分数不足，输出不明确环境。",
            )
        if top_score - second_score < min_margin:
            responsive_code = self._responsive_tie_break_code(
                scores=scores,
                facts=facts,
                top_code=top_code,
                second_code=second_code,
                floor=transition_floor,
            )
            if responsive_code:
                return self._select(
                    regime_code=responsive_code,
                    scores=scores,
                    decision_reason=(
                        "v2 识别到主要候选属于同一大方向家族或明确短周期修复阶段，"
                        "优先输出更具体的市场环境，而不是长期输出不明确环境。"
                    ),
                )
            scores["unclear_environment"] = max(scores["unclear_environment"], top_score)
            return self._select(
                regime_code="unclear_environment",
                scores=scores,
                decision_reason="主要候选之间差距过小且无法稳定收敛到同一市场家族，输出不明确环境。",
            )
        return self._select(
            regime_code=top_code,
            scores=scores,
            decision_reason="普通候选分数满足 v2 最低分与最小差距要求。",
        )

    def _responsive_tie_break_code(
        self,
        *,
        scores: Mapping[str, Decimal],
        facts: dict[str, DomainFact],
        top_code: str,
        second_code: str,
        floor: Decimal,
    ) -> str:
        transition_code = self._transition_regime_code(scores=scores, facts=facts, floor=floor)
        if transition_code:
            return transition_code
        top_family = self._regime_family(top_code)
        second_family = self._regime_family(second_code)
        if (
            top_family in {"bullish", "bearish"}
            and top_family == second_family
            and scores[top_code] >= floor
        ):
            return top_code
        return ""

    def _transition_regime_code(
        self,
        *,
        scores: Mapping[str, Decimal],
        facts: dict[str, DomainFact],
        floor: Decimal,
    ) -> str:
        context = facts["market_context"]
        trend = facts["trend"]
        momentum = facts["momentum"]
        if context.direction == "bearish" and self._short_cycle_repairing_against_context(
            trend=trend, momentum=momentum, context_direction="bearish"
        ):
            return self._best_above_floor(scores, floor, ("bearish_rebound", "bearish_low_range"))
        if context.direction == "bullish" and self._short_cycle_repairing_against_context(
            trend=trend, momentum=momentum, context_direction="bullish"
        ):
            return self._best_above_floor(scores, floor, ("bullish_pullback", "bullish_high_range"))
        return ""

    @staticmethod
    def _short_cycle_repairing_against_context(
        *,
        trend: DomainFact,
        momentum: DomainFact,
        context_direction: str,
    ) -> bool:
        opposite = "bullish" if context_direction == "bearish" else "bearish"
        trend_token_matches = (
            "rebound" in trend.state_code
            if context_direction == "bearish"
            else "pullback" in trend.state_code
        )
        return (
            opposite in trend.state_code
            or opposite in momentum.state_code
            or momentum.direction == opposite
            or trend_token_matches
        )

    @staticmethod
    def _best_above_floor(scores: Mapping[str, Decimal], floor: Decimal, codes: tuple[str, ...]) -> str:
        eligible = [(code, scores[code]) for code in codes if scores[code] >= floor]
        if not eligible:
            return ""
        return max(eligible, key=lambda item: item[1])[0]

    @staticmethod
    def _regime_family(regime_code: str) -> str:
        if regime_code.startswith("bullish_"):
            return "bullish"
        if regime_code.startswith("bearish_"):
            return "bearish"
        if regime_code == "neutral_range":
            return "neutral"
        if regime_code == "high_risk_environment":
            return "risk"
        return "unclear"


class ContextStructureRegimeV3Calculator(ContextStructureRegimeV2Calculator):
    """MarketRegime 模块：context_structure_regime/v3 市场环境分类 calculator。

    负责：在 v2 已改善熊市反弹识别的基础上，补充多头高位/回调转弱识别。
    不负责：计算特征、读取原子信号、选择策略、生成交易信号、生成目标仓位或订单动作。
    读写数据库：不涉及。
    访问 Redis：不涉及。
    访问外部服务：不涉及。
    发送 Hermes：不涉及。
    调用大模型：不涉及。
    涉及交易执行：不涉及。
    允许真实交易：否。
    """

    metadata = CalculatorMetadata(
        algorithm_name="context_structure_regime",
        algorithm_version="v3",
        calculator_type=CalculatorType.MARKET_REGIME,
        input_schema_version="1.0",
        output_schema_version="1.0",
        deterministic=True,
        supports_dry_run=True,
        algorithm_requirement_document_path="docs/requirements/market_regime/context_structure_regime_v3.md",
        implementation_document_path="docs/implementation/market_regime/context_structure_regime__v3.md",
    )
    evidence_type = "context_structure_regime_v3"

    def _score_regular_candidates(self, *, scores: dict[str, Decimal], facts: dict[str, DomainFact]) -> None:
        super()._score_regular_candidates(scores=scores, facts=facts)
        self._apply_bullish_weakening_adjustments(scores=scores, facts=facts)

    def _apply_bullish_weakening_adjustments(
        self,
        *,
        scores: dict[str, Decimal],
        facts: dict[str, DomainFact],
    ) -> None:
        context = facts["market_context"]
        if context.direction != "bullish":
            return

        trend = facts["trend"]
        momentum = facts["momentum"]
        volatility = facts["volatility"]
        structure = facts["structure"]
        pressure = self._bullish_weakening_pressure(
            trend=trend,
            momentum=momentum,
            volatility=volatility,
            structure=structure,
        )
        if pressure <= Decimal("0"):
            return

        if self._trend_has_bearish_primary(trend):
            scores["bullish_trend_continuation"] = min(scores["bullish_trend_continuation"], Decimal("0.35"))
            scores["bullish_pullback"] = min(scores["bullish_pullback"], Decimal("0.52"))
            scores["bullish_high_range"] = min(scores["bullish_high_range"], Decimal("0.55"))
        elif self._trend_has_bearish_short_cycle(trend) or momentum.direction == "bearish":
            scores["bullish_trend_continuation"] = min(scores["bullish_trend_continuation"], Decimal("0.45"))

        top_reversal_boost = pressure
        if "high" in context.state_code or "upper" in structure.state_code or "resistance" in structure.state_code:
            top_reversal_boost += Decimal("0.08")
        if "conflicted" in structure.state_code:
            top_reversal_boost += Decimal("0.06")

        scores["bullish_top_reversal_candidate"] = self._cap(
            scores["bullish_top_reversal_candidate"] + top_reversal_boost
        )

        if volatility.state_code == "volatility_extreme":
            scores["unclear_environment"] = max(scores["unclear_environment"], Decimal("0.45"))

    @staticmethod
    def _trend_has_bearish_primary(trend: DomainFact) -> bool:
        return trend.direction == "bearish" or "1d_bearish" in trend.state_code

    @staticmethod
    def _trend_has_bearish_short_cycle(trend: DomainFact) -> bool:
        return "4h_bearish" in trend.state_code or "minor_bearish" in trend.state_code

    def _bullish_weakening_pressure(
        self,
        *,
        trend: DomainFact,
        momentum: DomainFact,
        volatility: DomainFact,
        structure: DomainFact,
    ) -> Decimal:
        pressure = Decimal("0")
        if self._trend_has_bearish_primary(trend):
            pressure += Decimal("0.22")
        elif self._trend_has_bearish_short_cycle(trend):
            pressure += Decimal("0.12")

        if "aligned" in trend.state_code and trend.direction == "bearish":
            pressure += Decimal("0.08")
        if "rebound" in trend.state_code and self._trend_has_bearish_primary(trend):
            pressure += Decimal("0.05")
        if momentum.direction == "bearish":
            pressure += Decimal("0.12")
        if "strengthening" in momentum.state_code and momentum.direction == "bearish":
            pressure += Decimal("0.06")
        if volatility.state_code == "volatility_high":
            pressure += Decimal("0.08")
        elif volatility.state_code == "volatility_extreme":
            pressure += Decimal("0.12")
        if "breakdown" in structure.state_code:
            pressure += Decimal("0.10")

        return min(Decimal("0.45"), pressure)


class ContextStructureRegimeV4Calculator(ContextStructureRegimeCalculator):
    """MarketRegime 模块：context_structure_regime/v4 市场环境分类 calculator。

    负责：独立消费六个领域事实和 Structure 结构证据，输出结构证据增强版市场环境分类。
    不负责：计算特征、读取原子信号、选择策略、生成交易信号、生成目标仓位或订单动作。
    读写数据库：不涉及。
    访问 Redis：不涉及。
    访问外部服务：不涉及。
    发送 Hermes：不涉及。
    调用大模型：不涉及。
    涉及交易执行：不涉及。
    允许真实交易：否。
    """

    metadata = CalculatorMetadata(
        algorithm_name="context_structure_regime",
        algorithm_version="v4",
        calculator_type=CalculatorType.MARKET_REGIME,
        input_schema_version="1.0",
        output_schema_version="1.0",
        deterministic=True,
        supports_dry_run=True,
        algorithm_requirement_document_path="docs/requirements/market_regime/context_structure_regime_v4.md",
        implementation_document_path="docs/implementation/market_regime/context_structure_regime__v4.md",
    )
    evidence_type = "context_structure_regime_v4"

    def calculate(self, calculation_input: CalculatorInput) -> CalculatorOutput:
        values = dict(calculation_input.values)
        params = dict(calculation_input.frozen_params)
        allowed_regime_codes = self._string_tuple(values.get("allowed_regime_codes"))
        if set(allowed_regime_codes) != set(REGIME_CODES):
            return self._failed(
                "context_structure_regime_allowed_codes_invalid",
                "context_structure_regime/v4 必须使用文档登记的完整 regime_code 集合。",
            )
        domain_values = values.get("domain_values")
        if not isinstance(domain_values, (list, tuple)):
            return self._failed("context_structure_regime_domain_values_missing", "缺少领域事实输入。")
        facts_result = self._facts_by_domain(domain_values)
        if "error_code" in facts_result:
            return self._failed(str(facts_result["error_code"]), str(facts_result["error_message"]))
        facts: dict[str, DomainFact] = facts_result["facts"]
        structure_evidence = self._extract_structure_evidence(facts["structure"])
        if structure_evidence is None:
            return self._failed(
                "market_regime_structure_evidence_missing",
                "context_structure_regime/v4 必须消费 Structure 输出的 structure_evidence；当前输入缺少该证据。",
            )

        classification = self._classify_v4(facts=facts, params=params, structure_evidence=structure_evidence)
        used_ids = [facts[code].value_id for code in REQUIRED_DOMAIN_CODES]
        return CalculatorOutput.succeeded(
            output_schema_version=self.metadata.output_schema_version,
            values={
                "regime_code": classification.regime_code,
                "regime_scores": classification.scores,
                "regime_confidence": classification.confidence,
                "classification_margin": classification.margin,
                "used_domain_signal_value_ids": used_ids,
                "evidence_text_zh": self._evidence_text_v4(
                    facts=facts,
                    classification=classification,
                    structure_evidence=structure_evidence,
                ),
            },
            evidence_items=(
                {
                    "type": self.evidence_type,
                    "selected_regime_code": classification.regime_code,
                    "decision_reason": classification.decision_reason,
                    "competitors": [
                        {"regime_code": code, "score": str(score)} for code, score in classification.competitors
                    ],
                    "structure_evidence": structure_evidence,
                    "domain_summary": {
                        code: {
                            "direction": facts[code].direction,
                            "state_code": facts[code].state_code,
                            "strength": str(facts[code].strength),
                        }
                        for code in REQUIRED_DOMAIN_CODES
                    },
                },
            ),
            calculation_summary={
                "selected_regime_code": classification.regime_code,
                "decision_reason": classification.decision_reason,
                "used_domain_count": len(used_ids),
                "structure_primary_state_zh": str(structure_evidence.get("primary_state_zh") or ""),
            },
        )

    def _classify_v4(
        self,
        *,
        facts: dict[str, DomainFact],
        params: Mapping[str, Any],
        structure_evidence: Mapping[str, Any],
    ) -> ClassificationResult:
        scores = {code: Decimal("0") for code in REGIME_CODES}
        self._score_v4_candidates(scores=scores, facts=facts, structure_evidence=structure_evidence)

        risk = facts["risk_state"]
        if risk.state_code == "risk_high_signal_unreliable":
            scores["high_risk_environment"] = Decimal("1.00")
            return self._select(
                regime_code="high_risk_environment",
                scores=scores,
                decision_reason="risk_state 明确提示普通环境分类可靠性显著下降，优先归为高风险环境。",
            )
        if risk.state_code == "risk_unclear":
            scores["unclear_environment"] = max(scores["unclear_environment"], Decimal("0.80"))
            return self._select(
                regime_code="unclear_environment",
                scores=scores,
                decision_reason="risk_state 本身不明确，不能伪装成普通多头、空头或震荡环境。",
            )

        ordered = self._ordered_scores(scores)
        top_code, top_score = ordered[0]
        second_code, second_score = ordered[1] if len(ordered) > 1 else ("", Decimal("0"))
        priority_code = self._v4_priority_regime_code(
            scores=scores,
            facts=facts,
            top_code=top_code,
            structure_evidence=structure_evidence,
        )
        if priority_code:
            return self._select(
                regime_code=priority_code,
                scores=scores,
                decision_reason="v4 识别到关键结构证据，优先输出更贴近结构状态的市场环境。",
            )

        min_score = self._decimal_param(params, "min_regime_score", Decimal("0.50"))
        min_margin = self._decimal_param(params, "min_classification_margin", Decimal("0.05"))
        transition_floor = self._decimal_param(params, "transition_floor_score", Decimal("0.50"))
        if top_score < min_score:
            transition_code = self._v4_transition_regime_code(
                scores=scores,
                facts=facts,
                structure_evidence=structure_evidence,
                floor=transition_floor,
            )
            if transition_code:
                return self._select(
                    regime_code=transition_code,
                    scores=scores,
                    decision_reason="v4 在趋势背景清晰且结构证据明确时，允许输出具体阶段环境。",
                )
            scores["unclear_environment"] = max(scores["unclear_environment"], top_score)
            return self._select(
                regime_code="unclear_environment",
                scores=scores,
                decision_reason="最高候选分数不足，输出不明确环境。",
            )
        if top_score - second_score < min_margin:
            responsive_code = self._v4_responsive_tie_break_code(
                scores=scores,
                facts=facts,
                top_code=top_code,
                second_code=second_code,
                structure_evidence=structure_evidence,
                floor=transition_floor,
            )
            if responsive_code:
                return self._select(
                    regime_code=responsive_code,
                    scores=scores,
                    decision_reason="v4 根据同方向家族和结构证据，选择更具体的市场环境。",
                )
            scores["unclear_environment"] = max(scores["unclear_environment"], top_score)
            return self._select(
                regime_code="unclear_environment",
                scores=scores,
                decision_reason="主要候选之间差距过小且结构证据不足以收敛，输出不明确环境。",
            )
        return self._select(
            regime_code=top_code,
            scores=scores,
            decision_reason="普通候选分数满足 v4 最低分与最小差距要求。",
        )

    def _score_v4_candidates(
        self,
        *,
        scores: dict[str, Decimal],
        facts: dict[str, DomainFact],
        structure_evidence: Mapping[str, Any],
    ) -> None:
        self._score_v4_bullish_candidates(scores=scores, facts=facts, structure_evidence=structure_evidence)
        self._score_v4_bearish_candidates(scores=scores, facts=facts, structure_evidence=structure_evidence)
        self._score_v4_neutral_candidates(scores=scores, facts=facts)
        self._apply_v4_caps(scores=scores, facts=facts, structure_evidence=structure_evidence)

    def _score_v4_bullish_candidates(
        self,
        *,
        scores: dict[str, Decimal],
        facts: dict[str, DomainFact],
        structure_evidence: Mapping[str, Any],
    ) -> None:
        context = facts["market_context"]
        trend = facts["trend"]
        momentum = facts["momentum"]
        volatility = facts["volatility"]
        structure = facts["structure"]
        risk = facts["risk_state"]
        risk_ok_bonus = Decimal("0.05") if risk.state_code in {"risk_clear", "risk_elevated_classifiable"} else Decimal("0")
        volatility_drag = Decimal("0.08") if volatility.state_code == "volatility_extreme" else Decimal("0")
        support_holds = self._structure_flag_score(structure_evidence, "support_holds")
        resistance_holds = self._structure_flag_score(structure_evidence, "resistance_holds")
        support_breakdown = self._structure_flag_score(structure_evidence, "support_breakdown_candidate")
        resistance_breakout = self._structure_flag_score(structure_evidence, "resistance_breakout_candidate")
        scores["bullish_trend_continuation"] = self._cap(
            self._context_bonus(context, "bullish")
            + self._trend_bonus(trend, "bullish", aligned=True)
            + self._momentum_bonus(momentum, "bullish")
            + self._structure_not_broken_bonus(structure, "bullish")
            + support_holds
            + risk_ok_bonus
            - support_breakdown
            - volatility_drag
        )
        scores["bullish_breakout"] = self._cap(
            self._context_not_opposite_bonus(context, "bullish")
            + self._trend_bonus(trend, "bullish", aligned=False)
            + self._momentum_bonus(momentum, "bullish")
            + self._structure_break_bonus(structure, "bullish")
            + resistance_breakout
            + risk_ok_bonus
            - volatility_drag
        )
        scores["bullish_pullback"] = self._cap(
            self._context_bonus(context, "bullish")
            + self._trend_primary_bonus(trend, "bullish")
            + self._short_cycle_counter_bonus(trend, momentum, "bullish")
            + self._structure_zone_bonus(structure, "support")
            + support_holds
            + risk_ok_bonus
            - support_breakdown
        )
        scores["bullish_high_range"] = self._cap(
            self._context_bonus(context, "bullish")
            + self._context_zone_bonus(context, "high")
            + self._structure_range_bonus(structure, "resistance")
            + self._progress_slow_bonus(trend, momentum)
            + self._range_volatility_bonus(volatility)
            + resistance_holds
            + risk_ok_bonus
        )
        scores["bullish_top_reversal_candidate"] = self._cap(
            self._context_bonus(context, "bullish")
            + self._context_zone_bonus(context, "high")
            + self._structure_zone_bonus(structure, "resistance")
            + self._minor_break_bonus(structure, "bearish")
            + self._momentum_reversal_bonus(momentum, "bearish")
            + resistance_holds
            + support_breakdown
            + self._bullish_structure_pressure(trend=trend, momentum=momentum, volatility=volatility)
            + risk_ok_bonus
        )

    def _score_v4_bearish_candidates(
        self,
        *,
        scores: dict[str, Decimal],
        facts: dict[str, DomainFact],
        structure_evidence: Mapping[str, Any],
    ) -> None:
        context = facts["market_context"]
        trend = facts["trend"]
        momentum = facts["momentum"]
        volatility = facts["volatility"]
        structure = facts["structure"]
        risk = facts["risk_state"]
        risk_ok_bonus = Decimal("0.05") if risk.state_code in {"risk_clear", "risk_elevated_classifiable"} else Decimal("0")
        volatility_drag = Decimal("0.08") if volatility.state_code == "volatility_extreme" else Decimal("0")
        support_holds = self._structure_flag_score(structure_evidence, "support_holds")
        resistance_holds = self._structure_flag_score(structure_evidence, "resistance_holds")
        support_breakdown = self._structure_flag_score(structure_evidence, "support_breakdown_candidate")
        resistance_breakout = self._structure_flag_score(structure_evidence, "resistance_breakout_candidate")

        scores["bearish_trend_continuation"] = self._cap(
            self._context_bonus(context, "bearish")
            + self._trend_bonus(trend, "bearish", aligned=True)
            + self._momentum_bonus(momentum, "bearish")
            + self._structure_not_broken_bonus(structure, "bearish")
            + resistance_holds
            + risk_ok_bonus
            - resistance_breakout
            - volatility_drag
        )
        scores["bearish_breakdown"] = self._cap(
            self._context_not_opposite_bonus(context, "bearish")
            + self._trend_bonus(trend, "bearish", aligned=False)
            + self._momentum_bonus(momentum, "bearish")
            + self._structure_break_bonus(structure, "bearish")
            + support_breakdown
            + risk_ok_bonus
            - volatility_drag
        )
        scores["bearish_rebound"] = self._cap(
            self._context_bonus(context, "bearish")
            + self._trend_primary_bonus(trend, "bearish")
            + self._short_cycle_counter_bonus(trend, momentum, "bearish")
            + self._structure_zone_bonus(structure, "resistance")
            + resistance_holds
            + risk_ok_bonus
            - resistance_breakout
        )
        scores["bearish_low_range"] = self._cap(
            self._context_bonus(context, "bearish")
            + self._context_zone_bonus(context, "low")
            + self._structure_range_bonus(structure, "support")
            + self._progress_slow_bonus(trend, momentum)
            + self._range_volatility_bonus(volatility)
            + support_holds
            + risk_ok_bonus
        )
        scores["bearish_bottom_reversal_candidate"] = self._cap(
            self._context_bonus(context, "bearish")
            + self._context_zone_bonus(context, "low")
            + self._structure_zone_bonus(structure, "support")
            + self._minor_break_bonus(structure, "bullish")
            + self._momentum_reversal_bonus(momentum, "bullish")
            + support_holds
            + resistance_breakout
            + risk_ok_bonus
        )

    def _score_v4_neutral_candidates(
        self,
        *,
        scores: dict[str, Decimal],
        facts: dict[str, DomainFact],
    ) -> None:
        context = facts["market_context"]
        trend = facts["trend"]
        momentum = facts["momentum"]
        volatility = facts["volatility"]
        structure = facts["structure"]
        risk = facts["risk_state"]
        risk_ok_bonus = Decimal("0.05") if risk.state_code in {"risk_clear", "risk_elevated_classifiable"} else Decimal("0")

        scores["neutral_range"] = self._cap(
            (Decimal("0.30") if context.direction == "neutral" else Decimal("0"))
            + (Decimal("0.20") if trend.direction == "neutral" else Decimal("0"))
            + self._structure_range_bonus(structure, "middle")
            + self._range_volatility_bonus(volatility)
            + risk_ok_bonus
        )
        scores["unclear_environment"] = max(
            Decimal("0.25"),
            self._conflict_score(context=context, trend=trend, momentum=momentum, structure=structure),
        )

    def _apply_v4_caps(
        self,
        *,
        scores: dict[str, Decimal],
        facts: dict[str, DomainFact],
        structure_evidence: Mapping[str, Any],
    ) -> None:
        context = facts["market_context"]
        if context.direction != "bullish":
            scores["bullish_high_range"] = min(scores["bullish_high_range"], Decimal("0.45"))
        if context.direction != "bearish":
            scores["bearish_low_range"] = min(scores["bearish_low_range"], Decimal("0.45"))
        if context.direction != "neutral":
            scores["neutral_range"] = min(scores["neutral_range"], Decimal("0.50"))

        if not self._has_structure_signal(structure_evidence, "resistance_breakout_candidate") and not self._structure_break(
            facts["structure"], "bullish"
        ):
            scores["bullish_breakout"] = min(scores["bullish_breakout"], Decimal("0.48"))
        if not self._has_structure_signal(structure_evidence, "support_breakdown_candidate") and not self._structure_break(
            facts["structure"], "bearish"
        ):
            scores["bearish_breakdown"] = min(scores["bearish_breakdown"], Decimal("0.48"))
        if self._has_structure_signal(structure_evidence, "support_breakdown_candidate"):
            scores["bullish_trend_continuation"] = min(scores["bullish_trend_continuation"], Decimal("0.42"))
            scores["bullish_pullback"] = min(scores["bullish_pullback"], Decimal("0.50"))
            scores["unclear_environment"] = max(scores["unclear_environment"], Decimal("0.42"))
        if self._has_structure_signal(structure_evidence, "resistance_breakout_candidate"):
            scores["bearish_trend_continuation"] = min(scores["bearish_trend_continuation"], Decimal("0.42"))
            scores["bearish_rebound"] = min(scores["bearish_rebound"], Decimal("0.50"))
            scores["unclear_environment"] = max(scores["unclear_environment"], Decimal("0.42"))

    def _v4_priority_regime_code(
        self,
        *,
        scores: Mapping[str, Decimal],
        facts: dict[str, DomainFact],
        top_code: str,
        structure_evidence: Mapping[str, Any],
    ) -> str:
        if (
            top_code == "bullish_breakout"
            and scores["bullish_breakout"] >= Decimal("0.62")
            and self._has_structure_signal(structure_evidence, "resistance_breakout_candidate")
        ):
            return "bullish_breakout"
        if (
            top_code == "bearish_breakdown"
            and scores["bearish_breakdown"] >= Decimal("0.62")
            and self._has_structure_signal(structure_evidence, "support_breakdown_candidate")
        ):
            return "bearish_breakdown"
        if facts["market_context"].direction == "bullish" and self._has_structure_signal(
            structure_evidence, "support_breakdown_candidate"
        ):
            return self._best_above_floor(scores, Decimal("0.50"), ("bullish_top_reversal_candidate", "unclear_environment"))
        if facts["market_context"].direction == "bearish" and self._has_structure_signal(
            structure_evidence, "resistance_breakout_candidate"
        ):
            return self._best_above_floor(
                scores,
                Decimal("0.50"),
                ("bearish_bottom_reversal_candidate", "unclear_environment"),
            )
        return ""

    def _v4_responsive_tie_break_code(
        self,
        *,
        scores: Mapping[str, Decimal],
        facts: dict[str, DomainFact],
        top_code: str,
        second_code: str,
        structure_evidence: Mapping[str, Any],
        floor: Decimal,
    ) -> str:
        transition_code = self._v4_transition_regime_code(
            scores=scores,
            facts=facts,
            structure_evidence=structure_evidence,
            floor=floor,
        )
        if transition_code:
            return transition_code
        top_family = self._regime_family(top_code)
        second_family = self._regime_family(second_code)
        if top_family in {"bullish", "bearish"} and top_family == second_family and scores[top_code] >= floor:
            return top_code
        return ""

    def _v4_transition_regime_code(
        self,
        *,
        scores: Mapping[str, Decimal],
        facts: dict[str, DomainFact],
        structure_evidence: Mapping[str, Any],
        floor: Decimal,
    ) -> str:
        context = facts["market_context"]
        trend = facts["trend"]
        momentum = facts["momentum"]
        if context.direction == "bullish":
            if self._has_structure_signal(structure_evidence, "support_breakdown_candidate"):
                return self._best_above_floor(scores, floor, ("bullish_top_reversal_candidate", "unclear_environment"))
            if self._short_cycle_repairing_against_context(trend=trend, momentum=momentum, context_direction="bullish"):
                return self._best_above_floor(scores, floor, ("bullish_pullback", "bullish_high_range"))
        if context.direction == "bearish":
            if self._has_structure_signal(structure_evidence, "resistance_breakout_candidate"):
                return self._best_above_floor(scores, floor, ("bearish_bottom_reversal_candidate", "unclear_environment"))
            if self._short_cycle_repairing_against_context(trend=trend, momentum=momentum, context_direction="bearish"):
                return self._best_above_floor(scores, floor, ("bearish_rebound", "bearish_low_range"))
        return ""

    @staticmethod
    def _extract_structure_evidence(structure: DomainFact) -> Mapping[str, Any] | None:
        for item in structure.evidence_items:
            summary = item.get("summary")
            if isinstance(summary, Mapping) and isinstance(summary.get("structure_evidence"), Mapping):
                return summary["structure_evidence"]
            if isinstance(item.get("structure_evidence"), Mapping):
                return item["structure_evidence"]
        return None

    @staticmethod
    def _level_evidence(structure_evidence: Mapping[str, Any], level: str) -> Mapping[str, Any]:
        value = structure_evidence.get(level)
        return value if isinstance(value, Mapping) else {}

    def _has_structure_signal(self, structure_evidence: Mapping[str, Any], signal_key: str) -> bool:
        return bool(
            self._level_evidence(structure_evidence, "major").get(signal_key)
            or self._level_evidence(structure_evidence, "minor").get(signal_key)
        )

    def _structure_flag_score(self, structure_evidence: Mapping[str, Any], signal_key: str) -> Decimal:
        score = Decimal("0")
        if self._level_evidence(structure_evidence, "major").get(signal_key):
            score += Decimal("0.22")
        if self._level_evidence(structure_evidence, "minor").get(signal_key):
            score += Decimal("0.08")
        return min(Decimal("0.30"), score)

    @staticmethod
    def _bullish_structure_pressure(
        *,
        trend: DomainFact,
        momentum: DomainFact,
        volatility: DomainFact,
    ) -> Decimal:
        pressure = Decimal("0")
        if trend.direction == "bearish" or "1d_bearish" in trend.state_code:
            pressure += Decimal("0.18")
        elif "4h_bearish" in trend.state_code or "minor_bearish" in trend.state_code:
            pressure += Decimal("0.10")
        if momentum.direction == "bearish":
            pressure += Decimal("0.12")
        if volatility.state_code == "volatility_high":
            pressure += Decimal("0.06")
        elif volatility.state_code == "volatility_extreme":
            pressure += Decimal("0.10")
        return min(Decimal("0.35"), pressure)

    @staticmethod
    def _best_above_floor(scores: Mapping[str, Decimal], floor: Decimal, codes: tuple[str, ...]) -> str:
        eligible = [(code, scores[code]) for code in codes if scores[code] >= floor]
        if not eligible:
            return ""
        return max(eligible, key=lambda item: item[1])[0]

    @staticmethod
    def _regime_family(regime_code: str) -> str:
        if regime_code.startswith("bullish_"):
            return "bullish"
        if regime_code.startswith("bearish_"):
            return "bearish"
        if regime_code == "neutral_range":
            return "neutral"
        if regime_code == "high_risk_environment":
            return "risk"
        return "unclear"

    @staticmethod
    def _short_cycle_repairing_against_context(
        *,
        trend: DomainFact,
        momentum: DomainFact,
        context_direction: str,
    ) -> bool:
        opposite = "bullish" if context_direction == "bearish" else "bearish"
        trend_token_matches = (
            "rebound" in trend.state_code
            if context_direction == "bearish"
            else "pullback" in trend.state_code
        )
        return (
            opposite in trend.state_code
            or opposite in momentum.state_code
            or momentum.direction == opposite
            or trend_token_matches
        )

    @staticmethod
    def _evidence_text_v4(
        *,
        facts: dict[str, DomainFact],
        classification: ClassificationResult,
        structure_evidence: Mapping[str, Any],
    ) -> str:
        competitors = "、".join(f"{code}={score}" for code, score in classification.competitors if code != classification.regime_code)
        facts_zh = structure_evidence.get("facts_zh")
        structure_facts = "、".join(str(item) for item in facts_zh) if isinstance(facts_zh, (list, tuple)) else "无"
        return (
            f"MarketRegime v4 已将本轮六个领域事实归类为 {classification.regime_code}。"
            f"市场大背景={facts['market_context'].direction}/{facts['market_context'].state_code}；"
            f"趋势={facts['trend'].direction}/{facts['trend'].state_code}；"
            f"动能={facts['momentum'].direction}/{facts['momentum'].state_code}；"
            f"波动={facts['volatility'].state_code}；"
            f"结构={facts['structure'].direction}/{facts['structure'].state_code}；"
            f"结构证据={structure_evidence.get('primary_state_zh') or '未命名'}，{structure_facts}；"
            f"风险={facts['risk_state'].state_code}。"
            f"选择原因：{classification.decision_reason}"
            f"主要竞争候选：{competitors or '无'}。该结论只描述市场环境，不生成策略、目标仓位或订单动作。"
        )


class ContextStructureRegimeV5Calculator(ContextStructureRegimeCalculator):
    """MarketRegime 模块：context_structure_regime/v5 市场环境分类 calculator。

    负责：消费六个领域事实和 Structure 结构证据，输出结构保持/破坏/修复确认版市场环境分类。
    不负责：计算特征、读取原子信号、选择策略、生成交易信号、生成目标仓位或订单动作。
    读写数据库：不涉及。
    访问 Redis：不涉及。
    访问外部服务：不涉及。
    发送 Hermes：不涉及。
    调用大模型：不涉及。
    涉及交易执行：不涉及。
    允许真实交易：否。
    """

    metadata = CalculatorMetadata(
        algorithm_name="context_structure_regime",
        algorithm_version="v5",
        calculator_type=CalculatorType.MARKET_REGIME,
        input_schema_version="1.0",
        output_schema_version="1.0",
        deterministic=True,
        supports_dry_run=True,
        algorithm_requirement_document_path="docs/requirements/market_regime/context_structure_regime_v5.md",
        implementation_document_path="docs/implementation/market_regime/context_structure_regime__v5.md",
    )
    evidence_type = "context_structure_regime_v5"

    def calculate(self, calculation_input: CalculatorInput) -> CalculatorOutput:
        values = dict(calculation_input.values)
        params = dict(calculation_input.frozen_params)
        allowed_regime_codes = self._string_tuple(values.get("allowed_regime_codes"))
        if set(allowed_regime_codes) != set(REGIME_CODES):
            return self._failed(
                "context_structure_regime_allowed_codes_invalid",
                "context_structure_regime/v5 必须使用文档登记的完整 regime_code 集合。",
            )
        domain_values = values.get("domain_values")
        if not isinstance(domain_values, (list, tuple)):
            return self._failed("context_structure_regime_domain_values_missing", "缺少领域事实输入。")
        facts_result = self._facts_by_domain(domain_values)
        if "error_code" in facts_result:
            return self._failed(str(facts_result["error_code"]), str(facts_result["error_message"]))
        facts: dict[str, DomainFact] = facts_result["facts"]
        structure_evidence = self._extract_structure_evidence(facts["structure"])
        if structure_evidence is None:
            return self._failed(
                "market_regime_structure_evidence_missing",
                "context_structure_regime/v5 必须消费 Structure 输出的 structure_evidence；当前输入缺少该证据。",
            )

        structure_phase = self._structure_phase(facts=facts, structure_evidence=structure_evidence)
        classification = self._classify_v5(
            facts=facts,
            params=params,
            structure_evidence=structure_evidence,
            structure_phase=structure_phase,
        )
        used_ids = [facts[code].value_id for code in REQUIRED_DOMAIN_CODES]
        return CalculatorOutput.succeeded(
            output_schema_version=self.metadata.output_schema_version,
            values={
                "regime_code": classification.regime_code,
                "regime_scores": classification.scores,
                "regime_confidence": classification.confidence,
                "classification_margin": classification.margin,
                "used_domain_signal_value_ids": used_ids,
                "evidence_text_zh": self._evidence_text_v5(
                    facts=facts,
                    classification=classification,
                    structure_evidence=structure_evidence,
                    structure_phase=structure_phase,
                ),
            },
            evidence_items=(
                {
                    "type": self.evidence_type,
                    "selected_regime_code": classification.regime_code,
                    "decision_reason": classification.decision_reason,
                    "competitors": [
                        {"regime_code": code, "score": str(score)} for code, score in classification.competitors
                    ],
                    "structure_phase": structure_phase,
                    "structure_evidence": structure_evidence,
                    "domain_summary": {
                        code: {
                            "direction": facts[code].direction,
                            "state_code": facts[code].state_code,
                            "strength": str(facts[code].strength),
                        }
                        for code in REQUIRED_DOMAIN_CODES
                    },
                },
            ),
            calculation_summary={
                "selected_regime_code": classification.regime_code,
                "decision_reason": classification.decision_reason,
                "used_domain_count": len(used_ids),
                "structure_primary_state_zh": str(structure_evidence.get("primary_state_zh") or ""),
                "structure_phase": structure_phase,
            },
        )

    def _score_v5_candidates(
        self,
        *,
        scores: dict[str, Decimal],
        facts: dict[str, DomainFact],
        structure_evidence: Mapping[str, Any],
    ) -> None:
        context = facts["market_context"]
        trend = facts["trend"]
        momentum = facts["momentum"]
        volatility = facts["volatility"]
        structure = facts["structure"]
        risk = facts["risk_state"]
        risk_ok_bonus = Decimal("0.05") if risk.state_code in {"risk_clear", "risk_elevated_classifiable"} else Decimal("0")
        volatility_drag = Decimal("0.08") if volatility.state_code == "volatility_extreme" else Decimal("0")
        support_holds = self._structure_flag_score_v5(structure_evidence, "support_holds")
        resistance_holds = self._structure_flag_score_v5(structure_evidence, "resistance_holds")
        support_breakdown = self._structure_flag_score_v5(structure_evidence, "support_breakdown_candidate")
        resistance_breakout = self._structure_flag_score_v5(structure_evidence, "resistance_breakout_candidate")

        scores["bullish_trend_continuation"] = self._cap(
            self._context_bonus(context, "bullish")
            + self._trend_bonus(trend, "bullish", aligned=True)
            + self._momentum_bonus(momentum, "bullish")
            + self._structure_not_broken_bonus(structure, "bullish")
            + support_holds
            + risk_ok_bonus
            - support_breakdown
            - volatility_drag
        )
        scores["bullish_breakout"] = self._cap(
            self._context_not_opposite_bonus(context, "bullish")
            + self._trend_bonus(trend, "bullish", aligned=True)
            + self._momentum_bonus(momentum, "bullish")
            + self._structure_break_bonus(structure, "bullish")
            + resistance_breakout
            + risk_ok_bonus
            - volatility_drag
        )
        scores["bullish_pullback"] = self._cap(
            self._context_bonus(context, "bullish")
            + self._trend_primary_bonus(trend, "bullish")
            + self._short_cycle_counter_bonus(trend, momentum, "bullish")
            + self._structure_zone_bonus(structure, "support")
            + support_holds
            + risk_ok_bonus
            - support_breakdown
        )
        scores["bullish_high_range"] = self._cap(
            self._context_bonus(context, "bullish")
            + self._context_zone_bonus(context, "high")
            + self._structure_range_bonus(structure, "resistance")
            + self._progress_slow_bonus(trend, momentum)
            + self._range_volatility_bonus(volatility)
            + resistance_holds
            + support_breakdown
            + risk_ok_bonus
        )
        scores["bullish_top_reversal_candidate"] = self._cap(
            self._context_bonus(context, "bullish")
            + self._context_zone_bonus(context, "high")
            + self._minor_break_bonus(structure, "bearish")
            + self._momentum_reversal_bonus(momentum, "bearish")
            + self._bullish_structure_pressure_v5(trend=trend, momentum=momentum, volatility=volatility)
            + resistance_holds
            + support_breakdown
            + risk_ok_bonus
        )

        scores["bearish_trend_continuation"] = self._cap(
            self._context_bonus(context, "bearish")
            + self._trend_bonus(trend, "bearish", aligned=True)
            + self._momentum_bonus(momentum, "bearish")
            + self._structure_not_broken_bonus(structure, "bearish")
            + resistance_holds
            + risk_ok_bonus
            - resistance_breakout
            - volatility_drag
        )
        scores["bearish_breakdown"] = self._cap(
            self._context_not_opposite_bonus(context, "bearish")
            + self._trend_bonus(trend, "bearish", aligned=True)
            + self._momentum_bonus(momentum, "bearish")
            + self._structure_break_bonus(structure, "bearish")
            + support_breakdown
            + risk_ok_bonus
            - volatility_drag
        )
        scores["bearish_rebound"] = self._cap(
            self._context_bonus(context, "bearish")
            + self._trend_primary_bonus(trend, "bearish")
            + self._short_cycle_counter_bonus(trend, momentum, "bearish")
            + self._structure_zone_bonus(structure, "resistance")
            + resistance_holds
            + risk_ok_bonus
            - resistance_breakout
        )
        scores["bearish_low_range"] = self._cap(
            self._context_bonus(context, "bearish")
            + self._context_zone_bonus(context, "low")
            + self._structure_range_bonus(structure, "support")
            + self._progress_slow_bonus(trend, momentum)
            + self._range_volatility_bonus(volatility)
            + support_holds
            + resistance_breakout
            + risk_ok_bonus
        )
        scores["bearish_bottom_reversal_candidate"] = self._cap(
            self._context_bonus(context, "bearish")
            + self._context_zone_bonus(context, "deep")
            + self._minor_break_bonus(structure, "bullish")
            + self._momentum_reversal_bonus(momentum, "bullish")
            + self._bearish_structure_repair_pressure_v5(trend=trend, momentum=momentum, volatility=volatility)
            + support_holds
            + resistance_breakout
            + risk_ok_bonus
        )

        scores["neutral_range"] = self._cap(
            (Decimal("0.30") if context.direction == "neutral" else Decimal("0"))
            + (Decimal("0.20") if trend.direction == "neutral" else Decimal("0"))
            + self._structure_range_bonus(structure, "middle")
            + self._range_volatility_bonus(volatility)
            + risk_ok_bonus
        )
        if context.direction != "neutral":
            scores["neutral_range"] = min(scores["neutral_range"], Decimal("0.50"))

        scores["unclear_environment"] = max(
            Decimal("0.25"),
            self._conflict_score(context=context, trend=trend, momentum=momentum, structure=structure),
        )

    @staticmethod
    def _extract_structure_evidence(structure: DomainFact) -> Mapping[str, Any] | None:
        for item in structure.evidence_items:
            if not isinstance(item, Mapping):
                continue
            summary = item.get("summary")
            if isinstance(summary, Mapping) and isinstance(summary.get("structure_evidence"), Mapping):
                return summary["structure_evidence"]
            if isinstance(item.get("structure_evidence"), Mapping):
                return item["structure_evidence"]
        return None

    @staticmethod
    def _level_evidence(structure_evidence: Mapping[str, Any], level: str) -> Mapping[str, Any]:
        value = structure_evidence.get(level)
        return value if isinstance(value, Mapping) else {}

    def _structure_flag_score_v5(self, structure_evidence: Mapping[str, Any], flag: str) -> Decimal:
        score = Decimal("0")
        if self._level_evidence(structure_evidence, "major").get(flag):
            score += Decimal("0.14")
        if self._level_evidence(structure_evidence, "minor").get(flag):
            score += Decimal("0.06")
        return min(Decimal("0.20"), score)

    @staticmethod
    def _bullish_structure_pressure_v5(
        *,
        trend: DomainFact,
        momentum: DomainFact,
        volatility: DomainFact,
    ) -> Decimal:
        pressure = Decimal("0")
        if trend.direction == "bearish" or "1d_bearish" in trend.state_code:
            pressure += Decimal("0.18")
        elif trend.direction == "neutral" or "bearish" in trend.state_code:
            pressure += Decimal("0.12")
        if momentum.direction == "bearish":
            pressure += Decimal("0.16")
        elif "exhausting" in momentum.state_code:
            pressure += Decimal("0.10")
        if volatility.state_code in {"volatility_high", "volatility_extreme"}:
            pressure += Decimal("0.08")
        return min(Decimal("0.35"), pressure)

    @staticmethod
    def _bearish_structure_repair_pressure_v5(
        *,
        trend: DomainFact,
        momentum: DomainFact,
        volatility: DomainFact,
    ) -> Decimal:
        pressure = Decimal("0")
        if trend.direction == "bullish" or "1d_bullish" in trend.state_code:
            pressure += Decimal("0.18")
        elif trend.direction == "neutral" or "bullish" in trend.state_code:
            pressure += Decimal("0.12")
        if momentum.direction == "bullish":
            pressure += Decimal("0.16")
        elif "exhausting" in momentum.state_code:
            pressure += Decimal("0.10")
        if volatility.state_code in {"volatility_high", "volatility_extreme"}:
            pressure += Decimal("0.08")
        return min(Decimal("0.35"), pressure)

    @staticmethod
    def _best_above_floor(scores: Mapping[str, Decimal], floor: Decimal, codes: tuple[str, ...]) -> str:
        available = [(code, scores[code]) for code in codes if scores[code] >= floor]
        if not available:
            return ""
        return max(available, key=lambda item: item[1])[0]

    @staticmethod
    def _regime_family(regime_code: str) -> str:
        if regime_code.startswith("bullish_"):
            return "bullish"
        if regime_code.startswith("bearish_"):
            return "bearish"
        if regime_code in {"neutral_range"}:
            return "neutral"
        return "other"

    def _classify_v5(
        self,
        *,
        facts: dict[str, DomainFact],
        params: Mapping[str, Any],
        structure_evidence: Mapping[str, Any],
        structure_phase: Mapping[str, bool],
    ) -> ClassificationResult:
        scores = {code: Decimal("0") for code in REGIME_CODES}
        self._score_v5_candidates(scores=scores, facts=facts, structure_evidence=structure_evidence)
        self._apply_v5_structure_phase(scores=scores, facts=facts, structure_phase=structure_phase)

        risk = facts["risk_state"]
        if risk.state_code == "risk_high_signal_unreliable":
            scores["high_risk_environment"] = Decimal("1.00")
            return self._select(
                regime_code="high_risk_environment",
                scores=scores,
                decision_reason="risk_state 明确提示普通环境分类可靠性显著下降，优先归为高风险环境。",
            )
        if risk.state_code == "risk_unclear":
            scores["unclear_environment"] = max(scores["unclear_environment"], Decimal("0.80"))
            return self._select(
                regime_code="unclear_environment",
                scores=scores,
                decision_reason="risk_state 本身不明确，不能伪装成普通多头、空头或震荡环境。",
            )

        priority_code = self._v5_priority_regime_code(scores=scores, facts=facts, structure_phase=structure_phase)
        if priority_code:
            return self._select(
                regime_code=priority_code,
                scores=scores,
                decision_reason="v5 根据结构保持/破坏/修复阶段，优先输出更明确的市场环境。",
            )

        ordered = self._ordered_scores(scores)
        top_code, top_score = ordered[0]
        second_code, second_score = ordered[1] if len(ordered) > 1 else ("", Decimal("0"))
        min_score = self._decimal_param(params, "min_regime_score", Decimal("0.50"))
        min_margin = self._decimal_param(params, "min_classification_margin", Decimal("0.05"))
        transition_floor = self._decimal_param(params, "transition_floor_score", Decimal("0.50"))
        if top_score < min_score:
            transition_code = self._v5_transition_regime_code(
                scores=scores,
                facts=facts,
                structure_phase=structure_phase,
                floor=transition_floor,
            )
            if transition_code:
                return self._select(
                    regime_code=transition_code,
                    scores=scores,
                    decision_reason="v5 在结构阶段明确时，允许输出具体阶段环境。",
                )
            scores["unclear_environment"] = max(scores["unclear_environment"], top_score)
            return self._select(
                regime_code="unclear_environment",
                scores=scores,
                decision_reason="最高候选分数不足，输出不明确环境。",
            )
        if top_score - second_score < min_margin:
            responsive_code = self._v5_transition_regime_code(
                scores=scores,
                facts=facts,
                structure_phase=structure_phase,
                floor=transition_floor,
            )
            if responsive_code:
                return self._select(
                    regime_code=responsive_code,
                    scores=scores,
                    decision_reason="v5 根据结构阶段在相近候选中收敛到更具体环境。",
                )
            if self._regime_family(top_code) == self._regime_family(second_code) and scores[top_code] >= transition_floor:
                return self._select(
                    regime_code=top_code,
                    scores=scores,
                    decision_reason="v5 保留同方向家族内最高分候选。",
                )
            scores["unclear_environment"] = max(scores["unclear_environment"], top_score)
            return self._select(
                regime_code="unclear_environment",
                scores=scores,
                decision_reason="主要候选差距过小且结构阶段不能收敛，输出不明确环境。",
            )
        return self._select(
            regime_code=top_code,
            scores=scores,
            decision_reason="普通候选分数满足 v5 最低分与最小差距要求。",
        )

    def _apply_v5_structure_phase(
        self,
        *,
        scores: dict[str, Decimal],
        facts: dict[str, DomainFact],
        structure_phase: Mapping[str, bool],
    ) -> None:
        context = facts["market_context"]
        if context.direction == "bullish":
            if structure_phase["bullish_structure_maintained"]:
                scores["bullish_pullback"] = self._cap(scores["bullish_pullback"] + Decimal("0.08"))
                scores["bearish_breakdown"] = min(scores["bearish_breakdown"], Decimal("0.45"))
            if structure_phase["bullish_structure_under_pressure"]:
                scores["bullish_high_range"] = self._cap(scores["bullish_high_range"] + Decimal("0.06"))
                scores["bullish_top_reversal_candidate"] = self._cap(
                    scores["bullish_top_reversal_candidate"] + Decimal("0.08")
                )
            if structure_phase["bullish_structure_breakdown_candidate"]:
                scores["bullish_trend_continuation"] = min(scores["bullish_trend_continuation"], Decimal("0.35"))
                scores["bullish_pullback"] = min(scores["bullish_pullback"], Decimal("0.42"))
                scores["bullish_top_reversal_candidate"] = self._cap(
                    scores["bullish_top_reversal_candidate"] + Decimal("0.12")
                )
            if structure_phase["bullish_structure_broken"]:
                scores["bullish_trend_continuation"] = min(scores["bullish_trend_continuation"], Decimal("0.25"))
                scores["bullish_pullback"] = min(scores["bullish_pullback"], Decimal("0.30"))
                scores["bearish_breakdown"] = self._cap(scores["bearish_breakdown"] + Decimal("0.16"))
                scores["bearish_trend_continuation"] = self._cap(scores["bearish_trend_continuation"] + Decimal("0.10"))
        if context.direction == "bearish":
            if structure_phase["bearish_structure_maintained"]:
                scores["bearish_rebound"] = self._cap(scores["bearish_rebound"] + Decimal("0.08"))
                scores["bullish_breakout"] = min(scores["bullish_breakout"], Decimal("0.45"))
            if structure_phase["bearish_structure_under_pressure"]:
                scores["bearish_low_range"] = self._cap(scores["bearish_low_range"] + Decimal("0.06"))
                scores["bearish_bottom_reversal_candidate"] = self._cap(
                    scores["bearish_bottom_reversal_candidate"] + Decimal("0.08")
                )
            if structure_phase["bearish_structure_repair_candidate"]:
                scores["bearish_trend_continuation"] = min(scores["bearish_trend_continuation"], Decimal("0.35"))
                scores["bearish_rebound"] = min(scores["bearish_rebound"], Decimal("0.42"))
                scores["bearish_bottom_reversal_candidate"] = self._cap(
                    scores["bearish_bottom_reversal_candidate"] + Decimal("0.12")
                )
            if structure_phase["bearish_structure_repaired"]:
                scores["bearish_trend_continuation"] = min(scores["bearish_trend_continuation"], Decimal("0.25"))
                scores["bearish_rebound"] = min(scores["bearish_rebound"], Decimal("0.30"))
                scores["bullish_breakout"] = self._cap(scores["bullish_breakout"] + Decimal("0.16"))
                scores["bullish_trend_continuation"] = self._cap(scores["bullish_trend_continuation"] + Decimal("0.10"))

    def _v5_priority_regime_code(
        self,
        *,
        scores: Mapping[str, Decimal],
        facts: dict[str, DomainFact],
        structure_phase: Mapping[str, bool],
    ) -> str:
        context = facts["market_context"]
        if context.direction == "bullish":
            if structure_phase["bullish_structure_broken"] and scores["bearish_breakdown"] >= Decimal("0.58"):
                return "bearish_breakdown"
            if structure_phase["bullish_structure_breakdown_candidate"]:
                return self._best_above_floor(
                    scores,
                    Decimal("0.50"),
                    ("bullish_top_reversal_candidate", "bullish_high_range", "unclear_environment"),
                )
            if structure_phase["bullish_structure_maintained"]:
                return self._best_above_floor(scores, Decimal("0.52"), ("bullish_pullback", "bullish_trend_continuation"))
        if context.direction == "bearish":
            if structure_phase["bearish_structure_repaired"] and scores["bullish_breakout"] >= Decimal("0.58"):
                return "bullish_breakout"
            if structure_phase["bearish_structure_repair_candidate"]:
                return self._best_above_floor(
                    scores,
                    Decimal("0.50"),
                    ("bearish_bottom_reversal_candidate", "bearish_low_range", "unclear_environment"),
                )
            if structure_phase["bearish_structure_maintained"]:
                return self._best_above_floor(scores, Decimal("0.52"), ("bearish_rebound", "bearish_trend_continuation"))
        return ""

    def _v5_transition_regime_code(
        self,
        *,
        scores: Mapping[str, Decimal],
        facts: dict[str, DomainFact],
        structure_phase: Mapping[str, bool],
        floor: Decimal,
    ) -> str:
        context = facts["market_context"]
        if context.direction == "bullish":
            if structure_phase["bullish_structure_broken"]:
                return self._best_above_floor(scores, floor, ("bearish_breakdown", "bullish_top_reversal_candidate"))
            if structure_phase["bullish_structure_breakdown_candidate"]:
                return self._best_above_floor(scores, floor, ("bullish_top_reversal_candidate", "bullish_high_range"))
            if structure_phase["bullish_structure_maintained"]:
                return self._best_above_floor(scores, floor, ("bullish_pullback", "bullish_trend_continuation"))
        if context.direction == "bearish":
            if structure_phase["bearish_structure_repaired"]:
                return self._best_above_floor(scores, floor, ("bullish_breakout", "bearish_bottom_reversal_candidate"))
            if structure_phase["bearish_structure_repair_candidate"]:
                return self._best_above_floor(scores, floor, ("bearish_bottom_reversal_candidate", "bearish_low_range"))
            if structure_phase["bearish_structure_maintained"]:
                return self._best_above_floor(scores, floor, ("bearish_rebound", "bearish_trend_continuation"))
        return ""

    def _structure_phase(
        self,
        *,
        facts: dict[str, DomainFact],
        structure_evidence: Mapping[str, Any],
    ) -> dict[str, bool]:
        trend = facts["trend"]
        momentum = facts["momentum"]
        structure = facts["structure"]
        major_support_holds = bool(self._level_evidence(structure_evidence, "major").get("support_holds"))
        major_resistance_holds = bool(self._level_evidence(structure_evidence, "major").get("resistance_holds"))
        major_support_breakdown = bool(
            self._level_evidence(structure_evidence, "major").get("support_breakdown_candidate")
        )
        major_resistance_breakout = bool(
            self._level_evidence(structure_evidence, "major").get("resistance_breakout_candidate")
        )
        minor_support_breakdown = bool(
            self._level_evidence(structure_evidence, "minor").get("support_breakdown_candidate")
        )
        minor_resistance_breakout = bool(
            self._level_evidence(structure_evidence, "minor").get("resistance_breakout_candidate")
        )
        bearish_confirmation = (
            trend.direction == "bearish"
            and momentum.direction == "bearish"
            or "breakdown_down" in structure.state_code
            or "1d_bearish" in trend.state_code
        )
        bullish_confirmation = (
            trend.direction == "bullish"
            and momentum.direction == "bullish"
            or "breakout_up" in structure.state_code
            or "1d_bullish" in trend.state_code
        )
        bullish_candidate = major_support_breakdown or minor_support_breakdown
        bearish_candidate = major_resistance_breakout or minor_resistance_breakout
        return {
            "bullish_structure_maintained": major_support_holds and not bullish_candidate,
            "bullish_structure_under_pressure": major_resistance_holds or bullish_candidate,
            "bullish_structure_breakdown_candidate": bullish_candidate and not (major_support_breakdown and bearish_confirmation),
            "bullish_structure_broken": major_support_breakdown and bearish_confirmation,
            "bearish_structure_maintained": major_resistance_holds and not bearish_candidate,
            "bearish_structure_under_pressure": major_support_holds or bearish_candidate,
            "bearish_structure_repair_candidate": bearish_candidate and not (major_resistance_breakout and bullish_confirmation),
            "bearish_structure_repaired": major_resistance_breakout and bullish_confirmation,
        }

    @staticmethod
    def _evidence_text_v5(
        *,
        facts: dict[str, DomainFact],
        classification: ClassificationResult,
        structure_evidence: Mapping[str, Any],
        structure_phase: Mapping[str, bool],
    ) -> str:
        competitors = "、".join(f"{code}={score}" for code, score in classification.competitors if code != classification.regime_code)
        facts_zh = structure_evidence.get("facts_zh")
        structure_facts = "、".join(str(item) for item in facts_zh) if isinstance(facts_zh, (list, tuple)) else "无"
        active_phases = "、".join(name for name, enabled in structure_phase.items() if enabled) or "无明确结构阶段"
        return (
            f"MarketRegime v5 已将本轮六个领域事实归类为 {classification.regime_code}。"
            f"市场大背景={facts['market_context'].direction}/{facts['market_context'].state_code}；"
            f"趋势={facts['trend'].direction}/{facts['trend'].state_code}；"
            f"动能={facts['momentum'].direction}/{facts['momentum'].state_code}；"
            f"波动={facts['volatility'].state_code}；"
            f"结构={facts['structure'].direction}/{facts['structure'].state_code}；"
            f"结构阶段={active_phases}；"
            f"结构证据={structure_evidence.get('primary_state_zh') or '未命名'}，{structure_facts}；"
            f"风险={facts['risk_state'].state_code}。"
            f"选择原因：{classification.decision_reason}"
            f"主要竞争候选：{competitors or '无'}。该结论只描述市场环境，不生成策略、目标仓位或订单动作。"
        )


class ContextStructureRegimeV6Calculator(ContextStructureRegimeCalculator):
    """MarketRegime 模块：context_structure_regime/v6 市场环境分类 calculator。

    负责：消费六个领域事实和 Structure v3 结构位置证据，输出市场环境分类。
    不负责：计算特征、读取原子信号、选择策略、生成交易信号、生成目标仓位或订单动作。
    读写数据库：不涉及。
    访问 Redis：不涉及。
    访问外部服务：不涉及。
    发送 Hermes：不涉及。
    调用大模型：不涉及。
    涉及交易执行：不涉及。
    允许真实交易：否。
    """

    metadata = CalculatorMetadata(
        algorithm_name="context_structure_regime",
        algorithm_version="v6",
        calculator_type=CalculatorType.MARKET_REGIME,
        input_schema_version="1.0",
        output_schema_version="1.0",
        deterministic=True,
        supports_dry_run=True,
        algorithm_requirement_document_path="docs/requirements/market_regime/context_structure_regime_v6.md",
        implementation_document_path="docs/implementation/market_regime/context_structure_regime__v6.md",
    )
    evidence_type = "context_structure_regime_v6"

    def calculate(self, calculation_input: CalculatorInput) -> CalculatorOutput:
        values = dict(calculation_input.values)
        params = dict(calculation_input.frozen_params)
        allowed_regime_codes = self._string_tuple(values.get("allowed_regime_codes"))
        if set(allowed_regime_codes) != set(REGIME_CODES):
            return self._failed(
                "context_structure_regime_allowed_codes_invalid",
                "context_structure_regime/v6 必须使用文档登记的完整 regime_code 集合。",
            )
        domain_values = values.get("domain_values")
        if not isinstance(domain_values, (list, tuple)):
            return self._failed("context_structure_regime_domain_values_missing", "缺少领域事实输入。")
        facts_result = self._facts_by_domain(domain_values)
        if "error_code" in facts_result:
            return self._failed(str(facts_result["error_code"]), str(facts_result["error_message"]))
        facts: dict[str, DomainFact] = facts_result["facts"]
        structure_evidence = self._extract_structure_evidence_v6(facts["structure"])
        if structure_evidence is None:
            return self._failed(
                "market_regime_structure_evidence_missing",
                "context_structure_regime/v6 必须消费 Structure 输出的 structure_evidence；当前输入缺少该证据。",
            )

        structure_context = self._structure_context_v6(structure_evidence)
        classification = self._classify_v6(
            facts=facts,
            params=params,
            structure_context=structure_context,
        )
        used_ids = [facts[code].value_id for code in REQUIRED_DOMAIN_CODES]
        return CalculatorOutput.succeeded(
            output_schema_version=self.metadata.output_schema_version,
            values={
                "regime_code": classification.regime_code,
                "regime_scores": classification.scores,
                "regime_confidence": classification.confidence,
                "classification_margin": classification.margin,
                "used_domain_signal_value_ids": used_ids,
                "evidence_text_zh": self._evidence_text_v6(
                    facts=facts,
                    classification=classification,
                    structure_evidence=structure_evidence,
                    structure_context=structure_context,
                ),
            },
            evidence_items=(
                {
                    "type": self.evidence_type,
                    "selected_regime_code": classification.regime_code,
                    "decision_reason": classification.decision_reason,
                    "competitors": [
                        {"regime_code": code, "score": str(score)} for code, score in classification.competitors
                    ],
                    "structure_context": structure_context,
                    "structure_evidence": structure_evidence,
                    "domain_summary": {
                        code: {
                            "direction": facts[code].direction,
                            "state_code": facts[code].state_code,
                            "strength": str(facts[code].strength),
                        }
                        for code in REQUIRED_DOMAIN_CODES
                    },
                },
            ),
            calculation_summary={
                "selected_regime_code": classification.regime_code,
                "decision_reason": classification.decision_reason,
                "structure_position": structure_context["position"],
                "used_domain_count": len(used_ids),
            },
        )

    def _classify_v6(
        self,
        *,
        facts: dict[str, DomainFact],
        params: Mapping[str, Any],
        structure_context: Mapping[str, Any],
    ) -> ClassificationResult:
        scores = {code: Decimal("0") for code in REGIME_CODES}
        self._score_v6_candidates(scores=scores, facts=facts, structure_context=structure_context)

        risk = facts["risk_state"]
        if risk.state_code == "risk_high_signal_unreliable":
            scores["high_risk_environment"] = Decimal("1.00")
            return self._select(
                regime_code="high_risk_environment",
                scores=scores,
                decision_reason="risk_state 明确提示普通环境分类可靠性显著下降，优先归为高风险环境。",
            )
        if risk.state_code == "risk_unclear":
            scores["unclear_environment"] = max(scores["unclear_environment"], Decimal("0.80"))
            return self._select(
                regime_code="unclear_environment",
                scores=scores,
                decision_reason="risk_state 本身不明确，不能伪装成普通多头、空头或震荡环境。",
            )

        priority_code = self._v6_priority_regime_code(scores=scores, facts=facts, structure_context=structure_context)
        if priority_code:
            return self._select(
                regime_code=priority_code,
                scores=scores,
                decision_reason="v6 根据 Structure 位置事实修正市场环境，优先输出更贴近支撑/压力位置的分类。",
            )

        ordered = self._ordered_scores(scores)
        top_code, top_score = ordered[0]
        second_code, second_score = ordered[1] if len(ordered) > 1 else ("", Decimal("0"))
        min_score = self._decimal_param(params, "min_regime_score", Decimal("0.50"))
        min_margin = self._decimal_param(params, "min_classification_margin", Decimal("0.05"))
        if top_score < min_score:
            scores["unclear_environment"] = max(scores["unclear_environment"], top_score)
            return self._select(
                regime_code="unclear_environment",
                scores=scores,
                decision_reason="最高候选分数不足，输出不明确环境。",
            )
        if top_score - second_score < min_margin:
            if self._regime_family_v6(top_code) == self._regime_family_v6(second_code) and top_score >= Decimal("0.50"):
                return self._select(
                    regime_code=top_code,
                    scores=scores,
                    decision_reason="v6 保留同方向家族内最高分候选。",
                )
            scores["unclear_environment"] = max(scores["unclear_environment"], top_score)
            return self._select(
                regime_code="unclear_environment",
                scores=scores,
                decision_reason="主要候选差距过小，且 Structure 无法收敛到同方向家族，输出不明确环境。",
            )
        return self._select(
            regime_code=top_code,
            scores=scores,
            decision_reason="普通候选分数满足 v6 最低分与最小差距要求。",
        )

    def _score_v6_candidates(
        self,
        *,
        scores: dict[str, Decimal],
        facts: dict[str, DomainFact],
        structure_context: Mapping[str, Any],
    ) -> None:
        context = facts["market_context"]
        trend = facts["trend"]
        momentum = facts["momentum"]
        volatility = facts["volatility"]
        risk = facts["risk_state"]
        risk_ok_bonus = Decimal("0.04") if risk.state_code in {"risk_clear", "risk_elevated_classifiable"} else Decimal("0")
        volatility_drag = Decimal("0.10") if volatility.state_code == "volatility_extreme" else Decimal("0")
        volatility_range_bonus = Decimal("0.08") if volatility.state_code in {
            "volatility_high",
            "volatility_mixed",
            "volatility_low_compression",
        } else Decimal("0")

        bullish_base = (
            self._v6_context_score(context, "bullish")
            + self._v6_direction_score(trend, "bullish", full=Decimal("0.20"), weak=Decimal("0.06"))
            + self._v6_direction_score(momentum, "bullish", full=Decimal("0.14"), weak=Decimal("0.04"))
            + risk_ok_bonus
            - volatility_drag
        )
        bearish_base = (
            self._v6_context_score(context, "bearish")
            + self._v6_direction_score(trend, "bearish", full=Decimal("0.20"), weak=Decimal("0.06"))
            + self._v6_direction_score(momentum, "bearish", full=Decimal("0.14"), weak=Decimal("0.04"))
            + risk_ok_bonus
            - volatility_drag
        )

        support_active = bool(structure_context["support_active"])
        resistance_active = bool(structure_context["resistance_active"])
        sandwich = bool(structure_context["support_resistance_sandwich"])
        support_breakdown_candidate = bool(structure_context["support_breakdown_candidate"])
        resistance_breakout_candidate = bool(structure_context["resistance_breakout_candidate"])
        support_breakdown_confirmed = bool(structure_context["support_breakdown_confirmed"])
        resistance_breakout_confirmed = bool(structure_context["resistance_breakout_confirmed"])
        near_support_weight = Decimal("0.22") if structure_context["major_support_active"] else Decimal("0.14")
        near_resistance_weight = Decimal("0.22") if structure_context["major_resistance_active"] else Decimal("0.14")

        scores["bullish_trend_continuation"] = self._cap(
            bullish_base
            + (Decimal("0.10") if not resistance_active and not support_breakdown_candidate else Decimal("0"))
            - (Decimal("0.12") if resistance_active or sandwich else Decimal("0"))
        )
        scores["bullish_pullback"] = self._cap(
            self._v6_context_score(context, "bullish")
            + self._v6_direction_score(trend, "bullish", full=Decimal("0.16"), weak=Decimal("0.05"))
            + (near_support_weight if support_active and not support_breakdown_confirmed else Decimal("0"))
            + self._v6_counter_move_score(trend=trend, momentum=momentum, primary_direction="bullish")
            + risk_ok_bonus
            - (Decimal("0.18") if resistance_active and not support_active else Decimal("0"))
        )
        scores["bullish_high_range"] = self._cap(
            self._v6_context_score(context, "bullish")
            + (near_resistance_weight if resistance_active or sandwich else Decimal("0"))
            + (Decimal("0.10") if sandwich else Decimal("0"))
            + self._v6_progress_slow_score(trend=trend, momentum=momentum)
            + volatility_range_bonus
            + risk_ok_bonus
        )
        scores["bullish_top_reversal_candidate"] = self._cap(
            self._v6_context_score(context, "bullish")
            + (near_resistance_weight if resistance_active else Decimal("0"))
            + (Decimal("0.18") if support_breakdown_candidate else Decimal("0"))
            + self._v6_pressure_against_direction(trend=trend, momentum=momentum, pressure_direction="bearish")
            + volatility_range_bonus
            + risk_ok_bonus
        )
        scores["bullish_breakout"] = self._cap(
            (Decimal("0.50") if resistance_breakout_confirmed else Decimal("0"))
            + (Decimal("0.18") if resistance_breakout_candidate else Decimal("0"))
            + self._v6_direction_score(trend, "bullish", full=Decimal("0.16"), weak=Decimal("0.04"))
            + self._v6_direction_score(momentum, "bullish", full=Decimal("0.14"), weak=Decimal("0.04"))
            + self._v6_context_score(context, "bullish", opposite_penalty=False)
            + risk_ok_bonus
            - volatility_drag
        )
        if resistance_breakout_candidate and not resistance_breakout_confirmed:
            scores["bullish_breakout"] = min(scores["bullish_breakout"], Decimal("0.4800"))

        scores["bearish_trend_continuation"] = self._cap(
            bearish_base
            + (Decimal("0.10") if not support_active and not resistance_breakout_candidate else Decimal("0"))
            - (Decimal("0.12") if support_active or sandwich else Decimal("0"))
        )
        scores["bearish_rebound"] = self._cap(
            self._v6_context_score(context, "bearish")
            + self._v6_direction_score(trend, "bearish", full=Decimal("0.16"), weak=Decimal("0.05"))
            + (near_resistance_weight if resistance_active and not resistance_breakout_confirmed else Decimal("0"))
            + self._v6_counter_move_score(trend=trend, momentum=momentum, primary_direction="bearish")
            + risk_ok_bonus
            - (Decimal("0.18") if support_active and not resistance_active else Decimal("0"))
        )
        scores["bearish_low_range"] = self._cap(
            self._v6_context_score(context, "bearish")
            + (near_support_weight if support_active or sandwich else Decimal("0"))
            + (Decimal("0.10") if sandwich else Decimal("0"))
            + self._v6_progress_slow_score(trend=trend, momentum=momentum)
            + volatility_range_bonus
            + risk_ok_bonus
        )
        scores["bearish_bottom_reversal_candidate"] = self._cap(
            self._v6_context_score(context, "bearish")
            + (near_support_weight if support_active else Decimal("0"))
            + (Decimal("0.18") if resistance_breakout_candidate else Decimal("0"))
            + self._v6_pressure_against_direction(trend=trend, momentum=momentum, pressure_direction="bullish")
            + volatility_range_bonus
            + risk_ok_bonus
        )
        scores["bearish_breakdown"] = self._cap(
            (Decimal("0.50") if support_breakdown_confirmed else Decimal("0"))
            + (Decimal("0.18") if support_breakdown_candidate else Decimal("0"))
            + self._v6_direction_score(trend, "bearish", full=Decimal("0.16"), weak=Decimal("0.04"))
            + self._v6_direction_score(momentum, "bearish", full=Decimal("0.14"), weak=Decimal("0.04"))
            + self._v6_context_score(context, "bearish", opposite_penalty=False)
            + risk_ok_bonus
            - volatility_drag
        )
        if support_breakdown_candidate and not support_breakdown_confirmed:
            scores["bearish_breakdown"] = min(scores["bearish_breakdown"], Decimal("0.4800"))

        scores["neutral_range"] = self._cap(
            (Decimal("0.24") if context.direction == "neutral" else Decimal("0.06"))
            + (Decimal("0.18") if trend.direction == "neutral" else Decimal("0"))
            + (Decimal("0.18") if sandwich else Decimal("0"))
            + self._v6_progress_slow_score(trend=trend, momentum=momentum)
            + volatility_range_bonus
            + risk_ok_bonus
        )
        if context.direction != "neutral":
            scores["neutral_range"] = min(scores["neutral_range"], Decimal("0.5200"))
        scores["unclear_environment"] = max(
            Decimal("0.25"),
            Decimal("0.50") if structure_context["position"] == "conflicted" else Decimal("0"),
            Decimal("0.42") if sandwich and trend.direction == "neutral" else Decimal("0"),
        )

    def _v6_priority_regime_code(
        self,
        *,
        scores: Mapping[str, Decimal],
        facts: dict[str, DomainFact],
        structure_context: Mapping[str, Any],
    ) -> str:
        context = facts["market_context"]
        if structure_context["support_breakdown_confirmed"] and scores["bearish_breakdown"] >= Decimal("0.5600"):
            return "bearish_breakdown"
        if structure_context["resistance_breakout_confirmed"] and scores["bullish_breakout"] >= Decimal("0.5600"):
            return "bullish_breakout"

        if context.direction == "bullish":
            if structure_context["support_breakdown_candidate"]:
                return self._best_above_floor_v6(
                    scores,
                    Decimal("0.5000"),
                    ("bullish_top_reversal_candidate", "bullish_high_range", "unclear_environment"),
                )
            if structure_context["resistance_active"]:
                return self._best_above_floor_v6(
                    scores,
                    Decimal("0.5000"),
                    ("bullish_top_reversal_candidate", "bullish_high_range", "unclear_environment"),
                )
            if structure_context["support_active"] and not structure_context["support_breakdown_candidate"]:
                return self._best_above_floor_v6(
                    scores,
                    Decimal("0.5000"),
                    ("bullish_pullback", "bullish_trend_continuation"),
                )

        if context.direction == "bearish":
            if structure_context["resistance_breakout_candidate"]:
                return self._best_above_floor_v6(
                    scores,
                    Decimal("0.5000"),
                    ("bearish_bottom_reversal_candidate", "bearish_low_range", "unclear_environment"),
                )
            if structure_context["support_active"]:
                return self._best_above_floor_v6(
                    scores,
                    Decimal("0.5000"),
                    ("bearish_low_range", "bearish_bottom_reversal_candidate", "unclear_environment"),
                )
            if structure_context["resistance_active"] and not structure_context["resistance_breakout_candidate"]:
                return self._best_above_floor_v6(
                    scores,
                    Decimal("0.5000"),
                    ("bearish_rebound", "bearish_trend_continuation"),
                )
        return ""

    @staticmethod
    def _extract_structure_evidence_v6(structure: DomainFact) -> Mapping[str, Any] | None:
        for item in structure.evidence_items:
            if not isinstance(item, Mapping):
                continue
            summary = item.get("summary")
            if isinstance(summary, Mapping) and isinstance(summary.get("structure_evidence"), Mapping):
                return summary["structure_evidence"]
            if isinstance(item.get("structure_evidence"), Mapping):
                return item["structure_evidence"]
        return None

    @staticmethod
    def _level_evidence_v6(structure_evidence: Mapping[str, Any], level: str) -> Mapping[str, Any]:
        value = structure_evidence.get(level)
        return value if isinstance(value, Mapping) else {}

    def _structure_context_v6(self, structure_evidence: Mapping[str, Any]) -> dict[str, Any]:
        major = self._level_evidence_v6(structure_evidence, "major")
        minor = self._level_evidence_v6(structure_evidence, "minor")
        major_context = self._level_context_v6(major)
        minor_context = self._level_context_v6(minor)
        support_active = major_context["support_active"] or minor_context["support_active"]
        resistance_active = major_context["resistance_active"] or minor_context["resistance_active"]
        support_breakdown_confirmed = (
            major_context["support_breakdown_confirmed"] or minor_context["support_breakdown_confirmed"]
        )
        resistance_breakout_confirmed = (
            major_context["resistance_breakout_confirmed"] or minor_context["resistance_breakout_confirmed"]
        )
        support_breakdown_candidate = (
            major_context["support_breakdown_candidate"] or minor_context["support_breakdown_candidate"]
        ) and not support_breakdown_confirmed
        resistance_breakout_candidate = (
            major_context["resistance_breakout_candidate"] or minor_context["resistance_breakout_candidate"]
        ) and not resistance_breakout_confirmed
        sandwich = (
            major_context["support_resistance_sandwich"]
            or minor_context["support_resistance_sandwich"]
            or (support_active and resistance_active)
        )
        position = self._structure_position_v6(
            support_active=support_active,
            resistance_active=resistance_active,
            sandwich=sandwich,
            support_breakdown_candidate=support_breakdown_candidate,
            resistance_breakout_candidate=resistance_breakout_candidate,
            support_breakdown_confirmed=support_breakdown_confirmed,
            resistance_breakout_confirmed=resistance_breakout_confirmed,
            major_position=major_context["position"],
            minor_position=minor_context["position"],
        )
        return {
            "position": position,
            "major_position": major_context["position"],
            "minor_position": minor_context["position"],
            "major_support_active": major_context["support_active"],
            "major_resistance_active": major_context["resistance_active"],
            "minor_support_active": minor_context["support_active"],
            "minor_resistance_active": minor_context["resistance_active"],
            "support_active": support_active,
            "resistance_active": resistance_active,
            "support_resistance_sandwich": sandwich,
            "support_breakdown_candidate": support_breakdown_candidate,
            "resistance_breakout_candidate": resistance_breakout_candidate,
            "support_breakdown_confirmed": support_breakdown_confirmed,
            "resistance_breakout_confirmed": resistance_breakout_confirmed,
            "primary_state_zh": structure_evidence.get("primary_state_zh") or "",
        }

    @staticmethod
    def _level_context_v6(level_evidence: Mapping[str, Any]) -> dict[str, Any]:
        support_breakdown_confirmed = bool(level_evidence.get("support_breakdown_confirmed"))
        resistance_breakout_confirmed = bool(level_evidence.get("resistance_breakout_confirmed"))
        support_breakdown_candidate = bool(level_evidence.get("support_breakdown_candidate"))
        resistance_breakout_candidate = bool(level_evidence.get("resistance_breakout_candidate"))
        support_active = bool(
            level_evidence.get("support_holds")
            or level_evidence.get("support_testing")
            or level_evidence.get("near_support")
        ) and not support_breakdown_confirmed
        resistance_active = bool(
            level_evidence.get("resistance_holds")
            or level_evidence.get("resistance_testing")
            or level_evidence.get("near_resistance")
        ) and not resistance_breakout_confirmed
        sandwich = bool(
            level_evidence.get("between_support_resistance")
            or (support_active and resistance_active)
        )
        if support_breakdown_confirmed:
            position = "support_breakdown_confirmed"
        elif resistance_breakout_confirmed:
            position = "resistance_breakout_confirmed"
        elif support_breakdown_candidate:
            position = "support_breakdown_candidate"
        elif resistance_breakout_candidate:
            position = "resistance_breakout_candidate"
        elif sandwich:
            position = "between_support_resistance"
        elif support_active:
            position = "support_active"
        elif resistance_active:
            position = "resistance_active"
        elif level_evidence.get("state") == "conflicted":
            position = "conflicted"
        else:
            position = "unclear"
        return {
            "position": position,
            "support_active": support_active,
            "resistance_active": resistance_active,
            "support_resistance_sandwich": sandwich,
            "support_breakdown_candidate": support_breakdown_candidate and not support_breakdown_confirmed,
            "resistance_breakout_candidate": resistance_breakout_candidate and not resistance_breakout_confirmed,
            "support_breakdown_confirmed": support_breakdown_confirmed,
            "resistance_breakout_confirmed": resistance_breakout_confirmed,
        }

    @staticmethod
    def _structure_position_v6(
        *,
        support_active: bool,
        resistance_active: bool,
        sandwich: bool,
        support_breakdown_candidate: bool,
        resistance_breakout_candidate: bool,
        support_breakdown_confirmed: bool,
        resistance_breakout_confirmed: bool,
        major_position: str,
        minor_position: str,
    ) -> str:
        if major_position == "conflicted" or minor_position == "conflicted":
            return "conflicted"
        if support_breakdown_confirmed:
            return "support_breakdown_confirmed"
        if resistance_breakout_confirmed:
            return "resistance_breakout_confirmed"
        if support_breakdown_candidate:
            return "support_breakdown_candidate"
        if resistance_breakout_candidate:
            return "resistance_breakout_candidate"
        if sandwich:
            return "between_support_resistance"
        if support_active:
            return "support_active"
        if resistance_active:
            return "resistance_active"
        return "unclear"

    @staticmethod
    def _v6_context_score(context: DomainFact, direction: str, *, opposite_penalty: bool = True) -> Decimal:
        if context.direction == direction:
            return Decimal("0.26")
        if context.direction == "neutral" or not opposite_penalty:
            return Decimal("0.08")
        return Decimal("0")

    @staticmethod
    def _v6_direction_score(fact: DomainFact, direction: str, *, full: Decimal, weak: Decimal) -> Decimal:
        if fact.direction == direction:
            return full
        if fact.direction == "neutral":
            return weak
        return Decimal("0")

    @staticmethod
    def _v6_counter_move_score(*, trend: DomainFact, momentum: DomainFact, primary_direction: str) -> Decimal:
        opposite = "bearish" if primary_direction == "bullish" else "bullish"
        if trend.direction == opposite or momentum.direction == opposite:
            return Decimal("0.12")
        if opposite in trend.state_code or opposite in momentum.state_code or "exhausting" in momentum.state_code:
            return Decimal("0.08")
        return Decimal("0")

    @staticmethod
    def _v6_progress_slow_score(*, trend: DomainFact, momentum: DomainFact) -> Decimal:
        if trend.direction == "neutral":
            return Decimal("0.10")
        if momentum.direction == "neutral" or "choppy" in momentum.state_code or "exhausting" in momentum.state_code:
            return Decimal("0.08")
        return Decimal("0")

    @staticmethod
    def _v6_pressure_against_direction(
        *,
        trend: DomainFact,
        momentum: DomainFact,
        pressure_direction: str,
    ) -> Decimal:
        pressure = Decimal("0")
        if trend.direction == pressure_direction:
            pressure += Decimal("0.12")
        elif pressure_direction in trend.state_code:
            pressure += Decimal("0.08")
        if momentum.direction == pressure_direction:
            pressure += Decimal("0.12")
        elif pressure_direction in momentum.state_code or "exhausting" in momentum.state_code:
            pressure += Decimal("0.06")
        return min(Decimal("0.22"), pressure)

    @staticmethod
    def _best_above_floor_v6(scores: Mapping[str, Decimal], floor: Decimal, codes: tuple[str, ...]) -> str:
        eligible = [(code, scores[code]) for code in codes if scores[code] >= floor]
        if not eligible:
            return ""
        return max(eligible, key=lambda item: item[1])[0]

    @staticmethod
    def _regime_family_v6(regime_code: str) -> str:
        if regime_code.startswith("bullish_"):
            return "bullish"
        if regime_code.startswith("bearish_"):
            return "bearish"
        if regime_code == "neutral_range":
            return "neutral"
        return "other"

    @staticmethod
    def _evidence_text_v6(
        *,
        facts: dict[str, DomainFact],
        classification: ClassificationResult,
        structure_evidence: Mapping[str, Any],
        structure_context: Mapping[str, Any],
    ) -> str:
        competitors = "、".join(f"{code}={score}" for code, score in classification.competitors if code != classification.regime_code)
        facts_zh = structure_evidence.get("facts_zh")
        structure_facts = "、".join(str(item) for item in facts_zh) if isinstance(facts_zh, (list, tuple)) else "无"
        return (
            f"MarketRegime v6 已将本轮六个领域事实归类为 {classification.regime_code}。"
            f"市场大背景={facts['market_context'].direction}/{facts['market_context'].state_code}；"
            f"趋势={facts['trend'].direction}/{facts['trend'].state_code}；"
            f"动能={facts['momentum'].direction}/{facts['momentum'].state_code}；"
            f"波动={facts['volatility'].state_code}；"
            f"结构位置={structure_context['position']}，"
            f"结构证据={structure_evidence.get('primary_state_zh') or '未命名'}，{structure_facts}；"
            f"风险={facts['risk_state'].state_code}。"
            f"选择原因：{classification.decision_reason}"
            f"主要竞争候选：{competitors or '无'}。该结论只描述市场环境，不生成策略、目标仓位或订单动作。"
        )
