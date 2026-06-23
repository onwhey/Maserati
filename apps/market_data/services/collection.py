"""MarketData 模块：DataCollection service；读写 Kline 和采集记录，通过 Gateway 访问 Binance，不涉及交易执行。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.binance_gateway.public_market import PublicMarketGateway, get_public_market_gateway
from apps.binance_gateway.types import BinanceGatewayCallContext
from apps.foundation.context import ensure_context
from apps.foundation.results import ResultStatus, ServiceResult

from ..domain import (
    configured_collection_domain,
    binance_interval,
    ensure_utc,
    expected_open_times,
    is_closed_kline,
    latest_closed_open_time,
    normalize_binance_kline,
    timeframe_delta,
)
from ..kline_writer import write_kline_idempotently
from ..models import CommonStatus, DataCollectionRun
from .alerts import record_market_data_alert


COLLECTION_MODES = {"historical", "latest_closed", "incremental", "backfill_source_fetch"}


def collect_klines(
    *,
    timeframe: str,
    collection_mode: str,
    business_request_key: str,
    trace_id: str | None,
    trigger_source: str,
    start_open_time_utc: datetime | None = None,
    end_open_time_utc: datetime | None = None,
    lookback_count: int | None = None,
    dry_run: bool = False,
    gateway: PublicMarketGateway | None = None,
) -> ServiceResult:
    context = ensure_context(trace_id=trace_id, trigger_source=trigger_source)
    domain = configured_collection_domain()
    blocked_reason = _validate_request(timeframe=timeframe, collection_mode=collection_mode, domain_timeframes=domain.timeframes)
    if blocked_reason:
        return _blocked_result(context.trace_id, trigger_source, blocked_reason)
    if dry_run:
        return _dry_run_result(
            timeframe=timeframe,
            collection_mode=collection_mode,
            business_request_key=business_request_key,
            trace_id=context.trace_id,
            trigger_source=trigger_source,
            start_open_time_utc=start_open_time_utc,
            end_open_time_utc=end_open_time_utc,
        )

    existing = DataCollectionRun.objects.filter(business_request_key=business_request_key).first()
    if existing and existing.status != CommonStatus.RUNNING:
        return _result_from_run(existing)

    gateway = gateway or get_public_market_gateway()
    server_result = gateway.get_server_time(
        market_type=domain.market_type,
        call_context=BinanceGatewayCallContext(
            trace_id=context.trace_id,
            trigger_source=trigger_source,
            operation="get_server_time",
            market_type=domain.market_type,
            business_object_type="DataCollectionRun",
            business_object_id=business_request_key,
            request_time_utc=timezone.now(),
        ),
    )
    if not server_result.success or server_result.server_time_utc is None:
        return _failed_without_run(context.trace_id, trigger_source, "gateway_server_time_failed", server_result.sanitized_error_message)

    start_open, end_open, resolved_lookback = _resolve_window(
        timeframe=timeframe,
        server_time_utc=server_result.server_time_utc,
        start_open_time_utc=start_open_time_utc,
        end_open_time_utc=end_open_time_utc,
        lookback_count=lookback_count,
    )
    run = _get_or_create_run(
        business_request_key=business_request_key,
        trace_id=context.trace_id,
        trigger_source=trigger_source,
        timeframe=timeframe,
        collection_mode=collection_mode,
        start_open=start_open,
        end_open=end_open,
        lookback_count=resolved_lookback,
        server_time_utc=server_result.server_time_utc,
    )
    kline_result = gateway.get_klines(
        market_type=domain.market_type,
        symbol=domain.symbol,
        interval=binance_interval(timeframe),
        start_time_utc=start_open,
        end_time_utc=end_open + timeframe_delta(timeframe),
        limit=max(1, resolved_lookback),
        call_context=BinanceGatewayCallContext(
            trace_id=context.trace_id,
            trigger_source=trigger_source,
            operation="get_klines",
            market_type=domain.market_type,
            symbol=domain.symbol,
            business_object_type="DataCollectionRun",
            business_object_id=str(run.id),
            request_time_utc=timezone.now(),
        ),
    )
    if not kline_result.success:
        return _finish_run_failed(run, "gateway_klines_failed", kline_result.sanitized_error_message)
    return _write_collection_payload(run, kline_result.payload or [], server_result.server_time_utc)


def _validate_request(*, timeframe: str, collection_mode: str, domain_timeframes: tuple[str, ...]) -> str:
    if timeframe not in domain_timeframes:
        return "unsupported_timeframe"
    if collection_mode not in COLLECTION_MODES:
        return "unsupported_collection_mode"
    return ""


def _resolve_window(
    *,
    timeframe: str,
    server_time_utc: datetime,
    start_open_time_utc: datetime | None,
    end_open_time_utc: datetime | None,
    lookback_count: int | None,
) -> tuple[datetime, datetime, int]:
    if start_open_time_utc and end_open_time_utc:
        start_open = ensure_utc(start_open_time_utc)
        end_open = ensure_utc(end_open_time_utc)
        count = len(expected_open_times(start_open, end_open, timeframe))
        return start_open, end_open, count
    default_lookback = getattr(settings, "DATA_COLLECTION_4H_LOOKBACK_COUNT" if timeframe == "4h" else "DATA_COLLECTION_1D_LOOKBACK_COUNT")
    count = lookback_count or default_lookback
    end_open = latest_closed_open_time(server_time_utc, timeframe)
    start_open = end_open - (timeframe_delta(timeframe) * (count - 1))
    return start_open, end_open, count


def _get_or_create_run(
    *,
    business_request_key: str,
    trace_id: str,
    trigger_source: str,
    timeframe: str,
    collection_mode: str,
    start_open: datetime,
    end_open: datetime,
    lookback_count: int,
    server_time_utc: datetime,
) -> DataCollectionRun:
    domain = configured_collection_domain()
    with transaction.atomic():
        run, _created = DataCollectionRun.objects.get_or_create(
            business_request_key=business_request_key,
            defaults={
                "trace_id": trace_id,
                "trigger_source": trigger_source,
                "exchange": domain.exchange,
                "market_type": domain.market_type,
                "symbol": domain.symbol,
                "timeframe": timeframe,
                "collection_mode": collection_mode,
                "requested_start_open_time_utc": start_open,
                "requested_end_open_time_utc": end_open,
                "lookback_count": lookback_count,
                "server_time_utc": server_time_utc,
            },
        )
    return run


def _write_collection_payload(run: DataCollectionRun, payload: list[Any], server_time_utc: datetime) -> ServiceResult:
    domain = configured_collection_domain()
    counters = {"fetched": len(payload), "closed": 0, "inserted": 0, "skipped": 0, "unclosed": 0, "conflict": 0}
    for raw in payload:
        normalized = normalize_binance_kline(
            raw=raw,
            exchange=domain.exchange,
            market_type=domain.market_type,
            symbol=domain.symbol,
            timeframe=run.timeframe,
        )
        if not is_closed_kline(normalized, server_time_utc=server_time_utc):
            counters["unclosed"] += 1
            continue
        counters["closed"] += 1
        outcome = write_kline_idempotently(
            normalized=normalized,
            source_module="DataCollection",
            trace_id=run.trace_id,
            trigger_source=run.trigger_source,
            source_collection_run=run,
        )
        if outcome.action == "inserted":
            counters["inserted"] += 1
        elif outcome.action == "skipped_existing":
            counters["skipped"] += 1
        elif outcome.action == "conflict":
            counters["conflict"] += 1

    run.fetched_count = counters["fetched"]
    run.closed_count = counters["closed"]
    run.inserted_count = counters["inserted"]
    run.skipped_existing_count = counters["skipped"]
    run.filtered_unclosed_count = counters["unclosed"]
    run.conflict_count = counters["conflict"]
    run.status = CommonStatus.CONFLICT if counters["conflict"] else CommonStatus.SUCCEEDED
    run.reason_code = "kline_conflict" if counters["conflict"] else "collection_completed"
    run.finished_at_utc = timezone.now()
    run.save(update_fields=[
        "fetched_count",
        "closed_count",
        "inserted_count",
        "skipped_existing_count",
        "filtered_unclosed_count",
        "conflict_count",
        "status",
        "reason_code",
        "finished_at_utc",
    ])
    if counters["conflict"]:
        record_market_data_alert(
            source_module="DataCollection",
            event_type="data_collection_conflict",
            severity="warning",
            title_zh="行情采集发现 Kline 冲突",
            message_zh="DataCollection 发现同一 Kline 业务键下的 OHLCV 不一致，已阻断覆盖。",
            trace_id=run.trace_id,
            trigger_source=run.trigger_source,
            business_status=run.status,
            reason_code=run.reason_code,
            related_object_type="DataCollectionRun",
            related_object_id=str(run.id),
            payload_summary=counters,
        )
    return _result_from_run(run)


def _finish_run_failed(run: DataCollectionRun, reason_code: str, message: str) -> ServiceResult:
    run.status = CommonStatus.FAILED
    run.reason_code = reason_code
    run.error_code = reason_code
    run.error_message = message[:500]
    run.finished_at_utc = timezone.now()
    run.save(update_fields=["status", "reason_code", "error_code", "error_message", "finished_at_utc"])
    record_market_data_alert(
        source_module="DataCollection",
        event_type="data_collection_failed",
        severity="warning",
        title_zh="行情采集失败",
        message_zh="DataCollection 采集失败，未放行给 DataQuality。",
        trace_id=run.trace_id,
        trigger_source=run.trigger_source,
        business_status=run.status,
        reason_code=reason_code,
        related_object_type="DataCollectionRun",
        related_object_id=str(run.id),
        payload_summary={"error_message": message},
    )
    return _result_from_run(run)


def _result_from_run(run: DataCollectionRun) -> ServiceResult:
    if run.status == CommonStatus.SUCCEEDED:
        status = ResultStatus.SUCCEEDED
    elif run.status == CommonStatus.FAILED:
        status = ResultStatus.FAILED
    elif run.status == CommonStatus.UNKNOWN:
        status = ResultStatus.UNKNOWN
    else:
        status = ResultStatus.BLOCKED
    return ServiceResult(
        status=status,
        reason_code=run.reason_code,
        message=f"DataCollectionRun {run.status}",
        trace_id=run.trace_id,
        trigger_source=run.trigger_source,
        data={
            "data_collection_run_id": run.id,
            "inserted_count": run.inserted_count,
            "skipped_existing_count": run.skipped_existing_count,
            "conflict_count": run.conflict_count,
            "filtered_unclosed_count": run.filtered_unclosed_count,
        },
    )


def _blocked_result(trace_id: str, trigger_source: str, reason_code: str) -> ServiceResult:
    return ServiceResult(ResultStatus.BLOCKED, reason_code, "DataCollection blocked", trace_id, trigger_source)


def _failed_without_run(trace_id: str, trigger_source: str, reason_code: str, message: str) -> ServiceResult:
    return ServiceResult(ResultStatus.FAILED, reason_code, message, trace_id, trigger_source)


def _dry_run_result(
    *,
    timeframe: str,
    collection_mode: str,
    business_request_key: str,
    trace_id: str,
    trigger_source: str,
    start_open_time_utc: datetime | None,
    end_open_time_utc: datetime | None,
) -> ServiceResult:
    return ServiceResult(
        ResultStatus.SUCCEEDED,
        "dry_run_preview",
        "DataCollection dry-run 未写入正式结果",
        trace_id,
        trigger_source,
        data={
            "business_request_key": business_request_key,
            "timeframe": timeframe,
            "collection_mode": collection_mode,
            "start_open_time_utc": start_open_time_utc.isoformat() if start_open_time_utc else "",
            "end_open_time_utc": end_open_time_utc.isoformat() if end_open_time_utc else "",
        },
    )
