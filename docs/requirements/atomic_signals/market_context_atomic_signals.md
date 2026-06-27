# Market Context Atomic Signals

## 1. 文件定位

本文档定义 `market_context` 领域的第一批原子信号。

这些原子信号基于 [Market Context Features](../feature_layer/market_context_features.md) 输出的长期市场背景特征，形成最小市场判断。

本文档回答：

```text
哪些长期背景条件成立；
这些条件分别支持偏多、偏空还是仅表达状态；
每个判断使用哪些 FeatureValue；
每个判断为什么成立或不成立；
下游如何追溯判断依据。
```

本文档不负责：

```text
判断完整牛市或熊市；
判断牛市回调或熊市反弹；
综合多个领域；
识别 MarketRegime；
选择策略；
生成 StrategySignal；
生成 DecisionSnapshot；
读取账户或持仓；
请求 Binance；
执行真实交易。
```

本文档不是一个整体算法版本。本文档中的每个 AtomicSignalDefinition 独立版本化，单个原子信号算法升级时，只新增或切换该 AtomicSignalDefinition 的版本，不要求整份 market_context 原子信号清单整体升级。

## 2. 设计原则

Market Context 原子信号必须保持简单。

每个原子信号只回答一个明确问题：

```text
某个长期背景条件是否成立？
```

例如：

```text
价格是否明显高于 200 日均线；
价格是否明显低于 200 日均线；
200 日均线是否上行；
当前是否处于 365 日区间高位；
当前是否从高点发生深度回撤；
当前是否从回撤低点出现明显反弹。
```

原子信号不得直接输出：

```text
大级别上涨延续；
大级别下跌延续；
牛市回调；
熊市反弹；
高位宽幅震荡；
低位筑底；
趋势中继；
策略名称；
目标仓位；
订单动作。
```

这些结论必须由 DomainSignal、MarketRegime、StrategyRouting 或 StrategySignal 在各自职责内完成。

## 3. 输入要求

本文件只允许读取同一个 FeatureSet 内的 FeatureValue。

FeatureLayer 是 market_context 特征的数据工厂，负责计算并落库 `market_context_features.md` 定义的 FeatureValue。

Market Context AtomicSignal 是数据用户，只读取这些已经落库的 FeatureValue，不调用 FeatureLayer calculator，不调用 SMA、均线斜率、回撤、反弹或区间位置算法。

多个 Market Context 原子信号依赖同一个特征时，必须引用同一个 FeatureSet 内同一份 FeatureValue。

输入 FeatureValue 必须来自：

```text
docs/requirements/feature_layer/market_context_features.md
```

不得读取：

```text
Kline；
MarketSnapshot 原始 K 线；
FeatureLayer calculator；
SMA、均线斜率、回撤、反弹或区间位置算法函数；
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

## 4. 输出合同

每个原子信号输出 AtomicSignalValue。

### 4.1 成立与不成立

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

### 4.2 confidence 规则

当前清单中的 Market Context 原子信号默认：

```text
confidence = null
```

原因是这些信号只是确定性条件判断，尚未经过样本外概率校准。

不得因为计算成功就把 `confidence` 写成 1。

### 4.3 direction 语义

`bullish` 表示该条件支持“大背景偏多”的原子事实。

`bearish` 表示该条件支持“大背景偏空”的原子事实。

`neutral` 表示该条件只表达位置、回撤、反弹或状态，不直接给出方向。

这些方向不是交易动作，不得解释为买入、卖出、开仓、加仓、减仓或清仓。

## 5. 证据输出要求

每个 AtomicSignalValue 必须同时输出：

```text
used_feature_codes；
used_feature_value_ids；
evidence_items；
evidence_text_zh。
```

### 5.1 evidence_items 结构

`evidence_items` 至少包含：

```json
{
  "evidence_type": "market_context_atomic_condition",
  "signal_code": "信号代码",
  "condition_result": true,
  "used_features": [
    {
      "feature_code": "close_vs_sma_pct_1d_200",
      "feature_value_id": 123,
      "observed_value": "0.034"
    }
  ],
  "thresholds": {
    "min_value": "0.02"
  },
  "supporting_facts": [
    "当前收盘价高于 200 日均线 3.4%，超过 2% 缓冲阈值。"
  ],
  "weakening_facts": [],
  "calculation_summary": "close_vs_sma_pct_1d_200 >= 0.02"
}
```

`evidence_items` 只保存摘要和引用，不得复制完整 FeatureValue、完整 K 线窗口或大批量历史数组。

### 5.2 evidence_text_zh 结构

`evidence_text_zh` 必须是中文短句，面向人工复核可读。

示例：

```text
当前收盘价高于 200 日均线 3.4%，超过 2% 缓冲阈值，因此“价格明显高于 200 日均线”成立。
```

如果条件不成立，也必须说明原因：

```text
当前收盘价仅高于 200 日均线 0.8%，未超过 2% 缓冲阈值，因此“价格明显高于 200 日均线”不成立。
```

不得在 `evidence_text_zh` 中写交易建议。

## 6. 固定参数

本文档列出的初始 AtomicSignalDefinition 使用以下参数约定：

| 参数 | 值 | 用途 |
|---|---:|---|
| 长期均线距离缓冲 | 0.02 | 价格相对均线超过 2% 才认为明显上方或下方 |
| 均线斜率死区 | 0.003 | 20 日均线斜率变化超过 0.3% 才认为明显上行或下行 |
| 365 日高位阈值 | 0.75 | 区间位置高于 75% 认为处于长期高位区 |
| 365 日低位阈值 | 0.25 | 区间位置低于 25% 认为处于长期低位区 |
| 中等回撤下限 | 0.08 | 从 365 日高点回撤超过 8% 认为出现有效回撤 |
| 中等回撤上限 | 0.30 | 回撤不超过 30% 仍归为中等回撤 |
| 深度回撤阈值 | 0.30 | 从 365 日高点回撤超过 30% 认为深度回撤 |
| 明显反弹阈值 | 0.15 | 从回撤低点反弹超过 15% 认为明显反弹 |
| 高收复比例阈值 | 0.60 | 已收复前一段回撤的 60% 以上 |
| 低收复比例阈值 | 0.35 | 已收复前一段回撤的 35% 以下 |
| 365 日正收益阈值 | 0.10 | 365 日收益超过 10% |
| 365 日负收益阈值 | -0.10 | 365 日收益低于 -10% |

这些参数必须写入对应 AtomicSignalDefinition 的 params / params_hash，并属于对应原子信号算法版本的一部分。

后续如果只调整某一个原子信号的阈值、条件、默认方向或证据结构，只能新增该 AtomicSignalDefinition 的算法版本，不得静默修改历史 AtomicSignalValue 的含义，也不得要求无关原子信号同步升级。

## 7. 原子信号清单

### 7.1 价格相对长期均线

| signal_code | 问题 | 默认方向 | 依赖特征 | 条件 |
|---|---|---|---|---|
| `market_context_price_above_sma_1d_200` | 当前价格是否明显高于 200 日均线 | bullish | `close_vs_sma_pct_1d_200` | `close_vs_sma_pct_1d_200 >= 0.02` |
| `market_context_price_below_sma_1d_200` | 当前价格是否明显低于 200 日均线 | bearish | `close_vs_sma_pct_1d_200` | `close_vs_sma_pct_1d_200 <= -0.02` |
| `market_context_price_above_sma_1d_365` | 当前价格是否明显高于 365 日均线 | bullish | `close_vs_sma_pct_1d_365` | `close_vs_sma_pct_1d_365 >= 0.02` |
| `market_context_price_below_sma_1d_365` | 当前价格是否明显低于 365 日均线 | bearish | `close_vs_sma_pct_1d_365` | `close_vs_sma_pct_1d_365 <= -0.02` |

这些信号只表达价格相对长期均线的位置。

不成立不代表反向条件成立，反向条件必须由对应的反向信号单独判断。

### 7.2 长期均线斜率

| signal_code | 问题 | 默认方向 | 依赖特征 | 条件 |
|---|---|---|---|---|
| `market_context_sma_1d_200_rising` | 200 日均线是否明显上行 | bullish | `slope_sma_1d_200` | `slope_sma_1d_200 >= 0.003` |
| `market_context_sma_1d_200_falling` | 200 日均线是否明显下行 | bearish | `slope_sma_1d_200` | `slope_sma_1d_200 <= -0.003` |
| `market_context_sma_1d_365_rising` | 365 日均线是否明显上行 | bullish | `slope_sma_1d_365` | `slope_sma_1d_365 >= 0.003` |
| `market_context_sma_1d_365_falling` | 365 日均线是否明显下行 | bearish | `slope_sma_1d_365` | `slope_sma_1d_365 <= -0.003` |

均线斜率信号只表达长期均线方向，不判断趋势是否成立。

趋势是否成立由 `trend` 领域负责。

### 7.3 365 日区间位置

| signal_code | 问题 | 默认方向 | 依赖特征 | 条件 |
|---|---|---|---|---|
| `market_context_in_365d_high_zone` | 当前是否位于最近 365 日区间高位 | neutral | `range_position_pct_1d_365` | `range_position_pct_1d_365 >= 0.75` |
| `market_context_in_365d_low_zone` | 当前是否位于最近 365 日区间低位 | neutral | `range_position_pct_1d_365` | `range_position_pct_1d_365 <= 0.25` |

高位和低位是长期位置状态，不是做多、做空、减仓或清仓建议。

### 7.4 从长期高点回撤

| signal_code | 问题 | 默认方向 | 依赖特征 | 条件 |
|---|---|---|---|---|
| `market_context_moderate_drawdown_from_365d_high` | 当前是否从 365 日高点出现中等回撤 | neutral | `drawdown_from_high_pct_1d_365` | `0.08 <= drawdown_from_high_pct_1d_365 < 0.30` |
| `market_context_deep_drawdown_from_365d_high` | 当前是否从 365 日高点出现深度回撤 | bearish | `drawdown_from_high_pct_1d_365` | `drawdown_from_high_pct_1d_365 >= 0.30` |

中等回撤只表达“出现有效回落”，不直接判断为牛市回调。

深度回撤只表达长期结构压力增大，不直接判断为熊市。

### 7.5 从回撤低点反弹

| signal_code | 问题 | 默认方向 | 依赖特征 | 条件 |
|---|---|---|---|---|
| `market_context_material_rebound_from_drawdown_low` | 当前是否从回撤低点明显反弹 | neutral | `rebound_from_drawdown_low_pct_1d_365` | `rebound_from_drawdown_low_pct_1d_365 >= 0.15` |
| `market_context_high_recovery_from_drawdown` | 当前是否已经收复前一段回撤的大部分空间 | neutral | `recovery_ratio_from_drawdown_1d_365` | `recovery_ratio_from_drawdown_1d_365 >= 0.60` |
| `market_context_low_recovery_from_drawdown` | 当前是否只收复前一段回撤的小部分空间 | neutral | `recovery_ratio_from_drawdown_1d_365` | `recovery_ratio_from_drawdown_1d_365 <= 0.35` |

明显反弹不等于趋势恢复。

低收复比例不等于继续下跌。

这些状态必须交给 DomainSignal 和 MarketRegime 与趋势、动能、结构领域共同解释。

### 7.6 365 日收益

| signal_code | 问题 | 默认方向 | 依赖特征 | 条件 |
|---|---|---|---|---|
| `market_context_positive_365d_return` | 最近 365 日收益是否明显为正 | bullish | `return_pct_1d_365` | `return_pct_1d_365 >= 0.10` |
| `market_context_negative_365d_return` | 最近 365 日收益是否明显为负 | bearish | `return_pct_1d_365` | `return_pct_1d_365 <= -0.10` |

365 日收益只表达长期价格变化结果，不单独定义完整市场背景。

## 8. 与 DomainSignal 的关系

这些原子信号必须归属于 `market_context` 领域。

DomainSignal 可以把这些原子信号综合为领域级事实，例如：

```text
长期背景偏多；
长期背景偏空；
长期背景中性；
长期高位；
长期低位；
高点后中等回撤；
高点后深度回撤；
回撤后明显反弹；
反弹收复程度较高；
反弹收复程度较低。
```

但 DomainSignal 不得把这些原子信号直接解释为策略动作。

## 9. 与 MarketRegime 的关系

MarketRegime 可以在接收 `market_context`、`trend`、`momentum`、`volatility`、`structure` 和 `risk_state` 领域事实后，识别更完整的市场环境。

例如：

```text
market_context 显示长期背景仍偏多；
trend 显示中期趋势推进减弱；
structure 显示价格靠近区间支撑；
volatility 显示宽幅震荡；

MarketRegime 才可以形成“大级别偏多背景下的高位区间震荡，当前靠近支撑”之类的环境结论。
```

Market Context 原子信号不得单独承担上述结论。

## 10. 人工复核视角

后台或复盘展示一轮策略分析结果时，至少应能从 Market Context 原子信号看到：

```text
价格相对 200 / 365 日均线的位置；
200 / 365 日均线是否明显上行或下行；
当前处于 365 日区间高位、低位还是中部；
从 365 日高点回撤多少；
从回撤低点反弹多少；
反弹收复了多少前期回撤；
365 日收益是明显为正、明显为负还是不明显。
```

这些内容用于帮助人工判断系统是否理解了大级别背景，而不是用于人工喊单。

## 11. 验收规则

### 11.1 上涨背景样例

如果当前价格明显高于 200 日均线和 365 日均线，且 200 / 365 日均线均明显上行：

```text
market_context_price_above_sma_1d_200 应成立；
market_context_price_above_sma_1d_365 应成立；
market_context_sma_1d_200_rising 应成立；
market_context_sma_1d_365_rising 应成立；
对应反向信号不应成立。
```

### 11.2 下跌背景样例

如果当前价格明显低于 200 日均线和 365 日均线，且 200 / 365 日均线均明显下行：

```text
market_context_price_below_sma_1d_200 应成立；
market_context_price_below_sma_1d_365 应成立；
market_context_sma_1d_200_falling 应成立；
market_context_sma_1d_365_falling 应成立；
对应反向信号不应成立。
```

### 11.3 高位震荡样例

如果当前价格位于最近 365 日区间高位，但长期均线未明显下行：

```text
market_context_in_365d_high_zone 应成立；
market_context_sma_1d_200_falling 不应仅因为高位震荡而成立；
Market Context 原子层不得直接输出“高位宽幅震荡”。
```

### 11.4 下跌后反弹样例

如果当前从 365 日高点深度回撤后又明显反弹，但收复比例不足：

```text
market_context_deep_drawdown_from_365d_high 应成立；
market_context_material_rebound_from_drawdown_low 应成立；
market_context_low_recovery_from_drawdown 应按阈值判断；
原子层不得直接输出“熊市反弹”。
```

### 11.5 证据验收

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

## 12. 当前清单明确不处理

当前 market_context 原子信号清单不处理：

```text
周线背景；
宏观数据；
链上数据；
资金费率；
多币种强弱；
多交易所背景；
成交量背景；
主观形态识别；
机器学习市场分类。
```

这些能力如需加入，必须新增独立特征和原子信号需求文件。
