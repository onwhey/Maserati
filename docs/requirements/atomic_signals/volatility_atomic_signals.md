# Volatility Atomic Signals

## 1. 文件定位

本文档定义 `volatility` 领域的第一批原子信号。

这些原子信号基于 [Volatility Features](../feature_layer/volatility_features.md) 输出的波动特征，形成最小波动判断。

本文档回答：

```text
当前波动是否处于低分位、高分位或极高分位；
短周期波动是否压缩或扩张；
最新 K 线振幅是否异常；
最新 4h K 线是否为大实体或影线主导；
行情高低区间是否偏宽或偏窄；
每个判断使用哪些 FeatureValue；
每个判断为什么成立或不成立；
下游如何追溯判断依据。
```

本文档不负责：

```text
判断趋势方向；
判断动能是否增强或衰竭；
判断支撑压力；
判断异常行情是否应阻断交易；
综合多个波动原子信号形成完整 volatility 领域结论；
识别 MarketRegime；
选择策略；
生成 StrategySignal；
生成 DecisionSnapshot；
读取账户或持仓；
请求 Binance；
执行真实交易。
```

本文档不是一个整体算法版本。本文档中的每个 AtomicSignalDefinition 独立版本化，单个原子信号算法升级时，只新增或切换该 AtomicSignalDefinition 的版本，不要求整份 volatility 原子信号清单整体升级。

## 2. 设计原则

Volatility 原子信号必须保持简单。

每个原子信号只回答一个明确问题：

```text
某个波动条件是否成立？
```

例如：

```text
4h ATR 是否处于低分位；
4h ATR 是否处于高分位；
4h 短窗口波动是否低于长窗口波动；
最新 4h K 线振幅是否明显大于常态；
4h 行情高低区间是否偏宽。
```

volatility 原子信号只表达波动状态，不表达多空方向。

因此本文件中的原子信号默认：

```text
direction = neutral
```

原子信号不得直接输出：

```text
交易处理结论；
本轮不形成交易目标；
风险阻断结论；
方向性交易处理；
反方向交易处理；
仓位调整处理；
仓位退出处理；
止损；
止盈；
目标仓位；
订单动作。
```

这些结论必须由 MarketRegime、StrategySignal、StrategySignalQuality、RiskCheck 或后续模块在各自职责内完成。

## 3. 输入要求

本文件只允许读取同一个 FeatureSet 内的 FeatureValue。

FeatureLayer 是 volatility 特征的数据工厂，负责计算并落库 `volatility_features.md` 定义的 FeatureValue。

Volatility AtomicSignal 是数据用户，只读取这些已经落库的 FeatureValue，不调用 FeatureLayer calculator，不调用 ATR、实现波动率、分位、K 线振幅、区间宽度或短长波动比算法。

多个 Volatility 原子信号依赖同一个特征时，必须引用同一个 FeatureSet 内同一份 FeatureValue。

输入 FeatureValue 必须来自：

```text
docs/requirements/feature_layer/volatility_features.md
```

不得读取：

```text
Kline；
MarketSnapshot 原始 K 线；
FeatureLayer calculator；
ATR、实现波动率、分位、K 线振幅、区间宽度或短长波动比算法函数；
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

当前 Volatility 原子信号只使用：

```text
1d 已收盘 K 线生成的 volatility FeatureValue；
4h 已收盘 K 线生成的 volatility FeatureValue。
```

职责划分：

```text
1d 原子信号 = 日线级波动事实；
4h 原子信号 = 短周期波动事实。
```

4h 使用 MarketSnapshot 冻结的完整 4h 窗口，不是盘中实时判断。

当前不引入：

```text
3d；
1w；
布林带；
Keltner Channel；
GARCH；
隐含波动率；
盘口价差；
深度数据；
资金费率。
```

如果未来要引入这些波动原子信号，必须先补齐对应 FeatureDefinition，AtomicSignal 仍只能读取对应 FeatureValue。

## 5. 输出合同

每个原子信号输出 AtomicSignalValue。

### 5.1 成立与不成立

如果条件成立：

```text
status = created
is_valid = true
value_bool = true
direction = neutral
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

当前清单中的 Volatility 原子信号默认：

```text
confidence = null
```

原因是这些信号只是确定性条件判断，尚未经过样本外概率校准。

不得因为计算成功就把 `confidence` 写成 1。

### 5.3 direction 语义

本文件中的原子信号默认 `direction = neutral`。

波动偏高、偏低、压缩、扩张、单根振幅异常都不是多空方向。

不得把：

```text
高波动解释成看空；
低波动解释成看多；
波动压缩解释成即将突破；
波动扩张解释成方向性交易处理；
单根振幅异常解释成风险阻断。
```

这些解释必须交给后续领域综合或策略判断。

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
  "evidence_type": "volatility_atomic_condition",
  "signal_code": "volatility_4h_atr_high_percentile",
  "condition_result": true,
  "used_features": [
    {
      "feature_code": "atr_percentile_4h_120",
      "feature_value_id": 123,
      "observed_value": "0.86"
    }
  ],
  "thresholds": {
    "high_percentile": "0.80"
  },
  "supporting_facts": [
    "当前 4h ATR 百分比处于最近 120 个同类值的 86% 分位。"
  ],
  "weakening_facts": [],
  "calculation_summary": "atr_percentile_4h_120 >= 0.80"
}
```

`evidence_items` 只保存摘要和引用，不得复制完整 FeatureValue、完整 K 线窗口或大批量历史数组。

### 6.2 evidence_text_zh 结构

`evidence_text_zh` 必须是中文短句，面向人工复核可读。

示例：

```text
当前 4h ATR 百分比处于最近 120 个同类值的 86% 分位，超过 80% 阈值，因此“4h ATR 高分位”成立。
```

如果条件不成立，也必须说明原因：

```text
当前 4h ATR 百分比分位为 0.62，未达到 0.80 阈值，因此“4h ATR 高分位”不成立。
```

不得在 `evidence_text_zh` 中写交易建议。

## 7. 固定参数

本文档列出的初始 AtomicSignalDefinition 使用以下参数约定：

| 参数 | 值 | 用途 |
|---|---:|---|
| 低波动分位阈值 | 0.20 | 波动分位低于或等于 20% 认为处于低分位 |
| 高波动分位阈值 | 0.80 | 波动分位高于或等于 80% 认为处于高分位 |
| 极高波动分位阈值 | 0.95 | 波动分位高于或等于 95% 认为处于极高分位 |
| 波动压缩比例阈值 | 0.70 | 短窗口波动低于长窗口 70% 认为存在压缩 |
| 波动扩张比例阈值 | 1.30 | 短窗口波动高于长窗口 130% 认为存在扩张 |
| 单根振幅异常倍数 | 2.00 | 最新 K 线振幅超过 ATR 百分比 2 倍认为单根振幅较大 |
| 大实体占比阈值 | 0.70 | 实体占高低振幅 70% 以上认为实体主导 |
| 影线主导阈值 | 0.60 | 上影线或下影线占高低振幅 60% 以上认为影线主导 |
| 1d 宽区间阈值 | 0.25 | 最近 60 根 1d 高低区间宽度超过 25% 认为偏宽 |
| 1d 窄区间阈值 | 0.10 | 最近 60 根 1d 高低区间宽度低于 10% 认为偏窄 |
| 4h 宽区间阈值 | 0.12 | 最近 120 根 4h 高低区间宽度超过 12% 认为偏宽 |
| 4h 窄区间阈值 | 0.04 | 最近 120 根 4h 高低区间宽度低于 4% 认为偏窄 |

这些参数必须写入对应 AtomicSignalDefinition 的 params / params_hash，并属于对应原子信号算法版本的一部分。

后续如果只调整某一个原子信号的阈值、条件、默认方向或证据结构，只能新增该 AtomicSignalDefinition 的算法版本，不得静默修改历史 AtomicSignalValue 的含义，也不得要求无关原子信号同步升级。

## 8. 原子信号清单

### 8.1 1d ATR 分位

| signal_code | 问题 | 默认方向 | 依赖特征 | 条件 |
|---|---|---|---|---|
| `volatility_1d_atr_low_percentile` | 1d ATR 是否处于低分位 | neutral | `atr_percentile_1d_120` | `atr_percentile_1d_120 <= 0.20` |
| `volatility_1d_atr_high_percentile` | 1d ATR 是否处于高分位 | neutral | `atr_percentile_1d_120` | `atr_percentile_1d_120 >= 0.80` |
| `volatility_1d_atr_extreme_percentile` | 1d ATR 是否处于极高分位 | neutral | `atr_percentile_1d_120` | `atr_percentile_1d_120 >= 0.95` |

这些信号只表达日线级 ATR 分位位置。

### 8.2 4h ATR 分位

| signal_code | 问题 | 默认方向 | 依赖特征 | 条件 |
|---|---|---|---|---|
| `volatility_4h_atr_low_percentile` | 4h ATR 是否处于低分位 | neutral | `atr_percentile_4h_120` | `atr_percentile_4h_120 <= 0.20` |
| `volatility_4h_atr_high_percentile` | 4h ATR 是否处于高分位 | neutral | `atr_percentile_4h_120` | `atr_percentile_4h_120 >= 0.80` |
| `volatility_4h_atr_extreme_percentile` | 4h ATR 是否处于极高分位 | neutral | `atr_percentile_4h_120` | `atr_percentile_4h_120 >= 0.95` |

这些信号只表达短周期 ATR 分位位置。

### 8.3 4h 已实现波动率分位

| signal_code | 问题 | 默认方向 | 依赖特征 | 条件 |
|---|---|---|---|---|
| `volatility_4h_realized_vol_low_percentile` | 4h 已实现波动率是否处于低分位 | neutral | `realized_vol_percentile_4h_120` | `realized_vol_percentile_4h_120 <= 0.20` |
| `volatility_4h_realized_vol_high_percentile` | 4h 已实现波动率是否处于高分位 | neutral | `realized_vol_percentile_4h_120` | `realized_vol_percentile_4h_120 >= 0.80` |

这些信号只表达短周期收盘收益率波动在历史窗口中的位置。

### 8.4 4h 波动压缩 / 扩张

| signal_code | 问题 | 默认方向 | 依赖特征 | 条件 |
|---|---|---|---|---|
| `volatility_4h_compression` | 4h 短窗口波动是否低于长窗口波动 | neutral | `volatility_ratio_4h_20_to_60` | `volatility_ratio_4h_20_to_60 <= 0.70` |
| `volatility_4h_expansion` | 4h 短窗口波动是否高于长窗口波动 | neutral | `volatility_ratio_4h_20_to_60` | `volatility_ratio_4h_20_to_60 >= 1.30` |

波动压缩不等于即将突破。

波动扩张不等于方向性交易处理。

### 8.5 最新 K 线振幅较大

| signal_code | 问题 | 默认方向 | 依赖特征 | 条件 |
|---|---|---|---|---|
| `volatility_1d_latest_candle_range_large` | 最新 1d K 线振幅是否明显大于常态 | neutral | `candle_range_pct_1d_latest` / `atr_pct_1d_14` | `candle_range_pct_1d_latest >= 2.00 * atr_pct_1d_14` |
| `volatility_4h_latest_candle_range_large` | 最新 4h K 线振幅是否明显大于常态 | neutral | `candle_range_pct_4h_latest` / `atr_pct_4h_14` | `candle_range_pct_4h_latest >= 2.00 * atr_pct_4h_14` |

单根振幅较大只表达最新 K 线波动异常放大。

是否构成插针风险、急涨风险或急跌风险，属于 risk_state 判断。

### 8.6 最新 4h K 线实体和影线状态

| signal_code | 问题 | 默认方向 | 依赖特征 | 条件 |
|---|---|---|---|---|
| `volatility_4h_latest_large_body` | 最新 4h K 线是否为实体主导的大波动 K 线 | neutral | `candle_body_ratio_4h_latest` / `candle_range_pct_4h_latest` / `atr_pct_4h_14` | `candle_body_ratio_4h_latest >= 0.70` 且 `candle_range_pct_4h_latest >= atr_pct_4h_14` |
| `volatility_4h_latest_upper_shadow_dominant` | 最新 4h K 线是否上影线主导 | neutral | `upper_shadow_ratio_4h_latest` | `upper_shadow_ratio_4h_latest >= 0.60` |
| `volatility_4h_latest_lower_shadow_dominant` | 最新 4h K 线是否下影线主导 | neutral | `lower_shadow_ratio_4h_latest` | `lower_shadow_ratio_4h_latest >= 0.60` |

实体主导、上影线主导、下影线主导只表达 K 线结构事实。

不得在 volatility 原子层解释为反转、插针、诱多、诱空或风险阻断。

### 8.7 行情高低区间宽度

| signal_code | 问题 | 默认方向 | 依赖特征 | 条件 |
|---|---|---|---|---|
| `volatility_1d_range_wide` | 1d 行情高低区间是否偏宽 | neutral | `range_width_pct_1d_60` | `range_width_pct_1d_60 >= 0.25` |
| `volatility_1d_range_narrow` | 1d 行情高低区间是否偏窄 | neutral | `range_width_pct_1d_60` | `range_width_pct_1d_60 <= 0.10` |
| `volatility_4h_range_wide` | 4h 行情高低区间是否偏宽 | neutral | `range_width_pct_4h_120` | `range_width_pct_4h_120 >= 0.12` |
| `volatility_4h_range_narrow` | 4h 行情高低区间是否偏窄 | neutral | `range_width_pct_4h_120` | `range_width_pct_4h_120 <= 0.04` |

行情高低区间宽度不是支撑压力有效性。

支撑压力区间是否有效属于 structure 领域。

## 9. 与 DomainSignal 的关系

这些原子信号必须归属于 `volatility` 领域。

DomainSignal 可以把这些原子信号综合为领域级事实，例如：

```text
波动低分位；
波动正常；
波动高分位；
波动极高分位；
波动压缩；
波动扩张；
宽幅震荡；
窄幅整理；
单根 K 线振幅异常。
```

这些综合结论不在原子层重复计算。

原子层不单独定义“整体波动状态”，避免重复编写领域聚合规则。

## 10. 与 risk_state 的关系

Volatility 原子信号只描述波动事实。

risk_state 可以使用相同 FeatureValue 或 volatility 领域结果作为后续证据，但 risk_state 的输出语义必须是：

```text
异常行情是否让信号可靠性下降。
```

例如：

```text
volatility_4h_latest_upper_shadow_dominant = 最新 4h 上影线主导；
risk_state 才能判断是否存在插针风险或追涨风险。
```

Volatility 原子信号不得输出 risk_state 结论。

## 11. 与 MarketRegime 的关系

MarketRegime 可以在接收 `market_context`、`trend`、`momentum`、`volatility`、`structure` 和 `risk_state` 领域事实后，识别更完整的市场环境。

例如：

```text
market_context 显示大级别偏多；
trend 显示 1d 偏多但 4h 回调；
momentum 显示 1d 多头动能衰竭；
volatility 显示 4h 宽幅波动；
structure 显示当前处于高低区间中部；

MarketRegime 才可以形成“大级别偏多背景下的宽幅震荡”之类的环境结论。
```

Volatility 原子信号不得单独承担上述结论。

## 12. 人工复核视角

后台或复盘展示一轮策略分析结果时，至少应能从 Volatility 原子信号看到：

```text
1d ATR 分位是否低、高或极高；
4h ATR 分位是否低、高或极高；
4h 已实现波动率分位是否低或高；
4h 波动是否压缩或扩张；
最新 1d / 4h K 线振幅是否明显大于常态；
最新 4h K 线是否实体主导、上影线主导或下影线主导；
1d / 4h 行情高低区间是否偏宽或偏窄。
```

这些内容用于帮助人工判断系统是否正确理解当前波动环境，而不是用于人工喊单。

## 13. 验收规则

### 13.1 4h 波动压缩样例

如果短窗口 4h 实现波动率明显低于长窗口：

```text
volatility_ratio_4h_20_to_60 <= 0.70；
```

则：

```text
volatility_4h_compression 应成立；
volatility_4h_expansion 不应成立。
```

原子层不得输出“即将突破”。

### 13.2 4h 波动扩张样例

如果短窗口 4h 实现波动率明显高于长窗口：

```text
volatility_ratio_4h_20_to_60 >= 1.30；
```

则：

```text
volatility_4h_expansion 应成立；
volatility_4h_compression 不应成立。
```

原子层不得输出方向性交易处理。

### 13.3 最新 4h K 线振幅较大样例

如果最新 4h 高低振幅大于 4h ATR 百分比 2 倍：

```text
candle_range_pct_4h_latest >= 2.00 * atr_pct_4h_14；
```

则：

```text
volatility_4h_latest_candle_range_large 应成立。
```

原子层不得输出“插针风险”或“交易阻断”。

### 13.4 4h 高波动分位样例

如果当前 4h ATR 分位为 0.86：

```text
volatility_4h_atr_high_percentile 应成立；
volatility_4h_atr_extreme_percentile 不应成立。
```

如果当前 4h ATR 分位为 0.96：

```text
volatility_4h_atr_high_percentile 应成立；
volatility_4h_atr_extreme_percentile 应成立。
```

### 13.5 证据验收

每个 AtomicSignalValue 必须满足：

```text
used_feature_value_ids 全部属于同一个 FeatureSet；
evidence_items 能复算 condition_result；
evidence_text_zh 能解释成立或不成立原因；
confidence = null；
direction = neutral；
不包含交易建议；
不包含完整 K 线窗口；
不包含密钥、账户、订单或外部服务响应。
```

## 14. 当前清单明确不处理

当前 volatility 原子信号清单不处理：

```text
布林带宽度；
Keltner Channel；
GARCH；
隐含波动率；
盘口价差；
深度数据；
资金费率；
连续大振幅 K 线数量；
波动压缩后方向性启动；
波动扩张但方向不明；
插针风险；
急涨风险；
急跌风险；
异常行情交易阻断。
```

这些能力如需加入，必须新增独立特征和原子信号需求文件。

其中插针风险、急涨风险、急跌风险和异常行情交易阻断属于 risk_state 或更下游模块，不应由 volatility 原子层直接输出。

## 15. 明确禁止

禁止在 Volatility AtomicSignal 中：

```text
读取 Kline 重新计算波动特征；
调用 FeatureLayer calculator；
自己计算 ATR；
自己计算实现波动率；
自己计算分位；
自己计算 K 线振幅、实体或影线；
自己计算区间宽度；
自己计算短长波动比；
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
