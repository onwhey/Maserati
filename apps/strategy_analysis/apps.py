"""StrategyAnalysis 模块：Django app 配置；不访问外部服务，不涉及交易执行。"""

from __future__ import annotations

from django.apps import AppConfig


class StrategyAnalysisConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.strategy_analysis"
    verbose_name = "策略分析"

    def ready(self) -> None:
        from apps.strategy_calculator.atomic_signal import (
            AtomicConditionCalculator,
            FeatureCompareCalculator,
            PivotStructureAtomicCalculator,
        )
        from apps.strategy_calculator.decision_policy import PositionPolicyCalculator
        from apps.strategy_calculator.domain_signal import (
            GroupedAtomicAggregationCalculator,
            GroupedAtomicAggregationV11Calculator,
            GroupedAtomicAggregationV2Calculator,
            GroupedAtomicAggregationV3Calculator,
            SingleAtomicPassthroughCalculator,
        )
        from apps.strategy_calculator.errors import DuplicateCalculatorError
        from apps.strategy_calculator.feature_layer import KlinePriceFeatureCalculator, PivotSupportResistanceFeatureCalculator
        from apps.strategy_calculator.market_regime import (
            ContextStructureRegimeCalculator,
            ContextStructureRegimeV2Calculator,
            ContextStructureRegimeV3Calculator,
            ContextStructureRegimeV4Calculator,
            ContextStructureRegimeV5Calculator,
            ContextStructureRegimeV6Calculator,
            ContextStructureRegimeV61Calculator,
            ContextStructureRegimeV7Calculator,
        )
        from apps.strategy_calculator.registry import default_registry
        from apps.strategy_calculator.strategy_signal import (
            LongPullbackSupportCalculator,
            LongTrendFollowingCalculator,
            NoTradeStrategyCalculator,
            ShortReboundPressureCalculator,
            ShortTrendFollowingCalculator,
        )

        for calculator in (
            KlinePriceFeatureCalculator(),
            PivotSupportResistanceFeatureCalculator(),
            AtomicConditionCalculator(),
            FeatureCompareCalculator(),
            PivotStructureAtomicCalculator(),
            GroupedAtomicAggregationCalculator(),
            GroupedAtomicAggregationV11Calculator(),
            GroupedAtomicAggregationV2Calculator(),
            GroupedAtomicAggregationV3Calculator(),
            SingleAtomicPassthroughCalculator(),
            ContextStructureRegimeCalculator(),
            ContextStructureRegimeV2Calculator(),
            ContextStructureRegimeV3Calculator(),
            ContextStructureRegimeV4Calculator(),
            ContextStructureRegimeV5Calculator(),
            ContextStructureRegimeV6Calculator(),
            ContextStructureRegimeV61Calculator(),
            ContextStructureRegimeV7Calculator(),
            LongTrendFollowingCalculator(),
            LongPullbackSupportCalculator(),
            ShortTrendFollowingCalculator(),
            ShortReboundPressureCalculator(),
            NoTradeStrategyCalculator(),
            PositionPolicyCalculator(),
        ):
            try:
                default_registry.register(calculator)
            except DuplicateCalculatorError:
                pass
