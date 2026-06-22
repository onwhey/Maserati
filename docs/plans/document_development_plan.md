# 文档开发计划

## 1. 文档目的

本文档用于安排新版开发文档的后续编写顺序，明确：

```text
哪些文档已经完成；
哪些文档必须在编码前完成；
哪些文档只在具体算法确定后编写；
哪些文档应当等到代码设计阶段再编写；
哪些文档当前不需要创建。
```

本计划只管理当前全新开发文档，不修改旧文档。

## 2. 当前完成情况

### 2.1 工作规则

已完成：

```text
AGENTS.md
```

### 2.2 Requirements

`docs/requirements/` 当前已有需求文件已经完成逐项复核和统一口径。

需求体系已经覆盖：

```text
项目范围与系统能力；
核心业务合同与项目底座；
行情采集、质量检查、回补和市场快照；
特征、原子信号、领域信号和市场环境；
策略路由、策略信号、质量检查和目标仓位决策；
账户同步、价格快照、订单计划和风控；
执行准备、订单提交、订单状态和成交同步；
编排、通知、巡检、后台、绩效和 AI 复盘；
BinanceGateway、DeepSeekGateway、StrategyCalculator 和 StrategyAnalysisRelease。
```

### 2.3 Architecture

已完成：

```text
docs/architecture/system_architecture.md
docs/architecture/module_boundary_architecture.md
docs/architecture/data_flow_architecture.md
docs/architecture/runtime_task_architecture.md
docs/architecture/testing_and_safety_architecture.md
docs/architecture/README.md
```

上述文档已经分别回答：

```text
系统整体如何分层；
模块之间允许和禁止什么关系；
业务事实如何产生、传递、落库和停止传播；
运行任务如何调度、等待、恢复和隔离；
开发、测试、持续集成与实盘前如何完成安全验收；
不同开发任务如何找到并组合阅读上述架构依据。
```

### 2.4 Rules

已完成：

```text
docs/rules/project_invariants.md
```

## 3. 编码前必须继续完成的文档

以下文档按建议顺序编写。

### 3.1 `docs/rules/project_invariants.md`

优先级：第一。

状态：已完成。

作用：

```text
集中保存绝对不可违反的系统红线；
作为 requirements、architecture、plans 和代码的最高约束；
避免真实交易、订单提交、账户事实、策略边界和外部调用红线散落在多个文件中。
```

重点内容：

```text
主交易链不可绕过；
真实交易默认关闭；
真实交易权限检查位置；
订单提交绝不重试；
unknown 必须保守处理；
ActiveLock 释放证据；
所有 Binance 请求必须经过 BinanceGateway；
大模型不得参与实时交易；
MySQL 与 Redis 的事实边界；
数据采集域与交易域隔离；
UTC 时间规则；
正式主链路只运行冻结的 StrategyAnalysisRelease。
```

该文件只保存系统级不变量，不重复各模块的普通需求。

### 3.2 `docs/architecture/runtime_task_architecture.md`

优先级：第二。

状态：已完成。

作用：

```text
明确四小时自动编排如何触发；
明确 Celery task、Celery Beat、Connector 和 application service 的关系；
明确同步步骤、异步等待、恢复和巡检之间的边界；
明确哪些安全读取允许有限技术重试；
明确订单提交在任何层都不得重试；
明确 RuntimeGuard 的独立调度方式。
```

重点内容：

```text
四小时主编排调度；
日线数据在四小时编排中的消费条件；
任务入口与 service 边界；
OrchestrationRun / StepRun 的运行状态；
WAIT、恢复令牌和 worker 释放；
OrderStatusSync 两秒一次、最多三十秒的等待方式；
任务幂等和重复投递；
进程崩溃后的安全恢复；
RuntimeGuard 每十分钟独立巡检；
通知 pending 记录的定时扫描；
后台任务与自动主链路隔离。
```

### 3.3 `docs/architecture/testing_and_safety_architecture.md`

优先级：第三。

状态：已完成。

作用：

```text
统一测试层级和真实交易安全验收方法；
确保单元测试、集成测试、任务测试和 Gateway 测试使用一致边界；
防止测试或开发环境意外访问真实 Binance、DeepSeek 或 Hermes；
明确 dry-run、回测和 real 的数据隔离。
```

重点内容：

```text
calculator 纯计算单元测试；
service 业务合同测试；
repository 与数据库约束测试；
fake BinanceGateway / DeepSeekGateway / Hermes client；
Celery eager 与异步集成测试边界；
MySQL、Redis 故障测试；
订单提交唯一性和绝不重试测试；
unknown、幂等、并发和 ActiveLock 测试；
dry-run、回测、real 数据隔离；
真实交易默认关闭的验收证据。
```

### 3.4 `docs/architecture/README.md`

优先级：第四。

状态：已完成。

作用：

```text
提供架构文档索引；
说明各架构文件分别回答什么问题；
给出开发某类模块时应阅读哪些架构文档；
避免把某一份架构总览当成全部实现依据。
```

该文件应在主要架构文档完成后编写。

### 3.5 `README.md`

优先级：第五。

状态：已完成。

作用：

```text
作为人和 Codex 进入新版项目文档的第一入口；
说明项目定位、文档阅读顺序和目录用途；
链接 AGENTS、requirements、rules、architecture、plans、decisions 和 implementation；
说明当前阶段以文档为开发依据，尚未进入具体编码计划时不得猜测实现。
```

根 README 不重复完整业务需求或架构内容。

## 4. 架构完成后需要编写的开发计划

### 4.1 `docs/plans/implementation_roadmap.md`

在 rules 和 architecture 完成后编写。

作用：

```text
把需求按可交付阶段拆成开发顺序；
定义每阶段的前置条件、负责模块、明确不做事项和验收门槛；
避免按照文件列表机械编码而忽略真实依赖。
```

建议阶段只作为计划方向，最终以编写该文件时的确认结果为准：

```text
项目底座与公共合同；
行情数据与市场事实；
策略分析框架；
账户与价格事实；
订单计划、风控和执行准备；
订单提交、状态和成交闭环；
编排、通知和巡检；
后台、绩效和离线 AI 复盘。
```

### 4.2 分阶段开发计划

只有进入某一开发阶段前，才创建该阶段的具体计划，例如：

```text
docs/plans/foundation_implementation_plan.md
docs/plans/market_data_implementation_plan.md
docs/plans/strategy_analysis_implementation_plan.md
docs/plans/trading_execution_implementation_plan.md
docs/plans/operations_review_implementation_plan.md
```

以上文件名是建议命名，不在当前阶段提前创建。

每份计划至少明确：

```text
实现范围；
直接依赖；
代码模块；
数据库迁移范围；
外部服务边界；
是否涉及真实交易；
测试与验收；
本阶段明确不负责什么。
```

## 5. 具体算法确定后需要编写的文档

当前通用模块需求只定义算法框架、输入输出合同、版本机制和正式发布规则。

具体算法在被选择实现前，必须单独编写算法需求文档。

目录原则：

```text
docs/requirements/<模块>/<算法>.md
```

可能涉及：

```text
FeatureLayer 的具体特征算法；
AtomicSignal 的具体原子信号算法；
DomainSignal 的具体领域聚合算法；
MarketRegime 的具体市场环境分类算法；
StrategyRouting 的具体路由规则；
StrategySignal 的具体策略算法；
DecisionSnapshot 的具体目标仓位映射算法。
```

每份具体算法需求至少定义：

```text
业务目的；
明确输入；
计算公式或判断逻辑；
参数和默认值；
输出语义；
边界情况；
版本身份；
回测和验证要求；
允许进入 StrategyAnalysisRelease 的条件。
```

在具体算法尚未确定时，不创建空算法文档，不凭空填写公式。

## 6. 编码过程中才编写的 Implementation 文档

Implementation 文档记录代码实际如何实现，不替代需求文档。

目录原则：

```text
docs/implementation/<模块>/<实现或算法版本>.md
```

只有以下情况需要创建：

```text
特征和信号计算逻辑复杂；
市场环境、策略或目标仓位算法需要记录实际实现；
订单计划、风控或执行状态机存在复杂内部逻辑；
代码实现与多个模块协作，需要记录关键实现选择；
复盘归因逻辑需要保存实际计算口径。
```

Implementation 文档应在代码方案已经确定或代码实现完成时编写，记录：

```text
实际代码位置；
实际类和 service；
实际 calculator 注册；
实际数据库交互；
实际异常和状态处理；
测试覆盖；
与对应 requirements 的映射。
```

不得在当前架构阶段提前伪造实现记录。

## 7. 按实际需要创建的 Decisions 文档

目录：

```text
docs/decisions/
```

只有出现以下情况时才创建架构决策文档：

```text
requirements 没有直接给出唯一实现方向；
存在两种以上都会影响长期架构的可行方案；
选择结果会影响多个模块；
未来开发者需要知道为什么只能采用当前方案。
```

不为已经在 requirements 中明确确定的普通业务规则重复创建 Decision。

Decision 不得修改 requirements 的业务语义。如需改变需求，必须先修改 requirements，再记录相应架构选择。

## 8. 等到代码设计阶段再处理的文档

以下内容当前不单独编写：

```text
详细 Django Model 设计；
数据库表、字段类型、索引和 migration 清单；
repository / selector 具体接口；
REST API 路径和 serializer 字段；
Celery task 的具体函数名和 queue 名称；
Django app 最终目录结构；
前端组件和页面字段；
生产部署拓扑和容量参数。
```

这些内容应在对应阶段开发计划中确定，再随代码实现形成必要的 implementation 或部署文档。

当前不创建 `data_model_overview.md`。核心对象、对象所有权、业务外键和数据流已经由以下文件覆盖：

```text
docs/requirements/core_contracts.md
docs/architecture/module_boundary_architecture.md
docs/architecture/data_flow_architecture.md
```

等开始设计 Django Model 时，再根据实际模块边界制定数据模型和 migration 计划。

## 9. 当前不需要单独创建的重复文档

以下主题已经由现有文档覆盖，当前不再单独拆文件：

```text
Gateway 总览：由 binance_gateway.md、deepseek_gateway.md、system_architecture.md 和 module_boundary_architecture.md 覆盖；
存储总览：由 project_foundation.md、system_architecture.md 和 data_flow_architecture.md 覆盖；
真实交易权限架构：由 core_contracts.md、pipeline_orchestrator.md 和 system_architecture.md 覆盖；
通知架构：由 notifications.md、runtime_guard.md 和 system_architecture.md 覆盖；
后台架构：由 ops_console.md、performance_metrics.md 和 ai_review.md 覆盖；
详细数据模型：延后到代码设计阶段。
```

只有后续需求明显扩大、现有文档无法清晰承载时，才新增相应架构文件。

## 10. 后续执行顺序

从当前状态继续，剩余文档编写顺序为：

```text
1. docs/plans/implementation_roadmap.md
2. 按开发阶段编写对应计划
3. 具体算法确定后编写算法 requirements
4. 编码过程中按需编写 implementation
5. 遇到真实架构选择时按需编写 decisions
```

## 11. 完成标准

进入代码开发前，至少应满足：

```text
requirements 已复核并相互对齐；
project_invariants 已建立；
系统、模块边界、数据流、运行任务和测试安全架构已经明确；
根 README 和架构索引可以引导人和 Codex 正确阅读文档；
implementation_roadmap 已定义开发阶段和验收门槛；
当前准备实现的具体算法已有明确算法 requirements；
没有提前猜测数据库字段、API 结构或未确定算法。
```

## 12. 最终结论

当前文档阶段不继续扩大业务需求，也不提前设计详细数据模型。

后续工作的重点是：

```text
先固定最高系统红线；
再固定运行任务与测试安全架构；
然后制定真正可执行的编码路线；
具体算法和实现记录只在需要实现时补充。
```
