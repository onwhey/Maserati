"""BinanceGateway 模块：既有订单撤单受限接口；不写数据库；不访问 Redis；可访问外部 Binance；不发送 Hermes；不调用大模型；涉及既有真实订单撤单通信；只允许撤销既有 LIMIT 订单，不允许提交新订单。"""

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
from .order_submission import active_market_type, trade_credentials_for_market, trade_headers
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
    ERROR_ORDER_CANCEL_DISABLED,
    ERROR_ORDER_NOT_FOUND,
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

ORDER_CANCEL_PATHS = {
    MARKET_TYPE_USDS_M: "/fapi/v1/order",
    MARKET_TYPE_COIN_M: "/dapi/v1/order",
}

BINANCE_ORDER_NOT_FOUND_CODES = {"-2011", "-2013"}
FORBIDDEN_CANCEL_FIELDS = {
    "quantity",
    "price",
    "side",
    "newClientOrderId",
    "timeInForce",
    "leverage",
    "marginType",
    "positionMode",
    "stopPrice",
    "type",
    "reduceOnly",
    "signature",
}


class BinanceOrderCancelGateway(Protocol):
    def cancel_order(
        self,
        *,
        market_type: str,
        frozen_cancel_request: dict[str, Any],
        call_context: BinanceGatewayCallContext,
    ) -> BinanceGatewayResult: ...


class FakeBinanceOrderCancelGateway:
    """测试替身：记录撤单调用，不访问真实 Binance。"""

    def __init__(self, *, result: BinanceGatewayResult | None = None, payload: dict[str, Any] | None = None) -> None:
        self.result = result
        self.payload = payload
        self.calls: list[dict[str, Any]] = []

    def cancel_order(
        self,
        *,
        market_type: str,
        frozen_cancel_request: dict[str, Any],
        call_context: BinanceGatewayCallContext,
    ) -> BinanceGatewayResult:
        self.calls.append(
            {
                "operation": "cancel_order",
                "market_type": market_type,
                "frozen_cancel_request": dict(frozen_cancel_request),
                "call_context": call_context,
            }
        )
        if self.result is not None:
            return self.result
        payload = dict(self.payload) if self.payload is not None else {"orderId": frozen_cancel_request.get("orderId") or 123456, "status": "CANCELED"}
        payload.setdefault("symbol", frozen_cancel_request.get("symbol", ""))
        payload.setdefault("clientOrderId", frozen_cancel_request.get("origClientOrderId", ""))
        return BinanceGatewayResult(
            operation="cancel_order",
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


class HttpBinanceOrderCancelGateway:
    """真实撤单 Gateway：只撤销冻结身份指向的既有订单，且不做业务重试。"""

    def cancel_order(
        self,
        *,
        market_type: str,
        frozen_cancel_request: dict[str, Any],
        call_context: BinanceGatewayCallContext,
    ) -> BinanceGatewayResult:
        normalized_market_type = normalize_active_market_type(market_type)
        blocked = validate_order_cancel_request(
            market_type=normalized_market_type,
            frozen_cancel_request=frozen_cancel_request,
            call_context=call_context,
        )
        if blocked is not None:
            return blocked

        api_key, api_secret = trade_credentials_for_market(normalized_market_type)
        if not api_key or not api_secret:
            return _blocked(normalized_market_type, call_context, ERROR_CREDENTIAL_MISSING)

        started = timezone.now()
        try:
            url = build_signed_order_cancel_url(
                market_type=normalized_market_type,
                frozen_cancel_request=frozen_cancel_request,
                api_secret=api_secret,
            )
            request = urllib.request.Request(url, method="DELETE", headers=trade_headers(api_key))
            with urllib.request.urlopen(request, timeout=float(getattr(settings, "BINANCE_READ_TIMEOUT_SECONDS", 10))) as response:
                payload = json.loads(response.read().decode("utf-8"))
                return _success(
                    market_type=normalized_market_type,
                    payload=payload,
                    response=response,
                    started=started,
                    call_context=call_context,
                )
        except urllib.error.HTTPError as exc:
            details = _read_error_details(exc)
            return _failure(
                market_type=normalized_market_type,
                call_context=call_context,
                started=started,
                request_sent=True,
                response_received=True,
                http_status=exc.code,
                error_category=_classify_http_error(exc.code, details["code"]),
                sanitized_error_message=details["message"],
                binance_error_code=details["code"],
            )
        except TimeoutError:
            return _failure_for_exception(normalized_market_type, call_context, started, ERROR_TIMEOUT)
        except urllib.error.URLError as exc:
            return _failure_for_exception(normalized_market_type, call_context, started, ERROR_NETWORK_ERROR, sanitize_error_text(str(exc.reason)))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return _failure_for_exception(normalized_market_type, call_context, started, ERROR_RESPONSE_SCHEMA_ERROR)
        except Exception as exc:
            LOGGER.warning("Binance order cancel gateway failed during send: %s", sanitize_mapping({"error": type(exc).__name__}))
            return _failure_for_exception(normalized_market_type, call_context, started, ERROR_GATEWAY_FAILED, type(exc).__name__)


def validate_order_cancel_request(
    *,
    market_type: str,
    frozen_cancel_request: dict[str, Any],
    call_context: BinanceGatewayCallContext,
) -> BinanceGatewayResult | None:
    if not getattr(settings, "BINANCE_GATEWAY_ENABLED", False):
        return _blocked(market_type, call_context, ERROR_GATEWAY_DISABLED)
    if not getattr(settings, "BINANCE_ORDER_CANCEL_ENABLED", False):
        return _blocked(market_type, call_context, ERROR_ORDER_CANCEL_DISABLED)
    if not getattr(settings, "ALLOW_REAL_EXTERNAL_SERVICES", False):
        return _blocked(market_type, call_context, ERROR_REAL_EXTERNAL_SERVICES_DISABLED)
    if not is_supported_market_type(market_type):
        return _blocked(market_type, call_context, ERROR_INVALID_MARKET_TYPE)
    if market_type != active_market_type():
        return _blocked(market_type, call_context, ERROR_DOMAIN_MISMATCH)
    if call_context.account_domain and call_context.account_domain != getattr(settings, "ACTIVE_ACCOUNT_DOMAIN", ""):
        return _blocked(market_type, call_context, ERROR_DOMAIN_MISMATCH)
    if not public_base_url(market_type):
        return _blocked(market_type, call_context, ERROR_CONFIGURATION_ERROR)
    if order_cancel_request_error(frozen_cancel_request):
        return _blocked(market_type, call_context, ERROR_REQUEST_VALIDATION_FAILED)
    return None


def order_cancel_request_error(frozen_cancel_request: dict[str, Any]) -> bool:
    if not isinstance(frozen_cancel_request, dict):
        return True
    if any(key in frozen_cancel_request for key in FORBIDDEN_CANCEL_FIELDS):
        return True
    symbol = str(frozen_cancel_request.get("symbol") or "").strip()
    client_id = str(frozen_cancel_request.get("origClientOrderId") or "").strip()
    exchange_id = str(frozen_cancel_request.get("orderId") or "").strip()
    return not symbol or (not client_id and not exchange_id)


def build_signed_order_cancel_url(*, market_type: str, frozen_cancel_request: dict[str, Any], api_secret: str) -> str:
    payload: dict[str, Any] = {
        "symbol": str(frozen_cancel_request["symbol"]).upper(),
        "timestamp": utc_millis(timezone.now()),
        "recvWindow": int(getattr(settings, "BINANCE_RECV_WINDOW_MS", 5000)),
    }
    client_id = str(frozen_cancel_request.get("origClientOrderId") or "").strip()
    exchange_id = str(frozen_cancel_request.get("orderId") or "").strip()
    if client_id:
        payload["origClientOrderId"] = client_id
    elif exchange_id:
        payload["orderId"] = exchange_id
    query_without_signature = urllib.parse.urlencode(payload)
    signature = hmac.new(api_secret.encode("utf-8"), query_without_signature.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{public_base_url(market_type).rstrip('/')}{ORDER_CANCEL_PATHS[market_type]}?{query_without_signature}&signature={signature}"


def _read_error_details(exc: urllib.error.HTTPError) -> dict[str, str]:
    try:
        body = exc.read().decode("utf-8")
    except (OSError, UnicodeDecodeError):
        return {"code": "", "message": ERROR_GATEWAY_FAILED}
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return {"code": "", "message": sanitize_error_text(body)}
    return {
        "code": str(payload.get("code") or ""),
        "message": sanitize_error_text(str(payload.get("msg") or body)),
    }


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
    response: Any,
    started: datetime,
    call_context: BinanceGatewayCallContext,
) -> BinanceGatewayResult:
    finished = timezone.now()
    return BinanceGatewayResult(
        operation="cancel_order",
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


def _failure_for_exception(
    market_type: str,
    call_context: BinanceGatewayCallContext,
    started: datetime,
    category: str,
    message: str | None = None,
) -> BinanceGatewayResult:
    return _failure(
        market_type=market_type,
        call_context=call_context,
        started=started,
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
    request_sent: bool,
    response_received: bool,
    http_status: int | None,
    error_category: str,
    sanitized_error_message: str,
    binance_error_code: str = "",
) -> BinanceGatewayResult:
    result = failure_result(
        operation="cancel_order",
        market_type=market_type,
        call_context=call_context,
        started=started,
        attempt_count=1,
        request_sent=request_sent,
        response_received=response_received,
        http_status=http_status,
        error_category=error_category,
        sanitized_error_message=sanitized_error_message,
    )
    return BinanceGatewayResult(**{**result.__dict__, "binance_error_code": binance_error_code})


def _blocked(market_type: str, call_context: BinanceGatewayCallContext, reason: str) -> BinanceGatewayResult:
    return BinanceGatewayResult(
        operation="cancel_order",
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


def get_order_cancel_gateway() -> BinanceOrderCancelGateway:
    return HttpBinanceOrderCancelGateway()
