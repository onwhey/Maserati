"""DomainSignal 模块：幂等初始化当前默认领域定义；写数据库，不访问外部服务，不执行交易。"""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from apps.strategy_analysis.definition_hashes import domain_signal_definition_hash, normalize_atomic_signal_codes
from apps.strategy_analysis.models import (
    AtomicSignalDefinition,
    DefinitionLifecycleStatus,
    DomainSignalDefinition,
    DomainSignalOutputMode,
)
from apps.strategy_calculator.contracts import CalculatorType
from apps.strategy_calculator.registry import default_registry
from apps.strategy_calculator.utils import stable_hash


class Command(BaseCommand):
    help = "幂等初始化流程验证阶段默认 DomainSignalDefinition"

    def handle(self, *args, **options):
        atomic_signal = AtomicSignalDefinition.objects.filter(
            signal_code="sma_4h_20_above_sma_4h_60",
            status=DefinitionLifecycleStatus.ACTIVE,
            enabled=True,
        ).first()
        if atomic_signal is None:
            raise CommandError("默认 trend 领域依赖的 AtomicSignalDefinition 尚不可用")

        default_registry.resolve(
            calculator_type=CalculatorType.DOMAIN_SIGNAL,
            algorithm_name="single_atomic_passthrough",
            algorithm_version="1.0.0",
        )
        params = {}
        params_hash = stable_hash(params)
        required_codes = normalize_atomic_signal_codes([atomic_signal.signal_code])
        definition_hash = domain_signal_definition_hash(
            domain_code="trend",
            output_mode=DomainSignalOutputMode.DIRECTIONAL,
            algorithm_name="single_atomic_passthrough",
            algorithm_version="1.0.0",
            params_hash=params_hash,
            is_required=True,
            allowed_atomic_signal_codes=required_codes,
            required_atomic_signal_codes=required_codes,
            minimum_coverage_ratio="1",
            agreement_threshold=None,
        )
        definition, created = DomainSignalDefinition.objects.get_or_create(
            domain_code="trend",
            definition_hash=definition_hash,
            defaults={
                "display_name": "趋势领域：单原子透传",
                "description": "流程验证阶段的趋势领域定义，只消费默认趋势原子信号。",
                "category": "trend",
                "output_mode": DomainSignalOutputMode.DIRECTIONAL,
                "algorithm_name": "single_atomic_passthrough",
                "algorithm_version": "1.0.0",
                "params": params,
                "params_hash": params_hash,
                "status": DefinitionLifecycleStatus.ACTIVE,
                "enabled": True,
                "is_required": True,
                "allowed_atomic_signal_codes": list(required_codes),
                "required_atomic_signal_codes": list(required_codes),
                "minimum_coverage_ratio": "1",
                "agreement_threshold": None,
            },
        )
        if not created:
            identity_matches = (
                definition.params == params
                and definition.params_hash == params_hash
                and tuple(definition.allowed_atomic_signal_codes) == required_codes
                and tuple(definition.required_atomic_signal_codes) == required_codes
            )
            if not identity_matches:
                raise CommandError("已有 DomainSignalDefinition 身份字段与默认模板冲突，拒绝覆盖")
            DomainSignalDefinition.objects.filter(id=definition.id).update(
                display_name="趋势领域：单原子透传",
                description="流程验证阶段的趋势领域定义，只消费默认趋势原子信号。",
                category="trend",
            )
        self.stdout.write(
            self.style.SUCCESS(
                f"DomainSignalDefinition {'created' if created else 'existing'}: "
                f"id={definition.id} domain_code={definition.domain_code}"
            )
        )
