"""MarketData 模块：DataCollection 命令入口；只调用 service，不直接访问 Binance，不涉及交易执行。"""

from __future__ import annotations

from datetime import datetime

from django.core.management.base import BaseCommand, CommandParser

from apps.foundation.context import make_trace_id
from apps.foundation.idempotency import build_idempotency_key
from apps.market_data.services.collection import collect_klines


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


class Command(BaseCommand):
    help = "触发 DataCollection 拉取已收盘 Kline；真实外部访问仍受 Gateway 配置保护。"

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--timeframe", required=True, choices=["4h", "1d"])
        parser.add_argument("--mode", default="latest_closed")
        parser.add_argument("--start-open-time-utc")
        parser.add_argument("--end-open-time-utc")
        parser.add_argument("--lookback-count", type=int)
        parser.add_argument("--business-request-key")
        parser.add_argument("--trace-id")
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options) -> None:
        trace_id = options["trace_id"] or make_trace_id()
        key = options["business_request_key"] or build_idempotency_key(
            "collect_klines",
            options["timeframe"],
            options["mode"],
            options.get("start_open_time_utc") or "",
            options.get("end_open_time_utc") or "",
            options.get("lookback_count") or "",
        )
        result = collect_klines(
            timeframe=options["timeframe"],
            collection_mode=options["mode"],
            business_request_key=key,
            trace_id=trace_id,
            trigger_source="management_command",
            start_open_time_utc=_parse_dt(options.get("start_open_time_utc")),
            end_open_time_utc=_parse_dt(options.get("end_open_time_utc")),
            lookback_count=options.get("lookback_count"),
            dry_run=options["dry_run"],
        )
        self.stdout.write(str(result))

