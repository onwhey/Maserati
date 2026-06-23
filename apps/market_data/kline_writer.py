"""MarketData 模块：Kline 幂等写入与冲突检测；读写数据库，不访问 Redis，不访问外部服务，不涉及交易执行。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from django.db import IntegrityError, transaction

from apps.foundation.idempotency import build_idempotency_key

from .domain import NormalizedKline, kline_core_hash
from .models import BackfillRun, DataCollectionRun, DataConflict, Kline


@dataclass(frozen=True)
class KlineWriteOutcome:
    action: str
    kline: Kline | None = None
    conflict: DataConflict | None = None


def write_kline_idempotently(
    *,
    normalized: NormalizedKline,
    source_module: str,
    trace_id: str,
    trigger_source: str,
    source_collection_run: DataCollectionRun | None = None,
    source_backfill_run: BackfillRun | None = None,
) -> KlineWriteOutcome:
    try:
        with transaction.atomic():
            existing = (
                Kline.objects.select_for_update()
                .filter(
                    exchange=normalized.exchange,
                    market_type=normalized.market_type,
                    symbol=normalized.symbol,
                    timeframe=normalized.timeframe,
                    open_time_utc=normalized.open_time_utc,
                )
                .first()
            )
            if existing:
                if _same_core(existing, normalized):
                    return KlineWriteOutcome(action="skipped_existing", kline=existing)
                conflict = _record_conflict(
                    existing=existing,
                    incoming=normalized,
                    source_module=source_module,
                    trace_id=trace_id,
                    trigger_source=trigger_source,
                    source_collection_run=source_collection_run,
                    source_backfill_run=source_backfill_run,
                )
                return KlineWriteOutcome(action="conflict", conflict=conflict)
            kline = Kline.objects.create(
                exchange=normalized.exchange,
                market_type=normalized.market_type,
                symbol=normalized.symbol,
                timeframe=normalized.timeframe,
                open_time_utc=normalized.open_time_utc,
                close_time_utc=normalized.close_time_utc,
                open_price=normalized.open_price,
                high_price=normalized.high_price,
                low_price=normalized.low_price,
                close_price=normalized.close_price,
                volume=normalized.volume,
                quote_volume=normalized.quote_volume,
                trade_count=normalized.trade_count,
                data_source=normalized.data_source,
                source_collection_run=source_collection_run,
                source_backfill_run=source_backfill_run,
            )
        return KlineWriteOutcome(action="inserted", kline=kline)
    except IntegrityError:
        existing_after_race = Kline.objects.get(
            exchange=normalized.exchange,
            market_type=normalized.market_type,
            symbol=normalized.symbol,
            timeframe=normalized.timeframe,
            open_time_utc=normalized.open_time_utc,
        )
        if _same_core(existing_after_race, normalized):
            return KlineWriteOutcome(action="skipped_existing", kline=existing_after_race)
        conflict = _record_conflict(
            existing=existing_after_race,
            incoming=normalized,
            source_module=source_module,
            trace_id=trace_id,
            trigger_source=trigger_source,
            source_collection_run=source_collection_run,
            source_backfill_run=source_backfill_run,
        )
        return KlineWriteOutcome(action="conflict", conflict=conflict)


def _same_core(existing: Kline, incoming: NormalizedKline) -> bool:
    return (
        existing.close_time_utc == incoming.close_time_utc
        and existing.open_price == incoming.open_price
        and existing.high_price == incoming.high_price
        and existing.low_price == incoming.low_price
        and existing.close_price == incoming.close_price
        and existing.volume == incoming.volume
        and existing.quote_volume == incoming.quote_volume
        and existing.trade_count == incoming.trade_count
    )


def _record_conflict(
    *,
    existing: Kline,
    incoming: NormalizedKline,
    source_module: str,
    trace_id: str,
    trigger_source: str,
    source_collection_run: DataCollectionRun | None,
    source_backfill_run: BackfillRun | None,
) -> DataConflict:
    source_object_type, source_object_id = _source_object_ref(source_collection_run, source_backfill_run)
    conflict_key = build_idempotency_key(
        "data_conflict",
        existing.exchange,
        existing.market_type,
        existing.symbol,
        existing.timeframe,
        existing.open_time_utc.isoformat(),
        kline_core_hash(existing),
        kline_core_hash(incoming),
    )
    conflict, _created = DataConflict.objects.get_or_create(
        conflict_key=conflict_key,
        defaults={
            "exchange": existing.exchange,
            "market_type": existing.market_type,
            "symbol": existing.symbol,
            "timeframe": existing.timeframe,
            "open_time_utc": existing.open_time_utc,
            "source_module": source_module,
            "source_object_type": source_object_type,
            "source_object_id": source_object_id,
            "existing_value_hash": kline_core_hash(existing),
            "incoming_value_hash": kline_core_hash(incoming),
            "payload_summary": _conflict_summary(existing, incoming),
            "trace_id": trace_id,
            "trigger_source": trigger_source,
        },
    )
    return conflict


def _source_object_ref(
    source_collection_run: DataCollectionRun | None,
    source_backfill_run: BackfillRun | None,
) -> tuple[str, str]:
    if source_collection_run:
        return "DataCollectionRun", str(source_collection_run.id)
    if source_backfill_run:
        return "BackfillRun", str(source_backfill_run.id)
    return "", ""


def _conflict_summary(existing: Kline, incoming: NormalizedKline) -> dict[str, Any]:
    return {
        "existing": {
            "open": str(existing.open_price),
            "high": str(existing.high_price),
            "low": str(existing.low_price),
            "close": str(existing.close_price),
            "volume": str(existing.volume),
            "quote_volume": str(existing.quote_volume),
            "trade_count": existing.trade_count,
        },
        "incoming": {
            "open": str(incoming.open_price),
            "high": str(incoming.high_price),
            "low": str(incoming.low_price),
            "close": str(incoming.close_price),
            "volume": str(incoming.volume),
            "quote_volume": str(incoming.quote_volume),
            "trade_count": incoming.trade_count,
        },
    }
