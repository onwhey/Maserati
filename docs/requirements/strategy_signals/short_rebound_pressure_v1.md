# short_rebound_pressure_v1 策略信号算法需求

## 1. 模块定位

`short_rebound_pressure_v1` 是空头反弹压力策略信号算法。

它负责在系统已经识别出大背景偏空、但当前处于反弹或低位区间震荡时，基于领域事实判断压力侧是否具备偏空策略信号条件。

它回答的问题是：

```text
当前反弹是否仍属于空头结构中的正常反弹；
价格是否处在值得观察的压力区域附近；
压力事实、动能变化、波动状态和风险状态是否支持偏空策略信号；
如果不支持，为什么保持中性。
```

它不负责：

```text
重新计算 FeatureValue
重新计算 AtomicSignalValue
重新计算 DomainSignalValue
重新识别 MarketRegime
重新选择 StrategyDefinition
判断顶部或底部反转
处理趋势修复后的转换期
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

`short_rebound_pressure_v1` 的输出仍然只是策略层判断，不等于 `DecisionSnapshot`，也不等于交易指令。

## 2. 适用市场环境

本策略只允许由 `StrategyRouting` 在以下市场环境中选择：

```text
bearish_rebound
bearish_low_range
```

业务含义：

```text
bearish_rebound：大背景偏空，1d 下跌结构未确认改变，但 4h 或动能出现反弹。
bearish_low_range：大背景偏空，价格处于低位区间或趋势推进暂缓，策略只关注靠近压力侧的机会。
```

以下市场环境不得路由到本策略：

```text
bearish_trend_continuation
bearish_breakdown
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
MarketRegimeSnapshot 可以作为上游路由与审计追溯对象存在，但 short_rebound_pressure_v1 的计算不得依赖 MarketRegimeSnapshot 重新解释市场。
策略算法只消费领域层已经形成的事实，避免策略层绕回去重新做领域判断。
```

## 4. 内部策略模式

本策略内部只有两个模式：

```text
rebound_to_pressure：空头趋势中的反弹接近压力
low_range_pressure：空头低位区间中的压力侧观察
```

### 4.1 空头反弹接近压力

当领域事实同时满足以下条件时，可以进入 `rebound_to_pressure` 模式：

```text
market_context 显示大级别背景偏空；
trend 显示 1d 空头结构未被修复；
4h 反弹没有直接改写 1d 大方向；
structure 显示价格接近有效压力区，且关键压力没有被有效向上突破；
momentum 显示上涨动能减弱、钝化或不再继续增强；
volatility 没有显示不可分类的异常波动；
risk_state 没有显示高风险导致信号不可用。
```

业务含义：

```text
这不是追空策略，而是在空头背景下观察反弹是否进入更合理的位置；
反弹本身不是偏空理由，压力有效和上涨动能减弱才是策略确认重点。
```

### 4.2 空头低位区间压力侧

当领域事实同时满足以下条件时，可以进入 `low_range_pressure` 模式：

```text
market_context 显示大级别背景偏空；
trend 没有显示 1d 空头结构被有效修复；
structure 显示当前处于低位区间，但价格靠近区间压力侧，而不是靠近支撑侧或区间中部；
momentum 没有显示持续失控上涨；
volatility 显示区间波动可以被解释；
risk_state 没有显示高风险导致信号不可用。
```

业务含义：

```text
低位区间不等于自动偏空；
低位区间本身可能存在底部反转风险；
只有靠近压力侧、压力仍有效、反弹动能没有失控时，本策略才允许给出偏空信号。
```

如果 `rebound_to_pressure` 与 `low_range_pressure` 同时成立，优先使用更贴近 `MarketRegime` 路由来源的模式。

## 5. 反弹与趋势修复的边界

本策略必须区分三类情况。

### 5.1 正常反弹

```text
大背景偏空；
1d 结构未修复；
4h 出现反弹；
价格接近压力；
上涨动能减弱；
风险状态可控。
```

这种情况可以输出 `bearish`。

### 5.2 反弹仍在进行

```text
大背景偏空；
但 4h 上涨仍在推进；
价格尚未接近压力，或刚接近压力但上涨动能仍强；
压力有效性尚未被确认。
```

这种情况应输出 `neutral`，并说明“反弹尚未结束或价格条件不足”。

### 5.3 空头结构被修复

```text
大背景原本偏空；
但关键压力被有效向上突破；
1d 结构开始修复；
动能和风险事实不再支持把当前上涨解释为普通反弹。
```

这种情况不属于本策略的有效偏空场景。

处理规则：

```text
如果 StrategyRouting 已经没有选择本策略，则本策略不运行；
如果本策略被错误选择或输入事实在计算时显示结构修复，本策略不得输出 bearish；
本策略只能输出 neutral 或阻断，并在证据中说明“空头结构修复，不属于反弹压力策略范围”。
```

本策略不得自行把趋势修复解释为做多策略，也不得生成清仓、减仓或反手动作。

## 6. 打分逻辑

本策略采用组件打分方式。

组件包括：

```text
大背景分
趋势完整性分
压力质量分
反弹动能分
波动分
风险折减
```

### 6.1 大背景分

大背景分来自 `market_context`。

规则：

```text
大级别背景偏空：使用领域强度作为正向分。
大级别背景中性：本策略原则上不应被路由；如果进入本策略，应阻断或输出 neutral。
大级别背景偏多：本策略不得输出 bearish。
```

### 6.2 趋势完整性分

趋势完整性分来自 `trend`。

规则：

```text
1d 空头结构保持：趋势完整性分较高。
1d 偏空但 4h 反弹：不直接否定空头，但需要 structure 与 momentum 支持。
1d 不明确：降低强度和置信度。
1d 偏多或关键趋势结构修复：不得输出 bearish。
```

### 6.3 压力质量分

压力质量分来自 `structure`。

规则：

```text
价格接近 1d 关键压力或 1d / 4h 压力共振区域：压力质量分最高。
价格接近 4h 小结构压力，但 1d 大结构没有修复：压力质量分中等。
价格处于区间中部：压力质量分低。
价格靠近支撑侧：不得因为大背景偏空就输出强信号。
关键压力被有效向上突破：不得输出 bearish。
```

`structure` 只提供支撑、压力、区间位置和突破 / 跌破事实，不提供“卖出”“开空”“加空”等操作建议。

### 6.4 反弹动能分

反弹动能分来自 `momentum`。

规则：

```text
上涨动能减弱、反弹钝化、反向走弱开始出现：支持偏空策略信号。
动能中性：可以保留观察，但降低强度和置信度。
上涨动能继续增强：不得输出强偏空信号。
出现明显多头动能延续：不得输出 bearish。
```

### 6.5 波动分

波动分来自 `volatility`。

规则：

```text
波动正常或压力附近可解释放大：支持策略信号。
波动压缩：可以保留观察，但需要 structure 与 momentum 给出更明确证据。
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

## 7. 聚合公式

基础强度按以下权重聚合：

```text
raw_strength =
  0.25 * context_score
  + 0.20 * trend_integrity_score
  + 0.25 * pressure_quality_score
  + 0.20 * rebound_momentum_score
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
压力位置是否清晰
反弹状态是否清晰
风险事实是否清晰
是否存在明显冲突证据
```

置信度示意：

```text
confidence =
  0.25 * input_completeness
  + 0.25 * pressure_clarity
  + 0.20 * rebound_clarity
  + 0.20 * domain_agreement
  + 0.10 * risk_clarity
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
价格位于压力侧或反弹合理区域；
不存在关键领域事实冲突；
risk_state 未显示高风险导致信号不可用；
structure 未显示关键压力被有效向上突破；
momentum 未显示上涨动能继续失控增强。
```

输出 `neutral` 的典型情况：

```text
大背景偏空但反弹尚未结束；
价格尚未到达压力侧；
价格位于区间中部或支撑侧；
压力存在但上涨动能仍强；
压力被突破或趋势完整性不足；
波动风险可分类但会明显降低信号质量；
领域之间存在轻度冲突，但尚未达到计算失败。
```

`neutral` 表示本策略不给出有效偏空策略信号，不等于交易指令，也不等于撤单或清仓指令。

## 9. 交易价格条件

本策略可以输出 `trade_price_condition`，用于表达策略认为更合理的价格区域。

`trade_price_condition` 只能表达：

```text
适合观察的压力区域
不宜追价的条件
反弹未结束的条件
压力失效的条件
区间中部或支撑侧不适合本策略的提示
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
  "condition_type": "rebound_pressure_price_zone",
  "reference_price_zone": "1d / 4h 压力区附近",
  "acceptable_price_zone": "1d / 4h 压力区附近，且压力未被有效突破",
  "support_or_resistance_refs": ["structure.resistance_zone", "structure.current_zone_position"],
  "allow_chasing": false,
  "reason_code": "pressure_valid_wait_rebound_confirmation",
  "reason_summary_zh": "价格仍在区间中部、靠近支撑侧，或上涨动能仍在增强时不适合本策略"
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
反弹压力模式下，失效参考通常来自压力区上沿或关键压力被有效突破的位置。
低位区间压力侧模式下，失效参考通常来自区间上沿或压力失效位置。
如果没有清晰支撑区，不得编造 reference_take_profit，应输出 null 并写明原因。
```

这些信息不是自动保护单，不得被 Execution 直接解释为止损止盈订单。

如果真实成交后市场继续上涨，P0 由下一轮 4h 编排重新分析并生成新的策略信号和目标仓位决策，不做实时防守。

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
到压力了，做空。
反弹结束，加空。
风险高，停止交易。
```

正确示例：

```text
大背景偏空，1d 结构未修复，4h 反弹接近压力区；但上涨动能仍未明显减弱，因此策略方向保持 neutral，等待压力事实进一步确认。
```

## 12. 输出示例

### 12.1 正常反弹接近压力

```json
{
  "strategy_code": "short_rebound_pressure",
  "strategy_version": "v1",
  "internal_mode": "rebound_to_pressure",
  "direction": "bearish",
  "strength": 0.61,
  "confidence": 0.58,
  "prediction_horizon": "next_1_to_3_closed_4h",
  "trade_price_condition": {
    "condition_type": "rebound_pressure_price_zone",
    "reference_price_zone": "压力区附近",
    "acceptable_price_zone": "压力区附近且压力未被有效突破",
    "support_or_resistance_refs": ["structure.resistance_zone", "structure.current_zone_position"],
    "allow_chasing": false,
    "reason_code": "pressure_valid_rebound_momentum_weakening",
    "reason_summary_zh": "价格远离压力区或上涨动能继续增强时不适合本策略"
  },
  "aggregation_snapshot": {
    "component_scores": {
      "context": 0.72,
      "trend_integrity": 0.65,
      "pressure_quality": 0.69,
      "rebound_momentum": 0.57,
      "volatility": 0.63
    },
    "risk_reference": {
      "invalidation_level": "压力区上沿",
      "reference_stop_loss": "压力区上沿附近",
      "reference_take_profit": "下一支撑区或 null",
      "risk_reward_comment": "仅作为策略解释和风控参考，不是自动订单"
    }
  }
}
```

### 12.2 反弹仍在进行

```json
{
  "strategy_code": "short_rebound_pressure",
  "strategy_version": "v1",
  "internal_mode": "rebound_to_pressure",
  "direction": "neutral",
  "strength": 0.47,
  "confidence": 0.54,
  "prediction_horizon": "next_1_to_3_closed_4h",
  "trade_price_condition": {
    "condition_type": "rebound_pressure_price_zone",
    "reference_price_zone": "压力区附近且上涨动能减弱",
    "acceptable_price_zone": "压力区附近且上涨动能减弱",
    "support_or_resistance_refs": ["structure.resistance_zone", "structure.current_zone_position"],
    "allow_chasing": false,
    "reason_code": "rebound_still_in_progress",
    "reason_summary_zh": "当前上涨动能仍强，压力确认不足"
  },
  "aggregation_snapshot": {
    "reason": "大背景偏空，但反弹仍在推进，策略不给出有效偏空信号"
  }
}
```

## 13. 版本管理

本文件定义：

```text
strategy_code = short_rebound_pressure
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
本策略只处理空头反弹压力与空头低位区间压力侧。
本策略可以解释为什么 bearish 或 neutral。
本策略可以输出价格条件，但不决定订单类型和限价单价格。
本策略可以输出风险参考，但不生成自动止损止盈订单。
```

实现验收：

```text
当路由环境为 bearish_rebound 且压力有效、反弹动能减弱时，应生成 bearish StrategySignal。
当路由环境为 bearish_low_range 且价格靠近压力侧、压力有效时，可以生成 bearish StrategySignal。
当价格仍在区间中部、靠近支撑侧或反弹动能仍强时，应生成 neutral StrategySignal。
当 structure 显示关键压力被有效向上突破时，不得生成 bearish StrategySignal。
当 risk_state 显示高风险导致信号不可靠时，不得生成 bearish StrategySignal。
当输入领域不完整或版本不属于当前 release 时，应阻断或失败，不得用默认值生成信号。
```

## 15. 最高红线

`short_rebound_pressure_v1` 不得违反以下规则：

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
不得把“到压力区”直接写成“应该交易”。
```
