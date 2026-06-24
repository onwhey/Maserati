"""DomainSignal 模块：把单个有效原子信号映射为领域事实。

负责：纯计算 DomainSignalValue 所需方向、状态、强度、覆盖率和证据。
不负责：读取数据库、访问 Redis、访问外部服务、发送 Hermes、调用大模型、交易执行、真实交易。
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any, Mapping

from ..contracts import CalculatorInput, CalculatorMetadata, CalculatorOutput, CalculatorType


class SingleAtomicPassthroughCalculator:
    metadata = CalculatorMetadata(
        algorithm_name="single_atomic_passthrough",
        algorithm_version="1.0.0",
        calculator_type=CalculatorType.DOMAIN_SIGNAL,
        input_schema_version="1.0",
        output_schema_version="1.0",
        deterministic=True,
        supports_dry_run=True,
        algorithm_requirement_document_path="docs/requirements/domain_signals.md",
        implementation_document_path="docs/implementation/domain_signal/single_atomic_passthrough__1.0.0.md",
    )

    def calculate(self, calculation_input: CalculatorInput) -> CalculatorOutput:
        values = dict(calculation_input.values)
        params = dict(calculation_input.frozen_params)
        atomic_values = values.get("atomic_values")
        domain_code = values.get("domain_code")
        output_mode = values.get("output_mode")
        if not isinstance(domain_code, str) or not isinstance(output_mode, str):
            return self._failed("domain_context_missing", "缺少领域代码或输出模式")
        if not isinstance(atomic_values, tuple | list) or len(atomic_values) != 1:
            return self._failed("single_atomic_input_required", "single_atomic_passthrough 只允许一个有效原子输入")
        atomic_value = atomic_values[0]
        if not isinstance(atomic_value, Mapping):
            return self._failed("atomic_value_invalid", "原子输入必须是结构化映射")
        if atomic_value.get("is_valid") is not True:
            return self._failed("atomic_value_not_valid", "原子输入不是有效结果")

        direction = str(atomic_value.get("direction", "neutral"))
        if direction not in {"bullish", "bearish", "neutral", "none"}:
            return self._failed("atomic_direction_invalid", "原子方向不合法")
        try:
            strength = self._decimal_ratio(atomic_value.get("strength"))
        except ValueError:
            return self._failed("atomic_strength_invalid", "原子强度不合法")
        signal_code = str(atomic_value.get("signal_code", ""))
        signal_value_id = atomic_value.get("atomic_signal_value_id")

        state_code = ""
        if output_mode == "directional":
            if direction == "none":
                direction = "neutral"
        elif output_mode == "state":
            state_code = self._state_code(params=params, direction=direction, strength=strength)
            direction = "none"
        else:
            return self._failed("domain_output_mode_invalid", "领域输出模式不受支持")

        evidence = {
            "domain_code": domain_code,
            "output_mode": output_mode,
            "source_signal_code": signal_code,
            "source_atomic_signal_value_id": signal_value_id,
            "source_direction": atomic_value.get("direction"),
            "source_strength": str(strength),
        }
        evidence_text = f"{domain_code} 领域采用单个原子信号 {signal_code} 形成领域事实。"
        return CalculatorOutput.succeeded(
            output_schema_version=self.metadata.output_schema_version,
            values={
                "direction": direction,
                "state_code": state_code,
                "strength": strength,
                "coverage_ratio": Decimal("1"),
                "agreement_ratio": None,
                "evidence_text_zh": evidence_text,
            },
            evidence_items=(evidence,),
            calculation_summary={"source_signal_count": 1},
        )

    @classmethod
    def _failed(cls, error_code: str, error_message: str) -> CalculatorOutput:
        return CalculatorOutput.failed(
            output_schema_version=cls.metadata.output_schema_version,
            error_code=error_code,
            error_message=error_message,
        )

    @staticmethod
    def _decimal_ratio(value: Any) -> Decimal:
        try:
            result = Decimal(str(value))
        except (InvalidOperation, ValueError) as exc:
            raise ValueError("invalid_decimal") from exc
        if not result.is_finite() or result < 0 or result > 1:
            raise ValueError("invalid_ratio")
        return result

    @staticmethod
    def _state_code(*, params: Mapping[str, Any], direction: str, strength: Decimal) -> str:
        if direction in {"bullish", "bearish"} and strength > 0:
            return str(params.get("state_code_when_active", direction))
        return str(params.get("state_code_when_inactive", "neutral"))
