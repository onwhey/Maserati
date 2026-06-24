# StrategyAnalysis 阶段 2 第一切片实现记录

## 1. 对应需求

- `docs/requirements/strategy_analysis_release.md`
- `docs/requirements/feature_layer.md`
- `docs/plans/strategy_analysis_implementation_plan.md`

## 2. 本次实现范围

本次实现：

```text
StrategyAnalysisRelease 基础模型
ReleaseItem / Approval / Activation / ValidationEvidence
FeatureDefinition
FeatureSet / FeatureValue
版本包 hash 计算
版本包冻结、验证证据记录、批准、启用
FeatureLayer 正式 service
```

本次没有实现：

```text
AtomicSignal
DomainSignal
MarketRegime
StrategyRouting
StrategySignal
StrategySignalQuality
DecisionSnapshot
正式策略算法
后台自由组合回测
订单、账户、价格、风控、执行
```

## 3. 代码位置

```text
apps/strategy_analysis/models.py
apps/strategy_analysis/services/release.py
apps/strategy_analysis/services/feature_layer.py
apps/strategy_analysis/migrations/0001_initial.py
apps/strategy_analysis/migrations/0002_release_active_slot.py
apps/strategy_analysis/migrations/0003_remove_release_active_check.py
```

## 4. 关键实现说明

正式 FeatureLayer service 必须接收明确的：

```text
market_snapshot_id
strategy_analysis_release_id
release_hash
expected_definition_set_hash
```

编排开始时负责选择当时唯一已批准并启用的版本包。FeatureLayer 后续消费时校验历史批准、历史启用、版本包指纹和特征切片指纹，不再要求该版本仍是后台当前启用版本，因此后台切换只影响新运行，不会打断已经冻结版本的一轮。

数据库使用唯一启用槽位保证同一时刻最多存在一个当前版本。版本切换、Activation 审计和 AlertEvent 在同一事务内完成。

后续切片已补充 AtomicSignal 与 DomainSignal 的正式定义模型和部分依赖校验。MarketRegime、路由、策略和目标仓位正式定义模型仍未实现，因此包含这些未实现正式组件的完整版本包仍会在批准阶段保守阻断；测试 fake calculator 不能通过正式批准 service 伪装成完整版本包。

FeatureLayer 只读取 MarketSnapshot 固定窗口内的 Kline，并重新核对采集域、数量、连续时间索引、已收盘边界和窗口身份。FeatureDefinition 的代码、算法版本、参数内容与指纹必须同时一致。

FeatureSet 由数据库唯一约束和冲突后回查共同保护；并发重复请求复用已经完整落库的结果。阻断、失败和未知结果写对应 AlertEvent。

dry-run 会执行同一套 calculator 调用和校验，但不写 FeatureSet、FeatureValue，也不写正式 AlertEvent。

## 5. 测试入口

```bash
pytest tests/strategy_analysis -q
```
