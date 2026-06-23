"""项目底座模块：提供幂等辅助；不读写数据库，不访问外部服务，不涉及交易执行。"""

from __future__ import annotations

import hashlib

from .exceptions import IdempotencyConflictError


def build_idempotency_key(*parts: object) -> str:
    normalized = "|".join(str(part) for part in parts)
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    return f"idm_{digest}"


def assert_not_trace_id(idempotency_key: str, trace_id: str) -> None:
    if idempotency_key == trace_id or idempotency_key.startswith("trace_"):
        raise IdempotencyConflictError("业务幂等键不得使用 trace_id")

