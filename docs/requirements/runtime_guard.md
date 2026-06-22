# RuntimeGuard 需求

## 1. 模块定位

RuntimeGuard 是自动编排主链路的独立运行巡检模块，负责定期发现漏跑、卡住、步骤产物缺失、长期不确定状态和静默异常，并保存巡检问题、写 `AlertEvent`、标记是否需要人工处理。

RuntimeGuard 不是交易主流程，也不是自动修复服务。

RuntimeGuard 不跟随某一轮编排一起执行。

它必须作为独立定时巡检运行：

```text
Celery Beat / 定时调度
→ RuntimeGuard task
→ RuntimeGuard application service
→ 只读检查自动编排主链路事实
→ 写 RuntimeGuardRun / RuntimeGuardIssue / AlertEvent
```

核心边界：

```text
发现问题；
记录问题；
更新问题的持续时间和证据；
发送明确的巡检异常事件；
不修改被巡检业务对象；
不触发业务补跑或交易恢复。
```

## 2. 核心目标

本模块必须：

```text
每 10 分钟执行一次运行巡检；
发现自动编排漏跑；
发现 OrchestrationRun 长时间 running 或 waiting；
发现 OrchestrationStepRun 长时间 running 或 waiting；
发现编排步骤成功但缺少应有业务产物；
发现主链路 MarketSnapshot 缺失或未绑定；
发现主链路 PriceSnapshot 缺失、重复或未绑定；
发现订单链路在提交前的关键阶段长期断裂；
发现 OrderPlanActiveLock 长时间 active；
发现订单提交长期 submitting 或 unknown；
发现订单状态长期无法确认；
发现成交同步长期不完整或无法确认；
发现自动账户边界同步缺失、长期失败或过期；
发现 AlertEvent 投递异常；
对同一问题幂等创建 RuntimeGuardIssue；
避免重复问题和重复告警刷屏；
保留人工确认和处理所需证据。
```

## 3. 负责事项

RuntimeGuard 负责：

```text
创建 RuntimeGuardRun；
执行各类只读巡检器；
创建或更新 RuntimeGuardIssue；
计算 issue_key；
保存首次发现、最近发现、出现次数和脱敏证据；
设置 severity 和 needs_manual_attention；
写带有明确巡检语义的 AlertEvent；
提供问题查询和人工状态管理入口；
记录自身运行失败和检查项失败。
```

## 4. 不负责事项

RuntimeGuard 不得：

```text
创建、恢复或补跑 OrchestrationRun；
修改 OrchestrationRun 或 OrchestrationStepRun 状态；
调用业务模块继续执行编排步骤；
下单、补单、重试订单提交或撤单；
查询 Binance 订单或成交以推断业务结果；
修改 OrderSubmissionAttempt；
修改 OrderStatusSyncRecord；
修改 FillSyncResult、TradeFill 或 OrderFillSummary；
生成或修改 BinancePositionSnapshot；
直接修改 OrderPlanActiveLock；
调用 OrderPlanActiveLockService 解锁或标记失败；
创建 BinanceSyncRun 或账户事实快照；
根据账户余额或持仓倒推订单结果；
把 unknown、not_found、incomplete 或超时解释为成功或失败；
改变真实交易运行配置、运行模式、市场域或账户域；
巡检后台人工复盘、后台一键绩效补算或普通后台页面功能；
调用大模型；
直接发送 Hermes 消息。
```

业务对象的恢复、收尾或人工对账必须进入该对象所属模块的受控入口。RuntimeGuard 只提供问题和证据，不触发这些入口。

## 5. 运行频率

默认每 10 分钟运行一次。

RuntimeGuard 不依赖 4 小时 K 线边界，也不等待行情数据刷新。

所有调度、阈值和时间比较统一使用 UTC。服务器本地时区、用户时区和运行机器时区不得参与判断。

## 6. 巡检范围

必须覆盖：

```text
orchestration_run_missing
orchestration_run_stale_running
orchestration_run_stale_waiting
orchestration_step_stale_running
orchestration_step_stale_waiting
orchestration_step_output_missing
market_snapshot_missing
market_snapshot_unbound
price_snapshot_missing
price_snapshot_duplicate
price_snapshot_unbound
order_chain_pre_submission_stale
active_lock_stale
order_submission_stale_submitting
order_submission_unknown_unresolved
order_status_unresolved
fill_sync_stale_syncing
fill_sync_incomplete_unresolved
fill_sync_unknown_unresolved
account_sync_stale
account_sync_failure_unresolved
alert_dispatch_stale
alert_dispatch_failed_excessive
```

每类巡检都必须产生结构化检查结果，不得依赖异常消息文本判断问题类型。

## 7. 自动编排漏跑

自动编排计划使用 UTC：

```text
four_hour_boundary：04:05、08:05、12:05、16:05、20:05 UTC；
daily_boundary：00:05 UTC。
```

对于每个计划时间，RuntimeGuard 必须按以下自动运行身份查找 `OrchestrationRun`：

```text
pipeline_code
scheduled_for_utc
cycle_kind
trigger_mode = automatic
```

计划时间超过 15 分钟仍不存在对应 `OrchestrationRun` 时：

```text
issue_type = orchestration_run_missing；
severity = error；
needs_manual_attention = true；
创建或更新 RuntimeGuardIssue；
写 [RuntimeGuard] 巡检异常 AlertEvent。
```

RuntimeGuard 不得创建缺失的 `OrchestrationRun`，不得补跑业务流程。

人工诊断运行不能满足自动运行身份，也不能用于关闭漏跑问题。

## 8. 编排长时间未结束

`OrchestrationRun.status` 为以下状态且持续超过 30 分钟时，必须记录问题：

```text
running → orchestration_run_stale_running；
waiting → orchestration_run_stale_waiting。
```

证据至少包括：

```text
orchestration_run_id
pipeline_code
scheduled_for_utc
cycle_kind
status
current_step_code
last_completed_step_code
对应 OrchestrationStepRun.id
步骤状态
waiting_since_utc
started_at_utc
trace_id
```

RuntimeGuard 不得：

```text
恢复 run；
重新执行步骤；
消费 resume_token；
把 run 标记为 completed、failed 或 stale_interrupted；
把长时间 waiting 推断为业务失败；
调用订单提交 Gateway。
```

`PipelineOrchestrator` 的受控恢复入口独立承担编排恢复和状态收尾。

### 8.1 编排步骤长时间未结束

`OrchestrationStepRun.status` 为以下状态且持续超过 30 分钟时，必须记录问题：

```text
running → orchestration_step_stale_running；
waiting → orchestration_step_stale_waiting。
```

证据至少包括：

```text
orchestration_run_id
orchestration_step_run_id
pipeline_code
step_code
status
started_at_utc
waiting_since_utc
last_status_updated_at_utc
reason_code
trace_id
```

RuntimeGuard 不得恢复步骤、重新执行步骤、消费 resume_token、修改 StepRun 状态或替步骤补写业务产物。

### 8.2 编排步骤产物缺失

如果自动编排中的某个 `OrchestrationStepRun` 已明确成功，但通过 `OrchestrationBusinessObjectLink` 找不到该步骤应产生的业务对象，必须记录：

```text
issue_type = orchestration_step_output_missing；
severity = error；
needs_manual_attention = true。
```

本巡检只判断“步骤结果与业务产物绑定是否一致”，不重新计算业务结果。

至少覆盖以下主链路步骤：

```text
MarketSnapshot step → MarketSnapshot；
FeatureLayer step → FeatureSet；
AtomicSignal step → AtomicSignalSet；
DomainSignal step → DomainSignalSet；
MarketRegime step → MarketRegimeSnapshot；
StrategyRouting step → StrategyRouteDecision；
StrategySignal step → StrategySignal；
DecisionSnapshot step → DecisionSnapshot；
Binance Account Sync step → BinanceSyncRun；
PriceSnapshot step → PriceSnapshot；
OrderPlan step → OrderPlan 或明确 no_order_required / 真实交易权限关闭 / skipped 结果；
RiskCheck step → RiskCheckResult；
ExecutionPreparation step → ExecutionPreparationResult；
OrderSubmission step → OrderSubmissionAttempt；
OrderStatusSync step → OrderStatusSyncRecord；
FillSync step → FillSyncResult。
```

证据至少包括：

```text
orchestration_run_id
orchestration_step_run_id
step_code
step_status
expected_object_type
found_object_count
step_result_status
step_result_reason_code
trace_id
```

RuntimeGuard 不得创建缺失业务对象，不得补写 `OrchestrationBusinessObjectLink`，不得把“产物缺失”解释为该步骤业务失败或成功。

如果某个步骤的合法结果本来就是“不产出下游交易对象”，例如真实交易权限关闭导致不进入 OrderPlan，或者 `NO_TARGET_CHANGE / NO_TRADE` 不进入 PriceSnapshot，必须以该步骤自己的结构化结果为准，不得误报为产物缺失。

每个自动四小时 OrchestrationRun 都必须存在起始阶段成功的 Binance Account Sync step 和对应 BinanceSyncRun；没有进入 PriceSnapshot 的合法无交易结果不得记录 `price_snapshot_missing`。

### 8.3 MarketSnapshot 事实异常

自动主链路需要使用的 MarketSnapshot 缺失或未与本轮自动编排绑定时，必须记录问题：

```text
market_snapshot_missing；
market_snapshot_unbound。
```

适用场景至少包括：

```text
MarketSnapshot step 成功但找不到 MarketSnapshot；
后续 FeatureLayer 已运行但本轮 MarketSnapshot 绑定缺失；
MarketSnapshot 存在但不是本轮自动 OrchestrationRun 的业务对象；
MarketSnapshot 引用的数据质量状态不允许继续，但编排仍向后运行。
```

RuntimeGuard 不得重新采集行情、不得触发 DataBackfill、不得补建 MarketSnapshot。

### 8.4 PriceSnapshot 事实异常

自动主链路进入订单链路前，如果需要价格事实但本轮 PriceSnapshot 缺失、重复或未绑定，必须记录问题：

```text
price_snapshot_missing；
price_snapshot_duplicate；
price_snapshot_unbound。
```

适用场景至少包括：

```text
PriceSnapshot step 成功但找不到本轮 PriceSnapshot；
同一自动 OrchestrationRun 绑定多个有效 PriceSnapshot；
PriceSnapshot 存在但未通过 OrchestrationBusinessObjectLink 绑定本轮自动 run；
OrderPlan、RiskCheck 或 ExecutionPreparation 已运行，但找不到本轮 PriceSnapshot 事实。
```

RuntimeGuard 不得请求 Binance Gateway，不得生成新的 PriceSnapshot，不得刷新 Redis 价格缓存。

### 8.5 下单前订单链路断裂

正式订单链路进入后，关键阶段长期没有后续结果时，必须记录：

```text
issue_type = order_chain_pre_submission_stale；
severity = error；
needs_manual_attention = true。
```

至少覆盖：

```text
CandidateOrderIntent 已生成，但超过阈值仍没有 RiskCheckResult；
RiskCheck ALLOW 后，超过阈值仍没有 ApprovedOrderIntent；
ApprovedOrderIntent 已生成，但超过阈值仍没有 ExecutionPreparationResult；
ExecutionPreparation passed 后，超过阈值仍没有 OrderSubmissionAttempt。
```

证据至少包括：

```text
orchestration_run_id
order_plan_id
candidate_order_intent_id
risk_check_result_id
approved_order_intent_id
execution_preparation_result_id
last_known_stage
last_known_status
last_status_updated_at_utc
active_lock_id
trace_id
```

RuntimeGuard 不得调用 RiskCheck、不得生成 ApprovedOrderIntent、不得执行 ExecutionPreparation、不得提交订单。

## 9. ActiveLock 长时间阻断

`OrderPlanActiveLock.status = active` 持续超过 30 分钟时：

```text
issue_type = active_lock_stale；
severity = error；
needs_manual_attention = true。
```

证据至少包括：

```text
active_lock_id
order_plan_id
exchange
market_type
account_domain
symbol
status
acquired_at_utc
最近关联订单链路对象及其状态
trace_id
```

RuntimeGuard 告警不是锁释放证据。RuntimeGuard 不得直接写锁表，也不得调用 `OrderPlanActiveLockService`。

## 10. 订单提交异常

### 10.1 submitting 卡住

`OrderSubmissionAttempt.status = submitting` 持续超过 30 分钟时：

```text
issue_type = order_submission_stale_submitting；
severity = critical；
needs_manual_attention = true。
```

RuntimeGuard 不得把 attempt 改回 `created`，不得把 attempt 改成 `unknown`，不得再次调用订单提交 Gateway。

### 10.2 unknown 长期未解决

`OrderSubmissionAttempt.status = unknown` 持续超过 30 分钟，且仍不存在可信受控对账结论时：

```text
issue_type = order_submission_unknown_unresolved；
severity = critical；
needs_manual_attention = true。
```

`unknown` 表示无法确认交易所是否收到请求。RuntimeGuard 不得重新提交、撤单、解锁或推断订单不存在。

证据至少包括：

```text
order_submission_attempt_id
prepared_order_intent_id
active_lock_id
client_order_id
status
request_sent
status_updated_at_utc
最近 OrderStatusSyncRecord.id
最近查询结果
trace_id
```

## 11. 订单状态长期未确认

OrderStatusSync 的 30 秒立即轮询结束为 `polling_timeout` 后，如果持续超过 30 分钟仍没有明确终态或受控人工结论，必须记录：

```text
issue_type = order_status_unresolved；
severity = error；
needs_manual_attention = true。
```

长期未确认至少包括以下最后证据：

```text
query_outcome = not_found；
query_outcome = unknown；
found + exchange_status = NEW；
found + exchange_status = PARTIALLY_FILLED；
found + 未识别 exchange_status。
```

证据至少包括：

```text
order_submission_attempt_id
order_status_sync_record_id
client_order_id
query_outcome
exchange_status
is_recognized_status
is_terminal_status
submission_resolution_status
polling_deadline_utc
active_lock_id
trace_id
```

`not_found` 不证明提交失败；查询 `unknown` 不证明订单不存在；`NEW` 和 `PARTIALLY_FILLED` 不是终态。以上状态均不得作为解锁或重新提交依据。

## 12. 成交同步异常

### 12.1 syncing 卡住

`FillSyncResult.status = syncing` 持续超过 30 分钟时：

```text
issue_type = fill_sync_stale_syncing；
severity = error。
```

### 12.2 incomplete 长期未解决

`FillSyncResult.status = incomplete` 持续超过 30 分钟，且不存在后续完整结果时：

```text
issue_type = fill_sync_incomplete_unresolved；
severity = error。
```

### 12.3 unknown 长期未解决

`FillSyncResult.status = unknown` 持续超过 30 分钟，且不存在后续完整结果时：

```text
issue_type = fill_sync_unknown_unresolved；
severity = error。
```

证据至少包括：

```text
fill_sync_result_id
order_submission_attempt_id
terminal_order_status_sync_record_id
status
terminal_exchange_status
order_fill_summary_id
is_complete
lock_finalization_status
active_lock_id
trace_id
```

严格成立的 `synced_empty` 是明确的零成交事实，不属于异常。RuntimeGuard 不得因为结果为 `synced_empty` 单独创建问题。

RuntimeGuard 不得补查成交、补写 `TradeFill`、重算 `OrderFillSummary`、更新持仓或释放 ActiveLock。

## 13. 自动账户边界同步异常

RuntimeGuard 只巡检：

```text
sync_purpose = trade_preparation
```

当前 active market domain 最近一次成功的自动账户边界 `BinanceSyncRun` 距当前时间超过 4 小时，或其 `expires_at_utc` 已过期且后续没有成功批次时：

```text
issue_type = account_sync_stale；
severity = warning。
```

自动账户边界同步连续失败且尚无后续成功批次时：

```text
issue_type = account_sync_failure_unresolved；
severity = error。
```

证据至少包括：

```text
binance_sync_run_id
sync_purpose
market_type
account_domain
status
as_of_utc
expires_at_utc
consecutive_failure_count
last_error_code
trace_id
```

`ops_display` 批次不满足自动账户边界同步新鲜度，也不参与交易快照可用性判断。

RuntimeGuard 不得调用 Binance Account Sync，不得创建快照，不得把过期批次重新标记为可消费，也不得回退到更早的成功批次。

## 14. AlertEvent 投递异常

RuntimeGuard 必须巡检 Notifications 持久化的投递状态，至少包括：

```text
delivery_enabled AlertEvent 缺少对应 pending NotificationDeliveryAttempt 或 NotificationSuppression；
NotificationDeliveryAttempt 长时间 pending；
NotificationDeliveryAttempt 长时间 sending；
NotificationDeliveryAttempt unknown 长期未收尾；
NotificationDeliveryAttempt 连续 failed；
NotificationDeliveryAttempt 连续 abandoned；
Notifications 路由配置缺失；
Hermes 通道长期不可用。
```

问题类型：

```text
alert_dispatch_stale；
alert_dispatch_failed_excessive。
```

其中：

```text
alert_dispatch_stale 覆盖应投递事件缺少交接记录、pending 卡住、sending 卡住、unknown 长期未收尾；
alert_dispatch_failed_excessive 覆盖连续 failed、连续 abandoned、路由配置缺失或 Hermes 通道长期不可用。
```

投递阈值由 Notifications 拥有，RuntimeGuard 读取正式配置，不维护第二套阈值语义。

如果 Notifications 投递能力不可用，RuntimeGuard 至少必须保存 `RuntimeGuardIssue` 并写结构化日志。不得因为告警投递失败回滚已经保存的问题记录。

RuntimeGuard 不得修改 `NotificationDeliveryAttempt`、不得创建新的投递尝试、不得直接调用 Hermes、不得重放业务 AlertEvent。

## 15. RuntimeGuardRun

每次巡检必须创建一条 `RuntimeGuardRun`，至少记录：

```text
id
run_key
status
started_at_utc
finished_at_utc
checked_item_count
created_issue_count
updated_issue_count
alert_event_count
error_count
reason_code
reason_message
trace_id
trigger_source
created_at_utc
updated_at_utc
```

状态只允许：

```text
running
succeeded
partial_failed
failed
```

含义：

```text
running：巡检正在执行；
succeeded：所有已启用检查项执行完成；
partial_failed：至少一个检查项失败，其余检查结果已经保存；
failed：巡检无法形成任何有效检查结果。
```

单个检查项失败不得删除其他检查项已经保存的问题。

## 16. RuntimeGuardIssue

每个问题至少记录：

```text
id
issue_key
issue_type
severity
status
first_seen_at_utc
last_seen_at_utc
occurrence_count
resolved_at_utc
related_object_type
related_object_id
related_trace_id
description
evidence
needs_manual_attention
alert_event_id
last_alerted_at_utc
acknowledged_at_utc
acknowledged_by
resolution_note
created_at_utc
updated_at_utc
```

`evidence` 只能保存结构化、脱敏、大小受控的诊断证据，不得保存密钥、签名、认证 header、完整外部响应或不可控长文本。

`RuntimeGuardIssue` 不等于相关业务对象状态。问题状态变化不得隐式修改相关对象。

## 17. RuntimeGuardIssue 状态

状态只允许：

```text
open
acknowledged
resolved
ignored
```

语义：

```text
open：问题存在且尚未确认；
acknowledged：授权人员已确认问题并正在处理或等待处理；
resolved：问题已经通过独立业务证据确认解决；
ignored：授权人员确认无需处理，并记录理由。
```

`acknowledged`、`resolved` 和 `ignored` 必须记录操作人、操作时间、原因和 `trace_id`。

把 issue 标记为 `resolved` 只关闭巡检问题，不得修改被巡检对象，也不证明订单、成交或锁已经安全结束。

## 18. issue_key 与去重

同一问题未关闭前，只能存在一条有效 `RuntimeGuardIssue`。

对象问题的 `issue_key` 至少由以下内容计算：

```text
issue_type
related_object_type
related_object_id
```

漏跑问题的 `issue_key` 至少由以下内容计算：

```text
issue_type
pipeline_code
scheduled_for_utc
cycle_kind
trigger_mode
```

账户同步问题的 `issue_key` 至少包括：

```text
issue_type
market_type
account_domain
sync_purpose
```

编排步骤问题的 `issue_key` 至少包括：

```text
issue_type
orchestration_run_id
orchestration_step_run_id
step_code
expected_object_type（如适用）
```

主链路事实问题的 `issue_key` 至少包括：

```text
issue_type
orchestration_run_id
object_type
market_type（如适用）
account_domain（如适用）
symbol（如适用）
```

下单前链路断裂问题的 `issue_key` 至少包括：

```text
issue_type
orchestration_run_id
order_plan_id
last_known_stage
last_known_object_id
```

重复巡检命中同一问题时：

```text
不得创建第二条 open 或 acknowledged issue；
更新 last_seen_at_utc；
增加 occurrence_count；
更新最新脱敏 evidence；
按照提醒间隔决定是否再次写 AlertEvent。
```

数据库必须对有效问题身份提供唯一约束或等价的事务级并发保护。

## 19. 严重级别

支持：

```text
info
warning
error
critical
```

默认映射：

| issue_type | severity |
|---|---|
| orchestration_run_missing | error |
| orchestration_run_stale_running | error |
| orchestration_run_stale_waiting | error |
| orchestration_step_stale_running | error |
| orchestration_step_stale_waiting | error |
| orchestration_step_output_missing | error |
| market_snapshot_missing | error |
| market_snapshot_unbound | error |
| price_snapshot_missing | error |
| price_snapshot_duplicate | error |
| price_snapshot_unbound | error |
| order_chain_pre_submission_stale | error |
| active_lock_stale | error |
| order_submission_stale_submitting | critical |
| order_submission_unknown_unresolved | critical |
| order_status_unresolved | error |
| fill_sync_stale_syncing | error |
| fill_sync_incomplete_unresolved | error |
| fill_sync_unknown_unresolved | error |
| account_sync_stale | warning |
| account_sync_failure_unresolved | error |
| alert_dispatch_stale | error |
| alert_dispatch_failed_excessive | error |

严重级别可以由正式配置进一步收紧，但不得把订单提交不确定、未识别订单状态或身份冲突降为 `info`。

## 20. AlertEvent

首次发现问题时必须写 `AlertEvent`。重复发现按提醒间隔发送，不得每 10 分钟持续刷屏。

标题必须包含：

```text
[RuntimeGuard] 巡检异常：
```

事件至少记录：

```text
source_module = runtime_guard
event_type
runtime_guard_run_id
runtime_guard_issue_id
issue_type
severity
detected_at_utc
related_object_type
related_object_id
related_trace_id
needs_manual_attention
trace_id
```

通知内容必须明确：

```text
这是 RuntimeGuard 巡检发现的问题；
不是原业务模块的实时结果；
RuntimeGuard 不会自动修复、下单、撤单、补跑或解锁；
需要检查的关联对象和证据。
```

RuntimeGuard 只写 `AlertEvent`，不直接调用 Hermes。Notifications 根据自己的规则处理投递。

## 21. 人工处理入口

授权人工入口可以：

```text
查询 RuntimeGuardRun；
查询和筛选 RuntimeGuardIssue；
把 issue 标记为 acknowledged；
在独立证据确认问题解决后标记为 resolved；
记录理由后标记为 ignored。
```

人工入口不得借由 RuntimeGuard：

```text
提交或撤销订单；
修改订单状态；
补写成交；
释放 ActiveLock；
修改 OrchestrationRun；
创建 BinanceSyncRun；
改变真实交易运行配置。
```

需要修复业务对象时，操作人必须进入该对象所属模块的授权入口，并留下独立审计记录。

## 22. 幂等与并发

同一计划巡检必须使用稳定 `run_key` 防止重复执行。

并发巡检必须：

```text
对同一 run_key 只创建一条有效 RuntimeGuardRun；
对同一 issue_key 只创建一条有效问题；
使用数据库唯一约束和事务处理并发创建；
重复任务读取并更新既有对象；
不得依赖 Redis 作为问题事实的唯一存储。
```

Redis 可以用于短期调度防重复锁，但 MySQL 中的 `RuntimeGuardRun` 和 `RuntimeGuardIssue` 才是正式事实。

## 23. 配置

至少支持：

```text
RUNTIME_GUARD_ENABLED
RUNTIME_GUARD_INTERVAL_SECONDS = 600
RUNTIME_GUARD_ORCHESTRATION_MISSING_GRACE_SECONDS = 900
RUNTIME_GUARD_ORCHESTRATION_STALE_SECONDS = 1800
RUNTIME_GUARD_STEP_STALE_SECONDS = 1800
RUNTIME_GUARD_OUTPUT_MISSING_GRACE_SECONDS = 300
RUNTIME_GUARD_ORDER_CHAIN_PRE_SUBMISSION_STALE_SECONDS = 1800
RUNTIME_GUARD_ACTIVE_LOCK_STALE_SECONDS = 1800
RUNTIME_GUARD_ORDER_SUBMISSION_STALE_SECONDS = 1800
RUNTIME_GUARD_ORDER_STATUS_UNRESOLVED_SECONDS = 1800
RUNTIME_GUARD_FILL_SYNC_UNRESOLVED_SECONDS = 1800
RUNTIME_GUARD_ACCOUNT_SYNC_STALE_SECONDS = 14400
RUNTIME_GUARD_REPEAT_ALERT_INTERVAL_SECONDS
```

所有配置必须进入 `.env.example` 并附中文注释。不得硬编码生产阈值。

Notifications 投递失败阈值由 Notifications 配置拥有，RuntimeGuard 读取其正式配置。

## 24. Celery task 与 management command

Celery task 只允许：

```text
接收或生成 trace_id；
设置 trigger_source = celery_beat；
调用 RuntimeGuard application service；
返回 RuntimeGuardRun 摘要。
```

Management command 只允许：

```text
解析检查范围、dry-run 和 confirm-write 参数；
接收或生成 trace_id；
设置 trigger_source = management_command；
调用 RuntimeGuard application service；
输出结构化结果。
```

命令默认 `dry-run`。写入 `RuntimeGuardRun`、`RuntimeGuardIssue` 或 `AlertEvent` 必须显式 `confirm-write`。

task 和 command 不得承载巡检规则或直接修改业务对象。

## 25. 数据与外部服务

```text
读 MySQL：是，读取自动编排、主链路业务对象、账户同步、价格快照、订单、成交、锁和告警事实；
写 MySQL：是，只写 RuntimeGuardRun、RuntimeGuardIssue 和 AlertEvent；
访问 Redis：可选，只用于短期调度防重复；
访问 Binance：否；
调用 Binance Gateway：否；
直接发送 Hermes：否；
调用大模型：否；
涉及真实交易执行：否；
允许真实交易：否；
写 AlertEvent：是。
```

## 26. 异常处理

单个巡检器异常时：

```text
记录检查项错误码和脱敏错误信息；
增加 RuntimeGuardRun.error_count；
继续执行能够安全独立运行的其他巡检器；
最终状态为 partial_failed；
不得删除已经保存的问题；
不得把“未完成检查”解释为“没有问题”。
```

数据库整体不可用、无法创建运行记录或无法形成任何有效结果时，运行状态为 `failed`，并通过结构化日志保留诊断信息。

任何异常都不得触发交易、补跑、解锁或业务状态修正。

## 27. 测试要求

至少覆盖：

1. RuntimeGuard 由独立定时任务触发，不跟随某一轮编排一起执行。
2. 每 10 分钟可以调度一次巡检。
3. 全部时间判断使用 UTC。
4. 自动计划超过 15 分钟无对应 OrchestrationRun 时创建 `orchestration_run_missing`。
5. 人工诊断 run 不能满足自动计划身份。
6. RuntimeGuard 不创建或补跑 OrchestrationRun。
7. `OrchestrationRun.running` 超过 30 分钟时创建 `orchestration_run_stale_running`。
8. `OrchestrationRun.waiting` 超过 30 分钟时创建 `orchestration_run_stale_waiting`。
9. `OrchestrationStepRun.running` 超过 30 分钟时创建 `orchestration_step_stale_running`。
10. `OrchestrationStepRun.waiting` 超过 30 分钟时创建 `orchestration_step_stale_waiting`。
11. RuntimeGuard 不恢复步骤、不消费 resume_token、不修改 run 或 step 状态。
12. StepRun 成功但缺少应有业务对象时创建 `orchestration_step_output_missing`。
13. 合法 no-order、NO_TARGET_CHANGE / NO_TRADE 或真实交易权限关闭结果不会被误报为产物缺失。
13a. 自动四小时 run 缺少起始账户边界 BinanceSyncRun 时可以发现账户边界产物缺失。
13b. NO_TARGET_CHANGE / NO_TRADE 分支没有 PriceSnapshot 时不记录价格快照缺失。
14. MarketSnapshot 缺失或未绑定本轮自动 run 时创建问题。
15. RuntimeGuard 不重新采集行情、不触发 DataBackfill、不补建 MarketSnapshot。
16. PriceSnapshot 缺失、重复或未绑定本轮自动 run 时创建问题。
17. RuntimeGuard 不请求 Binance Gateway、不生成 PriceSnapshot、不刷新 Redis 价格缓存。
18. CandidateOrderIntent 已生成但长期没有 RiskCheckResult 时创建 `order_chain_pre_submission_stale`。
19. RiskCheck ALLOW 后长期没有 ApprovedOrderIntent 时创建 `order_chain_pre_submission_stale`。
20. ApprovedOrderIntent 已生成但长期没有 ExecutionPreparationResult 时创建 `order_chain_pre_submission_stale`。
21. ExecutionPreparation passed 后长期没有 OrderSubmissionAttempt 时创建 `order_chain_pre_submission_stale`。
22. RuntimeGuard 不调用 RiskCheck、不生成 ApprovedOrderIntent、不执行 ExecutionPreparation、不提交订单。
23. ActiveLock active 超过 30 分钟时创建 `active_lock_stale`。
24. RuntimeGuard 不修改锁，也不调用锁服务。
25. OrderSubmissionAttempt submitting 超过 30 分钟时创建 critical issue。
26. submitting 巡检不会再次调用 Gateway，也不会修改 attempt。
27. OrderSubmissionAttempt unknown 超过 30 分钟时创建 critical issue。
28. unknown 巡检不会重新提交、撤单或解锁。
29. polling_timeout 持续超过 30 分钟且无终态时创建 `order_status_unresolved`。
30. not_found 不被解释为提交失败。
31. NEW、PARTIALLY_FILLED 和未识别状态不被解释为终态。
32. FillSync syncing 超过 30 分钟时创建问题。
33. FillSync incomplete 超过 30 分钟时创建问题。
34. FillSync unknown 超过 30 分钟时创建问题。
35. 严格成立的 synced_empty 不会单独创建问题。
36. RuntimeGuard 不补写 TradeFill、不重算汇总、不生成或修改 BinancePositionSnapshot。
37. trade_preparation BinanceSyncRun 超过 4 小时或过期时创建 `account_sync_stale`。
38. ops_display 批次不能满足自动账户边界同步新鲜度。
39. RuntimeGuard 不请求 Binance Account Sync。
40. delivery_enabled AlertEvent 缺少 NotificationDeliveryAttempt 或 NotificationSuppression 时创建 `alert_dispatch_stale`。
41. NotificationDeliveryAttempt pending 或 sending 超过阈值时创建 `alert_dispatch_stale`。
42. NotificationDeliveryAttempt unknown 长期未收尾时创建 `alert_dispatch_stale`。
43. NotificationDeliveryAttempt 连续 failed 或 abandoned 超过正式阈值时创建 `alert_dispatch_failed_excessive`。
44. 路由配置缺失或 Hermes 通道长期不可用时创建 `alert_dispatch_failed_excessive`。
45. RuntimeGuard 不修改 DeliveryAttempt，不创建新投递尝试，不直接调用 Hermes。
46. 告警系统不可用时，RuntimeGuardIssue 仍然保存。
47. 同一 issue_key 重复发现时只更新一条有效问题。
48. 重复巡检不会每 10 分钟重复告警。
49. 并发运行不会创建重复 RuntimeGuardRun 或 RuntimeGuardIssue。
50. issue 状态变更记录操作人、原因、时间和 trace_id。
51. 标记 issue resolved 不修改被巡检业务对象。
52. 单个巡检器失败时其他巡检结果仍然保存，运行状态为 partial_failed。
53. dry-run 不写 RuntimeGuardRun、RuntimeGuardIssue 或 AlertEvent。
54. confirm-write 只写 RuntimeGuard 自有对象和 AlertEvent。
55. 日志、evidence 和 AlertEvent 不包含密钥或完整外部响应。
56. RuntimeGuard 不巡检 AIReview、PerformanceMetrics、后台一键补算或后台人工导出。
57. RuntimeGuard 不访问 Binance Gateway、不发送 Hermes、不调用大模型。

## 28. 验收标准

满足以下条件即通过：

```text
自动编排主链路的漏跑、卡住、产物缺失、长期不确定状态和投递异常均有明确巡检规则；
OrchestrationRun、OrchestrationStepRun 和各交易对象使用正式名称与状态；
MarketSnapshot、FeatureLayer、AtomicSignal、DomainSignal、MarketRegime、StrategyRouting、StrategySignal、DecisionSnapshot、AccountSync、PriceSnapshot、OrderPlan、RiskCheck、ExecutionPreparation、Execution、OrderStatusSync、FillSync 的编排产物缺失可被发现；
订单提交前链路断裂可被发现；
后台人工能力不纳入 RuntimeGuard 巡检范围；
所有问题均保存为可去重、可确认、可关闭的 RuntimeGuardIssue；
所有首次问题均写明确标识 RuntimeGuard 的 AlertEvent；
重复巡检不会重复建问题或持续刷屏；
RuntimeGuard 只读业务事实，不修改业务对象；
RuntimeGuard 不补跑、不恢复、不下单、不撤单、不解锁；
RuntimeGuard 不访问 Binance、不发送 Hermes、不调用大模型；
所有时间使用 UTC；
所有关键行为可通过 trace_id 审计。
```

## 29. 当前不包含的能力

```text
自动修复业务状态；
自动补跑编排；
自动恢复编排步骤；
自动对账；
订单提交、撤单或重试；
订单状态或成交查询；
ActiveLock 自动释放；
账户同步；
持仓更新；
真实交易运行配置控制；
AIReview 巡检；
PerformanceMetrics 巡检；
后台一键补算巡检；
后台人工导出或后台页面巡检；
大模型异常判断。
```
