# Context Structure Regime v1

## 1. 文件定位

本文档定义 MarketRegime 第一版具体市场环境分类算法：

```text
algorithm_name = context_structure_regime
algorithm_version = v1
```

它消费同一份 DomainSignalSet 中已经生成、已经落库、已经由 StrategyAnalysisRelease 选择的领域事实，生成一份 MarketRegimeSnapshot。

本文档回答：

```text
如何把 market_context、trend、momentum、volatility、structure、risk_state 六个领域组合成市场环境；
如何区分多头高位震荡、空头低位震荡和无方向震荡；
如何识别大级别趋势中的回调、反弹和反转候选；
哪些市场环境属于正常不明确，而不是系统错误；
MarketRegime 输出哪些 regime_code、评分、证据和中文解释。
```

本文档不负责：

```text
重新读取 K 线；
重新计算 FeatureValue；
重新计算 AtomicSignalValue；
重新计算 DomainSignalValue；
选择 StrategyDefinition；
生成 StrategySignal；
生成 DecisionSnapshot；
生成目标仓位；
生成订单动作；
读取账户、持仓、订单、成交或 PriceSnapshot；
请求 Binance；
调用大模型；
执行真实交易。
```

本算法进入正式 StrategyAnalysisRelease 前，必须具备：

```text
对应 implementation 实现记录；
calculator 注册；
测试覆盖；
回测或离线复核证据；
人工批准并启用的 StrategyAnalysisRelease。
```

正式运行时不读取 Markdown 文件；本文档只定义需求和验收合同。

## 2. 输入领域

本算法第一版要求六个领域全部存在：

| 领域 | 是否 required | 在本算法中的业务作用 |
|---|---|---|
| market_context | required | 判断大级别偏多、偏空还是不明确，以及长期高位、低位、回撤、反弹等背景 |
| trend | required | 判断 1d 主趋势与 4h 短周期趋势状态 |
| momentum | required | 判断 1d 主动能与 4h 短周期动能是否支持当前环境 |
| volatility | required | 判断波动压缩、正常、宽幅、高波动或极高波动 |
| structure | required | 判断 1d 大结构和 4h 小结构的位置、突破、跌破和区间状态 |
| risk_state | required | 判断市场风险状态是清晰、升高但可分类、高信号不可靠风险，还是风险不明确，并提供风险类别 |

如果任何 required 领域缺失、无效或不属于同一 DomainSignalSet：

```text
MarketRegimeService 必须 blocked 或 failed；
不得用默认值补齐；
不得跳过该领域；
不得生成可消费 MarketRegimeSnapshot。
```

`risk_state` 的 Feature / Atomic / Domain 具体算法文件、对应实现和验证证据必须与本算法一起进入同一 StrategyAnalysisRelease；缺失任一层时，本算法不得进入正式运行。

## 3. 输入归一化

Calculator 不直接读取底层原子信号或特征，只读取 DomainSignalValue。

为了避免把领域内部状态码直接写死在业务 service 中，calculator 在内部先把六个领域归一化为以下业务语义。

### 3.1 market_context 归一化

必须识别：

```text
大背景偏多；
大背景偏空；
大背景不明确；
长期高位；
长期低位；
长期回撤；
长期反弹；
收复较强；
收复较弱。
```

其中：

```text
大背景偏多 / 偏空 / 不明确来自 market_context.direction；
长期高位、低位、回撤、反弹和收复状态来自 market_context.state_code、state_tags 或 payload_summary。
```

### 3.2 trend 归一化

必须识别：

```text
1d 趋势偏多；
1d 趋势偏空；
1d 趋势不明确；
4h 与 1d 同向；
4h 与 1d 反向；
4h 不明确；
多头背景下的 4h 回调；
空头背景下的 4h 反弹。
```

典型来源：

```text
trend.direction = bullish / bearish / neutral；
trend.state_code = trend_1d_bullish_4h_aligned；
trend.state_code = trend_1d_bullish_4h_pullback；
trend.state_code = trend_1d_bearish_4h_aligned；
trend.state_code = trend_1d_bearish_4h_rebound；
trend.state_code = trend_unclear。
```

4h 只用于识别短周期状态，不得单独推翻 1d 主趋势。

### 3.3 momentum 归一化

必须识别：

```text
1d 动能偏多；
1d 动能偏空；
1d 动能不明确；
1d 动能增强；
1d 动能衰竭；
1d 动能拉扯；
4h 动能偏多；
4h 动能偏空；
4h 动能增强；
4h 动能衰竭；
4h 动能拉扯。
```

典型来源：

```text
momentum.direction；
momentum.state_code；
momentum.payload_summary.short_cycle_momentum_direction；
momentum.payload_summary.primary_momentum_phase；
momentum.state_tags。
```

momentum 只表达推动力事实，不直接决定交易方向。

### 3.4 volatility 归一化

必须识别：

```text
低波动；
低波动压缩；
正常波动；
高波动；
极高波动；
波动混合；
宽幅震荡条件。
```

典型来源：

```text
volatility.state_code = volatility_low；
volatility.state_code = volatility_low_compression；
volatility.state_code = volatility_normal；
volatility.state_code = volatility_high；
volatility.state_code = volatility_extreme；
volatility.state_code = volatility_mixed；
volatility.state_tags。
```

volatility 只描述波动状态。是否因此形成高风险环境，优先由 risk_state 表达。

### 3.5 structure 归一化

必须同时保留：

```text
major_structure = 1d 大结构；
minor_structure = 4h 小结构。
```

必须识别：

```text
1d 大结构靠近支撑；
1d 大结构靠近压力；
1d 大结构处于区间中部；
1d 大结构处于下半区；
1d 大结构处于上半区；
1d 大结构向上突破；
1d 大结构向下跌破；
1d 大结构不明确；
4h 小结构靠近支撑；
4h 小结构靠近压力；
4h 小结构处于区间中部；
4h 小结构向上突破；
4h 小结构向下跌破；
4h 小结构不明确。
```

4h 小结构不得单独推翻 1d 大结构，只能补充短周期位置和早期变化。

### 3.6 risk_state 归一化

必须识别：

```text
risk_clear = 无明显异常市场风险；
risk_elevated_classifiable = 风险升高但类型清楚，普通环境仍可分类；
risk_high_signal_unreliable = 风险已经让普通环境分类可靠性显著下降；
risk_unclear = 风险证据互相冲突，无法可靠判断风险性质。
```

还必须读取 risk_state.payload_summary 中的风险摘要：

```text
dominant_risk_categories；
risk_directions；
signal_reliability_score；
long_exposure_score；
short_exposure_score；
long_chase_score；
short_chase_score；
false_breakout_score；
false_breakdown_score；
market_disorder_score；
signal_unreliable_reason。
```

如果 risk_state.state_code = risk_high_signal_unreliable，本算法必须优先输出 `high_risk_environment`。

如果 risk_state.state_code = risk_unclear，本算法不得继续输出普通多头、空头或震荡环境，应优先输出 `unclear_environment`。

如果 risk_state.state_code = risk_elevated_classifiable，本算法可以继续普通环境分类，但必须把风险类别、风险方向和主要风险分写入 evidence_items / payload_summary。该状态不得被解释为“自动不操作”或“自动少做”。

risk_state 不得由 MarketRegime 临时用 volatility 自行替代；如果 risk_state 缺失，应阻断本算法正式运行。

## 4. 允许输出的 regime_code

本算法允许输出以下 regime_code：

| regime_code | 中文名称 | 业务含义 |
|---|---|---|
| high_risk_environment | 高风险环境 | 市场风险状态使普通环境分类可靠性显著下降 |
| bullish_trend_continuation | 多头趋势延续 | 大背景偏多，1d 趋势与动能继续支持上涨结构 |
| bullish_breakout | 多头向上突破 | 大背景偏多或至少不偏空，价格有效突破压力结构，趋势、动能和风险状态支持突破不是噪音 |
| bullish_pullback | 多头回调 | 大背景偏多，1d 结构未破坏，但 4h 或动能出现回调 |
| bullish_high_range | 多头高位震荡 | 大背景偏多，价格位于长期高位或大结构高位区间，趋势推进暂缓 |
| bullish_top_reversal_candidate | 多头顶部反转候选 | 大背景仍偏多，但 4h 小结构、动能或压力区行为提示顶部转弱候选 |
| bearish_trend_continuation | 空头趋势延续 | 大背景偏空，1d 趋势与动能继续支持下跌结构 |
| bearish_breakdown | 空头向下跌破 | 大背景偏空或至少不偏多，价格有效跌破支撑结构，趋势、动能和风险状态支持跌破不是噪音 |
| bearish_rebound | 空头反弹 | 大背景偏空，1d 下跌结构未确认改变，但 4h 或动能出现反弹 |
| bearish_low_range | 空头低位震荡 | 大背景偏空，价格位于长期低位或大结构低位区间，趋势推进暂缓 |
| bearish_bottom_reversal_candidate | 空头底部反转候选 | 大背景仍偏空，但 4h 小结构、动能或支撑区行为提示底部转强候选 |
| neutral_range | 无方向震荡 | 大背景不明确，趋势不明确，但结构区间相对有效 |
| unclear_environment | 不明确环境 | 输入有效但候选环境分数不足、冲突过大或无法形成稳定分类 |

这些 code 只表达市场环境。

它们不得被解释为：

```text
交易方向；
仓位动作；
止损；
止盈；
目标仓位；
订单动作。
```

## 5. 分类优先级

本算法按固定优先级分类。

```text
1. 先处理 risk_state = risk_high_signal_unreliable；
2. 再处理 risk_state = risk_unclear；
3. 再判断 market_context 大背景；
4. 在大背景内部判断 trend 主方向；
5. 优先识别有效向上突破或向下跌破；
6. 使用 structure 定位当前价格位置和短周期结构变化；
7. 使用 momentum 判断推进、衰竭或反向修复；
8. 使用 volatility 判断环境是否宽幅、压缩、正常或过度混乱；
9. 若候选分数不足或冲突过大，输出 unclear_environment；
10. 若大背景不明确但区间结构有效，输出 neutral_range。
```

不得反过来用 4h 小结构或短周期动能直接改写大背景。

## 6. 硬性分类规则

### 6.1 高风险环境

如果 risk_state.state_code = risk_high_signal_unreliable：

```text
regime_code = high_risk_environment
regime_scores.high_risk_environment = 1
classification_margin 按 high_risk_environment 与第二高候选分数计算
```

此时仍应记录其他领域证据摘要，但不得继续输出普通多头、空头或震荡环境。

### 6.1.1 风险不明确环境

如果 risk_state.state_code = risk_unclear：

```text
regime_code = unclear_environment
regime_scores.unclear_environment 至少不低于 0.70
classification_margin 按 unclear_environment 与第二高候选分数计算
```

此时不得继续输出普通多头、空头或震荡环境。

解释：

```text
risk_unclear 表示风险证据本身无法形成清楚解释；
它不是普通无方向震荡；
它也不是 high_risk_environment；
它应形成不明确环境，后续是否选择策略由 StrategyRouting 决定。
```

### 6.2 多头趋势延续

必须同时满足：

```text
market_context 大背景偏多；
trend 1d 偏多；
trend 4h 与 1d 同向或不明显反向；
momentum 1d 偏多，且没有明显衰竭；
structure 1d 大结构未跌破；
risk_state = risk_clear 或 risk_elevated_classifiable。
```

支持证据包括：

```text
structure 1d 向上突破；
structure 4h 向上突破；
volatility 正常、低波动压缩后扩张或非极端高波动；
market_context 未显示严重回撤破坏。
```

硬排除：

```text
structure 1d 大结构向下跌破；
trend 1d 偏空；
risk_state = risk_high_signal_unreliable 或 risk_unclear。
```

### 6.2.1 多头向上突破

必须同时满足：

```text
market_context 大背景偏多，或 market_context 不明确但 trend 1d 已偏多；
trend 1d 偏多或正在由不明确转向偏多；
structure 1d 大结构向上突破，或 structure 4h 小结构向上突破且 1d 大结构未显示向下破坏；
momentum 1d 或 4h 支持向上推进，且没有明显多头动能衰竭；
risk_state = risk_clear 或 risk_elevated_classifiable。
```

支持证据包括：

```text
structure 1d 与 4h 同时向上突破；
volatility 从压缩转扩张，但未进入高信号不可靠风险；
market_context 长期背景未处于深度破坏；
false_breakout_score 未升高。
```

硬排除：

```text
market_context 明确偏空且 trend 1d 未转多；
structure 1d 大结构向下跌破；
momentum 明显不支持向上推进；
risk_state = risk_high_signal_unreliable 或 risk_unclear。
```

该状态只表示“多头向上突破环境”成立，不表示交易进入动作。

### 6.3 多头回调

必须同时满足：

```text
market_context 大背景偏多；
trend 1d 仍偏多或未确认转空；
4h 趋势回调、4h 动能偏空，或 momentum 1d 多头动能衰竭；
structure 1d 大结构未跌破；
risk_state = risk_clear 或 risk_elevated_classifiable。
```

支持证据包括：

```text
structure 1d 靠近大支撑或下半区；
structure 4h 靠近小支撑；
market_context 处于中等回撤而非深度破坏；
volatility 未进入极端失控。
```

硬排除：

```text
market_context 大背景偏空；
structure 1d 大结构向下跌破；
trend 1d 明确偏空且 market_context 不再偏多。
```

### 6.4 多头高位震荡

必须同时满足：

```text
market_context 大背景偏多；
market_context 显示长期高位，或 structure 1d 显示大结构上半区 / 靠近大压力；
trend 推进减弱、4h 反复，或 trend 1d 仍偏多但 4h 不同向；
structure 1d 大区间有效；
risk_state = risk_clear 或 risk_elevated_classifiable。
```

支持证据包括：

```text
volatility 高波动但 risk_state = risk_clear / risk_elevated_classifiable，或宽幅震荡；
momentum 1d 多头动能衰竭 / 拉扯；
structure 4h 在小区间内反复。
```

它和无方向震荡的区别：

```text
多头高位震荡必须有大背景偏多或长期高位证据；
无方向震荡的大背景本身不明确。
```

### 6.5 多头顶部反转候选

必须同时满足：

```text
market_context 大背景仍偏多；
trend 1d 尚未确认偏空；
structure 1d 靠近大压力、高位区间，或 4h 小结构向下跌破；
momentum 1d 多头动能衰竭，或 4h 空头动能增强；
risk_state = risk_clear 或 risk_elevated_classifiable。
```

支持证据包括：

```text
volatility 高波动或波动混合；
structure 4h 靠近小压力后跌破；
trend state_code 表达 4h 回调；
market_context 长期高位。
```

硬排除：

```text
market_context 已明确偏空；
trend 1d 已明确偏空且大背景不再偏多。
```

该状态不是“已经反转”，只是顶部反转候选。后续如何处理该候选环境，由 StrategyRouting / StrategySignal 决定。

### 6.6 空头趋势延续

必须同时满足：

```text
market_context 大背景偏空；
trend 1d 偏空；
trend 4h 与 1d 同向或不明显反向；
momentum 1d 偏空，且没有明显衰竭；
structure 1d 大结构未向上突破；
risk_state = risk_clear 或 risk_elevated_classifiable。
```

支持证据包括：

```text
structure 1d 向下跌破；
structure 4h 向下跌破；
volatility 正常或非极端高波动；
market_context 未显示强收复改变大背景。
```

硬排除：

```text
structure 1d 大结构向上突破；
trend 1d 偏多；
risk_state = risk_high_signal_unreliable 或 risk_unclear。
```

### 6.6.1 空头向下跌破

必须同时满足：

```text
market_context 大背景偏空，或 market_context 不明确但 trend 1d 已偏空；
trend 1d 偏空或正在由不明确转向偏空；
structure 1d 大结构向下跌破，或 structure 4h 小结构向下跌破且 1d 大结构未显示向上突破；
momentum 1d 或 4h 支持向下推进，且没有明显空头动能衰竭；
risk_state = risk_clear 或 risk_elevated_classifiable。
```

支持证据包括：

```text
structure 1d 与 4h 同时向下跌破；
volatility 从压缩转扩张，但未进入高信号不可靠风险；
market_context 长期背景未出现强收复；
false_breakdown_score 未升高。
```

硬排除：

```text
market_context 明确偏多且 trend 1d 未转空；
structure 1d 大结构向上突破；
momentum 明显不支持向下推进；
risk_state = risk_high_signal_unreliable 或 risk_unclear。
```

该状态只表示“空头向下跌破环境”成立，不表示交易进入动作。

### 6.7 空头反弹

必须同时满足：

```text
market_context 大背景偏空；
trend 1d 仍偏空或未确认转多；
4h 趋势反弹、4h 动能偏多，或 momentum 1d 空头动能衰竭；
structure 1d 大结构未向上突破；
risk_state = risk_clear 或 risk_elevated_classifiable。
```

支持证据包括：

```text
structure 1d 靠近大压力或上半区；
structure 4h 靠近小压力；
market_context 出现反弹但收复不足；
volatility 未进入极端失控。
```

硬排除：

```text
market_context 大背景偏多；
structure 1d 大结构向上突破；
trend 1d 明确偏多且 market_context 不再偏空。
```

### 6.8 空头低位震荡

必须同时满足：

```text
market_context 大背景偏空；
market_context 显示长期低位，或 structure 1d 显示大结构下半区 / 靠近大支撑；
trend 推进减弱、4h 反复，或 trend 1d 仍偏空但 4h 不同向；
structure 1d 大区间有效；
risk_state = risk_clear 或 risk_elevated_classifiable。
```

支持证据包括：

```text
volatility 高波动但 risk_state = risk_clear / risk_elevated_classifiable，或宽幅震荡；
momentum 1d 空头动能衰竭 / 拉扯；
structure 4h 在小区间内反复。
```

它和无方向震荡的区别：

```text
空头低位震荡必须有大背景偏空或长期低位证据；
无方向震荡的大背景本身不明确。
```

### 6.9 空头底部反转候选

必须同时满足：

```text
market_context 大背景仍偏空；
trend 1d 尚未确认偏多；
structure 1d 靠近大支撑、低位区间，或 4h 小结构向上突破；
momentum 1d 空头动能衰竭，或 4h 多头动能增强；
risk_state = risk_clear 或 risk_elevated_classifiable。
```

支持证据包括：

```text
volatility 高波动或波动混合；
structure 4h 靠近小支撑后突破；
trend state_code 表达 4h 反弹；
market_context 长期低位。
```

硬排除：

```text
market_context 已明确偏多；
trend 1d 已明确偏多且大背景不再偏空。
```

该状态不是“已经反转”，只是底部反转候选。后续如何处理该候选环境，由 StrategyRouting / StrategySignal 决定。

### 6.10 无方向震荡

必须同时满足：

```text
market_context 大背景不明确；
trend 1d 不明确，或 trend 与 momentum 无法形成稳定同向解释；
structure 1d 或 4h 区间有效；
risk_state = risk_clear 或 risk_elevated_classifiable。
```

支持证据包括：

```text
volatility 正常、高波动但 risk_state = risk_clear / risk_elevated_classifiable，或低波动压缩；
structure 1d / 4h 处于区间中部；
momentum 中性或拉扯。
```

无方向震荡不是：

```text
多头高位震荡；
空头低位震荡；
牛市回调；
熊市反弹。
```

只要 market_context 明确偏多或偏空，就不得把震荡直接归为 `neutral_range`。

### 6.11 不明确环境

以下情况输出 `unclear_environment`：

```text
领域输入有效，但候选分数最高值低于最小分类阈值；
最高候选和第二候选差距过小；
领域事实存在强冲突，且不满足 neutral_range；
market_context 明确，但 trend / momentum / structure 无法支持任何同背景环境；
risk_state = risk_unclear。
```

`unclear_environment` 是合法市场环境，不是系统错误。

## 7. 候选评分规则

每个普通候选环境包含：

```text
mandatory_evidence = 必须满足的条件；
supporting_evidence = 支持但非必需的条件；
hard_exclusion = 硬排除条件。
```

评分规则：

```text
mandatory_score = 已满足 mandatory_evidence 数量 / mandatory_evidence 总数量；
supporting_score = 已满足 supporting_evidence 数量 / supporting_evidence 总数量；
raw_score = 0.70 * mandatory_score + 0.30 * supporting_score；
如果任一 hard_exclusion 成立，raw_score 上限为 0.35；
如果 risk_state = risk_high_signal_unreliable，除 high_risk_environment 外所有普通候选 raw_score 上限为 0.20。
如果 risk_state = risk_unclear，除 unclear_environment 外所有普通候选 raw_score 上限为 0.20。
```

如果某个候选没有 supporting_evidence：

```text
supporting_score = 0
raw_score = mandatory_score
```

所有 regime_code 都必须出现在 `regime_scores` 中。未参与候选评分的 code 分数为 0。

## 8. 最终选择规则

参数：

| 参数 | 值 | 说明 |
|---|---:|---|
| 最小分类分数 | 0.55 | 最高候选低于该值时输出 unclear_environment |
| 最小分类差距 | 0.10 | 最高候选与第二候选差距低于该值时输出 unclear_environment |
| 高风险环境分数 | 1.00 | risk_state = risk_high_signal_unreliable 时直接输出 |
| 突破 / 跌破候选优先阈值 | 0.68 | 有效突破 / 跌破达到该分数时，优先于同方向普通趋势延续、回调 / 反弹和区间震荡 |
| 反转候选优先阈值 | 0.65 | 反转候选达到该分数时，优先于普通回调 / 反弹 |
| 震荡候选优先阈值 | 0.60 | 高位 / 低位震荡达到该分数时，优先于普通回调 / 反弹 |

选择流程：

```text
1. 如果 risk_state = risk_high_signal_unreliable，直接选择 high_risk_environment；
2. 如果 risk_state = risk_unclear，直接选择 unclear_environment；
3. 计算所有普通候选分数；
4. 如果 bullish_breakout 或 bearish_breakdown 分数 >= 0.68 且无硬排除，优先于同方向普通趋势延续、回调 / 反弹和区间震荡参与最终比较；
5. 如果反转候选分数 >= 0.65 且无硬排除，优先在同背景候选中参与最终比较；
6. 如果高位 / 低位震荡分数 >= 0.60 且无硬排除，优先在同背景候选中参与最终比较；
7. 取最高分候选；
8. 如果最高分 < 0.55，输出 unclear_environment；
9. 如果最高分与第二高分差距 < 0.10，输出 unclear_environment；
10. 否则输出最高分候选。
```

如果 `bullish_breakout` 与 `bullish_trend_continuation` 同时得分较高：

```text
bullish_breakout 达到 0.68 且 structure 明确突破 → 优先 bullish_breakout；
否则保留 bullish_trend_continuation。
```

如果 `bearish_breakdown` 与 `bearish_trend_continuation` 同时得分较高：

```text
bearish_breakdown 达到 0.68 且 structure 明确跌破 → 优先 bearish_breakdown；
否则保留 bearish_trend_continuation。
```

如果 `neutral_range` 与 `bullish_high_range` 或 `bearish_low_range` 同时得分较高：

```text
market_context 偏多 → 优先 bullish_high_range；
market_context 偏空 → 优先 bearish_low_range；
market_context neutral → 只能选择 neutral_range 或 unclear_environment。
```

## 9. regime_confidence 与 classification_margin

```text
classification_margin = 最高候选分数 - 第二高候选分数
```

`regime_confidence` 公式：

```text
margin_component = min(classification_margin / 0.30, 1)
regime_confidence = clamp(0, 1, 0.70 * top_score + 0.30 * margin_component)
```

输出 `unclear_environment` 时：

```text
regime_confidence 不得高于 0.50；
classification_margin 仍保存真实候选差距；
regime_scores 仍保存所有候选分数。
```

`regime_confidence` 只表示环境分类明确程度，不是盈利概率、上涨概率、下跌概率或交易成功率。

## 10. 输出要求

CalculatorOutput 必须包含：

```text
regime_code；
regime_scores；
regime_confidence；
classification_margin；
used_domain_signal_value_refs；
evidence_items；
evidence_text_zh；
payload_summary。
```

### 10.1 regime_scores

必须包含全部 allowed_regime_codes：

```text
high_risk_environment
bullish_trend_continuation
bullish_breakout
bullish_pullback
bullish_high_range
bullish_top_reversal_candidate
bearish_trend_continuation
bearish_breakdown
bearish_rebound
bearish_low_range
bearish_bottom_reversal_candidate
neutral_range
unclear_environment
```

### 10.2 evidence_items

每条 evidence_items 至少包含：

```text
domain_code；
domain_signal_value_id；
used_field；
observed_value；
normalized_meaning；
contributes_to_regime_code；
evidence_role = mandatory / supporting / exclusion / explanation；
```

不得保存 FeatureValue 或 AtomicSignalValue 的直接引用作为 MarketRegime 的正式输入证据。

### 10.3 evidence_text_zh

必须用中文解释：

```text
大背景是什么；
趋势是什么；
动能是否支持；
波动是否异常；
1d 大结构在哪里；
4h 小结构是否出现早期变化；
如果选择 bullish_breakout / bearish_breakdown，必须说明突破或跌破来自 1d 大结构、4h 小结构，还是二者共同成立；
风险状态是清晰、升高但可分类、高信号不可靠风险，还是风险不明确；
如果风险升高但仍可分类，主要风险类别、风险方向和关键风险分是什么；
为什么选择最终 regime_code；
为什么没有选择主要竞争候选。
```

示例：

```text
大背景偏多，1d 趋势仍偏多，但 4h 趋势回调，1d 大结构未跌破且价格接近大支撑；动能出现短周期走弱，risk_state 为风险升高但可分类，主要风险是多头暴露风险和追多风险，因此归类为多头回调，而不是空头趋势或高风险环境。
```

## 11. 多头震荡、空头震荡和无方向震荡的区分

本算法必须严格区分：

```text
多头高位震荡；
空头低位震荡；
无方向震荡。
```

区分原则：

```text
震荡发生在大背景偏多里 → 多头高位震荡或多头回调区间；
震荡发生在大背景偏空里 → 空头低位震荡或空头反弹区间；
大背景本身不明确 → 无方向震荡。
```

因此：

```text
market_context.direction = bullish 时，不得因为 trend 短期不明确就输出 neutral_range；
market_context.direction = bearish 时，不得因为 trend 短期不明确就输出 neutral_range；
只有 market_context.direction = neutral，且结构区间有效，才允许输出 neutral_range。
```

这条规则用于避免系统把“大级别上涨后的高位横盘”误判为普通无方向震荡，也避免把“大级别下跌后的低位横盘”误判为普通无方向震荡。

## 12. 反转候选的处理

底部或顶部反转往往先出现在 4h，而日线不会立刻确认。

本算法允许输出：

```text
bullish_top_reversal_candidate；
bearish_bottom_reversal_candidate。
```

但必须遵守：

```text
4h 小结构只能提示反转候选；
4h 小结构不得单独把大背景从偏空改成偏多；
4h 小结构不得单独把大背景从偏多改成偏空；
反转候选不是反转确认；
反转候选不是交易动作。
```

示例：

```text
大背景偏空 + 1d 趋势仍偏空 + 1d 靠近大支撑 + 4h 向上突破 + 4h 多头动能增强
→ bearish_bottom_reversal_candidate。

大背景偏多 + 1d 趋势仍偏多 + 1d 靠近大压力 + 4h 向下跌破 + 4h 空头动能增强
→ bullish_top_reversal_candidate。
```

是否以及如何处理反转候选，由 StrategyRouting 和 StrategySignal 决定。

## 13. 边界条件

### 13.1 required 领域缺失

任一 required 领域缺失：

```text
不生成 MarketRegimeSnapshot；
返回 blocked 或 failed；
写 AlertEvent；
不得输出 unclear_environment 伪装正常不明确。
```

### 13.2 领域计算成功但市场不明确

如果六个领域均有效，但无法形成明确分类：

```text
regime_code = unclear_environment；
status = created；
is_usable = true；
allows_strategy_routing = true；
```

后续是否选择具体策略，由 StrategyRouting 决定。

### 13.3 高风险与不明确不同

```text
high_risk_environment = 风险状态明确使普通分类可靠性显著下降；
unclear_environment = 领域输入有效，但环境本身不明确或冲突；
neutral_range = 大背景不明确，但区间结构相对有效。
```

三者不得混用。

### 13.4 波动异常但 risk_state 未确认

volatility 极高或混合只能作为证据。

如果 risk_state = risk_clear 或 risk_elevated_classifiable：

```text
不得仅凭 volatility 直接输出 high_risk_environment；
可以降低普通候选分数；
可以把异常波动作为普通候选的支持或排除证据。
```

如果 risk_state = risk_unclear：

```text
不得伪装成普通震荡；
优先输出 unclear_environment。
```

## 14. 与 StrategyRouting 的关系

MarketRegime 只输出市场环境。

可能的路由含义由 StrategyRouting 独立定义。MarketRegime 不在本文件中预设具体路由结果。

```text
不同 regime_code 可以被 StrategyRouting 映射到不同 StrategyDefinition；
也可以被 StrategyRouting 映射为本轮不选择策略；
具体映射必须由 strategy_routing.md 中的路由规则定义。
```

本文档不定义正式路由规则。

## 15. 验收要求

至少覆盖以下测试场景：

```text
大背景偏多 + 1d/4h 同向 + 动能支持 → bullish_trend_continuation；
大背景偏多 + 1d 或 4h 有效突破压力 + 动能支持 + 假突破风险不高 → bullish_breakout；
大背景偏多 + 1d 未破 + 4h 回调 + 靠近 1d 支撑 → bullish_pullback；
大背景偏多 + 长期高位 + 区间有效 + 推进减弱 → bullish_high_range；
大背景偏多 + 靠近大压力 + 4h 跌破 + 动能衰竭 → bullish_top_reversal_candidate；
大背景偏空 + 1d/4h 同向 + 动能支持 → bearish_trend_continuation；
大背景偏空 + 1d 或 4h 有效跌破支撑 + 动能支持 + 假跌破风险不高 → bearish_breakdown；
大背景偏空 + 1d 未破 + 4h 反弹 + 靠近 1d 压力 → bearish_rebound；
大背景偏空 + 长期低位 + 区间有效 + 推进减弱 → bearish_low_range；
大背景偏空 + 靠近大支撑 + 4h 突破 + 空头动能衰竭 → bearish_bottom_reversal_candidate；
大背景不明确 + 结构区间有效 → neutral_range；
risk_state = risk_high_signal_unreliable → high_risk_environment；
risk_state = risk_unclear → unclear_environment；
risk_state = risk_elevated_classifiable → 普通分类仍可继续，但 evidence_text_zh 必须解释风险类别和风险方向；
候选分数不足或差距过小 → unclear_environment；
有效突破优先于同方向普通趋势延续，但不得覆盖 high_risk_environment；
有效跌破优先于同方向普通趋势延续，但不得覆盖 high_risk_environment；
突破后快速打回且 risk_state 指向高信号不可靠风险 → high_risk_environment 或 unclear_environment；
跌破后快速收回且 risk_state 指向高信号不可靠风险 → high_risk_environment 或 unclear_environment；
缺少任一 required 领域 → blocked / failed，不生成正常 Snapshot；
regime_scores 覆盖全部 allowed_regime_codes；
used_domain_signal_value_refs 只引用同一 DomainSignalSet 的 DomainSignalValue；
evidence_text_zh 能解释最终分类、主要竞争分类和 risk_state 对分类的影响。
```

## 16. 禁止项

禁止：

```text
让 MarketRegime 读取 FeatureValue；
让 MarketRegime 读取 AtomicSignalValue；
让 MarketRegime 读取 Kline；
让 MarketRegime 请求 Binance；
让 MarketRegime 读取账户、持仓、订单、成交或 PriceSnapshot；
让 MarketRegime 调用大模型；
让 MarketRegime 选择策略；
让 MarketRegime 生成 StrategySignal；
让 MarketRegime 生成 DecisionSnapshot；
让 MarketRegime 输出交易动作；
让 4h 小结构单独推翻 1d 大结构；
把多头高位震荡、空头低位震荡和无方向震荡混成同一种环境；
把 high_risk_environment、neutral_range、unclear_environment 混用；
把 regime_confidence 解释为盈利概率；
在 MarketRegimeService 中硬编码本算法 if / elif；
绕过 StrategyAnalysisRelease 直接启用本算法。
```

## 17. 最终定位

`context_structure_regime_v1` 的最终定位是：

```text
把六个领域已经确认的市场事实，
按大背景优先、风险优先、1d 主结构优先、4h 早期变化辅助的规则，
分类为可解释的市场环境，
为 StrategyRouting 提供上下文，
但不替代策略选择、策略判断或交易决策。
```
