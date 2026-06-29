# StrategyRouting 需求说明

## 1. 模块定位

StrategyRouting 位于 MarketRegime 之后、StrategySignal 之前。

它负责根据一份明确的 MarketRegimeSnapshot、冻结的 StrategyRoutePolicy、冻结的 StrategyRouteRule 集合和版本包策略切片，生成不可变的 StrategyRouteDecision。

正式链路为：

```text
DomainSignalSet / DomainSignalValue
→ MarketRegimeSnapshot
→ StrategyRouteDecision
→ StrategySignal
→ StrategySignalQualityResult
→ DecisionSnapshot
```

StrategyRouting 业务模块负责：

```text
接收明确的 market_regime_snapshot_id；
校验 MarketRegimeSnapshot 是否允许正式路由消费；
读取本轮 StrategyAnalysisRelease 唯一选择的 StrategyRoutePolicy；
读取并冻结 Policy、Rule 和版本包策略切片中的 StrategyDefinition；
按稳定规则执行优先级匹配；
校验被选 StrategyDefinition 的生命周期和可用性；
生成 StrategyRouteDecision；
保存匹配条件、选择原因、fallback 和完整证据；
处理状态、幂等、事务、unknown、恢复和 AlertEvent；
向 StrategySignal 提供唯一、明确的策略选择结果。
```

StrategyRoutingService 的规则匹配只负责：

```text
根据 MarketRegimeSnapshot 逐条判断版本包冻结规则；
按明确优先级找到唯一最高优先匹配规则；
执行 select_strategy 或 no_strategy 动作；
校验规则指定的已注册策略或明确 fallback 策略；
必要时执行明确配置的 fallback；
形成结构化选择结果和证据。
```

StrategyRouting 不负责：

```text
重新计算 MarketRegime；
读取 DomainSignalValue 代替 MarketRegimeSnapshot；
执行 StrategySignal 算法；
计算策略方向、强度或置信度；
计算策略权重；
读取策略历史表现并在线调参；
生成目标仓位；
读取账户、持仓或 PriceSnapshot；
生成订单；
风控审批；
交易执行；
调用 Binance；
调用大模型。
```

## 2. 路由的业务含义

MarketRegimeSnapshot 只回答：

```text
当前整体市场环境被归为什么类别；
分类评分和明确程度是什么；
分类依据是什么。
```

StrategyRouting 回答：

```text
在该市场环境和明确的路由配置下，应选择哪一个 StrategyDefinition；
或者，配置是否明确要求本轮不选择任何策略。
```

StrategyRouteDecision 只表达策略选择结果，不表达策略判断结果。

必须区分：

```text
MarketRegimeSnapshot  = 市场环境分类；
StrategyRoutePolicy   = 路由算法、规则集合和运行配置；
StrategyRouteRule     = Policy 下的一条确定性匹配规则；
StrategyRouteDecision = 一次不可变策略选择事实；
StrategyDefinition    = 可被选择并执行的策略定义；
StrategySignal        = 被选策略计算出的方向、强度、置信度和证据。
```

StrategyRouteDecision 不得输出：

```text
bullish / bearish 策略方向；
StrategySignal strength；
StrategySignal confidence；
target_position_ratio；
订单方向或数量；
交易建议。
```

### 2.1 MarketRegime 到 StrategyDefinition 的多对一关系

StrategyRouting 的业务关系是：

```text
多个 MarketRegimeSnapshot.regime_code 可以映射到同一个 StrategyDefinition；
一个 MarketRegimeSnapshot 在一次正式路由中最多命中一个最终 StrategyDefinition；
一个 StrategyDefinition 可以服务多个相近市场环境；
不适合进入策略计算的市场环境必须通过显式 no_strategy Rule 表达。
```

例如：

```text
bullish_trend_continuation 可以映射到多头趋势策略；
bullish_high_range 如果正式规则选择让同一策略进一步判断，也可以映射到多头回调支撑策略；
high_risk_environment 可以通过显式 Rule 映射为 no_strategy。
```

这表示“多个市场环境可以对应一个策略”，不是“一个路由结果对应多个策略”。

正式 P0 阶段仍然坚持：

```text
一轮只选择一个主策略；
不输出策略权重；
不做多策略投票；
不做策略组合资金分配；
不把 no_strategy 做成等待策略。
```

### 2.2 P0 路由目标族

P0 路由配置优先围绕四类策略目标族设计：

```text
多头趋势策略；
多头回调支撑策略；
空头趋势策略；
空头反弹压制策略。
```

这些是路由目标族，不等于本文件批准了正式 StrategyDefinition。

正式可选择的 StrategyDefinition 必须由 StrategySignal 具体策略算法需求、calculator 注册、StrategyAnalysisRelease 策略切片和 RouteRule 共同确认。

当前已明确的趋势策略算法需求为：

```text
docs/requirements/strategy_signals/long_trend_following_v1.md
docs/requirements/strategy_signals/long_pullback_support_v1.md
docs/requirements/strategy_signals/short_trend_following_v1.md
docs/requirements/strategy_signals/short_rebound_pressure_v1.md
```

`long_trend_following / v1` 可以作为“多头趋势策略”目标族下的具体 StrategyDefinition，用于承接：

```text
bullish_trend_continuation
bullish_breakout
```

`long_pullback_support / v1` 可以作为“多头回调支撑策略”目标族下的具体 StrategyDefinition，用于承接：

```text
bullish_pullback
bullish_high_range
```

`short_trend_following / v1` 可以作为“空头趋势策略”目标族下的具体 StrategyDefinition，用于承接：

```text
bearish_trend_continuation
bearish_breakdown
```

`short_rebound_pressure / v1` 可以作为“空头反弹压制策略”目标族下的具体 StrategyDefinition，用于承接：

```text
bearish_rebound
bearish_low_range
```

P0 推荐映射方向：

| MarketRegime regime_code | 路由目标族 | 说明 |
|---|---|---|
| bullish_trend_continuation | 多头趋势策略（long_trend_following / v1） | 大背景偏多且趋势延续，交给多头趋势策略进一步判断 |
| bullish_breakout | 多头趋势策略（long_trend_following / v1） | 价格有效向上突破压力结构，交给多头趋势策略以突破模式进一步判断 |
| bullish_pullback | 多头回调支撑策略（long_pullback_support / v1） | 大背景偏多但出现回调，交给回调支撑策略判断支撑位置、回调动能和风险 |
| bullish_high_range | 多头回调支撑策略（long_pullback_support / v1） | 大背景偏多的高位区间，策略内部继续判断是否靠近支撑侧并具备支撑优势 |
| bearish_trend_continuation | 空头趋势策略（short_trend_following / v1） | 大背景偏空且趋势延续，交给空头趋势策略进一步判断 |
| bearish_breakdown | 空头趋势策略（short_trend_following / v1） | 价格有效向下跌破支撑结构，交给空头趋势策略以跌破模式进一步判断 |
| bearish_rebound | 空头反弹压制策略（short_rebound_pressure / v1） | 大背景偏空但出现反弹，交给反弹压制策略判断压力位置、反弹动能和风险 |
| bearish_low_range | 空头反弹压制策略（short_rebound_pressure / v1） | 大背景偏空的低位区间，策略内部继续判断是否靠近压力侧并具备压力优势 |
| bullish_top_reversal_candidate | no_strategy | P0 不直接做顶部反转策略，除非后续新增并验证对应 StrategyDefinition |
| bearish_bottom_reversal_candidate | no_strategy | P0 不直接做底部反转策略，除非后续新增并验证对应 StrategyDefinition |
| neutral_range | no_strategy | 大背景无方向时，P0 不进入正式策略计算 |
| high_risk_environment | no_strategy | 高风险环境不进入正式策略计算，除非后续新增专门策略并验证 |
| unclear_environment | no_strategy | 不明确环境不进入正式策略计算 |

以上映射只能通过 StrategyRouteRule 配置表达，不得写入 StrategyRoutingService 的 if / elif。

如果某个 regime_code 的粒度不足以安全区分策略目标，StrategyRouting 不得读取 DomainSignalValue 补判；应当选择以下方式之一：

```text
在 RouteRule 中显式 no_strategy；
补充更细粒度的 MarketRegime regime_code；
让被选 StrategyDefinition 在 StrategySignal 阶段基于允许的 DomainSignalValue 输出 neutral 或低质量策略判断。
```

## 3. 固定规则匹配逻辑

StrategyRouting 不采用路由算法注册制。

业务逻辑固定为：

```text
读取 MarketRegimeSnapshot；
读取正式 StrategyRoutePolicy；
读取版本包冻结的 StrategyRouteRule 集合；
校验冻结 Rule 集合仍然可用且指纹一致；
按 priority 从高到低匹配；
找到唯一最高优先匹配规则；
执行该规则的 select_strategy 或 no_strategy 动作；
校验被选 StrategyDefinition；
生成 StrategyRouteDecision。
```

新增或停用策略时，只修改策略注册和 RouteRule，不修改上述流程；若正式版本包已经冻结的 Rule 后续被停用、删除或指纹失配，正式运行必须 blocked，不得静默剔除该 Rule 后继续匹配。

### 3.1 条件匹配

每条 RouteRule 只能读取 MarketRegimeSnapshot 已明确开放的市场环境字段。

一条规则的全部条件同时成立时，该规则匹配成功。

规则：

```text
priority 数字越小，优先级越高；
先确定所有匹配规则；
只考虑最高优先级的匹配结果；
最高优先级只有一条匹配规则时执行该规则；
最高优先级存在多条匹配规则时 blocked；
没有规则匹配时 blocked。
```

不得依靠数据库返回顺序处理冲突。

### 3.2 无条件规则

条件集合为空的 Rule 表示无条件匹配。

无条件规则可以用于：

```text
固定选择一个已注册策略；
明确 no_strategy；
作为最低优先级兜底规则。
```

因此固定策略选择不需要单独的路由类型或算法。

### 3.3 不支持隐式路由

以下行为不允许作为隐式路由模式：

```text
自动选择名称相近策略；
自动选择版本号最大的策略；
根据最近收益自动切换策略；
随机选择策略；
同时选择多个策略；
让 MarketRegime 直接返回策略 ID；
没有匹配规则时随便使用一个默认策略。
```

多策略组合不属于本模块范围。

## 4. route_outcome

`route_outcome` 必须明确区分：

```text
selected
no_strategy
```

### 4.1 selected

表示路由正常选择了一个明确 StrategyDefinition。

必须满足：

```text
selected_strategy_definition_id 非空；
StrategyDefinition.status = active；
StrategyDefinition.enabled = true；
策略定义满足正式运行资格；
选择来源可追溯到固定 Policy 或明确匹配 Rule；
allows_strategy_signal = true。
```

### 4.2 no_strategy

表示一条有效 RouteRule 明确决定本轮不选择策略。

例如某个已经登记的市场环境可以由规则明确配置为本轮不选择任何策略。

必须满足：

```text
status = created；
route_outcome = no_strategy；
selected_strategy_definition_id 为空；
allows_strategy_signal = false；
matched_rule_id 非空；
selection_reason 明确；
不是 fallback；
不写异常 AlertEvent。
```

`no_strategy` 是正常路由结果，不是 blocked、failed 或 unknown。

StrategyRouting 不得把“没有规则匹配”自动解释为 no_strategy。只有显式 `action = no_strategy` 的有效 Rule 才能产生该结果。

## 5. 核心原则

### 5.1 MarketRegimeSnapshot 是唯一正式上游边界

正式入口只允许消费：

```text
MarketRegimeSnapshot.status = created；
MarketRegimeSnapshot.is_usable = true；
MarketRegimeSnapshot.allows_strategy_routing = true；
MarketRegimeDefinition.status = active；
MarketRegimeDefinition.enabled = true；
MarketRegimeSnapshot 属于本轮同一 StrategyAnalysisRelease。
```

StrategyRouting 不得：

```text
自行寻找最近 MarketRegimeSnapshot；
通过 domain_signal_set_id 重新生成环境分类；
绕过 MarketRegimeSnapshot 直接读取 DomainSignalValue 做规则匹配；
调用 MarketRegimeService 临时补算；
混用其他 MarketRegimeSnapshot 的字段。
```

### 5.2 一次正式路由最多选择一个策略

正式 `StrategyRouteDecision` 只允许：

```text
选择一个 StrategyDefinition；
或者明确 no_strategy。
```

禁止：

```text
同时选择多个 StrategyDefinition；
输出策略权重集合；
输出资金分配比例；
在本模块内做策略组合优化。
```

### 5.3 路由规则配置化

所有选择必须来自：

```text
StrategyRoutePolicy；
StrategyRouteRule；
已注册且可用的 StrategyDefinition。
```

Service 不得使用具体 `regime_code → strategy_code` 的硬编码 if / elif。

### 5.4 输入事实与路由配置冻结

一次路由必须冻结：

```text
MarketRegimeSnapshot；
StrategyRoutePolicy；
参与匹配的 StrategyRouteRule 集合；
候选 StrategyDefinition 集合；
Policy 版本、条件 schema 和 rule_set_hash。
```

计算期间不得重新读取并替换其中任一对象。

正式运行只允许使用本轮编排开始时冻结的 StrategyAnalysisRelease Rule 集合。冻结集合中的任何 Rule 后续不可用、缺失或指纹不一致，都表示本轮版本包与运行事实不一致，必须 fail-closed；不得只过滤掉不可用 Rule 后继续使用剩余规则形成路由结果。

### 5.5 不读取策略表现进行在线选择

StrategyRouting 不得直接读取：

```text
历史收益；
胜率；
回撤；
最近成交；
账户盈亏；
复盘结论；
ReviewDataset；
人工临时评分。
```

未来如果策略表现参与路由，必须先形成独立、版本化、可回测的输入事实和规则合同，不得把临时查询逻辑塞进 RouteService。

### 5.6 MySQL 是正式事实来源

以下对象必须持久化到 MySQL：

```text
StrategyRoutePolicy；
StrategyRouteRule；
StrategyRouteDecision；
必要的 AlertEvent。
```

Redis 只允许用于短期锁、幂等、缓存和任务状态，不得作为 StrategyRouteDecision 的唯一存储，也不得作为 StrategySignal 的正式输入来源。

## 6. 服务入口合同

StrategyRoutingService 只提供正式路由入口。后台研究与回测使用独立研究服务，不调用正式服务的绕过入口。

### 6.1 正式路由入口

```text
route_for_strategy_signal(
    market_regime_snapshot_id,
    strategy_analysis_release_id,
    strategy_analysis_release_hash,
    expected_strategy_route_policy_hash,
    expected_strategy_definition_set_hash,
    business_request_key,
    trace_id,
    trigger_source,
)
```

正式入口必须：

```text
校验本轮 StrategyAnalysisRelease 已批准、已启用且 release_hash 一致；
读取版本包唯一选择的 StrategyRoutePolicy；
读取版本包策略切片中的 StrategyDefinition；
校验 Policy、Rule 集合和策略切片指纹；
不允许调用方指定 Policy、Rule 或匹配条件；
不允许调用方直接传 selected_strategy_definition_id；
版本包未选择或选择多个 Policy 时 blocked；
版本包冻结 Rule 缺失、被停用或指纹不一致时 blocked；
Rule 引用版本包策略切片之外的 StrategyDefinition 时 blocked；
只生成正式 StrategyRouteDecision。
```

正式版本包选择、批准、启用、切换、回滚和后台研究隔离统一遵守 [StrategyAnalysisRelease](strategy_analysis_release.md)。

### 6.2 business_request_key

`business_request_key` 用于业务请求幂等，由调用方显式传入。

不得包含：

```text
Celery task id；
worker 名称；
当前时间；
随机重试序号；
编排 ID。
```

### 6.3 trace_id 与 trigger_source

`trace_id` 只用于日志和审计，不参与路由计算或唯一性。

`trigger_source` 至少允许：

```text
orchestrator；
celery；
management_command；
ops_console；
recovery；
test。
```

触发来源不得改变 Policy、Rule、策略候选、算法或放行标准。

## 7. 结构化返回合同

StrategyRoutingService 返回至少包括：

```text
status
strategy_route_decision_id
strategy_route_decision_key
market_regime_snapshot_id
strategy_route_policy_id
strategy_analysis_release_id
strategy_analysis_release_hash
matched_route_rule_id
route_outcome
selected_strategy_definition_id
fallback_used
is_usable
allows_strategy_signal
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

### 7.1 created + selected

```text
status = created；
route_outcome = selected；
selected_strategy_definition_id 非空；
is_usable = true；
allows_strategy_signal = true。
```

### 7.2 created + no_strategy

```text
status = created；
route_outcome = no_strategy；
selected_strategy_definition_id 为空；
is_usable = true；
allows_strategy_signal = false；
selection_reason 非空。
```

### 7.3 blocked

blocked 表示业务输入或配置不足以形成可靠路由结果。

典型场景：

```text
MarketRegimeSnapshot 不可用；
StrategyAnalysisRelease 不存在、未批准、未启用或 release_hash 不一致；
版本包未选择或选择多个 Policy；
Policy、Rule 或策略切片指纹不一致；
版本包冻结 Rule 缺失、被停用或指纹不一致；
Policy 或 Rule 配置非法；
没有规则匹配且未配置显式处理；
同优先级规则产生冲突；
选中策略不存在或不可用；
选中 StrategyDefinition 未完成注册；
显式 fallback 被要求但不可用。
```

blocked 必须：

```text
is_usable = false；
allows_strategy_signal = false；
strategy_route_decision_id = null；
strategy_route_decision_key = null；
不创建 StrategyRouteDecision；
不得伪造 selected 或 no_strategy；
写明确 error_code；
写 AlertEvent。
```

`blocked` 是前置条件校验结果，不是已持久化 StrategyRouteDecision 的生命周期状态。

### 7.4 failed

failed 表示已进入处理但无法可靠完成。

典型场景：

```text
规则条件解析失败；
优先级匹配结果违反唯一性；
Rule 或 StrategyDefinition 不属于冻结集合；
route_outcome 合同校验失败；
数据库事务明确失败。
```

failed 必须 fail-closed，不得进入 StrategySignal。

### 7.5 unknown

unknown 只用于持久化结果无法确认。

必须先按：

```text
business_request_key；
strategy_route_decision_key。
```

查证，不得直接重新执行规则匹配。

## 8. StrategyRoutePolicy

StrategyRoutePolicy 是一组版本化路由规则的运行时根定义。

建议字段：

```text
id
policy_code
display_name
description
policy_version
condition_schema_version
rule_set_hash
definition_hash
fallback_policy
fallback_strategy_definition_id
status
enabled
created_at_utc
updated_at_utc
```

### 8.1 policy_code

`policy_code` 必须稳定、唯一、可读，不得包含运行环境或编排信息。

### 8.2 policy_version 与 condition_schema_version

`policy_version` 标识一套 Policy 配置的不可变版本。

`condition_schema_version` 标识 RouteRule 条件结构和比较语义。

规则：

```text
同一 policy_code + policy_version 的规则语义不可变；
条件字段、比较符或边界语义发生不兼容变化时必须使用新的 condition_schema_version；
Service 只实现文档明确支持的 condition_schema_version；
不得根据运行环境替换版本；
不得在同一版本下静默改变优先级或匹配语义。
```

### 8.3 Rule 集合

可被 StrategyAnalysisRelease 选择的 Policy 必须拥有至少一条 active + enabled RouteRule。

Policy 被纳入正式版本包后，本次正式运行应读取版本包冻结的 Rule 集合并逐条校验。运行时不得把冻结集合中已 disabled、retired、缺失或指纹失配的 Rule 静默过滤掉。

所有正式选择目标必须通过 Rule 的真实 StrategyDefinition 外键表达。

Policy 不保存算法名称、路由类型或算法参数；固定选择通过一条无条件 Rule 表达，按市场环境选择通过有条件 Rule 表达。

### 8.4 策略目标

Policy 本身不直接绑定选择目标。

规则：

```text
select_strategy Rule 必须绑定 selected_strategy_definition_id；
no_strategy Rule 不得绑定 StrategyDefinition；
Rule 与 fallback 引用的 StrategyDefinition 必须位于同一 StrategyAnalysisRelease 策略切片；
不得只保存 strategy_code 而缺少真实外键；
不得把目标策略 ID 隐藏在 match_conditions；
不得在运行时自动替换为其他策略版本。
```

### 8.5 固定业务语义

Policy 不能改变以下稳定规则：

```text
priority 数字越小越优先；
同一 Rule 的条件使用 AND；
最高优先级多条匹配即冲突；
没有匹配规则即 blocked；
只有显式 no_strategy Rule 才能正常不选择策略。
```

### 8.6 fallback_policy

允许值：

```text
none
explicit
```

含义：

```text
none     = 不允许 fallback；
explicit = 只允许使用 Policy 明确绑定的 fallback_strategy_definition_id。
```

禁止自动寻找：

```text
同名其他版本；
任意 active 策略；
最近使用策略；
历史表现最好策略。
```

fallback 只处理已匹配选择目标不可用的情况，不处理“没有规则匹配”。

### 8.7 rule_set_hash 与 definition_hash

`rule_set_hash` 必须覆盖冻结 Rule 集合的稳定身份和顺序。

`definition_hash` 至少覆盖：

```text
policy_code；
policy_version；
condition_schema_version；
rule_set_hash；
fallback_policy；
fallback_strategy_definition_id。
```

`enabled` 是策略路由配置库的可用性开关，不进入不可变 definition_hash。它不代表 Policy 自动进入正式运行；正式身份由 StrategyAnalysisRelease 选择并冻结。

### 8.8 生命周期和正式资格

生命周期：

```text
draft
active
deprecated
retired
disabled
```

可被 StrategyAnalysisRelease 选择的 Policy 必须满足：

```text
status = active；
enabled = true。
```

`status = active` 与 `enabled = true` 只表示 Policy 在路由配置库中可供选择。正式参与资格必须同时满足：

```text
被本轮 StrategyAnalysisRelease 唯一选择；
Policy 为 active 且 enabled；
definition_hash 与 rule_set_hash 均与版本包冻结值一致；
全部 select_strategy Rule 与显式 fallback 只引用版本包策略切片内的 StrategyDefinition。
```

算法库可以同时存在多个 active、enabled 的 Policy；一个 StrategyAnalysisRelease 只能选择其中一个。正式服务不得按最新版本或全局 active 数量自动选择。

被历史 Decision 引用的 Policy 不得物理删除。

## 9. StrategyRouteRule

StrategyRouteRule 是 StrategyRoutingService 直接执行的一条冻结业务规则。

建议字段：

```text
id
strategy_route_policy_id
rule_code
display_name
description
priority
action
match_conditions
selected_strategy_definition_id
status
enabled
valid_from_utc
valid_to_utc
rule_hash
created_at_utc
updated_at_utc
```

### 9.1 priority

priority 必须是确定性非负整数，数字越小优先级越高。

同一 Policy 中可以存在相同优先级，但最高优先级同时匹配多条 Rule 时必须 blocked，不得依靠数据库返回顺序或 Rule ID 选择。

### 9.2 action

允许值：

```text
select_strategy
no_strategy
```

约束：

```text
select_strategy → selected_strategy_definition_id 非空；
no_strategy     → selected_strategy_definition_id 为空。
```

Rule 不得输出策略权重、目标仓位或订单动作。

### 9.3 match_conditions

`match_conditions` 是小型、结构化、可校验的条件对象。

允许字段：

```text
regime_codes                   = 允许匹配的 regime_code 列表；
minimum_regime_confidence      = 可选最小分类明确程度；
minimum_classification_margin  = 可选最小类别区分程度；
regime_score_thresholds        = 可选、按已登记 regime_code 设置的最低评分。
```

匹配语义固定为：

```text
未出现的条件字段表示不限制；
同一 Rule 内所有已配置条件使用 AND；
regime_codes 使用包含判断；
minimum 字段使用大于或等于；
regime_score_thresholds 中每项均须达到对应阈值；
空 match_conditions 表示无条件匹配；
未知字段或未知 regime_code 使 Rule 配置非法。
```

禁止引用：

```text
DomainSignalValue；
AtomicSignalValue；
账户或持仓；
策略历史表现；
复盘输出；
当前服务器时间；
任意未登记 JSON 路径。
```

`match_conditions` 不得保存完整历史序列或不可控大 JSON。

### 9.4 valid_from_utc 与 valid_to_utc

可选有效窗口只使用 UTC。

规则：

```text
使用 MarketRegimeSnapshot.analysis_close_time_utc 判断；
不得使用任务执行当前时间改变同一输入的结果；
valid_from_utc 包含边界；
valid_to_utc 不包含边界；
窗口非法时 Rule 配置无效。
```

### 9.5 rule_hash

至少覆盖：

```text
policy_id；
rule_code；
priority；
action；
规范化 match_conditions；
selected_strategy_definition_id；
valid_from_utc；
valid_to_utc。
```

`enabled` 与 `status` 是运行配置；本次冻结状态必须写入 Decision 证据。

## 10. StrategyRouteDecision

StrategyRouteDecision 是在一份明确 MarketRegimeSnapshot 上形成的一次不可变路由事实。

建议字段：

```text
id
market_regime_snapshot_id
strategy_route_policy_id
strategy_analysis_release_id
strategy_analysis_release_hash
matched_strategy_route_rule_id
selected_strategy_definition_id
business_request_key
strategy_route_decision_key
strategy_route_schema_version
route_outcome
matched_conditions
selection_reason
fallback_used
fallback_reason
status
is_usable
allows_strategy_signal
policy_status
policy_enabled
policy_version
condition_schema_version
rule_set_hash
definition_hash
eligible_strategy_definition_ids
evidence_items
evidence_text_zh
payload_summary
error_code
error_message
analysis_close_time_utc
calculated_at_utc
latency_ms
created_at_utc
```

### 10.1 业务外键

必须通过真实外键形成：

```text
StrategyRouteDecision
→ MarketRegimeSnapshot
→ DomainSignalSet
→ AtomicSignalSet
→ FeatureSet
→ MarketSnapshot
```

Decision 必须绑定 StrategyRoutePolicy。

selected 结果必须绑定 StrategyDefinition。

所有 created Decision 必须绑定实际匹配的 StrategyRouteRule。selected 结果还必须绑定真实 StrategyDefinition 外键；no_strategy 结果的 StrategyDefinition 外键必须为空。

### 10.2 strategy_route_decision_key

唯一身份至少覆盖：

```text
market_regime_snapshot_id；
strategy_route_schema_version；
definition_hash。
```

不得包含 trace_id、task id、当前时间、编排 ID 或随机数。

### 10.3 不可变性

Decision 一旦 created：

```text
不得更换 MarketRegimeSnapshot；
不得更换 Policy 或 Rule；
不得改写 route_outcome；
不得改写 selected StrategyDefinition；
不得事后启用 fallback；
不得因 StrategyDefinition 后续停用而修改历史选择；
重新路由必须生成身份不同的新 Decision。
```

### 10.4 状态与放行

```text
created selected    → is_usable = true  → allows_strategy_signal = true；
created no_strategy → is_usable = true  → allows_strategy_signal = false；
failed              → is_usable = false → allows_strategy_signal = false；
unknown             → is_usable = false → allows_strategy_signal = false。
```

blocked 不创建 StrategyRouteDecision。正式服务不得创建只用于后台研究的 Decision，后台研究结果写入隔离对象。

## 11. 策略候选与选择校验

StrategyRoutingService 只把明确候选 StrategyDefinition 转换为 DTO。

版本包策略切片中的策略身份必须至少满足：

```text
定义身份完整；
StrategyDefinition 身份与版本包冻结值一致。
```

规则匹配前，Service 只校验 Rule 和 fallback 引用的 StrategyDefinition 是否属于本轮冻结版本包策略切片、外键是否真实存在、定义身份是否与冻结值一致。不得因为某个尚未命中的规则目标当前不可执行，就在匹配前静默删除该 Rule 或改写目标。

匹配完成后，若唯一命中的 `select_strategy` 目标需要进入 selected 结果，Service 才校验该目标是否满足正式可执行条件：

```text
status = active；
enabled = true；
对应 StrategySignal calculator 精确可用；
算法需求文档和 implementation 实现记录已在 CI、构建和版本包批准阶段通过一致性验证；
StrategyDefinition 身份与版本包冻结值一致。
```

Rule 选择 selected_strategy_definition_id 后，Service 必须再次校验：

```text
引用属于冻结策略集合；
与 Policy 或 matched Rule 的目标一致；
外键仍存在；
生命周期和启用状态未在冻结前失效；
没有发生版本替换。
```

冻结完成后外部配置发生变化，不得改变本次 Decision；后续新请求使用新配置。

## 12. fallback

fallback 默认关闭。

只有以下条件全部满足才允许：

```text
Policy.fallback_policy = explicit；
fallback_strategy_definition_id 非空；
原选择目标已由有效 Policy 或 Rule 明确产生；
唯一最高优先匹配 Rule 的 action = select_strategy；
原选择目标属于冻结策略集合但当前不可执行；
fallback StrategyDefinition 位于冻结策略集合；
fallback StrategyDefinition active + enabled；
fallback StrategySignal calculator 精确可用；
fallback 算法需求文档和 implementation 实现记录已在 CI、构建和版本包批准阶段通过一致性验证；
Service 明确记录 fallback_used = true；
Decision 完整记录 fallback_reason。
```

fallback 不允许用于：

```text
没有任何 Rule 匹配；
同优先级 Rule 冲突；
MarketRegimeSnapshot 不可用；
Policy 配置非法；
Rule 配置非法；
Rule 目标不属于版本包策略切片；
版本包冻结 Rule 缺失、被停用或指纹不一致；
规避 no_strategy 动作。
```

fallback 不能跨过 StrategySignal、DecisionSnapshot、OrderPlan 或 RiskCheck 的任何边界。

## 13. 稳定规则匹配业务逻辑

### 13.1 Service 职责

StrategyRoutingService 负责：

```text
校验服务入口和幂等键；
读取并校验 MarketRegimeSnapshot；
解析并冻结 StrategyRoutePolicy；
读取、校验并冻结版本包 Rule 集合；
读取并冻结 Rule 与 fallback 引用的 StrategyDefinition 身份；
校验 condition_schema_version；
逐条判断 Rule 条件；
确定唯一最高优先匹配 Rule；
执行 select_strategy 或 no_strategy；
校验选中 StrategyDefinition 的注册和可执行性；
按明确配置处理 fallback；
决定 is_usable 和 allows_strategy_signal；
事务写入 StrategyRouteDecision；
处理幂等、并发、unknown、恢复和 AlertEvent。
```

新增、停用或更换 StrategyDefinition 只修改策略注册与 RouteRule，不修改 Service 主流程。

### 13.2 条件判断顺序

对每条 active + enabled Rule，Service 固定执行：

```text
1. 使用 analysis_close_time_utc 检查有效窗口；
2. 校验 match_conditions schema；
3. 判断 regime_codes；
4. 判断 minimum_regime_confidence；
5. 判断 minimum_classification_margin；
6. 判断 regime_score_thresholds；
7. 记录逐项匹配证据。
```

`regime_score_thresholds` 引用的每个环境类别都必须存在于 MarketRegimeSnapshot 的完整评分映射中。评分缺失表示上游 MarketRegimeSnapshot 不满足输出合同，StrategyRouting 不得把缺失分数猜成 0，也不得忽略该条件继续匹配。

条件判断不得访问数据库补充其他市场事实，也不得改变 MarketRegimeSnapshot。

### 13.3 选择与结果映射

```text
唯一最高优先匹配 select_strategy Rule → 校验并选择其 StrategyDefinition；
唯一最高优先匹配 no_strategy Rule     → created + no_strategy；
最高优先级多条匹配                    → blocked；
没有 Rule 匹配                         → blocked；
条件或数据格式异常                     → failed；
持久化结果无法确认                     → unknown。
```

### 13.4 明确禁止

StrategyRoutingService 不得：

```text
读取 DomainSignalValue、AtomicSignalValue、FeatureValue 或 Kline；
调用 MarketRegimeService 补算；
查询策略表现；
修改 MarketRegimeSnapshot、Policy、Rule 或 StrategyDefinition；
同时选择多个策略；
执行 StrategySignal calculator；
输出策略方向、强度、置信度或权重；
读取账户、持仓、价格、订单或风控结果。
```

## 14. 策略注册边界

StrategyRouting 本身不注册路由算法。

策略注册由 StrategyDefinition 和 StrategySignal calculator 共同承担。

路由只允许选择同时满足以下条件的策略：

```text
StrategyDefinition 已登记；
status = active；
enabled = true；
位于本轮 StrategyAnalysisRelease 策略切片；
策略算法名称和版本完整；
对应 StrategySignal calculator 已注册；
对应算法需求文档和 implementation 实现记录已在 CI、构建和版本包批准阶段通过一致性验证；
定义指纹与版本包冻结值一致。
```

StrategyRouting 可以校验策略注册状态，但不得调用 StrategySignal calculator，也不得理解策略内部算法。

## 15. 默认模板与运行时配置

必须区分：

```text
default_strategy_routing_definitions.py = 受代码管理的 Policy / Rule 模板；
StrategyRoutePolicy 表             = 可供组合选择的 Policy 库；
StrategyRouteRule 表               = Policy 的版本化规则；
StrategyAnalysisRelease 路由与策略切片 = 正式运行时配置。
```

正式路由只读取本轮 StrategyAnalysisRelease 唯一选择的 Policy、其 Rule 集合和策略切片。

Service 不得把默认模板直接用于路由，也不得自动恢复 retired、disabled 或人工停用配置。

当前 P0 已存在默认路由模板，覆盖 `context_structure_regime_v1` 输出的 13 种市场环境。模板只定义 Policy / Rule，不创建 StrategyDefinition。被 Rule 引用的 StrategyDefinition 必须已经由 StrategySignal 层完成算法需求、calculator、StrategyDefinition 和版本包策略切片登记。

## 16. seed_strategy_routing

必须提供幂等初始化入口：

```bash
python manage.py seed_strategy_routing
```

命令只负责：

```text
读取项目中明确存在的 Policy / Rule 模板；
规范化 match_conditions；
计算 rule_hash、rule_set_hash 和 definition_hash；
校验 StrategyDefinition 外键；
校验 policy_version、condition_schema_version、Rule action 和 fallback；
校验被引用 StrategyDefinition 的注册状态；
按完整定义身份幂等写入；
输出初始化摘要。
```

命令不得：

```text
发明策略映射；
创建不存在的 StrategyDefinition；
生成 StrategyRouteDecision；
调用 StrategyRoutingService；
恢复 retired 或 disabled 配置；
覆盖人工 enabled 或修改任何 StrategyAnalysisRelease；
引用未注册或不可用 StrategyDefinition 时激活 Policy。
```

没有已确认模板时，命令必须返回零变更摘要。当前存在 P0 默认模板时，若被引用 StrategyDefinition 尚未 active + enabled，命令必须 fail-closed，不得创建半成品 Policy / Rule。

## 17. 规则版本与文档边界

StrategyRouting 的匹配逻辑已经由本需求固定，不属于 `StrategyCalculator` 算法域，不要求创建路由算法需求文档或路由 calculator 实现记录。

需要版本化的是：

```text
StrategyRoutePolicy.policy_version；
condition_schema_version；
StrategyRouteRule.rule_hash；
Policy.rule_set_hash；
Policy.definition_hash。
```

新增、删除或修改具体市场环境到策略的映射，只产生新的 Policy / Rule 配置身份，不产生新的路由算法。

策略本身的计算逻辑、算法需求文档和 implementation 实现记录属于 StrategySignal：

```text
算法需求文档放在 requirements 下的策略算法目录；
implementation 实现记录放在 docs/implementation/strategy_signal/。
```

## 18. 验证与正式发布

路由规则至少验证：

```text
确定性重放；
时间顺序回测；
样本外验证；
Rule 覆盖率；
Rule 冲突率；
no_strategy 频率；
策略切换频率；
环境分类边界附近的稳定性；
策略选择对整体策略表现的增量影响；
fallback 行为；
消融测试。
```

Policy 与 StrategyDefinition 在各自配置库中平权。正式资格只属于经过验证、人工批准并启用的完整 StrategyAnalysisRelease。

后台研究与回测服务可以自由选择 Policy、Rule、StrategyDefinition 和上下游算法组合，但结果必须写入隔离研究对象，不得写入正式 StrategyRouteDecision，也不得调用正式 StrategyRoutingService 的绕过入口。

## 19. StrategyRoutingService 主流程

正式入口流程：

```text
1. 接收 market_regime_snapshot_id、StrategyAnalysisRelease 身份、business_request_key、trace_id、trigger_source；
2. 校验请求字段；
3. 按 business_request_key 查询已有结果；
4. 读取 MarketRegimeSnapshot；
5. 校验 status、is_usable、allows_strategy_routing 和版本包身份；
6. 校验 StrategyAnalysisRelease 的批准、启用和 release_hash；
7. 读取版本包唯一绑定的 StrategyRoutePolicy；
8. 校验 Policy 的 active、enabled、definition_hash 和 rule_set_hash；
9. 读取并校验版本包冻结的 RouteRule 集合，任一冻结 Rule 缺失、不可用或指纹失配即 blocked；
10. 校验 Rule action、条件、优先级、窗口和 hash；
11. 读取并冻结版本包策略切片；
12. 校验 Rule 目标策略和 fallback 目标均位于策略切片且身份一致；
13. 生成 strategy_route_decision_key；
14. 按 key 查询已有完整 Decision；
15. 使用固定条件语义逐条判断 Rule；
16. 确定唯一最高优先匹配 Rule；
17. 执行 selected 或 no_strategy 动作；
18. 校验命中目标策略是否可执行，必要时按明确配置处理 fallback；
19. 校验 route_outcome 和选中策略；
20. 生成不可变 StrategyRouteDecision；
21. 在数据库事务中正式写入；
22. 写必要 AlertEvent；
23. 返回结构化业务结果。
```

## 20. 写库与事务

StrategyRouteDecision 必须在数据库事务中正式写入。

要求：

```text
使用 transaction.atomic() 或等价 Django 事务；
数据库唯一约束保护 business_request_key 和 strategy_route_decision_key；
写入前完成规则匹配、策略目标和结果合同校验；
Decision 与必要 AlertEvent 按项目事件事务规则写入；
不得在事务中访问外部服务；
不得在事务中等待其他模块；
事务失败不得留下 created 半成品。
```

## 21. 幂等与并发

### 21.1 重复请求

```text
已有 created → 返回已有 Decision；
前次 blocked 未形成 Decision → 重新校验本轮冻结版本包与上游前置事实，仍不满足则继续 blocked；
已有 failed → 返回已有失败结果，受控恢复可重新核验；
已有 unknown → 先查证，不重新路由。
```

blocked 不创建 StrategyRouteDecision。重复触发同一业务动作时，不得为了幂等创建伪造 Decision；告警重复由 AlertEvent 幂等、提醒间隔或运维问题去重控制。

### 21.2 相同输入身份

以下身份相同不得产生两份相同正式 Decision：

```text
market_regime_snapshot_id；
strategy_route_schema_version；
definition_hash；
运行语义。
```

### 21.3 并发冲突

依靠数据库唯一约束、原子创建和必要的短期 Redis 锁。

Redis 锁失效不能破坏数据库唯一性。

## 22. unknown 与恢复

持久化结果不明确时：

```text
不得假设写入失败；
不得立即重新执行规则匹配；
按 business_request_key 查询；
按 strategy_route_decision_key 查询；
核对 MarketRegimeSnapshot、Policy、Rule、StrategyDefinition 和 hash；
无法确认时保持 unknown 并告警。
```

不得覆盖已 created 的 Decision 重新路由。

受控恢复不得使用后来改变的 Policy 或 Rule 替换历史冻结配置。

## 23. StrategySignal 消费合同

StrategySignal 只允许消费：

```text
StrategyRouteDecision.status = created；
StrategyRouteDecision.route_outcome = selected；
StrategyRouteDecision.is_usable = true；
StrategyRouteDecision.allows_strategy_signal = true；
selected_strategy_definition_id 非空；
被选 StrategyDefinition.status = active；
被选 StrategyDefinition.enabled = true；
被选 StrategyDefinition 位于同一 StrategyAnalysisRelease 策略切片。
```

StrategySignal 必须：

```text
接收明确 strategy_route_decision_id；
使用 Decision 绑定的唯一 StrategyDefinition；
不得重新路由；
不得自行选择其他 StrategyDefinition；
不得使用 no_strategy、blocked、failed、unknown、后台研究或其他版本包的 Decision；
记录实际消费的 Decision 和 StrategyDefinition。
```

no_strategy 结果由编排 adapter 映射为本轮策略链正常停止，不生成 StrategySignal，也不写异常 AlertEvent。

## 24. 与 MarketRegime 和 StrategySignal 的关系

```text
MarketRegime 决定环境类别；
StrategyRouting 根据环境和路由配置选择策略；
StrategySignal 执行被选策略并生成策略判断。
```

边界：

```text
MarketRegime 不选择策略；
StrategyRouting 不重新分类市场环境；
StrategyRouting 不执行策略；
StrategySignal 不重新选择策略；
三层通过正式业务对象和外键衔接。
```

## 25. 与编排层的关系

StrategyRouting 是业务模块，不承担编排职责。

业务追溯链：

```text
StrategyRouteDecision
→ MarketRegimeSnapshot
→ DomainSignalSet
→ AtomicSignalSet
→ FeatureSet
→ MarketSnapshot
```

业务表不得保存或查询 OrchestrationRun ID、StepRun ID、步骤序号或编排内部状态。

`StrategyRoutingStepAdapter` 负责：

```text
调用正式 StrategyRoutingService；
理解 selected、no_strategy、blocked、failed 和 unknown；
selected → 允许编排继续 StrategySignal；
no_strategy → 本轮策略链正常结束；
blocked / failed / unknown → 按统一步骤合同停止并告警；
返回 strategy_route_decision_id 和对象引用。
```

编排关联只提供整轮快捷查询，不替代业务外键。

## 26. AlertEvent

至少覆盖：

```text
strategy_routing_blocked；
strategy_routing_failed；
strategy_routing_unknown；
strategy_route_policy_unavailable；
strategy_route_policy_conflict；
strategy_route_policy_invalid；
strategy_route_rule_invalid；
strategy_route_rule_conflict；
strategy_route_no_match；
selected_strategy_not_registered；
selected_strategy_unavailable；
fallback_strategy_unavailable；
strategy_route_output_invalid。
```

正常 selected 不写 AlertEvent。

显式 no_strategy 是正常路由结果，不写 AlertEvent。

StrategyRouting 只写 AlertEvent，不直接发送 Hermes。

## 27. 配置规则

允许环境配置：

```text
STRATEGY_ROUTE_SCHEMA_VERSION；
短期幂等锁 TTL；
单次最大 Rule 数量；
单次最大候选 StrategyDefinition 数量；
Decimal 精度和统一舍入规则；
单次规则匹配最大允许执行时长。
```

不允许通过 env 动态改变：

```text
Policy.policy_version；
Policy.condition_schema_version；
Rule match_conditions；
Rule priority；
StrategyDefinition 目标；
fallback 配置；
Policy / Rule 生命周期；
enabled；
StrategyAnalysisRelease 的 Policy 与策略切片；
优先级和条件匹配语义；
策略注册状态。
```

环境配置必须进入 `.env.example` 并带中文注释。

## 28. 服务、任务与命令边界

### 28.1 service

核心业务流程放在 service/domain 层。

StrategyRoutingService 不得包含具体市场环境映射、算法分支或策略代码硬编码。

### 28.2 Celery task

task 只接收参数、传递 trace_id 和 trigger_source、调用 Service、返回可序列化摘要。

task 不得实现规则匹配、读取策略表现或直接写 Decision。

### 28.3 management command

正式入口：

```bash
python manage.py route_strategy --market-regime-snapshot-id <id> --strategy-analysis-release-id <id> --strategy-analysis-release-hash <hash> --business-request-key <key> --trigger-source manual --trace-id <id>
```

command 只解析参数、调用 Service 和输出结果。

至少输出：

```text
strategy_route_decision_id；
status；
route_outcome；
selected_strategy_definition_id；
fallback_used；
allows_strategy_signal；
error_code。
```

## 29. 时间与精度

所有业务时间使用 UTC。

Rule 有效窗口必须使用 MarketRegimeSnapshot.analysis_close_time_utc 判断，不使用服务器当前时间。

相同 MarketRegimeSnapshot、Policy、Rule 集合和策略注册状态必须得到确定性一致结果。

Decimal 必须规范序列化，不得保存 NaN 或 Infinity。

## 30. 日志与审计

结构化日志至少包含：

```text
trace_id；
trigger_source；
business_request_key；
market_regime_snapshot_id；
strategy_route_decision_id；
strategy_route_decision_key；
strategy_route_policy_id；
matched_strategy_route_rule_id；
selected_strategy_definition_id；
route_outcome；
fallback_used；
policy_version；
condition_schema_version；
rule_set_hash；
definition_hash；
status；
allows_strategy_signal；
latency_ms；
error_code。
```

日志不得包含密钥、完整历史序列、账户信息或交易建议。

## 31. dry-run 与 confirm-write

dry-run 必须：

```text
读取明确 MarketRegimeSnapshot；
执行与正式模式相同的 Policy、Rule、策略注册和条件匹配校验；
不写 StrategyRouteDecision；
不写正式 AlertEvent；
不允许 StrategySignal 消费内存结果；
明确 persisted = false。
```

confirm-write 如提供，只控制是否落库，不得改变路由选择、fallback 或放行标准。

## 32. 测试要求

至少覆盖：

```text
1. StrategyRoutePolicy 可以创建。
2. StrategyRouteRule 可以绑定 Policy。
3. policy_version 和 condition_schema_version 必填。
4. rule_hash、rule_set_hash 和 definition_hash 稳定。
5. 同一 Policy 至少有一条 active + enabled Rule。
6. StrategyRouting 不注册或解析路由 calculator。
7. 本轮冻结版本包选择的 Policy 必须为 active 且 enabled。
8. 配置库允许同时存在多个 active 且 enabled 的 Policy。
9. 版本包未选择 Policy 时 blocked。
10. 版本包选择多个 Policy 时 blocked。
11. Policy、rule_set_hash 或策略切片指纹不一致时 blocked。
12. 未被本轮冻结版本包选择的 Policy 不参与正式路由。
13. 正式入口不能覆盖 Policy、Rule、条件或选中策略。
14. MarketRegimeSnapshot 不存在时 blocked。
15. MarketRegimeSnapshot 非 created 时 blocked。
16. MarketRegimeSnapshot.is_usable = false 时 blocked。
17. allows_strategy_routing = false 时 blocked。
18. 正式入口拒绝后台研究结果和其他版本包的 MarketRegimeSnapshot。
19. 相同冻结输入和规则产生确定性结果。
20. 选中目标不可用且无 fallback 时 blocked。
21. Service 只使用版本包冻结 Rule。
22. match_conditions 不能引用未开放字段。
23. Rule action 只允许 select_strategy / no_strategy。
24. select_strategy 必须绑定 StrategyDefinition。
25. no_strategy 不得绑定 StrategyDefinition。
26. 显式 no_strategy 生成 created 且 allows_strategy_signal = false。
27. 没有 Rule 匹配不能伪装成 no_strategy。
28. 多个不同优先级 Rule 匹配时选择 priority 数字最小的 Rule。
29. 同优先级冲突时 blocked。
30. Rule 有效窗口使用 analysis_close_time_utc。
31. 选中策略必须属于版本包冻结策略集合。
32. 选中策略必须 active + enabled。
33. 版本包策略切片之外的 StrategyDefinition 不得被正式 Rule 选择。
34. 不自动替换策略版本。
35. fallback 默认关闭。
36. explicit fallback 只使用绑定策略。
37. fallback 不处理无匹配和 Rule 冲突。
38. fallback 只处理已命中 select_strategy 目标当前不可执行，不处理版本包冻结 Rule 缺失或指纹失配。
39. 空 match_conditions 可以作为无条件规则。
40. 同一 Rule 内条件使用 AND。
41. regime_codes 使用包含判断。
42. minimum 条件使用大于或等于。
43. regime_score_thresholds 引用的评分缺失时不得猜成 0。
44. 未知条件字段使 Rule 配置非法。
45. 未登记 regime_code 使 Rule 配置非法。
46. Service 不读取 MarketRegimeSnapshot 合同外的市场字段。
47. Service 不同时选择多个策略。
48. Service 不输出策略权重。
49. Decision 正确绑定 MarketRegimeSnapshot 和 Policy。
50. 所有 created Decision 记录 matched Rule。
51. selected Decision 绑定 StrategyDefinition。
52. Decision 冗余保存 Policy、条件 schema 和 Rule 集合身份。
53. strategy_route_decision_key 对相同身份稳定。
54. 相同 business_request_key 重复执行返回已有结果。
55. 并发执行只生成一份相同身份 Decision。
56. 事务失败不留下 created 半成品。
57. unknown 先查证，不直接重新路由。
58. created Decision 不被覆盖。
59. seed 命令幂等。
60. seed 不发明策略映射。
61. seed 不创建 StrategyDefinition。
62. seed 不恢复停用配置。
63. 没有模板时 seed 返回零变更。
64. 策略注册变化不要求修改路由 Service 主流程。
65. 路由没有独立 StrategyCalculator 算法需求文档或 implementation 实现记录。
66. dry-run 执行相同规则匹配但不写库。
67. dry-run 结果不能进入 StrategySignal。
68. StrategyRouting 不读取 DomainSignalValue、AtomicSignalValue 或 FeatureValue。
69. StrategyRouting 不调用 MarketRegimeService 补算。
70. StrategyRouting 不读取策略表现。
71. StrategyRouting 不执行 StrategySignal。
72. StrategyRouting 不生成 DecisionSnapshot。
73. StrategyRouting 不读取账户、持仓或 PriceSnapshot。
74. StrategyRouting 不请求 Binance。
75. StrategyRouting 不调用大模型。
76. StrategyRouting 不保存或查询编排 ID。
77. no_strategy 由 adapter 映射为正常结束。
78. 全部业务时间使用 UTC。
79. 后台研究服务可以自由组合 Policy 和策略，但不写正式 Decision。
80. 正式服务不存在 allow_candidate、ignore_approval 或 use_latest 等绕过参数。
```

P0 路由目标族还必须额外覆盖：

```text
多个 regime_code 可以通过不同 RouteRule 映射到同一个 StrategyDefinition；
bullish_trend_continuation 可以通过 Rule 选择 long_trend_following / v1；
bullish_breakout 可以通过 Rule 选择 long_trend_following / v1；
bullish_pullback 与 bullish_high_range 可以通过 Rule 选择 long_pullback_support / v1；
bearish_trend_continuation 可以通过 Rule 选择 short_trend_following / v1；
bearish_breakdown 可以通过 Rule 选择 short_trend_following / v1；
bearish_rebound 与 bearish_low_range 可以通过 Rule 选择 short_rebound_pressure / v1；
bullish_top_reversal_candidate 在没有专门 StrategyDefinition 时必须通过显式 Rule 进入 no_strategy；
bearish_bottom_reversal_candidate 在没有专门 StrategyDefinition 时必须通过显式 Rule 进入 no_strategy；
neutral_range、high_risk_environment、unclear_environment 必须通过显式 Rule 进入 no_strategy；
上述映射均不得写入 StrategyRoutingService 主流程；
如果 RouteRule 条件粒度不足，Service 不得读取 DomainSignalValue 补判。
```

具体 StrategySignal 算法测试由对应策略算法需求文档定义，implementation 实现记录补充代码级测试入口；路由 Rule 条件测试属于本模块业务测试。

## 33. 验收方式

实现完成后至少执行：

```bash
pytest tests/strategy_routing/
python manage.py seed_strategy_routing
python manage.py route_strategy --market-regime-snapshot-id <id> --strategy-analysis-release-id <id> --strategy-analysis-release-hash <hash> --business-request-key <key> --trigger-source manual --trace-id <id>
```

版本包未选择可用 Policy 时，正式入口正确结果：

```text
status = blocked；
error_code = strategy_route_policy_unavailable；
allows_strategy_signal = false；
不生成伪造 StrategyDefinition 选择；
写对应 AlertEvent。
```

显式 no_strategy 正确结果：

```text
status = created；
route_outcome = no_strategy；
selected_strategy_definition_id 为空；
is_usable = true；
allows_strategy_signal = false；
不写异常 AlertEvent；
adapter 将本轮策略链正常结束。
```

数据库至少检查：

```text
Policy、Rule 和 StrategyDefinition 外键完整；
hash 可复算；
Decision 正确绑定 MarketRegimeSnapshot；
Decision 的 StrategyAnalysisRelease 身份、Policy 和策略切片一致；
matched_conditions、selection_reason 和 fallback 证据完整；
selected / no_strategy 放行字段正确；
重复调用没有生成第二份相同身份 Decision；
业务表没有保存编排 ID。
```

## 34. 模块影响声明

```text
读写 MySQL：是，读取 MarketRegimeSnapshot、StrategyRoutePolicy、StrategyRouteRule、StrategyDefinition，写 StrategyRouteDecision 和必要 AlertEvent；
访问 Redis：可选，仅用于短期锁、幂等和缓存；
访问 Binance：否；
调用 BinanceGateway：否；
发送 Hermes：否；
调用大模型：否；
涉及真实交易：否；
涉及 FeatureLayer：不直接读取；
涉及 AtomicSignal：不直接读取；
涉及 DomainSignal：不直接读取；
涉及 MarketRegime：只消费 MarketRegimeSnapshot；
涉及 StrategyRouting：是，本模块自身；
涉及 StrategySignal：只提供选定策略，不执行策略；
涉及 DecisionSnapshot：否；
涉及账户、PriceSnapshot、OrderPlan、RiskCheck 或 Execution：否；
写 AlertEvent：阻断、失败、未知、Policy/Rule 冲突、策略不可用或输出非法；
dry-run：可计算但不写正式业务对象；
confirm-write：如提供，只控制落库，不改变选择结果。
```

异常处理：

```text
业务前置条件不满足 → blocked；
规则解析、匹配或结果校验失败 → failed；
持久化无法确认 → unknown；
显式不选择策略 → created + no_strategy；
任何非 created selected 结果都不得进入 StrategySignal。
```

## 35. 明确禁止

StrategyRouting 禁止：

```text
自行查找最近 MarketRegimeSnapshot；
读取 DomainSignalValue、AtomicSignalValue、FeatureValue 或 Kline；
调用 MarketRegimeService 补算；
修改 MarketRegimeSnapshot；
在 Service 中硬编码环境到策略映射；
自动选择策略的其他版本；
同时选择多个策略；
输出策略权重；
读取策略表现在线切换；
没有 Rule 匹配时伪装成 no_strategy；
未经配置启用 fallback；
执行 StrategySignal 算法；
输出策略方向、强度或置信度；
生成目标仓位；
生成 CandidateOrderIntent；
执行 RiskCheck；
提交订单；
请求 Binance；
调用大模型参与实时判断；
直接发送 Hermes；
保存或查询编排 ID；
让编排关联替代业务外键。
```

## 36. 最终验收标准

StrategyRouting 验收通过必须满足：

```text
MarketRegimeSnapshot 是唯一正式上游边界；
Decision 与 MarketRegimeSnapshot、Policy、Rule 和 StrategyDefinition 形成清晰业务外键；
路由使用固定、确定性的优先级规则匹配；
策略采用注册制，新增或停用策略不修改 Service 主流程；
一次正式路由最多选择一个策略；
多个 MarketRegime 可以通过 RouteRule 映射到同一个 StrategyDefinition；
selected 与 no_strategy 语义明确；
没有匹配与显式 no_strategy 明确区分；
fallback 默认关闭且只能显式启用；
Policy、Rule 和候选策略完整冻结；
StrategyRouting 不注册或调用路由 calculator；
Policy、Rule、条件 schema 和匹配语义完整；
具体环境映射不写入 Service；
StrategySignal 算法需求文档和 implementation 实现记录归属于策略模块；
后台研究 Decision 和其他版本包 Decision 不进入 StrategySignal；
只有 created + selected + allows_strategy_signal = true 的正式 Decision 可被消费；
no_strategy 使本轮策略链正常结束；
MySQL 保存正式事实，Redis 只承担辅助能力；
业务外键独立于编排关联；
全部时间使用 UTC；
不访问 Binance；
不调用大模型；
不执行策略；
不生成目标仓位或订单；
不涉及真实交易；
不违反项目交易红线。
```

StrategyRouting 的最终定位是：

```text
根据一份明确 MarketRegimeSnapshot 和一套冻结、版本化、可验证的路由配置，确定性地选择一个 StrategyDefinition 或明确 no_strategy，并生成可审计的 StrategyRouteDecision，但不执行策略、不生成交易判断。
```
