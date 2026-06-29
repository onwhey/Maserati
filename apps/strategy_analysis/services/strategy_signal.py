"""StrategySignal 模块：执行 StrategyRouting 已选定的策略并生成标准化策略信号。

负责：校验冻结版本包、路由决定、策略定义和领域输入，调用精确 StrategySignal calculator，写 StrategySignal 与必要 AlertEvent。
不负责：重新路由、读取 MarketRegime 参与计算、生成目标仓位或订单；不访问 Redis、Binance、DeepSeek，不发送 Hermes，
不涉及交易执行或真实交易。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from time import perf_counter
from typing import Any

from django.conf import settings
from django.core.exceptions import ObjectDoesNotExist
from django.db import DataError, DatabaseError, IntegrityError, transaction
from django.utils import timezone

from apps.alerts.models import AlertSeverity
from apps.alerts.services import record_alert_event
from apps.foundation.idempotency import build_idempotency_key
from apps.foundation.results import ResultStatus, ServiceResult
from apps.strategy_calculator.contracts import CalculationStatus, CalculatorInput, CalculatorOutput, CalculatorType
from apps.strategy_calculator.errors import InvalidCalculatorContractError, StrategyCalculatorError
from apps.strategy_calculator.registry import CalculatorRegistry, default_registry
from apps.strategy_calculator.utils import stable_hash, thaw_value

from ..definition_hashes import (
    normalize_domain_codes,
    normalize_strategy_weights,
    strategy_definition_dependency_hash,
    strategy_definition_hash,
)
from ..models import (
    AnalysisObjectStatus,
    DefinitionLifecycleStatus,
    DomainSignalSet,
    DomainSignalSetStatus,
    DomainSignalValue,
    DomainSignalValueStatus,
    MarketRegimeSnapshot,
    ReleaseItemComponentType,
    StrategyDefinition,
    StrategyRouteDecision,
    StrategyRouteOutcome,
    StrategySignal,
    StrategySignalDirection,
)
from .release import FrozenReleaseSlice, resolve_frozen_slice


logger = logging.getLogger(__name__)

MAX_BUSINESS_REQUEST_KEY_LENGTH = 191
MAX_TRACE_FIELD_LENGTH = 80
MAX_ERROR_CODE_LENGTH = 120
MAX_ERROR_MESSAGE_LENGTH = 500
MAX_CONFIDENCE_SEMANTICS_LENGTH = 80
MAX_EVIDENCE_TEXT_LENGTH = 1000


def _limited_text(value: Any, *, max_length: int) -> str:
    text = str(value or "").strip()
    if len(text) <= max_length:
        return text
    return text[: max_length - 1] + "…"


@dataclass(frozen=True)
class StrategySignalContext:
    decision: StrategyRouteDecision
    definition: StrategyDefinition
    strategy_slice: FrozenReleaseSlice
    market_regime_snapshot: MarketRegimeSnapshot
    domain_signal_set: DomainSignalSet
    domain_values: tuple[DomainSignalValue, ...]
    allowed_domain_codes: tuple[str, ...]
    required_domain_codes: tuple[str, ...]
    frozen_weights: dict[str, str]


@dataclass(frozen=True)
class StrategySignalDraft:
    status: str
    direction: str
    strength: Decimal | None
    confidence: Decimal | None
    confidence_semantics: str
    prediction_horizon: str
    is_usable: bool
    allows_strategy_signal_quality: bool
    used_domain_signal_codes: list[str]
    used_domain_signal_value_ids: list[int]
    actual_input_weights: dict[str, str]
    trade_price_condition: dict[str, Any]
    aggregation_snapshot: dict[str, Any]
    conflict_snapshot: dict[str, Any]
    evidence_items: list[dict[str, Any]]
    evidence_text_zh: str
    payload_summary: dict[str, Any]
    error_code: str = ""
    error_message: str = ""
    latency_ms: int = 0


def _json_ready(value: Any) -> Any:
    value = thaw_value(value)
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _json_ready(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_json_ready(item) for item in value]
    return value


def _empty_result_data(*, strategy_route_decision_id: int | None = None) -> dict[str, Any]:
    return {
        "strategy_signal_id": None,
        "strategy_signal_key": None,
        "strategy_route_decision_id": strategy_route_decision_id,
        "strategy_definition_id": None,
        "strategy_analysis_release_id": None,
        "strategy_analysis_release_hash": "",
        "domain_signal_set_id": None,
        "market_regime_snapshot_id": None,
        "direction": StrategySignalDirection.NONE,
        "strength": None,
        "confidence": None,
        "is_usable": False,
        "allows_strategy_signal_quality": False,
        "error_code": "",
        "error_message": "",
        "persisted": False,
    }


def _result_with_alert(
    *,
    status: ResultStatus,
    reason_code: str,
    message: str,
    business_request_key: str,
    trace_id: str,
    trigger_source: str,
    dry_run: bool,
    strategy_route_decision_id: int | None = None,
    payload_summary: dict[str, Any] | None = None,
) -> ServiceResult:
    data = _empty_result_data(strategy_route_decision_id=strategy_route_decision_id)
    data.update(payload_summary or {})
    data["error_code"] = reason_code
    data["error_message"] = message
    data["persisted"] = False
    if not dry_run:
        event_type = "strategy_signal_blocked"
        severity = AlertSeverity.WARNING
        if status == ResultStatus.FAILED:
            event_type = "strategy_signal_failed"
            severity = AlertSeverity.HIGH
        elif status == ResultStatus.UNKNOWN:
            event_type = "strategy_signal_unknown"
            severity = AlertSeverity.HIGH
        try:
            record_alert_event(
                event_key=build_idempotency_key(event_type, business_request_key, reason_code),
                source_module="StrategySignal",
                event_type=event_type,
                event_category="strategy_analysis",
                severity=severity,
                title_zh=f"StrategySignal：{reason_code}",
                message_zh=message,
                trace_id=trace_id,
                trigger_source=trigger_source,
                related_object_type="StrategyRouteDecision" if strategy_route_decision_id else "",
                related_object_id=str(strategy_route_decision_id or ""),
                business_status=status.value,
                reason_code=reason_code,
                payload_summary=data,
            )
        except DatabaseError:
            logger.exception("StrategySignal AlertEvent 写入失败 reason_code=%s trace_id=%s", reason_code, trace_id)
    return ServiceResult(status, reason_code, message, trace_id, trigger_source, data)


def _validate_request(
    *,
    strategy_route_decision_id: int,
    strategy_analysis_release_id: int,
    strategy_analysis_release_hash: str,
    expected_strategy_definition_hash: str,
    business_request_key: str,
    trace_id: str,
    trigger_source: str,
) -> tuple[str, str]:
    if strategy_route_decision_id <= 0 or strategy_analysis_release_id <= 0:
        return "strategy_signal_request_invalid", "路由决定和版本包 ID 必须是正整数"
    required = {
        "strategy_analysis_release_hash": strategy_analysis_release_hash,
        "expected_strategy_definition_hash": expected_strategy_definition_hash,
        "business_request_key": business_request_key,
        "trace_id": trace_id,
        "trigger_source": trigger_source,
    }
    missing = [name for name, value in required.items() if not str(value).strip()]
    if missing:
        return "strategy_signal_request_invalid", f"StrategySignal 请求缺少必要字段：{','.join(missing)}"
    if len(business_request_key) > MAX_BUSINESS_REQUEST_KEY_LENGTH:
        return "strategy_signal_request_invalid", "business_request_key 超过允许长度"
    if len(trace_id) > MAX_TRACE_FIELD_LENGTH:
        return "strategy_signal_request_invalid", "trace_id 超过允许长度"
    if len(trigger_source) > MAX_TRACE_FIELD_LENGTH:
        return "strategy_signal_request_invalid", "trigger_source 超过允许长度"
    return "", ""


def _signal_matches_request(
    signal: StrategySignal,
    *,
    decision_id: int,
    release_id: int,
    release_hash: str,
    definition_hash: str,
) -> bool:
    return (
        signal.strategy_route_decision_id == decision_id
        and signal.strategy_analysis_release_id == release_id
        and signal.release_hash == release_hash
        and signal.definition_hash == definition_hash
    )


def _signal_result(signal: StrategySignal, *, trace_id: str, trigger_source: str) -> ServiceResult:
    status = ResultStatus.SUCCEEDED
    reason = "strategy_signal_created"
    message = "StrategySignal 已生成"
    if signal.status == AnalysisObjectStatus.FAILED:
        status = ResultStatus.FAILED
        reason = signal.error_code or "strategy_signal_failed"
        message = signal.error_message or "StrategySignal 生成失败"
    elif signal.status == AnalysisObjectStatus.BLOCKED:
        status = ResultStatus.BLOCKED
        reason = signal.error_code or "strategy_signal_blocked"
        message = signal.error_message or "StrategySignal 被阻断"
    elif signal.status == AnalysisObjectStatus.UNKNOWN:
        status = ResultStatus.UNKNOWN
        reason = signal.error_code or "strategy_signal_unknown"
        message = signal.error_message or "StrategySignal 状态未知"
    return ServiceResult(
        status,
        reason,
        message,
        trace_id,
        trigger_source,
        {
            "strategy_signal_id": signal.id,
            "strategy_signal_key": signal.strategy_signal_key,
            "strategy_route_decision_id": signal.strategy_route_decision_id,
            "strategy_definition_id": signal.strategy_definition_id,
            "strategy_analysis_release_id": signal.strategy_analysis_release_id,
            "strategy_analysis_release_hash": signal.release_hash,
            "domain_signal_set_id": signal.domain_signal_set_id,
            "market_regime_snapshot_id": signal.market_regime_snapshot_id,
            "strategy_code": signal.strategy_code,
            "strategy_version": signal.strategy_version,
            "direction": signal.direction,
            "strength": signal.strength,
            "confidence": signal.confidence,
            "trade_price_condition": signal.trade_price_condition,
            "is_usable": signal.is_usable,
            "allows_strategy_signal_quality": signal.allows_strategy_signal_quality,
            "error_code": signal.error_code,
            "error_message": signal.error_message,
            "persisted": True,
        },
    )


def _definition_identity(
    definition: StrategyDefinition,
    item: Any,
) -> tuple[tuple[str, ...], tuple[str, ...], dict[str, str]]:
    allowed = normalize_domain_codes(definition.allowed_domain_codes)
    required = normalize_domain_codes(definition.required_domain_codes, allow_empty=True)
    params_hash = stable_hash(definition.params)
    frozen_weights = normalize_strategy_weights(
        definition.domain_input_weights,
        allowed_domain_codes=allowed,
        uses_input_weights=definition.uses_input_weights,
    )
    actual_hash = strategy_definition_hash(
        strategy_code=definition.strategy_code,
        strategy_version=definition.strategy_version,
        algorithm_name=definition.algorithm_name,
        algorithm_version=definition.algorithm_version,
        input_schema_version=definition.input_schema_version,
        output_schema_version=definition.output_schema_version,
        params_hash=params_hash,
        allowed_domain_codes=allowed,
        required_domain_codes=required,
        uses_input_weights=definition.uses_input_weights,
        domain_input_weights=frozen_weights,
        prediction_horizon=definition.prediction_horizon,
    )
    dependency_hash = strategy_definition_dependency_hash(
        {"allowed_domain_codes": list(allowed), "required_domain_codes": list(required)}
    )
    item_dependency_hash = strategy_definition_dependency_hash(item.payload_summary or {})
    identity_matches = (
        item.component_object_id == definition.id
        and item.component_code == definition.strategy_code
        and item.algorithm_name == definition.algorithm_name
        and item.algorithm_version == definition.algorithm_version
        and definition.params_hash == params_hash
        and item.params_hash == params_hash
        and definition.definition_hash == actual_hash
        and item.definition_hash == actual_hash
        and item.dependency_hash == dependency_hash
        and item.dependency_hash == item_dependency_hash
    )
    if not identity_matches:
        raise ValueError("StrategyDefinition 与版本包冻结身份不一致")
    return allowed, required, frozen_weights


def _load_decision(
    *,
    decision_id: int,
    release_id: int,
    release_hash: str,
) -> tuple[StrategyRouteDecision | None, str]:
    try:
        decision = StrategyRouteDecision.objects.select_related(
            "selected_strategy_definition",
            "strategy_analysis_release",
            "market_regime_snapshot__domain_signal_set__strategy_analysis_release",
        ).get(id=decision_id)
    except StrategyRouteDecision.DoesNotExist:
        return None, "strategy_route_decision_not_found"
    if (
        decision.status != AnalysisObjectStatus.CREATED
        or decision.route_outcome != StrategyRouteOutcome.SELECTED
        or not decision.is_usable
        or not decision.allows_strategy_signal
        or decision.selected_strategy_definition_id is None
    ):
        return None, "strategy_route_decision_not_consumable"
    if decision.strategy_analysis_release_id != release_id or decision.release_hash != release_hash:
        return None, "strategy_signal_release_mismatch"
    return decision, ""


def _resolve_definition_context(
    *,
    decision: StrategyRouteDecision,
    expected_definition_hash: str,
    registry: CalculatorRegistry,
) -> tuple[FrozenReleaseSlice | None, tuple[str, ...], tuple[str, ...], dict[str, str], str]:
    try:
        strategy_slice = resolve_frozen_slice(
            release_id=decision.strategy_analysis_release_id,
            release_hash=decision.release_hash,
            component_type=ReleaseItemComponentType.STRATEGY_DEFINITION,
        )
    except (ObjectDoesNotExist, ValueError):
        return None, (), (), {}, "strategy_definition_slice_invalid"
    definition = decision.selected_strategy_definition
    if definition is None:
        return None, (), (), {}, "strategy_definition_missing"
    item = next((candidate for candidate in strategy_slice.items if candidate.component_object_id == definition.id), None)
    if item is None:
        return None, (), (), {}, "strategy_definition_not_in_release"
    if definition.definition_hash != expected_definition_hash:
        return None, (), (), {}, "strategy_definition_hash_mismatch"
    if definition.status != DefinitionLifecycleStatus.ACTIVE or not definition.enabled:
        return None, (), (), {}, "strategy_definition_not_selectable"
    if definition.id not in set(decision.eligible_strategy_definition_ids or []):
        return None, (), (), {}, "strategy_definition_not_eligible"
    try:
        allowed, required, weights = _definition_identity(definition, item)
        calculator = registry.resolve(
            calculator_type=CalculatorType.STRATEGY_SIGNAL,
            algorithm_name=definition.algorithm_name,
            algorithm_version=definition.algorithm_version,
        )
    except (ValueError, StrategyCalculatorError):
        return None, (), (), {}, "strategy_definition_or_calculator_invalid"
    metadata = calculator.metadata
    if (
        metadata.input_schema_version != definition.input_schema_version
        or metadata.output_schema_version != definition.output_schema_version
        or metadata.uses_input_weights != definition.uses_input_weights
    ):
        return None, (), (), {}, "strategy_calculator_contract_mismatch"
    return strategy_slice, allowed, required, weights, ""


def _load_domain_values(
    *,
    domain_signal_set: DomainSignalSet,
    allowed_codes: tuple[str, ...],
    required_codes: tuple[str, ...],
) -> tuple[tuple[DomainSignalValue, ...] | None, str]:
    if domain_signal_set.status != DomainSignalSetStatus.CREATED or not domain_signal_set.is_usable:
        return None, "domain_signal_set_not_usable"
    release_items = {
        item.component_code: item
        for item in domain_signal_set.strategy_analysis_release.items.filter(
            component_type=ReleaseItemComponentType.DOMAIN_SIGNAL_DEFINITION
        )
    }
    if not set(allowed_codes).issubset(set(release_items)):
        return None, "strategy_domain_membership_invalid"
    values = DomainSignalValue.objects.filter(
        domain_signal_set=domain_signal_set,
        domain_code__in=allowed_codes,
        status=DomainSignalValueStatus.CREATED,
        is_valid=True,
    ).order_by("domain_code", "id")
    by_code: dict[str, DomainSignalValue] = {}
    for value in values:
        if value.domain_code in by_code:
            return None, "strategy_domain_value_duplicate"
        item = release_items.get(value.domain_code)
        if item is None or item.definition_hash != value.definition_hash:
            return None, "strategy_domain_source_invalid"
        by_code[value.domain_code] = value
    missing = sorted(set(required_codes) - set(by_code))
    if missing:
        return None, "strategy_required_domain_missing"
    return tuple(by_code[code] for code in allowed_codes if code in by_code), ""


def _load_context(
    *,
    decision_id: int,
    release_id: int,
    release_hash: str,
    expected_definition_hash: str,
    registry: CalculatorRegistry,
) -> tuple[StrategySignalContext | None, str]:
    decision, error = _load_decision(decision_id=decision_id, release_id=release_id, release_hash=release_hash)
    if decision is None:
        return None, error
    snapshot = decision.market_regime_snapshot
    domain_signal_set = snapshot.domain_signal_set
    if (
        snapshot.status != AnalysisObjectStatus.CREATED
        or not snapshot.is_usable
        or not snapshot.allows_strategy_routing
        or snapshot.strategy_analysis_release_id != release_id
        or snapshot.release_hash != release_hash
        or domain_signal_set.strategy_analysis_release_id != release_id
        or domain_signal_set.release_hash != release_hash
        or not domain_signal_set.allows_market_regime
    ):
        return None, "strategy_upstream_chain_invalid"
    strategy_slice, allowed, required, weights, error = _resolve_definition_context(
        decision=decision,
        expected_definition_hash=expected_definition_hash,
        registry=registry,
    )
    if strategy_slice is None:
        return None, error
    domain_values, error = _load_domain_values(
        domain_signal_set=domain_signal_set,
        allowed_codes=allowed,
        required_codes=required,
    )
    if domain_values is None:
        return None, error
    return StrategySignalContext(
        decision=decision,
        definition=decision.selected_strategy_definition,
        strategy_slice=strategy_slice,
        market_regime_snapshot=snapshot,
        domain_signal_set=domain_signal_set,
        domain_values=domain_values,
        allowed_domain_codes=allowed,
        required_domain_codes=required,
        frozen_weights=weights,
    ), ""


def _domain_value_payload(value: DomainSignalValue) -> dict[str, Any]:
    return {
        "domain_signal_value_id": value.id,
        "domain_code": value.domain_code,
        "direction": value.direction,
        "state_code": value.state_code,
        "strength": value.strength,
        "coverage_ratio": value.coverage_ratio,
        "agreement_ratio": value.agreement_ratio,
        "definition_hash": value.definition_hash,
        "payload_summary": _domain_value_payload_summary(value),
    }


def _domain_value_payload_summary(value: DomainSignalValue) -> dict[str, Any]:
    evidence_items = value.evidence_items
    if not isinstance(evidence_items, list):
        return {}
    for item in evidence_items:
        if not isinstance(item, dict):
            continue
        if item.get("evidence_type") != "domain_grouped_atomic_aggregation":
            continue
        summary = item.get("summary")
        if isinstance(summary, dict):
            return _json_ready(summary)
    return {}


def _build_calculator_input(context: StrategySignalContext) -> CalculatorInput:
    definition = context.definition
    return CalculatorInput(
        calculator_type=CalculatorType.STRATEGY_SIGNAL,
        input_schema_version=definition.input_schema_version,
        output_schema_version=definition.output_schema_version,
        upstream_refs={
            "domain_signal_set_id": context.domain_signal_set.id,
            "domain_signal_value_ids": [value.id for value in context.domain_values],
        },
        business_time_utc=context.domain_signal_set.analysis_close_time_utc,
        market_identity={
            "exchange": context.domain_signal_set.exchange,
            "market_type": context.domain_signal_set.market_type,
            "symbol": context.domain_signal_set.symbol,
        },
        frozen_params=definition.params,
        params_hash=definition.params_hash,
        values={
            "strategy_definition": {
                "strategy_code": definition.strategy_code,
                "strategy_version": definition.strategy_version,
                "definition_hash": definition.definition_hash,
                "allowed_domain_codes": list(context.allowed_domain_codes),
                "required_domain_codes": list(context.required_domain_codes),
                "uses_input_weights": definition.uses_input_weights,
                "domain_input_weights": context.frozen_weights,
                "prediction_horizon": definition.prediction_horizon,
            },
            "domain_values": [_domain_value_payload(value) for value in context.domain_values],
        },
        evidence_summary={
            "strategy_code": definition.strategy_code,
            "strategy_version": definition.strategy_version,
            "definition_hash": definition.definition_hash,
        },
    )


def _ratio(value: Any, *, field_name: str) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise InvalidCalculatorContractError(f"{field_name} 不是合法 Decimal") from exc
    if not result.is_finite() or result < 0 or result > 1:
        raise InvalidCalculatorContractError(f"{field_name} 必须位于 0 到 1")
    return result


def _validate_used_refs(
    raw_refs: Any,
    *,
    context: StrategySignalContext,
) -> tuple[list[str], list[int]]:
    if not isinstance(raw_refs, list | tuple) or not raw_refs:
        raise InvalidCalculatorContractError("used_domain_signal_value_refs 必须是非空列表")
    input_by_code = {value.domain_code: value for value in context.domain_values}
    used_codes: list[str] = []
    used_ids: list[int] = []
    for ref in raw_refs:
        if not isinstance(ref, dict):
            raise InvalidCalculatorContractError("领域输入引用必须是映射")
        code = str(ref.get("domain_code", "")).strip()
        try:
            value_id = int(ref.get("domain_signal_value_id"))
        except (TypeError, ValueError) as exc:
            raise InvalidCalculatorContractError("领域输入引用 ID 非法") from exc
        expected = input_by_code.get(code)
        if expected is None or expected.id != value_id:
            raise InvalidCalculatorContractError("领域输入引用不属于本次 CalculatorInput")
        used_codes.append(code)
        used_ids.append(value_id)
    if len(used_codes) != len(set(used_codes)) or len(used_ids) != len(set(used_ids)):
        raise InvalidCalculatorContractError("领域输入引用不得重复")
    if not set(context.required_domain_codes).issubset(set(used_codes)):
        raise InvalidCalculatorContractError("calculator 未实际使用全部 required 领域")
    return used_codes, used_ids


def _validate_actual_weights(
    raw_weights: Any,
    *,
    context: StrategySignalContext,
    used_codes: list[str],
) -> dict[str, str]:
    if not isinstance(raw_weights, dict):
        raise InvalidCalculatorContractError("actual_input_weights 必须是映射")
    if not context.definition.uses_input_weights:
        if raw_weights:
            raise InvalidCalculatorContractError("未启用输入权重时 actual_input_weights 必须为空")
        return {}
    if set(raw_weights) != set(used_codes):
        raise InvalidCalculatorContractError("actual_input_weights 必须完整覆盖实际使用领域")
    normalized: dict[str, str] = {}
    for code in sorted(raw_weights):
        try:
            value = Decimal(str(raw_weights[code]))
        except (InvalidOperation, ValueError, TypeError) as exc:
            raise InvalidCalculatorContractError(f"actual_input_weights.{code} 非法") from exc
        if not value.is_finite() or value < 0:
            raise InvalidCalculatorContractError(f"actual_input_weights.{code} 必须是有限非负数")
        text = format(value.normalize(), "f")
        if text != context.frozen_weights.get(code):
            raise InvalidCalculatorContractError("实际权重与冻结 StrategyDefinition 不一致")
        normalized[code] = text
    return normalized


def _validate_trade_price_condition(value: Any) -> dict[str, Any]:
    if value in (None, ""):
        return {}
    if not isinstance(value, dict):
        raise InvalidCalculatorContractError("trade_price_condition 必须是映射或为空")
    if not value:
        return {}
    required = {
        "condition_type",
        "reference_price_zone",
        "acceptable_price_zone",
        "support_or_resistance_refs",
        "allow_chasing",
        "reason_code",
        "reason_summary_zh",
    }
    missing = sorted(required - set(value))
    if missing:
        raise InvalidCalculatorContractError(f"trade_price_condition 缺少必要字段：{','.join(missing)}")
    for field_name in ("condition_type", "reason_code", "reason_summary_zh"):
        if not str(value.get(field_name, "")).strip():
            raise InvalidCalculatorContractError(f"trade_price_condition.{field_name} 不能为空")
    refs = value.get("support_or_resistance_refs")
    if not isinstance(refs, list) or any(not isinstance(item, str) or not item.strip() for item in refs):
        raise InvalidCalculatorContractError("trade_price_condition.support_or_resistance_refs 必须是非空字符串列表")
    if not refs:
        raise InvalidCalculatorContractError("trade_price_condition.support_or_resistance_refs 不能为空")
    if not isinstance(value.get("allow_chasing"), bool):
        raise InvalidCalculatorContractError("trade_price_condition.allow_chasing 必须是 bool")
    return _json_ready(value)


def _failed_draft(output: CalculatorOutput, *, latency_ms: int) -> StrategySignalDraft:
    error_code = _limited_text(output.error_code or "strategy_signal_calculator_failed", max_length=MAX_ERROR_CODE_LENGTH)
    error_message = _limited_text(output.error_message or "StrategySignal calculator 计算失败", max_length=MAX_ERROR_MESSAGE_LENGTH)
    return StrategySignalDraft(
        status=AnalysisObjectStatus.FAILED,
        direction=StrategySignalDirection.NONE,
        strength=None,
        confidence=None,
        confidence_semantics="",
        prediction_horizon="",
        is_usable=False,
        allows_strategy_signal_quality=False,
        used_domain_signal_codes=[],
        used_domain_signal_value_ids=[],
        actual_input_weights={},
        trade_price_condition={},
        aggregation_snapshot={},
        conflict_snapshot={},
        evidence_items=[],
        evidence_text_zh="StrategySignal calculator 计算失败。",
        payload_summary={"calculator_error_code": output.error_code},
        error_code=error_code,
        error_message=error_message,
        latency_ms=latency_ms,
    )


def _validate_output(
    *,
    output: CalculatorOutput,
    context: StrategySignalContext,
    latency_ms: int,
) -> StrategySignalDraft:
    if not isinstance(output, CalculatorOutput):
        raise InvalidCalculatorContractError("StrategySignal calculator 必须返回 CalculatorOutput")
    if output.output_schema_version != context.definition.output_schema_version:
        raise InvalidCalculatorContractError("StrategySignal 输出 schema 与 Definition 不一致")
    if output.calculation_status == CalculationStatus.FAILED:
        return _failed_draft(output, latency_ms=latency_ms)
    values = thaw_value(output.values)
    direction = str(values.get("direction", "")).strip()
    if direction not in {
        StrategySignalDirection.BULLISH,
        StrategySignalDirection.BEARISH,
        StrategySignalDirection.NEUTRAL,
    }:
        raise InvalidCalculatorContractError("成功 StrategySignal direction 非法")
    strength = _ratio(values.get("strength"), field_name="strength")
    confidence = _ratio(values.get("confidence"), field_name="confidence")
    confidence_semantics = str(values.get("confidence_semantics", "")).strip()
    if not confidence_semantics:
        raise InvalidCalculatorContractError("confidence_semantics 不能为空")
    if len(confidence_semantics) > MAX_CONFIDENCE_SEMANTICS_LENGTH:
        raise InvalidCalculatorContractError("confidence_semantics 超过允许长度")
    prediction_horizon = str(values.get("prediction_horizon", "")).strip()
    if prediction_horizon != context.definition.prediction_horizon:
        raise InvalidCalculatorContractError("prediction_horizon 与冻结 StrategyDefinition 不一致")
    used_codes, used_ids = _validate_used_refs(
        values.get("used_domain_signal_value_refs"),
        context=context,
    )
    actual_weights = _validate_actual_weights(
        values.get("actual_input_weights", {}),
        context=context,
        used_codes=used_codes,
    )
    trade_price_condition = _validate_trade_price_condition(values.get("trade_price_condition"))
    aggregation_snapshot = values.get("aggregation_snapshot")
    conflict_snapshot = values.get("conflict_snapshot")
    if not isinstance(aggregation_snapshot, dict) or not isinstance(conflict_snapshot, dict):
        raise InvalidCalculatorContractError("aggregation_snapshot 和 conflict_snapshot 必须是映射")
    evidence_text_zh = str(values.get("evidence_text_zh", "")).strip()
    if not evidence_text_zh:
        raise InvalidCalculatorContractError("evidence_text_zh 不能为空")
    if len(evidence_text_zh) > MAX_EVIDENCE_TEXT_LENGTH:
        raise InvalidCalculatorContractError("evidence_text_zh 超过允许长度")
    calculator_evidence = _json_ready(output.evidence_items)
    evidence_items = [
        {
            "type": "strategy_signal_input",
            "strategy_definition_id": context.definition.id,
            "domain_signal_set_id": context.domain_signal_set.id,
            "used_domain_signal_value_ids": used_ids,
        },
        *calculator_evidence,
    ]
    return StrategySignalDraft(
        status=AnalysisObjectStatus.CREATED,
        direction=direction,
        strength=strength,
        confidence=confidence,
        confidence_semantics=confidence_semantics,
        prediction_horizon=prediction_horizon,
        is_usable=True,
        allows_strategy_signal_quality=True,
        used_domain_signal_codes=used_codes,
        used_domain_signal_value_ids=used_ids,
        actual_input_weights=actual_weights,
        trade_price_condition=trade_price_condition,
        aggregation_snapshot=_json_ready(aggregation_snapshot),
        conflict_snapshot=_json_ready(conflict_snapshot),
        evidence_items=evidence_items,
        evidence_text_zh=evidence_text_zh,
        payload_summary={
            "calculation_summary": _json_ready(output.calculation_summary),
            "used_domain_count": len(used_ids),
        },
        latency_ms=latency_ms,
    )


def _calculate_draft(
    *,
    context: StrategySignalContext,
    registry: CalculatorRegistry,
) -> StrategySignalDraft:
    start = perf_counter()
    try:
        calculator = registry.resolve(
            calculator_type=CalculatorType.STRATEGY_SIGNAL,
            algorithm_name=context.definition.algorithm_name,
            algorithm_version=context.definition.algorithm_version,
        )
        output = calculator.calculate(_build_calculator_input(context))
        return _validate_output(
            output=output,
            context=context,
            latency_ms=int((perf_counter() - start) * 1000),
        )
    except (InvalidCalculatorContractError, StrategyCalculatorError, TypeError, ValueError, OverflowError) as exc:
        error_message = _limited_text(exc, max_length=MAX_ERROR_MESSAGE_LENGTH)
        return StrategySignalDraft(
            status=AnalysisObjectStatus.FAILED,
            direction=StrategySignalDirection.NONE,
            strength=None,
            confidence=None,
            confidence_semantics="",
            prediction_horizon="",
            is_usable=False,
            allows_strategy_signal_quality=False,
            used_domain_signal_codes=[],
            used_domain_signal_value_ids=[],
            actual_input_weights={},
            trade_price_condition={},
            aggregation_snapshot={},
            conflict_snapshot={},
            evidence_items=[],
            evidence_text_zh="StrategySignal 输出合同校验失败。",
            payload_summary={"error": str(exc)},
            error_code="strategy_signal_output_invalid",
            error_message=error_message,
            latency_ms=int((perf_counter() - start) * 1000),
        )
    except Exception as exc:
        logger.exception("StrategySignal calculator 出现未预期异常")
        error_message = _limited_text(f"{type(exc).__name__}: {exc}", max_length=MAX_ERROR_MESSAGE_LENGTH)
        return StrategySignalDraft(
            status=AnalysisObjectStatus.FAILED,
            direction=StrategySignalDirection.NONE,
            strength=None,
            confidence=None,
            confidence_semantics="",
            prediction_horizon="",
            is_usable=False,
            allows_strategy_signal_quality=False,
            used_domain_signal_codes=[],
            used_domain_signal_value_ids=[],
            actual_input_weights={},
            trade_price_condition={},
            aggregation_snapshot={},
            conflict_snapshot={},
            evidence_items=[],
            evidence_text_zh="StrategySignal calculator 出现未预期异常。",
            payload_summary={"exception_type": type(exc).__name__},
            error_code="strategy_signal_calculator_unexpected_error",
            error_message=error_message,
            latency_ms=int((perf_counter() - start) * 1000),
        )


def _strategy_signal_key(context: StrategySignalContext) -> str:
    return stable_hash(
        {
            "strategy_route_decision_id": context.decision.id,
            "strategy_signal_schema_version": settings.STRATEGY_SIGNAL_SCHEMA_VERSION,
            "definition_hash": context.definition.definition_hash,
            "domain_signal_set_id": context.domain_signal_set.id,
        }
    )


def _persist_signal(
    *,
    context: StrategySignalContext,
    draft: StrategySignalDraft,
    business_request_key: str,
    signal_key: str,
    trace_id: str,
    trigger_source: str,
) -> StrategySignal:
    definition = context.definition
    return StrategySignal.objects.create(
        strategy_signal_key=signal_key,
        business_request_key=business_request_key,
        strategy_route_decision=context.decision,
        strategy_definition=definition,
        strategy_analysis_release=context.strategy_slice.release,
        release_hash=context.strategy_slice.release.release_hash,
        domain_signal_set=context.domain_signal_set,
        market_regime_snapshot=context.market_regime_snapshot,
        strategy_signal_schema_version=settings.STRATEGY_SIGNAL_SCHEMA_VERSION,
        strategy_code=definition.strategy_code,
        strategy_version=definition.strategy_version,
        direction=draft.direction,
        strength=draft.strength,
        confidence=draft.confidence,
        confidence_semantics=draft.confidence_semantics,
        prediction_horizon=draft.prediction_horizon,
        status=draft.status,
        is_usable=draft.is_usable,
        allows_strategy_signal_quality=draft.allows_strategy_signal_quality,
        definition_status=definition.status,
        definition_enabled=definition.enabled,
        algorithm_name=definition.algorithm_name,
        algorithm_version=definition.algorithm_version,
        input_schema_version=definition.input_schema_version,
        output_schema_version=definition.output_schema_version,
        params_hash=definition.params_hash,
        definition_hash=definition.definition_hash,
        used_domain_signal_codes=draft.used_domain_signal_codes,
        used_domain_signal_value_ids=draft.used_domain_signal_value_ids,
        actual_input_weights=draft.actual_input_weights,
        trade_price_condition=draft.trade_price_condition,
        aggregation_snapshot=draft.aggregation_snapshot,
        conflict_snapshot=draft.conflict_snapshot,
        evidence_items=draft.evidence_items,
        evidence_text_zh=draft.evidence_text_zh,
        payload_summary=draft.payload_summary,
        error_code=draft.error_code,
        error_message=draft.error_message,
        analysis_close_time_utc=context.domain_signal_set.analysis_close_time_utc,
        trace_id=trace_id,
        trigger_source=trigger_source,
        calculated_at_utc=timezone.now(),
        latency_ms=draft.latency_ms,
    )


def _persist_or_recover(
    *,
    context: StrategySignalContext,
    draft: StrategySignalDraft,
    business_request_key: str,
    signal_key: str,
    trace_id: str,
    trigger_source: str,
) -> tuple[StrategySignal | None, ServiceResult | None]:
    try:
        with transaction.atomic():
            signal = _persist_signal(
                context=context,
                draft=draft,
                business_request_key=business_request_key,
                signal_key=signal_key,
                trace_id=trace_id,
                trigger_source=trigger_source,
            )
            if draft.status == AnalysisObjectStatus.FAILED:
                record_alert_event(
                    event_key=build_idempotency_key("strategy_signal_failed", business_request_key, draft.error_code),
                    source_module="StrategySignal",
                    event_type="strategy_signal_failed",
                    event_category="strategy_analysis",
                    severity=AlertSeverity.HIGH,
                    title_zh="StrategySignal 计算失败",
                    message_zh=draft.error_message or "StrategySignal 计算失败。",
                    trace_id=trace_id,
                    trigger_source=trigger_source,
                    related_object_type="StrategySignal",
                    related_object_id=str(signal.id),
                    business_status=draft.status,
                    reason_code=draft.error_code,
                    payload_summary=draft.payload_summary,
                )
        return signal, None
    except IntegrityError:
        try:
            by_request = StrategySignal.objects.filter(business_request_key=business_request_key).first()
            by_key = StrategySignal.objects.filter(strategy_signal_key=signal_key).first()
        except DatabaseError:
            return None, _result_with_alert(
                status=ResultStatus.UNKNOWN,
                reason_code="strategy_signal_persist_unknown",
                message="StrategySignal 写入结果无法确认",
                business_request_key=business_request_key,
                trace_id=trace_id,
                trigger_source=trigger_source,
                dry_run=False,
                strategy_route_decision_id=context.decision.id,
            )
        if by_request is not None:
            if not _signal_matches_request(
                by_request,
                decision_id=context.decision.id,
                release_id=context.strategy_slice.release.id,
                release_hash=context.strategy_slice.release.release_hash,
                definition_hash=context.definition.definition_hash,
            ):
                return None, _result_with_alert(
                    status=ResultStatus.BLOCKED,
                    reason_code="strategy_signal_idempotency_conflict",
                    message="business_request_key 已被另一份 StrategySignal 请求使用",
                    business_request_key=business_request_key,
                    trace_id=trace_id,
                    trigger_source=trigger_source,
                    dry_run=False,
                    strategy_route_decision_id=context.decision.id,
                )
            return by_request, None
        if by_key is not None:
            return by_key, None
        return None, _result_with_alert(
            status=ResultStatus.FAILED,
            reason_code="strategy_signal_persist_failed",
            message="StrategySignal 写入被数据库明确拒绝",
            business_request_key=business_request_key,
            trace_id=trace_id,
            trigger_source=trigger_source,
            dry_run=False,
            strategy_route_decision_id=context.decision.id,
        )
    except DataError as exc:
        return None, _result_with_alert(
            status=ResultStatus.FAILED,
            reason_code="strategy_signal_persist_failed",
            message=f"StrategySignal 数据不满足存储合同：{exc}",
            business_request_key=business_request_key,
            trace_id=trace_id,
            trigger_source=trigger_source,
            dry_run=False,
            strategy_route_decision_id=context.decision.id,
        )
    except DatabaseError:
        logger.exception("StrategySignal 写入失败 trace_id=%s", trace_id)
        return None, _result_with_alert(
            status=ResultStatus.UNKNOWN,
            reason_code="strategy_signal_persist_unknown",
            message="StrategySignal 写入结果无法确认",
            business_request_key=business_request_key,
            trace_id=trace_id,
            trigger_source=trigger_source,
            dry_run=False,
            strategy_route_decision_id=context.decision.id,
        )


def generate_strategy_signal(
    *,
    strategy_route_decision_id: int,
    strategy_analysis_release_id: int,
    strategy_analysis_release_hash: str,
    expected_strategy_definition_hash: str,
    business_request_key: str,
    trace_id: str,
    trigger_source: str,
    dry_run: bool = False,
    registry: CalculatorRegistry = default_registry,
) -> ServiceResult:
    error, message = _validate_request(
        strategy_route_decision_id=strategy_route_decision_id,
        strategy_analysis_release_id=strategy_analysis_release_id,
        strategy_analysis_release_hash=strategy_analysis_release_hash,
        expected_strategy_definition_hash=expected_strategy_definition_hash,
        business_request_key=business_request_key,
        trace_id=trace_id,
        trigger_source=trigger_source,
    )
    if error:
        return _result_with_alert(
            status=ResultStatus.BLOCKED,
            reason_code=error,
            message=message,
            business_request_key=business_request_key or "invalid-strategy-signal-request",
            trace_id=trace_id,
            trigger_source=trigger_source,
            dry_run=dry_run,
            strategy_route_decision_id=strategy_route_decision_id if strategy_route_decision_id > 0 else None,
        )
    if not dry_run:
        existing = StrategySignal.objects.filter(business_request_key=business_request_key).first()
        if existing is not None:
            if not _signal_matches_request(
                existing,
                decision_id=strategy_route_decision_id,
                release_id=strategy_analysis_release_id,
                release_hash=strategy_analysis_release_hash,
                definition_hash=expected_strategy_definition_hash,
            ):
                return _result_with_alert(
                    status=ResultStatus.BLOCKED,
                    reason_code="strategy_signal_idempotency_conflict",
                    message="business_request_key 已被另一份 StrategySignal 请求使用",
                    business_request_key=business_request_key,
                    trace_id=trace_id,
                    trigger_source=trigger_source,
                    dry_run=False,
                    strategy_route_decision_id=strategy_route_decision_id,
                )
            return _signal_result(existing, trace_id=trace_id, trigger_source=trigger_source)
    context, error = _load_context(
        decision_id=strategy_route_decision_id,
        release_id=strategy_analysis_release_id,
        release_hash=strategy_analysis_release_hash,
        expected_definition_hash=expected_strategy_definition_hash,
        registry=registry,
    )
    if context is None:
        return _result_with_alert(
            status=ResultStatus.BLOCKED,
            reason_code=error,
            message="StrategySignal 上游、策略定义或领域输入不满足正式计算条件",
            business_request_key=business_request_key,
            trace_id=trace_id,
            trigger_source=trigger_source,
            dry_run=dry_run,
            strategy_route_decision_id=strategy_route_decision_id,
        )
    signal_key = _strategy_signal_key(context)
    if not dry_run:
        existing_by_key = StrategySignal.objects.filter(strategy_signal_key=signal_key).first()
        if existing_by_key is not None:
            return _signal_result(existing_by_key, trace_id=trace_id, trigger_source=trigger_source)
    draft = _calculate_draft(context=context, registry=registry)
    if dry_run:
        return ServiceResult(
            ResultStatus.SUCCEEDED if draft.status == AnalysisObjectStatus.CREATED else ResultStatus.FAILED,
            "strategy_signal_dry_run",
            "StrategySignal dry-run 已完成，未写入正式业务对象",
            trace_id,
            trigger_source,
            {
                **_empty_result_data(strategy_route_decision_id=strategy_route_decision_id),
                "strategy_definition_id": context.definition.id,
                "strategy_analysis_release_id": context.strategy_slice.release.id,
                "strategy_analysis_release_hash": context.strategy_slice.release.release_hash,
                "domain_signal_set_id": context.domain_signal_set.id,
                "market_regime_snapshot_id": context.market_regime_snapshot.id,
                "direction": draft.direction,
                "strength": draft.strength,
                "confidence": draft.confidence,
                "error_code": draft.error_code,
                "error_message": draft.error_message,
                "persisted": False,
            },
        )
    signal, persist_result = _persist_or_recover(
        context=context,
        draft=draft,
        business_request_key=business_request_key,
        signal_key=signal_key,
        trace_id=trace_id,
        trigger_source=trigger_source,
    )
    if persist_result is not None:
        return persist_result
    assert signal is not None
    return _signal_result(signal, trace_id=trace_id, trigger_source=trigger_source)
