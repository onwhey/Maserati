# Momentum Features

## 1. 文档定位

本文档定义 `momentum` 领域所需的 FeatureDefinition 候选目录。

本文档不是一个整体算法版本。本文档中的每个 FeatureDefinition 独立版本化、独立注册、独立进入 StrategyAnalysisRelease。

也就是说：

```text
return_pct_1d_7 可以有自己的 v1 / v2；
movement_efficiency_4h_24 可以有自己的 v1 / v2；
close_location_avg_pct_4h_12 可以有自己的 v1 / v2；
本文档本身不表示“momentum feature v1 整体版本”。
```

momentum 特征只回答“当前价格运动有没有推动力、推动力是否变强或变弱所需的基础数值事实是什么”，不回答“任何交易处理方式”。

momentum 特征服务于：

```text
AtomicSignal
→ DomainSignal.momentum
→ MarketRegime
→ StrategyRouting
→ StrategySignal
```

momentum 特征不得直接生成交易信号、目标仓位、订单意图或交易动作。

## 2. 与其他领域的边界

momentum 负责价格推动力相关事实，例如：

```text
近期价格推进幅度；
当前窗口相对前一窗口的推进变化；
上涨或下跌连续性；
价格推进效率；
K 线收盘强弱。
```

momentum 不负责：

```text
判断当前是牛市还是熊市；
判断主趋势方向；
判断支撑压力；
判断波动是否异常；
判断市场风险是否过高；
判断方向性交易处理、反方向交易处理或仓位处理。
```

边界规则：

```text
market_context 负责大级别背景；
trend 负责趋势方向和趋势结构；
momentum 负责趋势或价格运动是否还有推动力；
volatility 负责波动大小和波动状态；
structure 负责支撑压力、区间结构和价格位置；
risk_state 负责异常市场状态是否降低信号可靠性。
```

如果一个特征同时看起来能服务多个领域，必须优先判断它表达的是“数值事实”还是“领域结论”：

```text
近期 7 日收益率 = momentum 特征；
近期 7 日收益率明显转弱 = AtomicSignal；
多头动能衰竭 = DomainSignal.momentum；
当前不适合追多 = StrategySignal 或 StrategySignalQuality。
```

## 3. 周期范围

当前 P0 数据采集范围只包含 Binance USDS-M BTCUSDT 的已收盘 4h / 1d K 线。

因此 momentum 特征当前只允许使用：

```text
1d 已收盘 K 线；
4h 已收盘 K 线。
```

周期定位：

```text
1d = 日线级动能事实；
4h = 短周期动能事实。
```

4h 使用 MarketSnapshot 冻结的完整 4h 窗口，不是只看日线收盘之后的几根 4h，也不是盘中实时判断。

momentum 不引入 3d、1w、WebSocket 实时价格或盘中未收盘 K 线。

如果未来需要引入更长周期或更短周期，必须先修改 DataCollection / MarketSnapshot / FeatureLayer 相关需求，明确数据来源、窗口、质检和存储方式，不得在 momentum feature calculator 内临时拼接。

## 4. 输入数据要求

momentum FeatureCalculator 只能读取 MarketSnapshot 冻结的 K 线窗口。

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

momentum FeatureCalculator 不得请求 Binance。

momentum FeatureCalculator 不得自行扩大或缩小 MarketSnapshot 窗口。

## 5. 特征层与原子层的数据交接

FeatureLayer 是数据工厂，负责计算并落库 FeatureValue。

AtomicSignal 是数据用户，负责读取已经生成的 FeatureValue。

AtomicSignal 不得：

```text
自己计算收益率；
自己计算连续上涨或连续下跌；
自己计算推进效率；
自己计算收盘位置；
调用 FeatureLayer 算法函数；
绕过 FeatureValue 直接读取 K 线重新计算特征。
```

多个 AtomicSignal 需要同一个 momentum 特征时，必须引用同一个 FeatureValue，而不是各自重复计算。

例如：

```text
“多头动能增强”
“多头动能衰竭”
“震荡中推动力不足”
```

如果都需要 `return_pct_1d_7`，必须读取同一个 FeatureSet 中的同一个 `return_pct_1d_7` FeatureValue。

## 6. P0 设计原则

P0 momentum 特征优先使用可解释的价格行为事实。

P0 不默认引入 MACD、RSI、ADX 等经典指标。

原因：

```text
第一版需要先保证每个动能判断可以被人工复盘；
价格行为特征能直接解释“为什么说动能增强或衰竭”；
经典指标可以作为后续证据增强，但不应在第一版让权重和冲突处理变复杂。
```

这不表示 MACD / RSI 永远不用。

MACD / RSI 属于 P1 可扩展动能证据，后续可以新增独立 FeatureDefinition、AtomicSignal 和 StrategyAnalysisRelease 选择，不需要推翻 P0 特征。

## 7. P0 参数约定

初始 momentum 特征使用以下参数约定：

| 参数 | 默认值 | 说明 |
|---|---:|---|
| 1d 短窗口 | 3 根 1d K 线 | 观察最近数日推动 |
| 1d 中窗口 | 7 根 1d K 线 | 观察一周级推动 |
| 4h 短窗口 | 12 根 4h K 线 | 约等于 2 天 |
| 4h 中窗口 | 24 根 4h K 线 | 约等于 4 天 |
| 价格来源 | close | 收益率、窗口变化和推进效率统一使用收盘价 |
| 收盘位置来源 | high / low / close | 用 K 线高低点与收盘价计算收盘强弱 |

这些参数是初始 FeatureDefinition 的参数，不是不可变系统红线。

如果某个特征升级算法或参数，应新增该 FeatureDefinition 的独立版本，而不是直接覆盖历史版本。

## 8. P0 FeatureDefinition

### 8.1 窗口收益率

窗口收益率回答：

```text
最近一段时间，价格净推进了多少？
```

计算口径：

```text
(latest_close - first_close) / first_close
```

| FeatureCode | 含义 | 输出类型 | warmup |
|---|---|---|---:|
| return_pct_1d_3 | 最近 3 根 1d 收盘价净变化比例 | decimal | 3 |
| return_pct_1d_7 | 最近 7 根 1d 收盘价净变化比例 | decimal | 7 |
| return_pct_4h_12 | 最近 12 根 4h 收盘价净变化比例 | decimal | 12 |
| return_pct_4h_24 | 最近 24 根 4h 收盘价净变化比例 | decimal | 24 |

收益率为正只表示价格上涨，不等于看多信号。

收益率为负只表示价格下跌，不等于看空信号。

### 8.2 前后窗口收益率

前后窗口收益率回答：

```text
当前这段推动，相比上一段是变强还是变弱？
```

当前窗口：

```text
以 MarketSnapshot 中最新已收盘 K 线为结束点。
```

前一窗口：

```text
紧挨当前窗口之前、长度相同、不与当前窗口重叠的一段 K 线。
```

| FeatureCode | 含义 | 输出类型 | warmup |
|---|---|---|---:|
| previous_return_pct_1d_3 | 当前 3 日窗口之前 3 根 1d 的收益率 | decimal | 6 |
| previous_return_pct_1d_7 | 当前 7 日窗口之前 7 根 1d 的收益率 | decimal | 14 |
| previous_return_pct_4h_12 | 当前 12 根 4h 窗口之前 12 根 4h 的收益率 | decimal | 24 |
| previous_return_pct_4h_24 | 当前 24 根 4h 窗口之前 24 根 4h 的收益率 | decimal | 48 |

前一窗口特征只提供历史对照事实，不直接判断动能增强或衰竭。

### 8.3 收益率变化

收益率变化回答：

```text
当前窗口比前一窗口多推进了多少，或者少推进了多少？
```

计算口径：

```text
current_window_return_pct - previous_window_return_pct
```

| FeatureCode | 含义 | 输出类型 | warmup |
|---|---|---|---:|
| return_delta_pct_1d_3 | 最近 3 日收益率相对前 3 日收益率的变化 | decimal | 6 |
| return_delta_pct_1d_7 | 最近 7 日收益率相对前 7 日收益率的变化 | decimal | 14 |
| return_delta_pct_4h_12 | 最近 12 根 4h 收益率相对前 12 根 4h 收益率的变化 | decimal | 24 |
| return_delta_pct_4h_24 | 最近 24 根 4h 收益率相对前 24 根 4h 收益率的变化 | decimal | 48 |

收益率变化为正只表示当前窗口相对前一窗口更强，不直接等于多头动能增强。

收益率变化为负只表示当前窗口相对前一窗口更弱，不直接等于动能衰竭。

### 8.4 上涨 / 下跌 K 线占比

上涨 / 下跌 K 线占比回答：

```text
窗口内价格推进是否具有连续性，还是涨跌交替严重？
```

单根 K 线上涨定义：

```text
close > open
```

单根 K 线下跌定义：

```text
close < open
```

如果 `close == open`，该 K 线既不计入上涨，也不计入下跌。

| FeatureCode | 含义 | 输出类型 | warmup |
|---|---|---|---:|
| up_bar_ratio_1d_7 | 最近 7 根 1d 中上涨 K 线占比 | decimal | 7 |
| down_bar_ratio_1d_7 | 最近 7 根 1d 中下跌 K 线占比 | decimal | 7 |
| up_bar_ratio_4h_24 | 最近 24 根 4h 中上涨 K 线占比 | decimal | 24 |
| down_bar_ratio_4h_24 | 最近 24 根 4h 中下跌 K 线占比 | decimal | 24 |

占比只表达窗口内 K 线方向分布，不直接判断趋势成立。

### 8.5 连续上涨 / 连续下跌数量

连续上涨 / 连续下跌数量回答：

```text
最新一段价格是否正在连续推进，还是已经被打断？
```

计算口径：

```text
从最新已收盘 K 线向前统计；
遇到不满足方向条件的 K 线即停止。
```

| FeatureCode | 含义 | 输出类型 | warmup |
|---|---|---|---:|
| consecutive_up_count_1d_7 | 最近 7 根 1d 内，从最新 K 线向前连续上涨的数量 | integer | 7 |
| consecutive_down_count_1d_7 | 最近 7 根 1d 内，从最新 K 线向前连续下跌的数量 | integer | 7 |
| consecutive_up_count_4h_24 | 最近 24 根 4h 内，从最新 K 线向前连续上涨的数量 | integer | 24 |
| consecutive_down_count_4h_24 | 最近 24 根 4h 内，从最新 K 线向前连续下跌的数量 | integer | 24 |

连续上涨数量较高不等于方向性交易处理。

连续下跌数量较高不等于反方向交易处理。

### 8.6 推进效率

推进效率回答：

```text
价格是顺畅地朝一个方向推进，还是中间来回拉扯很严重？
```

计算口径：

```text
net_move = abs(latest_close - first_close)
path_move = sum(abs(close_i - close_i-1))
movement_efficiency = net_move / path_move
```

如果 `path_move <= 0`，该特征不可计算。

| FeatureCode | 含义 | 输出类型 | warmup |
|---|---|---|---:|
| movement_efficiency_1d_7 | 最近 7 根 1d 的价格推进效率 | decimal | 7 |
| movement_efficiency_4h_24 | 最近 24 根 4h 的价格推进效率 | decimal | 24 |

业务含义：

```text
接近 1：价格推进较顺畅；
接近 0：窗口内拉扯严重，净推进不明显。
```

推进效率不表达方向，方向必须结合窗口收益率由 AtomicSignal 判断。

### 8.7 收盘位置

收盘位置回答：

```text
K 线收盘更靠近高点，还是更靠近低点？
```

单根 K 线收盘位置：

```text
(close - low) / (high - low)
```

如果 `high == low`，该 K 线收盘位置不可计算。

| FeatureCode | 含义 | 输出类型 | warmup |
|---|---|---|---:|
| close_location_pct_1d_latest | 最新 1d K 线收盘位置 | decimal | 1 |
| close_location_pct_4h_latest | 最新 4h K 线收盘位置 | decimal | 1 |
| close_location_avg_pct_1d_3 | 最近 3 根 1d K 线收盘位置平均值 | decimal | 3 |
| close_location_avg_pct_4h_12 | 最近 12 根 4h K 线收盘位置平均值 | decimal | 12 |

业务含义：

```text
接近 1：收盘更靠近窗口高点；
接近 0：收盘更靠近窗口低点；
接近 0.5：收盘位置居中。
```

收盘位置只表达 K 线最后力量归属，不直接表达突破、支撑压力或交易动作。

## 9. P1 / P2 可扩展经典指标

以下特征可以作为后续动能证据增强，但不进入当前 P0：

```text
macd_line_4h_12_26_9
macd_signal_4h_12_26_9
macd_histogram_4h_12_26_9
macd_histogram_slope_4h_12_26_9
macd_line_1d_12_26_9
macd_histogram_1d_12_26_9
rsi_4h_14
rsi_1d_14
rsi_delta_4h_14
rsi_delta_1d_14
adx_4h_14
adx_1d_14
momentum_divergence_score
volume_confirmed_momentum
```

引入这些特征时必须满足：

```text
每个指标有独立 FeatureDefinition；
每个指标有明确算法公式、参数、输入窗口、warmup 和不可计算规则；
每个指标有独立版本；
AtomicSignal 只能读取对应 FeatureValue，不得自己计算指标；
是否启用由 StrategyAnalysisRelease 选择；
不得只凭指标名称实现。
```

MACD / RSI 等经典指标是补充证据，不替代 P0 价格行为特征。

## 10. FeatureValue 落库要求

每个 momentum FeatureValue 必须至少记录：

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

比例类特征统一使用小数表达：

```text
0.10 表示 10%；
-0.05 表示 -5%；
1.00 表示 100%。
```

## 11. 不可计算处理

当 K 线数量不足、输入窗口不连续或上游 MarketSnapshot 不完整时：

```text
不得生成伪造数值；
不得用 0 替代缺失；
不得沿用上一次 FeatureValue；
必须记录不可计算状态和原因；
下游 AtomicSignal 必须能识别该特征不可用。
```

如果某个 momentum FeatureValue 不可计算，只影响依赖该特征的 AtomicSignal，不得导致整个 FeatureLayer 任意补数。

## 12. 验收样例

### 12.1 多头推进增强样例

给定最近 7 根 1d 收盘价明显上涨，且最近 7 日收益率高于前 7 日：

```text
return_pct_1d_7 > 0；
return_delta_pct_1d_7 > 0；
up_bar_ratio_1d_7 较高；
movement_efficiency_1d_7 较高。
```

FeatureLayer 只能输出这些数值事实。

是否构成“多头动能增强”，由 AtomicSignal / DomainSignal 判断。

### 12.2 上涨趋势中动能衰竭样例

给定价格仍在上涨，但推进速度下降、连续性变差：

```text
return_pct_1d_7 > 0；
return_delta_pct_1d_7 < 0；
up_bar_ratio_1d_7 降低；
movement_efficiency_1d_7 降低；
close_location_avg_pct_1d_3 接近 0.5 或更低。
```

FeatureLayer 仍只输出事实。

是否属于“多头动能衰竭”，由 AtomicSignal / DomainSignal 判断。

### 12.3 下跌中短周期反弹样例

给定 1d 窗口仍偏弱，但 4h 窗口短期转强：

```text
return_pct_1d_7 < 0；
return_pct_4h_12 > 0；
return_delta_pct_4h_12 > 0；
close_location_avg_pct_4h_12 较高。
```

FeatureLayer 不判断这是反转、反弹还是诱多。

该判断应由 trend / momentum / market_context / structure 等领域事实共同进入 MarketRegime 后完成。

## 13. 明确禁止

禁止在 momentum FeatureLayer 中：

```text
输出 momentum_is_bullish；
输出 momentum_is_bearish；
输出 momentum_exhausted；
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
