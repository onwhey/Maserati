"""MarketRegime 模块：幂等初始化默认 MarketRegimeDefinition。
负责：把代码内置 MarketRegimeDefinition 模板写入数据库。
不负责：计算市场环境、修改版本包、选择策略、访问外部服务或执行交易。
读写数据库：写 MarketRegimeDefinition，读取已有 MarketRegimeDefinition。
访问 Redis：不涉及。
访问外部服务：不涉及。
发送 Hermes：不涉及。
调用大模型：不涉及。
涉及交易执行：不涉及。
允许真实交易：否。
"""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from apps.strategy_analysis.default_market_regime_definitions import DEFAULT_MARKET_REGIME_DEFINITIONS
from apps.strategy_analysis.definition_hashes import (
    market_regime_definition_hash,
    normalize_domain_codes,
    normalize_regime_codes,
)
from apps.strategy_analysis.models import DefinitionLifecycleStatus, MarketRegimeDefinition
from apps.strategy_calculator.contracts import CalculatorType
from apps.strategy_calculator.registry import default_registry
from apps.strategy_calculator.utils import stable_hash


class Command(BaseCommand):
    help = "幂等初始化默认 MarketRegimeDefinition"

    def handle(self, *args, **options):
        created_count = 0
        existing_count = 0
        for template in DEFAULT_MARKET_REGIME_DEFINITIONS:
            default_registry.resolve(
                calculator_type=CalculatorType.MARKET_REGIME,
                algorithm_name=template.algorithm_name,
                algorithm_version=template.algorithm_version,
            )
            allowed_domain_codes = normalize_domain_codes(template.allowed_domain_codes)
            required_domain_codes = normalize_domain_codes(template.required_domain_codes)
            allowed_regime_codes = normalize_regime_codes(template.allowed_regime_codes)
            if not set(required_domain_codes).issubset(set(allowed_domain_codes)):
                raise CommandError(f"{template.definition_code} required 领域不在 allowed 领域内")
            params_hash = stable_hash(template.params)
            definition_hash = market_regime_definition_hash(
                definition_code=template.definition_code,
                algorithm_name=template.algorithm_name,
                algorithm_version=template.algorithm_version,
                input_schema_version=template.input_schema_version,
                output_schema_version=template.output_schema_version,
                params_hash=params_hash,
                allowed_domain_codes=allowed_domain_codes,
                required_domain_codes=required_domain_codes,
                allowed_regime_codes=allowed_regime_codes,
            )
            definition, created = MarketRegimeDefinition.objects.get_or_create(
                definition_code=template.definition_code,
                definition_hash=definition_hash,
                defaults={
                    "display_name": template.display_name,
                    "description": template.description,
                    "algorithm_name": template.algorithm_name,
                    "algorithm_version": template.algorithm_version,
                    "input_schema_version": template.input_schema_version,
                    "output_schema_version": template.output_schema_version,
                    "params": template.params,
                    "params_hash": params_hash,
                    "allowed_domain_codes": list(allowed_domain_codes),
                    "required_domain_codes": list(required_domain_codes),
                    "allowed_regime_codes": list(allowed_regime_codes),
                    "status": DefinitionLifecycleStatus.ACTIVE,
                    "enabled": True,
                },
            )
            if created:
                created_count += 1
            else:
                existing_count += 1
                self._assert_identity(
                    definition,
                    template,
                    params_hash=params_hash,
                    definition_hash=definition_hash,
                    allowed_domain_codes=allowed_domain_codes,
                    required_domain_codes=required_domain_codes,
                    allowed_regime_codes=allowed_regime_codes,
                )
                MarketRegimeDefinition.objects.filter(id=definition.id).update(
                    display_name=template.display_name,
                    description=template.description,
                )
            self.stdout.write(
                self.style.SUCCESS(
                    f"MarketRegimeDefinition {'created' if created else 'existing'}: "
                    f"id={definition.id} definition_code={definition.definition_code}"
                )
            )
        self.stdout.write(
            self.style.SUCCESS(
                f"MarketRegimeDefinition seed done: created={created_count} existing={existing_count}"
            )
        )

    @staticmethod
    def _assert_identity(
        definition: MarketRegimeDefinition,
        template,
        *,
        params_hash: str,
        definition_hash: str,
        allowed_domain_codes: tuple[str, ...],
        required_domain_codes: tuple[str, ...],
        allowed_regime_codes: tuple[str, ...],
    ) -> None:
        identity_matches = (
            definition.algorithm_name == template.algorithm_name
            and definition.algorithm_version == template.algorithm_version
            and definition.input_schema_version == template.input_schema_version
            and definition.output_schema_version == template.output_schema_version
            and definition.params == template.params
            and definition.params_hash == params_hash
            and definition.definition_hash == definition_hash
            and tuple(definition.allowed_domain_codes) == allowed_domain_codes
            and tuple(definition.required_domain_codes) == required_domain_codes
            and tuple(definition.allowed_regime_codes) == allowed_regime_codes
        )
        if not identity_matches:
            raise CommandError("已有 MarketRegimeDefinition 身份字段与默认模板冲突，拒绝覆盖")
