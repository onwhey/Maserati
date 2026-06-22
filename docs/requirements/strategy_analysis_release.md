# StrategyAnalysisRelease 需求说明

## 1. 模块定位

StrategyAnalysisRelease 是从 FeatureLayer 到 DecisionSnapshot 的策略分析版本包。

它负责把一组已实现的特征、原子信号、领域信号、市场背景、路由规则、策略和目标仓位决策定义冻结为一个可追溯、可验证、可批准、可切换和可回滚的完整组合。

正式策略分析链路为：

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

正式运行不得在运行时临时拼装各层“当前最新”定义。编排开始时必须选择并冻结一份已批准、已启用的完整 StrategyAnalysisRelease；本轮后续步骤只使用该冻结版本包。

## 2. 业务目标

StrategyAnalysisRelease 必须解决：

```text
各层算法版本独立演进后被随意混用；
上游公式改变后下游仍沿用旧批准结论；
正式编排读取到尚未验证的候选定义；
同一轮运行中途切换版本；
历史决策无法还原当时的完整算法组合；
回滚时只回滚一部分层级而形成未验证组合；
后台回测结果污染正式业务事实。
```

## 3. 两种策略算法运行边界

### 3.1 正式运行

正式运行只允许使用当前唯一已批准并已启用的 StrategyAnalysisRelease。

正式运行必须：

```text
在编排开始时解析当前版本包；
冻结版本包 ID、版本指纹和各层组件身份；
每个模块只运行版本包指定的定义和算法版本；
不读取版本包之外的候选定义；
不在一轮中途切换版本包；
任一必需组件缺失、失配或已失效时 fail-closed；
没有合格的当前版本包时不得开始正式策略分析。
```

### 3.2 后台研究与回测

所有未纳入当前正式版本包的算法、定义、参数和版本组合，只允许通过后台研究与回测边界运行。

后台可以在可用算法库中自由选择：

```text
特征定义和算法版本；
原子信号定义和算法版本；
领域定义、原子依赖和聚合算法版本；
市场背景分类算法版本；
策略路由政策和规则版本；
策略定义、参数和算法版本；
策略质量和目标仓位决策版本。
```

后台研究与回测必须：

```text
记录完整选择组合和稳定指纹；
复用与正式运行相同的 calculator 实现；
使用独立的研究或回测运行入口；
不得调用正式 service 的“忽略批准”开关；
不写入正式 FeatureSet、AtomicSignalSet、DomainSignalSet、MarketRegimeSnapshot、StrategyRouteDecision、StrategySignal 或 DecisionSnapshot；
不改变当前正式版本包；
不进入正式订单链路；
不触发真实交易。
```

后台研究、自由组合和回测界面的详细功能不属于本文档；本文档只固定其与正式运行的隔离边界。

## 4. 核心原则

### 4.1 算法平权

所有已实现、已注册并通过文档、代码和测试一致性验证的 calculator 及其不可变版本，在已验证算法目录中保持平权。

算法代码不得内置：

```text
正式算法；
候选算法；
实习算法；
观察算法；
默认主策略；
回测专用公式。
```

一个算法版本是否运行，由后台回测组合或当前正式 StrategyAnalysisRelease 是否选中它决定。

### 4.2 版本不可变

同一 algorithm_name + algorithm_version 的计算行为不得发生不兼容变化。

```text
计算公式变化 → 新 algorithm_version；
参数、输入依赖、阈值或业务含义变化 → 新 Definition 身份；
版本包组件或依赖关系变化 → 新 StrategyAnalysisRelease；
展示名称和不影响计算的说明变化 → 不改变计算身份。
```

历史算法、历史定义、历史版本包和历史业务结果不得被覆盖。

### 4.3 完整组合批准

批准对象是完整 StrategyAnalysisRelease，不是单独一个 calculator 名称。

批准覆盖版本包内每个组件的：

```text
定义身份；
算法名称与版本；
参数指纹；
输入依赖；
阈值和边界规则；
输出合同；
跨层依赖闭包。
```

已批准版本包不得原地增删组件、替换版本或修改参数。

### 4.4 新组合不继承旧批准

任一会改变计算语义、输入依赖或输出的组件发生变化，必须形成新的候选 StrategyAnalysisRelease。

影响范围至少包括：

```text
特征变化 → 依赖该特征的原子信号以及所有后续层级重新验证；
原子信号变化 → 依赖该信号的领域以及所有后续层级重新验证；
领域变化 → MarketRegime 以及所有后续层级重新验证；
MarketRegime 或路由变化 → 策略与目标仓位决策重新验证；
策略变化 → 策略质量与目标仓位决策重新验证。
```

旧的已批准版本包仍然可以继续运行。新组合只有在完成整体验证和人工批准后才能替换它。

### 4.5 正式结果与研究结果隔离

正式结果与研究、回测结果必须在运行身份、业务对象、幂等键、查询入口和下游消费资格上明确隔离。

不得仅依靠调用方记住过滤某个布尔字段保障隔离。

## 5. 版本包范围

StrategyAnalysisRelease 必须冻结以下组件：

```text
特征定义集合和对应 calculator 版本；
原子信号定义集合和对应 calculator 版本；
领域定义集合、原子归属和聚合 calculator 版本；
MarketRegimeDefinition 和 calculator 版本；
StrategyRoutePolicy、StrategyRouteRule 和冻结策略定义集合；
StrategyDefinition 集合和 calculator 版本；
StrategySignalQualityRuleSet 规则与版本；
DecisionPolicyDefinition 和目标仓位 calculator 版本。
```

以下内容不属于 StrategyAnalysisRelease：

```text
DataCollection、DataQuality、DataBackfill 和 MarketSnapshot；
BinanceGateway 与 DeepSeekGateway；
Binance Account Sync 与 PriceSnapshot；
OrderPlan、RiskCheck、ExecutionPreparation 和 Execution；
OrderStatusSync、FillSync、PerformanceMetrics 和 AIReview。
```

## 6. 正式版本包完整性

候选或待批准版本包可以在后台逐步编辑，但只有完成以下校验才能批准：

在执行各层完整性校验前，版本包内被选中的所有定义、规则、规则集和目标仓位决策定义，都必须仍处于可被正式版本包选择的状态。

可选择状态以各模块 Definition、Policy、Rule、RuleSet 和 DecisionPolicyDefinition 的 active / enabled / 可用性约束为准。不可用、被禁用、已失效、缺少可解析 calculator 或不满足模块自身可选条件的组件，不得被批准进入新的正式 StrategyAnalysisRelease。

### 6.1 特征与原子信号

```text
每个被选原子信号声明的所有 feature_code 均存在于被选特征集合；
被选特征的 calculator 全部已注册；
被选原子信号的 calculator 全部已注册；
原子信号实际使用的特征身份与版本包完全一致；
不存在未选特征的隐式回退或替代。
```

### 6.2 原子信号与领域

```text
每个被选正式原子信号必须且只能归属一个被选领域；
每个领域声明的 required 原子信号全部被选；
一个领域不得读取其 allowed 列表之外的原子信号；
同一原子证据不得在多个被选领域内重复计算；
领域 calculator 与依赖配置全部已注册并可解析。
```

### 6.3 正式领域齐备

当前正式 StrategyAnalysisRelease 必须同时包含：

```text
trend；
momentum；
volatility。
```

三个领域均必须有明确定义、完整必需原子依赖、可解析 calculator 和合法输出合同。

任一领域缺失时不得批准版本包，正式编排也不得临时跳过该领域。

### 6.4 MarketRegime、路由与策略

```text
MarketRegimeDefinition 的 required domain 完全由当前版本包提供；
路由政策只引用版本包内的 MarketRegime 类别和 StrategyDefinition；
路由规则选中的所有策略均存在于冻结策略定义集合；
不存在指向版本包之外策略的 fallback；
所有被选策略的 calculator、参数和输入依赖完整；
版本包恰好选择一个 StrategySignalQualityRuleSet；
版本包恰好选择一个 DecisionPolicyDefinition；
质量规则与目标仓位规则对当前策略输出合同兼容。
```

### 6.5 禁止隐式选择

完整性校验必须拒绝：

```text
自动选择最新 algorithm_version；
自动选择“最接近”参数；
自动用同名但不同定义的上游结果代替；
在运行时追加版本包之外的 active 定义；
因某个版本不可用而悄然回退到历史版本。
```

## 7. 指纹与不可变性

### 7.1 release_hash

每个 StrategyAnalysisRelease 必须根据规范化后的完整组件清单和依赖关系生成 `release_hash`。

`release_hash` 至少覆盖：

```text
各层定义主键与不可变定义指纹；
各层 algorithm_name + algorithm_version；
参数指纹；
输入依赖和领域归属；
路由政策、规则顺序和 fallback；
策略候选集合；
质量检查和目标仓位决策合同。
```

不影响计算语义的展示名称、说明文字和界面排序可以不进入 `release_hash`。

### 7.2 已批准后不可修改

当版本包完成批准后：

```text
不得增删 ReleaseItem；
不得替换 Definition；
不得修改参数或依赖；
不得重算并覆盖 release_hash；
不得将另一套组合伪装成原版本包。
```

任何会改变 `release_hash` 的修改都必须复制为新候选版本包。

## 8. 数据模型

### 8.1 StrategyAnalysisRelease

建议字段：

```text
id
release_code
display_name
description
release_hash
approval_status
is_active
validation_evidence_count
approved_at_utc
activated_at_utc
deactivated_at_utc
created_by
approved_by
activated_by
created_at_utc
updated_at_utc
```

### 8.2 approval_status

允许状态：

```text
draft
validating
approved
rejected
invalidated
```

含义：

```text
draft       = 后台正在组装，可编辑；
validating  = 已冻结待验证，不得修改组件；
approved    = 已有完整证据并经授权管理员批准；
rejected    = 验证或人工审查未通过；
invalidated = 批准后发现缺陷或安全问题，禁止新正式运行使用。
```

`is_active = true` 只允许与 `approval_status = approved` 组合。

### 8.3 StrategyAnalysisReleaseItem

版本包不得只用一个不受控大 JSON 保存全部组件。

建议用 ReleaseItem 逐项绑定：

```text
id
strategy_analysis_release_id
component_type
component_id
component_code
definition_hash
algorithm_name
algorithm_version
params_hash
dependency_hash
sort_order
created_at_utc
```

`component_type` 至少支持：

```text
feature_definition
atomic_signal_definition
domain_signal_definition
market_regime_definition
strategy_route_policy
strategy_route_rule
strategy_definition
strategy_signal_quality_rule_set
decision_policy_definition
```

ReleaseItem 是版本包快照索引，不替代被引用定义的真实业务外键和不可变指纹。

### 8.4 StrategyAnalysisReleaseApproval

每次批准、拒绝或失效操作必须保存独立审计记录，不得只覆盖 Release 当前状态。

建议字段：

```text
id
strategy_analysis_release_id
release_hash
action
validation_evidence_refs
reason
operator_id
operated_at_utc
```

### 8.5 StrategyAnalysisReleaseActivation

每次启用、停用和回滚必须保存独立操作记录。

建议字段：

```text
id
strategy_analysis_release_id
release_hash
action
previous_release_id
operator_id
reason
operated_at_utc
```

### 8.6 StrategyAnalysisReleaseValidationEvidence

每份用于批准的验证证据必须保存为可审计对象，不得只用零散文本、外部链接或临时任务日志代替。

建议字段：

```text
id
strategy_analysis_release_id
release_hash
evidence_type
evidence_ref
summary
created_by
created_at_utc
```

`evidence_type` 至少可表达：

```text
dependency_closure_check
calculator_registry_check
backtest_result
test_result
manual_review
```

验证证据必须绑定当时的 `release_hash`。如果版本包组件、参数或依赖发生变化导致 `release_hash` 改变，旧验证证据不得被直接复用为新版本包的批准证据。

## 9. 验证证据与人工批准

### 9.1 验证证据

版本包进入 approved 前必须具有可追溯验证证据。

验证证据至少要证明：

```text
验证使用的组合指纹与 release_hash 一致；
必需依赖和输出合同完整；
所有 calculator 的算法需求文档和 implementation 实现记录已由 CI、构建或算法目录验证确认存在且身份一致；
不存在前视偏差；
不存在重复证据计分；
相同输入和版本组合可以确定性复现；
回测与正式 calculator 使用同一实现；
所有必需测试和验收项通过。
```

验证证据必须写入 StrategyAnalysisReleaseValidationEvidence，并由批准记录引用。批准流程不得只依赖后台页面当前显示内容、临时日志或人工口头确认。

具体收益率、回撤、稳定性、样本外表现和参数敏感性门槛，由后续后台回测与策略治理需求明确。StrategyAnalysisRelease 不自行猜测全局通用数值。

### 9.2 人工批准

回测、自动测试或验证证据具备不得自动将版本包改为 approved。

批准必须：

```text
由具有策略发布批准权限的管理员显式发起；
审查当前 release_hash 对应的验证证据；
再次校验完整依赖闭包；
记录批准人、时间、原因和证据引用；
通过专用审批 service 在数据库事务中执行。
```

不得通过以下方式伪造批准：

```text
修改 .env；
修改 calculator 代码默认值；
仅修改 Definition.status；
直接更新数据库 is_active；
仅因回测任务成功就自动放行。
```

## 10. 启用、切换与回滚

### 10.1 唯一当前版本包

全系统同一时刻最多只能有一个 `approval_status = approved + is_active = true` 的 StrategyAnalysisRelease。

唯一性必须由数据库约束、原子切换 service 和必要的短期 Redis 锁共同保护。Redis 失效不能破坏数据库最终唯一性。

### 10.2 启用

启用前必须：

```text
状态为 approved；
release_hash 与批准记录一致；
所有组件仍存在且指纹一致；
所有 calculator 仍可精确解析；
完整性和依赖闭包再次校验通过；
操作人具有策略发布启用权限；
明确记录启用原因。
```

启用操作必须在单一数据库事务中：

```text
停用原当前版本包；
启用目标版本包；
写入 Activation 审计记录；
写入必要 AlertEvent。
```

### 10.3 切换生效边界

版本包切换只影响切换后新开始的编排运行。

已经开始的编排运行必须继续使用开始时冻结的 StrategyAnalysisRelease，不得因后台切换而中途改变。

如需停止已开始的运行，必须由编排取消机制或人工运维操作显式处理，不得通过改变版本包来反向篡改已生成业务事实。

### 10.4 回滚

回滚只能选择一个历史上已批准、当前未 invalidated、组件仍可精确解析的完整 StrategyAnalysisRelease。

回滚必须整包执行，禁止：

```text
只回滚特征但保留新原子信号；
只回滚领域但保留新 MarketRegime；
只回滚策略但保留不兼容的决策规则；
在回滚时临时拼装一套未批准组合。
```

## 11. 正式编排合同

### 11.1 开始时冻结

正式 PipelineOrchestrator 在调用 FeatureLayer 之前必须：

```text
解析当前唯一已批准并已启用版本包；
校验 release_hash 与 Activation 事实；
将 strategy_analysis_release_id 和 release_hash 冻结到 OrchestrationRun；
冻结各层 ReleaseItem 集合；
版本包不存在或无效时结束本轮，不得进入 FeatureLayer。
```

StrategyAnalysisRelease 是策略配置事实，不是编排 ID。业务模块不保存 `orchestration_run_id`，也不通过编排反向查询业务输入。

### 11.2 模块切片

编排业务衔接器必须从冻结版本包中向每个模块提供该模块的精确 ReleaseItem 切片和预期定义集指纹。

业务模块必须：

```text
只读取传入切片指定的 Definition；
精确解析每个 calculator 版本；
计算实际 definition_set_hash；
与版本包的预期指纹比对；
任一 Definition 缺失、多出、指纹失配或 calculator 无法解析时返回 blocked；
不得因数据库中存在其他 active 定义而追加运行。
```

正式运行时不得读取 Markdown 文件重新验证文档存在性；运行时只校验精确 calculator 身份、本轮冻结版本包指纹和批准阶段已经形成的验证证据。

### 11.3 业务追溯

每个模块的正式业务对象继续保存自身真实业务外键、逐项定义绑定和定义集指纹。

业务对象不得仅依赖 StrategyAnalysisRelease 外键解释自身计算语义，也不得用版本包替代 FeatureValue、AtomicSignalValue、DomainSignalValue 等实际证据关联。

OrchestrationRun 可以记录 StrategyAnalysisRelease 作为本轮策略配置快捷索引，但该关联不替代业务对象自身外键链。

## 12. 模块执行约束

### 12.1 FeatureLayer

```text
只计算版本包选中的 FeatureDefinition；
不自动追加数据库中其他 active 特征；
特征依赖、calculator 和指纹必须与版本包一致。
```

### 12.2 AtomicSignal

```text
只计算版本包选中的 AtomicSignalDefinition；
所有 feature_code 依赖必须由同一版本包的 FeatureDefinition 提供；
不计算未选中原子信号，不生成观察原子结果。
```

### 12.3 DomainSignal

```text
只计算版本包选中的 DomainSignalDefinition；
只读取版本包已分配给该领域的 AtomicSignalDefinition 结果；
正式版本包必须同时生成 trend、momentum 和 volatility 结果；
不生成观察领域结果。
```

### 12.4 MarketRegime

```text
只使用版本包唯一指定的 MarketRegimeDefinition；
同一版本包仍必须生成 trend、momentum、volatility 三个领域结果，但 MarketRegime Calculator 只接收其 Definition.allowed_domain_codes 声明允许的子集，并要求 required_domain_codes 完整；
不提供正式链路内的观察分类入口。
```

### 12.5 StrategyRouting

```text
只使用版本包指定的 Policy、Rule 和 StrategyDefinition 集合；
不使用版本包之外的 fallback；
不提供正式链路内的观察路由入口。
```

### 12.6 StrategySignal

```text
只执行正式 RouteDecision 在版本包策略集合中选中的 StrategyDefinition；
不提供正式链路内的观察策略入口；
版本包之外的策略只能通过后台研究与回测边界执行。
```

### 12.7 StrategySignalQuality 与 DecisionSnapshot

```text
只消费同一版本包的正式 StrategySignal；
只使用版本包唯一选择的 StrategySignalQualityRuleSet；
只使用版本包唯一选择的 DecisionPolicyDefinition；
检查整条业务证据链的定义集指纹与版本包一致；
任一层身份不一致时禁止生成可进入 OrderPlan 的 DecisionSnapshot。
```

## 13. 服务与后台边界

### 13.1 正式 service

正式业务 service 必须强制执行版本包切片和指纹校验。

正式 service 禁止提供：

```text
ignore_approval；
allow_candidate；
observation_definition_id；
use_latest_version；
fallback_to_previous_version；
任何可绕过版本包的通用参数。
```

### 13.2 后台研究与回测 service

后台研究与回测 service 不得通过调用正式 service 并传入绕过参数来运行候选组合。

后台 service 应：

```text
读取管理员明确选择的组件身份；
构建与正式 calculator 兼容的不可变 DTO；
通过公共 CalculatorRegistry 调用同一 calculator；
写入独立研究或回测运行与结果对象；
永远不调用 OrderPlan、RiskCheck、ExecutionPreparation 或 Execution。
```

后台 service 与正式 service 可以共享 DTO 构造器、精度规则、依赖校验器和 CalculatorRegistry，但不共享正式业务对象写入器。

### 13.3 管理界面

后续 Ops Console 可以提供：

```text
组装候选版本包；
选择算法和定义版本；
启动回测和查看验证证据；
发起批准、拒绝或失效；
启用已批准版本包；
回滚到历史已批准版本包；
查询版本包、验证和正式运行历史。
```

界面不得直接更新批准或启用字段，只能调用受控业务 service。

## 14. MySQL 与 Redis

MySQL 是以下事实的唯一正式存储：

```text
StrategyAnalysisRelease；
StrategyAnalysisReleaseItem；
StrategyAnalysisReleaseApproval；
StrategyAnalysisReleaseActivation；
StrategyAnalysisReleaseValidationEvidence。
```

Redis 只允许用于：

```text
候选编辑短期锁；
批准和启用短期互斥；
当前版本包短期缓存；
后台回测任务状态。
```

Redis 不得成为批准、启用状态或版本包组件的唯一存储。

## 15. 幂等、并发与事务

### 15.1 组装与冻结

重复提交相同规范化组合必须得到同一 `release_hash`。

相同 `release_hash` 不得被伪装成两个不同内容的已批准版本包。

### 15.2 批准

同一个 validating 版本包的并发批准、拒绝或失效必须串行化。

批准操作与 Approval 记录必须在同一数据库事务中完成。

### 15.3 启用与回滚

切换当前版本包、停用原版本包、写 Activation 记录和 AlertEvent 必须在同一数据库事务中完成。

任何并发情况下都不得出现两个当前版本包。

## 16. 失败处理

### 16.1 无当前版本包

正式编排找不到已批准并已启用版本包时：

```text
本轮在 FeatureLayer 之前结束；
不生成任何正式策略分析对象；
写明确 AlertEvent；
返回 blocked；
不得自动选择上一个版本包。
```

### 16.2 版本包失配

任一业务模块发现实际定义集与冻结切片不一致时：

```text
返回 blocked；
不得使用部分结果继续；
不得动态修复或追加定义；
写 AlertEvent；
编排结束本轮。
```

### 16.3 已启用版本包失效

当前版本包被 invalidated 时：

```text
必须停止新正式编排使用；
如已有另一套合格版本包，仍必须由管理员显式回滚或启用；
系统不得自动切换；
已开始运行是否取消由编排取消机制或人工运维操作另行决定。
```

## 17. AlertEvent 与审计

以下事件必须写 AlertEvent：

```text
strategy_analysis_release_validating；
strategy_analysis_release_approved；
strategy_analysis_release_rejected；
strategy_analysis_release_activated；
strategy_analysis_release_deactivated；
strategy_analysis_release_rollback；
strategy_analysis_release_invalidated；
strategy_analysis_release_missing；
strategy_analysis_release_mismatch。
```

审计日志至少记录：

```text
release_id；
release_hash；
action；
previous_release_id；
operator_id；
validation_evidence_refs；
reason；
trace_id；
operated_at_utc。
```

批准、启用、失效和回滚属于高风险管理操作，必须在 Ops Console 中明确展示完整版本指纹和影响范围，并要求显式确认。

## 18. 权限

至少区分：

```text
strategy_release_viewer        = 查看版本包和验证证据；
strategy_release_editor        = 组装候选版本包；
strategy_release_approver      = 批准、拒绝或失效；
strategy_release_activator     = 启用、停用和回滚。
```

一个账号可以被授予多个权限，但每次操作仍必须独立审计。

本阶段不强制双人复核，但数据结构不得阻碍后续增加双人审批。

## 19. 服务、任务与命令边界

### 19.1 service

核心业务逻辑必须放在 service / domain 层。

至少需要受控能力：

```text
创建和编辑 draft 版本包；
冻结并进入 validating；
验证组件和依赖闭包；
关联验证证据；
批准、拒绝和失效；
启用、停用和回滚；
解析当前正式版本包；
为模块生成冻结 ReleaseItem 切片。
```

### 19.2 management command

后台界面实现前，可以提供受控 management command：

```text
validate_strategy_analysis_release
approve_strategy_analysis_release
activate_strategy_analysis_release
deactivate_strategy_analysis_release
rollback_strategy_analysis_release
invalidate_strategy_analysis_release
```

command 只负责：

```text
解析参数；
识别操作人；
要求明确确认；
调用专用 service；
输出结构化结果。
```

command 不得直接更新批准或启用字段。

### 19.3 Celery task

验证和回测可以通过 Celery task 执行，但批准、启用、失效和回滚不得由无人值守的定时任务自动发起。

## 20. 时间规则

全部时间使用 UTC。

版本包批准时间、启用时间、停用时间、失效时间和审计时间必须使用 UTC，不得用服务器本地时区参与顺序判断。

## 21. 测试要求

至少覆盖：

```text
1. 相同规范化组合生成相同 release_hash。
2. 任一组件、参数或依赖变化会生成不同 release_hash。
3. draft 可编辑，validating 和 approved 不可原地修改组件。
4. 特征与原子依赖不完整时不得批准。
5. 原子信号领域归属缺失或重复时不得批准。
6. trend、momentum 或 volatility 任一缺失时不得批准。
7. MarketRegime、路由、策略、质量或决策依赖不完整时不得批准。
8. 任一被选组件不可用于正式版本包选择时不得批准。
9. 未关联 StrategyAnalysisReleaseValidationEvidence 时不得批准。
10. 回测任务成功不会自动批准。
11. 只有 approved 版本包可以启用。
12. 同时最多一个当前版本包。
13. 切换只影响之后新开始的编排运行。
14. 已开始的运行不会中途切换版本包。
15. 正式编排无当前版本包时在 FeatureLayer 前 blocked。
16. 业务模块只执行版本包切片指定的定义。
17. 业务模块发现定义多出、缺失或指纹失配时 blocked。
18. 后台回测可选择未纳入正式版本包的版本。
19. 后台回测与正式运行复用同一 calculator。
20. 后台回测不调用带绕过参数的正式 service。
21. 后台回测不写正式策略分析业务对象。
22. 正式策略链路不生成候选或观察算法结果。
23. 每轮正式运行从开始到结束只使用启动时冻结的已批准版本包。
24. 失效版本包不得被新正式运行使用。
25. 回滚只能整包执行。
26. 批准、启用、失效和回滚均有独立审计记录。
27. 批准和启用不能由定时任务自动发起。
```

## 22. 验收方式

实现完成后至少执行：

```bash
pytest tests/strategy_analysis_release/
python manage.py validate_strategy_analysis_release --release-id <id>
python manage.py approve_strategy_analysis_release --release-id <id> --evidence-id <id> --confirm
python manage.py activate_strategy_analysis_release --release-id <id> --confirm
```

数据库检查：

```text
Release 与 ReleaseItem 数量一致；
release_hash 可从规范化组件清单复算；
依赖闭包完整；
trend、momentum 和 volatility 完整；
验证证据对象完整且 release_hash 与 Release 一致；
批准记录的 release_hash 与 Release 一致；
当前最多只有一个已批准启用版本包；
启用与回滚记录完整；
OrchestrationRun 冻结的 release_hash 不随后台切换变化；
正式业务对象的定义和指纹与版本包切片一致；
后台回测没有写入正式策略分析表。
```

## 23. 模块影响声明

```text
读写 MySQL：是，保存版本包、组件、批准、启用和审计事实；
访问 Redis：可选，仅用于短期锁和缓存；
访问 Binance：否；
调用 BinanceGateway：否；
调用 DeepSeekGateway：否；
发送 Hermes：否；
调用大模型：否；
涉及真实交易：不直接执行交易，但决定正式策略分析组合；
涉及 FeatureLayer、AtomicSignal、DomainSignal、MarketRegime、StrategyRouting、StrategySignal、StrategySignalQuality 和 DecisionSnapshot：是，冻结其定义与版本组合；
涉及 OrderPlan、RiskCheck、ExecutionPreparation、Execution 和 Tracking：否；
写 AlertEvent：是，批准、启用、切换、回滚、失效和版本失配事件；
后台回测：只定义与正式运行的隔离边界，不实现自由组合界面和回测引擎。
```

## 24. 明确禁止

StrategyAnalysisRelease 禁止：

```text
在正式编排中自由选择算法版本；
使用未批准或未启用的版本包运行正式策略链路；
在同一正式运行中混用多个版本包；
中途切换已开始运行的版本包；
自动使用最新或最接近版本；
将候选或观察定义追加到正式集合；
通过正式 service 的绕过参数运行后台回测；
把后台回测结果写入正式业务表；
让后台回测进入订单链路；
原地修改已批准版本包；
部分回滚；
因回测成功自动批准或启用；
通过 .env、代码默认值或数据库手工更新绕过批准审计；
使用版本包替代真实业务证据链。
```

## 25. 最终验收标准

StrategyAnalysisRelease 验收通过必须满足：

```text
所有已实现、已注册并通过一致性验证的算法版本在已验证算法目录中平权；
正式运行只使用本轮启动时冻结的已批准并已启用完整版本包；
后台研究与回测可选择版本包之外的算法和定义组合；
正式与后台回测复用同一 calculator，不维护两套公式；
后台回测不调用带绕过参数的正式 service；
正式策略链路只运行本轮启动时冻结版本包明确选择的定义与版本；
已批准版本包不可原地修改；
新组合不继承旧批准；
正式版本包同时具备 trend、momentum 和 volatility；
各层依赖闭包完整且无隐式回退；
同一时刻最多一个当前版本包；
一轮编排从开始到结束使用同一 release_hash；
切换只影响新运行，回滚只能整包执行；
批准、启用、失效和回滚都有完整审计；
无当前合格版本包或任一切片失配时 fail-closed；
正式结果和后台研究结果不混用；
正式策略分析运行只使用已批准并已启用的版本包；
不访问 Binance，不调用大模型，不直接执行交易；
不违反项目交易红线。
```
