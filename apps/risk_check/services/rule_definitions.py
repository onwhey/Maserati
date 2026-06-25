"""RiskCheck 模块：初始化和读取版本化风控规则定义；读写 MySQL；不访问外部服务；不涉及交易执行。"""

from __future__ import annotations

from django.db import transaction

from apps.binance_account_sync.services.hashing import stable_hash
from apps.binance_gateway.types import MARKET_TYPE_COIN_M, MARKET_TYPE_USDS_M

from ..models import RiskRuleDefinition, RiskRuleDefinitionStatus, RiskRuleSet, RiskRuleSetStatus
from .hashing import risk_rule_definition_hash, risk_rule_set_hash


BUILTIN_RULE_CODES = [
    "candidate_intent_valid",
    "order_plan_valid",
    "order_components_valid",
    "business_input_binding_valid",
    "binance_sync_run_consumable",
    "snapshot_integrity",
    "market_identity_consistency",
    "one_way_position_mode_required",
    "active_lock_consistency",
    "price_snapshot_present",
    "price_snapshot_fresh",
    "usds_m_balance_available",
    "coin_m_balance_available",
    "symbol_rule_min_notional",
    "symbol_rule_quantity_step",
    "symbol_rule_max_quantity",
    "symbol_rule_max_notional",
    "available_margin_check",
    "reverse_fallback_reduce_only",
]


def ensure_builtin_rule_set(rule_set_code: str) -> RiskRuleSet:
    """确保 P0 基础风控规则定义存在。"""

    with transaction.atomic():
        rule_set, _created = RiskRuleSet.objects.select_for_update().get_or_create(
            rule_set_code=rule_set_code,
            defaults={
                "description_zh": "P0 基础订单风控规则集",
                "status": RiskRuleSetStatus.ACTIVE,
                "enabled": True,
            },
        )
        for order, rule_code in enumerate(BUILTIN_RULE_CODES, start=10):
            params: dict[str, object] = {}
            params_hash = stable_hash(params)
            definition_hash = risk_rule_definition_hash(
                {
                    "rule_set_code": rule_set_code,
                    "rule_code": rule_code,
                    "rule_version": "1.0",
                    "algorithm_name": rule_code,
                    "algorithm_version": "1.0",
                    "params_hash": params_hash,
                    "applicable_market_types": [MARKET_TYPE_USDS_M, MARKET_TYPE_COIN_M],
                }
            )
            RiskRuleDefinition.objects.get_or_create(
                risk_rule_set=rule_set,
                rule_code=rule_code,
                rule_version="1.0",
                defaults={
                    "algorithm_name": rule_code,
                    "algorithm_version": "1.0",
                    "params": params,
                    "params_hash": params_hash,
                    "definition_hash": definition_hash,
                    "status": RiskRuleDefinitionStatus.ACTIVE,
                    "enabled": True,
                    "severity": "warning",
                    "execution_order": order,
                    "applicable_market_types": [MARKET_TYPE_USDS_M, MARKET_TYPE_COIN_M],
                    "description_zh": f"P0 基础风控规则：{rule_code}",
                },
            )
        _refresh_rule_set_hash(rule_set)
        return rule_set


def load_active_rule_definitions(rule_set_code: str) -> tuple[RiskRuleSet | None, list[RiskRuleDefinition]]:
    rule_set = RiskRuleSet.objects.filter(
        rule_set_code=rule_set_code,
        status=RiskRuleSetStatus.ACTIVE,
        enabled=True,
    ).first()
    if rule_set is None:
        return None, []
    definitions = list(
        rule_set.rule_definitions.filter(
            status=RiskRuleDefinitionStatus.ACTIVE,
            enabled=True,
        ).order_by("execution_order", "id")
    )
    _refresh_rule_set_hash(rule_set, definitions=definitions)
    rule_set.refresh_from_db()
    return rule_set, definitions


def _refresh_rule_set_hash(rule_set: RiskRuleSet, *, definitions: list[RiskRuleDefinition] | None = None) -> None:
    active_definitions = definitions
    if active_definitions is None:
        active_definitions = list(
            rule_set.rule_definitions.filter(
                status=RiskRuleDefinitionStatus.ACTIVE,
                enabled=True,
            ).order_by("execution_order", "id")
        )
    payload = {
        "rule_set_code": rule_set.rule_set_code,
        "definitions": [
            {
                "rule_code": item.rule_code,
                "rule_version": item.rule_version,
                "definition_hash": item.definition_hash,
                "params_hash": item.params_hash,
                "execution_order": item.execution_order,
            }
            for item in active_definitions
        ],
    }
    new_hash = risk_rule_set_hash(payload)
    if rule_set.rule_set_hash != new_hash:
        rule_set.rule_set_hash = new_hash
        rule_set.save(update_fields=["rule_set_hash", "updated_at_utc"])
