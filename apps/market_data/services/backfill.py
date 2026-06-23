"""MarketData 模块：DataBackfill service；读写回补事实，通过 Gateway 拉取 Kline，不涉及交易执行。"""

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
    binance_interval,
    configured_collection_domain,
    ensure_utc,
    expected_open_times,
    is_closed_kline,
    is_timeframe_boundary,
    normalize_binance_kline,
    timeframe_delta,
)
from ..kline_writer import write_kline_idempotently
from ..models import BackfillIssue, BackfillRequest, BackfillRun, CommonStatus, Kline
from .alerts import record_market_data_alert


BACKFILL_MODES = {
    "initial_historical_backfill",
    "gap_backfill",
    "manual_range_backfill",
    "conflict_recheck",
    "failure_recovery_backfill",
}
CLAIMABLE_STATUSES = {CommonStatus.PENDING, CommonStatus.FAILED}


def run_data_backfill(
    *,
    timeframe: str,
    backfill_mode: str,
    start_open_time_utc: datetime,
    end_open_time_utc: datetime,
    business_request_key: str,
    trace_id: str | None,
    trigger_source: str,
    backfill_request_id: int | None = None,
    missing_open_times: list[datetime] | None = None,
    dry_run: bool = False,
    confirm_write: bool = False,
    operator_id: str = "",
    reason: str = "",
    evidence: dict[str, Any] | None = None,
    gateway: PublicMarketGateway | None = None,
) -> ServiceResult:
    context = ensure_context(trace_id=trace_id, trigger_source=trigger_source, operator_id=operator_id)
    domain = configured_collection_domain()
    start_open = ensure_utc(start_open_time_utc)
    end_open = ensure_utc(end_open_time_utc)
    missing_times = sorted({ensure_utc(time) for time in (missing_open_times or [])})
    blocked_reason = _validate_backfill(timeframe, backfill_mode, start_open, end_open, missing_times)
    if blocked_reason:
        return _blocked_result(context.trace_id, trigger_source, blocked_reason)
    if backfill_mode == "manual_range_backfill" and not dry_run and not confirm_write:
        return _blocked_result(context.trace_id, trigger_source, "manual_backfill_requires_confirm_write")
    if dry_run:
        return _dry_run_result(context.trace_id, trigger_source, business_request_key, missing_times)

    request = _claim_request_if_needed(backfill_request_id, context.trace_id)
    if isinstance(request, ServiceResult):
        return request
    existing = BackfillRun.objects.filter(business_request_key=business_request_key).first()
    if existing and existing.status != CommonStatus.RUNNING:
        return _result_from_run(existing)

    run = _get_or_create_run(
        business_request_key=business_request_key,
        request=request,
        trace_id=context.trace_id,
        trigger_source=trigger_source,
        operator_id=operator_id,
        timeframe=timeframe,
        backfill_mode=backfill_mode,
        start_open=start_open,
        end_open=end_open,
        missing_times=missing_times,
    )
    gateway = gateway or get_public_market_gateway()
    server_result = gateway.get_server_time(
        market_type=domain.market_type,
        call_context=BinanceGatewayCallContext(
            trace_id=context.trace_id,
            trigger_source=trigger_source,
            operation="get_server_time",
            market_type=domain.market_type,
            business_object_type="BackfillRun",
            business_object_id=str(run.id),
            request_time_utc=timezone.now(),
        ),
    )
    if not server_result.success or server_result.server_time_utc is None:
        return _finish_run_failed(run, request, "gateway_server_time_failed", server_result.sanitized_error_message)
    return _fetch_and_write_pages(run, request, gateway, server_result.server_time_utc, missing_times)


def _validate_backfill(
    timeframe: str,
    backfill_mode: str,
    start_open: datetime,
    end_open: datetime,
    missing_times: list[datetime],
) -> str:
    domain = configured_collection_domain()
    if timeframe not in domain.timeframes:
        return "unsupported_timeframe"
    if backfill_mode not in BACKFILL_MODES:
        return "unsupported_backfill_mode"
    if start_open > end_open:
        return "time_range_invalid"
    if not is_timeframe_boundary(start_open, timeframe) or not is_timeframe_boundary(end_open, timeframe):
        return "time_boundary_invalid"
    for missing_time in missing_times:
        if not is_timeframe_boundary(missing_time, timeframe):
            return "missing_open_time_boundary_invalid"
    expected_count = len(expected_open_times(start_open, end_open, timeframe))
    if expected_count > getattr(settings, "DATA_BACKFILL_MAX_BARS_PER_RUN", 5000):
        return "max_bars_exceeded"
    page_limit = getattr(settings, "DATA_BACKFILL_KLINE_PAGE_LIMIT", 1000)
    max_pages = getattr(settings, "DATA_BACKFILL_MAX_PAGES_PER_RUN", 10)
    if expected_count > page_limit * max_pages:
        return "max_pages_exceeded"
    return ""


def _claim_request_if_needed(backfill_request_id: int | None, trace_id: str) -> BackfillRequest | ServiceResult | None:
    if backfill_request_id is None:
        return None
    with transaction.atomic():
        request = BackfillRequest.objects.select_for_update().get(id=backfill_request_id)
        if request.status not in CLAIMABLE_STATUSES:
            return ServiceResult(
                ResultStatus.SKIPPED,
                "backfill_request_not_claimable",
                "BackfillRequest 已非可执行状态",
                trace_id,
                request.trigger_source,
                data={"backfill_request_id": request.id, "status": request.status},
            )
        request.status = CommonStatus.RUNNING
        request.locked_by = trace_id
        request.locked_at_utc = timezone.now()
        request.attempt_count += 1
        request.save(update_fields=["status", "locked_by", "locked_at_utc", "attempt_count", "updated_at_utc"])
    return request


def _get_or_create_run(
    *,
    business_request_key: str,
    request: BackfillRequest | None,
    trace_id: str,
    trigger_source: str,
    operator_id: str,
    timeframe: str,
    backfill_mode: str,
    start_open: datetime,
    end_open: datetime,
    missing_times: list[datetime],
) -> BackfillRun:
    domain = configured_collection_domain()
    run, _created = BackfillRun.objects.get_or_create(
        business_request_key=business_request_key,
        defaults={
            "backfill_request": request,
            "trace_id": trace_id,
            "trigger_source": trigger_source,
            "operator_id": operator_id,
            "exchange": domain.exchange,
            "market_type": domain.market_type,
            "symbol": domain.symbol,
            "timeframe": timeframe,
            "backfill_mode": backfill_mode,
            "requested_start_open_time_utc": start_open,
            "requested_end_open_time_utc": end_open,
            "missing_open_times": [time.isoformat() for time in missing_times],
        },
    )
    if request and request.last_backfill_run_id != run.id:
        request.last_backfill_run = run
        request.save(update_fields=["last_backfill_run", "updated_at_utc"])
    return run


def _fetch_and_write_pages(
    run: BackfillRun,
    request: BackfillRequest | None,
    gateway: PublicMarketGateway,
    server_time_utc: datetime,
    missing_times: list[datetime],
) -> ServiceResult:
    domain = configured_collection_domain()
    current_start = run.requested_start_open_time_utc
    end_open = run.requested_end_open_time_utc
    page_limit = getattr(settings, "DATA_BACKFILL_KLINE_PAGE_LIMIT", 1000)
    max_pages = getattr(settings, "DATA_BACKFILL_MAX_PAGES_PER_RUN", 10)
    counters = {"fetched": 0, "closed": 0, "inserted": 0, "skipped": 0, "unclosed": 0, "not_requested": 0, "conflict": 0}
    requested_set = set(missing_times)
    page_count = 0
    while current_start <= end_open and page_count < max_pages:
        page_count += 1
        result = gateway.get_klines(
            market_type=domain.market_type,
            symbol=domain.symbol,
            interval=binance_interval(run.timeframe),
            start_time_utc=current_start,
            end_time_utc=end_open + timeframe_delta(run.timeframe),
            limit=page_limit,
            call_context=BinanceGatewayCallContext(
                trace_id=run.trace_id,
                trigger_source=run.trigger_source,
                operation="get_klines",
                market_type=domain.market_type,
                symbol=domain.symbol,
                business_object_type="BackfillRun",
                business_object_id=str(run.id),
                request_time_utc=timezone.now(),
            ),
        )
        run.gateway_attempt_count += result.attempt_count
        if not result.success:
            return _finish_run_failed(run, request, "gateway_klines_failed", result.sanitized_error_message)
        payload = result.payload or []
        counters["fetched"] += len(payload)
        if not payload:
            break
        last_open = _write_backfill_payload(run, payload, server_time_utc, requested_set, counters)
        if last_open is None or len(payload) < page_limit:
            break
        current_start = last_open + timeframe_delta(run.timeframe)

    run.page_count = page_count
    run.fetched_count = counters["fetched"]
    run.closed_count = counters["closed"]
    run.inserted_count = counters["inserted"]
    run.skipped_existing_count = counters["skipped"]
    run.filtered_unclosed_count = counters["unclosed"]
    run.filtered_not_requested_count = counters["not_requested"]
    run.conflict_count = counters["conflict"]
    run.requires_quality_recheck = True
    run.recheck_window_start_open_time_utc = run.requested_start_open_time_utc
    run.recheck_window_end_open_time_utc = run.requested_end_open_time_utc
    run.status = CommonStatus.CONFLICT if counters["conflict"] else CommonStatus.SUCCESS
    run.reason_code = "kline_conflict" if counters["conflict"] else "backfill_completed_requires_quality_recheck"
    run.finished_at_utc = timezone.now()
    run.save()
    _finish_request(request, run)
    missing_not_found = _missing_open_times_not_found(run, missing_times)
    if missing_not_found:
        return _finish_run_blocked(
            run,
            request,
            "missing_open_times_not_found",
            f"指定回补 open_time 未全部返回或写入：{', '.join(time.isoformat() for time in missing_not_found)}",
        )
    if counters["conflict"]:
        BackfillIssue.objects.create(run=run, issue_type="KLINE_CONFLICT", detail="回补发现 Kline 冲突")
    return _result_from_run(run)


def _missing_open_times_not_found(run: BackfillRun, missing_times: list[datetime]) -> list[datetime]:
    if not missing_times:
        return []
    existing_times = set(
        Kline.objects.filter(
            exchange=run.exchange,
            market_type=run.market_type,
            symbol=run.symbol,
            timeframe=run.timeframe,
            open_time_utc__in=missing_times,
        ).values_list("open_time_utc", flat=True)
    )
    return [time for time in missing_times if time not in existing_times]


def _write_backfill_payload(
    run: BackfillRun,
    payload: list[Any],
    server_time_utc: datetime,
    requested_set: set[datetime],
    counters: dict[str, int],
) -> datetime | None:
    domain = configured_collection_domain()
    last_open = None
    for raw in payload:
        normalized = normalize_binance_kline(
            raw=raw,
            exchange=domain.exchange,
            market_type=domain.market_type,
            symbol=domain.symbol,
            timeframe=run.timeframe,
        )
        last_open = normalized.open_time_utc
        if requested_set and normalized.open_time_utc not in requested_set:
            counters["not_requested"] += 1
            continue
        if not is_closed_kline(normalized, server_time_utc=server_time_utc):
            counters["unclosed"] += 1
            continue
        counters["closed"] += 1
        outcome = write_kline_idempotently(
            normalized=normalized,
            source_module="DataBackfill",
            trace_id=run.trace_id,
            trigger_source=run.trigger_source,
            source_backfill_run=run,
        )
        counters["inserted"] += 1 if outcome.action == "inserted" else 0
        counters["skipped"] += 1 if outcome.action == "skipped_existing" else 0
        counters["conflict"] += 1 if outcome.action == "conflict" else 0
    return last_open


def _finish_request(request: BackfillRequest | None, run: BackfillRun) -> None:
    if not request:
        return
    request.status = CommonStatus.CONFLICT if run.status == CommonStatus.CONFLICT else CommonStatus.SUCCESS
    request.last_backfill_run = run
    request.save(update_fields=["status", "last_backfill_run", "updated_at_utc"])


def _finish_run_failed(run: BackfillRun, request: BackfillRequest | None, reason_code: str, message: str) -> ServiceResult:
    run.status = CommonStatus.FAILED
    run.reason_code = reason_code
    run.error_code = reason_code
    run.error_message = message[:500]
    run.finished_at_utc = timezone.now()
    run.save(update_fields=["status", "reason_code", "error_code", "error_message", "finished_at_utc"])
    if request:
        request.status = CommonStatus.FAILED
        request.save(update_fields=["status", "updated_at_utc"])
    record_market_data_alert(
        source_module="DataBackfill",
        event_type="data_backfill_failed",
        severity="warning",
        title_zh="行情回补失败",
        message_zh="DataBackfill 未能完成 Kline 回补，不能放行给 MarketSnapshot。",
        trace_id=run.trace_id,
        trigger_source=run.trigger_source,
        business_status=run.status,
        reason_code=reason_code,
        related_object_type="BackfillRun",
        related_object_id=str(run.id),
        payload_summary={"error_message": message},
    )
    return _result_from_run(run)


def _finish_run_blocked(run: BackfillRun, request: BackfillRequest | None, reason_code: str, message: str) -> ServiceResult:
    run.status = CommonStatus.BLOCKED
    run.reason_code = reason_code
    run.error_code = reason_code
    run.error_message = message[:500]
    run.requires_quality_recheck = False
    run.finished_at_utc = timezone.now()
    run.save(update_fields=["status", "reason_code", "error_code", "error_message", "requires_quality_recheck", "finished_at_utc"])
    if request:
        request.status = CommonStatus.BLOCKED
        request.save(update_fields=["status", "updated_at_utc"])
    BackfillIssue.objects.create(run=run, issue_type="MISSING_OPEN_TIMES_NOT_FOUND", detail=message[:500])
    record_market_data_alert(
        source_module="DataBackfill",
        event_type="data_backfill_blocked",
        severity="warning",
        title_zh="行情回补被阻断",
        message_zh="DataBackfill 未能确认指定缺口已补齐，不能放行给 DataQuality 复检。",
        trace_id=run.trace_id,
        trigger_source=run.trigger_source,
        business_status=run.status,
        reason_code=reason_code,
        related_object_type="BackfillRun",
        related_object_id=str(run.id),
        payload_summary={"error_message": message},
    )
    return _result_from_run(run)


def _result_from_run(run: BackfillRun) -> ServiceResult:
    status = ResultStatus.SUCCEEDED if run.status == CommonStatus.SUCCESS else ResultStatus.BLOCKED
    return ServiceResult(
        status=status,
        reason_code=run.reason_code,
        message=f"BackfillRun {run.status}",
        trace_id=run.trace_id,
        trigger_source=run.trigger_source,
        data={
            "backfill_run_id": run.id,
            "requires_quality_recheck": run.requires_quality_recheck,
            "inserted_count": run.inserted_count,
            "skipped_existing_count": run.skipped_existing_count,
            "conflict_count": run.conflict_count,
        },
    )


def _blocked_result(trace_id: str, trigger_source: str, reason_code: str) -> ServiceResult:
    return ServiceResult(ResultStatus.BLOCKED, reason_code, "DataBackfill blocked", trace_id, trigger_source)


def _dry_run_result(
    trace_id: str,
    trigger_source: str,
    business_request_key: str,
    missing_times: list[datetime],
) -> ServiceResult:
    return ServiceResult(
        ResultStatus.SUCCEEDED,
        "dry_run_preview",
        "DataBackfill dry-run 未写入正式结果",
        trace_id,
        trigger_source,
        data={"business_request_key": business_request_key, "missing_open_times": [time.isoformat() for time in missing_times]},
    )
