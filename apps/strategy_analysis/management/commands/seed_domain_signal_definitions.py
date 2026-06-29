"""DomainSignal 模块：幂等初始化当前默认领域定义。
负责：把代码内置 DomainSignalDefinition 模板写入数据库。
不负责：计算领域信号、修改版本包、访问 Redis、访问外部服务、发送 Hermes、交易执行、真实交易。
"""

from __future__ import annotations

from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError

from apps.strategy_analysis.default_domain_definitions import DEFAULT_DOMAIN_SIGNAL_DEFINITIONS
from apps.strategy_analysis.definition_hashes import domain_signal_definition_hash
from apps.strategy_analysis.models import (
    AtomicSignalDefinition,
    DefinitionLifecycleStatus,
    DomainSignalDefinition,
)
from apps.strategy_calculator.contracts import CalculatorType
from apps.strategy_calculator.registry import default_registry
from apps.strategy_calculator.utils import stable_hash


class Command(BaseCommand):
    help = "幂等初始化当前默认 DomainSignalDefinition"

    def handle(self, *args, **options):
        created_count = 0
        existing_count = 0
        for template in DEFAULT_DOMAIN_SIGNAL_DEFINITIONS:
            self._assert_atomic_dependencies(template.allowed_atomic_signal_codes, template.domain_code)
            default_registry.resolve(
                calculator_type=CalculatorType.DOMAIN_SIGNAL,
                algorithm_name=template.algorithm_name,
                algorithm_version=template.algorithm_version,
            )
            params_hash = stable_hash(template.params)
            definition_hash = domain_signal_definition_hash(
                domain_code=template.domain_code,
                output_mode=template.output_mode,
                algorithm_name=template.algorithm_name,
                algorithm_version=template.algorithm_version,
                params_hash=params_hash,
                is_required=template.is_required,
                allowed_atomic_signal_codes=template.allowed_atomic_signal_codes,
                required_atomic_signal_codes=template.required_atomic_signal_codes,
                minimum_coverage_ratio=template.minimum_coverage_ratio,
                agreement_threshold=template.agreement_threshold,
            )
            definition, created = DomainSignalDefinition.objects.get_or_create(
                domain_code=template.domain_code,
                definition_hash=definition_hash,
                defaults={
                    "display_name": template.display_name,
                    "description": template.description,
                    "category": template.category,
                    "output_mode": template.output_mode,
                    "algorithm_name": template.algorithm_name,
                    "algorithm_version": template.algorithm_version,
                    "params": template.params,
                    "params_hash": params_hash,
                    "status": DefinitionLifecycleStatus.ACTIVE,
                    "enabled": True,
                    "is_required": template.is_required,
                    "allowed_atomic_signal_codes": list(template.allowed_atomic_signal_codes),
                    "required_atomic_signal_codes": list(template.required_atomic_signal_codes),
                    "minimum_coverage_ratio": template.minimum_coverage_ratio,
                    "agreement_threshold": template.agreement_threshold,
                },
            )
            if created:
                created_count += 1
            else:
                existing_count += 1
                self._assert_identity(definition, template, params_hash=params_hash)
                DomainSignalDefinition.objects.filter(id=definition.id).update(
                    display_name=template.display_name,
                    description=template.description,
                    category=template.category,
                )
            self.stdout.write(
                self.style.SUCCESS(
                    f"DomainSignalDefinition {'created' if created else 'existing'}: "
                    f"id={definition.id} domain_code={definition.domain_code}"
                )
            )
        self.stdout.write(self.style.SUCCESS(f"DomainSignalDefinition seed done: created={created_count} existing={existing_count}"))

    @staticmethod
    def _assert_atomic_dependencies(atomic_codes: tuple[str, ...], domain_code: str) -> None:
        existing_codes = set(
            AtomicSignalDefinition.objects.filter(
                signal_code__in=atomic_codes,
                status=DefinitionLifecycleStatus.ACTIVE,
                enabled=True,
            ).values_list("signal_code", flat=True)
        )
        missing = sorted(set(atomic_codes) - existing_codes)
        if missing:
            raise CommandError(f"{domain_code} 领域依赖的 AtomicSignalDefinition 尚不可用：{','.join(missing)}")

    @staticmethod
    def _assert_identity(definition: DomainSignalDefinition, template, *, params_hash: str) -> None:
        identity_matches = (
            definition.output_mode == template.output_mode
            and definition.algorithm_name == template.algorithm_name
            and definition.algorithm_version == template.algorithm_version
            and definition.params == template.params
            and definition.params_hash == params_hash
            and tuple(definition.allowed_atomic_signal_codes) == template.allowed_atomic_signal_codes
            and tuple(definition.required_atomic_signal_codes) == template.required_atomic_signal_codes
            and definition.minimum_coverage_ratio == Decimal(str(template.minimum_coverage_ratio))
            and (
                (definition.agreement_threshold is None and template.agreement_threshold is None)
                or definition.agreement_threshold == Decimal(str(template.agreement_threshold))
            )
            and definition.is_required == template.is_required
        )
        if not identity_matches:
            raise CommandError("已有 DomainSignalDefinition 身份字段与默认模板冲突，拒绝覆盖")
