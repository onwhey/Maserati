"""StrategySignalQuality 模块：验证 StrategySignal 是否可进入 DecisionSnapshot。
负责：读取已落库 StrategySignal 与同版本包质量规则集，生成质量结果与必要 AlertEvent。
不负责：重新执行策略、修改 StrategySignal、生成目标仓位或订单；不访问 Redis、Binance、DeepSeek，不发送 Hermes。
读写数据库；不访问外部服务；不调用大模型；不涉及交易执行或真实交易。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from django.core.exceptions import ObjectDoesNotExist
from django.db import DataError, DatabaseError, IntegrityError, transaction
from django.utils import timezone

from apps.alerts.models import AlertSeverity
from apps.alerts.services import record_alert_event
from apps.foundation.idempotency import build_idempotency_key
from apps.foundation.results import ResultStatus, ServiceResult
from apps.strategy_calculator.utils import stable_hash, thaw_value

from ..definition_hashes import normalize_strategy_weights, strategy_signal_quality_rule_set_hash
from ..models import (
    AnalysisObjectStatus,
    DefinitionLifecycleStatus,
    DomainSignalSetStatus,
    DomainSignalValue,
    DomainSignalValueStatus,
    ReleaseItemComponentType,
    StrategyRouteOutcome,
    StrategySignal,
    StrategySignalDirection,
    StrategySignalQualityIssue,
    StrategySignalQualityIssueSeverity,
    StrategySignalQualityResult,
    StrategySignalQualityRuleSet,
    StrategySignalQualityStatus,
    StrategySignalQualityValidationMode,
)
from .release import FrozenReleaseSlice, resolve_frozen_slice


logger = logging.getLogger(__name__)

MAX_BUSINESS_REQUEST_KEY_LENGTH = 191
MAX_TRACE_FIELD_LENGTH = 80
MAX_ERROR_CODE_LENGTH = 120
MAX_ERROR_MESSAGE_LENGTH = 500
MAX_SUMMARY_TEXT_LENGTH = 1000


@dataclass(frozen=True)
class QualityIssueDraft:
    issue_code: str
    severity: str
    check_group: str
    check_name: str
    field_name: str
    message_zh: str
    details: dict[str, Any]


@dataclass(frozen=True)
class QualityContext:
    signal: StrategySignal
    rule_set: StrategySignalQualityRuleSet
    quality_slice: FrozenReleaseSlice
    reference_time_utc: datetime
    validation_as_of_utc: datetime
    validation_mode: str
    issues: tuple[QualityIssueDraft, ...]


@dataclass(frozen=True)
class PreparedQualityValidation:
    context: QualityContext
    quality_result_key: str


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


def _empty_result_data(*, strategy_signal_id: int | None = None) -> dict[str, Any]:
    return {
        "quality_result_id": None,
        "quality_result_key": None,
        "strategy_signal_id": strategy_signal_id,
        "strategy_analysis_release_id": None,
        "strategy_analysis_release_hash": "",
        "strategy_signal_quality_rule_set_id": None,
        "quality_status": "",
        "is_usable": False,
        "allows_decision_snapshot": False,
        "issue_count": 0,
        "warning_count": 0,
        "error_count": 0,
        "critical_count": 0,
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
    strategy_signal_id: int | None = None,
    payload_summary: dict[str, Any] | None = None,
) -> ServiceResult:
    data = _empty_result_data(strategy_signal_id=strategy_signal_id)
    data.update(payload_summary or {})
    data["error_code"] = reason_code
    data["error_message"] = message
    if not dry_run:
        event_type = "strategy_signal_quality_blocked"
        severity = AlertSeverity.WARNING
        if status == ResultStatus.FAILED:
            event_type = "strategy_signal_quality_failed"
            severity = AlertSeverity.HIGH
        elif status == ResultStatus.UNKNOWN:
            event_type = "strategy_signal_quality_unknown"
            severity = AlertSeverity.HIGH
        try:
            record_alert_event(
                event_key=build_idempotency_key(event_type, business_request_key, reason_code),
                source_module="StrategySignalQuality",
                event_type=event_type,
                event_category="strategy_analysis",
                severity=severity,
                title_zh=f"StrategySignalQuality：{reason_code}",
                message_zh=message,
                trace_id=trace_id,
                trigger_source=trigger_source,
                related_object_type="StrategySignal" if strategy_signal_id else "",
                related_object_id=str(strategy_signal_id or ""),
                business_status=status.value,
                reason_code=reason_code,
                payload_summary=data,
            )
        except DatabaseError:
            logger.exception("StrategySignalQuality AlertEvent 写入失败 reason_code=%s trace_id=%s", reason_code, trace_id)
    return ServiceResult(status, reason_code, message, trace_id, trigger_source, data)


def _validate_request(
    *,
    strategy_signal_id: int,
    strategy_analysis_release_id: int,
    strategy_analysis_release_hash: str,
    expected_quality_rule_set_hash: str,
    business_request_key: str,
    validation_mode: str,
    trace_id: str,
    trigger_source: str,
) -> tuple[str, str]:
    if strategy_signal_id <= 0 or strategy_analysis_release_id <= 0:
        return "strategy_signal_quality_request_invalid", "策略信号和版本包 ID 必须是正整数"
    required = {
        "strategy_analysis_release_hash": strategy_analysis_release_hash,
        "expected_quality_rule_set_hash": expected_quality_rule_set_hash,
        "business_request_key": business_request_key,
        "validation_mode": validation_mode,
        "trace_id": trace_id,
        "trigger_source": trigger_source,
    }
    missing = [name for name, value in required.items() if not str(value).strip()]
    if missing:
        return "strategy_signal_quality_request_invalid", f"质量检查请求缺少必要字段：{','.join(missing)}"
    if validation_mode not in set(StrategySignalQualityValidationMode.values):
        return "strategy_signal_quality_request_invalid", "validation_mode 非法"
    if len(business_request_key) > MAX_BUSINESS_REQUEST_KEY_LENGTH:
        return "strategy_signal_quality_request_invalid", "business_request_key 超过允许长度"
    if len(trace_id) > MAX_TRACE_FIELD_LENGTH or len(trigger_source) > MAX_TRACE_FIELD_LENGTH:
        return "strategy_signal_quality_request_invalid", "trace_id 或 trigger_source 超过允许长度"
    return "", ""


def _normalize_reference_time(
    *,
    validation_mode: str,
    reference_time_utc: datetime | None,
    validation_as_of_utc: datetime,
) -> tuple[datetime | None, str]:
    if reference_time_utc is not None and (
        reference_time_utc.tzinfo is None or reference_time_utc.utcoffset() != timedelta(0)
    ):
        return None, "reference_time_must_be_utc"
    if validation_mode in {
        StrategySignalQualityValidationMode.REPLAY,
        StrategySignalQualityValidationMode.BACKFILL,
    } and reference_time_utc is None:
        return None, "reference_time_required"
    return reference_time_utc or validation_as_of_utc, ""


def _quality_rule_set_matches_request(
    result: StrategySignalQualityResult,
    *,
    signal_id: int,
    release_id: int,
    release_hash: str,
    quality_rule_set_hash: str,
    validation_mode: str,
) -> bool:
    return (
        result.strategy_signal_id == signal_id
        and result.strategy_analysis_release_id == release_id
        and result.release_hash == release_hash
        and result.quality_rule_set_hash == quality_rule_set_hash
        and result.validation_mode == validation_mode
    )


def _result_from_model(
    result: StrategySignalQualityResult,
    *,
    trace_id: str,
    trigger_source: str,
) -> ServiceResult:
    status = ResultStatus.SUCCEEDED
    reason = "strategy_signal_quality_created"
    message = "StrategySignalQuality 已完成"
    if result.status == AnalysisObjectStatus.BLOCKED:
        status = ResultStatus.BLOCKED
        reason = result.error_code or "strategy_signal_quality_blocked"
        message = result.error_message or "质量检查被阻断"
    elif result.status == AnalysisObjectStatus.FAILED:
        status = ResultStatus.FAILED
        reason = result.error_code or "strategy_signal_quality_failed"
        message = result.error_message or "质量检查失败"
    elif result.status == AnalysisObjectStatus.UNKNOWN:
        status = ResultStatus.UNKNOWN
        reason = result.error_code or "strategy_signal_quality_unknown"
        message = result.error_message or "质量检查状态未知"
    elif result.quality_status == StrategySignalQualityStatus.FAILED:
        status = ResultStatus.FAILED
        reason = result.error_code or "strategy_signal_quality_failed"
        message = result.error_message or "StrategySignal 未通过质量检查"
    return ServiceResult(status, reason, message, trace_id, trigger_source, _model_data(result))


def _model_data(result: StrategySignalQualityResult) -> dict[str, Any]:
    return {
        "quality_result_id": result.id,
        "quality_result_key": result.quality_result_key,
        "strategy_signal_id": result.strategy_signal_id,
        "strategy_analysis_release_id": result.strategy_analysis_release_id,
        "strategy_analysis_release_hash": result.release_hash,
        "strategy_signal_quality_rule_set_id": result.strategy_signal_quality_rule_set_id,
        "strategy_code": result.strategy_code,
        "strategy_version": result.strategy_version,
        "quality_status": result.quality_status,
        "is_usable": result.is_usable,
        "allows_decision_snapshot": result.allows_decision_snapshot,
        "issue_count": result.issue_count,
        "warning_count": result.warning_count,
        "error_count": result.error_count,
        "critical_count": result.critical_count,
        "error_code": result.error_code,
        "error_message": result.error_message,
        "persisted": True,
    }


def _load_signal(signal_id: int) -> tuple[StrategySignal | None, str]:
    try:
        return (
            StrategySignal.objects.select_related(
                "strategy_route_decision",
                "strategy_definition",
                "strategy_analysis_release",
                "domain_signal_set",
                "market_regime_snapshot",
            ).get(id=signal_id),
            "",
        )
    except StrategySignal.DoesNotExist:
        return None, "strategy_signal_missing"


def _load_quality_rule_set(
    *,
    release_id: int,
    release_hash: str,
    expected_quality_rule_set_hash: str,
) -> tuple[StrategySignalQualityRuleSet | None, FrozenReleaseSlice | None, str]:
    try:
        quality_slice = resolve_frozen_slice(
            release_id=release_id,
            release_hash=release_hash,
            component_type=ReleaseItemComponentType.STRATEGY_SIGNAL_QUALITY_RULE_SET,
        )
    except (ObjectDoesNotExist, ValueError):
        return None, None, "strategy_signal_quality_rule_set_unavailable"
    if len(quality_slice.items) != 1:
        return None, None, "strategy_signal_quality_rule_set_count_invalid"
    item = quality_slice.items[0]
    try:
        rule_set = StrategySignalQualityRuleSet.objects.get(id=item.component_object_id)
    except StrategySignalQualityRuleSet.DoesNotExist:
        return None, None, "strategy_signal_quality_rule_set_missing"
    if rule_set.status != DefinitionLifecycleStatus.ACTIVE or not rule_set.enabled:
        return None, None, "strategy_signal_quality_rule_set_not_selectable"
    params_hash = stable_hash(rule_set.params)
    actual_hash = strategy_signal_quality_rule_set_hash(
        rule_set_code=rule_set.rule_set_code,
        rule_set_version=rule_set.rule_set_version,
        quality_schema_version=rule_set.quality_schema_version,
        max_staleness_seconds=rule_set.max_staleness_seconds,
        warning_blocks_decision=rule_set.warning_blocks_decision,
        fail_alert_enabled=rule_set.fail_alert_enabled,
        warning_alert_enabled=rule_set.warning_alert_enabled,
        consecutive_failure_threshold=rule_set.consecutive_failure_threshold,
        params_hash=params_hash,
    )
    if (
        expected_quality_rule_set_hash != actual_hash
        or rule_set.params_hash != params_hash
        or rule_set.rule_set_hash != actual_hash
        or item.component_code != rule_set.rule_set_code
        or item.definition_hash != actual_hash
        or item.params_hash != params_hash
    ):
        return None, None, "strategy_signal_quality_rule_set_hash_mismatch"
    return rule_set, quality_slice, ""


def _issue(
    code: str,
    severity: str,
    group: str,
    name: str,
    field: str,
    message: str,
    details: dict[str, Any] | None = None,
) -> QualityIssueDraft:
    return QualityIssueDraft(
        issue_code=_limited_text(code, max_length=120),
        severity=severity,
        check_group=_limited_text(group, max_length=120),
        check_name=_limited_text(name, max_length=120),
        field_name=_limited_text(field, max_length=120),
        message_zh=_limited_text(message, max_length=500),
        details=_json_ready(details or {}),
    )


def _decimal_in_range(value: Any) -> bool:
    try:
        decimal = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return False
    return decimal.is_finite() and Decimal("0") <= decimal <= Decimal("1")


def _decimal_equal(left: Any, right: Any) -> bool:
    try:
        left_decimal = Decimal(str(left))
        right_decimal = Decimal(str(right))
    except (InvalidOperation, ValueError, TypeError):
        return False
    return left_decimal.is_finite() and right_decimal.is_finite() and left_decimal == right_decimal


def _collect_ref_ids(value: Any) -> set[int]:
    value = thaw_value(value)
    result: set[int] = set()
    if isinstance(value, dict):
        for key, item in value.items():
            if key == "domain_signal_value_id":
                try:
                    result.add(int(item))
                except (TypeError, ValueError):
                    pass
            elif key == "used_domain_signal_value_ids" and isinstance(item, list | tuple):
                for ref in item:
                    try:
                        result.add(int(ref))
                    except (TypeError, ValueError):
                        pass
            else:
                result.update(_collect_ref_ids(item))
    elif isinstance(value, list | tuple):
        for item in value:
            result.update(_collect_ref_ids(item))
    return result


def _normalize_used_domain_value_ids(value: Any) -> tuple[list[int], bool]:
    if not isinstance(value, list):
        return [], False
    result: list[int] = []
    is_valid = True
    for item in value:
        if isinstance(item, bool):
            is_valid = False
            continue
        if isinstance(item, int):
            parsed = item
        elif isinstance(item, str) and item.strip().isdigit():
            parsed = int(item.strip())
        else:
            is_valid = False
            continue
        if parsed <= 0:
            is_valid = False
            continue
        result.append(parsed)
    return result, is_valid and len(result) == len(value)


def _collect_quality_issues(signal: StrategySignal, rule_set: StrategySignalQualityRuleSet, reference_time: datetime) -> tuple[QualityIssueDraft, ...]:
    issues: list[QualityIssueDraft] = []
    issues.extend(_check_signal_contract(signal))
    issues.extend(_check_lineage_contract(signal))
    issues.extend(_check_domain_values(signal))
    issues.extend(_check_snapshot_contract(signal))
    issues.extend(_check_trade_price_condition_contract(signal))
    issues.extend(_check_evidence_contract(signal))
    issues.extend(_check_staleness(signal, rule_set, reference_time))
    return tuple(issues)


def _check_signal_contract(signal: StrategySignal) -> list[QualityIssueDraft]:
    issues: list[QualityIssueDraft] = []
    if signal.direction not in {StrategySignalDirection.BULLISH, StrategySignalDirection.BEARISH, StrategySignalDirection.NEUTRAL}:
        issues.append(_issue("strategy_signal_direction_invalid", "error", "structure", "direction", "direction", "策略方向非法"))
    if signal.strength is None or not _decimal_in_range(signal.strength):
        issues.append(_issue("strategy_signal_strength_invalid", "error", "numeric", "strength", "strength", "策略强度不在 0 到 1"))
    if signal.confidence is None or not _decimal_in_range(signal.confidence):
        issues.append(_issue("strategy_signal_confidence_invalid", "error", "numeric", "confidence", "confidence", "置信评分不在 0 到 1"))
    if not signal.confidence_semantics:
        issues.append(_issue("strategy_signal_confidence_semantics_missing", "error", "structure", "confidence_semantics", "confidence_semantics", "置信评分语义缺失"))
    if signal.prediction_horizon != signal.strategy_definition.prediction_horizon:
        issues.append(_issue("strategy_signal_prediction_horizon_invalid", "error", "structure", "prediction_horizon", "prediction_horizon", "预测期限与策略定义不一致"))
    if not isinstance(signal.used_domain_signal_value_ids, list) or not signal.used_domain_signal_value_ids:
        issues.append(_issue("strategy_signal_used_refs_missing", "error", "lineage", "used_refs", "used_domain_signal_value_ids", "实际使用领域输入缺失"))
    used_ids, used_ids_valid = _normalize_used_domain_value_ids(signal.used_domain_signal_value_ids)
    if used_ids_valid and len(used_ids) != len(set(used_ids)):
        issues.append(_issue("strategy_signal_used_refs_duplicate", "error", "lineage", "used_refs", "used_domain_signal_value_ids", "实际使用领域输入重复"))
    return issues


def _check_lineage_contract(signal: StrategySignal) -> list[QualityIssueDraft]:
    issues: list[QualityIssueDraft] = []
    decision = signal.strategy_route_decision
    definition = signal.strategy_definition
    if (
        decision.status != AnalysisObjectStatus.CREATED
        or decision.route_outcome != StrategyRouteOutcome.SELECTED
        or not decision.is_usable
        or not decision.allows_strategy_signal
        or decision.selected_strategy_definition_id != signal.strategy_definition_id
    ):
        issues.append(_issue("strategy_signal_route_lineage_invalid", "error", "lineage", "route_decision", "strategy_route_decision", "路由决定不可追溯或不可消费"))
    if (
        definition.status != DefinitionLifecycleStatus.ACTIVE
        or not definition.enabled
        or definition.strategy_code != signal.strategy_code
        or definition.strategy_version != signal.strategy_version
        or definition.algorithm_name != signal.algorithm_name
        or definition.algorithm_version != signal.algorithm_version
        or definition.definition_hash != signal.definition_hash
    ):
        issues.append(_issue("strategy_signal_definition_lineage_invalid", "error", "lineage", "definition", "strategy_definition", "策略定义身份不一致"))
    if (
        signal.strategy_analysis_release_id != decision.strategy_analysis_release_id
        or signal.strategy_analysis_release_id != signal.market_regime_snapshot.strategy_analysis_release_id
        or signal.strategy_analysis_release_id != signal.domain_signal_set.strategy_analysis_release_id
        or signal.release_hash != decision.release_hash
        or signal.release_hash != signal.market_regime_snapshot.release_hash
        or signal.release_hash != signal.domain_signal_set.release_hash
    ):
        issues.append(_issue("strategy_signal_release_lineage_invalid", "error", "lineage", "release", "release_hash", "策略信号与上游版本包身份不一致"))
    return issues


def _check_domain_values(signal: StrategySignal) -> list[QualityIssueDraft]:
    issues: list[QualityIssueDraft] = []
    domain_set = signal.domain_signal_set
    if domain_set.status != DomainSignalSetStatus.CREATED or not domain_set.is_usable:
        issues.append(_issue("strategy_signal_domain_set_invalid", "error", "lineage", "domain_set", "domain_signal_set", "领域信号集合不可用"))
    used_ids, used_ids_valid = _normalize_used_domain_value_ids(signal.used_domain_signal_value_ids)
    if not used_ids_valid:
        issues.append(_issue("strategy_signal_domain_value_id_invalid", "error", "lineage", "domain_values", "used_domain_signal_value_ids", "实际使用领域值 ID 非法"))
    values = DomainSignalValue.objects.filter(id__in=used_ids).order_by("id")
    by_id = {value.id: value for value in values}
    if set(by_id) != set(used_ids):
        issues.append(_issue("strategy_signal_domain_value_missing", "error", "lineage", "domain_values", "used_domain_signal_value_ids", "实际使用领域值不存在"))
    used_codes: set[str] = set()
    for value in by_id.values():
        used_codes.add(value.domain_code)
        if value.domain_signal_set_id != domain_set.id or value.status != DomainSignalValueStatus.CREATED or not value.is_valid:
            issues.append(_issue("strategy_signal_domain_value_invalid", "error", "lineage", "domain_values", "used_domain_signal_value_ids", "领域值不属于同一集合或不可用"))
        if value.domain_code not in signal.strategy_definition.allowed_domain_codes:
            issues.append(_issue("strategy_signal_domain_value_outside_allowed", "error", "lineage", "domain_values", "used_domain_signal_value_ids", "领域值不在策略允许范围内"))
    if not set(signal.strategy_definition.required_domain_codes or []).issubset(used_codes):
        issues.append(_issue("strategy_signal_required_domain_missing", "error", "lineage", "required_domain_codes", "used_domain_signal_value_ids", "必需领域输入未被实际使用"))
    issues.extend(_check_weights(signal, used_codes))
    return issues


def _check_weights(signal: StrategySignal, used_codes: set[str]) -> list[QualityIssueDraft]:
    if not isinstance(signal.actual_input_weights, dict):
        return [_issue("strategy_signal_weight_shape_invalid", "error", "weight", "actual_weights", "actual_input_weights", "实际权重必须是领域代码到权重值的映射")]
    try:
        frozen_weights = normalize_strategy_weights(
            signal.strategy_definition.domain_input_weights,
            allowed_domain_codes=signal.strategy_definition.allowed_domain_codes,
            uses_input_weights=signal.strategy_definition.uses_input_weights,
        )
    except ValueError as exc:
        return [_issue("strategy_signal_weight_definition_invalid", "error", "weight", "definition_weights", "actual_input_weights", str(exc))]
    if not signal.strategy_definition.uses_input_weights:
        return [] if not signal.actual_input_weights else [_issue("strategy_signal_hidden_weight", "error", "weight", "actual_weights", "actual_input_weights", "策略未启用权重但信号包含权重")]
    if set(signal.actual_input_weights) != used_codes:
        return [_issue("strategy_signal_weight_refs_invalid", "error", "weight", "actual_weights", "actual_input_weights", "实际权重未完整覆盖使用领域")]
    issues: list[QualityIssueDraft] = []
    for code, weight in signal.actual_input_weights.items():
        if str(weight) != frozen_weights.get(code):
            issues.append(_issue("strategy_signal_weight_mismatch", "error", "weight", "actual_weights", "actual_input_weights", "实际权重与策略定义不一致", {"domain_code": code}))
    return issues


def _check_snapshot_contract(signal: StrategySignal) -> list[QualityIssueDraft]:
    issues: list[QualityIssueDraft] = []
    snapshot = signal.market_regime_snapshot
    if (
        snapshot.status != AnalysisObjectStatus.CREATED
        or not snapshot.is_usable
        or snapshot.domain_signal_set_id != signal.domain_signal_set_id
        or signal.strategy_route_decision.market_regime_snapshot_id != snapshot.id
    ):
        issues.append(_issue("strategy_signal_market_regime_lineage_invalid", "error", "lineage", "market_regime", "market_regime_snapshot", "市场环境快照不可追溯或不可用"))
    aggregation = thaw_value(signal.aggregation_snapshot)
    if not isinstance(aggregation, dict):
        issues.append(_issue("strategy_signal_aggregation_invalid", "error", "snapshot", "aggregation", "aggregation_snapshot", "聚合快照非法"))
        return issues
    expected = {
        "final_direction": signal.direction,
        "final_strength": signal.strength,
        "final_confidence": signal.confidence,
    }
    for field, expected_value in expected.items():
        if field not in aggregation:
            issues.append(_issue("strategy_signal_aggregation_missing", "error", "snapshot", "aggregation", "aggregation_snapshot", f"聚合快照缺少 {field}"))
        elif field == "final_direction" and str(aggregation[field]) != expected_value:
            issues.append(_issue("strategy_signal_aggregation_mismatch", "error", "snapshot", "aggregation", "aggregation_snapshot", f"聚合快照 {field} 与主字段不一致"))
        elif field != "final_direction" and not _decimal_equal(aggregation[field], expected_value):
            issues.append(_issue("strategy_signal_aggregation_mismatch", "error", "snapshot", "aggregation", "aggregation_snapshot", f"聚合快照 {field} 与主字段不一致"))
    if not isinstance(thaw_value(signal.conflict_snapshot), dict):
        issues.append(_issue("strategy_signal_conflict_snapshot_invalid", "error", "snapshot", "conflict", "conflict_snapshot", "冲突快照非法"))
    return issues


def _check_evidence_contract(signal: StrategySignal) -> list[QualityIssueDraft]:
    issues: list[QualityIssueDraft] = []
    if not signal.evidence_text_zh:
        issues.append(_issue("strategy_signal_evidence_text_missing", "error", "evidence", "text", "evidence_text_zh", "中文证据缺失"))
    if not isinstance(signal.evidence_items, list) or not signal.evidence_items:
        issues.append(_issue("strategy_signal_evidence_items_missing", "error", "evidence", "items", "evidence_items", "结构化证据缺失"))
        return issues
    evidence_refs = _collect_ref_ids(signal.evidence_items)
    used_ids, _used_ids_valid = _normalize_used_domain_value_ids(signal.used_domain_signal_value_ids)
    used_refs = set(used_ids)
    if not used_refs.issubset(evidence_refs):
        issues.append(_issue("strategy_signal_evidence_refs_missing", "error", "evidence", "refs", "evidence_items", "证据未覆盖全部实际使用领域输入"))
    return issues


def _check_trade_price_condition_contract(signal: StrategySignal) -> list[QualityIssueDraft]:
    value = thaw_value(signal.trade_price_condition)
    if value in (None, "", {}):
        return []
    if not isinstance(value, dict):
        return [
            _issue(
                "strategy_signal_trade_price_condition_invalid",
                "error",
                "structure",
                "trade_price_condition",
                "trade_price_condition",
                "策略价格条件必须是结构化映射或为空",
            )
        ]
    issues: list[QualityIssueDraft] = []
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
        issues.append(
            _issue(
                "strategy_signal_trade_price_condition_missing",
                "error",
                "structure",
                "trade_price_condition",
                "trade_price_condition",
                "策略价格条件缺少必要字段",
                {"missing_fields": missing},
            )
        )
    for field_name in ("condition_type", "reason_code", "reason_summary_zh"):
        if field_name in value and not str(value.get(field_name, "")).strip():
            issues.append(
                _issue(
                    "strategy_signal_trade_price_condition_empty_field",
                    "error",
                    "structure",
                    "trade_price_condition",
                    "trade_price_condition",
                    "策略价格条件存在空字段",
                    {"field_name": field_name},
                )
            )
    refs = value.get("support_or_resistance_refs")
    if "support_or_resistance_refs" in value and (
        not isinstance(refs, list) or not refs or any(not isinstance(item, str) or not item.strip() for item in refs)
    ):
        issues.append(
            _issue(
                "strategy_signal_trade_price_condition_refs_invalid",
                "error",
                "structure",
                "trade_price_condition",
                "trade_price_condition",
                "策略价格条件的支撑压力引用必须是非空字符串列表",
            )
        )
    if "allow_chasing" in value and not isinstance(value.get("allow_chasing"), bool):
        issues.append(
            _issue(
                "strategy_signal_trade_price_condition_allow_chasing_invalid",
                "error",
                "structure",
                "trade_price_condition",
                "trade_price_condition",
                "策略价格条件的是否允许追价字段必须是布尔值",
            )
        )
    return issues


def _check_staleness(signal: StrategySignal, rule_set: StrategySignalQualityRuleSet, reference_time: datetime) -> list[QualityIssueDraft]:
    if not signal.analysis_close_time_utc or rule_set.max_staleness_seconds <= 0:
        return []
    age_seconds = (reference_time - signal.analysis_close_time_utc).total_seconds()
    if age_seconds <= rule_set.max_staleness_seconds:
        return []
    return [
        _issue(
            "strategy_signal_stale",
            "warning",
            "freshness",
            "staleness",
            "analysis_close_time_utc",
            "策略信号市场事实超过质量规则允许时效",
            {"age_seconds": int(age_seconds), "max_staleness_seconds": rule_set.max_staleness_seconds},
        )
    ]


def _quality_status(issues: tuple[QualityIssueDraft, ...], rule_set: StrategySignalQualityRuleSet) -> tuple[str, bool]:
    severities = {issue.severity for issue in issues}
    if StrategySignalQualityIssueSeverity.ERROR in severities or StrategySignalQualityIssueSeverity.CRITICAL in severities:
        return StrategySignalQualityStatus.FAILED, False
    if StrategySignalQualityIssueSeverity.WARNING in severities:
        return StrategySignalQualityStatus.WARNING, not rule_set.warning_blocks_decision
    return StrategySignalQualityStatus.PASSED, True


def _quality_result_key(
    *,
    signal_id: int,
    quality_schema_version: str,
    quality_rule_set_hash: str,
    validation_mode: str,
    reference_time_utc: datetime,
) -> str:
    return stable_hash(
        {
            "strategy_signal_id": signal_id,
            "quality_schema_version": quality_schema_version,
            "quality_rule_set_hash": quality_rule_set_hash,
            "validation_mode": validation_mode,
            "reference_time_utc": reference_time_utc.isoformat(),
        }
    )


def _build_context(
    *,
    signal: StrategySignal,
    rule_set: StrategySignalQualityRuleSet,
    quality_slice: FrozenReleaseSlice,
    validation_mode: str,
    reference_time_utc: datetime,
    validation_as_of_utc: datetime,
) -> QualityContext:
    issues = _collect_quality_issues(signal, rule_set, reference_time_utc)
    return QualityContext(
        signal=signal,
        rule_set=rule_set,
        quality_slice=quality_slice,
        reference_time_utc=reference_time_utc,
        validation_as_of_utc=validation_as_of_utc,
        validation_mode=validation_mode,
        issues=issues,
    )


def _precondition_error(signal: StrategySignal, *, release_id: int, release_hash: str) -> str:
    if (
        signal.status != AnalysisObjectStatus.CREATED
        or not signal.is_usable
        or not signal.allows_strategy_signal_quality
    ):
        return "strategy_signal_not_consumable"
    if (
        signal.strategy_analysis_release_id != release_id
        or signal.release_hash != release_hash
        or not signal.strategy_route_decision_id
        or not signal.strategy_definition_id
        or not signal.domain_signal_set_id
        or not signal.market_regime_snapshot_id
    ):
        return "strategy_signal_non_formal_rejected"
    return ""


def _persist_quality_result(
    *,
    context: QualityContext,
    quality_result_key: str,
    business_request_key: str,
    trace_id: str,
    trigger_source: str,
) -> StrategySignalQualityResult:
    signal = context.signal
    rule_set = context.rule_set
    quality_status, allows_decision = _quality_status(context.issues, rule_set)
    warning_count = sum(1 for issue in context.issues if issue.severity == StrategySignalQualityIssueSeverity.WARNING)
    error_count = sum(1 for issue in context.issues if issue.severity == StrategySignalQualityIssueSeverity.ERROR)
    critical_count = sum(1 for issue in context.issues if issue.severity == StrategySignalQualityIssueSeverity.CRITICAL)
    is_usable = allows_decision
    error_code = "strategy_signal_quality_failed" if quality_status == StrategySignalQualityStatus.FAILED else ""
    error_message = "StrategySignal 未通过质量检查" if error_code else ""
    result = StrategySignalQualityResult.objects.create(
        quality_result_key=quality_result_key,
        business_request_key=business_request_key,
        strategy_signal=signal,
        strategy_signal_key=signal.strategy_signal_key,
        strategy_analysis_release=context.quality_slice.release,
        release_hash=context.quality_slice.release.release_hash,
        strategy_signal_quality_rule_set=rule_set,
        strategy_route_decision=signal.strategy_route_decision,
        strategy_definition=signal.strategy_definition,
        domain_signal_set=signal.domain_signal_set,
        market_regime_snapshot=signal.market_regime_snapshot,
        strategy_code=signal.strategy_code,
        strategy_version=signal.strategy_version,
        algorithm_name=signal.algorithm_name,
        algorithm_version=signal.algorithm_version,
        quality_schema_version=rule_set.quality_schema_version,
        quality_rule_set_version=rule_set.rule_set_version,
        quality_rule_set_hash=rule_set.rule_set_hash,
        validation_mode=context.validation_mode,
        reference_time_utc=context.reference_time_utc,
        validation_as_of_utc=context.validation_as_of_utc,
        market_as_of_utc=signal.analysis_close_time_utc,
        status=AnalysisObjectStatus.CREATED,
        quality_status=quality_status,
        is_usable=is_usable,
        allows_decision_snapshot=allows_decision,
        issue_count=len(context.issues),
        warning_count=warning_count,
        error_count=error_count,
        critical_count=critical_count,
        blocked_reason="" if allows_decision else error_code,
        error_code=error_code,
        error_message=error_message,
        check_summary={
            "issue_codes": [issue.issue_code for issue in context.issues],
            "warning_blocks_decision": rule_set.warning_blocks_decision,
        },
        summary_text_zh=_summary_text(quality_status, allows_decision, len(context.issues)),
        trace_id=trace_id,
        trigger_source=trigger_source,
    )
    StrategySignalQualityIssue.objects.bulk_create(
        [
            StrategySignalQualityIssue(
                quality_result=result,
                issue_code=issue.issue_code,
                severity=issue.severity,
                check_group=issue.check_group,
                check_name=issue.check_name,
                field_name=issue.field_name,
                message_zh=issue.message_zh,
                details=issue.details,
            )
            for issue in context.issues
        ]
    )
    return result


def _summary_text(quality_status: str, allows_decision: bool, issue_count: int) -> str:
    if quality_status == StrategySignalQualityStatus.PASSED:
        return "策略信号质量检查通过，允许进入目标仓位决策。"
    if quality_status == StrategySignalQualityStatus.WARNING and allows_decision:
        return _limited_text(f"策略信号存在 {issue_count} 个非阻断质量警告，允许进入目标仓位决策。", max_length=MAX_SUMMARY_TEXT_LENGTH)
    if quality_status == StrategySignalQualityStatus.WARNING:
        return _limited_text(f"策略信号存在 {issue_count} 个质量警告，当前规则要求阻断目标仓位决策。", max_length=MAX_SUMMARY_TEXT_LENGTH)
    return _limited_text(f"策略信号存在 {issue_count} 个阻断性质量问题，不允许进入目标仓位决策。", max_length=MAX_SUMMARY_TEXT_LENGTH)


def _write_result_alert(result: StrategySignalQualityResult, *, business_request_key: str, trace_id: str, trigger_source: str) -> None:
    if result.quality_status == StrategySignalQualityStatus.PASSED:
        return
    if result.quality_status == StrategySignalQualityStatus.WARNING and not result.strategy_signal_quality_rule_set.warning_alert_enabled:
        return
    if result.quality_status == StrategySignalQualityStatus.FAILED and not result.strategy_signal_quality_rule_set.fail_alert_enabled:
        return
    severity = AlertSeverity.WARNING if result.quality_status == StrategySignalQualityStatus.WARNING else AlertSeverity.HIGH
    event_type = "strategy_signal_quality_warning" if result.quality_status == StrategySignalQualityStatus.WARNING else "strategy_signal_quality_failed"
    failed_issue_codes = list(
        result.issues.filter(
            severity__in=[
                StrategySignalQualityIssueSeverity.ERROR,
                StrategySignalQualityIssueSeverity.CRITICAL,
            ]
        ).values_list("issue_code", flat=True)
    )
    warning_issue_codes = list(
        result.issues.filter(severity=StrategySignalQualityIssueSeverity.WARNING).values_list("issue_code", flat=True)
    )
    payload_summary = _model_data(result)
    payload_summary.update(
        {
            "failed_issue_codes": failed_issue_codes,
            "warning_issue_codes": warning_issue_codes,
            "summary_text_zh": result.summary_text_zh,
        }
    )
    record_alert_event(
        event_key=build_idempotency_key(event_type, business_request_key, result.quality_result_key),
        source_module="StrategySignalQuality",
        event_type=event_type,
        event_category="strategy_analysis",
        severity=severity,
        title_zh="StrategySignalQuality 质量检查结果",
        message_zh=result.summary_text_zh,
        trace_id=trace_id,
        trigger_source=trigger_source,
        related_object_type="StrategySignalQualityResult",
        related_object_id=str(result.id),
        business_status=result.quality_status,
        reason_code=result.error_code,
        payload_summary=payload_summary,
    )


def _persist_or_recover(
    *,
    context: QualityContext,
    quality_result_key: str,
    business_request_key: str,
    trace_id: str,
    trigger_source: str,
) -> tuple[StrategySignalQualityResult | None, ServiceResult | None]:
    try:
        with transaction.atomic():
            result = _persist_quality_result(
                context=context,
                quality_result_key=quality_result_key,
                business_request_key=business_request_key,
                trace_id=trace_id,
                trigger_source=trigger_source,
            )
            _write_result_alert(result, business_request_key=business_request_key, trace_id=trace_id, trigger_source=trigger_source)
        return result, None
    except IntegrityError:
        try:
            by_request = StrategySignalQualityResult.objects.filter(business_request_key=business_request_key).first()
            by_key = StrategySignalQualityResult.objects.filter(quality_result_key=quality_result_key).first()
        except DatabaseError:
            return None, _result_with_alert(
                status=ResultStatus.UNKNOWN,
                reason_code="strategy_signal_quality_persist_unknown",
                message="StrategySignalQuality 写入结果无法确认",
                business_request_key=business_request_key,
                trace_id=trace_id,
                trigger_source=trigger_source,
                dry_run=False,
                strategy_signal_id=context.signal.id,
            )
        if by_request is not None:
            if not _quality_rule_set_matches_request(
                by_request,
                signal_id=context.signal.id,
                release_id=context.quality_slice.release.id,
                release_hash=context.quality_slice.release.release_hash,
                quality_rule_set_hash=context.rule_set.rule_set_hash,
                validation_mode=context.validation_mode,
            ):
                return None, _result_with_alert(
                    status=ResultStatus.BLOCKED,
                    reason_code="strategy_signal_quality_idempotency_conflict",
                    message="business_request_key 已被另一份 StrategySignalQuality 请求使用",
                    business_request_key=business_request_key,
                    trace_id=trace_id,
                    trigger_source=trigger_source,
                    dry_run=False,
                    strategy_signal_id=context.signal.id,
                )
            return by_request, None
        if by_key is not None:
            return by_key, None
        return None, _result_with_alert(
            status=ResultStatus.FAILED,
            reason_code="strategy_signal_quality_persist_failed",
            message="StrategySignalQuality 写入被数据库明确拒绝",
            business_request_key=business_request_key,
            trace_id=trace_id,
            trigger_source=trigger_source,
            dry_run=False,
            strategy_signal_id=context.signal.id,
        )
    except DataError as exc:
        return None, _result_with_alert(
            status=ResultStatus.FAILED,
            reason_code="strategy_signal_quality_persist_failed",
            message=f"StrategySignalQuality 数据不满足存储合同：{exc}",
            business_request_key=business_request_key,
            trace_id=trace_id,
            trigger_source=trigger_source,
            dry_run=False,
            strategy_signal_id=context.signal.id,
        )
    except DatabaseError:
        logger.exception("StrategySignalQuality 写入失败 trace_id=%s", trace_id)
        return None, _result_with_alert(
            status=ResultStatus.UNKNOWN,
            reason_code="strategy_signal_quality_persist_unknown",
            message="StrategySignalQuality 写入结果无法确认",
            business_request_key=business_request_key,
            trace_id=trace_id,
            trigger_source=trigger_source,
            dry_run=False,
            strategy_signal_id=context.signal.id,
        )


def _prepare_quality_validation(
    *,
    strategy_signal_id: int,
    strategy_analysis_release_id: int,
    strategy_analysis_release_hash: str,
    expected_quality_rule_set_hash: str,
    business_request_key: str,
    validation_mode: str,
    reference_time_utc: datetime | None,
    dry_run: bool,
    trace_id: str,
    trigger_source: str,
) -> tuple[PreparedQualityValidation | None, ServiceResult | None]:
    validation_as_of = timezone.now()
    reference_time, time_error = _normalize_reference_time(
        validation_mode=validation_mode,
        reference_time_utc=reference_time_utc,
        validation_as_of_utc=validation_as_of,
    )
    if reference_time is None:
        return None, _result_with_alert(
            status=ResultStatus.BLOCKED,
            reason_code=time_error,
            message="StrategySignalQuality 参考时间不满足验证模式要求",
            business_request_key=business_request_key,
            trace_id=trace_id,
            trigger_source=trigger_source,
            dry_run=dry_run,
            strategy_signal_id=strategy_signal_id,
        )
    signal, signal_error = _load_signal(strategy_signal_id)
    if signal is None:
        return None, _result_with_alert(
            status=ResultStatus.BLOCKED,
            reason_code=signal_error,
            message="StrategySignal 不存在，质量检查 fail-closed",
            business_request_key=business_request_key,
            trace_id=trace_id,
            trigger_source=trigger_source,
            dry_run=dry_run,
            strategy_signal_id=strategy_signal_id,
        )
    precondition_error = _precondition_error(
        signal,
        release_id=strategy_analysis_release_id,
        release_hash=strategy_analysis_release_hash,
    )
    if precondition_error:
        return None, _result_with_alert(
            status=ResultStatus.BLOCKED,
            reason_code=precondition_error,
            message="StrategySignal 不满足质量检查正式消费条件",
            business_request_key=business_request_key,
            trace_id=trace_id,
            trigger_source=trigger_source,
            dry_run=dry_run,
            strategy_signal_id=strategy_signal_id,
        )
    rule_set, quality_slice, rule_error = _load_quality_rule_set(
        release_id=strategy_analysis_release_id,
        release_hash=strategy_analysis_release_hash,
        expected_quality_rule_set_hash=expected_quality_rule_set_hash,
    )
    if rule_set is None or quality_slice is None:
        return None, _result_with_alert(
            status=ResultStatus.BLOCKED,
            reason_code=rule_error,
            message="StrategySignalQualityRuleSet 不满足正式质量检查条件",
            business_request_key=business_request_key,
            trace_id=trace_id,
            trigger_source=trigger_source,
            dry_run=dry_run,
            strategy_signal_id=strategy_signal_id,
        )
    context = _build_context(
        signal=signal,
        rule_set=rule_set,
        quality_slice=quality_slice,
        validation_mode=validation_mode,
        reference_time_utc=reference_time,
        validation_as_of_utc=validation_as_of,
    )
    result_key = _quality_result_key(
        signal_id=signal.id,
        quality_schema_version=rule_set.quality_schema_version,
        quality_rule_set_hash=rule_set.rule_set_hash,
        validation_mode=validation_mode,
        reference_time_utc=reference_time,
    )
    return PreparedQualityValidation(context=context, quality_result_key=result_key), None


def _dry_run_service_result(
    *,
    prepared: PreparedQualityValidation,
    strategy_signal_id: int,
    trace_id: str,
    trigger_source: str,
) -> ServiceResult:
    context = prepared.context
    quality_status, allows_decision = _quality_status(context.issues, context.rule_set)
    warning_count = sum(1 for issue in context.issues if issue.severity == StrategySignalQualityIssueSeverity.WARNING)
    error_count = sum(1 for issue in context.issues if issue.severity == StrategySignalQualityIssueSeverity.ERROR)
    critical_count = sum(1 for issue in context.issues if issue.severity == StrategySignalQualityIssueSeverity.CRITICAL)
    return ServiceResult(
        ResultStatus.SUCCEEDED if allows_decision else ResultStatus.FAILED,
        "strategy_signal_quality_dry_run",
        "StrategySignalQuality dry-run 已完成，未写入正式业务对象",
        trace_id,
        trigger_source,
        {
            **_empty_result_data(strategy_signal_id=strategy_signal_id),
            "quality_result_key": prepared.quality_result_key,
            "strategy_analysis_release_id": context.quality_slice.release.id,
            "strategy_analysis_release_hash": context.quality_slice.release.release_hash,
            "strategy_signal_quality_rule_set_id": context.rule_set.id,
            "quality_status": quality_status,
            "is_usable": False,
            "allows_decision_snapshot": False,
            "issue_count": len(context.issues),
            "warning_count": warning_count,
            "error_count": error_count,
            "critical_count": critical_count,
            "persisted": False,
        },
    )


def validate_strategy_signal(
    *,
    strategy_signal_id: int,
    strategy_analysis_release_id: int,
    strategy_analysis_release_hash: str,
    expected_quality_rule_set_hash: str,
    business_request_key: str,
    validation_mode: str,
    reference_time_utc: datetime | None = None,
    dry_run: bool = False,
    trace_id: str,
    trigger_source: str,
) -> ServiceResult:
    error, message = _validate_request(
        strategy_signal_id=strategy_signal_id,
        strategy_analysis_release_id=strategy_analysis_release_id,
        strategy_analysis_release_hash=strategy_analysis_release_hash,
        expected_quality_rule_set_hash=expected_quality_rule_set_hash,
        business_request_key=business_request_key,
        validation_mode=validation_mode,
        trace_id=trace_id,
        trigger_source=trigger_source,
    )
    if error:
        return _result_with_alert(
            status=ResultStatus.BLOCKED,
            reason_code=error,
            message=message,
            business_request_key=business_request_key or "invalid-strategy-signal-quality-request",
            trace_id=trace_id,
            trigger_source=trigger_source,
            dry_run=dry_run,
            strategy_signal_id=strategy_signal_id if strategy_signal_id > 0 else None,
        )
    if not dry_run:
        existing = StrategySignalQualityResult.objects.filter(business_request_key=business_request_key).first()
        if existing is not None:
            if not _quality_rule_set_matches_request(
                existing,
                signal_id=strategy_signal_id,
                release_id=strategy_analysis_release_id,
                release_hash=strategy_analysis_release_hash,
                quality_rule_set_hash=expected_quality_rule_set_hash,
                validation_mode=validation_mode,
            ):
                return _result_with_alert(
                    status=ResultStatus.BLOCKED,
                    reason_code="strategy_signal_quality_idempotency_conflict",
                    message="business_request_key 已被另一份 StrategySignalQuality 请求使用",
                    business_request_key=business_request_key,
                    trace_id=trace_id,
                    trigger_source=trigger_source,
                    dry_run=False,
                    strategy_signal_id=strategy_signal_id,
                )
            return _result_from_model(existing, trace_id=trace_id, trigger_source=trigger_source)
    prepared, preparation_result = _prepare_quality_validation(
        strategy_signal_id=strategy_signal_id,
        strategy_analysis_release_id=strategy_analysis_release_id,
        strategy_analysis_release_hash=strategy_analysis_release_hash,
        expected_quality_rule_set_hash=expected_quality_rule_set_hash,
        validation_mode=validation_mode,
        reference_time_utc=reference_time_utc,
        business_request_key=business_request_key,
        dry_run=dry_run,
        trace_id=trace_id,
        trigger_source=trigger_source,
    )
    if preparation_result is not None:
        return preparation_result
    assert prepared is not None
    if not dry_run:
        existing_by_key = StrategySignalQualityResult.objects.filter(quality_result_key=prepared.quality_result_key).first()
        if existing_by_key is not None:
            return _result_from_model(existing_by_key, trace_id=trace_id, trigger_source=trigger_source)
    if dry_run:
        return _dry_run_service_result(prepared=prepared, strategy_signal_id=strategy_signal_id, trace_id=trace_id, trigger_source=trigger_source)
    result, persist_result = _persist_or_recover(
        context=prepared.context,
        quality_result_key=prepared.quality_result_key,
        business_request_key=business_request_key,
        trace_id=trace_id,
        trigger_source=trigger_source,
    )
    if persist_result is not None:
        return persist_result
    assert result is not None
    return _result_from_model(result, trace_id=trace_id, trigger_source=trigger_source)
