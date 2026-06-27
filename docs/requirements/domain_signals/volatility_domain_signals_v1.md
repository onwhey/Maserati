# Volatility Domain Signals

## 1. 文件定位

本文档定义 `volatility` 领域的第一版领域聚合规则。

它消费 [Volatility Atomic Signals](../atomic_signals/volatility_atomic_signals.md) 产生的 AtomicSignalValue，生成一份 `volatility` DomainSignalValue。

本文档回答：

```text
当前波动状态是低波动、正常波动、高波动、极高波动，还是低波动压缩；
当前波动是否正在短周期扩张；
最近一根 K 线是否出现大振幅、实体主导或影线主导；
当前波动领域结论用了哪些原子信号；
人工如何复核波动领域判断是否跑偏。
```

本文档不负责：

```text
判断趋势方向；
判断动能强弱；
判断支撑压力；
判断异常行情是否应阻断交易；
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

Volatility DomainSignal 只能读取同一 AtomicSignalSet 中、归属于 `volatility` 领域、且被当前 StrategyAnalysisRelease 选中的 AtomicSignalValue。

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

如果需要新的波动原子证据，必须先修改 AtomicSignal requirements；如果需要新的基础数值，必须先修改 FeatureLayer requirements。

## 3. 输出模式

本版本 `volatility` 使用非方向性状态输出模式：

```text
direction = neutral；
state_code = 当前主要波动状态；
strength = 当前主要波动状态的强烈程度；
coverage_ratio = 已获得的有效原子证据覆盖程度；
agreement_ratio = 0；
payload_summary = 承载波动分组计数、状态标签和复核摘要。
```

`volatility` 领域只输出一份 DomainSignalValue。

不得分别输出“多头波动领域值”“空头波动领域值”。

波动领域没有多空方向，因此：

```text
direction 必须为 neutral；
agreement_ratio 固定为 0；
不得把高波动解释成看多或看空；
不得把低波动解释成即将突破；
不得把波动扩张解释成应该追单；
不得把单根大振幅解释成交易阻断。
```

如果下游需要判断异常波动是否降低信号可靠性，应由 `risk_state` 或更下游模块在自身边界内完成。

## 4. 原子信号分组

### 4.1 低波动证据

以下原子信号成立时，计入低波动证据：

```text
volatility_1d_atr_low_percentile
volatility_4h_atr_low_percentile
volatility_4h_realized_vol_low_percentile
volatility_4h_compression
volatility_1d_range_narrow
volatility_4h_range_narrow
```

低波动证据只说明市场波动相对收缩，不说明应该退出、等待突破或降低仓位。

### 4.2 高波动证据

以下原子信号成立时，计入高波动证据：

```text
volatility_1d_atr_high_percentile
volatility_4h_atr_high_percentile
volatility_4h_realized_vol_high_percentile
volatility_4h_expansion
volatility_1d_range_wide
volatility_4h_range_wide
```

高波动证据只说明市场波动相对放大，不说明应该追单、减仓或停止交易。

### 4.3 极高波动证据

以下原子信号成立时，计入极高波动证据：

```text
volatility_1d_atr_extreme_percentile
volatility_4h_atr_extreme_percentile
volatility_1d_latest_candle_range_large
volatility_4h_latest_candle_range_large
volatility_4h_latest_large_body
```

极高波动证据只说明波动状态异常强烈，不直接输出风险阻断结论。

### 4.4 K 线形态状态标签

以下原子信号不单独决定主要波动状态，只进入 `state_tags` 和 `payload_summary`：

```text
volatility_4h_latest_upper_shadow_dominant
volatility_4h_latest_lower_shadow_dominant
```

上影线或下影线主导只描述最新 4h K 线形态事实。

不得在 volatility 领域直接解释为反转、诱多、诱空、插针风险或追单风险。

## 5. 参数

本版本使用以下固定参数：

| 参数 | 值 | 说明 |
|---|---:|---|
| 最小覆盖率 | 0.70 | 至少 70% 被选中 volatility 原子信号有效，领域才可用 |
| 低波动最少证据数 | 2 | 低波动证据至少 2 项成立，才形成低波动状态 |
| 高波动最少证据数 | 2 | 高波动证据至少 2 项成立，才形成高波动状态 |
| 极高波动最少证据数 | 1 | 任一极高波动证据成立，即优先形成极高波动状态 |
| 强状态证据归一分母 | 4 | 低波动 / 高波动 strength 使用该分母归一 |

这些参数属于本算法版本的一部分。

后续如果调整覆盖率、证据分组、状态优先级、状态阈值或 strength 计算方式，必须新增算法版本。

## 6. 计算流程

### 6.1 收集输入

从同一 AtomicSignalSet 中读取当前版本包选中的 volatility 原子信号。

只允许使用：

```text
status = created；
is_valid = true；
definition_status = active；
definition_enabled = true。
```

failed 或 invalid 原子信号不参与状态计数，但必须计入 coverage_ratio。

### 6.2 计算 coverage_ratio

```text
coverage_ratio = 有效 volatility 原子信号数量 / 当前版本包选中的 volatility 原子信号数量
```

如果被选中的 volatility 原子信号数量为 0，领域计算失败。

如果 `coverage_ratio < 0.70`：

```text
DomainSignalValue.status = failed
is_valid = false
direction = none
state_code = ""
strength = 0
error_code = volatility_coverage_too_low
```

### 6.3 计算证据计数

只统计有效且条件成立的原子信号。

```text
low_volatility_count = 成立的低波动证据数量
high_volatility_count = 成立的高波动证据数量
extreme_volatility_count = 成立的极高波动证据数量
shape_tag_count = 成立的 K 线形态标签数量
```

同时记录：

```text
compression_active = volatility_4h_compression 是否成立
expansion_active = volatility_4h_expansion 是否成立
upper_shadow_dominant = volatility_4h_latest_upper_shadow_dominant 是否成立
lower_shadow_dominant = volatility_4h_latest_lower_shadow_dominant 是否成立
```

### 6.4 状态优先级

本版本按以下优先级确定 `state_code`：

| 优先级 | 条件 | state_code |
|---:|---|---|
| 1 | `extreme_volatility_count >= 1` | `volatility_extreme` |
| 2 | `high_volatility_count >= 2` 且 `low_volatility_count < 2` | `volatility_high` |
| 3 | `low_volatility_count >= 2` 且 `high_volatility_count < 2` 且 `compression_active = true` | `volatility_low_compression` |
| 4 | `low_volatility_count >= 2` 且 `high_volatility_count < 2` | `volatility_low` |
| 5 | `low_volatility_count >= 2` 且 `high_volatility_count >= 2` | `volatility_mixed` |
| 6 | 其他情况 | `volatility_normal` |

极高波动优先级最高。

如果极高波动证据成立，即使同时存在低波动证据，本轮主要状态仍为 `volatility_extreme`，并在 `state_tags` 中记录冲突或混合状态。

### 6.5 计算 direction

`volatility` 领域没有多空方向：

```text
direction = neutral
```

无论低波动、高波动、极高波动还是混合状态，direction 都不得变为 bullish 或 bearish。

### 6.6 计算 strength

`strength` 表示当前主要波动状态的强烈程度，不表示盈利概率、仓位比例、交易规模或策略置信度。

如果 `state_code = volatility_extreme`：

```text
strength = 1
```

如果 `state_code = volatility_high`：

```text
strength = min(1, high_volatility_count / 4)
```

如果 `state_code = volatility_low_compression` 或 `volatility_low`：

```text
strength = min(1, low_volatility_count / 4)
```

如果 `state_code = volatility_mixed`：

```text
strength = min(1, max(low_volatility_count, high_volatility_count) / 4)
```

如果 `state_code = volatility_normal`：

```text
strength = 0
```

### 6.7 计算 state_consistency_ratio

由于 volatility 没有多空方向，`agreement_ratio` 固定为 0。

为了便于人工复核，本版本在 `payload_summary` 中输出 `state_consistency_ratio`：

```text
state_consistency_ratio = 主要状态支持证据数量 / 全部成立的低波动、高波动、极高波动证据数量
```

如果没有任何低波动、高波动、极高波动证据成立：

```text
state_consistency_ratio = 0
```

`state_consistency_ratio` 只用于解释波动状态是否集中，不得被当作策略信号置信度。

### 6.8 生成 state_tags

`state_tags` 至少应根据成立事实包含以下标签：

| 成立条件 | state_tags |
|---|---|
| `compression_active = true` | `volatility_compression_active` |
| `expansion_active = true` | `volatility_expansion_active` |
| `upper_shadow_dominant = true` | `latest_4h_upper_shadow_dominant` |
| `lower_shadow_dominant = true` | `latest_4h_lower_shadow_dominant` |
| `low_volatility_count >= 2` 且 `high_volatility_count >= 2` | `volatility_low_high_mixed` |
| `extreme_volatility_count >= 1` 且 `low_volatility_count >= 2` | `volatility_extreme_with_low_volatility_conflict` |

标签只用于解释，不得直接触发交易动作。

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
  "evidence_type": "volatility_domain_aggregation",
  "low_volatility_count": 3,
  "high_volatility_count": 0,
  "extreme_volatility_count": 0,
  "shape_tag_count": 1,
  "compression_active": true,
  "expansion_active": false,
  "state_code": "volatility_low_compression",
  "direction": "neutral",
  "coverage_ratio": "1",
  "agreement_ratio": "0",
  "state_consistency_ratio": "1",
  "strength": "0.75",
  "state_tags": ["volatility_compression_active", "latest_4h_lower_shadow_dominant"],
  "used_atomic_signal_value_ids": [401, 402, 403, 404]
}
```

不得在 `evidence_items` 中复制完整 AtomicSignalValue、完整 FeatureValue 或完整 K 线窗口。

### 7.2 evidence_text_zh

`evidence_text_zh` 必须能让人工快速判断波动领域结论是否跑偏。

低波动压缩示例：

```text
volatility 领域为低波动压缩：低波动证据 3 项成立，高波动证据 0 项，极高波动证据 0 项；其中 4h 短窗口波动低于长窗口波动，说明短周期波动处于压缩状态。该结论只描述波动收缩，不代表即将突破或应该交易。
```

高波动示例：

```text
volatility 领域为高波动：高波动证据 3 项成立，低波动证据 0 项，极高波动证据 0 项；其中 4h ATR 分位较高且短窗口波动扩张，说明当前波动明显放大。该结论不代表应该追单。
```

极高波动示例：

```text
volatility 领域为极高波动：极高波动证据 1 项成立，说明当前波动处于异常强烈状态。是否降低信号质量或阻断交易，应由 risk_state、StrategySignalQuality 或后续模块判断。
```

混合状态示例：

```text
volatility 领域为混合：低波动证据 2 项成立，高波动证据 2 项成立，说明不同波动维度之间存在分歧，需下游结合 trend、momentum 和 structure 综合判断。
```

失败示例：

```text
volatility 领域计算失败：有效原子证据覆盖率 0.56，低于最低要求 0.70。
```

不得写交易建议。

## 8. payload_summary

`payload_summary` 至少包含：

```json
{
  "low_volatility_count": 3,
  "high_volatility_count": 0,
  "extreme_volatility_count": 0,
  "shape_tag_count": 1,
  "compression_active": true,
  "expansion_active": false,
  "upper_shadow_dominant": false,
  "lower_shadow_dominant": true,
  "primary_volatility_state": "low_compression",
  "state_consistency_ratio": "1",
  "state_tags": ["volatility_compression_active", "latest_4h_lower_shadow_dominant"],
  "failed_atomic_count": 0,
  "valid_atomic_count": 19,
  "selected_atomic_count": 19
}
```

`payload_summary` 是摘要，不得复制完整证据链。

完整追溯必须通过 `used_atomic_signal_value_ids` 回查 AtomicSignalValue，再通过 `used_feature_value_ids` 回查 FeatureValue。

## 9. 与 risk_state 的边界

Volatility DomainSignal 只描述波动状态。

它可以输出：

```text
volatility_low；
volatility_low_compression；
volatility_normal；
volatility_high；
volatility_extreme；
volatility_mixed。
```

但不得输出：

```text
插针风险；
急跌风险；
急涨追高风险；
突破信号不可靠；
反弹信号不可靠；
必须降低策略质量；
必须阻断交易；
必须退出持仓。
```

这些属于 `risk_state`、StrategySignalQuality、RiskCheck 或更下游模块的职责。

## 10. 与 MarketRegime 的边界

MarketRegime 可以综合 volatility 与其他领域，识别更完整的市场环境。

例如：

```text
market_context = 大级别偏多；
trend = 1d 偏多，4h 回调；
momentum = 1d 多头动能衰竭；
volatility = 高波动；
structure = 高位区间有效，当前靠近支撑；
risk_state = 无异常风险。
```

MarketRegime 才可以形成：

```text
大级别偏多下的高位宽幅区间震荡，当前靠近支撑。
```

Volatility DomainSignal 不得单独承担上述综合结论。

Volatility DomainSignal 也不得把低波动压缩直接解释成“趋势中继整理”，不得把高波动直接解释成“宽幅震荡”，不得把极高波动直接解释成“不交易”。

## 11. 人工复核视角

后台或复盘展示 volatility 领域结果时，至少应展示：

```text
主要波动状态；
低波动证据数量；
高波动证据数量；
极高波动证据数量；
4h 是否波动压缩；
4h 是否波动扩张；
最新 4h 是否上影线主导；
最新 4h 是否下影线主导；
覆盖率；
状态集中度；
中文解释；
使用的原子信号列表。
```

人工应能从这些信息判断：

```text
系统是否把当前波动状态看成低波动、正常、高波动或极高波动；
系统是否把短周期波动压缩或扩张识别出来；
系统是否把最新 K 线大振幅或影线状态纳入解释；
系统是否错误地把波动状态当作多空方向；
系统是否错误地把波动状态当作交易建议。
```

## 12. 验收规则

### 12.1 低波动压缩

如果以下条件同时满足：

```text
低波动证据数量 >= 2；
高波动证据数量 < 2；
volatility_4h_compression 成立；
coverage_ratio >= 0.70。
```

则：

```text
direction = neutral
state_code = volatility_low_compression
strength > 0
payload_summary.compression_active = true
```

不得输出“即将突破”。

### 12.2 高波动

如果以下条件同时满足：

```text
高波动证据数量 >= 2；
低波动证据数量 < 2；
极高波动证据数量 = 0；
coverage_ratio >= 0.70。
```

则：

```text
direction = neutral
state_code = volatility_high
strength > 0
```

不得输出“应该追单”或“应该减仓”。

### 12.3 极高波动

如果以下条件满足：

```text
极高波动证据数量 >= 1；
coverage_ratio >= 0.70。
```

则：

```text
direction = neutral
state_code = volatility_extreme
strength = 1
```

不得直接输出“交易阻断”。

### 12.4 混合状态

如果以下条件同时满足：

```text
低波动证据数量 >= 2；
高波动证据数量 >= 2；
极高波动证据数量 = 0；
coverage_ratio >= 0.70。
```

则：

```text
direction = neutral
state_code = volatility_mixed
state_tags 包含 volatility_low_high_mixed
```

不得强行解释为低波动或高波动。

### 12.5 覆盖率不足

如果有效 volatility 原子信号覆盖率低于 0.70：

```text
DomainSignalValue.status = failed
is_valid = false
direction = none
strength = 0
error_code = volatility_coverage_too_low
```

不得生成可被 MarketRegime 消费的有效领域值。

## 13. 本版本明确不处理

本版本不处理：

```text
3d 波动；
1w 波动；
布林带宽度；
Keltner Channel；
GARCH；
隐含波动率；
盘口价差；
深度数据；
资金费率；
连续大振幅 K 线数量；
低波动压缩后的方向性启动；
波动扩张后的方向性跟随；
插针风险；
急涨风险；
急跌风险；
异常行情交易阻断；
策略信号质量降权；
概率置信度校准；
机器学习波动分类。
```

这些能力如需加入，必须新增算法需求文件或新增算法版本。
