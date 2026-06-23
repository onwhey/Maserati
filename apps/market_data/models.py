"""MarketData 模块：定义行情事实、质检、回补和市场快照；读写数据库，不访问外部服务，不涉及交易执行。"""

from __future__ import annotations

from django.db import models
from django.utils import timezone


class CommonStatus(models.TextChoices):
    RUNNING = "running", "运行中"
    SUCCEEDED = "succeeded", "成功"
    SUCCESS = "success", "成功"
    PASS = "PASS", "通过"
    FAIL = "FAIL", "失败"
    BLOCKED = "blocked", "阻断"
    FAILED = "failed", "系统失败"
    UNKNOWN = "unknown", "未知"
    SKIPPED = "skipped", "跳过"
    CONFLICT = "conflict", "冲突"
    CREATED = "created", "已创建"
    PENDING = "pending", "待处理"
    CANCELLED = "cancelled", "已取消"


class Kline(models.Model):
    exchange = models.CharField("交易所", max_length=40)
    market_type = models.CharField("市场类型", max_length=40)
    symbol = models.CharField("交易品种", max_length=40)
    timeframe = models.CharField("K 线周期", max_length=20)
    open_time_utc = models.DateTimeField("开盘 UTC 时间")
    close_time_utc = models.DateTimeField("收盘 UTC 时间")
    open_price = models.DecimalField("开盘价", max_digits=38, decimal_places=18)
    high_price = models.DecimalField("最高价", max_digits=38, decimal_places=18)
    low_price = models.DecimalField("最低价", max_digits=38, decimal_places=18)
    close_price = models.DecimalField("收盘价", max_digits=38, decimal_places=18)
    volume = models.DecimalField("成交量", max_digits=38, decimal_places=18)
    quote_volume = models.DecimalField("报价成交量", max_digits=38, decimal_places=18)
    trade_count = models.PositiveIntegerField("成交笔数")
    data_source = models.CharField("数据来源", max_length=40)
    source_collection_run = models.ForeignKey(
        "DataCollectionRun",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="klines",
    )
    source_backfill_run = models.ForeignKey(
        "BackfillRun",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="klines",
    )
    source_request_id = models.CharField("来源请求 ID", max_length=120, blank=True)
    created_at_utc = models.DateTimeField("创建 UTC 时间", auto_now_add=True)
    updated_at_utc = models.DateTimeField("更新 UTC 时间", auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["exchange", "market_type", "symbol", "timeframe", "open_time_utc"],
                name="uniq_kline_business_key",
            )
        ]
        indexes = [
            models.Index(fields=["exchange", "market_type", "symbol", "timeframe", "open_time_utc"]),
            models.Index(fields=["timeframe", "open_time_utc"]),
        ]


class DataCollectionRun(models.Model):
    business_request_key = models.CharField("业务幂等键", max_length=191, unique=True)
    trace_id = models.CharField("追踪 ID", max_length=80)
    trigger_source = models.CharField("触发来源", max_length=80)
    exchange = models.CharField("交易所", max_length=40)
    market_type = models.CharField("市场类型", max_length=40)
    symbol = models.CharField("交易品种", max_length=40)
    timeframe = models.CharField("K 线周期", max_length=20)
    collection_mode = models.CharField("采集模式", max_length=40)
    status = models.CharField("状态", max_length=40, default=CommonStatus.RUNNING)
    reason_code = models.CharField("原因代码", max_length=120, blank=True)
    requested_start_open_time_utc = models.DateTimeField("请求开始 open_time", null=True, blank=True)
    requested_end_open_time_utc = models.DateTimeField("请求结束 open_time", null=True, blank=True)
    lookback_count = models.PositiveIntegerField("回看数量", default=0)
    server_time_utc = models.DateTimeField("Binance server time", null=True, blank=True)
    fetched_count = models.PositiveIntegerField("拉取数量", default=0)
    closed_count = models.PositiveIntegerField("已收盘数量", default=0)
    inserted_count = models.PositiveIntegerField("插入数量", default=0)
    skipped_existing_count = models.PositiveIntegerField("跳过已存在数量", default=0)
    filtered_unclosed_count = models.PositiveIntegerField("过滤未收盘数量", default=0)
    conflict_count = models.PositiveIntegerField("冲突数量", default=0)
    error_code = models.CharField("错误代码", max_length=120, blank=True)
    error_message = models.CharField("错误摘要", max_length=500, blank=True)
    started_at_utc = models.DateTimeField("开始 UTC 时间", default=timezone.now)
    finished_at_utc = models.DateTimeField("结束 UTC 时间", null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["exchange", "market_type", "symbol", "timeframe"]),
            models.Index(fields=["status", "started_at_utc"]),
            models.Index(fields=["trace_id"]),
        ]


class DataConflict(models.Model):
    conflict_key = models.CharField("冲突幂等键", max_length=191, unique=True)
    exchange = models.CharField("交易所", max_length=40)
    market_type = models.CharField("市场类型", max_length=40)
    symbol = models.CharField("交易品种", max_length=40)
    timeframe = models.CharField("K 线周期", max_length=20)
    open_time_utc = models.DateTimeField("冲突 Kline open_time")
    source_module = models.CharField("来源模块", max_length=80)
    source_object_type = models.CharField("来源对象类型", max_length=80, blank=True)
    source_object_id = models.CharField("来源对象 ID", max_length=120, blank=True)
    existing_value_hash = models.CharField("已有值摘要", max_length=80)
    incoming_value_hash = models.CharField("新值摘要", max_length=80)
    status = models.CharField("状态", max_length=40, default="active")
    payload_summary = models.JSONField("摘要", default=dict, blank=True)
    trace_id = models.CharField("追踪 ID", max_length=80)
    trigger_source = models.CharField("触发来源", max_length=80)
    created_at_utc = models.DateTimeField("创建 UTC 时间", auto_now_add=True)


class DataQualityResult(models.Model):
    business_request_key = models.CharField("业务幂等键", max_length=191, unique=True)
    trace_id = models.CharField("追踪 ID", max_length=80)
    trigger_source = models.CharField("触发来源", max_length=80)
    exchange = models.CharField("交易所", max_length=40)
    market_type = models.CharField("市场类型", max_length=40)
    symbol = models.CharField("交易品种", max_length=40)
    timeframe = models.CharField("K 线周期", max_length=20)
    status = models.CharField("状态", max_length=40)
    reason_code = models.CharField("原因代码", max_length=120, blank=True)
    check_start_open_time_utc = models.DateTimeField("检查窗口开始")
    check_end_open_time_utc = models.DateTimeField("检查窗口结束")
    expected_latest_open_time_utc = models.DateTimeField("期望最新 open_time", null=True, blank=True)
    expected_count = models.PositiveIntegerField("期望数量", default=0)
    actual_count = models.PositiveIntegerField("实际数量", default=0)
    issue_count = models.PositiveIntegerField("问题数量", default=0)
    allows_downstream = models.BooleanField("允许下游消费", default=False)
    coverage_start_open_time_utc = models.DateTimeField("覆盖开始", null=True, blank=True)
    coverage_end_open_time_utc = models.DateTimeField("覆盖结束", null=True, blank=True)
    source_collection_run = models.ForeignKey(DataCollectionRun, null=True, blank=True, on_delete=models.SET_NULL)
    source_backfill_run = models.ForeignKey("BackfillRun", null=True, blank=True, on_delete=models.SET_NULL)
    created_at_utc = models.DateTimeField("创建 UTC 时间", auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["exchange", "market_type", "symbol", "timeframe", "status"]),
            models.Index(fields=["trace_id"]),
        ]


class DataQualityIssue(models.Model):
    result = models.ForeignKey(DataQualityResult, on_delete=models.CASCADE, related_name="issues")
    issue_type = models.CharField("问题类型", max_length=80)
    severity = models.CharField("严重级别", max_length=40, default="blocking")
    open_time_utc = models.DateTimeField("相关 open_time", null=True, blank=True)
    detail = models.CharField("问题摘要", max_length=500, blank=True)
    backfillable = models.BooleanField("是否可回补", default=False)
    created_at_utc = models.DateTimeField("创建 UTC 时间", auto_now_add=True)


class BackfillRequest(models.Model):
    business_key = models.CharField("业务幂等键", max_length=191, unique=True)
    source_module = models.CharField("来源模块", max_length=80)
    source_object_type = models.CharField("来源对象类型", max_length=80, blank=True)
    source_object_id = models.CharField("来源对象 ID", max_length=120, blank=True)
    exchange = models.CharField("交易所", max_length=40)
    market_type = models.CharField("市场类型", max_length=40)
    symbol = models.CharField("交易品种", max_length=40)
    timeframe = models.CharField("K 线周期", max_length=20)
    backfill_mode = models.CharField("回补模式", max_length=60)
    requested_start_open_time_utc = models.DateTimeField("请求开始 open_time")
    requested_end_open_time_utc = models.DateTimeField("请求结束 open_time")
    missing_open_times = models.JSONField("精确缺口 open_time", default=list, blank=True)
    reason_code = models.CharField("原因代码", max_length=120, blank=True)
    status = models.CharField("状态", max_length=40, default=CommonStatus.PENDING)
    attempt_count = models.PositiveIntegerField("尝试次数", default=0)
    last_backfill_run = models.ForeignKey(
        "BackfillRun",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="latest_for_requests",
    )
    operator_id = models.CharField("操作者", max_length=120, blank=True)
    reason = models.CharField("人工原因", max_length=500, blank=True)
    evidence = models.JSONField("证据摘要", default=dict, blank=True)
    locked_by = models.CharField("锁持有者", max_length=120, blank=True)
    locked_at_utc = models.DateTimeField("锁定时间", null=True, blank=True)
    trace_id = models.CharField("追踪 ID", max_length=80)
    trigger_source = models.CharField("触发来源", max_length=80)
    created_at_utc = models.DateTimeField("创建 UTC 时间", auto_now_add=True)
    updated_at_utc = models.DateTimeField("更新 UTC 时间", auto_now=True)


class BackfillRun(models.Model):
    business_request_key = models.CharField("业务幂等键", max_length=191, unique=True)
    backfill_request = models.ForeignKey(BackfillRequest, null=True, blank=True, on_delete=models.SET_NULL)
    trace_id = models.CharField("追踪 ID", max_length=80)
    trigger_source = models.CharField("触发来源", max_length=80)
    operator_id = models.CharField("操作者", max_length=120, blank=True)
    exchange = models.CharField("交易所", max_length=40)
    market_type = models.CharField("市场类型", max_length=40)
    symbol = models.CharField("交易品种", max_length=40)
    timeframe = models.CharField("K 线周期", max_length=20)
    backfill_mode = models.CharField("回补模式", max_length=60)
    requested_start_open_time_utc = models.DateTimeField("请求开始 open_time")
    requested_end_open_time_utc = models.DateTimeField("请求结束 open_time")
    missing_open_times = models.JSONField("精确缺口 open_time", default=list, blank=True)
    status = models.CharField("状态", max_length=40, default=CommonStatus.RUNNING)
    reason_code = models.CharField("原因代码", max_length=120, blank=True)
    gateway_attempt_count = models.PositiveIntegerField("Gateway 尝试次数", default=0)
    page_count = models.PositiveIntegerField("分页数量", default=0)
    fetched_count = models.PositiveIntegerField("拉取数量", default=0)
    closed_count = models.PositiveIntegerField("已收盘数量", default=0)
    inserted_count = models.PositiveIntegerField("插入数量", default=0)
    skipped_existing_count = models.PositiveIntegerField("跳过已存在数量", default=0)
    filtered_unclosed_count = models.PositiveIntegerField("过滤未收盘数量", default=0)
    filtered_not_requested_count = models.PositiveIntegerField("过滤非请求数量", default=0)
    conflict_count = models.PositiveIntegerField("冲突数量", default=0)
    requires_quality_recheck = models.BooleanField("需要 DataQuality 复检", default=False)
    recheck_window_start_open_time_utc = models.DateTimeField("复检开始", null=True, blank=True)
    recheck_window_end_open_time_utc = models.DateTimeField("复检结束", null=True, blank=True)
    error_code = models.CharField("错误代码", max_length=120, blank=True)
    error_message = models.CharField("错误摘要", max_length=500, blank=True)
    started_at_utc = models.DateTimeField("开始 UTC 时间", default=timezone.now)
    finished_at_utc = models.DateTimeField("结束 UTC 时间", null=True, blank=True)


class BackfillIssue(models.Model):
    run = models.ForeignKey(BackfillRun, on_delete=models.CASCADE, related_name="issues")
    issue_type = models.CharField("问题类型", max_length=80)
    detail = models.CharField("问题摘要", max_length=500, blank=True)
    open_time_utc = models.DateTimeField("相关 open_time", null=True, blank=True)
    created_at_utc = models.DateTimeField("创建 UTC 时间", auto_now_add=True)


class MarketSnapshot(models.Model):
    business_request_key = models.CharField("业务幂等键", max_length=191, unique=True)
    exchange = models.CharField("交易所", max_length=40)
    market_type = models.CharField("市场类型", max_length=40)
    symbol = models.CharField("交易品种", max_length=40)
    base_timeframe = models.CharField("主周期", max_length=20)
    higher_timeframe = models.CharField("辅助周期", max_length=20)
    analysis_close_time_utc = models.DateTimeField("分析收盘边界")
    analysis_reference_time_utc = models.DateTimeField("分析参考时间")
    status = models.CharField("状态", max_length=40, default=CommonStatus.CREATED)
    reason_code = models.CharField("原因代码", max_length=120, blank=True)
    blocked_reason = models.CharField("阻断原因", max_length=500, blank=True)
    latest_4h_open_time_utc = models.DateTimeField("最新 4h open_time")
    latest_1d_open_time_utc = models.DateTimeField("最新 1d open_time")
    lookback_4h_count = models.PositiveIntegerField("4h 回看数量")
    lookback_1d_count = models.PositiveIntegerField("1d 回看数量")
    actual_4h_count = models.PositiveIntegerField("实际 4h 数量")
    actual_1d_count = models.PositiveIntegerField("实际 1d 数量")
    start_4h_open_time_utc = models.DateTimeField("4h 窗口开始")
    end_4h_open_time_utc = models.DateTimeField("4h 窗口结束")
    start_1d_open_time_utc = models.DateTimeField("1d 窗口开始")
    end_1d_open_time_utc = models.DateTimeField("1d 窗口结束")
    data_quality_result_4h = models.ForeignKey(
        DataQualityResult,
        on_delete=models.PROTECT,
        related_name="market_snapshots_4h",
    )
    data_quality_result_1d = models.ForeignKey(
        DataQualityResult,
        on_delete=models.PROTECT,
        related_name="market_snapshots_1d",
    )
    data_collection_run_ids = models.JSONField("采集运行索引", default=list, blank=True)
    backfill_run_ids = models.JSONField("回补运行索引", default=list, blank=True)
    payload_summary = models.JSONField("快照摘要", default=dict, blank=True)
    allows_feature_layer = models.BooleanField("允许特征层消费", default=True)
    trace_id = models.CharField("追踪 ID", max_length=80)
    trigger_source = models.CharField("触发来源", max_length=80)
    created_at_utc = models.DateTimeField("创建 UTC 时间", auto_now_add=True)
    finished_at_utc = models.DateTimeField("完成 UTC 时间", default=timezone.now)

    class Meta:
        indexes = [
            models.Index(fields=["exchange", "market_type", "symbol", "analysis_close_time_utc"]),
            models.Index(fields=["trace_id"]),
        ]

