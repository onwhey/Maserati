# OpsConsole 与 ReviewDataset 实施计划

## 1. 文档目的

本文档定义后台运维、受控人工操作和复盘数据集导出的实施顺序。

本阶段实现的是：

```text
OpsConsole 后台查询与受控操作入口；
ReviewDataset 复盘数据集构建、导出和下载；
相关 AlertEvent、AuditRecord、权限、CSRF 和测试。
```

本阶段不实现系统内大模型复盘，不在项目内调用外部大模型，不保存大模型报告，不自动生成策略修改建议。

离线复盘由项目外部的 Codex skill 或人工工具读取 ReviewDataset 导出文件完成；其输出保存在本地，不写入生产数据库。

## 2. 依据文档

实施前必须阅读：

```text
docs/requirements/project_scope.md
docs/requirements/system_capabilities.md
docs/requirements/core_contracts.md
docs/requirements/project_foundation.md
docs/requirements/ops_console.md
docs/requirements/review_dataset.md
docs/requirements/notifications.md
docs/requirements/runtime_guard.md
docs/architecture/system_architecture.md
docs/architecture/module_boundary_architecture.md
docs/architecture/data_flow_architecture.md
docs/architecture/runtime_task_architecture.md
docs/architecture/testing_and_safety_architecture.md
docs/rules/project_invariants.md
```

如以上文档冲突，以红线、决策、requirements、architecture、plans 的优先级处理，不得自行猜测。

## 3. 范围边界

### 3.1 OpsConsole

OpsConsole 负责：

```text
登录态和后台权限；
只读查询 Dashboard、编排、订单、账户展示、告警、巡检和审计；
受控人工操作入口；
真实交易运行开关；
ReviewDataset 创建、状态查询、下载和历史记录查看；
前端页面与后端 API 的安全交互。
```

OpsConsole 不得：

```text
直接访问 MySQL 或 Redis；
直接调用 BinanceGateway；
直接调用外部大模型；
直接提交订单；
直接释放 ActiveLock；
直接改写业务对象状态；
管理 API key；
写 .env；
热切 active market domain；
在前端复制交易状态机、订单状态机或复盘数据构建规则。
```

### 3.2 ReviewDataset

ReviewDataset 负责：

```text
按 UTC 4 小时周期、编排和业务对象关系读取已落库事实；
整理行情、特征、原子、领域、市场环境、策略、决策、账户、价格、订单、成交、告警、巡检和审计事实；
记录缺失事实和不可构建原因；
生成可下载数据集；
提供本地离线复盘所需的完整证据包。
```

ReviewDataset 不得：

```text
请求 Binance；
调用外部大模型；
生成交易信号；
修改策略；
修改真实交易运行配置；
提交、撤销或重试订单；
释放 ActiveLock；
影响自动交易主链路；
被 RuntimeGuard 巡检为主链路异常。
```

## 4. 推荐实施顺序

### 4.1 后端基础

实现后台 API 的通用能力：

```text
Django session 登录；
CSRF 保护；
后台权限校验；
统一 JSON 响应；
统一错误码；
AuditRecord 写入入口；
AlertEvent 写入入口；
分页、筛选和排序基础工具。
```

所有后台 API 都必须在后端校验权限，前端隐藏按钮不能替代后端权限。

### 4.2 OpsConsole 只读查询

实现以下只读查询：

```text
Dashboard 摘要；
OrchestrationRun 列表和详情；
订单链路列表和详情；
账户展示；
RuntimeGuardIssue；
AlertEvent；
AuditRecord；
ReviewDataset 列表和详情。
```

只读查询只能通过 selector / service 读取已落库事实，不得在 view 中写复杂查询逻辑。

### 4.3 受控人工操作

实现已由 `ops_console.md` 授权的人工入口：

```text
真实交易运行开关；
账户展示刷新；
订单状态受控补查；
成交受控补同步；
ActiveLock 授权人工收尾。
```

每个写操作必须具备：

```text
明确操作对象；
操作者；
二次确认；
原因；
影响摘要；
AuditRecord；
必要 AlertEvent；
后端权限校验；
CSRF 防护。
```

人工入口不得重试订单提交。

### 4.4 ReviewDataset 后端

实现 ReviewDataset 的核心对象和服务：

```text
ReviewDatasetRecord；
ReviewDatasetExport；
ReviewDatasetBuildService；
ReviewDatasetExportService；
ReviewDatasetSelector。
```

构建逻辑应放在 service / domain 层，不得放在 view、serializer、model、Celery task 或 management command 中。

构建范围至少支持：

```text
按 UTC 4 小时周期范围；
按 OrchestrationRun；
按交易订单链路相关对象；
按导出批次查询历史结果。
```

重复请求应按范围、输入事实指纹和数据集版本做幂等；输入一致时返回已有有效数据集。

### 4.5 ReviewDataset API 与下载

实现后台 API：

```text
预览可导出范围；
创建数据集；
查询数据集状态；
下载数据集文件；
查看数据集缺失事实和构建摘要。
```

下载内容不得包含：

```text
API key；
secret；
签名；
完整外部原始响应；
session cookie；
未脱敏大体积敏感数据。
```

### 4.6 OpsConsole 前端

实现前端页面：

```text
登录页；
Dashboard；
Runs；
Orders；
Account；
Runtime Guard；
Alerts；
Real Trading；
Ops Actions；
Audit Log；
Review Dataset。
```

前端使用 Next.js、TypeScript、shadcn/ui 和 Recharts。不得绕过后端 service 直接访问后端内部对象。

Review Dataset 页面只负责触发和下载数据集，不在前端实现复盘算法。

## 5. 任务与调度

OpsConsole API 可以同步执行轻量操作。

ReviewDataset 构建如果可能超时，应投递到离线任务组，由 Celery task 作为入口调用 service。

Celery task 只能：

```text
解析任务参数；
设置 trace_id 和 trigger_source；
调用 ReviewDataset service；
返回摘要。
```

Celery task 不得直接访问 Binance、Hermes、外部大模型或数据库写复杂业务逻辑。

ReviewDataset 不使用 Celery Beat 自动运行。

## 6. 数据与存储

MySQL 保存：

```text
ReviewDatasetRecord；
ReviewDatasetExport；
AuditRecord；
必要 AlertEvent；
导出文件元数据、输入指纹、数据集版本和构建状态。
```

导出文件可以保存在项目约定的本地或对象存储位置，数据库只保存索引和元数据。

Redis 只能用于：

```text
短期构建锁；
任务状态辅助；
限流；
下载短期令牌。
```

Redis 不得作为 ReviewDataset 唯一事实来源。

## 7. AlertEvent 与审计

必须写 AuditRecord 的行为：

```text
登录失败达到限制；
真实交易运行开关变更；
受控订单状态补查；
受控成交补同步；
人工 ActiveLock 收尾；
ReviewDataset 创建；
ReviewDataset 下载；
ReviewDataset 删除或过期清理。
```

必须写 AlertEvent 的行为：

```text
高风险人工操作；
ReviewDataset 构建失败；
ReviewDataset 构建发现关键事实缺失；
后台写操作失败；
通知或审计写入异常。
```

AlertEvent 是否需要外部通知由 Notifications 规则决定。

## 8. 测试要求

至少覆盖：

```text
未登录无法访问后台 API；
未授权无法执行写操作；
CSRF 缺失时写操作失败；
前端隐藏按钮不影响后端权限；
真实交易运行开关不能突破 .env 硬权限；
订单补查和成交补同步只调用对应业务 service；
ActiveLock 人工收尾不能绕过 ActiveLockService；
ReviewDataset 只读取已落库事实；
ReviewDataset 不请求 Binance；
ReviewDataset 不调用外部大模型；
ReviewDataset 缺少事实时记录原因，不伪造数据；
相同范围和输入指纹重复创建返回已有有效数据集；
导出文件不包含密钥、签名和未脱敏敏感数据；
RuntimeGuard 不巡检 ReviewDataset；
后台任一入口不得重新提交订单。
```

前端至少运行：

```text
npm run typecheck
npm run build
```

后端至少运行相关 Django / pytest 测试。

## 9. 验收标准

本阶段完成时应能证明：

```text
OpsConsole 所有 API 都有登录、权限和 CSRF 边界；
后台写操作都有审计和必要 AlertEvent；
ReviewDataset 可以按明确范围生成可下载数据集；
ReviewDataset 不进入自动交易主链路；
ReviewDataset 不调用 Binance、不调用外部大模型、不修改交易事实；
项目内不存在系统内大模型复盘模块；
离线复盘输出不写入生产数据库；
测试能证明后台、复盘导出和交易主链路隔离。
```

## 10. 明确不负责

本计划不负责：

```text
策略算法设计；
特征、原子、领域和市场环境算法；
订单计划、风控、执行和订单追踪规则；
真实 Binance 调用实现；
Hermes 通知通道实现；
外部 Codex skill 的具体复盘 prompt；
本地复盘报告存储格式；
自动策略优化；
自动参数调优；
自动把复盘结论写回生产系统。
```
