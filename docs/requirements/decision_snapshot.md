# DecisionSnapshot 需求说明

## 1. 模块定位

DecisionSnapshot 位于 StrategySignalQuality 之后、OrderPlan 之前。

它负责把一份质量放行的 StrategySignal 转换为不可变的目标仓位意图快照。

正式链路为：

```text
StrategySignal
→ StrategySignalQualityResult
→ DecisionSnapshot
→ TARGET_POSITION：PriceSnapshot → OrderPlan → CandidateOrderIntent
→ NO_TARGET_CHANGE / NO_TRADE：正常结束，不进入价格或订单链路
```

DecisionSnapshot 回答的问题是：

```text
在当前策略判断和决策规则下，系统理想上希望处于什么目标仓位？
如果策略提供了价格条件，本轮目标仓位应当携带哪些不可变价格条件供 OrderPlan 后续评估？
```

DecisionSnapshot 不回答：

```text
应该买还是卖；
应该开仓、平仓、加仓、减仓还是反手；
订单数量是多少；
当前账户是否有足够保证金；
当前交易所真实持仓是多少；
这组订单是否通过风控；
是否应该提交真实订单。
```

这些问题分别属于 OrderPlan、RiskCheck、ExecutionPreparation 和 Execution。

## 2. 核心边界

DecisionSnapshot 只表达目标仓位意图，不表达订单动作。

禁止输出或作为下游交易动作语义使用：

```text
ENTER_LONG
ENTER_SHORT
EXIT
HOLD
BUY
SELL
OPEN_LONG
OPEN_SHORT
CLOSE_POSITION
decision_action
order_side
order_quantity
reduce_only
close_position
leverage
交易所订单价格
stop_loss
take_profit
```

`NO_TRADE` 可以作为 DecisionSnapshot 的 `target_intent`，表示本轮不形成交易目标；但不得作为订单动作传给 RiskCheck 或 Execution。

DecisionSnapshot 不读取账户、余额、持仓、杠杆、symbol rule 或交易所订单。

因此：

```text
DecisionSnapshot 只输出目标仓位合同；
DecisionSnapshot 可以冻结 StrategySignal 已经标准化输出的交易价格条件；
OrderPlan 才读取当前持仓并生成 CandidateOrderIntent；
RiskCheck 只审批 CandidateOrderIntent；
Execution 才能提交真实订单。
```

## 3. 业务流程与算法分离

DecisionSnapshot 必须拆成两个稳定边界：

```text
DecisionSnapshotService
DecisionPolicyCalculator
```

DecisionSnapshotService 负责业务流程：

```text
接收明确的 strategy_signal_quality_result_id 和 StrategyAnalysisRelease 身份；
校验 StrategySignalQualityResult 是否允许进入决策层；
校验 StrategySignal 是否可追溯且可用；
校验版本包并读取其唯一选择的 DecisionPolicyDefinition；
构造不可变 DecisionPolicyCalculatorInput；
通过 CalculatorRegistry 精确解析 DecisionPolicyCalculator；
调用 calculator；
校验 CalculatorOutput；
生成不可变 DecisionSnapshot；
处理幂等、并发、unknown 和恢复；
写入必要 AlertEvent；
向编排 adapter 返回业务结果。
```

DecisionPolicyCalculator 负责纯计算：

```text
读取 CalculatorInput DTO；
读取 CalculatorInput 中唯一的 frozen_params；
把 StrategySignal 的方向、强度、置信评分和质量结果映射为目标仓位意图；
输出 target_intent；
输出 target_position_ratio；
输出 target_confidence；
输出 target_reason_code；
冻结 StrategySignal.trade_price_condition；
输出结构化证据和计算摘要；
输出可判定的计算失败。
```

DecisionPolicyCalculator 不负责：

```text
读取数据库；
读取 Redis；
读取 env；
读取当前时间；
读取账户或持仓；
读取 PriceSnapshot；
请求 Binance；
调用 DeepSeek；
生成订单；
写 AlertEvent；
决定业务 status；
处理幂等或事务。
```

算法后续可以替换，但必须通过新的 `algorithm_version`、新的参数或新的 DecisionPolicyDefinition 表达，不得修改稳定业务流程。

正式版本包选择、批准、启用、切换、回滚和后台研究隔离统一遵守 [StrategyAnalysisRelease](strategy_analysis_release.md)。后台研究可以自由组合 DecisionPolicyDefinition，但结果不得写入正式 DecisionSnapshot，也不得调用正式服务的绕过入口。

## 4. 正式消费合同

DecisionSnapshot 的正式入口必须接收明确的 `strategy_signal_quality_result_id`、本轮 `strategy_analysis_release_id` 和 `strategy_analysis_release_hash`。

不得跳过 StrategySignalQuality 直接消费 StrategySignal。

正式入口只允许消费：

```text
StrategySignalQualityResult.status = created；
StrategySignalQualityResult.is_usable = true；
StrategySignalQualityResult.allows_decision_snapshot = true；
StrategySignalQualityResult.quality_status = passed 或被配置允许的 warning；
StrategySignal.status = created；
StrategySignal.is_usable = true；
StrategySignal.allows_strategy_signal_quality = true；
DecisionPolicyDefinition.status = active；
DecisionPolicyDefinition.enabled = true；
StrategySignalQualityResult、StrategySignal 和 DecisionPolicyDefinition 属于同一 StrategyAnalysisRelease；
版本包唯一选择的 DecisionPolicyDefinition definition_hash 与本轮冻结值一致。
```

以下情况必须 fail-closed：

```text
StrategySignalQualityResult 缺失；
质量结果不允许进入 DecisionSnapshot；
质量结果来自 dry-run；
StrategySignal 缺失；
StrategySignal 不可用；
StrategySignal 来自后台研究或其他版本包；
StrategyAnalysisRelease 不存在、未批准、未启用或 release_hash 不一致；
DecisionPolicyDefinition 缺失；
DecisionPolicyDefinition disabled、retired 或 hash 不一致；
DecisionPolicyCalculator 缺失精确 algorithm_name + algorithm_version；
版本包缺少 DecisionPolicyCalculator 的文档、代码和测试一致性验证证据。
```

## 5. 目标仓位意图合同

### 5.1 target_intent

`target_intent` 必填。

允许值：

```text
TARGET_POSITION
NO_TARGET_CHANGE
NO_TRADE
```

### 5.2 TARGET_POSITION

表示决策规则明确提出一个目标总仓位比例。

当：

```text
target_intent = TARGET_POSITION
```

必须满足：

```text
target_position_ratio 必填；
-1.0 <= target_position_ratio <= +1.0。
```

语义：

```text
+1.0 = 目标满额多头；
+0.5 = 目标半额多头；
 0.0 = 目标空仓；
-0.5 = 目标半额空头；
-1.0 = 目标满额空头。
```

`target_position_ratio = 0.0` 表示目标空仓。

它不是“卖出动作”，也不是“平仓动作”。如果当前账户有持仓，后续是否生成平仓或减仓订单由 OrderPlan 根据账户持仓快照计算。

### 5.3 NO_TARGET_CHANGE

表示本轮决策规则不提出新的目标仓位变化。

当：

```text
target_intent = NO_TARGET_CHANGE
```

必须满足：

```text
target_position_ratio 为空。
```

它不等于目标空仓。

它的业务含义是：

```text
本轮不基于该 DecisionSnapshot 生成新的 PriceSnapshot、OrderPlan 或订单链路；
本轮自动账户边界事实已在编排起始阶段保存，不由 DecisionSnapshot 触发账户同步。
```

### 5.4 NO_TRADE

表示本轮信号不足、质量边界不满足、策略冲突或决策规则明确要求不进入交易链路。

当：

```text
target_intent = NO_TRADE
```

必须满足：

```text
target_position_ratio 为空。
```

它不等于目标空仓，也不得传递为订单动作。

它的业务含义是：

```text
本轮不进入 PriceSnapshot / OrderPlan / CandidateOrderIntent / RiskCheck / Execution；
本轮自动账户边界事实已在编排起始阶段保存，不由 DecisionSnapshot 触发账户同步。
```

如果 NO_TRADE 来自正常策略判断，它是正常终止状态，不是系统失败。

账户同步由编排衔接器在自动编排起始阶段调用，不是 DecisionSnapshot 的直接下游调用。DecisionSnapshot 不读取账户事实，也不因账户同步结果改变已经形成的目标意图。

## 6. DecisionPolicyDefinition

DecisionPolicyDefinition 是目标仓位映射规则的版本化业务定义。

DecisionPolicyDefinition 只能表达“标准化 StrategySignal → 目标仓位意图”的统一转换规则，不得承担市场分析、策略分类或策略类型分支职责。

DecisionSnapshot 不区分趋势策略、震荡策略、突破策略、防守策略或其他策略类型。所有策略差异必须在 StrategySignal 层输出前完成标准化。DecisionPolicyDefinition 不得按 `strategy_code`、`strategy_version`、MarketRegime、策略类型或路由结果选择不同仓位映射。

建议字段：

```text
id
policy_code
policy_version
display_name
description
algorithm_name
algorithm_version
input_schema_version
output_schema_version
target_schema_version
params
params_hash
definition_hash
status
enabled
created_at_utc
updated_at_utc
```

`status = active` 与 `enabled = true` 只表示 DecisionPolicyDefinition 在目标仓位算法库中可供选择，不表示自动进入正式运行。

正式参与资格必须同时满足：

```text
被本轮 StrategyAnalysisRelease 唯一选择；
Definition 为 active 且 enabled；
definition_hash 与版本包冻结值一致；
对应 DecisionPolicyCalculator、算法需求文档、implementation 实现记录和输入输出合同完整；
与本轮 StrategySignalQualityRuleSet 和标准化 StrategySignal 输出合同兼容。
```

算法库可以同时存在多个 active、enabled 的 DecisionPolicyDefinition；正式服务不得按最新版本、全局 active 状态或调用参数自行选择。

`policy_code + policy_version` 表达一套业务决策规则。

`algorithm_name + algorithm_version` 表达具体 DecisionPolicyCalculator 算法身份。

`params` 表达该算法所需的冻结参数，例如：

```text
min_strength_for_target；
min_confidence_for_target；
neutral_intent_policy；
weak_signal_intent_policy；
max_abs_target_position_ratio；
target_scale_method；
target_confidence_method；
target_flat_reason_codes；
expires_after_seconds。
```

参数含义和公式必须由对应算法需求文档定义。

params 禁止包含以下策略分支配置：

```text
按 strategy_code 设置不同 target_position_ratio；
按 strategy_version 设置不同缩放规则；
按 MarketRegime 设置不同仓位映射；
按 StrategyRouteDecision 或 RouteRule 设置不同仓位映射；
按策略类型设置趋势 / 震荡 / 突破 / 防守专用转换规则。
```

DecisionPolicyDefinition 禁止包含：

```text
当前账户权益；
当前持仓；
当前价格；
当前订单；
BinanceSyncRun；
PriceSnapshot；
风控审批结果；
Execution 结果；
实时复盘输出；
实时价格；
交易所订单类型；
编排 ID；
当前时间。
```

## 7. DecisionPolicyCalculator 合同

DecisionPolicyCalculator 的 `calculator_type` 为：

```text
decision_policy
```

Calculator metadata 必须遵守 [StrategyCalculator 公共合同](strategy_calculator.md)，声明 `calculator_type = decision_policy`、`algorithm_requirement_document_path` 和 `implementation_document_path`。

输入 DTO 只能包含已经由 DecisionSnapshotService 校验并冻结的事实：

```text
strategy_signal_id；
strategy_signal_quality_result_id；
strategy_direction；
strategy_strength；
strategy_confidence；
confidence_semantics；
prediction_horizon；
quality_status；
quality_issue_summary；
market_as_of_utc / analysis_close_time_utc；
target_schema_version；
必要的小型结构化证据摘要；
schema identity。
```

`strategy_code`、`strategy_version`、`algorithm_name`、`algorithm_version` 可以作为审计字段由 Service 写入 DecisionSnapshot，但不得作为 DecisionPolicyCalculator 的分支输入。

输入 DTO 不得包含：

```text
账户余额；
当前持仓；
当前价格；
PriceSnapshot；
BinanceSyncRun；
BinancePositionSnapshot；
订单；
成交；
风控结果；
Execution 结果；
MarketRegimeSnapshot 作为二次加权输入；
交易所订单类型；
实时价格；
DomainSignalValue 作为二次加权输入；
StrategyRouteDecision 作为分支输入；
strategy_code 或 strategy_version 作为分支输入；
AtomicSignalValue；
FeatureValue；
Kline。
```

Calculator 输出：

```text
target_intent；
target_position_ratio；
target_confidence；
target_reason_code；
target_reason_summary_zh；
decision_calculation_snapshot；
evidence_items；
error_code；
error_message。
```

StrategySignal.trade_price_condition 不由 DecisionPolicyCalculator 重新计算。正式服务可以在 StrategySignalQuality 放行后把该价格条件原样冻结进 DecisionSnapshot，用于后续 OrderPlan 评估；如果上游未提供，则冻结为空。

Calculator 约束：

```text
不得读取当前时间；
不得读取数据库；
不得请求 Binance；
不得调用 DeepSeek；
不得重新执行 StrategySignal；
不得再次使用 DomainSignal 或 MarketRegime 加权；
不得按 strategy_code、strategy_version、MarketRegime、StrategyRouteDecision 或策略类型分支；
不得输出订单动作；
不得输出业务 status；
不得输出 unknown；
不得写库或写 AlertEvent。
```

## 8. P0 映射规则边界

P0 阶段允许使用简单、可验证、可替换的规则映射。

典型规则形态：

```text
bullish 且 strength / confidence 满足阈值
→ TARGET_POSITION，target_position_ratio 为正；

bearish 且 strength / confidence 满足阈值
→ TARGET_POSITION，target_position_ratio 为负；

neutral
→ NO_TRADE 或 NO_TARGET_CHANGE，由 DecisionPolicyDefinition.params 决定；

strength 或 confidence 不满足阈值
→ NO_TRADE 或 NO_TARGET_CHANGE，由 DecisionPolicyDefinition.params 决定；

StrategySignal 结构化 reason_code 命中 target_flat_reason_codes
→ TARGET_POSITION，target_position_ratio = 0.0。
```

仓位比例可以使用线性缩放、分段缩放、阶梯缩放或其他确定性方法，但必须满足：

```text
具体公式写在算法需求文档；
输出范围限制在 [-1.0, +1.0]；
不把 strength 或 confidence 直接解释为仓位；
不把 confidence 解释为盈利概率；
不读取当前账户或持仓；
不根据近期收益在线调参。
```

DecisionPolicyCalculator 只消费标准化 StrategySignal 输出。若某个策略的 `direction / strength / confidence / prediction_horizon` 不能被统一映射规则正确解释，说明该策略的 StrategySignal 输出合同不合格，不得进入正式 StrategyAnalysisRelease；不得让 DecisionSnapshot 根据策略类型补做解释。

DecisionSnapshot 永远不得使用 MarketRegime 或 DomainSignal 作为目标仓位调节输入。若未来确实需要让市场环境影响仓位，应在 StrategySignal 层完成标准化输出，或新增独立需求重新划分职责；不得把二次市场分析放入 DecisionSnapshot。

## 9. DecisionSnapshot 对象

DecisionSnapshot 是不可变目标仓位快照。

建议字段：

```text
id
decision_snapshot_key
strategy_signal_id
strategy_signal_quality_result_id
decision_policy_definition_id
strategy_analysis_release_id
strategy_analysis_release_hash
policy_code
policy_version
algorithm_name
algorithm_version
params_hash
definition_hash
target_schema_version
target_intent
target_position_ratio
target_confidence
target_reason_code
target_reason_summary_zh
frozen_trade_price_condition
decision_calculation_snapshot
input_snapshot
evidence_summary
market_as_of_utc
analysis_close_time_utc
expires_at_utc
status
is_usable
allows_order_plan
blocked_reason
error_code
error_message
created_at_utc
updated_at_utc
business_request_key
trace_id
trigger_source
```

状态允许：

```text
created
blocked
failed
unknown
```

放行规则：

```text
created + TARGET_POSITION + is_usable = true + allows_order_plan = true
→ OrderPlan 可以消费；

created + NO_TARGET_CHANGE
→ 允许编排正常终止，不进入 PriceSnapshot 或 OrderPlan；

created + NO_TRADE
→ 允许编排正常终止，不进入 PriceSnapshot 或 OrderPlan；

blocked / failed / unknown
→ 不进入 OrderPlan。
```

`allows_order_plan` 只允许在以下条件同时满足时为 true：

```text
status = created；
target_intent = TARGET_POSITION；
target_position_ratio 合法；
DecisionSnapshot 未过期；
is_usable = true。
```

## 10. 输入快照与证据

`input_snapshot` 必须包含：

```text
StrategySignal 引用；
StrategySignalQualityResult 引用；
StrategySignal direction / strength / confidence / confidence_semantics；
prediction_horizon；
quality_status；
quality issue summary；
DecisionPolicyDefinition identity；
algorithm_name / algorithm_version；
params_hash；
source lineage hash；
market_as_of_utc / analysis_close_time_utc。
```

`input_snapshot` 不得包含：

```text
当前账户持仓；
账户余额；
BinancePositionSnapshot；
BinanceSyncRun；
PriceSnapshot；
订单；
成交；
风控结果。
```

`evidence_summary` 必须说明：

```text
为什么生成该 target_intent；
为什么得到该 target_position_ratio；
是否携带 StrategySignal 的价格条件，价格条件来自哪些策略证据；
使用了哪个 policy 和算法版本；
哪些质量结果被消费；
有哪些边界被触发。
```

不得只依赖自然语言摘要；结构化证据必须可复算。

## 11. 幂等与并发

`decision_snapshot_key` 至少基于：

```text
strategy_signal_quality_result_id
decision_policy_definition_id
definition_hash
params_hash
target_schema_version
target_intent
target_position_ratio
target_confidence
target_reason_code
frozen_trade_price_condition_hash
market_as_of_utc / analysis_close_time_utc
```

不得包含：

```text
当前持仓；
账户余额；
PriceSnapshot；
BinanceSyncRun；
订单；
decision_action；
编排 ID；
当前时间；
Celery task id。
```

并发要求：

```text
使用数据库唯一约束保护 decision_snapshot_key；
在事务中原子写入 DecisionSnapshot 和必要 AlertEvent；
可使用 Redis 短期锁降低并发冲突；
Redis 锁失效不得破坏数据库唯一性；
事务中不得访问外部服务。
```

同一质量结果、同一决策规则和同一冻结输入重复执行，必须返回同一 DecisionSnapshot 或等价幂等摘要。

## 12. 过期与生命周期

DecisionSnapshot 必须包含：

```text
market_as_of_utc
analysis_close_time_utc
expires_at_utc
status
is_usable
allows_order_plan
```

`expires_at_utc` 的计算规则由 DecisionPolicyDefinition 或业务配置定义，但必须冻结进快照。

过期的 DecisionSnapshot 不得被 OrderPlan 消费。

如果下游尝试消费过期 DecisionSnapshot，必须 fail-closed，并写入 AlertEvent；dry-run 除外。

不得仅因为 DecisionSnapshot 过期就对同一 StrategySignalQualityResult 重复生成新快照。新的分析周期应产生新的 StrategySignal 和质量结果。

## 13. unknown 与恢复

当持久化结果无法确认时，DecisionSnapshotService 可以返回 `unknown`。

unknown 处理规则：

```text
不得假设写入失败；
不得立即重新调用 DecisionPolicyCalculator；
必须先按 business_request_key 查询；
必须再按 decision_snapshot_key 查询；
核对 StrategySignalQualityResult、DecisionPolicyDefinition、params_hash 和目标仓位合同；
无法确认时保持 unknown，并写 AlertEvent；
受控恢复可以重新核验，但不得覆盖已有 created 结果。
```

Calculator 不得返回 unknown。

## 14. OrderPlan 消费合同

OrderPlan 只允许消费：

```text
DecisionSnapshot.status = created；
DecisionSnapshot.is_usable = true；
DecisionSnapshot.allows_order_plan = true；
DecisionSnapshot.target_intent = TARGET_POSITION；
DecisionSnapshot.target_position_ratio 非空；
DecisionSnapshot 未过期。
```

OrderPlan 不得基于以下 DecisionSnapshot 生成 CandidateOrderIntent：

```text
target_intent = NO_TARGET_CHANGE；
target_intent = NO_TRADE；
blocked；
failed；
unknown；
dry-run 内存结果；
过期快照。
```

OrderPlan 可以读取 `target_position_ratio` 和已冻结的 `frozen_trade_price_condition`，但不得重新解释 StrategySignal 或重新执行 DecisionPolicyCalculator。

`frozen_trade_price_condition` 的含义是“策略提供给订单规划评估的价格条件”，不是订单动作。OrderPlan 可以基于它和当前价格事实决定不交易、市价单、限价单或等待更好价格；DecisionSnapshot 自身不得决定订单类型。

## 15. 与编排层的关系

DecisionSnapshot 是业务模块，不承担编排职责。

业务表不得保存或查询：

```text
OrchestrationRun ID；
StepRun ID；
步骤序号；
编排内部状态。
```

编排层可以通过独立关联表记录本轮编排生成的 `decision_snapshot_id`，用于整轮追溯。

`DecisionSnapshotStepAdapter` 负责：

```text
调用 DecisionSnapshotService；
理解 TARGET_POSITION、NO_TARGET_CHANGE、NO_TRADE；
理解 created、blocked、failed、unknown；
TARGET_POSITION + allows_order_plan = true → 允许编排继续 PriceSnapshot 和 OrderPlan；
NO_TARGET_CHANGE / NO_TRADE → 允许编排正常结束，不进入 PriceSnapshot 或 OrderPlan；
blocked / failed / unknown → 按统一异常规则停止并告警；
返回 decision_snapshot_id 和对象引用。
```

DecisionSnapshotStepAdapter 不得直接调用 Binance Account Sync。它只返回明确分支语义；本轮账户边界同步必须已经由 Connector 在编排起始阶段完成。

编排关联只提供整轮快捷查询，不替代业务外键。

## 16. AlertEvent

必须写 AlertEvent 的场景：

```text
decision_snapshot_blocked；
decision_snapshot_failed；
decision_snapshot_unknown；
strategy_signal_quality_missing；
strategy_signal_quality_not_allowed；
strategy_signal_missing；
decision_policy_missing；
decision_policy_unavailable；
decision_policy_calculator_missing；
decision_policy_implementation_document_missing；
decision_policy_output_invalid；
target_position_ratio_invalid；
decision_snapshot_persist_unknown；
expired_decision_snapshot_consumed。
```

默认不写高严重级别 AlertEvent 的场景：

```text
TARGET_POSITION 正常生成；
NO_TARGET_CHANGE 正常生成；
NO_TRADE 正常生成；
dry-run。
```

如果 NO_TARGET_CHANGE 或 NO_TRADE 来自质量阻断、算法失败或输入缺失，应按对应异常写 AlertEvent。

DecisionSnapshot 只写 AlertEvent，不直接发送 Hermes。

## 17. 配置规则

允许环境配置：

```text
DECISION_SNAPSHOT_SCHEMA_VERSION
DECISION_SNAPSHOT_IDEMPOTENCY_LOCK_TTL_SECONDS
DECISION_SNAPSHOT_MAX_EXECUTION_SECONDS
```

配置要求：

```text
必须有测试默认值；
必须进入 .env.example 并带中文注释；
不得通过 env 改变 target_position_ratio 公式；
不得通过 env 替换 algorithm_name / algorithm_version；
不得通过 env 选择 DecisionPolicyDefinition 或修改 expires_after_seconds；
不得通过 env 跳过 StrategySignalQuality；
不得通过 env 允许读取账户或持仓；
不得通过 env 开启真实交易。
```

阈值、缩放方式、neutral 行为、目标空仓条件等算法参数必须进入 DecisionPolicyDefinition.params，而不是运行时 env。

## 18. 算法需求文档与 implementation 实现记录

每个 DecisionPolicyCalculator 算法版本必须同时具备：

```text
算法需求文档；
implementation 实现记录。
```

算法需求文档负责定义目标仓位决策公式、输入、参数、边界、输出语义和验证要求，应放在 requirements 下的对应决策算法目录。

当前 P0 目标仓位映射算法需求文件为：

```text
docs/requirements/decision_snapshot/position_policy_v1.md
```

implementation 实现记录负责记录代码落地位置、calculator、DTO、测试入口和实现差异，路径：

```text
docs/implementation/decision_snapshot/
```

文件名：

```text
<algorithm_name>__<algorithm_version>.md
```

算法需求文档至少记录：

```text
algorithm_name；
algorithm_version；
calculator_type = decision_policy；
业务用途；
明确不负责的内容；
input schema；
output schema；
完整计算步骤；
完整公式；
params 含义；
target_intent 决定规则；
target_position_ratio 计算规则；
target_confidence 计算规则；
StrategySignal.trade_price_condition 的冻结规则；
不按 strategy_code、strategy_version、MarketRegime 或策略类型分支的证明；
neutral / weak / conflicted 处理；
target flat 处理；
边界值处理；
舍入方式；
失败条件；
错误代码；
证据结构；
防止重复计分规则；
不读取账户和持仓的证明；
golden test 向量；
验证证据；
适用边界。
```

缺少算法需求文档或 implementation 实现记录的 DecisionPolicyCalculator 不允许通过 CI、算法目录验证或 StrategyAnalysisRelease 批准。正式运行时不读取 Markdown 文件，只校验本轮冻结版本包中的验证证据和精确 calculator 身份。

## 19. dry-run 与 confirm-write

dry-run 必须：

```text
读取明确的 StrategySignalQualityResult；
执行与正式模式相同的业务校验；
冻结相同 DecisionPolicyDefinition；
调用相同 DecisionPolicyCalculator；
校验相同输出合同；
返回完整摘要；
标记 persisted = false；
不写 DecisionSnapshot；
不写正式 AlertEvent；
不允许 OrderPlan 消费内存结果。
```

confirm-write 如提供，只控制是否落库，不得改变：

```text
DecisionPolicyDefinition；
calculator；
params；
放行标准；
过期规则；
AlertEvent 条件。
```

## 20. Management command

建议命令：

```bash
python manage.py build_decision_snapshot --strategy-signal-quality-result-id <id> --strategy-analysis-release-id <id> --strategy-analysis-release-hash <hash> --business-request-key <key> --trigger-source manual --trace-id <id>
```

建议参数：

```text
--strategy-signal-quality-result-id
--strategy-analysis-release-id
--strategy-analysis-release-hash
--business-request-key
--dry-run
--confirm-write
--trace-id
--trigger-source
```

command 只允许：

```text
解析参数；
生成或传递 trace_id；
设置 trigger_source；
调用 DecisionSnapshotService；
输出结构化结果。
```

command 不得：

```text
实现 DecisionPolicy 公式；
读取账户持仓；
读取 PriceSnapshot；
读取 Binance；
生成 OrderPlan；
接收 position_context_json。
```

## 21. 测试要求

至少覆盖：

```text
质量通过的 bullish StrategySignal → TARGET_POSITION 且 target_position_ratio > 0；
质量通过的 bearish StrategySignal → TARGET_POSITION 且 target_position_ratio < 0；
质量通过的 neutral StrategySignal → 按 policy 输出 NO_TRADE 或 NO_TARGET_CHANGE；
结构化 target_flat reason → TARGET_POSITION 且 target_position_ratio = 0.0；
strength 不满足阈值 → 按 policy 输出 NO_TRADE 或 NO_TARGET_CHANGE；
confidence 不满足阈值 → 按 policy 输出 NO_TRADE 或 NO_TARGET_CHANGE；
不同 strategy_code 但相同标准化 StrategySignal 输入 → DecisionPolicy 输出一致；
DecisionPolicyCalculator 试图按 strategy_code / strategy_version / MarketRegime / 策略类型分支 → failed 或注册校验失败；
target_position_ratio 超出 [-1.0, +1.0] → failed；
TARGET_POSITION 时 target_position_ratio 必填；
TARGET_POSITION 时允许 frozen_trade_price_condition 为空或有值，但有值时必须来自同一 StrategySignal；
NO_TARGET_CHANGE 时 target_position_ratio 为空；
NO_TRADE 时 target_position_ratio 为空；
target_position_ratio = 0.0 与 NO_TARGET_CHANGE 语义不同；
StrategySignalQualityResult 缺失 → blocked；
quality 不允许 DecisionSnapshot → blocked；
StrategySignal 缺失 → blocked；
DecisionPolicyDefinition 缺失 → blocked；
DecisionPolicyDefinition disabled / retired → blocked；
StrategyAnalysisRelease 不存在、未批准、未启用或 release_hash 不一致 → blocked；
版本包未选择或选择多个 DecisionPolicyDefinition → blocked；
DecisionPolicyDefinition 指纹与版本包冻结值不一致 → blocked；
质量结果、StrategySignal 与 DecisionPolicyDefinition 不属于同一版本包 → blocked；
DecisionPolicyCalculator 精确版本缺失 → blocked；
算法需求文档或 implementation 实现记录缺失 → blocked；
calculator 返回非法 target_intent → failed；
calculator 返回非法 target_position_ratio → failed；
calculator 返回业务 status → failed；
CalculatorInput 不包含账户、持仓、PriceSnapshot；
DecisionSnapshot 不读取 Binance；
DecisionSnapshot 不生成 OrderPlan；
DecisionSnapshot 不生成 CandidateOrderIntent；
DecisionSnapshot 不调用 RiskCheck；
OrderPlan 只消费 TARGET_POSITION + allows_order_plan = true；
NO_TRADE / NO_TARGET_CHANGE 不进入 OrderPlan；
NO_TRADE / NO_TARGET_CHANGE 不由 DecisionSnapshot 触发追加账户同步，且不生成 PriceSnapshot；
过期 DecisionSnapshot 不允许 OrderPlan 消费；
幂等重复执行返回已有结果；
并发执行只生成一份等价结果；
dry-run 不写库、不写 AlertEvent；
dry-run 结果不能被 OrderPlan 消费；
业务表不保存编排 ID；
后台研究结果不写入正式 DecisionSnapshot；
正式服务不存在 allow_candidate、ignore_approval 或 use_latest 等绕过参数。
```

## 22. 验收方式

实现完成后至少执行：

```bash
pytest tests/decision_snapshot/
pytest tests/strategy_calculator/ -k decision_policy
python manage.py build_decision_snapshot --strategy-signal-quality-result-id <id> --strategy-analysis-release-id <id> --strategy-analysis-release-hash <hash> --business-request-key <key> --trigger-source manual --trace-id <id> --dry-run
python manage.py build_decision_snapshot --strategy-signal-quality-result-id <id> --strategy-analysis-release-id <id> --strategy-analysis-release-hash <hash> --business-request-key <key> --trigger-source manual --trace-id <id>
```

数据库至少检查：

```text
DecisionSnapshot 正确绑定 StrategySignalQualityResult；
DecisionSnapshot 正确绑定 StrategySignal；
DecisionSnapshot 正确绑定 DecisionPolicyDefinition；
DecisionSnapshot 的 StrategyAnalysisRelease 身份与质量结果、StrategySignal 和 Policy 一致；
decision_snapshot_key 幂等；
algorithm_name / algorithm_version / params_hash 已冻结；
TARGET_POSITION 才允许 allows_order_plan = true；
NO_TRADE / NO_TARGET_CHANGE 不允许 allows_order_plan；
自动四小时编排起始阶段已经保存 trade_preparation 账户边界事实；
dry-run 没有写入正式对象；
业务表没有保存编排 ID。
```

通过标准：

```text
DecisionSnapshot 只表达目标仓位意图；
DecisionSnapshot 只冻结上游价格条件，不生成订单价格；
目标仓位算法由 DecisionPolicyCalculator 承担；
DecisionPolicyCalculator 只执行统一目标仓位转换，不做策略类型分支；
业务流程与算法版本解耦；
算法变化不要求修改 DecisionSnapshotService；
每个算法版本有独立算法需求文档和 implementation 实现记录；
不读取账户、持仓、价格、订单或 Binance；
不生成订单、风控审批或执行动作；
只有 TARGET_POSITION 且快照可用时才允许 OrderPlan 消费；
MySQL 保存正式快照事实；
Redis 只作为短期锁、幂等或缓存辅助；
所有业务时间使用 UTC；
不调用 DeepSeek；
不涉及真实交易。
```

## 23. 模块影响声明

```text
读写 MySQL：是，读取 StrategySignalQualityResult、StrategySignal、DecisionPolicyDefinition，写 DecisionSnapshot 和必要 AlertEvent；
访问 Redis：可选，仅用于短期锁、幂等和缓存；
访问 Binance：否；
调用 BinanceGateway：否；
发送 Hermes：否；
调用大模型：否；
涉及真实交易：否；
涉及 FeatureLayer：否；
涉及 AtomicSignal：否；
涉及 DomainSignal：否；
涉及 MarketRegime：否，不作为二次分析或二次加权输入；
涉及 StrategyRouting：否；
涉及 StrategySignal：只消费质量放行后的策略结果；
涉及 StrategySignalQuality：是，必须消费其放行结果；
涉及 DecisionSnapshot：本模块自身；
涉及 Binance Account Sync：否；
涉及 PriceSnapshot：否；
涉及 OrderPlan / CandidateOrderIntent：只向 OrderPlan 提供目标仓位快照，不生成订单；
涉及 RiskCheck / ApprovedOrderIntent：否；
涉及 ExecutionPreparation / Execution：否；
涉及 OrderStatusSync / FillSync / ReviewDataset：不直接调用，只作为后置追溯事实；
写 AlertEvent：阻断、失败、未知或非法消费时写；
dry-run：执行同样检查和计算但不写库；
confirm-write：如提供，只控制落库，不改变算法或放行标准。
```

## 24. 明确禁止

DecisionSnapshot 禁止：

```text
跳过 StrategySignalQuality；
直接消费后台研究 StrategySignal 或其他版本包的 StrategySignal；
通过调用参数临时选择 DecisionPolicyDefinition 或绕过版本包批准；
重新执行 StrategySignal calculator；
重新计算 MarketRegime、DomainSignal、AtomicSignal 或 Feature；
使用 MarketRegime 或 DomainSignal 做二次加权；
按 strategy_code、strategy_version、MarketRegime、StrategyRouteDecision 或策略类型选择不同目标仓位映射；
读取当前账户、余额、持仓、杠杆或交易规则；
读取 PriceSnapshot；
读取 BinanceSyncRun；
请求 Binance；
调用 DeepSeek 参与实时决策；
根据价格条件选择订单类型；
生成订单动作；
生成 CandidateOrderIntent；
执行 RiskCheck；
提交订单；
把 target_position_ratio = 0.0 解释成平仓动作；
把 NO_TARGET_CHANGE 解释成目标空仓；
把 NO_TRADE 作为订单动作；
保存或查询编排 ID；
让 dry-run 结果进入 OrderPlan。
```

DecisionSnapshot 的最终定位是：

```text
基于质量放行的标准化 StrategySignal 和版本化统一 DecisionPolicy，生成可审计、可复算、不可变的目标仓位意图快照，但不重新分析市场、不按策略类型二次分支、不读取账户、不生成订单、不执行交易。
```
