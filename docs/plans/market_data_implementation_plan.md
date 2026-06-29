# 行情数据与市场事实实施计划

## 1. 文档目的

本文档用于指导阶段 1 的代码实现。

阶段 1 的目标是实现从 Binance 已收盘 Kline 到 MarketSnapshot 的市场事实链路：

```text
BinancePublicMarketGateway
→ DataCollection
→ Kline
→ DataQuality
→ 必要时 DataBackfill
→ DataQuality 重新验证
→ MarketSnapshot
```

阶段 1 完成后，系统应能稳定、幂等、可审计地取得 Binance USDS-M BTCUSDT 的 4h / 1d 已收盘 Kline，并在 DataQuality 明确 PASS 后生成 MarketSnapshot，作为后续 FeatureLayer 的唯一正式市场输入。

本文档不实现策略、特征、账户、价格、订单、风控、执行、后台、复盘或完整编排。

---

## 2. 阶段定位

阶段 1 是市场事实阶段。

一句话：

```text
先把行情事实采回来、检查清楚、缺口补齐，并把一轮分析用到的 4h / 1d 窗口固定成 MarketSnapshot。
```

本阶段只解决“市场数据是否可信、是否能交给后续分析链路”的问题。

本阶段不判断市场趋势，不生成交易信号，不生成目标仓位，不进入订单链路。

---

## 3. 前置条件

进入本阶段前，应已完成或具备阶段 0 的基础能力：

```text
Django 项目可以启动；
settings 显式读取 .env；
MySQL 可用；
Redis 可用；
Celery app 可加载；
UTC 配置正确；
基础日志与脱敏可用；
trace_id / trigger_source 可传递；
AlertEvent 可写入；
AuditRecord 可写入；
测试框架可运行；
默认测试不访问真实外部服务。
```

如果阶段 0 尚未完成，本阶段只能先实现纯文档或纯模型设计，不应进入真实代码实现。

---

## 4. 文档依据

编码前必须阅读并遵守：

```text
AGENTS.md
README.md
docs/rules/project_invariants.md
docs/requirements/project_foundation.md
docs/requirements/core_contracts.md
docs/requirements/binance_gateway.md
docs/requirements/data_collection.md
docs/requirements/data_quality.md
docs/requirements/data_backfill.md
docs/requirements/market_snapshot.md
docs/architecture/data_flow_architecture.md
docs/architecture/module_boundary_architecture.md
docs/architecture/runtime_task_architecture.md
docs/architecture/testing_and_safety_architecture.md
docs/plans/foundation_implementation_plan.md
docs/plans/implementation_roadmap.md
```

如果本文档与 requirements 冲突，以 requirements 为准，并停止实现向用户确认。

---

## 5. 本阶段实现范围

### 5.1 BinancePublicMarketGateway 最小能力

本阶段需要实现 BinanceGateway 的公共行情最小能力。

只实现：

```text
get_server_time(market_type, call_context)
get_klines(market_type, symbol, interval, start_time_utc, end_time_utc, limit, call_context)
```

本阶段不实现：

```text
get_mark_price；
get_book_ticker；
get_exchange_info；
get_symbol_exchange_info；
BinanceAccountReadGateway；
BinanceOrderSubmissionGateway；
BinanceOrderStatusGateway；
BinanceFillQueryGateway。
```

如果为了类型结构或接口完整性保留这些接口的占位，必须默认禁用并返回明确 `capability_disabled`，不得访问真实 Binance。

Gateway 必须满足：

```text
业务模块不能获得 raw request；
业务模块不能拼 Binance endpoint；
业务模块不能自行创建 HTTP client；
请求 Kline 不传 timeZone；
Binance 时间戳按 UTC 解释；
日志和异常必须脱敏；
测试可以完整替换为 fake gateway。
```

### 5.2 DataCollection

实现 DataCollection service，负责：

```text
读取固定 data_collection_domain；
通过 BinancePublicMarketGateway 获取 server time；
通过 BinancePublicMarketGateway 获取 Kline；
过滤未收盘 Kline；
规范化 UTC 时间与 Decimal 数值；
按唯一业务键幂等写入 Kline；
记录 DataCollectionRun；
发现冲突时阻断且不覆盖；
必要时写 AlertEvent；
返回可交给 DataQuality 的采集覆盖摘要。
```

当前采集域固定：

```text
exchange = binance
market_type = usds_m_futures
symbol = BTCUSDT
timeframe = 4h / 1d
```

DataCollection 不得读取 active trading domain。

### 5.3 DataQuality

实现 DataQuality service，负责：

```text
读取已落库 Kline；
校验固定采集域；
校验 UTC 检查窗口；
检查 4h / 1d 周期边界；
检查已收盘；
检查连续性；
检查缺失；
检查重复；
检查 OHLC 合法性；
检查成交量合法性；
检查数据来源；
检查数据冲突；
写 DataQualityResult；
写 DataQualityIssue；
为可回补问题幂等创建 BackfillRequest；
必要时写 AlertEvent；
返回是否允许 MarketSnapshot 消费。
```

DataQuality 不请求 Binance，不执行回补，不写 Kline，不生成 MarketSnapshot。

### 5.4 DataBackfill

实现 DataBackfill service，负责：

```text
claim BackfillRequest；
校验固定采集域；
校验 UTC 回补范围；
通过 BinancePublicMarketGateway 获取 server time；
通过 BinancePublicMarketGateway 分批获取 Kline；
过滤未收盘 Kline；
按 missing_open_times 精确过滤；
幂等写入正式 Kline；
发现冲突时记录 DataConflict 且不覆盖；
记录 BackfillRun；
记录 BackfillIssue；
必要时写 AlertEvent；
标记 requires_quality_recheck = true。
```

DataBackfill 完成不等于数据可信。

回补后必须重新执行 DataQuality，只有新的 DataQualityResult PASS 才允许 MarketSnapshot 继续。

### 5.5 MarketSnapshot

实现 MarketSnapshot service，负责：

```text
校验固定采集域；
校验 analysis_close_time_utc；
计算或接收 4h 目标窗口；
计算或接收 1d 目标窗口；
读取 4h 与 1d DataQualityResult；
确认二者均 PASS 且 allows_downstream = true；
确认质量结果覆盖目标窗口；
读取窗口内 Kline；
确认数量、连续性、UTC 边界和已收盘；
创建或复用 MarketSnapshot；
记录窗口边界、lookback_count、DataQualityResult 引用、trace_id 和 trigger_source；
返回 market_snapshot_id。
```

MarketSnapshot created 后，才允许后续 FeatureLayer 消费。

MarketSnapshot 不请求 Binance，不写 Kline，不触发 DataBackfill，不生成特征、信号、决策或订单。

---

## 6. 当前固定业务口径

### 6.1 数据采集域

阶段 1 只支持：

```text
exchange = binance
market_type = usds_m_futures
symbol = BTCUSDT
```

该采集域是行情数据来源域，不等于交易执行域。

交易模块未来可支持 USDS-M 或 COIN-M，但 DataCollection、DataQuality、DataBackfill 和 MarketSnapshot 当前不随交易执行域切换。

禁止：

```text
根据 active trading domain 改变采集域；
后台热切 symbol；
按账户域切换行情采集目标；
同时为多个采集域生成当前主链路 MarketSnapshot。
```

### 6.2 时间周期

阶段 1 只支持：

```text
4h；
1d。
```

语义：

```text
4h = 主策略分析周期；
1d = 大周期趋势、市场环境和复盘辅助周期。
```

当前不采集、不检查、不生成快照：

```text
1m；
5m；
15m；
1h；
订单簿；
逐笔成交；
资金费率；
WebSocket 实时行情。
```

### 6.3 UTC

所有行情业务时间必须使用 UTC。

必须：

```text
Binance open_time 按 UTC 解释；
Binance close_time 按 UTC 解释；
Kline open_time_utc / close_time_utc 使用 UTC；
采集窗口使用 UTC；
检查窗口使用 UTC；
回补窗口使用 UTC；
MarketSnapshot analysis_close_time_utc 使用 UTC；
请求 Kline 时不传 timeZone。
```

禁止：

```text
用服务器本地时间判断 Kline 是否收盘；
用 PRC 时间计算采集、质检、回补或快照窗口；
用数据库自增 id 判断 Kline 顺序或连续性；
用 4h 节奏错误推断 1d 新鲜度。
```

---

## 7. 建议代码模块

具体 Django app 名称可在编码阶段最终确定，但建议：

```text
apps/binance_gateway/
apps/market_data/
```

`apps/binance_gateway/` 本阶段只包含公共行情最小能力和 fake gateway。

`apps/market_data/` 包含：

```text
DataCollection；
DataQuality；
DataBackfill；
MarketSnapshot；
Kline 存储；
相关 selector / repository / service / domain；
必要 command / task 薄入口。
```

业务逻辑必须放在：

```text
service 层；
domain 层；
必要的纯计算 helper。
```

禁止把复杂业务逻辑写进：

```text
Django model；
Celery task；
management command；
view；
serializer；
repository。
```

---

## 8. 数据库迁移范围

阶段 1 建议创建以下核心对象：

```text
Kline；
DataCollectionRun；
DataQualityResult；
DataQualityIssue；
BackfillRequest；
BackfillRun；
BackfillIssue；
DataConflict；
MarketSnapshot。
```

可选择单一 `Kline` 表，通过 `timeframe` 区分 4h / 1d。

如果实现采用 4h 与 1d 分表，两个表仍必须表达同一业务对象语义：`Kline`。

### 8.1 Kline 唯一业务键

唯一业务键至少包括：

```text
exchange；
market_type；
symbol；
timeframe；
open_time_utc。
```

必须有数据库唯一约束。

禁止使用：

```text
trace_id；
数据库自增 id；
Celery task id；
当前时间；
随机重试序号。
```

### 8.2 Kline 核心数值

价格、数量、成交量等必须使用 Decimal 或等价精确十进制。

禁止使用二进制浮点数决定：

```text
OHLC；
volume；
quote_volume；
成交量合法性；
窗口判断。
```

### 8.3 payload 边界

禁止在单个字段保存：

```text
完整 Binance Kline 批量响应；
完整历史窗口；
完整 Kline 数组；
不可控大 JSON。
```

允许保存：

```text
小型摘要；
hash；
错误摘要；
受控 schema 的 evidence。
```

---

## 9. 配置项

阶段 1 所有新增配置必须进入 `.env.example` 并带中文注释。

建议至少包括：

```text
DATA_COLLECTION_EXCHANGE=binance
DATA_COLLECTION_MARKET_TYPE=usds_m_futures
DATA_COLLECTION_SYMBOL=BTCUSDT
DATA_COLLECTION_TIMEFRAMES=4h,1d
DATA_COLLECTION_4H_LOOKBACK_COUNT=10
DATA_COLLECTION_1D_LOOKBACK_COUNT=5
DATA_BACKFILL_KLINE_PAGE_LIMIT
DATA_BACKFILL_MAX_PAGES_PER_RUN
DATA_BACKFILL_MAX_BARS_PER_RUN
MARKET_SNAPSHOT_4H_LOOKBACK_COUNT=500
MARKET_SNAPSHOT_1D_LOOKBACK_COUNT=365
```

Binance 公共行情 Gateway 相关配置按 `binance_gateway.md` 进入 `.env.example`。

本阶段不需要 Binance API key，因为 Kline 与 server time 为公共行情能力。

如果某个环境要求代理、超时或 base_url 配置，也必须进入 `.env.example`，不得硬编码。

---

## 10. 实施顺序

### 10.1 建立 market_data 模型与迁移

执行内容：

```text
创建 Kline；
创建 DataCollectionRun；
创建 DataQualityResult；
创建 DataQualityIssue；
创建 BackfillRequest；
创建 BackfillRun；
创建 BackfillIssue；
创建 DataConflict；
创建 MarketSnapshot；
添加唯一约束和必要索引；
生成 migration。
```

验收重点：

```text
Kline 唯一键正确；
业务时间字段为 UTC 语义；
Decimal 字段精度明确；
对象之间的正式外键清楚；
没有用大 JSON 逃避表结构。
```

### 10.2 实现 BinancePublicMarketGateway 最小能力

执行内容：

```text
实现 get_server_time；
实现 get_klines；
实现 market_type 校验；
实现固定采集域校验；
实现超时、错误分类和脱敏日志；
实现 fake gateway；
禁止 raw request 暴露给业务模块。
```

验收重点：

```text
DataCollection / DataBackfill 只能使用 server time 和 Kline；
请求 Kline 不传 timeZone；
测试默认使用 fake gateway；
真实请求能力受配置控制；
不实现账户、订单、成交或 mark price 能力。
```

### 10.3 实现 Kline 写入公共能力

执行内容：

```text
实现 Kline 标准化；
实现已收盘判断；
实现唯一键幂等写入；
实现一致数据跳过；
实现冲突检测；
实现 Kline 写入锁或等价并发保护；
实现 Decimal 转换与字段校验。
```

验收重点：

```text
未收盘 Kline 不写入；
重复采集不重复插入；
冲突不覆盖；
DataCollection 与 DataBackfill 共用写入规则；
Redis 不可用时不能破坏 MySQL 事实。
```

### 10.4 实现 DataCollection service

执行内容：

```text
实现 historical；
实现 latest_closed；
实现 incremental；
实现 backfill_source_fetch 所需的可信源拉取能力边界；
实现 lookback window；
写 DataCollectionRun；
写必要 AlertEvent；
返回稳定输出合同。
```

验收重点：

```text
只采集 Binance USDS-M BTCUSDT 4h / 1d；
只写已收盘 Kline；
成功不等于 DataQuality PASS；
不生成 DataQualityResult；
不生成 MarketSnapshot。
```

### 10.5 实现 DataQuality service

执行内容：

```text
读取 Kline；
计算 expected_open_times；
检查窗口覆盖；
检查时间字段；
检查周期边界；
检查已收盘；
检查连续性；
检查缺失；
检查重复；
检查 OHLC；
检查成交量；
检查数据来源；
检查冲突；
写 DataQualityResult；
写 DataQualityIssue；
必要时创建 BackfillRequest；
写必要 AlertEvent。
```

验收重点：

```text
任一 issue 都不得 PASS；
PASS 才 allows_downstream；
FAIL / BLOCKED / FAILED / UNKNOWN 均阻断；
可回补问题幂等创建 BackfillRequest；
DataQuality 不请求 Binance；
DataQuality 不修改 Kline。
```

### 10.6 实现 DataBackfill service

执行内容：

```text
实现 BackfillRequest claim；
实现 initial_historical_backfill；
实现 gap_backfill；
实现 manual_range_backfill；
实现 conflict_recheck；
实现 failure_recovery_backfill；
实现分页与 bars 上限；
实现 missing_open_times 精确过滤；
写 BackfillRun / BackfillIssue / DataConflict；
标记 requires_quality_recheck。
```

验收重点：

```text
BackfillRun success 不等于 DataQuality PASS；
回补后必须重新 DataQuality；
冲突不覆盖；
超过上限不写部分 Kline；
DataBackfill 不直接调用 DataQuality service；
DataBackfill 不生成 MarketSnapshot。
```

### 10.7 实现 MarketSnapshot service

执行内容：

```text
校验采集域；
校验 analysis_close_time_utc；
计算 4h 窗口；
计算 1d 窗口；
读取并校验 DataQualityResult；
读取并校验 Kline 窗口；
创建或复用 MarketSnapshot；
写必要 AlertEvent；
返回 market_snapshot_id。
```

验收重点：

```text
4h 与 1d 都必须 PASS；
短窗口 PASS 不得授权长窗口；
1d 新鲜度独立判断；
payload_summary 不保存完整 Kline；
created 后才允许 FeatureLayer。
```

### 10.8 建立薄入口

本阶段可以建立 management command 和 Celery task 作为薄入口。

允许：

```text
手动触发 DataCollection；
手动触发 DataQuality；
手动触发 DataBackfill；
手动创建 MarketSnapshot；
输出结构化摘要。
```

禁止：

```text
在 command / task 中写业务逻辑；
在 command / task 中直接请求 Binance；
在 command / task 中直接写 Kline；
在 command / task 中直接发送 Hermes；
在 command / task 中进入 FeatureLayer 或交易链路。
```

本阶段不实现完整 PipelineOrchestrator。

### 10.9 建立测试

测试必须覆盖：

```text
Gateway fake；
DataCollection；
DataQuality；
DataBackfill；
MarketSnapshot；
幂等；
并发；
Redis 不可用；
AlertEvent 脱敏；
UTC 时间边界；
dry-run；
command / task 薄入口。
```

测试默认不得访问真实 Binance。

---

## 11. 编排边界

本阶段不实现正式 PipelineOrchestrator。

但 service 输入输出必须为后续编排适配做好准备：

```text
每个 service 接收 business_request_key；
每个 service 接收 trace_id；
每个 service 接收 trigger_source；
每个 service 返回稳定 status；
每个 service 返回业务对象 id；
每个 service 不依赖 orchestration_run_id；
每个业务对象不保存或查询 orchestration_run_id。
```

后续 PipelineOrchestrator 可以通过 adapter 调用这些 service，并把业务对象写入 OrchestrationBusinessObjectLink。

阶段 1 不得为了临时串流程，把编排逻辑写进某个 market_data service。

---

## 12. dry-run 规则

### 12.1 DataCollection dry-run

可以：

```text
校验参数；
计算请求窗口；
读取已有 Kline 覆盖情况；
返回预计请求摘要。
```

不得：

```text
写 Kline；
写正式 DataCollectionRun；
写正式 AlertEvent；
触发 DataQuality；
触发 MarketSnapshot。
```

### 12.2 DataQuality dry-run

可以：

```text
读取 Kline；
计算 issue 摘要；
返回预计 BackfillRequest 范围。
```

不得：

```text
写 DataQualityResult；
写 DataQualityIssue；
写 BackfillRequest；
写正式 AlertEvent；
修改 Kline。
```

### 12.3 DataBackfill dry-run

可以：

```text
通过 fake Gateway 或明确受控真实公共 Gateway 预览回补；
读取已有 Kline；
比较插入、跳过、冲突。
```

不得：

```text
写正式 Kline；
写终态 BackfillRun；
写正式 AlertEvent；
要求 DataQuality 复检；
生成 MarketSnapshot。
```

默认测试必须使用 fake Gateway。

### 12.4 MarketSnapshot dry-run

可以：

```text
计算窗口；
读取 DataQualityResult；
读取 Kline；
返回是否可创建的摘要。
```

不得：

```text
写 MarketSnapshot；
写正式 AlertEvent；
触发 FeatureLayer；
请求 Binance。
```

---

## 13. AlertEvent 边界

本阶段各模块只写 AlertEvent，不直接发送 Hermes。

需要写 AlertEvent 的典型情况：

```text
采集域不匹配；
Gateway failed / unknown；
Kline 未收盘或无法确认；
Kline 数据冲突；
DataQuality FAIL / BLOCKED / FAILED / UNKNOWN；
BackfillRun blocked / failed / conflict / unknown；
BackfillRequest claim 异常；
MarketSnapshot blocked / failed / unknown；
数据库写入失败；
重复异常超过阈值。
```

AlertEvent 禁止包含：

```text
完整 Binance 响应；
完整 Kline 批量数据；
API key；
secret；
signature；
认证 header；
不可控大 JSON。
```

Notifications 投递留到后续运行与通知阶段。

---

## 14. Redis 使用边界

阶段 1 可以使用 Redis：

```text
Kline 写入锁；
短期采集锁；
短期回补锁；
短期任务状态；
短期限频辅助；
Celery broker / result backend。
```

Redis 不得作为：

```text
Kline 唯一事实来源；
DataQualityResult 唯一事实来源；
BackfillRequest 唯一事实来源；
BackfillRun 唯一事实来源；
MarketSnapshot 唯一事实来源；
DataQuality PASS 的替代依据。
```

Redis 不可用时：

```text
不得丢失 MySQL 事实；
不得默认放行下游；
如果无法保证并发安全，应 blocked / failed / unknown。
```

---

## 15. 异常与 unknown 处理

本阶段必须统一保守处理：

```text
blocked = 前置条件或安全条件不满足；
failed = 本地系统或外部明确失败；
unknown = 无法确认外部结果、写入结果或事务结果；
no_action = 合法执行但没有新数据或无需动作；
succeeded = 明确完成且结果可按本模块合同消费。
```

规则：

```text
unknown 不得当作 succeeded；
unknown 不得当作 failed 后继续放行；
blocked / failed / unknown 不得生成可消费下游对象；
DataCollection succeeded 不等于 DataQuality PASS；
BackfillRun success 不等于 DataQuality PASS；
MarketSnapshot created 才能进入 FeatureLayer。
```

---

## 16. 本阶段不实现

阶段 1 明确不实现：

```text
FeatureLayer；
AtomicSignal；
DomainSignal；
MarketRegime；
StrategyRouting；
StrategySignal；
StrategySignalQuality；
DecisionSnapshot；
StrategyAnalysisRelease；
Binance Account Sync；
PriceSnapshot；
OrderPlan；
CandidateOrderIntent；
RiskCheck；
ApprovedOrderIntent；
ExecutionPreparation；
Execution；
OrderStatusSync；
FillSync；
PipelineOrchestrator；
RuntimeGuard；
Notifications 投递；
OpsConsole 页面；
ReviewDataset；
项目内大模型调用；
WebSocket；
多交易所；
多品种主链路；
模拟交易运行模式；
真实交易。
```

阶段 1 也不得实现：

```text
人工编辑 Kline；
自动修复 Kline；
自动覆盖冲突数据；
用 WebSocket 拼接正式 Kline；
用大模型生成或修补行情数据。
```

---

## 17. 测试计划

### 17.1 Gateway 测试

必须测试：

```text
只能调用 get_server_time 和 get_klines；
没有 raw request 暴露给业务模块；
请求 Kline 不传 timeZone；
market_type 只允许 usds_m_futures 用于采集域；
symbol 只允许 BTCUSDT 用于采集域；
fake gateway 可替换真实实现；
错误结果脱敏；
测试默认不访问真实 Binance。
```

### 17.2 DataCollection 测试

必须测试：

```text
只采集 4h / 1d；
只采集 Binance USDS-M BTCUSDT；
未收盘 Kline 不写入；
重复 Kline 幂等跳过；
冲突 Kline 不覆盖；
lookback window 生效；
DataCollectionRun 记录摘要；
Gateway unknown 不放行；
DataCollection 不生成 DataQualityResult；
DataCollection 不生成 MarketSnapshot。
```

### 17.3 DataQuality 测试

必须测试：

```text
不调用 Binance；
UTC 窗口检查；
4h / 1d 边界检查；
缺失检查；
连续性检查；
重复检查；
未收盘检查；
OHLC 检查；
成交量检查；
数据来源检查；
冲突检查；
PASS 才 allows_downstream；
任一 issue 都不 PASS；
可回补问题幂等创建 BackfillRequest；
DataQuality 不修改 Kline。
```

### 17.4 DataBackfill 测试

必须测试：

```text
BackfillRequest 原子 claim；
终态请求不再执行；
Kline 写入锁；
分页上限；
bars 上限；
missing_open_times 精确过滤；
额外 open_time 被过滤；
未收盘 Kline 被过滤；
冲突不覆盖；
BackfillRun success 后 requires_quality_recheck；
BackfillRun success 不生成 DataQualityResult；
BackfillRun success 不生成 MarketSnapshot。
```

### 17.5 MarketSnapshot 测试

必须测试：

```text
不调用 Binance；
4h 与 1d 都必须 PASS；
短窗口 PASS 不授权长窗口；
1d 新鲜度独立判断；
Kline 数量不足时 blocked；
Kline 不连续时 blocked；
未收盘 Kline blocked；
相同 business_request_key 幂等；
并发创建最终只有一个 created；
payload_summary 不保存完整 Kline；
MarketSnapshot 非 created 不允许 FeatureLayer。
```

### 17.6 安全测试

必须测试：

```text
测试环境无法误连真实 Binance；
AlertEvent 不包含密钥和完整响应；
Redis 不可用时不丢失 MySQL 事实；
command 只调用 service；
Celery task 只调用 service；
dry-run 不写正式结果；
所有业务时间使用 UTC；
trace_id 不作为幂等键。
```

---

## 18. 阶段验收命令

具体命令以项目实际依赖管理工具为准。

至少需要等价执行：

```text
python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py migrate
pytest
```

如果使用 `uv`：

```text
uv run python manage.py check
uv run python manage.py makemigrations --check --dry-run
uv run python manage.py migrate
uv run pytest
```

如果使用 `poetry`：

```text
poetry run python manage.py check
poetry run python manage.py makemigrations --check --dry-run
poetry run python manage.py migrate
poetry run pytest
```

阶段回报必须说明实际运行了哪些命令。

---

## 19. 阶段通过标准

阶段 1 通过必须满足：

```text
Kline 只来自 BinancePublicMarketGateway；
当前采集域固定为 Binance USDS-M BTCUSDT；
当前只支持 4h / 1d；
只写已收盘 Kline；
所有时间使用 UTC；
Kline 唯一键与数据库约束正确；
重复采集幂等；
冲突不覆盖；
DataCollectionRun 可审计；
DataQuality 能识别主要质量问题；
DataQuality PASS 才允许 MarketSnapshot；
可回补问题能创建 BackfillRequest；
DataBackfill 能回补并要求复检；
BackfillRun success 不直接放行；
MarketSnapshot 同时固定 4h 与 1d 窗口；
MarketSnapshot created 才允许 FeatureLayer；
所有异常保守处理；
必要异常写 AlertEvent；
测试默认不访问真实 Binance；
本阶段不涉及真实交易。
```

---

## 20. 阶段失败标准

出现以下任一情况，本阶段不得通过：

```text
业务模块直接创建 Binance HTTP client；
业务模块直接拼接 Binance endpoint；
请求 Kline 传入 timeZone；
DataCollection 读取 active trading domain；
未收盘 Kline 写入正式 Kline；
冲突 Kline 被覆盖；
DataCollectionRun 被当作 DataQuality PASS；
BackfillRun success 被当作 DataQuality PASS；
DataQuality 请求 Binance；
DataQuality 修改 Kline；
MarketSnapshot 忽略 DataQualityResult；
MarketSnapshot 只固定 4h 不固定 1d；
MarketSnapshot payload 保存完整 Kline 数组；
Redis 成为核心行情事实唯一来源；
测试访问真实 Binance；
本阶段提前实现策略、账户、价格、订单、风控、执行或真实交易。
```

---

## 21. 交付回报要求

阶段 1 编码完成后，回报必须说明：

```text
本阶段实现了什么；
新增和修改了哪些文件；
主要调用链路是什么；
是否写库；
是否访问 Redis；
是否访问 Binance；
是否发送 Hermes；
是否调用大模型；
是否涉及交易执行；
是否涉及真实交易；
是否涉及 FeatureLayer；
是否涉及 AtomicSignal；
是否涉及 DecisionSnapshot；
是否涉及 Binance Account Sync；
是否涉及 PriceSnapshot；
是否涉及 OrderPlan / CandidateOrderIntent；
是否涉及 RiskCheck / ApprovedOrderIntent；
是否涉及 ExecutionPreparation / Execution；
是否写 AlertEvent；
dry-run / confirm-write 行为；
异常处理方式；
测试命令和结果；
本阶段明确不负责什么；
是否违反 project_invariants.md。
```

---

## 22. 下一阶段入口

阶段 1 验收通过后，下一步进入：

```text
docs/plans/strategy_analysis_implementation_plan.md
```

也就是策略分析框架阶段。

在进入下一阶段前，不应开始账户同步、价格快照、订单计划、风控、执行或后台复盘能力。
