"""MarketData 模块：Celery 薄入口；不写业务逻辑，不直接访问 Binance，不涉及交易执行。"""

from __future__ import annotations

from datetime import datetime

from celery import shared_task

from .services.backfill import run_data_backfill
from .services.collection import collect_klines
from .services.quality import check_data_quality
from .services.snapshot import create_market_snapshot


def _parse_dt(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


@shared_task(name="market_data.collect_klines")
def collect_klines_task(**kwargs):
    for key in ("start_open_time_utc", "end_open_time_utc"):
        if kwargs.get(key):
            kwargs[key] = _parse_dt(kwargs[key])
    return collect_klines(**kwargs).__dict__


@shared_task(name="market_data.check_data_quality")
def check_data_quality_task(**kwargs):
    for key in (
        "check_start_open_time_utc",
        "check_end_open_time_utc",
        "quality_reference_time_utc",
        "expected_latest_open_time_utc",
    ):
        if kwargs.get(key):
            kwargs[key] = _parse_dt(kwargs[key])
    return check_data_quality(**kwargs).__dict__


@shared_task(name="market_data.run_data_backfill")
def run_data_backfill_task(**kwargs):
    for key in ("start_open_time_utc", "end_open_time_utc"):
        if kwargs.get(key):
            kwargs[key] = _parse_dt(kwargs[key])
    if kwargs.get("missing_open_times"):
        kwargs["missing_open_times"] = [_parse_dt(value) for value in kwargs["missing_open_times"]]
    return run_data_backfill(**kwargs).__dict__


@shared_task(name="market_data.create_market_snapshot")
def create_market_snapshot_task(**kwargs):
    for key in ("analysis_close_time_utc", "analysis_reference_time_utc"):
        if kwargs.get(key):
            kwargs[key] = _parse_dt(kwargs[key])
    return create_market_snapshot(**kwargs).__dict__

