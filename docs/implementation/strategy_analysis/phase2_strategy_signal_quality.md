# 阶段 2：StrategySignalQuality 实现记录

## 1. 本阶段实现范围

本阶段实现 StrategySignalQuality，即策略信号进入 DecisionSnapshot 前的质量检查层。

它做的事情是：

- 读取已经落库的 StrategySignal。
- 读取同一个 StrategyAnalysisRelease 中批准的质量规则集。
- 检查策略信号是否仍然满足下游消费条件。
- 生成 StrategySignalQualityResult。
- 对发现的问题生成 StrategySignalQualityIssue。
- 在阻断性失败或配置允许的 warning 场景写 AlertEvent。

它不做的事情是：

- 不重新执行策略算法。
- 不修改 StrategySignal。
- 不生成目标仓位。
- 不生成订单。
- 不读取账户、价格或 Binance。
- 不访问 Redis。
- 不调用 DeepSeek。
- 不发送 Hermes。
- 不参与真实交易执行。

## 2. 核心检查逻辑

当前质量层主要检查以下几类问题：

1. 策略信号自身结构是否完整  
   例如方向、强度、置信度、预测周期、实际使用领域输入是否存在。

2. 上游追溯关系是否一致  
   策略信号必须来自同一版本包、同一路由结果、同一策略定义、同一领域集合和同一市场环境快照。

3. 使用的领域输入是否有效  
   策略信号声明使用的领域值必须存在、属于同一领域集合、状态可用，并且属于策略允许使用的领域范围。

4. 权重合同是否一致  
   如果策略未启用权重，结果中不得夹带权重；如果策略启用权重，实际权重必须与策略定义冻结值一致。

5. 聚合摘要是否与主字段一致  
   StrategySignal 的主方向、强度、置信度必须与聚合摘要中的最终结果一致。

6. 证据是否覆盖实际输入  
   结构化证据必须能追溯到实际使用的领域输入。

7. 时效性检查  
   如果质量规则集配置了最大允许陈旧时间，超时会生成 warning。

## 3. warning 与 failed 的处理

质量检查结果分三类：

- passed：无质量问题，允许进入 DecisionSnapshot。
- warning：存在非阻断问题；是否允许进入 DecisionSnapshot 由质量规则集决定。
- failed：存在 error 或 critical 问题，不允许进入 DecisionSnapshot。

当前实现不把 warning 自动等同于失败。这样可以支持后续在正式规则中决定某些轻微问题是继续还是阻断。

## 4. 幂等与 dry-run

正式运行时：

- 同一个业务请求键只能创建一份质量结果。
- 同一个策略信号、规则集、验证模式和参考时间组合只创建一份质量结果。
- 重复请求返回已有结果，不重复写问题记录。

dry-run 时：

- 执行同样的检查。
- 不写 StrategySignalQualityResult。
- 不写 StrategySignalQualityIssue。
- 不写 AlertEvent。
- 不允许作为正式 DecisionSnapshot 输入。

## 5. 入口

服务入口：

```text
apps.strategy_analysis.services.strategy_signal_quality.validate_strategy_signal
```

人工命令入口：

```text
python manage.py validate_strategy_signal
```

management command 只负责解析参数并调用 service，不承载质量检查业务逻辑。

## 6. 验收

已通过：

```text
python -m pytest tests/strategy_analysis/test_strategy_signal_quality.py -q
python -m pytest tests/strategy_analysis -q
python -m pytest -q
python manage.py check
python manage.py makemigrations --check --dry-run
```

验收结果：

```text
StrategySignalQuality 单测：12 passed
strategy_analysis 测试：95 passed
全量测试：138 passed
Django system check：no issues
迁移检查：No changes detected
```

## 7. 当前 P0 策略承接补充

为了承接当前四个 P0 趋势类 StrategySignal calculator，StrategySignalQuality 增加以下检查点：

- `aggregation_snapshot` 必须包含最终方向、最终强度和最终置信度，并与 StrategySignal 主字段一致；
- `trade_price_condition` 如果存在，必须仍然是合法结构化价格条件；
- `trade_price_condition` 只做结构校验，不解释价格区间、不计算限价价格、不生成订单类型；
- 非法价格条件会生成质量 issue，并阻断进入 DecisionSnapshot。

这层仍然不重新执行策略、不读取 Feature / Atomic / Kline，不访问 Binance，不生成目标仓位或订单。
