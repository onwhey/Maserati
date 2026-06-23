"""RuntimeConfig 模块：保存真实交易运行开关；读写数据库，不访问外部服务，不涉及交易执行。"""

from __future__ import annotations

from django.db import models


class RuntimeTradingConfig(models.Model):
    config_key = models.CharField("配置键", max_length=80, unique=True, default="default")
    runtime_real_trading_permission = models.BooleanField("MySQL 真实交易运行开关", default=False)
    updated_by = models.CharField("最后更新人", max_length=120, blank=True)
    updated_reason = models.CharField("最后更新原因", max_length=500, blank=True)
    created_at_utc = models.DateTimeField("创建 UTC 时间", auto_now_add=True)
    updated_at_utc = models.DateTimeField("更新 UTC 时间", auto_now=True)

    class Meta:
        verbose_name = "真实交易运行配置"
        verbose_name_plural = "真实交易运行配置"

    def __str__(self) -> str:
        return self.config_key

