from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from apps.binance_gateway.public_market import FakeBinancePublicMarketGateway, HttpBinancePublicMarketGateway
from apps.binance_gateway.types import BinanceGatewayCallContext
from apps.alerts.models import AlertEvent
from apps.foundation.idempotency import build_idempotency_key
from apps.foundation.results import ResultStatus
from apps.market_data.domain import DATA_SOURCE_BINANCE_REST
from apps.market_data.models import (
    BackfillRequest,
    BackfillRun,
    DataCollectionRun,
    DataConflict,
    DataQualityResult,
    Kline,
    MarketSnapshot,
)
from apps.market_data.services.backfill import run_data_backfill
from apps.market_data.services.collection import collect_klines
from apps.market_data.services.quality import check_data_quality
from apps.market_data.services.snapshot import create_market_snapshot


def dt(year: int, month: int, day: int, hour: int = 0) -> datetime:
    return datetime(year, month, day, hour, tzinfo=UTC)


def raw_kline(open_time: datetime, timeframe: str = "4h", close: str = "105") -> list[object]:
    delta = timedelta(hours=4) if timeframe == "4h" else timedelta(days=1)
    close_time = open_time + delta
    return [
        int(open_time.timestamp() * 1000),
        "100",
        "110",
        "90",
        close,
        "1.5",
        int(close_time.timestamp() * 1000) - 1,
        "150",
        10,
        "0",
        "0",
        "0",
    ]


def create_kline(open_time: datetime, timeframe: str = "4h") -> Kline:
    delta = timedelta(hours=4) if timeframe == "4h" else timedelta(days=1)
    return Kline.objects.create(
        exchange="binance",
        market_type="usds_m_futures",
        symbol="BTCUSDT",
        timeframe=timeframe,
        open_time_utc=open_time,
        close_time_utc=open_time + delta,
        open_price="100",
        high_price="110",
        low_price="90",
        close_price="105",
        volume="1.5",
        quote_volume="150",
        trade_count=10,
        data_source=DATA_SOURCE_BINANCE_REST,
    )


def quality_pass(timeframe: str, start_open: datetime, end_open: datetime, count: int) -> DataQualityResult:
    return DataQualityResult.objects.create(
        business_request_key=build_idempotency_key("quality", timeframe, start_open.isoformat(), end_open.isoformat()),
        trace_id="trace_quality",
        trigger_source="test",
        exchange="binance",
        market_type="usds_m_futures",
        symbol="BTCUSDT",
        timeframe=timeframe,
        status="PASS",
        reason_code="quality_pass",
        check_start_open_time_utc=start_open,
        check_end_open_time_utc=end_open,
        expected_count=count,
        actual_count=count,
        issue_count=0,
        allows_downstream=True,
        coverage_start_open_time_utc=start_open,
        coverage_end_open_time_utc=end_open,
    )


def gateway_context(operation: str) -> BinanceGatewayCallContext:
    return BinanceGatewayCallContext(
        trace_id="trace_gateway",
        trigger_source="test",
        operation=operation,
        market_type="usds_m_futures",
        symbol="BTCUSDT",
    )


def test_http_gateway_is_fail_closed_when_external_services_disabled(settings) -> None:
    settings.BINANCE_GATEWAY_ENABLED = False
    result = HttpBinancePublicMarketGateway().get_server_time(
        market_type="usds_m_futures",
        call_context=gateway_context("get_server_time"),
    )
    assert result.success is False
    assert result.request_sent is False
    assert result.sanitized_error_message == "gateway_disabled"


def test_fake_gateway_records_kline_call_without_timezone() -> None:
    gateway = FakeBinancePublicMarketGateway(klines=[raw_kline(dt(2026, 1, 1, 4))])
    result = gateway.get_klines(
        market_type="usds_m_futures",
        symbol="BTCUSDT",
        interval="4h",
        start_time_utc=dt(2026, 1, 1, 4),
        end_time_utc=dt(2026, 1, 1, 8),
        limit=10,
        call_context=gateway_context("get_klines"),
    )
    assert result.success is True
    assert gateway.calls[0]["timeZone"] is None


@pytest.mark.django_db
def test_data_collection_writes_only_closed_klines_and_no_downstream_objects() -> None:
    gateway = FakeBinancePublicMarketGateway(
        server_time_utc=dt(2026, 1, 1, 12),
        klines=[raw_kline(dt(2026, 1, 1, 4)), raw_kline(dt(2026, 1, 1, 12))],
    )
    result = collect_klines(
        timeframe="4h",
        collection_mode="historical",
        business_request_key="collect:closed-only",
        trace_id="trace_collect",
        trigger_source="test",
        start_open_time_utc=dt(2026, 1, 1, 4),
        end_open_time_utc=dt(2026, 1, 1, 12),
        gateway=gateway,
    )
    assert result.status == ResultStatus.SUCCEEDED
    assert Kline.objects.count() == 1
    assert DataCollectionRun.objects.get().filtered_unclosed_count == 1
    assert DataQualityResult.objects.count() == 0
    assert MarketSnapshot.objects.count() == 0


@pytest.mark.django_db
def test_data_collection_records_conflict_without_overwrite() -> None:
    server_time = dt(2026, 1, 1, 12)
    collect_klines(
        timeframe="4h",
        collection_mode="historical",
        business_request_key="collect:original",
        trace_id="trace_collect_1",
        trigger_source="test",
        start_open_time_utc=dt(2026, 1, 1, 4),
        end_open_time_utc=dt(2026, 1, 1, 4),
        gateway=FakeBinancePublicMarketGateway(server_time_utc=server_time, klines=[raw_kline(dt(2026, 1, 1, 4), close="105")]),
    )
    result = collect_klines(
        timeframe="4h",
        collection_mode="historical",
        business_request_key="collect:conflict",
        trace_id="trace_collect_2",
        trigger_source="test",
        start_open_time_utc=dt(2026, 1, 1, 4),
        end_open_time_utc=dt(2026, 1, 1, 4),
        gateway=FakeBinancePublicMarketGateway(server_time_utc=server_time, klines=[raw_kline(dt(2026, 1, 1, 4), close="106")]),
    )
    assert result.status == ResultStatus.BLOCKED
    assert DataConflict.objects.count() == 1
    assert Kline.objects.get().close_price == 105


@pytest.mark.django_db
def test_data_collection_gateway_failure_returns_failed_not_blocked() -> None:
    result = collect_klines(
        timeframe="4h",
        collection_mode="historical",
        business_request_key="collect:gateway-failed",
        trace_id="trace_collect_failed",
        trigger_source="test",
        start_open_time_utc=dt(2026, 1, 1, 4),
        end_open_time_utc=dt(2026, 1, 1, 4),
        gateway=FakeBinancePublicMarketGateway(
            server_time_utc=dt(2026, 1, 1, 12),
            klines=[],
            fail_operation="get_klines",
        ),
    )
    assert result.status == ResultStatus.FAILED
    assert DataCollectionRun.objects.get().status == "failed"


@pytest.mark.django_db
def test_data_quality_pass_allows_downstream() -> None:
    create_kline(dt(2026, 1, 1, 4))
    create_kline(dt(2026, 1, 1, 8))
    result = check_data_quality(
        timeframe="4h",
        check_start_open_time_utc=dt(2026, 1, 1, 4),
        check_end_open_time_utc=dt(2026, 1, 1, 8),
        expected_latest_open_time_utc=dt(2026, 1, 1, 8),
        business_request_key="quality:pass",
        trace_id="trace_quality",
        trigger_source="test",
        quality_reference_time_utc=dt(2026, 1, 1, 13),
    )
    assert result.status == ResultStatus.SUCCEEDED
    quality = DataQualityResult.objects.get()
    assert quality.status == "PASS"
    assert quality.allows_downstream is True


@pytest.mark.django_db
def test_data_quality_treats_exact_close_time_as_unclosed() -> None:
    create_kline(dt(2026, 1, 1, 8))
    result = check_data_quality(
        timeframe="4h",
        check_start_open_time_utc=dt(2026, 1, 1, 8),
        check_end_open_time_utc=dt(2026, 1, 1, 8),
        business_request_key="quality:exact-close-unclosed",
        trace_id="trace_quality",
        trigger_source="test",
        quality_reference_time_utc=dt(2026, 1, 1, 12),
    )
    assert result.status == ResultStatus.BLOCKED
    assert DataQualityResult.objects.get().issues.filter(issue_type="UNCLOSED_KLINE").exists()


@pytest.mark.django_db
def test_data_quality_missing_kline_creates_backfill_request() -> None:
    create_kline(dt(2026, 1, 1, 4))
    result = check_data_quality(
        timeframe="4h",
        check_start_open_time_utc=dt(2026, 1, 1, 4),
        check_end_open_time_utc=dt(2026, 1, 1, 8),
        business_request_key="quality:missing",
        trace_id="trace_quality",
        trigger_source="test",
        quality_reference_time_utc=dt(2026, 1, 1, 13),
    )
    assert result.status == ResultStatus.BLOCKED
    assert BackfillRequest.objects.count() == 1
    assert BackfillRequest.objects.get().missing_open_times == [dt(2026, 1, 1, 8).isoformat()]


@pytest.mark.django_db
def test_data_quality_empty_window_creates_backfill_request_for_all_missing_times() -> None:
    result = check_data_quality(
        timeframe="4h",
        check_start_open_time_utc=dt(2026, 1, 1, 4),
        check_end_open_time_utc=dt(2026, 1, 1, 12),
        business_request_key="quality:empty-window",
        trace_id="trace_quality",
        trigger_source="test",
        quality_reference_time_utc=dt(2026, 1, 1, 16),
    )
    assert result.status == ResultStatus.BLOCKED
    assert BackfillRequest.objects.get().missing_open_times == [
        dt(2026, 1, 1, 4).isoformat(),
        dt(2026, 1, 1, 8).isoformat(),
        dt(2026, 1, 1, 12).isoformat(),
    ]


@pytest.mark.django_db
def test_backfill_writes_kline_and_requires_quality_recheck() -> None:
    request = BackfillRequest.objects.create(
        business_key="backfill-request:1",
        source_module="DataQuality",
        exchange="binance",
        market_type="usds_m_futures",
        symbol="BTCUSDT",
        timeframe="4h",
        backfill_mode="gap_backfill",
        requested_start_open_time_utc=dt(2026, 1, 1, 8),
        requested_end_open_time_utc=dt(2026, 1, 1, 8),
        missing_open_times=[dt(2026, 1, 1, 8).isoformat()],
        trace_id="trace_backfill",
        trigger_source="test",
    )
    result = run_data_backfill(
        timeframe="4h",
        backfill_mode="gap_backfill",
        start_open_time_utc=dt(2026, 1, 1, 8),
        end_open_time_utc=dt(2026, 1, 1, 8),
        missing_open_times=[dt(2026, 1, 1, 8)],
        business_request_key="backfill:run:1",
        trace_id="trace_backfill",
        trigger_source="test",
        backfill_request_id=request.id,
        gateway=FakeBinancePublicMarketGateway(server_time_utc=dt(2026, 1, 1, 13), klines=[raw_kline(dt(2026, 1, 1, 8))]),
    )
    assert result.status == ResultStatus.SUCCEEDED
    run = BackfillRun.objects.get()
    assert run.requires_quality_recheck is True
    assert Kline.objects.count() == 1
    assert DataQualityResult.objects.count() == 0
    assert MarketSnapshot.objects.count() == 0


@pytest.mark.django_db
def test_backfill_blocks_before_fetch_when_page_limit_cannot_cover_range(settings) -> None:
    settings.DATA_BACKFILL_KLINE_PAGE_LIMIT = 1
    settings.DATA_BACKFILL_MAX_PAGES_PER_RUN = 1
    gateway = FakeBinancePublicMarketGateway(server_time_utc=dt(2026, 1, 1, 13), klines=[])
    result = run_data_backfill(
        timeframe="4h",
        backfill_mode="gap_backfill",
        start_open_time_utc=dt(2026, 1, 1, 4),
        end_open_time_utc=dt(2026, 1, 1, 8),
        business_request_key="backfill:max-pages",
        trace_id="trace_backfill",
        trigger_source="test",
        gateway=gateway,
    )
    assert result.status == ResultStatus.BLOCKED
    assert result.reason_code == "max_pages_exceeded"
    assert gateway.calls == []
    assert BackfillRun.objects.count() == 0


@pytest.mark.django_db
def test_backfill_blocks_when_requested_missing_time_is_not_returned() -> None:
    request = BackfillRequest.objects.create(
        business_key="backfill-request:missing-not-found",
        source_module="DataQuality",
        exchange="binance",
        market_type="usds_m_futures",
        symbol="BTCUSDT",
        timeframe="4h",
        backfill_mode="gap_backfill",
        requested_start_open_time_utc=dt(2026, 1, 1, 8),
        requested_end_open_time_utc=dt(2026, 1, 1, 8),
        missing_open_times=[dt(2026, 1, 1, 8).isoformat()],
        trace_id="trace_backfill",
        trigger_source="test",
    )
    result = run_data_backfill(
        timeframe="4h",
        backfill_mode="gap_backfill",
        start_open_time_utc=dt(2026, 1, 1, 8),
        end_open_time_utc=dt(2026, 1, 1, 8),
        missing_open_times=[dt(2026, 1, 1, 8)],
        business_request_key="backfill:missing-not-found",
        trace_id="trace_backfill",
        trigger_source="test",
        backfill_request_id=request.id,
        gateway=FakeBinancePublicMarketGateway(server_time_utc=dt(2026, 1, 1, 13), klines=[]),
    )
    assert result.status == ResultStatus.BLOCKED
    run = BackfillRun.objects.get()
    assert run.status == "blocked"
    assert run.requires_quality_recheck is False


@pytest.mark.django_db
def test_market_snapshot_requires_4h_and_1d_quality_pass() -> None:
    create_kline(dt(2026, 1, 1, 4))
    create_kline(dt(2026, 1, 1, 8))
    create_kline(dt(2025, 12, 30), timeframe="1d")
    create_kline(dt(2025, 12, 31), timeframe="1d")
    quality_pass("4h", dt(2026, 1, 1, 4), dt(2026, 1, 1, 8), 2)
    quality_pass("1d", dt(2025, 12, 30), dt(2025, 12, 31), 2)
    result = create_market_snapshot(
        analysis_close_time_utc=dt(2026, 1, 1, 12),
        analysis_reference_time_utc=dt(2026, 1, 1, 13),
        lookback_4h_count=2,
        lookback_1d_count=2,
        business_request_key="snapshot:1",
        trace_id="trace_snapshot",
        trigger_source="test",
    )
    assert result.status == ResultStatus.SUCCEEDED
    snapshot = MarketSnapshot.objects.get()
    assert snapshot.allows_feature_layer is True
    assert "klines" not in snapshot.payload_summary


@pytest.mark.django_db
def test_market_snapshot_treats_exact_reference_close_time_as_unclosed() -> None:
    create_kline(dt(2026, 1, 1, 4))
    create_kline(dt(2026, 1, 1, 8))
    create_kline(dt(2025, 12, 30), timeframe="1d")
    create_kline(dt(2025, 12, 31), timeframe="1d")
    quality_pass("4h", dt(2026, 1, 1, 4), dt(2026, 1, 1, 8), 2)
    quality_pass("1d", dt(2025, 12, 30), dt(2025, 12, 31), 2)
    result = create_market_snapshot(
        analysis_close_time_utc=dt(2026, 1, 1, 12),
        analysis_reference_time_utc=dt(2026, 1, 1, 12),
        lookback_4h_count=2,
        lookback_1d_count=2,
        business_request_key="snapshot:exact-close-unclosed",
        trace_id="trace_snapshot",
        trigger_source="test",
    )
    assert result.status == ResultStatus.BLOCKED
    assert result.reason_code == "4h_kline_unclosed"
    assert MarketSnapshot.objects.count() == 0


@pytest.mark.django_db
def test_market_snapshot_blocks_without_1d_quality() -> None:
    create_kline(dt(2026, 1, 1, 4))
    create_kline(dt(2026, 1, 1, 8))
    create_kline(dt(2025, 12, 30), timeframe="1d")
    create_kline(dt(2025, 12, 31), timeframe="1d")
    quality_pass("4h", dt(2026, 1, 1, 4), dt(2026, 1, 1, 8), 2)
    result = create_market_snapshot(
        analysis_close_time_utc=dt(2026, 1, 1, 12),
        analysis_reference_time_utc=dt(2026, 1, 1, 13),
        lookback_4h_count=2,
        lookback_1d_count=2,
        business_request_key="snapshot:blocked",
        trace_id="trace_snapshot",
        trigger_source="test",
    )
    assert result.status == ResultStatus.BLOCKED
    assert MarketSnapshot.objects.count() == 0


@pytest.mark.django_db
def test_market_snapshot_dry_run_block_does_not_write_alert_event() -> None:
    result = create_market_snapshot(
        analysis_close_time_utc=dt(2026, 1, 1, 12),
        analysis_reference_time_utc=dt(2026, 1, 1, 13),
        lookback_4h_count=2,
        lookback_1d_count=2,
        business_request_key="snapshot:dry-run-blocked",
        trace_id="trace_snapshot",
        trigger_source="test",
        dry_run=True,
    )
    assert result.status == ResultStatus.BLOCKED
    assert AlertEvent.objects.count() == 0
