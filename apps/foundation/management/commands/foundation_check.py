"""项目底座模块：基础健康检查命令；只读检查，不访问外部服务，不涉及交易执行。"""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from apps.foundation.health import run_foundation_health_checks


class Command(BaseCommand):
    help = "检查阶段 0 项目底座：Django、数据库、迁移、Redis 配置、Celery 与真实交易硬权限。"

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--skip-redis-ping",
            action="store_true",
            help="只检查 Redis 配置，不实际 ping Redis 服务。",
        )

    def handle(self, *args, **options) -> None:
        items = run_foundation_health_checks(check_redis_ping=not options["skip_redis_ping"])
        for item in items:
            marker = "OK" if item.passed else "FAIL"
            self.stdout.write(f"[{marker}] {item.name}: {item.message}")

        failed = [item for item in items if not item.passed]
        if failed:
            raise CommandError(f"阶段 0 底座检查失败：{len(failed)} 项未通过")

        self.stdout.write(self.style.SUCCESS("阶段 0 底座检查通过"))

