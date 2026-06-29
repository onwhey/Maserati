# 阶段 2：DomainSignal 实现记录

## 本阶段实现内容

本阶段实现从 `AtomicSignalSet` 到 `DomainSignalSet` 的正式业务链路：

```text
AtomicSignalSet / AtomicSignalValue
→ DomainSignal service
→ DomainSignal calculator
→ DomainSignalSet / DomainSignalValue
```

当前正式领域集合为：

```text
market_context
trend
momentum
volatility
structure
risk_state
```

六个领域必须在同一份 StrategyAnalysisRelease 的领域切片中各选择一个 DomainSignalDefinition，且同一份 release 内每个 AtomicSignalDefinition 必须且只能归属于一个领域。

## 代码边界

DomainSignal service 负责：

```text
校验 AtomicSignalSet 是否可被领域层消费；
校验 StrategyAnalysisRelease 的领域切片；
校验 DomainSignalDefinition 的身份、hash、状态、enabled 和 calculator；
校验每个 AtomicSignalDefinition 在正式领域中只归属一次；
调用纯 calculator；
保存 DomainSignalSet / DomainSignalValue；
在阻断、失败、未知时写必要 AlertEvent；
支持 dry-run。
```

DomainSignal service 不负责：

```text
读取 FeatureValue；
读取 Kline；
重新计算 AtomicSignal；
识别 MarketRegime；
选择 StrategyDefinition；
生成 StrategySignal；
生成目标仓位；
生成订单；
访问 Binance；
访问 DeepSeek；
发送 Hermes；
交易执行或真实交易。
```

## 当前默认算法

当前新增 `grouped_atomic_aggregation 1.0.0`，用于六个正式领域的第一版聚合。

该 calculator 的共同规则：

```text
只读取当前 DomainSignalDefinition.allowed_atomic_signal_codes 对应的有效 AtomicSignalValue；
只把条件成立的原子信号计入分组计数；
coverage_ratio = 有效原子信号数量 / 当前领域选中的原子信号数量；
不读取 FeatureValue；
不读取账户、价格快照或订单；
不生成交易动作。
```

领域差异：

```text
market_context：聚合长期背景偏多 / 偏空证据，并保留高位、低位、回撤、修复状态标签；
trend：以 1d 为主趋势，4h 只作为辅助状态；
momentum：以 1d 推动力为主，4h 只作为辅助状态，输出增强、衰竭或震荡标签；
volatility：输出非方向性波动状态，例如低波动、高波动、极高波动、混合；
structure：输出 1d 大结构与 4h 小结构组合事实，4h 不单独推翻 1d；
risk_state：输出非方向性市场风险状态，不等同于停止交易或仓位调整。
```

保留 `single_atomic_passthrough 1.0.0` 仅用于兼容早期测试和流程验证，不作为当前六领域默认模板。

## 默认 seed 行为

`seed_domain_signal_definitions` 会根据 `apps.strategy_analysis.default_domain_definitions.DEFAULT_DOMAIN_SIGNAL_DEFINITIONS` 幂等写入六个默认领域定义。

该命令要求对应 AtomicSignalDefinition 已经存在且为 active + enabled。

典型执行顺序：

```text
python manage.py seed_feature_definitions
python manage.py seed_atomic_signal_definitions
python manage.py seed_domain_signal_definitions
```

seed 命令不会自动创建 StrategyAnalysisRelease，也不会自动批准或启用版本包。

## required 与 coverage

默认领域模板采用 coverage 机制，不把全部原子信号设置为 required。

含义是：

```text
少量原子信号无效时，不立刻硬失败；
只要有效原子证据覆盖率达到领域定义阈值，就允许 calculator 聚合；
coverage 不足时领域失败。
```

service 仍保留 required 原子信号能力。后续如果某个领域算法确实需要某个原子必须有效，可以在该 DomainSignalDefinition 的 required_atomic_signal_codes 中明确声明。

## dry-run 行为

dry-run 会完整执行输入校验和 calculator 计算，但不会写入：

```text
DomainSignalSet；
DomainSignalValue；
AlertEvent。
```

dry-run 结果会返回：

```text
persisted = false
computed_count
valid_count
invalid_count
required_failed_count
```

## 验收方式

```text
python -m pytest tests/strategy_calculator/test_grouped_atomic_aggregation.py tests/strategy_analysis/test_domain_signal.py
python manage.py check
python manage.py makemigrations --check --dry-run
```

通过标准：

```text
六个正式领域可以被登记；
DomainSignal service 可以从 AtomicSignalSet 生成六个 DomainSignalValue；
领域切片缺失、原子归属重复、coverage 不一致等错误会被阻断或失败；
dry-run 不写业务对象或 AlertEvent；
不会访问 Binance / DeepSeek / Redis；
不会产生订单、目标仓位或真实交易动作。
```
