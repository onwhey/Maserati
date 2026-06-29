# DataCollection 需求

## 1. 模块定位

DataCollection 是系统行情事实入口。

本模块负责通过受控 BinanceGateway 获取已收盘 K 线，并以可追溯、可幂等、可审计的方式写入 MySQL，为 DataQuality、DataBackfill、MarketSnapshot、FeatureLayer、回测、复盘和后续自动交易链路提供基础行情事实。

DataCollection 的核心对象是：

```text
Kline
DataCollectionRun
```

`Kline` 是系统正式行情事实。`DataCollectionRun` 是一次采集运行的审计记录，不替代 Kline。

DataCollection 不是：

```text
数据质量判断模块；
数据回补决策模块；
MarketSnapshot 生成模块；
特征计算模块；
信号模块；
策略模块；
账户同步模块；
价格事实模块；
订单规划模块；
风控模块；
执行模块；
通知投递模块；
复盘分析模块。
```

## 2. 设计目标

DataCollection 的目标是：

```text
可信获取 Binance 已收盘 K 线；
只把已收盘 K 线写入正式 Kline；
统一使用 UTC 时间；
通过 BinancePublicMarketGateway 请求外部数据；
幂等写入 MySQL；
使用 lookback window 降低短期漏采风险；
发现同一唯一键数据冲突时保守阻断；
记录采集运行审计摘要；
为 DataQuality 提供待检查数据范围；
失败或异常不得静默成功；
不得越权进入策略、风控或交易执行。
```

当前主链路需要的行情周期：

```text
4h；
1d。
```

`4h` 是主策略周期数据。`1d` 是大周期趋势、市场环境和复盘辅助数据。

DataCollection 当前固定采集 Binance USDS-M BTCUSDT 行情数据。

DataCollection 使用独立的采集域配置。采集域由部署级硬配置决定，不受交易运行时 active trading domain 影响，DataCollection 不得根据交易账户域、下单市场域或后台运行时配置切换采集目标。

## 3. 负责事项

DataCollection 负责：

```text
读取固定 data_collection_domain；
校验采集请求范围；
通过 BinancePublicMarketGateway 获取 server time；
通过 BinancePublicMarketGateway 获取 K 线；
过滤未收盘 K 线；
规范化 Binance K 线时间和数值；
按唯一业务键幂等写入 Kline；
记录 DataCollectionRun；
记录 fetched、inserted、skipped、conflict、filtered_unclosed 等审计摘要；
发现采集异常时写必要 AlertEvent；
向编排或调用方返回本次采集结果；
为 DataQuality 提供实际采集覆盖范围。
```

## 4. 不负责事项

DataCollection 不负责：

```text
判断 Kline 是否最终允许进入策略链路；
执行完整连续性检查；
执行完整缺口检查；
执行完整 OHLC 合法性检查；
创建 BackfillRequest；
执行大范围数据回补；
生成 MarketSnapshot；
计算 FeatureValue；
生成 AtomicSignal；
生成 DomainSignal；
生成 MarketRegime；
执行 StrategyRouting；
生成 StrategySignal；
生成 StrategySignalQuality；
生成 DecisionSnapshot；
读取 Binance 账户、余额、持仓或订单；
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
人工修改 Kline。
```

DataCollection 可以发现明显采集异常和数据冲突，但最终质量授权由 DataQuality 负责。

## 5. 外部访问边界

DataCollection 所有 Binance 请求必须通过：

```text
BinancePublicMarketGateway
```

允许调用的 Gateway 操作仅包括：

```text
get_server_time(market_type, call_context)
get_klines(market_type, symbol, interval, start_time_utc, end_time_utc, limit, call_context)
```

DataCollection 禁止调用：

```text
BinanceAccountReadGateway；
BinanceOrderSubmissionGateway；
BinanceOrderStatusGateway；
BinanceFillQueryGateway；
任何 Binance 签名交易接口；
任何修改杠杆、保证金模式或持仓模式的接口；
任何绕过 BinanceGateway 的 HTTP client。
```

Gateway 负责：

```text
base_url 选择；
market_type 校验；
超时；
限频；
技术重试；
错误分类；
脱敏日志；
技术指标。
```

DataCollection 负责：

```text
K 线闭合判断；
K 线业务规范化；
幂等写入；
冲突检测；
DataCollectionRun 状态；
业务 AlertEvent。
```

Gateway 不保存 Kline，不判断 DataQuality，不生成 MarketSnapshot，不写业务 AlertEvent。

## 6. 采集域

DataCollection 必须使用固定 data_collection_domain。

当前 P0 data_collection_domain 固定为：

```text
exchange = binance；
market_type = usds_m_futures；
symbol = BTCUSDT。
```

采集域是行情数据来源域，不等于交易执行域。

交易模块可以根据系统配置支持 USDS-M 或 COIN-M，但 DataCollection 当前不随交易执行域切换。

data_collection_domain 至少包括：

```text
exchange；
market_type；
symbol。
```

规则：

```text
exchange 当前为 binance；
market_type 当前为 usds_m_futures；
symbol 当前为 BTCUSDT；
DataCollection 不得通过参数热切 symbol；
DataCollection 不得读取或依赖 active trading domain；
DataCollection 不得同时为多个采集域运行主链路采集；
非当前采集域的数据采集如未来需要，必须设计独立离线数据能力，不得自动进入当前主交易链路。
```

如果调用参数与 data_collection_domain 不一致，必须 `blocked`，不得请求 Binance。

## 7. K 线周期

当前主链路需要采集：

```text
4h；
1d。
```

规则：

```text
4h 用于主策略周期；
1d 用于大周期趋势和市场环境辅助；
采集 service 可以复用；
存储、唯一约束、质量检查和窗口覆盖必须按周期独立处理；
不得把不同 timeframe 的业务语义混在一起。
```

当前不采集：

```text
1m；
5m；
15m；
1h；
订单簿深度；
逐笔成交；
资金费率；
WebSocket 实时行情。
```

如果未来新增周期，必须先更新需求、数据质量和 MarketSnapshot 的消费边界。

## 8. REST 与 WebSocket 边界

当前 Kline 的标准来源是 Binance REST K 线。

DataCollection 当前不实现 WebSocket。

WebSocket 禁止：

```text
拼接 4h Kline；
拼接 1d Kline；
写入正式 Kline；
作为策略信号链路输入；
生成 MarketSnapshot；
生成 FeatureValue；
生成 AtomicSignal；
生成 DomainSignal；
生成 MarketRegime；
执行 StrategyRouting；
生成 StrategySignal；
生成 StrategySignalQuality；
生成 DecisionSnapshot；
触发 OrderPlan；
触发 RiskCheck；
触发 ExecutionPreparation；
触发 Execution；
触发真实交易。
```

如果未来需要实时行情监测，应设计独立 PriceFeed 或监控模块。该模块不得替代正式 Kline。

## 9. 时间规则

DataCollection 所有业务时间必须使用 UTC。

必须：

```text
Binance 返回的 open_time 按 UTC 解释；
Binance 返回的 close_time 按 UTC 解释；
Kline.open_time_utc 使用 UTC；
Kline.close_time_utc 使用 UTC；
Kline 排序使用 open_time_utc；
Kline 连续性判断使用 UTC；
采集窗口使用 UTC；
DataCollectionRun 时间使用 UTC；
请求 K 线时不传 timeZone 参数。
```

禁止：

```text
使用服务器本地时间判断 K 线是否收盘；
使用 PRC 时间参与采集窗口计算；
使用用户 IP 推断业务时间；
设计 local_time 或 prc_time 作为核心业务字段；
请求 Binance K 线时传入 timeZone。
```

K 线是否已收盘应使用：

```text
Binance serverTime
Kline close_time_utc
```

已收盘判断：

```text
server_time_utc > close_time_utc
```

如果无法确认已收盘，不得写入正式 Kline。

## 10. 输入合同

DataCollectionService 输入至少包括：

```text
exchange；
market_type；
symbol；
timeframe；
collection_mode；
start_time_utc；
end_time_utc；
lookback_count；
business_request_key；
trace_id；
trigger_source。
```

### 10.1 exchange

当前允许：

```text
binance
```

### 10.2 market_type

必须来自 data_collection_domain。

当前固定为：

```text
usds_m_futures
```

DataCollection 不得自行选择 USDS-M 或 COIN-M，也不得根据交易执行域混用不同市场域的 Kline。

### 10.3 symbol

必须来自 data_collection_domain。

当前固定为：

```text
BTCUSDT
```

如果人工入口需要指定 symbol，只能用于校验其是否等于 data_collection_domain.symbol，不得用来热切当前采集标的。

### 10.4 timeframe

当前允许：

```text
4h
1d
```

### 10.5 collection_mode

允许：

```text
historical；
latest_closed；
incremental；
backfill_source_fetch。
```

语义：

```text
historical = 初始化或指定历史区间采集；
latest_closed = 获取最新已收盘 K 线；
incremental = 周期性增量采集；
backfill_source_fetch = DataBackfill 要求的可信源区间拉取。
```

`backfill_source_fetch` 只表示通过可信源获取 K 线，不表示人工修改 Kline。

### 10.6 lookback_count

增量采集必须使用 lookback window。

建议默认：

```text
4h：最近 10 根已收盘 Kline；
1d：最近 5 根已收盘 Kline。
```

具体数值由配置或开发计划确定，不得硬编码散落在业务代码中。

### 10.7 business_request_key

业务幂等键由调用方或编排衔接器传入，也可由 DataCollection service 按稳定输入生成。

必须至少覆盖：

```text
exchange；
market_type；
symbol；
timeframe；
collection_mode；
start_time_utc；
end_time_utc；
lookback_count。
```

`trace_id` 不得作为采集业务幂等键。

## 11. 输出合同

DataCollection 输出必须包含稳定结果。

结果至少包括：

```text
status；
reason_code；
data_collection_run_id；
timeframe；
requested_start_time_utc；
requested_end_time_utc；
actual_start_time_utc；
actual_end_time_utc；
fetched_count；
closed_count；
inserted_count；
skipped_existing_count；
conflict_count；
filtered_unclosed_count；
allows_quality_check；
trace_id。
```

`allows_quality_check` 只表示本次采集结果可以交给 DataQuality 检查，不表示数据已经可信。

`allows_quality_check = true` 不得被下游解释为 DataQuality PASS。

## 12. 状态语义

DataCollectionRun 状态至少包括：

```text
succeeded；
no_data；
blocked；
conflict；
failed；
unknown。
```

语义：

```text
succeeded = 请求完成且可交给 DataQuality；
no_data = 请求成功但没有拿到可写入的已收盘 Kline；
blocked = 参数、安全、采集域或前置条件不允许采集；
conflict = 同一唯一业务键数据不一致；
failed = 本地或外部明确失败；
unknown = 无法确认外部请求或写入结果。
```

映射到全局结果：

```text
succeeded → succeeded；
no_data → no_action 或 blocked，由调用场景决定；
blocked → blocked；
conflict → blocked；
failed → failed；
unknown → unknown。
```

`unknown` 不得自动解释为成功或失败。

## 13. Kline 对象

Kline 表示一根 Binance 已收盘 K 线事实。

Kline 至少表达：

```text
exchange；
market_type；
symbol；
timeframe；
open_time_utc；
close_time_utc；
open_price；
high_price；
low_price；
close_price；
volume；
quote_volume；
trade_count；
data_source；
source_request_id 或 source_run_id；
created_at_utc；
updated_at_utc。
```

规则：

```text
一根 Kline 只表达一个 timeframe 的一个 open_time；
正式 Kline 不保存未收盘 K 线；
正式 Kline 不保存人工编辑来源；
正式 Kline 不保存完整原始响应；
完整大批量响应不得塞入单个 JSON 字段。
```

如实现上采用 4h 与 1d 分表，两个表仍然表达同一业务对象语义：`Kline`。

## 14. DataCollectionRun 对象

DataCollectionRun 表示一次采集运行审计记录。

至少表达：

```text
business_request_key；
trace_id；
trigger_source；
exchange；
market_type；
symbol；
timeframe；
collection_mode；
requested_start_time_utc；
requested_end_time_utc；
actual_start_time_utc；
actual_end_time_utc；
binance_server_time_utc；
status；
reason_code；
attempt_count；
gateway_attempt_count；
fetched_count；
closed_count；
inserted_count；
skipped_existing_count；
duplicate_in_response_count；
conflict_count；
filtered_unclosed_count；
error_code；
error_message；
started_at_utc；
finished_at_utc。
```

规则：

```text
DataCollectionRun 是审计摘要；
DataCollectionRun 不替代 Kline；
DataCollectionRun 不作为 MarketSnapshot 输入；
DataCollectionRun 不代表 DataQuality PASS；
同一 business_request_key 重复运行应返回已有 run 或幂等复用其结果。
```

## 15. 唯一业务键

Kline 唯一业务键至少包括：

```text
exchange；
market_type；
symbol；
timeframe；
open_time_utc。
```

禁止使用：

```text
数据库自增 id 判断 Kline 顺序；
数据库自增 id 判断 Kline 连续性；
数据库自增 id 判断 Kline 缺口；
trace_id 判断 Kline 唯一性。
```

数据库必须有唯一约束保护同一 Kline 不重复写入。

如果实现采用 4h 与 1d 分表，单表唯一约束中可以不包含 timeframe，但业务唯一键语义仍必须包含 timeframe。

## 16. 幂等写入

重复采集同一时间范围时：

```text
不得插入重复 Kline；
不得静默覆盖核心行情字段；
不得因为 Celery 重试产生重复事实；
不得因为编排恢复产生重复事实；
必须记录或复用 DataCollectionRun。
```

写入规则：

```text
同一唯一键不存在 → 插入；
同一唯一键存在且核心行情字段一致 → 跳过或只更新非核心审计字段；
同一唯一键存在但核心行情字段不一致 → 标记 conflict，不得覆盖。
```

核心行情字段包括：

```text
open_price；
high_price；
low_price；
close_price；
volume；
quote_volume；
trade_count。
```

冲突时必须保留旧值摘要、新值摘要、来源、trace_id 和 reason_code。

## 17. lookback window

增量采集不得只请求最新一根 Kline。

每次增量采集必须向前请求若干根已收盘 Kline。

目的：

```text
降低短期漏采风险；
补齐 lookback 范围内短期缺失；
发现最近数据冲突；
避免单次任务失败造成永久缺口。
```

lookback window 内发现数据库缺少 Kline 时，DataCollection 可以直接幂等写入补齐。

以下情况应交给 DataQuality / DataBackfill：

```text
lookback window 外缺口；
连续多根 Kline 缺失；
历史大范围缺口；
同一唯一键数据冲突；
交易所返回异常；
无法确认是否已收盘。
```

DataCollection 不得为了补齐历史缺口无限扩大 lookback window。

## 18. 已收盘过滤

DataCollection 只能写入已收盘 Kline。

必须过滤：

```text
close_time_utc >= binance_server_time_utc；
无法解析 close_time 的 Kline；
timeframe 边界不匹配的 Kline；
时间顺序异常的 Kline。
```

如果 Gateway 返回的数据中包含未收盘 Kline：

```text
不得写入正式 Kline；
filtered_unclosed_count 增加；
必要时 reason_code = unclosed_kline_filtered；
如果过滤后无可用 Kline，DataCollectionRun = no_data 或 blocked。
```

未收盘 Kline 不得进入：

```text
DataQuality；
MarketSnapshot；
FeatureLayer；
AtomicSignal；
DomainSignal；
MarketRegime；
StrategyRouting；
StrategySignal；
StrategySignalQuality；
DecisionSnapshot；
OrderPlan；
RiskCheck；
ExecutionPreparation；
Execution。
```

## 19. 数据冲突处理

数据冲突指：

```text
同一 Kline 唯一业务键下，重新采集到的核心行情字段与数据库已有记录不一致。
```

处理规则：

```text
不得静默覆盖；
不得人工修改；
不得用新值自动替换旧值；
不得继续把该冲突窗口标记为可质量检查；
必须记录冲突摘要；
必须写必要 AlertEvent；
必须返回 conflict 或 blocked；
后续由 DataQuality / DataBackfill / 人工审计流程处理。
```

冲突摘要不得保存不可控大 JSON。

冲突摘要应包含：

```text
唯一业务键；
旧值 hash 或摘要；
新值 hash 或摘要；
data_source；
collection_mode；
trace_id；
trigger_source；
detected_at_utc。
```

## 20. collection_mode

允许的 collection_mode：

```text
historical；
latest_closed；
incremental；
backfill_source_fetch。
```

规则：

```text
historical 用于初始化或指定历史范围；
latest_closed 用于获取最新已收盘 Kline；
incremental 用于周期性 lookback 采集；
backfill_source_fetch 只能由 DataBackfill 或受控人工入口触发；
collection_mode 不得改变 data_source；
backfill_source_fetch 不得变成人工改库。
```

## 21. data_source

当前正式 Kline 允许的数据来源：

```text
binance_rest
```

禁止作为正式 Kline 数据来源：

```text
manual_repair；
system_repair；
human_edit；
manual_input；
websocket_derived；
local_generated。
```

如果未来支持其他可信数据源，必须先定义数据源可信边界、冲突处理和质量检查规则。

## 22. 成功流程

### 22.1 historical

```text
接收历史采集请求；
校验 data_collection_domain；
校验 timeframe 和时间范围；
生成或复用 business_request_key；
创建或复用 DataCollectionRun；
通过 Gateway 获取 server time；
通过 Gateway 获取 Kline；
过滤未收盘 Kline；
规范化 Kline；
按唯一业务键幂等写入；
记录 DataCollectionRun 审计摘要；
返回采集结果；
进入或等待 DataQuality。
```

### 22.2 incremental

```text
接收增量采集请求；
校验 data_collection_domain；
计算 lookback 请求范围；
创建或复用 DataCollectionRun；
通过 Gateway 获取 server time；
通过 Gateway 获取最近多根已收盘 Kline；
过滤未收盘 Kline；
与数据库已有 Kline 按唯一业务键比对；
插入缺失 Kline；
跳过已存在且一致的 Kline；
发现冲突时阻断；
记录 DataCollectionRun 审计摘要；
返回采集结果；
进入或等待 DataQuality。
```

## 23. 失败流程

采集失败必须记录，不得静默成功。

失败时必须记录：

```text
trace_id；
trigger_source；
business_request_key；
collection_mode；
exchange；
market_type；
symbol；
timeframe；
requested_start_time_utc；
requested_end_time_utc；
error_type；
error_code；
error_message；
is_retryable；
gateway_status；
attempt_count。
```

典型失败：

```text
采集域不匹配；
时间范围非法；
Gateway 超时；
Gateway 限频；
Gateway 返回失败；
Gateway 返回 unknown；
Kline payload 为空；
Kline payload 结构异常；
Kline 周期边界异常；
Kline 未收盘；
数据库写入失败；
唯一键冲突无法归类为幂等跳过；
同一唯一键数据不一致。
```

失败后禁止：

```text
伪造 Kline；
手工补值；
静默成功；
生成 MarketSnapshot；
触发 FeatureLayer；
触发 AtomicSignal；
触发 DomainSignal；
触发 MarketRegime；
触发 StrategyRouting；
触发 StrategySignal；
触发 StrategySignalQuality；
触发 DecisionSnapshot；
进入 OrderPlan；
调用 RiskCheck；
调用 ExecutionPreparation；
调用 Execution；
同步等待 Hermes 成功。
```

## 24. 重试边界

DataCollection 不直接实现 Binance HTTP 重试。

安全读取请求的有限技术重试由 BinanceGateway 统一负责。

DataCollection 可以：

```text
读取 Gateway 返回的 attempt_count；
把 attempt_count 记录到 DataCollectionRun；
根据 Gateway 结果决定本次采集状态；
在编排或人工入口再次触发时按 business_request_key 幂等复用或重新运行安全读取动作。
```

DataCollection 禁止：

```text
绕过 Gateway 自行重试 HTTP 请求；
无限重试；
在 DataQuality 或 MarketSnapshot 已开始消费某窗口后继续异步补写本窗口 Kline；
因 Celery 自动重试产生重复 DataCollectionRun；
把 unknown 当作 succeeded；
把 unknown 当作 failed 并自动放行下游。
```

订单提交无重试规则与 DataCollection 无关，但 DataCollection 不得提供任何订单提交能力。

## 25. 与 DataQuality 的关系

DataCollection 成功不等于数据可信。

DataCollection 只提供：

```text
已收盘 Kline；
采集覆盖范围；
采集运行摘要；
明显采集异常；
明显数据冲突。
```

DataQuality 负责：

```text
连续性检查；
重复检查；
缺失检查；
OHLC 合法性检查；
周期边界检查；
数据源检查；
窗口覆盖检查；
是否允许进入 MarketSnapshot。
```

规则：

```text
DataCollection 不得生成 DataQualityResult；
DataCollection 不得把 allows_quality_check 当作 PASS；
DataQuality 不得假设采集成功就可信；
MarketSnapshot 只能消费 DataQuality PASS 的窗口。
```

## 26. 与 DataBackfill 的关系

DataCollection 与 DataBackfill 共享可信 Kline 存储，但职责不同。

DataCollection 负责：

```text
正常历史采集；
最新已收盘采集；
周期性增量采集；
lookback 范围内短期缺失补齐。
```

DataBackfill 负责：

```text
缺口回补请求；
较大历史范围补偿；
冲突复核；
回补运行记录；
回补后重新质检。
```

规则：

```text
回补得到的 Kline 仍写入正式 Kline 存储；
不得创建“正常采集 Kline”和“回补 Kline”两套主表；
DataBackfill 可以通过 DataCollection 的可信源拉取能力或共享底层 fetcher 获取 Kline；
无论由谁拉取，写入规则和冲突规则必须一致；
回补完成后必须重新进入 DataQuality。
```

## 27. 与 MarketSnapshot 的关系

MarketSnapshot 只读取通过 DataQuality 授权的 Kline 窗口。

规则：

```text
DataCollection 不生成 MarketSnapshot；
DataCollection 不触发 FeatureLayer；
MarketSnapshot 不请求 Binance；
MarketSnapshot 不写 Kline；
MarketSnapshot 不自动补数据；
缺少 Kline 时应先采集或回补，再 DataQuality，再 MarketSnapshot。
```

如果 DataCollection 失败，本轮不得跳过 DataQuality 直接生成 MarketSnapshot。

## 28. 与 PipelineOrchestrator 的关系

PipelineOrchestrator 可以编排 DataCollection，但不解释采集内部状态。

规则：

```text
编排层通过 BusinessStepAdapter 调用 DataCollection service；
adapter 负责把 DataCollection 原始结果映射为 normalized_status 和 flow_action；
DataCollection 返回业务对象索引；
OrchestrationBusinessObjectLink 可以记录 DataCollectionRun 和 Kline 范围摘要；
业务对象不得保存或查询 orchestration_run_id；
DataCollection 幂等键不得依赖 orchestration_run_id。
```

## 29. AlertEvent

DataCollection 在以下情况应写 AlertEvent：

```text
采集域不匹配；
Gateway 长时间失败；
Gateway 返回 unknown；
采集窗口无可用已收盘 Kline；
同一唯一键数据冲突；
数据库写入失败；
DataCollectionRun unknown；
重复异常超过阈值；
采集结果无法交给 DataQuality。
```

可以不写正式 AlertEvent 的情况：

```text
正常重复采集且全部 skipped_existing；
少量未收盘 Kline 被正常过滤；
dry-run 采集预览；
本次没有新插入但窗口已由已有 Kline 覆盖。
```

规则：

```text
DataCollection 只写 AlertEvent；
DataCollection 不直接发送 Hermes；
AlertEvent 不得包含完整 Binance 响应；
AlertEvent 不得包含 API key、secret、signature 或 header；
Notifications 负责后续投递。
```

## 30. 数据库、Redis 与外部服务

```text
读 MySQL：是，读取已有 Kline 和 DataCollectionRun。
写 MySQL：是，写入 Kline、DataCollectionRun、冲突摘要和 AlertEvent。
访问 Redis：可用于短期采集锁、短期限频辅助、短期任务状态和幂等保护，不作为唯一事实。
访问 Binance：是，但只能通过 BinancePublicMarketGateway。
发送 Hermes：否，只写 AlertEvent。
调用大模型：否。
涉及交易执行：否。
允许真实交易：否。
```

MySQL 是 Kline 和 DataCollectionRun 的正式事实来源。

Redis 不可用时：

```text
不得丢失 Kline；
不得只依赖 Redis 判断已采集；
可以降级为 MySQL 幂等与数据库唯一约束；
如果无法保证并发安全，应 blocked 或 failed。
```

## 31. Management command 与 Celery task

DataCollection 的 command / task 只能：

```text
解析参数；
生成或传递 trace_id；
设置 trigger_source；
校验 dry-run / confirm-write；
调用 DataCollection service；
输出结果摘要。
```

禁止：

```text
在 command / task 中直接请求 Binance；
在 command / task 中直接写 Kline；
在 command / task 中执行完整业务链路；
在 command / task 中直接生成 MarketSnapshot；
在 command / task 中直接调用 FeatureLayer；
在 command / task 中直接调用 OrderPlan；
在 command / task 中直接发送 Hermes。
```

## 32. dry-run

dry-run 用于预览采集计划。

dry-run 可以：

```text
校验参数；
计算请求窗口；
读取已有 Kline 覆盖情况；
返回预计请求数量；
返回预计 lookback 范围。
```

dry-run 不得：

```text
写 Kline；
写正式 DataCollectionRun；
写正式 AlertEvent；
请求真实 Binance，除非测试或诊断入口明确允许且不会写库；
触发 DataQuality；
触发 MarketSnapshot；
进入交易链路。
```

## 33. 异常处理

异常处理规则：

```text
参数非法 → blocked；
采集域不匹配 → blocked；
timeframe 不支持 → blocked；
Gateway blocked_before_send → blocked；
Gateway failed_before_send → failed；
Gateway unknown_after_send → unknown；
Gateway rate_limited → failed 或 blocked，由 Gateway 错误分类决定；
payload 结构异常 → failed；
未收盘 Kline 全部过滤 → no_data 或 blocked；
同一唯一键数据冲突 → conflict；
数据库写入失败 → failed 或 unknown；
AlertEvent 写入失败 → 高风险场景不得静默成功。
```

任何异常都不得导致未收盘、冲突或不可信 Kline 进入下游。

## 34. 测试要求

必须测试：

```text
1. DataCollection 只能通过 BinancePublicMarketGateway 获取 Kline。
2. DataCollection 不直接创建 Binance HTTP client。
3. 请求 Kline 时不传 timeZone。
4. Binance 时间戳按 UTC 解释。
5. 未收盘 Kline 不写入正式 Kline。
6. close_time_utc >= server_time_utc 时过滤。
7. 4h Kline 幂等写入。
8. 1d Kline 幂等写入。
9. 同一唯一键一致数据重复采集不重复插入。
10. 同一唯一键不同 OHLCV 标记 conflict 且不覆盖。
11. 增量采集使用 lookback window。
12. lookback 内缺失 Kline 可以补齐。
13. lookback 外缺口不由 DataCollection 无限扩大处理。
14. DataCollectionRun 记录 fetched / inserted / skipped / conflict / filtered_unclosed。
15. trace_id 不作为业务幂等键。
16. business_request_key 重复时幂等。
17. Gateway unknown 映射为 unknown，不放行下游。
18. Gateway failed 映射为 failed。
19. 采集域不匹配时不请求 Gateway。
20. DataCollection 成功不生成 DataQualityResult。
21. DataCollection 成功不生成 MarketSnapshot。
22. DataCollection 不调用账户、订单、成交或交易 Gateway。
23. DataCollection 不发送 Hermes。
24. 采集异常写必要 AlertEvent。
25. AlertEvent 不包含完整 Binance 响应或密钥。
26. Redis 不可用时 Kline 事实不丢失。
27. command 只调用 service。
28. Celery task 只调用 service。
29. 默认测试使用 fake Gateway，不访问真实 Binance。
30. dry-run 不写正式 Kline、DataCollectionRun 或 AlertEvent。
```

## 35. 验收标准

DataCollection 验收通过必须满足：

```text
Kline 只来自 BinancePublicMarketGateway；
只写入已收盘 Kline；
所有核心时间使用 UTC；
请求 Kline 不传 timeZone；
当前采集域固定为 Binance USDS-M BTCUSDT；
当前主链路支持 4h 与 1d；
Kline 唯一业务键清晰；
重复采集不会重复写入；
同一唯一键冲突不会静默覆盖；
增量采集具备 lookback window；
DataCollectionRun 可审计；
采集结果可以交给 DataQuality，但不等于 DataQuality PASS；
失败、冲突和 unknown 保守处理；
必要异常写 AlertEvent；
不直接发送 Hermes；
不读取账户、持仓、订单或成交；
不生成 MarketSnapshot、特征、信号、决策、订单或风控结果；
不涉及交易执行；
默认测试不访问真实 Binance。
```

## 36. 当前不包含的能力

当前不包含：

```text
WebSocket 实时行情；
WebSocket 拼接 Kline；
多交易所采集；
多采集域同时采集并进入主链路；
多品种组合采集；
1m / 5m / 15m 高频 Kline；
订单簿深度采集；
逐笔成交采集；
资金费率采集；
多数据源交叉校验；
人工编辑 Kline；
自动修复 Kline；
自动生成 DataQualityResult；
自动生成 MarketSnapshot；
直接触发策略或交易。
```

## 37. 最终结论

DataCollection 的最终定位是：

```text
可信、幂等、可审计地把 Binance 已收盘 K 线写入系统正式行情事实层。
```

一句话：

```text
DataCollection 只负责把已收盘行情事实采回来并安全落库；数据是否可信、是否需要回补、是否能生成 MarketSnapshot，都由后续模块决定。
```
