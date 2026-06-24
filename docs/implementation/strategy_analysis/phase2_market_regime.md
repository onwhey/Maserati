# MarketRegime 实现记录

## 本阶段实现范围

本阶段实现 MarketRegime 正式业务框架：

```text
DomainSignalSet
→ MarketRegimeDefinition
→ MarketRegime calculator
→ MarketRegimeSnapshot
```

MarketRegimeService 只接收明确的 `domain_signal_set_id`，只消费同一份 DomainSignalSet 下、且被本轮 MarketRegimeDefinition 声明允许使用的 DomainSignalValue。

## 已实现内容

```text
MarketRegimeDefinition 模型；
MarketRegimeSnapshot 模型；
MarketRegimeDefinition 稳定 definition_hash；
MarketRegimeDefinition 与领域依赖 membership hash；
classify_for_strategy_routing 正式 service；
classify_market_regime management command；
seed_market_regime_definitions 安全占位命令；
StrategyAnalysisRelease 对 MarketRegimeDefinition 的真实对象校验；
MarketRegime service 测试。
```

## 当前明确未实现内容

当前没有实现任何正式 MarketRegime calculator。

原因是当前需求文件明确说明：

```text
尚未指定正式 MarketRegime 算法；
尚未指定正式 regime_code 集合；
不得凭空创建可进入正式版本包的默认 MarketRegimeDefinition。
```

因此，正式版本包如果没有选择合法、可解析、已批准的 MarketRegimeDefinition，MarketRegime 正式入口必须 fail-closed，也就是返回 blocked，不生成可供 StrategyRouting 消费的 MarketRegimeSnapshot。

## 业务边界

MarketRegime 不负责：

```text
读取 AtomicSignalValue；
读取 FeatureValue；
读取 Kline；
重新计算 DomainSignal；
选择 StrategyDefinition；
生成 StrategyRouteDecision；
生成 StrategySignal；
生成 DecisionSnapshot；
读取账户、持仓或价格事实；
调用 Binance；
调用 DeepSeek；
发送 Hermes；
执行交易。
```

## 失败与阻断

前置条件不满足时：

```text
不调用 calculator；
不创建 MarketRegimeSnapshot；
写 market_regime_blocked AlertEvent。
```

calculator 已被调用但输出失败或输出合同非法时：

```text
创建 failed MarketRegimeSnapshot；
不允许 StrategyRouting 消费；
写 market_regime_failed AlertEvent。
```

dry-run 时：

```text
调用相同 service 和 calculator 合同；
不写 MarketRegimeSnapshot；
不写正式 AlertEvent；
返回内存结果摘要。
```

正式结果与 dry-run 严格隔离：dry-run 即使遇到相同业务幂等键或相同输入身份，也会执行相同 calculator 校验并返回 `persisted = false`，不会返回正式 Snapshot，也不会放行 StrategyRouting。不支持 dry-run 的 calculator 会在计算前阻断。

业务幂等键命中历史 Snapshot 时，Service 会同时核对 DomainSignalSet、StrategyAnalysisRelease 和 Definition 身份；同一个幂等键指向不同输入时阻断，不返回其他周期的结果。并发唯一键冲突后执行相同身份核验。

calculator 的未预期异常统一收口为 failed Snapshot 和 AlertEvent；结构化证据为空时视为输出合同失败。Snapshot 证据由使用到的领域事实、分类结果和 calculator 原始证据三部分组成。

数据库已明确拒绝的数据写入归为 failed；只有写入结果确实无法查证时才归为 unknown。

## 测试覆盖

当前测试覆盖：

```text
正常生成 MarketRegimeSnapshot；
business_request_key 幂等；
版本包未选择 MarketRegimeDefinition 时 blocked；
required DomainSignalValue 缺失时 blocked；
calculator 精确版本未注册时 blocked；
dry-run 不写库且不写 AlertEvent；
calculator 输出非法时写 failed Snapshot 和 AlertEvent。
业务幂等键复用但输入不一致时阻断；
dry-run 不复用正式 Snapshot；
不支持 dry-run 的 calculator 在计算前阻断；
calculator 未预期异常收口为 failed；
calculator 空结构化证据被拒绝；
重复领域、非正式领域和重复环境代码被拒绝；
明确数据库数据错误归为 failed。
```
