"""StrategySignal 模块：解析人工参数并调用正式 StrategySignal service。

入口不承载策略算法或业务规则，不直接读写数据库或 Redis，不访问外部服务，不发送 Hermes，不调用大模型，
不生成目标仓位或订单，不涉及交易执行或真实交易；正式业务对象与 AlertEvent 仅由 service 按合同写入。
"""

from __future__ import annotations

import json

from django.core.management.base import BaseCommand

from apps.strategy_analysis.services.strategy_signal import generate_strategy_signal


class Command(BaseCommand):
    help = "根据明确 StrategyRouteDecision 和冻结版本包生成 StrategySignal"

    def add_arguments(self, parser):
        parser.add_argument("--strategy-route-decision-id", type=int, required=True)
        parser.add_argument("--strategy-analysis-release-id", type=int, required=True)
        parser.add_argument("--strategy-analysis-release-hash", required=True)
        parser.add_argument("--expected-strategy-definition-hash", required=True)
        parser.add_argument("--business-request-key", required=True)
        parser.add_argument("--trace-id", required=True)
        parser.add_argument("--trigger-source", default="management_command")
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        result = generate_strategy_signal(
            strategy_route_decision_id=options["strategy_route_decision_id"],
            strategy_analysis_release_id=options["strategy_analysis_release_id"],
            strategy_analysis_release_hash=options["strategy_analysis_release_hash"],
            expected_strategy_definition_hash=options["expected_strategy_definition_hash"],
            business_request_key=options["business_request_key"],
            trace_id=options["trace_id"],
            trigger_source=options["trigger_source"],
            dry_run=options["dry_run"],
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
