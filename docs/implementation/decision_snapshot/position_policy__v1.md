# position_policy / v1 实现记录

## 1. 实现范围

`position_policy/v1` 是 DecisionSnapshot 阶段使用的目标仓位映射 calculator。

它只消费已经由 DecisionSnapshotService 校验并冻结的 StrategySignal 标准字段：

```text
strategy_direction
strategy_strength
strategy_confidence
confidence_semantics
prediction_horizon
quality_status
quality_issue_summary
analysis_close_time_utc
target_schema_version
frozen_params
```

它不读取 MarketRegime、DomainSignal、账户、持仓、价格、订单、成交或 Binance。

## 2. 默认冻结参数

默认 `DecisionPolicyDefinition.params`：

```json
{
  "min_strength_for_target": "0.55",
  "min_confidence_for_target": "0.55",
  "max_abs_target_position_ratio": "0.50",
  "neutral_intent": "NO_TRADE",
  "weak_signal_intent": "NO_TRADE",
  "confidence_multiplier_method": "linear_confidence",
  "strength_mapping_method": "linear_from_threshold_to_max",
  "rounding_decimal_places": 4,
  "expires_after_seconds": 14400
}
```

`expires_after_seconds = 14400` 表示目标仓位快照默认在一个 4 小时主周期内有效，避免上一轮目标快照被下一轮误消费。

## 3. 映射逻辑

- `neutral`：输出 `NO_TRADE`；
- 强度低于门槛：输出 `NO_TRADE`；
- 置信度低于门槛：输出 `NO_TRADE`；
- `bullish` 且通过门槛：输出正目标仓位；
- `bearish` 且通过门槛：输出负目标仓位；
- 仓位绝对值不超过 `max_abs_target_position_ratio`；
- 小额订单过滤不在本算法处理，由 OrderPlan 根据账户、价格和交易所规则处理。

仓位使用连续映射：

```text
strength_score = clamp((strategy_strength - min_strength_for_target) / (1 - min_strength_for_target), 0, 1)
base_abs_position_ratio = strength_score * max_abs_target_position_ratio
raw_target_position_ratio = direction_sign * base_abs_position_ratio * strategy_confidence
target_position_ratio = round(raw_target_position_ratio, rounding_decimal_places)
```

如果四舍五入后仓位为 0，则输出 `NO_TRADE`。

## 4. 明确不做

本实现不做：

```text
重新分析市场；
读取领域信号；
读取账户、持仓或价格；
解释 trade_price_condition；
根据 strategy_code 分支计算；
根据 MarketRegime 分支计算；
生成订单；
生成止盈止损；
执行风控；
调用 Binance；
访问 Redis；
发送 Hermes；
调用大模型；
参与真实交易执行。
```

`StrategySignal.trade_price_condition` 由 DecisionSnapshotService 原样冻结到 DecisionSnapshot，不进入本 calculator。
