# RiskState Aggregation 2.0.0 实现说明

## 定位

本实现是 `risk_state` 领域信号的第二版聚合器。

它只消费同一 `AtomicSignalSet` 内已经生成的 `risk_state` 原子信号，不读取 FeatureValue、Kline、数据库历史状态、账户、订单、持仓、Binance 或大模型。

## 第一轮实现范围

本轮只实现 RiskState v2 的基础能力：

```text
假突破 / 假跌破进入聚合得分；
输出 risk_score；
输出 market_event_score；
输出 signal_distortion_score；
输出 directional_exposure_score；
输出 chase_risk_score；
输出 direction_stability_score；
输出 risk_effect_tags；
输出 primary_risk_event；
输出 risk_event_phase；
消费单根 4h 极端振幅事件原子 risk_intrabar_extreme_range。
```

第一轮暂未实现：

```text
跨周期冲击后观察期；
跨周期冷静期；
高波动无方向的窗口统计；
读取上一轮 RiskState；
读取上一轮 MarketRegime。
```

## 第二轮实现范围

第二轮仍属于 `risk_state_aggregation/2.0.0`，不新增 v2.1 或 v3。

新增 Feature：

```text
risk_bars_since_market_shock_4h_6；
risk_direction_flip_count_4h_8；
risk_movement_efficiency_4h_8；
risk_cumulative_return_pct_4h_8；
risk_cumulative_range_pct_4h_8。
```

新增 AtomicSignal：

```text
risk_down_body_shock；
risk_up_body_shock；
risk_post_shock_observation；
risk_high_volatility_no_direction。
```

聚合器新增：

```text
单根振幅冲击、下行实体冲击、上行实体冲击任一成立，即标记当前 market_shock；
当前 market_shock 的 risk_event_phase 固定为 shock_active，不以 high 严重度作为额外门槛；
收盘位置只影响方向暴露和追单风险，不否定实体冲击；
冲击后 1-3 根 4h 输出 post_shock_observation；
冲击后 4-6 根 4h 输出 cooling；
输出 post_shock_observation_bars_remaining；
高波动无方向时输出 high_volatility_no_direction 和 direction_instability；
根据原子携带的方向切换次数和移动效率收紧 direction_stability_score。
```

观察期不读取上一轮 RiskState。`risk_bars_since_market_shock_4h_6` 每轮基于当前 MarketSnapshot 冻结的已收盘 4h 窗口重新计算；振幅达到 7% 或实体涨跌幅绝对值达到 4%，任一成立即视为市场冲击。

高波动无方向要求同时满足：

```text
实现波动分位 >= 0.80；
最近 8 根 4h 实体方向切换 >= 4 次；
最近 8 根 4h 移动效率 <= 0.35。
```

因此，高波动但方向稳定的单边行情不会仅因波动高而被归为无方向混乱。

## 聚合规则

每个 active 原子通过 `risk_severity` 转换为类别分数：

```text
none = 0
elevated = 55
high = 100
```

类别包括：

```text
signal_reliability_risk
long_exposure_risk
short_exposure_risk
long_chase_risk
short_chase_risk
false_breakout_risk
false_breakdown_risk
market_disorder_risk
```

其中以下类别会参与信号失真分数：

```text
signal_reliability_risk
false_breakout_risk
false_breakdown_risk
market_disorder_risk
```

其中以下类别会参与方向暴露分数：

```text
long_exposure_risk
short_exposure_risk
```

其中以下类别会参与追单风险分数：

```text
long_chase_risk
short_chase_risk
```

`risk_intrabar_extreme_range` 不直接表达“做多风险”或“做空风险”，而是表达单根 4h 内部出现极端振幅事件。它会打上：

```text
intrabar_extreme_range
market_shock
two_sided_instability
signal_distortion
```

这些标签用于提醒下游：当前普通趋势、突破、跌破解释可能失真。

`risk_down_body_shock` 与 `risk_up_body_shock` 分别表达开盘到收盘的下行 / 上行实体冲击。它们只用实体涨跌幅判断，不使用实体占比或收盘位置。二者会打上：

```text
body_shock
market_shock
signal_distortion
downside_shock 或 upside_shock
```

实体涨跌达到 4% 时为 elevated，达到 7% 时为 high。无论 elevated 还是 high，只要当前冲击原子成立，事件阶段都为 `shock_active`；状态强度仍由严重程度决定。

主状态仍保持兼容：

```text
risk_clear
risk_elevated_classifiable
risk_high_signal_unreliable
risk_unclear
```

`risk_unclear` 不再按风险类别数量判断。聚合器分别计算上行、下行、双向风险事实的最高强度：

```text
同方向多类风险 → 合并表达，不算冲突；
上下方向均达到 elevated 且分数相同 → risk_unclear；
上下方向均达到 high 且分数相同 → risk_unclear；
一边 high、另一边 elevated → 强侧占主导，不算 risk_unclear；
two_sided 单独成立 → 由信号失真或市场扰动状态表达，不自动算方向冲突。
```

摘要额外输出 `risk_direction_scores`，使 `risk_unclear` 可以从原子方向和严重程度完整复算。同强度上下冲突优先于 `risk_high_signal_unreliable`，但风险分数与信号失真分数仍保留原值。

## 边界

本实现只描述市场冲击、信号可靠性和方向暴露事实，不生成交易方向、目标仓位、订单动作或风控审批结论。

本轮未修改 MarketRegime、StrategyRouting、StrategySignal、DecisionSnapshot 或任何订单链路。
