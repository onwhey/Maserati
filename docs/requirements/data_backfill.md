# DataBackfill 需求

## 1. 模块定位

DataBackfill 是行情数据链路中的回补与复核模块。

本模块负责在初始化、缺口、采集失败、人工指定范围和数据冲突复核场景下，通过 `BinancePublicMarketGateway` 拉取 Binance 官方已收盘 Kline，并以幂等、可追溯、不可静默覆盖的方式写入正式 Kline 存储。

当前 DataBackfill 只对 DataCollection 固定采集域的数据执行主链路回补和复核：

```text
exchange = binance；
market_type = usds_m_futures；
symbol = BTCUSDT；
timeframe = 4h / 1d。
```

DataBackfill 的主要对象是：

```text
BackfillRequest
BackfillRun
```

DataBackfill 的辅助审计对象包括：

```text
BackfillIssue
DataConflict
```

回补完成不等于数据可信。

回补完成后必须标记或要求重新执行 DataQuality。只有新的 `DataQualityResult = PASS` 且覆盖目标窗口，基于该质量窗口的 MarketSnapshot、FeatureLayer、信号、策略和交易主链路才允许继续。

DataBackfill 不是：

```text
正常增量采集模块；
数据质量最终授权模块；
数据人工修复模块；
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
DataBackfill 负责把缺失或需要复核的 Binance USDS-M BTCUSDT 4h / 1d Kline 从可信源重新拉回来；是否可信、是否能继续主链路下游，必须由 DataQuality 重新判断。
```

## 2. 设计目标

DataBackfill 的目标是：

```text
补齐初始化所需历史 Kline；
补齐运行过程中发现的缺失 Kline；
对人工指定 UTC 范围重新拉取官方 Kline；
对数据冲突重新拉取官方 Kline 进行复核；
只使用 Binance 官方已收盘 Kline；
所有请求通过 BinancePublicMarketGateway；
按 UTC 时间窗口回补；
支持 missing_open_times 精确回补；
支持分批请求和规模上限；
幂等写入正式 Kline；
不静默覆盖已有 Kline；
记录 BackfillRun 和问题摘要；
必要时写 AlertEvent；
回补完成后要求 DataQuality 复检。
```

当前主链路回补周期：

```text
4h；
1d。
```

DataBackfill 必须使用固定 data_collection_domain，不得自行切换 symbol 或 market_type。

## 3. 负责事项

DataBackfill 负责：

```text
接收 BackfillRequest 或人工回补请求；
校验 data_collection_domain；
校验 timeframe 和 UTC 时间范围；
原子 claim BackfillRequest；
获取 Kline 写入锁；
通过 BinancePublicMarketGateway 获取 server time；
通过 BinancePublicMarketGateway 分批获取 Kline；
过滤未收盘 Kline；
按 missing_open_times 精确过滤；
规范化 Kline；
按唯一业务键幂等写入正式 Kline；
发现冲突时记录 DataConflict 并阻断；
记录 BackfillRun；
记录 BackfillIssue；
必要时写 AlertEvent；
回补完成后标记或要求 DataQuality 复检；
返回稳定回补结果。
```

## 4. 不负责事项

DataBackfill 不负责：

```text
正常周期性增量采集；
lookback window 内短期自动补漏；
判断数据最终可信；
生成 DataQualityResult = PASS；
直接执行 DataQuality；
等待 DataQuality 结果；
生成 MarketSnapshot；
计算 FeatureValue；
生成 AtomicSignal；
生成 DomainSignal；
生成 MarketRegime；
执行 StrategyRouting；
生成 StrategySignal；
生成 StrategySignalQuality；
生成 DecisionSnapshot；
读取 Binance 账户、余额、持仓、订单或成交；
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
人工修改 Kline；
自动修复 Kline；
静默覆盖冲突 Kline。
```

## 5. 外部访问边界

DataBackfill 所有 Binance 请求必须通过：

```text
BinancePublicMarketGateway
```

允许调用的 Gateway 操作仅包括：

```text
get_server_time(market_type, call_context)
get_klines(market_type, symbol, interval, start_time_utc, end_time_utc, limit, call_context)
```

DataBackfill 禁止调用：

```text
BinanceAccountReadGateway；
BinanceOrderSubmissionGateway；
BinanceOrderStatusGateway；
BinanceFillQueryGateway；
任何 Binance 签名交易接口；
任何账户、余额、持仓、订单或成交接口；
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

DataBackfill 负责：

```text
回补参数校验；
分批请求边界；
Kline 闭合判断；
missing_open_times 精确过滤；
幂等写入；
冲突检测；
BackfillRun 状态；
业务 AlertEvent。
```

Gateway 不保存 Kline，不执行回补业务，不判断 DataQuality，不生成 MarketSnapshot，不写业务 AlertEvent。

## 6. 采集域

DataBackfill 必须使用固定 data_collection_domain。

当前 data_collection_domain 固定为：

```text
exchange = binance；
market_type = usds_m_futures；
symbol = BTCUSDT。
```

采集域是行情数据来源域，不等于交易执行域。

交易模块可以根据系统配置支持 USDS-M 或 COIN-M，但 DataBackfill 当前不随交易执行域切换。

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
DataBackfill 不得通过参数热切 symbol；
DataBackfill 不得读取或依赖 active trading domain；
DataBackfill 不得同时为多个采集域回补并进入主链路；
非当前采集域的历史数据处理如未来需要，必须设计独立离线能力，不得进入当前主交易链路。
```

如果 BackfillRequest 或人工请求与 data_collection_domain 不一致，必须 `blocked`，不得请求 Gateway。

## 7. 回补触发场景

DataBackfill 支持以下 backfill_mode：

```text
initial_historical_backfill；
gap_backfill；
manual_range_backfill；
conflict_recheck；
failure_recovery_backfill。
```

### 7.1 initial_historical_backfill

用于项目初始化或历史数据补齐。

规则：

```text
必须由人工入口或受控初始化流程触发；
必须指定明确 UTC 起止时间；
不得自动猜测超大历史范围；
必须受分页和最大 bars 上限约束；
必须幂等；
完成后必须要求 DataQuality 检查。
```

### 7.2 gap_backfill

用于 DataQuality 发现缺失、不连续或窗口覆盖不足后的明确缺口回补。

规则：

```text
只补明确缺失范围；
优先使用 missing_open_times 精确回补；
不得无限扩大回补范围；
不得顺手写入未被请求的 open_time；
完成后必须要求 DataQuality 复检。
```

### 7.3 manual_range_backfill

用于人工指定 UTC 时间范围重新拉取。

规则：

```text
必须明确 timeframe、start_time_utc、end_time_utc；
必须记录 operator_id、reason 和 evidence；
必须支持 dry-run；
confirm-write 时必须写审计；
不得缺省起止时间后自动猜测。
```

### 7.4 conflict_recheck

用于同一 Kline 唯一业务键下 OHLCV 不一致时，从可信源重新拉取进行对照。

规则：

```text
不得自动覆盖已有 Kline；
不得自动删除旧 Kline；
不得自动选择其中一条作为正确值；
必须记录 DataConflict；
必须保留旧值摘要、新值摘要和官方重拉值摘要；
后续是否采用某个值必须由明确人工审计或独立数据修复需求定义。
```

### 7.5 failure_recovery_backfill

用于采集任务连续失败、系统停机或已知故障导致的数据缺口补偿。

规则：

```text
必须指定明确 UTC 时间范围；
必须受最大范围和分页上限约束；
必须通过 Gateway 拉取官方已收盘 Kline；
完成后必须要求 DataQuality 复检。
```

## 8. DataCollection 与 DataBackfill 的关系

DataCollection 负责：

```text
正常历史采集；
最新已收盘采集；
周期性增量采集；
lookback 范围内短期缺失补齐。
```

DataBackfill 负责：

```text
初始化历史补齐；
明确缺口回补；
较大范围补偿；
人工指定范围回补；
冲突复核。
```

存储规则：

```text
DataCollection 写入正式 Kline；
DataBackfill 也写入正式 Kline；
不得创建正常采集 Kline 和回补 Kline 两套主表；
不得创建人工修复 Kline 作为正式事实；
两者必须共用 Kline 唯一业务键；
两者必须共用 Kline 写入锁或等价并发保护。
```

如果两者共享底层 Kline fetcher / writer，必须保持 service 边界清晰：

```text
DataCollectionRun 不等于 BackfillRun；
DataCollection 结果不等于 BackfillRequest；
BackfillRun 不替代 DataQualityResult；
共享底层工具不得绕过两个业务 service 的状态、审计和 AlertEvent 规则。
```

## 9. 时间规则

DataBackfill 所有业务时间必须使用 UTC。

必须：

```text
start_time_utc 使用 UTC；
end_time_utc 使用 UTC；
missing_open_times 使用 UTC；
回补范围按 timeframe 周期边界对齐；
Binance 返回 open_time 按 UTC 解释；
Binance 返回 close_time 按 UTC 解释；
BackfillRun 时间使用 UTC；
请求 Kline 时不传 timeZone 参数。
```

禁止：

```text
使用服务器本地时间作为回补范围；
使用 PRC 时间作为回补范围；
根据运行机器时区推断时间；
根据用户 IP 推断时间；
请求 Binance Kline 时传入 timeZone；
保存本地时间作为核心业务字段。
```

周期边界：

```text
4h open_time_utc 必须落在 00:00、04:00、08:00、12:00、16:00、20:00；
1d open_time_utc 必须落在 00:00。
```

## 10. 输入合同

DataBackfillService 输入至少包括：

```text
backfill_request_id；
exchange；
market_type；
symbol；
timeframe；
backfill_mode；
start_time_utc；
end_time_utc；
missing_open_times；
limit_per_request；
business_request_key；
dry_run；
confirm_write；
operator_id；
reason；
evidence；
trace_id；
trigger_source。
```

### 10.1 backfill_request_id

如果由 DataQuality 创建 BackfillRequest 触发，必须传入 backfill_request_id。

DataBackfill 在执行前必须原子 claim BackfillRequest。

如果是人工 `manual_range_backfill` 或初始化回补，可以没有 BackfillRequest，但必须生成稳定 business_request_key，并记录 operator_id、reason 和 evidence。

### 10.2 exchange / market_type / symbol

必须与当前 data_collection_domain 一致。

规则：

```text
exchange 当前为 binance；
market_type 当前为 usds_m_futures；
symbol 当前为 BTCUSDT；
DataBackfill 不得通过参数热切 data_collection_domain；
非 data_collection_domain 数据不得进入当前主链路回补结果。
```

不一致时：

```text
BackfillRun.status = blocked；
不得请求 Gateway；
必要时写 AlertEvent。
```

### 10.3 timeframe

当前允许：

```text
4h；
1d。
```

### 10.4 backfill_mode

允许：

```text
initial_historical_backfill；
gap_backfill；
manual_range_backfill；
conflict_recheck；
failure_recovery_backfill。
```

### 10.5 missing_open_times

`missing_open_times` 用于精确回补。

规则：

```text
非空时，只允许写入这些 open_time 对应的 Kline；
Gateway 返回范围内额外 open_time 时必须过滤；
过滤掉的额外 Kline 必须计入审计摘要；
如果需要扩大范围，必须创建新的 BackfillRequest 或由人工发起新的 manual_range_backfill。
```

### 10.6 business_request_key

业务幂等键必须稳定。

至少覆盖：

```text
exchange；
market_type；
symbol；
timeframe；
backfill_mode；
start_time_utc；
end_time_utc；
missing_open_times；
source_backfill_request_id。
```

`trace_id` 不得作为回补幂等键。

## 11. 输出合同

DataBackfill 输出至少包括：

```text
status；
reason_code；
backfill_request_id；
backfill_run_id；
backfill_issue_ids；
data_conflict_ids；
fetched_count；
closed_count；
inserted_count；
skipped_existing_count；
filtered_unclosed_count；
filtered_not_requested_count；
conflict_count；
page_count；
requires_quality_recheck；
recheck_window_start_open_time_utc；
recheck_window_end_open_time_utc；
trace_id。
```

`requires_quality_recheck = true` 表示回补完成后必须重新执行 DataQuality。

它不表示 DataQuality 已经通过。

## 12. BackfillRequest

BackfillRequest 表示一个待回补或待复核请求。

BackfillRequest 由以下来源创建：

```text
DataQuality；
受控人工入口；
受控初始化流程；
RuntimeGuard 发现缺口后的人工确认入口。
```

BackfillRequest 至少表达：

```text
business_key；
source_module；
source_object_type；
source_object_id；
exchange；
market_type；
symbol；
timeframe；
backfill_mode；
requested_start_open_time_utc；
requested_end_open_time_utc；
missing_open_times；
reason_code；
status；
attempt_count；
last_backfill_run_id；
operator_id；
reason；
evidence；
trace_id；
trigger_source；
created_at_utc；
updated_at_utc。
```

状态至少包括：

```text
pending；
running；
success；
blocked；
failed；
conflict；
cancelled。
```

规则：

```text
BackfillRequest 是请求记录；
BackfillRequest 不等于 BackfillRun；
BackfillRequest 不等于 DataQualityResult；
BackfillRequest success 不等于数据可信；
BackfillRequest success 后仍需 DataQuality 复检。
```

## 13. BackfillRequest claim

消费 BackfillRequest 前必须原子 claim。

允许 claim 的状态：

```text
pending；
failed 且允许 retry。
```

claim 时必须原子更新：

```text
status = running；
locked_by；
locked_at_utc；
attempt_count = attempt_count + 1；
last_trace_id；
started_at_utc。
```

如果 BackfillRequest 已处于以下状态：

```text
running；
success；
blocked；
conflict；
cancelled。
```

本次执行必须：

```text
不请求 Gateway；
不写 Kline；
返回 skipped / already_claimed / terminal_state 等结构化结果；
必要时写 BackfillRun = skipped。
```

claim 是防止重复回补的第一道门。Kline 写入锁是防止并发写同一行情事实的第二道门。

## 14. BackfillRun

BackfillRun 表示一次实际回补执行。

BackfillRun 至少表达：

```text
business_request_key；
backfill_request_id；
trace_id；
trigger_source；
operator_id；
exchange；
market_type；
symbol；
timeframe；
backfill_mode；
requested_start_open_time_utc；
requested_end_open_time_utc；
missing_open_times；
status；
reason_code；
attempt_count；
gateway_attempt_count；
page_count；
fetched_count；
closed_count；
inserted_count；
skipped_existing_count；
filtered_unclosed_count；
filtered_not_requested_count；
conflict_count；
requires_quality_recheck；
quality_recheck_requested_at_utc；
started_at_utc；
finished_at_utc；
error_code；
error_message。
```

状态至少包括：

```text
running；
success；
blocked；
failed；
conflict；
skipped；
unknown；
dry_run_success；
dry_run_failed。
```

语义：

```text
success = 回补执行完成，可能写入或跳过 Kline，但仍需 DataQuality；
blocked = 参数、锁、范围、权限或规则阻断；
failed = Gateway、解析、数据库或系统异常失败；
conflict = 发现同一唯一键数据冲突；
skipped = 重复、终态、锁不可取得或无需执行；
unknown = 无法确认执行结果或事务结果；
dry_run_* = dry-run 结果，不得进入当前主链路下游。
```

## 15. BackfillIssue

BackfillIssue 表示回补过程中的问题摘要。

Issue 类型至少包括：

```text
INVALID_REQUEST；
COLLECTION_DOMAIN_MISMATCH；
TIME_RANGE_INVALID；
TIME_BOUNDARY_INVALID；
LIMIT_EXCEEDED；
GATEWAY_FAILED；
GATEWAY_UNKNOWN；
PAYLOAD_INVALID；
UNCLOSED_KLINE_FILTERED；
NO_CLOSED_KLINE；
MISSING_OPEN_TIMES_NOT_FOUND；
KLINE_CONFLICT；
KLINE_WRITE_FAILED；
LOCK_NOT_ACQUIRED；
LOCK_RELEASE_FAILED；
QUALITY_RECHECK_REQUIRED。
```

BackfillIssue 不替代 BackfillRun 状态。

## 16. DataConflict

DataConflict 表示回补过程中发现同一唯一业务键的核心行情字段不一致。

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

DataConflict 至少表达：

```text
backfill_run_id；
trace_id；
exchange；
market_type；
symbol；
timeframe；
open_time_utc；
existing_value_summary；
fetched_value_summary；
existing_value_hash；
fetched_value_hash；
data_source；
backfill_mode；
status；
created_at_utc。
```

规则：

```text
不得保存完整不可控大 JSON；
不得保存完整 Binance 响应；
不得自动覆盖已有 Kline；
不得自动删除已有 Kline；
不得自动选择正确值；
必须阻断基于该回补窗口的当前主链路下游放行。
```

## 17. Kline 唯一业务键与写入规则

Kline 唯一业务键至少包括：

```text
exchange；
market_type；
symbol；
timeframe；
open_time_utc。
```

写入规则：

```text
同一唯一键不存在 → 插入；
同一唯一键存在且核心行情字段一致 → 跳过；
同一唯一键存在但核心行情字段不一致 → 记录 DataConflict，阻断，不覆盖。
```

禁止：

```text
静默覆盖已有 Kline；
删除已有 Kline；
人工修复已有 Kline；
用回补结果直接替换历史事实；
自动选择冲突数据中的一条作为正确数据。
```

如果实现采用 4h 与 1d 分表，两个表仍表达同一业务对象语义：`Kline`。

## 18. Kline 写入锁

DataBackfill 写入正式 Kline 前必须取得 Kline 写入锁或等价并发保护。

锁粒度：

```text
exchange + market_type + symbol + timeframe
```

锁语义：

```text
kline_write:{exchange}:{market_type}:{symbol}:{timeframe}
```

规则：

```text
DataCollection 和 DataBackfill 必须共享同一类 Kline 写入锁；
获取锁必须具备原子性；
锁必须设置 TTL；
锁 owner 应为 trace_id、BackfillRun id 或等价唯一任务标识；
如果锁已存在，本次回补必须 skipped 或 blocked；
锁存在时不得请求 Gateway；
锁存在时不得写正式 Kline；
释放锁时必须校验 owner；
只能释放当前任务自己持有的锁；
释放失败必须写 BackfillIssue 和必要 AlertEvent。
```

目的：

```text
防止 DataCollection 与 DataBackfill 同时写同一 symbol/timeframe；
防止两个 BackfillRun 并发写同一 symbol/timeframe；
防止 lookback 自动补漏与人工回补互相冲突。
```

Redis 可以用于 Kline 写入锁，但 Redis 不是 Kline 事实来源。Redis 不可用且无法保证并发安全时，回补必须 blocked 或 failed。

## 19. 分批请求与规模上限

Binance Kline 接口存在单次 limit。DataBackfill 必须支持分批请求。

必须配置：

```text
DATA_BACKFILL_KLINE_PAGE_LIMIT；
DATA_BACKFILL_MAX_PAGES_PER_RUN；
DATA_BACKFILL_MAX_BARS_PER_RUN。
```

规则：

```text
每页请求 limit 不得超过 Binance 官方接口限制；
请求范围必须按 timeframe 推进；
不得无界循环；
必须记录 page_count；
必须记录每批请求范围和结果摘要；
预计或实际页数超过上限时必须停止；
预计或实际 Kline 数量超过上限时必须停止；
超过限制时 BackfillRun.status = blocked；
reason_code = limit_exceeded；
不得写入已拉取的部分 Kline；
必须写 BackfillIssue 和必要 AlertEvent。
```

当前回补优先采用 all-or-nothing 语义。

如果实现无法事务性回滚已经写入的内容，BackfillRun 必须明确记录可能部分影响，并且不得允许当前主链路下游继续。

## 20. 已收盘过滤

DataBackfill 只能写入已收盘 Kline。

已收盘判断：

```text
binance_server_time_utc > close_time_utc
```

规则：

```text
必须先通过 Gateway 获取 server time；
未收盘 Kline 不得写入正式 Kline；
未收盘 Kline 必须计入 filtered_unclosed_count；
如果请求结果全部为未收盘 Kline，本次回补必须 blocked 或 failed；
必要时写 BackfillIssue 和 AlertEvent。
```

禁止：

```text
使用本机时间作为唯一判断依据；
未获取 server time 仍继续写入；
把未收盘 Kline 写入正式表；
后续再覆盖未收盘 Kline。
```

## 21. missing_open_times 精确回补

当 BackfillRequest 指定 `missing_open_times` 时，DataBackfill 必须按精确 open_time 集合处理。

规则：

```text
missing_open_times 必须为 UTC open_time；
missing_open_times 必须落在 timeframe 周期边界；
只允许写入 missing_open_times 对应 Kline；
Gateway 返回范围内额外 open_time 时必须过滤；
过滤掉的额外 Kline 计入 filtered_not_requested_count；
如果某些 missing_open_times 未被 Gateway 返回，必须记录 BackfillIssue；
不得因为请求范围覆盖额外 Kline 就顺手写入；
不得把 missing_open_times 为空解释为无限范围。
```

## 22. 数据来源

正式回补 Kline 允许的数据来源：

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
third_party_feed；
local_generated；
llm_generated。
```

DataBackfill 不得把人工来源、WebSocket 拼接或大模型生成数据写入正式 Kline。

## 23. 成功流程

```text
接收 BackfillRequest 或人工回补请求；
校验 data_collection_domain；
校验 timeframe、UTC 范围和 backfill_mode；
如果来自 BackfillRequest，原子 claim 为 running；
获取 Kline 写入锁；
创建 BackfillRun = running；
通过 Gateway 获取 server time；
按分页规则通过 Gateway 获取 Kline；
过滤未收盘 Kline；
按 missing_open_times 精确过滤；
规范化 Kline；
按唯一业务键比对已有 Kline；
不存在则插入；
已存在且一致则跳过；
发现冲突则进入 conflict 流程；
写 BackfillRun = success；
释放 Kline 写入锁；
标记或要求 DataQuality 复检；
返回 requires_quality_recheck = true。
```

注意：

```text
BackfillRun success 不等于 DataQuality PASS；
BackfillRun success 不允许直接生成 MarketSnapshot；
BackfillRun success 不允许直接进入基于该回补窗口的策略或交易主链路。
```

## 24. conflict 流程

```text
发现同一唯一键核心行情字段不一致；
写 DataConflict；
写 BackfillIssue = KLINE_CONFLICT；
写 BackfillRun.status = conflict；
如果来自 BackfillRequest，更新 BackfillRequest.status = conflict；
写必要 AlertEvent；
不覆盖已有 Kline；
不继续写冲突后的数据；
释放 Kline 写入锁；
返回 requires_quality_recheck = true 或 manual_review_required。
```

冲突流程不得自动放行基于该回补窗口的当前主链路下游。

## 25. blocked / failed / unknown 流程

blocked 场景：

```text
采集域不匹配；
timeframe 不支持；
UTC 范围非法；
周期边界不对齐；
分页或 bars 超过上限；
BackfillRequest 已处于终态；
BackfillRequest 被其他任务 claim；
Kline 写入锁不可取得；
missing_open_times 非法；
dry-run 检查发现阻断条件。
```

failed 场景：

```text
Gateway 获取 server time 失败；
Gateway 获取 Kline 失败；
Gateway 返回 payload 结构异常；
数据库读取失败；
数据库写入失败；
BackfillRun 写入失败；
BackfillRequest 状态更新失败；
锁释放失败；
未预期系统异常。
```

unknown 场景：

```text
无法确认 Gateway 请求结果；
无法确认 Kline 是否部分写入；
无法确认 BackfillRun 最终状态；
无法确认锁是否释放；
事务结果不可确认。
```

这些状态都必须：

```text
不得放行 MarketSnapshot；
不得进入策略和交易链路；
必要时写 BackfillIssue；
必要时写 AlertEvent；
要求人工检查或后续 RuntimeGuard 巡检。
```

## 26. 回补后 DataQuality 复检

回补成功不等于数据可信。

DataBackfill 在完成后只能：

```text
标记 requires_quality_recheck = true；
记录 recheck_window_start_open_time_utc；
记录 recheck_window_end_open_time_utc；
返回给编排层或人工入口；
必要时写 AlertEvent。
```

DataBackfill 不得：

```text
直接调用 DataQuality service；
直接触发 DataQuality task；
同步等待 DataQualityResult；
生成 DataQualityResult = PASS；
强行放行 MarketSnapshot；
直接触发 FeatureLayer；
直接进入交易链路。
```

后续流程必须是：

```text
BackfillRun success
→ 标记或要求 DataQuality 复检
→ PipelineOrchestrator / recovery scan / 人工入口重新执行 DataQuality
→ 新 DataQualityResult = PASS 且覆盖目标窗口
→ MarketSnapshot 才可继续
```

## 27. 与 DataQuality 的关系

DataQuality 负责：

```text
发现缺口；
发现冲突；
记录 DataQualityIssue；
创建 BackfillRequest；
回补后复检并决定是否 PASS。
```

DataBackfill 负责：

```text
claim BackfillRequest；
通过 Gateway 拉取可信源 Kline；
幂等写入 Kline；
记录 BackfillRun；
记录冲突和问题；
要求复检。
```

规则：

```text
DataBackfill 不代替 DataQuality；
BackfillRun 不替代 DataQualityResult；
回补完成不能直接放行 MarketSnapshot；
DataQuality PASS 前当前主链路下游不得继续。
```

## 28. 与 MarketSnapshot 的关系

MarketSnapshot 不直接读取 BackfillRun 作为可信依据。

MarketSnapshot 只能读取通过 DataQuality PASS 的 Kline 窗口。

规则：

```text
BackfillRun success 但尚未复检 → 不得生成 MarketSnapshot；
BackfillRun success 但复检 FAIL → 不得生成 MarketSnapshot；
BackfillRun conflict / blocked / failed / unknown → 不得生成 MarketSnapshot；
MarketSnapshot 不触发 DataBackfill；
MarketSnapshot 不请求 Binance；
MarketSnapshot 不写 Kline。
```

## 29. 与 PipelineOrchestrator 的关系

PipelineOrchestrator 可以编排 DataBackfill，但不解释回补内部状态。

规则：

```text
编排层通过 BusinessStepAdapter 调用 DataBackfill service；
adapter 负责把 DataBackfill 原始结果映射为 normalized_status 和 flow_action；
DataBackfill 返回 BackfillRequest、BackfillRun、DataConflict 和 BackfillIssue 索引；
OrchestrationBusinessObjectLink 可以记录这些业务对象；
业务对象不得保存或查询 orchestration_run_id；
DataBackfill 幂等键不得依赖 orchestration_run_id；
BackfillRun success 后由编排层根据步骤定义重新进入 DataQuality。
```

## 30. 与 RuntimeGuard 的关系

RuntimeGuard 可以发现回补卡住、长期 running、unknown 或重复失败。

RuntimeGuard 不得：

```text
自动执行 BackfillRequest；
自动修改 BackfillRun；
自动释放 Kline 写入锁；
自动写 Kline；
自动请求 Binance；
自动放行 MarketSnapshot。
```

RuntimeGuard 只能创建或更新 RuntimeGuardIssue，并写必要 AlertEvent。

## 31. AlertEvent

DataBackfill 在以下情况必须写 AlertEvent：

```text
BackfillRun blocked；
BackfillRun failed；
BackfillRun conflict；
BackfillRun unknown；
BackfillRequest claim 失败超过阈值；
Gateway 长时间失败；
Gateway 返回 unknown；
请求结果为空；
全部 Kline 未收盘；
missing_open_times 未全部返回；
发现 DataConflict；
写库失败；
锁释放失败；
需要人工审计；
回补完成但需要复检。
```

可以不写正式 AlertEvent 的情况：

```text
dry-run 预览；
重复请求被幂等跳过；
已存在且一致的 Kline 被跳过；
少量未收盘 Kline 被正常过滤且不影响目标回补。
```

规则：

```text
DataBackfill 只写 AlertEvent；
DataBackfill 不直接发送 Hermes；
AlertEvent 不得包含完整 Binance 响应；
AlertEvent 不得包含完整 Kline 批量数据；
AlertEvent 不得包含 API key、secret、signature 或 header；
Notifications 负责后续投递。
```

## 32. 数据库、Redis 与外部服务

```text
读 MySQL：是，读取 BackfillRequest、BackfillRun、Kline、DataQualityIssue 和历史冲突记录。
写 MySQL：是，写入 BackfillRequest 状态、BackfillRun、BackfillIssue、DataConflict、Kline 和 AlertEvent。
访问 Redis：可用于 Kline 写入锁、短期任务状态、短期限频辅助和幂等保护，不作为唯一事实。
访问 Binance：是，但只能通过 BinancePublicMarketGateway。
发送 Hermes：否，只写 AlertEvent。
调用大模型：否。
涉及交易执行：否。
允许真实交易：否。
```

MySQL 是 BackfillRequest、BackfillRun、BackfillIssue、DataConflict 和 Kline 的正式事实来源。

Redis 不可用时：

```text
不得丢失 Kline；
不得只依赖 Redis 判断 BackfillRequest 是否已执行；
如果无法取得 Kline 写入锁或等价并发保护，必须 blocked 或 failed；
不得在并发安全不可判断时继续请求 Gateway 或写 Kline。
```

## 33. Management command 与 Celery task

DataBackfill 的 command / task 只能：

```text
解析参数；
生成或传递 trace_id；
设置 trigger_source；
校验 dry-run / confirm-write；
调用 DataBackfill service；
输出结果摘要。
```

禁止：

```text
在 command / task 中直接请求 Binance；
在 command / task 中直接写 Kline；
在 command / task 中直接 claim BackfillRequest；
在 command / task 中直接释放 Kline 写入锁；
在 command / task 中直接创建 MarketSnapshot；
在 command / task 中直接调用 DataQuality；
在 command / task 中直接调用 OrderPlan；
在 command / task 中直接调用 RiskCheck；
在 command / task 中直接提交订单；
在 command / task 中直接发送 Hermes。
```

人工 confirm-write 回补必须记录：

```text
operator_id；
reason；
evidence；
trace_id；
trigger_source。
```

## 34. dry-run

dry-run 用于预览回补影响。

dry-run 允许通过 BinancePublicMarketGateway 请求 Binance，以便真实预览将会插入、跳过或冲突的 Kline。

dry-run 可以：

```text
校验参数；
校验 data_collection_domain；
计算分页；
请求 Gateway 获取 Kline；
过滤未收盘 Kline；
按 missing_open_times 精确过滤；
读取已有 Kline；
比较是否会插入、跳过或冲突；
生成回补预览结果。
```

dry-run 不得：

```text
写正式 Kline；
修改已有 Kline；
删除已有 Kline；
覆盖冲突数据；
写正式 BackfillRequest 终态；
写正式 BackfillRun success；
写正式 AlertEvent；
要求 DataQuality 复检；
生成 MarketSnapshot；
进入策略链路；
进入交易链路。
```

dry-run 请求 Gateway 规则：

```text
使用 fake Gateway 进行默认测试；
明确标记 dry_run；
真实外部 dry-run 必须由人工入口或受控诊断入口显式触发；
不得由周期调度默认触发真实外部 dry-run；
不得写正式 Kline；
不得写正式 BackfillRun 终态；
不得写正式 AlertEvent；
不得触发正式主链路下游。
```

## 35. 幂等与并发

DataBackfill 必须支持幂等和并发保护。

规则：

```text
同一 business_request_key 重复执行不得生成重复 BackfillRun；
同一 BackfillRequest 只能被一个运行 claim；
同一 data_collection_domain / timeframe 的 Kline 写入必须受锁保护；
同一 Kline 唯一业务键不得重复插入；
等价 DataConflict 不得重复刷屏；
等价 AlertEvent 不得重复刷屏；
Celery 重复投递不得重复请求 Gateway 和写 Kline；
并发冲突时必须 skipped / blocked / failed，不得抢写。
```

如果无法判断幂等状态或写入状态：

```text
BackfillRun.status = unknown；
不得放行 MarketSnapshot；
必要时写 AlertEvent；
等待 RuntimeGuard 或人工检查。
```

## 36. 异常处理

异常处理规则：

```text
采集域不匹配 → blocked；
timeframe 不支持 → blocked；
UTC 范围非法 → blocked；
周期边界不对齐 → blocked；
BackfillRequest 不可 claim → skipped 或 blocked；
Kline 写入锁不可取得 → skipped 或 blocked；
分页或 bars 超限 → blocked；
Gateway blocked_before_send → blocked；
Gateway failed_before_send → failed；
Gateway unknown_after_send → unknown；
Gateway rate_limited → failed 或 blocked，由 Gateway 错误分类决定；
payload 结构异常 → failed；
全部 Kline 未收盘 → blocked 或 failed；
missing_open_times 未全部返回 → blocked 或 failed；
同一唯一键数据冲突 → conflict；
数据库写入失败 → failed 或 unknown；
锁释放失败 → failed 或 unknown；
事务结果不可确认 → unknown。
```

任何异常都不得导致未收盘、冲突或不可信 Kline 进入当前主链路下游。

## 37. 测试要求

必须测试：

```text
1. DataBackfill 只能通过 BinancePublicMarketGateway 获取 Kline。
2. DataBackfill 不直接创建 Binance HTTP client。
3. DataBackfill 不调用账户、订单、成交或交易 Gateway。
4. 请求 Kline 时不传 timeZone。
5. Binance 时间戳按 UTC 解释。
6. 采集域不匹配时不请求 Gateway。
7. start_time_utc / end_time_utc 非法时 blocked。
8. timeframe 周期边界不对齐时 blocked。
9. BackfillRequest claim 防止重复执行。
10. BackfillRequest 终态时不请求 Gateway。
11. Kline 写入锁存在时不请求 Gateway、不写 Kline。
12. 分页超过上限时 blocked 且不写部分 Kline。
13. bars 超过上限时 blocked 且不写部分 Kline。
14. 未收盘 Kline 被过滤。
15. 全部未收盘时 blocked 或 failed。
16. missing_open_times 非空时只写指定 open_time。
17. Gateway 返回额外 open_time 时过滤且记录 filtered_not_requested_count。
18. 已存在且一致时 skipped_existing。
19. 不存在时 insert。
20. 已存在但 OHLCV 不一致时记录 DataConflict 且不覆盖。
21. conflict_recheck 不覆盖 Kline。
22. BackfillRun success 后 requires_quality_recheck = true。
23. BackfillRun success 不生成 DataQualityResult。
24. BackfillRun success 不生成 MarketSnapshot。
25. DataBackfill 不调用 DataQuality service。
26. 回补失败写 BackfillRun 和必要 AlertEvent。
27. AlertEvent 不包含完整 Binance 响应或密钥。
28. Redis 不可用且无法保证锁时 blocked / failed。
29. command 只调用 service。
30. Celery task 只调用 service。
31. dry-run 不写正式 Kline、终态 BackfillRun 或 AlertEvent。
32. 默认测试使用 fake Gateway，不访问真实 Binance。
```

## 38. 验收标准

DataBackfill 验收通过必须满足：

```text
只通过 BinancePublicMarketGateway 拉取 Kline；
只写入已收盘 Kline；
所有核心时间使用 UTC；
请求 Kline 不传 timeZone；
当前采集域固定为 Binance USDS-M BTCUSDT；
当前主链路支持 4h 与 1d；
支持 initial_historical_backfill；
支持 gap_backfill；
支持 manual_range_backfill；
支持 conflict_recheck；
支持 failure_recovery_backfill；
支持 BackfillRequest 原子 claim；
支持 missing_open_times 精确回补；
支持分页和最大 bars 上限；
Kline 写入幂等；
Kline 冲突不覆盖；
DataCollection 与 DataBackfill 共用 Kline 写入锁；
BackfillRun 可审计；
BackfillRun success 后仍必须 DataQuality 复检；
DataQuality PASS 前不得进入 MarketSnapshot；
不读取账户、持仓、订单或成交；
不生成 MarketSnapshot、特征、信号、决策、订单或风控结果；
必要异常写 AlertEvent；
不直接发送 Hermes；
不调用 DeepSeek；
不涉及交易执行；
默认测试不访问真实 Binance。
```

## 39. 当前不包含的能力

当前不包含：

```text
多交易所回补；
多采集域同时回补并进入主链路；
多品种组合回补；
WebSocket 拼接 Kline；
第三方行情源回补；
多数据源自动择优；
自动覆盖冲突 Kline；
自动删除重复 Kline；
人工编辑 Kline；
自动生成 DataQualityResult；
自动生成 MarketSnapshot；
直接触发策略或交易；
复杂可视化回补管理；
自动长期历史完整性扫描。
```

## 40. 最终结论

DataBackfill 的最终定位是：

```text
通过受控 Gateway 从可信源补齐或复核 Kline，但不拥有质量放行权。
```

一句话：

```text
回补只是把数据重新拉回来；只有 DataQuality 重新 PASS，系统才可以基于该质量窗口继续生成 MarketSnapshot 和进入后续主链路。
```
