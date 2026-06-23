"""AtomicSignal 模块：幂等初始化默认定义；写数据库，不访问外部服务，不执行交易。"""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from apps.strategy_analysis.definition_hashes import (
    atomic_signal_definition_hash,
    normalize_feature_codes,
)
from apps.strategy_analysis.models import (
    AtomicSignalDefinition,
    AtomicSignalDirection,
    AtomicSignalOutputType,
    DefinitionLifecycleStatus,
    FeatureDefinition,
)
from apps.strategy_calculator.contracts import CalculatorType
from apps.strategy_calculator.registry import default_registry
from apps.strategy_calculator.utils import stable_hash


class Command(BaseCommand):
    help = "幂等初始化流程验证阶段默认 AtomicSignalDefinition"

    def handle(self, *args, **options):
        params = {
            "left_feature_code": "sma_4h_20",
            "operator": "gt",
            "right_feature_code": "sma_4h_60",
        }
        dependencies = normalize_feature_codes(["sma_4h_20", "sma_4h_60"])
        available_features = set(
            FeatureDefinition.objects.filter(feature_code__in=dependencies, is_enabled=True).values_list(
                "feature_code", flat=True
            )
        )
        missing = sorted(set(dependencies) - available_features)
        if missing:
            raise CommandError(f"默认原子信号依赖的 FeatureDefinition 尚不可用：{','.join(missing)}")
        default_registry.resolve(
            calculator_type=CalculatorType.ATOMIC_SIGNAL,
            algorithm_name="feature_compare",
            algorithm_version="1.0.0",
        )
        params_hash = stable_hash(params)
        definition_hash = atomic_signal_definition_hash(
            signal_code="sma_4h_20_above_sma_4h_60",
            default_direction=AtomicSignalDirection.BULLISH,
            algorithm_name="feature_compare",
            algorithm_version="1.0.0",
            params_hash=params_hash,
            is_required=True,
            depends_on_feature_codes=dependencies,
            output_type=AtomicSignalOutputType.BOOLEAN,
        )
        definition, created = AtomicSignalDefinition.objects.get_or_create(
            signal_code="sma_4h_20_above_sma_4h_60",
            definition_hash=definition_hash,
            defaults={
                "display_name": "4h SMA20 高于 4h SMA60",
                "description": "判断 4h SMA20 是否高于 4h SMA60，仅表达偏多证据是否存在。",
                "category": "trend",
                "default_direction": AtomicSignalDirection.BULLISH,
                "algorithm_name": "feature_compare",
                "algorithm_version": "1.0.0",
                "params": params,
                "params_hash": params_hash,
                "status": DefinitionLifecycleStatus.ACTIVE,
                "enabled": True,
                "is_required": True,
                "depends_on_feature_codes": list(dependencies),
                "output_type": AtomicSignalOutputType.BOOLEAN,
            },
        )
        if not created:
            identity_matches = (
                definition.definition_hash == definition_hash
                and definition.params == params
                and tuple(definition.depends_on_feature_codes) == dependencies
            )
            if not identity_matches:
                raise CommandError("已有 AtomicSignalDefinition 身份字段与默认模板冲突，拒绝覆盖")
            AtomicSignalDefinition.objects.filter(id=definition.id).update(
                display_name="4h SMA20 高于 4h SMA60",
                description="判断 4h SMA20 是否高于 4h SMA60，仅表达偏多证据是否存在。",
                category="trend",
            )
        self.stdout.write(
            self.style.SUCCESS(
                f"AtomicSignalDefinition {'created' if created else 'existing'}: id={definition.id} "
                f"signal_code={definition.signal_code}"
            )
        )
