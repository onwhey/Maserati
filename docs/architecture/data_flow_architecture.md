# 数据流架构

## 1. 文档目的

本文档定义系统中的业务事实、控制信息、审计信息和短期缓存如何产生、传递、落库和被下游消费。

本文档用于回答：

```text
一份数据最初从哪里产生；
哪个模块拥有并落库这份数据；
下游通过什么明确对象读取它；
哪些数据可以进入正式主链路；
哪些数据只能用于编排、巡检、后台或复盘；
MySQL、Redis、Celery 和外部 Gateway 在数据流中分别承担什么职责；
发生 blocked、unknown 或 failed 时，数据流在哪里停止。
```

本文档不定义：

```text
具体数据库表名和字段类型；
具体 Django app 名称；
具体 API 路径；
具体 Celery task 名称；
具体算法公式；
具体前端页面结构。
```

模块业务合同以 `docs/requirements/*.md` 为准。

如果本文档与 requirements 冲突，以 requirements 为准，并停止实现、向用户确认。

## 2. 数据流总原则

系统数据流必须遵守：

```text
外部返回先经过 Gateway，再由业务 service 转换为本模块拥有的业务事实；
业务模块只消费明确的直接上游对象，不按“数据库最新记录”猜测输入；
正式下游只读取已经落入 MySQL 且明确允许消费的业务对象；
内存计算结果、dry-run 结果、后台研究结果和 Redis 缓存不得进入正式下游；
主链路对象通过真实业务外键追溯，不通过编排编号猜测业务关系；
OrchestrationBusinessObjectLink 只提供整轮快捷索引，不替代业务外键；
trace_id 只负责技术追踪，不负责业务归属或幂等；
business_request_key 负责业务幂等，不得使用 trace_id、Celery task id 或随机重试序号代替；
MySQL 是核心事实来源，Redis 只能保存可丢失、可重建的短期数据；
任何 unknown 都必须保守处理，不得自动解释为成功或失败；
所有业务时间统一使用 UTC。
```

## 3. 数据类型

### 3.1 外部事实

外部事实来自系统之外：

```text
Binance 已收盘 Kline；
Binance 账户、余额、持仓和交易规则；
Binance mark price；
Binance 实时盘口价格；
Binance 订单状态；
Binance 逐笔成交；
Hermes 投递结果。
```

外部事实不得由业务模块直接请求，必须经过对应 Gateway。

Gateway 返回的是本次调用的技术结果。业务 service 校验后，才能把其中需要长期保留的内容写成业务对象。

系统不建立通用的 Gateway 结果业务表。需要持久化的调用事实由对应业务模块保存，例如：

```text
订单提交调用 → OrderSubmissionAttempt；
Hermes 投递调用 → NotificationDeliveryAttempt。
```

### 3.2 交易业务事实

主链路业务事实是正式下游可以消费的不可变或受控状态对象：

```text
Kline；
DataQualityResult；
MarketSnapshot；
FeatureSet / FeatureValue；
AtomicSignalSet / AtomicSignalValue；
DomainSignalSet / DomainSignalValue；
MarketRegimeSnapshot；
StrategyRouteDecision；
StrategySignal；
StrategySignalQualityResult；
DecisionSnapshot；
BinanceSyncRun 及其账户事实快照；
PriceSnapshot；
OrderPlan / CandidateOrderIntent；
RiskCheckResult / ApprovedOrderIntent；
ExecutionPreparationResult / PreparedOrderIntent；
OrderSubmissionAttempt；
OrderCycleCloseout / OrderCancelAttempt；
OrderStatusSyncRecord；
FillSyncResult / TradeFill / OrderFillSummary。
```

每个对象只能由其所属模块创建或推进状态。

### 3.3 运行控制信息

运行控制信息决定本轮可以运行什么，但不替代业务事实：

```text
OrchestrationStepRegistry 及其版本；
StrategyAnalysisRelease 及其冻结版本切片；
active market domain 部署配置；
.env 真实交易硬权限；
MySQL 真实交易运行开关；
模块 Definition、RuleSet 和 calculator 精确版本。
```

运行控制信息必须在规定位置解析和冻结，不得由下游模块临时改选。

### 3.4 编排、审计与复盘信息

以下对象用于整轮查看、运行诊断、通知、审计和离线复盘：

```text
OrchestrationRun；
OrchestrationStepRun；
OrchestrationBusinessObjectLink；
RuntimeGuardIssue；
AlertEvent；
NotificationDeliveryAttempt；
NotificationSuppression；
AuditRecord；
ReviewDatasetRecord；
ReviewDatasetExport。
```

这些对象可以引用主链路事实用于查看和复盘，但不得反向成为实时策略、风控或订单计算输入。

### 3.5 短期辅助数据

Redis 可以保存：

```text
短期缓存；
分布式锁；
短期幂等保护；
短期任务状态；
限流、冷却和熔断状态；
PriceSnapshot 缓存；
短期特征序列缓存；
Celery broker / result backend；
通知冷却和投递防重复状态。
```

Redis 数据不得替代 MySQL 中的正式业务事实。

## 4. 正式主链路数据流总览

```text
Binance 已收盘 Kline
→ Kline
→ DataQualityResult
→ 必要时 BackfillRequest / BackfillRun
→ Kline
→ 新的 DataQualityResult
→ MarketSnapshot
→ FeatureSet / FeatureValue
→ AtomicSignalSet / AtomicSignalValue
→ DomainSignalSet / DomainSignalValue
→ MarketRegimeSnapshot
→ StrategyRouteDecision
→ StrategySignal
→ StrategySignalQualityResult
→ DecisionSnapshot

Binance 账户与交易规则
→ BinanceSyncRun 及其事实快照

Binance mark price
→ PriceSnapshot

自动四小时 OrchestrationRun
→ 起始账户边界 BinanceSyncRun 及其事实快照

DecisionSnapshot
→ TARGET_POSITION：PriceSnapshot
   → 真实交易权限检查
   → OrderPlan
→ CandidateOrderIntent
→ RiskCheckResult
→ ApprovedOrderIntent
→ ExecutionPreparationResult
→ PreparedOrderIntent
→ OrderSubmissionAttempt
→ 订单提交事实完成

订单生命周期同步
→ OrderSubmissionAttempt
→ OrderStatusSyncRecord
→ FillSyncResult
→ TradeFill / OrderFillSummary

DecisionSnapshot
→ NO_TARGET_CHANGE / NO_TRADE：正常结束，不进入 PriceSnapshot 或订单链路
```

编排数据与业务数据并行记录：

```text
OrchestrationRun
→ OrchestrationStepRun
→ OrchestrationBusinessObjectLink
→ 关联本轮各步骤实际产生的业务对象
```

## 5. 行情事实数据流

### 5.1 DataCollection

数据来源固定为：

```text
Binance USDS-M Futures
BTCUSDT
已收盘 4h / 1d Kline
```

数据流：

```text
调度或初始化入口
→ DataCollectionService
→ BinanceGateway 公共 Kline 接口
→ 校验已收盘、UTC 时间和市场身份
→ 按 Kline 唯一业务键幂等写入 MySQL
→ Kline + DataCollectionRun
```

规则：

```text
DataCollectionRun 记录采集动作，但不是 MarketSnapshot 的输入；
正式下游消费的是 Kline，不消费 Gateway 原始响应；
数据采集域不读取 active trading domain；
未收盘、冲突或无法确认写入结果的 Kline 不得进入正式下游；
Redis 只能辅助短期锁和幂等，数据库唯一约束保护最终事实。
```

### 5.2 DataQuality

数据流：

```text
明确的 UTC 检查窗口
+ 已落库 Kline
→ DataQualityService
→ DataQualityResult / DataQualityIssue
```

结果分支：

```text
PASS
→ 允许 MarketSnapshot 使用该质量结果覆盖的 Kline 窗口

存在可回补缺口
→ BackfillRequest
→ DataBackfill

不可回补、冲突、失败或 unknown
→ 当前主链路停止
```

DataQuality 不请求 Binance，也不自行执行回补。

### 5.3 DataBackfill 闭环

数据流：

```text
BackfillRequest
→ DataBackfillService
→ BinanceGateway 公共 Kline 接口
→ 共用 Kline 写入规则与并发保护
→ BackfillRun / BackfillIssue / DataConflict
→ 幂等写入正式 Kline
→ 新的 DataQualityResult
```

规则：

```text
DataBackfill 完成不等于数据合格；
回补后的 Kline 必须重新经过 DataQuality；
DataBackfill 与 DataCollection 写入同一正式 Kline 事实层；
MarketSnapshot 不直接消费 BackfillRun；
回补循环必须有最大次数，禁止无限循环。
```

### 5.4 MarketSnapshot

数据流：

```text
PASS 的 DataQualityResult
+ 其明确覆盖的 4h / 1d Kline 窗口
+ analysis_close_time_utc
→ MarketSnapshotService
→ MarketSnapshot
```

MarketSnapshot 是 FeatureLayer 的唯一正式市场输入边界。

MarketSnapshot 固化的是策略分析使用的市场证据，不包含账户、持仓、mark price、订单或策略结论。

MarketSnapshot 与 PriceSnapshot 是两条不同数据流：

```text
MarketSnapshot → 策略分析使用的已收盘 Kline 证据；
PriceSnapshot  → 交易规划使用的本轮 mark price 事实。
```

两者不得互相派生或替代。

## 6. StrategyAnalysisRelease 冻结数据流

创建 OrchestrationRun 时，编排层解析当前唯一已批准、已启用且完整可用的 StrategyAnalysisRelease。

数据流：

```text
当前发布配置
→ 校验 release_hash、依赖闭包、Definition、RuleSet 和 calculator 注册
→ 在 OrchestrationRun 冻结 release ID 与 hash
→ Connector 向 FeatureLayer 至 DecisionSnapshot 显式传递同一版本包身份
```

冻结范围包括：

```text
FeatureDefinition 切片；
AtomicSignalDefinition 切片；
DomainSignalDefinition 切片；
MarketRegimeDefinition；
StrategyRoutePolicy / StrategyRouteRule；
StrategyDefinition 切片；
StrategySignalQualityRuleSet；
DecisionPolicyDefinition。
```

规则：

```text
同一 OrchestrationRun 从 FeatureLayer 到 DecisionSnapshot 只能使用一个版本包；
运行途中切换或回滚版本包，不改变本轮已经冻结的身份；
任一步骤发现定义、切片、calculator 或 hash 不一致时 fail-closed；
不得失败后重新读取“当前版本包”并替换本轮版本；
后台研究组合不得写入正式主链路对象。
```

没有唯一可用版本包时：

```text
DataCollection、DataQuality、必要回补和 MarketSnapshot 仍可执行；
在 FeatureLayer 前停止；
不得产生正式 FeatureSet 及其后续策略、决策和订单对象。
```

## 7. 特征、信号和决策数据流

| 阶段 | 唯一直接输入边界 | 正式输出 | 下游用途 |
|---|---|---|---|
| FeatureLayer | MarketSnapshot + 冻结 FeatureDefinition 切片 | FeatureSet / FeatureValue | AtomicSignal 输入 |
| AtomicSignal | FeatureSet / FeatureValue + 冻结原子信号定义切片 | AtomicSignalSet / AtomicSignalValue | DomainSignal 输入 |
| DomainSignal | AtomicSignalSet / AtomicSignalValue + 冻结领域定义切片 | DomainSignalSet / DomainSignalValue | MarketRegime 输入 |
| MarketRegime | DomainSignalSet / DomainSignalValue + 冻结 MarketRegimeDefinition | MarketRegimeSnapshot | StrategyRouting 输入 |
| StrategyRouting | MarketRegimeSnapshot + 冻结路由规则和策略切片 | StrategyRouteDecision | 指定本轮执行的策略 |
| StrategySignal | StrategyRouteDecision + 被选 StrategyDefinition + 同一 DomainSignalSet 中该策略声明使用的领域值 | StrategySignal | StrategySignalQuality 输入 |
| StrategySignalQuality | StrategySignal + 冻结质量规则集 | StrategySignalQualityResult | DecisionSnapshot 放行依据 |
| DecisionSnapshot | 已放行质量结果 + 标准化 StrategySignal + 冻结 DecisionPolicyDefinition | DecisionSnapshot | OrderPlan 的目标仓位输入 |

### 7.1 每层只消费直接上游

正式数据传递必须保持：

```text
FeatureSet 明确引用 MarketSnapshot；
AtomicSignalSet 明确引用 FeatureSet；
DomainSignalSet 明确引用 AtomicSignalSet；
MarketRegimeSnapshot 明确引用 DomainSignalSet；
StrategyRouteDecision 明确引用 MarketRegimeSnapshot；
StrategySignal 明确引用 StrategyRouteDecision 和实际使用的 DomainSignalValue；
StrategySignalQualityResult 明确引用 StrategySignal；
DecisionSnapshot 明确引用 StrategySignalQualityResult 和 StrategySignal。
```

下游可以沿业务外键进行追溯，但不得跳过直接上游重新计算上游结论。

### 7.2 算法输入与业务对象隔离

业务 service 负责：

```text
读取并校验正式业务对象；
冻结 Definition、参数、版本包身份和直接输入；
把纯数据 DTO 交给 calculator；
校验 calculator 输出合同；
把合法结果写成正式业务对象。
```

calculator 只接收纯数据，不接收 Django model、QuerySet、Gateway、Redis 连接或 Celery 上下文。

calculator 内存输出不能被下游直接消费，必须由所属 service 校验并落库。

### 7.3 DecisionSnapshot 的数据边界

DecisionSnapshot 只把标准化策略结果转换为目标仓位语义：

```text
target_intent；
target_position_ratio；
target_confidence；
target_reason_code；
结构化证据和算法版本。
```

DecisionSnapshot 不读取：

```text
账户、余额或持仓；
BinanceSyncRun；
PriceSnapshot；
MarketRegimeSnapshot 作为二次分析输入；
DomainSignalValue 作为二次加权输入；
订单或成交事实。
```

策略类型差异必须在 StrategySignal 输出前完成标准化，DecisionSnapshot 不根据趋势、震荡或其他策略类型再次分支分析市场。

`NO_TRADE` 或 `NO_TARGET_CHANGE` 表示本轮不进入价格和订单链路。编排层仍调用一次 BinanceAccountSyncStepAdapter，保存本轮 `trade_preparation` 账户边界事实后正常完成；不创建 PriceSnapshot、OrderPlan、CandidateOrderIntent 或 ActiveLock。

DecisionSnapshot 不直接调用账户同步，也不读取账户同步结果。分支推进由 Connector 按冻结 Registry 完成。

## 8. 账户事实数据流

### 8.1 trade_preparation

数据流：

```text
BinanceAccountSyncStepAdapter
→ 生成本轮稳定 business_request_key
→ BinanceAccountSyncService
→ BinanceGateway 账户只读与公共交易规则接口
→ BinanceSyncRun
   + BinanceAccountSnapshot
   + BinanceBalanceSnapshot
   + BinancePositionSnapshot
   + BinanceSymbolRuleSnapshot
→ OrchestrationBusinessObjectLink 记录本轮同步批次
```

规则：

```text
每个新的 trade_preparation business_request_key 产生新的同步批次；
同一批次内的账户、余额、持仓和交易规则形成完整不可变事实集合；
OrderPlan 与 RiskCheck 必须使用 Connector 显式传入的同一个 binance_sync_run_id；
ExecutionPreparation 必须追溯并校验该订单链使用的明确同步批次；
任何模块不得按“最新成功批次”自动选择交易输入；
Redis 不得作为账户事实来源。
```

正常无交易分支：

```text
DecisionSnapshot NO_TARGET_CHANGE / NO_TRADE
→ BinanceAccountSyncStepAdapter
→ trade_preparation BinanceSyncRun 及其事实快照
→ 写入 OrchestrationBusinessObjectLink
→ 本轮正常完成
```

该分支为 ReviewDataset 保留四小时账户边界，但不调用 PriceSnapshot、不检查真实交易权限、不进入 OrderPlan，也不取得 ActiveLock。

### 8.2 ops_display

后台账户展示使用独立数据流：

```text
OpsConsole
→ 账户展示刷新 service
→ BinanceAccountSync ops_display 入口
→ BinanceSyncRun 及展示事实
→ Account Overview
```

`ops_display` 只用于后台展示：

```text
不得被 OrderPlan、RiskCheck 或 ExecutionPreparation 消费；
不得替代 trade_preparation；
不得作为 ReviewDataset 的交易账户边界；
刷新失败只影响后台展示。
```

## 9. PriceSnapshot 数据流

数据流：

```text
DecisionSnapshot TARGET_POSITION
→
PriceSnapshotStepAdapter
→ 本轮稳定且不透明的 business_request_key
→ PriceSnapshotService
→ BinanceGateway mark price 接口
→ PriceSnapshot 写入 MySQL
→ 同一 PriceSnapshot 写入 Redis 短期缓存
```

规则：

```text
每个新 business_request_key 都实际请求一次 Binance；
Gateway 不返回历史缓存价格代替本次业务请求；
一轮 OrchestrationRun 只能使用一份明确 PriceSnapshot；
业务对象本身不保存 orchestration_run_id，由 OrchestrationBusinessObjectLink 建立本轮索引；
PriceSnapshot 默认 TTL 为 10 分钟；
OrderPlan、RiskCheck 和 ExecutionPreparation 使用同一份明确 PriceSnapshot；
不同业务请求或不同编排批次的 PriceSnapshot 不得混用；
Redis 命中只能加速读取同一份已落库快照；
Redis 缺失、损坏或 hash 不一致时回读 MySQL，不重新请求价格替换本轮快照。
```

PriceSnapshot 不从 BinancePositionSnapshot 中的 mark price 派生。

## 10. 真实交易权限数据流

真实交易权限不是独立业务模块，其数据来源是：

```text
.env / Django settings 中的部署级硬权限
+ MySQL 中的真实交易运行开关
→ OrderPlanStepAdapter
→ 本轮有效权限判断
```

分支：

```text
两项都允许
→ 冻结本次检查结果
→ 调用 OrderPlan

任一项明确关闭
→ 不调用 OrderPlan
→ 不生成 OrderPlan、CandidateOrderIntent 或 ActiveLock
→ 本轮正常完成

权限或市场配置不可读取、市场身份不一致
→ fail-closed
→ 本轮阻断并停止
```

检查通过后，本轮 RiskCheck、ExecutionPreparation 和 Execution 不重新读取后台开关。

OrderStatusSync 和 FillSync 属于订单生命周期同步数据流，也不重新读取后台真实交易运行开关；后台随后修改运行开关，不能中断已经存在的订单状态和成交同步。

后台随后修改运行开关，只影响下一次进入 OrderPlan 的检查。

## 11. OrderPlan 与 RiskCheck 数据流

### 11.1 OrderPlan

明确输入：

```text
可消费且未过期的 DecisionSnapshot
+ trade_preparation BinanceSyncRun 及其事实快照
+ 未过期 PriceSnapshot
+ 已通过的真实交易权限检查结果
```

输出分支：

```text
无需调整目标仓位
→ OrderPlan no_order_required
→ 不生成 CandidateOrderIntent
→ 不取得 ActiveLock
→ 本轮正常完成

需要调整目标仓位且输入合法
→ OrderPlan created
→ primary CandidateOrderIntent
→ 必要时预生成 fallback_reduce_only CandidateOrderIntent
→ 同一数据库事务取得 OrderPlanActiveLock

输入冲突、价格过期、账户事实不可用或锁冲突
→ blocked / failed / unknown
→ 不产生新的可执行订单链路
```

OrderPlan 是目标仓位到候选订单意图的唯一转换位置。

OrderPlan 不访问 Binance，不刷新账户，不刷新 PriceSnapshot，不做最终风控审批。

### 11.2 RiskCheck

明确输入：

```text
OrderPlan
+ CandidateOrderIntent
+ OrderPlan 已绑定的同一 BinanceSyncRun
+ OrderPlan 已绑定的同一 PriceSnapshot
+ ActiveLock
+ 已冻结风险规则集
```

输出分支：

```text
ALLOW
→ RiskCheckResult
→ ApprovedOrderIntent

primary 新增风险部分不通过，但预生成 fallback_reduce_only 全部通过
→ RiskCheckResult 记录 fallback 选择
→ ApprovedOrderIntent 引用该 fallback CandidateOrderIntent

DENY / BLOCKED / FAILED
→ RiskCheckResult
→ 不生成 ApprovedOrderIntent
→ 按确定性证据调用 ActiveLockService 收尾或保持阻断
```

RiskCheck 不生成新 CandidateOrderIntent，不缩小订单，不刷新价格，不重新选择账户同步批次。

## 12. 执行准备和订单提交数据流

### 12.1 ExecutionPreparation

明确输入：

```text
ApprovedOrderIntent
+ 原订单链的 BinanceSyncRun
+ 原订单链的 PriceSnapshot
+ ActiveLock
```

实时价格复核数据流：

```text
ExecutionPreparationService
→ BinanceGateway 实时盘口价格接口
→ 按订单方向选择买一或卖一价格
→ 与本轮 PriceSnapshot mark price 比较
```

规则：

```text
价格偏离小于或等于 1% → 允许继续；
价格偏离大于 1% → 阻断；
盘口查询失败或结果无法确认 → 不得回退到 mark price 放行；
本次盘口查询不会创建新的 PriceSnapshot；
盘口价格写入 ExecutionPreparationResult 作为执行前证据，不得写成实际成交价。
```

通过全部检查后：

```text
ExecutionPreparationResult
→ PreparedOrderIntent
```

PreparedOrderIntent 冻结最终提交参数、client_order_id 和有效期，但仍不是交易所订单。

### 12.2 Execution

数据流：

```text
有效且未提交的 PreparedOrderIntent
→ ExecutionService
→ BinanceGateway 订单提交接口
→ OrderSubmissionAttempt
```

OrderSubmissionAttempt 只记录提交动作结果：

```text
accepted；
rejected；
unknown；
failed_before_submit；
blocked_before_submit。
```

规则：

```text
同一 PreparedOrderIntent 只能提交一次；
订单提交在 Gateway、业务层、Celery、编排层和人工入口都不得重试；
accepted 只表示交易所接受请求，不表示已经成交；
unknown 不得推断成功或失败，也不得回到 Execution 再次提交。
```

## 13. 订单状态与成交数据流

### 13.1 OrderStatusSync

数据流：

```text
accepted 或 unknown 的 OrderSubmissionAttempt
→ OrderStatusSyncService
→ BinanceGateway 订单状态查询接口
→ OrderStatusSyncRecord
```

查询身份：

```text
优先使用提交前冻结的 client_order_id；
已有可信 exchange_order_id 时可以作为辅助查询身份；
不得用当前配置或人工输入改写历史订单市场身份。
```

短轮询规则：

```text
每 2 秒查询一次；
最多持续 30 秒；
查到明确终态立即停止；
30 秒仍无法确认时停止短轮询，保持 ActiveLock 并记录告警；
不得因此重新提交订单。
```

结果分支：

```text
NEW / PARTIALLY_FILLED
→ 保存状态事实
→ 继续等待，不进入 FillSync，不释放锁

明确终态
→ 保存终态 OrderStatusSyncRecord
→ 交给 FillSync

not_found / unknown
→ 保存不确定事实
→ 保持 ActiveLock
→ 等待受控恢复和人工排查
```

### 13.2 FillSync

明确输入：

```text
OrderSubmissionAttempt
+ 明确终态的 OrderStatusSyncRecord
+ 原订单链冻结的市场身份
```

数据流：

```text
FillSyncService
→ BinanceGateway 成交查询接口
→ 分页读取该订单全部成交
→ FillSyncResult
→ TradeFill
→ OrderFillSummary
→ OrderPlanActiveLockService 安全收尾判断
```

结果分支：

```text
查询完整且成交数量与终态一致
→ synced
→ 幂等保存 TradeFill 和 OrderFillSummary
→ 满足全部条件后释放 ActiveLock

明确无成交终态、查询完整且 executed quantity 为零
→ synced_empty
→ 满足全部条件后释放 ActiveLock

incomplete / unknown / 查询前失败 / 输入阻断
→ 不释放 ActiveLock
→ 不重新提交订单
```

FillSync 只保存成交事实，不直接修改账户或持仓快照。

下一轮 Binance Account Sync 再次从 Binance 读取真实账户和持仓，形成新的 BinancePositionSnapshot。系统不得仅根据 TradeFill 在本地推导一份交易所持仓事实。

## 14. ActiveLock 数据流

OrderPlanActiveLock 保护的是同一交易身份下的一条完整订单链路：

```text
OrderPlan created
→ 取得 ActiveLock
→ RiskCheck
→ ExecutionPreparation
→ Execution
→ 订单提交事实完成

订单生命周期同步或限价单周期收尾
→ OrderStatusSync
→ FillSync
→ 证据完整后释放 ActiveLock
```

数据修改边界：

```text
只有 OrderPlan 模块所属的 OrderPlanActiveLockService 可以修改锁状态；
RiskCheck、ExecutionPreparation、Execution、OrderStatusSync 和 FillSync 只能提交收尾证据并调用该 service；
PipelineOrchestrator、RuntimeGuard 和 OpsConsole 不得直接写锁表。
```

可以自动释放的数据证据：

```text
提交前能够明确证明没有发送订单；
交易所明确拒绝订单；
订单已经明确终态且成交同步完整；
明确无成交终态且 FillSync 严格确认 synced_empty。
```

不得自动释放的数据状态：

```text
提交结果 unknown；
订单状态 not_found 或 unknown；
订单状态 NEW 或 PARTIALLY_FILLED；
成交同步 incomplete、unknown 或 failed；
只有余额或持仓变化，没有订单终态和成交完整性证据。
```

## 15. 编排数据流

### 15.1 三类编排对象

```text
OrchestrationRun
→ 记录一轮运行、Registry 版本、冻结版本包和最终结果

OrchestrationStepRun
→ 记录某个步骤的输入摘要、统一结果、耗时和错误摘要

OrchestrationBusinessObjectLink
→ 记录 Run、StepRun 与本轮业务对象的一对多索引
```

### 15.2 业务输入传递

Connector 可以依据 Registry 依赖和已有 ObjectLink 找到上一合法步骤产生的对象，但必须把明确业务对象 ID 传给下游 adapter：

```text
FeatureLayer ← market_snapshot_id；
AtomicSignal ← feature_set_id；
DomainSignal ← atomic_signal_set_id；
MarketRegime ← domain_signal_set_id；
StrategyRouting ← market_regime_snapshot_id；
StrategySignal ← strategy_route_decision_id；
StrategySignalQuality ← strategy_signal_id；
DecisionSnapshot ← strategy_signal_quality_result_id；
OrderPlan ← decision_snapshot_id + binance_sync_run_id + price_snapshot_id；
RiskCheck ← order_plan_id + candidate_order_intent_id + 明确事实 ID；
ExecutionPreparation ← approved_order_intent_id；
Execution ← prepared_order_intent_id；
OrderStatusSync ← order_submission_attempt_id；
FillSync ← order_submission_attempt_id + terminal_order_status_sync_record_id。
```

业务 service 不接收 orchestration_run_id 后自行查询 ObjectLink 猜测输入。

### 15.3 标准写入顺序

同步业务步骤的数据写入顺序：

```text
创建 OrchestrationStepRun；
→ adapter 调用业务 service；
→ 业务 service 在自己的事务中写入业务对象；
→ adapter 把业务结果映射为 normalized_status 和 flow_action；
→ adapter 返回业务对象引用；
→ 编排层写 OrchestrationBusinessObjectLink；
→ 编排层保存 StepRun 统一结果并推进 OrchestrationRun。
```

不得为了同时写业务对象和编排对象而在数据库长事务中等待外部网络请求。

### 15.4 编排关联与业务外键的区别

真实业务外键回答：

```text
这份结果直接由哪份上游事实产生？
```

OrchestrationBusinessObjectLink 回答：

```text
这一轮运行涉及了哪些业务对象？
```

因此：

```text
RiskCheck 通过 candidate_order_intent_id 找待审批订单；
FillSync 通过终态 OrderStatusSyncRecord 找成交查询依据；
后台通过 orchestration_run_id 快速查看整轮对象；
三者不得互相替代。
```

## 16. trace_id、幂等键与对象身份

### 16.1 trace_id

`trace_id` 沿一次技术调用链传递，用于：

```text
结构化日志；
Gateway 调用上下文；
AlertEvent；
StepRun；
异常定位和跨进程技术追踪。
```

`trace_id` 不用于：

```text
判断两个业务对象是否属于同一订单链；
作为数据库业务外键；
作为业务幂等键；
替代 OrchestrationBusinessObjectLink；
替代交易所订单编号。
```

某些长期事实不重复保存 trace_id 时，必须可以通过其直接上游对象追溯到对应调用过程。

### 16.2 business_request_key

每个业务模块使用自己的稳定业务幂等键，回答：

```text
这是不是同一个业务动作的重复执行？
```

规则：

```text
相同业务输入和相同动作应得到相同稳定键；
重复执行应返回已有等价业务事实；
不同编排轮次需要新事实时，由 Connector 生成新的稳定键；
业务键不得依赖当前时间、随机重试序号、worker 名称或 task id；
业务键不得使用 orchestration_run_id 直接代替业务身份。
```

### 16.3 外部对象身份

交易所相关身份至少包括：

```text
exchange；
market_type；
account_domain；
symbol；
client_order_id；
可用时的 exchange_order_id；
TradeFill 的交易所成交编号。
```

历史订单查询和成交同步必须使用原订单链冻结的市场身份，不读取当前部署配置改写历史事实。

## 17. AlertEvent 与通知数据流

业务事件数据流：

```text
业务模块发生关键状态或异常
→ 通过 Notifications 拥有的事件能力写 AlertEvent
→ 通知路由判断
→ NotificationDeliveryAttempt
   或 NotificationSuppression
```

外部投递数据流：

```text
MySQL pending NotificationDeliveryAttempt
→ Celery worker 认领
→ Hermes channel client
→ 更新投递结果
```

规则：

```text
MySQL pending 记录是可靠投递来源；
Celery 消息只用于加速唤醒，不是唯一投递事实；
Redis 只用于冷却、限频和防重复；
通知失败不得回滚业务事实；
通知成功不得触发业务动作；
不需要外部发送时必须形成 NotificationSuppression 或等价抑制事实；
AlertEvent 不直接保存编排 ID，由 OrchestrationBusinessObjectLink 以 audit 角色关联。
```

## 18. RuntimeGuard 数据流

RuntimeGuard 独立于四小时主编排运行，只读巡检以下事实：

```text
OrchestrationRun / OrchestrationStepRun；
OrderPlanActiveLock；
OrderSubmissionAttempt；
OrderStatusSyncRecord；
FillSyncResult；
NotificationDeliveryAttempt / NotificationSuppression。
```

输出：

```text
RuntimeGuardIssue；
必要 AlertEvent。
```

RuntimeGuard 不形成以下数据流：

```text
RuntimeGuardIssue → 修改原业务对象；
RuntimeGuardIssue → 释放 ActiveLock；
RuntimeGuardIssue → 自动补跑编排；
RuntimeGuardIssue → 重新提交订单；
RuntimeGuardIssue → 直接发送 Hermes。
```

RuntimeGuard 不读取 ReviewDataset 作为巡检对象。

## 19. 后台与复盘数据流

### 19.1 OpsConsole

后台数据流：

```text
浏览器页面
→ OpsConsole API / application service
→ 对应业务 service 或只读 selector
→ MySQL 业务事实
→ 脱敏展示结果
```

OpsConsole 前端不得直接访问 MySQL、Redis、BinanceGateway 或外部大模型。

受控写操作必须经过对应业务 service，并写 AuditRecord。页面输入不能直接改写业务对象状态。

### 19.2 ReviewDataset

后台复盘数据集数据流：

```text
OpsConsole 创建数据集导出请求
→ ReviewDatasetService 按 UTC 4 小时周期和业务对象关系读取已落库事实
→ 汇总编排、行情、特征、信号、决策、账户、价格、订单、成交、告警、巡检和审计上下文
→ 生成 ReviewDatasetRecord
→ 生成 ReviewDatasetExport
→ 下载为本地复盘材料
```

规则：

```text
只读取已落库事实；
账户边界只使用自动 trade_preparation 账户快照；
自动账户边界快照在编排起始阶段产生，后续任何合法无交易分支都不影响其边界资格；
忽略 ops_display 和人工展示刷新；
不按数据库最新两份账户快照猜测周期关系；
不请求 Binance；
不调用外部大模型；
缺少必要事实时记录缺失原因，不伪造数据；
已存在且输入一致的有效数据集不重复写入；
导出结果只用于离线复盘，不反向进入交易链路。
```

离线 Codex skill 可以读取导出的 ReviewDataset：

```text
复盘报告保存在本地；
不得写入生产数据库；
不得进入 StrategyRouting、StrategySignal 或 DecisionSnapshot；
不得修改风控、真实交易运行开关或订单事实；
不得生成订单或触发交易。
```

## 20. MySQL、Redis、Celery 与 Gateway 的数据职责

| 组件 | 数据职责 | 不得承担 |
|---|---|---|
| MySQL | 保存核心业务、编排、审计、通知和复盘事实 | 不作为无结构的大历史数组存储 |
| Redis | 缓存、短期锁、限频、冷却、Celery 和短期状态 | 不作为 Kline、账户、价格、订单、成交或通知的唯一事实来源 |
| Celery | 异步唤醒和任务执行入口 | 不作为业务状态来源，不承载完整业务逻辑，不重试订单提交 |
| Celery Beat | 触发定时采集、编排、巡检和通知扫描 | 不决定业务结果，不直接访问外部服务 |
| BinanceGateway | 返回 Binance 受限接口技术结果 | 不选择业务对象，不写业务状态，不拥有订单重试策略 |
| Hermes client | 执行外部通知投递 | 不读取或触发交易链路 |

## 21. 失败与停止传播

| 业务结果 | 数据流处理 |
|---|---|
| succeeded | 正式对象完成且可消费时，Connector 显式传给下一步 |
| no_action | 本轮业务正常完成，不创建不需要的下游对象 |
| skipped | 本步骤按明确条件不适用，按 Registry 进入合法后续路径 |
| blocked | 安全条件不满足，禁止生成可消费下游对象 |
| denied | 风控明确拒绝，不生成 ApprovedOrderIntent |
| unknown | 无法判断外部结果或持久化结果，停止自动推进并保留保护状态 |
| failed | 系统异常，停止当前路径并记录必要 AlertEvent |

共同规则：

```text
blocked、denied、no_action 和 skipped 不等于系统故障；
unknown 不得自动转为 succeeded 或 failed；
failed 不得通过创建伪造下游对象掩盖；
下游不得消费 blocked、failed、unknown、dry-run 或后台研究对象；
恢复安全读取动作时必须按原业务幂等键核对已有事实；
订单提交动作永远不得通过恢复流程再次执行。
```

## 22. 禁止的数据捷径

禁止形成以下数据流：

```text
Gateway 原始响应 → 绕过业务 service 直接写下游对象；
Redis 缓存 → 作为账户、价格、订单或成交唯一事实；
DataCollectionRun → 直接生成 MarketSnapshot；
BackfillRun → 不经 DataQuality 直接生成 MarketSnapshot；
Kline → 绕过 MarketSnapshot 直接计算正式特征；
FeatureValue → 绕过 AtomicSignal / DomainSignal / MarketRegime 直接生成 StrategySignal；
MarketRegimeSnapshot → 绕过 StrategyRouting 直接执行任意策略；
StrategySignal → 绕过 StrategySignalQuality 直接生成 DecisionSnapshot；
DecisionSnapshot → 读取账户后直接生成订单；
DecisionSnapshot → 直接进入 RiskCheck 或 Execution；
PriceSnapshot 缓存过期 → 自动请求新价格替换同一订单链输入；
RiskCheck → 修改 CandidateOrderIntent 或临时生成 fallback；
ExecutionPreparation 盘口价格 → 写成实际成交价；
OrderSubmissionAttempt accepted → 当作 FILLED；
OrderSubmissionAttempt unknown → 再次提交订单；
OrderStatusSyncRecord → 伪造成 TradeFill；
TradeFill → 直接改写 BinancePositionSnapshot；
OrchestrationRun.id → 作为主交易业务对象正式外键；
OrchestrationBusinessObjectLink → 由业务模块用来猜测正式输入；
trace_id → 作为业务幂等键或对象归属依据；
RuntimeGuardIssue → 自动修复或释放锁；
离线复盘报告 → 修改实时策略、风控或订单；
NotificationDeliveryAttempt → 触发业务动作。
```

## 23. 数据流验收方向

实现代码时至少应验证：

```text
每个正式对象都能找到明确直接上游；
每个模块只写自己拥有的业务对象；
每个正式下游只消费 MySQL 中明确可用的对象；
同一策略链只使用一个冻结 StrategyAnalysisRelease；
同一订单计划、风控和执行准备使用一致的账户和价格事实；
ops_display 不进入交易链路，也不作为 ReviewDataset 的交易账户边界；
一轮编排只使用一个明确 PriceSnapshot；
真实交易权限关闭时不创建 OrderPlan、CandidateOrderIntent 或 ActiveLock；
NO_TARGET_CHANGE / NO_TRADE 时不补做账户同步，不创建 PriceSnapshot 或订单链路；
订单提交只发生一次；
unknown 不触发重提、解锁或伪造下游事实；
FillSync 只消费明确终态并完整保存成交事实；
TradeFill 不直接生成持仓快照；
ObjectLink 可以查清整轮对象，但业务模块仍使用真实业务外键；
Redis 丢失后核心业务事实仍可从 MySQL 恢复；
通知、巡检和 ReviewDataset 不会反向触发交易。
```

## 24. 最终结论

系统数据流的核心是：

```text
每一步先形成自己拥有、已经校验并落库的业务事实，再由 Connector 把明确对象交给直接下游；
主链路依靠真实业务外键保证因果关系，编排关联表负责整轮快捷查看，MySQL 保存最终事实，Redis 只提供短期加速和保护。
```

一句话：

```text
任何数据只有在来源明确、版本明确、业务身份明确、状态可消费并已安全落库后，才能进入下一层。
```
