# Risk State Atomic Signals

## 1. 文件定位

本文档定义 `risk_state` 领域第一版原子信号目录。

这些原子信号基于 [Risk State Features](../feature_layer/risk_state_features.md)、[Volatility Features](../feature_layer/volatility_features.md) 和 [Structure Features](../feature_layer/structure_features.md) 输出的 FeatureValue，形成最小风险判断。

本文档不是一个整体算法版本。本文档中的每个 AtomicSignalDefinition 独立版本化、独立注册、独立进入 StrategyAnalysisRelease。

也就是说：

```text
risk_long_exposure_shock_down 可以有自己的 v1 / v2；
risk_false_breakout_rejection 可以有自己的 v1 / v2；
risk_short_chase_after_down_shock 可以有自己的 v1 / v2；
本文档本身不表示“risk_state atomic signal v1 整体版本”。
```

## 2. 核心边界

risk_state AtomicSignal 只判断市场风险事实，不判断账户风险。

它不读取：

```text
账户；
持仓；
订单；
成交；
PriceSnapshot；
Binance；
DeepSeek；
StrategySignal；
DecisionSnapshot。
```

它不输出：

```text
交易方向；
仓位动作；
止损；
目标仓位；
订单动作。
```

特别注意：

```text
风险升高不等于“不操作”；
风险升高也不等于“少做”；
如果系统已经有仓位，不操作本身也可能是风险暴露。
```

risk_state 原子信号只能表达：

```text
信号可靠性风险；
多头方向暴露风险；
空头方向暴露风险；
追多风险；
追空风险；
假突破 / 假跌破风险；
行情脏数据或极端扰动风险。
```

真实持仓如何处理由 StrategySignal / DecisionSnapshot / OrderPlan / RiskCheck / Execution 后续链路决定。

## 3. FeatureValue 依赖原则

risk_state AtomicSignal 是 FeatureValue 用户，不是 Feature 计算器。

它可以读取同一版本包中声明的 FeatureValue：

```text
risk_state 专属 FeatureValue；
volatility FeatureValue；
structure FeatureValue。
```

但不得：

```text
重新计算 ATR；
重新计算支撑压力；
重新计算 K 线实体；
重新读取 Kline；
重新请求 Binance；
在原子层写 feature 算法。
```

如果多个 risk_state 原子信号需要同一个基础特征，必须读取同一个 FeatureValue。

例如：

```text
candle_body_pct_4h_latest 只能由 volatility FeatureDefinition 或共享 FeatureDefinition 计算一次；
risk_long_exposure_shock_down 和 risk_short_chase_after_down_shock 都读取同一份 candle_body_pct_4h_latest；
不得两个原子各自计算一份实体百分比。
```

## 4. 输出模式

本版本 risk_state AtomicSignal 使用非交易动作输出。

每个 AtomicSignalValue 至少包含：

```text
signal_code；
status；
is_valid；
risk_category；
risk_direction；
risk_severity；
condition_met；
strength；
evidence_items；
evidence_text_zh。
```

### 4.1 risk_category

允许值：

```text
signal_reliability_risk；
long_exposure_risk；
short_exposure_risk；
long_chase_risk；
short_chase_risk；
false_breakout_risk；
false_breakdown_risk；
market_disorder_risk。
```

含义：

```text
signal_reliability_risk = 普通信号可靠性下降；
long_exposure_risk = 如果存在多头方向暴露，该行情对多头不友好；
short_exposure_risk = 如果存在空头方向暴露，该行情对空头不友好；
long_chase_risk = 当前位置继续追多的行情风险较高；
short_chase_risk = 当前位置继续追空的行情风险较高；
false_breakout_risk = 向上突破信号可能失真；
false_breakdown_risk = 向下跌破信号可能失真；
market_disorder_risk = 行情过度混乱，普通分类可靠性下降。
```

这些都是条件性市场风险，不表示系统当前一定有对应持仓。

### 4.2 risk_direction

允许值：

```text
upside；
downside；
two_sided；
none。
```

示例：

```text
单根 4h 实体大跌 → downside；
单根 4h 实体大涨 → upside；
长上下影和极高波动混合 → two_sided；
纯粹不明确风险 → none。
```

### 4.3 risk_severity

允许值：

```text
none；
elevated；
high。
```

`high` 只表示该原子风险严重，不等于最终 DomainSignal 一定 risk_high_signal_unreliable。

## 5. 参数

本版本使用以下默认参数：

| 参数 | 值 | 说明 |
|---|---:|---|
| 大实体冲击阈值 | 4.0% | 单根 4h 实体涨跌幅绝对值达到该值认为冲击明显 |
| 极端实体冲击阈值 | 7.0% | 单根 4h 实体涨跌幅绝对值达到该值认为冲击极端 |
| 收盘靠近高点阈值 | 0.80 | close_location_ratio >= 0.80 |
| 收盘靠近低点阈值 | 0.20 | close_location_ratio <= 0.20 |
| 长上影阈值 | 0.45 | upper_shadow_ratio >= 0.45 |
| 长下影阈值 | 0.45 | lower_shadow_ratio >= 0.45 |
| ATR 高分位阈值 | 0.80 | atr_percentile_4h_120 >= 0.80 |
| ATR 极高分位阈值 | 0.95 | atr_percentile_4h_120 >= 0.95 |
| 连续大实体阈值 | 3 | 连续大阳 / 大阴达到 3 根 |
| 结构突破 / 跌破有效幅度 | 0.4% | 使用 4h 小结构默认突破 / 跌破阈值 |

这些参数属于对应 AtomicSignalDefinition 的默认参数。后续调整必须新增原子信号版本。

## 6. P0 原子信号定义

### 6.1 下行冲击下的多头暴露风险

```text
signal_code = risk_long_exposure_shock_down
risk_category = long_exposure_risk
risk_direction = downside
```

成立条件：

```text
risk_latest_body_return_pct_4h <= -4.0%
且 candle_body_ratio_4h_latest >= 0.60
且 risk_latest_close_location_ratio_4h <= 0.35。
```

强化条件：

```text
risk_latest_body_return_pct_4h <= -7.0%
或 atr_percentile_4h_120 >= 0.95
或 structure_major_breakdown_below_support_pct_1d_365 > 0。
```

输出：

```text
condition_met = true；
risk_severity = high，如果满足任一强化条件；
否则 risk_severity = elevated。
```

业务含义：

```text
如果系统存在多头方向暴露，这类行情对多头不友好。
```

它不表示：

```text
直接生成仓位处理结论；
直接形成反向交易目标；
不形成交易目标；
目标仓位归零。
```

### 6.2 上行冲击下的空头暴露风险

```text
signal_code = risk_short_exposure_shock_up
risk_category = short_exposure_risk
risk_direction = upside
```

成立条件：

```text
risk_latest_body_return_pct_4h >= 4.0%
且 candle_body_ratio_4h_latest >= 0.60
且 risk_latest_close_location_ratio_4h >= 0.65。
```

强化条件：

```text
risk_latest_body_return_pct_4h >= 7.0%
或 atr_percentile_4h_120 >= 0.95
或 structure_major_breakout_above_resistance_pct_1d_365 > 0。
```

业务含义：

```text
如果系统存在空头方向暴露，这类行情对空头不友好。
```

### 6.3 急跌后的追空风险

```text
signal_code = risk_short_chase_after_down_shock
risk_category = short_chase_risk
risk_direction = downside
```

成立条件：

```text
risk_latest_body_return_pct_4h <= -4.0%
且 atr_percentile_4h_120 >= 0.80
且 risk_latest_close_location_ratio_4h <= 0.35。
```

强化条件：

```text
risk_latest_body_return_pct_4h <= -7.0%
或 risk_consecutive_large_bear_body_count_4h_20 >= 3。
```

业务含义：

```text
行情已经出现明显下行冲击，当前位置继续追空的风险升高。
```

它不否定空头趋势，也不生成空头处理结论；它只描述当前位置的追空风险已经升高。

### 6.4 急涨后的追多风险

```text
signal_code = risk_long_chase_after_up_shock
risk_category = long_chase_risk
risk_direction = upside
```

成立条件：

```text
risk_latest_body_return_pct_4h >= 4.0%
且 atr_percentile_4h_120 >= 0.80
且 risk_latest_close_location_ratio_4h >= 0.65。
```

强化条件：

```text
risk_latest_body_return_pct_4h >= 7.0%
或 risk_consecutive_large_bull_body_count_4h_20 >= 3。
```

业务含义：

```text
行情已经出现明显上行冲击，当前位置继续追多的风险升高。
```

### 6.5 向上突破快速失败风险

```text
signal_code = risk_false_breakout_rejection
risk_category = false_breakout_risk
risk_direction = upside
```

成立条件：

```text
structure_minor_breakout_above_resistance_pct_4h_120 > 0
且 upper_shadow_ratio_4h_latest >= 0.45
且 risk_latest_close_location_ratio_4h <= 0.55。
```

强化条件：

```text
atr_percentile_4h_120 >= 0.95
或 risk_latest_from_intrabar_high_reversal_pct_4h >= 2.5%。
```

业务含义：

```text
向上突破后被明显打回，突破信号可靠性下降。
```

### 6.6 向下跌破快速收回风险

```text
signal_code = risk_false_breakdown_reclaim
risk_category = false_breakdown_risk
risk_direction = downside
```

成立条件：

```text
structure_minor_breakdown_below_support_pct_4h_120 > 0
且 lower_shadow_ratio_4h_latest >= 0.45
且 risk_latest_close_location_ratio_4h >= 0.45。
```

强化条件：

```text
atr_percentile_4h_120 >= 0.95
或 risk_latest_from_intrabar_low_recovery_pct_4h >= 2.5%。
```

业务含义：

```text
向下跌破后被明显收回，跌破信号可靠性下降。
```

### 6.7 连续急跌导致市场扰动

```text
signal_code = risk_consecutive_down_disorder
risk_category = market_disorder_risk
risk_direction = downside
```

成立条件：

```text
risk_consecutive_large_bear_body_count_4h_20 >= 3
或 risk_cumulative_return_pct_4h_3 <= -8.0%。
```

强化条件：

```text
atr_percentile_4h_120 >= 0.95
或 realized_vol_percentile_4h_120 >= 0.95。
```

业务含义：

```text
短周期连续急跌，普通结构和趋势信号的可靠性可能下降。
```

### 6.8 连续急涨导致市场扰动

```text
signal_code = risk_consecutive_up_disorder
risk_category = market_disorder_risk
risk_direction = upside
```

成立条件：

```text
risk_consecutive_large_bull_body_count_4h_20 >= 3
或 risk_cumulative_return_pct_4h_3 >= 8.0%。
```

强化条件：

```text
atr_percentile_4h_120 >= 0.95
或 realized_vol_percentile_4h_120 >= 0.95。
```

业务含义：

```text
短周期连续急涨，普通结构和趋势信号的可靠性可能下降。
```

### 6.9 双向剧烈扫动风险

```text
signal_code = risk_two_sided_whipsaw
risk_category = signal_reliability_risk
risk_direction = two_sided
```

成立条件：

```text
upper_shadow_ratio_4h_latest >= 0.45
且 lower_shadow_ratio_4h_latest >= 0.35
且 atr_percentile_4h_120 >= 0.80。
```

强化条件：

```text
atr_percentile_4h_120 >= 0.95
或 realized_vol_percentile_4h_120 >= 0.95。
```

业务含义：

```text
最新 4h 同时出现明显上扫和下扫，普通突破 / 跌破判断容易失真。
```

## 7. 不应放入 risk_state AtomicSignal 的判断

禁止：

```text
风险高所以本轮不形成交易目标；
风险高所以调整仓位；
风险高所以形成反向交易目标；
单根大跌所以一定形成空头交易目标；
单根大涨所以一定形成多头交易目标；
突破失败所以永久排除突破类策略；
账户当前多仓风险；
账户当前空仓风险；
保证金风险；
订单冲突风险。
```

这些属于 StrategySignal、DecisionSnapshot、RiskCheck 或交易执行链路。

## 8. 与 DomainSignal 的关系

risk_state DomainSignal 负责把这些原子风险聚合为：

```text
risk_clear；
risk_elevated_classifiable；
risk_high_signal_unreliable；
risk_unclear。
```

AtomicSignal 不直接输出这些领域状态。

## 9. 验收要求

至少覆盖以下场景：

```text
4h 实体大跌 8%，收盘靠近低点 → long_exposure_shock_down 成立；
4h 实体大跌 8%，高波动且收盘靠近低点 → short_chase_after_down_shock 成立；
4h 实体大涨 8%，收盘靠近高点 → short_exposure_shock_up 成立；
向上突破后长上影回落 → false_breakout_rejection 成立；
向下跌破后长下影收回 → false_breakdown_reclaim 成立；
连续 3 根大阴线 → consecutive_down_disorder 成立；
连续 3 根大阳线 → consecutive_up_disorder 成立；
长上下影且 ATR 高分位 → two_sided_whipsaw 成立；
同一基础 FeatureValue 被多个原子复用，不重复计算；
不读取账户、持仓、订单、成交、PriceSnapshot、Binance 或大模型；
不输出交易动作或目标仓位。
```

## 10. 禁止项

禁止：

```text
让 AtomicSignal 访问 Binance；
让 AtomicSignal 访问账户或持仓；
让 AtomicSignal 访问 PriceSnapshot；
让 AtomicSignal 重新计算 Feature；
让 AtomicSignal 读取 Kline；
让 AtomicSignal 输出交易动作；
让 AtomicSignal 输出目标仓位；
把风险升高直接解释为“不操作”；
把多头暴露风险解释为“系统当前一定有多仓”；
把空头暴露风险解释为“系统当前一定有空仓”。
```
