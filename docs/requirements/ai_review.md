# AIReview 需求

## 1. 模块定位

AIReview 是离线大模型复盘模块。

本模块基于已经落库的编排、策略、账户、价格、订单、成交、收益、告警和巡检事实，生成可发送给大模型的复盘数据包，通过 DeepSeekGateway 调用 DeepSeek，并保存复盘报告、问题发现和人工建议。

核心定位：

```text
离线复盘；
数据包组装；
prompt 版本管理；
DeepSeek 调用编排；
报告保存；
问题发现保存；
人工建议保存；
后台展示与人工评估的数据来源。
```

AIReview 不是：

```text
实时交易决策模块；
自动策略优化器；
自动调参器；
自动交易执行器；
自动修复系统；
后台页面模块；
DeepSeek 底层请求模块。
```

AIReview 的结果只能用于复盘、人工分析和后续人工改进流程，不得进入实时交易链路。

## 2. 核心原则

```text
只读取已经落库的业务事实；
不直接请求 Binance；
不直接请求 DeepSeek API；
调用 DeepSeek 必须通过 DeepSeekGateway；
不重新计算特征、信号、决策或收益；
不生成交易信号；
不生成目标仓位；
不生成订单；
不执行风控；
不提交、撤销或重试订单；
不释放 ActiveLock；
不修改历史交易事实；
不自动修改策略、风控或执行配置；
所有业务时间统一 UTC；
大模型输出必须经过人工理解和审核。
```

大模型结论不等于交易决策，不等于生产变更指令。

## 3. 负责事项

AIReview 负责：

```text
接收 OpsConsole 发起的复盘请求；
校验 review_mode、复盘范围、权限和大小限制；
冻结复盘输入范围；
读取 OrchestrationRun 及相关业务对象；
生成脱敏 AIReviewPackage；
选择 prompt_name、prompt_version 和 prompt_hash；
选择允许的 DeepSeek model_profile_code；
创建 AIReviewAttempt；
调用 DeepSeekGateway；
处理 DeepSeekGateway 返回的成功、失败和不确定结果；
保存 AIReviewReport；
拆分并保存 AIReviewFinding；
拆分并保存 AIReviewSuggestion；
记录 token usage、成本估算和调用元数据；
为 OpsConsole 提供请求、报告、发现和建议查询；
管理建议的人工状态流转；
写 AIReview 相关 AlertEvent 和审计记录。
```

## 4. 不负责事项

AIReview 不负责：

```text
创建 OrchestrationRun；
恢复或重跑编排；
采集行情；
生成 MarketSnapshot；
计算 FeatureLayer；
计算 AtomicSignal；
生成 StrategySignal；
生成 DecisionSnapshot；
执行 Binance Account Sync；
生成 PriceSnapshot；
生成 OrderPlan 或 CandidateOrderIntent；
执行 RiskCheck；
生成 ApprovedOrderIntent；
执行 ExecutionPreparation；
提交订单；
查询订单状态；
同步成交；
计算 PerformanceMetrics；
创建 RuntimeGuardIssue；
直接调用 DeepSeek API；
直接创建 DeepSeek client；
管理 DeepSeek API key；
解析完整 DeepSeek model_profile；
调用 Hermes；
把建议写入生产策略或配置。
```

## 5. 与 OpsConsole 的分工

OpsConsole 是页面和操作入口。

AIReview 是复盘业务模块。

分工如下：

```text
OpsConsole：
  选择 review_mode；
  选择复盘范围；
  填写人工问题；
  发起复盘请求；
  查看请求状态；
  查看复盘报告；
  查看发现和建议；
  标记建议状态；
  下载复盘数据包或报告。

AIReview：
  校验请求；
  冻结输入范围；
  组装复盘数据包；
  脱敏和裁剪数据；
  选择 prompt；
  调用 DeepSeekGateway；
  保存报告、发现和建议；
  管理请求状态；
  记录审计和 AlertEvent。
```

OpsConsole 不得直接调用 DeepSeekGateway。

允许路径：

```text
OpsConsole
→ AIReview API
→ AIReviewService
→ DeepSeekGateway
```

## 6. Review Mode

AIReview 必须支持 `review_mode`。

当前允许：

```text
cycle_review
anomaly_review
order_lifecycle_review
performance_attribution_review
manual_question_review
```

未知 `review_mode` 必须 fail-closed，不得默认映射为通用复盘。

### 6.1 cycle_review

周期复盘。

用于分析一组自动 OrchestrationRun 中：

```text
策略目标仓位；
实际持仓；
订单计划；
风控结果；
执行准备；
订单提交；
订单状态；
成交；
周期浮动收益；
告警和巡检问题。
```

目标是回答：

```text
这组周期内策略判断和交易链路整体表现如何？
```

### 6.2 anomaly_review

异常复盘。

用于分析：

```text
blocked；
unknown；
failed；
stale_interrupted；
RuntimeGuardIssue；
关键 AlertEvent。
```

目标是回答：

```text
异常在哪里发生，影响是什么，人工应该优先检查什么？
```

### 6.3 order_lifecycle_review

订单链路复盘。

用于分析：

```text
OrderPlan；
CandidateOrderIntent；
RiskCheckResult；
ApprovedOrderIntent；
ExecutionPreparationResult；
PreparedOrderIntent；
OrderSubmissionAttempt；
OrderStatusSyncRecord；
FillSyncResult；
TradeFill；
OrderFillSummary；
ActiveLock。
```

目标是回答：

```text
订单从计划到成交的链路是否清楚，是否存在卡住、不确定或执行质量问题？
```

### 6.4 performance_attribution_review

收益归因辅助复盘。

用于分析：

```text
OrchestrationRunPerformance；
目标仓位；
实际持仓；
mark price 变化；
订单 realized_pnl；
手续费；
是否调仓；
异常和告警。
```

目标是回答：

```text
周期浮动收益主要和哪些持仓、价格、执行或异常因素相关？
```

AIReview 只能做解释和线索整理，不重新计算 PerformanceMetrics。

### 6.5 manual_question_review

人工问题复盘。

用户必须提供明确问题，并选择受控数据范围。

规则：

```text
问题必须围绕所选复盘数据；
不得要求模型给出实时交易指令；
不得要求模型绕过风控；
不得要求模型生成下单建议；
不得要求模型输出未经人工审核即可执行的配置变更；
回答必须基于提供的数据包。
```

## 7. 触发入口

AIReview 当前只支持人工触发。

合法入口：

```text
OpsConsole AIReview 页面；
受控 management command dry-run；
受控 management command confirm-write；
受控 Celery task。
```

当前不做自动定时复盘。

后续如果需要自动复盘，必须单独定义触发条件、权限、成本上限和告警规则。

## 8. 对外服务入口

本模块必须提供明确 service 入口。

### 8.1 创建复盘请求

语义接口：

```text
create_review_request(
    review_mode,
    range_selector,
    filters,
    manual_question,
    model_profile_code,
    requested_by,
    trace_id,
    trigger_source,
)
```

返回：

```text
AIReviewRequest
```

要求：

```text
review_mode 必须合法；
range_selector 必须固定且可追溯；
manual_question 只在 manual_question_review 必填；
requested_by 必须有权限；
model_profile_code 必须是 AIReview 允许使用的 profile；
不得在这里调用 DeepSeek；
不得读取前端传入的任意模型名；
不得接受前端传入完整 model_profile；
不得接受前端传入 provider 参数；
不得接受前端传入 base_url 或 API key。
```

### 8.2 构建复盘数据包

语义接口：

```text
build_review_package(
    ai_review_request_id,
    trace_id,
)
```

返回：

```text
AIReviewPackage
```

要求：

```text
读取已冻结的复盘范围；
读取已落库业务事实；
生成结构化数据包；
执行脱敏；
执行大小控制；
计算 package_hash；
不得请求 Binance；
不得调用 DeepSeek；
不得改变任何上游业务对象。
```

### 8.3 执行复盘调用

语义接口：

```text
run_review(
    ai_review_request_id,
    trace_id,
)
```

返回：

```text
AIReviewReport 或明确失败结果
```

要求：

```text
必须已有 AIReviewPackage；
必须选择确定的 prompt 版本；
必须创建 AIReviewAttempt；
必须通过 DeepSeekGateway 调用 DeepSeek；
必须保存调用结果和 token usage；
不得绕过 DeepSeekGateway。
```

### 8.4 更新建议状态

语义接口：

```text
update_suggestion_status(
    ai_review_suggestion_id,
    new_status,
    operator_id,
    decision_note,
    trace_id,
)
```

要求：

```text
必须校验权限；
必须校验状态流转合法；
必须记录人工决策说明；
必须写审计；
不得执行建议内容；
不得修改策略、订单、风控或真实交易运行配置。
```

## 9. 复盘范围

AIReview 默认按 OrchestrationRun 范围复盘。

支持：

```text
最近 20 个自动 run；
最近 50 个自动 run；
最近 100 个自动 run；
自定义 UTC 时间范围；
显式 OrchestrationRun ID 列表；
只包含有订单 run；
只包含 blocked / unknown / failed run；
只包含存在 RuntimeGuardIssue 的 run。
```

规则：

```text
复盘范围必须在请求创建时冻结；
冻结后不得因为新数据产生而改变；
默认只选择 automatic run；
manual_diagnostic run 只有在显式选择时才可进入数据包；
不得用服务器本地时间解释范围；
不得通过数据库最新记录隐式扩展范围。
```

如果范围为空：

```text
AIReviewRequest.status = blocked；
reason_code = empty_review_range。
```

## 10. 可读取数据

AIReview 只读取已经落库的数据。

可以读取：

```text
OrchestrationRun；
OrchestrationStepRun；
OrchestrationBusinessObjectLink；
MarketSnapshot；
FeatureSet / FeatureValue；
AtomicSignalSet / AtomicSignalValue；
DomainSignalSet / DomainSignalValue；
MarketRegimeSnapshot；
StrategyRouteDecision；
StrategyAnalysisRelease；
StrategySignal；
StrategySignalQualityResult；
DecisionSnapshot；
BinanceSyncRun；
BinanceAccountSnapshot；
BinanceBalanceSnapshot；
BinancePositionSnapshot；
PriceSnapshot；
OrderPlan；
CandidateOrderIntent；
OrderPlanActiveLock；
RiskCheckResult；
ApprovedOrderIntent；
ExecutionPreparationResult；
PreparedOrderIntent；
OrderSubmissionAttempt；
OrderStatusSyncRecord；
FillSyncResult；
TradeFill；
OrderFillSummary；
OrchestrationRunPerformance；
RuntimeGuardIssue；
AlertEvent；
AuditRecord。
```

AIReview 不得：

```text
请求 Binance；
请求 DeepSeek API 原始 endpoint；
重新计算特征；
重新计算信号；
重新计算目标仓位；
重新计算订单计划；
重新执行风控；
重新计算周期收益；
用 Redis 缓存替代 MySQL 事实。
```

## 11. AIReviewPackage

AIReviewPackage 是发送给大模型的复盘数据包，也是后台可下载的复盘输入证据。

数据包必须结构化。

建议同时保存：

```text
JSON payload；
Markdown summary；
package_hash；
data_schema_version；
sanitization_version；
input_refs_hash。
```

数据包至少包含：

```text
复盘请求摘要；
review_mode；
复盘范围；
每个 OrchestrationRun 的时间、状态和终止原因；
每个 StepRun 的状态、统一结果和原因码；
关键业务对象引用；
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
OrchestrationRunPerformance；
AlertEvent 摘要；
RuntimeGuardIssue 摘要；
人工问题。
```

数据包不得复制不可控大体积原始数据。

例如：

```text
不得放入完整历史 K 线窗口；
不得放入完整大体积 raw_payload；
不得放入完整外部响应；
不得放入完整未裁剪日志；
不得放入数据库连接或环境变量。
```

## 12. 数据脱敏

AIReviewPackage 发送给 DeepSeek 前必须脱敏。

禁止包含：

```text
Binance API key；
Binance secret；
DeepSeek API key；
签名；
Authorization header；
Cookie；
认证 token；
数据库密码；
Redis 密码；
Webhook secret；
环境变量；
完整 request header；
完整未脱敏外部响应；
服务器本地敏感路径。
```

允许保留：

```text
symbol；
side；
quantity；
price；
mark_price；
order_id；
client_order_id；
status；
reason_code；
error_code；
脱敏 error_message；
trace_id；
业务对象 ID；
复盘所需数值。
```

如错误信息可能包含敏感内容，必须保存脱敏版本。

脱敏失败时：

```text
AIReviewRequest.status = failed；
reason_code = sanitization_failed；
不得调用 DeepSeekGateway。
```

## 13. 大小与成本控制

AIReview 必须控制输入大小和输出大小。

规则：

```text
默认最多支持最近 100 个自动 run；
不得允许无限历史一键提交；
构建数据包前必须估算输入大小；
超过 model_profile_code 对应的受控输入上限时必须阻断或要求缩小范围；
可以使用摘要模式降低输入大小；
必须记录 input size estimate；
必须记录 provider 返回的 token usage；
必须保存成本估算所需字段。
```

如果复盘范围过大：

```text
AIReviewRequest.status = blocked；
reason_code = review_package_too_large；
message_zh = 建议缩小复盘范围或使用摘要模式。
```

成本控制失败不得降级为绕过脱敏或发送完整原始数据。

## 14. Prompt 版本管理

AIReview 必须使用版本化 prompt。

每次调用必须记录：

```text
prompt_name；
prompt_version；
prompt_hash；
prompt_schema_version；
prompt_summary；
review_mode；
output_schema_version。
```

规则：

```text
不同 review_mode 使用明确 prompt；
prompt 变更必须生成新的 prompt_hash；
历史报告保留当时使用的 prompt 信息；
不得用数据库中可随意编辑的 prompt 覆盖历史报告语义；
prompt 必须明确说明大模型只做离线复盘；
prompt 必须禁止输出实时交易指令；
prompt 必须要求建议进入人工审核。
```

## 15. 输出格式

AIReview 默认要求结构化输出。

模型输出至少应包含：

```text
report_title；
executive_summary；
review_mode；
time_range_utc；
overall_assessment；
key_findings；
suggestions；
risk_notes；
data_limitations；
confidence；
manual_review_required_items。
```

`key_findings` 至少包含：

```text
finding_type；
severity；
title；
description；
evidence_refs；
related_run_ids；
related_order_ids；
confidence。
```

`suggestions` 至少包含：

```text
suggestion_type；
priority；
title；
description；
target_area；
suggested_action；
rationale；
expected_impact；
risk_note；
requires_human_review。
```

如果模型输出结构无法解析：

```text
AIReviewAttempt.status = response_parse_error；
AIReviewRequest.status = failed；
不得创建 completed AIReviewReport。
```

可以保存脱敏失败摘要，供人工排查。

## 16. 调用 DeepSeek

AIReview 只能通过 DeepSeekGateway 调用 DeepSeek。

调用前必须具备：

```text
AIReviewRequest；
AIReviewPackage；
prompt 版本；
model_profile_code；
input_package_hash；
idempotency_key；
trace_id。
```

AIReview 调用 DeepSeekGateway 时只能传递 `model_profile_code`，不得向 Gateway 传递完整 `model_profile`、任意模型名、base_url、API key 或 provider 参数。

调用时必须创建：

```text
AIReviewAttempt
```

AIReviewAttempt 记录一次 DeepSeekGateway 调用事实。

AIReview 不得：

```text
直接 import DeepSeek SDK；
直接创建 HTTP client；
直接拼接 DeepSeek endpoint；
直接读取 DeepSeek API key；
绕过 Gateway 重试；
把 Gateway unknown_after_send 解释为成功。
```

## 17. Gateway 结果映射

AIReview 必须显式映射 DeepSeekGatewayResult。

建议映射：

```text
Gateway succeeded
→ AIReviewAttempt succeeded
→ 解析输出并创建 AIReviewReport。

Gateway blocked_before_send
→ AIReviewAttempt blocked
→ AIReviewRequest failed。

Gateway failed_before_send
→ AIReviewAttempt failed_before_send
→ AIReviewRequest failed。

Gateway provider_rejected
→ AIReviewAttempt provider_rejected
→ AIReviewRequest failed。

Gateway rate_limited
→ AIReviewAttempt rate_limited
→ AIReviewRequest failed 或等待人工重新发起。

Gateway timeout 且 request_sent = false
→ AIReviewAttempt timeout_before_send
→ AIReviewRequest failed。

Gateway timeout 且 request_sent = true
→ AIReviewAttempt unknown
→ AIReviewRequest unknown。

Gateway unknown_after_send
→ AIReviewAttempt unknown
→ AIReviewRequest unknown。

Gateway response_parse_error
→ AIReviewAttempt response_parse_error
→ AIReviewRequest failed。

Gateway failed
→ AIReviewAttempt failed
→ AIReviewRequest failed。
```

未知 Gateway status 必须 fail-closed。

## 18. 重试与重新发起

AIReview 不自动重试 DeepSeek 调用。

规则：

```text
Gateway 内部有限技术重试只属于同一次 AIReviewAttempt；
AIReviewAttempt 失败后不得自动创建下一次 attempt；
unknown_after_send 不得自动重试；
provider_rejected 不得自动重试；
rate_limited 不得快速重试；
人工重新发起必须记录 operator_id、reason 和 trace_id；
已有 completed AIReviewReport 的 request 不得再次调用 DeepSeek。
```

失败后可以由授权用户创建新的 AIReviewRequest，引用原请求作为 `source_review_request_id`。

同一个 AIReviewRequest 最多有一个 completed AIReviewReport。

## 19. 数据模型

AIReview 拥有以下业务对象：

```text
AIReviewRequest；
AIReviewPackage；
AIReviewAttempt；
AIReviewReport；
AIReviewFinding；
AIReviewSuggestion。
```

实际模型名可以在实现计划中调整，但需求层面必须覆盖这些业务含义。

## 20. AIReviewRequest

AIReviewRequest 表示一次复盘请求。

至少记录：

```text
id
review_mode
range_selector
range_type
selected_orchestration_run_ids
filters
manual_question
status
reason_code
reason_message
requested_by
requested_at_utc
started_at_utc
finished_at_utc
source_review_request_id
model_provider
model_profile_code
model_name
prompt_name
prompt_version
prompt_hash
package_id
package_hash
attempt_count
input_size_estimate
input_token_count
output_token_count
total_token_count
cost_estimate
trace_id
created_at_utc
updated_at_utc
```

状态至少支持：

```text
created
packaging
packaged
calling_model
completed
blocked
unknown
failed
canceled
```

## 21. AIReviewPackage

AIReviewPackage 表示复盘数据包。

至少记录：

```text
id
review_request_id
package_format
data_schema_version
sanitization_version
package_hash
input_refs_hash
run_count
order_count
alert_count
runtime_issue_count
performance_record_count
payload_size_bytes
input_size_estimate
sanitized
sanitization_report
json_payload
markdown_summary
payload_storage_ref
created_at_utc
trace_id
```

如果数据包较大，可以使用受控对象存储或文件存储保存 payload，但 MySQL 必须保存正式索引、hash、摘要和存储引用。

## 22. AIReviewAttempt

AIReviewAttempt 表示一次大模型调用尝试。

至少记录：

```text
id
review_request_id
review_package_id
attempt_sequence
gateway_status
status
request_sent
provider
provider_request_id
model_profile_code
model_name
sanitized_model_profile_summary
api_format
prompt_hash
input_package_hash
idempotency_key
finish_reason
input_token_count
output_token_count
total_token_count
attempt_count_in_gateway
retryable
http_status
provider_error_code
error_code
error_message
sanitized_request_summary
sanitized_response_summary
started_at_utc
finished_at_utc
duration_ms
trace_id
```

AIReviewAttempt 不得保存 API key、完整 Authorization header、完整未脱敏 provider payload。

## 23. AIReviewReport

AIReviewReport 表示一次完整复盘报告。

至少记录：

```text
id
review_request_id
review_attempt_id
review_package_id
title
summary
full_report_markdown
structured_report_json
review_mode
model_provider
model_profile_code
model_name
prompt_name
prompt_version
prompt_hash
package_hash
output_hash
confidence
data_limitations
created_at_utc
trace_id
```

报告必须绑定 request、attempt 和 package。

历史报告不得被后续报告覆盖。

## 24. AIReviewFinding

AIReviewFinding 表示大模型发现的具体问题或观察点。

`finding_type` 至少支持：

```text
data_quality_issue
feature_issue
atomic_signal_issue
strategy_issue
decision_issue
account_fact_issue
price_fact_issue
order_plan_issue
risk_check_issue
execution_preparation_issue
order_submission_issue
order_status_issue
fill_sync_issue
performance_issue
runtime_issue
alert_pattern
manual_review_required
other
```

至少记录：

```text
id
review_report_id
finding_type
severity
title
description
evidence_refs
related_orchestration_run_ids
related_order_submission_attempt_ids
related_object_refs
confidence
needs_manual_attention
created_at_utc
trace_id
```

Finding 只用于复盘筛选和人工关注，不得自动触发交易修复。

## 25. AIReviewSuggestion

AIReviewSuggestion 表示大模型提出的人工建议。

`suggestion_type` 至少支持：

```text
investigate_run
investigate_order
investigate_runtime_issue
review_feature_definition
review_atomic_signal_definition
review_strategy_definition
review_risk_rule
review_execution_rule
review_order_plan_rule
review_performance_pattern
create_manual_task
no_action
other
```

至少记录：

```text
id
review_report_id
suggestion_type
priority
title
description
target_area
target_object_type
target_object_id
suggested_action
rationale
expected_impact
risk_note
status
reviewed_by
reviewed_at_utc
decision_note
created_at_utc
updated_at_utc
trace_id
```

Suggestion 是人工建议，不是生产变更。

## 26. Suggestion 状态流转

AIReviewSuggestion 至少支持：

```text
pending_review
accepted
rejected
converted_to_task
implemented
ignored
```

含义：

```text
pending_review：
  模型刚提出，等待人工评估。

accepted：
  人工认可建议，但尚未实施。

rejected：
  人工明确拒绝。

converted_to_task：
  已转为人工任务、开发计划或策略评估事项。

implemented：
  已通过人工流程落地。

ignored：
  人工确认暂不处理。
```

禁止：

```text
pending_review → 自动 implemented；
accepted → 自动变更生产配置；
converted_to_task → 自动生成代码或提交；
ignored → 删除原始建议；
implemented → 伪造实际变更证据。
```

状态变化必须记录 operator_id、decision_note、trace_id 和审计记录。

## 27. 如何利用复盘建议

正确流程：

```text
AIReview 生成建议
→ OpsConsole 展示建议
→ 人工审核
→ 人工转为任务或开发计划
→ 人工修改需求、策略定义或代码
→ 通过正常版本管理、测试和部署流程上线
→ 后续继续观察 OrchestrationRunPerformance 和交易链路。
```

禁止流程：

```text
AIReview 生成建议
→ 系统自动变更策略参数
→ 系统自动启用新策略
→ 系统自动交易。
```

## 28. 权限与审计

以下操作必须校验权限：

```text
发起复盘；
查看复盘请求；
下载复盘数据包；
查看完整 prompt 或数据包摘要；
查看复盘报告；
更新 Suggestion 状态；
取消未执行请求；
人工重新发起复盘。
```

以下操作必须写审计：

```text
创建 AIReviewRequest；
取消 AIReviewRequest；
下载 AIReviewPackage；
下载 AIReviewReport；
更新 AIReviewSuggestion 状态；
人工重新发起复盘；
标记建议 implemented。
```

审计记录不得包含完整未脱敏数据包、完整 prompt、API key 或 provider 原始响应。

## 29. AlertEvent

AIReview 必须写 AlertEvent 的场景至少包括：

```text
ai_review_requested；
ai_review_package_built；
ai_review_package_failed；
ai_review_call_started；
ai_review_call_succeeded；
ai_review_call_failed；
ai_review_call_unknown；
ai_review_report_created；
ai_review_suggestion_status_changed。
```

AlertEvent 必须脱敏。

AIReview 不直接发送 Hermes。

Notifications 是否投递由通知模块决定。

## 30. 与 DeepSeekGateway 的关系

DeepSeekGateway 是 DeepSeek API 的唯一请求边界。

AIReview 负责：

```text
构造业务输入；
脱敏数据；
生成 prompt；
创建 Attempt；
调用 DeepSeekGateway；
处理 Gateway 结果；
保存业务报告。
```

DeepSeekGateway 负责：

```text
API key；
base_url；
model profile；
请求格式；
超时；
限频；
错误标准化；
token usage；
技术日志。
```

AIReview 不得自行实现 HTTP 请求、API key 读取、provider 错误解析或重试循环。

## 31. 与 PerformanceMetrics 的关系

AIReview 可以读取 OrchestrationRunPerformance 作为复盘输入。

规则：

```text
AIReview 不计算周期浮动收益；
AIReview 不用订单 realized_pnl 替代周期浮动收益；
AIReview 不修改 OrchestrationRunPerformance；
AIReview 可以解释收益表现和潜在线索；
AIReview 必须明确说明收益解释基于已有 PerformanceMetrics。
```

## 32. 与 PipelineOrchestrator 的关系

AIReview 读取 OrchestrationRun、OrchestrationStepRun 和 OrchestrationBusinessObjectLink 来组织复盘上下文。

AIReview 不得：

```text
创建自动 OrchestrationRun；
重跑 OrchestrationRun；
推进 StepRun；
消费 resume_token；
变更 OrchestrationRun 状态；
补写 OrchestrationBusinessObjectLink；
绕过 Connector 调用交易模块。
```

## 33. 与 RuntimeGuardIssue 的关系

AIReview 可以读取 RuntimeGuardIssue 作为复盘输入。

可读取内容包括：

```text
自动编排主链路漏跑；
编排卡住；
步骤产物缺失；
订单链路长期不确定；
告警投递异常。
```

RuntimeGuard 不巡检 AIReview 自身状态。

AIReview 自身的 packaging、calling_model、unknown、failed 等状态，由 AIReview 模块和 OpsConsole 展示处理，不纳入 RuntimeGuard P0 巡检范围。

## 34. 数据库、Redis 与外部服务

```text
读 MySQL：是，读取复盘所需业务事实。
写 MySQL：是，保存 AIReviewRequest、AIReviewPackage、AIReviewAttempt、AIReviewReport、AIReviewFinding、AIReviewSuggestion、审计和 AlertEvent。
访问 Redis：可用于短期任务幂等、队列状态和防重复提交。
访问 Binance：否。
调用 DeepSeek：是，但只能通过 DeepSeekGateway。
发送 Hermes：否，只写 AlertEvent。
调用大模型：是，离线复盘用途。
涉及交易执行：否。
允许真实交易：否。
```

Redis 不得保存唯一复盘报告或唯一请求事实。

## 35. Management command 与 Celery task

允许提供：

```text
build_ai_review_package task；
run_ai_review task；
受控 dry-run command；
受控 confirm-write command。
```

task 和 command 只能：

```text
解析参数；
生成或传递 trace_id；
设置 trigger_source；
执行权限或确认校验；
调用 AIReview service；
输出结构化摘要。
```

task 和 command 不得：

```text
直接查询 DeepSeek；
直接创建 DeepSeek client；
直接写报告解析逻辑以外的业务对象；
直接修改交易链路；
直接修改策略或风控配置；
绕过 DeepSeekGateway。
```

人工命令默认 dry-run。写入请求、报告、建议或 AlertEvent 必须显式 confirm-write。

## 36. 幂等与并发

AIReview 必须处理重复点击、任务重放和 worker 崩溃。

规则：

```text
创建请求必须有 request_key 或等价幂等键；
相同 request_key 重复提交返回同一 AIReviewRequest；
同一 AIReviewRequest 不能并发构建多份有效 Package；
同一 AIReviewRequest 不能并发调用 DeepSeek；
同一 AIReviewRequest 最多一个 completed Report；
Package hash 相同的重复构建必须复用已有 Package；
Attempt sequence 必须单调递增；
worker 崩溃后不得自动重复发送已不确定是否发送的 DeepSeek 请求。
```

如果进程在 DeepSeekGateway 返回后、报告写入前崩溃：

```text
已保存的 AIReviewAttempt 作为恢复依据；
如果没有保存可解析输出，不得伪造 completed Report；
人工可以重新发起新的请求；
必须保留崩溃证据和 AlertEvent。
```

## 37. 异常处理

异常处理规则：

```text
review_mode 非法 → blocked；
复盘范围为空 → blocked；
数据包过大 → blocked；
脱敏失败 → failed；
Package 构建异常 → failed；
Prompt 缺失 → failed；
DeepSeekGateway blocked_before_send → failed；
DeepSeekGateway failed_before_send → failed；
DeepSeekGateway provider_rejected → failed；
DeepSeekGateway rate_limited → failed；
DeepSeekGateway timeout 且 request_sent = false → failed；
DeepSeekGateway timeout 且 request_sent = true → unknown；
DeepSeekGateway unknown_after_send → unknown；
DeepSeekGateway response_parse_error → failed；
DeepSeekGateway failed → failed；
模型输出结构不可解析 → failed；
数据库写入失败 → failed；
人工取消未开始请求 → canceled。
```

AIReview 失败不得：

```text
影响自动交易主流程；
修改 OrchestrationRun；
修改订单；
变更成交；
修改账户快照；
修改 PerformanceMetrics；
修改策略定义；
释放 ActiveLock；
触发下单；
触发 Binance 请求。
```

## 38. 测试要求

至少覆盖：

```text
1. OpsConsole 可以创建 cycle_review 请求。
2. OpsConsole 可以创建 anomaly_review 请求。
3. OpsConsole 可以创建 order_lifecycle_review 请求。
4. OpsConsole 可以创建 performance_attribution_review 请求。
5. manual_question_review 缺少人工问题时 blocked。
6. 未知 review_mode blocked。
7. 最近 20 / 50 / 100 个自动 run 范围可冻结。
8. UTC 时间范围查询不使用本地时区。
9. 空范围 blocked。
10. 构建 Package 只读取已落库数据。
11. Package 包含 OrchestrationRun、StepRun 和业务对象摘要。
12. Package 包含 PerformanceMetrics 但不重新计算收益。
13. Package 不包含 API key、secret、token、认证 header。
14. Package 过大时 blocked。
15. Prompt 信息记录 prompt_name、version 和 hash。
16. AIReview 只能通过 DeepSeekGateway 调用 DeepSeek。
17. AIReview 调用 Gateway 时只传 model_profile_code，不传完整 model_profile、任意模型名或 provider 参数。
18. AIReviewAttempt 保存 Gateway 返回的 sanitized_model_profile_summary。
19. 使用 fake DeepSeekGateway 可返回成功报告。
20. Gateway succeeded 后保存 Report、Finding 和 Suggestion。
21. Gateway failed_before_send 后 Request failed。
22. Gateway timeout 且 request_sent = false 后 Request failed。
23. Gateway timeout 且 request_sent = true 后 Request unknown。
24. Gateway unknown_after_send 后 Request 为 unknown，不自动重试。
25. Gateway response_parse_error 后 Request failed。
26. Gateway failed 后 Request failed。
27. Gateway provider_rejected 后 Request failed。
28. 模型 JSON 解析失败时不创建 completed Report。
29. 同一 Request 不产生两个 completed Report。
30. 重复提交 request_key 返回同一 Request。
31. Suggestion 初始状态为 pending_review。
32. Suggestion accepted 不会自动修改策略。
33. Suggestion implemented 必须记录人工说明。
34. AIReview 失败不影响交易主流程。
35. AIReview 不访问 Binance。
36. AIReview 不提交订单。
37. RuntimeGuardIssue 可作为 AIReview 复盘输入，但 RuntimeGuard 不巡检 AIReview 自身状态。
38. 下载 Package 需要权限。
39. 更新 Suggestion 状态需要权限并写审计。
40. AlertEvent 不包含敏感信息。
```

## 39. 验收标准

满足以下条件才算通过：

```text
AIReview 是离线复盘模块；
review_mode 明确且可扩展；
复盘范围冻结且可追溯；
复盘数据包结构化、脱敏、可 hash；
prompt 版本可追溯；
DeepSeek 调用只通过 DeepSeekGateway；
AIReview 只向 Gateway 传递 model_profile_code，不传完整 model_profile 或 provider 参数；
AIReviewAttempt 保存 Gateway 返回的脱敏模型配置摘要；
DeepSeek API key 不进入数据库或前端；
模型输出保存为报告、发现和建议；
建议只进入人工状态流转；
AIReview 不修改策略、风控、订单、账户、收益或锁；
AIReview 不参与实时交易；
失败、超时和 unknown 不影响交易主流程；
后台可以查看请求、报告、发现、建议和审计；
测试使用 fake DeepSeekGateway。
```

## 40. 当前不包含的能力

```text
自动定时复盘；
多 provider 路由；
多模型投票；
复杂向量数据库；
长期知识库；
RAG 检索系统；
自动回测；
自动验证建议收益；
自动调参；
自动创建策略版本；
自动启用或禁用策略；
自动暂停或恢复真实交易；
大模型直接写代码；
大模型直接提交 Git；
大模型直接调用外部工具；
大模型直接查询数据库。
```

## 41. 最终结论

AIReview 的最终定位是：

```text
离线大模型复盘分析模块。
```

一句话：

```text
AIReview 把已落库交易事实整理给 DeepSeek 做离线复盘，并保存报告、发现和人工建议；它不做实时交易、不自动改策略、不自动修复系统。
```
