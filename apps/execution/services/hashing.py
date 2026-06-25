"""Execution 模块：生成订单提交稳定指纹；不读写数据库；不访问 Redis；不访问外部服务；涉及交易执行事实标识。"""

from __future__ import annotations

from typing import Any

from apps.binance_account_sync.services.hashing import stable_hash


def order_submission_attempt_key_hash(payload: dict[str, Any]) -> str:
    return stable_hash({"object_type": "order_submission_attempt_key", "schema_version": "1.0", **payload})


def order_submission_request_hash(payload: dict[str, Any]) -> str:
    return stable_hash({"object_type": "order_submission_request", "schema_version": "1.0", **payload})


def order_submission_response_hash(payload: dict[str, Any]) -> str:
    return stable_hash({"object_type": "order_submission_response", "schema_version": "1.0", **payload})

