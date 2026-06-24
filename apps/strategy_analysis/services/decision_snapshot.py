"""DecisionSnapshot 模块：把质量放行的 StrategySignal 转换为目标仓位意图快照。
负责：校验 StrategySignalQualityResult 与冻结 DecisionPolicyDefinition，调用 DecisionPolicy calculator，写 DecisionSnapshot 与必要 AlertEvent。
不负责：重新分析市场、读取账户/价格/Binance、生成订单、风控审批或交易执行；不访问 Redis、DeepSeek，不发送 Hermes。
读写数据库；不访问外部服务；不调用大模型；不涉及真实交易。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from time import perf_counter
from typing import Any

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

from ..definition_hashes import decision_policy_definition_hash
from ..models import (
    AnalysisObjectStatus,
    DecisionPolicyDefinition,
    DecisionSnapshot,
    DecisionTargetIntent,
    DefinitionLifecycleStatus,
    ReleaseItemComponentType,
    StrategySignalQualityResult,
    StrategySignalQualityStatus,
)
from .release import FrozenReleaseSlice, resolve_frozen_slice


logger = logging.getLogger(__name__)

MAX_BUSINESS_REQUEST_KEY_LENGTH = 191
MAX_TRACE_FIELD_LENGTH = 80
MAX_ERROR_CODE_LENGTH = 120
MAX_ERROR_MESSAGE_LENGTH = 500
MAX_REASON_SUMMARY_LENGTH = 1000

FORBIDDEN_CALCULATOR_OUTPUT_FIELDS = {
    "status",
    "business_status",
    "allows_order_plan",
    "decision_action",
    "order_side",
    "order_quantity",
    "reduce_only",
    "close_position",
    "leverage",
}


@dataclass(frozen=True)
class DecisionContext:
    quality_result: StrategySignalQualityResult
    policy: DecisionPolicyDefinition
    policy_slice: FrozenReleaseSlice


@dataclass(frozen=True)
class DecisionDraft:
    status: str
    target_intent: str
    target_position_ratio: Decimal | None
    target_confidence: Decimal | None
    target_reason_code: str
    target_reason_summary_zh: str
    decision_calculation_snapshot: dict[str, Any]
    input_snapshot: dict[str, Any]
    evidence_summary: dict[str, Any]
    expires_at_utc: datetime | None
    is_usable: bool
    allows_order_plan: bool
    blocked_reason: str = ""
    error_code: str = ""
    error_message: str = ""


def _limited_text(value: Any, *, max_length: int) -> str:
    text = str(value or "").strip()
    if len(text) <= max_length:
        return text
    return text[: max_length - 1] + "…"


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


def _empty_result_data(*, quality_result_id: int | None = None) -> dict[str, Any]:
    return {
        "decision_snapshot_id": None,
        "decision_snapshot_key": None,
        "strategy_signal_quality_result_id": quality_result_id,
        "strategy_signal_id": None,
        "decision_policy_definition_id": None,
        "strategy_analysis_release_id": None,
        "strategy_analysis_release_hash": "",
        "target_intent": "",
        "target_position_ratio": None,
        "target_confidence": None,
        "is_usable": False,
        "allows_order_plan": False,
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
    quality_result_id: int | None = None,
    payload_summary: dict[str, Any] | None = None,
) -> ServiceResult:
    data = _empty_result_data(quality_result_id=quality_result_id)
    data.update(payload_summary or {})
    data["error_code"] = reason_code
    data["error_message"] = message
    if not dry_run:
        event_type = "decision_snapshot_blocked"
        severity = AlertSeverity.WARNING
        if status == ResultStatus.FAILED:
            event_type = "decision_snapshot_failed"
            severity = AlertSeverity.HIGH
        elif status == ResultStatus.UNKNOWN:
            event_type = "decision_snapshot_unknown"
            severity = AlertSeverity.HIGH
        try:
            record_alert_event(
                event_key=build_idempotency_key(event_type, business_request_key, reason_code),
                source_module="DecisionSnapshot",
                event_type=event_type,
                event_category="strategy_analysis",
                severity=severity,
                title_zh=f"DecisionSnapshot：{reason_code}",
                message_zh=message,
                trace_id=trace_id,
                trigger_source=trigger_source,
                related_object_type="StrategySignalQualityResult" if quality_result_id else "",
                related_object_id=str(quality_result_id or ""),
                business_status=status.value,
                reason_code=reason_code,
                payload_summary=data,
            )
        except DatabaseError:
            logger.exception("DecisionSnapshot AlertEvent 写入失败 reason_code=%s trace_id=%s", reason_code, trace_id)
    return ServiceResult(status, reason_code, message, trace_id, trigger_source, data)


def _validate_request(
    *,
    strategy_signal_quality_result_id: int,
    strategy_analysis_release_id: int,
    strategy_analysis_release_hash: str,
    business_request_key: str,
    trace_id: str,
    trigger_source: str,
) -> tuple[str, str]:
    if strategy_signal_quality_result_id <= 0 or strategy_analysis_release_id <= 0:
        return "decision_snapshot_request_invalid", "质量结果和版本包 ID 必须是正整数"
    required = {
        "strategy_analysis_release_hash": strategy_analysis_release_hash,
        "business_request_key": business_request_key,
        "trace_id": trace_id,
        "trigger_source": trigger_source,
    }
    missing = [name for name, value in required.items() if not str(value).strip()]
    if missing:
        return "decision_snapshot_request_invalid", f"DecisionSnapshot 请求缺少必要字段：{','.join(missing)}"
    if len(business_request_key) > MAX_BUSINESS_REQUEST_KEY_LENGTH:
        return "decision_snapshot_request_invalid", "business_request_key 超过允许长度"
    if len(trace_id) > MAX_TRACE_FIELD_LENGTH or len(trigger_source) > MAX_TRACE_FIELD_LENGTH:
        return "decision_snapshot_request_invalid", "trace_id 或 trigger_source 超过允许长度"
    return "", ""


def _snapshot_matches_request(
    snapshot: DecisionSnapshot,
    *,
    quality_result_id: int,
    release_id: int,
    release_hash: str,
) -> bool:
    return (
        snapshot.strategy_signal_quality_result_id == quality_result_id
        and snapshot.strategy_analysis_release_id == release_id
        and snapshot.release_hash == release_hash
    )


def _snapshot_result(snapshot: DecisionSnapshot, *, trace_id: str, trigger_source: str) -> ServiceResult:
    status = ResultStatus.SUCCEEDED
    reason = "decision_snapshot_created"
    message = "DecisionSnapshot 已生成"
    if snapshot.status == AnalysisObjectStatus.FAILED:
        status = ResultStatus.FAILED
        reason = snapshot.error_code or "decision_snapshot_failed"
        message = snapshot.error_message or "DecisionSnapshot 生成失败"
    elif snapshot.status == AnalysisObjectStatus.BLOCKED:
        status = ResultStatus.BLOCKED
        reason = snapshot.error_code or "decision_snapshot_blocked"
        message = snapshot.error_message or "DecisionSnapshot 被阻断"
    elif snapshot.status == AnalysisObjectStatus.UNKNOWN:
        status = ResultStatus.UNKNOWN
        reason = snapshot.error_code or "decision_snapshot_unknown"
        message = snapshot.error_message or "DecisionSnapshot 状态未知"
    return ServiceResult(status, reason, message, trace_id, trigger_source, _model_data(snapshot))


def _model_data(snapshot: DecisionSnapshot) -> dict[str, Any]:
    return {
        "decision_snapshot_id": snapshot.id,
        "decision_snapshot_key": snapshot.decision_snapshot_key,
        "strategy_signal_quality_result_id": snapshot.strategy_signal_quality_result_id,
        "strategy_signal_id": snapshot.strategy_signal_id,
        "decision_policy_definition_id": snapshot.decision_policy_definition_id,
        "strategy_analysis_release_id": snapshot.strategy_analysis_release_id,
        "strategy_analysis_release_hash": snapshot.release_hash,
        "target_intent": snapshot.target_intent,
        "target_position_ratio": snapshot.target_position_ratio,
        "target_confidence": snapshot.target_confidence,
        "is_usable": snapshot.is_usable,
        "allows_order_plan": snapshot.allows_order_plan,
        "error_code": snapshot.error_code,
        "error_message": snapshot.error_message,
        "persisted": True,
    }


def _load_quality_result(quality_result_id: int) -> tuple[StrategySignalQualityResult | None, str]:
    try:
        return (
            StrategySignalQualityResult.objects.select_related("strategy_signal").get(id=quality_result_id),
            "",
        )
    except StrategySignalQualityResult.DoesNotExist:
        return None, "strategy_signal_quality_missing"


def _precondition_error(
    quality_result: StrategySignalQualityResult,
    *,
    release_id: int,
    release_hash: str,
) -> str:
    signal = quality_result.strategy_signal
    if (
        quality_result.status != AnalysisObjectStatus.CREATED
        or not quality_result.is_usable
        or not quality_result.allows_decision_snapshot
        or quality_result.quality_status not in {StrategySignalQualityStatus.PASSED, StrategySignalQualityStatus.WARNING}
    ):
        return "strategy_signal_quality_not_allowed"
    if (
        signal.status != AnalysisObjectStatus.CREATED
        or not signal.is_usable
        or not signal.allows_strategy_signal_quality
    ):
        return "strategy_signal_not_consumable"
    if (
        quality_result.strategy_analysis_release_id != release_id
        or quality_result.release_hash != release_hash
        or signal.strategy_analysis_release_id != release_id
        or signal.release_hash != release_hash
    ):
        return "decision_snapshot_non_formal_rejected"
    return ""


def _load_decision_policy(
    *,
    release_id: int,
    release_hash: str,
    registry: CalculatorRegistry,
) -> tuple[DecisionPolicyDefinition | None, FrozenReleaseSlice | None, str]:
    try:
        policy_slice = resolve_frozen_slice(
            release_id=release_id,
            release_hash=release_hash,
            component_type=ReleaseItemComponentType.DECISION_POLICY_DEFINITION,
        )
    except (ObjectDoesNotExist, ValueError):
        return None, None, "decision_policy_missing"
    if len(policy_slice.items) != 1:
        return None, None, "decision_policy_count_invalid"
    item = policy_slice.items[0]
    try:
        policy = DecisionPolicyDefinition.objects.get(id=item.component_object_id)
    except DecisionPolicyDefinition.DoesNotExist:
        return None, None, "decision_policy_missing"
    if policy.status != DefinitionLifecycleStatus.ACTIVE or not policy.enabled:
        return None, None, "decision_policy_unavailable"
    actual_params_hash = stable_hash(policy.params)
    actual_hash = decision_policy_definition_hash(
        policy_code=policy.policy_code,
        policy_version=policy.policy_version,
        algorithm_name=policy.algorithm_name,
        algorithm_version=policy.algorithm_version,
        input_schema_version=policy.input_schema_version,
        output_schema_version=policy.output_schema_version,
        target_schema_version=policy.target_schema_version,
        params_hash=actual_params_hash,
    )
    if (
        item.component_code != policy.policy_code
        or item.algorithm_name != policy.algorithm_name
        or item.algorithm_version != policy.algorithm_version
        or policy.params_hash != actual_params_hash
        or item.params_hash != actual_params_hash
        or policy.definition_hash != actual_hash
        or item.definition_hash != actual_hash
    ):
        return None, None, "decision_policy_hash_mismatch"
    try:
        calculator = registry.resolve(
            calculator_type=CalculatorType.DECISION_POLICY,
            algorithm_name=policy.algorithm_name,
            algorithm_version=policy.algorithm_version,
        )
    except StrategyCalculatorError:
        return None, None, "decision_policy_calculator_missing"
    if (
        calculator.metadata.input_schema_version != policy.input_schema_version
        or calculator.metadata.output_schema_version != policy.output_schema_version
    ):
        return None, None, "decision_policy_calculator_schema_mismatch"
    return policy, policy_slice, ""


def _decimal(value: Any, *, field_name: str, minimum: Decimal, maximum: Decimal) -> Decimal:
    try:
        decimal = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise InvalidCalculatorContractError(f"{field_name} 不是合法 Decimal") from exc
    if not decimal.is_finite() or decimal < minimum or decimal > maximum:
        raise InvalidCalculatorContractError(f"{field_name} 必须位于 {minimum} 到 {maximum}")
    return decimal


def _expires_after_seconds(policy: DecisionPolicyDefinition) -> int:
    raw = thaw_value(policy.params).get("expires_after_seconds")
    try:
        seconds = int(raw)
    except (TypeError, ValueError) as exc:
        raise InvalidCalculatorContractError("DecisionPolicyDefinition.params.expires_after_seconds 必须是非负整数") from exc
    if seconds < 0:
        raise InvalidCalculatorContractError("DecisionPolicyDefinition.params.expires_after_seconds 不得为负数")
    return seconds


def _build_calculator_input(context: DecisionContext) -> CalculatorInput:
    quality = context.quality_result
    signal = quality.strategy_signal
    return CalculatorInput(
        calculator_type=CalculatorType.DECISION_POLICY,
        input_schema_version=context.policy.input_schema_version,
        output_schema_version=context.policy.output_schema_version,
        upstream_refs={
            "strategy_signal_id": signal.id,
            "strategy_signal_quality_result_id": quality.id,
        },
        business_time_utc=quality.market_as_of_utc or signal.analysis_close_time_utc,
        frozen_params=context.policy.params,
        params_hash=context.policy.params_hash,
        values={
            "strategy_signal_id": signal.id,
            "strategy_signal_quality_result_id": quality.id,
            "strategy_direction": signal.direction,
            "strategy_strength": str(signal.strength) if signal.strength is not None else None,
            "strategy_confidence": str(signal.confidence) if signal.confidence is not None else None,
            "confidence_semantics": signal.confidence_semantics,
            "prediction_horizon": signal.prediction_horizon,
            "quality_status": quality.quality_status,
            "quality_issue_summary": quality.check_summary,
            "target_schema_version": context.policy.target_schema_version,
            "market_as_of_utc": (quality.market_as_of_utc or signal.analysis_close_time_utc).isoformat(),
            "analysis_close_time_utc": signal.analysis_close_time_utc.isoformat(),
        },
        evidence_summary={
            "strategy_signal_quality_result_id": quality.id,
            "quality_status": quality.quality_status,
            "quality_issue_count": quality.issue_count,
        },
    )


def _input_snapshot(context: DecisionContext) -> dict[str, Any]:
    quality = context.quality_result
    signal = quality.strategy_signal
    return {
        "strategy_signal_id": signal.id,
        "strategy_signal_quality_result_id": quality.id,
        "strategy_direction": signal.direction,
        "strategy_strength": str(signal.strength) if signal.strength is not None else None,
        "strategy_confidence": str(signal.confidence) if signal.confidence is not None else None,
        "confidence_semantics": signal.confidence_semantics,
        "prediction_horizon": signal.prediction_horizon,
        "quality_status": quality.quality_status,
        "quality_issue_summary": quality.check_summary,
        "decision_policy_definition_id": context.policy.id,
        "policy_code": context.policy.policy_code,
        "policy_version": context.policy.policy_version,
        "algorithm_name": context.policy.algorithm_name,
        "algorithm_version": context.policy.algorithm_version,
        "params_hash": context.policy.params_hash,
        "definition_hash": context.policy.definition_hash,
        "market_as_of_utc": _json_ready(quality.market_as_of_utc or signal.analysis_close_time_utc),
        "analysis_close_time_utc": _json_ready(signal.analysis_close_time_utc),
    }


def _failed_draft(context: DecisionContext, *, error_code: str, error_message: str) -> DecisionDraft:
    quality = context.quality_result
    signal = quality.strategy_signal
    return DecisionDraft(
        status=AnalysisObjectStatus.FAILED,
        target_intent="",
        target_position_ratio=None,
        target_confidence=None,
        target_reason_code="",
        target_reason_summary_zh="DecisionPolicy calculator 计算失败。",
        decision_calculation_snapshot={},
        input_snapshot=_input_snapshot(context),
        evidence_summary={"strategy_signal_quality_result_id": quality.id, "strategy_signal_id": signal.id},
        expires_at_utc=None,
        is_usable=False,
        allows_order_plan=False,
        blocked_reason=error_code,
        error_code=_limited_text(error_code, max_length=MAX_ERROR_CODE_LENGTH),
        error_message=_limited_text(error_message, max_length=MAX_ERROR_MESSAGE_LENGTH),
    )


def _validate_output(*, output: CalculatorOutput, context: DecisionContext, latency_ms: int) -> DecisionDraft:
    if not isinstance(output, CalculatorOutput):
        raise InvalidCalculatorContractError("DecisionPolicy calculator 必须返回 CalculatorOutput")
    if output.output_schema_version != context.policy.output_schema_version:
        raise InvalidCalculatorContractError("DecisionPolicy 输出 schema 与 Definition 不一致")
    if output.calculation_status == CalculationStatus.FAILED:
        return _failed_draft(
            context,
            error_code=output.error_code or "decision_policy_calculator_failed",
            error_message=output.error_message or "DecisionPolicy calculator 计算失败",
        )
    values = thaw_value(output.values)
    forbidden = sorted(FORBIDDEN_CALCULATOR_OUTPUT_FIELDS & set(values))
    if forbidden:
        raise InvalidCalculatorContractError(f"DecisionPolicy 输出包含禁止字段：{','.join(forbidden)}")
    intent = str(values.get("target_intent", "")).strip()
    if intent not in set(DecisionTargetIntent.values):
        raise InvalidCalculatorContractError("target_intent 非法")
    ratio = _target_position_ratio(values.get("target_position_ratio"), target_intent=intent)
    confidence = _decimal(values.get("target_confidence"), field_name="target_confidence", minimum=Decimal("0"), maximum=Decimal("1"))
    reason_code = str(values.get("target_reason_code", "")).strip()
    reason_summary = str(values.get("target_reason_summary_zh", "")).strip()
    if not reason_code or not reason_summary:
        raise InvalidCalculatorContractError("target_reason_code 和 target_reason_summary_zh 不能为空")
    calculation_snapshot = values.get("decision_calculation_snapshot")
    if not isinstance(calculation_snapshot, dict):
        raise InvalidCalculatorContractError("decision_calculation_snapshot 必须是映射")
    expires_at = _expires_at(context)
    now = timezone.now()
    is_target_position = intent == DecisionTargetIntent.TARGET_POSITION
    is_usable = intent in set(DecisionTargetIntent.values) and (not is_target_position or expires_at > now)
    allows_order_plan = bool(is_target_position and ratio is not None and is_usable)
    evidence_items = _json_ready(output.evidence_items)
    if not evidence_items:
        raise InvalidCalculatorContractError("DecisionPolicy 输出证据不能为空")
    return DecisionDraft(
        status=AnalysisObjectStatus.CREATED,
        target_intent=intent,
        target_position_ratio=ratio,
        target_confidence=confidence,
        target_reason_code=_limited_text(reason_code, max_length=MAX_ERROR_CODE_LENGTH),
        target_reason_summary_zh=_limited_text(reason_summary, max_length=MAX_REASON_SUMMARY_LENGTH),
        decision_calculation_snapshot={
            **_json_ready(calculation_snapshot),
            "latency_ms": latency_ms,
        },
        input_snapshot=_input_snapshot(context),
        evidence_summary={
            "calculator_evidence": evidence_items,
            "calculation_summary": _json_ready(output.calculation_summary),
        },
        expires_at_utc=expires_at,
        is_usable=is_usable,
        allows_order_plan=allows_order_plan,
        blocked_reason="" if allows_order_plan or not is_target_position else "decision_snapshot_expired",
    )


def _target_position_ratio(value: Any, *, target_intent: str) -> Decimal | None:
    if target_intent == DecisionTargetIntent.TARGET_POSITION:
        if value is None or value == "":
            raise InvalidCalculatorContractError("TARGET_POSITION 必须包含 target_position_ratio")
        return _decimal(value, field_name="target_position_ratio", minimum=Decimal("-1"), maximum=Decimal("1"))
    if value not in (None, ""):
        raise InvalidCalculatorContractError("NO_TRADE / NO_TARGET_CHANGE 不得包含 target_position_ratio")
    return None


def _expires_at(context: DecisionContext) -> datetime:
    signal = context.quality_result.strategy_signal
    base_time = context.quality_result.market_as_of_utc or signal.analysis_close_time_utc
    if base_time is None:
        raise InvalidCalculatorContractError("DecisionSnapshot 缺少 market_as_of_utc / analysis_close_time_utc")
    return base_time + timedelta(seconds=_expires_after_seconds(context.policy))


def _calculate_draft(*, context: DecisionContext, registry: CalculatorRegistry) -> DecisionDraft:
    start = perf_counter()
    try:
        calculator = registry.resolve(
            calculator_type=CalculatorType.DECISION_POLICY,
            algorithm_name=context.policy.algorithm_name,
            algorithm_version=context.policy.algorithm_version,
        )
        output = calculator.calculate(_build_calculator_input(context))
        return _validate_output(output=output, context=context, latency_ms=int((perf_counter() - start) * 1000))
    except (InvalidCalculatorContractError, StrategyCalculatorError, TypeError, ValueError, OverflowError) as exc:
        return _failed_draft(
            context,
            error_code="decision_policy_output_invalid",
            error_message=str(exc),
        )
    except Exception as exc:
        logger.exception("DecisionPolicy calculator 出现未预期异常")
        return _failed_draft(
            context,
            error_code="decision_policy_calculator_unexpected_error",
            error_message=f"{type(exc).__name__}: {exc}",
        )


def _decision_snapshot_key(context: DecisionContext, draft: DecisionDraft) -> str:
    quality = context.quality_result
    signal = quality.strategy_signal
    return stable_hash(
        {
            "strategy_signal_quality_result_id": quality.id,
            "decision_policy_definition_id": context.policy.id,
            "definition_hash": context.policy.definition_hash,
            "params_hash": context.policy.params_hash,
            "target_schema_version": context.policy.target_schema_version,
            "target_intent": draft.target_intent,
            "target_position_ratio": str(draft.target_position_ratio) if draft.target_position_ratio is not None else None,
            "target_confidence": str(draft.target_confidence) if draft.target_confidence is not None else None,
            "target_reason_code": draft.target_reason_code,
            "market_as_of_utc": (quality.market_as_of_utc or signal.analysis_close_time_utc).isoformat(),
        }
    )


def _persist_snapshot(
    *,
    context: DecisionContext,
    draft: DecisionDraft,
    snapshot_key: str,
    business_request_key: str,
    trace_id: str,
    trigger_source: str,
) -> DecisionSnapshot:
    quality = context.quality_result
    signal = quality.strategy_signal
    return DecisionSnapshot.objects.create(
        decision_snapshot_key=snapshot_key,
        business_request_key=business_request_key,
        strategy_signal_quality_result=quality,
        strategy_signal=signal,
        decision_policy_definition=context.policy,
        strategy_analysis_release=context.policy_slice.release,
        release_hash=context.policy_slice.release.release_hash,
        strategy_code=signal.strategy_code,
        strategy_version=signal.strategy_version,
        policy_code=context.policy.policy_code,
        policy_version=context.policy.policy_version,
        algorithm_name=context.policy.algorithm_name,
        algorithm_version=context.policy.algorithm_version,
        params_hash=context.policy.params_hash,
        definition_hash=context.policy.definition_hash,
        target_schema_version=context.policy.target_schema_version,
        target_intent=draft.target_intent,
        target_position_ratio=draft.target_position_ratio,
        target_confidence=draft.target_confidence,
        target_reason_code=draft.target_reason_code,
        target_reason_summary_zh=draft.target_reason_summary_zh,
        decision_calculation_snapshot=_json_ready(draft.decision_calculation_snapshot),
        input_snapshot=_json_ready(draft.input_snapshot),
        evidence_summary=_json_ready(draft.evidence_summary),
        market_as_of_utc=quality.market_as_of_utc or signal.analysis_close_time_utc,
        analysis_close_time_utc=signal.analysis_close_time_utc,
        expires_at_utc=draft.expires_at_utc,
        status=draft.status,
        is_usable=draft.is_usable,
        allows_order_plan=draft.allows_order_plan,
        blocked_reason=draft.blocked_reason,
        error_code=draft.error_code,
        error_message=draft.error_message,
        trace_id=trace_id,
        trigger_source=trigger_source,
    )


def _write_snapshot_alert(snapshot: DecisionSnapshot, *, business_request_key: str, trace_id: str, trigger_source: str) -> None:
    if snapshot.status == AnalysisObjectStatus.CREATED:
        return
    event_type = "decision_snapshot_failed" if snapshot.status == AnalysisObjectStatus.FAILED else "decision_snapshot_blocked"
    record_alert_event(
        event_key=build_idempotency_key(event_type, business_request_key, snapshot.decision_snapshot_key),
        source_module="DecisionSnapshot",
        event_type=event_type,
        event_category="strategy_analysis",
        severity=AlertSeverity.HIGH,
        title_zh="DecisionSnapshot 目标仓位快照异常",
        message_zh=snapshot.error_message or snapshot.target_reason_summary_zh or "DecisionSnapshot 未形成可用目标仓位意图。",
        trace_id=trace_id,
        trigger_source=trigger_source,
        related_object_type="DecisionSnapshot",
        related_object_id=str(snapshot.id),
        business_status=snapshot.status,
        reason_code=snapshot.error_code or snapshot.blocked_reason,
        payload_summary=_model_data(snapshot),
    )


def _persist_or_recover(
    *,
    context: DecisionContext,
    draft: DecisionDraft,
    snapshot_key: str,
    business_request_key: str,
    trace_id: str,
    trigger_source: str,
) -> tuple[DecisionSnapshot | None, ServiceResult | None]:
    try:
        with transaction.atomic():
            snapshot = _persist_snapshot(
                context=context,
                draft=draft,
                snapshot_key=snapshot_key,
                business_request_key=business_request_key,
                trace_id=trace_id,
                trigger_source=trigger_source,
            )
            _write_snapshot_alert(snapshot, business_request_key=business_request_key, trace_id=trace_id, trigger_source=trigger_source)
        return snapshot, None
    except IntegrityError:
        try:
            by_request = DecisionSnapshot.objects.filter(business_request_key=business_request_key).first()
            by_key = DecisionSnapshot.objects.filter(decision_snapshot_key=snapshot_key).first()
        except DatabaseError:
            return None, _result_with_alert(
                status=ResultStatus.UNKNOWN,
                reason_code="decision_snapshot_persist_unknown",
                message="DecisionSnapshot 写入结果无法确认",
                business_request_key=business_request_key,
                trace_id=trace_id,
                trigger_source=trigger_source,
                dry_run=False,
                quality_result_id=context.quality_result.id,
            )
        if by_request is not None:
            if not _snapshot_matches_request(
                by_request,
                quality_result_id=context.quality_result.id,
                release_id=context.policy_slice.release.id,
                release_hash=context.policy_slice.release.release_hash,
            ):
                return None, _result_with_alert(
                    status=ResultStatus.BLOCKED,
                    reason_code="decision_snapshot_idempotency_conflict",
                    message="business_request_key 已被另一份 DecisionSnapshot 请求使用",
                    business_request_key=business_request_key,
                    trace_id=trace_id,
                    trigger_source=trigger_source,
                    dry_run=False,
                    quality_result_id=context.quality_result.id,
                )
            return by_request, None
        if by_key is not None:
            return by_key, None
        return None, _result_with_alert(
            status=ResultStatus.FAILED,
            reason_code="decision_snapshot_persist_failed",
            message="DecisionSnapshot 写入被数据库明确拒绝",
            business_request_key=business_request_key,
            trace_id=trace_id,
            trigger_source=trigger_source,
            dry_run=False,
            quality_result_id=context.quality_result.id,
        )
    except DataError as exc:
        return None, _result_with_alert(
            status=ResultStatus.FAILED,
            reason_code="decision_snapshot_persist_failed",
            message=f"DecisionSnapshot 数据不满足存储合同：{exc}",
            business_request_key=business_request_key,
            trace_id=trace_id,
            trigger_source=trigger_source,
            dry_run=False,
            quality_result_id=context.quality_result.id,
        )
    except DatabaseError:
        logger.exception("DecisionSnapshot 写入失败 trace_id=%s", trace_id)
        return None, _result_with_alert(
            status=ResultStatus.UNKNOWN,
            reason_code="decision_snapshot_persist_unknown",
            message="DecisionSnapshot 写入结果无法确认",
            business_request_key=business_request_key,
            trace_id=trace_id,
            trigger_source=trigger_source,
            dry_run=False,
            quality_result_id=context.quality_result.id,
        )


def _load_decision_context(
    *,
    strategy_signal_quality_result_id: int,
    strategy_analysis_release_id: int,
    strategy_analysis_release_hash: str,
    business_request_key: str,
    trace_id: str,
    trigger_source: str,
    dry_run: bool,
    registry: CalculatorRegistry,
) -> tuple[DecisionContext | None, ServiceResult | None]:
    quality_result, quality_error = _load_quality_result(strategy_signal_quality_result_id)
    if quality_result is None:
        return None, _result_with_alert(
            status=ResultStatus.BLOCKED,
            reason_code=quality_error,
            message="StrategySignalQualityResult 不存在，DecisionSnapshot fail-closed",
            business_request_key=business_request_key,
            trace_id=trace_id,
            trigger_source=trigger_source,
            dry_run=dry_run,
            quality_result_id=strategy_signal_quality_result_id,
        )
    precondition_error = _precondition_error(
        quality_result,
        release_id=strategy_analysis_release_id,
        release_hash=strategy_analysis_release_hash,
    )
    if precondition_error:
        return None, _result_with_alert(
            status=ResultStatus.BLOCKED,
            reason_code=precondition_error,
            message="质量结果不满足 DecisionSnapshot 正式消费条件",
            business_request_key=business_request_key,
            trace_id=trace_id,
            trigger_source=trigger_source,
            dry_run=dry_run,
            quality_result_id=strategy_signal_quality_result_id,
        )
    policy, policy_slice, policy_error = _load_decision_policy(
        release_id=strategy_analysis_release_id,
        release_hash=strategy_analysis_release_hash,
        registry=registry,
    )
    if policy is None or policy_slice is None:
        return None, _result_with_alert(
            status=ResultStatus.BLOCKED,
            reason_code=policy_error,
            message="DecisionPolicyDefinition 不满足正式目标仓位决策条件",
            business_request_key=business_request_key,
            trace_id=trace_id,
            trigger_source=trigger_source,
            dry_run=dry_run,
            quality_result_id=strategy_signal_quality_result_id,
        )
    return DecisionContext(quality_result=quality_result, policy=policy, policy_slice=policy_slice), None


def _dry_run_result(
    *,
    context: DecisionContext,
    draft: DecisionDraft,
    snapshot_key: str,
    trace_id: str,
    trigger_source: str,
) -> ServiceResult:
    status = ResultStatus.SUCCEEDED if draft.status == AnalysisObjectStatus.CREATED else ResultStatus.FAILED
    return ServiceResult(
        status,
        "decision_snapshot_dry_run",
        "DecisionSnapshot dry-run 已完成，未写入正式业务对象",
        trace_id,
        trigger_source,
        {
            **_empty_result_data(quality_result_id=context.quality_result.id),
            "decision_snapshot_key": snapshot_key,
            "strategy_signal_id": context.quality_result.strategy_signal_id,
            "decision_policy_definition_id": context.policy.id,
            "strategy_analysis_release_id": context.policy_slice.release.id,
            "strategy_analysis_release_hash": context.policy_slice.release.release_hash,
            "target_intent": draft.target_intent,
            "target_position_ratio": draft.target_position_ratio,
            "target_confidence": draft.target_confidence,
            "is_usable": False,
            "allows_order_plan": False,
            "error_code": draft.error_code,
            "error_message": draft.error_message,
            "persisted": False,
        },
    )


def build_decision_snapshot(
    *,
    strategy_signal_quality_result_id: int,
    strategy_analysis_release_id: int,
    strategy_analysis_release_hash: str,
    business_request_key: str,
    trace_id: str,
    trigger_source: str,
    dry_run: bool = False,
    registry: CalculatorRegistry = default_registry,
) -> ServiceResult:
    error, message = _validate_request(
        strategy_signal_quality_result_id=strategy_signal_quality_result_id,
        strategy_analysis_release_id=strategy_analysis_release_id,
        strategy_analysis_release_hash=strategy_analysis_release_hash,
        business_request_key=business_request_key,
        trace_id=trace_id,
        trigger_source=trigger_source,
    )
    if error:
        return _result_with_alert(
            status=ResultStatus.BLOCKED,
            reason_code=error,
            message=message,
            business_request_key=business_request_key or "invalid-decision-snapshot-request",
            trace_id=trace_id,
            trigger_source=trigger_source,
            dry_run=dry_run,
            quality_result_id=strategy_signal_quality_result_id if strategy_signal_quality_result_id > 0 else None,
        )
    if not dry_run:
        existing = DecisionSnapshot.objects.filter(business_request_key=business_request_key).first()
        if existing is not None:
            if not _snapshot_matches_request(
                existing,
                quality_result_id=strategy_signal_quality_result_id,
                release_id=strategy_analysis_release_id,
                release_hash=strategy_analysis_release_hash,
            ):
                return _result_with_alert(
                    status=ResultStatus.BLOCKED,
                    reason_code="decision_snapshot_idempotency_conflict",
                    message="business_request_key 已被另一份 DecisionSnapshot 请求使用",
                    business_request_key=business_request_key,
                    trace_id=trace_id,
                    trigger_source=trigger_source,
                    dry_run=False,
                    quality_result_id=strategy_signal_quality_result_id,
                )
            return _snapshot_result(existing, trace_id=trace_id, trigger_source=trigger_source)
    context, context_error = _load_decision_context(
        strategy_signal_quality_result_id=strategy_signal_quality_result_id,
        strategy_analysis_release_id=strategy_analysis_release_id,
        strategy_analysis_release_hash=strategy_analysis_release_hash,
        business_request_key=business_request_key,
        trace_id=trace_id,
        trigger_source=trigger_source,
        dry_run=dry_run,
        registry=registry,
    )
    if context_error is not None:
        return context_error
    assert context is not None
    draft = _calculate_draft(context=context, registry=registry)
    snapshot_key = _decision_snapshot_key(context, draft)
    if not dry_run:
        existing_by_key = DecisionSnapshot.objects.filter(decision_snapshot_key=snapshot_key).first()
        if existing_by_key is not None:
            return _snapshot_result(existing_by_key, trace_id=trace_id, trigger_source=trigger_source)
    if dry_run:
        return _dry_run_result(context=context, draft=draft, snapshot_key=snapshot_key, trace_id=trace_id, trigger_source=trigger_source)
    snapshot, persist_result = _persist_or_recover(
        context=context,
        draft=draft,
        snapshot_key=snapshot_key,
        business_request_key=business_request_key,
        trace_id=trace_id,
        trigger_source=trigger_source,
    )
    if persist_result is not None:
        return persist_result
    assert snapshot is not None
    return _snapshot_result(snapshot, trace_id=trace_id, trigger_source=trigger_source)
