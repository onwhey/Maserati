"""DomainSignal 模块：人工调用正式 service；不直接写业务状态、不访问外部服务、不执行交易。"""

from __future__ import annotations

import json

from django.core.management.base import BaseCommand

from apps.strategy_analysis.models import ReleaseItemComponentType, StrategyAnalysisRelease
from apps.strategy_analysis.services.domain_signal import build_domain_signals
from apps.strategy_analysis.services.release import calculate_definition_set_hash


class Command(BaseCommand):
    help = "根据明确 AtomicSignalSet 和冻结版本包构建 DomainSignalSet"

    def add_arguments(self, parser):
        parser.add_argument("--atomic-signal-set-id", type=int, required=True)
        parser.add_argument("--strategy-analysis-release-id", type=int, required=True)
        parser.add_argument("--strategy-analysis-release-hash", required=True)
        parser.add_argument("--business-request-key", required=True)
        parser.add_argument("--trace-id", required=True)
        parser.add_argument("--trigger-source", default="manual")
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        release = StrategyAnalysisRelease.objects.get(id=options["strategy_analysis_release_id"])
        items = tuple(
            release.items.filter(component_type=ReleaseItemComponentType.DOMAIN_SIGNAL_DEFINITION).order_by(
                "sort_order", "component_code", "id"
            )
        )
        result = build_domain_signals(
            atomic_signal_set_id=options["atomic_signal_set_id"],
            strategy_analysis_release_id=release.id,
            release_hash=options["strategy_analysis_release_hash"],
            expected_definition_set_hash=calculate_definition_set_hash(items),
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
