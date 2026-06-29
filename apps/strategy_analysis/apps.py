"""StrategyAnalysis 模块：Django app 配置；不访问外部服务，不涉及交易执行。"""

from __future__ import annotations

from django.apps import AppConfig


class StrategyAnalysisConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.strategy_analysis"
    verbose_name = "策略分析"

    def ready(self) -> None:
        from apps.strategy_calculator.atomic_signal import AtomicConditionCalculator, FeatureCompareCalculator
        from apps.strategy_calculator.decision_policy import PositionPolicyCalculator
        from apps.strategy_calculator.domain_signal import SingleAtomicPassthroughCalculator
        from apps.strategy_calculator.errors import DuplicateCalculatorError
        from apps.strategy_calculator.feature_layer import KlinePriceFeatureCalculator
        from apps.strategy_calculator.registry import default_registry

        for calculator in (
            KlinePriceFeatureCalculator(),
            AtomicConditionCalculator(),
            FeatureCompareCalculator(),
            SingleAtomicPassthroughCalculator(),
            PositionPolicyCalculator(),
        ):
            try:
                default_registry.register(calculator)
            except DuplicateCalculatorError:
                pass
