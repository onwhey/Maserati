"""PerformanceMetrics 模块：定义后置账户绩效复盘结果。

负责：持久化相邻自动编排账户边界之间的绩效复盘结果。
不负责：请求 Binance、查询订单、查询成交、生成交易信号、调整策略、提交订单、释放锁。
读写数据库：写 PerformanceMetrics 自身结果，读取已落库事实由 service 完成。
访问 Redis：不涉及。
访问外部服务：不涉及。
发送 Hermes：不涉及；只允许通过 AlertEvent 记录审计事件。
调用大模型：不涉及。
涉及交易执行：不涉及。
允许真实交易：不允许。
"""

from __future__ import annotations

from django.db import models


class PerformanceCalculationStatus(models.TextChoices):
    CALCULATED = "calculated", "已计算"
    INSUFFICIENT_SNAPSHOT = "insufficient_snapshot", "快照不足"
    SKIPPED = "skipped", "已跳过"
    FAILED = "failed", "计算失败"


class OrchestrationRunPerformance(models.Model):
    start_orchestration_run = models.ForeignKey(
        "orchestration.OrchestrationRun",
        on_delete=models.PROTECT,
        related_name="performance_period_starts",
    )
    end_orchestration_run = models.ForeignKey(
        "orchestration.OrchestrationRun",
        on_delete=models.PROTECT,
        related_name="performance_period_ends",
    )
    period_start_utc = models.DateTimeField("周期开始 UTC")
    period_end_utc = models.DateTimeField("周期结束 UTC")
    exchange = models.CharField("交易所", max_length=40, default="binance")
    market_type = models.CharField("市场类型", max_length=40)
    account_domain = models.CharField("账户域", max_length=120)
    symbol = models.CharField("交易品种", max_length=40)

    start_binance_sync_run = models.ForeignKey(
        "binance_account_sync.BinanceSyncRun",
        on_delete=models.PROTECT,
        related_name="performance_period_starts",
    )
    end_binance_sync_run = models.ForeignKey(
        "binance_account_sync.BinanceSyncRun",
        on_delete=models.PROTECT,
        related_name="performance_period_ends",
    )
    start_account_snapshot = models.ForeignKey(
        "binance_account_sync.BinanceAccountSnapshot",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="performance_period_starts",
    )
    end_account_snapshot = models.ForeignKey(
        "binance_account_sync.BinanceAccountSnapshot",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="performance_period_ends",
    )
    start_position_snapshot = models.ForeignKey(
        "binance_account_sync.BinancePositionSnapshot",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="performance_period_starts",
    )
    end_position_snapshot = models.ForeignKey(
        "binance_account_sync.BinancePositionSnapshot",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="performance_period_ends",
    )

    formula_version = models.CharField("计算公式版本", max_length=80, default="p0_position_quantity_delta_v1")
    start_position_quantity = models.DecimalField("期初持仓数量", max_digits=38, decimal_places=18, null=True, blank=True)
    end_position_quantity = models.DecimalField("期末持仓数量", max_digits=38, decimal_places=18, null=True, blank=True)
    net_fill_quantity = models.DecimalField("周期内净成交数量", max_digits=38, decimal_places=18, default=0)
    cycle_floating_pnl = models.DecimalField("周期浮动表现", max_digits=38, decimal_places=18, null=True, blank=True)
    cycle_floating_pnl_pct = models.DecimalField("周期浮动表现比例", max_digits=38, decimal_places=18, null=True, blank=True)

    start_mark_price = models.DecimalField("期初 mark price", max_digits=38, decimal_places=18, null=True, blank=True)
    end_mark_price = models.DecimalField("期末 mark price", max_digits=38, decimal_places=18, null=True, blank=True)
    start_unrealized_pnl = models.DecimalField("期初未实现盈亏", max_digits=38, decimal_places=18, null=True, blank=True)
    end_unrealized_pnl = models.DecimalField("期末未实现盈亏", max_digits=38, decimal_places=18, null=True, blank=True)
    start_notional = models.DecimalField("期初名义价值", max_digits=38, decimal_places=18, null=True, blank=True)
    end_notional = models.DecimalField("期末名义价值", max_digits=38, decimal_places=18, null=True, blank=True)

    has_decision_snapshot = models.BooleanField("是否有关联目标仓位决策", default=False)
    has_order_plan = models.BooleanField("是否有关联订单计划", default=False)
    has_candidate_order_intent = models.BooleanField("是否有关联候选订单意图", default=False)
    has_risk_check = models.BooleanField("是否有关联风控结果", default=False)
    has_approved_order_intent = models.BooleanField("是否有关联审批通过订单意图", default=False)
    has_execution_preparation = models.BooleanField("是否有关联执行准备", default=False)
    has_order_submission = models.BooleanField("是否有关联订单提交", default=False)
    has_terminal_order_status = models.BooleanField("是否有关联终态订单状态", default=False)
    has_fill = models.BooleanField("是否有关联成交事实", default=False)
    order_submission_status = models.CharField("订单提交状态", max_length=40, blank=True)
    terminal_exchange_order_status = models.CharField("交易所终态订单状态", max_length=80, blank=True)

    order_realized_pnl = models.DecimalField("周期订单已实现盈亏", max_digits=38, decimal_places=18, default=0)
    order_commission = models.DecimalField("周期手续费", max_digits=38, decimal_places=18, default=0)
    order_net_realized_pnl = models.DecimalField("周期订单净已实现盈亏", max_digits=38, decimal_places=18, default=0)
    related_alert_count = models.PositiveIntegerField("关联告警数量", default=0)
    related_runtime_guard_issue_count = models.PositiveIntegerField("关联巡检问题数量", default=0)

    calculation_status = models.CharField(
        "计算状态",
        max_length=40,
        choices=PerformanceCalculationStatus.choices,
        default=PerformanceCalculationStatus.CALCULATED,
    )
    reason_code = models.CharField("原因代码", max_length=120)
    reason_message = models.CharField("原因说明", max_length=500, blank=True)
    input_refs_hash = models.CharField("输入事实指纹", max_length=80)
    result_hash = models.CharField("结果指纹", max_length=80)
    trace_id = models.CharField("技术追踪 ID", max_length=80)
    trigger_source = models.CharField("触发来源", max_length=80)
    operator_id = models.CharField("操作人 ID", max_length=120, blank=True)
    calculated_at_utc = models.DateTimeField("计算 UTC 时间")
    created_at_utc = models.DateTimeField("创建 UTC 时间", auto_now_add=True)
    updated_at_utc = models.DateTimeField("更新 UTC 时间", auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=[
                    "start_orchestration_run",
                    "end_orchestration_run",
                    "market_type",
                    "account_domain",
                    "symbol",
                ],
                name="uniq_orchestration_run_performance_period",
            )
        ]
        indexes = [
            models.Index(fields=["period_start_utc", "period_end_utc"]),
            models.Index(fields=["market_type", "account_domain", "symbol"]),
            models.Index(fields=["calculation_status", "calculated_at_utc"]),
            models.Index(fields=["trace_id"]),
        ]

    def __str__(self) -> str:
        return f"Performance<{self.start_orchestration_run_id}->{self.end_orchestration_run_id}:{self.symbol}>"
