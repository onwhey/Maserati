# MarketRegime 需求说明

## 1. 模块定位

MarketRegime 是 DomainSignal 之后、StrategyRouting 之前的跨领域市场环境分类层。

它负责把同一份 DomainSignalSet 中可用于环境分类的领域事实，交给明确版本的 MarketRegime calculator，生成可追溯的 MarketRegimeSnapshot。

正式链路为：

```text
AtomicSignalSet / AtomicSignalValue
→ DomainSignalSet / DomainSignalValue
→ MarketRegimeSnapshot
→ StrategyRouteDecision
→ StrategySignal
→ StrategySignalQualityResult
→ DecisionSnapshot
```

MarketRegime 业务模块负责：

```text
接收明确的 domain_signal_set_id；
校验 DomainSignalSet 是否允许 MarketRegime 消费；
读取本轮 StrategyAnalysisRelease 明确选择的 MarketRegimeDefinition；
冻结 Definition、参数和领域输入；
把业务对象转换为不可变 CalculatorInput DTO；
通过公共 CalculatorRegistry 调用精确版本的 calculator；
校验 CalculatorOutput DTO；
生成 MarketRegimeSnapshot；
保存分类结果、评分、分类明确程度和证据；
处理状态、幂等、事务、unknown、恢复和 AlertEvent；
向 StrategyRouting 提供稳定的市场环境输入。
```

MarketRegime calculator 只负责：

```text
根据同一 DomainSignalSet 的跨领域输入执行纯计算；
输出 regime_code；
输出 regime_scores；
输出 regime_confidence；
输出 classification_margin；
输出结构化证据和可判定的计算失败。
```

MarketRegime 不负责：

```text
读取 AtomicSignalValue；
读取 FeatureValue 或 Kline；
重新计算 DomainSignal；
选择 StrategyDefinition；
生成 StrategyRouteDecision；
执行 StrategySignal 算法；
生成策略方向、策略强度或策略置信度；
生成目标仓位；
读取账户、持仓或 PriceSnapshot；
生成订单；
风控审批；
交易执行；
调用 Binance；
调用大模型。
```

这些边界属于稳定业务合同。市场环境算法可以演进，但算法变化不得把具体分类公式写入 MarketRegimeService。

## 2. MarketRegime 的业务含义

DomainSignalValue 回答限定领域的问题，例如：

```text
趋势领域当前是什么方向或状态；
动量领域当前是什么方向或状态；
波动领域当前是什么状态。
```

MarketRegimeSnapshot 回答跨领域的问题：

```text
在一组确定的领域事实下，当前整体市场环境被某个明确版本的分类算法归为什么类别；
各候选类别得到什么分类评分；
最终分类有多明确；
哪些领域事实构成了该分类证据。
```

MarketRegimeSnapshot 是市场上下文事实，不是策略选择，也不是交易判断。

必须区分：

```text
DomainSignalValue       = 单个领域的方向或状态事实；
MarketRegimeSnapshot    = 跨领域环境分类事实；
StrategyRouteDecision   = 根据明确路由规则选出的策略定义；
StrategySignal          = 已选策略产生的策略级方向、强度和置信度；
DecisionSnapshot        = 策略周期的目标仓位决策。
```

`regime_code` 不得被解释为：

```text
买入；
卖出；
开多；
开空；
平仓；
目标仓位；
订单动作；
收益预测。
```

## 3. 算法未指定时的系统行为

本需求只定义 MarketRegime 的业务框架、Calculator 合同和安全边界，不指定任何正式市场环境分类算法。

本需求不预设：

```text
正式 algorithm_name；
正式 algorithm_version；
正式 regime_code 枚举；
领域输入组合公式；
regime_scores 公式；
regime_confidence 公式；
classification_margin 公式；
分类阈值；
环境切换规则。
```

因此：

```text
不得仅凭本需求创建可进入正式版本包的默认定义；
不得在 MarketRegimeService 中临时编写分类 if / elif；
不得把示例市场名称当作正式 regime_code；
不得在缺少精确 calculator 时自动使用其他算法；
不得在缺少算法需求文档、implementation 实现记录或一致性验证证据时允许正式路由消费结果；正式运行时不读取 Markdown 文件。
```

在正式算法、参数、文档、测试和人工配置全部就绪前，正式分类入口必须 fail-closed。

可以登记任意已实现算法定义供后台研究组合，但正式服务只执行已批准并启用版本包选择的定义。

## 4. 核心原则

### 4.1 DomainSignalSet 是唯一正式输入边界

MarketRegimeService 必须接收明确的 `domain_signal_set_id`。

上游必须同时满足：

```text
DomainSignalSet.status = created；
DomainSignalSet.is_usable = true；
DomainSignalSet.allows_market_regime = true；
DomainSignalValue 全部属于该 DomainSignalSet；
供本 Definition 使用的 DomainSignalValue 状态明确。
```

`allows_market_regime = true` 只表示该 DomainSignalSet 具备进入本模块的基础资格，不代表它一定满足每个 MarketRegimeDefinition 的 required domain 合同。

MarketRegimeService 仍必须根据本次冻结的 MarketRegimeDefinition 校验：

```text
allowed_domain_codes 是否只引用正式版本包中的领域；
required_domain_codes 是否完整；
实际 DomainSignalValue 是否有效；
正式领域结果是否唯一；
领域结果是否与本轮 StrategyAnalysisRelease 一致；
所有输入是否来自同一 DomainSignalSet。
```

MarketRegime 不得：

```text
自行寻找最近一份 DomainSignalSet；
通过 AtomicSignalSet 重新计算领域结果；
绕过 DomainSignalSet 直接读取 DomainSignalValue；
调用 DomainSignalService 临时补算；
混用不同 DomainSignalSet 的领域结果。
```

### 4.2 只做跨领域环境分类

MarketRegime 可以组合多个不同领域的 DomainSignalValue。

它不得在分类过程中：

```text
重新聚合同一领域的 AtomicSignalValue；
修正 DomainSignalValue 的 direction、state_code 或 strength；
生成新的 DomainSignalValue；
把市场环境类别转换为策略方向；
直接选择策略；
直接决定是否交易。
```

### 4.3 不使用策略权重

策略级权重只属于 StrategySignal。

MarketRegimeDefinition 禁止包含：

```text
strategy_weight；
domain_strategy_weight；
target_position_weight；
portfolio_weight；
order_weight。
```

MarketRegime calculator 可以使用属于分类算法本身的固定参数、阈值或系数，但必须：

```text
写入冻结 params；
由具体算法需求文档解释；
进入 params_hash 和 definition_hash；
不得被解释为 StrategySignal 的输入权重；
不得在线自动优化。
```

### 4.4 不重复计算领域证据

DomainSignalValue 是 MarketRegime 的最小正式输入单位。

规则：

```text
同一 DomainSignalValue 在一次分类中最多使用一次；
不得同时读取 DomainSignalValue 及其底层 AtomicSignalValue 参与分类；
不得把相同领域事实复制成多个别名重复计分；
used_domain_signal_value_ids 必须去重；
实际使用值必须全部可追溯到同一 DomainSignalSet。
```

### 4.5 分类明确程度不等于盈利概率

`regime_confidence` 只表示算法对本次环境分类的明确程度。

它不得被解释为：

```text
策略盈利概率；
上涨概率；
下跌概率；
交易成功率；
仓位比例；
风控通过概率。
```

`classification_margin` 只表示算法定义的类别区分程度。具体公式必须由算法需求文档固定。

MarketRegime 不输出 StrategySignal.confidence。

### 4.6 正常不明确与计算失败分离

算法能够完成计算，但市场环境不明确时，必须生成合法的环境分类结果。

允许由具体算法定义一个明确的“不确定环境” regime_code，但该代码必须预先登记在 `allowed_regime_codes` 中。

正常不明确不得伪装成：

```text
blocked；
failed；
unknown；
calculator error。
```

只有输入、配置、算法或持久化无法可靠完成时，才使用阻断或失败状态。

### 4.7 MySQL 是正式事实来源

以下对象必须持久化到 MySQL：

```text
MarketRegimeDefinition；
MarketRegimeSnapshot；
必要的 AlertEvent。
```

Redis 只允许用于：

```text
短期幂等锁；
并发控制；
短期结果缓存；
短期任务状态。
```

Redis 不得成为 MarketRegimeSnapshot 的唯一存储，也不得作为 StrategyRouting 的正式输入来源。

## 5. 服务入口合同

MarketRegimeService 只提供正式分类入口。后台研究与回测使用独立研究服务，不调用正式服务的绕过入口。

### 5.1 正式分类入口

正式入口用于策略链：

```text
classify_for_strategy_routing(
    domain_signal_set_id,
    strategy_analysis_release_id,
    strategy_analysis_release_hash,
    expected_market_regime_definition_hash,
    business_request_key,
    trace_id,
    trigger_source,
)
```

该入口必须：

```text
校验本轮 StrategyAnalysisRelease 已批准、已启用且 release_hash 一致；
读取版本包唯一绑定的 MarketRegimeDefinition；
校验 Definition 为 active、enabled 且 definition_hash 与版本包预期一致；
校验 DomainSignalSet 与本轮版本包及领域切片一致；
不允许调用方指定 algorithm_name 或 algorithm_version；
不允许调用方覆盖 params；
版本包未选择或选择多个 MarketRegimeDefinition 时 blocked；
只返回允许 StrategyRouting 消费的正式 Snapshot。
```

正式版本包选择、批准、启用、切换、回滚和后台研究隔离统一遵守 [StrategyAnalysisRelease](strategy_analysis_release.md)。

### 5.2 business_request_key

`business_request_key` 由调用方生成并显式传入，用于业务请求幂等。

它不得包含：

```text
Celery task id；
worker 名称；
本地时间；
随机重试序号；
编排 ID。
```

同一业务请求重复执行必须返回已有结果，不得生成第二份正式 Snapshot。

### 5.3 trace_id 与 trigger_source

`trace_id` 只用于日志和审计关联，不参与业务唯一性或算法计算。

`trigger_source` 至少允许：

```text
orchestrator；
celery；
management_command；
ops_console；
recovery；
test。
```

触发来源不得改变 Definition 选择、算法参数、分类公式或下游放行标准。

## 6. 结构化返回合同

MarketRegimeService 必须返回结构化业务结果，至少包括：

```text
status
market_regime_snapshot_id
market_regime_snapshot_key
domain_signal_set_id
market_regime_definition_id
strategy_analysis_release_id
strategy_analysis_release_hash
regime_code
is_usable
allows_strategy_routing
error_code
error_message
trace_id
```

允许的业务状态：

```text
created
blocked
failed
unknown
```

### 6.1 created

`created` 表示：

```text
输入合同满足；
Definition 合法；
calculator 精确可用；
计算成功；
输出合同通过；
MarketRegimeSnapshot 完整落库。
```

```text
is_usable = true；
allows_strategy_routing = true。
```

### 6.2 blocked

`blocked` 表示业务前置条件不满足，未执行正式分类。

典型场景：

```text
DomainSignalSet 不存在；
DomainSignalSet 非 created；
DomainSignalSet.is_usable = false；
DomainSignalSet.allows_market_regime = false；
StrategyAnalysisRelease 不存在、未批准、未启用或 release_hash 不一致；
版本包未选择或选择多个 MarketRegimeDefinition；
版本包中的 Definition 指纹不一致；
Definition 状态或配置不允许；
required DomainSignalValue 缺失；
正式领域结果不唯一；
输入混用不同 DomainSignalSet；
calculator 精确版本未注册；
算法需求文档或 implementation 实现记录缺失。
```

blocked 必须：

```text
is_usable = false；
allows_strategy_routing = false；
market_regime_snapshot_id = null；
market_regime_snapshot_key = null；
写明确 error_code；
写 AlertEvent；
不创建 MarketRegimeSnapshot；
不得生成可消费的 regime_code。
```

`blocked` 是前置条件校验结果，不是已持久化 MarketRegimeSnapshot 的生命周期状态。

### 6.3 failed

`failed` 表示已进入处理但无法可靠完成。

典型场景：

```text
CalculatorInput 构造失败；
calculator 返回 failed；
calculator 抛出未预期异常；
CalculatorOutput 合同不满足；
regime_code 不在 allowed_regime_codes；
数值越界或不可序列化；
数据库事务明确失败。
```

failed 必须：

```text
is_usable = false；
allows_strategy_routing = false；
写 error_code 和 error_message；
写 AlertEvent；
不得被 StrategyRouting 消费。
```

### 6.4 unknown

`unknown` 只用于业务持久化结果无法确认的情况。

unknown 必须：

```text
is_usable = false；
allows_strategy_routing = false；
不得直接重新执行 calculator；
先按 business_request_key 和 market_regime_snapshot_key 查证；
无法确认时保持 unknown 并告警。
```

Calculator 本身不得返回 unknown。

## 7. MarketRegimeDefinition

MarketRegimeDefinition 是 MarketRegime 的运行时业务定义。

建议字段：

```text
id
definition_code
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
allowed_regime_codes
status
enabled
created_at_utc
updated_at_utc
```

### 7.1 definition_code

`definition_code` 必须稳定、唯一、可读，只标识业务定义，不表示交易动作。

禁止使用：

```text
buy_regime；
sell_regime；
open_long_regime；
close_position_regime；
target_position_regime。
```

### 7.2 algorithm_name 与 algorithm_version

`algorithm_name + algorithm_version` 必须精确对应一个 `calculator_type = market_regime` 的已注册 calculator。

规则：

```text
不得只填写 algorithm_name 后按版本顺序自动选择；
不得在缺失精确版本时回退；
不得在 Service 中根据 Definition 编写算法专用分支；
相同算法身份的计算行为不得发生不兼容变化。
```

本需求不指定正式算法身份。

### 7.3 params

`params` 只保存 calculator 所需的冻结参数。

允许内容由具体算法需求文档定义，例如参数类别可以包括：

```text
分类阈值；
归一化边界；
边界值处理方式；
缺失可选领域的处理方式；
分类平局处理方式。
```

params 禁止包含：

```text
策略代码；
策略权重；
目标仓位；
账户权益；
订单数量；
路由结果；
动态在线优化结果；
当前时间；
编排 ID。
```

### 7.4 params_hash

`params_hash` 使用规范化参数计算：

```text
sha256(canonical_json(params))
```

规范化必须固定：

```text
键排序；
Decimal 字符串格式；
空值语义；
布尔值格式；
数组顺序语义。
```

### 7.5 definition_hash

`definition_hash` 至少覆盖：

```text
definition_code；
algorithm_name；
algorithm_version；
input_schema_version；
output_schema_version；
params_hash；
allowed_domain_codes；
required_domain_codes；
allowed_regime_codes。
```

`enabled` 是算法库可用性开关，不进入不可变 definition_hash。它不代表 Definition 自动进入正式运行；正式身份由 StrategyAnalysisRelease 选择并冻结。

### 7.6 allowed_domain_codes

定义本算法声明会进入 CalculatorInput、允许被 calculator 读取的领域代码。

正式版本包必须生成 market_context、trend、momentum、volatility、structure、risk_state 六个领域，但单个 MarketRegimeDefinition 可以只声明并使用其中一部分。

例如：

```text
只使用趋势和波动的算法：allowed_domain_codes = [trend, volatility]；
同时使用市场背景、趋势和结构的算法：allowed_domain_codes = [market_context, trend, structure]。
```

未被列入 `allowed_domain_codes` 的领域，即使已经在 DomainSignalSet 中生成，也不得传入本算法。

规则：

```text
allowed_domain_codes 只能来自正式领域集合 trend、momentum、volatility；
Service 不得把列表外的 DomainSignalValue 传入 calculator；
calculator 不得请求额外领域；
实际使用领域必须记录到 Snapshot；
列表不得包含重复 domain_code。
```

### 7.7 required_domain_codes

定义完成本算法必须存在且有效的领域代码。

`required_domain_codes` 表示本算法没有这些领域就不能计算。若算法固定只使用 trend 和 volatility，则二者都应列入 required；若某个领域只是可选输入，必须由算法需求文档明确缺失或不使用时的处理方式。

必须满足：

```text
required_domain_codes 是 allowed_domain_codes 的子集；
每个 required domain 只有一份正式有效 DomainSignalValue；
required domain 缺失时 blocked，不调用 calculator；
required domain 正常为 neutral、mixed 或低强度时仍是有效输入。
```

MarketRegime 不得把领域的正常中性状态误判为输入缺失。

### 7.8 allowed_regime_codes

`allowed_regime_codes` 冻结该 Definition 可输出的完整环境类别集合。

规则：

```text
不得为空；
不得重复；
必须由算法需求文档逐项定义；
calculator succeeded 时 regime_code 必须属于该集合；
regime_scores 必须完整覆盖该集合中的每一个类别；
regime_scores 不得缺失低分或不占优的类别；
regime_scores 不得包含该集合之外的类别；
同一 algorithm_version 不得运行时生成未登记类别。
```

本需求不提供默认 regime_code 集合。

### 7.9 status

生命周期状态：

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

被历史 Snapshot 引用的 Definition 不得物理删除。

`status = active` 与 `enabled = true` 只表示 Definition 在算法库中可供选择，不表示它会自动进入正式 MarketRegime。

### 7.10 enabled 与正式参与资格

`enabled` 控制 Definition 是否可被新版本包选择、以及已启用版本包执行时是否仍可用：

```text
enabled = true  → 可供版本包选择；被本轮冻结版本包选择后才参与正式计算；
enabled = false → 不得被新版本包选择；若当前正式版本包仍引用它，正式执行必须 blocked 并触发运维告警。
```

MarketRegimeDefinition 不保存额外运行等级或“参与 StrategyRouting”开关。正式资格必须同时满足：

```text
被本轮 StrategyAnalysisRelease 唯一选择；
Definition 为 active 且 enabled；
definition_hash 与版本包冻结值一致；
版本包领域切片满足本 Definition 的 allowed / required domain 合同。
```

算法库可以同时存在多个 active、enabled 的 MarketRegimeDefinition；一个 StrategyAnalysisRelease 只能选择其中一个。正式服务不得按“最新版本”或全局 active 数量自动选择。

## 8. MarketRegimeSnapshot

MarketRegimeSnapshot 表示在一份确定 DomainSignalSet 上、使用一个确定 Definition 得到的不可变市场环境分类事实。

建议字段：

```text
id
domain_signal_set_id
market_regime_definition_id
strategy_analysis_release_id
strategy_analysis_release_hash
business_request_key
market_regime_snapshot_key
market_regime_schema_version
regime_code
regime_scores
regime_confidence
classification_margin
status
is_usable
allows_strategy_routing
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

每条 Snapshot 必须通过真实业务外键绑定：

```text
MarketRegimeSnapshot
→ DomainSignalSet
→ AtomicSignalSet
→ FeatureSet
→ MarketSnapshot
```

已解析 Definition 时还必须绑定 `MarketRegimeDefinition`。

正式 created Snapshot 的 Definition 外键不得为空。

### 8.2 不可变性

Snapshot 一旦 `created`：

```text
不得覆盖 regime_code；
不得覆盖评分和证据；
不得切换 Definition；
不得替换 DomainSignalSet；
不得因 Definition 后续停用而修改历史结果；
算法重算必须产生新的、身份不同的 Snapshot。
```

### 8.3 market_regime_snapshot_key

业务唯一键至少覆盖：

```text
domain_signal_set_id；
market_regime_schema_version；
definition_hash。
```

建议：

```text
sha256(
  domain_signal_set_id
  + market_regime_schema_version
  + definition_hash
)
```

不得加入 trace_id、task id、当前时间、编排 ID或随机数。

### 8.4 定义快照

Snapshot 必须冗余保存实际计算时的：

```text
algorithm_name；
algorithm_version；
input_schema_version；
output_schema_version；
params_hash；
definition_hash；
definition_status；
definition_enabled。
```

冗余字段用于审计，不替代 Definition 外键。

### 8.5 状态和放行

规则：

```text
created → is_usable = true  → allows_strategy_routing = true；
failed  → is_usable = false → allows_strategy_routing = false；
unknown → is_usable = false → allows_strategy_routing = false。
```

正式服务不得创建只用于后台研究的 MarketRegimeSnapshot。blocked 不创建 Snapshot，后台研究结果写入隔离的研究对象。

## 9. 分类输出字段

### 9.1 regime_code

`regime_code` 是本 Definition 对整体市场环境的分类代码。

必须满足：

```text
非空；
属于 allowed_regime_codes；
语义由算法需求文档固定；
不包含交易动作；
不能由 StrategyRouting 临时改写。
```

本需求不指定任何正式 regime_code。

### 9.2 regime_scores

`regime_scores` 是机器可读的候选类别评分映射。

要求：

```text
键集合必须与 allowed_regime_codes 完全一致；
值范围和归一化方式由算法需求文档固定；
不得包含 NaN 或 Infinity；
不得自动解释为概率分布；
是否要求各项之和为 1 必须由具体算法明确；
分数很低的环境类别也必须明确输出，不得省略；
最终 regime_code 必须能由评分和判定规则复算。
```

### 9.3 regime_confidence

范围：

```text
0 <= regime_confidence <= 1
```

它只表示分类明确程度。

计算公式、校准方式和边界行为由算法需求文档固定。

输入完整或计算成功不自动等于 `regime_confidence = 1`。

### 9.4 classification_margin

`classification_margin` 表示分类结果与其他候选类别的区分程度。

要求：

```text
语义和范围由算法需求文档固定；
不得在 Service 中假定它必然等于最高分减第二高分；
不得解释为策略优势或预期收益；
不适用时的空值合同必须由算法 metadata 和文档明确。
```

### 9.5 used_domain_signal_codes 与 used_domain_signal_value_ids

必须记录 calculator 实际使用的领域事实。

要求：

```text
所有 Value 属于同一 DomainSignalSet；
domain_code 位于 allowed_domain_codes；
required codes 全部存在；
未列入 allowed_domain_codes 的领域不得传入 calculator；
Value.status = created；
Value.is_valid = true；
Value 所属 Definition 位于同一 StrategyAnalysisRelease 领域切片；
ID 不重复；
不得只记录定义依赖而不记录实际使用值。
```

### 9.6 evidence_items

机器可读证据至少包括：

```text
实际 DomainSignalValue ID；
domain_code；
direction 或 state_code；
strength；
coverage_ratio；
agreement_ratio；
候选 regime scores；
最终 regime_code；
regime_confidence；
classification_margin；
calculator 输出的必要中间统计。
```

不得保存完整 AtomicSignalValue、FeatureValue 或 Kline 副本。

### 9.7 evidence_text_zh

必须用中文说明：

```text
使用了哪些领域事实；
这些事实分别是什么方向或状态；
算法将市场归为哪个 regime_code；
分类明确程度如何；
是否存在接近、冲突或不明确的候选类别。
```

中文证据不得包含交易建议、目标仓位、订单方向或杠杆建议。

## 10. MarketRegimeService 与 calculator 边界

### 10.1 公共合同

所有 MarketRegime calculator 必须遵守 [StrategyCalculator 公共合同](strategy_calculator.md)。纯计算、DTO、计算状态、异常、确定性、精度、Registry、算法版本和副作用隔离的通用规则，以公共合同为准。

本文件只增加 MarketRegime 特有的输入、输出和分类边界。

### 10.2 稳定业务代码

MarketRegimeService 负责：

```text
校验服务入口和幂等键；
读取并校验 DomainSignalSet；
解析并冻结 MarketRegimeDefinition；
读取并校验 DomainSignalValue；
构造不可变 MarketRegimeCalculatorInput DTO；
通过公共 CalculatorRegistry 精确解析 calculator；
调用 calculator；
校验 MarketRegimeCalculatorOutput DTO；
把 succeeded / failed 映射为业务状态；
决定 is_usable 和 allows_strategy_routing；
事务写入 MarketRegimeSnapshot；
处理幂等、并发、unknown、恢复和 AlertEvent。
```

只要 DTO 与业务合同兼容，新增算法版本不得要求修改 Service 主流程。

### 10.3 CalculatorInput

输入至少包含：

```text
同一 DomainSignalSet 中、且只属于 allowed_domain_codes 的不可变 DomainSignalValue DTO；
冻结的 allowed_domain_codes；
冻结的 required_domain_codes；
冻结的 allowed_regime_codes；
冻结 params；
算法和 schema 身份；
统一精度合同。
```

不得传入：

```text
Django model；
QuerySet；
数据库连接；
Redis client；
业务 service；
Celery task；
编排对象；
当前时间函数。
```

### 10.4 CalculatorOutput

输出至少包含：

```text
calculation_status = succeeded / failed；
regime_code；
regime_scores；
regime_confidence；
classification_margin；
used_domain_signal_value_refs；
结构化证据和中间统计；
失败时的 error_code / error_message。
```

CalculatorOutput 不得返回：

```text
created；
blocked；
unknown；
allows_strategy_routing；
selected_strategy；
StrategyRouteDecision；
StrategySignal；
目标仓位或订单对象。
```

### 10.5 MarketRegime 特有禁止项

除公共合同的副作用禁令外，MarketRegime calculator 还不得：

```text
读取 AtomicSignalValue、FeatureValue 或 Kline；
调用 DomainSignalService 或其他 calculator；
修改 DomainSignalValue；
跨 DomainSignalSet 混合输入；
使用未声明的 domain_code；
输出未登记的 regime_code；
选择 StrategyDefinition；
输出策略方向、策略强度或策略置信度；
读取账户、持仓、价格、订单或风控结果。
```

## 11. CalculatorRegistry 与算法身份

MarketRegime 使用 [StrategyCalculator 公共合同](strategy_calculator.md)定义的公共 CalculatorRegistry，不建立模块私有 Registry。

每个 calculator 必须声明：

```text
calculator_type = market_regime；
algorithm_name；
algorithm_version；
input_schema_version；
output_schema_version；
deterministic = true；
algorithm_requirement_document_path；
implementation_document_path。
```

MarketRegime 特有校验：

```text
Definition 必须精确解析到 calculator；
calculator_type 必须为 market_regime；
algorithm_requirement_document_path 和 implementation_document_path 必须记录稳定路径；
文档存在性与身份一致性由 CI、构建和版本包批准阶段验证并形成证据；
正式运行时不得读取 Markdown 文件判断 calculator 是否可用；
算法需求文档、implementation 实现记录身份必须与 metadata 一致；
不得回退到其他名称或版本；
不得使用 env 替换实现。
```

## 12. 默认模板与运行时 Definition

必须区分：

```text
default_market_regime_definitions.py = 受代码管理的定义模板；
MarketRegimeDefinition 表            = 可供组合选择的算法定义库；
StrategyAnalysisRelease 市场环境切片 = 正式运行时定义。
```

正式运行只读取本轮 StrategyAnalysisRelease 唯一选择的 Definition。

Service 不得：

```text
直接读取默认模板参与计算；
把模板与数据库 Definition 求合集；
把版本包选择与数据库其他 active Definition 求合集；
自动恢复 retired 或 disabled Definition；
覆盖 enabled 或修改任何 StrategyAnalysisRelease。
```

本需求没有指定具体算法，因此默认模板不得凭空生成可被正式版本包选择的 Definition。

## 13. seed_market_regime_definitions

必须提供幂等初始化入口：

```bash
python manage.py seed_market_regime_definitions
```

命令只负责：

```text
读取项目中明确存在的 Definition 模板；
规范化 params；
计算 params_hash 和 definition_hash；
校验 calculator metadata、算法需求文档与 implementation 实现记录；
校验 allowed / required domain codes；
校验 allowed_regime_codes；
按完整定义身份幂等写入；
输出初始化摘要。
```

命令不得：

```text
发明 algorithm_name、algorithm_version 或 regime_code；
生成 MarketRegimeSnapshot；
调用 MarketRegimeService；
恢复 retired 或 disabled Definition；
覆盖人工运行配置；
在缺少 calculator，或算法文档尚未通过 CI、构建与版本包批准阶段一致性验证时激活 Definition。
```

当不存在已确认模板时，命令必须安全返回零变更摘要，不得创建占位正式定义。

## 14. 算法需求文档与 implementation 实现记录

每个 MarketRegime calculator 必须遵守 [StrategyCalculator 公共合同](strategy_calculator.md)中的算法需求文档、implementation 实现记录、版本、代码一致性和验证状态规则。

每个 MarketRegime 算法版本必须同时具备：

```text
算法需求文档；
implementation 实现记录。
```

算法需求文档负责定义市场环境分类公式、输入领域、参数、边界、输出类别和验证要求，应放在 requirements 下的对应市场环境算法目录，具体目录由后续市场环境算法需求文件统一确定，例如：

```text
docs/requirements/<市场环境算法模块>/<regime_or_algorithm>.md
```

implementation 实现记录负责记录代码落地位置、calculator、DTO、测试入口和实现差异，统一目录：

```text
docs/implementation/market_regime/
```

每个 implementation 实现记录使用独立文件：

```text
<algorithm_name>__<algorithm_version>.md
```

除公共合同要求外，MarketRegime 算法需求文档还必须记录：

```text
适用的 allowed / required domain codes；
允许输出的 regime_code 及逐项语义；
每个 DomainSignal 字段的使用方式；
完整跨领域分类公式；
regime_scores 公式和范围；
regime_confidence 公式和校准语义；
classification_margin 公式和空值合同；
平局、冲突和不明确环境处理；
缺失可选领域的处理；
防止重复使用领域证据的规则；
领域专用计算示例；
golden test；
样本外验证要求。
```

算法行为变化必须使用不同 algorithm_version，并先形成新的算法需求文档；对应代码实现完成后，再形成新的 implementation 实现记录。

参数组合变化由 params、params_hash 和 definition_hash 表达；算法行为未变化时不得滥增算法版本。

本需求不创建任何具体 MarketRegime 算法需求文件，也不创建任何具体 MarketRegime implementation 实现记录。

## 15. 算法验证与正式发布

领域分类算法至少需要验证：

```text
时间顺序回测；
样本外验证；
walk-forward 验证；
类别稳定性；
参数敏感性；
分类切换频率；
不同市场阶段的混淆情况；
与简单单领域分类基准的增量价值；
消融测试；
分类结果对策略路由和策略表现的影响。
```

所有已实现、已注册并通过一致性验证的算法版本在已验证算法目录中平权。算法 Definition 不保存运行等级身份；只有本轮冻结的完整 StrategyAnalysisRelease 经过验证、人工批准并启用且明确选择该 MarketRegimeDefinition 后，该定义才能进入正式 StrategyRouting 链路。

后台研究与回测服务可以自由选择 MarketRegimeDefinition 及其上下游组合，使用相同 calculator、DTO、参数和精度规则，但结果必须写入隔离的研究对象，不得写入正式 MarketRegimeSnapshot，也不得调用正式 MarketRegimeService 的绕过入口。

算法需求文档、implementation 实现记录、Definition 状态或后台结果本身不能自动批准版本包，也不能开启真实交易。

## 16. MarketRegimeService 主流程

正式入口流程：

```text
1. 接收 domain_signal_set_id、StrategyAnalysisRelease 身份、business_request_key、trace_id、trigger_source；
2. 校验请求字段；
3. 按 business_request_key 查询已有业务结果；
4. 读取 DomainSignalSet；
5. 校验 status、is_usable 和 allows_market_regime；
6. 校验 StrategyAnalysisRelease 的批准、启用和 release_hash；
7. 读取版本包唯一绑定的 MarketRegimeDefinition；
8. 校验 Definition 的 active、enabled、definition_hash 和 calculator；
9. 校验 DomainSignalSet 与版本包领域切片一致；
10. 冻结 Definition 与 params；
11. 读取该 DomainSignalSet 的正式 DomainSignalValue；
12. 校验 allowed / required domain codes；
13. 校验来源一致、领域唯一且均属于同一版本包；
14. 生成 market_regime_snapshot_key；
15. 按 key 查询已有完整 Snapshot；
16. 通过公共 Registry 精确解析 calculator；
17. 构造不可变 MarketRegimeCalculatorInput DTO；
18. 执行 calculator；
19. 校验 MarketRegimeCalculatorOutput DTO；
20. 把 calculation_status 映射为业务状态；
21. 生成不可变 MarketRegimeSnapshot；
22. 在数据库事务中正式写入；
23. 写必要 AlertEvent；
24. 返回结构化业务结果。
```

计算期间不得重新读取 Definition 或参数并替换本次冻结内容。

## 17. 失败与阻断处理

### 17.1 calculator failed

calculator 返回 failed 时，Service 必须形成明确业务失败：

```text
status = failed；
is_usable = false；
allows_strategy_routing = false；
regime_code 为空；
error_code 非空；
error_message 非空；
evidence_text_zh 非空。
```

不得伪造一个正常 regime_code 掩盖计算失败。

### 17.2 正常不明确

calculator succeeded 且输出已登记的不明确类别时：

```text
status = created；
is_usable = true；
regime_code 保存该类别；
regime_confidence 保存实际分类明确程度；
证据说明为什么环境不明确。
```

正式 Definition 的合法不明确类别仍可以进入 StrategyRouting，由路由规则决定如何处理；MarketRegime 不得替 StrategyRouting 选择 fallback。

### 17.3 前置阻断

前置条件不满足时不得调用 calculator。

阻断结果必须区分：

```text
upstream_unavailable；
definition_unavailable；
definition_conflict；
required_domain_missing；
domain_membership_invalid；
calculator_missing；
implementation_document_missing。
```

## 18. 写库与事务

MarketRegimeSnapshot 的正式写入必须使用数据库事务。

要求：

```text
使用 transaction.atomic() 或等价 Django 事务；
数据库唯一约束保护 business_request_key 和 market_regime_snapshot_key；
写入前完成 calculator 和输出合同校验；
Snapshot 与必要 AlertEvent 按项目事件事务规则写入；
不得在数据库事务中执行外部请求；
不得在事务中等待其他模块；
事务失败不得留下 created 半成品。
```

MarketRegime 不访问任何外部服务，因此 calculator 调用应在短时纯计算范围内完成。

## 19. 幂等与并发

### 19.1 重复业务请求

相同 business_request_key：

```text
已有 created → 返回已有 Snapshot；
已有 blocked → 重新校验当前前置条件，仍不满足则继续返回 blocked；
已有 failed → 返回已有失败结果，受控恢复入口可重新核验；
已有 unknown → 先查证，不直接重新计算。
```

blocked 不创建 MarketRegimeSnapshot。重复触发同一业务动作时，不得为了幂等创建伪造 Snapshot；告警重复由 AlertEvent 幂等、提醒间隔或运维问题去重控制。

### 19.2 相同输入身份

即使 business_request_key 不同，只要以下身份相同：

```text
domain_signal_set_id；
market_regime_schema_version；
definition_hash；
run_semantics。
```

也不得产生两份相同的正式 Snapshot。

### 19.3 并发冲突

并发安全依靠：

```text
数据库唯一约束；
原子创建；
必要的短期 Redis 锁。
```

Redis 锁失效不能破坏数据库唯一性。

## 20. unknown 与恢复

数据库结果不明确时：

```text
不得假设写入失败；
不得立即重复计算或插入；
按 business_request_key 查询；
按 market_regime_snapshot_key 查询；
核对 domain_signal_set_id、definition_hash 和输出字段；
无法确认时保持 unknown 并告警。
```

受控恢复必须检查：

```text
DomainSignalSet 是否仍存在且身份一致；
Snapshot 是否已经落库；
Snapshot 是否绑定正确 Definition；
used_domain_signal_value_ids 是否完整；
regime_code 是否属于冻结枚举；
Definition 和 params 是否与计算时身份一致。
```

不得覆盖已 created 的 Snapshot 重新分类。

## 21. StrategyRouting 消费合同

StrategyRouting 只允许消费：

```text
MarketRegimeSnapshot.status = created；
MarketRegimeSnapshot.is_usable = true；
MarketRegimeSnapshot.allows_strategy_routing = true；
MarketRegimeDefinition.status = active；
MarketRegimeDefinition.enabled = true；
MarketRegimeSnapshot 与 StrategyRouting 使用同一 StrategyAnalysisRelease。
```

StrategyRouting 必须：

```text
接收明确的 market_regime_snapshot_id；
记录实际使用的 Snapshot；
不得重新执行 MarketRegime calculator；
不得直接读取 DomainSignalValue 替代 MarketRegime；
不得使用后台研究结果或其他版本包的 Snapshot；
不得改写 regime_code 或评分。
```

MarketRegimeSnapshot 只是路由上下文。它不直接指定 StrategyDefinition。

## 22. 与 DomainSignal 和 StrategySignal 的关系

正式边界：

```text
DomainSignalValue 提供领域事实；
MarketRegimeSnapshot 提供跨领域环境分类；
StrategyRouteDecision 记录策略选择结果；
StrategySignal 使用已选策略和 DomainSignalValue 生成策略判断，并保留 MarketRegimeSnapshot 追溯关系。
```

规则：

```text
MarketRegime 不修改 DomainSignal；
MarketRegime 不输出 StrategySignal 权重；
MarketRegime 不决定 StrategySignal 方向；
StrategySignal 不把 regime_confidence 当作领域方向权重重复相乘；
MarketRegimeSnapshot 不进入 StrategySignal calculator，不改变策略方向、strength 或 confidence。
```

## 23. 与编排层的关系

MarketRegime 是业务模块，不承担编排职责。

业务追溯链独立成立：

```text
MarketRegimeSnapshot
→ DomainSignalSet
→ DomainSignalValue
→ AtomicSignalSet
→ FeatureSet
→ MarketSnapshot
```

业务表不得保存或查询：

```text
OrchestrationRun ID；
OrchestrationStepRun ID；
编排步骤序号；
编排内部状态。
```

`MarketRegimeStepAdapter` 负责：

```text
接收编排层步骤请求；
调用正式 MarketRegimeService 入口；
理解 MarketRegime 原始业务结果；
映射为统一步骤状态；
向编排层返回 market_regime_snapshot_id 和对象引用。
```

编排关联只提供整轮快捷查询，不替代业务外键。

## 24. AlertEvent

至少覆盖：

```text
market_regime_blocked；
market_regime_failed；
market_regime_unknown；
market_regime_definition_unavailable；
market_regime_definition_conflict；
market_regime_definition_invalid；
market_regime_required_domain_missing；
market_regime_domain_membership_invalid；
market_regime_calculator_missing；
market_regime_implementation_document_missing；
market_regime_output_invalid。
```

正常 created 环境分类不写业务告警。

合法的不明确环境分类不是异常，不写 AlertEvent。

MarketRegime 只写 AlertEvent，不直接发送 Hermes；通知模块按规则消费 AlertEvent。

## 25. 配置规则

允许环境配置：

```text
MARKET_REGIME_SCHEMA_VERSION；
短期幂等锁 TTL；
Decimal 精度和统一舍入规则；
单次 calculator 最大允许执行时长。
```

不允许通过 env 动态改变：

```text
MarketRegimeDefinition.params；
allowed / required domain codes；
allowed_regime_codes；
Definition 生命周期；
enabled；
StrategyAnalysisRelease 市场环境定义选择；
algorithm_name 或 algorithm_version；
具体算法公式；
calculator 注册映射。
```

所有环境配置必须进入 `.env.example` 并带中文注释。

## 26. 服务、任务与命令边界

### 26.1 service

核心业务逻辑放在 service/domain 层。

MarketRegimeService 负责稳定业务流程，不得包含具体分类公式、算法版本专用分支或 regime_code 硬编码。

### 26.2 Celery task

Celery task 只负责：

```text
接收参数；
传递 trace_id 和 trigger_source；
调用 MarketRegimeService；
返回可序列化摘要。
```

task 不得实现分类算法、解析 Definition 或直接写 Snapshot。

### 26.3 management command

正式手工入口：

```bash
python manage.py classify_market_regime --domain-signal-set-id <id> --strategy-analysis-release-id <id> --strategy-analysis-release-hash <hash> --business-request-key <key> --trigger-source manual --trace-id <id>
```

command 只负责解析参数、调用 service 和输出结果。

至少输出：

```text
market_regime_snapshot_id；
market_regime_snapshot_key；
status；
regime_code；
strategy_analysis_release_id；
strategy_analysis_release_hash；
allows_strategy_routing；
error_code。
```

## 27. 时间与精度

所有业务时间统一使用 UTC。

规则：

```text
analysis_close_time_utc 从 DomainSignalSet 业务链继承；
calculated_at_utc 使用 UTC；
不得用服务器本地时间参与分类；
不得用运行时当前时间改变固定输入的结果；
Decimal 写入 JSON 时转换为规范字符串；
不得使用不可控 float 保存正式数值；
NaN 和 Infinity 必须失败。
```

相同 DomainSignalSet、Definition、参数、算法身份和精度配置必须得到确定性一致结果。

## 28. 日志与审计

结构化日志至少包含：

```text
trace_id；
trigger_source；
business_request_key；
domain_signal_set_id；
market_regime_snapshot_id；
market_regime_snapshot_key；
market_regime_definition_id；
algorithm_name；
algorithm_version；
definition_hash；
status；
regime_code；
strategy_analysis_release_id；
strategy_analysis_release_hash；
allows_strategy_routing；
latency_ms；
error_code。
```

日志不得包含完整上游对象副本、密钥或交易建议。

## 29. dry-run 与 confirm-write

MarketRegime 可以支持 dry-run。

dry-run 必须：

```text
读取明确 DomainSignalSet；
执行与正式模式相同的 Definition、输入、Registry 和输出校验；
调用相同 calculator；
不写 MarketRegimeSnapshot；
不写正式业务 AlertEvent；
不允许 StrategyRouting 消费内存结果；
明确返回 persisted = false。
```

如提供 confirm-write：

```text
只控制是否落库；
不得改变 Definition 选择；
不得改变算法或参数；
不得绕过 StrategyAnalysisRelease 身份、批准状态或定义选择；
不得把 blocked、failed 或 unknown 强制写成 created。
```

## 30. 测试要求

至少覆盖：

```text
1. MarketRegimeDefinition 可以创建。
2. params_hash 对相同规范化参数稳定。
3. definition_hash 对相同定义稳定。
4. allowed_regime_codes 不能为空且不能重复。
5. required_domain_codes 必须是 allowed_domain_codes 子集。
6. 本轮冻结版本包选择的 Definition 必须为 active 且 enabled。
7. 被选 Definition 非 active 或 enabled = false 时 blocked。
8. 算法库允许同时存在多个 active 且 enabled 的 Definition。
9. 版本包未选择 MarketRegimeDefinition 时正式入口 blocked。
10. 版本包选择多个 MarketRegimeDefinition 时正式入口 blocked。
11. release_hash 或 Definition 指纹与版本包冻结值不一致时 blocked。
12. 未被本轮冻结版本包选择的 Definition 不参与正式分类。
13. 正式入口不允许调用方覆盖算法或 params。
14. Service 只读取明确的 domain_signal_set_id。
15. DomainSignalSet 不存在时 blocked。
16. DomainSignalSet 非 created 时 blocked。
17. DomainSignalSet.is_usable = false 时 blocked。
18. DomainSignalSet.allows_market_regime = false 时 blocked。
19. required DomainSignalValue 缺失时 blocked。
20. required domain 正常 neutral 或 mixed 仍是有效输入。
21. 不属于同一版本包领域切片的 DomainSignalValue 不进入正式分类。
22. 不同 DomainSignalSet 的 Value 不能混用。
23. 同一 DomainSignalValue 不重复计分。
24. allowed codes 之外的 Value 不传给 calculator。
25. MarketRegime 使用公共 CalculatorRegistry。
26. Registry 解析结果 calculator_type = market_regime。
27. calculator 缺失精确版本时 blocked。
28. calculator 不回退到其他版本。
29. Service 传给 calculator 的输入不包含 Django model 或 QuerySet。
30. CalculatorOutput 只返回 succeeded / failed。
31. CalculatorOutput 不返回业务状态或 allows_strategy_routing。
32. calculator succeeded 时 regime_code 属于冻结枚举。
33. 未登记 regime_code 导致 failed。
34. regime_scores 键集合必须与冻结枚举完全一致。
35. regime_scores 不含 NaN 或 Infinity。
36. regime_confidence 范围为 0 到 1。
37. 输入完整不自动产生 confidence = 1。
38. regime_confidence 不解释为盈利概率。
39. classification_margin 合同可验证。
40. used_domain_signal_value_ids 完整且去重。
41. created Snapshot 绑定 DomainSignalSet 和 Definition。
42. Snapshot 冗余保存准确算法和定义身份。
43. 正常不明确环境是 created，不是 failed。
44. calculator failed 不伪造正常 regime_code。
45. 同一版本包的正式 created Snapshot 允许 StrategyRouting 消费。
46. 后台研究结果和其他版本包 Snapshot 不允许正式 StrategyRouting 消费。
47. blocked、failed、unknown 均不允许下游消费。
48. market_regime_snapshot_key 对相同输入身份稳定。
49. 相同 business_request_key 重复执行返回已有结果。
50. 并发执行只生成一份相同身份 Snapshot。
51. 事务失败不留下 created 半成品。
52. unknown 先查证，不直接重算。
53. 已 created Snapshot 不被覆盖重算。
54. seed 命令幂等。
55. seed 不发明算法或 regime_code。
56. seed 不恢复 retired 或 disabled Definition。
57. seed 不覆盖人工运行配置。
58. 没有模板时 seed 返回零变更。
59. 每个算法版本具有独立算法需求文档和 implementation 实现记录。
60. 算法需求文档、implementation 实现记录身份与 metadata 一致。
61. dry-run 调用相同 calculator 但不写库。
62. dry-run 结果不能进入 StrategyRouting。
63. MarketRegime 不读取 AtomicSignalValue、FeatureValue 或 Kline。
64. MarketRegime 不调用 DomainSignalService 补算。
65. MarketRegime 不选择 StrategyDefinition。
66. MarketRegime 不生成 StrategyRouteDecision。
67. MarketRegime 不生成 StrategySignal。
68. MarketRegime 不生成 DecisionSnapshot。
69. MarketRegime 不读取账户、持仓或 PriceSnapshot。
70. MarketRegime 不请求 Binance。
71. MarketRegime 不调用大模型。
72. MarketRegime 不保存或查询编排 ID。
73. adapter 显式映射业务结果。
74. 全部业务时间使用 UTC。
75. 算法版本变化不修改 MarketRegimeService 主流程。
76. 后台研究服务复用 calculator 合同，但不写正式 MarketRegimeSnapshot。
77. 正式服务不存在 allow_candidate、ignore_approval 或 use_latest 等绕过参数。
```

具体分类算法的数学测试由对应算法需求文档定义；implementation 实现记录补充代码级测试入口和实际执行结果。

## 31. 验收方式

实现完成后至少执行：

```bash
pytest tests/market_regime/
pytest tests/strategy_calculator/ -k market_regime
python manage.py seed_market_regime_definitions
python manage.py classify_market_regime --domain-signal-set-id <id> --strategy-analysis-release-id <id> --strategy-analysis-release-hash <hash> --business-request-key <key> --trigger-source manual --trace-id <id>
```

在版本包未选择可用 MarketRegimeDefinition 时，正式命令的正确结果是：

```text
status = blocked；
error_code = market_regime_definition_unavailable；
allows_strategy_routing = false；
不生成伪造 regime_code；
写对应 AlertEvent。
```

数据库至少检查：

```text
Definition 的算法、schema、params 和 hash 身份完整；
Snapshot 正确绑定 DomainSignalSet 和 Definition；
Snapshot 的 StrategyAnalysisRelease 身份与 DomainSignalSet 一致；
used_domain_signal_value_ids 来自同一 DomainSignalSet；
regime_code、scores、confidence、margin 和证据满足冻结合同；
regime_scores 覆盖全部 allowed_regime_codes；
正式放行字段正确；
重复调用没有生成第二份相同身份 Snapshot；
业务表没有保存任何编排 ID。
```

## 32. 模块影响声明

```text
读写 MySQL：是，读取 DomainSignalSet、DomainSignalValue、MarketRegimeDefinition，写 MarketRegimeSnapshot 和必要 AlertEvent；
访问 Redis：可选，仅用于短期锁、幂等和缓存；
访问 Binance：否；
调用 BinanceGateway：否；
发送 Hermes：否；
调用大模型：否；
涉及真实交易：否；
涉及 FeatureLayer：不直接读取，仅通过业务链追溯；
涉及 AtomicSignal：不直接读取，仅通过业务链追溯；
涉及 DomainSignal：只消费 DomainSignalSet / DomainSignalValue；
涉及 MarketRegime：是，本模块自身；
涉及 StrategyRouting：只提供正式输入，不选择策略；
涉及 StrategySignal：不生成，只定义环境上下文边界；
涉及 DecisionSnapshot：否；
涉及账户、PriceSnapshot、OrderPlan、RiskCheck 或 Execution：否；
写 AlertEvent：阻断、失败、未知、Definition 冲突、输入冲突或输出非法；
dry-run：可计算但不写正式业务对象；
confirm-write：如提供，只控制落库，不改变放行标准。
```

异常处理方式：

```text
业务前置条件不满足 → blocked；
calculator 或输出校验失败 → failed；
持久化结果无法确认 → unknown；
正常不明确环境 → created 并保存合法 regime_code；
任何非 created 结果都不得进入 StrategyRouting。
```

## 33. 明确禁止

MarketRegime 禁止：

```text
自行查找最近 DomainSignalSet；
读取 AtomicSignalValue、FeatureValue 或 Kline；
调用 DomainSignalService 补算；
混用不同 DomainSignalSet 的结果；
重复使用同一 DomainSignalValue；
修改 DomainSignalValue；
在 Service 中硬编码分类算法；
在缺少算法时发明 regime_code；
缺失精确 calculator 时自动回退；
把 regime_scores 自动解释为概率；
把 regime_confidence 解释为盈利概率；
把 classification_margin 解释为策略优势；
输出策略权重；
选择 StrategyDefinition；
生成 StrategyRouteDecision；
生成 StrategySignal；
生成目标仓位；
生成 CandidateOrderIntent；
执行 RiskCheck；
提交订单；
请求 Binance REST 或 WebSocket；
调用 BinanceGateway；
调用大模型参与实时判断；
直接发送 Hermes；
保存或查询编排 ID；
让编排关联替代业务外键。
```

## 34. 最终验收标准

MarketRegime 验收通过必须满足：

```text
DomainSignalSet 是唯一正式输入边界；
Snapshot 与 DomainSignalSet、Definition 形成明确业务外键；
正式服务与后台研究服务边界明确；
一个 StrategyAnalysisRelease 只选择一个 MarketRegimeDefinition；
没有具体算法时不会生成伪造环境分类；
Definition 冻结算法、参数、领域依赖和类别枚举；
MarketRegimeService 与 calculator 职责明确分离；
使用公共 CalculatorRegistry 和稳定 DTO；
calculator 只输出计算状态，不输出业务状态；
regime_code、scores、confidence 和 margin 语义明确；
regime_confidence 不被解释为盈利概率；
实际领域输入完整可追溯且不重复；
正常不明确环境与计算失败明确区分；
每个算法版本有独立算法需求文档和 implementation 实现记录；
未被已批准版本包选择的算法和后台研究结果不得进入 StrategyRouting；
只有 created 且 allows_strategy_routing = true 的正式 Snapshot 可被消费；
MySQL 保存正式事实，Redis 只承担辅助能力；
业务外键独立于编排关联；
全部时间使用 UTC；
不请求 Binance；
不调用大模型；
不选择策略；
不生成目标仓位或订单；
不涉及真实交易；
不违反项目交易红线。
```

MarketRegime 的最终定位是：

```text
把一份可用 DomainSignalSet 交给明确版本、可验证且无副作用的跨领域分类算法，生成不可变的市场环境事实，为 StrategyRouting 提供上下文，但不替代策略选择、策略判断或交易决策。
```
