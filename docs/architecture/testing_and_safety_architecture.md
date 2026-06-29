# 测试与安全验收架构

## 1. 文档目的

本文档定义项目如何通过自动化测试、隔离环境、故障注入、CI 验收和实盘前人工准入，证明各项业务边界和交易保护机制已经正确实现。

本文档用于回答：

```text
实现一个模块时必须编写哪一层测试；
不同测试层分别验证什么；
测试如何替换 Binance 和 Hermes；
如何验证重复任务不会重复下单；
如何验证异常状态会安全停止；
如何验证 RuntimeGuard 只巡检不修复；
如何隔离 dry-run、回测和 real；
CI 在什么条件下阻止代码进入下一阶段；
开启真实交易前必须取得哪些证据。
```

本文档不是业务模块，不在生产环境持续运行，也不替代 RuntimeGuard。

具体模块测试用例以对应 requirements 的“测试要求”和“验收标准”为准。本文件只定义跨模块统一测试方法和安全门槛。

## 2. 使用方式

本文档由 Codex、开发人员、测试代码和 CI 流程共同使用。

标准使用顺序：

```text
阅读 project_invariants 和模块 requirements
→ 阅读相关 architecture
→ 在开发计划中引用本文件的测试层级和安全门槛
→ 实现业务代码时同步实现对应测试
→ 本地运行相关测试
→ CI 运行自动测试和安全检查
→ 保存测试与验收结果
→ 满足阶段验收条件后才进入下一开发阶段
→ 满足全部实盘准入条件后，才允许人工考虑开启真实交易。
```

本文件本身不会自动检查代码。它必须落实为：

```text
pytest / pytest-django 测试；
Django system checks；
数据库和 migration 验证；
Celery 集成测试；
fake Gateway；
CI job；
阶段验收报告；
实盘前人工确认清单。
```

## 3. 测试总原则

项目测试必须遵守：

```text
默认不访问真实外部服务；
默认不持有真实密钥；
默认不允许真实交易；
测试数据与生产数据物理或逻辑隔离；
每个模块只测试和验证自己的业务责任；
跨模块测试使用正式 service / adapter 边界，不绕过业务层；
所有关键成功、无动作、阻断、拒绝、失败和不确定结果都必须覆盖；
幂等、并发、任务重投和进程崩溃必须覆盖；
订单提交唯一性必须通过可计数 fake Gateway 证明；
任何无法确认的外部结果都必须验证为保守处理；
测试失败不能通过删除校验、降低断言或跳过危险用例解决；
测试结果必须可重复、可审查、可追踪。
```

## 4. 测试层级

### 4.1 calculator 单元测试

适用：

```text
FeatureLayer calculator；
AtomicSignal calculator；
DomainSignal calculator；
MarketRegime calculator；
StrategyRouting 纯规则匹配；
StrategySignal calculator；
DecisionPolicy calculator；
OrderPlan、RiskCheck 和价格保护中的纯计算规则。
```

验证：

```text
相同输入和版本得到相同输出；
边界值计算正确；
Decimal 精度正确；
输入顺序变化不改变规范化结果；
非法输入返回明确计算失败；
没有数据库、Redis、Celery、网络和时间副作用；
不读取 Django model 或 QuerySet；
不产生业务状态、订单或 AlertEvent。
```

calculator 测试应当快速、确定，不依赖测试数据库。

### 4.2 domain / service 合同测试

验证一个业务模块是否正确执行自己的需求合同。

至少覆盖：

```text
合法输入产生正确业务对象；
非法或不完整输入被阻断；
上游状态和市场身份校验；
业务幂等；
状态流转；
业务对象所有权；
必要 AlertEvent；
不得调用的下游和外部能力；
dry-run 或 confirm-write 行为（如模块定义）；
错误、阻断和 unknown 的保守处理。
```

service 测试不得直接修改数据库状态来模拟“成功实现”，应当通过正式 service 入口创建和推进对象。测试准备数据可以使用受控 factory 或 fixture。

### 4.3 repository / selector 与数据库约束测试

验证：

```text
真实业务外键完整；
唯一业务键和数据库唯一约束生效；
同一业务请求不会产生重复对象；
并发创建最终只有一个有效对象；
selector 只返回明确允许的对象；
不得按 latest 猜测交易输入；
不可变对象不能被覆盖；
MySQL 是正式事实；
Redis 丢失不改变数据库事实。
```

这一层使用隔离测试数据库，不访问生产数据库。

### 4.4 adapter 与 Connector 测试

验证：

```text
每个业务原始结果映射为正确 normalized_status；
每个结果映射为正确 flow_action；
业务对象引用完整；
Connector 向下游显式传递直接业务对象 ID；
业务 service 不通过 OrchestrationRun 查询输入；
NO_TARGET_CHANGE / NO_TRADE 正常完成，且不补做账户边界同步；
TARGET_POSITION 才进入 PriceSnapshot 和订单链；
blocked、failed 和 unknown 不被错误放行；
订单提交 unknown 进入状态查询而不是重新提交。
```

### 4.5 PipelineOrchestrator 集成测试

验证一轮编排的步骤顺序、条件分支、状态、对象关联和恢复。

至少覆盖：

```text
DataQuality PASS 直接进入 MarketSnapshot；
可回补缺口进入 DataBackfill 并重新质检；
回补循环达到上限后停止；
StrategyAnalysisRelease 缺失时在 FeatureLayer 前停止；
同一 run 全程使用同一冻结版本包；
NO_TARGET_CHANGE / NO_TRADE 不补做账户同步，也不生成 PriceSnapshot；
真实交易权限关闭时不调用 OrderPlan；
OrderPlan no_order_required 正常完成；
RiskCheck DENY 不进入 ExecutionPreparation；
ExecutionPreparation BLOCKED 不进入 Execution；
订单 accepted / unknown 登记或触发独立订单生命周期同步管线；
明确终态进入 FillSync；
每个步骤产生 StepRun 和必要 ObjectLink；
业务外键不被 ObjectLink 替代。
```

### 4.6 Celery 与运行任务测试

验证 `runtime_task_architecture.md` 的任务行为：

```text
同一自动周期重复触发只有一个 OrchestrationRun；
同一时刻只有一个 driver 推进同一 run；
WAIT 后持久化进度并释放 worker；
resume token 只能消费一次；
交易关键步骤通过独立逻辑队列交接；
同一任务重复投递不会重复业务动作；
OrderStatusSync 定向查询不依赖 Beat 全表扫描；
通知唤醒消息丢失后可以从 MySQL pending 记录恢复；
ReviewDataset 不占用交易关键任务资源；
worker 崩溃后以 MySQL 状态恢复。
```

Celery eager 模式可用于部分入口测试，但不能替代所有真实 worker 行为测试。WAIT、重复投递、并发认领和队列隔离必须在能够表达异步行为的集成测试中验证。

### 4.7 端到端业务链测试

端到端测试使用隔离数据库和 fake Gateway，执行完整自动流程：

```text
Kline
→ DataQuality
→ MarketSnapshot
→ Feature / Signal / Decision
→ Account Sync / PriceSnapshot
→ OrderPlan
→ RiskCheck
→ ExecutionPreparation
→ Execution。
```

订单提交后的 OrderStatusSync / FillSync 使用独立订单生命周期同步测试覆盖。端到端测试验证模块交接和整体结果，但不能替代每个模块的精细单元与合同测试。

### 4.8 故障注入测试

通过 fake Gateway、数据库故障替身、Redis 故障替身和受控进程中断，主动模拟：

```text
网络超时；
HTTP 429 / 5xx；
响应损坏；
外部请求结果 unknown；
数据库写入失败或提交结果不明确；
Redis 不可用；
Celery 消息丢失或重复；
worker 在关键时间窗口崩溃；
业务对象已写入但 ObjectLink 未写入；
订单提交后响应丢失；
订单状态持续 not_found / unknown；
成交分页不完整；
通知投递失败；
ReviewDataset 导出输入缺失或数据过大。
```

故障测试的目标不是证明系统永不失败，而是证明失败时不会越权、重复下单、误解锁、伪造事实或静默放行。

## 5. 测试环境分层

### 5.1 纯单元测试环境

```text
不连接数据库；
不连接 Redis；
不启动 Celery worker；
不访问任何外部服务；
使用固定输入、固定时间和纯 calculator。
```

### 5.2 数据库集成测试环境

```text
使用专用测试数据库；
由 Django test framework 创建和清理；
使用正式 ORM 与 migration；
不访问生产 MySQL；
不读取生产数据；
不复用生产数据库账号。
```

### 5.3 Redis / Celery 集成测试环境

```text
使用专用测试 Redis 或隔离数据库编号；
不得连接生产 broker、result backend 或缓存；
使用专门测试队列和 worker；
测试结束后可以安全清理；
Redis 状态不能成为测试断言的唯一业务依据。
```

### 5.4 当前阶段不提供模拟交易环境

当前阶段不实现模拟交易运行模式，不提供模拟订单、模拟成交或虚拟账户状态运行环境。

因此测试与验收必须证明：

```text
不存在模拟交易提交入口；
不存在虚拟持仓被 real OrderPlan、RiskCheck 或 Execution 消费；
如后续新增模拟交易运行模式，必须先补充独立需求、架构和数据隔离测试。
```

### 5.5 预生产验收环境

预生产环境用于验证部署配置、任务调度、数据库 migration 和完整运行流程。

默认要求：

```text
真实交易硬权限关闭；
MySQL 真实交易运行开关关闭；
订单提交 Gateway 使用 fake、阻断适配器或交易所明确隔离环境；
使用非生产数据库和 Redis；
不持有生产交易密钥；
不发送正式 Hermes 通知；
离线复盘大模型调用不在项目测试环境内执行。
```

### 5.6 生产环境

生产环境不是自动化测试环境。

不得为了“验证一下”在生产环境自动提交真实订单、撤单、修改杠杆或修改保证金模式。

生产运行问题由业务状态、日志、AlertEvent、RuntimeGuard 和 OpsConsole 观察，不以破坏性测试代替监控。

## 6. 外部服务替身架构

### 6.1 Binance fake Gateway

所有 Binance 受限接口都必须有可注入 fake 实现：

```text
Kline 和 server time；
账户、余额、持仓和交易规则；
mark price；
book ticker；
订单提交；
订单状态；
成交查询。
```

fake 必须支持配置：

```text
正常响应；
明确拒绝；
超时；
429 / 5xx；
响应缺字段；
结果 unknown；
重复成交；
分页不完整；
市场身份不一致；
调用次数统计。
```

订单提交 fake 必须记录调用次数，使测试能够明确证明同一 PreparedOrderIntent 只调用一次提交接口。

### 6.2 Hermes fake client

必须支持：

```text
投递成功；
明确失败；
超时和结果不确定；
通道不可用；
调用次数统计；
消息脱敏检查；
消息长度检查。
```

通知测试不得发送真实消息。

### 6.3 禁止意外网络访问

测试配置必须默认把真实外部适配器替换为 fake。

在测试环境中如果代码尝试创建真实 Binance、Hermes 或项目内未授权外部大模型 client，应立即失败，而不是静默访问网络。

不能只依赖“没有配置 API key”防止真实请求；测试依赖注入和 settings 必须从入口上禁止真实 adapter。

## 7. 时间测试架构

所有业务时间按 UTC 测试。

测试应使用可控制的 UTC 时钟或明确 reference time，覆盖：

```text
Kline 已收盘与未收盘边界；
4h / 1d 时间窗口；
00:05 与其他四小时自动边界；
PriceSnapshot 到期边界；
PreparedOrderIntent 到期边界；
价格偏离等于阈值的边界；
OrderStatusSync 第 2 秒和第 30 秒；
RuntimeGuard 15 分钟、30 分钟和提醒间隔；
ReviewDataset UTC 4 小时周期边界。
```

测试不得依赖运行机器本地时区，也不得通过 sleep 等待真实时间流逝。

## 8. 数据链路测试

### 8.1 DataCollection

必须证明：

```text
只采集 Binance USDS-M BTCUSDT 4h / 1d；
只写入已收盘 Kline；
重复采集幂等；
采集域不受 active trading domain 影响；
Gateway unknown 不放行；
Redis 不可用时仍由 MySQL 唯一约束保护事实。
```

### 8.2 DataQuality 与 DataBackfill

必须证明：

```text
缺失、重复、冲突和时间断档可以发现；
不可消费窗口不能生成 MarketSnapshot；
回补只通过 BinanceGateway；
回补后必须重新质检；
并发回补不会重复或覆盖可信 Kline；
回补循环有上限；
dry-run 不写正式事实。
```

### 8.3 MarketSnapshot

必须证明：

```text
只消费 PASS 的明确质量窗口；
同一业务输入幂等；
blocked、failed 和 unknown 不进入 FeatureLayer；
MarketSnapshot 与 PriceSnapshot 不混用；
不访问 Binance、账户或订单事实。
```

## 9. 策略分析测试

### 9.1 StrategyAnalysisRelease

必须证明：

```text
只有唯一已批准并启用版本包可以冻结；
依赖闭包、Definition、calculator 和 hash 全部一致；
并发批准不会产生两个当前版本包；
运行途中切换不改变已冻结 run；
任一步骤发现版本不一致时停止；
后台研究对象不能进入正式主链路。
```

### 9.2 Feature 到 DecisionSnapshot

每一层必须证明：

```text
只消费直接上游正式对象；
只运行版本包选择的定义；
不动态加入其他 active 定义；
calculator 输出经 service 校验后才落库；
blocked、failed、unknown 和 dry-run 结果不放行；
业务外键完整；
同一输入确定且幂等；
不会访问账户、价格或订单 Gateway。
```

### 9.3 策略输出标准化

不同策略必须通过测试证明其 StrategySignal 输出具有统一业务语义。

DecisionSnapshot 对相同标准化输入不得因为策略名称、市场环境名称或算法名称不同而采用隐藏分支。

### 9.4 具体算法验证

具体算法测试依据对应算法 requirements，至少包括：

```text
公式和边界值；
固定样本；
缺失输入；
极端输入；
历史回放；
版本变化；
回测验证要求；
不得使用未来数据。
```

算法没有验证通过，不得进入 StrategyAnalysisRelease。

## 10. 账户与价格事实测试

### 10.1 Binance Account Sync

必须证明：

```text
每个新 trade_preparation 请求形成新的完整同步批次；
OrderPlan 与 RiskCheck 使用同一明确批次；
ops_display 不能进入交易链路，也不能作为 ReviewDataset 的交易账户边界；
USDS-M 与 COIN-M 不混用；
账户、余额、持仓或交易规则任一不完整时不放行；
自动四小时编排起始阶段形成账户边界事实；
Redis 不能代替账户事实；
不会修改杠杆或保证金模式。
```

### 10.2 PriceSnapshot

必须证明：

```text
每个新正式价格请求实际调用一次 Binance mark price；
相同业务请求返回同一快照且不再次请求；
不同请求不混用；
只在 TARGET_POSITION 自动分支创建；
Redis 只缓存同一 MySQL 事实；
缓存损坏时回读 MySQL，不选择其他价格；
过期后不刷新或替换同一订单链价格；
不从账户持仓或 Kline 派生。
```

## 11. 真实交易权限测试

必须覆盖以下组合：

```text
部署硬权限关闭 + 后台开关关闭；
部署硬权限关闭 + 后台开关开启；
部署硬权限开启 + 后台开关关闭；
部署硬权限开启 + 后台开关开启；
任一配置不可读取；
市场配置不一致。
```

必须证明：

```text
只有两项权限同时允许才调用 OrderPlan；
明确关闭时不调用 OrderPlan、不生成 CandidateOrderIntent、不取得 ActiveLock；
不可读取时 fail-closed；
权限只在进入 OrderPlan 前检查一次；
检查通过后后台关闭只影响下一次准入；
关闭新交易不停止既有 OrderStatusSync 和 FillSync；
OpsConsole 无法修改 .env 或密钥。
```

自动化测试不得为了覆盖“允许”组合而连接真实订单提交 Gateway。

## 12. OrderPlan 与 RiskCheck 测试

### 12.1 OrderPlan

必须证明：

```text
只有合法 TARGET_POSITION 进入；
明确账户和价格事实一致；
USDS-M 与 COIN-M 数量公式隔离；
symbol rule 正确规范化数量；
不使用观测杠杆放大目标仓位；
无需调整仓位时不创建 CandidateOrderIntent 或 ActiveLock；
需要交易时 OrderPlan、CandidateOrderIntent 和 ActiveLock 同一事务成立；
重复调用不重复创建候选订单或锁；
旧 ActiveLock 阻断新冲突订单；
不访问 Binance。
```

### 12.2 RiskCheck

必须证明：

```text
只消费 CandidateOrderIntent；
执行全部适用正式规则；
ALLOW 才生成 ApprovedOrderIntent；
DENY、BLOCKED、FAILED 不生成；
不缩单、不改向、不重新设计订单；
只选择 OrderPlan 预生成的 fallback_reduce_only；
缺少事实时 BLOCKED，不默认放行；
插件不访问数据库或 Binance；
dry-run 与正式使用同一规则但不写正式结果。
```

## 13. ExecutionPreparation 测试

必须证明：

```text
只消费 ApprovedOrderIntent；
读取原订单链同一账户和 PriceSnapshot；
每次实际请求 book ticker；
BUY 使用 best ask，SELL 使用 best bid；
价格偏离小于或等于 1% 时允许，大于 1% 时阻断；
查询失败不回退 mark price；
盘口结果不创建或覆盖 PriceSnapshot；
盘口结果不被写成成交价；
不修改方向、数量和 reduce-only；
PreparedOrderIntent 唯一且过期后不可恢复；
不调用订单提交 Gateway。
```

阈值边界必须使用 Decimal 测试，不能用浮点近似判断。

## 14. 订单提交最高安全测试

订单提交测试是实盘准入的强制阻断项。

### 14.1 唯一提交

使用可计数 fake Gateway：

```text
创建一条 PreparedOrderIntent；
并发或顺序触发多个相同 Execution task；
模拟 Celery 重投；
模拟 worker 重启；
模拟编排恢复；
模拟人工重复点击。
```

最终必须证明：

```text
订单提交 Gateway 调用次数恒等于一次；
只有一条有效 OrderSubmissionAttempt；
没有第二条交易所提交动作；
重复入口返回已有事实或保守状态。
```

### 14.2 所有错误都不重提

分别模拟：

```text
HTTP 429；
HTTP 5xx；
网络超时；
连接中断；
响应损坏；
明确拒绝；
提交后进程崩溃；
结果 unknown。
```

每种情况都必须断言不会第二次调用提交 Gateway。

### 14.3 unknown 路径

必须证明：

```text
unknown 不被改写成成功或失败；
unknown 不释放 ActiveLock；
unknown 使用原 client order identity 进入 OrderStatusSync；
OrderStatusSync 不回到 Execution；
RuntimeGuard 不重新提交。
```

任何一个用例出现第二次订单提交调用，整个交易执行阶段验收失败。

## 15. OrderStatusSync 与 FillSync 测试

### 15.1 OrderStatusSync

必须证明：

```text
accepted 和 unknown 都可以查询；
第一次查询发生在两秒边界；
每两秒最多一个逻辑轮次；
三十秒后停止短轮询；
Celery 重复投递同一轮次不重复查询；
NEW、PARTIALLY_FILLED、not_found 和 unknown 不释放锁；
明确终态才进入 FillSync；
关闭新交易不停止既有状态同步；
不重新提交订单；
不生成 TradeFill 或 BinancePositionSnapshot。
```

### 15.2 FillSync

必须证明：

```text
只消费明确终态；
完整读取全部成交分页；
TradeFill 幂等；
成交数量与终态一致；
synced 与严格 synced_empty 才能进入锁收尾判断；
incomplete、unknown 和查询前失败不释放锁；
不会生成或修改 BinancePositionSnapshot；
不会生成额外 Tracking 交接对象；
关闭新交易不停止既有成交同步；
不重新提交订单。
```

## 16. ActiveLock 测试

必须覆盖：

```text
同一交易身份同时只能有一条有效冲突订单链；
OrderPlan 与 ActiveLock 同一事务创建；
其他模块不能直接修改锁；
提交前明确未发送可以安全释放；
交易所明确拒绝可以安全释放；
终态且成交同步完整可以安全释放；
严格 synced_empty 可以安全释放；
unknown、not_found、NEW、PARTIALLY_FILLED、incomplete 和超时都不能释放；
RuntimeGuard 告警不能释放；
人工收尾必须通过 ActiveLockService 并写审计；
旧锁存在时新四小时周期仍能完成数据、策略和账户步骤，但不能创建冲突订单链。
```

## 17. RuntimeGuard 测试

RuntimeGuard 测试必须模拟已落库的异常状态，验证其发现能力和只读边界。

至少覆盖：

```text
自动编排漏跑；
Run / StepRun 长时间 running 或 waiting；
步骤成功但业务对象关联缺失；
NO_TARGET_CHANGE / NO_TRADE 没有 PriceSnapshot 不被误报；
正常无交易分支缺少 BinanceSyncRun 可以发现；
ActiveLock 长时间 active；
OrderSubmissionAttempt submitting 或 unknown 长期不明确；
OrderStatusSync 长期不明确；
FillSync incomplete 或 unknown；
通知 pending / sending / unknown 长期未完成；
同一问题重复巡检不重复创建 Issue 或持续刷屏。
```

每个用例还必须证明 RuntimeGuard 不会：

```text
创建或恢复 OrchestrationRun；
消费 resume token；
调用 Binance；
修改订单、成交、账户或锁；
重新提交订单；
直接发送 Hermes；
调用大模型；
巡检 ReviewDataset。
```

## 18. Notifications 测试

必须证明：

```text
AlertEvent 与首个 DeliveryAttempt 或 Suppression 可靠交接；
Celery 唤醒消息丢失不会永久漏投；
pending worker 并发认领不会重复发送；
Redis 不可用时 AlertEvent 不丢失；
通知失败不回滚业务；
通知成功不触发业务；
unknown 投递不自动重复发送；
敏感信息被拒绝或脱敏；
外部投递关闭时仍保存 AlertEvent；
RuntimeGuard 能发现投递卡住但不替代通知发送。
```

Hermes fake 必须能够证明消息中不存在密钥、签名和完整外部原始响应。

## 19. 后台与 ReviewDataset 测试

### 19.1 ReviewDataset

必须证明：

```text
只读取已落库事实；
账户边界只使用自动 trade_preparation 账户快照；
忽略 ops_display 和人工刷新作为交易账户边界；
NO_TARGET_CHANGE / NO_TRADE、no_strategy 或策略链路提前结束的周期仍可导出；
缺少必要事实时记录缺失原因，不伪造数据；
重复导出使用输入指纹幂等返回已有有效数据集；
不请求 Binance；
不调用外部大模型；
不影响编排和交易事实；
RuntimeGuard 不巡检其任务状态。
```

### 19.2 OpsConsole

OpsConsole 必须同时覆盖 Next.js 前端测试和 Django API 权限测试，并证明：

```text
未登录用户不能读取后台数据或执行后台动作；
前端使用 HttpOnly session cookie，不把登录凭据保存到 localStorage；
所有写操作具备 CSRF 防护；
前端隐藏按钮不替代 Django 后端权限校验；
危险操作要求明确目标、二次确认、原因和 AuditRecord；
前端不能直接访问 MySQL、Redis、BinanceGateway、外部大模型或 Hermes；
前端不复制交易状态机、复盘数据构建规则或 ActiveLock 规则；
账户刷新只生成 ops_display 事实；
订单补查、成交补同步和 ActiveLock 人工收尾只调用已授权业务 service；
任何后台入口都不能重新提交订单；
真实交易运行开关不能突破部署级硬权限；
API 响应、页面错误和浏览器日志不暴露密钥、签名、完整外部响应或未脱敏复盘数据。
```

## 20. dry-run、回测与 real 隔离测试

必须证明：

```text
dry-run 不写正式交易对象；
dry-run 结果不能进入正式下游；
回测结果不写入 real trading 业务表；
当前阶段不存在模拟交易运行入口；
real 链路只消费真实账户、真实价格和正式业务对象；
不同模式的任务和查询不会相互选择数据；
模式切换有明确人工确认和审计；
测试环境永远不能通过参数切换为 real Gateway。
```

## 21. Migration 与数据结构测试

每个数据库结构变更必须测试：

```text
Django migration 可以在空测试数据库执行；
从当前正式 migration 状态可以向前升级；
模型与 migration 一致；
唯一约束、外键和关键索引存在；
默认值不会意外放行真实交易；
不可空字段具有安全迁移路径；
迁移不包含真实密钥或生产数据；
删除、重命名和精度变化有独立影响说明。
```

不要求每个 migration 都自动反向回滚，但不可逆操作必须明确标记并在开发计划中说明恢复方式。

## 22. Django system checks

项目应使用 Django 内建 system check 框架承载不需要运行完整业务流程的启动前检查。

适合检查：

```text
必要 settings 是否存在；
环境标识是否明确；
测试环境是否禁用真实外部 adapter；
真实交易硬权限是否默认关闭；
active market domain 是否唯一且合法；
Celery timezone 是否为 UTC；
数据库和 Redis 配置是否使用明确环境来源；
生产配置是否缺少必要安全项；
危险配置组合是否应 fail-closed。
```

system check 不得：

```text
提交测试订单；
调用真实 Binance 验证密钥；
修改数据库业务对象；
自动开启或关闭真实交易；
替代完整测试套件。
```

## 23. CI 验收层级

CI 应按从快到慢的顺序执行。

### 23.1 基础检查

```text
文档和配置文件可解析；
Django system checks；
migration consistency；
禁止真实密钥和危险测试配置；
必要依赖和 Python / Django 版本符合约束。
OpsConsole 的 Node.js 版本、package.json 和唯一锁文件符合约束；
Next.js lint、TypeScript typecheck 和 production build 通过。
```

### 23.2 快速测试

```text
calculator 单元测试；
纯 domain 规则测试；
序列化和输入合同测试。
OpsConsole 组件、权限显示、确认对话框和 API client 单元测试。
```

### 23.3 数据库和模块测试

```text
repository / selector；
service 合同；
幂等和唯一约束；
模块 AlertEvent；
fake Gateway 交互。
OpsConsole Django API 的认证、CSRF、权限、审计和敏感字段过滤测试。
```

### 23.4 编排和异步测试

```text
adapter / Connector；
PipelineOrchestrator；
Celery WAIT 与恢复；
RuntimeGuard；
Notifications；
队列隔离和重复投递。
```

### 23.5 交易安全测试

```text
真实交易权限组合；
OrderPlan / RiskCheck；
ExecutionPreparation price guard；
订单提交唯一性；
unknown 全链路；
ActiveLock；
OrderStatusSync / FillSync；
dry-run / 回测 / real 隔离。
```

### 23.6 端到端验收

使用 fake 外部服务执行主要成功、无动作、阻断、不确定和故障场景。

任何前置层失败，后续层不得通过跳过测试继续。

## 24. CI 失败规则

出现以下任一情况，CI 必须失败：

```text
测试尝试访问真实 Binance、Hermes 或项目内未授权外部大模型；
测试读取到真实密钥；
OpsConsole lint、typecheck、build 或前端测试失败；
后台写接口缺少认证、CSRF、后端权限或危险操作审计；
相同 PreparedOrderIntent 触发超过一次订单提交调用；
unknown 被自动当成成功或失败；
风控未通过却生成 ApprovedOrderIntent；
ExecutionPreparation 未通过却进入 Execution；
ActiveLock 在证据不足时被释放；
跨 market_type 或 account_domain 消费事实；
后台研究或 dry-run 对象进入正式链路；
Redis 成为核心事实唯一来源；
RuntimeGuard 修改业务对象；
ReviewDataset 或 Notifications 触发交易；
关键 migration、唯一约束或外键不一致；
规定的交易安全测试被跳过。
```

不得通过标记跳过、删除断言、降低测试范围或改用更宽松配置使危险测试变绿。

## 25. 阶段验收证据

每个开发阶段完成后至少保存：

```text
实际执行的测试命令；
通过、失败和跳过数量；
失败原因与处理结果；
使用的测试环境说明；
是否访问外部服务；
是否使用 fake Gateway；
数据库 migration 检查结果；
关键安全场景结果；
明确未覆盖事项；
是否涉及真实交易；
是否违反 project_invariants。
```

不得用“代码看起来没问题”或“手工点过一次”替代测试证据。

## 26. 实盘前安全准入

开启真实交易不是自动化测试动作，必须由人工完成最终确认。

### 26.1 自动化前置条件

至少满足：

```text
全部基础、模块、编排和交易安全测试通过；
订单提交唯一性测试通过；
unknown、ActiveLock 和状态同步测试通过；
USDS-M / COIN-M 隔离测试通过；
fake 端到端流程通过；
migration 和 Django system checks 通过；
测试环境没有访问真实外部服务；
没有被跳过的强制交易安全测试。
```

### 26.2 隔离演练

在非生产数据库和隔离任务环境中运行：

```text
完整自动编排；
NO_TARGET_CHANGE / NO_TRADE 分支；
真实交易权限关闭分支；
OrderPlan、RiskCheck 和 ExecutionPreparation；
fake Execution accepted / rejected / unknown；
OrderStatusSync 和 FillSync；
RuntimeGuard 和 Notifications。
```

演练必须证明不会产生真实订单或污染生产事实。

### 26.3 配置检查

人工检查：

```text
部署环境身份正确；
active market domain 正确且唯一；
数据库、Redis、Celery 和 Gateway 指向预期环境；
真实交易硬权限仍处于预期状态；
MySQL 运行开关仍处于预期状态；
API key 权限符合最小授权；
通知通道和审计可用；
RuntimeGuard 和订单追踪 worker 正常；
回滚和人工停止路径明确。
```

配置检查不得输出完整密钥。

### 26.4 人工批准

自动化测试和 system checks 只能证明代码和配置符合已知规则，不能自行决定承担真实资金风险。

真实交易开启必须由授权人员明确确认：

```text
测试证据；
部署版本；
交易市场；
账户；
真实交易风险；
启用时间；
操作原因；
审计记录。
```

系统不得根据测试通过结果自动修改 `.env` 或 MySQL 真实交易运行开关。

## 27. 与 RuntimeGuard 的关系

testing_and_safety_architecture 负责上线前和开发过程中的验证规范。

RuntimeGuard 负责上线后的定时运行巡检。

两者没有运行调用关系：

```text
测试代码验证 RuntimeGuard 是否正确发现问题；
RuntimeGuard 不读取测试结果；
测试系统不代替 RuntimeGuard 巡检生产状态；
RuntimeGuard Issue 不自动触发测试或重新部署；
测试通过不表示生产环境永远不会出现异常。
```

## 28. 与 project_invariants 和 requirements 的关系

```text
project_invariants 定义绝对不能违反什么；
requirements 定义每个模块必须做什么；
architecture 定义系统如何组织；
本文件定义如何证明这些规则已经正确实现；
RuntimeGuard 定义上线后如何发现运行异常。
```

测试不能创造 requirements 没有的业务能力，也不能通过测试夹具改变正式业务语义。

## 29. 当前不固定的实现细节

以下内容留到开发计划确定：

```text
CI 平台；
CI job 的具体名称；
测试目录最终结构；
fixture / factory 使用的具体库；
并发测试工具；
覆盖率工具和数值门槛；
测试报告存储位置；
预生产部署拓扑；
真实交易批准人的组织流程。
```

无论采用什么工具，都不得削弱本文档的外部隔离、订单唯一提交、故障安全和人工实盘批准规则。

## 30. 验收标准

测试与安全验收架构成立必须满足：

```text
每个模块 requirements 的测试要求能够映射到明确测试层；
calculator、service、数据库、adapter、编排、任务和端到端测试职责清楚；
测试默认替换 Binance 和 Hermes；
测试环境无法意外进入真实交易；
所有关键状态和故障路径有测试方法；
订单提交唯一性可以用 fake Gateway 调用次数证明；
WAIT、重复任务和进程崩溃可以验证；
ActiveLock 只能在证据完整时释放；
RuntimeGuard 的发现能力和只读边界可以验证；
通知可靠交接和离线任务隔离可以验证；
dry-run、回测和 real 数据隔离可以验证；
CI 有明确失败条件；
阶段交付必须提供真实测试证据；
实盘前需要自动化检查、隔离演练和人工批准；
测试通过不会自动开启真实交易。
```

## 31. 最终结论

本项目的测试目标不是只证明正常流程能运行，而是证明：

```text
错误输入不能穿透边界；
失败不会静默放行；
不确定结果不会被猜测；
任务重复不会产生重复事实；
订单提交永远只有一次；
锁不会在证据不足时释放；
外部服务不会在测试中被误调用；
离线能力不会影响实时交易；
生产异常能够由 RuntimeGuard 发现；
真实交易只能在测试证据和人工授权都具备后开启。
```
