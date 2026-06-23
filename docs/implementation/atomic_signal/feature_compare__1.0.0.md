# feature_compare 1.0.0 实现记录

## 对应需求

- `docs/requirements/atomic_signals.md`
- `docs/requirements/strategy_calculator.md`

## 代码位置

```text
apps/strategy_calculator/atomic_signal/feature_compare.py
```

## 实现合同

`feature_compare` 是纯计算 calculator，只比较两个明确数值特征，或一个数值特征与常量。

当前支持运算符：

```text
gt
gte
lt
lte
eq
ne
```

布尔条件成立时输出定义声明的默认方向和强度 `1`；条件不成立时输出 `neutral` 和强度 `0`；`confidence` 固定为空，不把计算成功解释为高置信度。

calculator 不读取数据库、Redis、Kline、Binance 或运行时当前时间，不生成策略、目标仓位和订单语义。

## 测试入口

```bash
pytest tests/strategy_calculator/test_feature_compare.py -q
```
