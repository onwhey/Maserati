"""StrategyAnalysis 模块：策略分析链路批量回放命令入口。

负责：解析人工命令参数，调用 replay service，并输出 JSON 摘要。
不负责：计算策略算法、修改订单、风控审批、真实下单、订单同步或复盘结论。
读写数据库：仅通过 replay service 间接写入行情质检、策略分析链路事实。
访问 Redis：不涉及。
访问外部服务：不涉及。
发送 Hermes：不涉及。
调用大模型：不涉及。
涉及交易执行：不涉及。
允许真实交易：不涉及真实交易。
"""

from __future__ import annotations

import json
from datetime import datetime

from django.core.management.base import BaseCommand, CommandError

from apps.foundation.context import make_trace_id
from apps.market_data.domain import TIMEFRAME_4H, ensure_utc, timeframe_delta
from apps.strategy_analysis.services.replay import replay_strategy_analysis_chain


class Command(BaseCommand):
    help = "批量回放 FeatureLayer 到 DecisionSnapshot 的策略分析链路；不进入订单链路。"

    def add_arguments(self, parser):
        parser.add_argument("--analysis-close-time-utc", action="append", default=[])
        parser.add_argument("--analysis-close-times", default="")
        parser.add_argument("--end-analysis-close-time-utc")
        parser.add_argument("--period-count", type=int, default=0)
        parser.add_argument("--strategy-analysis-release-id", type=int)
        parser.add_argument("--strategy-analysis-release-hash", default="")
        parser.add_argument("--lookback-4h-count", type=int, default=500)
        parser.add_argument("--lookback-1d-count", type=int, default=500)
        parser.add_argument("--business-request-prefix", default="strategy-analysis-replay")
        parser.add_argument("--trace-id")
        parser.add_argument("--trigger-source", default="management_command")

    def handle(self, *args, **options):
        analysis_close_times = _resolve_analysis_close_times(options)
        result = replay_strategy_analysis_chain(
            analysis_close_times=analysis_close_times,
            strategy_analysis_release_id=options["strategy_analysis_release_id"],
            strategy_analysis_release_hash=options["strategy_analysis_release_hash"],
            lookback_4h_count=options["lookback_4h_count"],
            lookback_1d_count=options["lookback_1d_count"],
            business_request_prefix=options["business_request_prefix"],
            trace_id=options["trace_id"] or make_trace_id(),
            trigger_source=options["trigger_source"],
        )
        self.stdout.write(
            json.dumps(
                {
                    "status": result.status,
                    "reason_code": result.reason_code,
                    "message": result.message,
                    "trace_id": result.trace_id,
                    "data": result.data,
                },
                ensure_ascii=False,
                default=str,
            )
        )


def _resolve_analysis_close_times(options) -> list[datetime]:
    explicit_values: list[str] = []
    explicit_values.extend(options["analysis_close_time_utc"] or [])
    if options["analysis_close_times"]:
        explicit_values.extend(part.strip() for part in options["analysis_close_times"].split(",") if part.strip())
    if explicit_values and (options["end_analysis_close_time_utc"] or options["period_count"]):
        raise CommandError("明确时间点和 end-analysis-close-time-utc/period-count 只能二选一")
    if explicit_values:
        return [_parse_utc(value) for value in explicit_values]
    if options["end_analysis_close_time_utc"]:
        if options["period_count"] <= 0:
            raise CommandError("使用 --end-analysis-close-time-utc 时必须提供大于 0 的 --period-count")
        end = _parse_utc(options["end_analysis_close_time_utc"])
        step = timeframe_delta(TIMEFRAME_4H)
        return [end - step * index for index in range(options["period_count"])]
    raise CommandError("必须提供 --analysis-close-time-utc / --analysis-close-times，或提供 --end-analysis-close-time-utc + --period-count")


def _parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return ensure_utc(parsed)
