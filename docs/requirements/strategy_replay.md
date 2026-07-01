# StrategyReplay 需求

## 1. 模块定位

StrategyReplay 是策略分析链路的后台离线回放与回测验证模块。

它用于把历史 UTC 4 小时边界重新送入策略分析算法，观察当时系统会如何识别市场、选择策略、生成策略信号和目标仓位语义。

StrategyReplay 的核心定位是：

```text
策略链路离线验证；
历史 4h 周期批量回放；
策略版本包效果观察；
算法调试与人工验收辅助；
后台可删除、可重跑、可清理的研究数据域。
```

StrategyReplay 不是：

```text
正式自动交易主链路；
正式 PipelineOrchestrator；
正式 StrategySignal / DecisionSnapshot 事实来源；
正式订单链路；
模拟交易运行模式；
实盘交易回放器；
自动策略优化器；
自动参数调优系统；
复盘结论生成器。
```

## 2. 核心原则

StrategyReplay 必须与正式编排数据隔离。

规则：

```text
不写正式 MarketSnapshot；
不写正式 FeatureSet / FeatureValue；
不写正式 AtomicSignalSet / AtomicSignalValue；
不写正式 DomainSignalSet / DomainSignalValue；
不写正式 MarketRegimeSnapshot；
不写正式 StrategyRouteDecision；
不写正式 StrategySignal；
不写正式 StrategySignalQualityResult；
不写正式 DecisionSnapshot；
不进入 PriceSnapshot；
不进入 OrderPlan；
不生成 CandidateOrderIntent；
不执行 RiskCheck；
不生成 ApprovedOrderIntent；
不执行 ExecutionPreparation；
不提交订单；
不查询订单状态；
不同步成交；
不写 TradeFill；
不影响 ActiveLock；
不影响 RuntimeGuard；
不影响正式 ReviewDataset；
不触发 Hermes；
不调用大模型；
不参与真实交易。
```

StrategyReplay 可以复用正式 calculator 的计算逻辑，但不得复用正式 service 的“写正式业务对象”路径。

换句话说：

```text
正式链路写正式业务事实表；
StrategyReplay 写独立 replay / backtest 表；
两者可以共享算法实现，不能共享结果对象。
```

## 3. 与正式策略分析链路的区别

正式策略分析链路用于当前真实系统运行：

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

StrategyReplay 只模拟上述分析过程，并把结果写成独立回放对象：

```text
历史 Kline / StrategyAnalysisRelease
→ ReplayMarketSnapshot
→ ReplayFeatureSet
→ ReplayAtomicSignalSet
→ ReplayDomainSignalSet
→ ReplayMarketRegime
→ ReplayStrategyRoute
→ ReplayStrategySignal
→ ReplaySignalQuality
→ ReplayDecision
→ StrategyReplayPeriodResult
```

上述对象名称表示业务语义，不要求代码必须逐一使用相同类名；但实现必须满足“独立 replay 表，不写正式表”的边界。

## 4. 数据隔离要求

StrategyReplay 数据可以包含大量调试、失败、中间版本、bug 修复前后的结果。

因此它必须满足：

```text
可以按 run 删除；
可以按时间范围删除；
可以按版本包删除；
可以重新运行覆盖旧研究结果；
删除 StrategyReplay 数据不得影响正式业务事实；
正式交易链路不得读取 StrategyReplay 数据；
正式 ReviewDataset 默认不得读取 StrategyReplay 数据；
RuntimeGuard 不巡检 StrategyReplay；
AlertEvent 不把 StrategyReplay 的普通失败视为交易异常；
StrategyReplay 失败不影响真实交易运行权限；
StrategyReplay 失败不影响已启用 StrategyAnalysisRelease。
```

正式业务对象不得保存 StrategyReplayRun 作为正式外键。

StrategyReplay 对正式对象只能保存只读引用，例如：

```text
使用了哪个 StrategyAnalysisRelease；
使用了哪段 Kline 时间窗口；
由哪个后台用户触发；
使用了哪个算法版本包 hash。
```

## 5. 数据来源

StrategyReplay 只能读取已落库行情数据和已登记版本定义。

允许读取：

```text
Kline；
StrategyAnalysisRelease；
FeatureDefinition / AtomicSignalDefinition / DomainSignalDefinition；
MarketRegimeDefinition；
StrategyRoutePolicy / StrategyRouteRule；
StrategyDefinition；
StrategySignalQualityRuleSet；
DecisionPolicyDefinition；
对应 calculator 注册表；
必要的算法依赖关系。
```

禁止读取或调用：

```text
Binance Gateway 实时请求；
Binance Account Sync 真实账户快照作为回测账户；
PriceSnapshot 实时价格；
OrderPlan / RiskCheck / Execution 业务对象；
OrderStatusSync / FillSync 业务对象；
真实 ActiveLock；
真实交易运行开关；
.env 中的交易权限或 API key；
DeepSeek 或其他大模型。
```

如果历史 Kline 缺失，StrategyReplay 必须标记该周期失败或缺数据，不得临时请求 Binance 补齐。

补采或回补 Kline 属于 MarketData 能力，不属于 StrategyReplay。

## 6. StrategyAnalysisRelease 约束

StrategyReplay 必须绑定明确的策略版本包。

允许的版本包来源：

```text
已启用 StrategyAnalysisRelease；
已批准但未启用 StrategyAnalysisRelease；
后台明确选择的候选研究版本包。
```

每次 StrategyReplayRun 必须冻结：

```text
StrategyAnalysisRelease id；
release_hash；
各层组件定义 hash；
运行时 calculator 身份；
运行参数；
时间范围；
触发人；
触发原因。
```

如果版本包缺少必要组件、依赖闭包不完整、hash 不一致或 calculator 未注册，本次回放必须失败关闭，不得自动补默认组件。

StrategyReplay 的结果不能自动批准、启用、禁用或修改 StrategyAnalysisRelease。

## 7. 回放周期

StrategyReplay 的默认周期为 UTC 4 小时边界。

后台创建任务时至少支持：

```text
start_analysis_close_time_utc；
end_analysis_close_time_utc；
周期步长 = 4h；
lookback_4h_count；
lookback_1d_count；
StrategyAnalysisRelease；
业务说明 / 运行原因。
```

规则：

```text
所有时间必须是 UTC；
start / end 必须落在 UTC 4h 边界；
回放点按时间正序执行和展示；
单个周期失败不应默认中断整批任务，除非用户选择 fail-fast；
每个周期必须记录成功、无策略、阻断或失败原因；
每个周期必须能追溯到使用的版本包和输入窗口。
```

## 8. 核心对象

StrategyReplay 至少需要以下业务对象语义。

### 8.1 StrategyReplayRun

表示一次后台回放任务。

至少表达：

```text
回放任务身份；
时间范围；
周期数量；
StrategyAnalysisRelease 身份；
运行状态；
触发人；
运行原因；
创建时间；
开始时间；
结束时间；
成功数量；
失败数量；
阻断数量；
无策略数量；
结果摘要 hash。
```

### 8.2 StrategyReplayPeriodResult

表示某一个 UTC 4 小时回放点的结果。

至少表达：

```text
所属 StrategyReplayRun；
analysis_close_time_utc；
analysis_reference_time_utc；
周期状态；
停止阶段；
原因码；
市场大背景摘要；
趋势摘要；
动能摘要；
结构摘要；
波动摘要；
风险摘要；
市场环境结果；
策略路由结果；
策略信号摘要；
信号质量摘要；
目标仓位语义摘要；
是否产生目标仓位；
是否因高风险或无策略停止；
错误摘要。
```

### 8.3 StrategyReplayStepResult

可选对象，用于记录每个阶段的详细执行状态。

可表达：

```text
FeatureLayer replay 阶段；
AtomicSignal replay 阶段；
DomainSignal replay 阶段；
MarketRegime replay 阶段；
StrategyRouting replay 阶段；
StrategySignal replay 阶段；
StrategySignalQuality replay 阶段；
DecisionSnapshot replay 阶段。
```

### 8.4 StrategyReplayArtifact

可选对象，用于保存较大的导出文件、JSONL 明细或统计摘要。

大批量明细不应塞进单个数据库字段。

如果需要保存大量周期明细，应使用独立文件、分表行或分页查询。

## 9. 输出语义

StrategyReplay 的输出是“当时系统会如何分析”，不是“策略一定正确”。

后台展示至少应能回答：

```text
这段时间系统主要识别出哪些市场环境？
哪些周期选择了策略？
哪些周期没有策略？
哪些周期被风险状态阻断？
策略方向在什么时候发生变化？
目标仓位语义在什么时候变大或变小？
哪些周期的数据质量不足？
哪些周期的算法链路失败？
```

StrategyReplay 不回答：

```text
真实执行是否一定赚钱；
如果下单会不会成交；
真实手续费和滑点是多少；
策略是否应该自动上线；
参数是否应该自动调整；
下一轮是否应该真实交易。
```

真正涉及收益、撮合、手续费、滑点、胜率、最大回撤的能力，应作为后续 BacktestExecution / BacktestPerformance 独立需求，不得混入 StrategyReplay P0。

## 10. OpsConsole 能力

OpsConsole 可以提供 StrategyReplay 页面。

页面至少支持：

```text
创建回放任务；
选择 StrategyAnalysisRelease；
选择 UTC 起止时间；
设置 4h / 1d 回看窗口；
填写运行原因；
查看任务列表；
查看周期结果列表；
按状态、市场环境、策略、方向筛选；
查看单个周期摘要；
删除某次回放任务及其明细；
重新运行同一任务配置。
```

后台页面不得：

```text
把 StrategyReplay 结果写回正式业务对象；
把 StrategyReplay 结果作为正式版本包批准证据自动登记；
自动启用策略版本包；
自动修改当前策略组件工作区；
自动创建订单；
自动修改真实交易运行开关。
```

如果管理员认为某次 StrategyReplay 可作为人工验证证据，只能由人明确复制摘要或通过受控入口登记为 StrategyAnalysisRelease 验证材料；系统不得自动完成批准或启用。

## 11. 删除与清理

StrategyReplay 数据允许删除。

删除规则：

```text
只能删除 StrategyReplay 独立表和独立导出文件；
不得删除 Kline；
不得删除 StrategyAnalysisRelease；
不得删除正式 FeatureSet / StrategySignal / DecisionSnapshot；
不得删除正式 OrchestrationRun；
不得删除正式订单、成交、账户或告警事实；
删除操作必须写审计记录；
删除后不得影响正式链路。
```

支持的清理方式：

```text
按 StrategyReplayRun 删除；
按创建时间删除；
按运行状态删除失败或过期任务；
按版本包删除研究任务；
按操作人和原因记录清理审计。
```

## 12. 与 ReviewDataset 的关系

ReviewDataset 读取正式已落库业务事实，用于整理真实系统运行周期。

StrategyReplay 读取历史数据并生成研究结果。

两者必须隔离：

```text
ReviewDataset 默认不读取 StrategyReplay；
StrategyReplay 不生成 ReviewDatasetRecord；
StrategyReplay 不修改 ReviewDatasetExport；
ReviewDataset 不把 StrategyReplay 当作正式编排事实；
StrategyReplay 可以提供自己的导出文件，但该文件不是 ReviewDataset。
```

如果未来需要把 StrategyReplay 结果提供给离线分析，应新增 StrategyReplayExport 或 BacktestExport，而不是复用 ReviewDatasetExport。

## 13. 与当前开发期 replay 命令的关系

当前开发期命令 `replay_strategy_analysis_chain` 可作为临时链路诊断工具，用于确认现有正式 service 能否按历史窗口跑通。

但它不等于正式 StrategyReplay 后台功能。

正式接入 OpsConsole 前，必须满足：

```text
回放结果写入独立 StrategyReplay 数据对象；
不再把后台回放结果写入正式策略分析事实表；
支持按 run 删除；
支持后台任务状态追踪；
支持人类可读摘要；
支持审计记录；
禁止进入订单链路。
```

如果继续保留开发期命令，必须在命令帮助、文档或实现中明确其开发诊断性质，避免误接入后台正式回测页面。

## 14. AlertEvent、审计与通知

StrategyReplay 普通失败不属于交易异常。

规则：

```text
创建、删除、重跑 StrategyReplayRun 必须写后台审计；
回放任务失败可以写 replay 自身状态；
不要求写正式交易 AlertEvent；
不创建 NotificationDeliveryAttempt；
不创建 NotificationSuppression；
不发送 Hermes；
不触发 RuntimeGuardIssue。
```

只有当 StrategyReplay 暴露系统级错误，例如后台权限绕过、数据隔离失败、误写正式业务表时，才应作为系统安全问题记录告警。

## 15. 测试与验收

实现 StrategyReplay 时至少验证：

```text
按 UTC 起止时间生成正确 4h 周期；
非 4h 边界时间被拒绝；
缺少 Kline 时只标记 replay 周期失败，不请求 Binance；
使用指定 StrategyAnalysisRelease；
版本包 hash 不一致时失败关闭；
回放结果写入独立 replay 表；
不创建正式 MarketSnapshot；
不创建正式 FeatureSet；
不创建正式 StrategySignal；
不创建正式 DecisionSnapshot；
不创建 OrderPlan / CandidateOrderIntent；
不创建 RiskCheck / ApprovedOrderIntent；
不创建 PreparedOrderIntent / OrderSubmissionAttempt；
不写 TradeFill；
不影响 ActiveLock；
不写真实交易 AlertEvent；
删除 StrategyReplayRun 只删除 replay 数据；
正式主链路不会读取 StrategyReplay 表。
```

验收时必须额外说明：

```text
是否真实交易关闭；
是否访问 Binance；
是否写正式业务事实表；
是否写独立 replay 表；
是否可以删除；
是否发送 Hermes；
是否调用大模型；
是否进入订单链路。
```

## 16. 当前阶段边界

当前阶段可以实现：

```text
后台创建策略回放任务；
历史 4h 周期批量分析；
独立 replay 表保存摘要；
任务列表、详情和删除；
紧凑结果展示；
必要的导出雏形。
```

当前阶段不实现：

```text
真实成交撮合；
手续费和滑点模拟；
资金曲线；
最大回撤；
胜率；
策略自动评分；
自动参数优化；
自动修改 StrategyAnalysisRelease；
自动上线策略；
模拟交易运行模式；
任何真实交易动作。
```
