"""FillSync 模块：定义成交同步结果、逐笔成交和订单成交汇总；读写 MySQL；不访问 Redis 或外部服务；不发送 Hermes；不调用大模型；不提交订单；不修改账户快照。"""

from __future__ import annotations

from django.db import models


class FillSyncResultStatus(models.TextChoices):
    SYNCING = "syncing", "同步中"
    SYNCED = "synced", "成交同步完整"
    SYNCED_EMPTY = "synced_empty", "确认无成交"
    INCOMPLETE = "incomplete", "成交证据不完整"
    UNKNOWN = "unknown", "成交查询结果未知"
    FAILED_BEFORE_QUERY = "failed_before_query", "查询前失败"
    BLOCKED_BEFORE_QUERY = "blocked_before_query", "查询前阻断"
    RECOVERY_SKIPPED_OUT_OF_WINDOW = "recovery_skipped_out_of_window", "恢复窗口外跳过"


class FillSyncMode(models.TextChoices):
    NORMAL = "normal", "主链路同步"
    RECOVERY = "recovery", "受控恢复同步"


class OrderFillSummaryStatus(models.TextChoices):
    COMPLETE = "complete", "汇总完整"
    EMPTY = "empty", "确认无成交"
    INCOMPLETE = "incomplete", "汇总不完整"


class FillSyncResult(models.Model):
    fill_sync_result_key = models.CharField("成交同步幂等键", max_length=191, unique=True)
    sync_sequence = models.PositiveIntegerField("同步序号")
    sync_mode = models.CharField("同步模式", max_length=40, choices=FillSyncMode.choices, default=FillSyncMode.NORMAL)
    status = models.CharField("同步状态", max_length=40, choices=FillSyncResultStatus.choices)
    reason_code = models.CharField("原因代码", max_length=120)
    reason_message = models.CharField("原因说明", max_length=500, blank=True)
    order_submission_attempt = models.ForeignKey(
        "execution.OrderSubmissionAttempt",
        on_delete=models.PROTECT,
        related_name="fill_sync_results",
    )
    terminal_order_status_sync_record = models.ForeignKey(
        "order_status_sync.OrderStatusSyncRecord",
        on_delete=models.PROTECT,
        related_name="fill_sync_results",
    )
    prepared_order_intent = models.ForeignKey(
        "execution_preparation.PreparedOrderIntent",
        on_delete=models.PROTECT,
        related_name="fill_sync_results",
    )
    order_plan = models.ForeignKey(
        "order_plan.OrderPlan",
        on_delete=models.PROTECT,
        related_name="fill_sync_results",
    )
    active_lock = models.ForeignKey(
        "order_plan.OrderPlanActiveLock",
        on_delete=models.PROTECT,
        related_name="fill_sync_results",
    )
    business_request_key = models.CharField("业务幂等键", max_length=191)
    exchange = models.CharField("交易所", max_length=40, default="binance")
    market_type = models.CharField("市场类型", max_length=40)
    account_domain = models.CharField("账户域", max_length=120)
    endpoint_family = models.CharField("Gateway endpoint family", max_length=40, blank=True)
    symbol = models.CharField("交易品种", max_length=40)
    client_order_id = models.CharField("Binance clientOrderId", max_length=120, blank=True)
    exchange_order_id = models.CharField("交易所订单 ID", max_length=120, blank=True)
    terminal_exchange_status = models.CharField("终态订单状态", max_length=80, blank=True)
    terminal_executed_quantity = models.DecimalField("终态累计成交数量", max_digits=38, decimal_places=18, null=True, blank=True)
    terminal_cumulative_quote_quantity = models.DecimalField("终态累计 quote 数量", max_digits=38, decimal_places=18, null=True, blank=True)
    page_count = models.PositiveIntegerField("查询页数", default=0)
    pagination_complete = models.BooleanField("分页是否完整", default=False)
    gateway_attempt_count_total = models.PositiveIntegerField("Gateway 技术尝试总数", default=0)
    returned_fill_count = models.PositiveIntegerField("返回成交数量", default=0)
    inserted_fill_count = models.PositiveIntegerField("新增成交数量", default=0)
    duplicate_fill_count = models.PositiveIntegerField("重复成交数量", default=0)
    conflict_fill_count = models.PositiveIntegerField("冲突成交数量", default=0)
    sync_started_at_utc = models.DateTimeField("同步开始 UTC 时间")
    sync_finished_at_utc = models.DateTimeField("同步完成 UTC 时间", null=True, blank=True)
    config_snapshot = models.JSONField("配置快照", default=dict, blank=True)
    input_hash = models.CharField("输入指纹", max_length=80)
    evidence = models.JSONField("同步证据", default=dict, blank=True)
    alert_event_ids = models.JSONField("AlertEvent ID", default=list, blank=True)
    trace_id = models.CharField("技术追踪 ID", max_length=80)
    trigger_source = models.CharField("触发来源", max_length=80)
    created_at_utc = models.DateTimeField("创建 UTC 时间", auto_now_add=True)
    updated_at_utc = models.DateTimeField("更新 UTC 时间", auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["order_submission_attempt", "terminal_order_status_sync_record", "sync_sequence"],
                name="uniq_fill_sync_attempt_terminal_sequence",
            )
        ]
        indexes = [
            models.Index(fields=["order_submission_attempt", "sync_sequence"]),
            models.Index(fields=["status", "created_at_utc"]),
            models.Index(fields=["market_type", "account_domain", "symbol"]),
            models.Index(fields=["trace_id"]),
        ]


class TradeFill(models.Model):
    order_submission_attempt = models.ForeignKey(
        "execution.OrderSubmissionAttempt",
        on_delete=models.PROTECT,
        related_name="trade_fills",
    )
    terminal_order_status_sync_record = models.ForeignKey(
        "order_status_sync.OrderStatusSyncRecord",
        on_delete=models.PROTECT,
        related_name="trade_fills",
    )
    first_seen_fill_sync_result = models.ForeignKey(
        FillSyncResult,
        on_delete=models.PROTECT,
        related_name="first_seen_trade_fills",
    )
    exchange = models.CharField("交易所", max_length=40, default="binance")
    market_type = models.CharField("市场类型", max_length=40)
    account_domain = models.CharField("账户域", max_length=120)
    endpoint_family = models.CharField("Gateway endpoint family", max_length=40, blank=True)
    symbol = models.CharField("交易品种", max_length=40)
    client_order_id = models.CharField("Binance clientOrderId", max_length=120, blank=True)
    exchange_order_id = models.CharField("交易所订单 ID", max_length=120)
    exchange_trade_id = models.CharField("交易所成交 ID", max_length=120)
    side = models.CharField("订单方向", max_length=10)
    position_side = models.CharField("持仓方向", max_length=20)
    price = models.DecimalField("成交价格", max_digits=38, decimal_places=18)
    quantity = models.DecimalField("成交数量", max_digits=38, decimal_places=18)
    quantity_unit = models.CharField("数量单位", max_length=40)
    contract_size = models.DecimalField("合约面值", max_digits=38, decimal_places=18, null=True, blank=True)
    quote_quantity = models.DecimalField("quote 成交额", max_digits=38, decimal_places=18, null=True, blank=True)
    base_quantity = models.DecimalField("base 成交数量", max_digits=38, decimal_places=18, null=True, blank=True)
    commission = models.DecimalField("手续费", max_digits=38, decimal_places=18, null=True, blank=True)
    commission_asset = models.CharField("手续费资产", max_length=40, blank=True)
    realized_pnl = models.DecimalField("已实现盈亏", max_digits=38, decimal_places=18, null=True, blank=True)
    realized_pnl_asset = models.CharField("已实现盈亏资产", max_length=40, blank=True)
    is_buyer = models.BooleanField("是否买方", null=True, blank=True)
    is_maker = models.BooleanField("是否 maker", null=True, blank=True)
    trade_time_utc = models.DateTimeField("成交 UTC 时间")
    sanitized_raw_fill = models.JSONField("脱敏原始成交", default=dict, blank=True)
    raw_fill_hash = models.CharField("原始成交 hash", max_length=80)
    trigger_source = models.CharField("触发来源", max_length=80)
    created_at_utc = models.DateTimeField("创建 UTC 时间", auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["exchange", "market_type", "account_domain", "symbol", "exchange_order_id", "exchange_trade_id"],
                name="uniq_trade_fill_exchange_identity",
            )
        ]
        indexes = [
            models.Index(fields=["order_submission_attempt", "trade_time_utc"]),
            models.Index(fields=["market_type", "account_domain", "symbol"]),
            models.Index(fields=["exchange_trade_id"]),
        ]


class OrderFillSummary(models.Model):
    order_submission_attempt = models.OneToOneField(
        "execution.OrderSubmissionAttempt",
        on_delete=models.PROTECT,
        related_name="order_fill_summary",
    )
    latest_fill_sync_result = models.ForeignKey(
        FillSyncResult,
        on_delete=models.PROTECT,
        related_name="order_fill_summaries",
    )
    terminal_order_status_sync_record = models.ForeignKey(
        "order_status_sync.OrderStatusSyncRecord",
        on_delete=models.PROTECT,
        related_name="order_fill_summaries",
    )
    status = models.CharField("汇总状态", max_length=40, choices=OrderFillSummaryStatus.choices)
    reason_code = models.CharField("原因代码", max_length=120)
    exchange = models.CharField("交易所", max_length=40, default="binance")
    market_type = models.CharField("市场类型", max_length=40)
    account_domain = models.CharField("账户域", max_length=120)
    endpoint_family = models.CharField("Gateway endpoint family", max_length=40, blank=True)
    symbol = models.CharField("交易品种", max_length=40)
    client_order_id = models.CharField("Binance clientOrderId", max_length=120, blank=True)
    exchange_order_id = models.CharField("交易所订单 ID", max_length=120, blank=True)
    terminal_exchange_status = models.CharField("终态订单状态", max_length=80, blank=True)
    fill_count = models.PositiveIntegerField("成交笔数", default=0)
    total_quantity = models.DecimalField("总成交数量", max_digits=38, decimal_places=18)
    total_quote_quantity = models.DecimalField("总 quote 成交额", max_digits=38, decimal_places=18)
    total_base_quantity = models.DecimalField("总 base 成交数量", max_digits=38, decimal_places=18)
    filled_notional_usd = models.DecimalField("COIN-M 合约名义金额", max_digits=38, decimal_places=18, null=True, blank=True)
    average_price = models.DecimalField("均价", max_digits=38, decimal_places=18, null=True, blank=True)
    commission_by_asset = models.JSONField("手续费按资产汇总", default=dict, blank=True)
    realized_pnl_by_asset = models.JSONField("已实现盈亏按资产汇总", default=dict, blank=True)
    terminal_executed_quantity = models.DecimalField("终态累计成交数量", max_digits=38, decimal_places=18, null=True, blank=True)
    terminal_cumulative_quote_quantity = models.DecimalField("终态累计 quote 数量", max_digits=38, decimal_places=18, null=True, blank=True)
    quantity_reconciled = models.BooleanField("数量是否对账一致", default=False)
    quote_reconciled = models.BooleanField("quote 是否对账一致", default=False)
    identity_reconciled = models.BooleanField("身份是否对账一致", default=False)
    pagination_complete = models.BooleanField("分页是否完整", default=False)
    lock_finalization_status = models.CharField("锁收尾状态", max_length=80, blank=True)
    lock_finalized_at_utc = models.DateTimeField("锁收尾 UTC 时间", null=True, blank=True)
    summary_hash = models.CharField("汇总 hash", max_length=80)
    alert_event_ids = models.JSONField("AlertEvent ID", default=list, blank=True)
    created_at_utc = models.DateTimeField("创建 UTC 时间", auto_now_add=True)
    updated_at_utc = models.DateTimeField("更新 UTC 时间", auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["status", "updated_at_utc"]),
            models.Index(fields=["market_type", "account_domain", "symbol"]),
        ]
