# context_structure_regime / v1 实现记录

## 1. 定位

`context_structure_regime / v1` 是 MarketRegime 的第一版正式市场环境分类算法。

它只消费已落库的六个领域事实：

```text
market_context
trend
momentum
volatility
structure
risk_state
```

它不读取 FeatureValue、AtomicSignalValue、K 线、账户、订单、成交或价格事实，不访问 Binance，不调用大模型，不选择策略，不生成目标仓位，不生成订单动作。

## 2. 输入

输入由 MarketRegimeService 构造：

```text
DomainSignalSet
→ 六个 DomainSignalValue
→ MarketRegimeDefinition 冻结的 allowed / required domain
→ MarketRegimeDefinition 冻结的 allowed_regime_codes
```

本算法要求 `allowed_regime_codes` 完整等于需求文档中登记的 13 个环境类型。

## 3. 输出

输出包括：

```text
regime_code
regime_scores
regime_confidence
classification_margin
used_domain_signal_value_ids
evidence_text_zh
evidence_items
```

`regime_scores` 必须覆盖全部 13 个 `allowed_regime_codes`。

## 4. 分类规则

第一优先级是风险事实：

```text
risk_high_signal_unreliable → high_risk_environment
risk_unclear → unclear_environment
```

在风险没有阻断普通分类时，算法同时为普通候选环境打分：

```text
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

评分由大背景、趋势、动能、波动、结构和风险清晰度共同贡献。

如果最高候选分数不足，或最高候选与第二候选差距过小，算法输出 `unclear_environment`。

## 5. 震荡区分

算法不会把所有震荡都合并成一种环境：

```text
大背景偏多 + 高位/压力区/推进减弱 → bullish_high_range
大背景偏空 + 低位/支撑区/推进减弱 → bearish_low_range
大背景不明确 + 区间有效 → neutral_range
```

## 6. 突破与跌破

突破和跌破由 structure 领域提供事实，MarketRegime 只做环境分类。

```text
有效向上突破环境 → bullish_breakout
有效向下跌破环境 → bearish_breakdown
```

是否开仓、挂限价单或等待，由后续 StrategyRouting / StrategySignal / OrderPlan 决定。

## 7. 证据

`evidence_text_zh` 必须说明：

```text
最终环境类型；
六个领域的核心状态；
选择该环境的主要原因；
主要竞争候选；
risk_state 对分类的影响；
该结论不产生交易动作。
```
