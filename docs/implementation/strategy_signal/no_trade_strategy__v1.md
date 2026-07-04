# no_trade_strategy / v1 实现说明

## 1. 实现目的

`no_trade_strategy/v1` 用于把“不交易”从 StrategyRouting 的截断结果，移动到 StrategySignal 层的正式策略结果。

这样做的核心原因是：

```text
市场事实层只描述事实；
路由层只选择策略；
不交易也是一种策略；
策略层负责说明为什么本周期不交易。
```

## 2. 算法逻辑

算法不做复杂评分。

执行逻辑为：

```text
读取 StrategyDefinition；
读取六个领域事实；
确认必需领域事实齐全；
读取 StrategyDefinition 参数中的不交易原因；
输出中性策略信号；
把六个领域事实写入证据摘要。
```

输出固定为：

```text
direction = neutral
strength = 0
confidence = 1
trade_price_condition = {}
```

## 3. 为什么 confidence 是 1

这里的置信度不是“行情方向置信度”，而是“本策略决定不交易的确定性”。

真正进入目标仓位映射时，`direction = neutral` 会优先触发 `NO_TRADE`，不会因为置信度为 1 而产生仓位。

## 4. 不负责内容

本算法不负责：

```text
判断市场环境；
选择策略；
生成 bullish / bearish 方向；
生成目标仓位；
生成订单；
读取账户或价格；
访问外部服务。
```

