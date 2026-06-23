# 编码执行计划

## 1. 文档目的

本文档用于指导后续真正进入代码实现时，如何按阶段、按边界、按验收标准推进开发。

本文档不替代 requirements、architecture、rules 或各阶段 implementation plan，不新增业务需求，不定义最终字段、接口路径或具体代码命名。

它只回答：

```text
开始写代码时按什么顺序推进；
每个阶段开工前必须读哪些文档；
每个阶段应交付到什么程度；
每次编码如何验收；
哪些内容不能提前实现；
遇到文档冲突或业务不确定时如何处理。
```

## 2. 文档优先级

编码时必须遵守以下优先级：

```text
AGENTS.md / docs/rules/project_invariants.md
> docs/decisions/*.md
> docs/requirements/*.md
> docs/architecture/*.md
> docs/plans/*.md
> implementation 文档
> 代码
```

如果本文件与更高优先级文档冲突，以更高优先级文档为准。

如果 requirements、architecture、plans 之间出现冲突，必须停止当前实现并向用户说明冲突点，不得自行猜测。

## 3. 编码总原则

开发必须按业务依赖推进：

```text
先底座，后业务；
先事实，后策略；
先只读事实，后真实交易链路；
先订单计划、风控、执行准备，后订单提交；
先主链路闭环，后后台体验；
先可追溯、可测试、可审计，后复杂优化。
```

每次编码只围绕当前阶段和当前任务，不顺手实现后续阶段能力。

阶段之间允许为了测试建立 fake / stub，但 fake / stub 不得被当作正式业务能力，也不得进入真实交易链路。

## 4. 每次编码的固定流程

每次进入一个开发任务时，按以下流程执行：

### 4.1 明确阶段

先确认本次任务属于哪个阶段：

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

不能用“顺便需要”作为跨阶段提前实现的理由。

如果当前任务确实需要跨阶段能力，只能先做明确的接口形状、fake 或 stub，不能提前实现真实业务行为。

### 4.2 阅读当前阶段文档

每次开工前至少阅读：

```text
AGENTS.md
docs/rules/project_invariants.md
docs/plans/implementation_roadmap.md
当前阶段对应的 docs/plans/*_implementation_plan.md
当前阶段 plan 中列出的 requirements
当前阶段 plan 中列出的 architecture
```

不得只读 roadmap 就开始编码。

roadmap 只说明阶段边界；具体执行以对应阶段 plan 为准。

### 4.3 检查现有代码

修改或新增代码前，先检查现有目录结构、已有 app、已有 model、已有 service、已有测试。

禁止：

```text
重复创建相同职责模块；
绕过已有 service；
把业务逻辑写进 task / command / view / serializer；
为了方便直接访问外部服务；
为了测试绕过真实业务边界。
```

### 4.4 小步实现

每个阶段按“数据库事实 → service/domain → 入口 → 测试 → 验收”的顺序推进。

推荐顺序：

```text
先实现模型和迁移；
再实现纯业务 service / domain；
再实现 selector / repository；
再实现 task / command / API 入口；
最后实现测试和验收命令。
```

task、command、view、serializer 只能作为入口，不承载核心业务逻辑。

### 4.5 每阶段必须有测试

每个阶段至少需要覆盖：

```text
正常路径；
失败路径；
幂等路径；
禁止行为；
外部服务 fake；
真实交易关闭默认状态。
```

交易相关阶段还必须覆盖：

```text
真实交易权限关闭时不得进入 OrderPlan；
订单提交绝不重试；
unknown 不推断成功或失败；
ActiveLock 不被编排层、RuntimeGuard 或后台直接释放；
所有 Binance 请求必须经过 BinanceGateway。
```

### 4.6 每次交付必须回报

每次阶段交付或阶段内重要里程碑完成时，回报必须说明：

```text
实现了什么；
新增或修改了哪些文件；
主要调用链路是什么；
是否写库；
是否访问 Redis；
是否访问 Binance；
是否访问 DeepSeek；
是否发送 Hermes；
是否涉及真实交易；
是否写 AlertEvent；
是否创建 NotificationDeliveryAttempt / NotificationSuppression；
是否影响 Feature / Atomic / Domain / MarketRegime / Strategy / DecisionSnapshot；
是否影响 OrderPlan / RiskCheck / Execution / OrderStatusSync / FillSync；
是否影响 PerformanceMetrics / AIReview / OpsConsole；
本阶段明确不负责什么；
运行了哪些测试；
测试结果是什么。
```

不能用“看起来没问题”代替验收。

## 5. 阶段编码顺序

### 阶段 0：项目底座与公共合同

执行文件：

```text
docs/plans/foundation_implementation_plan.md
```

核心目标：

```text
建立 Django 5.2.x 项目底座；
建立 Python 3.12 约束；
建立 MySQL / Redis / Celery / Celery Beat / logging / pytest 基础；
建立 .env.example；
建立基础 AlertEvent / AuditRecord / 公共枚举 / 公共错误结构；
建立基础测试框架。
```

关键注意事项：

```text
Django 默认不会自动读取 .env；
settings 必须显式读取 .env / 环境变量；
数据库配置不得硬编码；
不得把 SQLite 作为正式默认数据库；
真实交易必须默认关闭；
本阶段不得请求 Binance / DeepSeek / Hermes；
本阶段不得实现业务主链路。
```

通过后才能进入阶段 1。

### 阶段 1：行情数据与市场事实

执行文件：

```text
docs/plans/market_data_implementation_plan.md
```

核心目标：

```text
实现 Binance USDS-M BTCUSDT 已收盘 4h / 1d K 线采集；
实现 DataQuality；
实现必要时 DataBackfill；
实现 MarketSnapshot；
形成后续 FeatureLayer 可消费的市场事实。
```

关键注意事项：

```text
数据采集范围固定为 Binance USDS-M BTCUSDT 4h / 1d；
数据采集不受 active market domain 影响；
只能采集已收盘 K 线；
所有时间使用 UTC；
所有 Binance 请求经过 BinanceGateway；
DataBackfill 后必须重新 DataQuality；
MarketSnapshot 只能使用质检通过的数据。
```

本阶段不实现特征、信号、账户、订单或交易。

### 阶段 2：策略分析框架

执行文件：

```text
docs/plans/strategy_analysis_implementation_plan.md
```

核心目标：

```text
实现从 MarketSnapshot 到 DecisionSnapshot 的策略分析框架；
实现 FeatureLayer、AtomicSignal、DomainSignal、MarketRegime、StrategyRouting、StrategySignal、StrategySignalQuality、DecisionSnapshot 的对象链路；
实现 StrategyCalculator / StrategyAnalysisRelease 的注册、版本、冻结和正式发布校验机制。
```

关键注意事项：

```text
本阶段可以先实现插件框架和测试用 fake calculator；
不得为了跑通链路临时发明正式算法；
测试用算法不得被批准为正式策略版本；
正式 StrategyAnalysisRelease 进入主链路前，必须补齐对应算法 requirements 和验证依据；
DecisionSnapshot 只表达目标仓位语义；
DecisionSnapshot 不读取账户、不读取 Binance、不做市场再判断。
```

这里的“插件化”表示算法可替换、可注册、可版本化，不表示算法需求可以省略。

如果当时尚未确定具体算法，本阶段仍可完成框架，但不能交付“可实盘运行的正式策略分析版本”。

### 阶段 3：账户与价格事实

执行文件：

```text
docs/plans/account_price_fact_implementation_plan.md
```

核心目标：

```text
实现 BinanceGateway 底层受限访问能力；
实现 Binance Account Sync；
实现每四小时自动账户边界快照；
实现 PriceSnapshot；
形成 OrderPlan / RiskCheck / ExecutionPreparation / PerformanceMetrics 可读取的账户和价格事实。
```

关键注意事项：

```text
四小时自动编排起始阶段必须稳定创建 trade_preparation 账户快照；
即便后续没有交易，账户快照也必须作为事实存在；
PerformanceMetrics 后续只使用自动边界账户快照；
PriceSnapshot 只在 TARGET_POSITION 分支创建；
PriceSnapshot 使用 BinanceGateway 主动请求 mark price；
Redis 只做短期缓存，MySQL 才是事实落库；
USDS-M 和 COIN-M 的账户、规则、价格、数量计算不得混用。
```

本阶段不实现 OrderPlan、RiskCheck、Execution 或订单提交。

### 阶段 4：订单计划、风控与执行准备

执行文件：

```text
docs/plans/trading_execution_implementation_plan.md
```

核心目标：

```text
把 DecisionSnapshot 的目标仓位转换为 CandidateOrderIntent；
实现真实交易权限检查；
实现 OrderPlanActiveLock；
实现 RiskCheck；
实现 ApprovedOrderIntent；
实现 ExecutionPreparation；
实现 PreparedOrderIntent；
实现提交前实时盘口价格检查。
```

关键注意事项：

```text
真实交易权限检查必须早于 OrderPlan 和 ActiveLock；
权限关闭时不得调用 OrderPlan，不得取得锁；
OrderPlan 不访问 Binance，不下单；
RiskCheck 不缩单，不任意修改订单数量；
ExecutionPreparation 不下单，只做最终检查和价格保护；
实时价格通过 BinanceGateway 获取；
实时价格与本周期 mark price 偏差大于 1% 阻断，小于或等于 1% 允许继续。
```

本阶段仍不提交真实订单。

### 阶段 5：订单提交、状态与成交闭环

执行文件：

```text
docs/plans/order_lifecycle_implementation_plan.md
```

核心目标：

```text
实现 Execution；
实现 OrderSubmissionAttempt；
实现订单提交 Gateway 受限接口；
实现 OrderStatusSync；
实现订单状态查询 Gateway 受限接口；
实现 FillSync；
实现成交查询 Gateway 受限接口；
实现 TradeFill 和 OrderFillSummary；
完成 ActiveLock 安全收尾证据链。
```

关键注意事项：

```text
Execution 是唯一真实订单提交入口；
同一个 PreparedOrderIntent 只能提交一次；
订单提交绝不重试；
Gateway、业务层、Celery、编排层、management command、人工入口都不得重试订单提交；
unknown 不能推断成功或失败；
unknown 必须进入 OrderStatusSync 查询；
OrderStatusSync 只查状态，不重新提交订单；
FillSync 只记录成交事实，不生成账户快照；
旧订单状态和成交查询必须使用订单冻结时的市场域，不随当前 active market domain 切换。
```

本阶段不得实现撤单、改单、自动修复、模拟交易运行模式。

### 阶段 6：编排、任务、通知与巡检

执行文件：

```text
docs/plans/orchestration_runtime_implementation_plan.md
```

核心目标：

```text
实现 PipelineOrchestrator；
实现 OrchestrationBusinessConnector 和各业务 StepAdapter；
实现 OrchestrationRun / OrchestrationStepRun / OrchestrationBusinessObjectLink；
实现 Celery / Celery Beat 主调度入口；
实现 Notifications；
实现 RuntimeGuard 只读巡检。
```

关键注意事项：

```text
编排层只理解 adapter 统一结果；
编排层不解释业务模块内部状态；
业务对象之间正式追溯依赖业务外键；
OrchestrationBusinessObjectLink 只做快捷审计索引；
自动四小时编排开始时先创建账户边界快照；
RuntimeGuard 独立周期运行，只读检查；
RuntimeGuard 不补跑、不修复、不释放锁、不调用 Binance、不调用 DeepSeek、不巡检后台离线任务；
Notifications 负责 AlertEvent 的外部投递或抑制记录。
```

本阶段不实现后台 UI、绩效补算或 AI 复盘。

### 阶段 7：后台、绩效与离线 AI 复盘

执行文件：

```text
docs/plans/operations_review_implementation_plan.md
```

核心目标：

```text
实现 OpsConsole 后端与前端；
实现账户展示；
实现真实交易运行开关管理；
实现编排、订单、成交、告警、巡检、通知查看；
实现 PerformanceMetrics 后台一键补算；
实现 DeepSeekGateway；
实现 AIReview 离线复盘。
```

关键注意事项：

```text
OpsConsole 不直接调用 Gateway；
OpsConsole 不绕过后端 service；
后台不得写 .env；
后台不得管理 API key；
后台不得热切 active market domain；
PerformanceMetrics 只读取已落库事实，不请求 Binance；
PerformanceMetrics 由后台一键补算，不是自动主链路步骤；
AIReview 只做离线复盘，不参与实时交易，不修改策略，不修改交易配置，不下单；
DeepSeekGateway 只能由 AIReview 作为业务调用方。
```

前端技术栈按已确定方向：

```text
Node LTS；
Next.js；
TypeScript；
shadcn/ui；
Recharts；
Django session auth。
```

## 6. 阶段内拆分建议

每个阶段不要一次性“大爆炸”提交。

推荐拆成以下小批次：

```text
批次 A：模型、迁移、枚举和基础约束；
批次 B：service / domain 业务逻辑；
批次 C：selector / repository 查询封装；
批次 D：task / command / API 入口；
批次 E：fake gateway / fake calculator / 测试夹具；
批次 F：单元测试、集成测试和验收命令；
批次 G：文档回填和阶段交付总结。
```

每个小批次都应能被测试或静态检查验证。

## 7. 必须持续检查的横切红线

### 7.1 外部服务

```text
所有 Binance 请求必须经过 BinanceGateway；
所有 DeepSeek 请求必须经过 DeepSeekGateway；
业务模块只写 AlertEvent，不直接发送 Hermes；
Hermes 只通知，不触发交易。
```

### 7.2 真实交易

```text
真实交易默认关闭；
如果文档没有明确允许真实交易，默认不得真实交易；
真实交易权限检查只在进入 OrderPlan 前执行；
权限关闭时不得调用 OrderPlan，不得取得 ActiveLock；
订单提交绝不重试。
```

### 7.3 策略分析

```text
FeatureLayer 不生成交易信号；
AtomicSignal 不直接下单；
DomainSignal 不生成订单动作；
MarketRegime 不生成订单动作；
StrategyRouting 不执行策略算法；
StrategySignal 不等于交易决策；
DecisionSnapshot 不生成订单，只表达目标仓位语义；
OrderPlan 是唯一把目标仓位转换为候选订单意图的模块。
```

### 7.4 数据存储

```text
MySQL 是核心事实主存储；
Redis 只做缓存、锁、短期幂等、短期任务状态或短期价格缓存；
Redis 不得成为核心业务数据唯一存储；
交易、风控、订单、成交、仓位、复盘事实必须可追溯。
```

### 7.5 RuntimeGuard

```text
RuntimeGuard 只巡检自动编排主链路、订单链路卡住状态、ActiveLock 风险状态和通知投递状态；
RuntimeGuard 不修复、不补跑、不释放锁、不修改业务对象；
RuntimeGuard 不巡检 PerformanceMetrics、AIReview 或后台人工离线任务。
```

## 8. 进入阶段 2 前后的算法处理

阶段 2 分成两个层次理解：

```text
策略分析框架；
正式策略算法。
```

策略分析框架可以按阶段 2 开工实现。

正式策略算法进入主链路前，必须具备：

```text
对应算法 requirements；
输入事实说明；
输出结果说明；
阈值、权重或判断规则说明；
版本号；
测试用例；
验证依据；
StrategyAnalysisRelease 依赖闭包。
```

如果这些还没准备好，阶段 2 只能交付框架、注册、版本、发布校验和测试用 fake calculator，不能交付正式可实盘使用的策略分析版本。

这不是否定插件化，而是保证插件里的真实算法不由代码临时猜出来。

## 9. 编码开始推荐顺序

当前应从阶段 0 开始：

```text
docs/plans/foundation_implementation_plan.md
```

阶段 0 完成后，再按顺序进入：

```text
docs/plans/market_data_implementation_plan.md
docs/plans/strategy_analysis_implementation_plan.md
docs/plans/account_price_fact_implementation_plan.md
docs/plans/trading_execution_implementation_plan.md
docs/plans/order_lifecycle_implementation_plan.md
docs/plans/orchestration_runtime_implementation_plan.md
docs/plans/operations_review_implementation_plan.md
```

如果中途发现阶段计划遗漏真实业务模块，必须先补 plan，再编码。

不得在实现过程中通过“临时写一点”绕过计划文件。

## 10. 阶段验收总门槛

每个阶段结束时，至少满足：

```text
迁移可生成并可运行；
测试可运行；
关键 service 有测试；
禁止行为有测试；
fake 外部服务覆盖真实外部调用；
真实交易默认关闭；
没有真实 Binance / DeepSeek / Hermes 调用；
没有绕过 Gateway；
没有把业务逻辑堆进 task / command / view / serializer；
没有提前实现后续阶段真实能力；
交付回报说明完整。
```

交易相关阶段还必须额外确认：

```text
是否产生 CandidateOrderIntent；
是否产生 ApprovedOrderIntent；
是否产生 PreparedOrderIntent；
是否提交 OrderSubmissionAttempt；
是否写入 TradeFill；
是否影响 BinancePositionSnapshot / 仓位事实；
是否写 AlertEvent；
是否创建 NotificationDeliveryAttempt 或 NotificationSuppression；
是否发送 Hermes；
是否可能触发真实交易。
```

## 11. 什么时候停止并询问用户

出现以下情况必须停止并询问用户：

```text
文档冲突；
交易行为不确定；
真实交易风险不确定；
资金风险不确定；
字段或对象边界影响多个模块；
算法规则缺失但要进入正式链路；
需要新增 requirements 未定义的能力；
需要突破 AGENTS.md 或 project_invariants.md；
需要删除或重写已有核心文件；
需要访问真实外部服务；
需要提交真实订单。
```

不得为了继续推进而自行猜测这些问题。

## 12. 当前下一步

下一步编码入口为：

```text
docs/plans/foundation_implementation_plan.md
```

开始阶段 0 前，应先读取：

```text
AGENTS.md
docs/rules/project_invariants.md
docs/requirements/project_scope.md
docs/requirements/system_capabilities.md
docs/requirements/core_contracts.md
docs/requirements/project_foundation.md
docs/requirements/notifications.md
docs/architecture/system_architecture.md
docs/architecture/module_boundary_architecture.md
docs/architecture/runtime_task_architecture.md
docs/architecture/testing_and_safety_architecture.md
docs/plans/foundation_implementation_plan.md
```

阶段 0 的第一批次建议为：

```text
创建 Django 项目结构；
创建 pyproject.toml；
配置 Python / Django / MySQL / Redis / Celery 依赖；
实现 settings 显式读取 .env；
创建 .env.example；
建立基础测试框架；
确认真实交易默认关闭。
```

阶段 0 第一批次不创建业务主链路模型，不请求外部服务，不实现交易相关业务。
