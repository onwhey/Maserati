"""DecisionSnapshot 模块：幂等初始化默认 DecisionPolicyDefinition。
负责：读取默认目标仓位策略模板，校验 calculator 与文档记录，把 DecisionPolicyDefinition 写入数据库。
不负责：生成 DecisionSnapshot、执行策略信号、创建订单、风控审批或交易执行。
读写数据库：写 DecisionPolicyDefinition，读取已有 DecisionPolicyDefinition。
访问 Redis：不涉及。
访问外部服务：不涉及。
发送 Hermes：不涉及。
调用大模型：不涉及。
涉及交易执行：不涉及。
允许真实交易：否。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from apps.strategy_analysis.default_decision_policy_definitions import (
    DEFAULT_DECISION_POLICY_DEFINITIONS,
    DecisionPolicyDefinitionTemplate,
)
from apps.strategy_analysis.definition_hashes import decision_policy_definition_hash
from apps.strategy_analysis.models import DecisionPolicyDefinition, DefinitionLifecycleStatus
from apps.strategy_calculator.contracts import CalculatorType
from apps.strategy_calculator.registry import default_registry
from apps.strategy_calculator.utils import stable_hash


@dataclass(frozen=True)
class SeededDecisionPolicyDefinition:
    definition: DecisionPolicyDefinition
    created: bool


class Command(BaseCommand):
    help = "幂等初始化默认 DecisionPolicyDefinition"

    def handle(self, *args, **options):
        created_count = 0
        existing_count = 0
        for template in DEFAULT_DECISION_POLICY_DEFINITIONS:
            seeded = _seed_template(template)
            if seeded.created:
                created_count += 1
            else:
                existing_count += 1
        self.stdout.write(
            self.style.SUCCESS(
                "DecisionPolicyDefinition seed completed: "
                f"created={created_count} existing={existing_count} total={created_count + existing_count}"
            )
        )


def _seed_template(template: DecisionPolicyDefinitionTemplate) -> SeededDecisionPolicyDefinition:
    calculator = _validate_calculator(template)
    _validate_document_paths(calculator.metadata.algorithm_requirement_document_path, calculator.metadata.implementation_document_path)
    params_hash = stable_hash(template.params)
    definition_hash = decision_policy_definition_hash(
        policy_code=template.policy_code,
        policy_version=template.policy_version,
        algorithm_name=template.algorithm_name,
        algorithm_version=template.algorithm_version,
        input_schema_version=template.input_schema_version,
        output_schema_version=template.output_schema_version,
        target_schema_version=template.target_schema_version,
        params_hash=params_hash,
    )
    definition, created = DecisionPolicyDefinition.objects.get_or_create(
        policy_code=template.policy_code,
        policy_version=template.policy_version,
        defaults={
            "display_name": template.display_name,
            "description": template.description,
            "algorithm_name": template.algorithm_name,
            "algorithm_version": template.algorithm_version,
            "input_schema_version": template.input_schema_version,
            "output_schema_version": template.output_schema_version,
            "target_schema_version": template.target_schema_version,
            "params": template.params,
            "params_hash": params_hash,
            "definition_hash": definition_hash,
            "status": DefinitionLifecycleStatus.ACTIVE,
            "enabled": True,
        },
    )
    if created:
        return SeededDecisionPolicyDefinition(definition=definition, created=True)
    _assert_identity(
        definition=definition,
        template=template,
        params_hash=params_hash,
        definition_hash=definition_hash,
    )
    DecisionPolicyDefinition.objects.filter(id=definition.id).update(
        display_name=template.display_name,
        description=template.description,
    )
    definition.display_name = template.display_name
    definition.description = template.description
    return SeededDecisionPolicyDefinition(definition=definition, created=False)


def _validate_calculator(template: DecisionPolicyDefinitionTemplate):
    try:
        calculator = default_registry.resolve(
            calculator_type=CalculatorType.DECISION_POLICY,
            algorithm_name=template.algorithm_name,
            algorithm_version=template.algorithm_version,
        )
    except Exception as exc:
        raise CommandError(
            f"DecisionPolicyDefinition {template.policy_code} 依赖的 DecisionPolicy calculator 不可用："
            f"{template.algorithm_name}/{template.algorithm_version}"
        ) from exc
    metadata = calculator.metadata
    if (
        metadata.input_schema_version != template.input_schema_version
        or metadata.output_schema_version != template.output_schema_version
    ):
        raise CommandError(f"DecisionPolicyDefinition {template.policy_code} 与 calculator metadata 不一致")
    return calculator


def _validate_document_paths(*paths: str) -> None:
    root = Path.cwd()
    missing = [path for path in paths if not (root / path).exists()]
    if missing:
        raise CommandError("DecisionPolicyDefinition calculator 文档路径不存在：" + ", ".join(missing))


def _assert_identity(
    *,
    definition: DecisionPolicyDefinition,
    template: DecisionPolicyDefinitionTemplate,
    params_hash: str,
    definition_hash: str,
) -> None:
    identity_matches = (
        definition.algorithm_name == template.algorithm_name
        and definition.algorithm_version == template.algorithm_version
        and definition.input_schema_version == template.input_schema_version
        and definition.output_schema_version == template.output_schema_version
        and definition.target_schema_version == template.target_schema_version
        and definition.params == template.params
        and definition.params_hash == params_hash
        and definition.definition_hash == definition_hash
    )
    if not identity_matches:
        raise CommandError("已有 DecisionPolicyDefinition 身份字段与默认目标仓位模板冲突，拒绝覆盖")
