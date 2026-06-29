# OrderStatusSync 需求

## 1. 模块定位

OrderStatusSync 位于订单提交与成交同步之间：

```text
OrderSubmissionAttempt
→ OrderStatusSync
→ OrderStatusSyncRecord
→ FillSync
→ TradeFill / OrderFillSummary
```

本模块只查询一条既有 `OrderSubmissionAttempt` 对应的 Binance 订单状态，并保存独立、可审计的查询事实。

OrderStatusSync 属于独立订单生命周期同步管线，不属于主交易编排在 OrderSubmission 后继续内嵌执行的尾部步骤。

本模块不提交订单，不重试订单提交，不把订单状态当作成交明细，也不单独释放 ActiveLock。

## 2. 核心目标

本模块必须完成：

```text
只处理明确指定的 OrderSubmissionAttempt；
对 accepted 或 unknown 的提交结果进行状态查询；
unknown 时使用提交前冻结的 client_order_id 查询；
通过 BinanceOrderStatusGateway 访问 Binance；
提交后首次等待 2 秒；
每 2 秒执行一个逻辑查询轮次；
立即轮询最长持续 30 秒；
查到明确终态后立即停止后续轮询；
区分 found、not_found、unknown、查询前失败和查询前阻断；
保存 Binance 原始订单状态；
保持原始 OrderSubmissionAttempt.status 不变；
为 unknown 保存后续解析结论；
明确终态后交给 FillSync；
30 秒仍未解决时停止短轮询、保持 ActiveLock 并告警；
支持受控的崩溃恢复补查；
保留查询轮次、Gateway 尝试次数和完整追溯证据。
```

## 3. 不负责事项

本模块不负责：

```text
重新提交订单；
调用 BinanceOrderSubmissionGateway；
生成新的 client_order_id；
修改原 OrderSubmissionAttempt 的提交历史事实；
生成或修改 PreparedOrderIntent；
重新执行 ExecutionPreparation 或 price guard；
重新执行 RiskCheck 或 OrderPlan；
查询逐笔成交；
计算平均成交价、手续费或 realized pnl；
生成 TradeFill 或 OrderFillSummary；
生成或修改 BinancePositionSnapshot；
根据订单状态单独释放 ActiveLock；
撤单、改单或补单；
接入 WebSocket 或 User Data Stream；
读取账户快照代替订单查询；
直接发送 Hermes；
调用大模型。
```

## 4. 与 OrderSubmissionAttempt 的关系

每一条 OrderStatusSyncRecord 必须直接关联一条 `OrderSubmissionAttempt`。

允许关系：

```text
一条 OrderSubmissionAttempt
→ 0 条 OrderStatusSyncRecord：尚未开始查询；
→ 1 条记录：第一轮已得到终态或执行一次恢复补查；
→ 多条记录：2 秒轮询、查询失败后的下一逻辑轮次或恢复补查。
```

禁止只通过以下字段拼接查询链路：

```text
symbol；
exchange_order_id；
client_order_id；
提交时间；
数据库全局最新订单。
```

这些字段属于校验和查询参数，不替代 `order_submission_attempt_id` 外键。

## 5. 正式服务入口

至少提供：

```text
start_order_status_polling(
    order_submission_attempt_id,
    business_request_key,
    trace_id,
    trigger_source,
)

poll_order_status(
    order_submission_attempt_id,
    business_request_key,
    poll_sequence,
    trace_id,
    trigger_source,
)
```

正式 service 必须在每次调用入口内部取得当前 UTC，调用方不得传入或覆盖订单状态判断时间。

测试通过可替换 UTC clock 固定时间，不通过正式 service 参数回拨轮询窗口或恢复窗口。

每次调用取得的当前时间不得早于 OrderSubmissionAttempt.finished_at_utc、已存在的 polling_started_at_utc 或上一轮查询完成时间。出现时间倒退时不得查询 Binance。

调用方只能传入明确的 `order_submission_attempt_id`，不得要求 service 自行查询“最近一笔订单”。

trace_id 来自当前技术调用上下文，只用于 StepRun、OrderStatusSyncRecord、AlertEvent、Gateway 元数据、结构化日志和下游技术交接，不作为业务外键、幂等键或订单归属依据。

正式自动链路缺少 trace_id 时必须在请求 Binance 前记录为 `failed_before_query`，本模块不得自行补造一条与当前编排无关的追踪链。

## 6. 输入资格

正常轮询只接受：

```text
OrderSubmissionAttempt.status = accepted
或
OrderSubmissionAttempt.status = unknown
```

以下状态不得进入订单状态查询：

```text
rejected
blocked_before_submit
failed_before_submit
```

原因：

```text
rejected 已有 Binance 明确未接单证据；
blocked_before_submit 和 failed_before_submit 必须能够证明 request_sent=false；
这三类状态不应通过查询接口重新解释为可能已提交。
```

长时间停留在 `submitting` 的 attempt 必须先由 Execution 恢复规则转为 `unknown` 或形成等价阻断证据，再进入 OrderStatusSync。

## 7. 本轮无提交时的处理

如果本次 Connector 调用没有明确可查询的 OrderSubmissionAttempt：

```text
不请求 Binance；
不查询历史最新订单；
不生成 OrderStatusSyncRecord；
记录普通运行日志；
不写风险告警。
```

其他业务链的历史订单不得因为本次没有订单而被自动选中。

## 8. 查询编号

### 8.1 client_order_id 优先

查询优先使用：

```text
OrderSubmissionAttempt.client_order_id
```

Gateway 将其映射为 Binance 对应的原客户订单编号查询参数。

原因：

```text
client_order_id 在提交前已经生成；
accepted 和 unknown 使用同一稳定编号；
unknown 通常没有 exchange_order_id；
client_order_id 能把丢失的提交响应与交易所订单重新关联。
```

### 8.2 exchange_order_id 备用

只有在 client_order_id 不可用且本地存在经过校验的 `exchange_order_id` 时，才允许使用 exchange_order_id。

如果两个编号都存在，默认仍使用 client_order_id，并校验查询响应中的 exchange_order_id 与本地已知值一致。

如果两个编号都缺失：

```text
不请求 Binance；
query_outcome = failed_before_query；
reason_code = missing_query_identifier；
保持 ActiveLock；
写 AlertEvent。
```

不得临时生成新的 client_order_id。

## 9. Binance Gateway 边界

唯一允许调用：

```text
BinanceOrderStatusGateway.query_order(
    market_type,
    symbol,
    call_context,
    client_order_id=None,
    exchange_order_id=None,
)
```

OrderStatusSync 不得获得：

```text
BinanceTransport；
Fapi adapter；
Dapi adapter；
通用 request 方法；
API secret；
signature；
endpoint path；
BinanceOrderSubmissionGateway；
BinanceFillQueryGateway。
```

Gateway 根据 `market_type` 在内部选择 fapi 或 dapi 查询路径。

## 10. Gateway 调用上下文

至少包括：

```text
trace_id
trigger_source
operation = query_order
market_type
account_domain
symbol
business_object_type = OrderSubmissionAttempt
business_object_id = order_submission_attempt_id
order_submission_attempt_id
client_order_id
exchange_order_id（如有）
poll_sequence
poll_mode
request_time_utc
```

Gateway 返回的 `endpoint_family`、请求时间、完成时间、延迟、attempt_count、限频元数据和脱敏错误必须写入 OrderStatusSyncRecord。

## 11. 市场域校验

OrderStatusSync 必须使用原 OrderSubmissionAttempt 及其绑定的 PreparedOrderIntent 已经冻结的市场身份查询原订单，不读取当前全局市场配置来改写历史订单的查询市场。

必须确认：

```text
OrderSubmissionAttempt.market_type 合法；
OrderSubmissionAttempt.account_domain 与 market_type 一致；
symbol 与原 PreparedOrderIntent 一致；
当前运行实例具备该 market_type 的只读查询能力；
Gateway adapter 与 market_type 一致。
```

部署市场配置发生变化也不得改变既有订单的市场身份。Gateway 必须按订单已经冻结的 market_type 选择查询 adapter；如果当前部署缺少该市场的只读凭据或查询能力，必须在请求前阻断并告警，不得改查另一市场。

### 11.1 自动追踪与交易关闭

已经进入 accepted 或 unknown 的订单必须继续自动查询状态。关闭真实交易运行开关只阻止下一次进入 OrderPlan，不能停止已有订单的 OrderStatusSync。

自动立即轮询和自动崩溃恢复：

```text
不要求真实订单提交权限仍为开启；
继续遵守原订单 market_type、查询编号、30 秒窗口和恢复窗口；
不得因此重新提交、撤单、改单或释放 ActiveLock。
```

## 12. 立即轮询时间规则

默认配置：

```text
ORDER_STATUS_POLL_INTERVAL_SECONDS = 2
ORDER_STATUS_POLL_MAX_DURATION_SECONDS = 30
```

轮询窗口锚点：

```text
polling_started_at_utc
= OrderSubmissionAttempt 提交结果成功持久化的 finished_at_utc

polling_deadline_utc
= polling_started_at_utc + 30 秒
```

OrderSubmissionAttempt 缺少可信 finished_at_utc 时不得自行猜测轮询起点。

规则：

```text
订单提交结果持久化后等待 2 秒执行第一轮；
第一轮计划时间为 polling_started_at_utc + 2 秒；
后续每隔 2 秒执行一个逻辑轮次；
计划轮次依次位于第 2、4、6……30 秒；
第 30 秒计划的第 15 轮允许执行；
只有实际开始时间小于或等于 polling_deadline_utc 的轮次才允许请求 Binance；
某轮任务延迟到 polling_deadline_utc 之后才开始时，不补做该轮；
正常无延迟情况下最多 15 个逻辑轮次，任务延迟或单轮耗时过长时可以少于 15 轮；
同一 OrderSubmissionAttempt 不允许并发查询；
前一轮未完成时不得启动重叠轮次；
查到明确终态后不再创建下一轮；
第 15 轮完成后仍无明确终态，立即进入 polling_timeout；
当前时间已经大于 polling_deadline_utc 时，不再创建新的立即轮询轮次。
```

时间计算统一使用 UTC，不使用服务器本地时区。

如果某轮 Gateway 请求耗时超过 2 秒，下一轮只能在本轮完成后调度，不得为了追赶时间并发补发请求。第 30 秒或更早开始的最后一轮可以在 deadline 之后完成，但完成后不得再创建新轮次。

## 13. 逻辑轮询与 Gateway 技术重试

每个 2 秒轮次只允许调用一次 `BinanceOrderStatusGateway.query_order`。

Gateway 可以对这一只读查询中的允许技术异常执行有限重试。两者含义不同：

```text
poll_sequence：业务层第几个 2 秒查询轮次；
gateway_attempt_count：该逻辑轮次内部实际进行了几次安全读取尝试。
```

要求：

```text
每个轮次保存 gateway_attempt_count；
Gateway 技术重试不得突破 polling_deadline_utc 后继续无界运行；
业务层不得自行实现 HTTP 重试循环；
Celery task 不通过 autoretry 重复同一 poll_sequence；
查询失败后只能由下一计划轮次继续；
订单提交接口在任何情况下都不会因此被再次调用。
```

## 14. OrderStatusSyncRecord

每一次实际查询都必须生成独立记录。

至少包含：

```text
id
order_status_sync_key
order_submission_attempt_id
prepared_order_intent_id
order_plan_id
business_request_key
active_lock_id
exchange
market_type
account_domain
endpoint_family
symbol
query_identifier_type
client_order_id
exchange_order_id_requested
poll_mode
poll_sequence
polling_started_at_utc
polling_deadline_utc
scheduled_at_utc
query_started_at_utc
query_finished_at_utc
query_outcome
reason_code
reason_message
request_sent
response_received
gateway_attempt_count
gateway_latency_ms
http_status
binance_error_code
sanitized_error_message
exchange_order_id_returned
exchange_client_order_id_returned
exchange_status
exchange_status_observed_at_utc
is_recognized_status
is_terminal_status
terminal_policy_version
submission_resolution_status
sanitized_response
response_hash
rate_limit_metadata
trace_id
trigger_source
alert_event_ids
created_at_utc
```

禁止保存 API secret、signature、完整 API key 或认证 header。

## 15. 幂等与并发

唯一约束至少包括：

```text
order_status_sync_key unique
(order_submission_attempt_id, poll_mode, poll_sequence) unique
```

每轮查询前必须：

```text
在数据库事务中 select_for_update 锁定 OrderSubmissionAttempt；
读取最新 OrderStatusSyncRecord；
确认尚未检测到终态；
确认当前 poll_sequence 尚未被执行或占用；
确认未超过 polling_deadline_utc；
创建该轮查询占位记录；
提交事务后再调用 Gateway。
```

同一 poll_sequence 重复投递时返回已有记录，不重复请求 Binance。

不得在持有数据库长事务或行锁时等待 Binance 网络响应。

## 16. 查询结果分类

`query_outcome` 只允许：

```text
found
not_found
unknown
failed_before_query
blocked_before_query
```

含义：

```text
found：成功取得目标订单并通过身份校验；
not_found：Binance 明确回复该目标订单未找到；
unknown：查询已经发出或无法判断，但没有得到可信结论；
failed_before_query：确认请求未发送，发生本地或 Gateway 前置失败；
blocked_before_query：业务安全规则在请求前阻断。
```

`skipped_no_submission` 只作为编排运行结果或普通日志，不创建虚假的 OrderStatusSyncRecord。

`polling_timeout` 和 `recovery_skipped_out_of_window` 属于轮询或恢复汇总结果，不伪装成某一次 Binance 查询结果。

## 17. found 的严格条件

必须同时满足：

```text
Gateway 请求成功；
response_received = true；
响应包含可识别订单对象；
symbol 与目标订单一致；
market_type 与目标订单一致；
返回 client_order_id 时与目标 client_order_id 一致；
返回 exchange_order_id 时与本地已知值不冲突；
status 字段存在且可解析；
响应结构通过校验。
```

身份不一致或响应结构损坏不能记为 found，必须记为 `unknown` 或 `failed_before_query`，并保持 ActiveLock。

## 18. not_found 的严格条件

只有 Binance 对本次单笔订单查询返回明确的“目标订单不存在”业务语义时，才可以记录：

```text
query_outcome = not_found
```

以下情况不得记为 not_found：

```text
当前挂单列表没有该订单；
查询超时；
网络错误；
HTTP 5xx；
HTTP 429 或 418；
认证或权限错误；
本地缺少查询编号；
响应结构损坏；
symbol 或市场域不一致。
```

not_found 只描述本次查询结果，不证明原订单提交失败。

即使连续 30 秒均为 not_found，也不得：

```text
把 OrderSubmissionAttempt.unknown 改成 rejected；
认定 request_sent=false；
重新提交订单；
生成新的 PreparedOrderIntent；
释放 ActiveLock；
允许新的编排运行绕过锁。
```

## 19. unknown 查询结果

以下任一情况记录为：

```text
query_outcome = unknown
```

典型情况：

```text
查询请求发出后 read timeout；
无法判断查询请求是否发出；
网络中断；
Binance 5xx 且无可信订单状态；
Gateway 耗尽安全读取尝试；
响应身份不一致；
响应结构无法验证；
返回未识别的订单状态；
其他无法形成可靠结论的情况。
```

查询 unknown 不得影响原订单提交的确定性，也不得触发重新下单或解锁。

## 20. Binance 原始状态

成功 found 时必须原样保存 Binance `status` 字段。

当前识别状态：

```text
NEW
PARTIALLY_FILLED
FILLED
CANCELED
REJECTED
EXPIRED
EXPIRED_IN_MATCH
```

不得把 Binance 原始状态翻译后覆盖原值。中文解释可以另存展示字段。

## 21. 终态白名单

终态集合固定为：

```text
FILLED
CANCELED
REJECTED
EXPIRED
EXPIRED_IN_MATCH
```

非终态集合固定为：

```text
NEW
PARTIALLY_FILLED
```

终态判断不是 env 可随意修改的交易参数，而是 Binance 订单协议映射。实现必须记录：

```text
terminal_policy_version
```

协议状态发生变化时，必须更新映射、测试和需求，不得在运行时临时把未知状态加入终态集合。

## 22. 明确终态的判断条件

只有同时满足以下条件，才可以设置：

```text
is_terminal_status = true
```

条件：

```text
query_outcome = found；
订单身份校验通过；
exchange_status 字段存在；
exchange_status 属于终态白名单；
本轮 OrderStatusSyncRecord 已成功持久化。
```

不得仅依据：

```text
市价单通常立即成交；
executedQty 看起来等于 quantity；
提交响应曾返回 FILLED；
账户持仓发生变化；
当前挂单列表没有订单；
连续多次 not_found；
人工推测。
```

## 23. 查到终态后的处理

查到明确终态后必须按顺序完成：

```text
保存本轮 OrderStatusSyncRecord；
记录 is_terminal_status=true；
保存原始 exchange_status；
停止创建后续立即轮询轮次；
写订单状态变化 AlertEvent；
创建或发送 FillSync 受控交接事件；
保持 ActiveLock，不在本模块释放。
```

即使终态是 `FILLED`，也不能直接释放 ActiveLock，因为成交明细、手续费和完整性尚未由 FillSync 确认。

即使终态是 `CANCELED / REJECTED / EXPIRED / EXPIRED_IN_MATCH`，也必须交给 FillSync 确认是否存在部分成交或 `synced_empty`。

## 24. 非终态处理

### 24.1 NEW

```text
保存状态；
is_terminal_status=false；
保持 ActiveLock；
在 polling_deadline_utc 前调度下一轮。
```

### 24.2 PARTIALLY_FILLED

```text
保存状态；
is_terminal_status=false；
保持 ActiveLock；
写订单部分成交 AlertEvent；
在 polling_deadline_utc 前调度下一轮。
```

OrderStatusSync 不在此时计算成交汇总，也不因市价单部分成交而假设剩余数量会立即完成。

对于 LIMIT 订单，`NEW` 表示交易所仍可能保留挂单，`PARTIALLY_FILLED` 表示订单仍可能继续成交。二者都不是失败，也不是允许解锁的证据。

如果 LIMIT 订单在 30 秒立即轮询窗口结束时仍为 `NEW` 或 `PARTIALLY_FILLED`，OrderStatusSync 只保存当前状态并保持 ActiveLock。到达该订单冻结的 `limit_valid_until_utc` 后，应由 OrderCycleCloseout 执行受控周期收尾；OrderStatusSync 自身不得撤单。

## 25. 未识别状态

如果 Binance 返回不在已识别集合中的状态：

```text
保留 raw status；
is_recognized_status=false；
is_terminal_status=false；
query_outcome=unknown；
保持 ActiveLock；
写 critical AlertEvent；
在 30 秒窗口内允许下一逻辑轮次；
不得自行推断终态。
```

## 26. unknown 提交的解析

原始提交事实必须保持：

```text
OrderSubmissionAttempt.status = unknown
```

OrderStatusSync 不得把历史提交响应改写成 accepted、rejected 或 failed_before_submit。

通过 OrderStatusSyncRecord 另外保存：

```text
submission_resolution_status
```

允许值：

```text
unresolved
order_found
terminal_confirmed
```

自动规则：

```text
not_found / query unknown
→ unresolved

found + NEW / PARTIALLY_FILLED
→ order_found

found + 终态
→ terminal_confirmed
```

## 27. 30 秒超时

满足以下条件时，立即轮询结束为：

```text
polling_timeout
```

条件：

```text
尚无 is_terminal_status=true 的记录；
不存在仍在执行中的已占用轮次；
并且满足以下任一条件：
  第 15 轮已经完成但仍无明确终态；
  当前 UTC 时间已经晚于 polling_deadline_utc，且没有在 deadline 前合法开始的轮次仍待完成。
```

当前时间恰好等于 polling_deadline_utc 时，如果存在下一合法轮次且其前置轮次均已完成，仍允许这一轮开始；不能在查询前抢先判定超时，也不能一次补发多个错过的轮次。

处理：

```text
不再调度新的 2 秒轮次；
保留最后一次 found / not_found / unknown 证据；
保持 OrderSubmissionAttempt 原状态；
保持 ActiveLock；
写 high / critical AlertEvent；
等待 RuntimeGuard 按巡检阈值创建问题，或由授权入口进入受控后续对账；
不得重新提交订单。
```

如果最后状态是 NEW 或 PARTIALLY_FILLED，订单可能仍在交易所活动；如果最后结果是 not_found 或 unknown，订单是否存在仍未解决。两类情况都不能自动解锁。

对于 LIMIT 订单，`NEW / PARTIALLY_FILLED` 持续到 30 秒窗口结束属于“订单仍未终态”的正常可能结果，不得写成提交失败、成交失败或策略失败。后续是否到期撤单由 OrderCycleCloseout 按冻结有效期处理。

## 28. 崩溃恢复补查

默认恢复窗口：

```text
ORDER_STATUS_RECOVERY_WINDOW_SECONDS = 86400
```

恢复对象必须满足：

```text
有明确 OrderSubmissionAttempt；
status = accepted 或 unknown；
缺少应有状态查询记录，或立即轮询在进程中断时未正常收尾；
距离提交时间不超过 24 小时；
仍可追溯 client_order_id 或 exchange_order_id；
ActiveLock 尚未安全释放。
```

恢复规则：

```text
必须按明确 order_submission_attempt_id 补查；
不得查询数据库全局最新订单；
不得扫描全历史订单；
不得重新开启一个新的 30 秒立即轮询窗口；
每次恢复任务只执行一个幂等 recovery 查询轮次；
found 时按正常状态和终态规则处理；
not_found / unknown 时继续保持锁定并告警；
不得重新提交订单。
```

超过 24 小时：

```text
不自动请求 Binance；
记录 recovery_skipped_out_of_window；
写 high / critical AlertEvent；
进入人工诊断或专用对账流程；
不得自动释放 ActiveLock。
```

24 小时恢复窗口只用于崩溃后补查，不表示持续轮询 24 小时。

## 29. ActiveLock 边界

OrderStatusSync 不得单独释放 ActiveLock。

固定规则：

```text
NEW → 不释放；
PARTIALLY_FILLED → 不释放；
not_found → 不释放；
query unknown → 不释放；
未识别状态 → 不释放；
polling_timeout → 不释放；
found terminal → 本模块仍不释放，只交给 FillSync。
```

只有后续同时具备以下证据，统一 OrderPlanActiveLockService 才能释放：

```text
OrderStatusSync 已确认明确终态；
FillSync 已完成成交查询；
所有 TradeFill 已幂等落库；
OrderFillSummary 已生成并通过完整性校验；
无成交终态已明确记录 synced_empty；
状态和成交证据属于同一 OrderSubmissionAttempt。
```

## 30. FillSync 交接

只有 found 且终态明确时，OrderStatusSync 才创建正式 FillSync 交接。

交接信息至少包括：

```text
order_submission_attempt_id
terminal_order_status_sync_record_id
market_type
account_domain
symbol
client_order_id
exchange_order_id
exchange_status
trace_id
trigger_source
```

交接必须幂等，同一终态记录只能触发一条有效 FillSync 工作项或等价事件。

OrderStatusSync 不得调用 `BinanceFillQueryGateway`。

## 31. 状态变化与重复状态

每轮查询都保存独立记录，但 AlertEvent 应区分状态变化与重复观察：

```text
首次观察到 NEW → 写状态事件；
NEW 再次观察为 NEW → 保存记录，可只写普通审计日志；
NEW → PARTIALLY_FILLED → 写状态变化事件；
PARTIALLY_FILLED 重复 → 保存记录，可只写普通审计日志；
任意非终态 → 终态 → 写终态事件并交接 FillSync。
```

不得让更低确定性的后续结果覆盖已确认终态。

一旦存在 `is_terminal_status=true` 的有效记录，后续重复任务不得再次请求 Binance。

## 32. reason_code

至少支持：

```text
order_submission_attempt_not_found
order_submission_attempt_not_queryable
missing_query_identifier
source_chain_mismatch
sync_time_before_source_fact
trace_context_missing
unsupported_market_type
gateway_disabled
query_found
query_not_found
query_unknown
query_failed_before_send
query_blocked_before_send
response_identity_mismatch
response_schema_invalid
unsupported_exchange_status
order_status_new
order_status_partially_filled
order_status_filled
order_status_canceled
order_status_rejected
order_status_expired
order_status_expired_in_match
polling_timeout
polling_already_terminal
duplicate_poll_sequence
recovery_query_completed
recovery_skipped_out_of_window
internal_error
```

reason_code 必须稳定，中文说明写入 reason_message 和 AlertEvent。

## 33. AlertEvent

至少包括：

```text
order_status_sync_started
order_status_found
order_status_not_found
order_status_query_unknown
order_status_query_failed
order_status_query_blocked
order_status_new
order_status_partially_filled
order_status_filled
order_status_canceled
order_status_rejected
order_status_expired
order_status_expired_in_match
order_status_polling_timeout
order_status_unknown_submission_resolved
order_status_recovery_completed
order_status_recovery_skipped
order_status_fill_sync_requested
```

最低字段：

```text
source_module = order_status_sync
trace_id
trigger_source
event_type
severity
reason_code
order_submission_attempt_id
order_status_sync_record_id
active_lock_id
market_type
account_domain
endpoint_family
symbol
client_order_id
exchange_order_id
poll_mode
poll_sequence
query_outcome
exchange_status
is_terminal_status
submission_resolution_status
gateway_attempt_count
polling_deadline_utc
```

通知必须明确这是订单状态查询，不得把 `found` 写成新订单提交，也不得把 `FILLED` 写成成交明细已经同步完成。

## 34. 日志与敏感信息

结构化日志至少包含：

```text
trace_id
order_submission_attempt_id
order_status_sync_record_id
client_order_id
market_type
endpoint_family
poll_mode
poll_sequence
query_outcome
exchange_status
is_terminal_status
gateway_attempt_count
latency_ms
```

不得记录：

```text
API secret；
signature；
完整 API key；
完整认证 header；
含敏感参数的完整请求 URL。
```

## 35. 配置

配置必须进入 `.env.example` 并带中文注释：

```text
ORDER_STATUS_SYNC_ENABLED
ORDER_STATUS_POLL_INTERVAL_SECONDS=2
ORDER_STATUS_POLL_MAX_DURATION_SECONDS=30
ORDER_STATUS_RECOVERY_WINDOW_SECONDS=86400
```

约束：

```text
轮询间隔必须大于零；
最大轮询时长必须大于等于轮询间隔；
默认配置最多形成 15 个逻辑轮次；
轮询起点固定为订单提交结果成功持久化时间；
第 30 秒允许开始最后一个合法轮次，超过第 30 秒不补做错过轮次；
恢复窗口不得被解释为 ActiveLock 自动过期时间；
Gateway 超时、技术重试、限频和熔断配置统一由 Binance Gateway 管理；
终态集合不通过 env 热修改。
```

## 36. Celery 与编排

PipelineOrchestrator 或 Execution 后续编排负责启动第一轮查询。

Celery Beat 不得每 2 秒扫描数据库全表。应按明确 attempt 创建受控任务链或使用等价的定时调度记录。

Celery task 只能：

```text
解析 order_submission_attempt_id 和 poll_sequence；
传递当前 OrchestrationRun / StepRun 已建立的 trace_id；
设置 trigger_source；
调用 OrderStatusSync service；
根据 service 返回结果决定是否登记下一轮；
输出结构化摘要。
```

task 不得：

```text
直接调用 Binance；
直接判断终态；
直接更新 ActiveLock；
自动重试同一 poll_sequence；
触发订单重新提交。
```
自动轮询的后续 task 沿用当前技术追踪上下文。

## 37. 数据与外部服务

```text
读写 MySQL：是，保存每轮 OrderStatusSyncRecord；
直接访问 Redis：非必要，不作为订单状态事实来源；
访问 Binance：是，只通过 BinanceOrderStatusGateway；
访问订单提交接口：否；
访问成交查询接口：否；
发送 Hermes：否，只写 AlertEvent；
调用大模型：否；
涉及真实交易：查询既有真实订单，不创建新订单；
涉及 PriceSnapshot：否；
涉及 Binance Account Sync：否；
涉及 OrderPlan / RiskCheck / ExecutionPreparation：只保留追溯；
涉及 FillSync：是，只向 FillSync 提供明确终态订单状态事实；
写 AlertEvent：是。
```

## 38. 异常处理

分类原则：

```text
请求成功且身份、结构、状态有效 → found；
Binance 明确回复目标订单不存在 → not_found；
查询已发出但结果不可信 → unknown；
能够证明查询未发送的系统失败 → failed_before_query；
业务安全条件阻断 → blocked_before_query。
```

禁止：

```text
把超时映射为 not_found；
把 not_found 映射为提交失败；
把查询 unknown 映射为订单不存在；
把未知 exchange_status 映射为终态；
查询失败时回退到账户持仓推测订单状态；
任何异常后重新提交订单；
30 秒超时后自动释放 ActiveLock。
```

## 39. 测试要求

自动化测试必须使用 fake Gateway，不得访问真实 Binance。

至少覆盖：

```text
1. accepted attempt 可以进入状态查询。
2. unknown attempt 可以进入状态查询。
3. rejected attempt 不查询。
4. blocked_before_submit 不查询。
5. failed_before_submit 不查询。
6. 本轮无提交时不查询历史订单。
7. 查询必须直接关联 OrderSubmissionAttempt。
8. unknown 使用原 client_order_id 查询。
9. client_order_id 缺失但 exchange_order_id 有效时使用后者。
10. 两种编号都缺失时 failed_before_query。
11. USDS-M 选择 Gateway 内部 fapi adapter。
12. COIN-M 选择 Gateway 内部 dapi adapter。
13. 业务模块不能访问 endpoint、adapter 或 transport。
14. 原订单冻结市场身份不一致或当前部署不具备对应查询能力时不查询。
15. 提交后 2 秒才执行第一轮。
16. 每 2 秒最多一个逻辑轮次。
17. 30 秒窗口最多 15 轮。
18. 前一轮未完成时不并发下一轮。
19. 每轮 Gateway 技术 attempt_count 被记录。
20. Celery 重复投递同一 sequence 不重复查询。
21. found 必须通过订单身份校验。
22. client_order_id 不一致不能记为 found。
23. exchange_order_id 冲突不能记为 found。
24. 明确订单不存在才记录 not_found。
25. 挂单列表缺失不能记录 not_found。
26. 查询超时记录 unknown，不记录 not_found。
27. 网络错误、5xx 和限频不记录 not_found。
28. not_found 不改变 OrderSubmissionAttempt.unknown。
29. 连续 30 秒 not_found 不重新下单、不解锁。
30. NEW 被识别为非终态并继续查询。
31. PARTIALLY_FILLED 被识别为非终态并继续查询。
32. PARTIALLY_FILLED 写 AlertEvent 但不生成成交汇总。
33. FILLED 被识别为终态并停止查询。
34. CANCELED 被识别为终态并停止查询。
35. REJECTED 被识别为终态并停止查询。
36. EXPIRED 被识别为终态并停止查询。
37. EXPIRED_IN_MATCH 被识别为终态并停止查询。
38. 未识别 exchange_status 不被当作终态。
39. 只有 found、身份一致、白名单状态和记录落库后才能确认终态。
40. 提交响应中的 FILLED 不替代本模块查询证据。
41. 查到订单后 unknown 的 resolution 变为 order_found。
42. 查到终态后 resolution 变为 terminal_confirmed。
43. OrderSubmissionAttempt.status=unknown 保持不变。
44. 终态后不创建下一轮。
45. 终态后幂等触发一次 FillSync 交接。
46. OrderStatusSync 不调用 Fill Gateway。
47. FILLED 后本模块不释放 ActiveLock。
48. CANCELED / REJECTED / EXPIRED 后仍等待 FillSync。
49. 30 秒仍为 NEW 时 polling_timeout 且不解锁。
50. 30 秒仍为 PARTIALLY_FILLED 时 polling_timeout 且不解锁。
51. 30 秒仍为 unknown 时 polling_timeout 且不解锁。
52. 恢复窗口内可以对明确 attempt 执行单次 recovery 查询。
53. recovery 不重置新的 30 秒窗口。
54. 超过 24 小时不自动查询且不解锁。
55. 不扫描数据库全局最新或全历史订单。
56. 不调用订单提交 Gateway。
57. 不生成新 client_order_id。
58. 不重新提交订单。
59. 不创建 TradeFill，也不生成或修改 BinancePositionSnapshot。
60. 所有关键状态变化写 AlertEvent。
61. 日志、记录和告警不包含密钥或签名。
62. polling_started_at_utc 等于提交结果成功持久化时间。
63. 当前时间恰好等于第 30 秒时允许一个下一合法轮次开始，完成后无终态则 polling_timeout。
64. 轮次在第 30 秒以后才开始时不请求 Binance，也不补发错过轮次。
65. 单轮耗时过长时实际轮次可以少于 15，不能并发追赶。
66. 正式 service 不接受调用方传入判断时间，时间早于既有事实时不查询。
67. 自动交易或新订单提交关闭后，accepted / unknown 订单仍继续自动状态追踪。
68. 当前部署不具备原订单市场的只读查询能力时 blocked_before_query，并保持 ActiveLock。
69. 自动 Celery task 只传递已有 trace_id。
70. 正式自动链路缺少 trace_id 时 failed_before_query，且不请求 Binance。
```

## 40. 验收标准

满足以下条件才算完成：

```text
OrderStatusSync 只查询明确 OrderSubmissionAttempt；
accepted 和 unknown 均可按原 client_order_id 查询；
所有 Binance 查询统一经过 BinanceOrderStatusGateway；
首次等待 2 秒，每 2 秒一个逻辑轮次，立即轮询不超过 30 秒；
第 30 秒可以执行最后一个合法轮次，完成后仍无终态才进入超时；
业务轮次与 Gateway 技术重试能够分开审计；
found、not_found、unknown 和查询前结果边界明确；
not_found 永远不自动解释为提交失败；
OrderSubmissionAttempt 的原始 unknown 历史不会被覆盖；
终态只依据成功查询、身份一致和固定白名单判断；
NEW 与 PARTIALLY_FILLED 不终结；
FILLED、CANCELED、REJECTED、EXPIRED、EXPIRED_IN_MATCH 终结轮询；
未知状态 fail-closed，不被推断为终态；
终态记录落库后才停止下一轮并交接 FillSync；
OrderStatusSync 不查询成交、不更新持仓、不单独释放 ActiveLock；
30 秒未解决时保持锁定并进入告警或对账；
24 小时窗口只用于崩溃恢复查询，不重启完整轮询；
关闭新交易不会停止 accepted / unknown 订单的自动状态追踪；
生产判断时间由 service 内部取得，调用方不能回拨轮询或恢复窗口；
trace_id 只用于查询技术追踪，不作为订单业务外键或幂等键；
任何状态查询结果都不会触发订单重新提交；
所有查询记录可追溯、可审计且不泄露敏感信息。
```

## 41. 当前不包含的能力

```text
订单重新提交；
撤单或改单；
长期挂单管理；
持续无限轮询；
WebSocket User Data Stream；
成交明细同步；
手续费与 realized pnl 同步；
BinancePositionSnapshot 生成或修改；
单独依据订单状态释放 ActiveLock；
自动把 not_found 认定为提交失败；
自动将 unknown 订单改判为不存在；
多 active domain 并行查询；
全历史订单扫描；
大模型判断订单状态。
```
