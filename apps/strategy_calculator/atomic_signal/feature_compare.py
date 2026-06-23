"""AtomicSignal 模块：比较两个数值特征或特征与常量；不读写数据库、Redis 或外部服务，不涉及交易执行。"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any, Callable, Mapping

from ..contracts import CalculatorInput, CalculatorMetadata, CalculatorOutput, CalculatorType


class FeatureCompareCalculator:
    metadata = CalculatorMetadata(
        algorithm_name="feature_compare",
        algorithm_version="1.0.0",
        calculator_type=CalculatorType.ATOMIC_SIGNAL,
        input_schema_version="1.0",
        output_schema_version="1.0",
        deterministic=True,
        supports_dry_run=True,
        algorithm_requirement_document_path="docs/requirements/atomic_signals.md",
        implementation_document_path="docs/implementation/atomic_signal/feature_compare__1.0.0.md",
    )

    _OPERATORS: dict[str, Callable[[Decimal, Decimal], bool]] = {
        "gt": lambda left, right: left > right,
        "gte": lambda left, right: left >= right,
        "lt": lambda left, right: left < right,
        "lte": lambda left, right: left <= right,
        "eq": lambda left, right: left == right,
        "ne": lambda left, right: left != right,
    }
    _OPERATOR_TEXT = {
        "gt": "高于",
        "gte": "高于或等于",
        "lt": "低于",
        "lte": "低于或等于",
        "eq": "等于",
        "ne": "不等于",
    }

    def calculate(self, calculation_input: CalculatorInput) -> CalculatorOutput:
        params = dict(calculation_input.frozen_params)
        values = dict(calculation_input.values)
        feature_values = values.get("feature_values")
        if not isinstance(feature_values, Mapping):
            return self._failed("feature_values_missing", "缺少原子信号所需的特征值映射")

        left_code = params.get("left_feature_code")
        operator_code = params.get("operator")
        right_code = params.get("right_feature_code")
        if not isinstance(left_code, str) or operator_code not in self._OPERATORS:
            return self._failed("feature_compare_params_invalid", "feature_compare 参数不完整或运算符不受支持")
        left_item = feature_values.get(left_code)
        if not isinstance(left_item, Mapping):
            return self._failed("left_feature_missing", f"缺少特征 {left_code}")

        right_item: Mapping[str, Any] | None = None
        if isinstance(right_code, str):
            right_item = feature_values.get(right_code)
            if not isinstance(right_item, Mapping):
                return self._failed("right_feature_missing", f"缺少特征 {right_code}")
            right_label = right_code
            right_raw = right_item.get("value")
        elif "right_value" in params:
            right_label = "常量"
            right_raw = params["right_value"]
        else:
            return self._failed("right_operand_missing", "缺少右侧特征或常量")

        try:
            left_value = self._decimal(left_item.get("value"))
            right_value = self._decimal(right_raw)
        except ValueError as exc:
            return self._failed("feature_value_invalid", str(exc))

        matched = self._OPERATORS[str(operator_code)](left_value, right_value)
        default_direction = values.get("default_direction")
        if default_direction not in {"bullish", "bearish", "neutral", "none"}:
            return self._failed("default_direction_invalid", "原子信号默认方向不合法")
        direction = str(default_direction) if matched else "neutral"
        strength = Decimal("1") if matched else Decimal("0")
        evidence = {
            "left_feature_code": left_code,
            "left_feature_value_id": left_item.get("feature_value_id"),
            "left_value": str(left_value),
            "operator": operator_code,
            "right_feature_code": right_code or "",
            "right_feature_value_id": right_item.get("feature_value_id") if right_item else None,
            "right_value": str(right_value),
            "result": matched,
        }
        evidence_text = (
            f"{left_code} 为 {left_value}，{self._OPERATOR_TEXT[str(operator_code)]}"
            f" {right_label} 的 {right_value}，因此条件{'成立' if matched else '不成立'}。"
        )
        return CalculatorOutput.succeeded(
            output_schema_version=self.metadata.output_schema_version,
            values={
                "value": matched,
                "direction": direction,
                "strength": strength,
                "confidence": None,
                "evidence_text_zh": evidence_text,
            },
            evidence_items=(evidence,),
            calculation_summary={"matched": matched},
        )

    @classmethod
    def _failed(cls, error_code: str, error_message: str) -> CalculatorOutput:
        return CalculatorOutput.failed(
            output_schema_version=cls.metadata.output_schema_version,
            error_code=error_code,
            error_message=error_message,
        )

    @staticmethod
    def _decimal(value: Any) -> Decimal:
        if isinstance(value, bool) or value is None:
            raise ValueError("特征值不是合法数值")
        try:
            result = Decimal(str(value))
        except (InvalidOperation, ValueError) as exc:
            raise ValueError("特征值不是合法数值") from exc
        if not result.is_finite():
            raise ValueError("特征值必须是有限数值")
        return result
