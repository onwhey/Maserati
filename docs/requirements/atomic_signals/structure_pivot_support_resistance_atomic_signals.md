# 拐点型支撑压力原子信号需求

## 1. 文档目的

本文定义新版 Structure 支撑压力链路中的 AtomicSignal 口径。

它承接：

```text
docs/requirements/feature_layer/support_resistance_level_features.md
```

对应实现切片：

```text
docs/plans/structure_pivot_support_resistance_implementation_slice.md
```

本文只回答一件事：

```text
Feature 已经算出拐点型支撑/压力后，原子信号如何把这些数值翻译成最小市场事实。
```

本文不负责：

```text
重新识别支撑/压力；
判断牛市或熊市；
判断 MarketRegime；
选择策略；
生成 StrategySignal；
生成目标仓位；
生成订单；
读取账户、持仓、订单、成交；
访问 Binance；
访问 Redis；
发送 Hermes；
调用大模型；
参与真实交易。
```

## 2. 核心边界

新版原子信号统一使用 `structure_pivot_` 前缀。

原因是它和旧 Structure 支撑压力原子不是同一套东西：

```text
旧支撑压力：可能来自较宽的历史区间。
新支撑压力：必须来自有效局部低点/高点，再经过反弹/回落验证与窄区聚合。
```

所以新版原子不能复用旧原子代码，也不能和旧原子混在同一个 Structure 聚合版本里使用。

## 3. 输入 Feature

P0 只消费两组周期：

```text
1d / 365：大级别结构位
4h / 120：小级别结构位
```

每组支撑/压力都包含：

```text
lower
upper
core
width_pct
touch_count
strength
status
distance_pct
distance_atr
```

其中 `status` 是原子信号的优先输入。

允许状态：

```text
none
active
testing
hold
breakdown_candidate
breakdown_confirmed
breakout_candidate
breakout_confirmed
invalidated
```

AtomicSignal 不得重新读取 K 线，不得重新计算局部高低点，不得重新聚类支撑压力。

## 4. 原子信号清单

### 4.1 1d 大支撑

```text
structure_pivot_major_support_valid
structure_pivot_major_near_support
structure_pivot_major_support_testing
structure_pivot_major_support_holds
structure_pivot_major_support_breakdown_candidate
structure_pivot_major_support_breakdown_confirmed
```

### 4.2 1d 大压力

```text
structure_pivot_major_resistance_valid
structure_pivot_major_near_resistance
structure_pivot_major_resistance_testing
structure_pivot_major_resistance_holds
structure_pivot_major_resistance_breakout_candidate
structure_pivot_major_resistance_breakout_confirmed
```

### 4.3 4h 小支撑

```text
structure_pivot_minor_support_valid
structure_pivot_minor_near_support
structure_pivot_minor_support_testing
structure_pivot_minor_support_holds
structure_pivot_minor_support_breakdown_candidate
structure_pivot_minor_support_breakdown_confirmed
```

### 4.4 4h 小压力

```text
structure_pivot_minor_resistance_valid
structure_pivot_minor_near_resistance
structure_pivot_minor_resistance_testing
structure_pivot_minor_resistance_holds
structure_pivot_minor_resistance_breakout_candidate
structure_pivot_minor_resistance_breakout_confirmed
```

### 4.5 夹层与不明确

```text
structure_pivot_major_between_support_resistance
structure_pivot_minor_between_support_resistance
structure_pivot_major_unclear
structure_pivot_minor_unclear
```

## 5. 判断口径

### 5.1 有效支撑/压力

有效支撑成立条件：

```text
support lower / upper / core 都存在；
support strength > 0；
support status 属于 active / testing / hold。
```

有效压力成立条件：

```text
resistance lower / upper / core 都存在；
resistance strength > 0；
resistance status 属于 active / testing / hold。
```

说明：

```text
breakdown_candidate / breakdown_confirmed 不再算“有效支撑”，而是结构破坏类事实。
breakout_candidate / breakout_confirmed 不再算“有效压力”，而是结构突破类事实。
invalidated 不作为有效结构位。
```

### 5.2 靠近支撑/压力

靠近支撑成立条件：

```text
有效支撑成立；
distance_to_support_pct 不为空；
distance_to_support_pct >= 0；
distance_to_support_pct <= near_threshold。
```

靠近压力成立条件：

```text
有效压力成立；
distance_to_resistance_pct 不为空；
distance_to_resistance_pct >= 0；
distance_to_resistance_pct <= near_threshold。
```

P0 阈值：

```text
1d near_threshold = 2.5%
4h near_threshold = 1.0%
```

直白解释：

```text
靠近，只表示价格离某个有效结构位不远。
靠近支撑不等于支撑守住。
靠近压力不等于压力压住。
```

### 5.3 测试支撑/压力

测试支撑成立条件：

```text
support status = testing
```

测试压力成立条件：

```text
resistance status = testing
```

直白解释：

```text
价格已经进入支撑/压力区域，市场正在检验这个位置是否有效。
```

### 5.4 支撑守住 / 压力压住

支撑守住成立条件：

```text
support status = hold
```

压力压住成立条件：

```text
resistance status = hold
```

直白解释：

```text
支撑守住 = 价格测试支撑后，没有确认跌破，并出现离开支撑区的反应。
压力压住 = 价格测试压力后，没有确认突破，并出现离开压力区的反应。
```

注意：

```text
“价格在支撑上方”不等于“支撑守住”。
“价格在压力下方”不等于“压力压住”。
```

### 5.5 跌破/突破候选

支撑跌破候选成立条件：

```text
support status = breakdown_candidate
```

压力突破候选成立条件：

```text
resistance status = breakout_candidate
```

直白解释：

```text
候选 = 已经出现穿透迹象，但确认条件还不够。
```

候选状态不能直接当成趋势反转，也不能直接生成交易动作。

### 5.6 确认跌破/确认突破

支撑确认跌破成立条件：

```text
support status = breakdown_confirmed
```

压力确认突破成立条件：

```text
resistance status = breakout_confirmed
```

直白解释：

```text
确认跌破 = 支撑作为支撑的角色被破坏。
确认突破 = 压力作为压力的角色被破坏。
```

这里表达的是结构事实，不是下单指令。

### 5.7 支撑压力夹层

支撑压力夹层成立条件：

```text
有效支撑成立；
有效压力成立；
support upper < resistance lower；
当前价格位于 support upper 与 resistance lower 之间。
```

直白解释：

```text
下方有有效支撑，上方有有效压力，价格夹在两者中间。
这种状态不应该被压缩成单边“支撑守住”或单边“压力压住”。
```

### 5.8 不明确

不明确成立条件：

```text
没有有效支撑；
没有有效压力；
或者关键 Feature 缺失，无法形成结构判断。
```

直白解释：

```text
系统找不到足够可靠的拐点型支撑/压力参考。
```

不明确不是看多，也不是看空。

## 6. direction 规则

原子信号只表达结构方向，不表达交易动作。

```text
near / testing / hold / valid / between / unclear 默认 direction = neutral
support_breakdown_candidate / support_breakdown_confirmed direction = bearish
resistance_breakout_candidate / resistance_breakout_confirmed direction = bullish
```

这里的 bullish / bearish 只表示结构方向：

```text
压力被突破，对结构偏多；
支撑被跌破，对结构偏空。
```

不得解释为：

```text
应该做多；
应该做空；
应该加仓；
应该平仓。
```

## 7. 输出要求

每个 AtomicSignalValue 必须输出：

```text
value_bool
direction
strength
confidence
used_feature_codes
used_feature_value_ids
evidence_items
evidence_text_zh
```

P0 规则：

```text
条件成立：value_bool = true，strength = 1
条件不成立：value_bool = false，strength = 0
计算失败：is_valid = false，并写明 error_code
confidence 默认 null
```

不得因为计算成功就把 confidence 写成 1。

## 8. evidence_text_zh 示例

成立示例：

```text
1d 拐点支撑区为 71500~72800，当前价格进入支撑区后未确认跌破，Feature 状态为 hold，因此“1d 大支撑守住”成立。
```

不成立示例：

```text
1d 拐点支撑区存在，但当前价格距离支撑上沿 5.2%，高于 2.5% 靠近阈值，因此“1d 靠近大支撑”不成立。
```

夹层示例：

```text
当前下方存在 1d 拐点支撑区 71500~72800，上方存在 1d 拐点压力区 85000~86500，价格位于两者之间，因此“大级别支撑压力夹层”成立。
```

不得在说明中写：

```text
建议开多；
建议开空；
适合加仓；
应该止损；
目标仓位应为多少。
```

## 9. 与旧原子信号的关系

旧链路继续保留：

```text
旧 Feature
→ 旧 Structure AtomicSignal
→ Structure v1 / v1.1 / v2
```

新链路新增：

```text
structure_pivot_* Feature
→ structure_pivot_* AtomicSignal
→ Structure v3
```

一个正式版本包中，不建议同时选择旧支撑压力原子和新版拐点型支撑压力原子。

如果后台暂时无法自动识别互斥关系，应在版本包人工组装时避免混用。

## 10. 验收方式

通过标准：

```text
没有重新计算 K 线或拐点；
只消费 FeatureValue；
能区分“靠近”“测试”“守住”“候选跌破/突破”“确认跌破/突破”；
支撑和压力同时存在时能输出夹层事实；
没有把结构事实写成交易建议；
缺少 Feature 时明确失败或输出不明确，不用默认值硬凑结论。
```

失败标准：

```text
只要价格在支撑上方就说支撑守住；
只要价格在压力下方就说压力压住；
候选跌破/突破直接被当成确认；
支撑和压力同时存在时只保留一个单边结论；
AtomicSignal 重新实现 FeatureLayer 的支撑压力算法；
输出目标仓位、订单动作或策略建议。
```
