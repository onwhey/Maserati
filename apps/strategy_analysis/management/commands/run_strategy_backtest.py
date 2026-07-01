"""StrategyAnalysis 模块：策略收益回测命令入口。
负责：解析人工命令参数，调用 StrategyBacktest service，并输出 JSON 摘要。
不负责：计算策略算法、生成订单、风控审批、真实下单、订单同步、成交同步或复盘结论。
读写数据库：通过 service 间接读取 Kline，并在测试环境复用 replay service 写入策略分析链路事实。
访问 Redis：不涉及。
访问外部服务：不涉及；行情数据必须已经由 DataCollection 落库。
发送 Hermes：不涉及。
调用大模型：不涉及。
涉及交易执行：不涉及。
允许真实交易：不允许。
"""

from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal, InvalidOperation

from django.core.management.base import BaseCommand, CommandError

from apps.foundation.context import make_trace_id
from apps.market_data.domain import ensure_utc
from apps.strategy_analysis.services.backtest import (
    NO_TARGET_POLICY_FLAT,
    NO_TARGET_POLICY_HOLD,
    run_strategy_backtest,
)


class Command(BaseCommand):
    help = "运行测试环境策略收益回测；复用策略分析 replay，不进入订单链路。"

    def add_arguments(self, parser):
        parser.add_argument("--start-analysis-close-time-utc", required=True)
        parser.add_argument("--end-analysis-close-time-utc", required=True)
        parser.add_argument("--strategy-analysis-release-id", type=int)
        parser.add_argument("--strategy-analysis-release-hash", default="")
        parser.add_argument("--lookback-4h-count", type=int, default=500)
        parser.add_argument("--lookback-1d-count", type=int, default=500)
        parser.add_argument("--initial-equity", default="10000")
        parser.add_argument("--fee-rate", default="0.0004")
        parser.add_argument("--leverage", default="1")
        parser.add_argument(
            "--no-target-policy",
            choices=[NO_TARGET_POLICY_HOLD, NO_TARGET_POLICY_FLAT],
            default=NO_TARGET_POLICY_HOLD,
        )
        parser.add_argument("--business-request-prefix", default="strategy-backtest")
        parser.add_argument("--trace-id")
        parser.add_argument("--trigger-source", default="management_command")
        parser.add_argument("--output-mode", choices=["summary", "full"], default="summary")

    def handle(self, *args, **options):
        result = run_strategy_backtest(
            start_analysis_close_time_utc=_parse_utc(options["start_analysis_close_time_utc"]),
            end_analysis_close_time_utc=_parse_utc(options["end_analysis_close_time_utc"]),
            strategy_analysis_release_id=options["strategy_analysis_release_id"],
            strategy_analysis_release_hash=options["strategy_analysis_release_hash"],
            lookback_4h_count=options["lookback_4h_count"],
            lookback_1d_count=options["lookback_1d_count"],
            initial_equity=_parse_decimal(options["initial_equity"], "--initial-equity"),
            fee_rate=_parse_decimal(options["fee_rate"], "--fee-rate"),
            leverage=_parse_decimal(options["leverage"], "--leverage"),
            no_target_policy=options["no_target_policy"],
            business_request_prefix=options["business_request_prefix"],
            trace_id=options["trace_id"] or make_trace_id(),
            trigger_source=options["trigger_source"],
        )
        data = result.data
        if options["output_mode"] == "summary":
            data = _summary_data(data)
        self.stdout.write(
            json.dumps(
                {
                    "status": result.status,
                    "reason_code": result.reason_code,
                    "message": result.message,
                    "trace_id": result.trace_id,
                    "data": data,
                },
                ensure_ascii=False,
                default=str,
            )
        )


def _parse_utc(value: str) -> datetime:
    try:
        return ensure_utc(datetime.fromisoformat(value.replace("Z", "+00:00")))
    except ValueError as exc:
        raise CommandError(f"时间参数不是合法 UTC ISO 格式：{value}") from exc


def _parse_decimal(value: str, option_name: str) -> Decimal:
    try:
        return Decimal(str(value))
    except InvalidOperation as exc:
        raise CommandError(f"{option_name} 必须是合法数字") from exc


def _summary_data(data: dict) -> dict:
    periods = data.get("periods") or []
    return {
        "release_id": data.get("release_id"),
        "release_hash": data.get("release_hash"),
        "start_analysis_close_time_utc": data.get("start_analysis_close_time_utc"),
        "end_analysis_close_time_utc": data.get("end_analysis_close_time_utc"),
        "period_count": data.get("period_count"),
        "replay_status": data.get("replay_status"),
        "replay_reason_code": data.get("replay_reason_code"),
        "initial_equity": data.get("initial_equity"),
        "leverage": data.get("leverage"),
        "final_equity": data.get("final_equity"),
        "total_return_pct": data.get("total_return_pct"),
        "max_drawdown_pct": data.get("max_drawdown_pct"),
        "trade_count": data.get("trade_count"),
        "turnover_ratio": data.get("turnover_ratio"),
        "total_fee": data.get("total_fee"),
        "benchmark_buy_hold_return_pct": data.get("benchmark_buy_hold_return_pct"),
        "completed_count": data.get("completed_count"),
        "simulation_blocked_count": data.get("simulation_blocked_count"),
        "is_liquidated": data.get("is_liquidated"),
        "liquidation_period_index": data.get("liquidation_period_index"),
        "liquidation_analysis_close_time_utc": data.get("liquidation_analysis_close_time_utc"),
        "liquidation_price": data.get("liquidation_price"),
        "liquidation_reason_code": data.get("liquidation_reason_code"),
        "strategy_counts": data.get("strategy_counts"),
        "first_period": periods[0] if periods else {},
        "last_period": periods[-1] if periods else {},
    }
