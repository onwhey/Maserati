# position_policy_v1 目标仓位映射算法需求

## 1. 模块定位

`position_policy_v1` 是 DecisionSnapshot 阶段的目标仓位映射算法。

它负责把一份已经通过 StrategySignalQuality 放行的标准化 StrategySignal，转换为不可变的目标仓位意图。

它回答的问题是：

```text
在不重新分析市场、不读取账户、不读取价格的前提下；
如何把 direction / strength / confidence 映射为 target_intent 和 target_position_ratio。
```

它不负责：

```text
重新执行 StrategySignal；
重新判断 MarketRegime；
重新读取 DomainSignal；
读取账户余额；
读取当前持仓；
读取当前价格；
判断支撑压力；
判断市价单或限价单；
判断订单价格；
判断订单数量；
判断最小订单金额；
提交订单；
撤单；
风控审批；
真实交易。
```

`position_policy_v1` 不是策略算法，不是风控规则，也不是订单规划规则。

## 2. 输入合同

本算法只允许消费 DecisionSnapshotService 已经校验并冻结的以下输入：

```text
strategy_signal_quality_result_id
strategy_signal_id
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

本算法不得把以下信息作为计算输入：

```text
strategy_code
strategy_version
StrategyRouteDecision
MarketRegimeSnapshot
DomainSignalValue
AtomicSignalValue
FeatureValue
Kline
PriceSnapshot
BinanceSyncRun
BinancePositionSnapshot
账户余额
当前持仓
当前价格
订单
成交
风控结果
Execution 结果
```

说明：

```text
strategy_code 和 strategy_version 可以作为 DecisionSnapshot 的审计字段保存；
但 position_policy_v1 不得根据它们分支计算目标仓位。
```

## 3. 输出合同

本算法输出：

```text
target_intent
target_position_ratio
target_confidence
target_reason_code
target_reason_summary_zh
decision_calculation_snapshot
evidence_items
error_code
error_message
```

允许的 `target_intent`：

```text
TARGET_POSITION
NO_TRADE
NO_TARGET_CHANGE
```

P0 默认规则：

```text
position_policy_v1 不主动输出 NO_TARGET_CHANGE；
neutral、弱信号、低置信度和无法形成有效目标仓位时，输出 NO_TRADE。
```

`NO_TARGET_CHANGE` 预留给后续具备“上一目标仓位”和“维持原目标”语义的 policy 版本使用。

## 4. 参数

`position_policy_v1` 的参数必须来自冻结的 `DecisionPolicyDefinition.params`。

P0 推荐默认值：

```json
{
  "min_strength_for_target": "0.55",
  "min_confidence_for_target": "0.55",
  "max_abs_target_position_ratio": "0.50",
  "neutral_intent": "NO_TRADE",
  "weak_signal_intent": "NO_TRADE",
  "confidence_multiplier_method": "linear_confidence",
  "strength_mapping_method": "linear_from_threshold_to_max",
  "rounding_decimal_places": 4
}
```

参数约束：

```text
0 <= min_strength_for_target <= 1；
0 <= min_confidence_for_target <= 1；
0 < max_abs_target_position_ratio <= 1；
rounding_decimal_places >= 0；
neutral_intent 必须为 NO_TRADE；
weak_signal_intent 必须为 NO_TRADE。
```

P0 不允许通过参数配置出以下行为：

```text
按 strategy_code 设置不同仓位；
按 MarketRegime 设置不同仓位；
按账户权益设置不同仓位；
按价格位置设置不同仓位；
按历史收益动态调整仓位；
弱信号自动维持旧目标仓位。
```

## 5. 核心映射规则

### 5.1 质量结果必须已放行

本算法只在 DecisionSnapshotService 已确认以下条件后执行：

```text
StrategySignalQualityResult.status = created；
StrategySignalQualityResult.is_usable = true；
StrategySignalQualityResult.allows_decision_snapshot = true；
quality_status = passed 或被规则允许的 warning。
```

如果质量结果未放行，DecisionSnapshotService 应阻断，不应调用本算法。

### 5.2 neutral 一律 NO_TRADE

规则：

```text
strategy_direction = neutral
→ target_intent = NO_TRADE
→ target_position_ratio = null
```

业务含义：

```text
策略计算成功，但没有形成有效方向；
本轮不形成新的目标仓位；
不进入 PriceSnapshot / OrderPlan。
```

### 5.3 弱信号一律 NO_TRADE

规则：

```text
strategy_strength < min_strength_for_target
或 strategy_confidence < min_confidence_for_target
→ target_intent = NO_TRADE
→ target_position_ratio = null
```

P0 使用保守门槛。

这不是永久正确的交易结论，只是 `position_policy_v1` 的版本化规则；后续可根据回测新增 `position_policy_v2` 调整阈值。

### 5.4 bullish 映射为正目标仓位

规则：

```text
strategy_direction = bullish
且 strategy_strength >= min_strength_for_target
且 strategy_confidence >= min_confidence_for_target
→ target_intent = TARGET_POSITION
→ target_position_ratio > 0
```

### 5.5 bearish 映射为负目标仓位

规则：

```text
strategy_direction = bearish
且 strategy_strength >= min_strength_for_target
且 strategy_confidence >= min_confidence_for_target
→ target_intent = TARGET_POSITION
→ target_position_ratio < 0
```

### 5.6 none 或非法方向

规则：

```text
strategy_direction = none
或 strategy_direction 不属于 bullish / bearish / neutral / none
→ failed
```

`none` 通常不应进入 DecisionSnapshot。如果出现，说明上游放行合同异常。

## 6. 连续仓位映射公式

`position_policy_v1` 使用连续映射，不使用分段阶梯。

原因：

```text
避免 strength 在边界附近出现小幅变化却导致目标仓位大幅跳变；
便于回测和参数敏感性分析；
保持 P0 映射简单、可解释、可复算。
```

### 6.1 方向符号

```text
direction_sign =
  +1, strategy_direction = bullish
  -1, strategy_direction = bearish
```

### 6.2 strength 基础仓位

```text
strength_span
= 1 - min_strength_for_target

strength_score
= clamp(
    (strategy_strength - min_strength_for_target) / strength_span,
    0,
    1
  )

base_abs_position_ratio
= strength_score * max_abs_target_position_ratio
```

当：

```text
strategy_strength = min_strength_for_target
→ base_abs_position_ratio = 0

strategy_strength = 1
→ base_abs_position_ratio = max_abs_target_position_ratio
```

### 6.3 confidence 折减

P0 使用连续折减：

```text
confidence_multiplier
= clamp(strategy_confidence, 0, 1)
```

说明：

```text
confidence 不被解释为盈利概率；
confidence 只作为结构化策略置信评分的仓位折减因子；
低于 min_confidence_for_target 时已经被 NO_TRADE 过滤。
```

### 6.4 最终目标仓位

```text
raw_target_position_ratio
= direction_sign
* base_abs_position_ratio
* confidence_multiplier

target_position_ratio
= round_decimal(
    raw_target_position_ratio,
    rounding_decimal_places
  )
```

最终必须满足：

```text
-max_abs_target_position_ratio <= target_position_ratio <= +max_abs_target_position_ratio
-1.0 <= target_position_ratio <= +1.0
```

如果四舍五入后得到 `0.0000`：

```text
target_intent = NO_TRADE
target_position_ratio = null
target_reason_code = rounded_target_zero
```

## 7. 最小订单金额不在本算法处理

`position_policy_v1` 不设置固定最小目标仓位比例。

原因：

```text
目标仓位比例是否过小，取决于账户权益、当前价格、合约规则和当前持仓；
这些信息都不是 DecisionSnapshot 的输入；
如果在本算法里写死 0.05 这类最小比例，会把账户规模问题错误地放进目标仓位层。
```

最小调仓与最小订单由 OrderPlan 负责：

```text
OrderPlan 根据 current_equity、当前持仓、mark_price 和 target_position_ratio 计算目标名义；
OrderPlan 数量规范化后检查 min_rebalance_notional；
OrderPlan 同时检查交易所 min_quantity 和 min_notional；
不满足时返回 no_order_required，不生成 CandidateOrderIntent。
```

因此：

```text
position_policy_v1 可以输出很小的 target_position_ratio；
但是否形成真实候选订单，由 OrderPlan 的最小调仓判断决定。
```

## 8. StrategySignal.trade_price_condition

DecisionSnapshotService 可以把 StrategySignal 已冻结的 `trade_price_condition` 原样保存到 DecisionSnapshot。

规则：

```text
position_policy_v1 不读取 trade_price_condition；
position_policy_v1 不解释 trade_price_condition；
position_policy_v1 不根据价格条件调整 target_position_ratio；
DecisionSnapshot 只冻结该价格条件，供 OrderPlan 后续评估。
```

如果上游没有提供价格条件：

```text
frozen_trade_price_condition = null
```

如果上游提供价格条件：

```text
必须原样冻结；
不得改写字段；
不得补充 limit_price；
不得决定订单类型；
不得决定订单有效期。
```

## 9. 计算示例

### 9.1 bullish 有效信号

输入：

```text
direction = bullish
strength = 0.73
confidence = 0.70
min_strength_for_target = 0.55
max_abs_target_position_ratio = 0.50
```

计算：

```text
strength_score = (0.73 - 0.55) / 0.45 = 0.4
base_abs_position_ratio = 0.4 * 0.50 = 0.20
target_position_ratio = +1 * 0.20 * 0.70 = +0.14
```

输出：

```text
target_intent = TARGET_POSITION
target_position_ratio = +0.1400
```

### 9.2 bearish 有效信号

输入：

```text
direction = bearish
strength = 0.82
confidence = 0.65
```

计算：

```text
strength_score = (0.82 - 0.55) / 0.45 = 0.6
base_abs_position_ratio = 0.6 * 0.50 = 0.30
target_position_ratio = -1 * 0.30 * 0.65 = -0.195
```

输出：

```text
target_intent = TARGET_POSITION
target_position_ratio = -0.1950
```

### 9.3 neutral

输入：

```text
direction = neutral
strength = 0.80
confidence = 0.80
```

输出：

```text
target_intent = NO_TRADE
target_position_ratio = null
target_reason_code = neutral_signal
```

### 9.4 强度不足

输入：

```text
direction = bullish
strength = 0.54
confidence = 0.80
```

输出：

```text
target_intent = NO_TRADE
target_position_ratio = null
target_reason_code = strength_below_threshold
```

### 9.5 置信度不足

输入：

```text
direction = bearish
strength = 0.80
confidence = 0.54
```

输出：

```text
target_intent = NO_TRADE
target_position_ratio = null
target_reason_code = confidence_below_threshold
```

## 10. decision_calculation_snapshot

`decision_calculation_snapshot` 必须保存可复算摘要。

至少包括：

```text
policy_code
policy_version
min_strength_for_target
min_confidence_for_target
max_abs_target_position_ratio
strategy_direction
strategy_strength
strategy_confidence
strength_span
strength_score
base_abs_position_ratio
confidence_multiplier
raw_target_position_ratio
target_position_ratio
target_intent
target_reason_code
```

不得保存：

```text
账户余额；
当前持仓；
当前价格；
MarketRegime 细节；
DomainSignal 细节；
订单计划结果；
风控结果；
Execution 结果。
```

## 11. evidence_items

证据必须说明：

```text
StrategySignalQuality 已放行；
使用了哪个 DecisionPolicyDefinition；
使用了哪些参数；
为什么输出 TARGET_POSITION / NO_TRADE；
target_position_ratio 如何计算；
是否冻结了 StrategySignal.trade_price_condition。
```

证据不得写成：

```text
买入；
卖出；
做多；
做空；
加仓；
减仓；
平仓；
提交订单。
```

## 12. 版本管理

本文件定义：

```text
policy_code = position_policy
policy_version = v1
calculator_type = decision_policy
algorithm_name = position_policy
algorithm_version = v1
```

后续如果修改以下内容，必须新增版本：

```text
方向到仓位的映射公式；
strength 映射方式；
confidence 折减方式；
neutral 处理方式；
弱信号处理方式；
max_abs_target_position_ratio 默认值；
是否引入最小目标仓位比例；
是否引入 NO_TARGET_CHANGE。
```

不得静默修改已经用于复盘或实盘的历史版本语义。

## 13. 验收要求

文档验收：

```text
本算法不读取账户。
本算法不读取当前持仓。
本算法不读取当前价格。
本算法不读取 MarketRegime / DomainSignal。
本算法不按 strategy_code / strategy_version 分支。
本算法不解释 trade_price_condition。
本算法不判断最小订单金额。
本算法不生成订单。
本算法只输出目标仓位意图。
```

实现验收：

```text
neutral → NO_TRADE；
strength < 0.55 → NO_TRADE；
confidence < 0.55 → NO_TRADE；
bullish 且通过阈值 → TARGET_POSITION，target_position_ratio > 0；
bearish 且通过阈值 → TARGET_POSITION，target_position_ratio < 0；
target_position_ratio 绝对值不超过 max_abs_target_position_ratio；
同 direction / strength / confidence 输入在不同 strategy_code 下输出一致；
trade_price_condition 被 Service 原样冻结，不参与 calculator；
小额订单不在本算法过滤，由 OrderPlan min_rebalance_notional / min_notional 处理。
```

## 14. 最高红线

`position_policy_v1` 不得违反以下规则：

```text
不得真实下单。
不得生成 CandidateOrderIntent。
不得生成 ApprovedOrderIntent。
不得生成 PreparedOrderIntent。
不得访问 Binance。
不得访问账户事实。
不得访问价格事实。
不得读取 MarketRegime 做二次分析。
不得读取 DomainSignal 做二次加权。
不得按策略类型分支。
不得释放 ActiveLock。
不得调用大模型。
不得发送 Hermes。
不得把目标仓位解释成订单动作。
```
