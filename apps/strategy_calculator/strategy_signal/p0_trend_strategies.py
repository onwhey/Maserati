"""StrategySignal 模块：P0 趋势类策略信号 calculator。
负责：消费 DomainSignalValue 标准领域事实，输出策略级方向、强度、置信度、价格条件和证据。
不负责：重新计算特征、原子、领域或市场环境；不生成目标仓位、订单、止盈止损订单或交易动作。
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
from decimal import Decimal, InvalidOperation
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
MIN_STRENGTH = Decimal("0.55")
MIN_CONFIDENCE = Decimal("0.55")


@dataclass(frozen=True)
class DomainFact:
    value_id: int
    domain_code: str
    direction: str
    state_code: str
    strength: Decimal
    coverage_ratio: Decimal
    agreement_ratio: Decimal | None
    payload_summary: dict[str, Any]


@dataclass(frozen=True)
class StrategyScore:
    internal_mode: str
    direction: str
    strength: Decimal
    confidence: Decimal
    component_scores: dict[str, Decimal]
    risk_multiplier: Decimal
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]
    price_condition: dict[str, Any]


class BaseP0TrendStrategyCalculator:
    strategy_code = ""
    strategy_version = "v1"
    strategy_direction = StrategySignalDirection.NEUTRAL
    requirement_document_path = ""
    implementation_document_path = "docs/implementation/strategy_signal/p0_trend_strategies__v1.md"

    @property
    def metadata(self) -> CalculatorMetadata:
        return CalculatorMetadata(
            algorithm_name=self.strategy_code,
            algorithm_version=self.strategy_version,
            calculator_type=CalculatorType.STRATEGY_SIGNAL,
            input_schema_version=INPUT_SCHEMA_VERSION,
            output_schema_version=OUTPUT_SCHEMA_VERSION,
            deterministic=True,
            supports_dry_run=True,
            algorithm_requirement_document_path=self.requirement_document_path,
            implementation_document_path=self.implementation_document_path,
            uses_input_weights=False,
        )

    def calculate(self, calculation_input: CalculatorInput) -> CalculatorOutput:
        values = thaw_value(calculation_input.values)
        definition = values.get("strategy_definition")
        if not isinstance(definition, Mapping):
            return self._failed("strategy_definition_missing", "缺少 StrategyDefinition 输入。")
        if definition.get("strategy_code") != self.strategy_code or definition.get("strategy_version") != self.strategy_version:
            return self._failed("strategy_definition_mismatch", "StrategyDefinition 与 calculator 身份不一致。")
        if definition.get("prediction_horizon") != PREDICTION_HORIZON:
            return self._failed("strategy_prediction_horizon_mismatch", "StrategyDefinition 预测周期与策略算法不一致。")
        facts_result = self._facts(values.get("domain_values"))
        if "error_code" in facts_result:
            return self._failed(str(facts_result["error_code"]), str(facts_result["error_message"]))
        facts: dict[str, DomainFact] = facts_result["facts"]
        score = self._score(facts)
        used_refs = [
            {"domain_code": code, "domain_signal_value_id": facts[code].value_id}
            for code in REQUIRED_DOMAIN_CODES
        ]
        return CalculatorOutput.succeeded(
            output_schema_version=OUTPUT_SCHEMA_VERSION,
            values={
                "direction": score.direction,
                "strength": score.strength,
                "confidence": score.confidence,
                "confidence_semantics": "domain_fact_strategy_score",
                "prediction_horizon": PREDICTION_HORIZON,
                "used_domain_signal_value_refs": used_refs,
                "actual_input_weights": {},
                "trade_price_condition": score.price_condition,
                "aggregation_snapshot": self._aggregation_snapshot(score=score, facts=facts),
                "conflict_snapshot": {
                    "has_conflict": bool(score.blockers),
                    "conflicting_domain_codes": self._conflicting_domains(score.blockers),
                    "effect": "neutralized" if score.blockers else "none",
                    "blockers": list(score.blockers),
                    "warnings": list(score.warnings),
                },
                "evidence_text_zh": self._evidence_text(score=score, facts=facts),
            },
            evidence_items=(
                {
                    "type": f"{self.strategy_code}_v1_score",
                    "internal_mode": score.internal_mode,
                    "component_scores": _decimal_text_map(score.component_scores),
                    "risk_multiplier": str(score.risk_multiplier),
                    "blockers": list(score.blockers),
                    "warnings": list(score.warnings),
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
                "strategy_code": self.strategy_code,
                "strategy_version": self.strategy_version,
                "internal_mode": score.internal_mode,
                "direction": score.direction,
                "strength": str(score.strength),
                "confidence": str(score.confidence),
            },
        )

    def _score(self, facts: dict[str, DomainFact]) -> StrategyScore:
        raise NotImplementedError

    def _base_score(
        self,
        *,
        internal_mode: str,
        component_scores: dict[str, Decimal],
        facts: dict[str, DomainFact],
        blockers: list[str],
        warnings: list[str],
        price_condition: dict[str, Any],
    ) -> StrategyScore:
        risk_multiplier = _risk_multiplier(facts["risk_state"])
        raw_strength = _cap(
            Decimal("0.25") * component_scores["context"]
            + Decimal("0.25") * component_scores["trend"]
            + Decimal("0.20") * component_scores["momentum"]
            + Decimal("0.20") * component_scores["structure"]
            + Decimal("0.10") * component_scores["volatility"]
        )
        strength = _cap(raw_strength * risk_multiplier)
        confidence = _confidence(component_scores=component_scores, risk_multiplier=risk_multiplier, blockers=blockers, warnings=warnings)
        direction = self.strategy_direction
        if blockers or strength < MIN_STRENGTH or confidence < MIN_CONFIDENCE:
            direction = StrategySignalDirection.NEUTRAL
        price_condition = _enrich_price_condition_with_structure_zone(price_condition, facts["structure"])
        return StrategyScore(
            internal_mode=internal_mode,
            direction=direction,
            strength=strength,
            confidence=confidence,
            component_scores=component_scores,
            risk_multiplier=risk_multiplier,
            blockers=tuple(blockers),
            warnings=tuple(warnings),
            price_condition=price_condition,
        )

    def _facts(self, raw_domain_values: Any) -> dict[str, Any]:
        if not isinstance(raw_domain_values, list | tuple):
            return {"error_code": "strategy_domain_values_missing", "error_message": "缺少领域事实输入。"}
        facts: dict[str, DomainFact] = {}
        for item in raw_domain_values:
            if not isinstance(item, Mapping):
                return {"error_code": "strategy_domain_value_invalid", "error_message": "领域事实输入必须是结构化映射。"}
            code = str(item.get("domain_code") or "").strip()
            if code in facts:
                return {"error_code": "strategy_domain_value_duplicate", "error_message": f"领域事实重复：{code}"}
            if code:
                try:
                    facts[code] = DomainFact(
                        value_id=int(item.get("domain_signal_value_id")),
                        domain_code=code,
                        direction=str(item.get("direction") or "neutral"),
                        state_code=str(item.get("state_code") or ""),
                        strength=_ratio(item.get("strength")),
                        coverage_ratio=_ratio(item.get("coverage_ratio")),
                        agreement_ratio=_ratio(item.get("agreement_ratio"), allow_none=True),
                        payload_summary=item.get("payload_summary") if isinstance(item.get("payload_summary"), dict) else {},
                    )
                except (TypeError, ValueError) as exc:
                    return {
                        "error_code": "strategy_domain_value_invalid",
                        "error_message": f"领域事实字段非法：{code}，{exc}",
                    }
        missing = sorted(set(REQUIRED_DOMAIN_CODES) - set(facts))
        if missing:
            return {"error_code": "strategy_required_domain_missing", "error_message": f"缺少必需领域：{','.join(missing)}"}
        return {"facts": facts}

    def _aggregation_snapshot(self, *, score: StrategyScore, facts: dict[str, DomainFact]) -> dict[str, Any]:
        return {
            "strategy_code": self.strategy_code,
            "strategy_version": self.strategy_version,
            "internal_mode": score.internal_mode,
            "final_direction": score.direction,
            "final_strength": str(score.strength),
            "final_confidence": str(score.confidence),
            "component_scores": _decimal_text_map(score.component_scores),
            "risk_reference": {
                "risk_state": facts["risk_state"].state_code,
                "risk_multiplier": str(score.risk_multiplier),
                "risk_reward_comment": "仅作为策略解释和风控参考，不是自动订单。",
            },
        }

    def _evidence_text(self, *, score: StrategyScore, facts: dict[str, DomainFact]) -> str:
        direction_text = "偏多" if score.direction == StrategySignalDirection.BULLISH else "偏空" if score.direction == StrategySignalDirection.BEARISH else "中性"
        blockers = "；".join(score.blockers) if score.blockers else "无硬性冲突"
        return (
            f"{self.strategy_code}/v1 基于六个领域事实形成 {score.internal_mode} 判断："
            f"市场背景 {facts['market_context'].direction}/{facts['market_context'].state_code}，"
            f"趋势 {facts['trend'].direction}/{facts['trend'].state_code}，"
            f"动能 {facts['momentum'].direction}/{facts['momentum'].state_code}，"
            f"结构 {facts['structure'].direction}/{facts['structure'].state_code}，"
            f"波动 {facts['volatility'].state_code}，风险 {facts['risk_state'].state_code}。"
            f"最终策略方向为{direction_text}，强度 {score.strength}，置信度 {score.confidence}，冲突：{blockers}。"
        )

    @staticmethod
    def _conflicting_domains(blockers: tuple[str, ...]) -> list[str]:
        result = []
        for domain in REQUIRED_DOMAIN_CODES:
            if any(domain in blocker for blocker in blockers):
                result.append(domain)
        return result

    @classmethod
    def _failed(cls, error_code: str, error_message: str) -> CalculatorOutput:
        return CalculatorOutput.failed(
            output_schema_version=OUTPUT_SCHEMA_VERSION,
            error_code=error_code,
            error_message=error_message,
        )


class LongTrendFollowingCalculator(BaseP0TrendStrategyCalculator):
    strategy_code = "long_trend_following"
    strategy_direction = StrategySignalDirection.BULLISH
    requirement_document_path = "docs/requirements/strategy_signals/long_trend_following_v1.md"

    def _score(self, facts: dict[str, DomainFact]) -> StrategyScore:
        structure = facts["structure"]
        blockers = _base_blockers(facts)
        if facts["market_context"].direction == "bearish":
            blockers.append("market_context_opposes_long_trend")
        if facts["trend"].direction == "bearish":
            blockers.append("trend_opposes_long_trend")
        if _has_state(structure, "breakdown_down"):
            blockers.append("structure_key_support_breakdown")
        if _major_structure_conflicted(structure):
            blockers.append("structure_major_conflicted_for_long_trend")
        warnings = _base_warnings(facts)
        if _minor_structure_conflicted(structure):
            warnings.append("structure_minor_conflicted_wait_support")
        mode = "breakout_continuation" if _has_state(structure, "breakout_up") else "trend_continuation"
        component_scores = {
            "context": _direction_score(facts["market_context"], "bullish", neutral_score="0.45"),
            "trend": _trend_score(facts["trend"], "bullish"),
            "momentum": _momentum_score(facts["momentum"], "bullish"),
            "structure": _long_trend_structure_score(structure),
            "volatility": _volatility_score(facts["volatility"]),
        }
        price_condition = _price_condition(
            condition_type=f"{mode}_price_zone",
            reference_price_zone="突破压力区、突破后回踩不破区域或趋势结构未破坏区域",
            acceptable_price_zone="关键结构上方但尚未明显过度延伸",
            refs=["structure.resistance_zone", "structure.breakout_zone", "structure.trend_structure"],
            reason_code="long_trend_valid_no_chasing",
            reason_summary="多头趋势或突破有效，但不允许在明显远离关键结构时追价。",
        )
        if _minor_structure_conflicted(structure):
            price_condition = _price_condition(
                condition_type="trend_minor_conflict_support_price_zone",
                reference_price_zone="短周期结构冲突时的支撑区、回踩区或趋势结构未破坏区域",
                acceptable_price_zone="支撑区或回踩区附近，且大结构仍未被破坏",
                refs=["structure.support_zone", "structure.current_zone_position"],
                reason_code="long_trend_minor_conflict_wait_support",
                reason_summary="1d 多头趋势仍有效，但 4h 小结构存在冲突；策略不追多，只接受支撑或回踩区域附近的价格条件。",
            )
        return self._base_score(
            internal_mode=mode,
            component_scores=component_scores,
            facts=facts,
            blockers=blockers,
            warnings=warnings,
            price_condition=price_condition,
        )


class LongPullbackSupportCalculator(BaseP0TrendStrategyCalculator):
    strategy_code = "long_pullback_support"
    strategy_direction = StrategySignalDirection.BULLISH
    requirement_document_path = "docs/requirements/strategy_signals/long_pullback_support_v1.md"

    def _score(self, facts: dict[str, DomainFact]) -> StrategyScore:
        blockers = _base_blockers(facts)
        if facts["market_context"].direction == "bearish":
            blockers.append("market_context_opposes_long_pullback")
        if facts["trend"].direction == "bearish":
            blockers.append("trend_structure_broken_for_long_pullback")
        if _has_state(facts["structure"], "breakdown_down"):
            blockers.append("structure_support_breakdown")
        warnings = _base_warnings(facts)
        mode = "pullback_to_support"
        component_scores = {
            "context": _direction_score(facts["market_context"], "bullish", neutral_score="0.40"),
            "trend": _trend_score(facts["trend"], "bullish", pullback_bonus=True),
            "momentum": _pullback_momentum_score(facts["momentum"], desired_direction="bullish"),
            "structure": _near_support_score(facts["structure"]),
            "volatility": _volatility_score(facts["volatility"]),
        }
        return self._base_score(
            internal_mode=mode,
            component_scores=component_scores,
            facts=facts,
            blockers=blockers,
            warnings=warnings,
            price_condition=_price_condition(
                condition_type="pullback_support_price_zone",
                reference_price_zone="1d / 4h 支撑区附近",
                acceptable_price_zone="支撑区附近，且关键支撑未被有效跌破",
                refs=["structure.support_zone", "structure.current_zone_position"],
                reason_code="support_valid_pullback_momentum_weakening",
                reason_summary="只在支撑仍有效且回调动能不失控时考虑本策略，禁止远离支撑追价。",
            ),
        )


class ShortTrendFollowingCalculator(BaseP0TrendStrategyCalculator):
    strategy_code = "short_trend_following"
    strategy_direction = StrategySignalDirection.BEARISH
    requirement_document_path = "docs/requirements/strategy_signals/short_trend_following_v1.md"

    def _score(self, facts: dict[str, DomainFact]) -> StrategyScore:
        structure = facts["structure"]
        blockers = _base_blockers(facts)
        if facts["market_context"].direction == "bullish":
            blockers.append("market_context_opposes_short_trend")
        if facts["trend"].direction == "bullish":
            blockers.append("trend_opposes_short_trend")
        if _has_state(structure, "breakout_up"):
            blockers.append("structure_key_resistance_breakout")
        if _major_structure_conflicted(structure):
            blockers.append("structure_major_conflicted_for_short_trend")
        warnings = _base_warnings(facts)
        if _minor_structure_conflicted(structure):
            warnings.append("structure_minor_conflicted_wait_pressure")
        mode = "breakdown_continuation" if _has_state(structure, "breakdown_down") else "trend_continuation"
        component_scores = {
            "context": _direction_score(facts["market_context"], "bearish", neutral_score="0.45"),
            "trend": _trend_score(facts["trend"], "bearish"),
            "momentum": _momentum_score(facts["momentum"], "bearish"),
            "structure": _short_trend_structure_score(structure),
            "volatility": _volatility_score(facts["volatility"]),
        }
        price_condition = _price_condition(
            condition_type=f"{mode}_price_zone",
            reference_price_zone="跌破支撑区、跌破后回抽不修复区域或趋势结构未修复区域",
            acceptable_price_zone="关键结构下方但尚未明显过度延伸",
            refs=["structure.support_zone", "structure.breakdown_zone", "structure.trend_structure"],
            reason_code="short_trend_valid_no_chasing",
            reason_summary="空头趋势或跌破有效，但不允许在明显远离关键结构时追价。",
        )
        if _minor_structure_conflicted(structure):
            price_condition = _price_condition(
                condition_type="trend_minor_conflict_resistance_price_zone",
                reference_price_zone="短周期结构冲突时的压力区、反弹区或趋势结构未修复区域",
                acceptable_price_zone="压力区或反弹区附近，且大结构仍未被修复",
                refs=["structure.resistance_zone", "structure.current_zone_position"],
                reason_code="short_trend_minor_conflict_wait_pressure",
                reason_summary="1d 空头趋势仍有效，但 4h 小结构存在冲突；策略不追空，只接受压力或反弹区域附近的价格条件。",
            )
        return self._base_score(
            internal_mode=mode,
            component_scores=component_scores,
            facts=facts,
            blockers=blockers,
            warnings=warnings,
            price_condition=price_condition,
        )


class ShortReboundPressureCalculator(BaseP0TrendStrategyCalculator):
    strategy_code = "short_rebound_pressure"
    strategy_direction = StrategySignalDirection.BEARISH
    requirement_document_path = "docs/requirements/strategy_signals/short_rebound_pressure_v1.md"

    def _score(self, facts: dict[str, DomainFact]) -> StrategyScore:
        blockers = _base_blockers(facts)
        if facts["market_context"].direction == "bullish":
            blockers.append("market_context_opposes_short_rebound")
        if facts["trend"].direction == "bullish":
            blockers.append("trend_structure_repaired_for_short_rebound")
        if _has_state(facts["structure"], "breakout_up"):
            blockers.append("structure_resistance_breakout")
        warnings = _base_warnings(facts)
        mode = "rebound_to_pressure"
        component_scores = {
            "context": _direction_score(facts["market_context"], "bearish", neutral_score="0.40"),
            "trend": _trend_score(facts["trend"], "bearish", pullback_bonus=True),
            "momentum": _pullback_momentum_score(facts["momentum"], desired_direction="bearish"),
            "structure": _near_resistance_score(facts["structure"]),
            "volatility": _volatility_score(facts["volatility"]),
        }
        return self._base_score(
            internal_mode=mode,
            component_scores=component_scores,
            facts=facts,
            blockers=blockers,
            warnings=warnings,
            price_condition=_price_condition(
                condition_type="rebound_pressure_price_zone",
                reference_price_zone="1d / 4h 压力区附近",
                acceptable_price_zone="压力区附近，且关键压力未被有效突破",
                refs=["structure.resistance_zone", "structure.current_zone_position"],
                reason_code="pressure_valid_rebound_momentum_weakening",
                reason_summary="只在压力仍有效且反弹动能不失控时考虑本策略，禁止远离压力追价。",
            ),
        )


def _ratio(value: Any, *, allow_none: bool = False) -> Decimal | None:
    if value is None and allow_none:
        return None
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError("领域事实数值不是合法 Decimal") from exc
    if not result.is_finite():
        raise ValueError("领域事实数值必须是有限数")
    return _cap(result)


def _cap(value: Decimal, *, low: Decimal = Decimal("0"), high: Decimal = Decimal("1")) -> Decimal:
    return max(low, min(high, value))


def _has_state(fact: DomainFact, fragment: str) -> bool:
    return fragment in fact.state_code


def _major_structure_conflicted(fact: DomainFact) -> bool:
    return fact.state_code in {"structure_major_conflicted", "structure_conflicted"}


def _minor_structure_conflicted(fact: DomainFact) -> bool:
    return "minor_conflicted" in fact.state_code


def _direction_score(fact: DomainFact, desired: str, *, neutral_score: str = "0.35") -> Decimal:
    if fact.direction == desired:
        return max(fact.strength, Decimal("0.55"))
    if fact.direction == "neutral":
        return Decimal(neutral_score)
    return Decimal("0")


def _trend_score(fact: DomainFact, desired: str, *, pullback_bonus: bool = False) -> Decimal:
    if fact.direction != desired:
        return Decimal("0.25") if fact.direction == "neutral" else Decimal("0")
    score = max(fact.strength, Decimal("0.55"))
    if "aligned" in fact.state_code:
        return _cap(score + Decimal("0.15"))
    if any(token in fact.state_code for token in ("pullback", "rebound")):
        return _cap(score + Decimal("0.05")) if pullback_bonus else _cap(score * Decimal("0.75"))
    return score


def _momentum_score(fact: DomainFact, desired: str) -> Decimal:
    if fact.direction == desired:
        score = max(fact.strength, Decimal("0.55"))
        if "strengthening" in fact.state_code:
            return _cap(score + Decimal("0.15"))
        if "exhausting" in fact.state_code:
            return _cap(score * Decimal("0.65"))
        return score
    if fact.direction == "neutral":
        return Decimal("0.45")
    if "exhausting" in fact.state_code:
        return Decimal("0.35")
    return Decimal("0.10")


def _pullback_momentum_score(fact: DomainFact, *, desired_direction: str) -> Decimal:
    opposite = "bearish" if desired_direction == "bullish" else "bullish"
    if fact.direction == desired_direction:
        return _cap(max(fact.strength, Decimal("0.55")) * Decimal("0.75"))
    if fact.direction == opposite and "exhausting" in fact.state_code:
        return Decimal("0.80")
    if fact.direction == "neutral":
        return Decimal("0.58")
    if fact.direction == opposite and "strengthening" in fact.state_code:
        return Decimal("0.10")
    return Decimal("0.45")


def _long_trend_structure_score(fact: DomainFact) -> Decimal:
    if _major_structure_conflicted(fact):
        return Decimal("0")
    if _minor_structure_conflicted(fact):
        if _has_state(fact, "breakout_up"):
            return Decimal("0.65")
        return Decimal("0.45")
    if _has_state(fact, "breakout_up"):
        return Decimal("0.95")
    if _has_state(fact, "breakdown_down"):
        return Decimal("0")
    if _has_state(fact, "near_resistance"):
        return Decimal("0.35")
    if fact.direction == "bullish":
        return max(fact.strength, Decimal("0.60"))
    return Decimal("0.50")


def _short_trend_structure_score(fact: DomainFact) -> Decimal:
    if _major_structure_conflicted(fact):
        return Decimal("0")
    if _minor_structure_conflicted(fact):
        if _has_state(fact, "breakdown_down"):
            return Decimal("0.65")
        return Decimal("0.45")
    if _has_state(fact, "breakdown_down"):
        return Decimal("0.95")
    if _has_state(fact, "breakout_up"):
        return Decimal("0")
    if _has_state(fact, "near_support"):
        return Decimal("0.35")
    if fact.direction == "bearish":
        return max(fact.strength, Decimal("0.60"))
    return Decimal("0.50")


def _near_support_score(fact: DomainFact) -> Decimal:
    if _has_state(fact, "breakdown_down"):
        return Decimal("0")
    if _has_state(fact, "near_support"):
        return Decimal("0.90")
    if "minor_near_support" in fact.state_code:
        return Decimal("0.72")
    if _has_state(fact, "range_middle"):
        return Decimal("0.45")
    return Decimal("0.35")


def _near_resistance_score(fact: DomainFact) -> Decimal:
    if _has_state(fact, "breakout_up"):
        return Decimal("0")
    if _has_state(fact, "near_resistance"):
        return Decimal("0.90")
    if "minor_near_resistance" in fact.state_code:
        return Decimal("0.72")
    if _has_state(fact, "range_middle"):
        return Decimal("0.45")
    return Decimal("0.35")


def _volatility_score(fact: DomainFact) -> Decimal:
    if fact.state_code == "volatility_extreme":
        return Decimal("0.25")
    if fact.state_code == "volatility_high":
        return Decimal("0.65")
    if fact.state_code in {"volatility_low_compression", "volatility_low"}:
        return Decimal("0.45")
    if fact.state_code == "volatility_mixed":
        return Decimal("0.55")
    return Decimal("0.75")


def _risk_multiplier(fact: DomainFact) -> Decimal:
    if fact.state_code == "risk_clear":
        return Decimal("1")
    if fact.state_code == "risk_elevated_classifiable":
        return Decimal("0.75")
    return Decimal("0")


def _base_blockers(facts: dict[str, DomainFact]) -> list[str]:
    risk = facts["risk_state"].state_code
    if risk == "risk_high_signal_unreliable":
        return ["risk_state_high_signal_unreliable"]
    if risk == "risk_unclear":
        return ["risk_state_unclear"]
    return []


def _base_warnings(facts: dict[str, DomainFact]) -> list[str]:
    warnings = []
    if facts["risk_state"].state_code == "risk_elevated_classifiable":
        warnings.append("risk_state_elevated_classifiable")
    if facts["volatility"].state_code in {"volatility_extreme", "volatility_mixed"}:
        warnings.append(f"volatility_state_{facts['volatility'].state_code}")
    return warnings


def _confidence(
    *,
    component_scores: Mapping[str, Decimal],
    risk_multiplier: Decimal,
    blockers: list[str],
    warnings: list[str],
) -> Decimal:
    average = sum(component_scores.values(), Decimal("0")) / Decimal(len(component_scores))
    minimum = min(component_scores.values())
    confidence = Decimal("0.30") + Decimal("0.45") * average + Decimal("0.25") * minimum
    if risk_multiplier < Decimal("1"):
        confidence *= risk_multiplier
    confidence -= Decimal("0.12") * Decimal(len(warnings))
    confidence -= Decimal("0.25") * Decimal(len(blockers))
    return _cap(confidence)


def _enrich_price_condition_with_structure_zone(price_condition: dict[str, Any], structure_fact: DomainFact) -> dict[str, Any]:
    refs = price_condition.get("support_or_resistance_refs")
    if not isinstance(refs, list):
        return price_condition
    zone_key = ""
    if "structure.support_zone" in refs and "structure.resistance_zone" not in refs:
        zone_key = "support_zone"
    elif "structure.resistance_zone" in refs and "structure.support_zone" not in refs:
        zone_key = "resistance_zone"
    if not zone_key:
        return price_condition
    zone = _structure_zone(structure_fact, zone_key)
    if zone is None:
        return price_condition
    return {**price_condition, "acceptable_price_zone": zone}


def _structure_zone(structure_fact: DomainFact, zone_key: str) -> dict[str, str] | None:
    raw_zone = structure_fact.payload_summary.get(zone_key)
    if not isinstance(raw_zone, Mapping):
        return None
    lower = raw_zone.get("lower")
    upper = raw_zone.get("upper")
    if lower is None or upper is None:
        return None
    try:
        lower_decimal = Decimal(str(lower))
        upper_decimal = Decimal(str(upper))
    except (InvalidOperation, ValueError):
        return None
    if not lower_decimal.is_finite() or not upper_decimal.is_finite() or lower_decimal > upper_decimal:
        return None
    return {"lower": str(lower), "upper": str(upper)}


def _price_condition(
    *,
    condition_type: str,
    reference_price_zone: str,
    acceptable_price_zone: Any,
    refs: list[str],
    reason_code: str,
    reason_summary: str,
) -> dict[str, Any]:
    return {
        "condition_type": condition_type,
        "reference_price_zone": reference_price_zone,
        "acceptable_price_zone": acceptable_price_zone,
        "support_or_resistance_refs": refs,
        "allow_chasing": False,
        "reason_code": reason_code,
        "reason_summary_zh": reason_summary,
    }


def _decimal_text_map(values: Mapping[str, Decimal]) -> dict[str, str]:
    return {key: str(value) for key, value in values.items()}
