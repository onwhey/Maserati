# StrategySignal 实现记录

## 实现范围

本阶段实现 StrategySignal 稳定业务框架：

```text
StrategyRouteDecision（selected）
→ 冻结 StrategyDefinition
→ 沿 MarketRegimeSnapshot 找到同一 DomainSignalSet
→ 筛选 allowed DomainSignalValue 并校验 required 输入
→ 精确解析 StrategySignal calculator
→ 标准化并持久化 StrategySignal
```

当前需求没有指定任何正式策略算法，因此没有新增正式 calculator、正式 StrategyDefinition 或默认策略模板。测试仅使用不进入生产 Registry 的 fake calculator。

## 已实现对象与入口

```text
StrategySignal；
StrategySignalDirection；
generate_strategy_signal 正式 service；
generate_strategy_signal management command；
seed_strategy_definitions 安全零变更命令；
StrategySignal calculator 权重能力 metadata；
版本包批准阶段的 schema 与权重合同校验。
```

## 输入边界

StrategyRouteDecision 是唯一正式入口。Service 只消费：

```text
created；
selected；
is_usable = true；
allows_strategy_signal = true；
绑定唯一 StrategyDefinition。
```

领域输入只来自 Decision 业务链上的同一 DomainSignalSet。Service 只把 StrategyDefinition 允许的有效 DomainSignalValue 交给 calculator，并在调用前确认 required 领域齐全、领域值指纹属于同一版本包。

CalculatorInput 不包含 StrategyRouteDecision DTO 或 MarketRegimeSnapshot。MarketRegimeSnapshot 只作为 StrategySignal 的业务外键保留，不能再次改变策略方向、强度、置信评分或权重。

## 输出合同

成功 calculator 必须输出统一业务语义：

```text
direction = bullish / bearish / neutral；
strength 与 confidence 位于 0 到 1；
confidence_semantics 非空；
prediction_horizon 与冻结 Definition 一致；
实际使用领域引用完整且不重复；
实际权重与冻结 Definition 一致；
聚合摘要、冲突摘要和中文证据完整。
```

正常 neutral 是 created 且允许进入 StrategySignalQuality。calculator failed、异常或非法输出形成 failed StrategySignal，不伪装为 neutral，也不允许下游消费。

## 权重边界

CalculatorMetadata 增加只读 `uses_input_weights` 合同。StrategyAnalysisRelease 验证、StrategyRouting 可执行性检查和 StrategySignal 执行前检查都会确认它与 StrategyDefinition 一致。

未启用领域权重时，calculator 返回任何隐藏权重都会失败。启用权重时，实际使用领域必须逐项记录与 Definition 一致的权重；Service 不为缺失权重猜测默认值。

## 幂等、事务和 dry-run

```text
business_request_key 用于请求幂等并校验请求身份；
RouteDecision、schema、Definition 指纹和 DomainSignalSet 形成稳定 StrategySignal key；
数据库唯一约束处理并发重复；
created 或 failed StrategySignal 在事务中完整落库；
failed 与持久化异常写 AlertEvent；
写入结果无法确认返回 unknown，不重新执行 calculator；
dry-run 执行相同校验和 calculator，但不写 StrategySignal 或 AlertEvent，也不允许下游消费。
```

## 明确边界

本阶段不重新路由，不重新计算 MarketRegime 或 DomainSignal，不读取 AtomicSignalValue、FeatureValue、Kline、账户、持仓、PriceSnapshot、订单或风控事实；不访问 Redis、Binance、DeepSeek，不发送 Hermes，不调用大模型，不生成 DecisionSnapshot、目标仓位或订单，不涉及交易执行和真实交易。

## 测试覆盖

```text
正常 bullish 标准输出和业务外键；
正常 neutral；
no_strategy 阻断且不调用 calculator；
只传 allowed 领域；
required 领域缺失阻断；
MarketRegime 不进入 calculator；
Definition 停用阻断；
精确 calculator 缺失阻断；
calculator failed；
非法方向和隐藏权重失败；
未预期 calculator 异常；
请求幂等与幂等冲突；
dry-run 不写库且不允许下游消费。
```
