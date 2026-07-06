# context_structure_regime / v3 实现记录

## 1. 定位

`context_structure_regime / v3` 是 MarketRegime 的第三版市场环境分类算法。

它只消费已落库的六个领域事实：

```text
market_context
trend
momentum
volatility
structure
risk_state
```

它不读取 FeatureValue、AtomicSignalValue、K 线、账户、订单、成交或价格事实，不访问 Binance，不调用大模型，不选择策略，不生成目标仓位，不生成订单动作。

## 2. 与 v1 / v2 的关系

v1 保留为保守型市场环境识别算法。

v2 保留为敏捷型市场环境识别算法，已经改善熊市背景下反弹识别过慢的问题。

v3 不覆盖 v1 / v2，而是作为独立 calculator 版本注册：

```text
algorithm_name = context_structure_regime
algorithm_version = v3
```

后台可以同时登记 v1、v2、v3，策略版本包选择其中一个 MarketRegimeDefinition。

## 3. 实现差异

v3 第一版复用 v2 的基础流程和 13 个 regime_code。

v3 的新增差异集中在多头或高位背景转弱识别：

```text
保留 v2 对熊市反弹、熊市低位震荡和同方向阶段切换的识别；
当大背景仍偏多，但 1d 趋势已经转空或 4h 明显转弱时，降低多头趋势延续候选；
当多头背景下同时出现高波动、结构跌破、动能转空或趋势转空时，提高顶部反转候选；
极端波动下保留不明确环境兜底，避免把剧烈冲突行情强行归为趋势延续。
```

## 4. 不变边界

v3 仍然遵守：

```text
MarketRegime 只输出市场环境；
不选择 StrategyDefinition；
不执行 StrategySignal；
不生成目标仓位；
不生成订单动作；
高风险环境优先级不降低；
risk_unclear 仍可输出不明确环境；
不新增 regime_code。
```

## 5. 第一轮验收关注点

第一轮重点看：

```text
v2 已经改善的熊市反弹识别不能退化；
2025-02-01 到 2025-04-15 这类牛市背景下的深度回调，不能长期停留在多头趋势延续；
2025-07-15 到 2025-10-15 这类高位转弱阶段，顶部反转候选或高位区间识别应更早出现；
正常上涨趋势窗口仍应保持多头环境识别，不应因为短周期波动过度悲观；
MarketRegime 仍只给客观市场环境，不替策略决定交易动作。
```
