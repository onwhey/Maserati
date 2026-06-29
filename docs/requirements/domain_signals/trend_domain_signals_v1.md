# Trend Domain Signals

## 1. 文件定位

本文档定义 `trend` 领域的第一版领域聚合规则。

它消费 [Trend Atomic Signals](../atomic_signals/trend_atomic_signals.md) 产生的 AtomicSignalValue，生成一份 trend DomainSignalValue。

本文档回答：

```text
1d 主趋势偏多、偏空还是不明确；
4h 短周期趋势状态偏多、偏空还是不明确；
1d 与 4h 是否同向；
当前是否表现为 1d 上行中的 4h 回调；
当前是否表现为 1d 下行中的 4h 反弹；
趋势领域结论用了哪些原子信号；
趋势领域结论为什么成立；
人工如何复核该领域判断是否跑偏。
```

本文档不负责：

```text
判断大级别牛市或熊市；
判断牛市回调或熊市反弹；
判断长期高位或低位；
判断支撑压力；
识别完整 MarketRegime；
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

Trend DomainSignal 只能读取同一 AtomicSignalSet 中、归属于 `trend` 领域、且被当前 StrategyAnalysisRelease 选中的 AtomicSignalValue。

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

如果需要新的趋势原子证据，必须先修改 AtomicSignal requirements；如果需要新的基础数值，必须先修改 FeatureLayer requirements。

## 3. 输出模式

本版本 `trend` 使用主周期优先的 directional 输出模式：

```text
direction = bullish / bearish / neutral；
state_code = 用于表达 1d 主方向与 4h 短周期趋势状态；
strength = 仅由 1d 主趋势证据决定的趋势明显程度；
coverage_ratio = 已获得的有效原子证据覆盖程度；
agreement_ratio = 仅由 1d 主趋势证据计算的一致程度。
```

`trend` 领域只输出一份 DomainSignalValue。

不得为同一轮行情分别输出“趋势偏多领域值”和“趋势偏空领域值”。

## 4. 周期优先级

当前 P0 只使用 1d 与 4h。

周期职责：

```text
1d = trend 主判断周期；
4h = trend 短周期趋势状态周期。
```

领域主方向由 1d 聚合结果决定。

4h 不得单独推翻 1d 主方向，只能表达短周期趋势状态：

```text
与 1d 同向；
与 1d 反向；
4h 不明确。
```

因此：

```text
1d 偏多 + 4h 偏空 = trend direction 仍为 bullish，state_code 表达 4h 回调；
1d 偏空 + 4h 偏多 = trend direction 仍为 bearish，state_code 表达 4h 反弹；
1d 不明确 + 4h 偏多或偏空 = trend direction 仍为 neutral。
```

这保证 4h 只作为短周期趋势状态事实，不把趋势领域降级成短线判断。

4h 不参与：

```text
trend direction；
trend strength；
trend agreement_ratio。
```

4h 只进入：

```text
state_code；
payload_summary；
evidence_text_zh。
```

当前不引入 3d。

如果未来需要 3d，必须先补齐 3d 的 DataCollection、MarketSnapshot、FeatureDefinition、AtomicSignalDefinition 和对应 DomainSignal 算法版本。

## 5. 原子信号分组

### 5.1 1d 偏多证据

以下原子信号成立时，计入 1d 偏多证据：

```text
trend_1d_ma_bullish_alignment
trend_1d_slow_slope_rising
trend_1d_price_above_medium_ma
trend_1d_block_structure_rising
```

### 5.2 1d 偏空证据

以下原子信号成立时，计入 1d 偏空证据：

```text
trend_1d_ma_bearish_alignment
trend_1d_slow_slope_falling
trend_1d_price_below_medium_ma
trend_1d_block_structure_falling
```

### 5.3 4h 偏多证据

以下原子信号成立时，计入 4h 偏多证据：

```text
trend_4h_ma_bullish_alignment
trend_4h_medium_slope_rising
trend_4h_price_above_medium_ma
trend_4h_block_structure_rising
```

### 5.4 4h 偏空证据

以下原子信号成立时，计入 4h 偏空证据：

```text
trend_4h_ma_bearish_alignment
trend_4h_medium_slope_falling
trend_4h_price_below_medium_ma
trend_4h_block_structure_falling
```

## 6. 参数

本版本使用以下固定参数：

| 参数 | 值 | 说明 |
|---|---:|---|
| 最小覆盖率 | 0.70 | 至少 70% 被选中 trend 原子信号有效，领域才可用 |
| 1d 最小方向差 | 2 | 1d 多空证据数量差至少为 2，才形成主方向 |
| 4h 最小方向差 | 2 | 4h 多空证据数量差至少为 2，才形成短周期趋势状态 |
| 1d 强方向差 | 4 | 1d 多空证据数量差达到 4，认为主方向非常明显 |

这些参数属于本算法版本的一部分。

后续如果调整方向差、覆盖率、强度计算或状态映射，必须新增算法版本。

## 7. 计算流程

### 7.1 收集输入

从同一 AtomicSignalSet 中读取当前版本包选择的 trend 原子信号。

只允许使用：

```text
status = created；
is_valid = true；
definition_status = active；
definition_enabled = true。
```

failed 或 invalid 原子信号不参与方向计算，但必须计入 coverage_ratio。

### 7.2 计算 coverage_ratio

```text
coverage_ratio = 有效 trend 原子信号数量 / 当前版本包选择的 trend 原子信号数量
```

如果被选中的 trend 原子信号数量为 0，领域计算失败。

如果 `coverage_ratio < 0.70`：

```text
DomainSignalValue.status = failed
is_valid = false
direction = none
state_code = ""
strength = 0
error_code = trend_coverage_too_low
```

### 7.3 计算 1d 方向

只统计有效且条件成立的 1d 趋势原子信号。

```text
primary_bullish_count = 成立的 1d 偏多证据数量
primary_bearish_count = 成立的 1d 偏空证据数量
primary_direction_gap = abs(primary_bullish_count - primary_bearish_count)
```

如果：

```text
primary_bullish_count - primary_bearish_count >= 2
```

则：

```text
primary_direction = bullish
```

如果：

```text
primary_bearish_count - primary_bullish_count >= 2
```

则：

```text
primary_direction = bearish
```

否则：

```text
primary_direction = neutral
```

### 7.4 计算 4h 短周期趋势状态

只统计有效且条件成立的 4h 趋势原子信号。

```text
auxiliary_bullish_count = 成立的 4h 偏多证据数量
auxiliary_bearish_count = 成立的 4h 偏空证据数量
short_cycle_direction_gap = abs(auxiliary_bullish_count - auxiliary_bearish_count)
```

如果：

```text
auxiliary_bullish_count - auxiliary_bearish_count >= 2
```

则：

```text
short_cycle_direction = bullish
```

如果：

```text
auxiliary_bearish_count - auxiliary_bullish_count >= 2
```

则：

```text
short_cycle_direction = bearish
```

否则：

```text
short_cycle_direction = neutral
```

### 7.5 计算领域 direction

领域主方向只由 1d 主方向决定。

| primary_direction | direction |
|---|---|
| bullish | bullish |
| bearish | bearish |
| neutral | neutral |

如果 primary_direction = neutral，即使 short_cycle_direction 为 bullish 或 bearish，领域 direction 也必须为 neutral。

### 7.6 计算 state_code

`state_code` 由 primary_direction 和 short_cycle_direction 共同形成。

| primary_direction | short_cycle_direction | state_code |
|---|---|---|
| bullish | bullish | `trend_1d_bullish_4h_aligned` |
| bullish | bearish | `trend_1d_bullish_4h_pullback` |
| bullish | neutral | `trend_1d_bullish_4h_unclear` |
| bearish | bearish | `trend_1d_bearish_4h_aligned` |
| bearish | bullish | `trend_1d_bearish_4h_rebound` |
| bearish | neutral | `trend_1d_bearish_4h_unclear` |
| neutral | bullish | `trend_1d_neutral_4h_bullish` |
| neutral | bearish | `trend_1d_neutral_4h_bearish` |
| neutral | neutral | `trend_unclear` |

这些 state_code 只表达 trend 领域事实。

不得把：

```text
trend_1d_bullish_4h_pullback
```

解释成牛市回调、支撑位置策略处理或仓位动作。

不得把：

```text
trend_1d_bearish_4h_rebound
```

解释成熊市反弹、压力位置策略处理或仓位动作。

完整市场环境必须由 MarketRegime 综合 market_context、trend、momentum、volatility、structure 和 risk_state 后形成。

### 7.7 计算 strength

本版本 strength 表示 1d 主趋势方向明显程度。

如果 direction = bullish 或 bearish：

```text
strength = min(1, primary_direction_gap / 4)
```

如果 direction = neutral：

```text
strength = 0
```

strength 不代表盈利概率，不代表仓位比例，不代表交易规模。

4h 短周期趋势状态不得给 strength 加分或扣分。

原因：

```text
4h 的职责是判断完整短周期趋势状态；
不是趋势主方向裁判；
不能把正常短周期回调误写成趋势变弱；
也不能把短周期顺行误写成趋势变强。
```

### 7.8 计算 agreement_ratio

如果 direction = bullish：

```text
supporting_count = primary_bullish_count
conflicting_count = primary_bearish_count
```

如果 direction = bearish：

```text
supporting_count = primary_bearish_count
conflicting_count = primary_bullish_count
```

如果 direction = neutral：

```text
agreement_ratio = 0
```

如果 direction 非 neutral 且 `supporting_count + conflicting_count > 0`：

```text
agreement_ratio = supporting_count / (supporting_count + conflicting_count)
```

agreement_ratio 只表示 1d 主趋势证据与主方向的一致程度，不表示策略置信度。

4h 短周期趋势状态不得参与 agreement_ratio。

## 8. 证据输出

DomainSignalValue 必须输出：

```text
used_atomic_signal_codes；
used_atomic_signal_value_ids；
evidence_items；
evidence_text_zh；
payload_summary。
```

### 8.1 evidence_items

`evidence_items` 至少包含：

```json
{
  "evidence_type": "trend_domain_aggregation",
  "primary_bullish_count": 4,
  "primary_bearish_count": 0,
  "auxiliary_bullish_count": 1,
  "auxiliary_bearish_count": 3,
  "primary_direction": "bullish",
  "short_cycle_direction": "bearish",
  "direction": "bullish",
  "state_code": "trend_1d_bullish_4h_pullback",
  "coverage_ratio": "1",
  "agreement_ratio": "1",
  "strength": "1",
  "used_atomic_signal_value_ids": [201, 202, 203, 204, 205, 206, 207, 208]
}
```

不得在 evidence_items 中复制完整 AtomicSignalValue、完整 FeatureValue 或完整 K 线窗口。

### 8.2 evidence_text_zh

`evidence_text_zh` 必须能让人工快速判断趋势领域结论是否跑偏。

示例：

```text
trend 领域偏多：1d 偏多证据 4 项、偏空证据 0 项，形成 1d 主方向偏多；4h 偏空证据占优，表现为 1d 上行中的 4h 回调。
```

如果 1d 不明确但 4h 偏多：

```text
trend 领域中性：1d 多空证据差不足 2，无法形成主方向；4h 偏多只能作为短周期趋势状态事实。
```

如果失败：

```text
trend 领域计算失败：有效原子证据覆盖率 0.56，低于最低要求 0.70。
```

不得写交易建议。

## 9. payload_summary

`payload_summary` 至少包含：

```json
{
  "primary_timeframe": "1d",
  "auxiliary_timeframe": "4h",
  "primary_bullish_count": 4,
  "primary_bearish_count": 0,
  "primary_direction_gap": 4,
  "primary_direction": "bullish",
  "auxiliary_bullish_count": 1,
  "auxiliary_bearish_count": 3,
  "short_cycle_direction_gap": 2,
  "short_cycle_direction": "bearish",
  "supporting_count": 4,
  "conflicting_count": 0,
  "failed_atomic_count": 0,
  "valid_atomic_count": 16,
  "selected_atomic_count": 16
}
```

`payload_summary` 是摘要，不得复制完整证据链。

完整追溯必须通过 `used_atomic_signal_value_ids` 回查 AtomicSignalValue，再通过 `used_feature_value_ids` 回查 FeatureValue。

## 10. 与 MarketRegime 的边界

Trend DomainSignal 可以输出：

```text
trend_1d_bullish_4h_aligned；
trend_1d_bullish_4h_pullback；
trend_1d_bearish_4h_aligned；
trend_1d_bearish_4h_rebound；
trend_1d_neutral_4h_bullish；
trend_1d_neutral_4h_bearish；
trend_unclear。
```

但不得输出：

```text
牛市回调；
熊市反弹；
高位宽幅震荡；
低位筑底；
趋势中继整理；
支撑或压力位置下的策略处理；
突破或跌破后的交易动作。
```

这些必须由 MarketRegime 或更下游模块在自身边界内完成。

## 11. 人工复核视角

后台或复盘展示 trend 领域结果时，应至少展示：

```text
领域方向；
领域状态；
1d 偏多证据数量；
1d 偏空证据数量；
4h 偏多证据数量；
4h 偏空证据数量；
1d 主方向；
4h 短周期趋势状态；
覆盖率；
1d 证据一致性；
中文解释；
使用的原子信号列表。
```

人工应能从这些信息判断：

```text
系统是否把 1d 主趋势看偏多、偏空或不明确；
系统是否把 4h 短周期误当成主趋势；
系统是否识别了 1d 上行中的 4h 回调；
系统是否识别了 1d 下行中的 4h 反弹；
系统是否因为证据不足而失败。
```

## 12. 验收规则

### 12.1 1d 与 4h 同向偏多

如果以下条件同时满足：

```text
1d 偏多证据数量 - 1d 偏空证据数量 >= 2；
4h 偏多证据数量 - 4h 偏空证据数量 >= 2；
coverage_ratio >= 0.70。
```

则：

```text
direction = bullish
state_code = trend_1d_bullish_4h_aligned
strength > 0
```

### 12.2 1d 偏多但 4h 回调

如果以下条件同时满足：

```text
1d 偏多证据数量 - 1d 偏空证据数量 >= 2；
4h 偏空证据数量 - 4h 偏多证据数量 >= 2；
coverage_ratio >= 0.70。
```

则：

```text
direction = bullish
state_code = trend_1d_bullish_4h_pullback
strength 只按 1d 方向差计算，不因 4h 反向而扣减
```

不得输出“牛市回调”或“支撑位置策略处理”。

### 12.3 1d 与 4h 同向偏空

如果以下条件同时满足：

```text
1d 偏空证据数量 - 1d 偏多证据数量 >= 2；
4h 偏空证据数量 - 4h 偏多证据数量 >= 2；
coverage_ratio >= 0.70。
```

则：

```text
direction = bearish
state_code = trend_1d_bearish_4h_aligned
strength > 0
```

### 12.4 1d 偏空但 4h 反弹

如果以下条件同时满足：

```text
1d 偏空证据数量 - 1d 偏多证据数量 >= 2；
4h 偏多证据数量 - 4h 偏空证据数量 >= 2；
coverage_ratio >= 0.70。
```

则：

```text
direction = bearish
state_code = trend_1d_bearish_4h_rebound
strength 只按 1d 方向差计算，不因 4h 反向而扣减
```

不得输出“熊市反弹”或“压力位置策略处理”。

### 12.5 1d 不明确但 4h 偏多

如果以下条件同时满足：

```text
1d 多空证据差不足 2；
4h 偏多证据数量 - 4h 偏空证据数量 >= 2；
coverage_ratio >= 0.70。
```

则：

```text
direction = neutral
state_code = trend_1d_neutral_4h_bullish
strength = 0
```

4h 不能单独决定 trend 领域主方向。

### 12.6 覆盖率不足

如果有效 trend 原子信号覆盖率低于 0.70：

```text
DomainSignalValue.status = failed
is_valid = false
direction = none
strength = 0
error_code = trend_coverage_too_low
```

不得生成可被 MarketRegime 消费的有效领域值。

## 13. 本版本明确不处理

本版本不处理：

```text
3d 趋势；
周线趋势；
趋势通道；
人工趋势线；
ADX 趋势强度；
EMA 趋势体系；
MACD 趋势体系；
成交量确认；
概率置信度；
机器学习分类；
历史状态平滑；
连续多轮趋势确认；
趋势末端衰竭。
```

这些能力如需加入，必须新增算法需求文件或新增算法版本。
