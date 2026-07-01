# P0 趋势类 StrategySignal calculator 实现记录

## 实现范围

本实现记录覆盖四个 P0 策略信号 calculator：

```text
long_trend_following / v1
long_pullback_support / v1
short_trend_following / v1
short_rebound_pressure / v1
```

它们只消费 StrategySignalService 传入的六个 DomainSignalValue 标准字段：

```text
market_context
trend
momentum
volatility
structure
risk_state
```

calculator 不读取 FeatureValue、AtomicSignalValue、MarketRegimeSnapshot 细节、账户、持仓、价格快照、订单、成交或风控结果。

## 共同输入

每个 calculator 必须确认：

```text
strategy_code / strategy_version 与 StrategyDefinition 一致；
prediction_horizon = next_1_to_3_closed_4h；
六个必需领域事实齐全；
领域事实只作为市场事实使用，不被解释为订单动作。
```

## 共同输出

每个 calculator 输出：

```text
direction = bullish / bearish / neutral；
strength = 0 到 1；
confidence = 0 到 1；
confidence_semantics = domain_fact_strategy_score；
prediction_horizon = next_1_to_3_closed_4h；
trade_price_condition；
aggregation_snapshot；
conflict_snapshot；
evidence_text_zh。
```

`aggregation_snapshot` 必须包含：

```text
final_direction；
final_strength；
final_confidence。
```

这些字段用于 StrategySignalQuality 在下游放行前核对策略主字段是否被完整冻结，不用于重新计算策略。

`trade_price_condition` 只表达合理价格区域、是否不追价和结构引用，不表达订单类型、限价价格、数量、有效期或交易所参数。

## 评分逻辑

四个策略统一使用五个组件分：

```text
context_score
trend_score
momentum_score
structure_score
volatility_score
```

基础强度：

```text
raw_strength =
  0.25 * context_score
  + 0.25 * trend_score
  + 0.20 * momentum_score
  + 0.20 * structure_score
  + 0.10 * volatility_score
```

最终强度：

```text
strength = clamp(raw_strength * risk_multiplier, 0, 1)
```

风险折减：

```text
risk_clear → 1.00
risk_elevated_classifiable → 0.75
risk_high_signal_unreliable / risk_unclear → 0.00
```

置信度由组件平均分、最低组件分、风险折减、警告和硬冲突共同形成。硬冲突、强度低于 0.55 或置信度低于 0.55 时，输出 `neutral`。

## 四个策略差异

### long_trend_following / v1

用于多头趋势延续或有效向上突破。

关键支持：

```text
market_context 偏多；
trend 偏多；
momentum 偏多或未明显衰竭；
structure 向上突破或未跌破关键支撑；
risk_state 未显示高风险。
```

关键冲突：

```text
market_context 偏空；
trend 偏空；
structure 显示关键支撑跌破。
```

### long_pullback_support / v1

用于大背景偏多下的回调支撑或高位区间支撑侧。

关键支持：

```text
market_context 偏多；
trend 仍偏多，允许 4h 回调；
structure 靠近支撑且未跌破；
momentum 下跌动能不失控，或回调动能衰竭；
risk_state 未显示高风险。
```

关键冲突：

```text
market_context 偏空；
trend 已偏空；
structure 显示支撑跌破。
```

### short_trend_following / v1

用于空头趋势延续或有效向下跌破。

关键支持：

```text
market_context 偏空；
trend 偏空；
momentum 偏空或未明显衰竭；
structure 向下跌破或压力未修复；
risk_state 未显示高风险。
```

关键冲突：

```text
market_context 偏多；
trend 偏多；
structure 显示关键压力向上突破。
```

### short_rebound_pressure / v1

用于大背景偏空下的反弹压力或低位区间压力侧。

关键支持：

```text
market_context 偏空；
trend 仍偏空，允许 4h 反弹；
structure 靠近压力且未突破；
momentum 上涨动能不失控，或反弹动能衰竭；
risk_state 未显示高风险。
```

关键冲突：

```text
market_context 偏多；
trend 已偏多；
structure 显示压力向上突破。
```

## structure conflicted handling

P0 trend-following calculators distinguish major and minor structure conflicts:

```text
major_structure conflicted:
  means the 1d primary structure is unclear;
  long_trend_following / short_trend_following add a blocker;
  final direction is neutral, and no new trend-following signal is emitted.

minor_structure conflicted:
  means the 4h structure has overlapping support / resistance or breakout / pullback facts;
  it does not directly invalidate the 1d primary trend;
  long_trend_following / short_trend_following add a warning;
  structure_score is reduced and confidence is discounted by the warning;
  long_trend_following changes trade_price_condition to wait for support / pullback zones;
  short_trend_following changes trade_price_condition to wait for resistance / rebound zones.
```

This logic does not generate order actions and does not read account or price facts. It only changes StrategySignal explanation, scores, confidence, and price conditions.

## 明确不做

本实现不做：

```text
重新识别市场环境；
重新计算支撑压力价格；
生成目标仓位；
生成订单；
生成止损止盈订单；
调用 Binance；
访问 Redis；
发送 Hermes；
调用大模型；
参与真实交易执行。
```
## structure 区间承接补充说明

P0 趋势类策略 calculator 只消费 StrategySignalService 传入的 DomainSignalValue 标准事实。

当 `structure` 领域的 `payload_summary` 中存在结构化区间时：

```text
support_zone = {"lower": "...", "upper": "..."}
resistance_zone = {"lower": "...", "upper": "..."}
```

策略会把对应区间写入 `trade_price_condition.acceptable_price_zone`：

```text
默认情况下：
  long_trend_following / short_rebound_pressure 读取 resistance_zone；
  long_pullback_support / short_trend_following 读取 support_zone。

minor_structure conflicted 时：
  long_trend_following 改为读取 support_zone，表示不追多、等待回踩；
  short_trend_following 改为读取 resistance_zone，表示不追空、等待反弹。
```

如果结构领域没有给出可用区间，策略保留原有文字型价格条件，不自行回算支撑压力。

该字段仍然只表达“合理价格区域”，不表达订单类型、限价价格、数量、有效期或交易所参数；这些由 DecisionSnapshot 冻结后交给 OrderPlan 解释。
