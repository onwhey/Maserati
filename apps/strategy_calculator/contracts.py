"""StrategyCalculator 模块：定义纯计算 DTO 合同；不读写数据库，不访问 Redis，不访问外部服务，不涉及交易执行。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any, Mapping, Protocol

from .errors import InvalidCalculatorContractError
from .utils import contains_invalid_number, freeze_value, stable_hash, thaw_value, validate_pure_data


class CalculatorType(StrEnum):
    FEATURE_LAYER = "feature_layer"
    ATOMIC_SIGNAL = "atomic_signal"
    DOMAIN_SIGNAL = "domain_signal"
    MARKET_REGIME = "market_regime"
    STRATEGY_SIGNAL = "strategy_signal"
    DECISION_POLICY = "decision_policy"


class CalculationStatus(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"


@dataclass(frozen=True)
class CalculatorMetadata:
    algorithm_name: str
    algorithm_version: str
    calculator_type: CalculatorType
    input_schema_version: str
    output_schema_version: str
    deterministic: bool
    supports_dry_run: bool
    algorithm_requirement_document_path: str
    implementation_document_path: str
    uses_input_weights: bool = False

    def __post_init__(self) -> None:
        required = {
            "algorithm_name": self.algorithm_name,
            "algorithm_version": self.algorithm_version,
            "input_schema_version": self.input_schema_version,
            "output_schema_version": self.output_schema_version,
            "algorithm_requirement_document_path": self.algorithm_requirement_document_path,
            "implementation_document_path": self.implementation_document_path,
        }
        missing = [key for key, value in required.items() if not value]
        if missing:
            raise InvalidCalculatorContractError(f"calculator metadata 缺少必要字段：{','.join(missing)}")
        if self.calculator_type not in set(CalculatorType):
            raise InvalidCalculatorContractError("不支持的 calculator_type")

    @property
    def identity(self) -> tuple[str, str]:
        return self.algorithm_name, self.algorithm_version


@dataclass(frozen=True)
class CalculatorInput:
    calculator_type: CalculatorType
    input_schema_version: str
    output_schema_version: str
    upstream_refs: Mapping[str, Any] = field(default_factory=dict)
    business_time_utc: datetime | None = None
    market_identity: Mapping[str, Any] = field(default_factory=dict)
    frozen_params: Mapping[str, Any] = field(default_factory=dict)
    params_hash: str = ""
    values: Mapping[str, Any] = field(default_factory=dict)
    evidence_summary: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        mapping_fields = {
            "upstream_refs": self.upstream_refs,
            "market_identity": self.market_identity,
            "frozen_params": self.frozen_params,
            "values": self.values,
            "evidence_summary": self.evidence_summary,
        }
        invalid_mappings = [name for name, value in mapping_fields.items() if not isinstance(value, Mapping)]
        if invalid_mappings:
            raise InvalidCalculatorContractError(f"CalculatorInput 字段必须是映射：{','.join(invalid_mappings)}")
        if self.calculator_type not in set(CalculatorType):
            raise InvalidCalculatorContractError("不支持的 calculator_type")
        if self.business_time_utc is not None and (
            self.business_time_utc.tzinfo is None or self.business_time_utc.utcoffset() != timedelta(0)
        ):
            raise InvalidCalculatorContractError("business_time_utc 必须是 UTC 时间")
        validate_pure_data(self.upstream_refs, path="CalculatorInput.upstream_refs")
        validate_pure_data(self.market_identity, path="CalculatorInput.market_identity")
        validate_pure_data(self.frozen_params, path="CalculatorInput.frozen_params")
        validate_pure_data(self.values, path="CalculatorInput.values")
        validate_pure_data(self.evidence_summary, path="CalculatorInput.evidence_summary")
        frozen_params = freeze_value(self.frozen_params)
        object.__setattr__(self, "upstream_refs", freeze_value(self.upstream_refs))
        object.__setattr__(self, "market_identity", freeze_value(self.market_identity))
        object.__setattr__(self, "frozen_params", frozen_params)
        object.__setattr__(self, "values", freeze_value(self.values))
        object.__setattr__(self, "evidence_summary", freeze_value(self.evidence_summary))
        actual_params_hash = stable_hash(thaw_value(frozen_params))
        if self.params_hash and self.params_hash != actual_params_hash:
            raise InvalidCalculatorContractError("CalculatorInput.params_hash 与冻结参数不一致")
        object.__setattr__(self, "params_hash", actual_params_hash)
        if any(
            contains_invalid_number(value)
            for value in (self.upstream_refs, self.market_identity, self.frozen_params, self.values, self.evidence_summary)
        ):
            raise InvalidCalculatorContractError("CalculatorInput 不允许 NaN 或 Infinity")


@dataclass(frozen=True)
class CalculatorOutput:
    calculation_status: CalculationStatus
    output_schema_version: str
    values: Mapping[str, Any] = field(default_factory=dict)
    evidence_items: tuple[Mapping[str, Any], ...] = field(default_factory=tuple)
    calculation_summary: Mapping[str, Any] = field(default_factory=dict)
    error_code: str = ""
    error_message: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.values, Mapping) or not isinstance(self.calculation_summary, Mapping):
            raise InvalidCalculatorContractError("CalculatorOutput.values 和 calculation_summary 必须是映射")
        if not isinstance(self.evidence_items, tuple) or any(not isinstance(item, Mapping) for item in self.evidence_items):
            raise InvalidCalculatorContractError("CalculatorOutput.evidence_items 必须是映射 tuple")
        if self.calculation_status not in set(CalculationStatus):
            raise InvalidCalculatorContractError("CalculatorOutput 只允许 succeeded / failed")
        if not self.output_schema_version:
            raise InvalidCalculatorContractError("CalculatorOutput 必须包含 output_schema_version")
        if self.calculation_status == CalculationStatus.FAILED and (not self.error_code or not self.error_message):
            raise InvalidCalculatorContractError("failed 输出必须包含 error_code 和 error_message")
        if self.calculation_status == CalculationStatus.SUCCEEDED and (self.error_code or self.error_message):
            raise InvalidCalculatorContractError("succeeded 输出不得携带错误字段")
        validate_pure_data(self.values, path="CalculatorOutput.values")
        validate_pure_data(self.evidence_items, path="CalculatorOutput.evidence_items")
        validate_pure_data(self.calculation_summary, path="CalculatorOutput.calculation_summary")
        object.__setattr__(self, "values", freeze_value(self.values))
        object.__setattr__(self, "evidence_items", tuple(freeze_value(item) for item in self.evidence_items))
        object.__setattr__(self, "calculation_summary", freeze_value(self.calculation_summary))
        if any(
            contains_invalid_number(value)
            for value in (self.values, self.evidence_items, self.calculation_summary)
        ):
            raise InvalidCalculatorContractError("CalculatorOutput 不允许 NaN 或 Infinity")

    @classmethod
    def succeeded(
        cls,
        *,
        output_schema_version: str,
        values: Mapping[str, Any],
        evidence_items: tuple[Mapping[str, Any], ...] = (),
        calculation_summary: Mapping[str, Any] | None = None,
    ) -> "CalculatorOutput":
        return cls(
            calculation_status=CalculationStatus.SUCCEEDED,
            output_schema_version=output_schema_version,
            values=values,
            evidence_items=evidence_items,
            calculation_summary=calculation_summary or {},
        )

    @classmethod
    def failed(
        cls,
        *,
        output_schema_version: str,
        error_code: str,
        error_message: str,
        calculation_summary: Mapping[str, Any] | None = None,
    ) -> "CalculatorOutput":
        return cls(
            calculation_status=CalculationStatus.FAILED,
            output_schema_version=output_schema_version,
            error_code=error_code,
            error_message=error_message,
            calculation_summary=calculation_summary or {},
        )


class CalculatorProtocol(Protocol):
    metadata: CalculatorMetadata

    def calculate(self, calculation_input: CalculatorInput) -> CalculatorOutput:
        ...
