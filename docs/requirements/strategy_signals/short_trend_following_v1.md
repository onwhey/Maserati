# short_trend_following_v1 策略信号算法需求

## 1. 模块定位

`short_trend_following_v1` 是空头趋势跟随策略信号算法。

它负责在系统已经识别出空头趋势延续或向下跌破环境后，基于领域事实生成标准化 `StrategySignal`。

它回答的问题是：

```text
在当前空头趋势或向下跌破环境下，是否值得给出偏空策略信号；
如果值得，信号强度、置信度、证据和交易价格条件是什么；
如果不值得，为什么保持中性。
```

它不负责：

```text
重新计算 FeatureValue
重新计算 AtomicSignalValue
重新计算 DomainSignalValue
重新识别 MarketRegime
重新选择 StrategyDefinition
生成目标仓位
生成订单
决定订单类型
决定限价单价格
决定订单有效期
决定真实交易
提交订单
撤单
实时防守
自动止损止盈
```

`short_trend_following_v1` 的输出仍然只是策略层判断，不等于 `DecisionSnapshot`，也不等于交易指令。

## 2. 适用市场环境

本策略只允许由 `StrategyRouting` 在以下市场环境中选择：

```text
bearish_trend_continuation
bearish_breakdown
```

业务含义：

```text
bearish_trend_continuation：大背景与趋势仍然偏空，价格结构没有向上修复，空头趋势仍有延续条件。
bearish_breakdown：价格已经有效向下跌破关键支撑区，并且趋势、动能、波动和风险状态支持将其视为有效跌破候选。
```

以下市场环境不得路由到本策略：

```text
bearish_rebound
bearish_low_range
bearish_bottom_reversal_candidate
bullish_trend_continuation
bullish_breakout
bullish_pullback
bullish_high_range
bullish_top_reversal_candidate
neutral_range
high_risk_environment
unclear_environment
```

如果运行时发现路由结果与本策略适用范围不一致，应阻断本次 StrategySignal 计算，并写明原因。

## 3. 输入边界

本策略只读取同一轮 `DomainSignalSet` 中已经批准发布的领域事实。

必需领域：

```text
market_context
trend
momentum
volatility
structure
risk_state
```

本策略不得直接读取：

```text
Kline
MarketSnapshot
FeatureValue
AtomicSignalValue
MarketRegimeSnapshot 作为计算输入
BinanceAccountSnapshot
PriceSnapshot
OrderPlan
RiskCheck
Execution
```

说明：

```text
MarketRegimeSnapshot 可以作为上游路由与审计追溯对象存在，但 short_trend_following_v1 的计算不得依赖 MarketRegimeSnapshot 重新解释市场。
策略算法只消费领域层已经形成的事实，避免策略层绕回去重新做领域判断。
```

## 4. 内部策略模式

本策略内部只有两个模式：

```text
trend_continuation：空头趋势延续
breakdown_continuation：空头向下跌破延续
```

### 4.1 空头趋势延续

当领域事实同时满足以下条件时，可以进入 `trend_continuation` 模式：

```text
market_context 显示大级别背景偏空或至少不明显偏多；
trend 显示 1d 与 4h 的趋势结构整体偏空；
momentum 没有显示空头动能明显衰竭；
structure 没有显示关键压力被有效向上突破；
volatility 没有显示不可分类的异常波动；
risk_state 没有显示高风险导致信号不可用。
```

业务含义：

```text
趋势仍然有效，但不要求价格正在跌破新支撑区；
策略关注的是顺势跟随，而不是在压力区做反弹压制，也不是在低位区间做震荡交易。
```

### 4.2 空头向下跌破延续

当领域事实同时满足以下条件时，可以进入 `breakdown_continuation` 模式：

```text
structure 显示价格已有效向下跌破关键支撑区，或 4h 小结构跌破与 1d 大结构未修复形成一致；
trend 显示趋势方向偏空；
momentum 显示跌破具备动能支持，而不是明显钝化、缩量或反向衰竭；
volatility 显示跌破波动可以被解释，而不是不可分类的异常插针；
risk_state 没有显示高风险导致信号不可用。
```

业务含义：

```text
跌破是否真实，首先由 MarketRegime 和 structure / momentum / volatility / risk_state 的领域事实共同过滤；
策略层只在已经通过前置过滤后，判断这个跌破是否值得给出偏空策略信号。
```

如果 `trend_continuation` 与 `breakdown_continuation` 同时成立，优先使用 `breakdown_continuation`。

## 5. 假跌破处理边界

假跌破识别分两层。

第一层由前置市场分析完成：

```text
structure 负责描述是否跌破、跌破发生在哪个周期和哪个结构级别；
momentum 负责描述跌破是否有动能支持；
volatility 负责描述跌破波动是否异常；
risk_state 负责描述当前市场是否存在会使信号不可靠的高风险事实；
MarketRegime 负责综合领域事实，将明显假跌破、高风险或无法分类的情况识别为不适合本策略的市场环境。
```

第二层由本策略做策略确认：

```text
如果跌破事实存在，但动能、趋势、波动或风险证据不足，本策略不得硬给偏空信号；
可以输出 neutral，并在证据中说明“跌破存在但策略确认不足”。
```

本策略不得把假跌破处理写成实时防守系统。

## 6. 打分逻辑

本策略采用组件打分方式。

组件包括：

```text
大背景分
趋势分
动能分
结构分
波动分
风险折减
```

### 6.1 大背景分

大背景分来自 `market_context`。

规则：

```text
大级别背景偏空：使用领域强度作为正向分。
大级别背景中性：允许参与跌破模式，但最终强度与置信度需要被上限约束。
大级别背景偏多：本策略原则上不应被路由；如果进入本策略，应阻断或输出 neutral。
```

### 6.2 趋势分

趋势分来自 `trend`。

规则：

```text
1d 偏空且 4h 同向：趋势分最高。
1d 偏空但 4h 反弹：趋势分下降，但不直接否定空头趋势。
1d 中性但 4h 偏空：只允许作为跌破模式的辅助证据，不应单独形成强偏空信号。
1d 偏多：本策略原则上不应输出偏空信号。
```

### 6.3 动能分

动能分来自 `momentum`。

规则：

```text
向下动能增强或维持：支持偏空策略信号。
动能中性：可以保留偏空方向，但降低强度和置信度。
空头动能衰竭或出现反向背离：不得给出强偏空信号。
```

### 6.4 结构分

结构分来自 `structure`。

规则：

```text
有效向下跌破关键支撑区：结构分最高，优先进入跌破延续模式。
趋势结构保持偏空但未跌破新支撑：结构分中等，进入趋势延续模式。
靠近下方关键支撑且尚未跌破：不得因为趋势偏空就给出强信号，应降低强度。
关键压力被有效向上突破：本策略不得输出偏空信号。
```

`structure` 只提供价格结构事实，不提供“卖出”“开空”“减仓”等操作建议。

### 6.5 波动分

波动分来自 `volatility`。

规则：

```text
波动正常或可解释扩张：支持策略信号。
波动压缩：趋势延续模式降低强度；跌破模式需要等待结构事实确认。
波动异常但可分类：降低置信度，不直接否定。
波动异常且不可分类：本策略不得输出有效偏空信号。
```

### 6.6 风险折减

风险折减来自 `risk_state`。

规则：

```text
无明显异常风险：不折减。
存在可分类风险：降低强度和置信度。
存在高风险且信号不可靠：本策略不得输出有效偏空信号。
风险事实不清楚：本策略不得输出有效偏空信号。
```

`risk_state` 只描述市场风险事实，不决定是否交易；是否输出策略信号由本策略根据所有领域事实综合决定。

空头趋势策略需要额外注意：

```text
急跌后的快速反抽、插针回收、低位超跌反弹，都可能使偏空信号失真；
这些现象应通过 momentum / volatility / structure / risk_state 的领域事实体现；
本策略只做最终策略确认，不自行重新识别这些事实。
```

## 7. 聚合公式

基础强度按以下权重聚合：

```text
raw_strength =
  0.25 * context_score
  + 0.25 * trend_score
  + 0.20 * momentum_score
  + 0.20 * structure_score
  + 0.10 * volatility_score
```

最终强度：

```text
strength = clamp(raw_strength * risk_multiplier, 0, 1)
```

置信度按以下维度计算：

```text
输入完整性
领域之间是否同向
当前内部策略模式是否清晰
风险事实是否清晰
是否存在明显冲突证据
```

置信度示意：

```text
confidence =
  0.30 * input_completeness
  + 0.30 * domain_agreement
  + 0.20 * mode_clarity
  + 0.20 * risk_clarity
  - conflict_penalty
```

所有分值必须限制在 `[0, 1]`。

如果任一必需领域缺失、版本不属于当前 `StrategyAnalysisRelease`、或领域结果不可消费，应输出计算失败或阻断结果，不得用默认值硬凑信号。

## 8. 输出规则

本策略只允许输出以下方向：

```text
bearish
neutral
```

不得输出：

```text
bullish
long
short
buy
sell
open_short
close_short
increase_position
reduce_position
```

输出 `bearish` 的最低条件：

```text
内部策略模式明确；
strength >= 0.55；
confidence >= 0.55；
不存在关键领域事实冲突；
risk_state 未显示高风险导致信号不可用；
structure 未显示关键压力被有效向上突破。
```

输出 `neutral` 的典型情况：

```text
趋势偏空但动能不足；
跌破存在但策略确认不足；
价格过度远离合理交易区域；
波动风险可分类但会明显降低信号质量；
领域之间存在轻度冲突，但尚未达到计算失败。
```

`neutral` 表示本策略不给出有效偏空策略信号，不等于交易指令，也不等于撤单或清仓指令。

## 9. 交易价格条件

本策略可以输出 `trade_price_condition`，用于表达策略认为更合理的价格区域。

`trade_price_condition` 只能表达：

```text
适合观察的价格区间
不宜追价的条件
跌破回抽区域
趋势延续可接受区域
距离关键结构过远时的提示
```

不得表达：

```text
订单类型
限价单价格
市价单价格
下单数量
订单有效期
交易所参数
```

示例：

```json
{
  "condition_type": "breakdown_continuation_price_zone",
  "reference_price_zone": "跌破支撑区或跌破后回抽不修复区域",
  "acceptable_price_zone": "跌破支撑区下方但尚未明显过度延伸",
  "support_or_resistance_refs": ["structure.support_zone", "structure.breakdown_zone"],
  "allow_chasing": false,
  "reason_code": "breakdown_valid_but_no_chasing",
  "reason_summary_zh": "跌破有效但价格远离跌破区且向下动能没有继续增强时不宜追价"
}
```

后续是否使用限价单、限价单价格如何生成、订单有效期如何设置，属于 `OrderPlan / ExecutionPreparation / Execution` 的职责，不属于本策略。

## 10. 风险参考信息

本策略可以在 `aggregation_snapshot.risk_reference` 中输出风险参考信息。

风险参考信息包括：

```text
invalidation_level：策略判断失效参考位置
reference_stop_loss：用于风控和复盘参考的止损位置
reference_take_profit：用于复盘参考的目标区域或下一支撑区
risk_reward_comment：风险收益结构说明
```

规则：

```text
跌破延续模式下，失效参考通常来自跌破区上沿或回抽失败区域。
趋势延续模式下，失效参考通常来自关键压力区上沿或趋势结构修复位置。
如果没有清晰支撑区，不得编造 reference_take_profit，应输出 null 并写明原因。
```

这些信息不是自动保护单，不得被 Execution 直接解释为止损止盈订单。

如果真实成交后市场反向运行，P0 由下一轮 4h 编排重新分析并生成新的策略信号和目标仓位决策，不做实时防守。

## 11. 证据要求

每个 `StrategySignal` 必须保存可解释证据。

证据至少包括：

```text
选择的内部策略模式
使用了哪些领域事实
各组件分数
强度和置信度来源
支持偏空的证据
削弱偏空的证据
是否存在冲突证据
价格条件说明
风险参考说明
为什么输出 bearish 或 neutral
```

证据不得写成喊单话术。

错误示例：

```text
跌破了，做空。
趋势很弱，加空。
风险高，停止交易。
```

正确示例：

```text
大背景偏空，1d 与 4h 趋势同向，结构显示 4h 已跌破前支撑区；但当前价格距离跌破区偏远，因此策略方向为 bearish，强度中等，交易价格条件提示不宜追价。
```

## 12. 输出示例

### 12.1 空头趋势延续

```json
{
  "strategy_code": "short_trend_following",
  "strategy_version": "v1",
  "internal_mode": "trend_continuation",
  "direction": "bearish",
  "strength": 0.66,
  "confidence": 0.63,
  "prediction_horizon": "next_1_to_3_closed_4h",
  "trade_price_condition": {
    "condition_type": "trend_continuation_price_zone",
    "reference_price_zone": "趋势结构未修复时的压力结构附近",
    "acceptable_price_zone": "趋势结构未修复且价格未明显远离压力结构",
    "support_or_resistance_refs": ["structure.resistance_zone", "structure.trend_structure"],
    "allow_chasing": false,
    "reason_code": "trend_valid_no_chasing",
    "reason_summary_zh": "趋势结构仍偏空，但不允许在价格明显远离压力结构时追价"
  },
  "aggregation_snapshot": {
    "component_scores": {
      "context": 0.70,
      "trend": 0.74,
      "momentum": 0.62,
      "structure": 0.60,
      "volatility": 0.68
    },
    "risk_reference": {
      "invalidation_level": "关键压力区上沿",
      "reference_stop_loss": "关键压力区上沿附近",
      "reference_take_profit": "下一支撑区或 null",
      "risk_reward_comment": "仅作为策略解释和风控参考，不是自动订单"
    }
  }
}
```

### 12.2 空头跌破但不宜追价

```json
{
  "strategy_code": "short_trend_following",
  "strategy_version": "v1",
  "internal_mode": "breakdown_continuation",
  "direction": "neutral",
  "strength": 0.51,
  "confidence": 0.57,
  "prediction_horizon": "next_1_to_3_closed_4h",
  "trade_price_condition": {
    "condition_type": "breakdown_continuation_price_zone",
    "reference_price_zone": "跌破区下方或回抽不修复区域",
    "acceptable_price_zone": "跌破区下方或回抽不修复区域",
    "support_or_resistance_refs": ["structure.breakdown_zone", "structure.support_zone"],
    "allow_chasing": false,
    "reason_code": "price_too_far_from_breakdown_zone",
    "reason_summary_zh": "当前价格已经明显远离跌破区，且向下动能没有继续增强"
  },
  "aggregation_snapshot": {
    "reason": "跌破事实存在，但价格条件不适合追随，策略不给出有效偏空信号"
  }
}
```

## 13. 版本管理

本文件定义：

```text
strategy_code = short_trend_following
strategy_version = v1
```

后续如果修改本策略算法，应新增新的策略算法需求文件或在策略定义中新增版本，不得静默修改已经用于复盘或实盘的历史版本语义。

策略版本属于 StrategyAnalysisRelease 可选择的组成部分。

## 14. 验收要求

文档验收：

```text
本策略没有生成订单动作。
本策略没有生成目标仓位。
本策略没有直接读取 FeatureValue / AtomicSignalValue / Kline。
本策略没有绕过 MarketRegime 和 StrategyRouting。
本策略只处理空头趋势延续与向下跌破。
本策略可以解释为什么 bearish 或 neutral。
本策略可以输出价格条件，但不决定订单类型和限价单价格。
本策略可以输出风险参考，但不生成自动止损止盈订单。
```

实现验收：

```text
当路由环境为 bearish_trend_continuation 且领域事实同向时，应生成 bearish StrategySignal。
当路由环境为 bearish_breakdown 且跌破证据充分时，应生成 bearish StrategySignal。
当跌破存在但价格过度远离合理区域时，应生成 neutral StrategySignal，并写明不宜追价。
当 risk_state 显示高风险导致信号不可靠时，不得生成 bearish StrategySignal。
当 structure 显示关键压力被有效向上突破时，不得生成 bearish StrategySignal。
当输入领域不完整或版本不属于当前 release 时，应阻断或失败，不得用默认值生成信号。
```

## 15. 最高红线

`short_trend_following_v1` 不得违反以下规则：

```text
不得真实下单。
不得生成 CandidateOrderIntent。
不得生成 ApprovedOrderIntent。
不得生成 PreparedOrderIntent。
不得访问 Binance。
不得访问账户事实。
不得访问价格事实。
不得释放 ActiveLock。
不得调用大模型。
不得发送 Hermes。
不得把 risk_state 的高风险事实直接写成交易动作。
不得把 structure 的支撑压力事实直接写成交易动作。
```
