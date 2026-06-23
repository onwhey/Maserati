# StrategyAnalysis 阶段 2 AtomicSignal 实现记录

## 对应需求

- `docs/requirements/atomic_signals.md`
- `docs/requirements/strategy_analysis_release.md`
- `docs/plans/strategy_analysis_implementation_plan.md`

## 实现范围

本切片实现：

```text
AtomicSignalDefinition
AtomicSignalSet
AtomicSignalValue
AtomicSignalService
feature_compare 1.0.0 calculator
默认原子信号定义幂等初始化命令
人工构建命令
FeatureSet 稳定键与 FeatureValue 有效性衔接字段
```

AtomicSignalService 只消费明确 FeatureSet，不读取 Kline，不调用 FeatureLayer，不访问 Binance、Redis 或其他外部服务。

正式计算只使用本轮冻结版本包的 AtomicSignalDefinition 切片。服务校验定义身份、参数和依赖指纹、特征切片覆盖、唯一领域归属、FeatureValue 来源以及 calculator 精确版本。

单项计算失败会保存 failed AtomicSignalValue。required 信号失败，或全部被选定义的失败比例达到本次写入集合的阻断阈值时，AtomicSignalSet 保存为 failed，不允许 DomainSignal 消费。

dry-run 执行相同校验和计算，但不写 AtomicSignalSet、AtomicSignalValue 或正式 AlertEvent。

当前尚未实现 DomainSignalDefinition 的正式模型及其后续完整版本包组件，因此完整 StrategyAnalysisRelease 仍不能进入正式批准；本切片不使用测试对象绕过正式批准 service。

## 配置

```text
FEATURE_SCHEMA_VERSION=1.0
SIGNAL_SCHEMA_VERSION=1.0
ATOMIC_SIGNAL_FAILURE_BLOCK_RATIO=0.3
```

## 命令

```bash
python manage.py seed_atomic_signal_definitions
python manage.py build_atomic_signals --feature-set-id <id> --strategy-analysis-release-id <id> --strategy-analysis-release-hash <hash> --business-request-key <key> --trace-id <id> --trigger-source manual
```

## 测试入口

```bash
pytest tests/strategy_analysis/test_atomic_signal.py tests/strategy_calculator/test_feature_compare.py -q
```
