"""MarketData 模块：DataBackfill 命令入口；只调用 service，不直接访问 Binance，不涉及交易执行。"""

from __future__ import annotations

from datetime import datetime

from django.core.management.base import BaseCommand, CommandParser

from apps.foundation.context import make_trace_id
from apps.foundation.idempotency import build_idempotency_key
from apps.market_data.services.backfill import run_data_backfill


def _parse_dt(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


class Command(BaseCommand):
    help = "触发 DataBackfill；真实外部访问仍受 Gateway 配置保护。"

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--timeframe", required=True, choices=["4h", "1d"])
        parser.add_argument("--mode", required=True)
        parser.add_argument("--start-open-time-utc", required=True)
        parser.add_argument("--end-open-time-utc", required=True)
        parser.add_argument("--missing-open-time-utc", action="append", default=[])
        parser.add_argument("--backfill-request-id", type=int)
        parser.add_argument("--business-request-key")
        parser.add_argument("--trace-id")
        parser.add_argument("--operator-id", default="")
        parser.add_argument("--reason", default="")
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument("--confirm-write", action="store_true")

    def handle(self, *args, **options) -> None:
        trace_id = options["trace_id"] or make_trace_id()
        key = options["business_request_key"] or build_idempotency_key(
            "run_data_backfill",
            options["timeframe"],
            options["mode"],
            options["start_open_time_utc"],
            options["end_open_time_utc"],
            ",".join(options["missing_open_time_utc"]),
        )
        result = run_data_backfill(
            timeframe=options["timeframe"],
            backfill_mode=options["mode"],
            start_open_time_utc=_parse_dt(options["start_open_time_utc"]),
            end_open_time_utc=_parse_dt(options["end_open_time_utc"]),
            missing_open_times=[_parse_dt(value) for value in options["missing_open_time_utc"]],
            business_request_key=key,
            trace_id=trace_id,
            trigger_source="management_command",
            backfill_request_id=options.get("backfill_request_id"),
            dry_run=options["dry_run"],
            confirm_write=options["confirm_write"],
            operator_id=options["operator_id"],
            reason=options["reason"],
        )
        self.stdout.write(str(result))

