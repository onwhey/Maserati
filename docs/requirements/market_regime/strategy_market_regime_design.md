# 策略市场环境设计说明

## 1. 文档定位

本文档用于说明在补充 `market_context`、`structure`、`risk_state` 等策略领域后，MarketRegime 应该如何理解这些领域事实，并把它们组合成可供 StrategyRouting 使用的市场环境。

本文档只做设计规划，不定义正式算法公式，不批准任何正式 `regime_code`，不替代 `market_regime.md`。

任何市场环境分类进入正式主链路前，仍必须完成：

```text
独立算法 requirements；
implementation 实现记录；
测试和回测证据；
StrategyAnalysisRelease 选择、验证、人工批准和启用。
```

## 2. 核心结论

MarketRegime 的职责不是重新分析行情，而是把已经生成的领域事实组合起来，回答：

```text
当前整体市场更像哪一种环境？
这种环境是否足够明确？
这个判断由哪些领域事实支撑？
```

MarketRegime 不得：

```text
重新读取 K 线；
重新计算特征；
重新计算原子信号；
重新聚合领域信号；
选择策略；
执行策略；
输出目标仓位；
输出订单动作。
```

支撑压力、区间结构、大级别背景和异常风险，都不应成为独立业务模块。它们应该通过：

```text
FeatureLayer
→ AtomicSignal
→ DomainSignal
→ MarketRegime
```

逐层进入市场环境判断。

## 3. MarketRegime 与 StrategySignal 的边界

MarketRegime 负责判断“市场环境是什么”。

StrategySignal 负责判断“在这个环境下，已选定策略如何行动”。

例如：

```text
MarketRegime 可以判断：
大级别偏多，高位宽幅区间，当前靠近支撑，风险状态正常。

StrategyRouting 可以据此选择：
long_bullish_pullback_range。

StrategySignal 才能判断：
靠近支撑是否偏多；
靠近压力是否减仓；
跌破支撑是否退出；
突破压力是否切换为趋势突破打法。
```

因此，MarketRegime 中不得出现：

```text
买入；
卖出；
加仓；
减仓；
清仓；
目标仓位；
止盈止损；
订单方向。
```

## 4. 输入领域规划

为支持趋势突破和大级别偏多区间策略，MarketRegime 后续规划可消费以下领域事实：

```text
market_context  = 大级别市场背景；
trend           = 趋势方向与趋势强度；
momentum        = 推动力与衰竭状态；
volatility      = 波动状态；
structure       = 支撑压力、区间结构与价格位置；
risk_state      = 市场异常风险状态。
```

正式算法不一定必须使用全部领域，但必须在算法 requirements 中提前声明：

```text
必须使用哪些领域；
允许缺失哪些领域；
缺失时是 blocked、降级分类，还是归入不明确环境；
每个领域在分类中承担什么业务含义。
```

不得在运行时临时决定“这次看哪些领域”。

高位、低位、趋势中继、宽幅区间等市场环境语义，不由单个 `structure` 领域直接输出。

MarketRegime 必须把多个领域组合后再形成这些环境判断，例如：

```text
market_context 提供大级别高位或低位背景；
trend 提供当前趋势是否仍有效；
volatility 提供宽幅震荡或异常波动状态；
structure 提供支撑压力区间与当前价格位置；
risk_state 提供异常行情对信号可靠性的风险。
```

因此：

```text
structure = 区间有效，当前靠近支撑；
market_context = 大级别偏多，当前处于长期高位区域；
volatility = 宽幅震荡；
trend = 推进减弱但结构未确认破坏；
risk_state = 无异常风险。
```

MarketRegime 才可以形成：

```text
大级别偏多高位宽幅区间，当前靠近支撑。
```

## 5. 候选市场环境类型

以下类型只是设计候选，不是正式枚举。

MarketRegime 不应只把市场分成“上涨”和“下跌”。更重要的是识别：

```text
大级别背景；
中级别阶段；
结构位置；
动量状态；
风险状态。
```

### 5.1 大级别偏多趋势延续

业务含义：

```text
大级别背景偏多；
中短期趋势仍在推进；
动量没有明显衰竭；
结构没有破坏；
波动没有异常失控。
```

这类环境通常服务于多头趋势延续或向上突破策略。

MarketRegime 只表达环境，不表达“应该做多”。

### 5.2 大级别偏多中级别回调

业务含义：

```text
大级别背景仍偏多；
中级别出现下跌或回调；
回调尚未确认破坏大级别上涨结构；
价格可能接近结构支撑；
风险状态没有明显恶化。
```

这类环境用于区分：

```text
牛市中的正常回调；
趋势已经失效后的下跌。
```

具体是否买入、等待或降低仓位，由后续策略判断。

### 5.3 大级别偏多高位宽幅区间

业务含义：

```text
大级别背景偏多；
此前有明显上涨；
当前较长时间处于高位宽幅震荡；
支撑压力结构相对清晰；
趋势推进暂时减弱，但大级别结构没有完全破坏。
```

这是用户重点提出的场景：

```text
上涨后长期震荡；
趋势没有明显破坏；
但继续用单纯趋势策略可能收益效率较低。
```

这类环境本身不是交易动作，它只是告诉 StrategyRouting：

```text
当前可能更适合多头回调 / 区间结构打法，而不是盲目追趋势。
```

### 5.4 大级别偏多区间位置

业务含义：

```text
大级别背景偏多；
区间结构有效；
当前价格可能靠近支撑、靠近压力，或位于区间中部；
支撑或压力尚未被有效突破 / 跌破；
风险状态可接受。
```

MarketRegime 可以表达“靠近支撑”“靠近压力”“区间中部”这些位置环境。

是否支撑做多、压力减仓或维持目标仓位，由被选中的 StrategySignal 决定。

### 5.5 大级别偏空趋势延续

业务含义：

```text
大级别背景偏空；
中短期趋势仍向下推进；
下跌动量没有明显衰竭；
反弹没有改变下跌结构；
波动没有异常失控。
```

这类环境通常服务于空头趋势延续或向下跌破策略。

MarketRegime 只表达环境，不表达“应该做空”。

### 5.6 大级别偏空中级别反弹

业务含义：

```text
大级别背景仍偏空；
中级别出现持续反弹；
反弹尚未确认改变大级别下跌结构；
价格可能接近结构压力；
风险状态没有明显恶化。
```

这类环境用于区分：

```text
熊市中的普通反弹；
大级别趋势已经反转后的上涨。
```

具体是否观望、停止追空、或等待反弹压制策略，由后续策略判断。

### 5.7 大级别偏空反弹靠近压力

业务含义：

```text
大级别背景偏空；
中级别反弹接近压力区域；
压力尚未被有效突破；
反弹动量可能减弱；
追涨风险或反弹失败风险上升。
```

MarketRegime 不输出开空。

是否等待、偏空、或放弃空头打法，由 StrategySignal 决定。

### 5.8 大级别偏空反弹失败

业务含义：

```text
大级别背景偏空；
中级别反弹未能突破压力；
反弹后重新转弱；
下跌结构仍然有效；
风险状态可接受。
```

这类环境可为反弹压制策略或空头趋势策略提供上下文。

MarketRegime 不生成订单动作。

### 5.9 大级别偏空低位宽幅区间

业务含义：

```text
大级别背景偏空；
此前有明显下跌；
当前进入低位宽幅震荡；
支撑压力结构相对清晰；
趋势方向暂时不明确。
```

这类环境不应简单等同于“可以做多”。

它可能更适合：

```text
观望；
等待方向；
等待下跌延续；
等待大级别反转证据。
```

### 5.10 向上突破区间

业务含义：

```text
原有压力区域被有效突破；
趋势或动量有配合；
突破不是单纯噪音；
波动没有异常失控。
```

这类环境可为多头趋势突破策略提供上下文。

MarketRegime 不判断开仓，只判断“区间向上突破环境”。

### 5.11 向下跌破区间

业务含义：

```text
关键支撑区域被有效跌破；
原有区间或趋势结构被破坏；
下跌动量可能配合；
风险状态上升。
```

这类环境可为空头趋势跌破策略或风险规避策略提供上下文。

MarketRegime 不判断清仓、开空或下单。

### 5.12 异常高波动或不明确环境

业务含义：

```text
波动异常；
领域事实互相冲突；
趋势、结构、动量不能形成明确解释；
假突破、插针或连续大波动导致信号可靠性下降。
```

这类环境不是系统错误。

它应该被视为一种合法市场环境，并由 StrategyRouting 决定是否进入 `no_strategy`。

## 6. 第一批策略研究优先级

第一批不建议一次性追求所有精细环境都可实盘使用。

候选环境应优先服务四类策略研究：

```text
long_trend_following_breakout；
long_bullish_pullback_range；
short_trend_following_breakdown；
short_bearish_rebound_rejection。
```

对应最小候选环境可以先收敛为：

```text
大级别偏多趋势延续；
大级别偏多中级别回调；
大级别偏多高位宽幅区间；
大级别偏多区间靠近支撑 / 压力 / 中部；
大级别偏空趋势延续；
大级别偏空中级别反弹；
大级别偏空反弹靠近压力；
大级别偏空反弹失败；
向上突破区间；
向下跌破区间；
异常高波动或不明确环境。
```

这样既能覆盖：

```text
上涨趋势继续；
上涨后长时间震荡；
牛市回调；
熊市反弹；
下跌趋势继续；
反弹到压力后的空头机会；
突破切换；
跌破切换；
高风险观望。
```

又不会把每一种“大背景 + 短期走势”的排列组合都拆成独立策略。

## 7. 市场环境到策略路由的关系

MarketRegime 输出市场环境后，StrategyRouting 才能根据路由规则选择策略。

示例：

```text
大级别偏多趋势延续 + 向上突破
→ 可路由到 long_trend_following_breakout。

大级别偏多中级别回调 + 靠近支撑
→ 可路由到 long_bullish_pullback_range。

大级别偏多高位宽幅区间 + 靠近支撑
→ 可路由到 long_bullish_pullback_range。

大级别偏多区间中部
→ 可路由到 no_strategy。

大级别偏空趋势延续 + 向下跌破
→ 可路由到 short_trend_following_breakdown。

大级别偏空中级别反弹 + 靠近压力
→ 可路由到 short_bearish_rebound_rejection。

大级别偏空反弹失败
→ 可路由到 short_bearish_rebound_rejection 或 short_trend_following_breakdown。

大级别偏空反弹中部
→ 可路由到 no_strategy。

异常高波动或不明确环境
→ 可路由到 no_strategy。
```

以上只是业务映射方向，不是正式路由配置。

正式路由必须由 `strategy_routing.md` 定义的 `StrategyRoutePolicy` 和 `StrategyRouteRule` 冻结。

## 8. 需要避免的错误

### 8.1 只看短窗口导致误判

如果只看最近 20 天均线或短窗口震荡，系统可能只能识别“震荡”，却看不出这是大级别上涨后的高位区间。

因此，MarketRegime 的正式算法必须允许利用 `market_context` 领域提供的大级别背景事实。

### 8.2 把区间环境误当作趋势失败

上涨后的长时间横盘，不一定意味着趋势失败。

正式算法需要区分：

```text
大级别偏多高位区间；
趋势结构破坏；
大级别偏空下跌。
```

这三者不能混成一个“震荡”。

### 8.3 把熊市反弹误当作牛市上涨

大级别下跌中的一两个月反弹，不一定意味着大级别已经反转。

正式算法需要区分：

```text
大级别偏空中级别反弹；
大级别偏空反弹靠近压力；
大级别偏空反弹失败；
大级别趋势反转后的上涨。
```

这几者不能只因为短期价格上涨就统一归为“上涨趋势”。

### 8.4 在 MarketRegime 中提前做交易动作

MarketRegime 可以识别：

```text
靠近支撑；
靠近压力；
跌破支撑；
向上突破。
```

但不得输出：

```text
支撑买入；
压力减仓；
跌破清仓；
突破加仓。
```

这些都属于 StrategySignal。

### 8.5 使用未来数据或当前未收盘 K 线

MarketRegime 只能消费已经由上游冻结的领域事实。

如果某个领域事实涉及突破、跌破或区间边界，底层特征与原子信号必须明确：

```text
是否排除当前判断 K 线；
是否只使用已收盘 K 线；
是否存在未来函数风险。
```

MarketRegime 不得临时修正这些底层问题。

## 9. 正式算法文件建议

如果确认以上设计，后续可新增正式算法需求文件：

```text
docs/requirements/market_regime/context_structure_regime_v1.md
```

该文件应明确：

```text
正式 regime_code 枚举；
输入领域清单；
每个领域必需或可选；
分类流程；
分类分数；
分类置信度；
边界条件；
不明确环境处理方式；
回测验证要求；
允许进入 StrategyAnalysisRelease 的条件。
```

正式算法的实现记录再进入：

```text
docs/implementation/market_regime/context_structure_regime_v1.md
```

implementation 文档只记录实际代码实现和验证结果，不替代 requirements。

## 10. 明确禁止

禁止：

```text
新增独立 MarketStructureService；
新增独立 SupportResistanceModule；
让 MarketRegime 读取 FeatureValue；
让 MarketRegime 读取 AtomicSignalValue；
让 MarketRegime 重新计算支撑压力；
让 MarketRegime 重新判断趋势；
让 MarketRegime 选择策略；
让 MarketRegime 输出交易动作；
让 MarketRegime 输出目标仓位；
让 MarketRegime 访问账户、价格快照或 Binance；
让 MarketRegime 调用大模型；
把示例环境名称直接当作正式 regime_code；
绕过 StrategyAnalysisRelease 启用新市场环境算法。
```

## 11. 最终定位

MarketRegime 的最终定位是：

```text
基于同一轮 DomainSignalSet 中已经批准、已经落库的领域事实，
通过明确版本的市场环境算法，
形成一份不可变的整体市场环境快照，
为 StrategyRouting 提供上下文，
但不替代策略选择、策略判断或交易决策。
```
