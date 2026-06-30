# 策略领域设计说明

## 1. 文档定位

本文档用于定义策略分析链路中的领域划分思路。

本文档回答：

```text
交易员观察市场时，系统应该把哪些市场问题拆成领域；
每个领域应该回答什么问题；
每个领域需要倒推出哪些 AtomicSignal 类型；
AtomicSignal 再需要倒推出哪些 Feature 类型；
哪些内容属于领域事实，哪些内容属于策略打法。
```

本文档不定义具体算法公式，不批准任何正式策略版本，不替代具体算法 requirements。

任何领域、原子信号、特征或策略要进入正式主链路，仍必须满足：

```text
独立算法 requirements；
implementation 实现记录；
测试和回测证据；
StrategyAnalysisRelease 选择、验证、人工批准和启用。
```

## 2. 核心结论

当前策略分析不新增独立业务模块。

不得新增：

```text
SupportResistanceModule
MarketStructureModule
StructureService
独立支撑压力业务模块
```

支撑压力、区间结构、大级别背景和风险状态都必须纳入现有策略分析链路：

```text
FeatureLayer
→ AtomicSignal
→ DomainSignal
→ MarketRegime
→ StrategyRouting
→ StrategySignal
→ StrategySignalQuality
→ DecisionSnapshot
```

也就是说：

```text
支撑压力不是一个独立模块；
它是一条贯穿现有策略分析链路的结构类市场事实能力。
```

## 3. 设计顺序与运行顺序

设计策略能力时，推荐采用：

```text
领域 → 原子 → 特征
```

也就是先问：

```text
交易员看市场时，会分哪几类问题？
每一类问题下需要哪些最小判断？
每个最小判断需要哪些基础特征？
```

系统运行时仍然是：

```text
特征 → 原子 → 领域
```

也就是：

```text
FeatureLayer 计算数值事实；
AtomicSignal 形成最小市场判断；
DomainSignal 聚合同类判断；
MarketRegime 综合多个领域判断市场环境；
StrategyRouting 选择打法；
StrategySignal 按打法输出策略判断；
DecisionSnapshot 转换为目标仓位意图。
```

## 4. 领域与策略的边界

领域层负责回答：

```text
市场事实是什么？
```

策略层负责回答：

```text
在这些市场事实下，我这套打法如何判断？
```

例如：

```text
structure 领域可以判断当前靠近支撑区；
StrategySignal 才能判断靠近支撑区时是否偏多。
```

再例如：

```text
MarketRegime 可以判断当前是大级别偏多下的高位区间震荡；
StrategyRouting 才能选择区间结构策略；
StrategySignal 才能输出该策略在支撑、压力或跌破结构下的策略级判断。
```

领域不得：

```text
选择策略；
输出目标仓位；
生成订单动作；
读取账户；
读取 PriceSnapshot；
访问 Binance；
执行风控；
提交订单。
```

## 5. 建议领域清单

策略分析链路建议从以下领域构建。

当前已有正式基础领域：

```text
trend
momentum
volatility
```

为支持大级别背景、支撑压力和区间结构策略，建议新增规划领域：

```text
market_context
structure
risk_state
```

因此，完整领域规划为：

```text
market_context  = 大级别市场背景领域
trend           = 趋势方向与趋势强度领域
momentum        = 动量强弱与衰竭领域
volatility      = 波动状态领域
structure       = 支撑压力、区间结构与价格位置领域
risk_state      = 异常风险状态领域
```

其中：

```text
market_context、structure、risk_state 是策略能力扩展规划；
是否进入正式运行，必须由后续具体 requirements 与 StrategyAnalysisRelease 决定。
```

领域之间必须保持独立聚合边界：

```text
单个 DomainSignal 只聚合自己领域下的 AtomicSignal；
DomainSignal 之间不得互相读取、互相修正或互相补算；
跨领域组合统一由 MarketRegime 完成。
```

关键边界：

```text
market_context 负责大级别背景，优先使用 1d 长窗口；
trend 负责当前趋势方向和强度，其中 1d 是主判断周期，4h 表达完整短周期趋势状态；
volatility 负责波动大小、压缩、扩张和异常波动状态；
risk_state 负责异常行情对信号可靠性的风险含义，不重复表达波动大小本身；
structure 负责支撑压力、区间边界和价格位置，不判断高位、低位或趋势中继；
structure 必须保留 1d 大结构与 4h 小结构两套事实，不强行合并成一个价格带或一个最终答案。
```

### 5.1 领域、原子和特征的依赖关系强度

FeatureLayer 与 AtomicSignal 之间是硬依赖关系。

含义：

```text
原子信号依赖的特征缺失时，该原子信号不得运行；
原子信号不得自己重算特征；
原子信号不得临时用其他特征替代声明依赖；
原子信号的特征依赖发生变化时，应形成新的 AtomicSignalDefinition 版本。
```

DomainSignal 与 AtomicSignal 之间是可组合依赖关系，但不是无约束关系。

含义：

```text
领域定义必须声明必需原子和可选原子；
必需原子缺失时，该领域不得作为完整正式领域进入 StrategyAnalysisRelease；
可选原子缺失时，领域可以运行，但必须在证据完整性、置信度或缺失说明中体现；
领域不得读取 allowed 列表之外的原子信号；
领域的原子组合发生计算语义变化时，应形成新的领域定义版本或领域依赖配置版本。
```

因此：

```text
没有 B 特征，就不能计算依赖 B 的 A 原子；
没有 F 原子，E 领域是否还能计算，取决于 F 是 E 的必需原子还是可选原子；
如果 E 领域从 F/G/H 改为只使用 G/H，必须形成可追溯的新领域版本或依赖配置版本，不能原地修改已发布版本。
```

后台当前配置工作区中，从 AtomicSignalDefinition 开始应支持“纳入 / 不纳入当前组合”的选择状态。

```text
未纳入的原子不参与领域输入，也不反推 FeatureDefinition；
未纳入的领域不参与 MarketRegime 输入；
FeatureDefinition 不单独设置纳入状态，只由已纳入原子的必需特征依赖自动进入版本包；
已经生成的 StrategyAnalysisRelease 不受后续纳入状态变化影响。
```

## 6. market_context 领域

### 6.1 领域问题

market_context 回答：

```text
当前市场处在什么大级别背景？
```

典型问题：

```text
当前是大级别偏多、偏空，还是无方向？
当前震荡发生在高位、低位，还是趋势中段？
当前是牛市回调，还是熊市反弹？
当前是否仍处于长期上涨结构中？
```

market_context 的重点是大级别背景，不替代 trend 对当前趋势的判断。

默认边界：

```text
market_context 使用 1d 长窗口事实；
trend 使用 1d 主趋势事实和 4h 短周期趋势状态事实；
二者可以使用相似类型的特征，但窗口、问题和输出语义必须不同。
```

### 6.2 候选 AtomicSignal 类型

```text
长期价格处于高位区；
长期价格处于低位区；
价格位于长期均线之上；
价格位于长期均线之下；
长期均线斜率向上；
长期均线斜率向下；
近一年收益为正；
近一年收益为负；
距离近一年高点较近；
距离近一年低点较近；
大级别回撤处于可接受范围；
大级别回撤过深；
当前更像牛市回调；
当前更像熊市反弹。
```

### 6.3 候选 Feature 类型

```text
1d 120 / 200 / 365 日均线；
1d 120 / 200 / 365 日均线斜率；
近 365 日高点；
近 365 日低点；
距离近 365 日高点百分比；
距离近 365 日低点百分比；
近 365 日收益率；
从近 365 日高点回撤百分比；
当前回撤持续天数；
当前反弹收复比例；
当前价格在近 365 日区间中的位置。
```

## 7. trend 领域

### 7.1 领域问题

trend 回答：

```text
当前趋势方向是什么？
趋势强度是否足够？
多周期趋势是否一致？
```

trend 只表达趋势事实，不表达交易动作。

trend 的重点是当前运行趋势，不替代 market_context 对大级别背景的判断。

默认边界：

```text
1d 用于当前运行趋势主判断；
4h 用于短周期趋势状态；
更长窗口的大级别背景归属于 market_context。
```

### 7.2 候选 AtomicSignal 类型

```text
4h 短周期趋势状态偏多；
4h 短周期趋势状态偏空；
1d 中长期趋势偏多；
1d 中长期趋势偏空；
趋势斜率增强；
趋势斜率减弱；
价格持续位于趋势均线上方；
价格持续位于趋势均线下方；
趋势结构尚未破坏；
趋势结构已破坏。
```

4h 与 1d 是否一致，不作为单独 AtomicSignal。原子层分别输出 1d 与 4h 的最小趋势事实，trend DomainSignal 再聚合判断 1d 与 4h 是否同向、是否为 1d 上行中的 4h 回调或 1d 下行中的 4h 反弹。4h 只影响短周期趋势状态，不影响 trend 的主方向、strength 和 agreement_ratio。

### 7.3 候选 Feature 类型

```text
4h / 1d SMA 或 EMA；
4h / 1d 均线排列；
4h / 1d 均线斜率；
价格相对趋势均线距离；
连续位于均线上方或下方的 K 线数量；
高低点抬高或降低的结构统计。
```

## 8. momentum 领域

### 8.1 领域问题

momentum 回答：

```text
当前趋势是否有推动力？
动量是在增强、减弱，还是出现衰竭？
日线级动能与短周期动能是否同向？
短周期动能是否只是反向修复或回调？
```

momentum 不决定是否交易，只为 MarketRegime 和 StrategySignal 提供推动力事实。

### 8.2 候选 AtomicSignal 类型

```text
1d 多头推进存在；
1d 空头推进存在；
1d 多头推进增强；
1d 空头推进增强；
1d 多头推进衰竭；
1d 空头推进衰竭；
1d 推进连续性；
1d 推进效率；
1d 收盘强弱；
4h 多头推进存在；
4h 空头推进存在；
4h 多头推进增强；
4h 空头推进增强；
4h 多头推进衰竭；
4h 空头推进衰竭；
4h 推进连续性；
4h 推进效率；
4h 收盘强弱。
```

突破伴随动量增强、突破但动量不跟随，不作为单个 momentum AtomicSignal。

原因：

```text
“突破”属于 structure 领域事实；
“动量增强”属于 momentum 领域事实；
二者是否同时出现，应由 MarketRegime 或 StrategySignal 在自身边界内综合，不应让 momentum 原子层跨领域读取 structure。
```

### 8.3 候选 Feature 类型

```text
4h / 1d 窗口收益率；
当前窗口相对前一窗口的收益率变化；
上涨 / 下跌 K 线占比；
连续上涨 / 连续下跌数量；
推进效率；
收盘位置；
MACD / RSI / ADX 等经典指标预留；
动量背离相关数值预留。
```

## 9. volatility 领域

### 9.1 领域问题

volatility 回答：

```text
当前波动状态是什么？
是低波动压缩、正常波动、波动扩张、宽幅震荡，还是异常高波动？
```

低波动本身不得被解释为仓位处理信号。

低波动必须结合 trend 与 structure 判断：

```text
趋势中的低波动可能只是整理；
无趋势下的低波动可能只是无方向压缩状态；
趋势破坏后的低波动可能只是结构未明状态。
```

### 9.2 候选 AtomicSignal 类型

```text
1d ATR 低分位；
1d ATR 高分位；
1d ATR 极高分位；
4h ATR 低分位；
4h ATR 高分位；
4h ATR 极高分位；
4h 已实现波动率低分位；
4h 已实现波动率高分位；
4h 波动压缩；
4h 波动扩张；
最新 K 线振幅较大；
最新 4h K 线实体主导；
最新 4h K 线影线主导；
行情高低区间偏宽；
行情高低区间偏窄。
```

### 9.3 候选 Feature 类型

```text
4h / 1d ATR 百分比；
4h / 1d 已实现波动率；
波动历史分位；
单根 K 线振幅；
单根 K 线实体和影线比例；
行情高低区间宽度；
短窗口波动相对长窗口波动的比例；
连续大振幅 K 线数量预留；
布林带宽度、Keltner Channel 等经典波动指标预留。
```

## 10. structure 领域

### 10.1 领域问题

structure 回答：

```text
当前价格处在什么结构位置？
支撑在哪里？
压力在哪里？
区间是否有效？
当前靠近支撑、压力、区间中部，还是已经突破或跌破？
```

structure 是支撑压力、区间结构和价格位置的领域事实。

structure 第一版必须区分：

```text
major_structure = 1d 大结构，用于表达大级别支撑压力和主要区间；
minor_structure = 4h 小结构，用于表达大区间内部的精细位置。
```

一份 structure DomainSignalValue 可以同时承载 major_structure 与 minor_structure，但不得把它们强行合并成一个支撑压力答案。

structure 只描述结构事实，不描述大级别高位、低位或趋势中继。

如果需要判断“高位宽幅震荡”“低位筑底”“趋势中继整理”，应由 MarketRegime 综合 market_context、trend、volatility 与 structure 后形成。

structure 不负责决定如何处理支撑、压力或跌破结构。

这些动作属于 StrategySignal。

### 10.2 候选 AtomicSignal 类型

```text
当前靠近支撑区；
当前靠近压力区；
当前位于区间中部；
支撑区多次有效；
压力区多次有效；
区间结构有效；
区间结构失效；
区间持续时间足够；
区间宽度足够；
区间边界清晰；
区间边界模糊；
向上突破压力区；
向下跌破支撑区；
突破后回踩不破；
跌破后反抽不过；
假突破风险高；
当前处于已识别区间内；
当前处于区间上半部；
当前处于区间下半部。
```

### 10.3 候选 Feature 类型

```text
近 N 根 4h 高点区域；
近 N 根 4h 低点区域；
近 N 根 1d 高点区域；
近 N 根 1d 低点区域；
1d 大结构支撑区上沿 / 下沿；
1d 大结构压力区上沿 / 下沿；
4h 小结构支撑区上沿 / 下沿；
4h 小结构压力区上沿 / 下沿；
当前价格距离支撑区百分比；
当前价格距离压力区百分比；
区间宽度百分比；
区间持续 K 线数量；
区间内停留 K 线数量；
支撑区触碰次数；
压力区触碰次数；
当前价格在区间中的位置百分比；
突破幅度；
跌破幅度；
突破后回踩深度；
跌破后反抽高度。
```

### 10.4 支撑压力必须是区域

系统不得只把支撑或压力表达为单点价格。

应表达为：

```text
support_zone = [support_lower, support_upper]
resistance_zone = [resistance_lower, resistance_upper]
```

原因：

```text
市场不会精确尊重一根线；
区间策略的风险边界需要价格带；
回测时可以避免事后画线过拟合。
```

structure 的 DomainSignalValue 需要能够承载结构化 payload，例如：

```json
{
  "major_structure": {
    "timeframe": "1d",
    "support_zone": {"lower": "58000", "upper": "60000"},
    "resistance_zone": {"lower": "68000", "upper": "70000"},
    "current_zone_position": "near_support",
    "range_position_ratio": "0.18"
  },
  "minor_structure": {
    "timeframe": "4h",
    "support_zone": {"lower": "63200", "upper": "63600"},
    "resistance_zone": {"lower": "65500", "upper": "66000"},
    "current_zone_position": "range_middle",
    "range_position_ratio": "0.51"
  }
}
```

payload 只保存结构事实，不保存交易动作。

structure 的具体第一版领域聚合规则以 `docs/requirements/domain_signals/structure_domain_signals_v1.md` 为准。

## 11. risk_state 领域

### 11.1 领域问题

risk_state 回答：

```text
当前行情是否存在会影响信号可靠性、方向暴露或追单风险的异常市场状态？
```

risk_state 不是账户风控。

账户、保证金、订单、持仓风险仍由 RiskCheck 负责。

risk_state 只表达市场状态风险。

risk_state 不重复表达波动大小本身。

```text
volatility 说明市场波动状态；
risk_state 说明异常行情是否构成信号可靠性风险、方向暴露风险、追多追空风险或市场扰动风险。
```

如果 risk_state 使用 K 线振幅、ATR 分位、影线比例等特征作为证据，输出也必须落在“风险状态”语义上，而不是再次输出“高波动”“低波动”。

risk_state 不得表达“风险高所以不操作”。如果系统已经有仓位，不操作本身也可能是风险暴露；risk_state 只表达条件性市场风险。StrategySignal 只生成策略级方向、强度、置信评分和证据；具体目标仓位属于 DecisionSnapshot；订单计划和交易动作属于 OrderPlan 及后续订单链路。

### 11.2 候选 AtomicSignal 类型

```text
连续大阴线风险；
连续大阳线追高风险；
插针风险；
急跌后反弹不稳定；
急涨后回落风险；
异常波动环境下突破或跌破信号可靠性下降；
结构跌破后尚未稳定；
突破后快速失败；
接近压力但追涨风险高；
接近支撑但下跌动量未止。
```

risk_state 的具体第一版领域聚合规则以 `docs/requirements/domain_signals/risk_state_domain_signals_v1.md` 为准。

### 11.3 候选 Feature 类型

```text
单根 K 线振幅；
实体占比；
上下影线比例；
连续大振幅数量；
连续同方向 K 线数量；
突破失败后的回撤幅度；
跌破后的反抽失败幅度；
ATR 分位；
价格跳变幅度。
```

## 12. 不建议独立成领域的内容

以下内容可以规划，但不建议作为独立领域。

### 12.1 突破 / 跌破

突破和跌破应优先作为 structure 领域下的原子信号。

原因：

```text
突破压力、跌破支撑，本质上都是结构位置变化；
如果单独做 breakout 领域，容易和 structure 重复计算同一证据。
```

动量是否配合突破，则应由 momentum 领域表达。

### 12.2 回调 / 反弹

回调和反弹通常需要 trend + structure + momentum 共同解释。

例如：

```text
上涨趋势中的正常回调；
上涨趋势回调过深；
下跌趋势中的普通反弹；
反弹未改变下跌结构。
```

这些更适合作为 MarketRegime 的综合分类结果，或作为 trend / structure 下的原子信号，不建议第一版独立成领域。

### 12.3 区间成熟度

区间成熟度应归入 structure 领域。

它回答的是：

```text
这个支撑压力区间是否足够清晰和可用？
```

不应单独拆成 range_maturity 领域。

### 12.4 信号稳定性

信号稳定性更适合 StrategySignalQuality。

原因：

```text
它通常依赖最近多轮策略信号或领域结果是否频繁翻转；
不一定适合在 AtomicSignal / DomainSignal 阶段计算；
它的主要用途是判断本轮策略信号是否可靠，而不是描述一个稳定市场领域。
```

## 13. 领域到 MarketRegime 的关系

MarketRegime 应综合多个领域，而不是重新计算领域事实。

DomainSignal 之间不得互相读取。

```text
structure 不读取 market_context 或 trend；
trend 不读取 structure；
risk_state 不读取 volatility；
跨领域语义统一由 MarketRegime 组合。
```

示例：

```text
market_context = 大级别偏多，当前处于长期高位区域；
trend = 偏多但推进减弱；
momentum = 减弱；
volatility = 宽幅震荡；
structure = 区间有效，当前靠近支撑；
risk_state = risk_clear。
```

MarketRegime 可以据此判断：

```text
大级别偏多下的高位区间震荡，当前靠近支撑。
```

MarketRegime 不得：

```text
直接读取 FeatureValue；
直接读取 AtomicSignalValue；
重新计算支撑压力；
重新判断趋势斜率；
执行策略；
输出目标仓位。
```

## 14. 领域到 StrategyRouting 的关系

StrategyRouting 消费 MarketRegime 的结果选择打法。

示例：

```text
大级别偏多 + 趋势延续或向上突破 → long_trend_following_v1；
大级别偏多 + 回调或高位区间靠近支撑 → long_pullback_support_v1；
大级别偏空 + 趋势延续或向下跌破 → short_trend_following_v1；
大级别偏空 + 中级别反弹靠近压力或低位区间靠近压力 → short_rebound_pressure_v1；
大级别偏多 + 区间中部 → 由 StrategyRouting 判断是否选择策略；
大级别偏空 + 反弹中部 → 由 StrategyRouting 判断是否选择策略；
高风险环境或不明确环境 → 由 StrategyRouting 判断是否选择策略。
```

StrategyRouting 不得重新读取领域事实替代 MarketRegime，也不得执行策略算法。

## 15. 领域到 StrategySignal 的关系

StrategySignal 只消费路由选中策略允许使用的 DomainSignalValue。

策略可以决定：

```text
如何使用支撑压力；
如何处理靠近支撑；
如何处理靠近压力；
如何处理跌破支撑；
如何处理向上突破；
如何处理大级别偏多但动量减弱；
如何处理高波动风险。
```

策略不得：

```text
直接读取 FeatureValue；
直接读取 AtomicSignalValue；
重新计算支撑压力；
重新识别 MarketRegime；
输出目标仓位；
生成订单动作。
```

## 16. 候选策略映射

本设计服务于以下候选策略方向。

### 16.1 long_trend_following_v1

适用：

```text
大级别偏多；
中短期趋势明确，或向上突破结构位；
趋势和动量配合；
波动和 risk_state 不显示信号不可用。
```

主要依赖领域：

```text
market_context
trend
momentum
volatility
structure
risk_state
```

策略判断：

```text
趋势延续 + 大背景与动量支持 → 偏多；
有效向上突破 + 趋势与动量支持 → 偏多；
突破但动量不跟随 → 信号质量偏弱；
高风险环境 → 信号可靠性下降；
突破失败 → 假突破风险上升。
```

### 16.2 long_pullback_support_v1

适用：

```text
大级别偏多；
中级别回调或进入高位区间震荡；
支撑压力结构有效。
```

主要依赖领域：

```text
market_context
trend
momentum
volatility
structure
risk_state
```

策略判断：

```text
靠近支撑 + 支撑未破 + risk_state 为 risk_clear 或 risk_elevated_classifiable → 偏多；
区间中部 → 方向优势不足；
靠近压力 + 未突破 → 上方空间受限；
向上突破压力 → 趋势突破策略输入条件可能成立；
向下跌破支撑 → 原支撑结构失效风险上升。
```

### 16.3 short_trend_following_v1

适用：

```text
大级别偏空；
中短期下跌趋势明确，或向下跌破结构位；
下跌趋势和动量配合；
波动和 risk_state 不显示信号不可用。
```

主要依赖领域：

```text
market_context
trend
momentum
volatility
structure
risk_state
```

策略判断：

```text
空头趋势延续 + 大背景与动量支持 → 偏空；
有效向下跌破 + 趋势与动量支持 → 偏空；
跌破但动量不跟随 → 信号质量偏弱；
高风险环境 → 信号可靠性下降；
跌破后快速收回 → 假跌破风险上升。
```

### 16.4 short_rebound_pressure_v1

适用：

```text
大级别偏空；
中级别出现反弹；
反弹接近压力区；
反弹没有改变下跌结构；
反弹动量衰竭或压力附近风险升高。
```

主要依赖领域：

```text
market_context
trend
momentum
volatility
structure
risk_state
```

策略判断：

```text
反弹靠近压力 + 压力未破 + risk_state 为 risk_clear 或 risk_elevated_classifiable → 偏空；
反弹中部 → 方向优势不足；
反弹突破压力并改变下跌结构 → 原空头反弹结构失效；
低位区间靠近压力且压力仍有效 → 偏空条件可能成立。
```

## 17. 进入正式链路的要求

本文档只是领域设计说明。

任何新增领域进入正式链路前，必须至少完成：

```text
对应 DomainSignalDefinition；
领域算法 requirements；
领域 calculator implementation 记录；
对应 AtomicSignalDefinition；
对应 FeatureDefinition；
领域归属唯一性校验；
MarketRegime requirements 更新；
StrategyRouting requirements 更新；
StrategySignal requirements 更新；
StrategySignalQuality requirements 更新；
StrategyAnalysisRelease 版本包选择、验证、人工批准和启用。
```

如果 `domain_signals.md` 与本文档发生冲突，以主需求文件 `domain_signals.md` 为准，直到主需求文件完成对应更新。

## 18. 明确禁止

禁止：

```text
把 structure 做成独立业务模块；
在 StrategySignal 内部重新计算支撑压力；
让 MarketRegime 直接读取 FeatureValue 或 AtomicSignalValue；
让 DomainSignal 输出交易动作；
让 DomainSignal 输出目标仓位；
把支撑压力单点价格当作完整结构事实；
把所有候选领域默认纳入正式运行；
绕过 StrategyAnalysisRelease 直接启用新增领域；
用大模型参与实时领域判断或策略判断。
```

## 19. 下一步文档拆分建议

如果确认本设计，建议后续按以下顺序补充正式算法 requirements：

```text
docs/requirements/feature_layer/market_context_features.md
docs/requirements/feature_layer/trend_features.md
docs/requirements/feature_layer/momentum_features.md
docs/requirements/feature_layer/volatility_features.md
docs/requirements/feature_layer/structure_features.md
docs/requirements/atomic_signals/market_context_atomic_signals.md
docs/requirements/atomic_signals/trend_atomic_signals.md
docs/requirements/atomic_signals/momentum_atomic_signals.md
docs/requirements/atomic_signals/volatility_atomic_signals.md
docs/requirements/atomic_signals/structure_atomic_signals.md
docs/requirements/domain_signals/market_context_domain_signals_v1.md
docs/requirements/domain_signals/trend_domain_signals_v1.md
docs/requirements/domain_signals/momentum_domain_signals_v1.md
docs/requirements/domain_signals/volatility_domain_signals_v1.md
docs/requirements/domain_signals/structure_domain_signals_v1.md
docs/requirements/domain_signals/risk_state_domain_signals_v1.md
docs/requirements/market_regime/context_structure_regime_v1.md
docs/requirements/strategy_signals/long_trend_following_v1.md
docs/requirements/strategy_signals/long_pullback_support_v1.md
docs/requirements/strategy_signals/short_trend_following_v1.md
docs/requirements/strategy_signals/short_rebound_pressure_v1.md
docs/requirements/decision_snapshot/position_policy_v1.md
```

这些文件应分别定义：

```text
输入；
输出；
算法公式；
参数；
边界条件；
失败条件；
证据结构；
回测验证要求；
进入 StrategyAnalysisRelease 的条件。
```
