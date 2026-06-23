"""BinanceGateway 模块：公共行情受限接口；不写数据库，可访问外部 Binance，不发送 Hermes，不涉及交易执行。"""

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

from .types import BinanceGatewayCallContext, BinanceGatewayResult


LOGGER = logging.getLogger(__name__)

MARKET_TYPE_USDS_M = "usds_m_futures"
MARKET_TYPE_COIN_M = "coin_m_futures"
DATA_COLLECTION_SYMBOL = "BTCUSDT"


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


def utc_from_millis(value: int) -> datetime:
    return datetime.fromtimestamp(value / 1000, tz=UTC)


def millis_from_utc(value: datetime) -> int:
    if value.tzinfo is None:
        raise ValueError("时间必须带 UTC timezone")
    return int(value.astimezone(UTC).timestamp() * 1000)


class FakeBinancePublicMarketGateway:
    """测试替身：不访问真实 Binance。"""

    def __init__(
        self,
        *,
        server_time_utc: datetime | None = None,
        klines: list[list[Any]] | None = None,
        fail_operation: str = "",
    ) -> None:
        self.server_time_utc = server_time_utc or timezone.now()
        self.klines = klines or []
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
            return self._failed("get_server_time", market_type, call_context, "fake_gateway_failed")
        return BinanceGatewayResult(
            operation="get_server_time",
            market_type=market_type,
            endpoint_family=_endpoint_family(market_type),
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
            return self._failed("get_klines", market_type, call_context, "fake_gateway_failed")
        return BinanceGatewayResult(
            operation="get_klines",
            market_type=market_type,
            endpoint_family=_endpoint_family(market_type),
            success=True,
            payload=self.klines[:limit],
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
            endpoint_family=_endpoint_family(market_type),
            success=False,
            response_received=False,
            request_sent=False,
            sanitized_error_message=message,
            attempt_count=1,
            trace_id=call_context.trace_id,
        )


class HttpBinancePublicMarketGateway:
    """真实公共行情 Gateway：只暴露 server time 与 Kline，受外部服务开关保护。"""

    def get_server_time(
        self,
        *,
        market_type: str,
        call_context: BinanceGatewayCallContext,
    ) -> BinanceGatewayResult:
        return self._request_json(
            operation="get_server_time",
            market_type=market_type,
            path="/fapi/v1/time",
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
        if market_type != MARKET_TYPE_USDS_M or symbol != DATA_COLLECTION_SYMBOL:
            return _blocked_result(
                operation="get_klines",
                market_type=market_type,
                call_context=call_context,
                reason="collection_domain_mismatch",
            )
        params = {
            "symbol": symbol,
            "interval": interval,
            "startTime": millis_from_utc(start_time_utc),
            "endTime": millis_from_utc(end_time_utc),
            "limit": limit,
        }
        return self._request_json(
            operation="get_klines",
            market_type=market_type,
            path="/fapi/v1/klines",
            params=params,
            call_context=call_context,
        )

    def _request_json(
        self,
        *,
        operation: str,
        market_type: str,
        path: str,
        params: dict[str, Any],
        call_context: BinanceGatewayCallContext,
    ) -> BinanceGatewayResult:
        if not getattr(settings, "BINANCE_GATEWAY_ENABLED", False):
            return _blocked_result(
                operation=operation,
                market_type=market_type,
                call_context=call_context,
                reason="gateway_disabled",
            )
        if not getattr(settings, "BINANCE_PUBLIC_DATA_ENABLED", False):
            return _blocked_result(
                operation=operation,
                market_type=market_type,
                call_context=call_context,
                reason="public_data_disabled",
            )
        if not getattr(settings, "ALLOW_REAL_EXTERNAL_SERVICES", False):
            return _blocked_result(
                operation=operation,
                market_type=market_type,
                call_context=call_context,
                reason="real_external_services_disabled",
            )
        if market_type != MARKET_TYPE_USDS_M:
            return _blocked_result(
                operation=operation,
                market_type=market_type,
                call_context=call_context,
                reason="unsupported_market_type",
            )

        started = timezone.now()
        attempts = max(1, int(getattr(settings, "BINANCE_SAFE_READ_MAX_ATTEMPTS", 1)))
        url = self._build_url(market_type=market_type, path=path, params=params)
        last_error = ""
        for attempt in range(1, attempts + 1):
            try:
                request = urllib.request.Request(url, method="GET", headers={"User-Agent": "the-cypto/market-data"})
                with urllib.request.urlopen(
                    request,
                    timeout=float(getattr(settings, "BINANCE_READ_TIMEOUT_SECONDS", 10)),
                ) as response:
                    raw = response.read().decode("utf-8")
                    payload = json.loads(raw)
                    finished = timezone.now()
                    server_time = None
                    if operation == "get_server_time" and isinstance(payload, dict) and "serverTime" in payload:
                        server_time = utc_from_millis(int(payload["serverTime"]))
                    return BinanceGatewayResult(
                        operation=operation,
                        market_type=market_type,
                        endpoint_family=_endpoint_family(market_type),
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
            except urllib.error.HTTPError as exc:
                last_error = f"http_{exc.code}"
                if exc.code not in {429, 500, 502, 503, 504}:
                    break
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
                last_error = type(exc).__name__
            if attempt < attempts:
                time.sleep(min(0.2 * attempt, 1.0))

        finished = timezone.now()
        LOGGER.warning(
            "Binance public gateway failed: %s",
            sanitize_mapping({"operation": operation, "error": last_error, "params": params}),
        )
        return BinanceGatewayResult(
            operation=operation,
            market_type=market_type,
            endpoint_family=_endpoint_family(market_type),
            success=False,
            response_received=False,
            request_sent=True,
            sanitized_error_message=last_error or "gateway_failed",
            request_started_at_utc=started,
            request_finished_at_utc=finished,
            latency_ms=int((finished - started).total_seconds() * 1000),
            attempt_count=attempts,
            trace_id=call_context.trace_id,
        )

    @staticmethod
    def _build_url(*, market_type: str, path: str, params: dict[str, Any]) -> str:
        base_url = getattr(settings, "BINANCE_USDS_M_BASE_URL", "") or getattr(settings, "BINANCE_BASE_URL", "")
        if market_type == MARKET_TYPE_COIN_M:
            base_url = getattr(settings, "BINANCE_COIN_M_BASE_URL", "")
        query = urllib.parse.urlencode(params)
        return f"{base_url.rstrip('/')}{path}" + (f"?{query}" if query else "")


def _endpoint_family(market_type: str) -> str:
    if market_type == MARKET_TYPE_USDS_M:
        return "fapi"
    if market_type == MARKET_TYPE_COIN_M:
        return "dapi"
    return "unknown"


def _blocked_result(
    *,
    operation: str,
    market_type: str,
    call_context: BinanceGatewayCallContext,
    reason: str,
) -> BinanceGatewayResult:
    return BinanceGatewayResult(
        operation=operation,
        market_type=market_type,
        endpoint_family=_endpoint_family(market_type),
        success=False,
        response_received=False,
        request_sent=False,
        sanitized_error_message=reason,
        attempt_count=0,
        trace_id=call_context.trace_id,
    )


def get_public_market_gateway() -> PublicMarketGateway:
    return HttpBinancePublicMarketGateway()

