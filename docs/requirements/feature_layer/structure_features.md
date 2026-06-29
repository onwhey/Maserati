# Structure Features

## 1. 文件定位

本文档定义 `structure` 领域所需的 FeatureDefinition 候选目录。

本文档不是一个整体算法版本。本文档中的每个 FeatureDefinition 独立版本化、独立注册、独立进入 StrategyAnalysisRelease。

也就是说：

```text
structure_major_support_lower_1d_365 可以有自己的 v1 / v2；
structure_minor_resistance_upper_4h_120 可以有自己的 v1 / v2；
structure_minor_range_position_pct_4h_120 可以有自己的 v1 / v2；
本文档本身不表示“structure feature v1 整体版本”。
```

structure 特征只回答“支撑压力区、区间边界和价格位置的基础数值事实是什么”，不回答“任何交易处理方式”。

structure 特征服务于：

```text
AtomicSignal
→ DomainSignal.structure
→ MarketRegime
→ StrategyRouting
→ StrategySignal
```

structure 特征不得直接生成交易信号、目标仓位、订单意图或交易动作。

## 2. 大结构与小结构

structure 第一版不把 1d 和 4h 强行合并成一个最终支撑压力答案。

本文件固定区分：

```text
major_structure = 1d 大结构；
minor_structure = 4h 小结构。
```

业务含义：

```text
1d 大结构回答：当前价格处在哪个大区间，哪些支撑/压力不应轻易忽视；
4h 小结构回答：在大区间内部，近期是否出现更细的支撑/压力和入场位置。
```

例如：

```text
1d 大支撑：60000 ~ 61000；
1d 大压力：69000 ~ 70000；
4h 小支撑：63200 ~ 63600；
4h 小压力：65500 ~ 66000。
```

后续策略可以选择：

```text
趋势策略优先尊重 1d 大结构，4h 小结构只用于位置优化；
区间策略必须知道自己是在 1d 大区间中交易 4h 小区间；
4h 小支撑跌破不等于 1d 大结构破坏；
1d 大支撑跌破才是结构级别变化。
```

FeatureLayer 只计算并保存这两套结构事实，不负责决定采用哪一套打法。

## 3. 与其他领域的边界

structure 负责：

```text
支撑区；
压力区；
当前价格到支撑/压力的距离；
当前价格在区间中的位置；
支撑/压力触碰次数；
区间宽度；
突破压力的幅度；
跌破支撑的幅度。
```

structure 不负责：

```text
判断当前是牛市还是熊市；
判断趋势方向；
判断动量是否增强；
判断波动是否异常；
判断靠近支撑后的交易处理；
判断靠近压力后的仓位处理；
判断跌破支撑后的仓位处理；
判断订单类型；
输出限价单价格。
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

## 4. 周期范围

当前 P0 数据采集范围只包含 Binance USDS-M BTCUSDT 的已收盘 4h / 1d K 线。

因此 structure 特征当前只允许使用：

```text
1d 已收盘 K 线；
4h 已收盘 K 线。
```

周期定位：

```text
1d = major_structure 大结构；
4h = minor_structure 小结构。
```

当前不引入：

```text
未收盘 K 线；
WebSocket 实时价格；
盘口深度；
成交密集区；
清算热力图；
资金费率；
人工画线；
大模型画线。
```

如果未来要引入成交密集区、订单簿、清算热力图或人工标注结构，必须先新增数据采集、质检、存储和回测边界，不得在 structure feature calculator 内临时请求或人工注入。

## 5. 输入数据要求

Structure FeatureCalculator 只能读取 MarketSnapshot 冻结的 K 线窗口。

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

Structure FeatureCalculator 不得请求 Binance。

Structure FeatureCalculator 不得自行扩大或缩小 MarketSnapshot 窗口。

## 6. 特征层与原子层的数据交接

FeatureLayer 是数据工厂，负责计算并落库 FeatureValue。

AtomicSignal 是数据用户，负责读取已经生成的 FeatureValue。

AtomicSignal 不得：

```text
自己计算 swing high / swing low；
自己聚类支撑压力区；
自己计算触碰次数；
自己计算区间位置；
自己判断突破或跌破参考区；
调用 FeatureLayer 算法函数；
绕过 FeatureValue 直接读取 K 线重新计算结构。
```

多个 Structure 原子信号依赖同一个 structure 特征时，必须引用同一个 FeatureSet 内同一份 FeatureValue。

## 7. P0 算法总览

P0 支撑压力算法使用“候选转折点 → 价格区聚类 → 区间打分 → 输出最近可用区”的方式。

流程：

```text
已收盘 K 线窗口
→ 排除当前判断 K 线，形成参考窗口
→ 识别 swing low / swing high
→ 把相近 swing 点聚合成支撑区 / 压力区
→ 计算触碰次数、最近程度和反应幅度
→ 选择当前价格下方最近有效支撑区
→ 选择当前价格上方最近有效压力区
→ 计算当前价格在大小结构中的位置。
```

支撑压力必须表达为区域，不得只表达为单点价格。

```text
support_zone = [support_lower, support_upper]
resistance_zone = [resistance_lower, resistance_upper]
```

## 8. 排除当前 K 线规则

用于判断突破或跌破的参考支撑压力，必须排除当前判断 K 线。

原因：

```text
如果把当前 K 线纳入 rolling high / rolling low 或 swing 区间；
当前 K 线自己会抬高压力或压低支撑；
突破 / 跌破条件可能变成永远不成立或严重失真。
```

本文件约定：

```text
latest_closed_bar = 当前判断 K 线；
reference_window = latest_closed_bar 之前的已收盘 K 线；
支撑压力区、触碰次数和区间边界都从 reference_window 计算；
latest_closed_bar.close 只用于计算当前位置、距离、突破幅度和跌破幅度。
```

这条规则同时适用于 1d 大结构和 4h 小结构。

## 9. P0 参数约定

| 参数 | 1d 大结构 | 4h 小结构 | 说明 |
|---|---:|---:|---|
| 参考窗口 | 365 根 1d | 120 根 4h | 大结构看更长历史，小结构看近期细节 |
| swing 左右邻居 | 3 根 | 2 根 | 识别局部高低点 |
| 最少 swing 点 | 4 | 4 | 少于该数量时结构不可用 |
| 最少触碰次数 | 2 | 2 | 支撑/压力至少被多次测试 |
| 反应确认窗口 | 10 根 1d | 12 根 4h | 触碰后观察是否有反应 |
| 最小反应幅度 | 3% | 1.2% | 用于过滤无意义触碰 |
| 默认区间半宽 | max(1.2%, median_range_pct) | max(0.6%, median_range_pct) | 区域宽度随波动变化 |
| 最大有效区间宽度 | 45% | 20% | 超过则不作为可用区间 |
| 价格来源 | close | close | 当前位置统一使用最新收盘价 |
| 高低点来源 | high / low | high / low | swing 和触碰使用 K 线高低点 |

这些参数是初始 FeatureDefinition 的参数，不是不可变系统红线。

如果某个特征升级算法或参数，应新增该 FeatureDefinition 的独立版本，而不是直接覆盖历史版本。

## 10. swing 点识别

### 10.1 swing low

某根参考 K 线满足以下条件，才是候选支撑点：

```text
low <= 左侧 N 根 K 线 low 的最小值；
low <= 右侧 N 根 K 线 low 的最小值；
与相邻候选点价格过近时，保留更极端且更近的候选点。
```

`N` 由周期参数决定：

```text
1d N = 3；
4h N = 2。
```

### 10.2 swing high

某根参考 K 线满足以下条件，才是候选压力点：

```text
high >= 左侧 N 根 K 线 high 的最大值；
high >= 右侧 N 根 K 线 high 的最大值；
与相邻候选点价格过近时，保留更极端且更近的候选点。
```

### 10.3 当前 K 线不得成为候选点

`latest_closed_bar` 不参与 swing 点识别。

如果参考窗口不足以识别 swing 点：

```text
FeatureValue.status = failed
error_code = structure_insufficient_reference_window
```

## 11. 支撑压力区聚类

### 11.1 区间半宽

区间半宽按周期独立计算：

```text
median_range_pct = median((high - low) / close)
zone_half_width_pct = max(default_min_half_width_pct, median_range_pct)
```

默认最小半宽：

```text
1d = 1.2%
4h = 0.6%
```

### 11.2 聚类规则

把价格接近的 swing 点合并为同一个候选区：

```text
abs(candidate_price - zone_center) / zone_center <= zone_half_width_pct
```

候选区边界：

```text
zone_lower = min(cluster_prices) * (1 - zone_half_width_pct)
zone_upper = max(cluster_prices) * (1 + zone_half_width_pct)
zone_center = median(cluster_prices)
```

### 11.3 触碰次数

支撑区触碰：

```text
K 线 low 进入 support_zone；
且后续 confirmation_window 内最高 close 相对触碰价反弹 >= min_reaction_pct。
```

压力区触碰：

```text
K 线 high 进入 resistance_zone；
且后续 confirmation_window 内最低 close 相对触碰价回落 >= min_reaction_pct。
```

没有反应的穿越不计为有效触碰。

### 11.4 区间打分

候选区 score 至少由以下部分组成：

```text
touch_count_score = min(touch_count, 5) / 5
recency_score = 越接近当前，分数越高
reaction_score = 触碰后平均反应幅度归一化
```

P0 总分：

```text
zone_score = 0.45 * touch_count_score
           + 0.30 * recency_score
           + 0.25 * reaction_score
```

这些固定系数属于当前 FeatureDefinition 算法版本，不是 StrategySignal 权重。

## 12. 最近可用支撑与压力

### 12.1 最近支撑区

最近支撑区定义：

```text
zone_upper <= latest_close；
或 latest_close 落在 zone_lower 与 zone_upper 之间；
在满足触碰次数和 score 的候选支撑区中，选择距离 latest_close 最近的一组。
```

如果没有有效支撑区：

```text
support_lower / support_upper = null；
support_touch_count = 0；
support_score = 0；
```

### 12.2 最近压力区

最近压力区定义：

```text
zone_lower >= latest_close；
或 latest_close 落在 zone_lower 与 zone_upper 之间；
在满足触碰次数和 score 的候选压力区中，选择距离 latest_close 最近的一组。
```

如果没有有效压力区：

```text
resistance_lower / resistance_upper = null；
resistance_touch_count = 0；
resistance_score = 0；
```

### 12.3 区间有效性基础

只有同时存在支撑区和压力区，且：

```text
support_upper < resistance_lower；
range_width_pct <= max_range_width_pct；
support_touch_count >= min_touch_count；
resistance_touch_count >= min_touch_count。
```

对应区间才可以被下游判断为“候选有效区间”。

FeatureLayer 不直接输出“区间有效”，只输出下游判断所需的数值事实。

## 13. P0 FeatureDefinition

### 13.1 当前收盘价

| FeatureCode | 含义 | 输出类型 | warmup |
|---|---|---|---:|
| structure_major_latest_close_1d | 当前 1d 已收盘 close | decimal | 1 |
| structure_minor_latest_close_4h | 当前 4h 已收盘 close | decimal | 1 |

### 13.2 大结构支撑压力区

| FeatureCode | 含义 | 输出类型 | warmup |
|---|---|---|---:|
| structure_major_support_lower_1d_365 | 1d 大结构最近有效支撑区下沿 | decimal/null | 365 |
| structure_major_support_upper_1d_365 | 1d 大结构最近有效支撑区上沿 | decimal/null | 365 |
| structure_major_resistance_lower_1d_365 | 1d 大结构最近有效压力区下沿 | decimal/null | 365 |
| structure_major_resistance_upper_1d_365 | 1d 大结构最近有效压力区上沿 | decimal/null | 365 |
| structure_major_support_touch_count_1d_365 | 1d 大结构支撑区有效触碰次数 | integer | 365 |
| structure_major_resistance_touch_count_1d_365 | 1d 大结构压力区有效触碰次数 | integer | 365 |
| structure_major_support_score_1d_365 | 1d 大结构支撑区质量分 | decimal | 365 |
| structure_major_resistance_score_1d_365 | 1d 大结构压力区质量分 | decimal | 365 |

### 13.3 小结构支撑压力区

| FeatureCode | 含义 | 输出类型 | warmup |
|---|---|---|---:|
| structure_minor_support_lower_4h_120 | 4h 小结构最近有效支撑区下沿 | decimal/null | 120 |
| structure_minor_support_upper_4h_120 | 4h 小结构最近有效支撑区上沿 | decimal/null | 120 |
| structure_minor_resistance_lower_4h_120 | 4h 小结构最近有效压力区下沿 | decimal/null | 120 |
| structure_minor_resistance_upper_4h_120 | 4h 小结构最近有效压力区上沿 | decimal/null | 120 |
| structure_minor_support_touch_count_4h_120 | 4h 小结构支撑区有效触碰次数 | integer | 120 |
| structure_minor_resistance_touch_count_4h_120 | 4h 小结构压力区有效触碰次数 | integer | 120 |
| structure_minor_support_score_4h_120 | 4h 小结构支撑区质量分 | decimal | 120 |
| structure_minor_resistance_score_4h_120 | 4h 小结构压力区质量分 | decimal | 120 |

### 13.4 价格位置与距离

距离支撑：

```text
distance_to_support_upper_pct = (latest_close - support_upper) / latest_close
```

距离压力：

```text
distance_to_resistance_lower_pct = (resistance_lower - latest_close) / latest_close
```

区间位置：

```text
range_position_pct = (latest_close - support_upper) / (resistance_lower - support_upper)
```

| FeatureCode | 含义 | 输出类型 | warmup |
|---|---|---|---:|
| structure_major_distance_to_support_upper_pct_1d_365 | 1d 当前价距离大支撑上沿百分比 | decimal/null | 365 |
| structure_major_distance_to_resistance_lower_pct_1d_365 | 1d 当前价距离大压力下沿百分比 | decimal/null | 365 |
| structure_major_range_position_pct_1d_365 | 1d 当前价在大结构支撑压力区间中的位置 | decimal/null | 365 |
| structure_major_range_width_pct_1d_365 | 1d 大结构支撑压力区间宽度 | decimal/null | 365 |
| structure_minor_distance_to_support_upper_pct_4h_120 | 4h 当前价距离小支撑上沿百分比 | decimal/null | 120 |
| structure_minor_distance_to_resistance_lower_pct_4h_120 | 4h 当前价距离小压力下沿百分比 | decimal/null | 120 |
| structure_minor_range_position_pct_4h_120 | 4h 当前价在小结构支撑压力区间中的位置 | decimal/null | 120 |
| structure_minor_range_width_pct_4h_120 | 4h 小结构支撑压力区间宽度 | decimal/null | 120 |

如果支撑或压力缺失，对应距离和区间位置为 null，不得用 0 替代。

### 13.5 突破与跌破幅度

突破压力：

```text
breakout_above_resistance_pct = (latest_close - resistance_upper) / latest_close
```

只有 `latest_close > resistance_upper` 时该值为正，否则为 0 或负值。

跌破支撑：

```text
breakdown_below_support_pct = (support_lower - latest_close) / latest_close
```

只有 `latest_close < support_lower` 时该值为正，否则为 0 或负值。

| FeatureCode | 含义 | 输出类型 | warmup |
|---|---|---|---:|
| structure_major_breakout_above_resistance_pct_1d_365 | 1d 当前收盘价突破大压力上沿的幅度 | decimal/null | 365 |
| structure_major_breakdown_below_support_pct_1d_365 | 1d 当前收盘价跌破大支撑下沿的幅度 | decimal/null | 365 |
| structure_minor_breakout_above_resistance_pct_4h_120 | 4h 当前收盘价突破小压力上沿的幅度 | decimal/null | 120 |
| structure_minor_breakdown_below_support_pct_4h_120 | 4h 当前收盘价跌破小支撑下沿的幅度 | decimal/null | 120 |

这些特征只表达突破或跌破幅度，不判断突破是否有效，也不生成交易动作。

## 14. null 与失败规则

如果窗口不足：

```text
status = failed
error_code = structure_insufficient_window
```

如果窗口足够但找不到有效支撑或压力：

```text
status = created
value = null
quality_flag = no_valid_zone
```

如果支撑与压力顺序异常：

```text
status = created
value = null
quality_flag = invalid_zone_order
```

AtomicSignal 必须能区分：

```text
特征计算失败；
特征成功但无有效区；
特征成功且有有效区。
```

不得把无有效区解释成看多、看空或风险阻断。

## 15. 证据与可复核性

每个结构特征必须保留简短 evidence 摘要：

```text
reference_timeframe；
lookback_bars；
excluded_latest_bar_close_time；
zone_half_width_pct；
selected_zone_score；
touch_count；
nearest_touch_close_time；
latest_close；
calculation_summary。
```

不得保存完整 K 线窗口、完整 swing 点列表或完整聚类结果到单个 FeatureValue。

如果需要调试完整中间过程，只能写入受控 implementation 日志或测试夹具，不得进入正式业务字段。

## 16. 与 StrategyAnalysisRelease 的关系

正式运行只允许计算：

```text
被当前 StrategyAnalysisRelease 特征切片明确选中；
状态 active；
依赖关系完整；
calculator 已注册；
算法 requirements 与 implementation 记录完整；
验证证据完整。
```

没有被版本包选择的 Structure FeatureDefinition，即使已经 active，也不得进入正式 FeatureSet。

## 17. 测试要求

至少覆盖：

```text
窗口不足时失败；
当前判断 K 线不参与参考区计算；
同一历史点附近多个 swing 被聚合为同一区域；
支撑区和压力区输出为上下沿而不是单点；
没有有效支撑时输出 null 而不是 0；
没有有效压力时输出 null 而不是 0；
4h 小结构不覆盖 1d 大结构；
1d 大结构不吞掉 4h 小结构；
突破压力时参考压力不包含当前 K 线；
跌破支撑时参考支撑不包含当前 K 线；
重复计算同一 FeatureSet 结果幂等。
```

## 18. 明确禁止

禁止：

```text
让 FeatureLayer 判断靠近支撑后的交易处理；
让 FeatureLayer 判断靠近压力后的仓位处理；
让 FeatureLayer 判断跌破支撑后的仓位处理；
用当前 K 线参与突破参考区计算；
只输出单点支撑或单点压力；
把 1d 大结构和 4h 小结构强行合并成一个价格带；
把完整 K 线窗口写入 FeatureValue；
读取 PriceSnapshot、账户、订单或成交；
访问 Binance 或调用大模型；
绕过 StrategyAnalysisRelease 直接计算候选结构特征。
```
