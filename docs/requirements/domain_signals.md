# DomainSignal 需求说明

## 1. 模块定位

DomainSignal 是 AtomicSignal 之后、MarketRegime 之前的领域判断层。

它负责把同一分析领域内的多个原子判断，压缩为一个稳定、可解释、可追溯的领域结论。

正式链路为：

```text
FeatureSet / FeatureValue
→ AtomicSignalSet / AtomicSignalValue
→ DomainSignalSet / DomainSignalValue
→ MarketRegimeSnapshot
→ StrategyRouteDecision
→ StrategySignal
```

DomainSignal 负责：

```text
接收明确的 atomic_signal_set_id；
校验 AtomicSignalSet 是否允许领域层消费；
读取本轮 StrategyAnalysisRelease 明确选择的 DomainSignalDefinition；
冻结本次领域定义集合；
按领域读取实际 AtomicSignalValue；
执行同领域聚合 calculator；
生成 DomainSignalSet；
为每个领域生成 DomainSignalValue；
保存覆盖率、一致性、强度和证据；
向 MarketRegime 提供稳定的领域输入。
```

这些职责由稳定的 DomainSignal 业务代码与可替换的 DomainSignal calculator 共同完成：业务代码负责业务对象、状态、放行、持久化和审计，calculator 只负责领域计算。算法变化不得把计算公式重新写入 DomainSignalService。

DomainSignal 不负责：

```text
读取 FeatureValue；
读取 Kline；
重新计算 AtomicSignal；
跨领域识别整体市场环境；
选择 StrategyDefinition；
计算策略权重；
生成 StrategySignal；
生成目标仓位；
读取账户或持仓；
生成订单；
风控审批；
交易执行；
调用大模型。
```

## 2. 领域判断的含义

AtomicSignal 回答一个具体问题，例如：

```text
4h 收盘价是否高于 4h SMA20；
4h SMA20 是否高于 4h SMA60；
4h 动量是否为正；
ATR 标准化值是否处于高位。
```

DomainSignal 回答一个限定领域的问题，例如：

```text
趋势领域当前偏多、偏空还是中性；
动量领域当前增强、减弱还是混合；
波动领域当前偏高、正常还是偏低。
```

DomainSignal 是领域结论，但不是整体市场结论，也不是交易策略结论。

必须区分：

```text
AtomicSignalValue = 单项条件判断；
DomainSignalValue = 同领域条件的聚合判断；
MarketRegimeSnapshot = 跨领域市场环境分类；
StrategySignal = 选定策略产生的策略级判断。
```

## 3. 当前领域范围

当前正式领域范围包括：

```text
market_context = 大级别市场背景领域；
trend          = 趋势领域；
momentum       = 动量领域；
volatility     = 波动领域；
structure      = 支撑压力与区间结构领域；
risk_state     = 市场风险状态领域。
```

允许通过 DomainSignalDefinition 注册其他领域，但必须满足：

```text
领域语义稳定且互相可区分；
输入 AtomicSignalDefinition 明确；
不存在与已有领域重复计算同一证据的问题；
calculator、算法需求文档和 implementation 实现记录完整；
只有被完整 StrategyAnalysisRelease 选择、验证、人工批准并启用后，才能参与正式 MarketRegime。
```

## 4. 核心原则

### 4.1 AtomicSignalSet 是唯一正式输入边界

DomainSignalService 必须接收明确的 `atomic_signal_set_id`。

只允许消费同时满足以下条件的 AtomicSignalSet：

```text
status = created；
is_usable = true；
allows_domain_signal = true；
AtomicSignalValue 集合完整；
required AtomicSignalValue 具有明确状态；
AtomicSignalValue 所属定义位于同一 StrategyAnalysisRelease 原子信号切片；
AtomicSignalValue 按版本包依赖关系恰好归属于当前领域定义。
```

DomainSignal 不得：

```text
自行寻找“最近一份” AtomicSignalSet；
通过 feature_set_id 重新计算 AtomicSignal；
绕过 AtomicSignalSet 读取 FeatureValue；
调用 AtomicSignalService 临时补算；
混用不同 AtomicSignalSet 的 AtomicSignalValue。
```

### 4.2 只聚合同一领域

每个 DomainSignalDefinition 只能表达一个领域。

例如：

```text
trend 定义只聚合趋势类 AtomicSignal；
momentum 定义只聚合动量类 AtomicSignal；
volatility 定义只聚合波动类 AtomicSignal。
```

禁止：

```text
在 trend 定义中同时完成波动环境分类；
在 momentum 定义中选择策略；
在 volatility 定义中生成目标仓位；
在单个 DomainSignalValue 中形成最终交易方向。
```

### 4.3 领域层不使用业务权重

权重只属于 StrategySignal。

DomainSignalDefinition 禁止包含：

```text
signal_weight；
domain_weight；
strategy_weight；
priority_weight；
portfolio_weight。
```

领域 calculator 可以使用确定性的：

```text
必要条件；
允许条件；
阈值；
计数；
比例；
均值；
最小值；
最大值；
中位数；
明确的归一化公式。
```

数学公式中的固定系数如果属于算法本身，必须作为 calculator 参数记录，并且不得被解释为 StrategySignal 的输入权重。

### 4.4 每份原子证据只进入一个正式领域

同一 StrategyAnalysisRelease 内，同一 AtomicSignalDefinition 不得归属于两个 DomainSignalDefinition。

规则：

```text
正式领域归属必须唯一；
领域归属冲突必须在定义校验时阻断；
后台研究组合如允许重叠，也必须在隔离的研究任务中显式记录，不能写入正式 DomainSignalSet；
不得依靠 StrategySignal 再次去重。
```

这条规则用于防止同一市场证据经过多个领域后被 StrategySignal 重复计算。

同一 `domain_code` 在一份 StrategyAnalysisRelease 与 DomainSignalSet 中必须且只能选择一个 DomainSignalDefinition。

规则：

```text
一个领域最多产生一份正式 DomainSignalValue；
MarketRegime 只能读取该领域唯一的正式结果；
正式版本包必须同时包含 market_context、trend、momentum、volatility、structure、risk_state 六个领域；
同领域缺失或存在多个定义时必须 blocked，不得自动选择版本。
```

### 4.5 强度不逐层相乘

AtomicSignalValue.strength 只作为 DomainSignal calculator 的输入。

DomainSignalValue.strength 是领域 calculator 重新生成的领域强度，不是所有 AtomicSignal strength 的连续乘积。

禁止：

```text
atomic_strength × atomic_confidence × domain_factor；
在没有版本化算法合同的情况下把上游 strength 原样复制为 domain strength；
在一个 DomainSignalValue 内重复使用同一 AtomicSignalValue；
把多个领域的 strength 在本模块内继续聚合。
```

单输入领域算法可以在算法合同中明确采用恒等映射，例如把唯一有效原子信号的 strength 作为领域 strength。此时“复制”本身就是经过版本管理的确定性算法，不属于无合同透传；算法文件必须说明适用范围、边界和后续替换方式。

### 4.6 不输出通用 confidence

DomainSignalValue 不输出通用 `confidence` 字段。

本层使用含义明确的字段：

```text
coverage_ratio  = 所需原子证据的覆盖程度；
agreement_ratio = 有效原子证据在领域结论上的一致程度；
strength        = 领域状态或方向的明显程度。
```

这些字段不得被包装成盈利概率。

最终策略置信度由 StrategySignal 根据领域事实和经过验证的策略规则统一计算；MarketRegime 已用于路由，不在策略 calculator 中再次参与评分。

### 4.7 MySQL 是正式事实来源

以下对象必须持久化到 MySQL：

```text
DomainSignalDefinition；
DomainSignalSet；
DomainSignalValue。
```

Redis 只允许用于：

```text
短期幂等控制；
并发互斥；
短期计算缓存；
Celery 任务状态。
```

Redis 不得成为 DomainSignalValue 的唯一存储，也不得作为 MarketRegime 的正式输入来源。

## 5. 输入合同

DomainSignalService 的正式输入至少包括：

```text
atomic_signal_set_id
strategy_analysis_release_id
strategy_analysis_release_hash
expected_domain_signal_definition_set_hash
business_request_key
trace_id
trigger_source
```

### 5.1 atomic_signal_set_id

`atomic_signal_set_id` 是本次领域计算的唯一原子信号事实入口。

服务必须通过该 ID 读取：

```text
AtomicSignalSet 状态和放行字段；
AtomicSignalSet 绑定的 feature_set_id；
market_snapshot_id；
exchange；
market_type；
symbol；
analysis_close_time_utc；
AtomicSignalValue；
AtomicSignalDefinition 身份；
atomic_signal_set_key；
definition_set_hash。
```

### 5.2 StrategyAnalysisRelease 领域切片

正式运行的版本包选择、批准、启用、切换、回滚和后台研究隔离统一遵守 [StrategyAnalysisRelease](strategy_analysis_release.md)。

`strategy_analysis_release_id` 与 `strategy_analysis_release_hash` 必须对应本轮编排开始时冻结的已批准并已启用版本包。DomainSignalService 必须只读取版本包的领域切片，并校验：

```text
market_context、trend、momentum、volatility、structure、risk_state 六个领域全部存在；
每个 domain_code 恰好选择一个 DomainSignalDefinition；
每个被选定义为 active、enabled 且 calculator 已注册；
每个正式 AtomicSignalDefinition 恰好归属于一个被选领域；
领域声明的 required / allowed 原子信号均位于同一版本包原子信号切片；
definition_set_hash 与 expected_domain_signal_definition_set_hash 一致。
```

任一条件不满足时必须 blocked，且不得创建 DomainSignalSet。

### 5.3 business_request_key

`business_request_key` 是调用方提供的不透明业务幂等键。

规则：

```text
DomainSignal 只保存和比较该键；
不得解析其中的编排含义；
相同业务请求重复调用必须返回同一业务结果；
不得因任务重投创建第二份有效 DomainSignalSet。
```

### 5.4 trace_id

`trace_id` 用于跨模块日志和审计关联。

它不是业务外键，不能替代：

```text
atomic_signal_set_id；
domain_signal_set_id；
domain_signal_definition_id；
used_atomic_signal_value_ids。
```

### 5.5 trigger_source

允许表达：

```text
orchestrated
manual
scheduled
recovery
test
```

触发来源不得改变领域算法或放行标准。

## 6. 输出合同

DomainSignalService 必须返回结构化结果，至少包括：

```text
status
domain_signal_set_id
domain_signal_set_key
atomic_signal_set_id
strategy_analysis_release_id
strategy_analysis_release_hash
computed_count
valid_count
invalid_count
required_failed_count
allows_market_regime
error_code
error_message
trace_id
```

DomainSignalSet 允许的业务状态：

```text
created
blocked
failed
unknown
```

### 6.1 created

表示领域集合计算完成，或幂等复用已有完整结果。

必须满足：

```text
所有 required DomainSignalValue 有效；
定义集合身份完整；
DomainSignalSet 与 Value 完整落库；
market_context、trend、momentum、volatility、structure、risk_state 六个正式领域结果齐全。
```

放行规则：

```text
六个领域的 DomainSignalValue 全部有效
+ 所有 is_required = true 的输入有效
+ 正式领域归属唯一且版本包指纹一致
→ allows_market_regime = true；

任一正式领域缺失、计算失败、归属冲突或版本包指纹不一致
→ allows_market_regime = false。
```

`allows_market_regime = true` 只表达 DomainSignalSet 具备被 MarketRegime 检查的基础资格。具体 MarketRegimeDefinition 的 `required_domain_codes` 必须由 MarketRegimeService 在消费时校验，DomainSignal 不读取或推断下游算法配置。

### 6.2 blocked

表示前置业务条件不满足，领域计算未获准执行。

典型原因：

```text
AtomicSignalSet 不存在；
AtomicSignalSet 非 created；
AtomicSignalSet.is_usable = false；
AtomicSignalSet.allows_domain_signal = false；
StrategyAnalysisRelease 不存在、未批准、未启用或指纹不一致；
版本包未完整选择 market_context、trend、momentum、volatility、structure、risk_state 六个领域；
版本包领域切片缺失、多出、重复或定义集指纹不一致；
版本包选择了不可用的 DomainSignalDefinition；
正式领域归属冲突；
定义集合配置非法。
```

blocked 必须：

```text
allows_market_regime = false；
domain_signal_set_id = null；
domain_signal_set_key = null；
不创建 DomainSignalSet 或 DomainSignalValue；
不得生成可消费 DomainSignalValue；
不得进入 MarketRegime。
```

`blocked` 是前置条件校验结果，不是已持久化 DomainSignalSet 的生命周期状态。重复请求必须重新读取本轮冻结版本包和上游事实，不得改用后来启用的版本包。

### 6.3 failed

表示已经进入领域计算，但发生明确的集合级失败。

典型原因：

```text
required DomainSignalValue 失败；
required AtomicSignalValue 缺失或无效；
AtomicSignalValue 来源混用；
calculator 缺失；
输出范围或状态非法；
证据合同不完整；
数据库事务明确回滚。
```

failed 必须：

```text
allows_market_regime = false；
保存明确 error_code；
不得被 MarketRegime 消费。
```

### 6.4 unknown

表示无法安全确认本次结果是否完整提交。

unknown 必须：

```text
allows_market_regime = false；
不得自动放行；
不得立即重复插入；
先按 business_request_key 和 domain_signal_set_key 查证；
必要时写 AlertEvent。
```

## 7. DomainSignalDefinition

DomainSignalDefinition 是正式运行时领域判断字典。

建议字段：

```text
id
domain_code
display_name
description
category
output_mode
algorithm_name
algorithm_version
params
params_hash
definition_hash
status
enabled
is_required
allowed_atomic_signal_codes
required_atomic_signal_codes
minimum_coverage_ratio
agreement_threshold
created_at_utc
updated_at_utc
```

### 7.1 domain_code

`domain_code` 必须稳定、唯一、可读。

当前代码：

```text
trend
momentum
volatility
```

不得使用策略或交易动作命名，例如：

```text
buy_domain
sell_domain
entry_domain
position_domain
order_domain
```

### 7.2 output_mode

允许值：

```text
directional
state
```

含义：

```text
directional = 输出 bullish / bearish / neutral；
state       = 输出非方向性状态代码。
```

建议：

```text
trend      → directional；
momentum   → directional；
volatility → state。
```

非方向性领域必须：

```text
direction = none；
state_code 非空。
```

### 7.3 algorithm_name 与 algorithm_version

`algorithm_name` 表示领域聚合算法族。

候选算法族：

```text
directional_consensus
threshold_consensus
state_classifier
```

`algorithm_version` 表示算法实现的不可变身份。

注册键：

```text
algorithm_name + algorithm_version
```

相同注册键的计算行为不得发生不兼容变化。

### 7.4 params

`params` 保存领域 calculator 参数，例如：

```text
方向阈值；
中性区间；
强度标准化边界；
状态分类阈值；
最少有效输入数；
边界值处理规则。
```

params 不得包含：

```text
策略权重；
目标仓位；
订单数量；
账户权益；
路由结果；
动态在线优化参数。
```

### 7.5 params_hash

`params_hash` 建议使用：

```text
sha256(canonical_json(params))
```

规范化输入不得包含 trace_id、任务 ID、当前时间或编排信息。

### 7.6 definition_hash

`definition_hash` 至少覆盖：

```text
domain_code；
output_mode；
algorithm_name；
algorithm_version；
params_hash；
is_required；
allowed_atomic_signal_codes；
required_atomic_signal_codes；
minimum_coverage_ratio；
agreement_threshold。
```

`enabled` 是算法库可用性开关，不进入不可变 definition_hash。它不代表定义自动进入正式运行；正式集合由 StrategyAnalysisRelease 领域切片与 definition_set_hash 共同冻结。

### 7.7 status

允许的生命周期状态：

```text
draft
active
deprecated
retired
disabled
```

可被 StrategyAnalysisRelease 选择的定义必须满足：

```text
status = active；
enabled = true。
```

被历史结果引用的 DomainSignalDefinition 不得物理删除。

`status = active` 与 `enabled = true` 只表示定义在算法库中可供选择，不表示它会自动进入正式 DomainSignalSet。

### 7.8 enabled

`enabled` 控制定义是否可被新版本包选择、以及已启用版本包执行时该定义是否仍可用：

```text
enabled = true  → 可供版本包选择；被本轮冻结版本包选择后才参与正式计算；
enabled = false → 不得被新版本包选择；若当前正式版本包仍引用它，正式执行必须 blocked 并触发运维告警。
```

### 7.9 正式参与资格

DomainSignalDefinition 不保存额外的算法运行等级或“参与正式 MarketRegime”开关。

正式参与资格由完整版本包决定：

```text
定义被本轮 StrategyAnalysisRelease 领域切片选择；
定义为 active 且 enabled；
同一 domain_code 只选择一个定义；
market_context、trend、momentum、volatility、structure、risk_state 六个领域齐全；
原子依赖与同一版本包原子信号切片一致。
```

未满足这些条件的定义不得由正式 DomainSignalService 运行。后台研究与回测通过独立研究服务自由组合，不得借用正式服务绕过批准。

### 7.10 is_required

`is_required` 表示该领域无法计算时是否阻断整个 DomainSignalSet。

规则：

```text
required 领域无法计算 → DomainSignalSet failed；
optional 领域无法计算 → 保存 failed DomainSignalValue；
MarketRegime 仍需按自己的 required domain 合同决定是否阻断。
```

`is_required` 不表示该领域必须为 bullish、bearish 或某个指定状态。

### 7.11 allowed_atomic_signal_codes

列出该领域允许读取的 AtomicSignalDefinition。

DomainSignalService 不得读取列表之外的 AtomicSignalValue；列表中的定义必须位于同一 StrategyAnalysisRelease 原子信号切片，并且只能归属于当前领域。

### 7.12 required_atomic_signal_codes

列出完成该领域计算必须存在且有效的原子信号。

必须区分：

```text
required 原子信号计算成功但条件不成立 = 正常领域输入；
required 原子信号缺失或 is_valid = false = 领域失败。
```

### 7.13 minimum_coverage_ratio

覆盖率定义：

```text
coverage_ratio
= 有效 allowed AtomicSignalValue 数量
  / 本次定义要求评估的 AtomicSignal 数量
```

如果覆盖率低于定义阈值：

```text
DomainSignalValue.status = failed；
DomainSignalValue.is_valid = false。
```

### 7.14 agreement_threshold

一致性表示有效原子证据对领域结论的方向或状态一致程度。

具体计算公式必须由 algorithm implementation 文件定义。

当 agreement_ratio 未达到 agreement_threshold 时，正常业务含义可以是：

```text
direction = neutral；
state_code = mixed；
status = created；
is_valid = true。
```

不得把正常分歧自动当作计算失败。

单输入领域算法适用以下固定语义：

```text
唯一 required 原子信号存在且有效 → coverage_ratio = 1；
唯一 required 原子信号缺失或无效 → 领域计算失败；
agreement_ratio = null；
不应用 agreement_threshold；
direction、state_code 与 strength 由该算法版本的明确合同生成。
```

单输入算法不得伪造 `agreement_ratio = 1`，因为一份证据不存在“多项一致性”。

## 8. DomainSignalSet

DomainSignalSet 表示在一份 AtomicSignalSet 上、使用一组冻结领域定义得到的领域判断集合。

建议字段：

```text
id
domain_signal_set_key
business_request_key
atomic_signal_set_id
feature_set_id
strategy_analysis_release_id
strategy_analysis_release_hash
market_snapshot_id
exchange
market_type
symbol
analysis_close_time_utc
domain_schema_version
definition_set_hash
status
is_usable
allows_market_regime
selected_definition_count
computed_count
valid_count
invalid_count
required_failed_count
payload_summary
error_code
error_message
trace_id
trigger_source
started_at_utc
finished_at_utc
created_at_utc
updated_at_utc
```

### 8.1 粒度

正式结果粒度：

```text
一份 AtomicSignalSet
+ 一份冻结的 DomainSignalDefinition 集合
+ 一个 domain_schema_version
→ 最多一份可消费 DomainSignalSet
```

DomainSignalSet 不按任务执行次数重复创建。

### 8.2 domain_signal_set_key

建议输入：

```text
atomic_signal_set_id；
atomic_signal_set_key；
domain_schema_version；
definition_set_hash。
```

规则：

```text
必须具有数据库唯一约束；
相同输入身份只能生成一份正式结果；
并发调用不得创建两个 created 集合；
重复调用返回已有完整结果。
```

### 8.3 definition_set_hash

`definition_set_hash` 是本次冻结领域定义集合的指纹。

必须按稳定顺序覆盖每个定义的：

```text
domain_code；
definition_hash；
is_required。
```

该集合必须严格等于本轮 StrategyAnalysisRelease 的领域切片，且必须包含 market_context、trend、momentum、volatility、structure、risk_state 各一个定义。数据库中其他 active 或 enabled 定义不得加入本次 definition_set_hash。

definition_set_hash 不能替代 DomainSignalValue 对 DomainSignalDefinition 的逐条绑定。

### 8.4 状态与放行字段

必须满足：

```text
created → is_usable = true；
blocked → is_usable = false → allows_market_regime = false；
failed  → is_usable = false → allows_market_regime = false；
unknown → is_usable = false → allows_market_regime = false。
```

created 的放行规则：

```text
market_context、trend、momentum、volatility、structure、risk_state 六个正式领域结果全部有效
+ 所有 is_required = true 的 DomainSignalValue 有效
+ 正式领域归属唯一且版本包指纹一致
→ allows_market_regime = true；

任一正式领域缺失
或正式领域计算失败
或正式领域归属冲突
→ allows_market_regime = false。
```

正式服务不得创建仅供研究使用的 DomainSignalSet。无法满足六个领域完整性与放行条件时，应按发生阶段返回 blocked 或持久化 failed，不得以 created 规避失败。

MarketRegimeDefinition 的 required domain 合同属于下游配置，由 MarketRegimeService 校验，不参与 DomainSignalSet 的放行计算。

### 8.5 payload_summary

只保存小型摘要：

```text
领域定义数量；
有效领域数量；
失败领域数量；
版本包身份；
definition_set_hash；
主要错误代码。
```

不得复制全部 AtomicSignalValue、DomainSignalValue 或证据明细。

## 9. DomainSignalValue

DomainSignalValue 是 DomainSignalSet 内某个 DomainSignalDefinition 的正式结果。

建议字段：

```text
id
domain_signal_set_id
domain_signal_definition_id
domain_code
output_mode
direction
state_code
strength
coverage_ratio
agreement_ratio
status
is_valid
definition_status
definition_enabled
algorithm_name
algorithm_version
params_hash
definition_hash
used_atomic_signal_codes
used_atomic_signal_value_ids
evidence_items
evidence_text_zh
payload_summary
error_code
error_message
calculated_at_utc
latency_ms
created_at_utc
```

### 9.1 定义绑定

每条 DomainSignalValue 必须绑定具体 DomainSignalDefinition。

同时冗余保存：

```text
domain_code；
output_mode；
algorithm_name；
algorithm_version；
params_hash；
definition_hash。
```

冗余字段不能替代真实外键。

### 9.2 status

DomainSignalValue 允许：

```text
created
failed
```

正常中性、混合、低强度或条件不满足仍然是：

```text
status = created；
is_valid = true。
```

### 9.3 direction

方向型领域允许：

```text
bullish
bearish
neutral
```

状态型领域必须：

```text
direction = none。
```

方向是领域倾向，不是交易动作。

### 9.4 state_code

`state_code` 用于表达领域内部状态。

示例语义：

```text
trend      → aligned / mixed / unclear；
momentum   → strengthening / weakening / mixed；
volatility → high / normal / low / expanding / contracting。
```

实际允许值必须由 DomainSignalDefinition 和 calculator implementation 固定。

不得让同一 algorithm_version 在运行时产生未登记的状态代码。

### 9.5 strength

范围：

```text
0 <= strength <= 1
```

含义：

```text
directional 模式 → 领域方向的明显程度；
state 模式       → 当前 state_code 的明显程度。
```

strength 必须由 calculator 根据 AtomicSignalValue 重新计算。

不得：

```text
原样复制某个 AtomicSignalValue.strength；
把所有 AtomicSignal strength 连乘；
乘以 StrategySignal 权重；
解释为目标仓位比例。
```

### 9.6 coverage_ratio

范围：

```text
0 <= coverage_ratio <= 1
```

coverage_ratio 只表示证据覆盖情况，不表示预测胜率。

### 9.7 agreement_ratio

范围：

```text
0 <= agreement_ratio <= 1
```

agreement_ratio 只表示同领域有效证据的一致程度，不表示策略置信度。

### 9.8 used_atomic_signal_codes 与 used_atomic_signal_value_ids

必须记录实际参与计算的 AtomicSignalValue。

追溯链：

```text
DomainSignalValue
→ used_atomic_signal_value_ids
→ AtomicSignalValue
→ AtomicSignalSet
→ FeatureSet
→ MarketSnapshot
```

校验要求：

```text
所有 AtomicSignalValue 属于同一 AtomicSignalSet；
signal_code 位于 allowed_atomic_signal_codes；
required code 全部存在；
使用前 AtomicSignalValue.is_valid = true；
不得只记录定义依赖而不记录实际使用值。
```

### 9.9 evidence_items

必须保存机器可读证据，至少包括：

```text
实际 AtomicSignalValue ID；
signal_code；
direction 或 state；
strength；
is_valid；
领域 calculator 的中间统计；
覆盖率；
一致性；
最终方向或状态；
最终强度。
```

不得保存完整 FeatureValue 或 Kline 副本。

### 9.10 evidence_text_zh

必须保存中文领域说明。

例如：

```text
趋势领域共评估 3 个原子信号，3 个有效，其中 2 个偏多、1 个中性；领域方向为偏多，强度为 0.62，证据覆盖率为 1.00。
```

失败示例：

```text
趋势领域计算失败：必需原子信号 sma_4h_20_above_sma_4h_60 无有效结果，无法形成领域结论。
```

中文说明不得包含交易建议、目标仓位、订单方向或杠杆建议。

## 10. DomainSignalService 与 calculator 边界

### 10.1 公共合同

所有 DomainSignal calculator 必须遵守 [StrategyCalculator 公共合同](strategy_calculator.md)。纯计算、DTO、计算状态、异常、确定性、精度、Registry、算法版本和副作用隔离的通用规则，以该公共合同为准。

本文件只增加 DomainSignal 特有的业务合同与聚合边界。实现时不得复制并形成第二套公共 Calculator 规则。

### 10.2 稳定业务代码

DomainSignalService 负责：

```text
读取并校验 AtomicSignalSet / AtomicSignalValue；
读取、校验并冻结 DomainSignalDefinition；
校验正式领域归属和原子证据归属；
把 ORM 对象转换为不可变 DomainSignalCalculatorInput DTO；
通过公共 CalculatorRegistry 精确定位 calculator；
调用 calculator 并校验 DomainSignalCalculatorOutput DTO；
把计算成功或失败映射为 DomainSignalValue 业务状态；
汇总 DomainSignalSet 状态与 allows_market_regime；
处理幂等、并发、事务、unknown、恢复和 AlertEvent；
持久化正式业务对象并返回结构化业务结果。
```

只要 DTO 和业务合同保持兼容，新增或替换领域算法不得要求修改上述业务流程。

### 10.3 可替换计算代码

DomainSignalCalculatorInput 至少包含：

```text
同一 AtomicSignalSet、同一领域的不可变 AtomicSignalValue DTO；
冻结的 allowed / required atomic signal codes；
冻结的 DomainSignalDefinition params；
公共合同要求的 schema、精度和算法身份信息。
```

其中 AtomicSignalValue DTO 必须来自当前 DomainSignalDefinition 允许的代码集合、同一 AtomicSignalSet 和同一 StrategyAnalysisRelease，并同时满足 `status = created`、`is_valid = true`。AtomicSignalValue.confidence 不得作为默认权重传入计算公式；如算法需要使用，必须由该领域 calculator 的版本化合同单独说明，且不得与 strength 形成未经定义的重复加权。

不得把 Django model、QuerySet、数据库连接、Redis client、service 或编排对象传入 calculator。

DomainSignalCalculatorOutput 至少包含：

```text
calculation_status = succeeded / failed；
direction；
state_code；
strength；
coverage_ratio；
agreement_ratio；
结构化证据与中间统计；
失败时的 error_code / error_message。
```

CalculatorOutput 不得返回 `created / blocked / unknown` 等业务状态，也不得决定 `allows_market_regime`。这些结果只能由 DomainSignalService 根据业务前置条件、calculator 输出和 Definition 配置确定。

### 10.4 DomainSignal 特有禁止项

除公共合同的副作用禁令外，DomainSignal calculator 还不得：

```text
跨领域读取或聚合 AtomicSignalValue；
重复使用同一 AtomicSignalValue 计分；
调用 AtomicSignalService 或其他 calculator；
创建 DomainSignalSet 或 DomainSignalValue；
决定 Definition 生命周期或启用状态；
识别 MarketRegime；
选择策略或使用策略权重；
输出通用 confidence；
生成 StrategySignal、DecisionSnapshot、目标仓位或订单对象。
```

## 11. CalculatorRegistry 与算法身份

DomainSignal 使用 [StrategyCalculator 公共合同](strategy_calculator.md)定义的公共 CalculatorRegistry，不建立模块私有 Registry。

每个 DomainSignal calculator 必须声明：

```text
calculator_type = domain_signal；
algorithm_name；
algorithm_version；
input_schema_version；
output_schema_version；
algorithm_requirement_document_path；
implementation_document_path。
```

DomainSignal 特有规则：

```text
被本轮冻结 StrategyAnalysisRelease 选择的 DomainSignalDefinition 必须为 active、enabled 且能精确解析到对应 calculator；
解析结果的 calculator_type 必须为 domain_signal；
不得在 DomainSignalService 中维护大型 if / elif 算法分发；
不得把 MarketRegime 分类器注册为 DomainSignal calculator；
不得把 StrategySignal 加权算法注册为 DomainSignal calculator。
```

## 12. 默认定义与运行时定义

必须区分：

```text
default_domain_signal_definitions.py = 受代码管理的默认模板；
DomainSignalDefinition 表            = 可供组合选择的算法定义库；
StrategyAnalysisRelease 领域切片     = 正式运行时集合。
```

正式计算只读取本轮冻结版本包切片中同时满足以下条件的定义：

```text
status = active；
enabled = true。
```

DomainSignalService 不得：

```text
直接读取默认模板参与正式计算；
把默认模板与数据库定义求合集；
把版本包切片与数据库其他 active 定义求合集；
自动恢复 retired 或 disabled 定义；
通过运行参数临时增删版本包定义。
```

## 13. seed_domain_signal_definitions

必须提供幂等初始化入口：

```bash
python manage.py seed_domain_signal_definitions
```

命令负责：

```text
读取默认模板；
规范化 params；
计算 params_hash；
计算 definition_hash；
校验原子信号领域归属；
按完整定义身份写入 DomainSignalDefinition；
输出初始化摘要。
```

命令不得：

```text
生成 DomainSignalSet；
生成 DomainSignalValue；
调用 DomainSignalService；
修改 AtomicSignalSet 或 AtomicSignalValue；
恢复 retired 或 disabled 定义；
覆盖人工 enabled 配置；
修改任何 StrategyAnalysisRelease；
覆盖已经使用过的身份字段。
```

## 14. 算法需求文档与 implementation 实现记录

每个正式领域 calculator 必须遵守 [StrategyCalculator 公共合同](strategy_calculator.md)中的算法需求文档、implementation 实现记录、版本、代码一致性和验证状态规则。

每个领域算法版本必须同时具备：

```text
算法需求文档；
implementation 实现记录。
```

算法需求文档负责定义领域聚合公式、输入原子信号语义、参数、边界和验证要求，应放在 requirements 下的对应领域算法目录，具体目录由后续领域算法需求文件统一确定，例如：

```text
docs/requirements/<领域算法模块>/<domain_or_algorithm>.md
```

implementation 实现记录负责记录代码落地位置、calculator、DTO、测试入口和实现差异，统一目录：

```text
docs/implementation/domain_signal/
```

除公共合同要求的通用内容外，DomainSignal 算法需求文档还必须记录：

```text
适用 domain_code 与 output_mode；
允许和必需的 AtomicSignal 输入语义；
领域方向或状态的完整判定公式；
strength 归一化公式；
coverage_ratio 公式；
agreement_ratio 公式；
防止重复计算规则；
同领域证据冲突的处理规则；
领域专用计算示例和 golden test。
```

算法行为变化必须使用不同 algorithm_version，并先形成新的算法需求文档；对应代码实现完成后，再形成新的 implementation 实现记录。

DomainSignalDefinition 的具体参数组合由 `params / params_hash / definition_hash` 表达；参数不同但 calculator 行为相同，不重复创建算法需求版本文件或 implementation 实现记录。

## 15. 算法验证与正式发布

DomainSignal 框架不等于领域算法已经具备预测价值。

每个领域算法必须支持以下验证：

```text
时间顺序回测；
样本外验证；
walk-forward 验证；
参数敏感性测试；
与简单原子信号基准比较；
领域聚合增量价值测试；
消融测试；
手续费、滑点和资金费率后的策略影响评估。
```

所有已实现、已注册并通过一致性验证的算法版本在已验证算法目录中平权。算法本身不保存运行等级身份；正式资格只属于本轮冻结的、经过验证、人工批准并启用的完整 StrategyAnalysisRelease。

后台研究与回测服务可以自由选择领域定义及其上下游组合，结果必须写入隔离的研究对象，不得写入 DomainSignalSet，也不得调用正式 DomainSignalService 的绕过参数。

### 15.1 初始单输入算法

为支持流程搭建与简单基准比较，可以登记：

```text
algorithm_name = single_atomic_passthrough
```

其算法合同必须明确：

```text
只接受一个 required AtomicSignalValue；
输入有效时 coverage_ratio = 1；
agreement_ratio = null；
不执行 agreement_threshold；
direction 与 state_code 按领域输出模式映射；
strength 使用该算法需求文档明确的恒等或归一化公式；
输入缺失或无效时返回计算失败。
```

该算法只是可选择的基准算法，不自动进入正式链路。其实现必须记录在独立 algorithm_version 文件中；以后替换聚合逻辑时新增算法版本，不修改 DomainSignalService。

如果算法库尚不能为 market_context、trend、momentum、volatility、structure、risk_state 六个领域组成完整版本包，则不得批准或启用正式 StrategyAnalysisRelease；系统应在 FeatureLayer 前阻断，而不是用空领域或默认值补齐。

## 16. DomainSignalService 主流程

标准流程：

```text
1. 接收 atomic_signal_set_id、StrategyAnalysisRelease 身份、business_request_key、trace_id、trigger_source；
2. 校验请求字段；
3. 按 business_request_key 查询已有结果；
4. 读取 AtomicSignalSet；
5. 校验 status、is_usable 和 allows_domain_signal；
6. 校验 AtomicSignalSet 与本轮 StrategyAnalysisRelease 身份和原子信号切片一致；
7. 读取 AtomicSignalValue 并构建 signal_code → Value 映射；
8. 读取版本包领域切片，不追加其他 active 定义；
9. 校验 market_context、trend、momentum、volatility、structure、risk_state 各一个定义以及原子证据唯一归属；
10. 校验所有 Definition 为 active、enabled 且 calculator 已注册；
11. 冻结定义集合、计算 definition_set_hash 并与版本包预期指纹比较；
12. 生成 domain_signal_set_key；
13. 按 domain_signal_set_key 查询已有完整结果；
14. 校验每个领域的 allowed / required AtomicSignal 依赖；
15. 将业务对象转换为不可变 DomainSignalCalculatorInput DTO；
16. 逐个执行领域 calculator；
17. 校验 DomainSignalCalculatorOutput DTO；
18. 把 calculation_status 映射为 DomainSignalValue 业务状态；
19. 单项失败时形成 failed DomainSignalValue；
20. 汇总 required_failed_count；
21. 决定集合状态和 allows_market_regime；
22. 在数据库事务中写 DomainSignalSet 与 DomainSignalValue；
23. 写必要 AlertEvent；
24. 返回结构化业务结果。
```

计算期间冻结的定义集合不得重新读取并替换。

## 17. 单项失败处理

DomainSignalValue 失败时必须写入：

```text
status = failed；
is_valid = false；
direction = none；
state_code 为空；
strength = 0；
coverage_ratio 保存实际值；
agreement_ratio 为空或保存可计算值；
error_code 非空；
error_message 非空；
evidence_text_zh 非空。
```

失败不得伪装为正常 neutral、mixed 或 low。

## 18. 集合失败处理

以下任一条件成立时 DomainSignalSet 必须 failed：

```text
required_failed_count > 0；
正式领域归属冲突；
AtomicSignalValue 来源混用；
定义集合身份不完整；
输出合同不满足；
数据库事务明确失败。
```

集合失败必须：

```text
is_usable = false；
allows_market_regime = false；
写 domain_signal_set_failed AlertEvent；
不得进入 MarketRegime。
```

## 19. 写库与事务

DomainSignalSet 与 DomainSignalValue 必须在同一个数据库事务中正式写入。

要求：

```text
使用 transaction.atomic() 或等价 Django 事务；
DomainSignalValue 使用 bulk_create 或等价批量写入；
数据库唯一约束保护 business_request_key 和 domain_signal_set_key；
不得出现 DomainSignalSet created 但 Value 只写一部分；
不得在数据库长事务中执行外部请求；
不得在事务中等待其他模块。
```

## 20. 幂等与并发

### 20.1 重复调用

相同 business_request_key：

```text
已有 created → 返回已有 DomainSignalSet；
已有 blocked → 返回已有阻断结果；
已有 failed → 返回已有失败结果，受控恢复入口可重新核验；
已有 unknown → 先查证，不直接再次计算。
```

### 20.2 相同输入身份

即使 business_request_key 不同，只要以下身份相同：

```text
atomic_signal_set_id；
domain_schema_version；
definition_set_hash。
```

也不得生成两份相同的正式 DomainSignalSet。

### 20.3 并发冲突

并发安全依靠：

```text
数据库唯一约束；
原子创建；
必要的短期 Redis 锁。
```

Redis 锁失效不能破坏数据库唯一性。

## 21. unknown 与恢复

数据库返回结果不明确时：

```text
不得假设写入失败；
不得立即重复插入；
按 business_request_key 和 domain_signal_set_key 查证；
核对 Value 数量、definition_set_hash 和 required 结果；
无法确认时保持 unknown 并告警。
```

受控恢复必须检查：

```text
AtomicSignalSet 是否仍然可用；
DomainSignalSet 是否存在；
DomainSignalValue 数量是否与冻结定义集合一致；
每条 Value 是否绑定正确 Definition；
required 领域是否全部有效；
原子证据归属是否唯一。
```

不得覆盖已经 created 的 DomainSignalSet 重新计算。

## 22. MarketRegime 消费合同

MarketRegime 只允许消费：

```text
DomainSignalSet.status = created；
DomainSignalSet.is_usable = true；
DomainSignalSet.allows_market_regime = true；
DomainSignalValue.status = created；
DomainSignalValue.is_valid = true；
DomainSignalDefinition.status = active；
DomainSignalDefinition.enabled = true；
DomainSignalSet 与 MarketRegime 使用同一 StrategyAnalysisRelease。
```

MarketRegime 必须：

```text
消费明确的 domain_signal_set_id；
记录实际使用的 domain_signal_value_id；
不得重新计算 DomainSignal；
不得直接读取 AtomicSignalValue 参与环境分类；
不得读取版本包领域切片之外的 DomainSignalValue；
不得读取后台研究结果用于正式分类。
```

## 23. 与 StrategySignal 的关系

StrategySignal 不得绕过 DomainSignal，重复加权 DomainSignalValue 已经使用过的 AtomicSignalValue。

正式方向聚合规则：

```text
AtomicSignalValue 只在 DomainSignal 内被使用；
DomainSignalValue 才是 StrategySignal 的方向和状态输入；
MarketRegimeSnapshot 只用于路由和审计追溯，不进入 StrategySignal calculator；
策略权重只应用于 DomainSignalValue。
```

DomainSignal 不输出策略权重，也不决定 StrategySignal 最终方向。

## 24. 与编排层的关系

DomainSignal 是业务模块，不承担编排职责。

业务追溯链：

```text
DomainSignalValue
→ DomainSignalSet
→ AtomicSignalSet
→ FeatureSet
→ MarketSnapshot
```

DomainSignal 业务表不得保存或查询：

```text
orchestration_run_id；
orchestration_step_run_id；
编排对象关联表。
```

编排流程由 `DomainSignalStepAdapter` 负责：

```text
接收 atomic_signal_set_id 和 business_request_key；
调用 DomainSignalService；
理解 DomainSignal 原始业务结果；
把 created / blocked / failed / unknown 映射为统一状态和 flow_action；
向编排层返回 domain_signal_set_id 及对象引用。
```

编排层可以登记 DomainSignalSet 根对象，并由根对象展开 DomainSignalValue；该关联不替代业务外键。

## 25. AlertEvent

成功且无单项失败时默认只写结构化日志，不强制写 AlertEvent。

应写事件：

```text
domain_signal_blocked
domain_signal_failed
domain_signal_set_failed
domain_signal_set_unknown
domain_signal_definition_invalid
domain_signal_calculator_missing
domain_signal_membership_conflict
```

规则：

```text
DomainSignal 只写 AlertEvent；
不得直接调用 Hermes；
不得直接调用 Notifications 发送消息；
AlertEvent 不触发交易；
告警失败不能把 failed 结果改为 created。
```

## 26. 配置规则

允许环境配置：

```text
DOMAIN_SIGNAL_SCHEMA_VERSION；
单次允许计算的最大领域数量；
短期幂等锁 TTL；
Decimal 精度和统一舍入规则。
```

不允许通过 env 动态改变：

```text
DomainSignalDefinition.params；
allowed / required atomic signal codes；
Definition 生命周期；
enabled；
StrategyAnalysisRelease 领域切片；
具体算法公式；
calculator 注册映射。
```

所有环境配置进入 `.env.example` 并带中文注释。

## 27. 服务、任务与命令边界

### 27.1 service

核心业务逻辑放在 service/domain 层。

DomainSignalService 负责：

```text
输入校验；
AtomicSignalSet 放行检查；
版本包与领域切片校验；
定义冻结；
领域归属校验；
原子依赖解析；
calculator 调度；
失败隔离；
集合汇总；
事务落库；
幂等返回。
```

DomainSignalService 不得包含具体领域公式、算法分支或算法版本专用处理。领域算法只能通过稳定 DTO 和公共 CalculatorRegistry 接入。

### 27.2 Celery task

Celery task 只负责：

```text
接收参数；
传递 trace_id 和 trigger_source；
调用 DomainSignalService；
返回可序列化摘要。
```

task 不得实现领域算法或直接写业务对象。

### 27.3 management command

手动构建入口：

```bash
python manage.py build_domain_signals --atomic-signal-set-id <id> --strategy-analysis-release-id <id> --strategy-analysis-release-hash <hash> --business-request-key <key> --trigger-source manual --trace-id <id>
```

command 只负责解析参数、调用 service 和输出结果。

至少输出：

```text
domain_signal_set_id；
domain_signal_set_key；
strategy_analysis_release_id；
strategy_analysis_release_hash；
status；
computed_count；
valid_count；
invalid_count；
allows_market_regime。
```

## 28. 时间与精度

所有时间统一使用 UTC。

规则：

```text
analysis_close_time_utc 从 AtomicSignalSet 业务链继承；
calculated_at_utc 使用 UTC；
不得用本地时区参与领域判断；
不得用运行时当前时间改变固定输入；
Decimal 写入 JSON 时转换为字符串；
不得使用不可控 float 保存正式数值。
```

同一 AtomicSignalSet、同一定义集合和同一算法身份必须得到确定性一致结果。

## 29. 日志与审计

结构化日志至少包含：

```text
trace_id；
trigger_source；
business_request_key；
atomic_signal_set_id；
domain_signal_set_id；
domain_signal_set_key；
definition_set_hash；
status；
computed_count；
valid_count；
invalid_count；
required_failed_count；
error_code；
latency_ms。
```

日志不得包含完整 AtomicSignalValue、完整证据集合、Kline、密钥或不可控长 JSON。

## 30. dry-run 与 confirm-write

DomainSignal 可以支持 dry-run。

dry-run 必须：

```text
读取明确的 AtomicSignalSet；
执行与正式模式相同的放行、归属、依赖和 calculator 校验；
不写 DomainSignalSet；
不写 DomainSignalValue；
不写正式业务 AlertEvent；
不允许 MarketRegime 消费内存结果；
明确返回 persisted = false。
```

如提供 confirm-write：

```text
只控制是否落库；
不得绕过 required 领域失败；
不得绕过 StrategyAnalysisRelease 身份、批准状态或定义切片；
不得把 blocked、failed 或 unknown 强制写成 created。
```

## 31. 测试要求

至少覆盖：

```text
1. DomainSignalDefinition 可以创建。
2. params_hash 对相同规范化参数稳定。
3. definition_hash 对相同定义稳定。
4. 本轮冻结版本包选择的 active 且 enabled 定义参与正式计算。
5. 未被本轮冻结版本包选择的 active 且 enabled 定义不参与正式计算。
6. 非 active 或 enabled = false 的被选定义会阻断正式计算。
7. 版本包不存在、未批准、未启用或 release_hash 不一致时 blocked。
8. 版本包领域切片缺项、多项、重复或 definition_set_hash 不一致时 blocked。
9. 同一版本包中相同原子信号不能属于两个正式领域。
10. 后台研究的重叠组合不得写入正式 DomainSignalSet。
11. 正式版本包必须包含 market_context、trend、momentum、volatility、structure、risk_state 各一个定义。
12. 同领域缺失或存在多个定义时 blocked，不自动选择。
13. CalculatorRegistry 按完整算法身份定位实现。
14. calculator 缺失时不生成可消费集合。
15. 重复 calculator 注册被拒绝。
16. DomainSignal 只读取明确的 atomic_signal_set_id。
17. AtomicSignalSet 不存在时 blocked。
18. AtomicSignalSet 非 created 时 blocked。
19. AtomicSignalSet.is_usable = false 时 blocked。
20. AtomicSignalSet.allows_domain_signal = false 时 blocked。
21. DomainSignal 不读取 FeatureValue 或 Kline。
22. DomainSignal 不调用 AtomicSignalService。
23. 不同 AtomicSignalSet 的 Value 不能混用。
24. allowed codes 之外的 Value 不参与计算。
25. 版本包原子信号切片之外的 AtomicSignalValue 不参与正式领域计算。
26. required AtomicSignalValue 缺失时领域失败。
27. required 原子条件正常不成立不会被误判为缺失。
28. invalid AtomicSignalValue 不参与正常计算。
29. DomainSignalSet 绑定 AtomicSignalSet。
30. DomainSignalValue 绑定 DomainSignalDefinition。
31. DomainSignalValue 记录实际 used_atomic_signal_value_ids。
32. used values 全部属于同一 AtomicSignalSet。
33. directional 模式输出合法 direction。
34. state 模式 direction = none 且 state_code 非空。
35. strength 范围为 0 到 1。
36. coverage_ratio 范围为 0 到 1。
37. agreement_ratio 范围为 0 到 1。
38. DomainSignalValue 不输出通用 confidence。
39. DomainSignalDefinition 不配置策略权重。
40. DomainSignal 不把 AtomicSignal strength 连乘。
41. 正常 neutral 或 mixed 为 created 且 is_valid = true。
42. 失败结果不会伪装成正常 neutral 或 mixed。
43. required 领域失败会阻断 DomainSignalSet。
44. 未被版本包选择的定义和后台研究结果不进入 MarketRegime。
45. 正式服务不得创建仅用于研究的 DomainSignalSet。
46. 六个领域齐全、created 且 allows_market_regime = true 才能进入 MarketRegime。
47. blocked、failed、unknown 均不允许下游消费。
48. definition_set_hash 对相同定义集合稳定。
49. domain_signal_set_key 对相同输入身份稳定。
50. 相同 business_request_key 重复执行返回已有结果。
51. 并发执行只生成一份正式 DomainSignalSet。
52. Set 与 Value 在同一事务写入。
53. 事务失败不会留下 created 半成品。
54. unknown 不会自动重算或放行。
55. seed 命令幂等。
56. seed 不恢复 retired 或 disabled 定义。
57. seed 不覆盖运行配置。
58. seed 不生成 DomainSignalSet。
59. dry-run 不写业务对象或 AlertEvent。
60. DomainSignal 不识别 MarketRegime。
61. DomainSignal 不选择策略。
62. DomainSignal 不生成 StrategySignal。
63. DomainSignal 不生成 DecisionSnapshot。
64. DomainSignal 不请求 Binance。
65. DomainSignal 不调用 BinanceGateway。
66. DomainSignal 不调用大模型。
67. DomainSignal 不保存或查询编排 ID。
68. adapter 显式映射业务结果。
69. 全部业务时间使用 UTC。
70. 每个算法版本有独立算法需求文档和 implementation 实现记录。
71. DomainSignal 使用公共 CalculatorRegistry，不建立模块私有 Registry。
72. Registry 解析结果的 calculator_type 必须为 domain_signal。
73. Service 传给 calculator 的输入不包含 Django model 或 QuerySet。
74. CalculatorOutput 不返回 created、blocked 或 unknown。
75. Service 负责把 succeeded / failed 计算结果映射为业务状态。
76. 替换兼容 DTO 的算法版本不需要修改 DomainSignalService 主流程。
77. 单输入算法有效时 coverage_ratio = 1、agreement_ratio = null 且不应用 agreement_threshold。
78. 单输入算法缺少唯一 required 原子信号时计算失败。
79. single_atomic_passthrough 的恒等映射行为由独立算法版本合同固定。
80. 正式服务不存在 allow_candidate、ignore_approval 或 use_latest 等绕过参数。
```

## 32. 验收方式

实现完成后至少执行：

```bash
pytest tests/domain_signals/
python manage.py seed_domain_signal_definitions
python manage.py build_domain_signals --atomic-signal-set-id <id> --strategy-analysis-release-id <id> --strategy-analysis-release-hash <hash> --business-request-key <key> --trigger-source manual --trace-id <id>
```

数据库检查：

```text
DomainSignalDefinition 的状态、配置和 hash 完整；
StrategyAnalysisRelease 身份、六领域切片与原子归属完整；
DomainSignalSet 正确绑定 AtomicSignalSet；
definition_set_hash 可复算；
Value 数量与冻结定义集合一致；
每条 Value 绑定具体 Definition；
used_atomic_signal_value_ids 可追溯到同一 AtomicSignalSet；
正式领域归属无冲突；
coverage_ratio 与 agreement_ratio 可复算；
六个正式领域输入完整的 created 集合 allows_market_regime = true；
重复执行没有产生第二份正式集合；
没有保存任何编排 ID。
```

通过标准：

```text
相同 AtomicSignalSet 和定义集合得到唯一、确定性结果；
每个领域只聚合同领域证据；
同一正式原子信号不会跨领域重复计算；
正常分歧与计算失败可以区分；
未被版本包选择的算法与后台研究结果不会进入 MarketRegime；
证据链可以回查到实际 AtomicSignalValue；
没有策略权重；
没有外部网络访问；
没有交易副作用。
```

## 33. 模块影响声明

```text
读写 MySQL：是，读取 AtomicSignalSet、AtomicSignalValue、DomainSignalDefinition，写 DomainSignalSet、DomainSignalValue 和必要 AlertEvent；
访问 Redis：可选，仅用于短期锁、幂等和缓存，不保存正式事实；
访问 Binance：否；
调用 BinanceGateway：否；
发送 Hermes：否；
调用大模型：否；
涉及真实交易：否；
涉及 FeatureLayer：不直接读取，仅通过业务链追溯；
涉及 AtomicSignal：只消费 AtomicSignalSet / AtomicSignalValue；
涉及 DomainSignal：是，本模块自身；
涉及 MarketRegime：只提供正式输入，不执行环境分类；
涉及 StrategyRouting：否；
涉及 StrategySignal：不生成，只定义下游去重边界；
涉及 DecisionSnapshot：否；
涉及账户、PriceSnapshot、OrderPlan、RiskCheck 或 Execution：否；
写 AlertEvent：单项失败、集合失败、阻断、未知或定义冲突；
dry-run：可计算但不写正式业务对象；
confirm-write：如提供，只控制落库，不改变放行标准。
```

## 34. 明确禁止

DomainSignal 禁止：

```text
绕过 AtomicSignalSet；
读取 FeatureValue 或 Kline；
请求 Binance REST 或 WebSocket；
调用 BinanceGateway；
调用 AtomicSignalService 补算；
混用不同 AtomicSignalSet 的结果；
在多个正式领域重复使用同一 AtomicSignalDefinition；
输出或分配策略权重；
将 AtomicSignal strength 连乘；
将 coverage 或 agreement 解释为盈利概率；
输出通用 confidence；
跨领域识别整体市场环境；
选择 StrategyDefinition；
生成 StrategyRouteDecision；
生成 StrategySignal；
生成目标仓位；
输出 position_size 或 leverage；
生成 CandidateOrderIntent；
执行 RiskCheck；
提交订单；
直接发送 Hermes；
调用大模型参与实时判断；
保存或查询编排 ID；
让编排对象关联替代业务外键。
```

## 35. 最终验收标准

DomainSignal 验收通过必须满足：

```text
AtomicSignalSet 是唯一正式输入边界；
DomainSignalSet 与 AtomicSignalSet 形成明确业务外键；
DomainSignalValue 逐条绑定 DomainSignalDefinition；
每个领域只聚合同类原子信号；
正式原子证据领域归属唯一；
领域层不使用业务权重；
AtomicSignal strength 只在领域 calculator 中使用一次；
AtomicSignal confidence 不作为领域层默认权重；
DomainSignal strength 是重新计算的领域强度；
coverage_ratio 与 agreement_ratio 语义明确；
不输出通用 confidence；
算法、参数和定义身份可追溯；
正式运行只读取本轮已冻结 StrategyAnalysisRelease 领域切片中的 active 且 enabled 定义；
默认模板只用于幂等初始化；
未被版本包选择的定义与后台研究结果不会进入 MarketRegime；
每个算法版本具有独立算法需求文档和 implementation 实现记录；
DomainSignalService 与 DomainSignal calculator 职责明确分离；
DomainSignal 使用公共 CalculatorRegistry 和稳定 DTO；
calculator 不输出业务状态或决定下游放行；
正常 neutral / mixed 与失败明确区分；
只有 created 且 allows_market_regime = true 的集合可被消费；
业务外键独立于编排关联；
MySQL 保存正式事实，Redis 只承担辅助能力；
全部时间使用 UTC；
不请求 Binance；
不调用大模型；
不生成市场环境、策略、目标仓位或订单；
不涉及真实交易；
不违反项目交易红线。
```

DomainSignal 的最终定位是：

```text
把一组可用 AtomicSignalValue 按唯一领域归属压缩为领域方向或状态事实，为 MarketRegime 提供不重复计分、可解释且可验证的输入。
```
