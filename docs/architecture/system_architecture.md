# 系统架构总览

## 1. 文档目的

本文档定义当前系统的工程架构总览，用于把 `requirements` 中已经确定的业务边界落到代码组织、模块调用、数据存储、任务调度和外部访问边界上。

本文档用于回答：

```text
系统整体如何分层；
主交易链路如何落到 service / domain / task / model；
编排层、业务层、Gateway、后台、巡检和复盘如何隔离；
MySQL、Redis、Celery、Gateway 各自处于什么位置；
哪些调用方向允许，哪些调用方向禁止；
代码实现时应该优先放在哪一层。
```

本文档不定义：

```text
具体数据库字段；
具体 Django app 名称；
具体 Celery task 名称；
具体 REST API 路径；
具体策略算法；
具体风控规则；
具体订单数量公式；
具体前端页面组件。
```

具体业务语义以 `docs/requirements/*.md` 为准。

## 2. 架构总原则

系统架构必须优先保证：

```text
数据可信；
链路可追溯；
策略分析与交易执行隔离；
目标仓位与订单意图隔离；
风控不可绕过；
真实交易权限不可绕过；
订单提交不可重试；
异常状态保守处理；
复盘可以解释系统行为。
```

核心原则：

```text
上游模块不得反向依赖下游模块；
业务模块不得绕过自身上游事实；
业务模块不得直接访问不属于自己的外部服务；
入口层不得承载复杂业务逻辑；
Django model 不承载复杂业务逻辑；
Celery task 不串完整业务链路；
management command 不直接写交易逻辑；
所有 Binance 请求经过 BinanceGateway；
所有 DeepSeek 请求经过 DeepSeekGateway；
业务模块只写 AlertEvent，不直接发送 Hermes；
MySQL 是核心业务事实主存储；
Redis 只做短期缓存、锁、限频、Celery 和短期状态；
所有核心业务时间使用 UTC。
```

## 3. 系统业务分层

系统按业务责任分为以下层级：

```text
行情数据层
→ 市场证据层
→ 特征与信号层
→ 策略分析层
→ 目标仓位决策层
→ 账户与价格事实层
→ 订单计划与风控层
→ 执行准备与订单提交层
→ 订单状态与成交同步层
→ 编排、巡检、通知、后台和复盘层
```

### 3.1 行情数据层

包含：

```text
DataCollection
DataQuality
DataBackfill
```

职责：

```text
采集 Binance USDS-M BTCUSDT 已收盘 4h / 1d K 线；
校验数据连续性、完整性和可消费性；
发现缺口后执行受控回补；
只提供行情事实，不生成交易信号。
```

数据采集域固定，不受 active market domain 影响。

### 3.2 市场证据层

包含：

```text
MarketSnapshot
```

职责：

```text
固化一次分析周期使用的市场证据；
绑定已通过质量检查的数据窗口；
为 FeatureLayer 提供不可变输入；
保证后续复盘可以知道当时到底使用了哪些行情事实。
```

MarketSnapshot 不计算特征、不生成信号、不读取账户、不下单。

### 3.3 特征与信号层

包含：

```text
FeatureLayer
AtomicSignal
DomainSignal
MarketRegime
```

职责：

```text
FeatureLayer 只计算特征；
AtomicSignal 把特征转换为最小市场判断；
DomainSignal 聚合同类原子信号，形成领域级市场事实；
MarketRegime 基于领域事实识别市场环境。
```

这一层不得生成订单动作，不得读取账户事实，不得访问 Binance 交易接口。

### 3.4 策略分析层

包含：

```text
StrategyRouting
StrategySignal
StrategySignalQuality
StrategyCalculator
StrategyAnalysisRelease
```

职责：

```text
StrategyRouting 基于 MarketRegime 和路由配置选择本轮策略；
StrategySignal 执行已选策略，生成标准化策略判断；
StrategySignalQuality 判断策略信号是否允许进入下游；
StrategyCalculator 承载纯算法计算规则；
StrategyAnalysisRelease 冻结正式主链路允许运行的版本组合。
```

正式自动编排只能运行已批准的 `StrategyAnalysisRelease`。

策略分析层不得读取账户余额、持仓、订单状态，不得生成 CandidateOrderIntent，不得真实下单。

### 3.5 目标仓位决策层

包含：

```text
DecisionSnapshot
DecisionPolicy / DecisionPolicyCalculator
```

职责：

```text
消费通过质量检查的 StrategySignal；
生成目标仓位意图；
表达 target_intent / target_position_ratio；
保留策略证据、原因和版本信息。
```

DecisionSnapshot 不包含：

```text
订单 side；
订单 quantity；
reduce_only；
client_order_id；
交易所 endpoint；
交易所订单类型参数。
```

DecisionSnapshot 不读取账户、余额、持仓或 BinanceSyncRun。

### 3.6 账户与价格事实层

包含：

```text
BinanceGateway
Binance Account Sync
PriceSnapshot
```

职责：

```text
BinanceGateway 统一 Binance REST 访问边界；
Binance Account Sync 只读同步账户、余额、持仓和交易规则事实；
PriceSnapshot 主动请求 Binance mark price，并固化本轮交易价格事实。
```

交易链路只能使用 `trade_preparation` 账户快照。

自动四小时编排在起始阶段必须执行一次 `trade_preparation` 账户同步，以保存绩效周期边界事实，并作为后续可能进入订单链路时的账户事实。`NO_TARGET_CHANGE`、`NO_TRADE` 或其他正常无交易结果不得触发第二次账户同步。

后台展示只能使用 `ops_display` 账户快照，不得进入交易链路。

一轮 OrchestrationRun 只能使用一个 PriceSnapshot。

不同批次价格快照不得混用。

### 3.7 订单计划与风控层

包含：

```text
OrderPlan
CandidateOrderIntent
RiskCheck
ApprovedOrderIntent
OrderPlanActiveLock
```

职责：

```text
OrderPlan 把 DecisionSnapshot、账户事实和价格事实转换为 CandidateOrderIntent；
CandidateOrderIntent 是待风控审批的候选订单意图；
RiskCheck 只审批 CandidateOrderIntent；
ApprovedOrderIntent 是风控通过后的订单意图；
OrderPlanActiveLock 防止同一交易身份出现并行冲突订单链路。
```

OrderPlanStepAdapter 必须在调用 OrderPlan 前完成真实交易权限检查。

权限检查未通过时不得调用 OrderPlan，不得取得 ActiveLock。

RiskCheck 不得自动缩单，不得任意修改订单数量，只能选择 OrderPlan 已生成的 primary 或 fallback_reduce_only。

### 3.8 执行准备与订单提交层

包含：

```text
ExecutionPreparation
PreparedOrderIntent
Execution
OrderSubmissionAttempt
```

职责：

```text
ExecutionPreparation 对 ApprovedOrderIntent 做最终检查和 price guard；
PreparedOrderIntent 是参数冻结且等待唯一一次提交的执行请求；
Execution 是唯一允许提交真实订单的模块；
OrderSubmissionAttempt 记录一次提交尝试及其结果。
```

订单提交规则：

```text
同一个 PreparedOrderIntent 只能提交一次；
订单提交绝不重试；
Gateway、业务层、Celery、编排层、management command 和人工入口均不得重试订单提交；
unknown 不得推断成功或失败；
unknown 必须进入 OrderStatusSync 查询。
```

### 3.9 订单状态与成交同步层

包含：

```text
OrderStatusSync
OrderStatusSyncRecord
FillSync
TradeFill
OrderFillSummary
```

职责：

```text
OrderStatusSync 查询交易所订单状态；
OrderStatusSyncRecord 保存状态查询事实；
FillSync 查询、保存和汇总成交事实；
TradeFill 保存逐笔成交；
OrderFillSummary 保存一条提交尝试关联成交的幂等汇总。
```

OrderStatusSync 不重新提交订单，不生成 TradeFill。

FillSync 不提交订单，不生成订单状态，不根据成交汇总直接生成账户快照。

OrderStatusSync 和 FillSync 不自行拥有后台页面、通用人工查询入口或对应额外运行开关。`ops_console.md` 已授权的受控补查与补同步由 OpsConsole 提供权限、明确对象、二次确认和审计入口，实际动作仍调用对应业务 service。

## 4. 工程分层

代码应按工程职责分层：

```text
entrypoint 层
application service 层
domain / calculator 层
repository / selector 层
gateway / client 层
model 层
```

### 4.1 entrypoint 层

包含：

```text
Celery task
Celery Beat schedule
management command
HTTP API view
OpsConsole 后端接口
```

只能负责：

```text
解析参数；
生成或传递 trace_id；
设置 trigger_source；
校验基础权限；
调用 application service；
返回结果摘要。
```

不得：

```text
写复杂业务逻辑；
直接访问 Binance；
直接访问 DeepSeek；
直接发送 Hermes；
直接提交订单；
直接释放 ActiveLock；
直接修改业务状态；
绕过 OrderPlanStepAdapter 的真实交易权限检查；
自动重试订单提交。
```

### 4.2 application service 层

职责：

```text
承载一个完整业务用例；
组织 domain / calculator；
控制事务边界；
调用 repository / selector / gateway；
处理幂等、状态流转、错误记录和 AlertEvent。
```

application service 可以协调多个 domain service，但不得把完整系统主链路塞成一个超大 service。

### 4.3 domain / calculator 层

职责：

```text
承载纯业务判断；
承载特征、原子信号、领域信号、市场环境、策略、目标仓位、风控、订单计划、price guard 等核心规则；
尽量不依赖 Django ORM 细节；
不直接访问外部服务。
```

算法可变部分应与业务流程解耦。策略分析相关算法统一按 `strategy_calculator.md` 和各模块 requirements 管理。

### 4.4 repository / selector 层

职责：

```text
封装数据库读写；
隔离 ORM 查询细节；
提供稳定查询接口；
保证核心业务对象通过明确 service / repository 创建或状态流转。
```

repository / selector 不得发起外部服务请求。

### 4.5 gateway / client 层

职责：

```text
封装外部服务访问；
统一认证、签名、超时、限频、错误分类、技术重试、脱敏日志和测试替身。
```

包含：

```text
BinanceGateway
DeepSeekGateway
Hermes / Notification channel client
```

Gateway 只返回技术事实，不拥有业务对象状态，不替代业务模块写业务结果。

### 4.6 model 层

Django model 只负责：

```text
数据结构；
字段约束；
索引约束；
最小数据校验；
中文说明。
```

禁止在 model 中实现：

```text
策略逻辑；
风控逻辑；
订单计划逻辑；
交易执行逻辑；
外部请求；
Hermes 发送；
大模型调用；
复杂状态机。
```

## 5. 主链路架构

正式自动主链路：

```text
Binance Account Sync（自动四小时账户边界，编排起始步骤）
→ DataCollection
→ DataQuality
→ 必要时 DataBackfill 与重新质检
→ MarketSnapshot
→ FeatureLayer
→ AtomicSignal
→ DomainSignal
→ MarketRegime
→ StrategyRouting
→ StrategySignal
→ StrategySignalQuality
→ DecisionSnapshot
→ TARGET_POSITION：PriceSnapshot
→ OrderPlanStepAdapter 真实交易权限检查
→ OrderPlan
→ CandidateOrderIntent
→ RiskCheck
→ ApprovedOrderIntent
→ ExecutionPreparation
→ PreparedOrderIntent
→ Execution
→ OrderSubmissionAttempt
→ OrderStatusSync
→ FillSync
→ 订单状态与成交事实同步完成
或 NO_TARGET_CHANGE / NO_TRADE：正常结束，不进入 PriceSnapshot 或订单链路
```

该链路由 PipelineOrchestrator 和 OrchestrationBusinessConnector 推进。

编排层只理解统一结果，不解释业务模块内部状态。

业务模块返回值由业务衔接器转换为统一结果后交给编排层。

任何模块不得跳过中间强边界直接调用下游模块。

## 6. 编排架构

编排相关对象：

```text
OrchestrationRun
OrchestrationStepRun
OrchestrationBusinessObjectLink
```

PipelineOrchestrator 负责：

```text
创建一轮运行；
冻结步骤定义；
调用 OrchestrationBusinessConnector；
保存步骤统一结果；
保存业务对象索引；
根据 flow_action 推进、等待、停止或完成。
```

OrchestrationBusinessConnector 负责：

```text
定义可编排业务模块；
调用业务 service；
理解业务模块原始返回；
转换为统一 normalized_status；
转换为统一 flow_action；
返回业务对象索引。
```

编排层不得：

```text
直接调用 Binance；
直接调用 DeepSeek；
直接修改业务对象；
直接释放 ActiveLock；
直接提交订单；
绕过业务 service。
```

主交易业务对象不得把 OrchestrationRun 当正式业务外键或下游输入。

业务对象之间的正式追溯必须依赖真实业务外键。

OrchestrationBusinessObjectLink 只提供一轮运行的快捷审计索引。

## 7. 真实交易权限架构

真实交易权限不是独立业务模块。

权限来源：

```text
.env / Django settings = 真实交易部署级硬权限
MySQL = 后台真实交易运行开关
```

有效权限：

```text
effective_real_trading_permission = deployment_real_trading_permission AND runtime_real_trading_permission
```

架构规则：

```text
ProjectFoundation 提供基础配置读取、保存、审计和 fail-closed 能力；
OpsConsole 只能修改 MySQL 后台运行开关；
OpsConsole 不能写 .env；
OpsConsole 不能管理 API key；
OpsConsole 不能热切 active market domain；
OrderPlanStepAdapter 在调用 OrderPlan 前检查一次最终权限；
检查未通过时不调用 OrderPlan，不取得 ActiveLock；
检查通过后，本轮后续步骤不重新读取 MySQL 开关；
Execution、OrderStatusSync、FillSync 不重新读取真实交易运行开关。
```

## 8. 外部 Gateway 架构

### 8.1 BinanceGateway

BinanceGateway 是系统访问 Binance REST API 的唯一基础设施边界。

能力方向：

```text
受限账户只读接口；
受限公共市场接口；
受限订单提交接口；
受限订单查询接口；
受限成交查询接口。
```

所有 Binance 访问必须经过 BinanceGateway。

业务模块不得直接创建 Binance HTTP client、不得直接生成签名、不得拼接 endpoint。

BinanceGateway 涉及账户、价格、订单、成交和交易规则的调用必须携带并校验 active market domain。

订单提交接口不自动重试。

### 8.2 DeepSeekGateway

DeepSeekGateway 是系统访问 DeepSeek API 的唯一基础设施边界。

只有 AIReview 允许作为业务调用方。

OpsConsole 不得直接调用 DeepSeekGateway，只能通过 AIReview service 创建和查看复盘请求。

DeepSeekGateway 不选择复盘范围，不生成交易结论，不修改策略、风控、真实交易运行配置或订单事实。

业务调用方只能选择 model profile 套餐编号，不传完整模型配置。

### 8.3 Notifications / Hermes

业务模块只写 AlertEvent。

Notifications 根据 AlertEvent 创建 NotificationDeliveryAttempt 或 NotificationSuppression。

Hermes 只负责外部通知，不触发交易。

通知失败不得回滚业务事实。

通知成功不得触发业务动作。

## 9. 存储架构

### 9.1 MySQL

MySQL 是核心业务主存储。

必须保存：

```text
行情事实；
数据质量结果；
数据回补事实；
市场快照；
特征；
原子信号；
领域信号；
市场环境；
策略路由；
策略信号；
策略分析发布版本；
目标仓位决策；
账户事实；
价格事实；
订单计划；
候选订单意图；
风控结果；
风控批准订单意图；
执行准备结果；
订单提交尝试；
订单状态同步记录；
成交事实；
编排运行；
运行巡检问题；
绩效记录；
复盘请求、复盘数据包、复盘调用尝试、复盘报告、复盘发现和人工建议；
AlertEvent；
NotificationDeliveryAttempt；
NotificationSuppression；
审计记录；
真实交易运行开关。
```

### 9.2 Redis

Redis 只能用于：

```text
缓存；
分布式锁；
Celery broker；
Celery result backend；
短期幂等控制；
短期任务状态；
限流计数；
短期特征序列缓存；
PriceSnapshot 短期缓存；
Gateway 限频、冷却和熔断状态；
Notifications 冷却、聚合和投递防重复。
```

Redis 不得作为核心业务事实唯一存储。

Redis 不可用时不得用过期缓存放行真实交易。

## 10. Celery 与调度架构

Celery task 只作为异步入口。

Celery Beat 只作为定时调度入口。

任务入口只能：

```text
解析参数；
生成或传递 trace_id；
设置 trigger_source；
调用 application service；
输出结构化摘要。
```

禁止：

```text
在 Celery task 中直接写完整业务流程；
在 Celery task 中直接访问 Binance；
在 Celery task 中直接访问 DeepSeek；
在 Celery task 中直接发送 Hermes；
在 Celery task 中绕过 service；
在 Celery task 中自动重试订单提交。
```

订单提交相关任务重复执行时，只能读取已有 OrderSubmissionAttempt，不得再次调用订单提交 Gateway。

## 11. RuntimeGuard 架构

RuntimeGuard 是独立巡检能力，不随主链路步骤内联执行。

RuntimeGuard 覆盖：

```text
自动编排主链路；
订单链路卡住状态；
ActiveLock 风险状态；
通知投递状态。
```

RuntimeGuard 不覆盖：

```text
AIReview；
PerformanceMetrics；
后台人工补算；
后台人工复盘；
普通后台页面功能。
```

RuntimeGuard 不得修改业务对象，不得释放锁，不得补跑业务，不得直接发送 Hermes。

RuntimeGuard 可按独立 Celery Beat 周期运行。它的周期不等于交易周期，不应与 4 小时主编排冲突，因为它只读巡检和记录问题，不推进业务链路。

## 12. 后台与复盘架构

### 12.1 OpsConsole

OpsConsole 是运维控制台和复盘工作台。

OpsConsole 可以通过后端 service：

```text
查看 Dashboard；
查看 OrchestrationRun；
查看订单链路；
查看账户展示；
查看 PerformanceMetrics；
查看 RuntimeGuardIssue；
查看 AlertEvent；
操作真实交易运行开关；
创建 AIReview 请求；
查看 AIReview 报告；
查看审计日志。
```

OpsConsole 不得：

```text
直接访问数据库；
直接调用 BinanceGateway；
直接调用 DeepSeekGateway；
直接提交订单；
直接释放 ActiveLock；
直接写业务表；
管理 API key；
写 .env；
热切 active market domain。
```

### 12.2 PerformanceMetrics

PerformanceMetrics 是后台一键补算的周期绩效复盘能力。

它基于已落库事实和相邻自动边界 `trade_preparation` 账户快照计算 UTC 4 小时周期浮动收益。

PerformanceMetrics 不请求 Binance，不读取 ops_display，不影响交易主流程，不由 RuntimeGuard 巡检。

### 12.3 AIReview

AIReview 是离线大模型复盘能力。

AIReview 读取已落库事实，生成脱敏复盘数据包，通过 DeepSeekGateway 调用 DeepSeek，并保存报告、发现和人工建议。

AIReview 不参与实时交易，不自动修改策略，不自动修改真实交易运行配置，不自动下单。

## 13. AlertEvent 与审计架构

正式交易相关关键事件必须写 AlertEvent。

AlertEvent 是业务事件，不等于外部通知投递结果。

外部通知交接：

```text
AlertEvent
→ NotificationDeliveryAttempt
或
→ NotificationSuppression
```

人工操作和高风险状态变更必须写 AuditRecord 或等价审计记录。

至少覆盖：

```text
真实交易运行开关变更；
人工 ActiveLock 收尾；
PerformanceMetrics 后台一键补算；
AIReview 请求创建；
通知路由变更；
高风险状态变更。
```

审计记录不得替代业务对象状态。

## 14. trace_id、trigger_source 与幂等架构

`trace_id` 用于技术追踪，不作为业务幂等键，不替代业务外键。

`trigger_source` 用于记录任务触发来源。

业务幂等键用于同一业务动作重复执行时返回同一个业务事实。

规则：

```text
入口层如未传入 trace_id，应生成 trace_id；
下游 service 必须显式传递 trace_id；
Gateway 调用上下文必须携带 trace_id；
AlertEvent 必须记录 trace_id；
审计记录必须记录 trace_id；
同一业务幂等键重复执行不得生成重复业务对象；
Redis 不得作为唯一幂等事实来源。
```

## 15. Django app 划分原则

具体 app 名称由后续开发计划确定。

划分原则：

```text
按业务边界拆分，而不是按技术层随意拆分；
一个 app 不承担多个架构层职责；
strategy 相关 app 不直接依赖 execution gateway；
notifications app 不反向触发交易；
order_plan / risk_check 不直接依赖 WebSocket；
execution 是唯一真实下单入口。
```

建议方向：

```text
market_data
feature_layer
strategy_analysis
decision_snapshot
binance_gateway
binance_account_sync
price_snapshot
order_plan
risk_check
execution_preparation
execution
tracking
pipeline_orchestrator
runtime_guard
notifications
performance_metrics
ops_console
ai_review
common
```

实际名称以 plans 和代码实现阶段确认结果为准。

## 16. 回测、dry-run 和 real 的隔离

当前阶段不实现模拟交易运行模式。系统只要求回测、dry-run 和 real trading 隔离。

规则：

```text
dry-run 不写正式交易对象，不进入真实下游；
回测结果不得写入正式 real trading 业务表；
real trading 只能消费真实账户事实、真实价格事实和真实订单链路对象。
```

回测和 real 应尽量复用同一套核心业务规则，但必须隔离数据源、执行结果和账户事实。后续如要新增模拟交易运行模式，必须先补充独立需求和架构，不得在当前 real trading 链路内临时模拟。

## 17. 禁止提前实现的架构能力

当前阶段不得提前实现：

```text
多交易所；
多 active market domain 同时交易；
后台热切 active market domain；
复杂投资组合管理；
复杂多策略权重分配；
机器学习交易模型；
大模型实时交易决策；
大模型生成订单；
自动参数优化；
自动上线策略；
自动禁用策略；
复杂报表系统；
自动调整杠杆；
自动修改保证金模式；
自动资金划转；
自动交易修复；
.env 在线编辑；
API key 后台管理；
Hermes 入站交易命令；
通知触发交易；
未由 OpsConsole 需求授权的通用订单状态补查入口；
未由 OpsConsole 需求授权的通用成交补同步入口。
```

## 18. 架构验收方向

实现代码时，至少应能验证：

```text
入口层只调用 service；
业务逻辑主要位于 service / domain / calculator；
Django model 不承载复杂业务逻辑；
所有 Binance 请求经过 BinanceGateway；
所有 DeepSeek 请求经过 DeepSeekGateway；
业务模块不直接发送 Hermes；
主链路不能跳过 OrderPlan、RiskCheck、ExecutionPreparation、Execution；
真实交易权限只在进入 OrderPlan 前检查一次；
Execution 不重试订单提交；
OrderStatusSync 和 FillSync 不自行定义后台人工入口或额外开关；OpsConsole 受控入口只调用对应业务 service；
RuntimeGuard 只读巡检，不修改业务对象；
PerformanceMetrics 和 AIReview 不属于自动交易主链路；
MySQL 保存核心事实；
Redis 不作为核心事实唯一存储。
```

## 19. 最终结论

本系统架构的核心目标是：

```text
把可信行情事实、策略分析、目标仓位决策、账户与价格事实、订单计划、风控审批、执行准备、受控提交、状态追踪、成交同步、巡检、通知、后台和复盘组织成清晰分层、不可绕过、可追溯、可审计、可测试的自动交易闭环。
```

一句话：

```text
系统可以自动交易，但架构必须保证每一步都有明确事实来源、清晰模块边界、安全准入、审计记录和复盘依据。
```
