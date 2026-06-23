"""StrategyCalculator 模块：提供 calculator 注册与精确解析；不读写数据库，不访问外部服务，不涉及交易执行。"""

from __future__ import annotations

from dataclasses import dataclass, field

from .contracts import CalculatorMetadata, CalculatorProtocol, CalculatorType
from .errors import CalculatorNotFoundError, CalculatorTypeMismatchError, DuplicateCalculatorError, InvalidCalculatorContractError


@dataclass
class CalculatorRegistry:
    _calculators: dict[tuple[str, str], CalculatorProtocol] = field(default_factory=dict)
    _sealed: bool = False

    def register(self, calculator: CalculatorProtocol) -> None:
        if self._sealed:
            raise InvalidCalculatorContractError("CalculatorRegistry 已进入只读状态")
        metadata = self._validate_metadata(calculator)
        key = metadata.identity
        if key in self._calculators:
            raise DuplicateCalculatorError(f"calculator 重复注册：{metadata.algorithm_name} {metadata.algorithm_version}")
        self._calculators[key] = calculator

    def resolve(self, *, calculator_type: CalculatorType, algorithm_name: str, algorithm_version: str) -> CalculatorProtocol:
        self.seal()
        key = (algorithm_name, algorithm_version)
        calculator = self._calculators.get(key)
        if calculator is None:
            raise CalculatorNotFoundError(f"未找到 calculator：{algorithm_name} {algorithm_version}")
        if calculator.metadata.calculator_type != calculator_type:
            raise CalculatorTypeMismatchError(
                f"calculator_type 不匹配：期望 {calculator_type}，实际 {calculator.metadata.calculator_type}"
            )
        return calculator

    def list_registered(self) -> tuple[CalculatorMetadata, ...]:
        self.seal()
        return tuple(calculator.metadata for calculator in self._calculators.values())

    def validate_unique(self) -> None:
        self.seal()
        if len(self._calculators) != len(set(self._calculators)):
            raise DuplicateCalculatorError("CalculatorRegistry 存在重复算法身份")

    def seal(self) -> None:
        self._sealed = True

    def validate_required_algorithms(self, required: list[tuple[CalculatorType, str, str]]) -> None:
        for calculator_type, algorithm_name, algorithm_version in required:
            self.resolve(
                calculator_type=calculator_type,
                algorithm_name=algorithm_name,
                algorithm_version=algorithm_version,
            )

    @staticmethod
    def _validate_metadata(calculator: CalculatorProtocol) -> CalculatorMetadata:
        metadata = getattr(calculator, "metadata", None)
        if not isinstance(metadata, CalculatorMetadata):
            raise InvalidCalculatorContractError("calculator 必须声明 CalculatorMetadata")
        if not metadata.deterministic:
            raise InvalidCalculatorContractError("正式 calculator metadata 必须声明 deterministic=true")
        calculate = getattr(calculator, "calculate", None)
        if not callable(calculate):
            raise InvalidCalculatorContractError("calculator 必须提供 calculate 方法")
        return metadata


default_registry = CalculatorRegistry()
