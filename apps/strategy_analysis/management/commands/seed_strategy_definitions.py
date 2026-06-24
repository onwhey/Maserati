"""StrategySignal 模块：安全零变更的策略定义初始化入口。

当前不读写数据库或 Redis，不发明策略、参数或算法，不访问外部服务，不发送 Hermes，不调用大模型，
不生成策略信号、目标仓位或订单，不涉及交易执行或真实交易。
"""

from __future__ import annotations

import json

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "当前没有已确认的正式策略算法模板，因此不自动创建 StrategyDefinition"

    def handle(self, *args, **options):
        self.stdout.write(
            json.dumps(
                {
                    "created_strategy_definition_count": 0,
                    "updated_strategy_definition_count": 0,
                    "reason": "尚未指定具体策略算法需求，不创建默认 StrategyDefinition",
                },
                ensure_ascii=False,
            )
        )
