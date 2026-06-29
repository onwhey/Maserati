# OrderCycleCloseout 需求

## 1. 模块定位

OrderCycleCloseout 负责在一个 4 小时交易周期结束前，对本周期遗留的限价订单进行受控收尾。

它解决的问题是：

```text
本周期生成并提交的 LIMIT 订单；
到本周期收尾时间仍未确认终态；
不能让它继续挂到下一轮主交易编排；
也不能让下一轮在旧订单未收尾时绕过 ActiveLock 继续生成新订单链路。
```

OrderCycleCloseout 不是订单提交模块，不是订单状态同步模块，不是成交同步模块，也不是策略复盘模块。

它只处理已经存在的订单链路风险收尾。

## 2. 核心目标

本模块必须完成：

```text
按明确周期找到本周期需要收尾的 LIMIT 订单；
确认订单所属市场身份、订单链路和 ActiveLock 一致；
在限价单有效期结束后，对仍无明确终态的订单执行受控撤单；
撤单只通过 BinanceOrderCancelGateway；
撤单后必须交给 OrderStatusSync 查询最终订单状态；
明确终态后必须交给 FillSync 查询成交事实；
保留撤单尝试、撤单结果、状态查询和成交同步的完整追溯；
不释放 ActiveLock，只推动后续状态与成交事实完成后由锁服务收尾。
```

## 3. 不负责事项

OrderCycleCloseout 不负责：

```text
提交新订单；
重试订单提交；
修改订单；
追单；
把 LIMIT 改成 MARKET；
重新计算 OrderPlan；
重新执行 RiskCheck；
重新执行 ExecutionPreparation；
重新生成 PreparedOrderIntent；
判断策略是否正确；
判断限价未成交是否代表策略失败；
生成 TradeFill；
生成 OrderFillSummary；
直接释放 ActiveLock；
直接调用 BinanceOrderStatusGateway；
直接调用 BinanceFillQueryGateway；
调用大模型；
发送 Hermes。
```

OrderCycleCloseout 可以写 AlertEvent，但不直接发送通知。

## 4. 运行时机

限价单默认只服务当前 4 小时交易周期，不得跨入下一轮主交易编排。

示例：

```text
00:00 周期生成的 LIMIT 订单，默认最晚有效到 03:50 UTC；
03:55 UTC 执行本周期订单收尾任务；
04:05 UTC 执行下一轮主交易编排。
```

其他周期同理：

```text
04:00 周期 → 07:50 到期，07:55 收尾，08:05 下一轮主编排；
08:00 周期 → 11:50 到期，11:55 收尾，12:05 下一轮主编排。
```

具体时间可以由部署调度配置决定，但必须满足：

```text
closeout_time_utc > limit_valid_until_utc；
closeout_time_utc < next_main_orchestration_time_utc；
LIMIT 订单不得被设计为跨周期长期挂单。
```

## 5. 输入对象

本模块只接受明确周期或明确订单链路作为输入。

周期收尾输入至少包括：

```text
cycle_start_utc
cycle_end_utc
closeout_time_utc
market_type
account_domain
symbol
trigger_source
trace_id
```

单笔收尾输入至少包括：

```text
order_submission_attempt_id
prepared_order_intent_id
active_lock_id
trigger_source
trace_id
```

不得通过“数据库最新订单”“最近一条挂单”“某个 symbol 的全部未完成订单”来自动猜测收尾对象。

## 6. 可收尾订单资格

只有同时满足以下条件的订单才能进入本模块：

```text
存在 PreparedOrderIntent；
PreparedOrderIntent.order_type = LIMIT；
存在 OrderSubmissionAttempt；
OrderSubmissionAttempt 属于该 PreparedOrderIntent；
订单提交结果为 accepted 或 unknown；
存在明确 client_order_id；
market_type、account_domain、symbol 与上游订单链路一致；
存在 OrderPlanActiveLock；
ActiveLock 仍属于该订单链路；
limit_valid_until_utc 已经到达或超过；
尚无明确终态且成交同步完整的收尾证据。
```

以下情况不得撤单：

```text
MARKET 订单；
提交前失败且 request_sent=false 的订单；
交易所明确拒绝且没有可能存在挂单的订单；
已经确认 FILLED / CANCELED / REJECTED / EXPIRED / EXPIRED_IN_MATCH 的订单；
已经完成 FillSync 且 ActiveLock 已安全释放的订单；
市场身份无法确认的订单；
缺少 client_order_id 且缺少 exchange_order_id 的订单。
```

## 7. 收尾流程

标准流程：

```text
1. 根据周期或明确订单链路选中待收尾 LIMIT 订单；
2. 锁定本地订单链路和 ActiveLock，防止并发收尾；
3. 读取最新 OrderStatusSyncRecord；
4. 如果已经存在明确终态，跳过撤单，交给 FillSync 或确认 FillSync 状态；
5. 如果仍无明确终态，构造冻结撤单请求；
6. 调用 BinanceOrderCancelGateway.cancel_order；
7. 保存 OrderCancelAttempt；
8. 写 AlertEvent；
9. 调用或触发 OrderStatusSync 对该 OrderSubmissionAttempt 继续查询；
10. OrderStatusSync 查到明确终态后，交给 FillSync；
11. FillSync 完成后，由 OrderPlanActiveLockService 判断是否释放锁。
```

OrderCycleCloseout 不直接查询订单状态 Gateway，也不直接查询成交 Gateway。

它只能调用：

```text
BinanceOrderCancelGateway；
OrderStatusSync service；
FillSync service（仅在已经存在明确终态且需要补齐成交同步时）。
```

## 8. 撤单请求规则

撤单请求必须使用上游已经冻结的订单身份：

```text
market_type
account_domain
symbol
client_order_id
exchange_order_id（如已知）
order_submission_attempt_id
prepared_order_intent_id
active_lock_id
```

撤单请求不得携带：

```text
quantity
price
side
newClientOrderId
timeInForce
leverage
marginType
positionMode
任意用于重新下单或改单的字段。
```

如果撤单请求返回“订单不存在”，不得直接解释为订单从未提交，也不得释放 ActiveLock。必须继续通过 OrderStatusSync 保存状态查询事实。

如果撤单请求返回 unknown，不得重试撤单，不得重试订单提交，必须保持 ActiveLock，并通过 OrderStatusSync / RuntimeGuard 保留后续排查入口。

## 9. OrderCancelAttempt

每次撤单尝试必须保存为独立记录。

至少记录：

```text
id
order_cancel_attempt_key
order_submission_attempt_id
prepared_order_intent_id
order_plan_id
active_lock_id
market_type
account_domain
symbol
client_order_id
exchange_order_id
cancel_reason_code
cancel_status
request_sent
response_received
gateway_attempt_count
http_status
binance_error_code
sanitized_error_message
sanitized_response
response_hash
trace_id
trigger_source
started_at_utc
finished_at_utc
created_at_utc
```

`cancel_status` 至少支持：

```text
accepted
not_found
unknown
failed_before_cancel
blocked_before_cancel
```

撤单记录只描述撤单请求本身，不等于订单最终状态。

## 10. 幂等与并发

同一 `OrderSubmissionAttempt` 在同一周期收尾窗口内最多只能存在一条有效 `OrderCancelAttempt`。

幂等键至少包含：

```text
order_submission_attempt_id
prepared_order_intent_id
active_lock_id
limit_valid_until_utc
closeout_time_utc
cancel_reason_code
```

并发规则：

```text
撤单前必须在数据库事务中锁定 OrderSubmissionAttempt、PreparedOrderIntent 和 ActiveLock；
发现已有有效撤单记录时，不得重复请求 Binance；
撤单网络请求不得在长事务中等待；
撤单结果写入后，再触发 OrderStatusSync；
不得并发对同一订单执行多个撤单请求。
```

## 11. 与真实交易权限的关系

OrderCycleCloseout 处理的是已经提交过的真实订单风险收尾，不是新开仓、新加仓或重新提交订单。

规则：

```text
关闭新的真实交易运行开关，不得阻止既有 LIMIT 订单的受控撤单收尾；
.env 或部署凭据缺少交易写权限时，撤单请求必须在发送前失败；
撤单失败不得转为重新下单；
撤单失败不得自动释放 ActiveLock；
撤单失败必须写 AlertEvent，并等待 RuntimeGuard 或 OpsConsole 人工排查。
```

## 12. 与主编排的关系

OrderCycleCloseout 可以由独立的周期收尾编排运行承载。

该编排运行应记录：

```text
cycle_kind = order_cycle_closeout
subject_cycle_start_utc
subject_cycle_end_utc
subject_orchestration_run_id（如能明确关联原主编排）
```

它不是下一轮主交易编排的一部分。

如果收尾任务在下一轮主交易编排开始前未完成：

```text
下一轮仍可以执行数据采集、质检、快照、特征和策略分析；
但只要同一交易身份的 ActiveLock 未释放，下一轮不得进入新的 OrderPlan 订单链路；
不得为了让下一轮继续而绕过或释放旧锁。
```

## 13. AlertEvent

至少支持：

```text
order_cycle_closeout_started
order_cycle_closeout_no_residual_order
order_cycle_closeout_cancel_requested
order_cycle_closeout_cancel_accepted
order_cycle_closeout_cancel_not_found
order_cycle_closeout_cancel_unknown
order_cycle_closeout_cancel_failed
order_cycle_closeout_status_sync_requested
order_cycle_closeout_fill_sync_requested
order_cycle_closeout_blocked
```

通知必须明确这是“限价单周期收尾”或“撤单请求”，不得写成新订单提交、成交确认或锁已释放。

## 14. 当前不包含的能力

```text
跨周期长期挂单；
追单；
改单；
把 LIMIT 改为 MARKET；
自动重新下单；
根据未成交结果评价策略；
直接生成复盘结论；
后台自由扫描全历史订单；
WebSocket User Data Stream；
自动释放 ActiveLock。
```

## 15. 测试要求

至少覆盖：

```text
1. 只处理 LIMIT 订单。
2. MARKET 订单不会进入撤单收尾。
3. limit_valid_until_utc 未到时不撤单。
4. 已有明确终态时不撤单。
5. 已完成 FillSync 并释放锁时不撤单。
6. 缺少订单身份时 blocked_before_cancel。
7. 市场身份不一致时 blocked_before_cancel。
8. ActiveLock 不属于该订单链路时 blocked_before_cancel。
9. accepted LIMIT 到期后生成 OrderCancelAttempt。
10. unknown LIMIT 到期后允许受控撤单。
11. 同一订单同一收尾窗口不会重复撤单。
12. 撤单 accepted 后触发 OrderStatusSync。
13. 撤单 not_found 后不释放锁，仍触发或等待 OrderStatusSync 事实。
14. 撤单 unknown 后不重试撤单、不重试订单提交。
15. 撤单失败不触发新订单。
16. 撤单请求不携带数量、价格、方向、timeInForce 或改单字段。
17. 关闭新的真实交易运行开关不阻止既有订单撤单收尾。
18. 缺少撤单所需部署凭据时不请求 Binance，并写 AlertEvent。
19. OrderCycleCloseout 不直接调用订单状态 Gateway 或成交 Gateway。
20. OrderCycleCloseout 不直接释放 ActiveLock。
```

## 16. 验收标准

满足以下条件才算完成：

```text
限价单不会跨周期无约束遗留；
收尾任务只处理明确归属的 LIMIT 订单；
撤单只通过 BinanceOrderCancelGateway；
撤单不会变成订单提交重试、改单或追单；
撤单后订单最终状态仍由 OrderStatusSync 确认；
成交事实仍由 FillSync 同步；
ActiveLock 只在状态与成交事实完整后由锁服务收尾；
下一轮主编排不会绕过未收尾旧锁；
所有撤单尝试、异常、状态查询和成交同步均可审计。
```
