# StrategyBacktest 需求

## 1. 模块定位

StrategyBacktest 是策略收益回放与验证模块，用于回答：

```text
如果按某个 StrategyAnalysisRelease 在历史 4h 周期中产生的目标仓位执行，
过去一段时间的模拟收益率、回撤和交易频率大致是什么样？
```

它不是正式自动交易主链路，也不是实盘执行模块。

StrategyBacktest 的第一阶段目标是：

```text
用历史 K 线和现有策略分析链路生成目标仓位；
按固定、可解释的撮合规则模拟调仓；
输出账户权益曲线和核心收益指标；
帮助人工判断策略组合是否值得继续优化。
```

## 2. 当前阶段边界

当前阶段只实现测试环境收益回放能力。

规则：

```text
只允许在非 production 环境运行；
不进入 PriceSnapshot；
不进入 OrderPlan；
不生成 CandidateOrderIntent；
不执行 RiskCheck；
不生成 ApprovedOrderIntent；
不执行 ExecutionPreparation；
不执行 Execution；
不提交订单；
不查询订单状态；
不同步成交；
不写 TradeFill；
不影响 ActiveLock；
不发送 Hermes；
不调用大模型；
不修改 StrategyAnalysisRelease 状态；
不自动批准或启用策略版本包。
```

当前 P0 可以复用 `replay_strategy_analysis_chain` 得到历史周期的 `DecisionSnapshot` 语义。

由于 `replay_strategy_analysis_chain` 复用正式策略分析 service，当前 P0 会把回放过程中的策略分析事实写入当前测试库的正式策略分析表。该行为只允许在测试环境使用；正式环境不得运行。

OpsConsole 触发的回测必须先生成 `StrategyBacktestRun` 运行记录，用于保存请求参数、排队 / 运行 / 完成状态、错误摘要和最终 JSON 摘要。`StrategyBacktestRun` 只属于测试环境研究能力，不属于正式自动交易主链路对象。

当前 P0 使用 `StrategyBacktestRun.result_summary` 保存核心指标、策略计数、首周期摘要、末周期摘要和周期总数；每个 UTC 4h 周期的模拟调仓明细保存到 `StrategyBacktestPeriodResult`。这样既避免在单个 JSON 字段中保存完整历史周期大数组，也能让 OpsConsole 展示每次模拟调仓的价格、仓位和收益来源。测试环境中的回测运行记录和周期明细可以按需清理。

`StrategyBacktestPeriodResult` 同时保存该周期策略分析链路对象索引和摘要，用于 OpsConsole 从单个回测周期追溯查看：

```text
MarketSnapshot；
FeatureLayer / FeatureValue；
AtomicSignal / AtomicSignalValue；
DomainSignal / DomainSignalValue；
MarketRegime；
StrategyRouting；
StrategySignal；
StrategySignalQuality；
DecisionSnapshot。
```

该索引只用于测试环境回测解释和人工验收，不作为正式交易输入，不替代各模块自身业务外键。

## 3. 输入

P0 输入：

```text
StrategyAnalysisRelease；
start_analysis_close_time_utc；
end_analysis_close_time_utc；
lookback_4h_count；
lookback_1d_count；
initial_equity；
fee_rate；
leverage；
no_target_policy；
business_request_prefix；
trace_id；
trigger_source。
```

时间规则：

```text
所有时间必须是 UTC；
start / end 必须落在 UTC 4h 边界；
回测周期按 4h 正序生成；
每个分析点代表该 4h 边界刚完成一次策略分析。
```

## 4. P0 撮合规则

P0 使用保守、简单、可解释的撮合规则：

```text
每个 UTC 4h 分析边界 T 生成策略分析结果；
如果该周期产生 target_position_ratio，则从下一根 4h K 线开盘价开始持有该目标仓位；
这里的“下一根 4h K 线”open_time 即为 T；
该仓位持有到该根 4h K 线收盘；
有效仓位比例 = 目标仓位比例 × leverage；
有效仓位变化 = (目标仓位比例 - 当前仓位比例) × leverage；
周期收益 = 有效仓位比例 × 该根 4h K 线收益率；
调仓手续费 = abs(有效仓位变化) × 当前权益 × fee_rate；
position_change_notional 使用有效仓位变化 × 当前权益估算；
没有目标仓位时，默认维持当前仓位，不主动平仓；
初始仓位默认为 0。
```

`leverage` 只属于 StrategyBacktest 撮合参数，用于放大回测名义敞口；它不等于交易所真实杠杆配置，不会修改 Binance 杠杆，不会进入 OrderPlan / RiskCheck / Execution。

P0 需要模拟简化爆仓事件：

```text
当有效仓位为多头时，如果该 4h K 线最低价触及按权益和有效名义敞口估算出的强平价，则该周期标记为爆仓；
当有效仓位为空头时，如果该 4h K 线最高价触及按权益和有效名义敞口估算出的强平价，则该周期标记为爆仓；
爆仓后本次回测权益归零，仓位归零，后续周期不再继续收益模拟；
爆仓是回测结果，不是系统错误，不触发真实订单、撤单或风控动作。
```

P0 爆仓价只是保守估算，不等于 Binance 精确强平引擎。它不模拟维持保证金阶梯、风险限额、资金费率、保险基金、逐仓 / 全仓差异、交易所手续费返佣或真实强平撮合细节。

P0 不模拟：

```text
限价单成交；
滑点；
资金费率；
交易所精确维持保证金 / 风险限额强平模型；
订单簿排队；
部分成交；
撤单；
真实交易所拒单；
跨品种组合；
多 active market domain。
```

## 5. no_target_policy

当某周期没有形成目标仓位时，P0 默认采用：

```text
hold：维持上一周期仓位。
```

原因是正式主链路中 `NO_TRADE / NO_TARGET_CHANGE` 不进入订单链路，本质上不会自动生成平仓订单。

未来可增加：

```text
flat：没有目标仓位时强制空仓。
```

但 P0 默认不使用该口径，避免和正式链路行为不一致。

## 6. 输出

P0 输出 JSON 摘要：

```text
release_id；
release_hash；
start_analysis_close_time_utc；
end_analysis_close_time_utc；
period_count；
completed_count；
blocked_count；
initial_equity；
leverage；
final_equity；
total_return_pct；
max_drawdown_pct；
trade_count；
turnover_ratio；
total_fee；
benchmark_buy_hold_return_pct；
is_liquidated；
liquidation_period_index；
liquidation_analysis_close_time_utc；
liquidation_price；
liquidation_reason_code；
strategy_counts；
periods。
```

OpsConsole 后台任务额外记录：

```text
StrategyBacktestRun ID；
运行状态；
进度总周期数；
已完成周期数；
当前处理 UTC 分析边界；
最近周期状态；
最近周期原因代码；
进度更新时间；
Celery task id；
请求人；
开始运行时间；
结束运行时间；
错误摘要。
```

每个周期至少输出：

```text
analysis_close_time_utc；
status；
market_regime；
selected_strategy；
signal_direction；
previous_position_ratio；
target_position_ratio；
position_change_ratio；
position_change_notional；
position_ratio；
leverage；
effective_position_ratio；
effective_position_change_ratio；
effective_position_notional；
is_liquidated；
liquidation_price；
liquidation_reason_code；
open_price；
close_price；
period_return_pct；
fee；
equity；
drawdown_pct；
reason_code。
```

OpsConsole 后台任务完成后，每个周期明细落库为 `StrategyBacktestPeriodResult`：

```text
previous_position_ratio 表示该周期调仓前仓位；
target_position_ratio 表示该周期策略目标仓位；
position_change_ratio 表示本周期模拟调仓幅度；
position_change_notional 表示按杠杆后的有效仓位变化和调仓前权益估算的模拟调仓名义金额；
leverage 表示本次回测使用的杠杆倍数；
effective_position_ratio 表示目标仓位乘以杠杆后的回测有效敞口；
effective_position_change_ratio 表示仓位变化乘以杠杆后的回测有效变化；
effective_position_notional 表示有效仓位乘以调仓前权益估算的当前名义敞口；
is_liquidated 表示该周期是否触发 P0 估算爆仓；
liquidation_price 表示按当前权益和有效名义敞口估算的触发价；
liquidation_reason_code 表示爆仓原因；
simulated_execution_price 使用该 UTC 4h K 线 open_price；
close_price 使用该 UTC 4h K 线 close_price。
analysis_object_ids 保存该周期从 MarketSnapshot 到 DecisionSnapshot 的对象 ID；
analysis_summary 保存该周期策略分析摘要，用于后台解释本周期判断链路。
```

注意：`simulated_execution_price` 是回测撮合口径下的模拟成交价，不是真实订单价。StrategyBacktest P0 不进入 OrderPlan / Execution，因此不产生真实下单数量、真实挂单价、真实成交价或交易所订单 ID。

## 7. 与正式交易链路关系

StrategyBacktest 的结果不得作为实时交易输入。

禁止：

```text
把回测目标仓位写回 DecisionSnapshot；
把回测收益写入正式策略信号；
根据回测结果自动修改策略版本包；
根据回测结果自动批准策略；
根据回测结果自动启用策略；
根据回测结果自动暂停真实交易；
根据回测结果自动下单。
```

回测结果只能作为人工研究材料。

## 8. 与 OpsConsole 的关系

OpsConsole 提供 StrategyBacktest P0 页面。

页面支持：

```text
选择策略版本包；
选择 UTC 日期范围；
设置初始资金和手续费；
创建测试环境回测后台任务；
刷新或自动刷新任务状态；
查看后台任务处理进度；
查看收益率、最大回撤、模拟调仓次数、手续费、买入持有对照、首尾周期摘要和周期模拟调仓明细。
从某个周期明细进入周期复盘解释详情，查看该周期每个策略分析层级的产出和人类可读解释。
```

OpsConsole P0 页面不要求用户选择具体 4h 时间点。页面中的日期按 UTC 解释：

```text
2026-07-01
→ 2026-07-01T00:00:00+00:00
→ 截止到 2026-07-01 00:00 UTC 开盘的这根 4h K 线
```

当前 P0 页面保存的是运行状态和结果摘要，不把回测结果写回正式策略、风控、订单或成交对象。

页面不实现复杂权益曲线图，不做策略参数优化，不自动批准或启用策略版本包。

周期复盘解释详情页只读取已落库事实，不重新计算策略分析，不触发回测，不进入订单链路，不访问 Binance，不发送 Hermes，不调用大模型。

周期复盘解释详情页的默认视图面向人工策略复盘，而不是面向机器读取。页面必须优先展示：

```text
本周期系统结论；
市场大背景、趋势、动能、波动、结构、风险各领域为什么这样判断；
每个领域使用了哪些原子信号；
每个原子信号依赖了哪些特征值；
市场环境如何由领域事实得出；
策略路由为什么选择该策略或为什么没有策略；
策略信号、信号质量和目标仓位如何形成；
如果判断错了，应优先检查哪一层。
```

底层 FeatureValue / AtomicSignalValue / DomainSignalValue / JSON 明细可以保留为折叠排查区。默认页面不得把大段 JSON 当作主要内容。

## 9. 测试与验收

P0 至少验证：

```text
非 4h UTC 边界会被拒绝；
production 环境会被拒绝；
回测不会进入订单链路；
没有目标仓位时默认维持仓位；
仓位变化会扣手续费；
多头价格上涨时权益上升；
空头价格下跌时权益上升；
输出最大回撤；
输出 benchmark buy-and-hold 对比；
输出不会包含密钥、token 或交易所签名。
```

验收必须说明：

```text
是否真实交易关闭；
是否访问 Binance；
是否进入 OrderPlan；
是否提交订单；
是否写 TradeFill；
是否发送 Hermes；
是否调用大模型；
是否仅用于测试环境。
```
