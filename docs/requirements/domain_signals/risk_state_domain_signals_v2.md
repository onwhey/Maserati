# Risk State Domain Signals v2

## 1. 文件定位

本文档定义 `risk_state` 领域第二版聚合口径。

RiskState v2 的核心目标不是预测涨跌，也不是替代风控，而是判断：

```text
当前市场是否还适合被普通趋势、反弹、回调、突破、跌破逻辑正常解释。
```

换句话说，RiskState v2 是市场事实链路里的“信号可靠性与市场混乱度识别层”。

它消费同一版本包内已选中的 `risk_state` AtomicSignalValue，生成一份 `risk_state` DomainSignalValue，为后续 MarketRegime 复验提供风险上下文。

当前阶段只补全 RiskState 领域事实，不开发 MarketRegime 消费逻辑，也不进入 StrategySignal。StrategySignal 是否以及如何消费 RiskState，必须等领域层复核和 MarketRegime 主环境边界稳定后另行验收。

本文档回答：

```text
当前是否出现极端冲击；
极端冲击后是否仍处于观察期；
当前是否高波动但无明确方向；
突破 / 跌破信号是否可能失真；
普通市场环境分类是否应降低可信度；
风险状态强度如何用分数表达；
为什么 RiskState 不输出交易建议。
```

本文档不负责：

```text
读取 FeatureValue；
读取 Kline；
重新计算 AtomicSignal；
读取账户、持仓、订单或成交；
判断系统当前是否真的有多仓或空仓；
决定是否开仓、平仓、减仓、加仓或空仓；
选择策略；
生成 StrategySignal；
生成 DecisionSnapshot；
读取 PriceSnapshot；
请求 Binance；
执行真实交易；
调用大模型。
```

## 2. 核心设计原则

### 2.1 风险识别与风控分离

RiskState 只描述市场风险事实。

它可以说：

```text
当前存在下行冲击；
当前处于冲击后观察期；
当前方向稳定性低；
当前信号失真风险高；
当前追空风险升高；
当前突破信号可靠性下降。
```

它不得说：

```text
应该停止交易；
应该开多；
应该开空；
应该减仓；
应该空仓；
应该阻断订单；
应该降低杠杆。
```

这些属于 StrategySignal、StrategySignalQuality、DecisionSnapshot、OrderPlan、RiskCheck 或更下游模块。

### 2.2 承认市场有时不可解释

趋势系统不应该在所有行情里强行寻找趋势。

当市场处于以下状态时，RiskState 应明确告诉下游“普通解释可信度下降”：

```text
极端冲击刚刚发生；
冲击后仍未恢复稳定；
高波动但方向频繁反转；
突破 / 跌破快速失败；
上下影线剧烈扫动；
短时间多空信号互相打脸。
```

这不是回避判断，而是更准确的市场事实表达。

### 2.3 保持 state_code 兼容，细节放入 payload

为避免 MarketRegime、StrategySignal 等下游被状态名频繁改动拖住，v2 暂时保留 v1 的四类主状态：

```text
risk_clear；
risk_elevated_classifiable；
risk_high_signal_unreliable；
risk_unclear。
```

新增细节通过 `payload_summary` 表达，例如：

```text
risk_score；
signal_distortion_score；
direction_stability_score；
risk_effect_tags；
primary_risk_event；
risk_event_phase；
post_shock_observation_bars_remaining。
```

## 3. 输入边界

RiskState v2 只能读取同一 AtomicSignalSet 中：

```text
归属于 risk_state 领域；
被当前 StrategyAnalysisRelease 选中；
status = created；
is_valid = true；
definition_status = active；
definition_enabled = true。
```

不得读取：

```text
FeatureValue；
Kline；
MarketSnapshot 原始行情；
其它领域 AtomicSignalValue；
其它 DomainSignalValue；
MarketRegimeSnapshot；
StrategyRouteDecision；
StrategySignal；
DecisionSnapshot；
账户、持仓、订单或成交；
PriceSnapshot；
Binance；
DeepSeek。
```

如果 v2 需要表达“冲击后观察期”，必须由 Feature / AtomicSignal 在当前 MarketSnapshot 的历史窗口中计算完成。

DomainSignal 不得通过读取上一轮 DomainSignal 或数据库历史状态来维持观察期。

## 4. 输出模式

RiskState v2 输出一份 DomainSignalValue：

```text
direction = none；
state_code = risk_clear / risk_elevated_classifiable / risk_high_signal_unreliable / risk_unclear；
strength = 主风险强度，0-1；
agreement_ratio = 0；
coverage_ratio = 有效 risk_state 原子覆盖率；
payload_summary = 市场事件分数、信号失真分数、方向暴露、风险标签、解释证据。
```

`direction = none` 的含义：

```text
RiskState 不表达市场方向；
RiskState 不表达交易方向；
RiskState 不表达目标仓位方向。
```

## 5. payload_summary 目标结构

v2 的 `payload_summary` 至少应包含：

```json
{
  "risk_state": "risk_high_signal_unreliable",
  "risk_score": 82,
  "market_event_score": 82,
  "signal_distortion_score": 86,
  "directional_exposure_score": 0,
  "chase_risk_score": 0,
  "direction_stability_score": 24,
  "primary_risk_event": "high_volatility_no_direction",
  "risk_event_phase": "post_shock_observation",
  "post_shock_observation_bars_remaining": 3,
  "risk_effect_tags": [
    "post_down_shock_observation",
    "high_volatility_no_direction",
    "signal_distortion"
  ],
  "dominant_risk_categories": [
    "market_disorder_risk",
    "signal_reliability_risk"
  ],
  "risk_directions": [
    "downside",
    "two_sided"
  ],
  "directional_exposure": {
    "dominant_exposed_position": "none",
    "long_position_exposure_score": 0,
    "short_position_exposure_score": 0
  },
  "evidence_items": [
    {
      "name": "最新 4h 振幅",
      "value": "7.26%",
      "interpretation": "单根波动显著高于普通 4h 波动"
    }
  ]
}
```

## 5.1 第一轮落地范围

第一轮实现只做 RiskState v2 的最小可用闭环：

```text
1. 假突破 / 假跌破信号失真事件进入 RiskState 聚合得分；
2. 新增 risk_score、market_event_score、signal_distortion_score、directional_exposure_score、chase_risk_score、direction_stability_score；
3. 新增 risk_effect_tags、primary_risk_event、risk_event_phase；
4. 单根 4h 振幅 >= 7% 通过 risk_intrabar_extreme_range 原子进入 RiskState；
5. 暂不实现跨周期观察期，不读取上一轮 DomainSignal 或数据库历史状态。
```

说明：

```text
“振幅 >= 7%”本身是最小市场事实，因此落在 AtomicSignal；
“这些市场事件、信号失真或方向暴露事实任意一个足够严重，就把 RiskState 推到对应状态”落在 DomainSignal v2 聚合层。
其中单根极端振幅不是天然等于“做空风险”或“做多风险”，它首先是市场冲击事件；是否对多头或空头不利，由 long_exposure_risk / short_exposure_risk 这类方向暴露类别表达。
```

后续第二轮再实现：

```text
极端冲击后的观察期；
高波动无方向 / 方向稳定性识别；
更长周期累计冲击风险。
```

## 5.2 第二轮正式开发范围

RiskState v2 第二轮只实现两类缺失事实：

```text
1. 极端冲击后观察期；
2. 高波动无方向 / 方向稳定性不足。
```

第二轮不新增 RiskState v2.1 或 v3，不修改四类 `state_code`，新增信息仍通过 v2 的分数、事件阶段和标签表达。

第二轮不负责：

```text
修改 MarketRegime 分类算法；
新增或删除 MarketRegime 主环境；
读取上一周期 MarketRegime；
决定主趋势延续或反转；
开发 StrategySignal 消费规则；
生成不交易、减仓、空仓等策略动作；
实现更长周期累计冲击风险。
```

第二轮开始编码前，Feature / AtomicSignal 必须先能在“当前 MarketSnapshot 所携带的历史窗口”中提供以下最小事实：

```text
最近一次极端冲击距离当前多少根已收盘 4h K；
冲击后是否出现新的极端振幅、假突破、假跌破或双向扫动；
最近固定窗口内方向切换次数；
最近固定窗口内方向一致性；
最近固定窗口内累计收益与累计振幅；
最近固定窗口内趋势效率或等价的方向稳定性事实。
```

RiskState DomainSignal 只聚合这些原子事实。若第二轮所需原子没有纳入版本包，应按依赖完整性规则阻断该 RiskState v2 定义的发布或计算，不得把证据缺失伪装成 `risk_clear`。

第二轮中的窗口长度、阈值和严重程度必须由对应 Feature / AtomicSignal 定义冻结并可追溯；不得在 DomainSignal 聚合器中重复计算 K 线或另藏一套阈值。

字段语义：

| 字段 | 含义 |
|---|---|
| `risk_score` | 综合市场风险强度，0-100，越高风险越强 |
| `signal_distortion_score` | 普通趋势、突破、跌破等信号失真程度，0-100，越高越失真 |
| `direction_stability_score` | 最近一段行情方向稳定性，0-100，越高越稳定 |
| `primary_risk_event` | 当前最主要风险事件 |
| `risk_event_phase` | 风险事件生命周期阶段 |
| `post_shock_observation_bars_remaining` | 冲击后观察期剩余 4h K 数 |
| `risk_effect_tags` | 下游可消费的风险效果标签 |
| `dominant_risk_categories` | 当前主导风险类别 |
| `risk_directions` | 风险方向，不等于交易方向 |
| `risk_direction_scores` | 上行、下行、双向风险事实各自的最高强度，0-100 |
| `evidence_items` | 人工复核证据 |

## 6. 风险事件生命周期

v2 新增风险事件生命周期概念。

允许值：

```text
none；
shock_active；
post_shock_observation；
cooling；
resolved。
```

### 6.1 shock_active

当前 4h K 线本身已经构成极端冲击。

当前市场冲击采用以下领域层“或者”关系：

```text
单根 4h 振幅 >= 7%；
或单根 4h 开盘到收盘实体跌幅 >= 4%；
或单根 4h 开盘到收盘实体涨幅 >= 4%。
```

这三类事实必须由三个独立 AtomicSignal 表达，RiskState 只负责聚合。任何一个原子成立，当前 `risk_event_phase` 都必须为 `shock_active`，不得因事件分数低于 high、实体占比不足或收盘位置不够靠近极值而回落为 `none` / `risk_clear`。

收盘位置只用于进一步区分：

```text
是否更像向下杀跌还是下探收回；
是否形成多头 / 空头方向暴露风险；
是否存在急跌追空 / 急涨追多风险。
```

它不负责否定“当根已经发生明显实体冲击”这一客观事实。

典型事实：

```text
单根实体涨跌幅极大；
open-low / open-high 极端；
整根振幅极大；
收盘靠近极端位置；
ATR 或实现波动处于高分位。
```

### 6.2 post_shock_observation

过去 N 根 4h K 线内出现过极端冲击，当前仍处于观察期。

这一阶段即使当前 K 线不再极端，也不得立即回到 `risk_clear`。

典型解释：

```text
市场刚刚经历极端冲击，普通趋势、反弹、突破、跌破信号仍可能失真。
```

### 6.3 cooling

冲击后的波动开始下降，但尚未完全恢复稳定。

典型事实：

```text
最新 K 线振幅回落；
方向切换减少；
但距离冲击事件仍较近。
```

### 6.4 resolved

冲击影响已解除。

典型事实：

```text
观察期结束；
波动率回落；
方向稳定性恢复；
未继续出现假突破、假跌破或双向扫动。
```

## 7. 风险事件类型

### 7.1 extreme_down_shock

下行极端冲击。

它表达：

```text
当前市场出现强烈向下冲击；
若存在多头方向暴露，该行情不友好；
当前位置追空也可能存在追空风险；
但它不直接等于做空信号。
```

### 7.2 extreme_up_shock

上行极端冲击。

它表达：

```text
当前市场出现强烈向上冲击；
若存在空头方向暴露，该行情不友好；
当前位置追多也可能存在追多风险；
但它不直接等于做多信号。
```

### 7.3 high_volatility_no_direction

高波动无方向。

典型事实：

```text
最近 6-8 根 4h K 线波动偏大；
涨跌方向频繁切换；
累计涨跌并不支持明确趋势；
上下影或实体冲击多次出现；
方向一致性低。
```

它表达：

```text
当前市场不适合被普通趋势逻辑强行解释。
```

这是 v2 的核心新增能力之一。

### 7.4 false_breakout_distortion

向上突破快速失败导致信号失真。

典型事实：

```text
价格突破压力后很快打回；
长上影明显；
收盘未能站稳突破区；
波动或反转幅度较大。
```

### 7.5 false_breakdown_distortion

向下跌破快速收回导致信号失真。

典型事实：

```text
价格跌破支撑后很快收回；
长下影明显；
收盘未能有效跌破；
波动或反转幅度较大。
```

### 7.6 chase_risk_after_shock

冲击后追单风险。

典型事实：

```text
刚刚发生急涨后继续追多风险升高；
刚刚发生急跌后继续追空风险升高。
```

它不否定原方向，只说明当前位置追同方向的质量变差。

### 7.7 accumulated_shock_risk

累计冲击风险。

典型事实：

```text
过去 3 天累计涨跌幅过大；
过去 1 周持续高波动；
连续多根 4h 大实体 K 线；
累计波动明显超过普通趋势推进。
```

该能力可作为 v2 后续增强点，初版可先保留接口字段。

## 8. risk_effect_tags

`risk_effect_tags` 用于给下游清楚表达“风险影响”，但不表达交易建议。

建议标签：

```text
down_shock；
up_shock；
post_down_shock_observation；
post_up_shock_observation；
high_volatility_no_direction；
direction_instability；
signal_distortion；
false_breakout_risk；
false_breakdown_risk；
long_exposure_risk；
short_exposure_risk；
long_chase_risk；
short_chase_risk；
market_disorder_risk；
shock_cooling；
risk_resolved。
```

禁止标签：

```text
allow_trade；
caution_trade；
block_trade；
reduce_position；
close_position；
open_long；
open_short；
no_trade。
```

## 9. risk_score 计算原则

`risk_score` 是市场风险强度，不是仓位建议。

建议区间：

| 分数区间 | 含义 |
|---:|---|
| 0-19 | 风险正常 |
| 20-49 | 风险升高但可分类 |
| 50-74 | 明显风险，普通分类需要打折 |
| 75-100 | 信号失真风险高 |

分数来源：

```text
当前极端冲击；
冲击后观察期；
高波动无方向；
方向稳定性低；
假突破 / 假跌破；
双向扫动；
连续冲击；
累计冲击；
风险事件尚未冷却。
```

不得把 `risk_score` 直接解释为：

```text
仓位比例；
交易概率；
做多概率；
做空概率；
订单阻断等级。
```

## 10. signal_distortion_score

`signal_distortion_score` 表示普通市场信号失真程度。

它主要回答：

```text
趋势、突破、跌破、反弹、回调这些普通分类，在当前行情下是否容易被噪音误导。
```

高分触发因素：

```text
高波动无方向；
方向频繁切换；
上下影线剧烈扫动；
假突破；
假跌破；
冲击后观察期；
连续冲击但无稳定方向。
```

MarketRegime 可以消费该字段来降低普通分类置信度。

## 11. direction_stability_score

`direction_stability_score` 表示最近一段行情方向稳定性。

高分表示：

```text
涨跌方向一致；
趋势推进连续；
回撤或反弹没有频繁打脸；
普通趋势解释相对可靠。
```

低分表示：

```text
涨跌交替频繁；
同一窗口内多空 K 线互相吞没；
累计涨跌不明显但振幅较大；
普通趋势解释容易失真。
```

它不表示看多或看空，只表示“方向是否稳定”。

## 12. state_code 判定

### 12.1 risk_clear

满足：

```text
risk_score < 20；
signal_distortion_score < 20；
无有效冲击观察期；
无假突破 / 假跌破；
无高波动无方向。
```

### 12.2 risk_elevated_classifiable

满足：

```text
至少一类风险事实达到 elevated；
风险方向或风险类别清楚；
没有严重信号失真；
不存在强度相同的上下方向风险冲突；
MarketRegime 仍可正常分类，但应保留风险上下文。
```

典型例子：

```text
单根大跌方向清晰，收盘靠近低点，没有快速收回，也没有双向扫动。
```

### 12.3 risk_high_signal_unreliable

满足任一：

```text
risk_score >= 75；
signal_distortion_score >= 75；
当前处于严重冲击后观察期；
高波动无方向达到严重级别；
假突破 / 假跌破达到 high；
双向扫动达到 high；
多类信号失真风险同时成立。
```

### 12.4 risk_unclear

只在上下方向风险事实真实冲突且没有主次时成立：

```text
上行方向分数 >= 55；
下行方向分数 >= 55；
上行方向分数 = 下行方向分数。
```

补充规则：

```text
同方向同时出现多类风险，不构成 risk_unclear；
一边 high、另一边 elevated，存在明确主次，不构成 risk_unclear；
只有 two_sided 风险而没有相反的上行 / 下行事实，不构成 risk_unclear；
上下两边同为 elevated，或上下两边同为 high，才属于无主次的方向冲突；
risk_unclear 的优先级高于 risk_high_signal_unreliable，但 risk_score 和 signal_distortion_score 仍保留真实强度。
```

例如，同一次下行实体冲击同时产生：

```text
下行市场冲击；
多头方向暴露风险；
急跌后追空风险。
```

三者都来自同一向下事件，必须聚合为 `risk_elevated_classifiable` 或 `risk_high_signal_unreliable`，不得仅因风险类别数量达到三类而输出 `risk_unclear`。

## 13. 假突破 / 假跌破聚合要求

v2 必须修复 v1 的实际实现缺口：

```text
false_breakout_risk；
false_breakdown_risk。
```

这两类风险必须进入领域聚合打分。

规则：

```text
elevated 假突破 / 假跌破 → 至少抬高 risk_score 和 signal_distortion_score；
high 假突破 / 假跌破 → 可以直接触发 risk_high_signal_unreliable；
同时出现假突破和假跌破 → 优先考虑 risk_unclear 或 risk_high_signal_unreliable。
```

不得出现：

```text
原子层识别到假突破 / 假跌破，但领域层仍输出 risk_clear。
```

## 14. 冲击后观察期要求

v2 必须支持冲击后观察期。

观察期来源：

```text
AtomicSignal 或 Feature 在当前 MarketSnapshot 历史窗口中识别最近 N 根 4h 是否出现过极端冲击；
DomainSignal 只消费原子结果，不自行读取历史 K 线。
```

初始建议：

```text
极端 4h 冲击后观察 3-6 根 4h；
若后续继续出现大幅波动、假突破、假跌破或方向频繁切换，观察期可延长；
若波动下降、方向稳定性恢复、没有新冲击，进入 cooling；
观察期结束且风险分下降后才允许 resolved。
```

观察期输出必须包含：

```text
risk_event_phase；
post_shock_observation_bars_remaining；
risk_effect_tags；
evidence_text_zh。
```

## 15. 高波动无方向识别要求

高波动无方向是 v2 的核心新增能力。

建议由 AtomicSignal 提供以下证据：

```text
recent_direction_flip_count；
recent_large_body_alternation_count；
recent_cumulative_return_pct；
recent_realized_vol_percentile；
recent_range_sum_pct；
recent_trend_efficiency_ratio。
```

DomainSignal 消费这些原子后判断：

```text
波动大；
方向一致性低；
累计方向收益不足；
上下反复或多空互相吞没明显；
普通趋势解释容易失真。
```

输出标签：

```text
high_volatility_no_direction；
direction_instability；
signal_distortion。
```

## 16. 与 Volatility 的边界

Volatility 负责描述：

```text
波动高低；
波动是否极端；
波动是否收敛；
波动是否扩张。
```

RiskState 负责描述：

```text
这种波动是否导致普通市场信号失真；
这种波动是否导致方向稳定性下降；
这种波动是否处于冲击后观察期；
这种波动是否构成市场混乱风险。
```

高波动不必然等于高风险。

只有当高波动伴随方向失真、冲击、假突破、假跌破或双向扫动时，RiskState 才应提高风险状态。

## 17. 与 MarketRegime 的关系

MarketRegime 可以消费 RiskState v2：

```text
risk_clear → 普通市场环境分类可正常进行；
risk_elevated_classifiable → 普通分类可继续，但必须保留风险标签和分数；
risk_high_signal_unreliable → 普通分类可信度显著下降，可作为高风险环境或不明确环境证据；
risk_unclear → 可作为不明确环境或低可信分类证据；
high_volatility_no_direction → 不应强行解释为趋势延续、反弹、回调或突破；
post_shock_observation → 不应把冲击后的下一根普通 K 线立即当作正常行情。
```

MarketRegime 不得用 Volatility 临时代替 RiskState。

### 17.1 与“主环境 / 当前事件”新边界的兼容性

RiskState v2 不负责改写日线级主环境。

同一周期允许同时成立：

```text
主环境：多头回调；
RiskState：下行极端冲击后的观察期。
```

也允许同时成立：

```text
主环境：空头反弹；
RiskState：高波动无方向，普通信号可靠性低。
```

两者回答的是不同问题：

```text
MarketRegime 主环境回答：当前处于哪一种可持续行情阶段；
RiskState 回答：当前冲击、混乱和信号失真程度有多高。
```

因此，RiskState 可以让后续 MarketRegime 降低置信度或承认当前证据不足，但不得直接输出“转多”“转空”“趋势延续”“趋势反转”，也不得自行覆盖 MarketRegime 主环境。

## 18. 与 StrategySignal 的未来关系（当前不开发）

领域层和 MarketRegime 完成复核后，StrategySignal 可以再单独设计如何消费 RiskState v2 的风险事实，例如：

```text
看到 long_exposure_risk 高时，降低多头信号置信度；
看到 short_chase_risk 高时，避免把急跌后的空头信号解释得过强；
看到 high_volatility_no_direction 时，降低趋势策略信号质量；
看到 false_breakout_risk 时，降低突破类策略信任度。
```

但 RiskState 自己不得输出策略动作。

上述内容只用于保留未来边界，不属于 RiskState v2 第二轮的开发和验收范围。

## 19. evidence_text_zh 要求

RiskState v2 必须输出人能看懂的中文解释。

示例：

```text
最新 4h 出现明显下行冲击，且过去 6 根 K 线方向多次反转、波动保持高位，说明市场仍处于冲击后观察期。当前普通趋势、反弹、跌破分类的可靠性下降，因此状态为高信号不可靠。该结论只描述市场冲击、信号可靠性和方向暴露事实，不等于停止交易、减仓或下单。
```

高波动无方向示例：

```text
过去 8 根 4h K 线振幅偏大，但涨跌方向频繁切换，累计方向收益不明显，说明当前市场更像高波动无方向环境。普通趋势解释容易被噪音打脸。
```

## 20. 验收要求

至少覆盖：

```text
无风险原子成立 → risk_clear；
单根 4h 下行极端冲击 → risk_elevated_classifiable 或 risk_high_signal_unreliable，payload 包含 down_shock；
单根实体跌幅达到 4%、振幅不足 7%、收盘位置为 0.385 → 仍须识别 extreme_down_shock，risk_event_phase 为 shock_active，不得 risk_clear；
单根实体涨幅达到 4%、振幅不足 7%、收盘位置未靠近最高点 → 仍须识别 extreme_up_shock，risk_event_phase 为 shock_active，不得 risk_clear；
收盘位置条件只影响方向暴露和追单风险原子，不得否定当前市场冲击；
极端冲击后第 1-3 根 4h → post_shock_observation，不得立即 risk_clear；
冲击后波动下降、方向稳定 → cooling / resolved；
假突破 elevated → risk_score 上升，不得 risk_clear；
假突破 high → risk_high_signal_unreliable；
假跌破 elevated → risk_score 上升，不得 risk_clear；
假跌破 high → risk_high_signal_unreliable；
高波动无方向 → risk_high_signal_unreliable 或 risk_unclear，payload 包含 high_volatility_no_direction；
方向稳定但单边强冲击 → risk_elevated_classifiable，而不是默认 risk_unclear；
双向扫动 high → risk_high_signal_unreliable；
同方向三类风险同时成立 → 不得 risk_unclear；
上下方向风险同为 elevated → risk_unclear；
上下方向风险同为 high → risk_unclear，并保留 100 分风险强度；
一边 high、另一边 elevated → 存在明确主次，不得 risk_unclear；
coverage_ratio 低于阈值 → failed，不得伪装 risk_clear；
risk_score、signal_distortion_score、direction_stability_score 可复算；
evidence_text_zh 不得输出交易建议。
```

## 21. 禁止项

禁止：

```text
读取账户或持仓；
读取订单或成交；
读取 PriceSnapshot；
请求 Binance；
调用大模型；
输出交易动作；
输出目标仓位；
输出 allow / caution / block 这类交易建议；
把 risk_score 当作仓位比例；
把 risk_high_signal_unreliable 解释为必须不交易；
把 high_volatility_no_direction 解释为一定不开仓；
把 post_shock_observation 解释为一定平仓；
把 long_exposure_risk 解释为系统当前一定有多仓；
把 short_exposure_risk 解释为系统当前一定有空仓；
用 volatility 高波动直接替代 risk_state；
把单根大跌直接等同于做空信号；
把单根大涨直接等同于做多信号。
```

## 22. 后续实现切片

RiskState v2 按以下切片推进：

### 22.1 聚合器修复切片

状态：已完成第一轮实现并完成基础回测复核。

已实现：

```text
false_breakout_risk；
false_breakdown_risk；
risk_score；
signal_distortion_score；
direction_stability_score；
risk_effect_tags。
```

### 22.2 冲击生命周期切片

状态：当根冲击与生命周期已由回测 107 / 108 验证；同方向多类风险误判为 `risk_unclear` 的聚合修复已完成自动化回归，待复跑 107 对应窗口验证落库结果。

本切片新增：

```text
extreme_down_shock；
extreme_up_shock；
post_shock_observation；
cooling；
resolved。
```

通过标准：当根振幅达到 7% 或实体涨跌幅绝对值达到 4%，任一成立都必须进入 `shock_active`；极端冲击后的下一根普通 K 线不得立即回到 `risk_clear`；观察期、冷却期和解除状态必须由当前历史窗口中的原子事实复算得到，不读取上一轮 DomainSignal。

### 22.3 高波动无方向切片

状态：代码已实现，待新版本包回测验证。

本切片新增：

```text
high_volatility_no_direction；
direction_instability；
recent_direction_flip_count；
recent_trend_efficiency_ratio；
方向随机但波动大的识别。
```

通过标准：高波动且方向频繁切换的样本必须提高 `signal_distortion_score` 并降低 `direction_stability_score`；高波动但方向稳定的单边行情不得被误判为无方向混乱。

## 23. 最终定位

RiskState v2 的最终定位是：

```text
识别市场风险事实、信号失真程度和市场是否处于普通解释失效状态，
帮助 MarketRegime 不再强行解释冲击后、混乱、高波动无方向行情，
帮助 StrategySignal 理解信号质量，
但不替代策略、不替代目标仓位、不替代账户风控、不触发交易动作。
```
