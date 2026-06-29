# Trend Features

## 1. 文档定位

本文档定义 trend 领域所需的 FeatureDefinition 候选目录。

本文档不是一个整体算法版本。本文档中的每个 FeatureDefinition 独立版本化、独立注册、独立进入 StrategyAnalysisRelease。

也就是说：

```text
sma_1d_20 可以有自己的 v1 / v2；
slope_sma_1d_60 可以有自己的 v1 / v2；
higher_high_count_1d_60_block20 可以有自己的 v1 / v2；
本文档本身不表示“trend feature v1 整体版本”。
```

trend 特征只回答“当前运行趋势的基础数值事实是什么”，不回答“任何交易处理方式”。

trend 特征服务于：

```text
AtomicSignal
→ DomainSignal.trend
→ MarketRegime
→ StrategyRouting
→ StrategySignal
```

trend 特征不得直接生成交易信号、目标仓位、订单意图或交易动作。

## 2. 与 market_context 的边界

market_context 负责大级别市场背景，例如：

```text
大级别偏多；
大级别偏空；
牛市回调；
熊市反弹；
长期高位或低位。
```

trend 负责当前运行趋势，例如：

```text
1d 趋势是否向上；
1d 趋势是否向下；
4h 是否与 1d 同向；
4h 是否只是 1d 趋势中的回调；
当前趋势推进是否仍然稳定。
```

trend 不判断当前是牛市还是熊市。

trend 不判断当前价格处于历史大级别高位还是低位。

trend 不判断支撑位或压力位下的交易处理。

## 3. 周期范围

当前 P0 数据采集范围只包含 Binance USDS-M BTCUSDT 的已收盘 4h / 1d K 线。

因此 trend 特征当前只允许使用：

```text
1d 已收盘 K 线；
4h 已收盘 K 线。
```

周期定位：

```text
1d = trend 主判断周期；
4h = trend 短周期趋势状态周期。
```

当前不引入 3d。

如果未来需要 3d，必须先修改 DataCollection / MarketSnapshot / FeatureLayer 相关需求，明确 3d 数据来源、窗口、质检和存储方式，不得在 trend feature calculator 内临时拼接 3d。

## 4. 输入数据要求

trend FeatureCalculator 只能读取 MarketSnapshot 冻结的 K 线窗口。

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
持仓；
订单；
成交；
人工画线结果；
外部新闻；
大模型输出。
```

trend FeatureCalculator 不得请求 Binance。

trend FeatureCalculator 不得自行扩大或缩小 MarketSnapshot 窗口。

## 5. 特征层与原子层的数据交接

FeatureLayer 是数据工厂，负责计算并落库 FeatureValue。

AtomicSignal 是数据用户，负责读取已经生成的 FeatureValue。

AtomicSignal 不得：

```text
自己计算 SMA；
自己计算 rolling high / rolling low；
自己计算斜率；
自己重算高低点结构；
调用 FeatureLayer 算法函数；
绕过 FeatureValue 直接读取 K 线重新算特征。
```

多个 AtomicSignal 需要同一个趋势特征时，必须引用同一个 FeatureValue，而不是各自重复计算。

## 6. P0 参数约定

初始 trend 特征使用以下参数约定：

| 参数 | 默认值 | 说明 |
|---|---:|---|
| 1d 均线窗口 | 20 / 60 / 120 | 表达日线短、中、慢趋势参考 |
| 4h 均线窗口 | 20 / 60 / 120 | 表达 4h 辅助趋势参考 |
| 1d 斜率回看 | 10 根 1d K 线 | 用于衡量均线方向变化 |
| 4h 斜率回看 | 12 根 4h K 线 | 约等于 2 天，用于观察短周期趋势推进 |
| 高低点结构窗口 | 60 根 K 线 | 用于观察近期高低点是否抬高或降低 |
| 高低点结构分块 | 3 组，每组 20 根 K 线 | 避免复杂主观 swing 识别 |
| 价格来源 | close | 均线、距离和收益类特征统一使用收盘价 |
| 高低点来源 | high / low | rolling high / rolling low 与结构计数使用 K 线高低价 |

这些参数是初始 FeatureDefinition 的参数，不是不可变系统红线。

如果某个特征升级算法或参数，应新增该 FeatureDefinition 的独立版本，而不是直接覆盖历史版本。

## 7. P0 FeatureDefinition

### 7.1 日线均线特征

| FeatureCode | 含义 | 输出类型 | warmup |
|---|---|---|---:|
| sma_1d_20 | 最近 20 根 1d 收盘价简单均线 | decimal | 20 |
| sma_1d_60 | 最近 60 根 1d 收盘价简单均线 | decimal | 60 |
| sma_1d_120 | 最近 120 根 1d 收盘价简单均线 | decimal | 120 |

这些特征只提供均线数值，不判断价格是否在均线上方。

### 7.2 4h 均线特征

| FeatureCode | 含义 | 输出类型 | warmup |
|---|---|---|---:|
| sma_4h_20 | 最近 20 根 4h 收盘价简单均线 | decimal | 20 |
| sma_4h_60 | 最近 60 根 4h 收盘价简单均线 | decimal | 60 |
| sma_4h_120 | 最近 120 根 4h 收盘价简单均线 | decimal | 120 |

4h 均线用于观察短周期趋势状态，不得替代 1d 主趋势判断。

### 7.3 收盘价相对均线距离

计算口径：

```text
(latest_close - sma) / sma
```

| FeatureCode | 含义 | 输出类型 | warmup |
|---|---|---|---:|
| close_vs_sma_pct_1d_20 | 1d 最新收盘价相对 20 日均线距离 | decimal | 20 |
| close_vs_sma_pct_1d_60 | 1d 最新收盘价相对 60 日均线距离 | decimal | 60 |
| close_vs_sma_pct_1d_120 | 1d 最新收盘价相对 120 日均线距离 | decimal | 120 |
| close_vs_sma_pct_4h_20 | 4h 最新收盘价相对 20 根 4h 均线距离 | decimal | 20 |
| close_vs_sma_pct_4h_60 | 4h 最新收盘价相对 60 根 4h 均线距离 | decimal | 60 |
| close_vs_sma_pct_4h_120 | 4h 最新收盘价相对 120 根 4h 均线距离 | decimal | 120 |

距离为正只表示价格高于对应均线，不等于看多信号。

距离为负只表示价格低于对应均线，不等于看空信号。

### 7.4 均线斜率

计算口径：

```text
(current_sma - lagged_sma) / lagged_sma
```

| FeatureCode | 含义 | 输出类型 | warmup |
|---|---|---|---:|
| slope_sma_1d_20_lag10 | 1d 20 日均线相对 10 根 1d 前的斜率 | decimal | 30 |
| slope_sma_1d_60_lag10 | 1d 60 日均线相对 10 根 1d 前的斜率 | decimal | 70 |
| slope_sma_1d_120_lag10 | 1d 120 日均线相对 10 根 1d 前的斜率 | decimal | 130 |
| slope_sma_4h_20_lag12 | 4h 20 均线相对 12 根 4h 前的斜率 | decimal | 32 |
| slope_sma_4h_60_lag12 | 4h 60 均线相对 12 根 4h 前的斜率 | decimal | 72 |
| slope_sma_4h_120_lag12 | 4h 120 均线相对 12 根 4h 前的斜率 | decimal | 132 |

斜率只表达趋势参考线的方向变化，不表达趋势是否成立。

### 7.5 均线排列距离

计算口径：

```text
(fast_sma - slow_sma) / slow_sma
```

| FeatureCode | 含义 | 输出类型 | warmup |
|---|---|---|---:|
| sma_spread_pct_1d_20_60 | 1d 20 日均线相对 60 日均线距离 | decimal | 60 |
| sma_spread_pct_1d_60_120 | 1d 60 日均线相对 120 日均线距离 | decimal | 120 |
| sma_spread_pct_4h_20_60 | 4h 20 均线相对 60 均线距离 | decimal | 60 |
| sma_spread_pct_4h_60_120 | 4h 60 均线相对 120 均线距离 | decimal | 120 |

均线排列距离用于后续原子信号判断趋势排列，不在特征层直接判断多头排列或空头排列。

### 7.6 近期滚动高低点

| FeatureCode | 含义 | 输出类型 | warmup |
|---|---|---|---:|
| rolling_high_1d_60 | 最近 60 根 1d K 线最高价 | decimal | 60 |
| rolling_low_1d_60 | 最近 60 根 1d K 线最低价 | decimal | 60 |
| rolling_high_4h_60 | 最近 60 根 4h K 线最高价 | decimal | 60 |
| rolling_low_4h_60 | 最近 60 根 4h K 线最低价 | decimal | 60 |

这些特征用于观察当前价格相对近期趋势区间的位置。

是否排除当前 K 线必须由具体 FeatureDefinition 写清楚。

初始口径：

```text
用于描述当前所处区间时，可以包含当前已收盘 K 线；
用于后续判断突破参考位时，派生的结构特征必须排除当前判断 K 线。
```

如果 AtomicSignal 要判断突破，不得直接使用包含当前 K 线的 rolling high / rolling low 作为突破参考。

### 7.7 当前价格相对近期高低点距离

| FeatureCode | 含义 | 输出类型 | warmup |
|---|---|---|---:|
| distance_from_rolling_high_pct_1d_60 | 1d 最新收盘价相对 60 日高点距离 | decimal | 60 |
| distance_from_rolling_low_pct_1d_60 | 1d 最新收盘价相对 60 日低点距离 | decimal | 60 |
| distance_from_rolling_high_pct_4h_60 | 4h 最新收盘价相对 60 根 4h 高点距离 | decimal | 60 |
| distance_from_rolling_low_pct_4h_60 | 4h 最新收盘价相对 60 根 4h 低点距离 | decimal | 60 |

参考公式：

```text
distance_from_rolling_high_pct = (latest_close - rolling_high) / rolling_high
distance_from_rolling_low_pct = (latest_close - rolling_low) / rolling_low
```

这些特征只表达距离，不表达“追涨”“抄底”“止盈”或“止损”。

### 7.8 分块高低点结构计数

为了避免在 P0 阶段引入主观 swing high / swing low 识别，初始趋势结构采用固定分块方式。

计算方法：

```text
取最近 60 根已收盘 K 线；
按时间顺序分为 3 组，每组 20 根；
分别计算每组的最高价和最低价；
比较相邻组之间最高价和最低价是否抬高或降低；
计数范围为 0 到 2。
```

| FeatureCode | 含义 | 输出类型 | warmup |
|---|---|---|---:|
| higher_high_count_1d_60_block20 | 1d 近 60 根 K 线分块高点抬高次数 | integer | 60 |
| higher_low_count_1d_60_block20 | 1d 近 60 根 K 线分块低点抬高次数 | integer | 60 |
| lower_high_count_1d_60_block20 | 1d 近 60 根 K 线分块高点降低次数 | integer | 60 |
| lower_low_count_1d_60_block20 | 1d 近 60 根 K 线分块低点降低次数 | integer | 60 |
| higher_high_count_4h_60_block20 | 4h 近 60 根 K 线分块高点抬高次数 | integer | 60 |
| higher_low_count_4h_60_block20 | 4h 近 60 根 K 线分块低点抬高次数 | integer | 60 |
| lower_high_count_4h_60_block20 | 4h 近 60 根 K 线分块高点降低次数 | integer | 60 |
| lower_low_count_4h_60_block20 | 4h 近 60 根 K 线分块低点降低次数 | integer | 60 |

这些特征只描述高低点结构是否在固定分块上抬高或降低，不直接判断趋势成立。

## 8. P1 / P2 研究特征

以下特征可以作为后续研究，但不进入当前 P0：

```text
ema_1d_20
ema_1d_60
ema_1d_120
ema_4h_20
ema_4h_60
ema_4h_120
adx_1d_14
adx_4h_14
trend_channel_slope_1d_120
trend_channel_slope_4h_120
distance_to_trendline_pct_1d
distance_to_trendline_pct_4h
pullback_depth_pct_from_recent_high
trend_continuation_range_score
```

这些特征需要独立 requirements 定义后才能进入正式候选目录。

不得只凭指标名称实现。

## 9. FeatureValue 落库要求

每个 trend FeatureValue 必须至少记录：

```text
FeatureDefinition；
FeatureDefinition 版本；
MarketSnapshot；
timeframe；
window；
input_start_time；
input_end_time；
value；
value_type；
params；
calculated_at；
status；
failure_reason；
evidence_summary。
```

FeatureValue 不得保存完整 K 线数组。

FeatureValue 不得保存不可控长文本。

FeatureValue 不得保存交易动作语义。

## 10. 不可计算处理

当 K 线数量不足、输入窗口不连续或上游 MarketSnapshot 不完整时：

```text
不得生成伪造数值；
不得用 0 代替缺失；
不得沿用上一次 FeatureValue；
必须记录不可计算状态和原因；
下游 AtomicSignal 必须能识别该特征不可用。
```

如果某个 trend FeatureValue 不可计算，只影响依赖该特征的 AtomicSignal，不得导致整个 FeatureLayer 任意补数。

## 11. 验收样例

### 11.1 日线趋势向上样例

给定 1d 收盘价长期上升：

```text
sma_1d_20 > sma_1d_60 > sma_1d_120；
slope_sma_1d_60_lag10 > 0；
slope_sma_1d_120_lag10 > 0；
higher_high_count_1d_60_block20 较高；
higher_low_count_1d_60_block20 较高。
```

FeatureLayer 只能输出这些数值事实。

是否构成“日线趋势向上”由 AtomicSignal / DomainSignal 判断。

### 11.2 日线下跌但 4h 反弹样例

给定 1d 慢均线斜率向下，但 4h 短均线斜率向上：

```text
slope_sma_1d_120_lag10 < 0；
slope_sma_4h_20_lag12 > 0；
close_vs_sma_pct_4h_20 > 0。
```

FeatureLayer 只能输出上述事实。

是否属于下跌趋势中的反弹，由 trend 原子信号和 MarketRegime 判断。

### 11.3 上升趋势中的横盘样例

给定 1d 慢趋势仍向上，但 4h 高低点结构不再继续抬高：

```text
slope_sma_1d_120_lag10 > 0；
sma_spread_pct_1d_60_120 > 0；
higher_high_count_4h_60_block20 降低；
higher_low_count_4h_60_block20 降低；
distance_from_rolling_high_pct_4h_60 为负且持续。
```

FeatureLayer 仍只输出事实。

是否属于“上升大趋势中的高位震荡”，由 MarketRegime 综合 market_context / trend / structure 等领域事实判断。

## 12. 明确禁止

禁止在 trend FeatureLayer 中：

```text
输出 trend_is_bullish；
输出 trend_is_bearish；
输出 uptrend_confirmed；
输出 downtrend_confirmed；
输出 long_signal；
输出 short_signal；
输出 reduce_position_signal；
输出 target_position_ratio；
读取账户、持仓、订单或成交；
读取 PriceSnapshot；
请求 Binance；
调用 DeepSeek；
调用策略；
生成 AtomicSignal；
生成 DomainSignal；
生成 MarketRegime；
生成 StrategySignal；
生成 DecisionSnapshot；
生成订单意图。
```
