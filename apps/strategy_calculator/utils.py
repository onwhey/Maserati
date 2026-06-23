"""StrategyCalculator 模块：提供确定性序列化和不可变 DTO 工具；不读写数据库，不访问外部服务，不涉及交易执行。"""

from __future__ import annotations

import json
import math
from datetime import datetime, timedelta
from decimal import Decimal
from hashlib import sha256
from types import MappingProxyType
from typing import Any, Mapping

from .errors import InvalidCalculatorContractError


def _json_default(value: Any) -> str:
    if isinstance(value, Decimal):
        return str(value)
    raise TypeError(f"无法序列化的值：{type(value)!r}")


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=_json_default)


def stable_hash(value: Any) -> str:
    return sha256(canonical_json(value).encode("utf-8")).hexdigest()


def validate_pure_data(value: Any, *, path: str = "value") -> None:
    """拒绝 ORM、client、service 等非纯数据对象，并统一检查嵌套 UTC 时间。"""

    if value is None or isinstance(value, str | bool | int | Decimal):
        return
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            raise InvalidCalculatorContractError(f"{path} 不允许 NaN 或 Infinity")
        return
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() != timedelta(0):
            raise InvalidCalculatorContractError(f"{path} 中的时间必须是 UTC")
        return
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str):
                raise InvalidCalculatorContractError(f"{path} 的键必须是字符串")
            validate_pure_data(item, path=f"{path}.{key}")
        return
    if isinstance(value, list | tuple | set | frozenset):
        for index, item in enumerate(value):
            validate_pure_data(item, path=f"{path}[{index}]")
        return
    raise InvalidCalculatorContractError(f"{path} 只允许纯数据，收到 {type(value).__name__}")


def freeze_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): freeze_value(item) for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))})
    if isinstance(value, list | tuple):
        return tuple(freeze_value(item) for item in value)
    if isinstance(value, set | frozenset):
        return tuple(sorted((freeze_value(item) for item in value), key=repr))
    return value


def thaw_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: thaw_value(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [thaw_value(item) for item in value]
    return value


def contains_invalid_number(value: Any) -> bool:
    if isinstance(value, Decimal):
        return value.is_nan() or value.is_infinite()
    if isinstance(value, float):
        return math.isnan(value) or math.isinf(value)
    if isinstance(value, Mapping):
        return any(contains_invalid_number(item) for item in value.values())
    if isinstance(value, list | tuple | set | frozenset):
        return any(contains_invalid_number(item) for item in value)
    return False
