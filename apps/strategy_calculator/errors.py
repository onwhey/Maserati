"""StrategyCalculator 模块：定义纯计算框架异常；不读写数据库，不访问外部服务，不涉及交易执行。"""

from __future__ import annotations


class StrategyCalculatorError(Exception):
    """StrategyCalculator 基础异常。"""


class InvalidCalculatorContractError(StrategyCalculatorError):
    """Calculator 输入、输出或 metadata 不满足合同。"""


class DuplicateCalculatorError(StrategyCalculatorError):
    """相同 algorithm_name + algorithm_version 被重复注册。"""


class CalculatorNotFoundError(StrategyCalculatorError):
    """无法按精确 algorithm_name + algorithm_version 解析 calculator。"""


class CalculatorTypeMismatchError(StrategyCalculatorError):
    """解析到的 calculator_type 与业务模块要求不一致。"""

