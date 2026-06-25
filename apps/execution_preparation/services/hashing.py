"""ExecutionPreparation 模块：生成执行准备稳定指纹；不读写数据库；不访问 Redis；不访问外部服务；不涉及交易执行。"""

from __future__ import annotations

from typing import Any

from apps.binance_account_sync.services.hashing import stable_hash


def execution_preparation_key_hash(payload: dict[str, Any]) -> str:
    return stable_hash({"object_type": "execution_preparation_key", "schema_version": "1.0", **payload})


def prepared_order_intent_key_hash(payload: dict[str, Any]) -> str:
    return stable_hash({"object_type": "prepared_order_intent_key", "schema_version": "1.0", **payload})


def prepared_order_idempotency_hash(payload: dict[str, Any]) -> str:
    return stable_hash({"object_type": "prepared_order_idempotency", "schema_version": "1.0", **payload})


def prepared_order_evidence_hash(payload: dict[str, Any]) -> str:
    return stable_hash({"object_type": "prepared_order_evidence", "schema_version": "1.0", **payload})
