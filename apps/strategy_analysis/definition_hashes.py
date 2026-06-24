"""StrategyAnalysis 模块：规范化定义并计算稳定指纹；不读写数据库、Redis 或外部服务，不涉及交易执行。"""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable, Mapping

from apps.strategy_calculator.utils import stable_hash


FORMAL_DOMAIN_CODES = frozenset({"trend", "momentum", "volatility"})
STRATEGY_ROUTE_CONDITION_SCHEMA_VERSION = "1.0"


def _normalize_ratio_text(value: Any) -> str:
    if value is None:
        return ""
    try:
        ratio = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("ratio is not a valid Decimal") from exc
    if not ratio.is_finite():
        raise ValueError("ratio must be finite")
    return format(ratio.normalize(), "f")


def _normalize_required_decimal_text(value: Any, *, field_name: str) -> str:
    if value is None:
        raise ValueError(f"{field_name} 不能为空")
    text = _normalize_ratio_text(value)
    if not text:
        raise ValueError(f"{field_name} 不能为空")
    return text


def _required_text(value: Any, *, field_name: str) -> str:
    text = str(value).strip() if value is not None else ""
    if not text:
        raise ValueError(f"{field_name} 不能为空")
    return text


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


def normalize_atomic_signal_codes(values: Iterable[Any], *, allow_empty: bool = False) -> tuple[str, ...]:
    codes = tuple(sorted({str(value).strip() for value in values if str(value).strip()}))
    if not codes and not allow_empty:
        raise ValueError("领域定义必须声明至少一个原子信号依赖")
    return codes


def domain_signal_definition_hash(
    *,
    domain_code: str,
    output_mode: str,
    algorithm_name: str,
    algorithm_version: str,
    params_hash: str,
    is_required: bool,
    allowed_atomic_signal_codes: Iterable[Any],
    required_atomic_signal_codes: Iterable[Any],
    minimum_coverage_ratio: Any,
    agreement_threshold: Any,
) -> str:
    return stable_hash(
        {
            "domain_code": domain_code,
            "output_mode": output_mode,
            "algorithm_name": algorithm_name,
            "algorithm_version": algorithm_version,
            "params_hash": params_hash,
            "is_required": is_required,
            "allowed_atomic_signal_codes": list(normalize_atomic_signal_codes(allowed_atomic_signal_codes)),
            "required_atomic_signal_codes": list(normalize_atomic_signal_codes(required_atomic_signal_codes)),
            "minimum_coverage_ratio": _normalize_ratio_text(minimum_coverage_ratio),
            "agreement_threshold": _normalize_ratio_text(agreement_threshold),
        }
    )


def _normalize_unique_codes(
    values: Iterable[Any],
    *,
    empty_message: str,
    duplicate_message: str,
    invalid_message: str,
    allow_empty: bool = False,
) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)):
        raise ValueError(invalid_message)
    codes: list[str] = []
    for value in values:
        if value is None or not str(value).strip():
            raise ValueError(invalid_message)
        codes.append(str(value).strip())
    if len(codes) != len(set(codes)):
        raise ValueError(duplicate_message)
    normalized = tuple(sorted(codes))
    if not normalized and not allow_empty:
        raise ValueError(empty_message)
    return normalized


def normalize_domain_codes(values: Iterable[Any], *, allow_empty: bool = False) -> tuple[str, ...]:
    codes = _normalize_unique_codes(
        values,
        empty_message="市场环境定义必须声明至少一个领域依赖",
        duplicate_message="市场环境定义不得包含重复领域代码",
        invalid_message="市场环境定义不得包含空领域代码",
        allow_empty=allow_empty,
    )
    unsupported = sorted(set(codes) - FORMAL_DOMAIN_CODES)
    if unsupported:
        raise ValueError(f"市场环境定义包含非正式领域代码：{','.join(unsupported)}")
    return codes


def normalize_regime_codes(values: Iterable[Any]) -> tuple[str, ...]:
    return _normalize_unique_codes(
        values,
        empty_message="市场环境定义必须声明至少一个允许输出的环境代码",
        duplicate_message="市场环境定义不得包含重复环境代码",
        invalid_message="市场环境定义不得包含空环境代码",
    )


def market_regime_domain_membership_hash(payload_summary: dict[str, Any]) -> str:
    allowed = normalize_domain_codes(payload_summary.get("allowed_domain_codes", []))
    required = normalize_domain_codes(payload_summary.get("required_domain_codes", []), allow_empty=True)
    return stable_hash(
        {
            "allowed_domain_codes": list(allowed),
            "required_domain_codes": list(required),
        }
    )


def market_regime_definition_hash(
    *,
    definition_code: str,
    algorithm_name: str,
    algorithm_version: str,
    input_schema_version: str,
    output_schema_version: str,
    params_hash: str,
    allowed_domain_codes: Iterable[Any],
    required_domain_codes: Iterable[Any],
    allowed_regime_codes: Iterable[Any],
) -> str:
    return stable_hash(
        {
            "definition_code": definition_code,
            "algorithm_name": algorithm_name,
            "algorithm_version": algorithm_version,
            "input_schema_version": input_schema_version,
            "output_schema_version": output_schema_version,
            "params_hash": params_hash,
            "allowed_domain_codes": list(normalize_domain_codes(allowed_domain_codes)),
            "required_domain_codes": list(normalize_domain_codes(required_domain_codes, allow_empty=True)),
            "allowed_regime_codes": list(normalize_regime_codes(allowed_regime_codes)),
        }
    )


def normalize_strategy_weights(
    values: Mapping[str, Any],
    *,
    allowed_domain_codes: Iterable[Any],
    uses_input_weights: bool,
) -> dict[str, str]:
    if not isinstance(values, Mapping):
        raise ValueError("domain_input_weights 必须是映射")
    allowed = set(normalize_domain_codes(allowed_domain_codes))
    if any(not isinstance(code, str) or not code.strip() for code in values):
        raise ValueError("domain_input_weights 的领域代码必须是非空字符串")
    if not uses_input_weights:
        if values:
            raise ValueError("未启用输入权重时 domain_input_weights 必须为空")
        return {}
    if set(values) != allowed:
        raise ValueError("启用输入权重时必须完整覆盖 allowed_domain_codes")
    normalized: dict[str, str] = {}
    for code, value in values.items():
        text = _normalize_required_decimal_text(value, field_name=f"domain_input_weights.{code}")
        if Decimal(text) < 0:
            raise ValueError("domain_input_weights 不得为负数")
        normalized[str(code)] = text
    return {code: normalized[code] for code in sorted(normalized)}


def strategy_definition_dependency_hash(payload_summary: dict[str, Any]) -> str:
    allowed = normalize_domain_codes(payload_summary.get("allowed_domain_codes", []))
    required = normalize_domain_codes(payload_summary.get("required_domain_codes", []), allow_empty=True)
    return stable_hash(
        {
            "allowed_domain_codes": list(allowed),
            "required_domain_codes": list(required),
        }
    )


def strategy_definition_hash(
    *,
    strategy_code: str,
    strategy_version: str,
    algorithm_name: str,
    algorithm_version: str,
    input_schema_version: str,
    output_schema_version: str,
    params_hash: str,
    allowed_domain_codes: Iterable[Any],
    required_domain_codes: Iterable[Any],
    uses_input_weights: bool,
    domain_input_weights: Mapping[str, Any],
    prediction_horizon: str,
) -> str:
    allowed = normalize_domain_codes(allowed_domain_codes)
    required = normalize_domain_codes(required_domain_codes, allow_empty=True)
    weights = normalize_strategy_weights(
        domain_input_weights,
        allowed_domain_codes=allowed,
        uses_input_weights=uses_input_weights,
    )
    if not set(required).issubset(set(allowed)):
        raise ValueError("策略 required_domain_codes 必须属于 allowed_domain_codes")
    if not str(prediction_horizon).strip():
        raise ValueError("prediction_horizon 不能为空")
    identity = {
        "strategy_code": _required_text(strategy_code, field_name="strategy_code"),
        "strategy_version": _required_text(strategy_version, field_name="strategy_version"),
        "algorithm_name": _required_text(algorithm_name, field_name="algorithm_name"),
        "algorithm_version": _required_text(algorithm_version, field_name="algorithm_version"),
        "input_schema_version": _required_text(input_schema_version, field_name="input_schema_version"),
        "output_schema_version": _required_text(output_schema_version, field_name="output_schema_version"),
    }
    return stable_hash(
        {
            **identity,
            "params_hash": params_hash,
            "allowed_domain_codes": list(allowed),
            "required_domain_codes": list(required),
            "uses_input_weights": bool(uses_input_weights),
            "domain_input_weights": weights,
            "prediction_horizon": str(prediction_horizon).strip(),
        }
    )


ROUTE_CONDITION_FIELDS = frozenset(
    {
        "regime_codes",
        "minimum_regime_confidence",
        "minimum_classification_margin",
        "regime_score_thresholds",
    }
)


def normalize_route_conditions(
    conditions: Mapping[str, Any],
    *,
    allowed_regime_codes: Iterable[Any],
) -> dict[str, Any]:
    if not isinstance(conditions, Mapping):
        raise ValueError("match_conditions 必须是映射")
    if any(not isinstance(field, str) or not field.strip() for field in conditions):
        raise ValueError("match_conditions 字段名必须是非空字符串")
    unknown = sorted(set(conditions) - ROUTE_CONDITION_FIELDS)
    if unknown:
        raise ValueError(f"match_conditions 包含未知字段：{','.join(unknown)}")
    allowed = set(normalize_regime_codes(allowed_regime_codes))
    normalized: dict[str, Any] = {}
    if "regime_codes" in conditions:
        codes = normalize_regime_codes(conditions["regime_codes"])
        if not set(codes).issubset(allowed):
            raise ValueError("regime_codes 包含未登记环境代码")
        normalized["regime_codes"] = list(codes)
    if "minimum_regime_confidence" in conditions:
        confidence = Decimal(
            _normalize_required_decimal_text(
                conditions["minimum_regime_confidence"],
                field_name="minimum_regime_confidence",
            )
        )
        if confidence < 0 or confidence > 1:
            raise ValueError("minimum_regime_confidence 必须位于 0 到 1")
        normalized["minimum_regime_confidence"] = format(confidence.normalize(), "f")
    if "minimum_classification_margin" in conditions:
        normalized["minimum_classification_margin"] = _normalize_required_decimal_text(
            conditions["minimum_classification_margin"],
            field_name="minimum_classification_margin",
        )
    if "regime_score_thresholds" in conditions:
        thresholds = conditions["regime_score_thresholds"]
        if not isinstance(thresholds, Mapping):
            raise ValueError("regime_score_thresholds 必须是映射")
        if any(not isinstance(code, str) or not code.strip() for code in thresholds):
            raise ValueError("regime_score_thresholds 环境代码必须是非空字符串")
        unknown_codes = sorted(set(thresholds) - allowed)
        if unknown_codes:
            raise ValueError("regime_score_thresholds 包含未登记环境代码")
        normalized["regime_score_thresholds"] = {
            str(code): _normalize_required_decimal_text(
                thresholds[code],
                field_name=f"regime_score_thresholds.{code}",
            )
            for code in sorted(thresholds)
        }
    return normalized


def _normalize_utc_datetime(value: datetime | None, *, field_name: str) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError(f"{field_name} 必须是 UTC 时间")
    return value.isoformat()


def strategy_route_rule_hash(
    *,
    policy_id: int,
    rule_code: str,
    priority: int,
    action: str,
    match_conditions: Mapping[str, Any],
    selected_strategy_definition_id: int | None,
    valid_from_utc: datetime | None,
    valid_to_utc: datetime | None,
    allowed_regime_codes: Iterable[Any],
) -> str:
    if int(priority) < 0:
        raise ValueError("priority 不得为负数")
    normalized_rule_code = _required_text(rule_code, field_name="rule_code")
    if action not in {"select_strategy", "no_strategy"}:
        raise ValueError("StrategyRouteRule action 非法")
    if action == "select_strategy" and selected_strategy_definition_id is None:
        raise ValueError("select_strategy Rule 必须绑定 StrategyDefinition")
    if action == "no_strategy" and selected_strategy_definition_id is not None:
        raise ValueError("no_strategy Rule 不得绑定 StrategyDefinition")
    valid_from = _normalize_utc_datetime(valid_from_utc, field_name="valid_from_utc")
    valid_to = _normalize_utc_datetime(valid_to_utc, field_name="valid_to_utc")
    if valid_from_utc is not None and valid_to_utc is not None and valid_from_utc >= valid_to_utc:
        raise ValueError("RouteRule 有效窗口非法")
    normalized_conditions = normalize_route_conditions(
        match_conditions,
        allowed_regime_codes=allowed_regime_codes,
    )
    return stable_hash(
        {
            "policy_id": int(policy_id),
            "rule_code": normalized_rule_code,
            "priority": int(priority),
            "action": action,
            "match_conditions": normalized_conditions,
            "selected_strategy_definition_id": selected_strategy_definition_id,
            "valid_from_utc": valid_from,
            "valid_to_utc": valid_to,
        }
    )


def strategy_route_rule_set_hash(rule_payloads: Iterable[Mapping[str, Any]]) -> str:
    normalized = sorted(
        (
            {
                "rule_id": int(item["rule_id"]),
                "rule_code": str(item["rule_code"]),
                "priority": int(item["priority"]),
                "rule_hash": str(item["rule_hash"]),
            }
            for item in rule_payloads
        ),
        key=lambda item: (item["priority"], item["rule_code"], item["rule_id"]),
    )
    if not normalized:
        raise ValueError("StrategyRoutePolicy 必须包含至少一条 Rule")
    return stable_hash(normalized)


def strategy_route_policy_hash(
    *,
    policy_code: str,
    policy_version: str,
    condition_schema_version: str,
    rule_set_hash: str,
    fallback_policy: str,
    fallback_strategy_definition_id: int | None,
) -> str:
    normalized_policy_code = _required_text(policy_code, field_name="policy_code")
    normalized_policy_version = _required_text(policy_version, field_name="policy_version")
    normalized_condition_schema = _required_text(
        condition_schema_version,
        field_name="condition_schema_version",
    )
    if fallback_policy not in {"none", "explicit"}:
        raise ValueError("fallback_policy 非法")
    if fallback_policy == "none" and fallback_strategy_definition_id is not None:
        raise ValueError("fallback_policy=none 时不得绑定 fallback StrategyDefinition")
    if fallback_policy == "explicit" and fallback_strategy_definition_id is None:
        raise ValueError("fallback_policy=explicit 时必须绑定 fallback StrategyDefinition")
    return stable_hash(
        {
            "policy_code": normalized_policy_code,
            "policy_version": normalized_policy_version,
            "condition_schema_version": normalized_condition_schema,
            "rule_set_hash": rule_set_hash,
            "fallback_policy": fallback_policy,
            "fallback_strategy_definition_id": fallback_strategy_definition_id,
        }
    )


def strategy_signal_quality_rule_set_hash(
    *,
    rule_set_code: str,
    rule_set_version: str,
    quality_schema_version: str,
    max_staleness_seconds: int,
    warning_blocks_decision: bool,
    fail_alert_enabled: bool,
    warning_alert_enabled: bool,
    consecutive_failure_threshold: int,
    params_hash: str,
) -> str:
    if int(max_staleness_seconds) < 0:
        raise ValueError("max_staleness_seconds 不得为负数")
    if int(consecutive_failure_threshold) < 0:
        raise ValueError("consecutive_failure_threshold 不得为负数")
    return stable_hash(
        {
            "rule_set_code": _required_text(rule_set_code, field_name="rule_set_code"),
            "rule_set_version": _required_text(rule_set_version, field_name="rule_set_version"),
            "quality_schema_version": _required_text(quality_schema_version, field_name="quality_schema_version"),
            "max_staleness_seconds": int(max_staleness_seconds),
            "warning_blocks_decision": bool(warning_blocks_decision),
            "fail_alert_enabled": bool(fail_alert_enabled),
            "warning_alert_enabled": bool(warning_alert_enabled),
            "consecutive_failure_threshold": int(consecutive_failure_threshold),
            "params_hash": _required_text(params_hash, field_name="params_hash"),
        }
    )


def decision_policy_definition_hash(
    *,
    policy_code: str,
    policy_version: str,
    algorithm_name: str,
    algorithm_version: str,
    input_schema_version: str,
    output_schema_version: str,
    target_schema_version: str,
    params_hash: str,
) -> str:
    return stable_hash(
        {
            "policy_code": _required_text(policy_code, field_name="policy_code"),
            "policy_version": _required_text(policy_version, field_name="policy_version"),
            "algorithm_name": _required_text(algorithm_name, field_name="algorithm_name"),
            "algorithm_version": _required_text(algorithm_version, field_name="algorithm_version"),
            "input_schema_version": _required_text(input_schema_version, field_name="input_schema_version"),
            "output_schema_version": _required_text(output_schema_version, field_name="output_schema_version"),
            "target_schema_version": _required_text(target_schema_version, field_name="target_schema_version"),
            "params_hash": _required_text(params_hash, field_name="params_hash"),
        }
    )
