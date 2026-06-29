# grouped_atomic_aggregation 1.0.0 实现说明

## 定位

`grouped_atomic_aggregation 1.0.0` 是 DomainSignal calculator。

它把同一领域内的一组 `AtomicSignalValue` 按固定分组聚合为一条 `DomainSignalValue`。

它只做市场事实聚合，不做策略、不做仓位、不做订单。

## 输入

calculator 接收：

```text
domain_code；
output_mode；
atomic_values；
DomainSignalDefinition.params。
```

`atomic_values` 必须来自当前 DomainSignalDefinition 允许读取的原子信号集合。

该 calculator 不读取数据库，不读取 FeatureValue，不访问 Binance。

## 条件成立的判断

原子信号满足以下任一条件，才被视为“成立”：

```text
value_bool = true；
或 value_json.condition_met = true。
```

无效、失败或条件不成立的原子信号不参与分组计数，但会通过 service 计入 coverage 分母。

## 六个领域的聚合口径

### market_context

聚合长期偏多 / 偏空证据。

输出方向来自偏多与偏空证据数量差。

状态标签承载：

```text
高位；
低位；
中等回撤；
深度回撤；
明显修复；
高修复；
低修复。
```

### trend

以 1d 为主趋势，4h 只作为辅助状态。

输出方向只由 1d 主趋势决定。

典型状态：

```text
1d 偏多 + 4h 偏多；
1d 偏多 + 4h 回调；
1d 偏空 + 4h 偏空；
1d 偏空 + 4h 反弹；
趋势不明确。
```

### momentum

以 1d 推动力为主，4h 只作为辅助状态。

输出方向只由 1d 动能方向决定。

状态描述推动力处于增强、衰竭、拉扯或不明确。

### volatility

输出非方向性状态。

典型状态：

```text
volatility_low；
volatility_low_compression；
volatility_normal；
volatility_high；
volatility_extreme；
volatility_mixed。
```

该领域不输出多空方向。

### structure

聚合 1d 大结构与 4h 小结构。

1d 大结构决定结构领域方向：

```text
大结构突破 → bullish；
大结构跌破 → bearish；
其他情况 → neutral。
```

4h 小结构只进入状态解释，不单独推翻 1d 大结构。

### risk_state

输出非方向性风险状态。

典型状态：

```text
risk_clear；
risk_elevated_classifiable；
risk_high_signal_unreliable；
risk_unclear。
```

`risk_state` 不等于“停止交易”，也不等于“减仓”。它只说明市场风险事实。

## 输出

calculator 输出：

```text
direction；
state_code；
strength；
coverage_ratio；
agreement_ratio；
evidence_items；
evidence_text_zh。
```

`evidence_items` 会记录：

```text
领域代码；
领域类型；
成立的原子信号；
分组计数；
状态标签；
摘要信息。
```

## 不负责事项

```text
不读取数据库；
不读取 Redis；
不访问 Binance；
不访问 DeepSeek；
不发送 Hermes；
不生成 MarketRegime；
不选择策略；
不生成 StrategySignal；
不生成目标仓位；
不生成订单；
不执行真实交易。
```
## structure 区间摘要补充说明

`structure` 领域仍然只聚合结构事实，不生成交易动作。

当结构类原子信号的 JSON 输出携带 `feature_values` 时，`grouped_atomic_aggregation` 会从其中整理出：

```text
major_support_zone
major_resistance_zone
minor_support_zone
minor_resistance_zone
support_zone
resistance_zone
current_zone_position
```

其中：

```text
major_* 来自 1d 大结构；
minor_* 来自 4h 小结构；
support_zone / resistance_zone 是给下游策略读取的默认结构区间；
current_zone_position 只表达价格当前处于哪类结构位置。
```

该摘要写入 DomainSignalValue 的 evidence summary，供 StrategySignal 读取。它不代表“支撑做多”“压力做空”等操作建议。
