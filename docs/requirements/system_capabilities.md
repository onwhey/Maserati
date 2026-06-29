# 系统能力说明

## 1. 文档目的

本文档定义当前系统应具备的能力地图、能力边界、能力依赖和当前不包含的能力。

本文档用于回答：

```text
系统由哪些能力组成；
每项能力负责什么；
每项能力不负责什么；
能力之间如何依赖；
哪些能力必须进入当前闭环；
哪些能力只保留边界；
哪些能力明确禁止。
```

本文档不定义：

```text
数据库字段；
Django app 结构；
Celery task 名称；
REST API 路径；
前端页面组件；
具体策略公式；
回测撮合细节；
外部服务 SDK 实现。
```

对象语义以 `core_contracts.md` 为准。模块内部状态、原因码、幂等规则、异常处理和验收标准以对应模块需求为准。

## 2. 能力优先级

需求能力统一使用以下优先级语义：

```text
必须：当前系统成立所需的强制能力。
应当：当前范围内应实现，允许在计划中分步交付。
可以：不影响当前主链路的增强能力。
不在当前范围：尚未形成完整需求合同，不得提前实现。
禁止：违反系统红线，任何阶段不得实现。
```

模块文档不得使用另一套优先级语义覆盖本文档。

## 3. 总体能力地图

当前系统能力分为以下领域：

```text
项目基础与核心合同；
外部访问网关；
行情数据；
数据质量；
数据回补；
市场快照；
特征；
原子信号；
领域信号；
市场环境；
策略路由；
策略信号；
策略信号质量；
策略分析发布版本；
目标仓位决策；
账户事实；
价格事实；
真实交易运行权限；
订单规划；
风控审批；
执行准备；
订单提交；
限价单周期收尾；
订单状态同步；
成交同步；
编排；
运行巡检；
通知与审计；
复盘数据集；
后台运维；
配置、权限与存储治理。
```

能力之间的主依赖为：

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
→ OrderPlan / CandidateOrderIntent
→ RiskCheck / ApprovedOrderIntent
→ ExecutionPreparation / PreparedOrderIntent
→ Execution / OrderSubmissionAttempt
→ 订单提交事实完成，主交易编排结束
或 NO_TARGET_CHANGE / NO_TRADE：正常结束，不进入 PriceSnapshot 或订单链路
```

订单提交后的状态与成交同步属于独立订单生命周期分支，不内嵌在主交易编排尾部：

```text
OrderSubmissionAttempt
→ OrderStatusSync
→ FillSync
→ ActiveLock 安全收尾判断
```

LIMIT 订单到期仍未终态时，存在独立周期收尾分支：

```text
OrderCycleCloseout / OrderCancelAttempt
→ OrderStatusSync
→ FillSync
→ ActiveLock 安全收尾判断
```

横切能力包括：

```text
PipelineOrchestrator；
RuntimeGuard；
Notifications / AlertEvent / NotificationDeliveryAttempt / NotificationSuppression；
ReviewDataset；
OpsConsole；
AuditRecord。
```

横切能力不得改变业务对象的所有权，也不得绕过业务 service。

## 4. 项目基础与核心合同能力

系统必须具备统一的项目范围、对象语义、交易红线、时间规则和审计规则。

必须具备：

```text
统一的项目范围说明；
统一的核心对象合同；
统一的正式交易链路；
统一的模块结果语义；
统一的外部访问边界；
统一的运行模式与真实交易权限语义；
统一的 UTC 时间规则；
统一的 trace_id 与幂等要求；
统一的 MySQL 与 Redis 使用边界；
统一的 AlertEvent 和审计要求。
```

不负责：

```text
替代模块需求；
替代架构设计；
替代开发计划；
替代测试用例；
替代数据库 migration。
```

核心原则：

```text
StrategySignal 不等于 DecisionSnapshot；
DecisionSnapshot 不等于 CandidateOrderIntent；
CandidateOrderIntent 不等于 ApprovedOrderIntent；
ApprovedOrderIntent 不等于 PreparedOrderIntent；
PreparedOrderIntent 不等于 OrderSubmissionAttempt；
OrderSubmissionAttempt 不等于交易所完整订单状态；
TradeFill 不等于 BinancePositionSnapshot；
ReviewDatasetRecord 不等于交易决策、策略评估结论或生产策略变更指令。
```

## 5. 外部访问网关能力

系统必须把外部服务访问收敛到受控网关。

当前必须具备的网关：

```text
BinanceGateway。
```

### 5.1 BinanceGateway

BinanceGateway 是系统访问 Binance REST API 的唯一基础设施边界。

必须具备：

```text
统一签名；
统一超时；
统一限频；
统一错误分类；
统一脱敏日志；
统一技术指标；
受限账户只读接口；
受限公共市场接口；
受限订单提交接口；
受限订单撤销接口；
受限订单查询接口；
受限成交查询接口。
```

边界：

```text
业务模块不得直接创建 Binance HTTP client；
业务模块不得直接生成 Binance 签名；
业务模块不得拼接 Binance endpoint；
系统不得调用交易所修改杠杆接口；
订单提交绝不自动重试；
Gateway 不拥有业务对象状态；
Gateway 不直接写业务 AlertEvent。
```

当前正式系统内不调用 DeepSeek。

如后续重新引入系统内大模型复盘或其他大模型能力，必须先新增独立需求和安全边界；不得让大模型参与实时交易决策。

## 6. 行情数据能力

行情数据能力负责保存可信的已收盘 K 线事实，为后续快照、特征、信号、回测和复盘提供输入。

必须具备：

```text
从可信数据源采集已收盘 K 线；
按 UTC 保存 open_time / close_time；
记录 exchange、market_type、symbol、interval；
保证同一 K 线业务身份幂等；
保留原始价格、成交量和必要元数据；
拒绝未收盘 K 线进入正式分析链路。
```

应当具备：

```text
采集运行记录；
采集失败原因；
采集窗口摘要；
重复数据保护；
与 DataQuality 的清晰交接。
```

不负责：

```text
生成市场快照；
生成特征；
生成信号；
生成交易决策；
回补缺口的业务判断；
真实下单。
```

## 7. 数据质量能力

数据质量能力负责判断某个数据窗口是否允许下游消费。

必须具备：

```text
K 线连续性检查；
时间顺序检查；
重复 K 线检查；
缺失 K 线检查；
异常价格或成交量检查；
输出 DataQualityResult；
在质量不通过时阻止下游正式消费。
```

边界：

```text
DataQuality 可以阻断下游流程；
DataQuality 不人工伪造 K 线；
DataQuality 不直接修补数据；
DataQuality 不生成策略判断；
DataQuality 不下单。
```

## 8. 数据回补能力

数据回补能力负责在发现可回补缺口后，从可信数据源拉取缺失范围并重新进入质检。

必须具备：

```text
创建 BackfillRequest；
执行 BackfillRun；
记录回补范围；
记录回补来源；
幂等写入 K 线；
回补完成后触发或等待重新质检；
回补失败时保留失败事实。
```

边界：

```text
DataBackfill 不直接放行下游；
DataBackfill 不跳过 DataQuality；
DataBackfill 不人工编造数据；
DataBackfill 不触发订单链路。
```

## 9. 市场快照能力

MarketSnapshot 负责固化一次分析周期使用的市场证据。

必须具备：

```text
绑定明确数据窗口；
绑定通过质检的数据结果；
固化分析周期输入；
为 FeatureLayer 提供不可变输入；
保存可追溯的快照状态。
```

边界：

```text
MarketSnapshot 不计算特征；
MarketSnapshot 不生成信号；
MarketSnapshot 不读取账户；
MarketSnapshot 不读取 Binance 订单接口；
MarketSnapshot 不下单。
```

## 10. 特征能力

FeatureLayer 负责基于 MarketSnapshot 计算可复用特征。

必须具备：

```text
生成 FeatureSet；
生成 FeatureValue；
特征结果可追溯到 MarketSnapshot；
特征计算使用已固化输入；
特征版本可追溯；
计算失败保留错误事实。
```

边界：

```text
FeatureLayer 不生成交易信号；
FeatureLayer 不生成目标仓位；
FeatureLayer 不读取账户事实；
FeatureLayer 不生成订单；
FeatureLayer 不下单。
```

## 11. 原子信号能力

AtomicSignal 负责把特征转换为最小市场判断单元。

必须具备：

```text
生成 AtomicSignalSet；
生成 AtomicSignalValue；
每个原子信号可追溯到 FeatureSet；
保留信号名称、方向、强度和证据摘要；
失败或不适用时保留状态。
```

边界：

```text
AtomicSignal 不生成策略最终判断；
AtomicSignal 不生成目标仓位；
AtomicSignal 不生成订单动作；
AtomicSignal 不读取账户；
AtomicSignal 不下单。
```

## 12. 领域信号能力

DomainSignal 负责把同类原子信号聚合成领域级市场事实。

必须具备：

```text
消费 AtomicSignalSet / AtomicSignalValue；
生成 DomainSignalSet；
生成 DomainSignalValue；
记录领域名称、方向、强度、置信度和证据摘要；
保持到 AtomicSignal 的追溯关系；
只运行已批准进入正式链路的领域计算版本。
```

边界：

```text
DomainSignal 不生成策略最终判断；
DomainSignal 不识别完整市场环境；
DomainSignal 不选择策略；
DomainSignal 不生成目标仓位；
DomainSignal 不生成订单动作；
DomainSignal 不读取账户；
DomainSignal 不下单。
```

## 13. 市场环境能力

MarketRegime 负责基于领域信号识别当前市场环境。

必须具备：

```text
消费 DomainSignalSet / DomainSignalValue；
生成 MarketRegimeSnapshot；
记录各类市场环境判断和证据摘要；
即使某类环境分数较低，也应保留明确判断；
保持到 DomainSignal 的追溯关系；
只运行已批准进入正式链路的市场环境计算版本。
```

边界：

```text
MarketRegime 不直接执行策略；
MarketRegime 不生成 StrategySignal；
MarketRegime 不生成目标仓位；
MarketRegime 不生成订单动作；
MarketRegime 不读取账户；
MarketRegime 不下单。
```

## 14. 策略路由能力

StrategyRouting 负责基于市场环境和路由配置选择本轮要执行的策略。

必须具备：

```text
消费 MarketRegimeSnapshot；
读取已批准的策略定义和路由配置；
生成 StrategyRouteDecision；
记录为什么选择该策略；
记录未选择其他策略的摘要原因；
保持到 MarketRegime 和策略路由配置的追溯关系。
```

边界：

```text
StrategyRouting 不执行策略算法；
StrategyRouting 不生成 StrategySignal；
StrategyRouting 不生成目标仓位；
StrategyRouting 不生成订单动作；
StrategyRouting 不读取账户；
StrategyRouting 不下单。
```

## 15. 策略信号能力

StrategySignal 负责执行 StrategyRouting 已选定的策略，形成标准化策略级市场判断。

必须具备：

```text
消费 StrategyRouteDecision；
消费策略允许使用的 DomainSignalSet / DomainSignalValue；
生成 StrategySignal；
记录策略名称和策略版本；
记录方向、置信度、证据摘要和适用状态；
保持到 StrategyRouteDecision、StrategyDefinition 和 DomainSignal 的追溯关系；
只运行已批准进入正式链路的策略版本。
```

边界：

```text
StrategySignal 不是交易决策；
StrategySignal 不生成订单动作；
StrategySignal 不读取账户；
StrategySignal 不读取当前持仓；
StrategySignal 不直接进入 Execution。
```

## 16. 策略信号质量能力

StrategySignalQuality 负责判断策略信号是否具备进入 DecisionSnapshot 的条件。

必须具备：

```text
检查 StrategySignal 结构完整性；
检查证据可追溯性；
检查数值有效性；
检查快照一致性；
检查时效；
输出 StrategySignalQualityResult；
质量不通过时阻断 DecisionSnapshot。
```

边界：

```text
StrategySignalQuality 不生成策略信号；
StrategySignalQuality 不改变策略方向；
StrategySignalQuality 不调整目标仓位；
StrategySignalQuality 不生成订单参数。
```

## 17. 策略分析发布版本能力

StrategyAnalysisRelease 负责冻结一套可以进入正式策略分析链路的版本组合。

必须具备：

```text
记录正式链路允许使用的 Feature、AtomicSignal、DomainSignal、MarketRegime、StrategyRouting、StrategySignal 和 DecisionPolicy 版本组合；
只有已批准的发布版本可以进入正式自动编排；
发布版本一经用于正式运行，不得被原地修改；
保留批准人、批准时间、版本摘要和适用范围；
支持后台查看当前正式版本组合。
```

边界：

```text
StrategyAnalysisRelease 不执行任何算法；
StrategyAnalysisRelease 不自动批准新算法；
StrategyAnalysisRelease 不自动上线策略；
StrategyAnalysisRelease 不生成交易信号；
StrategyAnalysisRelease 不生成订单动作。
```

## 18. 目标仓位决策能力

DecisionSnapshot 负责表达一个分析周期的目标仓位语义。

必须具备：

```text
消费 StrategySignalQualityResult；
消费已通过质量检查的 StrategySignal；
生成 DecisionSnapshot；
表达 target_intent；
表达 target_position_ratio；
记录策略版本、证据和原因；
不包含交易所订单参数。
```

边界：

```text
DecisionSnapshot 不读取账户、余额或持仓；
DecisionSnapshot 不读取 BinanceSyncRun；
DecisionSnapshot 不生成 CandidateOrderIntent；
DecisionSnapshot 不包含 side、quantity、reduce_only 或 client_order_id；
DecisionSnapshot 不直接触发下单。
```

## 19. 账户事实能力

Binance Account Sync 负责读取并固化 Binance 账户、余额、持仓和交易规则事实。

必须具备：

```text
通过 BinanceGateway 读取账户事实；
自动四小时编排起始阶段生成 trade_preparation 账户边界事实；
创建 BinanceSyncRun；
创建 BinanceAccountSnapshot；
创建 BinanceBalanceSnapshot；
创建 BinancePositionSnapshot；
创建 BinanceSymbolRuleSnapshot；
区分 trade_preparation 与 ops_display；
记录 active market domain；
记录请求摘要和同步状态。
```

边界：

```text
交易链路只能使用 trade_preparation；
OrderPlan、RiskCheck 和 ExecutionPreparation 只能消费本轮编排起始账户边界批次；
后台展示只能使用 ops_display；
ops_display 不得进入交易链路；
Binance Account Sync 不提交订单；
Binance Account Sync 不修改杠杆；
Binance Account Sync 不推导策略判断。
```

## 20. 价格事实能力

PriceSnapshot 负责在交易链路中固化本轮使用的 mark price 事实。

必须具备：

```text
通过 BinanceGateway 主动请求 mark price；
写入 MySQL；
写入 Redis 短期缓存；
Redis TTL 默认为十分钟；
一轮 OrchestrationRun 只能使用一个 PriceSnapshot；
不同批次 PriceSnapshot 不得混用；
PriceSnapshot 可追溯到请求上下文。
```

边界：

```text
PriceSnapshot 不从账户持仓快照读取价格；
PriceSnapshot 不代表最终成交价；
PriceSnapshot 不提交订单；
PriceSnapshot 不直接判断是否交易；
PriceSnapshot 不替代 ExecutionPreparation 的报单前价格检查。
```

## 21. 真实交易运行权限能力

系统不建立独立的运行权限业务模块。ProjectFoundation 提供最小配置能力，OrderPlanStepAdapter 负责在进入 OrderPlan 前判断一次最终真实交易权限。

必须具备：

```text
.env 真实交易部署级硬权限；
MySQL 后台真实交易运行开关；
effective_real_trading_permission = deployment_real_trading_permission AND runtime_real_trading_permission；
真实交易默认关闭；
active market domain 只由部署配置决定；
后台不能突破 `.env` 真实交易硬权限；
权限检查早于 OrderPlan 与 ActiveLock；
检查通过后本轮不重新读取 MySQL 运行开关；
BinanceOrderSubmissionGateway 独立遵守自己的部署级接口硬配置。
```

必须支持：

```text
展示 active market domain；
读取和变更 MySQL 真实交易运行开关；
进入 OrderPlan 前的一次性权限判断；
运行开关变更权限、二次确认、审计和 AlertEvent。
```

边界：

```text
后台不管理 API key；
后台不写 .env；
后台不热切 active market domain；
MySQL 运行开关不控制账户展示刷新、ActiveLock 或 ReviewDataset；
Execution、OrderStatusSync 和 FillSync 不重新读取真实交易运行开关。
```

## 22. 订单规划能力

OrderPlan 是唯一允许把目标仓位转换为 CandidateOrderIntent 的模块。

必须具备：

```text
消费 DecisionSnapshot；
消费 trade_preparation BinanceSyncRun；
消费 PriceSnapshot；
计算当前仓位与目标仓位差异；
生成 OrderPlan；
生成 MARKET 或 LIMIT CandidateOrderIntent；
必要时生成 fallback_reduce_only 候选；
创建并维护 OrderPlanActiveLock；
写入 OrderPlan 相关 AlertEvent。
```

边界：

```text
OrderPlan 不访问 Binance；
OrderPlan 不做最终风控审批；
OrderPlan 不生成 ApprovedOrderIntent；
OrderPlan 不真实下单；
OrderPlan 不读取 ops_display 账户快照；
OrderPlanStepAdapter 的真实交易权限检查未通过时不得调用 OrderPlan，因此不得取得 ActiveLock。
```

## 23. 风控审批能力

RiskCheck 负责审批既有 CandidateOrderIntent。

必须具备：

```text
校验 CandidateOrderIntent；
校验 OrderPlan；
校验 ActiveLock；
校验账户事实；
校验 PriceSnapshot；
校验 symbol rule；
运行插件化风控规则；
生成 RiskCheckResult；
ALLOW 时生成 ApprovedOrderIntent；
DENY / BLOCKED / FAILED 时不得生成 ApprovedOrderIntent；
写入 RiskCheck 相关 AlertEvent。
```

边界：

```text
RiskCheck 不消费 DecisionSnapshot；
RiskCheck 不生成新的 CandidateOrderIntent；
RiskCheck 不任意修改订单数量；
RiskCheck 不拆单；
RiskCheck 不提交订单；
RiskCheck 不修改杠杆；
RiskCheck 只能选择 OrderPlan 已经生成的 primary 或 fallback_reduce_only。
```

当前风控规则必须支持插件化扩展。当前不做自动缩单。

## 24. 执行准备能力

ExecutionPreparation 负责执行前最终检查，并生成 PreparedOrderIntent。

必须具备：

```text
消费 ApprovedOrderIntent；
校验风控结果仍有效；
校验账户事实仍可用；
校验 PriceSnapshot 仍可用；
校验 ActiveLock；
报单前通过 BinanceGateway 查询实时市场价格；
实时价格与本周期 mark price 偏差大于 1% 时阻断；
实时价格与本周期 mark price 偏差小于或等于 1% 时允许继续；
冻结 PreparedOrderIntent；
写入 ExecutionPreparation 相关 AlertEvent。
```

边界：

```text
ExecutionPreparation 不提交订单；
ExecutionPreparation 不重新设计订单；
ExecutionPreparation 不调用成交查询；
ExecutionPreparation 不释放锁；
ExecutionPreparation 不绕过 BinanceGateway。
```

## 25. 订单提交能力

Execution 是唯一允许提交真实订单的模块。

必须具备：

```text
消费 PreparedOrderIntent；
提交前检查 ActiveLock；
通过 BinanceGateway 提交 MARKET 或 LIMIT 订单；
记录 OrderSubmissionAttempt；
区分 accepted、rejected、unknown、failed_before_submit、blocked_before_submit；
写入 Execution 相关 AlertEvent。
```

订单提交规则：

```text
订单提交绝不重试；
Gateway 不重试；
业务层不重试；
Celery 不重试；
编排层不重试；
unknown 不得推断成功或失败；
unknown 必须通过独立订单生命周期同步管线进入 OrderStatusSync 查询。
```

边界：

```text
Execution 不生成订单计划；
Execution 不做风控审批；
Execution 不修改 PreparedOrderIntent；
Execution 不根据本地推测生成 TradeFill；
Execution 不自动释放 unknown 订单的 ActiveLock。
```

Execution 产生 `OrderSubmissionAttempt` 后，主交易编排结束；订单状态与成交事实由独立订单生命周期同步管线继续处理。

## 26. 限价单周期收尾能力

OrderCycleCloseout 负责在本周期结束前处理仍未终态的 LIMIT 订单。

必须具备：

```text
只处理已提交的 LIMIT 订单；
按冻结的 limit_valid_until_utc 判断是否进入收尾；
通过 BinanceOrderCancelGateway 撤销仍未终态的限价单；
记录 OrderCancelAttempt；
撤单后交给 OrderStatusSync 查询订单终态；
明确终态后交给 FillSync 查询成交事实；
写入限价单周期收尾相关 AlertEvent。
```

边界：

```text
OrderCycleCloseout 不提交新订单；
OrderCycleCloseout 不追单；
OrderCycleCloseout 不改单；
OrderCycleCloseout 不生成 TradeFill；
OrderCycleCloseout 不释放 ActiveLock；
OrderCycleCloseout 不根据未成交结果评价策略。
```

## 27. 订单状态同步能力

OrderStatusSync 负责在订单提交后查询交易所订单状态。

必须具备：

```text
消费 OrderSubmissionAttempt；
对 accepted 和 unknown 提交进行状态查询；
使用冻结的 client_order_id；
每两秒查询一次，最多查询三十秒；
查到明确终态立即停止；
记录 OrderStatusSyncRecord；
保留 not_found、unknown 和查询失败事实；
写入订单状态相关 AlertEvent。
```

明确终态至少包括：

```text
FILLED；
CANCELED；
EXPIRED；
REJECTED。
```

边界：

```text
OrderStatusSync 不重新提交订单；
OrderStatusSync 不生成 TradeFill；
OrderStatusSync 不根据账户余额倒推成交；
OrderStatusSync 不在 unknown、not_found、NEW 或 PARTIALLY_FILLED 时自动释放锁。
```

## 28. 成交同步能力

FillSync 负责查询、保存和汇总订单成交事实。

必须具备：

```text
消费明确可同步的 OrderStatusSyncRecord；
通过 BinanceGateway 查询成交；
幂等写入 TradeFill；
生成 OrderFillSummary；
区分 synced、synced_empty、incomplete、unknown、failed_before_query、blocked_before_query 和 recovery_skipped_out_of_window；
在订单终态且成交同步完整时推动锁安全收尾；
写入成交相关 AlertEvent。
```

边界：

```text
FillSync 不提交订单；
FillSync 不生成订单状态；
FillSync 不修改账户快照；
FillSync 不根据成交汇总直接生成 BinancePositionSnapshot；
FillSync 不在成交不确定时释放锁。
```

## 29. 编排能力

PipelineOrchestrator 负责按照步骤定义推进一轮业务流程。

必须具备：

```text
创建 OrchestrationRun；
冻结步骤定义；
调用 OrchestrationBusinessConnector；
保存 OrchestrationStepRun；
保存 OrchestrationBusinessObjectLink；
根据统一 flow_action 推进、等待、停止或完成；
记录步骤耗时、状态和错误摘要。
```

OrchestrationBusinessConnector 必须具备：

```text
定义可编排业务模块；
调用业务 service；
理解每个业务模块原始返回；
转换为统一 normalized_status；
转换为统一 flow_action；
返回业务对象索引。
```

边界：

```text
PipelineOrchestrator 不解释业务模块内部状态；
PipelineOrchestrator 不直接调用 Binance；
PipelineOrchestrator 不直接调用 DeepSeek；
PipelineOrchestrator 不直接修改业务对象；
PipelineOrchestrator 不直接释放 ActiveLock；
PipelineOrchestrator 不直接提交订单；
主交易业务对象不得把 OrchestrationRun 当作正式业务外键或下游输入。
```

业务对象之间的正式追溯必须依赖真实业务外键。
`OrchestrationBusinessObjectLink` 只提供一轮运行的快捷审计索引，不替代业务外键。
复盘、后台、巡检和审计类对象可以保存 OrchestrationRun 引用，用于展示、复盘或人工排查，但不得作为交易模块的正式输入。

## 30. 运行巡检能力

RuntimeGuard 负责发现自动编排主链路中的漏跑、卡住、长期不确定状态和静默异常。

必须具备：

```text
巡检 OrchestrationRun；
巡检 OrchestrationStepRun；
巡检 ActiveLock；
巡检 OrderSubmissionAttempt；
巡检 OrderStatusSyncRecord；
巡检 FillSyncResult；
巡检 NotificationDeliveryAttempt；
巡检 NotificationSuppression；
创建或更新 RuntimeGuardIssue；
写入 RuntimeGuard 相关 AlertEvent。
```

覆盖范围：

```text
自动编排主链路；
订单链路卡住状态；
ActiveLock 风险状态；
通知投递状态。
```

边界：

```text
RuntimeGuard 不补跑业务；
RuntimeGuard 不恢复编排；
RuntimeGuard 不修改业务对象；
RuntimeGuard 不释放锁；
RuntimeGuard 不巡检 ReviewDataset；
RuntimeGuard 不巡检后台人工补算；
RuntimeGuard 不巡检后台人工复盘；
RuntimeGuard 不调用 Binance；
RuntimeGuard 不调用 DeepSeek；
RuntimeGuard 不直接发送 Hermes；
RuntimeGuard 不自动恢复交易。
```

## 31. 通知与审计能力

Notifications 负责 AlertEvent、通知投递尝试和通知抑制记录。

必须具备：

```text
创建 AlertEvent；
创建 NotificationDeliveryAttempt；
创建 NotificationSuppression；
记录事件类型、严重级别、业务对象、状态和摘要；
异步投递 Hermes；
记录投递状态；
通知失败可重试投递；
通知内容脱敏；
通知与业务事实解耦。
```

业务规则：

```text
所有正式交易相关关键事件必须写 AlertEvent；
业务模块写 AlertEvent，不直接发送 Hermes；
需要外部投递的 AlertEvent 必须形成 NotificationDeliveryAttempt；
不需要外部投递的 AlertEvent 必须形成 NotificationSuppression 或等价抑制记录；
Hermes 只负责通知，不触发交易；
通知失败不得回滚业务事实；
通知成功不得触发业务动作。
```

审计能力必须覆盖：

```text
真实交易运行开关变更；
人工锁收尾；
ReviewDataset 导出；
高风险状态变更。
```

## 32. 复盘数据集能力

ReviewDataset 负责把已经落库的系统事实整理成可下载、可校验、可离线分析的复盘数据集。

必须具备：

```text
读取已落库业务事实；
按 UTC 4 小时周期组织数据；
关联 subject_orchestration_run；
关联开始边界和结束边界 OrchestrationRun；
整理行情、特征、原子、领域、市场环境、策略、目标仓位、账户、价格、订单、成交、告警、巡检和审计事实；
记录 ReviewDatasetRecord；
创建 ReviewDatasetExport；
生成 manifest、内容 hash、schema 版本和导出审计；
支持 JSON / JSONL / CSV 等白名单格式导出。
```

边界：

```text
ReviewDataset 不请求 Binance；
ReviewDataset 不调用 DeepSeek；
ReviewDataset 不生成复盘结论；
ReviewDataset 不判断策略是否正确；
ReviewDataset 不影响交易主流程；
ReviewDataset 不生成交易信号；
ReviewDataset 不调整策略；
ReviewDataset 不自动暂停或恢复交易；
ReviewDataset 的导出结果只能用于人工、本地脚本或 Codex skill 离线复盘。
```

## 33. 后台运维能力

OpsConsole 是运维控制台和复盘工作台。

当前必须具备：

```text
Dashboard；
OrchestrationRun 查看；
订单链路查看；
账户展示刷新；
ReviewDataset 导出；
RuntimeGuardIssue 查看；
AlertEvent 查看；
真实交易运行开关操作；
受控人工入口；
审计日志查看。
```

边界：

```text
OpsConsole 不直接访问数据库；
OpsConsole 不直接调用 BinanceGateway；
OpsConsole 不直接提交订单；
OpsConsole 不直接释放 ActiveLock；
OpsConsole 不直接写业务表；
OpsConsole 不管理 API key；
OpsConsole 不写 .env；
OpsConsole 不热切 active market domain。
```

后台后续可以承载更多运维功能，但当前只实现已形成需求合同的功能。

## 34. Codex skill 离线复盘边界

当前系统不在 Django 内部实现大模型复盘。

正式路径是：

```text
ReviewDataset API / 导出文件
→ 本地 Codex skill 读取数据
→ 本地生成 Markdown / JSON 复盘报告
```

边界：

```text
Codex skill 不写生产 MySQL；
Codex skill 不参与实时交易；
Codex skill 不生成交易指令；
Codex skill 不自动修改策略；
Codex skill 不自动修改真实交易运行配置；
Codex skill 不自动提交订单；
Codex skill 不自动释放锁；
Codex skill 的复盘结果默认只保存为本地文件。
```

## 35. 配置与权限能力

系统必须具备清晰的配置、密钥、权限和审计边界。

必须具备：

```text
所有环境配置进入 .env.example；
真实密钥不得提交；
真实交易权限配置不得硬编码；
API key 不得经后台页面管理；
高风险操作必须鉴权；
高风险操作必须二次确认；
高风险操作必须写审计记录；
日志和通知必须脱敏。
```

权限边界：

```text
.env 决定系统最高权限；
运行时开关只能进一步收紧；
后台不能放大硬配置权限；
人工入口不能绕过后端 service；
Celery task 不能绕过后端安全校验；
management command 不能绕过后端安全校验。
```

## 36. 数据与存储能力

系统必须以 MySQL 作为核心业务主存储，以 Redis 作为短期能力支撑。

MySQL 必须保存：

```text
行情事实；
数据质量结果；
市场快照；
特征；
原子信号；
领域信号；
市场环境；
策略路由；
策略信号；
策略分析发布版本；
目标仓位决策；
账户事实；
价格事实；
订单计划；
候选订单意图；
风控结果；
风控批准订单意图；
执行准备结果；
订单提交尝试；
订单状态同步记录；
成交事实；
编排运行；
运行巡检问题；
复盘数据集记录；
复盘数据导出记录；
AlertEvent；
NotificationDeliveryAttempt；
NotificationSuppression；
审计记录。
```

Redis 只能用于：

```text
缓存；
分布式锁；
Celery broker；
短期幂等控制；
短期任务状态；
限流计数；
短期特征序列缓存；
PriceSnapshot 短期缓存；
Celery result backend。
```

禁止：

```text
把 Redis 作为核心业务数据唯一存储；
在单个字段中保存不可控长文本；
在单个字段中保存完整历史窗口；
用大 JSON 逃避表结构设计；
交易、风控、订单、成交、仓位、复盘数据不可追溯。
```

## 37. 调度与幂等能力

系统必须支持自动运行和人工入口的幂等保护。

必须具备：

```text
Celery Beat 或等价调度入口；
明确 trigger_source；
明确 trace_id；
明确业务幂等键；
重复执行不产生重复业务事实；
外部请求结果不确定时保守处理；
订单提交无重试；
正式交易链路具备 ActiveLock 保护。
```

边界：

```text
Celery task 只作为入口；
management command 只作为入口；
复杂业务逻辑必须在 service 或 domain 层；
调度器不得绕过进入 OrderPlan 前的真实交易权限检查；
调度器不得直接提交订单。
```

## 38. 当前不包含的能力

当前不包含：

```text
多交易所；
多 active market domain 同时交易；
后台热切 active market domain；
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
.env 在线编辑；
API key 后台管理；
Hermes 入站交易命令；
通知触发交易；
RiskCheck 任意修改订单数量；
RiskCheck 自行生成订单；
DecisionSnapshot 直接生成订单动作。
```

这些能力不得因为代码实现便利而提前进入主链路。

## 39. 明确禁止能力

任何阶段都禁止：

```text
策略模块直接下单；
原子信号直接下单；
特征层生成交易信号；
DecisionSnapshot 生成订单动作；
DecisionSnapshot 直接读取账户或持仓；
绕过 OrderPlan；
绕过 RiskCheck；
绕过 ApprovedOrderIntent；
绕过 ExecutionPreparation；
绕过 Execution；
大模型参与实时交易决策；
Hermes 触发交易；
系统自动调整杠杆；
当前阶段提前建设模拟交易运行模式；
dry-run 或回测结果污染 real trading；
真实交易在未显式允许时执行；
订单提交自动重试；
unknown 状态被自动解释为成功或失败；
仅凭本地推导释放 ActiveLock。
```

## 40. 能力验收方向

系统能力验收不以收益率为唯一标准。

更重要的验收方向：

```text
数据是否可信；
链路是否完整；
决策是否可追溯；
账户事实是否明确；
价格事实是否明确；
真实交易运行权限是否有效；
风控是否有效；
执行是否受控；
订单提交是否无重试；
锁是否不会泄漏；
未知状态是否保守处理；
通知是否可追溯；
巡检是否能发现异常；
后台是否不能绕过后端规则；
复盘是否能解释系统行为；
真实交易是否默认关闭。
```

基础验收必须覆盖：

```text
缺失或异常 K 线不会进入正式策略链路；
MarketSnapshot 可追溯到通过质检的数据窗口；
FeatureSet 可追溯到 MarketSnapshot；
AtomicSignal 可追溯到 FeatureSet；
DomainSignal 可追溯到 AtomicSignal；
MarketRegime 可追溯到 DomainSignal；
StrategyRouting 可追溯到 MarketRegime 和策略路由配置；
StrategySignal 可追溯到 StrategyRouteDecision、StrategyDefinition 和 DomainSignal；
StrategySignalQualityResult 可追溯到 StrategySignal；
DecisionSnapshot 可追溯到 StrategySignalQualityResult、StrategySignal 和 DecisionPolicy；
Binance Account Sync 可追溯到 BinanceGateway 调用摘要；
PriceSnapshot 可追溯到 mark price 请求；
OrderPlan 可追溯到 DecisionSnapshot、账户事实和价格事实；其所属运行可通过编排索引追溯到进入 OrderPlan 前的真实交易权限检查结果；
CandidateOrderIntent 可追溯到 OrderPlan；
RiskCheckResult 可追溯到 CandidateOrderIntent；
ApprovedOrderIntent 可追溯到 RiskCheckResult；
PreparedOrderIntent 可追溯到 ExecutionPreparation；
OrderSubmissionAttempt 可追溯到 PreparedOrderIntent；
OrderStatusSyncRecord 可追溯到 OrderSubmissionAttempt；
TradeFill 可追溯到订单状态和成交同步；
OrchestrationRun 可聚合本轮业务对象索引；
RuntimeGuardIssue 可追溯到被巡检对象；
ReviewDatasetRecord 可追溯到 subject_orchestration_run、相邻自动边界账户快照和相关业务对象；
ReviewDatasetExport 可追溯到导出范围、数据集记录、manifest 和内容 hash；
AlertEvent 可追溯到相关业务对象；
NotificationDeliveryAttempt 和 NotificationSuppression 可追溯到 AlertEvent。
```

## 41. 最终结论

当前系统能力目标是：

```text
建立一个从可信行情事实到目标仓位决策、账户与价格事实、订单规划、风控审批、执行准备、受控提交、订单追踪、成交同步、巡检、通知和复盘数据集导出的自动交易闭环。
```

一句话：

```text
系统可以自动交易，但每一步都必须有事实来源、业务边界、安全准入、审计记录和复盘依据。
```
