"""RiskCheck 模块：定义风控只读上下文、规则结果和纯计算 helper；不读写数据库；不访问外部服务；不涉及交易执行。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Protocol

from django.utils import timezone

from apps.binance_account_sync.models import (
    BinanceAccountSnapshot,
    BinanceBalanceSnapshot,
    BinancePositionSnapshot,
    BinanceSymbolRuleSnapshot,
    BinanceSyncRun,
)
from apps.order_plan.models import CandidateOrderIntent, OrderPlan, OrderPlanActiveLock
from apps.price_snapshot.models import PriceSnapshot

from .models import RiskRuleDefinition, RiskRuleResultStatus


@dataclass(frozen=True)
class RiskRuleEvaluation:
    rule_code: str
    rule_version: str
    status: str
    severity: str
    reason_code: str
    message_zh: str
    risk_measures: dict[str, Any] = field(default_factory=dict)
    evidence: dict[str, Any] = field(default_factory=dict)
    definition_hash: str = ""
    params_hash: str = ""
    started_at_utc: datetime = field(default_factory=timezone.now)
    finished_at_utc: datetime = field(default_factory=timezone.now)

    @classmethod
    def pass_result(cls, definition: RiskRuleDefinition, message: str = "规则通过") -> "RiskRuleEvaluation":
        now = timezone.now()
        return cls(
            rule_code=definition.rule_code,
            rule_version=definition.rule_version,
            status=RiskRuleResultStatus.PASS,
            severity=definition.severity,
            reason_code="pass",
            message_zh=message,
            definition_hash=definition.definition_hash,
            params_hash=definition.params_hash,
            started_at_utc=now,
            finished_at_utc=now,
        )


@dataclass(frozen=True)
class RuleEngineSummary:
    final_status: str
    reason_code: str
    message_zh: str
    evaluations: list[RiskRuleEvaluation]


@dataclass(frozen=True)
class RiskCheckContext:
    order_plan: OrderPlan
    candidate: CandidateOrderIntent
    primary_candidate: CandidateOrderIntent
    fallback_candidate: CandidateOrderIntent | None
    active_lock: OrderPlanActiveLock
    sync_run: BinanceSyncRun
    account_snapshot: BinanceAccountSnapshot
    balance_snapshot: BinanceBalanceSnapshot
    position_snapshot: BinancePositionSnapshot
    symbol_rule_snapshot: BinanceSymbolRuleSnapshot
    price_snapshot: PriceSnapshot
    reference_time_utc: datetime
    risk_config: dict[str, Any]
    snapshot_integrity_reason: str = ""
    price_integrity_reason: str = ""

    @property
    def has_increase_risk_component(self) -> bool:
        return any(item.get("risk_effect") == "increase_risk" for item in self.candidate.order_components or [])

    @property
    def is_risk_reducing_total(self) -> bool:
        components = self.candidate.order_components or []
        return bool(components) and all(item.get("risk_effect") == "reduce_risk" for item in components)


class RiskRulePlugin(Protocol):
    rule_code: str

    def evaluate(self, *, context: RiskCheckContext, definition: RiskRuleDefinition) -> RiskRuleEvaluation:
        ...


def aggregate_rule_results(evaluations: list[RiskRuleEvaluation]) -> RuleEngineSummary:
    if not evaluations:
        return RuleEngineSummary("BLOCKED", "risk_rule_set_empty", "当前规则集没有可执行规则", evaluations)
    for status, final_status in (
        (RiskRuleResultStatus.FAILED, "FAILED"),
        (RiskRuleResultStatus.BLOCKED, "BLOCKED"),
        (RiskRuleResultStatus.DENY, "DENY"),
    ):
        matched = next((item for item in evaluations if item.status == status), None)
        if matched is not None:
            return RuleEngineSummary(final_status, matched.reason_code, matched.message_zh, evaluations)
    return RuleEngineSummary("ALLOW", "risk_check_passed", "全部风控规则通过", evaluations)


def decimal_or_none(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    if not parsed.is_finite():
        return None
    return parsed


def decimal_is_multiple(value: Decimal, step: Decimal) -> bool:
    if step <= 0:
        return False
    try:
        return value % step == 0
    except InvalidOperation:
        return False


def decimal_places_allowed(value: Decimal, precision: int | None) -> bool:
    if precision is None or precision < 0:
        return False
    exponent = value.normalize().as_tuple().exponent
    places = abs(exponent) if exponent < 0 else 0
    return places <= precision


def component_decimal(component: dict[str, Any], key: str) -> Decimal | None:
    return decimal_or_none(component.get(key))


def total_component_value(components: list[dict[str, Any]], key: str) -> Decimal | None:
    total = Decimal("0")
    for component in components:
        value = component_decimal(component, key)
        if value is None:
            return None
        total += value
    return total
