"""PipelineOrchestrator 模块：定义正式步骤 Registry；不读写数据库；不访问外部服务；不涉及交易执行。"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Iterable


REGISTRY_VERSION = "p0.2"
PIPELINE_CODE = "main_trading_pipeline"


@dataclass(frozen=True)
class StepDefinition:
    pipeline_code: str
    registry_version: str
    step_code: str
    step_order: int
    module_code: str
    adapter_code: str
    adapter_version: str
    depends_on_step_codes: tuple[str, ...]
    execution_mode: str = "synchronous"
    is_required: bool = True
    is_conditional: bool = False
    timeout_policy: str = "default"
    result_mapping_version: str = "1.0"
    enabled: bool = True


FORMAL_STEPS: tuple[StepDefinition, ...] = (
    StepDefinition(PIPELINE_CODE, REGISTRY_VERSION, "binance_account_sync", 10, "binance_account_sync", "BinanceAccountSyncStepAdapter", "1.0", ()),
    StepDefinition(PIPELINE_CODE, REGISTRY_VERSION, "data_collection", 20, "market_data", "DataCollectionStepAdapter", "1.0", ("binance_account_sync",)),
    StepDefinition(PIPELINE_CODE, REGISTRY_VERSION, "data_quality", 30, "market_data", "DataQualityStepAdapter", "1.0", ("data_collection",)),
    StepDefinition(PIPELINE_CODE, REGISTRY_VERSION, "data_backfill", 40, "market_data", "DataBackfillStepAdapter", "1.0", ("data_quality",), is_required=False, is_conditional=True),
    StepDefinition(PIPELINE_CODE, REGISTRY_VERSION, "market_snapshot", 50, "market_data", "MarketSnapshotStepAdapter", "1.0", ("data_quality",)),
    StepDefinition(PIPELINE_CODE, REGISTRY_VERSION, "feature_layer", 60, "strategy_analysis", "FeatureLayerStepAdapter", "1.0", ("market_snapshot",)),
    StepDefinition(PIPELINE_CODE, REGISTRY_VERSION, "atomic_signals", 70, "strategy_analysis", "AtomicSignalStepAdapter", "1.0", ("feature_layer",)),
    StepDefinition(PIPELINE_CODE, REGISTRY_VERSION, "domain_signals", 80, "strategy_analysis", "DomainSignalStepAdapter", "1.0", ("atomic_signals",)),
    StepDefinition(PIPELINE_CODE, REGISTRY_VERSION, "market_regime", 90, "strategy_analysis", "MarketRegimeStepAdapter", "1.0", ("domain_signals",)),
    StepDefinition(PIPELINE_CODE, REGISTRY_VERSION, "strategy_routing", 100, "strategy_analysis", "StrategyRoutingStepAdapter", "1.0", ("market_regime",)),
    StepDefinition(PIPELINE_CODE, REGISTRY_VERSION, "strategy_signals", 110, "strategy_analysis", "StrategySignalStepAdapter", "1.0", ("strategy_routing",)),
    StepDefinition(PIPELINE_CODE, REGISTRY_VERSION, "strategy_signal_quality", 120, "strategy_analysis", "StrategySignalQualityStepAdapter", "1.0", ("strategy_signals",)),
    StepDefinition(PIPELINE_CODE, REGISTRY_VERSION, "decision_snapshot", 130, "strategy_analysis", "DecisionSnapshotStepAdapter", "1.0", ("strategy_signal_quality",)),
    StepDefinition(PIPELINE_CODE, REGISTRY_VERSION, "price_snapshot", 140, "price_snapshot", "PriceSnapshotStepAdapter", "1.0", ("decision_snapshot",), is_required=False, is_conditional=True),
    StepDefinition(PIPELINE_CODE, REGISTRY_VERSION, "order_plan", 150, "order_plan", "OrderPlanStepAdapter", "1.0", ("price_snapshot",), is_required=False, is_conditional=True),
    StepDefinition(PIPELINE_CODE, REGISTRY_VERSION, "risk_check", 160, "risk_check", "RiskCheckStepAdapter", "1.0", ("order_plan",), is_required=False, is_conditional=True),
    StepDefinition(PIPELINE_CODE, REGISTRY_VERSION, "execution_preparation", 170, "execution_preparation", "ExecutionPreparationStepAdapter", "1.0", ("risk_check",), is_required=False, is_conditional=True),
    StepDefinition(PIPELINE_CODE, REGISTRY_VERSION, "order_submission", 180, "execution", "OrderSubmissionStepAdapter", "1.0", ("execution_preparation",), execution_mode="asynchronous_wait", is_required=False, is_conditional=True),
)


class RegistryValidationError(ValueError):
    pass


def enabled_steps() -> tuple[StepDefinition, ...]:
    steps = tuple(step for step in FORMAL_STEPS if step.enabled)
    validate_registry(steps)
    return steps


def registry_hash(steps: Iterable[StepDefinition] | None = None) -> str:
    payload = [asdict(step) for step in (tuple(steps) if steps is not None else enabled_steps())]
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def adapter_versions(steps: Iterable[StepDefinition] | None = None) -> dict[str, str]:
    return {step.adapter_code: step.adapter_version for step in (tuple(steps) if steps is not None else enabled_steps())}


def mapping_versions(steps: Iterable[StepDefinition] | None = None) -> dict[str, str]:
    return {step.step_code: step.result_mapping_version for step in (tuple(steps) if steps is not None else enabled_steps())}


def validate_registry(steps: Iterable[StepDefinition]) -> None:
    ordered = tuple(steps)
    step_codes = [step.step_code for step in ordered]
    if len(step_codes) != len(set(step_codes)):
        raise RegistryValidationError("step_code duplicated")
    orders = [step.step_order for step in ordered]
    if len(orders) != len(set(orders)):
        raise RegistryValidationError("step_order duplicated")
    known = set(step_codes)
    for step in ordered:
        for dependency in step.depends_on_step_codes:
            if dependency not in known:
                raise RegistryValidationError(f"unknown dependency: {step.step_code}->{dependency}")
    _assert_no_cycles(ordered)


def _assert_no_cycles(steps: tuple[StepDefinition, ...]) -> None:
    graph = {step.step_code: set(step.depends_on_step_codes) for step in steps}
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node: str) -> None:
        if node in visiting:
            raise RegistryValidationError("registry dependency cycle")
        if node in visited:
            return
        visiting.add(node)
        for dependency in graph[node]:
            visit(dependency)
        visiting.remove(node)
        visited.add(node)

    for code in graph:
        visit(code)


def ordered_step_codes() -> tuple[str, ...]:
    return tuple(step.step_code for step in sorted(enabled_steps(), key=lambda item: item.step_order))


def step_by_code(step_code: str) -> StepDefinition:
    for step in enabled_steps():
        if step.step_code == step_code:
            return step
    raise RegistryValidationError(f"step not found: {step_code}")
