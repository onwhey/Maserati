"""PipelineOrchestrator adapter registry.

Module: PipelineOrchestrator
Responsibility: provide explicit adapter lookup for formal orchestration steps.
Not responsible for business logic, database writes, Redis, external services,
Hermes, LLM calls, or trade execution.
"""

from __future__ import annotations

from collections.abc import Mapping

from .base import BusinessStepAdapter
from .business import (
    AtomicSignalStepAdapter,
    BinanceAccountSyncStepAdapter,
    DataBackfillStepAdapter,
    DataCollectionStepAdapter,
    DataQualityStepAdapter,
    DecisionSnapshotStepAdapter,
    DomainSignalStepAdapter,
    ExecutionPreparationStepAdapter,
    FeatureLayerStepAdapter,
    FillSyncStepAdapter,
    MarketRegimeStepAdapter,
    MarketSnapshotStepAdapter,
    OrderPlanStepAdapter,
    OrderStatusSyncStepAdapter,
    OrderSubmissionStepAdapter,
    PriceSnapshotStepAdapter,
    RiskCheckStepAdapter,
    StrategyRoutingStepAdapter,
    StrategySignalQualityStepAdapter,
    StrategySignalStepAdapter,
)


def default_adapter_registry() -> dict[str, BusinessStepAdapter]:
    adapters: tuple[BusinessStepAdapter, ...] = (
        BinanceAccountSyncStepAdapter(),
        DataCollectionStepAdapter(),
        DataQualityStepAdapter(),
        DataBackfillStepAdapter(),
        MarketSnapshotStepAdapter(),
        FeatureLayerStepAdapter(),
        AtomicSignalStepAdapter(),
        DomainSignalStepAdapter(),
        MarketRegimeStepAdapter(),
        StrategyRoutingStepAdapter(),
        StrategySignalStepAdapter(),
        StrategySignalQualityStepAdapter(),
        DecisionSnapshotStepAdapter(),
        PriceSnapshotStepAdapter(),
        OrderPlanStepAdapter(),
        RiskCheckStepAdapter(),
        ExecutionPreparationStepAdapter(),
        OrderSubmissionStepAdapter(),
        OrderStatusSyncStepAdapter(),
        FillSyncStepAdapter(),
    )
    return {adapter.adapter_code: adapter for adapter in adapters}


def get_adapter(adapter_code: str, registry: Mapping[str, BusinessStepAdapter] | None = None) -> BusinessStepAdapter:
    source = registry or default_adapter_registry()
    try:
        return source[adapter_code]
    except KeyError as exc:
        raise LookupError(f"adapter_not_registered:{adapter_code}") from exc

