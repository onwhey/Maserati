# 策略系统验收清单

## 1. 文档目的

本文档用于在进入策略参数调优前，先验收当前策略分析与回测系统是否可信。

本阶段回答的问题是：

```text
系统链路是否能稳定跑完？
数据边界是否正确？
回测口径是否符合当前设计？
后台是否能看清结果？
异常是否能被发现并停止？
回测是否严格隔离于真实交易链路？
```

本阶段不回答的问题是：

```text
当前策略是否赚钱；
参数是否最优；
应该做多、做空还是震荡策略；
是否应该实盘启用；
是否应该自动优化策略；
```

只有当本文档中的系统验收通过后，才进入策略参数、策略规则和市场识别细节的调优阶段。

## 2. 验收范围

本次验收覆盖：

```text
数据采集与数据质量；
MarketSnapshot；
FeatureLayer；
AtomicSignal；
DomainSignal；
MarketRegime；
StrategyRouting；
StrategySignal；
StrategySignalQuality；
DecisionSnapshot；
StrategyBacktest；
OpsConsole 回测页面；
回测数据落库；
回测与真实交易链路隔离；
```

本次验收不覆盖：

```text
OrderPlan；
CandidateOrderIntent；
RiskCheck；
ApprovedOrderIntent；
ExecutionPreparation；
Execution；
OrderStatusSync；
FillSync；
真实下单；
真实撤单；
真实成交；
实盘收益；
策略自动优化；
```

## 3. 前置条件

验收前必须满足：

```text
MySQL 已启动；
Redis 已启动；
Django 后端可运行；
Celery worker 已启动，并且已经重启到最新代码；
OpsConsole 前端可运行；
当前环境不是 production；
真实交易部署级权限关闭；
数据库中至少存在一个 approved 且 active 的 StrategyAnalysisRelease；
数据库中存在足够的 BTCUSDT 4h / 1d 已收盘 K 线；
```

注意：

```text
如果代码刚改过模型、service 或 Celery task，必须重启 Celery worker。
否则可能出现页面显示 running，但 Celery 任务实际已经失败的状态。
```

## 4. 验收通过标准

系统验收通过，不要求收益为正。

通过标准是：

```text
链路能稳定跑完；
失败能明确失败，不假装成功；
页面能看清进度、收益摘要和周期明细；
回测口径与文档一致；
回测不进入真实交易链路；
回测不会产生订单、风控、执行或成交对象；
关键异常不会卡死在 running 状态；
```

以下情况属于失败：

```text
时间边界使用了本地时间或 PRC 时间参与业务判断；
缺少 K 线时仍继续生成后续策略对象；
StrategyAnalysisRelease 未冻结或使用不一致；
没有目标仓位时被错误解释为必须平仓；
杠杆没有影响有效仓位；
触发估算爆仓后仍继续模拟后续周期收益；
后台显示完成但没有结果摘要；
Celery 失败但 StrategyBacktestRun 长时间保持 running；
回测产生 CandidateOrderIntent、ApprovedOrderIntent、PreparedOrderIntent、OrderSubmissionAttempt 或 TradeFill；
回测触发 Binance 订单接口；
```

## 5. 数据验收

### 5.1 K 线数据完整性

检查项：

```text
4h K 线按 UTC open_time 连续；
1d K 线按 UTC open_time 连续；
系统只使用已收盘 K 线；
K 线 open_time / close_time 来自 Binance UTC 时间戳；
同一 timeframe 不存在重复业务键；
```

建议验收命令：

```powershell
.\.venv\Scripts\python.exe manage.py collect_klines --timeframe 1d --lookback-count 560
.\.venv\Scripts\python.exe manage.py collect_klines --timeframe 4h --lookback-count 620
```

通过标准：

```text
新增缺失 K 线时 inserted_count > 0；
已有数据重复采集时 skipped_existing_count 增加；
conflict_count = 0；
filtered_unclosed_count 符合当前时间边界预期；
```

### 5.2 数据质量检查

检查项：

```text
质量检查窗口使用 UTC；
expected_count 与 actual_count 合理；
缺失数据时 DataQualityResult FAIL；
数据合格时 allows_downstream = true；
```

通过标准：

```text
数据完整时允许进入 MarketSnapshot；
数据缺失时阻断，不生成 MarketSnapshot；
阻断原因可以在输出或后台中看到；
```

## 6. 策略分析链路验收

### 6.1 单周期链路

使用一个明确的 UTC 4h 边界运行单周期链路。

检查顺序：

```text
MarketSnapshot；
FeatureLayer；
AtomicSignal；
DomainSignal；
MarketRegime；
StrategyRouting；
StrategySignal；
StrategySignalQuality；
DecisionSnapshot；
```

通过标准：

```text
每一层都引用明确的直接上游对象；
每一层都使用同一个 StrategyAnalysisRelease ID 和 hash；
每一层失败时有 reason_code；
DomainSignal 只描述市场事实，不输出交易动作；
MarketRegime 只识别市场环境，不输出订单动作；
StrategyRouting 只选择策略，不执行策略算法；
StrategySignal 输出策略判断，但不直接生成目标仓位或订单；
StrategySignalQuality 只判断信号是否可下游消费；
DecisionSnapshot 只输出目标仓位语义；
```

### 6.2 多日期抽样

至少抽样以下类型的日期：

```text
趋势延续期；
趋势反弹或回调期；
高风险或异常波动期；
无策略或不适合交易期；
```

建议先使用已讨论过的日期：

```text
2026-02-07T00:00:00+00:00；
2026-02-20T00:00:00+00:00；
2026-03-15T00:00:00+00:00；
2026-04-15T00:00:00+00:00；
2026-05-15T00:00:00+00:00；
2026-06-10T00:00:00+00:00；
```

通过标准：

```text
每个日期都能输出市场事实、市场环境、路由结果和最终目标仓位语义；
如果没有策略，必须明确是 no_strategy，而不是异常；
如果高风险阻断，必须明确是风险环境或质量问题，而不是静默失败；
```

## 7. StrategyBacktest 验收

### 7.1 创建和运行

通过 OpsConsole 创建回测任务。

检查项：

```text
能选择 StrategyAnalysisRelease；
能选择 UTC 日期范围；
日期按当天 00:00:00+00:00 转换为 4h 边界；
能设置 initial_equity；
能设置 fee_rate；
能设置 leverage；
“无目标仓位时”默认是“维持上一周期仓位”；
任务创建后进入 queued；
Celery worker 启动后进入 running；
任务完成后进入 succeeded 或 blocked / failed；
```

通过标准：

```text
页面刷新不丢任务；
进度能更新；
完成后 result_summary 有值；
完成后 StrategyBacktestPeriodResult 有周期明细；
```

### 7.2 回测口径

必须逐项验收：

```text
目标仓位存在时，按该目标仓位进入下一根 4h K 线模拟；
没有目标仓位时，默认维持上一周期仓位；
目标仓位明确为 0 时，模拟平仓；
有效仓位 = 目标仓位 × leverage；
有效仓位变化 = 仓位变化 × leverage；
手续费 = abs(有效仓位变化) × 当前权益 × fee_rate；
周期收益 = 有效仓位 × 该 4h K 线涨跌幅；
多头上涨权益增加；
多头下跌权益减少；
空头下跌权益增加；
空头上涨权益减少；
```

通过标准：

```text
周期明细中 previous_position_ratio、target_position_ratio、position_change_ratio、effective_position_ratio、effective_position_change_ratio、fee、equity 都能解释；
收益、手续费和权益变化能人工抽样复算；
```

### 7.3 杠杆与估算爆仓

检查项：

```text
leverage 只影响回测有效敞口；
leverage 不修改交易所真实杠杆；
leverage 不进入 OrderPlan / RiskCheck / Execution；
多头时，如果 4h low 触及估算强平价，标记爆仓；
空头时，如果 4h high 触及估算强平价，标记爆仓；
爆仓后权益归零；
爆仓后仓位归零；
爆仓后停止后续周期收益模拟；
```

通过标准：

```text
result_summary.is_liquidated 正确；
liquidation_period_index 正确；
liquidation_analysis_close_time_utc 正确；
liquidation_price 可见；
liquidation_reason_code 可见；
爆仓不是系统失败，但会改变本次回测结果；
```

注意：

```text
当前 P0 的爆仓价是估算，不是 Binance 精确强平引擎。
验收时只确认估算逻辑自洽，不要求和交易所逐仓 / 全仓 / 维持保证金模型完全一致。
```

### 7.4 异常场景

必须验收：

```text
缺少 4h K 线时，周期 blocked；
数据质量失败时，链路 blocked；
StrategyAnalysisRelease 不存在时，创建失败；
production 环境阻断；
真实交易部署级权限打开时阻断；
Celery task 失败时，StrategyBacktestRun 不得长期保持 running；
```

通过标准：

```text
页面能看到失败或阻断；
reason_code 可见；
不会留下“进度 100% 但一直 running”的不可解释状态；
```

## 8. OpsConsole 页面验收

### 8.1 回测列表页

页面：

```text
/strategy-backtests
```

检查项：

```text
能创建回测任务；
最近回测运行列表可见；
列表展示 ID、状态、进度、版本包、本次收益、开始日期、结束日期；
本次收益正数为绿色；
本次收益负数为红色；
无结果时显示空值或横杠；
点击详情可进入单次回测详情页；
```

通过标准：

```text
完成任务能看到本次收益；
运行中任务显示进度；
失败任务显示失败状态；
```

### 8.2 回测详情页

页面：

```text
/strategy-backtests/{run_id}
```

检查项：

```text
运行状态可见；
收益摘要可见；
是否爆仓可见；
估算强平价可见；
周期调仓明细可见；
每个周期能看到策略、方向、调仓前仓位、目标仓位、有效仓位、模拟成交价、收盘价、周期收益、手续费、权益；
```

通过标准：

```text
能解释每一次模拟调仓；
能找到收益来源；
能找到亏损来源；
能找到爆仓周期；
页面刷新不丢数据；
```

## 9. 安全红线验收

回测前后必须检查以下对象数量不因回测增加：

```text
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
OrderPlanActiveLock；
```

通过标准：

```text
StrategyBacktest 只写 StrategyBacktestRun 和 StrategyBacktestPeriodResult；
由于当前 P0 复用 replay_strategy_analysis_chain，测试环境允许写入策略分析中间事实；
不得写入订单链路、风控链路、执行链路、成交链路对象；
不得调用 Binance 下单、撤单、订单查询或成交查询接口；
不得发送 Hermes；
不得调用大模型；
不得修改 StrategyAnalysisRelease 状态；
```

## 10. 建议验收命令

代码级验收：

```powershell
.\.venv\Scripts\python.exe manage.py check
.\.venv\Scripts\python.exe manage.py makemigrations --check --dry-run
.\.venv\Scripts\python.exe -m pytest tests\strategy_analysis\test_strategy_backtest.py tests\test_ops_console_stage7.py -q
```

前端验收：

```powershell
cd frontend\ops-console
npm run typecheck
npm run build
```

任务运行验收：

```powershell
.\.venv\Scripts\python.exe manage.py run_strategy_backtest `
  --start-analysis-close-time-utc 2026-06-01T00:00:00+00:00 `
  --end-analysis-close-time-utc 2026-06-30T00:00:00+00:00 `
  --strategy-analysis-release-id <release_id> `
  --strategy-analysis-release-hash <release_hash> `
  --initial-equity 10000 `
  --fee-rate 0.0004 `
  --leverage 1 `
  --no-target-policy hold `
  --business-request-prefix acceptance-backtest `
  --trace-id trace_acceptance_backtest
```

后台验收：

```text
打开 /strategy-backtests；
创建一条短区间回测；
确认列表收益显示；
进入详情页；
确认周期明细可读；
刷新页面；
确认结果仍在；
```

## 11. 验收记录模板

每次验收建议记录：

```text
验收日期：
代码提交或工作区状态：
数据库环境：
StrategyAnalysisRelease ID：
StrategyAnalysisRelease hash：
K 线覆盖范围：
回测起始 UTC：
回测结束 UTC：
初始资金：
手续费率：
杠杆：
无目标仓位口径：
是否完成：
是否阻断：
是否失败：
总收益：
最大回撤：
是否爆仓：
交易次数：
无法模拟周期数：
是否产生订单链路对象：
是否访问真实交易接口：
发现的问题：
是否允许进入策略参数调优：
```

## 12. 阶段结论规则

如果验收结果满足：

```text
系统链路稳定；
回测口径清晰；
异常可见；
页面能解释结果；
安全红线未突破；
```

则可以进入下一阶段：

```text
策略识别准确性分析；
策略参数调优；
策略路由规则调整；
StrategySignal 具体规则改进；
```

如果未满足，应先修系统问题，不进入策略参数调优。

