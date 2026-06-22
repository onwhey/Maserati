# PerformanceMetrics 需求

## 1. 模块定位

PerformanceMetrics 是账户绩效复盘模块。

本模块基于自动编排边界产生的账户事实快照，计算每个 UTC 4 小时已关闭周期的持仓表现，并整理策略目标仓位、实际持仓、订单、成交、告警和巡检问题等复盘上下文。

核心定位：

```text
账户绩效复盘；
周期浮动收益统计；
策略目标仓位表现解释；
后台图表和离线复盘的数据来源。
```

本模块不是：

```text
策略模块；
订单规划模块；
风控模块；
执行模块；
账户总览展示模块；
大模型实时交易模块。
```

PerformanceMetrics 的结果只用于复盘、展示、审计和离线分析，不参与实时交易决策。

## 2. 核心原则

```text
只读取已落库事实；
只使用自动编排边界绑定的 trade_preparation 账户快照；
真实交易权限关闭不影响自动边界账户快照用于绩效计算；
自动四小时编排一开始必须生成账户边界快照，后续无交易、权限关闭或策略链路提前结束都不影响该快照用于绩效计算；
不使用 ops_display 账户快照；
不请求 Binance；
不主动刷新账户；
不查询订单状态；
不查询成交；
不生成订单；
不释放 ActiveLock；
不影响主交易编排是否继续；
所有业务时间统一 UTC。
```

PerformanceMetrics 的主收益口径是：

```text
Cycle Floating PnL
周期浮动收益
Mark-to-Market PnL
```

它用于回答：

```text
这个 4 小时周期里，策略提出或维持的目标仓位表现如何？
```

它不用于回答：

```text
某一笔订单最终平仓赚了多少钱？
```

## 3. 负责事项

本模块负责：

```text
识别可计算的 UTC 4 小时已关闭周期；
找到周期开始边界和结束边界对应的自动 OrchestrationRun；
读取两个边界 run 绑定的 trade_preparation BinanceSyncRun；
读取账户、余额、持仓和标记价格事实；
读取开始边界 run 的 DecisionSnapshot、OrderPlan、订单、状态和成交上下文；
计算周期浮动收益；
记录目标仓位、实际持仓、是否调仓、是否成交等复盘字段；
保存 OrchestrationRunPerformance；
为后台图表、编排详情页和离线 AIReview 提供查询数据；
支持后台一键扫描缺失周期并补齐；
支持幂等补算。
```

## 4. 不负责事项

本模块不负责：

```text
生成 MarketSnapshot、FeatureLayer、AtomicSignal 或 StrategySignal；
生成 DecisionSnapshot；
生成 PriceSnapshot；
生成 OrderPlan 或 CandidateOrderIntent；
执行 RiskCheck；
生成 ApprovedOrderIntent；
执行 ExecutionPreparation；
提交订单；
查询订单状态；
查询成交；
修改 BinanceSyncRun 或账户快照；
修改 PriceSnapshot；
修改 OrderSubmissionAttempt；
修改 OrderStatusSyncRecord；
修改 FillSyncResult 或 TradeFill；
修改 BinancePositionSnapshot；
释放或关闭 ActiveLock；
调用 Binance Gateway；
调用 Hermes；
调用大模型生成实时交易结论。
```

## 5. 周期划分

PerformanceMetrics 按 UTC 4 小时已关闭周期计算：

```text
00:00 - 04:00
04:00 - 08:00
08:00 - 12:00
12:00 - 16:00
16:00 - 20:00
20:00 - 00:00
```

自动边界 run 的账户快照时间来自编排调度：

```text
00:05 UTC：daily_boundary run；
04:05 UTC：four_hour_boundary run；
08:05 UTC：four_hour_boundary run；
12:05 UTC：four_hour_boundary run；
16:05 UTC：four_hour_boundary run；
20:05 UTC：four_hour_boundary run。
```

必须明确区分：

```text
收益周期边界 = UTC 4 小时 K 线边界；
自动编排运行时间 = 边界后 5 分钟；
账户快照时间 = 自动编排中 Binance Account Sync 成功保存的 as_of_utc。
```

不得使用服务器本地时区、用户时区或运行机器时区参与周期判断。

## 6. 周期归属规则

一个周期收益由相邻两个自动边界账户快照计算。

示例：

```text
00:05 自动边界账户快照
+ 04:05 自动边界账户快照
→ 计算 00:00 - 04:00 周期表现。

04:05 自动边界账户快照
+ 08:05 自动边界账户快照
→ 计算 04:00 - 08:00 周期表现。
```

同一条边界账户快照具有双重复盘用途：

```text
作为上一已关闭周期的结束状态；
作为下一周期的开始状态。
```

`OrchestrationRunPerformance` 归属于周期开始边界 run，并同时记录周期结束边界 run。

含义：

```text
start_orchestration_run = 提出或维持该周期目标仓位的自动 run；
end_orchestration_run = 提供该周期结束账户事实的自动 run。
```

该归属只用于复盘和审计，不允许交易模块把 PerformanceMetrics 结果作为实时输入。

## 7. 触发入口

PerformanceMetrics 不作为主交易链路的阻断步骤。

如果某个自动编排周期因为真实交易权限关闭而没有进入 OrderPlan，只要该周期仍然成功产生自动 `trade_preparation` 账户快照，PerformanceMetrics 仍然可以计算相邻 4 小时周期的持仓表现。

真实交易权限关闭只表示本轮不允许进入正式下单链路，不表示账户事实不可用于复盘。

自动四小时编排的 `trade_preparation` 账户同步发生在流程起始阶段。无论后续 DecisionSnapshot 是 `TARGET_POSITION`、`NO_TARGET_CHANGE`、`NO_TRADE`，还是流程在策略链路中正常提前结束，该账户快照都具有相同的周期边界资格。

P0 合法触发入口只有后台受控补算入口。

后台入口的业务语义是：

```text
用户点击一次；
系统扫描所有已关闭、可计算、但尚未生成有效绩效记录的 4 小时周期；
对缺失周期逐个补算；
已经存在有效绩效记录的周期直接跳过；
最终返回本次扫描、补算、跳过和失败的结构化摘要。
```

本模块 P0 不要求定时调用，也不要求每轮编排结束后自动触发。

如果后续实现为了避免后台请求超时而使用 Celery，只能作为“用户点击后触发的后台任务”，不得设计为 Celery Beat 定时自动补算。

后台一键补算的扫描规则：

```text
只扫描已经关闭的 UTC 4 小时周期；
周期开始边界和结束边界都必须存在自动 OrchestrationRun；
两个边界 run 都必须能通过 OrchestrationBusinessObjectLink 找到 trade_preparation BinanceSyncRun；
两个 BinanceSyncRun 都必须成功且快照完整；
同一周期已经存在有效 OrchestrationRunPerformance 时跳过；
缺少任一边界事实时不猜测、不请求 Binance、不用最新快照兜底。
```

后台一键补算失败不得影响主交易编排继续执行。

PerformanceMetrics 后台补算任务失败不得改变 `OrchestrationRun.status`。

## 8. 对外服务入口

本模块必须提供明确 service 入口。

### 8.1 后台一键补算

语义接口：

```text
backfill_missing_closed_period_performance(
    operator_id,
    reason,
    trace_id,
)
```

要求：

```text
由系统自动扫描所有缺失的已关闭周期；
不得要求用户逐个选择周期；
每个可计算周期必须找到相邻的 start_orchestration_run 和 end_orchestration_run；
每个周期必须使用两者绑定的 trade_preparation BinanceSyncRun；
每条绩效记录必须归属于 start_orchestration_run，并记录 end_orchestration_run；
不得按数据库最新账户快照猜测；
不得使用 ops_display 快照；
不得请求 Binance；
不得覆盖已经存在且输入引用一致的有效记录；
结果写入 OrchestrationRunPerformance；
返回本次扫描、补算、跳过和失败摘要。
```

### 8.2 后台扫描预览

语义接口：

```text
preview_missing_closed_period_performance(
    trace_id,
)
```

要求：

```text
只返回当前缺失周期数量、可计算周期数量、不可计算原因摘要；
不写 MySQL；
不写 AlertEvent；
不改变任何上游对象；
仍然只允许使用自动边界 trade_preparation 快照。
```

### 8.3 单周期内部计算

语义接口：

```text
calculate_one_closed_period_from_boundaries(
    start_orchestration_run_id,
    end_orchestration_run_id,
    trace_id,
)
```

要求：

```text
该接口是后台一键补算的内部步骤；
不得作为后台用户直接选择周期的 P0 入口；
必须校验两个边界 run 是否相邻且属于同一周期；
必须幂等；
不得创建重复有效记录；
不得使用人工账户刷新快照；
不得补写或修改上游交易事实。
```

## 9. 快照选择规则

PerformanceMetrics 只能使用：

```text
自动 OrchestrationRun；
自动 run 中已成功完成的 Binance Account Sync 步骤；
该步骤绑定的 trade_preparation BinanceSyncRun；
该 BinanceSyncRun 内完整保存的账户、余额和持仓快照。
```

PerformanceMetrics 禁止使用：

```text
ops_display BinanceSyncRun；
后台人工账户总览刷新；
人工诊断 run；
数据库最新两条账户快照；
非相邻边界账户快照；
非 active account domain 的账户快照；
running 或 failed 状态的 BinanceSyncRun；
过期批次作为交易事实补救来源；
Redis 缓存里的账户事实。
```

PerformanceMetrics 不能用：

```text
最新账户快照 - 上一条账户快照
```

正确方式是：

```text
根据结束边界自动 run 找到本周期结束 BinanceSyncRun；
根据 UTC 周期边界找到相邻开始自动 run；
根据开始自动 run 找到本周期开始 BinanceSyncRun；
校验两个 BinanceSyncRun 的 market_type、account_domain、symbol 和快照完整性；
用这两条明确边界快照计算周期表现。
```

## 10. 快照缺失处理

如果缺少结束边界自动账户快照，不计算该周期收益。

如果缺少开始边界自动账户快照，不计算该周期收益。

如果两个边界之间存在人工账户刷新快照，直接忽略。

快照不足时记录：

```text
calculation_status = insufficient_snapshot
```

并写入明确 `reason_code`。

PerformanceMetrics 不得用人工快照、展示快照或其他周期快照补算。

## 11. 可读取数据

PerformanceMetrics 只读取已经落库的数据。

可以读取：

```text
OrchestrationRun；
OrchestrationStepRun；
OrchestrationBusinessObjectLink；
BinanceSyncRun；
BinanceAccountSnapshot；
BinanceBalanceSnapshot；
BinancePositionSnapshot；
BinanceSymbolRuleSnapshot；
DecisionSnapshot；
OrderPlan；
CandidateOrderIntent；
RiskCheckResult；
ApprovedOrderIntent；
ExecutionPreparationResult；
PreparedOrderIntent；
OrderSubmissionAttempt；
OrderStatusSyncRecord；
FillSyncResult；
TradeFill；
OrderFillSummary；
AlertEvent；
RuntimeGuardIssue。
```

读取 `OrchestrationBusinessObjectLink` 只用于复盘聚合和审计导航，不作为交易模块的正式输入方式。

## 12. BinanceSyncRun 的作用

BinanceSyncRun 在 PerformanceMetrics 中提供周期边界账户事实。

必须使用其中的：

```text
active market_type；
active account_domain；
账户权益上下文；
余额上下文；
持仓方向；
持仓数量；
entry_price；
mark_price；
unrealized_pnl；
symbol 交易规则；
snapshot_set_hash。
```

`BinancePositionSnapshot.mark_price` 是本模块计算周期边界持仓表现的价格事实来源。

PerformanceMetrics 不主动生成 PriceSnapshot，也不反向修改 PriceSnapshot。

如果需要在复盘详情页展示本轮策略使用的 PriceSnapshot，可以通过 OrchestrationBusinessObjectLink 作为辅助上下文读取；它不是 PerformanceMetrics 计算账户边界收益的强制输入。

## 13. 主收益口径

PerformanceMetrics 的主收益口径是周期浮动收益。

它关注：

```text
周期开始时的账户持仓状态；
周期结束时的账户持仓状态；
周期内策略目标仓位；
周期内是否发生调仓；
周期内交易执行对最终持仓的影响；
持仓在价格变化下的表现。
```

它不把以下内容作为主收益口径：

```text
订单 realized_pnl；
减仓收益；
平仓收益；
手续费后净收益；
账户 available_balance 变化；
账户 wallet_balance 变化；
全账户估值变化。
```

订单已实现收益、手续费和订单净收益可以作为辅助字段保存，用于解释该周期是否发生减仓、平仓或执行成本。

周期内发生调仓时，订单成交导致的持仓本金变化不得被当作周期浮动收益。

基础口径：

```text
无调仓周期：
  周期浮动收益 = 周期结束边界持仓表现 - 周期开始边界持仓表现。

有调仓周期：
  必须先识别周期内订单成交带来的净持仓变化；
  订单新增或减少的仓位本金不计入周期浮动收益；
  周期浮动收益只表达扣除本周期净调仓影响后的持仓表现变化。
```

示例：

```text
00:00 周期开始时无持仓；
00:05 市价单买入 0.1 BTC；
04:05 周期结束时账户持仓表现为 0.2 BTC；
则 00:00-04:00 周期浮动收益为 0.1 BTC，而不是 0.2 BTC。

04:05 新周期开始时账户持仓表现为 0.2 BTC；
04:05-08:00 周期内没有调仓；
08:05 周期结束时账户持仓表现为 0.21 BTC；
则 04:00-08:00 周期浮动收益为 0.01 BTC。
```

本规则只要求 P0 正确扣除本周期净调仓造成的持仓本金变化，不要求做分钟级或秒级持仓时间加权收益归因。

## 14. 计算规则

计算必须使用 Decimal，禁止使用 float 处理金额、数量、价格和百分比。

同一个绩效记录至少在以下维度内独立计算：

```text
exchange；
market_type；
account_domain；
symbol。
```

计算输入必须来自同一市场身份：

```text
start BinanceSyncRun.market_type = end BinanceSyncRun.market_type；
start BinanceSyncRun.account_domain = end BinanceSyncRun.account_domain；
start BinancePositionSnapshot.symbol = end BinancePositionSnapshot.symbol。
```

如果身份不一致，必须 fail-closed：

```text
calculation_status = skipped
reason_code = market_identity_mismatch
```

周期浮动收益字段必须表达：

```text
从周期开始边界到周期结束边界，
该 symbol 账户持仓在 mark-to-market 口径下的表现。
```

实现阶段可以根据 USDS-M 与 COIN-M 的合约语义分别确定公式，但必须满足：

```text
USDS-M 不引入 COIN-M contract_size；
COIN-M 必须使用 contract_size 和 settlement asset 语义；
不得跨账户域强制折算为 USDT；
不得把 Binance 不同市场域字段混用；
公式版本必须可追溯；
结果必须保存 formula_version。
```

## 15. 订单和成交上下文

PerformanceMetrics 必须整理周期开始边界 run 内的交易上下文。

至少包括：

```text
目标仓位方向；
目标仓位数量；
目标仓位名义；
实际开始持仓方向；
实际开始持仓数量；
实际结束持仓方向；
实际结束持仓数量；
是否生成 OrderPlan；
如果未生成 OrderPlan，是否因为真实交易权限关闭；
是否生成 CandidateOrderIntent；
RiskCheck 是否允许；
是否生成 ApprovedOrderIntent；
是否进入 ExecutionPreparation；
是否提交订单；
订单提交结果；
订单最终状态；
是否有成交；
周期内净调仓数量；
周期内净调仓名义；
订单 realized_pnl；
订单 commission；
订单 net_realized_pnl；
周期内相关 AlertEvent；
周期内相关 RuntimeGuardIssue。
```

订单和成交上下文只用于解释周期表现，不得反向修改订单、成交或账户事实。

## 16. 无下单周期

即使某个周期没有下单，只要存在连续两个自动边界 `trade_preparation` 账户快照，也必须计算周期浮动收益。

原因：

```text
策略每个周期都会提出或维持目标仓位；
不下单也代表策略认为当前仓位无需变化；
该周期持仓表现仍然属于策略复盘的一部分。
```

不能因为没有 OrderSubmissionAttempt 或 TradeFill 就跳过计算。

## 17. 手续费处理

PerformanceMetrics 保存手续费字段，但手续费不进入策略浮动收益主口径。

手续费用于解释执行成本，例如：

```text
本周期发生了多少手续费；
调仓频率是否导致成本过高；
订单净收益与周期浮动收益为什么不同。
```

后台可以同时展示：

```text
周期浮动收益；
订单 realized_pnl；
手续费；
订单净收益。
```

但 PerformanceMetrics 不把手续费强行归因到策略目标仓位是否合理。

## 18. 资金费处理

当前不处理资金费。

PerformanceMetrics 不同步 funding fee，不读取 income 流水，不拆分资金费影响。

如需资金费归因，应由独立资金费或 income sync 模块提供事实来源后，再由复盘模块消费。

## 19. 多账户域处理

PerformanceMetrics 不自行决定 U 本位或币本位。

它根据自动边界 `trade_preparation` BinanceSyncRun 绑定的 active market_type 和 account_domain 处理数据。

规则：

```text
USDS-M 周期只处理 USDS-M 快照；
COIN-M 周期只处理 COIN-M 快照；
非 active domain 快照不参与交易收益统计；
ops_display 快照不参与交易收益统计；
COIN-M 不在本模块内强制折算为 USDT。
```

如果开始边界和结束边界账户域不同，记录 `skipped`，不得尝试合并。

## 20. 输出对象

本模块拥有：

```text
OrchestrationRunPerformance
```

该对象用于：

```text
后台周期收益图表；
编排详情页；
账户复盘详情；
离线 AIReview 导出。
```

## 21. 建议字段

`OrchestrationRunPerformance` 至少记录以下业务含义：

```text
id
start_orchestration_run_id
end_orchestration_run_id
period_start_utc
period_end_utc
exchange
market_type
symbol
account_domain
start_binance_sync_run_id
end_binance_sync_run_id
start_account_snapshot_id
end_account_snapshot_id
start_position_snapshot_id
end_position_snapshot_id
formula_version
target_position_direction
target_position_quantity
target_position_notional
actual_position_direction_start
actual_position_quantity_start
actual_position_notional_start
actual_position_direction_end
actual_position_quantity_end
actual_position_notional_end
mark_price_start
mark_price_end
unrealized_pnl_start
unrealized_pnl_end
cycle_floating_pnl
cycle_floating_pnl_pct
has_decision_snapshot
has_order_plan
has_candidate_order_intent
has_risk_check
has_approved_order_intent
has_execution_preparation
has_order_submission
has_terminal_order_status
has_fill
order_submission_status
terminal_exchange_order_status
order_realized_pnl
order_commission
order_net_realized_pnl
related_alert_count
related_runtime_guard_issue_count
calculation_status
reason_code
reason_message
input_refs_hash
result_hash
trigger_source
operator_id
trace_id
calculated_at_utc
created_at_utc
updated_at_utc
```

字段名可在实现计划中按模型命名规范细化，但需求层面必须保留这些业务含义。

## 22. 计算状态

`calculation_status` 至少支持：

```text
calculated
insufficient_snapshot
skipped
failed
```

含义：

```text
calculated：
  本周期表现已成功计算。

insufficient_snapshot：
  缺少必要的自动边界账户快照，不能计算。

skipped：
  周期不适合计算，例如非自动边界、账户域不一致或缺少必要上游归属。

failed：
  计算过程发生代码异常、合同损坏或不可预期错误。
```

## 23. 原因码

必须记录不能计算、跳过或失败的原因。

原因码至少包括：

```text
missing_start_orchestration_run
missing_end_orchestration_run
missing_start_binance_sync_run
missing_end_binance_sync_run
missing_start_account_snapshot
missing_end_account_snapshot
missing_start_position_snapshot
missing_end_position_snapshot
snapshot_not_bound_to_automatic_run
ops_display_snapshot_not_allowed
manual_diagnostic_run_not_allowed
non_adjacent_boundary_run
period_boundary_mismatch
market_identity_mismatch
missing_position_data
missing_mark_price
unsupported_account_domain
upstream_run_not_finalized
calculation_exception
```

原因码可以在实现计划中继续细化，但不得用模糊异常文本代替结构化原因。

## 24. 幂等要求

PerformanceMetrics 必须幂等。

同一个周期、同一个市场身份、同一个 symbol 重复运行，不得创建多条有效绩效记录。

唯一性至少覆盖：

```text
start_orchestration_run_id
end_orchestration_run_id
market_type
account_domain
symbol
```

重复触发时：

```text
输入引用一致 → 返回已有记录；
输入引用缺失后补齐 → 更新同一条记录；
输入引用发生冲突 → fail-closed 并写 AlertEvent；
后台一键补算重复执行 → 已有有效记录跳过，缺失记录继续补齐。
```

不得通过创建多条有效记录掩盖计算冲突。

## 25. 与编排的关系

PipelineOrchestrator 负责创建 `OrchestrationRun`、`OrchestrationStepRun` 和 `OrchestrationBusinessObjectLink`。

PerformanceMetrics 读取这些对象来定位复盘周期和关联业务对象。

PerformanceMetrics 不得：

```text
推进 OrchestrationRun；
修改 OrchestrationRun.status；
修改 OrchestrationStepRun；
补写交易步骤结果；
绕过 Connector 调用交易业务模块；
把绩效结果传回交易链路。
```

`OrchestrationRunPerformance` 可以保存开始和结束 run 引用，因为它本身就是编排复盘对象；该引用只服务复盘查询、图表展示和离线审计。

## 26. 与 Binance Account Sync 的关系

Binance Account Sync 提供自动边界账户事实。

PerformanceMetrics 只能消费：

```text
sync_purpose = trade_preparation
status = succeeded
快照集合完整
snapshot_set_hash 可验证
```

PerformanceMetrics 不得要求 Binance Account Sync 为它额外刷新账户。

如果账户同步失败或缺失，PerformanceMetrics 只能记录 `insufficient_snapshot` 或 `skipped`。

## 27. 与 PriceSnapshot 的关系

PriceSnapshot 是交易链路的价格事实层。

PerformanceMetrics 计算账户边界收益时，以自动账户快照内的持仓 mark_price 为准。

PerformanceMetrics 可以把周期内关联的 PriceSnapshot 作为复盘上下文展示，例如解释 OrderPlan、RiskCheck 或 ExecutionPreparation 当时使用的价格事实。

PerformanceMetrics 不得：

```text
生成新的 PriceSnapshot；
刷新 PriceSnapshot；
使用 PriceSnapshot 替代账户边界持仓快照；
因为 PriceSnapshot 缺失而请求 Binance。
```

## 28. 与订单、状态和成交的关系

PerformanceMetrics 读取订单链路结果，但不改变订单链路。

读取目的：

```text
解释本周期是否调仓；
解释实际持仓为什么与目标仓位不同；
展示订单提交、交易所状态、成交和手续费上下文；
为离线复盘提供证据。
```

PerformanceMetrics 不得：

```text
根据绩效结果重做 OrderPlan；
根据绩效结果触发 RiskCheck；
根据绩效结果提交订单；
根据绩效结果查询订单状态；
根据绩效结果同步成交；
根据绩效结果释放 ActiveLock。
```

## 29. 与 RuntimeGuardIssue 的关系

PerformanceMetrics 可以读取 RuntimeGuardIssue 作为周期复盘上下文。

可读取内容包括：

```text
自动编排主链路漏跑；
编排卡住；
步骤产物缺失；
订单链路长期不确定；
告警投递异常。
```

RuntimeGuard 不巡检 PerformanceMetrics 自身状态。

PerformanceMetrics 是后台一键补算功能。未补算、补算失败或 insufficient_snapshot 不属于 RuntimeGuard P0 巡检范围，由 PerformanceMetrics 后台页面和补算结果自行展示。

## 30. 与后台和离线复盘的关系

后台可以使用 `OrchestrationRunPerformance` 展示：

```text
周期收益图表；
周期目标仓位；
周期实际持仓；
订单提交；
订单状态；
成交明细；
手续费；
AlertEvent；
RuntimeGuardIssue。
```

AIReview 可以离线导出 `OrchestrationRunPerformance` 作为复盘输入。

AIReview 不得把复盘结论写回实时策略、风控或执行链路。

## 31. AlertEvent

PerformanceMetrics 至少在以下场景写 AlertEvent：

```text
performance_calculated；
performance_insufficient_snapshot；
performance_skipped；
performance_failed；
performance_input_conflict；
performance_manual_confirm_write。
```

AlertEvent 必须包含：

```text
period_start_utc；
period_end_utc；
market_type；
account_domain；
symbol；
calculation_status；
reason_code；
trace_id。
```

AlertEvent 不得包含大体积原始快照、密钥、签名、认证 header 或未脱敏外部 payload。

## 32. 数据库、Redis 与外部服务

```text
读 MySQL：是。
写 MySQL：是，保存 OrchestrationRunPerformance 和 AlertEvent。
访问 Redis：非必需；如用于短期任务防重复，只能保存短期状态。
访问 Binance：否。
调用 Binance Gateway：否。
发送 Hermes：否，只写 AlertEvent。
调用大模型：否。
涉及交易执行：否。
允许真实交易：否。
```

MySQL 是绩效记录的唯一正式事实来源。

Redis 不得保存唯一绩效结果。

## 33. 后台入口与可选异步任务

允许提供：

```text
后台一键补算 service；
后台缺失扫描预览 service；
后台复盘查询 service；
用户点击后触发的 Celery task（可选）。
```

不要求提供：

```text
Celery Beat 定时补算；
每轮编排结束自动补算；
人工选择单个周期补算入口；
management command 作为主入口。
```

后台入口和可选 task 只能：

```text
接收后台用户的一键补算请求；
生成或传递 trace_id；
记录 operator_id 和 reason；
执行权限校验；
调用 PerformanceMetrics service；
输出扫描、补算、跳过、失败的结构化摘要。
```

后台入口和可选 task 不得：

```text
直接写绩效计算细节；
直接访问 Binance；
直接读取 Redis 当作账户事实；
直接修改订单、成交、账户或编排状态；
调用大模型；
触发真实交易。
```

后台一键补算写入 `OrchestrationRunPerformance` 或 AlertEvent 时，必须记录 operator_id、reason 和 trace_id。

## 34. 异常处理

异常处理规则：

```text
缺少边界快照 → insufficient_snapshot；
非自动边界 run → skipped；
账户域不一致 → skipped；
必要持仓数据缺失 → insufficient_snapshot；
mark_price 缺失或不可解析 → insufficient_snapshot；
公式合同损坏 → failed；
数据库写入失败 → failed；
输入引用冲突 → failed；
未知异常 → failed。
```

PerformanceMetrics 失败不得：

```text
影响下一轮自动编排；
修改上游快照；
修改订单状态；
变更成交；
释放 ActiveLock；
触发下单；
触发 Binance 请求。
```

## 35. 测试要求

至少覆盖：

```text
1. 00:05 和 04:05 自动边界账户快照可计算 00:00-04:00 周期表现。
2. 04:05 账户快照可作为上一周期结束状态和下一周期开始状态。
3. 自动边界 run 必须通过 OrchestrationBusinessObjectLink 找到 trade_preparation BinanceSyncRun。
4. ops_display 快照夹在两个自动边界之间时必须忽略。
5. 人工诊断 run 的账户快照不能参与自动周期收益计算。
6. 缺少结束边界快照时状态为 insufficient_snapshot。
7. 缺少开始边界快照时状态为 insufficient_snapshot。
8. 边界 run 不相邻时不得按最新两条快照计算。
9. 无下单但有连续边界快照时也要计算周期表现。
10. 有订单 realized_pnl 时只作为辅助字段保留。
11. 手续费字段保留但不影响周期浮动收益主口径。
12. 周期内发生调仓时，成交新增或减少的仓位本金不计入周期浮动收益。
13. 无调仓周期按开始和结束边界持仓表现差额计算。
14. 有调仓周期必须扣除本周期净调仓影响后再计算持仓表现。
15. 不做分钟级或秒级持仓时间加权收益归因。
16. 同一周期重复触发不得生成重复绩效记录。
17. market_type 不一致时 skipped。
18. account_domain 不一致时 skipped。
19. symbol 缺少持仓快照时 insufficient_snapshot。
20. mark_price 缺失时 insufficient_snapshot。
21. USDS-M 不使用 COIN-M contract_size。
22. COIN-M 缺失 contract_size 时不能使用 USDS-M 公式兜底。
23. 计算失败不得修改 BinanceSyncRun、订单状态或成交记录。
24. PerformanceMetrics 不访问 Binance Gateway。
25. 后台一键补算首次运行时，可以补齐所有可计算的缺失周期。
26. 后台一键补算重复运行时，已有有效绩效记录必须跳过，只补齐剩余缺失周期，并记录 operator_id、reason 和 trace_id。
27. RuntimeGuardIssue 可以作为复盘上下文，但 RuntimeGuard 不巡检 PerformanceMetrics 自身状态。
28. AIReview 只能离线读取结果，不影响实时交易。
```

## 36. 验收标准

满足以下条件才算通过：

```text
只使用自动边界 trade_preparation 账户快照；
不使用 ops_display、人工刷新或数据库最新快照兜底；
周期边界与 UTC 4 小时窗口严格一致；
00:05 边界由 daily_boundary run 提供；
每个周期、市场身份和 symbol 只有一条有效绩效记录；
后台一键补算可以自动补齐所有缺失的已关闭可计算周期；
后台一键补算重复运行时不得重复生成已有有效记录；
周期无下单也能计算；
真实交易权限关闭导致未进入 OrderPlan 时，只要自动边界账户快照连续存在，仍然可以计算；
NO_TARGET_CHANGE / NO_TRADE、no_strategy 或策略链路提前结束的周期，只要自动边界账户快照连续存在，仍然可以计算；
调仓周期扣除成交带来的净仓位本金变化后计算周期浮动收益；
不要求做分钟级或秒级持仓时间加权归因；
订单 realized_pnl 和手续费只作为辅助字段；
资金费不在当前范围内；
USDS-M 与 COIN-M 公式语义分离；
失败不影响主交易编排；
不请求 Binance；
不生成订单；
不修改订单、成交、账户或锁；
结果可供后台、编排详情和离线 AIReview 使用；
所有时间字段使用 UTC。
```

## 37. 当前不包含的能力

```text
完整账户净值曲线；
资金费拆分；
income 流水同步；
跨账户域统一估值；
币本位强制 USDT 折算；
VaR、夏普比率、最大回撤等复杂指标；
长期组合绩效分析；
多策略归因；
多账户组合归因；
订单级平仓收益作为周期主收益；
自动生成复盘结论；
大模型参与实时交易决策；
根据绩效结果自动调整策略参数；
根据绩效结果自动暂停或恢复真实交易。
```

## 38. 最终结论

PerformanceMetrics 的最终定位是：

```text
周期浮动收益统计 + 账户绩效复盘上下文。
```

它基于相邻自动边界的 `trade_preparation` 账户快照，计算 UTC 4 小时周期内策略目标仓位对应的持仓表现。

一句话：

```text
PerformanceMetrics 复盘账户与仓位表现，不参与策略生成、订单规划、风控审批或交易执行。
```
