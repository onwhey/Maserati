# 策略原子信号设计说明

## 1. 文档定位

本文档用于根据 [策略领域设计说明](../domain_signals/strategy_domain_design.md) 倒推策略分析链路需要的 AtomicSignal 类型。

本文档回答：

```text
每个领域下面需要哪些原子市场判断；
每类原子信号回答什么业务问题；
每类原子信号归属于哪个领域；
每类原子信号需要哪些 Feature 类型；
哪些原子信号适合作为 P0 正式候选；
哪些只适合作为后续研究；
哪些判断不应该放进 AtomicSignal。
```

本文档不定义具体算法公式、阈值或正式参数，不批准任何正式 AtomicSignalDefinition。

任何原子信号要进入正式主链路，仍必须具备：

```text
独立算法 requirements；
implementation 实现记录；
对应 FeatureDefinition；
对应 DomainSignalDefinition 归属；
测试和回测证据；
StrategyAnalysisRelease 选择、验证、人工批准和启用。
```

## 2. 设计原则

AtomicSignal 是最小市场判断。

它只回答：

```text
某个明确市场条件是否成立；
成立时表达什么方向或状态；
强度和证据是什么。
```

AtomicSignal 不负责：

```text
跨原子信号聚合；
跨领域综合；
识别整体市场环境；
选择策略；
执行策略算法；
输出目标仓位；
生成订单动作；
读取账户；
读取 PriceSnapshot；
访问 Binance；
调用大模型。
```

AtomicSignal 只能消费明确传入的 FeatureSet / FeatureValue。

FeatureLayer 是数据工厂，负责根据 MarketSnapshot 和 FeatureDefinition 计算并落库 FeatureValue。

AtomicSignal 是数据用户，只负责读取同一 FeatureSet 中已经落库的 FeatureValue，并基于这些值判断条件是否成立。

AtomicSignal 调用的是数据读取边界，不是 FeatureLayer 的算法函数。

多个 AtomicSignal 依赖同一个特征时，必须复用同一个 FeatureSet 内对应的同一份 FeatureValue，不得各自重复计算、临时派生或生成同义特征。

不得：

```text
读取 Kline；
读取 MarketSnapshot 原始行情重新计算特征；
调用 FeatureLayer calculator 或任何特征算法函数；
复制或内嵌 SMA、ATR、收益率变化、支撑压力、回撤比例、区间位置等 FeatureLayer 算法；
临时补算 Feature；
根据原子信号名字自动创建 Feature；
读取其他 AtomicSignal；
把多个 AtomicSignal 聚合成领域判断；
把 direction 解释成买卖指令。
```

## 3. 原子信号与领域的关系

原子信号必须归属于一个且仅一个正式领域。

当前规划领域：

```text
market_context
trend
momentum
volatility
structure
risk_state
```

同一个 StrategyAnalysisRelease 中，同一 AtomicSignalDefinition 不得被多个 DomainSignalDefinition 同时使用。

如果一个判断看似同时服务多个领域，应拆分为多个含义明确的原子信号，或重新确认它真正归属的领域。

示例：

```text
突破压力 = structure 原子信号；
同一窗口内短周期多头推进增强 = momentum 原子信号；
突破伴随动量增强 = 需要 structure 与 momentum 共同参与的跨领域综合结论，不是单个 AtomicSignal；
突破后快速失败 = risk_state 原子信号。
```

## 4. P0 / P1 / P2 分级

本文档使用以下分级：

```text
P0 = 第一批策略研究与正式候选优先设计；
P1 = 建议规划，但不一定进入第一版正式版本包；
P2 = 后续研究方向，需要更多数据或更多回测证据。
```

分级不等于正式启用。

正式启用只由 StrategyAnalysisRelease 决定。

## 5. market_context 原子信号

### 5.1 领域问题

market_context 用于判断大级别市场背景。

它回答：

```text
当前价格处在大级别什么位置；
长期结构是否偏多或偏空；
当前震荡发生在高位、低位还是中段；
当前更像牛市回调还是熊市反弹。
```

### 5.2 P0 候选原子信号

| 原子信号业务类型 | 业务含义 | 候选方向 / 状态 | 需要的 Feature 类型 |
|---|---|---|---|
| 长期价格位于长期均线上方 | 当前价格仍处于大级别均线之上 | bullish | 1d 长期均线、当前收盘价 |
| 长期价格位于长期均线下方 | 当前价格处于大级别均线之下 | bearish | 1d 长期均线、当前收盘价 |
| 长期均线斜率向上 | 长期趋势背景偏多 | bullish | 1d 长期均线斜率 |
| 长期均线斜率向下 | 长期趋势背景偏空 | bearish | 1d 长期均线斜率 |
| 当前处于近一年高位区 | 价格靠近长期区间上半部或高位区域 | state | 近一年高低点、当前位置百分比 |
| 当前处于近一年低位区 | 价格靠近长期区间下半部或低位区域 | state | 近一年高低点、当前位置百分比 |
| 大级别回撤未破坏长期结构 | 当前回撤仍可解释为长期上涨中的回调 | bullish / state | 近一年高点、回撤百分比、长期均线 |
| 大级别回撤过深 | 当前回撤已经威胁长期结构 | bearish / state | 近一年高点、回撤百分比、长期均线 |

### 5.3 P1 / P2 研究原子信号

```text
当前更像牛市回调；
当前更像熊市反弹；
长期高低点结构持续抬高；
长期高低点结构持续降低；
长期区间从低位切换到中位；
长期区间从高位回落到中位。
```

这些判断需要更严格的结构算法，暂不建议直接进入第一版正式版本包。

## 6. trend 原子信号

### 6.1 领域问题

trend 用于判断趋势方向、趋势强度和多周期一致性。

它回答：

```text
当前有没有方向；
方向是向上还是向下；
趋势是否仍然有效；
多周期是否一致。
```

### 6.2 P0 候选原子信号

| 原子信号业务类型 | 业务含义 | 候选方向 / 状态 | 需要的 Feature 类型 |
|---|---|---|---|
| 4h 短期趋势偏多 | 4h 趋势结构向上 | bullish | 4h 均线排列、斜率、价格相对均线 |
| 4h 短期趋势偏空 | 4h 趋势结构向下 | bearish | 4h 均线排列、斜率、价格相对均线 |
| 1d 中长期趋势偏多 | 日线趋势结构向上 | bullish | 1d 均线排列、斜率、价格相对均线 |
| 1d 中长期趋势偏空 | 日线趋势结构向下 | bearish | 1d 均线排列、斜率、价格相对均线 |
| 趋势斜率增强 | 趋势推进力度增强 | state / bullish 或 bearish | 均线斜率变化 |
| 趋势斜率减弱 | 趋势推进力度减弱 | state | 均线斜率变化 |
| 趋势结构尚未破坏 | 当前回撤未破坏趋势结构 | state | 关键结构位、均线、回撤深度 |
| 趋势结构已破坏 | 当前价格破坏趋势结构 | state / opposite direction | 关键结构位、均线、回撤深度 |

多周期趋势一致性不在原子层重复定义。原子层分别输出 1d 与 4h 的最小趋势事实，DomainSignal 再聚合判断 1d 与 4h 是否一致、是否为 1d 上行中的 4h 回调或 1d 下行中的 4h 反弹。

### 6.3 P1 / P2 研究原子信号

```text
高低点持续抬高；
高低点持续降低；
趋势推进暂停；
趋势重新启动；
趋势末端衰竭。
```

其中“趋势推进暂停”只能表达趋势推进状态变化，不得单独解释为“趋势中继整理”。“趋势中继整理”需要由 MarketRegime 综合 trend、momentum、volatility 与 structure 后形成。

## 7. momentum 原子信号

### 7.1 领域问题

momentum 用于判断趋势推动力和衰竭状态。

它回答：

```text
当前上涨或下跌有没有动力；
动量是在增强还是减弱；
突破或跌破是否有动量配合；
是否出现过热或背离。
```

### 7.2 P0 候选原子信号

| 原子信号业务类型 | 业务含义 | 候选方向 / 状态 | 需要的 Feature 类型 |
|---|---|---|---|
| 1d 多头推进存在 | 最近 7 根 1d 是否存在明显上涨推进 | bullish | 1d 窗口收益率 |
| 1d 空头推进存在 | 最近 7 根 1d 是否存在明显下跌推进 | bearish | 1d 窗口收益率 |
| 1d 多头推进增强 | 日线上涨推进是否相对前一窗口增强 | bullish | 1d 窗口收益率、前后窗口收益率变化 |
| 1d 空头推进增强 | 日线下跌推进是否相对前一窗口增强 | bearish | 1d 窗口收益率、前后窗口收益率变化 |
| 1d 多头推进衰竭 | 日线上涨仍在但推进速度减弱 | state | 1d 窗口收益率、前后窗口收益率变化 |
| 1d 空头推进衰竭 | 日线下跌仍在但下跌速度减弱 | state | 1d 窗口收益率、前后窗口收益率变化 |
| 1d 推进连续性 | 日线推进是否连续 | bullish / bearish / state | 1d 上涨 / 下跌 K 线占比、连续上涨 / 下跌数量 |
| 1d 推进效率 | 日线推进是否顺畅或拉扯严重 | state | 1d 推进效率 |
| 1d 收盘强弱 | 日线收盘更靠近高点还是低点 | bullish / bearish / state | 1d 收盘位置 |
| 4h 多头推进存在 | 最近 24 根 4h 是否存在明显上涨推进 | bullish | 4h 窗口收益率 |
| 4h 空头推进存在 | 最近 24 根 4h 是否存在明显下跌推进 | bearish | 4h 窗口收益率 |
| 4h 多头推进增强 | 短周期上涨推进是否相对前一窗口增强 | bullish | 4h 窗口收益率、前后窗口收益率变化 |
| 4h 空头推进增强 | 短周期下跌推进是否相对前一窗口增强 | bearish | 4h 窗口收益率、前后窗口收益率变化 |
| 4h 多头推进衰竭 | 短周期上涨仍在但推进速度减弱 | state | 4h 窗口收益率、前后窗口收益率变化 |
| 4h 空头推进衰竭 | 短周期下跌仍在但下跌速度减弱 | state | 4h 窗口收益率、前后窗口收益率变化 |
| 4h 推进连续性 | 短周期推进是否连续 | bullish / bearish / state | 4h 上涨 / 下跌 K 线占比、连续上涨 / 下跌数量 |
| 4h 推进效率 | 短周期推进是否顺畅或拉扯严重 | state | 4h 推进效率 |
| 4h 收盘强弱 | 短周期收盘更靠近高点还是低点 | bullish / bearish / state | 4h 收盘位置 |

### 7.3 P1 / P2 研究原子信号

```text
新高后动量不跟随；
新低后动量不跟随；
突破伴随动量增强；
突破但动量不跟随；
连续上涨后过热；
连续下跌后过热；
动量背离；
急涨后动量断裂；
急跌后反弹动量不足。
```

这些信号容易产生歧义，需要回测后确定是否进入正式版本包。

其中“突破伴随动量增强 / 突破但动量不跟随”需要 structure 领域的结构事实配合，不应在 momentum 原子层直接读取 structure 原子信号或领域信号。

## 8. volatility 原子信号

### 8.1 领域问题

volatility 用于判断波动状态。

它回答：

```text
当前是低波动压缩、正常波动、宽幅震荡还是异常高波动；
当前波动是否压缩、扩张或处于异常区间。
```

### 8.2 P0 候选原子信号

| 原子信号业务类型 | 业务含义 | 候选方向 / 状态 | 需要的 Feature 类型 |
|---|---|---|---|
| 1d ATR 低分位 | 日线 ATR 处于近期低分位 | state | 1d ATR 历史分位 |
| 1d ATR 高分位 | 日线 ATR 处于近期高分位 | state | 1d ATR 历史分位 |
| 1d ATR 极高分位 | 日线 ATR 处于近期极高分位 | state | 1d ATR 历史分位 |
| 4h ATR 低分位 | 短周期 ATR 处于近期低分位 | state | 4h ATR 历史分位 |
| 4h ATR 高分位 | 短周期 ATR 处于近期高分位 | state | 4h ATR 历史分位 |
| 4h ATR 极高分位 | 短周期 ATR 处于近期极高分位 | state | 4h ATR 历史分位 |
| 4h 已实现波动率低分位 | 短周期收盘收益率波动处于低分位 | state | 4h 已实现波动率分位 |
| 4h 已实现波动率高分位 | 短周期收盘收益率波动处于高分位 | state | 4h 已实现波动率分位 |
| 4h 波动压缩 | 短窗口波动明显低于长窗口 | state | 4h 短长波动比 |
| 4h 波动扩张 | 短窗口波动明显高于长窗口 | state | 4h 短长波动比 |
| 最新 K 线振幅较大 | 最新 K 线振幅明显大于常态 | state | K 线振幅、ATR 百分比 |
| 最新 4h 大实体 | 最新 4h K 线实体主导 | state | 4h 实体占比、振幅 |
| 最新 4h 影线主导 | 最新 4h K 线上影线或下影线主导 | state | 4h 影线比例 |
| 行情高低区间偏宽 | 近期行情高低活动范围偏宽 | state | 行情高低区间宽度 |
| 行情高低区间偏窄 | 近期行情高低活动范围偏窄 | state | 行情高低区间宽度 |

### 8.3 P1 / P2 研究原子信号

```text
连续大振幅 K 线出现；
波动压缩后方向性启动；
波动扩张但方向不明；
布林带宽度波动状态；
Keltner Channel 波动状态。
```

volatility 原子信号只表达波动事实，不得把“波动正常”解释成“可交易范围”。

## 9. structure 原子信号

### 9.1 领域问题

structure 用于判断价格在支撑压力和区间结构中的位置。

它回答：

```text
支撑在哪里；
压力在哪里；
区间是否有效；
当前靠近支撑、靠近压力、位于区间中部、突破压力还是跌破支撑。
```

structure 原子信号只表达结构事实，不表达交易动作。

structure 原子信号必须区分：

```text
major_structure = 1d 大结构；
minor_structure = 4h 小结构。
```

同一轮中，4h 小结构可以显示更精细的位置变化，但不得在原子层推翻 1d 大结构，也不得把两套结构强行合并成一个判断。

### 9.2 P0 候选原子信号

| 原子信号业务类型 | 业务含义 | 候选方向 / 状态 | 需要的 Feature 类型 |
|---|---|---|---|
| 当前靠近支撑区 | 价格接近下方支撑区域 | state | 支撑区、当前价格、距离百分比 |
| 当前靠近压力区 | 价格接近上方压力区域 | state | 压力区、当前价格、距离百分比 |
| 当前位于区间中部 | 价格离支撑压力都不近 | state | 支撑区、压力区、当前位置百分比 |
| 支撑区多次有效 | 支撑区被多次测试但未有效跌破 | state | 支撑触碰次数、跌破幅度 |
| 压力区多次有效 | 压力区被多次测试但未有效突破 | state | 压力触碰次数、突破幅度 |
| 区间结构有效 | 当前支撑压力区间仍可解释行情 | state | 区间上下沿、持续时间、触碰次数 |
| 区间结构失效 | 当前区间已被突破或跌破破坏 | state | 突破 / 跌破幅度、收盘确认 |
| 向上突破压力区 | 收盘有效突破压力区域 | bullish / state | 压力区、收盘价、突破幅度 |
| 向下跌破支撑区 | 收盘有效跌破支撑区域 | bearish / state | 支撑区、收盘价、跌破幅度 |
| 当前处于已识别区间内 | 价格仍处于可解释的支撑压力区间内 | state | 支撑区、压力区、当前价格 |
| 当前处于区间上半部 | 价格位于区间偏上位置 | state | 区间位置百分比 |
| 当前处于区间下半部 | 价格位于区间偏下位置 | state | 区间位置百分比 |

### 9.3 P1 / P2 研究原子信号

```text
区间持续时间足够；
区间宽度足够；
区间边界清晰；
区间边界模糊；
突破后回踩不破；
跌破后反抽不过；
假突破风险高；
压力区突破后转换为支撑区；
支撑区跌破后转换为压力区。
```

### 9.4 结构类原子信号的特别边界

支撑压力必须表达为区域，不得只表达为单点。

结构类原子信号不得输出：

```text
方向性交易处理；
仓位调整处理；
仓位退出处理；
止损；
止盈；
目标仓位；
订单动作。
```

例如：

```text
当前靠近支撑区 = structure 事实；
靠近支撑区所以偏多 = StrategySignal 判断；
靠近支撑区所以目标仓位 30% = DecisionSnapshot 之后的目标仓位语义。
```

structure 的具体 P0 原子信号清单以 `docs/requirements/atomic_signals/structure_atomic_signals.md` 为准。

## 10. risk_state 原子信号

### 10.1 领域问题

risk_state 用于判断市场状态风险。

它回答：

```text
当前行情是否存在会影响信号可靠性、方向暴露或追单风险的异常状态。
```

risk_state 不是账户风控，也不是订单风控。

账户、保证金、持仓、订单冲突和最大亏损仍由 RiskCheck 负责。

risk_state 不重复表达波动大小本身。

```text
volatility 说明市场波动状态；
risk_state 说明异常行情是否构成信号可靠性风险、方向暴露风险、追多追空风险或市场扰动风险。
```

risk_state 不得输出“风险高所以不操作”。如果系统已经有仓位，不操作本身也可能是风险暴露；AtomicSignal 只能输出条件性市场风险事实，不能读取账户判断真实持仓。

### 10.2 P0 候选原子信号

| 原子信号业务类型 | 业务含义 | 候选方向 / 状态 | 需要的 Feature 类型 |
|---|---|---|---|
| 连续大阴线风险 | 市场短期急跌，多头方向风险升高 | bearish / state | 连续下跌、振幅、实体比例 |
| 连续大阳线追高风险 | 市场短期急涨，上行追价风险升高 | state | 连续上涨、振幅、实体比例 |
| 异常波动环境下信号可靠性下降 | 异常波动下突破或跌破信号更容易失真 | state | ATR 分位、单根振幅、突破 / 跌破幅度 |
| 突破后快速失败 | 突破信号被快速否定 | state | 突破后回落幅度、收盘位置 |
| 结构跌破后尚未稳定 | 跌破支撑后尚未形成新稳定结构 | state | 跌破幅度、反抽失败、波动 |
| 接近支撑但下跌动量未止 | 支撑附近仍存在急跌风险 | state | 支撑距离、短周期收益率变化、连续下跌 |
| 接近压力但追涨风险高 | 压力附近继续追涨风险高 | state | 压力距离、振幅、动量过热 |

risk_state 的具体 P0 原子信号清单以 `docs/requirements/atomic_signals/risk_state_atomic_signals.md` 为准。

### 10.3 P1 / P2 研究原子信号

```text
插针风险；
急跌后反弹不稳定；
急涨后回落风险；
流动性异常风险。
```

流动性异常风险需要盘口、成交深度或价差数据；当前 P0 行情数据范围不支持正式实现。

## 11. 不应放入 AtomicSignal 的判断

以下判断不应放入 AtomicSignal。

### 11.1 策略动作

```text
支撑位置下的交易处理；
压力位置下的仓位处理；
跌破结构后的仓位处理；
突破结构后的仓位处理；
方向反转后的交易处理；
止盈；
止损；
交易进入动作；
平仓。
```

这些属于 StrategySignal、DecisionSnapshot、OrderPlan、RiskCheck 或 Execution 后续链路。

### 11.2 目标仓位

```text
目标仓位 30%；
目标仓位 50%；
目标空仓；
目标减半。
```

AtomicSignal 不输出目标仓位。

目标仓位语义只属于 DecisionSnapshot。

### 11.3 领域综合判断

```text
大级别偏多下的高位区间震荡；
上涨趋势中的宽幅震荡；
趋势破坏后的交易处理；
震荡偏空；
牛市回调。
```

这些属于 MarketRegime。

AtomicSignal 只能提供形成这些判断的最小证据。

### 11.4 策略信号质量判断

```text
最近几轮策略信号频繁翻转；
策略证据不自洽；
策略输出不稳定；
当前策略信号不允许进入 DecisionSnapshot。
```

这些优先属于 StrategySignalQuality。

如果未来确实需要从市场事实层描述“原子判断频繁翻转”，必须先单独定义数据来源和边界，不能让 AtomicSignal 读取历史 StrategySignal。

## 12. 领域到原子到特征的倒推示例

以 structure 领域为例。

领域问题：

```text
当前价格处于什么结构位置？
```

倒推出原子信号：

```text
当前靠近支撑区；
当前靠近压力区；
当前位于区间中部；
区间结构有效；
向上突破压力区；
向下跌破支撑区。
```

再倒推出特征：

```text
支撑区上下沿；
压力区上下沿；
当前价格；
距离支撑百分比；
距离压力百分比；
区间宽度；
触碰次数；
突破或跌破幅度。
```

这个过程说明：

```text
不是系统根据原子信号名字自动生成 Feature；
而是文档先定义原子信号依赖，再由 FeatureLayer requirements 明确补齐对应 FeatureDefinition。
```

## 13. 第一批正式候选建议

第一批正式候选不等于全部正式启用。

建议 P0 候选覆盖以下能力：

```text
大级别背景；
趋势方向；
动量强弱；
波动状态；
支撑压力结构；
异常市场风险。
```

但实际进入第一版 StrategyAnalysisRelease 时，应根据回测和验证证据选择最小闭环组合。

建议第一版至少支持两类策略研究：

```text
long_trend_following_v1；
long_pullback_support_v1；
short_trend_following_v1；
short_rebound_pressure_v1。
```

对应原子信号应优先支撑：

```text
是否大级别偏多；
是否大级别偏空；
是否趋势明确；
是否动量配合；
是否波动异常；
是否靠近支撑；
是否靠近压力；
是否突破压力；
是否跌破支撑；
区间结构是否有效；
是否处于牛市回调；
是否处于熊市反弹；
反弹是否接近压力；
反弹是否改变下跌结构；
反弹是否失败；
是否存在明显追涨、急跌或急拉风险。
```

## 14. 与 StrategyAnalysisRelease 的关系

本文档列出的所有原子信号都只是候选设计。

正式运行只允许消费：

```text
被当前 StrategyAnalysisRelease 原子信号切片明确选中；
状态 active；
enabled = true；
依赖 FeatureDefinition 完整；
恰好归属于一个正式 DomainSignalDefinition；
calculator 已注册；
算法 requirements 与 implementation 记录完整；
验证证据完整。
```

没有被版本包选择的原子信号，即使已经 active，也不得进入正式 AtomicSignalSet。

## 15. 下一步文档拆分建议

如果确认本设计，建议后续按以下顺序补充：

```text
docs/requirements/feature_layer/strategy_feature_design.md
docs/requirements/atomic_signals/market_context_atomic_signals.md
docs/requirements/atomic_signals/trend_atomic_signals.md
docs/requirements/atomic_signals/momentum_atomic_signals.md
docs/requirements/atomic_signals/volatility_atomic_signals.md
docs/requirements/atomic_signals/structure_atomic_signals.md
docs/requirements/atomic_signals/risk_state_atomic_signals.md
```

这些后续文件才定义：

```text
具体 signal_code；
具体算法；
具体阈值；
具体 params；
具体 strength 计算；
具体 confidence 含义；
具体 evidence_items；
具体测试向量；
具体回测验证要求。
```

## 16. 明确禁止

禁止：

```text
把支撑、压力或跌破结构下的交易处理写成 AtomicSignal；
让 AtomicSignal 自动推导或创建 Feature；
让 AtomicSignal 读取 Kline；
让 AtomicSignal 读取其他 AtomicSignal；
让 AtomicSignal 聚合形成 DomainSignal；
让 AtomicSignal 识别 MarketRegime；
让 AtomicSignal 选择 StrategyDefinition；
让 AtomicSignal 输出 target_position_ratio；
让 AtomicSignal 生成订单意图；
让 AtomicSignal 访问 Binance、DeepSeek 或账户事实；
绕过 StrategyAnalysisRelease 直接启用候选原子信号。
```
