# StrategySignal 需求说明

## 1. 模块定位

StrategySignal 位于 StrategyRouting 之后、StrategySignalQuality 之前。

它负责执行 StrategyRouteDecision 已经选定的 StrategyDefinition，基于同一业务链上的 DomainSignalValue 生成策略级市场判断。

正式链路为：

```text
DomainSignalSet / DomainSignalValue
→ MarketRegimeSnapshot
→ StrategyRouteDecision
→ StrategySignal
→ StrategySignalQualityResult
→ DecisionSnapshot
→ TARGET_POSITION：PriceSnapshot
→ OrderPlan
或 NO_TARGET_CHANGE / NO_TRADE：正常结束
```

StrategySignal 业务模块负责：

```text
接收明确的 strategy_route_decision_id；
校验路由结果是否允许生成策略信号；
读取路由绑定的唯一 StrategyDefinition；
校验 StrategyDefinition 的注册、生命周期和正式资格；
沿业务外键找到同一 DomainSignalSet；
读取并冻结策略所需 DomainSignalValue；
冻结 Definition、参数和输入权重；
把业务对象转换为不可变 StrategySignalCalculatorInput DTO；
通过公共 CalculatorRegistry 调用精确版本的 StrategySignal calculator；
校验 CalculatorOutput DTO；
生成不可变 StrategySignal；
保存方向、强度、置信评分、预测期限、权重和完整证据；
处理状态、幂等、事务、unknown、恢复和 AlertEvent；
向 StrategySignalQuality 提供稳定输入。
```

StrategySignal calculator 只负责：

```text
根据同一 DomainSignalSet 的领域输入执行纯策略计算；
按算法要求使用一次策略级领域权重；
输出 direction；
输出 strength；
输出 confidence；
输出 prediction_horizon；
输出实际使用的领域输入和权重；
输出聚合、冲突和结构化证据；
输出可判定的计算失败。
```

StrategySignal 不负责：

```text
重新选择策略；
重新计算 MarketRegime；
重新计算 DomainSignal；
读取 AtomicSignalValue；
读取 FeatureValue 或 Kline；
生成目标仓位；
生成 NO_TRADE、HOLD、ENTER、EXIT 等决策或订单动作；
读取账户、持仓或 PriceSnapshot；
生成 CandidateOrderIntent；
执行 RiskCheck；
交易执行；
调用 Binance；
调用大模型。
```

## 2. 策略注册制

策略采用注册制。

一个可被路由选择的策略必须同时具备：

```text
一条持久化 StrategyDefinition；
明确 strategy_code 和 strategy_version；
明确 algorithm_name 和 algorithm_version；
一个已注册 StrategySignal calculator；
稳定 CalculatorInput / CalculatorOutput schema；
独立算法需求文档；
代码 implementation 实现记录；
完整测试；
明确验证状态；
人工启用配置。
```

策略注册分为两层：

```text
StrategyDefinition = 业务注册信息、参数、输入要求、权重和运行资格；
StrategySignal calculator = 具体策略计算代码。
```

新增策略时只允许增加或配置：

```text
StrategyDefinition；
对应 calculator 及注册；
对应算法需求文档；
对应 implementation 实现记录；
策略算法测试；
指向该 StrategyDefinition 的 StrategyRouteRule。
```

不得因此修改：

```text
StrategyRoutingService 主流程；
StrategySignalService 主流程；
StrategyRouteDecision 核心合同；
StrategySignal 核心输出合同；
StrategySignalQuality、DecisionSnapshot 或订单链业务边界。
```

停用策略只修改 StrategyDefinition 的生命周期和运行配置，不删除历史 Definition、StrategyRouteDecision 或 StrategySignal。

## 3. 当前算法边界

本需求只定义策略注册框架、业务合同和 Calculator 边界，不指定任何正式策略算法。

本需求不指定：

```text
正式 strategy_code；
正式 strategy_version；
正式 algorithm_name；
正式 algorithm_version；
具体趋势判断公式；
具体领域输入权重；
具体方向聚合公式；
具体 strength 公式；
具体 confidence 公式；
具体 prediction_horizon；
正式 StrategyDefinition。
```

因此：

```text
不得仅凭本需求 seed 一个可被正式版本包选择的策略；
不得把历史文档中的示例策略当作正式策略；
不得在 StrategySignalService 中临时实现趋势公式；
不得缺少精确 calculator 时使用其他策略算法；
不得在算法需求文档、implementation 实现记录和一致性验证证据缺失时允许路由选择策略。
```

版本包没有选择可用 StrategyDefinition 时，StrategyRouting 应阻断；StrategySignal 不生成伪造结果。算法库可以登记任意已实现策略，正式服务只执行已批准并启用版本包选择且由路由命中的定义。

## 4. 核心原则

### 4.1 StrategyRouteDecision 是唯一正式入口

StrategySignalService 必须接收明确的 `strategy_route_decision_id`。

只允许消费：

```text
StrategyRouteDecision.status = created；
StrategyRouteDecision.route_outcome = selected；
StrategyRouteDecision.is_usable = true；
StrategyRouteDecision.allows_strategy_signal = true；
selected_strategy_definition_id 非空。
```

StrategySignal 不得：

```text
自行寻找最近一份 StrategyRouteDecision；
重新匹配 StrategyRouteRule；
自行选择另一个 StrategyDefinition；
使用 no_strategy Decision；
使用 blocked、failed、unknown、后台研究或其他版本包的 Decision；
在被选策略不可用时自动寻找替代策略。
```

### 4.2 DomainSignalValue 是唯一正式计算输入

策略 calculator 只读取同一 DomainSignalSet 中明确允许的 DomainSignalValue DTO。

必须满足：

```text
所有 DomainSignalValue 属于同一 DomainSignalSet；
DomainSignalSet.status = created；
DomainSignalSet.is_usable = true；
DomainSignalValue.status = created；
DomainSignalValue.is_valid = true；
domain_code 位于 StrategyDefinition.allowed_domain_codes；
required_domain_codes 全部存在；
实际使用值 ID 完整记录。
```

StrategySignal 不得正式读取：

```text
AtomicSignalValue；
AtomicSignalDefinition；
FeatureValue；
Kline；
不同 DomainSignalSet 的领域结果。
```

这条规则用于防止同一底层市场证据同时经 DomainSignal 和 AtomicSignal 被重复计分。

### 4.3 MarketRegime 只作为追溯上下文

MarketRegimeSnapshot 已经参与 StrategyRouting，决定了本轮选择哪个 StrategyDefinition。

StrategySignal 业务对象必须保存并可追溯本轮 MarketRegimeSnapshot，但 StrategySignal calculator 不接收 MarketRegimeSnapshot DTO。

因此 MarketRegime 不得在 StrategySignal calculator 中再次：

```text
乘入领域权重；
改变策略方向；
放大或缩小 strength；
放大或缩小 confidence；
切换算法参数；
否决已经完成的路由选择。
```

如果未来确实需要市场环境再次参与某个策略算法，必须先修改需求合同并证明不会重复计算，不能通过 params 暗中引入。

### 4.4 权重只在策略层使用一次

策略级业务权重只属于 StrategySignal calculator。

允许权重的最小输入单位是 DomainSignalValue。

禁止同时加权：

```text
某个 DomainSignalValue；
以及该 DomainSignalValue 已经聚合过的 AtomicSignalValue。
```

禁止使用：

```text
MarketRegime.regime_confidence 作为领域权重；
DomainSignal.coverage_ratio 直接替代权重；
DomainSignal.agreement_ratio 直接替代权重；
历史收益临时生成动态权重；
AIReview 输出生成实时权重；
账户权益或持仓生成策略权重。
```

### 4.5 正常 neutral 与失败分离

策略计算成功但没有形成明确方向时，应生成：

```text
status = created；
direction = neutral；
is_usable = true；
正式结果 allows_strategy_signal_quality = true。
```

正常 neutral 可以来源于：

```text
领域方向冲突；
策略强度不足；
条件正常不成立；
多空证据接近；
算法定义的中性区间。
```

这些不是 blocked 或 failed，也不写异常 AlertEvent。

### 4.6 StrategySignal 不是目标仓位决策

StrategySignal 只表示策略级市场判断。

允许输出：

```text
direction；
strength；
confidence；
prediction_horizon；
evidence_items；
evidence_text_zh；
aggregation_snapshot；
conflict_snapshot。
```

禁止输出：

```text
target_position_ratio；
target_notional；
entry_price；
stop_loss；
take_profit；
position_size；
leverage；
reduce_only；
order_side；
order_quantity；
CandidateOrderIntent。
```

目标仓位由 DecisionSnapshot 生成，候选订单由 OrderPlan 生成。

### 4.7 MySQL 是正式事实来源

以下对象必须持久化到 MySQL：

```text
StrategyDefinition；
StrategySignal；
必要的 AlertEvent。
```

Redis 只允许用于短期锁、幂等、缓存和任务状态，不得成为 StrategySignal 的唯一存储，也不得作为 StrategySignalQuality 的正式输入来源。

## 5. 服务入口合同

StrategySignalService 只提供正式入口。后台研究与回测使用独立研究服务，不调用正式服务的绕过入口。

### 5.1 正式入口

```text
generate_strategy_signal(
    strategy_route_decision_id,
    strategy_analysis_release_id,
    strategy_analysis_release_hash,
    expected_strategy_definition_hash,
    business_request_key,
    trace_id,
    trigger_source,
)
```

正式入口不允许调用方：

```text
指定另一个 StrategyDefinition；
覆盖 algorithm_name 或 algorithm_version；
覆盖 params 或 input_weights；
传入额外 DomainSignalValue；
传入 MarketRegime 参与计算；
绕过 StrategyRouteDecision。
```

正式版本包选择、批准、启用、切换、回滚和后台研究隔离统一遵守 [StrategyAnalysisRelease](strategy_analysis_release.md)。

正式入口必须校验 RouteDecision、被选 StrategyDefinition、DomainSignalSet 与本轮 StrategyAnalysisRelease 一致，且被选策略位于版本包策略切片、definition_hash 与冻结值一致。

### 5.2 business_request_key

`business_request_key` 用于业务请求幂等，由调用方显式传入。

不得包含 task id、worker 名称、当前时间、随机重试序号或编排 ID。

### 5.3 trace_id 与 trigger_source

`trace_id` 只用于日志审计，不参与业务唯一性或算法计算。

`trigger_source` 至少允许：

```text
orchestrator；
celery；
management_command；
ops_console；
recovery；
test。
```

触发来源不得改变 StrategyDefinition、算法、参数、权重或放行标准。

## 6. 结构化返回合同

StrategySignalService 返回至少包括：

```text
status
strategy_signal_id
strategy_signal_key
strategy_route_decision_id
strategy_definition_id
strategy_analysis_release_id
strategy_analysis_release_hash
domain_signal_set_id
market_regime_snapshot_id
direction
strength
confidence
is_usable
allows_strategy_signal_quality
error_code
error_message
trace_id
```

允许业务状态：

```text
created
blocked
failed
unknown
```

### 6.1 created

表示：

```text
正式入口和路由合同满足；
StrategyDefinition 注册和配置有效；
领域输入完整；
calculator 精确可用；
计算成功；
CalculatorOutput 合同通过；
StrategySignal 完整落库。
```

```text
is_usable = true；
allows_strategy_signal_quality = true。
```

### 6.2 blocked

blocked 表示业务前置条件不满足，没有执行可靠策略计算。

典型场景：

```text
StrategyRouteDecision 不存在或不可用；
route_outcome 不是 selected；
allows_strategy_signal = false；
StrategyAnalysisRelease 不存在、未批准、未启用或 release_hash 不一致；
Decision、Definition 或 DomainSignalSet 不属于同一版本包；
被选 StrategyDefinition 不存在；
StrategyDefinition 非 active 或 disabled；
StrategyDefinition 不在版本包策略切片；
Definition 身份或参数不完整；
required DomainSignalValue 缺失；
领域输入来源混用；
calculator 精确版本未注册；
算法需求文档或 implementation 实现记录缺失；
Definition 指纹与版本包冻结值不一致。
```

blocked 必须：

```text
is_usable = false；
allows_strategy_signal_quality = false；
strategy_signal_id = null；
strategy_signal_key = null；
不创建 StrategySignal；
不得伪造 direction；
写明确 error_code；
写 AlertEvent。
```

`blocked` 是前置条件校验结果，不是已持久化 StrategySignal 的生命周期状态。

### 6.3 failed

failed 表示已进入处理但无法可靠完成。

典型场景：

```text
CalculatorInput 构造失败；
calculator 返回 failed；
calculator 抛出未预期异常；
CalculatorOutput 合同非法；
direction 非法；
strength 或 confidence 越界；
used_domain_signal_value_refs 非法；
实际权重与冻结 Definition 不一致；
证据无法序列化；
数据库事务明确失败。
```

failed 不得伪装成 neutral。

### 6.4 unknown

unknown 只用于持久化结果无法确认。

必须先按 business_request_key 和 strategy_signal_key 查证，不得直接重新执行 calculator。

Calculator 不得返回 unknown。

## 7. StrategyDefinition

StrategyDefinition 是策略注册表中的业务定义。

建议字段：

```text
id
strategy_code
strategy_version
display_name
description
algorithm_name
algorithm_version
input_schema_version
output_schema_version
params
params_hash
definition_hash
allowed_domain_codes
required_domain_codes
uses_input_weights
domain_input_weights
prediction_horizon
status
enabled
created_at_utc
updated_at_utc
```

### 7.1 strategy_code 与 strategy_version

`strategy_code` 表示稳定策略家族，使用可读 snake_case。

`strategy_version` 表示业务策略定义版本。

唯一性：

```text
strategy_code + strategy_version
```

它们不得包含运行环境、任务 ID、编排 ID 或启用状态。

### 7.2 algorithm_name 与 algorithm_version

表示具体 StrategySignal calculator 的不可变算法身份。

必须通过公共 CalculatorRegistry 精确解析：

```text
calculator_type = strategy_signal；
algorithm_name 完全一致；
algorithm_version 完全一致。
```

不得缺省版本、按版本排序选择、回退到名称相近算法或由 env 替换实现。

### 7.3 策略版本与算法版本

必须区分：

```text
strategy_version = 一整套策略业务定义的版本；
algorithm_version = 计算公式和边界行为的版本；
params_hash = 本次参数组合身份。
```

同一算法可以被多个 StrategyDefinition 使用不同参数复用。

算法行为未变化、只改变参数时，不得滥增 algorithm_version。

### 7.4 params

params 只保存该 calculator 所需的冻结策略参数。

可能包含的参数类别必须由算法需求文档定义，例如：

```text
中性区间；
方向阈值；
强度归一化边界；
置信评分参数；
冲突处理方式；
最小有效领域数量；
预测期限计算参数。
```

params 禁止包含：

```text
账户权益；
持仓；
价格快照；
目标仓位；
订单数量；
杠杆；
MarketRegime 权重；
AIReview 实时输出；
当前时间；
编排 ID；
在线自动优化结果。
```

### 7.5 params_hash

使用规范化参数计算：

```text
sha256(canonical_json(params))
```

规范化必须固定键排序、Decimal 字符串、空值、布尔值和数组顺序语义。

### 7.6 allowed_domain_codes 与 required_domain_codes

`allowed_domain_codes` 定义策略 calculator 允许读取的领域。

`required_domain_codes` 定义完成策略计算必须存在且有效的领域。

规则：

```text
required_domain_codes 是 allowed_domain_codes 的子集；
列表不得重复；
不得包含未注册 DomainSignalDefinition 的 domain_code；
Service 不把 allowed 列表外的 Value 传给 calculator；
required 缺失时 blocked；
required 领域正常 neutral、mixed 或低强度仍是有效输入。
```

### 7.7 uses_input_weights 与 domain_input_weights

`uses_input_weights` 由 StrategyDefinition 与 calculator metadata 共同确认。

当 `uses_input_weights = true`：

```text
每个实际参与正式计算的 domain_code 必须有明确权重；
权重必须是有限、非负 Decimal；
权重缺失不得默认使用 1；
归一化方式必须由算法需求文档固定；
实际使用权重必须写入 StrategySignal；
同一 DomainSignalValue 只能应用一次权重。
```

当 `uses_input_weights = false`：

```text
domain_input_weights 必须为空；
calculator 不得在内部读取隐藏权重；
StrategySignal.actual_input_weights 为空。
```

权重为零是否允许、权重总和是否必须等于一，由具体算法需求文档明确；不得由 Service 猜测。

### 7.8 prediction_horizon

`prediction_horizon` 表示策略判断预期适用的分析期限，不表示订单有效期、持仓承诺或成交期限。

必须：

```text
由 Definition 或 calculator 明确输出；
使用稳定、机器可读格式；
不依赖服务器当前时间；
写入 StrategySignal；
由算法需求文档说明。
```

### 7.9 definition_hash

至少覆盖：

```text
strategy_code；
strategy_version；
algorithm_name；
algorithm_version；
input_schema_version；
output_schema_version；
params_hash；
allowed_domain_codes；
required_domain_codes；
uses_input_weights；
规范化 domain_input_weights；
prediction_horizon。
```

`enabled` 是策略算法库可用性开关，不进入不可变 definition_hash。它不代表 StrategyDefinition 自动进入正式运行；正式身份由 StrategyAnalysisRelease 策略切片选择并冻结。

### 7.10 生命周期和正式参与资格

生命周期：

```text
draft
active
deprecated
retired
disabled
```

可被 StrategyAnalysisRelease 选择的 Definition 必须满足：

```text
status = active；
enabled = true。
```

`status = active` 与 `enabled = true` 只表示 StrategyDefinition 在策略算法库中可供选择。正式参与资格必须同时满足：

```text
位于本轮 StrategyAnalysisRelease 策略切片；
Definition 为 active 且 enabled；
definition_hash 与版本包冻结值一致；
StrategyRoutePolicy 的 Rule 明确引用该 Definition；
对应 calculator、算法需求文档、implementation 实现记录与输入合同完整。
```

已实现、已注册并通过文档、代码和测试一致性验证的策略版本在已验证算法目录中平权；是否正式执行只由本轮冻结版本包的选择和路由结果决定，不使用额外“可正式路由”开关。

被历史对象引用的 StrategyDefinition 不得物理删除或覆盖不可变身份字段。

## 8. StrategySignal

StrategySignal 是某个已注册策略基于一组确定领域事实形成的不可变策略级判断。

建议字段：

```text
id
strategy_route_decision_id
strategy_definition_id
strategy_analysis_release_id
strategy_analysis_release_hash
domain_signal_set_id
market_regime_snapshot_id
business_request_key
strategy_signal_key
strategy_signal_schema_version
strategy_code
strategy_version
direction
strength
confidence
confidence_semantics
prediction_horizon
status
is_usable
allows_strategy_signal_quality
definition_status
definition_enabled
algorithm_name
algorithm_version
input_schema_version
output_schema_version
params_hash
definition_hash
used_domain_signal_codes
used_domain_signal_value_ids
actual_input_weights
aggregation_snapshot
conflict_snapshot
evidence_items
evidence_text_zh
payload_summary
error_code
error_message
analysis_close_time_utc
calculated_at_utc
latency_ms
created_at_utc
```

### 8.1 业务外键

正式 StrategySignal 必须形成：

```text
StrategySignal
→ StrategyRouteDecision
→ StrategyDefinition
→ MarketRegimeSnapshot
→ DomainSignalSet / DomainSignalValue
→ AtomicSignalSet
→ FeatureSet
→ MarketSnapshot
```

正式 StrategySignal 必须绑定真实 StrategyRouteDecision；后台研究信号写入隔离研究对象，不使用 StrategySignal 表。

### 8.2 strategy_signal_key

正式唯一身份至少覆盖：

```text
strategy_route_decision_id；
strategy_signal_schema_version；
definition_hash；
domain_signal_set_id。
```

唯一键不得包含 trace_id、task id、当前时间、编排 ID 或随机数。

### 8.3 不可变性

StrategySignal 一旦 created：

```text
不得更换 StrategyRouteDecision；
不得更换 StrategyDefinition；
不得替换 DomainSignalSet；
不得改写方向、强度、置信评分、权重或证据；
不得因 Definition 后续停用而修改历史结果；
重算必须产生身份不同的新 StrategySignal。
```

### 8.4 状态与放行

```text
created → is_usable = true  → allows_strategy_signal_quality = true；
failed  → is_usable = false → allows_strategy_signal_quality = false；
unknown → is_usable = false → allows_strategy_signal_quality = false。
```

blocked 不创建 StrategySignal。正式服务不得创建只用于后台研究的 StrategySignal。

## 9. 策略输出字段

StrategySignal 的输出字段必须是跨策略统一语义，而不是某个策略 calculator 的内部原始指标。

无论当前执行的是趋势策略、震荡策略、突破策略、防守策略或其他策略，正式 StrategySignal 输出都必须遵守同一套下游可解释合同：

```text
direction = 统一的策略级市场方向；
strength = 统一的目标方向强度；
confidence = 统一的结构化策略置信评分；
prediction_horizon = 统一的策略判断适用期限；
evidence = 可追溯、可审计的标准化证据。
```

策略差异必须在 StrategySignal calculator 内部消化，并在输出前标准化。DecisionSnapshot 不按 `strategy_code`、`strategy_version`、MarketRegime 或策略类型做二次分支，因此 StrategySignal 不能把策略内部指标伪装成统一输出。

禁止出现以下情况：

```text
趋势策略的 strength 表示趋势斜率，震荡策略的 strength 表示反转空间，但二者都直接写入同一 strength 字段；
某个策略的 confidence 表示信号覆盖率，另一个策略的 confidence 表示盈利概率，却使用同一 confidence_semantics；
某个策略天然只适合轻仓，却输出高 strength 后期望 DecisionSnapshot 根据 strategy_code 再降仓；
某个策略的 bullish 只表示局部反弹，另一个策略的 bullish 表示趋势延续，却不通过 strength、confidence、prediction_horizon 和证据完成标准化。
```

如果某个策略算法无法把自身结果转换为统一 StrategySignal 输出语义，则该策略算法不得进入正式 StrategyAnalysisRelease。

### 9.1 direction

允许值：

```text
bullish
bearish
neutral
none
```

语义：

```text
bullish = 策略级市场判断偏多；
bearish = 策略级市场判断偏空；
neutral = 策略计算成功但没有形成明确方向；
none    = blocked / failed 等无有效策略方向。
```

direction 不是买卖、开平仓或目标仓位动作。

### 9.2 strength

范围：

```text
0 <= strength <= 1
```

它表示最终策略判断的明显程度。

具体公式、归一化和 neutral 行为由算法需求文档固定。

strength 不得直接复制某个 DomainSignalValue.strength，也不得解释为目标仓位比例。

不同策略 calculator 输出的 strength 必须具备同一业务解释：越接近 1，表示该策略对其最终 direction 的目标方向强度越强；越接近 0，表示目标方向强度越弱或不足。strength 不得保存策略内部未标准化指标。

### 9.3 confidence

范围：

```text
0 <= confidence <= 1
```

未完成概率校准时，confidence 只表示结构化策略置信评分，不是盈利概率。

输入完整、calculator succeeded 或领域覆盖率为一，都不自动等于 confidence = 1。

相同 `confidence_semantics` 下，不同策略 calculator 输出的 confidence 必须具备同一业务解释。若某个策略需要不同置信语义，必须使用新的 `confidence_semantics`、算法需求文档和验证证据，并确保下游 DecisionSnapshot 能按统一合同解释；不得在同一语义代码下混用不同含义。

禁止：

```text
把多个上游 confidence 连乘；
把 MarketRegime.regime_confidence 复制为策略 confidence；
把 agreement_ratio 直接当 confidence；
把 confidence 解释为下单概率或仓位比例。
```

如果算法声称 confidence 是概率，必须通过独立样本外校准，并在算法需求文档中明确统计语义和验证方法。

### 9.4 confidence_semantics

必须明确记录 confidence 的语义代码。

在没有概率校准时使用：

```text
strategy_score
```

其他语义只有在算法需求文档、验证和 schema 同时明确后才能使用。

### 9.5 prediction_horizon

保存本次策略输出的适用分析期限。

它不得被 OrderPlan、Execution 或订单状态模块解释为订单有效期。

不同策略的 prediction_horizon 必须使用同一格式和同一语义体系。若某个策略天然只适合短期限判断，应通过 prediction_horizon、strength、confidence 和证据表达，而不是要求 DecisionSnapshot 识别策略类型后重新解释。

### 9.6 actual_input_weights

必须记录 calculator 实际应用的领域权重。

要求：

```text
键只包含实际 used_domain_signal_codes；
值与冻结 Definition 一致；
Decimal 使用规范字符串；
不包含 MarketRegime 权重；
不包含 AtomicSignal 权重；
uses_input_weights = false 时为空。
```

### 9.7 used_domain_signal_codes 与 used_domain_signal_value_ids

必须记录实际参与计算的领域事实。

全部 Value 必须来自同一 DomainSignalSet，且每个 ID 只出现一次。

不得只记录 Definition 依赖而不记录实际使用值。

### 9.8 aggregation_snapshot

保存策略计算的机器可读聚合摘要，至少包括：

```text
输入领域代码；
各领域方向或状态；
各领域 strength；
实际权重；
算法所需中间统计；
最终 direction；
最终 strength；
最终 confidence。
```

具体结构由算法 output schema 和算法需求文档固定。

### 9.9 conflict_snapshot

保存策略算法识别出的领域冲突信息。

至少应表达：

```text
是否存在冲突；
发生冲突的领域；
冲突如何影响最终结果；
为什么形成 neutral、bullish 或 bearish。
```

正常冲突可以产生 created + neutral，不自动 blocked。

### 9.10 evidence_items 与 evidence_text_zh

机器可读证据至少引用：

```text
实际 DomainSignalValue ID；
领域方向或状态；
领域 strength、coverage_ratio 和 agreement_ratio；
实际使用权重；
策略中间统计；
最终方向、强度和置信评分；
冲突信息。
```

不得复制完整 AtomicSignalValue、FeatureValue 或 Kline。

中文证据必须说明为什么得到本次策略判断，但不得包含目标仓位、订单动作、杠杆或交易建议。

## 10. StrategySignalService 与 calculator 边界

### 10.1 公共合同

所有 StrategySignal calculator 必须遵守 [StrategyCalculator 公共合同](strategy_calculator.md)。纯计算、DTO、状态、异常、确定性、精度、Registry、版本和副作用隔离规则以公共合同为准。

### 10.2 稳定业务代码

StrategySignalService 负责：

```text
校验服务入口和幂等键；
读取并校验 StrategyRouteDecision；
读取并冻结被选 StrategyDefinition；
校验策略注册和正式资格；
沿业务链定位 DomainSignalSet；
读取并校验 DomainSignalValue；
校验 allowed / required domain codes；
冻结 params 和 input_weights；
构造不可变 StrategySignalCalculatorInput DTO；
通过公共 CalculatorRegistry 精确解析 calculator；
调用 calculator；
校验 StrategySignalCalculatorOutput DTO；
把 succeeded / failed 映射为业务状态；
决定 is_usable 和 allows_strategy_signal_quality；
事务写入 StrategySignal；
处理幂等、并发、unknown、恢复和 AlertEvent。
```

新增兼容策略 Calculator 或 StrategyDefinition 不得要求修改 Service 主流程。

### 10.3 CalculatorInput

至少包含：

```text
不可变 StrategyDefinition DTO；
同一 DomainSignalSet 的不可变 DomainSignalValue DTO；
冻结 allowed / required domain codes；
冻结 params；
冻结 input_weights；
算法、schema 和精度身份。
```

CalculatorInput 不包含：

```text
StrategyRouteDecision DTO；
MarketRegimeSnapshot DTO；
AtomicSignalValue DTO；
Django model；
QuerySet；
数据库连接；
Redis client；
service；
Celery task；
编排对象。
```

路由和市场环境由 Service 负责校验、绑定和审计，不进入策略数学计算。

### 10.4 CalculatorOutput

至少包含：

```text
calculation_status = succeeded / failed；
direction；
strength；
confidence；
confidence_semantics；
prediction_horizon；
used_domain_signal_value_refs；
actual_input_weights；
aggregation_snapshot；
conflict_snapshot；
结构化证据；
失败时 error_code / error_message。
```

CalculatorOutput 不得返回：

```text
created；
blocked；
unknown；
allows_strategy_signal_quality；
target_position_ratio；
订单动作或订单对象。
```

### 10.5 StrategySignal 特有禁止项

calculator 不得：

```text
读取 MarketRegimeSnapshot；
读取 AtomicSignalValue、FeatureValue 或 Kline；
调用其他 calculator；
查询数据库补充领域输入；
修改 StrategyDefinition 或 DomainSignalValue；
选择另一个策略；
读取策略历史表现；
读取账户、持仓、价格、订单或风控结果；
生成目标仓位或交易动作。
```

## 11. CalculatorRegistry 与策略算法身份

StrategySignal 使用 [StrategyCalculator 公共合同](strategy_calculator.md)定义的公共 CalculatorRegistry。

每个策略 calculator 必须声明：

```text
calculator_type = strategy_signal；
algorithm_name；
algorithm_version；
input_schema_version；
output_schema_version；
deterministic = true；
uses_input_weights；
algorithm_requirement_document_path；
implementation_document_path。
```

规则：

```text
StrategyDefinition 必须精确解析到 calculator；
uses_input_weights 必须与 Definition 一致；
algorithm_requirement_document_path 和 implementation_document_path 必须记录稳定路径；
文档存在性与身份一致性由 CI、构建和版本包批准阶段验证并形成证据；
正式运行时不得读取 Markdown 文件判断 calculator 是否可用；
算法需求文档、implementation 实现记录的身份必须与 metadata 一致；
缺少精确版本时 blocked；
不得回退其他名称或版本；
Registry 初始化后只读。
```

## 12. 默认模板与运行时 StrategyDefinition

必须区分：

```text
default_strategy_definitions.py = 受代码管理的策略模板；
StrategyDefinition 表           = 可供组合选择的策略算法库；
StrategyAnalysisRelease 策略切片 = 正式运行时策略集合。
```

正式运行只读取本轮 StrategyAnalysisRelease 策略切片中被 StrategyRouteDecision 选定的 StrategyDefinition。

Service 不得直接读取模板参与计算、把模板与数据库求合集、自动恢复停用策略或覆盖人工配置。

本需求没有指定具体策略，因此默认模板不得凭空创建可被正式版本包选择的 StrategyDefinition。

## 13. seed_strategy_definitions

必须提供幂等初始化入口：

```bash
python manage.py seed_strategy_definitions
```

命令只负责：

```text
读取项目中明确存在的策略模板；
规范化 params 和 domain_input_weights；
计算 params_hash 和 definition_hash；
校验 allowed / required domain codes；
校验 calculator metadata、算法需求文档和 implementation 实现记录；
校验 uses_input_weights；
按完整定义身份幂等写入；
输出初始化摘要。
```

命令不得：

```text
发明策略或计算公式；
生成 StrategySignal；
生成 StrategyRouteRule；
调用 StrategySignalService；
恢复 retired 或 disabled Definition；
覆盖 enabled 或修改任何 StrategyAnalysisRelease；
缺少 calculator，或算法文档尚未通过 CI、构建与版本包批准阶段一致性验证时把 Definition 标记为可用。
```

没有已确认模板时，命令必须返回零变更摘要。

## 14. 策略算法需求文档与 implementation 实现记录

每个 StrategySignal calculator 必须同时具备：

```text
独立算法需求文档；
代码 implementation 实现记录。
```

二者职责不同：

```text
算法需求文档 = 先定义这个策略算法要怎么算、使用哪些领域输入、公式、参数、边界、验证要求和业务语义；
implementation 实现记录 = 代码实现完成后，记录实际落地的 calculator、类/函数、DTO、异常处理、测试入口和实现差异。
```

implementation 实现记录不得新增算法需求文档没有定义的策略行为。代码实现时发现算法需求不完整，必须先回到 requirements 补齐算法需求，再继续实现。

算法需求文档应放在 requirements 下的对应策略算法目录，具体目录结构由后续策略算法需求文件统一确定，例如：

```text
docs/requirements/<策略算法模块>/<strategy_code>.md
```

implementation 实现记录统一目录：

```text
docs/implementation/strategy_signal/
```

文件名：

```text
<algorithm_name>__<algorithm_version>.md
```

除 [StrategyCalculator 公共合同](strategy_calculator.md)要求外，每份策略算法需求文档还必须记录：

```text
适用的 strategy_code；
allowed / required domain codes；
uses_input_weights；
权重归一化公式；
每个领域字段的使用方式；
完整方向计算公式；
strength 公式和归一化；
confidence 公式和统计语义；
prediction_horizon；
如何把策略内部指标标准化为统一 direction / strength / confidence / prediction_horizon；
该算法输出与统一 StrategySignal 语义合同的兼容性证明；
中性区间；
冲突处理；
缺失可选领域处理；
边界值和失败条件；
防止重复计分规则；
完整计算示例；
golden test；
验证证据和适用边界。
```

算法行为变化必须使用不同 algorithm_version，并先形成新的算法需求文档；对应代码实现完成后，再形成新的 implementation 实现记录。

参数组合变化由 params、params_hash 和 definition_hash 表达；计算行为未变化时不得滥增算法版本。

本需求不创建任何具体 StrategySignal 算法需求文件，也不创建任何具体 StrategySignal implementation 实现记录。

## 15. 策略验证与正式发布

策略至少验证：

```text
时间顺序回测；
样本外验证；
walk-forward 验证；
参数敏感性；
领域权重敏感性；
简单基准比较；
消融测试；
前视偏差检查；
重复计分检查；
不同市场环境下的表现分解；
手续费、滑点和资金费率后的有效性；
后台研究与正式 calculator 一致性。
```

所有已实现、已注册并通过一致性验证的策略算法版本在已验证算法目录中平权。正式资格只属于本轮冻结的、经过验证、人工批准并启用的完整 StrategyAnalysisRelease。

后台研究与回测服务可以自由选择 StrategyDefinition、参数版本及其上下游组合，使用相同 calculator、DTO、权重和精度规则，但结果必须写入隔离研究对象，不得写入正式 StrategySignal，也不得调用正式 StrategySignalService 的绕过入口。

算法需求文档、implementation 实现记录、Definition 状态或后台结果本身不能自动批准版本包，也不能开启真实交易。

## 16. StrategySignalService 主流程

正式流程：

```text
1. 接收 strategy_route_decision_id、StrategyAnalysisRelease 身份、business_request_key、trace_id、trigger_source；
2. 校验请求字段；
3. 按 business_request_key 查询已有结果；
4. 读取 StrategyRouteDecision；
5. 校验 status、route_outcome、is_usable、allows_strategy_signal 和版本包身份；
6. 读取 Decision 绑定的 StrategyDefinition；
7. 校验 StrategyAnalysisRelease 的批准、启用和 release_hash；
8. 校验 Definition 位于版本包策略切片且 definition_hash 一致；
9. 校验 Definition 注册、生命周期、启用状态和 calculator；
10. 冻结 Definition、params、input_weights 和 hash；
11. 沿 Decision → MarketRegimeSnapshot → DomainSignalSet 确定输入集合；
12. 读取同一 DomainSignalSet 的 DomainSignalValue；
13. 校验 allowed / required domain codes；
14. 校验输入来源一致、同属版本包、状态有效且 ID 去重；
15. 生成 strategy_signal_key；
16. 按 key 查询已有完整 StrategySignal；
17. 通过公共 Registry 精确解析 calculator；
18. 构造不可变 CalculatorInput DTO，不包含 MarketRegimeSnapshot；
19. 执行 calculator；
20. 校验 CalculatorOutput DTO；
21. 校验方向、数值范围、权重和证据；
22. 把 calculation_status 映射为业务状态；
23. 生成不可变 StrategySignal；
24. 在数据库事务中正式写入；
25. 写必要 AlertEvent；
26. 返回结构化业务结果。
```

计算期间不得重新读取 Definition、权重或领域输入并替换冻结内容。

## 17. 单项输入与失败处理

### 17.1 required 领域缺失

required DomainSignalValue 不存在或无效时：

```text
status = blocked；
不调用 calculator；
allows_strategy_signal_quality = false；
写 required_domain_signal_missing AlertEvent。
```

### 17.2 optional 领域缺失

optional 领域缺失是否允许计算，必须由 StrategyDefinition 和 calculator contract 明确。

Service 只按冻结合同决定是否调用 calculator，不自行填充中性值或零值。

### 17.3 calculator failed

calculator 返回 failed 时：

```text
status = failed；
direction = none；
is_usable = false；
allows_strategy_signal_quality = false；
error_code 和 error_message 非空；
不得伪造 neutral。
```

### 17.4 正常 neutral

calculator succeeded 且方向为 neutral 时：

```text
status = created；
direction = neutral；
strength 和 confidence 保存算法实际值；
证据完整；
正式结果允许进入 StrategySignalQuality。
```

## 18. 写库与事务

StrategySignal 必须在数据库事务中正式写入。

要求：

```text
使用 transaction.atomic() 或等价 Django 事务；
数据库唯一约束保护 business_request_key 和 strategy_signal_key；
写入前完成 calculator、权重和输出合同校验；
StrategySignal 与必要 AlertEvent 按项目事件事务规则写入；
不得在事务中执行外部请求；
不得在事务中等待其他模块；
事务失败不得留下 created 半成品。
```

## 19. 幂等与并发

### 19.1 重复请求

```text
已有 created → 返回已有 StrategySignal；
已有 blocked → 返回已有阻断结果；
已有 failed → 返回已有失败结果，受控恢复可以重新核验；
已有 unknown → 先查证，不重新计算。
```

### 19.2 相同输入身份

以下身份相同不得产生两份相同正式 StrategySignal：

```text
strategy_route_decision_id；
strategy_signal_schema_version；
definition_hash；
domain_signal_set_id；
运行语义。
```

### 19.3 并发冲突

使用数据库唯一约束、原子创建和必要的短期 Redis 锁。

Redis 锁失效不能破坏数据库唯一性。

## 20. unknown 与恢复

持久化结果不明确时：

```text
不得假设写入失败；
不得立即重新执行 calculator；
按 business_request_key 查询；
按 strategy_signal_key 查询；
核对 RouteDecision、Definition、DomainSignalSet、used Value 和 hash；
无法确认时保持 unknown 并告警。
```

不得覆盖已 created 的 StrategySignal 重算。

受控恢复不得使用后来改变的 StrategyDefinition、参数或权重替换历史冻结输入。

## 21. StrategySignalQuality 消费合同

StrategySignalQuality 只允许消费：

```text
StrategySignal.status = created；
StrategySignal.is_usable = true；
StrategySignal.allows_strategy_signal_quality = true；
StrategyDefinition.status = active；
StrategyDefinition.enabled = true；
StrategySignal 与 StrategySignalQuality 使用同一 StrategyAnalysisRelease。
```

StrategySignalQuality 必须接收明确 strategy_signal_id，不得重新执行策略 calculator、重新选择 StrategyDefinition 或改写方向、强度、置信评分和权重。

## 22. 与 StrategyRouting 的关系

```text
StrategyRouting 选择已注册 StrategyDefinition；
StrategySignal 执行被选 StrategyDefinition；
StrategySignal 不重新路由；
StrategyRouting 不执行策略 calculator。
```

新增策略的业务流程：

```text
注册 StrategyDefinition 与 calculator
→ 完成算法需求文档、implementation 实现记录和验证
→ 将 Definition 和对应 StrategyRouteRule 纳入完整 StrategyAnalysisRelease
→ 完成版本包验证、人工批准与启用
→ 路由可以选择该策略
→ StrategySignalService 使用公共流程执行。
```

## 23. 与 MarketRegime 的关系

MarketRegimeSnapshot 通过 StrategyRouteDecision 参与策略选择和审计追溯。

StrategySignal 保存 market_regime_snapshot_id，但 CalculatorInput 不包含 MarketRegimeSnapshot。

MarketRegime 不得在策略层再次加权或改变方向、强度、置信评分。

## 24. 与 DecisionSnapshot 的关系

StrategySignal 不直接生成 DecisionSnapshot。

正式关系：

```text
StrategySignal
→ StrategySignalQualityResult
→ DecisionSnapshot
```

只有通过质量检查的 StrategySignal 才能进入 DecisionSnapshot。

StrategySignal 不得输出 ENTER_LONG、ENTER_SHORT、EXIT、HOLD、NO_TRADE 或任何订单动作。

## 25. 与编排层的关系

StrategySignal 是业务模块，不承担编排职责。

业务追溯链：

```text
StrategySignal
→ StrategyRouteDecision
→ StrategyDefinition
→ MarketRegimeSnapshot
→ DomainSignalSet / DomainSignalValue
```

业务表不得保存或查询 OrchestrationRun ID、StepRun ID、步骤序号或编排内部状态。

`StrategySignalStepAdapter` 负责：

```text
调用 StrategySignalService；
理解 created、blocked、failed 和 unknown；
把原始业务结果映射为统一步骤状态；
返回 strategy_signal_id 和对象引用。
```

编排关联只提供整轮快捷查询，不替代业务外键。

## 26. AlertEvent

至少覆盖：

```text
strategy_signal_blocked；
strategy_signal_failed；
strategy_signal_unknown；
strategy_definition_unavailable；
strategy_definition_invalid；
strategy_calculator_missing；
strategy_algorithm_requirement_document_missing；
strategy_implementation_document_missing；
strategy_required_domain_missing；
strategy_domain_source_invalid；
strategy_weight_invalid；
strategy_output_invalid。
```

正常 created bullish、bearish 或 neutral 不写 AlertEvent。

StrategySignal 只写 AlertEvent，不直接发送 Hermes。

## 27. 配置规则

允许环境配置：

```text
STRATEGY_SIGNAL_SCHEMA_VERSION；
短期幂等锁 TTL；
单次最大领域输入数量；
Decimal 精度和统一舍入规则；
calculator 最大允许执行时长。
```

不允许通过 env 动态改变：

```text
StrategyDefinition.params；
allowed / required domain codes；
uses_input_weights；
domain_input_weights；
prediction_horizon；
Definition 生命周期；
enabled；
StrategyAnalysisRelease 策略切片；
algorithm_name 或 algorithm_version；
具体策略公式；
calculator 注册映射。
```

环境配置必须进入 `.env.example` 并带中文注释。

## 28. 服务、任务与命令边界

### 28.1 service

核心业务流程放在 service/domain 层。

StrategySignalService 不得包含具体策略公式、算法版本分支或策略代码硬编码。

### 28.2 Celery task

task 只接收参数、传递 trace_id 和 trigger_source、调用 Service、返回可序列化摘要。

task 不得实现策略算法、解析 calculator 或直接写 StrategySignal。

### 28.3 management command

正式入口：

```bash
python manage.py generate_strategy_signal --strategy-route-decision-id <id> --strategy-analysis-release-id <id> --strategy-analysis-release-hash <hash> --business-request-key <key> --trigger-source manual --trace-id <id>
```

command 只解析参数、调用 Service 和输出结果。

至少输出：

```text
strategy_signal_id；
status；
strategy_code；
strategy_version；
direction；
strength；
confidence；
strategy_analysis_release_id；
strategy_analysis_release_hash；
allows_strategy_signal_quality；
error_code。
```

## 29. 时间与精度

所有业务时间使用 UTC。

`analysis_close_time_utc` 从 DomainSignalSet 业务链继承。

calculator 不得读取当前时间或本地时区改变固定输入结果。

相同 Definition、DomainSignalValue、参数、权重、算法身份和精度配置必须得到确定性一致结果。

Decimal 必须规范序列化，不得保存 NaN 或 Infinity。

## 30. 日志与审计

结构化日志至少包含：

```text
trace_id；
trigger_source；
business_request_key；
strategy_signal_id；
strategy_signal_key；
strategy_route_decision_id；
strategy_definition_id；
domain_signal_set_id；
market_regime_snapshot_id；
strategy_code；
strategy_version；
algorithm_name；
algorithm_version；
definition_hash；
direction；
strength；
confidence；
status；
allows_strategy_signal_quality；
latency_ms；
error_code。
```

日志不得包含密钥、完整历史序列、账户信息或交易建议。

## 31. dry-run 与 confirm-write

dry-run 必须：

```text
读取明确的正式 RouteDecision 与 StrategyAnalysisRelease；
执行与正式模式相同的 Definition、领域输入、Registry、权重和输出校验；
调用相同 calculator；
不写 StrategySignal；
不写正式 AlertEvent；
不允许 StrategySignalQuality 消费内存结果；
明确 persisted = false。
```

confirm-write 如提供，只控制是否落库，不得改变策略、算法、权重或放行标准。

## 32. 测试要求

至少覆盖：

```text
1. StrategyDefinition 可以创建。
2. strategy_code + strategy_version 唯一。
3. params_hash 和 definition_hash 稳定。
4. 本轮冻结版本包选择且路由命中的 active + enabled Definition 可以执行。
5. 非 active 或 enabled = false 的被选 Definition 会阻断正式信号。
6. 未被本轮冻结版本包选择的 Definition 不参与正式执行。
7. RouteRule 只能选择同一版本包策略切片中的 Definition。
8. 路由只能选择已注册 StrategyDefinition。
9. StrategyDefinition 精确解析 calculator。
10. calculator_type 必须为 strategy_signal。
11. calculator 缺失精确版本时 blocked。
12. calculator 不回退其他版本。
13. 算法需求文档、implementation 实现记录身份与 metadata 一致。
14. StrategySignal 只读取明确 strategy_route_decision_id。
15. RouteDecision 不存在时 blocked。
16. RouteDecision 非 created 时 blocked。
17. route_outcome 非 selected 时 blocked。
18. allows_strategy_signal = false 时 blocked。
19. 正式入口拒绝后台研究结果和其他版本包的 Decision。
20. StrategySignal 使用 Decision 绑定的唯一 StrategyDefinition。
21. StrategySignal 不重新路由。
22. StrategySignal 不自动替换策略版本。
23. DomainSignalSet 来源可由 RouteDecision 业务链唯一确定。
24. 不同 DomainSignalSet 的 Value 不能混用。
25. allowed codes 外的 Value 不传给 calculator。
26. required domain 缺失时 blocked。
27. required domain 正常 neutral 或 mixed 仍是有效输入。
28. optional domain 缺失按冻结合同处理。
29. StrategySignal 不读取 AtomicSignalValue。
30. CalculatorInput 不包含 MarketRegimeSnapshot。
31. MarketRegime 不参与策略权重。
32. uses_input_weights 与 calculator metadata 一致。
33. uses_input_weights = true 时实际输入权重完整。
34. 正式权重缺失时不默认使用 1。
35. uses_input_weights = false 时权重为空。
36. 同一 DomainSignalValue 只应用一次权重。
37. calculator 输出合法 bullish。
38. calculator 输出合法 bearish。
39. calculator 输出合法 neutral。
40. 正常 neutral 为 created 且 is_usable = true。
41. calculator failed 不伪装 neutral。
42. direction 非法时 failed。
43. strength 范围为 0 到 1。
44. confidence 范围为 0 到 1。
45. 输入完整不自动 confidence = 1。
46. confidence 不解释为盈利概率。
47. prediction_horizon 合同完整。
48. actual_input_weights 与冻结 Definition 一致。
49. used_domain_signal_value_ids 完整且去重。
50. aggregation_snapshot 可复算。
51. conflict_snapshot 可以解释 neutral。
52. evidence_items 不复制完整上游对象。
53. StrategySignal 正确绑定 RouteDecision、Definition 和 DomainSignalSet。
54. StrategySignal 记录 MarketRegimeSnapshot 但不把它传给 calculator。
55. 同一版本包的正式 created 允许 StrategySignalQuality 消费。
56. 后台研究信号和其他版本包 Signal 不允许 StrategySignalQuality 消费。
57. blocked、failed、unknown 均不允许下游消费。
58. strategy_signal_key 对相同身份稳定。
59. 相同 business_request_key 重复执行返回已有结果。
60. 并发执行只生成一份相同身份 StrategySignal。
61. 事务失败不留下 created 半成品。
62. unknown 先查证，不直接重算。
63. created StrategySignal 不被覆盖。
64. seed 命令幂等。
65. seed 不发明策略或算法。
66. seed 不创建 RouteRule。
67. seed 不恢复停用 Definition。
68. 没有模板时 seed 返回零变更。
69. 每个策略算法版本有独立算法需求文档和 implementation 实现记录。
70. dry-run 调用相同 calculator 但不写库。
71. dry-run 结果不能进入 StrategySignalQuality。
72. StrategySignal 不生成 DecisionSnapshot。
73. StrategySignal 不生成目标仓位。
74. StrategySignal 不读取账户、持仓或 PriceSnapshot。
75. StrategySignal 不请求 Binance。
76. StrategySignal 不调用 DeepSeekGateway。
77. StrategySignal 不保存或查询编排 ID。
78. adapter 显式映射业务结果。
79. 全部业务时间使用 UTC。
80. 新增或停用策略不修改 StrategySignalService 主流程。
81. 后台研究服务复用 calculator 合同，但不写正式 StrategySignal。
82. 正式服务不存在 allow_candidate、ignore_approval 或 use_latest 等绕过参数。
83. 不同策略 calculator 的 direction / strength / confidence / prediction_horizon 具备统一业务语义。
84. 未标准化策略内部指标不得写入 StrategySignal 标准字段。
85. 无法标准化输出语义的策略算法不得进入正式 StrategyAnalysisRelease。
```

具体策略数学测试由对应算法需求文档定义；implementation 实现记录补充代码级测试入口和实际执行结果。

## 33. 验收方式

实现完成后至少执行：

```bash
pytest tests/strategy_signals/
pytest tests/strategy_calculator/ -k strategy_signal
python manage.py seed_strategy_definitions
python manage.py generate_strategy_signal --strategy-route-decision-id <id> --strategy-analysis-release-id <id> --strategy-analysis-release-hash <hash> --business-request-key <key> --trigger-source manual --trace-id <id>
```

版本包未提供可用 StrategyDefinition 时，正确结果是：

```text
StrategyRouting 无法选择版本包内策略；
StrategySignal 不生成伪造结果；
相关步骤保持 fail-closed。
```

数据库至少检查：

```text
Definition 的策略、算法、schema、params、权重和 hash 身份完整；
StrategySignal 正确绑定 RouteDecision、Definition、DomainSignalSet 和 MarketRegimeSnapshot；
StrategySignal 的 StrategyAnalysisRelease 身份与上游链一致；
used_domain_signal_value_ids 全部来自同一 DomainSignalSet；
actual_input_weights 与冻结 Definition 一致；
方向、强度、置信评分、预测期限和证据满足合同；
正式放行字段正确；
重复调用没有生成第二份相同身份 StrategySignal；
业务表没有保存编排 ID。
```

## 34. 模块影响声明

```text
读写 MySQL：是，读取 StrategyRouteDecision、StrategyDefinition、MarketRegimeSnapshot、DomainSignalSet、DomainSignalValue，写 StrategySignal 和必要 AlertEvent；
访问 Redis：可选，仅用于短期锁、幂等和缓存；
访问 Binance：否；
调用 BinanceGateway：否；
发送 Hermes：否；
调用大模型：否；
涉及真实交易：否；
涉及 FeatureLayer：不直接读取；
涉及 AtomicSignal：不直接读取；
涉及 DomainSignal：只消费 DomainSignalSet / DomainSignalValue；
涉及 MarketRegime：只记录追溯上下文，不参与 calculator；
涉及 StrategyRouting：只消费 StrategyRouteDecision；
涉及 StrategySignal：是，本模块自身；
涉及 StrategySignalQuality：只提供正式输入，不执行质量检查；
涉及 DecisionSnapshot：不生成；
涉及账户、PriceSnapshot、OrderPlan、RiskCheck 或 Execution：否；
写 AlertEvent：阻断、失败、未知、Definition/输入/权重/输出非法；
dry-run：可计算但不写正式业务对象；
confirm-write：如提供，只控制落库，不改变策略计算。
```

异常处理：

```text
业务前置条件不满足 → blocked；
calculator 或输出校验失败 → failed；
持久化无法确认 → unknown；
正常中性策略判断 → created + neutral；
任何非 created 结果都不得进入 StrategySignalQuality。
```

## 35. 明确禁止

StrategySignal 禁止：

```text
绕过 StrategyRouteDecision；
重新选择 StrategyDefinition；
自行寻找最近业务对象；
读取 AtomicSignalValue、FeatureValue 或 Kline；
混用不同 DomainSignalSet；
把 MarketRegime 再次用于方向、权重、strength 或 confidence；
同时加权 DomainSignalValue 和其底层 AtomicSignalValue；
使用策略历史表现在线调整权重；
使用 AIReview 参与实时策略判断；
缺失精确 calculator 时自动回退；
自动选择策略的其他版本；
把 confidence 解释为盈利概率；
把 strength 或 confidence 解释为目标仓位；
生成 ENTER_LONG、ENTER_SHORT、EXIT、HOLD 或 NO_TRADE；
生成目标仓位；
生成 CandidateOrderIntent；
执行 RiskCheck；
提交订单；
请求 Binance；
直接发送 Hermes；
保存或查询编排 ID；
让编排关联替代业务外键。
```

## 36. 最终验收标准

StrategySignal 验收通过必须满足：

```text
策略采用 StrategyDefinition + StrategySignal calculator 注册制；
新增或停用策略不修改 Routing 或 Signal Service 主流程；
StrategyRouteDecision 是唯一正式入口；
路由选中的唯一 StrategyDefinition 不被替换；
DomainSignalValue 是唯一正式计算输入；
MarketRegime 只保存为追溯上下文，不进入 calculator；
策略权重只应用于 DomainSignalValue 且只使用一次；
StrategySignalService 与 calculator 职责明确分离；
使用公共 CalculatorRegistry 和稳定 DTO；
calculator 不接收 ORM、存储、网络或编排对象；
所有策略输出字段具备跨策略统一解释；
direction、strength、confidence 和 prediction_horizon 语义明确；
confidence 未校准时不是盈利概率；
normal neutral 与 blocked / failed 明确分离；
每个算法版本有独立算法需求文档和 implementation 实现记录；
版本包没有可用策略算法时不会生成伪造策略信号；
未被版本包选择的策略、后台研究信号和其他版本包 Signal 不进入正式下游；
只有 created 且 allows_strategy_signal_quality = true 的正式 Signal 可被消费；
StrategySignal 不生成目标仓位或订单动作；
MySQL 保存正式事实，Redis 只承担辅助能力；
业务外键独立于编排关联；
全部时间使用 UTC；
不请求 Binance；
不调用大模型；
不涉及真实交易；
不违反项目交易红线。
```

StrategySignal 的最终定位是：

```text
执行 StrategyRouting 已选定并完成注册的策略，基于同一 DomainSignalSet 的领域事实生成可追溯、可验证的策略级方向、强度、置信评分和证据，但不生成目标仓位、订单或交易动作。
```
