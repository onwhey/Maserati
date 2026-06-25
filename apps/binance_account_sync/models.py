"""BinanceAccountSync 模块：定义账户同步批次和账户/余额/持仓/规则快照；读写数据库；不访问 Redis；不访问外部服务；不发送 Hermes；不调用大模型；不涉及交易执行；不允许真实交易。"""

from __future__ import annotations

from django.db import models
from django.utils import timezone


class BinanceSyncStatus(models.TextChoices):
    RUNNING = "running", "运行中"
    SUCCEEDED = "succeeded", "成功"
    FAILED = "failed", "失败"


class BinanceSyncPurpose(models.TextChoices):
    TRADE_PREPARATION = "trade_preparation", "自动交易账户边界"
    OPS_DISPLAY = "ops_display", "后台展示刷新"


class BinancePositionMode(models.TextChoices):
    ONE_WAY = "one_way", "单向持仓"
    HEDGE = "hedge", "双向持仓"
    UNKNOWN = "unknown", "未知"


class BinanceSyncRun(models.Model):
    business_request_key = models.CharField("业务幂等键", max_length=191)
    request_identity_hash = models.CharField("请求身份 hash", max_length=64, unique=True, null=True, blank=True)
    exchange = models.CharField("交易所", max_length=40, default="binance")
    market_type = models.CharField("市场类型", max_length=40)
    account_domain = models.CharField("账户域", max_length=120)
    sync_purpose = models.CharField("同步目的", max_length=40, choices=BinanceSyncPurpose.choices)
    requested_symbols = models.JSONField("请求 symbol 列表", default=list)
    status = models.CharField("状态", max_length=40, choices=BinanceSyncStatus.choices, default=BinanceSyncStatus.RUNNING)
    started_at_utc = models.DateTimeField("开始 UTC 时间", default=timezone.now)
    finished_at_utc = models.DateTimeField("完成 UTC 时间", null=True, blank=True)
    as_of_utc = models.DateTimeField("事实观察 UTC 时间", null=True, blank=True)
    expires_at_utc = models.DateTimeField("过期 UTC 时间", null=True, blank=True)
    position_mode = models.CharField(
        "持仓模式",
        max_length=40,
        choices=BinancePositionMode.choices,
        default=BinancePositionMode.UNKNOWN,
    )
    snapshot_set_hash = models.CharField("快照集合 hash", max_length=80, blank=True)
    gateway_call_summary = models.JSONField("Gateway 调用摘要", default=dict, blank=True)
    error_code = models.CharField("错误代码", max_length=120, blank=True)
    error_message = models.CharField("错误摘要", max_length=500, blank=True)
    trace_id = models.CharField("追踪 ID", max_length=80)
    trigger_source = models.CharField("触发来源", max_length=80)
    operator_id = models.CharField("操作人", max_length=120, blank=True)
    created_at_utc = models.DateTimeField("创建 UTC 时间", auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["market_type", "account_domain", "sync_purpose", "status"]),
            models.Index(fields=["status", "started_at_utc"]),
            models.Index(fields=["expires_at_utc"]),
            models.Index(fields=["trace_id"]),
        ]


class BinanceAccountSnapshot(models.Model):
    sync_run = models.ForeignKey(BinanceSyncRun, on_delete=models.PROTECT, related_name="account_snapshots")
    market_type = models.CharField("市场类型", max_length=40)
    account_domain = models.CharField("账户域", max_length=120)
    fee_tier = models.IntegerField("手续费等级", null=True, blank=True)
    can_trade = models.BooleanField("是否允许交易", null=True, blank=True)
    can_deposit = models.BooleanField("是否允许充值", null=True, blank=True)
    can_withdraw = models.BooleanField("是否允许提现", null=True, blank=True)
    position_mode = models.CharField("持仓模式", max_length=40, choices=BinancePositionMode.choices)
    total_wallet_balance = models.DecimalField("钱包余额", max_digits=38, decimal_places=18, null=True, blank=True)
    total_unrealized_profit = models.DecimalField("未实现盈亏", max_digits=38, decimal_places=18, null=True, blank=True)
    total_margin_balance = models.DecimalField("保证金余额", max_digits=38, decimal_places=18, null=True, blank=True)
    available_balance = models.DecimalField("可用余额", max_digits=38, decimal_places=18, null=True, blank=True)
    max_withdraw_amount = models.DecimalField("最大可提现", max_digits=38, decimal_places=18, null=True, blank=True)
    native_asset = models.CharField("原生结算资产", max_length=40, blank=True)
    as_of_utc = models.DateTimeField("事实观察 UTC 时间")
    source_operation = models.CharField("来源 Gateway 操作", max_length=80)
    raw_payload = models.JSONField("脱敏原始载荷", default=dict, blank=True)
    snapshot_hash = models.CharField("快照 hash", max_length=80)
    created_at_utc = models.DateTimeField("创建 UTC 时间", auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["sync_run"], name="uniq_account_snapshot_per_sync_run")
        ]
        indexes = [
            models.Index(fields=["market_type", "account_domain"]),
            models.Index(fields=["snapshot_hash"]),
        ]


class BinanceBalanceSnapshot(models.Model):
    sync_run = models.ForeignKey(BinanceSyncRun, on_delete=models.PROTECT, related_name="balance_snapshots")
    market_type = models.CharField("市场类型", max_length=40)
    account_domain = models.CharField("账户域", max_length=120)
    asset = models.CharField("资产", max_length=40)
    wallet_balance = models.DecimalField("钱包余额", max_digits=38, decimal_places=18, null=True, blank=True)
    cross_wallet_balance = models.DecimalField("全仓钱包余额", max_digits=38, decimal_places=18, null=True, blank=True)
    cross_unrealized_pnl = models.DecimalField("全仓未实现盈亏", max_digits=38, decimal_places=18, null=True, blank=True)
    available_balance = models.DecimalField("可用余额", max_digits=38, decimal_places=18, null=True, blank=True)
    max_withdraw_amount = models.DecimalField("最大可提现", max_digits=38, decimal_places=18, null=True, blank=True)
    margin_available = models.BooleanField("是否可作保证金", null=True, blank=True)
    update_time_utc = models.DateTimeField("更新时间", null=True, blank=True)
    source_operation = models.CharField("来源 Gateway 操作", max_length=80)
    raw_payload = models.JSONField("脱敏原始载荷", default=dict, blank=True)
    snapshot_hash = models.CharField("快照 hash", max_length=80)
    created_at_utc = models.DateTimeField("创建 UTC 时间", auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["sync_run", "asset"], name="uniq_balance_snapshot_asset")
        ]
        indexes = [
            models.Index(fields=["market_type", "account_domain", "asset"]),
            models.Index(fields=["snapshot_hash"]),
        ]


class BinancePositionSnapshot(models.Model):
    sync_run = models.ForeignKey(BinanceSyncRun, on_delete=models.PROTECT, related_name="position_snapshots")
    market_type = models.CharField("市场类型", max_length=40)
    account_domain = models.CharField("账户域", max_length=120)
    symbol = models.CharField("交易品种", max_length=40)
    raw_position_side = models.CharField("原始持仓方向", max_length=40, blank=True)
    normalized_position_side = models.CharField("标准化持仓方向", max_length=40)
    position_amount = models.DecimalField("持仓数量", max_digits=38, decimal_places=18, null=True, blank=True)
    entry_price = models.DecimalField("开仓均价", max_digits=38, decimal_places=18, null=True, blank=True)
    break_even_price = models.DecimalField("盈亏平衡价", max_digits=38, decimal_places=18, null=True, blank=True)
    mark_price = models.DecimalField("账户响应观察标记价格", max_digits=38, decimal_places=18, null=True, blank=True)
    unrealized_pnl = models.DecimalField("未实现盈亏", max_digits=38, decimal_places=18, null=True, blank=True)
    liquidation_price = models.DecimalField("强平价格", max_digits=38, decimal_places=18, null=True, blank=True)
    isolated_margin = models.DecimalField("逐仓保证金", max_digits=38, decimal_places=18, null=True, blank=True)
    notional = models.DecimalField("名义价值", max_digits=38, decimal_places=18, null=True, blank=True)
    margin_asset = models.CharField("保证金资产", max_length=40, blank=True)
    margin_mode = models.CharField("保证金模式", max_length=40, blank=True)
    position_mode_observed = models.CharField("观察到的持仓模式", max_length=40, choices=BinancePositionMode.choices)
    observed_exchange_leverage = models.DecimalField("交易所观察杠杆", max_digits=38, decimal_places=18, null=True, blank=True)
    update_time_utc = models.DateTimeField("更新时间", null=True, blank=True)
    source_operation = models.CharField("来源 Gateway 操作", max_length=80)
    raw_payload = models.JSONField("脱敏原始载荷", default=dict, blank=True)
    snapshot_hash = models.CharField("快照 hash", max_length=80)
    created_at_utc = models.DateTimeField("创建 UTC 时间", auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["sync_run", "symbol", "normalized_position_side"],
                name="uniq_position_snapshot_side",
            )
        ]
        indexes = [
            models.Index(fields=["market_type", "account_domain", "symbol"]),
            models.Index(fields=["snapshot_hash"]),
        ]


class BinanceSymbolRuleSnapshot(models.Model):
    sync_run = models.ForeignKey(BinanceSyncRun, on_delete=models.PROTECT, related_name="symbol_rule_snapshots")
    market_type = models.CharField("市场类型", max_length=40)
    account_domain = models.CharField("账户域", max_length=120)
    symbol = models.CharField("交易品种", max_length=40)
    contract_status = models.CharField("合约状态", max_length=80, blank=True)
    base_asset = models.CharField("基础资产", max_length=40, blank=True)
    quote_asset = models.CharField("计价资产", max_length=40, blank=True)
    margin_asset = models.CharField("保证金资产", max_length=40, blank=True)
    settlement_asset = models.CharField("结算资产", max_length=40, blank=True)
    contract_type = models.CharField("合约类型", max_length=80, blank=True)
    price_precision = models.IntegerField("价格精度", null=True, blank=True)
    quantity_precision = models.IntegerField("数量精度", null=True, blank=True)
    tick_size = models.DecimalField("价格步长", max_digits=38, decimal_places=18, null=True, blank=True)
    step_size = models.DecimalField("数量步长", max_digits=38, decimal_places=18, null=True, blank=True)
    min_price = models.DecimalField("最小价格", max_digits=38, decimal_places=18, null=True, blank=True)
    max_price = models.DecimalField("最大价格", max_digits=38, decimal_places=18, null=True, blank=True)
    min_quantity = models.DecimalField("最小数量", max_digits=38, decimal_places=18, null=True, blank=True)
    max_quantity = models.DecimalField("最大数量", max_digits=38, decimal_places=18, null=True, blank=True)
    min_notional = models.DecimalField("最小名义价值", max_digits=38, decimal_places=18, null=True, blank=True)
    contract_size = models.DecimalField("合约面值", max_digits=38, decimal_places=18, null=True, blank=True)
    supported_order_types = models.JSONField("支持订单类型", default=list, blank=True)
    raw_filters = models.JSONField("原始过滤器", default=list, blank=True)
    source_operation = models.CharField("来源 Gateway 操作", max_length=80)
    raw_payload = models.JSONField("脱敏原始载荷", default=dict, blank=True)
    snapshot_hash = models.CharField("快照 hash", max_length=80)
    created_at_utc = models.DateTimeField("创建 UTC 时间", auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["sync_run", "symbol"], name="uniq_symbol_rule_snapshot")
        ]
        indexes = [
            models.Index(fields=["market_type", "account_domain", "symbol"]),
            models.Index(fields=["snapshot_hash"]),
        ]
