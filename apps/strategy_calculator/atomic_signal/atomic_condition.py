"""AtomicSignal 模块：基于已落库 FeatureValue 做通用条件判断。

负责：读取 calculator 输入中的 FeatureValue 摘要并判断条件是否成立。
不负责：计算 Feature、聚合领域信号、识别市场环境、选择策略或生成订单动作。
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
from typing import Any, Callable, Mapping

from ..contracts import CalculatorInput, CalculatorMetadata, CalculatorOutput, CalculatorType


class AtomicConditionCalculator:
    metadata = CalculatorMetadata(
        algorithm_name="atomic_condition",
        algorithm_version="1.0.0",
        calculator_type=CalculatorType.ATOMIC_SIGNAL,
        input_schema_version="1.0",
        output_schema_version="1.0",
        deterministic=True,
        supports_dry_run=True,
        algorithm_requirement_document_path="docs/requirements/atomic_signals/strategy_atomic_signal_design.md",
        implementation_document_path="docs/implementation/atomic_signal/atomic_condition__1.0.0.md",
    )

    _OPERATORS: dict[str, Callable[[Decimal, Decimal], bool]] = {
        "gt": lambda left, right: left > right,
        "gte": lambda left, right: left >= right,
        "lt": lambda left, right: left < right,
        "lte": lambda left, right: left <= right,
        "eq": lambda left, right: left == right,
        "ne": lambda left, right: left != right,
        "abs_gte": lambda left, right: abs(left) >= right,
        "abs_lte": lambda left, right: abs(left) <= right,
    }
    _OPERATOR_TEXT = {
        "gt": "大于",
        "gte": "大于或等于",
        "lt": "小于",
        "lte": "小于或等于",
        "eq": "等于",
        "ne": "不等于",
        "abs_gte": "绝对值大于或等于",
        "abs_lte": "绝对值小于或等于",
        "is_null": "为空",
        "is_not_null": "不为空",
    }

    def calculate(self, calculation_input: CalculatorInput) -> CalculatorOutput:
        params = dict(calculation_input.frozen_params)
        values = dict(calculation_input.values)
        feature_values = values.get("feature_values")
        if not isinstance(feature_values, Mapping):
            return self._failed("feature_values_missing", "缺少原子信号所需的 FeatureValue 映射")

        conditions = params.get("conditions")
        if not isinstance(conditions, (list, tuple)) or not conditions:
            return self._failed("atomic_condition_params_invalid", "conditions 必须是非空列表")
        aggregation = str(params.get("aggregation", "all"))
        if aggregation not in {"all", "any"}:
            return self._failed("atomic_condition_params_invalid", "aggregation 只支持 all / any")

        condition_results: list[dict[str, Any]] = []
        for condition in conditions:
            if not isinstance(condition, Mapping):
                return self._failed("atomic_condition_params_invalid", "condition 必须是映射")
            result = self._evaluate_condition(condition, feature_values)
            if result.get("error_code"):
                return self._failed(str(result["error_code"]), str(result["error_message"]))
            condition_results.append(result)

        matched = all(item["result"] for item in condition_results) if aggregation == "all" else any(
            item["result"] for item in condition_results
        )
        default_direction = values.get("default_direction")
        if default_direction not in {"bullish", "bearish", "neutral", "none"}:
            return self._failed("default_direction_invalid", "原子信号默认方向不合法")
        direction = str(default_direction) if matched else "neutral"
        strength = self._decimal_param(params.get("strength_when_matched", "1"), field_name="strength_when_matched")
        confidence_raw = params.get("confidence_when_matched")
        confidence = None
        if confidence_raw is not None:
            confidence = self._decimal_param(confidence_raw, field_name="confidence_when_matched")

        output_value = matched
        if params.get("value_mode") == "json":
            output_value = self._json_value(params, matched, feature_values)

        evidence_item = self._evidence_item(
            signal_code=str(values.get("signal_code") or ""),
            params=params,
            matched=matched,
            condition_results=condition_results,
        )
        evidence_text = self._evidence_text(
            params=params,
            matched=matched,
            condition_results=condition_results,
        )
        return CalculatorOutput.succeeded(
            output_schema_version=self.metadata.output_schema_version,
            values={
                "value": output_value,
                "direction": direction,
                "strength": strength if matched else Decimal("0"),
                "confidence": confidence if matched else None,
                "evidence_text_zh": evidence_text,
            },
            evidence_items=(evidence_item,),
            calculation_summary={"matched": matched, "aggregation": aggregation},
        )

    def _evaluate_condition(self, condition: Mapping[str, Any], feature_values: Mapping[str, Any]) -> dict[str, Any]:
        feature_code = condition.get("feature_code")
        operator_code = condition.get("operator")
        if not isinstance(feature_code, str) or not feature_code:
            return self._condition_error("atomic_condition_params_invalid", "condition 缺少 feature_code")
        if not isinstance(operator_code, str) or not operator_code:
            return self._condition_error("atomic_condition_params_invalid", "condition 缺少 operator")
        item = feature_values.get(feature_code)
        if not isinstance(item, Mapping):
            return self._condition_error("atomic_condition_feature_missing", f"缺少特征 {feature_code}")
        left_raw = item.get("value")
        if operator_code == "is_null":
            return self._condition_result(condition, item, left_raw is None, right_value=None)
        if operator_code == "is_not_null":
            return self._condition_result(condition, item, left_raw is not None, right_value=None)
        if operator_code not in self._OPERATORS:
            return self._condition_error("atomic_condition_operator_invalid", f"不支持的 operator: {operator_code}")
        if left_raw is None:
            return self._condition_result(condition, item, False, right_value=None, left_value=None)

        try:
            left_value = self._decimal_value(left_raw)
            right_value = self._right_value(condition, feature_values)
        except ValueError as exc:
            return self._condition_error("atomic_condition_value_invalid", str(exc))
        if right_value is None:
            return self._condition_result(condition, item, False, right_value=None, left_value=left_value)

        result = self._OPERATORS[operator_code](left_value, right_value)
        return self._condition_result(condition, item, result, right_value=right_value, left_value=left_value)

    def _right_value(self, condition: Mapping[str, Any], feature_values: Mapping[str, Any]) -> Decimal | None:
        right_code = condition.get("right_feature_code")
        if isinstance(right_code, str) and right_code:
            right_item = feature_values.get(right_code)
            if not isinstance(right_item, Mapping):
                raise ValueError(f"缺少右侧特征 {right_code}")
            raw = right_item.get("value")
            if raw is None:
                return None
            right = self._decimal_value(raw)
            multiplier = self._decimal_param(condition.get("right_multiplier", "1"), field_name="right_multiplier")
            return right * multiplier
        if "value" in condition:
            return self._decimal_param(condition.get("value"), field_name="value")
        raise ValueError("condition 缺少 value 或 right_feature_code")

    def _json_value(self, params: Mapping[str, Any], matched: bool, feature_values: Mapping[str, Any]) -> dict[str, Any]:
        payload = params.get("json_payload", {})
        if not isinstance(payload, Mapping):
            payload = {}
        severity = str(payload.get("risk_severity") or "none")
        if matched:
            severity = str(params.get("base_severity") or severity or "elevated")
            high_conditions = params.get("severity_conditions", [])
            if isinstance(high_conditions, (list, tuple)) and high_conditions:
                severity_results = [self._evaluate_condition(condition, feature_values) for condition in high_conditions]
                if any(item.get("error_code") for item in severity_results):
                    severity = str(params.get("base_severity") or "elevated")
                elif any(item.get("result") for item in severity_results):
                    severity = str(params.get("high_severity") or "high")
        result = {
            **dict(payload),
            "condition_met": matched,
            "risk_severity": severity,
        }
        included_features = self._included_feature_values(params=params, feature_values=feature_values)
        if included_features:
            result["feature_values"] = included_features
        return result

    def _included_feature_values(self, *, params: Mapping[str, Any], feature_values: Mapping[str, Any]) -> dict[str, Any]:
        include_feature_values = params.get("include_feature_values")
        if not isinstance(include_feature_values, (list, tuple)):
            return {}
        result: dict[str, Any] = {}
        for raw_code in include_feature_values:
            code = str(raw_code).strip()
            if not code or code in result:
                continue
            item = feature_values.get(code)
            if not isinstance(item, Mapping):
                continue
            result[code] = {
                "feature_value_id": item.get("feature_value_id"),
                "value": self._json_scalar(item.get("value")),
                "value_type": item.get("value_type"),
            }
        return result

    @staticmethod
    def _json_scalar(value: Any) -> Any:
        if isinstance(value, Decimal):
            return str(value)
        return value

    def _evidence_item(
        self,
        *,
        signal_code: str,
        params: Mapping[str, Any],
        matched: bool,
        condition_results: list[dict[str, Any]],
    ) -> dict[str, Any]:
        return {
            "evidence_type": str(params.get("evidence_type") or "atomic_condition"),
            "signal_code": signal_code,
            "condition_result": matched,
            "aggregation": str(params.get("aggregation", "all")),
            "used_features": [
                {
                    "feature_code": item["feature_code"],
                    "feature_value_id": item.get("feature_value_id"),
                    "observed_value": item.get("observed_value"),
                }
                for item in condition_results
            ],
            "conditions": condition_results,
            "calculation_summary": self._calculation_summary(condition_results, str(params.get("aggregation", "all"))),
        }

    def _evidence_text(
        self,
        *,
        params: Mapping[str, Any],
        matched: bool,
        condition_results: list[dict[str, Any]],
    ) -> str:
        label = str(params.get("label_zh") or "原子条件")
        fact_text = "；".join(item["fact_text"] for item in condition_results)
        result_text = "成立" if matched else "不成立"
        return f"{fact_text}，因此“{label}”{result_text}。"

    def _condition_result(
        self,
        condition: Mapping[str, Any],
        item: Mapping[str, Any],
        result: bool,
        *,
        right_value: Decimal | None,
        left_value: Decimal | None | object = ...,
    ) -> dict[str, Any]:
        feature_code = str(condition["feature_code"])
        operator_code = str(condition["operator"])
        observed = item.get("value") if left_value is ... else left_value
        if isinstance(observed, Decimal):
            observed_text = str(observed)
        elif observed is None:
            observed_text = None
        else:
            observed_text = str(observed)
        right_text = str(right_value) if right_value is not None else None
        fact_text = self._condition_fact_text(feature_code, observed_text, operator_code, right_text, result)
        return {
            "feature_code": feature_code,
            "feature_value_id": item.get("feature_value_id"),
            "observed_value": observed_text,
            "operator": operator_code,
            "right_feature_code": condition.get("right_feature_code") or "",
            "right_value": right_text,
            "result": result,
            "fact_text": fact_text,
        }

    def _condition_fact_text(
        self,
        feature_code: str,
        observed_text: str | None,
        operator_code: str,
        right_text: str | None,
        result: bool,
    ) -> str:
        operator_text = self._OPERATOR_TEXT.get(operator_code, operator_code)
        result_text = "满足" if result else "未满足"
        if operator_code in {"is_null", "is_not_null"}:
            return f"{feature_code} 当前值为 {observed_text}，{result_text}“{operator_text}”条件"
        return f"{feature_code} 当前值为 {observed_text}，{result_text}“{operator_text} {right_text}”条件"

    @staticmethod
    def _calculation_summary(condition_results: list[dict[str, Any]], aggregation: str) -> str:
        joiner = " AND " if aggregation == "all" else " OR "
        parts = []
        for item in condition_results:
            operator_code = item["operator"]
            if operator_code in {"is_null", "is_not_null"}:
                parts.append(f"{item['feature_code']} {operator_code}")
            else:
                right = item["right_feature_code"] or item["right_value"]
                parts.append(f"{item['feature_code']} {operator_code} {right}")
        return joiner.join(parts)

    @staticmethod
    def _condition_error(error_code: str, error_message: str) -> dict[str, Any]:
        return {"error_code": error_code, "error_message": error_message}

    @classmethod
    def _failed(cls, error_code: str, error_message: str) -> CalculatorOutput:
        return CalculatorOutput.failed(
            output_schema_version=cls.metadata.output_schema_version,
            error_code=error_code,
            error_message=error_message,
        )

    @staticmethod
    def _decimal_param(value: Any, *, field_name: str) -> Decimal:
        if isinstance(value, bool) or value is None:
            raise ValueError(f"{field_name} 不是合法 Decimal")
        try:
            result = Decimal(str(value))
        except (InvalidOperation, ValueError) as exc:
            raise ValueError(f"{field_name} 不是合法 Decimal") from exc
        if not result.is_finite():
            raise ValueError(f"{field_name} 必须是有限 Decimal")
        return result

    @classmethod
    def _decimal_value(cls, value: Any) -> Decimal:
        return cls._decimal_param(value, field_name="feature_value")
