"""RiskState DomainSignal v2 calculator.

所属模块：StrategyCalculator / DomainSignal。
负责：把已落库并传入的 risk_state 原子信号聚合成市场风险状态、风险分数和信号失真摘要。
不负责：计算 Feature、生成 AtomicSignal、识别 MarketRegime、选择策略、生成目标仓位或订单动作。
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

from ..contracts import CalculatorMetadata, CalculatorType
from .grouped_atomic_aggregation import GroupedAtomicAggregationCalculator


class RiskStateAggregationV2Calculator(GroupedAtomicAggregationCalculator):
    """RiskState v2 聚合器。

    这里仍复用 GroupedAtomicAggregationCalculator 的输入/输出壳，
    但只覆盖 risk_state 的领域聚合逻辑，避免把风险状态的业务口径继续塞进通用聚合器。
    """

    metadata = CalculatorMetadata(
        algorithm_name="risk_state_aggregation",
        algorithm_version="2.0.0",
        calculator_type=CalculatorType.DOMAIN_SIGNAL,
        input_schema_version="1.0",
        output_schema_version="1.0",
        deterministic=True,
        supports_dry_run=True,
        algorithm_requirement_document_path="docs/requirements/domain_signals/risk_state_domain_signals_v2.md",
        implementation_document_path="docs/implementation/domain_signal/risk_state_aggregation__2.0.0.md",
    )

    _CATEGORY_NAMES = (
        "signal_reliability_risk",
        "long_exposure_risk",
        "short_exposure_risk",
        "long_chase_risk",
        "short_chase_risk",
        "false_breakout_risk",
        "false_breakdown_risk",
        "market_disorder_risk",
    )
    _DISTORTION_CATEGORIES = {
        "signal_reliability_risk",
        "false_breakout_risk",
        "false_breakdown_risk",
        "market_disorder_risk",
    }
    _EXPOSURE_CATEGORIES = {
        "long_exposure_risk",
        "short_exposure_risk",
    }
    _CHASE_CATEGORIES = {
        "long_chase_risk",
        "short_chase_risk",
    }
    _CATEGORY_EVENT = {
        "signal_reliability_risk": "signal_distortion_event",
        "false_breakout_risk": "false_breakout_distortion_event",
        "false_breakdown_risk": "false_breakdown_distortion_event",
        "market_disorder_risk": "market_disorder_event",
        "long_exposure_risk": "long_exposure_risk",
        "short_exposure_risk": "short_exposure_risk",
        "long_chase_risk": "chase_risk_after_shock",
        "short_chase_risk": "chase_risk_after_shock",
    }

    def _risk_state(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        active = payload["active_set"]
        values_by_code = payload["values_by_code"]
        category_scores: dict[str, Decimal] = {category: Decimal("0") for category in self._CATEGORY_NAMES}
        risk_directions: set[str] = set()
        active_risks: list[dict[str, str]] = []
        risk_effect_tags: set[str] = set()

        for code in active:
            item = values_by_code.get(code, {})
            value_json = item.get("value_json")
            if not isinstance(value_json, Mapping):
                continue
            category = str(value_json.get("risk_category") or "")
            direction = str(value_json.get("risk_direction") or "")
            severity = str(value_json.get("risk_severity") or "none")
            score = self._score_from_severity(severity)
            if category in category_scores and score > category_scores[category]:
                category_scores[category] = score
            if direction:
                risk_directions.add(direction)
            if category:
                risk_effect_tags.add(category)
            if category in self._DISTORTION_CATEGORIES:
                risk_effect_tags.add("signal_distortion")
            if category in self._EXPOSURE_CATEGORIES:
                risk_effect_tags.add("directional_exposure")
            if category in self._CHASE_CATEGORIES:
                risk_effect_tags.add("chase_risk")
            if code == "risk_intrabar_extreme_range":
                risk_effect_tags.update(
                    {
                        "intrabar_extreme_range",
                        "market_shock",
                        "signal_distortion",
                        "two_sided_instability",
                    }
                )
            active_risks.append(
                {
                    "signal_code": code,
                    "risk_category": category,
                    "risk_direction": direction,
                    "risk_severity": severity,
                }
            )

        signal_distortion_score = max(category_scores[category] for category in self._DISTORTION_CATEGORIES)
        risk_score_ratio = max(category_scores.values()) if category_scores else Decimal("0")
        directional_exposure_score_ratio = max(category_scores[category] for category in self._EXPOSURE_CATEGORIES)
        chase_risk_score_ratio = max(category_scores[category] for category in self._CHASE_CATEGORIES)
        elevated_categories = [category for category, score in category_scores.items() if score >= Decimal("0.55")]
        dominant_categories = [category for category, score in category_scores.items() if score == risk_score_ratio and score > 0]

        direction_stability_score = self._direction_stability_score(
            risk_directions=risk_directions,
            signal_distortion_score=signal_distortion_score,
            elevated_category_count=len(elevated_categories),
        )
        unclear = self._is_unclear(category_scores=category_scores, elevated_category_count=len(elevated_categories))
        high_unreliable = signal_distortion_score >= Decimal("0.70")

        if high_unreliable:
            state_code = "risk_high_signal_unreliable"
        elif unclear:
            state_code = "risk_unclear"
        elif elevated_categories:
            state_code = "risk_elevated_classifiable"
        else:
            state_code = "risk_clear"

        primary_event = self._primary_risk_event(dominant_categories, active_codes=set(active))
        risk_score = self._score_to_int(risk_score_ratio)
        market_event_score = risk_score
        distortion_score = self._score_to_int(signal_distortion_score)
        directional_exposure_score = self._score_to_int(directional_exposure_score_ratio)
        chase_risk_score = self._score_to_int(chase_risk_score_ratio)
        event_phase = self._event_phase(
            market_event_score=market_event_score,
            signal_distortion_score=distortion_score,
            risk_effect_tags=risk_effect_tags,
        )
        summary = {
            "risk_state": state_code,
            "risk_score": risk_score,
            "market_event_score": market_event_score,
            "signal_distortion_score": distortion_score,
            "directional_exposure_score": directional_exposure_score,
            "chase_risk_score": chase_risk_score,
            "direction_stability_score": direction_stability_score,
            "primary_risk_event": primary_event,
            "risk_event_phase": event_phase,
            "post_shock_observation_bars_remaining": 0,
            "risk_effect_tags": sorted(risk_effect_tags),
            "dominant_risk_categories": dominant_categories,
            "risk_directions": sorted(risk_directions),
            "active_risks": active_risks,
            "active_market_events": active_risks,
            "directional_exposure": self._directional_exposure(category_scores=category_scores),
            "category_scores": {category: self._score_to_int(score) for category, score in category_scores.items()},
        }
        return {
            "direction": "none",
            "state_code": state_code,
            "strength": risk_score_ratio,
            "agreement_ratio": Decimal("0"),
            "counts": {category: str(score) for category, score in category_scores.items()},
            "state_tags": sorted(elevated_categories),
            "summary": summary,
            "evidence_text_zh": (
                f"RiskState v2 领域聚合完成：状态为 {state_code}，市场事件分数 {market_event_score}，"
                f"信号失真分数 {distortion_score}，方向暴露分数 {directional_exposure_score}，"
                f"主要事件为 {primary_event}。该结论只描述市场冲击、信号可靠性和方向暴露事实，"
                "不等于停止交易、减仓或下单。"
            ),
        }

    @staticmethod
    def _score_from_severity(severity: str) -> Decimal:
        if severity == "high":
            return Decimal("1")
        if severity == "elevated":
            return Decimal("0.55")
        return Decimal("0")

    @staticmethod
    def _score_to_int(score: Decimal) -> int:
        return int((score * Decimal("100")).to_integral_value())

    @staticmethod
    def _direction_stability_score(
        *,
        risk_directions: set[str],
        signal_distortion_score: Decimal,
        elevated_category_count: int,
    ) -> int:
        directional = {direction for direction in risk_directions if direction in {"upside", "downside"}}
        if "two_sided" in risk_directions or len(directional) >= 2:
            return 25
        if signal_distortion_score >= Decimal("0.70"):
            return 40
        if signal_distortion_score >= Decimal("0.55") or elevated_category_count >= 3:
            return 60
        return 100

    @staticmethod
    def _is_unclear(*, category_scores: Mapping[str, Decimal], elevated_category_count: int) -> bool:
        return (
            category_scores["long_exposure_risk"] >= Decimal("0.55")
            and category_scores["short_exposure_risk"] >= Decimal("0.55")
        ) or (
            category_scores["long_chase_risk"] >= Decimal("0.55")
            and category_scores["short_chase_risk"] >= Decimal("0.55")
        ) or (
            category_scores["false_breakout_risk"] >= Decimal("0.55")
            and category_scores["false_breakdown_risk"] >= Decimal("0.55")
        ) or elevated_category_count >= 3

    @classmethod
    def _primary_risk_event(cls, dominant_categories: list[str], *, active_codes: set[str]) -> str:
        if "risk_intrabar_extreme_range" in active_codes and "signal_reliability_risk" in dominant_categories:
            return "intrabar_extreme_range_event"
        for category in (
            "signal_reliability_risk",
            "market_disorder_risk",
            "false_breakout_risk",
            "false_breakdown_risk",
            "long_exposure_risk",
            "short_exposure_risk",
            "long_chase_risk",
            "short_chase_risk",
        ):
            if category in dominant_categories:
                return cls._CATEGORY_EVENT[category]
        return "none"

    @staticmethod
    def _directional_exposure(*, category_scores: Mapping[str, Decimal]) -> dict[str, str | int]:
        long_score = int((category_scores["long_exposure_risk"] * Decimal("100")).to_integral_value())
        short_score = int((category_scores["short_exposure_risk"] * Decimal("100")).to_integral_value())
        if long_score > 0 and short_score > 0:
            dominant_position = "mixed"
        elif long_score > 0:
            dominant_position = "long_position"
        elif short_score > 0:
            dominant_position = "short_position"
        else:
            dominant_position = "none"
        return {
            "dominant_exposed_position": dominant_position,
            "long_position_exposure_score": long_score,
            "short_position_exposure_score": short_score,
        }

    @staticmethod
    def _event_phase(
        *,
        market_event_score: int,
        signal_distortion_score: int,
        risk_effect_tags: set[str],
    ) -> str:
        if "market_shock" in risk_effect_tags and market_event_score >= 70:
            return "shock_active"
        if signal_distortion_score >= 70:
            return "signal_distortion_active"
        if market_event_score >= 70:
            return "risk_event_active"
        return "none"
