"""MarketData 模块：MarketSnapshot service；只消费已质检行情事实，不请求 Binance，不涉及交易执行。"""

from __future__ import annotations

from datetime import datetime

from django.conf import settings

from apps.foundation.context import ensure_context
from apps.foundation.results import ResultStatus, ServiceResult

from ..domain import (
    TIMEFRAME_1D,
    TIMEFRAME_4H,
    configured_collection_domain,
    ensure_utc,
    expected_open_times,
    is_timeframe_boundary,
    latest_closed_open_time,
    timeframe_delta,
)
from ..models import CommonStatus, DataQualityResult, Kline, MarketSnapshot
from .alerts import record_market_data_alert


def create_market_snapshot(
    *,
    analysis_close_time_utc: datetime,
    analysis_reference_time_utc: datetime,
    business_request_key: str,
    trace_id: str | None,
    trigger_source: str,
    lookback_4h_count: int | None = None,
    lookback_1d_count: int | None = None,
    dry_run: bool = False,
) -> ServiceResult:
    context = ensure_context(trace_id=trace_id, trigger_source=trigger_source)
    analysis_close = ensure_utc(analysis_close_time_utc)
    analysis_reference = ensure_utc(analysis_reference_time_utc)
    if not is_timeframe_boundary(analysis_close, TIMEFRAME_4H):
        return _blocked(context.trace_id, trigger_source, "analysis_close_time_not_4h_boundary")
    existing = MarketSnapshot.objects.filter(business_request_key=business_request_key).first()
    if existing and not dry_run:
        return _result_from_snapshot(existing)

    windows = _snapshot_windows(
        analysis_close=analysis_close,
        analysis_reference=analysis_reference,
        lookback_4h_count=lookback_4h_count,
        lookback_1d_count=lookback_1d_count,
    )
    quality_4h = _find_quality_result(TIMEFRAME_4H, windows["start_4h"], windows["end_4h"], windows["lookback_4h"])
    quality_1d = _find_quality_result(TIMEFRAME_1D, windows["start_1d"], windows["end_1d"], windows["lookback_1d"])
    if not quality_4h or not quality_1d:
        return _blocked_with_alert(
            context.trace_id,
            trigger_source,
            "quality_result_not_covering_snapshot",
            windows,
            write_alert=not dry_run,
        )

    klines_4h = _load_window_klines(TIMEFRAME_4H, windows["start_4h"], windows["end_4h"])
    klines_1d = _load_window_klines(TIMEFRAME_1D, windows["start_1d"], windows["end_1d"])
    validation_reason = _validate_kline_window(
        klines_4h,
        TIMEFRAME_4H,
        windows["start_4h"],
        windows["end_4h"],
        windows["lookback_4h"],
        analysis_reference,
    ) or _validate_kline_window(
        klines_1d,
        TIMEFRAME_1D,
        windows["start_1d"],
        windows["end_1d"],
        windows["lookback_1d"],
        analysis_reference,
    )
    if validation_reason:
        return _blocked_with_alert(
            context.trace_id,
            trigger_source,
            validation_reason,
            windows,
            write_alert=not dry_run,
        )
    if dry_run:
        return _dry_result(context.trace_id, trigger_source, windows)

    domain = configured_collection_domain()
    snapshot = MarketSnapshot.objects.create(
        business_request_key=business_request_key,
        exchange=domain.exchange,
        market_type=domain.market_type,
        symbol=domain.symbol,
        base_timeframe=TIMEFRAME_4H,
        higher_timeframe=TIMEFRAME_1D,
        analysis_close_time_utc=analysis_close,
        analysis_reference_time_utc=analysis_reference,
        status=CommonStatus.CREATED,
        reason_code="market_snapshot_created",
        latest_4h_open_time_utc=windows["end_4h"],
        latest_1d_open_time_utc=windows["end_1d"],
        lookback_4h_count=windows["lookback_4h"],
        lookback_1d_count=windows["lookback_1d"],
        actual_4h_count=len(klines_4h),
        actual_1d_count=len(klines_1d),
        start_4h_open_time_utc=windows["start_4h"],
        end_4h_open_time_utc=windows["end_4h"],
        start_1d_open_time_utc=windows["start_1d"],
        end_1d_open_time_utc=windows["end_1d"],
        data_quality_result_4h=quality_4h,
        data_quality_result_1d=quality_1d,
        data_collection_run_ids=_source_ids(klines_4h + klines_1d, "source_collection_run_id"),
        backfill_run_ids=_source_ids(klines_4h + klines_1d, "source_backfill_run_id"),
        payload_summary=_payload_summary(windows, quality_4h, quality_1d),
        allows_feature_layer=True,
        trace_id=context.trace_id,
        trigger_source=trigger_source,
    )
    return _result_from_snapshot(snapshot)


def _snapshot_windows(
    *,
    analysis_close: datetime,
    analysis_reference: datetime,
    lookback_4h_count: int | None,
    lookback_1d_count: int | None,
) -> dict[str, object]:
    lookback_4h = lookback_4h_count or getattr(settings, "MARKET_SNAPSHOT_4H_LOOKBACK_COUNT", 500)
    lookback_1d = lookback_1d_count or getattr(settings, "MARKET_SNAPSHOT_1D_LOOKBACK_COUNT", 365)
    end_4h = analysis_close - timeframe_delta(TIMEFRAME_4H)
    end_1d = latest_closed_open_time(analysis_reference, TIMEFRAME_1D)
    return {
        "lookback_4h": lookback_4h,
        "lookback_1d": lookback_1d,
        "start_4h": end_4h - timeframe_delta(TIMEFRAME_4H) * (lookback_4h - 1),
        "end_4h": end_4h,
        "start_1d": end_1d - timeframe_delta(TIMEFRAME_1D) * (lookback_1d - 1),
        "end_1d": end_1d,
    }


def _find_quality_result(timeframe: str, start_open: datetime, end_open: datetime, lookback_count: int) -> DataQualityResult | None:
    domain = configured_collection_domain()
    return (
        DataQualityResult.objects.filter(
            exchange=domain.exchange,
            market_type=domain.market_type,
            symbol=domain.symbol,
            timeframe=timeframe,
            status=CommonStatus.PASS,
            allows_downstream=True,
            check_start_open_time_utc__lte=start_open,
            check_end_open_time_utc__gte=end_open,
            coverage_start_open_time_utc__lte=start_open,
            coverage_end_open_time_utc__gte=end_open,
            expected_count__gte=lookback_count,
            actual_count__gte=lookback_count,
            issue_count=0,
        )
        .order_by("-created_at_utc")
        .first()
    )


def _load_window_klines(timeframe: str, start_open: datetime, end_open: datetime) -> list[Kline]:
    domain = configured_collection_domain()
    return list(
        Kline.objects.filter(
            exchange=domain.exchange,
            market_type=domain.market_type,
            symbol=domain.symbol,
            timeframe=timeframe,
            open_time_utc__gte=start_open,
            open_time_utc__lte=end_open,
        ).order_by("open_time_utc")
    )


def _validate_kline_window(
    klines: list[Kline],
    timeframe: str,
    start_open: datetime,
    end_open: datetime,
    lookback_count: int,
    analysis_reference: datetime,
) -> str:
    if len(klines) < lookback_count:
        return f"{timeframe}_kline_count_insufficient"
    expected = expected_open_times(start_open, end_open, timeframe)
    actual = [kline.open_time_utc for kline in klines]
    if actual != expected:
        return f"{timeframe}_kline_window_not_continuous"
    if any(kline.close_time_utc >= analysis_reference for kline in klines):
        return f"{timeframe}_kline_unclosed"
    return ""


def _source_ids(klines: list[Kline], field_name: str) -> list[int]:
    values = sorted({getattr(kline, field_name) for kline in klines if getattr(kline, field_name)})
    return values


def _payload_summary(windows: dict[str, object], quality_4h: DataQualityResult, quality_1d: DataQualityResult) -> dict[str, object]:
    return {
        "start_4h_open_time_utc": windows["start_4h"].isoformat(),
        "end_4h_open_time_utc": windows["end_4h"].isoformat(),
        "start_1d_open_time_utc": windows["start_1d"].isoformat(),
        "end_1d_open_time_utc": windows["end_1d"].isoformat(),
        "lookback_4h_count": windows["lookback_4h"],
        "lookback_1d_count": windows["lookback_1d"],
        "data_quality_result_4h_id": quality_4h.id,
        "data_quality_result_1d_id": quality_1d.id,
    }


def _result_from_snapshot(snapshot: MarketSnapshot) -> ServiceResult:
    return ServiceResult(
        ResultStatus.SUCCEEDED if snapshot.status == CommonStatus.CREATED else ResultStatus.BLOCKED,
        snapshot.reason_code,
        f"MarketSnapshot {snapshot.status}",
        snapshot.trace_id,
        snapshot.trigger_source,
        data={
            "market_snapshot_id": snapshot.id,
            "allows_feature_layer": snapshot.allows_feature_layer,
            "analysis_close_time_utc": snapshot.analysis_close_time_utc.isoformat(),
            "latest_4h_open_time_utc": snapshot.latest_4h_open_time_utc.isoformat(),
            "latest_1d_open_time_utc": snapshot.latest_1d_open_time_utc.isoformat(),
        },
    )


def _blocked(trace_id: str, trigger_source: str, reason_code: str) -> ServiceResult:
    return ServiceResult(ResultStatus.BLOCKED, reason_code, "MarketSnapshot blocked", trace_id, trigger_source)


def _blocked_with_alert(
    trace_id: str,
    trigger_source: str,
    reason_code: str,
    windows: dict[str, object],
    *,
    write_alert: bool = True,
) -> ServiceResult:
    if write_alert:
        record_market_data_alert(
            source_module="MarketSnapshot",
            event_type="market_snapshot_blocked",
            severity="warning",
            title_zh="市场快照创建被阻断",
            message_zh="MarketSnapshot 前置行情窗口或 DataQuality 授权不满足，已阻断后续分析。",
            trace_id=trace_id,
            trigger_source=trigger_source,
            business_status="blocked",
            reason_code=reason_code,
            payload_summary={key: value.isoformat() if isinstance(value, datetime) else value for key, value in windows.items()},
        )
    return _blocked(trace_id, trigger_source, reason_code)


def _dry_result(trace_id: str, trigger_source: str, windows: dict[str, object]) -> ServiceResult:
    return ServiceResult(
        ResultStatus.SUCCEEDED,
        "dry_run_preview",
        "MarketSnapshot dry-run 未写入正式结果",
        trace_id,
        trigger_source,
        data={key: value.isoformat() if isinstance(value, datetime) else value for key, value in windows.items()},
    )
