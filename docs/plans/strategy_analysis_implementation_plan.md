# 策略分析框架实施计划

## 1. 文档目的

本文档用于指导阶段 2 的代码实现。

阶段 2 的目标是实现从 `MarketSnapshot` 到 `DecisionSnapshot` 的策略分析框架：

```text
MarketSnapshot
→ FeatureLayer
→ AtomicSignal
→ DomainSignal
→ MarketRegime
→ StrategyRouting
→ StrategySignal
→ StrategySignalQuality
→ DecisionSnapshot
```

阶段 2 完成后，系统应具备一条可版本化、可冻结、可审计、可测试的策略分析链路。

本文档不指定具体交易策略公式，不发明正式市场环境分类算法，不发明正式目标仓位算法，不进入账户、价格、订单、风控、执行或真实交易链路。

---

## 2. 阶段定位

阶段 2 是策略分析框架阶段。

一句话：

```text
把行情事实转换成一份目标仓位意图快照，但把所有可变化、需要市场验证的算法都隔离到可版本化的 calculator 和 StrategyAnalysisRelease 中。
```

本阶段解决的是：

```text
哪些市场事实进入策略分析；
每一层如何只消费直接上游；
每一层如何保存不可变业务结果；
算法如何注册、版本化和验证；
一轮正式分析如何只使用同一份已批准版本包；
DecisionSnapshot 如何只表达目标仓位意图，而不越权生成订单动作。
```

本阶段不解决：

```text
当前策略是否赚钱；
最终使用哪套正式策略公式；
账户真实持仓是多少；
当前 mark price 是多少；
应该下多少订单；
订单是否通过风控；
是否真实下单。
```

---

## 3. 前置条件

进入本阶段前，应已完成或具备：

```text
阶段 0 项目底座；
阶段 1 行情数据与市场事实；
MarketSnapshot 可以由已通过 DataQuality 的 4h / 1d Kline 生成；
AlertEvent、AuditRecord、trace_id、trigger_source、UTC、MySQL、Redis、测试框架均可用；
测试默认不访问真实 Binance、DeepSeek 或 Hermes。
```

如果阶段 1 尚未完成，本阶段可以先实现纯计算框架、模型、service skeleton 和单元测试，但不得伪造正式 MarketSnapshot 进入完整正式链路。

---

## 4. 文档依据

编码前必须阅读并遵守：

```text
AGENTS.md
README.md
docs/rules/project_invariants.md
docs/requirements/project_scope.md
docs/requirements/project_foundation.md
docs/requirements/system_capabilities.md
docs/requirements/core_contracts.md
docs/requirements/feature_layer.md
docs/requirements/atomic_signals.md
docs/requirements/domain_signals.md
docs/requirements/market_regime.md
docs/requirements/strategy_routing.md
docs/requirements/strategy_signals.md
docs/requirements/strategy_signal_quality.md
docs/requirements/decision_snapshot.md
docs/requirements/strategy_calculator.md
docs/requirements/strategy_analysis_release.md
docs/architecture/system_architecture.md
docs/architecture/data_flow_architecture.md
docs/architecture/module_boundary_architecture.md
docs/architecture/runtime_task_architecture.md
docs/architecture/testing_and_safety_architecture.md
docs/plans/foundation_implementation_plan.md
docs/plans/market_data_implementation_plan.md
docs/plans/implementation_roadmap.md
```

如果本文档与 requirements 冲突，以 requirements 为准，并停止实现向用户确认。

---

## 5. 本阶段核心口径

### 5.1 正式策略分析链路

正式链路只允许：

```text
MarketSnapshot.created
→ FeatureSet.created
→ AtomicSignalSet.created
→ DomainSignalSet.created
→ MarketRegimeSnapshot.created
→ StrategyRouteDecision.created + selected
→ StrategySignal.created
→ StrategySignalQualityResult.created + passed 或允许通过的 warning
→ DecisionSnapshot.created
```

任一层出现：

```text
blocked
failed
unknown
不可用结果
版本包失配
定义缺失
calculator 缺失
```

都必须 fail-closed，不得继续生成下游正式对象。

### 5.2 正式版本包

正式运行只能使用一份：

```text
已批准；
已启用；
release_hash 一致；
依赖闭包完整；
组件指纹完整；
calculator 可精确解析；
验证证据完整；
在本轮开始时已冻结的 StrategyAnalysisRelease。
```

正式 service 不允许读取“数据库中所有 active 定义”来临时拼装链路。

正式 service 也不允许提供：

```text
ignore_approval；
allow_candidate；
use_latest_version；
fallback_to_previous_version；
observation_definition_id；
绕过版本包的通用参数。
```

### 5.3 算法与业务分离

业务 service 负责：

```text
读写业务对象；
校验状态；
冻结版本包切片；
构造 CalculatorInput；
调用 CalculatorRegistry；
校验 CalculatorOutput；
事务写库；
处理幂等、并发、unknown 和 AlertEvent。
```

calculator 只负责：

```text
纯计算；
确定性输出；
返回结构化证据；
返回 succeeded 或 failed。
```

calculator 不得访问：

```text
MySQL；
Redis；
Celery；
Binance；
DeepSeek；
Hermes；
账户；
持仓；
PriceSnapshot；
订单；
编排对象。
```

### 5.4 不发明正式算法

本阶段可以实现策略分析框架、公共 calculator 注册机制、DTO、模型、service、测试和受控命令。

但是：

```text
没有明确算法需求文档的算法版本，不得进入已验证算法目录；
没有 implementation 实现记录的算法版本，不得被 StrategyAnalysisRelease 选中；
没有完整验证证据的版本包，不得批准；
没有已批准并启用的版本包，正式链路必须在 FeatureLayer 前 blocked。
```

如果编码阶段需要为了测试贯通流程，可以使用测试专用 fake calculator 或 fixture，但测试专用对象不得被 seed 为正式版本包，也不得被正式 service 当作可交易策略。

### 5.5 DecisionSnapshot 的边界

DecisionSnapshot 只把质量放行后的标准化 StrategySignal 转换为目标仓位意图。

它不得：

```text
重新判断市场环境；
按趋势策略、震荡策略或策略类型分支；
读取账户、持仓或价格；
读取 BinanceSyncRun；
读取 PriceSnapshot；
生成订单动作；
生成 CandidateOrderIntent；
调用 RiskCheck；
提交订单。
```

`DecisionSnapshot.target_intent` 只允许：

```text
TARGET_POSITION；
NO_TARGET_CHANGE；
NO_TRADE。
```

其中：

```text
TARGET_POSITION = 提出目标总仓位比例；
NO_TARGET_CHANGE = 本轮不提出新的目标仓位变化；
NO_TRADE = 本轮不进入价格和订单链路。
```

`NO_TARGET_CHANGE` 和 `NO_TRADE` 都是本轮不交易的正常终止语义，不是订单动作。

---

## 6. 本阶段实现范围

### 6.1 StrategyCalculator 公共框架

实现公共纯计算框架。

至少包括：

```text
CalculatorInput / CalculatorOutput 基础合同；
各 calculator_type 的 DTO 合同；
CalculatorRegistry；
calculator metadata；
algorithm_name + algorithm_version 唯一注册；
精确 resolve；
缺失版本失败；
重复注册失败；
文档路径 metadata；
禁止依赖扫描或等价测试；
Decimal、NaN、Infinity、除零边界测试。
```

支持的 calculator_type：

```text
feature_layer；
atomic_signal；
domain_signal；
market_regime；
strategy_signal；
decision_policy。
```

明确不支持：

```text
strategy_routing calculator。
```

StrategyRouting 是固定业务规则匹配，不是 calculator 注册制。

### 6.2 StrategyAnalysisRelease

实现策略分析版本包能力。

至少包括：

```text
StrategyAnalysisRelease；
StrategyAnalysisReleaseItem；
StrategyAnalysisReleaseApproval；
StrategyAnalysisReleaseActivation；
StrategyAnalysisReleaseValidationEvidence；
release_hash 生成；
依赖闭包校验；
批准；
启用；
停用；
回滚；
失效；
当前唯一 active release；
为各模块生成冻结切片；
版本包失配 AlertEvent。
```

本阶段可以先提供 management command 作为受控入口。

command 只允许：

```text
解析参数；
要求明确确认；
识别操作人或测试操作人；
调用 service；
输出结构化结果。
```

command 不得直接更新批准、启用字段。

### 6.3 FeatureLayer

实现 FeatureLayer 正式 service。

负责：

```text
接收明确 market_snapshot_id；
接收 StrategyAnalysisRelease 身份和特征切片指纹；
校验 MarketSnapshot 可消费；
只计算版本包选中的 FeatureDefinition；
读取 MarketSnapshot 窗口内的 Kline 值；
构造 FeatureLayer calculator input；
调用精确 algorithm_name + algorithm_version；
写 FeatureSet；
写 FeatureValue；
记录定义集指纹、参数指纹、输入窗口、证据和 hash；
处理幂等、并发、unknown 和 AlertEvent。
```

FeatureLayer 不得：

```text
请求 Binance；
读取账户或持仓；
读取 PriceSnapshot；
生成信号；
判断策略方向；
生成目标仓位；
保存或查询编排 ID。
```

### 6.4 AtomicSignal

实现 AtomicSignal 正式 service。

负责：

```text
接收明确 feature_set_id；
只计算版本包选中的 AtomicSignalDefinition；
校验每个原子信号依赖的 FeatureValue 来自同一个 FeatureSet；
校验 AtomicSignalDefinition 与 FeatureDefinition 依赖闭包一致；
构造 AtomicSignal calculator input；
写 AtomicSignalSet；
写 AtomicSignalValue；
区分正常 neutral、无效、blocked、failed；
记录方向、强度、可空 confidence 和证据。
```

AtomicSignal 不得：

```text
读取 Kline；
重新计算 Feature；
生成 DomainSignal；
生成 StrategySignal；
生成目标仓位；
生成订单语义；
保存或查询编排 ID。
```

### 6.5 DomainSignal

实现 DomainSignal 正式 service。

负责：

```text
接收明确 atomic_signal_set_id；
只计算版本包选中的 DomainSignalDefinition；
校验每个正式 AtomicSignalValue 只能归属一个领域；
正式版本包必须同时具备 trend、momentum、volatility 三个领域；
按领域读取同一 AtomicSignalSet 中的原子信号；
构造 DomainSignal calculator input；
写 DomainSignalSet；
写 DomainSignalValue；
输出领域 direction 或 state_code、strength、coverage_ratio、agreement_ratio 和证据。
```

DomainSignal 不输出通用 confidence，不使用策略权重，不跨领域聚合。

DomainSignal 不得：

```text
读取 FeatureValue；
读取 Kline；
识别 MarketRegime；
选择策略；
生成目标仓位；
保存或查询编排 ID。
```

### 6.6 MarketRegime

实现 MarketRegime 正式 service 和框架。

负责：

```text
接收明确 domain_signal_set_id；
读取版本包唯一 MarketRegimeDefinition；
校验 allowed_domain_codes 与 required_domain_codes；
只把允许使用的 DomainSignalValue 传给 calculator；
required domain 缺失时 blocked；
调用精确 MarketRegime calculator；
写 MarketRegimeSnapshot；
保存 regime_code、regime_scores、regime_confidence、classification_margin 和证据。
```

注意：

```text
当前需求文件没有指定正式 MarketRegime 算法和正式 regime_code 集合。
```

因此编码阶段不得凭空创建正式 MarketRegimeDefinition。

如果没有对应算法需求文档、implementation 实现记录和已验证 calculator：

```text
版本包不得批准；
正式 MarketRegime 入口必须 blocked；
不得用“默认趋势环境”“默认震荡环境”或类似规则临时通过。
```

MarketRegime 不得：

```text
选择策略；
输出策略方向；
输出目标仓位；
读取 AtomicSignalValue；
读取 FeatureValue；
保存或查询编排 ID。
```

### 6.7 StrategyRouting

实现 StrategyRouting 正式 service。

负责：

```text
接收明确 market_regime_snapshot_id；
读取版本包唯一 StrategyRoutePolicy；
读取版本包冻结 StrategyRouteRule 集合；
读取版本包策略切片中的 StrategyDefinition；
按固定优先级规则匹配；
生成 StrategyRouteDecision；
明确 selected 或 no_strategy；
记录命中规则、选择原因、fallback 和证据。
```

StrategyRouting 不使用 calculator。

策略是注册制：

```text
新增策略 = 新增 StrategyDefinition、StrategySignal calculator、算法需求文档、implementation 实现记录、测试和 RouteRule；
不修改 StrategyRoutingService 主流程；
不修改 StrategySignalService 主流程。
```

路由规则固定：

```text
priority 数字越小越优先；
同一 Rule 内条件 AND；
最高优先级多条匹配即 blocked；
没有匹配即 blocked；
只有显式 no_strategy Rule 才能正常不选择策略；
fallback 默认关闭，只允许 explicit fallback。
```

StrategyRouting 不得：

```text
读取 DomainSignalValue 重新判断；
调用 MarketRegimeService 补算；
读取策略历史表现；
同时选择多个策略；
输出策略权重；
执行 StrategySignal；
生成目标仓位。
```

### 6.8 StrategySignal

实现 StrategySignal 正式 service。

负责：

```text
接收明确 strategy_route_decision_id；
只消费 created + selected + allows_strategy_signal 的 StrategyRouteDecision；
读取路由选中的唯一 StrategyDefinition；
沿业务外键找到同一 DomainSignalSet；
只读取 StrategyDefinition.allowed_domain_codes 内的 DomainSignalValue；
校验 required_domain_codes；
构造 StrategySignal calculator input；
调用精确 StrategySignal calculator；
写 StrategySignal；
保存方向、强度、置信评分、预测期限、权重、聚合快照、冲突快照和证据。
```

StrategySignal calculator 是唯一允许使用策略级领域权重的地方。

StrategySignal 不得：

```text
重新路由；
重新计算 MarketRegime；
读取 AtomicSignalValue；
读取 FeatureValue；
读取 Kline；
把 MarketRegime 再次作为权重或方向输入；
生成 target_position_ratio；
生成订单动作。
```

注意：

```text
当前 strategy_signals.md 只定义框架，不指定正式 strategy_code、公式、权重或 prediction_horizon。
```

因此编码阶段不得 seed 正式策略，除非已经存在对应算法需求文档、implementation 实现记录、测试和版本包验证证据。

### 6.9 StrategySignalQuality

实现 StrategySignalQuality 正式 service。

负责：

```text
接收明确 strategy_signal_id；
读取版本包唯一 StrategySignalQualityRuleSet；
校验 StrategySignal 结构完整；
校验 direction、strength、confidence、prediction_horizon；
校验证据和业务追溯；
校验 used_domain_signal_value_ids、权重和快照一致性；
校验数据新鲜度；
写 StrategySignalQualityResult；
写 StrategySignalQualityIssue；
决定是否允许 DecisionSnapshot 消费。
```

StrategySignalQuality 不得：

```text
重新执行 StrategySignal calculator；
修改 StrategySignal；
重新加权 DomainSignal；
读取 AtomicSignalValue；
读取 FeatureValue；
读取 Kline；
读取账户、持仓、PriceSnapshot；
生成 DecisionSnapshot。
```

### 6.10 DecisionSnapshot

实现 DecisionSnapshot 正式 service。

负责：

```text
接收明确 strategy_signal_quality_result_id；
读取版本包唯一 DecisionPolicyDefinition；
校验质量结果允许进入 DecisionSnapshot；
构造 DecisionPolicy calculator input；
调用精确 DecisionPolicy calculator；
校验 target_intent、target_position_ratio、target_confidence；
写 DecisionSnapshot；
处理 TARGET_POSITION / NO_TARGET_CHANGE / NO_TRADE；
为后续 OrderPlan 提供唯一目标仓位快照。
```

DecisionPolicyCalculator 是唯一允许输出 `target_position_ratio` 的 calculator。

DecisionSnapshot 不得：

```text
按 strategy_code 分支；
按 MarketRegime 分支；
按策略类型分支；
读取账户；
读取当前持仓；
读取 PriceSnapshot；
读取 Binance；
生成 CandidateOrderIntent；
调用 RiskCheck；
保存或查询编排 ID。
```

---

## 7. 当前算法实施边界

### 7.1 可以实现的内容

本阶段可以实现：

```text
公共 CalculatorRegistry；
calculator DTO；
calculator metadata；
业务 service 调用 calculator 的标准流程；
算法文档路径一致性验证工具；
测试专用 fake calculator；
已经在 requirements 中明确到足够可编码程度的 calculator；
后台或命令层用于组装、验证、批准和启用 StrategyAnalysisRelease 的基础能力。
```

### 7.2 必须先补需求再实现的内容

以下内容如果没有独立算法需求文档，不得作为正式算法实现：

```text
MarketRegime 正式分类算法；
正式 regime_code 集合；
StrategySignal 正式策略算法；
StrategySignal 领域权重；
DecisionPolicy 正式目标仓位映射公式；
质量规则中会阻断 DecisionSnapshot 的复杂扩展规则。
```

如果编码阶段发现为了完成正式 happy path 必须有这些算法，应先停止编码，补充对应 requirements 算法文档，再继续实现。

### 7.3 测试专用算法限制

测试专用 fake calculator 只能用于：

```text
单元测试；
service contract 测试；
版本包失配测试；
幂等和事务测试；
接口形状测试。
```

测试专用 fake calculator 不得：

```text
进入已验证算法目录；
写入正式 StrategyAnalysisRelease；
由正式 service seed；
作为真实策略运行；
产生可进入订单链路的 DecisionSnapshot。
```

---

## 8. 建议代码模块

具体 Django app 名称可在编码阶段最终确定，但建议：

```text
apps/strategy_calculator/
apps/strategy_release/
apps/feature_layer/
apps/atomic_signals/
apps/domain_signals/
apps/market_regime/
apps/strategy_routing/
apps/strategy_signals/
apps/strategy_signal_quality/
apps/decision_snapshot/
```

约束：

```text
apps/strategy_calculator/ 不定义 Django model，不访问数据库，不注册 Celery task；
apps/strategy_release/ 负责版本包、批准、启用和切片；
其余 app 分别负责各自业务对象、service、selector、repository、薄入口和测试；
不得创建一个包含整条策略链业务逻辑的总 service；
不得让 calculator 直接跨层调用其他 calculator；
不得让编排对象进入业务表。
```

如果编码阶段为了减少 app 数量进行合并，必须保证：

```text
模块边界仍然清楚；
service 职责不混杂；
测试目录仍能按模块定位；
后续拆分不需要改变业务合同。
```

---

## 9. 数据库迁移范围

阶段 2 建议创建以下对象。

### 9.1 StrategyCalculator 相关

StrategyCalculator 本身不需要正式业务表。

可选创建只读算法目录或验证证据索引，但不得把运行结果存在 calculator 模块。

### 9.2 StrategyAnalysisRelease 相关

```text
StrategyAnalysisRelease；
StrategyAnalysisReleaseItem；
StrategyAnalysisReleaseApproval；
StrategyAnalysisReleaseActivation；
StrategyAnalysisReleaseValidationEvidence。
```

### 9.3 FeatureLayer 相关

```text
FeatureDefinition；
FeatureSet；
FeatureValue。
```

### 9.4 AtomicSignal 相关

```text
AtomicSignalDefinition；
AtomicSignalSet；
AtomicSignalValue。
```

### 9.5 DomainSignal 相关

```text
DomainSignalDefinition；
DomainSignalSet；
DomainSignalValue。
```

### 9.6 MarketRegime 相关

```text
MarketRegimeDefinition；
MarketRegimeSnapshot。
```

### 9.7 StrategyRouting 相关

```text
StrategyRoutePolicy；
StrategyRouteRule；
StrategyRouteDecision。
```

### 9.8 StrategySignal 相关

```text
StrategyDefinition；
StrategySignal。
```

### 9.9 StrategySignalQuality 相关

```text
StrategySignalQualityRuleSet；
StrategySignalQualityResult；
StrategySignalQualityIssue。
```

### 9.10 DecisionSnapshot 相关

```text
DecisionPolicyDefinition；
DecisionSnapshot。
```

### 9.11 数据建模共同要求

所有正式业务结果对象必须：

```text
有稳定业务 key 或等价唯一约束；
保存直接上游业务外键；
保存 StrategyAnalysisRelease 身份；
保存 algorithm_name / algorithm_version；
保存 definition_hash / params_hash / schema_version；
保存 status / is_usable / 下游放行字段；
保存 UTC 业务时间；
保存 trace_id / trigger_source；
可追溯到 AlertEvent。
```

禁止：

```text
把完整历史窗口存成大 JSON；
把完整上游对象复制进 evidence；
用 trace_id 当业务外键；
用编排 ID 当业务外键；
让业务表保存或查询 OrchestrationRun ID；
用 Redis 保存正式策略结果；
物理删除已被历史对象引用的 Definition、Policy、Rule、RuleSet 或 Release。
```

---

## 10. 配置范围

所有部署可调配置必须由 Django settings 统一读取，进入 `.env.example` 并附中文注释；测试必须提供明确默认值。

### 10.1 FeatureLayer

```text
FEATURE_SCHEMA_VERSION；
FeatureValue Decimal 精度和统一舍入规则；
短期幂等锁 TTL；
单次允许计算的最大特征数量；
管理命令默认输出格式。
```

### 10.2 AtomicSignal

```text
SIGNAL_SCHEMA_VERSION；
ATOMIC_SIGNAL_FAILURE_BLOCK_RATIO = 0.3；
单次允许计算的最大定义数量；
短期幂等锁 TTL；
Decimal 精度和统一舍入规则。
```

`0.3` 是流程验证阶段的临时默认值。实际运行值必须写入 AtomicSignalSet 供复盘；后续调整必须有回测或运行数据依据。

### 10.3 DomainSignal

```text
DOMAIN_SIGNAL_SCHEMA_VERSION；
单次允许计算的最大领域数量；
短期幂等锁 TTL；
Decimal 精度和统一舍入规则。
```

### 10.4 MarketRegime

```text
MARKET_REGIME_SCHEMA_VERSION；
短期幂等锁 TTL；
Decimal 精度和统一舍入规则；
单次 calculator 最大允许执行时长。
```

### 10.5 StrategyRouting

```text
STRATEGY_ROUTE_SCHEMA_VERSION；
短期幂等锁 TTL；
单次最大 Rule 数量；
单次最大候选 StrategyDefinition 数量；
Decimal 精度和统一舍入规则；
单次规则匹配最大允许执行时长。
```

### 10.6 StrategySignal

```text
STRATEGY_SIGNAL_SCHEMA_VERSION；
短期幂等锁 TTL；
单次最大领域输入数量；
Decimal 精度和统一舍入规则；
calculator 最大允许执行时长。
```

### 10.7 StrategySignalQuality

```text
STRATEGY_SIGNAL_QUALITY_IDEMPOTENCY_LOCK_TTL_SECONDS；
STRATEGY_SIGNAL_QUALITY_MAX_CHECK_COUNT；
STRATEGY_SIGNAL_QUALITY_MAX_EXECUTION_SECONDS。
```

### 10.8 DecisionSnapshot

```text
DECISION_SNAPSHOT_SCHEMA_VERSION；
DECISION_SNAPSHOT_IDEMPOTENCY_LOCK_TTL_SECONDS；
DECISION_SNAPSHOT_MAX_EXECUTION_SECONDS。
```

### 10.9 禁止动态配置的内容

不得通过 `.env` 或运行时配置改变：

```text
Definition.params 或算法公式；
algorithm_name / algorithm_version；
calculator 注册映射；
StrategyAnalysisRelease 选择的任何切片；
路由 Policy、Rule、优先级或目标 StrategyDefinition；
权重、prediction_horizon 或 DecisionPolicyDefinition；
质量 RuleSet、严重程度或放行规则；
target_position_ratio 公式；
账户、持仓或真实交易访问权限；
任何跳过正式策略分析步骤的能力。
```

---

## 11. 实施顺序

### 11.1 实现 StrategyCalculator 公共框架

执行内容：

```text
建立 strategy_calculator package；
定义基础 DTO；
定义 calculator_type；
实现 Registry；
实现 metadata；
实现 resolve / register / validate；
实现禁止依赖测试；
实现确定性和 Decimal 边界测试。
```

验收重点：

```text
calculator 不访问数据库、Redis、网络或当前时间；
缺少精确版本会失败；
不回退相近版本；
CalculatorOutput 不出现 created / blocked / unknown；
StrategyRouting 不被注册为 calculator。
```

### 11.2 实现 StrategyAnalysisRelease

执行内容：

```text
创建版本包模型；
实现 ReleaseItem；
实现 release_hash；
实现完整性校验；
实现验证证据；
实现批准、启用、停用、回滚和失效；
实现当前版本包解析；
实现模块切片输出。
```

验收重点：

```text
同一时刻最多一个 approved + active release；
批准后不可原地修改；
切换只影响新运行；
无当前版本包时正式策略链在 FeatureLayer 前 blocked；
后台研究结果不写正式业务对象。
```

### 11.3 实现定义模型和基础 seed 入口

执行内容：

```text
创建各层 Definition / Policy / Rule / RuleSet / DecisionPolicyDefinition 模型；
实现 definition_hash / params_hash；
实现 active / enabled 生命周期；
实现受控 seed command；
实现 seed 幂等。
```

验收重点：

```text
seed 不发明策略；
seed 不恢复停用配置；
seed 不自动批准版本包；
seed 不把测试 fake calculator 放进正式版本包；
同一业务定义不可变字段不能被覆盖。
```

### 11.4 实现 FeatureLayer

执行内容：

```text
实现 FeatureSet / FeatureValue；
实现 FeatureLayerService；
接入 StrategyAnalysisRelease 特征切片；
接入 FeatureLayer calculator；
实现 dry-run；
实现 command / task 薄入口；
实现测试。
```

验收重点：

```text
只消费 MarketSnapshot；
只计算版本包选中特征；
不请求 Binance；
不生成信号。
```

### 11.5 实现 AtomicSignal

执行内容：

```text
实现 AtomicSignalSet / AtomicSignalValue；
实现 AtomicSignalService；
校验 FeatureSet 和定义依赖；
接入 AtomicSignal calculator；
实现 failure block ratio 相关基础配置；
实现 dry-run；
实现测试。
```

验收重点：

```text
只消费 FeatureSet；
不读取 Kline；
不进入 StrategySignal；
每个正式原子信号必须能归属一个领域。
```

### 11.6 实现 DomainSignal

执行内容：

```text
实现 DomainSignalSet / DomainSignalValue；
实现 DomainSignalService；
校验 trend、momentum、volatility 三领域定义；
校验原子信号唯一归属；
接入 DomainSignal calculator；
实现 dry-run；
实现测试。
```

验收重点：

```text
领域只聚合同领域原子信号；
不跨领域聚合；
不使用策略权重；
正式版本包缺少三领域时不得批准。
```

### 11.7 实现 MarketRegime 框架

执行内容：

```text
实现 MarketRegimeDefinition；
实现 MarketRegimeSnapshot；
实现 MarketRegimeService；
实现 allowed / required domain 校验；
接入 MarketRegime calculator；
实现 blocked 场景；
实现测试。
```

验收重点：

```text
没有正式算法文档和已验证 calculator 时不得生成可消费 MarketRegimeSnapshot；
不发明默认 regime_code；
不选择策略；
不生成目标仓位。
```

### 11.8 实现 StrategyRouting

执行内容：

```text
实现 StrategyRoutePolicy；
实现 StrategyRouteRule；
实现 StrategyRouteDecision；
实现固定优先级匹配；
实现 selected / no_strategy；
实现 explicit fallback；
实现冲突、无匹配、目标不可用处理；
实现测试。
```

验收重点：

```text
路由不使用 calculator；
没有匹配不等于 no_strategy；
一次最多选择一个策略；
策略注册变化不要求改路由 service；
不读取策略表现。
```

### 11.9 实现 StrategySignal

执行内容：

```text
实现 StrategyDefinition；
实现 StrategySignal；
实现 StrategySignalService；
校验 StrategyRouteDecision；
读取同一 DomainSignalSet 的领域输入；
接入 StrategySignal calculator；
实现标准化 direction / strength / confidence / prediction_horizon；
实现测试。
```

验收重点：

```text
只执行路由选定的唯一策略；
MarketRegime 只作为追溯上下文；
权重只在策略层使用一次；
不输出目标仓位或订单动作；
没有正式策略算法文档时不得 seed 正式策略。
```

### 11.10 实现 StrategySignalQuality

执行内容：

```text
实现 StrategySignalQualityRuleSet；
实现 StrategySignalQualityResult；
实现 StrategySignalQualityIssue；
实现质量检查 service；
实现 live / replay / backfill / manual 验证模式；
实现数据新鲜度检查；
实现测试。
```

验收重点：

```text
质量检查不重算策略；
不修改 StrategySignal；
不读取 AtomicSignal、Feature、Kline、账户或 PriceSnapshot；
只有质量放行结果可进入 DecisionSnapshot。
```

### 11.11 实现 DecisionSnapshot

执行内容：

```text
实现 DecisionPolicyDefinition；
实现 DecisionSnapshot；
实现 DecisionSnapshotService；
接入 DecisionPolicy calculator；
实现 TARGET_POSITION / NO_TARGET_CHANGE / NO_TRADE；
实现过期判断；
实现 dry-run；
实现测试。
```

验收重点：

```text
只消费 StrategySignalQualityResult；
不按策略类型二次判断；
不读取账户、持仓或 PriceSnapshot；
不生成订单；
只有 TARGET_POSITION + allows_order_plan 才允许后续 OrderPlan。
```

### 11.12 建立薄入口

本阶段可以建立以下 management command 或等价薄入口：

```text
validate_strategy_analysis_release；
approve_strategy_analysis_release；
activate_strategy_analysis_release；
deactivate_strategy_analysis_release；
build_feature_set；
build_atomic_signal_set；
build_domain_signal_set；
classify_market_regime；
route_strategy；
generate_strategy_signal；
validate_strategy_signal；
build_decision_snapshot。
```

命令只允许：

```text
解析参数；
生成或传递 trace_id；
设置 trigger_source；
调用 service；
输出结构化结果。
```

命令不得写复杂业务逻辑，不得访问外部服务，不得进入订单链路。

### 11.13 建立测试

本阶段测试必须覆盖：

```text
strategy_calculator；
strategy_analysis_release；
feature_layer；
atomic_signals；
domain_signals；
market_regime；
strategy_routing；
strategy_signals；
strategy_signal_quality；
decision_snapshot；
跨模块 contract；
版本包失配；
幂等和并发；
unknown 恢复；
AlertEvent；
dry-run；
禁止外部访问；
禁止编排 ID 进入业务表。
```

---

## 12. 编排边界

本阶段不实现正式 PipelineOrchestrator。

但是所有 service 必须为后续编排做好准备：

```text
接收 business_request_key；
接收 trace_id；
接收 trigger_source；
接收明确上游业务对象 ID；
接收 StrategyAnalysisRelease ID 和 hash；
返回稳定业务 status；
返回业务对象 id；
不保存或查询 orchestration_run_id；
不依赖 Celery task id。
```

后续编排层负责：

```text
在一轮开始时冻结 StrategyAnalysisRelease；
按顺序调用 adapter；
理解每个业务模块返回结果；
记录 OrchestrationRun 与业务对象的一对多快捷关联。
```

业务模块不得为了临时串流程，把编排顺序写进自身 service。

---

## 13. dry-run 规则

本阶段各业务 service 可以支持 dry-run。

dry-run 可以：

```text
读取正式上游对象；
读取版本包切片；
构造相同 CalculatorInput；
调用相同 calculator；
执行相同业务校验；
返回完整摘要。
```

dry-run 不得：

```text
写正式业务对象；
写正式 AlertEvent；
进入下游正式消费；
进入 OrderPlan；
改变版本包批准或启用状态；
使用另一套算法。
```

dry-run 结果必须明确：

```text
persisted = false。
```

---

## 14. AlertEvent 边界

本阶段各模块只写 AlertEvent，不直接发送 Hermes。

需要写 AlertEvent 的典型情况：

```text
strategy_analysis_release_missing；
strategy_analysis_release_mismatch；
calculator_missing；
definition_missing；
definition_hash_mismatch；
upstream_not_consumable；
feature_layer_blocked / failed / unknown；
atomic_signal_blocked / failed / unknown；
domain_signal_blocked / failed / unknown；
market_regime_blocked / failed / unknown；
strategy_routing_blocked / failed / unknown；
strategy_signal_blocked / failed / unknown；
strategy_signal_quality_blocked / failed / unknown；
decision_snapshot_blocked / failed / unknown；
output_contract_invalid；
persistence_unknown。
```

正常情况一般不写异常 AlertEvent：

```text
FeatureSet 正常生成；
AtomicSignalSet 正常生成；
DomainSignalSet 正常生成；
MarketRegimeSnapshot 正常生成；
StrategyRouteDecision selected；
StrategyRouteDecision 显式 no_strategy；
StrategySignal 正常 neutral；
StrategySignalQuality passed；
DecisionSnapshot TARGET_POSITION；
DecisionSnapshot NO_TARGET_CHANGE；
DecisionSnapshot NO_TRADE。
```

AlertEvent 禁止包含：

```text
完整 Kline 历史；
完整上游对象副本；
账户信息；
订单信息；
密钥；
不可控大 JSON；
交易建议式喊单文本。
```

---

## 15. Redis 使用边界

本阶段可以使用 Redis：

```text
短期幂等锁；
短期并发锁；
当前版本包短期缓存；
Celery broker / result backend；
短期任务状态。
```

Redis 不得作为：

```text
StrategyAnalysisRelease 唯一事实来源；
FeatureSet 唯一事实来源；
AtomicSignalSet 唯一事实来源；
DomainSignalSet 唯一事实来源；
MarketRegimeSnapshot 唯一事实来源；
StrategyRouteDecision 唯一事实来源；
StrategySignal 唯一事实来源；
StrategySignalQualityResult 唯一事实来源；
DecisionSnapshot 唯一事实来源；
正式批准、启用和回滚状态唯一来源。
```

Redis 失效不得破坏 MySQL 唯一性和正式事实。

---

## 16. 异常与 unknown 处理

本阶段必须统一保守处理：

```text
blocked = 前置条件、版本包、定义、状态或放行条件不满足；
failed = 已进入处理但计算、校验或事务明确失败；
unknown = 持久化结果或业务结果无法确认；
created = 已生成可审计业务对象；
no_strategy = StrategyRouting 明确正常不选择策略；
NO_TARGET_CHANGE / NO_TRADE = DecisionSnapshot 明确正常不进入订单链路。
```

规则：

```text
unknown 不得当作 created；
blocked 不得创建伪造下游对象；
failed 不得伪装成 neutral；
normal neutral 不得伪装成 failed；
no_strategy 不得伪装成 blocked；
没有路由规则匹配不得伪装成 no_strategy；
NO_TRADE 不得传递为订单动作。
```

unknown 恢复必须先按：

```text
business_request_key；
对应业务对象 key。
```

查询确认，不得直接重新计算并覆盖历史 created 结果。

---

## 17. 本阶段不实现

阶段 2 明确不实现：

```text
Binance Account Sync；
PriceSnapshot；
OrderPlan；
CandidateOrderIntent；
RiskCheck；
ApprovedOrderIntent；
ExecutionPreparation；
Execution；
OrderStatusSync；
FillSync；
PipelineOrchestrator；
RuntimeGuard；
Notifications 投递；
OpsConsole 页面；
PerformanceMetrics；
DeepSeekGateway；
AIReview；
后台自由组合回测界面；
完整回测撮合引擎；
策略收益归因；
自动参数优化；
自动策略上线；
真实交易。
```

本阶段也不得实现：

```text
通过 StrategySignal 直接下单；
通过 DecisionSnapshot 直接下单；
通过质量检查改变策略方向；
通过 MarketRegime 二次放大策略权重；
通过环境变量切换策略算法；
通过后台研究结果进入正式链路；
通过 fake calculator 产生正式交易决策。
```

---

## 18. 外部服务边界

阶段 2 不访问真实外部服务。

禁止：

```text
访问 Binance；
调用 BinanceGateway；
访问 DeepSeek；
调用 DeepSeekGateway；
发送 Hermes；
提交真实订单；
查询账户；
查询持仓；
查询 mark price；
修改交易所杠杆；
修改保证金模式。
```

允许：

```text
读取阶段 1 已落库的 MarketSnapshot；
读取 MySQL 中的策略定义和业务对象；
使用 Redis 做短期锁或缓存；
在测试中使用 fake calculator；
在测试中使用 fixture MarketSnapshot。
```

---

## 19. 测试计划

### 19.1 StrategyCalculator 测试

必须测试：

```text
注册唯一性；
精确版本解析；
缺失版本失败；
不回退相近版本；
metadata 完整；
CalculatorInput 不包含 Django model；
CalculatorOutput 只允许 succeeded / failed；
相同输入确定性一致；
不读取当前时间；
不访问 MySQL / Redis / 网络；
Decimal、NaN、Infinity 和除零边界；
每个注册 calculator 有需求文档路径和 implementation 路径 metadata。
```

### 19.2 StrategyAnalysisRelease 测试

必须测试：

```text
release_hash 稳定；
组件变化导致 release_hash 变化；
draft 可编辑；
validating / approved 不可原地修改；
依赖闭包缺失不得批准；
trend / momentum / volatility 任一缺失不得批准；
MarketRegime / Routing / Strategy / Quality / Decision 依赖不完整不得批准；
未关联验证证据不得批准；
同时最多一个当前版本包；
启用只影响新运行；
回滚只能整包执行；
后台研究不写正式业务对象。
```

### 19.3 FeatureLayer 测试

必须测试：

```text
只消费 MarketSnapshot；
MarketSnapshot 不可用时 blocked；
版本包未选中特征不计算；
definition_set_hash 不一致 blocked；
calculator 缺失 blocked；
FeatureValue 合同非法 failed；
重复请求幂等；
dry-run 不写库；
不请求 Binance。
```

### 19.4 AtomicSignal 测试

必须测试：

```text
只消费 FeatureSet；
依赖 FeatureValue 缺失 blocked；
未选中 AtomicSignalDefinition 不计算；
原子信号不直接进入 StrategySignal；
正常 neutral 为 created；
calculator failed 不伪装 neutral；
失败比例超过阈值阻断；
不读取 Kline。
```

### 19.5 DomainSignal 测试

必须测试：

```text
只消费 AtomicSignalSet；
原子信号领域归属缺失不得批准版本包；
原子信号归属多个领域不得批准版本包；
trend / momentum / volatility 完整；
只读取本领域原子信号；
不使用策略权重；
不输出通用 confidence。
```

### 19.6 MarketRegime 测试

必须测试：

```text
只消费 DomainSignalSet；
只把 allowed_domain_codes 传给 calculator；
required domain 缺失 blocked；
未选中 MarketRegimeDefinition blocked；
calculator 缺失 blocked；
无正式算法文档时不得生成正式可消费结果；
不选择策略；
不生成目标仓位。
```

### 19.7 StrategyRouting 测试

必须测试：

```text
只消费 MarketRegimeSnapshot；
不读取 DomainSignalValue；
固定优先级匹配；
同优先级冲突 blocked；
没有匹配 blocked；
显式 no_strategy 正常 created；
selected 必须绑定版本包内 StrategyDefinition；
fallback 默认关闭；
不读取策略表现；
不使用 calculator。
```

### 19.8 StrategySignal 测试

必须测试：

```text
只消费 StrategyRouteDecision selected；
no_strategy 不进入 StrategySignal；
只执行路由选中的唯一 StrategyDefinition；
allowed_domain_codes 外的 DomainSignalValue 不传给 calculator；
required domain 缺失 blocked；
MarketRegime 不进入 calculator；
权重只应用一次；
输出 direction / strength / confidence / prediction_horizon 标准化；
不输出目标仓位；
不输出订单动作。
```

### 19.9 StrategySignalQuality 测试

必须测试：

```text
只消费 created StrategySignal；
后台研究或其他版本包结果 blocked；
结构完整性；
数值合法性；
证据充分性；
业务追溯；
质量 RuleSet 来自版本包；
warning 放行由 RuleSet 决定；
dry-run 不写库；
不重新执行 StrategySignal calculator。
```

### 19.10 DecisionSnapshot 测试

必须测试：

```text
只消费 StrategySignalQualityResult；
质量不放行时 blocked；
DecisionPolicyDefinition 来自版本包；
calculator 精确版本缺失 blocked；
TARGET_POSITION 时 target_position_ratio 必填且在 [-1, 1]；
NO_TARGET_CHANGE 时 target_position_ratio 为空；
NO_TRADE 时 target_position_ratio 为空；
target_position_ratio = 0.0 不等于 NO_TARGET_CHANGE；
不同 strategy_code 但相同标准化 StrategySignal 输入不得导致 DecisionPolicy 分支；
DecisionSnapshot 不读取账户、持仓、PriceSnapshot 或 Binance；
DecisionSnapshot 不生成 OrderPlan。
```

### 19.11 安全测试

必须测试：

```text
测试默认不访问真实 Binance；
测试默认不访问真实 DeepSeek；
测试默认不发送 Hermes；
测试不能提交订单；
业务表不保存编排 ID；
trace_id 不作为业务幂等键；
AlertEvent 脱敏；
Redis 不可用不破坏 MySQL 正式事实；
无当前 StrategyAnalysisRelease 时正式链路 fail-closed。
```

---

## 20. 阶段验收命令

具体命令以项目实际依赖管理工具为准。

至少需要等价执行：

```text
python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py migrate
pytest tests/strategy_calculator/
pytest tests/strategy_analysis_release/
pytest tests/feature_layer/
pytest tests/atomic_signals/
pytest tests/domain_signals/
pytest tests/market_regime/
pytest tests/strategy_routing/
pytest tests/strategy_signals/
pytest tests/strategy_signal_quality/
pytest tests/decision_snapshot/
pytest
```

如果使用 `uv`：

```text
uv run python manage.py check
uv run python manage.py makemigrations --check --dry-run
uv run python manage.py migrate
uv run pytest
```

如果使用 `poetry`：

```text
poetry run python manage.py check
poetry run python manage.py makemigrations --check --dry-run
poetry run python manage.py migrate
poetry run pytest
```

阶段回报必须说明实际运行了哪些命令。

---

## 21. 阶段通过标准

阶段 2 通过必须满足：

```text
StrategyCalculator 是纯计算框架；
StrategyRouting 不属于 calculator；
正式运行只使用已批准、已启用并在本轮开始冻结的 StrategyAnalysisRelease；
各层只消费直接上游业务对象；
FeatureLayer 只消费 MarketSnapshot；
AtomicSignal 只消费 FeatureSet；
DomainSignal 只消费 AtomicSignalSet；
MarketRegime 只消费 DomainSignalSet；
StrategyRouting 只消费 MarketRegimeSnapshot；
StrategySignal 只消费 StrategyRouteDecision 和同链 DomainSignalSet；
StrategySignalQuality 只验证 StrategySignal；
DecisionSnapshot 只消费 StrategySignalQualityResult；
DecisionSnapshot 不做市场二次判断；
DecisionSnapshot 不读取账户、持仓、价格或 Binance；
DecisionSnapshot 只输出目标仓位意图；
TARGET_POSITION / NO_TARGET_CHANGE / NO_TRADE 语义清楚；
版本包、定义、参数、算法和结果均可追溯；
后台研究与正式业务对象隔离；
MySQL 保存正式事实；
Redis 只作为短期辅助；
所有时间使用 UTC；
测试默认不访问真实外部服务；
不涉及真实交易。
```

---

## 22. 阶段失败标准

出现以下任一情况，本阶段不得通过：

```text
正式 service 读取所有 active 定义临时拼版本包；
正式 service 支持 ignore_approval 或 use_latest；
calculator 查询数据库、Redis、网络或当前时间；
StrategyRouting 被做成 calculator；
StrategySignal 直接读取 AtomicSignalValue；
StrategySignal 把 MarketRegime 再次用于权重或方向；
DecisionSnapshot 按策略类型或 MarketRegime 二次分支；
DecisionSnapshot 读取账户、持仓、PriceSnapshot 或 Binance；
DecisionSnapshot 输出订单动作；
NO_TRADE 被传给订单链路；
没有规则匹配被伪装成 no_strategy；
没有正式算法需求文档却 seed 正式策略；
测试 fake calculator 进入正式版本包；
后台研究结果写入正式业务对象；
业务表保存或查询 OrchestrationRun ID；
Redis 成为正式策略结果唯一事实来源；
测试访问真实 Binance、DeepSeek 或 Hermes；
本阶段提前实现 OrderPlan、RiskCheck、Execution 或真实交易。
```

---

## 23. 交付回报要求

阶段 2 编码完成后，回报必须说明：

```text
本阶段实现了什么；
新增和修改了哪些文件；
主要调用链路是什么；
是否写库；
是否访问 Redis；
是否访问 Binance；
是否发送 Hermes；
是否调用大模型；
是否涉及交易执行；
是否涉及真实交易；
是否涉及 FeatureLayer；
是否涉及 AtomicSignal；
是否涉及 DomainSignal；
是否涉及 MarketRegime；
是否涉及 StrategyRouting；
是否涉及 StrategySignal；
是否涉及 StrategySignalQuality；
是否涉及 DecisionSnapshot；
是否涉及 Binance Account Sync；
是否涉及 PriceSnapshot；
是否涉及 OrderPlan / CandidateOrderIntent；
是否涉及 RiskCheck / ApprovedOrderIntent；
是否涉及 ExecutionPreparation / Execution；
是否写 AlertEvent；
dry-run / confirm-write 行为；
异常处理方式；
测试命令和结果；
本阶段明确不负责什么；
是否违反 project_invariants.md。
```

如测试无法运行，必须说明原因和下一步处理。

---

## 24. 下一阶段入口

阶段 2 验收通过后，下一步进入：

```text
docs/plans/account_price_fact_implementation_plan.md
```

也就是账户与价格事实阶段。

在进入下一阶段前，不应开始 OrderPlan、RiskCheck、ExecutionPreparation、Execution、通知投递、后台复盘或真实交易能力。
