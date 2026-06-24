# 阶段 2：DecisionSnapshot 实现记录

## 1. 本阶段实现范围

本阶段实现 DecisionSnapshot，即策略信号质量检查通过后，把标准化策略判断转换成目标仓位语义的模块。

它做的事情是：

- 读取已经落库的 StrategySignalQualityResult。
- 校验质量结果、StrategySignal 和 StrategyAnalysisRelease 是否仍然一致。
- 读取同一个版本包中唯一批准的 DecisionPolicyDefinition。
- 通过 DecisionPolicy calculator 生成目标仓位意图。
- 写入 DecisionSnapshot。
- 在阻断、失败或未知场景写 AlertEvent。

它不做的事情是：

- 不重新分析市场环境。
- 不读取 DomainSignal 或 MarketRegime 重新判断市场。
- 不读取账户、持仓、价格或 Binance。
- 不生成订单。
- 不做风控审批。
- 不访问 Redis。
- 不调用 DeepSeek。
- 不发送 Hermes。
- 不涉及交易执行或真实交易。

## 2. 核心业务逻辑

DecisionSnapshot 只消费已经通过质量检查的 StrategySignalQualityResult。

正常流程是：

```text
StrategySignalQualityResult
→ DecisionPolicyDefinition
→ DecisionPolicy calculator
→ DecisionSnapshot
```

DecisionSnapshot 当前只允许产生三类目标意图：

```text
TARGET_POSITION
NO_TARGET_CHANGE
NO_TRADE
```

其中：

- TARGET_POSITION 必须包含目标总仓位比例，范围是 -1 到 1。
- 目标仓位比例 0 表示目标空仓，不表示具体下单动作。
- NO_TARGET_CHANGE / NO_TRADE 不允许携带目标仓位比例。
- 只有可用且未过期的 TARGET_POSITION 才允许进入 OrderPlan。

## 3. Calculator 边界

DecisionPolicy calculator 只接收策略信号和质量结果形成的标准化输入。

它不会收到：

- 策略代码用于重新选择策略。
- MarketRegimeSnapshot 用于重新判断市场。
- DomainSignalValue 用于重新聚合领域信号。
- 账户、仓位、价格或 Binance 数据。

这样可以避免 DecisionSnapshot 变成第二层策略分析模块。

## 4. 幂等与 dry-run

正式运行时：

- 同一个业务请求键只能创建一份 DecisionSnapshot。
- 同一份质量结果、同一份决策规则和同一份输出结果会形成稳定快照键。
- 重复请求返回已有结果，不重复调用 calculator。

dry-run 时：

- 执行同样的校验和 calculator 调用。
- 不写 DecisionSnapshot。
- 不写 AlertEvent。
- 不允许作为 OrderPlan 输入。

## 5. 入口

服务入口：

```text
apps.strategy_analysis.services.decision_snapshot.build_decision_snapshot
```

人工命令入口：

```text
python manage.py build_decision_snapshot
```

management command 只负责解析参数并调用 service，不承载目标仓位业务逻辑。

## 6. 验收

已通过：

```text
python -m pytest tests/strategy_analysis/test_decision_snapshot.py -q
python -m pytest tests/strategy_analysis -q
python -m pytest -q
python manage.py check
python manage.py makemigrations --check --dry-run
```

验收结果：

```text
DecisionSnapshot 单测：13 passed
strategy_analysis 测试：108 passed
全量测试：151 passed
Django system check：no issues
迁移检查：No changes detected
```
