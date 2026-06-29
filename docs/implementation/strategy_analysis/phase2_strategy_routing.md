# StrategyRouting 实现记录

## 实现范围

本阶段实现固定规则路由框架：

```text
MarketRegimeSnapshot
→ StrategyRoutePolicy
→ StrategyRouteRule 集合
→ StrategyDefinition 候选集合
→ StrategyRouteDecision
```

StrategyRouting 不注册路由 calculator。条件结构、AND 匹配、priority 数字越小越优先、同优先级冲突阻断、无匹配阻断以及显式 `no_strategy` 均由稳定业务 service 实现。

## 已实现对象

```text
StrategyDefinition；
StrategyRoutePolicy；
StrategyRouteRule；
StrategyRouteDecision；
策略定义、Rule、RuleSet 和 Policy 指纹；
版本包策略、Policy 和 Rule 真实对象校验；
route_for_strategy_signal 正式 service；
route_strategy management command；
seed_strategy_routing 默认路由配置初始化命令。
```

## 条件匹配

当前 `condition_schema_version = 1.0` 对应需求文件已经固定的条件语义：

```text
regime_codes；
minimum_regime_confidence；
minimum_classification_margin；
regime_score_thresholds。
```

同一 Rule 内全部已配置条件使用 AND。Rule 有效窗口使用 MarketRegimeSnapshot 的分析收盘边界，不读取服务器当前时间。

Decision 的匹配证据同时冻结实际参与匹配 Rule 的状态、启用值、指纹、优先级、动作和有效窗口，便于历史审计；不会因为 Rule 后续状态变化而改写历史 Decision。

## 策略选择与 fallback

唯一最高优先匹配 Rule 才能产生结果：

```text
select_strategy → 校验并选择版本包内 StrategyDefinition；
no_strategy     → 正常 created，但不允许进入 StrategySignal；
无匹配          → blocked；
同优先级冲突    → blocked。
```

fallback 默认关闭。只有 Rule 已明确选择的原策略当前不可执行、Policy 明确配置 `explicit` fallback，且 fallback 位于相同版本包策略切片并可执行时才使用。fallback 不处理无匹配、规则冲突或冻结配置损坏。

StrategyRouting 只解析 StrategySignal calculator 的精确注册身份，不调用 calculator。

## 默认正式映射登记

当前已登记 P0 默认 StrategyRoutePolicy / StrategyRouteRule 模板，覆盖 context_structure_regime_v1 的 13 种市场环境。

`seed_strategy_routing` 只写入 Policy / Rule，不创建 StrategyDefinition。命令执行前会校验四个被引用的 StrategyDefinition 已经 active + enabled：

```text
long_trend_following / v1；
long_pullback_support / v1；
short_trend_following / v1；
short_rebound_pressure / v1。
```

如果上述 StrategyDefinition 尚未可用，命令 fail-closed，不创建半成品 Policy / Rule。

正式版本包缺少完整策略、Policy 或 Rule 时，Service fail-closed，不生成可被 StrategySignal 消费的 Decision。

## 幂等、dry-run 与失败

```text
business_request_key 命中时核对 MarketRegimeSnapshot、版本包和 Policy 身份；
相同 Snapshot、schema 和 Policy 身份只生成一个正式 Decision；
dry-run 执行相同匹配和策略注册校验，但不写 Decision 或 AlertEvent；
blocked 不创建 Decision；
规则数据异常形成 failed Decision 和 AlertEvent；
明确数据库拒绝为 failed，无法确认写入结果才是 unknown。
```

## 边界

本阶段不读取 DomainSignalValue、AtomicSignalValue、FeatureValue、账户、持仓、价格、订单或策略表现，不访问 Redis、Binance、DeepSeek，不发送 Hermes，不执行 StrategySignal，不生成目标仓位，不涉及交易执行或真实交易。

## 测试覆盖

```text
正常选择注册策略；
显式 no_strategy；
不同优先级选择；
同优先级冲突；
无匹配阻断；
目标不可用时 explicit fallback；
无 fallback 时阻断；
fallback 不处理无匹配；
冻结 Rule 停用阻断；
未知条件字段阻断；
业务幂等与幂等冲突；
dry-run 不写库且不复用正式 Decision；
评分缺失形成 failed Decision；
有效窗口使用业务时间。
```
