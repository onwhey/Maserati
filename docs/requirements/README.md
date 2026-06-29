# 需求文档索引

## 1. 文档目的

本目录定义系统必须具备的业务能力、模块合同、状态语义、失败边界和验收要求。

需求文档是系统架构、开发计划、实现和测试的业务依据。架构文档负责说明如何组织系统，不得改变需求文档已经确定的业务语义。

## 2. 阅读顺序

开发任何模块前，应按以下顺序阅读：

```text
project_scope.md
→ system_capabilities.md
→ core_contracts.md
→ 对应模块需求
→ architecture 文档
→ plans 文档
```

交易相关模块还必须阅读：

```text
docs/rules/project_invariants.md
```

## 3. 需求分组

### 3.1 项目与基础能力

```text
project_scope.md
system_capabilities.md
core_contracts.md
project_foundation.md
notifications.md
binance_gateway.md
```

### 3.2 行情数据与市场事实

```text
data_collection.md
data_quality.md
data_backfill.md
market_snapshot.md
price_snapshot.md
```

### 3.3 特征、信号与决策

```text
feature_layer.md
atomic_signals.md
domain_signals.md
market_regime.md
strategy_routing.md
strategy_signals.md
strategy_signal_quality.md
strategy_calculator.md
strategy_analysis_release.md
decision_snapshot.md
```

### 3.4 账户事实、订单规划与风控

```text
binance_account_sync.md
order_plan.md
risk_check.md
```

### 3.5 执行与交易事实追踪

```text
execution_preparation.md
order_submission.md
order_cycle_closeout.md
order_status_sync.md
fill_sync.md
```

### 3.6 编排、巡检与复盘

```text
pipeline_orchestrator.md
runtime_guard.md
review_dataset.md
ops_console.md
```

## 4. 核心依赖顺序

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
→ OrderPlan / CandidateOrderIntent
→ RiskCheck / ApprovedOrderIntent
→ ExecutionPreparation / PreparedOrderIntent
→ Execution / OrderSubmissionAttempt
→ 订单提交事实完成，主交易编排结束
或 NO_TARGET_CHANGE / NO_TRADE：正常结束，不进入 PriceSnapshot 或订单链路
```

订单提交后的状态与成交同步属于独立订单生命周期分支，不内嵌在主交易编排尾部：

```text
OrderSubmissionAttempt
→ OrderStatusSync
→ FillSync
→ ActiveLock 安全收尾判断
```

LIMIT 订单在本周期到期后仍未终态时，走独立周期收尾分支：

```text
OrderCycleCloseout / OrderCancelAttempt
→ OrderStatusSync
→ FillSync
→ ActiveLock 安全收尾判断
```

`PipelineOrchestrator` 负责按业务结果编排上述能力，但不拥有各模块的业务判断。

`ReviewDataset` 和 `OpsConsole` 属于后置复盘和后台能力，不是自动交易主链路必跑步骤。

`RuntimeGuard` 负责发现自动编排主链路、订单链路、ActiveLock 和通知投递中的卡住、不确定或静默异常，但不自动修改交易事实。

真实交易运行权限由 `.env` 硬权限和 MySQL 后台开关共同决定，并在进入 `OrderPlan` 前检查一次。

## 5. 文档职责规则

每份模块需求只维护以下内容：

```text
模块目标
负责与不负责的事项
输入与输出合同
核心状态和原因码
幂等与并发要求
外部访问边界
数据库、Redis、通知和大模型边界
与上下游模块的关系
异常处理
测试与验收标准
```

模块需求不得重复定义全局交易链路、文档优先级或其他模块的内部实现。

跨模块对象语义统一由 `core_contracts.md` 定义。模块文档只能补充本模块拥有的字段、状态和行为。

## 6. 优先级规则

需求优先级统一使用：

```text
必须：当前系统成立所需的强制能力。
应当：当前范围内应实现，允许在计划中分阶段交付。
可以：不影响当前主链路的增强能力。
不在当前范围：尚未形成完整需求合同，不得提前实现。
禁止：违反系统红线，任何阶段不得实现。
```

模块内部不得使用 P0、P1、P2 表示与项目阶段不同的含义。

## 7. 命名规则

同一个业务对象只能有一个正式名称。

正式名称、对象所有者和对象间关系以 `core_contracts.md` 为准。代码类名、数据库模型名和 API 字段如需不同，必须在对应模块需求中明确映射，不得形成第二套业务术语。

## 8. 时间与审计

所有业务时间使用 UTC。

所有关键业务对象必须携带或可追溯到：

```text
trace_id
trigger_source
业务幂等键
创建时间
最终状态
失败或阻断原因
相关上游对象
```

任何可能影响真实交易、订单追踪、风险判断或人工恢复的行为都不得静默失败。
