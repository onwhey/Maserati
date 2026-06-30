"""StrategyAnalysis 模块：管理策略配置工作区；读写数据库，不访问 Redis 或外部服务，不发送 Hermes，不调用大模型，不涉及交易执行，不允许真实交易。"""

from __future__ import annotations

from typing import Any, Iterable

from django.core.exceptions import ObjectDoesNotExist
from django.db import transaction

from apps.audit.services import record_audit
from apps.foundation.results import ResultStatus, ServiceResult

from ..definition_hashes import normalize_atomic_signal_codes, normalize_domain_codes, normalize_feature_codes
from ..models import (
    AtomicSignalDefinition,
    DefinitionLifecycleStatus,
    DomainSignalDefinition,
    MarketRegimeDefinition,
    ReleaseItemComponentType,
    StrategyAnalysisWorkspace,
    StrategyAnalysisWorkspaceItem,
    StrategyDefinition,
    StrategyRoutePolicy,
    StrategyRouteRule,
)
from .release import (
    COMPONENT_MODEL_BY_TYPE,
    ReleaseComponentSelection,
    create_draft_release_from_component_selections,
)


DEFAULT_WORKSPACE_CODE = "default_strategy_analysis_workspace"
DEFAULT_WORKSPACE_SLOT = 1

INCLUSION_MANAGED_COMPONENT_TYPES = {
    ReleaseItemComponentType.ATOMIC_SIGNAL_DEFINITION,
    ReleaseItemComponentType.DOMAIN_SIGNAL_DEFINITION,
    ReleaseItemComponentType.MARKET_REGIME_DEFINITION,
    ReleaseItemComponentType.STRATEGY_ROUTE_POLICY,
    ReleaseItemComponentType.STRATEGY_ROUTE_RULE,
    ReleaseItemComponentType.STRATEGY_DEFINITION,
    ReleaseItemComponentType.STRATEGY_SIGNAL_QUALITY_RULE_SET,
    ReleaseItemComponentType.DECISION_POLICY_DEFINITION,
}

RELEASE_SORT_BASE = {
    ReleaseItemComponentType.FEATURE_DEFINITION: 1000,
    ReleaseItemComponentType.ATOMIC_SIGNAL_DEFINITION: 2000,
    ReleaseItemComponentType.DOMAIN_SIGNAL_DEFINITION: 3000,
    ReleaseItemComponentType.MARKET_REGIME_DEFINITION: 4000,
    ReleaseItemComponentType.STRATEGY_ROUTE_POLICY: 5000,
    ReleaseItemComponentType.STRATEGY_ROUTE_RULE: 5100,
    ReleaseItemComponentType.STRATEGY_DEFINITION: 6000,
    ReleaseItemComponentType.STRATEGY_SIGNAL_QUALITY_RULE_SET: 7000,
    ReleaseItemComponentType.DECISION_POLICY_DEFINITION: 8000,
}


def get_or_create_default_workspace(*, operator_id: str = "") -> StrategyAnalysisWorkspace:
    workspace, created = StrategyAnalysisWorkspace.objects.get_or_create(
        default_slot=DEFAULT_WORKSPACE_SLOT,
        defaults={
            "workspace_code": DEFAULT_WORKSPACE_CODE,
            "display_name": "默认策略分析配置",
            "description": "OpsConsole 当前策略分析配置工作区。",
            "created_by": operator_id,
            "updated_by": operator_id,
        },
    )
    if created:
        return workspace
    return workspace


def _component_code(component_type: ReleaseItemComponentType, component: Any) -> str:
    if component_type == ReleaseItemComponentType.FEATURE_DEFINITION:
        return component.feature_code
    if component_type == ReleaseItemComponentType.ATOMIC_SIGNAL_DEFINITION:
        return component.signal_code
    if component_type == ReleaseItemComponentType.DOMAIN_SIGNAL_DEFINITION:
        return component.domain_code
    if component_type == ReleaseItemComponentType.MARKET_REGIME_DEFINITION:
        return component.definition_code
    if component_type == ReleaseItemComponentType.STRATEGY_ROUTE_POLICY:
        return component.policy_code
    if component_type == ReleaseItemComponentType.STRATEGY_ROUTE_RULE:
        return component.rule_code
    if component_type == ReleaseItemComponentType.STRATEGY_DEFINITION:
        return component.strategy_code
    if component_type == ReleaseItemComponentType.STRATEGY_SIGNAL_QUALITY_RULE_SET:
        return component.rule_set_code
    if component_type == ReleaseItemComponentType.DECISION_POLICY_DEFINITION:
        return component.policy_code
    raise ValueError("不支持的组件类型")


def _component_version(component_type: ReleaseItemComponentType, component: Any) -> str:
    if component_type == ReleaseItemComponentType.FEATURE_DEFINITION:
        return component.definition_version
    if component_type == ReleaseItemComponentType.STRATEGY_ROUTE_POLICY:
        return component.policy_version
    if component_type == ReleaseItemComponentType.STRATEGY_DEFINITION:
        return component.strategy_version
    if component_type == ReleaseItemComponentType.STRATEGY_SIGNAL_QUALITY_RULE_SET:
        return component.rule_set_version
    if component_type == ReleaseItemComponentType.DECISION_POLICY_DEFINITION:
        return component.policy_version
    return getattr(component, "algorithm_version", "")


def _component_definition_hash(component_type: ReleaseItemComponentType, component: Any) -> str:
    if component_type == ReleaseItemComponentType.STRATEGY_ROUTE_RULE:
        return component.rule_hash
    if component_type == ReleaseItemComponentType.STRATEGY_SIGNAL_QUALITY_RULE_SET:
        return component.rule_set_hash
    return component.definition_hash


def _component_is_selectable(component_type: ReleaseItemComponentType, component: Any) -> bool:
    if component_type == ReleaseItemComponentType.FEATURE_DEFINITION:
        return bool(component.is_enabled)
    return component.status == DefinitionLifecycleStatus.ACTIVE and bool(component.enabled)


def _normalize_component_type(component_type: str) -> ReleaseItemComponentType:
    return ReleaseItemComponentType(component_type)


def _load_component_for_item(item: StrategyAnalysisWorkspaceItem) -> Any:
    component_type = _normalize_component_type(item.component_type)
    component = COMPONENT_MODEL_BY_TYPE[component_type].objects.get(id=item.component_object_id)
    if _component_code(component_type, component) != item.component_code:
        raise ValueError(f"{item.component_type}:{item.component_code} 指向的组件代码已变化")
    if _component_definition_hash(component_type, component) != item.definition_hash:
        raise ValueError(f"{item.component_type}:{item.component_code} 指向的定义指纹已变化")
    if not _component_is_selectable(component_type, component):
        raise ValueError(f"{item.component_type}:{item.component_code} 当前不可被发布包选择")
    return component


def _record_workspace_audit(
    *,
    workspace: StrategyAnalysisWorkspace,
    operator_id: str,
    operation_type: str,
    reason: str,
    before_state: dict[str, Any],
    after_state: dict[str, Any],
    evidence: dict[str, Any],
    trace_id: str,
    trigger_source: str,
) -> None:
    if not operator_id:
        return
    record_audit(
        operator_id=operator_id,
        operation_type=operation_type,
        target_object_type="StrategyAnalysisWorkspace",
        target_object_id=str(workspace.id),
        before_state_summary=before_state,
        after_state_summary=after_state,
        reason=reason,
        evidence=evidence,
        result="succeeded",
        trace_id=trace_id,
        trigger_source=trigger_source,
    )


def upsert_workspace_item(
    *,
    component_type: str,
    component_object_id: int,
    is_included: bool,
    operator_id: str,
    reason: str,
    trace_id: str,
    trigger_source: str,
) -> ServiceResult:
    try:
        normalized_type = _normalize_component_type(component_type)
    except ValueError:
        return ServiceResult(ResultStatus.BLOCKED, "invalid_component_type", "组件类型不受支持", trace_id, trigger_source)

    try:
        component = COMPONENT_MODEL_BY_TYPE[normalized_type].objects.get(id=component_object_id)
    except ObjectDoesNotExist:
        return ServiceResult(ResultStatus.BLOCKED, "workspace_component_not_found", "选择的组件定义不存在", trace_id, trigger_source)

    if not _component_is_selectable(normalized_type, component):
        return ServiceResult(ResultStatus.BLOCKED, "workspace_component_not_selectable", "选择的组件定义当前不可用", trace_id, trigger_source)

    inclusion_managed = normalized_type in INCLUSION_MANAGED_COMPONENT_TYPES
    normalized_included = bool(is_included) if inclusion_managed else False
    component_code = _component_code(normalized_type, component)
    defaults = {
        "component_object_id": component.id,
        "component_version": _component_version(normalized_type, component),
        "definition_hash": _component_definition_hash(normalized_type, component),
        "inclusion_managed": inclusion_managed,
        "is_included": normalized_included,
        "selection_reason": reason.strip(),
        "updated_by": operator_id,
        "trace_id": trace_id,
        "trigger_source": trigger_source,
    }

    with transaction.atomic():
        workspace = get_or_create_default_workspace(operator_id=operator_id)
        existing = (
            StrategyAnalysisWorkspaceItem.objects.select_for_update()
            .filter(workspace=workspace, component_type=normalized_type, component_code=component_code)
            .first()
        )
        before = (
            {
                "item_id": existing.id,
                "component_object_id": existing.component_object_id,
                "component_version": existing.component_version,
                "is_included": existing.is_included,
            }
            if existing
            else {}
        )
        item, _created = StrategyAnalysisWorkspaceItem.objects.update_or_create(
            workspace=workspace,
            component_type=normalized_type,
            component_code=component_code,
            defaults=defaults,
        )
        workspace.updated_by = operator_id
        workspace.save(update_fields=["updated_by", "updated_at_utc"])
        after = {
            "item_id": item.id,
            "component_type": item.component_type,
            "component_code": item.component_code,
            "component_object_id": item.component_object_id,
            "component_version": item.component_version,
            "inclusion_managed": item.inclusion_managed,
            "is_included": item.is_included,
        }

    _record_workspace_audit(
        workspace=workspace,
        operator_id=operator_id,
        operation_type="strategy_workspace_item_upsert",
        reason=reason,
        before_state=before,
        after_state=after,
        evidence={"component_type": normalized_type, "component_object_id": component_object_id},
        trace_id=trace_id,
        trigger_source=trigger_source,
    )
    return ServiceResult(
        ResultStatus.SUCCEEDED,
        "strategy_workspace_item_upserted",
        "当前策略配置已更新",
        trace_id,
        trigger_source,
        {"workspace_id": workspace.id, "item_id": item.id},
    )


def remove_workspace_item(
    *,
    item_id: int,
    operator_id: str,
    reason: str,
    trace_id: str,
    trigger_source: str,
) -> ServiceResult:
    with transaction.atomic():
        workspace = get_or_create_default_workspace(operator_id=operator_id)
        try:
            item = StrategyAnalysisWorkspaceItem.objects.select_for_update().get(workspace=workspace, id=item_id)
        except ObjectDoesNotExist:
            return ServiceResult(ResultStatus.BLOCKED, "workspace_item_not_found", "当前配置项不存在", trace_id, trigger_source)
        before = {
            "item_id": item.id,
            "component_type": item.component_type,
            "component_code": item.component_code,
            "component_object_id": item.component_object_id,
        }
        item.delete()
        workspace.updated_by = operator_id
        workspace.save(update_fields=["updated_by", "updated_at_utc"])

    _record_workspace_audit(
        workspace=workspace,
        operator_id=operator_id,
        operation_type="strategy_workspace_item_remove",
        reason=reason,
        before_state=before,
        after_state={},
        evidence=before,
        trace_id=trace_id,
        trigger_source=trigger_source,
    )
    return ServiceResult(
        ResultStatus.SUCCEEDED,
        "strategy_workspace_item_removed",
        "当前策略配置项已移除",
        trace_id,
        trigger_source,
        {"workspace_id": workspace.id, "removed_item_id": item_id},
    )


def _included_items_by_type(items: Iterable[StrategyAnalysisWorkspaceItem]) -> dict[ReleaseItemComponentType, list[StrategyAnalysisWorkspaceItem]]:
    grouped: dict[ReleaseItemComponentType, list[StrategyAnalysisWorkspaceItem]] = {}
    for item in items:
        component_type = _normalize_component_type(item.component_type)
        if component_type == ReleaseItemComponentType.FEATURE_DEFINITION:
            continue
        if not item.is_included:
            continue
        grouped.setdefault(component_type, []).append(item)
    return grouped


def _dependency_errors(
    *,
    included_by_type: dict[ReleaseItemComponentType, list[StrategyAnalysisWorkspaceItem]],
    loaded_components: dict[int, Any],
) -> list[str]:
    errors: list[str] = []
    included_atomic_codes = {
        item.component_code
        for item in included_by_type.get(ReleaseItemComponentType.ATOMIC_SIGNAL_DEFINITION, [])
    }
    included_domain_codes = {
        item.component_code
        for item in included_by_type.get(ReleaseItemComponentType.DOMAIN_SIGNAL_DEFINITION, [])
    }
    included_strategy_codes = {
        item.component_code
        for item in included_by_type.get(ReleaseItemComponentType.STRATEGY_DEFINITION, [])
    }

    for item in included_by_type.get(ReleaseItemComponentType.DOMAIN_SIGNAL_DEFINITION, []):
        definition: DomainSignalDefinition = loaded_components[item.id]
        for code in normalize_atomic_signal_codes(definition.required_atomic_signal_codes, allow_empty=True):
            if code not in included_atomic_codes:
                errors.append(f"领域 {item.component_code} 缺少必需原子 {code}")

    for item in included_by_type.get(ReleaseItemComponentType.MARKET_REGIME_DEFINITION, []):
        definition: MarketRegimeDefinition = loaded_components[item.id]
        for code in normalize_domain_codes(definition.required_domain_codes, allow_empty=True):
            if code not in included_domain_codes:
                errors.append(f"市场环境 {item.component_code} 缺少必需领域 {code}")

    for item in included_by_type.get(ReleaseItemComponentType.STRATEGY_DEFINITION, []):
        definition: StrategyDefinition = loaded_components[item.id]
        for code in normalize_domain_codes(definition.required_domain_codes, allow_empty=True):
            if code not in included_domain_codes:
                errors.append(f"策略 {item.component_code} 缺少必需领域 {code}")

    for item in included_by_type.get(ReleaseItemComponentType.STRATEGY_ROUTE_RULE, []):
        definition: StrategyRouteRule = loaded_components[item.id]
        selected = definition.selected_strategy_definition
        if selected and selected.strategy_code not in included_strategy_codes:
            errors.append(f"路由规则 {item.component_code} 选择的策略 {selected.strategy_code} 未纳入当前组合")

    for item in included_by_type.get(ReleaseItemComponentType.STRATEGY_ROUTE_POLICY, []):
        definition: StrategyRoutePolicy = loaded_components[item.id]
        fallback = definition.fallback_strategy_definition
        if fallback and fallback.strategy_code not in included_strategy_codes:
            errors.append(f"路由策略 {item.component_code} fallback 策略 {fallback.strategy_code} 未纳入当前组合")

    return errors


def _release_selections_from_workspace(
    workspace: StrategyAnalysisWorkspace,
) -> tuple[list[ReleaseComponentSelection], list[str]]:
    items = list(workspace.items.order_by("component_type", "component_code", "id"))
    feature_items = {
        item.component_code: item
        for item in items
        if item.component_type == ReleaseItemComponentType.FEATURE_DEFINITION
    }
    included_by_type = _included_items_by_type(items)
    included_non_feature_items = [
        item
        for component_type in RELEASE_SORT_BASE
        if component_type != ReleaseItemComponentType.FEATURE_DEFINITION
        for item in sorted(included_by_type.get(component_type, []), key=lambda value: (value.component_code, value.id))
    ]
    if not included_non_feature_items:
        return [], ["当前配置没有从原子层往上纳入任何组件"]

    loaded_components: dict[int, Any] = {}
    errors: list[str] = []
    for item in included_non_feature_items:
        try:
            loaded_components[item.id] = _load_component_for_item(item)
        except (ObjectDoesNotExist, ValueError) as exc:
            errors.append(str(exc))

    if errors:
        return [], errors

    required_feature_codes: set[str] = set()
    for item in included_by_type.get(ReleaseItemComponentType.ATOMIC_SIGNAL_DEFINITION, []):
        definition: AtomicSignalDefinition = loaded_components[item.id]
        required_feature_codes.update(normalize_feature_codes(definition.depends_on_feature_codes))

    inferred_feature_items: list[StrategyAnalysisWorkspaceItem] = []
    for feature_code in sorted(required_feature_codes):
        feature_item = feature_items.get(feature_code)
        if feature_item is None:
            errors.append(f"原子信号依赖的特征 {feature_code} 尚未选择具体版本")
            continue
        try:
            _load_component_for_item(feature_item)
        except (ObjectDoesNotExist, ValueError) as exc:
            errors.append(str(exc))
            continue
        inferred_feature_items.append(feature_item)

    errors.extend(_dependency_errors(included_by_type=included_by_type, loaded_components=loaded_components))
    if errors:
        return [], errors

    selected_items = inferred_feature_items + included_non_feature_items
    selections: list[ReleaseComponentSelection] = []
    order_offsets: dict[ReleaseItemComponentType, int] = {}
    for item in selected_items:
        component_type = _normalize_component_type(item.component_type)
        order_offsets[component_type] = order_offsets.get(component_type, 0) + 10
        selections.append(
            ReleaseComponentSelection(
                component_type=component_type,
                component_object_id=item.component_object_id,
                sort_order=RELEASE_SORT_BASE[component_type] + order_offsets[component_type],
            )
        )
    return selections, []


def generate_release_from_workspace(
    *,
    release_code: str,
    display_name: str,
    description: str,
    operator_id: str,
    reason: str,
    trace_id: str,
    trigger_source: str,
) -> ServiceResult:
    workspace = get_or_create_default_workspace(operator_id=operator_id)
    selections, errors = _release_selections_from_workspace(workspace)
    if errors:
        return ServiceResult(
            ResultStatus.BLOCKED,
            "strategy_workspace_dependency_invalid",
            "当前策略配置依赖不完整，不能生成版本包草稿",
            trace_id,
            trigger_source,
            {"workspace_id": workspace.id, "error_count": len(errors), "errors": errors},
        )

    result = create_draft_release_from_component_selections(
        release_code=release_code,
        display_name=display_name,
        description=description,
        selections=selections,
        operator_id=operator_id,
        reason=reason,
        trace_id=trace_id,
        trigger_source=trigger_source,
    )
    if result.status == ResultStatus.SUCCEEDED:
        result.data["workspace_id"] = workspace.id
    return result
