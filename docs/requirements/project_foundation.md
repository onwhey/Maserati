# 项目基础设施需求

## 1. 文档目的

本文档定义本项目的基础设施、开发框架、配置、存储、任务、日志、追踪、审计、测试和外部服务接入底座。

本文档用于回答：

```text
项目基础框架应该具备哪些能力；
哪些能力必须使用 Django / Celery / Redis 等框架内建能力；
配置、密钥和真实交易权限如何进入系统；
MySQL 与 Redis 的职责边界是什么；
Celery task 和 management command 能做什么；
trace_id、trigger_source 和幂等键如何传递；
日志、异常、AlertEvent 和审计应该遵守什么底线；
外部服务请求如何通过 Gateway 收敛；
默认测试环境必须避免哪些真实外部访问。
```

本文档不定义：

```text
具体业务表字段；
具体 Django app 拆分；
具体 Celery task 名称；
具体 REST API 路径；
具体策略公式；
K 线采集规则；
数据质量规则；
回补规则；
订单规划规则；
风控规则；
执行状态机；
复盘归因逻辑；
前端页面组件。
```

模块业务合同以对应 requirements 文档为准。本文档只定义所有模块共同依赖的工程底座和禁止边界。

## 2. 模块定位

ProjectFoundation 是系统底座能力，不是交易业务模块。

它负责提供：

```text
Django 项目基础；
Django settings 配置入口；
Django ORM 与 migrations 约束；
MySQL 主业务存储能力；
Redis 短期状态能力；
Celery / Celery Beat 任务基础；
Python logging / Django logging 基础；
trace_id 与 trigger_source 规范；
业务幂等键规范；
基础异常分类；
测试基础；
配置与密钥安全规则；
外部 Gateway 接入规则；
AlertEvent、通知投递和审计的基础约束。
```

它不负责：

```text
生成 MarketSnapshot；
计算 FeatureLayer；
生成 AtomicSignal；
生成 DomainSignal；
生成 MarketRegime；
执行 StrategyRouting；
生成 StrategySignal；
管理 StrategyAnalysisRelease；
生成 DecisionSnapshot；
同步 Binance 账户；
生成 PriceSnapshot；
生成 OrderPlan；
执行 RiskCheck；
执行 ExecutionPreparation；
提交订单；
同步订单状态；
同步成交；
生成 ReviewDataset；
调用大模型做系统内复盘。
```

一句话：

```text
ProjectFoundation 负责让后续所有业务模块在同一个配置、存储、任务、日志、追踪、安全和测试底座上运行。
```

## 3. 基础建设原则

### 3.1 框架优先原则

本项目必须优先使用已选定框架的内建能力。

项目基础框架包括：

```text
Python 3.12.x；
Django 5.2.x LTS；
Django settings；
Django ORM；
Django migrations；
Django management command；
Python logging / Django logging；
MySQL；
Redis；
Celery；
Celery Beat；
pytest / pytest-django 或 Django test framework；
Node.js LTS（仅 OpsConsole 前端）；
Next.js + TypeScript（仅 OpsConsole 前端）；
shadcn/ui；
Recharts。
```

禁止自研：

```text
ORM；
migration 系统；
配置加载框架；
日志框架；
任务队列框架；
调度框架；
测试框架；
数据库连接池框架；
后台命令框架。
```

如确实需要封装，只能在框架能力之上做薄封装。封装必须服务于业务边界、可测试性和安全约束，不得替代框架机制。

### 3.2 业务逻辑分层原则

核心业务逻辑必须放在：

```text
service 层；
domain 层。
```

以下层只能作为轻量入口或数据结构：

```text
Django model；
Celery task；
management command；
view；
serializer；
repository；
scripts。
```

禁止：

```text
在 Django model 中堆复杂业务流程；
在 Celery task 中串完整主链路；
在 management command 中直接写交易逻辑；
在 view 或 serializer 中直接执行交易判断；
在 scripts 中绕过 service 写核心业务表；
在 repository 中发起外部服务请求。
```

### 3.3 入口层轻量原则

以下入口只能做入口职责：

```text
management command；
Celery task；
Celery Beat schedule；
HTTP API view；
OpsConsole 后端接口；
CLI / scripts（如保留）。
```

入口层只能：

```text
解析参数；
校验入口请求；
生成或传递 trace_id；
设置 trigger_source；
校验基础权限；
调用 application service；
返回结果摘要。
```

入口层不得：

```text
直接访问 Binance；
直接访问 DeepSeek；
直接发送 Hermes；
直接提交订单；
直接释放 ActiveLock；
直接修改业务状态；
吞掉异常不记录；
绕过 OrderPlanStepAdapter 的真实交易权限检查；
绕过业务幂等。
```

## 4. 技术版本约束

项目技术底座固定为：

```text
Python 3.12.x；
Django 5.2.x LTS；
MySQL；
Redis；
Celery；
Celery Beat；
Node.js LTS（仅 OpsConsole 前端）；
Next.js + TypeScript（仅 OpsConsole 前端）；
shadcn/ui；
Recharts。
```

版本约束：

```toml
requires-python = ">=3.12,<3.13"
```

```text
Django>=5.2,<5.3；
celery>=5.6,<5.7。
```

规则：

```text
不得随意升级或降级核心版本；
Python 依赖范围写入 pyproject.toml；
OpsConsole 前端依赖写入 package.json；
后端与前端锁文件分别固定实际安装版本；
核心版本变化必须先有架构决策和兼容性验证。
```

OpsConsole 是独立 Web Console，不使用 Django Templates 或 Django Admin 作为正式产品后台。前端通过受控 Django API 使用系统能力，具体边界以 `ops_console.md` 为准。

## 5. Django 项目框架要求

项目必须基于 Django 标准能力建设。

必须：

```text
使用 Django settings 管理配置；
使用 Django app 组织模块；
使用 Django ORM 定义业务模型；
使用 Django migrations 管理表结构变化；
使用 Django transaction 控制关键事务；
使用 Django management command 作为人工命令入口；
使用 Django / pytest-django 测试能力。
```

禁止：

```text
绕过 Django settings 自写配置系统；
绕过 Django ORM 自写通用 ORM；
绕过 Django migrations 手写业务建表系统；
在 scripts 中直接执行核心业务 SQL；
在入口文件中塞入复杂业务逻辑；
通过 raw SQL 逃避业务约束。
```

受控 raw SQL 只能用于明确性能敏感查询，并且必须：

```text
有 service 层封装；
有参数绑定；
有测试覆盖；
不绕过核心业务状态机；
不绕过审计；
不绕过权限和安全校验。
```

## 6. 配置与环境变量要求

配置必须通过 Django settings 和环境变量管理。

所有新增环境配置必须进入 `.env.example`，并带中文注释。

基础配置必须覆盖：

```text
Django secret key；
debug 开关；
allowed hosts；
当前运行环境；
MySQL 连接配置；
Redis 连接配置；
Celery broker 配置；
Celery result backend 配置；
日志级别；
active market domain；
Binance Gateway 配置；
Notifications / Hermes 配置；
真实交易相关硬开关。
```

敏感配置包括：

```text
数据库密码；
Redis 密码；
Webhook secret；
Binance API key；
Binance API secret；
真实交易部署硬配置；
真实发送开关；
生产环境开关；
杠杆相关配置。
```

规则：

```text
真实 .env 不得提交；
真实 API key 不得提交；
真实 token 不得提交；
真实 webhook secret 不得提交；
配置缺失时必须明确失败；
默认测试环境不得使用生产配置；
日志、异常、AlertEvent、审计和前端响应不得泄露敏感配置。
```

禁止：

```text
在业务代码中硬编码数据库连接信息；
在业务代码中硬编码 Redis 密码；
在业务代码中硬编码 Binance key；
在业务代码中硬编码 DeepSeek key；
在业务代码中硬编码 Hermes webhook；
在测试中使用真实生产配置；
通过 OpsConsole 编辑 .env；
通过数据库放大 .env 硬配置权限。
```

## 7. 部署级硬配置与运行时配置

系统对真实交易采用双层权限模型：

```text
.env / Django settings = 真实交易部署级硬权限；
MySQL = 后台真实交易运行开关；
effective_real_trading_permission = deployment_real_trading_permission AND runtime_real_trading_permission。
```

部署级硬配置至少包含：

```text
运行环境；
active exchange；
active market_type；
active account_domain；
active symbol；
Binance API key 是否配置；
是否允许真实交易；
是否允许订单提交；
```

真实交易权限模型中的 MySQL 运行配置只包含真实交易运行开关。规则：

```text
运行开关只能进一步收紧 `.env` 真实交易硬权限；
`.env` 禁止真实交易时，后台不能放行；
后台不能热切 active market domain；
后台不能管理 API key 或 secret；
开关变更必须写审计；
开关变更必须写 AlertEvent；
开启真实交易必须具备高权限并二次确认。
```

OrderPlanStepAdapter 在进入 OrderPlan 前读取并判断一次最终真实交易权限。如果硬配置或 MySQL 开关不可读取，必须 fail-closed；本轮检查通过后不再重新读取，后续开关变化只影响下一次准入。

## 8. active market domain

当前运行时只能存在一个 active market domain。

active market domain 至少由以下硬配置决定：

```text
exchange；
market_type；
account_domain；
symbol。
```

规则：

```text
active market domain 属于部署级硬配置；
非 active domain 不得参与主交易链路；
USDS-M 与 COIN-M 事实、公式和交易规则不得混用；
后台不得热切 active domain；
切换 active domain 必须通过部署配置、服务重启和完整验证；
BinanceGateway 涉及账户、价格、订单、成交和交易规则的调用必须携带并校验 active market domain。
```

## 9. MySQL 基础能力要求

MySQL 是项目核心业务主存储。

必须：

```text
Django 可以连接 MySQL；
Django migrations 可以正常执行；
业务表通过 Django model + migration 创建；
关键业务事实写入 MySQL；
测试环境使用独立测试库或测试替身；
连接失败时有明确错误；
业务状态变更可审计、可追溯。
```

MySQL 必须保存：

```text
行情事实；
数据质量结果；
数据回补事实；
市场快照；
特征；
原子信号；
领域信号；
市场环境；
策略路由；
策略信号；
策略分析发布版本；
目标仓位决策；
账户事实；
价格事实；
订单计划；
候选订单意图；
风控结果；
风控批准订单意图；
执行准备结果；
订单提交尝试；
订单状态同步记录；
成交事实；
编排运行；
运行巡检问题；
复盘数据集记录；
复盘数据导出记录；
AlertEvent；
NotificationDeliveryAttempt；
NotificationSuppression；
审计记录；
真实交易运行开关。
```

禁止：

```text
使用 Redis 替代 MySQL 存储核心业务事实；
只写日志不入库；
在无 migration 的情况下手动创建业务表；
用裸 SQL 作为常规业务写入方式；
绕过 Django ORM 写核心业务对象；
把核心业务事实只保存在外部服务响应中。
```

## 10. Redis 基础能力要求

Redis 是短期状态、缓存、限频、锁和 Celery 基础设施。

Redis 可以用于：

```text
Celery broker；
Celery result backend；
缓存；
分布式锁；
短期幂等控制；
短期任务状态；
限流计数；
短期特征序列缓存；
PriceSnapshot 短期缓存；
Gateway 限频、冷却和熔断状态；
Notifications 冷却、聚合和投递防重复。
```

Redis 禁止用于：

```text
核心 K 线主存储；
DataQualityResult 主存储；
BackfillRun 主存储；
MarketSnapshot 主存储；
FeatureSet / FeatureValue 主存储；
AtomicSignal 主存储；
DomainSignal 主存储；
MarketRegimeSnapshot 主存储；
StrategyRouteDecision 主存储；
StrategyAnalysisRelease 主存储；
StrategySignal 主存储；
DecisionSnapshot 主存储；
BinanceSyncRun 主存储；
OrderPlan 主存储；
CandidateOrderIntent 主存储；
ApprovedOrderIntent 主存储；
OrderSubmissionAttempt 主存储；
OrderStatusSyncRecord 主存储；
TradeFill 主存储；
RuntimeGuardIssue 主存储；
ReviewDatasetRecord 主存储；
ReviewDatasetExport 主存储；
NotificationDeliveryAttempt 主存储；
NotificationSuppression 主存储；
长期审计数据主存储。
```

规则：

```text
Redis 数据必须可过期；
Redis 数据必须可重建；
Redis 丢失不得导致核心事实丢失；
Redis 不可用时不得用过期缓存放行真实交易；
Redis 不得替代 MySQL 作为核心事实来源。
```

## 11. Celery / Celery Beat 基础要求

Celery 是异步任务入口，Celery Beat 是定时调度入口。

必须：

```text
Celery app 可初始化；
Celery 使用 Redis 作为 broker；
Celery result backend 可配置；
Celery Beat 可注册定时任务；
任务入口生成或传递 trace_id；
任务入口设置 trigger_source；
任务入口调用 service；
任务异常记录日志和必要 AlertEvent。
```

Celery task 只能：

```text
解析参数；
生成或传递 trace_id；
设置 trigger_source；
调用 application service；
返回简短结果摘要。
```

禁止：

```text
Celery task 中直接写完整业务流程；
Celery task 中直接访问 Binance 并写业务表；
Celery task 中直接访问 DeepSeek 并写业务表；
Celery task 中直接发送 Hermes；
Celery task 中绕过 application service；
Celery task 中绕过 OrderPlanStepAdapter 的真实交易权限检查；
Celery task 中吞掉异常不记录；
Celery task 中绕过 trace_id；
Celery task 自动重试订单提交。
```

订单提交相关任务必须特别遵守：

```text
订单提交绝不重试；
Celery 重复投递只能读取已有 OrderSubmissionAttempt；
不得再次调用 BinanceOrderSubmissionGateway；
unknown 状态不得自动解释为成功或失败。
```

## 12. Management command 基础要求

management command 只作为人工命令入口。

它只能：

```text
解析命令参数；
生成或接收 trace_id；
设置 trigger_source = management_command 或更具体来源；
校验人工确认参数；
调用 service；
输出结果摘要。
```

禁止：

```text
在 command 中写复杂业务逻辑；
在 command 中直接操作业务表状态；
在 command 中直接调用 Binance；
在 command 中直接调用 DeepSeek；
在 command 中直接发送 Hermes；
在 command 中直接释放 ActiveLock；
在 command 中绕过正式交易链路的真实交易权限检查；
在 command 中绕过权限和审计。
```

涉及真实交易、人工 ActiveLock 收尾、ReviewDataset 导出或真实交易运行开关的 command 必须显式说明：

```text
运行模式；
是否 dry-run；
是否 confirm-write；
目标对象；
操作者；
原因；
证据；
trace_id。
```

## 13. 日志基础要求

项目必须使用 Python logging / Django logging。

必须：

```text
统一日志格式；
日志使用 UTC 时间；
日志包含级别、模块、message；
重要业务日志包含 trace_id；
外部调用日志包含脱敏摘要；
异常日志包含错误类型和必要上下文；
高风险失败不得只有日志而没有业务事实或 AlertEvent。
```

禁止记录：

```text
数据库密码；
Redis 密码；
完整 API key；
API secret；
signature；
Authorization header；
cookie；
完整 webhook；
.env 完整内容；
完整外部请求体；
完整外部响应体；
账户敏感信息；
订单敏感信息。
```

禁止：

```text
用 print 作为业务日志；
每个模块自定义一套日志系统；
日志中输出完整敏感配置；
把日志当作业务事实唯一来源。
```

## 14. UTC 时间规则

所有核心业务时间统一使用 UTC。

必须：

```text
Binance 返回时间戳按 UTC 解释；
K 线 open_time / close_time 使用 Binance 返回时间戳；
数据库核心业务时间按 UTC 存储；
编排运行时间按 UTC；
订单追踪、成交追踪和复盘时间按 UTC；
后台展示默认标注 UTC。
```

禁止：

```text
根据服务器本地时区判断业务时间；
根据用户 IP 转换业务判断时间；
使用 PRC 时间参与业务判断；
请求 K 线时传入本地 timeZone；
在核心业务表中设计本地时间字段。
```

自动运行时间、周期边界和复盘窗口必须以对应模块需求中的 UTC 规则为准。

## 15. trace_id 要求

trace_id 用于追踪一次业务运行或一次事件链路。

必须：

```text
入口层如未传入 trace_id，应生成 trace_id；
下游 service 必须显式传递 trace_id；
Gateway 调用上下文必须携带 trace_id；
OrchestrationRun 必须保存 trace_id；
OrchestrationStepRun 必须继承 trace_id；
AlertEvent 必须记录 trace_id；
审计记录必须记录 trace_id；
人工操作必须记录 trace_id。
```

规则：

```text
trace_id 用于追踪；
trace_id 不作为业务幂等键；
trace_id 不替代唯一业务键；
异步 WAIT 恢复应继续使用原 trace_id；
人工诊断可以使用新的 trace_id，但必须关联原对象。
```

禁止：

```text
用 trace_id 判断业务是否重复；
用 trace_id 替代业务外键；
丢弃上游传入的 trace_id；
Celery worker 覆盖原始 trace_id。
```

## 16. trigger_source 要求

trigger_source 用于记录任务触发来源。

建议取值包括：

```text
celery_beat；
celery_worker；
management_command；
ops_console；
manual_review；
runtime_guard；
system；
test；
dry_run。
```

规则：

```text
trigger_source 必须显式设置；
trigger_source 不得由程序随意猜测；
Celery worker 不得覆盖原始 trigger_source；
如果需要记录执行者，应另设 operator_id 或 executor_source；
AlertEvent 和审计记录必须保存 trigger_source。
```

## 17. 业务幂等要求

系统必须区分 trace_id 和业务幂等键。

业务幂等键用于同一业务动作重复执行时返回同一个业务事实。

必须：

```text
每个核心业务 service 接收或生成稳定业务幂等键；
同一幂等键重复执行不得生成重复业务对象；
外部请求不确定时不得通过重试制造重复事实；
AlertEvent 使用稳定 event_key 去重；
编排层生成不透明 business_request_key；
业务模块只把 business_request_key 当作幂等输入，不反向查询编排 ID。
```

订单提交特殊规则：

```text
订单提交不允许通过幂等键触发二次提交；
重复执行只能读取已有 OrderSubmissionAttempt；
如果请求已经发送但结果 unknown，不得自动重试；
后续只能通过 OrderStatusSync 查询。
```

禁止：

```text
把 trace_id 当作幂等键；
用当前时间拼接不稳定幂等键；
因 Celery 重试生成重复业务事实；
因编排恢复重新提交订单；
用 Redis 作为唯一幂等事实来源。
```

## 18. 基础异常分类

系统必须有统一异常分类或等价错误语义。

至少区分：

```text
配置错误；
权限错误；
参数错误；
数据库连接错误；
Redis 连接错误；
外部服务调用错误；
Gateway 错误；
安全准入错误；
幂等冲突；
状态冲突；
未知外部结果；
通知投递错误；
系统未预期错误。
```

要求：

```text
异常消息不得包含敏感信息；
异常应保留 trace_id；
异常应能映射为稳定 reason_code；
异常应可写日志；
高风险异常应写 AlertEvent；
未知外部结果必须保守处理。
```

禁止：

```text
把所有异常都吞掉；
把未知外部结果当成功；
把未知外部结果当失败并自动清理；
把 provider 原始错误完整透传到前端或 AlertEvent。
```

## 19. Service Result 基础语义

业务 service 可以定义模块内状态，但必须能映射到全局结果语义。

全局结果类别：

```text
succeeded；
no_action；
skipped；
blocked；
denied；
unknown；
failed。
```

规则：

```text
blocked、denied、no_action 和 skipped 不是系统异常；
unknown 不得自动映射为 succeeded 或 failed；
模块返回值不得让编排层靠 true / false 猜测；
OrchestrationBusinessConnector 负责理解模块原始返回并转换成统一结果；
主交易业务 service 不得把 OrchestrationRun 当作正式业务外键或下游输入；
业务对象之间的正式追溯必须依赖真实业务外键；
OrchestrationBusinessObjectLink 负责一轮运行的快捷审计索引；
复盘、后台、巡检和审计类 service 可以保存 OrchestrationRun 引用，用于展示、复盘或人工排查。
```

## 20. 外部服务接入基础规则

所有外部服务请求必须通过受控 Gateway 或受控通知通道。

当前外部能力包括：

```text
BinanceGateway；
Notifications / Hermes。
```

必须：

```text
外部请求上下文携带 trace_id 和 trigger_source；
BinanceGateway 涉及账户、价格、订单、成交和交易规则的调用必须携带并校验 active market domain；
Notifications 不以 active market domain 作为通用必填上下文；
Gateway 负责认证、签名、超时、限频、错误分类和脱敏；
Gateway 只返回技术事实；
业务模块保存业务事实；
业务模块根据业务语义写 AlertEvent；
自动化测试使用 fake gateway 或 mock channel。
```

禁止：

```text
业务模块直接创建 Binance HTTP client；
业务模块直接生成 Binance 签名；
业务模块直接拼接 Binance endpoint；
OpsConsole 直接调用 BinanceGateway；
业务模块直接发送 Hermes webhook；
Gateway 代替业务模块写业务状态；
Gateway 代替业务模块写业务 AlertEvent。
```

## 21. BinanceGateway 基础依赖

ProjectFoundation 必须为 BinanceGateway 提供配置、日志、测试和安全基础。

必须支持：

```text
Binance base_url 配置；
active market_type 配置；
read-only API key 配置；
trade API key 配置；
recvWindow 配置；
超时配置；
安全读取请求重试配置；
订单提交禁用重试；
限频与熔断配置；
fake gateway 测试替换。
```

基础边界：

```text
读凭据与交易凭据必须分离；
真实交易默认关闭；
env 禁止时数据库不能打开；
订单提交绝不自动重试；
Redis 故障时不得默认放行真实订单提交；
日志和异常不得泄露 secret、signature 或完整认证 header。
```

## 22. Notifications 基础依赖

Notifications 拥有 AlertEvent、NotificationDeliveryAttempt 和 NotificationSuppression。

ProjectFoundation 必须支持：

```text
AlertEvent 写入基础；
NotificationRoute 配置基础；
NotificationTemplate 配置基础；
NotificationDeliveryAttempt 记录基础；
NotificationSuppression 不投递原因记录基础；
Hermes 通道配置；
通知投递 worker 基础；
fake Hermes 或 mock channel 测试替换。
```

基础边界：

```text
业务模块只写 AlertEvent；
业务模块不直接发送 Hermes；
Notifications 异步投递；
通知失败不得回滚业务事实；
Hermes 不得触发交易；
AlertEvent 不得包含密钥、签名、完整认证 header 或完整外部响应。
```

Notifications 的字段、路由、模板、投递状态和重试规则以 `notifications.md` 为准。本文档不重复维护通知模块内部设计。

## 23. 真实交易运行权限基础能力

ProjectFoundation 必须提供最小化的真实交易运行配置读取、变更、审计和 fail-closed 基础，不建立独立的运行权限业务模块。

必须支持：

```text
读取 `.env` 真实交易硬权限；
读取和保存 MySQL 真实交易运行开关；
计算最终真实交易权限；
向 OpsConsole 提供脱敏配置摘要；
保存开关变更审计；
开关变更写 AlertEvent；
权限不可判断时在进入 OrderPlan 前 fail-closed。
```

基础边界：

```text
.env 是真实交易最高权限；
MySQL 是后台真实交易运行开关的正式事实来源；
Redis 不作为真实交易权限事实来源；
后台不能写 .env；
后台不能管理 API key；
后台不能突破真实交易硬权限；
后台不能热切 active market domain；
OrderPlanStepAdapter 只在调用 OrderPlan 前检查一次；
Execution 和后续追踪模块不重新读取 MySQL 运行开关。
```

## 24. AuditRecord 基础要求

人工操作和高风险状态变更必须可审计。

审计至少覆盖：

```text
真实交易运行开关变更；
人工 ActiveLock 收尾；
ReviewDataset 导出；
通知路由变更；
高风险配置相关操作。
```

审计记录必须包含：

```text
operator_id；
operation_type；
target_object_type；
target_object_id；
before_state_summary；
after_state_summary；
reason；
evidence；
result；
trace_id；
trigger_source；
created_at_utc。
```

禁止：

```text
审计记录包含密钥；
审计记录包含完整认证 header；
审计记录包含未脱敏外部响应；
高风险操作无审计；
用 AlertEvent 替代审计记录；
用审计记录替代业务对象状态。
```

## 25. 测试基础要求

项目必须具备可运行的自动化测试基础。

默认测试必须：

```text
不访问真实 Binance；
不访问真实 DeepSeek；
不发送真实 Hermes；
不访问生产 MySQL；
不访问生产 Redis；
不提交真实订单；
不依赖真实 API key；
不依赖真实余额或真实持仓；
使用 UTC 时间；
使用 fake gateway 或 mock channel；
覆盖 trace_id 与 trigger_source 传递；
覆盖敏感信息不进入日志和异常。
```

涉及外部服务的测试必须：

```text
默认使用 fake；
真实集成测试必须显式开启；
真实集成测试必须使用非生产凭据；
真实集成测试不得提交订单；
真实集成测试不得修改杠杆；
真实集成测试不得污染生产数据。
```

基础测试应覆盖：

```text
Django settings 可加载；
MySQL 配置可读取；
Redis 配置可读取；
Celery app 可初始化；
日志脱敏规则；
trace_id 生成与传递；
trigger_source 传递；
业务幂等键不等于 trace_id；
AlertEvent 可以通过 service 写入；
NotificationDeliveryAttempt 可通过 mock channel 记录；
真实交易权限配置不可读取时，OrderPlanStepAdapter fail-closed；
Gateway fake 替换；
管理命令只调用 service；
Celery task 只调用 service。
```

## 26. dry-run 与 confirm-write 基础规则

系统必须明确区分 dry-run 和 confirm-write。

dry-run 规则：

```text
不得写核心业务结果；
不得提交真实订单；
不得修改真实交易运行开关；
不得释放 ActiveLock；
可以返回计划结果摘要；
可以写测试或诊断日志；
是否写 AlertEvent 由具体模块定义，默认不得写正式交易 AlertEvent。
```

confirm-write 规则：

```text
人工入口涉及写库或高风险状态变更时必须显式确认；
必须记录 operator_id；
必须记录 reason；
必须记录 evidence；
必须记录 trace_id；
必须写审计；
必要时写 AlertEvent。
```

禁止：

```text
默认 confirm-write；
用 dry-run 结果进入正式下游；
用 dry-run 绕过真实交易权限检查；
用 confirm-write 绕过业务 service。
```

## 27. 文件与模块顶部说明

新增核心 Python 文件顶部必须用简短注释说明：

```text
属于哪个模块；
负责什么；
不负责什么；
是否读写数据库；
是否访问 Redis；
是否访问外部服务；
是否发送 Hermes；
是否调用大模型；
是否涉及交易执行；
是否允许真实交易。
```

如果不涉及某项，应明确写“不涉及”。

该说明不得代替正式需求文档或代码测试。

## 28. 当前不包含的基础能力

当前基础设施不包含：

```text
自研 ORM；
自研 migration；
自研配置中心；
自研日志系统；
自研任务队列；
自研调度系统；
自研测试框架；
复杂 UI 框架设计；
多环境配置发布系统；
.env 在线编辑；
API key 后台管理；
多交易所接入；
多 active market domain 同时运行；
后台热切 active market domain；
自动修复交易异常；
自动恢复编排；
自动释放 ActiveLock；
Hermes 入站命令；
大模型实时交易判断。
```

这些能力不得以“基础设施封装”的名义提前进入系统。

## 29. 禁止事项

ProjectFoundation 层面禁止：

```text
绕过 Django settings；
绕过 Django ORM；
绕过 Django migrations；
绕过 service 层；
用 scripts 承载核心业务逻辑；
用 Redis 替代 MySQL 保存核心事实；
将真实密钥写入代码、日志、AlertEvent、审计或前端；
业务模块直接调用 Hermes；
业务模块直接访问 Binance；
业务模块直接访问 DeepSeek；
Celery task 自动重试订单提交；
management command 直接提交订单；
后台接口直接释放 ActiveLock；
后台接口直接写业务状态；
默认测试访问真实外部服务；
系统使用本地时间参与业务判断；
在基础设施层实现策略、风控或交易业务。
```

## 30. 验收标准

ProjectFoundation 验收必须满足：

```text
Django settings 可以加载基础配置；
所有新增配置进入 .env.example 并带中文注释；
敏感配置不会进入日志、异常、AlertEvent、审计或前端；
MySQL 作为核心业务主存储；
Redis 只作为短期状态、缓存、锁、限频和 Celery 基础设施；
Celery app 可初始化；
Celery Beat 可配置定时入口；
management command 只调用 service；
Celery task 只调用 service；
trace_id 可以生成并贯穿 service、Gateway、AlertEvent 和审计；
trigger_source 显式传递；
业务幂等键不等于 trace_id；
所有核心业务时间使用 UTC；
外部服务请求通过受控 Gateway 或 Notifications；
默认测试不访问真实 Binance、DeepSeek、Hermes 或生产数据库；
真实交易权限不可判断时，进入 OrderPlan 前 fail-closed；
订单提交不存在任何自动重试入口；
Notifications 只投递通知，不触发交易；
ProjectFoundation 不实现策略、风控、订单提交或复盘业务。
```

## 31. 最终结论

ProjectFoundation 的最终定位是：

```text
为自动交易闭环提供稳定、可测试、可审计、可追溯、默认安全的工程底座。
```

一句话：

```text
业务模块可以复杂，但底座必须简单、统一、可追踪、可脱敏、可测试，并且真实交易必须默认关闭，只有 `.env` 硬权限和 MySQL 运行开关同时允许时才能进入 OrderPlan。
```
