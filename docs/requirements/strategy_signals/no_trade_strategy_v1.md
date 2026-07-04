# 显式不交易策略 v1

## 1. 定位

显式不交易策略是 StrategySignal 层的正式策略。

它用于表达：

```text
当前市场事实已经被识别；
当前版本包也确实选中了一个具体策略；
但这个策略的方法论决定本周期不交易。
```

它不是：

```text
StrategyRouting 没有选中策略；
MarketRegime 给出的操作建议；
系统异常；
回测缺数据；
目标仓位决策；
订单计划。
```

## 2. 为什么需要它

保守策略或标准趋势策略遇到某些行情时，合理结果就是“不交易”。

例如：

```text
熊市反弹但反弹尚未结束；
牛市回调但回调尚未结束；
无方向震荡；
高风险极端波动；
顶部或底部反转只是候选，还没有确认。
```

这些场景不应该由 MarketRegime 或 StrategyRouting 越权决定“停止交易”。

正确链路是：

```text
MarketRegime 只说明客观市场环境；
StrategyRouting 选择一个具体的不交易策略；
StrategySignal 执行该策略并输出 neutral；
DecisionSnapshot 把 neutral 映射为 NO_TRADE。
```

## 3. 输入

本策略读取标准六个领域事实：

```text
市场大背景；
趋势；
动能；
波动；
结构位置；
风险状态。
```

它读取这些事实是为了留下完整复盘证据，而不是为了生成订单动作。

## 4. 输出

本策略固定输出：

```text
策略方向：中性；
策略强度：0；
策略置信：1；
价格条件：空；
策略解释：当前具体策略明确不交易；
允许进入策略信号质量检查。
```

进入 DecisionSnapshot 后，目标仓位策略应输出：

```text
NO_TRADE
```

## 5. 边界

本策略不得：

```text
修改市场事实；
生成 bullish / bearish 方向；
生成目标仓位；
生成订单；
访问账户、持仓或价格事实；
访问 Binance；
调用大模型；
发送 Hermes。
```

本策略可以：

```text
作为保守模板、标准趋势模板或其他模板中的具体 StrategyDefinition；
用不同 StrategyDefinition 参数表达不同的不交易原因；
参与回测和复盘，让“不交易”也成为可解释的策略结果。
```

## 6. 验收

通过标准：

```text
StrategyRouting 选择该策略时，必须进入 StrategySignal；
StrategySignal 必须落库，方向为中性；
StrategySignalQuality 必须能通过基础合同检查；
DecisionSnapshot 必须输出 NO_TRADE；
不得进入 PriceSnapshot、OrderPlan 或订单链路；
复盘页面能看到是哪一个不交易策略做出的决定。
```

