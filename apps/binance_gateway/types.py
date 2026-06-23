"""BinanceGateway 模块：定义受限接口返回结构；不读写数据库，不访问 Redis，不访问外部服务，不涉及交易执行。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class BinanceGatewayCallContext:
    trace_id: str
    trigger_source: str
    operation: str
    market_type: str
    symbol: str = ""
    business_object_type: str = ""
    business_object_id: str = ""
    request_time_utc: datetime | None = None


@dataclass(frozen=True)
class BinanceGatewayResult:
    operation: str
    market_type: str
    endpoint_family: str
    success: bool
    payload: Any = None
    response_received: bool = False
    request_sent: bool = False
    http_status: int | None = None
    binance_error_code: str = ""
    sanitized_error_message: str = ""
    server_time_utc: datetime | None = None
    request_started_at_utc: datetime | None = None
    request_finished_at_utc: datetime | None = None
    latency_ms: int = 0
    attempt_count: int = 0
    rate_limit_metadata: dict[str, Any] = field(default_factory=dict)
    trace_id: str = ""

