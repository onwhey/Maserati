# 核心业务合同

## 1. 文档目的

本文档统一定义跨模块核心对象、对象所有权、正式交易链路和全局状态语义。

模块需求可以扩展本模块拥有对象的字段和状态，但不得改变本文档定义的对象边界。

## 2. 正式业务链路

系统的自动交易闭环分为六段。

### 2.1 市场事实

```text
Kline
→ DataQualityResult
→ MarketSnapshot
```

数据存在可回补缺口时：

```text
DataQualityResult
→ BackfillRequest / BackfillRun
→ Kline
→ 新的 DataQualityResult
```

### 2.2 特征、信号与决策

```text
MarketSnapshot
→ FeatureSet / FeatureValue
→ AtomicSignalSet / AtomicSignalValue
→ DomainSignalSet / DomainSignalValue
→ MarketRegimeSnapshot
→ StrategyRouteDecision
→ StrategySignal
→ StrategySignalQualityResult
→ DecisionSnapshot
```

### 2.3 账户与价格事实

```text
BinanceSyncRun
→ BinanceAccountSnapshot / BinanceBalanceSnapshot / BinancePositionSnapshot / BinanceSymbolRuleSnapshot

PriceSnapshot
```

### 2.4 订单规划与风控

```text
DecisionSnapshot
+ BinanceSyncRun 及其事实快照
+ PriceSnapshot
→ OrderPlan
→ CandidateOrderIntent
→ RiskCheckResult
→ ApprovedOrderIntent
```

### 2.5 执行与交易事实

```text
ApprovedOrderIntent
→ ExecutionPreparationResult
→ PreparedOrderIntent
→ Execution
→ OrderSubmissionAttempt
→ 订单提交事实完成
```

订单提交后的生命周期事实：

```text
OrderSubmissionAttempt
→ OrderStatusSyncRecord
→ FillSyncResult
→ TradeFill / OrderFillSummary
```

LIMIT 订单到期仍未终态时的周期收尾事实：

```text
OrderSubmissionAttempt
→ OrderCycleCloseout
→ OrderCancelAttempt
→ OrderStatusSyncRecord
→ FillSyncResult
→ TradeFill / OrderFillSummary
```

### 2.6 编排、巡检与复盘

```text
OrchestrationRun
→ OrchestrationStepRun
→ OrchestrationBusinessObjectLink

ReviewDatasetRecord
→ ReviewDatasetExport

RuntimeGuardIssue
→ 人工确认、处理和关闭
```

通知与审计横跨所有阶段：

```text
AlertEvent
NotificationDeliveryAttempt
NotificationSuppression
AuditRecord
```

## 3. 核心对象所有权

| 对象 | 所有模块 | 核心语义 |
|---|---|---|
| Kline | DataCollection | Binance 已收盘 K 线事实 |
| DataQualityResult | DataQuality | 某个明确数据窗口是否允许下游消费 |
| BackfillRequest / BackfillRun | DataBackfill | 缺口回补请求与执行事实 |
| MarketSnapshot | MarketSnapshot | 一次分析周期使用的不可变市场证据快照 |
| FeatureSet / FeatureValue | FeatureLayer | 一个市场快照上的特征集合与单项特征值 |
| AtomicSignalSet / AtomicSignalValue | AtomicSignals | 一个特征集合上的原子判断集合与单项结果 |
| DomainSignalSet / DomainSignalValue | DomainSignals | 对同类原子信号聚合形成的领域判断事实 |
| MarketRegimeSnapshot | MarketRegime | 基于领域信号形成的市场环境判断快照 |
| StrategyRouteDecision | StrategyRouting | 基于市场环境选择本轮应执行策略的路由结果 |
| StrategyAnalysisRelease | StrategyAnalysisRelease | 一套已批准、可冻结运行的策略分析组件版本包 |
| StrategySignal | StrategySignals | 执行已选策略后形成的方向、强度、置信评分和证据，不是目标仓位或订单动作 |
| StrategySignalQualityResult | StrategySignalQuality | 策略信号是否具备下游消费条件 |
| DecisionSnapshot | DecisionSnapshot | 分析周期的目标仓位决策，不包含交易所订单参数 |
| BinanceSyncRun | BinanceAccountSync | 一次自动编排账户边界或后台展示账户事实同步批次 |
| BinanceAccountSnapshot / BinanceBalanceSnapshot / BinancePositionSnapshot / BinanceSymbolRuleSnapshot | BinanceAccountSync | 同一同步批次内的账户、余额、持仓和交易规则事实 |
| PriceSnapshot | PriceSnapshot | 通过 Binance REST 主动获取并按不透明 business_request_key 幂等创建的 mark price 事实 |
| OrderPlan | OrderPlan | 将目标仓位与当前仓位差异转换为候选订单的规划结果 |
| CandidateOrderIntent | OrderPlan | 尚未通过风控的候选订单意图 |
| OrderPlanActiveLock | OrderPlan | 防止同一市场身份存在并行冲突订单链路的保护锁 |
| RiskCheckResult | RiskCheck | 对候选订单意图的风控结果 |
| ApprovedOrderIntent | RiskCheck | 风控允许的订单意图，仍不可直接提交交易所 |
| ExecutionPreparationResult | ExecutionPreparation | 执行前校验结果 |
| PreparedOrderIntent | ExecutionPreparation | 参数已经冻结、具有有效期、等待唯一一次提交的执行请求 |
| OrderSubmissionAttempt | Execution | 一次真实订单提交尝试及其确定或不确定结果 |
| OrderCancelAttempt | OrderCycleCloseout | 一次针对既有限价订单的受控撤单尝试 |
| OrderStatusSyncRecord | OrderStatusSync | 对一条提交尝试进行交易所订单状态查询的事实记录 |
| FillSyncResult | FillSync | 一次正式成交查询、恢复同步及其完整性结果 |
| TradeFill | FillSync | 交易所逐笔成交事实 |
| OrderFillSummary | FillSync | 一条提交尝试关联成交的幂等汇总 |
| OrchestrationRun | PipelineOrchestrator | 一轮 UTC 业务流程的编排和审计主记录 |
| OrchestrationStepRun | PipelineOrchestrator | 一轮编排中某个业务步骤的执行记录 |
| OrchestrationBusinessObjectLink | PipelineOrchestrator | 编排、步骤与业务对象的一对多审计索引 |
| RuntimeGuardIssue | RuntimeGuard | 巡检发现的待人工关注问题 |
| ReviewDatasetRecord | ReviewDataset | 一个已关闭 UTC 4 小时周期的复盘数据索引，绑定被复盘编排、开始边界编排和结束边界编排 |
| ReviewDatasetExport | ReviewDataset | 一次受控复盘数据导出请求、导出清单和下载审计事实 |
| AlertEvent | Notifications | 系统事件、异常和交易状态通知事实 |
| NotificationDeliveryAttempt | Notifications | 一条 AlertEvent 向外部通知渠道投递的一次尝试记录 |
| NotificationSuppression | Notifications | 一条 AlertEvent 未进行外部投递的明确抑制原因 |
| AuditRecord | 对应业务模块或统一审计能力 | 人工操作和高风险状态变更记录 |

## 4. 不可混用的对象

```text
AtomicSignalSet 不等于 DomainSignalSet。
DomainSignalSet 不等于 MarketRegimeSnapshot。
MarketRegimeSnapshot 不等于 StrategyRouteDecision。
StrategyRouteDecision 不等于 StrategySignal。
StrategySignal 不等于 DecisionSnapshot。
DecisionSnapshot 不等于 CandidateOrderIntent。
OrderPlan 不等于 RiskCheckResult。
CandidateOrderIntent 不等于 ApprovedOrderIntent。
ApprovedOrderIntent 不等于 PreparedOrderIntent。
PreparedOrderIntent 不等于 OrderSubmissionAttempt。
OrderSubmissionAttempt 不等于交易所完整订单状态。
OrderCancelAttempt 不等于交易所订单终态。
OrderStatusSyncRecord 不等于 TradeFill。
TradeFill 不等于 BinancePositionSnapshot。
BinanceSyncRun 不等于交易执行。
PriceSnapshot 不等于策略行情快照，也不等于实际成交价；不同业务请求生成的 PriceSnapshot 不得被 Connector 混用。
RuntimeGuardIssue 不等于原业务对象的状态。
ReviewDatasetRecord 不等于交易决策、策略评估结论或生产策略变更指令。
ReviewDatasetExport 不等于复盘结论或大模型报告。
NotificationDeliveryAttempt 不等于 AlertEvent 本身。
NotificationSuppression 不等于投递失败。
```

## 5. 决策与订单边界

`DecisionSnapshot` 只表达目标仓位语义，例如目标方向和 `target_position_ratio`。

`DecisionSnapshot` 不得包含：

```text
ENTER_LONG
ENTER_SHORT
EXIT
HOLD
订单 side
订单 quantity
reduce_only
client_order_id
交易所 endpoint
交易所订单类型参数
```

`NO_TRADE` 和 `NO_TARGET_CHANGE` 只能表示本轮不进入价格与订单链路，不得作为订单动作传给 RiskCheck、ExecutionPreparation 或 Execution。

自动四小时编排在起始阶段必须先执行本轮 `trade_preparation` Binance Account Sync，保存周期复盘所需的账户边界事实。后续即使形成 `NO_TRADE`、`NO_TARGET_CHANGE`、`no_strategy`、真实交易权限关闭或其他正常无交易结果，也不得补造或改用其他账户快照。

该账户同步由编排衔接器调用。DecisionSnapshot 不得直接调用 Binance Account Sync，也不得读取同步结果。

`OrderPlan` 是唯一允许把目标仓位转换成 `CandidateOrderIntent` 的模块。

`RiskCheck` 只审批既有 `CandidateOrderIntent`，不得重新设计订单。风控允许时生成 `ApprovedOrderIntent`；拒绝、阻断或失败时不得生成。

`ExecutionPreparation` 只消费 `ApprovedOrderIntent`，执行价格、时效、账户事实、持仓事实、交易规则、ActiveLock 和上游身份校验，并冻结为 `PreparedOrderIntent`。

`Execution` 是唯一允许向交易网关提交真实订单的模块，只消费有效且未过期的 `PreparedOrderIntent`。

同一个 `PreparedOrderIntent` 只能提交一次。

无论提交前失败、提交后超时、交易所明确拒绝、HTTP 429、HTTP 5xx、响应损坏或结果无法判断，都不得对同一个 `PreparedOrderIntent` 再次调用订单提交接口。

后续如需再次交易，必须在 ActiveLock 安全释放后，由新的编排运行重新经过 DecisionSnapshot、OrderPlan、RiskCheck、ExecutionPreparation 和 Execution 生成新的订单链路。

`OrderCycleCloseout` 只允许对既有、已提交且仍未终态的 LIMIT 订单执行周期收尾撤单。撤单必须形成 `OrderCancelAttempt`，但 `OrderCancelAttempt` 只描述撤单请求本身，不等于订单终态，也不等于成交事实。

撤单后仍必须通过 `OrderStatusSyncRecord` 确认交易所订单状态，通过 `FillSyncResult / TradeFill / OrderFillSummary` 确认成交事实。OrderCycleCloseout 不得提交新订单，不得修改原订单，不得追单，不得释放 ActiveLock。

## 6. 订单提交结果与订单状态

`OrderSubmissionAttempt` 只描述提交动作本身：

```text
accepted
rejected
unknown
failed_before_submit
blocked_before_submit
```

`accepted` 只表示交易所接受了请求，不表示订单已经成交。

`unknown` 表示无法确认交易所是否收到请求。该状态不得自动重试提交、不得自动释放订单保护锁、不得推断成功或失败。

交易所订单的 `NEW`、`PARTIALLY_FILLED`、`FILLED`、`CANCELED`、`EXPIRED`、`REJECTED` 等状态由 `OrderStatusSyncRecord` 保存。

## 7. 成交与持仓事实

`FillSync` 保存逐笔成交和订单成交汇总，不直接修改账户或持仓快照。

持仓事实只能来自明确的账户同步结果。后续订单规划必须使用本轮自动编排起始账户边界同步绑定的 `BinancePositionSnapshot`，不得根据本地成交汇总自行推导交易所持仓。

## 7.1 复盘数据事实

`ReviewDatasetRecord` 是后台或只读 API 生成的复盘数据索引，不是自动交易主链路的必跑步骤。

它基于一个已关闭 UTC 4 小时周期内已经落库的编排、策略、账户、价格、订单、成交、告警和巡检事实，整理出可导出的复盘数据范围。

例如：

```text
00:00 - 04:00 复盘数据
归属于 00:05 自动 OrchestrationRun
结束账户事实来自 04:05 自动 OrchestrationRun
```

ReviewDataset 缺失不等于自动交易主链路异常，不由 RuntimeGuard 巡检。

ReviewDataset 只提供事实数据，不判断策略是否正确，不在系统内调用大模型，也不把复盘结论写回生产交易链路。

## 8. ActiveLock 合同

`OrderPlanActiveLock` 的业务身份至少由以下字段确定：

```text
exchange
market_type
account_domain
symbol
```

同一业务身份只允许存在一条有效的冲突订单链路。

锁状态只能通过 `OrderPlan` 所属的统一锁服务修改。RiskCheck、ExecutionPreparation、Execution、OrderStatusSync 和 FillSync 只能调用该服务，不得直接更新锁状态。

可以自动释放锁的事实必须能够证明：

```text
订单在提交前已经明确终止；
或交易所明确拒绝订单；
或交易所订单已经进入明确终态，且所需成交事实已经同步完成；
或经过授权的人工收尾。
```

以下情况不得自动释放：

```text
提交结果 unknown；
订单状态 unknown 或 not_found；
订单状态 NEW；
订单状态 PARTIALLY_FILLED；
成交同步 unknown；
成交同步成功但无法证明订单已经终态；
仅凭账户余额或持仓变化进行倒推。
```

## 9. 真实交易运行权限

真实交易权限由 `.env` 部署硬权限和 MySQL 后台运行开关共同决定。

```text
effective_real_trading_permission = deployment_real_trading_permission AND runtime_real_trading_permission
```

真实交易默认关闭。

OrderPlanStepAdapter 在进入 OrderPlan 前判断一次最终权限。权限关闭或不可读取时不得调用 OrderPlan、生成 CandidateOrderIntent 或取得 ActiveLock；检查通过后，本轮后续步骤不重新读取后台开关。

任何前端、人工命令、定时任务或恢复入口都不得绕过正式交易链路和该次权限检查。

## 10. 全局结果语义

模块可以按自身需要定义更细状态，但必须映射到以下结果类别：

```text
succeeded：业务动作成功完成。
no_action：业务正常完成，但无需产生下游动作。
skipped：因明确条件不适用而跳过。
blocked：业务安全条件不满足，主动阻断。
denied：风控明确拒绝候选订单。
unknown：外部结果无法确认，必须保守处理。
failed：系统异常或不可预期错误。
```

`blocked`、`denied`、`no_action` 和 `skipped` 都不是系统异常。

`unknown` 不得被自动映射为成功或失败。

## 11. 追溯合同

正式交易链路中的每个对象必须通过真实业务外键直接或间接追溯到：

```text
DecisionSnapshot
BinanceSyncRun
PriceSnapshot
OrderPlan
CandidateOrderIntent
RiskCheckResult
ApprovedOrderIntent
PreparedOrderIntent
OrderSubmissionAttempt
OrderCancelAttempt
```

编排追踪由以下对象单独维护：

```text
OrchestrationRun
OrchestrationStepRun
OrchestrationBusinessObjectLink
```

主交易链路对象不得把 `OrchestrationRun.id` 当作正式业务外键或下游输入。交易链路的正式追溯仍通过真实业务外键完成。

`OrchestrationBusinessObjectLink` 只提供一轮运行的快捷审计索引，不替代业务外键。

复盘、巡检、后台查询和审计对象可以保存 `OrchestrationRun` 引用，但只能用于展示、审计、复盘和人工排查，不得作为交易模块的正式输入。

成交记录还必须追溯到对应的订单状态查询和交易所订单编号。

人工操作必须记录操作人、操作来源、修改前状态、修改后状态、原因、结果和 `trace_id`。

## 12. 外部能力边界

```text
所有 Binance REST 请求必须通过 BinanceGateway 的受限接口。
业务模块不得直接创建 Binance HTTP client、生成签名或拼接 endpoint。
BinanceAccountSync 只能通过账户只读和公共市场接口读取账户、余额、仓位和交易规则。
PriceSnapshot 只能读取并固化价格事实。
Execution 是唯一可以调用订单提交接口的业务模块。
OrderStatusSync 只能调用订单状态查询接口并保存订单状态。
FillSync 只能调用成交查询接口并保存成交事实。
Notifications 只能通知和记录投递状态，不能触发交易。
ReviewDataset 只能读取已落库事实并生成复盘数据集，不能影响实时交易。
当前正式复盘路径不在交易系统内调用大模型。
如后续重新引入系统内大模型复盘，必须先新增独立需求，不得复用 ReviewDataset 私自保存大模型结论。
AlertEvent 必须形成明确通知交接：需要外部投递时创建 NotificationDeliveryAttempt；不外部投递时创建 NotificationSuppression 或等价抑制记录。
RuntimeGuard 可以巡检通知投递状态，但不得修改 NotificationDeliveryAttempt、不得创建新投递尝试、不得直接调用 Hermes。
```
