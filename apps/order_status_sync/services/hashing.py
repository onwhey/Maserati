"""OrderStatusSync 模块：生成订单状态查询稳定指纹；不读写数据库；不访问 Redis；不访问外部服务；不发送 Hermes；不调用大模型；不涉及交易执行。"""

from __future__ import annotations

from typing import Any

from apps.binance_account_sync.services.hashing import stable_hash


def order_status_sync_key_hash(payload: dict[str, Any]) -> str:
    return stable_hash({"object_type": "order_status_sync_key", "schema_version": "1.0", **payload})


def order_status_response_hash(payload: dict[str, Any]) -> str:
    return stable_hash({"object_type": "order_status_response", "schema_version": "1.0", **payload})
