"""StrategyAnalysis 模块：规范化定义并计算稳定指纹；不读写数据库、Redis 或外部服务，不涉及交易执行。"""

from __future__ import annotations

from typing import Any, Iterable

from apps.strategy_calculator.utils import stable_hash


def normalize_feature_codes(values: Iterable[Any]) -> tuple[str, ...]:
    codes = tuple(sorted({str(value).strip() for value in values if str(value).strip()}))
    if not codes:
        raise ValueError("原子信号必须声明至少一个特征依赖")
    return codes


def atomic_signal_definition_hash(
    *,
    signal_code: str,
    default_direction: str,
    algorithm_name: str,
    algorithm_version: str,
    params_hash: str,
    is_required: bool,
    depends_on_feature_codes: Iterable[Any],
    output_type: str,
) -> str:
    return stable_hash(
        {
            "signal_code": signal_code,
            "default_direction": default_direction,
            "algorithm_name": algorithm_name,
            "algorithm_version": algorithm_version,
            "params_hash": params_hash,
            "is_required": is_required,
            "depends_on_feature_codes": list(normalize_feature_codes(depends_on_feature_codes)),
            "output_type": output_type,
        }
    )


def atomic_signal_dependency_hash(depends_on_feature_codes: Iterable[Any]) -> str:
    return stable_hash({"depends_on_feature_codes": list(normalize_feature_codes(depends_on_feature_codes))})


def domain_atomic_membership_hash(payload_summary: dict[str, Any]) -> str:
    allowed = sorted({str(code) for code in payload_summary.get("allowed_atomic_signal_codes", [])})
    required = sorted({str(code) for code in payload_summary.get("required_atomic_signal_codes", [])})
    return stable_hash(
        {
            "allowed_atomic_signal_codes": allowed,
            "required_atomic_signal_codes": required,
        }
    )
