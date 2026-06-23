"""MarketData 模块：MarketSnapshot 命令入口；只调用 service，不请求 Binance，不涉及交易执行。"""

from __future__ import annotations

from datetime import datetime

from django.core.management.base import BaseCommand, CommandParser

from apps.foundation.context import make_trace_id
from apps.foundation.idempotency import build_idempotency_key
from apps.market_data.services.snapshot import create_market_snapshot


def _parse_dt(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


class Command(BaseCommand):
    help = "创建 MarketSnapshot；只消费已 PASS 的 DataQualityResult。"

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--analysis-close-time-utc", required=True)
        parser.add_argument("--analysis-reference-time-utc", required=True)
        parser.add_argument("--lookback-4h-count", type=int)
        parser.add_argument("--lookback-1d-count", type=int)
        parser.add_argument("--business-request-key")
        parser.add_argument("--trace-id")
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options) -> None:
        trace_id = options["trace_id"] or make_trace_id()
        key = options["business_request_key"] or build_idempotency_key(
            "create_market_snapshot",
            options["analysis_close_time_utc"],
            options.get("lookback_4h_count") or "",
            options.get("lookback_1d_count") or "",
        )
        result = create_market_snapshot(
            analysis_close_time_utc=_parse_dt(options["analysis_close_time_utc"]),
            analysis_reference_time_utc=_parse_dt(options["analysis_reference_time_utc"]),
            lookback_4h_count=options.get("lookback_4h_count"),
            lookback_1d_count=options.get("lookback_1d_count"),
            business_request_key=key,
            trace_id=trace_id,
            trigger_source="management_command",
            dry_run=options["dry_run"],
        )
        self.stdout.write(str(result))

