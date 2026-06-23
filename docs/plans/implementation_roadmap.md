# 实施路线图

## 1. 文档目的

本文档用于把已经完成的 requirements、rules 和 architecture 拆成可执行的开发阶段。

它回答：

```text
先做什么；
后做什么；
每个阶段的前置条件是什么；
每个阶段交付到什么程度；
哪些能力不能提前实现；
每个阶段如何验收；
哪些后续计划需要在进入阶段前再细化。
```

本文档不是代码设计，不定义最终 Django app、Model 字段、API 路径、Celery task 名称或数据库迁移细节。

具体代码结构必须在对应阶段计划和实现阶段再确定。

## 2. 总体原则

开发必须按业务依赖推进，而不是按 requirements 文件列表机械实现。

总原则：

```text
先底座，后业务；
先事实，后策略；
先策略分析，后交易执行；
先只读事实，后真实下单；
先自动化测试和安全边界，后真实交易能力；
先主链路闭环，后后台体验；
先可追溯，后复杂优化。
```

任何阶段不得绕过：

```text
docs/rules/project_invariants.md；
docs/requirements/core_contracts.md；
docs/architecture/module_boundary_architecture.md；
docs/architecture/data_flow_architecture.md；
docs/architecture/testing_and_safety_architecture.md。
```

## 3. 阶段总览

建议开发阶段如下：

```text
阶段 0：项目底座与公共合同
阶段 1：行情数据与市场事实
阶段 2：策略分析框架
阶段 3：账户与价格事实
阶段 4：订单计划、风控与执行准备
阶段 5：订单提交、状态与成交闭环
阶段 6：编排、任务、通知与巡检
阶段 7：后台、绩效与离线 AI 复盘
```

阶段之间允许为了测试建立最小 fake / stub，但不得提前实现下一阶段的真实业务能力。

例如：

```text
策略分析阶段可以使用 fake 账户事实测试下游接口形状；
账户与价格阶段可以使用 fake BinanceGateway；
订单执行阶段可以使用 fake OrderSubmissionGateway；
但不得在前置阶段真实下单、真实调用 DeepSeek 或绕过主链路。
```

## 4. 阶段 0：项目底座与公共合同

### 4.1 目标

建立可以承载后续模块的 Django 项目底座、配置体系、数据库连接、Redis 连接、日志、基础审计、AlertEvent、测试框架和公共合同。

### 4.2 范围

本阶段至少包括：

```text
Django 5.2.x 项目初始化；
Python 3.12 约束；
pyproject.toml；
MySQL 配置；
Redis 配置；
Celery / Celery Beat 基础安装；
pytest / Django test framework；
settings 分层；
.env.example；
日志基础；
UTC 时间基础规则；
AlertEvent 基础模型或等价事件事实；
AuditRecord 基础能力；
公共枚举、状态、错误码和 trace_id 基础能力；
基础 selector / service / repository 组织规则。
```

### 4.3 关键要求

Django 默认不会自动读取 `.env`。

因此本阶段必须明确实现：

```text
Django settings 显式读取 .env；
数据库配置从 .env / 环境变量读取；
Redis 配置从 .env / 环境变量读取；
Celery broker / result backend 从 .env / 环境变量读取；
.env.example 提供中文注释和默认示例；
真实 .env 不提交 Git；
缺少必要数据库配置时启动必须给出清晰错误，而不是静默连接默认数据库。
```

特别注意：

```text
不得依赖 Django 默认 DATABASES 配置；
不得把 MySQL 用户名、密码、host、port、database 写死在 settings；
不得因为本地开发方便把 SQLite 作为正式默认配置；
不得在测试外绕过 .env 配置读取。
```

### 4.4 文档依据

主要需求依据：

```text
docs/requirements/project_foundation.md
docs/requirements/core_contracts.md
docs/requirements/system_capabilities.md
docs/requirements/notifications.md
```

公共约束：

```text
docs/rules/project_invariants.md
AGENTS.md
README.md
```

架构依据：

```text
docs/architecture/system_architecture.md
docs/architecture/module_boundary_architecture.md
docs/architecture/runtime_task_architecture.md
docs/architecture/testing_and_safety_architecture.md
```

阶段计划必须再次确认这些文件，不能只读本 roadmap。

### 4.5 不负责

本阶段不实现：

```text
行情采集；
策略计算；
Binance 真实请求；
OrderPlan；
RiskCheck；
订单提交；
后台 UI；
AIReview；
复杂数据模型细节。
```

### 4.6 验收门槛

本阶段通过必须满足：

```text
项目可以启动 Django；
settings 能正确从 .env 读取 MySQL 配置；
错误数据库配置会明确失败；
pytest 能运行最小测试；
Django migration 能在测试数据库执行；
Redis 配置可被读取；
Celery app 能加载但不要求完整业务任务；
.env.example 完整列出必要配置并带中文注释；
不会访问真实 Binance、DeepSeek 或 Hermes；
真实交易默认关闭。
```

## 5. 阶段 1：行情数据与市场事实

### 5.1 目标

实现行情数据基础链路，形成可信的市场事实输入。

### 5.2 范围

本阶段包括：

```text
DataCollection；
DataQuality；
DataBackfill；
MarketSnapshot；
Kline 存储；
数据质量结果；
缺口识别；
受控回补；
行情窗口选择；
MarketSnapshot 生成。
```

数据采集范围固定为：

```text
Binance USDS-M BTCUSDT；
4h 和 1d 已收盘 Kline；
UTC；
不传 timeZone。
```

### 5.3 依赖

依赖阶段 0。

需要 fake BinanceGateway 或临时受限只读接口测试行情采集，但真实请求边界仍必须遵守 BinanceGateway 需求。

### 5.4 文档依据

主要需求依据：

```text
docs/requirements/data_collection.md
docs/requirements/data_quality.md
docs/requirements/data_backfill.md
docs/requirements/market_snapshot.md
```

公共约束：

```text
docs/requirements/binance_gateway.md
docs/requirements/project_foundation.md
docs/requirements/core_contracts.md
docs/requirements/project_scope.md
docs/requirements/system_capabilities.md
docs/rules/project_invariants.md
```

架构依据：

```text
docs/architecture/data_flow_architecture.md
docs/architecture/module_boundary_architecture.md
docs/architecture/runtime_task_architecture.md
docs/architecture/testing_and_safety_architecture.md
```

本阶段会请求 Binance Kline，因此必须遵守 BinanceGateway 的公共只读接口边界。DataCollection / DataBackfill 不得自己拼 HTTP、签名、限流或重试。

### 5.5 不负责

本阶段不实现：

```text
账户同步；
价格快照；
特征计算；
策略信号；
订单；
风控；
执行；
后台复盘。
```

### 5.6 验收门槛

```text
只能采集 BTCUSDT USDS-M 4h / 1d 已收盘 Kline；
重复采集幂等；
缺失 Kline 可识别；
必要时可触发受控 DataBackfill；
回补后必须重新 DataQuality；
MarketSnapshot 只能使用通过质量检查的数据；
不得使用未收盘 Kline；
所有时间按 UTC；
测试不访问真实 Binance。
```

## 6. 阶段 2：策略分析框架

### 6.1 目标

实现从 MarketSnapshot 到 DecisionSnapshot 的策略分析主链路框架。

### 6.2 范围

本阶段包括：

```text
FeatureLayer；
AtomicSignals；
DomainSignals；
MarketRegime；
StrategyRouting；
StrategySignals；
StrategySignalQuality；
DecisionSnapshot；
StrategyCalculator；
StrategyAnalysisRelease；
算法注册与版本冻结；
正式发布包选择；
策略分析链路测试。
```

### 6.3 算法要求

本阶段必须建立完整框架和测试可运行的算法替身，但不得为了跑通链路而发明正式算法。

具体算法必须满足：

```text
正式链路只运行已批准、已启用、已冻结的 StrategyAnalysisRelease；
Feature / Atomic / Domain / MarketRegime / Strategy / DecisionPolicy 的算法实现必须可版本化；
算法文档放在 docs/requirements/<模块>/<算法>.md；
代码实现记录按需放在 docs/implementation/<模块>/；
测试专用算法只能验证框架、依赖闭包和数据传递，不得批准、启用或进入真实订单链路；
只有具体算法 requirements、验证证据和依赖闭包齐全后，才能形成正式 StrategyAnalysisRelease；
DecisionSnapshot 不读取账户、价格或 Binance；
DecisionSnapshot 不区分策略类型再次计算市场；
DecisionSnapshot 只输出目标仓位意图。
```

### 6.4 依赖

依赖阶段 1 的 MarketSnapshot。

### 6.5 文档依据

主要需求依据：

```text
docs/requirements/feature_layer.md
docs/requirements/atomic_signals.md
docs/requirements/domain_signals.md
docs/requirements/market_regime.md
docs/requirements/strategy_routing.md
docs/requirements/strategy_signals.md
docs/requirements/strategy_signal_quality.md
docs/requirements/decision_snapshot.md
docs/requirements/strategy_calculator.md
docs/requirements/strategy_analysis_release.md
```

公共约束：

```text
docs/requirements/core_contracts.md
docs/requirements/project_scope.md
docs/requirements/system_capabilities.md
docs/rules/project_invariants.md
```

架构依据：

```text
docs/architecture/data_flow_architecture.md
docs/architecture/module_boundary_architecture.md
docs/architecture/system_architecture.md
docs/architecture/testing_and_safety_architecture.md
```

如本阶段选择实现具体算法，必须补充对应算法需求文档；不得只在代码里临时写算法。

### 6.6 不负责

本阶段不实现：

```text
账户同步；
PriceSnapshot；
OrderPlan；
真实交易权限检查；
RiskCheck；
订单提交；
成交同步；
真实策略收益验证。
```

### 6.7 验收门槛

```text
测试专用版本包可以验证 MarketSnapshot 到 DecisionSnapshot 的完整框架链路；
具体正式算法需求齐全时，正式版本包可以按 FeatureSet、AtomicSignalSet、DomainSignalSet、MarketRegimeSnapshot、StrategyRouteDecision、StrategySignal、StrategySignalQuality、DecisionSnapshot 顺序运行；
DecisionSnapshot 只表达 TARGET_POSITION / NO_TARGET_CHANGE / NO_TRADE；
没有唯一可用 StrategyAnalysisRelease 时不能进入 FeatureLayer；
未批准算法不能进入正式链路；
测试专用算法不能被批准或启用为正式版本包；
dry-run 或后台研究结果不能进入正式下游。
```

## 7. 阶段 3：账户与价格事实

### 7.1 目标

实现 Binance 访问边界、自动账户边界同步和交易价格事实。

### 7.2 范围

本阶段包括：

```text
BinanceGateway；
Binance Account Sync；
PriceSnapshot；
active market domain 配置读取；
USDS-M / COIN-M 隔离；
账户、余额、持仓、交易规则快照；
mark price 快照；
Redis 短期价格缓存；
OpsConsole 账户展示所需 ops_display 同步入口的后端 service。
```

### 7.3 关键要求

自动四小时编排起始阶段必须生成：

```text
trade_preparation BinanceSyncRun；
BinanceAccountSnapshot；
BinanceBalanceSnapshot；
BinancePositionSnapshot；
BinanceSymbolRuleSnapshot。
```

该账户边界事实：

```text
不依赖后续是否交易；
不因 NO_TRADE / NO_TARGET_CHANGE 补做；
不使用 ops_display 兜底；
不读取数据库 latest 兜底；
供 OrderPlan、RiskCheck、ExecutionPreparation 和 PerformanceMetrics 使用。
```

PriceSnapshot：

```text
只在 TARGET_POSITION 分支创建；
通过 BinanceGateway 主动请求 mark price；
MySQL 持久化；
Redis 只缓存同一事实；
同一业务请求不能刷新或创建第二份价格快照。
```

### 7.4 依赖

依赖阶段 0。

可与阶段 2 后半并行设计接口，但正式接入必须等阶段 2 的 DecisionSnapshot 合同稳定。

### 7.5 文档依据

主要需求依据：

```text
docs/requirements/binance_gateway.md
docs/requirements/binance_account_sync.md
docs/requirements/price_snapshot.md
docs/requirements/project_foundation.md
```

公共约束：

```text
docs/requirements/core_contracts.md
docs/requirements/project_scope.md
docs/requirements/system_capabilities.md
docs/rules/project_invariants.md
```

架构依据：

```text
docs/architecture/data_flow_architecture.md
docs/architecture/module_boundary_architecture.md
docs/architecture/runtime_task_architecture.md
docs/architecture/testing_and_safety_architecture.md
```

本阶段的公共底层能力是 BinanceGateway。Binance Account Sync、PriceSnapshot 和后续订单相关模块都不得绕过 Gateway。

### 7.6 不负责

本阶段不实现：

```text
OrderPlan；
RiskCheck；
ExecutionPreparation；
订单提交；
订单状态；
成交同步；
绩效计算。
```

### 7.7 验收门槛

```text
所有 Binance 请求经过 BinanceGateway；
Gateway 不暴露通用 request 给业务层；
账户同步只能同步当前 active domain；
ops_display 不进入交易链路；
自动账户边界同步失败不能用旧快照兜底；
PriceSnapshot 不从账户持仓 mark_price 或 Kline 派生；
Redis 不可用不影响 MySQL 事实；
测试使用 fake Binance。
```

## 8. 阶段 4：订单计划、风控与执行准备

### 8.1 目标

实现从目标仓位到准备提交订单前的完整安全链路。

### 8.2 范围

本阶段包括：

```text
OrderPlan；
CandidateOrderIntent；
OrderPlanActiveLock；
RiskCheck；
RiskRule 插件框架；
ApprovedOrderIntent；
ExecutionPreparation；
PreparedOrderIntent；
BinancePublicMarketGateway.get_book_ticker 受限盘口读取能力；
真实交易权限检查；
price guard。
```

### 8.3 关键要求

```text
OrderPlanStepAdapter 在调用 OrderPlan 前检查真实交易权限；
真实交易权限 = .env 硬权限 AND MySQL 后台运行开关；
权限关闭时不调用 OrderPlan，不生成 CandidateOrderIntent，不取得 ActiveLock；
OrderPlan 只把目标仓位转换成 CandidateOrderIntent；
RiskCheck 只审批 CandidateOrderIntent；
RiskCheck 不缩单，不任意修改订单；
ExecutionPreparation 只做提交前最终检查和价格保护；
ExecutionPreparation 不提交订单；
阶段 4 在既有 BinanceGateway 中补齐实时盘口接口，不另建 Binance client；
实时价格与本周期 mark price 偏差 > 1% 阻断；
偏差 <= 1% 允许继续。
```

### 8.4 依赖

依赖阶段 2 的 DecisionSnapshot。

依赖阶段 3 的 BinanceSyncRun 和 PriceSnapshot。

### 8.5 文档依据

主要需求依据：

```text
docs/requirements/order_plan.md
docs/requirements/risk_check.md
docs/requirements/execution_preparation.md
docs/requirements/binance_gateway.md
docs/requirements/binance_account_sync.md
docs/requirements/price_snapshot.md
```

公共约束：

```text
docs/requirements/core_contracts.md
docs/requirements/project_foundation.md
docs/requirements/project_scope.md
docs/requirements/system_capabilities.md
docs/rules/project_invariants.md
```

架构依据：

```text
docs/architecture/module_boundary_architecture.md
docs/architecture/data_flow_architecture.md
docs/architecture/testing_and_safety_architecture.md
```

本阶段虽然不提交订单，但已经进入真实交易前的强安全边界，必须重点遵守真实交易权限、ActiveLock 和 price guard 规则。

### 8.6 不负责

本阶段不实现：

```text
真实订单提交；
订单状态查询；
成交同步；
PerformanceMetrics；
AIReview；
复杂后台 UI。
```

### 8.7 验收门槛

```text
NO_TRADE / NO_TARGET_CHANGE 不能进入 OrderPlan；
权限关闭不创建订单链路和锁；
OrderPlan 输入账户和价格事实必须明确；
OrderPlan 不访问 Binance；
RiskCheck 插件可扩展；
RiskCheck DENY / BLOCKED / FAILED 不生成 ApprovedOrderIntent；
ExecutionPreparation price guard 使用 BinanceGateway；
ExecutionPreparation 阻断时不提交订单；
ActiveLock 不会被编排层直接释放。
```

## 9. 阶段 5：订单提交、状态与成交闭环

### 9.1 目标

实现真实订单提交后的状态确认、成交同步和订单链路安全收尾。

### 9.2 范围

本阶段包括：

```text
Execution；
OrderSubmissionAttempt；
BinanceOrderSubmissionGateway 受限调用；
BinanceOrderStatusGateway 受限调用；
BinanceFillQueryGateway 受限调用；
OrderStatusSync；
OrderStatusSyncRecord；
FillSync；
TradeFill；
OrderFillSummary；
ActiveLock 安全释放证据；
unknown 状态处理。
```

### 9.3 关键要求

```text
Execution 是唯一真实订单提交入口；
当前只提交 MARKET 订单；
订单提交绝不重试；
Gateway、业务层、Celery、编排层都不得重试订单提交；
unknown 不推断成功或失败；
unknown 必须进入 OrderStatusSync；
OrderStatusSync 每 2 秒查询一次，最多 30 秒；
查到明确终态立即停止；
既有订单状态和成交查询始终使用原订单冻结市场，不改查当前 active market domain；
FillSync 只在明确终态后查询成交；
FillSync 不修改账户或持仓快照；
新的持仓事实只能来自新的 Binance Account Sync。
```

### 9.4 依赖

依赖阶段 4 的 PreparedOrderIntent。

依赖阶段 3 建立的 BinanceGateway 公共结构、市场域隔离和凭据基础；订单提交、订单状态查询和成交查询三个受限接口由本阶段补齐。

### 9.5 文档依据

主要需求依据：

```text
docs/requirements/order_submission.md
docs/requirements/order_status_sync.md
docs/requirements/fill_sync.md
docs/requirements/binance_gateway.md
docs/requirements/order_plan.md
```

公共约束：

```text
docs/requirements/core_contracts.md
docs/requirements/project_foundation.md
docs/requirements/system_capabilities.md
docs/rules/project_invariants.md
```

架构依据：

```text
docs/architecture/data_flow_architecture.md
docs/architecture/module_boundary_architecture.md
docs/architecture/runtime_task_architecture.md
docs/architecture/testing_and_safety_architecture.md
```

本阶段必须同时阅读订单提交、订单状态、成交同步和 BinanceGateway 文档；订单提交绝不重试是最高优先级约束之一。

### 9.6 不负责

本阶段不实现：

```text
自动重新下单；
撤单；
修改订单；
自动杠杆调整；
模拟交易运行模式；
根据本地成交推导持仓快照。
```

### 9.7 验收门槛

```text
既有 BinanceGateway 已补齐订单提交、订单状态查询和成交查询三个受限接口；
同一 PreparedOrderIntent 最多提交一次；
HTTP 429、5xx、超时、响应损坏都不重试；
accepted 不等于 filled；
unknown 进入状态查询；
OrderStatusSync 未确认终态不释放 ActiveLock；
FillSync synced 或严格 synced_empty 才允许进入锁收尾判断；
FillSync incomplete / unknown / failed_before_query / blocked_before_query / recovery_skipped_out_of_window 不释放锁；
TradeFill 可追溯到 OrderSubmissionAttempt 和终态查询结果；
测试使用 fake Binance，不访问真实交易所。
```

## 10. 阶段 6：编排、任务、通知与巡检

### 10.1 目标

实现自动四小时主编排、任务调度、步骤等待恢复、通知投递和只读运行巡检。

### 10.2 范围

本阶段包括：

```text
PipelineOrchestrator；
OrchestrationBusinessConnector；
BusinessStepAdapter；
OrchestrationRun；
OrchestrationStepRun；
OrchestrationBusinessObjectLink；
Celery / Celery Beat 任务入口；
RuntimeGuard；
Notifications；
NotificationDeliveryAttempt；
NotificationSuppression；
AlertEvent 投递链路。
```

### 10.3 关键要求

```text
编排层只消费 adapter 统一结果；
编排层不理解业务原始 status；
业务模块不保存 OrchestrationRun ID；
ObjectLink 只用于审计和快速查询；
自动四小时编排起始阶段先调用 Binance Account Sync；
OrderStatusSync WAIT 不长期占用 worker；
RuntimeGuard 每 10 分钟独立巡检；
RuntimeGuard 只读，不修复、不补写、不释放锁；
Notifications 负责 AlertEvent 到外部通知的可靠交接；
后台离线任务不属于 RuntimeGuard 巡检范围。
```

### 10.4 依赖

依赖阶段 0 到阶段 5 的主要业务模块。

### 10.5 文档依据

主要需求依据：

```text
docs/requirements/pipeline_orchestrator.md
docs/requirements/runtime_guard.md
docs/requirements/notifications.md
docs/requirements/project_foundation.md
```

公共约束：

```text
docs/requirements/core_contracts.md
docs/requirements/system_capabilities.md
docs/rules/project_invariants.md
```

架构依据：

```text
docs/architecture/runtime_task_architecture.md
docs/architecture/module_boundary_architecture.md
docs/architecture/data_flow_architecture.md
docs/architecture/testing_and_safety_architecture.md
docs/architecture/system_architecture.md
```

本阶段是运行层，不拥有各业务模块的业务规则。PipelineOrchestrator、RuntimeGuard 和 Notifications 必须严格保持各自边界。

### 10.6 不负责

本阶段不实现：

```text
业务算法；
订单计划规则；
风控规则；
真实 Binance 请求细节；
后台 UI；
绩效计算；
AIReview。
```

### 10.7 验收门槛

```text
每轮自动编排创建唯一 OrchestrationRun；
每个实际步骤有 StepRun；
每个关键对象写入 ObjectLink；
DataBackfill 条件循环有上限；
no_strategy / NO_TRADE / NO_TARGET_CHANGE 能正常结束；
真实交易权限关闭不误报为失败；
RuntimeGuard 能发现卡住、unknown、缺失对象和 stale 状态；
RuntimeGuard 不修改业务对象；
通知 pending 能被投递或明确抑制；
重复任务不重复生成业务对象或重复提交订单。
```

## 11. 阶段 7：后台、绩效与离线 AI 复盘

### 11.1 目标

实现面向运维、复盘和人工审查的后台能力。

### 11.2 范围

本阶段包括：

```text
OpsConsole 后端能力；
账户展示；
真实交易运行开关管理；
编排详情查看；
订单链路查看；
RuntimeGuardIssue 查看；
Notification 查看；
PerformanceMetrics 后台一键补算；
OrchestrationRunPerformance；
DeepSeekGateway；
AIReview；
AIReviewPackage；
AIReviewAttempt；
AIReviewReport；
AIReviewFinding；
AIReviewSuggestion。
```

### 11.3 关键要求

```text
OpsConsole 不直接调用 Gateway；
OpsConsole 不能绕过后端 service；
后台账户展示只使用 ops_display；
真实交易运行开关只存 MySQL，不写 .env；
PerformanceMetrics 是后台一键补算，不是自动主链路步骤；
PerformanceMetrics 不请求 Binance；
PerformanceMetrics 只使用相邻自动边界账户快照；
DeepSeekGateway 是底层大模型访问能力；
AIReview 只做离线复盘；
AIReview 不参与实时交易决策，不修改策略、风控或订单。
```

### 11.4 依赖

依赖阶段 0 到阶段 6 的业务事实、编排事实、通知事实和绩效输入。

### 11.5 文档依据

主要需求依据：

```text
docs/requirements/ops_console.md
docs/requirements/performance_metrics.md
docs/requirements/deepseek_gateway.md
docs/requirements/ai_review.md
docs/requirements/binance_account_sync.md
docs/requirements/notifications.md
```

公共约束：

```text
docs/requirements/core_contracts.md
docs/requirements/project_foundation.md
docs/requirements/system_capabilities.md
docs/rules/project_invariants.md
```

架构依据：

```text
docs/architecture/system_architecture.md
docs/architecture/data_flow_architecture.md
docs/architecture/module_boundary_architecture.md
docs/architecture/testing_and_safety_architecture.md
```

本阶段的后台能力不得绕过后端 service；AIReview 和 DeepSeekGateway 只服务离线复盘，不进入实时交易判断。

### 11.6 不负责

本阶段不实现：

```text
复杂前端体验；
自动策略上线；
自动参数优化；
大模型实时交易；
大模型自动修改策略；
自动恢复交易异常。
```

### 11.7 验收门槛

```text
后台可以查看一轮完整 OrchestrationRun；
后台可以查看账户、订单、成交、告警、巡检和绩效；
后台真实交易开关有权限、二次确认和 AuditRecord；
PerformanceMetrics 一键补算可补齐所有缺失可计算周期；
重复补算跳过已有有效记录；
AIReviewPackage 脱敏且可追溯；
AIReviewAttempt 记录 DeepSeekGateway 调用摘要；
AIReviewReport / Finding / Suggestion 只供人工查看；
后台操作不能直接触发交易。
```

## 12. 分阶段计划文件

八个阶段的实施计划均已创建。编码进入某阶段时，应以对应计划为直接执行清单，并先复核其与最新 requirements 和 architecture 是否一致。

当前文件：

```text
docs/plans/foundation_implementation_plan.md
docs/plans/market_data_implementation_plan.md
docs/plans/strategy_analysis_implementation_plan.md
docs/plans/account_price_fact_implementation_plan.md
docs/plans/trading_execution_implementation_plan.md
docs/plans/order_lifecycle_implementation_plan.md
docs/plans/orchestration_runtime_implementation_plan.md
docs/plans/operations_review_implementation_plan.md
```

路线图只维护阶段边界和依赖；具体实施顺序、迁移、测试与验收细节由上述阶段计划维护。

每份阶段计划必须至少说明：

```text
本阶段实现范围；
直接依赖；
拟创建 Django app 或代码模块；
数据库迁移范围；
外部服务边界；
是否涉及真实交易；
是否访问 Binance / DeepSeek / Hermes；
测试命令；
验收标准；
本阶段明确不负责什么。
```

## 13. 当前不得提前实现

在对应阶段到来前，不得提前实现：

```text
真实订单提交；
复杂后台 UI；
模拟交易运行模式；
多策略组合管理；
机器学习模型；
自动参数优化；
自动策略上线；
大模型实时交易判断；
自动恢复交易异常；
未批准算法进入正式链路；
自动修改杠杆、保证金模式或持仓模式。
```

## 14. 路线图完成标准

本路线图完成后，下一步应进入：

```text
docs/plans/foundation_implementation_plan.md
```

进入代码开发前，至少需要：

```text
当前阶段计划已完成；
当前阶段涉及的 requirements 已阅读；
当前阶段涉及的 architecture 已阅读；
测试和安全验收方式明确；
真实交易风险边界明确；
缺失的算法 requirements 已补齐；
没有需要用户确认的业务规则悬空。
```

## 15. 最终结论

项目应先完成底座与事实链路，再进入策略分析和交易执行。

当前最优下一步不是直接编码全部模块，而是先编写：

```text
docs/plans/foundation_implementation_plan.md
```

然后按阶段逐步实现和验收。
