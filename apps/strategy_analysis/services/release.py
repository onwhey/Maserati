"""StrategyAnalysis 模块：管理策略分析版本包；读写数据库，不访问 Redis 或外部服务，不涉及交易执行。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.alerts.models import AlertSeverity
from apps.alerts.services import record_alert_event
from apps.foundation.idempotency import build_idempotency_key
from apps.foundation.results import ResultStatus, ServiceResult
from apps.strategy_calculator.contracts import CalculatorType
from apps.strategy_calculator.errors import StrategyCalculatorError
from apps.strategy_calculator.registry import CalculatorRegistry, default_registry
from apps.strategy_calculator.utils import stable_hash

from ..definition_hashes import (
    atomic_signal_definition_hash,
    atomic_signal_dependency_hash,
    domain_atomic_membership_hash,
    normalize_feature_codes,
)
from ..models import (
    AtomicSignalDefinition,
    DefinitionLifecycleStatus,
    ReleaseAction,
    ReleaseApprovalStatus,
    ReleaseItemComponentType,
    FeatureDefinition,
    StrategyAnalysisRelease,
    StrategyAnalysisReleaseActivation,
    StrategyAnalysisReleaseApproval,
    StrategyAnalysisReleaseItem,
    StrategyAnalysisReleaseValidationEvidence,
)


IMPLEMENTED_FORMAL_COMPONENT_TYPES = {
    ReleaseItemComponentType.FEATURE_DEFINITION,
    ReleaseItemComponentType.ATOMIC_SIGNAL_DEFINITION,
}


CALCULATOR_TYPE_BY_COMPONENT = {
    ReleaseItemComponentType.FEATURE_DEFINITION: CalculatorType.FEATURE_LAYER,
    ReleaseItemComponentType.ATOMIC_SIGNAL_DEFINITION: CalculatorType.ATOMIC_SIGNAL,
    ReleaseItemComponentType.DOMAIN_SIGNAL_DEFINITION: CalculatorType.DOMAIN_SIGNAL,
    ReleaseItemComponentType.MARKET_REGIME_DEFINITION: CalculatorType.MARKET_REGIME,
    ReleaseItemComponentType.STRATEGY_DEFINITION: CalculatorType.STRATEGY_SIGNAL,
    ReleaseItemComponentType.DECISION_POLICY_DEFINITION: CalculatorType.DECISION_POLICY,
}


@dataclass(frozen=True)
class FrozenReleaseSlice:
    release: StrategyAnalysisRelease
    component_type: str
    items: tuple[StrategyAnalysisReleaseItem, ...]
    definition_set_hash: str


def release_manifest(release: StrategyAnalysisRelease) -> list[dict[str, object]]:
    items = release.items.order_by("component_type", "sort_order", "component_code", "id")
    return [
        {
            "component_type": item.component_type,
            "component_object_id": item.component_object_id,
            "component_code": item.component_code,
            "definition_hash": item.definition_hash,
            "algorithm_name": item.algorithm_name,
            "algorithm_version": item.algorithm_version,
            "params_hash": item.params_hash,
            "dependency_hash": item.dependency_hash,
            "expected_definition_set_hash": item.expected_definition_set_hash,
            "sort_order": item.sort_order,
        }
        for item in items
    ]


def calculate_release_hash(release: StrategyAnalysisRelease) -> str:
    return stable_hash(release_manifest(release))


def calculate_definition_set_hash(items: Iterable[StrategyAnalysisReleaseItem]) -> str:
    normalized = [
        {
            "component_type": item.component_type,
            "component_object_id": item.component_object_id,
            "component_code": item.component_code,
            "definition_hash": item.definition_hash,
            "algorithm_name": item.algorithm_name,
            "algorithm_version": item.algorithm_version,
            "params_hash": item.params_hash,
            "dependency_hash": item.dependency_hash,
            "sort_order": item.sort_order,
        }
        for item in sorted(items, key=lambda item: (item.sort_order, item.component_code, item.id or 0))
    ]
    return stable_hash(normalized)


def freeze_release_for_validation(
    *,
    release_id: int,
    trace_id: str,
    trigger_source: str,
) -> ServiceResult:
    with transaction.atomic():
        release = StrategyAnalysisRelease.objects.select_for_update().get(id=release_id)
        if release.approval_status != ReleaseApprovalStatus.DRAFT:
            return ServiceResult(ResultStatus.BLOCKED, "release_not_draft", "只有 draft 版本包可以冻结验证", trace_id, trigger_source)
        release.release_hash = calculate_release_hash(release)
        release.approval_status = ReleaseApprovalStatus.VALIDATING
        release.save(update_fields=["release_hash", "approval_status", "updated_at_utc"])
        record_alert_event(
            event_key=build_idempotency_key("strategy_release_validating", release.id, release.release_hash),
            source_module="StrategyAnalysisRelease",
            event_type="strategy_analysis_release_validating",
            event_category="strategy_analysis_release",
            severity=AlertSeverity.INFO,
            title_zh="策略分析版本包进入验证",
            message_zh=f"版本包 {release.release_code} 已冻结并进入验证。",
            trace_id=trace_id,
            trigger_source=trigger_source,
            related_object_type="StrategyAnalysisRelease",
            related_object_id=str(release.id),
            business_status=release.approval_status,
            payload_summary={"release_hash": release.release_hash},
        )
    return ServiceResult(
        ResultStatus.SUCCEEDED,
        "release_validating",
        "版本包已冻结并进入验证状态",
        trace_id,
        trigger_source,
        {"release_id": release.id, "release_hash": release.release_hash},
    )


def create_validation_evidence(
    *,
    release_id: int,
    evidence_type: str,
    evidence_ref: str,
    summary: str,
    created_by: str,
    trace_id: str,
    trigger_source: str,
) -> ServiceResult:
    release = StrategyAnalysisRelease.objects.get(id=release_id)
    if release.approval_status != ReleaseApprovalStatus.VALIDATING or not release.release_hash:
        return ServiceResult(
            ResultStatus.BLOCKED,
            "release_not_validating",
            "只有已冻结的 validating 版本包可以记录验证证据",
            trace_id,
            trigger_source,
        )
    evidence = StrategyAnalysisReleaseValidationEvidence.objects.create(
        release=release,
        release_hash=release.release_hash,
        evidence_type=evidence_type,
        evidence_ref=evidence_ref,
        summary=summary,
        created_by=created_by,
    )
    StrategyAnalysisRelease.objects.filter(id=release_id).update(
        validation_evidence_count=StrategyAnalysisReleaseValidationEvidence.objects.filter(
            release_id=release_id,
            release_hash=release.release_hash,
        ).count()
    )
    return ServiceResult(
        ResultStatus.SUCCEEDED,
        "validation_evidence_created",
        "验证证据已记录",
        trace_id,
        trigger_source,
        {"evidence_id": evidence.id},
    )


def validate_release_integrity(
    release: StrategyAnalysisRelease,
    *,
    registry: CalculatorRegistry = default_registry,
) -> list[str]:
    errors: list[str] = []
    items = list(release.items.all())
    component_types = {item.component_type for item in items}
    required_types = {
        ReleaseItemComponentType.FEATURE_DEFINITION,
        ReleaseItemComponentType.ATOMIC_SIGNAL_DEFINITION,
        ReleaseItemComponentType.DOMAIN_SIGNAL_DEFINITION,
        ReleaseItemComponentType.MARKET_REGIME_DEFINITION,
        ReleaseItemComponentType.STRATEGY_ROUTE_POLICY,
        ReleaseItemComponentType.STRATEGY_ROUTE_RULE,
        ReleaseItemComponentType.STRATEGY_DEFINITION,
        ReleaseItemComponentType.STRATEGY_SIGNAL_QUALITY_RULE_SET,
        ReleaseItemComponentType.DECISION_POLICY_DEFINITION,
    }
    missing_types = sorted(str(item) for item in required_types - component_types)
    if missing_types:
        errors.append(f"版本包缺少组件类型：{','.join(missing_types)}")

    for item in items:
        if item.component_object_id is None:
            errors.append(f"{item.component_type}:{item.component_code} 缺少真实组件对象")
        if item.component_type not in IMPLEMENTED_FORMAL_COMPONENT_TYPES:
            errors.append(f"{item.component_type}:{item.component_code} 的正式组件校验尚未实现")

    feature_items = [item for item in items if item.component_type == ReleaseItemComponentType.FEATURE_DEFINITION]
    feature_definitions = {
        definition.id: definition
        for definition in FeatureDefinition.objects.filter(
            id__in=[item.component_object_id for item in feature_items if item.component_object_id is not None]
        )
    }
    for item in feature_items:
        definition = feature_definitions.get(item.component_object_id)
        if definition is None:
            errors.append(f"feature_definition:{item.component_code} 指向的真实定义不存在")
            continue
        if not definition.is_enabled:
            errors.append(f"feature_definition:{item.component_code} 已被禁用")
        if item.component_code != definition.feature_code:
            errors.append(f"feature_definition:{item.component_code} 组件代码与真实定义不一致")
        if item.definition_hash != definition.definition_hash:
            errors.append(f"feature_definition:{item.component_code} 定义指纹不一致")
        if item.algorithm_name != definition.algorithm_name or item.algorithm_version != definition.algorithm_version:
            errors.append(f"feature_definition:{item.component_code} 算法身份不一致")
        actual_params_hash = stable_hash(definition.params)
        if definition.params_hash != actual_params_hash or item.params_hash != actual_params_hash:
            errors.append(f"feature_definition:{item.component_code} 参数指纹不一致")

    feature_codes = {item.component_code for item in feature_items}
    atomic_items = [item for item in items if item.component_type == ReleaseItemComponentType.ATOMIC_SIGNAL_DEFINITION]
    atomic_definitions = {
        definition.id: definition
        for definition in AtomicSignalDefinition.objects.filter(
            id__in=[item.component_object_id for item in atomic_items if item.component_object_id is not None]
        )
    }
    domain_memberships: dict[str, int] = {}
    for domain_item in (item for item in items if item.component_type == ReleaseItemComponentType.DOMAIN_SIGNAL_DEFINITION):
        payload = domain_item.payload_summary or {}
        if domain_item.dependency_hash != domain_atomic_membership_hash(payload):
            errors.append(f"domain_signal_definition:{domain_item.component_code} 原子信号归属指纹不一致")
        codes = set(payload.get("allowed_atomic_signal_codes", [])) | set(payload.get("required_atomic_signal_codes", []))
        for code in codes:
            domain_memberships[str(code)] = domain_memberships.get(str(code), 0) + 1
    for item in atomic_items:
        definition = atomic_definitions.get(item.component_object_id)
        if definition is None:
            errors.append(f"atomic_signal_definition:{item.component_code} 指向的真实定义不存在")
            continue
        if definition.status != DefinitionLifecycleStatus.ACTIVE or not definition.enabled:
            errors.append(f"atomic_signal_definition:{item.component_code} 不是 active + enabled")
        actual_params_hash = stable_hash(definition.params)
        try:
            dependencies = normalize_feature_codes(definition.depends_on_feature_codes)
            actual_definition_hash = atomic_signal_definition_hash(
                signal_code=definition.signal_code,
                default_direction=definition.default_direction,
                algorithm_name=definition.algorithm_name,
                algorithm_version=definition.algorithm_version,
                params_hash=actual_params_hash,
                is_required=definition.is_required,
                depends_on_feature_codes=dependencies,
                output_type=definition.output_type,
            )
        except ValueError as exc:
            errors.append(f"atomic_signal_definition:{item.component_code} 依赖不合法：{exc}")
            continue
        if not set(dependencies).issubset(feature_codes):
            errors.append(f"atomic_signal_definition:{item.component_code} 的特征依赖未包含在版本包特征切片")
        if (
            item.component_code != definition.signal_code
            or item.algorithm_name != definition.algorithm_name
            or item.algorithm_version != definition.algorithm_version
            or definition.params_hash != actual_params_hash
            or item.params_hash != actual_params_hash
            or definition.definition_hash != actual_definition_hash
            or item.definition_hash != actual_definition_hash
            or item.dependency_hash != atomic_signal_dependency_hash(dependencies)
        ):
            errors.append(f"atomic_signal_definition:{item.component_code} 定义身份或指纹不一致")
        if domain_memberships.get(definition.signal_code, 0) != 1:
            errors.append(f"atomic_signal_definition:{item.component_code} 必须且只能归属一个领域")

    domain_codes = {
        item.component_code
        for item in items
        if item.component_type == ReleaseItemComponentType.DOMAIN_SIGNAL_DEFINITION
    }
    for code in ("trend", "momentum", "volatility"):
        if code not in domain_codes:
            errors.append(f"版本包缺少正式领域：{code}")

    for component_type in (
        ReleaseItemComponentType.MARKET_REGIME_DEFINITION,
        ReleaseItemComponentType.STRATEGY_ROUTE_POLICY,
        ReleaseItemComponentType.STRATEGY_SIGNAL_QUALITY_RULE_SET,
        ReleaseItemComponentType.DECISION_POLICY_DEFINITION,
    ):
        count = sum(1 for item in items if item.component_type == component_type)
        if count != 1:
            errors.append(f"{component_type} 必须恰好一个，当前 {count}")

    for item in items:
        calculator_type = CALCULATOR_TYPE_BY_COMPONENT.get(item.component_type)
        if not calculator_type:
            continue
        if not item.algorithm_name or not item.algorithm_version:
            errors.append(f"{item.component_type}:{item.component_code} 缺少算法身份")
            continue
        try:
            calculator = registry.resolve(
                calculator_type=calculator_type,
                algorithm_name=item.algorithm_name,
                algorithm_version=item.algorithm_version,
            )
            if item.component_type == ReleaseItemComponentType.FEATURE_DEFINITION:
                definition = feature_definitions.get(item.component_object_id)
                if definition and calculator.metadata.output_schema_version != definition.output_schema_version:
                    errors.append(f"feature_definition:{item.component_code} 输出 schema 与 calculator 不一致")
        except StrategyCalculatorError as exc:
            errors.append(f"{item.component_type}:{item.component_code} calculator 不可解析：{exc}")
    return errors


def approve_release(
    *,
    release_id: int,
    operator_id: str,
    reason: str,
    trace_id: str,
    trigger_source: str,
    registry: CalculatorRegistry = default_registry,
) -> ServiceResult:
    with transaction.atomic():
        release = StrategyAnalysisRelease.objects.select_for_update().get(id=release_id)
        if release.approval_status != ReleaseApprovalStatus.VALIDATING:
            return ServiceResult(ResultStatus.BLOCKED, "release_not_validating", "只有 validating 版本包可以批准", trace_id, trigger_source)
        current_hash = calculate_release_hash(release)
        if release.release_hash != current_hash:
            return ServiceResult(ResultStatus.BLOCKED, "release_hash_mismatch", "版本包指纹已失配", trace_id, trigger_source)
        evidence_refs = list(
            StrategyAnalysisReleaseValidationEvidence.objects.filter(
                release=release,
                release_hash=release.release_hash,
            ).values_list("id", flat=True)
        )
        if not evidence_refs:
            return ServiceResult(ResultStatus.BLOCKED, "validation_evidence_missing", "缺少验证证据，不能批准", trace_id, trigger_source)
        integrity_errors = validate_release_integrity(release, registry=registry)
        if integrity_errors:
            return ServiceResult(
                ResultStatus.BLOCKED,
                "release_integrity_failed",
                "版本包完整性校验失败",
                trace_id,
                trigger_source,
                {"errors": integrity_errors},
            )
        now = timezone.now()
        release.approval_status = ReleaseApprovalStatus.APPROVED
        release.approved_at_utc = now
        release.approved_by = operator_id
        release.validation_evidence_count = len(evidence_refs)
        release.save(
            update_fields=[
                "approval_status",
                "approved_at_utc",
                "approved_by",
                "validation_evidence_count",
                "updated_at_utc",
            ]
        )
        approval = StrategyAnalysisReleaseApproval.objects.create(
            release=release,
            release_hash=release.release_hash,
            action=ReleaseAction.APPROVE,
            validation_evidence_refs=evidence_refs,
            reason=reason,
            operator_id=operator_id,
            trace_id=trace_id,
            trigger_source=trigger_source,
        )
        record_alert_event(
            event_key=build_idempotency_key("strategy_release_approved", release.id, release.release_hash),
            source_module="StrategyAnalysisRelease",
            event_type="strategy_analysis_release_approved",
            event_category="strategy_analysis_release",
            severity=AlertSeverity.INFO,
            title_zh="策略分析版本包已批准",
            message_zh=f"版本包 {release.release_code} 已被批准。",
            trace_id=trace_id,
            trigger_source=trigger_source,
            related_object_type="StrategyAnalysisRelease",
            related_object_id=str(release.id),
            business_status=release.approval_status,
            payload_summary={"release_hash": release.release_hash, "approval_id": approval.id},
        )
    return ServiceResult(
        ResultStatus.SUCCEEDED,
        "release_approved",
        "版本包已批准",
        trace_id,
        trigger_source,
        {"release_id": release.id, "release_hash": release.release_hash, "approval_id": approval.id},
    )


def activate_release(
    *,
    release_id: int,
    operator_id: str,
    reason: str,
    trace_id: str,
    trigger_source: str,
    registry: CalculatorRegistry = default_registry,
) -> ServiceResult:
    try:
        with transaction.atomic():
            list(StrategyAnalysisRelease.objects.select_for_update().order_by("id").values_list("id", flat=True))
            release = StrategyAnalysisRelease.objects.get(id=release_id)
            if release.approval_status != ReleaseApprovalStatus.APPROVED:
                return ServiceResult(ResultStatus.BLOCKED, "release_not_approved", "只有 approved 版本包可以启用", trace_id, trigger_source)
            if release.release_hash != calculate_release_hash(release):
                return ServiceResult(ResultStatus.BLOCKED, "release_hash_mismatch", "版本包指纹已失配", trace_id, trigger_source)
            if not StrategyAnalysisReleaseApproval.objects.filter(
                release=release,
                release_hash=release.release_hash,
                action=ReleaseAction.APPROVE,
            ).exists():
                return ServiceResult(ResultStatus.BLOCKED, "release_approval_missing", "版本包缺少匹配的批准记录", trace_id, trigger_source)
            integrity_errors = validate_release_integrity(release, registry=registry)
            if integrity_errors:
                return ServiceResult(
                    ResultStatus.BLOCKED,
                    "release_integrity_failed",
                    "版本包完整性校验失败",
                    trace_id,
                    trigger_source,
                    {"errors": integrity_errors},
                )
            if release.is_active and release.active_slot == 1:
                return ServiceResult(
                    ResultStatus.SUCCEEDED,
                    "release_already_active",
                    "版本包已经启用",
                    trace_id,
                    trigger_source,
                    {"release_id": release.id, "release_hash": release.release_hash},
                )
            previous = StrategyAnalysisRelease.objects.filter(active_slot=1).exclude(id=release.id).first()
            if previous:
                previous.is_active = False
                previous.active_slot = None
                previous.deactivated_at_utc = timezone.now()
                previous.save(update_fields=["is_active", "active_slot", "deactivated_at_utc", "updated_at_utc"])
            release.is_active = True
            release.active_slot = 1
            release.activated_at_utc = timezone.now()
            release.activated_by = operator_id
            release.save(update_fields=["is_active", "active_slot", "activated_at_utc", "activated_by", "updated_at_utc"])
            activation = StrategyAnalysisReleaseActivation.objects.create(
                release=release,
                release_hash=release.release_hash,
                action=ReleaseAction.ACTIVATE,
                previous_release=previous,
                operator_id=operator_id,
                reason=reason,
                trace_id=trace_id,
                trigger_source=trigger_source,
            )
            record_alert_event(
                event_key=build_idempotency_key("strategy_release_activated", activation.id),
                source_module="StrategyAnalysisRelease",
                event_type="strategy_analysis_release_activated",
                event_category="strategy_analysis_release",
                severity=AlertSeverity.INFO,
                title_zh="策略分析版本包已启用",
                message_zh=f"版本包 {release.release_code} 已启用，新编排将使用该版本包。",
                trace_id=trace_id,
                trigger_source=trigger_source,
                related_object_type="StrategyAnalysisRelease",
                related_object_id=str(release.id),
                business_status=release.approval_status,
                payload_summary={"release_hash": release.release_hash, "activation_id": activation.id},
            )
    except IntegrityError:
        return ServiceResult(
            ResultStatus.BLOCKED,
            "active_release_conflict",
            "并发启用冲突，数据库已阻止产生多个当前版本包",
            trace_id,
            trigger_source,
        )
    return ServiceResult(
        ResultStatus.SUCCEEDED,
        "release_activated",
        "版本包已启用",
        trace_id,
        trigger_source,
        {"release_id": release.id, "release_hash": release.release_hash, "activation_id": activation.id},
    )


def get_current_active_release() -> StrategyAnalysisRelease | None:
    return StrategyAnalysisRelease.objects.filter(
        approval_status=ReleaseApprovalStatus.APPROVED,
        is_active=True,
        active_slot=1,
    ).order_by("-activated_at_utc", "-id").first()


def resolve_frozen_slice(
    *,
    release_id: int,
    release_hash: str,
    component_type: str,
    expected_definition_set_hash: str = "",
) -> FrozenReleaseSlice:
    release = StrategyAnalysisRelease.objects.get(id=release_id)
    if release.approval_status not in {ReleaseApprovalStatus.APPROVED, ReleaseApprovalStatus.INVALIDATED}:
        raise ValueError("版本包没有已批准身份")
    if release.release_hash != release_hash:
        raise ValueError("版本包指纹不匹配")
    if calculate_release_hash(release) != release_hash:
        raise ValueError("版本包内容已被修改")
    if not StrategyAnalysisReleaseApproval.objects.filter(
        release=release,
        release_hash=release_hash,
        action=ReleaseAction.APPROVE,
    ).exists():
        raise ValueError("版本包缺少匹配的批准记录")
    if not StrategyAnalysisReleaseActivation.objects.filter(
        release=release,
        release_hash=release_hash,
        action__in=[ReleaseAction.ACTIVATE, ReleaseAction.ROLLBACK],
    ).exists():
        raise ValueError("版本包没有历史启用事实")
    items = tuple(release.items.filter(component_type=component_type).order_by("sort_order", "component_code", "id"))
    actual_hash = calculate_definition_set_hash(items)
    if expected_definition_set_hash and actual_hash != expected_definition_set_hash:
        raise ValueError("模块定义集指纹不匹配")
    return FrozenReleaseSlice(release=release, component_type=component_type, items=items, definition_set_hash=actual_hash)
