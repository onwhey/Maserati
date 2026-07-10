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

暂不实现：

```text
跨周期冲击后观察期；
跨周期冷静期；
高波动无方向的窗口统计；
读取上一轮 RiskState；
读取上一轮 MarketRegime。
```

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

主状态仍保持兼容：

```text
risk_clear
risk_elevated_classifiable
risk_high_signal_unreliable
risk_unclear
```

## 边界

本实现只描述市场冲击、信号可靠性和方向暴露事实，不生成交易方向、目标仓位、订单动作或风控审批结论。
