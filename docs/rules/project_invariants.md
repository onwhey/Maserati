# 项目不变量

## 1. 文档目的

本文档定义本项目在需求、架构、计划、实现、测试、部署和运行阶段都不得违反的最高系统边界。

本文档只保存长期稳定、违反后会破坏系统正确性、交易安全性或审计可信度的规则。

本文档不定义：

```text
具体策略公式；
具体数据库表和字段；
具体 Django app 名称；
具体 Celery task 名称；
具体 API 路径；
具体页面结构；
普通模块内部状态和原因码；
可以在不破坏系统边界的情况下调整的实现细节。
```

详细业务语义由 requirements 定义，工程组织由 architecture 定义，开发顺序由 plans 定义，实际代码说明由 implementation 定义。

## 2. 文档优先级不变量

仓库内开发文档优先级为：

```text
project_invariants.md
> decisions
> requirements
> architecture
> plans
> implementation
> code
```

规则：

```text
低优先级文档不得改变高优先级文档的语义；
代码不得反向成为修改需求的依据；
发现冲突时必须停止实现并向用户说明；
不得自行选择对实现更方便的低优先级口径；
不得通过兼容代码同时保留两套相互冲突的正式合同。
```

修改本文档必须作为明确、独立的系统边界变更处理，不得在普通功能开发中顺手修改。

## 3. 项目定位不变量

本项目是中低频趋势跟踪自动交易系统。

系统目标是形成以下闭环：

```text
可信行情事实
→ 策略分析
→ 目标仓位决策
→ 账户与价格事实
→ 订单计划
→ 风控审批
→ 执行准备
→ 唯一订单提交
→ 订单状态与成交同步
→ 巡检、通知、审计和离线复盘
```

本项目允许自动交易，但不属于：

```text
人工喊单系统；
大模型实时交易系统；
大模型喊单系统；
绕过结构化决策和风控的交易脚本；
仅凭前端操作直接下单的后台系统。
```

如果项目文档没有明确允许某个真实交易行为，默认禁止该行为。

## 4. 技术底座不变量

当前技术底座：

```text
Python 3.12.x
Django 5.2.x LTS
MySQL
Redis
Celery
Celery Beat
Python logging / Django logging
pytest / pytest-django 或 Django test framework
```

版本约束：

```toml
requires-python = ">=3.12,<3.13"
```

```text
Django>=5.2,<5.3
celery>=5.6,<5.7
```

规则：

```text
不得随意升级或降级核心版本；
核心版本变化必须先形成架构决策并完成兼容性验证；
pyproject.toml 使用兼容范围；
锁文件固定实际安装版本；
不得自研 ORM、migration、配置系统、日志系统、任务队列、调度系统、测试框架或数据库连接池。
```

## 5. 数据采集域与交易域不变量

数据采集域固定为：

```text
exchange = Binance
market_type = USDS-M Futures
symbol = BTCUSDT
timeframe = 4h / 1d
数据范围 = 已收盘 Kline
```

数据采集域不读取、不依赖 active trading domain，也不因交易账户或后台配置变化而改变。

交易相关模块必须保持 USDS-M 与 COIN-M 的明确隔离：

```text
Binance Account Sync；
PriceSnapshot；
OrderPlan；
RiskCheck；
ExecutionPreparation；
Execution；
OrderStatusSync；
FillSync。
```

同一运行环境同时只能存在一个 active market domain。

active market domain 属于部署级硬配置，后台不得热切换。切换必须经过部署配置变更、服务重启和完整验证。

禁止：

```text
用 symbol 猜测 market_type；
USDS-M 余额不足时读取 COIN-M 余额兜底；
COIN-M 事实缺失时读取 USDS-M 事实兜底；
跨 market_type 使用持仓、余额、交易规则、价格、订单或成交事实；
把数据采集域配置当作交易账户配置。
```

## 6. 正式主链路不变量

正式自动主链路为：

```text
Binance Account Sync（自动四小时账户边界，编排起始步骤）
→ DataCollection
→ DataQuality
→ 必要时 DataBackfill
→ DataQuality 重新验证
→ MarketSnapshot
→ FeatureLayer
→ AtomicSignal
→ DomainSignal
→ MarketRegime
→ StrategyRouting
→ StrategySignal
→ StrategySignalQuality
→ DecisionSnapshot
→ NO_TARGET_CHANGE / NO_TRADE：正常结束，不进入价格或订单链路
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
→ 订单提交事实完成，主交易编排结束
```

订单提交后的状态与成交同步属于独立订单生命周期分支，不内嵌在正式自动主链路尾部：

```text
OrderSubmissionAttempt
→ OrderStatusSync
→ FillSync
→ ActiveLock 安全收尾判断
```

规则：

```text
不得跳过 DataQuality；
不得跳过 MarketSnapshot；
不得跳过 DomainSignal、MarketRegime 或 StrategyRouting；
不得跳过 StrategySignalQuality；
不得跳过 DecisionSnapshot；
不得绕过 OrderPlan；
不得绕过 CandidateOrderIntent；
不得绕过 RiskCheck；
不得绕过 ApprovedOrderIntent；
不得绕过 ExecutionPreparation；
不得绕过 PreparedOrderIntent；
不得绕过 Execution；
不得用后台、命令、任务或恢复入口建立第二条真实交易捷径。
```

## 7. 数据可信度不变量

正式行情事实必须来自 Binance 可信接口，并通过受控 Gateway、业务校验和幂等写入进入 MySQL。

禁止：

```text
人工伪造 Kline；
直接手工改写正式 Kline；
把未收盘 Kline 写入正式行情事实；
把冲突、缺失或无法确认的数据静默送入策略链路；
使用大模型生成、补全或修改正式行情数据；
把 dry-run、后台研究或内存结果写成正式行情事实。
```

数据缺口必须通过：

```text
DataQuality 发现问题；
DataBackfill 通过 BinanceGateway 回补；
回补结果重新写入正式 Kline；
新的 DataQualityResult 重新验证；
只有 PASS 的明确窗口才能生成 MarketSnapshot。
```

DataCollectionRun 和 BackfillRun 都不能替代 DataQualityResult 成为 MarketSnapshot 的放行依据。

## 8. 正式策略分析不变量

正式策略分析只能使用一份已批准、已启用并在 OrchestrationRun 创建时冻结的 StrategyAnalysisRelease。

同一 OrchestrationRun 从 FeatureLayer 到 DecisionSnapshot 必须使用同一版本包身份和 hash。

禁止：

```text
运行时从数据库所有 active Definition 动态拼装正式算法集合；
运行途中切换、回滚或重新解析版本包；
某一步失败后改用另一个版本包继续；
混用不同版本包产生的 Feature、AtomicSignal、DomainSignal、MarketRegime、StrategySignal 或 DecisionSnapshot；
把后台研究、回测、dry-run 或未批准算法结果写入正式主链路对象；
用复盘结果实时改变算法、路由、权重或目标仓位。
```

如果没有唯一可用 StrategyAnalysisRelease：

```text
数据采集、质量检查、回补和 MarketSnapshot 可以继续；
必须在 FeatureLayer 前停止正式策略分析；
不得临时选择其他 Definition 兜底。
```

calculator 必须保持纯计算边界：

```text
只接收 service 已校验和冻结的纯数据；
不得接收 Django model、QuerySet、Gateway、Celery 或 Redis 连接；
不得读写数据库；
不得访问外部服务；
不得创建业务对象；
不得输出真实交易指令。
```

## 9. 质量放行与结果语义不变量

正式下游只能消费其直接上游明确允许消费的已落库对象。

以下结果不得进入正式下游：

```text
blocked；
denied；
failed；
unknown；
dry-run 内存结果；
后台研究结果；
其他 StrategyAnalysisRelease 的结果；
过期、撤销、hash 不一致或市场身份不一致的对象。
```

全局结果语义不得混用：

```text
succeeded = 业务动作成功完成；
no_action = 业务正常完成但不产生交易动作；
skipped = 明确不适用；
blocked = 安全条件不满足；
denied = 风控明确拒绝；
unknown = 无法可靠判断结果；
failed = 系统异常或合同损坏。
```

规则：

```text
blocked、denied、no_action 和 skipped 不得伪装成系统失败；
unknown 不得自动映射为成功或失败；
failed 不得通过创建伪造下游对象掩盖；
任何放行判断都必须可以追溯到明确输入、规则版本和结果证据。
```

## 10. 核心业务对象边界不变量

以下对象必须保持独立语义：

```text
FeatureSet 不等于 AtomicSignalSet；
AtomicSignalSet 不等于 DomainSignalSet；
DomainSignalSet 不等于 MarketRegimeSnapshot；
MarketRegimeSnapshot 不等于 StrategyRouteDecision；
StrategyRouteDecision 不等于 StrategySignal；
StrategySignal 不等于 DecisionSnapshot；
DecisionSnapshot 不等于 CandidateOrderIntent；
OrderPlan 不等于 RiskCheckResult；
CandidateOrderIntent 不等于 ApprovedOrderIntent；
ApprovedOrderIntent 不等于 PreparedOrderIntent；
PreparedOrderIntent 不等于 OrderSubmissionAttempt；
OrderSubmissionAttempt 不等于交易所完整订单状态；
OrderStatusSyncRecord 不等于 TradeFill；
TradeFill 不等于 BinancePositionSnapshot；
BinanceSyncRun 不等于交易执行；
PriceSnapshot 不等于策略行情快照，也不等于实际成交价；
RuntimeGuardIssue 不等于原业务对象状态；
ReviewDatasetRecord 不等于交易决策、策略评估结论或策略变更指令；
ReviewDatasetExport 不等于复盘结论或大模型报告；
AlertEvent 不等于 NotificationDeliveryAttempt；
NotificationSuppression 不等于投递失败。
```

不得把策略判断、目标仓位、候选订单、风控审批、执行参数、提交尝试、订单状态、真实成交、账户持仓和复盘结论混成一个对象。

## 11. DecisionSnapshot 不变量

DecisionSnapshot 只表达目标仓位意图。

允许表达：

```text
TARGET_POSITION；
NO_TARGET_CHANGE；
NO_TRADE；
target_position_ratio；
目标置信度；
原因和结构化证据；
算法与版本信息。
```

DecisionSnapshot 不得：

```text
读取账户、余额、持仓或 BinanceSyncRun；
读取 PriceSnapshot；
根据 MarketRegime 或策略类型进行第二次市场分析；
输出订单 side、quantity、reduce_only 或 client_order_id；
把 ENTER_LONG、ENTER_SHORT、EXIT 或 HOLD 作为订单动作；
直接进入 RiskCheck；
直接进入 Execution。
```

`NO_TARGET_CHANGE / NO_TRADE` 不进入 PriceSnapshot 或订单链路。本轮 ReviewDataset 所需的账户边界事实必须已经由自动四小时编排起始阶段的 `trade_preparation` Binance Account Sync 形成。

该账户边界同步必须在自动四小时编排起始阶段完成。DecisionSnapshot 不直接调用 Binance Account Sync，也不读取同步结果；它只决定是否继续进入 PriceSnapshot 与订单链路。

## 12. 账户与价格事实不变量

### 12.1 Binance Account Sync

Binance Account Sync 只提供账户事实，不生成策略判断或交易动作。

自动四小时编排一开始必须执行一次 `trade_preparation` Binance Account Sync，形成本轮账户边界事实。交易链路只允许消费 Connector 显式传入的该批次 `BinanceSyncRun`。

规则：

```text
OrderPlan 与 RiskCheck 使用同一明确 BinanceSyncRun；
ExecutionPreparation 必须追溯原订单链使用的明确批次；
不得按数据库最新成功批次自动选择交易输入；
不得使用 ops_display 批次进入交易链路；
不得用 Redis 缓存账户事实放行交易；
FillSync 不直接生成或修改账户、余额和持仓快照；
新的 BinancePositionSnapshot 只能由新的账户同步形成。
```

### 12.2 PriceSnapshot

PriceSnapshot 是交易规划使用的 mark price 事实。

规则：

```text
正式来源只能是 BinanceGateway 的 mark price 受限接口；
不得从 BinancePositionSnapshot.mark_price、Kline close 或人工输入派生；
每个新业务请求必须实际请求一次 Binance，不返回 Gateway 历史缓存价格；
一轮 TARGET_POSITION 编排只能使用一份明确 PriceSnapshot；
OrderPlan、RiskCheck 和 ExecutionPreparation 必须使用同一份明确 PriceSnapshot；
不得按数据库 latest 或 Redis 裸价格选择交易价格事实；
Redis 只缓存已经写入 MySQL 的同一 PriceSnapshot；
PriceSnapshot 不代表最终报单价格或实际成交价。
```

`NO_TARGET_CHANGE / NO_TRADE` 自动分支不创建 PriceSnapshot。

## 13. 真实交易权限不变量

系统不建立独立的交易权限业务模块。

真实交易权限只来自：

```text
.env / Django settings 中的部署级真实交易硬权限；
MySQL 中由 OpsConsole 管理的真实交易运行开关。
```

最终权限：

```text
effective_real_trading_permission
= deployment_real_trading_permission
  AND runtime_real_trading_permission
```

规则：

```text
真实交易默认关闭；
.env 禁止时后台无法放行；
后台不得写 .env；
后台不得管理 API key 或 secret；
OrderPlanStepAdapter 在调用 OrderPlan 前检查一次最终权限；
检查必须早于 OrderPlan 和 ActiveLock；
权限明确关闭时不调用 OrderPlan、不生成 CandidateOrderIntent、不取得 ActiveLock，并正常结束本轮；
权限或市场配置不可读取时 fail-closed；
检查通过后，本轮后续步骤不得重新读取 MySQL 运行开关；
后台随后修改开关只影响下一次进入 OrderPlan 的检查；
Execution、OrderStatusSync 和 FillSync 不重复检查该开关；
已经存在的订单状态与成交同步不得因关闭新交易权限而中断；
已经提交的 LIMIT 订单周期收尾不得因关闭新交易权限而中断。
```

不得新增未经 requirements 明确定义的模块级交易开关、人工补查开关、成交补同步开关或复盘请求开关。

## 14. OrderPlan 与 RiskCheck 不变量

OrderPlan 是目标仓位到 CandidateOrderIntent 的唯一转换入口。

OrderPlan 只能读取 Connector 显式传入的：

```text
DecisionSnapshot；
trade_preparation BinanceSyncRun 及其事实；
PriceSnapshot。
```

OrderPlan 不得：

```text
访问 Binance；
刷新账户或价格；
真实下单或撤单；
做最终风控审批；
修改交易所杠杆或保证金模式；
根据可用余额自行缩小目标仓位。
```

RiskCheck 只审批既有 CandidateOrderIntent。

RiskCheck 不得：

```text
直接消费 DecisionSnapshot；
生成新的 CandidateOrderIntent；
任意修改方向、数量或订单组件；
临时生成 fallback；
刷新账户或 PriceSnapshot；
真实下单、撤单或修改交易所配置。
```

RiskCheck 只允许在 primary 新增风险部分不通过时，选择 OrderPlan 已经预生成且自身全部通过风控的 `fallback_reduce_only`。

只有 ALLOW 可以生成 ApprovedOrderIntent。DENY、BLOCKED、FAILED 和 unknown 都不得生成 ApprovedOrderIntent。

## 15. 杠杆与保证金模式不变量

系统任何时候都不得自动修改交易所杠杆或保证金模式。

禁止：

```text
调用 Binance 修改杠杆接口；
调用 Binance 修改保证金模式接口；
根据行情、策略、回测或复盘结果自动调整杠杆；
在 OrderPlan、RiskCheck、ExecutionPreparation 或 Execution 中修改杠杆；
用 observed_exchange_leverage 放大目标仓位；
用系统目标仓位比例冒充交易所杠杆。
```

字段语义必须区分：

```text
max_target_notional_to_equity_ratio
= OrderPlan 内部目标名义价值与账户权益的比例参数；

observed_exchange_leverage
= Binance Account Sync 观测到的交易所实际设置；

configured_exchange_leverage
= 部署配置中的环境校验值，如项目启用该校验。
```

`observed_exchange_leverage` 可以用于保证金风险估算和审计，不得参与目标仓位计算。缺失时不得伪造或用其他字段填充。

配置与观测不一致时，只能阻断真实交易、写 AlertEvent 并等待人工处理，不得自动修正交易所配置。

## 16. ExecutionPreparation 不变量

ExecutionPreparation 只消费 ApprovedOrderIntent，并冻结为 PreparedOrderIntent。

必须保持：

```text
原 OrderPlan、CandidateOrderIntent、RiskCheckResult 和 ApprovedOrderIntent 业务外键完整；
原订单链 BinanceSyncRun、PriceSnapshot 和 ActiveLock 身份一致；
订单参数不被缩小、放大、拆分或改向；
PreparedOrderIntent 唯一、短期有效且只能提交一次。
```

报单前价格检查必须：

```text
通过 BinanceGateway 实际请求实时盘口；
BUY 使用 best ask，SELL 使用 best bid；
与原订单链明确 PriceSnapshot.mark_price 比较；
把盘口结果保存为 ExecutionPreparationResult 证据；
不得把盘口结果写回或替代 PriceSnapshot；
不得把盘口价格写成实际成交价；
查询失败或结果无法确认时不得回退到 mark price 放行。
```

ExecutionPreparation 不得提交订单，也不重新读取真实交易运行开关。

## 17. 订单提交不变量

Execution 是唯一允许调用 BinanceGateway 订单提交接口的业务模块。

Execution 只消费有效且未提交的 PreparedOrderIntent。

同一个 PreparedOrderIntent 只能发生一次订单提交调用。

以下所有层级都不得重试订单提交：

```text
BinanceGateway；
Execution 业务层；
Celery；
PipelineOrchestrator；
management command；
OpsConsole 或任何人工入口；
任务恢复和进程崩溃恢复。
```

无论发生以下哪种结果，都不得再次提交同一个 PreparedOrderIntent：

```text
交易所明确拒绝；
HTTP 429；
HTTP 5xx；
超时；
网络断开；
响应损坏；
进程在提交后崩溃；
无法确认交易所是否收到请求。
```

`OrderSubmissionAttempt.accepted` 只表示交易所接受请求，不表示订单已经成交。

`OrderSubmissionAttempt.unknown` 不得推断成功或失败，不得自动释放 ActiveLock，必须通过独立订单生命周期同步管线进入 OrderStatusSync 查询。

LIMIT 订单到达冻结有效期后仍未终态时，只能由 OrderCycleCloseout 针对既有订单执行周期收尾撤单。该撤单不属于订单提交重试，不得演变成改单、追单、补单或解锁。

## 18. 订单状态、成交与持仓不变量

OrderStatusSync 只查询订单状态，不重新提交订单，不生成 TradeFill。

OrderCycleCloseout 只保存 OrderCancelAttempt 并触发后续状态与成交事实闭环，不直接生成订单终态、成交事实或 ActiveLock 释放结论。

FillSync 只消费明确终态的 OrderStatusSyncRecord，并通过 BinanceGateway 查询完整成交事实。

规则：

```text
NEW、PARTIALLY_FILLED、not_found 和 unknown 不得进入成交收尾；
FillSync 必须完整读取该订单全部成交页；
TradeFill 必须按交易所成交身份幂等；
OrderFillSummary 必须能追溯到 OrderSubmissionAttempt 和终态 OrderStatusSyncRecord；
incomplete、unknown、查询前失败或身份冲突不得作为解锁证据；
关闭新交易权限不能停止既有订单的状态与成交同步；
OrderStatusSync 和 FillSync 不得自行定义未由 OpsConsole 需求授权的人工补查、人工补同步入口或额外开关；已授权后台入口只负责权限、确认和审计，实际动作仍由对应业务 service 执行。
```

FillSync 不得直接更新 BinancePositionSnapshot，也不得根据本地 TradeFill 推导交易所真实持仓。

持仓事实只能来自新的 Binance Account Sync。

## 19. ActiveLock 不变量

OrderPlanActiveLock 是同一交易身份的唯一冲突订单链保护锁。

锁业务身份至少包括：

```text
exchange；
market_type；
account_domain；
symbol。
```

只有 OrderPlan 所属 OrderPlanActiveLockService 可以修改锁状态。

以下订单链业务模块只能提交证据并调用锁服务，不得直接写锁表：

```text
RiskCheck；
ExecutionPreparation；
Execution；
OrderStatusSync；
FillSync。
```

PipelineOrchestrator 只记录步骤结果和对象关联，不得调用锁服务。RuntimeGuard 只读巡检，不得调用锁服务。OpsConsole 如后续提供授权人工收尾，只能调用专门的后端维护 service，并写入完整审计，不得直接写锁表或绕过 ActiveLockService。

可以自动释放锁的事实必须明确证明：

```text
订单在提交前已经明确终止且未发送；
交易所明确拒绝订单；
订单已经明确终态且所需成交事实完整同步；
明确零成交终态且 FillSync 严格确认 synced_empty。
```

以下状态不得自动释放：

```text
OrderSubmissionAttempt unknown；
OrderStatusSync not_found 或 unknown；
订单 NEW 或 PARTIALLY_FILLED；
FillSync incomplete、unknown、failed_before_query、blocked_before_query 或 recovery_skipped_out_of_window；
仅凭余额或持仓变化进行倒推；
仅因锁存在时间较长；
仅因 RuntimeGuard 产生告警。
```

授权人工收尾必须调用 ActiveLockService，并记录操作者、原因、证据、修改前后状态、trace_id 和 AuditRecord。

## 20. Gateway 与外部请求不变量

### 20.1 BinanceGateway

所有 Binance REST 请求必须经过 BinanceGateway 的受限接口。

业务模块不得：

```text
直接创建 Binance HTTP client；
直接生成签名；
直接拼接 endpoint；
直接读取 Binance API key；
调用未在 Gateway 合同中开放的接口。
```

调用权限必须保持：

```text
DataCollection / DataBackfill → 公共 Kline 和 server time；
Binance Account Sync → 账户只读与公共交易规则；
PriceSnapshot → mark price；
ExecutionPreparation → book ticker；
Execution → 订单提交；
OrderCycleCloseout → 既有 LIMIT 订单撤销；
OrderStatusSync → 订单状态查询；
FillSync → 成交查询。
```

Gateway 只返回技术事实，不替代业务模块写业务状态、业务对象或 AlertEvent。

### 20.2 大模型边界

当前正式系统内不调用大模型做复盘，也不保存大模型复盘报告。

如后续重新引入系统内大模型复盘，必须先新增独立需求和红线定义。

### 20.3 Notifications 与 Hermes

业务模块只写 AlertEvent，不直接发送 Hermes。

Notifications 根据 AlertEvent 创建 NotificationDeliveryAttempt 或 NotificationSuppression。

Hermes 只负责外部通知，不得：

```text
触发交易；
触发撤单；
触发平仓、加仓或减仓；
生成 CandidateOrderIntent 或 ApprovedOrderIntent；
修改任何业务事实。
```

通知失败不得回滚业务事实，通知成功不得触发业务动作。

### 20.4 通用外部请求

所有外部请求必须：

```text
设置明确超时；
携带 trace_id 和受控调用上下文；
记录脱敏的错误分类、尝试次数和耗时；
不得泄露密钥；
不得无限重试。
```

安全读取类请求只允许由 Gateway 按对应合同进行有限技术重试，且这些尝试仍属于同一次业务调用。

业务层恢复读取动作时必须使用稳定业务幂等键，并先核对已有事实。

订单提交适用第 17 节的绝不重试规则，不适用安全读取重试。

## 21. 编排与追溯不变量

PipelineOrchestrator 只按照版本化 Registry 和 adapter 返回的统一结果推进流程。

OrchestrationBusinessConnector 负责理解业务模块原始返回，并映射：

```text
normalized_status；
flow_action；
reason_code；
business_object_refs。
```

编排层不得：

```text
解释业务模块内部状态；
直接访问 Binance 或 DeepSeek；
直接修改业务对象；
直接释放 ActiveLock；
直接提交订单；
在订单提交恢复时再次调用 Gateway；
使用大模型决定下一步骤。
```

业务对象之间必须使用真实业务外键保持因果关系。

主交易业务对象不得把 OrchestrationRun.id 当作正式业务外键或下游输入。

OrchestrationBusinessObjectLink 只提供整轮运行的快捷审计索引，不替代业务外键。

Connector 可以根据 Registry 和 ObjectLink 找到上一合法步骤的输出，但必须向下游 service 显式传递直接业务对象 ID。业务 service 不得接收 orchestration_run_id 后自行查询关联表猜测输入。

## 22. trace_id、trigger_source 与幂等不变量

`trace_id` 只用于技术追踪：

```text
结构化日志；
StepRun；
Gateway 调用上下文；
AlertEvent；
异常定位和跨进程追踪。
```

`trace_id` 不得：

```text
作为业务外键；
作为业务幂等键；
判断对象是否属于同一订单链；
替代 OrchestrationBusinessObjectLink；
替代交易所订单或成交身份。
```

所有关键任务和运行记录必须保存明确 `trigger_source`。异步 worker 不得覆盖原始触发来源；实际执行者需要单独记录。

每个业务模块必须使用稳定业务幂等键。业务幂等键不得直接使用：

```text
trace_id；
Celery task id；
worker 名称；
当前时间；
随机重试序号；
orchestration_run_id。
```

重复调度、重复消息投递、进程恢复和并发调用不得产生重复核心业务对象或重复订单提交。

## 23. RuntimeGuard 与 ReviewDataset 不变量

### 23.1 RuntimeGuard

RuntimeGuard 是独立只读巡检能力，只覆盖：

```text
自动编排主链路；
订单链路卡住和不确定状态；
ActiveLock 风险状态；
通知投递状态。
```

RuntimeGuard 不得：

```text
补跑业务；
恢复编排；
修改业务对象；
释放 ActiveLock；
重新提交订单；
访问 BinanceGateway；
直接发送 Hermes；
巡检 ReviewDataset 或普通后台页面功能。
```

### 23.2 ReviewDataset

ReviewDataset 是后台受控导出的复盘数据集能力，不是自动主链路步骤。

它只读取已经落库的编排、策略、账户、价格、订单、成交、告警、巡检和审计事实。

ReviewDataset 不得：

```text
请求 Binance；
调用 DeepSeek；
生成复盘结论；
判断策略是否正确；
按数据库最新对象猜测周期事实；
影响 OrchestrationRun；
生成交易信号；
修改订单、成交、账户或策略；
自动暂停或恢复交易。
```

### 23.3 本地复盘结果

Codex skill 或本地脚本生成的复盘结果默认只保存为本地文件，不是生产系统事实。

任何复盘建议进入生产前，必须经过人工确认、需求更新、回测或验证和风险复核。

## 24. MySQL 主存储不变量

MySQL 是核心业务、编排、审计、通知和复盘事实的主存储。

以下数据不得只存在于 Redis、Celery 消息或进程内存：

```text
Kline 和数据质量事实；
MarketSnapshot；
Feature、AtomicSignal、DomainSignal 和 MarketRegime；
StrategyRouteDecision、StrategySignal 和 StrategyAnalysisRelease；
DecisionSnapshot；
BinanceSyncRun 及其账户事实；
PriceSnapshot；
OrderPlan、CandidateOrderIntent 和 ActiveLock；
RiskCheckResult 和 ApprovedOrderIntent；
ExecutionPreparationResult 和 PreparedOrderIntent；
OrderSubmissionAttempt；
OrderCancelAttempt；
OrderStatusSyncRecord；
FillSyncResult、TradeFill 和 OrderFillSummary；
OrchestrationRun、StepRun 和 ObjectLink；
RuntimeGuardIssue；
AlertEvent、NotificationDeliveryAttempt 和 NotificationSuppression；
ReviewDatasetRecord；
ReviewDatasetExport；
AuditRecord。
```

通知投递必须以 MySQL pending NotificationDeliveryAttempt 为可靠来源，Celery 消息只能加速唤醒。

## 25. Redis 不变量

Redis 只允许用于：

```text
缓存；
分布式锁；
Celery broker；
Celery result backend；
短期幂等保护；
短期任务状态；
限流、冷却和熔断计数；
短期特征序列缓存；
PriceSnapshot 短期缓存；
通知冷却和防重复。
```

Redis 中的数据必须可过期、可重建，丢失后能够从 MySQL 或外部可信数据源恢复。

禁止 Redis：

```text
成为 Kline、账户、价格、订单、成交、策略、通知或复盘的唯一事实来源；
在 MySQL 事实缺失时用缓存默认放行真实交易；
替代数据库唯一约束；
成为 ActiveLock 的唯一业务事实；
成为真实交易权限事实来源。
```

## 26. 结构化存储与 JSON 不变量

核心时间序列和业务事实必须结构化存储。

禁止把以下内容整体塞进单个字段：

```text
大批量 Kline；
完整历史窗口；
完整指标数组；
完整 FeatureValue、AtomicSignalValue 或 DomainSignalValue 集合；
完整订单状态历史；
完整成交历史；
完整账户快照历史；
为了逃避表结构设计而形成的大 JSON。
```

JSON 字段只允许保存：

```text
有明确 schema 和大小边界的配置快照；
少量结构化 evidence；
摘要；
错误详情；
不可作为核心查询和外键关系替代的补充信息。
```

下游正式主链路不得硬编码依赖其他模块私有 JSON payload 的内部字段。

不可控长文本、大模型完整原始输出和大体积计算过程不得直接污染主业务表。需要保留时，应使用隔离对象、摘要、hash 和受控 storage reference。

## 27. 数值与字段语义不变量

金额、价格、数量、比例、手续费、保证金和收益等业务计算必须使用 Decimal 或等价精确十进制，不得使用二进制浮点数决定交易、风控或阈值边界。

Decimal 精度必须按字段业务含义设计，不得为所有字段机械使用同一套超大精度。

需要参与计算的数值不得为了省事保存为字符串。

核心字段不得使用无边界的模糊名称，例如：

```text
data；
info；
content；
extra；
payload；
result。
```

如果使用上述名称作为补充字段，必须明确内容 schema、大小边界和禁止用途。

核心表和核心字段必须具有中文业务说明。代码标识使用英文，中文说明必须解释业务含义、取值边界、是否可空和追溯作用。

## 28. Django Migration 不变量

数据库结构变更必须通过 Django migration。

禁止：

```text
手工修改核心表后不生成 migration；
在生产环境直接手工修改核心表结构；
同时维护第二套主迁移体系；
在 migration 中写入真实密钥、Token、Webhook secret 或 API key；
为了绕过 migration 评审而在启动代码中动态改表。
```

删除表、删除字段、重命名核心字段、增加唯一约束、增加大字段或改变关键精度时，必须在对应开发计划或决策中说明影响。

## 29. 配置与密钥不变量

配置必须来自明确的 `.env`、Django settings 或 requirements 指定的 MySQL 运行配置。

禁止在代码、文档示例、日志、异常、AlertEvent、审计记录、前端响应和 Hermes 消息中暴露：

```text
数据库密码；
Redis 密码；
Binance API key / secret；
DeepSeek API key；
Webhook secret；
真实 Token；
完整签名材料。
```

禁止硬编码：

```text
真实交易权限；
真实外部发送开关；
生产环境开关；
交易所 API key；
模型 API key；
杠杆配置。
```

`.env.example` 中所有配置项必须有中文注释且不得包含真实值。

OpsConsole 不得编辑 `.env`、管理 API key 或放大部署级硬权限。

## 30. Celery 与调度不变量

Celery task 只作为异步入口，Celery Beat 只作为定时入口。

task 和调度入口只能：

```text
解析参数；
生成或传递 trace_id；
保留 trigger_source；
执行基础权限校验；
调用 application service；
输出结构化摘要。
```

不得在 task、Beat 配置、management command 或 view 中实现复杂业务逻辑。

所有关键定时任务必须有数据库幂等或等价可靠兜底，重复调度不得导致重复业务对象或重复订单提交。

失败任务不得无限重试。订单提交任务不得配置任何自动重试。

订单提交相关任务重复执行时，只能读取已有 OrderSubmissionAttempt，不得再次调用订单提交 Gateway。

运行调度、后台任务和 RuntimeGuard 必须使用 UTC，不得依赖服务器本地时区。

## 31. 代码结构不变量

业务核心逻辑必须位于 service / domain / calculator 层。

禁止把复杂业务逻辑堆入：

```text
Django model；
Celery task；
management command；
view；
serializer；
repository；
scripts。
```

Django model 只定义数据结构和最小约束。

repository / selector 只封装数据库读写和稳定查询，不实现策略、风控或外部调用。

Gateway 只封装外部访问，不拥有业务状态。

入口层不得直接访问 Binance、DeepSeek 或 Hermes，不得直接提交订单、释放 ActiveLock 或修改业务状态。

模块之间必须通过明确 service、selector、Gateway 和真实业务外键协作，不得直接操作其他模块内部表和私有实现。

## 32. 执行模式隔离不变量

当前阶段不实现模拟交易运行模式。系统只保留 dry-run 与 real trading 的隔离规则。

规则：

```text
dry-run 不写正式交易对象，不进入真实下游；
real trading 只能消费真实账户、真实价格和正式订单链事实；
dry-run 结果不得进入 OrderPlan、RiskCheck、ExecutionPreparation、Execution、OrderStatusSync 或 FillSync；
真实交易不得通过前端参数无审计切换；
后续如新增模拟交易运行模式，必须先新增独立需求、架构和数据隔离设计，不得复用 real trading 表模拟。
```

## 33. 回测与实盘一致性不变量

未来回测能力必须尽量复用与正式运行相同的 calculator、Definition 和核心业务规则，但必须隔离数据源和执行结果。

禁止：

```text
look-ahead bias（前视偏差）；
使用实盘当时不可获得的数据；
使用包含当前 Kline 的区间值判断同一根 Kline 是否突破；
假设当前 Kline 收盘价可以无条件完美成交；
为了得到更好结果而跳过手续费、滑点、最小下单量、交易规则和风控边界；
把回测对象写入正式 real trading 业务表。
```

如果正式运行只能在 Kline 收盘后生成信号，回测也必须在相同信息时点生成信号。

## 34. 测试安全不变量

核心链路必须有自动化测试，不得只依赖人工测试。

测试必须覆盖：

```text
正常结果；
blocked、denied、failed 和 unknown；
幂等与重复消息；
并发与数据库唯一约束；
外部请求失败；
Redis 不可用；
配置关闭和权限不可读取；
StrategyAnalysisRelease 冲突；
ActiveLock 冲突和安全释放；
订单提交唯一性与绝不重试；
USDS-M / COIN-M 隔离；
dry-run 与 real trading 隔离。
```

默认测试不得：

```text
访问真实 Binance；
访问真实 DeepSeek；
发送真实 Hermes；
访问生产 MySQL 或生产 Redis；
提交、撤销或修改真实交易所订单；
修改真实交易所杠杆或保证金模式；
依赖真实密钥。
```

外部服务测试必须使用 fake、mock 或专门隔离环境。

任何声称验证真实交易的测试都必须由独立计划明确授权，并再次确认账户、环境、权限和资金风险。

## 35. UTC 时间不变量

Binance 返回的时间戳按 UTC 解释。

系统内部所有核心业务时间统一使用 UTC。

规则：

```text
Kline open_time / close_time 使用 Binance 返回的时间戳；
请求 Kline 不传 timeZone，使用 Binance 默认 UTC；
行情排序、连续性、策略周期、任务调度、订单追踪、成交同步和复盘全部使用 UTC；
不得根据服务器本地时区、用户 IP、浏览器时区或运行机器时区改变业务判断；
系统不设计参与业务判断的本地时间字段；
通知、日志和后台展示默认显示 UTC，并明确标注 UTC。
```

## 36. AlertEvent 与审计不变量

正式交易链路中的关键状态、阻断、失败和不确定结果必须写 AlertEvent。

至少包括：

```text
OrderPlan 和 CandidateOrderIntent 结果；
RiskCheck 结果和 fallback 选择；
ApprovedOrderIntent 结果；
ExecutionPreparation 结果；
OrderSubmissionAttempt 结果；
OrderCycleCloseout 和 OrderCancelAttempt 结果；
OrderStatusSync 关键状态；
FillSync 和 TradeFill 结果；
ActiveLock 保持、失败和释放；
真实交易权限配置不可读取；
关键数据、账户或价格事实不可用。
```

人工操作和高风险状态变更必须写 AuditRecord，至少记录：

```text
操作者；
操作来源；
目标对象；
修改前状态；
修改后状态；
原因；
证据；
结果；
trace_id；
UTC 时间。
```

审计记录不得替代业务对象状态，AlertEvent 不得替代 NotificationDeliveryAttempt。

## 37. 禁止静默降级不变量

以下情况禁止为了让流程继续而静默兜底：

```text
数据质量失败后继续生成 MarketSnapshot；
版本包不完整时选择其他 active Definition；
账户同步失败时读取历史 succeeded 或 ops_display；
PriceSnapshot 缺失或过期时读取 latest、Kline close 或持仓 mark price；
实时盘口查询失败时回退到 mark price；
风控缺少事实时默认 ALLOW；
订单提交 unknown 时推断失败并重提；
订单状态 not_found 时推断订单不存在并解锁；
成交 incomplete 时按已有部分成交解锁；
Redis 故障时使用不可信缓存放行交易；
通知失败时回滚或重放业务动作；
RuntimeGuard 发现问题后自动修改原业务对象；
复盘建议自动改变生产系统。
```

无法可靠判断时必须 fail-closed、保持 unknown、停止自动推进或保留保护状态，具体行为由对应 requirements 定义。

## 38. 本文档不承担的事项

本文档不规定普通业务配置值、数据库字段细节、算法公式和页面交互。

以下内容必须在对应 requirements、architecture 或 plans 中定义：

```text
具体阈值；
具体 TTL；
具体轮询周期；
具体字段精度；
具体索引；
具体 task 和 queue；
具体 API；
具体算法及其版本；
具体部署拓扑。
```

任何具体实现都必须能够说明自己没有违反本文档。

## 39. 最终结论

本项目的最高原则是：

```text
可信事实先于计算；
明确版本先于正式运行；
目标仓位与订单意图严格隔离；
风控与执行准备不可绕过；
订单提交只能发生一次；
unknown 必须保守处理；
真实交易权限不可绕过；
核心事实必须落入 MySQL；
所有关键行为必须可追溯、可审计、可测试；
大模型、通知、巡检和复盘不得反向触发交易。
```
