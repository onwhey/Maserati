# 模块边界架构

## 1. 文档目的

本文档定义新版需求文件之间的直接关系，以及各业务模块在架构上的允许依赖、禁止依赖和调用边界。

本文档用于回答：

```text
某个模块可以读取谁；
某个模块可以生成谁；
某个模块不能调用谁；
某个需求文件和其他需求文件是什么关系；
编码时出现跨模块调用时应该如何判断是否越界。
```

本文档不定义：

```text
数据库字段；
Django app 名称；
Celery task 名称；
具体函数名；
具体算法公式；
具体状态枚举细节；
具体前端页面。
```

模块业务合同以 `docs/requirements/*.md` 为准。

如果本文档与 requirements 冲突，以 requirements 为准，并停止实现、向用户确认。

## 2. 边界总原则

模块关系遵守单向主链路：

```text
数据事实
→ 市场证据
→ 特征
→ 原子信号
→ 领域信号
→ 市场环境
→ 策略路由
→ 策略信号
→ 策略信号质量
→ 目标仓位决策
→ 账户事实 / 价格事实
→ 订单计划
→ 风控审批
→ 执行准备
→ 订单提交
→ 订单状态查询
→ 成交同步
→ 交易事实闭环
```

横切模块只能通过明确 service 或审计索引协作：

```text
PipelineOrchestrator
RuntimeGuard
Notifications
OpsConsole
ReviewDataset
```

任何模块不得因为实现方便而直接跳过上游或调用下游内部逻辑。

## 3. 需求文件关系总览

### 3.1 高层与基础文件

| 文件 | 作用 | 直接约束对象 |
|---|---|---|
| `project_scope.md` | 定义当前项目范围、主链路和不做事项 | 全部 requirements |
| `system_capabilities.md` | 定义系统能力地图和能力边界 | 全部业务模块 |
| `core_contracts.md` | 定义核心对象语义和对象不可混用边界 | 全部业务对象 |
| `project_foundation.md` | 定义技术底座、配置、存储、任务、日志、审计基础 | 所有实现层 |
| `README.md` | 需求目录索引 | 读文档顺序 |

高层文件不拥有具体业务流程实现，不能替代模块需求。

### 3.2 主链路需求文件顺序

```text
data_collection.md
→ data_quality.md
→ data_backfill.md（必要时）
→ data_quality.md（回补后重新质检）
→ market_snapshot.md
→ feature_layer.md
→ atomic_signals.md
→ domain_signals.md
→ market_regime.md
→ strategy_routing.md
→ strategy_signals.md
→ strategy_signal_quality.md
→ decision_snapshot.md
→ binance_account_sync.md / price_snapshot.md
→ pipeline_orchestrator.md 中的 OrderPlanStepAdapter 真实交易权限检查
→ order_plan.md
→ risk_check.md
→ execution_preparation.md
→ order_submission.md
→ order_status_sync.md
→ fill_sync.md
```

### 3.3 底层能力文件

| 文件 | 服务对象 | 边界 |
|---|---|---|
| `binance_gateway.md` | 所有 Binance REST 请求 | 只提供受限接口，不拥有业务状态 |
| `strategy_calculator.md` | 策略分析相关模块 | 只定义纯计算通用规则，不直接参与编排 |
| `strategy_analysis_release.md` | 策略分析正式运行版本选择 | 冻结正式版本组合，不执行算法 |
| `notifications.md` | AlertEvent 外部投递 | 不触发交易 |
| `runtime_guard.md` | 主链路巡检 | 只读巡检，不修复业务 |

### 3.4 后置和后台文件

| 文件 | 直接依赖 | 边界 |
|---|---|---|
| `ops_console.md` | 后端 service、只读查询、受控操作入口 | 不直接访问数据库，不直接调用 Gateway |
| `review_dataset.md` | 已落库业务事实、OrchestrationRun、业务外键 | 只生成和导出复盘数据集，不调用大模型，不属于自动主链路 |

## 4. 模块直接关系表

| 模块 / 文件 | 直接上游 | 直接下游 | 禁止越界 |
|---|---|---|---|
| DataCollection / `data_collection.md` | BinanceGateway 公共市场接口、调度入口 | DataQuality | 不生成质量结论、快照、特征、信号或交易对象 |
| DataQuality / `data_quality.md` | 已落库 Kline、明确 UTC 检查窗口 | MarketSnapshot；必要时创建 BackfillRequest | 不请求 Binance，不执行回补，不生成 MarketSnapshot |
| DataBackfill / `data_backfill.md` | BackfillRequest 或受控初始化/人工回补请求 | Kline 写入；回补后等待 DataQuality 复检 | 不直接放行下游，不跳过 DataQuality，不触发交易 |
| MarketSnapshot / `market_snapshot.md` | PASS 的 DataQualityResult、Kline 窗口 | FeatureLayer | 不计算特征，不读取账户，不访问 Binance |
| FeatureLayer / `feature_layer.md` | MarketSnapshot | AtomicSignal | 不生成交易信号，不生成目标仓位，不读取账户 |
| AtomicSignal / `atomic_signals.md` | FeatureSet / FeatureValue | DomainSignal | 不生成策略最终判断，不生成目标仓位或订单动作 |
| DomainSignal / `domain_signals.md` | AtomicSignalSet / AtomicSignalValue | MarketRegime | 不识别完整市场环境，不选择策略，不生成订单动作 |
| MarketRegime / `market_regime.md` | DomainSignalSet / DomainSignalValue | StrategyRouting | 不执行策略，不生成 StrategySignal，不生成订单动作 |
| StrategyRouting / `strategy_routing.md` | MarketRegimeSnapshot、路由配置、已批准 StrategyDefinition | StrategySignal | 不执行策略算法，不生成目标仓位，不生成订单动作 |
| StrategySignal / `strategy_signals.md` | StrategyRouteDecision、StrategyDefinition、允许使用的 DomainSignalValue | StrategySignalQuality | 不直接聚合原子信号，不生成目标仓位，不读取账户 |
| StrategySignalQuality / `strategy_signal_quality.md` | StrategySignal | DecisionSnapshot | 不改变策略方向，不调整目标仓位，不生成订单参数 |
| DecisionSnapshot / `decision_snapshot.md` | StrategySignalQualityResult、StrategySignal、DecisionPolicy | OrderPlan | 不读取账户、持仓或 BinanceSyncRun，不生成订单动作 |
| Binance Account Sync / `binance_account_sync.md` | BinanceGateway 账户只读和公共规则接口 | OrderPlan、RiskCheck、ExecutionPreparation、ReviewDataset | 不提交订单，不修改杠杆，不推导策略 |
| PriceSnapshot / `price_snapshot.md` | BinanceGateway mark price 接口 | OrderPlan、RiskCheck、ExecutionPreparation | 不从账户持仓快照取价格，不代表最终成交价，不判断是否交易 |
| OrderPlan / `order_plan.md` | DecisionSnapshot、trade_preparation BinanceSyncRun、PriceSnapshot、真实交易权限已通过 | CandidateOrderIntent、OrderPlanActiveLock | 不访问 Binance，不做最终风控，不生成 ApprovedOrderIntent，不下单 |
| RiskCheck / `risk_check.md` | CandidateOrderIntent、OrderPlan、账户事实、PriceSnapshot、symbol rule | ApprovedOrderIntent 或阻断结果 | 不消费 DecisionSnapshot，不生成新 CandidateOrderIntent，不任意改数量，不下单 |
| ExecutionPreparation / `execution_preparation.md` | ApprovedOrderIntent、账户事实、PriceSnapshot、ActiveLock | PreparedOrderIntent | 不提交订单，不重新设计订单，不释放锁 |
| Execution / `order_submission.md` | PreparedOrderIntent、ActiveLock | OrderSubmissionAttempt | 不生成订单计划，不做风控，不重试提交，不根据本地推测生成成交 |
| OrderStatusSync / `order_status_sync.md` | OrderSubmissionAttempt | OrderStatusSyncRecord；明确终态后交给 FillSync | 不重新提交订单，不查询成交，不生成 TradeFill；不自行提供后台入口或开关，OpsConsole 受控补查仍调用本模块 service |
| FillSync / `fill_sync.md` | 明确可同步的 OrderStatusSyncRecord | TradeFill、OrderFillSummary、锁安全收尾请求 | 不提交订单，不生成订单状态，不修改账户快照；不自行提供后台入口或开关，OpsConsole 受控补同步仍调用本模块 service |

## 5. 横切模块边界

### 5.1 PipelineOrchestrator

直接关系：

```text
PipelineOrchestrator
→ OrchestrationBusinessConnector
→ 各业务 service
```

职责：

```text
创建 OrchestrationRun；
冻结步骤定义；
保存 OrchestrationStepRun；
保存 OrchestrationBusinessObjectLink；
根据统一 flow_action 推进、等待、停止或完成。
```

禁止：

```text
直接解释业务模块内部状态；
直接调用 Binance；
直接调用 DeepSeek；
直接修改业务对象；
直接释放 ActiveLock；
直接提交订单。
```

### 5.2 RuntimeGuard

直接读取：

```text
OrchestrationRun；
OrchestrationStepRun；
OrderPlanActiveLock；
OrderSubmissionAttempt；
OrderStatusSyncRecord；
FillSyncResult；
NotificationDeliveryAttempt；
NotificationSuppression。
```

输出：

```text
RuntimeGuardIssue；
AlertEvent。
```

禁止：

```text
补跑业务；
恢复编排；
修改业务对象；
释放锁；
调用 Binance；
直接发送 Hermes；
巡检 ReviewDataset；
巡检后台人工补算或普通后台页面功能。
```

### 5.3 Notifications

直接输入：

```text
AlertEvent。
```

输出：

```text
NotificationDeliveryAttempt；
NotificationSuppression；
外部 Hermes 通知结果。
```

禁止：

```text
触发交易；
修改业务事实；
回滚业务结果；
把通知成功当作业务动作。
```

### 5.4 OpsConsole

允许通过后端 service：

```text
查看系统状态；
查看账户展示；
查看 OrchestrationRun；
查看订单链路；
查看 RuntimeGuardIssue；
查看 AlertEvent；
创建和下载 ReviewDataset；
操作真实交易运行开关；
查看审计日志。
```

禁止：

```text
直接访问数据库；
直接调用 BinanceGateway；
直接调用外部大模型；
直接提交订单；
直接释放 ActiveLock；
直接写业务表；
管理 API key；
写 .env；
热切 active market domain。
```

### 5.5 ReviewDataset

直接读取：

```text
已落库业务事实；
自动边界 trade_preparation 账户快照；
OrchestrationRun；
业务外键关联的订单、成交、告警、巡检和审计事实。
```

输出：

```text
ReviewDatasetRecord；
ReviewDatasetExport。
```

禁止：

```text
请求 Binance；
调用外部大模型；
影响交易主流程；
生成交易信号；
调整策略；
自动暂停或恢复交易；
被 RuntimeGuard 当作主链路异常巡检对象。
```

## 6. 底层能力边界

### 6.1 BinanceGateway

允许调用方：

```text
DataCollection；
DataBackfill；
Binance Account Sync；
PriceSnapshot；
Execution；
OrderStatusSync；
FillSync。
```

调用限制：

```text
DataCollection / DataBackfill 只能使用公共市场数据接口；
Binance Account Sync 只能使用账户只读和公共规则接口；
PriceSnapshot 只能使用公共 mark price 接口；
Execution 是唯一允许调用订单提交接口的业务模块；
OrderStatusSync 只能调用订单状态查询接口；
FillSync 只能调用成交查询接口。
```

禁止：

```text
任何模块绕过 BinanceGateway 请求 Binance；
任何模块调用交易所修改杠杆接口；
Gateway 代替业务模块写业务状态；
Gateway 代替业务模块写业务 AlertEvent；
订单提交自动重试。
```

### 6.2 StrategyCalculator

允许调用方：

```text
FeatureLayer service；
AtomicSignal service；
DomainSignal service；
MarketRegime service；
StrategyRouting service；
StrategySignal service；
DecisionPolicy service；
后台研究 / 回测 service。

## 11. StrategyBacktest 模块边界

StrategyBacktest 是测试环境策略收益回放模块。

| 模块 | 输入 | 输出 | 禁止 |
| --- | --- | --- | --- |
| StrategyBacktest | 历史 Kline、StrategyAnalysisRelease、UTC 时间范围、初始资金、手续费、回测杠杆倍数 | StrategyBacktestRun 状态、回测 JSON 摘要、StrategyBacktestPeriodResult 周期模拟调仓明细和估算爆仓信息 | 不进入订单链路，不提交订单，不写 TradeFill，不影响 ActiveLock，不修改策略版本包，不修改交易所真实杠杆 |

StrategyBacktest 可以复用现有策略分析链路取得历史目标仓位语义，但不得把收益结果写回正式策略分析对象。

当前 P0 只允许非 production 环境运行。
```

禁止：

```text
编排层直接调用；
calculator 之间直接调用；
调用 BinanceGateway；
调用外部大模型；
调用 Celery；
生成订单对象；
读取账户或持仓；
输出真实交易指令。
```

## 7. 真实交易权限关系

真实交易权限检查位置：

```text
Binance Account Sync（自动四小时账户边界，编排起始步骤）
→ DecisionSnapshot
→ TARGET_POSITION：PriceSnapshot
→ OrderPlanStepAdapter 真实交易权限检查
→ OrderPlan
或 NO_TARGET_CHANGE / NO_TRADE：正常结束
```

规则：

```text
自动四小时编排起始阶段必须先保存一次 trade_preparation 账户快照；
NO_TARGET_CHANGE / NO_TRADE 不补做账户同步，不生成 PriceSnapshot 或订单链路；
权限检查未通过时，不得调用 OrderPlan；
权限检查未通过时，不得生成 CandidateOrderIntent；
权限检查未通过时，不得取得 ActiveLock；
检查通过后，本轮后续步骤不重新读取 MySQL 运行开关；
后台开关变化只影响下一次进入 OrderPlan 的检查。
```

Execution、OrderStatusSync、FillSync 不重新读取真实交易运行开关。

## 8. 对象追溯关系

主链路业务对象的正式追溯关系：

```text
Kline
→ DataQualityResult
→ MarketSnapshot
→ FeatureSet / FeatureValue
→ AtomicSignalSet / AtomicSignalValue
→ DomainSignalSet / DomainSignalValue
→ MarketRegimeSnapshot
→ StrategyRouteDecision
→ StrategySignal
→ StrategySignalQualityResult
→ DecisionSnapshot
→ OrderPlan
→ CandidateOrderIntent
→ RiskCheckResult
→ ApprovedOrderIntent
→ PreparedOrderIntent
→ OrderSubmissionAttempt
→ OrderStatusSyncRecord
→ TradeFill / OrderFillSummary
```

`OrchestrationBusinessObjectLink` 只提供一轮运行的快捷审计索引，不替代上述业务外键。

主交易业务对象不得把 `OrchestrationRun.id` 当作正式业务外键或下游输入。

## 9. 禁止跨越关系清单

以下跨越关系禁止：

```text
FeatureLayer → OrderPlan
AtomicSignal → StrategySignal（绕过 DomainSignal / MarketRegime / StrategyRouting）
DomainSignal → StrategySignal（绕过 MarketRegime / StrategyRouting）
MarketRegime → StrategySignal（绕过 StrategyRouting）
StrategySignal → DecisionSnapshot 之外的订单链路
DecisionSnapshot → Binance Account Sync
DecisionSnapshot → PriceSnapshot
DecisionSnapshot → OrderPlan 内部订单计算
DecisionSnapshot → RiskCheck
DecisionSnapshot → Execution
OrderPlan → BinanceGateway
OrderPlan → Execution
RiskCheck → DecisionSnapshot
RiskCheck → Execution
ExecutionPreparation → BinanceOrderSubmissionGateway
Execution → OrderPlan / RiskCheck 内部逻辑
OrderStatusSync → Execution 订单提交
OrderStatusSync → FillSync 成交生成之外的订单修改
FillSync → Execution 订单提交
RuntimeGuard → ActiveLock 直接释放
OpsConsole → BinanceGateway
OpsConsole → 外部大模型
Notifications → 交易链路
ReviewDataset → 交易链路
```

## 10. 未定义关系处理规则

如果编码时发现需要新增本文档没有定义的模块关系，必须先判断：

```text
是否已有 requirements 明确允许；
是否会绕过上游事实；
是否会绕过风控或执行前检查；
是否会访问不该访问的 Gateway；
是否会写入不属于本模块的业务对象；
是否会影响真实交易、锁、订单提交或资金安全。
```

只要存在不确定，必须停止实现并向用户确认。

不得用“临时方便”“先打通流程”“后面再拆”作为跨越模块边界的理由。

## 11. 最终结论

模块边界架构的核心结论是：

```text
每个模块只消费直接上游的已落库事实或明确输入，只生成自己拥有的业务对象；
跨模块协作通过 service、selector、Gateway、OrchestrationBusinessObjectLink 和真实业务外键完成；
任何绕过 DataQuality、MarketSnapshot、StrategyRouting、DecisionSnapshot、OrderPlan、RiskCheck、ExecutionPreparation 或 Execution 的实现都属于架构违规。
```
