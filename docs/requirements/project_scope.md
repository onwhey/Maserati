# 项目范围说明

## 1. 文档目的

本文档定义本项目当前阶段的项目目标、系统边界、交付范围和不做事项。

本文档用于回答：

```text
这个项目要做什么；
当前阶段做什么；
当前阶段不做什么；
哪些能力只是预留；
什么结果算阶段性交付完成。
```

本文档不定义：

```text
数据库表字段；
Django app 结构；
Celery 任务名称；
交易所接口细节；
策略公式；
回测撮合细节；
前端组件实现；
代码实现方案。
```

具体模块合同由本目录下各模块需求文档定义。

如本文档与更高优先级规则冲突，以更高优先级规则为准。

## 2. 项目定位

本项目是一个中低频趋势跟踪自动交易系统。

系统目标是构建一个从行情数据、特征、信号、目标仓位决策、账户事实、价格事实、订单计划、风控审批、执行准备、交易执行、订单追踪、成交同步、运行巡检、绩效复盘、后台运维和离线 AI 复盘的自动交易闭环。

本项目追求：

```text
数据可信；
链路清晰；
决策可追溯；
风控可审计；
执行可控；
异常可发现；
结果可复盘；
真实交易默认关闭且受强约束。
```

本项目不是：

```text
人工喊单系统；
大模型实时交易系统；
大模型喊单系统；
单纯回测脚本；
单纯交易所 API 下单脚本；
单纯前端展示平台；
自动策略优化平台；
自动参数调优系统。
```

大模型不得参与实时交易决策。

## 3. 当前阶段交易范围

当前阶段围绕最小可验证自动交易闭环建设。

交易范围：

```text
交易所：Binance
交易风格：中低频趋势跟踪
主要驱动：K 线收盘后的周期性分析
运行方式：自动编排 + 明确真实交易权限 + 可审计执行
```

数据采集 P0 范围：

```text
交易所：Binance
市场类型：USDS-M Futures
交易品种：BTCUSDT
数据类型：已收盘 K 线
```

数据采集域不受 active market domain 影响：

```text
DataCollection P0 固定采集 Binance USDS-M BTCUSDT 已收盘 K 线；
active market domain 不得反向改变 DataCollection 的采集对象；
即使交易运行域启用 COIN-M，数据采集仍然保持 Binance USDS-M BTCUSDT；
数据采集域是策略分析数据源，不是交易账户配置。
```

交易模块能力范围：

```text
Binance Account Sync、PriceSnapshot、OrderPlan、RiskCheck、ExecutionPreparation、Execution、OrderStatusSync 和 FillSync 必须支持 USDS-M 与 COIN-M 的 market_type 隔离；
USDS-M 与 COIN-M 必须使用各自独立的账户事实、持仓事实、交易规则、价格事实和数量计算公式；
不得因为数据采集 P0 使用 BTCUSDT / USDS-M，就把交易模块写死为只支持 BTCUSDT / USDS-M。
```

当前阶段交易运行链路只能存在一个 active market domain。

active domain 至少由以下硬配置决定：

```text
exchange
market_type
account_domain
symbol
```

规则：

```text
active market domain 属于部署级硬配置；
后台不得热切换 active domain；
active market domain 只约束交易运行链路，不约束数据采集链路；
非 active domain 不得参与当前主交易链路；
USDS-M 与 COIN-M 事实、公式和交易规则不得混用；
切换 active domain 必须通过部署配置、服务重启和完整验证。
```

策略数据域与交易执行域的映射必须显式配置：

```text
DecisionSnapshot 只表达目标仓位意图，不绑定具体交易所订单；
OrderPlan 负责把目标仓位意图转换为 active market domain 下的 CandidateOrderIntent；
当策略数据域与交易执行域不完全相同时，必须存在明确的映射配置；
没有明确映射配置时，OrderPlan 必须 blocked；
系统不得根据 symbol 名称、市场类型或最近成功记录自动猜测映射。
```

## 4. 当前阶段系统范围

当前阶段包含以下能力或边界：

```text
数据采集；
数据质量检查；
必要时数据回补；
MarketSnapshot；
FeatureLayer；
AtomicSignal；
DomainSignal；
MarketRegime；
StrategyRouting；
StrategySignal；
StrategySignalQuality；
DecisionSnapshot；
StrategyCalculator；
StrategyAnalysisRelease；
DecisionPolicy / DecisionPolicyCalculator；
Binance Gateway；
Binance Account Sync；
PriceSnapshot；
OrderPlan；
CandidateOrderIntent；
RiskCheck；
ApprovedOrderIntent；
ExecutionPreparation；
PreparedOrderIntent；
Execution；
OrderSubmissionAttempt；
OrderStatusSync；
FillSync；
TradeFill / OrderFillSummary；
PipelineOrchestrator；
RuntimeGuard；
PerformanceMetrics；
Notifications / AlertEvent / NotificationDeliveryAttempt / NotificationSuppression；
OpsConsole；
DeepSeekGateway；
AIReview。
```

每个能力必须有清晰边界，不得把策略判断、账户事实、订单意图、风控审批、交易所订单、成交事实和复盘结论混成一个对象。

## 5. 当前阶段主链路

正式主链路：

```text
Binance Account Sync（自动四小时账户边界，编排起始步骤）
→ DataCollection
→ DataQuality
→ 必要时 DataBackfill 与重新质检
→ MarketSnapshot
→ FeatureLayer
→ AtomicSignal
→ DomainSignal
→ MarketRegime
→ StrategyRouting
→ StrategySignal
→ StrategySignalQuality
→ DecisionSnapshot
→ TARGET_POSITION：PriceSnapshot
→ OrderPlanStepAdapter 真实交易权限检查
→ OrderPlan
→ CandidateOrderIntent
→ RiskCheck
→ ApprovedOrderIntent
→ ExecutionPreparation
→ PreparedOrderIntent
→ Execution
→ OrderSubmissionAttempt
→ OrderStatusSync
→ FillSync
→ 订单状态与成交事实同步完成
或 NO_TARGET_CHANGE / NO_TRADE：正常结束，不进入 PriceSnapshot 或订单链路
```

编排、巡检和通知横跨主链路：

```text
PipelineOrchestrator
RuntimeGuard
Notifications / AlertEvent
```

后置复盘和后台能力不属于自动交易主链路必跑步骤：

```text
PerformanceMetrics
OpsConsole
AIReview
```

## 6. 编排范围

当前阶段使用 `OrchestrationRun` 表达一轮业务流程的编排和审计记录。

编排相关对象：

```text
OrchestrationRun；
OrchestrationStepRun；
OrchestrationBusinessObjectLink。
```

编排层职责：

```text
创建一轮运行；
冻结步骤定义；
调用业务衔接器；
保存步骤统一结果；
保存业务对象索引；
根据统一 flow_action 推进、等待、停止或完成。
```

编排层不负责：

```text
解释业务模块内部状态；
直接访问 Binance；
直接修改业务对象；
直接释放 ActiveLock；
直接提交订单；
绕过业务 service。
```

业务对象之间的真实关系必须依赖业务外键。`OrchestrationBusinessObjectLink` 只提供一轮运行的快捷审计索引，不替代业务外键。

## 7. 数据与信号范围

当前阶段前半段链路负责把行情事实转换成目标仓位决策。

边界：

```text
DataCollection 只保存已收盘行情事实；
DataQuality 决定数据窗口是否可消费；
DataBackfill 只处理缺口回补，不直接触发交易；
MarketSnapshot 固化一次分析周期的市场证据；
FeatureLayer 只计算特征，不生成交易信号；
AtomicSignal 只生成原子判断，不生成订单动作；
DomainSignal 聚合同类原子判断，形成领域级市场事实，不生成订单动作；
MarketRegime 基于领域事实识别市场环境，不选择订单动作；
StrategyRouting 基于市场环境和路由配置选择 StrategyDefinition，不执行策略算法；
StrategySignal 执行 StrategyRouting 已选定的 StrategyDefinition，基于 DomainSignalValue 生成策略级判断，不等于交易决策；
StrategySignalQuality 判断策略信号是否具备下游消费条件；
DecisionSnapshot 使用版本化 DecisionPolicy / DecisionPolicyCalculator 生成目标仓位意图，只表达目标仓位语义。
```

DecisionSnapshot 不得包含：

```text
订单 side；
订单 quantity；
reduce_only；
client_order_id；
交易所 endpoint；
交易所订单类型参数。
```

## 8. 账户与价格事实范围

账户事实由 Binance Account Sync 提供。

规则：

```text
所有 Binance 请求必须通过 Binance Gateway；
Binance Account Sync 只通过受限账户只读和公共市场接口读取事实；
自动四小时编排起始阶段必须生成本轮 trade_preparation 账户边界快照；
交易链路只能使用 trade_preparation BinanceSyncRun；
后台账户展示只能使用 ops_display BinanceSyncRun；
ops_display 不得进入交易链路；
账户快照不等于交易执行。
```

允许通过明确边界模块读取的交易所事实包括：

```text
账户权益；
可用余额；
冻结余额；
手续费率；
交易所实际杠杆；
真实仓位；
保证金余额；
订单状态；
成交状态；
交易规则；
行情价格事实。
```

读取行为必须受以下约束：

```text
配置开关；
trace_id；
超时；
错误码；
失败记录；
AlertEvent；
审计日志；
敏感信息脱敏。
```

价格事实由 PriceSnapshot 提供。

规则：

```text
PriceSnapshot 直接通过 Binance Gateway 获取 mark price；
PriceSnapshot 写入 MySQL 与 Redis；
Redis 只作为短期缓存；
一轮 OrchestrationRun 只能使用一个 PriceSnapshot；
不同批次价格快照不得混用；
最终真实成交价由订单和成交链路记录。
```

## 9. 真实交易运行权限范围

系统不建立独立的运行权限业务模块。真实交易权限由 ProjectFoundation 提供基础配置读写能力，由 OrderPlanStepAdapter 在进入 OrderPlan 前判断一次。

核心模型：

```text
.env = 真实交易部署级硬权限；
MySQL = 后台真实交易运行开关；
effective_real_trading_permission = deployment_real_trading_permission AND runtime_real_trading_permission。
```

规则：

```text
.env 禁止真实交易时，后台不能放行；
.env 允许时，MySQL 运行开关才能决定是否允许下一轮进入 OrderPlan；
后台不得写 .env；
后台不得管理 API key 或 secret；
后台不得热切换 active market domain；
真实交易默认关闭；
权限检查必须早于 OrderPlan 和 ActiveLock；
检查通过后，本轮后续步骤不重新读取 MySQL 运行开关；
后台开关变化只影响下一次进入 OrderPlan 的检查；
BinanceOrderSubmissionGateway 仍独立遵守自己的部署级接口硬配置。
```

任何真实提交路径必须同时满足：

```text
DecisionSnapshot.status = created；
DecisionSnapshot.allows_order_plan = true；
DecisionSnapshot 未过期；
账户事实快照可用且属于 active market domain；
PriceSnapshot 可用且未过期；
OrderPlan 已生成 CandidateOrderIntent；
RiskCheck 已生成 ALLOW 结果；
ApprovedOrderIntent 已生成；
ExecutionPreparation 已通过；
PreparedOrderIntent 已生成；
进入 OrderPlan 前，`.env` 与 MySQL 真实交易权限均已显式允许。
```

## 10. 订单规划与风控范围

OrderPlan 是唯一允许把目标仓位转换成候选订单意图的模块。

规则：

```text
OrderPlan 消费 DecisionSnapshot、BinanceSyncRun 和 PriceSnapshot；
OrderPlan 不访问 Binance；
OrderPlan 不做最终风控审批；
OrderPlan 创建 CandidateOrderIntent；
OrderPlan 拥有 OrderPlanActiveLock；
OrderPlan 只有在 OrderPlanStepAdapter 完成真实交易权限检查后才会被调用并取得 ActiveLock。
```

RiskCheck 只审批既有 CandidateOrderIntent。

规则：

```text
RiskCheck 不消费 DecisionSnapshot；
RiskCheck 不生成新的 CandidateOrderIntent；
RiskCheck 不任意修改订单数量；
RiskCheck 不下单；
RiskCheck 允许时生成 ApprovedOrderIntent；
RiskCheck 拒绝、阻断或失败时不得生成 ApprovedOrderIntent。
```

风控规则必须支持插件化扩展，但当前不做自动缩单。

## 11. 执行与交易事实范围

ExecutionPreparation 负责执行前最终检查。

规则：

```text
ExecutionPreparation 只消费 ApprovedOrderIntent；
ExecutionPreparation 执行 price guard；
报单前必须通过 Binance Gateway 查询实时市场价格；
实时价格与本周期 mark price 偏差大于 1% 时阻断；
小于或等于 1% 时允许继续；
ExecutionPreparation 不真实下单。
```

Execution 是唯一允许提交真实订单的模块。

规则：

```text
Execution 只消费 PreparedOrderIntent；
Execution 不重复读取真实交易运行开关；
Execution 调用 BinanceOrderSubmissionGateway；
订单提交绝不重试；
Gateway、业务层、Celery、编排层均不得重试订单提交；
提交结果 unknown 时不得推断成功或失败；
unknown 必须进入 OrderStatusSync 查询。
```

当前阶段不实现模拟交易运行模式。dry-run 与 real trading 必须隔离：

```text
dry-run 不写正式交易对象，不进入真实下游；
real trading 只能消费真实账户事实、真实价格事实和真实订单链路对象。
```

OrderStatusSync 负责订单状态查询。

FillSync 负责成交同步和成交汇总。

二者都不得生成新订单，不得根据本地推导修改交易所持仓事实。

## 12. ActiveLock 范围

OrderPlanActiveLock 是同一交易身份的唯一订单链路保护锁。

规则：

```text
OrderPlanStepAdapter 的真实交易权限检查未通过时不得调用 OrderPlan，因此不得取得锁；
锁只能由 OrderPlan 所属 ActiveLockService 修改；
编排层不得直接释放锁；
RuntimeGuard 不得直接释放锁；
OpsConsole 不得直接写锁状态；
unknown / not_found / NEW / PARTIALLY_FILLED 不得自动释放锁；
提交前明确未发送、交易所明确拒绝、订单终态且成交同步完整、或授权人工收尾，才允许释放锁。
```

锁用于防止同一市场身份存在并行冲突订单链路。

## 13. 通知与审计范围

Notifications 拥有 AlertEvent、NotificationDeliveryAttempt 和 NotificationSuppression。

规则：

```text
所有正式交易相关关键事件必须写 AlertEvent；
业务模块只写 AlertEvent，不直接发送 Hermes；
Notifications 异步投递 Hermes；
需要外部投递的 AlertEvent 必须形成 NotificationDeliveryAttempt；
不需要外部投递的 AlertEvent 必须形成 NotificationSuppression 或等价抑制记录；
Hermes 只负责通知，不触发交易；
通知失败不得回滚业务事实；
通知成功不得触发业务动作；
AlertEvent 不得包含密钥、签名、完整认证 header 或完整外部响应。
```

人工操作和高风险状态变更必须审计。

## 14. 巡检与后台范围

RuntimeGuard 负责发现自动编排主链路中的漏跑、卡住、长期不确定状态和静默异常。

RuntimeGuard 覆盖范围：

```text
自动编排主链路；
订单链路卡住状态；
ActiveLock 风险状态；
通知投递状态。
```

RuntimeGuard 不负责：

```text
补跑业务；
恢复编排；
修改业务对象；
释放锁；
巡检 AIReview；
巡检 PerformanceMetrics；
巡检后台人工补算；
巡检后台人工复盘；
调用 Binance；
调用 DeepSeek；
直接发送 Hermes。
```

OpsConsole 是运维控制台和复盘工作台。

OpsConsole 可以：

```text
看系统状态；
看账户展示；
看 OrchestrationRun；
看订单；
看 RuntimeGuardIssue；
看 AlertEvent；
看 PerformanceMetrics；
查看市场配置并操作真实交易运行开关；
触发受控人工入口；
导出离线复盘数据。
```

OpsConsole 不得：

```text
直接访问数据库；
直接调用 Binance Gateway；
直接调用 DeepSeekGateway；
直接提交订单；
直接释放锁；
直接写业务表；
绕过后端安全校验。
```

## 15. 绩效与 AI 复盘范围

PerformanceMetrics 是账户绩效复盘模块。

规则：

```text
只读取已落库事实；
只使用自动边界 trade_preparation 账户快照；
不使用 ops_display；
不请求 Binance；
不影响交易主流程；
计算 UTC 4 小时周期浮动收益；
订单 realized_pnl 和手续费只作为辅助字段。
```

AIReview 是离线大模型复盘模块。

规则：

```text
AIReview 读取已落库事实；
AIReview 生成脱敏复盘数据包；
AIReview 通过 DeepSeekGateway 调用 DeepSeek；
AIReview 保存报告、发现和人工建议；
AIReview 不参与实时交易；
AIReview 不自动修改策略；
AIReview 不自动修改真实交易运行配置；
AIReview 不自动下单。
```

DeepSeekGateway 是 DeepSeek API 的受控请求边界，不拥有复盘业务判断。

## 16. 当前阶段不做事项

当前阶段不做：

```text
多交易所；
多品种组合管理；
复杂投资组合管理；
复杂多策略权重分配；
机器学习交易模型；
大模型实时交易决策；
大模型生成订单；
自动参数优化；
自动上线策略；
自动禁用策略；
复杂报表系统；
自动调整杠杆；
自动修改保证金模式；
自动资金划转；
自动交易修复；
后台热切换 active market domain；
.env 在线编辑；
API key 管理；
Hermes 入站交易命令；
通知触发交易；
RiskCheck 任意修改订单数量；
RiskCheck 自行生成新订单；
DecisionSnapshot 直接生成订单动作。
```

任何时候都不允许系统自动调整交易所杠杆。

杠杆相关规则：

```text
交易所杠杆只能来自 .env 或明确配置；
系统可以读取 observed_exchange_leverage 作为交易所事实；
observed_exchange_leverage 不得参与目标仓位放大计算；
风控必须在交易前二次核验配置杠杆与交易所观测杠杆；
系统不得调用交易所接口修改杠杆或保证金模式。
```

## 17. 当前阶段核心对象范围

当前阶段核心对象以 `core_contracts.md` 为准。

本文档只列出范围层面的对象类别：

```text
行情事实对象；
数据质量与回补对象；
市场快照对象；
特征对象；
原子信号对象；
领域信号对象；
市场环境对象；
策略路由对象；
策略信号对象；
策略分析发布版本对象；
目标仓位决策对象；
账户事实对象；
价格事实对象；
订单计划对象；
候选订单意图；
风控结果；
风控批准订单意图；
执行准备对象；
冻结执行请求；
订单提交尝试；
订单状态同步记录；
成交同步结果；
逐笔成交和成交汇总；
编排运行与步骤；
编排业务对象索引；
真实交易运行开关；
运行巡检问题；
周期绩效记录；
复盘请求、复盘数据包、复盘调用尝试、复盘报告、复盘发现和人工建议；
通知事件；
通知投递尝试；
通知抑制记录；
审计记录。
```

字段结构、关系设计、索引设计和存储细节由模块需求、架构文档和开发计划定义。

## 18. 当前阶段交付目标

当前阶段交付目标不是完整量化平台，而是一个最小可验证、可审计、可复盘的自动交易闭环。

应至少达到：

```text
能够稳定采集 Binance USDS-M BTCUSDT 已收盘 K 线数据；
能够校验数据完整性和连续性；
能够在发现缺失 K 线时创建回补请求，并在回补后重新质检；
能够生成 MarketSnapshot；
能够生成 FeatureSet / FeatureValue；
能够生成 AtomicSignalSet / AtomicSignalValue；
能够生成 DomainSignalSet / DomainSignalValue；
能够生成 MarketRegimeSnapshot；
能够生成 StrategyRouteDecision；
能够冻结并使用已批准的 StrategyAnalysisRelease；
能够生成 StrategySignal；
能够生成 StrategySignalQualityResult；
能够生成 DecisionSnapshot；
能够同步 Binance 账户、余额、持仓和交易规则事实；
能够生成 PriceSnapshot；
能够在 `.env` 与 MySQL 真实交易权限同时允许时生成 OrderPlan 和 CandidateOrderIntent；
能够通过 RiskCheck 阻断或放行 CandidateOrderIntent；
能够在风控允许后生成 ApprovedOrderIntent；
能够通过 ExecutionPreparation 完成真实提交前准备；
能够通过 Execution 执行真实提交，并保证 dry-run 不进入真实提交链路；
能够跟踪订单状态；
能够同步成交明细和成交汇总；
能够防止冲突订单链路并安全收尾 ActiveLock；
能够通过 Notifications 记录并投递关键事件；
能够通过 RuntimeGuard 发现卡住和不确定状态；
能够通过 PerformanceMetrics 计算周期浮动收益；
能够通过 OpsConsole 查看系统、账户、编排、订单、异常和收益；
能够通过 AIReview 生成离线复盘报告。
```

## 19. 当前阶段必须能回答的问题

系统必须能够回答：

```text
当时使用了哪些行情数据？
数据质量是否通过？
是否发生回补？
当时市场快照是什么？
当时特征值是什么？
哪些原子信号成立？
领域信号是什么？
市场环境判断是什么？
为什么选择这个策略？
策略信号是什么？
策略质量是否允许下游继续？
目标仓位决策是什么？
账户、余额、持仓和交易规则事实是什么？
价格快照是什么？
进入 OrderPlan 前的真实交易权限检查是否通过？
OrderPlan 为什么生成或没有生成 CandidateOrderIntent？
ActiveLock 是否取得，为什么释放或保持？
RiskCheck 为什么允许、拒绝、阻断或失败？
是否生成 ApprovedOrderIntent？
ExecutionPreparation 是否通过？
订单是否提交？
提交是否 accepted、rejected、unknown 或 blocked_before_submit？
订单状态最终如何？
成交是否同步完整？
周期浮动收益是多少？
哪些 AlertEvent 和 RuntimeGuardIssue 与本轮有关？
如果发生异常，人工应该看哪里？
AIReview 的复盘结论基于哪些输入？
```

## 20. 当前阶段验收方向

当前阶段验收不以收益率为唯一标准。

更重要的验收方向：

```text
数据是否可信；
链路是否完整；
决策是否可追溯；
账户事实是否明确；
价格事实是否明确；
风控是否有效；
执行是否受控；
锁是否不会泄漏；
未知状态是否保守处理；
回测、dry-run 和实盘逻辑是否一致；
每次系统行为是否可复盘；
真实交易是否默认关闭，并且只有 `.env` 与 MySQL 运行开关同时允许时才进入 OrderPlan。
```

基础验收标准：

```text
缺失或异常 K 线不会静默进入策略链路；
特征计算结果可追溯到 MarketSnapshot；
原子信号可追溯到 FeatureSet；
DomainSignal 可追溯到 AtomicSignalSet / AtomicSignalValue；
MarketRegime 可追溯到 DomainSignalSet / DomainSignalValue；
StrategyRouting 可追溯到 MarketRegimeSnapshot、StrategyRoutePolicy、StrategyRouteRule 和 StrategyDefinition；
StrategySignal 可追溯到 StrategyRouteDecision、StrategyDefinition、DomainSignalSet / DomainSignalValue；
StrategySignalQuality 可追溯到 StrategySignal；
DecisionSnapshot 可追溯到 StrategySignalQualityResult、StrategySignal 和 DecisionPolicyDefinition；
Binance Account Sync 可追溯到 Gateway 调用摘要和 active domain；
PriceSnapshot 可追溯到 mark price 请求；
OrderPlan 可追溯到 DecisionSnapshot、账户事实和价格事实；其所属运行可通过编排索引追溯到进入 OrderPlan 前的真实交易权限检查结果；
CandidateOrderIntent 可追溯到 OrderPlan；
RiskCheckResult 可追溯到 CandidateOrderIntent；
ApprovedOrderIntent 可追溯到 RiskCheckResult；
PreparedOrderIntent 可追溯到 ExecutionPreparation；
OrderSubmissionAttempt 可追溯到 PreparedOrderIntent；
OrderStatusSyncRecord 可追溯到 OrderSubmissionAttempt；
TradeFill 可追溯到订单状态和成交同步；
PerformanceMetrics 可追溯到相邻自动边界账户快照；
AlertEvent 可追溯到相关业务对象；
AIReviewReport 可追溯到复盘数据包、prompt 和 DeepSeekGateway 调用；
当前阶段不实现模拟交易运行模式；
OpsConsole 不能绕过后端安全校验。
```

## 21. 风险声明

本项目的核心风险包括：

```text
策略没有真实市场优势；
回测过拟合；
回测存在前视偏差；
回测没有充分考虑手续费、滑点和成交约束；
数据质量不可信；
数据缺失后未重新质检；
回测、dry-run 和 real 链路不一致；
账户事实、价格事实或交易规则不可信；
风控边界不清；
ActiveLock 泄漏或误释放；
订单 unknown 被错误解释；
进入 OrderPlan 前的真实交易权限检查被绕过；
把 dry-run 或回测结果当成 real trading 事实使用；
执行不可审计；
通知被误当成交易指令；
大模型复盘结论被误当成实时交易决策；
复盘无法解释系统行为。
```

因此当前阶段优先级是：

```text
第一，真实策略有效性。
第二，数据、回测、风控、实盘一致性。
第三，策略组合、监控、复盘。
第四，后台、界面、交互体验。
```

如果某项功能不能直接服务策略验证、风控、执行可靠性或复盘可信度，应延后。

## 22. 最终结论

当前阶段的目标是：

```text
建设一个安全、可追溯、可审计、可复盘的中低频趋势跟踪自动交易闭环。
```

一句话：

```text
系统可以自动交易，但必须先证明数据可信、决策可追溯、风控有效、真实交易权限生效、执行受控、异常可发现、结果可复盘。
```
