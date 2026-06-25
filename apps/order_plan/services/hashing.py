"""OrderPlan 模块：生成订单计划和候选意图稳定指纹；不读写数据库；不访问外部服务；不涉及交易执行。"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from apps.binance_account_sync.services.hashing import stable_hash


def order_plan_hash(payload: dict[str, Any]) -> str:
    return stable_hash({"object_type": "order_plan", "schema_version": "1.0", **payload})


def candidate_intent_hash(payload: dict[str, Any]) -> str:
    return stable_hash({"object_type": "candidate_order_intent", "schema_version": "1.0", **payload})


def decimal_hash_value(value: Decimal) -> str:
    normalized = value.normalize()
    if normalized == normalized.to_integral():
        return format(normalized, "f")
    return format(normalized, "f").rstrip("0").rstrip(".")
