"""BinanceGateway 模块：账户事实只读受限接口；不写数据库；不访问 Redis；可访问外部 Binance；不发送 Hermes；不调用大模型；不涉及交易执行；不允许真实交易。"""

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

from .public_market import (
    classify_http_error,
    failure_result,
    public_base_url,
    read_http_error_message,
    sanitize_error_text,
)
from .types import (
    ERROR_ACCOUNT_READ_DISABLED,
    ERROR_CONFIGURATION_ERROR,
    ERROR_CREDENTIAL_MISSING,
    ERROR_DOMAIN_MISMATCH,
    ERROR_GATEWAY_DISABLED,
    ERROR_GATEWAY_FAILED,
    ERROR_INVALID_MARKET_TYPE,
    ERROR_NETWORK_ERROR,
    ERROR_REAL_EXTERNAL_SERVICES_DISABLED,
    ERROR_REQUEST_VALIDATION_FAILED,
    ERROR_RESPONSE_SCHEMA_ERROR,
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

ACCOUNT_READ_PATHS = {
    "get_account": {
        MARKET_TYPE_USDS_M: "/fapi/v2/account",
        MARKET_TYPE_COIN_M: "/dapi/v1/account",
    },
    "get_balances": {
        MARKET_TYPE_USDS_M: "/fapi/v2/balance",
        MARKET_TYPE_COIN_M: "/dapi/v1/balance",
    },
    "get_positions": {
        MARKET_TYPE_USDS_M: "/fapi/v2/positionRisk",
        MARKET_TYPE_COIN_M: "/dapi/v1/positionRisk",
    },
}


class AccountReadGateway(Protocol):
    def get_account(
        self,
        *,
        market_type: str,
        account_domain: str,
        call_context: BinanceGatewayCallContext,
    ) -> BinanceGatewayResult: ...

    def get_balances(
        self,
        *,
        market_type: str,
        account_domain: str,
        call_context: BinanceGatewayCallContext,
    ) -> BinanceGatewayResult: ...

    def get_positions(
        self,
        *,
        market_type: str,
        account_domain: str,
        call_context: BinanceGatewayCallContext,
        symbol: str = "",
    ) -> BinanceGatewayResult: ...


class FakeBinanceAccountReadGateway:
    """测试替身：记录账户只读调用，不访问真实 Binance。"""

    def __init__(
        self,
        *,
        account_payload: Any | None = None,
        balances_payload: Any | None = None,
        positions_payload: Any | None = None,
        fail_operation: str = "",
    ) -> None:
        self.account_payload = account_payload or {"assets": [], "positions": []}
        self.balances_payload = balances_payload or []
        self.positions_payload = positions_payload or []
        self.fail_operation = fail_operation
        self.calls: list[dict[str, Any]] = []

    def get_account(
        self,
        *,
        market_type: str,
        account_domain: str,
        call_context: BinanceGatewayCallContext,
    ) -> BinanceGatewayResult:
        self.calls.append({"operation": "get_account", "market_type": market_type, "account_domain": account_domain})
        return self._result("get_account", market_type, call_context, self.account_payload)

    def get_balances(
        self,
        *,
        market_type: str,
        account_domain: str,
        call_context: BinanceGatewayCallContext,
    ) -> BinanceGatewayResult:
        self.calls.append({"operation": "get_balances", "market_type": market_type, "account_domain": account_domain})
        return self._result("get_balances", market_type, call_context, self.balances_payload)

    def get_positions(
        self,
        *,
        market_type: str,
        account_domain: str,
        call_context: BinanceGatewayCallContext,
        symbol: str = "",
    ) -> BinanceGatewayResult:
        self.calls.append(
            {"operation": "get_positions", "market_type": market_type, "account_domain": account_domain, "symbol": symbol}
        )
        return self._result("get_positions", market_type, call_context, self.positions_payload)

    def _result(
        self,
        operation: str,
        market_type: str,
        call_context: BinanceGatewayCallContext,
        payload: Any,
    ) -> BinanceGatewayResult:
        if self.fail_operation == operation:
            return BinanceGatewayResult(
                operation=operation,
                market_type=market_type,
                endpoint_family=endpoint_family_for_market(market_type),
                success=False,
                request_sent=False,
                error_category=ERROR_GATEWAY_FAILED,
                sanitized_error_message=ERROR_GATEWAY_FAILED,
                trace_id=call_context.trace_id,
            )
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


class HttpBinanceAccountReadGateway:
    """真实账户只读 Gateway：只用 READ 凭证签名，不使用 TRADE 凭证。"""

    def get_account(
        self,
        *,
        market_type: str,
        account_domain: str,
        call_context: BinanceGatewayCallContext,
    ) -> BinanceGatewayResult:
        return self._request_signed_read_json(
            operation="get_account",
            market_type=market_type,
            account_domain=account_domain,
            params={},
            call_context=call_context,
        )

    def get_balances(
        self,
        *,
        market_type: str,
        account_domain: str,
        call_context: BinanceGatewayCallContext,
    ) -> BinanceGatewayResult:
        return self._request_signed_read_json(
            operation="get_balances",
            market_type=market_type,
            account_domain=account_domain,
            params={},
            call_context=call_context,
        )

    def get_positions(
        self,
        *,
        market_type: str,
        account_domain: str,
        call_context: BinanceGatewayCallContext,
        symbol: str = "",
    ) -> BinanceGatewayResult:
        normalized_symbol = symbol.strip().upper()
        params = {"symbol": normalized_symbol} if normalized_symbol else {}
        return self._request_signed_read_json(
            operation="get_positions",
            market_type=market_type,
            account_domain=account_domain,
            params=params,
            call_context=call_context,
        )

    def _request_signed_read_json(
        self,
        *,
        operation: str,
        market_type: str,
        account_domain: str,
        params: dict[str, Any],
        call_context: BinanceGatewayCallContext,
    ) -> BinanceGatewayResult:
        normalized_market_type = normalize_active_market_type(market_type)
        blocked = validate_account_read_request(
            operation=operation,
            market_type=normalized_market_type,
            account_domain=account_domain,
            call_context=call_context,
        )
        if blocked is not None:
            return blocked

        api_key, api_secret = read_credentials_for_market(normalized_market_type)
        if not api_key or not api_secret:
            return blocked_account_result(operation, normalized_market_type, call_context, ERROR_CREDENTIAL_MISSING)

        started = timezone.now()
        attempts = max(1, int(getattr(settings, "BINANCE_SAFE_READ_MAX_ATTEMPTS", 1)))
        url = build_signed_read_url(market_type=normalized_market_type, operation=operation, params=params, api_secret=api_secret)
        last_error = ERROR_GATEWAY_FAILED
        last_category = ERROR_GATEWAY_FAILED
        last_http_status = None
        for attempt in range(1, attempts + 1):
            try:
                request = urllib.request.Request(url, method="GET", headers=read_headers(api_key))
                with urllib.request.urlopen(
                    request,
                    timeout=float(getattr(settings, "BINANCE_READ_TIMEOUT_SECONDS", 10)),
                ) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                    return account_success_result(
                        operation=operation,
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
            "Binance account read gateway failed: %s",
            sanitize_mapping({"operation": operation, "error": last_error, "params": params}),
        )
        return failure_result(
            operation=operation,
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


def validate_account_read_request(
    *,
    operation: str,
    market_type: str,
    account_domain: str,
    call_context: BinanceGatewayCallContext,
) -> BinanceGatewayResult | None:
    if not getattr(settings, "BINANCE_GATEWAY_ENABLED", False):
        return blocked_account_result(operation, market_type, call_context, ERROR_GATEWAY_DISABLED)
    if not getattr(settings, "BINANCE_ACCOUNT_READ_ENABLED", False):
        return blocked_account_result(operation, market_type, call_context, ERROR_ACCOUNT_READ_DISABLED)
    if not getattr(settings, "ALLOW_REAL_EXTERNAL_SERVICES", False):
        return blocked_account_result(operation, market_type, call_context, ERROR_REAL_EXTERNAL_SERVICES_DISABLED)
    if not is_supported_market_type(market_type):
        return blocked_account_result(operation, market_type, call_context, ERROR_INVALID_MARKET_TYPE)
    if market_type != active_market_type():
        return blocked_account_result(operation, market_type, call_context, ERROR_DOMAIN_MISMATCH)
    if not public_base_url(market_type):
        return blocked_account_result(operation, market_type, call_context, ERROR_CONFIGURATION_ERROR)
    if not account_domain:
        return blocked_account_result(operation, market_type, call_context, ERROR_REQUEST_VALIDATION_FAILED)
    if account_domain != getattr(settings, "ACTIVE_ACCOUNT_DOMAIN", ""):
        return blocked_account_result(operation, market_type, call_context, ERROR_DOMAIN_MISMATCH)
    return None


def read_credentials_for_market(market_type: str) -> tuple[str, str]:
    if market_type == MARKET_TYPE_COIN_M:
        return (
            getattr(settings, "BINANCE_COIN_M_READ_API_KEY", ""),
            getattr(settings, "BINANCE_COIN_M_READ_API_SECRET", ""),
        )
    return (
        getattr(settings, "BINANCE_USDS_M_READ_API_KEY", ""),
        getattr(settings, "BINANCE_USDS_M_READ_API_SECRET", ""),
    )


def active_market_type() -> str:
    return normalize_active_market_type(getattr(settings, "ACTIVE_MARKET_TYPE", ""))


def build_signed_read_url(*, market_type: str, operation: str, params: dict[str, Any], api_secret: str) -> str:
    payload = dict(params)
    payload["timestamp"] = utc_millis(timezone.now())
    payload["recvWindow"] = int(getattr(settings, "BINANCE_RECV_WINDOW_MS", 5000))
    query_without_signature = urllib.parse.urlencode(payload)
    signature = hmac.new(api_secret.encode("utf-8"), query_without_signature.encode("utf-8"), hashlib.sha256).hexdigest()
    query = f"{query_without_signature}&signature={signature}"
    path = ACCOUNT_READ_PATHS[operation][market_type]
    return f"{public_base_url(market_type).rstrip('/')}{path}?{query}"


def utc_millis(value: datetime) -> int:
    return int(value.timestamp() * 1000)


def read_headers(api_key: str) -> dict[str, str]:
    return {
        "User-Agent": "the-cypto/binance-account-read",
        "X-MBX-APIKEY": api_key,
    }


def account_success_result(
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
    return BinanceGatewayResult(
        operation=operation,
        market_type=market_type,
        endpoint_family=endpoint_family_for_market(market_type),
        success=True,
        payload=payload,
        response_received=True,
        request_sent=True,
        http_status=response.status,
        request_started_at_utc=started,
        request_finished_at_utc=finished,
        latency_ms=int((finished - started).total_seconds() * 1000),
        attempt_count=attempt,
        trace_id=call_context.trace_id,
    )


def blocked_account_result(
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


def get_account_read_gateway() -> AccountReadGateway:
    return HttpBinanceAccountReadGateway()
