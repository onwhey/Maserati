# DeepSeekGateway 需求

## 1. 模块定位

DeepSeekGateway 是系统访问 DeepSeek API 的唯一基础设施边界。

任何业务模块需要调用 DeepSeek 生成离线复盘分析、结构化建议或报告内容，都必须通过 DeepSeekGateway 提供的受限接口完成。

当前允许调用方：

```text
AIReview
```

OpsConsole 只提交复盘任务，不直接调用 DeepSeekGateway。

DeepSeekGateway 是通信基础能力，不是复盘业务模块、策略模块、风控模块、执行模块或后台页面模块。

## 2. 设计目标

本模块必须实现：

```text
所有 DeepSeek API 访问统一出口；
API key、base_url、model 和超时配置统一管理；
请求、响应和错误使用统一结构；
支持官方兼容 API 格式；
支持非流式复盘生成；
支持结构化 JSON 输出参数；
统一执行超时、限频、并发控制、冷却和脱敏；
对可证明未发送的技术失败执行有限重试；
对已发送或无法确认是否发送的请求不自动重试；
记录调用指标、token usage 和脱敏元数据；
测试时可使用 fake gateway 覆盖真实外部调用；
不得让大模型参与实时交易决策。
```

DeepSeekGateway 只返回技术事实。复盘任务状态、prompt 版本、报告保存和业务解释由 AIReview 负责。

## 3. 负责事项

DeepSeekGateway 负责：

```text
加载 DeepSeek API key；
加载 base_url；
加载允许使用的 model profile；
构造规范化请求；
执行连接、读取超时和连接池管理；
执行本地限频和并发控制；
执行短期冷却和熔断；
执行允许范围内的有限技术重试；
解析 HTTP 状态和 provider 错误；
解析 DeepSeek 返回的响应结构；
提取输出文本；
提取 token usage；
提取 provider request id 或等价元数据；
返回脱敏后的请求和响应摘要；
记录技术日志和调用指标；
过滤日志、异常和指标中的敏感信息。
```

## 4. 不负责事项

DeepSeekGateway 不负责：

```text
选择要复盘哪些 OrchestrationRun；
读取交易业务数据；
构造 AIReviewPackage；
编写 prompt；
决定 review_mode；
决定 prompt_version；
判断策略是否合理；
判断风控是否合理；
生成 AIReviewReport；
拆分 AIReviewFinding；
拆分 AIReviewSuggestion；
保存复盘报告；
保存业务 AlertEvent；
修改策略定义；
修改风控规则；
修改订单、成交、账户或持仓；
修改 PerformanceMetrics；
修改 RuntimeGuardIssue；
提交订单；
撤单；
重试订单提交；
调用 Binance；
调用 Hermes；
把大模型结论写回实时交易链路。
```

## 5. 内部结构

DeepSeekGateway 由两层组成：

```text
受限能力接口
→ DeepSeekTransport
```

`DeepSeekTransport` 是模块内部实现，不得作为公共 service 暴露给业务模块。

禁止提供以下公共能力：

```text
request(method, path, body)
raw_request(...)
call_any_endpoint(...)
raw_client
session
直接暴露 SDK client
```

业务模块只能调用本文档定义的具体语义操作。

## 6. 受限接口

当前只提供一个受限接口：

```text
DeepSeekReviewGateway
```

允许调用方：

```text
AIReviewService
```

允许操作：

```text
generate_review_completion(
    context,
    model_profile_code,
    messages,
    response_format,
    max_output_tokens,
    trace_id,
)
```

实际 Python 方法名可在开发计划中确定，但不得改变操作语义。

`DeepSeekReviewGateway` 只生成一次离线复盘响应，不提供通用聊天能力。

## 7. API 格式

DeepSeekGateway 必须支持官方兼容 API 格式。

当前默认采用：

```text
OpenAI-compatible chat completions format
```

如后续需要 Anthropic-compatible format，必须作为明确配置和测试路径加入，不得让业务模块直接拼接不同 provider 格式。

Gateway 必须屏蔽 provider 格式差异，向 AIReview 返回统一结果。

## 8. Model Profile

DeepSeekGateway 不允许业务模块直接传入任意模型名，也不允许业务模块直接传入完整模型参数。

业务模块只能传入受控 `model_profile_code`。

DeepSeekGateway 必须根据 `model_profile_code` 从环境配置或受控 settings 中读取完整 `model_profile`。

也就是说：

```text
AIReview 只能选择已经配置好的模型套餐编号；
DeepSeekGateway 才能解析具体 model_name、api_format、timeout、temperature、token 上限和推理参数；
OpsConsole 或 AIReviewRequest 不得直接提交完整模型参数。
```

`model_profile` 至少包含：

```text
profile_code
model_name
api_format
thinking_enabled
reasoning_effort
json_output_enabled
max_input_tokens
max_output_tokens
temperature
top_p
timeout_seconds
enabled
```

规则：

```text
模型名来自环境配置或受控 settings；
不得硬编码到业务 service；
不得使用被官方标记为废弃的兼容别名；
不得由 OpsConsole 前端任意填写模型名；
不得由 AIReviewRequest 绕过配置传入任意 model；
不得由 AIReviewRequest 绕过配置传入完整 model_profile；
禁用的 profile 不得调用；
Gateway 必须在返回结果中提供本次实际使用的脱敏 profile 参数摘要；
AIReview 负责把该摘要保存进 AIReviewAttempt 或等价调用记录。
```

如果模型配置缺失、禁用或不合法，Gateway 必须在发起外部请求前阻断。

## 9. 结构化输出

DeepSeekGateway 必须支持 AIReview 请求结构化输出。

当 AIReview 需要 JSON 结果时，Gateway 应根据官方兼容格式设置等价参数：

```text
response_format = json_object
```

规则：

```text
AIReview 负责在 prompt 中要求输出 JSON；
AIReview 负责提供 JSON schema 或示例；
Gateway 只负责传递结构化输出参数；
Gateway 可以校验返回内容是否可解析为 JSON；
Gateway 不解释 JSON 中的业务含义；
JSON 解析失败时返回 response_parse_error；
空内容必须返回 content_empty。
```

Gateway 不得用模型输出直接修改业务对象。

## 10. Thinking 与推理参数

DeepSeekGateway 可以支持 thinking mode、reasoning_effort 或等价推理参数。

规则：

```text
推理参数来自 model_profile；
AIReview 可以按 review_mode 选择允许的 profile；
OpsConsole 不能直接传入任意推理参数；
Gateway 只负责参数透传和合法性校验；
推理参数必须进入脱敏调用摘要；
推理过程内容是否保存由 AIReview 文档单独定义。
```

如果 provider 返回不可展示或不适合保存的中间推理内容，Gateway 不得默认写入日志或数据库。

## 11. 请求上下文

所有调用必须接收 `DeepSeekGatewayCallContext` 或等价不可变结构。

至少包含：

```text
caller_module
purpose
ai_review_request_id
review_mode
input_package_hash
prompt_hash
model_profile_code
idempotency_key
operator_id
trace_id
trigger_source
created_at_utc
```

规则：

```text
purpose 当前只允许 ai_review；
caller_module 当前只允许 AIReview；
idempotency_key 由 AIReview 生成；
Gateway 不解析 idempotency_key 的业务含义；
operator_id 只用于审计，不写入 provider user_id；
trace_id 贯穿日志和业务记录。
```

如使用 provider 的 `user_id` 或等价隔离字段，必须使用不含隐私信息的稳定技术 ID。

## 12. 请求内容限制

DeepSeekGateway 必须在发起请求前执行基础内容限制。

至少校验：

```text
messages 非空；
messages 总大小不超过 model_profile.max_input_tokens 或等价估算；
max_output_tokens 不超过 profile 上限；
message role 合法；
message content 为文本或允许的结构；
不包含明显密钥字段；
不包含完整认证 header；
不包含数据库连接串；
不包含 Binance API key / secret；
不包含 DeepSeek API key；
不包含不可控大体积原始 payload。
```

敏感字段检测不能替代 AIReviewPackage 的正式脱敏规则，但必须作为最后一道保护。

不满足限制时：

```text
不发起外部请求；
返回 blocked_before_send；
记录 reason_code；
不记录原始敏感内容。
```

## 13. 返回结果

所有操作必须返回稳定的 `DeepSeekGatewayResult` 或等价结构。

至少包含：

```text
status
request_sent
provider_request_id
model_name
model_profile_code
sanitized_model_profile_summary
api_format
response_text
response_json
finish_reason
input_token_count
output_token_count
total_token_count
attempt_count
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

`response_text` 和 `response_json` 是否由 AIReview 保存，取决于 AIReview 的数据模型和脱敏规则。

Gateway 自身不得把完整大模型输出写入技术日志。

## 14. 结果状态

`status` 至少支持：

```text
succeeded
blocked_before_send
failed_before_send
provider_rejected
rate_limited
timeout
unknown_after_send
response_parse_error
failed
```

含义：

```text
succeeded：
  收到 provider 响应并成功解析出可交给 AIReview 的结果。

blocked_before_send：
  配置、安全、权限、大小或敏感内容校验失败，未发送请求。

failed_before_send：
  本地连接准备、配置加载或序列化失败，能证明请求未离开本地进程。

provider_rejected：
  provider 明确拒绝，例如认证、余额、参数或权限问题。

rate_limited：
  本地限频或 provider 429。

timeout：
  调用超时，且能按 request_sent 标记是否已发送。

unknown_after_send：
  请求已经发送或无法确认是否发送，但没有取得可解析终态响应。

response_parse_error：
  收到响应，但结构、JSON 或必要字段无法解析。

failed：
  其他不可预期技术失败。
```

`unknown_after_send` 不得被 AIReview 自动解释为 succeeded。

## 15. 错误分类

Gateway 必须把 provider 和本地异常转换为稳定错误分类。

至少包括：

```text
gateway_disabled
invalid_configuration
invalid_model_profile
payload_too_large
sensitive_payload_blocked
serialization_failed
connection_error_before_send
request_timeout_before_send
request_timeout_after_send
network_lost_after_send
authentication_failed
insufficient_balance
invalid_request_format
invalid_parameters
rate_limit_reached
provider_server_error
provider_overloaded
empty_content
json_parse_failed
output_truncated
unexpected_response_schema
unknown_provider_error
```

错误信息必须脱敏。

不得把 provider 原始错误完整透传到前端、日志或 AlertEvent。

## 16. 超时与重试

DeepSeekGateway 可以执行有限技术重试，但必须非常保守。

允许重试的前提：

```text
能证明请求尚未离开本地进程；
或连接在发送请求体前失败；
或本地连接池获取失败；
或 DNS / TLS 建连阶段失败。
```

禁止自动重试：

```text
请求已经发送；
无法判断请求是否已发送；
provider 已经开始推理；
已经收到 provider 业务错误；
认证失败；
余额不足；
参数错误；
内容过大；
敏感内容阻断；
JSON 解析失败；
response 内容为空；
输出被截断。
```

规则：

```text
重试次数来自配置；
不得无限重试；
必须指数退避或等价冷却；
每次 attempt 必须记录；
Gateway attempt_count 与 AIReview 业务 attempt 必须分开记录；
Gateway 耗尽尝试后返回标准结果；
是否重新发起 AIReview 调用由 AIReview 业务规则和人工操作决定。
```

同一个 AIReviewRequest 不得因为 Gateway 自动重试产生多份业务报告。

## 17. 限频、并发与冷却

DeepSeekGateway 必须统一处理本地限频和并发控制。

至少按以下维度控制：

```text
provider
model_profile_code
caller_module
purpose
```

规则：

```text
不得让业务模块各自实现独立请求计数器；
本地限频命中时不得发起外部请求；
provider 429 时进入冷却；
provider 500 / 503 可进入短期冷却；
冷却期内快速失败并返回 rate_limited 或 provider_overloaded；
不得在冷却期快速循环请求。
```

Redis 可以用于短期限频、冷却和并发计数。

Redis 不得保存正式复盘报告或唯一调用事实。

## 18. 熔断

Gateway 应维护短期熔断状态。

建议维度：

```text
provider
base_url
model_profile_code
error_class
```

触发场景：

```text
连续认证失败；
连续余额不足；
连续 provider_overloaded；
连续 provider_server_error；
连续 timeout；
连续 response_parse_error。
```

熔断只阻断新的 DeepSeek 请求，不影响历史报告查看，不影响交易主流程。

## 19. 日志与指标

DeepSeekGateway 必须记录脱敏技术日志和指标。

至少包括：

```text
provider；
model_profile_code；
api_format；
purpose；
review_mode；
status；
error_code；
http_status；
request_sent；
attempt_count；
duration_ms；
input_token_count；
output_token_count；
total_token_count；
retryable；
trace_id。
```

日志和指标不得包含：

```text
DeepSeek API key；
Authorization header；
完整 prompt；
完整大模型输出；
完整 AIReviewPackage；
Binance API key；
数据库密码；
未脱敏外部响应。
```

完整 prompt、数据包和报告如需保存，必须由 AIReview 按自己的脱敏和大小控制规则保存。

## 20. AlertEvent 边界

DeepSeekGateway 不直接写业务 AlertEvent。

调用方 AIReview 必须根据 Gateway 结果决定：

```text
AIReviewRequest.status；
AIReviewAttempt.status；
是否写 AlertEvent；
是否需要 RuntimeGuard 后续巡检。
```

Gateway 可以暴露技术指标供监控或 RuntimeGuard 间接查看，但 RuntimeGuard 不得通过 Gateway 自动发起复盘。

## 21. 配置

所有配置必须进入 `.env.example` 并带中文注释。

至少包括：

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

规则：

```text
真实 API key 不得提交；
API key 不得保存到数据库；
API key 不得由 OpsConsole 页面管理；
base_url 不得由前端传入；
model 不得由前端任意传入；
配置变更必须通过部署配置或受控 settings；
启动时必须校验关键配置合法性。
```

## 22. 数据库、Redis 与外部服务

```text
读 MySQL：否。
写 MySQL：否。
访问 Redis：可用于短期限频、冷却、熔断和并发计数。
访问 DeepSeek：是。
访问 Binance：否。
发送 Hermes：否。
调用大模型：是，只作为 AIReview 的离线复盘请求底层能力。
涉及交易执行：否。
允许真实交易：否。
```

DeepSeekGateway 不拥有核心业务表。

AIReview 负责保存请求、尝试、数据包、报告、问题和建议。

## 23. 与 AIReview 的关系

AIReview 是 DeepSeekGateway 的唯一业务调用方。

职责分工：

```text
AIReview 负责选择 review_mode；
AIReview 负责选择 OrchestrationRun 范围；
AIReview 负责生成 AIReviewPackage；
AIReview 负责脱敏业务数据；
AIReview 负责生成 prompt；
AIReview 负责选择允许的 model_profile_code；
AIReview 负责调用 DeepSeekGateway；
AIReview 负责保存报告和结构化结果；
AIReview 负责处理 Gateway 返回的失败、不确定和重试建议。
```

DeepSeekGateway 不得读取 AIReview 业务表来决定是否调用。

AIReview 不得绕过 DeepSeekGateway 直接创建 DeepSeek client。

## 24. 与 OpsConsole 的关系

OpsConsole 不直接调用 DeepSeekGateway。

允许路径：

```text
OpsConsole
→ AIReview API
→ AIReviewService
→ DeepSeekGateway
```

禁止路径：

```text
OpsConsole
→ DeepSeekGateway

OpsConsole
→ DeepSeek API
```

OpsConsole 只能展示 AIReview 状态、报告和错误摘要。

OpsConsole 不得展示 DeepSeek API key、完整 provider payload 或未脱敏 prompt。

## 25. 与交易链路的关系

DeepSeekGateway 与正式交易链路完全隔离。

DeepSeekGateway 不得：

```text
生成 DecisionSnapshot；
生成 OrderPlan；
执行 RiskCheck；
生成 ApprovedOrderIntent；
执行 ExecutionPreparation；
提交订单；
查询订单状态；
查询成交；
释放 ActiveLock；
修改 PerformanceMetrics；
修改 RuntimeGuardIssue；
修改真实交易运行配置；
触发 Hermes 交易通知。
```

DeepSeek 调用失败、超时、限频或余额不足，不得影响自动交易主流程。

## 26. Fake Gateway 与测试

自动化测试必须使用 fake DeepSeekGateway，不得访问真实 DeepSeek。

Fake Gateway 必须支持：

```text
返回固定成功响应；
返回结构化 JSON；
返回空内容；
返回 JSON 解析失败；
返回 provider_rejected；
返回 rate_limited；
返回 timeout；
返回 unknown_after_send；
返回 token usage；
验证敏感信息没有进入请求。
```

测试不得依赖真实 API key、真实余额、真实网络或真实模型输出。

## 27. 异常处理

异常处理规则：

```text
gateway disabled → blocked_before_send；
配置缺失 → blocked_before_send；
model_profile 禁用 → blocked_before_send；
payload 过大 → blocked_before_send；
敏感内容命中 → blocked_before_send；
认证失败 → provider_rejected；
余额不足 → provider_rejected；
参数错误 → provider_rejected；
本地限频 → rate_limited；
provider 429 → rate_limited；
provider 500 / 503 且已收到明确响应 → failed；
请求已发送后断连 → unknown_after_send；
JSON 解析失败 → response_parse_error；
返回空内容 → response_parse_error；
未知异常 → failed。
```

Gateway 只返回技术结果，不直接更新 AIReviewRequest。

## 28. 测试要求

至少覆盖：

```text
1. AIReview 只能通过 DeepSeekGateway 调用 DeepSeek。
2. OpsConsole 不能直接调用 DeepSeekGateway。
3. Gateway disabled 时不发起外部请求。
4. 缺少 API key 时不发起外部请求。
5. 禁用 model_profile 时不发起外部请求。
6. 前端和 AIReviewRequest 不能传入任意 model_name 或完整 model_profile。
7. Gateway 必须根据 model_profile_code 解析受控 profile。
8. messages 为空时 blocked_before_send。
9. payload 超过限制时 blocked_before_send。
10. 敏感字段命中时 blocked_before_send。
11. 成功响应返回 succeeded、输出内容和 token usage。
12. JSON 输出可解析时返回 response_json。
13. JSON 输出不可解析时返回 response_parse_error。
14. 空内容返回 response_parse_error。
15. 认证失败映射 provider_rejected。
16. 余额不足映射 provider_rejected。
17. 参数错误映射 provider_rejected。
18. provider 429 映射 rate_limited 并进入冷却。
19. provider 500 / 503 收到明确响应时映射 failed，不映射 unknown_after_send。
20. provider 500 / 503 不快速循环重试。
21. 请求已发送后断连返回 unknown_after_send。
22. 可证明未发送的连接失败可以有限重试。
23. 请求已发送或不确定是否发送时不自动重试。
24. Gateway attempt_count 与 AIReview 业务 attempt 分开记录。
25. 日志不包含 API key、Authorization header、完整 prompt 或完整输出。
26. fake gateway 可覆盖成功、失败、限频、超时和 unknown。
27. DeepSeek 调用失败不影响交易主流程。
28. Gateway 不写业务 AlertEvent。
29. Gateway 不访问 Binance。
30. Gateway 不提交订单、不撤单、不修改锁。
```

## 29. 验收标准

满足以下条件才算通过：

```text
DeepSeek API 访问只有 DeepSeekGateway 一个出口；
AIReview 是唯一业务调用方；
OpsConsole 不直接调用 Gateway；
API key、base_url、model 和超时均由配置管理；
前端和 AIReviewRequest 不能传入任意模型、完整 model_profile 或 provider 参数；
请求、响应和错误结构稳定；
Gateway 返回本次实际使用的脱敏 profile 参数摘要；
支持结构化 JSON 输出；
支持 token usage 记录；
限频、并发、冷却和熔断集中实现；
已发送或不确定是否发送的请求不会自动重试；
敏感信息不会进入日志、指标、前端或 AlertEvent；
测试使用 fake gateway；
大模型调用与实时交易链路隔离；
Gateway 不保存业务报告、不解释复盘结论、不修改任何交易对象。
```

## 30. 当前不包含的能力

```text
多 provider 路由；
多模型自动对比；
自动选择最优模型；
流式输出展示；
Tool Calls；
让 DeepSeek 调用外部工具；
让 DeepSeek 直接查询数据库；
让 DeepSeek 直接调用 Binance；
让 DeepSeek 直接修改策略；
让 DeepSeek 自动生成代码并提交；
让 DeepSeek 参与实时交易决策；
把 DeepSeek 结论自动转成生产配置。
```

## 31. 最终结论

DeepSeekGateway 的最终定位是：

```text
DeepSeek API 的受控请求边界。
```

一句话：

```text
DeepSeekGateway 只负责安全、可追溯、可限流地调用 DeepSeek；AIReview 才负责复盘业务，实时交易链路永远不消费大模型结论。
```
