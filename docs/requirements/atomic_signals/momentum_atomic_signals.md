# Momentum Atomic Signals

## 1. 文件定位

本文档定义 `momentum` 领域的第一批原子信号。

这些原子信号基于 [Momentum Features](../feature_layer/momentum_features.md) 输出的动能特征，形成最小动能判断。

本文档回答：

```text
1d 当前是否存在多头或空头推进；
1d 推进是在增强还是衰竭；
4h 当前是否存在多头或空头推进；
4h 推进是在增强还是衰竭；
当前推进是否连续、顺畅；
当前收盘是否偏强或偏弱；
每个判断使用哪些 FeatureValue；
每个判断为什么成立或不成立；
下游如何追溯判断依据。
```

本文档不负责：

```text
判断完整动能领域结论；
综合 1d 与 4h 形成动能状态；
判断趋势方向；
判断大级别牛市或熊市；
判断支撑压力；
判断波动是否异常；
识别 MarketRegime；
选择策略；
生成 StrategySignal；
生成 DecisionSnapshot；
读取账户或持仓；
请求 Binance；
执行真实交易。
```

本文档不是一个整体算法版本。本文档中的每个 AtomicSignalDefinition 独立版本化，单个原子信号算法升级时，只新增或切换该 AtomicSignalDefinition 的版本，不要求整份 momentum 原子信号清单整体升级。

## 2. 设计原则

Momentum 原子信号必须保持简单。

每个原子信号只回答一个明确问题：

```text
某个动能条件是否成立？
```

例如：

```text
1d 是否存在明显多头推进；
1d 多头推进是否增强；
1d 多头推进是否衰竭；
4h 是否存在明显空头推进；
4h 空头推进是否增强；
4h 收盘是否偏强；
当前推进效率是否较低。
```

原子信号不得直接输出：

```text
动能偏多且增强；
动能偏多但衰竭；
动能偏空且增强；
动能偏空但衰竭；
多空动能冲突；
上涨趋势中的正常回调；
下跌趋势中的反弹；
突破质量良好；
突破质量不足；
策略名称；
目标仓位；
订单动作。
```

这些结论必须由 DomainSignal、MarketRegime、StrategyRouting 或 StrategySignal 在各自职责内完成。

## 3. 输入要求

本文件只允许读取同一个 FeatureSet 内的 FeatureValue。

FeatureLayer 是 momentum 特征的数据工厂，负责计算并落库 `momentum_features.md` 定义的 FeatureValue。

Momentum AtomicSignal 是数据用户，只读取这些已经落库的 FeatureValue，不调用 FeatureLayer calculator，不调用收益率、连续性、推进效率或收盘位置算法。

多个 Momentum 原子信号依赖同一个特征时，必须引用同一个 FeatureSet 内同一份 FeatureValue。

输入 FeatureValue 必须来自：

```text
docs/requirements/feature_layer/momentum_features.md
```

不得读取：

```text
Kline；
MarketSnapshot 原始 K 线；
FeatureLayer calculator；
收益率、连续上涨、连续下跌、推进效率或收盘位置算法函数；
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

当前 Momentum 原子信号只使用：

```text
1d 已收盘 K 线生成的 momentum FeatureValue；
4h 已收盘 K 线生成的 momentum FeatureValue。
```

职责划分：

```text
1d 原子信号 = 日线级动能事实；
4h 原子信号 = 短周期动能事实。
```

4h 使用 MarketSnapshot 冻结的完整 4h 窗口，不是只看日线收盘之后的几根 4h，也不是盘中实时判断。

当前不引入 3d、1w、MACD、RSI、ADX 或成交量原子信号。

如果未来要引入经典指标原子信号，必须先补齐对应 FeatureDefinition，AtomicSignal 仍只能读取对应 FeatureValue。

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

当前清单中的 Momentum 原子信号默认：

```text
confidence = null
```

原因是这些信号只是确定性条件判断，尚未经过样本外概率校准。

不得因为计算成功就把 `confidence` 写成 1。

### 5.3 direction 语义

`bullish` 表示该条件支持“多头动能事实”。

`bearish` 表示该条件支持“空头动能事实”。

`neutral` 表示该条件只表达状态、衰竭、混乱或条件不成立，不直接给出方向。

这些方向不是交易动作，不得解释为方向性交易处理、交易进入动作、仓位调整或仓位退出。

衰竭类原子信号默认使用 `neutral`，并通过 `state_label` 或 evidence 说明它削弱的是多头推进还是空头推进，避免把“多头衰竭”误写成“直接看空”。

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
  "evidence_type": "momentum_atomic_condition",
  "signal_code": "momentum_1d_bullish_push_strengthening",
  "condition_result": true,
  "used_features": [
    {
      "feature_code": "return_pct_1d_7",
      "feature_value_id": 123,
      "observed_value": "0.064"
    },
    {
      "feature_code": "return_delta_pct_1d_7",
      "feature_value_id": 124,
      "observed_value": "0.021"
    }
  ],
  "thresholds": {
    "min_return_pct": "0.03",
    "min_return_delta_pct": "0.015"
  },
  "supporting_facts": [
    "最近 7 根 1d 收盘价上涨 6.4%。",
    "最近 7 日收益率比前 7 日高 2.1%。"
  ],
  "weakening_facts": [],
  "calculation_summary": "return_pct_1d_7 >= 0.03 AND return_delta_pct_1d_7 >= 0.015"
}
```

`evidence_items` 只保存摘要和引用，不得复制完整 FeatureValue、完整 K 线窗口或大批量历史数组。

### 6.2 evidence_text_zh 结构

`evidence_text_zh` 必须是中文短句，面向人工复核可读。

示例：

```text
最近 7 根 1d 收盘价上涨 6.4%，且最近 7 日收益率比前 7 日高 2.1%，因此“1d 多头推进增强”成立。
```

如果条件不成立，也必须说明原因：

```text
最近 7 根 1d 收盘价上涨 1.2%，未达到 3% 最小推进阈值，因此“1d 多头推进存在”不成立。
```

不得在 `evidence_text_zh` 中写交易建议。

## 7. 固定参数

本文档列出的初始 AtomicSignalDefinition 使用以下参数约定：

| 参数 | 值 | 用途 |
|---|---:|---|
| 1d 最小推进阈值 | 0.03 | 最近 7 根 1d 收益率超过 3% 才认为日线推进明显 |
| 4h 最小推进阈值 | 0.02 | 最近 24 根 4h 收益率超过 2% 才认为短周期推进明显 |
| 1d 推进变化阈值 | 0.015 | 当前 7 日收益率相对前 7 日变化超过 1.5% 才认为变化明显 |
| 4h 推进变化阈值 | 0.01 | 当前 24 根 4h 收益率相对前 24 根 4h 变化超过 1% 才认为变化明显 |
| 方向 K 线占比阈值 | 0.60 | 上涨或下跌 K 线占比超过 60% 才认为连续性较好 |
| 1d 连续推进根数 | 3 | 最近 7 根 1d 中最新连续 3 根同向，认为短段连续推进 |
| 4h 连续推进根数 | 4 | 最近 24 根 4h 中最新连续 4 根同向，认为短段连续推进 |
| 高推进效率阈值 | 0.55 | 推进效率超过 0.55 认为推进较顺畅 |
| 低推进效率阈值 | 0.30 | 推进效率低于 0.30 认为拉扯严重 |
| 强收盘阈值 | 0.65 | 收盘位置高于 0.65 认为收盘偏强 |
| 弱收盘阈值 | 0.35 | 收盘位置低于 0.35 认为收盘偏弱 |

这些参数必须写入对应 AtomicSignalDefinition 的 params / params_hash，并属于对应原子信号算法版本的一部分。

后续如果只调整某一个原子信号的阈值、条件、默认方向或证据结构，只能新增该 AtomicSignalDefinition 的算法版本，不得静默修改历史 AtomicSignalValue 的含义，也不得要求无关原子信号同步升级。

## 8. 原子信号清单

### 8.1 1d 净推进存在

| signal_code | 问题 | 默认方向 | 依赖特征 | 条件 |
|---|---|---|---|---|
| `momentum_1d_bullish_push_exists` | 1d 是否存在明显多头推进 | bullish | `return_pct_1d_7` | `return_pct_1d_7 >= 0.03` |
| `momentum_1d_bearish_push_exists` | 1d 是否存在明显空头推进 | bearish | `return_pct_1d_7` | `return_pct_1d_7 <= -0.03` |

这些信号只表达最近 7 根 1d 的净推进方向和幅度，不单独定义完整动能领域结论。

不成立不代表反向条件成立，反向条件必须由对应的反向信号单独判断。

### 8.2 1d 推进增强

| signal_code | 问题 | 默认方向 | 依赖特征 | 条件 |
|---|---|---|---|---|
| `momentum_1d_bullish_push_strengthening` | 1d 多头推进是否增强 | bullish | `return_pct_1d_7` / `return_delta_pct_1d_7` | `return_pct_1d_7 >= 0.03` 且 `return_delta_pct_1d_7 >= 0.015` |
| `momentum_1d_bearish_push_strengthening` | 1d 空头推进是否增强 | bearish | `return_pct_1d_7` / `return_delta_pct_1d_7` | `return_pct_1d_7 <= -0.03` 且 `return_delta_pct_1d_7 <= -0.015` |

多头推进增强表示上涨窗口仍为正，且当前窗口比前一窗口更强。

空头推进增强表示下跌窗口仍为负，且当前窗口比前一窗口更弱。

这里的增强不是交易动作，不等于加仓或追单。

### 8.3 1d 推进衰竭

| signal_code | 问题 | 默认方向 | 依赖特征 | 条件 |
|---|---|---|---|---|
| `momentum_1d_bullish_push_exhausting` | 1d 多头推进是否衰竭 | neutral | `return_pct_1d_7` / `return_delta_pct_1d_7` | `return_pct_1d_7 >= 0.03` 且 `return_delta_pct_1d_7 <= -0.015` |
| `momentum_1d_bearish_push_exhausting` | 1d 空头推进是否衰竭 | neutral | `return_pct_1d_7` / `return_delta_pct_1d_7` | `return_pct_1d_7 <= -0.03` 且 `return_delta_pct_1d_7 >= 0.015` |

多头推进衰竭表示价格仍在上涨，但当前上涨速度相对前一窗口明显减弱。

空头推进衰竭表示价格仍在下跌，但当前下跌速度相对前一窗口明显减弱。

衰竭类信号只削弱原方向的动能证据，不直接生成反向方向。

### 8.4 1d 推进连续性

| signal_code | 问题 | 默认方向 | 依赖特征 | 条件 |
|---|---|---|---|---|
| `momentum_1d_bullish_continuity_good` | 1d 上涨连续性是否较好 | bullish | `up_bar_ratio_1d_7` / `consecutive_up_count_1d_7` | `up_bar_ratio_1d_7 >= 0.60` 或 `consecutive_up_count_1d_7 >= 3` |
| `momentum_1d_bearish_continuity_good` | 1d 下跌连续性是否较好 | bearish | `down_bar_ratio_1d_7` / `consecutive_down_count_1d_7` | `down_bar_ratio_1d_7 >= 0.60` 或 `consecutive_down_count_1d_7 >= 3` |

连续性较好只表示窗口内推进更连贯。

它不等于趋势成立，也不等于适合追单。

### 8.5 1d 推进效率

| signal_code | 问题 | 默认方向 | 依赖特征 | 条件 |
|---|---|---|---|---|
| `momentum_1d_movement_efficiency_high` | 1d 推进是否较顺畅 | neutral | `movement_efficiency_1d_7` | `movement_efficiency_1d_7 >= 0.55` |
| `momentum_1d_movement_efficiency_low` | 1d 推进是否拉扯严重 | neutral | `movement_efficiency_1d_7` | `movement_efficiency_1d_7 <= 0.30` |

推进效率不表达方向。

DomainSignal 必须结合净推进方向，才能解释“高效率上涨”或“高效率下跌”。

### 8.6 1d 收盘强弱

| signal_code | 问题 | 默认方向 | 依赖特征 | 条件 |
|---|---|---|---|---|
| `momentum_1d_close_strength_bullish` | 1d 收盘是否偏强 | bullish | `close_location_avg_pct_1d_3` | `close_location_avg_pct_1d_3 >= 0.65` |
| `momentum_1d_close_strength_bearish` | 1d 收盘是否偏弱 | bearish | `close_location_avg_pct_1d_3` | `close_location_avg_pct_1d_3 <= 0.35` |

收盘偏强或偏弱只表达最近几根 K 线最后力量归属，不表达突破、支撑压力或订单动作。

### 8.7 4h 净推进存在

| signal_code | 问题 | 默认方向 | 依赖特征 | 条件 |
|---|---|---|---|---|
| `momentum_4h_bullish_push_exists` | 4h 是否存在明显多头推进 | bullish | `return_pct_4h_24` | `return_pct_4h_24 >= 0.02` |
| `momentum_4h_bearish_push_exists` | 4h 是否存在明显空头推进 | bearish | `return_pct_4h_24` | `return_pct_4h_24 <= -0.02` |

这些信号只表达最近 24 根 4h 的净推进方向和幅度。

### 8.8 4h 推进增强

| signal_code | 问题 | 默认方向 | 依赖特征 | 条件 |
|---|---|---|---|---|
| `momentum_4h_bullish_push_strengthening` | 4h 多头推进是否增强 | bullish | `return_pct_4h_24` / `return_delta_pct_4h_24` | `return_pct_4h_24 >= 0.02` 且 `return_delta_pct_4h_24 >= 0.01` |
| `momentum_4h_bearish_push_strengthening` | 4h 空头推进是否增强 | bearish | `return_pct_4h_24` / `return_delta_pct_4h_24` | `return_pct_4h_24 <= -0.02` 且 `return_delta_pct_4h_24 <= -0.01` |

4h 推进增强只表达短周期推动力增强。

它不改变 1d 趋势主方向，也不直接决定交易动作。

### 8.9 4h 推进衰竭

| signal_code | 问题 | 默认方向 | 依赖特征 | 条件 |
|---|---|---|---|---|
| `momentum_4h_bullish_push_exhausting` | 4h 多头推进是否衰竭 | neutral | `return_pct_4h_24` / `return_delta_pct_4h_24` | `return_pct_4h_24 >= 0.02` 且 `return_delta_pct_4h_24 <= -0.01` |
| `momentum_4h_bearish_push_exhausting` | 4h 空头推进是否衰竭 | neutral | `return_pct_4h_24` / `return_delta_pct_4h_24` | `return_pct_4h_24 <= -0.02` 且 `return_delta_pct_4h_24 >= 0.01` |

4h 衰竭类信号只说明短周期原方向推动力下降。

它不得被直接解释为反向交易信号。

### 8.10 4h 推进连续性

| signal_code | 问题 | 默认方向 | 依赖特征 | 条件 |
|---|---|---|---|---|
| `momentum_4h_bullish_continuity_good` | 4h 上涨连续性是否较好 | bullish | `up_bar_ratio_4h_24` / `consecutive_up_count_4h_24` | `up_bar_ratio_4h_24 >= 0.60` 或 `consecutive_up_count_4h_24 >= 4` |
| `momentum_4h_bearish_continuity_good` | 4h 下跌连续性是否较好 | bearish | `down_bar_ratio_4h_24` / `consecutive_down_count_4h_24` | `down_bar_ratio_4h_24 >= 0.60` 或 `consecutive_down_count_4h_24 >= 4` |

4h 连续性较好只表达短周期推进更连贯。

### 8.11 4h 推进效率

| signal_code | 问题 | 默认方向 | 依赖特征 | 条件 |
|---|---|---|---|---|
| `momentum_4h_movement_efficiency_high` | 4h 推进是否较顺畅 | neutral | `movement_efficiency_4h_24` | `movement_efficiency_4h_24 >= 0.55` |
| `momentum_4h_movement_efficiency_low` | 4h 推进是否拉扯严重 | neutral | `movement_efficiency_4h_24` | `movement_efficiency_4h_24 <= 0.30` |

4h 推进效率不表达方向。

### 8.12 4h 收盘强弱

| signal_code | 问题 | 默认方向 | 依赖特征 | 条件 |
|---|---|---|---|---|
| `momentum_4h_close_strength_bullish` | 4h 收盘是否偏强 | bullish | `close_location_avg_pct_4h_12` | `close_location_avg_pct_4h_12 >= 0.65` |
| `momentum_4h_close_strength_bearish` | 4h 收盘是否偏弱 | bearish | `close_location_avg_pct_4h_12` | `close_location_avg_pct_4h_12 <= 0.35` |

4h 收盘偏强或偏弱只表达短周期 K 线最后力量归属。

## 9. 与 DomainSignal 的关系

这些原子信号必须归属于 `momentum` 领域。

DomainSignal 可以把这些原子信号综合为领域级事实，例如：

```text
日线多头动能增强；
日线多头动能衰竭；
日线空头动能增强；
日线空头动能衰竭；
短周期多头动能增强；
短周期多头动能衰竭；
短周期空头动能增强；
短周期空头动能衰竭；
多空动能冲突；
动能不明确。
```

这些综合结论不在原子层重复计算。

原子层不单独定义“动能偏多且增强 / 动能偏多但衰竭 / 动能偏空且增强 / 动能偏空但衰竭”信号，避免重复编写领域聚合规则。

## 10. 与 MarketRegime 的关系

MarketRegime 可以在接收 `market_context`、`trend`、`momentum`、`volatility`、`structure` 和 `risk_state` 领域事实后，识别更完整的市场环境。

例如：

```text
market_context 显示大级别偏多；
trend 显示 1d 偏多但 4h 回调；
momentum 显示 1d 多头动能衰竭，但 4h 短周期多头动能恢复；
structure 显示当前靠近支撑区；

MarketRegime 才可以形成“大级别偏多背景下，1d 上升趋势中的支撑区附近回调修复”之类的环境结论。
```

Momentum 原子信号不得单独承担上述结论。

## 11. 人工复核视角

后台或复盘展示一轮策略分析结果时，至少应能从 Momentum 原子信号看到：

```text
1d 最近 7 根 K 线是否明显上涨或下跌；
1d 当前窗口相对前一窗口是否增强或减弱；
1d 上涨或下跌连续性是否较好；
1d 推进效率是否较高或较低；
1d 收盘是否偏强或偏弱；
4h 最近 24 根 K 线是否明显上涨或下跌；
4h 当前窗口相对前一窗口是否增强或减弱；
4h 上涨或下跌连续性是否较好；
4h 推进效率是否较高或较低；
4h 收盘是否偏强或偏弱。
```

这些内容用于帮助人工判断系统是否正确理解当前推动力，而不是用于人工喊单。

## 12. 验收规则

### 12.1 1d 多头推进增强样例

如果最近 7 根 1d 明显上涨，且当前 7 日收益率高于前 7 日：

```text
momentum_1d_bullish_push_exists 应成立；
momentum_1d_bullish_push_strengthening 应成立；
如果上涨 K 线占比高或最新连续上涨数量达标，momentum_1d_bullish_continuity_good 应成立；
如果推进效率高，momentum_1d_movement_efficiency_high 应成立；
对应 1d 空头推进信号不应成立。
```

### 12.2 1d 多头推进衰竭样例

如果最近 7 根 1d 仍然上涨，但当前 7 日收益率明显低于前 7 日：

```text
momentum_1d_bullish_push_exists 可以成立；
momentum_1d_bullish_push_exhausting 应成立；
momentum_1d_bullish_push_strengthening 不应成立；
原子层不得直接输出“多头动能衰竭”作为领域结论。
```

“多头动能衰竭”必须由 Momentum DomainSignal 综合判断。

### 12.3 4h 空头推进增强样例

如果最近 24 根 4h 明显下跌，且当前 24 根 4h 收益率比前 24 根 4h 更弱：

```text
momentum_4h_bearish_push_exists 应成立；
momentum_4h_bearish_push_strengthening 应成立；
如果下跌 K 线占比高或最新连续下跌数量达标，momentum_4h_bearish_continuity_good 应成立；
对应 4h 多头推进信号不应成立。
```

### 12.4 4h 下跌但空头衰竭样例

如果最近 24 根 4h 仍然下跌，但跌幅相对前 24 根 4h 明显收窄：

```text
momentum_4h_bearish_push_exists 可以成立；
momentum_4h_bearish_push_exhausting 应成立；
momentum_4h_bearish_push_strengthening 不应成立；
原子层不得直接输出“下跌趋势中的反弹”。
```

“下跌趋势中的反弹”必须由 Trend DomainSignal 或 MarketRegime 综合判断。

### 12.5 证据验收

每个 AtomicSignalValue 必须满足：

```text
used_feature_value_ids 全部属于同一个 FeatureSet；
evidence_items 能复算 condition_result；
evidence_text_zh 能解释成立或不成立原因；
confidence = null；
不包含交易建议；
不包含完整 K 线窗口；
不包含密钥、账户、订单或外部服务响应。
```

## 13. 当前清单明确不处理

当前 momentum 原子信号清单不处理：

```text
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
急跌后反弹动量不足。
```

这些能力如需加入，必须新增独立特征和原子信号需求文件。

其中“突破伴随动量增强 / 突破但动量不跟随”需要 structure 领域的结构事实配合，不应在 momentum 原子层直接读取 structure 原子信号或领域信号。

## 14. 明确禁止

禁止在 Momentum AtomicSignal 中：

```text
读取 Kline 重新计算动能特征；
调用 FeatureLayer calculator；
自己计算收益率；
自己计算连续上涨或连续下跌；
自己计算推进效率；
自己计算收盘位置；
自己计算 MACD；
自己计算 RSI；
读取其他 AtomicSignalValue；
输出完整 DomainSignal；
输出完整 MarketRegime；
输出 StrategySignal；
输出 target_position_ratio；
生成订单意图；
读取账户、持仓、订单或成交；
读取 PriceSnapshot；
请求 Binance；
调用 DeepSeek；
生成交易建议。
```
