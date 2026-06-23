"""项目底座模块：负责技术追踪上下文；不读写数据库，不访问外部服务，不涉及交易执行。"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4


def make_trace_id() -> str:
    return f"trace_{uuid4().hex}"


@dataclass(frozen=True)
class ExecutionContext:
    trace_id: str
    trigger_source: str
    operator_id: str = ""


def ensure_context(*, trace_id: str | None, trigger_source: str, operator_id: str = "") -> ExecutionContext:
    return ExecutionContext(
        trace_id=trace_id or make_trace_id(),
        trigger_source=trigger_source,
        operator_id=operator_id,
    )

