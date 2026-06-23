"""MarketData 模块：行情时间与 Kline 标准化规则；不读写数据库，不访问外部服务，不涉及交易执行。"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from django.conf import settings


EXCHANGE_BINANCE = "binance"
MARKET_TYPE_USDS_M = "usds_m_futures"
SYMBOL_BTCUSDT = "BTCUSDT"
TIMEFRAME_4H = "4h"
TIMEFRAME_1D = "1d"
DATA_SOURCE_BINANCE_REST = "binance_rest"

TIMEFRAME_DELTAS = {
    TIMEFRAME_4H: timedelta(hours=4),
    TIMEFRAME_1D: timedelta(days=1),
}

BINANCE_INTERVALS = {
    TIMEFRAME_4H: "4h",
    TIMEFRAME_1D: "1d",
}


@dataclass(frozen=True)
class CollectionDomain:
    exchange: str
    market_type: str
    symbol: str
    timeframes: tuple[str, ...]


@dataclass(frozen=True)
class NormalizedKline:
    exchange: str
    market_type: str
    symbol: str
    timeframe: str
    open_time_utc: datetime
    close_time_utc: datetime
    open_price: Decimal
    high_price: Decimal
    low_price: Decimal
    close_price: Decimal
    volume: Decimal
    quote_volume: Decimal
    trade_count: int
    data_source: str = DATA_SOURCE_BINANCE_REST


def configured_collection_domain() -> CollectionDomain:
    return CollectionDomain(
        exchange=getattr(settings, "DATA_COLLECTION_EXCHANGE", EXCHANGE_BINANCE),
        market_type=getattr(settings, "DATA_COLLECTION_MARKET_TYPE", MARKET_TYPE_USDS_M),
        symbol=getattr(settings, "DATA_COLLECTION_SYMBOL", SYMBOL_BTCUSDT),
        timeframes=tuple(getattr(settings, "DATA_COLLECTION_TIMEFRAMES", [TIMEFRAME_4H, TIMEFRAME_1D])),
    )


def ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("业务时间必须带 UTC timezone")
    return value.astimezone(UTC)


def timeframe_delta(timeframe: str) -> timedelta:
    if timeframe not in TIMEFRAME_DELTAS:
        raise ValueError(f"不支持的 Kline 周期：{timeframe}")
    return TIMEFRAME_DELTAS[timeframe]


def binance_interval(timeframe: str) -> str:
    if timeframe not in BINANCE_INTERVALS:
        raise ValueError(f"不支持的 Binance Kline 周期：{timeframe}")
    return BINANCE_INTERVALS[timeframe]


def is_timeframe_boundary(value: datetime, timeframe: str) -> bool:
    utc_value = ensure_utc(value)
    if timeframe == TIMEFRAME_4H:
        return utc_value.minute == 0 and utc_value.second == 0 and utc_value.microsecond == 0 and utc_value.hour % 4 == 0
    if timeframe == TIMEFRAME_1D:
        return (
            utc_value.hour == 0
            and utc_value.minute == 0
            and utc_value.second == 0
            and utc_value.microsecond == 0
        )
    return False


def expected_open_times(start_open_time_utc: datetime, end_open_time_utc: datetime, timeframe: str) -> list[datetime]:
    start = ensure_utc(start_open_time_utc)
    end = ensure_utc(end_open_time_utc)
    if start > end:
        raise ValueError("开始 open_time 不能晚于结束 open_time")
    step = timeframe_delta(timeframe)
    current = start
    values: list[datetime] = []
    while current <= end:
        values.append(current)
        current += step
    return values


def latest_closed_open_time(reference_time_utc: datetime, timeframe: str) -> datetime:
    reference = ensure_utc(reference_time_utc)
    step = timeframe_delta(timeframe)
    if timeframe == TIMEFRAME_4H:
        boundary_hour = (reference.hour // 4) * 4
        boundary = reference.replace(hour=boundary_hour, minute=0, second=0, microsecond=0)
    elif timeframe == TIMEFRAME_1D:
        boundary = reference.replace(hour=0, minute=0, second=0, microsecond=0)
    else:
        raise ValueError(f"不支持的 Kline 周期：{timeframe}")
    if reference > boundary:
        return boundary - step
    return boundary - (step * 2)


def normalize_binance_kline(
    *,
    raw: list[Any],
    exchange: str,
    market_type: str,
    symbol: str,
    timeframe: str,
) -> NormalizedKline:
    if len(raw) < 11:
        raise ValueError("Binance Kline payload 字段不足")
    open_time = datetime.fromtimestamp(int(raw[0]) / 1000, tz=UTC)
    close_time = datetime.fromtimestamp((int(raw[6]) + 1) / 1000, tz=UTC)
    return NormalizedKline(
        exchange=exchange,
        market_type=market_type,
        symbol=symbol,
        timeframe=timeframe,
        open_time_utc=open_time,
        close_time_utc=close_time,
        open_price=_decimal(raw[1]),
        high_price=_decimal(raw[2]),
        low_price=_decimal(raw[3]),
        close_price=_decimal(raw[4]),
        volume=_decimal(raw[5]),
        quote_volume=_decimal(raw[7]),
        trade_count=int(raw[8]),
    )


def kline_core_hash(kline: NormalizedKline | Any) -> str:
    fields = [
        kline.open_time_utc.isoformat(),
        kline.close_time_utc.isoformat(),
        str(kline.open_price),
        str(kline.high_price),
        str(kline.low_price),
        str(kline.close_price),
        str(kline.volume),
        str(kline.quote_volume),
        str(kline.trade_count),
    ]
    return hashlib.sha256("|".join(fields).encode("utf-8")).hexdigest()


def is_closed_kline(kline: NormalizedKline, *, server_time_utc: datetime) -> bool:
    return ensure_utc(server_time_utc) > ensure_utc(kline.close_time_utc)


def _decimal(value: Any) -> Decimal:
    try:
        return Decimal(str(value))
    except InvalidOperation as exc:
        raise ValueError(f"无法转换 Decimal：{value}") from exc

