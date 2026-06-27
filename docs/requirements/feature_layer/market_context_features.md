# Market Context Features

## 1. 文件定位

本文档定义 `market_context` 领域所需的市场大背景特征清单。

这些特征用于回答：

```text
当前 BTC 处在长期价格结构中的什么位置？
当前价格相对长期均线是偏强还是偏弱？
当前是从长期高点回撤，还是从阶段低点反弹？
当前反弹是否已经收复了前一段回撤的大部分空间？
```

本文档只定义特征计算，不定义原子信号、领域信号、市场环境、策略路由或交易动作。

本文档不是一个整体算法版本。本文档中的每个 FeatureDefinition 独立版本化，单个特征算法升级时，只新增或切换该 FeatureDefinition 的版本，不要求整份 market_context 特征清单整体升级。

## 2. 模块边界

MarketContextFeatureCalculator 负责：

```text
读取已落库的 1d 已收盘 K 线；
计算长期均线、均线斜率、长期高低点、区间位置、回撤、反弹和长期收益；
输出可被 AtomicSignal 消费的 FeatureValue；
记录每个特征使用的算法版本、参数和输入窗口。
```

MarketContextFeatureCalculator 不负责：

```text
判断牛市或熊市；
判断趋势是否成立；
判断是否应该做多或做空；
选择策略；
生成 StrategySignal；
生成 DecisionSnapshot；
读取账户、持仓、订单或成交；
请求 Binance；
访问 DeepSeek；
发送通知；
执行真实交易。
```

## 3. 输入数据

### 3.1 数据来源

输入必须来自 MarketSnapshot 对应的已落库行情事实。

本文件只使用：

```text
交易所：Binance
市场类型：USDS-M Futures
交易品种：BTCUSDT
K 线周期：1d
K 线状态：已收盘
时间标准：UTC
```

不得使用未收盘 K 线。

不得从 Binance 临时请求行情。

不得使用服务器本地时间参与判断。

### 3.2 输入窗口

本文件的核心窗口为最近 365 根 1d 已收盘 K 线。

部分均线斜率特征需要额外历史 K 线作为 warm-up：

```text
365 日均线斜率至少需要 385 根 1d 已收盘 K 线；
200 日均线斜率至少需要 220 根 1d 已收盘 K 线；
120 日均线斜率至少需要 140 根 1d 已收盘 K 线。
```

如果输入 K 线不足，相关特征不得输出伪造值，必须标记为不可计算。

### 3.3 排序规则

输入 K 线必须按 UTC open_time 升序排列。

如果存在重复 open_time、缺失日线、时间倒序或未收盘 K 线，当前特征批次必须失败，并交由 DataQuality / DataBackfill 处理。

## 4. 参数约定

本文档列出的初始 FeatureDefinition 使用以下参数约定：

| 参数 | 值 | 说明 |
|---|---:|---|
| 长期背景窗口 | 365 根 1d K 线 | 判断一年级别价格位置 |
| 中长期均线窗口 | 120 / 200 / 365 根 1d K 线 | 判断价格相对长期均线的位置 |
| 均线斜率滞后窗口 | 20 根 1d K 线 | 比较当前均线与 20 天前均线 |
| 价格来源 | close | 均线、收益、回撤和反弹以收盘价为当前价格 |
| 高低点来源 | high / low | 长期高低点使用 K 线 high / low |

这些参数必须写入对应 FeatureDefinition 的 params / params_hash，并属于对应特征算法版本的一部分。

后续如果只调整某一个特征的窗口、公式、输入价格或参数，只能新增该 FeatureDefinition 的算法版本，不得静默修改历史 FeatureValue 的含义，也不得要求无关特征同步升级。

## 5. 特征清单

### 5.1 长期均线

| 特征代码 | 含义 | 计算方式 |
|---|---|---|
| `sma_1d_120` | 最近 120 日收盘均价 | 最近 120 根 1d K 线 close 的算术平均 |
| `sma_1d_200` | 最近 200 日收盘均价 | 最近 200 根 1d K 线 close 的算术平均 |
| `sma_1d_365` | 最近 365 日收盘均价 | 最近 365 根 1d K 线 close 的算术平均 |

长期均线只表达价格基准，不表达交易方向。

### 5.2 当前价格相对长期均线距离

| 特征代码 | 含义 | 计算方式 |
|---|---|---|
| `close_vs_sma_pct_1d_120` | 当前收盘价相对 120 日均线的偏离 | `(latest_close - sma_1d_120) / sma_1d_120` |
| `close_vs_sma_pct_1d_200` | 当前收盘价相对 200 日均线的偏离 | `(latest_close - sma_1d_200) / sma_1d_200` |
| `close_vs_sma_pct_1d_365` | 当前收盘价相对 365 日均线的偏离 | `(latest_close - sma_1d_365) / sma_1d_365` |

如果均线值小于或等于 0，相关特征不可计算。

这些特征只表达“价格离长期均线有多远”，不直接判断牛市、熊市、做多或做空。

### 5.3 长期均线斜率

| 特征代码 | 含义 | 计算方式 |
|---|---|---|
| `slope_sma_1d_120` | 120 日均线最近 20 天变化率 | `(current_sma_120 - lagged_sma_120) / lagged_sma_120` |
| `slope_sma_1d_200` | 200 日均线最近 20 天变化率 | `(current_sma_200 - lagged_sma_200) / lagged_sma_200` |
| `slope_sma_1d_365` | 365 日均线最近 20 天变化率 | `(current_sma_365 - lagged_sma_365) / lagged_sma_365` |

`lagged_sma` 指以当前分析时间向前 20 根 1d K 线为结束点计算出来的对应均线。

如果历史 K 线不足，或 `lagged_sma <= 0`，相关特征不可计算。

长期均线斜率只表达长期价格基准本身是在抬升、走平还是下行，不直接生成市场环境结论。

### 5.4 365 日高低点与当前位置

| 特征代码 | 含义 | 计算方式 |
|---|---|---|
| `rolling_high_1d_365` | 最近 365 日最高价 | 最近 365 根 1d K 线 high 的最大值 |
| `rolling_low_1d_365` | 最近 365 日最低价 | 最近 365 根 1d K 线 low 的最小值 |
| `range_position_pct_1d_365` | 当前收盘价在 365 日区间中的位置 | `(latest_close - rolling_low_1d_365) / (rolling_high_1d_365 - rolling_low_1d_365)` |

`range_position_pct_1d_365` 的业务含义：

```text
接近 0：当前价格接近最近 365 日低位；
接近 0.5：当前价格处在最近 365 日中部；
接近 1：当前价格接近最近 365 日高位。
```

如果 `rolling_high_1d_365 == rolling_low_1d_365`，`range_position_pct_1d_365` 不可计算。

当前位置特征只表达长期区间位置，不判断支撑、压力、入场或离场。

### 5.5 从 365 日高点回撤

| 特征代码 | 含义 | 计算方式 |
|---|---|---|
| `drawdown_from_high_pct_1d_365` | 当前价格相对最近 365 日高点的回撤比例 | `(rolling_high_1d_365 - latest_close) / rolling_high_1d_365` |
| `drawdown_duration_days_1d_365` | 从最近一次 365 日高点到当前已持续多少根日线 | 最近一次达到 `rolling_high_1d_365` 的 K 线之后，到当前 K 线的根数 |

如果最近 365 日最高价出现在当前 K 线，`drawdown_duration_days_1d_365 = 0`。

如果 `rolling_high_1d_365 <= 0`，回撤比例不可计算。

回撤特征只描述从长期高位回落的幅度和持续时间，不判断该回撤是牛市回调还是熊市下跌。

### 5.6 从回撤低点反弹

回撤低点指：

```text
最近一次达到 rolling_high_1d_365 的 K 线之后，到当前 K 线之间出现的最低 low。
```

如果最近 365 日高点出现在当前 K 线，则回撤低点等于当前 K 线 low。

| 特征代码 | 含义 | 计算方式 |
|---|---|---|
| `drawdown_low_since_high_1d_365` | 从最近 365 日高点之后形成的回撤低点 | 高点之后到当前之间 low 的最小值 |
| `rebound_from_drawdown_low_pct_1d_365` | 当前价格相对回撤低点的反弹比例 | `(latest_close - drawdown_low_since_high_1d_365) / drawdown_low_since_high_1d_365` |
| `rebound_duration_days_1d_365` | 从最近一次回撤低点到当前已持续多少根日线 | 最近一次达到回撤低点的 K 线之后，到当前 K 线的根数 |
| `recovery_ratio_from_drawdown_1d_365` | 当前反弹已收复前一段回撤的比例 | `(latest_close - drawdown_low_since_high_1d_365) / (rolling_high_1d_365 - drawdown_low_since_high_1d_365)` |

如果 `drawdown_low_since_high_1d_365 <= 0`，反弹比例不可计算。

如果 `rolling_high_1d_365 == drawdown_low_since_high_1d_365`：

```text
若 latest_close >= rolling_high_1d_365，则 recovery_ratio_from_drawdown_1d_365 = 1；
否则 recovery_ratio_from_drawdown_1d_365 不可计算。
```

反弹特征只描述从回撤低点反弹的幅度、持续时间和收复程度，不判断该反弹是趋势恢复、熊市反弹还是震荡反抽。

### 5.7 365 日收益

| 特征代码 | 含义 | 计算方式 |
|---|---|---|
| `return_pct_1d_365` | 当前收盘价相对 365 日窗口起点的收益率 | `(latest_close - first_close_1d_365) / first_close_1d_365` |

`first_close_1d_365` 指最近 365 根 1d K 线中最早一根 K 线的 close。

如果 `first_close_1d_365 <= 0`，该特征不可计算。

365 日收益只表达长期价格变动幅度，不直接判断市场状态。

## 6. 输出要求

每个成功计算的特征必须保存为 FeatureValue，并至少能追溯：

```text
所属 FeatureSet；
特征代码；
算法版本；
输入 MarketSnapshot；
输入 K 线周期；
输入窗口起止时间；
参数；
数值；
数值单位；
是否可计算；
不可计算原因；
计算时间。
```

数值使用 Decimal，不使用 float 作为最终落库值。

比例类特征统一使用小数表达：

```text
0.10 表示 10%；
-0.05 表示 -5%；
1.00 表示 100%。
```

## 7. 不可计算处理

以下情况必须标记当前特征不可计算：

```text
输入 K 线不足；
输入 K 线未通过 DataQuality；
输入窗口存在缺口；
输入窗口存在重复；
输入窗口包含未收盘 K 线；
分母小于或等于 0；
高低点区间无法形成；
当前 MarketSnapshot 与输入窗口不一致。
```

不可计算不得用 0、空字符串或默认值替代。

如果某个必需特征不可计算，FeatureLayer 必须按 FeatureLayer 主文档的失败规则处理当前 FeatureSet。

## 8. 与 AtomicSignal 的关系

FeatureLayer 是数据工厂，本文件定义的每个特征都必须先形成已落库 FeatureValue。

AtomicSignal 是数据用户，只能读取这些已落库 FeatureValue，用于生成市场大背景相关原子信号，例如：

```text
价格长期处于 200 日均线上方；
价格长期处于 365 日高位区域；
价格从 365 日高点回撤较深；
价格从回撤低点反弹较强；
长期均线仍在上行；
长期均线已经下行；
当前更接近长期区间低位；
当前更接近长期区间高位。
```

多个 AtomicSignal 依赖同一个 market_context 特征时，必须复用同一个 FeatureSet 内的同一份 FeatureValue。

AtomicSignal 不得调用 MarketContextFeatureCalculator，不得复制本文件中的特征算法，也不得读取 Kline 或 MarketSnapshot 原始行情重新计算特征。

但这些判断必须在 AtomicSignal 层完成。

FeatureLayer 不得直接写出：

```text
牛市；
熊市；
牛市回调；
熊市反弹；
适合做多；
适合做空；
应该等待；
应该减仓；
应该清仓。
```

## 9. 与后续市场环境识别的关系

MarketRegime 可以通过 DomainSignal 间接消费这些特征形成的原子和领域结论，用于识别：

```text
大级别上涨延续；
大级别上涨中的中期回调；
大级别上涨后的高位宽幅震荡；
大级别下跌延续；
大级别下跌中的中期反弹；
大级别下跌后的低位宽幅震荡。
```

MarketContextFeatureCalculator 不得直接识别上述环境。

## 10. 验收规则

### 10.1 上升行情样例

如果最近 365 日整体上涨，且当前价格接近窗口高位：

```text
range_position_pct_1d_365 应接近 1；
drawdown_from_high_pct_1d_365 应较低；
return_pct_1d_365 应为正；
长期均线斜率通常应为正。
```

### 10.2 下跌后反弹样例

如果先形成 365 日高点，之后大幅回撤，再持续反弹：

```text
drawdown_from_high_pct_1d_365 应仍能表达相对高点的回撤；
rebound_from_drawdown_low_pct_1d_365 应表达从低点反弹幅度；
recovery_ratio_from_drawdown_1d_365 应表达反弹收复程度；
drawdown_duration_days_1d_365 与 rebound_duration_days_1d_365 不应混淆。
```

### 10.3 长期震荡样例

如果最近 365 日高低点区间长期存在，当前价格在区间中部：

```text
range_position_pct_1d_365 应接近 0.5；
return_pct_1d_365 可能接近 0；
均线斜率可能接近 0。
```

### 10.4 数据异常样例

如果输入 1d K 线缺失、重复或包含未收盘 K 线：

```text
不得继续计算；
不得输出伪造 FeatureValue；
必须返回明确失败原因。
```

## 11. 当前清单明确不处理

当前 market_context 特征清单不处理：

```text
周线特征；
链上数据；
宏观数据；
资金费率；
成交量分布；
盘口深度；
多币种背景；
多交易所背景；
机器学习市场分类；
自动参数优化。
```

这些能力如需引入，必须新增独立需求文件或新增算法版本。
