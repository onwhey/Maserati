# 订单计划、风控与执行准备实施计划

## 1. 文档目的

本文档用于指导阶段 4 的代码实现。

阶段 4 的目标是实现从目标仓位快照到可提交订单请求的交易前链路：

```text
DecisionSnapshot
+ BinanceSyncRun
+ PriceSnapshot
→ OrderPlan
→ CandidateOrderIntent
→ RiskCheck
→ ApprovedOrderIntent
→ ExecutionPreparation
→ PreparedOrderIntent
```

阶段 4 完成后，系统应能：

```text
在真实交易权限允许时，把 TARGET_POSITION 转换成候选订单意图；
通过插件化 RiskCheck 审批候选订单；
在执行前用实时盘口价格做 1% price guard；
生成唯一、短期有效、可审计的 PreparedOrderIntent；
用 ActiveLock 防止同一交易身份重复订单链路。
```

本文档不实现真实订单提交，不实现订单状态查询，不实现成交同步，不实现订单最终收尾释放。

---

## 2. 阶段定位

阶段 4 是真实订单提交前的强安全边界阶段。

一句话：

```text
把“目标仓位”变成“通过风控和执行前检查、但尚未提交交易所的冻结订单请求”。
```

本阶段解决：

```text
真实交易权限关闭时不进入订单链路；
OrderPlan 如何基于明确账户与价格事实生成 CandidateOrderIntent；
ActiveLock 如何阻止重复订单链路；
RiskCheck 如何只审批候选订单而不改订单；
ApprovedOrderIntent 如何成为唯一可进入执行准备的订单意图；
ExecutionPreparation 如何做最终 price guard；
PreparedOrderIntent 如何冻结交易所可提交参数。
```

本阶段不解决：

```text
如何向 Binance 提交订单；
提交后 accepted / unknown / rejected 如何处理；
订单状态如何轮询；
成交如何同步；
ActiveLock 如何基于交易所终态和成交事实最终释放；
真实成交价如何记录；
ReviewDataset 如何使用交易事实。
```

---

## 3. 前置条件

进入本阶段前，应已完成或具备：

```text
阶段 0 项目底座；
阶段 1 行情数据与 MarketSnapshot；
阶段 2 DecisionSnapshot；
阶段 3 BinanceGateway、trade_preparation BinanceSyncRun 和 PriceSnapshot；
真实交易最终权限读取能力；
AlertEvent、AuditRecord、trace_id、trigger_source、UTC、MySQL、Redis、测试框架均可用；
测试默认使用 fake BinanceGateway；
OrderPlan 输入能拿到明确 decision_snapshot_id、binance_sync_run_id、price_snapshot_id。
```

如果阶段 3 尚未完成，本阶段只能实现模型、service skeleton、纯计算 helper 和单元测试，不得接入正式订单链路。

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
docs/requirements/order_plan.md
docs/requirements/risk_check.md
docs/requirements/execution_preparation.md
docs/requirements/binance_account_sync.md
docs/requirements/price_snapshot.md
docs/requirements/binance_gateway.md
docs/requirements/pipeline_orchestrator.md
docs/architecture/system_architecture.md
docs/architecture/data_flow_architecture.md
docs/architecture/module_boundary_architecture.md
docs/architecture/runtime_task_architecture.md
docs/architecture/testing_and_safety_architecture.md
docs/plans/foundation_implementation_plan.md
docs/plans/market_data_implementation_plan.md
docs/plans/strategy_analysis_implementation_plan.md
docs/plans/account_price_fact_implementation_plan.md
docs/plans/implementation_roadmap.md
```

如果本文档与 requirements 冲突，以 requirements 为准，并停止实现向用户确认。

---

## 5. 本阶段核心口径

### 5.1 真实交易权限检查在 OrderPlan 之前

正式编排只允许在 `OrderPlanStepAdapter` 完成真实交易权限检查后调用 OrderPlan。

真实交易权限必须同时满足：

```text
.env / settings 中部署级真实交易硬权限允许；
MySQL 中由 OpsConsole 管理的真实交易运行开关允许。
```

如果任一项关闭：

```text
不调用 OrderPlan service；
不生成 OrderPlan；
不生成 CandidateOrderIntent；
不取得 ActiveLock；
不进入 RiskCheck；
不进入 ExecutionPreparation；
返回 NO_ACTION + COMPLETE；
reason_code = real_trading_not_allowed。
```

如果权限配置不可读取，或当前业务市场与部署市场配置不一致：

```text
返回 BLOCKED + STOP；
不得进入 OrderPlan。
```

OrderPlan 本身不读取 `.env`，不读取后台运行开关，也不重复判断真实交易权限。

### 5.2 OrderPlan 是唯一订单意图生成入口

OrderPlan 是唯一把 `DecisionSnapshot.target_position_ratio` 转换为 `CandidateOrderIntent` 的模块。

禁止：

```text
StrategySignal 直接生成订单；
DecisionSnapshot 直接生成订单动作；
RiskCheck 重新设计订单；
ExecutionPreparation 修改订单数量；
Execution 直接消费 DecisionSnapshot；
任何模块绕过 OrderPlan 生成 CandidateOrderIntent。
```

### 5.3 CandidateOrderIntent 不可直接提交

`CandidateOrderIntent` 只是待风控审批的候选订单意图。

它不得：

```text
被 Execution 直接提交；
被 BinanceGateway 直接提交；
被 OpsConsole 直接提交；
被 management command 直接提交。
```

只有 RiskCheck `ALLOW` 后生成的 `ApprovedOrderIntent`，才可以进入 ExecutionPreparation。

### 5.4 RiskCheck 不缩单、不改订单

RiskCheck 只审批 OrderPlan 已生成的 CandidateOrderIntent。

RiskCheck 不得：

```text
缩小数量；
修改 side；
修改 reduce_only；
拆单；
重新生成 CandidateOrderIntent；
临时生成 fallback；
为了通过风控调整订单。
```

当前正式结果只有：

```text
ALLOW；
DENY；
BLOCKED；
FAILED。
```

只有 `ALLOW` 可以生成 `ApprovedOrderIntent`。

### 5.5 fallback_reduce_only 只能由 OrderPlan 预生成

净额反手场景下，OrderPlan 可以同时生成：

```text
primary；
fallback_reduce_only。
```

RiskCheck 只能选择：

```text
primary；
或 OrderPlan 已预生成的 fallback_reduce_only。
```

RiskCheck 不得临时改造 primary，也不得临时构造新的 reduce-only 订单。

### 5.6 ExecutionPreparation 只准备，不提交

ExecutionPreparation 负责把 ApprovedOrderIntent 冻结成 PreparedOrderIntent。

它不得：

```text
真实下单；
调用 BinanceOrderSubmissionGateway；
创建 OrderSubmissionAttempt；
查询订单状态；
查询成交；
修改订单；
修改杠杆；
修改保证金模式。
```

只有 Execution 模块可以把 PreparedOrderIntent 提交给 Binance。

### 5.7 price guard 规则

ExecutionPreparation 必须通过 Binance Gateway 查询实时盘口：

```text
BinancePublicMarketGateway.get_book_ticker
```

价格选择：

```text
BUY  → best ask；
SELL → best bid。
```

与本轮明确绑定的 PriceSnapshot.mark_price 比较：

```text
偏差 <= 1% → 允许继续；
偏差 > 1%  → BLOCKED。
```

必须使用 Decimal 或等价精确十进制。

等于 1% 必须允许继续。

盘口查询结果不是新的 PriceSnapshot，也不是成交价。

### 5.8 ActiveLock 只由 OrderPlanActiveLockService 修改

ActiveLock 是同一交易身份的唯一订单链路门锁。

锁身份：

```text
exchange
market_type
account_domain
symbol
```

本阶段实现：

```text
OrderPlan created 时取得 active 锁；
active 锁阻断新的 OrderPlan；
RiskCheck DENY / BLOCKED 且未生成 ApprovedOrderIntent 时安全释放；
ExecutionPreparation BLOCKED 且未生成 PreparedOrderIntent、未进入提交时安全释放；
ExecutionPreparation FAILED 且无法确认安全性时保持阻断或 failed；
PreparedOrderIntent PREPARED 后锁保持 active。
```

本阶段不实现：

```text
订单提交后基于交易所终态和成交事实的最终释放；
accepted / unknown / NEW / PARTIALLY_FILLED 场景的自动释放；
FillSync 完整后释放。
```

PipelineOrchestrator、RuntimeGuard 和 OpsConsole 不得直接写锁状态。

---

## 6. 本阶段实现范围

### 6.1 OrderPlan

实现 OrderPlan 正式 service。

负责：

```text
接收明确 business_request_key；
接收明确 decision_snapshot_id；
接收明确 binance_sync_run_id；
接收明确 price_snapshot_id；
校验 DecisionSnapshot = TARGET_POSITION 且 allows_order_plan；
读取指定 BinanceSyncRun 的账户、余额、持仓和交易规则；
读取指定 PriceSnapshot 的 mark_price；
校验 market_type、account_domain、symbol 一致；
校验账户和价格事实未过期；
按 USDS-M 或 COIN-M 计算目标仓位；
按 symbol rule 规范化数量；
判断 no_order_required；
生成 OrderPlan；
生成 primary CandidateOrderIntent；
净额反手时预生成 fallback_reduce_only；
在同一事务中取得 ActiveLock；
写 AlertEvent。
```

### 6.2 OrderPlanActiveLock

实现：

```text
OrderPlanActiveLock；
OrderPlanActiveLockEvent；
OrderPlanActiveLockService。
```

负责：

```text
取得锁；
阻断已有 active / failed 锁；
记录锁事件；
支持 RiskCheck 与 ExecutionPreparation 在安全条件下推进锁；
支持幂等收尾；
支持人工收尾所需字段。
```

本阶段不基于订单终态释放锁。

### 6.3 CandidateOrderIntent

实现 CandidateOrderIntent 模型与生成逻辑。

至少支持：

```text
primary；
fallback_reduce_only；
MARKET；
One-Way Mode；
positionSide = BOTH；
USDS-M quantity；
COIN-M contracts；
order_components。
```

CandidateOrderIntent 状态初始为：

```text
pending_risk_check
```

CandidateOrderIntent 不可直接执行。

### 6.4 RiskCheck 插件框架

实现：

```text
RiskRuleDefinition；
RiskRulePlugin；
RiskRuleRegistry；
RuleEngine；
RiskRuleResult；
RiskCheckIssue；
RiskCheckResult；
ApprovedOrderIntent。
```

RiskCheck service 负责：

```text
校验 CandidateOrderIntent；
校验 OrderPlan；
校验 ActiveLock；
校验 BinanceSyncRun；
校验 PriceSnapshot；
执行当前 risk_rule_set 内全部适用 active + enabled 规则；
汇总规则结果；
选择 primary 或预生成 fallback；
ALLOW 时生成 ApprovedOrderIntent；
DENY / BLOCKED / FAILED 时不生成 ApprovedOrderIntent；
按安全条件调用 ActiveLockService；
写 AlertEvent。
```

### 6.5 当前 RiskRulePlugin

本阶段至少实现需求中定义的基础规则插件：

```text
candidate_intent_valid；
order_plan_valid；
order_components_valid；
business_input_binding_valid；
binance_sync_run_consumable；
snapshot_integrity；
market_identity_consistency；
one_way_position_mode_required；
active_lock_consistency；
price_snapshot_present；
price_snapshot_fresh；
usds_m_balance_available；
coin_m_balance_available；
symbol_rule_min_notional；
symbol_rule_quantity_step；
symbol_rule_max_quantity；
symbol_rule_max_notional；
available_margin_check；
reverse_fallback_reduce_only。
```

新增规则必须通过插件机制扩展，不得在 RuleEngine 中堆大型 if / elif。

### 6.6 ApprovedOrderIntent

只有 RiskCheck `ALLOW` 可以生成 ApprovedOrderIntent。

ApprovedOrderIntent 必须：

```text
引用 RiskCheckResult；
引用实际被批准的 CandidateOrderIntent；
冻结 side、数量、单位、reduce_only、order_type；
冻结账户事实、价格事实、规则集和 hash；
设置有效期；
不可修改核心订单参数；
不能绕过 ExecutionPreparation。
```

### 6.7 ExecutionPreparation

实现 ExecutionPreparation 正式 service。

本阶段还必须在阶段 3 已有 `apps/binance_gateway/` 中补齐 `BinancePublicMarketGateway.get_book_ticker`。阶段 1 只实现 K 线和服务器时间，阶段 3 只实现标记价格和交易规则，因此不得假设盘口接口已经存在。

`get_book_ticker` 必须：

```text
每次业务调用实际请求 Binance，不返回 Gateway 历史缓存盘口；
按明确 market_type 选择 USDS-M 或 COIN-M adapter；
返回标准化 best bid、best ask、观测时间和 Gateway 尝试次数；
只提供盘口事实，不按 BUY / SELL 选择价格；
不计算 1% 偏差，不决定是否允许执行；
不写 PriceSnapshot、PreparedOrderIntent 或其他业务事实；
提供可覆盖成功、无效盘口和读取失败的 fake gateway。
```

负责：

```text
接收 approved_order_intent_id；
校验完整上游链路；
校验 PriceSnapshot；
校验 RiskCheck 使用的 BinanceSyncRun；
校验 ActiveLock；
通过 BinancePublicMarketGateway.get_book_ticker 查询实时盘口；
BUY 选择 best ask；
SELL 选择 best bid；
执行 1% price guard；
复核 reduce-only；
复核 symbol rule；
冻结交易所可提交参数；
生成 ExecutionPreparationResult；
生成 PreparedOrderIntent；
生成稳定 client_order_id；
生成稳定 idempotency_key；
写 AlertEvent。
```

### 6.8 PreparedOrderIntent

PreparedOrderIntent 表示尚未提交交易所的待执行请求。

它必须：

```text
一对一绑定 ApprovedOrderIntent；
一对一绑定 ExecutionPreparationResult；
保存冻结订单参数；
保存 client_order_id；
保存 idempotency_key；
保存 price guard 证据；
短期有效；
过期后不得恢复或复用；
不能被重复生成。
```

PreparedOrderIntent 不表示 Binance 已接收订单，不表示已经成交。

---

## 7. 建议代码模块

具体 Django app 名称可在编码阶段最终确定，但建议：

```text
apps/binance_gateway/（扩展既有 app，不新建第二套 Gateway）
apps/order_plan/
apps/risk_check/
apps/execution_preparation/
```

其中：

```text
apps/binance_gateway/ 补齐 get_book_ticker 受限公共市场读取能力，不写业务事实；
apps/order_plan/ 保存 OrderPlan、CandidateOrderIntent、ActiveLock 和锁服务；
apps/risk_check/ 保存风控规则、插件、结果和 ApprovedOrderIntent；
apps/execution_preparation/ 保存 ExecutionPreparationResult 和 PreparedOrderIntent。
```

业务逻辑必须放在：

```text
service 层；
domain 层；
必要的纯计算 helper。
```

禁止把复杂逻辑写入：

```text
Django model；
Celery task；
management command；
view；
serializer。
```

---

## 8. 数据库迁移范围

### 8.1 OrderPlan 相关

建议创建：

```text
OrderPlan；
CandidateOrderIntent；
OrderPlanActiveLock；
OrderPlanActiveLockEvent。
```

### 8.2 RiskCheck 相关

建议创建：

```text
RiskRuleDefinition；
RiskRuleSet 或等价规则集合对象；
RiskRuleResult；
RiskCheckIssue；
RiskCheckResult；
ApprovedOrderIntent。
```

### 8.3 ExecutionPreparation 相关

建议创建：

```text
ExecutionPreparationResult；
PreparedOrderIntent。
```

### 8.4 共同建模要求

所有正式对象必须：

```text
保存直接上游业务外键；
保存 business_request_key；
保存 market_type、account_domain、symbol；
保存 trace_id / trigger_source；
保存 hash / params / config snapshot；
保存 status / reason_code；
保存 AlertEvent 引用或可追溯事件 key；
使用 UTC 时间；
支持幂等唯一约束。
```

业务表不得保存或查询：

```text
OrchestrationRun ID；
StepRun ID；
步骤序号；
编排内部状态。
```

编排关联由 `OrchestrationBusinessObjectLink` 负责，不替代业务外键。

---

## 9. 配置项

所有新增配置必须进入 `.env.example` 并带中文注释。

### 9.1 OrderPlan 配置

```text
ORDER_PLAN_ENABLED
ORDER_PLAN_SUPPORTED_MARKET_TYPES
ORDER_PLAN_TARGET_NOTIONAL_BASIS=current_equity
ORDER_PLAN_MAX_TARGET_NOTIONAL_TO_EQUITY_RATIO=3.0
ORDER_PLAN_MIN_REBALANCE_NOTIONAL=20
ORDER_PLAN_SUPPORTED_POSITION_MODE=one_way
ORDER_PLAN_SUPPORTED_ORDER_TYPES=MARKET,LIMIT
```

### 9.2 RiskCheck 配置

```text
RISK_CHECK_ENABLED
RISK_CHECK_RULE_SET
RISK_CHECK_MARGIN_BUFFER_RATIO
RISK_CHECK_RULE_FAILURE_MODE
RISK_CHECK_APPROVED_INTENT_TTL_SECONDS
```

具体规则参数保存于版本化 RiskRuleDefinition，不得散落在 RuleEngine、task 或 settings 中。

### 9.3 ExecutionPreparation 配置

```text
EXECUTION_PREPARATION_ENABLED
EXECUTION_PREPARATION_MAX_PRICE_DEVIATION_BPS=100
PREPARED_ORDER_INTENT_TTL_SECONDS=30
EXECUTION_PREPARATION_SUPPORTED_ORDER_TYPES=MARKET,LIMIT
EXECUTION_PREPARATION_SUPPORTED_POSITION_MODE=one_way
```

Gateway 的 base URL、超时、有限重试、限频和熔断配置属于 BinanceGateway，不在本模块重复配置。

---

## 10. 实施顺序

### 10.1 实现 OrderPlan 模型与锁模型

执行内容：

```text
创建 OrderPlan；
创建 CandidateOrderIntent；
创建 OrderPlanActiveLock；
创建 OrderPlanActiveLockEvent；
添加唯一约束和索引；
生成 migration。
```

验收重点：

```text
同一交易身份只能有一个 active 锁；
created OrderPlan 与 ActiveLock 同事务生成；
no_order_required / blocked / failed 不留下 active 锁。
```

### 10.2 实现 OrderPlan 计算与数量规范化

执行内容：

```text
实现 USDS-M 目标数量计算；
实现 COIN-M 目标 contracts 计算；
实现 Decimal helper；
实现 step_size 向零取整；
实现 min_quantity / max_quantity / min_notional 校验；
实现 no_order_required；
实现 order_components；
实现 fallback_reduce_only 生成。
```

验收重点：

```text
observed_exchange_leverage 不参与目标仓位计算；
available_balance 不用于缩小订单；
COIN-M 必须使用 contract_size；
净额反手 primary 与 fallback 结构清楚。
```

### 10.3 实现 OrderPlanService 与 Adapter 形状

执行内容：

```text
实现 OrderPlanStepAdapter 权限检查形状；
实现 OrderPlanService；
校验 DecisionSnapshot；
校验 BinanceSyncRun；
校验 PriceSnapshot；
校验 market identity；
实现幂等；
写 AlertEvent。
```

验收重点：

```text
真实交易权限关闭时 adapter 不调用 OrderPlan；
NO_TRADE / NO_TARGET_CHANGE 不能进入 OrderPlan；
OrderPlan 不访问 Binance；
OrderPlan 不读取 latest account 或 latest price。
```

### 10.4 实现 RiskCheck 插件基础设施

执行内容：

```text
创建 RiskRuleDefinition；
创建规则集合；
实现 RiskRulePlugin；
实现 RiskRuleRegistry；
实现 RuleEngine；
实现 RiskRuleResult；
实现 RiskCheckIssue；
实现规则说明文档路径或等价元数据。
```

验收重点：

```text
新增规则不修改 RuleEngine 主流程；
缺少 plugin 不放行；
只执行当前 risk_rule_set 内 active + enabled 规则。
```

### 10.5 实现基础 RiskRulePlugin

执行内容：

```text
实现输入绑定规则；
实现 ActiveLock 规则；
实现账户与快照规则；
实现 PriceSnapshot 规则；
实现 order_components 规则；
实现 USDS-M 保证金规则；
实现 COIN-M 保证金规则；
实现 symbol rule 规则；
实现 reverse fallback 规则。
```

验收重点：

```text
违反风险上限时 DENY；
事实缺失或不一致时 BLOCKED；
系统异常时 FAILED；
RiskCheck 不改订单。
```

### 10.6 实现 RiskCheckService

执行内容：

```text
校验 CandidateOrderIntent；
校验 OrderPlan；
校验 ActiveLock；
执行规则；
聚合结果；
选择 primary 或 fallback；
生成 RiskCheckResult；
ALLOW 时生成 ApprovedOrderIntent；
DENY / BLOCKED / FAILED 时不生成 ApprovedOrderIntent；
按安全条件推进 ActiveLock；
写 AlertEvent；
实现 dry-run。
```

验收重点：

```text
ALLOW 才生成 ApprovedOrderIntent；
DENY / BLOCKED / FAILED 不生成 ApprovedOrderIntent；
fallback 只能选择预生成对象；
所有正式结果写 AlertEvent。
```

### 10.7 补齐 BinanceGateway 实时盘口接口

执行内容：

```text
在既有 BinancePublicMarketGateway 中实现 get_book_ticker；
复用既有市场域、endpoint family、超时、有限安全读取重试、限频、熔断和脱敏设施；
标准化 best bid、best ask、观测时间和 Gateway 尝试次数；
实现对应 fake gateway；
确保 Gateway 不缓存并返回历史盘口，不写业务事实。
```

验收重点：

```text
USDS-M 与 COIN-M 盘口 endpoint 不混用；
每次业务调用实际发出本次 Binance 请求；
Gateway 不按订单方向选择价格；
Gateway 不执行 price guard；
Gateway 不创建或覆盖 PriceSnapshot；
未新增第二套 Binance client 或连接配置。
```

### 10.8 实现 ExecutionPreparation 模型

执行内容：

```text
创建 ExecutionPreparationResult；
创建 PreparedOrderIntent；
添加唯一约束；
添加 client_order_id 唯一约束；
添加 idempotency_key 唯一约束；
生成 migration。
```

验收重点：

```text
ApprovedOrderIntent 与 PreparedOrderIntent 一对一；
同一 ApprovedOrderIntent 并发不会生成两份准备结果；
PreparedOrderIntent 不是订单提交记录。
```

### 10.9 实现 ExecutionPreparationService

执行内容：

```text
校验 ApprovedOrderIntent；
校验 RiskCheckResult；
校验 CandidateOrderIntent；
校验 OrderPlan；
校验 PriceSnapshot；
校验 BinanceSyncRun；
校验 ActiveLock；
调用 BinancePublicMarketGateway.get_book_ticker；
按 side 选择 best ask / best bid；
执行 1% price guard；
复核 reduce-only；
复核 symbol rule；
生成 client_order_id；
生成 idempotency_key；
生成 ExecutionPreparationResult；
生成 PreparedOrderIntent；
推进状态；
写 AlertEvent。
```

验收重点：

```text
偏差等于 1% 允许；
偏差大于 1% 阻断；
盘口查询结果不覆盖 PriceSnapshot；
不调用 BinanceOrderSubmissionGateway；
不创建 OrderSubmissionAttempt。
```

### 10.10 建立薄入口

允许建立：

```text
OrderPlan management command 或 adapter；
RiskCheck management command 或 adapter；
ExecutionPreparation management command 或 adapter；
Celery task 薄入口。
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
实现订单计算；
实现风控规则；
实现 price guard；
直接改锁；
调用订单提交 Gateway。
```

### 10.11 建立测试

测试必须覆盖：

```text
OrderPlan；
CandidateOrderIntent；
ActiveLock；
RiskCheck 插件；
ApprovedOrderIntent；
ExecutionPreparation；
PreparedOrderIntent；
真实交易权限检查；
price guard；
幂等；
并发；
AlertEvent；
禁止真实 Binance 下单。
```

---

## 11. 编排边界

本阶段不实现完整 PipelineOrchestrator。

但必须为后续编排提供明确 adapter 合同。

### 11.1 OrderPlanStepAdapter

输入：

```text
decision_snapshot_id；
binance_sync_run_id；
price_snapshot_id；
business_request_key；
trace_id；
trigger_source。
```

职责：

```text
检查真实交易权限；
检查市场配置可读且一致；
权限允许时调用 OrderPlanService；
权限关闭时返回 NO_ACTION + COMPLETE；
权限不可读或市场不一致时返回 BLOCKED + STOP。
```

### 11.2 RiskCheckStepAdapter

输入：

```text
order_plan_id；
candidate_order_intent_id；
binance_sync_run_id；
price_snapshot_id；
active_lock_id；
risk_rule_set；
business_request_key；
trace_id；
trigger_source。
```

职责：

```text
调用 RiskCheckService；
理解 ALLOW / DENY / BLOCKED / FAILED；
ALLOW 时继续 ExecutionPreparation；
其他结果按统一合同停止；
返回 risk_check_result_id 和 approved_order_intent_id。
```

### 11.3 ExecutionPreparationStepAdapter

输入：

```text
approved_order_intent_id；
business_request_key；
reference_time_utc；
trace_id；
trigger_source。
```

职责：

```text
调用 ExecutionPreparationService；
理解 PREPARED / BLOCKED / FAILED / EXPIRED；
PREPARED 时继续后续 Execution 阶段；
其他结果按统一合同停止；
返回 execution_preparation_result_id 和 prepared_order_intent_id。
```

---

## 12. ActiveLock 边界

本阶段实现 ActiveLock 的取得和提交前安全推进。

可以释放：

```text
RiskCheck DENY，且未生成 ApprovedOrderIntent；
RiskCheck BLOCKED，且未生成 ApprovedOrderIntent；
RiskCheck FAILED，且事务确认未生成 ApprovedOrderIntent、未进入执行准备；
ExecutionPreparation BLOCKED，且没有 PreparedOrderIntent、没有进入 Execution；
ExecutionPreparation FAILED，且能够证明没有形成可提交请求、没有进入 Execution；
PreparedOrderIntent EXPIRED，且确认从未提交。
```

不得释放：

```text
ApprovedOrderIntent 已生成且进入 ExecutionPreparation；
PreparedOrderIntent 已生成且未过期；
PreparedOrderIntent 可能已进入 Execution；
OrderSubmissionAttempt accepted；
OrderSubmissionAttempt unknown；
OrderStatusSync unknown；
订单状态 NEW；
订单状态 PARTIALLY_FILLED；
只因为编排结束；
只因为超时；
只因为持仓变化。
```

订单提交后的最终锁释放留给后续订单状态和成交闭环阶段。

---

## 13. dry-run 规则

### 13.1 OrderPlan dry-run

可以：

```text
读取明确 DecisionSnapshot、BinanceSyncRun 和 PriceSnapshot；
执行相同计算；
返回候选订单预览。
```

不得：

```text
写 OrderPlan；
写 CandidateOrderIntent；
取得 ActiveLock；
写正式 AlertEvent；
进入 RiskCheck。
```

### 13.2 RiskCheck dry-run

可以：

```text
执行相同输入校验；
执行相同插件规则；
返回风控摘要。
```

不得：

```text
写 RiskCheckResult；
写 RiskRuleResult；
生成 ApprovedOrderIntent；
修改 ActiveLock；
写正式 AlertEvent；
进入 ExecutionPreparation。
```

### 13.3 ExecutionPreparation dry-run

当前阶段不实现 ExecutionPreparation dry-run。

原因：

```text
ExecutionPreparation 会生成 client_order_id、PreparedOrderIntent 和短期有效执行请求；
需求文件明确当前阶段不生成预览版 ExecutionPreparationResult、PreparedOrderIntent 或 client_order_id。
```

---

## 14. AlertEvent 边界

本阶段只写 AlertEvent，不直接发送 Hermes。

必须写 AlertEvent 的典型场景：

```text
真实交易权限关闭；
真实交易权限不可读取；
OrderPlan no_order_required；
OrderPlan blocked；
OrderPlan failed；
CandidateOrderIntent generated；
ActiveLock conflict；
RiskCheck ALLOW；
RiskCheck DENY；
RiskCheck BLOCKED；
RiskCheck FAILED；
fallback_reduce_only selected；
ApprovedOrderIntent generated；
ExecutionPreparation PREPARED；
ExecutionPreparation BLOCKED；
ExecutionPreparation FAILED；
ExecutionPreparation EXPIRED；
price guard blocked；
PreparedOrderIntent generated。
```

通知语义必须明确区分：

```text
候选订单意图；
风控审批；
审批通过订单意图；
执行前检查；
待提交订单请求。
```

不得把任何本阶段通知写成：

```text
订单已提交；
交易所已接受；
已经成交；
仓位已变化。
```

---

## 15. Redis 使用边界

本阶段可以使用 Redis：

```text
短期幂等锁；
短期并发锁；
Celery broker / result backend。
```

Redis 不得作为：

```text
ActiveLock 唯一事实来源；
OrderPlan 唯一事实来源；
RiskCheckResult 唯一事实来源；
PreparedOrderIntent 唯一事实来源；
账户事实来源；
价格事实来源。
```

ActiveLock 必须以 MySQL 和数据库事务为最终事实。

---

## 16. 外部服务边界

本阶段唯一允许的 Binance 请求是：

```text
ExecutionPreparation
→ BinancePublicMarketGateway.get_book_ticker
```

禁止：

```text
OrderPlan 请求 Binance；
RiskCheck 请求 Binance；
ExecutionPreparation 调用账户签名接口；
ExecutionPreparation 调用订单提交接口；
任何模块提交订单；
任何模块查询订单状态；
任何模块查询成交；
任何模块修改杠杆、保证金模式或持仓模式；
任何模块调用 DeepSeek；
任何模块直接发送 Hermes。
```

自动化测试必须使用 fake BinanceGateway，不得访问真实 Binance。

---

## 17. 测试计划

### 17.1 OrderPlan 测试

必须测试：

```text
真实交易权限关闭时 adapter 不调用 OrderPlan；
NO_TRADE / NO_TARGET_CHANGE 传入时 blocked；
账户或价格市场身份不一致时 blocked；
PriceSnapshot 过期时 blocked；
One-Way Mode 正常计算；
Hedge Mode 和 unknown mode blocked；
USDS-M 目标数量计算；
COIN-M contracts 计算；
COIN-M 缺 contract_size fail-closed；
observed_exchange_leverage 不参与目标仓位计算；
available_balance 不用于缩小订单；
数量按 step_size 向零取整；
低于 min_rebalance_notional 时 no_order_required；
净额反手生成 primary 和 fallback_reduce_only；
created OrderPlan 与 ActiveLock 同事务生成；
active 锁阻断下一周期 OrderPlan；
相同 business_request_key 幂等。
```

### 17.2 ActiveLock 测试

必须测试：

```text
同一身份只能有一个 active 锁；
released 锁允许新 OrderPlan 取得；
failed 锁继续阻断；
RiskCheck DENY / BLOCKED 安全释放；
ExecutionPreparation BLOCKED 安全释放；
PREPARED 后保持 active；
无法确认是否提交时不释放；
PipelineOrchestrator 不能直接改锁；
并发取得锁只有一条有效订单链路。
```

### 17.3 RiskCheck 测试

必须测试：

```text
只消费 CandidateOrderIntent；
输入业务外键一致性；
ActiveLock 必须 active 且绑定当前 OrderPlan；
ops_display 账户批次不可消费；
PriceSnapshot 过期 BLOCKED；
RiskCheck 不修改 side、数量、reduce_only 或订单类型；
违反风险上限 DENY，不缩单；
primary 全部通过选择 primary；
primary 新增风险不通过、fallback 通过时选择 fallback；
fallback 不是 RiskCheck 临时生成；
increase_risk 缺 leverage 时 BLOCKED；
reduce_risk 不因 leverage 缺失阻断；
USDS-M 保证金计算；
COIN-M 原生保证金计算；
COIN-M 缺 contract_size BLOCKED；
RuleEngine 不包含具体 rule_code 分支；
ALLOW 生成唯一 ApprovedOrderIntent；
DENY / BLOCKED / FAILED 不生成 ApprovedOrderIntent；
dry-run 不写库、不告警、不生成 ApprovedOrderIntent。
```

### 17.4 ExecutionPreparation 测试

必须测试：

```text
get_book_ticker 对 USDS-M 与 COIN-M 选择正确且隔离的 endpoint family；
get_book_ticker 每次业务调用实际请求 Binance，不返回历史缓存盘口；
get_book_ticker 的有限安全读取重试次数可审计；
Gateway 不按 BUY / SELL 选择价格、不执行 1% 判断、不写业务事实；
只消费有效 ApprovedOrderIntent；
上游业务外键或市场身份不一致时 blocked；
只读取明确 PriceSnapshot；
PriceSnapshot 过期 blocked；
只读取明确 BinanceSyncRun；
不选择 latest succeeded 或 ops_display 批次；
BUY 选择 best ask；
SELL 选择 best bid；
book ticker 查询失败 blocked；
bid / ask 缺失、非正数或 ask 小于 bid blocked；
偏差 0% 通过；
偏差 0.9999% 通过；
偏差恰好 1% 通过；
偏差大于 1% blocked；
上涨和下跌均按绝对偏差检查；
盘口结果不创建或覆盖 PriceSnapshot；
reduce-only 不成立 blocked；
交易规则不满足 blocked 且不改数量；
成功只生成一份 PreparedOrderIntent；
client_order_id 和 idempotency_key 唯一且稳定；
同一 ApprovedOrderIntent 并发只有一次进入盘口查询；
幂等重放不重新查价；
PreparedOrderIntent TTL 从实时盘口价格观测时间开始；
PREPARED 后 ActiveLock 保持 active；
BLOCKED 确认未提交后释放 ActiveLock；
FAILED 安全性不明时 ActiveLock 继续阻断；
不调用 BinanceOrderSubmissionGateway；
不创建 OrderSubmissionAttempt；
不修改 side、quantity、reduce_only、杠杆或保证金模式。
```

### 17.5 安全测试

必须测试：

```text
测试默认不访问真实 Binance；
测试不提交订单；
测试不查询订单状态；
测试不查询成交；
AlertEvent 不含密钥、签名或完整认证 header；
业务表不保存或查询 OrchestrationRun ID；
Redis 不可用不破坏 MySQL 事实；
真实交易权限关闭不会生成订单链路或锁。
```

---

## 18. 阶段验收命令

具体命令以项目实际依赖管理工具为准。

至少需要等价执行：

```text
python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py migrate
pytest tests/binance_gateway/
pytest tests/order_plan/
pytest tests/risk_check/
pytest tests/execution_preparation/
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

## 19. 阶段通过标准

阶段 4 通过必须满足：

```text
既有 BinanceGateway 已补齐 get_book_ticker 受限接口；
get_book_ticker 支持 USDS-M 与 COIN-M 且不混用市场域；
盘口 Gateway 只返回事实，不选择订单方向价格、不执行 price guard、不写业务事实；
真实交易权限关闭时不调用 OrderPlan；
NO_TRADE / NO_TARGET_CHANGE 不进入 OrderPlan；
OrderPlan 是目标仓位到 CandidateOrderIntent 的唯一入口；
OrderPlan 输入账户和价格事实均来自明确业务对象；
OrderPlan 不访问 Binance；
USDS-M 与 COIN-M 计算口径正确；
数量在风控前已按交易规则规范化；
净额反手具有 primary 和 fallback_reduce_only；
CandidateOrderIntent 不可直接提交；
ActiveLock 是新订单链路统一门锁；
RiskCheck 插件架构可扩展；
RiskCheck 不缩单、不改数量、不生成订单；
RiskCheck DENY / BLOCKED / FAILED 不生成 ApprovedOrderIntent；
ApprovedOrderIntent 不能绕过 ExecutionPreparation；
ExecutionPreparation 使用 BinanceGateway 查询实时盘口；
BUY 用 best ask，SELL 用 best bid；
价格偏差 <= 1% 允许，> 1% 阻断；
PreparedOrderIntent 唯一、幂等、短期有效；
PREPARED 后 ActiveLock 保持 active；
本阶段不调用订单提交接口；
本阶段不创建 OrderSubmissionAttempt、OrderStatusSyncRecord、TradeFill；
测试默认不访问真实 Binance；
所有时间使用 UTC。
```

---

## 20. 阶段失败标准

出现以下任一情况，本阶段不得通过：

```text
ExecutionPreparation 调用一个未实际实现的 get_book_ticker 接口；
为实时盘口另建第二套 Binance client、连接配置或 Gateway app；
Gateway 返回历史缓存盘口，或代替 ExecutionPreparation 选择价格和执行 1% 判断；
真实交易权限关闭仍调用 OrderPlan；
权限关闭仍生成 CandidateOrderIntent 或 ActiveLock；
OrderPlan 访问 Binance；
OrderPlan 使用 latest 账户或 latest 价格兜底；
RiskCheck 修改订单数量、方向或 reduce_only；
RiskCheck 临时生成 fallback；
DENY / BLOCKED / FAILED 生成 ApprovedOrderIntent；
ExecutionPreparation 提交订单；
ExecutionPreparation 调用 BinanceOrderSubmissionGateway；
ExecutionPreparation 用 last price、index price 或 Kline close 替代盘口；
偏差等于 1% 被阻断；
盘口查询结果覆盖 PriceSnapshot；
PreparedOrderIntent 过期后被恢复；
PREPARED 后释放 ActiveLock；
accepted / unknown / NEW / PARTIALLY_FILLED 场景在本阶段被自动释放锁；
PipelineOrchestrator 直接修改 ActiveLock；
业务表保存或查询 OrchestrationRun ID；
测试访问真实 Binance；
本阶段查询订单状态、查询成交或修改交易所配置。
```

---

## 21. 交付回报要求

阶段 4 编码完成后，回报必须说明：

```text
本阶段实现了什么；
新增和修改了哪些文件；
主要调用链路是什么；
是否写库；
是否访问 Redis；
是否访问 Binance；
是否发送 Hermes；
是否调用大模型；
是否涉及交易执行；
是否涉及真实交易；
是否涉及 DecisionSnapshot；
是否涉及 Binance Account Sync；
是否涉及 PriceSnapshot；
是否涉及 OrderPlan / CandidateOrderIntent；
是否涉及 RiskCheck / ApprovedOrderIntent；
是否涉及 ExecutionPreparation / PreparedOrderIntent；
是否涉及 Execution / OrderSubmissionAttempt；
是否涉及 OrderStatusSync / FillSync；
是否写 AlertEvent；
是否修改 ActiveLock；
dry-run / confirm-write 行为；
异常处理方式；
测试命令和结果；
本阶段明确不负责什么；
是否违反 project_invariants.md。
```

如测试无法运行，必须说明原因和下一步处理。

---

## 22. 下一阶段入口

阶段 4 验收通过后，下一步进入订单提交、状态与成交闭环阶段。

该后续阶段的计划文件为：

```text
docs/plans/order_lifecycle_implementation_plan.md
```

该后续阶段应实现：

```text
Execution；
OrderSubmissionAttempt；
BinanceOrderSubmissionGateway 受限调用；
OrderStatusSync；
FillSync；
TradeFill；
OrderFillSummary；
订单提交后的 ActiveLock 收尾。
```

在进入后续阶段前，不应实现真实订单提交、订单状态查询、成交同步或基于交易所终态的自动解锁。
