"""AtomicSignal 模块：幂等初始化默认定义。

负责：把代码管理的 AtomicSignalDefinition 模板写入数据库。
不负责：计算原子信号、选择版本包、生成交易信号或订单动作。
读写数据库：写 AtomicSignalDefinition，读取 FeatureDefinition。
访问 Redis：不涉及。
访问外部服务：不涉及。
发送 Hermes：不涉及。
调用大模型：不涉及。
涉及交易执行：不涉及。
允许真实交易：否。
"""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from apps.strategy_analysis.default_atomic_definitions import DEFAULT_ATOMIC_SIGNAL_DEFINITIONS
from apps.strategy_analysis.definition_hashes import atomic_signal_definition_hash
from apps.strategy_analysis.models import AtomicSignalDefinition, DefinitionLifecycleStatus, FeatureDefinition
from apps.strategy_calculator.contracts import CalculatorType
from apps.strategy_calculator.registry import default_registry
from apps.strategy_calculator.utils import stable_hash


class Command(BaseCommand):
    help = "幂等初始化默认 AtomicSignalDefinition"

    def handle(self, *args, **options):
        created_count = 0
        existing_count = 0
        for template in DEFAULT_ATOMIC_SIGNAL_DEFINITIONS:
            created = self._upsert_template(template)
            if created:
                created_count += 1
            else:
                existing_count += 1
        self.stdout.write(
            self.style.SUCCESS(
                f"AtomicSignalDefinition seed completed: created={created_count} existing={existing_count}"
            )
        )

    def _upsert_template(self, template) -> bool:
        dependencies = template.depends_on_feature_codes
        self._validate_features(template.signal_code, dependencies)
        self._validate_calculator(template)
        params_hash = stable_hash(template.params)
        definition_hash = atomic_signal_definition_hash(
            signal_code=template.signal_code,
            default_direction=template.default_direction,
            algorithm_name=template.algorithm_name,
            algorithm_version=template.algorithm_version,
            params_hash=params_hash,
            is_required=template.is_required,
            depends_on_feature_codes=dependencies,
            output_type=template.output_type,
        )
        definition, created = AtomicSignalDefinition.objects.get_or_create(
            signal_code=template.signal_code,
            definition_hash=definition_hash,
            defaults={
                "display_name": template.display_name,
                "description": template.description,
                "category": template.category,
                "default_direction": template.default_direction,
                "algorithm_name": template.algorithm_name,
                "algorithm_version": template.algorithm_version,
                "params": template.params,
                "params_hash": params_hash,
                "status": DefinitionLifecycleStatus.ACTIVE,
                "enabled": True,
                "is_required": template.is_required,
                "depends_on_feature_codes": list(dependencies),
                "output_type": template.output_type,
            },
        )
        if not created:
            self._validate_existing_definition(definition, template, params_hash, dependencies)
            AtomicSignalDefinition.objects.filter(id=definition.id).update(
                display_name=template.display_name,
                description=template.description,
                category=template.category,
            )
        return created

    @staticmethod
    def _validate_features(signal_code: str, dependencies: tuple[str, ...]) -> None:
        available_features = set(
            FeatureDefinition.objects.filter(feature_code__in=dependencies, is_enabled=True).values_list(
                "feature_code",
                flat=True,
            )
        )
        missing = sorted(set(dependencies) - available_features)
        if missing:
            raise CommandError(
                f"默认原子信号 {signal_code} 依赖的 FeatureDefinition 尚不可用：{','.join(missing)}"
            )

    @staticmethod
    def _validate_calculator(template) -> None:
        default_registry.resolve(
            calculator_type=CalculatorType.ATOMIC_SIGNAL,
            algorithm_name=template.algorithm_name,
            algorithm_version=template.algorithm_version,
        )

    @staticmethod
    def _validate_existing_definition(
        definition: AtomicSignalDefinition,
        template,
        params_hash: str,
        dependencies: tuple[str, ...],
    ) -> None:
        identity_matches = (
            definition.default_direction == template.default_direction
            and definition.algorithm_name == template.algorithm_name
            and definition.algorithm_version == template.algorithm_version
            and definition.params == template.params
            and definition.params_hash == params_hash
            and definition.is_required == template.is_required
            and tuple(definition.depends_on_feature_codes) == dependencies
            and definition.output_type == template.output_type
        )
        if not identity_matches:
            raise CommandError("已有 AtomicSignalDefinition 身份字段与默认模板冲突，拒绝覆盖")
