# FeatureLayer 需求说明

## 1. 模块定位

FeatureLayer 是 `MarketSnapshot` 之后、`AtomicSignal` 之前的基础特征计算层。

它负责把一个已经固定并通过质量授权的市场证据窗口，转换为稳定、可复现、可追溯的中性数值特征。

正式链路为：

```text
Kline
→ DataQualityResult
→ MarketSnapshot
→ FeatureSet / FeatureValue
→ AtomicSignalSet / AtomicSignalValue
→ DomainSignalSet / DomainSignalValue
→ MarketRegimeSnapshot
→ StrategyRouteDecision
→ StrategySignal
→ StrategySignalQualityResult
→ DecisionSnapshot
```

FeatureLayer 负责：

```text
接收明确的 market_snapshot_id；
校验 MarketSnapshot 是否允许特征层消费；
按照 MarketSnapshot 固定的窗口索引读取 4h 与 1d Kline；
冻结本次使用的 FeatureDefinition 集合；
按已注册的算法和参数计算基础特征；
生成 FeatureSet；
生成逐项 FeatureValue；
保存算法、参数、定义和输入窗口的追溯信息；
向 AtomicSignal 提供唯一、稳定的特征事实输入。
```

FeatureLayer 不负责：

```text
请求 Binance；
采集、回补或修复 Kline；
重新执行 DataQuality；
创建或修改 MarketSnapshot；
比较特征并判断条件是否成立；
判断 bullish、bearish、long 或 short；
生成 AtomicSignal；
生成 DomainSignal；
判断 MarketRegime；
选择 StrategyRouteDecision；
生成 StrategySignal；
生成 DecisionSnapshot；
读取账户、持仓或订单；
生成订单意图；
风控审批；
交易执行；
调用 DeepSeek 或其他大模型。
```

## 2. 业务目标

FeatureLayer 必须解决以下问题：

```text
不同模块重复计算相同指标；
相同特征在不同模块中使用不同公式；
算法或参数变化后无法还原历史结果；
策略、实盘和回测使用的特征口径不一致；
下游无法证明某项判断使用了哪些具体特征值；
特征计算逻辑混入信号或策略模块。
```

FeatureLayer 提供统一的：

```text
特征定义；
算法注册；
算法版本；
参数管理；
计算入口；
精度规则；
持久化结果；
幂等规则；
追溯链路。
```

## 3. 核心原则

### 3.1 MarketSnapshot 是唯一正式输入边界

FeatureLayer 必须接收明确的 `market_snapshot_id`。

当前主链路只允许消费以下固定 `data_collection_domain` 生成的 MarketSnapshot：

```text
exchange = binance
market_type = usds_m_futures
symbol = BTCUSDT
base_timeframe = 4h
higher_timeframe = 1d
```

该采集域不随交易执行域、账户类型或运行时交易配置变化。交易模块支持 U 本位或币本位，不会改变 FeatureLayer 的行情输入范围。

只允许消费同时满足以下条件的 MarketSnapshot：

```text
status = created；
is_usable = true；
allows_feature_layer = true；
4h 与 1d 窗口信息完整；
关联的质量授权完整；
data_collection_domain 与上述固定采集域完全一致。
```

FeatureLayer 不得：

```text
按当前时间自行寻找“最新 Kline”；
自行决定分析截止时间；
自行扩大或缩小 MarketSnapshot 的窗口；
绕过 MarketSnapshot 直接启动一轮正式特征计算；
在 MarketSnapshot 非 created 时尝试继续。
```

### 3.2 一份 FeatureSet 只能属于一份 MarketSnapshot

FeatureSet 必须通过真实业务外键绑定 MarketSnapshot。

正式结果粒度为：

```text
一份 MarketSnapshot
+ 一份冻结的 FeatureDefinition 集合
+ 一个 feature_schema_version
→ 最多一份可消费 FeatureSet
```

FeatureSet 不是“每天一条”的记录，也不按任务执行次数重复创建。

### 3.3 定义、算法、结果必须分离

必须区分：

```text
FeatureDefinition = 一个特征的业务定义、参数和算法身份；
Calculator        = 纯计算代码；
FeatureSet        = 某份 MarketSnapshot 上的一批计算结果；
FeatureValue      = FeatureSet 内某一个特征的具体值。
```

不得用单个大 JSON 同时替代 FeatureDefinition、FeatureSet 和 FeatureValue。

### 3.4 特征层只产生中性事实

允许的特征包括：

```text
latest_close_4h
latest_volume_4h
sma_4h_20
sma_4h_60
atr_4h_14
return_4h_1
range_4h_60_high
range_1d_60_low
volume_sma_4h_20
```

FeatureLayer 不得产生：

```text
sma_4h_20_above_sma_4h_60
bullish_trend
bearish_trend
long_signal
short_signal
entry_signal
should_trade
target_position
position_size
leverage
stop_loss
take_profit
risk_block
```

特征间比较、阈值判断、突破判断和方向倾向属于 AtomicSignal。

### 3.5 历史结果不可被定义变化污染

一旦 FeatureDefinition 已参与正式 FeatureSet：

```text
不得原地修改其身份字段；
不得让算法代码在相同 algorithm_version 下改变历史行为；
不得覆盖已经生成的 FeatureValue；
不得让生命周期状态变化影响历史追溯。
```

算法逻辑变化必须使用不同的 `algorithm_version`。

参数或业务含义变化必须形成不同的 FeatureDefinition 身份。

### 3.6 MySQL 是正式事实来源

以下对象必须持久化到 MySQL：

```text
FeatureDefinition；
FeatureSet；
FeatureValue。
```

Redis 只允许用于：

```text
短期幂等控制；
并发互斥；
短期计算缓存；
Celery 任务状态。
```

Redis 不得成为 FeatureValue 的唯一存储，也不得作为 AtomicSignal 的正式输入来源。

## 4. 输入合同

FeatureLayerService 的正式输入至少包括：

```text
market_snapshot_id
strategy_analysis_release_id
strategy_analysis_release_hash
expected_feature_definition_set_hash
business_request_key
trace_id
trigger_source
```

正式运行的版本包选择、批准、启用、切换、回滚和后台回测隔离统一遵守 [StrategyAnalysisRelease](strategy_analysis_release.md)。

FeatureLayerService 必须根据明确的 StrategyAnalysisRelease 读取特征切片，不得读取“全部 active FeatureDefinition”作为正式计算集合。

### 4.1 market_snapshot_id

`market_snapshot_id` 是本次计算的唯一市场事实入口。

服务必须通过该 ID 读取：

```text
exchange；
market_type；
symbol；
analysis_close_time_utc；
analysis_reference_time_utc；
4h 窗口起止索引；
1d 窗口起止索引；
4h lookback_count 与 actual_count；
1d lookback_count 与 actual_count；
snapshot_key；
MarketSnapshot 状态和放行字段。
```

### 4.2 StrategyAnalysisRelease 特征切片

`strategy_analysis_release_id` 与 `strategy_analysis_release_hash` 必须对应本轮编排开始时冻结的已批准并已启用版本包。

FeatureLayerService 必须：

```text
只读取版本包特征切片明确绑定的 FeatureDefinition；
校验定义、calculator、参数和依赖指纹；
用实际冻结定义集合重算 definition_set_hash；
确认其与 expected_feature_definition_set_hash 一致；
任一定义缺失、多出、失效或指纹失配时返回 blocked；
不得自动追加其他 active 或默认特征。
```

版本包身份用于正式运行选择和审计，不替代 FeatureSet 对 MarketSnapshot 的业务外键或 FeatureValue 对 FeatureDefinition 的逐条绑定。

### 4.3 business_request_key

`business_request_key` 是调用方提供的不透明业务幂等键。

规则：

```text
FeatureLayer 只保存和比较该键；
不得解析其中是否包含编排信息；
相同业务请求重复调用必须返回同一业务结果；
不得因 Celery 重投或进程重启创建第二份有效结果。
```

### 4.4 trace_id

`trace_id` 用于跨模块日志和审计关联。

`trace_id` 不是业务外键，不能代替：

```text
market_snapshot_id；
feature_set_id；
feature_definition_id。
```

### 4.5 trigger_source

允许表达：

```text
orchestrated
manual
scheduled
recovery
test
```

`trigger_source` 只说明触发来源，不改变计算公式或放行标准。

## 5. 输出合同

FeatureLayerService 必须返回结构化结果，至少包括：

```text
status
feature_set_id
feature_set_key
market_snapshot_id
strategy_analysis_release_id
strategy_analysis_release_hash
computed_count
valid_count
invalid_count
required_failed_count
optional_failed_count
allows_atomic_signal
error_code
error_message
trace_id
```

允许的业务状态：

```text
created
blocked
failed
unknown
```

### 5.1 created

表示计算完成或幂等复用已有完整结果。

只有同时满足以下条件时才允许：

```text
FeatureSet 完整落库；
所有 required FeatureValue 有效；
定义集合身份完整；
MarketSnapshot 业务外键完整；
allows_atomic_signal = true。
```

### 5.2 blocked

表示前置业务条件不满足，未获准执行特征计算。

典型原因：

```text
MarketSnapshot 不存在；
MarketSnapshot 非 created；
MarketSnapshot.is_usable = false；
MarketSnapshot.allows_feature_layer = false；
MarketSnapshot 窗口元数据不完整；
没有可用于正式计算的 FeatureDefinition；
MarketSnapshot 的采集域与固定 data_collection_domain 不一致；
StrategyAnalysisRelease 不存在、未批准、未启用或指纹不一致；
版本包特征切片缺失、多出或定义集指纹不一致。
```

blocked 必须：

```text
allows_atomic_signal = false；
feature_set_id = null；
feature_set_key = null；
不创建 FeatureSet 或 FeatureValue；
不得进入 AtomicSignal。
```

`blocked` 是前置条件校验结果，不是已持久化 FeatureSet 的生命周期状态。重复请求必须重新读取当前前置事实并返回明确结果，不得把旧的阻断结果当作可消费业务对象。

### 5.3 failed

表示已经进入计算，但出现可明确判断的失败。

典型原因：

```text
Kline 回查数量与 MarketSnapshot 不一致；
Kline 窗口索引不连续；
required 特征输入不足；
required calculator 缺失或计算失败；
结果精度或类型不符合定义；
数据库事务明确回滚。
```

failed 必须：

```text
allows_atomic_signal = false；
保存明确 error_code；
不得留下可被误认为完整结果的 FeatureSet。
```

### 5.4 unknown

表示无法安全确认本次结果是否完整提交，例如数据库连接中断时无法判断事务结果。

unknown 必须：

```text
allows_atomic_signal = false；
不得自动重算并覆盖可能存在的结果；
先按 business_request_key 和 feature_set_key 查证；
查证完成后再返回 created 或 failed；
必要时写 AlertEvent。
```

## 6. FeatureDefinition

FeatureDefinition 是正式运行时特征字典。

建议字段：

```text
id
feature_code
display_name
description
category
timeframe
value_type
algorithm_name
algorithm_version
params
params_hash
definition_hash
status
is_required
warmup_bars
output_unit
depends_on_feature_codes
created_at_utc
updated_at_utc
```

### 6.1 feature_code

`feature_code` 必须稳定、唯一、可读，并尽量显式表达周期与关键参数。

例如：

```text
sma_4h_20
sma_4h_60
atr_4h_14
return_4h_1
range_1d_60_high
```

不得使用含糊代码，例如：

```text
sma_fast
sma_slow
main_atr
latest_indicator
```

因为这些代码无法独立说明实际周期和参数。

### 6.2 timeframe

`timeframe` 必须明确记录特征所属周期。

当前正式分析周期为：

```text
4h
1d
```

同名算法在不同周期上必须是不同 FeatureDefinition。

### 6.3 algorithm_name 与 algorithm_version

`algorithm_name` 表示算法族，例如：

```text
latest_value
simple_moving_average
atr_wilder
rolling_high
rolling_low
return_pct
volume_sma
feature_ratio
```

`algorithm_version` 表示该算法代码的不可变实现身份。

注册键为：

```text
algorithm_name + algorithm_version
```

相同注册键的计算行为不得发生不兼容变化。

### 6.4 params

`params` 保存算法参数，例如：

```json
{
  "timeframe": "4h",
  "source": "close",
  "window": 20
}
```

参数必须经过规范化后再计算 hash。

规范化至少要求：

```text
键名稳定；
键顺序稳定；
数值与字符串类型明确；
不包含运行时间、trace_id 或任务 ID；
不包含无法复现的动态默认值。
```

### 6.5 params_hash

`params_hash` 建议使用：

```text
sha256(canonical_json(params))
```

`params_hash` 用于证明本次计算使用的参数身份。

### 6.6 definition_hash

`definition_hash` 至少覆盖：

```text
feature_code；
timeframe；
value_type；
algorithm_name；
algorithm_version；
params_hash；
is_required；
warmup_bars；
output_unit；
depends_on_feature_codes。
```

不影响计算语义的展示名称和描述可以不进入 definition_hash。

### 6.7 status

允许的生命周期状态：

```text
draft
active
deprecated
retired
disabled
```

可被后台新组合或 StrategyAnalysisRelease 选择的 FeatureDefinition 必须满足：

```text
status = active
```

`status = active` 只表示定义在算法库中可供选择，不表示它会自动进入正式 FeatureSet。正式计算集合必须严格等于本轮编排开始时冻结的 StrategyAnalysisRelease 特征切片。

状态变化只影响后续计算，不得影响历史 FeatureValue。

FeatureDefinition 不允许物理删除，除非该定义从未被任何正式业务对象引用且经过受控数据治理流程。

### 6.8 is_required

`is_required` 表示该特征失败是否阻断整个 FeatureSet。

规则：

```text
required 特征失败 → FeatureSet failed；
optional 特征失败 → 保存无效 FeatureValue，FeatureSet 可继续汇总；
AtomicSignal 仍必须自行确认其依赖的 FeatureValue 有效。
```

当前默认特征均作为 required 特征使用。

### 6.9 warmup_bars

`warmup_bars` 是该特征完成计算所需的最少 Kline 数量。

例如：

```text
latest_close → 1；
latest_volume → 1；
sma_20 → 20；
return_1 → 2；
rolling_high_60 → 60；
atr_14 → 由对应算法版本明确定义。
```

FeatureLayer 必须在 calculator 执行前校验窗口数量。

不得让 calculator 在数据不足时静默输出零值或空值。

### 6.10 depends_on_feature_codes

复合数值特征可以声明对其他 FeatureValue 的依赖。

例如：

```text
close_4h_vs_sma_4h_20_pct
→ latest_close_4h
→ sma_4h_20
```

依赖规则：

```text
必须形成无环有向图；
依赖的 feature_code 必须存在于本次冻结集合；
计算顺序由依赖关系决定；
不得在计算中动态引入冻结集合之外的定义；
不得用 depends_on_feature_codes 实现信号判断。
```

## 7. FeatureSet

FeatureSet 表示在一份 MarketSnapshot 上、使用一组冻结定义得到的特征集合。

建议字段：

```text
id
feature_set_key
business_request_key
market_snapshot_id
snapshot_key
exchange
market_type
symbol
analysis_close_time_utc
feature_schema_version
definition_set_hash
status
is_usable
allows_atomic_signal
active_definition_count
computed_count
valid_count
invalid_count
required_failed_count
optional_failed_count
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

### 7.1 feature_set_key

`feature_set_key` 必须稳定生成。

建议输入：

```text
market_snapshot_id；
snapshot_key；
feature_schema_version；
definition_set_hash。
```

规则：

```text
相同输入身份只能对应一份正式 FeatureSet；
feature_set_key 必须有数据库唯一约束；
并发请求不能创建两份 created 结果；
重复请求必须返回已经存在的完整结果。
```

### 7.2 definition_set_hash

`definition_set_hash` 是本次冻结 FeatureDefinition 集合的指纹。

应按稳定排序计算，至少包含每个定义的：

```text
feature_code；
definition_hash。
```

`definition_set_hash` 不能替代 FeatureValue 对 FeatureDefinition 的逐条外键绑定。

### 7.3 feature_schema_version

`feature_schema_version` 表示 FeatureSet 输出合同的结构身份。

它不替代：

```text
algorithm_version；
params_hash；
definition_hash；
definition_set_hash。
```

输出合同发生不兼容变化时必须使用不同 schema 身份，历史 FeatureSet 不得被覆盖。

### 7.4 status、is_usable 与 allows_atomic_signal

已持久化 FeatureSet 的三个字段必须一致：

```text
created → is_usable = true  → allows_atomic_signal = true；
failed  → is_usable = false → allows_atomic_signal = false；
unknown → is_usable = false → allows_atomic_signal = false。
```

`blocked` 只属于 FeatureLayerService 的前置校验返回状态，不创建 FeatureSet，因此不参与上述 FeatureSet 字段映射。

不得仅凭 `status = created` 之外的单个字段放行下游。

### 7.5 payload_summary

`payload_summary` 只保存便于查询和展示的小型摘要，例如：

```text
特征总数；
有效数量；
无效数量；
required 失败数量；
definition_set_hash；
主要错误代码。
```

不得在 payload_summary 中保存：

```text
完整 Kline 窗口；
全部 FeatureValue 副本；
不可控长文本；
用于规避表结构设计的大型 JSON。
```

## 8. FeatureValue

FeatureValue 是某个 FeatureSet 内某个 FeatureDefinition 的正式计算结果。

建议字段：

```text
id
feature_set_id
feature_definition_id
feature_code
timeframe
algorithm_name
algorithm_version
params_hash
definition_hash
value_type
value_decimal
value_integer
value_bool
value_text
value_json
is_valid
error_code
error_message
calculated_at_utc
created_at_utc
```

### 8.1 逐条定义绑定

每条 FeatureValue 必须绑定具体 FeatureDefinition。

同时冗余保存：

```text
feature_code；
timeframe；
algorithm_name；
algorithm_version；
params_hash；
definition_hash。
```

冗余字段用于历史可读性和审计，不得替代真实外键。

### 8.2 值类型

根据 `value_type` 只使用对应值字段：

```text
decimal → value_decimal；
integer → value_integer；
bool    → value_bool；
text    → value_text；
json    → value_json。
```

当前默认特征只使用中性数值结果，不使用表达比较条件的 bool 值。

### 8.3 精度

价格、成交量、均线、ATR、收益率、区间值等必须使用 Decimal 或明确的可控精度计算。

规则：

```text
不得以二进制 float 作为正式持久化结果；
Decimal 写入 JSON 时转换为字符串；
不得用零值代替缺失或失败；
除法分母为零必须明确失败；
舍入规则必须由算法定义或统一精度合同规定。
```

### 8.4 无效 FeatureValue

optional 特征计算失败时可以保存无效 FeatureValue：

```text
is_valid = false；
正式值字段为空；
error_code 非空；
error_message 非空。
```

无效值不得通过零、false 或空字符串伪装成正常结果。

## 9. Calculator 架构

Calculator 负责纯计算，不负责数据库和流程控制。

所有 FeatureLayer calculator 必须遵守 [StrategyCalculator 公共合同](strategy_calculator.md)。本文件只定义 FeatureLayer 特有的输入、输出与业务边界，不得削弱公共合同规定的纯计算、确定性、精确版本选择和副作用隔离要求。

建议按算法族组织：

```text
latest
moving_average
volatility
returns
ranges
volume
ratios
```

Calculator 输入应是：

```text
已按时间升序排列的 Kline 值对象；
FeatureDefinition 中冻结的 params；
必要的已计算依赖特征。
```

Calculator 输出应是：

```text
明确类型的值；
必要的精度元数据；
可判定的计算错误。
```

Calculator 不得：

```text
读取或写入数据库；
访问 Redis；
请求 Binance；
读取当前系统时间决定业务窗口；
读取 env 改变单次计算公式；
创建 FeatureSet；
创建 FeatureValue；
调用其他业务 service；
生成信号、策略或交易动作。
```

## 10. CalculatorRegistry

CalculatorRegistry 必须按以下组合定位 calculator：

```text
algorithm_name + algorithm_version
```

规则：

```text
启动或健康检查时校验当前 StrategyAnalysisRelease 特征切片是否都有注册实现；
重复注册同一组合必须失败；
未知组合不得回退到“最接近”的 calculator；
不得在 FeatureLayerService 中维护大型 if / elif 分发；
不得注册 feature_compare、threshold_check 等信号判断算法。
```

## 11. 默认定义与运行时定义

默认定义模板与正式运行时字典必须分离：

```text
default_definitions.py = 受代码管理的默认模板；
FeatureDefinition 表  = 正式运行时字典。
```

默认模板只能初始化算法库中可供选择的定义。正式计算不得根据默认模板或数据库全量 active 定义自行组装输入，只读取 StrategyAnalysisRelease 特征切片。

特征切片中的定义必须满足：

```text
FeatureDefinition.status = active
```

FeatureLayerService 不得：

```text
直接读取 default_definitions.py 参与计算；
把默认模板与数据库定义求合集；
把版本包特征切片与数据库其他 active 定义求合集；
因模板仍存在而自动激活 disabled 或 retired 定义。
```

## 12. seed_feature_definitions

必须提供幂等的定义初始化入口：

```bash
python manage.py seed_feature_definitions
```

该命令只负责：

```text
读取默认模板；
规范化 params；
计算 params_hash；
计算 definition_hash；
按完整定义身份写入 FeatureDefinition；
输出初始化摘要。
```

该命令不得：

```text
计算 FeatureSet；
生成 FeatureValue；
调用 FeatureLayerService；
请求 Binance；
修改 Kline；
修改 MarketSnapshot；
自动恢复 retired 或 disabled 定义；
覆盖人工维护的生命周期状态；
覆盖已经使用过的身份字段。
```

允许更新的内容仅限不改变计算身份的展示元数据，例如：

```text
display_name；
description；
category；
output_unit。
```

## 13. 当前默认特征集合

当前默认集合包含 15 个中性数值特征。

### 13.1 4h 特征

```text
latest_close_4h
latest_volume_4h
sma_4h_20
sma_4h_60
atr_4h_14
range_4h_60_high
range_4h_60_low
return_4h_1
volume_sma_4h_20
```

### 13.2 1d 特征

```text
latest_close_1d
sma_1d_20
atr_1d_14
range_1d_60_high
range_1d_60_low
return_1d_1
```

所有默认特征必须：

```text
具有明确 FeatureDefinition；
具有明确 timeframe；
具有明确 algorithm_name 和 algorithm_version；
具有明确 warmup_bars；
具有 calculator 注册；
具有算法需求文档；
具有 implementation 实现记录；
不包含方向或交易语义。
```

### 13.3 默认算法语义

默认特征的算法语义必须由对应 FeatureDefinition、calculator metadata 和算法需求文档共同固定；implementation 实现记录只记录代码落地、测试入口和实现差异，不新增算法语义。

最低要求：

```text
latest_close = 固定窗口中最后一根 Kline 的 close；
latest_volume = 固定窗口中最后一根 Kline 的 volume；
simple_moving_average = 指定 source 在固定窗口末端 N 根 Kline 上的算术平均；
rolling_high = 指定 source 在固定窗口末端 N 根 Kline 上的最大值；
rolling_low = 指定 source 在固定窗口末端 N 根 Kline 上的最小值；
return_pct = 当前值相对 N 根前对应值的变化比例；
volume_sma = 固定窗口末端 N 根 Kline 的 volume 算术平均。
```

当前 `atr_wilder` 对应的正式算法身份采用：

```text
逐根计算 True Range；
对指定窗口内的 True Range 做算术平均；
不使用递推 Wilder smoothing。
```

算法名称不能替代实际公式。若采用递推 Wilder smoothing，必须登记不同的 `algorithm_version`，并保留当前算法身份的计算行为。

## 14. Kline 读取规则

FeatureLayer 可以读取 Kline，但必须严格受 MarketSnapshot 窗口约束。

### 14.1 4h 窗口

只允许读取 MarketSnapshot 记录的：

```text
exchange；
market_type；
symbol；
timeframe = 4h；
start_open_time_utc；
end_open_time_utc；
lookback_count。
```

### 14.2 1d 窗口

只允许读取 MarketSnapshot 记录的：

```text
exchange；
market_type；
symbol；
timeframe = 1d；
start_open_time_utc；
end_open_time_utc；
lookback_count。
```

### 14.3 一致性检查

回查结果必须满足：

```text
市场身份完全一致；
timeframe 完全一致；
数量与 MarketSnapshot 记录一致；
起止 open_time_utc 一致；
按 open_time_utc 严格升序；
窗口内没有重复 Kline；
窗口内没有未收盘 Kline；
4h 与 1d 数据不得混用。
```

任何不一致都不得通过自行查询更多 Kline 来补救。

应返回 failed，并由数据链路负责修复后重新生成合格的 MarketSnapshot。

## 15. 时间规则

所有时间统一使用 UTC。

FeatureLayer 必须遵守：

```text
Kline open_time_utc / close_time_utc 按 Binance UTC 时间解释；
计算排序只使用 UTC；
不得用服务器本地时区参与窗口判断；
不得用用户界面时区参与计算；
不得按运行时当前时间替换 analysis_reference_time_utc；
日志和后台展示默认明确标注 UTC。
```

FeatureValue 的数值必须只由固定输入和固定定义决定，不能因重试时间不同而变化。

## 16. FeatureLayerService 主流程

标准流程：

```text
1. 接收 market_snapshot_id、StrategyAnalysisRelease 身份、business_request_key、trace_id、trigger_source；
2. 校验请求字段；
3. 按 business_request_key 查询已有结果；
4. 读取 MarketSnapshot；
5. 校验 status、is_usable 和 allows_feature_layer；
6. 校验 StrategyAnalysisRelease 并读取特征切片；
7. 只按切片读取并冻结 FeatureDefinition 集合；
8. 计算 definition_set_hash 并与切片预期指纹比对；
9. 计算 feature_set_key；
10. 按 feature_set_key 查询已有完整 FeatureSet；
11. 按 MarketSnapshot 窗口读取 4h 与 1d Kline；
12. 校验窗口数量、时间、周期和市场身份；
13. 校验 FeatureDefinition 依赖无环且 calculator 完整；
14. 按依赖顺序调用 calculator；
15. 在内存中形成全部 FeatureValue 待写结果；
16. 汇总 required 和 optional 失败；
17. 在数据库事务中写入 FeatureSet 与 FeatureValue；
18. 返回结构化业务结果。
```

计算过程中冻结的 FeatureDefinition 集合不得再次读取并替换，也不得因数据库中存在其他 active 定义而追加计算。

## 17. 写库与事务

FeatureSet 与 FeatureValue 必须在同一个数据库事务中完成正式写入。

要求：

```text
使用 transaction.atomic() 或等价 Django 事务；
FeatureValue 使用 bulk_create 或等价批量写入；
数据库唯一约束保护 business_request_key 和 feature_set_key；
不得出现 FeatureSet created 但 FeatureValue 只写入一部分；
不得在数据库长事务中执行外部请求；
不得在事务中等待 Celery 或其他模块。
```

本模块没有外部网络请求，因此应先完成内存计算，再进入短事务落库。

## 18. 幂等与并发

### 18.1 重复调用

相同 `business_request_key` 重复调用：

```text
已有 created → 返回已有 FeatureSet；
已有 failed → 返回已有明确失败结果，受控恢复入口可重新核验；
已有 unknown → 先查证，不直接再次计算。
上一次返回 blocked → 重新读取 MarketSnapshot 和 FeatureDefinition 等前置事实，不查找所谓“已持久化 blocked FeatureSet”。
```

### 18.2 相同输入身份

即使 business_request_key 不同，只要以下身份相同：

```text
market_snapshot_id；
feature_schema_version；
definition_set_hash。
```

也不得生成两份相同的正式 FeatureSet。

### 18.3 并发冲突

并发请求必须依靠：

```text
数据库唯一约束；
原子创建；
必要的短期 Redis 锁。
```

Redis 锁失效不能破坏数据库唯一性。

## 19. 失败处理

### 19.1 前置阻断

MarketSnapshot 未放行时：

```text
返回 blocked；
不读取完整 Kline 窗口；
不调用 calculator；
feature_set_id 和 feature_set_key 返回 null；
不生成 FeatureSet 或 FeatureValue；
不进入 AtomicSignal。
```

### 19.2 单个 optional 特征失败

允许：

```text
保存 is_valid = false 的 FeatureValue；
记录 error_code 和 error_message；
继续计算不依赖该值的其他特征；
增加 optional_failed_count。
```

如果其他 required 特征或下游正式依赖该 optional 特征，则必须按依赖规则阻断相应结果。

### 19.3 required 特征失败

任一 required 特征失败：

```text
FeatureSet.status = failed；
FeatureSet.is_usable = false；
FeatureSet.allows_atomic_signal = false；
不得进入 AtomicSignal。
```

### 19.4 未知结果

数据库返回结果不明确时：

```text
不得假设写入失败；
不得立即重复插入；
按 business_request_key 与 feature_set_key 查证；
核对 FeatureValue 数量和 required 有效性；
无法确认时保持 unknown 并告警。
```

## 20. 恢复规则

受控恢复必须先读取已有事实：

```text
MarketSnapshot 是否仍为 created；
FeatureSet 是否存在；
FeatureValue 数量是否与冻结定义集合一致；
definition_set_hash 是否一致；
required FeatureValue 是否全部有效。
```

恢复结果：

```text
完整且一致 → 返回 created；
未创建且前置条件仍满足 → 使用相同幂等身份执行；
存在不完整事务外残留 → failed 并告警，禁止放行；
无法判断 → unknown，等待人工或巡检处理。
```

不得覆盖已经 created 的 FeatureSet 重新计算。

如需按不同定义重算同一 MarketSnapshot，必须形成不同的定义集合身份和 FeatureSet，不得修改既有结果。

## 21. 与 AtomicSignal 的关系

AtomicSignal 必须消费明确的 `feature_set_id`。

只允许消费：

```text
FeatureSet.status = created；
FeatureSet.is_usable = true；
FeatureSet.allows_atomic_signal = true。
```

AtomicSignal 必须：

```text
通过 FeatureSet 读取 FeatureValue；
校验依赖的 FeatureValue.is_valid = true；
记录实际使用的 feature_value_id；
不得重新计算基础特征；
不得绕过 FeatureSet 直接读取 Kline。
```

### 21.1 与 PriceSnapshot 的区别

FeatureValue 与 PriceSnapshot 是两类不同事实：

```text
FeatureValue = 基于 MarketSnapshot 固定 Kline 窗口计算的分析特征；
PriceSnapshot = 通过 BinanceGateway 主动获取的 mark price 价格事实。
```

规则：

```text
FeatureLayer 不读取 PriceSnapshot；
FeatureLayer 不把 mark price 混入 Kline 特征；
OrderPlan、RiskCheck 和 ExecutionPreparation 使用价格事实时读取 PriceSnapshot；
策略分析链路需要基础特征时读取 FeatureSet / FeatureValue；
两类对象不得互相替代。
```

## 22. 与编排层的关系

FeatureLayer 是业务模块，不承担编排职责。

业务对象必须通过自身外键形成完整追溯链：

```text
FeatureValue
→ FeatureSet
→ MarketSnapshot
→ DataQualityResult / Kline 窗口
```

FeatureLayer 不得在业务表中保存或查询：

```text
orchestration_run_id；
orchestration_step_run_id；
编排对象关联表。
```

编排流程由 `FeatureLayerStepAdapter` 负责：

```text
接收编排层传入的 market_snapshot_id 和 business_request_key；
调用 FeatureLayerService；
理解 FeatureLayer 原始业务结果；
把 created / blocked / failed / unknown 映射为统一状态和 flow_action；
向编排层返回 feature_set_id 及对象引用。
```

编排层可以把 FeatureSet 登记到对象关联表，用于一轮详情快速查询；该关联不替代 FeatureSet 对 MarketSnapshot 的业务外键。

## 23. 与回测和研究的关系

正式运行和回测必须复用相同的：

```text
FeatureDefinition 语义；
Calculator 实现；
algorithm_version；
params 规范化；
精度与舍入规则。
```

研究或历史重算不得覆盖正式 FeatureSet。

不同用途的结果必须有清晰的数据域或模式隔离，且能明确识别其来源。

## 24. AlertEvent

FeatureLayer 成功时默认只写结构化日志，不强制写 AlertEvent。

以下情况应写 AlertEvent：

```text
feature_layer_blocked
feature_set_failed
feature_set_unknown
feature_definition_missing_calculator
feature_window_mismatch
feature_required_value_failed
```

规则：

```text
FeatureLayer 只写 AlertEvent；
不得直接调用 Hermes；
不得直接调用 Notifications 发送消息；
AlertEvent 不触发自动交易；
告警写入不能把失败结果变成 created。
```

## 25. 配置规则

允许配置：

```text
FEATURE_SCHEMA_VERSION；
FeatureValue Decimal 精度和统一舍入规则；
短期幂等锁 TTL；
单次允许计算的最大特征数量；
管理命令默认输出格式。
```

不允许通过 env 动态改变：

```text
FeatureDefinition.params；
具体算法公式；
StrategyAnalysisRelease 选择的特征定义集合；
required / optional 身份；
算法注册映射。
```

这些正式业务定义必须由 FeatureDefinition、StrategyAnalysisRelease 和受版本管理的代码共同表达。环境变量不得替代版本包选择，也不得临时增删正式特征。

所有环境配置进入 `.env.example`，并带中文注释。

## 26. 服务、任务与命令边界

### 26.1 service

核心业务逻辑放在 service/domain 层。

FeatureLayerService 负责：

```text
输入校验；
前置条件；
定义冻结；
窗口读取；
计算调度；
结果汇总；
事务落库；
幂等返回。
```

### 26.2 Celery task

Celery task 只负责：

```text
接收参数；
传递 trace_id 和 trigger_source；
调用 FeatureLayerService；
返回可序列化摘要。
```

task 不得实现特征算法或直接写 FeatureValue。

### 26.3 management command

手动构建入口：

```bash
python manage.py build_features --market-snapshot-id <id> --business-request-key <key> --trigger-source manual --trace-id <id>
```

command 只负责参数解析、调用 service 和输出结果。

至少输出：

```text
feature_set_id；
feature_set_key；
status；
computed_count；
valid_count；
invalid_count；
allows_atomic_signal。
```

## 27. 算法需求文档与 implementation 实现记录

每个正式 calculator 都必须同时具备：

```text
算法需求文档；
implementation 实现记录。
```

算法需求文档负责定义特征算法的输入、公式、参数、边界和验证要求，应放在 requirements 下的对应特征算法目录，具体目录由后续特征算法需求文件统一确定，例如：

```text
docs/requirements/<特征算法模块>/<feature_or_algorithm>.md
```

implementation 实现记录负责记录代码落地位置、calculator、DTO、测试入口和实现差异，统一目录：

```text
docs/implementation/feature_layer/
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
simple_moving_average__1.0.0.md
atr_wilder__1.0.0.md
rolling_high__1.0.0.md
```

至少说明：

```text
算法名称；
算法版本；
中文用途；
输入字段；
窗口需求；
计算公式；
精度与舍入；
失败条件；
输出类型；
不包含的交易语义。
```

算法需求文档必须与实际 calculator 行为一致；implementation 实现记录必须与实际代码位置和测试入口一致。

任何算法行为变化都必须形成不同的算法身份，不能只修改说明文字或直接改变既有实现。

FeatureDefinition 的参数组合继续由 `params / params_hash / definition_hash` 表达；参数不同但 calculator 算法行为相同，不重复创建算法需求版本文件或 implementation 实现记录。

## 28. 日志与审计

结构化日志至少包含：

```text
trace_id；
trigger_source；
business_request_key；
market_snapshot_id；
feature_set_id；
feature_set_key；
definition_set_hash；
status；
computed_count；
valid_count；
invalid_count；
error_code；
latency_ms。
```

日志不得包含：

```text
完整 Kline 窗口；
全部 FeatureValue；
API Key；
数据库密码；
Redis 密码；
不可控长 JSON。
```

## 29. dry-run 与 confirm-write

FeatureLayer 可以支持 `dry-run`，用于验证读取、定义解析和计算结果。

dry-run 必须：

```text
读取明确的 MarketSnapshot；
执行与正式模式相同的窗口校验和 calculator；
不写 FeatureSet；
不写 FeatureValue；
不写正式业务 AlertEvent；
不允许 AtomicSignal 消费其内存结果；
明确返回 persisted = false。
```

如提供 `confirm-write` 参数：

```text
默认不得绕过幂等和前置条件；
confirm-write 只控制是否落库；
不得把 blocked 或 failed 强制写成 created；
不得绕过 MarketSnapshot 放行条件。
```

## 30. 测试要求

至少覆盖：

```text
1. FeatureDefinition 可以创建并计算稳定 params_hash。
2. definition_hash 对相同规范化输入稳定。
3. FeatureDefinition 生命周期状态只影响后续计算。
4. 本轮冻结版本包选择的 active 定义参与正式 FeatureSet。
5. 未被本轮冻结版本包选择的 active 定义不参与正式 FeatureSet。
6. draft、deprecated、retired、disabled 定义即使被错误写入版本包也必须阻断计算。
7. 相同算法族可以注册不同 algorithm_version。
8. CalculatorRegistry 能按完整注册键找到实现。
9. 未注册 calculator 时不允许生成可消费 FeatureSet。
10. 重复注册同一 calculator 身份被拒绝。
11. registry 不包含 feature_compare 或交易判断算法。
12. 版本包不存在、未批准、未启用或指纹不一致时阻断计算。
13. 版本包特征切片存在缺项、多项或定义集合指纹不一致时阻断计算。
11. MarketSnapshot created 且允许下游时可以计算。
12. MarketSnapshot 不存在时 blocked。
13. MarketSnapshot 非 created 时 blocked。
14. MarketSnapshot.is_usable = false 时 blocked。
15. MarketSnapshot.allows_feature_layer = false 或采集域不匹配时 blocked，且不创建 FeatureSet。
16. FeatureLayer 只读取明确传入的 market_snapshot_id。
17. FeatureLayer 不自行选择最新 Kline。
18. 4h Kline 数量不一致时 failed。
19. 1d Kline 数量不一致时 failed。
20. Kline 市场身份不一致时 failed。
21. Kline 周期混用时 failed。
22. Kline 时间不连续时 failed。
23. 未收盘 Kline 不得进入计算。
24. warmup_bars 不足时特征失败。
25. required 特征失败时 FeatureSet failed。
26. optional 特征失败时保存明确无效值。
27. 无效 FeatureValue 不用零值伪装。
28. FeatureValue 绑定 FeatureDefinition。
29. FeatureValue 冗余保存定义身份。
30. FeatureSet 绑定 MarketSnapshot。
31. FeatureSet 与 FeatureValue 在同一事务写入。
32. 事务失败不会留下 created 的半成品 FeatureSet。
33. Decimal 不以 float 持久化。
34. Decimal 写入 JSON 时转换为字符串。
35. definition_set_hash 对相同定义集合稳定。
36. feature_set_key 对相同输入身份稳定。
37. 相同 business_request_key 重复执行会复用已持久化结果；上次 blocked 则重新校验前置事实。
38. 相同 feature_set_key 并发执行只生成一份结果。
39. unknown 不自动放行 AtomicSignal。
40. created 才允许 AtomicSignal 消费。
41. blocked、failed、unknown 均不允许 AtomicSignal 消费。
42. AtomicSignal 能通过 feature_set_id 读取 FeatureValue。
43. FeatureLayer 不生成 AtomicSignal、DomainSignal、MarketRegimeSnapshot、StrategyRouteDecision 或 StrategySignal。
44. AtomicSignal 之后的正式链路包含 DomainSignal、MarketRegime 和 StrategyRouting，不得直接跳到 StrategySignal。
45. FeatureLayer 不生成 DecisionSnapshot。
46. FeatureLayer 不请求 Binance。
47. FeatureLayer 不调用 BinanceGateway。
48. FeatureLayer 不调用大模型。
49. FeatureLayer 不调用 DataQuality 或 DataBackfill。
50. FeatureLayer 不修改 Kline 或 MarketSnapshot。
51. FeatureLayer 不保存或查询编排 ID。
52. adapter 能把业务结果显式映射给编排层。
53. dry-run 不写 FeatureSet 或 FeatureValue。
54. seed 命令幂等。
55. seed 不恢复 retired 或 disabled 定义。
56. seed 不计算 FeatureSet。
57. command 与 task 不承载计算逻辑。
58. 异常只写 AlertEvent，不直接发送 Hermes。
59. 全部业务时间使用 UTC。
60. 默认集合包含 15 个中性数值特征，其中 `latest_volume_4h` 可与 `volume_sma_4h_20` 共同供成交量原子信号使用。
```

## 31. 验收方式

实现完成后至少执行：

```bash
pytest tests/feature_layer/
python manage.py seed_feature_definitions
python manage.py build_features --market-snapshot-id <id> --business-request-key <key> --trigger-source manual --trace-id <id>
```

数据库检查：

```text
FeatureDefinition 的 hash、状态和 calculator 身份完整；
FeatureSet 正确绑定 MarketSnapshot；
FeatureSet 的 definition_set_hash 可复算；
FeatureValue 数量与冻结定义集合一致；
每条 FeatureValue 绑定具体 FeatureDefinition；
required FeatureValue 全部有效；
created FeatureSet 的 allows_atomic_signal = true；
重复执行没有产生第二份正式 FeatureSet；
没有保存任何编排 ID。
```

通过标准：

```text
同一 MarketSnapshot 和定义集合得到唯一、稳定结果；
结果可以从 FeatureValue 追溯到 FeatureDefinition、FeatureSet 和 MarketSnapshot；
4h 与 1d 窗口没有混用；
失败输入不能进入 AtomicSignal；
没有外部网络访问；
没有交易副作用。
```

## 32. 模块影响声明

```text
读写 MySQL：是，读取 MarketSnapshot、Kline、FeatureDefinition，写 FeatureSet、FeatureValue 和必要 AlertEvent；
访问 Redis：可选，仅用于短期锁、幂等和缓存，不保存正式事实；
访问 Binance：否；
调用 BinanceGateway：否；
发送 Hermes：否；
调用大模型：否；
涉及真实交易：否；
涉及 FeatureLayer：是，本模块自身；
涉及 AtomicSignal：只提供正式输入，不生成 AtomicSignal；
涉及 DecisionSnapshot：否；
涉及 Binance Account Sync：否；
涉及 PriceSnapshot：否；
涉及 OrderPlan / CandidateOrderIntent：否；
涉及 RiskCheck / ApprovedOrderIntent：否；
涉及 ExecutionPreparation / Execution：否；
涉及 OrderStatusSync / FillSync / ReviewDataset：否；
写 AlertEvent：仅异常、阻断或未知状态；
dry-run：可计算但不写正式业务对象；
confirm-write：如提供，只控制落库，不改变业务放行标准。
```

## 33. 明确禁止

FeatureLayer 禁止：

```text
绕过 MarketSnapshot；
自行选择分析窗口；
请求 Binance REST 或 WebSocket；
调用 BinanceGateway；
创建或修改 Kline；
执行 DataQuality；
执行 DataBackfill；
覆盖 MarketSnapshot；
把完整 Kline 数组写入 FeatureSet JSON；
把全部特征只保存在 Redis；
用 float 保存正式价格和指标；
用零值伪装失败值；
修改已经用于正式结果的算法行为；
物理删除被历史结果引用的 FeatureDefinition；
生成比较型条件；
生成方向信号；
生成策略结论；
生成目标仓位；
读取账户和持仓；
生成 CandidateOrderIntent；
执行风控；
提交订单；
直接发送 Hermes；
调用大模型；
保存或查询编排 ID；
让编排对象关联替代业务外键。
```

## 34. 最终验收标准

FeatureLayer 验收通过必须满足：

```text
MarketSnapshot 是唯一正式输入边界；
MarketSnapshot 必须属于 Binance USDS-M BTCUSDT 4h / 1d 固定 data_collection_domain；
FeatureSet 与 MarketSnapshot 一对一地表达一次定义集合计算结果；
FeatureValue 逐条绑定 FeatureDefinition；
FeatureDefinition、Calculator、FeatureSet、FeatureValue 职责分离；
算法和参数身份可追溯且历史行为不可被覆盖；
正式运行只读取本轮已冻结 StrategyAnalysisRelease 特征切片中的 active FeatureDefinition；
未被版本包选择的算法不得混入正式 FeatureSet，后台研究组合不得写入正式 FeatureSet；
默认模板只用于幂等初始化；
4h 与 1d Kline 严格按 MarketSnapshot 窗口读取；
全部时间使用 UTC；
正式数值使用 Decimal 或明确可控精度；
required 特征失败会阻断下游；
blocked 只作为服务前置校验结果，不创建 FeatureSet 或 FeatureValue；
只有 created 且 allows_atomic_signal = true 的 FeatureSet 可被消费；
AtomicSignal 读取 FeatureValue，不重复计算基础特征；
默认集合包含 `latest_volume_4h`，成交量原子信号不需要绕过 FeatureSet 读取 Kline；
业务外键可以独立完成完整追溯；
编排 ID 不进入业务模型；
MySQL 保存正式事实，Redis 只承担辅助能力；
不请求 Binance；
不调用大模型；
不生成信号、决策、订单或交易动作；
不涉及真实交易；
不违反项目交易红线。
```

FeatureLayer 的最终定位是：

```text
把一份已授权的 MarketSnapshot，确定性地转换为一份可审计、可复现、可供 AtomicSignal 消费的基础特征事实。
```
