# Market Context Domain Signals

## 1. 文件定位

本文档定义 `market_context` 领域的第一版领域聚合规则。

它消费 [Market Context Atomic Signals](../atomic_signals/market_context_atomic_signals.md) 产生的 AtomicSignalValue，生成一份 market_context DomainSignalValue。

本文档回答：

```text
一组 market_context 原子信号合起来，长期大背景偏多、偏空还是中性；
当前是否同时具有高位、低位、回撤、反弹、收复等长期背景状态；
领域结论用了哪些原子信号；
领域结论为什么成立；
人工如何复核该领域判断是否跑偏。
```

本文档不负责：

```text
识别完整 MarketRegime；
判断牛市回调；
判断熊市反弹；
判断高位宽幅震荡；
判断低位筑底；
判断趋势中继；
选择策略；
生成 StrategySignal；
生成 DecisionSnapshot；
读取 FeatureValue；
读取 Kline；
读取 MarketSnapshot 原始行情；
读取账户、持仓、订单或成交；
请求 Binance；
执行真实交易。
```

## 2. 输入边界

Market Context DomainSignal 只能读取同一 AtomicSignalSet 中、归属于 `market_context` 领域、且被当前 StrategyAnalysisRelease 选中的 AtomicSignalValue。

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
账户、持仓、订单或成交；
Binance；
DeepSeek。
```

DomainSignal 是原子信号用户，不是特征用户。

如果需要新的原子证据，必须先修改 AtomicSignal requirements；如果需要新的基础数值，必须先修改 FeatureLayer requirements。

## 3. 输出模式

本版本 `market_context` 使用 directional 输出模式：

```text
direction = bullish / bearish / neutral；
state_code = 用于表达长期背景附加状态；
strength = 领域方向明显程度；
coverage_ratio = 已获得的有效原子证据覆盖程度；
agreement_ratio = 多空方向性原子证据的一致程度。
```

`market_context` 领域只输出一份 DomainSignalValue。

不得为同一轮行情分别输出“偏多领域值”和“偏空领域值”。

## 4. 原子信号分组

### 4.1 偏多证据

以下原子信号成立时，计入偏多证据：

```text
market_context_price_above_sma_1d_200
market_context_price_above_sma_1d_365
market_context_sma_1d_200_rising
market_context_sma_1d_365_rising
market_context_positive_365d_return
```

### 4.2 偏空证据

以下原子信号成立时，计入偏空证据：

```text
market_context_price_below_sma_1d_200
market_context_price_below_sma_1d_365
market_context_sma_1d_200_falling
market_context_sma_1d_365_falling
market_context_negative_365d_return
market_context_deep_drawdown_from_365d_high
```

### 4.3 状态证据

以下原子信号成立时，只计入状态标签，不直接改变方向票数：

```text
market_context_in_365d_high_zone
market_context_in_365d_low_zone
market_context_moderate_drawdown_from_365d_high
market_context_material_rebound_from_drawdown_low
market_context_high_recovery_from_drawdown
market_context_low_recovery_from_drawdown
```

状态证据只描述长期背景状态。

例如：

```text
长期高位；
长期低位；
中等回撤；
明显反弹；
高收复；
低收复。
```

状态证据不得直接变成牛市回调、熊市反弹或策略动作。

## 5. 参数

本版本使用以下固定参数：

| 参数 | 值 | 说明 |
|---|---:|---|
| 最小覆盖率 | 0.70 | 至少 70% 被选中原子信号有效，领域才可用 |
| 最小方向差 | 2 | 多空方向性证据数量差至少为 2，才输出偏多或偏空 |
| 强方向差 | 4 | 多空方向性证据数量差达到 4，认为方向非常明显 |
| 中性 state_code | `balanced` | 方向差不足时使用 |
| 混合 state_code | `mixed_context` | 多空证据都存在但差距不足时使用 |

这些参数属于本算法版本的一部分。

后续如果调整方向差、覆盖率或状态映射，必须新增算法版本。

## 6. 计算流程

### 6.1 收集输入

从同一 AtomicSignalSet 中读取当前版本包选择的 market_context 原子信号。

只允许使用：

```text
status = created；
is_valid = true；
definition_status = active；
definition_enabled = true。
```

failed 或 invalid 原子信号不参与方向和状态计算，但必须计入 coverage_ratio。

### 6.2 计算 coverage_ratio

```text
coverage_ratio = 有效 market_context 原子信号数量 / 当前版本包选择的 market_context 原子信号数量
```

如果被选中的 market_context 原子信号数量为 0，领域计算失败。

如果 `coverage_ratio < 0.70`：

```text
DomainSignalValue.status = failed
is_valid = false
direction = none
state_code = ""
strength = 0
error_code = market_context_coverage_too_low
```

### 6.3 计算多空证据数量

只统计有效且条件成立的方向性原子信号。

```text
bullish_count = 成立的偏多证据数量
bearish_count = 成立的偏空证据数量
directional_total = bullish_count + bearish_count
direction_gap = abs(bullish_count - bearish_count)
```

如果 `directional_total = 0`：

```text
direction = neutral
state_code = balanced
agreement_ratio = 0
strength = 0
```

### 6.4 计算 direction

如果：

```text
bullish_count - bearish_count >= 2
```

则：

```text
direction = bullish
```

如果：

```text
bearish_count - bullish_count >= 2
```

则：

```text
direction = bearish
```

否则：

```text
direction = neutral
```

### 6.5 计算 state_code

`state_code` 由方向和状态证据共同形成，但不得表达完整 MarketRegime。

基础 state_code：

| 条件 | state_code |
|---|---|
| direction = bullish 且未出现特殊状态 | `long_term_bullish` |
| direction = bearish 且未出现特殊状态 | `long_term_bearish` |
| direction = neutral 且多空证据都存在 | `mixed_context` |
| direction = neutral 且无明显方向证据 | `balanced` |

状态标签必须同时写入 `payload_summary.state_tags`。

允许的 `state_tags`：

```text
high_zone
low_zone
moderate_drawdown
deep_drawdown
material_rebound
high_recovery
low_recovery
```

如果存在状态标签，`state_code` 可以使用以下组合值：

| 条件 | state_code |
|---|---|
| direction = bullish 且 moderate_drawdown 成立 | `bullish_with_moderate_drawdown` |
| direction = bullish 且 high_zone 成立 | `bullish_high_zone` |
| direction = bullish 且 material_rebound 成立 | `bullish_with_rebound` |
| direction = bearish 且 material_rebound 成立 | `bearish_with_rebound` |
| direction = bearish 且 low_zone 成立 | `bearish_low_zone` |
| direction = bearish 且 deep_drawdown 成立 | `bearish_deep_drawdown` |
| direction = neutral 且 high_zone 成立 | `neutral_high_zone` |
| direction = neutral 且 low_zone 成立 | `neutral_low_zone` |

如果多个状态同时成立，`state_code` 只能选择一个主状态，其他状态进入 `payload_summary.state_tags`。

主状态优先级：

```text
deep_drawdown
moderate_drawdown
material_rebound
high_recovery
low_recovery
high_zone
low_zone
```

### 6.6 计算 strength

本版本 strength 表示 market_context 领域方向明显程度。

如果 direction = bullish 或 bearish：

```text
strength = min(1, direction_gap / 4)
```

如果 direction = neutral：

```text
strength = 0
```

strength 不代表盈利概率，不代表仓位比例。

### 6.7 计算 agreement_ratio

如果 `directional_total > 0`：

```text
agreement_ratio = max(bullish_count, bearish_count) / directional_total
```

如果 `directional_total = 0`：

```text
agreement_ratio = 0
```

agreement_ratio 只表示方向性证据一致程度，不表示策略置信度。

## 7. 证据输出

DomainSignalValue 必须输出：

```text
used_atomic_signal_codes；
used_atomic_signal_value_ids；
evidence_items；
evidence_text_zh；
payload_summary。
```

### 7.1 evidence_items

`evidence_items` 至少包含：

```json
{
  "evidence_type": "market_context_domain_aggregation",
  "bullish_count": 4,
  "bearish_count": 1,
  "direction_gap": 3,
  "coverage_ratio": "1",
  "agreement_ratio": "0.8",
  "direction": "bullish",
  "state_code": "bullish_with_moderate_drawdown",
  "state_tags": ["moderate_drawdown", "material_rebound"],
  "used_atomic_signal_value_ids": [101, 102, 103, 104, 105]
}
```

不得在 evidence_items 中复制完整 AtomicSignalValue、完整 FeatureValue 或完整 K 线窗口。

### 7.2 evidence_text_zh

`evidence_text_zh` 必须能让人工快速判断领域结论是否跑偏。

示例：

```text
market_context 长期背景偏多：偏多证据 4 项，偏空证据 1 项，方向差 3；同时出现中等回撤和明显反弹状态。
```

如果方向中性：

```text
market_context 长期背景中性：偏多证据 2 项，偏空证据 1 项，方向差不足 2；当前处于长期高位状态。
```

如果失败：

```text
market_context 领域计算失败：有效原子证据覆盖率 0.58，低于最低要求 0.70。
```

不得写交易建议。

## 8. payload_summary

`payload_summary` 至少包含：

```json
{
  "bullish_count": 4,
  "bearish_count": 1,
  "direction_gap": 3,
  "directional_total": 5,
  "state_tags": ["moderate_drawdown", "material_rebound"],
  "failed_atomic_count": 0,
  "valid_atomic_count": 12,
  "selected_atomic_count": 12
}
```

`payload_summary` 是摘要，不得复制完整证据链。

完整追溯必须通过 `used_atomic_signal_value_ids` 回查 AtomicSignalValue，再通过 `used_feature_value_ids` 回查 FeatureValue。

## 9. 与 MarketRegime 的边界

Market Context DomainSignal 可以输出：

```text
long_term_bullish；
long_term_bearish；
balanced；
mixed_context；
bullish_with_moderate_drawdown；
bearish_with_rebound；
neutral_high_zone。
```

但不得输出：

```text
大级别上涨延续；
大级别下跌延续；
牛市回调；
熊市反弹；
高位宽幅震荡；
低位筑底；
趋势中继整理；
支撑或压力位置下的策略处理；
任何交易动作判断。
```

这些必须由 MarketRegime 或更下游模块在自身边界内完成。

## 10. 人工复核视角

后台或复盘展示 market_context 领域结果时，应至少展示：

```text
领域方向；
领域状态；
偏多证据数量；
偏空证据数量；
方向差；
覆盖率；
一致性；
状态标签；
中文解释；
使用的原子信号列表。
```

人工应能从这些信息判断：

```text
系统是否把长期大背景看偏多、偏空或中性；
系统是否注意到了高位、低位、回撤、反弹等状态；
系统是否因为证据不足而失败；
系统是否出现多空证据严重冲突。
```

## 11. 验收规则

### 11.1 明确偏多背景

如果以下原子信号成立：

```text
market_context_price_above_sma_1d_200
market_context_price_above_sma_1d_365
market_context_sma_1d_200_rising
market_context_sma_1d_365_rising
market_context_positive_365d_return
```

且偏空证据不足 2 项，则：

```text
direction = bullish
strength > 0
state_code 以 bullish 为主
```

### 11.2 明确偏空背景

如果以下原子信号成立：

```text
market_context_price_below_sma_1d_200
market_context_price_below_sma_1d_365
market_context_sma_1d_200_falling
market_context_sma_1d_365_falling
market_context_negative_365d_return
```

且偏多证据不足 2 项，则：

```text
direction = bearish
strength > 0
state_code 以 bearish 为主
```

### 11.3 多空证据混合

如果偏多证据 2 项、偏空证据 1 项：

```text
direction = neutral
state_code = mixed_context 或带状态的 neutral_*
strength = 0
```

原因是方向差不足 2。

### 11.4 偏多但回撤

如果长期偏多证据明显占优，同时 `market_context_moderate_drawdown_from_365d_high` 成立：

```text
direction = bullish
state_code = bullish_with_moderate_drawdown
payload_summary.state_tags 包含 moderate_drawdown
```

但不得输出“牛市回调”。

### 11.5 偏空但反弹

如果长期偏空证据明显占优，同时 `market_context_material_rebound_from_drawdown_low` 成立：

```text
direction = bearish
state_code = bearish_with_rebound
payload_summary.state_tags 包含 material_rebound
```

但不得输出“熊市反弹”。

### 11.6 覆盖率不足

如果有效 market_context 原子信号覆盖率低于 0.70：

```text
DomainSignalValue.status = failed
is_valid = false
direction = none
strength = 0
error_code = market_context_coverage_too_low
```

不得生成可被 MarketRegime 消费的有效领域值。

## 12. 本版本明确不处理

本版本不处理：

```text
加权原子证据；
概率置信度；
机器学习分类；
历史状态平滑；
连续多周期确认；
周线背景；
宏观背景；
链上背景；
多币种强弱；
成交量背景。
```

这些能力如需加入，必须新增算法需求文件或新增算法版本。
