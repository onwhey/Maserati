"""BinanceGateway 模块：定义受限接口合同与返回结构；不读写数据库；不访问 Redis；不访问外部服务；不发送 Hermes；不调用大模型；不涉及交易执行；不允许真实交易。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

MARKET_TYPE_USDS_M = "usds_m_futures"
MARKET_TYPE_COIN_M = "coin_m_futures"
SUPPORTED_MARKET_TYPES = {MARKET_TYPE_USDS_M, MARKET_TYPE_COIN_M}

ENDPOINT_FAMILY_FAPI = "fapi"
ENDPOINT_FAMILY_DAPI = "dapi"
ENDPOINT_FAMILY_UNKNOWN = "unknown"

ERROR_GATEWAY_DISABLED = "gateway_disabled"
ERROR_CAPABILITY_DISABLED = "capability_disabled"
ERROR_PUBLIC_DATA_DISABLED = "public_data_disabled"
ERROR_ACCOUNT_READ_DISABLED = "account_read_disabled"
ERROR_ORDER_SUBMISSION_DISABLED = "order_submission_disabled"
ERROR_REAL_EXTERNAL_SERVICES_DISABLED = "real_external_services_disabled"
ERROR_REAL_TRADING_DISABLED = "real_trading_disabled"
ERROR_INVALID_MARKET_TYPE = "invalid_market_type"
ERROR_COLLECTION_DOMAIN_MISMATCH = "collection_domain_mismatch"
ERROR_REQUEST_VALIDATION_FAILED = "request_validation_failed"
ERROR_CONFIGURATION_ERROR = "configuration_error"
ERROR_CREDENTIAL_MISSING = "credential_missing"
ERROR_DOMAIN_MISMATCH = "domain_mismatch"
ERROR_AUTHENTICATION_FAILED = "authentication_failed"
ERROR_PERMISSION_DENIED = "permission_denied"
ERROR_RATE_LIMITED = "rate_limited"
ERROR_SERVER_ERROR = "server_error"
ERROR_NETWORK_ERROR = "network_error"
ERROR_TIMEOUT = "timeout"
ERROR_RESPONSE_SCHEMA_ERROR = "response_schema_error"
ERROR_BINANCE_REJECTED = "binance_rejected"
ERROR_GATEWAY_FAILED = "gateway_failed"


@dataclass(frozen=True)
class BinanceGatewayCallContext:
    trace_id: str
    trigger_source: str
    operation: str
    market_type: str
    symbol: str = ""
    account_domain: str = ""
    business_object_type: str = ""
    business_object_id: str = ""
    request_time_utc: datetime | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


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
    error_category: str = ""
    binance_error_code: str = ""
    sanitized_error_message: str = ""
    server_time_utc: datetime | None = None
    request_started_at_utc: datetime | None = None
    request_finished_at_utc: datetime | None = None
    latency_ms: int = 0
    attempt_count: int = 0
    rate_limit_metadata: dict[str, Any] = field(default_factory=dict)
    trace_id: str = ""


def endpoint_family_for_market(market_type: str) -> str:
    if market_type == MARKET_TYPE_USDS_M:
        return ENDPOINT_FAMILY_FAPI
    if market_type == MARKET_TYPE_COIN_M:
        return ENDPOINT_FAMILY_DAPI
    return ENDPOINT_FAMILY_UNKNOWN


def is_supported_market_type(market_type: str) -> bool:
    return market_type in SUPPORTED_MARKET_TYPES


def normalize_active_market_type(value: str | None) -> str:
    raw_value = str(value or "").strip()
    normalized = raw_value.lower().replace("_", "-")
    if normalized in {"usds-m", "usds-m-futures", "usdm", "usdm-futures"}:
        return MARKET_TYPE_USDS_M
    if normalized in {"coin-m", "coin-m-futures", "coinm", "coinm-futures"}:
        return MARKET_TYPE_COIN_M
    return raw_value
