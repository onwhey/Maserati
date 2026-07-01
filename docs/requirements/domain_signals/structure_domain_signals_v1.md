# Structure Domain Signals v1

## 1. 文件定位

本文档定义 `structure` 领域的第一版领域聚合规则。

它消费 [Structure Atomic Signals](../atomic_signals/structure_atomic_signals.md) 产生的 AtomicSignalValue，生成一份 `structure` DomainSignalValue。

本文档回答：

```text
1d 大结构处于靠近支撑、靠近压力、区间中部、突破、跌破还是不明确；
4h 小结构处于靠近支撑、靠近压力、区间中部、突破、跌破还是不明确；
1d 大结构与 4h 小结构是否同时支持同一结构状态；
是否出现“大结构未破但小结构走弱”；
结构领域结论用了哪些原子信号；
人工如何复核结构判断是否跑偏。
```

本文档不负责：

```text
判断牛市或熊市；
判断趋势方向；
判断动量是否配合；
判断波动风险；
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

Structure DomainSignal 只能读取同一 AtomicSignalSet 中、归属于 `structure` 领域、且被当前 StrategyAnalysisRelease 选中的 AtomicSignalValue。

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

如果需要新的结构原子证据，必须先修改 AtomicSignal requirements；如果需要新的基础数值，必须先修改 FeatureLayer requirements。

## 3. 输出模式

本版本 `structure` 使用“双层结构状态输出模式”：

```text
direction = major 结构方向优先；
state_code = major 与 minor 的组合摘要；
strength = 当前结构状态的清晰程度；
coverage_ratio = 已获得的有效原子证据覆盖程度；
agreement_ratio = major 与 minor 是否同向或同状态的结构一致程度；
payload_summary = 同时承载 major_structure 与 minor_structure。
```

`structure` 领域只输出一份 DomainSignalValue。

不得为同一轮行情分别输出“大结构领域值”和“小结构领域值”两条正式 DomainSignalValue。

但是一份 DomainSignalValue 的 payload 必须保留：

```text
major_structure；
minor_structure。
```

不得把 1d 大结构和 4h 小结构强行合并成一个价格带或一个单点结论。

## 4. 周期优先级

当前 P0 只使用 1d 与 4h。

周期职责：

```text
1d = major_structure 大结构；
4h = minor_structure 小结构。
```

领域方向由 major_structure 优先决定。

4h 小结构不得单独推翻 1d 大结构，只能表达短周期结构状态。

因此：

```text
1d 大结构靠近支撑 + 4h 小结构跌破 = direction 仍为 neutral，state_code 表达“大支撑附近但短线走弱”；
1d 大结构跌破 = direction 可以为 bearish；
1d 大结构突破 = direction 可以为 bullish；
1d 大结构不明确 + 4h 小结构突破 = direction 仍为 neutral，state_code 表达“小结构突破但大结构不明确”。
```

这保证 4h 只作为精细位置事实，不把 structure 领域降级成短线判断。

## 5. 原子信号分组

### 5.1 大结构位置证据

```text
structure_major_near_support
structure_major_near_resistance
structure_major_range_middle
structure_major_lower_half
structure_major_upper_half
```

### 5.2 小结构位置证据

```text
structure_minor_near_support
structure_minor_near_resistance
structure_minor_range_middle
structure_minor_lower_half
structure_minor_upper_half
```

### 5.3 大结构有效性证据

```text
structure_major_support_valid
structure_major_resistance_valid
structure_major_range_valid
structure_major_unclear
```

### 5.4 小结构有效性证据

```text
structure_minor_support_valid
structure_minor_resistance_valid
structure_minor_range_valid
structure_minor_unclear
```

### 5.5 结构突破 / 跌破证据

```text
structure_major_breakout_up
structure_major_breakdown_down
structure_minor_breakout_up
structure_minor_breakdown_down
```

## 6. 参数

本版本使用以下固定参数：

| 参数 | 值 | 说明 |
|---|---:|---|
| 最小覆盖率 | 0.70 | 至少 70% 被选中 structure 原子信号有效，领域才可用 |
| major 优先级 | 高 | 大结构先决定领域方向 |
| minor 方向上限 | neutral | 小结构不能单独决定领域方向 |
| clear_state_strength | 0.80 | major 出现突破、跌破、靠近支撑或靠近压力时的基础强度 |
| minor_only_strength_cap | 0.50 | 只有小结构明确时，领域强度封顶 |
| unclear_strength | 0 | 结构不明确时 strength 为 0 |

这些参数属于本算法版本的一部分。

后续如果调整覆盖率、状态优先级、major/minor 权重或 strength 计算方式，必须新增算法版本。

## 7. 计算流程

### 7.1 收集输入

从同一 AtomicSignalSet 中读取当前版本包选择的 structure 原子信号。

只允许使用：

```text
status = created；
is_valid = true；
definition_status = active；
definition_enabled = true。
```

failed 或 invalid 原子信号不参与状态判断，但必须计入 coverage_ratio。

### 7.2 计算 coverage_ratio

```text
coverage_ratio = 有效 structure 原子信号数量 / 当前版本包选择的 structure 原子信号数量
```

如果被选中的 structure 原子信号数量为 0，领域计算失败。

如果 `coverage_ratio < 0.70`：

```text
DomainSignalValue.status = failed
is_valid = false
direction = none
state_code = ""
strength = 0
error_code = structure_coverage_too_low
```

### 7.3 计算 major_structure

major 优先级从高到低：

```text
major_breakdown_down；
major_breakout_up；
major_unclear；
major_near_support；
major_near_resistance；
major_range_middle；
major_lower_half；
major_upper_half；
major_range_valid。
```

状态映射：

```text
major_breakdown_down 成立 → major_state = breakdown_down
major_breakout_up 成立 → major_state = breakout_up
major_unclear 成立 → major_state = unclear
major_near_support 成立 → major_state = near_support
major_near_resistance 成立 → major_state = near_resistance
major_range_middle 成立 → major_state = range_middle
major_lower_half 成立 → major_state = lower_half
major_upper_half 成立 → major_state = upper_half
否则 → major_state = range_observed 或 unclear
```

如果同时出现互斥状态，例如：

```text
major_breakout_up 与 major_breakdown_down 同时成立；
major_near_support 与 major_near_resistance 同时成立且 range_width 正常；
major_unclear 与 major_range_valid 同时成立。
```

则不直接判定 DomainSignal 失败，而是将大结构记录为冲突结构事实：

```text
major_state = conflicted
state_code = structure_major_conflicted
direction = neutral
strength = unclear_strength
```

结构冲突表示同一周期内结构事实重叠或不清晰，只能作为市场事实下传，不得解释成交易动作。

### 7.4 计算 minor_structure

minor 优先级从高到低：

```text
minor_breakdown_down；
minor_breakout_up；
minor_unclear；
minor_near_support；
minor_near_resistance；
minor_range_middle；
minor_lower_half；
minor_upper_half；
minor_range_valid。
```

状态映射与 major 相同，但输出到 `minor_structure`。

如果出现互斥状态，则不直接判定 DomainSignal 失败，而是将小结构记录为冲突结构事实：

```text
minor_state = conflicted
state_code = structure_major_<major_state>_minor_conflicted
direction 仍只由 major_state 决定
```

如果 major_state 本身不支持明确方向，minor conflicted 不得单独生成方向。

### 7.5 计算 direction

方向只由 major_structure 的结构突破或跌破决定：

```text
major_state = breakout_up → direction = bullish
major_state = breakdown_down → direction = bearish
其他 → direction = neutral
```

minor_structure 不得单独决定 direction。

例如：

```text
major_state = range_middle
minor_state = breakout_up
→ direction = neutral
```

### 7.6 计算 state_code

常见 state_code：

```text
structure_major_breakout_up
structure_major_breakdown_down
structure_major_near_support_minor_aligned
structure_major_near_support_minor_breakdown
structure_major_near_resistance_minor_aligned
structure_major_near_resistance_minor_breakout
structure_major_range_middle_minor_near_support
structure_major_range_middle_minor_near_resistance
structure_major_unclear_minor_clear
structure_unclear
```

组合规则：

```text
major 突破 / 跌破优先；
major 靠近支撑且 minor 也靠近支撑 → aligned；
major 靠近压力且 minor 也靠近压力 → aligned；
major 靠近支撑但 minor 跌破 → major_near_support_minor_breakdown；
major 靠近压力但 minor 突破 → major_near_resistance_minor_breakout；
major 区间中部时，minor 位置用于说明短线靠近哪一侧；
major 不明确但 minor 明确时，只表达 minor 清晰但大结构不足；
两者都不明确时 → structure_unclear。
```

state_code 不得包含交易动作语义。

禁止：

```text
support_long；
resistance_reduce；
breakdown_exit；
breakout_buy。
```

### 7.7 计算 agreement_ratio

agreement_ratio 只表达 major 与 minor 的结构一致程度。

```text
major 与 minor 同为 near_support / lower_half → agreement_ratio = 1
major 与 minor 同为 near_resistance / upper_half → agreement_ratio = 1
major 与 minor 同为 breakout_up → agreement_ratio = 1
major 与 minor 同为 breakdown_down → agreement_ratio = 1
major range_middle 且 minor range_middle → agreement_ratio = 0.7
major 明确但 minor 相反 → agreement_ratio = 0.2
major 或 minor unclear → agreement_ratio = 0
```

agreement_ratio 不用于订单动作，不得被解释成仓位比例。

### 7.8 计算 strength

strength 表示结构状态清晰程度，不表示交易强度。

基础规则：

```text
major_state in [breakout_up, breakdown_down] → strength = 0.90
major_state in [near_support, near_resistance] → strength = 0.80
major_state in [range_middle, lower_half, upper_half] → strength = 0.55
major_state = unclear 且 minor_state 明确 → strength = min(0.50, minor_strength)
major_state = unclear 且 minor_state unclear → strength = 0
```

minor 与 major 同向或同位置时，可提高但不得超过 1：

```text
strength = min(1.0, base_strength + 0.10 * agreement_ratio)
```

minor 与 major 相反时，不提高 strength。

## 8. payload_summary

DomainSignalValue 必须输出结构化 payload。

至少包括：

```json
{
  "major_structure": {
    "timeframe": "1d",
    "state": "near_support",
    "support_zone": {"lower": "60000", "upper": "61000"},
    "resistance_zone": {"lower": "69000", "upper": "70000"},
    "range_position_pct": "0.18",
    "distance_to_support_pct": "0.012",
    "distance_to_resistance_pct": "0.128",
    "touch_counts": {"support": 3, "resistance": 2}
  },
  "minor_structure": {
    "timeframe": "4h",
    "state": "range_middle",
    "support_zone": {"lower": "63200", "upper": "63600"},
    "resistance_zone": {"lower": "65500", "upper": "66000"},
    "range_position_pct": "0.51",
    "distance_to_support_pct": "0.030",
    "distance_to_resistance_pct": "0.028",
    "touch_counts": {"support": 2, "resistance": 2}
  },
  "combined_state": "structure_major_near_support_minor_range_middle"
}
```

payload 只保存结构事实和引用摘要，不保存交易动作。

不得出现：

```text
should_buy；
should_sell；
target_position_ratio；
limit_order_price；
stop_loss；
take_profit。
```

## 9. evidence_text_zh

`evidence_text_zh` 必须解释 major 与 minor 的关系。

示例：

```text
1d 大结构显示当前价格靠近 60000~61000 支撑区，4h 小结构仍处于 63200~66000 小区间中部；说明大结构靠近支撑，但短周期尚未给出更精确边界突破或跌破。
```

另一个示例：

```text
1d 大结构支撑尚未跌破，但 4h 小结构已经跌破 63200~63600 小支撑区；说明大结构未破、短线结构走弱。
```

不得写成：

```text
形成方向性交易处理；
形成仓位处理；
生成订单动作；
生成具体订单参数。
```

## 10. 与 MarketRegime 的关系

MarketRegime 可以综合：

```text
market_context；
trend；
momentum；
volatility；
structure；
risk_state。
```

例如：

```text
market_context = 大级别偏多；
trend = 1d 偏多、4h 回调；
momentum = 4h 多头动能减弱；
volatility = 宽幅震荡；
structure = 1d 靠近大支撑，4h 小结构中部；
```

MarketRegime 可以据此判断：

```text
大级别偏多下的回调接近大支撑，但短周期尚未到小支撑。
```

Structure DomainSignal 不得自己生成该跨领域结论。

## 11. 与 StrategySignal 的关系

StrategySignal 可以根据路由选中的策略使用 structure 领域事实。

例如：

```text
long_pullback_support_v1 可以使用 near_support；
long_trend_following_v1 可以使用 breakout_up；
short_rebound_pressure_v1 可以使用 near_resistance；
short_trend_following_v1 可以使用 breakdown_down。
```

但是 StrategySignal 不得：

```text
直接读取 FeatureValue；
直接读取 AtomicSignalValue；
重新计算支撑压力；
重算 major / minor 结构；
绕过 structure DomainSignal 生成结构事实。
```

## 12. 与 StrategyAnalysisRelease 的关系

正式运行只允许消费：

```text
被当前 StrategyAnalysisRelease 领域切片明确选中；
状态 active；
enabled = true；
依赖 AtomicSignalDefinition 完整；
calculator 已注册；
算法 requirements 与 implementation 记录完整；
验证证据完整。
```

同一 StrategyAnalysisRelease 中，同一 `domain_code=structure` 只能选择一个 DomainSignalDefinition 版本。

## 13. 测试要求

至少覆盖：

```text
major 靠近支撑 + minor 靠近支撑 → aligned；
major 靠近支撑 + minor 跌破 → 大支撑附近但短线走弱；
major 区间中部 + minor 靠近支撑 → 大区间中部、短线靠近小支撑；
major 突破压力 → direction bullish；
major 跌破支撑 → direction bearish；
minor 突破压力但 major 不明确 → direction neutral；
major 和 minor 都不明确 → structure_unclear；
coverage_ratio 低于阈值时 failed；
互斥 major / minor 状态同时成立时输出 conflicted 结构事实，不直接 failed；
payload 同时包含 major_structure 与 minor_structure；
evidence_text_zh 不包含交易动作。
```

## 14. 明确禁止

禁止：

```text
让 Structure DomainSignal 读取 FeatureValue；
让 Structure DomainSignal 读取 Kline；
让 Structure DomainSignal 重新计算支撑压力；
把 1d 大结构和 4h 小结构合并成单一价格带；
让 4h 小结构单独推翻 1d 大结构；
让 DomainSignal 输出支撑、压力或跌破后的交易处理；
让 DomainSignal 输出 target_position_ratio；
让 DomainSignal 生成订单意图；
让 DomainSignal 访问 Binance、DeepSeek、账户或 PriceSnapshot；
绕过 StrategyAnalysisRelease 直接启用 structure 领域。
```
