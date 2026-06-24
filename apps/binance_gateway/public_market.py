"""BinanceGateway 模块：公共行情受限接口；不写数据库；不访问 Redis；可访问外部 Binance；不发送 Hermes；不调用大模型；不涉及交易执行；不允许真实交易。"""

from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from typing import Any, Protocol

from django.conf import settings
from django.utils import timezone

from apps.foundation.redaction import sanitize_mapping

from .types import (
    ERROR_BINANCE_REJECTED,
    ERROR_COLLECTION_DOMAIN_MISMATCH,
    ERROR_CONFIGURATION_ERROR,
    ERROR_DOMAIN_MISMATCH,
    ERROR_GATEWAY_DISABLED,
    ERROR_GATEWAY_FAILED,
    ERROR_INVALID_MARKET_TYPE,
    ERROR_NETWORK_ERROR,
    ERROR_PUBLIC_DATA_DISABLED,
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

DATA_COLLECTION_SYMBOL = "BTCUSDT"

PUBLIC_PATHS = {
    "get_server_time": {
        MARKET_TYPE_USDS_M: "/fapi/v1/time",
        MARKET_TYPE_COIN_M: "/dapi/v1/time",
    },
    "get_klines": {
        MARKET_TYPE_USDS_M: "/fapi/v1/klines",
        MARKET_TYPE_COIN_M: "/dapi/v1/klines",
    },
    "get_mark_price": {
        MARKET_TYPE_USDS_M: "/fapi/v1/premiumIndex",
        MARKET_TYPE_COIN_M: "/dapi/v1/premiumIndex",
    },
    "get_book_ticker": {
        MARKET_TYPE_USDS_M: "/fapi/v1/ticker/bookTicker",
        MARKET_TYPE_COIN_M: "/dapi/v1/ticker/bookTicker",
    },
    "get_exchange_info": {
        MARKET_TYPE_USDS_M: "/fapi/v1/exchangeInfo",
        MARKET_TYPE_COIN_M: "/dapi/v1/exchangeInfo",
    },
}


class PublicMarketGateway(Protocol):
    def get_server_time(
        self,
        *,
        market_type: str,
        call_context: BinanceGatewayCallContext,
    ) -> BinanceGatewayResult: ...

    def get_klines(
        self,
        *,
        market_type: str,
        symbol: str,
        interval: str,
        start_time_utc: datetime,
        end_time_utc: datetime,
        limit: int,
        call_context: BinanceGatewayCallContext,
    ) -> BinanceGatewayResult: ...

    def get_mark_price(
        self,
        *,
        market_type: str,
        symbol: str,
        call_context: BinanceGatewayCallContext,
    ) -> BinanceGatewayResult: ...

    def get_book_ticker(
        self,
        *,
        market_type: str,
        symbol: str,
        call_context: BinanceGatewayCallContext,
    ) -> BinanceGatewayResult: ...

    def get_exchange_info(
        self,
        *,
        market_type: str,
        call_context: BinanceGatewayCallContext,
    ) -> BinanceGatewayResult: ...

    def get_symbol_exchange_info(
        self,
        *,
        market_type: str,
        symbol: str,
        call_context: BinanceGatewayCallContext,
    ) -> BinanceGatewayResult: ...


def utc_from_millis(value: int) -> datetime:
    return datetime.fromtimestamp(value / 1000, tz=UTC)


def millis_from_utc(value: datetime) -> int:
    if value.tzinfo is None:
        raise ValueError("时间必须携带 UTC timezone")
    return int(value.astimezone(UTC).timestamp() * 1000)


class FakeBinancePublicMarketGateway:
    """测试替身：记录调用，不访问真实 Binance。"""

    def __init__(
        self,
        *,
        server_time_utc: datetime | None = None,
        klines: list[list[Any]] | None = None,
        mark_price_payload: Any | None = None,
        book_ticker_payload: Any | None = None,
        exchange_info_payload: Any | None = None,
        fail_operation: str = "",
    ) -> None:
        self.server_time_utc = server_time_utc or timezone.now()
        self.klines = klines or []
        self.mark_price_payload = mark_price_payload or {"symbol": DATA_COLLECTION_SYMBOL, "markPrice": "100"}
        self.book_ticker_payload = book_ticker_payload or {"symbol": DATA_COLLECTION_SYMBOL, "bidPrice": "99", "askPrice": "101"}
        self.exchange_info_payload = exchange_info_payload or {"symbols": [{"symbol": DATA_COLLECTION_SYMBOL}]}
        self.fail_operation = fail_operation
        self.calls: list[dict[str, Any]] = []

    def get_server_time(
        self,
        *,
        market_type: str,
        call_context: BinanceGatewayCallContext,
    ) -> BinanceGatewayResult:
        self.calls.append({"operation": "get_server_time", "market_type": market_type})
        if self.fail_operation == "get_server_time":
            return self._failed("get_server_time", market_type, call_context, ERROR_GATEWAY_FAILED)
        return BinanceGatewayResult(
            operation="get_server_time",
            market_type=market_type,
            endpoint_family=endpoint_family_for_market(market_type),
            success=True,
            payload={"serverTime": millis_from_utc(self.server_time_utc)},
            response_received=True,
            request_sent=True,
            server_time_utc=self.server_time_utc.astimezone(UTC),
            attempt_count=1,
            trace_id=call_context.trace_id,
        )

    def get_klines(
        self,
        *,
        market_type: str,
        symbol: str,
        interval: str,
        start_time_utc: datetime,
        end_time_utc: datetime,
        limit: int,
        call_context: BinanceGatewayCallContext,
    ) -> BinanceGatewayResult:
        self.calls.append(
            {
                "operation": "get_klines",
                "market_type": market_type,
                "symbol": symbol,
                "interval": interval,
                "start_time_utc": start_time_utc,
                "end_time_utc": end_time_utc,
                "limit": limit,
                "timeZone": None,
            }
        )
        if self.fail_operation == "get_klines":
            return self._failed("get_klines", market_type, call_context, ERROR_GATEWAY_FAILED)
        return self._success("get_klines", market_type, call_context, self.klines[:limit])

    def get_mark_price(
        self,
        *,
        market_type: str,
        symbol: str,
        call_context: BinanceGatewayCallContext,
    ) -> BinanceGatewayResult:
        self.calls.append({"operation": "get_mark_price", "market_type": market_type, "symbol": symbol})
        if self.fail_operation == "get_mark_price":
            return self._failed("get_mark_price", market_type, call_context, ERROR_GATEWAY_FAILED)
        return self._success("get_mark_price", market_type, call_context, self.mark_price_payload)

    def get_book_ticker(
        self,
        *,
        market_type: str,
        symbol: str,
        call_context: BinanceGatewayCallContext,
    ) -> BinanceGatewayResult:
        self.calls.append({"operation": "get_book_ticker", "market_type": market_type, "symbol": symbol})
        if self.fail_operation == "get_book_ticker":
            return self._failed("get_book_ticker", market_type, call_context, ERROR_GATEWAY_FAILED)
        return self._success("get_book_ticker", market_type, call_context, self.book_ticker_payload)

    def get_exchange_info(
        self,
        *,
        market_type: str,
        call_context: BinanceGatewayCallContext,
    ) -> BinanceGatewayResult:
        self.calls.append({"operation": "get_exchange_info", "market_type": market_type})
        if self.fail_operation == "get_exchange_info":
            return self._failed("get_exchange_info", market_type, call_context, ERROR_GATEWAY_FAILED)
        return self._success("get_exchange_info", market_type, call_context, self.exchange_info_payload)

    def get_symbol_exchange_info(
        self,
        *,
        market_type: str,
        symbol: str,
        call_context: BinanceGatewayCallContext,
    ) -> BinanceGatewayResult:
        self.calls.append({"operation": "get_symbol_exchange_info", "market_type": market_type, "symbol": symbol})
        if self.fail_operation == "get_symbol_exchange_info":
            return self._failed("get_symbol_exchange_info", market_type, call_context, ERROR_GATEWAY_FAILED)
        return self._success("get_symbol_exchange_info", market_type, call_context, self.exchange_info_payload)

    @staticmethod
    def _success(
        operation: str,
        market_type: str,
        call_context: BinanceGatewayCallContext,
        payload: Any,
    ) -> BinanceGatewayResult:
        return BinanceGatewayResult(
            operation=operation,
            market_type=market_type,
            endpoint_family=endpoint_family_for_market(market_type),
            success=True,
            payload=payload,
            response_received=True,
            request_sent=True,
            attempt_count=1,
            trace_id=call_context.trace_id,
        )

    @staticmethod
    def _failed(
        operation: str,
        market_type: str,
        call_context: BinanceGatewayCallContext,
        message: str,
    ) -> BinanceGatewayResult:
        return BinanceGatewayResult(
            operation=operation,
            market_type=market_type,
            endpoint_family=endpoint_family_for_market(market_type),
            success=False,
            response_received=False,
            request_sent=False,
            error_category=message,
            sanitized_error_message=message,
            attempt_count=1,
            trace_id=call_context.trace_id,
        )


class HttpBinancePublicMarketGateway:
    """真实公共行情 Gateway：只做公共读取，公共接口不加载 API key 或 secret。"""

    def get_server_time(
        self,
        *,
        market_type: str,
        call_context: BinanceGatewayCallContext,
    ) -> BinanceGatewayResult:
        return self._request_public_json(
            operation="get_server_time",
            market_type=market_type,
            params={},
            call_context=call_context,
        )

    def get_klines(
        self,
        *,
        market_type: str,
        symbol: str,
        interval: str,
        start_time_utc: datetime,
        end_time_utc: datetime,
        limit: int,
        call_context: BinanceGatewayCallContext,
    ) -> BinanceGatewayResult:
        normalized_market_type = normalize_active_market_type(market_type)
        normalized_symbol = symbol.strip().upper()
        if normalized_market_type != MARKET_TYPE_USDS_M or normalized_symbol != DATA_COLLECTION_SYMBOL:
            return blocked_result(
                operation="get_klines",
                market_type=normalized_market_type,
                call_context=call_context,
                reason=ERROR_COLLECTION_DOMAIN_MISMATCH,
            )
        params = {
            "symbol": normalized_symbol,
            "interval": interval,
            "startTime": millis_from_utc(start_time_utc),
            "endTime": millis_from_utc(end_time_utc),
            "limit": limit,
        }
        return self._request_public_json(
            operation="get_klines",
            market_type=normalized_market_type,
            params=params,
            call_context=call_context,
        )

    def get_mark_price(
        self,
        *,
        market_type: str,
        symbol: str,
        call_context: BinanceGatewayCallContext,
    ) -> BinanceGatewayResult:
        return self._request_symbol_public_json(
            operation="get_mark_price",
            market_type=market_type,
            symbol=symbol,
            call_context=call_context,
            require_active_market=True,
        )

    def get_book_ticker(
        self,
        *,
        market_type: str,
        symbol: str,
        call_context: BinanceGatewayCallContext,
    ) -> BinanceGatewayResult:
        return self._request_symbol_public_json(
            operation="get_book_ticker",
            market_type=market_type,
            symbol=symbol,
            call_context=call_context,
            require_active_market=True,
        )

    def get_exchange_info(
        self,
        *,
        market_type: str,
        call_context: BinanceGatewayCallContext,
    ) -> BinanceGatewayResult:
        return self._request_public_json(
            operation="get_exchange_info",
            market_type=market_type,
            params={},
            call_context=call_context,
            require_active_market=True,
        )

    def get_symbol_exchange_info(
        self,
        *,
        market_type: str,
        symbol: str,
        call_context: BinanceGatewayCallContext,
    ) -> BinanceGatewayResult:
        return self._request_symbol_public_json(
            operation="get_exchange_info",
            market_type=market_type,
            symbol=symbol,
            call_context=call_context,
            result_operation="get_symbol_exchange_info",
            require_active_market=True,
        )

    def _request_symbol_public_json(
        self,
        *,
        operation: str,
        market_type: str,
        symbol: str,
        call_context: BinanceGatewayCallContext,
        result_operation: str | None = None,
        require_active_market: bool = False,
    ) -> BinanceGatewayResult:
        normalized_symbol = symbol.strip().upper()
        if not normalized_symbol:
            return blocked_result(
                operation=result_operation or operation,
                market_type=normalize_active_market_type(market_type),
                call_context=call_context,
                reason=ERROR_REQUEST_VALIDATION_FAILED,
            )
        return self._request_public_json(
            operation=operation,
            result_operation=result_operation,
            market_type=market_type,
            params={"symbol": normalized_symbol},
            call_context=call_context,
            require_active_market=require_active_market,
        )

    def _request_public_json(
        self,
        *,
        operation: str,
        market_type: str,
        params: dict[str, Any],
        call_context: BinanceGatewayCallContext,
        result_operation: str | None = None,
        require_active_market: bool = False,
    ) -> BinanceGatewayResult:
        effective_operation = result_operation or operation
        normalized_market_type = normalize_active_market_type(market_type)
        blocked = validate_public_request(
            operation=effective_operation,
            market_type=normalized_market_type,
            call_context=call_context,
            require_active_market=require_active_market,
        )
        if blocked is not None:
            return blocked

        started = timezone.now()
        attempts = max(1, int(getattr(settings, "BINANCE_SAFE_READ_MAX_ATTEMPTS", 1)))
        url = build_public_url(market_type=normalized_market_type, operation=operation, params=params)
        last_error = ERROR_GATEWAY_FAILED
        last_category = ERROR_GATEWAY_FAILED
        last_http_status = None
        for attempt in range(1, attempts + 1):
            try:
                request = urllib.request.Request(url, method="GET", headers={"User-Agent": "the-cypto/binance-public"})
                with urllib.request.urlopen(
                    request,
                    timeout=float(getattr(settings, "BINANCE_READ_TIMEOUT_SECONDS", 10)),
                ) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                    return public_success_result(
                        operation=effective_operation,
                        market_type=normalized_market_type,
                        payload=payload,
                        response=response,
                        started=started,
                        attempt=attempt,
                        call_context=call_context,
                    )
            except urllib.error.HTTPError as exc:
                last_http_status = exc.code
                last_category = classify_http_error(exc.code)
                last_error = read_http_error_message(exc, last_category)
                if exc.code not in {429, 500, 502, 503, 504}:
                    break
            except TimeoutError:
                last_category = ERROR_TIMEOUT
                last_error = ERROR_TIMEOUT
            except urllib.error.URLError as exc:
                last_category = ERROR_NETWORK_ERROR
                last_error = sanitize_error_text(str(exc.reason))
            except (json.JSONDecodeError, UnicodeDecodeError):
                last_category = ERROR_RESPONSE_SCHEMA_ERROR
                last_error = ERROR_RESPONSE_SCHEMA_ERROR
                break
            if attempt < attempts:
                time.sleep(min(0.2 * attempt, 1.0))

        LOGGER.warning(
            "Binance public gateway failed: %s",
            sanitize_mapping({"operation": effective_operation, "error": last_error, "params": params}),
        )
        return failure_result(
            operation=effective_operation,
            market_type=normalized_market_type,
            call_context=call_context,
            started=started,
            attempt_count=attempts,
            request_sent=True,
            response_received=last_http_status is not None,
            http_status=last_http_status,
            error_category=last_category,
            sanitized_error_message=last_error,
        )


def validate_public_request(
    *,
    operation: str,
    market_type: str,
    call_context: BinanceGatewayCallContext,
    require_active_market: bool = False,
) -> BinanceGatewayResult | None:
    if not getattr(settings, "BINANCE_GATEWAY_ENABLED", False):
        return blocked_result(operation=operation, market_type=market_type, call_context=call_context, reason=ERROR_GATEWAY_DISABLED)
    if not getattr(settings, "BINANCE_PUBLIC_DATA_ENABLED", False):
        return blocked_result(operation=operation, market_type=market_type, call_context=call_context, reason=ERROR_PUBLIC_DATA_DISABLED)
    if not getattr(settings, "ALLOW_REAL_EXTERNAL_SERVICES", False):
        return blocked_result(
            operation=operation,
            market_type=market_type,
            call_context=call_context,
            reason=ERROR_REAL_EXTERNAL_SERVICES_DISABLED,
        )
    if not is_supported_market_type(market_type):
        return blocked_result(operation=operation, market_type=market_type, call_context=call_context, reason=ERROR_INVALID_MARKET_TYPE)
    if require_active_market and market_type != active_market_type():
        return blocked_result(operation=operation, market_type=market_type, call_context=call_context, reason=ERROR_DOMAIN_MISMATCH)
    if not public_base_url(market_type):
        return blocked_result(operation=operation, market_type=market_type, call_context=call_context, reason=ERROR_CONFIGURATION_ERROR)
    return None


def build_public_url(*, market_type: str, operation: str, params: dict[str, Any]) -> str:
    base_url = public_base_url(market_type)
    path = PUBLIC_PATHS[operation][market_type]
    query = urllib.parse.urlencode(params)
    return f"{base_url.rstrip('/')}{path}" + (f"?{query}" if query else "")


def public_base_url(market_type: str) -> str:
    if market_type == MARKET_TYPE_COIN_M:
        return getattr(settings, "BINANCE_COIN_M_BASE_URL", "")
    return getattr(settings, "BINANCE_USDS_M_BASE_URL", "") or getattr(settings, "BINANCE_BASE_URL", "")


def active_market_type() -> str:
    return normalize_active_market_type(getattr(settings, "ACTIVE_MARKET_TYPE", ""))


def public_success_result(
    *,
    operation: str,
    market_type: str,
    payload: Any,
    response: Any,
    started: datetime,
    attempt: int,
    call_context: BinanceGatewayCallContext,
) -> BinanceGatewayResult:
    finished = timezone.now()
    server_time = None
    if operation == "get_server_time" and isinstance(payload, dict) and "serverTime" in payload:
        server_time = utc_from_millis(int(payload["serverTime"]))
    return BinanceGatewayResult(
        operation=operation,
        market_type=market_type,
        endpoint_family=endpoint_family_for_market(market_type),
        success=True,
        payload=payload,
        response_received=True,
        request_sent=True,
        http_status=response.status,
        server_time_utc=server_time,
        request_started_at_utc=started,
        request_finished_at_utc=finished,
        latency_ms=int((finished - started).total_seconds() * 1000),
        attempt_count=attempt,
        trace_id=call_context.trace_id,
    )


def blocked_result(
    *,
    operation: str,
    market_type: str,
    call_context: BinanceGatewayCallContext,
    reason: str,
) -> BinanceGatewayResult:
    return BinanceGatewayResult(
        operation=operation,
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


def failure_result(
    *,
    operation: str,
    market_type: str,
    call_context: BinanceGatewayCallContext,
    started: datetime,
    attempt_count: int,
    request_sent: bool,
    response_received: bool,
    http_status: int | None,
    error_category: str,
    sanitized_error_message: str,
) -> BinanceGatewayResult:
    finished = timezone.now()
    return BinanceGatewayResult(
        operation=operation,
        market_type=market_type,
        endpoint_family=endpoint_family_for_market(market_type),
        success=False,
        response_received=response_received,
        request_sent=request_sent,
        http_status=http_status,
        error_category=error_category,
        sanitized_error_message=sanitized_error_message,
        request_started_at_utc=started,
        request_finished_at_utc=finished,
        latency_ms=int((finished - started).total_seconds() * 1000),
        attempt_count=attempt_count,
        trace_id=call_context.trace_id,
    )


def classify_http_error(http_status: int) -> str:
    if http_status == 429:
        return ERROR_RATE_LIMITED
    if http_status in {500, 502, 503, 504}:
        return ERROR_SERVER_ERROR
    return ERROR_BINANCE_REJECTED


def read_http_error_message(exc: urllib.error.HTTPError, fallback: str) -> str:
    try:
        body = exc.read().decode("utf-8")
    except (OSError, UnicodeDecodeError):
        return fallback
    return sanitize_error_text(body) or fallback


def sanitize_error_text(value: str) -> str:
    return str(sanitize_mapping({"error": value}).get("error", ""))[:500]


def get_public_market_gateway() -> PublicMarketGateway:
    return HttpBinancePublicMarketGateway()


def _endpoint_family(market_type: str) -> str:
    return endpoint_family_for_market(market_type)


def _blocked_result(
    *,
    operation: str,
    market_type: str,
    call_context: BinanceGatewayCallContext,
    reason: str,
) -> BinanceGatewayResult:
    return blocked_result(operation=operation, market_type=market_type, call_context=call_context, reason=reason)
