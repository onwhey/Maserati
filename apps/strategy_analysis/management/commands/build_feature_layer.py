"""FeatureLayer 模块：人工调用正式 service 生成 FeatureSet。

负责：解析人工命令参数、计算版本包特征切片指纹、调用 FeatureLayerService。
不负责：计算具体特征算法、生成原子信号、生成交易信号、生成目标仓位或订单。
读写数据库：通过 FeatureLayerService 写入 FeatureSet / FeatureValue。
访问 Redis：不涉及。
访问外部服务：不涉及。
发送 Hermes：不涉及。
调用大模型：不涉及。
涉及交易执行：不涉及。
允许真实交易：不涉及真实交易。
"""

from __future__ import annotations

import json

from django.core.management.base import BaseCommand

from apps.strategy_analysis.models import ReleaseItemComponentType, StrategyAnalysisRelease
from apps.strategy_analysis.services.feature_layer import build_feature_set
from apps.strategy_analysis.services.release import calculate_definition_set_hash


class Command(BaseCommand):
    help = "根据明确 MarketSnapshot 和冻结版本包构建 FeatureSet"

    def add_arguments(self, parser):
        parser.add_argument("--market-snapshot-id", type=int, required=True)
        parser.add_argument("--strategy-analysis-release-id", type=int, required=True)
        parser.add_argument("--strategy-analysis-release-hash", required=True)
        parser.add_argument("--business-request-key", required=True)
        parser.add_argument("--trace-id", required=True)
        parser.add_argument("--trigger-source", default="manual")
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        release = StrategyAnalysisRelease.objects.get(id=options["strategy_analysis_release_id"])
        items = tuple(
            release.items.filter(component_type=ReleaseItemComponentType.FEATURE_DEFINITION).order_by(
                "sort_order", "component_code", "id"
            )
        )
        result = build_feature_set(
            market_snapshot_id=options["market_snapshot_id"],
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
