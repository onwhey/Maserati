# the_cypto

## 1. 项目简介

`the_cypto` 是一个中低频自动交易系统，目标是建立从行情事实、策略分析、目标仓位决策，到订单计划、风控、执行、成交同步、巡检和复盘的完整闭环。

当前项目开发文档位于项目根目录：

```text
AGENTS.md
README.md
docs/
```

本文档集用于指导后续开发。当前仓库已经按阶段实现了部分后端、前端和业务骨架，实际实现状态以代码、测试和 `docs/implementation/` 记录为准。

## 2. 当前阶段

当前处于：

```text
需求和架构已经确定；
实施路线和阶段计划已经形成；
代码按阶段持续实现和复核；
策略分析的具体算法文档仍在逐步补齐。
```

编码必须按照 `implementation_roadmap`、`coding_execution_plan` 和对应阶段实施计划推进。计划没有确定的业务规则、具体算法或长期架构选择，仍不得根据目录自行猜测。

## 3. 系统主链路

正式分析与交易链路为：

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
→ PriceSnapshot（仅目标仓位需要调整时）
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

LIMIT 订单到期仍未终态时，走独立周期收尾分支：

```text
OrderCycleCloseout / OrderCancelAttempt
→ OrderStatusSync
→ FillSync
→ ActiveLock 安全收尾判断
```

`PipelineOrchestrator` 负责按照业务顺序推进流程，但不替代业务模块做判断。

`RuntimeGuard`、`ReviewDataset` 和 `OpsConsole` 是运行巡检、后台与复盘数据能力，不是实时策略决策模块。

## 4. 当前业务范围摘要

当前范围的几个关键区别是：

```text
行情采集固定为 Binance USDS-M BTCUSDT 的 4h 和 1d 已收盘 Kline；
行情采集范围不受当前交易市场域配置影响；
交易链路必须支持 USDS-M 和 COIN-M；
一次正式运行只使用一个 active market domain；
正式主链路只运行一个冻结且正式批准的 StrategyAnalysisRelease；
DecisionSnapshot 只表达目标仓位，不生成订单动作；
真实订单只能由 Execution 提交；
项目内不调用大模型；离线复盘可由项目外 Codex skill 或人工工具读取 ReviewDataset 导出数据完成，不参与实时交易判断。
```

完整范围以 [`project_scope.md`](./docs/requirements/project_scope.md) 为准。

## 5. 从哪里开始阅读

### 5.1 Codex 开发入口

Codex 开始任何任务前，首先阅读：

1. [`AGENTS.md`](./AGENTS.md)
2. [`project_invariants.md`](./docs/rules/project_invariants.md)
3. 与任务直接相关的 requirements
4. 与任务直接相关的 architecture
5. 当前阶段 plans
6. 已存在且与任务相关的 decisions 和 implementation

`AGENTS.md` 规定工作纪律；`project_invariants.md` 规定系统红线。二者都不是普通模块需求。

### 5.2 首次理解项目

推荐按以下顺序阅读：

1. 本 README
2. [`project_scope.md`](./docs/requirements/project_scope.md)
3. [`system_capabilities.md`](./docs/requirements/system_capabilities.md)
4. [`core_contracts.md`](./docs/requirements/core_contracts.md)
5. [`requirements/README.md`](./docs/requirements/README.md)
6. [`architecture/README.md`](./docs/architecture/README.md)
7. [`implementation_roadmap.md`](./docs/plans/implementation_roadmap.md)
8. [`coding_execution_plan.md`](./docs/plans/coding_execution_plan.md)

### 5.3 开发某个模块

不要遍历文件名后直接编码。开发某个模块时至少需要确认：

```text
项目红线；
模块需求；
模块上下游需求；
模块边界；
数据流；
运行任务方式；
测试和安全验收；
当前阶段计划。
```

具体选读方式见 [`architecture/README.md`](./docs/architecture/README.md)。

## 6. 文档目录

```text
.
├── AGENTS.md
├── README.md
└── docs/
    ├── requirements/
    ├── rules/
    ├── architecture/
    ├── plans/
    ├── decisions/        按实际架构选择创建
    └── implementation/   编码过程中按需创建
```

各目录职责如下：

| 目录 | 职责 |
| --- | --- |
| `docs/requirements/` | 定义系统与模块必须实现的业务能力和合同 |
| `docs/rules/` | 保存任何设计和实现都不得违反的系统红线 |
| `docs/architecture/` | 组织系统分层、模块边界、数据流、运行任务和测试安全架构 |
| `docs/plans/` | 定义开发阶段、顺序、范围和验收门槛 |
| `docs/decisions/` | 记录存在多个长期架构方案时的实际选择 |
| `docs/implementation/` | 记录复杂逻辑最终如何在代码中实现 |

目录尚未存在时，表示当前阶段尚未需要该类文档，不允许因此跳过更高优先级依据。

## 7. 文档索引

### 7.1 Requirements

需求入口：[`docs/requirements/README.md`](./docs/requirements/README.md)

该索引按照以下业务顺序组织需求：

```text
项目范围与公共合同；
行情和市场事实；
特征、信号、策略与决策；
账户、价格、订单计划与风控；
执行、订单状态与成交同步；
编排、巡检、后台和复盘；
Gateway 与策略计算公共能力。
```

### 7.2 Rules

系统红线入口：[`docs/rules/project_invariants.md`](./docs/rules/project_invariants.md)

该文件优先约束真实交易、订单提交、未知状态、ActiveLock、外部服务、数据存储、时间和正式策略发布。

### 7.3 Architecture

架构入口：[`docs/architecture/README.md`](./docs/architecture/README.md)

架构主体包括：

```text
system_architecture.md；
module_boundary_architecture.md；
data_flow_architecture.md；
runtime_task_architecture.md；
testing_and_safety_architecture.md。
```

### 7.4 Plans

编码路线：[`docs/plans/implementation_roadmap.md`](./docs/plans/implementation_roadmap.md)

编码执行计划：[`docs/plans/coding_execution_plan.md`](./docs/plans/coding_execution_plan.md)

八份阶段实施计划已经位于 `docs/plans/`，分别覆盖项目底座、行情数据、策略分析、账户与价格事实、交易准备、订单生命周期、编排运行和后台复盘。

### 7.5 Decisions

只有出现多个会长期影响系统的可行方案时，才创建 Decision。

Decision 记录技术或架构选择，不得绕过 requirements 改变业务需求。

### 7.6 Implementation

Implementation 文档只在代码方案确定或实现完成时按需创建，用于记录复杂算法、状态机或跨模块实现。

Implementation 不能代替 requirements，也不能把尚未实现的设计写成既成事实。

## 8. 文档优先级

发生冲突时，不根据文件更新时间或篇幅自行选择。

完整优先级和冲突处理纪律由 [`AGENTS.md`](./AGENTS.md) 定义。

如果低优先级文档或代码与高优先级依据冲突，应停止当前实现、指出具体冲突并先完成文档对齐。

## 9. 技术底座

当前确定的技术底座为：

```text
Python 3.12.x
Django 5.2.x LTS
MySQL
Redis
Celery 5.6.x
Celery Beat
pytest / Django test framework
Node.js LTS（仅 OpsConsole 前端）
Next.js + TypeScript（仅 OpsConsole 前端）
shadcn/ui
Recharts
```

具体版本范围、配置、存储、日志、任务和测试要求见 [`project_foundation.md`](./docs/requirements/project_foundation.md)。

当前分阶段实施计划已经形成，但代码工程尚未开始。安装、启动和迁移命令应在对应代码阶段根据实际项目结构补充，不能提前伪造。

## 10. 真实交易安全提示

真实交易默认关闭。

任何真实订单都必须经过文档定义的完整链路，不得直接调用 Binance 下单接口，也不得通过脚本、管理命令、Celery task、后台页面或测试代码绕过正式边界。

订单提交、unknown、ActiveLock、真实交易权限和外部请求的完整红线以 [`project_invariants.md`](./docs/rules/project_invariants.md) 为准。

## 11. 文档使用边界

项目开发只以当前文档集为依据。

历史文档、旧仓库内容或未纳入当前文档集的说明不能覆盖当前需求、架构和系统红线。

如果当前文档缺少实现所必需的业务决定，应向用户确认并先补充文档，不得自行补造规则。

## 12. 开发工作流

后续编码按以下方式推进：

```text
确认对应需求和系统红线；
确认模块边界、数据流和运行方式；
确认当前阶段计划与明确不做事项；
必要时先制定具体算法 requirements；
实现最小完整阶段；
执行测试与安全验收；
按需记录 implementation；
回报实际修改、调用链、外部访问和交易风险。
```

不得仅以“一份需求文件对应一次编码”为理由，重复实现已经抽象为 Gateway、StrategyCalculator 或公共合同的能力。

## 13. 当前明确不做

当前文档阶段不提前确定：

```text
详细 Django Model 和数据库字段；
最终 Django app 目录；
具体 REST API；
具体 Celery task 和 queue 名称；
未确定的特征、信号和策略算法；
生产部署拓扑与容量；
超出当前需求的人工恢复能力。
```

详细范围与非目标以 [`project_scope.md`](./docs/requirements/project_scope.md) 为准。

## 14. 当前下一步

需求、规则、主要架构、编码路线和八份阶段实施计划已经完成。

完成一致性复核后，下一步从阶段 0 开始：

```text
docs/plans/foundation_implementation_plan.md
```

后续按路线图逐阶段实现和验收；进入尚未确定的正式策略算法前，必须先补充对应算法 requirements，不得用测试算法代替生产算法。

## 15. 最终说明

本 README 是人和 Codex 进入项目文档的第一入口。

它负责指出项目是什么、当前做到哪里以及应去哪里寻找依据，不承载完整需求、完整架构或具体实现方案。
