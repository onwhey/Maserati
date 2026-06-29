# Risk State Domain Signals

## 1. 文件定位

本文档定义 `risk_state` 领域的第一版领域聚合规则。

它消费 [Risk State Atomic Signals](../atomic_signals/risk_state_atomic_signals.md) 产生的 AtomicSignalValue，生成一份 `risk_state` DomainSignalValue。

本文档回答：

```text
一组 risk_state 原子信号合起来，当前市场风险状态是清晰、升高但可分类、高信号不可靠风险，还是风险不明确；
当前风险主要属于信号可靠性风险、方向暴露风险、追单风险，还是市场扰动风险；
为什么单根大跌 / 大涨不等于一律不操作；
MarketRegime 应如何消费 risk_state；
人工如何复核风险判断是否跑偏。
```

本文档不负责：

```text
读取 FeatureValue；
读取 Kline；
重新计算 AtomicSignal；
读取账户、持仓、订单或成交；
判断当前系统是否真的持有多仓或空仓；
决定仓位如何变化、是否形成交易目标或是否执行交易动作；
选择策略；
生成 StrategySignal；
生成 DecisionSnapshot；
读取 PriceSnapshot；
请求 Binance；
执行真实交易；
调用大模型。
```

## 2. 输入边界

Risk State DomainSignal 只能读取同一 AtomicSignalSet 中、归属于 `risk_state` 领域、且被当前 StrategyAnalysisRelease 选中的 AtomicSignalValue。

不得读取：

```text
FeatureValue；
Kline；
MarketSnapshot 原始行情；
其他领域的 AtomicSignalValue；
其他 DomainSignalValue；
MarketRegimeSnapshot；
StrategyRouteDecision；
StrategySignal；
DecisionSnapshot；
账户、持仓、订单或成交；
PriceSnapshot；
Binance；
DeepSeek。
```

DomainSignal 是原子信号用户，不是特征用户。

## 3. 输出模式

本版本 `risk_state` 使用非方向性风险状态输出模式：

```text
direction = neutral；
state_code = risk_clear / risk_elevated_classifiable / risk_high_signal_unreliable / risk_unclear；
strength = 风险状态强烈程度；
coverage_ratio = 已获得的有效原子证据覆盖程度；
agreement_ratio = 0；
payload_summary = 风险类型、风险方向、严重度和复核摘要。
```

risk_state 领域只输出一份 DomainSignalValue。

不得为同一轮行情分别输出“多头风险领域值”和“空头风险领域值”。

`direction = neutral` 的含义是：

```text
risk_state 不表达市场涨跌方向；
risk_state 不表达交易方向；
risk_state 不表达目标仓位方向。
```

## 4. state_code 语义

### 4.1 risk_clear

含义：

```text
没有明显异常市场风险；
没有高严重度风险原子信号成立；
普通策略分析可以继续消费其它领域事实。
```

它不表示策略一定形成交易目标。

### 4.2 risk_elevated_classifiable

含义：

```text
市场风险升高；
但风险类型、方向和证据相对清楚；
MarketRegime 仍可以形成普通市场环境；
StrategySignal 后续应能看到风险类型。
```

典型场景：

```text
4h 实体大跌且收盘靠近低点，趋势和结构也偏空；
这可能是有效下跌冲击，也可能对多头暴露不友好；
但不一定是脏行情，也不一定必须 risk_high_signal_unreliable。
```

### 4.3 risk_high_signal_unreliable

含义：

```text
风险已经高到普通市场环境分类可靠性显著下降；
MarketRegime 应把它作为高风险环境证据；
后续是否选择策略、降低信号质量或不形成交易目标，由 StrategyRouting / StrategySignal / StrategySignalQuality / DecisionSnapshot 决定。
```

典型场景：

```text
向上突破后快速打回；
向下跌破后快速收回；
极高波动伴随长上下影双向扫动；
连续极端波动导致普通趋势 / 结构信号明显失真。
```

它仍然不表示“系统立刻不操作”。如果系统已有持仓，后续策略和目标仓位决策仍必须处理风险暴露。

### 4.4 risk_unclear

含义：

```text
风险证据互相冲突；
无法可靠判断风险是可分类冲击，还是脏行情；
MarketRegime 应把它作为不明确环境证据。
```

## 5. 原子风险分组

### 5.1 信号可靠性风险

以下类别计入信号可靠性风险：

```text
signal_reliability_risk；
false_breakout_risk；
false_breakdown_risk；
market_disorder_risk。
```

这些风险主要影响：

```text
突破是否可信；
跌破是否可信；
趋势 / 结构信号是否可能失真；
MarketRegime 是否应形成高风险环境或不明确环境。
```

### 5.2 方向暴露风险

以下类别计入方向暴露风险：

```text
long_exposure_risk；
short_exposure_risk。
```

这些风险是条件性风险：

```text
long_exposure_risk = 如果有多头方向暴露，该行情不友好；
short_exposure_risk = 如果有空头方向暴露，该行情不友好。
```

risk_state 不读取账户，因此不得判断系统当前是否真的有该方向仓位。

### 5.3 追单风险

以下类别计入追单风险：

```text
long_chase_risk；
short_chase_risk。
```

这些风险说明：

```text
行情已经发生快速冲击；
当前位置继续追同方向可能面临回撤或假突破风险；
但它不否定趋势方向。
```

## 6. 参数

本版本使用以下固定参数：

| 参数 | 值 | 说明 |
|---|---:|---|
| 最小覆盖率 | 0.70 | 至少 70% 被选中 risk_state 原子信号有效，领域才可用 |
| high 严重度权重 | 1.00 | high 原子风险计分 |
| elevated 严重度权重 | 0.55 | elevated 原子风险计分 |
| risk_clear 上限 | 0.20 | 总风险分不高于该值且无 high 风险时 risk_clear |
| elevated_classifiable 下限 | 0.20 | 总风险分超过该值但未达到高信号不可靠风险时 risk_elevated_classifiable |
| signal_unreliable 下限 | 0.70 | 信号可靠性风险或市场扰动风险达到该值时 risk_high_signal_unreliable |
| conflicting_unclear 下限 | 0.45 | 多类高风险冲突且无主导时 risk_unclear |

这些参数属于本算法版本。后续调整必须新增算法版本。

## 7. 计算流程

### 7.1 收集输入

从同一 AtomicSignalSet 中读取当前版本包选择的 risk_state 原子信号。

只允许使用：

```text
status = created；
is_valid = true；
definition_status = active；
definition_enabled = true。
```

failed 或 invalid 原子信号不参与风险计算，但必须计入 coverage_ratio。

### 7.2 计算 coverage_ratio

```text
coverage_ratio = 有效 risk_state 原子信号数量 / 当前版本包选择的 risk_state 原子信号数量
```

如果被选中的 risk_state 原子信号数量为 0，领域计算失败。

如果 `coverage_ratio < 0.70`：

```text
DomainSignalValue.status = failed
is_valid = false
direction = none
state_code = ""
error_code = risk_state_coverage_too_low
```

不得用 risk_clear 伪装缺失。

### 7.3 计算风险分

每个成立的原子信号按 severity 计分：

```text
none = 0
elevated = 0.55
high = 1.00
```

分别计算：

```text
signal_reliability_score；
long_exposure_score；
short_exposure_score；
long_chase_score；
short_chase_score；
market_disorder_score；
false_breakout_score；
false_breakdown_score。
```

每个分数按该类别成立原子信号的最高 severity 计，不重复叠加同类风险，避免同一市场事实被多次计分。

### 7.4 判断 risk_high_signal_unreliable

满足任一条件时输出 `risk_high_signal_unreliable`：

```text
false_breakout_score = 1.00；
false_breakdown_score = 1.00；
market_disorder_score = 1.00 且 signal_reliability_score >= 0.55；
signal_reliability_score = 1.00 且 long_exposure_score >= 0.55 且 short_exposure_score >= 0.55；
双向扫动风险 high。
```

解释：

```text
risk_high_signal_unreliable 针对的是普通信号可靠性显著下降；
不是因为单根大跌或大涨本身就阻断；
如果大跌方向清晰、结构和趋势一致，可以是 risk_elevated_classifiable。
```

### 7.5 判断 risk_unclear

满足任一条件时输出 `risk_unclear`：

```text
long_exposure_score >= 0.55 且 short_exposure_score >= 0.55，但 signal_reliability_score < 0.55；
long_chase_score >= 0.55 且 short_chase_score >= 0.55；
false_breakout_score >= 0.55 且 false_breakdown_score >= 0.55，但均未达到 risk_high_signal_unreliable；
多个风险类别均 elevated，但无法形成主导风险。
```

### 7.6 判断 risk_elevated_classifiable

满足任一条件时输出 `risk_elevated_classifiable`：

```text
long_exposure_score > 0.20；
short_exposure_score > 0.20；
long_chase_score > 0.20；
short_chase_score > 0.20；
signal_reliability_score > 0.20；
market_disorder_score > 0.20；
false_breakout_score > 0.20；
false_breakdown_score > 0.20。
```

且不满足 risk_high_signal_unreliable / risk_unclear。

典型解释：

```text
4h 实体大跌 8% 且收盘靠近低点：
long_exposure_risk 高；
short_chase_risk 高；
如果没有长下影快速收回、没有假跌破、没有双向扫动，
则 risk_state = risk_elevated_classifiable，而不是 risk_high_signal_unreliable。
```

### 7.7 判断 risk_clear

如果没有成立的 elevated / high 风险原子信号：

```text
state_code = risk_clear
strength = 0
```

## 8. 输出 payload_summary

payload_summary 至少包含：

```json
{
  "risk_state": "risk_elevated_classifiable",
  "dominant_risk_categories": ["long_exposure_risk", "short_chase_risk"],
  "risk_directions": ["downside"],
  "signal_reliability_score": "0.00",
  "long_exposure_score": "1.00",
  "short_exposure_score": "0.00",
  "long_chase_score": "0.00",
  "short_chase_score": "1.00",
  "false_breakout_score": "0.00",
  "false_breakdown_score": "0.00",
  "market_disorder_score": "0.55",
  "signal_unreliable_reason": null
}
```

字段含义：

```text
dominant_risk_categories = 本轮最主要风险类型；
risk_directions = 风险方向；
*_score = 各类风险分；
signal_unreliable_reason = 如果 state_code = risk_high_signal_unreliable，必须说明触发原因。
```

## 9. strength

```text
strength = max(所有风险类别分数)
```

如果 `state_code = risk_clear`：

```text
strength = 0
```

如果 `state_code = risk_high_signal_unreliable`：

```text
strength >= 0.70
```

strength 只表示风险状态强烈程度，不表示交易仓位、盈利概率或行情方向概率。

## 10. evidence_text_zh

必须输出中文解释。

示例：

```text
最新 4h 实体下跌幅度达到 8%，且收盘靠近低点，说明若存在多头方向暴露，行情对多头不友好；同时由于波动处于高分位，当前位置继续追空也存在追空风险。当前没有出现跌破后快速收回或双向扫动，因此归类为风险升高但仍可分类，而不是高信号不可靠风险。
```

高信号不可靠风险示例：

```text
最新 4h 向下跌破小结构支撑后快速收回，并伴随长下影和极高波动，跌破信号可靠性显著下降，因此归类为高信号不可靠风险。
```

## 11. 与 MarketRegime 的关系

MarketRegime 可以消费 risk_state：

```text
risk_clear → 普通环境分类可继续；
risk_elevated_classifiable → 普通环境分类可继续，但证据中必须保留风险类型、风险方向和主要风险分；
risk_high_signal_unreliable → MarketRegime 应把它作为高风险环境证据；
risk_unclear → MarketRegime 应把它作为不明确环境证据。
```

MarketRegime 不得用 volatility 临时代替 risk_state。

## 12. 与 StrategySignal / DecisionSnapshot 的关系

StrategySignal 可以把 risk_state 作为策略证据之一，但不得把 risk_state 直接翻译成目标仓位或订单动作。

例如：

```text
多头策略看到 long_exposure_risk 高，不应继续给出高强度多头判断；
空头策略看到 short_chase_risk 高，不应无脑追空；
区间策略看到 false_breakout_risk 高，应降低对突破信号的信任。
```

但 risk_state 自己不得输出：

```text
降低目标仓位；
目标仓位变化；
交易方向；
订单动作；
NO_TRADE；
NO_TARGET_CHANGE。
```

这些属于 StrategySignal、StrategySignalQuality 或 DecisionSnapshot 后续模块。

## 13. 验收要求

至少覆盖以下场景：

```text
无风险原子成立 → risk_clear；
4h 实体大跌 8%，无快速收回 → risk_elevated_classifiable，payload 包含 long_exposure_risk 和 short_chase_risk；
4h 实体大涨 8%，无快速回落 → risk_elevated_classifiable，payload 包含 short_exposure_risk 和 long_chase_risk；
向上突破后长上影打回 → risk_high_signal_unreliable 或 risk_elevated_classifiable，取决于 severity；
向下跌破后长下影收回 → risk_high_signal_unreliable 或 risk_elevated_classifiable，取决于 severity；
双向扫动且极高波动 → risk_high_signal_unreliable；
多类风险 elevated 但无主导 → risk_unclear；
coverage_ratio 低于 0.70 → failed，不输出 risk_clear；
strength 可复算；
payload_summary 保存风险类别分数；
evidence_text_zh 清楚说明为什么不是“风险高就不操作”。
```

## 14. 禁止项

禁止：

```text
读取账户或持仓；
读取订单或成交；
读取 PriceSnapshot；
请求 Binance；
调用大模型；
输出交易动作；
输出目标仓位；
把 risk_high_signal_unreliable 解释为立刻不形成交易目标；
把 risk_elevated_classifiable 解释为一定降低交易参与度；
把 long_exposure_risk 解释为系统当前一定有多仓；
把 short_exposure_risk 解释为系统当前一定有空仓；
用 volatility 的高波动状态直接替代 risk_state；
把单根大跌直接等同于 risk_high_signal_unreliable；
把单根大涨直接等同于 risk_high_signal_unreliable。
```

## 15. 最终定位

risk_state 的最终定位是：

```text
把市场异常、冲击、假突破、假跌破和追单风险等原子事实，
聚合为一份不读取账户、不生成交易动作的市场风险状态，
为 MarketRegime 和 StrategySignal 提供风险上下文，
但不替代账户风控、目标仓位决策或交易执行。
```
