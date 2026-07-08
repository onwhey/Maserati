# Structure DomainSignal v3：拐点支撑压力聚合

## 目标

Structure DomainSignal v3 只负责把“拐点型支撑压力”原子信号聚合成领域级结构事实。

它回答的问题是：

```text
当前价格在 1d 大结构和 4h 小结构中，靠近支撑、靠近压力、处于夹层、正在跌破/突破候选，还是已经确认跌破/突破？
```

它不回答：

```text
应该做多还是做空
应该选择哪一个策略
应该开仓、平仓、减仓或下单
```

## 输入边界

v3 只消费新版拐点型原子信号：

```text
structure_pivot_major_*
structure_pivot_minor_*
```

v3 不消费旧版大区间支撑压力原子：

```text
structure_major_*
structure_minor_*
structure_historical_major_*
```

旧版原子可以继续保留给历史版本包或对照实验使用，但默认 Structure 领域聚合从 v3 开始不再混用新旧结构事实。

## 聚合口径

每个层级分别形成结构状态：

```text
1d 大结构
4h 小结构
```

每个层级的优先级：

```text
确认跌破支撑
确认突破压力
跌破支撑候选
突破压力候选
支撑和压力同时有效，处于夹层
支撑守住
压力压住
测试支撑
测试压力
靠近支撑
靠近压力
结构不明确
```

当支撑和压力同时存在时，不能把主结论强行压成“支撑守住”或“压力压住”，必须表达为：

```text
处于支撑压力夹层
```

## 输出要求

输出必须包含：

```text
major_structure：1d 大结构状态
minor_structure：4h 小结构状态
structure_evidence：给 MarketRegime 消费的结构化证据
support_zone / resistance_zone：当前可用的支撑压力区间
current_zone_position：当前价格在结构区间中的位置
```

其中 `structure_evidence` 必须至少包含：

```text
support_holds
resistance_holds
support_breakdown_candidate
support_breakdown_confirmed
resistance_breakout_candidate
resistance_breakout_confirmed
between_support_resistance
```

这些字段用于 MarketRegime 判断结构是否保持、受压、跌破候选、突破候选或确认破坏。

## 交易红线

Structure DomainSignal v3：

```text
不生成交易动作
不生成目标仓位
不读取账户或持仓
不访问 Binance
不访问 Redis
不发送 Hermes
不调用大模型
不参与真实交易执行
```
