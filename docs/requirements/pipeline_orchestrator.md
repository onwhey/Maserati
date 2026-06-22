# PipelineOrchestrator 需求

## 1. 模块定位

PipelineOrchestrator 负责执行一轮完整业务流程，并提供统一的运行状态、步骤状态和业务对象索引。

系统采用三层结构：

```text
业务层
→ 编排&业务衔接器
→ 编排层
```

职责原则：

```text
业务层拥有业务事实、业务规则和真实业务外键；
编排&业务衔接器理解每个业务模块的入口、返回值和继续条件；
编排层只消费统一结果，并按衔接器定义的顺序执行、等待、停止或收尾。
```

编排层不得理解 `ALLOW`、`synced_empty`、`no_order_required`、`success`、`ok` 或 `true` 等模块特有语义。

## 2. 核心目标

本模块必须完成：

```text
每轮开始时创建唯一 OrchestrationRun；
解析并冻结当前唯一已批准、已启用的 StrategyAnalysisRelease；
从 OrchestrationStepRegistry 读取有版本的步骤定义和顺序；
通过对应 BusinessStepAdapter 调用业务 service；
把不同业务返回值转换为统一结果；
按统一 flow_action 决定继续、完成、等待、停止或失败；
为每个实际步骤创建 OrchestrationStepRun；
收集每个业务模块返回的业务对象引用；
把业务对象写入 OrchestrationBusinessObjectLink；
支持一轮编排关联多个业务对象；
支持异步等待和幂等恢复；
防止同一自动周期重复运行；
保留 registry、adapter、输入、输出和决策证据；
允许从一个编排 ID 快速查询整轮执行详情；
不替代业务模块之间的真实外键关系。
```

## 3. 不负责事项

PipelineOrchestrator 不负责：

```text
计算行情、特征、原子信号、领域信号、市场环境、路由或策略信号；
生成目标仓位；
读取或解释 Binance 原始响应；
计算 OrderPlan；
执行 RiskCheck；
修改 CandidateOrderIntent 或 ApprovedOrderIntent；
执行 price guard；
提交、查询或重试订单；
同步成交；
判断 ActiveLock 是否可以释放；
修改业务对象核心字段；
绕过业务模块直接写业务表；
根据字符串真假自行猜测业务结果；
调用管理命令或 shell 代替业务 service；
调用大模型参与实时交易判断；
通过后台热切换正式交易步骤顺序。
```

## 4. 第一层：业务层

业务模块继续拥有自己的：

```text
service；
domain 规则；
数据模型；
业务状态；
reason_code；
幂等规则；
真实业务外键；
AlertEvent；
外部服务访问边界。
```

业务模块不需要理解：

```text
OrchestrationRun；
OrchestrationStepRun；
步骤顺序；
上一环节或下一环节在编排中的编号；
编排最终状态；
其他模块的原始返回值。
```

业务 service 只接收完成本模块工作所需的直接业务输入和不透明幂等键。

## 5. 业务外键必须保留

业务对象之间的真实关系必须通过业务外键表达。

必须保留例如：

```text
CandidateOrderIntent.order_plan_id
RiskCheckResult.order_plan_id
RiskCheckResult.candidate_order_intent_id
ApprovedOrderIntent.risk_check_result_id
ApprovedOrderIntent.candidate_order_intent_id
PreparedOrderIntent.approved_order_intent_id
OrderSubmissionAttempt.prepared_order_intent_id
OrderStatusSyncRecord.order_submission_attempt_id
FillSyncResult.order_submission_attempt_id
TradeFill.order_submission_attempt_id
TradeFill.terminal_order_status_sync_record_id
OrderFillSummary.order_submission_attempt_id
```

这些外键证明业务对象为什么相关，是业务事实来源。

## 6. 第二层：编排&业务衔接器

编排&业务衔接器统一命名为：

```text
OrchestrationBusinessConnector
```

它由两部分组成：

```text
OrchestrationStepRegistry
BusinessStepAdapter
```

Connector 负责：

```text
提供当前有版本的步骤定义；
按 step_code 找到对应 adapter；
为 adapter 构造业务输入；
调用业务 service；
理解该业务模块的原始返回值；
严格映射统一 normalized_status；
严格映射统一 flow_action；
收集业务对象引用；
返回统一 OrchestrationStepResult；
保留原始结果摘要和映射证据。
```

Connector 不拥有业务规则，不得修改业务模块返回的事实。

## 7. OrchestrationStepRegistry

Registry 定义所有可被正式编排的模块和顺序。

每个步骤定义至少包含：

```text
pipeline_code
registry_version
step_code
step_order
module_code
adapter_code
adapter_version
depends_on_step_codes
execution_mode
is_required
is_conditional
timeout_policy
result_mapping_version
enabled
```

`execution_mode` 至少支持：

```text
synchronous
asynchronous_wait
```

Registry 规则：

```text
正式运行只加载 enabled 的已发布定义；
step_code 在同一 pipeline 中唯一；
step_order 不得冲突；
依赖必须形成无环图；
adapter 必须存在且版本匹配；
任何步骤变化必须生成新 registry_version；
生产运行中的 registry 不得原地修改；
运行时后台不得热插入交易步骤；
OrchestrationRun 必须冻结 registry_version 和 registry_hash。
```

Registry 可以由代码注册和版本化定义实现，不要求建立允许后台任意修改的数据库规则系统。

## 8. BusinessStepAdapter

原则上每个业务模块一个 adapter。

示例：

```text
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
BinanceAccountSyncStepAdapter
PriceSnapshotStepAdapter
OrderPlanStepAdapter
RiskCheckStepAdapter
ExecutionPreparationStepAdapter
OrderSubmissionStepAdapter
OrderStatusSyncStepAdapter
FillSyncStepAdapter
```

每个 adapter 必须实现等价接口：

```text
execute(step_context) -> OrchestrationStepResult
```

adapter 负责：

```text
从 step_context 取得明确业务对象 ID；
构造业务 service 参数；
传入不透明 business_request_key；
调用且只调用对应业务 service；
读取结构化业务结果；
按显式映射表转换结果；
收集 primary 和 related 业务对象引用；
返回统一结果。
```

adapter 不得：

```text
复制业务算法；
直接修改业务表；
绕过业务 service；
调用另一个业务模块补救当前结果；
重新解释业务事实；
把未知返回值按 truthy 自动放行；
直接提交订单；
直接修改 ActiveLock。
```

## 9. 禁止宽松真假判断

不同模块可能返回：

```text
success
ok
true
ALLOW
PREPARED
synced
```

这些值不能由编排器统一执行宽松布尔转换。

每个 adapter 必须使用明确映射，例如：

```text
DataCollection.status == success
→ SUCCEEDED + CONTINUE

RiskCheck.status == ALLOW
→ SUCCEEDED + CONTINUE

ExecutionPreparation.status == PREPARED
→ SUCCEEDED + CONTINUE

FillSync.status == synced
→ SUCCEEDED + COMPLETE
```

禁止：

```text
bool("false")；
非空字符串一律继续；
未知枚举一律继续；
缺失 status 时默认成功；
捕获异常后伪造 success。
```

未映射结果必须 fail-closed：

```text
normalized_status = FAILED
flow_action = FAIL
reason_code = unmapped_business_result
needs_manual_attention = true
```

## 10. OrchestrationStepResult

所有 adapter 必须返回统一不可变结果：

```text
step_code
module_code
adapter_code
adapter_version
normalized_status
flow_action
reason_code
message_zh
primary_object_ref
business_object_refs
raw_business_status
raw_result_summary
raw_result_hash
needs_manual_attention
resume_token
resume_step_code
started_at_utc
finished_at_utc
trace_id
```

`raw_result_summary` 必须脱敏且受大小限制，不得复制完整 K 线、特征数组、Binance 原始大响应或密钥。

## 11. normalized_status

只允许：

```text
SUCCEEDED
NO_ACTION
BLOCKED
UNKNOWN
FAILED
SKIPPED
```

语义：

```text
SUCCEEDED：业务步骤成功产生可消费结果；
NO_ACTION：业务正常完成，但本轮不需要继续产生交易动作；
BLOCKED：业务安全条件不允许继续；
UNKNOWN：业务事实无法确认；
FAILED：系统异常、合同损坏或未映射结果；
SKIPPED：根据已发布流程条件，本步骤本轮无需执行。
```

## 12. flow_action

只允许：

```text
CONTINUE
COMPLETE
WAIT
STOP
FAIL
```

语义：

```text
CONTINUE：按 Registry 进入下一合法步骤；
COMPLETE：本轮正常完成，不再执行后续步骤；
WAIT：异步业务尚未结束，保存等待状态后暂停；
STOP：业务阻断或不可继续，本轮受控结束；
FAIL：编排或系统失败，本轮失败结束。
```

编排层只读取 `flow_action`，不读取业务模块原始状态决定流程。

## 13. normalized_status 与 flow_action 分离

两者不能合并成一个布尔字段。

示例：

```text
订单提交 accepted
→ SUCCEEDED + CONTINUE

订单提交 unknown
→ UNKNOWN + CONTINUE
  原因：下一步 OrderStatusSync 仍可以找回订单。

订单状态轮询进行中
→ UNKNOWN + WAIT

订单状态 30 秒仍无法确认
→ UNKNOWN + COMPLETE
  OrchestrationRun 最终状态为 unknown。

OrderPlan no_order_required
→ NO_ACTION + COMPLETE

DecisionSnapshot NO_TARGET_CHANGE / NO_TRADE
→ NO_ACTION + COMPLETE
  原因：本轮自动账户边界事实已在编排起始阶段保存，不再产生价格或订单动作。

RiskCheck DENY
→ BLOCKED + STOP

未预期代码异常
→ FAILED + FAIL
```

## 14. 第三层：编排层

编排层核心组件：

```text
PipelineOrchestrator
```

它只负责：

```text
创建 OrchestrationRun；
冻结 Registry；
冻结 StrategyAnalysisRelease 身份；
创建 OrchestrationStepRun；
调用 OrchestrationBusinessConnector；
持久化统一步骤结果；
持久化业务对象关联；
按 flow_action 推进状态；
等待和恢复异步步骤；
写编排级 AlertEvent；
完成或终结 OrchestrationRun。
```

PipelineOrchestrator 不得包含针对具体业务状态的大型 if / elif / switch。

## 15. 正式步骤顺序

Registry 必须定义以下主线步骤：

```text
binance_account_sync（自动四小时账户边界，起始步骤）
data_collection
data_quality
data_backfill（条件步骤）
market_snapshot
feature_layer
atomic_signals
domain_signals
market_regime
strategy_routing
strategy_signals
strategy_signal_quality
decision_snapshot
price_snapshot
order_plan
risk_check
execution_preparation
order_submission
order_status_sync
fill_sync
```

依赖主线：

```text
BinanceAccountSync（自动四小时账户边界，起始步骤）
→ DataCollection
→ DataQuality
→ 必要时 DataBackfill
→ 重新 DataQuality
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
→ OrderPlan
→ RiskCheck
→ ExecutionPreparation
→ OrderSubmission
→ OrderStatusSync
→ FillSync
或 NO_TARGET_CHANGE / NO_TRADE：正常结束，不进入 PriceSnapshot 或订单链路
```

具体分支由对应 adapter 返回统一结果，编排层不理解分支业务原因。

## 16. 条件步骤与循环限制

DataBackfill 属于受控条件步骤。

允许路径：

```text
DataQuality 请求补采
→ DataBackfill
→ DataQuality 重新验证
```

条件执行规则：

```text
DataQuality 通过 → DataBackfill 本轮 SKIPPED，继续进入 MarketSnapshot；
DataQuality 不通过但返回可回补结论 → 进入 DataBackfill；
DataBackfill 完成后必须回到 DataQuality 重新验证；
DataQuality 不通过且不可回补 → BLOCKED + STOP；
DataBackfill 失败或超过最大回补轮次 → BLOCKED + STOP。
```

是否需要回补、是否允许回补、回补后是否通过，均由 DataQuality / DataBackfill adapter 的明确映射决定。编排层只消费统一结果，不读取具体缺口原因。

Registry 必须定义最大补采轮次，禁止无界循环。

其他交易步骤不得通过 Registry 形成自动循环，特别禁止：

```text
RiskCheck 失败后自动重做 OrderPlan；
ExecutionPreparation 阻断后自动刷新价格并重做；
订单提交失败后自动重新提交；
订单 unknown 后回到订单提交；
成交同步失败后重新下单。
```

## 17. 模块结果映射摘要

### 17.1 数据与信号

```text
数据成功且质量通过 → SUCCEEDED + CONTINUE；
需要补采 → BLOCKED + CONTINUE 到条件 DataBackfill；
补采后仍不合格 → BLOCKED + STOP；
版本包缺失、冲突或指纹不一致 → BLOCKED + STOP，且不得进入 FeatureLayer；
FeatureLayer / AtomicSignal / DomainSignal / MarketRegime 成功 → SUCCEEDED + CONTINUE；
StrategyRouting selected → SUCCEEDED + CONTINUE；
StrategyRouting no_strategy → NO_ACTION + COMPLETE；
StrategySignal 成功且质量通过 → SUCCEEDED + CONTINUE；
DecisionSnapshot TARGET_POSITION → SUCCEEDED + CONTINUE 到 PriceSnapshot；
DecisionSnapshot NO_TARGET_CHANGE / NO_TRADE → NO_ACTION + COMPLETE；
策略质量不通过 → BLOCKED + STOP。
```

### 17.2 账户、价格与规划

```text
自动四小时账户边界同步成功 → SUCCEEDED + CONTINUE 到 DataCollection；
账户同步不可消费 → BLOCKED + STOP；
价格快照成功 → SUCCEEDED + CONTINUE；
价格快照失败或过期 → BLOCKED + STOP；
真实交易权限关闭 → NO_ACTION + COMPLETE；
OrderPlan created → SUCCEEDED + CONTINUE；
OrderPlan no_order_required → NO_ACTION + COMPLETE；
OrderPlan blocked → BLOCKED + STOP。
```

#### 17.2.1 自动四小时账户边界同步

自动四小时编排在创建 OrchestrationRun 并冻结本轮运行身份后，必须优先调用一次 BinanceAccountSyncStepAdapter：

```text
sync_purpose = trade_preparation；
使用本轮自动编排的稳定 business_request_key；
成功结果写入 OrchestrationBusinessObjectLink；
作为 PerformanceMetrics 的自动账户边界事实；
同步完成后 flow_action = CONTINUE，进入 DataCollection。
```

该步骤与后续策略和订单分支解耦。无论后续流程是 TARGET_POSITION、NO_TARGET_CHANGE、NO_TRADE、no_strategy、真实交易权限关闭、质量阻断或版本包缺失，只要本轮自动编排已经开始，就必须优先尝试保存该账户边界事实。

该步骤禁止：

```text
调用 PriceSnapshot；
检查真实交易权限；
调用 OrderPlan；
生成 CandidateOrderIntent；
取得 ActiveLock。
```

DecisionSnapshotStepAdapter 只返回目标仓位分支语义，不直接调用 Binance Account Sync。Connector 不得在 DecisionSnapshot 后补做第二次账户边界同步。

账户同步失败、阻断或 unknown 时，必须按 Binance Account Sync 的统一结果映射停止或标记本轮，不得为了形成绩效边界伪造账户快照。

#### 17.2.2 真实交易权限准入

OrderPlanStepAdapter 在调用 OrderPlan service 前，必须检查一次当前真实交易权限。

只有以下两项同时允许，才可以进入 OrderPlan：

```text
.env 中的真实交易硬权限允许；
MySQL 中由 OpsConsole 管理的真实交易运行开关允许。
```

如果任一项关闭，adapter 必须：

```text
不调用 OrderPlan service；
不生成 OrderPlan；
不生成 CandidateOrderIntent；
不取得 ActiveLock；
返回 normalized_status = NO_ACTION；
返回 flow_action = COMPLETE；
reason_code = real_trading_not_allowed；
记录本次权限检查时间、配置版本和脱敏结果摘要。
```

如果部署配置、MySQL 运行开关或当前交易市场配置不可读取，或者当前业务市场与部署市场配置不一致：

```text
normalized_status = BLOCKED；
flow_action = STOP；
reason_code = real_trading_permission_unavailable 或 market_context_mismatch。
```

本次检查通过后，本轮后续步骤使用已经冻结的检查结果，不再重新读取真实交易运行开关。后台随后发生的开关变化只影响下一次进入 OrderPlan 的检查。

真实交易权限判断属于 OrderPlanStepAdapter 的业务衔接职责。编排层只消费 adapter 返回的统一结果，不直接读取配置，也不得直接释放 ActiveLock。

### 17.3 风控与执行准备

```text
RiskCheck ALLOW → SUCCEEDED + CONTINUE；
RiskCheck DENY / BLOCKED → BLOCKED + STOP；
RiskCheck FAILED → FAILED + FAIL；
ExecutionPreparation PREPARED → SUCCEEDED + CONTINUE；
ExecutionPreparation BLOCKED → BLOCKED + STOP；
ExecutionPreparation FAILED → FAILED + FAIL。
```

### 17.4 提交、状态与成交

```text
OrderSubmission accepted → SUCCEEDED + CONTINUE；
OrderSubmission unknown → UNKNOWN + CONTINUE 到 OrderStatusSync；
OrderSubmission rejected → BLOCKED + STOP；
blocked_before_submit → BLOCKED + STOP；
failed_before_submit → FAILED + FAIL；

OrderStatusSync 正在 2 秒轮询 → UNKNOWN + WAIT；
OrderStatusSync 找到非终态 → UNKNOWN + WAIT；
OrderStatusSync 找到明确终态 → SUCCEEDED + CONTINUE 到 FillSync；
OrderStatusSync 30 秒未解决 → UNKNOWN + COMPLETE；

FillSync synced → SUCCEEDED + COMPLETE；
FillSync synced_empty 且锁安全收尾 → SUCCEEDED + COMPLETE；
FillSync incomplete / unknown → UNKNOWN + COMPLETE；
FillSync failed_before_query → FAILED + FAIL；
FillSync blocked_before_query → BLOCKED + STOP；
FillSync recovery_skipped_out_of_window → UNKNOWN + COMPLETE。
```

以上摘要必须由各 adapter 的版本化映射实现，不得复制进 PipelineOrchestrator 主循环。

## 18. OrchestrationRun

每轮开始时先创建 `OrchestrationRun`。

`OrchestrationRun.id` 是唯一编排 ID。

至少记录：

```text
id
run_key
pipeline_code
registry_version
registry_hash
strategy_analysis_release_id
strategy_analysis_release_hash
strategy_analysis_release_freeze_status
strategy_analysis_release_freeze_reason_code
run_config_snapshot_id
run_config_snapshot_hash
scheduled_for_utc
cycle_kind
trigger_mode
trigger_source
status
final_outcome
reason_code
reason_message
current_step_code
last_completed_step_code
last_stopped_step_code
needs_manual_attention
trace_id
started_at_utc
waiting_since_utc
finished_at_utc
created_at_utc
updated_at_utc
```

### 18.1 StrategyAnalysisRelease 冻结

创建 OrchestrationRun 时必须尝试解析当前唯一已批准并已启用的 StrategyAnalysisRelease，并验证 `release_hash`、依赖闭包、calculator 注册和完整链路切片。

规则：

```text
解析成功后，把 strategy_analysis_release_id 与 strategy_analysis_release_hash 冻结到 OrchestrationRun；
解析失败时，strategy_analysis_release_id 与 strategy_analysis_release_hash 允许为空，但必须记录 strategy_analysis_release_freeze_status 和 reason_code；
同一 OrchestrationRun 后续所有 FeatureLayer 到 DecisionSnapshot 步骤只能使用该版本包；
版本包在运行途中被切换、停用或回滚，不改变本轮已经冻结的身份；
如果冻结版本包中的 Definition 后续被禁用或实现缺失，业务步骤必须 fail-closed，不得改用新版本包；
不得在某个步骤失败后重新解析“当前版本包”；
不得把不同版本包的上游业务对象拼接到同一轮正式链路。
```

没有唯一可用版本包时，OrchestrationRun 仍可记录数据采集、质量检查、回补和 MarketSnapshot 等数据维护步骤，但必须在 FeatureLayer 前停止策略分析主线：

```text
normalized_status = BLOCKED；
flow_action = STOP；
reason_code = strategy_analysis_release_unavailable 或 strategy_analysis_release_conflict；
不得调用 FeatureLayer 及其后续策略、决策、订单步骤；
写编排级 AlertEvent。
```

版本包管理、批准、启用、切换和回滚统一遵守 [StrategyAnalysisRelease](strategy_analysis_release.md)。

`cycle_kind` 至少支持：

```text
four_hour_boundary
daily_boundary
manual_diagnostic
```

## 19. OrchestrationRun 状态

只允许：

```text
created
running
waiting
completed
completed_no_action
blocked
unknown
failed
stale_interrupted
```

语义：

```text
created：主记录已创建，尚未执行第一步；
running：正在执行同步步骤；
waiting：等待已登记的异步业务结果；
completed：流程正常完成；
completed_no_action：业务正常结束且无需交易动作；
blocked：业务安全条件终止；
unknown：订单或外部事实在允许窗口内仍无法确认；
failed：系统异常或合同失败；
stale_interrupted：进程中断且无法安全自动恢复。
```

业务 BLOCKED 不得自动映射成 failed。

## 20. OrchestrationStepRun

每次实际步骤执行必须创建一条 `OrchestrationStepRun`。

至少记录：

```text
id
orchestration_run_id
step_code
step_order
execution_sequence
module_code
adapter_code
adapter_version
result_mapping_version
business_request_key
status
raw_business_status
normalized_status
flow_action
reason_code
reason_message
needs_manual_attention
resume_token
input_refs_hash
result_hash
started_at_utc
waiting_since_utc
finished_at_utc
error_class
sanitized_error_message
trace_id
created_at_utc
updated_at_utc
```

唯一约束至少包括：

```text
(orchestration_run_id, step_code, execution_sequence) unique
business_request_key unique
resume_token unique（非空时）
```

## 21. OrchestrationStepRun 状态

只允许：

```text
pending
running
waiting
completed
blocked
unknown
failed
skipped
```

异步恢复不得创建第二条相同 execution_sequence 的有效步骤记录。

## 22. OrchestrationBusinessObjectLink

该表提供编排 ID 与业务对象 ID 的一对多关联。

至少记录：

```text
id
orchestration_run_id
orchestration_step_run_id
step_code
module_code
object_type
object_id
object_role
object_label
created_at_utc
```

`object_role` 至少支持：

```text
primary_output
output
input
related
audit
```

唯一约束：

```text
(
    orchestration_run_id,
    orchestration_step_run_id,
    object_type,
    object_id,
    object_role,
) unique
```

索引至少包括：

```text
orchestration_run_id
(orchestration_run_id, step_code)
(object_type, object_id)
orchestration_step_run_id
```

`object_id` 必须使用可容纳 UUID、整数主键或其他标准业务 ID 的统一字符串表示，不允许保存模糊展示名称代替真实 ID。

## 23. 关联表不是业务外键

两套关系必须严格区分：

```text
业务外键
= 业务对象之间的真实来源和依赖关系；

OrchestrationBusinessObjectLink
= 快速查询一轮编排产生、读取和关联了哪些业务对象。
```

业务模块不得通过 OrchestrationBusinessObjectLink 查找自己的正式输入。

例如 RiskCheck 必须通过显式 `order_plan_id`、`candidate_order_intent_id` 等业务输入读取对象，不得传入 `orchestration_run_id` 后让 RiskCheck 自行从关联表猜测要审核哪一条订单计划。

业务链追溯不得依赖编排关联表；既有业务对象之间必须能够独立通过真实业务外键追溯。

## 24. 业务对象引用收集

adapter 返回：

```text
primary_object_ref
business_object_refs
```

每个引用至少包括：

```text
object_type
object_id
object_role
object_label
```

示例：

```text
OrderPlanStepAdapter
→ primary_output: OrderPlan
→ output: CandidateOrderIntent primary
→ output: CandidateOrderIntent fallback_reduce_only（如有）
→ related: OrderPlanActiveLock

RiskCheckStepAdapter
→ primary_output: RiskCheckResult
→ output: ApprovedOrderIntent（仅 ALLOW）
→ related: RiskRuleResult
→ audit: AlertEvent

FillSyncStepAdapter
→ primary_output: OrderFillSummary
→ output: FillSyncResult
→ output: 多条 TradeFill
→ related: terminal OrderStatusSyncRecord
→ related: released OrderPlanActiveLock（仅安全收尾成功）
```

## 25. 大量子对象处理

FeatureValue、AtomicSignalValue、TradeFill、RiskRuleResult 等模块可能产生多条记录。

规则：

```text
必须关联模块根对象、set、batch、summary 或 primary result；
关键同级业务对象可以逐条关联；
可通过根对象业务外键展开的海量子记录不要求全部重复写关联表；
adapter 必须明确采用 root_only、all_primary 或 explicit_refs 策略；
采用何种策略必须进入 adapter_version 和测试。
```

关联表不得成为复制整个业务数据库的影子表。

## 26. 不透明业务幂等键

PriceSnapshot、BinanceSyncRun 等模块必须独立保证业务对象不会重复生成。

编排层在调用业务 service 前生成：

```text
business_request_key
```

生成依据至少包括：

```text
orchestration_run_id
step_code
execution_sequence
registry_version
```

业务模块只把它视为不透明幂等键，不解析其中的编排含义。

业务 service 要求：

```text
相同 business_request_key 重复调用返回同一业务结果；
不得生成第二份有效主对象；
不得因任务重放再次访问不应重复访问的外部接口；
business_request_key 在对应业务主对象上唯一；
业务模块不通过该 key 查询编排数据。
```

## 27. 崩溃窗口与关联恢复

必须处理以下场景：

```text
业务 service 已成功写入业务对象；
进程在写 OrchestrationBusinessObjectLink 前崩溃。
```

恢复规则：

```text
OrchestrationStepRun 和 business_request_key 已在调用前持久化；
恢复时使用同一 business_request_key 重放 adapter；
业务 service 返回原业务对象，不创建第二份；
adapter 重新返回 object refs；
编排层幂等补写关联表；
不得重做订单提交。
```

订单提交步骤的重放只能读取已有 OrderSubmissionAttempt，绝不能再次调用 BinanceOrderSubmissionGateway。

## 28. 业务输入传递

编排层不得把 `orchestration_run_id` 当作业务 service 的查询入口。

Connector 根据已有 object links 和 Registry 依赖构造明确输入，再调用 adapter。

示例：

```text
FeatureLayer
← market_snapshot_id
← strategy_analysis_release_id / hash
← expected_feature_definition_set_hash

AtomicSignal
← feature_set_id
← strategy_analysis_release_id / hash
← expected_atomic_signal_definition_set_hash

DomainSignal
← atomic_signal_set_id
← strategy_analysis_release_id / hash
← expected_domain_signal_definition_set_hash

MarketRegime
← domain_signal_set_id
← strategy_analysis_release_id / hash
← expected_market_regime_definition_hash

StrategyRouting
← market_regime_snapshot_id
← strategy_analysis_release_id / hash
← expected_strategy_route_policy_hash
← expected_strategy_definition_set_hash

StrategySignal
← strategy_route_decision_id
← strategy_analysis_release_id / hash
← expected_strategy_definition_hash

StrategySignalQuality
← strategy_signal_id
← strategy_analysis_release_id / hash
← expected_quality_rule_set_hash

DecisionSnapshot
← strategy_signal_quality_result_id
← strategy_analysis_release_id / hash
← expected_decision_policy_definition_hash

OrderPlan
← decision_snapshot_id
← binance_sync_run_id
← price_snapshot_id

RiskCheck
← order_plan_id
← candidate_order_intent_id
← binance_sync_run_id
← price_snapshot_id
← active_lock_id

ExecutionPreparation
← approved_order_intent_id

OrderSubmission
← prepared_order_intent_id

OrderStatusSync
← order_submission_attempt_id

FillSync
← order_submission_attempt_id
← terminal_order_status_sync_record_id
```

业务模块继续自行校验市场身份、symbol、直接上游外键和事实完整性。

## 29. 关联写入顺序

同步步骤的标准顺序：

```text
创建并提交 OrchestrationStepRun；
调用 adapter；
业务 service 自己完成业务事务；
adapter 返回统一结果和 object refs；
编排层在事务中锁定 StepRun；
写入 OrchestrationBusinessObjectLink；
保存统一结果；
推进 OrchestrationRun；
提交事务。
```

不得在数据库长事务中等待外部网络请求。

## 30. 异步 WAIT 与恢复

OrderStatusSync 等步骤可能异步等待。

当 `flow_action = WAIT`：

```text
OrchestrationStepRun.status = waiting；
OrchestrationRun.status = waiting；
保存 resume_token；
保存等待对象引用和下一检查时间；
当前 worker 结束，不持续占用进程；
异步结果到达后使用同一 resume_token 恢复。
```

恢复时必须：

```text
锁定 OrchestrationRun 和 waiting StepRun；
确认 resume_token 匹配且未消费；
读取 adapter 的新统一结果；
幂等补写新 object refs；
推进或终结本轮；
不得重新执行已完成步骤。
```

## 31. 订单状态轮询衔接

OrderSubmission accepted 或 unknown 后进入 OrderStatusSync。

衔接器负责把 OrderStatusSync 的业务结果转换为：

```text
开始 2 秒轮询 → WAIT；
轮询仍在 30 秒窗口 → WAIT；
查到明确终态 → CONTINUE 到 FillSync；
30 秒仍 not_found / unknown / 非终态 → COMPLETE，run 最终 unknown；
查询合同失败 → FAIL。
```

编排层不实现 2 秒计时、不判断 Binance status、不判断终态白名单。

## 32. 订单提交绝不重试

编排层不得因为以下状态重新执行 order_submission：

```text
rejected；
unknown；
blocked_before_submit；
failed_before_submit；
Celery 重复投递；
进程崩溃；
恢复编排；
人工点击重放。
```

恢复订单提交步骤时只能读取已有 OrderSubmissionAttempt 并返回统一结果。

## 33. 自动运行时间

自动运行使用 UTC：

```text
four_hour_boundary：04:05、08:05、12:05、16:05、20:05 UTC；
daily_boundary：00:05 UTC。
```

日线边界必须由数据质量 adapter 确认最新已收盘 4h 与 1d 数据均可消费。

不得使用服务器本地时区、用户时区或运行机器时区决定业务周期。

## 34. 防重复运行

自动运行唯一键至少包括：

```text
pipeline_code
scheduled_for_utc
cycle_kind
trigger_mode = automatic
```

同一自动周期：

```text
已经 created / running / waiting → 不创建第二轮；
已经终结 → 不自动重跑；
unknown / failed / stale_interrupted → 不自动重新执行交易链路；
订单相关步骤已经开始 → 永远不通过新 run 绕过 ActiveLock。
```

人工诊断必须创建新的 `manual_diagnostic` OrchestrationRun，并明确只允许诊断或受控恢复能力，不得伪装成原自动周期继续下单。

## 35. 最终状态映射

```text
最后步骤 SUCCEEDED + COMPLETE
→ completed

NO_ACTION + COMPLETE
→ completed_no_action

BLOCKED + STOP
→ blocked

UNKNOWN + COMPLETE
→ unknown

FAILED + FAIL
→ failed
```

最终状态必须由统一结果映射，不得由异常消息文本猜测。

## 36. Stale run

RuntimeGuard 必须能够发现长期停留在：

```text
running
waiting
```

RuntimeGuard 只负责创建或更新 `RuntimeGuardIssue` 并写 `AlertEvent`，不得恢复编排、修改 `OrchestrationRun` 状态或修改任何业务事实。

`PipelineOrchestrator` 可以提供受控恢复入口。受控恢复必须：

```text
记录最后 StepRun；
检查是否存在合法 resume_token；
能安全恢复的非提交步骤按原 business_request_key 恢复；
订单提交步骤绝不重新调用 Gateway；
无法安全恢复时标记 stale_interrupted；
写 AlertEvent；
不直接修改业务事实或 ActiveLock。
```

受控恢复不得由 RuntimeGuard 自动触发。人工触发时必须记录操作人、原因、证据和 `trace_id`。

## 37. 编排级 AlertEvent

至少包括：

```text
orchestration_run_started
orchestration_step_started
orchestration_step_completed
orchestration_step_waiting
orchestration_step_blocked
orchestration_step_unknown
orchestration_step_failed
orchestration_run_completed
orchestration_run_completed_no_action
orchestration_run_blocked
orchestration_run_unknown
orchestration_run_failed
orchestration_run_stale_interrupted
duplicate_orchestration_triggered
unmapped_business_result
orchestration_object_link_failed
```

编排 AlertEvent 只说明流程状态，不替代业务模块自己的业务事件。

## 38. trace_id

每个 OrchestrationRun 必须生成或接收唯一 `trace_id`。

规则：

```text
所有 StepRun 继承 trace_id；
所有 adapter 把 trace_id 传给业务 service；
业务对象和 AlertEvent 按自身合同保存 trace_id；
异步 WAIT 恢复继续使用原 trace_id；
人工诊断使用新的 trace_id 并关联原 run ID；
trace_id 不是业务外键，也不是幂等键。
```

## 39. 查询一轮编排详情

查询入口：

```text
get_orchestration_detail(orchestration_run_id)
```

必须返回：

```text
OrchestrationRun 摘要；
冻结的 Registry 版本；
冻结的 StrategyAnalysisRelease 身份与 release_hash；
按执行顺序排列的 StepRun；
每一步统一结果；
每一步 primary / output / input / related / audit 对象引用；
当前等待或停止位置；
needs_manual_attention；
编排级 AlertEvent；
业务详情跳转所需 object_type 和 object_id。
```

查询 service 只聚合和展示，不修改业务对象。

## 40. 查询业务对象所属编排

必须支持反向查询：

```text
find_orchestration_runs(object_type, object_id)
```

用于：

```text
从 OrderPlan 找到产生它的编排；
从 RiskCheckResult 找到审核流程；
从 OrderSubmissionAttempt 找到完整运行；
从 TradeFill 找到策略、价格和账户事实；
从 AlertEvent 找到对应步骤。
```

反向查询只用于审计、排错和界面导航，不参与业务决策。

## 41. 配置与版本

所有环境配置进入 `.env.example` 并带中文注释：

```text
PIPELINE_ORCHESTRATOR_ENABLED
PIPELINE_CODE
ORCHESTRATION_STALE_RUNNING_SECONDS
ORCHESTRATION_STALE_WAITING_SECONDS
ORCHESTRATION_MAX_BACKFILL_ROUNDS
```

步骤顺序、业务结果映射和终态语义不通过 env 任意热修改，必须由版本化 Registry 和 Adapter 管理。

每个 OrchestrationRun 必须保存实际使用的：

```text
registry_version
registry_hash
strategy_analysis_release_id
strategy_analysis_release_hash
adapter_versions
result_mapping_versions
config_snapshot
```

这些版本和配置快照可以直接保存在 OrchestrationRun 上，也可以保存到独立的 `OrchestrationRunConfigSnapshot`。如果使用独立快照，OrchestrationRun 必须保存 `run_config_snapshot_id` 和 `run_config_snapshot_hash`。

`OrchestrationRunConfigSnapshot` 至少记录：

```text
id
orchestration_run_id
registry_version
registry_hash
strategy_analysis_release_id
strategy_analysis_release_hash
adapter_versions
result_mapping_versions
config_snapshot
snapshot_hash
created_at_utc
```

该快照只用于审计和恢复，不得作为业务模块读取输入的来源。

## 42. Celery task 与 management command

Celery task 只能：

```text
解析 scheduled_for_utc 或 orchestration_run_id；
生成或传递 trace_id；
设置 trigger_source；
调用 PipelineOrchestrator service；
输出结构化摘要。
```

management command 同样只能作为入口。

task 和 command 不得：

```text
直接调用业务模块；
自行解释业务返回值；
直接写业务对象关联；
修改 Registry；
绕过 Connector；
绕过进入 OrderPlan 前的真实交易权限检查；
重试订单提交。
```

## 43. 数据与外部服务

```text
读写 MySQL：是，保存 Run、StepRun、ObjectLink 和编排审计；
直接访问 Redis：可用于编排触发幂等和短期调度，不作为编排主事实；
直接访问 Binance：否；
发送 Hermes：否，只写 AlertEvent；
调用大模型：否；
涉及真实交易：编排交易模块，但不直接提交订单；
涉及 FeatureLayer：通过 Connector；
涉及 AtomicSignal：通过 Connector；
涉及 DecisionSnapshot：通过 Connector；
涉及 Binance Account Sync：通过 Connector；
涉及 PriceSnapshot：通过 Connector；
涉及 OrderPlan / CandidateOrderIntent：通过 Connector；
涉及 RiskCheck / ApprovedOrderIntent：通过 Connector；
涉及 ExecutionPreparation / Execution：通过 Connector；
涉及 OrderStatusSync / FillSync：通过 Connector；
直接更新 ActiveLock：否；
写 AlertEvent：是。
```

## 44. 异常处理

```text
业务返回明确统一结果 → 按 flow_action 处理；
业务返回未知枚举 → FAIL；
adapter 缺失或版本不匹配 → FAIL；
Registry 损坏或依赖成环 → 启动前 FAIL；
业务 service 抛出未预期异常 → FAILED + FAIL；
ObjectLink 写入失败 → 保留 StepRun，标记 failed 并通过同一 business_request_key 恢复；
异步结果超时 → 按 adapter 映射 UNKNOWN 或 FAILED；
无法确认订单提交结果 → 继续查询，不重新提交；
无法安全恢复 → stale_interrupted。
```

禁止静默跳过缺失关联或把异常默认成成功。

## 45. 测试要求

至少覆盖：

```text
1. 每轮开始生成唯一 OrchestrationRun。
2. 同一自动周期并发触发只生成一份 run。
3. Registry 版本和 hash 被冻结。
3a. StrategyAnalysisRelease ID 和 hash 在每轮开始时冻结。
4. Registry 依赖成环时启动失败。
5. 缺失 adapter 时启动失败。
6. 每个正式模块都已注册 adapter，包括 DomainSignal、MarketRegime 和 StrategyRouting。
7. PipelineOrchestrator 不包含模块特有状态判断。
8. success 显式映射 SUCCEEDED + CONTINUE。
9. ok 显式映射 SUCCEEDED + CONTINUE。
10. true 只在对应 adapter 明确允许时继续。
11. 未知非空字符串不会被 truthy 放行。
12. 缺失业务 status 时 FAIL。
13. unmapped result 写 AlertEvent。
14. NO_ACTION 正常结束而不是 failed。
15. BLOCKED 正常受控停止而不是异常崩溃。
16. UNKNOWN 可以按 adapter 进入 CONTINUE、WAIT 或 COMPLETE。
17. 每个实际步骤生成 StepRun。
18. StepRun 保存 adapter 和 mapping 版本。
19. 同一 execution_sequence 不重复执行。
20. 每个业务主对象写 ObjectLink。
21. 一步产生多个对象时形成一对多关联。
22. FeatureSet 根对象可展开 FeatureValue。
23. AtomicSignalSet 根对象可展开 AtomicSignalValue。
24. OrderPlan、Candidate 和 ActiveLock 均可关联。
25. RiskCheckResult 和 ApprovedOrderIntent 均可关联。
26. 多条 OrderStatusSyncRecord 可以关联同一 run。
27. 多条 TradeFill 可以关联同一 run。
28. ObjectLink 可以反向找到 run。
29. 业务模块不读取 ObjectLink 获取正式输入。
30. RiskCheck 通过 order_plan_id 读取真实上游。
31. OrderStatusSync 通过 attempt 外键读取订单。
32. 业务外键链独立于编排关联并可单独追溯。
33. business_request_key 对同一步唯一。
34. PriceSnapshot 重放返回同一对象。
35. BinanceSyncRun 重放返回同一对象。
36. 业务成功但关联前崩溃时可幂等补链。
37. 关联恢复不重复请求不应重复的 Binance 接口。
38. 订单提交步骤恢复不再次提交。
39. DataQuality 可以受控进入 DataBackfill。
40. Backfill 循环超过上限时停止。
41. OrderPlan no_order_required 完成无订单流程。
42. RiskCheck DENY 停止执行链路。
43. ExecutionPreparation BLOCKED 不进入订单提交。
44. OrderSubmission accepted 进入状态同步。
45. OrderSubmission unknown 进入状态同步而不重提。
46. OrderStatusSync 轮询时 run 进入 waiting。
47. WAIT 不持续占用 worker。
48. resume_token 只能消费一次。
49. 状态终态后恢复进入 FillSync。
50. 30 秒 unresolved 后 run 进入 unknown。
51. FillSync synced 后正常完成。
52. FillSync synced_empty 严格成立后正常完成。
53. FillSync incomplete 后 run unknown 且锁保持阻断。
54. 编排层不直接访问 Binance。
55. 编排层不直接更新 ActiveLock。
56. 编排层不修改业务对象核心字段。
57. stale running 可以安全识别。
58. stale waiting 可以安全识别。
59. 无法安全恢复的 run 标记 stale_interrupted。
60. 自动周期使用 UTC。
61. 日线周期要求 4h 与 1d 数据可消费。
62. 人工诊断创建新 run，不复用自动 run。
63. get_orchestration_detail 返回完整步骤和对象引用。
64. 大量子对象采用明确关联策略，不复制全表。
65. 编排和业务 AlertEvent 可以分别追溯。
66. 日志和结果不包含密钥或大体积原始数据。
67. 真实交易权限关闭时不调用 OrderPlan，不生成 CandidateOrderIntent，不取得 ActiveLock。
68. 真实交易权限或市场配置不可读取时，OrderPlanStepAdapter fail-closed。
69. 权限在进入 OrderPlan 前只检查一次；检查通过后，本轮后续步骤不重新读取后台开关。
70. 没有唯一已批准并启用的 StrategyAnalysisRelease 时，在 FeatureLayer 前停止策略分析主线。
71. 版本包在运行途中切换不改变本轮冻结 ID 和 hash。
72. 任一步骤发现 Definition、切片或 hash 与冻结版本包不一致时 fail-closed，不改用其他版本包。
73. FeatureLayer 到 DecisionSnapshot 的所有 adapter 传递同一 strategy_analysis_release_id / hash。
74. 自动四小时编排起始阶段必须执行一次 trade_preparation 账户同步。
75. NO_TARGET_CHANGE / NO_TRADE 正常结束时不补做账户同步，不调用 PriceSnapshot、OrderPlan，也不取得 ActiveLock。
76. 正式步骤顺序包含 DomainSignal、MarketRegime 和 StrategyRouting。
77. 不同版本包的业务对象不能拼接到同一轮正式策略链。
```

## 46. 验收标准

满足以下条件才算完成：

```text
业务层、编排&业务衔接器、编排层职责清楚；
所有被编排模块都由版本化 Registry 定义；
每轮正式策略分析只使用一个冻结的 StrategyAnalysisRelease；
每个业务模块具有独立 adapter；
业务原始返回值由 adapter 理解和显式映射；
编排层只消费 normalized_status 和 flow_action；
未知结果不会默认放行；
OrchestrationRun.id 是唯一编排 ID；
每个步骤具有可审计 StepRun；
每轮业务对象通过 ObjectLink 一对多关联；
业务模块不保存或查询编排 ID；
业务对象之间的真实外键完整保留；
从编排 ID 可以查清整轮所有关键业务对象；
从业务对象可以反查相关编排；
不透明 business_request_key 保证业务对象幂等；
崩溃后可以补写关联而不重复生成业务对象；
异步步骤可以 WAIT 和幂等恢复；
订单提交在任何恢复路径都不重试；
真实交易权限关闭时不创建订单链路和 ActiveLock；
自动账户边界快照在编排起始阶段形成；NO_TARGET_CHANGE / NO_TRADE 不创建 PriceSnapshot 或订单链路；
业务阻断、无动作、未知和系统失败语义不混淆；
编排层不访问 Binance、不修改业务事实、不释放 ActiveLock；
所有流程、映射、版本和关联可审计。
```

## 47. 当前不包含的能力

```text
后台动态拖拽交易步骤；
无版本热修改 Registry；
用户自定义任意交易流程；
多策略组合编排；
跨交易所编排；
通过大模型决定下一步骤；
编排层实现业务补偿算法；
编排层直接提交、查询或撤销订单；
编排层直接修改业务表或 ActiveLock；
把 ObjectLink 当作业务外键来源；
全量复制所有业务子记录到关联表。
```
