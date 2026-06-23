"""MarketData 模块：DataQuality service；只读 Kline 并写质检事实，不请求 Binance，不涉及交易执行。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from django.db import transaction

from apps.foundation.context import ensure_context
from apps.foundation.idempotency import build_idempotency_key
from apps.foundation.results import ResultStatus, ServiceResult

from ..domain import (
    DATA_SOURCE_BINANCE_REST,
    configured_collection_domain,
    ensure_utc,
    expected_open_times,
    is_timeframe_boundary,
    timeframe_delta,
)
from ..models import BackfillRequest, CommonStatus, DataConflict, DataQualityIssue, DataQualityResult, Kline
from .alerts import record_market_data_alert


BACKFILLABLE_ISSUES = {
    "EMPTY_KLINE_SET",
    "MISSING_KLINE",
    "LATEST_KLINE_DELAYED",
    "NON_CONTINUOUS_KLINE",
    "WINDOW_COVERAGE_INSUFFICIENT",
}


@dataclass(frozen=True)
class IssueSpec:
    issue_type: str
    detail: str
    open_time_utc: datetime | None = None
    backfillable: bool = False


def check_data_quality(
    *,
    timeframe: str,
    check_start_open_time_utc: datetime,
    check_end_open_time_utc: datetime,
    business_request_key: str,
    trace_id: str | None,
    trigger_source: str,
    quality_reference_time_utc: datetime,
    expected_latest_open_time_utc: datetime | None = None,
    source_collection_run_id: int | None = None,
    source_backfill_run_id: int | None = None,
    dry_run: bool = False,
) -> ServiceResult:
    context = ensure_context(trace_id=trace_id, trigger_source=trigger_source)
    domain = configured_collection_domain()
    start_open = ensure_utc(check_start_open_time_utc)
    end_open = ensure_utc(check_end_open_time_utc)
    reference_time = ensure_utc(quality_reference_time_utc)
    existing = DataQualityResult.objects.filter(business_request_key=business_request_key).first()
    if existing and not dry_run:
        return _result_from_quality(existing)

    validation_issue = _validate_window(timeframe=timeframe, start_open=start_open, end_open=end_open)
    expected_times = [] if validation_issue else expected_open_times(start_open, end_open, timeframe)
    klines = list(_kline_queryset(timeframe=timeframe, start_open=start_open, end_open=end_open))
    issues = [validation_issue] if validation_issue else []
    issues.extend(_collect_kline_issues(klines=klines, expected_times=expected_times, timeframe=timeframe, reference_time=reference_time))
    issues.extend(_collect_conflict_issues(timeframe=timeframe, start_open=start_open, end_open=end_open))
    if expected_latest_open_time_utc and ensure_utc(expected_latest_open_time_utc) not in {k.open_time_utc for k in klines}:
        issues.append(IssueSpec("LATEST_KLINE_DELAYED", "期望最新 Kline 尚未落库", ensure_utc(expected_latest_open_time_utc), True))

    status = CommonStatus.PASS if not issues else CommonStatus.FAIL
    allows_downstream = status == CommonStatus.PASS
    if dry_run:
        return _dry_result(context.trace_id, trigger_source, status, issues, expected_times, klines)

    with transaction.atomic():
        result = DataQualityResult.objects.create(
            business_request_key=business_request_key,
            trace_id=context.trace_id,
            trigger_source=trigger_source,
            exchange=domain.exchange,
            market_type=domain.market_type,
            symbol=domain.symbol,
            timeframe=timeframe,
            status=status,
            reason_code="quality_pass" if allows_downstream else "quality_issues_found",
            check_start_open_time_utc=start_open,
            check_end_open_time_utc=end_open,
            expected_latest_open_time_utc=expected_latest_open_time_utc,
            expected_count=len(expected_times),
            actual_count=len(klines),
            issue_count=len(issues),
            allows_downstream=allows_downstream,
            coverage_start_open_time_utc=klines[0].open_time_utc if klines else None,
            coverage_end_open_time_utc=klines[-1].open_time_utc if klines else None,
            source_collection_run_id=source_collection_run_id,
            source_backfill_run_id=source_backfill_run_id,
        )
        DataQualityIssue.objects.bulk_create([
            DataQualityIssue(
                result=result,
                issue_type=issue.issue_type,
                detail=issue.detail,
                open_time_utc=issue.open_time_utc,
                backfillable=issue.backfillable,
            )
            for issue in issues
        ])
        backfill_request = _create_backfill_request_if_needed(result, issues)

    if not allows_downstream:
        record_market_data_alert(
            source_module="DataQuality",
            event_type="data_quality_not_pass",
            severity="warning",
            title_zh="行情数据质检未通过",
            message_zh="DataQuality 发现行情窗口存在问题，已阻断 MarketSnapshot。",
            trace_id=context.trace_id,
            trigger_source=trigger_source,
            business_status=result.status,
            reason_code=result.reason_code,
            related_object_type="DataQualityResult",
            related_object_id=str(result.id),
            payload_summary={"issue_count": len(issues), "backfill_request_id": backfill_request.id if backfill_request else None},
        )
    return _result_from_quality(result)


def _validate_window(*, timeframe: str, start_open: datetime, end_open: datetime) -> IssueSpec | None:
    domain = configured_collection_domain()
    if timeframe not in domain.timeframes:
        return IssueSpec("UNEXPECTED_TIMEFRAME", "不支持的 Kline 周期")
    if start_open > end_open:
        return IssueSpec("INVALID_TIME_BOUNDARY", "检查窗口开始时间晚于结束时间")
    if not is_timeframe_boundary(start_open, timeframe) or not is_timeframe_boundary(end_open, timeframe):
        return IssueSpec("INVALID_TIME_BOUNDARY", "检查窗口未对齐 Kline 周期边界")
    return None


def _kline_queryset(*, timeframe: str, start_open: datetime, end_open: datetime):
    domain = configured_collection_domain()
    return (
        Kline.objects.filter(
            exchange=domain.exchange,
            market_type=domain.market_type,
            symbol=domain.symbol,
            timeframe=timeframe,
            open_time_utc__gte=start_open,
            open_time_utc__lte=end_open,
        )
        .order_by("open_time_utc")
    )


def _collect_kline_issues(
    *,
    klines: list[Kline],
    expected_times: list[datetime],
    timeframe: str,
    reference_time: datetime,
) -> list[IssueSpec]:
    if not klines:
        issues = [IssueSpec("EMPTY_KLINE_SET", "检查窗口内没有任何 Kline")]
        issues.extend(
            IssueSpec("MISSING_KLINE", "缺失目标 open_time 的 Kline", expected_time, True)
            for expected_time in expected_times
        )
        return issues
    issues: list[IssueSpec] = []
    by_open = {k.open_time_utc: k for k in klines}
    for expected_time in expected_times:
        if expected_time not in by_open:
            issues.append(IssueSpec("MISSING_KLINE", "缺失目标 open_time 的 Kline", expected_time, True))
    for kline in klines:
        issues.extend(_single_kline_issues(kline, timeframe, reference_time))
    actual_times = [k.open_time_utc for k in klines]
    if actual_times != sorted(actual_times):
        issues.append(IssueSpec("NON_CONTINUOUS_KLINE", "Kline 排序不连续", None, True))
    return issues


def _single_kline_issues(kline: Kline, timeframe: str, reference_time: datetime) -> list[IssueSpec]:
    issues: list[IssueSpec] = []
    if kline.close_time_utc != kline.open_time_utc + timeframe_delta(timeframe):
        issues.append(IssueSpec("INVALID_OPEN_CLOSE_TIME", "open_time 与 close_time 不匹配", kline.open_time_utc))
    if kline.close_time_utc >= reference_time:
        issues.append(IssueSpec("UNCLOSED_KLINE", "检查窗口内存在未收盘 Kline", kline.open_time_utc))
    if not is_timeframe_boundary(kline.open_time_utc, timeframe):
        issues.append(IssueSpec("INVALID_TIME_BOUNDARY", "Kline open_time 未对齐周期边界", kline.open_time_utc))
    if not _valid_ohlc(kline):
        issues.append(IssueSpec("INVALID_OHLC", "OHLC 价格关系非法", kline.open_time_utc))
    if kline.volume <= Decimal("0") or kline.quote_volume <= Decimal("0"):
        issues.append(IssueSpec("INVALID_VOLUME", "BTCUSDT 4h/1d 成交量不得为 0", kline.open_time_utc))
    if kline.data_source != DATA_SOURCE_BINANCE_REST:
        issues.append(IssueSpec("INVALID_DATA_SOURCE", "Kline 数据来源不是 binance_rest", kline.open_time_utc))
    return issues


def _valid_ohlc(kline: Kline) -> bool:
    return (
        kline.open_price > 0
        and kline.high_price > 0
        and kline.low_price > 0
        and kline.close_price > 0
        and kline.high_price >= kline.low_price
        and kline.high_price >= kline.open_price
        and kline.high_price >= kline.close_price
        and kline.low_price <= kline.open_price
        and kline.low_price <= kline.close_price
    )


def _collect_conflict_issues(*, timeframe: str, start_open: datetime, end_open: datetime) -> list[IssueSpec]:
    domain = configured_collection_domain()
    conflicts = DataConflict.objects.filter(
        exchange=domain.exchange,
        market_type=domain.market_type,
        symbol=domain.symbol,
        timeframe=timeframe,
        open_time_utc__gte=start_open,
        open_time_utc__lte=end_open,
        status="active",
    )
    return [IssueSpec("DATA_CONFLICT", "目标窗口存在未处理数据冲突", conflict.open_time_utc) for conflict in conflicts]


def _create_backfill_request_if_needed(result: DataQualityResult, issues: list[IssueSpec]) -> BackfillRequest | None:
    missing_times = sorted({issue.open_time_utc for issue in issues if issue.backfillable and issue.open_time_utc})
    if not missing_times:
        return None
    business_key = build_idempotency_key(
        "backfill_request",
        result.exchange,
        result.market_type,
        result.symbol,
        result.timeframe,
        "gap_backfill",
        ",".join(time.isoformat() for time in missing_times),
        result.id,
    )
    request, _created = BackfillRequest.objects.get_or_create(
        business_key=business_key,
        defaults={
            "source_module": "DataQuality",
            "source_object_type": "DataQualityResult",
            "source_object_id": str(result.id),
            "exchange": result.exchange,
            "market_type": result.market_type,
            "symbol": result.symbol,
            "timeframe": result.timeframe,
            "backfill_mode": "gap_backfill",
            "requested_start_open_time_utc": missing_times[0],
            "requested_end_open_time_utc": missing_times[-1],
            "missing_open_times": [time.isoformat() for time in missing_times],
            "reason_code": "quality_backfillable_issues",
            "trace_id": result.trace_id,
            "trigger_source": result.trigger_source,
        },
    )
    return request


def _result_from_quality(result: DataQualityResult) -> ServiceResult:
    status = ResultStatus.SUCCEEDED if result.status == CommonStatus.PASS else ResultStatus.BLOCKED
    return ServiceResult(
        status=status,
        reason_code=result.reason_code,
        message=f"DataQualityResult {result.status}",
        trace_id=result.trace_id,
        trigger_source=result.trigger_source,
        data={
            "data_quality_result_id": result.id,
            "status": result.status,
            "allows_downstream": result.allows_downstream,
            "issue_count": result.issue_count,
            "expected_count": result.expected_count,
            "actual_count": result.actual_count,
        },
    )


def _dry_result(
    trace_id: str,
    trigger_source: str,
    status: str,
    issues: list[IssueSpec],
    expected_times: list[datetime],
    klines: list[Kline],
) -> ServiceResult:
    return ServiceResult(
        ResultStatus.SUCCEEDED if status == CommonStatus.PASS else ResultStatus.BLOCKED,
        "dry_run_preview",
        "DataQuality dry-run 未写入正式结果",
        trace_id,
        trigger_source,
        data={
            "status": status,
            "issue_types": [issue.issue_type for issue in issues],
            "expected_count": len(expected_times),
            "actual_count": len(klines),
        },
    )
