# Notifications 需求

## 1. 模块定位

Notifications 是系统事件记录与通知投递模块。

本模块拥有 `AlertEvent`，负责保存系统事件、交易事件、异常事件和配置权限事件，并根据通知规则异步投递到 Hermes 等外部通知通道。

核心定位：

```text
事件事实记录；
通知路由；
通知投递；
投递状态追踪；
投递失败重试；
去重、冷却和限频；
脱敏和消息模板；
为 OpsConsole 和 RuntimeGuard 提供告警事实。
```

Notifications 不是：

```text
交易执行模块；
策略模块；
风控模块；
恢复模块；
配置中心；
大模型模块；
外部命令入口。
```

AlertEvent 是系统事实，不等于 Hermes 消息。

Hermes 是通知投递通道，不是交易触发器。

## 2. 核心原则

```text
所有正式交易相关事件必须先写 AlertEvent；
业务模块只写事件事实，不直接发送 Hermes；
Notifications 异步消费 AlertEvent 并投递；
MySQL 中的 pending NotificationDeliveryAttempt 是可靠投递来源，Celery 消息只负责加速唤醒；
通知投递失败不得回滚业务事实；
通知投递成功不得触发业务动作；
Hermes 不得触发交易；
AlertEvent 不得包含密钥、签名或完整外部响应；
RuntimeGuard 巡检事件必须与业务实时事件区分；
OpsConsole 只能展示和筛选 AlertEvent，不能把事件反向当作交易指令；
所有事件时间统一 UTC。
```

通知链路必须是单向的：

```text
业务模块
→ AlertEvent
→ Notifications
→ Hermes / 其他通知通道
→ 人类查看
```

禁止反向链路：

```text
Hermes / 通知消息
→ 触发交易
→ 修改业务对象
→ 释放锁
→ 恢复编排
```

## 3. 负责事项

Notifications 负责：

```text
提供 AlertEvent 写入 service；
定义统一事件字段、类型、严重级别和幂等规则；
保存 AlertEvent；
保存通知路由配置；
保存通知投递尝试；
根据事件类型和严重级别决定是否投递；
渲染脱敏中文消息；
投递 Hermes；
记录投递成功、失败、抑制和放弃状态；
对投递执行有限重试；
执行去重、冷却、限频和聚合；
为 OpsConsole 提供事件查询；
为 RuntimeGuard 提供投递状态巡检数据。
```

## 4. 不负责事项

Notifications 不负责：

```text
生成策略信号；
生成交易决策；
生成 OrderPlan；
执行 RiskCheck；
提交订单；
查询订单状态；
同步成交；
修改账户、持仓或收益；
修改 OrchestrationRun；
修改 ActiveLock；
恢复业务流程；
调用 Binance；
调用 DeepSeek；
解释是否应该交易；
根据通知回复执行任何动作；
管理真实交易运行配置。
```

业务模块负责判断“发生了什么业务事件”，Notifications 只负责保存、路由和投递。

## 5. AlertEvent 定位

AlertEvent 是系统事件事实。

它用于描述：

```text
某个模块在某个时间发生了某个业务状态、异常、权限状态或审计事件。
```

AlertEvent 可以被：

```text
OpsConsole 展示；
RuntimeGuard 巡检；
AIReview 离线复盘读取；
Notifications 投递到 Hermes；
人工排查引用。
```

AlertEvent 不得被：

```text
当作交易输入；
当作订单状态来源；
当作成交事实来源；
当作 ActiveLock 释放证据；
当作真实交易运行开关变更依据；
当作自动恢复指令。
```

## 6. 必须写 AlertEvent 的事件

所有正式订单相关关键事件必须写 AlertEvent。

至少包括：

```text
OrderPlan no_order_required / blocked / failed；
CandidateOrderIntent generated / skipped / blocked；
RiskCheck ALLOW / DENY / BLOCKED / FAILED；
fallback_reduce_only selected；
ApprovedOrderIntent generated / expired / canceled；
ExecutionPreparation passed / blocked / failed；
OrderSubmissionAttempt accepted / rejected / unknown / blocked_before_submit / failed_before_submit；
OrderStatusSync NEW / PARTIALLY_FILLED / FILLED / CANCELED / REJECTED / EXPIRED / EXPIRED_IN_MATCH / polling_timeout；
TradeFill recorded；
OrderFillSummary synced / synced_empty / incomplete / unknown；
BinancePositionSnapshot changed；
ActiveLock released / failed / manual_finalized；
real trading runtime permission changed；
RuntimeGuardIssue created / reminded / resolved；
PerformanceMetrics calculated / insufficient_snapshot / failed；
AIReview requested / failed / completed；
Notifications delivery failed / abandoned。
```

非交易模块的严重异常也必须写 AlertEvent，例如：

```text
数据质量阻断；
回补失败；
账户同步失败；
价格快照失败；
配置安全异常；
外部服务长期不可用；
密钥配置缺失；
真实交易权限配置不可读取。
```

## 7. 默认不写正式 AlertEvent 的事件

以下事件默认不写正式 AlertEvent，除非达到模块自己的阈值：

```text
普通查询成功；
普通页面查看；
debug 级内部日志；
单次非关键缓存 miss；
正常无交易信号；
策略正常无动作；
dry-run 预览。
```

dry-run 如需要记录，必须明确：

```text
is_dry_run = true；
delivery_enabled = false；
不得进入正式交易通知通道。
```

## 8. 事件类型与分类

AlertEvent 必须记录稳定事件类型。

建议分类：

```text
trade_lifecycle
risk_control
execution
tracking
runtime_guard
safety_control
account_sync
price_snapshot
performance
ai_review
data_pipeline
notification_delivery
system_security
ops_action
```

事件类型必须是稳定枚举或稳定字符串，不得使用自由文本代替。

示例：

```text
order_plan_blocked
risk_check_denied
execution_preparation_blocked
order_submission_unknown
order_status_terminal_confirmed
fill_sync_incomplete
active_lock_manual_finalized
runtime_guard_issue_created
safety_order_submission_disabled
notification_delivery_failed
```

## 9. 严重级别

AlertEvent 至少支持：

```text
info
warning
high
critical
```

语义：

```text
info：
  普通业务状态或重要里程碑。

warning：
  需要关注但未直接威胁订单安全。

high：
  可能影响交易链路、资金安全、数据可信度或人工处理。

critical：
  订单不确定、锁阻断、真实交易安全、密钥异常、严重投递异常等必须尽快关注的问题。
```

严重级别只影响展示、路由和提醒，不改变业务对象状态。

## 10. AlertEvent 字段

AlertEvent 至少包含：

```text
id
event_key
source_module
event_type
event_category
severity
title_zh
message_zh
business_status
reason_code
reason_message
related_object_type
related_object_id
related_object_label
correlation_key
dedupe_key
cooldown_key
trace_id
event_time_utc
payload_summary
evidence_refs
is_dry_run
delivery_enabled
created_at_utc
```

规则：

```text
event_key 必须幂等；
source_module 必须明确；
related_object_type / id 必须指向真实业务对象或审计对象；
payload_summary 必须脱敏且大小受控；
evidence_refs 只保存对象引用、hash 或短摘要；
trace_id 只用于技术追踪，不作为业务外键、幂等键或编排归属依据；
时间字段必须使用 UTC。
```

AlertEvent 不直接保存 orchestration_run_id 或 orchestration_step_run_id。编排层必须通过 OrchestrationBusinessObjectLink 以 `object_role = audit` 关联 AlertEvent；Notifications 不得要求业务模块为了写事件而读取或传入编排对象。

## 11. 幂等与去重

每个业务模块写 AlertEvent 时必须提供稳定 `event_key`。

数据库必须对 `AlertEvent.event_key` 建立唯一约束。并发写入发生唯一冲突时必须读取并返回已有 AlertEvent，不得创建第二条等价事件。

`event_key` 建议由以下内容组成：

```text
source_module；
event_type；
related_object_type；
related_object_id；
business_status；
reason_code；
关键 sequence 或 state_version。
```

规则：

```text
同一 event_key 重复写入必须返回同一 AlertEvent；
不得因为 Celery 重试或编排恢复重复刷屏；
同一业务事实不得生成多条含义相同的正式 AlertEvent；
状态变化可以生成新的 AlertEvent；
重复观察同一状态应由 cooldown 或 reminder 规则控制。
```

幂等去重不得隐藏真实状态变化。

## 12. 写入时机

业务模块应在确定业务结果后写 AlertEvent。

规则：

```text
业务结果和 AlertEvent 需要一致时，应在同一数据库事务中写入；
如果外部网络请求仍在进行，不得先写成功 AlertEvent；
业务事务回滚时不得留下虚假的成功 AlertEvent；
投递失败不得回滚业务事务；
AlertEvent 写入失败时，高风险业务结果不得静默成功。
```

对于真实交易关键事件，业务模块必须保证：

```text
业务事实已保存；
AlertEvent 已保存或失败已被明确记录；
调用方能看到通知记录状态。
```

### 12.1 AlertEvent 到投递任务的可靠交接

对 `delivery_enabled = true` 的 AlertEvent，Notifications 必须在保存 AlertEvent 的同一数据库事务中完成路由解析，并为每条匹配的外部路由创建首个：

```text
NotificationDeliveryAttempt.status = pending
attempt_sequence = 1
```

如果没有匹配的外部路由、事件仅允许后台展示、处于冷却或外部投递被关闭，应在同一事务中创建 NotificationSuppression 或等价的明确路由结果，不得让事件处于“无法判断是否需要投递”的空白状态。

事务提交后可以发送 Celery 唤醒消息，但 Celery 消息不是唯一投递事实。即使进程在事务提交后、发送 Celery 消息前崩溃，worker 仍必须能够从 MySQL 扫描并认领 pending DeliveryAttempt。

禁止：

```text
只保存 AlertEvent，依赖一次 Celery 消息决定是否投递；
把 Redis 或 Celery broker 作为唯一待投递事实；
因为唤醒消息丢失而永久漏投；
在数据库事务提交前调用 Hermes。
```

## 13. 脱敏与大小限制

AlertEvent 和通知消息不得包含：

```text
Binance API key；
Binance secret；
DeepSeek API key；
signature；
Authorization header；
Cookie；
认证 token；
数据库密码；
Redis 密码；
Webhook secret；
完整 request header；
完整外部响应；
完整大体积 raw_payload；
不可控长文本。
```

允许包含：

```text
symbol；
side；
quantity；
price；
order_id；
client_order_id；
business object id；
status；
reason_code；
脱敏 error_code；
脱敏 error_message；
trace_id；
短摘要；
hash。
```

如果脱敏失败：

```text
不得创建可投递事件；
必须返回 write_blocked 或 equivalent；
必要时写本地结构化安全日志；
不得把原始敏感内容写入 AlertEvent。
```

## 14. AlertEvent 与业务对象状态

AlertEvent 不能替代业务对象状态。

例如：

```text
order_submission_unknown AlertEvent
不等于 OrderSubmissionAttempt.status。

fill_sync_incomplete AlertEvent
不等于 FillSyncResult.status。

runtime_guard_issue_created AlertEvent
不等于原业务对象失败。
```

查询真实业务状态必须读取对应业务对象。

OpsConsole 可以把 AlertEvent 与业务对象一起展示，但必须标明事件来源。

## 15. 通知路由

Notifications 必须根据事件配置决定是否投递。

路由条件至少支持：

```text
source_module
event_category
event_type
severity
is_dry_run
delivery_enabled
environment
```

路由结果至少包含：

```text
channel
template_code
template_version
priority
cooldown_policy
retry_policy
enabled
```

当前通道至少支持：

```text
hermes
```

可以预留：

```text
console_only
log_only
```

`console_only` 表示只进入 OpsConsole，不外部投递。

## 16. Hermes 投递边界

Hermes 是通知通道。

Notifications 可以向 Hermes 发送：

```text
交易链路状态；
关键异常；
RuntimeGuard 巡检问题；
真实交易运行开关变更；
投递系统异常；
复盘任务结果。
```

Hermes 不得：

```text
触发交易；
触发撤单；
触发订单重试；
释放 ActiveLock；
修改真实交易运行开关；
修改 OrchestrationRun；
修改任何业务事实；
调用 Binance；
调用 DeepSeek；
接受自然语言命令执行系统动作。
```

如果未来需要入站命令，必须另行设计独立的人工审批和权限系统，不属于 Notifications。

## 17. NotificationDeliveryAttempt

Notifications 必须记录每次投递尝试。

建议模型：

```text
NotificationDeliveryAttempt
```

至少包含：

```text
id
delivery_attempt_key
alert_event_id
channel
route_code
template_code
template_version
route_config_hash
template_hash
delivery_status
attempt_sequence
provider_idempotency_key
provider_message_id
request_sent
http_status
provider_error_code
error_code
error_message
retryable
next_retry_at_utc
claimed_at_utc
started_at_utc
finished_at_utc
duration_ms
sanitized_request_summary
sanitized_response_summary
trace_id
created_at_utc
```

投递尝试不得保存完整 Webhook URL、完整 secret、完整 header 或完整 provider 响应。

数据库唯一约束至少包括：

```text
delivery_attempt_key unique
(alert_event_id, route_code, channel, attempt_sequence) unique
```

同一 AlertEvent 可以匹配多条不同路由，但同一路由的同一 attempt_sequence 只能存在一条记录。

### 17.1 投递资格抢占

worker 投递前必须：

```text
开启短数据库事务；
select_for_update 锁定 NotificationDeliveryAttempt；
确认 delivery_status = pending；
确认没有同一路由更早的未完成尝试；
将状态推进为 sending 并记录 claimed_at_utc；
提交事务；
事务提交后才调用 Hermes。
```

Hermes 返回后，在新的数据库事务中锁定同一 DeliveryAttempt，并保存 sent / failed / unknown / abandoned。

重复 Celery 消息、重复扫描或并发 worker 发现 attempt 已不是 pending 时，只返回已有状态，不得再次调用 Hermes。不得在持有数据库长事务或行锁时等待外部网络响应。

## 18. 投递状态

DeliveryAttempt 至少支持：

```text
pending
sending
sent
failed
suppressed
abandoned
unknown
```

含义：

```text
pending：
  等待投递。

sending：
  worker 正在投递。

sent：
  外部通道确认接收。

failed：
  本次投递失败，可能后续重试。

suppressed：
  因冷却、限频、重复或路由规则被抑制。

abandoned：
  达到最大重试次数或不可重试错误后放弃投递。

unknown：
  请求可能已发送但无法确认通道是否接收。
```

投递状态不改变 AlertEvent 事实本身。

## 19. 投递重试

Notifications 可以对投递失败执行有限重试。

允许重试：

```text
临时网络错误；
provider 5xx；
provider 限频后的延迟重试；
可证明请求未被通道接收的连接错误。
```

禁止无限重试。

禁止重试：

```text
Webhook 配置缺失；
认证失败；
签名失败；
消息内容非法；
消息过大；
敏感内容阻断；
目标通道明确拒绝且不可重试；
达到最大重试次数。
```

规则：

```text
重试只针对通知投递；
重试不得触发业务模块重跑；
重试不得重新提交订单；
重试不得重新创建 AlertEvent；
只有上一条 DeliveryAttempt 明确为 failed 且 retryable=true 时，才能创建下一条 attempt_sequence；
每次重试创建新的 DeliveryAttempt，既有 attempt 的历史结果不得被覆盖；
创建下一次 attempt 时必须锁定同一 AlertEvent 和 route，按唯一约束只创建一条；
必须记录 attempt_sequence；
必须指数退避或等价冷却。
```

`unknown` 表示通知可能已经被通道接收。当前阶段不得自动重试 unknown，也不得把 stale sending 自动改回 pending 后再次发送。只有未来通道提供可靠 provider idempotency 且另有明确需求时，才可以设计 unknown 的受控恢复。

## 20. 冷却、聚合与限频

Notifications 必须避免告警刷屏。

至少支持：

```text
dedupe_key；
cooldown_key；
cooldown_seconds；
max_deliveries_per_window；
aggregation_window_seconds。
```

规则：

```text
同一 cooldown_key 在冷却期内可以继续保存 AlertEvent；
冷却期内可抑制外部投递；
抑制必须记录 suppressed 状态；
critical 事件可以配置更短冷却或绕过普通冷却；
RuntimeGuard 重复提醒必须按提醒间隔，不得每次巡检都外部投递。
```

保存事件事实和外部投递频率必须分离。

## 21. 模板与消息内容

Notifications 必须使用受控模板渲染外部消息。

消息默认使用中文。

交易相关通知必须明确区分：

```text
系统分析；
策略信号；
目标仓位决策；
订单计划；
候选订单意图；
风控结果；
审批通过订单意图；
执行前检查；
交易所订单；
真实成交；
仓位变化；
复盘结论。
```

禁止写成模糊喊单。

例如不得把：

```text
RiskCheck ALLOW
```

写成：

```text
建议立刻买入。
```

必须写成：

```text
风控审批通过候选订单意图，等待执行前检查。
```

## 22. RuntimeGuard 巡检事件

RuntimeGuard 写入的 AlertEvent 必须明确标记：

```text
source_module = runtime_guard
event_category = runtime_guard
title_zh 包含 [RuntimeGuard] 或等价标识
```

RuntimeGuard Alert 表示巡检发现的问题，不等于业务模块刚刚实时失败。

OpsConsole 展示时必须区分：

```text
业务模块实时事件；
RuntimeGuard 巡检事件；
通知投递事件。
```

## 23. 投递系统自监控

Notifications 必须为投递异常提供可巡检状态。

RuntimeGuard 可以巡检：

```text
DeliveryAttempt 长时间 pending；
DeliveryAttempt 长时间 sending；
delivery_enabled AlertEvent 缺少对应 pending DeliveryAttempt 或 Suppression；
连续 delivery failed；
连续 abandoned；
unknown delivery 长期未收尾；
路由配置缺失；
Hermes 通道不可用。
```

RuntimeGuard 不替 Notifications 投递消息，不修改 DeliveryAttempt，不直接调用 Hermes。

### 23.1 通知系统自身故障防递归

每一次 Hermes 投递失败只保存对应 NotificationDeliveryAttempt，不为每次重试失败继续创建新的 AlertEvent。

只有以下重要节点可以生成通知系统内部 AlertEvent：

```text
同一路由首次失败；
连续失败达到正式阈值；
达到最大次数并 abandoned；
Hermes 通道被确认长期不可用。
```

这些内部事件必须：

```text
event_category = notification_delivery；
使用稳定 event_key、dedupe_key 和 cooldown_key；
默认 delivery_enabled = false；
路由结果固定为 console_only；
只进入 MySQL、OpsConsole 和 RuntimeGuard 巡检；
不得再次投递到产生故障的同一个 Hermes 通道。
```

RuntimeGuard 针对 Notifications 故障创建的巡检 AlertEvent 也必须遵守同一规则。当前只有 Hermes 一个外部通道时，系统必须接受“通道故障只能在后台查看”，不能通过递归重试假装已经通知到人。

未来增加独立备用通道后，通知系统内部故障事件只允许路由到与故障通道不同且状态健康的备用通道，仍不得回投原故障通道。

## 24. 服务入口

Notifications 必须提供明确 service。

### 24.1 写入 AlertEvent

语义接口：

```text
record_alert_event(
    event_key,
    source_module,
    event_type,
    severity,
    related_object_ref,
    title_zh,
    message_zh,
    reason_code,
    payload_summary,
    evidence_refs,
    trace_id,
)
```

要求：

```text
执行幂等检查；
执行字段校验；
执行脱敏检查；
保存 AlertEvent；
在同一事务中解析路由；
为每条匹配外部路由创建唯一 pending DeliveryAttempt，或创建明确 Suppression；
返回 AlertEvent。
```

### 24.2 调度投递

语义接口：

```text
enqueue_notification_delivery(alert_event_id, trace_id)
```

要求：

```text
确认 AlertEvent 已存在 pending DeliveryAttempt 或明确 Suppression；
在数据库事务提交后发送 Celery 唤醒消息；
唤醒失败时保留 pending 事实，等待 worker 扫描恢复；
不得同步等待 Hermes 成功。
```

### 24.3 执行投递

语义接口：

```text
deliver_notification_attempt(delivery_attempt_id, trace_id)
```

要求：

```text
按投递资格抢占合同锁定并认领 pending DeliveryAttempt；
渲染模板；
调用 Hermes channel；
保存 sent / failed / unknown / abandoned；
不得改变业务对象。
```

### 24.4 查询事件

语义接口：

```text
query_alert_events(filters, pagination)
```

用于 OpsConsole、RuntimeGuard 和 AIReview。

查询接口只能读取，不得产生投递副作用。

## 25. 数据模型

本模块拥有：

```text
AlertEvent
NotificationRoute
NotificationDeliveryAttempt
NotificationTemplate
NotificationSuppression
```

实际模型名可以在实现计划中调整，但必须覆盖这些业务含义。

## 26. NotificationRoute

NotificationRoute 表示事件到通道的路由规则。

至少记录：

```text
id
route_code
route_version
source_module
event_category
event_type
min_severity
channel
template_code
template_version
enabled
cooldown_seconds
max_attempts
retry_policy
route_hash
created_at_utc
updated_at_utc
```

规则：

```text
路由变更必须审计；
已用于投递的 route_version / route_hash 不得被原地改写；
生产路由不得由普通用户随意修改；
路由禁用只影响后续投递，不删除 AlertEvent。
```

数据库必须保证 `(route_code, route_version)` 唯一。路由条件、模板版本、重试或冷却策略发生变化时创建新版本。

## 27. NotificationTemplate

NotificationTemplate 表示外部消息模板。

至少记录：

```text
template_code
template_version
channel
language
title_template
body_template
max_length
enabled
template_hash
updated_at_utc
```

模板渲染必须：

```text
只使用脱敏字段；
控制长度；
缺少字段时 fail-closed 或使用安全占位；
不得读取任意模型字段或执行任意代码。
```

数据库唯一约束：

```text
(template_code, template_version) unique
```

已用于 DeliveryAttempt 的模板版本不得原地覆盖。模板内容变化必须创建新版本，使历史 template_hash 对应的消息能够复现。

## 28. NotificationSuppression

NotificationSuppression 记录冷却、聚合或限频导致的外部投递抑制。

至少记录：

```text
id
alert_event_id
suppression_type
dedupe_key
cooldown_key
window_start_utc
window_end_utc
reason_code
created_at_utc
trace_id
```

抑制只影响外部投递，不删除 AlertEvent。

## 29. 与业务模块的关系

业务模块必须按自身合同写 AlertEvent。

规则：

```text
业务模块不直接发送 Hermes；
业务模块不实现投递重试；
业务模块不维护通知限频计数；
业务模块必须提供稳定 event_key；
业务模块必须提供脱敏 message_zh 和 payload_summary；
业务模块必须区分业务状态和通知状态。
```

Gateway 类基础模块通常不写业务 AlertEvent，由调用方根据业务语义写事件。

## 30. 与 OpsConsole 的关系

OpsConsole 可以：

```text
查询 AlertEvent；
筛选 severity、source_module、event_type；
查看 DeliveryAttempt；
查看投递失败原因；
查看抑制原因；
跳转相关业务对象；
查看 RuntimeGuard 巡检事件。
```

OpsConsole 不得：

```text
根据 AlertEvent 触发交易；
根据 AlertEvent 释放锁；
根据 AlertEvent 恢复编排；
直接重发业务事件；
直接调用 Hermes；
编辑 AlertEvent 原始事实。
```

如允许人工重试通知投递，必须只重试 NotificationDeliveryAttempt，不得重放业务模块。

## 31. 与 RuntimeGuard 的关系

RuntimeGuard 可以读取 Notifications 的正式状态。

RuntimeGuard 可巡检：

```text
AlertEvent 投递卡住；
应投递 AlertEvent 缺少 DeliveryAttempt 或 Suppression；
DeliveryAttempt 连续失败；
Notifications worker 停止；
Hermes 通道长期不可用；
关键 AlertEvent 长期未投递。
```

RuntimeGuard 只能创建自己的 RuntimeGuardIssue 和 AlertEvent。

RuntimeGuard 不得：

```text
替 Notifications 投递；
修改 DeliveryAttempt；
直接调用 Hermes；
删除 AlertEvent；
关闭通知路由。
```

## 32. 与 AIReview 的关系

AIReview 可以读取 AlertEvent 和 DeliveryAttempt 摘要作为离线复盘输入。

AIReview 不得：

```text
根据告警自动修改策略；
根据告警自动恢复交易；
根据告警自动变更通知路由；
根据告警自动触发 Hermes。
```

AIReview 生成的复盘报告和建议本身也可以写 AlertEvent，但必须明确标识为离线复盘事件。

## 33. 与真实交易运行开关的关系

真实交易运行开关变更必须写 AlertEvent。

Notifications 外部投递失败不得阻止关闭真实交易运行权限。

如果开启真实交易运行开关时 AlertEvent 写入失败：

```text
本次开启操作必须 fail-closed 或返回高风险失败；
不得在缺少审计和事件记录时静默恢复高风险权限。
```

## 34. 配置

所有配置必须进入 `.env.example` 并带中文注释。

建议配置：

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
Webhook secret 不得进入数据库；
Webhook URL 返回前端时必须脱敏；
AlertEvent 正式事实记录没有运行时关闭开关；
关闭外部投递时仍保存 AlertEvent，并记录 console_only / delivery_disabled Suppression；
只关闭 worker 时仍保存 AlertEvent 和 pending DeliveryAttempt；
worker 恢复后可以从 MySQL 继续认领 pending DeliveryAttempt；
配置缺失时必须 fail-closed 到 console_only 或 delivery disabled。
```

禁止使用任何总开关同时关闭 AlertEvent 写入和外部投递。真实交易权限和审计事件在外部投递关闭时仍必须正常写入 MySQL。

## 35. 数据库、Redis 与外部服务

```text
读 MySQL：是，读取 AlertEvent、路由、模板和投递记录。
写 MySQL：是，保存 AlertEvent、DeliveryAttempt、Suppression 和审计。
访问 Redis：可用于短期限频、冷却和 worker 防重复，不作为唯一事件事实。
访问 Binance：否。
访问 DeepSeek：否。
发送 Hermes：是，仅作为通知投递。
调用大模型：否。
涉及交易执行：否。
允许真实交易：否。
```

MySQL 是 AlertEvent 和投递状态的正式事实来源。

Redis 不可用时不得丢失 AlertEvent。

## 36. Management command 与 Celery task

允许提供：

```text
扫描和认领 pending DeliveryAttempt 的 Celery task；
重试 failed DeliveryAttempt 的 Celery task；
查看通知队列状态 command；
为 failed 且 retryable 的 DeliveryAttempt 创建下一次尝试的受控 command；
通知健康检查 command。
```

task 和 command 只能：

```text
解析参数；
生成或传递 trace_id；
调用 Notifications service；
输出结构化摘要。
```

task 和 command 不得：

```text
直接修改业务对象；
直接提交订单；
直接恢复编排；
直接释放锁；
绕过脱敏发送消息；
绕过路由规则发送 Hermes。
```

Celery 定时扫描只能扫描 pending DeliveryAttempt，不得重新路由并重复创建 attempt。人工命令不得重发 sent、sending、unknown、suppressed 或 abandoned 记录。

## 37. 异常处理

异常处理规则：

```text
AlertEvent 字段非法 → 拒绝写入；
敏感内容命中 → 拒绝写入或清洗后写入；
event_key 重复 → 返回已有事件；
路由缺失 → 保存 AlertEvent，投递状态为 suppressed 或 console_only；
模板缺失 → DeliveryAttempt failed；
Hermes 配置缺失 → DeliveryAttempt failed 或 suppressed；
Hermes 超时 → DeliveryAttempt failed / unknown；
Hermes 认证失败 → abandoned；
provider 5xx → failed 并按策略重试；
达到最大重试次数 → abandoned；
Redis 不可用 → 降级为 MySQL 幂等和保守限频。
```

投递异常不得改变相关业务对象状态。

## 38. 测试要求

至少覆盖：

```text
1. 业务模块写入 AlertEvent 后不会同步等待 Hermes。
2. 相同 event_key 重复写入返回同一 AlertEvent。
3. AlertEvent 不包含 API key、secret、signature 或认证 header。
4. dry-run 事件默认不投递 Hermes。
5. critical 交易事件可以路由到 Hermes。
6. info 事件可以仅 console_only。
7. Hermes 投递成功保存 sent。
8. Hermes 投递失败保存 failed。
9. 达到最大重试次数后保存 abandoned。
10. 请求可能已发送但结果不明时保存 unknown。
11. 冷却期内重复事件保存 AlertEvent 但抑制外部投递。
12. RuntimeGuard 事件带有巡检来源标识。
13. OpsConsole 可以按 source_module、severity 和 event_type 查询。
14. OpsConsole 不能通过 AlertEvent 触发业务动作。
15. 通知重试不会重放业务模块。
16. 通知投递失败不会回滚订单提交事实。
17. 真实交易运行开关开启事件写入失败时不得静默放行。
18. 模板渲染只能使用脱敏字段。
19. Redis 不可用时 AlertEvent 仍保存到 MySQL。
20. Hermes secret 不会返回前端。
21. AIReview 可以读取脱敏 AlertEvent 摘要。
22. RuntimeGuard 可以巡检 DeliveryAttempt 卡住。
23. Notifications 不访问 Binance Gateway。
24. Notifications 不调用 DeepSeek。
25. Notifications 不提交订单、不释放 ActiveLock。
26. AlertEvent 与首个 pending DeliveryAttempt 或明确 Suppression 在同一事务中保存。
27. AlertEvent 提交后 Celery 唤醒丢失时，worker 能从 MySQL 扫描并完成投递。
28. event_key 数据库唯一，并发重复写入只产生一条 AlertEvent。
29. 同一事件、路由、通道和 attempt_sequence 数据库唯一。
30. 重复 Celery 消息或并发 worker 最多一次调用 Hermes。
31. failed 且 retryable 才能创建下一条 attempt_sequence，旧 attempt 不被覆盖。
32. unknown 和 stale sending 不自动重试。
33. 通知系统自身失败事件默认 console_only，不回投故障 Hermes 通道。
34. 单次投递重试失败不继续生成新的 AlertEvent。
35. 外部投递关闭时 AlertEvent 仍保存，并记录明确 Suppression。
36. worker 关闭时 pending DeliveryAttempt 仍保存，恢复后可继续认领。
37. 正式 AlertEvent 写入没有可关闭总开关。
38. 交易事件清单使用 OrderSubmissionAttempt、OrderStatusSyncRecord、TradeFill、OrderFillSummary 和 BinancePositionSnapshot，不为通知额外引入新的交易业务对象。
39. AlertEvent 不直接保存 orchestration_run_id 或 step_run_id，由 OrchestrationBusinessObjectLink 关联。
40. DeliveryAttempt 冻结 route_hash 和 template_hash，后续配置变更不改写历史。
41. RuntimeGuard 能发现应投递事件缺少 DeliveryAttempt / Suppression 的异常。
```

## 39. 验收标准

满足以下条件才算通过：

```text
AlertEvent 是统一事件事实；
业务模块只写 AlertEvent，不直接发送 Hermes；
Hermes 只是外部通知通道；
通知不会触发交易或恢复；
所有正式交易关键事件都有 AlertEvent；
事件字段、severity、event_type 和 source_module 稳定；
event_key 幂等；
AlertEvent 与首个 pending DeliveryAttempt 或明确 Suppression 在同一事务中形成可靠交接；
MySQL pending DeliveryAttempt 是可靠投递来源，Celery 消息丢失不会造成永久漏投；
投递资格通过行锁和唯一约束抢占，并发 worker 不会重复发送；
投递状态可追踪；
投递失败可有限重试；
unknown 投递不自动重发；
投递失败不回滚业务事实；
通知系统自身故障不会回投同一故障通道形成递归；
关闭外部投递或 worker 不会关闭 AlertEvent 正式事实记录；
冷却和限频能避免刷屏；
RuntimeGuard 巡检事件与业务实时事件可区分；
敏感信息不进入事件、投递、日志或前端；
OpsConsole 可查询但不能把事件当作指令；
AlertEvent 通过 OrchestrationBusinessObjectLink 归入编排，不直接保存编排编号；
测试使用 fake Hermes 或 mock channel。
```

## 40. 当前不包含的能力

```text
Hermes 入站命令；
根据通知回复执行系统动作；
短信、电话、邮件多通道复杂路由；
复杂值班排班；
多租户通知；
外部工单系统自动创建；
让大模型生成通知内容；
通知内容自动触发策略变更；
通知内容自动触发交易。
```

## 41. 最终结论

Notifications 的最终定位是：

```text
系统事件事实与外部通知投递模块。
```

一句话：

```text
业务模块写 AlertEvent，Notifications 异步投递 Hermes；通知只负责让人知道发生了什么，永远不负责让系统去交易或修复。
```
