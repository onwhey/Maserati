# Market Data 阶段 1 实现记录

## 1. 实现范围

本阶段实现行情数据与市场事实链路：

```text
BinancePublicMarketGateway
→ DataCollection
→ Kline
→ DataQuality
→ DataBackfill
→ DataQuality 重新验证
→ MarketSnapshot
```

当前固定采集域：

```text
exchange = binance
market_type = usds_m_futures
symbol = BTCUSDT
timeframe = 4h / 1d
```

本阶段不实现 FeatureLayer、AtomicSignal、DecisionSnapshot、账户同步、PriceSnapshot、订单链路、RuntimeGuard、OpsConsole、AIReview 或真实交易。

## 2. 新增模块

### 2.1 BinanceGateway 最小公共行情能力

新增：

```text
apps/binance_gateway/
```

当前只实现：

```text
get_server_time
get_klines
FakeBinancePublicMarketGateway
HttpBinancePublicMarketGateway
```

真实 HTTP Gateway 默认 fail-closed：

```text
BINANCE_GATEWAY_ENABLED=false
BINANCE_PUBLIC_DATA_ENABLED=false
ALLOW_REAL_EXTERNAL_SERVICES=false
```

测试默认使用 fake gateway，不访问真实 Binance。

### 2.2 MarketData

新增：

```text
apps/market_data/
```

核心模型：

```text
Kline
DataCollectionRun
DataQualityResult
DataQualityIssue
BackfillRequest
BackfillRun
BackfillIssue
DataConflict
MarketSnapshot
```

Kline 唯一业务键：

```text
exchange
market_type
symbol
timeframe
open_time_utc
```

所有 OHLCV 使用 Decimal 字段。

## 3. 关键业务规则

DataCollection：

```text
只通过 BinancePublicMarketGateway 拉取 server time 和 Kline。
只写已收盘 Kline。
重复 Kline 幂等跳过。
冲突 Kline 记录 DataConflict，不覆盖原事实。
DataCollectionRun 成功不等于 DataQuality PASS。
```

DataQuality：

```text
只读取已落库 Kline。
不请求 Binance。
任一 issue 都不会 PASS。
PASS 才 allows_downstream。
可回补问题会幂等创建 BackfillRequest。
```

DataBackfill：

```text
claim BackfillRequest 后执行。
只通过 BinancePublicMarketGateway 拉取 Kline。
只写已收盘 Kline。
missing_open_times 非空时只写指定 open_time。
BackfillRun success 只表示回补完成，仍必须 DataQuality 复检。
```

MarketSnapshot：

```text
不请求 Binance。
不写 Kline。
只消费 DataQualityResult = PASS 且 allows_downstream = true 的 4h / 1d 窗口。
4h 和 1d 必须同时满足，才创建 MarketSnapshot。
created 后才允许 FeatureLayer 消费。
```

## 4. 薄入口

新增 management command：

```text
python manage.py collect_klines
python manage.py check_data_quality
python manage.py run_data_backfill
python manage.py create_market_snapshot
```

新增 Celery task：

```text
market_data.collect_klines
market_data.check_data_quality
market_data.run_data_backfill
market_data.create_market_snapshot
```

这些入口只解析参数并调用 service，不承载核心业务逻辑。

## 5. 配置

新增 `.env.example` 配置：

```text
DATA_COLLECTION_EXCHANGE
DATA_COLLECTION_MARKET_TYPE
DATA_COLLECTION_SYMBOL
DATA_COLLECTION_TIMEFRAMES
DATA_COLLECTION_4H_LOOKBACK_COUNT
DATA_COLLECTION_1D_LOOKBACK_COUNT
DATA_BACKFILL_KLINE_PAGE_LIMIT
DATA_BACKFILL_MAX_PAGES_PER_RUN
DATA_BACKFILL_MAX_BARS_PER_RUN
MARKET_SNAPSHOT_4H_LOOKBACK_COUNT
MARKET_SNAPSHOT_1D_LOOKBACK_COUNT
BINANCE_GATEWAY_ENABLED
BINANCE_PUBLIC_DATA_ENABLED
BINANCE_USDS_M_BASE_URL
BINANCE_COIN_M_BASE_URL
BINANCE_CONNECT_TIMEOUT_SECONDS
BINANCE_READ_TIMEOUT_SECONDS
BINANCE_SAFE_READ_MAX_ATTEMPTS
```

## 6. 验收命令

已执行：

```text
.\.venv\Scripts\python.exe manage.py check
.\.venv\Scripts\python.exe manage.py makemigrations --check --dry-run
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe manage.py migrate
```

结果：

```text
manage.py check：通过
makemigrations --check --dry-run：No changes detected
pytest：22 passed
migrate：market_data.0001_initial OK
```

## 7. 明确未实现

本阶段未实现：

```text
mark price
book ticker
exchange info
账户读取 Gateway
订单提交 Gateway
订单状态 Gateway
成交查询 Gateway
PipelineOrchestrator
RuntimeGuard
Notifications 投递
真实交易
```

真实外部 Binance 访问仍由配置显式开启，默认关闭。

