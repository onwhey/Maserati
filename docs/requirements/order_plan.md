# OrderPlan 需求

## 1. 模块定位

OrderPlan 是系统中唯一负责把目标仓位转换为候选订单意图的模块。

它读取 Connector 显式传入的目标仓位、账户事实、持仓事实、价格事实和交易规则，计算目标仓位与当前仓位的差额，生成可审计、可供 RiskCheck 审批、但不可直接执行的 `CandidateOrderIntent`。

OrderPlan 同时拥有 `OrderPlanActiveLock`。该锁用于保证同一交易身份在上一条订单链路没有安全结束时，不会生成新的冲突订单链路。

## 2. 核心链路

```text
DecisionSnapshot
+ 明确的 BinanceSyncRun
+ 明确的 PriceSnapshot
→ OrderPlan
→ CandidateOrderIntent
→ RiskCheck
→ ApprovedOrderIntent
→ ExecutionPreparation
→ PreparedOrderIntent
→ Execution / OrderSubmissionAttempt
→ OrderStatusSyncRecord
→ TradeFill / OrderFillSummary
```

## 3. 负责事项

OrderPlan 负责：

```text
校验 business_request_key 和直接业务输入；
校验 DecisionSnapshot 目标仓位语义；
读取指定 BinanceSyncRun 的账户、持仓和交易规则；
读取指定 PriceSnapshot 的 mark_price；
按市场域选择正确仓位计算器；
计算目标名义、目标数量或目标合约张数；
计算当前仓位与目标仓位差额；
按交易规则规范化订单数量；
判断是否无需调仓；
生成 primary CandidateOrderIntent；
净额反手时预生成 fallback_reduce_only_intent；
生成 order_components；
创建和维护 OrderPlanActiveLock；
记录计算证据、配置快照、原因码和 AlertEvent；
保证相同 business_request_key 幂等和跨业务请求冲突保护。
```

## 4. 不负责事项

OrderPlan 不负责：

```text
生成策略信号；
决定 target_position_ratio；
读取数据库最新账户批次作为兜底；
读取 Connector 未明确传入的价格；
请求 Binance；
访问 Binance Gateway；
计算或修改交易所杠杆；
最终保证金审批；
修改候选订单以通过风控；
生成 ApprovedOrderIntent；
准备交易所请求；
提交、撤销或查询订单；
查询成交；
修改交易所持仓；
根据 Hermes、后台或大模型建议生成订单。
```

## 5. 当前支持范围

```text
交易所：Binance
市场域：usds_m_futures、coin_m_futures
持仓模式：One-Way Mode
positionSide：BOTH
订单类型：MARKET
单 active account domain
单业务请求 / 单 symbol
目标仓位范围：-1.0 至 +1.0
```

Hedge Mode、多个 active domain、批量订单和组合级订单规划不在当前范围。

## 6. 直接业务输入合同

每个 `business_request_key` 最多生成一条有效 OrderPlan。

OrderPlanStepAdapter 必须显式传入：

```text
business_request_key
decision_snapshot_id
binance_sync_run_id
price_snapshot_id
reference_time_utc
trace_id
trigger_source
```

OrderPlan 必须确认：

```text
business_request_key 存在且格式合法；
DecisionSnapshot 可用且未过期；
BinanceSyncRun 是明确传入的 trade_preparation 批次；
该 BinanceSyncRun 来自本轮自动编排起始账户边界同步；
PriceSnapshot 是明确传入的价格事实；
market_type、account_domain 和 symbol 全部一致；
BinanceSyncRun 与 PriceSnapshot 均未过期；
账户、持仓、交易规则和价格 hash 可验证。
```

任一条件不满足时必须 `blocked`，不得读取历史成功对象兜底。

## 7. DecisionSnapshot 合同

OrderPlan 只消费目标仓位语义：

```text
target_intent
target_position_ratio
policy_code
policy_version
allows_order_plan
evidence_summary
```

OrderPlan 只允许消费：

```text
DecisionSnapshot.status = created；
DecisionSnapshot.is_usable = true；
target_intent = TARGET_POSITION；
allows_order_plan = true；
DecisionSnapshot 未过期。
```

当传入的 DecisionSnapshot 为以下目标意图时：

```text
target_intent = NO_TARGET_CHANGE；
target_intent = NO_TRADE。
```

正常情况下，编排层不应把 `NO_TARGET_CHANGE` 或 `NO_TRADE` 的 DecisionSnapshot 继续传入 OrderPlan。

如果这类 DecisionSnapshot 被传入 OrderPlan，表示上游调用合同错误，OrderPlan 必须 fail-closed：

OrderPlan 必须：

```text
status = blocked；
reason_code = decision_snapshot_not_orderable；
不生成 CandidateOrderIntent；
不生成或占用 ActiveLock；
写 AlertEvent。
```

`target_position_ratio` 表示目标总仓位，不是新增下单比例：

```text
+1.0 = 目标满仓做多
+0.5 = 目标半仓做多
 0.0 = 目标空仓
-0.5 = 目标半仓做空
-1.0 = 目标满仓做空
```

OrderPlan 必须校验其为有限 Decimal 且处于 `[-1, 1]`。OrderPlan 不重新解释 StrategySignal，也不改变目标比例。

## 8. 账户与持仓合同

OrderPlan 必须通过 `binance_sync_run_id` 读取同一批次：

```text
BinanceAccountSnapshot
BinanceBalanceSnapshot
BinancePositionSnapshot
BinanceSymbolRuleSnapshot
```

必须校验：

```text
BinanceSyncRun.status = succeeded；
sync_purpose = trade_preparation；
position_mode = one_way；
目标 symbol 的持仓事实存在；
目标资产余额存在；
交易规则完整；
COIN-M contract_size 合法。
```

OrderPlan 不使用 `ops_display` 批次，不自动选择 latest succeeded。

`current_equity` 必须使用包含未实现盈亏的账户权益口径，不得使用不包含未实现盈亏的 wallet balance 口径。

USDS-M：

```text
current_equity_quote = totalMarginBalance 或对应 quote asset 的 marginBalance；
available_balance_quote = availableBalance 或对应 quote asset 的 availableBalance。
```

COIN-M：

```text
current_equity_native = settlement asset 的 marginBalance；
available_balance_native = settlement asset 的 availableBalance。
```

`current_equity` 只用于 OrderPlan 目标仓位换算；`available_balance` 只作为 RiskCheck 新增风险审批输入。OrderPlan 不得因为可用余额不足而自行缩小订单或改变目标仓位。

## 9. PriceSnapshot 合同

OrderPlan 只读取 adapter 明确传入的 PriceSnapshot。

必须校验：

```text
price_type = mark_price；
market_type、account_domain、symbol 一致；
mark_price 大于零；
price_snapshot_hash 可验证；
reference_time_utc 未超过 expires_at_utc。
```

PriceSnapshot 默认 TTL 为 600 秒。OrderPlan 只使用 PriceSnapshot.expires_at_utc 判断价格有效性，不维护独立的价格 TTL，也不得请求刷新价格。

PriceSnapshot 在 OrderPlan 中只用于估值换算和审计绑定，不代表最终下单价格，也不代表真实成交价格。

最终报单前的实时价格查询、1% price guard、PreparedOrderIntent 有效期和成交价格对比，属于 ExecutionPreparation、Execution、OrderStatusSync 或 FillSync 的职责，不属于 OrderPlan。

价格过期时：

```text
OrderPlan.status = blocked；
reason_code = price_snapshot_stale；
不生成 CandidateOrderIntent；
不生成或占用 ActiveLock；
写 AlertEvent。
```

### 9.1 正式调用边界

正式编排只能在 OrderPlanStepAdapter 已经完成真实交易权限和交易市场校验后调用 OrderPlan service。

如果真实交易权限关闭、权限配置不可读取或当前业务市场与部署市场配置不一致，adapter 不得调用 OrderPlan，因此不会生成 OrderPlan、CandidateOrderIntent 或 ActiveLock。

OrderPlan 不读取 `.env`，不读取后台真实交易运行开关，也不重复判断权限。权限检查通过后，本轮后续步骤沿用进入 OrderPlan 前冻结的检查结果。

## 10. 核心仓位参数

当前使用：

```text
target_notional_basis = current_equity
max_target_notional_to_equity_ratio = 3.0
min_rebalance_notional = 20
```

所有值必须来自配置，并写入 `config_snapshot`。

`max_target_notional_to_equity_ratio` 是系统目标名义仓位相对当前权益的上限比例，不是 Binance 杠杆。

目标名义：

```text
target_notional
= current_equity
* max_target_notional_to_equity_ratio
* abs(target_position_ratio)
```

OrderPlan 不使用 `observed_exchange_leverage` 计算目标仓位，也不要求它等于配置值。

## 11. USDS-M 计算

单位：

```text
权益：quote asset
目标名义：quote asset
持仓和订单：base asset quantity
价格：quote asset / base asset
```

计算：

```text
target_notional_quote
= current_equity_quote
* max_target_notional_to_equity_ratio
* abs(target_position_ratio)

raw_target_abs_quantity
= target_notional_quote / mark_price

raw_target_signed_quantity
= sign(target_position_ratio) * raw_target_abs_quantity
```

当前持仓使用 `BinancePositionSnapshot.position_amount`，不得根据本地成交推导。

## 12. COIN-M 计算

单位：

```text
权益：settlement asset
目标名义：USD
持仓和订单：contracts
价格：USD mark price
contract_size：每张合约固定 USD 面值
```

计算：

```text
current_equity_usd
= current_equity_native * mark_price

target_notional_usd
= current_equity_usd
* max_target_notional_to_equity_ratio
* abs(target_position_ratio)

raw_target_abs_contracts
= target_notional_usd / contract_size

raw_target_signed_contracts
= sign(target_position_ratio) * raw_target_abs_contracts
```

COIN-M 必须使用 `BinanceSymbolRuleSnapshot.contract_size`。缺失、无法解析或小于等于零时必须阻断，不得复用 USDS-M 公式。

OrderPlan 不重算 COIN-M PnL，不使用线性合约 PnL 公式推导账户权益。

## 13. 数量规范化

OrderPlan 必须在生成 CandidateOrderIntent 前按 `BinanceSymbolRuleSnapshot` 规范化数量。

### 13.1 通用规则

必须读取：

```text
quantity_precision
step_size
min_quantity
max_quantity
min_notional
contract_size（COIN-M）
```

规则：

```text
所有计算使用 Decimal；
不得使用 float；
目标数量按 step_size 向零方向取整，避免超过目标风险；
COIN-M contracts 必须满足整数和 step_size；
取整后重新计算目标名义和订单差额；
取整后再检查最小数量、最大数量和最小名义；
不得把不合法数量留给 ExecutionPreparation 修改。
```

### 13.2 全平与 reduce-only

全平或纯减仓必须以交易所持仓快照中的实际仓位数量为上限。

如果实际仓位数量不符合当前 symbol rule：

```text
不得擅自放大数量；
不得生成超过当前持仓的 reduce-only 数量；
无法形成合法减仓数量时必须 blocked；
记录 position_quantity_not_aligned 或 reduce_only_quantity_invalid。
```

允许合法 step_size 造成不可交易的极小残余仓位，但必须记录 `residual_position_size`，不得宣称已经完全平仓。

### 13.3 净额反手

净额反手数量由两部分组成：

```text
closing_size = 当前可合法关闭数量
opening_size = 规范化后的新方向目标数量
requested_size = closing_size + opening_size
```

primary intent 和 fallback reduce-only intent 必须分别通过数量与交易规则校验。

### 13.4 最小调仓判断

最小调仓判断必须在数量规范化之后执行。

```text
normalized_order_notional < min_rebalance_notional
→ no_order_required
```

同时必须满足交易所的 `min_quantity` 和 `min_notional`。系统最小调仓阈值与交易所阈值任一不满足，都不得生成候选订单。

## 14. 仓位差额

规范化目标仓位后：

```text
delta_signed_size
= target_signed_size - current_signed_size

requested_size
= abs(delta_signed_size)
```

方向：

```text
delta > 0 → BUY
delta < 0 → SELL
delta = 0 → no_order_required
```

`target_position_ratio` 与 `target_signed_size` 必须同时保留，前者表达策略目标，后者表达按本次明确输入事实换算后的可交易目标。

## 15. 仓位转换类型

OrderPlan 至少区分：

```text
open_long
open_short
increase_long
increase_short
reduce_long
reduce_short
close_long
close_short
netting_reverse_long_to_short
netting_reverse_short_to_long
no_order_required
```

One-Way Mode 的净额反手可以生成一笔 MARKET 候选订单，但必须拆分内部风险组件。

## 16. order_components

`order_components` 表达一笔候选订单内部的风险语义，不是 Binance 子订单。

每个 component 至少包含：

```text
component_index
component_type
position_effect
side
size
size_unit
notional
risk_effect
is_risk_reducing
```

枚举：

```text
component_type：
  close_existing_position
  open_new_position
  increase_existing_position
  reduce_existing_position

position_effect：
  open_long / open_short
  increase_long / increase_short
  reduce_long / reduce_short
  close_long / close_short

risk_effect：
  reduce_risk
  increase_risk
```

组件不得使用 `reduceOnly` 作为自身参数。`reduceOnly` 只属于整笔未来交易所订单。

## 17. 典型转换

### 17.1 空仓开仓或同向加仓

```text
BUY 增加多仓，或 SELL 增加空仓；
exchange_reduce_only = false；
全部组件为 increase_risk。
```

### 17.2 同向减仓或平仓

```text
多仓减少 → SELL；
空仓减少 → BUY；
exchange_reduce_only = true；
全部组件为 reduce_risk；
requested_size 不得超过当前持仓。
```

### 17.3 净额反手

例如当前多仓 0.8，目标空仓 0.5：

```text
primary：SELL 1.3，reduceOnly=false；
component 1：close_long 0.8，reduce_risk；
component 2：open_short 0.5，increase_risk。
```

反向场景同理。

## 18. CandidateOrderIntent

OrderPlan 生成的候选意图状态为：

```text
pending_risk_check
```

至少记录：

```text
id
order_plan_id
intent_role
symbol
market_type
account_domain
position_mode
order_type
plan_type
side
position_side
exchange_reduce_only
requested_size
requested_notional
requested_size_unit
price_snapshot_id
reference_mark_price
binance_sync_run_id
current_position_snapshot_id
symbol_rule_snapshot_id
current_position_signed_size
target_position_signed_size
delta_signed_size
closing_size
opening_size
residual_position_size
order_components
status
reason_code
evidence
intent_hash
trace_id
created_at_utc
```

`intent_role`：

```text
primary
fallback_reduce_only
```

CandidateOrderIntent 不是 PreparedOrderIntent，也不能被 Execution 直接提交。

## 19. fallback_reduce_only

仅净额反手可以预生成 fallback reduce-only intent。

规则：

```text
fallback 必须由 OrderPlan 与 primary 同时生成；
fallback 只关闭当前方向仓位，不开新方向仓位；
fallback.exchange_reduce_only = true；
fallback 只有 reduce_risk components；
fallback 数量不得超过当前持仓；
fallback 必须独立通过数量、交易规则和 hash 校验；
RiskCheck 只能选择已存在的 primary 或 fallback；
RiskCheck 不得临时修改 primary 生成 fallback。
```

非反手场景不得生成无意义 fallback。

## 20. OrderPlan 模型

至少记录：

```text
id
business_request_key
decision_snapshot_id
binance_sync_run_id
account_snapshot_id
position_snapshot_id
symbol_rule_snapshot_id
price_snapshot_id
active_lock_id
exchange
market_type
account_domain
symbol
position_mode
target_position_ratio
current_equity
current_signed_size
raw_target_signed_size
target_signed_size
delta_signed_size
mark_price
target_notional
normalized_order_notional
min_rebalance_notional
max_target_notional_to_equity_ratio
status
reason_code
allows_downstream
config_snapshot
calculation_evidence
order_plan_hash
trace_id
trigger_source
created_at_utc
```

状态：

```text
created
no_order_required
blocked
failed
```

只有 `created` 可以生成 CandidateOrderIntent 并占用 ActiveLock。

## 21. OrderPlanActiveLock 定位

OrderPlanActiveLock 是同一交易身份的唯一订单链路门锁。

锁身份：

```text
exchange
market_type
account_domain
symbol
```

在锁没有安全释放前，任何新业务请求都不得为相同身份生成新的有效 OrderPlan。

ActiveLock 是 OrderPlan 判断能否生成新订单链路的唯一并发入口。OrderPlan 不得分别扫描 OrderPlan、CandidateOrderIntent、ApprovedOrderIntent 或订单状态表猜测并发状态；其他对象只作为锁收尾证据和一致性巡检依据。

## 22. 锁的取得

生成 `created` OrderPlan 和 primary CandidateOrderIntent 时，必须在同一数据库事务中取得 ActiveLock。

规则：

```text
锁不存在 → 创建 active 锁；
锁为 released → 在行锁保护下绑定新 OrderPlan 并变为 active；
锁为 active → 新 OrderPlan blocked；
锁为 failed → 新 OrderPlan blocked，等待人工处理。
```

只有 OrderPlan 的锁取得服务可以执行 `released → active`。

`no_order_required`、`blocked` 或 `failed` 的 OrderPlan 不得留下新的 active 锁。

## 23. 锁状态

```text
active
released
failed
```

含义：

```text
active：上一条订单链路尚未被证明安全结束，继续阻断新计划；
released：上一条链路已依据明确事实结束，可以取得新锁；
failed：锁收尾或关联事实出现无法自动确认的问题，继续阻断并等待人工处理。
```

`failed` 不是可自动重用状态。任何自动流程不得把 `failed` 改为 `active` 或 `released`。

## 24. 锁修改权

只有 OrderPlan 模块内的 `OrderPlanActiveLockService` 可以修改锁状态。

以下模块只能提交收尾事实并调用该服务：

```text
RiskCheck
ExecutionPreparation
Execution
OrderStatusSync
FillSync
授权人工运维入口
```

PipelineOrchestrator、RuntimeGuard 和 OpsConsole 不得直接写锁状态。

## 25. 自动释放条件

### 25.1 风控阶段结束

可以释放：

```text
RiskCheck DENY，且未生成 ApprovedOrderIntent；
RiskCheck BLOCKED，且未生成 ApprovedOrderIntent；
RiskCheck FAILED，但事务确认未生成 ApprovedOrderIntent 且订单链路尚未进入执行准备。
```

### 25.2 执行准备结束

可以释放：

```text
ExecutionPreparation BLOCKED，且没有可提交 PreparedOrderIntent；
ExecutionPreparation FAILED，且能够证明没有形成可提交请求、没有调用订单提交。
```

无法证明时不得释放，应将锁保持 active 或标记 failed 并人工处理。

### 25.3 提交前结束

可以释放：

```text
OrderSubmissionAttempt.blocked_before_submit，且 request_sent=false；
OrderSubmissionAttempt.failed_before_submit，且 request_sent=false；
OrderSubmissionAttempt.rejected，且 Binance 明确拒绝、订单未被接受。
```

### 25.4 交易所订单终态

订单提交曾被接受时，只有同时满足以下条件才能释放：

```text
OrderStatusSync 已确认订单进入明确终态；
与该订单有关的成交查询已经完成；
TradeFill 已幂等落库；
OrderFillSummary 已生成并通过完整性校验；
状态与成交事实可以追溯到同一 OrderSubmissionAttempt。
```

明确终态包括：

```text
FILLED
CANCELED
EXPIRED
REJECTED
EXPIRED_IN_MATCH
```

终态无成交时，必须由 FillSync 明确确认 `synced_empty`，并且订单状态确实是不可能继续成交的终态，才允许释放。

### 25.5 人工收尾

授权操作人可以在核对 Binance 和本地证据后执行：

```text
failed / active → released
active → failed
```

必须记录操作人、原因、证据、trace_id 和 AlertEvent。

## 26. 不得自动释放

以下情况不得自动释放：

```text
OrderSubmissionAttempt.accepted，但尚未确认订单终态；
OrderSubmissionAttempt.unknown；
OrderStatusSync unknown；
OrderStatusSync not_found；
订单状态 NEW；
订单状态 PARTIALLY_FILLED；
FillSync unknown、incomplete、failed_before_query、blocked_before_query、recovery_skipped_out_of_window 或完整性失败；
成交同步成功但订单仍可能继续成交；
只看到余额或持仓变化；
只看到 RuntimeGuard 告警；
上层编排流程已经结束；
超过等待时间但没有明确交易所事实。
```

市价单通常快速成交，但不得以“通常如此”替代终态证据。

## 27. OrderStatusSync 等待边界

Execution accepted 后，OrderStatusSync 将按其需求进行有限状态同步：

```text
每 2 秒查询一次；
最多持续 30 秒；
查到终态后停止；
30 秒后仍是 NEW / PARTIALLY_FILLED 或无法确认时停止自动查询并标记人工关注。
```

OrderPlanActiveLockService 不负责轮询，也不因 30 秒超时自动解锁。详细查询、恢复和状态记录由 OrderStatusSync 需求定义。

## 28. 锁幂等与并发

锁取得和收尾必须使用数据库行锁和事务。

规则：

```text
同一身份同时只能有一个 active OrderPlan；
相同收尾事实重复调用返回幂等结果；
不得重复写等价状态变更；
不得让较低确定性的结果覆盖明确终态；
released 不得被普通收尾流程改回 active；
failed 不得被自动流程清除；
并发收尾只有一个状态变更生效。
```

锁事件必须保留历史，重新取得 released 锁不得覆盖上一条链路的收尾审计。

## 29. 幂等

OrderPlan 业务唯一性至少包含：

```text
business_request_key
decision_snapshot_id
binance_sync_run_id
price_snapshot_id
market_type
account_domain
symbol
配置 hash
```

相同 business_request_key 重复运行：

```text
输入完全一致 → 返回已有 OrderPlan；
已存在 OrderPlan 但输入对象不同 → blocked 并记录 input_conflict；
不得创建第二条 CandidateOrderIntent；
不得重复取得 ActiveLock。
```

## 30. AlertEvent

必须写 AlertEvent 的场景至少包括：

```text
OrderPlan no_order_required；
OrderPlan blocked；
OrderPlan failed；
CandidateOrderIntent generated；
输入批次或市场身份不一致；
价格或账户事实过期；
数量无法按交易规则规范化；
ActiveLock 冲突；
ActiveLock released；
ActiveLock failed；
ActiveLock 因不确定事实保持阻断；
人工锁收尾。
```

AlertEvent 不得被 Hermes 或后台反向用作交易触发器。

## 31. 配置

所有配置必须进入 `.env.example` 并带中文注释：

```text
ORDER_PLAN_ENABLED
ORDER_PLAN_SUPPORTED_MARKET_TYPES
ORDER_PLAN_TARGET_NOTIONAL_BASIS=current_equity
ORDER_PLAN_MAX_TARGET_NOTIONAL_TO_EQUITY_RATIO=3.0
ORDER_PLAN_MIN_REBALANCE_NOTIONAL=20
ORDER_PLAN_SUPPORTED_POSITION_MODE=one_way
ORDER_PLAN_SUPPORTED_ORDER_TYPE=MARKET
```

PriceSnapshot TTL 由 PriceSnapshot 模块管理，OrderPlan 不重复定义。

## 32. 数据库、Redis 与外部服务

```text
读写 MySQL：是，保存 OrderPlan、CandidateOrderIntent、ActiveLock 和锁事件。
访问 Redis：非必需，不作为订单链路唯一锁。
访问 Binance：否。
发送 Hermes：不直接发送，只写 AlertEvent。
调用大模型：否。
涉及交易执行：生成不可执行候选意图，不提交订单。
允许真实交易：否。
```

## 33. 测试要求

至少覆盖：

```text
1. Adapter 显式传入 DecisionSnapshot、BinanceSyncRun 和 PriceSnapshot。
2. OrderPlan 与 RiskCheck 使用同一账户和价格批次。
3. 账户或价格市场身份不一致时被阻断。
4. PriceSnapshot 过期时 blocked，且不刷新价格。
5. One-Way Mode 正常计算。
6. Hedge Mode 和 unknown mode 被阻断。
7. USDS-M 目标数量计算正确。
8. COIN-M 目标 contracts 计算正确。
9. COIN-M 缺 contract_size 时 fail-closed。
10. observed_exchange_leverage 不参与目标仓位计算。
11. USDS-M current_equity 使用 totalMarginBalance 或 quote asset marginBalance，不使用 walletBalance。
12. COIN-M current_equity 使用 settlement asset marginBalance，并用 mark_price 折算 USD 目标名义。
13. OrderPlan 不使用 available_balance 缩小订单或改变目标仓位。
14. PriceSnapshot 只用于估值和审计绑定，不被解释为最终下单价或成交价。
15. 目标数量按 step_size 向零取整。
16. COIN-M contracts 满足整数和 step_size。
17. 取整后重新检查 min_quantity / max_quantity / min_notional。
18. 全平数量不超过实际持仓。
19. 无法合法全平时记录 residual 并阻断或生成合法减仓意图。
20. 调仓名义低于系统阈值时 no_order_required。
21. 不启用 rebalance_band_bps。
22. 不启用 max_rebalance_delta_ratio_per_cycle。
23. 空仓开仓、同向加仓、同向减仓和平仓组件正确。
24. 多转空、空转多生成 reduce_risk + increase_risk components。
25. 净额反手预生成合法 fallback_reduce_only。
26. RiskCheck 无法临时修改 primary 或生成新 fallback。
27. NO_TARGET_CHANGE / NO_TRADE 被传入时 blocked，且不生成 CandidateOrderIntent 或 ActiveLock。
28. 真实交易权限关闭时，OrderPlanStepAdapter 不调用 OrderPlan，且不生成 CandidateOrderIntent 或 ActiveLock。
29. 权限或市场配置不可读取时，OrderPlanStepAdapter fail-closed。
30. OrderPlan 本身不读取或修改真实交易权限配置。
31. created OrderPlan 与 ActiveLock 在同一事务生成。
32. active 锁阻断下一周期 OrderPlan。
33. released 锁允许新 OrderPlan 取得。
34. failed 锁继续阻断，不能自动重用。
35. DENY / BLOCKED 且无 ApprovedOrderIntent 时释放锁。
36. 提交前明确未发送时释放锁。
37. rejected 明确未被接受时释放锁。
38. accepted 不释放锁。
39. unknown / not_found 不释放锁。
40. NEW / PARTIALLY_FILLED 不释放锁。
41. FILLED 且成交同步完整后释放锁。
42. 终态部分成交在成交同步完整后释放锁。
43. synced_empty 只有配合无成交终态才释放锁。
44. 30 秒状态同步超时不释放锁。
45. 人工收尾记录操作人和证据。
46. 并发取得锁只能有一条有效订单链路。
47. 并发收尾只有一次状态变更。
48. 相同 business_request_key 幂等运行不重复生成 CandidateOrderIntent 或锁。
```

## 34. 验收标准

满足以下条件才算通过：

```text
OrderPlan 是目标仓位到 CandidateOrderIntent 的唯一转换入口；
每个 OrderPlan 可通过真实业务外键追溯到明确的决策、账户和价格事实；
USDS-M 与 COIN-M 使用各自正确公式；
数量在风控前已经按交易规则规范化；
OrderPlan 不使用交易所杠杆放大目标仓位；
净额反手具有清晰 order_components 和预生成 fallback；
CandidateOrderIntent 不可直接提交；
ActiveLock 是新订单链路的统一门锁；
无法证明上一笔订单结束时锁不会释放；
failed 锁不会被自动覆盖；
市场订单部分成交不会导致提前解锁；
模块不访问 Binance、不执行风控、不提交订单。
```

## 35. 当前不包含的能力

```text
Hedge Mode；
多 symbol 组合订单规划；
多 active domain；
LIMIT / STOP / TAKE_PROFIT 等订单类型；
分批调仓；
rebalance_band_bps；
max_rebalance_delta_ratio_per_cycle；
任意 MODIFY；
自动缩单；
RiskCheck 动态生成 fallback；
自动撤单；
自动解锁未知订单；
根据账户变化倒推订单结束；
杠杆或保证金模式修改。
```
