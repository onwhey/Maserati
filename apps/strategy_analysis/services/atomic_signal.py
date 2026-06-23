"""StrategyAnalysis 模块：由 FeatureSet 生成 AtomicSignal 事实；读写数据库，不访问 Redis、Kline 或外部服务，不涉及交易执行。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from time import perf_counter
from typing import Any
import logging

from django.conf import settings
from django.core.exceptions import ObjectDoesNotExist
from django.db import DatabaseError, IntegrityError, transaction
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
    atomic_signal_definition_hash,
    atomic_signal_dependency_hash,
    domain_atomic_membership_hash,
    normalize_feature_codes,
)
from ..models import (
    AnalysisObjectStatus,
    AtomicSignalDefinition,
    AtomicSignalDirection,
    AtomicSignalOutputType,
    AtomicSignalSet,
    AtomicSignalValue,
    DefinitionLifecycleStatus,
    FeatureSet,
    FeatureValue,
    FeatureValueType,
    ReleaseItemComponentType,
    StrategyAnalysisReleaseItem,
)
from .release import FrozenReleaseSlice, resolve_frozen_slice


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AtomicValueDraft:
    definition: AtomicSignalDefinition
    status: str
    is_valid: bool
    direction: str
    strength: Decimal
    confidence: Decimal | None
    value_fields: dict[str, Any]
    evidence_items: list[dict[str, Any]]
    evidence_text_zh: str
    used_feature_codes: list[str]
    used_feature_value_ids: list[int]
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


def _result_with_alert(
    *,
    status: ResultStatus,
    reason_code: str,
    message: str,
    business_request_key: str,
    trace_id: str,
    trigger_source: str,
    dry_run: bool,
    payload_summary: dict[str, Any] | None = None,
) -> ServiceResult:
    if not dry_run:
        if status == ResultStatus.BLOCKED:
            event_type = "atomic_signal_blocked"
            severity = AlertSeverity.WARNING
        elif status == ResultStatus.UNKNOWN:
            event_type = "atomic_signal_set_unknown"
            severity = AlertSeverity.HIGH
        else:
            event_type = "atomic_signal_set_failed"
            severity = AlertSeverity.HIGH
        try:
            record_alert_event(
                event_key=build_idempotency_key(event_type, business_request_key, reason_code),
                source_module="AtomicSignal",
                event_type=event_type,
                event_category="strategy_analysis",
                severity=severity,
                title_zh=f"AtomicSignal：{reason_code}",
                message_zh=message,
                trace_id=trace_id,
                trigger_source=trigger_source,
                business_status=status.value,
                reason_code=reason_code,
                payload_summary=payload_summary or {},
            )
        except DatabaseError:
            logger.exception("AtomicSignal AlertEvent 写入失败 reason_code=%s trace_id=%s", reason_code, trace_id)
    return ServiceResult(status, reason_code, message, trace_id, trigger_source)


def _definition_set(
    *,
    frozen_slice: FrozenReleaseSlice,
    signal_schema_version: str,
    dry_run: bool,
    registry: CalculatorRegistry,
) -> tuple[dict[int, AtomicSignalDefinition] | None, str]:
    if not frozen_slice.items:
        return None, "atomic_signal_definition_slice_empty"
    definitions = {
        definition.id: definition
        for definition in AtomicSignalDefinition.objects.filter(
            id__in=[item.component_object_id for item in frozen_slice.items]
        )
    }
    if len(definitions) != len(frozen_slice.items):
        return None, "atomic_signal_definition_missing"

    release = frozen_slice.release
    feature_codes = set(
        release.items.filter(component_type=ReleaseItemComponentType.FEATURE_DEFINITION).values_list(
            "component_code", flat=True
        )
    )
    memberships: dict[str, int] = {}
    domain_items = release.items.filter(component_type=ReleaseItemComponentType.DOMAIN_SIGNAL_DEFINITION)
    for domain_item in domain_items:
        payload = domain_item.payload_summary or {}
        if domain_item.dependency_hash != domain_atomic_membership_hash(payload):
            return None, "atomic_signal_domain_membership_hash_mismatch"
        domain_codes = set(payload.get("allowed_atomic_signal_codes", [])) | set(
            payload.get("required_atomic_signal_codes", [])
        )
        for code in domain_codes:
            memberships[str(code)] = memberships.get(str(code), 0) + 1

    for item in frozen_slice.items:
        definition = definitions[item.component_object_id]
        if definition.status != DefinitionLifecycleStatus.ACTIVE or not definition.enabled:
            return None, "atomic_signal_definition_not_selectable"
        try:
            dependencies = normalize_feature_codes(definition.depends_on_feature_codes)
        except ValueError:
            return None, "atomic_signal_feature_dependency_invalid"
        params_hash = stable_hash(definition.params)
        definition_hash = atomic_signal_definition_hash(
            signal_code=definition.signal_code,
            default_direction=definition.default_direction,
            algorithm_name=definition.algorithm_name,
            algorithm_version=definition.algorithm_version,
            params_hash=params_hash,
            is_required=definition.is_required,
            depends_on_feature_codes=dependencies,
            output_type=definition.output_type,
        )
        if (
            item.component_code != definition.signal_code
            or item.algorithm_name != definition.algorithm_name
            or item.algorithm_version != definition.algorithm_version
            or item.params_hash != params_hash
            or definition.params_hash != params_hash
            or item.definition_hash != definition_hash
            or definition.definition_hash != definition_hash
            or item.dependency_hash != atomic_signal_dependency_hash(dependencies)
        ):
            return None, "atomic_signal_definition_identity_mismatch"
        if not set(dependencies).issubset(feature_codes):
            return None, "atomic_signal_release_feature_dependency_missing"
        if memberships.get(definition.signal_code, 0) != 1:
            return None, "atomic_signal_domain_membership_invalid"
        try:
            calculator = registry.resolve(
                calculator_type=CalculatorType.ATOMIC_SIGNAL,
                algorithm_name=definition.algorithm_name,
                algorithm_version=definition.algorithm_version,
            )
        except StrategyCalculatorError:
            return None, "atomic_signal_calculator_missing"
        if calculator.metadata.output_schema_version != signal_schema_version:
            return None, "atomic_signal_calculator_schema_mismatch"
        if dry_run and not calculator.metadata.supports_dry_run:
            return None, "atomic_signal_calculator_dry_run_unsupported"
    return definitions, ""


def _feature_value_map(feature_set: FeatureSet) -> tuple[dict[str, FeatureValue] | None, str]:
    feature_values = list(feature_set.values.select_related("feature_definition").order_by("feature_code", "id"))
    if len(feature_values) != feature_set.feature_count:
        return None, "feature_value_set_incomplete"
    mapping = {value.feature_code: value for value in feature_values}
    if len(mapping) != len(feature_values):
        return None, "feature_value_code_duplicate"
    if any(value.feature_set_id != feature_set.id for value in feature_values):
        return None, "feature_value_source_mixed"
    return mapping, ""


def _feature_payload(feature_value: FeatureValue) -> Any:
    if feature_value.value_type == FeatureValueType.DECIMAL:
        return feature_value.numeric_value
    if feature_value.value_type == FeatureValueType.BOOLEAN:
        return feature_value.bool_value
    if feature_value.value_type == FeatureValueType.TEXT:
        return feature_value.text_value
    raise InvalidCalculatorContractError(f"不支持的 FeatureValue 类型：{feature_value.value_type}")


def _failed_draft(
    definition: AtomicSignalDefinition,
    *,
    error_code: str,
    error_message: str,
    used_values: list[FeatureValue],
    latency_ms: int = 0,
) -> AtomicValueDraft:
    return AtomicValueDraft(
        definition=definition,
        status=AnalysisObjectStatus.FAILED,
        is_valid=False,
        direction=AtomicSignalDirection.NEUTRAL,
        strength=Decimal("0"),
        confidence=None,
        value_fields={"value_bool": None, "value_decimal": None, "value_text": "", "value_json": None},
        evidence_items=[],
        evidence_text_zh=f"原子信号计算失败：{error_message}"[:1000],
        used_feature_codes=[value.feature_code for value in used_values],
        used_feature_value_ids=[value.id for value in used_values],
        error_code=error_code,
        error_message=error_message[:500],
        latency_ms=latency_ms,
    )


def _decimal_ratio(value: Any, *, field_name: str) -> Decimal | None:
    if value is None:
        return None
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise InvalidCalculatorContractError(f"{field_name} 不是合法 Decimal") from exc
    if not result.is_finite() or result < 0 or result > 1:
        raise InvalidCalculatorContractError(f"{field_name} 必须位于 0 到 1")
    return result


def _finite_decimal(value: Any, *, field_name: str) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise InvalidCalculatorContractError(f"{field_name} 不是合法 Decimal") from exc
    if not result.is_finite():
        raise InvalidCalculatorContractError(f"{field_name} 必须是有限 Decimal")
    return result


def _value_fields(output_type: str, value: Any) -> dict[str, Any]:
    fields = {"value_bool": None, "value_decimal": None, "value_text": "", "value_json": None}
    if output_type == AtomicSignalOutputType.BOOLEAN:
        if not isinstance(value, bool):
            raise InvalidCalculatorContractError("布尔原子信号必须输出 bool")
        fields["value_bool"] = value
    elif output_type == AtomicSignalOutputType.DECIMAL:
        fields["value_decimal"] = _finite_decimal(value, field_name="value")
    elif output_type == AtomicSignalOutputType.TEXT:
        text_value = str(value)
        if len(text_value) > 500:
            raise InvalidCalculatorContractError("原子信号文本结果超过 500 字符")
        fields["value_text"] = text_value
    elif output_type == AtomicSignalOutputType.JSON:
        fields["value_json"] = _json_ready(value)
    else:
        raise InvalidCalculatorContractError("原子信号 output_type 不受支持")
    return fields


def _run_calculator(
    *,
    definition: AtomicSignalDefinition,
    feature_values: list[FeatureValue],
    feature_set: FeatureSet,
    signal_schema_version: str,
    registry: CalculatorRegistry,
) -> AtomicValueDraft:
    invalid_values = [
        value
        for value in feature_values
        if value.status != AnalysisObjectStatus.CREATED or not value.is_valid
    ]
    if invalid_values:
        return _failed_draft(
            definition,
            error_code="feature_value_invalid",
            error_message="依赖特征值无效，无法执行原子判断",
            used_values=feature_values,
        )

    started = perf_counter()
    try:
        calculator = registry.resolve(
            calculator_type=CalculatorType.ATOMIC_SIGNAL,
            algorithm_name=definition.algorithm_name,
            algorithm_version=definition.algorithm_version,
        )
        feature_payload = {
            value.feature_code: {
                "feature_value_id": value.id,
                "value": _feature_payload(value),
                "value_type": value.value_type,
            }
            for value in feature_values
        }
        calculation_input = CalculatorInput(
            calculator_type=CalculatorType.ATOMIC_SIGNAL,
            input_schema_version=calculator.metadata.input_schema_version,
            output_schema_version=signal_schema_version,
            upstream_refs={
                "feature_set_id": feature_set.id,
                "feature_value_ids": [value.id for value in feature_values],
            },
            business_time_utc=feature_set.market_snapshot.analysis_close_time_utc,
            market_identity={
                "exchange": feature_set.market_snapshot.exchange,
                "market_type": feature_set.market_snapshot.market_type,
                "symbol": feature_set.market_snapshot.symbol,
            },
            frozen_params=definition.params,
            params_hash=definition.params_hash,
            values={
                "signal_code": definition.signal_code,
                "default_direction": definition.default_direction,
                "feature_values": feature_payload,
            },
            evidence_summary={"definition_hash": definition.definition_hash},
        )
        output = calculator.calculate(calculation_input)
        latency_ms = max(0, int((perf_counter() - started) * 1000))
        if not isinstance(output, CalculatorOutput):
            raise InvalidCalculatorContractError("calculator 必须返回 CalculatorOutput")
        if output.output_schema_version != signal_schema_version:
            raise InvalidCalculatorContractError("calculator 输出 schema 不匹配")
        if output.calculation_status == CalculationStatus.FAILED:
            return _failed_draft(
                definition,
                error_code=output.error_code,
                error_message=output.error_message,
                used_values=feature_values,
                latency_ms=latency_ms,
            )
        values = thaw_value(output.values)
        direction = values.get("direction")
        if direction not in AtomicSignalDirection.values:
            raise InvalidCalculatorContractError("原子信号 direction 不合法")
        strength = _decimal_ratio(values.get("strength"), field_name="strength")
        confidence = _decimal_ratio(values.get("confidence"), field_name="confidence")
        if strength is None:
            raise InvalidCalculatorContractError("原子信号 strength 不能为空")
        value = values.get("value")
        value_fields = _value_fields(definition.output_type, value)
        if definition.output_type == AtomicSignalOutputType.BOOLEAN:
            expected_direction = definition.default_direction if value is True else AtomicSignalDirection.NEUTRAL
            if direction != expected_direction:
                raise InvalidCalculatorContractError("布尔结果与 direction 不一致")
        evidence_items = _json_ready(output.evidence_items)
        evidence_text_zh = values.get("evidence_text_zh")
        if not evidence_items or not isinstance(evidence_text_zh, str) or not evidence_text_zh.strip():
            raise InvalidCalculatorContractError("原子信号证据不完整")
        return AtomicValueDraft(
            definition=definition,
            status=AnalysisObjectStatus.CREATED,
            is_valid=True,
            direction=str(direction),
            strength=strength,
            confidence=confidence,
            value_fields=value_fields,
            evidence_items=evidence_items,
            evidence_text_zh=evidence_text_zh[:1000],
            used_feature_codes=[value.feature_code for value in feature_values],
            used_feature_value_ids=[value.id for value in feature_values],
            latency_ms=latency_ms,
        )
    except Exception as exc:
        latency_ms = max(0, int((perf_counter() - started) * 1000))
        error_code = "atomic_signal_contract_invalid" if isinstance(exc, StrategyCalculatorError) else "atomic_signal_unexpected_error"
        return _failed_draft(
            definition,
            error_code=error_code,
            error_message=f"{type(exc).__name__}：{exc}",
            used_values=feature_values,
            latency_ms=latency_ms,
        )


def _persist_atomic_signal_set(
    *,
    feature_set: FeatureSet,
    frozen_slice: FrozenReleaseSlice,
    atomic_signal_set_key: str,
    business_request_key: str,
    signal_schema_version: str,
    drafts: list[AtomicValueDraft],
    failure_block_ratio: Decimal,
    trace_id: str,
    trigger_source: str,
) -> ServiceResult:
    invalid_count = sum(not draft.is_valid for draft in drafts)
    valid_count = len(drafts) - invalid_count
    required_failed_count = sum(not draft.is_valid and draft.definition.is_required for draft in drafts)
    failure_ratio = Decimal(invalid_count) / Decimal(len(drafts))
    set_failed = required_failed_count > 0 or failure_ratio >= failure_block_ratio
    set_status = AnalysisObjectStatus.FAILED if set_failed else AnalysisObjectStatus.CREATED
    error_code = ""
    error_message = ""
    if required_failed_count:
        error_code = "required_atomic_signal_failed"
        error_message = "至少一个 required 原子信号计算失败"
    elif failure_ratio >= failure_block_ratio:
        error_code = "atomic_signal_failure_ratio_exceeded"
        error_message = "原子信号失败比例达到阻断阈值"

    now = timezone.now()
    try:
        with transaction.atomic():
            signal_set = AtomicSignalSet.objects.create(
                atomic_signal_set_key=atomic_signal_set_key,
                business_request_key=business_request_key,
                feature_set=feature_set,
                feature_set_key=feature_set.feature_set_key,
                strategy_analysis_release=frozen_slice.release,
                release_hash=frozen_slice.release.release_hash,
                market_snapshot=feature_set.market_snapshot,
                exchange=feature_set.market_snapshot.exchange,
                market_type=feature_set.market_snapshot.market_type,
                symbol=feature_set.market_snapshot.symbol,
                analysis_close_time_utc=feature_set.market_snapshot.analysis_close_time_utc,
                signal_schema_version=signal_schema_version,
                definition_set_hash=frozen_slice.definition_set_hash,
                status=set_status,
                is_usable=not set_failed,
                allows_domain_signal=not set_failed and valid_count > 0,
                selected_definition_count=len(drafts),
                computed_count=len(drafts),
                valid_count=valid_count,
                invalid_count=invalid_count,
                failed_count=invalid_count,
                required_failed_count=required_failed_count,
                failure_ratio=failure_ratio,
                failure_block_ratio=failure_block_ratio,
                payload_summary={
                    "selected_definition_count": len(drafts),
                    "valid_count": valid_count,
                    "failed_count": invalid_count,
                    "failure_ratio": str(failure_ratio),
                    "definition_set_hash": frozen_slice.definition_set_hash,
                },
                error_code=error_code,
                error_message=error_message,
                trace_id=trace_id,
                trigger_source=trigger_source,
                finished_at_utc=now,
            )
            AtomicSignalValue.objects.bulk_create(
                [
                    AtomicSignalValue(
                        atomic_signal_set=signal_set,
                        atomic_signal_definition=draft.definition,
                        signal_code=draft.definition.signal_code,
                        direction=draft.direction,
                        strength=draft.strength,
                        confidence=draft.confidence,
                        status=draft.status,
                        is_valid=draft.is_valid,
                        definition_status=draft.definition.status,
                        definition_enabled=draft.definition.enabled,
                        algorithm_name=draft.definition.algorithm_name,
                        algorithm_version=draft.definition.algorithm_version,
                        params_hash=draft.definition.params_hash,
                        definition_hash=draft.definition.definition_hash,
                        output_type=draft.definition.output_type,
                        evidence_items=draft.evidence_items,
                        evidence_text_zh=draft.evidence_text_zh,
                        used_feature_codes=draft.used_feature_codes,
                        used_feature_value_ids=draft.used_feature_value_ids,
                        error_code=draft.error_code,
                        error_message=draft.error_message,
                        calculated_at_utc=now,
                        latency_ms=draft.latency_ms,
                        **draft.value_fields,
                    )
                    for draft in drafts
                ]
            )
    except IntegrityError:
        existing = AtomicSignalSet.objects.filter(business_request_key=business_request_key).first()
        if existing is None:
            existing = AtomicSignalSet.objects.filter(atomic_signal_set_key=atomic_signal_set_key).first()
        if existing:
            return _existing_result(existing, trace_id=trace_id, trigger_source=trigger_source)
        return _result_with_alert(
            status=ResultStatus.FAILED,
            reason_code="atomic_signal_persistence_conflict",
            message="AtomicSignalSet 写入发生非幂等唯一冲突",
            business_request_key=business_request_key,
            trace_id=trace_id,
            trigger_source=trigger_source,
            dry_run=False,
        )
    except DatabaseError:
        existing = AtomicSignalSet.objects.filter(business_request_key=business_request_key).first()
        if existing is None:
            existing = AtomicSignalSet.objects.filter(atomic_signal_set_key=atomic_signal_set_key).first()
        if existing:
            return _existing_result(existing, trace_id=trace_id, trigger_source=trigger_source)
        return _result_with_alert(
            status=ResultStatus.UNKNOWN,
            reason_code="atomic_signal_persistence_unknown",
            message="无法确认 AtomicSignalSet 是否完整落库",
            business_request_key=business_request_key,
            trace_id=trace_id,
            trigger_source=trigger_source,
            dry_run=False,
        )

    _record_calculation_alerts(signal_set, drafts)
    return _existing_result(signal_set, trace_id=trace_id, trigger_source=trigger_source)


def _record_calculation_alerts(signal_set: AtomicSignalSet, drafts: list[AtomicValueDraft]) -> None:
    try:
        for draft in drafts:
            if draft.is_valid:
                continue
            record_alert_event(
                event_key=build_idempotency_key("atomic_signal_failed", signal_set.id, draft.definition.signal_code),
                source_module="AtomicSignal",
                event_type="atomic_signal_failed",
                event_category="strategy_analysis",
                severity=AlertSeverity.WARNING,
                title_zh="原子信号计算失败",
                message_zh=draft.evidence_text_zh,
                trace_id=signal_set.trace_id,
                trigger_source=signal_set.trigger_source,
                related_object_type="AtomicSignalSet",
                related_object_id=str(signal_set.id),
                business_status=draft.status,
                reason_code=draft.error_code,
                payload_summary={"signal_code": draft.definition.signal_code},
            )
        if signal_set.status == AnalysisObjectStatus.FAILED:
            record_alert_event(
                event_key=build_idempotency_key("atomic_signal_set_failed", signal_set.id),
                source_module="AtomicSignal",
                event_type="atomic_signal_set_failed",
                event_category="strategy_analysis",
                severity=AlertSeverity.HIGH,
                title_zh="原子信号集合失败",
                message_zh=signal_set.error_message,
                trace_id=signal_set.trace_id,
                trigger_source=signal_set.trigger_source,
                related_object_type="AtomicSignalSet",
                related_object_id=str(signal_set.id),
                business_status=signal_set.status,
                reason_code=signal_set.error_code,
                payload_summary={"failure_ratio": str(signal_set.failure_ratio)},
            )
    except DatabaseError:
        logger.exception("AtomicSignal 计算告警写入失败 atomic_signal_set_id=%s", signal_set.id)


def _existing_result(signal_set: AtomicSignalSet, *, trace_id: str, trigger_source: str) -> ServiceResult:
    if signal_set.status == AnalysisObjectStatus.CREATED:
        status = ResultStatus.SUCCEEDED
    elif signal_set.status == AnalysisObjectStatus.UNKNOWN:
        status = ResultStatus.UNKNOWN
    else:
        status = ResultStatus.FAILED
    return ServiceResult(
        status,
        "atomic_signal_set_created" if status == ResultStatus.SUCCEEDED else signal_set.error_code or "atomic_signal_set_unknown",
        "AtomicSignalSet 已创建" if status == ResultStatus.SUCCEEDED else signal_set.error_message or "AtomicSignalSet 状态未知",
        trace_id,
        trigger_source,
        {
            "atomic_signal_set_id": signal_set.id,
            "atomic_signal_set_key": signal_set.atomic_signal_set_key,
            "feature_set_id": signal_set.feature_set_id,
            "strategy_analysis_release_id": signal_set.strategy_analysis_release_id,
            "strategy_analysis_release_hash": signal_set.release_hash,
            "business_status": signal_set.status,
            "computed_count": signal_set.computed_count,
            "valid_count": signal_set.valid_count,
            "invalid_count": signal_set.invalid_count,
            "required_failed_count": signal_set.required_failed_count,
            "failure_ratio": str(signal_set.failure_ratio),
            "allows_domain_signal": signal_set.allows_domain_signal,
            "persisted": True,
        },
    )


def _load_feature_set_for_atomic(
    *,
    feature_set_id: int,
    strategy_analysis_release_id: int,
    release_hash: str,
    business_request_key: str,
    trace_id: str,
    trigger_source: str,
    dry_run: bool,
) -> FeatureSet | ServiceResult:
    try:
        feature_set = FeatureSet.objects.select_related("market_snapshot", "strategy_analysis_release").get(id=feature_set_id)
    except FeatureSet.DoesNotExist:
        return _result_with_alert(
            status=ResultStatus.BLOCKED,
            reason_code="feature_set_missing",
            message="FeatureSet 不存在",
            business_request_key=business_request_key,
            trace_id=trace_id,
            trigger_source=trigger_source,
            dry_run=dry_run,
        )
    if (
        feature_set.status != AnalysisObjectStatus.CREATED
        or not feature_set.is_usable
        or not feature_set.allows_atomic_signal
    ):
        return _result_with_alert(
            status=ResultStatus.BLOCKED,
            reason_code="feature_set_not_consumable",
            message="FeatureSet 不允许进入 AtomicSignal",
            business_request_key=business_request_key,
            trace_id=trace_id,
            trigger_source=trigger_source,
            dry_run=dry_run,
        )
    if (
        feature_set.strategy_analysis_release_id != strategy_analysis_release_id
        or feature_set.release_hash != release_hash
    ):
        return _result_with_alert(
            status=ResultStatus.BLOCKED,
            reason_code="feature_set_release_mismatch",
            message="FeatureSet 与本轮冻结版本包不一致",
            business_request_key=business_request_key,
            trace_id=trace_id,
            trigger_source=trigger_source,
            dry_run=dry_run,
        )
    return feature_set


def build_atomic_signals(
    *,
    feature_set_id: int,
    strategy_analysis_release_id: int,
    release_hash: str,
    expected_definition_set_hash: str,
    business_request_key: str,
    trace_id: str,
    trigger_source: str,
    dry_run: bool = False,
    registry: CalculatorRegistry = default_registry,
) -> ServiceResult:
    existing = AtomicSignalSet.objects.filter(business_request_key=business_request_key).first()
    if existing:
        return _existing_result(existing, trace_id=trace_id, trigger_source=trigger_source)
    feature_set = _load_feature_set_for_atomic(
        feature_set_id=feature_set_id,
        strategy_analysis_release_id=strategy_analysis_release_id,
        release_hash=release_hash,
        business_request_key=business_request_key,
        trace_id=trace_id,
        trigger_source=trigger_source,
        dry_run=dry_run,
    )
    if isinstance(feature_set, ServiceResult):
        return feature_set

    signal_schema_version = settings.SIGNAL_SCHEMA_VERSION
    failure_block_ratio = settings.ATOMIC_SIGNAL_FAILURE_BLOCK_RATIO
    if failure_block_ratio <= 0 or failure_block_ratio > 1:
        return _result_with_alert(
            status=ResultStatus.BLOCKED,
            reason_code="atomic_signal_failure_ratio_config_invalid",
            message="AtomicSignal 失败比例阈值必须大于 0 且不超过 1",
            business_request_key=business_request_key,
            trace_id=trace_id,
            trigger_source=trigger_source,
            dry_run=dry_run,
        )
    try:
        frozen_slice = resolve_frozen_slice(
            release_id=strategy_analysis_release_id,
            release_hash=release_hash,
            component_type=ReleaseItemComponentType.ATOMIC_SIGNAL_DEFINITION,
            expected_definition_set_hash=expected_definition_set_hash,
        )
    except (ObjectDoesNotExist, ValueError) as exc:
        return _result_with_alert(
            status=ResultStatus.BLOCKED,
            reason_code="atomic_signal_release_slice_invalid",
            message="原子信号版本包切片无效",
            business_request_key=business_request_key,
            trace_id=trace_id,
            trigger_source=trigger_source,
            dry_run=dry_run,
            payload_summary={"error": str(exc)},
        )
    definitions, definition_error = _definition_set(
        frozen_slice=frozen_slice,
        signal_schema_version=signal_schema_version,
        dry_run=dry_run,
        registry=registry,
    )
    if definition_error or definitions is None:
        return _result_with_alert(
            status=ResultStatus.BLOCKED,
            reason_code=definition_error,
            message="原子信号定义集合或依赖不完整",
            business_request_key=business_request_key,
            trace_id=trace_id,
            trigger_source=trigger_source,
            dry_run=dry_run,
        )
    feature_values, feature_error = _feature_value_map(feature_set)
    if feature_error or feature_values is None:
        return _result_with_alert(
            status=ResultStatus.BLOCKED,
            reason_code=feature_error,
            message="FeatureValue 集合不完整",
            business_request_key=business_request_key,
            trace_id=trace_id,
            trigger_source=trigger_source,
            dry_run=dry_run,
        )
    for definition in definitions.values():
        dependencies = normalize_feature_codes(definition.depends_on_feature_codes)
        if any(code not in feature_values for code in dependencies):
            return _result_with_alert(
                status=ResultStatus.BLOCKED,
                reason_code="atomic_signal_feature_value_missing",
                message="本轮 FeatureSet 缺少原子信号声明的特征",
                business_request_key=business_request_key,
                trace_id=trace_id,
                trigger_source=trigger_source,
                dry_run=dry_run,
                payload_summary={"signal_code": definition.signal_code},
            )

    atomic_signal_set_key = stable_hash(
        {
            "feature_set_id": feature_set.id,
            "feature_set_key": feature_set.feature_set_key,
            "signal_schema_version": signal_schema_version,
            "definition_set_hash": frozen_slice.definition_set_hash,
        }
    )
    existing_by_key = AtomicSignalSet.objects.filter(atomic_signal_set_key=atomic_signal_set_key).first()
    if existing_by_key:
        return _existing_result(existing_by_key, trace_id=trace_id, trigger_source=trigger_source)

    drafts = [
        _run_calculator(
            definition=definitions[item.component_object_id],
            feature_values=[feature_values[code] for code in normalize_feature_codes(definitions[item.component_object_id].depends_on_feature_codes)],
            feature_set=feature_set,
            signal_schema_version=signal_schema_version,
            registry=registry,
        )
        for item in frozen_slice.items
    ]
    invalid_count = sum(not draft.is_valid for draft in drafts)
    required_failed_count = sum(not draft.is_valid and draft.definition.is_required for draft in drafts)
    failure_ratio = Decimal(invalid_count) / Decimal(len(drafts))
    set_failed = required_failed_count > 0 or failure_ratio >= failure_block_ratio
    if dry_run:
        return ServiceResult(
            ResultStatus.FAILED if set_failed else ResultStatus.SUCCEEDED,
            "atomic_signal_set_dry_run_failed" if set_failed else "atomic_signal_set_dry_run_succeeded",
            "AtomicSignal dry-run 失败" if set_failed else "AtomicSignal dry-run 通过",
            trace_id,
            trigger_source,
            {
                "persisted": False,
                "atomic_signal_set_key": atomic_signal_set_key,
                "feature_set_id": feature_set.id,
                "strategy_analysis_release_id": frozen_slice.release.id,
                "strategy_analysis_release_hash": frozen_slice.release.release_hash,
                "computed_count": len(drafts),
                "valid_count": len(drafts) - invalid_count,
                "invalid_count": invalid_count,
                "required_failed_count": required_failed_count,
                "failure_ratio": str(failure_ratio),
                "allows_domain_signal": False,
            },
        )
    return _persist_atomic_signal_set(
        feature_set=feature_set,
        frozen_slice=frozen_slice,
        atomic_signal_set_key=atomic_signal_set_key,
        business_request_key=business_request_key,
        signal_schema_version=signal_schema_version,
        drafts=drafts,
        failure_block_ratio=failure_block_ratio,
        trace_id=trace_id,
        trigger_source=trigger_source,
    )
