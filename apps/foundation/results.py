"""项目底座模块：定义 service 返回语义；不读写数据库，不访问外部服务，不涉及交易执行。"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class ResultStatus(StrEnum):
    SUCCEEDED = "succeeded"
    NO_ACTION = "no_action"
    SKIPPED = "skipped"
    BLOCKED = "blocked"
    DENIED = "denied"
    UNKNOWN = "unknown"
    FAILED = "failed"


@dataclass(frozen=True)
class ServiceResult:
    status: ResultStatus
    reason_code: str
    message: str
    trace_id: str
    trigger_source: str
    data: dict[str, Any] = field(default_factory=dict)

