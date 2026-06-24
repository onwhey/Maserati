# 阶段 2：DomainSignal 实现记录

## 本阶段实现内容

本阶段实现从 AtomicSignalSet 到 DomainSignalSet 的正式业务链路：

```text
AtomicSignalSet / AtomicSignalValue
→ DomainSignalService
→ DomainSignal calculator
→ DomainSignalSet / DomainSignalValue
```

## 代码边界

DomainSignalService 负责：

```text
校验 AtomicSignalSet 是否可被领域层消费；
校验 StrategyAnalysisRelease 的领域切片；
校验 DomainSignalDefinition 的身份、hash、状态和 calculator；
校验每个 AtomicSignalDefinition 在正式领域中只归属一次；
校验 trend / momentum / volatility 三个正式领域存在；
调用纯 calculator；
保存 DomainSignalSet / DomainSignalValue；
在阻断、失败、未知时写必要 AlertEvent；
支持 dry-run。
```

DomainSignalService 不负责：

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

当前只提供 `single_atomic_passthrough 1.0.0`，用于流程验证阶段。

该算法只适合一个领域消费一个已验证原子信号的场景。正式策略效果仍需后续通过更多特征、原子信号和领域算法补齐。

## 默认 seed 行为

`seed_domain_signal_definitions` 只根据当前已存在的默认原子信号创建 `trend` 领域定义。

它不会为了凑完整 release 自动创建 momentum / volatility，也不会创建不存在的原子信号。

完整正式 StrategyAnalysisRelease 仍必须包含真实的 trend、momentum、volatility 三个领域定义。

## dry-run 行为

dry-run 会完整执行输入校验和 calculator 计算，但不会写入：

```text
DomainSignalSet；
DomainSignalValue；
AlertEvent。
```

dry-run 结果会明确返回：

```text
persisted = false
computed_count
valid_count
invalid_count
required_failed_count
allows_market_regime = false
```

## 验收方式

```text
python manage.py makemigrations --check --dry-run
pytest -q
```

通过标准：

```text
DomainSignal 相关模型迁移完整；
DomainSignal calculator 单测通过；
DomainSignal service 创建、阻断、失败、幂等、dry-run 用例通过；
全量测试通过。
```
