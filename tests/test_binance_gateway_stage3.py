from __future__ import annotations

import json
from datetime import UTC, datetime
from urllib.parse import parse_qs, urlparse

import pytest

from apps.binance_gateway.account_read import HttpBinanceAccountReadGateway
from apps.binance_gateway.public_market import FakeBinancePublicMarketGateway, HttpBinancePublicMarketGateway
from apps.binance_gateway.types import (
    ERROR_ACCOUNT_READ_DISABLED,
    ERROR_CREDENTIAL_MISSING,
    ERROR_DOMAIN_MISMATCH,
    ERROR_GATEWAY_DISABLED,
    ERROR_PUBLIC_DATA_DISABLED,
    MARKET_TYPE_COIN_M,
    MARKET_TYPE_USDS_M,
    BinanceGatewayCallContext,
)


class FakeHttpResponse:
    def __init__(self, payload: object, *, status: int = 200) -> None:
        self.payload = payload
        self.status = status

    def __enter__(self) -> "FakeHttpResponse":
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


def gateway_context(operation: str, *, market_type: str = MARKET_TYPE_USDS_M, symbol: str = "BTCUSDT") -> BinanceGatewayCallContext:
    return BinanceGatewayCallContext(
        trace_id="trace_binance_gateway",
        trigger_source="test",
        operation=operation,
        market_type=market_type,
        symbol=symbol,
        account_domain="default",
    )


def enable_public_gateway(settings) -> None:
    settings.BINANCE_GATEWAY_ENABLED = True
    settings.BINANCE_PUBLIC_DATA_ENABLED = True
    settings.ALLOW_REAL_EXTERNAL_SERVICES = True
    settings.ACTIVE_MARKET_TYPE = "USDS-M"
    settings.BINANCE_USDS_M_BASE_URL = "https://fapi.test"
    settings.BINANCE_COIN_M_BASE_URL = "https://dapi.test"
    settings.BINANCE_SAFE_READ_MAX_ATTEMPTS = 1


def enable_account_read_gateway(settings) -> None:
    settings.BINANCE_GATEWAY_ENABLED = True
    settings.BINANCE_ACCOUNT_READ_ENABLED = True
    settings.ALLOW_REAL_EXTERNAL_SERVICES = True
    settings.ACTIVE_ACCOUNT_DOMAIN = "default"
    settings.ACTIVE_MARKET_TYPE = "USDS-M"
    settings.BINANCE_USDS_M_BASE_URL = "https://fapi.test"
    settings.BINANCE_COIN_M_BASE_URL = "https://dapi.test"
    settings.BINANCE_USDS_M_READ_API_KEY = "read-key-usds"
    settings.BINANCE_USDS_M_READ_API_SECRET = "read-secret-usds"
    settings.BINANCE_COIN_M_READ_API_KEY = "read-key-coin"
    settings.BINANCE_COIN_M_READ_API_SECRET = "read-secret-coin"
    settings.BINANCE_USDS_M_TRADE_API_KEY = "trade-key-usds"
    settings.BINANCE_USDS_M_TRADE_API_SECRET = "trade-secret-usds"
    settings.BINANCE_SAFE_READ_MAX_ATTEMPTS = 1
    settings.BINANCE_RECV_WINDOW_MS = 5000


def request_headers(request) -> dict[str, str]:
    return {key.lower(): value for key, value in request.header_items()}


def test_public_gateway_blocks_when_gateway_disabled(settings) -> None:
    settings.BINANCE_GATEWAY_ENABLED = False
    result = HttpBinancePublicMarketGateway().get_mark_price(
        market_type=MARKET_TYPE_USDS_M,
        symbol="BTCUSDT",
        call_context=gateway_context("get_mark_price"),
    )
    assert result.success is False
    assert result.request_sent is False
    assert result.error_category == ERROR_GATEWAY_DISABLED


def test_public_gateway_blocks_when_public_data_disabled(settings) -> None:
    settings.BINANCE_GATEWAY_ENABLED = True
    settings.BINANCE_PUBLIC_DATA_ENABLED = False
    settings.ALLOW_REAL_EXTERNAL_SERVICES = True
    result = HttpBinancePublicMarketGateway().get_exchange_info(
        market_type=MARKET_TYPE_USDS_M,
        call_context=gateway_context("get_exchange_info"),
    )
    assert result.success is False
    assert result.request_sent is False
    assert result.error_category == ERROR_PUBLIC_DATA_DISABLED


def test_public_mark_price_requests_each_business_call_and_uses_no_secret(settings, monkeypatch) -> None:
    enable_public_gateway(settings)
    settings.BINANCE_USDS_M_READ_API_KEY = "must-not-be-used"
    seen_urls: list[str] = []
    seen_headers: list[dict[str, str]] = []

    def fake_urlopen(request, timeout):
        seen_urls.append(request.full_url)
        seen_headers.append(request_headers(request))
        return FakeHttpResponse({"symbol": "BTCUSDT", "markPrice": str(100 + len(seen_urls))})

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    gateway = HttpBinancePublicMarketGateway()
    first = gateway.get_mark_price(
        market_type=MARKET_TYPE_USDS_M,
        symbol="BTCUSDT",
        call_context=gateway_context("get_mark_price"),
    )
    second = gateway.get_mark_price(
        market_type=MARKET_TYPE_USDS_M,
        symbol="BTCUSDT",
        call_context=gateway_context("get_mark_price"),
    )

    assert first.payload["markPrice"] == "101"
    assert second.payload["markPrice"] == "102"
    assert len(seen_urls) == 2
    assert "/fapi/v1/premiumIndex?symbol=BTCUSDT" in seen_urls[0]
    assert all("x-mbx-apikey" not in headers for headers in seen_headers)


def test_public_gateway_normalizes_external_market_type_alias(settings, monkeypatch) -> None:
    enable_public_gateway(settings)
    seen_urls: list[str] = []

    def fake_urlopen(request, timeout):
        seen_urls.append(request.full_url)
        return FakeHttpResponse({"symbol": "BTCUSDT", "markPrice": "100"})

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    result = HttpBinancePublicMarketGateway().get_mark_price(
        market_type="USDS-M",
        symbol=" btcusdt ",
        call_context=gateway_context("get_mark_price", market_type="USDS-M"),
    )

    assert result.success is True
    assert result.market_type == MARKET_TYPE_USDS_M
    assert seen_urls == ["https://fapi.test/fapi/v1/premiumIndex?symbol=BTCUSDT"]


def test_public_gateway_uses_coin_m_endpoint_for_coin_m_market(settings, monkeypatch) -> None:
    enable_public_gateway(settings)
    settings.ACTIVE_MARKET_TYPE = "COIN-M"
    seen_urls: list[str] = []

    def fake_urlopen(request, timeout):
        seen_urls.append(request.full_url)
        return FakeHttpResponse({"symbols": []})

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    result = HttpBinancePublicMarketGateway().get_exchange_info(
        market_type=MARKET_TYPE_COIN_M,
        call_context=gateway_context("get_exchange_info", market_type=MARKET_TYPE_COIN_M),
    )

    assert result.success is True
    assert seen_urls == ["https://dapi.test/dapi/v1/exchangeInfo"]


def test_fake_public_gateway_records_mark_price_call_without_cache() -> None:
    gateway = FakeBinancePublicMarketGateway(mark_price_payload={"symbol": "BTCUSDT", "markPrice": "100"})
    gateway.get_mark_price(
        market_type=MARKET_TYPE_USDS_M,
        symbol="BTCUSDT",
        call_context=gateway_context("get_mark_price"),
    )
    gateway.get_mark_price(
        market_type=MARKET_TYPE_USDS_M,
        symbol="BTCUSDT",
        call_context=gateway_context("get_mark_price"),
    )
    assert [call["operation"] for call in gateway.calls] == ["get_mark_price", "get_mark_price"]


def test_account_read_gateway_blocks_when_capability_disabled(settings) -> None:
    settings.BINANCE_GATEWAY_ENABLED = True
    settings.BINANCE_ACCOUNT_READ_ENABLED = False
    result = HttpBinanceAccountReadGateway().get_account(
        market_type=MARKET_TYPE_USDS_M,
        account_domain="default",
        call_context=gateway_context("get_account"),
    )
    assert result.success is False
    assert result.request_sent is False
    assert result.error_category == ERROR_ACCOUNT_READ_DISABLED


def test_account_read_gateway_blocks_when_credential_missing(settings, monkeypatch) -> None:
    enable_account_read_gateway(settings)
    settings.BINANCE_USDS_M_READ_API_KEY = ""
    monkeypatch.setattr("urllib.request.urlopen", pytest.fail)
    result = HttpBinanceAccountReadGateway().get_balances(
        market_type=MARKET_TYPE_USDS_M,
        account_domain="default",
        call_context=gateway_context("get_balances"),
    )
    assert result.success is False
    assert result.request_sent is False
    assert result.error_category == ERROR_CREDENTIAL_MISSING


def test_account_read_gateway_blocks_account_domain_mismatch(settings, monkeypatch) -> None:
    enable_account_read_gateway(settings)
    monkeypatch.setattr("urllib.request.urlopen", pytest.fail)
    result = HttpBinanceAccountReadGateway().get_positions(
        market_type=MARKET_TYPE_USDS_M,
        account_domain="other",
        call_context=gateway_context("get_positions"),
    )
    assert result.success is False
    assert result.request_sent is False
    assert result.error_category == ERROR_DOMAIN_MISMATCH


def test_account_read_gateway_uses_read_key_and_signed_query(settings, monkeypatch) -> None:
    enable_account_read_gateway(settings)
    seen_urls: list[str] = []
    seen_headers: list[dict[str, str]] = []

    def fake_urlopen(request, timeout):
        seen_urls.append(request.full_url)
        seen_headers.append(request_headers(request))
        return FakeHttpResponse({"assets": [], "positions": []})

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    result = HttpBinanceAccountReadGateway().get_account(
        market_type=MARKET_TYPE_USDS_M,
        account_domain="default",
        call_context=gateway_context("get_account"),
    )

    parsed = urlparse(seen_urls[0])
    query = parse_qs(parsed.query)
    assert result.success is True
    assert parsed.path == "/fapi/v2/account"
    assert "timestamp" in query
    assert query["recvWindow"] == ["5000"]
    assert "signature" in query
    assert seen_headers[0]["x-mbx-apikey"] == "read-key-usds"
    assert seen_headers[0]["x-mbx-apikey"] != "trade-key-usds"


def test_account_read_gateway_normalizes_external_market_type_alias(settings, monkeypatch) -> None:
    enable_account_read_gateway(settings)
    seen_urls: list[str] = []

    def fake_urlopen(request, timeout):
        seen_urls.append(request.full_url)
        return FakeHttpResponse([])

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    result = HttpBinanceAccountReadGateway().get_positions(
        market_type="USDS-M",
        account_domain="default",
        symbol=" btcusdt ",
        call_context=gateway_context("get_positions", market_type="USDS-M", symbol=" btcusdt "),
    )

    parsed = urlparse(seen_urls[0])
    query = parse_qs(parsed.query)
    assert result.success is True
    assert result.market_type == MARKET_TYPE_USDS_M
    assert parsed.path == "/fapi/v2/positionRisk"
    assert query["symbol"] == ["BTCUSDT"]


def test_account_read_gateway_uses_coin_m_read_credentials(settings, monkeypatch) -> None:
    enable_account_read_gateway(settings)
    settings.ACTIVE_MARKET_TYPE = "COIN-M"
    seen_urls: list[str] = []
    seen_headers: list[dict[str, str]] = []

    def fake_urlopen(request, timeout):
        seen_urls.append(request.full_url)
        seen_headers.append(request_headers(request))
        return FakeHttpResponse([])

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    result = HttpBinanceAccountReadGateway().get_positions(
        market_type=MARKET_TYPE_COIN_M,
        account_domain="default",
        symbol="BTCUSD_PERP",
        call_context=gateway_context("get_positions", market_type=MARKET_TYPE_COIN_M, symbol="BTCUSD_PERP"),
    )

    parsed = urlparse(seen_urls[0])
    query = parse_qs(parsed.query)
    assert result.success is True
    assert parsed.path == "/dapi/v1/positionRisk"
    assert query["symbol"] == ["BTCUSD_PERP"]
    assert seen_headers[0]["x-mbx-apikey"] == "read-key-coin"


def test_gateway_context_accepts_utc_request_time() -> None:
    context = BinanceGatewayCallContext(
        trace_id="trace",
        trigger_source="test",
        operation="get_account",
        market_type=MARKET_TYPE_USDS_M,
        request_time_utc=datetime(2026, 1, 1, tzinfo=UTC),
    )
    assert context.request_time_utc.tzinfo is UTC
