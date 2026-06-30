"""StrategySignalQuality 模块：幂等初始化默认 StrategySignalQualityRuleSet。
负责：读取默认质量规则集模板，计算指纹，把 StrategySignalQualityRuleSet 写入数据库。
不负责：执行质量检查、修改 StrategySignal、生成目标仓位、创建订单、风控审批或交易执行。
读写数据库：写 StrategySignalQualityRuleSet，读取已有 StrategySignalQualityRuleSet。
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

from apps.strategy_analysis.default_strategy_signal_quality_definitions import (
    DEFAULT_STRATEGY_SIGNAL_QUALITY_RULE_SETS,
    StrategySignalQualityRuleSetTemplate,
)
from apps.strategy_analysis.definition_hashes import strategy_signal_quality_rule_set_hash
from apps.strategy_analysis.models import DefinitionLifecycleStatus, StrategySignalQualityRuleSet
from apps.strategy_calculator.utils import stable_hash


@dataclass(frozen=True)
class SeededStrategySignalQualityRuleSet:
    rule_set: StrategySignalQualityRuleSet
    created: bool


class Command(BaseCommand):
    help = "幂等初始化默认 StrategySignalQualityRuleSet"

    def handle(self, *args, **options):
        created_count = 0
        existing_count = 0
        for template in DEFAULT_STRATEGY_SIGNAL_QUALITY_RULE_SETS:
            seeded = _seed_template(template)
            if seeded.created:
                created_count += 1
            else:
                existing_count += 1
        self.stdout.write(
            self.style.SUCCESS(
                "StrategySignalQualityRuleSet seed completed: "
                f"created={created_count} existing={existing_count} total={created_count + existing_count}"
            )
        )


def _seed_template(template: StrategySignalQualityRuleSetTemplate) -> SeededStrategySignalQualityRuleSet:
    _validate_template(template)
    params_hash = stable_hash(template.params)
    rule_set_hash = strategy_signal_quality_rule_set_hash(
        rule_set_code=template.rule_set_code,
        rule_set_version=template.rule_set_version,
        quality_schema_version=template.quality_schema_version,
        max_staleness_seconds=template.max_staleness_seconds,
        warning_blocks_decision=template.warning_blocks_decision,
        fail_alert_enabled=template.fail_alert_enabled,
        warning_alert_enabled=template.warning_alert_enabled,
        consecutive_failure_threshold=template.consecutive_failure_threshold,
        params_hash=params_hash,
    )
    rule_set, created = StrategySignalQualityRuleSet.objects.get_or_create(
        rule_set_code=template.rule_set_code,
        rule_set_version=template.rule_set_version,
        defaults={
            "display_name": template.display_name,
            "description": template.description,
            "quality_schema_version": template.quality_schema_version,
            "max_staleness_seconds": template.max_staleness_seconds,
            "warning_blocks_decision": template.warning_blocks_decision,
            "fail_alert_enabled": template.fail_alert_enabled,
            "warning_alert_enabled": template.warning_alert_enabled,
            "consecutive_failure_threshold": template.consecutive_failure_threshold,
            "params": template.params,
            "params_hash": params_hash,
            "rule_set_hash": rule_set_hash,
            "status": DefinitionLifecycleStatus.ACTIVE,
            "enabled": True,
        },
    )
    if created:
        return SeededStrategySignalQualityRuleSet(rule_set=rule_set, created=True)
    _assert_identity(
        rule_set=rule_set,
        template=template,
        params_hash=params_hash,
        rule_set_hash=rule_set_hash,
    )
    StrategySignalQualityRuleSet.objects.filter(id=rule_set.id).update(
        display_name=template.display_name,
        description=template.description,
    )
    rule_set.display_name = template.display_name
    rule_set.description = template.description
    return SeededStrategySignalQualityRuleSet(rule_set=rule_set, created=False)


def _validate_template(template: StrategySignalQualityRuleSetTemplate) -> None:
    if template.max_staleness_seconds < 0:
        raise CommandError(f"StrategySignalQualityRuleSet {template.rule_set_code} 最大允许陈旧秒数不得为负数")
    if template.consecutive_failure_threshold < 0:
        raise CommandError(f"StrategySignalQualityRuleSet {template.rule_set_code} 连续失败阈值不得为负数")
    if not template.rule_set_code.strip() or not template.rule_set_version.strip():
        raise CommandError("StrategySignalQualityRuleSet 模板缺少规则集代码或版本")
    if not template.quality_schema_version.strip():
        raise CommandError(f"StrategySignalQualityRuleSet {template.rule_set_code} 缺少质量 schema 版本")


def _assert_identity(
    *,
    rule_set: StrategySignalQualityRuleSet,
    template: StrategySignalQualityRuleSetTemplate,
    params_hash: str,
    rule_set_hash: str,
) -> None:
    identity_matches = (
        rule_set.quality_schema_version == template.quality_schema_version
        and rule_set.max_staleness_seconds == template.max_staleness_seconds
        and rule_set.warning_blocks_decision == template.warning_blocks_decision
        and rule_set.fail_alert_enabled == template.fail_alert_enabled
        and rule_set.warning_alert_enabled == template.warning_alert_enabled
        and rule_set.consecutive_failure_threshold == template.consecutive_failure_threshold
        and rule_set.params == template.params
        and rule_set.params_hash == params_hash
        and rule_set.rule_set_hash == rule_set_hash
    )
    if not identity_matches:
        raise CommandError("已有 StrategySignalQualityRuleSet 身份字段与默认质量规则模板冲突，拒绝覆盖")
