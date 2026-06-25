"""BinanceGateway 模块：订单提交受限接口；不写数据库；不访问 Redis；可访问外部 Binance；不发送 Hermes；不调用大模型；涉及交易执行通信；仅在硬开关通过时允许真实订单提交。"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from typing import Any, Protocol

from django.conf import settings
from django.utils import timezone

from apps.foundation.redaction import sanitize_mapping

from .account_read import utc_millis
from .public_market import (
    failure_result,
    public_base_url,
    read_http_error_message,
    sanitize_error_text,
)
from .types import (
    ERROR_BINANCE_REJECTED,
    ERROR_CONFIGURATION_ERROR,
    ERROR_CREDENTIAL_MISSING,
    ERROR_DOMAIN_MISMATCH,
    ERROR_GATEWAY_DISABLED,
    ERROR_GATEWAY_FAILED,
    ERROR_INVALID_MARKET_TYPE,
    ERROR_NETWORK_ERROR,
    ERROR_ORDER_SUBMISSION_DISABLED,
    ERROR_RATE_LIMITED,
    ERROR_REAL_EXTERNAL_SERVICES_DISABLED,
    ERROR_REAL_TRADING_DISABLED,
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

ORDER_SUBMISSION_PATHS = {
    MARKET_TYPE_USDS_M: "/fapi/v1/order",
    MARKET_TYPE_COIN_M: "/dapi/v1/order",
}


class BinanceOrderSubmissionGateway(Protocol):
    def submit_order(
        self,
        *,
        market_type: str,
        frozen_order_request: dict[str, Any],
        call_context: BinanceGatewayCallContext,
    ) -> BinanceGatewayResult: ...


class FakeBinanceOrderSubmissionGateway:
    """测试替身：记录订单提交调用，不访问真实 Binance。"""

    def __init__(self, *, result: BinanceGatewayResult | None = None, payload: dict[str, Any] | None = None) -> None:
        self.result = result
        self.payload = payload
        self.calls: list[dict[str, Any]] = []

    def submit_order(
        self,
        *,
        market_type: str,
        frozen_order_request: dict[str, Any],
        call_context: BinanceGatewayCallContext,
    ) -> BinanceGatewayResult:
        self.calls.append(
            {
                "operation": "submit_order",
                "market_type": market_type,
                "frozen_order_request": dict(frozen_order_request),
                "call_context": call_context,
            }
        )
        if self.result is not None:
            return self.result
        payload = dict(self.payload) if self.payload is not None else {"orderId": 123456, "status": "NEW"}
        payload.setdefault("clientOrderId", frozen_order_request.get("newClientOrderId", ""))
        return BinanceGatewayResult(
            operation="submit_order",
            market_type=market_type,
            endpoint_family=endpoint_family_for_market(market_type),
            success=True,
            payload=payload,
            response_received=True,
            request_sent=True,
            http_status=200,
            request_started_at_utc=timezone.now(),
            request_finished_at_utc=timezone.now(),
            attempt_count=1,
            trace_id=call_context.trace_id,
        )


class HttpBinanceOrderSubmissionGateway:
    """真实订单提交 Gateway：只用 TRADE 凭证，且订单提交绝不重试。"""

    def submit_order(
        self,
        *,
        market_type: str,
        frozen_order_request: dict[str, Any],
        call_context: BinanceGatewayCallContext,
    ) -> BinanceGatewayResult:
        normalized_market_type = normalize_active_market_type(market_type)
        blocked = validate_order_submission_request(
            market_type=normalized_market_type,
            frozen_order_request=frozen_order_request,
            call_context=call_context,
        )
        if blocked is not None:
            return blocked

        api_key, api_secret = trade_credentials_for_market(normalized_market_type)
        if not api_key or not api_secret:
            return blocked_order_result(normalized_market_type, call_context, ERROR_CREDENTIAL_MISSING)

        started = timezone.now()
        try:
            url, body = build_signed_order_request(
                market_type=normalized_market_type,
                frozen_order_request=frozen_order_request,
                api_secret=api_secret,
            )
            request = urllib.request.Request(url, data=body.encode("utf-8"), method="POST", headers=trade_headers(api_key))
            with urllib.request.urlopen(
                request,
                timeout=float(getattr(settings, "BINANCE_READ_TIMEOUT_SECONDS", 10)),
            ) as response:
                payload = json.loads(response.read().decode("utf-8"))
                return order_success_result(
                    market_type=normalized_market_type,
                    payload=payload,
                    response=response,
                    started=started,
                    call_context=call_context,
                )
        except urllib.error.HTTPError as exc:
            category = classify_order_http_error(exc.code)
            return failure_result(
                operation="submit_order",
                market_type=normalized_market_type,
                call_context=call_context,
                started=started,
                attempt_count=1,
                request_sent=True,
                response_received=True,
                http_status=exc.code,
                error_category=category,
                sanitized_error_message=read_http_error_message(exc, category),
            )
        except TimeoutError:
            return _single_attempt_failure(normalized_market_type, call_context, started, ERROR_TIMEOUT, request_sent=True)
        except urllib.error.URLError as exc:
            return _single_attempt_failure(
                normalized_market_type,
                call_context,
                started,
                ERROR_NETWORK_ERROR,
                request_sent=True,
                message=sanitize_error_text(str(exc.reason)),
            )
        except (json.JSONDecodeError, UnicodeDecodeError):
            return _single_attempt_failure(normalized_market_type, call_context, started, ERROR_RESPONSE_SCHEMA_ERROR, request_sent=True)
        except Exception as exc:
            LOGGER.warning("Binance order submission gateway failed during send: %s", sanitize_mapping({"error": type(exc).__name__}))
            return _single_attempt_failure(
                normalized_market_type,
                call_context,
                started,
                ERROR_GATEWAY_FAILED,
                request_sent=True,
                message=type(exc).__name__,
            )


def validate_order_submission_request(
    *,
    market_type: str,
    frozen_order_request: dict[str, Any],
    call_context: BinanceGatewayCallContext,
) -> BinanceGatewayResult | None:
    if not getattr(settings, "BINANCE_GATEWAY_ENABLED", False):
        return blocked_order_result(market_type, call_context, ERROR_GATEWAY_DISABLED)
    if not getattr(settings, "BINANCE_ORDER_SUBMISSION_ENABLED", False):
        return blocked_order_result(market_type, call_context, ERROR_ORDER_SUBMISSION_DISABLED)
    if not getattr(settings, "ALLOW_REAL_EXTERNAL_SERVICES", False):
        return blocked_order_result(market_type, call_context, ERROR_REAL_EXTERNAL_SERVICES_DISABLED)
    if not getattr(settings, "DEPLOYMENT_REAL_TRADING_ENABLED", False):
        return blocked_order_result(market_type, call_context, ERROR_REAL_TRADING_DISABLED)
    if not is_supported_market_type(market_type):
        return blocked_order_result(market_type, call_context, ERROR_INVALID_MARKET_TYPE)
    if market_type != active_market_type():
        return blocked_order_result(market_type, call_context, ERROR_DOMAIN_MISMATCH)
    if call_context.account_domain and call_context.account_domain != getattr(settings, "ACTIVE_ACCOUNT_DOMAIN", ""):
        return blocked_order_result(market_type, call_context, ERROR_DOMAIN_MISMATCH)
    if not public_base_url(market_type):
        return blocked_order_result(market_type, call_context, ERROR_CONFIGURATION_ERROR)
    if order_request_error(frozen_order_request):
        return blocked_order_result(market_type, call_context, ERROR_REQUEST_VALIDATION_FAILED)
    return None


def order_request_error(frozen_order_request: dict[str, Any]) -> bool:
    if not isinstance(frozen_order_request, dict):
        return True
    if frozen_order_request.get("type") != "MARKET":
        return True
    if frozen_order_request.get("side") not in {"BUY", "SELL"}:
        return True
    if not frozen_order_request.get("symbol") or not frozen_order_request.get("quantity") or not frozen_order_request.get("newClientOrderId"):
        return True
    forbidden = {"price", "stopPrice", "timeInForce", "idempotency_key", "signature"}
    return any(key in frozen_order_request for key in forbidden)


def trade_credentials_for_market(market_type: str) -> tuple[str, str]:
    if market_type == MARKET_TYPE_COIN_M:
        return (
            getattr(settings, "BINANCE_COIN_M_TRADE_API_KEY", ""),
            getattr(settings, "BINANCE_COIN_M_TRADE_API_SECRET", ""),
        )
    return (
        getattr(settings, "BINANCE_USDS_M_TRADE_API_KEY", ""),
        getattr(settings, "BINANCE_USDS_M_TRADE_API_SECRET", ""),
    )


def active_market_type() -> str:
    return normalize_active_market_type(getattr(settings, "ACTIVE_MARKET_TYPE", ""))


def build_signed_order_request(*, market_type: str, frozen_order_request: dict[str, Any], api_secret: str) -> tuple[str, str]:
    payload = {
        "symbol": str(frozen_order_request["symbol"]).upper(),
        "side": frozen_order_request["side"],
        "type": "MARKET",
        "quantity": str(frozen_order_request["quantity"]),
        "newClientOrderId": frozen_order_request["newClientOrderId"],
        "reduceOnly": "true" if frozen_order_request.get("reduceOnly") else "false",
        "timestamp": utc_millis(timezone.now()),
        "recvWindow": int(getattr(settings, "BINANCE_RECV_WINDOW_MS", 5000)),
    }
    query_without_signature = urllib.parse.urlencode(payload)
    signature = hmac.new(api_secret.encode("utf-8"), query_without_signature.encode("utf-8"), hashlib.sha256).hexdigest()
    body = f"{query_without_signature}&signature={signature}"
    url = f"{public_base_url(market_type).rstrip('/')}{ORDER_SUBMISSION_PATHS[market_type]}"
    return url, body


def trade_headers(api_key: str) -> dict[str, str]:
    return {
        "User-Agent": "the-cypto/binance-order-submission",
        "Content-Type": "application/x-www-form-urlencoded",
        "X-MBX-APIKEY": api_key,
    }


def order_success_result(
    *,
    market_type: str,
    payload: Any,
    response: Any,
    started: datetime,
    call_context: BinanceGatewayCallContext,
) -> BinanceGatewayResult:
    finished = timezone.now()
    return BinanceGatewayResult(
        operation="submit_order",
        market_type=market_type,
        endpoint_family=endpoint_family_for_market(market_type),
        success=True,
        payload=sanitize_mapping(payload if isinstance(payload, dict) else {"payload": payload}),
        response_received=True,
        request_sent=True,
        http_status=response.status,
        request_started_at_utc=started,
        request_finished_at_utc=finished,
        latency_ms=int((finished - started).total_seconds() * 1000),
        attempt_count=1,
        trace_id=call_context.trace_id,
    )


def blocked_order_result(market_type: str, call_context: BinanceGatewayCallContext, reason: str) -> BinanceGatewayResult:
    return BinanceGatewayResult(
        operation="submit_order",
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


def classify_order_http_error(http_status: int) -> str:
    if http_status == 429:
        return ERROR_RATE_LIMITED
    if http_status in {500, 502, 503, 504}:
        return ERROR_SERVER_ERROR
    return ERROR_BINANCE_REJECTED


def _single_attempt_failure(
    market_type: str,
    call_context: BinanceGatewayCallContext,
    started: datetime,
    category: str,
    *,
    request_sent: bool,
    message: str | None = None,
) -> BinanceGatewayResult:
    return failure_result(
        operation="submit_order",
        market_type=market_type,
        call_context=call_context,
        started=started,
        attempt_count=1,
        request_sent=request_sent,
        response_received=False,
        http_status=None,
        error_category=category,
        sanitized_error_message=message or category,
    )


def get_order_submission_gateway() -> BinanceOrderSubmissionGateway:
    return HttpBinanceOrderSubmissionGateway()
