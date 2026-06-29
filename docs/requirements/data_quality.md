# DataQuality 需求

## 1. 模块定位

DataQuality 是行情数据链路的质量闸门。

本模块负责读取已落库的 `Kline`，检查指定 UTC 窗口内的 K 线是否完整、连续、边界正确、数值合法、来源可信，并输出 `DataQualityResult`。

当前 DataQuality 只对 DataCollection 固定采集域的数据做主链路质量授权：

```text
exchange = binance；
market_type = usds_m_futures；
symbol = BTCUSDT；
timeframe = 4h / 1d。
```

DataQuality 的核心对象是：

```text
DataQualityResult
DataQualityIssue
```

DataQuality 可以在发现明确可回补问题时创建 `BackfillRequest`，但不执行回补。

DataQuality 不是：

```text
K 线采集模块；
Binance 请求模块；
数据回补执行模块；
数据修复模块；
MarketSnapshot 生成模块；
特征计算模块；
信号模块；
策略模块；
订单规划模块；
风控模块；
执行模块；
通知投递模块；
复盘分析模块。
```

一句话：

```text
DataQuality 只决定一段已落库的 Binance USDS-M BTCUSDT 4h / 1d Kline 是否允许进入 MarketSnapshot；它不采集、不回补、不修数、不交易。
```

## 2. 设计目标

DataQuality 的目标是：

```text
检查 Kline 是否可信；
发现任何质量问题时阻断基于该质量窗口的当前主链路下游；
记录 DataQualityResult；
记录 DataQualityIssue；
为可回补问题创建 BackfillRequest；
为不可自动处理问题留下审计证据；
必要时写 AlertEvent；
防止坏数据进入 MarketSnapshot；
防止坏数据进入 FeatureLayer、信号、策略、订单和交易链路。
```

当前采用严格阻断策略：

```text
只要检查窗口内存在任何质量问题，
DataQualityResult 就不得为 PASS，
基于该质量窗口的下游不得生成 MarketSnapshot。
```

严格阻断不表示系统停止处理问题。可回补问题交给 DataBackfill；不可回补或冲突问题交给人工审计或后续恢复流程。

## 3. Binance 请求边界

DataQuality 不得直接请求 Binance。

禁止：

```text
直接调用 Binance REST；
直接创建 Binance HTTP client；
直接调用 BinancePublicMarketGateway；
直接读取 Binance server time；
直接拉取 Kline；
直接读取账户、订单、成交或持仓；
直接调用任何签名接口。
```

涉及 Binance 请求的职责归属：

```text
DataCollection：正常历史采集、最新已收盘采集、增量 lookback 采集；
DataBackfill：缺口回补、冲突复核、人工指定区间回补；
BinanceGateway：统一外部请求、限频、超时、错误分类和脱敏。
```

DataQuality 只能使用已落库事实：

```text
Kline；
DataCollectionRun；
BackfillRun；
DataBackfill 标记的复检需求；
已有 DataQualityResult / DataQualityIssue。
```

如果 DataQuality 需要判断“理论上应该存在的 Kline”，必须由调用方传入明确的 UTC 检查窗口、期望最新 Kline 或质量参考时间，不得临时请求 Binance。

## 4. 负责事项

DataQuality 负责：

```text
读取待检查 Kline；
校验 data_collection_domain；
校验检查窗口；
检查 Kline 时间字段；
检查 timeframe 周期边界；
检查 Kline 是否已收盘；
检查 Kline 连续性；
检查 Kline 缺失；
检查 Kline 重复；
检查 OHLC 合法性；
检查成交量合法性；
检查数据来源合法性；
检查同一唯一键数据冲突；
检查窗口覆盖范围；
写入 DataQualityResult；
写入 DataQualityIssue；
为可回补问题幂等创建 BackfillRequest；
必要时写 AlertEvent；
返回是否允许下游继续。
```

## 5. 不负责事项

DataQuality 不负责：

```text
采集 Kline；
执行回补；
请求 Binance；
修复 Kline；
覆盖 Kline；
删除 Kline；
修改 OHLCV；
生成 MarketSnapshot；
计算 FeatureValue；
生成 AtomicSignal；
生成 DomainSignal；
生成 MarketRegime；
执行 StrategyRouting；
生成 StrategySignal；
生成 StrategySignalQuality；
生成 DecisionSnapshot；
读取账户或持仓；
生成 PriceSnapshot；
生成 OrderPlan；
生成 CandidateOrderIntent；
执行 RiskCheck；
生成 ApprovedOrderIntent；
执行 ExecutionPreparation；
提交订单；
查询订单状态；
查询成交；
调用 DeepSeek；
同步发送 Hermes；
写跨流程风险状态；
通知风控系统。
```

DataQuality 不得因为发现问题而直接启动下游或恢复流程。

## 6. 严格阻断策略

只要存在任一 DataQualityIssue，基于本次质量窗口的当前主链路下游必须被阻断。

阻断范围包括：

```text
MarketSnapshot；
FeatureLayer；
AtomicSignal；
DomainSignal；
MarketRegime；
StrategyRouting；
StrategySignal；
StrategySignalQuality；
DecisionSnapshot；
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
ReviewDataset。
```

说明：

```text
DataQuality 不调用这些下游模块；
DataQuality 只通过结果状态阻断当前编排主链路继续；
PipelineOrchestrator 根据 BusinessStepAdapter 的统一结果停止或转入回补流程。
```

当前不设计 WARN 放行机制。`severity` 只影响展示、通知和统计，不影响是否放行。

## 7. 输入合同

DataQualityService 输入至少包括：

```text
exchange；
market_type；
symbol；
timeframe；
check_start_open_time_utc；
check_end_open_time_utc；
expected_latest_open_time_utc；
expected_count；
check_scope；
quality_reference_time_utc；
source_collection_run_id；
source_backfill_run_id；
business_request_key；
trace_id；
trigger_source。
```

### 7.1 exchange / market_type / symbol

必须与当前 data_collection_domain 一致。

规则：

```text
exchange 当前为 binance；
market_type 当前为 usds_m_futures；
symbol 当前为 BTCUSDT；
DataQuality 不得用参数热切 data_collection_domain；
非 data_collection_domain 数据不得进入当前主链路质量授权。
```

如果输入与 data_collection_domain 不一致，结果必须 `BLOCKED`，不得读取非当前采集域数据授权下游。

### 7.2 timeframe

当前主链路允许：

```text
4h；
1d。
```

其他 timeframe 必须 `BLOCKED`，除非对应需求、DataCollection、DataBackfill 和 MarketSnapshot 已同步扩展。

### 7.3 check_start_open_time_utc / check_end_open_time_utc

这两个字段定义本次检查覆盖的 Kline open_time 范围。

规则：

```text
必须使用 UTC；
必须落在 timeframe 周期边界；
start 必须小于或等于 end；
不得使用本地时间；
不得使用 PRC 时间；
不得由 DataQuality 根据本机时间自行猜测。
```

### 7.4 expected_latest_open_time_utc

`expected_latest_open_time_utc` 表示调用方期望当前检查窗口至少覆盖到哪一根最新已收盘 Kline。

用途：

```text
检测最新 Kline 是否缺失；
检测数据采集是否滞后；
为 MarketSnapshot 确认目标窗口覆盖。
```

DataQuality 只能校验输入是否被 Kline 覆盖，不得自行请求 Binance 判断最新 Kline。

### 7.5 expected_count

`expected_count` 表示本次窗口内理论应存在的 Kline 数量。

如果调用方未提供，DataQuality 可以根据 timeframe 和 UTC 开始/结束边界计算。

计算必须基于 UTC 周期，不得基于数据库自增 id。

### 7.6 quality_reference_time_utc

`quality_reference_time_utc` 是本次质量判断使用的可信参考时间。

允许来源：

```text
DataCollectionRun.binance_server_time_utc；
BackfillRun.binance_server_time_utc；
编排层按 UTC 周期传入的分析参考时间；
人工入口明确传入的 UTC 参考时间。
```

禁止来源：

```text
服务器本地时区；
用户 IP 时区；
PRC 本地时间；
DataQuality 临时请求 Binance server time。
```

如果检查需要参考时间，但未提供或来源不可追溯，结果必须 `BLOCKED`。

### 7.7 check_scope

允许：

```text
analysis_cycle；
daily_audit；
manual_check；
backfill_recheck；
recovery_scan。
```

规则：

```text
check_scope 只影响审计、AlertEvent 类型和调度语义；
check_scope 不得降低质量标准；
任何 scope 发现 issue 都不得 PASS。
```

### 7.8 business_request_key

业务幂等键必须稳定。

至少覆盖：

```text
exchange；
market_type；
symbol；
timeframe；
check_start_open_time_utc；
check_end_open_time_utc；
expected_latest_open_time_utc；
check_scope；
source_collection_run_id；
source_backfill_run_id。
```

`trace_id` 不得作为 DataQuality 幂等键。

## 8. 输出合同

DataQuality 输出至少包括：

```text
status；
reason_code；
data_quality_result_id；
issue_count；
backfill_request_ids；
allows_downstream；
coverage_start_open_time_utc；
coverage_end_open_time_utc；
expected_count；
actual_count；
missing_count；
duplicate_count；
conflict_count；
trace_id。
```

`allows_downstream = true` 只有在 `status = PASS` 时允许。

所有非 PASS 状态都必须：

```text
allows_downstream = false；
不得生成 MarketSnapshot；
不得进入策略和交易链路。
```

## 9. DataQualityResult

DataQualityResult 表示一次质量检查的总体结论。

状态包括：

```text
PASS；
FAIL；
BLOCKED；
FAILED；
UNKNOWN。
```

语义：

```text
PASS = 检查完成，无任何质量问题，允许下游消费；
FAIL = 检查完成，发现一个或多个质量问题；
BLOCKED = 输入、采集域、参考时间或前置条件不满足，无法执行有效检查；
FAILED = 本地系统异常或数据库异常；
UNKNOWN = 无法确认检查或写入结果。
```

DataQualityResult 至少表达：

```text
business_request_key；
trace_id；
trigger_source；
exchange；
market_type；
symbol；
timeframe；
check_scope；
check_start_open_time_utc；
check_end_open_time_utc；
expected_latest_open_time_utc；
quality_reference_time_utc；
source_collection_run_id；
source_backfill_run_id；
status；
reason_code；
allows_downstream；
expected_count；
actual_count；
issue_count；
missing_count；
duplicate_count；
conflict_count；
coverage_start_open_time_utc；
coverage_end_open_time_utc；
created_at_utc；
finished_at_utc。
```

规则：

```text
PASS 必须 issue_count = 0；
PASS 必须 allows_downstream = true；
FAIL / BLOCKED / FAILED / UNKNOWN 必须 allows_downstream = false；
同一 business_request_key 重复执行应返回已有结果或幂等复用；
DataQualityResult 不能替代 MarketSnapshot。
```

## 10. DataQualityIssue

DataQualityIssue 表示具体质量问题。

Issue 类型至少包括：

```text
EMPTY_KLINE_SET；
MISSING_KLINE；
LATEST_KLINE_DELAYED；
NON_CONTINUOUS_KLINE；
DUPLICATE_KLINE；
UNCLOSED_KLINE；
INVALID_TIME_BOUNDARY；
INVALID_OPEN_CLOSE_TIME；
INVALID_OHLC；
INVALID_VOLUME；
INVALID_DATA_SOURCE；
UNEXPECTED_SYMBOL；
UNEXPECTED_MARKET_TYPE；
UNEXPECTED_TIMEFRAME；
DATA_CONFLICT；
WINDOW_COVERAGE_INSUFFICIENT；
DATABASE_INCONSISTENCY。
```

DataQualityIssue 至少表达：

```text
data_quality_result_id；
trace_id；
exchange；
market_type；
symbol；
timeframe；
issue_type；
severity；
affected_start_open_time_utc；
affected_end_open_time_utc；
affected_open_time_utc；
expected_value_summary；
actual_value_summary；
message；
is_backfillable；
suggested_backfill_mode；
created_at_utc。
```

规则：

```text
severity 不影响 PASS / FAIL；
只要存在 issue，DataQualityResult 就不得 PASS；
Issue 摘要不得保存不可控大 JSON；
Issue 不得包含完整 Binance 响应；
Issue 不得包含密钥或认证 header。
```

## 11. BackfillRequest 创建边界

DataQuality 可以为明确可回补问题创建 BackfillRequest。

可创建 BackfillRequest 的问题：

```text
EMPTY_KLINE_SET；
MISSING_KLINE；
LATEST_KLINE_DELAYED；
NON_CONTINUOUS_KLINE；
WINDOW_COVERAGE_INSUFFICIENT。
```

可以创建复核型 BackfillRequest 的问题：

```text
DATA_CONFLICT。
```

但 `DATA_CONFLICT` 的回补只用于从可信源重新拉取并对照，不得自动覆盖已有 Kline。

不应自动创建普通回补的类型：

```text
DUPLICATE_KLINE；
UNCLOSED_KLINE；
INVALID_TIME_BOUNDARY；
INVALID_OPEN_CLOSE_TIME；
INVALID_OHLC；
INVALID_VOLUME；
INVALID_DATA_SOURCE；
UNEXPECTED_SYMBOL；
UNEXPECTED_MARKET_TYPE；
UNEXPECTED_TIMEFRAME；
DATABASE_INCONSISTENCY。
```

这些问题需要人工审计、数据修复流程或明确的冲突复核流程，不得静默处理。

## 12. BackfillRequest 幂等

BackfillRequest 的幂等键至少包括：

```text
exchange；
market_type；
symbol；
timeframe；
backfill_mode；
requested_start_open_time_utc；
requested_end_open_time_utc；
missing_open_times；
source_quality_issue_type。
```

规则：

```text
同一质量问题重复检查时，应复用已有 pending / running / retryable failed BackfillRequest；
不得因为重复运行 DataQuality 无限创建等价 BackfillRequest；
missing_open_times 必须作为幂等键的一部分；
missing_open_times 不同，应视为不同回补请求；
BackfillRequest 只是请求记录，实际回补动作由 DataBackfill 执行。
```

DataQuality 不得调用 BackfillService，不得领取或执行 BackfillRequest。

## 13. 检查窗口与覆盖

DataQuality 必须确认检查窗口被 Kline 完整覆盖。

必须计算：

```text
expected_open_times；
expected_count；
actual_open_times；
actual_count；
missing_open_times；
coverage_start_open_time_utc；
coverage_end_open_time_utc。
```

PASS 条件至少包括：

```text
actual_count = expected_count；
missing_open_times 为空；
coverage_start_open_time_utc <= check_start_open_time_utc；
coverage_end_open_time_utc >= check_end_open_time_utc；
所有 Kline 均通过后续检查。
```

覆盖不足时：

```text
DataQualityIssue = WINDOW_COVERAGE_INSUFFICIENT 或 MISSING_KLINE；
DataQualityResult = FAIL；
allows_downstream = false。
```

短窗口 DataQualityResult 不得授权更长窗口的 MarketSnapshot。

## 14. 时间字段检查

必须检查：

```text
open_time_utc 存在；
close_time_utc 存在；
open_time_utc < close_time_utc；
close_time_utc = open_time_utc + timeframe_interval；
open_time_utc 使用 UTC；
close_time_utc 使用 UTC。
```

禁止：

```text
使用数据库自增 id 判断时间顺序；
使用本地时间判断；
使用 PRC 时间判断；
使用运行机器时区判断；
根据请求 IP 推断时间。
```

异常类型：

```text
INVALID_OPEN_CLOSE_TIME；
INVALID_TIME_BOUNDARY。
```

## 15. 周期边界检查

4h Kline 的 `open_time_utc` 必须落在 UTC 4 小时边界：

```text
00:00；
04:00；
08:00；
12:00；
16:00；
20:00。
```

1d Kline 的 `open_time_utc` 必须落在 UTC 日线边界：

```text
00:00。
```

边界错误时：

```text
DataQualityIssue = INVALID_TIME_BOUNDARY；
DataQualityResult = FAIL。
```

## 16. 已收盘检查

正式 Kline 表中只允许已收盘 Kline。

检查规则：

```text
close_time_utc <= quality_reference_time_utc；
close_time_utc = open_time_utc + timeframe_interval；
Kline 不得带有未收盘来源标记；
Kline 不得来自 websocket_derived。
```

如果缺少 `quality_reference_time_utc` 且本次检查需要验证最新窗口，结果必须 `BLOCKED`。

如发现未收盘 Kline：

```text
DataQualityIssue = UNCLOSED_KLINE；
DataQualityResult = FAIL；
不得创建普通 BackfillRequest；
不得放行下游。
```

## 17. 连续性检查

必须按 `open_time_utc` 正序检查连续性。

4h 规则：

```text
下一根 open_time_utc - 当前 open_time_utc = 4 小时。
```

1d 规则：

```text
下一根 open_time_utc - 当前 open_time_utc = 1 天。
```

禁止使用数据库自增 id 判断顺序、连续性或缺口。

不连续时：

```text
DataQualityIssue = NON_CONTINUOUS_KLINE；
DataQualityResult = FAIL；
可创建 gap_backfill BackfillRequest。
```

## 18. 缺失检查

DataQuality 必须根据 `expected_open_times` 检查缺失。

如果检查范围内缺少应存在的 Kline：

```text
DataQualityIssue = MISSING_KLINE；
DataQualityResult = FAIL；
missing_open_times 必须记录；
可创建 gap_backfill BackfillRequest。
```

如果整个窗口为空：

```text
DataQualityIssue = EMPTY_KLINE_SET；
DataQualityResult = FAIL；
可创建 gap_backfill BackfillRequest。
```

## 19. 最新 Kline 延迟检查

如果输入包含 `expected_latest_open_time_utc`，DataQuality 必须确认对应 Kline 已存在并覆盖到目标窗口。

缺失时：

```text
DataQualityIssue = LATEST_KLINE_DELAYED；
DataQualityResult = FAIL；
可创建 failure_recovery_backfill 或 gap_backfill BackfillRequest。
```

DataQuality 不得通过请求 Binance 判断最新 Kline 是否已经出现。该判断必须基于调用方传入的 UTC 目标。

## 20. 重复检查

同一 Kline 唯一业务键不得存在多条有效记录。

唯一业务键至少包括：

```text
exchange；
market_type；
symbol；
timeframe；
open_time_utc。
```

如果同一唯一业务键存在多条有效记录：

```text
DataQualityIssue = DUPLICATE_KLINE；
DataQualityResult = FAIL。
```

说明：

```text
数据库应通过唯一约束防止重复；
DataQuality 仍需识别历史脏数据、软删除状态、人工导入或旧代码遗留造成的重复；
DataQuality 不得自动删除重复记录。
```

## 21. OHLC 合法性检查

必须检查：

```text
open_price 存在且 > 0；
high_price 存在且 > 0；
low_price 存在且 > 0；
close_price 存在且 > 0；
high_price >= low_price；
high_price >= open_price；
high_price >= close_price；
low_price <= open_price；
low_price <= close_price。
```

异常时：

```text
DataQualityIssue = INVALID_OHLC；
DataQualityResult = FAIL。
```

DataQuality 不得自动修正价格。

## 22. 成交量合法性检查

必须检查：

```text
volume 存在且 >= 0；
quote_volume 存在且 >= 0；
trade_count 存在时必须 >= 0。
```

对于 Binance USDS-M BTCUSDT 的 4h / 1d Kline：

```text
volume = 0；
quote_volume = 0；
```

应视为质量问题，除非后续需求明确允许某些低流动性品种零成交。

异常时：

```text
DataQualityIssue = INVALID_VOLUME；
DataQualityResult = FAIL。
```

## 23. 数据来源检查

当前正式 Kline 合法数据来源只能是：

```text
binance_rest。
```

禁止来源：

```text
manual_repair；
system_repair；
human_edit；
manual_input；
websocket_derived；
local_generated。
```

发现非法来源：

```text
DataQualityIssue = INVALID_DATA_SOURCE；
DataQualityResult = FAIL。
```

DataQuality 不得把人工来源 Kline 视为可信事实。

## 24. 数据冲突检查

数据冲突指同一唯一业务键对应的核心行情字段存在不一致。

核心字段包括：

```text
open_price；
high_price；
low_price；
close_price；
volume；
quote_volume；
trade_count。
```

数据冲突可能来自：

```text
DataCollection 冲突摘要；
DataBackfill 冲突摘要；
历史脏数据；
重复有效记录；
人工导入残留。
```

发现冲突时：

```text
DataQualityIssue = DATA_CONFLICT；
DataQualityResult = FAIL；
可以创建 conflict_recheck BackfillRequest；
不得自动覆盖；
不得自动删除；
不得自动选择其中一条作为正确值。
```

## 25. Kline 写入入口收窄

允许写入正式 Kline 的模块只有：

```text
DataCollection；
DataBackfill。
```

DataQuality 禁止写入、更新或删除 Kline。

禁止以下模块写入正式 Kline：

```text
MarketSnapshot；
FeatureLayer；
AtomicSignal；
DomainSignal；
MarketRegime；
StrategyRouting；
StrategySignal；
StrategySignalQuality；
DecisionSnapshot；
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
Notifications；
OpsConsole；
ReviewDataset；
大模型；
人工后台直接改表。
```

DataQuality 只能写：

```text
DataQualityResult；
DataQualityIssue；
BackfillRequest；
AlertEvent。
```

## 26. PASS 流程

```text
接收质量检查请求；
校验 data_collection_domain；
校验 timeframe 和 UTC 窗口；
读取已落库 Kline；
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
检查数据冲突；
未发现任何问题；
写 DataQualityResult = PASS；
返回 allows_downstream = true；
允许后续生成基于该质量窗口的 MarketSnapshot。
```

PASS 不写正式 AlertEvent，不创建 BackfillRequest。

## 27. FAIL 流程

```text
接收质量检查请求；
读取已落库 Kline；
执行质量检查；
发现任一问题；
写 DataQualityResult = FAIL；
写 DataQualityIssue；
必要时幂等创建 BackfillRequest；
写 AlertEvent；
返回 allows_downstream = false；
阻断基于该质量窗口的 MarketSnapshot 和后续主链路。
```

FAIL 不得：

```text
修改 Kline；
执行回补；
生成 MarketSnapshot；
继续 FeatureLayer；
继续策略链路；
进入订单链路；
进入交易执行。
```

## 28. BLOCKED / FAILED / UNKNOWN 流程

BLOCKED 场景：

```text
采集域不匹配；
timeframe 不支持；
检查窗口非法；
quality_reference_time_utc 缺失且检查需要它；
输入缺少必要业务上下文；
上游对象状态不允许检查。
```

FAILED 场景：

```text
数据库读取失败；
数据库写入失败；
事务失败；
代码未预期异常；
AlertEvent 写入失败且该事件属于高风险阻断事件。
```

UNKNOWN 场景：

```text
无法确认 DataQualityResult 是否成功写入；
无法确认 BackfillRequest 是否成功创建；
无法确认事务最终状态。
```

所有这些状态都必须：

```text
allows_downstream = false；
不得生成 MarketSnapshot；
不得进入策略和交易链路；
必要时写 AlertEvent 或系统异常日志。
```

## 29. 与 DataCollection 的关系

DataCollection 负责：

```text
通过 BinancePublicMarketGateway 获取已收盘 Kline；
过滤未收盘 Kline；
幂等写入 Kline；
记录 DataCollectionRun；
把可检查范围交给 DataQuality。
```

DataQuality 负责：

```text
读取已落库 Kline；
判断窗口质量；
输出 DataQualityResult；
创建 DataQualityIssue；
必要时创建 BackfillRequest。
```

规则：

```text
DataCollection 成功不等于 DataQuality PASS；
DataCollectionRun 不替代 DataQualityResult；
DataQuality 不得反向调用 DataCollection 采集数据；
DataQuality 不得请求 Binance 验证采集结果。
```

## 30. 与 DataBackfill 的关系

DataQuality 可以创建 BackfillRequest。

DataBackfill 负责：

```text
claim BackfillRequest；
通过 BinancePublicMarketGateway 获取可信源 Kline；
幂等写入 Kline；
记录 BackfillRun；
标记或要求重新 DataQuality。
```

规则：

```text
DataQuality 不执行 BackfillRequest；
DataQuality 不调用 DataBackfill service；
BackfillRun 完成不等于 DataQuality PASS；
回补后必须重新执行 DataQuality；
只有新的 DataQualityResult = PASS，才允许继续 MarketSnapshot。
```

## 31. 与 MarketSnapshot 的关系

MarketSnapshot 只能消费 PASS 的 DataQualityResult。

要求：

```text
DataQualityResult.status = PASS；
DataQualityResult.allows_downstream = true；
DataQualityResult 覆盖 MarketSnapshot 所需窗口；
DataQualityResult 的 exchange / market_type / symbol 与 MarketSnapshot 输入一致；
DataQualityResult 的 timeframe 与 MarketSnapshot 输入一致。
```

MarketSnapshot 不得：

```text
忽略 DataQualityResult；
使用 FAIL / BLOCKED / FAILED / UNKNOWN 的结果；
使用覆盖不足的 PASS；
自行重新执行完整 DataQuality；
直接请求 Binance；
自动回补；
写 Kline。
```

## 32. 与 PipelineOrchestrator 的关系

PipelineOrchestrator 可以编排 DataQuality，但不解释质量细节。

规则：

```text
编排层通过 BusinessStepAdapter 调用 DataQuality service；
adapter 负责把 DataQuality 原始结果映射为 normalized_status 和 flow_action；
DataQuality 返回 DataQualityResult、Issue 和 BackfillRequest 索引；
OrchestrationBusinessObjectLink 可以记录 DataQualityResult、DataQualityIssue、BackfillRequest；
业务对象不得保存或查询 orchestration_run_id；
DataQuality 幂等键不得依赖 orchestration_run_id。
```

如果 DataQuality 创建 BackfillRequest，编排层可以根据步骤定义进入 DataBackfill，但不得由 DataQuality 自己执行回补。

## 33. AlertEvent

DataQuality 在以下情况必须写 AlertEvent：

```text
DataQualityResult = FAIL；
DataQualityResult = BLOCKED 且影响分析链路；
DataQualityResult = FAILED；
DataQualityResult = UNKNOWN；
创建 BackfillRequest；
重复质量失败超过阈值；
发现 DATA_CONFLICT；
发现 DATABASE_INCONSISTENCY。
```

PASS 默认不写正式 AlertEvent。

dry-run 默认不写正式 AlertEvent。

规则：

```text
DataQuality 只写 AlertEvent；
DataQuality 不直接发送 Hermes；
AlertEvent 不得包含完整 Kline 批量数据；
AlertEvent 不得包含完整 Binance 响应；
AlertEvent 不得包含密钥、signature 或认证 header；
Notifications 负责后续投递。
```

如果 AlertEvent 写入失败且本次质量问题会影响下游交易安全，不得静默返回 PASS。

## 34. 数据库、Redis 与外部服务

```text
读 MySQL：是，读取 Kline、DataCollectionRun、BackfillRun 和历史质量结果。
写 MySQL：是，写入 DataQualityResult、DataQualityIssue、BackfillRequest 和 AlertEvent。
访问 Redis：可用于短期防重复、短期任务状态和并发锁，不作为唯一事实。
访问 Binance：否。
发送 Hermes：否，只写 AlertEvent。
调用大模型：否。
涉及交易执行：否。
允许真实交易：否。
```

MySQL 是 DataQualityResult、DataQualityIssue 和 BackfillRequest 的正式事实来源。

Redis 不可用时：

```text
不得丢失质量结果；
不得只依赖 Redis 判断是否已检查；
可以降级为 MySQL 幂等和数据库唯一约束；
如果无法保证并发安全，应 BLOCKED 或 FAILED。
```

## 35. Management command 与 Celery task

DataQuality 的 command / task 只能：

```text
解析参数；
生成或传递 trace_id；
设置 trigger_source；
校验 dry-run / confirm-write；
调用 DataQuality service；
输出结果摘要。
```

禁止：

```text
在 command / task 中直接请求 Binance；
在 command / task 中直接读取或修改 Kline；
在 command / task 中直接创建 MarketSnapshot；
在 command / task 中直接执行 BackfillRequest；
在 command / task 中直接发送 Hermes；
在 command / task 中直接调用 OrderPlan；
在 command / task 中直接调用 RiskCheck；
在 command / task 中直接提交订单。
```

## 36. dry-run

dry-run 用于预览质量检查结果。

dry-run 可以：

```text
校验参数；
读取 Kline；
计算 expected_open_times；
生成临时 issue 摘要；
返回预计 BackfillRequest 范围；
返回是否会阻断基于该质量窗口的当前主链路下游。
```

dry-run 不得：

```text
写 DataQualityResult；
写 DataQualityIssue；
写 BackfillRequest；
写正式 AlertEvent；
修改 Kline；
请求 Binance；
执行回补；
生成 MarketSnapshot；
进入交易链路。
```

## 37. 幂等与并发

DataQuality 必须支持幂等重复执行。

规则：

```text
同一 business_request_key 重复执行应返回同一 DataQualityResult 或等价结果；
不得重复创建等价 DataQualityIssue；
不得重复创建等价 BackfillRequest；
不得重复刷屏 AlertEvent；
并发检查同一 data_collection_domain / timeframe / window 时必须受控；
并发冲突不得导致 PASS 与 FAIL 同时成为有效结果。
```

如果发现同一窗口存在多个有效 DataQualityResult：

```text
必须按状态和创建时间保守选择非 PASS；
必要时创建 DATABASE_INCONSISTENCY issue；
不得让 MarketSnapshot 继续。
```

## 38. 异常处理

异常处理规则：

```text
采集域不匹配 → BLOCKED；
timeframe 不支持 → BLOCKED；
检查窗口非法 → BLOCKED；
quality_reference_time_utc 不可用 → BLOCKED；
Kline 集合为空 → FAIL；
缺失 Kline → FAIL；
发现任一 issue → FAIL；
数据库读取失败 → FAILED；
数据库写入失败 → FAILED 或 UNKNOWN；
BackfillRequest 创建失败 → FAILED；
AlertEvent 写入失败 → 高风险场景 FAILED；
事务结果不可确认 → UNKNOWN。
```

任何异常都不得导致不可信 Kline 进入下游。

## 39. 测试要求

必须测试：

```text
1. DataQuality 不调用 BinanceGateway。
2. DataQuality 不直接创建 Binance HTTP client。
3. DataQuality 不请求 Binance server time。
4. 所有检查窗口使用 UTC。
5. timeframe 边界非法时 BLOCKED 或 FAIL。
6. 采集域不匹配时 BLOCKED。
7. 缺少 quality_reference_time_utc 且检查需要它时 BLOCKED。
8. Kline 空集合时 FAIL。
9. 缺失 Kline 时 FAIL。
10. 最新 Kline 缺失时 FAIL。
11. Kline 不连续时 FAIL。
12. 重复 Kline 时 FAIL。
13. 未收盘 Kline 时 FAIL。
14. open_time / close_time 不合法时 FAIL。
15. OHLC 不合法时 FAIL。
16. volume / quote_volume 不合法时 FAIL。
17. 非法数据来源时 FAIL。
18. 同一唯一键数据冲突时 FAIL。
19. PASS 时 issue_count = 0 且 allows_downstream = true。
20. FAIL / BLOCKED / FAILED / UNKNOWN 时 allows_downstream = false。
21. 可回补问题创建 BackfillRequest。
22. 等价回补请求幂等复用，不重复创建。
23. DATA_CONFLICT 只创建复核请求，不覆盖 Kline。
24. DataQuality 不修改 Kline。
25. DataQuality 不生成 MarketSnapshot。
26. DataQuality 不调用 DataBackfill service。
27. BackfillRun 完成后仍需重新 DataQuality。
28. PASS 默认不写正式 AlertEvent。
29. FAIL / BLOCKED / FAILED / UNKNOWN 写必要 AlertEvent。
30. AlertEvent 不包含完整 Kline 批量数据或密钥。
31. Redis 不可用时质量事实不丢失。
32. command 只调用 service。
33. Celery task 只调用 service。
34. dry-run 不写正式结果、BackfillRequest 或 AlertEvent。
35. 短窗口 PASS 不得授权更长 MarketSnapshot。
36. 默认测试不访问真实 Binance。
```

## 40. 验收标准

DataQuality 验收通过必须满足：

```text
只读取已落库 Kline；
不请求 Binance；
所有业务时间使用 UTC；
只为 Binance USDS-M BTCUSDT 的 4h / 1d Kline 提供当前主链路质量授权；
可以识别缺失、不连续、重复、未收盘、边界错误、OHLC 异常、成交量异常、非法来源和数据冲突；
发现任一 issue 不得 PASS；
PASS 才允许进入 MarketSnapshot；
PASS 必须覆盖目标窗口；
FAIL / BLOCKED / FAILED / UNKNOWN 均阻断基于该质量窗口的当前主链路下游；
可回补问题幂等创建 BackfillRequest；
DataQuality 不执行回补；
DataQuality 不修改 Kline；
DataQuality 不生成 MarketSnapshot；
必要异常写 AlertEvent；
不直接发送 Hermes；
不调用 DeepSeek；
不涉及交易执行；
默认测试不访问真实 Binance。
```

## 41. 当前不包含的能力

当前不包含：

```text
多交易所质量检查；
多采集域同时授权主链路；
多数据源交叉验证；
复杂异常行情评分体系；
WARN 放行机制；
自动修复 Kline；
自动覆盖冲突数据；
自动删除重复数据；
直接请求 Binance；
直接执行回补；
质量可视化看板；
根据质量问题自动暂停真实交易；
根据质量问题自动调整策略参数。
```

## 42. 最终结论

DataQuality 的最终定位是：

```text
作为 Kline 进入 MarketSnapshot 前的强制质量授权边界。
```

一句话：

```text
Binance USDS-M BTCUSDT 的 4h / 1d Kline 采回来还不算可信；只有 DataQuality 明确 PASS 且覆盖目标窗口，后续 MarketSnapshot、特征、信号、策略和交易主链路才可以继续。
```
