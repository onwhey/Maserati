"""RuntimeConfig 模块：查看真实交易权限；只读数据库，不访问外部服务，不涉及交易执行。"""

from __future__ import annotations

from django.core.management.base import BaseCommand

from apps.runtime_config.services import get_effective_real_trading_permission


class Command(BaseCommand):
    help = "查看真实交易最终权限：部署级硬权限 AND MySQL 运行开关。"

    def handle(self, *args, **options) -> None:
        permission = get_effective_real_trading_permission()
        self.stdout.write(f"deployment_allowed: {permission.deployment_allowed}")
        self.stdout.write(f"runtime_allowed: {permission.runtime_allowed}")
        self.stdout.write(f"effective_allowed: {permission.effective_allowed}")
        self.stdout.write(f"fail_closed: {permission.fail_closed}")
        self.stdout.write(f"reason_code: {permission.reason_code}")

