"""FeatureLayer 模块：幂等初始化默认 FeatureDefinition。

负责：读取默认特征模板并写入 FeatureDefinition 表。
不负责：计算 FeatureSet、生成 FeatureValue、调用 FeatureLayerService、请求 Binance 或生成交易动作。
读写数据库：写 FeatureDefinition，读取已有 FeatureDefinition。
访问 Redis：不涉及。
访问外部服务：不涉及。
发送 Hermes：不涉及。
调用大模型：不涉及。
涉及交易执行：不涉及。
允许真实交易：否。
"""

from __future__ import annotations

from dataclasses import dataclass

from django.core.management.base import BaseCommand, CommandError

from apps.strategy_analysis.default_definitions import DEFAULT_FEATURE_DEFINITIONS, FeatureDefinitionTemplate
from apps.strategy_analysis.definition_hashes import feature_definition_hash
from apps.strategy_analysis.models import FeatureDefinition
from apps.strategy_calculator.contracts import CalculatorType
from apps.strategy_calculator.registry import default_registry
from apps.strategy_calculator.utils import stable_hash


@dataclass(frozen=True)
class SeededFeatureDefinition:
    definition: FeatureDefinition
    created: bool


class Command(BaseCommand):
    help = "幂等初始化默认 FeatureDefinition"

    def handle(self, *args, **options):
        created_count = 0
        existing_count = 0
        for template in DEFAULT_FEATURE_DEFINITIONS:
            seeded = _seed_template(template)
            if seeded.created:
                created_count += 1
            else:
                existing_count += 1
        self.stdout.write(
            self.style.SUCCESS(
                "FeatureDefinition seed completed: "
                f"created={created_count} existing={existing_count} total={created_count + existing_count}"
            )
        )


def _seed_template(template: FeatureDefinitionTemplate) -> SeededFeatureDefinition:
    _validate_calculator(template)
    params_hash = stable_hash(template.params)
    definition_hash = feature_definition_hash(
        feature_code=template.feature_code,
        definition_version=template.definition_version,
        algorithm_name=template.algorithm_name,
        algorithm_version=template.algorithm_version,
        params_hash=params_hash,
        value_type=template.value_type,
        input_timeframes=template.input_timeframes,
        output_schema_version=template.output_schema_version,
    )
    definition, created = FeatureDefinition.objects.get_or_create(
        feature_code=template.feature_code,
        definition_version=template.definition_version,
        defaults={
            "display_name": template.display_name,
            "description": template.description,
            "definition_hash": definition_hash,
            "algorithm_name": template.algorithm_name,
            "algorithm_version": template.algorithm_version,
            "params": template.params,
            "params_hash": params_hash,
            "value_type": template.value_type,
            "input_timeframes": list(template.input_timeframes),
            "output_schema_version": template.output_schema_version,
            "is_enabled": True,
        },
    )
    if created:
        return SeededFeatureDefinition(definition=definition, created=True)

    _validate_existing_identity(
        template=template,
        definition=definition,
        expected_params_hash=params_hash,
        expected_definition_hash=definition_hash,
    )
    FeatureDefinition.objects.filter(id=definition.id).update(
        display_name=template.display_name,
        description=template.description,
    )
    definition.display_name = template.display_name
    definition.description = template.description
    return SeededFeatureDefinition(definition=definition, created=False)


def _validate_calculator(template: FeatureDefinitionTemplate) -> None:
    try:
        default_registry.resolve(
            calculator_type=CalculatorType.FEATURE_LAYER,
            algorithm_name=template.algorithm_name,
            algorithm_version=template.algorithm_version,
        )
    except Exception as exc:
        raise CommandError(
            f"FeatureDefinition {template.feature_code} 依赖的 FeatureLayer calculator 不可用："
            f"{template.algorithm_name}/{template.algorithm_version}"
        ) from exc


def _validate_existing_identity(
    *,
    template: FeatureDefinitionTemplate,
    definition: FeatureDefinition,
    expected_params_hash: str,
    expected_definition_hash: str,
) -> None:
    identity_matches = (
        definition.definition_hash == expected_definition_hash
        and definition.algorithm_name == template.algorithm_name
        and definition.algorithm_version == template.algorithm_version
        and definition.params == template.params
        and definition.params_hash == expected_params_hash
        and definition.value_type == template.value_type
        and list(definition.input_timeframes) == list(template.input_timeframes)
        and definition.output_schema_version == template.output_schema_version
    )
    if not identity_matches:
        raise CommandError(
            f"已有 FeatureDefinition 与默认模板身份冲突，拒绝覆盖："
            f"feature_code={template.feature_code} definition_version={template.definition_version}"
        )
