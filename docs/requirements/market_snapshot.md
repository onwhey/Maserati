# MarketSnapshot 需求

## 1. 模块定位

MarketSnapshot 是策略分析前的市场证据快照模块。

本模块负责把已经落库、已经通过 DataQuality 授权的 Kline 窗口，固化成一份可追溯、可复盘、不可混用的市场事实输入。

MarketSnapshot 的核心对象是：

```text
MarketSnapshot
```

它回答的是：

```text
本次分析使用哪一个 data_collection_domain；
本次分析使用哪一组 4h Kline；
本次分析使用哪一组 1d Kline；
这些 Kline 是否已经通过 DataQuality；
这些 Kline 对应的数据窗口、质量结果和 trace 信息是什么；
当前主链路下游 FeatureLayer、AtomicSignal、DomainSignal、MarketRegime、StrategyRouting、StrategySignal 和 DecisionSnapshot 是否沿同一业务外键链追溯到本份市场证据。
```

MarketSnapshot 不是：

```text
Kline 采集模块；
数据质量检查模块；
数据回补模块；
价格事实模块；
特征计算模块；
原子信号模块；
策略信号模块；
目标仓位决策模块；
订单规划模块；
风控模块；
执行模块；
复盘分析模块；
大模型模块。
```

一句话：

```text
MarketSnapshot 只负责把通过质量授权的行情窗口固定下来，作为后续分析链路共同引用的市场证据。
```

## 2. 设计目标

MarketSnapshot 的目标是：

```text
固定一轮分析使用的市场事实；
统一 4h 主周期与 1d 辅助周期的行情窗口；
强制当前主链路下游使用同一份市场证据；
防止 FeatureLayer、信号或策略模块散乱查询 Kline；
防止未通过 DataQuality 的 Kline 进入分析链路；
防止不同分析批次混用行情窗口；
保证复盘时能还原当时使用的数据范围、质量授权和触发来源。
```

MarketSnapshot 创建成功只表示市场证据可供分析链路消费，不表示：

```text
策略一定会产生信号；
DecisionSnapshot 一定会产生目标仓位；
后续一定会进入订单链路；
本轮一定允许真实交易。
```

## 3. 当前范围

当前主链路只支持固定 data_collection_domain。

当前 data_collection_domain 固定为：

```text
exchange = binance
market_type = usds_m_futures
symbol = BTCUSDT
```

采集域是行情数据来源域，不等于交易执行域。

交易模块可以根据系统配置支持 USDS-M 或 COIN-M，但 MarketSnapshot 当前不随交易执行域切换。

data_collection_domain 至少包含：

```text
exchange
market_type
symbol
```

当前分析周期为：

```text
base_timeframe = 4h
higher_timeframe = 1d
```

语义：

```text
4h 是主策略分析周期；
1d 是大周期趋势、市场环境和复盘辅助周期；
同一份 MarketSnapshot 必须同时固定 4h 与 1d 窗口。
```

MarketSnapshot 不得通过参数热切换 symbol 或 market_type。

如果输入与 data_collection_domain 不一致，必须返回 blocked，不得读取非当前采集域的 Kline 作为主链路市场证据。

## 4. 负责事项

MarketSnapshot 负责：

```text
读取固定 data_collection_domain；
校验输入的 exchange、market_type、symbol；
校验 base_timeframe 与 higher_timeframe；
校验 analysis_close_time_utc；
计算或接收本次分析应使用的 4h 与 1d 窗口；
读取已落库 Kline；
读取对应 DataQualityResult；
确认 DataQualityResult.status = PASS；
确认 DataQualityResult.allows_downstream = true；
确认 DataQualityResult 覆盖本次目标窗口；
确认 Kline 数量满足 lookback_count；
确认 Kline 窗口可按 open_time_utc 连续回查；
确认窗口内 Kline 都是已收盘事实；
创建或复用 MarketSnapshot；
记录窗口边界、数量、质量结果、trace_id 和 trigger_source；
向 adapter 返回 market_snapshot_id；
必要时写 AlertEvent。
```

## 5. 不负责事项

MarketSnapshot 不负责：

```text
请求 Binance；
请求 Binance server time；
创建 Binance HTTP client；
读取 Binance 账户、余额、持仓、订单或成交；
采集 Kline；
回补 Kline；
修复 Kline；
覆盖 Kline；
删除 Kline；
写入 Kline；
创建 DataQualityResult；
执行完整 DataQuality 检查；
创建 BackfillRequest；
执行 BackfillRequest；
触发 DataBackfill；
生成 FeatureValue；
生成 AtomicSignal；
生成 DomainSignal；
生成 MarketRegime；
执行 StrategyRouting；
生成 StrategySignal；
生成 StrategySignalQualityResult；
生成 DecisionSnapshot；
生成 BinanceSyncRun；
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
直接发送 Hermes；
解释策略优劣；
给出交易建议。
```

MarketSnapshot 不得因为发现数据缺口而直接修复数据。它只能阻断，并把原因记录清楚。

## 6. 与 Binance 请求边界

MarketSnapshot 不得访问 Binance。

禁止：

```text
直接调用 Binance REST；
直接调用 Binance WebSocket；
直接调用 BinancePublicMarketGateway；
直接调用 BinanceAccountReadGateway；
直接调用 BinanceOrderSubmissionGateway；
直接调用 BinanceOrderStatusGateway；
直接调用 BinanceFillQueryGateway；
临时请求 Binance server time；
临时请求 mark price；
使用任何绕过 BinanceGateway 的 HTTP client。
```

MarketSnapshot 只能消费已经落库并通过质量授权的事实：

```text
Kline
DataQualityResult
DataQualityIssue 摘要
DataCollectionRun 摘要
BackfillRun 摘要
```

其中 DataCollectionRun 与 BackfillRun 只作为追溯信息，不替代 DataQualityResult。

## 7. 输入合同

MarketSnapshotService 输入至少包括：

```text
exchange
market_type
symbol
base_timeframe
higher_timeframe
analysis_close_time_utc
analysis_reference_time_utc
lookback_4h_count
lookback_1d_count
business_request_key
trace_id
trigger_source
```

### 7.1 analysis_close_time_utc

`analysis_close_time_utc` 表示本次分析所针对的主周期收盘边界。

规则：

```text
必须使用 UTC；
必须落在 4h 收盘边界；
不得使用本地时间；
不得使用 PRC 时间；
不得根据运行机器时区推断；
不得根据用户 IP 推断。
```

4h 收盘边界为：

```text
00:00
04:00
08:00
12:00
16:00
20:00
```

示例：

```text
UTC 08:05 执行分析；
本次分析对象是 04:00-08:00 的 4h Kline；
analysis_close_time_utc = 08:00；
latest_4h_open_time_utc = 04:00。
```

### 7.2 analysis_reference_time_utc

`analysis_reference_time_utc` 表示本次快照判断所使用的可信 UTC 参考时间。

允许来源：

```text
PipelineOrchestrator 按 UTC 调度传入；
DataCollectionRun 中记录的 Binance server time；
BackfillRun 中记录的 Binance server time；
受控人工入口明确传入的 UTC 时间。
```

禁止来源：

```text
服务器本地时间；
PRC 时间；
用户 IP 时区；
MarketSnapshot 临时请求 Binance server time。
```

如果本次判断需要参考时间但缺少可信来源，必须 blocked。

### 7.3 lookback_count

`lookback_4h_count` 与 `lookback_1d_count` 必须可配置，不得硬编码散落在业务逻辑中。

建议默认值：

```text
lookback_4h_count = 500
lookback_1d_count = 365
```

规则：

```text
MarketSnapshot 必须记录实际使用的 lookback_count；
MarketSnapshot 必须记录实际读到的 actual_count；
配置变化不得影响已经创建快照的复盘解释；
actual_count 不足时必须 blocked。
```

### 7.4 business_request_key

`business_request_key` 是 MarketSnapshot 的业务幂等键。

至少应覆盖：

```text
exchange
market_type
symbol
base_timeframe
higher_timeframe
analysis_close_time_utc
lookback_4h_count
lookback_1d_count
```

`trace_id` 不得作为业务幂等键。

## 8. 输出合同

MarketSnapshotService 输出至少包括：

```text
status
reason_code
market_snapshot_id
business_request_key
analysis_close_time_utc
latest_4h_open_time_utc
latest_1d_open_time_utc
lookback_4h_count
lookback_1d_count
actual_4h_count
actual_1d_count
data_quality_result_4h_id
data_quality_result_1d_id
allows_feature_layer
trace_id
```

`allows_feature_layer = true` 只允许在 `status = created` 时出现。

其他任何状态都必须：

```text
allows_feature_layer = false；
不得进入 FeatureLayer；
不得进入 AtomicSignal；
不得进入 DomainSignal；
不得进入 MarketRegime；
不得进入 StrategyRouting；
不得进入 StrategySignal；
不得进入 StrategySignalQuality；
不得进入 DecisionSnapshot；
不得进入基于该 MarketSnapshot 的当前订单主链路。
```

## 9. MarketSnapshot 对象

MarketSnapshot 至少表达：

```text
market_snapshot_id
business_request_key
exchange
market_type
symbol
base_timeframe
higher_timeframe
analysis_close_time_utc
analysis_reference_time_utc
status
reason_code
blocked_reason
error_code
error_message
latest_4h_open_time_utc
latest_1d_open_time_utc
lookback_4h_count
lookback_1d_count
actual_4h_count
actual_1d_count
start_4h_open_time_utc
end_4h_open_time_utc
start_1d_open_time_utc
end_1d_open_time_utc
data_quality_result_4h_id
data_quality_result_1d_id
data_collection_run_ids
backfill_run_ids
payload_summary
trace_id
trigger_source
created_at_utc
finished_at_utc
```

字段命名和具体表结构由后续数据模型设计确定，但以上语义必须可保存、可查询、可追溯。

## 10. 状态语义

MarketSnapshot 状态至少包括：

```text
created
blocked
failed
unknown
```

### 10.1 created

`created` 表示快照成功创建或幂等复用，并且允许 FeatureLayer 消费。

必须满足：

```text
data_collection_domain 匹配；
base_timeframe = 4h；
higher_timeframe = 1d；
analysis_close_time_utc 合法；
4h Kline 窗口存在；
1d Kline 窗口存在；
4h DataQualityResult.status = PASS；
1d DataQualityResult.status = PASS；
4h DataQualityResult.allows_downstream = true；
1d DataQualityResult.allows_downstream = true；
4h DataQualityResult 覆盖目标窗口；
1d DataQualityResult 覆盖目标窗口；
4h actual_count >= lookback_4h_count；
1d actual_count >= lookback_1d_count；
窗口内 Kline 全部已收盘；
窗口可按 UTC open_time_utc 连续回查。
```

### 10.2 blocked

`blocked` 表示业务前置条件不满足，本轮不能继续分析。

典型原因：

```text
采集域不匹配；
timeframe 不支持；
analysis_close_time_utc 不在 4h 边界；
analysis_reference_time_utc 缺失或不可追溯；
4h 最新已收盘 Kline 缺失；
1d 当前理论最新已收盘 Kline 缺失；
4h DataQualityResult 缺失；
1d DataQualityResult 缺失；
4h DataQualityResult 非 PASS；
1d DataQualityResult 非 PASS；
DataQualityResult 不允许当前主链路下游消费；
DataQualityResult 覆盖窗口不足；
Kline 数量不足；
Kline 窗口不连续；
读到未收盘 Kline；
发现同一窗口存在不可判定的数据冲突。
```

blocked 不表示系统异常，也不表示策略失败。

blocked 后不得自动请求 Binance、不得自动创建回补、不得自动跳过数据质量授权。

### 10.3 failed

`failed` 表示本地系统、数据库、事务或合同执行失败。

典型原因：

```text
数据库读取失败；
数据库写入失败；
幂等冲突无法安全处理；
序列化失败；
必要 AlertEvent 写入失败且该事件属于高风险阻断场景；
代码未预期异常；
输入输出合同损坏。
```

failed 必须记录 error_code、error_message、trace_id 和 trigger_source。

### 10.4 unknown

`unknown` 表示无法确认 MarketSnapshot 是否已经安全创建或写入。

典型原因：

```text
事务结果不可确认；
数据库连接中断后无法确认提交状态；
MarketSnapshot 写入状态不可确认；
AlertEvent 写入状态不可确认且影响阻断事实审计；
幂等查询无法确认唯一事实。
```

unknown 不得被解释为 created，也不得被解释为可以继续。

unknown 必须交给 PipelineOrchestrator、RuntimeGuard 或人工入口处理。

## 11. 窗口计算规则

### 11.1 4h 窗口

4h 最新 Kline 由 `analysis_close_time_utc` 决定：

```text
latest_4h_open_time_utc = analysis_close_time_utc - 4 小时
```

4h 目标窗口为：

```text
end_4h_open_time_utc = latest_4h_open_time_utc
start_4h_open_time_utc = end_4h_open_time_utc - (lookback_4h_count - 1) * 4 小时
```

4h 窗口必须完整覆盖 `lookback_4h_count` 根 Kline。

### 11.2 1d 窗口

1d 最新 Kline 必须按日线收盘边界独立判断。

规则：

```text
latest_1d_open_time_utc 是 close_time_utc <= analysis_reference_time_utc 的最新 1d Kline open_time；
1d 不要求每个 4h 周期都出现新 Kline；
如果新的 1d 理论上已经收盘但尚未通过质量授权，不得沿用更早的 1d Kline 假装新鲜。
```

1d 目标窗口为：

```text
end_1d_open_time_utc = latest_1d_open_time_utc
start_1d_open_time_utc = end_1d_open_time_utc - (lookback_1d_count - 1) * 1 天
```

### 11.3 禁止的时间处理

禁止：

```text
用数据库自增 id 判断 Kline 顺序；
用服务器本地时间判断最新 Kline；
用 PRC 时间参与窗口计算；
用用户 IP 推断业务时间；
用 4h 节奏推断 1d 一定可沿用；
请求 Kline 时传 timeZone 参数。
```

## 12. DataQualityResult 覆盖合同

MarketSnapshot 只能消费 `DataQualityResult.status = PASS` 且 `allows_downstream = true` 的质量结果。

每个 timeframe 对应的 DataQualityResult 必须满足：

```text
exchange 与 MarketSnapshot 一致；
market_type 与 MarketSnapshot 一致；
symbol 与 MarketSnapshot 一致；
timeframe 与目标窗口一致；
check_start_open_time_utc <= MarketSnapshot 对应 start_open_time_utc；
check_end_open_time_utc >= MarketSnapshot 对应 end_open_time_utc；
coverage_start_open_time_utc <= MarketSnapshot 对应 start_open_time_utc；
coverage_end_open_time_utc >= MarketSnapshot 对应 end_open_time_utc；
expected_count >= MarketSnapshot 对应 lookback_count；
actual_count >= MarketSnapshot 对应 lookback_count；
issue_count = 0；
allows_downstream = true。
```

规则：

```text
4h 与 1d 必须分别满足覆盖合同；
短窗口 PASS 不得授权长窗口 MarketSnapshot；
只覆盖最近少量 Kline 的 PASS 不得授权更大 lookback；
DataCollectionRun 成功不得替代 DataQualityResult；
BackfillRun 成功不得替代 DataQualityResult；
任一周期覆盖不足时，MarketSnapshot 必须 blocked。
```

## 13. Kline 消费合同

MarketSnapshot 读取的 Kline 必须满足：

```text
来自正式 Kline 存储；
data_source 是当前允许的可信来源；
exchange / market_type / symbol / timeframe 与目标一致；
open_time_utc 与 timeframe 边界对齐；
close_time_utc = open_time_utc + timeframe_interval；
close_time_utc <= analysis_reference_time_utc；
窗口内 open_time_utc 连续；
窗口内数量等于目标 lookback_count；
不存在未收盘 Kline；
不存在不可判定重复或冲突。
```

MarketSnapshot 不重新执行完整数据质量检查，但必须做这些消费前确认。

如果确认失败：

```text
status = blocked；
reason_code 记录具体原因；
必要时写 AlertEvent；
不得创建可消费快照。
```

## 14. payload 规则

MarketSnapshot 的 `payload_summary` 只保存摘要、窗口索引和审计元数据。

允许包含：

```text
market_snapshot_id
business_request_key
exchange
market_type
symbol
base_timeframe
higher_timeframe
analysis_close_time_utc
latest_4h_open_time_utc
latest_1d_open_time_utc
lookback_4h_count
lookback_1d_count
actual_4h_count
actual_1d_count
start_4h_open_time_utc
end_4h_open_time_utc
start_1d_open_time_utc
end_1d_open_time_utc
data_quality_result ids
source run ids
trace_id
trigger_source
```

禁止在 payload 中保存：

```text
完整 Kline 数组；
逐根 open / high / low / close / volume 明细；
完整 Binance 响应；
不可控长文本；
策略解释；
交易建议；
大模型输出；
账户余额；
持仓明细；
订单信息；
密钥、signature、header。
```

如果下游需要完整 Kline，应通过 MarketSnapshot 记录的窗口索引回查正式 Kline 表。

MarketSnapshot 不是第二份 Kline 仓库。

## 15. 禁止包含策略内容

MarketSnapshot 禁止包含：

```text
趋势判断；
开多判断；
开空判断；
平仓判断；
持仓建议；
目标仓位；
入场价格；
止损价格；
止盈价格；
仓位大小；
杠杆建议；
保证金建议；
策略评分；
风控结论；
大模型解释。
```

这些内容分别属于 FeatureLayer、AtomicSignal、DomainSignal、MarketRegime、StrategyRouting、StrategySignal、StrategySignalQuality、DecisionSnapshot、RiskCheck 或 ReviewDataset，不属于 MarketSnapshot。

## 16. 幂等与并发

同一业务幂等键只能有一份可消费 MarketSnapshot。

规则：

```text
相同 business_request_key 重复执行时，如已有 created 快照，应返回同一 market_snapshot_id；
不得为同一 business_request_key 创建第二份 created 快照；
blocked / failed / unknown 记录可以保留审计历史；
重新尝试必须保留原失败或阻断记录；
并发创建必须通过数据库唯一约束或等价事务保护；
trace_id 不参与幂等判断。
```

如果无法确认幂等状态：

```text
status = unknown；
不得放行 FeatureLayer；
必要时写 AlertEvent。
```

## 17. 成功流程

```text
PipelineOrchestrator
→ BusinessStepAdapter 调用 MarketSnapshotService
→ 校验 data_collection_domain
→ 校验 UTC 分析时间
→ 计算 4h 窗口
→ 计算 1d 窗口
→ 读取 4h DataQualityResult
→ 读取 1d DataQualityResult
→ 校验两个质量结果均 PASS 且允许当前主链路下游消费
→ 校验两个质量结果覆盖目标窗口
→ 读取 4h Kline 窗口
→ 读取 1d Kline 窗口
→ 校验数量、连续性和已收盘
→ 创建或复用 MarketSnapshot
→ 返回 market_snapshot_id
→ adapter 归一化为 SUCCEEDED + CONTINUE
→ PipelineOrchestrator 继续 FeatureLayer
```

成功时可以只记录结构化日志，不强制写正式 AlertEvent。

## 18. 阻断流程

```text
MarketSnapshotService 前置条件不满足
→ 返回 blocked
→ 写明 reason_code 与 blocked_reason
→ 必要时写 AlertEvent
→ adapter 归一化为 BLOCKED
→ PipelineOrchestrator 停止或进入受控恢复路径
```

阻断后不得：

```text
请求 Binance；
触发 DataCollection；
触发 DataBackfill；
创建 DataQualityResult；
继续 FeatureLayer；
继续基于该 MarketSnapshot 的策略主链路；
继续订单链路。
```

是否先补采、回补或重新执行 DataQuality，由 PipelineOrchestrator 的步骤定义、RuntimeGuard 或人工入口决定。

## 19. 失败与未知流程

失败流程：

```text
发生本地系统异常、数据库异常或合同损坏
→ 返回 failed
→ 记录 error_code 与 error_message
→ 写 AlertEvent
→ adapter 归一化为 FAILED
```

未知流程：

```text
无法确认事务或写入结果
→ 返回 unknown
→ 记录 reason_code
→ 写必要 AlertEvent
→ adapter 归一化为 UNKNOWN
→ 不允许当前主链路下游消费
```

`unknown` 必须保守处理，不得自动当作 created 继续。

## 20. 与 DataCollection 的关系

DataCollection 负责：

```text
通过 BinancePublicMarketGateway 获取已收盘 Kline；
过滤未收盘 Kline；
幂等写入 Kline；
记录 DataCollectionRun；
把可检查范围交给 DataQuality。
```

MarketSnapshot 负责：

```text
读取已通过 DataQuality 授权的 Kline 窗口；
创建市场证据快照。
```

规则：

```text
DataCollection 成功不等于 DataQuality PASS；
DataCollectionRun 不等于 MarketSnapshot；
MarketSnapshot 不调用 DataCollection；
DataCollection 不创建 MarketSnapshot；
采集失败时不得跳过 DataQuality 直接创建 MarketSnapshot。
```

## 21. 与 DataQuality 的关系

DataQuality 是 Kline 进入 MarketSnapshot 前的质量授权边界。

MarketSnapshot 只能消费：

```text
DataQualityResult.status = PASS；
DataQualityResult.allows_downstream = true；
DataQualityResult 覆盖目标窗口。
```

MarketSnapshot 不得：

```text
忽略 DataQualityResult；
使用 FAIL / BLOCKED / FAILED / UNKNOWN 的质量结果；
使用覆盖不足的 PASS；
自行重新执行完整质量检查；
把 DataQualityResult 当作 Kline 数据本身。
```

## 22. 与 DataBackfill 的关系

DataBackfill 负责把缺口或需要复核的 Kline 从可信来源拉回正式 Kline 存储。

规则：

```text
BackfillRun success 不等于 DataQuality PASS；
BackfillRun success 不允许直接生成 MarketSnapshot；
回补后必须重新执行 DataQuality；
新的 DataQualityResult PASS 且覆盖目标窗口后，MarketSnapshot 才能继续；
MarketSnapshot 不触发 DataBackfill。
```

如果 MarketSnapshot 发现缺口或覆盖不足：

```text
返回 blocked；
记录原因；
必要时写 AlertEvent；
等待编排、巡检或人工入口处理。
```

## 23. 与 FeatureLayer 的关系

FeatureLayer 必须消费明确的 MarketSnapshot。

规则：

```text
FeatureLayer 只能读取 adapter 明确传入的 market_snapshot_id；
FeatureLayer 不得绕过 MarketSnapshot 散乱查询 Kline；
FeatureLayer 不得自行创建 MarketSnapshot；
FeatureLayer 结果必须能追溯到 MarketSnapshot；
MarketSnapshot 非 created 时 FeatureLayer 不得运行。
```

如果 FeatureLayer 需要完整 Kline：

```text
必须通过 MarketSnapshot 的窗口索引查询；
不得自行决定分析窗口；
不得混用其他快照的窗口。
```

## 24. 与信号和决策链路的关系

以下对象必须基于同一个 MarketSnapshot 派生：

```text
FeatureSet / FeatureValue
AtomicSignalSet / AtomicSignalValue
DomainSignalSet / DomainSignalValue
MarketRegimeSnapshot
StrategyRouteDecision
StrategySignal
StrategySignalQualityResult
DecisionSnapshot
```

规则：

```text
AtomicSignal 不得直接查询 Kline 选择新窗口；
DomainSignal 不得直接查询 Kline 选择新窗口；
MarketRegime 不得直接查询 Kline 选择新窗口；
StrategyRouting 不得直接查询 Kline 选择新窗口；
StrategySignal 不得直接查询 Kline 选择新窗口；
DecisionSnapshot 不得直接查询 Kline 选择新窗口；
DecisionSnapshot 不得生成或修改 MarketSnapshot；
MarketSnapshot blocked / failed / unknown 时，不得生成 DecisionSnapshot。
```

## 25. 与 PriceSnapshot 的关系

MarketSnapshot 与 PriceSnapshot 是两个完全不同的事实对象。

MarketSnapshot：

```text
固定策略分析所需的 Kline 窗口；
来源是已落库且通过 DataQuality 的 Kline；
作为 FeatureLayer 的直接输入，并通过业务外键链为 AtomicSignal、DomainSignal、MarketRegime、StrategyRouting、StrategySignal 和 DecisionSnapshot 提供可追溯的市场证据；
不请求 Binance；
不提供订单价格。
```

PriceSnapshot：

```text
通过 Binance Gateway 主动请求 mark price；
用于 OrderPlan、RiskCheck 和 ExecutionPreparation；
写入 MySQL，并可写入 Redis 缓存；
有 600 秒有效期；
不替代策略分析 Kline 窗口。
```

禁止：

```text
用 MarketSnapshot 中的 Kline close price 作为订单价格事实；
用 MarketSnapshot 替代 PriceSnapshot；
用 PriceSnapshot 替代 MarketSnapshot；
用 PriceSnapshot mark price 推导策略 Kline；
用 MarketSnapshot 触发价格刷新。
```

## 26. 与 PipelineOrchestrator 的关系

PipelineOrchestrator 负责安排 MarketSnapshot 步骤，但不解释 MarketSnapshot 内部业务细节。

规则：

```text
PipelineOrchestrator 通过 BusinessStepAdapter 调用 MarketSnapshotService；
BusinessStepAdapter 负责把 MarketSnapshot 原始结果映射为 normalized_status 和 flow_action；
MarketSnapshot 返回 market_snapshot_id 与窗口摘要；
OrchestrationBusinessObjectLink 可以记录 MarketSnapshot 的业务对象引用；
MarketSnapshot 业务模型不得保存或查询 orchestration_run_id；
MarketSnapshot 的幂等键不得依赖 orchestration_run_id。
```

如果 MarketSnapshot 返回 blocked，编排层是否进入 DataBackfill 或停止，由编排步骤定义决定。

MarketSnapshot 不得反向调用 PipelineOrchestrator。

## 27. 与交易链路的关系

MarketSnapshot 不直接参与订单、风控或执行。

MarketSnapshot 不得调用：

```text
Binance Account Sync；
PriceSnapshot；
OrderPlan；
CandidateOrderIntent；
RiskCheck；
ApprovedOrderIntent；
ExecutionPreparation；
Execution；
OrderStatusSync；
FillSync。
```

如果 MarketSnapshot 未 created，本轮不应继续到 DecisionSnapshot，也就不会进入基于该快照的当前订单主链路。

## 28. AlertEvent

MarketSnapshot 在以下情况应写 AlertEvent：

```text
采集域不匹配；
analysis_close_time_utc 非法；
analysis_reference_time_utc 不可用；
4h 最新已收盘 Kline 缺失；
1d 当前理论最新已收盘 Kline 缺失；
4h DataQualityResult 缺失或非 PASS；
1d DataQualityResult 缺失或非 PASS；
DataQualityResult 覆盖窗口不足；
Kline 数量不足；
Kline 窗口不连续；
发现未收盘 Kline；
发现不可判定数据冲突；
MarketSnapshot 写入失败；
MarketSnapshot 结果 unknown；
重复异常超过阈值。
```

可以不写正式 AlertEvent 的情况：

```text
重复运行且幂等返回已有 created 快照；
dry-run 预览；
人工查询已有快照；
正常 created 且无异常。
```

规则：

```text
MarketSnapshot 只写 AlertEvent；
MarketSnapshot 不直接发送 Hermes；
AlertEvent 不得包含完整 Kline 数组；
AlertEvent 不得包含完整 Binance 响应；
AlertEvent 不得包含密钥、signature 或 header；
Notifications 负责后续投递。
```

## 29. 数据库、Redis 与外部服务

```text
读 MySQL：是，读取 Kline、DataQualityResult、相关审计摘要和已有 MarketSnapshot。
写 MySQL：是，写入 MarketSnapshot 和必要 AlertEvent。
访问 Redis：可用于短期幂等保护、并发锁或短期任务状态，不作为唯一事实。
访问 Binance：否。
发送 Hermes：否，只写 AlertEvent。
调用大模型：否。
涉及交易执行：否。
允许真实交易：否。
```

MySQL 是 MarketSnapshot 的唯一业务事实来源。

Redis 不可用时：

```text
不得丢失 MarketSnapshot；
不得只依赖 Redis 判断快照是否存在；
应退回 MySQL 幂等与唯一约束；
如果无法保证并发安全，必须 blocked、failed 或 unknown。
```

## 30. Management command 与 Celery task

MarketSnapshot 的 command / task 只能：

```text
解析参数；
生成或传递 trace_id；
设置 trigger_source；
校验 dry-run / confirm-write；
调用 MarketSnapshot service；
输出结果摘要。
```

禁止在 command / task 中：

```text
直接请求 Binance；
直接读取或写入 Kline；
直接执行 DataQuality；
直接执行 DataBackfill；
直接创建 FeatureValue；
直接创建 DomainSignal；
直接创建 MarketRegime；
直接执行 StrategyRouting；
直接创建 StrategySignal；
直接创建 StrategySignalQualityResult；
直接创建 DecisionSnapshot；
直接调用 OrderPlan；
直接调用 RiskCheck；
直接提交订单；
直接发送 Hermes。
```

## 31. dry-run

dry-run 用于预览 MarketSnapshot 是否可以创建。

dry-run 可以：

```text
校验输入参数；
计算 4h 与 1d 目标窗口；
读取已有 Kline；
读取已有 DataQualityResult；
检查覆盖与数量；
返回会创建、会复用、会阻断或会失败的摘要。
```

dry-run 不得：

```text
写入 MarketSnapshot；
写入正式 AlertEvent；
写入 Kline；
创建 DataQualityResult；
创建 BackfillRequest；
请求 Binance；
触发 DataCollection；
触发 DataBackfill；
触发 FeatureLayer；
进入基于该 MarketSnapshot 的策略或交易主链路。
```

## 32. 恢复规则

系统重启、任务失败或编排恢复时，不得跳过 MarketSnapshot 前置链路。

恢复检查顺序：

```text
目标 analysis_close_time_utc 是否已有 created MarketSnapshot；
目标 4h Kline 是否存在；
目标 1d Kline 是否存在；
对应 4h DataQualityResult 是否 PASS 且覆盖窗口；
对应 1d DataQualityResult 是否 PASS 且覆盖窗口；
MarketSnapshot 是否可以创建或复用；
下游 FeatureLayer 是否已经完成。
```

规则：

```text
已有 created MarketSnapshot → 复用；
缺少 Kline → 等待采集或回补后重新 DataQuality；
DataQuality 非 PASS → 阻断；
MarketSnapshot 已创建但当前主链路下游未完成 → 从 FeatureLayer 继续；
MarketSnapshot unknown → 不自动继续，等待巡检或人工确认。
```

禁止：

```text
因为当前时间已经晚于计划时间就跳过采集和质量授权；
因为服务重启就直接生成策略信号；
因为已有其他时间的 MarketSnapshot 就替代当前 analysis_close_time_utc；
因为 4h 合格就忽略 1d；
因为 1d 合格就忽略 4h。
```

## 33. 异常处理

异常处理规则：

```text
采集域不匹配 → blocked；
timeframe 不支持 → blocked；
analysis_close_time_utc 非法 → blocked；
analysis_reference_time_utc 不可用 → blocked；
DataQualityResult 缺失 → blocked；
DataQualityResult 非 PASS → blocked；
DataQualityResult 覆盖不足 → blocked；
Kline 窗口为空 → blocked；
Kline 数量不足 → blocked；
Kline 不连续 → blocked；
读到未收盘 Kline → blocked；
数据库读取失败 → failed；
数据库写入失败 → failed 或 unknown；
幂等状态不可确认 → unknown；
AlertEvent 写入失败且影响高风险审计 → failed 或 unknown；
未预期异常 → failed。
```

任何异常都不得导致未授权 Kline 进入 FeatureLayer。

## 34. 测试要求

必须测试：

```text
1. MarketSnapshot 不调用 BinanceGateway。
2. MarketSnapshot 不创建 Binance HTTP client。
3. MarketSnapshot 不请求 Binance server time。
4. 采集域不匹配时 blocked。
5. timeframe 不支持时 blocked。
6. analysis_close_time_utc 不在 4h 边界时 blocked。
7. analysis_reference_time_utc 缺失且需要时 blocked。
8. 4h Kline 缺失时 blocked。
9. 1d Kline 缺失时 blocked。
10. 4h DataQualityResult 缺失时 blocked。
11. 1d DataQualityResult 缺失时 blocked。
12. 4h DataQualityResult 非 PASS 时 blocked。
13. 1d DataQualityResult 非 PASS 时 blocked。
14. DataQualityResult.allows_downstream = false 时 blocked。
15. 4h DataQualityResult 覆盖不足时 blocked。
16. 1d DataQualityResult 覆盖不足时 blocked。
17. 短窗口 PASS 不得授权长窗口 MarketSnapshot。
18. Kline 数量不足时 blocked。
19. Kline 不连续时 blocked。
20. 读到未收盘 Kline 时 blocked。
21. 4h 与 1d 必须同时满足才 created。
22. 1d 新鲜度按日线边界独立判断。
23. 相同 business_request_key 重复调用返回同一 created 快照。
24. 并发创建同一快照最终只有一个 created 事实。
25. payload_summary 不保存完整 Kline 数组。
26. payload_summary 不保存逐根 OHLCV 明细。
27. MarketSnapshot 不写 Kline。
28. MarketSnapshot 不创建 DataQualityResult。
29. MarketSnapshot 不创建 BackfillRequest。
30. MarketSnapshot 不触发 DataBackfill。
31. MarketSnapshot created 后 FeatureLayer 才可运行。
32. MarketSnapshot 非 created 时不进入 FeatureLayer。
33. MarketSnapshot 不生成 FeatureValue。
34. MarketSnapshot 不生成 AtomicSignal。
35. MarketSnapshot 不生成 DomainSignal。
36. MarketSnapshot 不生成 MarketRegime。
37. MarketSnapshot 不执行 StrategyRouting。
38. MarketSnapshot 不生成 StrategySignal。
39. MarketSnapshot 不生成 StrategySignalQualityResult。
40. MarketSnapshot 不生成 DecisionSnapshot。
41. MarketSnapshot 不生成 PriceSnapshot。
42. MarketSnapshot 不调用 OrderPlan / RiskCheck / ExecutionPreparation / Execution。
43. blocked / failed / unknown 写必要 AlertEvent。
44. AlertEvent 不包含完整 Kline、完整 Binance 响应或密钥。
45. dry-run 不写 MarketSnapshot、不写正式 AlertEvent、不触发当前主链路下游。
46. 恢复流程必须按 Kline → DataQualityResult → MarketSnapshot 的顺序检查。
47. 默认测试不访问真实 Binance。
```

## 35. 验收标准

MarketSnapshot 验收通过必须满足：

```text
只消费已经落库的 Kline；
只消费 DataQualityResult = PASS 且 allows_downstream = true 的窗口；
同时固定 4h 与 1d 窗口；
4h 与 1d 均按 UTC 周期边界判断；
1d 新鲜度不被 4h 节奏错误替代；
能记录 latest_4h_open_time_utc 与 latest_1d_open_time_utc；
能记录 lookback_count 与 actual_count；
能记录 DataQualityResult 引用；
能记录 trace_id 与 trigger_source；
同一 business_request_key 幂等；
payload_summary 不保存完整 Kline；
不请求 Binance；
不写 Kline；
不触发回补；
不生成特征、信号、决策、订单或风控对象；
blocked / failed / unknown 不放行当前主链路下游；
created 后才允许 FeatureLayer 消费；
必要异常写 AlertEvent；
不直接发送 Hermes；
不调用 DeepSeek；
不涉及交易执行。
```

## 36. 当前不包含的能力

当前不包含：

```text
多采集域同时进入主链路；
多交易所 MarketSnapshot；
多品种组合 MarketSnapshot；
1m / 5m / 15m / 1h 高频分析快照；
WebSocket 实时行情快照；
订单簿快照；
逐笔成交快照；
资金费率快照；
行情可视化；
自动选择最佳数据源；
自动修复 Kline；
自动触发回补；
自动生成策略解释；
自动生成复盘结论；
任何交易执行能力。
```

## 37. 最终结论

MarketSnapshot 的最终定位是：

```text
DataQuality 之后、FeatureLayer 之前的强制市场证据边界。
```

一句话：

```text
只有 MarketSnapshot created，基于该快照的特征、信号、策略质量、目标仓位决策和交易主链路才有资格继续；MarketSnapshot 本身不采集、不回补、不请求 Binance、不定策略、不定订单。
```
