# StrategyCalculator 注册框架实现记录

## 1. 对应需求

- `docs/requirements/strategy_calculator.md`
- `docs/plans/strategy_analysis_implementation_plan.md`

## 2. 本次实现范围

本次只实现公共纯计算框架：

```text
CalculatorMetadata
CalculatorInput
CalculatorOutput
CalculatorRegistry
calculator 精确注册与解析
```

本次没有实现任何正式交易算法，也没有把测试 calculator 注册成正式策略。

## 3. 代码位置

```text
apps/strategy_calculator/contracts.py
apps/strategy_calculator/registry.py
apps/strategy_calculator/errors.py
apps/strategy_calculator/utils.py
```

## 4. 关键实现说明

Calculator 以 `algorithm_name + algorithm_version` 作为唯一身份。注册时拒绝重复身份，解析时必须精确命中，不会自动回退到其他版本。

`CalculatorInput` 和 `CalculatorOutput` 使用不可变 DTO。输入参数、数值和证据会被冻结，避免 calculator 在计算过程中修改调用方传入的数据。

DTO 只接受纯数据结构，拒绝 ORM 对象、client、service 等运行对象；所有时间必须是 UTC，冻结参数内容必须与参数指纹一致，NaN 和 Infinity 不得进入输入或成功输出。

CalculatorRegistry 在首次解析或读取后自动进入只读状态，不能在正式运行过程中追加或替换 calculator。

`CalculatorOutput` 只允许：

```text
succeeded
failed
```

不允许 calculator 返回业务状态，例如 created、blocked、unknown。

Calculator 不读数据库、不访问 Redis、不访问 Binance、不访问 DeepSeek、不写 AlertEvent、不发送 Hermes、不生成订单动作。

## 5. 测试入口

```bash
pytest tests/strategy_calculator -q
```
