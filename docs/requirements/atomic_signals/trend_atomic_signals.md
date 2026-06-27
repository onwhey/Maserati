# Trend Atomic Signals

## 1. 文件定位

本文档定义 `trend` 领域的第一批原子信号。

这些原子信号基于 [Trend Features](../feature_layer/trend_features.md) 输出的趋势特征，形成最小趋势判断。

本文档回答：

```text
1d 当前趋势事实是否偏多、偏空或不明确；
4h 当前趋势事实是否偏多、偏空或不明确；
哪些趋势条件成立；
每个判断使用哪些 FeatureValue；
每个判断为什么成立或不成立；
下游如何追溯判断依据。
```

本文档不负责：

```text
判断大级别牛市或熊市；
判断牛市回调或熊市反弹；
判断支撑压力；
综合 1d 与 4h 形成完整趋势领域结论；
识别 MarketRegime；
选择策略；
生成 StrategySignal；
生成 DecisionSnapshot；
读取账户或持仓；
请求 Binance；
执行真实交易。
```

本文档不是一个整体算法版本。本文档中的每个 AtomicSignalDefinition 独立版本化，单个原子信号算法升级时，只新增或切换该 AtomicSignalDefinition 的版本，不要求整份 trend 原子信号清单整体升级。

## 2. 设计原则

Trend 原子信号必须保持简单。

每个原子信号只回答一个明确问题：

```text
某个趋势条件是否成立？
```

例如：

```text
1d 均线是否呈偏多排列；
1d 均线是否呈偏空排列；
1d 慢趋势斜率是否向上；
4h 均线是否呈偏多排列；
4h 高低点结构是否连续抬高；
4h 高低点结构是否连续降低。
```

原子信号不得直接输出：

```text
完整上涨趋势；
完整下跌趋势；
多周期一致偏多；
多周期一致偏空；
上涨趋势中的横盘；
下跌趋势中的反弹；
趋势中继；
趋势破坏后观望；
策略名称；
目标仓位；
订单动作。
```

这些结论必须由 DomainSignal、MarketRegime、StrategyRouting 或 StrategySignal 在各自职责内完成。

## 3. 输入要求

本文件只允许读取同一个 FeatureSet 内的 FeatureValue。

FeatureLayer 是 trend 特征的数据工厂，负责计算并落库 `trend_features.md` 定义的 FeatureValue。

Trend AtomicSignal 是数据用户，只读取这些已经落库的 FeatureValue，不调用 FeatureLayer calculator，不调用 SMA、均线斜率、滚动高低点或分块结构计数算法。

多个 Trend 原子信号依赖同一个特征时，必须引用同一个 FeatureSet 内同一份 FeatureValue。

输入 FeatureValue 必须来自：

```text
docs/requirements/feature_layer/trend_features.md
```

不得读取：

```text
Kline；
MarketSnapshot 原始 K 线；
FeatureLayer calculator；
SMA、均线斜率、滚动高低点或高低点结构计数算法函数；
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

当前 Trend 原子信号只使用：

```text
1d 已收盘 K 线生成的趋势 FeatureValue；
4h 已收盘 K 线生成的趋势 FeatureValue。
```

职责划分：

```text
1d 原子信号 = 当前运行趋势的主判断事实；
4h 原子信号 = 当前运行趋势的短周期趋势事实。
```

当前不引入 3d 原子信号。

如果未来要引入 3d，必须先补齐 3d 的 DataCollection、MarketSnapshot、FeatureDefinition 和 FeatureValue 需求，不能在原子层把多个 1d 临时拼成 3d。

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

当前清单中的 Trend 原子信号默认：

```text
confidence = null
```

原因是这些信号只是确定性条件判断，尚未经过样本外概率校准。

不得因为计算成功就把 `confidence` 写成 1。

### 5.3 direction 语义

`bullish` 表示该条件支持“趋势事实偏多”。

`bearish` 表示该条件支持“趋势事实偏空”。

`neutral` 表示该条件只表达状态或条件不成立，不直接给出方向。

这些方向不是交易动作，不得解释为买入、卖出、开仓、加仓、减仓或清仓。

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
  "evidence_type": "trend_atomic_condition",
  "signal_code": "trend_1d_ma_bullish_alignment",
  "condition_result": true,
  "used_features": [
    {
      "feature_code": "sma_spread_pct_1d_20_60",
      "feature_value_id": 123,
      "observed_value": "0.018"
    },
    {
      "feature_code": "sma_spread_pct_1d_60_120",
      "feature_value_id": 124,
      "observed_value": "0.026"
    }
  ],
  "thresholds": {
    "min_spread_pct": "0.003"
  },
  "supporting_facts": [
    "1d 20 日均线高于 60 日均线 1.8%。",
    "1d 60 日均线高于 120 日均线 2.6%。"
  ],
  "weakening_facts": [],
  "calculation_summary": "sma_spread_pct_1d_20_60 >= 0.003 AND sma_spread_pct_1d_60_120 >= 0.003"
}
```

`evidence_items` 只保存摘要和引用，不得复制完整 FeatureValue、完整 K 线窗口或大批量历史数组。

### 6.2 evidence_text_zh 结构

`evidence_text_zh` 必须是中文短句，面向人工复核可读。

示例：

```text
1d 20 日均线高于 60 日均线 1.8%，且 60 日均线高于 120 日均线 2.6%，超过 0.3% 缓冲阈值，因此“1d 均线偏多排列”成立。
```

如果条件不成立，也必须说明原因：

```text
1d 20 日均线仅高于 60 日均线 0.1%，未超过 0.3% 缓冲阈值，因此“1d 均线偏多排列”不成立。
```

不得在 `evidence_text_zh` 中写交易建议。

## 7. 固定参数

本文档列出的初始 AtomicSignalDefinition 使用以下参数约定：

| 参数 | 值 | 用途 |
|---|---:|---|
| 均线排列缓冲 | 0.003 | 快慢均线距离超过 0.3% 才认为排列明确 |
| 价格相对中期均线缓冲 | 0.005 | 收盘价相对中期均线超过 0.5% 才认为明显上方或下方 |
| 1d 慢趋势斜率死区 | 0.003 | 1d 120 日均线斜率超过 0.3% 才认为明显上行或下行 |
| 4h 中期趋势斜率死区 | 0.003 | 4h 60 均线斜率超过 0.3% 才认为明显上行或下行 |
| 分块结构连续阈值 | 2 | 最近 3 个分块之间连续两次抬高或降低，才认为结构连续 |

这些参数必须写入对应 AtomicSignalDefinition 的 params / params_hash，并属于对应原子信号算法版本的一部分。

后续如果只调整某一个原子信号的阈值、条件、默认方向或证据结构，只能新增该 AtomicSignalDefinition 的算法版本，不得静默修改历史 AtomicSignalValue 的含义，也不得要求无关原子信号同步升级。

## 8. 原子信号清单

### 8.1 1d 均线排列

| signal_code | 问题 | 默认方向 | 依赖特征 | 条件 |
|---|---|---|---|---|
| `trend_1d_ma_bullish_alignment` | 1d 均线是否呈偏多排列 | bullish | `sma_spread_pct_1d_20_60` / `sma_spread_pct_1d_60_120` | 两者均 `>= 0.003` |
| `trend_1d_ma_bearish_alignment` | 1d 均线是否呈偏空排列 | bearish | `sma_spread_pct_1d_20_60` / `sma_spread_pct_1d_60_120` | 两者均 `<= -0.003` |

这些信号只表达 1d 均线排列，不单独定义完整趋势。

不成立不代表反向条件成立，反向条件必须由对应的反向信号单独判断。

### 8.2 1d 慢趋势斜率

| signal_code | 问题 | 默认方向 | 依赖特征 | 条件 |
|---|---|---|---|---|
| `trend_1d_slow_slope_rising` | 1d 120 日均线是否明显上行 | bullish | `slope_sma_1d_120_lag10` | `slope_sma_1d_120_lag10 >= 0.003` |
| `trend_1d_slow_slope_falling` | 1d 120 日均线是否明显下行 | bearish | `slope_sma_1d_120_lag10` | `slope_sma_1d_120_lag10 <= -0.003` |

慢趋势斜率只表达趋势参考线方向，不判断牛市或熊市。

### 8.3 1d 价格相对中期均线

| signal_code | 问题 | 默认方向 | 依赖特征 | 条件 |
|---|---|---|---|---|
| `trend_1d_price_above_medium_ma` | 1d 收盘价是否明显位于 60 日均线上方 | bullish | `close_vs_sma_pct_1d_60` | `close_vs_sma_pct_1d_60 >= 0.005` |
| `trend_1d_price_below_medium_ma` | 1d 收盘价是否明显位于 60 日均线下方 | bearish | `close_vs_sma_pct_1d_60` | `close_vs_sma_pct_1d_60 <= -0.005` |

这些信号只表达价格相对中期趋势线的位置。

### 8.4 1d 分块高低点结构

| signal_code | 问题 | 默认方向 | 依赖特征 | 条件 |
|---|---|---|---|---|
| `trend_1d_block_structure_rising` | 1d 近 60 根 K 线分块高低点是否连续抬高 | bullish | `higher_high_count_1d_60_block20` / `higher_low_count_1d_60_block20` | 两者均 `>= 2` |
| `trend_1d_block_structure_falling` | 1d 近 60 根 K 线分块高低点是否连续降低 | bearish | `lower_high_count_1d_60_block20` / `lower_low_count_1d_60_block20` | 两者均 `>= 2` |

分块高低点结构只表达固定分块上的结构变化。

它不是人工画线，也不是完整趋势通道识别。

### 8.5 4h 均线排列

| signal_code | 问题 | 默认方向 | 依赖特征 | 条件 |
|---|---|---|---|---|
| `trend_4h_ma_bullish_alignment` | 4h 均线是否呈偏多排列 | bullish | `sma_spread_pct_4h_20_60` / `sma_spread_pct_4h_60_120` | 两者均 `>= 0.003` |
| `trend_4h_ma_bearish_alignment` | 4h 均线是否呈偏空排列 | bearish | `sma_spread_pct_4h_20_60` / `sma_spread_pct_4h_60_120` | 两者均 `<= -0.003` |

4h 均线排列只是短周期趋势事实，不得替代 1d 主趋势。

### 8.6 4h 中期趋势斜率

| signal_code | 问题 | 默认方向 | 依赖特征 | 条件 |
|---|---|---|---|---|
| `trend_4h_medium_slope_rising` | 4h 60 均线是否明显上行 | bullish | `slope_sma_4h_60_lag12` | `slope_sma_4h_60_lag12 >= 0.003` |
| `trend_4h_medium_slope_falling` | 4h 60 均线是否明显下行 | bearish | `slope_sma_4h_60_lag12` | `slope_sma_4h_60_lag12 <= -0.003` |

4h 中期斜率用于观察短周期推进方向。

### 8.7 4h 价格相对中期均线

| signal_code | 问题 | 默认方向 | 依赖特征 | 条件 |
|---|---|---|---|---|
| `trend_4h_price_above_medium_ma` | 4h 收盘价是否明显位于 60 根 4h 均线上方 | bullish | `close_vs_sma_pct_4h_60` | `close_vs_sma_pct_4h_60 >= 0.005` |
| `trend_4h_price_below_medium_ma` | 4h 收盘价是否明显位于 60 根 4h 均线下方 | bearish | `close_vs_sma_pct_4h_60` | `close_vs_sma_pct_4h_60 <= -0.005` |

这些信号只表达 4h 价格相对中期趋势线的位置。

### 8.8 4h 分块高低点结构

| signal_code | 问题 | 默认方向 | 依赖特征 | 条件 |
|---|---|---|---|---|
| `trend_4h_block_structure_rising` | 4h 近 60 根 K 线分块高低点是否连续抬高 | bullish | `higher_high_count_4h_60_block20` / `higher_low_count_4h_60_block20` | 两者均 `>= 2` |
| `trend_4h_block_structure_falling` | 4h 近 60 根 K 线分块高低点是否连续降低 | bearish | `lower_high_count_4h_60_block20` / `lower_low_count_4h_60_block20` | 两者均 `>= 2` |

4h 分块结构用于观察短周期是否仍在推进或反向运行。

## 9. 与 DomainSignal 的关系

这些原子信号必须归属于 `trend` 领域。

DomainSignal 可以把这些原子信号综合为领域级事实，例如：

```text
1d 趋势偏多；
1d 趋势偏空；
4h 短周期趋势状态偏多；
4h 短周期趋势状态偏空；
1d 与 4h 同向；
1d 上行但 4h 回调；
1d 下行但 4h 反弹；
趋势推进增强；
趋势推进减弱。
```

这些综合结论不在原子层重复计算。

原子层不单独定义“多周期一致偏多 / 多周期一致偏空”信号，避免重复编写 1d 与 4h 判断规则。多周期一致性由 DomainSignal 聚合本文件中 1d 与 4h 原子信号后形成。

## 10. 与 MarketRegime 的关系

MarketRegime 可以在接收 `market_context`、`trend`、`momentum`、`volatility`、`structure` 和 `risk_state` 领域事实后，识别更完整的市场环境。

例如：

```text
market_context 显示大级别偏多；
trend 显示 1d 偏多但 4h 回调；
structure 显示当前靠近支撑区；
volatility 显示宽幅震荡；

MarketRegime 才可以形成“大级别偏多背景下，1d 上升趋势中的支撑区附近震荡回调”之类的环境结论。
```

Trend 原子信号不得单独承担上述结论。

## 11. 人工复核视角

后台或复盘展示一轮策略分析结果时，至少应能从 Trend 原子信号看到：

```text
1d 均线排列是否偏多或偏空；
1d 慢趋势斜率是否上行或下行；
1d 收盘价是否明显位于中期均线上方或下方；
1d 分块高低点是否连续抬高或降低；
4h 均线排列是否偏多或偏空；
4h 中期斜率是否上行或下行；
4h 收盘价是否明显位于中期均线上方或下方；
4h 分块高低点是否连续抬高或降低。
```

这些内容用于帮助人工判断系统是否正确理解当前运行趋势，而不是用于人工喊单。

## 12. 验收规则

### 12.1 日线偏多样例

如果 1d 均线呈多头排列，120 日均线明显上行，收盘价明显高于 60 日均线，且分块高低点连续抬高：

```text
trend_1d_ma_bullish_alignment 应成立；
trend_1d_slow_slope_rising 应成立；
trend_1d_price_above_medium_ma 应成立；
trend_1d_block_structure_rising 应成立；
对应 1d 偏空信号不应成立。
```

### 12.2 日线偏空样例

如果 1d 均线呈空头排列，120 日均线明显下行，收盘价明显低于 60 日均线，且分块高低点连续降低：

```text
trend_1d_ma_bearish_alignment 应成立；
trend_1d_slow_slope_falling 应成立；
trend_1d_price_below_medium_ma 应成立；
trend_1d_block_structure_falling 应成立；
对应 1d 偏多信号不应成立。
```

### 12.3 日线上行但 4h 回调样例

如果 1d 偏多信号成立，但 4h 价格低于 60 根 4h 均线，且 4h 分块结构连续降低：

```text
1d 偏多原子信号应按各自条件成立；
trend_4h_price_below_medium_ma 可以成立；
trend_4h_block_structure_falling 可以成立；
原子层不得直接输出“上涨趋势中的回调”。
```

“上涨趋势中的回调”必须由 Trend DomainSignal 或 MarketRegime 综合判断。

### 12.4 日线下行但 4h 反弹样例

如果 1d 偏空信号成立，但 4h 价格高于 60 根 4h 均线，且 4h 中期斜率上行：

```text
1d 偏空原子信号应按各自条件成立；
trend_4h_price_above_medium_ma 可以成立；
trend_4h_medium_slope_rising 可以成立；
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

当前 trend 原子信号清单不处理：

```text
3d 趋势；
周线趋势；
人工趋势线；
趋势通道；
ADX；
EMA；
MACD；
成交量趋势；
多币种趋势强弱；
机器学习趋势分类；
完整趋势中继识别；
完整趋势末端衰竭识别。
```

这些能力如需加入，必须新增独立特征和原子信号需求文件。

## 14. 明确禁止

禁止在 Trend AtomicSignal 中：

```text
读取 Kline 重新计算趋势特征；
调用 FeatureLayer calculator；
自己计算 SMA；
自己计算均线斜率；
自己计算滚动高低点；
自己计算高低点分块结构；
读取其他 AtomicSignalValue；
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
