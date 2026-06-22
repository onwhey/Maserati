# RiskCheck 需求

## 1. 模块定位

RiskCheck 是 CandidateOrderIntent 进入执行准备前的强制风控审批层。

正式链路：

```text
OrderPlan
→ CandidateOrderIntent
→ RiskCheck
→ RiskCheckResult
→ ApprovedOrderIntent
→ ExecutionPreparation
```

RiskCheck 只审批 OrderPlan 已经生成的候选订单，不制定策略目标，不生成订单，不修改订单数量。

## 2. 核心原则

```text
只消费 CandidateOrderIntent；
所有规则通过插件注册；
正式结果只有 ALLOW / DENY / BLOCKED / FAILED；
不缩单、不改数量、不拆单；
不生成新的 CandidateOrderIntent；
只允许选择 OrderPlan 已经生成的 primary 或 fallback_reduce_only；
ALLOW 才能生成 ApprovedOrderIntent；
所有正式结果必须写 AlertEvent；
不访问 Binance；
不修改杠杆、保证金模式或持仓模式。
```

## 3. 负责事项

RiskCheck 负责：

```text
校验 CandidateOrderIntent、OrderPlan 和 ActiveLock；
校验直接业务输入绑定；
校验 BinanceSyncRun、账户、余额、持仓和交易规则；
校验 PriceSnapshot；
按 order_components 分段评估增加风险和降低风险部分；
按 USDS-M / COIN-M 使用不同保证金计算器；
检查余额、保证金、数量、名义和交易规则；
执行当前 risk_rule_set 内全部 active + enabled RiskRulePlugin；
汇总 RiskRuleResult；
生成 RiskCheckResult；
选择 primary 或预生成 fallback_reduce_only；
ALLOW 时生成 ApprovedOrderIntent；
调用 OrderPlanActiveLockService 推进锁生命周期；
保留规则版本、配置、计算结果和中文证据。
```

## 4. 不负责事项

RiskCheck 不负责：

```text
读取 StrategySignal 或重新判断行情；
读取 DecisionSnapshot 动作枚举；
制定 target_position_ratio；
生成或修改 OrderPlan；
缩小 CandidateOrderIntent；
改变 side、数量、reduce_only 或订单类型；
临时生成 fallback；
刷新账户或价格快照；
请求 Binance；
准备或提交订单；
查询订单或成交；
直接修改 ActiveLock；
调用 Hermes；
调用大模型；
执行报单前实时价格检查或 1% price guard。
```

## 5. 输入合同

正式输入至少包括：

```text
business_request_key
order_plan_id
candidate_order_intent_id
binance_sync_run_id
price_snapshot_id
active_lock_id
reference_time_utc
risk_rule_set
risk_config
trace_id
trigger_source
```

必须确认 business_request_key 合法，且所有直接业务输入的 market_type、account_domain、symbol 和真实外键关系一致。

risk_rule_set 是本次风控审批允许执行的规则集合边界。RiskCheck 不得把其他规则集中的规则混入当前审批，也不得因为某条规则处于 active 状态就跨规则集执行。

RiskCheck 不接受 DecisionSnapshot 直接触发，也不接受 `ENTER_LONG / ENTER_SHORT / EXIT / HOLD / NO_TRADE` 等动作字段。

## 6. CandidateOrderIntent 校验

必须校验：

```text
CandidateOrderIntent 存在；
status = pending_risk_check；
来自当前 OrderPlan；
intent_role 合法；
intent_hash 可验证；
side、position_side、order_type 和 requested_size 合法；
requested_size 已按 symbol rule 规范化；
order_components 完整且汇总一致；
price_snapshot_id 和 binance_sync_run_id 与 OrderPlan 一致；
没有被取消、过期、废弃或消费。
```

结构或追溯失败必须 `BLOCKED`，不得尝试修复。

## 7. ActiveLock 校验

RiskCheck 必须确认当前 ActiveLock：

```text
status = active；
绑定当前 OrderPlan；
exchange、market_type、account_domain、symbol 一致。
```

RiskCheck 不得扫描多张业务表猜测是否存在其他活动订单。ActiveLock 是统一门锁。

锁缺失、属于其他 OrderPlan、状态异常或身份不一致时必须 `BLOCKED`。

## 8. 账户事实合同

RiskCheck 必须使用 OrderPlan 已经绑定的同一个 `BinanceSyncRun`，不得选择其他批次。

必须校验：

```text
status = succeeded；
sync_purpose = trade_preparation；
批次未过期；
snapshot_set_hash 可验证；
账户、余额、持仓和 symbol rule 完整；
position_mode = one_way；
市场身份一致。
```

不得回退 latest succeeded，不得使用 ops_display 批次。

## 9. PriceSnapshot 合同

RiskCheck 必须使用 OrderPlan 明确引用的 PriceSnapshot。

必须校验：

```text
price_type = mark_price；
price_snapshot_id 与 OrderPlan 一致；
mark_price 大于零；
price_snapshot_hash 可验证；
reference_time_utc 未超过 expires_at_utc；
市场身份一致。
```

RiskCheck 不维护独立 TTL，不刷新价格，不允许使用另一 PriceSnapshot 重新审批同一个候选订单。

PriceSnapshot 在 RiskCheck 中只用于估值、保证金、交易规则和审计证据，不代表最终报单价格或成交价格。

RiskCheck 不执行报单前实时市场价格查询，也不比较实时价格与本周期 mark price 的偏离。该检查属于 ExecutionPreparation。

## 10. order_components

每个 CandidateOrderIntent 必须包含可验证的 order_components。

规则结果按组件评估，但最终审批对象仍是完整 CandidateOrderIntent。

### 10.1 reduce_risk

至少检查：

```text
当前持仓存在且方向一致；
关闭数量不超过当前持仓；
数量满足 step_size、min_quantity、max_quantity 和 min_notional；
组件汇总与 CandidateOrderIntent 一致；
reduce-only 语义与整笔订单一致。
```

纯 reduce_risk 组件不因 `observed_exchange_leverage` 缺失而阻断，也不按新增仓位计算保证金。

### 10.2 increase_risk

至少检查：

```text
可用余额；
新增保证金；
observed_exchange_leverage；
交易所最大数量和最大名义；
symbol rule；
风险配置上限。
```

## 11. 不允许 MODIFY

RiskCheck 禁止：

```text
把 BUY 1.0 改成 BUY 0.8；
自动截断数量；
保留部分组件；
拆分成多笔订单；
改变订单方向；
改变 reduce_only；
生成新的候选订单。
```

候选订单超过风险约束时返回 `DENY`，不返回缩单建议。

## 12. 净额反手与 fallback

净额反手时，OrderPlan 可以同时生成：

```text
primary：平旧方向并开新方向；
fallback_reduce_only：只平旧方向，不开新方向。
```

选择规则：

```text
primary 全部通过 → ALLOW primary；
primary 的 increase_risk 部分不通过，但 fallback 全部通过 → ALLOW fallback；
fallback 也不通过 → DENY / BLOCKED / FAILED。
```

fallback 必须在 RiskCheck 前已经存在。RiskCheck 只能选择，不能生成或修改。

选择 fallback 必须写 AlertEvent，明确说明完整反手未获批准，仅批准降低旧方向风险。

fallback 失败分类：

```text
持仓方向、持仓数量或账户快照与候选订单不匹配 → BLOCKED；
快照完整且可判断，但 fallback 违反数量、名义或交易规则 → DENY；
缺少判断 fallback 所需的账户、持仓、价格或 symbol rule 字段 → BLOCKED；
插件执行、数据库事务或不可预期系统异常 → FAILED。
```

## 13. 状态语义

```text
ALLOW：输入完整，全部强制规则通过，可以生成 ApprovedOrderIntent。
DENY：输入完整且可判断，但明确违反风险限制。
BLOCKED：输入、快照、结构或前置事实不完整，无法安全判断。
FAILED：代码、数据库或不可预期系统异常。
```

`DENY / BLOCKED / FAILED` 均不得生成 ApprovedOrderIntent。

## 14. USDS-M 保证金检查

只对 increase_risk 组件计算：

```text
opening_notional_quote
= opening_quantity * mark_price

margin_required_quote
= opening_notional_quote / observed_exchange_leverage
```

必须比较同一 BinanceSyncRun 中 quote asset 的 `available_balance`，并应用配置化安全缓冲。

存在 increase_risk 组件时，observed_exchange_leverage 缺失、非正数或无法验证必须 `BLOCKED`。

## 15. COIN-M 保证金检查

```text
opening_notional_usd
= opening_contracts * contract_size

margin_required_native
= opening_notional_usd / mark_price / observed_exchange_leverage
```

必须使用同一 BinanceSyncRun 中对应 settlement / margin asset 的可用余额。

以下任一缺失且存在 increase_risk 组件时必须 `BLOCKED`：

```text
contract_size
mark_price
margin_asset
available_balance_native
observed_exchange_leverage
```

不得复用 USDS-M 线性公式。

## 16. market calculator

必须为 USDS-M 和 COIN-M 使用独立 calculator，并可共享无市场语义的 Decimal helper。

共享 helper 不得：

```text
决定风控结果；
访问数据库或外部服务；
写 AlertEvent；
承载 rule_code 分发。
```

## 17. symbol rule 复核

RiskCheck 必须重新验证 OrderPlan 已规范化的数量：

```text
step_size
quantity_precision
min_quantity
max_quantity
min_notional
max_notional（如交易所提供）
contract_size（COIN-M）
supported_order_types
```

RiskCheck 只验证，不重新取整或修改数量。

数据完整但违反规则 → `DENY`。规则字段缺失或快照不一致 → `BLOCKED`。

### 17.1 交易所最大可承接能力边界

RiskCheck P0 只检查当前候选订单是否满足余额、保证金估算、交易所数量上限、交易所名义上限和 symbol rule。

RiskCheck 不计算“交易所最多还能开多少”的精确可开能力，也不把候选订单自动缩小到交易所可接受的最大数量。

如果候选订单超过交易所规则或余额、保证金约束：

```text
事实完整且可判断 → DENY；
事实缺失、快照不一致或无法安全判断 → BLOCKED。
```

## 18. RiskRuleDefinition

风控规则必须配置化、版本化。

至少记录：

```text
rule_code
rule_version
algorithm_name
algorithm_version
params
params_hash
definition_hash
status
enabled
severity
execution_order
applicable_market_types
created_at_utc
updated_at_utc
```

生命周期：

```text
draft
active
deprecated
retired
disabled
```

生产只执行当前 risk_rule_set 内的 `active + enabled` 规则。已用于生产的规则不得原地修改算法身份或参数；变化必须创建新版本并保留历史。

## 19. Plugin 架构

必须保留：

```text
RiskRulePlugin
RiskRuleRegistry
RuleEngine
RiskRuleResult
RiskCheckIssue
```

规则：

```text
原则上一个 RiskRulePlugin 一个文件；
rule_code 与文件和注册名保持可读对应；
Registry 负责 rule_code → plugin；
RuleEngine 不使用大型 if / elif / switch 分发规则；
plugin 不写数据库、不访问 Binance、不生成 ApprovedOrderIntent；
plugin 只返回结构化 RiskRuleResult；
plugin 可以使用只读 context 和 shared calculator；
找不到 active rule 对应 plugin 时必须 BLOCKED 或 FAILED；
所有实际执行的规则版本必须进入 rule_set_hash。
```

新增规则只需增加定义、plugin、注册、中文说明和测试，不得修改 RuleEngine 主流程。

## 20. RiskRuleResult

单条规则结果至少支持：

```text
PASS
DENY
BLOCKED
FAILED
```

至少记录：

```text
rule_code
rule_version
status
severity
reason_code
message_zh
risk_measures
evidence
definition_hash
params_hash
started_at_utc
finished_at_utc
```

## 21. RuleEngine 聚合

RuleEngine 必须执行当前 risk_rule_set 内全部适用的 active + enabled 规则，除非输入已经严重损坏到无法构建安全 context。

RuleEngine 不得跨 risk_rule_set 自动补充规则，也不得用全局 active 规则替代当前审批明确指定的规则集合。

聚合原则：

```text
存在 FAILED → 最终 FAILED；
否则存在 BLOCKED → 最终 BLOCKED；
否则存在 DENY → 最终 DENY；
否则全部规则 PASS → ALLOW。
```

## 22. 当前规则插件

至少包括：

```text
candidate_intent_valid
order_plan_valid
order_components_valid
business_input_binding_valid
binance_sync_run_consumable
snapshot_integrity
market_identity_consistency
one_way_position_mode_required
active_lock_consistency
price_snapshot_present
price_snapshot_fresh
usds_m_balance_available
coin_m_balance_available
symbol_rule_min_notional
symbol_rule_quantity_step
symbol_rule_max_quantity
symbol_rule_max_notional
available_margin_check
reverse_fallback_reduce_only
```

后续规则必须通过同一插件机制扩展。

## 23. RiskCheckResult

至少记录：

```text
id
business_request_key
risk_check_key
status
is_usable
allows_downstream
selected_candidate_order_intent_id
selected_intent_role
order_plan_id
primary_candidate_order_intent_id
fallback_candidate_order_intent_id
binance_sync_run_id
binance_snapshot_set_hash
account_snapshot_id
balance_snapshot_ids
position_snapshot_id
symbol_rule_snapshot_id
price_snapshot_id
price_snapshot_hash
active_lock_id
rule_set_hash
checked_rules
risk_measures
risk_config_snapshot
input_snapshot
risk_snapshot
evidence_items
evidence_text_zh
reason_code
error_code
error_message
alert_event_ids
trace_id
trigger_source
created_at_utc
```

`risk_measures` 至少记录：

```text
current_equity
available_balance
order_notional
requested_size
margin_required_total
margin_required_by_component
observed_exchange_leverage
estimated_leverage_after_order
is_risk_reducing_total
has_increase_risk_component
price_snapshot_id
mark_price
market_type
margin_asset
```

COIN-M 还必须记录：

```text
contract_size
current_equity_native
current_equity_usd
margin_required_native
available_balance_native
```

## 24. ApprovedOrderIntent

只有 `ALLOW` 可以生成 ApprovedOrderIntent。

ApprovedOrderIntent 必须：

```text
引用 RiskCheckResult；
引用实际被批准的 CandidateOrderIntent；
冻结被批准候选的 side、数量、单位、reduce_only、order_type 和组件摘要；
保留账户、价格、规则集和 hash 追溯；
具有明确状态和有效期；
不能在生成后修改订单核心参数。
```

ApprovedOrderIntent 不是交易所订单，不能绕过 ExecutionPreparation。

## 25. ActiveLock 推进

RiskCheck 不直接修改 ActiveLock，只调用 OrderPlanActiveLockService。

```text
ALLOW → 锁保持 active；
DENY → 未生成 ApprovedOrderIntent，调用服务释放锁；
BLOCKED → 未生成 ApprovedOrderIntent，调用服务释放锁；
FAILED → 若事务确认未生成 ApprovedOrderIntent 且未进入执行准备，可以释放；无法确认时锁保持阻断或 failed，等待人工处理。
```

## 26. 幂等

幂等键至少包含：

```text
business_request_key
candidate_order_intent_id
order_plan_id
binance_sync_run_id
binance_snapshot_set_hash
price_snapshot_id
price_snapshot_hash
rule_set_hash
risk_config_hash
```

相同输入重复执行必须返回已有 RiskCheckResult，不重复生成 ApprovedOrderIntent、规则结果或等价 AlertEvent。

同一 CandidateOrderIntent 只能使用 OrderPlan 已引用的 PriceSnapshot，不允许换价格重新审批。

## 27. dry-run

dry-run 必须执行与正式流程相同的输入校验、插件执行、保证金计算和结果聚合，但：

```text
不写 RiskCheckResult；
不写 RiskRuleResult / RiskCheckIssue；
不生成 ApprovedOrderIntent；
不修改 ActiveLock；
不写正式 AlertEvent；
不修改数据库；
只返回结构化风控摘要。
```

dry-run 结果不得进入 ExecutionPreparation。

## 28. AlertEvent

每次正式检查都必须写 AlertEvent：

```text
ALLOW
DENY
BLOCKED
FAILED
fallback_reduce_only selected
ApprovedOrderIntent generated
```

Alert 必须明确这是风控审批结果，不得写成交易已经提交或成交。

## 29. 配置

所有配置必须进入 `.env.example` 并带中文注释：

```text
RISK_CHECK_ENABLED
RISK_CHECK_RULE_SET
RISK_CHECK_MARGIN_BUFFER_RATIO
RISK_CHECK_RULE_FAILURE_MODE
RISK_CHECK_APPROVED_INTENT_TTL_SECONDS
```

具体规则参数保存于版本化 RiskRuleDefinition，不得散落在 RuleEngine 或 task 中。

## 30. 数据与外部服务

```text
读写 MySQL：是。
访问 Redis：非必需，不作为风控事实来源。
访问 Binance：否。
发送 Hermes：不直接发送，只写 AlertEvent。
调用大模型：否。
涉及交易执行：审批候选意图，不提交订单。
允许真实交易：否。
```

## 31. 规则说明文档

每个生产 RiskRulePlugin 必须有独立中文说明，至少包含：

```text
用途
输入和依赖字段
适用市场域
参数与版本
计算逻辑
PASS / DENY / BLOCKED / FAILED 边界
reason_code
风险度量
AlertEvent 语义
测试场景
禁止事项
```

## 32. 测试要求

至少覆盖：

```text
1. 只消费 CandidateOrderIntent。
2. OrderPlan、账户和价格通过直接业务 ID 绑定正确。
3. 市场身份或业务外键不一致时 BLOCKED。
4. ActiveLock 必须 active 且绑定当前 OrderPlan。
5. PriceSnapshot 过期 BLOCKED 且不刷新。
6. ops_display 账户批次不可消费。
7. Candidate hash 或组件结构错误 BLOCKED。
8. RiskCheck 不修改 side、数量、reduce_only 或订单类型。
9. 违反风险上限时 DENY，不缩单。
10. primary 全部通过时选择 primary。
11. primary 新增风险不通过、fallback 通过时选择 fallback。
12. fallback 不是 RiskCheck 临时生成。
13. increase_risk 缺 leverage 时 BLOCKED。
14. reduce_risk 不因 leverage 缺失阻断。
15. USDS-M 保证金计算正确。
16. COIN-M 原生保证金计算正确。
17. COIN-M 缺 contract_size BLOCKED。
18. symbol rule 违反时 DENY，缺字段时 BLOCKED。
19. RuleRegistry 正确查找 plugin。
20. 缺少 plugin 时不放行。
21. RuleEngine 不包含具体 rule_code 分支。
22. 多条插件结果按优先级聚合。
23. ALLOW 生成唯一 ApprovedOrderIntent。
24. DENY / BLOCKED / FAILED 不生成 ApprovedOrderIntent。
25. ApprovedOrderIntent 核心参数等于被选 Candidate。
26. ALLOW 保持锁 active。
27. DENY / BLOCKED 安全释放锁。
28. FAILED 无法确认时锁继续阻断。
29. risk_measures 包含保证金、余额、名义和估算杠杆审计字段。
30. dry-run 执行相同规则但不写库、不告警、不生成 ApprovedOrderIntent。
31. 相同输入幂等执行不重复写结果或告警。
32. 测试不访问 Binance、不提交订单。
33. 只执行当前 risk_rule_set 内 active + enabled 规则，不混入其他规则集。
34. RiskCheck 不刷新 PriceSnapshot，不查询实时价格，不执行 1% price guard。
35. 候选订单超过交易所数量或名义上限时 DENY，不自动缩小订单。
36. 缺少判断 fallback 所需事实时 BLOCKED，规则明确违反时 DENY，系统异常时 FAILED。
```

## 33. 验收标准

```text
插件架构可注册、版本化、审计和独立测试；
新增规则不需要修改 RuleEngine 主流程；
RiskCheck 只审批既有 CandidateOrderIntent；
RiskCheck 不缩单、不改数量、不生成订单；
primary 与 fallback 的选择可追溯；
账户、价格和规则事实均来自 OrderPlan 明确引用的业务对象；
风控规则只来自当前 risk_rule_set；
USDS-M 与 COIN-M 使用正确保证金口径；
所有正式结果写 AlertEvent；
只有 ALLOW 生成 ApprovedOrderIntent；
ApprovedOrderIntent 不能绕过 ExecutionPreparation；
模块不访问 Binance，不修改交易所配置，不执行交易。
```

## 34. 当前不包含的能力

```text
任意 MODIFY；
自动缩单；
自动拆单；
风控主动生成减仓订单；
动态仓位上限回写 OrderPlan；
自动调杠杆；
自动改保证金模式；
精确计算交易所最大可开能力；
自动缩小到交易所最大可开数量；
执行前实时价格查询与 1% price guard；
跨 risk_rule_set 自动混用规则；
组合级风控；
大模型风控；
绕过 ApprovedOrderIntent 的执行路径。
```
