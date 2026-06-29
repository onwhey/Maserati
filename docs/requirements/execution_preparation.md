# ExecutionPreparation 需求

## 1. 模块定位

ExecutionPreparation 位于风控审批与订单提交之间：

```text
RiskCheck
→ ApprovedOrderIntent
→ ExecutionPreparation
→ ExecutionPreparationResult
→ PreparedOrderIntent
→ Execution
```

本模块把已经通过风控的订单意图，经过执行前最终校验后，冻结为唯一、幂等、短期有效且可审计的待提交请求。

本模块不得真实下单。只有 Execution 可以把 `PreparedOrderIntent` 提交给 Binance。

## 2. 核心目标

本模块必须完成：

```text
校验 ApprovedOrderIntent 及其完整上游链路；
校验 ApprovedOrderIntent 业务链明确引用的 PriceSnapshot；
校验 RiskCheck 使用的 BinanceSyncRun 仍可消费；
复核 RiskCheck 已批准并明确绑定的持仓事实、reduce-only 和交易规则语义；
通过 BinancePublicMarketGateway 单独查询一次实时盘口价格；
按订单方向选择最接近市价单执行侧的价格；
将实时盘口价格与上游明确引用的 mark price 比较；
价格偏差小于或等于 1% 时允许继续；
价格偏差大于 1% 时阻断；
冻结交易所可提交参数；
生成稳定的 client_order_id 和 idempotency_key；
生成短期有效的 PreparedOrderIntent；
记录结构化结果、证据和 AlertEvent。
```

## 3. 不负责事项

本模块不负责：

```text
重新判断是否应该交易；
重新计算目标仓位；
生成或修改 CandidateOrderIntent；
重新执行 RiskCheck；
缩小、放大、拆分或反转订单；
选择 RiskCheck 未批准的订单；
创建新的 PriceSnapshot；
覆盖上游明确引用的 PriceSnapshot；
自动创建新的 BinanceSyncRun；
隐式选择数据库中的最新账户同步批次；
提交、撤销或修改交易所订单；
查询订单状态或成交；
比较最终成交价与 mark price；
更新真实持仓；
修改杠杆、保证金模式或持仓模式；
接入 WebSocket；
直接发送 Hermes；
调用大模型。
```

盘口查询只用于执行前 price guard，不是交易决策，也不是成交事实。

## 4. 输入合同

正式入口：

```text
prepare_execution(
    approved_order_intent_id,
    business_request_key,
    reference_time_utc,
    trace_id,
    trigger_source,
)
```

正式输入至少包括：

```text
approved_order_intent_id
business_request_key
reference_time_utc
trace_id
trigger_source
```

`reference_time_utc` 必须是 UTC aware datetime。生产环境由 service 获取当前 UTC；测试和受控管理命令可以显式传入。

当前阶段不实现 dry-run，不生成预览版 ExecutionPreparationResult、PreparedOrderIntent 或 client_order_id。

### 4.1 reference_time_utc 边界

`reference_time_utc` 是本次执行准备用于判断上游事实有效期的统一时间点。

它不得早于以下已绑定事实的产生时间：

```text
ApprovedOrderIntent 创建时间；
RiskCheckResult 完成时间；
PriceSnapshot.as_of_utc；
BinanceSyncRun 完成时间。
```

如果早于任一关键事实，必须：

```text
status = BLOCKED
reason_code = reference_time_before_source_fact
```

本模块不得使用服务器本地时区修正、回拨或猜测业务时间。

### 4.2 trace_id 技术边界

同一次自动编排进入 ExecutionPreparation 时，必须继承该次技术调用已经建立的 trace_id，不得在本模块内另行生成一条与原调用无关的追踪链。

trace_id 只用于：

```text
ExecutionPreparationResult 技术执行记录；
AlertEvent；
Binance Gateway 调用上下文与返回元数据；
任务日志和异常日志。
```

trace_id 不是业务外键，不参与幂等，不用于判断业务对象是否属于同一轮，也不能代替 OrchestrationRun 关联表和真实业务外键。

PreparedOrderIntent 不需要重复保存 trace_id。需要排查其生成过程时，通过 execution_preparation_result_id 读取对应技术执行记录和 AlertEvent。

人工诊断或独立恢复必须建立新的技术追踪链，并通过对应的 OrchestrationRun 或受控恢复记录关联原业务对象，不得冒充原自动调用继续执行。

正式自动链路缺少 trace_id 时，本模块不得自行补造，必须返回 `FAILED`，并使用 `trace_context_missing` 说明技术审计上下文不完整。

## 5. ApprovedOrderIntent 前置条件

必须确认：

```text
ApprovedOrderIntent 存在；
状态允许进入执行准备；
尚未过期、取消或被消费；
绑定有效 RiskCheckResult；
RiskCheckResult.status = ALLOW；
绑定实际获批的 CandidateOrderIntent；
绑定有效 OrderPlan；
绑定 OrderPlan 和 RiskCheck 使用的 PriceSnapshot；
绑定 RiskCheck 使用的 BinanceSyncRun；
绑定有效 OrderPlanActiveLock；
订单链路尚未终结；
不存在已经开始的 Execution 或 OrderSubmissionAttempt。
```

任一业务前置条件不成立时必须 `BLOCKED`，不得生成 `PreparedOrderIntent`。

上游引用损坏、数据库异常或无法判断是否已进入 Execution 时必须 `FAILED`，不得继续提交链路。

## 6. 链路身份一致性

以下身份必须在 OrderPlan、CandidateOrderIntent、RiskCheckResult、ApprovedOrderIntent、PriceSnapshot、BinanceSyncRun 和 ActiveLock 之间一致：

```text
exchange
market_type
account_domain
symbol
order_plan_id
candidate_order_intent_id
risk_check_result_id
price_snapshot_id
binance_sync_run_id
```

不得根据 symbol 推测市场域，不得把 USDS-M 与 COIN-M 对象混用，不得读取上游业务链未明确引用的价格或账户事实。

身份不一致时：

```text
status = BLOCKED
reason_code = source_chain_mismatch 或 market_identity_mismatch
```

## 7. PriceSnapshot 消费合同

ExecutionPreparation 必须读取 ApprovedOrderIntent、RiskCheckResult 和 OrderPlan 明确引用的同一 `PriceSnapshot`。

必须校验：

```text
PriceSnapshot 存在；
price_type = mark_price；
mark_price > 0；
price_snapshot_hash 可验证；
exchange、market_type、account_domain 和 symbol 一致；
reference_time_utc 不晚于 expires_at_utc；
PriceSnapshot 未被撤销或标记为不可消费。
```

本模块不得：

```text
请求 PriceSnapshot 模块刷新价格；
为同一业务链生成第二份 PriceSnapshot；
因 PriceSnapshot 过期而回退到其他价格对象；
使用 Redis 中无法追溯到该 PriceSnapshot 的裸价格；
把本次盘口查询结果写回 PriceSnapshot。
```

PriceSnapshot 的 10 分钟 TTL 是该 mark price 事实的有效期。本模块不要求该 mark price 必须在 30 秒内生成，执行时点的实时性由本次独立盘口查询补充。

## 8. 实时盘口价格查询

### 8.1 唯一访问路径

ExecutionPreparation 必须调用：

```text
BinancePublicMarketGateway.get_book_ticker(market_type, symbol, call_context)
```

不得自行创建 Binance HTTP client、拼接 endpoint、维护签名、配置 base URL 或直接调用 Binance SDK。

本次查询是公共只读请求，不使用账户 API key，不获得订单提交权限。

### 8.2 调用上下文

调用上下文至少包括：

```text
trace_id
trigger_source
operation = get_book_ticker
market_type
account_domain
symbol
business_object_type = ApprovedOrderIntent
business_object_id = approved_order_intent_id
business_request_key
request_time_utc
```

Gateway 返回的请求时间、完成时间、延迟、尝试次数、endpoint family 和限频元数据必须进入执行准备证据。

### 8.3 不使用缓存价格

`get_book_ticker` 必须在本次 ExecutionPreparation 中发起实际 Binance 请求。

禁止：

```text
使用上一次 ExecutionPreparation 的盘口结果；
使用 PriceSnapshot Redis 缓存代替盘口查询；
使用 K 线 close、index price 或 last price 代替盘口价格；
把 Gateway 内部缓存结果当作本次实时查询；
查询失败时回退到上游 mark price 并继续。
```

Gateway 可以按安全读取规则对技术异常执行有限重试，但业务层不得在一次准备失败后无界重复查询。

## 9. 按订单方向选择价格

市价单的执行侧参考价格定义为：

```text
BUY  → best_ask_price
SELL → best_bid_price
```

原因：

```text
BUY 市价单会主动吃卖盘，best ask 比 last price 更接近当前可买价格；
SELL 市价单会主动吃买盘，best bid 比 last price 更接近当前可卖价格。
```

本模块必须同时保留：

```text
best_bid_price
best_bid_quantity
best_ask_price
best_ask_quantity
selected_live_price
selected_live_price_side
```

其中：

```text
selected_live_price_side = ask，适用于 BUY；
selected_live_price_side = bid，适用于 SELL。
```

以下任一情况必须阻断：

```text
Gateway 未成功返回；
response_received = false；
symbol 或 market_type 不一致；
bid 或 ask 缺失、无法解析或不大于零；
best_ask_price < best_bid_price；
订单 side 不是 BUY 或 SELL；
响应结构无法验证。
```

典型 reason_code：

```text
live_price_unavailable
live_price_invalid
live_price_market_identity_mismatch
unsupported_order_side
```

## 10. Price guard

### 10.1 比较价格

```text
reference_mark_price = PriceSnapshot.mark_price

selected_live_price =
    best_ask_price，当 side = BUY
    best_bid_price，当 side = SELL
```

### 10.2 计算公式

```text
price_deviation_ratio
= abs(selected_live_price - reference_mark_price)
  / reference_mark_price

price_deviation_bps
= price_deviation_ratio * 10000
```

必须使用 Decimal 或等价精确十进制计算，不得使用二进制浮点数决定阈值边界。

### 10.3 阈值规则

默认配置：

```text
EXECUTION_PREPARATION_MAX_PRICE_DEVIATION_BPS = 100
```

即：

```text
价格偏差 < 1%  → 允许继续；
价格偏差 = 1%  → 允许继续；
价格偏差 > 1%  → BLOCKED。
```

无论价格变化对订单看起来有利还是不利，都使用绝对偏差执行相同规则。ExecutionPreparation 不得自行判断“有利滑点可以忽略”。

超出阈值时：

```text
ExecutionPreparationResult.status = BLOCKED
reason_code = live_price_deviation_exceeded
不得生成 PreparedOrderIntent
不得修改订单数量或方向
不得改用其他 PriceSnapshot
写 AlertEvent
```

阈值比较必须明确使用 `>`。实现不得把等于 100 bps 误判为阻断。

## 11. 价格证据边界

本次盘口查询结果是 `ExecutionPreparationResult` 的执行前证据，不是新的 `PriceSnapshot`。

必须记录：

```text
price_snapshot_id
price_snapshot_hash
reference_mark_price
mark_price_observed_at_utc
mark_price_expires_at_utc
best_bid_price
best_bid_quantity
best_ask_price
best_ask_quantity
selected_live_price
selected_live_price_side
live_price_requested_at_utc
live_price_observed_at_utc
price_deviation_ratio
price_deviation_bps
price_deviation_limit_bps
gateway_attempt_count
gateway_latency_ms
gateway_endpoint_family
```

最终成交价、平均成交价、滑点和成交后偏差由 Execution、FillSync、Tracking 或 Review 的对应合同定义，本模块不得把盘口价格写成实际成交价。

## 12. BinanceSyncRun 消费合同

ExecutionPreparation 必须复用并明确读取 RiskCheck 已绑定的 `binance_sync_run_id`。

必须校验：

```text
BinanceSyncRun 存在；
sync_purpose = trade_preparation；
status = succeeded；
批次尚未过期；
snapshot_set_hash 可验证；
exchange、market_type 和 account_domain 一致；
账户、目标 symbol 持仓和 symbol rule 快照完整。
```

本模块不自动生成执行前复核批次，也不选择数据库中的 `latest succeeded`。

禁止使用：

```text
上游业务链未明确引用的批次；
ops_display 批次；
过期批次；
失败或部分成功批次；
调用方未显式绑定的更新批次。
```

如以后需要在报单前重新同步账户，必须先在 BinanceAccountSync 和编排合同中定义新的显式同步目的与绑定规则，不得在本模块内偷偷读取“最新账户”。

## 13. 账户与持仓复核

本模块基于 RiskCheck 使用的同一 BinanceSyncRun 复核已批准的账户与持仓事实：

```text
position_mode
margin_mode
observed_exchange_leverage
normalized_position_side
position_amount
balance snapshot identity
symbol rule identity
```

复核目标是确认：

```text
PreparedOrderIntent 冻结的订单语义仍与已批准事实一致；
读取到的快照未过期、未损坏、未被替换；
ApprovedOrderIntent 没有引用另一批账户事实；
持仓方向和数量与 RiskCheck 证据一致。
```

本模块不声称同一旧批次能够发现 Binance 上在 RiskCheck 后发生的新变化。需要更新账户事实时必须由编排层显式创建并绑定受支持的同步批次。

因此，本节所称“持仓复核”只表示核对已绑定快照与获批证据是否一致，不表示本模块已经重新查询 Binance 当前持仓。

以下任一情况必须阻断：

```text
账户批次不可消费；
账户或持仓快照缺失；
持仓方向与获批证据不一致；
持仓数量与获批证据不一致；
position_mode 不是受支持模式；
保证金模式、杠杆观测值或规则 hash 与获批证据不一致。
```

Decimal 格式等价不视为数量变化，例如 `0.0100` 与 `0.01` 等价。

## 14. reduce-only 复核

当 `reduce_only = true` 时必须满足：

```text
存在可被减少的对应持仓；
绑定持仓快照中的持仓绝对数量大于零；
订单数量不大于可减少持仓数量；
side 是减少该持仓的方向；
position_side 与绑定持仓快照中的持仓语义一致。
```

不满足时：

```text
status = BLOCKED
reason_code = reduce_only_invalid
```

本模块不得因为持仓事实不满足而：

```text
取消 reduce_only；
缩小数量；
改变 side；
把平仓变成反手；
把反手变成单边开仓。
```

## 15. 交易规则复核

规则来源只能是同一 BinanceSyncRun 内的 `BinanceSymbolRuleSnapshot`。

必须复核：

```text
symbol 和 market_type；
supported_order_types；
quantity > 0；
quantity_unit；
quantity_precision；
step_size；
min_quantity；
max_quantity；
min_notional；
max_notional（如交易所提供）；
contract_size（COIN-M）；
rule_hash。
```

对 MARKET 单进行当前名义价值复核时：

```text
USDS-M estimated_notional
= quantity * selected_live_price

COIN-M estimated_notional_usd
= contracts * contract_size
```

如果数量或当前估算名义价值违反规则，必须 `BLOCKED`，不得自动调整数量。

## 16. 支持的订单合同

当前支持：

```text
order_type = MARKET
order_type = LIMIT
position_mode = one_way
position_side = BOTH
```

数量单位组合：

```text
usds_m_futures → quantity
coin_m_futures → contracts
```

MARKET 单不得发送 `timeInForce`。

PreparedOrderIntent 中可以记录：

```text
time_in_force = null 或 not_applicable
```

LIMIT 单必须冻结：

```text
limit_price；
limit_valid_until_utc；
time_in_force；
price_condition_hash；
price_condition_evidence_refs。
```

LIMIT 单的 `limit_valid_until_utc` 必须来自上游 CandidateOrderIntent / ApprovedOrderIntent，不得由 ExecutionPreparation 临时延长。若执行准备时已经晚于或等于 `limit_valid_until_utc`，必须 BLOCKED，不得生成 PreparedOrderIntent。

`selected_live_price` 仍只用于 price guard、名义复核和审计。对于 LIMIT 单，`selected_live_price` 不得覆盖 `limit_price`。

不支持的订单类型、持仓模式、position_side 或数量单位必须阻断，不得临时转换。

## 17. 交易所参数冻结

成功后至少冻结：

```text
exchange
market_type
account_domain
symbol
side
position_side
position_mode
order_type
quantity
quantity_unit
reduce_only
time_in_force
limit_price
limit_valid_until_utc
price_condition_hash
client_order_id
idempotency_key
```

冻结值必须来自获批的 CandidateOrderIntent，不得由本模块重新规划。

`selected_live_price` 只用于 price guard 和审计。MARKET 单不得发送 limit price；LIMIT 单只能发送已冻结的 `limit_price`，不得用 `selected_live_price` 替换。

## 18. ExecutionPreparationResult

每个 `ApprovedOrderIntent` 只能有一份正式 `ExecutionPreparationResult`。

至少记录：

```text
id
execution_preparation_key
status
reason_code
reason_message
business_request_key
approved_order_intent_id
risk_check_result_id
candidate_order_intent_id
order_plan_id
active_lock_id
price_snapshot_id
price_snapshot_hash
binance_sync_run_id
binance_snapshot_set_hash
account_snapshot_id
position_snapshot_id
symbol_rule_snapshot_id
reference_mark_price
best_bid_price
best_ask_price
selected_live_price
selected_live_price_side
price_deviation_ratio
price_deviation_bps
price_deviation_limit_bps
live_price_requested_at_utc
live_price_observed_at_utc
gateway_result_metadata
config_snapshot
input_hash
evidence
alert_event_ids
trace_id
trigger_source
started_at_utc
finished_at_utc
created_at_utc
updated_at_utc
```

正式状态：

```text
PREPARING
PREPARED
BLOCKED
FAILED
EXPIRED
```

含义：

```text
PREPARING：已占用本 ApprovedOrderIntent 的唯一准备资格，正在执行检查；
PREPARED：全部检查通过并生成 PreparedOrderIntent；
BLOCKED：业务事实不允许安全继续；
FAILED：系统异常或结果无法可靠判断；
EXPIRED：已经生成的 PreparedOrderIntent 超过有效期且未进入提交。
```

幂等重放是调用响应语义，不把已持久化的 `PREPARED` 改写成另一个终态。

## 19. PreparedOrderIntent

只有 `ExecutionPreparationResult.status = PREPARED` 才能生成 `PreparedOrderIntent`。

至少记录：

```text
id
prepared_order_intent_key
execution_preparation_result_id
source_approved_order_intent_id
source_risk_check_result_id
source_candidate_order_intent_id
source_order_plan_id
exchange
market_type
account_domain
symbol
position_mode
position_side
side
order_type
quantity
quantity_unit
reduce_only
time_in_force
client_order_id
idempotency_key
price_snapshot_id
reference_mark_price
selected_live_price
price_deviation_bps
binance_sync_run_id
account_snapshot_id
position_snapshot_id
symbol_rule_snapshot_id
prepared_at_utc
expires_at_utc
status
trigger_source
config_snapshot
evidence_hash
created_at_utc
updated_at_utc
```

PreparedOrderIntent 表示尚未提交交易所的待执行请求。它不表示 Binance 已接收订单，也不表示已经成交。

## 20. PreparedOrderIntent 有效期

默认配置：

```text
PREPARED_ORDER_INTENT_TTL_SECONDS = 30
```

有效期计算：

```text
expires_at_utc = min(
    live_price_observed_at_utc + 30 秒,
    ApprovedOrderIntent.expires_at_utc,
    PriceSnapshot.expires_at_utc,
    BinanceSyncRun.expires_at_utc,
)
```

30 秒有效窗口从本次实时盘口价格被成功观测的时间开始，不从数据库写入完成时间重新计时。

LIMIT 单还必须满足：

```text
expires_at_utc <= limit_valid_until_utc
```

PreparedOrderIntent 的 30 秒有效期只限制“提交动作必须尽快发生”，不表示限价单在交易所的挂单有效期。限价单挂单有效期由 `limit_valid_until_utc` 和后续订单周期收尾流程约束。

如果准备过程消耗了部分时间，PreparedOrderIntent 只能使用剩余有效时间。如果计算出的 `expires_at_utc <= prepared_at_utc`，本次准备必须阻断。

Execution 在发送任何订单请求前必须再次确认：

```text
PreparedOrderIntent.status = prepared；
当前 UTC 时间 < expires_at_utc；
不存在既有 OrderSubmissionAttempt；
ActiveLock 仍属于本订单链路。
```

过期后不得：

```text
改回 prepared；
继续提交；
为同一 ApprovedOrderIntent 创建第二份 PreparedOrderIntent；
自动重新查询价格并恢复；
自动重走 RiskCheck。
```

## 21. client_order_id

必须为每个 ApprovedOrderIntent 生成唯一且稳定的 `client_order_id`。

规则：

```text
同一 ApprovedOrderIntent 重放时保持不变；
不同 ApprovedOrderIntent 不得重复；
符合 Binance 长度和字符约束；
能够追溯系统订单链路；
生成后不得因阻断、失败或过期而复用；
不得包含密钥或敏感账户信息。
```

冲突时必须 `FAILED`，不得进入 Execution。

## 22. 幂等性与并发

数据库唯一约束至少包括：

```text
ExecutionPreparationResult.approved_order_intent_id unique
ExecutionPreparationResult.execution_preparation_key unique
PreparedOrderIntent.source_approved_order_intent_id unique
PreparedOrderIntent.prepared_order_intent_key unique
PreparedOrderIntent.client_order_id unique
PreparedOrderIntent.idempotency_key unique
```

`idempotency_key` 至少绑定：

```text
business_request_key
approved_order_intent_id
risk_check_result_id
candidate_order_intent_id
order_plan_id
price_snapshot_id
binance_sync_run_id
symbol
market_type
account_domain
side
position_side
quantity
quantity_unit
reduce_only
order_type
limit_price
limit_valid_until_utc
price_condition_hash
```

实时盘口返回值不参与幂等 key；它属于该唯一准备结果的证据。

并发控制使用：

```text
数据库事务；
select_for_update；
唯一约束；
IntegrityError 后读取已有结果。
```

同一 ApprovedOrderIntent 并发调用时，只允许一条调用进入实际准备和盘口查询。其他调用返回已有结果或明确的进行中状态，不得生成第二份 PreparedOrderIntent。

重放规则：

```text
已有 PREPARED 且未过期 → 返回同一 PreparedOrderIntent，响应标记 IDEMPOTENT_REPLAY；
已有 BLOCKED 或 FAILED → 返回原结果，不重新查询价格；
已有 EXPIRED → 返回原过期结果，不创建新对象；
已有 PreparedOrderIntent 已进入 submitted → 不重新准备；
已有 PREPARING 长时间未完成 → 不自动接管，进入人工或专用恢复流程。
```

## 23. ActiveLock

ExecutionPreparation 必须通过统一 `OrderPlanActiveLockService` 校验和推进锁，不得直接更新锁表。

进入准备前必须确认：

```text
ActiveLock.status = active；
active_order_plan_id 等于当前 OrderPlan；
exchange、market_type、account_domain 和 symbol 一致；
不存在另一条订单链路持有同一业务身份的锁。
```

状态规则：

```text
PREPARED → ActiveLock 保持 active；
BLOCKED → 确认尚未生成 PreparedOrderIntent、尚未进入 Execution 后安全释放；
FAILED → ActiveLock 进入 failed 或继续阻断，等待人工确认；
EXPIRED → 在行锁内确认从未提交后安全释放；
IDEMPOTENT_REPLAY → 不重复推进锁。
```

如果无法证明没有开始订单提交，禁止释放 ActiveLock。

## 24. 状态推进

成功时：

```text
ExecutionPreparationResult.status = PREPARED
PreparedOrderIntent.status = prepared
ApprovedOrderIntent.status = execution_prepared
OrderPlan 保持订单链路进行中
ActiveLock 保持 active
```

业务阻断时：

```text
ExecutionPreparationResult.status = BLOCKED
不生成 PreparedOrderIntent
ApprovedOrderIntent.status = preparation_blocked
OrderPlan.status = preparation_blocked
安全释放 ActiveLock
```

系统失败时：

```text
ExecutionPreparationResult.status = FAILED
不允许进入 Execution
ApprovedOrderIntent.status = preparation_failed
OrderPlan.status = preparation_failed
ActiveLock 保持阻断或进入 failed
```

PreparedOrderIntent 过期时：

```text
PreparedOrderIntent.status = expired
ExecutionPreparationResult.status = EXPIRED
ApprovedOrderIntent.status = preparation_expired
OrderPlan.status = preparation_expired
确认未提交后安全释放 ActiveLock
```

## 25. reason_code

至少支持：

```text
approved_order_intent_not_found
approved_order_intent_not_ready
approved_order_intent_expired
source_chain_mismatch
market_identity_mismatch
reference_time_before_source_fact
trace_context_missing
active_lock_missing
active_lock_not_active
active_chain_conflict
price_snapshot_missing
price_snapshot_expired
price_snapshot_invalid
price_snapshot_identity_mismatch
live_price_unavailable
live_price_invalid
live_price_market_identity_mismatch
live_price_deviation_exceeded
binance_sync_run_missing
binance_sync_run_expired
binance_sync_run_not_consumable
account_snapshot_unavailable
position_snapshot_unavailable
position_side_changed
position_amount_changed
reduce_only_invalid
symbol_rule_unavailable
symbol_rule_changed
exchange_rule_violation
unsupported_order_type
unsupported_position_mode
unsupported_quantity_unit
unsupported_order_side
prepared_request_conflict
client_order_id_conflict
prepared_order_intent_expired
internal_error
```

reason_code 必须稳定；中文解释写入 `reason_message` 和 AlertEvent。

## 26. AlertEvent 与审计

所有正式结果都必须写 AlertEvent。

至少包括：

```text
execution_preparation_prepared
execution_preparation_blocked
execution_preparation_failed
execution_preparation_expired
execution_preparation_idempotent_replay
execution_preparation_live_price_unavailable
execution_preparation_price_deviation_exceeded
execution_preparation_active_chain_conflict
execution_preparation_account_fact_invalid
execution_preparation_position_invalid
execution_preparation_reduce_only_invalid
execution_preparation_exchange_rule_violation
```

最低审计字段：

```text
trace_id
trigger_source
event_type
severity
reason_code
approved_order_intent_id
execution_preparation_result_id
prepared_order_intent_id
order_plan_id
candidate_order_intent_id
risk_check_result_id
active_lock_id
symbol
market_type
account_domain
price_snapshot_id
binance_sync_run_id
reference_mark_price
best_bid_price
best_ask_price
selected_live_price
selected_live_price_side
price_deviation_bps
price_deviation_limit_bps
client_order_id
idempotency_key
config_snapshot
```

通知必须明确写成“执行前检查”，不得写成订单已经提交或成交。

## 27. 配置

所有配置必须进入 `.env.example` 并带中文注释：

```text
EXECUTION_PREPARATION_ENABLED
EXECUTION_PREPARATION_MAX_PRICE_DEVIATION_BPS=100
PREPARED_ORDER_INTENT_TTL_SECONDS=30
EXECUTION_PREPARATION_SUPPORTED_ORDER_TYPES=MARKET,LIMIT
EXECUTION_PREPARATION_SUPPORTED_POSITION_MODE=one_way
```

实时盘口请求的 base URL、超时、有限重试、限频和熔断配置统一属于 Binance Gateway，不在本模块重复配置。

每次执行准备必须把实际使用的阈值和 TTL 写入 `config_snapshot`。配置在一条订单链路中不得热变更。

## 28. service、task 与 command

核心逻辑必须位于 ExecutionPreparation application service / domain service。

Celery task 或 management command 只能：

```text
解析 approved_order_intent_id；
传递调用入口已经建立的 trace_id；
设置 trigger_source；
调用 prepare_execution；
输出结构化摘要。
```

task、command、view 和 serializer 不得实现 price guard、幂等、状态推进或锁逻辑，也不得直接调用 Binance Gateway。

## 29. 数据与外部服务

```text
读写 MySQL：是；
访问 Redis：不作为必要事实来源，不直接依赖 Redis 裸价格；
访问 Binance：是，只通过 BinancePublicMarketGateway.get_book_ticker；
访问签名账户接口：否；
访问订单提交接口：否；
发送 Hermes：否，只写 AlertEvent；
调用大模型：否；
涉及交易执行：只准备，不提交；
允许真实交易：否。
```

## 30. 异常处理

分类原则：

```text
业务事实不满足安全条件 → BLOCKED；
Binance 实时盘口不可获得或不可验证 → BLOCKED；
明确超过 1% → BLOCKED；
数据库、代码或结构化结果出现不可预期异常 → FAILED；
无法确认是否已经进入 Execution → FAILED 且锁继续阻断。
```

禁止：

```text
静默吞异常；
把 Gateway 错误当作价格未变化；
把请求失败当作 0 偏差；
失败后自动生成第二个 client_order_id；
失败后自动释放无法确认安全性的锁；
在日志或 AlertEvent 中记录密钥、签名或认证 header。
```

## 31. 测试要求

自动化测试必须使用 fake gateway，不得访问真实 Binance。

至少覆盖：

```text
1. 只消费有效 ApprovedOrderIntent。
2. 上游业务外键或市场身份不一致时被阻断。
3. 只读取 OrderPlan 与 RiskCheck 明确引用的 PriceSnapshot。
4. PriceSnapshot 过期时阻断，不创建第二份快照。
5. 复用 RiskCheck 明确绑定的 BinanceSyncRun。
6. 不选择 latest succeeded 或 ops_display 批次。
7. BUY 调用 book ticker 后选择 best ask。
8. SELL 调用 book ticker 后选择 best bid。
9. 不使用 last price、index price 或 K 线 close。
10. book ticker 查询失败时阻断。
11. bid / ask 缺失、非正数或 ask 小于 bid 时阻断。
12. Gateway 返回 symbol 或 market_type 不一致时阻断。
13. 偏差 0% 时通过。
14. 偏差 0.9999% 时通过。
15. 偏差恰好 1% 时通过。
16. 偏差大于 1% 时阻断。
17. 上涨和下跌均按绝对偏差检查。
18. 阈值计算使用 Decimal。
19. 盘口结果不创建或覆盖 PriceSnapshot。
20. 盘口结果完整写入执行准备证据。
21. 持仓方向或数量证据不一致时阻断。
22. reduce-only 不成立时阻断。
23. 交易规则不满足时阻断且不改数量。
24. USDS-M quantity 路径正确。
25. COIN-M contracts 与 contract_size 路径正确。
26. 支持 MARKET / LIMIT、One-Way Mode 和 position_side = BOTH；MARKET 不发送 timeInForce，LIMIT 必须冻结 timeInForce 与 limit_price。
27. 成功只生成一份 PreparedOrderIntent。
28. PreparedOrderIntent 与 ApprovedOrderIntent 一对一。
29. client_order_id 和 idempotency_key 唯一且稳定。
30. 同一 ApprovedOrderIntent 并发调用只有一次进入盘口查询。
31. 幂等重放返回同一 PreparedOrderIntent，不重新查价。
32. 30 秒 TTL 从实时盘口价格观测时间开始，并受上游事实到期时间限制。
33. 过期对象不能恢复或提交。
34. PREPARED 后 ActiveLock 保持 active。
35. BLOCKED 仅在确认未提交后释放 ActiveLock。
36. FAILED 且安全性不明时 ActiveLock 继续阻断。
37. 所有正式结果写 AlertEvent。
38. 不调用 BinanceOrderSubmissionGateway。
39. 不创建 OrderSubmissionAttempt、OrderStatusSyncRecord 或 TradeFill。
40. 不修改 side、quantity、reduce_only、杠杆或保证金模式。
41. reference_time_utc 早于任一上游关键事实时 BLOCKED。
42. 当前阶段不提供 dry-run。
43. trace_id 进入 ExecutionPreparationResult、AlertEvent、Gateway 元数据和日志，但不重复写入 PreparedOrderIntent。
44. 正式自动链路缺少 trace_id 时 FAILED，且本模块不自行生成替代值。
45. 持仓复核只核对已绑定账户快照，不宣称已重新查询 Binance 当前持仓。
46. LIMIT 单的 limit_valid_until_utc 已过期时 BLOCKED。
47. LIMIT 单的 PreparedOrderIntent.expires_at_utc 不得晚于 limit_valid_until_utc。
48. LIMIT 单不得用 selected_live_price 覆盖 limit_price。
49. limit_price、limit_valid_until_utc 和 price_condition_hash 进入幂等键。
```

## 32. 验收标准

满足以下条件才算完成：

```text
ExecutionPreparation 只消费 ApprovedOrderIntent；
上游业务链明确引用的 mark price 是唯一比较基准；
BUY 使用 best ask，SELL 使用 best bid；
偏差小于或等于 1% 时允许，只有大于 1% 才阻断；
实时查询统一经过 BinancePublicMarketGateway；
盘口结果作为审计证据保存，但不成为 PriceSnapshot 或成交价；
账户事实只按明确 sync_run_id 读取，不隐式选择最新批次；
持仓复核只核对获批快照，不伪装成 Binance 当前持仓查询；
订单参数不被缩小、放大、拆分或改向；
PreparedOrderIntent 唯一、幂等、短期有效且不可复用；
PreparedOrderIntent 有效期从实时盘口价格观测时间开始计算；
ActiveLock 在订单提交前持续保护订单链路；
trace_id 只用于技术追踪，不作为业务外键、幂等键或 PreparedOrderIntent 字段；
所有结果可追溯到完整上游对象和 Gateway 元数据；
本模块不访问订单提交接口，不执行真实交易。
```

## 33. 当前不包含的能力

```text
WebSocket 实时行情；
dry-run；
盘口深度和预估冲击成本；
根据流动性动态缩单；
止损单或追踪止损单；
自动重新风控；
自动重新生成账户或价格快照；
订单提交；
订单状态查询；
成交同步；
成交价与 mark price 的事后滑点比较；
自动修改杠杆、保证金模式或持仓模式。
```
