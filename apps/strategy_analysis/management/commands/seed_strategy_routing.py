"""StrategyRouting 模块：安全零变更初始化入口。

当前不读写数据库或 Redis，不创建策略、Policy 或 Rule，不访问外部服务，不发送 Hermes，不调用大模型，
不执行策略、订单或真实交易。
"""

from __future__ import annotations

import json

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "StrategyRouting 当前没有已确认策略与路由模板，因此不自动创建配置"

    def handle(self, *args, **options):
        self.stdout.write(
            json.dumps(
                {
                    "created_policy_count": 0,
                    "created_rule_count": 0,
                    "created_strategy_definition_count": 0,
                    "reason": "尚未指定正式 StrategyDefinition 和路由映射，不创建默认配置",
                },
                ensure_ascii=False,
            )
        )
