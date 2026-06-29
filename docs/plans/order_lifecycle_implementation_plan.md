# 订单提交、状态与成交闭环实施计划

## 1. 文档目的

本文档用于指导阶段 5 的代码实现。

阶段 5 的目标是把阶段 4 已经形成的 `PreparedOrderIntent` 推进为完整、可审计、可收尾的订单生命周期事实：

```text
PreparedOrderIntent
→ Execution / OrderSubmission
→ OrderSubmissionAttempt
→ 订单提交事实完成
```

订单提交后的状态与成交事实由独立订单生命周期同步管线推进：

```text
OrderSubmissionAttempt
→ OrderStatusSync
→ OrderStatusSyncRecord
→ FillSync
→ TradeFill
→ OrderFillSummary
→ ActiveLock 安全收尾
```

阶段 5 完成后，系统应能：

```text
把一份已通过风控和执行前检查的订单请求提交给 Binance；
严格保证同一 PreparedOrderIntent 最多提交一次；
区分订单提交 accepted / rejected / unknown / 提交前阻断 / 提交前失败；
对 accepted / unknown 订单登记或触发独立订单生命周期同步管线；
由订单生命周期同步管线执行 2 秒一次、最多 30 秒的状态查询；
只在明确终态后同步成交；
保存逐笔成交和订单成交汇总；
只在订单状态与成交事实完整时安全释放 ActiveLock；
为编排、后台、RuntimeGuard 和 ReviewDataset 提供可信订单事实。
```

本文档不实现四小时主编排，不实现 RuntimeGuard，不实现 Notifications 投递，不实现后台 UI。

---

## 2. 阶段定位

阶段 5 是真实订单提交后的事实闭环阶段。

一句话：

```text
把“待提交订单”变成“交易所提交事实、订单状态事实、成交事实和安全收尾事实”。
```

本阶段解决：

```text
订单如何提交且绝不重试；
提交结果不明时如何保守处理；
accepted 不等于成交；
unknown 不等于失败；
订单状态如何短轮询；
订单终态如何判断；
成交如何逐笔落库；
成交汇总如何生成；
ActiveLock 什么时候可以安全释放；
订单生命周期如何被后续编排和巡检消费。
```

本阶段不解决：

```text
四小时自动编排如何调度；
编排步骤如何登记和恢复；
RuntimeGuard 如何巡检；
通知如何投递到 Hermes；
ReviewDataset 如何使用订单和成交事实；
AI 如何复盘；
后台页面如何展示。
```

限价单周期收尾撤单由 `docs/requirements/order_cycle_closeout.md` 定义。本阶段如接入该能力，只允许围绕既有 LIMIT 订单执行周期收尾撤单，不得扩展为通用撤单、改单或追单。

---

## 3. 前置条件

进入本阶段前，应已完成或具备：

```text
阶段 0 项目底座；
阶段 3 已建立 BinanceGateway 公共结构、市场域隔离、凭据隔离、账户与价格读取能力；
阶段 4 OrderPlan、CandidateOrderIntent、RiskCheck、ApprovedOrderIntent、ExecutionPreparation、PreparedOrderIntent；
OrderPlanActiveLockService；
AlertEvent 写入能力；
AuditRecord 或等价审计能力；
trace_id、trigger_source、UTC、MySQL、测试框架；
测试默认使用 fake BinanceGateway。
```

如果阶段 4 尚未完成，本阶段只能实现模型 skeleton、接口合同和纯测试替身，不得接入真实提交链路。

---

## 4. 文档依据

编码前必须阅读并遵守：

```text
AGENTS.md
README.md
docs/rules/project_invariants.md
docs/requirements/project_scope.md
docs/requirements/project_foundation.md
docs/requirements/system_capabilities.md
docs/requirements/core_contracts.md
docs/requirements/binance_gateway.md
docs/requirements/order_plan.md
docs/requirements/risk_check.md
docs/requirements/execution_preparation.md
docs/requirements/order_submission.md
docs/requirements/order_status_sync.md
docs/requirements/fill_sync.md
docs/requirements/order_cycle_closeout.md
docs/requirements/notifications.md
docs/requirements/pipeline_orchestrator.md
docs/requirements/runtime_guard.md
docs/architecture/system_architecture.md
docs/architecture/data_flow_architecture.md
docs/architecture/module_boundary_architecture.md
docs/architecture/runtime_task_architecture.md
docs/architecture/testing_and_safety_architecture.md
docs/plans/foundation_implementation_plan.md
docs/plans/account_price_fact_implementation_plan.md
docs/plans/trading_execution_implementation_plan.md
docs/plans/implementation_roadmap.md
```

如果本文档与 requirements 冲突，以 requirements 为准，并停止实现向用户确认。

---

## 5. 本阶段核心口径

### 5.1 Execution 是唯一真实订单提交入口

只有 Execution / OrderSubmission 可以调用 BinanceOrderSubmissionGateway。

禁止：

```text
OrderPlan 直接下单；
RiskCheck 直接下单；
ExecutionPreparation 直接下单；
PipelineOrchestrator 直接下单；
Celery task 绕过 service 下单；
management command 绕过 service 下单；
OpsConsole 直接下单。
```

### 5.2 订单提交绝不重试

同一 PreparedOrderIntent 对应的真实提交调用最多一次。

以下层级都不得重试订单提交：

```text
Gateway；
Gateway 内部 transport；
Execution service；
Celery task；
PipelineOrchestrator；
management command；
OpsConsole；
人工重复触发。
```

提交失败、超时、限频、5xx、响应损坏、进程崩溃或结果不明，都不得再次提交同一 PreparedOrderIntent。

### 5.3 unknown 必须保守处理

unknown 表示系统无法确认 Binance 是否收到或处理订单。

unknown 后必须：

```text
保存 OrderSubmissionAttempt；
保持 ActiveLock 阻断；
不得重新提交；
不得生成新的 PreparedOrderIntent；
不得允许新编排绕过锁；
进入 OrderStatusSync；
写 high / critical AlertEvent。
```

unknown 不等于失败，也不等于订单不存在。

### 5.4 accepted 不等于成交

accepted 只表示 Binance 明确接受订单请求。

accepted 后不得：

```text
直接生成 TradeFill；
直接生成 OrderFillSummary；
直接释放 ActiveLock；
直接更新 BinancePositionSnapshot；
把提交响应里的 FILLED 当作完整成交事实。
```

成交事实只能由 FillSync 生成。

### 5.5 OrderStatusSync 只确认订单状态

OrderStatusSync 负责查询订单状态。

它不负责：

```text
重新提交订单；
同步成交；
计算平均成交价；
生成 TradeFill；
释放 ActiveLock；
更新账户或持仓快照。
```

订单状态明确终态后，仍必须进入 FillSync。

### 5.6 FillSync 是成交事实入口

FillSync 负责：

```text
查询目标订单全部成交；
逐笔保存 TradeFill；
生成 OrderFillSummary；
校验成交完整性；
在证据完整时调用 OrderPlanActiveLockService 收尾。
```

FillSync 不得根据账户持仓反推成交，也不得修改 BinancePositionSnapshot。

### 5.7 ActiveLock 只在证据完整时释放

accepted 或 unknown 后，锁必须保持阻断，直到同时具备：

```text
OrderStatusSync 明确终态；
FillSync 完成成交查询；
TradeFill 幂等落库；
OrderFillSummary 完整；
synced 或严格 synced_empty；
全部证据属于同一 OrderSubmissionAttempt。
```

RuntimeGuard、PipelineOrchestrator、OrderStatusSync 和 FillSync 都不得直接写锁表。

锁收尾必须通过 OrderPlanActiveLockService。

---

## 6. 本阶段实现范围

### 6.1 BinanceGateway 订单生命周期受限接口

本阶段必须在阶段 3 已有 `apps/binance_gateway/` 内补齐：

```text
BinanceOrderSubmissionGateway.submit_order；
BinanceOrderStatusGateway.query_order；
BinanceFillQueryGateway.query_order_fills；
USDS-M / COIN-M endpoint family 映射；
订单提交使用对应市场域的 TRADE 凭据和签名；
订单状态与成交查询使用对应市场域的 READ 凭据和签名；
market_type / account_domain / symbol 上下文校验；
订单提交、订单查询和成交查询响应标准化；
脱敏错误分类与 attempt_count；
三个接口对应的 fake gateway。
```

规则：

```text
submit_order 任何错误都不执行技术重试；
query_order 和 query_order_fills 可以按 BinanceGateway 合同执行有限安全读取技术重试；
submit_order 必须校验 PreparedOrderIntent 的冻结市场与当前 active market domain 一致；
query_order 和 query_order_fills 必须按原 OrderSubmissionAttempt 冻结的 market_type 选择只读 adapter，不得改查当前 active market domain；
既有订单原市场的只读凭据或查询能力缺失时必须在发送前失败，不得跨市场回退；
所有技术尝试仍属于同一次业务调用；
Gateway 不写 OrderSubmissionAttempt、OrderStatusSyncRecord、TradeFill 或其他业务事实；
Gateway 不决定订单终态、成交完整性或 ActiveLock；
不得创建第二套 base URL、API key、超时、限频或熔断配置。
```

### 6.2 Execution / OrderSubmission

实现订单提交 service。

负责：

```text
接收明确 prepared_order_intent_id；
校验 PreparedOrderIntent 可提交；
校验 ExecutionPreparationResult = PREPARED；
校验完整上游订单链；
校验 ActiveLock；
校验冻结市场身份；
校验冻结订单参数；
抢占唯一提交资格；
创建或读取唯一 OrderSubmissionAttempt；
构造冻结订单请求；
调用一次 BinanceOrderSubmissionGateway.submit_order；
根据 Gateway 证据分类 accepted / rejected / unknown / blocked_before_submit / failed_before_submit；
推进 PreparedOrderIntent 状态；
按安全规则推进 ActiveLock；
写 AlertEvent；
为 OrderStatusSync 提供后续输入。
```

### 6.3 OrderSubmissionAttempt

实现 OrderSubmissionAttempt 模型和幂等约束。

至少支持状态：

```text
created；
submitting；
accepted；
rejected；
unknown；
blocked_before_submit；
failed_before_submit。
```

每份 PreparedOrderIntent 最多一条 OrderSubmissionAttempt。

### 6.4 OrderStatusSync

实现订单状态查询 service。

负责：

```text
只接收明确 OrderSubmissionAttempt；
只查询 accepted 或 unknown 的提交结果；
优先使用原 client_order_id 查询；
通过 BinanceOrderStatusGateway 查询；
提交结果持久化后等待 2 秒执行第一轮；
每 2 秒一个逻辑轮次；
最多 30 秒；
查到明确终态立即停止；
保存每轮 OrderStatusSyncRecord；
区分 found / not_found / unknown / failed_before_query / blocked_before_query；
终态后交接 FillSync；
30 秒仍未解决时停止短轮询并保持锁阻断；
写 AlertEvent。
```

### 6.5 OrderStatusSyncRecord

实现每轮订单状态查询记录。

每次实际查询必须保存独立记录。

必须支持：

```text
轮次编号；
查询编号；
查询结果；
Binance 原始订单状态；
是否识别；
是否终态；
提交 unknown 的解析状态；
Gateway 尝试次数；
脱敏响应摘要；
trace_id；
trigger_source。
```

### 6.6 FillSync

实现成交同步 service。

负责：

```text
只消费明确终态 OrderStatusSyncRecord；
通过 BinanceFillQueryGateway 查询目标订单成交；
按分页完整拉取；
逐条保存 TradeFill；
按交易所成交身份幂等；
生成 OrderFillSummary；
校验身份、分页、数量、市场口径和汇总 hash；
区分 synced / synced_empty / incomplete / unknown / failed_before_query / blocked_before_query；
证据完整时调用 OrderPlanActiveLockService 安全释放锁；
写 AlertEvent。
```

### 6.7 TradeFill

实现不可变成交事实。

规则：

```text
每条成交直接关联 OrderSubmissionAttempt；
使用交易所成交身份唯一约束幂等；
重复同步不重复插入、不重复累计；
相同成交身份但 payload 冲突时不得覆盖旧记录；
TradeFill 不保存 order_fill_summary_id；
TradeFill 不生成或修改账户持仓快照。
```

### 6.8 OrderFillSummary

实现订单级成交汇总。

规则：

```text
每条 OrderSubmissionAttempt 最多一条 OrderFillSummary；
从数据库中该订单全部 TradeFill 全量重算；
不做不可验证的增量累加；
USDS-M 和 COIN-M 使用各自 calculator；
手续费和 realized pnl 按资产分别汇总；
完整性不满足时不得释放锁。
```

---

## 7. 建议代码模块

具体 Django app 名称可在编码阶段最终确定，但建议：

```text
apps/binance_gateway/（扩展既有 app，不新建第二套 Gateway）
apps/execution/
apps/order_status_sync/
apps/fill_sync/
```

其中：

```text
apps/binance_gateway/ 只实现订单提交、订单状态和成交查询受限通信能力，不写业务事实；
apps/execution/ 保存 Execution / OrderSubmission 和 OrderSubmissionAttempt；
apps/order_status_sync/ 保存 OrderStatusSync 和 OrderStatusSyncRecord；
apps/fill_sync/ 保存 FillSyncResult、TradeFill 和 OrderFillSummary。
```

业务逻辑必须放在：

```text
service 层；
domain 层；
必要的纯计算 helper。
```

Celery task、management command、view 和 serializer 只能作为薄入口。

---

## 8. 数据库迁移范围

### 8.1 Execution 相关

建议创建：

```text
OrderSubmissionAttempt。
```

需要对以下身份建立唯一约束或等价并发保护：

```text
prepared_order_intent_id；
order_submission_attempt_key；
client_order_id；
idempotency_key。
```

### 8.2 OrderStatusSync 相关

建议创建：

```text
OrderStatusSyncRecord。
```

唯一约束至少覆盖：

```text
order_status_sync_key；
同一 OrderSubmissionAttempt 的同一 poll_mode + poll_sequence。
```

### 8.3 FillSync 相关

建议创建：

```text
FillSyncResult；
TradeFill；
OrderFillSummary。
```

唯一约束至少覆盖：

```text
FillSyncResult.fill_sync_result_key；
TradeFill 的交易所成交身份；
OrderFillSummary.order_submission_attempt_id。
```

### 8.4 共同建模要求

所有正式对象必须：

```text
保存直接上游业务外键；
保存 business_request_key；
保存 market_type、account_domain、symbol；
保存 status / reason_code；
保存 trace_id / trigger_source；
保存脱敏 Gateway 证据；
保存 UTC 时间；
支持幂等唯一约束；
可被 OrchestrationBusinessObjectLink 关联。
```

业务表不得保存或查询：

```text
OrchestrationRun ID；
StepRun ID；
步骤序号；
编排内部状态。
```

---

## 9. 配置项

所有新增配置必须进入 `.env.example` 并带中文注释。

### 9.1 Execution 配置

Execution 不设置独立的订单提交运行开关。

订单提交的 base URL、API key、secret、真实交易部署级硬开关、超时、限频和熔断配置属于 BinanceGateway。

Execution 只消费 Gateway 返回的受控结果，不重复配置交易所连接信息，不读取 MySQL 真实交易运行开关，也不新增另一套订单提交开关。

### 9.2 OrderStatusSync 配置

```text
ORDER_STATUS_SYNC_ENABLED
ORDER_STATUS_POLL_INTERVAL_SECONDS=2
ORDER_STATUS_POLL_MAX_DURATION_SECONDS=30
ORDER_STATUS_RECOVERY_WINDOW_SECONDS=86400
```

终态集合不通过 env 热修改。

### 9.3 FillSync 配置

```text
FILL_SYNC_ENABLED
FILL_SYNC_PAGE_SIZE
FILL_SYNC_MAX_PAGES
FILL_SYNC_RECOVERY_WINDOW_SECONDS=86400
```

完整性规则和市场计算公式不得通过 env 任意热修改。

---

## 10. 实施顺序

### 10.1 扩展 BinanceGateway 订单生命周期接口

执行内容：

```text
在既有 apps/binance_gateway/ 内实现订单提交、订单状态查询和成交查询三个受限接口；
复用既有 market domain、凭据、签名、超时、限频、冷却、熔断和错误分类基础设施；
分别映射 USDS-M 与 COIN-M endpoint family；
实现业务模块可消费的标准化返回合同；
为三个接口实现 fake gateway；
确保 Gateway 不写任何订单、状态或成交业务事实。
```

验收重点：

```text
业务模块不直接拼接 Binance endpoint、不接触签名或密钥；
订单提交只使用 TRADE 凭据，订单状态与成交查询只使用 READ 凭据；
订单提交接口任何错误都不重试；
订单状态和成交查询只允许受限安全读取重试；
Gateway 返回实际技术尝试次数；
三个 fake gateway 可以独立模拟成功、拒绝、未找到、未知和读取失败；
未新增第二套 Binance 连接配置或重复 Gateway app。
```

### 10.2 实现 OrderSubmissionAttempt 模型

执行内容：

```text
创建 OrderSubmissionAttempt；
添加唯一约束和索引；
保存冻结订单请求、提交状态、Gateway 证据和脱敏响应；
生成 migration。
```

验收重点：

```text
每份 PreparedOrderIntent 最多一条 attempt；
client_order_id 唯一；
重复调用返回已有 attempt；
submitting 不会被重复提交。
```

### 10.3 实现 Execution 提交资格抢占

执行内容：

```text
锁定 PreparedOrderIntent；
锁定 ActiveLock；
校验上游链路；
校验冻结市场身份；
校验 PreparedOrderIntent 未过期；
创建 attempt；
推进 attempt 为 submitting；
提交事务后才调用 Gateway。
```

验收重点：

```text
不在数据库长事务中等待 Binance；
并发调用最多一个进入 Gateway；
阻断和提交前失败必须能证明 request_sent=false。
```

### 10.4 实现 Execution Gateway 调用与结果分类

执行内容：

```text
调用一次 BinanceOrderSubmissionGateway.submit_order；
检查 Gateway attempt_count；
分类 accepted / rejected / unknown；
保存 request_sent、response_received 和脱敏结果；
推进 PreparedOrderIntent；
按规则推进 ActiveLock；
写 AlertEvent。
```

验收重点：

```text
任何错误都不重试；
accepted 保持锁；
unknown 保持锁；
明确 rejected 或明确未发送才可安全释放；
提交响应中的 FILLED 不生成成交。
```

### 10.5 实现 OrderStatusSyncRecord 模型

执行内容：

```text
创建 OrderStatusSyncRecord；
保存轮次、查询编号、查询结果、订单状态和 Gateway 证据；
添加唯一约束；
生成 migration。
```

验收重点：

```text
同一轮次重复投递不重复查询；
每一次实际查询都有记录；
终态判断证据可审计。
```

### 10.6 实现 OrderStatusSync 轮询 service

执行内容：

```text
校验 OrderSubmissionAttempt；
计算 2 秒轮询窗口；
按 poll_sequence 创建占位记录；
调用 BinanceOrderStatusGateway.query_order；
保存 found / not_found / unknown / 查询前失败 / 查询前阻断；
识别 NEW、PARTIALLY_FILLED 和终态白名单；
终态后停止轮询并交接 FillSync；
30 秒未终态后停止短轮询；
写 AlertEvent。
```

验收重点：

```text
not_found 不等于提交失败；
unknown 不等于订单不存在；
NEW 和 PARTIALLY_FILLED 不终结；
只有明确终态才能进入 FillSync；
30 秒未解决不释放锁。
```

### 10.7 实现 FillSyncResult、TradeFill、OrderFillSummary 模型

执行内容：

```text
创建 FillSyncResult；
创建 TradeFill；
创建 OrderFillSummary；
添加成交身份唯一约束；
添加 summary 唯一约束；
生成 migration。
```

验收重点：

```text
TradeFill 不可变；
重复同步不重复累计；
OrderFillSummary 从 TradeFill 全量重算；
TradeFill 不反向引用后生成的 summary。
```

### 10.8 实现 FillSync 分页查询与成交落库

执行内容：

```text
校验终态 OrderStatusSyncRecord；
校验 exchange_order_id；
按页调用 BinanceFillQueryGateway.query_order_fills；
逐条校验成交身份；
幂等写入 TradeFill；
处理重复和 payload 冲突；
记录分页完整性；
写 AlertEvent。
```

验收重点：

```text
缺 exchange_order_id 不宽泛查询；
分页未完成不得 synced；
payload 冲突不得覆盖既有成交；
查询失败不重新提交订单。
```

### 10.9 实现成交汇总与锁收尾

执行内容：

```text
从数据库读取该订单全部 TradeFill；
按市场域 calculator 重算汇总；
校验数量与终态 executed_quantity；
生成或更新 OrderFillSummary；
设置 synced / synced_empty / incomplete / unknown；
证据完整时调用 OrderPlanActiveLockService.finalize_after_fill_sync；
记录锁收尾结果；
写 AlertEvent。
```

验收重点：

```text
FILLED + 零成交不得 synced_empty；
synced_empty 只允许严格零成交终态；
incomplete / unknown / 查询前失败不得解锁；
锁服务拒绝时不修改成交事实。
```

### 10.10 建立薄入口

允许建立：

```text
Execution Celery task；
OrderStatusSync Celery task；
FillSync Celery task；
受控 management command。
```

入口层只能：

```text
解析参数；
传递 trace_id；
设置 trigger_source；
调用 service；
输出结构化摘要。
```

入口层不得：

```text
直接调用 Binance；
直接判断终态；
直接计算成交汇总；
直接释放 ActiveLock；
自动重试订单提交。
```

---

## 11. 编排边界

本阶段不实现完整 PipelineOrchestrator。

但必须为后续编排提供明确 adapter 合同。

### 11.1 OrderSubmissionStepAdapter

输入：

```text
prepared_order_intent_id；
business_request_key；
trace_id；
trigger_source。
```

职责：

```text
调用 Execution / OrderSubmission service；
理解 accepted / rejected / unknown / blocked_before_submit / failed_before_submit；
accepted 或 unknown 时登记或触发独立订单生命周期同步管线；
rejected 或提交前阻断时受控停止；
返回 order_submission_attempt_id。
```

### 11.2 OrderStatusSyncStepAdapter

该 adapter 属于独立订单生命周期同步管线，不属于 OrderSubmission 后主交易 run 的内嵌尾部步骤。

输入：

```text
order_submission_attempt_id；
business_request_key；
trace_id；
trigger_source。
```

职责：

```text
启动或恢复订单状态轮询；
将轮询中映射为 WAIT；
将明确终态映射为 CONTINUE 到 FillSync；
将 30 秒未解决映射为 UNKNOWN + COMPLETE；
返回 OrderStatusSyncRecord 引用。
```

### 11.3 FillSyncStepAdapter

该 adapter 属于独立订单生命周期同步管线，不属于 OrderSubmission 后主交易 run 的内嵌尾部步骤。

输入：

```text
order_submission_attempt_id；
terminal_order_status_sync_record_id；
business_request_key；
trace_id；
trigger_source。
```

职责：

```text
调用 FillSync service；
synced 或严格 synced_empty 时 COMPLETE；
incomplete 或 unknown 时 UNKNOWN + COMPLETE；
failed_before_query 时 FAIL；
blocked_before_query 时 STOP；
返回 FillSyncResult、TradeFill 和 OrderFillSummary 引用。
```

---

## 12. ActiveLock 收尾边界

本阶段可以释放 ActiveLock 的唯一自动路径：

```text
FillSyncResult.status = synced 或严格 synced_empty；
OrderFillSummary.is_complete = true；
终态 OrderStatusSyncRecord 明确；
全部成交事实属于同一 OrderSubmissionAttempt；
OrderPlanActiveLockService 重新校验通过。
```

不得释放：

```text
OrderSubmissionAttempt.status = accepted 但未查终态；
OrderSubmissionAttempt.status = unknown；
OrderStatusSync not_found；
OrderStatusSync unknown；
OrderStatusSync NEW；
OrderStatusSync PARTIALLY_FILLED；
OrderStatusSync polling_timeout；
FillSync incomplete；
FillSync unknown；
FillSync failed_before_query；
FillSync blocked_before_query；
成交分页不完整；
成交数量不一致；
TradeFill payload 冲突；
只因为市价单通常很快成交。
```

---

## 13. AlertEvent 边界

本阶段只写 AlertEvent，不直接发送 Hermes。

必须写 AlertEvent 的典型场景：

```text
order_submission_accepted；
order_submission_rejected；
order_submission_unknown；
order_submission_blocked_before_submit；
order_submission_failed_before_submit；
order_submission_gateway_contract_violation；
order_status_found；
order_status_not_found；
order_status_query_unknown；
order_status_new；
order_status_partially_filled；
order_status_filled；
order_status_canceled；
order_status_rejected；
order_status_expired；
order_status_expired_in_match；
order_status_polling_timeout；
order_status_fill_sync_requested；
fill_sync_synced；
fill_sync_synced_empty；
fill_sync_incomplete；
fill_sync_unknown；
trade_fill_recorded；
trade_fill_payload_conflict；
order_fill_summary_generated；
active_lock_released_after_fill_sync；
active_lock_finalization_blocked。
```

通知语义必须明确区分：

```text
订单已提交；
交易所已接受；
订单状态查询；
订单终态；
逐笔成交；
订单成交汇总；
锁收尾。
```

不得把 accepted 写成已经成交，不得把 FILLED 写成成交明细已同步完成。

---

## 14. Redis 使用边界

本阶段一般不需要直接使用 Redis。

允许 Redis 用于：

```text
Celery broker / result backend；
短期任务防重复唤醒。
```

禁止 Redis 作为：

```text
订单提交事实来源；
订单状态事实来源；
成交事实来源；
ActiveLock 正式来源；
Notification 或 AlertEvent 唯一来源。
```

MySQL 是本阶段所有订单生命周期事实的正式来源。

---

## 15. 外部服务边界

本阶段允许的 Binance 请求只有：

```text
Execution
→ BinanceOrderSubmissionGateway.submit_order

OrderStatusSync
→ BinanceOrderStatusGateway.query_order

FillSync
→ BinanceFillQueryGateway.query_order_fills
```

禁止：

```text
绕过 BinanceGateway；
业务模块直接拼 HTTP；
业务模块接触 API secret、signature 或认证 header；
OrderStatusSync 调用订单提交 Gateway；
FillSync 调用订单提交或订单状态 Gateway；
任何模块修改杠杆、保证金模式或持仓模式；
任何模块调用 DeepSeek；
任何模块直接发送 Hermes。
```

自动化测试必须使用 fake BinanceGateway，不得访问真实 Binance。

---

## 16. 测试计划

### 16.1 BinanceGateway 订单生命周期接口测试

必须测试：

```text
USDS-M 与 COIN-M 使用正确且相互隔离的 endpoint family；
订单提交凭据与订单状态、成交查询凭据按 TRADE / READ 权限严格隔离；
市场域、账户域和交易品种不一致时在发出请求前阻断；
新订单提交市场与当前 active market domain 不一致时阻断；
既有订单状态和成交查询始终使用原订单冻结市场，不受当前 active market domain 变化影响；
原订单市场只读凭据缺失时不改查另一个市场；
业务调用方无法传入或覆盖 API key、secret、签名、base URL 和底层 endpoint；
submit_order 成功时只执行一次网络请求；
submit_order 遇到连接超时、读取超时、429、5xx 或损坏响应时均不重试；
query_order 与 query_order_fills 只按 Gateway 合同执行有限安全读取重试；
安全读取重试的实际尝试次数被标准化返回；
Gateway 错误和响应摘要完成脱敏；
Gateway 不写 OrderSubmissionAttempt、OrderStatusSyncRecord、TradeFill 或其他业务事实；
三个 fake gateway 可以覆盖成功、拒绝、未找到、未知、分页和读取失败场景。
```

### 16.2 Execution 测试

必须测试：

```text
只消费 prepared 状态的 PreparedOrderIntent；
PreparedOrderIntent 过期不提交；
上游链路身份不一致不提交；
ActiveLock 缺失或不匹配不提交；
同一 PreparedOrderIntent 最多一条 attempt；
并发调用最多一次进入 Gateway；
Celery 重复投递不重复调用 Gateway；
Gateway submit_order 最多调用一次；
connect timeout 不重试；
read timeout 不重试；
HTTP 429 不重试；
HTTP 5xx 不重试；
Gateway attempt_count > 1 记为合同异常；
accepted 保存交易所标识且保持锁；
rejected 明确未接单时释放锁；
unknown 保持锁；
提交响应 FILLED 不生成 TradeFill；
Execution 不读取 MySQL 真实交易运行开关；
Execution 不重新查询价格；
Execution 不修改冻结订单参数；
所有正式结果写 AlertEvent。
```

### 16.3 OrderStatusSync 测试

必须测试：

```text
accepted 和 unknown 可以查询；
rejected / blocked_before_submit / failed_before_submit 不查询；
unknown 使用原 client_order_id 查询；
两种编号都缺失时不请求 Binance；
提交后 2 秒执行第一轮；
每 2 秒最多一个逻辑轮次；
30 秒窗口最多 15 轮；
同一 poll_sequence 不重复查询；
not_found 不解释为提交失败；
NEW 继续等待；
PARTIALLY_FILLED 继续等待；
FILLED / CANCELED / REJECTED / EXPIRED / EXPIRED_IN_MATCH 终结轮询；
未识别状态不当作终态；
终态后只交接 FillSync，不释放锁；
30 秒未解决进入 unknown 结果且保持锁；
关闭新交易不停止既有订单追踪。
```

### 16.4 FillSync 测试

必须测试：

```text
只有明确终态触发 FillSync；
NEW / PARTIALLY_FILLED / not_found / unknown 不触发；
缺 exchange_order_id 不宽泛查询；
多页成交完整拉取；
分页失败不标记 synced；
重复成交不重复插入；
payload 冲突标记 incomplete；
USDS-M 汇总口径正确；
COIN-M contracts 和 base quantity 口径正确；
手续费按资产分别汇总；
OrderFillSummary 从数据库全部 TradeFill 重算；
FILLED + 零成交标记 incomplete；
严格零成交终态可以 synced_empty；
incomplete / unknown 不释放锁；
synced / synced_empty 证据完整时调用锁服务；
锁服务拒绝时不修改成交事实；
FillSync 不修改 BinancePositionSnapshot；
关闭新交易不停止既有终态订单成交同步。
```

### 16.5 安全测试

必须测试：

```text
测试默认不访问真实 Binance；
测试不泄露 API key、secret、signature 或认证 header；
订单提交 task 禁用自动重试；
OrderStatusSync task 不自动重试同一 poll_sequence；
FillSync task 不通过任务重试重复累计成交；
业务表不保存或查询 OrchestrationRun ID；
RuntimeGuard 不在本阶段实现；
Notifications 不在本阶段直接发送 Hermes；
DeepSeek 不被调用。
```

---

## 17. 阶段验收命令

具体命令以项目实际依赖管理工具为准。

至少需要等价执行：

```text
python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py migrate
pytest tests/binance_gateway/
pytest tests/execution/
pytest tests/order_status_sync/
pytest tests/fill_sync/
pytest
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

阶段回报必须说明实际运行了哪些命令。

---

## 18. 阶段通过标准

阶段 5 通过必须满足：

```text
既有 BinanceGateway 已补齐订单提交、订单状态查询和成交查询三个受限接口；
三个受限接口均支持 USDS-M 与 COIN-M 且严格隔离市场域和凭据；
提交只使用 TRADE 凭据，状态与成交查询只使用 READ 凭据；
既有订单状态与成交追踪按订单冻结市场执行，不因 active market domain 变化而跨市场查询；
Gateway 不写订单、状态或成交业务事实；
订单状态和成交查询的有限安全读取重试不被误解为业务重试；
Execution 是唯一真实订单提交入口；
每份 PreparedOrderIntent 最多提交一次；
订单提交在 Gateway、Execution、Celery、编排和人工入口均不重试；
accepted、rejected、unknown 和提交前结果分类清楚；
unknown 不重试、不解锁；
accepted 不等于成交；
OrderStatusSync 只查询明确 OrderSubmissionAttempt；
2 秒一次、最多 30 秒的短轮询可审计；
终态只依据成功查询、身份一致和固定白名单；
not_found 不解释为提交失败；
NEW / PARTIALLY_FILLED 不终结；
明确终态后交给 FillSync；
FillSync 只消费明确终态；
TradeFill 幂等且不可变；
OrderFillSummary 从 TradeFill 全量重算；
USDS-M 和 COIN-M 成交口径正确；
synced_empty 只允许严格零成交终态；
成交证据不完整时不释放锁；
只有终态与成交证据完整时才通过锁服务释放 ActiveLock；
本阶段不生成或修改 BinancePositionSnapshot；
本阶段不调用大模型；
本阶段不直接发送 Hermes；
所有时间使用 UTC；
所有关键结果写 MySQL 和 AlertEvent；
所有测试使用 fake Gateway。
```

---

## 19. 阶段失败标准

出现以下任一情况，本阶段不得通过：

```text
订单提交、订单状态查询或成交查询任一接口没有实际实现，仅在业务层假设其存在；
为订单生命周期另建第二套 Binance client、连接配置或 Gateway app；
既有订单追踪改用当前 active market domain，或在原市场查询能力缺失时跨市场回退；
Gateway 直接写入订单、状态或成交业务事实；
订单提交发生自动重试；
同一 PreparedOrderIntent 进入 Gateway 两次；
unknown 被当作失败；
unknown 释放 ActiveLock；
not_found 被当作提交失败；
accepted 被当作已成交；
提交响应 FILLED 直接生成 TradeFill；
OrderStatusSync 释放 ActiveLock；
30 秒未解决自动解锁；
FillSync 查询失败后重新提交订单；
FILLED + 零成交被标记 synced_empty；
分页不完整被标记 synced；
TradeFill 重复累计；
相同成交身份 payload 冲突被覆盖；
COIN-M contracts 被当作 base quantity；
FillSync 修改 BinancePositionSnapshot；
业务模块绕过 BinanceGateway；
日志或事件保存密钥、签名或完整认证 header；
测试访问真实 Binance；
业务表保存或查询 OrchestrationRun ID。
```

---

## 20. 交付回报要求

阶段 5 编码完成后，回报必须说明：

```text
本阶段实现了什么；
新增和修改了哪些文件；
主要调用链路是什么；
是否写库；
是否访问 Redis；
是否访问 Binance；
是否发送 Hermes；
是否调用大模型；
是否涉及真实交易；
是否涉及 OrderPlan / CandidateOrderIntent；
是否涉及 RiskCheck / ApprovedOrderIntent；
是否涉及 ExecutionPreparation / PreparedOrderIntent；
是否涉及 Execution / OrderSubmissionAttempt；
是否涉及 OrderStatusSync / OrderStatusSyncRecord；
是否涉及 FillSync / TradeFill / OrderFillSummary；
是否写 AlertEvent；
是否修改 ActiveLock；
订单提交是否绝不重试；
unknown 如何处理；
dry-run / confirm-write 行为；
异常处理方式；
测试命令和结果；
本阶段明确不负责什么；
是否违反 project_invariants.md。
```

如测试无法运行，必须说明原因和下一步处理。

---

## 21. 下一阶段入口

阶段 5 验收通过后，下一步进入：

```text
docs/plans/orchestration_runtime_implementation_plan.md
```

该阶段应实现：

```text
PipelineOrchestrator；
OrchestrationBusinessConnector；
BusinessStepAdapter；
OrchestrationRun；
OrchestrationStepRun；
OrchestrationBusinessObjectLink；
Celery / Celery Beat 编排入口；
RuntimeGuard；
Notifications；
AlertEvent 投递链路。
```

在进入下一阶段前，订单提交、状态查询、成交同步和订单链路锁收尾必须已经具备清晰 service 合同，供编排 adapter 调用。
