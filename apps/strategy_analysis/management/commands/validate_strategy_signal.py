"""StrategySignalQuality 模块：解析人工参数并调用正式质量检查 service。
入口不承载质量规则或业务判断；不直接读写数据库或 Redis，不访问外部服务，不发送 Hermes，不调用大模型。
不生成目标仓位或订单，不涉及交易执行或真实交易；正式业务对象与 AlertEvent 仅由 service 按合同写入。
"""

from __future__ import annotations

import json

from django.core.management.base import BaseCommand, CommandError
from django.utils.dateparse import parse_datetime

from apps.strategy_analysis.models import ReleaseItemComponentType, StrategyAnalysisRelease
from apps.strategy_analysis.services.strategy_signal_quality import validate_strategy_signal


class Command(BaseCommand):
    help = "根据明确 StrategySignal 和冻结版本包执行 StrategySignalQuality 检查"

    def add_arguments(self, parser):
        parser.add_argument("--strategy-signal-id", type=int, required=True)
        parser.add_argument("--strategy-analysis-release-id", type=int, required=True)
        parser.add_argument("--strategy-analysis-release-hash", required=True)
        parser.add_argument("--expected-quality-rule-set-hash", default="")
        parser.add_argument("--business-request-key", required=True)
        parser.add_argument("--validation-mode", default="live", choices=["live", "replay", "backfill", "manual"])
        parser.add_argument("--reference-time-utc")
        parser.add_argument("--trace-id", required=True)
        parser.add_argument("--trigger-source", default="management_command")
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        reference_time = None
        if options["reference_time_utc"]:
            reference_time = parse_datetime(options["reference_time_utc"])
            if reference_time is None:
                raise CommandError("--reference-time-utc 必须是合法 ISO datetime")
        expected_quality_rule_set_hash = options["expected_quality_rule_set_hash"]
        if not expected_quality_rule_set_hash:
            release = StrategyAnalysisRelease.objects.get(id=options["strategy_analysis_release_id"])
            quality_items = tuple(
                release.items.filter(component_type=ReleaseItemComponentType.STRATEGY_SIGNAL_QUALITY_RULE_SET)
                .order_by("sort_order", "component_code", "id")
            )
            if len(quality_items) != 1:
                raise CommandError("版本包必须且只能包含一个策略信号质量规则集")
            expected_quality_rule_set_hash = quality_items[0].definition_hash
        result = validate_strategy_signal(
            strategy_signal_id=options["strategy_signal_id"],
            strategy_analysis_release_id=options["strategy_analysis_release_id"],
            strategy_analysis_release_hash=options["strategy_analysis_release_hash"],
            expected_quality_rule_set_hash=expected_quality_rule_set_hash,
            business_request_key=options["business_request_key"],
            validation_mode=options["validation_mode"],
            reference_time_utc=reference_time,
            dry_run=options["dry_run"],
            trace_id=options["trace_id"],
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
