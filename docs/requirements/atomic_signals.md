# AtomicSignal 需求说明

## 1. 模块定位

AtomicSignal 是 FeatureLayer 之后、DomainSignal 之前的原子市场判断层。

它把一项或少量明确的 `FeatureValue` 转换为单一、可解释、可追溯的市场条件判断。

正式链路为：

```text
MarketSnapshot
→ FeatureSet / FeatureValue
→ AtomicSignalSet / AtomicSignalValue
→ DomainSignalSet / DomainSignalValue
→ MarketRegimeSnapshot
→ StrategyRouteDecision
→ StrategySignal
→ StrategySignalQualityResult
→ DecisionSnapshot
```

AtomicSignal 负责：

```text
接收明确的 feature_set_id；
校验 FeatureSet 是否允许原子信号层消费；
冻结本次使用的 AtomicSignalDefinition 集合；
读取定义声明的 FeatureValue；
执行单一、原子化的条件判断；
生成 AtomicSignalSet；
生成逐项 AtomicSignalValue；
保存结构化证据和中文证据；
为 DomainSignal 提供统一、可审计的输入。
```

AtomicSignal 不负责：

```text
读取 Kline；
重新计算基础特征；
请求 Binance；
聚合多个原子信号形成策略结论；
分配策略权重；
计算目标仓位；
读取账户或持仓；
生成订单意图；
风控审批；
交易执行；
调用 DeepSeek 或其他大模型。
```

## 2. 名称与语义

AtomicSignal 是规则型原子判断，不是机器学习模型。

不得使用以下名称表达本模块的对象：

```text
WeakModel
ModelResult
ModelSignal
```

避免把普通规则判断误解为模型训练、模型推理或大模型决策。

AtomicSignal 的 `signal` 只表示市场条件判断，不等于：

```text
交易策略；
目标仓位；
买卖建议；
候选订单意图；
审批通过订单意图；
交易所订单。
```

## 3. 业务目标

AtomicSignal 必须解决：

```text
把基础特征转换为标准化的单点条件判断；
让领域层复用原子判断而不是重复实现特征比较；
让每个判断具有独立定义、算法版本和参数身份；
让每个判断可以单独统计、回测和复盘；
正式运行只计算本轮已批准版本包明确选择的定义；
未被正式版本包选择的定义只允许由后台研究与回测服务组合运行；
隔离单项计算失败；
在输入整体不可靠时阻断领域层及其后续链路；
保存机器可读证据和人类可读中文证据。
```

## 4. 核心原则

### 4.1 FeatureSet 是唯一正式输入边界

AtomicSignalService 必须接收明确的 `feature_set_id`。

只允许消费同时满足以下条件的 FeatureSet：

```text
status = created；
is_usable = true；
allows_atomic_signal = true；
FeatureValue 集合完整；
required FeatureValue 全部有效。
```

AtomicSignal 只消费 FeatureSet 已经固定的特征事实。MarketSnapshot 与 FeatureLayer 已负责固定行情来源、周期和数据窗口；AtomicSignal 不直接读取 Kline，也不重新选择或解释行情采集域。

AtomicSignal 不得：

```text
按当前市场身份自行寻找“最近一份” FeatureSet；
通过 MarketSnapshot 重新计算 FeatureValue；
绕过 FeatureSet 直接读取 Kline；
调用 FeatureLayerService 临时补算特征；
根据原子信号名称自动推导或创建特征；
混用不同 FeatureSet 的 FeatureValue。
```

### 4.2 原子信号之间平权

AtomicSignal 之间不得互相调用或依赖彼此输出。

禁止：

```text
AtomicSignal A 读取 AtomicSignal B；
一个 AtomicSignal 聚合多个 AtomicSignal；
AtomicSignal 内部分配信号权重；
AtomicSignal 内部执行策略路由；
AtomicSignal 内部形成最终多空结论。
```

每个 AtomicSignal 只判断其定义中明确声明的条件。

同类原子信号的聚合与领域结论生成属于 DomainSignal。AtomicSignal 不负责跨领域判断、市场背景分类、策略路由或策略权重计算。

### 4.3 统一输出合同

所有 AtomicSignalValue 必须遵守同一核心结构，至少包括：

```text
signal_code；
direction；
strength；
confidence；
status；
is_valid；
evidence_items；
evidence_text_zh；
used_feature_codes；
used_feature_value_ids；
algorithm_name；
algorithm_version；
params_hash；
definition_hash。
```

不得为每个原子信号设计互不兼容的输出对象。

### 4.4 不输出权重

AtomicSignal 禁止输出：

```text
weight
priority
fixed_weight
static_weight
strategy_weight
final_score
strategy_score
```

AtomicSignalDefinition 不定义面向策略层的角色。原子信号属于哪个领域、是否为某个领域必需输入，由 DomainSignalDefinition 明确声明。

### 4.5 失败不能伪装为正常 neutral

失败结果可以使用安全降级值：

```text
direction = neutral；
strength = 0；
confidence = null。
```

但必须同时满足：

```text
status = failed；
is_valid = false；
error_code 非空；
error_message 非空；
evidence_text_zh 明确说明失败原因。
```

下游必须先检查 `status` 和 `is_valid`，再解释 direction 与 strength。`confidence` 只有在对应 calculator 定义了可复现含义时才允许使用，不得把计算成功自动解释为高置信度。

### 4.6 MySQL 是正式事实来源

以下对象必须持久化到 MySQL：

```text
AtomicSignalDefinition；
AtomicSignalSet；
AtomicSignalValue。
```

Redis 只允许用于：

```text
短期幂等控制；
并发互斥；
短期计算缓存；
Celery 任务状态。
```

Redis 不得成为 AtomicSignalValue 的唯一存储，也不得作为 DomainSignal 的正式输入来源。

## 5. 输入合同

AtomicSignalService 的正式输入至少包括：

```text
feature_set_id
strategy_analysis_release_id
strategy_analysis_release_hash
expected_atomic_signal_definition_set_hash
business_request_key
trace_id
trigger_source
```

正式运行的版本包选择、批准、启用、切换、回滚和后台研究隔离统一遵守 [StrategyAnalysisRelease](strategy_analysis_release.md)。

AtomicSignalService 必须只读取本轮已冻结 StrategyAnalysisRelease 的原子信号切片，不得读取“全部 active 且 enabled 的定义”自行组装正式计算集合。

### 5.1 feature_set_id

`feature_set_id` 是本次计算的唯一特征事实入口。

服务必须通过该 ID 读取：

```text
FeatureSet 状态与放行字段；
FeatureSet 绑定的 market_snapshot_id；
exchange；
market_type；
symbol；
analysis_close_time_utc；
FeatureValue；
FeatureDefinition 身份；
feature_set_key；
definition_set_hash。
```

### 5.2 StrategyAnalysisRelease 原子信号切片

`strategy_analysis_release_id` 与 `strategy_analysis_release_hash` 必须对应本轮编排开始时冻结的已批准并已启用版本包。

服务必须：

```text
校验版本包身份、批准状态、启用状态与 release_hash；
读取版本包明确绑定的 AtomicSignalDefinition；
确认每个定义均为可选状态且 calculator 已注册；
确认原子信号依赖的 FeatureDefinition 已包含在同一版本包的特征切片中；
确认每个正式原子信号在同一版本包中恰好归属于一个正式领域定义；
按稳定顺序复算 definition_set_hash；
将复算结果与 expected_atomic_signal_definition_set_hash 比较。
```

缺少、多出、重复、跨版本包混用或指纹不一致时必须 blocked，且不得创建 AtomicSignalSet。

### 5.3 business_request_key

`business_request_key` 是调用方提供的不透明业务幂等键。

规则：

```text
AtomicSignal 只保存和比较该键；
不得解析其中的编排含义；
相同业务请求重复调用必须返回同一业务结果；
不得因任务重投创建第二份有效 AtomicSignalSet。
```

### 5.4 trace_id

`trace_id` 用于跨模块日志和审计关联。

它不是业务外键，不能替代：

```text
feature_set_id；
atomic_signal_set_id；
atomic_signal_definition_id；
used_feature_value_ids。
```

### 5.5 trigger_source

允许表达：

```text
orchestrated
manual
scheduled
recovery
test
```

触发来源不得改变计算规则和放行条件。

## 6. 输出合同

AtomicSignalService 必须返回结构化结果，至少包括：

```text
status
atomic_signal_set_id
atomic_signal_set_key
feature_set_id
strategy_analysis_release_id
strategy_analysis_release_hash
computed_count
valid_count
invalid_count
required_failed_count
failure_ratio
allows_domain_signal
error_code
error_message
trace_id
```

AtomicSignalService 允许返回的业务状态：

```text
created
blocked
failed
unknown
```

### 6.1 created

表示本次原子信号集合计算完成，或者幂等复用了已有完整结果。

created 可以包含少量无效的 optional AtomicSignalValue，但必须满足：

```text
required_failed_count = 0；
failure_ratio 未达到阻断阈值；
AtomicSignalSet 完整落库。
```

正式 AtomicSignalSet 只包含版本包选择的原子信号。集合达到 created 且至少存在一个有效正式信号时，`allows_domain_signal = true`；正式服务不得创建“只用于观察”的 AtomicSignalSet。

### 6.2 blocked

表示前置业务条件不满足，AtomicSignal 未被授权执行。

典型原因：

```text
FeatureSet 不存在；
FeatureSet 非 created；
FeatureSet.is_usable = false；
FeatureSet.allows_atomic_signal = false；
FeatureValue 集合不完整；
StrategyAnalysisRelease 不存在、未批准、未启用或指纹不一致；
版本包原子信号切片为空、缺失、多出或定义集指纹不一致；
版本包选择了不可用的 AtomicSignalDefinition；
定义集合存在不合法依赖或配置；
本轮 FeatureSet 不包含版本包原子信号所明确声明的特征；
正式原子信号未归属于一个且仅一个版本包领域定义。
```

blocked 必须：

```text
allows_domain_signal = false；
atomic_signal_set_id = null；
atomic_signal_set_key = null；
不创建 AtomicSignalSet 或 AtomicSignalValue；
不得进入 DomainSignal。
```

`blocked` 是前置条件校验结果，不是已持久化 AtomicSignalSet 的生命周期状态。重复请求必须重新读取当前前置事实，不得复用所谓“已持久化 blocked AtomicSignalSet”。

### 6.3 failed

表示已经进入计算，但存在明确的集合级失败。

典型原因：

```text
required AtomicSignalValue 失败；
失败比例达到阻断阈值；
calculator 缺失；
输出类型或范围非法；
证据结构不完整；
数据库事务明确回滚。
```

failed 必须：

```text
allows_domain_signal = false；
保存明确 error_code；
不得被 DomainSignal 消费。
```

### 6.4 unknown

表示无法安全确认本次结果是否完整提交。

unknown 必须：

```text
allows_domain_signal = false；
不得自动放行；
不得立即重复插入；
先按 business_request_key 和 atomic_signal_set_key 查证；
必要时写 AlertEvent。
```

## 7. AtomicSignalDefinition

AtomicSignalDefinition 是正式运行时原子信号字典。

建议字段：

```text
id
signal_code
display_name
description
category
default_direction
algorithm_name
algorithm_version
params
params_hash
definition_hash
status
enabled
is_required
depends_on_feature_codes
output_type
created_at_utc
updated_at_utc
```

### 7.1 signal_code

`signal_code` 必须稳定、可读，并明确表达判断对象和周期。

`signal_code` 是原子判断的稳定业务代码，不表示历史上只能存在一条 AtomicSignalDefinition。同一业务代码可以保留多个不可变的历史定义；同一 StrategyAnalysisRelease 内最多只能选择其中一个定义身份。

建议对以下完整身份建立唯一约束：

```text
signal_code
+ algorithm_name
+ algorithm_version
+ params_hash
```

升级算法或改变判断参数时必须新建定义，不得覆盖历史定义。旧定义可以继续被历史版本包引用；是否进入正式运行由 StrategyAnalysisRelease 决定。

例如：

```text
close_4h_above_sma_4h_20
close_4h_above_sma_4h_60
sma_4h_20_above_sma_4h_60
volume_4h_above_volume_sma_4h_20
close_1d_above_sma_1d_20
```

禁止使用交易动作语义：

```text
should_long
should_short
buy_signal
sell_signal
entry_signal
exit_order
stop_loss_signal
take_profit_signal
```

### 7.2 default_direction

允许值：

```text
bullish
bearish
neutral
none
```

含义：

```text
bullish = 条件成立时表达偏多倾向；
bearish = 条件成立时表达偏空倾向；
neutral = 条件成立时表达中性状态；
none    = 该定义没有方向语义。
```

direction 是市场倾向，不是买入、卖出、开多或开空指令。

### 7.3 algorithm_name 与 algorithm_version

`algorithm_name` 表示判断算法族，例如：

```text
feature_compare
threshold_check
range_breakout_check
feature_ratio_check
```

`algorithm_version` 表示该算法实现的不可变身份。

统一 CalculatorRegistry 中的注册键为：

```text
algorithm_name + algorithm_version
```

解析结果的 metadata.calculator_type 必须为 `atomic_signal`，相同注册键的计算行为不得发生不兼容变化。

### 7.4 params

`params` 保存条件参数，例如：

```json
{
  "left_feature_code": "sma_4h_20",
  "operator": "gt",
  "right_feature_code": "sma_4h_60"
}
```

params 必须完整表达：

```text
输入 feature_code；
运算符；
阈值或右侧 feature_code；
输出类型；
必要的边界处理。
```

不得在运行时根据市场结果动态改写 params。

### 7.5 params_hash

`params_hash` 建议使用：

```text
sha256(canonical_json(params))
```

规范化输入必须稳定，不得包含 trace_id、任务 ID 或运行时间。

### 7.6 definition_hash

`definition_hash` 至少覆盖：

```text
signal_code；
default_direction；
algorithm_name；
algorithm_version；
params_hash；
is_required；
depends_on_feature_codes；
output_type。
```

展示名称和说明文字可以不进入计算身份。

`enabled` 是算法库可用性开关，不进入不可变 definition_hash。它只决定定义能否被新版本包选择或继续执行，不代表定义会自动进入正式计算；正式集合身份由 StrategyAnalysisRelease 切片与 definition_set_hash 共同冻结。

### 7.7 status

允许的生命周期状态：

```text
draft
active
deprecated
retired
disabled
```

可被 StrategyAnalysisRelease 选择的定义必须满足：

```text
status = active；
enabled = true。
```

`status = active` 与 `enabled = true` 只表示该定义在算法库中可供选择，不表示自动进入正式 AtomicSignalSet。状态变化只影响后续执行，不得影响历史 AtomicSignalValue。

被历史结果引用的 AtomicSignalDefinition 不得物理删除。

### 7.8 enabled

`enabled` 控制定义是否可被新版本包选择、以及已启用版本包执行时该定义是否仍可用：

```text
enabled = true  → 可供版本包选择；被本轮冻结版本包选择后才参与正式计算；
enabled = false → 不得被新版本包选择；若当前正式版本包仍引用它，正式执行必须 blocked 并触发运维告警。
```

### 7.9 正式参与资格

AtomicSignalDefinition 不保存“观察”或“参与正式领域”的运行身份。

正式参与资格由完整版本包决定：

```text
定义被本轮 StrategyAnalysisRelease 原子信号切片选择；
定义为 active 且 enabled；
定义依赖的特征位于同一版本包特征切片；
定义在同一版本包中恰好归属于一个领域定义。
```

未满足这些条件的定义不得由正式 AtomicSignalService 运行。后台研究与回测应通过独立研究服务选择组合，不得借用正式服务的绕过参数。

### 7.10 is_required

`is_required` 表示该信号计算失败是否阻断整个 AtomicSignalSet。

规则：

```text
版本包内 required 信号失败 → AtomicSignalSet failed；
optional 信号失败 → 保存失败值并参与失败比例统计；
optional 失败比例达到阈值 → AtomicSignalSet failed。
```

`is_required` 不表示该条件必须成立。

必须区分：

```text
required 信号计算成功但条件不成立 = 正常业务结果；
required 信号无法计算 = 集合失败。
```

### 7.11 depends_on_feature_codes

必须列明该定义依赖的具体 feature_code。

例如：

```text
sma_4h_20_above_sma_4h_60
→ sma_4h_20
→ sma_4h_60
```

规则：

```text
依赖代码必须包含明确 timeframe；
不得用“某个 SMA”之类模糊语义；
依赖的 FeatureValue 必须属于同一个 FeatureSet；
FeatureValue.is_valid 必须为 true；
实际使用结果必须写入 used_feature_value_ids。
```

AtomicSignalDefinition 不保存某一轮 `feature_set_id`。定义阶段只固定自身依赖的 `feature_code`；运行阶段由 AtomicSignalSet 绑定本轮唯一 FeatureSet，再从其中解析实际 FeatureValue。

依赖治理规则：

```text
系统不根据原子信号自动推导、设计或创建特征；
每个特征依赖必须在开发阶段明确声明；
定义进入 active 前，必须确认每个依赖都有可用的 FeatureDefinition 和已注册 calculator；
依赖不完整时拒绝启用该原子信号；
本轮 FeatureSet 缺少已声明特征时，在计算前返回 blocked，不得临时创建特征或修改 FeatureSet；
特征存在但本轮值无效时，对应 AtomicSignalValue 按计算失败处理。
```

## 8. AtomicSignalSet

AtomicSignalSet 表示在一份 FeatureSet 上、使用一组冻结定义生成的原子信号集合。

建议字段：

```text
id
atomic_signal_set_key
business_request_key
feature_set_id
feature_set_key
strategy_analysis_release_id
strategy_analysis_release_hash
market_snapshot_id
exchange
market_type
symbol
analysis_close_time_utc
signal_schema_version
definition_set_hash
status
is_usable
allows_domain_signal
selected_definition_count
computed_count
valid_count
invalid_count
failed_count
required_failed_count
failure_ratio
failure_block_ratio
payload_summary
error_code
error_message
trace_id
trigger_source
started_at_utc
finished_at_utc
created_at_utc
updated_at_utc
```

### 8.1 粒度

正式结果粒度为：

```text
一份 FeatureSet
+ 一份冻结的 AtomicSignalDefinition 集合
+ 一个 signal_schema_version
→ 最多一份可消费 AtomicSignalSet
```

AtomicSignalSet 不按任务执行次数重复创建。

### 8.2 atomic_signal_set_key

`atomic_signal_set_key` 必须稳定生成。

建议输入：

```text
feature_set_id；
feature_set_key；
signal_schema_version；
definition_set_hash。
```

规则：

```text
必须具有数据库唯一约束；
相同输入身份只能生成一份正式结果；
并发调用不得创建两个 created 集合；
重复调用返回已有完整结果。
```

### 8.3 definition_set_hash

`definition_set_hash` 是本次冻结定义集合的指纹。

应按稳定顺序覆盖每个定义的：

```text
signal_code；
definition_hash；
is_required。
```

该集合必须严格等于本轮 StrategyAnalysisRelease 的原子信号切片。数据库中其他 active 或 enabled 定义不得加入本次 definition_set_hash。

`definition_set_hash` 不能替代 AtomicSignalValue 对 AtomicSignalDefinition 的逐条外键绑定。

### 8.4 signal_schema_version

`signal_schema_version` 表示 AtomicSignalSet 和 AtomicSignalValue 输出合同的结构身份。

它不替代：

```text
algorithm_version；
params_hash；
definition_hash；
definition_set_hash。
```

### 8.5 状态与放行字段

必须保持一致：

```text
created  → is_usable = true  → allows_domain_signal = true；
failed   → is_usable = false → allows_domain_signal = false；
unknown  → is_usable = false → allows_domain_signal = false。
```

`blocked` 不创建 AtomicSignalSet，因此不参与上述已持久化字段映射。

不得通过单个布尔值绕过状态检查。

### 8.6 failure_ratio

失败比例计算：

```text
failure_ratio = invalid_count / selected_definition_count
```

失败比例只统计本轮版本包选择的正式定义：

```text
selected_definition_count > 0；
每个被选定义无论 required 或 optional 都进入分母；
计算失败或结果无效的被选定义进入分子。
```

当版本包原子信号切片为空时返回 blocked，不得创建只用于观察的 AtomicSignalSet，也不得发生除零。

默认阻断阈值：

```text
ATOMIC_SIGNAL_FAILURE_BLOCK_RATIO = 0.3
```

`0.3` 是流程验证阶段的临时默认值，不是已由策略数据验证的永久阈值。后续必须根据回测和运行观测结果校准；调整后的实际值必须持续写入 AtomicSignalSet 供复盘。

规则：

```text
required_failed_count > 0 → failed；
failure_ratio >= failure_block_ratio → failed；
failure_ratio < failure_block_ratio 且 required_failed_count = 0 → 可继续汇总。
```

本次实际使用的 `failure_block_ratio` 必须写入 AtomicSignalSet，便于复盘。

### 8.7 payload_summary

`payload_summary` 只保存小型摘要，例如：

```text
定义数量；
有效数量；
失败数量；
版本包身份与定义集合指纹；
版本包选择数量；
failure_ratio；
definition_set_hash；
主要错误代码。
```

不得在 payload_summary 中复制全部 AtomicSignalValue 或 FeatureValue。

## 9. AtomicSignalValue

AtomicSignalValue 是 AtomicSignalSet 内某个 AtomicSignalDefinition 的计算结果。

建议字段：

```text
id
atomic_signal_set_id
atomic_signal_definition_id
signal_code
direction
strength
confidence
status
is_valid
definition_status
definition_enabled
algorithm_name
algorithm_version
params_hash
definition_hash
output_type
value_bool
value_decimal
value_text
value_json
evidence_items
evidence_text_zh
used_feature_codes
used_feature_value_ids
error_code
error_message
calculated_at_utc
latency_ms
created_at_utc
```

### 9.1 定义绑定

每条 AtomicSignalValue 必须绑定具体 AtomicSignalDefinition。

同时冗余保存：

```text
signal_code；
algorithm_name；
algorithm_version；
params_hash；
definition_hash。
```

冗余字段用于历史可读性，不能替代真实外键。

### 9.2 status

AtomicSignalValue 允许的状态：

```text
created
failed
```

条件正常不成立仍然是：

```text
status = created；
is_valid = true。
```

不得把“条件不成立”记录为 failed。

### 9.3 direction

允许值：

```text
bullish
bearish
neutral
none
```

`direction` 只表达该原子判断的市场倾向。

对布尔条件，默认方向规则为：

```text
条件成立 → direction = AtomicSignalDefinition.default_direction；
条件不成立 → direction = neutral；
计算失败 → direction = neutral 且 is_valid = false。
```

“偏多条件不成立”只表示本条偏多证据缺席，不得自动解释为偏空。需要表达相反条件时，必须定义独立原子信号。

禁止解释为：

```text
开多；
开空；
买入；
卖出；
平仓；
下单。
```

### 9.4 strength

`strength` 范围：

```text
0 <= strength <= 1
```

布尔条件的标准行为可以是：

```text
条件成立 → strength = 1；
条件不成立 → strength = 0；
计算失败 → strength = 0 且 is_valid = false。
```

非布尔强度必须由对应 calculator 明确定义归一化公式。

### 9.5 confidence

`confidence` 为可空字段。非空时范围为：

```text
0 <= confidence <= 1
```

规则：

```text
calculator 有明确、可复现的置信度定义 → 输出 0 到 1；
calculator 没有可验证的置信度定义 → confidence = null；
计算失败或输入无效 → confidence = null。
```

输入完整、计算成功和 `is_valid = true` 只说明计算过程有效，不自动等于 `confidence = 1`。任何非空 confidence 都必须有明确、可复现的公式和业务含义，不能由主观文字产生。

DomainSignal 不得把 AtomicSignalValue.confidence 当作默认权重，也不得在没有领域 calculator 明确合同的情况下与 strength 相乘。原子 confidence 主要用于审计和算法评估，避免在后续层重复加权。

### 9.6 evidence_items

`evidence_items` 是机器可读的结构化证据，必须保存。

示例：

```json
{
  "left_feature_code": "sma_4h_20",
  "left_feature_value_id": 101,
  "left_value": "102500.25",
  "operator": "gt",
  "right_feature_code": "sma_4h_60",
  "right_feature_value_id": 102,
  "right_value": "101800.10",
  "result": true
}
```

要求：

```text
Decimal 使用字符串；
记录实际使用的 FeatureValue ID；
记录实际值和运算符；
记录判断结果；
不得保存完整 Kline；
不得保存不可控大 JSON。
```

### 9.7 evidence_text_zh

`evidence_text_zh` 是面向用户、审计和复盘的中文证据说明，必须保存。

正常示例：

```text
4h SMA20 为 102500.25，高于 4h SMA60 的 101800.10，因此该均线比较条件成立。
```

失败示例：

```text
原子信号计算失败：缺少有效的 sma_4h_60 特征值，无法完成均线比较。
```

evidence_text_zh 禁止包含：

```text
买入建议；
卖出建议；
开多建议；
开空建议；
止损建议；
止盈建议；
仓位建议；
杠杆建议；
下单指令。
```

### 9.8 used_feature_codes 与 used_feature_value_ids

必须记录实际参与计算的 FeatureValue。

追溯链为：

```text
AtomicSignalValue
→ used_feature_value_ids
→ FeatureValue
→ FeatureDefinition
→ FeatureSet
→ MarketSnapshot
```

校验要求：

```text
所有 FeatureValue 必须属于 AtomicSignalSet 绑定的同一 FeatureSet；
used_feature_codes 与 FeatureValue.feature_code 一致；
使用前 FeatureValue.is_valid = true；
不得只记录定义中声明的依赖而不记录实际使用值。
```

## 10. Calculator 架构

AtomicSignal calculator 必须注册到 [StrategyCalculator 公共合同](strategy_calculator.md) 定义的统一 CalculatorRegistry，不建立模块私有 Registry。

所有 AtomicSignal calculator 必须遵守 [StrategyCalculator 公共合同](strategy_calculator.md)。本文件只定义 AtomicSignal 特有的输入、输出与判断边界，不得削弱公共合同规定的纯计算、确定性、精确版本选择和副作用隔离要求。

注册键为：

```text
algorithm_name + algorithm_version
```

Calculator metadata 必须遵守 [StrategyCalculator 公共合同](strategy_calculator.md)，声明 `calculator_type = atomic_signal`、`algorithm_requirement_document_path` 和 `implementation_document_path`。AtomicSignalService 必须校验解析结果类型，禁止把其他模块 calculator 当作原子信号实现。

允许的基础算法族包括：

```text
feature_compare
threshold_check
range_breakout_check
feature_ratio_check
```

当前必须具备 `feature_compare`，用于两个 FeatureValue 或 FeatureValue 与常量之间的明确比较。

Calculator 只负责纯判断逻辑。

Calculator 不得：

```text
读取或写入数据库；
访问 Redis；
请求 Binance；
读取 Kline；
调用 FeatureLayerService；
调用其他 AtomicSignal；
创建 AtomicSignalSet；
创建 AtomicSignalValue；
生成 StrategySignal；
调用 DecisionSnapshot；
读取账户、价格快照或订单；
调用 RiskCheck、ExecutionPreparation 或 Execution。
```

## 11. CalculatorRegistry

规则：

```text
被本轮冻结 StrategyAnalysisRelease 选择的 AtomicSignalDefinition 必须为 active、enabled 且有对应 calculator；
重复注册同一组合必须失败；
未知组合不得回退到相近算法；
不得在 AtomicSignalService 中维护大型 if / elif 分发；
不得把策略聚合算法注册为 AtomicSignal calculator。
```

Calculator 输入：

```text
AtomicSignalDefinition.params；
该定义实际依赖的 FeatureValue 映射。
```

Calculator 输出：

```text
output value；
direction；
strength；
confidence；
evidence_items 所需数据；
可判定的计算错误。
```

其中 confidence 允许为 null；CalculatorRegistry 和 AtomicSignalService 不得把成功结果自动补成 1。

## 12. 默认定义与运行时定义

必须区分：

```text
default_atomic_signal_definitions.py = 受代码管理的默认模板；
AtomicSignalDefinition 表            = 可供组合选择的算法定义库；
StrategyAnalysisRelease 原子信号切片 = 正式运行时集合。
```

正式计算只读取本轮冻结版本包切片中同时满足以下条件的定义：

```text
status = active；
enabled = true。
```

AtomicSignalService 不得：

```text
直接读取默认模板参与正式计算；
把默认模板与数据库定义求合集；
把版本包切片与数据库其他 active 定义求合集；
因模板仍存在而恢复 retired 或 disabled 定义；
通过运行参数临时增删版本包定义。
```

## 13. seed_atomic_signal_definitions

必须提供幂等初始化入口：

```bash
python manage.py seed_atomic_signal_definitions
```

命令负责：

```text
读取默认模板；
规范化 params；
计算 params_hash；
计算 definition_hash；
按完整定义身份写入 AtomicSignalDefinition；
输出初始化摘要。
```

命令不得：

```text
生成 AtomicSignalSet；
生成 AtomicSignalValue；
调用 AtomicSignalService；
请求 Binance；
修改 FeatureSet 或 FeatureValue；
恢复 retired 或 disabled 定义；
覆盖人工 enabled 配置；
覆盖已经使用过的身份字段。
```

允许更新的内容仅限不改变计算身份的展示元数据，例如：

```text
display_name；
description；
category。
```

## 14. 当前默认定义范围

当前流程验证阶段的默认模板只初始化一个原子信号定义：

```text
sma_4h_20_above_sma_4h_60
```

该信号的算法合同为：

```text
业务含义：4h SMA20 高于 4h SMA60；
特征依赖：sma_4h_20、sma_4h_60；
判断算法：feature_compare；
运算符：gt；
输出类型：bool；
条件成立方向：bullish；
条件不成立方向：neutral；
计算成功且条件成立：strength = 1；
计算成功且条件不成立：strength = 0；
confidence = null；
is_required = true；
enabled = true。
```

该信号可被版本包选入，用于贯通 FeatureLayer、AtomicSignal、DomainSignal、MarketRegime、StrategyRouting 与 StrategySignal 的完整流程。默认模板只把它登记到算法定义库，不自动授予正式运行资格；是否参与正式链路取决于已批准并启用的 StrategyAnalysisRelease。它不因被选入版本包而获得真实交易权限，真实交易仍必须经过完整交易链路，并在进入 OrderPlan 前通过 `.env` 与 MySQL 运行权限检查。

该定义只是市场条件判断，不是 StrategySignal。

范围突破类信号只有在其依赖的区间特征明确排除当前判断 Kline、且不存在前视偏差时才允许被版本包选择。不得使用包含当前 Kline 的区间高低值制造逻辑上无法成立或带有口径歧义的突破判断。

默认定义必须：

```text
声明 default_direction；
声明具体 FeatureValue 依赖；
声明算法与参数身份；
声明是否 required；
具有中文计算逻辑说明；
不包含交易动作。
```

## 15. 特征与周期绑定

AtomicSignalDefinition 必须明确每个输入特征的周期。

规则：

```text
sma_4h_20 与 sma_1d_20 是两个不同特征；
不同周期不得隐式替换；
同一 AtomicSignalValue 的输入必须来自同一 FeatureSet；
不得根据缺失情况自动改用其他周期；
不得把 PriceSnapshot 的 mark price 当作 FeatureValue。
```

AtomicSignal 只使用 FeatureLayer 已持久化的特征事实，不访问行情价格接口。

## 16. AtomicSignalService 主流程

标准流程：

```text
1. 接收 feature_set_id、StrategyAnalysisRelease 身份、business_request_key、trace_id、trigger_source；
2. 校验请求字段；
3. 按 business_request_key 查询已有结果；
4. 读取 FeatureSet；
5. 校验 status、is_usable 和 allows_atomic_signal；
6. 读取 FeatureValue 并构建 feature_code → FeatureValue 映射；
7. 校验 StrategyAnalysisRelease 身份、批准状态、启用状态和 release_hash；
8. 读取版本包原子信号切片，不追加其他 active 定义；
9. 校验每个定义的 active、enabled、calculator、特征依赖和唯一领域归属；
10. 校验版本包特征依赖与本轮 FeatureSet 覆盖；
11. 缺项、多项、依赖未覆盖或指纹不一致时返回 blocked，不创建 AtomicSignalSet；
12. 冻结定义集合并计算 definition_set_hash；
13. 生成 atomic_signal_set_key；
14. 按 atomic_signal_set_key 查询已有完整结果；
15. 逐项执行 calculator；
16. 单项失败时形成 failed AtomicSignalValue，并继续其他 optional 定义；
17. 基于全部版本包定义汇总 required_failed_count 和 failure_ratio；
18. 决定集合状态和 allows_domain_signal；
19. 在数据库事务中写 AtomicSignalSet 与 AtomicSignalValue；
20. 写必要 AlertEvent；
21. 返回结构化业务结果。
```

计算期间冻结的定义集合不得重新读取并替换。

## 17. 单项失败处理

单个 AtomicSignalValue 失败时必须写入：

```text
status = failed；
is_valid = false；
direction = neutral；
strength = 0；
confidence = null；
error_code 非空；
error_message 非空；
evidence_text_zh 非空。
```

单项失败不得：

```text
伪装为正常 neutral；
伪装为条件不成立；
省略证据；
中断所有其他 optional 定义计算；
让 DomainSignal 使用该值。
```

单项失败应写：

```text
alert_type = atomic_signal_failed；
severity = warning。
```

## 18. 集合失败处理

以下任一条件成立时 AtomicSignalSet 必须 failed：

```text
required_failed_count > 0；
failure_ratio >= failure_block_ratio；
定义集合身份不完整；
FeatureValue 来源混用；
输出范围或证据合同不满足；
数据库事务明确失败。
```

集合失败必须：

```text
is_usable = false；
allows_domain_signal = false；
写 atomic_signal_set_failed AlertEvent；
不得进入 DomainSignal。
```

## 19. 写库与事务

AtomicSignalSet 与 AtomicSignalValue 必须在同一个数据库事务中正式写入。

要求：

```text
使用 transaction.atomic() 或等价 Django 事务；
AtomicSignalValue 使用 bulk_create 或等价批量写入；
数据库唯一约束保护 business_request_key 和 atomic_signal_set_key；
不得出现 AtomicSignalSet created 但 Value 只写一部分；
不得在数据库长事务中执行外部请求；
不得在事务中等待其他模块。
```

计算可先在内存中完成，随后进入短事务落库。

## 20. 幂等与并发

### 20.1 重复调用

相同 `business_request_key` 重复调用：

```text
已有 created → 返回已有 AtomicSignalSet；
已有 failed → 返回已有失败结果，受控恢复入口可重新核验；
已有 unknown → 先查证，不直接再次计算。
上一次返回 blocked → 重新读取 FeatureSet、FeatureValue 和定义配置等前置事实。
```

### 20.2 相同输入身份

即使 business_request_key 不同，只要以下身份相同：

```text
feature_set_id；
signal_schema_version；
definition_set_hash。
```

也不得生成两份相同的正式 AtomicSignalSet。

### 20.3 并发冲突

并发安全依靠：

```text
数据库唯一约束；
原子创建；
必要的短期 Redis 锁。
```

Redis 锁失效不能破坏数据库唯一性。

## 21. unknown 与恢复

数据库返回结果不明确时：

```text
不得假设写入失败；
不得立即重复插入；
按 business_request_key 和 atomic_signal_set_key 查证；
核对 Value 数量、definition_set_hash 和 required 结果；
无法确认时保持 unknown 并告警。
```

受控恢复必须检查：

```text
FeatureSet 是否仍然可用；
AtomicSignalSet 是否存在；
AtomicSignalValue 数量是否与冻结集合一致；
每条 Value 是否绑定正确 Definition；
required 信号是否全部有效；
failure_ratio 是否可复算。
```

恢复结果：

```text
完整且一致 → 返回 created；
没有结果且前置条件仍满足 → 使用相同幂等身份执行；
存在不完整或冲突结果 → failed 并告警；
无法判断 → unknown，禁止放行。
```

不得覆盖已经 created 的 AtomicSignalSet 重新计算。

## 22. DomainSignal 消费合同

DomainSignal 只允许消费：

```text
AtomicSignalSet.status = created；
AtomicSignalSet.is_usable = true；
AtomicSignalSet.allows_domain_signal = true；
AtomicSignalValue.status = created；
AtomicSignalValue.is_valid = true；
AtomicSignalValue.definition_status = active；
AtomicSignalValue.definition_enabled = true；
AtomicSignalValue 所属 Definition 位于同一 StrategyAnalysisRelease 原子信号切片。
```

DomainSignal 必须使用 AtomicSignalValue 在生成时冻结的定义状态与开关，不得通过重新读取 AtomicSignalDefinition 的当前状态改变既有结果的含义。后续配置变化只影响新生成的 AtomicSignalSet；如需终止已开始的本轮流程，应由编排层按照明确的业务结果处理。

DomainSignalDefinition 必须通过版本包内的依赖关系明确声明自己允许、必须读取哪些原子信号。每个正式 AtomicSignalDefinition 在同一版本包中必须且只能归属于一个领域，DomainSignal 不得读取其所属领域之外的原子信号。

未被正式版本包选择的定义与任意研究组合，只允许由后台研究与回测服务运行并写入隔离的研究结果，不得写入正式 AtomicSignalSet，也不得进入正式 DomainSignal、MarketRegime、StrategyRouting 或 StrategySignal。

StrategySignal 不得直接消费 AtomicSignalSet 或 AtomicSignalValue。正式策略输入必须先经过 DomainSignal、MarketRegime 和 StrategyRouting 的既定链路。

## 23. 独立评估

每个 AtomicSignalDefinition 必须支持按自身身份独立统计。

可统计：

```text
条件成立频率；
计算成功率；
失败率；
稳定性；
与后续策略结果的关系；
与收益结果的关系；
与其他原子信号的相关性；
不同研究组合中的表现。
```

评估不得反向修改已经生成的 AtomicSignalValue。

任何用于正式策略的定义或组合变化，都必须形成新的 StrategyAnalysisRelease，完成验证、人工批准和单独启用后才能进入正式运行。

## 24. 与编排层的关系

AtomicSignal 是业务模块，不承担编排职责。

业务对象追溯链：

```text
AtomicSignalValue
→ AtomicSignalSet
→ FeatureSet
→ MarketSnapshot
```

AtomicSignal 业务表不得保存或查询：

```text
orchestration_run_id；
orchestration_step_run_id；
编排对象关联表。
```

编排流程由 `AtomicSignalStepAdapter` 负责：

```text
接收 feature_set_id 和 business_request_key；
调用 AtomicSignalService；
理解 AtomicSignal 原始业务结果；
把 created / blocked / failed / unknown 映射为统一状态和 flow_action；
向编排层返回 atomic_signal_set_id 及对象引用。
```

编排层可以登记 AtomicSignalSet 根对象，并由根对象展开 AtomicSignalValue；该关联不替代业务外键。

## 25. AlertEvent

成功且无单项失败时默认只写结构化日志，不强制写 AlertEvent。

应写的事件：

```text
atomic_signal_blocked
atomic_signal_failed
atomic_signal_set_failed
atomic_signal_set_unknown
atomic_signal_definition_invalid
atomic_signal_calculator_missing
```

规则：

```text
AtomicSignal 只写 AlertEvent；
不得直接调用 Hermes；
不得直接调用 Notifications 发送消息；
AlertEvent 不触发交易；
告警失败不能把 failed 结果改为 created。
```

## 26. 配置规则

允许配置：

```text
SIGNAL_SCHEMA_VERSION；
ATOMIC_SIGNAL_FAILURE_BLOCK_RATIO；
单次允许计算的最大定义数量；
短期幂等锁 TTL；
Decimal 精度和统一舍入规则。
```

不允许通过 env 动态改变：

```text
AtomicSignalDefinition.params；
Definition 生命周期状态；
enabled；
StrategyAnalysisRelease 原子信号切片；
具体算法公式；
calculator 注册映射。
```

正式业务定义由 MySQL 中的 AtomicSignalDefinition、StrategyAnalysisRelease 与受版本管理的 calculator 共同表达。环境变量不得选择正式算法组合。

所有环境配置进入 `.env.example`，并带中文注释。

## 27. 服务、任务与命令边界

### 27.1 service

核心业务逻辑放在 service/domain 层。

AtomicSignalService 负责：

```text
输入校验；
FeatureSet 放行检查；
版本包与定义切片校验；
定义冻结；
特征依赖解析；
calculator 调度；
失败隔离；
集合汇总；
事务落库；
幂等返回。
```

### 27.2 Celery task

Celery task 只负责：

```text
接收参数；
传递 trace_id 和 trigger_source；
调用 AtomicSignalService；
返回可序列化摘要。
```

task 不得实现判断算法或直接写业务对象。

### 27.3 management command

手动构建入口：

```bash
python manage.py build_atomic_signals --feature-set-id <id> --strategy-analysis-release-id <id> --strategy-analysis-release-hash <hash> --business-request-key <key> --trigger-source manual --trace-id <id>
```

command 只负责解析参数、调用 service 和输出结果。

至少输出：

```text
atomic_signal_set_id；
atomic_signal_set_key；
strategy_analysis_release_id；
strategy_analysis_release_hash；
status；
computed_count；
valid_count；
invalid_count；
failure_ratio；
allows_domain_signal。
```

## 28. 算法需求文档与 implementation 实现记录

每个正式 calculator 和默认 AtomicSignalDefinition 都必须同时具备：

```text
算法需求文档；
implementation 实现记录。
```

算法需求文档负责定义原子信号的输入特征、运算符、阈值、输出语义、边界和验证要求，应放在 requirements 下的对应原子信号算法目录，具体目录由后续原子信号算法需求文件统一确定，例如：

```text
docs/requirements/<原子信号算法模块>/<atomic_signal_or_algorithm>.md
```

implementation 实现记录负责记录代码落地位置、calculator、DTO、测试入口和实现差异，统一目录：

```text
docs/implementation/atomic_signal/
```

文件粒度：

```text
一个 algorithm_name + algorithm_version 对应一个独立 Markdown 文件；
文件名使用 <algorithm_name>__<algorithm_version>.md；
不同算法版本不得共用同一个文件；
同一算法版本不得拆成互相冲突的多份实现记录。
```

示例：

```text
feature_compare__1.0.0.md
threshold_check__1.0.0.md
range_breakout_check__1.0.0.md
```

至少说明：

```text
信号名称；
信号代码；
default_direction；
输入 FeatureValue；
算法与参数身份；
具体运算符和公式；
strength 计算，以及 confidence 非空时的含义与计算；
条件成立与不成立的输出；
失败条件；
证据格式；
交易语义边界。
```

算法需求文档和 implementation 实现记录均不得把 AtomicSignal 解释成策略、目标仓位或交易建议。

AtomicSignalDefinition 的具体输入、运算符和阈值继续由 `params / params_hash / definition_hash` 表达；多个定义复用同一 calculator 算法版本时，共用对应算法需求文档和 implementation 实现记录，并在算法需求文档中说明适用的参数合同。

## 29. 时间与精度

所有时间统一使用 UTC。

规则：

```text
analysis_close_time_utc 从 FeatureSet 继承；
calculated_at_utc 使用 UTC；
不得用本地时区参与信号判断；
不得用运行时当前时间改变固定输入语义；
Decimal 证据写入 JSON 时转换为字符串；
不得使用不可控 float 保存正式数值。
```

同一 FeatureSet、同一定义集合和同一算法身份必须得到确定性一致结果。

## 30. 日志与审计

结构化日志至少包含：

```text
trace_id；
trigger_source；
business_request_key；
feature_set_id；
atomic_signal_set_id；
atomic_signal_set_key；
definition_set_hash；
status；
computed_count；
valid_count；
invalid_count；
required_failed_count；
failure_ratio；
error_code；
latency_ms。
```

日志不得包含：

```text
完整 FeatureValue 集合；
完整 evidence_items 集合；
完整 Kline；
密钥或 Token；
不可控长 JSON。
```

## 31. dry-run 与 confirm-write

AtomicSignal 可以支持 dry-run。

dry-run 必须：

```text
读取明确的 FeatureSet；
执行与正式模式相同的放行、依赖和 calculator 校验；
不写 AtomicSignalSet；
不写 AtomicSignalValue；
不写正式业务 AlertEvent；
不允许 DomainSignal 消费内存结果；
明确返回 persisted = false。
```

如提供 confirm-write：

```text
只控制是否落库；
不得改变失败比例；
不得绕过 required 信号失败；
不得把 blocked、failed 或 unknown 强制写成 created。
```

## 32. 测试要求

至少覆盖：

```text
1. AtomicSignalDefinition 可以创建。
2. params_hash 对相同规范化参数稳定。
3. definition_hash 对相同定义稳定。
4. 本轮冻结版本包选择的 active 且 enabled 定义参与正式计算。
5. 未被本轮冻结版本包选择的 active 且 enabled 定义不参与正式计算。
6. draft、deprecated、retired、disabled 或 enabled = false 的被选定义会阻断正式计算。
7. 版本包不存在、未批准、未启用或 release_hash 不一致时 blocked。
8. 版本包原子信号切片缺项、多项、重复或 definition_set_hash 不一致时 blocked。
9. 生命周期变化不影响历史 AtomicSignalValue。
10. CalculatorRegistry 按算法完整身份查找实现。
11. 未注册 calculator 时不生成可消费集合。
12. 重复 calculator 注册被拒绝。
13. AtomicSignal 之间不互相调用。
14. AtomicSignal 不读取 Kline。
15. AtomicSignal 不重新计算 FeatureValue。
16. AtomicSignal 只读取明确传入的 feature_set_id。
17. FeatureSet 不存在时 blocked。
18. FeatureSet 非 created 时 blocked。
19. FeatureSet.is_usable = false 时 blocked。
20. FeatureSet.allows_atomic_signal = false 时 blocked。
21. 不同 FeatureSet 的 FeatureValue 不能混用。
22. 定义的特征依赖未声明或无可用 FeatureDefinition 时拒绝启用。
23. 本轮 FeatureSet 缺少已声明特征时 blocked 且不创建 AtomicSignalSet；特征存在但值无效时对应信号 failed。
24. 不同 timeframe 不得隐式替换。
25. AtomicSignalSet 绑定 FeatureSet。
26. AtomicSignalValue 绑定 AtomicSignalDefinition。
27. AtomicSignalValue 记录实际 used_feature_value_ids。
28. used_feature_value_ids 全部属于同一 FeatureSet。
29. evidence_items 必填且可复算判断结果。
30. evidence_text_zh 必填。
31. evidence_text_zh 不包含交易建议。
32. 正常条件不成立为 created、is_valid = true 且 direction = neutral，不自动解释为相反方向。
33. 单项计算失败为 failed 且 is_valid = false。
34. 失败 neutral 与正常 neutral 可以区分。
35. strength 范围为 0 到 1。
36. confidence 允许为 null，非空时范围为 0 到 1 且公式可复现。
37. required 信号计算失败会阻断集合。
38. required 信号条件不成立不会被误判为计算失败。
39. optional 单项失败不会立即中断其他 optional 计算。
40. failure_ratio 统计版本包选择的全部正式原子信号。
41. failure_ratio 小于阈值且无 required 失败时可 created。
42. failure_ratio 等于或大于阈值时 failed。
43. selected_definition_count 为零时 blocked 且不创建 AtomicSignalSet。
44. AtomicSignalSet created 且 allows_domain_signal = true 才允许 DomainSignal 消费。
45. blocked、failed、unknown 均不允许 DomainSignal 消费。
46. 未被本轮冻结版本包选择的定义不得写入正式 AtomicSignalSet 或 AtomicSignalValue。
47. DomainSignal 只读取同一版本包为该领域明确绑定的 AtomicSignalValue。
48. 计算成功不会自动把 confidence 设为 1。
49. DomainSignal 不把 AtomicSignal confidence 当作默认权重重复乘算。
50. definition_set_hash 对相同定义集合稳定。
51. atomic_signal_set_key 对相同输入身份稳定。
52. 相同 business_request_key 重复执行复用已持久化结果；上次 blocked 则重新校验前置事实。
53. 并发执行只生成一份正式 AtomicSignalSet。
54. AtomicSignalSet 与 Value 在同一事务写入。
55. 事务失败不会留下 created 半成品集合。
56. unknown 不会自动重新插入或放行下游。
57. seed 命令幂等。
58. seed 不恢复 retired 或 disabled 定义。
59. seed 不覆盖 enabled，也不修改任何 StrategyAnalysisRelease。
60. seed 不生成 AtomicSignalSet。
61. dry-run 不写业务对象或 AlertEvent。
62. AtomicSignal 不生成 StrategySignal。
63. AtomicSignal 不生成 DecisionSnapshot。
64. AtomicSignal 不读取账户或 PriceSnapshot。
65. AtomicSignal 不请求 Binance。
66. AtomicSignal 不调用 BinanceGateway。
67. AtomicSignal 不调用大模型。
68. AtomicSignal 不保存或查询编排 ID。
69. adapter 显式映射原始业务结果。
70. 全部业务时间使用 UTC。
71. 默认模板只启用 sma_4h_20_above_sma_4h_60。
72. 默认信号精确依赖 sma_4h_20 和 sma_4h_60，条件成立为 bullish，不成立为 neutral。
73. 默认信号只有被本轮冻结的已批准版本包选择后才能进入 DomainSignal，且不因此获得真实交易权限。
74. 定义开关在结果生成后变化，不会反向改变已有 AtomicSignalValue 的冻结含义。
75. 同一 signal_code 可保留多个历史定义，同一 StrategyAnalysisRelease 最多选择其中一个身份。
76. 每个版本包正式原子信号恰好归属于一个版本包领域定义。
77. 后台研究服务可组合未被正式版本包选择的定义，但结果与正式 AtomicSignalSet 隔离。
78. 正式服务不存在 allow_candidate、ignore_approval 或 use_latest 等绕过参数。
```

## 33. 验收方式

实现完成后至少执行：

```bash
pytest tests/atomic_signals/
python manage.py seed_atomic_signal_definitions
python manage.py build_atomic_signals --feature-set-id <id> --strategy-analysis-release-id <id> --strategy-analysis-release-hash <hash> --business-request-key <key> --trigger-source manual --trace-id <id>
```

数据库检查：

```text
AtomicSignalDefinition 的状态、开关和 hash 完整；
StrategyAnalysisRelease 身份、原子信号切片和依赖关系完整；
AtomicSignalSet 正确绑定 FeatureSet；
definition_set_hash 可复算；
Value 数量与冻结定义集合一致；
每条 Value 绑定具体 Definition；
used_feature_value_ids 可追溯到同一 FeatureSet；
evidence_items 与 evidence_text_zh 完整；
失败比例可复算；
created 时 allows_domain_signal = true，failed 或 unknown 时为 false；
重复执行没有产生第二份正式集合；
没有保存任何编排 ID。
```

通过标准：

```text
相同 FeatureSet 和定义集合得到唯一、确定性结果；
单项失败与正常条件不成立严格区分；
未被版本包选择的算法与后台研究结果不会进入正式领域判断；
大规模失败或 required 失败会阻断 DomainSignal 及其后续链路；
证据链能够回查到实际 FeatureValue；
没有外部网络访问；
没有交易副作用。
```

## 34. 模块影响声明

```text
读写 MySQL：是，读取 FeatureSet、FeatureValue、AtomicSignalDefinition，写 AtomicSignalSet、AtomicSignalValue 和必要 AlertEvent；
访问 Redis：可选，仅用于短期锁、幂等和缓存，不保存正式事实；
访问 Binance：否；
调用 BinanceGateway：否；
发送 Hermes：否；
调用大模型：否；
涉及真实交易：否；
涉及 FeatureLayer：只消费 FeatureSet / FeatureValue；
涉及 AtomicSignal：是，本模块自身；
涉及 DomainSignal：只提供正式输入，不生成 DomainSignal；
涉及 MarketRegime / StrategyRouting：否；
涉及 StrategySignal：不直接提供输入，不生成 StrategySignal；
涉及 DecisionSnapshot：否；
涉及 Binance Account Sync：否；
涉及 PriceSnapshot：否；
涉及 OrderPlan / CandidateOrderIntent：否；
涉及 RiskCheck / ApprovedOrderIntent：否；
涉及 ExecutionPreparation / Execution：否；
涉及 OrderStatusSync / FillSync / ReviewDataset：否；
写 AlertEvent：单项失败、集合失败、阻断或未知状态；
dry-run：可计算但不写正式业务对象；
confirm-write：如提供，只控制落库，不改变放行标准。
```

## 35. 明确禁止

AtomicSignal 禁止：

```text
绕过 FeatureSet；
读取 Kline；
请求 Binance REST 或 WebSocket；
调用 BinanceGateway；
调用 FeatureLayerService 补算特征；
重新计算 FeatureValue；
混用不同 FeatureSet 的值；
依赖其他 AtomicSignal；
聚合原子信号形成策略结论；
输出固定权重或优先级；
输出 final_score 或 strategy_score；
把失败伪装成正常 neutral；
让未被本轮冻结版本包选择的定义进入正式策略；
通过正式服务参数绕过版本包批准或临时增删定义；
把 direction 解释为下单指令；
输出 entry_price；
输出 stop_loss 或 take_profit；
输出 target_position；
输出 position_size；
输出 leverage；
生成 CandidateOrderIntent；
审批 ApprovedOrderIntent；
执行 ExecutionPreparation；
调用 Execution 或提交真实订单；
直接发送 Hermes；
调用大模型参与实时判断；
保存或查询编排 ID；
让编排对象关联替代业务外键。
```

## 36. 最终验收标准

AtomicSignal 验收通过必须满足：

```text
FeatureSet 是唯一正式输入边界；
AtomicSignalSet 与 FeatureSet 形成明确业务外键；
AtomicSignalValue 逐条绑定 AtomicSignalDefinition；
每个定义只表达一个原子判断；
AtomicSignal 之间平权且互不调用；
算法、参数和定义身份可追溯；
正式运行只读取本轮已冻结 StrategyAnalysisRelease 原子信号切片中的 active 且 enabled 定义；
默认模板只用于幂等初始化；
AtomicSignalDefinition 在定义阶段声明 feature_code 依赖，AtomicSignalSet 在运行阶段绑定本轮唯一 FeatureSet；
系统不自动推导或创建特征，依赖不完整时拒绝启用或在计算前 blocked；
enabled 只表达算法库可用性，不自动授予正式运行资格；
未被正式版本包选择的定义与后台研究结果不会进入正式领域判断；
失败比例只依据版本包选择的正式原子信号计算；
evidence_items 与 evidence_text_zh 完整；
实际 FeatureValue 证据可以独立追溯；
失败 neutral 与正常 neutral 明确区分；
单项 optional 失败可以隔离；
required 失败或失败比例达到阈值会阻断下游；
流程验证阶段的失败比例阈值暂定为 30%，后续必须根据回测数据校准；
只有 created 且 allows_domain_signal = true 的集合可被 DomainSignal 消费；
默认模板只登记 sma_4h_20_above_sma_4h_60；它只有被版本包选择后才贯通后续流程，且不授予真实交易权限；
不输出权重、策略结论、目标仓位或订单动作；
业务外键独立于编排关联；
MySQL 保存正式事实，Redis 只承担辅助能力；
全部时间使用 UTC；
不请求 Binance；
不调用大模型；
不涉及真实交易；
不违反项目交易红线。
```

AtomicSignal 的最终定位是：

```text
把一份可用 FeatureSet 转换为一组独立、可解释、可观察、可供 DomainSignal 按领域选择和聚合的原子市场判断事实。
```
