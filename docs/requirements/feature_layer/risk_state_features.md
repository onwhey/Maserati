# Risk State Features

## 1. 文件定位

本文档定义 `risk_state` 领域所需的 FeatureDefinition 候选目录。

本文档不是一个整体算法版本。本文档中的每个 FeatureDefinition 独立版本化、独立注册、独立进入 StrategyAnalysisRelease。

也就是说：

```text
risk_latest_body_return_pct_4h 可以有自己的 v1 / v2；
risk_consecutive_large_bear_body_count_4h_20 可以有自己的 v1 / v2；
risk_latest_close_location_ratio_4h 可以有自己的 v1 / v2；
本文档本身不表示“risk_state feature v1 整体版本”。
```

risk_state 特征只回答“当前行情是否出现风险判断所需的基础事实”，不回答“任何交易处理方式”。

risk_state 特征服务于：

```text
AtomicSignal
→ DomainSignal.risk_state
→ MarketRegime
→ StrategyRouting
→ StrategySignal
```

risk_state 特征不得直接生成交易信号、目标仓位、订单意图或交易动作。

## 2. 领域边界

risk_state 负责为市场风险判断提供基础事实，例如：

```text
最新 K 线实体涨跌幅；
最新 K 线收盘在高低区间中的位置；
连续大实体上涨或下跌数量；
短窗口累计冲击幅度；
最新 K 线是否在极端位置收盘；
急涨急跌后是否出现快速反向收回。
```

risk_state 不负责：

```text
判断当前是牛市还是熊市；
判断趋势方向；
判断动能是否增强；
判断支撑压力是否有效；
重复输出高波动或低波动；
判断账户是否有持仓；
判断保证金风险；
判断订单风险；
决定仓位如何变化；
决定是否形成交易目标；
决定是否执行某个交易方向。
```

边界规则：

```text
volatility 负责波动大小、压缩、扩张和波动位置；
structure 负责支撑压力、区间结构和价格位置；
risk_state 负责异常行情对信号可靠性、方向暴露和追单风险的风险含义。
```

同一个基础特征可以被多个领域复用。

例如：

```text
candle_body_pct_4h_latest 可以被 volatility 用于描述单根 K 线实体大小；
candle_body_pct_4h_latest 也可以被 risk_state 用于判断急涨急跌是否构成风险证据。
```

复用必须读取同一份 FeatureValue，不得在不同领域各自重复计算同义特征。

## 3. 数据范围

当前 P0 数据采集范围只包含 Binance USDS-M BTCUSDT 的已收盘 4h / 1d K 线。

因此 risk_state 特征当前只允许使用：

```text
1d 已收盘 K 线；
4h 已收盘 K 线。
```

P0 以 4h 风险事实为主，1d 只作为大级别风险补充。

risk_state 不引入：

```text
盘口深度；
价差；
逐笔成交；
资金费率；
爆仓数据；
WebSocket 实时价格；
未收盘 K 线。
```

如果未来需要引入流动性或盘口风险，必须先修改 DataCollection / MarketSnapshot / FeatureLayer 相关需求。

## 4. 输入数据要求

risk_state FeatureCalculator 只能读取 MarketSnapshot 冻结的 K 线窗口。

允许输入：

```text
MarketSnapshot 固定的 1d 已收盘 K 线；
MarketSnapshot 固定的 4h 已收盘 K 线；
K 线 open_time / close_time / open / high / low / close。
```

禁止输入：

```text
未收盘 K 线；
WebSocket 实时价格；
PriceSnapshot mark price；
账户权益；
持仓方向；
订单状态；
成交明细；
Binance 实时请求；
DeepSeek 或其他大模型；
人工画线结果。
```

FeatureLayer 只负责计算并保存基础事实，不负责解释这些事实是否应该导致交易动作。

## 5. 可复用的既有 FeatureValue

risk_state AtomicSignal 可以读取同一版本包中已经选择的 volatility / structure FeatureValue。

允许复用的典型特征包括：

```text
candle_range_pct_4h_latest；
candle_body_pct_4h_latest；
candle_body_ratio_4h_latest；
upper_shadow_ratio_4h_latest；
lower_shadow_ratio_4h_latest；
atr_percentile_4h_120；
realized_vol_percentile_4h_120；
structure_major_distance_to_support_upper_pct_1d_365；
structure_major_distance_to_resistance_lower_pct_1d_365；
structure_minor_distance_to_support_upper_pct_4h_120；
structure_minor_distance_to_resistance_lower_pct_4h_120；
structure_major_breakout_above_resistance_pct_1d_365；
structure_major_breakdown_below_support_pct_1d_365；
structure_minor_breakout_above_resistance_pct_4h_120；
structure_minor_breakdown_below_support_pct_4h_120。
```

这些特征仍由各自 FeatureDefinition 负责计算。risk_state 不复制其算法。

## 6. P0 risk_state 专属特征

### 6.1 最新 4h 收益与实体方向

| FeatureCode | 业务含义 | 值类型 | 最小窗口 |
|---|---|---|---:|
| risk_latest_close_return_pct_4h | 最新 4h 收盘价相对上一根 4h 收盘价涨跌幅 | decimal | 2 |
| risk_latest_body_return_pct_4h | 最新 4h 实体涨跌幅，`(close - open) / open` | decimal | 1 |
| risk_latest_abs_body_return_pct_4h | 最新 4h 实体涨跌幅绝对值 | decimal | 1 |

说明：

```text
risk_latest_body_return_pct_4h > 0 表示阳线实体；
risk_latest_body_return_pct_4h < 0 表示阴线实体；
它只表达事实，不表示追多、追空、平仓或反向。
```

### 6.2 最新 4h 收盘位置

| FeatureCode | 业务含义 | 值类型 | 最小窗口 |
|---|---|---|---:|
| risk_latest_close_location_ratio_4h | 最新 4h 收盘价在高低区间中的位置，`(close - low) / (high - low)` | decimal/null | 1 |
| risk_latest_close_near_high_distance_pct_4h | 最新 4h 收盘价距离最高价百分比 | decimal/null | 1 |
| risk_latest_close_near_low_distance_pct_4h | 最新 4h 收盘价距离最低价百分比 | decimal/null | 1 |

当 `high = low` 时：

```text
risk_latest_close_location_ratio_4h = null；
near_high / near_low distance = null；
对应 FeatureValue.status = created，但 evidence 中必须说明无有效高低区间。
```

### 6.3 连续大实体

| FeatureCode | 业务含义 | 值类型 | 最小窗口 |
|---|---|---|---:|
| risk_consecutive_large_bear_body_count_4h_20 | 截至最新 4h，连续大阴线数量 | integer | 20 |
| risk_consecutive_large_bull_body_count_4h_20 | 截至最新 4h，连续大阳线数量 | integer | 20 |
| risk_large_body_same_direction_count_4h_6 | 最近 6 根 4h 中同方向大实体数量的最大值 | integer | 6 |

大实体默认定义：

```text
abs(body_return_pct) >= max(1.8%, 1.2 * median(abs(body_return_pct), 最近 60 根 4h))
```

如果 60 根历史不足：

```text
使用已冻结窗口内可用 4h K 线；
少于 20 根时，该特征 failed，不得用 0 伪装正常。
```

### 6.4 短窗口冲击幅度

| FeatureCode | 业务含义 | 值类型 | 最小窗口 |
|---|---|---|---:|
| risk_cumulative_return_pct_4h_3 | 最近 3 根 4h 收盘累计涨跌幅 | decimal | 4 |
| risk_cumulative_return_pct_4h_6 | 最近 6 根 4h 收盘累计涨跌幅 | decimal | 7 |
| risk_max_single_body_return_pct_4h_20 | 最近 20 根 4h 最大单根实体涨幅 | decimal | 20 |
| risk_min_single_body_return_pct_4h_20 | 最近 20 根 4h 最大单根实体跌幅 | decimal | 20 |

这些特征只表达价格冲击，不解释冲击是否有效突破或假突破。

### 6.5 快速反向收回

| FeatureCode | 业务含义 | 值类型 | 最小窗口 |
|---|---|---|---:|
| risk_latest_from_intrabar_high_reversal_pct_4h | 最新 4h 从最高价回落到收盘的幅度 | decimal/null | 1 |
| risk_latest_from_intrabar_low_recovery_pct_4h | 最新 4h 从最低价回收到收盘的幅度 | decimal/null | 1 |
| risk_two_bar_opposite_reversal_pct_4h | 最新 2 根 4h 相对前一根方向的反向收回幅度 | decimal/null | 2 |

计算说明：

```text
from_intrabar_high_reversal_pct = (high - close) / high；
from_intrabar_low_recovery_pct = (close - low) / low；
two_bar_opposite_reversal_pct 用于表达前一根大阳 / 大阴后，后一根是否出现明显反向收回。
```

这些特征用于后续原子信号判断“快速失败”或“插针风险”，但 FeatureLayer 不直接输出风险结论。

## 7. 参数

本文件涉及的默认参数：

| 参数 | 值 | 说明 |
|---|---:|---|
| 大实体绝对下限 | 1.8% | 4h 实体涨跌幅绝对值下限 |
| 大实体相对倍数 | 1.2 | 相对最近 60 根实体绝对值中位数的倍数 |
| 连续大实体统计窗口 | 20 根 4h | 统计连续大阳 / 大阴 |
| 短窗口冲击窗口 | 3 / 6 根 4h | 识别短期冲击 |
| 收盘靠近高点阈值 | 0.80 | close_location_ratio >= 0.80 |
| 收盘靠近低点阈值 | 0.20 | close_location_ratio <= 0.20 |

这些参数属于对应 FeatureDefinition 的默认参数。后续调整必须新增 FeatureDefinition 版本。

## 8. 输出证据要求

每个 FeatureValue 必须保存：

```text
feature_code；
algorithm_name；
algorithm_version；
timeframe；
lookback_window；
analysis_close_time_utc；
input_kline_open_time_range；
input_kline_close_time_range；
value；
value_unit；
params_hash；
evidence_items；
evidence_text_zh。
```

evidence_items 至少包含：

```text
最新 K 线 open_time / close_time；
最新 K 线 open / high / low / close；
使用窗口长度；
阈值参数；
被排除的未收盘 K 线数量，正常应为 0；
失败原因，如窗口不足或 high = low。
```

## 9. 与 risk_state AtomicSignal 的关系

AtomicSignal 可以组合读取：

```text
risk_state 专属 FeatureValue；
volatility FeatureValue；
structure FeatureValue。
```

组合读取只发生在 AtomicSignal 层。

FeatureLayer 不得：

```text
因为单根下跌 8% 就输出交易动作；
因为单根上涨 8% 就输出交易方向；
因为高波动就输出交易链路是否应继续；
因为支撑跌破就输出“空头趋势确认”；
读取账户或判断当前是否真的有多仓 / 空仓。
```

## 10. 验收要求

至少覆盖以下场景：

```text
最新 4h 实体大跌，risk_latest_body_return_pct_4h 为负；
最新 4h 实体大涨，risk_latest_body_return_pct_4h 为正；
最新 4h 长下影收回，close_location_ratio 高于 0.80；
最新 4h 长上影回落，close_location_ratio 低于 0.20；
连续 3 根大阴线，连续大阴线数量正确；
连续 3 根大阳线，连续大阳线数量正确；
最近 3 根累计跌幅可复算；
最近 6 根累计涨幅可复算；
high = low 时位置类特征为 null 且证据说明原因；
窗口不足时 failed，不用 0 伪装正常；
不访问 Binance、账户、订单、成交、PriceSnapshot 或大模型。
```

## 11. 禁止项

禁止：

```text
在 FeatureLayer 输出风险阻断；
在 FeatureLayer 输出交易动作；
在 FeatureLayer 输出目标仓位；
在 FeatureLayer 读取账户持仓；
在 FeatureLayer 请求 Binance；
在 FeatureLayer 调用大模型；
重复计算 volatility / structure 已经定义的同义特征；
把“单根大跌”直接解释成交易链路处理结果；
把“单根大涨”直接解释成交易方向。
```
