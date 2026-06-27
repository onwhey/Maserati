# 策略特征设计说明

## 1. 文档定位

本文档用于根据 [策略原子信号设计说明](../atomic_signals/strategy_atomic_signal_design.md) 倒推策略分析链路需要的 Feature 类型。

本文档回答：

```text
AtomicSignal 需要哪些基础数值事实；
这些事实应该由 FeatureLayer 如何分类；
哪些特征服务于 market_context / trend / momentum / volatility / structure / risk_state；
哪些特征适合作为 P0 候选；
哪些特征只适合后续研究；
哪些内容不应该写入 FeatureLayer。
```

本文档不定义具体算法公式、阈值或正式参数，不批准任何正式 FeatureDefinition。

任何特征要进入正式主链路，仍必须具备：

```text
独立算法 requirements；
implementation 实现记录；
测试和回测证据；
StrategyAnalysisRelease 选择、验证、人工批准和启用。
```

## 2. FeatureLayer 的边界

FeatureLayer 只负责把 MarketSnapshot 固定的 K 线窗口转换为中性数值事实。

FeatureLayer 不负责：

```text
判断条件是否成立；
判断 bullish / bearish；
生成 AtomicSignal；
生成 DomainSignal；
识别 MarketRegime；
选择策略；
执行策略算法；
输出目标仓位；
读取账户；
读取 PriceSnapshot；
访问 Binance；
调用大模型；
生成订单动作。
```

FeatureLayer 只能消费：

```text
MarketSnapshot 固定的 4h / 1d 已收盘 K 线窗口。
```

FeatureLayer 不得：

```text
自行选择最新 K 线；
自行扩大或缩小 MarketSnapshot 窗口；
读取未收盘 K 线；
读取 PriceSnapshot 的 mark price；
把完整 K 线数组写入 FeatureValue；
把特征比较结果写成信号；
把支撑压力解释成交易动作。
```

## 3. 设计顺序

策略特征设计采用以下倒推路径：

```text
领域问题
→ AtomicSignal 类型
→ Feature 类型
→ 后续正式 FeatureDefinition
```

例如：

```text
structure 领域需要判断当前是否靠近支撑区；
AtomicSignal 需要“当前价格距离支撑区百分比”；
FeatureLayer 因此需要计算支撑区上下沿、当前收盘价、距离支撑区百分比。
```

这不表示系统运行时自动推导 Feature。

正式运行时必须由 StrategyAnalysisRelease 冻结明确的 FeatureDefinition 集合。

## 4. 特征命名原则

FeatureCode 应显式表达：

```text
周期；
窗口；
数据来源；
计算对象；
必要参数。
```

推荐：

```text
sma_1d_200
rolling_high_1d_365
rolling_low_4h_120
atr_pct_4h_14
range_width_pct_4h_120
distance_to_support_upper_pct_4h_120
```

不推荐：

```text
main_sma
big_trend
support
pressure
entry_feature
buy_area
```

FeatureCode 不得包含交易动作语义。

## 5. 特征值形态

FeatureValue 应优先保存：

```text
数值；
百分比；
计数；
枚举所需的原始数值；
紧凑结构事实。
```

对于支撑压力区间，优先拆成多个 FeatureValue：

```text
support_lower_4h_120
support_upper_4h_120
resistance_lower_4h_120
resistance_upper_4h_120
```

如果后续算法 requirements 明确允许小型结构值，也必须满足：

```text
结构固定；
字段有限；
可复算；
不得保存完整历史窗口；
不得把大批量 K 线塞入 JSON。
```

## 6. market_context 特征

### 6.1 目的

market_context 特征用于支持大级别背景判断。

它们只描述：

```text
长期价格位置；
长期趋势斜率；
长期区间位置；
长期回撤深度；
长期回撤持续时间；
长期反弹幅度；
长期反弹持续时间；
长期反弹收复程度；
长期收益状态。
```

### 6.2 P0 候选特征

| 特征类型 | 业务含义 | 示例 FeatureCode | 服务的原子信号 |
|---|---|---|---|
| 长期均线 | 表达长期价格参考线 | sma_1d_120 / sma_1d_200 / sma_1d_365 | 长期价格位于长期均线上方 / 下方 |
| 长期均线斜率 | 表达长期趋势线方向变化 | slope_sma_1d_200 | 长期均线斜率向上 / 向下 |
| 长期滚动高点 | 表达近一年高位参考 | rolling_high_1d_365 | 当前处于近一年高位区 |
| 长期滚动低点 | 表达近一年低位参考 | rolling_low_1d_365 | 当前处于近一年低位区 |
| 长期区间位置 | 当前价格在近一年区间的位置 | range_position_pct_1d_365 | 高位区 / 低位区判断 |
| 长期回撤深度 | 从长期高点回撤百分比 | drawdown_from_high_pct_1d_365 | 大级别回撤未破坏 / 过深 |
| 长期回撤持续时间 | 从长期高点回撤后持续的天数 | drawdown_duration_days_1d_365 | 牛市回调 / 熊市反弹研究 |
| 长期反弹幅度 | 从回撤低点反弹的百分比 | rebound_from_drawdown_low_pct_1d_365 | 熊市反弹研究 |
| 长期反弹持续时间 | 从回撤低点反弹后持续的天数 | rebound_duration_days_1d_365 | 熊市反弹研究 |
| 长期反弹收复比例 | 从回撤低点反弹后收复跌幅的比例 | recovery_ratio_from_drawdown_1d_365 | 牛市回调 / 熊市反弹研究 |
| 长期收益 | 长窗口涨跌幅 | return_pct_1d_365 | 长期收益为正 / 负 |

### 6.3 P1 / P2 研究特征

```text
rolling_high_1d_730；
rolling_low_1d_730；
range_position_pct_1d_730；
drawdown_from_cycle_high_pct；
higher_high_count_1d_365；
lower_low_count_1d_365。
```

这些特征需要更长历史数据和更严格的周期定义，暂不建议作为第一版正式必要特征。

## 7. trend 特征

### 7.1 目的

trend 特征用于支持趋势方向、趋势强度和多周期一致性判断。

它们只描述趋势数值事实，不输出趋势结论。

### 7.2 P0 候选特征

| 特征类型 | 业务含义 | 示例 FeatureCode | 服务的原子信号 |
|---|---|---|---|
| 4h 短均线 | 短周期趋势参考 | sma_4h_20 | 4h 短期趋势偏多 / 偏空 |
| 4h 长均线 | 短周期慢速趋势参考 | sma_4h_60 | 4h 短期趋势偏多 / 偏空 |
| 1d 短均线 | 日线短趋势参考 | sma_1d_20 | 1d 中长期趋势判断 |
| 1d 长均线 | 日线慢趋势参考 | sma_1d_60 / sma_1d_120 | 1d 中长期趋势判断 |
| 均线斜率 | 趋势推进方向变化 | slope_sma_4h_20 / slope_sma_1d_60 | 趋势斜率增强 / 减弱 |
| 价格相对均线距离 | 价格距离趋势参考线的百分比 | close_vs_sma_pct_4h_20 / close_vs_sma_pct_1d_60 | 价格持续位于趋势均线上方 / 下方 |
| 高低点结构计数 | 近期高低点是否持续抬高或降低 | higher_high_count_4h_60 / lower_low_count_4h_60 | 趋势结构尚未破坏 / 已破坏 |

### 7.3 P1 / P2 研究特征

```text
ema_4h_20；
ema_4h_60；
ema_1d_120；
trend_channel_slope_4h_120；
trend_channel_slope_1d_120；
pullback_depth_pct_from_recent_high；
distance_to_trendline_pct。
```

趋势线和通道类特征需要明确算法，不能靠人工画线或事后拟合。

## 8. momentum 特征

### 8.1 目的

momentum 特征用于支持动量增强、减弱、衰竭和突破质量判断。

它们只提供动量数值事实，不判断是否应该交易。

### 8.2 P0 候选特征

| 特征类型 | 业务含义 | 示例 FeatureCode | 服务的原子信号 |
|---|---|---|---|
| 窗口收益率 | 短窗口和中窗口涨跌幅 | return_pct_4h_12 / return_pct_4h_24 | 短周期多头 / 空头推进存在 |
| 日线收益率 | 日线级别涨跌幅 | return_pct_1d_3 / return_pct_1d_7 | 日线多头 / 空头推进存在 |
| 前后窗口收益率 | 当前窗口相对前一窗口的推进变化 | previous_return_pct_4h_12 / return_delta_pct_4h_12 | 动量增强 / 衰竭 |
| 上涨 / 下跌 K 线占比 | 窗口内方向连续性 | up_bar_ratio_4h_24 / down_bar_ratio_4h_24 | 推进连续 / 推进混乱 |
| 连续上涨 / 连续下跌数量 | 最新一段价格是否连续推进 | consecutive_up_count_4h_24 / consecutive_down_count_4h_24 | 连续推进 / 推进被打断 |
| 推进效率 | 净推进相对路径波动的效率 | movement_efficiency_4h_24 / movement_efficiency_1d_7 | 推进顺畅 / 拉扯严重 |
| 收盘位置 | 收盘价在单根或窗口高低区间中的位置 | close_location_pct_4h_latest / close_location_avg_pct_4h_12 | 收盘强弱 |

### 8.3 P1 / P2 研究特征

```text
macd_line_4h；
macd_histogram_4h；
macd_histogram_slope_4h；
rsi_4h_14；
rsi_1d_14；
adx_4h_14；
adx_1d_14；
momentum_divergence_score；
volume_confirmed_momentum。
```

MACD、RSI、ADX、背离类特征需要单独算法 requirements，不得只凭指标名实现。

## 9. volatility 特征

### 9.1 目的

volatility 特征用于支持波动状态判断。

它们描述：

```text
当前波动大小；
波动分位；
波动压缩或扩张；
单根 K 线是否异常；
区间宽度是否过大或过小。
```

### 9.2 P0 候选特征

| 特征类型 | 业务含义 | 示例 FeatureCode | 服务的原子信号 |
|---|---|---|---|
| ATR 百分比 | 标准化波动幅度 | atr_pct_4h_14 / atr_pct_1d_14 | 波动正常 / 异常高波动 |
| 已实现波动率 | 多窗口收盘收益率波动 | realized_vol_pct_4h_20 / realized_vol_pct_1d_20 | 波动压缩 / 扩张 |
| 波动历史分位 | 当前波动在历史窗口中的位置 | atr_percentile_4h_120 / realized_vol_percentile_4h_120 | 波动正常 / 过高 / 过低 |
| K 线振幅、实体和影线 | 单根 K 线高低振幅、实体和影线结构 | candle_range_pct_4h_latest / upper_shadow_ratio_4h_latest | 单根 K 线振幅异常 |
| 行情高低区间宽度 | 最近行情高低活动范围宽度 | range_width_pct_4h_120 / range_width_pct_1d_60 | 宽幅震荡 / 窄幅整理 |
| 短长波动比 | 短窗口波动相对长窗口波动的比例 | volatility_ratio_4h_20_to_60 | 波动压缩 / 扩张 |

### 9.3 P1 / P2 研究特征

```text
volatility_contraction_score；
volatility_expansion_score；
multi_window_volatility_ratio；
gap_or_jump_pct；
extreme_bar_count_4h_20；
bollinger_band_width_4h_20；
keltner_channel_width_4h_20。
```

这些特征需要定义清楚窗口、分位参考、异常标准和数据来源。

## 10. structure 特征

### 10.1 目的

structure 特征用于支持支撑压力、区间结构和价格位置判断。

它们只描述结构事实，不输出交易动作。

### 10.2 P0 候选特征

| 特征类型 | 业务含义 | 示例 FeatureCode | 服务的原子信号 |
|---|---|---|---|
| 4h 滚动高点 | 短中期压力参考 | rolling_high_4h_120 | 靠近压力、突破压力 |
| 4h 滚动低点 | 短中期支撑参考 | rolling_low_4h_120 | 靠近支撑、跌破支撑 |
| 1d 滚动高点 | 日线压力参考 | rolling_high_1d_120 | 高位区间压力 |
| 1d 滚动低点 | 日线支撑参考 | rolling_low_1d_120 | 高位区间支撑 |
| 支撑区下沿 | 支撑价格带下边界 | support_lower_4h_120 | 支撑区判断 |
| 支撑区上沿 | 支撑价格带上边界 | support_upper_4h_120 | 距离支撑判断 |
| 压力区下沿 | 压力价格带下边界 | resistance_lower_4h_120 | 距离压力判断 |
| 压力区上沿 | 压力价格带上边界 | resistance_upper_4h_120 | 压力区判断 |
| 距离支撑百分比 | 当前价格距离支撑区的百分比 | distance_to_support_upper_pct_4h_120 | 当前靠近支撑区 |
| 距离压力百分比 | 当前价格距离压力区的百分比 | distance_to_resistance_lower_pct_4h_120 | 当前靠近压力区 |
| 区间位置百分比 | 当前价格在区间中的位置 | range_position_pct_4h_120 | 区间中部 / 靠近边界 |
| 区间宽度百分比 | 支撑压力区间相对宽度 | range_width_pct_4h_120 | 宽幅震荡 / 窄幅整理 |
| 支撑触碰次数 | 价格测试支撑区次数 | support_touch_count_4h_120 | 支撑区多次有效 |
| 压力触碰次数 | 价格测试压力区次数 | resistance_touch_count_4h_120 | 压力区多次有效 |
| 突破幅度 | 收盘价突破压力区的距离 | breakout_above_resistance_pct_4h_120 | 向上突破压力区 |
| 跌破幅度 | 收盘价跌破支撑区的距离 | breakdown_below_support_pct_4h_120 | 向下跌破支撑区 |

### 10.3 P1 / P2 研究特征

```text
range_duration_bars_4h；
range_boundary_clarity_score_4h；
false_breakout_reversal_pct_4h；
retest_support_depth_pct_4h；
retest_resistance_height_pct_4h；
support_resistance_role_flip_score；
high_level_range_score_1d；
low_level_range_score_1d。
```

这些特征涉及更复杂结构识别，必须先有明确算法文档。

### 10.4 排除当前 K 线规则

用于判断突破或区间边界的滚动高低点，必须明确是否排除当前判断 K 线。

原则：

```text
用于判断“是否突破”的参考区间，必须排除当前 K 线；
否则当前 K 线自己会把区间高点抬高，导致突破条件失真。
```

后续正式算法 requirements 必须明确：

```text
rolling_high / rolling_low 是否排除当前 K 线；
窗口结束位置；
窗口包含的 K 线数量；
边界处理方式。
```

## 11. risk_state 特征

### 11.1 目的

risk_state 特征用于支持市场状态风险判断。

它们只描述市场风险事实，不等同于账户风控。

risk_state 可以复用 K 线振幅、ATR 分位、实体比例和影线比例等中性特征作为证据，但输出语义必须是“异常行情是否让信号可靠性下降”，不得重复输出“高波动 / 低波动”这类 volatility 结论。

### 11.2 P0 候选特征

| 特征类型 | 业务含义 | 示例 FeatureCode | 服务的原子信号 |
|---|---|---|---|
| 单根振幅证据 | 为异常行情风险判断提供波动强度证据 | candle_range_pct_4h_latest | 异常波动环境下信号可靠性下降 |
| 实体占比 | K 线推进是否强烈 | candle_body_ratio_4h_latest | 急涨急跌风险 |
| 上影线比例 | 冲高回落风险 | upper_shadow_ratio_4h_latest | 压力附近追涨风险 |
| 下影线比例 | 下探回收或插针风险 | lower_shadow_ratio_4h_latest | 支撑附近风险观察 |
| 连续下跌数量 | 急跌延续风险 | consecutive_down_count_4h_20 | 连续大阴线风险 |
| 连续上涨数量 | 追高风险 | consecutive_up_count_4h_20 | 连续大阳线追高风险 |
| 突破失败回撤 | 突破后被打回幅度 | failed_breakout_reversal_pct_4h_120 | 突破后快速失败 |
| 跌破后反抽失败 | 跌破支撑后反抽不过 | failed_reclaim_pct_4h_120 | 结构跌破后尚未稳定 |

### 11.3 P1 / P2 研究特征

```text
wick_spike_score；
panic_drop_score；
blowoff_top_score；
liquidity_proxy_score；
spread_or_depth_risk。
```

其中价差和深度风险需要新增数据采集能力，当前 P0 K 线数据范围不支持正式实现。

## 12. 特征复用关系

同一个 Feature 可以服务多个 AtomicSignal。

例如：

```text
rolling_high_4h_120
```

可以服务：

```text
当前靠近压力区；
向上突破压力区；
区间宽度计算；
高位区间判断。
```

但复用不等于重复计算。

正式版本包应只选择一份 FeatureDefinition，由多个 AtomicSignal 通过 FeatureValue 引用。

## 13. 不应放入 FeatureLayer 的内容

### 13.1 条件判断

以下不应成为 Feature：

```text
close_above_sma；
sma_fast_above_sma_slow；
near_support_is_true；
breakout_confirmed；
volatility_too_high；
trend_is_bullish。
```

这些属于 AtomicSignal。

### 13.2 领域判断

以下不应成为 Feature：

```text
trend_domain_bullish；
market_context_bullish；
structure_near_support；
uptrend_range_regime。
```

这些属于 DomainSignal 或 MarketRegime。

### 13.3 策略判断

以下不应成为 Feature：

```text
support_long_signal；
pressure_reduce_signal；
breakout_entry_signal；
risk_off_signal。
```

这些属于 StrategySignal。

### 13.4 目标仓位或订单语义

以下绝对不应成为 Feature：

```text
target_position_ratio；
position_size；
leverage；
stop_loss；
take_profit；
order_qty；
should_buy；
should_sell。
```

## 14. P0 最小特征组合建议

如果只为了支撑第一批策略研究，P0 可以先围绕以下最小组合：

```text
长期均线和长期区间位置；
4h / 1d 趋势均线和斜率；
4h / 1d 动量收益率；
ATR 百分比和波动分位；
4h / 1d 滚动高低点；
支撑压力区上下沿；
距离支撑压力百分比；
区间宽度和位置；
回撤深度、回撤持续时间、反弹幅度和反弹持续时间；
单根 K 线振幅、实体、影线；
连续上涨 / 下跌数量。
```

这个组合优先服务：

```text
long_trend_following_breakout；
long_bullish_pullback_range；
short_trend_following_breakdown；
short_bearish_rebound_rejection。
```

## 15. 与 StrategyAnalysisRelease 的关系

本文档列出的所有特征都只是候选设计。

正式运行只允许计算：

```text
被当前 StrategyAnalysisRelease 特征切片明确选中；
状态 active；
依赖关系完整；
calculator 已注册；
算法 requirements 与 implementation 记录完整；
验证证据完整。
```

没有被版本包选择的 FeatureDefinition，即使已经 active，也不得进入正式 FeatureSet。

## 16. 下一步文档拆分建议

如果确认本设计，建议后续按以下顺序补充：

```text
docs/requirements/feature_layer/market_context_features.md
docs/requirements/feature_layer/trend_features.md
docs/requirements/feature_layer/momentum_features.md
docs/requirements/feature_layer/volatility_features.md
docs/requirements/feature_layer/structure_features.md
docs/requirements/feature_layer/risk_state_features.md
```

这些后续文件才定义：

```text
具体 feature_code；
具体算法；
具体窗口；
具体参数；
具体输出类型；
具体 warmup_bars；
具体失败条件；
具体测试向量；
具体回测验证要求。
```

## 17. 明确禁止

禁止：

```text
让 FeatureLayer 生成看多或看空判断；
让 FeatureLayer 判断支撑是否有效；
让 FeatureLayer 判断是否靠近支撑或压力；
让 FeatureLayer 判断是否突破或跌破；
让 FeatureLayer 生成 AtomicSignal；
让 FeatureLayer 生成 MarketRegime；
让 FeatureLayer 生成 StrategySignal；
让 FeatureLayer 输出目标仓位或订单动作；
让 FeatureLayer 读取 PriceSnapshot、账户、持仓或 Binance；
让 FeatureLayer 保存完整 K 线历史数组；
绕过 StrategyAnalysisRelease 直接计算候选特征。
```
