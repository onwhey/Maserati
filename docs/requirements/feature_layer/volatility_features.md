# Volatility Features

## 1. 文档定位

本文档定义 `volatility` 领域所需的 FeatureDefinition 候选目录。

本文档不是一个整体算法版本。本文档中的每个 FeatureDefinition 独立版本化、独立注册、独立进入 StrategyAnalysisRelease。

也就是说：

```text
atr_pct_4h_14 可以有自己的 v1 / v2；
realized_vol_pct_1d_20 可以有自己的 v1 / v2；
volatility_ratio_4h_20_to_60 可以有自己的 v1 / v2；
本文档本身不表示“volatility feature v1 整体版本”。
```

volatility 特征只回答“当前波动大小、波动位置、波动是否压缩或扩张所需的基础数值事实是什么”，不回答“任何交易处理方式”。

volatility 特征服务于：

```text
AtomicSignal
→ DomainSignal.volatility
→ MarketRegime
→ StrategyRouting
→ StrategySignal
```

volatility 特征不得直接生成交易信号、目标仓位、订单意图或交易动作。

## 2. 与其他领域的边界

volatility 负责波动状态相关事实，例如：

```text
当前 ATR 相对价格有多大；
收益率实际波动有多大；
当前波动处于历史窗口什么分位；
最新 K 线振幅、实体和影线情况；
近期行情高低区间宽度；
短窗口波动相对长窗口波动是在压缩还是扩张。
```

volatility 不负责：

```text
判断当前是牛市还是熊市；
判断趋势方向；
判断动能是否增强或衰竭；
判断支撑压力是否有效；
判断异常行情是否应阻断交易；
判断方向性交易处理、反方向交易处理或仓位处理。
```

边界规则：

```text
market_context 负责大级别背景；
trend 负责趋势方向和趋势结构；
momentum 负责价格推动力；
volatility 负责波动大小、压缩、扩张和波动位置；
structure 负责支撑压力、区间结构和价格位置；
risk_state 负责异常行情对信号可靠性的风险含义。
```

同一个基础特征可以被多个领域复用。

例如：

```text
candle_range_pct_4h_latest 可以被 volatility 用于描述单根 K 线振幅；
candle_range_pct_4h_latest 也可以被 risk_state 用于判断异常行情是否降低信号可靠性。
```

复用必须读取同一份 FeatureValue，不得在不同领域各自重复计算同义特征。

## 3. 周期范围

当前 P0 数据采集范围只包含 Binance USDS-M BTCUSDT 的已收盘 4h / 1d K 线。

因此 volatility 特征当前只允许使用：

```text
1d 已收盘 K 线；
4h 已收盘 K 线。
```

周期定位：

```text
1d = 日线级波动事实；
4h = 短周期波动事实。
```

4h 使用 MarketSnapshot 冻结的完整 4h 窗口，不是盘中实时判断。

volatility 不引入 3d、1w、WebSocket 实时价格、盘口深度、价差、隐含波动率、资金费率或盘中未收盘 K 线。

如果未来需要引入非 K 线数据，必须先修改 DataCollection / MarketSnapshot / FeatureLayer 相关需求，明确数据来源、窗口、质检和存储方式，不得在 volatility feature calculator 内临时请求。

## 4. 输入数据要求

volatility FeatureCalculator 只能读取 MarketSnapshot 冻结的 K 线窗口。

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
盘口深度；
价差；
资金费率；
外部新闻；
大模型输出。
```

volatility FeatureCalculator 不得请求 Binance。

volatility FeatureCalculator 不得自行扩大或缩小 MarketSnapshot 窗口。

## 5. 特征层与原子层的数据交接

FeatureLayer 是数据工厂，负责计算并落库 FeatureValue。

AtomicSignal 是数据用户，负责读取已经生成的 FeatureValue。

AtomicSignal 不得：

```text
自己计算 ATR；
自己计算实现波动率；
自己计算波动分位；
自己计算 K 线振幅、实体或影线；
自己计算行情区间宽度；
自己计算短长波动比；
调用 FeatureLayer 算法函数；
绕过 FeatureValue 直接读取 K 线重新计算特征。
```

多个 AtomicSignal 需要同一个 volatility 特征时，必须引用同一个 FeatureValue，而不是各自重复计算。

## 6. P0 设计原则

P0 volatility 特征优先使用当前 K 线数据范围内稳定可复算的波动事实。

P0 不默认引入：

```text
布林带宽度；
Keltner Channel；
GARCH；
隐含波动率；
盘口价差；
深度数据；
资金费率。
```

原因：

```text
当前正式数据源只有 4h / 1d 已收盘 K 线；
第一版波动判断需要能稳定复盘；
非 K 线数据需要额外数据采集、质检和存储边界。
```

这些能力如需引入，应作为 P1 / P2 独立特征补充，不应混入当前 P0。

## 7. P0 参数约定

初始 volatility 特征使用以下参数约定：

| 参数 | 默认值 | 说明 |
|---|---:|---|
| ATR 窗口 | 14 根 K 线 | 经典 ATR 基础窗口 |
| 实现波动率短窗口 | 20 根 K 线 | 观察近期收盘收益率波动 |
| 实现波动率长窗口 | 60 根 4h K 线 | 观察短周期较长参照 |
| 波动分位参照窗口 | 120 根 K 线 | 观察当前波动在近期历史中的位置 |
| 1d 区间宽度窗口 | 60 根 1d K 线 | 观察日线级行情高低区间宽度 |
| 4h 区间宽度窗口 | 120 根 4h K 线 | 观察短周期行情高低区间宽度 |
| 价格来源 | close | ATR 百分比、实现波动率和比例归一化使用收盘价 |
| 高低点来源 | high / low | ATR、单根振幅和区间宽度使用 K 线高低点 |

这些参数是初始 FeatureDefinition 的参数，不是不可变系统红线。

如果某个特征升级算法或参数，应新增该 FeatureDefinition 的独立版本，而不是直接覆盖历史版本。

## 8. P0 FeatureDefinition

### 8.1 ATR 百分比

ATR 百分比回答：

```text
当前 K 线级别的平均真实波动幅度，相对当前价格有多大？
```

真实波动范围：

```text
true_range = max(
  high - low,
  abs(high - previous_close),
  abs(low - previous_close)
)
```

ATR：

```text
atr = 最近 N 根 true_range 的算术平均值
```

ATR 百分比：

```text
atr_pct = atr / latest_close
```

如果 `latest_close <= 0`，该特征不可计算。

| FeatureCode | 含义 | 输出类型 | warmup |
|---|---|---|---:|
| atr_pct_1d_14 | 最近 14 根 1d 的 ATR 相对最新收盘价比例 | decimal | 15 |
| atr_pct_4h_14 | 最近 14 根 4h 的 ATR 相对最新收盘价比例 | decimal | 15 |

ATR 百分比只表达标准化波动幅度，不直接判断波动高低。

### 8.2 已实现波动率

已实现波动率回答：

```text
窗口内收盘收益率本身波动有多大？
```

单根收盘收益率：

```text
return_i = (close_i - close_i-1) / close_i-1
```

已实现波动率：

```text
realized_vol_pct = 窗口内 return_i 的标准差
```

如果任一 `close_i-1 <= 0`，该特征不可计算。

| FeatureCode | 含义 | 输出类型 | warmup |
|---|---|---|---:|
| realized_vol_pct_1d_20 | 最近 20 根 1d 收盘收益率标准差 | decimal | 21 |
| realized_vol_pct_4h_20 | 最近 20 根 4h 收盘收益率标准差 | decimal | 21 |
| realized_vol_pct_4h_60 | 最近 60 根 4h 收盘收益率标准差 | decimal | 61 |

已实现波动率只表达收盘收益率的离散程度，不表达方向。

### 8.3 波动历史分位

波动历史分位回答：

```text
当前波动值在最近历史窗口中处于什么位置？
```

计算口径：

```text
percentile = 参照窗口中小于或等于当前波动值的历史波动值数量 / 参照窗口历史波动值数量
```

参照窗口中的每个历史波动值必须按相同 FeatureDefinition 算法、相同窗口长度、相同参数计算。

不得用当前波动值和不同算法版本的历史波动值混算。

| FeatureCode | 含义 | 输出类型 | warmup |
|---|---|---|---:|
| atr_percentile_1d_120 | 当前 `atr_pct_1d_14` 在最近 120 个同类 1d ATR 百分比中的分位 | decimal | 134 |
| atr_percentile_4h_120 | 当前 `atr_pct_4h_14` 在最近 120 个同类 4h ATR 百分比中的分位 | decimal | 134 |
| realized_vol_percentile_4h_120 | 当前 `realized_vol_pct_4h_20` 在最近 120 个同类 4h 实现波动率中的分位 | decimal | 140 |

分位接近 1 只表示当前波动处于近期高位，不等于风险阻断。

分位接近 0 只表示当前波动处于近期低位，不等于即将突破。

### 8.4 单根 K 线振幅、实体和影线

单根 K 线特征回答：

```text
最新一根已收盘 K 线本身的振幅、实体和影线结构是什么？
```

计算口径：

```text
candle_range_pct = (high - low) / close
candle_body_pct = abs(close - open) / close
candle_body_ratio = abs(close - open) / (high - low)
upper_shadow_ratio = (high - max(open, close)) / (high - low)
lower_shadow_ratio = (min(open, close) - low) / (high - low)
```

如果 `close <= 0`，百分比类特征不可计算。

如果 `high == low`，实体占比和影线比例不可计算。

| FeatureCode | 含义 | 输出类型 | warmup |
|---|---|---|---:|
| candle_range_pct_1d_latest | 最新 1d K 线高低振幅相对收盘价比例 | decimal | 1 |
| candle_range_pct_4h_latest | 最新 4h K 线高低振幅相对收盘价比例 | decimal | 1 |
| candle_body_pct_4h_latest | 最新 4h K 线实体相对收盘价比例 | decimal | 1 |
| candle_body_ratio_4h_latest | 最新 4h K 线实体占高低振幅比例 | decimal | 1 |
| upper_shadow_ratio_4h_latest | 最新 4h K 线上影线占高低振幅比例 | decimal | 1 |
| lower_shadow_ratio_4h_latest | 最新 4h K 线下影线占高低振幅比例 | decimal | 1 |

这些特征只描述最新 K 线形态事实，不直接判断插针、追高风险或异常行情。

risk_state 如需使用这些事实，必须读取同一份 FeatureValue。

### 8.5 行情高低区间宽度

区间宽度回答：

```text
最近一段行情的高低活动范围，相对当前价格有多宽？
```

计算口径：

```text
range_width_pct = (rolling_high - rolling_low) / latest_close
```

其中：

```text
rolling_high = 窗口内 high 的最大值
rolling_low = 窗口内 low 的最小值
```

如果 `latest_close <= 0`，该特征不可计算。

| FeatureCode | 含义 | 输出类型 | warmup |
|---|---|---|---:|
| range_width_pct_1d_60 | 最近 60 根 1d 高低区间宽度相对最新收盘价比例 | decimal | 60 |
| range_width_pct_4h_120 | 最近 120 根 4h 高低区间宽度相对最新收盘价比例 | decimal | 120 |

这里的区间宽度只是行情高低活动范围，不等同于 structure 领域里的支撑压力区间。

如果 structure 后续也需要 `range_width_pct_4h_120`，必须复用本 FeatureDefinition 或明确说明二者不是同义特征，不得重复定义同名不同义特征。

### 8.6 短长波动比

短长波动比回答：

```text
近期波动相对更长窗口是在压缩还是扩张？
```

计算口径：

```text
volatility_ratio_4h_20_to_60 = realized_vol_pct_4h_20 / realized_vol_pct_4h_60
```

如果 `realized_vol_pct_4h_60 <= 0`，该特征不可计算。

| FeatureCode | 含义 | 输出类型 | warmup |
|---|---|---|---:|
| volatility_ratio_4h_20_to_60 | 4h 20 根实现波动率相对 4h 60 根实现波动率的比例 | decimal | 61 |

短长波动比大于 1 只表示短窗口波动高于长窗口，不直接等于波动扩张信号。

短长波动比小于 1 只表示短窗口波动低于长窗口，不直接等于波动压缩信号。

## 9. P1 / P2 可扩展波动特征

以下特征可以作为后续波动证据增强，但不进入当前 P0：

```text
bollinger_band_width_4h_20
bollinger_band_width_1d_20
keltner_channel_width_4h_20
volatility_contraction_score_4h
volatility_expansion_score_4h
extreme_bar_count_4h_20
gap_or_jump_pct_4h_latest
multi_window_volatility_ratio_1d
garch_volatility_estimate
implied_volatility_proxy
spread_or_depth_volatility_proxy
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

盘口价差、深度、隐含波动率、资金费率相关特征需要新增数据采集和质检能力，当前 P0 不支持正式实现。

## 10. FeatureValue 落库要求

每个 volatility FeatureValue 必须至少记录：

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

分位类特征也使用小数表达：

```text
0.90 表示处于 90% 分位；
0.10 表示处于 10% 分位。
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

如果某个 volatility FeatureValue 不可计算，只影响依赖该特征的 AtomicSignal，不得导致整个 FeatureLayer 任意补数。

## 12. 验收样例

### 12.1 日线波动升高样例

给定最近 1d 高低振幅扩大，且 ATR 百分比处于较高历史分位：

```text
atr_pct_1d_14 明显高于近期常态；
atr_percentile_1d_120 接近高分位；
candle_range_pct_1d_latest 较高。
```

FeatureLayer 只能输出这些数值事实。

是否构成“波动偏高”或“异常高波动”，由 AtomicSignal / DomainSignal 判断。

### 12.2 短周期波动压缩样例

给定最近 20 根 4h 收盘收益率波动明显低于最近 60 根 4h：

```text
realized_vol_pct_4h_20 较低；
realized_vol_pct_4h_60 高于短窗口；
volatility_ratio_4h_20_to_60 < 1；
atr_percentile_4h_120 较低。
```

FeatureLayer 不判断“即将突破”。

是否属于“波动压缩”，由 AtomicSignal / DomainSignal 判断。

### 12.3 单根 4h K 线振幅异常样例

给定最新 4h K 线高低振幅明显扩大，且上影线较长：

```text
candle_range_pct_4h_latest 较高；
upper_shadow_ratio_4h_latest 较高；
candle_body_ratio_4h_latest 可能较低。
```

FeatureLayer 只输出振幅、实体和影线事实。

是否构成“异常波动”属于 volatility 原子 / 领域判断；是否构成“插针风险”属于 risk_state 判断。

## 13. 明确禁止

禁止在 volatility FeatureLayer 中：

```text
输出 volatility_is_high；
输出 volatility_is_low；
输出 volatility_compressed；
输出 volatility_expanding；
输出 risk_off_signal；
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
