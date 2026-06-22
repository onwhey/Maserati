# Execution / OrderSubmission 需求

## 1. 模块定位

Execution 是系统唯一允许提交真实订单的模块，`OrderSubmission` 是 Execution 当前承担的订单提交能力。

正式链路：

```text
ExecutionPreparationResult
→ PreparedOrderIntent
→ Execution / OrderSubmission
→ OrderSubmissionAttempt
→ OrderStatusSync
→ FillSync
→ 订单状态与成交事实闭环
```

本模块只消费有效的 `PreparedOrderIntent`，抢占其唯一提交资格，通过 `BinanceOrderSubmissionGateway` 发起至多一次真实订单提交，并保存提交事实。

`OrderSubmissionAttempt` 只表示一次提交动作及其确定性，不代表完整订单生命周期，也不代表已经成交。

## 2. 核心目标

本模块必须完成：

```text
校验 PreparedOrderIntent 可提交；
校验完整上游身份和 ActiveLock；
校验冻结订单链中的市场身份一致；
校验冻结订单参数未被修改；
以数据库事务抢占唯一提交资格；
通过 BinanceOrderSubmissionGateway 发起一次订单提交；
绝不重试提交；
把结果分类为 accepted、rejected、unknown、blocked_before_submit 或 failed_before_submit；
记录 request_sent 与 response_received；
持久化 OrderSubmissionAttempt；
推进 PreparedOrderIntent 和 ActiveLock；
把 accepted / unknown 交给 OrderStatusSync；
写 AlertEvent 和结构化审计证据。
```

## 3. 不负责事项

本模块不负责：

```text
生成 StrategySignal 或 DecisionSnapshot；
重新计算目标仓位；
生成或修改 OrderPlan；
生成或修改 CandidateOrderIntent；
重新执行 RiskCheck；
生成或修改 ApprovedOrderIntent；
重新执行 ExecutionPreparation；
重新查询 mark price 或盘口价格；
重新执行 1% price guard；
生成新的 PriceSnapshot 或 BinanceSyncRun；
修改 side、quantity、contracts、reduce_only 或 order_type；
自动缩单、补单、拆单或反转订单；
自动重试订单提交；
撤销、替换或修改交易所订单；
确认订单最终状态；
同步逐笔成交、手续费或真实持仓；
根据提交响应直接生成 TradeFill；
修改杠杆、保证金模式或持仓模式；
接入 WebSocket 或 User Data Stream；
直接发送 Hermes；
调用大模型。
```

## 4. 支持范围

当前支持：

```text
Binance USDS-M Futures；
Binance COIN-M Futures；
MARKET order；
One-Way Mode；
positionSide = BOTH；
每个运行实例只激活一个 market domain；
每份 PreparedOrderIntent 至多一次真实提交调用。
```

市场组合：

| market_type | account_domain | quantity_unit | Gateway adapter |
|---|---|---|---|
| usds_m_futures | usds_m_futures | quantity | Gateway 内部 fapi adapter |
| coin_m_futures | coin_m_futures | contracts | Gateway 内部 dapi adapter |

Execution 不直接选择 fapi / dapi endpoint，也不得接触 adapter 实例。Gateway 根据 `market_type` 和受控配置完成内部路由。

当前不支持：

```text
LIMIT；
STOP_MARKET；
TAKE_PROFIT_MARKET；
TRAILING_STOP_MARKET；
批量订单；
Hedge Mode；
多 active domain 并行交易；
多账户并行交易；
其他交易所；
在本模块内执行模拟撮合或虚拟持仓仿真。
```

## 5. 正式服务入口

```text
submit_prepared_order(
    prepared_order_intent_id,
    business_request_key,
    trace_id,
    trigger_source,
)
```

输入至少包括：

```text
prepared_order_intent_id
business_request_key
trace_id
trigger_source
```

要求：

```text
正式服务在入口内部取得当前 UTC，调用方不得传入或覆盖业务判断时间；
测试通过可替换 UTC clock 固定时间，不通过正式服务参数回拨时间；
trace_id 必须来自当前 OrchestrationRun / StepRun 的技术调用上下文，不从 PreparedOrderIntent 读取；
trigger_source 必须记录 scheduler、orchestrator、management_command 或受控人工入口；
调用方不得传入 base URL、API key、secret、endpoint path 或 adapter 名称。
```

trace_id 在本模块中只用于当前 StepRun 技术上下文、OrderSubmissionAttempt、AlertEvent、Gateway 元数据、结构化日志和下游技术交接，不作为业务外键、幂等键或订单链路归属依据。

正式自动链路缺少 trace_id 时必须在调用 Gateway 前 `failed_before_submit`，本模块不得自行生成一个与当前编排无关的替代值。

## 6. 必须读取的对象

提交前必须读取：

```text
PreparedOrderIntent
ExecutionPreparationResult
ApprovedOrderIntent
RiskCheckResult
CandidateOrderIntent
OrderPlan
OrderPlanActiveLock
BinanceSymbolRuleSnapshot
既有 OrderSubmissionAttempt
```

可以通过上游引用校验 `PriceSnapshot`、`BinanceSyncRun` 和证据 hash，但不得重新选择价格或账户事实。

## 7. PreparedOrderIntent 校验

必须满足：

```text
PreparedOrderIntent 存在；
status = prepared；
当前 UTC 时间严格早于 expires_at_utc；
绑定 ExecutionPreparationResult；
ExecutionPreparationResult.status = PREPARED；
绑定 ApprovedOrderIntent、RiskCheckResult、CandidateOrderIntent 和 OrderPlan；
冻结参数完整；
client_order_id 非空；
idempotency_key 非空；
evidence_hash 可验证；
position_mode = one_way；
position_side = BOTH；
不存在已经开始或完成的 OrderSubmissionAttempt；
订单链路未取消、未过期、未终结。
```

service 必须在入口内部只取得一次 `submission_time_utc`，并在提交资格抢占前使用该时间判断有效期。在 `submission_time_utc >= expires_at_utc` 时必须阻断，等于过期时间也不可提交。

`submission_time_utc` 不得早于 PreparedOrderIntent.prepared_at_utc 或 ExecutionPreparationResult.finished_at_utc；出现时间倒退时必须阻断，不得调用 Gateway。

过期对象不得：

```text
恢复为 prepared；
重新执行 price guard；
重新生成 client_order_id；
创建第二份 PreparedOrderIntent；
进入 Gateway。
```

## 8. 链路身份一致性

必须确认以下字段在上游对象之间一致：

```text
exchange
market_type
account_domain
symbol
order_plan_id
candidate_order_intent_id
risk_check_result_id
approved_order_intent_id
execution_preparation_result_id
prepared_order_intent_id
price_snapshot_id
binance_sync_run_id
active_lock_id
```

任一身份冲突必须在调用 Gateway 前阻断。

不得：

```text
根据 symbol 猜测 market_type；
根据 quantity_unit 反推并覆盖 account_domain；
拼接没有真实业务外键关系的对象；
使用其他订单链路的 ActiveLock；
使用数据库中的 latest PriceSnapshot 或 BinanceSyncRun 兜底。
```

## 9. Price guard 边界

ExecutionPreparation 已经通过 `BinancePublicMarketGateway.get_book_ticker` 完成执行前价格保护。

Execution 只校验：

```text
ExecutionPreparationResult.status = PREPARED；
price_snapshot_id 与 PreparedOrderIntent 一致；
price_snapshot_hash 可验证；
reference_mark_price 大于零；
selected_live_price 大于零；
price_deviation_bps 小于或等于执行准备时冻结的阈值；
price guard 证据 hash 与 PreparedOrderIntent.evidence_hash 一致；
PreparedOrderIntent 尚未过期。
```

Execution 不得：

```text
再次调用 get_mark_price；
再次调用 get_book_ticker；
读取另一份 PriceSnapshot；
重新计算新的价格阈值；
用“最新价格”替换冻结证据；
因价格看起来更有利而绕过已冻结结果。
```

实时盘口查询与 mark price 的 1% 比较只发生在 ExecutionPreparation。本模块通过 30 秒以内的 `PreparedOrderIntent` 有效期限制提交时间。

## 10. 冻结市场身份

Execution 只使用 PreparedOrderIntent 及其完整上游订单链已经冻结的市场身份：

合法值：

```text
usds_m_futures
coin_m_futures
```

提交前必须满足：

```text
PreparedOrderIntent.market_type = ExecutionPreparationResult.market_type；
PreparedOrderIntent.account_domain = ExecutionPreparationResult.account_domain；
PreparedOrderIntent.market_type = OrderPlanActiveLock.market_type；
PreparedOrderIntent.account_domain = OrderPlanActiveLock.account_domain；
以上市场身份与 ApprovedOrderIntent、CandidateOrderIntent 和 OrderPlan 一致。
```

Execution 不读取当前全局市场配置来替换冻结市场身份。BinanceOrderSubmissionGateway 根据冻结的 market_type 选择 adapter，并独立校验自己的部署级接口硬配置。

任何不一致都必须 `blocked_before_submit`，不得切换市场域、不得回退到另一 adapter、不得提交。

## 11. 真实交易权限边界

正式编排进入 OrderPlan 前已经由 OrderPlanStepAdapter 检查并冻结本轮真实交易权限。Execution 不再读取 `.env` 或 MySQL 运行开关，也不在报单前重复执行运行权限检查。

后台在本轮通过 OrderPlan 准入后关闭真实交易，只影响下一次进入 OrderPlan 的检查，不中止本轮已经形成的订单链。

BinanceOrderSubmissionGateway 仍按自己的合同检查 Gateway、订单提交接口和真实交易部署级硬开关。该检查只保护外部接口能力，不引入数据库运行开关或独立安全模块。

管理命令和 OpsConsole 不得直接构造 PreparedOrderIntent 或绕过正式链路调用真实提交；dry-run 不能调用 BinanceOrderSubmissionGateway。当前阶段不实现模拟交易运行模式。

### 11.1 订单名义记录

Execution 只能使用 PreparedOrderIntent 已冻结的数量、ExecutionPreparation 已冻结的 `selected_live_price`，以及明确绑定的 BinanceSymbolRuleSnapshot 计算本次订单名义。

```text
USDS-M order_notional
= quantity * selected_live_price

COIN-M order_notional_usd
= contracts * contract_size
```

要求：

```text
使用 Decimal 或等价精确十进制；
selected_live_price 必须来自已通过的 ExecutionPreparationResult；
COIN-M contract_size 必须来自同一订单链明确绑定且 hash 可验证的 BinanceSymbolRuleSnapshot；
不得查询新的价格；
不得重新执行 price guard；
订单名义只作为提交事实和后续审计字段，不在本模块形成新的运行时金额上限；
不得根据本模块重新计算的名义修改、缩小、拆分或重写冻结订单。
```

## 12. ActiveLock 校验

提交前必须确认：

```text
OrderPlanActiveLock 存在；
status = active；
active_order_plan_id 等于当前 OrderPlan；
exchange、market_type、account_domain 和 symbol 一致；
锁没有被 ExecutionPreparation 释放或标记 failed；
不存在另一条订单链路持有同一业务身份的有效锁。
```

ActiveLock 缺失、冲突或状态异常时不得调用 Gateway。

Execution 只能调用 `OrderPlanActiveLockService` 推进锁，不得直接更新锁表。

## 13. 冻结订单请求

`frozen_order_request` 必须完全来自 PreparedOrderIntent 已冻结字段：

```text
symbol
side
position_side
position_mode
order_type
quantity
quantity_unit
reduce_only
client_order_id
```

Execution 可以执行字段名映射和结构化封装，但不得改变任何业务值。

冻结的 `position_mode` 必须是 `one_way`，冻结的 `position_side` 必须是 `BOTH`。任一不满足时必须在调用 Gateway 前阻断，Execution 和 Gateway 均不得替调用方改写。

MARKET 请求要求：

```text
type = MARKET；
side 只能是 BUY 或 SELL；
quantity 大于零；
positionSide = BOTH，或由 Gateway 按 One-Way Mode 的固定协议省略；
newClientOrderId = PreparedOrderIntent.client_order_id；
reduceOnly = PreparedOrderIntent.reduce_only；
不发送 price；
不发送 stopPrice；
不发送 timeInForce；
不发送 idempotency_key。
```

数量语义：

```text
USDS-M：quantity 表示上游冻结的标的数量；
COIN-M：quantity 参数承载上游冻结的 contracts 张数；
Execution 和 Gateway 都不得把 contracts 转成 base asset 或 quote asset。
```

## 14. Gateway 调用合同

唯一允许调用：

```text
BinanceOrderSubmissionGateway.submit_order(
    market_type,
    frozen_order_request,
    call_context,
)
```

调用上下文至少包括：

```text
trace_id
trigger_source
operation = submit_order
market_type
account_domain
symbol
business_object_type = PreparedOrderIntent
business_object_id = prepared_order_intent_id
prepared_order_intent_id
order_submission_attempt_id
client_order_id
execution_mode = real
request_time_utc
```

Execution 不得获得：

```text
BinanceTransport
FapiOrderAdapter
DapiOrderAdapter
raw HTTP client
通用 request 方法
API secret
signature
认证 header
endpoint path
```

Gateway 内部根据 `market_type` 选择 fapi 或 dapi adapter，并在结果元数据中返回实际 `endpoint_family`。

## 15. 订单提交绝不重试

同一 `PreparedOrderIntent` 对应的 `submit_order` 最多只能被调用一次。

以下所有层级均不得重试订单提交：

```text
BinanceOrderSubmissionGateway；
Gateway 内部 transport；
Execution application service；
Execution domain service；
Celery task；
PipelineOrchestrator；
management command；
OpsConsole；
人工重复触发；
异常恢复任务。
```

无论发生何种错误，都不得对同一 PreparedOrderIntent 再次调用提交接口，包括：

```text
connect timeout；
read timeout；
DNS 错误；
连接断开；
HTTP 429；
HTTP 418；
HTTP 5xx；
Binance 系统繁忙；
认证失败；
权限失败；
参数错误；
明确拒单；
本地配置错误；
数据库异常；
进程崩溃；
无法判断请求是否发出。
```

提交前明确未发出也不允许复用本次 PreparedOrderIntent。该订单链路终结并在安全条件下释放 ActiveLock，后续只能由新的编排运行重新生成完整订单链路。

提交结果不明时不得生成新订单，也不得由新编排运行绕过未释放的 ActiveLock。

## 16. Gateway 返回合同

Execution 必须消费 Gateway 标准结果，至少包括：

```text
operation
market_type
endpoint_family
success
payload
request_sent
response_received
http_status
binance_error_code
sanitized_error_message
server_time_utc
request_started_at_utc
request_finished_at_utc
latency_ms
attempt_count
rate_limit_metadata
trace_id
```

订单提交必须满足：

```text
attempt_count = 1；
Gateway 不隐藏 request_sent；
Gateway 不隐藏 response_received；
错误结果也返回可审计元数据；
payload 不包含 secret、signature 或完整认证 header。
```

如果 Gateway 返回 `attempt_count > 1`，Execution 必须记录 critical 级别异常并停止后续自动动作，因为这违反订单提交禁重试合同。

## 17. OrderSubmissionAttempt

每个 PreparedOrderIntent 只能对应一份正式提交尝试记录。

至少记录：

```text
id
order_submission_attempt_key
prepared_order_intent_id
execution_preparation_result_id
approved_order_intent_id
risk_check_result_id
candidate_order_intent_id
order_plan_id
business_request_key
active_lock_id
exchange
market_type
account_domain
endpoint_family
symbol
side
position_side
position_mode
order_type
quantity
quantity_unit
reduce_only
order_notional
client_order_id
idempotency_key
frozen_order_request
request_payload_hash
status
request_sent
response_received
gateway_attempt_count
exchange_order_id
exchange_client_order_id
exchange_status
sanitized_exchange_response
exchange_response_hash
http_status
binance_error_code
sanitized_error_message
exception_class
reason_code
reason_message
rate_limit_metadata
trace_id
trigger_source
claimed_at_utc
submitted_at_utc
finished_at_utc
created_at_utc
updated_at_utc
```

禁止保存：

```text
API secret；
signature；
完整 X-MBX-APIKEY；
完整认证 header；
未脱敏的敏感 Gateway 内部状态。
```

## 18. OrderSubmissionAttempt 状态

正式状态：

```text
created
submitting
accepted
rejected
unknown
blocked_before_submit
failed_before_submit
```

含义：

```text
created：唯一 attempt 已创建，尚未抢占提交权；
submitting：已抢占唯一提交权，即将或正在调用 Gateway；
accepted：Binance 明确接受订单请求；
rejected：Binance 明确拒绝且可以确认未接受订单；
unknown：无法确认 Binance 是否收到或处理订单；
blocked_before_submit：业务或安全条件阻断，确认未发送请求；
failed_before_submit：系统失败，且能够确认未发送请求。
```

`submitting` 是高风险中间状态。进程崩溃后不得把它自动恢复成 `created` 或再次调用 Gateway。

## 19. PreparedOrderIntent 状态推进

固定映射：

```text
attempt.accepted
→ PreparedOrderIntent.status = submitted

attempt.rejected
→ PreparedOrderIntent.status = submission_rejected

attempt.unknown
→ PreparedOrderIntent.status = submission_unknown

attempt.blocked_before_submit
→ PreparedOrderIntent.status = submission_blocked

attempt.failed_before_submit
→ PreparedOrderIntent.status = submission_failed
```

任何终结状态都不得改回 `prepared`。

同一 PreparedOrderIntent 不得创建第二个 client_order_id、第二个 attempt 或第二次 Gateway 调用。

## 20. accepted 分类

只有 Gateway 返回的确定证据满足以下要求时，才可分类为 `accepted`：

```text
request_sent = true；
response_received = true；
success = true；
HTTP 响应属于成功范围；
返回可识别 exchange_order_id 或 exchange_client_order_id；
返回 client order id 时必须等于 PreparedOrderIntent.client_order_id；
不存在 Binance 明确错误码；
响应市场身份与请求一致。
```

accepted 后：

```text
OrderSubmissionAttempt.status = accepted；
PreparedOrderIntent.status = submitted；
保存 exchange_order_id、exchange_client_order_id 和 exchange_status；
ActiveLock 保持 active；
写 AlertEvent；
触发 OrderStatusSync 的受控后续编排。
```

即使 MARKET 响应中出现 `FILLED`，本模块也只记录提交响应，不直接创建 TradeFill，不因响应看起来已成交而释放 ActiveLock。

`accepted` 只表示交易所接受了订单，不表示成交完整。

## 21. rejected 分类

只有同时满足以下条件时，才可分类为 `rejected`：

```text
response_received = true；
Binance 返回明确业务拒绝；
可以确认订单没有被接受；
错误不具有 execution status unknown 语义；
不存在可能已创建订单的歧义。
```

rejected 后：

```text
OrderSubmissionAttempt.status = rejected；
PreparedOrderIntent.status = submission_rejected；
记录错误码和脱敏错误摘要；
不得重试；
调用 OrderPlanActiveLockService 安全释放锁；
写 AlertEvent；
不触发订单状态轮询。
```

后续如仍需交易，只能等待新的编排运行重新完成账户同步、价格快照、OrderPlan、RiskCheck 和 ExecutionPreparation。

## 22. unknown 分类

以下任一情况必须进入 `unknown`：

```text
request_sent = true 且 response_received = false；
无法判断 request_sent；
请求发出后 read timeout；
连接在提交期间断开；
Binance 返回 execution status unknown 语义；
HTTP 503 或其他响应无法确认订单是否创建；
Gateway 结果缺少确定分类所需字段；
进程在 submitting 期间崩溃；
Gateway 返回成功，但本地无法可靠完成结果持久化；
任何无法证明订单未被接受的情况。
```

unknown 后：

```text
OrderSubmissionAttempt.status = unknown；
PreparedOrderIntent.status = submission_unknown；
ActiveLock 保持 active 或 failed 阻断；
不得再次调用 submit_order；
不得生成新的 PreparedOrderIntent；
不得允许新的编排运行绕过锁；
写 high / critical AlertEvent；
交给 OrderStatusSync 使用原 client_order_id 查询。
```

订单查询返回 `not_found` 也不足以立即释放锁，必须继续遵守 OrderStatusSync 和 ActiveLock 的确定性规则。

## 23. blocked_before_submit

适用于业务条件明确阻断，且能够证明 `request_sent = false`：

```text
PreparedOrderIntent 已过期；
PreparedOrderIntent 状态不可提交；
submission_time_utc 早于已绑定事实时间；
ExecutionPreparationResult 不是 PREPARED；
ActiveLock 缺失或不匹配；
冻结订单链市场身份不一致；
execution_mode 不是 real；
冻结业务参数不合法；
position_mode 不是 one_way；
position_side 不是 BOTH；
冻结证据 hash 不一致；
订单类型或数量单位不支持。
```

处理：

```text
OrderSubmissionAttempt.status = blocked_before_submit；
request_sent = false；
PreparedOrderIntent.status = submission_blocked；
不得重试；
不得恢复本次 PreparedOrderIntent；
确认没有其他提交事实后安全释放 ActiveLock；
写 AlertEvent。
```

PreparedOrderIntent 不存在时无法创建有效外键 attempt，但仍必须返回结构化阻断结果并写 AlertEvent。

## 24. failed_before_submit

适用于系统异常，且能够证明 Gateway 没有发送订单：

```text
本地数据库错误发生在提交资格抢占前；
正式自动链路缺少 trace_id；
请求结构构建失败且尚未调用 Gateway；
Gateway 在请求发送前明确返回本地配置或权限失败；
Gateway 明确返回 request_sent = false；
其他能够证明 Binance 未收到请求的系统失败。
```

处理：

```text
OrderSubmissionAttempt.status = failed_before_submit；
request_sent = false；
PreparedOrderIntent.status = submission_failed；
不得重试；
不得恢复本次 PreparedOrderIntent；
确认没有其他提交事实后安全释放 ActiveLock；
写 AlertEvent。
```

如果无法证明 `request_sent = false`，必须改为 `unknown`，不得使用 failed_before_submit。

## 25. 幂等与唯一约束

数据库唯一约束至少包括：

```text
OrderSubmissionAttempt.prepared_order_intent_id unique
OrderSubmissionAttempt.order_submission_attempt_key unique
OrderSubmissionAttempt.client_order_id unique
OrderSubmissionAttempt.idempotency_key unique
```

规则：

```text
同一 PreparedOrderIntent 重复调用只返回已有 attempt；
已有任何状态的 attempt 都不得创建第二条；
accepted 重放不得调用 Gateway；
rejected 重放不得调用 Gateway；
unknown 重放不得调用 Gateway；
blocked_before_submit 重放不得调用 Gateway；
failed_before_submit 重放不得调用 Gateway；
submitting 重放不得调用 Gateway；
人工重复触发与 Celery 重复投递遵守同一规则。
```

幂等意味着“重复调用不重复下单”，不意味着可以重新执行一次提交。

## 26. 并发与提交资格抢占

必须采用两段事务结构。

### 26.1 提交前事务

```text
开启数据库事务；
select_for_update 锁定 PreparedOrderIntent；
select_for_update 锁定 OrderPlanActiveLock；
读取或创建唯一 OrderSubmissionAttempt；
完成全部提交前校验；
将 attempt 推进为 submitting；
冻结 request payload 和 hash；
提交数据库事务。
```

如果已有 attempt，直接返回，不进入 Gateway。

### 26.2 外部调用

数据库抢占事务提交后，调用一次：

```text
BinanceOrderSubmissionGateway.submit_order(...)
```

不得在持有长事务或数据库行锁时等待 Binance 网络响应。

### 26.3 结果事务

```text
重新开启数据库事务；
锁定 OrderSubmissionAttempt、PreparedOrderIntent 和 ActiveLock；
根据 Gateway 证据分类结果；
保存脱敏响应和 hash；
推进状态；
写 AlertEvent；
提交事务。
```

如果外部调用完成但结果事务失败，恢复流程必须保守视为 `unknown`，不得再次提交。

## 27. submitting 卡住恢复

RuntimeGuard 必须识别长时间停留在 `submitting` 的 attempt。

RuntimeGuard 只创建或更新 `RuntimeGuardIssue` 并写 `AlertEvent`，不得修改 `OrderSubmissionAttempt`，不得调用 Gateway，也不得触发订单状态查询。

Execution 可以提供受控恢复入口。受控恢复必须：

```text
不得改回 created；
不得再次调用 Gateway；
不得假设请求未发送；
依据持久化提交证据标记 unknown 或保持阻断；
写 AlertEvent；
使用原 client_order_id 进入订单查询和人工核对。
```

受控恢复不得由 RuntimeGuard 自动触发。

监控阈值只决定何时报告卡住，不赋予重试权限。

## 28. ActiveLock 推进

固定规则：

```text
accepted
→ 保持 active，等待订单终态和成交同步完整；

unknown
→ 保持 active 或标记 failed 阻断，不得释放；

rejected
→ 明确未被接受后安全释放；

blocked_before_submit
→ request_sent=false 且无其他提交事实时安全释放；

failed_before_submit
→ request_sent=false 且无其他提交事实时安全释放；

submitting stale
→ 不释放。
```

accepted 后只有同时满足以下条件，后续模块才可以释放锁：

```text
OrderStatusSync 已确认明确终态；
FillSync 已完成成交查询；
TradeFill 已幂等落库；
OrderFillSummary 已生成并通过完整性检查；
无成交终态已明确记录 synced_empty；
所有证据属于同一 OrderSubmissionAttempt。
```

Execution 本身不得因为 MARKET 单“通常立即成交”而释放锁。

## 29. OrderStatusSync 交接

accepted 或 unknown 后，编排层必须把同一 `OrderSubmissionAttempt` 交给 OrderStatusSync。

交接信息至少包括：

```text
order_submission_attempt_id
market_type
account_domain
symbol
client_order_id
exchange_order_id（如已知）
trace_id
trigger_source
```

OrderStatusSync 使用 `BinanceOrderStatusGateway` 查询，不得调用订单提交接口。

当前查询边界：

```text
每 2 秒查询一次；
最多持续 30 秒；
查到明确终态后停止；
超时后停止自动轮询，但不释放 ActiveLock；
unknown 或 not_found 不触发重新提交。
```

Execution 只负责产生交接事实或事件，不在本模块内实现轮询。

## 30. 订单响应与完整生命周期边界

Gateway 提交响应中的 `exchange_status` 可以记录，但不能替代 OrderStatusSync。

以下状态由 OrderStatusSync 统一确认：

```text
NEW
PARTIALLY_FILLED
FILLED
CANCELED
REJECTED
EXPIRED
EXPIRED_IN_MATCH
```

以下事实由 FillSync 统一确认：

```text
逐笔 TradeFill；
累计成交数量；
平均成交价；
手续费；
成交完整性；
synced_empty；
OrderFillSummary。
```

Execution 不得直接根据提交响应生成或修改 BinancePositionSnapshot。

## 31. reason_code

至少支持：

```text
prepared_order_intent_not_found
prepared_order_intent_not_ready
prepared_order_intent_expired
execution_preparation_not_prepared
source_chain_mismatch
submission_time_before_source_fact
trace_context_missing
active_lock_missing
active_lock_not_active
active_lock_mismatch
market_identity_invalid
market_identity_mismatch
execution_disabled
real_trading_disabled
unsupported_execution_mode
unsupported_order_type
unsupported_position_mode
unsupported_position_side
unsupported_quantity_unit
invalid_frozen_order_request
frozen_evidence_mismatch
duplicate_submission_attempt
gateway_disabled
gateway_request_not_sent
submission_accepted
submission_rejected
submission_unknown
submission_blocked_before_send
submission_failed_before_send
stale_submitting
gateway_contract_violation
internal_error
```

reason_code 必须稳定，中文解释写入 `reason_message` 和 AlertEvent。

## 32. AlertEvent

必须写入：

```text
order_submission_accepted
order_submission_rejected
order_submission_unknown
order_submission_blocked_before_submit
order_submission_failed_before_submit
order_submission_stale_submitting
order_submission_idempotent_replay
order_submission_market_identity_mismatch
order_submission_real_trading_disabled
order_submission_gateway_contract_violation
```

最低字段：

```text
source_module = execution
trace_id
trigger_source
event_type
severity
reason_code
prepared_order_intent_id
execution_preparation_result_id
order_submission_attempt_id
approved_order_intent_id
order_plan_id
active_lock_id
market_type
account_domain
endpoint_family
symbol
side
quantity
quantity_unit
reduce_only
order_notional
client_order_id
status
request_sent
response_received
exchange_order_id
exchange_status
http_status
binance_error_code
gateway_attempt_count
```

通知必须明确区分“订单提交结果”和“最终成交状态”。accepted 不得描述为已成交。

## 33. 日志与敏感信息

结构化日志至少包含：

```text
trace_id
prepared_order_intent_id
order_submission_attempt_id
client_order_id
market_type
endpoint_family
status
request_sent
response_received
latency_ms
```

日志、数据库、AlertEvent 和异常信息均不得包含：

```text
API secret；
signature；
完整 API key；
完整认证 header；
包含敏感信息的请求 URL；
Gateway 内部 session 或 transport 对象。
```

## 34. 配置归属

以下部署级硬配置由 Binance Gateway 读取，Execution 不直接解析：

```text
BINANCE_GATEWAY_ENABLED
BINANCE_ACTIVE_MARKET_TYPE
BINANCE_API_ENVIRONMENT
BINANCE_ORDER_SUBMISSION_ENABLED
BINANCE_REAL_TRADING_ENABLED
```

base URL、交易凭据、recvWindow、超时、本地限频和熔断配置统一由 Binance Gateway 管理。MySQL 真实交易运行开关只由 OrderPlanStepAdapter 在进入 OrderPlan 前检查一次，Execution 不读取该开关。

以下重复配置不属于 Execution：

```text
ORDER_SUBMISSION_USDS_M_BASE_URL
ORDER_SUBMISSION_COIN_M_BASE_URL
ORDER_SUBMISSION_USDS_M_API_KEY
ORDER_SUBMISSION_COIN_M_API_KEY
ORDER_SUBMISSION_CONNECT_TIMEOUT_SECONDS
ORDER_SUBMISSION_READ_TIMEOUT_SECONDS
ORDER_SUBMISSION_RECV_WINDOW_MS
ORDER_SUBMISSION_LOCAL_RATE_LIMIT_PER_MINUTE
ORDER_SUBMISSION_MAX_PRICE_AGE_SECONDS
ORDER_SUBMISSION_MAX_PRICE_DEVIATION_BPS
```

所有环境配置必须进入 `.env.example` 并带中文注释，不得提交真实密钥。

## 35. Celery task 与 management command

Celery task 只能：

```text
解析 prepared_order_intent_id；
传递当前 OrchestrationRun / StepRun 已建立的 trace_id；
设置 trigger_source；
调用 submit_prepared_order；
输出结构化结果。
```

订单提交 task 必须禁用自动重试。

消息重复投递时，service 通过数据库幂等返回已有 attempt，不得再次调用 Gateway。

可提供受控 management command：

```text
python manage.py submit_order \
  --prepared-order-intent-id <id> \
  --trigger-source management_command
```

受控 management command 必须在命令入口创建新的技术追踪标签，并创建对应的受控人工操作记录或 OrchestrationRun 关联原 PreparedOrderIntent。命令不得接收调用者传入的旧 trace_id 冒充原自动调用。

command 不得：

```text
绕过真实交易硬开关；
传入密钥或 base URL；
重置既有 attempt；
把 unknown 改成 rejected；
再次提交同一 PreparedOrderIntent；
打印敏感请求参数。
```

## 36. 数据与外部服务

```text
读写 MySQL：是；
直接访问 Redis：否，Gateway 可按自身合同使用 Redis 限频；
访问 Binance：是，只通过 BinanceOrderSubmissionGateway；
发送 Hermes：否，只写 AlertEvent；
调用大模型：否；
涉及 FeatureLayer：否；
涉及 AtomicSignal：否；
涉及 DecisionSnapshot：只保留上游追溯，不读取其业务内容；
涉及 Binance Account Sync：只保留上游 sync_run 追溯，不重新同步；
涉及 PriceSnapshot：只校验冻结证据，不重新查价；
涉及 OrderPlan / CandidateOrderIntent：只保留上游追溯；
涉及 RiskCheck / ApprovedOrderIntent：只校验链路；
涉及 ExecutionPreparation：是，只消费 PreparedOrderIntent；
涉及真实交易：是，满足全部硬开关时提交一次；
涉及 OrderStatusSync / FillSync：只产生 OrderSubmissionAttempt 作为后续输入；
写 AlertEvent：是。
```

## 37. 异常处理总则

```text
能证明未发送的业务阻断 → blocked_before_submit；
能证明未发送的系统失败 → failed_before_submit；
Binance 明确接受 → accepted；
Binance 明确拒绝且未接受 → rejected；
其他无法确定的结果 → unknown。
```

确定性优先级：

```text
只有明确证据才能使用 accepted 或 rejected；
无法证明未发送时不能使用 failed_before_submit；
无法确认结果时统一使用 unknown；
unknown 永远不能自动转换成 rejected；
任何异常都不赋予重新提交权限。
```

## 38. 测试要求

自动化测试必须使用 fake Gateway，不得访问真实 Binance。

至少覆盖：

```text
1. 只消费 status=prepared 的 PreparedOrderIntent。
2. service 内部取得的当前 UTC 等于 expires_at_utc 时拒绝提交。
3. ExecutionPreparationResult 不是 PREPARED 时不提交。
4. 上游链路身份不一致时不提交。
5. ActiveLock 缺失、非 active 或不属于当前 OrderPlan 时不提交。
6. USDS-M 只使用 quantity 语义。
7. COIN-M 只使用 contracts 语义。
8. COIN-M contracts 不转换成 base 或 quote 数量。
9. 冻结订单链市场身份不一致时不调用 Gateway。
10. Gateway 根据 market_type 内部选择 fapi / dapi。
11. Execution 无法访问 adapter、transport、密钥或 endpoint path。
12. MARKET payload 不包含 price、stopPrice 或 timeInForce。
13. newClientOrderId 等于 PreparedOrderIntent.client_order_id。
14. idempotency_key 不发送给 Binance。
15. side、quantity、reduce_only 和 order_type 不被修改。
16. Execution 不查询 mark price、book ticker 或另一 PriceSnapshot。
17. price guard 证据 hash 不一致时不提交。
18. Binance Gateway 任一订单提交部署硬开关关闭时，Gateway 在发送前拒绝；Execution 不读取 MySQL 运行开关。
19. dry-run 不调用真实提交 Gateway；当前阶段不存在模拟交易提交路径。
20. 每个 PreparedOrderIntent 最多创建一个 attempt。
21. 两个并发调用最多一个进入 Gateway。
22. Celery 重复投递不重复调用 Gateway。
23. 人工重复触发不重复调用 Gateway。
24. Gateway 的 submit_order 最大调用次数为一次。
25. connect timeout 不重试并分类 unknown 或明确未发送失败。
26. read timeout 不重试并分类 unknown。
27. HTTP 429 不重试。
28. HTTP 5xx 不重试。
29. 明确参数拒绝不重试。
30. 提交前配置错误不允许复用 PreparedOrderIntent。
31. Gateway attempt_count 必须等于 1。
32. accepted 保存交易所标识并保持 ActiveLock。
33. accepted 不生成 TradeFill，也不生成或修改 BinancePositionSnapshot。
34. rejected 明确未接单时安全释放 ActiveLock。
35. unknown 不释放 ActiveLock。
36. unknown 重放不重新提交。
37. stale submitting 不重新提交并转入查询或人工处理。
38. blocked_before_submit 的 request_sent=false。
39. failed_before_submit 的 request_sent=false。
40. 无法证明 request_sent=false 时使用 unknown。
41. accepted / unknown 交给 OrderStatusSync。
42. rejected / pre-submit failure 不触发订单轮询。
43. OrderStatusSync 30 秒超时不释放 ActiveLock。
44. 提交响应中的 FILLED 不直接释放 ActiveLock。
45. request 和 response 持久化内容均已脱敏。
46. 日志与 AlertEvent 不包含 secret、signature 或完整 API key。
47. 所有正式结果写 AlertEvent。
48. 不调用 Hermes 或大模型。
49. 正式服务入口不接受调用方传入业务判断时间。
50. submission_time_utc 早于 PreparedOrderIntent 或 ExecutionPreparationResult 的事实时间时不提交。
51. Execution 不读取 MySQL 真实交易运行开关，也不在报单前重复执行运行权限检查。
52. USDS-M 使用冻结数量乘 selected_live_price 记录订单名义。
53. COIN-M 使用冻结 contracts 乘 contract_size 记录订单名义。
54. 订单名义只用于事实记录和审计，不在 Execution 形成新的运行时金额上限。
55. position_mode 不是 one_way 或 position_side 不是 BOTH 时不提交。
56. trace_id 来自当前技术调用上下文，只进入 StepRun、attempt、AlertEvent、Gateway 元数据、日志和下游技术交接。
57. Celery task 不新建 trace_id；受控人工命令建立新的技术追踪并关联原业务对象。
58. Execution 使用冻结订单链的市场身份，不读取当前全局市场配置替换它。
```

## 39. 验收标准

满足以下条件才算完成：

```text
Execution 是唯一可以调用 BinanceOrderSubmissionGateway 的业务模块；
只消费有效、未过期且唯一的 PreparedOrderIntent；
不重复执行 ExecutionPreparation 或 price guard；
不信任业务层传入的 endpoint path 或 adapter；
Gateway 根据 market_type 管理 fapi / dapi 路由；
USDS-M 与 COIN-M 数量语义清楚且不可混用；
真实交易部署硬权限和 MySQL 运行开关默认关闭，且在进入 OrderPlan 前检查一次；
Execution 不重复读取真实交易运行开关；
Execution 使用冻结订单链的市场身份，不使用当前全局配置覆盖历史事实；
订单名义只用于事实记录和审计，不在本模块新增运行时金额上限；
生产提交时间由 service 内部取得，调用方不能通过回拨时间绕过过期；
One-Way Mode 下只接受 position_side = BOTH；
每份 PreparedOrderIntent 最多调用一次 submit_order；
Gateway、Execution、Celery、编排、命令和人工入口均不重试提交；
提交前明确失败也不复用本次 PreparedOrderIntent；
accepted、rejected、unknown 和提交前失败分类确定；
request_sent、response_received 和 attempt_count 可审计；
accepted 不代表成交；
unknown 不重试、不解锁；
明确 rejected 和明确未发送可以安全解锁；
accepted / unknown 进入 OrderStatusSync；
订单终态和成交完整前不释放已接受订单的锁；
所有结果写 MySQL、AlertEvent 和结构化日志；
trace_id 只用于提交技术追踪，不作为订单业务外键或幂等键；
密钥、签名和敏感 header 不进入业务存储；
本模块不撤单、不查成交、不改仓位、不调用大模型。
```

## 40. 当前不包含的能力

```text
订单提交重试；
自动补单或缩单；
批量订单；
限价、止损、止盈或追踪止损订单；
撤单与改单；
订单状态同步实现；
成交同步实现；
User Data Stream；
根据提交响应直接更新持仓；
多 active domain；
多账户；
其他交易所；
模拟撮合；
大模型交易判断。
```
