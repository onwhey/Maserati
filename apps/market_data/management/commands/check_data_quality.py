"""MarketData 模块：DataQuality 命令入口；只调用 service，不请求 Binance，不涉及交易执行。"""

from __future__ import annotations

from datetime import datetime

from django.core.management.base import BaseCommand, CommandParser

from apps.foundation.context import make_trace_id
from apps.foundation.idempotency import build_idempotency_key
from apps.market_data.services.quality import check_data_quality


def _parse_dt(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


class Command(BaseCommand):
    help = "触发 DataQuality 检查已落库 Kline。"

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--timeframe", required=True, choices=["4h", "1d"])
        parser.add_argument("--start-open-time-utc", required=True)
        parser.add_argument("--end-open-time-utc", required=True)
        parser.add_argument("--quality-reference-time-utc", required=True)
        parser.add_argument("--expected-latest-open-time-utc")
        parser.add_argument("--business-request-key")
        parser.add_argument("--trace-id")
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options) -> None:
        trace_id = options["trace_id"] or make_trace_id()
        key = options["business_request_key"] or build_idempotency_key(
            "check_data_quality",
            options["timeframe"],
            options["start_open_time_utc"],
            options["end_open_time_utc"],
        )
        result = check_data_quality(
            timeframe=options["timeframe"],
            check_start_open_time_utc=_parse_dt(options["start_open_time_utc"]),
            check_end_open_time_utc=_parse_dt(options["end_open_time_utc"]),
            quality_reference_time_utc=_parse_dt(options["quality_reference_time_utc"]),
            expected_latest_open_time_utc=_parse_dt(options["expected_latest_open_time_utc"])
            if options.get("expected_latest_open_time_utc")
            else None,
            business_request_key=key,
            trace_id=trace_id,
            trigger_source="management_command",
            dry_run=options["dry_run"],
        )
        self.stdout.write(str(result))

