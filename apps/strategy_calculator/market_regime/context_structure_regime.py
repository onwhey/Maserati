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

    def calculate(self, calculation_input: CalculatorInput) -> CalculatorOutput:
        values = dict(calculation_input.values)
        params = dict(calculation_input.frozen_params)
        allowed_regime_codes = self._string_tuple(values.get("allowed_regime_codes"))
        if set(allowed_regime_codes) != set(REGIME_CODES):
            return self._failed(
                "context_structure_regime_allowed_codes_invalid",
                "context_structure_regime/v1 必须使用文档登记的完整 regime_code 集合。",
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
                    "type": "context_structure_regime_v1",
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

    @staticmethod
    def _failed(error_code: str, error_message: str) -> CalculatorOutput:
        return CalculatorOutput.failed(
            output_schema_version=ContextStructureRegimeCalculator.metadata.output_schema_version,
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
