"""RiskCheck 模块：按规则集定义执行插件并聚合结果；不写数据库；不访问外部服务；不涉及交易执行。"""

from __future__ import annotations

from django.utils import timezone

from ..domain import RiskCheckContext, RiskRuleEvaluation, aggregate_rule_results
from ..models import RiskRuleDefinition, RiskRuleResultStatus
from .rule_registry import RiskRuleRegistry


class RuleEngine:
    def __init__(self, registry: RiskRuleRegistry) -> None:
        self.registry = registry

    def evaluate(
        self,
        *,
        context: RiskCheckContext,
        definitions: list[RiskRuleDefinition],
    ):
        evaluations: list[RiskRuleEvaluation] = []
        for definition in definitions:
            if context.order_plan.market_type not in definition.applicable_market_types:
                continue
            plugin = self.registry.get(definition.rule_code)
            started = timezone.now()
            if plugin is None:
                evaluations.append(
                    RiskRuleEvaluation(
                        rule_code=definition.rule_code,
                        rule_version=definition.rule_version,
                        status=RiskRuleResultStatus.BLOCKED,
                        severity=definition.severity,
                        reason_code="risk_rule_plugin_missing",
                        message_zh="当前规则集存在未注册的风控插件，不能放行候选订单。",
                        definition_hash=definition.definition_hash,
                        params_hash=definition.params_hash,
                        started_at_utc=started,
                        finished_at_utc=timezone.now(),
                    )
                )
                continue
            try:
                evaluation = plugin.evaluate(context=context, definition=definition)
            except Exception as exc:  # noqa: BLE001 - 插件异常必须转换为 FAILED 事实，不向上静默穿透。
                evaluations.append(
                    RiskRuleEvaluation(
                        rule_code=definition.rule_code,
                        rule_version=definition.rule_version,
                        status=RiskRuleResultStatus.FAILED,
                        severity=definition.severity,
                        reason_code="risk_rule_plugin_failed",
                        message_zh="风控插件执行异常，不能放行候选订单。",
                        evidence={"error_type": type(exc).__name__},
                        definition_hash=definition.definition_hash,
                        params_hash=definition.params_hash,
                        started_at_utc=started,
                        finished_at_utc=timezone.now(),
                    )
                )
                continue
            evaluations.append(
                RiskRuleEvaluation(
                    rule_code=evaluation.rule_code,
                    rule_version=evaluation.rule_version,
                    status=evaluation.status,
                    severity=evaluation.severity,
                    reason_code=evaluation.reason_code,
                    message_zh=evaluation.message_zh,
                    risk_measures=evaluation.risk_measures,
                    evidence=evaluation.evidence,
                    definition_hash=evaluation.definition_hash,
                    params_hash=evaluation.params_hash,
                    started_at_utc=started,
                    finished_at_utc=timezone.now(),
                )
            )
        return aggregate_rule_results(evaluations)
