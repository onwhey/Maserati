# 运行任务架构

## 1. 文档目的

本文档定义系统在运行时如何使用 Celery、Celery Beat、PipelineOrchestrator、业务 Connector、异步等待任务和独立后台任务安全执行已经确定的业务流程。

本文档用于回答：

```text
四小时自动编排由谁触发；
一轮编排如何顺序执行多个业务模块；
哪些步骤在同一个驱动任务内执行；
等待订单状态时如何释放 worker；
任务重复投递或进程崩溃时如何恢复；
上一轮订单未结束时下一周期是否继续运行；
交易关键任务、通知和离线任务如何隔离；
哪些动作允许重试，哪些绝不能重试；
MySQL、Redis、Celery 消息和任务结果分别承担什么职责。
```

本文档不重新定义业务步骤顺序、模块状态、策略算法或交易规则。

具体业务结果和状态语义以 `docs/requirements/*.md` 为准。

具体 Celery task 函数名、queue 名称、worker 数量、并发参数、超时数值和部署拓扑在开发计划与部署阶段确定。

## 2. 运行架构总原则

运行任务必须遵守：

```text
Celery Beat 只负责按 UTC 触发任务；
Celery task 只负责传递上下文并调用 application service；
PipelineOrchestrator 只按 Registry 和统一 flow_action 推进步骤；
业务 Connector 负责调用 adapter、理解业务返回并映射统一结果；
业务 service 负责真正业务逻辑和业务事务；
MySQL 保存运行和业务最终事实；
Redis 与 Celery 消息只承担短期调度和加速能力；
一轮编排内部严格按步骤顺序执行；
不同计划周期可以存在不同 OrchestrationRun；
ActiveLock 只阻止冲突订单链，不阻止新周期生成行情、策略和账户事实；
等待异步结果时必须持久化进度并释放 worker；
任务重复投递必须通过业务幂等安全吸收；
订单提交在任何运行、恢复和重放路径都绝不重试；
所有运行时间使用 UTC。
```

## 3. 运行组件职责

### 3.1 Celery Beat

Celery Beat 负责：

```text
投递四小时和日线边界的自动编排触发任务；
投递 RuntimeGuard 独立巡检任务；
投递 Notifications pending 记录扫描任务；
投递 requirements 明确允许的其他定时入口。
```

Celery Beat 不负责：

```text
判断业务是否成功；
解释业务模块状态；
调用 Binance 或 DeepSeek；
直接写业务对象；
直接下单；
恢复卡住的业务；
释放 ActiveLock。
```

生产环境只允许一个正式活动的 Beat 调度实例。

数据库幂等仍然必须存在，不能只依赖“只有一个 Beat”防止重复运行。

### 3.2 Orchestration driver task

每个自动计划周期由一个逻辑编排驱动负责推进对应 OrchestrationRun。

同一时刻只允许一个 driver task 推进该 run。遇到 WAIT 或交易关键队列交接时，当前 driver task 结束；后续由携带原恢复信息的新 driver task 继续同一 run。因此“一轮一个驱动”表示只有一个统一推进者，不表示整个生命周期必须由同一个 Celery task 进程持续占用 worker。

驱动任务只负责：

```text
接收计划时间、周期类型、运行模式和技术追踪上下文；
调用 PipelineOrchestrator 创建或取得该周期唯一 OrchestrationRun；
从当前步骤开始顺序推进同步步骤；
遇到 WAIT 时保存等待状态并结束当前任务；
遇到 COMPLETE、STOP 或 FAIL 时保存最终状态并结束；
输出结构化运行摘要。
```

驱动任务不得实现业务模块内部规则，也不得直接访问 Gateway。

### 3.3 PipelineOrchestrator

PipelineOrchestrator 负责：

```text
创建或读取 OrchestrationRun；
冻结 Registry 与 StrategyAnalysisRelease；
创建和推进 OrchestrationStepRun；
调用 OrchestrationBusinessConnector；
保存 normalized_status 与 flow_action；
保存 OrchestrationBusinessObjectLink；
按统一结果继续、等待、完成、停止或失败。
```

它不执行策略、风控、下单、订单查询或成交同步的内部逻辑。

### 3.4 OrchestrationBusinessConnector 与 adapter

Connector 负责：

```text
根据 Registry 读取下一合法步骤；
根据真实业务依赖和已有 ObjectLink 构造明确输入；
调用对应 BusinessStepAdapter；
把业务原始结果映射为统一结果；
返回业务对象引用；
决定是否需要登记异步恢复信息。
```

adapter 只理解自己对应模块的业务返回，不把完整主流程写进单个 adapter。

### 3.5 application service

application service 负责：

```text
校验直接业务输入；
执行本模块业务规则；
调用 selector、repository、calculator 或 Gateway；
处理本模块幂等和并发；
在本模块事务中写业务对象；
写必要 AlertEvent；
返回稳定业务结果。
```

业务 service 不读取 OrchestrationRun 决定自己的业务输入。

## 4. 逻辑任务组与资源隔离

系统至少按以下逻辑职责隔离任务。

具体 Celery queue 名称在开发计划中确定，本文件只规定隔离关系。

### 4.1 编排任务组

包含：

```text
自动 OrchestrationRun 驱动；
安全的编排恢复；
数据质量与条件回补衔接；
非订单提交步骤的顺序推进。
```

该任务组不得直接下单。

### 4.2 交易关键任务组

至少包含：

```text
Execution 订单提交入口；
OrderStatusSync 定向轮询；
FillSync 成交同步和安全收尾交接。
```

要求：

```text
与 AIReview、PerformanceMetrics 等离线任务隔离；
不得因离线大模型调用、批量复盘或通知积压而无法及时运行；
worker 重启和任务重投不得导致重复订单提交；
关闭新交易权限不能停止既有订单状态和成交同步。
```

### 4.3 运维任务组

包含：

```text
RuntimeGuard；
Notifications pending 投递扫描；
通知投递；
必要的运行健康检查。
```

运维任务不修改交易业务事实，不触发订单动作。

### 4.4 离线任务组

包含：

```text
AIReview 数据包构建和 DeepSeek 调用；
PerformanceMetrics 后台一键补算；
后台导出和其他明确允许的离线分析。
```

离线任务不得占用交易关键任务的专用处理能力，也不得反向触发实时交易。

### 4.5 隔离原则

```text
交易关键任务优先于通知和离线复盘；
通知故障不阻断业务事实落库；
AIReview 堵塞不影响编排、订单状态或成交同步；
PerformanceMetrics 批量补算不影响四小时主编排；
各任务组可以使用独立 worker 资源；
所有任务组仍使用 MySQL 业务事实进行协调，不以 queue 状态代替业务状态。
```

## 5. 自动编排调度

### 5.1 UTC 计划时间

自动编排按 UTC 调度：

```text
daily_boundary：00:05 UTC；
four_hour_boundary：04:05、08:05、12:05、16:05、20:05 UTC。
```

`daily_boundary` 同时要求最新已收盘 4h 和 1d 数据满足正式消费条件。

其他四小时边界按对应 MarketSnapshot 和 DataQuality 合同执行。

服务器本地时区、部署机器时区、浏览器时区和用户时区不得参与计划时间计算。

### 5.2 触发数据

Beat 投递自动编排任务时只传递必要的小型运行上下文，例如：

```text
pipeline 身份；
scheduled_for_utc；
cycle_kind；
trigger_mode = automatic；
trigger_source；
trace_id。
```

任务消息不得携带完整 Kline、特征、账户快照、策略输出或订单对象。

### 5.3 自动运行唯一性

同一自动计划周期只能对应一条有效 OrchestrationRun。

唯一身份至少由以下内容确定：

```text
pipeline 身份；
scheduled_for_utc；
cycle_kind；
automatic 运行模式。
```

同一计划周期重复投递时：

```text
已有 created / running / waiting → 返回并继续已有 run，不新建第二轮；
已有终态 → 返回已有结果，不自动重跑；
已有 unknown / failed / stale_interrupted → 不自动建立第二条交易链；
重复任务不得生成第二份相同业务对象。
```

## 6. 一轮编排的驱动方式

### 6.1 单轮顺序执行

一轮 OrchestrationRun 由一个逻辑驱动顺序推进同步步骤。

基本方式：

```text
driver task
→ 取得当前 OrchestrationRun
→ 读取冻结 Registry 的下一步骤
→ 创建或取得 OrchestrationStepRun
→ Connector 调用 adapter
→ adapter 调用业务 service
→ 保存业务结果和对象关联
→ 根据 flow_action 处理
→ 继续下一同步步骤或结束当前 driver task
```

不为每个普通同步模块机械创建一条独立 Celery chain。

这样可以保证：

```text
步骤顺序由 Registry 和 PipelineOrchestrator 统一控制；
业务结果映射只有一个来源；
同步步骤之间不依赖 Celery chain 的隐式返回格式；
异常、停止和无动作分支统一落入 OrchestrationRun；
恢复时以数据库状态为准，而不是以 Celery canvas 状态为准。
```

### 6.2 不是全局单线程

“单轮顺序执行”只表示同一 OrchestrationRun 内的业务步骤不能乱序。

它不表示整个系统只有一个 worker，也不表示所有计划周期必须等待上一周期完全结束。

系统可以并行运行：

```text
不同计划周期的 OrchestrationRun；
RuntimeGuard；
Notifications；
AIReview；
PerformanceMetrics；
后台账户展示刷新。
```

并发安全由数据库唯一约束、业务幂等、明确任务认领和 ActiveLock 共同保证。

### 6.3 不持有长数据库事务

每个外部请求和业务 service 调用都不得被包在编排层长事务中。

标准顺序：

```text
短事务创建或认领 StepRun；
提交事务；
调用业务 service；
业务 service 自行完成业务事务；
短事务锁定 StepRun；
写 ObjectLink 和统一结果；
推进 Run；
提交事务。
```

不得在数据库事务中等待 Binance、DeepSeek、Hermes 或两秒轮询定时器。

### 6.4 交易关键队列交接

普通同步步骤由 orchestration driver 直接通过 Connector 调用。

进入以下交易关键步骤时，driver 必须把明确工作项交给交易关键任务组：

```text
Execution；
OrderStatusSync；
FillSync。
```

交接方式：

```text
driver 创建或认领当前 StepRun；
→ 保存明确业务对象引用和受控恢复信息；
→ 投递交易关键任务；
→ 原 run 进入 waiting；
→ driver task 结束并释放 orchestration worker；
→ 交易关键 worker 调用对应 adapter / service；
→ 保存业务结果；
→ 使用原恢复信息唤醒逻辑 driver；
→ driver 继续或结束同一 OrchestrationRun。
```

这不是把完整业务流程拆成隐式 Celery chain。步骤顺序、结果映射和下一步选择仍由 PipelineOrchestrator 控制。

交易关键任务重复投递时必须先认领原 StepRun 并核对已有业务事实。特别是 Execution task，只要已经存在对应 OrderSubmissionAttempt 或无法确认是否已经提交，就不得再次调用订单提交 Gateway。

## 7. 正式步骤推进

驱动任务必须遵守 `pipeline_orchestrator.md` 冻结的步骤顺序。

主线：

```text
Binance Account Sync（自动四小时账户边界，编排起始步骤）
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
→ 真实交易权限检查
→ OrderPlan
→ RiskCheck
→ ExecutionPreparation
→ Execution
→ OrderStatusSync
→ FillSync。
或 NO_TARGET_CHANGE / NO_TRADE：正常完成，不进入 PriceSnapshot 或订单链路。
```

编排驱动只消费 adapter 返回的 `flow_action`：

```text
CONTINUE → 进入 Registry 中下一合法步骤；
COMPLETE → 正常完成当前 run；
WAIT → 保存等待状态并释放 worker；
STOP → 受控阻断当前 run；
FAIL → 以系统失败结束当前 run。
```

编排驱动不得根据业务错误文本猜测下一步。

## 8. 条件步骤与有限循环

当前正式主链路只允许 DataQuality 与 DataBackfill 形成受控循环：

```text
DataQuality 发现可回补缺口
→ DataBackfill
→ DataQuality 重新验证。
```

规则：

```text
最大回补轮次由版本化 Registry 或正式配置定义；
达到上限必须停止；
DataBackfill 完成不等于质量通过；
不得在驱动任务中使用无限 while 循环；
每次实际步骤执行都必须有 StepRun；
每次回补和复检结果都必须可审计。
```

禁止形成以下自动循环：

```text
RiskCheck 未通过后重新生成 OrderPlan；
ExecutionPreparation 阻断后刷新价格并重做；
订单提交失败或 unknown 后重新提交；
成交同步失败后重新下单。
```

## 9. 上一周期未结束时的新周期

不同 `scheduled_for_utc` 表示不同自动周期。

如果上一周期仍处于 waiting、unknown、blocked 或 ActiveLock 尚未安全释放，新的计划周期仍然创建自己的唯一 OrchestrationRun。

新周期可以继续执行：

```text
行情采集；
数据质量；
必要回补；
MarketSnapshot；
特征和策略分析；
DecisionSnapshot；
trade_preparation Binance Account Sync；
TARGET_POSITION 分支的 PriceSnapshot 和真实交易权限检查。
```

如果新周期不需要交易：

```text
保存账户边界事实后正常完成；
不受旧 ActiveLock 影响；
为 PerformanceMetrics 保留新的四小时边界数据。
```

如果新周期需要进入 OrderPlan：

```text
OrderPlan 必须检查同一交易身份的 ActiveLock；
旧订单链仍持有有效锁时，新 OrderPlan 被阻断；
不得复用、覆盖或释放旧锁；
不得为了新周期重新提交旧订单；
不得通过新 OrchestrationRun 绕过旧订单链。
```

ActiveLock 只串行化冲突订单链，不是全系统编排锁。

## 10. WAIT 与 worker 释放

### 10.1 WAIT 的含义

业务步骤需要等待未来事实时，adapter 返回 `flow_action = WAIT`。

PipelineOrchestrator 必须：

```text
把 OrchestrationStepRun 标记为 waiting；
把 OrchestrationRun 标记为 waiting；
保存 resume_token；
保存等待对象引用和下一次检查时间；
提交数据库状态；
结束当前 driver task；
释放 worker。
```

禁止：

```text
在 worker 中 sleep 两秒后继续；
用数据库长事务等待；
持续占用一个 worker 直到三十秒结束；
只在 Celery result backend 保存等待状态。
```

### 10.2 恢复 WAIT

恢复任务必须：

```text
携带明确 resume_token 和技术追踪上下文；
锁定原 OrchestrationRun 和 waiting StepRun；
确认 token 匹配、未消费且步骤仍可恢复；
调用对应 adapter 取得新的业务结果；
幂等补写业务对象引用；
推进或结束原 run；
不得重新执行已经完成的步骤。
```

同一个 resume_token 只能成功消费一次。

## 11. OrderStatusSync 定向轮询

### 11.1 启动条件

只有以下提交结果进入 OrderStatusSync：

```text
OrderSubmissionAttempt.accepted；
OrderSubmissionAttempt.unknown。
```

第一轮查询在提交结果成功持久化两秒后开始。

### 11.2 每轮任务

每个定向查询任务只处理一条明确 OrderSubmissionAttempt 和一个明确逻辑轮次。

任务只传递：

```text
order_submission_attempt_id；
poll_sequence；
原技术追踪上下文；
关联 StepRun 的恢复信息。
```

任务不得携带或自行重建完整订单对象。

任务不得：

```text
直接调用 Binance；
自行判断交易所终态；
直接更新 ActiveLock；
自动重试同一个 poll_sequence；
触发订单重新提交。
```

### 11.3 轮询节奏

```text
第一次查询：提交事实落库两秒后；
后续查询：每两秒最多一个逻辑轮次；
最大立即轮询窗口：三十秒；
第 30 秒允许开始最后一个合法轮次；
超过第 30 秒不补发错过轮次。
```

Celery Beat 不得每两秒扫描订单状态全表。

下一轮必须由当前明确 attempt 的结果定向登记，或使用等价的持久化定时调度记录。

### 11.4 查询分支

```text
明确终态
→ 停止后续查询
→ 恢复原 OrchestrationRun
→ 继续 FillSync

NEW / PARTIALLY_FILLED / not_found / unknown 且仍在窗口内
→ 保存 OrderStatusSyncRecord
→ 登记下一轮定向查询
→ 原 run 保持 waiting

三十秒仍没有明确终态
→ 停止短轮询
→ 原 run 结束为 unknown
→ ActiveLock 保持保护
→ 写必要 AlertEvent
```

RuntimeGuard 只在后续达到巡检条件时发现长期不确定状态，不接管轮询、不恢复订单、不释放锁。

## 12. 任务重复投递与幂等

Celery 运行必须按“任务可能重复投递”设计。

任务消息不是 exactly-once 保证，业务正确性必须依赖 MySQL 业务幂等和唯一约束。

规则：

```text
同一自动周期重复触发返回同一 OrchestrationRun；
同一步骤重复驱动返回同一 StepRun 或安全恢复原 StepRun；
同一 business_request_key 返回已有业务结果；
同一 poll_sequence 重复任务不重复请求 Binance；
同一 NotificationDeliveryAttempt 不被多个 worker 同时认领；
同一 AIReview request_key 不创建重复请求；
同一 PerformanceMetrics 周期不创建重复有效记录；
Redis 锁失效不能破坏 MySQL 唯一性。
```

`celery_task_id`、worker 名称和任务重试次数都不得作为业务幂等键。

## 13. 崩溃窗口与安全恢复

### 13.1 业务对象已写入，ObjectLink 未写入

场景：

```text
业务 service 已成功提交业务对象；
worker 在写 OrchestrationBusinessObjectLink 前崩溃。
```

恢复：

```text
使用原 StepRun 和相同 business_request_key 重放 adapter；
业务 service 返回已有业务对象；
adapter 重新返回 object refs；
编排层幂等补写 ObjectLink；
不得创建第二份业务对象。
```

### 13.2 StepRun 为 running 时进程崩溃

受控恢复必须先判断：

```text
业务动作是否可能已经完成；
对应业务幂等键是否已有结果；
该步骤是否允许安全重放；
是否涉及订单提交或其他不可重复外部动作。
```

无法可靠判断时不得自动继续，必须保留不确定状态并等待人工排查。

RuntimeGuard 可以发现 stale 状态，但不得执行恢复。

### 13.3 订单提交崩溃窗口

订单提交前后任何崩溃都不得导致第二次提交。

恢复 order_submission 步骤时：

```text
只读取已有 PreparedOrderIntent 和 OrderSubmissionAttempt；
已有 attempt 时返回其结果；
提交是否发生无法确认时保持 unknown；
进入 OrderStatusSync 查询；
绝不再次调用订单提交 Gateway。
```

### 13.4 通知唤醒消息丢失

AlertEvent 路由后产生的 pending NotificationDeliveryAttempt 已经保存在 MySQL。

如果事务提交后、发送 Celery 唤醒消息前进程崩溃：

```text
业务事实和 pending attempt 仍然存在；
Notifications 定时扫描重新发现 pending attempt；
worker 认领并执行投递；
不得重新路由并创建重复 attempt。
```

## 14. 重试边界

### 14.1 BinanceGateway 安全读取技术重试

以下 Binance 读取动作可以由 BinanceGateway 按正式合同执行有限技术重试：

```text
Kline 和 server time；
账户、余额、持仓和交易规则；
mark price；
book ticker；
订单状态查询；
成交查询。
```

这些技术尝试仍属于同一次业务调用，业务 service 必须能看到最终错误分类和 attempt_count。

DeepSeek 调用只允许对发送前、能够明确证明请求尚未送出的技术失败按 DeepSeekGateway 合同处理；发送结果不确定时不得重试。

Hermes 投递只按 Notifications 自己的 DeliveryAttempt 状态和路由策略处理，不适用 Binance 安全读取规则。

### 14.2 业务恢复

业务恢复不是 Celery 的盲目自动重试。

安全恢复必须：

```text
先读取 MySQL 已有状态；
使用原业务幂等键；
确认动作可重复；
记录恢复来源和结果；
不得降低业务校验。
```

### 14.3 订单提交绝不重试

订单提交不适用任何 Gateway、Celery、业务或编排自动重试规则。

以下情况均不得重提：

```text
HTTP 429；
HTTP 5xx；
网络超时；
响应损坏；
worker 崩溃；
Celery redelivery；
编排恢复；
人工点击重放；
OrderSubmissionAttempt.unknown。
```

### 14.4 AIReview 不自动重试

AIReview 不自动重复调用 DeepSeek。

Gateway 内部有限技术重试只属于同一次 AIReviewAttempt。

发送结果 unknown、provider rejected 或 rate limited 时，由 AIReview 保存明确状态并交给后台处理，不自动快速重试。

### 14.5 通知重试不重放业务

Notifications 只允许对自己的 DeliveryAttempt 按路由策略执行受控重试。

通知重试不得：

```text
重新执行产生 AlertEvent 的业务模块；
重新提交订单；
恢复编排；
修改业务对象。
```

## 15. 新交易关闭后的既有任务

真实交易权限只在进入 OrderPlan 前检查一次。

关闭后台真实交易运行开关后：

```text
下一次进入 OrderPlan 的新订单链被阻止；
已通过权限检查的本轮不重新读取开关；
已经存在的 ExecutionPreparation、Execution、OrderStatusSync 和 FillSync 按原订单链继续；
已经提交或可能已经提交的订单必须继续查询状态和成交；
不得因为关闭新交易而停止安全收尾。
```

Runtime task 不得把关闭新交易解释为取消既有订单任务。

## 16. RuntimeGuard 独立调度

RuntimeGuard 使用独立 Celery Beat 计划，每十分钟运行一次。

它不属于某一 OrchestrationRun 的步骤，也不等待四小时边界。

运行方式：

```text
Beat
→ RuntimeGuard task
→ RuntimeGuard application service
→ 只读检查 MySQL 业务与运行事实
→ 写 RuntimeGuardRun / RuntimeGuardIssue / AlertEvent。
```

RuntimeGuard 不得：

```text
创建缺失 OrchestrationRun；
补跑主链路；
消费 resume_token；
修改 Run、StepRun 或业务对象；
调用 BinanceGateway；
重新提交订单；
创建成交事实；
释放 ActiveLock；
直接发送 Hermes；
巡检 AIReview、PerformanceMetrics 或普通后台页面功能。
```

同一计划巡检使用稳定 run_key，重复投递只产生一条有效 RuntimeGuardRun。

## 17. Notifications 运行方式

### 17.1 可靠交接

业务模块写 AlertEvent 时，Notifications 必须在同一数据库事务中形成：

```text
NotificationDeliveryAttempt.status = pending；
或 NotificationSuppression。
```

Celery 消息只负责加速唤醒通知 worker，不是唯一投递事实。

### 17.2 pending 扫描

Notifications 定时任务只扫描和认领 MySQL 中的 pending DeliveryAttempt。

它不得：

```text
重新解析原业务并重复创建 AlertEvent；
重新路由并重复创建首个 attempt；
把 Redis 或 broker 当作待投递事实；
在数据库事务提交前调用 Hermes。
```

### 17.3 通知与业务隔离

```text
通知失败不回滚业务；
通知成功不触发业务；
通知积压不阻止交易状态和成交事实写入；
通知 worker 恢复后从 MySQL pending 记录继续；
RuntimeGuard 只巡检投递状态，不替 Notifications 投递。
```

## 18. 后台和离线任务

### 18.1 PerformanceMetrics

PerformanceMetrics 只能由 OpsConsole 一键补算入口触发。

允许同步执行，也可以为了避免页面超时投递到离线任务组。

禁止：

```text
通过 Celery Beat 定时自动补算；
把补算放进四小时主编排；
补算失败后修改 OrchestrationRun；
请求 Binance；
占用交易关键任务资源。
```

后台重复点击必须通过周期业务幂等返回已有结果并补齐剩余缺失周期。

### 18.2 AIReview

AIReview 只由 OpsConsole 或明确管理入口创建请求，然后由离线任务组执行：

```text
创建 AIReviewRequest；
→ 构建 AIReviewPackage；
→ 调用 DeepSeekGateway；
→ 保存 AIReviewAttempt 和报告结果。
```

AIReview 不使用 Celery Beat 自动运行，不属于 PipelineOrchestrator，也不由 RuntimeGuard 恢复。

### 18.3 ops_display 账户刷新

OpsConsole 账户刷新是独立后台任务或同步 service 调用，只生成 `ops_display` BinanceSyncRun。

它不加入自动 OrchestrationRun，不进入 OrderPlan、RiskCheck、ExecutionPreparation 或 PerformanceMetrics。

## 19. 人工入口与诊断任务

management command 和 OpsConsole 只能调用明确 application service。

人工诊断如果需要编排记录，必须创建新的 `manual_diagnostic` OrchestrationRun，并明确引用原 run 作为诊断上下文。

人工诊断不得：

```text
伪装成原 automatic run；
复用原 run 的 resume_token；
绕过 Connector 调用交易步骤；
绕过真实交易权限；
重新提交订单；
直接修改业务对象或 ActiveLock；
把诊断结果写成正式策略或订单结果。
```

人工 ActiveLock 收尾必须调用 OrderPlan 所属锁服务并完成审计。

OrderStatusSync 和 FillSync 不因本运行架构自动获得未定义的人工补查或人工补同步入口。

## 20. MySQL、Redis 与 Celery 状态边界

### 20.1 MySQL

MySQL 是以下状态的正式来源：

```text
OrchestrationRun；
OrchestrationStepRun；
OrchestrationBusinessObjectLink；
业务模块对象和状态；
OrderSubmissionAttempt；
OrderStatusSyncRecord；
FillSyncResult；
ActiveLock；
RuntimeGuardRun / Issue；
NotificationDeliveryAttempt / Suppression；
AIReview 和 PerformanceMetrics 结果；
AuditRecord。
```

### 20.2 Redis

Redis 可以用于：

```text
Celery broker / result backend；
短期调度锁；
短期 worker 认领辅助；
短期任务状态；
限流、冷却和熔断。
```

Redis 不得成为业务步骤是否完成、订单是否提交、锁是否有效或通知是否待投递的唯一依据。

### 20.3 Celery result backend

Celery result backend 只用于技术查看和短期结果传递。

任何业务恢复都必须读取 MySQL，不能根据 Celery task 的 SUCCESS、FAILURE 或丢失状态直接判断业务是否成功。

### 20.4 Celery 消息

Celery 消息是执行请求，不是业务事实。

消息丢失、重复或延迟都不得改变已经落库的业务语义。

## 21. 任务认领与并发

任务 worker 在执行可并发竞争的业务前，必须通过数据库原子更新、行锁、唯一约束或等价可靠机制认领对象。

至少保证：

```text
同一 OrchestrationRun 不被两个 driver 同时推进同一步；
同一 StepRun execution_sequence 不产生两条有效执行；
同一 resume_token 只消费一次；
同一 poll_sequence 只执行一次业务查询；
同一 NotificationDeliveryAttempt 同时只被一个 worker 投递；
同一 AIReviewRequest 不产生并发重复发送；
同一 PerformanceMetrics 周期不产生重复有效记录。
```

Redis 锁可以减少竞争，但数据库约束必须保护最终正确性。

## 22. worker 停止与重启

worker 停止或重启时：

```text
不得依赖进程内变量保存业务进度；
运行进度必须已写入 MySQL；
正在等待的 run 仍保持 waiting；
正在提交或可能已提交的订单不得自动重提；
pending 通知仍可由其他 worker 或重启后扫描恢复；
离线任务根据自身业务对象恢复，不影响交易任务。
```

无法确认某一步是否完成时，必须保守保留 unknown 或 stale 状态，不得通过重新执行高风险动作“试一下”。

## 23. 日志与运行观测

每个关键任务至少记录：

```text
trace_id；
trigger_source；
task 技术身份；
业务对象 ID；
OrchestrationRun / StepRun ID（如适用）；
scheduled_for_utc；
开始和结束 UTC 时间；
执行耗时；
统一结果；
脱敏错误分类；
是否登记后续任务。
```

task id 只用于技术定位，不是业务外键或幂等键。

日志不得包含密钥、完整 Binance 响应、完整 prompt、完整 DeepSeek 输出或大体积业务数据。

## 24. 测试方向

运行任务架构至少应测试：

```text
同一计划周期重复触发只创建一条 OrchestrationRun；
一轮内步骤按 Registry 顺序执行；
普通同步步骤不为每步建立隐式 Celery chain；
Execution、OrderStatusSync 和 FillSync 通过交易关键队列交接并恢复同一 run；
WAIT 后 driver task 结束且 worker 不被 sleep 占用；
resume_token 只能消费一次；
OrderStatusSync 每两秒最多一个轮次且不全表扫描；
三十秒后停止短轮询并保持 ActiveLock；
业务已写入但 ObjectLink 未写入时可以只补关联；
Celery 重复投递不重复请求不可重复的外部动作；
订单提交任务 redelivery 不再次调用 Gateway；
上一周期 ActiveLock 未释放时新周期仍完成数据、策略和账户步骤；
新周期在 OrderPlan 被旧 ActiveLock 阻断且不产生冲突订单；
关闭新交易权限后既有状态与成交任务继续；
RuntimeGuard 与四小时编排独立；
RuntimeGuard 不恢复业务；
通知唤醒消息丢失后可以从 MySQL pending 记录恢复；
AIReview 和 PerformanceMetrics 不阻塞交易关键任务；
Redis 与 result backend 丢失不破坏 MySQL 业务状态；
所有调度按 UTC。
```

测试默认使用 fake Gateway，不访问真实 Binance、DeepSeek 或 Hermes，不提交真实订单。

## 25. 当前不确定到具体实现阶段的事项

以下内容不在本文档中提前固定：

```text
Celery queue 的实际字符串名称；
每类 worker 的实例数量和 concurrency；
prefetch、ack_late、soft time limit 和 hard time limit 具体配置；
容器、进程或主机部署拓扑；
Notifications pending 扫描具体秒数；
任务监控产品和 Dashboard；
自动扩缩容策略；
具体 task 函数和模块路径。
```

这些配置必须在开发计划或部署文档中确定，但不得违反本文档的任务隔离、幂等、WAIT、恢复和绝不重提规则。

## 26. 验收标准

满足以下条件才算运行任务架构成立：

```text
生产环境只有一个正式活动 Beat 调度实例；
同一自动周期重复触发不会创建第二轮；
一轮编排由一个 driver 顺序推进同步步骤；
不同计划周期可以各自创建 OrchestrationRun；
旧 ActiveLock 只阻断新订单链，不阻断新周期数据、策略和账户事实；
等待订单状态时保存 WAIT 并释放 worker；
订单状态使用定向延迟任务，不使用 Beat 每两秒全表扫描；
所有任务以 MySQL 业务状态为准；
Redis、broker 和 result backend 不成为唯一业务事实；
交易关键任务与通知、AIReview、PerformanceMetrics 逻辑隔离；
任务重投和崩溃恢复不会造成重复订单提交；
订单提交在任何层级都绝不重试；
关闭新交易权限不会中断既有订单追踪和成交同步；
RuntimeGuard 只读巡检且独立调度；
PerformanceMetrics 只由后台补算入口触发，AIReview 只由 OpsConsole 或明确受控管理入口触发；
所有计划时间和运行判断使用 UTC；
具体实现仍遵守 requirements、project_invariants 和现有架构边界。
```

## 27. 最终结论

本系统的运行任务架构采用：

```text
单轮编排驱动任务顺序推进同步步骤；
WAIT 持久化后释放 worker；
订单状态使用定向延迟任务恢复原 run；
不同计划周期允许并存；
ActiveLock 只保护冲突订单链；
交易关键任务与通知、巡检和离线复盘隔离；
MySQL 保存最终运行事实；
任务重复投递由业务幂等吸收；
订单提交永远不重试。
```
