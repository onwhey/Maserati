# FillSync 需求

## 1. 模块定位

FillSync 位于订单终态确认之后，负责把 Binance 逐笔成交事实落库并生成订单级成交汇总：

```text
OrderSubmissionAttempt
→ terminal OrderStatusSyncRecord
→ FillSyncResult
→ TradeFill
→ OrderFillSummary
→ OrderPlanActiveLockService
→ ActiveLock 安全收尾判断
```

FillSync 是交易所成交事实的正式入口，但不是订单提交模块、订单状态查询模块或持仓更新模块。

FillSync 属于独立订单生命周期同步管线，不属于主交易编排在 OrderSubmission 后继续内嵌执行的尾部步骤。

## 2. 核心目标

本模块必须完成：

```text
只消费 OrderStatusSync 已确认的明确订单终态；
通过 BinanceFillQueryGateway 查询目标订单全部成交；
支持 USDS-M 与 COIN-M；
逐条保存不可变 TradeFill；
按交易所成交身份幂等去重；
生成一条 OrderFillSummary；
按市场域使用正确的数量与金额口径；
按手续费资产分别汇总；
验证分页完整性；
验证成交数量与终态 executed_quantity 一致；
严格区分 synced、synced_empty、incomplete 和 unknown；
只有状态与成交证据完整时才调用 OrderPlanActiveLockService 安全收尾；
保存查询、计算、完整性和锁收尾证据；
为 OpsConsole 和 ReviewDataset 提供已落库成交事实。
```

## 3. 不负责事项

本模块不负责：

```text
提交或重新提交订单；
查询订单状态；
生成新的 client_order_id；
修改 OrderSubmissionAttempt 的历史提交结果；
重新执行 ExecutionPreparation、RiskCheck 或 OrderPlan；
重新查询 mark price 或盘口价格；
补单、缩单、撤单或改单；
根据成交结果重新设计订单；
修改杠杆、保证金模式或持仓模式；
更新 BinanceAccountSnapshot；
生成或修改 BinancePositionSnapshot；
把账户持仓变化当作逐笔成交；
直接修改 OrderPlanActiveLock 表；
接入 WebSocket 或 User Data Stream；
直接发送 Hermes；
调用大模型。
```

## 4. 正式输入

正式入口：

```text
sync_order_fills(
    order_submission_attempt_id,
    terminal_order_status_sync_record_id,
    business_request_key,
    trace_id,
    trigger_source,
)
```

要求：

```text
正式 service 在入口内部取得当前 UTC，调用方不得传入或覆盖成交同步判断时间；
测试通过可替换 UTC clock 固定时间，不通过正式 service 参数回拨恢复窗口；
必须显式传入 OrderSubmissionAttempt；
必须显式传入确认终态的 OrderStatusSyncRecord；
不得要求 service 自行选择数据库最新订单；
自动链路的 trace_id 必须来自当前 OrchestrationRun / StepRun 技术上下文；
trigger_source 必须可审计。
```

当前时间不得早于终态 OrderStatusSyncRecord 的确认时间、OrderSubmissionAttempt.finished_at_utc 或已有 FillSyncResult 的完成时间。出现时间倒退时不得查询 Binance。

trace_id 只用于 StepRun、FillSyncResult、AlertEvent、Gateway 元数据、结构化日志和下游技术交接，不作为 TradeFill、OrderFillSummary 的业务字段，也不参与业务外键或幂等。

正式自动链路缺少 trace_id 时必须在请求 Binance 前记录为 `failed_before_query`，本模块不得自行补造与当前编排无关的追踪链。

## 5. 上游资格

必须满足：

```text
OrderSubmissionAttempt 存在；
OrderStatusSyncRecord 存在；
OrderStatusSyncRecord.order_submission_attempt_id 等于输入 attempt；
OrderStatusSyncRecord.query_outcome = found；
OrderStatusSyncRecord.is_terminal_status = true；
exchange_status 属于终态白名单；
订单身份校验已通过；
exchange_order_id 存在且可验证；
market_type、account_domain、symbol 一致；
ActiveLock 仍属于当前 OrderPlan，或处于允许收尾的 failed 阻断状态。
```

终态白名单：

```text
FILLED
CANCELED
REJECTED
EXPIRED
EXPIRED_IN_MATCH
```

以下任何情况不得进入正式成交同步：

```text
NEW；
PARTIALLY_FILLED；
OrderStatusSync not_found；
OrderStatusSync unknown；
OrderStatusSync failed_before_query；
OrderStatusSync blocked_before_query；
未识别 exchange_status；
仅凭 OrderSubmissionAttempt 提交响应推测终态。
```

## 6. 本轮无终态订单时的处理

如果没有符合条件的终态 OrderStatusSyncRecord：

```text
不请求 Binance；
不查询数据库历史最新订单；
不生成 TradeFill；
不生成可用 OrderFillSummary；
不调用 OrderPlanActiveLockService 释放锁；
记录 skipped_no_terminal_order_status 或对应上游异常。
```

其他业务链的订单不得被当前流程自动选中。

## 7. Binance Gateway 边界

唯一允许调用：

```text
BinanceFillQueryGateway.query_order_fills(
    market_type,
    symbol,
    exchange_order_id,
    call_context,
    page_cursor=None,
    page_size=None,
)
```

FillSync 不得获得：

```text
BinanceTransport；
Fapi adapter；
Dapi adapter；
通用 request 方法；
API secret；
signature；
endpoint path；
BinanceOrderSubmissionGateway；
BinanceOrderStatusGateway。
```

Gateway 根据 `market_type` 在内部选择 fapi 或 dapi 成交查询路径。

## 8. Gateway 调用上下文

至少包括：

```text
trace_id
trigger_source
operation = query_order_fills
market_type
account_domain
symbol
business_object_type = OrderSubmissionAttempt
business_object_id = order_submission_attempt_id
order_submission_attempt_id
terminal_order_status_sync_record_id
fill_sync_result_id
exchange_order_id
page_sequence
page_cursor
page_size
request_time_utc
```

每一页查询都必须记录 Gateway 返回的 endpoint family、时间、延迟、attempt_count、分页元数据、限频元数据和脱敏错误。

## 9. 市场域

支持：

```text
usds_m_futures
coin_m_futures
```

FillSync 必须使用原 OrderSubmissionAttempt、终态 OrderStatusSyncRecord 及其上游订单链已经冻结的市场身份查询成交，不读取当前全局市场配置来改写历史订单的查询市场。

必须确认：

```text
OrderSubmissionAttempt.market_type 合法；
account_domain 与 market_type 一致；
终态 OrderStatusSyncRecord 市场身份一致；
symbol 一致；
运行实例具备该市场域的成交只读能力；
Gateway endpoint_family 与 market_type 一致。
```

部署市场配置发生变化也不得改变既有订单的市场身份。Gateway 必须按订单已经冻结的 market_type 选择成交查询 adapter；如果当前部署缺少该市场的只读凭据或查询能力，必须在请求前阻断并告警，不得改查另一市场。

### 9.1 自动成交同步与交易关闭

已经取得明确订单终态后，自动 FillSync 必须继续完成成交查询和 ActiveLock 收尾。关闭真实交易运行开关只阻止下一次进入 OrderPlan，不能停止既有订单的自动成交同步。

自动正常同步和自动恢复：

```text
不要求真实订单提交权限仍为开启；
继续遵守原订单 market_type、终态证据和恢复窗口；
不得因此重新提交、补单、撤单或修改订单。
```

## 10. 查询编号

成交查询必须使用经过终态查询验证的：

```text
exchange_order_id
```

exchange_order_id 可以来自：

```text
OrderSubmissionAttempt accepted 响应；
OrderStatusSync 使用 client_order_id 找回的订单响应。
```

如果缺少 exchange_order_id：

```text
不按 symbol + 时间窗口宽泛查询；
不尝试混入其他订单成交；
FillSyncResult.status = failed_before_query；
reason_code = missing_exchange_order_id；
保持 ActiveLock；
写 AlertEvent。
```

## 11. 分页与完整查询

一笔订单可能包含多笔成交。FillSync 必须查询该 `exchange_order_id` 的全部成交页。

每页 Gateway 结果必须提供：

```text
fills
page_cursor
next_page_cursor
pagination_complete
```

规则：

```text
page_sequence 从 1 开始；
下一页必须使用上一页返回的 next_page_cursor；
同一 cursor 不得循环；
没有明确 pagination_complete=true 时不得认为查询完整；
达到配置页数上限仍有下一页时标记 incomplete；
任一页 unknown 时整体不得标记 synced；
已经落库的前序页 TradeFill 保留并依靠幂等在恢复时复用；
分页失败不得删除已确认的 TradeFill。
```

默认配置必须设置保守页数和单页上限，但不得静默截断结果。

## 12. Gateway 技术重试与业务补同步

成交查询是安全读取。

Gateway 可以对单页查询的允许技术异常执行有限重试。FillSync 必须分别记录：

```text
sync_sequence：第几次业务同步或恢复执行；
page_sequence：本次同步的第几页；
gateway_attempt_count：该页内部安全读取尝试次数。
```

Gateway 耗尽尝试后：

```text
本次 FillSyncResult.status = unknown；
保持 ActiveLock；
允许后续受控恢复补同步；
不得触发订单重新提交。
```

业务补同步是对既有订单进行幂等读取，不是订单提交重试。

## 13. FillSyncResult

每次正式同步或恢复执行都必须生成一条 `FillSyncResult`。

至少记录：

```text
id
fill_sync_result_key
sync_sequence
sync_mode
status
reason_code
reason_message
order_submission_attempt_id
terminal_order_status_sync_record_id
prepared_order_intent_id
order_plan_id
business_request_key
active_lock_id
exchange
market_type
account_domain
endpoint_family
symbol
client_order_id
exchange_order_id
terminal_exchange_status
terminal_executed_quantity
terminal_cumulative_quote_quantity
page_count
pagination_complete
gateway_attempt_count_total
returned_fill_count
inserted_fill_count
duplicate_fill_count
conflict_fill_count
sync_started_at_utc
sync_finished_at_utc
config_snapshot
input_hash
evidence
trace_id
trigger_source
alert_event_ids
created_at_utc
updated_at_utc
```

`sync_mode`：

```text
normal
recovery
```

## 14. FillSyncResult 状态

正式状态：

```text
syncing
synced
synced_empty
incomplete
unknown
failed_before_query
blocked_before_query
recovery_skipped_out_of_window
```

含义：

```text
syncing：同步已开始；
synced：查询完整、存在成交、全部成交幂等落库且完整性校验通过；
synced_empty：查询完整、返回零成交，且终态 executed_quantity 明确为零；
incomplete：查询取得部分事实，但分页、数量、身份或汇总完整性不足；
unknown：查询结果无法形成可信结论；
failed_before_query：能够证明查询未发出且发生系统失败；
blocked_before_query：业务安全条件阻断；
recovery_skipped_out_of_window：超过自动恢复窗口，未请求 Binance。
```

只有 `synced` 和严格成立的 `synced_empty` 可以进入 ActiveLock 收尾判断。

## 15. TradeFill

每一笔 Binance 成交保存为一条不可变 `TradeFill`。

至少记录：

```text
id
order_submission_attempt_id
terminal_order_status_sync_record_id
first_seen_fill_sync_result_id
exchange
market_type
account_domain
endpoint_family
symbol
client_order_id
exchange_order_id
exchange_trade_id
side
position_side
price
quantity
quantity_unit
quote_quantity
base_quantity
commission
commission_asset
realized_pnl
realized_pnl_asset
is_buyer
is_maker
trade_time_utc
sanitized_raw_fill
raw_fill_hash
trigger_source
created_at_utc
```

Binance 时间戳按 UTC 解释和保存。

TradeFill 已创建后不得因重复同步修改核心成交事实。

TradeFill 不保存 order_fill_summary_id。OrderFillSummary 通过共同的 order_submission_attempt_id 聚合所属 TradeFill，避免汇总生成后回头修改已经落库的成交事实。

TradeFill 不重复保存 trace_id。需要追踪首次同步过程时，通过 first_seen_fill_sync_result_id 读取对应 FillSyncResult、AlertEvent 和 Gateway 证据。

## 16. TradeFill 身份与幂等

数据库唯一约束：

```text
(
    exchange,
    market_type,
    account_domain,
    symbol,
    exchange_order_id,
    exchange_trade_id,
) unique
```

重复同步相同成交时：

```text
不重复插入；
不重复累计数量；
不重复累计金额；
不重复累计手续费；
不重复累计 realized pnl；
duplicate_fill_count 增加；
保留首次发现来源。
```

如果相同唯一身份对应不同核心 payload：

```text
不得覆盖旧 TradeFill；
记录数据完整性冲突；
FillSyncResult.status = incomplete；
conflict_fill_count 增加；
保持 ActiveLock；
写 critical AlertEvent。
```

## 17. 成交身份校验

每条返回成交必须满足：

```text
exchange_order_id 等于目标订单；
symbol 等于目标订单；
market_type 与 account_domain 一致；
exchange_trade_id 存在；
price > 0；
quantity > 0；
trade_time_utc 可解析；
side 和 position_side 可映射；
手续费字段可按原始资产保存。
```

任一成交身份不一致时不得混入目标订单汇总，整体结果为 `incomplete`。

## 18. USDS-M 成交口径

USDS-M 至少保存：

```text
quantity：成交标的数量；
quote_quantity：Binance 返回或可验证的 quote 数量；
price：成交价格；
commission / commission_asset；
realized_pnl 及其资产语义。
```

订单汇总：

```text
filled_quantity
= sum(TradeFill.quantity)

filled_quote_quantity
= sum(TradeFill.quote_quantity)

average_fill_price
= filled_quote_quantity / filled_quantity
```

如果 quote_quantity 缺失但允许使用 `price * quantity` 重建，必须由 USDS-M calculator 执行并记录计算来源；不能静默混用原始值与重建值。

## 19. COIN-M 成交口径

COIN-M 必须分别保存：

```text
quantity：成交 contracts 张数；
quantity_unit = contracts；
contract_size；
base_quantity：Binance 返回的原生 base 数量；
price：成交价格；
commission / commission_asset；
realized_pnl 及其原生资产语义。
```

禁止：

```text
把 contracts 当作 base quantity；
把 contracts 当作 quote quantity；
复用 USDS-M 线性金额公式；
丢弃 Binance 返回的 base_quantity；
把不同资产的手续费或 realized pnl 直接相加。
```

COIN-M 汇总必须使用独立 calculator。

当字段完整时：

```text
filled_contracts
= sum(TradeFill.quantity)

filled_notional_usd
= sum(contracts * contract_size)

filled_base_quantity
= sum(TradeFill.base_quantity)

average_fill_price
= filled_notional_usd / filled_base_quantity
```

如果原始字段不足以安全计算平均价，必须保留空值和 reason_code，不得套用 USDS-M 公式。

## 20. 手续费与 realized pnl

手续费必须按资产分别汇总：

```text
commission_totals_by_asset = {
    asset: sum(commission)
}
```

如果一笔订单存在多个手续费资产，必须全部保留，不得折算后强行写入单一 `total_commission`。

realized pnl 同样按 Binance 返回的资产语义分别保存和汇总。

FillSync 只记录交易所事实，不把 realized pnl 直接写入账户权益、ReviewDatasetRecord 或 BinancePositionSnapshot。

## 21. OrderFillSummary

每一条 OrderSubmissionAttempt 最多一条 OrderFillSummary。

唯一约束：

```text
order_submission_attempt_id unique
```

至少记录：

```text
id
order_submission_attempt_id
terminal_order_status_sync_record_id
latest_fill_sync_result_id
order_plan_id
exchange
market_type
account_domain
endpoint_family
symbol
client_order_id
exchange_order_id
terminal_exchange_status
terminal_executed_quantity
sync_status
is_complete
is_synced_empty
fill_count
filled_quantity
quantity_unit
filled_quote_quantity
filled_base_quantity
filled_notional_usd
average_fill_price
commission_totals_by_asset
realized_pnl_totals_by_asset
first_trade_time_utc
last_trade_time_utc
pagination_complete
quantity_reconciled
identity_reconciled
summary_hash
lock_finalization_status
lock_finalized_at_utc
trigger_source
created_at_utc
updated_at_utc
```

OrderFillSummary 必须从数据库中属于该 OrderSubmissionAttempt 的全部有效 TradeFill 重新聚合，不得在每次同步时对旧汇总做不可验证的增量累加。

OrderFillSummary 不重复保存 trace_id。同步过程通过 latest_fill_sync_result_id 追踪；业务归属通过 order_submission_attempt_id 和真实业务外键追溯。

## 22. 完整性校验

必须同时验证：

```text
终态 OrderStatusSyncRecord 有效；
所有查询页 pagination_complete=true；
所有 TradeFill 身份属于同一订单；
没有 payload 冲突；
TradeFill.quantity 汇总与 terminal_executed_quantity 一致；
市场域 calculator 计算成功；
OrderFillSummary 从数据库重算后 hash 稳定；
汇总引用的终态记录与 FillSyncResult 一致。
```

数量比较使用 Decimal 和交易所数量单位，不使用二进制浮点数。

允许 Decimal 格式等价，例如 `1.000` 与 `1` 等价。

任何校验失败：

```text
FillSyncResult.status = incomplete；
OrderFillSummary.is_complete = false；
保持 ActiveLock；
写 AlertEvent；
允许后续受控补同步或人工对账。
```

## 23. synced

只有满足以下全部条件才可以标记：

```text
FillSyncResult.status = synced
OrderFillSummary.sync_status = synced
OrderFillSummary.is_complete = true
```

条件：

```text
查询成功；
pagination_complete=true；
至少一条 TradeFill；
所有 TradeFill 幂等落库；
无身份或 payload 冲突；
filled_quantity = terminal_executed_quantity；
terminal_executed_quantity > 0；
汇总重算成功。
```

## 24. synced_empty

`synced_empty` 只能在以下全部条件满足时成立：

```text
终态状态属于 CANCELED / REJECTED / EXPIRED / EXPIRED_IN_MATCH；
terminal_executed_quantity = 0；
成交查询成功；
pagination_complete=true；
返回 0 条成交；
数据库中不存在该订单既有 TradeFill；
身份和查询证据完整；
OrderFillSummary 已生成且 is_complete=true。
```

结果：

```text
FillSyncResult.status = synced_empty；
OrderFillSummary.sync_status = synced_empty；
OrderFillSummary.is_synced_empty = true；
filled_quantity = 0；
average_fill_price = null。
```

以下情况绝不能标记 synced_empty：

```text
terminal_exchange_status = FILLED；
terminal_executed_quantity > 0；
分页未完成；
查询 unknown；
存在既有 TradeFill；
状态或成交身份不一致。
```

## 25. incomplete

以下任一情况必须标记 `incomplete`：

```text
FILLED 但返回 0 条成交；
terminal_executed_quantity > 0 但 TradeFill 汇总为 0；
filled_quantity 不等于 terminal_executed_quantity；
分页未完成或达到页数上限；
任一页结果不可信；
成交身份不一致；
相同成交身份出现 payload 冲突；
COIN-M 必需 contract_size 或 base quantity 缺失；
汇总计算失败；
OrderFillSummary hash 无法验证。
```

incomplete 不代表无成交，不允许解锁或重新下单。

## 26. unknown 与查询前结果

### 26.1 unknown

查询已经发出或无法判断是否发出，但结果不可信：

```text
网络错误；
read timeout；
Binance 5xx；
限频后 Gateway 耗尽尝试；
响应结构无法验证；
分页中途失败且不能形成完整结果。
```

### 26.2 failed_before_query

确认未发送查询请求并发生系统失败，例如缺少 exchange_order_id 或无法构建请求。

### 26.3 blocked_before_query

业务安全条件阻断，例如市场域不一致或终态证据不合法。

三类结果均不得释放 ActiveLock，不得触发重新提交订单。

## 27. ActiveLock 收尾

FillSync 是自动订单链路中最后一个可以发起 ActiveLock 安全释放判断的模块。

FillSync 不直接更新锁表，只调用：

```text
OrderPlanActiveLockService.finalize_after_fill_sync(
    active_lock_id,
    order_submission_attempt_id,
    terminal_order_status_sync_record_id,
    fill_sync_result_id,
    order_fill_summary_id,
    trace_id,
)
```

服务必须重新确认：

```text
ActiveLock 仍属于当前 OrderPlan；
OrderSubmissionAttempt 与全部证据一致；
OrderStatusSyncRecord 是明确终态；
FillSyncResult.status 为 synced 或严格成立的 synced_empty；
OrderFillSummary.is_complete=true；
pagination_complete=true；
quantity_reconciled=true；
identity_reconciled=true；
不存在 unknown、incomplete 或数据冲突。
```

只有全部通过才能：

```text
OrderPlanActiveLock.status = released
```

如果锁服务拒绝收尾：

```text
不得修改成交事实；
OrderFillSummary.lock_finalization_status = blocked 或 failed；
保持锁阻断；
写 high / critical AlertEvent；
进入人工核对。
```

## 28. 不得释放锁的情况

```text
OrderStatusSync 非终态；
OrderStatusSync not_found 或 unknown；
FillSyncResult syncing；
FillSyncResult incomplete；
FillSyncResult unknown；
FillSyncResult failed_before_query；
FillSyncResult blocked_before_query；
FILLED 但零成交；
terminal_executed_quantity 与成交汇总不一致；
分页不完整；
成交 payload 冲突；
OrderFillSummary 不完整；
证据属于不同 OrderSubmissionAttempt；
ActiveLock 身份不一致；
无法证明所有成交已同步。
```

不得以“市价单通常立即成交”代替完整证据。

## 29. 数据库事务

每页查询完成后的成交写入必须使用数据库事务：

```text
锁定 FillSyncResult；
按唯一键写入或读取 TradeFill；
检测重复和 payload 冲突；
更新页进度和证据；
提交事务。
```

所有页完成后，在独立事务中：

```text
锁定 FillSyncResult 和 OrderSubmissionAttempt；
从数据库重新读取全部 TradeFill；
重算 OrderFillSummary；
执行完整性校验；
推进 FillSyncResult；
写 AlertEvent；
提交事务。
```

数据库事务中不得等待 Binance 网络响应。

锁释放调用必须基于已经提交的成交与汇总事实，不得在成交事务回滚前释放锁。

## 30. 恢复补同步

默认恢复窗口：

```text
FILL_SYNC_RECOVERY_WINDOW_SECONDS = 86400
```

恢复对象必须满足：

```text
有明确 OrderSubmissionAttempt；
有终态 OrderStatusSyncRecord；
尚无完整 OrderFillSummary；
或最近 FillSyncResult 为 unknown / incomplete / failed_before_query；
距离终态确认不超过 24 小时；
仍可追溯 exchange_order_id；
ActiveLock 尚未安全释放。
```

恢复规则：

```text
必须按明确 attempt 和 terminal record 补同步；
创建新的 recovery FillSyncResult；
复用既有 TradeFill，按唯一键幂等补齐；
从数据库全部 TradeFill 重算汇总；
完整后再次调用 OrderPlanActiveLockService 收尾；
不得查询数据库全局最新订单；
不得扫描全历史订单；
不得触发重新下单。
```

超过 24 小时：

```text
不自动请求 Binance；
记录 recovery_skipped_out_of_window；
保持 ActiveLock；
写 critical AlertEvent；
进入人工诊断或专用对账。
```

## 31. 与账户持仓事实和后置复盘的关系

FillSync 不生成或修改 BinancePositionSnapshot。

TradeFill 和 OrderFillSummary 是成交事实。OpsConsole 和 ReviewDataset 可以通过对应后端 service 读取这些已落库事实，不需要 FillSync 额外生成 Tracking 交接对象或事件。

下一轮账户持仓事实必须由 Binance Account Sync 从 Binance 重新读取并形成新的 BinancePositionSnapshot，不得根据 TradeFill 在本地推导交易所持仓，也不得要求 FillSync 修改账户快照。

## 32. reason_code

至少支持：

```text
order_submission_attempt_not_found
terminal_order_status_record_not_found
terminal_order_status_invalid
source_chain_mismatch
fill_sync_time_before_source_fact
trace_context_missing
missing_exchange_order_id
unsupported_market_type
gateway_disabled
fill_query_synced
fill_query_synced_empty
fill_query_unknown
fill_query_failed_before_send
fill_query_blocked_before_send
pagination_incomplete
pagination_cursor_loop
pagination_limit_exceeded
fill_identity_mismatch
fill_payload_conflict
terminal_executed_quantity_mismatch
filled_order_has_no_fills
coin_m_contract_size_missing
summary_calculation_failed
summary_hash_invalid
active_lock_finalized
active_lock_finalization_blocked
active_lock_finalization_failed
recovery_completed
recovery_skipped_out_of_window
internal_error
```

reason_code 必须稳定，中文说明写入 reason_message 和 AlertEvent。

## 33. AlertEvent

至少包括：

```text
fill_sync_started
trade_fill_recorded
trade_fill_duplicate_skipped
trade_fill_payload_conflict
fill_sync_synced
fill_sync_synced_empty
fill_sync_incomplete
fill_sync_unknown
fill_sync_failed
fill_sync_blocked
fill_sync_recovery_completed
fill_sync_recovery_skipped
order_fill_summary_generated
active_lock_released_after_fill_sync
active_lock_finalization_blocked
```

最低字段：

```text
source_module = fill_sync
trace_id
trigger_source
event_type
severity
reason_code
order_submission_attempt_id
terminal_order_status_sync_record_id
fill_sync_result_id
order_fill_summary_id
active_lock_id
market_type
account_domain
endpoint_family
symbol
client_order_id
exchange_order_id
terminal_exchange_status
terminal_executed_quantity
fill_count
filled_quantity
quantity_unit
pagination_complete
quantity_reconciled
lock_finalization_status
```

通知必须明确区分逐笔成交、订单成交汇总和账户持仓快照变化。FillSync 不得把成交同步写成 BinancePositionSnapshot 已更新。

## 34. 日志与敏感信息

结构化日志至少包含：

```text
trace_id
order_submission_attempt_id
fill_sync_result_id
order_fill_summary_id
exchange_order_id
market_type
endpoint_family
sync_sequence
page_sequence
status
returned_fill_count
inserted_fill_count
duplicate_fill_count
gateway_attempt_count
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

所有配置必须进入 `.env.example` 并带中文注释：

```text
FILL_SYNC_ENABLED
FILL_SYNC_PAGE_SIZE
FILL_SYNC_MAX_PAGES
FILL_SYNC_RECOVERY_WINDOW_SECONDS=86400
```

约束：

```text
PAGE_SIZE 和 MAX_PAGES 必须大于零；
达到 MAX_PAGES 且仍存在下一页时必须 incomplete；
恢复窗口不是 ActiveLock 自动过期时间；
Gateway 超时、读取重试、限频和熔断配置统一由 Binance Gateway 管理；
完整性规则和市场计算公式不得通过 env 任意热修改。
```

## 36. Celery 与管理入口

Celery task 只能：

```text
解析 order_submission_attempt_id 和 terminal record id；
传递当前 OrchestrationRun / StepRun 已建立的 trace_id；
设置 trigger_source；
调用 FillSync service；
输出结构化结果。
```

task 不得：

```text
直接调用 Binance；
直接计算汇总；
直接修改 ActiveLock；
触发订单提交；
把任务重试实现成重复插入成交。
```
自动同步后续 task 沿用当前技术追踪上下文。

## 37. 数据与外部服务

```text
读写 MySQL：是，保存 FillSyncResult、TradeFill 和 OrderFillSummary；
直接访问 Redis：非必要，不作为成交事实来源；
访问 Binance：是，只通过 BinanceFillQueryGateway；
访问订单提交接口：否；
访问订单状态接口：否；
发送 Hermes：否，只写 AlertEvent；
调用大模型：否；
涉及真实交易：同步既有真实订单成交，不创建新订单；
涉及 PriceSnapshot：否；
涉及 Binance Account Sync：否；
涉及 OrderPlan / RiskCheck / ExecutionPreparation：只保留追溯；
涉及 OrderStatusSync：是，只消费明确终态记录；
涉及 ReviewDataset：只提供已落库成交事实与汇总，不直接调用；
生成或修改 BinancePositionSnapshot：否；
写 AlertEvent：是。
```

## 38. 异常处理

分类原则：

```text
查询完整且成交数量一致 → synced；
查询完整、终态零成交且确实无成交 → synced_empty；
获得部分事实但不完整或不一致 → incomplete；
查询无法形成可信结论 → unknown；
确认查询未发送的系统失败 → failed_before_query；
业务安全条件阻断 → blocked_before_query。
```

禁止：

```text
把查询超时解释为零成交；
把 FILLED + 零成交解释为 synced_empty；
把部分分页结果解释为完整；
把数量不一致解释为浮点误差并放行；
把 incomplete 或 unknown 用作解锁证据；
因成交查询失败重新提交订单；
用账户持仓倒推出缺失 TradeFill；
覆盖具有相同交易所身份但内容不同的既有成交。
```

对于 LIMIT 订单，`CANCELED`、`EXPIRED` 或 `EXPIRED_IN_MATCH` 不等于“没有成交”。只要交易所终态中的已成交数量大于零，FillSync 必须查询并落库全部逐笔成交，生成 `OrderFillSummary`。只有终态明确为零成交、成交查询完整且没有任何 TradeFill 时，才允许 `synced_empty`。

## 39. 测试要求

自动化测试必须使用 fake Gateway，不得访问真实 Binance。

至少覆盖：

```text
1. 只有明确终态 OrderStatusSyncRecord 可以触发 FillSync。
2. NEW 不触发 FillSync。
3. PARTIALLY_FILLED 不触发 FillSync。
4. not_found 不触发 FillSync。
5. OrderStatusSync unknown 不触发 FillSync。
6. 输入必须明确关联 OrderSubmissionAttempt。
7. 缺少 exchange_order_id 时不宽泛查询。
8. USDS-M 通过 Gateway 内部 fapi adapter 查询。
9. COIN-M 通过 Gateway 内部 dapi adapter 查询。
10. FillSync 无法访问 endpoint、adapter、transport 或密钥。
11. 原订单冻结市场身份不一致或当前部署不具备对应查询能力时不查询。
12. 多页成交全部查询并按 cursor 前进。
13. cursor 循环时 incomplete。
14. 达到 MAX_PAGES 仍有下一页时 incomplete。
15. 分页中途失败时不删除已落库 TradeFill。
16. 每页 Gateway attempt_count 可审计。
17. Gateway 查询失败不触发订单提交。
18. 一笔订单一条成交正确落库。
19. 一笔订单多条成交逐条落库。
20. 每条 TradeFill 直接关联 OrderSubmissionAttempt。
21. 每条 TradeFill 保存 exchange_trade_id。
22. 相同 exchange trade 重复同步不重复插入。
23. 重复同步不重复累计数量、金额、手续费或 pnl。
24. 相同唯一身份 payload 冲突时不覆盖并标记 incomplete。
25. 返回其他订单的成交时 identity mismatch。
26. 价格、数量和成交时间非法时 incomplete。
27. USDS-M 使用 quantity 和 quote_quantity 口径。
28. USDS-M 平均价计算正确。
29. COIN-M quantity 保持 contracts。
30. COIN-M 保存 contract_size 和 base_quantity。
31. COIN-M 不复用 USDS-M 线性公式。
32. COIN-M 平均价使用原生 calculator。
33. 多手续费资产分别汇总。
34. 多 realized pnl 资产分别汇总。
35. OrderFillSummary 对 OrderSubmissionAttempt 唯一。
36. 汇总每次从数据库全部 TradeFill 重算。
37. synced 要求至少一条成交和完整分页。
38. filled_quantity 等于 terminal_executed_quantity 时通过。
39. 数量不一致时 incomplete。
40. FILLED + 零成交时 incomplete。
41. terminal_executed_quantity > 0 + 零成交时 incomplete。
42. CANCELED + executed_quantity=0 + 完整零成交可以 synced_empty。
43. REJECTED + executed_quantity=0 + 完整零成交可以 synced_empty。
44. EXPIRED + executed_quantity=0 + 完整零成交可以 synced_empty。
45. EXPIRED_IN_MATCH + executed_quantity=0 + 完整零成交可以 synced_empty。
46. CANCELED / EXPIRED 有部分成交时必须同步并核对数量。
47. synced_empty 不允许存在既有 TradeFill。
48. incomplete 不释放 ActiveLock。
49. unknown 不释放 ActiveLock。
50. failed_before_query 不释放 ActiveLock。
51. blocked_before_query 不释放 ActiveLock。
52. synced 且所有证据完整时调用 OrderPlanActiveLockService。
53. synced_empty 严格成立时调用 OrderPlanActiveLockService。
54. 锁服务重新校验全部证据后才释放。
55. 锁服务拒绝时不修改成交事实并保持阻断。
56. ActiveLock 释放写 AlertEvent。
57. 恢复同步复用既有 TradeFill 并补齐缺失成交。
58. 恢复后从数据库重算汇总。
59. 超过 24 小时不自动查询、不解锁。
60. 不扫描数据库全局最新或全历史订单。
61. FillSync 不生成或修改 BinancePositionSnapshot。
62. 完整汇总无需生成额外 Tracking 交接对象或事件。
63. 不调用订单状态或订单提交 Gateway。
64. 日志、记录和告警不包含密钥或签名。
65. 所有正式结果和关键成交写 AlertEvent。
66. 正式 service 不接受调用方传入判断时间，时间早于上游终态或既有同步事实时不查询。
67. 自动交易或新订单提交关闭后，明确终态订单仍继续自动 FillSync。
68. 当前部署不具备原订单市场的成交只读能力时 blocked_before_query，并保持 ActiveLock。
69. trace_id 保存在 FillSyncResult、AlertEvent、Gateway 元数据和日志中，不写入 TradeFill 或 OrderFillSummary。
70. 自动 Celery task 只传递已有 trace_id。
71. TradeFill 不保存 order_fill_summary_id，生成汇总后不回写修改既有成交事实。
72. 正式自动链路缺少 trace_id 时 failed_before_query，且不请求 Binance。
```

## 40. 验收标准

满足以下条件才算完成：

```text
FillSync 只消费 OrderStatusSync 明确终态；
所有 Binance 成交查询统一经过 BinanceFillQueryGateway；
exchange_order_id 是正式查询边界，不做宽泛时间窗口混单查询；
所有分页完整拉取，截断或失败不会被标记成功；
TradeFill 按交易所成交身份幂等且不可变；
重复同步不会重复累计任何成交或费用；
USDS-M 与 COIN-M 使用独立、正确的数量和金额口径；
手续费和 realized pnl 保留资产维度；
OrderFillSummary 对提交 attempt 唯一并从 TradeFill 全量重算；
synced 要求查询完整且成交数量与终态一致；
synced_empty 只允许明确零成交终态；
FILLED、正 executed_quantity、分页不完整或数量不一致时不得 synced_empty；
incomplete、unknown 和查询前失败均不会解锁；
只有终态与成交证据完整时才调用 OrderPlanActiveLockService；
FillSync 不直接修改锁表；
锁释放后所有事实仍可追溯到同一 OrderSubmissionAttempt；
关闭新交易不会停止明确终态订单的自动成交同步和安全收尾；
生产判断时间由 service 内部取得，调用方不能回拨恢复窗口；
trace_id 只保留在同步技术记录和技术交接中，不写入 TradeFill 或 OrderFillSummary；
TradeFill 不反向引用后生成的 OrderFillSummary，成交事实创建后无需为汇总关系回写；
FillSync 不重新下单、不生成或修改 BinancePositionSnapshot、不调用大模型；
所有成交事实、汇总、异常和锁收尾均可审计。
```

## 41. 当前不包含的能力

```text
订单提交或重试提交；
订单状态查询；
撤单或改单；
无限成交查询重试；
WebSocket User Data Stream；
账户余额同步；
BinancePositionSnapshot 生成或修改；
账户级或策略级盈亏计算；
手续费资产自动折算；
自动补单或缩单；
全历史成交扫描；
多 active domain 并行同步；
大模型成交判断。
```
