# AGENTS.md

## 1. 项目定位

本项目是一个中低频趋势跟踪自动交易系统。

系统目标是构建一个从行情事实、特征、信号、目标仓位决策、账户事实、价格事实、订单计划、风控审批、执行准备、交易执行、订单追踪、成交同步、运行巡检、通知审计、复盘数据集导出和后台运维组成的自动交易闭环。

当前正式主链路为：

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
→ TARGET_POSITION：PriceSnapshot
→ OrderPlanStepAdapter 真实交易权限检查
→ OrderPlan
→ CandidateOrderIntent
→ RiskCheck
→ ApprovedOrderIntent
→ ExecutionPreparation
→ PreparedOrderIntent
→ Execution
→ OrderSubmissionAttempt
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

LIMIT 订单到期仍未终态时，存在独立周期收尾分支：

```text
OrderCycleCloseout / OrderCancelAttempt
→ OrderStatusSync
→ FillSync
→ ActiveLock 安全收尾判断
```

横切能力：

```text
PipelineOrchestrator
RuntimeGuard
Notifications / AlertEvent
```

后置复盘和后台能力：

```text
OpsConsole
ReviewDataset
```

后置复盘和后台能力不属于自动交易主链路必跑步骤。

本项目允许自动交易，但真实交易必须经过结构化策略决策、账户事实读取、价格事实确认、订单计划、风控审批、执行前最终检查、交易执行边界、真实交易权限、AlertEvent、日志审计和复盘追踪。

本项目不是：

```text
人工喊单系统
大模型实时交易系统
大模型喊单系统
单纯回测脚本
单纯交易所 API 下单脚本
单纯前端展示平台
自动策略优化平台
自动参数调优系统
```

大模型不得参与实时交易决策。

## 2. AGENTS.md 职责边界

本文档只定义 Codex 的工作纪律、文档优先级、开发安全规则和最高级禁止行为。

本文档不承载完整系统设计，不重复维护完整模块设计，不定义数据库字段、接口路径、任务名称或具体算法。

具体内容以以下文档为准：

```text
项目范围：docs/requirements/project_scope.md
系统能力：docs/requirements/system_capabilities.md
核心对象：docs/requirements/core_contracts.md
项目基础：docs/requirements/project_foundation.md
模块需求：docs/requirements/*.md
系统架构：docs/architecture/*.md
开发计划：docs/plans/*.md
架构决策：docs/decisions/*.md
```

新增普通业务模块时，优先修改 requirements / architecture / plans。

只有当新增内容影响以下事项时，才修改 AGENTS.md：

```text
Codex 工作纪律
文档优先级
真实交易红线
最高禁止项
开发流程
回报要求
```

## 3. 技术底座

本项目技术底座：

```text
Python 3.12.x
Django 5.2.x LTS
MySQL
Redis
Celery
Celery Beat
Python logging / Django logging
pytest / pytest-django 或 Django test framework
Node.js LTS（仅 OpsConsole 前端）
Next.js + TypeScript（仅 OpsConsole 前端）
shadcn/ui
Recharts
```

版本约束：

```toml
requires-python = ">=3.12,<3.13"
```

```text
Django>=5.2,<5.3
celery>=5.6,<5.7
```

不得随意升级或降级核心版本，除非先有架构决策文档并完成兼容性验证。

Python 依赖版本应在 `pyproject.toml` 中使用兼容范围；OpsConsole 前端依赖应写入 `package.json`；后端与前端锁文件分别固定实际安装版本。

## 4. 文档优先级

开发前必须先阅读并遵守：

```text
docs/requirements/project_scope.md
docs/requirements/system_capabilities.md
docs/requirements/core_contracts.md
docs/requirements/project_foundation.md
docs/requirements/*.md
docs/architecture/*.md
docs/decisions/*.md
docs/plans/*.md
```

文档优先级：

```text
project_invariants / 系统红线
> decisions
> requirements
> architecture
> plans
> implementation
> code
```

如果文档之间冲突，以更高优先级文档为准，并向用户说明冲突，不得自行猜测。

本项目以当前仓库文档为唯一实现依据。

如果 `docs/decisions` 或 `docs/plans` 目录尚未存在，表示该阶段尚未开始；Codex 不得因此自行猜测实现方案，也不得绕过已有 requirements / architecture 文档。

## 5. 当前交易范围红线

数据采集范围与交易运行范围必须区分。

数据采集 P0 范围：

```text
交易所：Binance
市场类型：USDS-M Futures
交易品种：BTCUSDT
数据类型：已收盘 4h / 1d K 线
```

数据采集域不受 active market domain 影响。

交易模块必须支持：

```text
USDS-M
COIN-M
```

交易运行链路同一时刻只能存在一个 active market domain。

active market domain 属于部署级硬配置，后台不得热切换。

切换 active market domain 必须通过部署配置、服务重启和完整验证。

USDS-M 与 COIN-M 的账户事实、持仓事实、交易规则、价格事实和数量计算公式不得混用。

## 6. 最高交易红线

以下规则任何时候不得违反：

```text
特征层不得生成交易信号。
原子信号不得直接下单。
DomainSignal 不得生成订单动作。
MarketRegime 不得生成订单动作。
StrategyRouting 不得执行策略算法，不得生成订单动作。
StrategySignal 不等于交易决策，不得直接下单。
DecisionSnapshot 只表达目标仓位语义，不得生成订单动作。
DecisionSnapshot 不得直接读取账户、持仓或 BinanceSyncRun。
OrderPlan 是唯一把目标仓位转换为 CandidateOrderIntent 的模块。
OrderPlan 不得访问 Binance，不得真实下单，不得做最终风控审批。
RiskCheck 只审批 CandidateOrderIntent，不直接审批 DecisionSnapshot。
RiskCheck 不得生成新的 CandidateOrderIntent，不得任意修改订单数量。
RiskCheck 不得真实下单，不得撤单，不得修改杠杆，不得修改保证金模式。
ApprovedOrderIntent 只是风控审批通过的订单意图，不等于交易所订单。
ExecutionPreparation 只做执行前最终检查和 price guard，不得真实下单。
Execution 是唯一允许提交真实订单的模块。
OrderCycleCloseout 只允许对既有、已提交且仍未终态的 LIMIT 订单执行周期收尾撤单，不得提交新订单、改单、追单或释放 ActiveLock。
OrderStatusSync 不得重新提交订单，不得生成 TradeFill。
FillSync 不得提交订单，不得根据成交汇总直接生成账户快照。
Hermes 不得触发交易。
大模型不得参与实时交易决策。
不得绕过 OrderPlan。
不得绕过 RiskCheck。
不得绕过 ApprovedOrderIntent。
不得绕过 ExecutionPreparation。
不得绕过 Execution。
真实交易默认关闭，必须显式配置开启。
系统不得自动调整杠杆。
当前阶段不得实现模拟交易运行模式，不得把 dry-run 或回测结果写入 real trading 业务对象。
```

如果文档没有明确允许真实交易，默认不得执行真实交易。

## 7. 策略分析链路纪律

正式策略分析链路为：

```text
FeatureLayer
→ AtomicSignal
→ DomainSignal
→ MarketRegime
→ StrategyRouting
→ StrategySignal
→ StrategySignalQuality
→ DecisionSnapshot
```

Codex 实现策略分析相关模块时必须遵守：

```text
FeatureLayer 只计算特征，不生成交易信号。
AtomicSignal 只生成原子判断，不生成订单动作。
DomainSignal 只聚合同类原子信号，形成领域级市场事实。
MarketRegime 基于领域事实识别市场环境，不选择订单动作。
StrategyRouting 基于市场环境和路由配置选择 StrategyDefinition，不执行策略算法。
StrategySignal 执行已选定策略，生成标准化策略级判断，不等于目标仓位或订单动作。
StrategySignalQuality 只判断策略信号是否具备下游消费条件。
DecisionSnapshot 只表达 target_intent / target_position_ratio 等目标仓位语义。
```

正式主链路只能运行已批准的 StrategyAnalysisRelease。

算法计算规则必须与业务流程解耦。特征、原子信号、领域信号、市场环境、策略路由、策略信号和目标仓位决策中的可变算法，应通过对应 calculator / definition / release 机制管理。

implementation 文档只用于记录复杂内部逻辑和实际实现说明，不得替代 requirements。

## 8. 真实交易权限纪律

系统不建立独立的运行权限业务模块。

真实交易权限模型：

```text
.env / Django settings = 真实交易部署级硬权限
MySQL = 后台真实交易运行开关
effective_real_trading_permission = deployment_real_trading_permission AND runtime_real_trading_permission
```

规则：

```text
.env 禁止真实交易时，后台不能放行。
.env 允许时，MySQL 运行开关才能决定下一轮是否允许进入 OrderPlan。
后台不得写 .env。
后台不得管理 API key 或 secret。
后台不得热切 active market domain。
权限检查必须早于 OrderPlan 和 ActiveLock。
OrderPlanStepAdapter 在进入 OrderPlan 前只检查一次真实交易权限。
检查通过后，本轮后续步骤不重新读取 MySQL 运行开关。
后台开关变化只影响下一次进入 OrderPlan 的检查。
Execution、OrderStatusSync 和 FillSync 不重新读取真实交易运行开关。
```

权限检查未通过时，不得调用 OrderPlan，不得取得 ActiveLock。

## 9. 订单提交纪律

订单提交必须保守处理。

```text
Execution 只消费 PreparedOrderIntent。
Execution 调用 BinanceOrderSubmissionGateway。
同一个 PreparedOrderIntent 只能提交一次。
订单提交绝不重试。
Gateway 不重试订单提交。
业务层不重试订单提交。
Celery 不重试订单提交。
编排层不重试订单提交。
management command 不重试订单提交。
人工入口不重试订单提交。
unknown 不得推断成功或失败。
unknown 必须通过独立订单生命周期同步管线进入 OrderStatusSync 查询。
```

任何通过重试、恢复、任务重放或人工命令再次提交同一 PreparedOrderIntent 的实现都禁止。

限价单周期收尾撤单不属于订单提交重试。撤单只能由 OrderCycleCloseout 针对既有 LIMIT 订单调用 BinanceOrderCancelGateway；撤单后仍必须通过 OrderStatusSync 和 FillSync 完成状态与成交事实闭环。

## 10. ActiveLock 纪律

OrderPlanActiveLock 是同一交易身份的唯一订单链路保护锁。

规则：

```text
锁只能由 OrderPlan 所属 ActiveLockService 修改。
编排层不得直接释放锁。
RuntimeGuard 不得直接释放锁。
OpsConsole 不得直接写锁状态。
unknown / not_found / NEW / PARTIALLY_FILLED 不得自动释放锁。
提交前明确未发送、交易所明确拒绝、订单终态且成交同步完整、或授权人工收尾，才允许释放锁。
```

不得为了让流程继续而绕过 ActiveLock。

## 11. 核心对象边界

Codex 必须严格区分以下对象：

```text
AtomicSignalSet 不等于 DomainSignalSet。
DomainSignalSet 不等于 MarketRegimeSnapshot。
MarketRegimeSnapshot 不等于 StrategyRouteDecision。
StrategyRouteDecision 不等于 StrategySignal。
StrategySignal 不等于 DecisionSnapshot。
DecisionSnapshot 不等于 CandidateOrderIntent。
DecisionSnapshot 不等于 ApprovedOrderIntent。
DecisionSnapshot 不等于 OrderSubmissionAttempt。
DecisionSnapshot 不等于 OrderStatusSyncRecord。
OrderPlan 不等于 RiskCheck。
CandidateOrderIntent 不等于 ApprovedOrderIntent。
ApprovedOrderIntent 不等于 PreparedOrderIntent。
ApprovedOrderIntent 不等于 OrderSubmissionAttempt。
ExecutionPreparation 不等于 Execution。
PreparedOrderIntent 不等于 OrderSubmissionAttempt。
OrderSubmissionAttempt 不等于交易所完整订单状态。
OrderStatusSyncRecord 不等于 TradeFill。
TradeFill 不等于 BinancePositionSnapshot。
Binance Account Sync 不等于交易执行。
PriceSnapshot 不等于 WebSocket。
RiskCheck 不等于交易执行。
ReviewDatasetRecord 不等于交易决策、策略评估结论或生产策略变更指令。
ReviewDatasetExport 不等于复盘结论或大模型报告。
NotificationDeliveryAttempt 不等于 AlertEvent 本身。
NotificationSuppression 不等于投递失败。
```

完整核心对象清单以 `core_contracts.md` 为准，AGENTS.md 只保留红线级边界。

## 12. 外部服务边界

所有 Binance 请求必须通过 BinanceGateway。

```text
业务模块不得直接创建 Binance HTTP client。
业务模块不得直接生成 Binance 签名。
业务模块不得拼接 Binance endpoint。
系统不得调用交易所修改杠杆接口。
```

BinanceGateway 涉及账户、价格、订单、成交和交易规则的调用必须携带并校验 active market domain。

当前正式系统内不调用 DeepSeek，不在 Django 内部保存大模型复盘报告。

如后续重新引入系统内大模型复盘，必须先新增独立需求和红线定义。

Notifications 不以 active market domain 作为通用必填上下文。

业务模块只写 AlertEvent，不直接发送 Hermes。

Hermes 只负责通知，不触发交易。

## 13. 通知、审计与巡检纪律

所有正式交易相关关键事件必须写 AlertEvent，包括但不限于：

```text
OrderPlan no_order_required / blocked / failed
CandidateOrderIntent generated / skipped / blocked
RiskCheck ALLOW / DENY / BLOCKED / FAILED
fallback_reduce_only selected
ApprovedOrderIntent generated / expired / canceled
ExecutionPreparation passed / blocked / failed
Execution submitted / failed / canceled / rejected / unknown
OrderStatusSync found / not_found / unknown / terminal
TradeFill recorded
OrderFillSummary generated
ActiveLock kept / released / blocked
```

Notifications 拥有：

```text
AlertEvent
NotificationDeliveryAttempt
NotificationSuppression
```

需要外部投递的 AlertEvent 必须形成 NotificationDeliveryAttempt。

不需要外部投递的 AlertEvent 必须形成 NotificationSuppression 或等价抑制记录。

通知失败不得回滚业务事实。

通知成功不得触发业务动作。

RuntimeGuard 只覆盖：

```text
自动编排主链路
订单链路卡住状态
ActiveLock 风险状态
通知投递状态
```

RuntimeGuard 不得：

```text
补跑业务
恢复编排
修改业务对象
释放锁
巡检 ReviewDataset
巡检后台人工补算
巡检后台人工复盘
调用 Binance
调用 DeepSeek
直接发送 Hermes
自动恢复交易
```

## 14. ReviewDataset 与本地复盘纪律

ReviewDataset 是后置复盘数据集模块，不属于自动交易主链路必跑步骤。

规则：

```text
只读取已落库事实。
按 UTC 4 小时周期组织数据。
整理编排、策略、账户、价格、订单、成交、告警、巡检和审计事实。
不请求 Binance。
不调用 DeepSeek。
不影响交易主流程。
不生成交易信号。
不调整策略。
不自动暂停或恢复交易。
不保存系统内大模型复盘报告。
```

Codex skill 或本地脚本可以读取 ReviewDataset API / 导出文件进行离线复盘。

规则：

```text
Codex skill 不写生产 MySQL。
Codex skill 不参与实时交易。
Codex skill 不生成交易指令。
Codex skill 不自动修改策略。
Codex skill 不自动修改真实交易运行配置。
Codex skill 不自动下单。
Codex skill 的复盘报告默认保存为本地文件。
```

本地复盘输出只能作为离线复盘材料和人工参考，不得被当作实时交易决策。

## 15. 不得预设未定人工恢复能力

OrderStatusSync 和 FillSync 模块不自行定义独立人工补查页面、人工补同步页面或对应额外运行开关。

当前受控人工恢复和人工对账入口统一由 `docs/requirements/ops_console.md` 定义。OpsConsole 只负责权限、明确对象选择、二次确认、原因、审计和结果展示；实际补查、补同步仍必须调用 OrderStatusSync / FillSync 对应业务 service。

任何新增或扩展的后台人工恢复能力，必须先修改独立 OpsConsole / 后台需求，并明确：

```text
入口权限
操作对象
允许动作
禁止动作
审计记录
AlertEvent
是否写库
是否访问外部服务
是否影响 ActiveLock
是否影响真实交易
```

不得在订单状态同步或成交同步模块中自行埋入未由 OpsConsole 需求授权的人工入口、通用查询入口或额外开关。

## 16. 业务逻辑组织规则

业务逻辑必须放在：

```text
service 层
domain 层
```

不得把复杂业务逻辑堆进：

```text
Django model
Celery task
management command
view
serializer
repository
scripts
```

Django model 只定义数据结构和最小约束。

Celery task 只作为任务入口。

Management command 只作为人工命令入口。

跨模块编排应放在 orchestration service 或明确的 service 层中。

## 17. 编排规则

PipelineOrchestrator 负责按照步骤定义推进一轮业务流程。

编排层负责：

```text
创建 OrchestrationRun
冻结步骤定义
调用 OrchestrationBusinessConnector
保存 OrchestrationStepRun
保存 OrchestrationBusinessObjectLink
根据统一 flow_action 推进、等待、停止或完成
记录步骤耗时、状态和错误摘要
```

编排层不得：

```text
解释业务模块内部状态
直接调用 Binance
直接调用 DeepSeek
直接修改业务对象
直接释放 ActiveLock
直接提交订单
绕过业务 service
```

主交易业务对象不得把 OrchestrationRun 当作正式业务外键或下游输入。

业务对象之间的正式追溯必须依赖真实业务外键。

OrchestrationBusinessObjectLink 只提供一轮运行的快捷审计索引，不替代业务外键。

复盘、后台、巡检和审计类对象可以保存 OrchestrationRun 引用，用于展示、复盘或人工排查，但不得作为交易模块的正式输入。

## 18. 数据与存储红线

MySQL 是核心业务主存储。

Redis 只能用于：

```text
缓存
分布式锁
Celery broker
Celery result backend
短期幂等控制
短期任务状态
限流计数
短期特征序列缓存
PriceSnapshot 短期缓存
Gateway 限频、冷却和熔断状态
Notifications 冷却、聚合和投递防重复
```

禁止把 Redis 作为核心业务数据唯一存储。

禁止在单个字段中保存：

```text
大批量 K 线
完整历史窗口
完整历史指标数组
不可控长文本
逃避表结构设计的大 JSON
```

交易、风控、订单、成交、仓位、复盘相关数据必须可追溯、可审计、可复盘。

## 19. 配置与密钥规则

所有环境配置必须进入 `.env.example`，并带中文注释。

禁止硬编码：

```text
数据库密码
Redis 密码
Webhook secret
模型 API key
交易所 API key
真实交易开关
真实发送开关
生产环境开关
杠杆配置
```

禁止提交真实 `.env`、真实 API key、真实 token、真实 webhook secret。

日志、异常信息、AlertEvent、审计记录、前端响应和 Hermes 通知不得暴露密钥。

后台不得管理 API key，不得编辑 `.env`，不得放大 `.env` 硬配置权限。

## 20. 时间规则

Binance 返回的时间戳按 UTC 解释。

系统内部所有核心业务时间统一 UTC。

K 线 open_time / close_time 必须使用 Binance 返回的时间戳，并按 UTC 存储和判断。

请求 K 线时不传 timeZone，默认使用 UTC。

所有核心业务时间、行情时间、K 线排序、连续性判断、回测判断、策略周期判断、订单追踪、成交追踪、仓位追踪、复盘追踪，统一使用 UTC 时间。

系统不设计本地时间字段。

通知、日志、复盘、后台展示如需人类可读时间，也应默认展示 UTC，并明确标注 UTC。

不得根据服务器本地时区、用户 IP、运行机器时区或 PRC 时间参与任何业务判断。

## 21. Management command 与 Celery task 规则

management command 只作为人工命令入口。

Celery task 只作为异步任务入口。

二者只能：

```text
解析参数
生成或传递 trace_id
设置 trigger_source
校验基础权限
调用 application service
输出结果摘要
```

禁止在 command 或 task 中写复杂业务逻辑。

禁止：

```text
command / task 直接访问 Binance
command / task 直接发送 Hermes
command / task 直接提交订单
command / task 直接释放 ActiveLock
command / task 直接修改业务状态
command / task 绕过 OrderPlanStepAdapter 的真实交易权限检查
command / task 绕过业务幂等
command / task 自动重试订单提交
```

如果 command / task 涉及真实交易、OrderCycleCloseout 限价单周期收尾、人工 ActiveLock 收尾、ReviewDataset 导出或真实交易运行开关，必须明确：

```text
运行模式
是否 dry-run
是否 confirm-write
目标对象
操作者
原因
证据
trace_id
trigger_source
是否写审计
是否写 AlertEvent
```

## 22. 文件修改安全规则

修改已有文件前必须先读取原文件内容。

禁止：

```text
清空重写已有核心文件
删除整个 docs/、apps/、config/、tests/ 目录
用脚手架命令覆盖已有项目结构
大范围格式化与当前任务无关的文件
为了通过测试而删除测试
为了通过测试而降低测试强度
绕过业务规则
新增重复模块
新增重复工具类
新增重复封装
新增重复配置
```

新增文件必须符合当前目录结构和文档约定。

如果工作树已有用户修改，Codex 必须保护用户修改，不得用重置、覆盖或无关格式化吞掉用户工作。

## 23. 开发纪律

每次修改必须围绕用户本次任务。

禁止：

```text
顺手重构无关模块
顺手改命名
顺手优化相邻代码
顺手新增计划外功能
顺手调整架构
提前实现超出当前 requirements / plans 的能力
```

如果发现当前任务需要突破已有文档边界，必须停止并向用户说明原因。

如果存在不确定字段、表名、配置名、流程边界、交易行为、真实交易风险或资金风险，必须停止并向用户确认。

不得自行猜测业务规则。

## 24. 函数与职责规则

```text
不按文件总行数机械限制拆分。
单个函数 / 方法原则上不超过 120 行。
超过 180 行需要在回报中说明原因。
超过 250 行原则上应拆分，除非用户明确允许。
一个函数只做一个清晰职责。
一个 class / service 不得承担多个架构层职责。
禁止把完整主链路塞进一个 service、task 或 management command。
不得为了满足行数规则进行无意义拆分。
```

优先保证职责清晰、调用链清楚、测试容易。

## 25. 新增核心 Python 文件顶部说明

新增核心 Python 文件时，文件顶部必须用简短注释说明：

```text
属于哪个模块
负责什么
不负责什么
是否读写数据库
是否访问 Redis
是否访问外部服务
是否发送 Hermes
是否调用大模型
是否涉及交易执行
是否允许真实交易
```

如果不涉及某项，应明确写“不涉及”。

## 26. 测试与验收规则

每次开发必须提供可执行的验收方式。

至少说明：

```text
应运行哪些测试
应执行哪些 management command
应检查哪些数据库记录
什么结果算通过
什么结果算失败
```

如果测试无法运行，必须说明原因。

不得用“看起来没问题”代替验收。

交易相关功能必须额外说明：

```text
是否真实交易关闭
是否使用 dry-run
是否产生 CandidateOrderIntent
是否产生 ApprovedOrderIntent
是否产生 PreparedOrderIntent
是否提交 OrderSubmissionAttempt
是否写入 TradeFill
是否写入或影响 BinancePositionSnapshot / 仓位事实
是否写 AlertEvent
是否创建 NotificationDeliveryAttempt 或 NotificationSuppression
是否发送 Hermes
```

## 27. 阶段交付回报规则

Codex 回报必须说明：

```text
本阶段实现了什么
修改和新增了哪些文件
主要调用链路是什么
是否写库
是否访问 Redis
是否发送 Hermes
是否调用大模型
是否涉及交易执行
是否涉及真实交易
是否涉及 FeatureLayer
是否涉及 AtomicSignal / DomainSignal / MarketRegime
是否涉及 StrategyRouting / StrategySignal / StrategyAnalysisRelease
是否涉及 DecisionSnapshot
是否涉及 Binance Account Sync
是否涉及 PriceSnapshot
是否涉及 OrderPlan / CandidateOrderIntent
是否涉及 RiskCheck / ApprovedOrderIntent
是否涉及 ExecutionPreparation / Execution
是否涉及 OrderStatusSync / FillSync
是否涉及 ReviewDataset
是否写 AlertEvent
是否创建 NotificationDeliveryAttempt / NotificationSuppression
dry-run / confirm-write 行为，如本阶段涉及
异常处理方式
测试命令和结果
本阶段明确不负责什么
是否违反最高交易红线
```

默认不强制创建 implementation 文档。

implementation 文档只用于记录复杂内部逻辑，例如：

```text
特征计算
原子信号
领域信号
市场环境判断
策略路由
策略规则
目标仓位决策算法
风控规则
订单计划规则
回测撮合
执行状态机
复盘归因逻辑
```

## 28. 当前阶段禁止提前实现

除非用户明确要求，否则当前阶段不得提前实现：

```text
复杂 UI
多交易所
多 active market domain 同时交易
复杂投资组合管理
复杂多策略权重分配
机器学习交易模型
实时大模型交易判断
大模型生成订单
复杂报表系统
自动参数优化
自动上线策略
自动禁用策略
自动调整杠杆
自动修改保证金模式
自动资金划转
自动交易修复
后台热切 active market domain
.env 在线编辑
API key 后台管理
Hermes 入站交易命令
通知触发交易
未经验证的实盘执行
```

项目优先级：

```text
第一，真实策略有效性。
第二，数据、回测、风控、实盘一致性。
第三，策略组合、监控、复盘。
第四，后台、界面、交互体验。
```

如果任务过早投入外围功能，Codex 应提醒用户该功能是否直接服务策略验证、风控、执行可靠性或复盘可信度。

## 29. 语言与通知

面向用户的通知、日志摘要、Hermes 消息优先使用中文。

专业术语可保留英文，但应附中文解释。

交易相关通知必须明确区分：

```text
系统分析
策略信号
目标仓位决策
账户事实
价格事实
订单计划
候选订单意图
风控结果
审批通过订单意图
执行前检查
订单提交尝试
交易所订单状态
真实成交
锁状态
复盘结论
```

不得把通知写成模糊喊单。

## 30. 框架优先原则

Codex 必须优先使用项目已选定框架的内建能力。

本项目后端使用 Django、Django ORM、Django migrations、Django settings、Celery、Celery Beat、Redis、Python logging 和 pytest / Django test framework；OpsConsole 前端使用 Next.js、TypeScript、shadcn/ui 和 Recharts。

Codex 不得自研 ORM、migration、配置系统、日志系统、任务队列、调度系统、测试框架或数据库连接池。

scripts、management command、Celery task 只能作为入口调用 application service，不得承载核心业务逻辑。
