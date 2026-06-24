"""BinanceAccountSync 模块：提供快照确定性 hash 工具；不读写数据库；不访问 Redis；不访问外部服务；不发送 Hermes；不调用大模型；不涉及交易执行；不允许真实交易。"""

from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal
from hashlib import sha256
from typing import Any


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=_json_default)


def stable_hash(value: Any) -> str:
    return sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _json_default(value: Any) -> str:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    raise TypeError(f"无法序列化的值：{type(value)!r}")

