"""MarketRegime 模块：安全占位初始化入口；当前不创建默认正式 Definition，不访问外部服务，不执行交易。"""

from __future__ import annotations

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "MarketRegime 当前没有已指定正式算法，因此不自动创建默认 Definition"

    def handle(self, *args, **options):
        self.stdout.write(
            self.style.WARNING(
                "MarketRegime 未指定正式算法和 regime_code 集合；"
                "本命令不会创建默认 MarketRegimeDefinition。"
            )
        )
