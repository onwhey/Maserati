# Structure Atomic Signals

## 1. 文件定位

本文档定义 `structure` 领域的第一批原子信号。

这些原子信号基于 [Structure Features](../feature_layer/structure_features.md) 输出的结构特征，形成最小结构判断。

本文档回答：

```text
当前价格是否靠近 1d 大支撑或大压力；
当前价格是否靠近 4h 小支撑或小压力；
当前价格是否处于大区间或小区间中部；
大结构或小结构是否出现突破 / 跌破；
支撑压力区是否具备基本有效性；
每个判断使用哪些 FeatureValue；
每个判断为什么成立或不成立；
下游如何追溯判断依据。
```

本文档不负责：

```text
判断牛市或熊市；
判断趋势方向；
判断动量是否配合；
判断波动风险；
综合 1d 与 4h 形成完整 structure 领域结论；
识别 MarketRegime；
选择策略；
生成 StrategySignal；
生成 DecisionSnapshot；
读取账户或持仓；
请求 Binance；
执行真实交易。
```

本文档不是一个整体算法版本。本文档中的每个 AtomicSignalDefinition 独立版本化，单个原子信号算法升级时，只新增或切换该 AtomicSignalDefinition 的版本，不要求整份 structure 原子信号清单整体升级。

## 2. 设计原则

Structure 原子信号必须保持简单。

每个原子信号只回答一个明确问题：

```text
某个结构条件是否成立？
```

例如：

```text
当前价格是否靠近 1d 大支撑区；
当前价格是否靠近 4h 小压力区；
当前价格是否突破 4h 小压力区；
当前价格是否跌破 1d 大支撑区。
```

原子信号不得直接输出：

```text
支撑位置下的交易处理；
压力位置下的仓位处理；
跌破结构后的仓位处理；
突破结构后的交易处理；
方向反转后的交易处理；
目标仓位；
订单动作；
限价单价格。
```

这些结论必须由 StrategySignal、DecisionSnapshot、OrderPlan 或后续模块在各自职责内完成。

## 3. 输入要求

本文件只允许读取同一个 FeatureSet 内的 FeatureValue。

FeatureLayer 是 structure 特征的数据工厂，负责计算并落库 `structure_features.md` 定义的 FeatureValue。

Structure AtomicSignal 是数据用户，只读取这些已经落库的 FeatureValue，不调用 FeatureLayer calculator，不调用 swing、聚类、触碰次数、区间位置或突破幅度算法。

多个 Structure 原子信号依赖同一个特征时，必须引用同一个 FeatureSet 内同一份 FeatureValue。

输入 FeatureValue 必须来自：

```text
docs/requirements/feature_layer/structure_features.md
```

不得读取：

```text
Kline；
MarketSnapshot 原始 K 线；
FeatureLayer calculator；
swing high / swing low 算法函数；
支撑压力聚类算法函数；
其他 AtomicSignalValue；
DomainSignalValue；
MarketRegimeSnapshot；
账户；
持仓；
订单；
成交；
PriceSnapshot；
Binance。
```

如果必需 FeatureValue 缺失、不可计算或不属于同一 FeatureSet，则对应 AtomicSignalValue 必须失败，不得用默认值替代，也不得在原子层临时补算。

## 4. 周期职责

当前 Structure 原子信号使用两套结构事实：

```text
1d 大结构 FeatureValue；
4h 小结构 FeatureValue。
```

职责划分：

```text
1d 大结构原子信号 = 大级别支撑压力和结构变化事实；
4h 小结构原子信号 = 大区间内部更细的短周期位置事实。
```

4h 小结构不得推翻 1d 大结构。

例如：

```text
4h 小支撑跌破 = 短周期结构走弱；
1d 大支撑未跌破 = 大结构尚未破坏。
```

是否因此形成仓位处理、维持目标或切换策略，不属于 AtomicSignal。

## 5. 输出合同

每个原子信号输出 AtomicSignalValue。

### 5.1 成立与不成立

如果条件成立：

```text
status = created
is_valid = true
value_bool = true
direction = 该信号定义的默认方向
strength = 1
confidence = null
```

如果条件不成立：

```text
status = created
is_valid = true
value_bool = false
direction = neutral
strength = 0
confidence = null
```

如果计算失败：

```text
status = failed
is_valid = false
value_bool = null
direction = none
strength = 0
confidence = null
error_code 非空
evidence_text_zh 说明失败原因
```

### 5.2 confidence 规则

当前清单中的 Structure 原子信号默认：

```text
confidence = null
```

原因是这些信号只是确定性条件判断，尚未经过样本外概率校准。

不得因为计算成功就把 `confidence` 写成 1。

### 5.3 direction 语义

大多数 structure 原子信号默认 `direction = neutral`。

例外：

```text
向上突破压力区 = bullish；
向下跌破支撑区 = bearish。
```

这里的 bullish / bearish 只表达结构方向，不是交易动作。

不得把：

```text
bullish 解释成方向性交易处理；
bearish 解释成方向性交易处理；
neutral 解释成本轮不形成交易目标。
```

## 6. 证据输出要求

每个 AtomicSignalValue 必须同时输出：

```text
used_feature_codes；
used_feature_value_ids；
evidence_items；
evidence_text_zh。
```

### 6.1 evidence_items 结构

`evidence_items` 至少包含：

```json
{
  "evidence_type": "structure_atomic_condition",
  "signal_code": "structure_minor_near_support",
  "condition_result": true,
  "structure_level": "minor",
  "used_features": [
    {
      "feature_code": "structure_minor_support_upper_4h_120",
      "feature_value_id": 123,
      "observed_value": "63600"
    },
    {
      "feature_code": "structure_minor_distance_to_support_upper_pct_4h_120",
      "feature_value_id": 124,
      "observed_value": "0.006"
    }
  ],
  "thresholds": {
    "near_zone_max_pct": "0.010"
  },
  "supporting_facts": [
    "4h 小支撑区上沿为 63600。",
    "当前收盘价距离小支撑区上沿 0.6%。"
  ],
  "weakening_facts": [],
  "calculation_summary": "distance_to_support_upper_pct <= 0.010"
}
```

`evidence_items` 只保存摘要和引用，不得复制完整 FeatureValue、完整 K 线窗口或完整 swing 点列表。

### 6.2 evidence_text_zh 结构

`evidence_text_zh` 必须是中文短句，面向人工复核可读。

示例：

```text
4h 小支撑区为 63200~63600，当前收盘价距离支撑上沿 0.6%，低于 1.0% 靠近阈值，因此“4h 靠近小支撑区”成立。
```

如果条件不成立，也必须说明原因：

```text
当前收盘价距离 4h 小支撑上沿 2.8%，高于 1.0% 靠近阈值，因此“4h 靠近小支撑区”不成立。
```

不得在 `evidence_text_zh` 中写交易建议。

## 7. 固定参数

| 参数 | 1d 大结构 | 4h 小结构 | 说明 |
|---|---:|---:|---|
| 靠近支撑阈值 | 2.5% | 1.0% | 当前价距离支撑上沿的最大比例 |
| 靠近压力阈值 | 2.5% | 1.0% | 当前价距离压力下沿的最大比例 |
| 突破确认缓冲 | 0.8% | 0.4% | 收盘价突破压力上沿的最小比例 |
| 跌破确认缓冲 | 0.8% | 0.4% | 收盘价跌破支撑下沿的最小比例 |
| 最少支撑触碰 | 2 | 2 | 支撑区基本有效性 |
| 最少压力触碰 | 2 | 2 | 压力区基本有效性 |
| 最小区间位置 | 0.25 | 0.25 | 低于该值认为靠近区间下半部 |
| 最大区间位置 | 0.75 | 0.75 | 高于该值认为靠近区间上半部 |

这些参数属于本批 AtomicSignalDefinition 的初始算法版本。

后续如果调整阈值或判断方式，必须新增对应原子信号版本。

## 8. P0 AtomicSignalDefinition

### 8.1 大结构位置原子信号

| SignalCode | 业务问题 | 默认方向 | 必需 FeatureValue |
|---|---|---|---|
| structure_major_near_support | 当前是否靠近 1d 大支撑区 | neutral | latest_close、major_support_upper、major_distance_to_support_upper_pct |
| structure_major_near_resistance | 当前是否靠近 1d 大压力区 | neutral | latest_close、major_resistance_lower、major_distance_to_resistance_lower_pct |
| structure_major_range_middle | 当前是否处于 1d 大区间中部 | neutral | major_range_position_pct |
| structure_major_lower_half | 当前是否处于 1d 大区间下半部 | neutral | major_range_position_pct |
| structure_major_upper_half | 当前是否处于 1d 大区间上半部 | neutral | major_range_position_pct |

判断口径：

```text
near_support = distance_to_support_upper_pct >= 0 AND distance_to_support_upper_pct <= 0.025
near_resistance = distance_to_resistance_lower_pct >= 0 AND distance_to_resistance_lower_pct <= 0.025
range_middle = range_position_pct > 0.25 AND range_position_pct < 0.75
lower_half = range_position_pct <= 0.50
upper_half = range_position_pct >= 0.50
```

### 8.2 小结构位置原子信号

| SignalCode | 业务问题 | 默认方向 | 必需 FeatureValue |
|---|---|---|---|
| structure_minor_near_support | 当前是否靠近 4h 小支撑区 | neutral | latest_close、minor_support_upper、minor_distance_to_support_upper_pct |
| structure_minor_near_resistance | 当前是否靠近 4h 小压力区 | neutral | latest_close、minor_resistance_lower、minor_distance_to_resistance_lower_pct |
| structure_minor_range_middle | 当前是否处于 4h 小区间中部 | neutral | minor_range_position_pct |
| structure_minor_lower_half | 当前是否处于 4h 小区间下半部 | neutral | minor_range_position_pct |
| structure_minor_upper_half | 当前是否处于 4h 小区间上半部 | neutral | minor_range_position_pct |

判断口径：

```text
near_support = distance_to_support_upper_pct >= 0 AND distance_to_support_upper_pct <= 0.010
near_resistance = distance_to_resistance_lower_pct >= 0 AND distance_to_resistance_lower_pct <= 0.010
range_middle = range_position_pct > 0.25 AND range_position_pct < 0.75
lower_half = range_position_pct <= 0.50
upper_half = range_position_pct >= 0.50
```

### 8.3 支撑压力基本有效性原子信号

| SignalCode | 业务问题 | 默认方向 | 必需 FeatureValue |
|---|---|---|---|
| structure_major_support_valid | 1d 大支撑区是否具备基本有效性 | neutral | major_support_lower、major_support_upper、major_support_touch_count、major_support_score |
| structure_major_resistance_valid | 1d 大压力区是否具备基本有效性 | neutral | major_resistance_lower、major_resistance_upper、major_resistance_touch_count、major_resistance_score |
| structure_minor_support_valid | 4h 小支撑区是否具备基本有效性 | neutral | minor_support_lower、minor_support_upper、minor_support_touch_count、minor_support_score |
| structure_minor_resistance_valid | 4h 小压力区是否具备基本有效性 | neutral | minor_resistance_lower、minor_resistance_upper、minor_resistance_touch_count、minor_resistance_score |

判断口径：

```text
zone_lower 不为空；
zone_upper 不为空；
touch_count >= 2；
zone_score > 0。
```

### 8.4 区间结构原子信号

| SignalCode | 业务问题 | 默认方向 | 必需 FeatureValue |
|---|---|---|---|
| structure_major_range_valid | 1d 大支撑压力区间是否具备基本可解释性 | neutral | major_support_valid 所需特征、major_resistance_valid 所需特征、major_range_width_pct |
| structure_minor_range_valid | 4h 小支撑压力区间是否具备基本可解释性 | neutral | minor_support_valid 所需特征、minor_resistance_valid 所需特征、minor_range_width_pct |

判断口径：

```text
support_valid = true；
resistance_valid = true；
support_upper < resistance_lower；
range_width_pct > 0；
range_width_pct <= 对应周期最大有效区间宽度。
```

最大有效区间宽度：

```text
1d 大结构 = 45%；
4h 小结构 = 20%。
```

### 8.5 突破与跌破原子信号

| SignalCode | 业务问题 | 默认方向 | 必需 FeatureValue |
|---|---|---|---|
| structure_major_breakout_up | 当前是否收盘突破 1d 大压力区 | bullish | major_breakout_above_resistance_pct |
| structure_major_breakdown_down | 当前是否收盘跌破 1d 大支撑区 | bearish | major_breakdown_below_support_pct |
| structure_minor_breakout_up | 当前是否收盘突破 4h 小压力区 | bullish | minor_breakout_above_resistance_pct |
| structure_minor_breakdown_down | 当前是否收盘跌破 4h 小支撑区 | bearish | minor_breakdown_below_support_pct |

判断口径：

```text
major_breakout_up = major_breakout_above_resistance_pct >= 0.008
major_breakdown_down = major_breakdown_below_support_pct >= 0.008
minor_breakout_up = minor_breakout_above_resistance_pct >= 0.004
minor_breakdown_down = minor_breakdown_below_support_pct >= 0.004
```

突破 / 跌破只表示结构事实，不表示方向性交易处理、止损、仓位退出或方向反转处理。

### 8.6 无明确结构原子信号

| SignalCode | 业务问题 | 默认方向 | 必需 FeatureValue |
|---|---|---|---|
| structure_major_unclear | 1d 大结构是否缺少可用支撑或压力 | neutral | major support / resistance 相关特征 |
| structure_minor_unclear | 4h 小结构是否缺少可用支撑或压力 | neutral | minor support / resistance 相关特征 |

判断口径：

```text
support zone 缺失；
或 resistance zone 缺失；
或 support_upper >= resistance_lower；
或 range_width_pct 为空。
```

`unclear` 不是看多或看空，也不是交易阻断。下游应把它当作结构证据不足。

## 9. null 处理

如果必需 FeatureValue 为 null：

```text
位置类、突破类、区间类原子信号 = created / is_valid=true / value_bool=false；
unclear 类原子信号 = created / is_valid=true / value_bool=true；
```

如果 FeatureValue 本身 failed：

```text
对应 AtomicSignalValue 必须 failed。
```

不得把 null 当成 0。

不得因为没有有效支撑压力区就默认认为突破、跌破、靠近支撑或靠近压力成立。

## 10. 与 DomainSignal 的关系

Structure AtomicSignal 只输出最小结构判断。

DomainSignal.structure 才负责：

```text
把 1d 大结构原子信号聚合为 major_structure；
把 4h 小结构原子信号聚合为 minor_structure；
保留两套结构事实；
形成结构领域摘要。
```

AtomicSignal 不得自己综合 1d 与 4h。

例如：

```text
1d 靠近大支撑 + 4h 跌破小支撑
```

原子层只能分别输出两条事实，不得得出“应当维持处理”“应当形成交易目标”或“大结构未破但短线走弱”这种综合结论。

## 11. 与 StrategyAnalysisRelease 的关系

正式运行只允许消费：

```text
被当前 StrategyAnalysisRelease 原子信号切片明确选中；
状态 active；
enabled = true；
依赖 FeatureDefinition 完整；
恰好归属于 structure DomainSignalDefinition；
calculator 已注册；
算法 requirements 与 implementation 记录完整；
验证证据完整。
```

没有被版本包选择的 Structure AtomicSignalDefinition，即使已经 active，也不得进入正式 AtomicSignalSet。

## 12. 测试要求

至少覆盖：

```text
靠近 1d 大支撑但不靠近 4h 小支撑；
靠近 4h 小支撑但不靠近 1d 大支撑；
4h 小支撑跌破但 1d 大支撑未跌破；
1d 大压力突破；
4h 小压力突破；
支撑或压力缺失时 unclear 成立；
FeatureValue failed 时原子信号 failed；
null 不被当成 0；
突破判断使用 FeatureLayer 已排除当前 K 线的参考区；
evidence_text_zh 不包含交易建议。
```

## 13. 明确禁止

禁止：

```text
让 AtomicSignal 读取 Kline；
让 AtomicSignal 调用支撑压力算法；
让 AtomicSignal 重新计算支撑压力区；
让 AtomicSignal 把 1d 与 4h 强行合并；
让 AtomicSignal 输出支撑、压力或跌破结构下的交易处理；
让 AtomicSignal 输出 target_position_ratio；
让 AtomicSignal 生成订单意图；
让 AtomicSignal 访问 Binance、DeepSeek、账户或 PriceSnapshot；
绕过 StrategyAnalysisRelease 直接启用候选结构原子信号。
```
