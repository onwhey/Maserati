# 架构文档索引

## 1. 文档目的

本文档是 `docs/architecture/` 的阅读入口，用于说明：

```text
现有架构文档分别回答什么问题；
不同开发任务应阅读哪些架构文档；
架构文档与 requirements、rules、plans 和 implementation 的关系；
架构发生变化时应更新哪份文档。
```

本文档只提供索引和阅读指引，不新增业务需求，不替代任何模块需求文件。

## 2. 阅读架构前的前置文档

阅读架构文档前，应先阅读：

1. [`AGENTS.md`](../../AGENTS.md)：Codex 工作纪律、文档优先级和最高禁止行为。
2. [`project_invariants.md`](../rules/project_invariants.md)：任何设计和实现都不得违反的系统红线。
3. [`project_scope.md`](../requirements/project_scope.md)：项目做什么、不做什么。
4. [`system_capabilities.md`](../requirements/system_capabilities.md)：系统需要具备哪些业务能力。
5. [`core_contracts.md`](../requirements/core_contracts.md)：核心对象、对象语义和跨模块合同。
6. 对应的模块需求文件：模块具体应实现什么。

架构文档用于组织已经确定的需求，不能反向修改 requirements 的业务含义。

## 3. 架构文档总览

| 文档 | 核心问题 | 主要使用场景 |
| --- | --- | --- |
| [`system_architecture.md`](./system_architecture.md) | 系统整体由哪些层组成，各层如何协作 | 理解全局结构、确定新能力属于哪一层 |
| [`module_boundary_architecture.md`](./module_boundary_architecture.md) | 每个模块负责什么、不得做什么、允许依赖谁 | 划分 Django app、service、adapter、Gateway 和跨模块调用 |
| [`data_flow_architecture.md`](./data_flow_architecture.md) | 业务事实怎样产生、传递、落库、关联和停止传播 | 设计输入输出、业务外键、审计索引、MySQL 与 Redis 使用方式 |
| [`runtime_task_architecture.md`](./runtime_task_architecture.md) | 四小时编排、异步等待、任务调度、恢复和运行隔离怎样工作 | 设计 Celery task、Celery Beat、任务队列和运行恢复 |
| [`testing_and_safety_architecture.md`](./testing_and_safety_architecture.md) | 如何证明代码符合需求且不会误触真实外部能力 | 编写测试、配置 CI、阶段验收和实盘前安全检查 |

这五份文档从不同角度描述同一个系统，不是五套独立设计。

## 4. 推荐阅读顺序

首次理解系统时，按以下顺序阅读：

```text
system_architecture.md
→ module_boundary_architecture.md
→ data_flow_architecture.md
→ runtime_task_architecture.md
→ testing_and_safety_architecture.md
```

阅读逻辑是：

```text
先理解系统整体分层；
再确认模块职责和依赖边界；
再理解业务事实如何流动；
再理解这些模块如何被任务调度和恢复；
最后确认如何测试和验收整个设计。
```

## 5. 按开发任务选读

### 5.1 开发普通业务模块

至少阅读：

```text
对应 requirements；
module_boundary_architecture.md；
data_flow_architecture.md；
testing_and_safety_architecture.md。
```

需要先确认：

```text
模块输入来自哪里；
模块产生什么业务事实；
业务事实写入哪里；
下游通过什么业务外键读取；
模块失败后是否允许继续传播；
应通过哪些测试证明合同成立。
```

### 5.2 开发行情、特征和策略分析链路

先阅读：

```text
system_architecture.md；
module_boundary_architecture.md；
data_flow_architecture.md；
testing_and_safety_architecture.md；
对应的行情、特征、信号、策略和 DecisionSnapshot requirements。
```

具体算法不得从架构文档中推测。算法公式、参数、版本和验证条件应由对应算法 requirements 定义。

### 5.3 开发账户、价格、订单、风控和执行链路

五份架构文档都必须阅读。

还必须阅读：

```text
binance_gateway.md；
binance_account_sync.md；
price_snapshot.md；
order_plan.md；
risk_check.md；
execution_preparation.md；
order_submission.md；
order_status_sync.md；
fill_sync.md；
pipeline_orchestrator.md。
```

该链路涉及真实交易边界，任何实现都必须同时满足 `project_invariants.md`。

### 5.4 开发 PipelineOrchestrator 或 Celery 任务

重点阅读：

```text
module_boundary_architecture.md；
data_flow_architecture.md；
runtime_task_architecture.md；
testing_and_safety_architecture.md；
pipeline_orchestrator.md。
```

任务入口只负责触发和传递运行上下文，业务判断仍由 application service 和业务模块完成。

### 5.5 开发 BinanceGateway、DeepSeekGateway 或外部通知

重点阅读：

```text
module_boundary_architecture.md；
data_flow_architecture.md；
runtime_task_architecture.md；
testing_and_safety_architecture.md；
对应 Gateway 或 Notifications requirements。
```

外部调用必须遵守对应受限接口、重试、幂等、审计和测试替身边界。

### 5.6 开发 RuntimeGuard

重点阅读：

```text
module_boundary_architecture.md；
runtime_task_architecture.md；
testing_and_safety_architecture.md；
runtime_guard.md。
```

RuntimeGuard 是生产运行期间的只读巡检能力；测试与安全验收架构是开发、持续集成和实盘前验收依据。二者不能互相替代。

### 5.7 开发后台、绩效或 AI 复盘

重点阅读：

```text
system_architecture.md；
module_boundary_architecture.md；
data_flow_architecture.md；
runtime_task_architecture.md；
testing_and_safety_architecture.md；
ops_console.md；
performance_metrics.md；
ai_review.md；
deepseek_gateway.md。
```

这些属于后台或离线能力，不得进入实时策略判断和正式交易决策链路。

## 6. 五份架构文档的分工

### 6.1 系统架构总览

负责回答：

```text
系统包含哪些业务层；
正式主链路如何从行情走到成交同步；
底层能力、运行能力和后台能力位于哪里；
各层之间的总体依赖方向是什么。
```

不负责具体字段、接口参数、算法公式或任务名称。

### 6.2 模块边界架构

负责回答：

```text
每个模块拥有哪类业务职责；
模块允许调用哪些上游或底层能力；
模块不得越权承担什么职责；
跨模块连接应经过 service、adapter 还是 Gateway。
```

不负责重复每份 requirements 的完整功能清单。

### 6.3 数据流架构

负责回答：

```text
外部事实和内部业务事实如何形成；
上游结果怎样交给下游；
业务外键和编排审计索引分别解决什么问题；
MySQL、Redis、日志和 AlertEvent 分别保存什么；
失败或阻断后哪些事实不得继续传播。
```

不负责提前确定 Django Model 字段、数据库索引和 migration 细节。

### 6.4 运行任务架构

负责回答：

```text
谁按四小时触发正式编排；
编排步骤怎样串行推进；
订单关键步骤怎样异步等待并恢复；
不同任务组怎样逻辑隔离；
重复投递、进程退出和运行卡住时怎样安全处理；
RuntimeGuard 和后台任务怎样独立运行。
```

不负责承载业务模块内部计算逻辑。

### 6.5 测试与安全验收架构

负责回答：

```text
不同层级代码应使用什么类型的测试；
外部服务如何使用 fake 或 mock 隔离；
哪些故障、幂等、并发和未知状态必须验证；
dry-run、回测和 real 怎样隔离；
持续集成和实盘前准入需要什么证据。
```

它是一份开发和验收规范，不是生产运行模块。

## 7. 架构文档与其他文档的关系

### 7.1 Requirements

Requirements 定义系统和模块必须实现的业务结果、输入输出、边界条件和禁止行为。

Architecture 负责把这些需求组织成一致的系统结构，不得削弱或改变需求。

### 7.2 Rules

`project_invariants.md` 保存最高系统红线。

任何架构内容与系统红线冲突时，必须先停止设计并处理冲突，不能在架构文档中自行放宽红线。

### 7.3 Plans

Plans 定义开发顺序、阶段范围、前置条件和验收门槛。

Architecture 说明系统应怎样组织；Plans 说明这些内容何时实现。

### 7.4 Decisions

Decisions 记录存在多个可行架构方案时最终选择了哪一种，以及为什么。

Decision 不得绕过 requirements 改变业务需求。需求需要变化时，应先修改 requirements。

### 7.5 Implementation

Implementation 记录代码最终如何实现复杂内部逻辑。

Architecture 不提前虚构具体类名、表字段、队列名和代码位置；这些内容应在对应开发阶段确定后记录。

## 8. 架构变更时更新哪份文档

出现以下变化时，更新对应文档：

| 变化类型 | 应更新的文档 |
| --- | --- |
| 新增、删除或重新划分系统层 | `system_architecture.md` |
| 模块职责、所有权或依赖方向变化 | `module_boundary_architecture.md` |
| 业务事实来源、消费关系、存储或停止传播规则变化 | `data_flow_architecture.md` |
| 调度周期、任务边界、等待恢复或任务隔离变化 | `runtime_task_architecture.md` |
| 测试层级、外部隔离、安全验收或实盘准入变化 | `testing_and_safety_architecture.md` |
| 架构文件增加、删除或阅读方式变化 | 本 README |

如果变化首先属于业务需求变化，应先修改对应 requirements，再更新受影响的架构文档。

## 9. 当前不由架构索引确定的内容

本索引不确定以下实现细节：

```text
Django app 最终目录；
Model、字段、索引和 migration；
repository、selector 和 service 的具体接口名；
Celery task、queue 和 routing key 的具体名称；
REST API 和后台页面字段；
具体策略、信号、特征和目标仓位算法；
生产部署数量和容量参数。
```

这些内容应在对应阶段计划、算法 requirements、代码设计或 implementation 文档中确定。

## 10. 架构阅读完成标准

开发者或 Codex 在开始模块设计前，至少应能够回答：

```text
该模块属于系统哪一层；
该模块负责什么和不负责什么；
它从哪里读取哪些业务事实；
它产生什么结果并由谁消费；
结果写入 MySQL、Redis、日志还是 AlertEvent；
它如何被调度或调用；
失败、阻断、unknown 和重复调用时如何处理；
应使用哪些测试证明实现符合需求；
是否涉及真实交易或外部服务。
```

如果其中任何关键答案无法从 requirements、rules 和 architecture 中确认，应先向用户确认，不得在编码时自行猜测。

## 11. 最终结论

架构目录的五份主体文档分别从整体分层、模块边界、数据流、运行任务和测试安全五个角度约束同一个系统。

本 README 只负责把这些文档连接起来，使人和 Codex 能够根据当前任务找到正确依据。
