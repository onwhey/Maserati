# 项目底座实施计划

## 1. 文档目的

本文档用于指导阶段 0 的代码实现。

阶段 0 的目标不是实现交易业务，而是先建立后续所有模块共同依赖的工程底座：

```text
Django 项目结构
配置与 .env 读取
MySQL
Redis
Celery / Celery Beat
UTC 时间规则
日志与脱敏
trace_id / trigger_source
基础幂等语义
基础异常语义
AlertEvent
AuditRecord
真实交易权限基础读取
测试框架与安全默认值
```

阶段 0 完成后，项目应当具备“可以安全继续开发业务模块”的基础能力。

本文档不定义具体业务算法，不定义最终数据库字段全集，不实现 Binance、DeepSeek、Hermes、策略、订单、风控、执行、后台页面或复盘业务。

---

## 2. 阶段定位

阶段 0 是工程地基阶段。

一句话：

```text
让 Django 项目能以正确配置、安全默认值、可测试方式启动，并提供后续业务模块共用的最小基础能力。
```

阶段 0 只允许实现底座，不允许顺手实现业务链路。

---

## 3. 文档依据

编码前必须阅读并遵守：

```text
AGENTS.md
README.md
docs/rules/project_invariants.md
docs/requirements/project_scope.md
docs/requirements/project_foundation.md
docs/requirements/core_contracts.md
docs/requirements/system_capabilities.md
docs/requirements/notifications.md
docs/architecture/system_architecture.md
docs/architecture/module_boundary_architecture.md
docs/architecture/runtime_task_architecture.md
docs/architecture/testing_and_safety_architecture.md
docs/plans/implementation_roadmap.md
```

如果本文档与更高优先级文档冲突，以更高优先级文档为准，并停止实现向用户确认。

---

## 4. 本阶段实现范围

### 4.1 项目结构

本阶段应创建标准 Django 项目结构。

建议至少包含：

```text
config/
apps/
tests/
```

其中：

```text
config/ = Django settings、urls、asgi、wsgi、celery app 等项目级入口；
apps/ = 后续业务 Django app 所在目录；
tests/ = 项目级测试与基础安全测试。
```

具体 app 名称可以在编码阶段按项目结构确定，但必须避免创建含义模糊、职责膨胀的“大杂烩模块”。

允许创建的底座类 app 包括：

```text
foundation / core：基础类型、trace、trigger_source、异常、幂等工具、system checks；
audit：AuditRecord 与审计写入服务；
alerts：AlertEvent 与基础事件写入服务；
runtime_config：真实交易运行开关等最小运行配置事实。
```

如果编码阶段选择合并其中部分 app，必须保证职责边界仍然清楚。

### 4.2 Python 与依赖管理

本阶段必须建立 `pyproject.toml`。

必须约束：

```toml
requires-python = ">=3.12,<3.13"
```

核心依赖必须符合：

```text
Django>=5.2,<5.3
celery>=5.6,<5.7
```

应包含 MySQL、Redis、Celery、测试和 `.env` 读取所需依赖。

依赖策略：

```text
pyproject.toml 使用兼容范围；
锁文件固定实际安装版本；
不得随意升级或降级核心框架；
不得自研 ORM、migration、配置系统、日志系统、任务队列或测试框架。
```

### 4.3 Django settings 与 `.env`

这是本阶段最高优先级之一。

Django 默认不会自动读取 `.env`。

因此本阶段必须显式实现：

```text
Django settings 启动时读取 .env；
数据库配置从 .env / 环境变量读取；
Redis 配置从 .env / 环境变量读取；
Celery broker / result backend 从 .env / 环境变量读取；
Binance / Hermes 的密钥配置只提供占位项，不进行真实访问；当前项目不提供系统内大模型访问配置；
真实交易硬权限默认关闭；
缺失关键配置时给出清晰错误。
```

禁止：

```text
依赖 Django 默认 DATABASES；
把 MySQL 用户名、密码、host、port、database 写死在 settings；
把 SQLite 作为正式默认数据库；
用静默 fallback 掩盖数据库配置错误；
提交真实 .env；
让 OpsConsole 或数据库反向修改 .env。
```

`.env.example` 必须存在，并且每一项配置都带中文注释。

### 4.4 MySQL

MySQL 是核心业务主存储。

本阶段必须实现：

```text
Django 可以通过 settings 读取 MySQL 配置；
Django migration 可以运行；
基础表通过 Django model + migration 创建；
测试环境不得访问生产 MySQL；
数据库连接错误应清晰失败。
```

本阶段至少需要支持后续基础事实落库：

```text
AlertEvent
AuditRecord
真实交易运行开关
必要的基础配置摘要或运行配置事实
```

禁止：

```text
绕过 migration 手动建核心表；
把 Redis 当作核心业务事实主存储；
只写日志不落库；
把核心业务事实塞进不可控大 JSON。
```

### 4.5 Redis

Redis 在本项目中只作为短期基础设施。

本阶段必须实现：

```text
Redis URL / host / port / db / password 从配置读取；
缓存配置可初始化；
Celery broker 可使用 Redis；
必要时可作为 result backend；
Redis 不可用时不能放行真实交易。
```

禁止：

```text
把 Redis 作为核心业务数据唯一存储；
把真实交易权限事实存在 Redis；
用 Redis 缓存替代 MySQL 业务事实；
Redis 故障时默认放行交易链路。
```

### 4.6 Celery / Celery Beat

本阶段只建立 Celery 基础，不实现业务任务。

必须实现：

```text
Celery app 可以加载 Django settings；
Celery 使用配置中的 Redis broker；
Celery Beat 配置入口存在；
任务模块自动发现机制可用；
示例或健康检查任务不得包含业务逻辑。
```

Celery task 在本项目中只允许作为入口：

```text
解析参数；
生成或传递 trace_id；
设置 trigger_source；
调用 service；
返回结构化摘要。
```

本阶段不得实现：

```text
自动四小时主编排；
RuntimeGuard 定时巡检；
通知投递 worker；
订单状态轮询；
成交同步；
ReviewDataset。
```

这些能力留到对应阶段计划。

### 4.7 UTC 时间基础

本阶段必须统一项目时间规则：

```text
USE_TZ = True；
TIME_ZONE 使用 UTC；
所有核心业务时间使用 UTC；
日志和测试默认使用 UTC；
Celery timezone 使用 UTC；
不设计本地时间字段参与业务判断。
```

禁止：

```text
使用服务器本地时区参与业务判断；
使用 PRC 时间判断 K 线、编排、订单、成交或复盘周期；
请求 K 线时传入本地 timeZone；
在核心业务表中设计本地时间字段。
```

### 4.8 日志与脱敏

本阶段必须建立统一日志基础。

要求：

```text
使用 Python logging / Django logging；
日志包含 UTC 时间、级别、模块和消息；
关键上下文应支持 trace_id；
异常日志不得泄露敏感信息；
外部服务相关日志只记录脱敏摘要。
```

禁止日志输出：

```text
数据库密码；
Redis 密码；
Binance API key / secret；
外部大模型 API key；
Webhook secret；
完整 Authorization header；
完整签名材料；
真实 .env 内容；
完整外部请求体或响应体；
完整大模型 prompt 或输出。
```

### 4.9 trace_id 与 trigger_source

本阶段必须提供最小公共能力：

```text
trace_id 生成；
trace_id 显式传递；
trigger_source 标准取值；
service 结果可携带 trace_id / trigger_source；
AlertEvent 与 AuditRecord 可记录 trace_id / trigger_source。
```

规则：

```text
trace_id 只用于技术追踪；
trace_id 不得作为业务外键；
trace_id 不得作为业务幂等键；
trigger_source 必须由入口显式设置；
Celery worker 不得覆盖上游 trigger_source。
```

### 4.10 基础幂等语义

本阶段不实现具体业务幂等对象，但必须提供通用规则与基础工具。

要求：

```text
业务幂等键与 trace_id 分离；
每个后续核心 service 必须有稳定业务幂等输入；
重复任务不得生成重复核心业务对象；
订单提交阶段后续必须能够禁止自动重试。
```

本阶段可以提供：

```text
幂等 key 生成辅助；
幂等冲突异常；
幂等结果语义；
数据库唯一约束示例测试。
```

不得在本阶段替后续业务模块定义完整幂等键。

### 4.11 基础异常语义

本阶段应建立统一异常分类或等价错误语义。

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
异常可映射为稳定 reason_code；
unknown 不得自动映射为 succeeded 或 failed；
高风险异常后续应能写 AlertEvent。
```

### 4.12 AlertEvent

本阶段应实现 AlertEvent 的最小可写基础。

AlertEvent 是系统事件、异常和交易状态通知事实，不等于外部通知投递。

AlertEvent 的对象身份、幂等语义和后续投递扩展必须与 `notifications.md` 一致。阶段 6 只能扩展同一模型及其投递对象，不得另建第二套事件事实。

本阶段只需要：

```text
定义 AlertEvent 基础模型；
提供 AlertEvent 写入 service；
支持 event_key 去重或等价防重复；
支持 severity / category / reason_code / message_summary / trace_id / trigger_source；
支持脱敏摘要；
支持基础测试。
```

本阶段不实现：

```text
Hermes 投递；
NotificationDeliveryAttempt 完整投递状态机；
NotificationSuppression 完整抑制规则；
通知 worker；
通知模板系统。
```

这些留到通知阶段。

### 4.13 AuditRecord

本阶段应实现 AuditRecord 的最小可写基础。

AuditRecord 用于记录人工操作和高风险状态变更，不替代业务对象状态。

本阶段至少支持：

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
用 AlertEvent 替代 AuditRecord；
用 AuditRecord 替代业务对象状态。
```

### 4.14 真实交易权限基础

本阶段必须建立真实交易权限的最小基础，但不进入订单链路。

真实交易权限由两层共同决定：

```text
.env / Django settings 中的部署级硬权限；
MySQL 中由后台管理的运行开关。
```

最终权限语义：

```text
真实交易最终权限 = 部署级硬权限 AND MySQL 运行开关
```

本阶段必须实现：

```text
从 settings 读取部署级硬权限；
MySQL 保存运行开关；
计算最终权限；
权限不可读取时 fail-closed；
开关变更写 AuditRecord；
必要时写 AlertEvent；
默认关闭真实交易。
```

本阶段不实现：

```text
OpsConsole 页面；
OrderPlanStepAdapter；
OrderPlan；
真实下单；
订单链路准入。
```

但本阶段输出的服务必须能被后续 OrderPlanStepAdapter 使用。

### 4.15 Django system checks

本阶段应建立基础 Django system checks。

至少检查：

```text
必要 settings 是否存在；
Django 是否显式读取 .env；
数据库配置是否来自环境；
Redis 配置是否存在；
真实交易硬权限默认关闭；
active market domain 配置是否唯一且合法；
Celery timezone 是否为 UTC；
测试环境是否禁用真实外部 adapter；
危险配置组合是否 fail-closed。
```

system check 不得：

```text
调用 Binance；
调用外部大模型；
发送 Hermes；
提交订单；
修改数据库业务对象；
自动开启或关闭真实交易。
```

### 4.16 测试框架

本阶段必须建立可运行测试基础。

推荐：

```text
pytest；
pytest-django；
Django test database；
factory / fixture 可后续按需引入。
```

测试默认规则：

```text
不访问真实 Binance；
不访问真实外部大模型；
不发送真实 Hermes；
不访问生产 MySQL；
不访问生产 Redis；
不依赖真实 API key；
不提交真实订单；
使用 UTC；
使用 fake / mock 外部服务边界。
```

阶段 0 至少应覆盖：

```text
Django settings 可以加载；
.env.example 配置完整；
MySQL 配置缺失时明确失败；
Redis 配置可读取；
Celery app 可以加载；
UTC 配置正确；
trace_id 可以生成和传递；
trigger_source 可以显式传递；
AlertEvent 可以通过 service 写入；
AuditRecord 可以通过 service 写入；
真实交易最终权限默认关闭；
权限不可读取时 fail-closed；
日志脱敏规则基础测试；
Django system checks 可以运行。
```

---

## 5. 建议实施顺序

### 5.1 初始化工程结构

执行内容：

```text
创建 pyproject.toml；
创建 Django project；
创建 config/；
创建 apps/；
创建 tests/；
建立 pytest 配置；
建立 .gitignore；
建立 .env.example。
```

验收：

```text
Python 版本约束正确；
Django 可以 import；
项目目录没有旧版临时目录路径；
真实 .env 不进入 Git。
```

### 5.2 配置系统与 `.env`

执行内容：

```text
选择一种明确 .env 读取方案；
settings 启动时加载 .env；
定义必要环境变量；
实现配置缺失时的清晰错误；
更新 .env.example 中文注释。
```

验收：

```text
settings 不依赖 Django 默认 DATABASES；
MySQL / Redis / Celery 配置均来自环境；
缺少必要数据库配置时失败信息清楚；
真实交易硬权限默认关闭。
```

### 5.3 MySQL 与 migration

执行内容：

```text
配置 MySQL；
创建基础 app；
创建 AlertEvent / AuditRecord / RuntimeTradingConfig 等基础模型；
生成 migration；
验证 migration。
```

验收：

```text
Django migration 可以在测试数据库执行；
核心基础表来自 Django migration；
没有手写建表脚本替代 migration。
```

### 5.4 Redis 与 Celery

执行内容：

```text
配置 Django cache / Redis；
配置 Celery app；
配置 Celery Beat 入口；
创建只用于健康检查的最小任务或导入测试。
```

验收：

```text
Celery app 能加载；
Celery 配置来自环境；
没有业务任务；
没有订单、Binance、DeepSeek、Hermes 调用。
```

### 5.5 公共上下文与异常

执行内容：

```text
实现 trace_id 生成；
实现 trigger_source 标准语义；
实现基础 service result 语义；
实现基础异常类型或 reason_code 映射；
实现日志脱敏工具。
```

验收：

```text
trace_id 不被用作幂等键；
trigger_source 由入口显式设置；
unknown 不被映射为成功或失败；
敏感信息不会进入日志。
```

### 5.6 AlertEvent 与 AuditRecord service

执行内容：

```text
实现 AlertEvent 写入 service；
实现 AuditRecord 写入 service；
实现 event_key 去重或等价防重复；
实现基础脱敏摘要。
```

验收：

```text
业务入口只能通过 service 写入；
重复 event_key 不产生重复告警事实；
审计记录不替代业务对象；
敏感字段不进入 AlertEvent / AuditRecord。
```

### 5.7 真实交易权限基础

执行内容：

```text
读取 settings 中的部署级真实交易硬权限；
读取 MySQL 真实交易运行开关；
计算最终真实交易权限；
实现 fail-closed；
变更运行开关写 AuditRecord；
必要时写 AlertEvent。
```

验收：

```text
默认最终权限为关闭；
.env 关闭时 MySQL 开启也不能放行；
MySQL 关闭时 .env 开启也不能放行；
任一配置不可读取时 fail-closed；
本阶段不会调用 OrderPlan。
```

### 5.8 system checks 与基础测试

执行内容：

```text
实现 Django system checks；
实现 pytest / pytest-django 基础测试；
实现配置安全测试；
实现 migration 测试；
实现 fake 外部服务默认禁止测试。
```

验收：

```text
python manage.py check 可以运行；
pytest 可以运行；
测试不访问真实外部服务；
测试不依赖真实密钥；
测试不访问生产数据库或生产 Redis。
```

---

## 6. 本阶段不实现

阶段 0 明确不实现：

```text
行情采集；
数据质量；
数据回补；
MarketSnapshot；
FeatureLayer；
AtomicSignal；
DomainSignal；
MarketRegime；
StrategyRouting；
StrategySignal；
DecisionSnapshot；
BinanceGateway 真实请求；
Binance Account Sync；
PriceSnapshot；
OrderPlan；
CandidateOrderIntent；
RiskCheck；
ApprovedOrderIntent；
ExecutionPreparation；
Execution；
OrderStatusSync；
FillSync；
PipelineOrchestrator；
RuntimeGuard；
Notifications 投递；
OpsConsole 页面；
ReviewDataset；
项目内未授权外部大模型请求。
```

本阶段可以为这些模块预留配置项、基础接口形状或 fake 注入机制，但不得实现真实业务逻辑。

---

## 7. 外部服务边界

阶段 0 不访问真实外部服务。

禁止：

```text
访问 Binance；
访问 DeepSeek；
发送 Hermes；
提交真实订单；
修改交易所杠杆；
修改保证金模式；
访问真实生产数据库；
访问真实生产 Redis。
```

允许：

```text
定义配置项；
定义 fake / mock 注入机制；
定义 Gateway 后续接入的基础异常和日志脱敏规则；
定义测试中禁止真实网络访问的安全检查。
```

---

## 8. 数据库迁移范围

本阶段 migration 只覆盖基础设施对象。

建议包括：

```text
AlertEvent；
AuditRecord；
RuntimeTradingConfig 或等价真实交易运行开关；
必要的基础配置摘要对象。
```

不应在本阶段创建完整业务链路表。

禁止本阶段提前创建：

```text
Kline；
FeatureValue；
AtomicSignalValue；
DecisionSnapshot；
OrderPlan；
CandidateOrderIntent；
ApprovedOrderIntent；
ExchangeOrder；
TradeFill；
ReviewDatasetRecord。
```

这些表应由对应业务阶段按需求创建。

---

## 9. 安全风险与处理

### 9.1 Django 未读取 `.env`

风险：

```text
Django 使用默认配置启动；
数据库连接失败；
误连本地 SQLite；
误用生产配置。
```

处理：

```text
settings 必须显式读取 .env；
关键配置缺失必须明确失败；
正式默认数据库只能是 MySQL；
测试数据库必须隔离。
```

### 9.2 真实交易误开启

风险：

```text
默认配置误放行真实交易；
后台开关绕过 .env；
测试参数切到真实交易。
```

处理：

```text
真实交易硬权限默认关闭；
最终权限使用 AND 模型；
权限不可读 fail-closed；
测试环境禁止真实外部 adapter；
system check 检查危险组合。
```

### 9.3 Redis 被误当主存储

风险：

```text
核心业务事实只存在 Redis；
Redis 丢失导致事实不可追溯；
Redis 缓存被用于放行真实交易。
```

处理：

```text
MySQL 是唯一核心事实主存储；
Redis 只做缓存、锁、Celery 和短期状态；
Redis 故障不得放行真实交易。
```

### 9.4 日志泄密

风险：

```text
密钥、签名、完整请求体或响应体进入日志、AlertEvent 或审计。
```

处理：

```text
建立脱敏工具；
基础测试覆盖敏感字段；
外部服务日志只记录摘要。
```

---

## 10. 阶段验收命令

具体命令以最终项目脚手架为准，但阶段 0 至少应提供等价验收：

```text
python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py migrate --check 或测试数据库 migration 验证
pytest
```

如果使用具体依赖管理工具，应补充对应命令，例如：

```text
uv run python manage.py check
uv run pytest
```

或：

```text
poetry run python manage.py check
poetry run pytest
```

阶段回报必须说明实际使用哪一种。

---

## 11. 阶段通过标准

阶段 0 通过必须满足：

```text
Django 项目可以启动；
settings 显式读取 .env；
.env.example 完整且有中文注释；
MySQL 配置来自环境；
Redis 配置来自环境；
Celery app 可以加载；
Celery Beat 入口存在；
UTC 配置正确；
基础日志可用且脱敏；
trace_id 可以生成和传递；
trigger_source 可以显式传递；
AlertEvent 可以通过 service 写入；
AuditRecord 可以通过 service 写入；
真实交易最终权限默认关闭；
权限不可读取时 fail-closed；
Django system checks 可运行；
基础测试可运行；
测试默认不访问真实外部服务；
没有真实交易能力；
没有提前实现业务链路。
```

---

## 12. 阶段失败标准

出现以下任一情况，本阶段不得通过：

```text
Django 仍依赖默认 DATABASES；
settings 没有显式读取 .env；
SQLite 被作为正式默认数据库；
.env.example 缺少关键配置或中文注释；
真实密钥进入仓库；
真实交易默认开启；
后台运行开关可以绕过 .env 硬权限；
Redis 被用于保存核心业务事实；
Celery task 中出现复杂业务逻辑；
测试访问真实 Binance、Hermes 或外部大模型；
测试访问生产 MySQL 或生产 Redis；
本阶段提前实现 OrderPlan、Execution 或真实下单能力；
日志、AlertEvent 或 AuditRecord 泄露敏感信息。
```

---

## 13. 交付回报要求

阶段 0 编码完成后，回报必须说明：

```text
本阶段实现了什么；
新增和修改了哪些文件；
Django settings 如何读取 .env；
MySQL / Redis / Celery 如何配置；
是否写库；
是否访问 Redis；
是否访问外部服务；
是否发送 Hermes；
是否调用大模型；
是否涉及交易执行；
是否可能真实交易；
真实交易权限默认状态；
AlertEvent / AuditRecord 是否已落库；
测试命令与结果；
本阶段明确不负责什么；
是否违反 project_invariants.md。
```

如测试无法运行，必须说明原因和下一步处理。

---

## 14. 下一阶段入口

阶段 0 验收通过后，下一步进入：

```text
docs/plans/market_data_implementation_plan.md
```

也就是行情数据与市场事实阶段。

在进入下一阶段前，不应开始策略、订单、风控、执行或后台复盘能力。
