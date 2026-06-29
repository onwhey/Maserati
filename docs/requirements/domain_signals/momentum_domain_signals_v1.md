# Momentum Domain Signals

## 1. 文件定位

本文档定义 `momentum` 领域的第一版领域聚合规则。

它消费 [Momentum Atomic Signals](../atomic_signals/momentum_atomic_signals.md) 产生的 AtomicSignalValue，生成一份 momentum DomainSignalValue。

本文档回答：

```text
1d 日线级动能偏多、偏空还是不明确；
1d 日线级动能是在增强、衰竭、顺畅推进还是拉扯严重；
4h 短周期动能偏多、偏空还是不明确；
4h 短周期动能是在增强、衰竭、顺畅推进还是拉扯严重；
当前动能领域结论用了哪些原子信号；
动能领域结论为什么成立；
人工如何复核该领域判断是否跑偏。
```

本文档不负责：

```text
判断趋势方向；
判断大级别牛市或熊市；
判断支撑压力；
判断突破质量；
判断完整 MarketRegime；
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

Momentum DomainSignal 只能读取同一 AtomicSignalSet 中、归属于 `momentum` 领域、且被当前 StrategyAnalysisRelease 选中的 AtomicSignalValue。

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

如果需要新的动能原子证据，必须先修改 AtomicSignal requirements；如果需要新的基础数值，必须先修改 FeatureLayer requirements。

## 3. 输出模式

本版本 `momentum` 使用主周期优先的 directional 输出模式：

```text
direction = bullish / bearish / neutral；
state_code = 用于表达 1d 主动能状态；
strength = 仅由 1d 动能方向证据决定的动能明显程度；
coverage_ratio = 已获得的有效原子证据覆盖程度；
agreement_ratio = 仅由 1d 动能方向证据计算的一致程度；
payload_summary = 同时承载 1d 与 4h 的动能状态摘要。
```

`momentum` 领域只输出一份 DomainSignalValue。

不得为同一轮行情分别输出“多头动能领域值”和“空头动能领域值”。

## 4. 周期优先级

当前 P0 只使用 1d 与 4h。

周期职责：

```text
1d = 日线级主动能判断周期；
4h = 短周期动能状态周期。
```

领域主方向由 1d 动能聚合结果决定。

4h 不得单独推翻 1d 主动能方向，只能表达短周期动能状态：

```text
与 1d 同向增强；
与 1d 同向但衰竭；
与 1d 反向增强；
4h 不明确；
4h 拉扯严重。
```

因此：

```text
1d 多头动能仍在 + 4h 空头动能增强 = momentum direction 仍按 1d 判断，4h 只表达短周期反向动能；
1d 空头动能仍在 + 4h 多头动能增强 = momentum direction 仍按 1d 判断，4h 只表达短周期反弹动能；
1d 不明确 + 4h 偏多或偏空 = momentum direction 仍为 neutral。
```

这保证 4h 只作为短周期动能事实，不把动能领域降级成短线判断。

4h 不参与：

```text
momentum direction；
momentum strength；
momentum agreement_ratio。
```

4h 只进入：

```text
payload_summary；
evidence_text_zh；
state_tags。
```

当前不引入 3d、1w、MACD、RSI、ADX、成交量或背离。

## 5. 原子信号分组

### 5.1 1d 偏多动能证据

以下原子信号成立时，计入 1d 偏多动能证据：

```text
momentum_1d_bullish_push_exists
momentum_1d_bullish_push_strengthening
momentum_1d_bullish_continuity_good
momentum_1d_close_strength_bullish
```

### 5.2 1d 偏空动能证据

以下原子信号成立时，计入 1d 偏空动能证据：

```text
momentum_1d_bearish_push_exists
momentum_1d_bearish_push_strengthening
momentum_1d_bearish_continuity_good
momentum_1d_close_strength_bearish
```

### 5.3 1d 衰竭与效率状态

以下原子信号成立时，不直接改变方向票数，只进入 1d 动能状态：

```text
momentum_1d_bullish_push_exhausting
momentum_1d_bearish_push_exhausting
momentum_1d_movement_efficiency_high
momentum_1d_movement_efficiency_low
```

### 5.4 4h 偏多动能证据

以下原子信号成立时，计入 4h 偏多动能证据：

```text
momentum_4h_bullish_push_exists
momentum_4h_bullish_push_strengthening
momentum_4h_bullish_continuity_good
momentum_4h_close_strength_bullish
```

### 5.5 4h 偏空动能证据

以下原子信号成立时，计入 4h 偏空动能证据：

```text
momentum_4h_bearish_push_exists
momentum_4h_bearish_push_strengthening
momentum_4h_bearish_continuity_good
momentum_4h_close_strength_bearish
```

### 5.6 4h 衰竭与效率状态

以下原子信号成立时，不直接改变 4h 方向票数，只进入 4h 动能状态：

```text
momentum_4h_bullish_push_exhausting
momentum_4h_bearish_push_exhausting
momentum_4h_movement_efficiency_high
momentum_4h_movement_efficiency_low
```

## 6. 参数

本版本使用以下固定参数：

| 参数 | 值 | 说明 |
|---|---:|---|
| 最小覆盖率 | 0.70 | 至少 70% 被选中 momentum 原子信号有效，领域才可用 |
| 1d 最小方向差 | 2 | 1d 多空动能证据数量差至少为 2，才形成主动能方向 |
| 4h 最小方向差 | 2 | 4h 多空动能证据数量差至少为 2，才形成短周期动能方向 |
| 1d 强方向差 | 4 | 1d 多空动能证据数量差达到 4，认为主动能非常明显 |

这些参数属于本算法版本的一部分。

后续如果调整方向差、覆盖率、强度计算或状态映射，必须新增算法版本。

## 7. 计算流程

### 7.1 收集输入

从同一 AtomicSignalSet 中读取当前版本包选择的 momentum 原子信号。

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
coverage_ratio = 有效 momentum 原子信号数量 / 当前版本包选择的 momentum 原子信号数量
```

如果被选中的 momentum 原子信号数量为 0，领域计算失败。

如果 `coverage_ratio < 0.70`：

```text
DomainSignalValue.status = failed
is_valid = false
direction = none
state_code = ""
strength = 0
error_code = momentum_coverage_too_low
```

### 7.3 计算 1d 动能方向

只统计有效且条件成立的 1d 动能方向原子信号。

```text
primary_bullish_count = 成立的 1d 偏多动能证据数量
primary_bearish_count = 成立的 1d 偏空动能证据数量
primary_direction_gap = abs(primary_bullish_count - primary_bearish_count)
```

如果：

```text
primary_bullish_count - primary_bearish_count >= 2
```

则：

```text
primary_momentum_direction = bullish
```

如果：

```text
primary_bearish_count - primary_bullish_count >= 2
```

则：

```text
primary_momentum_direction = bearish
```

否则：

```text
primary_momentum_direction = neutral
```

### 7.4 计算 4h 短周期动能方向

只统计有效且条件成立的 4h 动能方向原子信号。

```text
short_cycle_bullish_count = 成立的 4h 偏多动能证据数量
short_cycle_bearish_count = 成立的 4h 偏空动能证据数量
short_cycle_direction_gap = abs(short_cycle_bullish_count - short_cycle_bearish_count)
```

如果：

```text
short_cycle_bullish_count - short_cycle_bearish_count >= 2
```

则：

```text
short_cycle_momentum_direction = bullish
```

如果：

```text
short_cycle_bearish_count - short_cycle_bullish_count >= 2
```

则：

```text
short_cycle_momentum_direction = bearish
```

否则：

```text
short_cycle_momentum_direction = neutral
```

### 7.5 计算 1d 动能阶段

1d 动能阶段由主动能方向与 1d 衰竭、增强、效率状态共同形成。

如果 `primary_momentum_direction = bullish`：

| 条件 | primary_momentum_phase |
|---|---|
| `momentum_1d_bullish_push_exhausting` 成立 | `exhausting` |
| `momentum_1d_bullish_push_strengthening` 成立 | `strengthening` |
| `momentum_1d_movement_efficiency_low` 成立 | `choppy` |
| 以上都不成立 | `present` |

如果 `primary_momentum_direction = bearish`：

| 条件 | primary_momentum_phase |
|---|---|
| `momentum_1d_bearish_push_exhausting` 成立 | `exhausting` |
| `momentum_1d_bearish_push_strengthening` 成立 | `strengthening` |
| `momentum_1d_movement_efficiency_low` 成立 | `choppy` |
| 以上都不成立 | `present` |

如果 `primary_momentum_direction = neutral`：

| 条件 | primary_momentum_phase |
|---|---|
| `momentum_1d_movement_efficiency_low` 成立 | `choppy` |
| 其他情况 | `unclear` |

同一方向的 strengthening 与 exhausting 理论上不应同时成立。

如果由于数据或定义错误导致同一方向 strengthening 与 exhausting 同时成立：

```text
primary_momentum_phase = conflict
state_tags 必须包含 primary_momentum_conflict
evidence_text_zh 必须说明冲突。
```

### 7.6 计算 4h 短周期动能阶段

4h 短周期动能阶段规则与 1d 相同，但只使用 4h 原子信号。

如果 `short_cycle_momentum_direction = bullish`：

| 条件 | short_cycle_momentum_phase |
|---|---|
| `momentum_4h_bullish_push_exhausting` 成立 | `exhausting` |
| `momentum_4h_bullish_push_strengthening` 成立 | `strengthening` |
| `momentum_4h_movement_efficiency_low` 成立 | `choppy` |
| 以上都不成立 | `present` |

如果 `short_cycle_momentum_direction = bearish`：

| 条件 | short_cycle_momentum_phase |
|---|---|
| `momentum_4h_bearish_push_exhausting` 成立 | `exhausting` |
| `momentum_4h_bearish_push_strengthening` 成立 | `strengthening` |
| `momentum_4h_movement_efficiency_low` 成立 | `choppy` |
| 以上都不成立 | `present` |

如果 `short_cycle_momentum_direction = neutral`：

| 条件 | short_cycle_momentum_phase |
|---|---|
| `momentum_4h_movement_efficiency_low` 成立 | `choppy` |
| 其他情况 | `unclear` |

### 7.7 计算领域 direction

领域主方向只由 1d 动能方向决定。

| primary_momentum_direction | direction |
|---|---|
| bullish | bullish |
| bearish | bearish |
| neutral | neutral |

如果 primary_momentum_direction = neutral，即使 short_cycle_momentum_direction 为 bullish 或 bearish，领域 direction 也必须为 neutral。

### 7.8 计算 state_code

`state_code` 只表达 1d 主动能状态。

| primary_momentum_direction | primary_momentum_phase | state_code |
|---|---|---|
| bullish | strengthening | `momentum_1d_bullish_strengthening` |
| bullish | exhausting | `momentum_1d_bullish_exhausting` |
| bullish | choppy | `momentum_1d_bullish_choppy` |
| bullish | present | `momentum_1d_bullish_present` |
| bearish | strengthening | `momentum_1d_bearish_strengthening` |
| bearish | exhausting | `momentum_1d_bearish_exhausting` |
| bearish | choppy | `momentum_1d_bearish_choppy` |
| bearish | present | `momentum_1d_bearish_present` |
| neutral | choppy | `momentum_1d_choppy` |
| neutral | unclear | `momentum_unclear` |
| any | conflict | `momentum_conflict` |

4h 短周期动能状态不进入主 state_code，而是进入 `payload_summary.short_cycle_momentum_*` 与 `state_tags`。

这样可以避免 state_code 因 1d 和 4h 组合过多而失控，同时保留完整短周期证据。

### 7.9 计算 strength

本版本 strength 表示 1d 主动能方向明显程度。

如果 direction = bullish 或 bearish：

```text
strength = min(1, primary_direction_gap / 4)
```

如果 direction = neutral：

```text
strength = 0
```

strength 不代表盈利概率，不代表仓位比例，不代表交易规模。

4h 短周期动能状态不得给 strength 加分或扣分。

### 7.10 计算 agreement_ratio

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

agreement_ratio 只表示 1d 主动能证据与主方向的一致程度，不表示策略置信度。

4h 短周期动能状态不得参与 agreement_ratio。

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
  "evidence_type": "momentum_domain_aggregation",
  "primary_bullish_count": 4,
  "primary_bearish_count": 0,
  "primary_momentum_direction": "bullish",
  "primary_momentum_phase": "strengthening",
  "short_cycle_bullish_count": 1,
  "short_cycle_bearish_count": 3,
  "short_cycle_momentum_direction": "bearish",
  "short_cycle_momentum_phase": "strengthening",
  "direction": "bullish",
  "state_code": "momentum_1d_bullish_strengthening",
  "coverage_ratio": "1",
  "agreement_ratio": "1",
  "strength": "1",
  "state_tags": ["short_cycle_bearish_strengthening"],
  "used_atomic_signal_value_ids": [301, 302, 303, 304, 305, 306]
}
```

不得在 evidence_items 中复制完整 AtomicSignalValue、完整 FeatureValue 或完整 K 线窗口。

### 8.2 evidence_text_zh

`evidence_text_zh` 必须能让人工快速判断动能领域结论是否跑偏。

示例：

```text
momentum 领域偏多：1d 多头动能证据 4 项、空头动能证据 0 项，形成日线级多头动能；其中 1d 多头推进增强成立，状态为多头动能增强。4h 短周期空头动能证据占优，说明短周期存在反向推动。
```

如果 1d 不明确但 4h 偏多：

```text
momentum 领域中性：1d 多空动能证据差不足 2，无法形成主动能方向；4h 偏多只能作为短周期动能事实。
```

如果 1d 多头推进衰竭：

```text
momentum 领域偏多但衰竭：1d 多头动能证据占优，但 1d 多头推进衰竭原子信号成立，说明上涨仍在但推进速度明显下降。
```

如果失败：

```text
momentum 领域计算失败：有效原子证据覆盖率 0.56，低于最低要求 0.70。
```

不得写交易建议。

## 9. payload_summary

`payload_summary` 至少包含：

```json
{
  "primary_timeframe": "1d",
  "short_cycle_timeframe": "4h",
  "primary_bullish_count": 4,
  "primary_bearish_count": 0,
  "primary_direction_gap": 4,
  "primary_momentum_direction": "bullish",
  "primary_momentum_phase": "strengthening",
  "short_cycle_bullish_count": 1,
  "short_cycle_bearish_count": 3,
  "short_cycle_direction_gap": 2,
  "short_cycle_momentum_direction": "bearish",
  "short_cycle_momentum_phase": "strengthening",
  "primary_efficiency_state": "high",
  "short_cycle_efficiency_state": "low",
  "state_tags": ["primary_efficiency_high", "short_cycle_bearish_strengthening", "short_cycle_efficiency_low"],
  "supporting_count": 4,
  "conflicting_count": 0,
  "failed_atomic_count": 0,
  "valid_atomic_count": 20,
  "selected_atomic_count": 20
}
```

`payload_summary` 是摘要，不得复制完整证据链。

完整追溯必须通过 `used_atomic_signal_value_ids` 回查 AtomicSignalValue，再通过 `used_feature_value_ids` 回查 FeatureValue。

## 10. 与 MarketRegime 的边界

Momentum DomainSignal 可以输出：

```text
momentum_1d_bullish_strengthening；
momentum_1d_bullish_exhausting；
momentum_1d_bearish_strengthening；
momentum_1d_bearish_exhausting；
momentum_1d_choppy；
momentum_unclear。
```

但不得输出：

```text
上涨趋势中的正常回调；
下跌趋势中的反弹；
突破质量良好；
突破质量不足；
牛市回调；
熊市反弹；
支撑区或压力区的交易处理；
追单判断；
仓位调整判断；
订单动作判断。
```

这些必须由 MarketRegime 或更下游模块在自身边界内完成。

## 11. 人工复核视角

后台或复盘展示 momentum 领域结果时，应至少展示：

```text
领域方向；
领域状态；
1d 多头动能证据数量；
1d 空头动能证据数量；
1d 动能阶段；
4h 多头动能证据数量；
4h 空头动能证据数量；
4h 短周期动能方向；
4h 短周期动能阶段；
1d 推进效率状态；
4h 推进效率状态；
覆盖率；
1d 证据一致性；
中文解释；
使用的原子信号列表。
```

人工应能从这些信息判断：

```text
系统是否把日线级动能看偏多、偏空或不明确；
系统是否注意到日线级动能增强或衰竭；
系统是否把短周期动能误当成主动能方向；
系统是否因为证据不足而失败；
系统是否出现多空动能证据严重冲突。
```

## 12. 验收规则

### 12.1 1d 多头动能增强

如果以下条件同时满足：

```text
1d 偏多动能证据数量 - 1d 偏空动能证据数量 >= 2；
momentum_1d_bullish_push_strengthening 成立；
coverage_ratio >= 0.70。
```

则：

```text
direction = bullish
state_code = momentum_1d_bullish_strengthening
strength > 0
payload_summary.primary_momentum_phase = strengthening
```

### 12.2 1d 多头动能衰竭

如果以下条件同时满足：

```text
1d 偏多动能证据数量 - 1d 偏空动能证据数量 >= 2；
momentum_1d_bullish_push_exhausting 成立；
coverage_ratio >= 0.70。
```

则：

```text
direction = bullish
state_code = momentum_1d_bullish_exhausting
strength 只按 1d 方向差计算
payload_summary.primary_momentum_phase = exhausting
```

不得输出仓位处理或交易方向处理。

### 12.3 1d 空头动能增强

如果以下条件同时满足：

```text
1d 偏空动能证据数量 - 1d 偏多动能证据数量 >= 2；
momentum_1d_bearish_push_strengthening 成立；
coverage_ratio >= 0.70。
```

则：

```text
direction = bearish
state_code = momentum_1d_bearish_strengthening
strength > 0
payload_summary.primary_momentum_phase = strengthening
```

### 12.4 1d 空头动能衰竭

如果以下条件同时满足：

```text
1d 偏空动能证据数量 - 1d 偏多动能证据数量 >= 2；
momentum_1d_bearish_push_exhausting 成立；
coverage_ratio >= 0.70。
```

则：

```text
direction = bearish
state_code = momentum_1d_bearish_exhausting
payload_summary.primary_momentum_phase = exhausting
```

不得输出交易方向处理。

### 12.5 1d 不明确但 4h 偏多

如果以下条件同时满足：

```text
1d 多空动能证据差不足 2；
4h 偏多动能证据数量 - 4h 偏空动能证据数量 >= 2；
coverage_ratio >= 0.70。
```

则：

```text
direction = neutral
state_code = momentum_unclear 或 momentum_1d_choppy
strength = 0
payload_summary.short_cycle_momentum_direction = bullish
```

4h 不能单独决定 momentum 领域主方向。

### 12.6 1d 偏多但 4h 反向增强

如果以下条件同时满足：

```text
1d 偏多动能证据数量 - 1d 偏空动能证据数量 >= 2；
4h 偏空动能证据数量 - 4h 偏多动能证据数量 >= 2；
momentum_4h_bearish_push_strengthening 成立；
coverage_ratio >= 0.70。
```

则：

```text
direction = bullish
state_code 按 1d 主动能状态确定；
payload_summary.short_cycle_momentum_direction = bearish；
payload_summary.short_cycle_momentum_phase = strengthening。
```

不得输出“趋势反转”或交易方向处理。

### 12.7 覆盖率不足

如果有效 momentum 原子信号覆盖率低于 0.70：

```text
DomainSignalValue.status = failed
is_valid = false
direction = none
strength = 0
error_code = momentum_coverage_too_low
```

不得生成可被 MarketRegime 消费的有效领域值。

## 13. 本版本明确不处理

本版本不处理：

```text
3d 动能；
周线动能；
MACD；
RSI；
ADX；
成交量确认；
动量背离；
突破伴随动量增强；
突破但动量不跟随；
新高后动量不跟随；
新低后动量不跟随；
连续上涨后过热；
连续下跌后过热；
急涨后动量断裂；
急跌后反弹动量不足；
概率置信度；
机器学习分类；
历史状态平滑；
连续多轮动能确认。
```

这些能力如需加入，必须新增算法需求文件或新增算法版本。
