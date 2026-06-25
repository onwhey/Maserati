"""FillSync 模块：成交同步 hash 工具；不读写数据库；不访问 Redis 或外部服务；不发送 Hermes；不涉及交易执行。"""

from __future__ import annotations

from typing import Any

from apps.binance_account_sync.services.hashing import stable_hash


def fill_sync_result_key_hash(value: Any) -> str:
    return stable_hash({"fill_sync_result_key": value})


def fill_sync_input_hash(value: Any) -> str:
    return stable_hash({"fill_sync_input": value})


def trade_fill_hash(value: Any) -> str:
    return stable_hash({"trade_fill": value})


def order_fill_summary_hash(value: Any) -> str:
    return stable_hash({"order_fill_summary": value})
