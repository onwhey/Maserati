# single_atomic_passthrough 1.0.0 实现记录

## 定位

这是 DomainSignal 的单输入过渡算法，只用于把一个已经有效的 AtomicSignalValue 映射为一个 DomainSignalValue。

它不读取数据库、不访问 Redis、不访问 Binance、不调用 DeepSeek、不发送 Hermes、不生成交易动作。

## 输入

业务 service 只传入一个有效原子信号：

```text
AtomicSignalValue.status = created
AtomicSignalValue.is_valid = true
```

算法不接收 FeatureValue、Kline、账户、价格、订单、编排运行对象或策略权重。

## 计算逻辑

directional 领域：

```text
原子方向 bullish / bearish / neutral → 原样作为领域方向
原子方向 none → 领域方向 neutral
领域强度 = 原子强度
coverage_ratio = 1
agreement_ratio = null
```

state 领域：

```text
领域方向固定为 none
若原子方向为 bullish / bearish 且强度大于 0：
    state_code = params.state_code_when_active 或原子方向
否则：
    state_code = params.state_code_when_inactive 或 neutral
领域强度 = 原子强度
coverage_ratio = 1
agreement_ratio = null
```

这里的“强度透传”是本算法版本的明确合同，不是业务 service 默认复制上游强度。

## 失败条件

以下情况直接返回 failed：

```text
缺少 domain_code 或 output_mode；
输入原子信号不是恰好一个；
输入不是结构化纯数据；
原子信号无效；
原子方向非法；
原子强度不是 0 到 1 之间的有限数；
领域输出模式不支持。
```

## 后续替换

当领域算法成熟后，应新增新的 calculator 文件和新的 implementation 记录，例如：

```text
docs/implementation/domain_signal/directional_consensus__1.0.0.md
docs/implementation/domain_signal/state_classifier__1.0.0.md
```

不得修改本文件对应算法的历史语义。
