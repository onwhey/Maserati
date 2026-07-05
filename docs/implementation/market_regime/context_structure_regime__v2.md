# context_structure_regime / v2 实现记录

## 1. 定位

`context_structure_regime / v2` 是 MarketRegime 的第二版市场环境分类算法。

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

## 2. 与 v1 的关系

v1 保留为保守型市场环境识别算法。

v2 不覆盖 v1，而是作为独立 calculator 版本注册：

```text
algorithm_name = context_structure_regime
algorithm_version = v2
```

后台可以同时登记 v1 和 v2，策略版本包选择其中一个 MarketRegimeDefinition。

## 3. 实现差异

v2 复用 v1 的领域归一化、基础评分、风险优先级和 13 个 regime_code。

v2 的主要差异是分类选择阶段：

```text
默认最低候选分数从 0.55 降为 0.50；
默认最小分类差距从 0.10 降为 0.05；
新增 transition_floor_score = 0.50；
当主要候选属于同一多头或空头家族时，允许选择更具体的候选环境，而不是直接退回不明确；
当大背景清晰、风险清晰、短周期出现反向修复时，优先承认多头回调或空头反弹。
```

## 4. 不变边界

v2 仍然遵守：

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
同样回测窗口中，不明确环境是否减少；
熊市反弹是否比 v1 更早识别；
牛市回调是否比 v1 更早识别；
大方向是否没有明显劣化；
是否没有把所有冲突行情粗暴改成反弹或回调。
```
