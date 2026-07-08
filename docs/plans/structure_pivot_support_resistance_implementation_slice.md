# 拐点型支撑压力实现切片

## 1. 文档目的

本文把 `docs/requirements/feature_layer/support_resistance_level_features.md` 中的新支撑压力识别口径，拆成可编码的实现切片。

这不是旧支撑压力算法的小修小补，而是一套新的拐点型支撑压力算法。

核心目标：

```text
有效局部低点 / 高点
→ 反弹 / 回落验证
→ 聚合成窄支撑区 / 压力区
→ 生成结构原子事实
→ Structure 领域表达当前结构状态
```

本文只定义实现切片，不直接决定 MarketRegime、策略路由、策略信号或目标仓位。

## 2. 版本口径

### 2.1 支撑压力算法版本

新的支撑压力算法命名为：

```text
pivot_support_resistance_v1
```

这里的 `v1` 指的是“拐点型支撑压力算法”的第一版，不是旧支撑压力算法的升级参数。

### 2.2 Structure 领域版本

当前系统已经存在：

```text
Structure v1.0
Structure v1.1
Structure v2.0
```

因此新的 Structure 领域版本不应继续占用 `v2.0`。

建议注册为：

```text
Structure v3.0 = 拐点型支撑压力结构版本
```

直白说：

```text
支撑压力算法：pivot_support_resistance_v1
Structure 领域：structure / v3.0
```

这样可以避免和现有 Structure v2 的“支撑压力并存表达”混在一起。

## 3. 新旧隔离原则

旧链路保留：

```text
旧支撑压力 Feature
→ 旧 Structure AtomicSignal
→ Structure v1 / v1.1 / v2
```

新链路新增：

```text
拐点型支撑压力 Feature
→ 拐点型 Structure AtomicSignal
→ Structure v3
```

规则：

- 不删除旧算法。
- 不覆盖旧 FeatureDefinition。
- 不复用旧支撑压力原子信号代码。
- 新版本包里不要同时选择旧支撑压力原子和新支撑压力原子。
- 新 Structure v3 只消费拐点型支撑压力原子。
- 旧 Structure v1 / v1.1 / v2 继续消费旧支撑压力原子。

## 4. Feature 切片

### 4.1 新 Feature 职责

FeatureLayer 负责计算客观结构位。

它只回答：

```text
最近有效支撑在哪里？
最近有效压力在哪里？
当前价格距离它们多远？
这些结构位是否足够窄？
这些结构位被触碰过几次？
当前是否正在测试结构位？
当前是否已经突破 / 跌破结构位？
```

它不回答：

```text
应该做多还是做空；
应该开仓还是平仓；
应该选择哪种策略；
应该给多少仓位。
```

### 4.2 P0 Feature 输出

P0 先只做 1d 与 4h 两组。

1d：

```text
structure_pivot_support_lower_1d_365
structure_pivot_support_upper_1d_365
structure_pivot_support_core_1d_365
structure_pivot_support_width_pct_1d_365
structure_pivot_support_touch_count_1d_365
structure_pivot_support_strength_1d_365
structure_pivot_support_status_1d_365
structure_pivot_distance_to_support_pct_1d_365
structure_pivot_distance_to_support_atr_1d_365

structure_pivot_resistance_lower_1d_365
structure_pivot_resistance_upper_1d_365
structure_pivot_resistance_core_1d_365
structure_pivot_resistance_width_pct_1d_365
structure_pivot_resistance_touch_count_1d_365
structure_pivot_resistance_strength_1d_365
structure_pivot_resistance_status_1d_365
structure_pivot_distance_to_resistance_pct_1d_365
structure_pivot_distance_to_resistance_atr_1d_365
```

4h：

```text
structure_pivot_support_lower_4h_120
structure_pivot_support_upper_4h_120
structure_pivot_support_core_4h_120
structure_pivot_support_width_pct_4h_120
structure_pivot_support_touch_count_4h_120
structure_pivot_support_strength_4h_120
structure_pivot_support_status_4h_120
structure_pivot_distance_to_support_pct_4h_120
structure_pivot_distance_to_support_atr_4h_120

structure_pivot_resistance_lower_4h_120
structure_pivot_resistance_upper_4h_120
structure_pivot_resistance_core_4h_120
structure_pivot_resistance_width_pct_4h_120
structure_pivot_resistance_touch_count_4h_120
structure_pivot_resistance_strength_4h_120
structure_pivot_resistance_status_4h_120
structure_pivot_distance_to_resistance_pct_4h_120
structure_pivot_distance_to_resistance_atr_4h_120
```

### 4.3 状态字段

`structure_pivot_support_status_*` 和 `structure_pivot_resistance_status_*` 使用文本状态。

允许值：

```text
none
candidate
active
testing
hold
breakdown_candidate
breakdown_confirmed
breakout_candidate
breakout_confirmed
invalidated
role_converted
```

说明：

- 支撑使用 `breakdown_*`。
- 压力使用 `breakout_*`。
- `role_converted` 只表达角色转换事实，不直接表达交易方向。

### 4.4 Feature 失败时的输出

如果没有找到有效支撑或压力：

```text
lower / upper / core = null
width_pct = null
touch_count = 0
strength = 0
status = none
distance = null
```

不能为了“有值”强行输出宽区间。

## 5. AtomicSignal 切片

### 5.1 新原子信号命名

新原子统一使用 `structure_pivot_` 前缀，避免和旧原子混淆。

1d 支撑：

```text
structure_pivot_major_support_valid
structure_pivot_major_near_support
structure_pivot_major_support_testing
structure_pivot_major_support_holds
structure_pivot_major_support_breakdown_candidate
structure_pivot_major_support_breakdown_confirmed
```

1d 压力：

```text
structure_pivot_major_resistance_valid
structure_pivot_major_near_resistance
structure_pivot_major_resistance_testing
structure_pivot_major_resistance_holds
structure_pivot_major_resistance_breakout_candidate
structure_pivot_major_resistance_breakout_confirmed
```

4h 支撑：

```text
structure_pivot_minor_support_valid
structure_pivot_minor_near_support
structure_pivot_minor_support_testing
structure_pivot_minor_support_holds
structure_pivot_minor_support_breakdown_candidate
structure_pivot_minor_support_breakdown_confirmed
```

4h 压力：

```text
structure_pivot_minor_resistance_valid
structure_pivot_minor_near_resistance
structure_pivot_minor_resistance_testing
structure_pivot_minor_resistance_holds
structure_pivot_minor_resistance_breakout_candidate
structure_pivot_minor_resistance_breakout_confirmed
```

夹层 / 不明确：

```text
structure_pivot_major_between_support_resistance
structure_pivot_minor_between_support_resistance
structure_pivot_major_unclear
structure_pivot_minor_unclear
```

### 5.2 原子职责

原子只把 Feature 数值转换为可聚合事实。

例子：

```text
structure_pivot_major_support_holds
```

只能表达：

```text
1d 拐点支撑仍然有效，当前没有确认跌破。
```

不能表达：

```text
应该做多；
应该减空；
行情一定会反弹。
```

### 5.3 不复用旧原子的原因

旧原子基于旧 Feature：

```text
structure_major_support_lower_1d_365
structure_major_support_upper_1d_365
...
```

新原子基于新 Feature：

```text
structure_pivot_support_lower_1d_365
structure_pivot_support_upper_1d_365
...
```

两者含义不同。

旧原子里的“支撑有效”可能来自宽区间。

新原子里的“支撑有效”必须来自有效局部低点聚合出的窄区域。

因此新旧不能混用。

## 6. DomainSignal 切片

### 6.1 新 Structure v3 职责

Structure v3 只聚合拐点型结构事实。

它应输出：

```text
下方是否有有效支撑；
上方是否有有效压力；
当前更靠近支撑还是压力；
当前是否正在测试支撑；
当前是否正在测试压力；
是否出现支撑跌破候选；
是否出现压力突破候选；
是否确认跌破关键支撑；
是否确认突破关键压力；
是否处于支撑压力夹层。
```

它不应只输出一句：

```text
支撑守住
```

因为支撑和压力可能同时存在。

### 6.2 推荐状态

Structure v3 可输出以下状态：

```text
pivot_structure_support_side
pivot_structure_resistance_side
pivot_structure_between_support_resistance
pivot_structure_support_testing
pivot_structure_resistance_testing
pivot_structure_support_breakdown_candidate
pivot_structure_support_breakdown_confirmed
pivot_structure_resistance_breakout_candidate
pivot_structure_resistance_breakout_confirmed
pivot_structure_unclear
```

中文展示建议：

```text
靠近支撑侧
靠近压力侧
位于支撑压力之间
正在测试支撑
正在测试压力
支撑跌破候选
支撑确认跌破
压力突破候选
压力确认突破
结构不明确
```

### 6.3 输出摘要

Structure v3 的 payload 应包含：

```text
support_zone
resistance_zone
current_position
major_context
minor_context
support_resistance_context
text_zh
```

`support_zone` 和 `resistance_zone` 至少包含：

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
timeframe
```

### 6.4 聚合原则

优先级从高到低：

```text
确认跌破 / 确认突破
→ 跌破候选 / 突破候选
→ 正在测试支撑 / 压力
→ 支撑压力夹层
→ 靠近某一侧
→ 结构不明确
```

如果支撑和压力同时有效：

- 不强行选择一边作为唯一结论；
- 必须在 payload 里同时保留上下两侧；
- `text_zh` 应说明当前价格处于什么位置。

## 7. 后台组装口径

当前阶段仍允许手工选择组件。

但在新版本包中，临时选择原则是：

```text
选新版 pivot Feature；
选新版 structure_pivot AtomicSignal；
选 Structure v3；
不要同时选旧支撑压力 AtomicSignal；
不要同时选旧 Structure v1 / v1.1 / v2。
```

后续 `TODO-015` 会处理自动依赖带入。

在 `TODO-015` 完成前，每次创建新版本包时，需要人工核对：

- 新 Structure v3 是否被纳入；
- 新 `structure_pivot_` 原子是否被纳入；
- 新 `structure_pivot_` 特征是否被纳入；
- 旧 `structure_major_*` / `structure_minor_*` 支撑压力原子是否没有被混选。

## 8. 页面展示口径

回测周期详情页中，Structure v3 应展示：

```text
最近支撑区
最近压力区
当前价格位置
距离支撑
距离压力
结构状态
为什么这么判断
```

示例：

```text
最近支撑：71500 - 72800
来源：1d 有效局部低点聚合
触碰次数：3
状态：测试中
当前距离：0.8%

最近压力：84500 - 85800
来源：1d 有效局部高点聚合
触碰次数：2
状态：有效
当前距离：16.4%

结论：价格正在测试下方支撑，上方仍存在压力，因此不是单边结构。
```

## 9. 实现顺序

第一步：Feature

```text
新增 FeatureDefinition；
新增拐点型支撑压力 calculator；
单元测试覆盖：
  - 局部低点识别；
  - 局部高点识别；
  - 反弹 / 回落验证；
  - 区域宽度上限；
  - 无有效结构位时输出 null / none。
```

第二步：AtomicSignal

```text
新增 structure_pivot_ 原子定义；
测试每个原子只读取新 Feature；
确认旧原子不会误读新 Feature。
```

第三步：DomainSignal

```text
新增 Structure v3 定义；
新增 Structure v3 聚合逻辑；
测试支撑压力并存时不会压缩成单一结论。
```

第四步：后台展示

```text
周期详情页展示新支撑 / 压力区；
结构解释使用中文；
旧字段不混入新结构解释。
```

第五步：回测验证

```text
先跑单点和短窗口；
确认结构线合理后再跑大窗口。
```

## 10. 验收样本

优先样本：

```text
2026-05-10
2026-05-16
2026-05-27
2026-06-01
2025-04-08
2025-10-15
```

验收重点：

- 不再输出过宽区间；
- 支撑 / 压力接近图上能看懂的关键位；
- 允许窄区间误差，例如 `71500 - 72800`；
- 不允许把多个结构位揉成一个巨大区间；
- 支撑和压力同时存在时，页面能解释清楚；
- 没有未来数据泄漏；
- 没有交易动作越界。

## 11. 当前切片不做什么

本切片不做：

```text
MarketRegime v6；
策略路由调整；
策略信号调整；
目标仓位调整；
OrderPlan；
RiskCheck；
Execution；
真实交易；
成交量确认；
自动组件依赖带入。
```

其中：

- MarketRegime 如何消费 Structure v3，等 Structure v3 验证稳定后再设计。
- 成交量确认属于另一个领域复核问题，不塞进本切片。
- 自动组件依赖带入已经记入 `TODO-015`，不阻塞本次主线。

## 12. 通过标准

本切片通过标准：

- 新 Feature 能独立生成拐点型支撑压力结构位。
- 新 AtomicSignal 只消费新 Feature。
- 新 Structure v3 只消费新原子。
- 新旧支撑压力链路互不污染。
- 回测详情页能解释支撑压力来源和当前状态。
- 典型样本不再出现过宽支撑压力区。
- 不违反 FeatureLayer / AtomicSignal / DomainSignal 的交易红线。

