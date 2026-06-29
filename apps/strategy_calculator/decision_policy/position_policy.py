"""DecisionSnapshot 模块：position_policy/v1 目标仓位映射 calculator。

负责：把标准化 StrategySignal 的 direction / strength / confidence 映射为目标仓位意图。
不负责：市场分析、策略选择、价格条件解释、账户读取、订单规划、风控审批或交易执行。
读写数据库：不涉及。
访问 Redis：不涉及。
访问外部服务：不涉及。
发送 Hermes：不涉及。
调用大模型：不涉及。
涉及交易执行：不涉及。
允许真实交易：否。
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any

from ..contracts import CalculatorInput, CalculatorMetadata, CalculatorOutput, CalculatorType


class PositionPolicyCalculator:
    metadata = CalculatorMetadata(
        algorithm_name="position_policy",
        algorithm_version="v1",
        calculator_type=CalculatorType.DECISION_POLICY,
        input_schema_version="1.0",
        output_schema_version="1.0",
        deterministic=True,
        supports_dry_run=True,
        algorithm_requirement_document_path="docs/requirements/decision_snapshot/position_policy_v1.md",
        implementation_document_path="docs/implementation/decision_snapshot/position_policy__v1.md",
    )

    _TARGET_POSITION = "TARGET_POSITION"
    _NO_TRADE = "NO_TRADE"

    def calculate(self, calculation_input: CalculatorInput) -> CalculatorOutput:
        params = dict(calculation_input.frozen_params)
        values = dict(calculation_input.values)
        try:
            min_strength = self._ratio(params.get("min_strength_for_target", "0.55"), field_name="min_strength_for_target")
            min_confidence = self._ratio(
                params.get("min_confidence_for_target", "0.55"),
                field_name="min_confidence_for_target",
            )
            max_abs = self._ratio(
                params.get("max_abs_target_position_ratio", "0.50"),
                field_name="max_abs_target_position_ratio",
                allow_zero=False,
            )
            rounding_places = self._rounding_places(params.get("rounding_decimal_places", 4))
            if params.get("neutral_intent", self._NO_TRADE) != self._NO_TRADE:
                return self._failed("position_policy_params_invalid", "neutral_intent 必须为 NO_TRADE")
            if params.get("weak_signal_intent", self._NO_TRADE) != self._NO_TRADE:
                return self._failed("position_policy_params_invalid", "weak_signal_intent 必须为 NO_TRADE")
            if params.get("confidence_multiplier_method", "linear_confidence") != "linear_confidence":
                return self._failed("position_policy_params_invalid", "confidence_multiplier_method 不受支持")
            if params.get("strength_mapping_method", "linear_from_threshold_to_max") != "linear_from_threshold_to_max":
                return self._failed("position_policy_params_invalid", "strength_mapping_method 不受支持")
        except ValueError as exc:
            return self._failed("position_policy_params_invalid", str(exc))

        direction = str(values.get("strategy_direction", "")).strip()
        if direction == "neutral":
            return self._no_trade(
                reason_code="neutral_signal_no_trade",
                reason_summary="策略方向为中性，position_policy_v1 不形成目标仓位。",
                target_confidence=Decimal("0"),
                calculation_snapshot={"strategy_direction": direction},
            )
        if direction == "none" or direction not in {"bullish", "bearish"}:
            return self._failed("position_policy_direction_invalid", "strategy_direction 不允许进入目标仓位映射")

        try:
            strength = self._ratio(values.get("strategy_strength"), field_name="strategy_strength")
            confidence = self._ratio(values.get("strategy_confidence"), field_name="strategy_confidence")
        except ValueError as exc:
            return self._failed("position_policy_input_invalid", str(exc))

        if strength < min_strength or confidence < min_confidence:
            return self._no_trade(
                reason_code="weak_signal_no_trade",
                reason_summary="策略强度或置信评分低于 position_policy_v1 的 P0 保守门槛。",
                target_confidence=confidence,
                calculation_snapshot={
                    "strategy_direction": direction,
                    "strategy_strength": str(strength),
                    "strategy_confidence": str(confidence),
                    "min_strength_for_target": str(min_strength),
                    "min_confidence_for_target": str(min_confidence),
                },
            )

        if min_strength >= Decimal("1"):
            strength_score = Decimal("1")
        else:
            strength_score = (strength - min_strength) / (Decimal("1") - min_strength)
        strength_score = self._clamp(strength_score, Decimal("0"), Decimal("1"))
        raw_abs = strength_score * max_abs
        raw_ratio = raw_abs * self._clamp(confidence, Decimal("0"), Decimal("1"))
        if direction == "bearish":
            raw_ratio = -raw_ratio
        rounded_ratio = self._round(raw_ratio, rounding_places)
        if rounded_ratio == Decimal("0"):
            return self._no_trade(
                reason_code="rounded_target_zero",
                reason_summary="目标仓位连续映射后四舍五入为 0，本轮不形成目标仓位。",
                target_confidence=confidence,
                calculation_snapshot={
                    "strategy_direction": direction,
                    "raw_target_position_ratio": str(raw_ratio),
                    "rounding_decimal_places": rounding_places,
                },
            )
        return CalculatorOutput.succeeded(
            output_schema_version=self.metadata.output_schema_version,
            values={
                "target_intent": self._TARGET_POSITION,
                "target_position_ratio": str(rounded_ratio),
                "target_confidence": str(confidence),
                "target_reason_code": "position_policy_target_position",
                "target_reason_summary_zh": "position_policy_v1 根据标准化策略方向、强度和置信评分生成目标仓位语义。",
                "decision_calculation_snapshot": {
                    "strategy_direction": direction,
                    "strategy_strength": str(strength),
                    "strategy_confidence": str(confidence),
                    "min_strength_for_target": str(min_strength),
                    "min_confidence_for_target": str(min_confidence),
                    "max_abs_target_position_ratio": str(max_abs),
                    "strength_score": str(strength_score),
                    "raw_target_position_ratio": str(raw_ratio),
                    "rounding_decimal_places": rounding_places,
                },
            },
            evidence_items=(
                {
                    "type": "position_policy_v1",
                    "strategy_direction": direction,
                    "strategy_strength": str(strength),
                    "strategy_confidence": str(confidence),
                    "target_position_ratio": str(rounded_ratio),
                },
            ),
            calculation_summary={"target_intent": self._TARGET_POSITION},
        )

    def _no_trade(
        self,
        *,
        reason_code: str,
        reason_summary: str,
        target_confidence: Decimal,
        calculation_snapshot: dict[str, Any],
    ) -> CalculatorOutput:
        return CalculatorOutput.succeeded(
            output_schema_version=self.metadata.output_schema_version,
            values={
                "target_intent": self._NO_TRADE,
                "target_position_ratio": None,
                "target_confidence": str(self._clamp(target_confidence, Decimal("0"), Decimal("1"))),
                "target_reason_code": reason_code,
                "target_reason_summary_zh": reason_summary,
                "decision_calculation_snapshot": calculation_snapshot,
            },
            evidence_items=(
                {
                    "type": "position_policy_v1",
                    "target_intent": self._NO_TRADE,
                    "reason_code": reason_code,
                },
            ),
            calculation_summary={"target_intent": self._NO_TRADE},
        )

    @classmethod
    def _failed(cls, error_code: str, error_message: str) -> CalculatorOutput:
        return CalculatorOutput.failed(
            output_schema_version=cls.metadata.output_schema_version,
            error_code=error_code,
            error_message=error_message,
        )

    @staticmethod
    def _ratio(value: Any, *, field_name: str, allow_zero: bool = True) -> Decimal:
        try:
            result = Decimal(str(value))
        except (InvalidOperation, ValueError, TypeError) as exc:
            raise ValueError(f"{field_name} 不是合法 Decimal") from exc
        if not result.is_finite() or result < 0 or result > 1 or (not allow_zero and result == 0):
            raise ValueError(f"{field_name} 必须位于 {'(0, 1]' if not allow_zero else '[0, 1]'}")
        return result

    @staticmethod
    def _rounding_places(value: Any) -> int:
        try:
            places = int(value)
        except (TypeError, ValueError) as exc:
            raise ValueError("rounding_decimal_places 必须是非负整数") from exc
        if places < 0:
            raise ValueError("rounding_decimal_places 必须是非负整数")
        return places

    @staticmethod
    def _round(value: Decimal, places: int) -> Decimal:
        quant = Decimal("1") if places == 0 else Decimal("1").scaleb(-places)
        return value.quantize(quant, rounding=ROUND_HALF_UP)

    @staticmethod
    def _clamp(value: Decimal, minimum: Decimal, maximum: Decimal) -> Decimal:
        return max(minimum, min(maximum, value))
