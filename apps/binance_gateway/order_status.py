"""BinanceGateway 模块：订单状态只读受限接口；不写数据库；不访问 Redis；可访问外部 Binance；不发送 Hermes；不调用大模型；不提交订单；不允许真实交易执行。"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from typing import Any, Protocol

from django.conf import settings
from django.utils import timezone

from apps.foundation.redaction import sanitize_mapping

from .account_read import read_credentials_for_market, read_headers, utc_millis
from .public_market import failure_result, public_base_url, sanitize_error_text
from .types import (
    ERROR_AUTHENTICATION_FAILED,
    ERROR_CONFIGURATION_ERROR,
    ERROR_CREDENTIAL_MISSING,
    ERROR_DOMAIN_MISMATCH,
    ERROR_GATEWAY_DISABLED,
    ERROR_GATEWAY_FAILED,
    ERROR_INVALID_MARKET_TYPE,
    ERROR_NETWORK_ERROR,
    ERROR_ORDER_NOT_FOUND,
    ERROR_ORDER_STATUS_QUERY_DISABLED,
    ERROR_PERMISSION_DENIED,
    ERROR_RATE_LIMITED,
    ERROR_REAL_EXTERNAL_SERVICES_DISABLED,
    ERROR_REQUEST_VALIDATION_FAILED,
    ERROR_RESPONSE_SCHEMA_ERROR,
    ERROR_SERVER_ERROR,
    ERROR_TIMEOUT,
    MARKET_TYPE_COIN_M,
    MARKET_TYPE_USDS_M,
    BinanceGatewayCallContext,
    BinanceGatewayResult,
    endpoint_family_for_market,
    is_supported_market_type,
    normalize_active_market_type,
)


LOGGER = logging.getLogger(__name__)

ORDER_STATUS_PATHS = {
    MARKET_TYPE_USDS_M: "/fapi/v1/order",
    MARKET_TYPE_COIN_M: "/dapi/v1/order",
}

BINANCE_ORDER_NOT_FOUND_CODES = {"-2011", "-2013"}


class BinanceOrderStatusGateway(Protocol):
    def query_order(
        self,
        *,
        market_type: str,
        symbol: str,
        call_context: BinanceGatewayCallContext,
        client_order_id: str | None = None,
        exchange_order_id: str | None = None,
    ) -> BinanceGatewayResult: ...


class FakeBinanceOrderStatusGateway:
    """测试替身：记录订单状态查询调用，不访问真实 Binance。"""

    def __init__(
        self,
        *,
        result: BinanceGatewayResult | None = None,
        payload: dict[str, Any] | None = None,
        not_found: bool = False,
    ) -> None:
        self.result = result
        self.payload = payload
        self.not_found = not_found
        self.calls: list[dict[str, Any]] = []

    def query_order(
        self,
        *,
        market_type: str,
        symbol: str,
        call_context: BinanceGatewayCallContext,
        client_order_id: str | None = None,
        exchange_order_id: str | None = None,
    ) -> BinanceGatewayResult:
        self.calls.append(
            {
                "operation": "query_order",
                "market_type": market_type,
                "symbol": symbol,
                "client_order_id": client_order_id or "",
                "exchange_order_id": exchange_order_id or "",
                "call_context": call_context,
            }
        )
        if self.result is not None:
            return self.result
        if self.not_found:
            return _failure(
                market_type=market_type,
                call_context=call_context,
                started=timezone.now(),
                attempt_count=1,
                request_sent=True,
                response_received=True,
                http_status=400,
                error_category=ERROR_ORDER_NOT_FOUND,
                sanitized_error_message=ERROR_ORDER_NOT_FOUND,
                binance_error_code="-2013",
            )
        payload = dict(self.payload) if self.payload is not None else {"orderId": 123456, "status": "NEW"}
        payload.setdefault("symbol", symbol)
        if client_order_id:
            payload.setdefault("clientOrderId", client_order_id)
        if exchange_order_id:
            payload.setdefault("orderId", exchange_order_id)
        return _success(market_type=market_type, payload=payload, call_context=call_context, started=timezone.now(), attempt=1)


class HttpBinanceOrderStatusGateway:
    """真实订单状态查询 Gateway：只读签名查询，允许安全读技术重试，不提交订单。"""

    def query_order(
        self,
        *,
        market_type: str,
        symbol: str,
        call_context: BinanceGatewayCallContext,
        client_order_id: str | None = None,
        exchange_order_id: str | None = None,
    ) -> BinanceGatewayResult:
        normalized_market_type = normalize_active_market_type(market_type)
        normalized_symbol = symbol.strip().upper()
        blocked = validate_order_status_request(
            market_type=normalized_market_type,
            symbol=normalized_symbol,
            account_domain=call_context.account_domain,
            client_order_id=client_order_id,
            exchange_order_id=exchange_order_id,
            call_context=call_context,
        )
        if blocked is not None:
            return blocked

        api_key, api_secret = read_credentials_for_market(normalized_market_type)
        if not api_key or not api_secret:
            return _blocked(normalized_market_type, call_context, ERROR_CREDENTIAL_MISSING)
        return _send_query(
            market_type=normalized_market_type,
            symbol=normalized_symbol,
            client_order_id=client_order_id,
            exchange_order_id=exchange_order_id,
            api_key=api_key,
            api_secret=api_secret,
            call_context=call_context,
        )


def validate_order_status_request(
    *,
    market_type: str,
    symbol: str,
    account_domain: str,
    client_order_id: str | None,
    exchange_order_id: str | None,
    call_context: BinanceGatewayCallContext,
) -> BinanceGatewayResult | None:
    if not getattr(settings, "BINANCE_GATEWAY_ENABLED", False):
        return _blocked(market_type, call_context, ERROR_GATEWAY_DISABLED)
    if not getattr(settings, "BINANCE_ORDER_STATUS_QUERY_ENABLED", False):
        return _blocked(market_type, call_context, ERROR_ORDER_STATUS_QUERY_DISABLED)
    if not getattr(settings, "ALLOW_REAL_EXTERNAL_SERVICES", False):
        return _blocked(market_type, call_context, ERROR_REAL_EXTERNAL_SERVICES_DISABLED)
    if not is_supported_market_type(market_type):
        return _blocked(market_type, call_context, ERROR_INVALID_MARKET_TYPE)
    if not public_base_url(market_type):
        return _blocked(market_type, call_context, ERROR_CONFIGURATION_ERROR)
    if not account_domain or account_domain != getattr(settings, "ACTIVE_ACCOUNT_DOMAIN", ""):
        return _blocked(market_type, call_context, ERROR_DOMAIN_MISMATCH)
    if not symbol or (not client_order_id and not exchange_order_id):
        return _blocked(market_type, call_context, ERROR_REQUEST_VALIDATION_FAILED)
    return None


def _send_query(
    *,
    market_type: str,
    symbol: str,
    client_order_id: str | None,
    exchange_order_id: str | None,
    api_key: str,
    api_secret: str,
    call_context: BinanceGatewayCallContext,
) -> BinanceGatewayResult:
    started = timezone.now()
    attempts = max(1, int(getattr(settings, "BINANCE_SAFE_READ_MAX_ATTEMPTS", 1)))
    last: dict[str, Any] = {"category": ERROR_GATEWAY_FAILED, "message": ERROR_GATEWAY_FAILED, "http_status": None, "code": ""}
    for attempt in range(1, attempts + 1):
        url = build_signed_order_status_url(
            market_type=market_type,
            symbol=symbol,
            client_order_id=client_order_id,
            exchange_order_id=exchange_order_id,
            api_secret=api_secret,
        )
        result = _request_once(url, api_key, market_type, call_context, started, attempt)
        if result.success or result.error_category in {
            ERROR_ORDER_NOT_FOUND,
            ERROR_AUTHENTICATION_FAILED,
            ERROR_PERMISSION_DENIED,
            ERROR_REQUEST_VALIDATION_FAILED,
            ERROR_RESPONSE_SCHEMA_ERROR,
        }:
            return result
        last = {
            "category": result.error_category,
            "message": result.sanitized_error_message,
            "http_status": result.http_status,
            "code": result.binance_error_code,
        }
        if attempt < attempts:
            time.sleep(min(0.2 * attempt, 1.0))
    LOGGER.warning("Binance order status query failed: %s", sanitize_mapping({"error": last["message"], "symbol": symbol}))
    return _failure(
        market_type=market_type,
        call_context=call_context,
        started=started,
        attempt_count=attempts,
        request_sent=True,
        response_received=last["http_status"] is not None,
        http_status=last["http_status"],
        error_category=last["category"],
        sanitized_error_message=last["message"],
        binance_error_code=last["code"],
    )


def _request_once(
    url: str,
    api_key: str,
    market_type: str,
    call_context: BinanceGatewayCallContext,
    started: datetime,
    attempt: int,
) -> BinanceGatewayResult:
    try:
        request = urllib.request.Request(url, method="GET", headers=read_headers(api_key))
        with urllib.request.urlopen(request, timeout=float(getattr(settings, "BINANCE_READ_TIMEOUT_SECONDS", 10))) as response:
            payload = json.loads(response.read().decode("utf-8"))
            return _success(market_type=market_type, payload=payload, call_context=call_context, started=started, attempt=attempt, response=response)
    except urllib.error.HTTPError as exc:
        details = _read_error_details(exc)
        return _failure(
            market_type=market_type,
            call_context=call_context,
            started=started,
            attempt_count=attempt,
            request_sent=True,
            response_received=True,
            http_status=exc.code,
            error_category=_classify_http_error(exc.code, details["code"]),
            sanitized_error_message=details["message"],
            binance_error_code=details["code"],
        )
    except TimeoutError:
        return _failure_for_exception(market_type, call_context, started, attempt, ERROR_TIMEOUT)
    except urllib.error.URLError as exc:
        return _failure_for_exception(market_type, call_context, started, attempt, ERROR_NETWORK_ERROR, sanitize_error_text(str(exc.reason)))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return _failure_for_exception(market_type, call_context, started, attempt, ERROR_RESPONSE_SCHEMA_ERROR)


def build_signed_order_status_url(
    *,
    market_type: str,
    symbol: str,
    client_order_id: str | None,
    exchange_order_id: str | None,
    api_secret: str,
) -> str:
    payload: dict[str, Any] = {"symbol": symbol, "timestamp": utc_millis(timezone.now()), "recvWindow": int(getattr(settings, "BINANCE_RECV_WINDOW_MS", 5000))}
    if client_order_id:
        payload["origClientOrderId"] = client_order_id
    elif exchange_order_id:
        payload["orderId"] = exchange_order_id
    query_without_signature = urllib.parse.urlencode(payload)
    signature = hmac.new(api_secret.encode("utf-8"), query_without_signature.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{public_base_url(market_type).rstrip('/')}{ORDER_STATUS_PATHS[market_type]}?{query_without_signature}&signature={signature}"


def _read_error_details(exc: urllib.error.HTTPError) -> dict[str, str]:
    try:
        body = exc.read().decode("utf-8")
    except (OSError, UnicodeDecodeError):
        return {"code": "", "message": ERROR_GATEWAY_FAILED}
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return {"code": "", "message": sanitize_error_text(body)}
    code = str(payload.get("code") or "")
    message = sanitize_error_text(str(payload.get("msg") or body))
    return {"code": code, "message": message}


def _classify_http_error(http_status: int, binance_code: str) -> str:
    if binance_code in BINANCE_ORDER_NOT_FOUND_CODES:
        return ERROR_ORDER_NOT_FOUND
    if http_status in {401, 403}:
        return ERROR_AUTHENTICATION_FAILED if http_status == 401 else ERROR_PERMISSION_DENIED
    if http_status == 429:
        return ERROR_RATE_LIMITED
    if http_status in {500, 502, 503, 504}:
        return ERROR_SERVER_ERROR
    return ERROR_REQUEST_VALIDATION_FAILED


def _success(
    *,
    market_type: str,
    payload: Any,
    call_context: BinanceGatewayCallContext,
    started: datetime,
    attempt: int,
    response: Any | None = None,
) -> BinanceGatewayResult:
    finished = timezone.now()
    return BinanceGatewayResult(
        operation="query_order",
        market_type=market_type,
        endpoint_family=endpoint_family_for_market(market_type),
        success=True,
        payload=sanitize_mapping(payload if isinstance(payload, dict) else {"payload": payload}),
        response_received=True,
        request_sent=True,
        http_status=getattr(response, "status", 200),
        request_started_at_utc=started,
        request_finished_at_utc=finished,
        latency_ms=int((finished - started).total_seconds() * 1000),
        attempt_count=attempt,
        trace_id=call_context.trace_id,
    )


def _failure_for_exception(
    market_type: str,
    call_context: BinanceGatewayCallContext,
    started: datetime,
    attempt: int,
    category: str,
    message: str | None = None,
) -> BinanceGatewayResult:
    return _failure(
        market_type=market_type,
        call_context=call_context,
        started=started,
        attempt_count=attempt,
        request_sent=True,
        response_received=False,
        http_status=None,
        error_category=category,
        sanitized_error_message=message or category,
    )


def _failure(
    *,
    market_type: str,
    call_context: BinanceGatewayCallContext,
    started: datetime,
    attempt_count: int,
    request_sent: bool,
    response_received: bool,
    http_status: int | None,
    error_category: str,
    sanitized_error_message: str,
    binance_error_code: str = "",
) -> BinanceGatewayResult:
    result = failure_result(
        operation="query_order",
        market_type=market_type,
        call_context=call_context,
        started=started,
        attempt_count=attempt_count,
        request_sent=request_sent,
        response_received=response_received,
        http_status=http_status,
        error_category=error_category,
        sanitized_error_message=sanitized_error_message,
    )
    return BinanceGatewayResult(**{**result.__dict__, "binance_error_code": binance_error_code})


def _blocked(market_type: str, call_context: BinanceGatewayCallContext, reason: str) -> BinanceGatewayResult:
    return BinanceGatewayResult(
        operation="query_order",
        market_type=market_type,
        endpoint_family=endpoint_family_for_market(market_type),
        success=False,
        response_received=False,
        request_sent=False,
        error_category=reason,
        sanitized_error_message=reason,
        attempt_count=0,
        trace_id=call_context.trace_id,
    )


def get_order_status_gateway() -> BinanceOrderStatusGateway:
    return HttpBinanceOrderStatusGateway()
