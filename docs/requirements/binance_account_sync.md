# Binance Account Sync 需求

## 1. 模块定位

Binance Account Sync 是 Binance 账户事实同步模块。

本模块通过 Binance Gateway 读取当前 active account domain 的账户、余额、持仓和交易规则，将同一次同步得到的事实保存为一个完整、不可变、可追溯的 `BinanceSyncRun` 快照批次。

主要消费者：

```text
OrderPlan
RiskCheck
ExecutionPreparation
OpsConsole
PerformanceMetrics
Review
```

其中自动交易与后台展示必须使用不同的同步目的和消费入口。

## 2. 核心原则

```text
Binance 专属；
只读同步；
单 active market_type / account_domain；
每个自动四小时编排起始步骤都必须生成或幂等返回本轮 trade_preparation 同步批次；
OrderPlan 与 RiskCheck 使用同一个明确批次；
数据库快照是下游唯一账户事实来源；
同一批次内账户、余额、持仓和交易规则必须完整一致；
成功批次不可原地修改；
不得自动回退到历史成功批次；
后台人工刷新批次不得自动进入交易链路。
```

## 3. 负责事项

本模块负责：

```text
接收编排层或后台的账户同步请求；
校验 active market_type 和 account_domain；
调用 BinanceAccountReadGateway 读取账户、余额和持仓；
调用 BinancePublicMarketGateway 读取交易规则；
创建 BinanceSyncRun；
标准化 Binance 字段；
生成账户、余额、持仓和交易规则快照；
推断 position_mode；
记录 observed_exchange_leverage；
记录 COIN-M contract_size；
生成单项 snapshot_hash 和批次 snapshot_set_hash；
提供按 sync_run_id 读取完整交易上下文的 selector；
为 OpsConsole 提供当前 active domain 的一键刷新入口和展示查询入口；
记录同步失败、阻断和异常 AlertEvent；
提供健康状态和最近同步摘要。
```

## 4. 不负责事项

本模块不负责：

```text
自行创建 Binance HTTP client；
拼接 Binance endpoint；
API 签名、超时、重试、限频或熔断；
同步全部支持账户域；
并行同步多个 active domain；
账户统一估值；
跨账户域资产折算；
生成 PriceSnapshot；
生成 StrategySignal 或 DecisionSnapshot；
生成 OrderPlan 或 CandidateOrderIntent；
执行 RiskCheck；
生成 ApprovedOrderIntent 或 PreparedOrderIntent；
提交、查询、撤销或修改订单；
查询成交；
根据成交记录推导交易所持仓；
更新 OrderPlanActiveLock；
修改杠杆、保证金模式或持仓模式；
资金划转、充值或提现；
调用 Hermes；
调用大模型。
```

## 5. Binance 访问边界

本模块只能调用：

```text
BinanceAccountReadGateway
BinancePublicMarketGateway
```

允许的语义操作：

```text
get_account(active_market_type, call_context)
get_balances(active_market_type, call_context)
get_positions(active_market_type, call_context, configured_symbols)
get_symbol_exchange_info(active_market_type, symbol, call_context)
```

本模块不得获得：

```text
BinanceOrderSubmissionGateway
BinanceOrderStatusGateway
BinanceFillQueryGateway
BinanceTransport
通用 request 接口
```

API key、secret、base URL、签名、recvWindow、连接池、超时、重试和限频全部由 Binance Gateway 管理。

## 6. 市场域

当前支持：

```text
usds_m_futures
coin_m_futures
```

系统运行时只能存在一个 active market type。

每次同步必须满足：

```text
requested_market_type = configured_active_market_type
requested_account_domain = configured_active_account_domain
requested_market_type = requested_account_domain
```

任何不一致都必须在调用 Binance Gateway 前阻断。

禁止：

```text
一次调用同时同步 USDS-M 与 COIN-M；
当前 active domain 同步失败后回退到另一市场域；
把一个市场域的余额、持仓或交易规则写入另一个市场域批次；
通过 OpsConsole 热切换 active market type；
根据 symbol 自动猜测 market_type。
```

## 7. 同步目的

`BinanceSyncRun` 必须记录 `sync_purpose`。

当前只允许：

```text
trade_preparation
ops_display
```

### 7.1 trade_preparation

由 BinanceAccountSyncStepAdapter 在自动四小时编排起始账户边界步骤调用。该步骤先于行情、特征、信号、决策和订单链路执行，既为 PerformanceMetrics 保存周期账户边界事实，也为后续可能出现的 TARGET_POSITION 订单链路提供同一份账户事实。业务模块只接收不透明 `business_request_key`，不读取编排对象。

规则：

```text
每个 business_request_key 最多生成一份有效 BinanceSyncRun；
相同 business_request_key 幂等重放返回同一批次；
不同 business_request_key 不得复用同一 BinanceSyncRun；
同步失败时返回不可继续的业务结果；
同步成功后 adapter 返回 binance_sync_run_id，由编排层写入业务对象关联表。
```

同步成功后，无论后续流程是否进入交易链路，该批次都保持本轮自动账户边界资格：

```text
完整保存账户、余额、持仓和交易规则快照；
该批次可以作为 PerformanceMetrics 自动周期边界；
该批次可以作为 OrderPlan / RiskCheck / ExecutionPreparation 的上游账户事实；
后续 NO_TARGET_CHANGE / NO_TRADE / no_strategy / 真实交易权限关闭不会触发第二次 trade_preparation 同步；
后续流程不得用 ops_display 或数据库最新批次替换该批次。
```

BinanceAccountSyncService 不读取 DecisionSnapshot，也不自行判断后续分支。账户同步服务只生成同一合同的账户事实。

### 7.2 ops_display

由 OpsConsole 的账户总览页面通过受控后端 service 人工触发。

规则：

```text
只同步当前 active account domain；
不提供同步全部账户域能力；
必须记录操作人、trigger_source、trace_id 和同步结果；
可以供 OpsConsole、运维排查和人工查看；
不得自动关联正式交易编排；
不得被 OrderPlan 或 RiskCheck 自动选择；
不得改变全局交易允许状态；
同步失败只影响本次展示刷新，不修改正式交易编排事实。
```

## 8. 对外服务入口

本模块必须提供两个明确入口。

### 8.1 自动账户边界同步

语义接口：

```text
sync_for_trade_preparation(
    business_request_key,
    market_type,
    account_domain,
    symbols,
    trace_id,
    trigger_source,
)
```

返回：

```text
BinanceSyncRun
```

要求：

```text
business_request_key 必须存在且格式合法；
market_type / account_domain 必须等于当前 active domain；
相同 business_request_key 重复调用返回同一有效批次或当前失败结果；
不得因为重试创建两份可供交易消费的批次；
不得回退到其他 business_request_key 的成功批次；
本模块不得解析 business_request_key 或据此查询编排数据。
```

### 8.2 后台一键刷新

语义接口：

```text
refresh_for_ops_console(
    operator_id,
    trace_id,
    trigger_source="ui_one_click",
)
```

返回当前 active domain 的 `BinanceSyncRun` 和展示摘要。

要求：

```text
必须由后端执行权限校验；
必须记录操作人、触发来源和审计信息；
不得接收前端传入的任意 market_type；
不得直接返回敏感 Gateway 元数据；
不得让前端直接调用 Binance Gateway；
不得生成 trade_preparation 目的的同步批次。
```

## 9. 编排衔接合同

BinanceAccountSyncStepAdapter 在每个自动四小时 OrchestrationRun 起始账户边界步骤中必须：

```text
接收 OrchestrationStepRun 生成的不透明 business_request_key；
调用 sync_for_trade_preparation；
确认 BinanceSyncRun.status = succeeded；
确认 sync_purpose = trade_preparation；
确认 BinanceSyncRun.business_request_key 与本次请求一致；
确认批次未过期且快照集合完整；
把 binance_sync_run_id 作为 primary_output 返回；
由编排层写入 OrchestrationBusinessObjectLink。
```

同步成功后的分支映射：

```text
自动账户边界同步成功 → 继续 DataCollection；
后续 TARGET_POSITION → 复用该 binance_sync_run_id 进入 PriceSnapshot / OrderPlan；
后续 NO_TARGET_CHANGE / NO_TRADE / no_strategy / 真实交易权限关闭 → 不补做账户同步。
```

如果本次同步失败、阻断或结果不完整：

```text
adapter 返回 STOP 或 FAIL；
不得生成 OrderPlan；
不得读取其他请求的成功批次；
不得使用 ops_display 批次兜底；
必须记录原因和 AlertEvent。
```

## 10. OrderPlan 与 RiskCheck 消费合同

OrderPlan 和 RiskCheck 必须接收编排层显式传入的同一个 `binance_sync_run_id`。

必须满足：

```text
BinanceSyncRun.sync_purpose = trade_preparation；
BinanceSyncRun.status = succeeded；
market_type / account_domain 与当前交易身份一致；
批次未过期；
账户、余额、目标 symbol 持仓和交易规则快照完整；
snapshot_set_hash 可验证。
```

OrderPlan 不得使用一份批次、RiskCheck 再自动选择另一份批次。

任何条件不满足时：

```text
OrderPlan 必须 blocked，或 RiskCheck 必须 BLOCKED；
不得继续使用部分快照；
不得自动回退到 latest succeeded；
不得回退到 ops_display 批次；
必须写明 reason_code 和 AlertEvent。
```

## 11. ExecutionPreparation 消费边界

ExecutionPreparation 必须能够追溯 RiskCheck 使用的 `binance_sync_run_id`。

本模块只提供按明确 `sync_run_id` 读取和校验快照的能力，不向 ExecutionPreparation 提供“自动选择数据库最新批次”的交易 selector。

ExecutionPreparation 是否复用风控批次，或者使用编排层显式绑定的更新复核批次，由 ExecutionPreparation 需求定义；但必须满足：

```text
复核使用的 sync_run_id 被记录；
不得隐式读取 ops_display 批次；
不得无记录地切换账户事实；
不得因账户事实过期而自动放行；
使用更新批次时必须比较风控批准时的关键账户和持仓字段。
```

## 12. 数据模型

本模块拥有：

```text
BinanceSyncRun
BinanceAccountSnapshot
BinanceBalanceSnapshot
BinancePositionSnapshot
BinanceSymbolRuleSnapshot
```

同一组表通过 `market_type` 和 `account_domain` 区分 USDS-M 与 COIN-M，不为两个市场域创建两套重复模型。

### 12.1 BinanceSyncRun

表示一次完整同步批次。

至少记录：

```text
id
exchange
market_type
account_domain
sync_purpose
business_request_key（trade_preparation 必填；与 market_type、account_domain、sync_purpose 组合唯一）
requested_symbols
status
started_at_utc
finished_at_utc
as_of_utc
expires_at_utc
position_mode
snapshot_set_hash
gateway_call_summary
error_code
error_message
trace_id
trigger_source
operator_id（人工刷新时记录）
created_at_utc
```

状态只允许：

```text
running
succeeded
failed
```

`succeeded` 是整批快照的发布标记。只有所有必需快照写入成功、hash 完成并通过完整性校验后才能设置。

不使用 `partial_failed` 作为可消费状态。部分接口成功但整个批次不完整时，批次必须 `failed`。

### 12.2 BinanceAccountSnapshot

至少记录：

```text
sync_run_id
market_type
account_domain
fee_tier
can_trade
can_deposit
can_withdraw
position_mode
total_wallet_balance
total_unrealized_profit
total_margin_balance
available_balance
max_withdraw_amount
native_asset
as_of_utc
source_operation
raw_payload
snapshot_hash
```

不同市场域不存在的字段允许为空，但不得用另一市场域字段伪造。

### 12.3 BinanceBalanceSnapshot

每个资产一条记录，至少包含：

```text
sync_run_id
market_type
account_domain
asset
wallet_balance
cross_wallet_balance
cross_unrealized_pnl
available_balance
max_withdraw_amount
margin_available
update_time_utc
source_operation
raw_payload
snapshot_hash
```

### 12.4 BinancePositionSnapshot

每个 symbol / position side 一条记录，至少包含：

```text
sync_run_id
market_type
account_domain
symbol
raw_position_side
normalized_position_side
position_amount
entry_price
break_even_price
mark_price
unrealized_pnl
liquidation_price
isolated_margin
notional
margin_asset
margin_mode
position_mode_observed
observed_exchange_leverage
update_time_utc
source_operation
raw_payload
snapshot_hash
```

即使仓位数量为零，也应保存目标 symbol 的持仓事实，便于证明当前为空仓。

### 12.5 BinanceSymbolRuleSnapshot

每个 symbol 一条记录，至少包含：

```text
sync_run_id
market_type
account_domain
symbol
contract_status
base_asset
quote_asset
margin_asset
settlement_asset
contract_type
price_precision
quantity_precision
tick_size
step_size
min_price
max_price
min_quantity
max_quantity
min_notional
contract_size
supported_order_types
raw_filters
source_operation
raw_payload
snapshot_hash
```

USDS-M 的 `contract_size` 可以为空；COIN-M 的 `contract_size` 必须存在、可解析且大于零，否则该 symbol 的交易上下文不可消费。

## 13. position_mode

本模块根据 Binance 持仓响应中的 position side 记录观测到的持仓模式。

规则：

```text
只出现 BOTH → one_way；
出现 LONG 或 SHORT → hedge；
无法确认 → unknown。
```

本模块只记录，不调用 Binance 修改 position mode。

当前自动交易只支持 `one_way`。出现 `hedge` 或 `unknown` 时：

```text
同步批次可以保存成功事实；
交易 selector 必须返回不可用于当前交易链路；
OrderPlan / RiskCheck 必须 fail-closed；
写入明确 reason_code。
```

## 14. observed_exchange_leverage

`observed_exchange_leverage` 是 Binance 当前 symbol 返回的实际杠杆设置。

规则：

```text
可解析且大于零时保存 Decimal 值；
缺失、为空、无法解析或小于等于零时保存 null；
不得用环境配置值填充；
不得用目标名义权益比例填充；
不得参与 OrderPlan 的目标仓位计算；
不得触发系统自动修改 Binance 杠杆。
```

RiskCheck 可以使用该事实估算新增风险组件所需保证金。是否阻断由 RiskCheck 需求定义。

## 15. USDS-M 与 COIN-M 字段口径

### 15.1 USDS-M

```text
current_equity 使用对应账户事实中的 margin balance 口径；
available_balance 使用对应结算资产的可用余额；
目标数量使用标的数量单位；
不得引入 COIN-M contract_size。
```

### 15.2 COIN-M

```text
账户权益和可用余额以原生 settlement asset 保存；
不得在本模块内强制折算为 USDT；
交易规则必须保存 contract_size；
持仓数量和合约张数语义必须保留；
不得复用 USDS-M 的收益、名义或保证金公式。
```

### 15.3 禁止混用

```text
不得用 USDS-M 余额补 COIN-M 缺失余额；
不得用 COIN-M 余额补 USDS-M 缺失余额；
不得跨市场域复用 PositionSnapshot；
不得跨市场域复用 SymbolRuleSnapshot；
不得用统一估值字段覆盖原始币种字段。
```

## 16. mark_price 与 PriceSnapshot

`BinancePositionSnapshot.mark_price` 是 Binance 账户持仓响应中的观测字段。

PriceSnapshot 不从 `BinancePositionSnapshot.mark_price` 派生。每份正式 PriceSnapshot 都必须通过 BinancePublicMarketGateway 主动请求本轮标记价格。

边界：

```text
Binance Account Sync 不生成 PriceSnapshot；
PriceSnapshot 不反向修改 PositionSnapshot；
PositionSnapshot.mark_price 不等于实际成交价；
OrderPlan、RiskCheck 和 ExecutionPreparation 消费价格的正式规则由 PriceSnapshot 需求定义。
```

## 17. 同步流程

标准流程：

```text
1. 校验调用参数、sync_purpose 和 active domain。
2. 执行业务幂等检查。
3. 创建 BinanceSyncRun(status=running)。
4. 通过 BinanceAccountReadGateway 获取账户、余额和持仓。
5. 通过 BinancePublicMarketGateway 获取目标 symbol 交易规则。
6. 校验 Gateway 结果和必要 payload。
7. 标准化字段并推断 position_mode。
8. 构建账户、余额、持仓和交易规则快照。
9. 计算各 snapshot_hash。
10. 计算 snapshot_set_hash。
11. 在数据库事务中写入完整快照集合。
12. 完整性校验通过后发布 BinanceSyncRun(status=succeeded)。
13. 返回 BinanceSyncRun 和摘要。
```

如果外部请求或标准化失败：

```text
BinanceSyncRun.status = failed；
记录脱敏 error_code / error_message；
不得发布部分快照；
不得让下游消费已写入的中间结果；
写 AlertEvent；
由调用方 adapter 决定正式编排停止或后台刷新失败。
```

外部请求不得长时间包含在数据库写事务中。

## 18. 完整性与事务

一个交易同步批次至少必须包含：

```text
1 条 BinanceAccountSnapshot；
目标资产所需 BinanceBalanceSnapshot；
每个 configured symbol 的 BinancePositionSnapshot；
每个 configured symbol 的 BinanceSymbolRuleSnapshot。
```

只有全部满足才可 `succeeded`。

规则：

```text
快照集合写入必须使用 transaction.atomic；
不得出现 sync run succeeded 但缺少必需子快照；
不得出现某些子快照属于其他 sync run；
不得让 running / failed 批次进入交易 selector；
不得把部分成功解释为可交易。
```

## 19. 新鲜度

`BinanceSyncRun` 必须记录：

```text
as_of_utc
expires_at_utc
```

交易 selector 以 `expires_at_utc` 判断批次是否可消费。

规则：

```text
TTL 来自配置；
不得使用服务器本地时区；
不得由下游自行延长 expires_at_utc；
过期批次不得供 OrderPlan、RiskCheck 或 ExecutionPreparation 继续使用；
过期时不得自动回退到上一条 succeeded；
OpsConsole 可以展示过期批次，但必须明确标记 stale。
```

## 20. Selector

### 20.1 交易 selector

交易 selector 必须以明确的 `binance_sync_run_id` 为主输入。

至少提供：

```text
get_sync_run(sync_run_id)
get_account_snapshot(sync_run_id)
get_balance_snapshots(sync_run_id)
get_balance_snapshot_for_asset(sync_run_id, asset)
get_position_snapshot(sync_run_id, symbol, position_side=None)
get_symbol_rule_snapshot(sync_run_id, symbol)
get_sync_context_bundle(sync_run_id, symbol)
get_symbol_trading_context(sync_run_id, symbol)
```

交易 selector 必须统一校验：

```text
status
sync_purpose
business_request_key
market_type
account_domain
expires_at_utc
快照完整性
snapshot_set_hash
symbol
position_mode
COIN-M contract_size
margin_asset 对应余额
```

### 20.2 展示 selector

OpsConsole 可以使用：

```text
get_latest_ops_display_run(active_market_type)
get_account_overview(sync_run_id)
get_sync_health(active_market_type)
```

展示 selector 可以读取最新的 `ops_display` 或明确指定批次，但必须返回：

```text
sync_purpose
status
as_of_utc
expires_at_utc
is_stale
market_type
account_domain
```

展示 selector 不提供“可用于交易”结论。

## 21. 幂等与并发

### 21.1 trade_preparation

业务唯一性至少覆盖：

```text
business_request_key
market_type
account_domain
sync_purpose=trade_preparation
```

同一 business_request_key 并发调用时只能产生一份有效自动账户边界同步批次。

如果已有：

```text
running → 返回正在运行或重复触发结果，不启动第二次同步；
succeeded → 返回已有批次；
failed → 返回当前失败结果，本轮自动编排不得自动创建第二个可消费批次。
```

同一 `business_request_key` 的 `trade_preparation` 同步失败后，不得在本轮内再次生成可消费批次。如需再次尝试，必须由新的编排轮次生成新的 `business_request_key`。

Binance Gateway 内部允许的技术重试仍属于同一次业务调用，不构成新的账户边界同步批次。

### 21.2 ops_display

后台连续点击必须有短期防重复保护。

同一个操作请求必须通过稳定 idempotency key 避免重复同步。不同人工刷新可以创建新的 ops_display 批次。

后台刷新不得与 trade_preparation 同步争夺或覆盖同一 `BinanceSyncRun`，两类目的必须生成独立记录。

## 22. Hash 与不可变性

每条快照必须有稳定 `snapshot_hash`。

`BinanceSyncRun.snapshot_set_hash` 必须反映整批核心标准字段和子快照 hash。

hash 至少覆盖：

```text
sync_purpose
business_request_key（可为空）
market_type
account_domain
position_mode
账户权益与可用余额
资产余额
持仓方向与数量
entry_price / mark_price
margin_mode
observed_exchange_leverage
交易规则
COIN-M contract_size
各子快照业务身份
```

成功批次发布后：

```text
不得修改核心字段；
不得替换 raw_payload；
不得重新计算后覆盖 hash；
不得把 ops_display 改为 trade_preparation；
不得修改 business_request_key；
不得覆盖历史批次。
```

Binance 事实变化必须生成新的 BinanceSyncRun 和新快照。

## 23. 健康状态

本模块应提供当前 active domain 的同步健康摘要：

```text
latest_trading_sync_status
latest_trading_sync_at_utc
latest_ops_sync_status
latest_ops_sync_at_utc
consecutive_failure_count
is_fresh
last_error_code
last_error_at_utc
```

健康摘要用于监控和展示，不替代具体 BinanceSyncRun，也不作为交易 selector 的自动回退来源。

RuntimeGuard 可以巡检长期失败或自动账户边界同步缺失，但不得代替本模块生成快照或修改同步结果。

## 24. AlertEvent

必须写 AlertEvent 的场景至少包括：

```text
自动账户边界同步失败；
active market type / account domain 配置非法；
部署级 Gateway / Account Sync 硬开关关闭，或账户读取权限不可用；
认证或权限错误；
Gateway 返回无法确认的技术结果；
必要响应字段缺失或类型非法；
快照集合写入失败；
完整性或 hash 校验失败；
Connector 试图把无效、过期或错误目的批次传给交易模块；
OrderPlan / RiskCheck 传入不同 sync_run_id；
连续同步失败达到告警阈值。
```

后台人工刷新成功可以只写操作审计和普通状态事件；刷新失败必须在页面明确显示，是否发送 Hermes 由 Notifications 规则决定。

AlertEvent 不得包含 API key、secret、signature、完整认证 header 或未脱敏 Gateway payload。

## 25. 配置

本模块自己的配置必须进入 `.env.example` 并带中文注释：

```text
BINANCE_ACCOUNT_SYNC_ENABLED
BINANCE_ACCOUNT_SYNC_TTL_SECONDS
BINANCE_ACCOUNT_SYNC_SYMBOLS
BINANCE_ACCOUNT_SYNC_CONSECUTIVE_FAILURE_ALERT_THRESHOLD
BINANCE_ACCOUNT_SYNC_OPS_REFRESH_COOLDOWN_SECONDS
```

`BINANCE_ACCOUNT_SYNC_ENABLED` 是部署级硬开关，只能通过环境配置变更并随服务重启或配置加载生效。

它只表示当前部署环境是否允许执行 Binance Account Sync 模块，不是 OpsConsole 后台动态开关，不得由业务模块或前端修改，也不得用来表达是否允许真实交易。

当 `BINANCE_ACCOUNT_SYNC_ENABLED = false` 时：

```text
trade_preparation 账户同步必须 blocked / failed；
不得请求 Binance；
不得生成可交易 BinanceSyncRun；
必须写明确 AlertEvent；
OpsConsole 一键刷新返回模块未启用或不可执行。
```

本模块不得重复定义：

```text
Binance API key / secret
Binance base URL
Gateway timeout
Gateway retry
Gateway rate limit
recvWindow
签名配置
```

这些配置属于 Binance Gateway。

## 26. 数据库、Redis 与外部服务

```text
读写 MySQL：是，保存同步批次和事实快照。
访问 Redis：非必需；如用于短期防重复锁，只能保存短期状态。
访问 Binance：是，但只能通过 Binance Gateway。
发送 Hermes：不直接发送，只写 AlertEvent。
调用大模型：否。
涉及交易执行：否。
允许真实交易：否。
```

Redis 不得成为账户事实来源。Redis 不可用时，不得把缓存数据作为交易快照兜底。

## 27. Management command 与任务入口

允许提供：

```text
自动账户边界同步 application service 入口；
OpsConsole 人工刷新 API；
受控 management command；
PipelineStage adapter。
```

入口层只能：

```text
解析参数；
生成或传递 trace_id；
设置 trigger_source；
执行后台操作权限校验；
调用 BinanceAccountSyncService；
输出结果摘要。
```

入口层不得实现 Gateway 调用、字段标准化、快照写入、hash 或交易消费判断。

## 28. 测试要求

自动化测试必须使用 fake Binance Gateway，不得访问真实 Binance。

至少覆盖：

```text
1. 每个自动四小时编排起始账户边界请求创建新的 trade_preparation BinanceSyncRun。
2. 相同 business_request_key 重复调用返回同一有效批次。
3. 不同 business_request_key 不复用 BinanceSyncRun。
4. 本次同步失败时不回退其他请求的 succeeded 批次。
4a. 同步发生在 DataCollection、FeatureLayer、DecisionSnapshot 和 OrderPlan 之前。
4b. NO_TARGET_CHANGE / NO_TRADE / no_strategy / 真实交易权限关闭不会触发第二次 trade_preparation 同步。
5. OrderPlan 与 RiskCheck 只能使用 Connector 显式传入的同一 sync_run_id。
6. OrderPlan 与 RiskCheck 使用不同 sync_run_id 时阻断并告警。
7. ops_display 批次不能被交易 selector 消费。
8. OpsConsole 一键刷新只同步 active domain。
9. 前端传入其他 market_type 时被拒绝且不调用 Gateway。
10. 不存在同步全部账户域的 service。
11. USDS-M 只调用对应 Gateway adapter。
12. COIN-M 只调用对应 Gateway adapter。
13. 账户、余额、持仓或交易规则任一失败时批次 failed。
14. 不完整批次不能发布 succeeded。
15. succeeded 批次快照不可修改。
16. selector 只能读取同一 sync_run 的子快照。
17. 过期批次不可供交易消费。
18. position side 只有 BOTH 时推断 one_way。
19. 出现 LONG / SHORT 时推断 hedge。
20. position mode unknown 时交易 selector 不可消费。
21. observed_exchange_leverage 合法时正确保存。
22. leverage 缺失、零或非法时保存 null，不伪造。
23. COIN-M contract_size 正确保存。
24. COIN-M contract_size 缺失或非法时交易上下文不可消费。
25. margin_asset 找不到对应余额时交易上下文不可消费。
26. snapshot_hash 和 snapshot_set_hash 稳定。
27. 核心字段变化时 hash 变化。
28. UI 刷新失败不会修改任何正式交易编排关联。
29. Gateway 错误被映射为失败批次和脱敏 AlertEvent。
30. 不直接创建 HTTP client 或执行签名。
31. 不调用下单、订单查询或成交查询 Gateway。
32. Redis 不可用时不使用缓存账户事实放行交易。
```

## 29. 验收标准

满足以下条件才算通过：

```text
每个自动四小时编排起始账户边界请求都有自己新生成或幂等返回的 trade_preparation BinanceSyncRun；
即使后续无交易、权限关闭或策略链路提前结束，自动周期仍保存完整 trade_preparation 账户边界事实；
OrderPlan 与 RiskCheck 使用 Connector 显式传入的同一个批次；
本次同步失败时交易链路停止且不回退历史批次；
后台一键刷新仅刷新 active domain；
后台刷新与交易同步使用不同 sync_purpose；
后台刷新批次不会自动进入交易链路；
所有 Binance 请求均通过 Binance Gateway；
同步批次完整、原子发布、可 hash 校验且不可变；
USDS-M 与 COIN-M 事实不混用；
position_mode、observed_exchange_leverage 和 contract_size 语义明确；
测试不访问真实 Binance；
模块不生成订单、不执行风控、不下单、不修改交易所配置。
```

## 30. 当前不包含的能力

```text
同步全部账户域；
非 active domain 账户总览；
多账户并行同步；
多交易所账户抽象；
账户统一估值；
资金费同步；
收入流水同步；
订单对账；
成交对账；
WebSocket User Data Stream；
实时 current position 表；
自动资金划转；
自动修改杠杆、保证金模式或持仓模式。
```
