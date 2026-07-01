# OpsConsole 需求

## 1. 模块定位

OpsConsole 是系统的运维控制台与复盘工作台。

本模块面向系统维护、交易链路排查、账户展示、异常处理、收益查看和离线复盘。

核心定位：

```text
看系统；
看账户；
看一轮编排；
看订单；
看异常；
看收益；
导出复盘数据；
提供受控人工入口。
```

OpsConsole 可以随着项目发展承载更多后台功能，但当前需求只定义自动交易闭环已经需要的运维与复盘能力。

OpsConsole 不是：

```text
Django Admin；
数据库后台；
交易执行器；
交易所终端；
策略实时决策模块；
自动修复系统；
大模型交易入口。
```

## 2. 核心原则

```text
只通过后端 API 访问系统能力；
所有人工操作必须调用对应业务 service；
前端不得直接访问数据库；
前端不得直接调用 Binance Gateway；
前端不得直接变更业务表；
不绕过 PipelineOrchestrator；
不绕过 OrderPlan；
不绕过 RiskCheck；
不绕过 ExecutionPreparation；
不绕过 Execution；
不重试订单提交；
不自动修复交易事实；
不自动释放 ActiveLock；
不把复盘结论写回实时交易链路；
所有核心业务时间统一展示 UTC。
```

OpsConsole 的核心价值是让人能看清系统发生了什么，并通过受控入口处理需要人工处理的问题。

## 3. 当前范围

当前范围包含：

```text
Dashboard 首页；
OrchestrationRun 列表页；
OrchestrationRun 详情页；
Order 订单详情页；
Account Overview 账户总览页；
Strategy Analysis Components 策略分析组件管理页；
Strategy Release 策略版本包管理页；
Review Dataset 复盘数据导出页；
RuntimeGuardIssue 巡检问题页；
AlertEvent 告警记录页；
真实交易控制页；
Ops Actions 受控人工操作入口。
```

当前范围不包含：

```text
在线编辑算法公式；
在线创建没有文档和代码依据的新策略定义；
在线修改 calculator 代码；
任意流程编排器；
复杂报表系统；
自动策略优化；
自动参数调优；
自动交易修复；
系统内自动大模型复盘结论；
移动端完整适配；
公开用户系统；
多租户后台。
```

策略分析组件管理页允许查看和选择已经登记入库的定义、版本和依赖关系，形成当前策略分析配置工作区；它不是算法代码编辑器，也不是在线公式编辑器。

Strategy Release 策略版本包管理页从当前策略分析配置工作区生成完整版本包快照，冻结、验证、批准和启用完整版本包；它不是几百个组件混合下拉选择器。

## 4. 负责事项

OpsConsole 负责：

```text
展示系统运行状态；
展示自动编排列表和详情；
展示交易链路对象；
展示账户总览；
展示策略分析版本包；
展示策略分析各层级定义、版本和依赖关系；
管理策略分析当前配置工作区；
从当前配置工作区生成 StrategyAnalysisRelease draft；
执行 StrategyAnalysisRelease 依赖闭包预校验；
冻结 StrategyAnalysisRelease；
登记 StrategyAnalysisRelease 验证证据；
批准、拒绝、失效和启用 StrategyAnalysisRelease；
展示复盘数据导出入口与导出历史；
展示订单、状态和成交详情；
展示 RuntimeGuardIssue；
展示 AlertEvent；
触发允许的后台展示账户刷新；
触发允许的订单状态受控补查；
触发允许的成交受控补同步；
触发允许的 ActiveLock 人工收尾入口；
标记 RuntimeGuardIssue 的人工处理状态；
导出 ReviewDataset 复盘数据；
记录人工操作审计；
执行登录、权限、二次确认和 API 安全校验。
```

## 5. 不负责事项

OpsConsole 不负责：

```text
采集行情；
编辑算法代码；
在线修改 calculator；
在线创建特征、原子、领域、市场环境、路由、策略或目标仓位算法定义；
生成特征、原子信号或策略信号；
生成 DecisionSnapshot；
生成 BinanceSyncRun 的 trade_preparation 批次；
生成 PriceSnapshot；
生成 OrderPlan 或 CandidateOrderIntent；
执行 RiskCheck；
生成 ApprovedOrderIntent；
执行 ExecutionPreparation；
提交订单；
撤单；
重试订单提交；
查询 Binance 的通用接口；
直接写 OrderSubmissionAttempt；
直接写 OrderStatusSyncRecord；
直接写 FillSyncResult 或 TradeFill；
直接写 OrderPlanActiveLock；
直接变更 OrchestrationRun 状态；
直接变更 RuntimeGuard 原始巡检事实；
生成实时交易建议；
调用大模型参与实时交易。
```

## 6. 技术与访问边界

OpsConsole 是独立 Web Console。

正式后台不以 Django Admin 作为主产品后台。Django Admin 如存在，只能作为开发便利或内部临时查看工具，不属于本模块正式交互入口。

正式前端技术方向：

```text
Next.js；
shadcn/ui；
图表使用 Recharts 或 ECharts；
后端继续使用 Django、现有 application service 和受控 API。
```

OpsConsole 前端与 Django 后端保持独立工程边界。前端只通过受控 API 读取数据和提交人工操作，不把 Django Templates 或 Django Admin 作为正式产品后台。

前端通过后端 API 使用系统能力：

```text
OpsConsole UI
→ Django API
→ 对应 application service
→ 对应业务对象
```

禁止路径：

```text
OpsConsole UI → MySQL；
OpsConsole UI → Redis；
OpsConsole UI → Binance Gateway；
OpsConsole UI → Binance API；
OpsConsole UI → 直接写业务表；
OpsConsole UI → 直接改锁；
OpsConsole UI → 直接提交订单。
```

具体 Next.js、shadcn/ui 与图表依赖版本由实施阶段写入前端依赖清单并由锁文件固定；不得在不修改需求或架构决策的情况下改用另一套正式前端框架。

## 7. 页面结构

当前导航至少包含：

```text
Dashboard
Runs
Orders
Account Overview
Strategy Components
Strategy Release
Review Dataset
Runtime Guard
Alerts
Real Trading
Ops Actions
Audit Log
```

页面可以合并实现，但必须保留对应业务入口和权限边界。

例如账户、订单和周期事实图表可以作为 Dashboard 图表与 Run 详情页的一部分；复盘数据统一通过 `Review Dataset` 入口导出。

## 8. Dashboard 首页

Dashboard 用于快速判断系统是否正常。

至少展示：

```text
最近 N 个 UTC 4 小时周期浮动收益曲线；
累计周期浮动收益曲线；
最近 OrchestrationRun 状态；
最近是否产生订单；
最近是否出现 unknown；
当前是否存在 active lock；
当前是否存在 open RuntimeGuardIssue；
最近 AlertEvent；
最近 trade_preparation 账户同步时间；
最近 ops_display 账户展示同步时间；
最近 ReviewDataset 导出状态；
当前运行权限摘要；
真实交易运行开关状态摘要。
```

复盘展示规则：

```text
OpsConsole 不在页面内计算策略是否正确；
OpsConsole 不在页面内计算执行质量结论；
订单 realized_pnl、手续费和净收益只作为订单详情或导出字段；
周期级复盘数据通过 ReviewDataset 导出，由本地人工、脚本或 Codex skill 分析。
```

Dashboard 不得用订单已实现收益替代复盘结论。

## 9. OrchestrationRun 列表页

Runs 列表页用于查看最近自动与人工诊断编排。

列表至少展示：

```text
orchestration_run_id；
scheduled_for_utc；
cycle_kind；
trigger_mode；
trigger_source；
status；
final_outcome；
reason_code；
current_step_code；
last_completed_step_code；
needs_manual_attention；
是否产生 OrderPlan；
是否产生订单提交；
是否完成订单状态查询；
是否完成成交同步；
是否存在 ReviewDatasetRecord；
是否存在 open RuntimeGuardIssue；
trace_id；
started_at_utc；
finished_at_utc。
```

筛选至少支持：

```text
最近 20 / 50 / 100 条；
automatic；
manual_diagnostic；
completed；
completed_no_action；
blocked；
unknown；
failed；
stale_interrupted；
needs_manual_attention；
有订单；
无订单；
已生成复盘数据记录；
复盘数据记录缺失；
存在 RuntimeGuardIssue。
```

Runs 列表页只展示和导航，不创建自动交易 run，不重跑自动 run。

ReviewDatasetRecord 缺失只表示后台尚未为该周期生成复盘数据索引，不等于自动交易主链路异常，也不由 RuntimeGuard 巡检。

## 10. OrchestrationRun 详情页

Run 详情页用于回答：

```text
这一轮为什么继续？
这一轮为什么停止？
这一轮为什么没有订单？
这一轮为什么 blocked？
这一轮为什么 unknown？
这一轮订单走到了哪里？
这一轮有哪些复盘数据可以导出？
这一轮是否需要人工处理？
```

详情页必须基于：

```text
OrchestrationRun；
OrchestrationStepRun；
OrchestrationBusinessObjectLink；
业务对象自己的真实外键；
AlertEvent；
RuntimeGuardIssue。
```

详情页至少展示：

```text
Run 基本信息；
冻结的 registry_version；
每个步骤的 StepRun；
每个步骤的 normalized_status；
每个步骤的 flow_action；
每个步骤的 reason_code；
每个步骤的 primary / output / related / audit 对象引用；
DataQuality 摘要；
MarketSnapshot 摘要；
FeatureSet 摘要；
AtomicSignalSet 摘要；
DomainSignalSet 摘要；
MarketRegimeSnapshot 摘要；
StrategyRouteDecision 摘要；
StrategyAnalysisRelease 身份与 hash；
StrategySignal 摘要；
StrategySignalQualityResult 摘要；
DecisionSnapshot 摘要；
BinanceSyncRun 摘要；
PriceSnapshot 摘要；
OrderPlan / CandidateOrderIntent；
RiskCheckResult / ApprovedOrderIntent；
ExecutionPreparationResult / PreparedOrderIntent；
OrderSubmissionAttempt；
OrderStatusSyncRecord；
FillSyncResult / OrderFillSummary；
TradeFill 摘要；
ReviewDatasetRecord；
AlertEvent；
RuntimeGuardIssue。
```

如果链路缺失，必须明确显示：

```text
缺失阶段；
缺失对象类型；
缺失对象 ID；
缺失原因；
是否需要人工处理；
建议查看的 RuntimeGuardIssue 或 AlertEvent。
```

不得静默隐藏缺失链路。

## 11. 链路追踪规则

OpsConsole 查询一轮详情优先使用 PipelineOrchestrator 提供的查询 service：

```text
get_orchestration_detail(orchestration_run_id)
```

业务对象反查 run 时使用：

```text
find_orchestration_runs(object_type, object_id)
```

OpsConsole 可以沿业务外键展开详情，但不得用展示页自己拼接逻辑替代业务 service。

禁止：

```text
用时间范围猜测某个订单属于哪一轮；
用数据库最新对象猜测当前链路；
用 trace_id 单独替代真实业务外键；
用 OrchestrationBusinessObjectLink 作为交易模块正式输入；
遇到缺失链路时自行补写关联。
```

## 12. Order 订单详情页

Order 页面围绕 `OrderSubmissionAttempt` 展开。

订单详情至少展示：

```text
OrderSubmissionAttempt；
PreparedOrderIntent；
ApprovedOrderIntent；
RiskCheckResult；
CandidateOrderIntent；
OrderPlan；
client_order_id；
exchange_order_id；
symbol；
side；
position_side；
market_type；
account_domain；
quantity；
order_type；
submit_status；
error_code；
error_message；
submit_response 摘要；
OrderStatusSyncRecord 列表；
终态判断结果；
FillSyncResult；
OrderFillSummary；
TradeFill 摘要；
realized_pnl；
commission；
net_realized_pnl；
关联 OrchestrationRun；
关联 ActiveLock；
关联 AlertEvent；
关联 RuntimeGuardIssue。
```

订单详情页的收益口径是订单级收益，不是周期收益。

订单详情页可以展示：

```text
realized_pnl；
commission；
net_realized_pnl。
```

但不得把它们称为周期浮动收益。

## 13. Account Overview 账户总览页

Account Overview 是后台展示页面。

它使用 Binance Account Sync 的 `ops_display` 入口：

```text
refresh_for_ops_console(
    operator_id,
    trace_id,
    trigger_source="ui_one_click",
)
```

页面至少展示当前 active account domain：

```text
sync_run_id；
sync_purpose = ops_display；
status；
market_type；
account_domain；
as_of_utc；
expires_at_utc；
is_stale；
账户摘要；
余额摘要；
持仓摘要；
交易规则摘要；
最近错误；
trace_id。
```

规则：

```text
只展示当前 active account domain；
不提供同步全部账户域能力；
不得让前端传入任意 market_type；
不得生成 trade_preparation 批次；
不得供 OrderPlan、RiskCheck 或 ExecutionPreparation 消费；
不得参与 ReviewDataset 的自动账户边界事实；
不得作为交易主流程 gate；
不得直接调用 Binance Gateway。
```

账户展示刷新失败只影响后台展示，不改变正式交易编排事实。

## 14. Review Dataset 复盘数据导出

OpsConsole 通过 ReviewDataset service 预览、创建和下载复盘数据集。

至少展示：

```text
export_id；
period_start_utc；
period_end_utc；
subject_orchestration_run_id；
start_boundary_orchestration_run_id；
end_boundary_orchestration_run_id；
cleanup_orchestration_run_id；
market_type；
account_domain；
symbol；
dataset_schema_version；
record_count；
file_count；
export_format；
content_hash；
build_status；
reason_code；
trace_id。
```

展示规则：

```text
只展示数据集范围、对象数量、导出状态和下载入口；
可以展示订单 realized_pnl、手续费和账户字段作为导出摘要；
不得把这些字段解释为策略成败结论；
build_status 非 completed 时必须显示原因；
数据缺失不得用最新对象或订单收益兜底。
```

OpsConsole 不自己拼接数据库查询生成数据集。

OpsConsole 必须提供 ReviewDataset 导出入口。

导出入口必须调用 ReviewDataset service。

页面至少支持：

```text
按 UTC 时间范围预览可导出周期数量；
按最近 N 个周期预览导出范围；
选择是否只导出有订单周期；
选择是否只导出 blocked / unknown / failed 周期；
创建 ReviewDatasetExport；
下载导出包；
查看导出 manifest 摘要；
查看最近一次导出操作审计。
```

规则：

```text
导出只能读取已落库事实；
缺少自动边界账户快照的周期只能显示缺失原因；
ReviewDataset 缺失不等于自动交易主链路异常；
RuntimeGuard 不巡检 ReviewDataset 自身状态；
导出文件不得包含密钥、token、签名或完整认证 header。
```

## 15. RuntimeGuardIssue 页面

Runtime Guard 页面展示 RuntimeGuard 发现的问题。

至少展示：

```text
issue_id；
issue_type；
severity；
status；
needs_manual_attention；
related_object_type；
related_object_id；
first_seen_at_utc；
last_seen_at_utc；
last_alerted_at_utc；
evidence 摘要；
reason_code；
trace_id；
关联 OrchestrationRun；
关联 AlertEvent。
```

支持的人工状态操作：

```text
acknowledge；
resolve；
ignore。
```

规则：

```text
只能调用 RuntimeGuard 提供的 issue 状态管理 service；
不得借由 RuntimeGuard 页面补跑业务；
不得借由 RuntimeGuard 页面变更 OrchestrationRun；
不得借由 RuntimeGuard 页面变更订单、成交、账户或锁；
ignore 必须二次确认并记录理由。
```

RuntimeGuardIssue 不等于原业务对象状态。页面必须区分：

```text
巡检发现的问题；
业务对象自己的状态。
```

## 16. AlertEvent 页面

Alert 页面展示系统事件和告警。

至少支持：

```text
按时间筛选；
按 severity 筛选；
按 source_module 筛选；
按 event_type 筛选；
按 trace_id 筛选；
按 related_object 筛选；
只看交易相关事件；
只看 RuntimeGuard 巡检事件；
只看投递失败事件。
```

页面必须区分：

```text
业务模块实时 AlertEvent；
编排级 AlertEvent；
RuntimeGuard 巡检 AlertEvent；
通知投递状态事件。
```

RuntimeGuard 发现的问题必须明确展示为巡检发现，不得伪装成原业务模块刚刚实时失败。

AlertEvent 只用于展示、通知和审计，不得被页面反向用作交易触发器。

### 16.1 真实交易控制页

真实交易控制页只负责展示交易市场配置，并管理 MySQL 中的真实交易运行开关。它不提供其他业务模块开关。

页面至少展示：

```text
.env 中的真实交易硬权限脱敏结果；
.env 中当前交易 market_type 和 account_domain；
MySQL 中的真实交易运行开关；
当前最终真实交易权限；
最近真实交易运行开关变更审计。
```

页面只允许通过 ProjectFoundation 提供的运行配置 service 执行：

```text
关闭真实交易运行开关；
开启真实交易运行开关。
```

运行开关只有在 `.env` 真实交易硬权限允许时才能使最终权限为允许。编排衔接器在进入 OrderPlan 前读取并判断一次；已经通过检查的本轮流程不因页面随后修改开关而重新判断，变更只影响下一次准入检查。

页面不得：

```text
写 .env；
管理 API key；
管理 API secret；
热切换 active market domain；
突破 `.env` 真实交易硬权限；
直接写运行配置表；
绕过二次确认；
绕过后端权限；
在硬配置禁止时打开真实交易。
```

开启真实交易运行开关必须具备高权限并二次确认。开启和关闭都必须记录操作人、原因、变更前后值、UTC 时间、审计记录和 AlertEvent。

## 17. ReviewDataset 导出入口

ReviewDataset 页面用于创建复盘数据导出、查看导出状态、下载导出包和查看导出审计。

支持选择：

```text
最近 20 个自动 run；
最近 50 个自动 run；
最近 100 个自动 run；
自定义 UTC 时间范围；
只导出有订单 run；
只导出 blocked / unknown / failed run。
```

ReviewDataset 页面至少支持：

```text
预览导出范围；
创建 ReviewDatasetExport；
查看 ReviewDatasetExport 状态；
查看 manifest 摘要；
下载导出包；
查看导出审计记录。
```

导出数据包内容至少包含：

```text
OrchestrationRun 摘要；
StepRun 摘要；
市场快照摘要；
特征摘要；
原子信号摘要；
领域信号摘要；
市场环境摘要；
策略路由摘要；
StrategyAnalysisRelease 身份与 hash；
策略信号摘要；
策略信号质量摘要；
DecisionSnapshot；
BinanceSyncRun 摘要；
PriceSnapshot；
OrderPlan；
RiskCheckResult；
ExecutionPreparationResult；
OrderSubmissionAttempt；
OrderStatusSyncRecord；
FillSyncResult；
OrderFillSummary；
ReviewDatasetRecord；
AlertEvent；
RuntimeGuardIssue；
blocked / unknown / failed 原因。
```

数据包下载格式至少支持一种结构化格式：

```text
JSON；
JSONL；
CSV。
```

ReviewDataset 页面和数据包下载不得包含：

```text
API key；
secret；
signature；
认证 header；
认证 token；
数据库密码；
环境变量敏感信息；
未脱敏外部响应；
不可控大体积原始 payload。
```

ReviewDataset 只提供事实数据。复盘结论由本地人工、脚本或 Codex skill 离线生成，不得自动影响实时策略、风控或执行。

## 18. Strategy Analysis 组件管理与 Strategy Release 策略版本包管理

OpsConsole 必须把策略分析后台拆成两个层次：

```text
Strategy Components = 管理各层级已经登记入库的定义、版本、依赖关系和当前配置工作区；
Strategy Release = 从当前配置工作区生成完整发布包快照，并完成冻结、验证、批准和启用。
```

### 18.1 Strategy Components 组件管理

Strategy Components 是策略分析组件管理入口，不是把所有层级堆在一起的单一大表单页面。

Strategy Components 必须按策略分析链路层级拆分为多个独立管理页面。入口页只展示当前配置工作区摘要、各层级入口和从当前配置生成 draft 的操作；具体定义版本选择、纳入状态和依赖关系展示必须进入对应层级页面完成。

至少包含以下入口：

```text
Feature 管理；
AtomicSignal 管理；
DomainSignal 管理；
MarketRegime 管理；
StrategyRouting 管理；
StrategySignal 管理；
StrategySignalQuality 管理；
DecisionSnapshot 管理。
```

每个层级管理页面至少展示：

```text
该层级定义数量；
每个定义的代码、名称、用途和状态；
每个定义有哪些版本；
每个版本的算法名称、算法版本、定义指纹、参数指纹、依赖指纹、文档路径和是否可被正式发布包选择；
当前配置工作区采用的版本；
除 Feature 外，当前配置工作区是否纳入该定义版本；
该版本依赖哪些上游组件；
该版本被哪些下游组件消费；
不可选原因。
```

管理规则：

```text
Feature 与 AtomicSignal 是硬依赖：原子声明需要的特征缺失时，该原子不能运行；
Feature 不提供独立“纳入当前组合”开关，是否进入发布包由已纳入 AtomicSignal 的特征依赖自动反推；
AtomicSignal 的必需 Feature 依赖不应在后台随意编辑，改变依赖必须形成新的 AtomicSignalDefinition 版本；
从 AtomicSignal 开始，各层级定义版本必须支持当前配置工作区纳入 / 不纳入状态；
DomainSignal 与 AtomicSignal 是可组合依赖：领域必须区分必需原子和可选原子；
领域必需原子缺失时，领域不能作为完整正式领域进入发布包；
领域可选原子缺失时，领域可以运行，但必须在证据完整性、置信度或缺失说明中体现；
领域的原子集合发生计算语义变化时，必须形成新的 DomainSignalDefinition 版本或新的领域依赖配置版本；
已发布版本包引用过的定义、版本和依赖关系不得原地修改。
```

Strategy Components 可以把“当前采用版本”和“是否纳入当前组合”保存为工作区配置，但工作区不是正式运行依据。正式主链路只读取已批准且已启用的 StrategyAnalysisRelease。

Strategy Components 的当前配置工作区选择可以采用行内开关即时保存：Feature 层使用“采用此版本”，AtomicSignal 及以上层级使用“纳入当前组合”。该操作只修改工作区配置并写审计，不触发交易、不生成正式发布包、不影响已启用版本包，因此不应要求管理员在每一行反复填写二次确认。

Strategy Components 不得：

```text
在线编辑算法代码；
在线修改 calculator 公式；
创建没有 requirements、implementation 和测试依据的新算法语义；
把当前工作区直接接入正式主链路；
绕过 StrategyAnalysisRelease 生成正式运行配置。
```

### 18.2 Strategy Release 策略版本包管理

Strategy Release 页面用于管理正式策略分析版本包。

本页面从当前策略分析配置工作区生成 StrategyAnalysisRelease draft，并完成验证、批准和启用流程。它不应把所有组件混在一个下拉框中让管理员逐个选择。

生成 draft 时：

```text
只采纳当前配置工作区中已纳入的 AtomicSignal 及以上层级组件；
FeatureDefinition 由已纳入 AtomicSignal 的特征依赖自动反推；
未纳入当前组合的原子、领域、市场环境、路由规则、策略、质量规则和目标仓位决策不得进入 ReleaseItem；
如果已纳入组件的硬依赖缺失，生成或预校验必须明确提示并阻止冻结。
```

页面至少支持：

```text
查看版本包列表；
查看当前已启用版本包；
查看版本包详情；
查看版本包 ReleaseItem 清单；
从当前配置工作区生成 draft 版本包；
从历史版本包复制生成新的 draft；
编辑 draft 的展示名称和说明；
查看 draft 的依赖树；
查看 draft 的缺失组件、不可用组件和指纹不一致组件；
重新从当前配置工作区生成 draft ReleaseItem；
执行依赖闭包预校验；
冻结 draft 并进入 validating；
登记验证证据；
批准 validating 版本包；
拒绝 validating 版本包；
失效 approved 或 active 版本包；
启用 approved 版本包；
回滚到历史 approved 且未失效的版本包；
查看版本包相关 AlertEvent 与 AuditRecord。
```

如保留人工增删或替换 ReleaseItem 的高级入口，必须满足：

```text
只对 draft 开放；
按层级和组件类型分组；
展示上下游依赖影响；
写审计记录；
不得作为主要交互方式；
不得要求每个自动收集组件都单独填写原因；
不得绕过依赖闭包预校验。
```

draft 编辑规则：

```text
只有 draft 可以重新生成或高级修正 ReleaseItem；
validating、approved、active、invalidated 均不得原地修改 ReleaseItem；
修改历史版本包必须先复制为新 draft；
复制历史版本包后，新 draft 必须重新冻结、验证、批准和启用；
页面不得提供直接修改 release_hash 的入口。
```

依赖闭包预校验至少展示：

```text
缺失的上游组件；
Feature 与 AtomicSignal 硬依赖缺口；
DomainSignal 必需原子缺口；
DomainSignal 可选原子缺失说明；
重复归属的原子信号；
缺失的六个正式领域；
MarketRegime 需要但未选择的领域；
RouteRule 指向但未选择的 StrategyDefinition；
StrategyDefinition 需要但未选择的领域；
缺失的唯一 StrategySignalQualityRuleSet；
缺失的唯一 DecisionPolicyDefinition；
calculator 不可解析的组件；
指纹与真实定义不一致的组件。
```

冻结、批准和启用规则：

```text
冻结必须二次确认；
冻结后计算 release_hash；
验证证据必须绑定 release_hash；
批准必须引用验证证据；
批准不会自动启用；
启用必须二次确认；
启用只影响新开始的编排；
回滚只能整包回滚，不允许局部回滚；
失效 active 版本包后不得自动切换到其他版本包。
```

页面禁止：

```text
编辑算法代码；
编辑 calculator；
绕过 StrategyAnalysisRelease service；
把当前工作区直接标记为正式运行；
把回测成功自动变成批准；
把批准自动变成启用；
绕过验证证据；
绕过二次确认；
绕过权限；
直接写 Release、ReleaseItem、Approval、Activation 或 ValidationEvidence 表；
通过 management command 替代后台发布流程；
让未批准版本包进入正式主链路。
```

Strategy Release 页面不属于实时交易执行入口。它决定后续新编排使用哪套策略分析定义，但不生成 FeatureSet、AtomicSignalSet、DomainSignalSet、StrategySignal、DecisionSnapshot、OrderPlan 或订单。

## 19. Ops Actions 受控人工入口

Ops Actions 页面集中展示允许的人工操作。

当前允许的操作包括：

```text
刷新 Account Overview；
对明确 OrderSubmissionAttempt 执行订单状态受控补查；
对明确 OrderSubmissionAttempt 执行成交受控补同步；
对明确 OrderPlanActiveLock 执行人工收尾；
标记 RuntimeGuardIssue acknowledged；
标记 RuntimeGuardIssue resolved；
标记 RuntimeGuardIssue ignored；
预览 ReviewDataset 导出范围；
创建 ReviewDatasetExport；
下载 ReviewDataset 导出包。
```

所有操作必须调用对应模块后端 service。

Ops Actions 不得提供：

```text
订单重新提交；
自动撤单；
自动补单；
跳过 RiskCheck；
跳过 ExecutionPreparation；
直接创建 ApprovedOrderIntent；
直接创建 PreparedOrderIntent；
直接释放 ActiveLock；
直接把 unknown 标成 success；
直接变更 OrchestrationRun 终态；
直接改 BinanceSyncRun 的 sync_purpose。
```

## 20. 订单状态受控补查入口

订单状态补查必须调用 OrderStatusSync 的受控恢复或对账入口。

要求：

```text
必须传入明确 order_submission_attempt_id；
必须显示 attempt 当前状态；
必须显示 client_order_id；
必须显示 exchange_order_id（如有）；
必须显示 market_type、account_domain 和 symbol；
必须要求二次确认；
必须记录 operator_id、reason 和 trace_id；
必须保存补查结果；
必须遵守 OrderStatusSync 的幂等规则和恢复窗口规则。
```

禁止：

```text
按最近一单补查；
按 symbol 自动选择订单；
用页面输入任意 client_order_id 查询；
补查后自动提交新订单；
补查后直接释放锁；
补查后直接改 OrderSubmissionAttempt 状态。
```

订单提交在任何后台入口都不得重试。

## 21. 成交受控补同步入口

成交补同步必须调用 FillSync 的受控恢复或人工对账入口。

要求：

```text
必须传入明确 order_submission_attempt_id；
必须存在可追溯的订单状态同步上下文；
必须显示终态证据；
必须要求二次确认；
必须记录 operator_id、reason 和 trace_id；
必须复用 FillSync 幂等逻辑；
必须由 FillSync 自己保存 FillSyncResult、TradeFill 和 OrderFillSummary。
```

禁止：

```text
页面直接录入 TradeFill；
页面直接重算 OrderFillSummary；
页面直接变更成交同步状态；
页面直接更新持仓；
页面直接释放 ActiveLock。
```

ActiveLock 是否可以收尾，必须由 ActiveLockService 根据正式事实判断。

## 22. ActiveLock 人工收尾入口

ActiveLock 人工收尾必须调用 OrderPlan 所属的 ActiveLockService。

页面至少展示：

```text
active_lock_id；
exchange；
market_type；
account_domain；
symbol；
lock_status；
locked_by_order_plan_id；
locked_by_order_submission_attempt_id；
关联 OrderStatusSyncRecord；
关联 FillSyncResult；
阻断原因；
已存在的 RuntimeGuardIssue；
最近 AlertEvent。
```

人工收尾要求：

```text
必须二次确认；
必须记录 operator_id；
必须记录 reason；
必须记录证据；
必须记录 trace_id；
必须写 AlertEvent；
必须由 ActiveLockService 判断目标状态。
```

页面不得直接把锁状态写成 released、failed 或其他状态。

## 23. 危险操作二次确认

以下操作必须二次确认：

```text
刷新 Account Overview；
订单状态受控补查；
成交受控补同步；
ActiveLock 人工收尾；
RuntimeGuardIssue ignore；
ReviewDataset 导出；
ReviewDataset 大范围导出请求。
StrategyAnalysisRelease 冻结；
StrategyAnalysisRelease 批准；
StrategyAnalysisRelease 拒绝；
StrategyAnalysisRelease 失效；
StrategyAnalysisRelease 启用；
StrategyAnalysisRelease 回滚。
```

二次确认必须明确显示：

```text
操作对象；
操作影响；
是否会访问 Binance；
是否会写 MySQL；
是否会访问 Redis；
是否会写 AlertEvent；
是否会影响交易主流程；
是否可能改变锁状态；
是否涉及真实交易；
是否允许撤销。
```

用户确认只代表授权后端 service 执行对应受控操作，不代表允许绕过业务规则。

## 24. 操作审计

所有人工操作必须写审计记录。

审计记录至少包含：

```text
operator_id；
operator_role；
operation_type；
target_object_type；
target_object_id；
before_state 摘要；
after_state 摘要；
reason；
result；
failure_reason；
trace_id；
created_at_utc。
```

审计记录不得被普通页面操作删除。

审计记录不得包含密钥、签名、认证 header 或完整未脱敏外部响应。

## 25. 登录与权限

OpsConsole 不允许匿名访问。

至少区分以下权限：

```text
readonly；
ops_operator；
review_exporter；
strategy_release_viewer；
strategy_release_editor；
strategy_release_approver；
strategy_release_activator；
admin。
```

权限规则：

```text
readonly 只能查看；
ops_operator 可以执行受控运维操作；
review_exporter 可以创建和查看离线复盘数据导出请求、下载复盘数据包；
strategy_release_viewer 可以查看策略版本包和验证证据；
strategy_release_editor 可以创建和编辑 draft 版本包；
strategy_release_approver 可以批准、拒绝或失效版本包；
strategy_release_activator 可以启用、停用或回滚版本包；
admin 可以管理用户和权限；
查看权限不自动包含操作权限；
复盘权限不自动包含订单补查权限；
运维操作权限不自动包含用户管理权限。
策略版本包编辑权限不自动包含批准权限；
策略版本包批准权限不自动包含启用权限。
```

所有后端 API 都必须执行权限校验，不能只依赖前端隐藏按钮。

## 26. API 安全

OpsConsole API 不得返回：

```text
Binance API key；
Binance secret；
signature；
认证 header；
认证 token；
数据库连接信息；
环境变量敏感信息；
完整外部 request；
完整未脱敏 response；
不可控大体积 JSON。
```

返回外部响应摘要时必须脱敏并限制大小。

危险操作 API 必须要求：

```text
登录用户；
权限；
二次确认 token 或等价确认参数；
reason；
trace_id；
目标对象明确 ID。
```

API 不得允许前端传入任意模型名、表名或 SQL 条件进行通用查询。

## 27. 与 PipelineOrchestrator 的关系

OpsConsole 展示编排事实，但不拥有编排事实。

允许：

```text
查看 OrchestrationRun；
查看 OrchestrationStepRun；
查看 OrchestrationBusinessObjectLink；
查看编排级 AlertEvent；
调用编排详情查询 service；
展示受控恢复入口的可用性。
```

禁止：

```text
直接创建自动 OrchestrationRun；
直接重跑自动 OrchestrationRun；
直接推进步骤；
直接消费 resume_token；
直接变更 Run 或 StepRun 状态；
把人工诊断伪装成自动 run；
绕过 Connector 调用交易步骤。
```

受控编排恢复如需要开放给后台，必须由 PipelineOrchestrator 提供专门 service，并记录操作人、原因、证据和 trace_id。

## 28. 与 Binance Account Sync 的关系

OpsConsole 账户展示只调用 `ops_display` 入口。

规则：

```text
Account Overview 只展示 ops_display 批次；
后台刷新不得生成 trade_preparation 批次；
后台刷新不得覆盖自动账户边界同步批次；
后台刷新不得改变交易 selector；
后台刷新不得满足 RuntimeGuard 对自动账户边界同步新鲜度的要求；
后台刷新不得作为 ReviewDataset 的周期账户边界事实。
```

OpsConsole 不直接调用 Binance Gateway。

## 29. 与订单状态和成交同步的关系

OpsConsole 可以触发受控补查和受控补同步，但只能调用对应模块 service。

规则：

```text
OrderStatusSync 负责订单状态补查和状态记录；
FillSync 负责成交补同步和成交记录；
OpsConsole 只负责展示、确认、授权和审计；
补查或补同步失败时展示失败原因；
补查或补同步 unknown 时展示人工关注状态；
任何路径都不得重试订单提交。
```

## 30. 与 ReviewDataset 的关系

OpsConsole 使用 ReviewDataset service 导出复盘数据。

OpsConsole 不计算复盘结论。

OpsConsole 不在系统内调用大模型生成复盘报告。

ReviewDataset 相关规则：

```text
只读取已落库事实；
只导出复盘数据；
不提交模型参数；
不调用 DeepSeek；
不保存 AI 报告；
不参与实时交易；
不自动变更策略；
不自动变更风控；
不自动变更执行；
不自动暂停或开启真实交易。
```

## 31. 与 RuntimeGuard 的关系

OpsConsole 展示 RuntimeGuardIssue，并提供 issue 状态管理入口。

规则：

```text
RuntimeGuard 发现问题；
OpsConsole 展示问题；
人工通过 RuntimeGuard service 标记问题状态；
业务对象的恢复或收尾进入对应业务模块 service。
```

OpsConsole 不替 RuntimeGuard 巡检。

OpsConsole 不替 RuntimeGuard 创建问题。

OpsConsole 不借 RuntimeGuard 页面修复业务事实。

## 32. 数据库、Redis 与外部服务

```text
读 MySQL：通过后端 service/API 读取。
写 MySQL：只通过对应后端 service 写审计、状态或业务模块允许的对象。
访问 Redis：前端否；后端可按对应模块规则使用短期状态。
访问 Binance：前端否；后端只通过被调用业务 service 间接访问允许接口。
调用 Binance Gateway：前端否；OpsConsole 后端自身不直接调用。
发送 Hermes：否，只写或展示 AlertEvent，由 Notifications 处理投递。
调用大模型：否；当前系统内不做大模型复盘调用。
涉及交易执行：展示和受控运维涉及交易对象，但不提交订单。
允许真实交易：否。
```

## 33. 时间展示

所有业务时间默认展示 UTC，并明确标注 UTC。

不得使用浏览器本地时间参与：

```text
周期判断；
run 查询；
收益归属；
订单追踪；
成交追踪；
巡检判断。
```

如果界面提供本地时间辅助展示，必须只作为人类阅读辅助，不得参与业务筛选的实际边界计算。

## 34. 异常处理

页面异常处理规则：

```text
后端返回权限不足 → 显示无权限，不重试危险操作；
后端返回对象不存在 → 显示对象缺失和 object_id；
后端返回链路缺失 → 显示缺失阶段；
后端返回 unknown → 显示不确定状态，不解释为成功；
后端返回 blocked → 显示阻断原因，不解释为系统异常；
后端返回 failed → 显示脱敏错误信息；
外部服务不可用 → 显示业务 service 返回的脱敏错误；
审计写入失败 → 危险操作不得静默成功。
```

OpsConsole 不得因为页面展示失败而变更业务状态。

## 35. 测试要求

至少覆盖：

```text
1. 未登录不能访问 OpsConsole。
2. readonly 用户不能执行人工操作。
3. ops_operator 可以执行授权范围内的受控操作。
4. review_exporter 可以创建和查看 ReviewDataset 导出但不能补查订单。
5. Dashboard 不把 realized_pnl 当成策略或复盘结论。
6. Dashboard 不自行计算周期收益。
7. Runs 列表展示 OrchestrationRun 状态。
8. Run 详情通过编排详情 service 展示 StepRun 和 ObjectLink。
9. 链路缺失时页面显示缺失阶段。
10. Order 页面展示 OrderSubmissionAttempt、OrderStatusSyncRecord 和 FillSyncResult。
11. Account Overview 调用 ops_display 入口。
12. Account Overview 不生成 trade_preparation 批次。
13. 前端传入 market_type 刷新账户时被后端拒绝。
14. RuntimeGuardIssue 页面能标记 acknowledged。
15. RuntimeGuardIssue ignore 必须二次确认并记录理由。
16. Alert 页面区分业务 AlertEvent 和 RuntimeGuard 巡检 AlertEvent。
17. 订单状态补查必须传入明确 order_submission_attempt_id。
18. 订单状态补查不会重试订单提交。
19. 成交补同步不会直接写 TradeFill。
20. ActiveLock 人工收尾不会由页面直接写锁状态。
21. ReviewDataset 预览导出范围不修改上游业务事实。
22. ReviewDataset 导出需要权限、理由和审计。
23. ReviewDataset 不调用 DeepSeek。
24. ReviewDataset 导出包不包含密钥、token、签名或完整认证 header。
25. 危险操作必须二次确认。
26. 所有人工操作写审计记录。
27. 前端不能直接访问数据库。
28. 前端不能直接调用 Binance Gateway。
29. 所有业务时间以 UTC 查询和展示。
30. Strategy Components 按层级展示定义、版本、当前采用版本和上下游依赖。
31. Strategy Release 可以从当前配置工作区生成 draft，而不是依赖混合下拉框逐个选组件。
32. 已生成版本包不受后续当前配置工作区变更影响。
33. 发布包生成只要求一次发布原因，不要求每个自动纳入组件单独填写原因。
```

## 36. 验收标准

满足以下条件才算通过：

```text
OpsConsole 是独立受控后台；
所有页面通过后端 API 获取数据；
所有人工动作调用对应业务 service；
策略分析组件管理按层级组织，不使用混合组件下拉框作为主要入口；
Strategy Release 从当前配置工作区生成不可变发布包快照；
前端不直接访问数据库、Redis 或 Binance；
后台账户总览只使用 ops_display；
后台账户总览不参与交易和收益计算；
Run 页面以 OrchestrationRun 为中心；
Run 详情可以查清一轮关键业务对象；
Order 页面区分订单级收益和周期收益；
Dashboard 不生成复盘结论；
ReviewDataset 通过后台受控入口导出复盘数据；
RuntimeGuardIssue 与原业务对象状态清晰区分；
AlertEvent 区分业务事件、编排事件和巡检事件；
订单提交在任何后台入口都不重试；
ActiveLock 不由页面直接变更；
系统内不提供大模型复盘页面；
OpsConsole 不调用大模型；
危险操作具备权限、二次确认和审计；
敏感信息不会通过 API、页面、导出或审计泄露。
```

## 37. 最终结论

OpsConsole 的最终定位是：

```text
受控运维控制台 + 交易链路查看台 + 账户展示页 + 复盘数据导出台。
```

一句话：

```text
OpsConsole 帮人看清系统、处理需要人工授权的问题和导出复盘数据，但它不是交易执行器，也不是自动修复器。
```

## 38. StrategyBacktest 后台入口

OpsConsole 提供 StrategyBacktest P0 页面，用于在测试环境查看策略版本包的历史模拟收益。

当前阶段 `/strategy-backtests` 作为 StrategyBacktest 入口页，用于创建 `StrategyBacktestRun` 后台任务和查看最近运行列表；单次回测详情页 `/strategy-backtests/{run_id}` 展示任务状态、结果摘要和周期模拟调仓明细。页面允许刷新；排队或运行中的任务不会因为页面刷新而丢失。

后台入口必须遵守：

```text
只允许非 production 环境运行；
只读取历史 K 线和策略分析结果；
不进入 PriceSnapshot；
不进入 OrderPlan；
不生成 CandidateOrderIntent；
不执行 RiskCheck；
不执行 ExecutionPreparation；
不执行 Execution；
不提交订单；
不查询订单状态；
不写 TradeFill；
不影响 ActiveLock；
不发送 Hermes；
不调用大模型；
不修改 StrategyAnalysisRelease；
不自动批准或启用策略。
```

页面展示重点：

```text
运行状态；
是否仍在排队或运行；
已完成周期 / 总周期；
当前处理 UTC 分析边界；
最近周期状态和原因；
进度更新时间；
UTC 日期范围；
总收益率；
最大回撤；
模拟调仓次数；
手续费；
和 BTC 买入持有对比；
首尾周期摘要；
每个 UTC 4h 周期的调仓前仓位、目标仓位、杠杆倍数、有效仓位、仓位变化、有效仓位变化、模拟成交价、收盘价、周期收益、结束权益和估算爆仓信息。
```

StrategyBacktest P0 页面不要求选择具体 4h 时间点。页面日期按 UTC 解释，并自动转换为当天 `00:00:00+00:00` 的 4h 边界。

StrategyBacktest P0 页面中“无目标仓位时”的默认选项为“维持上一周期仓位”，用于更贴近正式主链路：没有新的目标仓位不等于主动平仓。只有策略明确输出目标仓位为 0 时，回测才模拟平仓。

StrategyBacktest P0 页面允许填写杠杆倍数。该杠杆只用于回测中把目标仓位转换为有效名义敞口，并用于估算是否触发爆仓；不会修改交易所真实杠杆，也不会进入正式订单链路。

StrategyBacktest 的具体收益计算口径以 `docs/requirements/strategy_backtest.md` 为准。
