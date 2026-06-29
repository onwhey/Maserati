# atomic_condition 1.0.0 实现记录

## 1. 定位

`atomic_condition` 是 AtomicSignal 层的通用条件判断 calculator。

它只消费同一个 `FeatureSet` 中已经落库的 `FeatureValue` 摘要，不读取 K 线，不调用 FeatureLayer calculator，也不访问账户、订单、Binance、DeepSeek 或任何外部服务。

## 2. 输入

每个 `AtomicSignalDefinition.params` 至少包含：

```json
{
  "conditions": [
    {
      "feature_code": "return_pct_1d_7",
      "operator": "gte",
      "value": "0.03"
    }
  ],
  "aggregation": "all",
  "label_zh": "1d 存在明显多头推进",
  "evidence_type": "momentum_atomic_condition"
}
```

支持的条件形式：

```text
feature_code + operator + value
feature_code + operator + right_feature_code
feature_code + operator + right_feature_code + right_multiplier
feature_code + is_null
feature_code + is_not_null
```

支持的数值运算：

```text
gt / gte / lt / lte / eq / ne / abs_gte / abs_lte
```

`aggregation` 支持：

```text
all：全部条件成立才成立；
any：任一条件成立即成立。
```

## 3. null 处理

数值条件遇到 `FeatureValue.value = null` 时，条件结果为 `false`，不会把 null 当成 0。

只有 `is_null` / `is_not_null` 会直接判断 null 状态。

这用于支撑压力缺失、区间不可用等结构类原子信号。

## 4. 输出

普通原子信号输出布尔结果：

```text
value = true / false
direction = 条件成立时使用 AtomicSignalDefinition.default_direction，不成立时 neutral
strength = 条件成立时 1，不成立时 0
confidence = null
```

`risk_state` 原子信号可以使用结构化 JSON 输出：

```json
{
  "condition_met": true,
  "risk_category": "long_exposure_risk",
  "risk_direction": "downside",
  "risk_severity": "high"
}
```

其中 `risk_severity` 只表达该原子风险的严重程度，不代表交易动作、仓位处理或停止交易。

## 5. 证据

每次计算输出：

```text
evidence_items
evidence_text_zh
```

证据只记录：

```text
使用了哪些 FeatureValue；
观察值是多少；
比较条件是什么；
每个条件是否成立；
最终原子判断是否成立。
```

证据不得包含完整 K 线窗口、完整历史数组、账户信息、订单信息或交易建议。

## 6. 明确不负责

`atomic_condition` 不负责：

```text
计算 Feature；
跨原子聚合；
形成 DomainSignal；
识别 MarketRegime；
选择策略；
生成 StrategySignal；
生成目标仓位；
生成订单意图；
执行真实交易。
```
## 7. 结构类 JSON 原子补充说明

`atomic_condition` 支持 `include_feature_values` 参数。该参数只把本次 calculator 输入中已经存在的 `FeatureValue` 摘要复制进 JSON 输出，不重新计算特征，也不调用 FeatureLayer。

结构类原子默认携带以下支撑/压力区间特征快照：

```text
structure_major_support_lower_1d_365
structure_major_support_upper_1d_365
structure_major_resistance_lower_1d_365
structure_major_resistance_upper_1d_365
structure_minor_support_lower_4h_120
structure_minor_support_upper_4h_120
structure_minor_resistance_lower_4h_120
structure_minor_resistance_upper_4h_120
```

输出示例：

```json
{
  "condition_met": true,
  "structure_signal_family": "zone_snapshot",
  "feature_values": {
    "structure_major_support_lower_1d_365": {
      "feature_value_id": 1,
      "value": "49000",
      "value_type": "decimal"
    }
  }
}
```

该快照只作为后续 DomainSignal / StrategySignal 的证据输入，不代表交易建议。
