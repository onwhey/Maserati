# 后台、绩效与离线 AI 复盘实施计划

## 1. 文档目的

本文档用于指导阶段 7 的代码实施与验收。

本阶段在自动交易主链路、编排、通知和巡检已经完成的基础上，实现面向运维、人工审查和离线复盘的后置能力：

```text
OpsConsole 独立 Web Console；
Django 受控后台 API；
账户展示与 ops_display 刷新；
真实交易运行开关管理；
编排、订单、成交、告警和巡检查询；
受控人工运维入口；
PerformanceMetrics 后台一键补算；
DeepSeekGateway；
AIReview 离线复盘。
```

本阶段不是自动交易主链路的一部分。

后台页面、绩效补算和 AIReview 的失败、阻塞或积压不得阻断四小时自动编排，不得改变实时策略决策，不得自动恢复交易。

---

## 2. 阶段定位

本阶段对应 [implementation_roadmap.md](implementation_roadmap.md) 的阶段 7：

```text
后台、绩效与离线 AI 复盘。
```

主要运行关系：

```text
Next.js OpsConsole
→ Django 受控 API
→ application service / selector
→ MySQL 业务事实；

OpsConsole
→ PerformanceMetrics service
→ 扫描并补齐所有缺失且可计算的已关闭四小时周期；

OpsConsole
→ AIReview service
→ 构建脱敏数据包
→ DeepSeekGateway
→ DeepSeek
→ 保存离线报告、发现和人工建议。
```

本阶段涉及账户刷新、订单状态补查、成交补同步和 ActiveLock 人工收尾等受控人工入口，但 OpsConsole 只负责展示、授权、二次确认和审计；实际动作必须由对象所属业务模块的 application service 执行。

---

## 3. 已确定技术方向

### 3.1 前端

正式 OpsConsole 使用：

```text
Next.js；
TypeScript；
shadcn/ui；
Recharts（P0 图表）；
Next.js App Router。
```

选择 Recharts 作为 P0 图表实现，是为了满足周期收益曲线和基础趋势展示，避免在当前阶段引入复杂图表平台。后续如确需复杂交互图表，可以通过独立计划评估 ECharts，不在本阶段同时维护两套图表库。

### 3.2 后端

```text
Django；
Django ORM；
Django migrations；
Django 内建 authentication、session、group 与 permission；
Django JSON API；
Celery / Redis；
MySQL。
```

本阶段不额外引入第二套 Python Web 框架、认证框架或 ORM。

### 3.3 前后端认证边界

P0 使用 Django 内建 session 认证：

```text
HttpOnly session cookie；
CSRF 防护；
Secure cookie（生产环境）；
SameSite 受控策略；
后端逐接口权限校验；
危险操作二次确认凭据或等价确认参数。
```

正式部署应让 OpsConsole 与 Django API 处于同一受控站点边界或由反向代理形成同源访问，减少跨域认证复杂度。

本阶段不自研 token 系统，不默认引入 JWT，不把登录凭据保存到浏览器 localStorage。

---

## 4. 前置条件

开始本阶段编码前，阶段 0 至阶段 6 必须已经通过验收，至少具备：

```text
Django、MySQL、Redis、Celery、日志、UTC 和配置基础；
Django 用户、AuditRecord、AlertEvent 和真实交易运行配置基础；
所有主交易业务对象和真实业务外键；
PipelineOrchestrator 查询 service；
OrchestrationRun、StepRun 和 ObjectLink；
RuntimeGuardRun 与 RuntimeGuardIssue；
Notifications 投递状态；
Binance Account Sync 的 trade_preparation 与 ops_display 入口；
OrderStatusSync、FillSync 与 ActiveLockService；
四小时自动账户边界事实；
独立离线任务组。
```

如果前置阶段尚未提供明确 application service，OpsConsole 不得通过直接写表临时补齐。

---

## 5. 文档依据

### 5.1 主要需求依据

```text
docs/requirements/ops_console.md
docs/requirements/performance_metrics.md
docs/requirements/deepseek_gateway.md
docs/requirements/ai_review.md
docs/requirements/binance_account_sync.md
docs/requirements/notifications.md
docs/requirements/order_plan.md
docs/requirements/order_submission.md
docs/requirements/order_status_sync.md
docs/requirements/fill_sync.md
docs/requirements/pipeline_orchestrator.md
docs/requirements/runtime_guard.md
```

### 5.2 公共约束依据

```text
AGENTS.md
docs/rules/project_invariants.md
docs/requirements/project_scope.md
docs/requirements/system_capabilities.md
docs/requirements/core_contracts.md
docs/requirements/project_foundation.md
```

### 5.3 架构依据

```text
docs/architecture/system_architecture.md
docs/architecture/module_boundary_architecture.md
docs/architecture/data_flow_architecture.md
docs/architecture/runtime_task_architecture.md
docs/architecture/testing_and_safety_architecture.md
```

### 5.4 前置实施计划

```text
docs/plans/foundation_implementation_plan.md
docs/plans/market_data_implementation_plan.md
docs/plans/strategy_analysis_implementation_plan.md
docs/plans/account_price_fact_implementation_plan.md
docs/plans/trading_execution_implementation_plan.md
docs/plans/order_lifecycle_implementation_plan.md
docs/plans/orchestration_runtime_implementation_plan.md
```

发生冲突时，按项目文档优先级处理，不得由本实施计划覆盖 requirements 或 project_invariants。

---

## 6. 本阶段核心口径

### 6.1 OpsConsole 只通过后端能力工作

```text
页面只调用 Django API；
API 只调用 application service / selector；
前端不访问 MySQL；
前端不访问 Redis；
前端不调用 BinanceGateway；
前端不调用 DeepSeekGateway；
前端不直接发送 Hermes；
前端不直接修改任何业务表。
```

### 6.2 后台不是自动修复系统

OpsConsole 可以提供明确授权的人工操作入口，但不得：

```text
自动重跑交易；
自动重新提交订单；
自动撤单或补单；
绕过 RiskCheck；
绕过 ExecutionPreparation；
直接修改订单、成交、编排或锁状态；
把 unknown 手工改成 success；
把 AIReview 建议直接应用到生产。
```

### 6.3 PerformanceMetrics 是后置补算

```text
只读取已落库事实；
只使用相邻自动 trade_preparation 账户边界快照；
不使用 ops_display；
不请求 Binance；
不加入四小时主编排；
不由 Celery Beat 自动定时计算；
不由 RuntimeGuard 巡检；
不生成交易信号或交易动作。
```

### 6.4 AIReview 是离线分析

```text
只读取已落库事实；
先构建可追溯、脱敏、大小受控的数据包；
只通过 DeepSeekGateway 调用 DeepSeek；
只保存报告、发现和人工建议；
不参与实时交易；
不修改策略、风控、订单、账户、绩效或锁；
不自动重新调用不确定的模型请求。
```

### 6.5 DeepSeekGateway 只提供底层访问

DeepSeekGateway 不拥有复盘范围、prompt 业务含义或报告对象。

调用方只传受控 `model_profile_code`，不得传完整模型配置、任意模型名、base URL 或 API key。

DeepSeekGatewayResult 是进程内的标准化返回合同，不建立独立数据库业务表。需要持久化的业务调用事实由 `AIReviewAttempt` 保存。

### 6.6 真实交易运行开关边界

```text
.env / Django settings 是部署级硬权限；
MySQL 是后台真实交易运行开关；
最终权限 = 硬权限 AND 运行开关。
```

后台只能修改 MySQL 开关，不能写 `.env`，不能管理密钥，不能热切 active market domain。

### 6.7 所有危险操作必须可审计

危险操作必须具备：

```text
已登录用户；
明确权限；
明确目标对象 ID；
二次确认；
操作原因；
trace_id；
AuditRecord；
必要 AlertEvent；
结构化结果。
```

---

## 7. 本阶段实现范围

### 7.1 OpsConsole 页面与 API

P0 至少实现：

```text
登录；
Dashboard；
Runs 列表与详情；
Orders 列表与详情；
Account Overview；
Performance；
Runtime Guard；
Alerts；
Real Trading；
AI Review；
Ops Actions；
Audit Log。
```

页面可以合并布局，但权限和业务入口必须保持独立。

### 7.2 账户展示

实现当前 active account domain 的账户展示和一键刷新。

刷新必须调用：

```text
Binance Account Sync 的 ops_display service。
```

不得生成 `trade_preparation` 批次，不得供 OrderPlan、RiskCheck、ExecutionPreparation 或 PerformanceMetrics 消费。

### 7.3 真实交易控制

实现：

```text
展示脱敏部署级硬权限；
展示 active market domain；
展示 MySQL 运行开关；
展示最终真实交易权限；
开启运行开关；
关闭运行开关；
展示最近变更审计。
```

开启需要高权限和二次确认。开启与关闭都必须通过 ProjectFoundation 的运行配置 service，写 AuditRecord 和 AlertEvent。

### 7.4 编排、订单、成交、巡检和通知查询

实现只读 selector / API，用于展示：

```text
完整 OrchestrationRun；
每一步 StepRun 和统一结果；
业务对象索引和真实业务外键链；
OrderPlan 到 TradeFill 的完整订单链；
ActiveLock；
RuntimeGuardIssue；
AlertEvent；
NotificationDeliveryAttempt；
NotificationSuppression；
AuditRecord。
```

### 7.5 受控人工操作

实现 OpsConsole 需求已经明确允许的入口：

```text
刷新 Account Overview；
对明确 OrderSubmissionAttempt 执行订单状态受控补查；
对明确 OrderSubmissionAttempt 执行成交受控补同步；
对明确 OrderPlanActiveLock 执行人工收尾；
更新 RuntimeGuardIssue 人工状态；
预览并补齐 PerformanceMetrics；
创建 AIReviewRequest；
更新 AIReviewSuggestion 人工状态。
```

不得增加通用 SQL、任意模型写入、任意 client_order_id 查询或通用 Gateway 调试入口。

### 7.6 PerformanceMetrics

实现：

```text
缺失周期扫描预览；
所有缺失且可计算周期的一键补齐；
单周期内部计算；
OrchestrationRunPerformance；
订单和成交辅助上下文；
幂等、并发与审计；
查询 service；
可选离线 Celery task。
```

### 7.7 DeepSeekGateway

实现：

```text
受限 AIReview 接口；
Model Profile 注册与选择；
请求格式构造；
结构化输出约束；
连接和读取超时；
请求前有限技术重试；
限频、并发、冷却与熔断；
错误标准化；
token usage；
脱敏技术日志；
Fake Gateway。
```

### 7.8 AIReview

实现：

```text
五种 review_mode；
冻结复盘范围；
构建脱敏数据包；
输入大小与成本控制；
版本化 prompt；
AIReviewAttempt；
DeepSeekGateway 结果映射；
结构化报告解析；
Report / Finding / Suggestion；
建议人工状态流转；
权限、审计与 AlertEvent；
离线 Celery task。
```

---

## 8. 建议代码结构

### 8.1 Django 后端

建议新增或完善：

```text
apps/ops_console/
apps/performance_metrics/
apps/deepseek_gateway/
apps/ai_review/
```

继续复用：

```text
apps/audit/
apps/alerts/
apps/runtime_config/ 或现有 ProjectFoundation 运行配置模块；
apps/orchestration/
apps/runtime_guard/
各业务模块的 service 和 selector。
```

`apps/ops_console` 只放：

```text
API view；
request / response schema 或表单校验；
权限校验；
二次确认校验；
页面聚合 selector；
Ops action application facade。
```

不得把 PerformanceMetrics 算法、AIReview 数据包构建、订单状态查询、成交同步或锁收尾规则写入 `ops_console`。

### 8.2 Next.js 前端

建议目录：

```text
frontend/ops-console/
```

建议职责结构：

```text
app/
  App Router 页面和布局；

components/
  shadcn/ui 组件组合、表格、状态徽标、确认对话框；

features/
  runs、orders、account、performance、runtime-guard、alerts、real-trading、ai-review、ops-actions；

lib/api/
  受控 Django API client；

lib/auth/
  session 状态和 CSRF 处理；

lib/time/
  UTC 格式化；

types/
  API 响应类型；

tests/
  页面、权限、危险操作和 API client 测试。
```

不得在前端复制后端业务状态机或收益算法。

---

## 9. 数据库迁移范围

### 9.1 OpsConsole

OpsConsole 本身不复制主业务对象。

优先复用：

```text
Django User / Group / Permission；
AuditRecord；
RuntimeTradingConfig 或既有运行配置事实；
AlertEvent；
RuntimeGuardIssue。
```

底座阶段的 `AuditRecord` 是最小模型。本阶段必须通过 migration 复用并补齐 OpsConsole 正式审计合同，至少确认以下字段可独立查询和持久化：

```text
operator_id；
operator_role；
operation_type；
target_object_type；
target_object_id；
before_state_summary；
after_state_summary；
reason；
evidence；
result；
failure_reason；
trace_id；
trigger_source；
created_at_utc。
```

不得另建第二套 OpsConsoleAudit 表，不得覆盖或删除底座阶段已经存在的历史 AuditRecord。

如需保存二次确认挑战或短期危险操作授权，必须明确过期时间、一次性消费和操作者绑定；不得保存明文密码或长期万能确认 token。

### 9.2 PerformanceMetrics

迁移建立：

```text
OrchestrationRunPerformance。
```

字段、状态和原因码按 `performance_metrics.md` 实现，至少保存：

```text
周期开始和结束 UTC；
开始与结束 OrchestrationRun；
开始与结束 BinanceSyncRun；
market_type、account_domain、symbol；
开始和结束实际持仓数量；
开始和结束 mark price；
cycle_floating_pnl；
cycle_floating_pnl_pct；
订单与成交辅助上下文；
calculation_status；
reason_code；
算法或口径版本；
trace_id；
审计时间。
```

必须建立周期身份唯一约束，使重复补算返回已有有效记录。

### 9.3 DeepSeekGateway

不建立 `DeepSeekGatewayResult` 数据库表。

Gateway 的限频、冷却和熔断可使用 Redis 短期状态；需要长期保留的业务调用事实由 AIReviewAttempt 负责。

### 9.4 AIReview

迁移建立：

```text
AIReviewRequest；
AIReviewPackage；
AIReviewAttempt；
AIReviewReport；
AIReviewFinding；
AIReviewSuggestion。
```

必须落实：

```text
request_key 或等价请求幂等约束；
同一 Request 只有一份有效 Package；
Attempt sequence 唯一且递增；
同一 Request 最多一份 completed Report；
Package / prompt / output hash；
Suggestion 状态与人工审核字段；
按 review_mode、状态、时间和请求人查询的索引；
所有时间使用 UTC。
```

P0 只把大小受控的数据包写入 MySQL。超过正式输入或数据库大小上限时阻断请求，不在本阶段临时引入对象存储、向量数据库或外部知识库。

---

## 10. OpsConsole API 与权限设计

### 10.1 API 原则

所有 API 必须：

```text
要求登录；
执行后端权限校验；
校验输入 schema；
限制分页和时间范围；
只返回脱敏摘要；
明确 UTC；
返回稳定 reason_code；
危险操作要求二次确认和 reason；
写操作传递 trace_id 和 operator_id。
```

不得提供任意表名、字段名、SQL 条件、模型名、provider 参数或任意 Gateway endpoint。

### 10.2 权限角色

使用 Django Group / Permission 表达：

```text
readonly；
ops_operator；
review_exporter；
admin。
```

权限必须细分到具体动作，不只依赖角色名称。

至少区分：

```text
查看运行事实；
刷新账户展示；
执行订单状态补查；
执行成交补同步；
执行 ActiveLock 人工收尾；
管理 RuntimeGuardIssue 状态；
补算绩效；
发起 AIReview；
下载复盘数据；
更新建议状态；
开启真实交易运行开关；
关闭真实交易运行开关；
管理用户和权限。
```

### 10.3 二次确认

危险操作确认界面必须展示：

```text
目标对象；
动作；
是否访问 Binance；
是否写 MySQL；
是否影响锁；
是否涉及真实交易；
是否可撤销；
操作原因。
```

后端必须重新校验当前对象状态和权限，不能信任前端确认时看到的旧状态。

### 10.4 输出脱敏

API 不得返回：

```text
API key、secret、signature；
认证 header、cookie、session token；
数据库或 Redis 密码；
完整环境变量；
完整未脱敏外部请求或响应；
完整 DeepSeek prompt 和 provider payload；
不可控大体积 JSON。
```

---

## 11. OpsConsole 页面实施顺序

### 11.1 建立前端工程和认证壳

实现：

```text
Next.js + TypeScript；
shadcn/ui；
Recharts；
登录页；
受保护布局；
session 状态检查；
CSRF 获取与提交；
401 / 403 / 429 / unknown 统一展示；
UTC 时间组件；
基础无障碍和错误边界。
```

### 11.2 建立 Django API 基础

实现：

```text
登录、登出和当前用户；
统一 JSON 响应；
权限装饰器或等价中间件；
分页、筛选和时间范围校验；
危险操作确认校验；
trace_id；
审计写入；
API 错误脱敏。
```

### 11.3 Dashboard

Dashboard 只聚合现有 selector，不自行计算业务结果。

至少展示：

```text
最近运行状态；
最近周期收益曲线；
最近订单和 unknown；
当前 ActiveLock；
open RuntimeGuardIssue；
最近 AlertEvent；
最近 trade_preparation 与 ops_display 同步；
最近绩效补算；
真实交易权限摘要。
```

收益图使用 `cycle_floating_pnl`，不得用订单 realized PnL 替代。

### 11.4 Runs

实现运行列表、筛选和详情。

详情必须通过 PipelineOrchestrator 查询 service 获取编排索引，再通过对象所属 selector 展开业务详情。

链路缺失必须明确显示，不得静默隐藏。

### 11.5 Orders

围绕 `OrderSubmissionAttempt` 展示：

```text
PreparedOrderIntent 到 OrderPlan 的真实外键链；
提交事实；
状态查询记录；
成交汇总和 TradeFill；
订单级收益与手续费；
ActiveLock；
关联 run、告警和巡检问题。
```

订单级收益不得标注为周期浮动收益。

### 11.6 Account Overview

只读取当前 active account domain 最近有效的 `ops_display` 结果。

刷新按钮必须调用后台受控 service，并明确提示会访问 Binance、写 MySQL，但不会进入交易主链路。

### 11.7 Runtime Guard 与 Alerts

RuntimeGuard 页面只管理 Issue 人工状态，不修改原业务对象。

Alerts 页面区分：

```text
业务事件；
编排事件；
巡检事件；
通知投递状态。
```

AlertEvent 不能被页面转换成交易动作。

### 11.8 Real Trading

展示硬权限、运行开关、最终权限和审计。

开启和关闭都通过 ProjectFoundation service；开启操作必须更高权限和二次确认。

页面不提供其他业务模块开关。

### 11.9 Performance

提供：

```text
周期收益列表和曲线；
不可计算原因；
缺失周期预览；
一键补齐全部缺失且可计算周期；
扫描、计算、跳过和失败摘要；
最近操作审计。
```

不提供逐周期手工选择作为主要补算方式。

### 11.10 AI Review

提供：

```text
创建五种复盘请求；
选择受控范围；
选择后端允许的 model_profile_code；
查看请求、数据包、Attempt、报告、Finding 和 Suggestion；
下载脱敏数据包和报告；
管理建议人工状态。
```

页面不得提交完整 model profile、任意模型名、base URL、API key 或 provider 参数。

### 11.11 Ops Actions 与 Audit Log

Ops Actions 只列出后端明确判定当前可执行的动作。

Audit Log 展示人工操作审计，不允许普通用户删除或改写。

---

## 12. PerformanceMetrics 实施计划

### 12.1 周期识别

只识别 UTC 已关闭四小时周期：

```text
00:00 - 04:00；
04:00 - 08:00；
08:00 - 12:00；
12:00 - 16:00；
16:00 - 20:00；
20:00 - 00:00。
```

使用边界后五分钟自动 run 中的 `trade_preparation` 账户快照作为相邻边界。

### 12.2 一键补算流程

```text
用户预览；
→ 扫描所有已关闭周期；
→ 跳过已有有效记录；
→ 识别可计算与不可计算周期；
→ 二次确认；
→ 补齐全部缺失且可计算周期；
→ 保存每周期结果；
→ 返回扫描、计算、跳过和失败摘要；
→ 写 AuditRecord 和必要 AlertEvent。
```

重复点击必须返回或跳过已有有效记录。

### 12.3 快照选择

每周期必须使用：

```text
开始边界自动 run 的 trade_preparation 快照；
结束边界自动 run 的 trade_preparation 快照。
```

禁止使用：

```text
ops_display；
数据库 latest 任意快照；
人工选择快照；
旧周期外快照兜底；
Binance 实时查询。
```

### 12.4 计算口径

周期浮动收益使用相邻边界账户事实之间的持仓浮动变化。

必须正确覆盖：

```text
周期内新开仓；
周期内未调仓但价格变化；
周期内加仓或减仓；
无持仓；
无订单但持仓价值变化；
USDS-M 与 COIN-M 分离计算。
```

例如：

```text
00:05 无持仓；
00:05 后建立 0.1 BTC 持仓；
04:05 账户持仓价值变化对应 0.1 BTC；
该变化归属于 00:00 - 04:00 周期；

04:05 到 08:05 没有调仓；
持仓价值又增加 0.01 BTC；
第二周期只记录新增的 0.01 BTC 变化，不重复累计第一周期的 0.1 BTC。
```

具体公式和 USDS-M / COIN-M 数值口径必须严格按 `performance_metrics.md` 实现，并通过独立 calculator 或纯计算函数测试。

### 12.5 订单辅助上下文

订单 realized PnL、手续费和净 realized PnL 只作为辅助分析字段，不替代周期浮动收益。

### 12.6 不可计算

缺失任一合法自动边界快照时：

```text
保存或返回明确不可计算原因；
不请求 Binance；
不使用 ops_display；
不伪造零收益；
不影响自动主链路。
```

---

## 13. 受控人工运维实施计划

### 13.1 账户展示刷新

调用 Binance Account Sync 的 `ops_display` service，传入 operator、trace_id 和 UI trigger source。

刷新失败只影响后台展示。

### 13.2 订单状态受控补查

只允许针对明确 `OrderSubmissionAttempt`。

后台必须展示当前订单身份和状态，二次确认后调用 OrderStatusSync 的受控恢复或对账 service。

禁止：

```text
按最近一单；
按 symbol 猜订单；
输入任意 client_order_id；
重新提交订单；
直接修改 attempt；
直接释放锁。
```

### 13.3 成交受控补同步

只允许针对明确 attempt，且具有可追溯订单状态上下文。

由 FillSync service 自己保存 FillSyncResult、TradeFill 和 OrderFillSummary。

OpsConsole 不直接录入成交，不直接重算汇总，不更新持仓，不释放锁。

### 13.4 ActiveLock 人工收尾

只调用 OrderPlan 所属 ActiveLockService。

页面提供目标锁、订单状态、成交状态、证据、告警和巡检信息；最终目标状态由锁服务判断。

OpsConsole 不直接写锁状态。

### 13.5 RuntimeGuardIssue 状态

只调用 RuntimeGuard issue 状态管理 service。

`resolve` 只关闭巡检问题，不修改原业务对象，也不证明订单或锁已经完成。

---

## 14. DeepSeekGateway 实施计划

### 14.1 受限入口

只提供 `DeepSeekReviewGateway.generate_review_completion` 这一项 AIReview 所需受限语义操作，不暴露通用 HTTP request、通用聊天接口或任意 provider 参数接口。

业务调用只接受：

```text
model_profile_code；
结构化消息；
输出 schema；
不超过 profile 上限的 max_output_tokens；
idempotency_key；
trace_id；
受控 metadata。
```

### 14.2 Model Profile

Model Profile 由 settings 或代码注册表管理，至少冻结：

```text
provider；
model_name；
API format；
thinking / reasoning 参数；
输入输出上限；
超时；
结构化输出能力；
profile hash。
```

OpsConsole 和 AIReview 只能选择允许的 profile code。

### 14.3 结果合同

Gateway 返回标准化进程内结果，明确区分：

```text
succeeded；
blocked_before_send；
failed_before_send；
provider_rejected；
rate_limited；
timeout；
unknown_after_send；
response_parse_error；
failed。
```

必须携带 `request_sent`，使 AIReview 能区分发送前失败和发送后不确定。

### 14.4 重试

只允许对能明确证明请求未离开本地进程的技术错误执行有限重试。

请求已经发送或无法确认是否发送时不得自动重试。

Gateway 内部技术重试仍属于同一次 AIReviewAttempt。

### 14.5 限频与熔断

Redis 可保存短期限频、并发、冷却和熔断状态。

Redis 不可用时 fail-closed 或降级为更保守的单实例限制，不得绕过配置无限请求。

### 14.6 安全

```text
API key 只来自 settings；
不入库；
不返回前端；
不进入日志、AlertEvent 或 AIReviewPackage；
完整 prompt 和 provider 原始响应不进入普通技术日志；
错误摘要脱敏并限制大小。
```

---

## 15. AIReview 实施计划

### 15.1 Review Mode

第一版支持：

```text
cycle_review；
anomaly_review；
order_lifecycle_review；
performance_attribution_review；
manual_question_review。
```

未知模式 fail-closed。

### 15.2 创建请求

创建请求时：

```text
校验权限；
校验 review_mode；
冻结 UTC 范围和明确 run 集合；
校验 filters；
校验 manual question；
校验 model_profile_code；
生成 request_key；
保存 AIReviewRequest；
写 AuditRecord 和 AlertEvent；
不得立即在 Web 请求中同步调用 DeepSeek。
```

### 15.3 构建数据包

只读取 MySQL 已落库事实。

数据包至少包含需求规定的运行、策略、账户、价格、订单、成交、绩效、告警和巡检摘要。

不得重新计算特征、信号、目标仓位、订单计划、风控或绩效。

### 15.4 脱敏与大小控制

构建顺序：

```text
冻结输入引用；
读取业务事实；
生成受控摘要；
脱敏；
估算大小和 token；
验证 profile 上限；
生成 JSON 与 Markdown summary；
计算 input_refs_hash 和 package_hash；
保存 AIReviewPackage。
```

脱敏失败或数据包过大时，不调用 DeepSeekGateway。

### 15.5 Prompt 版本

每个 review mode 使用明确、版本化 prompt。

必须保存：

```text
prompt_name；
prompt_version；
prompt_hash；
prompt_schema_version；
output_schema_version。
```

prompt 必须声明这是离线复盘，禁止模型输出可直接执行的实时交易指令。

### 15.6 执行模型调用

```text
认领 AIReviewRequest；
确认已有合法 Package；
创建 AIReviewAttempt；
通过 DeepSeekGateway 调用；
保存 Gateway 摘要和 token usage；
显式映射结果；
成功时解析结构化输出；
创建 Report、Finding 和 Suggestion；
更新 Request；
写 AlertEvent。
```

### 15.7 不确定结果

DeepSeek 请求发送后超时或结果未知时：

```text
Attempt = unknown；
Request = unknown；
不自动重试；
不伪造报告；
由授权人员创建新的 AIReviewRequest 重新发起；
新请求引用原请求并写审计。
```

### 15.8 建议状态

Suggestion 只进行人工状态流转：

```text
pending_review；
accepted；
rejected；
converted_to_task；
implemented；
ignored。
```

任何状态变化都不执行建议内容，不修改代码、策略、配置或交易对象。

---

## 16. 离线任务与资源隔离

PerformanceMetrics 和 AIReview 使用离线任务组，与交易关键任务组隔离。

### 16.1 PerformanceMetrics

由后台点击触发，可同步扫描预览；正式批量补算可投递离线 task，避免页面超时。

不得使用 Celery Beat 自动补算。

### 16.2 AIReview

```text
创建 Request；
→ build package task；
→ run review task；
→ 保存结果。
```

不使用 Celery Beat 自动复盘。

### 16.3 重复任务

```text
PerformanceMetrics 依赖周期唯一约束；
AIReview 依赖 request_key、Package hash、Attempt 认领和唯一 completed Report；
Celery task id 不是业务幂等键；
worker 重启不能重复发送不确定的 DeepSeek 请求。
```

离线任务积压不得占用 Execution、OrderStatusSync 或 FillSync 的交易关键资源。

---

## 17. 配置范围

所有配置进入 `.env.example` 并附中文注释。

### 17.1 OpsConsole

OpsConsole 不建立独立业务总开关，也不建立用于绕过登录、权限或审计的配置。

部署层只需通过 Django 与 Next.js 的标准配置明确：

```text
正式站点地址和 API 同源路由；
Django session cookie 的 Secure / HttpOnly / SameSite；
CSRF trusted origins；
允许的 host；
默认和最大分页大小；
危险操作二次确认的短期有效时间。
```

实际配置名优先使用 Django 和 Next.js 内建配置；确需项目自定义的部署变量时，必须进入 `.env.example` 并附中文注释。这些配置只控制 Web 入口和安全策略，不得成为额外交易业务开关。

### 17.2 PerformanceMetrics

配置只允许控制安全的批处理大小、单次任务上限或算法版本选择，不得通过 env 改写收益业务语义。

具体周期、快照资格和公式以 requirements 为准。

### 17.3 DeepSeekGateway

按 `deepseek_gateway.md` 至少支持：

```text
DEEPSEEK_GATEWAY_ENABLED
DEEPSEEK_API_KEY
DEEPSEEK_BASE_URL
DEEPSEEK_API_FORMAT
DEEPSEEK_DEFAULT_MODEL_PROFILE
DEEPSEEK_DEFAULT_MODEL
DEEPSEEK_REVIEW_MODEL
DEEPSEEK_REASONING_ENABLED
DEEPSEEK_REASONING_EFFORT
DEEPSEEK_CONNECT_TIMEOUT_SECONDS
DEEPSEEK_READ_TIMEOUT_SECONDS
DEEPSEEK_MAX_RETRIES
DEEPSEEK_RETRY_BACKOFF_MS
DEEPSEEK_MAX_CONCURRENCY
DEEPSEEK_RATE_LIMIT_PER_MINUTE
DEEPSEEK_COOLDOWN_SECONDS
DEEPSEEK_MAX_INPUT_TOKENS
DEEPSEEK_MAX_OUTPUT_TOKENS
DEEPSEEK_JSON_OUTPUT_ENABLED
```

### 17.4 AIReview

AIReview 不建立独立请求开关。是否能够调用模型由 DeepSeekGateway 的部署配置、允许的 model profile 和 AIReview 权限共同约束。

AIReview 的容量和版本配置至少明确：

```text
单次请求最多允许的 run 数；
数据包最大字节数；
允许的 model profile code 集合；
默认 model profile code；
Package schema version；
sanitization version。
```

配置由 Django settings 或版本化代码定义统一读取；部署可调项进入 `.env.example` 并附中文注释。不得允许前端传任意模型、provider 或 base URL。

---

## 18. 数据、Redis 与外部服务边界

### 18.1 MySQL

MySQL 保存：

```text
用户、组和权限；
AuditRecord；
真实交易运行开关；
OrchestrationRunPerformance；
AIReviewRequest / Package / Attempt / Report / Finding / Suggestion；
AlertEvent；
所有既有业务事实。
```

### 18.2 Redis

可以用于：

```text
Celery broker / result backend；
短期 session 或 cache（如 Django settings 正式选择）；
DeepSeek 限频、并发、冷却和熔断；
AIReview 短期任务认领辅助；
PerformanceMetrics 批量任务短期锁。
```

Redis 不保存唯一绩效记录、唯一复盘报告、唯一建议或真实交易权限事实。

### 18.3 Binance

OpsConsole 后端自身不直接调用 BinanceGateway。

只有账户展示刷新、订单状态补查和成交补同步通过对应业务 service 间接访问允许的 BinanceGateway 受限接口。

PerformanceMetrics 和 AIReview 不访问 Binance。

### 18.4 DeepSeek

只有 AIReview 可以通过 DeepSeekGateway 调用。

OpsConsole 不直接调用 DeepSeekGateway。

### 18.5 Hermes

本阶段业务模块只写 AlertEvent。Hermes 投递继续由 Notifications 处理。

---

## 19. 测试计划

### 19.1 前端测试

至少覆盖：

```text
未登录跳转登录；
不同权限显示不同操作能力；
前端隐藏按钮不替代后端权限；
UTC 时间明确展示；
API 401 / 403 / 429 / 5xx / unknown 正确展示；
危险操作二次确认；
reason 必填；
Dashboard 不自行计算收益；
订单收益和周期收益标签不混淆；
AIReview 页面不提交完整 model profile；
敏感字段不渲染；
页面使用 mock API，不访问真实外部服务。
```

### 19.2 OpsConsole API 测试

至少覆盖：

```text
所有 API 要求登录；
readonly 不能写；
ops_operator 权限不包含用户管理；
review_exporter 权限不包含订单补查；
危险操作后端再次校验对象和权限；
分页和范围有上限；
API 不返回敏感信息；
人工操作写 AuditRecord；
真实交易开启无法突破 .env 硬权限；
后台不能热切 active market domain；
OpsConsole 不直接调用 Gateway。
```

### 19.3 页面聚合测试

至少覆盖：

```text
完整 run 可以展开所有关键对象；
缺失链路明确显示；
业务对象通过真实外键展开；
ObjectLink 只用于导航；
Order 页面围绕明确 attempt；
Account Overview 只读取 ops_display；
RuntimeGuardIssue 与原业务状态分开；
AlertEvent 类型分开；
Dashboard 收益来自 PerformanceMetrics。
```

### 19.4 PerformanceMetrics 测试

至少覆盖 requirements 中的所有公式与边界，并重点覆盖：

```text
相邻自动边界快照；
00:05 daily boundary 与后续四小时边界；
trade_preparation 合法；
ops_display 不合法；
真实交易关闭仍可计算；
新开仓周期；
未调仓但价格变化周期；
第二周期只计算新增变化；
无持仓；
无订单周期；
USDS-M 与 COIN-M 分离；
缺快照不可计算且不访问 Binance；
重复补算不重复建记录；
并发点击幂等；
一键补齐全部缺失可计算周期。
```

### 19.5 受控运维测试

至少覆盖：

```text
账户刷新只生成 ops_display；
订单状态补查要求明确 attempt；
不能输入任意 client_order_id；
补查不会重新提交订单；
成交补同步只调用 FillSync service；
页面不能直接写 TradeFill；
人工锁收尾只调用 ActiveLockService；
证据不足时锁保持；
所有动作要求权限、二次确认、reason 和审计；
使用 fake BinanceGateway。
```

### 19.6 DeepSeekGateway 测试

至少覆盖：

```text
只存在 DeepSeekReviewGateway.generate_review_completion 受限语义操作；
未知 profile code 被阻断；
调用方不能覆盖 model、base URL 或 API key；
max_output_tokens 超过 profile 上限时在发送前阻断；
结构化输出；
发送前技术失败有限重试；
发送后 timeout 不重试；
unknown_after_send 不重试；
限频、冷却和熔断；
token usage；
敏感信息脱敏；
Fake Gateway 不访问真实 DeepSeek。
```

### 19.7 AIReview 测试

至少覆盖 `ai_review.md` 的完整清单，并重点覆盖：

```text
五种 review_mode；
范围冻结；
空范围 blocked；
人工问题必填；
只读取已落库事实；
Package 脱敏；
Package 过大 blocked；
prompt 版本和 hash；
只传 model_profile_code；
Gateway 结果显式映射；
发送后 unknown 不重试；
结构解析失败不创建 completed Report；
同一 Request 最多一个 completed Report；
Suggestion 不自动执行；
失败不影响交易主链路；
不访问 Binance；
不直接发送 Hermes；
使用 fake DeepSeekGateway。
```

### 19.8 端到端安全测试

至少验证：

```text
用户登录并查看完整 run；
账户展示刷新不污染 trade_preparation；
真实交易硬权限关闭时后台无法最终开启交易；
绩效一键补算不会触发 Binance；
AIReview 请求不会进入 PipelineOrchestrator；
AIReview 建议不会改变策略或运行开关；
任何后台入口都不能重新提交订单；
后台、绩效或模型任务积压不阻塞交易关键队列。
```

---

## 20. 阶段验收命令

后端至少等价执行：

```text
python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py migrate
pytest tests/ops_console/
pytest tests/performance_metrics/
pytest tests/deepseek_gateway/
pytest tests/ai_review/
pytest tests/integration/
pytest
```

如果使用 `uv`：

```text
uv run python manage.py check
uv run python manage.py makemigrations --check --dry-run
uv run python manage.py migrate
uv run pytest
```

前端至少等价执行：

```text
npm ci
npm run lint
npm run typecheck
npm run test
npm run build
```

P0 使用 npm 和 `package-lock.json`。同一前端工程只保留这一套锁文件和正式命令，不同时提交 pnpm、Yarn 或其他重复锁文件。

所有外部服务测试必须使用 fake BinanceGateway、fake DeepSeekGateway 和 fake Hermes。

阶段回报必须说明实际执行的命令和结果。

---

## 21. 阶段通过标准

阶段 7 通过必须满足：

```text
OpsConsole 使用 Next.js + shadcn/ui；
前端只通过 Django API；
正式后台不依赖 Django Admin；
所有页面要求登录；
权限由后端强制执行；
危险操作具备二次确认、reason、AuditRecord 和必要 AlertEvent；
Dashboard、Runs、Orders、Account、Performance、RuntimeGuard、Alerts、Real Trading、AI Review、Ops Actions 和 Audit Log 可用；
账户展示只使用 ops_display；
真实交易开关不能突破 .env；
后台不能热切 active market domain；
后台任何入口都不能重新提交订单；
订单补查、成交补同步和锁收尾只调用所属业务 service；
PerformanceMetrics 一键补齐所有缺失且可计算周期；
重复补算不重复生成有效记录；
PerformanceMetrics 只使用相邻 trade_preparation 快照；
PerformanceMetrics 不访问 Binance、不进入主编排；
DeepSeekGateway 是唯一 DeepSeek 访问边界；
DeepSeekReviewGateway 只向 AIReview 提供一次离线复盘生成操作，不提供通用聊天或任意请求能力；
DeepSeekGatewayResult 不建立独立业务表；
AIReview 范围冻结、数据包脱敏且可追溯；
AIReview 只传 model_profile_code；
AIReview unknown 不自动重试；
AIReview 报告、发现和建议只供人工使用；
AIReview 不修改实时交易系统；
离线任务与交易关键任务隔离；
所有业务时间使用 UTC；
所有 API、日志、审计、数据包和事件不泄露密钥；
测试不访问真实 Binance、DeepSeek 或 Hermes。
```

---

## 22. 阶段失败标准

出现以下任一情况，本阶段不得通过：

```text
改用 Django Admin 作为正式后台；
前端直接访问数据库、Redis 或 Gateway；
前端复制后端交易状态机或绩效算法；
API 只依赖前端隐藏按钮做权限；
认证 token 保存到 localStorage；
后台写 .env、管理 API key 或热切 active market domain；
后台真实交易开关突破硬权限；
后台直接修改订单、成交、编排、巡检事实或锁；
任何人工入口重新提交订单；
账户刷新生成 trade_preparation；
PerformanceMetrics 使用 ops_display 或 latest 快照兜底；
PerformanceMetrics 请求 Binance；
PerformanceMetrics 自动加入四小时编排或 Beat；
周期收益使用订单 realized PnL 替代；
DeepSeekGateway 接受完整 model profile 或任意模型名；
DeepSeek 请求发送后自动重试；
为 DeepSeekGatewayResult 建立无业务价值的独立流水表；
AIReviewPackage 包含密钥、认证信息或未脱敏大响应；
AIReview 自动修改策略、风控、执行、运行开关或订单；
AIReview 建议自动执行；
AIReview 进入实时交易主链路；
离线任务占用交易关键任务资源；
测试访问真实外部服务。
```

---

## 23. 交付回报要求

阶段 7 编码完成后，回报必须说明：

```text
本阶段实现了什么；
新增和修改了哪些文件；
前端技术栈和构建结果；
主要 API 与页面；
认证、权限和二次确认方式；
是否写库；
是否访问 Redis；
是否访问 Binance；
是否发送 Hermes；
是否调用大模型；
是否涉及交易执行；
是否涉及真实交易；
是否涉及 FeatureLayer；
是否涉及 AtomicSignal / DomainSignal / MarketRegime；
是否涉及 StrategyRouting / StrategySignal / StrategyAnalysisRelease；
是否涉及 DecisionSnapshot；
是否涉及 Binance Account Sync；
是否涉及 PriceSnapshot；
是否涉及 OrderPlan / CandidateOrderIntent；
是否涉及 RiskCheck / ApprovedOrderIntent；
是否涉及 ExecutionPreparation / Execution；
是否涉及 OrderStatusSync / FillSync；
是否涉及 PerformanceMetrics / AIReview；
是否写 AlertEvent；
是否创建 NotificationDeliveryAttempt / NotificationSuppression；
受控人工操作范围；
订单提交是否绝不重试；
DeepSeek unknown 如何处理；
dry-run / confirm-write 行为；
异常处理方式；
测试命令和结果；
本阶段明确不负责什么；
是否违反 project_invariants.md。
```

---

## 24. 本阶段明确不负责

```text
复杂 UI 动效或完整移动端适配；
复杂报表设计器；
通用数据库管理后台；
策略、特征和原子信号在线编辑器；
后台任意流程编排器；
自动策略上线；
自动参数优化；
自动回测；
模拟交易运行模式；
自动交易修复；
自动订单重提；
自动撤单或补单；
自动释放 ActiveLock；
AIReview 自动定时运行；
多模型投票；
多 provider 路由；
RAG、向量数据库或长期知识库；
大模型实时交易；
大模型自动修改策略、代码或配置；
大模型直接提交 Git 或调用外部工具。
```

---

## 25. 路线图完成条件

本阶段是当前实施路线图的最后一个计划阶段。

阶段 0 至阶段 7 全部验收通过后，系统才具备：

```text
可信市场事实；
版本化策略分析链路；
账户与价格事实；
订单计划、风控和执行准备；
订单提交、状态与成交闭环；
统一编排、通知和只读巡检；
后台运维、绩效补算和离线 AI 复盘。
```

路线图完成不等于可以直接开启真实交易。

真实交易开启前仍必须按测试与安全架构完成：

```text
完整自动化测试；
fake 外部服务验收；
配置与密钥检查；
真实交易默认关闭验证；
订单提交绝不重试验证；
预生产隔离演练；
人工批准。
```
