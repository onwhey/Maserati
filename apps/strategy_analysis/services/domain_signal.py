"""StrategyAnalysis 模块：由 AtomicSignalSet 生成 DomainSignal 事实。

负责：读取同一版本包冻结选择的 DomainSignalDefinition，消费已落库 AtomicSignalValue，
生成 DomainSignalSet / DomainSignalValue，并写入必要 AlertEvent。
不负责：读取 FeatureValue / Kline、重新计算 AtomicSignal、识别 MarketRegime、选择策略、
生成目标仓位、访问 Redis、访问 Binance/DeepSeek、发送 Hermes、交易执行或真实交易。
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
    domain_atomic_membership_hash,
    domain_signal_definition_hash,
    normalize_atomic_signal_codes,
)
from ..models import (
    AnalysisObjectStatus,
    AtomicSignalDirection,
    AtomicSignalSet,
    AtomicSignalValue,
    DefinitionLifecycleStatus,
    DomainSignalDefinition,
    DomainSignalOutputMode,
    DomainSignalSet,
    DomainSignalValue,
    ReleaseItemComponentType,
)
from .release import FrozenReleaseSlice, resolve_frozen_slice


logger = logging.getLogger(__name__)

REQUIRED_FORMAL_DOMAIN_CODES = frozenset({"trend", "momentum", "volatility"})


@dataclass(frozen=True)
class DomainValueDraft:
    definition: DomainSignalDefinition
    status: str
    is_valid: bool
    direction: str
    state_code: str
    strength: Decimal
    coverage_ratio: Decimal
    agreement_ratio: Decimal | None
    evidence_items: list[dict[str, Any]]
    evidence_text_zh: str
    used_atomic_signal_codes: list[str]
    used_atomic_signal_value_ids: list[int]
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
            event_type = "domain_signal_blocked"
            severity = AlertSeverity.WARNING
        elif status == ResultStatus.UNKNOWN:
            event_type = "domain_signal_set_unknown"
            severity = AlertSeverity.HIGH
        else:
            event_type = "domain_signal_set_failed"
            severity = AlertSeverity.HIGH
        try:
            record_alert_event(
                event_key=build_idempotency_key(event_type, business_request_key, reason_code),
                source_module="DomainSignal",
                event_type=event_type,
                event_category="strategy_analysis",
                severity=severity,
                title_zh=f"DomainSignal：{reason_code}",
                message_zh=message,
                trace_id=trace_id,
                trigger_source=trigger_source,
                business_status=status.value,
                reason_code=reason_code,
                payload_summary=payload_summary or {},
            )
        except DatabaseError:
            logger.exception("DomainSignal AlertEvent 写入失败 reason_code=%s trace_id=%s", reason_code, trace_id)
    return ServiceResult(status, reason_code, message, trace_id, trigger_source)


def _decimal_ratio(value: Any, *, field_name: str, allow_none: bool = False) -> Decimal | None:
    if value is None:
        if allow_none:
            return None
        raise InvalidCalculatorContractError(f"{field_name} 不能为空")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise InvalidCalculatorContractError(f"{field_name} 不是合法 Decimal") from exc
    if not result.is_finite() or result < 0 or result > 1:
        raise InvalidCalculatorContractError(f"{field_name} 必须位于 0 到 1")
    return result


def _domain_definition_payload(definition: DomainSignalDefinition) -> tuple[dict[str, list[str]], str]:
    allowed_codes = normalize_atomic_signal_codes(definition.allowed_atomic_signal_codes)
    required_codes = normalize_atomic_signal_codes(definition.required_atomic_signal_codes)
    payload = {
        "allowed_atomic_signal_codes": list(allowed_codes),
        "required_atomic_signal_codes": list(required_codes),
    }
    return payload, domain_atomic_membership_hash(payload)


def _definition_identity_valid(definition: DomainSignalDefinition, item: Any) -> bool:
    try:
        payload, dependency_hash = _domain_definition_payload(definition)
        params_hash = stable_hash(definition.params)
        definition_hash = domain_signal_definition_hash(
            domain_code=definition.domain_code,
            output_mode=definition.output_mode,
            algorithm_name=definition.algorithm_name,
            algorithm_version=definition.algorithm_version,
            params_hash=params_hash,
            is_required=definition.is_required,
            allowed_atomic_signal_codes=payload["allowed_atomic_signal_codes"],
            required_atomic_signal_codes=payload["required_atomic_signal_codes"],
            minimum_coverage_ratio=definition.minimum_coverage_ratio,
            agreement_threshold=definition.agreement_threshold,
        )
    except ValueError:
        return False
    return (
        item.component_code == definition.domain_code
        and item.algorithm_name == definition.algorithm_name
        and item.algorithm_version == definition.algorithm_version
        and definition.params_hash == params_hash
        and item.params_hash == params_hash
        and definition.definition_hash == definition_hash
        and item.definition_hash == definition_hash
        and item.dependency_hash == dependency_hash
        and item.dependency_hash == domain_atomic_membership_hash(item.payload_summary or {})
    )


def _load_domain_definitions(
    *,
    frozen_slice: FrozenReleaseSlice,
    atomic_signal_set: AtomicSignalSet,
    domain_schema_version: str,
    dry_run: bool,
    registry: CalculatorRegistry,
) -> tuple[dict[int, DomainSignalDefinition] | None, str]:
    if not frozen_slice.items:
        return None, "domain_signal_definition_slice_empty"
    if any(item.component_object_id is None for item in frozen_slice.items):
        return None, "domain_signal_definition_object_missing"

    definitions = {
        definition.id: definition
        for definition in DomainSignalDefinition.objects.filter(
            id__in=[item.component_object_id for item in frozen_slice.items]
        )
    }
    if len(definitions) != len(frozen_slice.items):
        return None, "domain_signal_definition_missing"

    domain_codes = [item.component_code for item in frozen_slice.items]
    if len(set(domain_codes)) != len(domain_codes):
        return None, "domain_signal_code_duplicate"
    if not REQUIRED_FORMAL_DOMAIN_CODES.issubset(set(domain_codes)):
        return None, "domain_signal_required_domain_missing"

    release_atomic_codes = set(
        atomic_signal_set.strategy_analysis_release.items.filter(
            component_type=ReleaseItemComponentType.ATOMIC_SIGNAL_DEFINITION
        ).values_list("component_code", flat=True)
    )
    if not release_atomic_codes:
        return None, "domain_signal_release_atomic_slice_empty"

    memberships: dict[str, int] = {code: 0 for code in release_atomic_codes}
    for item in frozen_slice.items:
        definition = definitions[item.component_object_id]
        if definition.status != DefinitionLifecycleStatus.ACTIVE or not definition.enabled:
            return None, "domain_signal_definition_not_selectable"
        if not _definition_identity_valid(definition, item):
            return None, "domain_signal_definition_identity_mismatch"

        payload, _dependency_hash = _domain_definition_payload(definition)
        allowed_codes = set(payload["allowed_atomic_signal_codes"])
        required_codes = set(payload["required_atomic_signal_codes"])
        if not required_codes.issubset(allowed_codes):
            return None, "domain_signal_required_atomic_not_allowed"
        if not allowed_codes.issubset(release_atomic_codes):
            return None, "domain_signal_release_atomic_dependency_missing"
        for code in allowed_codes:
            memberships[code] = memberships.get(code, 0) + 1

        try:
            calculator = registry.resolve(
                calculator_type=CalculatorType.DOMAIN_SIGNAL,
                algorithm_name=definition.algorithm_name,
                algorithm_version=definition.algorithm_version,
            )
        except StrategyCalculatorError:
            return None, "domain_signal_calculator_missing"
        if calculator.metadata.output_schema_version != domain_schema_version:
            return None, "domain_signal_calculator_schema_mismatch"
        if dry_run and not calculator.metadata.supports_dry_run:
            return None, "domain_signal_calculator_dry_run_unsupported"

    if any(count != 1 for count in memberships.values()):
        return None, "domain_signal_atomic_membership_invalid"
    return definitions, ""


def _atomic_value_map(atomic_signal_set: AtomicSignalSet) -> tuple[dict[str, AtomicSignalValue] | None, str]:
    atomic_values = list(
        atomic_signal_set.values.select_related("atomic_signal_definition").order_by("signal_code", "id")
    )
    if len(atomic_values) != atomic_signal_set.computed_count:
        return None, "atomic_signal_value_set_incomplete"
    mapping = {value.signal_code: value for value in atomic_values}
    if len(mapping) != len(atomic_values):
        return None, "atomic_signal_value_code_duplicate"
    if any(value.atomic_signal_set_id != atomic_signal_set.id for value in atomic_values):
        return None, "atomic_signal_value_source_mixed"
    return mapping, ""


def _failed_draft(
    definition: DomainSignalDefinition,
    *,
    error_code: str,
    error_message: str,
    used_values: list[AtomicSignalValue],
    latency_ms: int = 0,
) -> DomainValueDraft:
    return DomainValueDraft(
        definition=definition,
        status=AnalysisObjectStatus.FAILED,
        is_valid=False,
        direction=AtomicSignalDirection.NONE if definition.output_mode == DomainSignalOutputMode.STATE else AtomicSignalDirection.NEUTRAL,
        state_code="",
        strength=Decimal("0"),
        coverage_ratio=Decimal("0"),
        agreement_ratio=None,
        evidence_items=[],
        evidence_text_zh=f"领域信号计算失败：{error_message}"[:1000],
        used_atomic_signal_codes=[value.signal_code for value in used_values],
        used_atomic_signal_value_ids=[value.id for value in used_values],
        error_code=error_code,
        error_message=error_message[:500],
        latency_ms=latency_ms,
    )


def _atomic_payload(value: AtomicSignalValue) -> dict[str, Any]:
    return {
        "atomic_signal_value_id": value.id,
        "signal_code": value.signal_code,
        "direction": value.direction,
        "strength": value.strength,
        "is_valid": value.is_valid,
        "status": value.status,
        "value_bool": value.value_bool,
        "value_decimal": value.value_decimal,
        "value_text": value.value_text,
        "value_json": value.value_json,
    }


def _run_calculator(
    *,
    definition: DomainSignalDefinition,
    atomic_values: list[AtomicSignalValue],
    atomic_signal_set: AtomicSignalSet,
    domain_schema_version: str,
    registry: CalculatorRegistry,
) -> DomainValueDraft:
    payload, _dependency_hash = _domain_definition_payload(definition)
    required_codes = set(payload["required_atomic_signal_codes"])
    invalid_required = [
        value
        for value in atomic_values
        if value.signal_code in required_codes and (value.status != AnalysisObjectStatus.CREATED or not value.is_valid)
    ]
    if invalid_required:
        return _failed_draft(
            definition,
            error_code="required_atomic_signal_invalid",
            error_message="必要原子信号无效，无法形成领域事实",
            used_values=atomic_values,
        )

    valid_values = [
        value
        for value in atomic_values
        if value.status == AnalysisObjectStatus.CREATED and value.is_valid
    ]
    coverage_ratio = Decimal(len(valid_values)) / Decimal(len(payload["allowed_atomic_signal_codes"]))
    if coverage_ratio < definition.minimum_coverage_ratio:
        return _failed_draft(
            definition,
            error_code="domain_signal_coverage_below_minimum",
            error_message="领域有效原子证据覆盖率低于定义阈值",
            used_values=atomic_values,
        )

    started = perf_counter()
    try:
        calculator = registry.resolve(
            calculator_type=CalculatorType.DOMAIN_SIGNAL,
            algorithm_name=definition.algorithm_name,
            algorithm_version=definition.algorithm_version,
        )
        calculation_input = CalculatorInput(
            calculator_type=CalculatorType.DOMAIN_SIGNAL,
            input_schema_version=calculator.metadata.input_schema_version,
            output_schema_version=domain_schema_version,
            upstream_refs={
                "atomic_signal_set_id": atomic_signal_set.id,
                "domain_signal_definition_id": definition.id,
                "atomic_signal_value_ids": [value.id for value in valid_values],
            },
            business_time_utc=atomic_signal_set.analysis_close_time_utc,
            market_identity={
                "exchange": atomic_signal_set.exchange,
                "market_type": atomic_signal_set.market_type,
                "symbol": atomic_signal_set.symbol,
            },
            frozen_params=definition.params,
            params_hash=definition.params_hash,
            values={
                "domain_code": definition.domain_code,
                "output_mode": definition.output_mode,
                "atomic_values": [_atomic_payload(value) for value in valid_values],
            },
            evidence_summary={"definition_hash": definition.definition_hash},
        )
        output = calculator.calculate(calculation_input)
        latency_ms = max(0, int((perf_counter() - started) * 1000))
        if not isinstance(output, CalculatorOutput):
            raise InvalidCalculatorContractError("calculator 必须返回 CalculatorOutput")
        if output.output_schema_version != domain_schema_version:
            raise InvalidCalculatorContractError("calculator 输出 schema 不匹配")
        if output.calculation_status == CalculationStatus.FAILED:
            return _failed_draft(
                definition,
                error_code=output.error_code,
                error_message=output.error_message,
                used_values=atomic_values,
                latency_ms=latency_ms,
            )

        values = thaw_value(output.values)
        direction = values.get("direction")
        state_code = str(values.get("state_code", ""))
        if direction not in AtomicSignalDirection.values:
            raise InvalidCalculatorContractError("领域 direction 不合法")
        if definition.output_mode == DomainSignalOutputMode.DIRECTIONAL and direction == AtomicSignalDirection.NONE:
            raise InvalidCalculatorContractError("directional 领域不得输出 none")
        if definition.output_mode == DomainSignalOutputMode.STATE and (direction != AtomicSignalDirection.NONE or not state_code):
            raise InvalidCalculatorContractError("state 领域必须 direction=none 且 state_code 非空")

        strength = _decimal_ratio(values.get("strength"), field_name="strength")
        output_coverage = _decimal_ratio(values.get("coverage_ratio"), field_name="coverage_ratio")
        agreement = _decimal_ratio(values.get("agreement_ratio"), field_name="agreement_ratio", allow_none=True)
        if strength is None or output_coverage is None:
            raise InvalidCalculatorContractError("领域强度或覆盖率不能为空")
        if output_coverage != coverage_ratio:
            raise InvalidCalculatorContractError("calculator 输出 coverage_ratio 与业务覆盖率不一致")

        evidence_items = _json_ready(output.evidence_items)
        evidence_text_zh = values.get("evidence_text_zh")
        if not evidence_items or not isinstance(evidence_text_zh, str) or not evidence_text_zh.strip():
            raise InvalidCalculatorContractError("领域信号证据不完整")
        return DomainValueDraft(
            definition=definition,
            status=AnalysisObjectStatus.CREATED,
            is_valid=True,
            direction=str(direction),
            state_code=state_code[:80],
            strength=strength,
            coverage_ratio=coverage_ratio,
            agreement_ratio=agreement,
            evidence_items=evidence_items,
            evidence_text_zh=evidence_text_zh[:1000],
            used_atomic_signal_codes=[value.signal_code for value in valid_values],
            used_atomic_signal_value_ids=[value.id for value in valid_values],
            latency_ms=latency_ms,
        )
    except Exception as exc:
        latency_ms = max(0, int((perf_counter() - started) * 1000))
        error_code = (
            "domain_signal_contract_invalid"
            if isinstance(exc, StrategyCalculatorError)
            else "domain_signal_unexpected_error"
        )
        return _failed_draft(
            definition,
            error_code=error_code,
            error_message=f"{type(exc).__name__}: {exc}",
            used_values=atomic_values,
            latency_ms=latency_ms,
        )


def _domain_set_status(drafts: list[DomainValueDraft]) -> tuple[bool, int, int]:
    invalid_count = sum(not draft.is_valid for draft in drafts)
    valid_count = len(drafts) - invalid_count
    required_failed_count = sum(not draft.is_valid and draft.definition.is_required for draft in drafts)
    return required_failed_count > 0, valid_count, required_failed_count


def _persist_domain_signal_set(
    *,
    atomic_signal_set: AtomicSignalSet,
    frozen_slice: FrozenReleaseSlice,
    domain_signal_set_key: str,
    business_request_key: str,
    domain_schema_version: str,
    drafts: list[DomainValueDraft],
    trace_id: str,
    trigger_source: str,
) -> ServiceResult:
    has_required_failure, valid_count, required_failed_count = _domain_set_status(drafts)
    domain_codes = {draft.definition.domain_code for draft in drafts}
    formal_domains_valid = REQUIRED_FORMAL_DOMAIN_CODES.issubset(
        {draft.definition.domain_code for draft in drafts if draft.is_valid}
    )
    set_failed = has_required_failure or not formal_domains_valid
    set_status = AnalysisObjectStatus.FAILED if set_failed else AnalysisObjectStatus.CREATED
    error_code = ""
    error_message = ""
    if has_required_failure:
        error_code = "required_domain_signal_failed"
        error_message = "至少一个 required 领域信号计算失败"
    elif not formal_domains_valid:
        error_code = "required_formal_domain_missing"
        error_message = "trend、momentum、volatility 三个正式领域结果未全部有效"

    now = timezone.now()
    try:
        with transaction.atomic():
            signal_set = DomainSignalSet.objects.create(
                domain_signal_set_key=domain_signal_set_key,
                business_request_key=business_request_key,
                atomic_signal_set=atomic_signal_set,
                atomic_signal_set_key=atomic_signal_set.atomic_signal_set_key,
                strategy_analysis_release=frozen_slice.release,
                release_hash=frozen_slice.release.release_hash,
                market_snapshot=atomic_signal_set.market_snapshot,
                exchange=atomic_signal_set.exchange,
                market_type=atomic_signal_set.market_type,
                symbol=atomic_signal_set.symbol,
                analysis_close_time_utc=atomic_signal_set.analysis_close_time_utc,
                domain_schema_version=domain_schema_version,
                definition_set_hash=frozen_slice.definition_set_hash,
                status=set_status,
                is_usable=not set_failed,
                allows_market_regime=not set_failed and formal_domains_valid,
                selected_definition_count=len(drafts),
                computed_count=len(drafts),
                valid_count=valid_count,
                invalid_count=len(drafts) - valid_count,
                required_failed_count=required_failed_count,
                payload_summary={
                    "selected_definition_count": len(drafts),
                    "valid_count": valid_count,
                    "invalid_count": len(drafts) - valid_count,
                    "required_failed_count": required_failed_count,
                    "domain_codes": sorted(domain_codes),
                    "definition_set_hash": frozen_slice.definition_set_hash,
                },
                error_code=error_code,
                error_message=error_message,
                trace_id=trace_id,
                trigger_source=trigger_source,
                finished_at_utc=now,
            )
            DomainSignalValue.objects.bulk_create(
                [
                    DomainSignalValue(
                        domain_signal_set=signal_set,
                        domain_signal_definition=draft.definition,
                        domain_code=draft.definition.domain_code,
                        output_mode=draft.definition.output_mode,
                        direction=draft.direction,
                        state_code=draft.state_code,
                        strength=draft.strength,
                        coverage_ratio=draft.coverage_ratio,
                        agreement_ratio=draft.agreement_ratio,
                        status=draft.status,
                        is_valid=draft.is_valid,
                        definition_status=draft.definition.status,
                        definition_enabled=draft.definition.enabled,
                        algorithm_name=draft.definition.algorithm_name,
                        algorithm_version=draft.definition.algorithm_version,
                        params_hash=draft.definition.params_hash,
                        definition_hash=draft.definition.definition_hash,
                        used_atomic_signal_codes=draft.used_atomic_signal_codes,
                        used_atomic_signal_value_ids=draft.used_atomic_signal_value_ids,
                        evidence_items=draft.evidence_items,
                        evidence_text_zh=draft.evidence_text_zh,
                        error_code=draft.error_code,
                        error_message=draft.error_message,
                        calculated_at_utc=now,
                        latency_ms=draft.latency_ms,
                    )
                    for draft in drafts
                ]
            )
    except IntegrityError:
        existing = DomainSignalSet.objects.filter(business_request_key=business_request_key).first()
        if existing is None:
            existing = DomainSignalSet.objects.filter(domain_signal_set_key=domain_signal_set_key).first()
        if existing:
            return _existing_result(existing, trace_id=trace_id, trigger_source=trigger_source)
        return _result_with_alert(
            status=ResultStatus.FAILED,
            reason_code="domain_signal_persistence_conflict",
            message="DomainSignalSet 写入发生非幂等唯一冲突",
            business_request_key=business_request_key,
            trace_id=trace_id,
            trigger_source=trigger_source,
            dry_run=False,
        )
    except DatabaseError:
        existing = DomainSignalSet.objects.filter(business_request_key=business_request_key).first()
        if existing is None:
            existing = DomainSignalSet.objects.filter(domain_signal_set_key=domain_signal_set_key).first()
        if existing:
            return _existing_result(existing, trace_id=trace_id, trigger_source=trigger_source)
        return _result_with_alert(
            status=ResultStatus.UNKNOWN,
            reason_code="domain_signal_persistence_unknown",
            message="无法确认 DomainSignalSet 是否完整落库",
            business_request_key=business_request_key,
            trace_id=trace_id,
            trigger_source=trigger_source,
            dry_run=False,
        )

    _record_calculation_alerts(signal_set, drafts)
    return _existing_result(signal_set, trace_id=trace_id, trigger_source=trigger_source)


def _record_calculation_alerts(signal_set: DomainSignalSet, drafts: list[DomainValueDraft]) -> None:
    try:
        for draft in drafts:
            if draft.is_valid:
                continue
            record_alert_event(
                event_key=build_idempotency_key("domain_signal_failed", signal_set.id, draft.definition.domain_code),
                source_module="DomainSignal",
                event_type="domain_signal_failed",
                event_category="strategy_analysis",
                severity=AlertSeverity.WARNING,
                title_zh="领域信号计算失败",
                message_zh=draft.evidence_text_zh,
                trace_id=signal_set.trace_id,
                trigger_source=signal_set.trigger_source,
                related_object_type="DomainSignalSet",
                related_object_id=str(signal_set.id),
                business_status=draft.status,
                reason_code=draft.error_code,
                payload_summary={"domain_code": draft.definition.domain_code},
            )
        if signal_set.status == AnalysisObjectStatus.FAILED:
            record_alert_event(
                event_key=build_idempotency_key("domain_signal_set_failed", signal_set.id),
                source_module="DomainSignal",
                event_type="domain_signal_set_failed",
                event_category="strategy_analysis",
                severity=AlertSeverity.HIGH,
                title_zh="领域信号集合失败",
                message_zh=signal_set.error_message,
                trace_id=signal_set.trace_id,
                trigger_source=signal_set.trigger_source,
                related_object_type="DomainSignalSet",
                related_object_id=str(signal_set.id),
                business_status=signal_set.status,
                reason_code=signal_set.error_code,
                payload_summary={"valid_count": signal_set.valid_count},
            )
    except DatabaseError:
        logger.exception("DomainSignal 计算告警写入失败 domain_signal_set_id=%s", signal_set.id)


def _existing_result(signal_set: DomainSignalSet, *, trace_id: str, trigger_source: str) -> ServiceResult:
    if signal_set.status == AnalysisObjectStatus.CREATED:
        status = ResultStatus.SUCCEEDED
    elif signal_set.status == AnalysisObjectStatus.UNKNOWN:
        status = ResultStatus.UNKNOWN
    else:
        status = ResultStatus.FAILED
    return ServiceResult(
        status,
        "domain_signal_set_created" if status == ResultStatus.SUCCEEDED else signal_set.error_code or "domain_signal_set_unknown",
        "DomainSignalSet 已创建" if status == ResultStatus.SUCCEEDED else signal_set.error_message or "DomainSignalSet 状态未知",
        trace_id,
        trigger_source,
        {
            "domain_signal_set_id": signal_set.id,
            "domain_signal_set_key": signal_set.domain_signal_set_key,
            "atomic_signal_set_id": signal_set.atomic_signal_set_id,
            "strategy_analysis_release_id": signal_set.strategy_analysis_release_id,
            "strategy_analysis_release_hash": signal_set.release_hash,
            "business_status": signal_set.status,
            "computed_count": signal_set.computed_count,
            "valid_count": signal_set.valid_count,
            "invalid_count": signal_set.invalid_count,
            "required_failed_count": signal_set.required_failed_count,
            "allows_market_regime": signal_set.allows_market_regime,
            "persisted": True,
        },
    )


def _load_atomic_signal_set_for_domain(
    *,
    atomic_signal_set_id: int,
    strategy_analysis_release_id: int,
    release_hash: str,
    business_request_key: str,
    trace_id: str,
    trigger_source: str,
    dry_run: bool,
) -> AtomicSignalSet | ServiceResult:
    try:
        atomic_signal_set = AtomicSignalSet.objects.select_related(
            "market_snapshot",
            "strategy_analysis_release",
        ).get(id=atomic_signal_set_id)
    except AtomicSignalSet.DoesNotExist:
        return _result_with_alert(
            status=ResultStatus.BLOCKED,
            reason_code="atomic_signal_set_missing",
            message="AtomicSignalSet 不存在",
            business_request_key=business_request_key,
            trace_id=trace_id,
            trigger_source=trigger_source,
            dry_run=dry_run,
        )
    if (
        atomic_signal_set.status != AnalysisObjectStatus.CREATED
        or not atomic_signal_set.is_usable
        or not atomic_signal_set.allows_domain_signal
    ):
        return _result_with_alert(
            status=ResultStatus.BLOCKED,
            reason_code="atomic_signal_set_not_consumable",
            message="AtomicSignalSet 不允许进入 DomainSignal",
            business_request_key=business_request_key,
            trace_id=trace_id,
            trigger_source=trigger_source,
            dry_run=dry_run,
        )
    if (
        atomic_signal_set.strategy_analysis_release_id != strategy_analysis_release_id
        or atomic_signal_set.release_hash != release_hash
    ):
        return _result_with_alert(
            status=ResultStatus.BLOCKED,
            reason_code="atomic_signal_set_release_mismatch",
            message="AtomicSignalSet 与本轮冻结版本包不一致",
            business_request_key=business_request_key,
            trace_id=trace_id,
            trigger_source=trigger_source,
            dry_run=dry_run,
        )
    return atomic_signal_set


def build_domain_signals(
    *,
    atomic_signal_set_id: int,
    strategy_analysis_release_id: int,
    release_hash: str,
    expected_definition_set_hash: str,
    business_request_key: str,
    trace_id: str,
    trigger_source: str,
    dry_run: bool = False,
    registry: CalculatorRegistry = default_registry,
) -> ServiceResult:
    existing = DomainSignalSet.objects.filter(business_request_key=business_request_key).first()
    if existing and not dry_run:
        return _existing_result(existing, trace_id=trace_id, trigger_source=trigger_source)

    atomic_signal_set = _load_atomic_signal_set_for_domain(
        atomic_signal_set_id=atomic_signal_set_id,
        strategy_analysis_release_id=strategy_analysis_release_id,
        release_hash=release_hash,
        business_request_key=business_request_key,
        trace_id=trace_id,
        trigger_source=trigger_source,
        dry_run=dry_run,
    )
    if isinstance(atomic_signal_set, ServiceResult):
        return atomic_signal_set

    domain_schema_version = settings.DOMAIN_SIGNAL_SCHEMA_VERSION
    try:
        frozen_slice = resolve_frozen_slice(
            release_id=strategy_analysis_release_id,
            release_hash=release_hash,
            component_type=ReleaseItemComponentType.DOMAIN_SIGNAL_DEFINITION,
            expected_definition_set_hash=expected_definition_set_hash,
        )
    except (ObjectDoesNotExist, ValueError) as exc:
        return _result_with_alert(
            status=ResultStatus.BLOCKED,
            reason_code="domain_signal_release_slice_invalid",
            message="领域信号版本包切片无效",
            business_request_key=business_request_key,
            trace_id=trace_id,
            trigger_source=trigger_source,
            dry_run=dry_run,
            payload_summary={"error": str(exc)},
        )

    definitions, definition_error = _load_domain_definitions(
        frozen_slice=frozen_slice,
        atomic_signal_set=atomic_signal_set,
        domain_schema_version=domain_schema_version,
        dry_run=dry_run,
        registry=registry,
    )
    if definition_error or definitions is None:
        return _result_with_alert(
            status=ResultStatus.BLOCKED,
            reason_code=definition_error,
            message="DomainSignalDefinition 集合或原子归属不完整",
            business_request_key=business_request_key,
            trace_id=trace_id,
            trigger_source=trigger_source,
            dry_run=dry_run,
        )

    atomic_values, atomic_error = _atomic_value_map(atomic_signal_set)
    if atomic_error or atomic_values is None:
        return _result_with_alert(
            status=ResultStatus.BLOCKED,
            reason_code=atomic_error,
            message="AtomicSignalValue 集合不完整",
            business_request_key=business_request_key,
            trace_id=trace_id,
            trigger_source=trigger_source,
            dry_run=dry_run,
        )

    drafts: list[DomainValueDraft] = []
    for item in frozen_slice.items:
        definition = definitions[item.component_object_id]
        payload, _dependency_hash = _domain_definition_payload(definition)
        missing_required = [code for code in payload["required_atomic_signal_codes"] if code not in atomic_values]
        if missing_required:
            drafts.append(
                _failed_draft(
                    definition,
                    error_code="required_atomic_signal_missing",
                    error_message="必要原子信号缺失",
                    used_values=[],
                )
            )
            continue
        allowed_values = [atomic_values[code] for code in payload["allowed_atomic_signal_codes"] if code in atomic_values]
        drafts.append(
            _run_calculator(
                definition=definition,
                atomic_values=allowed_values,
                atomic_signal_set=atomic_signal_set,
                domain_schema_version=domain_schema_version,
                registry=registry,
            )
        )

    has_required_failure, valid_count, required_failed_count = _domain_set_status(drafts)
    formal_domains_valid = REQUIRED_FORMAL_DOMAIN_CODES.issubset(
        {draft.definition.domain_code for draft in drafts if draft.is_valid}
    )
    set_failed = has_required_failure or not formal_domains_valid
    domain_signal_set_key = stable_hash(
        {
            "atomic_signal_set_id": atomic_signal_set.id,
            "atomic_signal_set_key": atomic_signal_set.atomic_signal_set_key,
            "domain_schema_version": domain_schema_version,
            "definition_set_hash": frozen_slice.definition_set_hash,
        }
    )
    existing_by_key = DomainSignalSet.objects.filter(domain_signal_set_key=domain_signal_set_key).first()
    if existing_by_key and not dry_run:
        return _existing_result(existing_by_key, trace_id=trace_id, trigger_source=trigger_source)

    if dry_run:
        return ServiceResult(
            ResultStatus.FAILED if set_failed else ResultStatus.SUCCEEDED,
            "domain_signal_set_dry_run_failed" if set_failed else "domain_signal_set_dry_run_succeeded",
            "DomainSignal dry-run 失败" if set_failed else "DomainSignal dry-run 通过",
            trace_id,
            trigger_source,
            {
                "persisted": False,
                "domain_signal_set_key": domain_signal_set_key,
                "atomic_signal_set_id": atomic_signal_set.id,
                "strategy_analysis_release_id": frozen_slice.release.id,
                "strategy_analysis_release_hash": frozen_slice.release.release_hash,
                "computed_count": len(drafts),
                "valid_count": valid_count,
                "invalid_count": len(drafts) - valid_count,
                "required_failed_count": required_failed_count,
                "allows_market_regime": False,
            },
        )

    return _persist_domain_signal_set(
        atomic_signal_set=atomic_signal_set,
        frozen_slice=frozen_slice,
        domain_signal_set_key=domain_signal_set_key,
        business_request_key=business_request_key,
        domain_schema_version=domain_schema_version,
        drafts=drafts,
        trace_id=trace_id,
        trigger_source=trigger_source,
    )
