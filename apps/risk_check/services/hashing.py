"""RiskCheck 模块：生成风控审批稳定指纹；不读写数据库；不访问外部服务；不涉及交易执行。"""

from __future__ import annotations

from typing import Any

from apps.binance_account_sync.services.hashing import stable_hash


def risk_rule_definition_hash(payload: dict[str, Any]) -> str:
    return stable_hash({"object_type": "risk_rule_definition", "schema_version": "1.0", **payload})


def risk_rule_set_hash(payload: dict[str, Any]) -> str:
    return stable_hash({"object_type": "risk_rule_set", "schema_version": "1.0", **payload})


def risk_check_key_hash(payload: dict[str, Any]) -> str:
    return stable_hash({"object_type": "risk_check_key", "schema_version": "1.0", **payload})


def risk_check_result_hash(payload: dict[str, Any]) -> str:
    return stable_hash({"object_type": "risk_check_result", "schema_version": "1.0", **payload})


def approved_order_intent_hash(payload: dict[str, Any]) -> str:
    return stable_hash({"object_type": "approved_order_intent", "schema_version": "1.0", **payload})
