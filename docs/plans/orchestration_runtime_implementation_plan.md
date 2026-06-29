# 编排、运行任务、通知与巡检实施计划

## 1. 文档目的

本文档用于指导阶段 6 的代码实施与验收。

本阶段把阶段 0 至阶段 5 已完成的业务模块接入统一运行层，实现：

```text
自动四小时主编排；
业务模块与编排层之间的适配；
编排运行、步骤运行和业务对象索引；
同步步骤顺序推进；
交易关键步骤异步交接；
WAIT 状态保存和幂等恢复；
AlertEvent 的可靠路由和外部通知投递；
独立、只读的 RuntimeGuard 运行巡检。
```

本文档不重新定义行情、策略、账户、价格、订单计划、风控、执行、订单状态或成交规则。

业务规则仍由各自 requirements 和业务 service 拥有。编排层只按已发布步骤定义调用业务模块，并消费 adapter 返回的统一结果。

---

## 2. 阶段定位

本阶段对应 [implementation_roadmap.md](implementation_roadmap.md) 的阶段 6：

```text
编排、任务、通知与巡检。
```

完成后，系统应形成以下运行结构：

```text
Celery Beat
→ orchestration driver task
→ PipelineOrchestrator
→ OrchestrationBusinessConnector
→ BusinessStepAdapter
→ 已实现的业务 service
→ OrchestrationStepResult
→ PipelineOrchestrator 按 flow_action 推进、等待或结束。
```

交易关键步骤采用独立任务资源：

```text
PipelineOrchestrator
→ Execution 交易关键工作项
→ 交易关键 worker
→ 主交易 OrchestrationRun 的订单提交步骤完成；

独立订单生命周期同步管线
→ OrderStatusSync / FillSync 交易关键工作项
→ 交易关键 worker
→ 订单生命周期同步 run 的 WAIT 恢复入口。
```

横切运行能力：

```text
业务模块 / 编排层
→ AlertEvent
→ NotificationDeliveryAttempt 或 NotificationSuppression
→ Notifications worker
→ Hermes；

Celery Beat
→ RuntimeGuard
→ 只读检查 MySQL 事实
→ RuntimeGuardRun / RuntimeGuardIssue / AlertEvent。
```

本阶段会驱动真实交易链路，但 PipelineOrchestrator、RuntimeGuard 和 Notifications 均不是订单提交入口。

Execution 仍是唯一允许提交真实订单的业务模块。

---

## 3. 前置条件

开始本阶段编码前，必须确认阶段 0 至阶段 5 已通过各自验收，至少具备：

```text
Django、MySQL、Redis、Celery 与 Celery Beat 基础配置；
统一 UTC、日志、trace_id 与配置读取能力；
DataCollection 到 MarketSnapshot 的业务 service；
FeatureLayer 到 DecisionSnapshot 的业务 service；
StrategyAnalysisRelease 解析、校验与冻结所需能力；
BinanceGateway、Binance Account Sync 与 PriceSnapshot；
OrderPlan、RiskCheck 与 ExecutionPreparation；
Execution、OrderStatusSync 与 FillSync；
各业务模块的幂等键、真实业务外键和结构化返回结果；
各业务模块应写的 AlertEvent 合同。
```

如果某个业务模块仍只有 task、command 或 view，没有可由 adapter 调用的 application service，必须先补齐该模块的 service 边界，不得把缺失的业务逻辑写进 adapter。

如果某个业务模块无法返回结构化状态、主对象引用或稳定幂等结果，不得通过 truthy 判断临时接入正式编排。

---

## 4. 文档依据

### 4.1 主要需求依据

```text
docs/requirements/pipeline_orchestrator.md
docs/requirements/runtime_guard.md
docs/requirements/notifications.md
docs/requirements/project_foundation.md
```

### 4.2 业务模块依据

编写每个 adapter 时，必须同时阅读其对应需求文件：

```text
docs/requirements/binance_account_sync.md
docs/requirements/data_collection.md
docs/requirements/data_quality.md
docs/requirements/data_backfill.md
docs/requirements/market_snapshot.md
docs/requirements/feature_layer.md
docs/requirements/atomic_signals.md
docs/requirements/domain_signals.md
docs/requirements/market_regime.md
docs/requirements/strategy_routing.md
docs/requirements/strategy_signals.md
docs/requirements/strategy_signal_quality.md
docs/requirements/decision_snapshot.md
docs/requirements/price_snapshot.md
docs/requirements/order_plan.md
docs/requirements/risk_check.md
docs/requirements/execution_preparation.md
docs/requirements/order_submission.md
docs/requirements/order_status_sync.md
docs/requirements/fill_sync.md
```

### 4.3 公共约束依据

```text
AGENTS.md
docs/rules/project_invariants.md
docs/requirements/project_scope.md
docs/requirements/system_capabilities.md
docs/requirements/core_contracts.md
```

### 4.4 架构依据

```text
docs/architecture/system_architecture.md
docs/architecture/module_boundary_architecture.md
docs/architecture/data_flow_architecture.md
docs/architecture/runtime_task_architecture.md
docs/architecture/testing_and_safety_architecture.md
```

### 4.5 前置实施计划

```text
docs/plans/foundation_implementation_plan.md
docs/plans/market_data_implementation_plan.md
docs/plans/strategy_analysis_implementation_plan.md
docs/plans/account_price_fact_implementation_plan.md
docs/plans/trading_execution_implementation_plan.md
docs/plans/order_lifecycle_implementation_plan.md
```

发生冲突时，按项目文档优先级处理，不得由本实施计划覆盖 requirements 或 project_invariants。

---

## 5. 本阶段核心口径

### 5.1 三层职责必须分离

```text
业务层：
  拥有业务规则、业务状态、业务对象、幂等和真实业务外键；

OrchestrationBusinessConnector / BusinessStepAdapter：
  理解单个业务模块的入口和原始返回值；
  构造明确业务输入；
  显式映射统一状态与流程动作；
  收集业务对象引用；

PipelineOrchestrator：
  创建和推进运行记录；
  只消费统一流程动作；
  不解释业务模块内部状态。
```

PipelineOrchestrator 中不得出现针对 `ALLOW`、`PREPARED`、`synced_empty`、`no_order_required`、`FILLED` 等业务状态的大型分支判断。

### 5.2 编排索引不替代业务外键

业务模块继续通过真实业务外键消费直接上游。

```text
RiskCheck 通过订单计划和候选订单意图读取审核对象；
ExecutionPreparation 通过审批通过订单意图读取输入；
Execution 通过 PreparedOrderIntent 读取输入；
OrderStatusSync 通过 OrderSubmissionAttempt 读取订单；
FillSync 通过提交尝试和终态查询记录读取输入。
```

`OrchestrationBusinessObjectLink` 只用于快速查询一轮运行涉及哪些业务对象，不得成为业务 service 的查询入口。

### 5.3 MySQL 是运行事实来源

```text
OrchestrationRun；
OrchestrationStepRun；
OrchestrationBusinessObjectLink；
RuntimeGuardRun；
RuntimeGuardIssue；
AlertEvent；
NotificationDeliveryAttempt；
NotificationSuppression。
```

以上对象的正式状态必须保存在 MySQL。

Redis、Celery broker、Celery result backend 和进程内变量不得成为运行是否完成、订单是否提交、通知是否待投递或问题是否存在的唯一依据。

### 5.4 任务可能重复投递

所有 task 必须按消息可能重复、延迟或丢失设计。

正确性依赖：

```text
数据库唯一约束；
短事务认领；
业务幂等；
稳定 business_request_key；
稳定 resume_token；
明确 poll_sequence；
已有业务事实检查。
```

Celery task id、worker 名称或任务重试次数不得作为业务幂等键。

### 5.5 WAIT 必须释放 worker

业务步骤需要等待后续事实时：

```text
保存 Run 和 StepRun 的 waiting 状态；
保存恢复令牌、等待对象和下一检查时间；
提交数据库状态；
结束当前 task；
由定向任务恢复对应 run。
```

不得用 `sleep`、长数据库事务或持续占用 worker 等待订单状态。

### 5.6 订单提交绝不重试

任何编排触发、Celery redelivery、WAIT 恢复、进程重启、人工诊断或 ObjectLink 补写都不得再次提交同一 `PreparedOrderIntent`。

恢复订单提交步骤时，只能读取已经存在的 `OrderSubmissionAttempt`。无法确认是否提交时保持 `unknown`，并进入订单状态查询。

### 5.7 RuntimeGuard 只读巡检

RuntimeGuard 只负责发现问题并保存巡检事实。

它不得：

```text
补跑主链路；
恢复编排；
重新执行步骤；
消费恢复令牌；
修改业务对象；
释放 ActiveLock；
访问 Binance；
调用外部大模型；
直接发送 Hermes；
巡检 ReviewDataset。
```

### 5.8 通知与业务隔离

业务模块和编排层只写 `AlertEvent`，不直接发送 Hermes。

```text
通知失败不回滚业务事实；
通知成功不触发业务动作；
通知重试只重试通知投递；
通知 unknown 不自动重发；
外部通知关闭时仍保存 AlertEvent。
```

---

## 6. 本阶段实现范围

### 6.1 PipelineOrchestrator

实现一轮运行的创建、认领、推进、等待、恢复和终结。

至少提供以下 application service 能力：

```text
创建或取得自动周期唯一 run；
创建 manual_diagnostic run；
冻结 Registry 与 StrategyAnalysisRelease；
驱动下一合法步骤；
保存步骤统一结果和对象引用；
处理 CONTINUE / COMPLETE / WAIT / STOP / FAIL；
恢复 waiting 步骤；
对安全的非提交步骤执行受控恢复；
查询一轮完整运行详情；
从业务对象反查相关运行。
```

### 6.2 OrchestrationStepRegistry

实现代码注册、版本化和启动校验。

Registry 必须：

```text
固定正式步骤顺序；
校验步骤编码唯一；
校验顺序不冲突；
校验依赖无环；
校验 adapter 存在且版本匹配；
记录 execution_mode、条件步骤和超时策略；
生成稳定 registry_hash；
版本变化时生成新 registry_version；
禁止运行时后台热修改正式步骤。
```

### 6.3 OrchestrationBusinessConnector

Connector 负责：

```text
根据冻结 Registry 找到 adapter；
从已经保存的对象引用构造明确输入；
把冻结的 StrategyAnalysisRelease 身份传给策略分析步骤；
调用 adapter；
校验 OrchestrationStepResult 合同；
拒绝未映射或缺失状态；
把统一结果交给 PipelineOrchestrator。
```

Connector 不直接调用 Binance、DeepSeek、Hermes，也不拥有任何业务算法。

### 6.4 BusinessStepAdapter

正式 Registry 至少实现以下 adapter：

```text
BinanceAccountSyncStepAdapter
DataCollectionStepAdapter
DataQualityStepAdapter
DataBackfillStepAdapter
MarketSnapshotStepAdapter
FeatureLayerStepAdapter
AtomicSignalStepAdapter
DomainSignalStepAdapter
MarketRegimeStepAdapter
StrategyRoutingStepAdapter
StrategySignalStepAdapter
StrategySignalQualityStepAdapter
DecisionSnapshotStepAdapter
PriceSnapshotStepAdapter
OrderPlanStepAdapter
RiskCheckStepAdapter
ExecutionPreparationStepAdapter
OrderSubmissionStepAdapter
OrderStatusSyncStepAdapter
FillSyncStepAdapter
```

每个 adapter 必须：

```text
只调用一个对应业务 application service；
使用显式业务对象 ID 作为输入；
传递不透明 business_request_key；
传递原 trace_id；
对原始状态执行完整白名单映射；
未知状态 fail-closed；
返回 primary_object_ref 和必要 object refs；
对大批量子对象采用明确引用策略；
不修改业务对象；
不复制业务算法。
```

### 6.5 编排运行对象

实现：

```text
OrchestrationRun；
OrchestrationRunConfigSnapshot；
OrchestrationStepRun；
OrchestrationBusinessObjectLink。
```

模型字段、状态、唯一约束和索引必须覆盖 `pipeline_orchestrator.md` 的完整合同。

### 6.6 Celery / Celery Beat 运行入口

实现：

```text
自动周期触发 task；
run driver task；
waiting run 恢复 task；
Execution 交易关键工作项；
OrderStatusSync 定向轮询工作项；
FillSync 交易关键工作项；
RuntimeGuard 定时 task；
Notifications pending 扫描 task；
NotificationDeliveryAttempt 投递 task。
```

task 只解析小型运行上下文、调用 application service 并返回结构化摘要。

### 6.7 Notifications

实现：

```text
AlertEvent 写入服务；
事件幂等、字段校验和脱敏检查；
NotificationRoute 与 NotificationTemplate 版本读取；
同事务创建首个 DeliveryAttempt 或 Suppression；
事务提交后 Celery 唤醒；
MySQL pending 扫描；
投递资格抢占；
Hermes 投递；
有限通知重试；
冷却、聚合和限频；
事件与投递查询。
```

### 6.8 RuntimeGuard

实现独立的十分钟巡检：

```text
自动编排漏跑；
Run / StepRun 长时间 running 或 waiting；
成功步骤产物绑定缺失；
MarketSnapshot 事实异常；
PriceSnapshot 事实异常；
提交前订单链路断裂；
ActiveLock 长时间阻断；
订单提交 submitting 或 unknown 长期未解决；
订单状态长期未确认；
FillSync 长期未解决；
自动账户边界同步异常；
通知投递异常。
```

每项检查独立执行并形成结构化结果。单项失败不得丢弃其他已保存问题。

---

## 7. 建议代码模块

建议新增或完善以下 Django app：

```text
apps/orchestration/
apps/runtime_guard/
apps/alerts/（沿用底座阶段已建立的 AlertEvent app，并扩展为完整 Notifications 能力）
```

底座阶段已经建立 `AlertEvent` 基础模型与写入 service，本阶段必须在同一模型和同一 app 边界上扩展路由、投递与抑制能力。

不得另建一份 AlertEvent，不得同时保留 `alerts.AlertEvent` 与 `notifications.AlertEvent` 两套事件事实。

### 7.1 orchestration

建议职责划分：

```text
models.py
  只定义编排运行、步骤运行、配置快照和对象关联；

registry/
  保存版本化步骤定义、校验器和 hash 生成；

adapters/
  每个业务模块一个 adapter；

services/
  PipelineOrchestrator、Connector、运行推进、WAIT 恢复和查询服务；

selectors/
  运行详情和对象反查；

tasks.py
  自动触发、driver、交易关键交接和恢复的薄任务入口；

management/commands/
  只提供明确诊断或受控恢复入口；

tests/
  模型、Registry、adapter、编排、任务和故障注入测试。
```

### 7.2 runtime_guard

建议职责划分：

```text
models.py
  RuntimeGuardRun 与 RuntimeGuardIssue；

checks/
  按问题类型拆分只读检查器；

services/
  运行巡检、问题去重、提醒间隔和状态管理；

selectors/
  从 MySQL 读取被巡检事实；

tasks.py
  十分钟调度薄入口；

management/commands/
  dry-run / confirm-write 巡检入口；

tests/
  各检查器、并发去重和禁止副作用测试。
```

### 7.3 alerts / Notifications

建议职责划分：

```text
models.py
  扩展既有 AlertEvent，并新增 Route、Template、DeliveryAttempt、Suppression；

services/
  事件写入、路由、投递、重试和抑制；

channels/
  Hermes 单向外部通道适配；

selectors/
  pending 扫描和后台查询；

tasks.py
  pending 扫描和投递薄入口；

management/commands/
  队列查看、健康检查和受控通知重试；

tests/
  可靠交接、认领、投递、重试、抑制和脱敏测试。
```

不得创建一个同时承担编排、巡检和通知的通用 runtime service。

---

## 8. 数据库迁移范围

### 8.1 编排模型

迁移至少建立：

```text
OrchestrationRun；
OrchestrationRunConfigSnapshot；
OrchestrationStepRun；
OrchestrationBusinessObjectLink。
```

必须落实：

```text
同一自动计划周期唯一；
同一 run、step 和 execution_sequence 唯一；
business_request_key 唯一；
非空 resume_token 唯一；
同一对象引用角色唯一；
按 run、step、object_type 与 object_id 查询的索引；
所有业务时间使用 UTC；
结构化摘要有明确大小限制。
```

### 8.2 RuntimeGuard 模型

迁移至少建立：

```text
RuntimeGuardRun；
RuntimeGuardIssue。
```

必须落实：

```text
同一计划巡检 run_key 唯一；
同一未关闭问题 issue_key 唯一或等价并发保护；
按 issue_type、severity、status、关联对象和最近发现时间索引；
证据字段结构化、脱敏且大小受控；
问题状态变更可记录操作人与原因。
```

### 8.3 Notifications 模型

本阶段必须沿用底座阶段已经建立的 `AlertEvent` 模型和数据库表，通过 migration 补齐 Notifications 正式合同需要但基础模型尚未具备的字段、约束和索引。

不得删除后重建 AlertEvent 表，不得复制历史事件，不得修改已经存在的 `event_key` 身份。

迁移至少扩展或建立：

```text
AlertEvent（扩展既有模型）；
NotificationRoute；
NotificationTemplate；
NotificationDeliveryAttempt；
NotificationSuppression。
```

必须落实：

```text
event_key 唯一；
(route_code, route_version) 唯一；
(template_code, template_version) 唯一；
delivery_attempt_key 唯一；
同一事件、路由、通道和 attempt_sequence 唯一；
pending、next_retry_at_utc、claimed_at_utc 和状态查询索引；
route_hash 与 template_hash 不可被历史配置变更改写；
Suppression 与 AlertEvent 明确关联。
```

### 8.4 迁移边界

本阶段不得：

```text
给主交易业务对象统一增加 orchestration_run_id；
删除既有真实业务外键；
把业务状态复制进 ObjectLink；
在 AlertEvent 上直接增加 orchestration_run_id 或 step_run_id；
把 Redis 结构当成 migration 的替代；
为未定义的人工补查或补同步能力建表。
```

---

## 9. 配置范围

所有环境配置必须进入 `.env.example` 并附中文注释，由 Django settings 统一读取。

### 9.1 编排配置

```text
PIPELINE_ORCHESTRATOR_ENABLED
PIPELINE_CODE
ORCHESTRATION_STALE_RUNNING_SECONDS
ORCHESTRATION_STALE_WAITING_SECONDS
ORCHESTRATION_MAX_BACKFILL_ROUNDS
```

步骤顺序、业务状态映射和终态语义不得通过 `.env` 热修改。

### 9.2 RuntimeGuard 配置

```text
RUNTIME_GUARD_ENABLED
RUNTIME_GUARD_INTERVAL_SECONDS
RUNTIME_GUARD_ORCHESTRATION_MISSING_GRACE_SECONDS
RUNTIME_GUARD_ORCHESTRATION_STALE_SECONDS
RUNTIME_GUARD_STEP_STALE_SECONDS
RUNTIME_GUARD_OUTPUT_MISSING_GRACE_SECONDS
RUNTIME_GUARD_ORDER_CHAIN_PRE_SUBMISSION_STALE_SECONDS
RUNTIME_GUARD_ACTIVE_LOCK_STALE_SECONDS
RUNTIME_GUARD_ORDER_SUBMISSION_STALE_SECONDS
RUNTIME_GUARD_ORDER_STATUS_UNRESOLVED_SECONDS
RUNTIME_GUARD_FILL_SYNC_UNRESOLVED_SECONDS
RUNTIME_GUARD_ACCOUNT_SYNC_STALE_SECONDS
RUNTIME_GUARD_REPEAT_ALERT_INTERVAL_SECONDS
```

默认值以 `runtime_guard.md` 为准，不在代码中重复硬编码第二套生产阈值。

### 9.3 Notifications 配置

```text
NOTIFICATIONS_DELIVERY_ENABLED
NOTIFICATIONS_WORKER_ENABLED
NOTIFICATIONS_DEFAULT_CHANNEL
NOTIFICATIONS_MAX_ATTEMPTS
NOTIFICATIONS_RETRY_BACKOFF_SECONDS
NOTIFICATIONS_DEFAULT_COOLDOWN_SECONDS
NOTIFICATIONS_MAX_EVENTS_PER_MINUTE
NOTIFICATIONS_WORKER_STALE_SECONDS
HERMES_WEBHOOK_URL
HERMES_WEBHOOK_SECRET
HERMES_TIMEOUT_SECONDS
HERMES_MAX_MESSAGE_LENGTH
```

规则：

```text
没有关闭 AlertEvent 正式事实写入的总开关；
关闭外部投递时仍保存 AlertEvent 和 Suppression；
只关闭 worker 时仍保存 pending DeliveryAttempt；
Webhook secret 不入库、不进日志、不返回前端；
Hermes 配置缺失时 fail-closed，不绕过路由直接发送。
```

### 9.4 Celery 任务路由

Django settings 必须区分以下逻辑任务组：

```text
编排任务组；
交易关键任务组；
运维任务组。
```

物理 queue 名称通过 settings 统一配置，不散落在 task 或业务 service 中。

本阶段不把 ReviewDataset 接入交易关键任务组；其离线任务路由在下一阶段计划中实现。

---

## 10. 正式 Registry 与输入传递

### 10.1 正式步骤顺序

第一版正式 Registry 必须按以下业务顺序发布：

```text
Binance Account Sync（trade_preparation，起始步骤）
→ DataCollection
→ DataQuality
→ 必要时 DataBackfill
→ DataQuality 重新验证
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
→ RiskCheck
→ ExecutionPreparation
→ Execution
→ 订单提交事实完成。
```

订单提交后的 OrderStatusSync / FillSync 通过独立订单生命周期同步管线推进，不作为主交易编排尾部继续执行。

`NO_TARGET_CHANGE`、`NO_TRADE`、`no_strategy` 和 `no_order_required` 必须通过 adapter 显式映射为正常无动作结束，不得当作系统失败。

### 10.2 条件步骤和有限循环

只有以下受控循环允许进入第一版 Registry：

```text
DataQuality 请求回补
→ DataBackfill
→ DataQuality 重新验证。
```

达到最大回补轮次后必须停止。

不得建立订单计划重算、风控重试、价格刷新重做、订单重新提交或成交失败重下单循环。

### 10.3 StrategyAnalysisRelease 冻结

创建 run 时必须解析并冻结当前唯一已批准、已启用的版本包。

```text
冻结成功：
  FeatureLayer 到 DecisionSnapshot 全部使用相同 release ID 与 hash；

冻结失败：
  仍允许完成账户边界、行情、质量、回补和 MarketSnapshot；
  在 FeatureLayer 前受控停止；
  不进入策略、决策或订单链路。
```

运行中版本包发生切换，不得改变本轮已冻结身份。

### 10.4 明确业务输入

Connector 必须根据 Registry 依赖与已保存对象引用构造明确输入。

业务 service 不接收 `orchestration_run_id` 后自行查找输入，也不得解析 `business_request_key` 推断编排语义。

### 10.5 对象引用策略

每个 adapter 在实现时必须声明：

```text
primary_object_ref；
必须记录的 output / input / related / audit refs；
大量子对象采用 root_only、all_primary 或 explicit_refs 中哪一种；
引用策略对应的 adapter_version；
引用策略测试。
```

FeatureValue、AtomicSignalValue、TradeFill、RiskRuleResult 等可通过根对象业务外键展开的大量子记录，不机械复制到 ObjectLink。

---

## 11. 实施顺序

### 11.1 建立编排模型与约束

先实现编排四类模型、状态枚举、唯一约束和索引。

验收重点：

```text
同一自动周期并发创建只有一条 run；
同一步骤执行序号不会重复；
同一业务对象引用幂等；
业务表不新增编排外键；
Run 与 StepRun 状态语义不混淆。
```

### 11.2 实现 Registry 与启动校验

实现第一版正式步骤定义、版本和 hash。

启动或测试时必须验证：

```text
步骤顺序；
依赖无环；
adapter 完整；
adapter 版本；
result mapping 版本；
条件步骤；
执行模式。
```

Registry 损坏、依赖成环或 adapter 缺失时，必须在启动正式 run 前失败。

### 11.3 实现统一结果合同

实现不可变的 `OrchestrationStepResult` 及其校验。

只允许：

```text
normalized_status：SUCCEEDED / NO_ACTION / BLOCKED / UNKNOWN / FAILED / SKIPPED；
flow_action：CONTINUE / COMPLETE / WAIT / STOP / FAIL。
```

禁止把二者合并成一个布尔值。

### 11.4 分组实现 adapter

按业务链路顺序分组实现：

```text
第一组：账户、行情、质量、回补和市场快照；
第二组：特征、原子、领域、市场环境、策略路由、策略、质量和决策；
第三组：价格、真实交易权限、订单计划、风控和执行准备；
第四组：订单提交、状态同步和成交同步。
```

每完成一组必须先通过 adapter 合同测试，再接入 PipelineOrchestrator。

### 11.5 实现同步 driver

driver 的标准步骤：

```text
创建或认领 run；
读取冻结 Registry 的下一合法步骤；
创建或认领 StepRun；
提交短事务；
调用 Connector；
业务 service 自行完成业务事务；
锁定原 StepRun；
幂等写入 ObjectLink；
保存统一结果；
推进或结束 Run；
提交短事务。
```

不得在调用外部服务期间持有编排数据库事务。

### 11.6 实现自动 UTC 调度

Celery Beat 按以下 UTC 计划触发：

```text
daily_boundary：00:05 UTC；
four_hour_boundary：04:05、08:05、12:05、16:05、20:05 UTC。
```

00:05 的日线周期必须由业务质量结果确认最新已收盘 4h 与 1d 数据均可消费。

Beat 只投递计划身份和技术上下文，不传递完整业务对象。

### 11.7 实现交易关键任务交接

进入 Execution 时：

```text
主交易 driver 保存明确 StepRun、业务对象引用和恢复信息；
主交易 run 进入 waiting；
投递交易关键工作项；
driver task 结束；
交易关键 worker 调用 Execution adapter / service；
结果落库后恢复主交易 run；
accepted 或 unknown 时主交易 run 完成，并登记或触发独立订单生命周期同步 run。
```

进入 OrderStatusSync 或 FillSync 时：

```text
订单生命周期同步 driver 保存明确 StepRun、业务对象引用和恢复信息；
订单生命周期同步 run 进入 waiting；
投递交易关键工作项；
driver task 结束；
交易关键 worker 调用对应 adapter / service；
结果落库后恢复订单生命周期同步 run。
```

Execution 任务重复投递时，必须先检查已有 `OrderSubmissionAttempt`。已有记录或无法确认是否提交时，不得再次调用提交 Gateway。

### 11.8 实现 OrderStatusSync 定向轮询

```text
accepted 或 unknown 提交结果
→ 两秒后查询明确 attempt
→ 每次任务只执行一个逻辑轮次
→ 仍未终结且在 30 秒窗口内，登记下一轮
→ 明确终态，恢复订单生命周期同步 run 并进入 FillSync
→ 30 秒仍未解决，订单生命周期同步 run 结束为 unknown，ActiveLock 保持。
```

不得使用每两秒全表扫描；不得在 worker 内 sleep；不得补发超过窗口的遗漏轮次。

### 11.9 实现崩溃恢复

至少覆盖：

```text
业务对象已保存但 ObjectLink 未保存；
StepRun 停留 running；
run 停留 waiting；
订单提交前后进程中断；
Celery 消息重复；
通知唤醒消息丢失。
```

安全恢复以 MySQL 事实为准。

无法判断动作是否完成时，保留 `unknown` 或 `stale_interrupted`，不得通过重做高风险动作试探。

### 11.10 实现 Notifications 可靠交接

先实现 AlertEvent 写入与同事务路由：

```text
校验并保存 AlertEvent；
解析已发布 Route 与 Template；
为每个匹配路由创建首个 pending DeliveryAttempt；
或创建明确 NotificationSuppression；
提交事务；
再发送 Celery 唤醒消息。
```

如果唤醒消息丢失，pending 扫描必须能够继续发现并投递。

### 11.11 实现 Notifications 投递与有限重试

worker 必须先在短事务中认领 pending attempt，提交后再调用 Hermes，最后在新事务中保存结果。

```text
sent：通道确认接收；
failed：本次失败，只有 retryable 才能建立下一次尝试；
unknown：可能已经发送，不自动重试；
abandoned：明确不可重试或达到上限。
```

每次允许的重试创建新的 DeliveryAttempt，不覆盖旧尝试。

### 11.12 实现 RuntimeGuard

按 `issue_type` 拆分只读检查器，再由统一 service 顺序执行。

流程：

```text
创建或取得本计划 RuntimeGuardRun；
执行启用的独立检查器；
创建或更新 RuntimeGuardIssue；
首次发现或达到提醒间隔时写 AlertEvent；
汇总检查数量、问题数量和错误数量；
保存 succeeded / partial_failed / failed。
```

不得在检查器中调用被巡检业务 service 来“确认一下”或“补一下”。

### 11.13 建立查询与诊断入口

实现：

```text
查询完整 OrchestrationRun；
从业务对象反查 run；
查询 RuntimeGuardRun / Issue；
确认、解决或忽略 Issue；
查询 AlertEvent、DeliveryAttempt 与 Suppression；
查看通知 pending 状态；
只读通知健康检查。
```

这些入口为下一阶段 OpsConsole 提供 application service，不在本阶段实现复杂 UI。

---

## 12. 自动周期与并发规则

### 12.1 同一计划周期

同一自动周期重复触发：

```text
已有 created / running / waiting：返回并安全继续已有 run；
已有终态：返回已有结果，不自动重跑；
已有 unknown / failed / stale_interrupted：不新建第二条交易链。
```

### 12.2 不同计划周期

不同计划周期可以拥有独立 run，并完成：

```text
账户边界同步；
行情与质量；
市场快照；
策略分析；
DecisionSnapshot；
必要时 PriceSnapshot 和真实交易权限检查。
```

如果旧订单链仍持有 ActiveLock，新周期只在尝试进入 OrderPlan 时被锁服务阻断。

ActiveLock 只保护冲突订单链，不是全系统编排锁。

### 12.3 数据库认领

至少保证：

```text
同一 run 不被两个 driver 推进同一步；
同一 execution_sequence 不重复执行；
同一 resume_token 只消费一次；
同一 poll_sequence 只查询一次；
同一 DeliveryAttempt 同时只被一个 worker 投递；
同一 RuntimeGuard run 和 issue 不重复创建。
```

Redis 锁只能降低竞争，数据库约束必须保证最终正确性。

---

## 13. 真实交易权限与订单安全边界

### 13.1 权限检查位置

`OrderPlanStepAdapter` 在调用 OrderPlan 前检查一次：

```text
.env / Django settings 部署级硬权限
AND
MySQL 后台真实交易运行开关。
```

权限关闭时：

```text
不调用 OrderPlan；
不生成 CandidateOrderIntent；
不取得 ActiveLock；
本轮正常无动作完成。
```

权限不可读取或市场上下文不一致时 fail-closed。

### 13.2 权限通过后的本轮

检查通过后，本轮后续步骤使用已经冻结的检查结果，不重新读取 MySQL 运行开关。

后台关闭新交易只影响下一轮进入 OrderPlan 的检查，不中止已经存在的订单状态查询和成交同步。

### 13.3 编排不得拥有交易动作

PipelineOrchestrator、Connector、RuntimeGuard 和 Notifications 均不得：

```text
直接调用 Binance；
直接提交、撤销或修改订单；
修改 ActiveLock；
修改订单或成交事实；
根据告警触发交易；
绕过业务 service。
```

---

## 14. AlertEvent 与通知边界

### 14.1 事件归属

业务模块写业务事件，编排层写编排事件，RuntimeGuard 写巡检事件。

三类事件不得互相替代。

`AlertEvent` 是事件事实，不等于业务对象状态，也不等于已经外部投递。

### 14.2 编排事件

至少覆盖：

```text
run started / completed / completed_no_action / blocked / unknown / failed / stale_interrupted；
step started / completed / waiting / blocked / unknown / failed；
duplicate trigger；
unmapped business result；
object link failed。
```

### 14.3 巡检事件

首次发现问题写 RuntimeGuard AlertEvent；重复发现只按正式提醒间隔写事件，不得每十分钟刷屏。

事件内容必须明确它是巡检发现，不是原业务模块的实时结论。

### 14.4 通知自身故障

单次 Hermes 投递失败只更新 DeliveryAttempt，不为每次失败递归生成新的 AlertEvent。

只允许在首次失败、达到连续失败阈值或通道长期不可用等正式节点生成通知系统内部事件。

通知系统自身异常不得通过同一故障通道无限递归告警。

---

## 15. RuntimeGuard 问题与状态管理

### 15.1 问题去重

同一未关闭问题只保留一条有效 `RuntimeGuardIssue`。

重复发现时：

```text
更新 last_seen_at_utc；
增加 occurrence_count；
更新结构化证据；
仅在达到提醒间隔时再次写 AlertEvent。
```

### 15.2 问题状态

只允许：

```text
open；
acknowledged；
resolved；
ignored。
```

确认、解决或忽略问题必须记录操作人、时间、原因和 trace_id。

把 Issue 标记为 resolved 只表示巡检问题关闭，不修改也不证明关联交易对象已经安全结束。

### 15.3 单项检查失败

一个检查器失败时：

```text
保存脱敏错误；
继续执行其他安全独立检查；
保留已经发现的问题；
RuntimeGuardRun 最终为 partial_failed。
```

不得把未执行的检查解释为没有问题。

---

## 16. Redis、Celery 与外部服务边界

### 16.1 Redis

可以用于：

```text
Celery broker / result backend；
短期调度锁；
短期任务认领辅助；
Notifications 限频与冷却；
短期技术状态。
```

Redis 不可用时，MySQL 中已有运行、事件、投递和问题事实不得丢失。

### 16.2 Binance

编排、RuntimeGuard 和 Notifications 均不直接访问 Binance。

业务模块仍按各自合同通过 BinanceGateway 访问 Binance。

### 16.3 Hermes

只有 Notifications channel 可以发送 Hermes。

Hermes 是单向通知通道，不接收交易命令，不触发编排恢复或业务动作。

### 16.4 外部大模型

本阶段不调用外部大模型，也不实现系统内大模型复盘。

### 16.5 真实交易

本阶段会调度 Execution 所属真实交易链路，但不新增任何订单提交实现。

测试和阶段验收必须使用 fake Gateway，并保持真实交易关闭。

---

## 17. Management command 边界

允许提供：

```text
触发 manual_diagnostic 编排；
查询编排详情；
执行明确的受控编排恢复；
RuntimeGuard dry-run；
RuntimeGuard confirm-write；
查看通知 pending 状态；
通知健康检查；
为 failed 且 retryable 的通知创建下一次尝试。
```

command 必须薄，只解析参数并调用 application service。

人工编排恢复必须记录：

```text
操作者；
原因；
证据；
目标 run；
新的 trace_id；
trigger_source；
是否写审计和 AlertEvent。
```

command 不得：

```text
伪装成原 automatic run；
复用原 resume_token；
直接调用业务模块；
重新提交订单；
直接修改业务对象；
直接释放 ActiveLock；
绕过 Notifications 路由发送 Hermes。
```

---

## 18. 测试计划

### 18.1 Registry 与 adapter 测试

至少覆盖：

```text
正式步骤完整且顺序正确；
DomainSignal、MarketRegime、StrategyRouting 与 StrategySignalQuality 未遗漏；
依赖成环时拒绝启动；
adapter 缺失或版本不匹配时拒绝启动；
每个业务状态都由白名单显式映射；
未知字符串、缺失状态和未知枚举 fail-closed；
normalized_status 与 flow_action 独立；
adapter 只调用对应 service；
adapter 不修改业务对象；
大对象引用策略正确。
```

### 18.2 PipelineOrchestrator 测试

至少覆盖：

```text
同一自动周期只创建一条 run；
Run 冻结 registry、adapter、mapping、配置和 StrategyAnalysisRelease；
每次实际步骤都有 StepRun；
ObjectLink 一对多写入且可反向查询；
业务外键链不依赖 ObjectLink；
CONTINUE、COMPLETE、WAIT、STOP、FAIL 映射正确；
NO_ACTION 不误报失败；
DataBackfill 循环有上限；
NO_TRADE / NO_TARGET_CHANGE 不进入 PriceSnapshot 或订单链；
权限关闭不调用 OrderPlan、不建 Candidate、不取 ActiveLock；
不同 release 的对象不能拼接；
失败不静默跳步。
```

### 18.3 WAIT 与任务测试

至少覆盖：

```text
WAIT 后 driver 结束且没有 sleep；
resume_token 只能消费一次；
恢复不重做已完成步骤；
Execution 使用交易关键任务组完成主交易订单提交步骤；
OrderStatusSync、FillSync 使用交易关键任务组完成独立订单生命周期同步；
同一 poll_sequence 只查询一次；
两秒节奏和 30 秒窗口正确；
达到窗口后 run 为 unknown 且锁保持；
worker 重启后以 MySQL 恢复；
Celery result backend 丢失不破坏业务状态。
```

### 18.4 崩溃与订单安全测试

至少覆盖：

```text
业务对象落库后、ObjectLink 前崩溃可以只补关联；
重复 adapter 调用返回已有业务结果；
订单提交步骤 redelivery 不再次调用 Gateway；
已有 OrderSubmissionAttempt 时不重新提交；
提交发生与否不确定时保持 unknown；
编排恢复不释放 ActiveLock；
RuntimeGuard 不恢复编排；
Notifications 不触发业务重放。
```

### 18.5 Notifications 测试

至少覆盖：

```text
event_key 幂等；
AlertEvent 与首个 pending attempt 或 Suppression 同事务形成；
Celery 唤醒丢失后 pending 扫描可恢复；
并发 worker 只发送一次；
Hermes 在事务提交后调用；
失败不回滚业务事实；
retryable failed 才能创建下一次尝试；
unknown 不自动重发；
外部投递关闭仍保存事件和 Suppression；
模板和路由 hash 可复现；
敏感信息不进入数据库、日志或消息；
使用 fake Hermes，不访问真实通道。
```

### 18.6 RuntimeGuard 测试

必须逐项覆盖 `runtime_guard.md` 定义的问题类型，并额外覆盖：

```text
十分钟调度与四小时编排互不冲突；
漏跑 grace window 正确；
合法无交易分支不误报 PriceSnapshot 缺失；
ops_display 不满足 trade_preparation 账户边界；
严格 synced_empty 不误报；
同一 issue_key 不重复建问题；
重复发现按提醒间隔告警；
单项检查失败形成 partial_failed；
RuntimeGuard 不调用 Binance、业务 service、锁服务或 Hermes；
RuntimeGuard 不修改被巡检对象；
dry-run 不写 Run、Issue 或 AlertEvent。
```

### 18.7 端到端测试

至少建立以下 fake 场景：

```text
完整无交易周期；
完整目标仓位但真实交易权限关闭周期；
OrderPlan no_order_required；
RiskCheck DENY；
ExecutionPreparation BLOCKED；
订单 accepted 后终态并完成 FillSync；
订单 unknown 后在窗口内找回；
订单 30 秒仍 unresolved；
通知 Hermes 临时失败后有限重试；
通知 unknown 不重发；
RuntimeGuard 发现长期 unknown 但不执行修复。
```

所有端到端测试禁止真实访问 Binance、DeepSeek 或 Hermes。

---

## 19. 阶段验收命令

具体命令以项目实际依赖管理工具为准。

至少需要等价执行：

```text
python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py migrate
pytest tests/orchestration/
pytest tests/runtime_guard/
pytest tests/notifications/
pytest tests/integration/
pytest
```

应提供等价的 Celery 集成测试或测试 worker 验证：

```text
重复消息；
WAIT 恢复；
交易关键任务路由；
pending 通知扫描；
RuntimeGuard 定时入口。
```

如果使用 `uv`：

```text
uv run python manage.py check
uv run python manage.py makemigrations --check --dry-run
uv run python manage.py migrate
uv run pytest
```

如果使用 `poetry`：

```text
poetry run python manage.py check
poetry run python manage.py makemigrations --check --dry-run
poetry run python manage.py migrate
poetry run pytest
```

阶段回报必须说明实际运行了哪些命令；无法执行的命令必须说明原因。

---

## 20. 阶段通过标准

阶段 6 通过必须满足：

```text
业务层、Connector / adapter 与 PipelineOrchestrator 职责清晰；
正式步骤由版本化 Registry 定义并通过启动校验；
自动四小时 run 从 trade_preparation Binance Account Sync 开始；
每轮冻结唯一 StrategyAnalysisRelease；
每个实际步骤都有 StepRun；
关键业务对象都有 ObjectLink；
业务对象继续使用真实业务外键；
编排层只消费统一 flow_action；
未知结果 fail-closed；
DataBackfill 循环有上限；
WAIT 释放 worker 并可幂等恢复；
OrderStatusSync 使用定向任务，不使用两秒全表扫描；
同一自动周期不重复创建 run；
同一步骤和业务对象不重复生成；
订单提交在任何恢复路径都不重试；
真实交易权限关闭时不创建订单链和 ActiveLock；
既有订单状态和成交任务不因关闭新交易而中止；
AlertEvent 与投递事实可靠交接；
通知消息丢失不会造成永久漏投；
通知失败不回滚业务；
通知 unknown 不自动重发；
RuntimeGuard 每十分钟独立运行；
RuntimeGuard 覆盖主编排、订单链、锁和通知投递；
RuntimeGuard 不修复业务、不释放锁、不访问外部交易服务；
MySQL 是所有运行事实的正式来源；
测试不访问真实 Binance、DeepSeek 或 Hermes；
所有业务时间使用 UTC；
所有日志和事件完成脱敏。
```

---

## 21. 阶段失败标准

出现以下任一情况，本阶段不得通过：

```text
PipelineOrchestrator 解释业务模块原始状态；
adapter 使用宽松 truthy 判断；
adapter 复制业务算法或直接修改业务表；
业务对象通过 orchestration_run_id 查找正式输入；
ObjectLink 替代真实业务外键；
同一自动周期创建多条有效 run；
运行进度只保存在 Redis、Celery 或进程内存；
WAIT 使用 sleep 或长事务占用 worker；
订单提交步骤因重投、恢复或人工操作再次调用 Gateway；
30 秒订单状态未解决后自动解锁；
RuntimeGuard 自动补跑、恢复、修改状态或释放锁；
RuntimeGuard 巡检 ReviewDataset；
RuntimeGuard 直接调用 Binance 或 Hermes；
业务模块直接发送 Hermes；
AlertEvent 保存成功但没有首个 DeliveryAttempt 或明确 Suppression；
通知 pending 只依赖一次 Celery 消息；
NotificationDeliveryAttempt unknown 被自动重发；
通知失败回滚业务事实；
通知成功触发业务动作；
关闭外部投递同时关闭 AlertEvent 写入；
任务队列积压改变业务事实；
日志、事件或投递记录暴露密钥、签名或完整外部响应；
测试访问真实交易所、DeepSeek 或 Hermes；
后台或 command 绕过业务 service。
```

---

## 22. 交付回报要求

阶段 6 编码完成后，回报必须说明：

```text
本阶段实现了什么；
新增和修改了哪些文件；
主要调用链路是什么；
Registry 版本与步骤顺序；
adapter 覆盖范围；
是否写库；
是否访问 Redis；
是否访问 Binance；
是否发送 Hermes；
是否调用大模型；
是否涉及真实交易；
是否涉及 FeatureLayer；
是否涉及 AtomicSignal / DomainSignal / MarketRegime；
是否涉及 StrategyRouting / StrategySignal / StrategyAnalysisRelease；
是否涉及 DecisionSnapshot；
是否涉及 Binance Account Sync；
是否涉及 PriceSnapshot；
是否涉及 OrderPlan / CandidateOrderIntent；
是否涉及 RiskCheck / ApprovedOrderIntent；
是否涉及 ExecutionPreparation / Execution；
是否涉及 OrderStatusSync / FillSync；
是否涉及 RuntimeGuard；
是否涉及 Notifications；
是否写 AlertEvent；
是否创建 NotificationDeliveryAttempt / NotificationSuppression；
订单提交是否绝不重试；
WAIT 如何释放和恢复；
RuntimeGuard 是否保持只读；
dry-run / confirm-write 行为；
异常处理方式；
测试命令和结果；
本阶段明确不负责什么；
是否违反 project_invariants.md。
```

---

## 23. 本阶段明确不负责

```text
重新实现各业务模块算法；
新增交易策略或修改目标仓位算法；
新增 Binance 请求接口；
新增未由 requirements 定义的订单类型、通用撤单或改单；
人工订单状态补查或成交补同步；
自动恢复交易异常；
自动释放 ActiveLock；
ReviewDataset 导出；
项目内大模型调用；
OpsConsole 复杂 UI；
后台热修改 Registry；
后台热切 active market domain；
模拟交易运行模式；
多交易所或多 active market domain 并行交易。
```

已由 `order_cycle_closeout.md` 定义的限价单周期收尾步骤可以接入编排，但不得扩展为通用撤单、改单或追单能力。

---

## 24. 下一阶段入口

阶段 6 验收通过后，下一步进入：

```text
docs/plans/operations_review_implementation_plan.md
```

下一阶段负责：

```text
OpsConsole 后端能力；
账户展示；
真实交易运行开关管理；
编排、订单、巡检和通知详情展示；
ReviewDataset 创建、状态查询和下载。
```

这些后置能力不得成为自动交易主链路必跑步骤，也不得反向触发交易。
