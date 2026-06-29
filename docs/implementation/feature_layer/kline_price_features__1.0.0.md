# kline_price_features / 1.0.0 实现记录

## 1. 定位

`kline_price_features / 1.0.0` 是 FeatureLayer 的通用 K 线价格特征 calculator。

它只基于 MarketSnapshot 已冻结的 1d / 4h 已收盘 K 线计算基础数值事实，不生成原子信号、领域结论、市场环境、策略判断、目标仓位或订单动作。

## 2. 输入

正式输入来自 FeatureLayerService 传入的 `CalculatorInput`：

```text
values.market_snapshot.1d
values.market_snapshot.4h
frozen_params
```

每根 K 线只使用：

```text
open_time_utc
close_time_utc
open
high
low
close
volume
```

calculator 不请求 Binance，不读取 PriceSnapshot，不读取账户、持仓、订单或成交。

## 3. 输出

成功时统一输出：

```text
values.value
```

由 FeatureDefinition.value_type 决定落库到 FeatureValue 的数值字段。

当前实现主要输出 Decimal；计数类特征也以 Decimal 形式交给 FeatureValue 落库。

## 4. 已实现的通用 operation

当前版本支持以下基础 operation：

```text
latest_close
latest_volume
volume_sma
sma
close_vs_sma_pct
slope_sma
sma_spread_pct
rolling_high
rolling_low
distance_from_rolling_high_pct
distance_from_rolling_low_pct
range_position_pct
drawdown_from_high_pct
drawdown_duration_bars
drawdown_low_since_high
rebound_from_drawdown_low_pct
rebound_duration_bars
recovery_ratio_from_drawdown
return_pct
previous_return_pct
return_delta_pct
up_bar_ratio
down_bar_ratio
consecutive_up_count
consecutive_down_count
movement_efficiency
close_location_pct_latest
close_location_avg_pct
atr
atr_pct
realized_vol_pct
atr_percentile
realized_vol_percentile
candle_range_pct_latest
candle_body_pct_latest
candle_body_ratio_latest
upper_shadow_ratio_latest
lower_shadow_ratio_latest
range_width_pct
volatility_ratio
latest_close_return_pct
latest_body_return_pct
latest_abs_body_return_pct
latest_close_location_ratio
latest_close_near_high_distance_pct
latest_close_near_low_distance_pct
consecutive_large_bear_body_count
consecutive_large_bull_body_count
large_body_same_direction_count
cumulative_return_pct
max_single_body_return_pct
min_single_body_return_pct
from_intrabar_high_reversal_pct
from_intrabar_low_recovery_pct
two_bar_opposite_reversal_pct
higher_high_count
higher_low_count
lower_high_count
lower_low_count
structure_zone_metric
```

这些 operation 覆盖 market_context、trend、momentum、volatility、risk_state 和 structure 第一批基础特征所需的计算口径。

## 5. 关键算法口径

SMA：

```text
最近 N 根 K 线指定价格字段的算术平均。
默认价格字段为 close。
```

均线斜率：

```text
(current_sma - lagged_sma) / lagged_sma
```

窗口收益率：

```text
(latest_close - first_close) / first_close
```

实现波动率：

```text
窗口内收盘收益率的总体标准差。
```

ATR 百分比：

```text
true_range = max(high - low, abs(high - previous_close), abs(low - previous_close))
atr = 最近 N 根 true_range 的算术平均
atr_pct = atr / latest_close
```

其中 `atr` 输出绝对价格幅度，`atr_pct` 输出相对当前收盘价的比例。

收盘位置：

```text
(close - low) / (high - low)
```

推进效率：

```text
abs(latest_close - first_close) / sum(abs(close_i - close_i-1))
```

大实体默认判断：

```text
abs((close - open) / open) >= max(0.018, 1.2 * median(abs(body_return_pct), 最近最多 60 根 4h))
```

固定分块高低点计数：

```text
取最近 window 根已收盘 K 线；
按 block_size 等长分块；
分别计算每块最高价 / 最低价；
相邻块最高价抬高则 higher_high_count + 1；
相邻块最低价抬高则 higher_low_count + 1；
相邻块最高价降低则 lower_high_count + 1；
相邻块最低价降低则 lower_low_count + 1。
```

structure zone metric：

```text
取最近 window 根已收盘 K 线；
最新一根 K 线只用于当前位置，不参与 swing 点识别；
按 swing_left_right 识别 swing low / swing high；
用 median((high - low) / close) 与 default_min_half_width_pct 取较大值作为区间半宽；
把价格接近的 swing 点聚类为支撑区或压力区；
触碰必须在 confirmation_window 内出现 min_reaction_pct 以上反应才计数；
score = 0.45 * touch_count_score + 0.30 * recency_score + 0.25 * reaction_score；
支撑区取当前价下方或当前价所在区间中距离最近的一组；
压力区取当前价上方或当前价所在区间中距离最近的一组。
```

`structure_zone_metric` 通过 `params.metric` 输出单个数值事实，例如：

```text
support_lower
support_upper
resistance_lower
resistance_upper
support_touch_count
resistance_touch_count
support_score
resistance_score
distance_to_support_upper_pct
distance_to_resistance_lower_pct
range_position_pct
range_width_pct
breakout_above_resistance_pct
breakdown_below_support_pct
```

如果对应支撑区或压力区不存在，且 FeatureDefinition.params.nullable = true，则该特征允许成功输出 null，并由 FeatureValue.numeric_value 保存为空。

## 6. 不可计算处理

以下情况返回 failed CalculatorOutput：

```text
缺少 timeframe；
K 线窗口不足；
Decimal 字段非法；
分母小于或等于 0；
operation 不支持；
必填参数缺失或非法。
```

FeatureLayerService 收到 failed 输出后按 FeatureLayer 主流程处理，不用 0 或默认值伪装。

## 7. 版本说明

本实现记录只描述 `kline_price_features / 1.0.0` 的代码口径。

单个 FeatureDefinition 的参数、窗口、feature_code、value_type 和是否进入正式 StrategyAnalysisRelease，由对应 FeatureDefinition 和版本包决定。
