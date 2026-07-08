"""AtomicSignal 模块：拐点型支撑压力原子事实 calculator。

负责：把已落库的 structure_pivot_* FeatureValue 翻译成最小结构事实。
不负责：识别支撑压力、计算 Feature、聚合 DomainSignal、识别 MarketRegime、选择策略或生成订单动作。
读写数据库：不涉及。
访问 Redis：不涉及。
访问外部服务：不涉及。
发送 Hermes：不涉及。
调用大模型：不涉及。
涉及交易执行：不涉及。
允许真实交易：否。
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any, Mapping

from ..contracts import CalculatorInput, CalculatorMetadata, CalculatorOutput, CalculatorType


class PivotStructureAtomicCalculator:
    metadata = CalculatorMetadata(
        algorithm_name="pivot_structure_atomic",
        algorithm_version="1.0.0",
        calculator_type=CalculatorType.ATOMIC_SIGNAL,
        input_schema_version="1.0",
        output_schema_version="1.0",
        deterministic=True,
        supports_dry_run=True,
        algorithm_requirement_document_path=(
            "docs/requirements/atomic_signals/structure_pivot_support_resistance_atomic_signals.md"
        ),
        implementation_document_path="docs/plans/structure_pivot_support_resistance_implementation_slice.md",
    )

    _VALID_STATUSES = {"active", "testing", "hold"}
    _SUPPORT_BREAKDOWN_STATUSES = {"breakdown_candidate", "breakdown_confirmed"}
    _RESISTANCE_BREAKOUT_STATUSES = {"breakout_candidate", "breakout_confirmed"}

    def calculate(self, calculation_input: CalculatorInput) -> CalculatorOutput:
        params = dict(calculation_input.frozen_params)
        values = dict(calculation_input.values)
        feature_values = values.get("feature_values")
        if not isinstance(feature_values, Mapping):
            return self._failed("feature_values_missing", "缺少原子信号所需 FeatureValue 映射")

        condition = str(params.get("condition") or "").strip()
        if not condition:
            return self._failed("pivot_atomic_condition_missing", "缺少拐点型结构原子条件")

        try:
            evaluation = self._evaluate(condition=condition, params=params, feature_values=feature_values)
        except ValueError as exc:
            return self._failed("pivot_atomic_params_invalid", str(exc))

        matched = bool(evaluation["matched"])
        default_direction = str(values.get("default_direction") or "neutral")
        direction = default_direction if matched else "neutral"
        signal_code = str(values.get("signal_code") or "")
        label = str(params.get("label_zh") or signal_code or "拐点型结构原子")
        evidence_text = self._evidence_text(
            label=label,
            matched=matched,
            condition=condition,
            evaluation=evaluation,
        )
        evidence_item = {
            "evidence_type": "structure_pivot_atomic_condition",
            "signal_code": signal_code,
            "condition": condition,
            "condition_result": matched,
            "level": params.get("level"),
            "side": params.get("side"),
            "timeframe": params.get("timeframe"),
            "window": params.get("window"),
            "used_features": evaluation["used_features"],
            "facts": evaluation["facts"],
            "thresholds": evaluation.get("thresholds", {}),
            "calculation_summary": evaluation["summary"],
        }
        return CalculatorOutput.succeeded(
            output_schema_version=self.metadata.output_schema_version,
            values={
                "value": matched,
                "direction": direction,
                "strength": Decimal("1") if matched else Decimal("0"),
                "confidence": None,
                "evidence_text_zh": evidence_text,
            },
            evidence_items=(evidence_item,),
            calculation_summary={
                "condition": condition,
                "matched": matched,
                "summary": evaluation["summary"],
            },
        )

    def _evaluate(
        self,
        *,
        condition: str,
        params: Mapping[str, Any],
        feature_values: Mapping[str, Any],
    ) -> dict[str, Any]:
        side = str(params.get("side") or "").strip()
        if condition in {"between", "unclear"}:
            return self._evaluate_context(condition=condition, params=params, feature_values=feature_values)
        if side not in {"support", "resistance"}:
            raise ValueError("side 只支持 support / resistance")

        snapshot = self._zone_snapshot(params=params, feature_values=feature_values, side=side)
        status = snapshot["status"]
        has_zone = snapshot["has_zone"]
        matched = False
        thresholds: dict[str, Any] = {}

        if condition == "valid":
            matched = has_zone and status in self._VALID_STATUSES
        elif condition == "near":
            threshold = self._decimal_param(params, "near_threshold")
            thresholds["near_threshold"] = str(threshold)
            distance = snapshot["distance_pct"]
            matched = has_zone and status in self._VALID_STATUSES and distance is not None and Decimal("0") <= distance <= threshold
        elif condition == "testing":
            matched = has_zone and status == "testing"
        elif condition == "holds":
            matched = has_zone and status == "hold"
        elif condition == "breakdown_candidate":
            matched = side == "support" and has_zone and status == "breakdown_candidate"
        elif condition == "breakdown_confirmed":
            matched = side == "support" and has_zone and status == "breakdown_confirmed"
        elif condition == "breakout_candidate":
            matched = side == "resistance" and has_zone and status == "breakout_candidate"
        elif condition == "breakout_confirmed":
            matched = side == "resistance" and has_zone and status == "breakout_confirmed"
        else:
            raise ValueError(f"不支持的拐点型结构原子条件：{condition}")

        return {
            "matched": matched,
            "used_features": snapshot["used_features"],
            "facts": snapshot["facts"],
            "thresholds": thresholds,
            "summary": f"{side} status={status or 'none'} condition={condition}",
        }

    def _evaluate_context(
        self,
        *,
        condition: str,
        params: Mapping[str, Any],
        feature_values: Mapping[str, Any],
    ) -> dict[str, Any]:
        support = self._zone_snapshot(params=params, feature_values=feature_values, side="support")
        resistance = self._zone_snapshot(params=params, feature_values=feature_values, side="resistance")
        support_valid = support["has_zone"] and support["status"] in self._VALID_STATUSES
        resistance_valid = resistance["has_zone"] and resistance["status"] in self._VALID_STATUSES
        support_upper = support["upper"]
        resistance_lower = resistance["lower"]
        support_distance = support["distance_pct"]
        resistance_distance = resistance["distance_pct"]

        between = (
            support_valid
            and resistance_valid
            and support_upper is not None
            and resistance_lower is not None
            and support_upper < resistance_lower
            and support_distance is not None
            and resistance_distance is not None
            and support_distance >= Decimal("0")
            and resistance_distance >= Decimal("0")
        )
        unclear = not support_valid and not resistance_valid
        matched = between if condition == "between" else unclear
        return {
            "matched": matched,
            "used_features": [*support["used_features"], *resistance["used_features"]],
            "facts": [
                *support["facts"],
                *resistance["facts"],
                f"支撑有效={support_valid}",
                f"压力有效={resistance_valid}",
            ],
            "thresholds": {},
            "summary": (
                f"support_valid={support_valid} resistance_valid={resistance_valid} "
                f"support_upper={support_upper} resistance_lower={resistance_lower}"
            ),
        }

    def _zone_snapshot(
        self,
        *,
        params: Mapping[str, Any],
        feature_values: Mapping[str, Any],
        side: str,
    ) -> dict[str, Any]:
        timeframe = str(params.get("timeframe") or "").strip()
        window = str(params.get("window") or "").strip()
        if not timeframe or not window:
            raise ValueError("timeframe/window 不能为空")
        prefix = f"structure_pivot_{side}"
        suffix = f"{timeframe}_{window}"
        codes = {
            "lower": f"{prefix}_lower_{suffix}",
            "upper": f"{prefix}_upper_{suffix}",
            "core": f"{prefix}_core_{suffix}",
            "strength": f"{prefix}_strength_{suffix}",
            "status": f"{prefix}_status_{suffix}",
            "distance_pct": f"structure_pivot_distance_to_{side}_pct_{suffix}",
            "distance_atr": f"structure_pivot_distance_to_{side}_atr_{suffix}",
        }
        lower = self._decimal_feature(feature_values, codes["lower"])
        upper = self._decimal_feature(feature_values, codes["upper"])
        core = self._decimal_feature(feature_values, codes["core"])
        strength = self._decimal_feature(feature_values, codes["strength"])
        status = self._text_feature(feature_values, codes["status"]) or "none"
        distance_pct = self._decimal_feature(feature_values, codes["distance_pct"])
        distance_atr = self._decimal_feature(feature_values, codes["distance_atr"])
        has_zone = lower is not None and upper is not None and core is not None and strength is not None and strength > 0
        return {
            "lower": lower,
            "upper": upper,
            "core": core,
            "strength": strength,
            "status": status,
            "distance_pct": distance_pct,
            "distance_atr": distance_atr,
            "has_zone": has_zone,
            "used_features": [self._feature_item(feature_values, code) for code in codes.values()],
            "facts": [
                f"{side} 区间={self._fmt(lower)}~{self._fmt(upper)}",
                f"{side} 核心价={self._fmt(core)}",
                f"{side} 强度={self._fmt(strength)}",
                f"{side} 状态={status}",
                f"{side} 距离={self._fmt(distance_pct)}",
            ],
        }

    @staticmethod
    def _feature_item(feature_values: Mapping[str, Any], code: str) -> dict[str, Any]:
        item = feature_values.get(code)
        if not isinstance(item, Mapping):
            return {"feature_code": code, "feature_value_id": None, "observed_value": None, "missing": True}
        return {
            "feature_code": code,
            "feature_value_id": item.get("feature_value_id"),
            "observed_value": PivotStructureAtomicCalculator._json_scalar(item.get("value")),
        }

    @staticmethod
    def _decimal_feature(feature_values: Mapping[str, Any], code: str) -> Decimal | None:
        item = feature_values.get(code)
        if not isinstance(item, Mapping):
            return None
        value = item.get("value")
        if value is None:
            return None
        try:
            result = Decimal(str(value))
        except (InvalidOperation, ValueError):
            return None
        return result if result.is_finite() else None

    @staticmethod
    def _text_feature(feature_values: Mapping[str, Any], code: str) -> str | None:
        item = feature_values.get(code)
        if not isinstance(item, Mapping):
            return None
        value = item.get("value")
        if value is None:
            return None
        return str(value)

    @staticmethod
    def _decimal_param(params: Mapping[str, Any], key: str) -> Decimal:
        raw = params.get(key)
        if raw is None:
            raise ValueError(f"缺少参数 {key}")
        try:
            value = Decimal(str(raw))
        except (InvalidOperation, ValueError) as exc:
            raise ValueError(f"参数 {key} 不是合法 Decimal") from exc
        if not value.is_finite() or value < 0:
            raise ValueError(f"参数 {key} 必须是非负有限 Decimal")
        return value

    @staticmethod
    def _evidence_text(
        *,
        label: str,
        matched: bool,
        condition: str,
        evaluation: Mapping[str, Any],
    ) -> str:
        result = "成立" if matched else "不成立"
        facts = "；".join(str(item) for item in evaluation.get("facts", [])[:6])
        return f"{facts}。因此“{label}”{result}。"

    @staticmethod
    def _json_scalar(value: Any) -> Any:
        if isinstance(value, Decimal):
            return str(value)
        return value

    @staticmethod
    def _fmt(value: Any) -> str:
        if value is None:
            return "无"
        return str(value)

    @classmethod
    def _failed(cls, error_code: str, error_message: str) -> CalculatorOutput:
        return CalculatorOutput.failed(
            output_schema_version=cls.metadata.output_schema_version,
            error_code=error_code,
            error_message=error_message,
        )
