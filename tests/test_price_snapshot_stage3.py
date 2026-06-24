from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.alerts.models import AlertEvent
from apps.binance_gateway.public_market import FakeBinancePublicMarketGateway
from apps.binance_gateway.types import MARKET_TYPE_USDS_M
from apps.foundation.results import ResultStatus
from apps.price_snapshot.models import PriceSnapshot, PriceType
from apps.price_snapshot.selectors import load_price_snapshot_for_trading
from apps.price_snapshot.services.snapshot import cache_summary_from_snapshot, create_price_snapshot


pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def clear_cache() -> None:
    cache.clear()


def enable_price_snapshot(settings) -> None:
    settings.ACTIVE_MARKET_TYPE = "USDS-M"
    settings.ACTIVE_ACCOUNT_DOMAIN = "default"
    settings.ACTIVE_SYMBOL = "BTCUSDT"
    settings.PRICE_SNAPSHOT_ENABLED = True
    settings.PRICE_SNAPSHOT_TTL_SECONDS = 600
    settings.PRICE_SNAPSHOT_REDIS_CACHE_ENABLED = True
    settings.PRICE_SNAPSHOT_REDIS_KEY_PREFIX = "price_snapshot"
    settings.PRICE_SNAPSHOT_MAX_DECIMAL_PLACES = 18
    settings.BINANCE_MAX_CLOCK_SKEW_MS = 1000


def now_millis(offset_seconds: int = 0) -> int:
    value = timezone.now() + timedelta(seconds=offset_seconds)
    return int(value.timestamp() * 1000)


def mark_price_payload(*, symbol: str = "BTCUSDT", mark_price: str = "50000.1234", offset_seconds: int = 0) -> dict[str, object]:
    return {
        "symbol": symbol,
        "markPrice": mark_price,
        "time": now_millis(offset_seconds),
        "priceUnit": "USDT",
    }


def fake_gateway(payload: dict[str, object] | None = None, *, fail_operation: str = "") -> FakeBinancePublicMarketGateway:
    return FakeBinancePublicMarketGateway(mark_price_payload=payload or mark_price_payload(), fail_operation=fail_operation)


def create_snapshot(settings, *, key: str = "price:2026-01-01T00:00:00Z", gateway: FakeBinancePublicMarketGateway | None = None):
    enable_price_snapshot(settings)
    return create_price_snapshot(
        business_request_key=key,
        market_type=MARKET_TYPE_USDS_M,
        account_domain="default",
        symbol="BTCUSDT",
        trace_id=f"trace-{key}",
        trigger_source="test",
        gateway=gateway or fake_gateway(),
    )


def load_snapshot(snapshot_id: int):
    return load_price_snapshot_for_trading(
        price_snapshot_id=snapshot_id,
        reference_time_utc=timezone.now(),
        expected_market_type=MARKET_TYPE_USDS_M,
        expected_account_domain="default",
        expected_symbol="BTCUSDT",
        trace_id="trace-load",
        trigger_source="test",
    )


def test_create_price_snapshot_requests_mark_price_writes_mysql_and_cache(settings) -> None:
    gateway = fake_gateway()

    result = create_snapshot(settings, gateway=gateway)
    snapshot = PriceSnapshot.objects.get(id=result.data["price_snapshot_id"])
    loaded = load_snapshot(snapshot.id)

    assert result.status == ResultStatus.SUCCEEDED
    assert snapshot.price_type == PriceType.MARK_PRICE
    assert snapshot.mark_price == Decimal("50000.1234")
    assert snapshot.price_snapshot_hash
    assert snapshot.expires_at_utc == snapshot.as_of_utc + timedelta(seconds=600)
    assert [call["operation"] for call in gateway.calls] == ["get_mark_price"]
    assert loaded.status == ResultStatus.SUCCEEDED
    assert loaded.reason_code == "price_snapshot_loaded_from_cache"
    assert loaded.data["mark_price"] == Decimal("50000.1234")


def test_same_business_request_key_returns_existing_snapshot_without_second_gateway_call(settings) -> None:
    gateway = fake_gateway()

    first = create_snapshot(settings, key="price:same", gateway=gateway)
    second = create_snapshot(settings, key="price:same", gateway=gateway)

    assert first.data["price_snapshot_id"] == second.data["price_snapshot_id"]
    assert second.reason_code == "price_snapshot_already_exists"
    assert PriceSnapshot.objects.count() == 1
    assert len(gateway.calls) == 1


def test_different_business_request_keys_create_different_snapshots(settings) -> None:
    gateway = fake_gateway()

    first = create_snapshot(settings, key="price:one", gateway=gateway)
    second = create_snapshot(settings, key="price:two", gateway=gateway)

    assert first.data["price_snapshot_id"] != second.data["price_snapshot_id"]
    assert PriceSnapshot.objects.count() == 2
    assert len(gateway.calls) == 2


def test_disabled_price_snapshot_blocks_without_gateway_call(settings) -> None:
    enable_price_snapshot(settings)
    settings.PRICE_SNAPSHOT_ENABLED = False
    gateway = fake_gateway()

    result = create_price_snapshot(
        business_request_key="price:disabled",
        market_type=MARKET_TYPE_USDS_M,
        account_domain="default",
        symbol="BTCUSDT",
        trace_id="trace-disabled",
        trigger_source="test",
        gateway=gateway,
    )

    assert result.status == ResultStatus.BLOCKED
    assert result.reason_code == "price_snapshot_disabled"
    assert gateway.calls == []
    assert PriceSnapshot.objects.count() == 0
    assert AlertEvent.objects.filter(source_module="PriceSnapshot", event_type="price_snapshot_blocked").exists()


@pytest.mark.parametrize(
    ("payload", "reason_code"),
    [
        ({"symbol": "BTCUSDT", "time": now_millis(), "priceUnit": "USDT"}, "mark_price_missing"),
        (mark_price_payload(mark_price="0"), "mark_price_non_positive"),
        (mark_price_payload(mark_price="-1"), "mark_price_non_positive"),
        ({"symbol": "BTCUSDT", "markPrice": "50000", "priceUnit": "USDT"}, "mark_price_time_missing"),
    ],
)
def test_invalid_mark_price_payload_does_not_create_snapshot(settings, payload: dict[str, object], reason_code: str) -> None:
    result = create_snapshot(settings, key=f"price:{reason_code}", gateway=fake_gateway(payload))

    assert result.status == ResultStatus.FAILED
    assert result.reason_code == reason_code
    assert PriceSnapshot.objects.count() == 0
    assert AlertEvent.objects.filter(source_module="PriceSnapshot", event_type="price_snapshot_failed", reason_code=reason_code).exists()


def test_stale_mark_price_at_creation_is_rejected(settings) -> None:
    result = create_snapshot(settings, key="price:stale-create", gateway=fake_gateway(mark_price_payload(offset_seconds=-601)))

    assert result.status == ResultStatus.FAILED
    assert result.reason_code == "mark_price_stale_at_creation"
    assert PriceSnapshot.objects.count() == 0


def test_request_market_identity_mismatch_blocks_before_gateway(settings) -> None:
    enable_price_snapshot(settings)
    gateway = fake_gateway()

    result = create_price_snapshot(
        business_request_key="price:wrong-symbol",
        market_type=MARKET_TYPE_USDS_M,
        account_domain="default",
        symbol="ETHUSDT",
        trace_id="trace-wrong-symbol",
        trigger_source="test",
        gateway=gateway,
    )

    assert result.status == ResultStatus.BLOCKED
    assert result.reason_code == "market_identity_mismatch"
    assert gateway.calls == []
    assert PriceSnapshot.objects.count() == 0


def test_gateway_payload_symbol_mismatch_fails_without_snapshot(settings) -> None:
    result = create_snapshot(settings, key="price:payload-symbol", gateway=fake_gateway(mark_price_payload(symbol="ETHUSDT")))

    assert result.status == ResultStatus.FAILED
    assert result.reason_code == "market_identity_mismatch"
    assert PriceSnapshot.objects.count() == 0


def test_gateway_failure_writes_alert_without_snapshot(settings) -> None:
    result = create_snapshot(settings, key="price:gateway-failed", gateway=fake_gateway(fail_operation="get_mark_price"))

    assert result.status == ResultStatus.FAILED
    assert result.reason_code == "mark_price_request_failed"
    assert PriceSnapshot.objects.count() == 0
    assert AlertEvent.objects.filter(source_module="PriceSnapshot", reason_code="mark_price_request_failed").exists()


def test_expired_price_snapshot_blocks_and_does_not_create_second_snapshot(settings) -> None:
    result = create_snapshot(settings, key="price:expire")
    snapshot = PriceSnapshot.objects.get(id=result.data["price_snapshot_id"])

    loaded = load_price_snapshot_for_trading(
        price_snapshot_id=snapshot.id,
        reference_time_utc=snapshot.expires_at_utc + timedelta(seconds=1),
        expected_market_type=MARKET_TYPE_USDS_M,
        expected_account_domain="default",
        expected_symbol="BTCUSDT",
        trace_id="trace-expired",
        trigger_source="test",
    )

    assert loaded.status == ResultStatus.BLOCKED
    assert loaded.reason_code == "price_snapshot_stale"
    assert PriceSnapshot.objects.count() == 1


def test_cache_hash_mismatch_falls_back_to_same_mysql_snapshot(settings) -> None:
    result = create_snapshot(settings, key="price:bad-cache")
    snapshot = PriceSnapshot.objects.get(id=result.data["price_snapshot_id"])
    bad_cache = cache_summary_from_snapshot(snapshot)
    bad_cache["mark_price"] = "1"
    cache.set(f"price_snapshot:{snapshot.id}", bad_cache, timeout=600)

    loaded = load_snapshot(snapshot.id)

    assert loaded.status == ResultStatus.SUCCEEDED
    assert loaded.reason_code == "price_snapshot_loaded"
    assert loaded.data["source"] == "mysql"
    assert loaded.data["mark_price"] == Decimal("50000.123400000000000000")
    assert AlertEvent.objects.filter(source_module="PriceSnapshot", reason_code="price_snapshot_hash_mismatch").exists()


def test_redis_write_failure_keeps_mysql_fact_valid(settings, monkeypatch) -> None:
    def fail_set(*args, **kwargs):
        raise RuntimeError("redis-down")

    monkeypatch.setattr("apps.price_snapshot.services.snapshot.cache.set", fail_set)

    result = create_snapshot(settings, key="price:redis-failed")

    assert result.status == ResultStatus.SUCCEEDED
    assert result.data["cache_write_status"] == "failed"
    assert PriceSnapshot.objects.count() == 1
    assert AlertEvent.objects.filter(source_module="PriceSnapshot", reason_code="redis_write_failed").exists()


def test_price_snapshot_core_fields_are_immutable_after_creation(settings) -> None:
    result = create_snapshot(settings, key="price:immutable")
    snapshot = PriceSnapshot.objects.get(id=result.data["price_snapshot_id"])
    snapshot.mark_price = Decimal("1")

    with pytest.raises(ValidationError):
        snapshot.save()
