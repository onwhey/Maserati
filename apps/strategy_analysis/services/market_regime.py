"""StrategyAnalysis 模块：由 DomainSignalSet 生成 MarketRegimeSnapshot。

负责：读取同一版本包冻结选择的 MarketRegimeDefinition，消费已落库 DomainSignalValue，生成 MarketRegimeSnapshot，并写必要 AlertEvent。
不负责：读取 AtomicSignalValue / FeatureValue / Kline、重新计算 DomainSignal、选择策略、生成 StrategySignal 或目标仓位、访问 Redis、访问 Binance/DeepSeek、发送 Hermes、交易执行或真实交易。
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
    market_regime_definition_hash,
    market_regime_domain_membership_hash,
    normalize_domain_codes,
    normalize_regime_codes,
)
from ..models import (
    AnalysisObjectStatus,
    DefinitionLifecycleStatus,
    DomainSignalSet,
    DomainSignalSetStatus,
    DomainSignalValue,
    DomainSignalValueStatus,
    MarketRegimeDefinition,
    MarketRegimeSnapshot,
    ReleaseItemComponentType,
)
from .release import FrozenReleaseSlice, resolve_frozen_slice


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class MarketRegimeDraft:
    status: str
    is_usable: bool
    allows_strategy_routing: bool
    regime_code: str
    regime_scores: dict[str, str]
    regime_confidence: Decimal | None
    classification_margin: Decimal | None
    used_domain_signal_codes: list[str]
    used_domain_signal_value_ids: list[int]
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
        event_type = "market_regime_blocked"
        severity = AlertSeverity.WARNING
        if status == ResultStatus.FAILED:
            event_type = "market_regime_failed"
            severity = AlertSeverity.HIGH
        elif status == ResultStatus.UNKNOWN:
            event_type = "market_regime_unknown"
            severity = AlertSeverity.HIGH
        try:
            record_alert_event(
                event_key=build_idempotency_key(event_type, business_request_key, reason_code),
                source_module="MarketRegime",
                event_type=event_type,
                event_category="strategy_analysis",
                severity=severity,
                title_zh=f"MarketRegime：{reason_code}",
                message_zh=message,
                trace_id=trace_id,
                trigger_source=trigger_source,
                business_status=status.value,
                reason_code=reason_code,
                payload_summary=payload_summary or {},
            )
        except DatabaseError:
            logger.exception("MarketRegime AlertEvent 写入失败 reason_code=%s trace_id=%s", reason_code, trace_id)
    return ServiceResult(status, reason_code, message, trace_id, trigger_source, payload_summary or {})


def _validate_request_fields(
    *,
    domain_signal_set_id: int,
    strategy_analysis_release_id: int,
    strategy_analysis_release_hash: str,
    business_request_key: str,
    trace_id: str,
    trigger_source: str,
) -> tuple[str, str]:
    if domain_signal_set_id <= 0:
        return "market_regime_request_invalid", "domain_signal_set_id 必须是正整数"
    if strategy_analysis_release_id <= 0:
        return "market_regime_request_invalid", "strategy_analysis_release_id 必须是正整数"
    required_text = {
        "strategy_analysis_release_hash": strategy_analysis_release_hash,
        "business_request_key": business_request_key,
        "trace_id": trace_id,
        "trigger_source": trigger_source,
    }
    missing = [name for name, value in required_text.items() if not str(value).strip()]
    if missing:
        return "market_regime_request_invalid", f"MarketRegime 请求缺少必要字段：{','.join(missing)}"
    return "", ""


def _snapshot_matches_request(
    snapshot: MarketRegimeSnapshot,
    *,
    domain_signal_set_id: int,
    strategy_analysis_release_id: int,
    strategy_analysis_release_hash: str,
    expected_definition_hash: str,
) -> bool:
    return (
        snapshot.domain_signal_set_id == domain_signal_set_id
        and snapshot.strategy_analysis_release_id == strategy_analysis_release_id
        and snapshot.release_hash == strategy_analysis_release_hash
        and (not expected_definition_hash or snapshot.definition_hash == expected_definition_hash)
    )


def _idempotency_conflict_result(
    *,
    business_request_key: str,
    trace_id: str,
    trigger_source: str,
    dry_run: bool,
    existing_snapshot: MarketRegimeSnapshot,
    requested_domain_signal_set_id: int,
) -> ServiceResult:
    return _result_with_alert(
        status=ResultStatus.BLOCKED,
        reason_code="market_regime_idempotency_conflict",
        message="business_request_key 已被另一份 MarketRegime 业务请求使用",
        business_request_key=business_request_key,
        trace_id=trace_id,
        trigger_source=trigger_source,
        dry_run=dry_run,
        payload_summary={
            "existing_market_regime_snapshot_id": existing_snapshot.id,
            "existing_domain_signal_set_id": existing_snapshot.domain_signal_set_id,
            "requested_domain_signal_set_id": requested_domain_signal_set_id,
        },
    )


def _existing_request_result(
    *,
    domain_signal_set_id: int,
    strategy_analysis_release_id: int,
    strategy_analysis_release_hash: str,
    expected_definition_hash: str,
    business_request_key: str,
    trace_id: str,
    trigger_source: str,
) -> ServiceResult | None:
    existing = MarketRegimeSnapshot.objects.filter(business_request_key=business_request_key).first()
    if existing is None:
        return None
    if not _snapshot_matches_request(
        existing,
        domain_signal_set_id=domain_signal_set_id,
        strategy_analysis_release_id=strategy_analysis_release_id,
        strategy_analysis_release_hash=strategy_analysis_release_hash,
        expected_definition_hash=expected_definition_hash,
    ):
        return _idempotency_conflict_result(
            business_request_key=business_request_key,
            trace_id=trace_id,
            trigger_source=trigger_source,
            dry_run=False,
            existing_snapshot=existing,
            requested_domain_signal_set_id=domain_signal_set_id,
        )
    return _snapshot_result(existing, trace_id=trace_id, trigger_source=trigger_source)


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


def _decimal_value(value: Any, *, field_name: str, allow_none: bool = False) -> Decimal | None:
    if value is None:
        if allow_none:
            return None
        raise InvalidCalculatorContractError(f"{field_name} 不能为空")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise InvalidCalculatorContractError(f"{field_name} 不是合法 Decimal") from exc
    if not result.is_finite():
        raise InvalidCalculatorContractError(f"{field_name} 必须是有限数值")
    return result


def _definition_payload(definition: MarketRegimeDefinition) -> tuple[dict[str, list[str]], str]:
    allowed_domains = normalize_domain_codes(definition.allowed_domain_codes)
    required_domains = normalize_domain_codes(definition.required_domain_codes, allow_empty=True)
    allowed_regimes = normalize_regime_codes(definition.allowed_regime_codes)
    payload = {
        "allowed_domain_codes": list(allowed_domains),
        "required_domain_codes": list(required_domains),
        "allowed_regime_codes": list(allowed_regimes),
    }
    return payload, market_regime_domain_membership_hash(payload)


def _definition_identity_valid(definition: MarketRegimeDefinition, item: Any) -> bool:
    try:
        payload, dependency_hash = _definition_payload(definition)
        params_hash = stable_hash(definition.params)
        definition_hash = market_regime_definition_hash(
            definition_code=definition.definition_code,
            algorithm_name=definition.algorithm_name,
            algorithm_version=definition.algorithm_version,
            input_schema_version=definition.input_schema_version,
            output_schema_version=definition.output_schema_version,
            params_hash=params_hash,
            allowed_domain_codes=payload["allowed_domain_codes"],
            required_domain_codes=payload["required_domain_codes"],
            allowed_regime_codes=payload["allowed_regime_codes"],
        )
    except ValueError:
        return False
    return (
        item.component_code == definition.definition_code
        and item.algorithm_name == definition.algorithm_name
        and item.algorithm_version == definition.algorithm_version
        and definition.params_hash == params_hash
        and item.params_hash == params_hash
        and definition.definition_hash == definition_hash
        and item.definition_hash == definition_hash
        and item.dependency_hash == dependency_hash
        and item.dependency_hash == market_regime_domain_membership_hash(item.payload_summary or {})
    )


def _load_market_regime_definition(
    *,
    frozen_slice: FrozenReleaseSlice,
    expected_definition_hash: str,
    dry_run: bool,
    registry: CalculatorRegistry,
) -> tuple[MarketRegimeDefinition | None, str]:
    if len(frozen_slice.items) != 1:
        return None, "market_regime_definition_unavailable"
    item = frozen_slice.items[0]
    if item.component_object_id is None:
        return None, "market_regime_definition_object_missing"
    definition = MarketRegimeDefinition.objects.filter(id=item.component_object_id).first()
    if definition is None:
        return None, "market_regime_definition_missing"
    if definition.status != DefinitionLifecycleStatus.ACTIVE or not definition.enabled:
        return None, "market_regime_definition_not_selectable"
    if expected_definition_hash and definition.definition_hash != expected_definition_hash:
        return None, "market_regime_definition_hash_mismatch"
    if not _definition_identity_valid(definition, item):
        return None, "market_regime_definition_identity_mismatch"

    payload, _dependency_hash = _definition_payload(definition)
    allowed = set(payload["allowed_domain_codes"])
    required = set(payload["required_domain_codes"])
    if not required.issubset(allowed):
        return None, "market_regime_required_domain_not_allowed"
    release_domain_codes = set(
        frozen_slice.release.items.filter(component_type=ReleaseItemComponentType.DOMAIN_SIGNAL_DEFINITION).values_list(
            "component_code", flat=True
        )
    )
    if not allowed.issubset(release_domain_codes):
        return None, "market_regime_domain_membership_invalid"
    try:
        calculator = registry.resolve(
            calculator_type=CalculatorType.MARKET_REGIME,
            algorithm_name=definition.algorithm_name,
            algorithm_version=definition.algorithm_version,
        )
    except StrategyCalculatorError:
        return None, "market_regime_calculator_missing"
    if (
        calculator.metadata.input_schema_version != definition.input_schema_version
        or calculator.metadata.output_schema_version != definition.output_schema_version
    ):
        return None, "market_regime_calculator_schema_mismatch"
    if dry_run and not calculator.metadata.supports_dry_run:
        return None, "market_regime_calculator_dry_run_unsupported"
    return definition, ""


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
        "evidence_items": _json_ready(value.evidence_items),
    }


def _load_domain_values(
    *,
    domain_signal_set: DomainSignalSet,
    definition: MarketRegimeDefinition,
) -> tuple[list[DomainSignalValue] | None, str]:
    payload, _dependency_hash = _definition_payload(definition)
    allowed_codes = payload["allowed_domain_codes"]
    required_codes = set(payload["required_domain_codes"])
    release_domain_items = {
        item.component_code: item
        for item in domain_signal_set.strategy_analysis_release.items.filter(
            component_type=ReleaseItemComponentType.DOMAIN_SIGNAL_DEFINITION
        )
    }
    values = list(
        DomainSignalValue.objects.filter(
            domain_signal_set=domain_signal_set,
            domain_code__in=allowed_codes,
            status=DomainSignalValueStatus.CREATED,
            is_valid=True,
        ).order_by("domain_code", "id")
    )
    by_code: dict[str, DomainSignalValue] = {}
    for value in values:
        if value.domain_code in by_code:
            return None, "market_regime_domain_value_duplicate"
        item = release_domain_items.get(value.domain_code)
        if item is None or item.definition_hash != value.definition_hash:
            return None, "market_regime_domain_membership_invalid"
        by_code[value.domain_code] = value
    missing = sorted(required_codes - set(by_code))
    if missing:
        return None, "market_regime_required_domain_missing"
    return [by_code[code] for code in allowed_codes if code in by_code], ""


def _snapshot_key(*, domain_signal_set_id: int, schema_version: str, definition_hash: str) -> str:
    return stable_hash(
        {
            "domain_signal_set_id": domain_signal_set_id,
            "market_regime_schema_version": schema_version,
            "definition_hash": definition_hash,
        }
    )


def _build_calculator_input(
    *,
    domain_signal_set: DomainSignalSet,
    definition: MarketRegimeDefinition,
    domain_values: list[DomainSignalValue],
) -> CalculatorInput:
    payload, _dependency_hash = _definition_payload(definition)
    return CalculatorInput(
        calculator_type=CalculatorType.MARKET_REGIME,
        input_schema_version=definition.input_schema_version,
        output_schema_version=definition.output_schema_version,
        upstream_refs={
            "domain_signal_set_id": domain_signal_set.id,
            "domain_signal_value_ids": [value.id for value in domain_values],
        },
        business_time_utc=domain_signal_set.analysis_close_time_utc,
        market_identity={
            "exchange": domain_signal_set.exchange,
            "market_type": domain_signal_set.market_type,
            "symbol": domain_signal_set.symbol,
        },
        frozen_params=definition.params,
        params_hash=definition.params_hash,
        values={
            "domain_values": [_domain_value_payload(value) for value in domain_values],
            "allowed_domain_codes": payload["allowed_domain_codes"],
            "required_domain_codes": payload["required_domain_codes"],
            "allowed_regime_codes": payload["allowed_regime_codes"],
        },
        evidence_summary={
            "definition_code": definition.definition_code,
            "definition_hash": definition.definition_hash,
        },
    )


def _failed_draft(output: CalculatorOutput, *, latency_ms: int) -> MarketRegimeDraft:
    return MarketRegimeDraft(
        status=AnalysisObjectStatus.FAILED,
        is_usable=False,
        allows_strategy_routing=False,
        regime_code="",
        regime_scores={},
        regime_confidence=None,
        classification_margin=None,
        used_domain_signal_codes=[],
        used_domain_signal_value_ids=[],
        evidence_items=[],
        evidence_text_zh="MarketRegime calculator 计算失败。",
        payload_summary={"calculator_error_code": output.error_code},
        error_code=output.error_code,
        error_message=output.error_message,
        latency_ms=latency_ms,
    )


def _validate_output(
    *,
    output: CalculatorOutput,
    definition: MarketRegimeDefinition,
    input_domain_values: list[DomainSignalValue],
    latency_ms: int,
) -> MarketRegimeDraft:
    if output.output_schema_version != definition.output_schema_version:
        raise InvalidCalculatorContractError("MarketRegime 输出 schema 与 Definition 不一致")
    if output.calculation_status == CalculationStatus.FAILED:
        return _failed_draft(output, latency_ms=latency_ms)

    values = thaw_value(output.values)
    allowed_regime_codes = set(normalize_regime_codes(definition.allowed_regime_codes))
    regime_code = str(values.get("regime_code", "")).strip()
    if regime_code not in allowed_regime_codes:
        raise InvalidCalculatorContractError("regime_code 不在 allowed_regime_codes 中")
    raw_scores = values.get("regime_scores")
    if not isinstance(raw_scores, dict) or set(raw_scores) != allowed_regime_codes:
        raise InvalidCalculatorContractError("regime_scores 必须完整覆盖 allowed_regime_codes")
    regime_scores = {
        str(code): str(_decimal_value(score, field_name=f"regime_scores.{code}"))
        for code, score in raw_scores.items()
    }
    confidence = _decimal_ratio(values.get("regime_confidence"), field_name="regime_confidence")
    margin = _decimal_value(values.get("classification_margin"), field_name="classification_margin", allow_none=True)
    input_ids_by_code = {value.domain_code: value.id for value in input_domain_values}
    input_ids = set(input_ids_by_code.values())
    used_ids_raw = values.get("used_domain_signal_value_ids", [])
    if not isinstance(used_ids_raw, list | tuple) or not used_ids_raw:
        raise InvalidCalculatorContractError("used_domain_signal_value_ids 不能为空")
    used_ids = [int(value_id) for value_id in used_ids_raw]
    if len(used_ids) != len(set(used_ids)) or not set(used_ids).issubset(input_ids):
        raise InvalidCalculatorContractError("used_domain_signal_value_ids 必须来自本次输入且不可重复")
    required_codes = set(normalize_domain_codes(definition.required_domain_codes, allow_empty=True))
    required_ids = {input_ids_by_code[code] for code in required_codes if code in input_ids_by_code}
    if not required_ids.issubset(set(used_ids)):
        raise InvalidCalculatorContractError("required domain 必须实际参与分类")
    used_codes = [value.domain_code for value in input_domain_values if value.id in set(used_ids)]
    evidence_text = str(values.get("evidence_text_zh", "")).strip()
    if not evidence_text:
        raise InvalidCalculatorContractError("evidence_text_zh 不能为空")
    calculator_evidence_items = _json_ready(output.evidence_items)
    if not isinstance(calculator_evidence_items, list) or not calculator_evidence_items:
        raise InvalidCalculatorContractError("MarketRegime calculator 必须输出非空结构化证据")
    used_id_set = set(used_ids)
    evidence_items = [
        {
            "evidence_type": "domain_signal_value",
            "domain_signal_value_id": value.id,
            "domain_code": value.domain_code,
            "direction": value.direction,
            "state_code": value.state_code,
            "strength": str(value.strength),
            "coverage_ratio": str(value.coverage_ratio),
            "agreement_ratio": str(value.agreement_ratio) if value.agreement_ratio is not None else None,
        }
        for value in input_domain_values
        if value.id in used_id_set
    ]
    evidence_items.append(
        {
            "evidence_type": "market_regime_classification",
            "regime_code": regime_code,
            "regime_scores": regime_scores,
            "regime_confidence": str(confidence),
            "classification_margin": str(margin) if margin is not None else None,
        }
    )
    evidence_items.extend(
        {"evidence_type": "calculator_output", "payload": item} for item in calculator_evidence_items
    )
    payload_summary = {
        "regime_code": regime_code,
        "regime_scores": regime_scores,
        "regime_confidence": str(confidence),
        "classification_margin": str(margin) if margin is not None else None,
        "calculation_summary": _json_ready(output.calculation_summary),
    }
    return MarketRegimeDraft(
        status=AnalysisObjectStatus.CREATED,
        is_usable=True,
        allows_strategy_routing=True,
        regime_code=regime_code,
        regime_scores=regime_scores,
        regime_confidence=confidence,
        classification_margin=margin,
        used_domain_signal_codes=used_codes,
        used_domain_signal_value_ids=used_ids,
        evidence_items=evidence_items,
        evidence_text_zh=evidence_text,
        payload_summary=payload_summary,
        latency_ms=latency_ms,
    )


def _persist_snapshot(
    *,
    domain_signal_set: DomainSignalSet,
    definition: MarketRegimeDefinition,
    frozen_slice: FrozenReleaseSlice,
    business_request_key: str,
    snapshot_key: str,
    draft: MarketRegimeDraft,
    trace_id: str,
    trigger_source: str,
) -> MarketRegimeSnapshot:
    return MarketRegimeSnapshot.objects.create(
        market_regime_snapshot_key=snapshot_key,
        business_request_key=business_request_key,
        domain_signal_set=domain_signal_set,
        market_regime_definition=definition,
        strategy_analysis_release=frozen_slice.release,
        release_hash=frozen_slice.release.release_hash,
        market_snapshot=domain_signal_set.market_snapshot,
        exchange=domain_signal_set.exchange,
        market_type=domain_signal_set.market_type,
        symbol=domain_signal_set.symbol,
        analysis_close_time_utc=domain_signal_set.analysis_close_time_utc,
        market_regime_schema_version=settings.MARKET_REGIME_SCHEMA_VERSION,
        definition_set_hash=frozen_slice.definition_set_hash,
        regime_code=draft.regime_code,
        regime_scores=draft.regime_scores,
        regime_confidence=draft.regime_confidence,
        classification_margin=draft.classification_margin,
        status=draft.status,
        is_usable=draft.is_usable,
        allows_strategy_routing=draft.allows_strategy_routing,
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
        evidence_items=draft.evidence_items,
        evidence_text_zh=draft.evidence_text_zh,
        payload_summary=draft.payload_summary,
        error_code=draft.error_code,
        error_message=draft.error_message,
        trace_id=trace_id,
        trigger_source=trigger_source,
        calculated_at_utc=timezone.now(),
        latency_ms=draft.latency_ms,
    )


def _snapshot_result(snapshot: MarketRegimeSnapshot, *, trace_id: str, trigger_source: str) -> ServiceResult:
    status = ResultStatus.SUCCEEDED
    reason = "market_regime_created"
    message = "MarketRegimeSnapshot 已生成"
    if snapshot.status == AnalysisObjectStatus.FAILED:
        status = ResultStatus.FAILED
        reason = snapshot.error_code or "market_regime_failed"
        message = snapshot.error_message or "MarketRegimeSnapshot 生成失败"
    elif snapshot.status == AnalysisObjectStatus.UNKNOWN:
        status = ResultStatus.UNKNOWN
        reason = snapshot.error_code or "market_regime_unknown"
        message = snapshot.error_message or "MarketRegimeSnapshot 状态未知"
    return ServiceResult(
        status,
        reason,
        message,
        trace_id,
        trigger_source,
        {
            "market_regime_snapshot_id": snapshot.id,
            "market_regime_snapshot_key": snapshot.market_regime_snapshot_key,
            "domain_signal_set_id": snapshot.domain_signal_set_id,
            "market_regime_definition_id": snapshot.market_regime_definition_id,
            "strategy_analysis_release_id": snapshot.strategy_analysis_release_id,
            "strategy_analysis_release_hash": snapshot.release_hash,
            "regime_code": snapshot.regime_code,
            "is_usable": snapshot.is_usable,
            "allows_strategy_routing": snapshot.allows_strategy_routing,
        },
    )


def _load_ready_domain_signal_set(
    *,
    domain_signal_set_id: int,
    strategy_analysis_release_id: int,
    strategy_analysis_release_hash: str,
    business_request_key: str,
    trace_id: str,
    trigger_source: str,
    dry_run: bool = False,
) -> tuple[DomainSignalSet | None, ServiceResult | None]:
    try:
        domain_signal_set = DomainSignalSet.objects.select_related(
            "strategy_analysis_release",
            "market_snapshot",
        ).get(id=domain_signal_set_id)
    except DomainSignalSet.DoesNotExist:
        return _result_with_alert(
            status=ResultStatus.BLOCKED,
            reason_code="domain_signal_set_not_found",
            message="DomainSignalSet 不存在，MarketRegime 阻断",
            business_request_key=business_request_key,
            trace_id=trace_id,
            trigger_source=trigger_source,
            dry_run=dry_run,
        )
        return None, result

    if (
        domain_signal_set.status != DomainSignalSetStatus.CREATED
        or not domain_signal_set.is_usable
        or not domain_signal_set.allows_market_regime
    ):
        return _result_with_alert(
            status=ResultStatus.BLOCKED,
            reason_code="domain_signal_set_not_usable",
            message="DomainSignalSet 不允许进入 MarketRegime",
            business_request_key=business_request_key,
            trace_id=trace_id,
            trigger_source=trigger_source,
            dry_run=dry_run,
            payload_summary={"domain_signal_set_id": domain_signal_set.id},
        )
        return None, result
    if (
        domain_signal_set.strategy_analysis_release_id != strategy_analysis_release_id
        or domain_signal_set.release_hash != strategy_analysis_release_hash
    ):
        return _result_with_alert(
            status=ResultStatus.BLOCKED,
            reason_code="market_regime_release_mismatch",
            message="DomainSignalSet 与传入版本包身份不一致",
            business_request_key=business_request_key,
            trace_id=trace_id,
            trigger_source=trigger_source,
            dry_run=dry_run,
            payload_summary={"domain_signal_set_id": domain_signal_set.id},
        )
        return None, result
    return domain_signal_set, None


def _resolve_definition_for_regime(
    *,
    strategy_analysis_release_id: int,
    strategy_analysis_release_hash: str,
    expected_market_regime_definition_hash: str,
    business_request_key: str,
    trace_id: str,
    trigger_source: str,
    dry_run: bool,
    registry: CalculatorRegistry,
) -> tuple[FrozenReleaseSlice | None, MarketRegimeDefinition | None, ServiceResult | None]:

    try:
        frozen_slice = resolve_frozen_slice(
            release_id=strategy_analysis_release_id,
            release_hash=strategy_analysis_release_hash,
            component_type=ReleaseItemComponentType.MARKET_REGIME_DEFINITION,
        )
    except (ObjectDoesNotExist, ValueError) as exc:
        result = _result_with_alert(
            status=ResultStatus.BLOCKED,
            reason_code="market_regime_release_invalid",
            message=f"MarketRegime 版本包不可用：{exc}",
            business_request_key=business_request_key,
            trace_id=trace_id,
            trigger_source=trigger_source,
            dry_run=dry_run,
        )
        return None, None, result

    definition, definition_error = _load_market_regime_definition(
        frozen_slice=frozen_slice,
        expected_definition_hash=expected_market_regime_definition_hash,
        dry_run=dry_run,
        registry=registry,
    )
    if definition is None:
        result = _result_with_alert(
            status=ResultStatus.BLOCKED,
            reason_code=definition_error,
            message="MarketRegimeDefinition 不满足正式分类条件",
            business_request_key=business_request_key,
            trace_id=trace_id,
            trigger_source=trigger_source,
            dry_run=dry_run,
            payload_summary={"definition_error": definition_error},
        )
        return None, None, result
    return frozen_slice, definition, None


def _calculate_draft(
    *,
    domain_signal_set: DomainSignalSet,
    definition: MarketRegimeDefinition,
    domain_values: list[DomainSignalValue],
    registry: CalculatorRegistry,
) -> MarketRegimeDraft:
    start = perf_counter()
    try:
        calculator = registry.resolve(
            calculator_type=CalculatorType.MARKET_REGIME,
            algorithm_name=definition.algorithm_name,
            algorithm_version=definition.algorithm_version,
        )
        calculation_input = _build_calculator_input(
            domain_signal_set=domain_signal_set,
            definition=definition,
            domain_values=domain_values,
        )
        output = calculator.calculate(calculation_input)
        latency_ms = int((perf_counter() - start) * 1000)
        return _validate_output(
            output=output,
            definition=definition,
            input_domain_values=domain_values,
            latency_ms=latency_ms,
        )
    except (InvalidCalculatorContractError, StrategyCalculatorError, TypeError, ValueError, OverflowError) as exc:
        return MarketRegimeDraft(
            status=AnalysisObjectStatus.FAILED,
            is_usable=False,
            allows_strategy_routing=False,
            regime_code="",
            regime_scores={},
            regime_confidence=None,
            classification_margin=None,
            used_domain_signal_codes=[],
            used_domain_signal_value_ids=[],
            evidence_items=[],
            evidence_text_zh="MarketRegime 输出合同校验失败。",
            payload_summary={"error": str(exc)},
            error_code="market_regime_output_invalid",
            error_message=str(exc),
            latency_ms=int((perf_counter() - start) * 1000),
        )
    except Exception as exc:
        logger.exception("MarketRegime calculator 出现未预期异常")
        return MarketRegimeDraft(
            status=AnalysisObjectStatus.FAILED,
            is_usable=False,
            allows_strategy_routing=False,
            regime_code="",
            regime_scores={},
            regime_confidence=None,
            classification_margin=None,
            used_domain_signal_codes=[],
            used_domain_signal_value_ids=[],
            evidence_items=[],
            evidence_text_zh="MarketRegime calculator 出现未预期异常。",
            payload_summary={"exception_type": type(exc).__name__},
            error_code="market_regime_calculator_unexpected_error",
            error_message=f"{type(exc).__name__}: {exc}",
            latency_ms=int((perf_counter() - start) * 1000),
        )


def _persist_draft_or_recover(
    *,
    domain_signal_set: DomainSignalSet,
    definition: MarketRegimeDefinition,
    frozen_slice: FrozenReleaseSlice,
    business_request_key: str,
    snapshot_key: str,
    draft: MarketRegimeDraft,
    trace_id: str,
    trigger_source: str,
) -> tuple[MarketRegimeSnapshot | None, ServiceResult | None]:
    try:
        with transaction.atomic():
            snapshot = _persist_snapshot(
                domain_signal_set=domain_signal_set,
                definition=definition,
                frozen_slice=frozen_slice,
                business_request_key=business_request_key,
                snapshot_key=snapshot_key,
                draft=draft,
                trace_id=trace_id,
                trigger_source=trigger_source,
            )
            if draft.status == AnalysisObjectStatus.FAILED:
                record_alert_event(
                    event_key=build_idempotency_key("market_regime_failed", business_request_key, draft.error_code),
                    source_module="MarketRegime",
                    event_type="market_regime_failed",
                    event_category="strategy_analysis",
                    severity=AlertSeverity.HIGH,
                    title_zh="MarketRegime 计算失败",
                    message_zh=draft.error_message or "MarketRegime 计算失败。",
                    trace_id=trace_id,
                    trigger_source=trigger_source,
                    related_object_type="MarketRegimeSnapshot",
                    related_object_id=str(snapshot.id),
                    business_status=draft.status,
                    reason_code=draft.error_code,
                    payload_summary=draft.payload_summary,
                )
        return snapshot, None
    except IntegrityError:
        try:
            existing_by_request = MarketRegimeSnapshot.objects.filter(
                business_request_key=business_request_key
            ).first()
            existing_by_snapshot_key = MarketRegimeSnapshot.objects.filter(
                market_regime_snapshot_key=snapshot_key
            ).first()
        except DatabaseError:
            logger.exception("MarketRegimeSnapshot 并发冲突后查证失败 trace_id=%s", trace_id)
            result = _result_with_alert(
                status=ResultStatus.UNKNOWN,
                reason_code="market_regime_persist_unknown",
                message="MarketRegimeSnapshot 写入结果无法确认",
                business_request_key=business_request_key,
                trace_id=trace_id,
                trigger_source=trigger_source,
                dry_run=False,
            )
            return None, result
        if existing_by_request is not None:
            if not _snapshot_matches_request(
                existing_by_request,
                domain_signal_set_id=domain_signal_set.id,
                strategy_analysis_release_id=frozen_slice.release.id,
                strategy_analysis_release_hash=frozen_slice.release.release_hash,
                expected_definition_hash=definition.definition_hash,
            ):
                return None, _idempotency_conflict_result(
                    business_request_key=business_request_key,
                    trace_id=trace_id,
                    trigger_source=trigger_source,
                    dry_run=False,
                    existing_snapshot=existing_by_request,
                    requested_domain_signal_set_id=domain_signal_set.id,
                )
            return existing_by_request, None
        if existing_by_snapshot_key is not None:
            return existing_by_snapshot_key, None
        result = _result_with_alert(
            status=ResultStatus.FAILED,
            reason_code="market_regime_persist_failed",
            message="MarketRegimeSnapshot 写入被数据库明确拒绝",
            business_request_key=business_request_key,
            trace_id=trace_id,
            trigger_source=trigger_source,
            dry_run=False,
        )
        return None, result
    except DataError as exc:
        logger.exception("MarketRegimeSnapshot 数据写入失败 trace_id=%s", trace_id)
        result = _result_with_alert(
            status=ResultStatus.FAILED,
            reason_code="market_regime_persist_failed",
            message=f"MarketRegimeSnapshot 数据不满足存储合同：{exc}",
            business_request_key=business_request_key,
            trace_id=trace_id,
            trigger_source=trigger_source,
            dry_run=False,
        )
        return None, result
    except DatabaseError:
        logger.exception("MarketRegimeSnapshot 写入失败 trace_id=%s", trace_id)
        result = _result_with_alert(
            status=ResultStatus.UNKNOWN,
            reason_code="market_regime_persist_unknown",
            message="MarketRegimeSnapshot 写入结果无法确认",
            business_request_key=business_request_key,
            trace_id=trace_id,
            trigger_source=trigger_source,
            dry_run=False,
        )
        return None, result


def classify_for_strategy_routing(
    *,
    domain_signal_set_id: int,
    strategy_analysis_release_id: int,
    strategy_analysis_release_hash: str,
    expected_market_regime_definition_hash: str = "",
    business_request_key: str,
    trace_id: str,
    trigger_source: str,
    dry_run: bool = False,
    registry: CalculatorRegistry = default_registry,
) -> ServiceResult:
    request_error, request_message = _validate_request_fields(
        domain_signal_set_id=domain_signal_set_id,
        strategy_analysis_release_id=strategy_analysis_release_id,
        strategy_analysis_release_hash=strategy_analysis_release_hash,
        business_request_key=business_request_key,
        trace_id=trace_id,
        trigger_source=trigger_source,
    )
    if request_error:
        return _result_with_alert(
            status=ResultStatus.BLOCKED,
            reason_code=request_error,
            message=request_message,
            business_request_key=business_request_key or "invalid-market-regime-request",
            trace_id=trace_id,
            trigger_source=trigger_source,
            dry_run=dry_run,
        )

    if not dry_run:
        existing_result = _existing_request_result(
            domain_signal_set_id=domain_signal_set_id,
            strategy_analysis_release_id=strategy_analysis_release_id,
            strategy_analysis_release_hash=strategy_analysis_release_hash,
            expected_definition_hash=expected_market_regime_definition_hash,
            business_request_key=business_request_key,
            trace_id=trace_id,
            trigger_source=trigger_source,
        )
        if existing_result is not None:
            return existing_result

    domain_signal_set, blocked = _load_ready_domain_signal_set(
        domain_signal_set_id=domain_signal_set_id,
        strategy_analysis_release_id=strategy_analysis_release_id,
        strategy_analysis_release_hash=strategy_analysis_release_hash,
        business_request_key=business_request_key,
        trace_id=trace_id,
        trigger_source=trigger_source,
        dry_run=dry_run,
    )
    if blocked is not None:
        return blocked
    assert domain_signal_set is not None

    frozen_slice, definition, blocked = _resolve_definition_for_regime(
        strategy_analysis_release_id=strategy_analysis_release_id,
        strategy_analysis_release_hash=strategy_analysis_release_hash,
        expected_market_regime_definition_hash=expected_market_regime_definition_hash,
        business_request_key=business_request_key,
        trace_id=trace_id,
        trigger_source=trigger_source,
        dry_run=dry_run,
        registry=registry,
    )
    if blocked is not None:
        return blocked
    assert frozen_slice is not None
    assert definition is not None

    domain_values, domain_error = _load_domain_values(domain_signal_set=domain_signal_set, definition=definition)
    if domain_values is None:
        return _result_with_alert(
            status=ResultStatus.BLOCKED,
            reason_code=domain_error,
            message="DomainSignalValue 不满足 MarketRegime 输入合同",
            business_request_key=business_request_key,
            trace_id=trace_id,
            trigger_source=trigger_source,
            dry_run=dry_run,
            payload_summary={"domain_signal_set_id": domain_signal_set.id},
        )

    snapshot_key = _snapshot_key(
        domain_signal_set_id=domain_signal_set.id,
        schema_version=settings.MARKET_REGIME_SCHEMA_VERSION,
        definition_hash=definition.definition_hash,
    )
    if not dry_run:
        existing_by_key = MarketRegimeSnapshot.objects.filter(market_regime_snapshot_key=snapshot_key).first()
        if existing_by_key is not None:
            return _snapshot_result(existing_by_key, trace_id=trace_id, trigger_source=trigger_source)

    draft = _calculate_draft(
        domain_signal_set=domain_signal_set,
        definition=definition,
        domain_values=domain_values,
        registry=registry,
    )

    if dry_run:
        return ServiceResult(
            ResultStatus.SUCCEEDED if draft.status == AnalysisObjectStatus.CREATED else ResultStatus.FAILED,
            "market_regime_dry_run",
            "MarketRegime dry-run 已完成，未写入正式业务对象",
            trace_id,
            trigger_source,
            {
                "persisted": False,
                "regime_code": draft.regime_code,
                "is_usable": draft.is_usable,
                "allows_strategy_routing": False,
                "error_code": draft.error_code,
            },
        )

    snapshot, unknown = _persist_draft_or_recover(
        domain_signal_set=domain_signal_set,
        definition=definition,
        frozen_slice=frozen_slice,
        business_request_key=business_request_key,
        snapshot_key=snapshot_key,
        draft=draft,
        trace_id=trace_id,
        trigger_source=trigger_source,
    )
    if unknown is not None:
        return unknown
    assert snapshot is not None

    return _snapshot_result(snapshot, trace_id=trace_id, trigger_source=trigger_source)
