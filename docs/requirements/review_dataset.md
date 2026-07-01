# ReviewDataset 需求

## 1. 模块定位

ReviewDataset 是复盘数据集模块。

本模块只负责把已经落库的系统事实，按 UTC 4 小时周期、编排运行和业务对象关系整理成可下载、可校验、可离线分析的数据包。

核心定位：

```text
复盘数据出口；
4 小时周期事实整理；
编排链路、策略链路、账户事实、订单事实、成交事实和异常事实的统一导出；
供人工、本地脚本或 Codex skill 离线复盘使用。
```

ReviewDataset 不是：

```text
绩效结论模块；
策略正确性判断模块；
执行质量结论模块；
系统内复盘结论模块；
后台复杂报表系统；
自动策略优化系统；
自动调参系统；
实时交易模块；
交易修复模块。
```

ReviewDataset 的输出只能作为离线复盘材料，不得进入实时交易链路。

## 2. 核心原则

```text
只读取已落库事实；
不请求 Binance；
不请求 DeepSeek；
不调用大模型；
不生成交易信号；
不生成目标仓位；
不生成订单；
不执行风控；
不提交、撤销或重试订单；
不释放 ActiveLock；
不修改历史业务事实；
不修改策略配置；
不修改真实交易运行配置；
不自动暂停或恢复交易；
所有业务时间统一使用 UTC。
```

ReviewDataset 只回答：

```text
某个 UTC 4 小时周期里，系统已经产生了哪些事实？
这些事实分别来自哪些业务模块？
这些事实之间如何通过编排 id 和业务外键追溯？
如果要离线复盘，应该下载哪批数据？
```

ReviewDataset 不回答：

```text
策略是否一定正确；
入场价是否一定合理；
某次未成交是否一定是策略错误；
未来应该如何调参；
下一轮是否应该交易；
是否应该暂停或恢复真实交易。
```

## 3. 与 Codex skill 的边界

本项目只实现 ReviewDataset API 和数据导出能力。

Codex skill 不属于本项目运行时，不运行在 Django 内部，不写入本项目 MySQL，不参与自动交易主链路。

推荐关系：

```text
交易系统 MySQL
→ ReviewDataset API / 导出文件
→ Codex skill 只读数据
→ Codex 在本地生成复盘报告文件
```

Codex skill 可以：

```text
读取 ReviewDataset API；
读取导出的 JSON / JSONL / CSV；
理解系统业务链路；
生成本地 Markdown / JSON 复盘报告；
把多次复盘结果保存在本地 review_outputs 目录。
```

Codex skill 不得：

```text
写入生产 MySQL；
写入交易业务表；
调用 Binance；
调用 DeepSeek 参与实时交易；
生成实时交易指令；
修改策略、风控、执行或真实交易配置；
释放 ActiveLock；
触发订单提交、撤单、状态补查或成交补同步。
```

## 4. 职责范围

ReviewDataset 负责：

```text
按 UTC 4 小时周期识别可导出的复盘区间；
按 OrchestrationRun 读取一轮编排的业务对象索引；
沿真实业务外键读取上下游对象；
整理行情、特征、原子信号、领域信号、市场环境、策略路由、策略信号、信号质量和目标仓位快照；
整理账户边界快照、价格快照、订单计划、风控、执行准备、订单提交、订单状态、成交和成交汇总；
整理 RuntimeGuardIssue、AlertEvent、通知投递摘要和人工操作审计摘要；
生成结构化数据集；
生成导出清单、数据范围、对象数量、schema 版本和内容 hash；
向 OpsConsole 提供受控下载入口；
向本地 Codex skill 或人工复盘提供只读 API。
```

ReviewDataset 不负责：

```text
创建 OrchestrationRun；
恢复或重跑编排；
采集行情；
生成 MarketSnapshot；
计算 FeatureLayer；
生成 AtomicSignal；
生成 DomainSignal；
生成 MarketRegime；
执行 StrategyRouting；
执行 StrategySignal；
生成 DecisionSnapshot；
执行 Binance Account Sync；
生成 PriceSnapshot；
生成 OrderPlan 或 CandidateOrderIntent；
执行 RiskCheck；
生成 ApprovedOrderIntent；
执行 ExecutionPreparation；
提交订单；
查询订单状态；
同步成交；
刷新账户；
重新计算策略；
重新计算收益结论；
调用 DeepSeek；
保存系统内大模型复盘报告；
保存 AI 建议；
修改任何上游事实对象。
```

## 5. 数据来源

ReviewDataset 只读取 MySQL 已落库事实。

允许读取的数据包括：

```text
OrchestrationRun；
OrchestrationStepRun；
OrchestrationBusinessObjectLink；
DataCollection / Kline 事实；
DataQuality 结果；
DataBackfill 结果；
MarketSnapshot；
FeatureSet / FeatureValue；
AtomicSignalSet / AtomicSignalValue；
DomainSignalSet / DomainSignalValue；
MarketRegimeSnapshot；
StrategyRouteDecision；
StrategySignal；
StrategySignalQualityResult；
DecisionSnapshot；
BinanceSyncRun；
BinanceAccountSnapshot；
BinanceBalanceSnapshot；
BinancePositionSnapshot；
BinanceTradingRuleSnapshot；
PriceSnapshot；
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
RuntimeGuardIssue；
AlertEvent；
NotificationDeliveryAttempt；
NotificationSuppression；
OpsAuditLog 或等价人工操作审计记录。
```

禁止读取的数据包括：

```text
.env；
API key；
secret；
webhook token；
完整 Authorization header；
交易所签名材料；
Redis 中的短期缓存作为复盘事实来源；
本地临时日志文件作为核心事实来源；
尚未落库的内存对象。
```

## 6. 周期语义

ReviewDataset 的主周期是已关闭 UTC 4 小时周期：

```text
00:00 - 04:00
04:00 - 08:00
08:00 - 12:00
12:00 - 16:00
16:00 - 20:00
20:00 - 00:00
```

一条周期数据集记录必须明确：

```text
period_start_utc；
period_end_utc；
subject_orchestration_run_id；
start_boundary_orchestration_run_id；
end_boundary_orchestration_run_id；
cleanup_orchestration_run_id（如存在）；
market_type；
account_domain；
symbol；
dataset_schema_version；
dataset_generated_at_utc。
```

含义：

```text
subject_orchestration_run_id = 本周期被复盘的原始策略编排；
start_boundary_orchestration_run_id = 提供周期开始账户边界事实的编排；
end_boundary_orchestration_run_id = 提供周期结束账户边界事实的编排；
cleanup_orchestration_run_id = 如存在限价单到期收尾或订单残留清理任务，记录对应清理编排。
```

业务判断不得依赖“猜测编排 id 关系”。ReviewDataset 可以保存这些 id 作为复盘索引，但具体对象关系仍必须优先通过真实业务外键追溯。

## 7. 数据集粒度

ReviewDataset P0 使用以下粒度：

```text
一条 ReviewDatasetRecord 对应一个 UTC 4 小时周期、一个 subject_orchestration_run、一个交易身份。
```

交易身份至少包括：

```text
market_type；
account_domain；
symbol。
```

如果同一周期未来支持多个交易身份，应生成多条 ReviewDatasetRecord，不得把不同交易身份混在同一条记录里。

## 8. ReviewDatasetRecord

ReviewDatasetRecord 是本模块整理出的周期复盘数据索引。

它不是交易业务事实，不得被交易模块消费。

字段语义至少包括：

```text
record_id；
period_start_utc；
period_end_utc；
subject_orchestration_run_id；
start_boundary_orchestration_run_id；
end_boundary_orchestration_run_id；
cleanup_orchestration_run_id；
market_type；
account_domain；
symbol；
dataset_schema_version；
input_refs_hash；
record_content_hash；
build_status；
reason_code；
created_at_utc；
updated_at_utc；
trace_id。
```

ReviewDatasetRecord 可以保存紧凑摘要，但不得在单个字段中保存完整历史 K 线数组、完整特征历史窗口或不可控大 JSON。

大体量明细应通过导出文件分表表达。

## 9. 数据集内容分组

ReviewDataset 至少应支持以下数据组。

### 9.1 编排组

包含：

```text
OrchestrationRun 摘要；
OrchestrationStepRun 列表；
OrchestrationBusinessObjectLink 列表；
每个步骤的开始、结束、状态、耗时、flow_action、reason_code；
缺失对象摘要。
```

目标：

```text
复盘者能够看清这一轮为什么继续、为什么停止、在哪一步产生了什么对象。
```

### 9.2 市场事实组

包含：

```text
DataCollection 摘要；
DataQuality 摘要；
DataBackfill 摘要；
MarketSnapshot 摘要；
必要的 4h / 1d K 线窗口引用或导出明细；
PriceSnapshot 摘要。
```

规则：

```text
导出 K 线明细时必须使用独立文件或独立记录行；
不得把完整 K 线窗口塞进 ReviewDatasetRecord 单字段；
必须标注 K 线 open_time / close_time UTC。
```

### 9.3 策略分析组

包含：

```text
FeatureSet / FeatureValue 摘要与明细；
AtomicSignalSet / AtomicSignalValue 摘要与明细；
DomainSignalSet / DomainSignalValue 摘要与明细；
MarketRegimeSnapshot；
StrategyRouteDecision；
StrategySignal；
StrategySignalQualityResult；
DecisionSnapshot；
StrategyAnalysisRelease 身份、版本和 hash。
```

要求：

```text
必须保留证据字段；
必须保留算法版本；
必须保留可解释摘要；
必须保留 NO_TRADE / NO_TARGET_CHANGE / TARGET_POSITION 的最终目标语义；
不得在导出阶段重新运行策略算法。
```

### 9.4 账户事实组

包含：

```text
周期开始 trade_preparation 账户快照；
周期结束 trade_preparation 账户快照；
账户余额摘要；
持仓摘要；
交易规则摘要；
mark price 或价格事实引用；
账户权益、可用余额、持仓数量、未实现盈亏等已落库字段。
```

规则：

```text
只读取自动四小时边界 trade_preparation 快照；
不使用 ops_display 快照作为复盘边界；
不请求 Binance 补齐缺失快照；
缺失边界快照时，记录缺失原因，不猜测。
```

### 9.5 订单与成交组

包含：

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
OrderPlanActiveLock 摘要。
```

规则：

```text
订单提交 unknown 必须保持 unknown；
未成交、部分成交、撤单、过期、not_found 必须按已落库事实导出；
不得把未成交直接解释为策略失败；
不得把成交失败直接解释为策略失败；
不得重新查询订单或成交。
```

### 9.6 异常、通知与人工操作组

包含：

```text
RuntimeGuardIssue；
AlertEvent；
NotificationDeliveryAttempt；
NotificationSuppression；
OpsAuditLog 或等价审计记录。
```

规则：

```text
通知失败不得改变数据集生成结果；
审计记录只作为复盘上下文；
不得通过 ReviewDataset 自动关闭 RuntimeGuardIssue。
```

## 10. 导出包结构

ReviewDatasetExport 表示一次导出任务或导出请求。

导出包建议结构：

```text
manifest.json
cycles.jsonl
orchestration_steps.jsonl
business_object_links.jsonl
market_facts.jsonl
features.jsonl
atomic_signals.jsonl
domain_signals.jsonl
market_regimes.jsonl
strategy_signals.jsonl
decisions.jsonl
account_snapshots.jsonl
orders.jsonl
fills.jsonl
alerts.jsonl
runtime_guard_issues.jsonl
audit_logs.jsonl
```

如果导出 CSV，应保持同等语义，只是文件格式变化。

manifest 至少包含：

```text
export_id；
dataset_schema_version；
range_selector；
filters；
generated_at_utc；
generated_by；
record_count；
file_list；
row_counts；
content_hash；
redaction_policy；
source_system；
time_basis = UTC。
```

## 11. API 能力

ReviewDataset 必须提供后端 service，再由 OpsConsole API 或本地只读 API 暴露。

### 11.1 预览导出范围

语义接口：

```text
preview_review_dataset(
    range_selector,
    filters,
    trace_id,
)
```

返回：

```text
可导出周期数量；
可导出 subject_orchestration_run 数量；
预计对象数量；
预计导出文件大小等级；
缺失数据摘要；
是否超过导出上限；
不会写库。
```

### 11.2 构建数据集记录

语义接口：

```text
build_review_dataset_records(
    range_selector,
    filters,
    operator_id,
    reason,
    trace_id,
)
```

要求：

```text
只处理已关闭 UTC 4 小时周期；
幂等生成 ReviewDatasetRecord；
已有记录且 input_refs_hash 未变化时跳过；
输入引用发生变化时可以生成新版本或刷新记录；
不得修改上游业务对象；
不得请求外部服务。
```

### 11.3 创建导出包

语义接口：

```text
create_review_dataset_export(
    range_selector,
    filters,
    export_format,
    operator_id,
    reason,
    trace_id,
)
```

返回：

```text
ReviewDatasetExport；
下载地址或后续下载 token；
manifest 摘要。
```

要求：

```text
export_format 只允许后端白名单；
必须校验导出范围上限；
必须脱敏；
必须记录审计；
不得导出密钥；
不得调用 DeepSeek；
不得生成复盘结论。
```

### 11.4 下载导出包

语义接口：

```text
download_review_dataset_export(
    export_id,
    operator_id,
    trace_id,
)
```

要求：

```text
必须校验权限；
必须校验导出包归属与状态；
失败时返回结构化错误；
不得现场补跑交易模块；
不得因为下载动作修改业务事实。
```

## 12. 本地复盘结果存储建议

本项目不保存 Codex skill 的复盘报告。

推荐 Codex skill 在本地保存：

```text
review_outputs/
  2026-06-28_001/
    request.json
    dataset_manifest.json
    report.md
    findings.json
```

这些本地文件不是生产系统事实，不进入交易数据库，不被交易模块读取。

如果后续需要在后台归档复盘报告，必须单独新增需求，不得复用本模块私自写入报告结论。

## 13. 权限与审计

ReviewDataset 导出属于后台受控操作。

要求：

```text
必须登录；
必须具备导出权限；
必须记录 operator_id；
必须填写或记录 reason；
必须写审计记录；
大范围导出必须二次确认；
不得匿名导出；
不得绕过 OpsConsole API 权限。
```

导出审计至少记录：

```text
operator_id；
range_selector；
filters；
export_format；
record_count；
file_count；
content_hash；
created_at_utc；
downloaded_at_utc；
trace_id。
```

## 14. 脱敏规则

ReviewDataset 禁止导出：

```text
API key；
secret；
签名；
Authorization header；
webhook secret；
数据库密码；
Redis 密码；
完整错误堆栈中的密钥片段；
完整第三方 provider request header。
```

允许导出：

```text
业务 id；
编排 id；
订单 id；
交易所订单 id；
client_order_id；
状态；
数量；
价格；
时间；
错误码；
脱敏后的错误摘要；
策略证据字段；
账户与持仓事实中复盘所需的数值。
```

如果字段是否敏感无法确定，默认不导出完整值，只导出脱敏摘要。

## 15. 幂等与版本

ReviewDataset 必须记录 schema 版本。

同一导出范围、同一过滤条件、同一输入引用集合，在上游事实未变化时，应生成相同的 content_hash。

如果上游晚到事实发生变化，例如：

```text
订单状态后来查明确；
成交后来补同步完成；
AlertEvent 后续补写；
RuntimeGuardIssue 后续关闭；
```

则新的 ReviewDatasetRecord 或导出包必须反映新的输入引用 hash，不得静默覆盖无法追溯。

## 16. 与主交易链路关系

ReviewDataset 不属于自动交易主链路必跑步骤。

主链路完成与否不依赖 ReviewDataset。

ReviewDataset 失败不得影响：

```text
下一轮编排；
真实交易权限；
OrderPlan；
RiskCheck；
ExecutionPreparation；
Execution；
OrderStatusSync；
FillSync；
ActiveLock。
```

交易模块不得读取 ReviewDataset 结果作为实时输入。

## 17. 与 OpsConsole 的关系

OpsConsole 只提供页面入口和下载入口。

OpsConsole 可以：

```text
预览可导出范围；
选择时间范围或最近 N 个周期；
选择导出格式；
创建导出任务；
下载导出包；
查看导出历史和审计摘要。
```

OpsConsole 不得：

```text
自己拼接数据库查询替代 ReviewDataset service；
直接读取 MySQL；
直接调用 Binance；
直接调用 DeepSeek；
保存系统内大模型复盘报告；
根据复盘结果修改交易系统；
把导出动作伪装成策略评估结论。
```

## 18. 与系统内大模型调用的关系

ReviewDataset 不调用大模型。

当前正式复盘路径不在交易系统内调用 DeepSeek。

如果后续需要重新引入系统内大模型复盘，必须单独新增需求，明确：

```text
调用入口；
数据范围；
成本控制；
权限；
脱敏；
报告存储；
与 ReviewDataset 的关系；
不得参与实时交易的红线。
```

## 19. 当前正式复盘口径

当前正式复盘能力统一收敛为 ReviewDataset。

账户表现、订单成交、策略证据和异常上下文都作为 ReviewDataset 的数据字段导出，由人工、本地脚本或 Codex skill 在离线环境中分析。

系统内不保存大模型复盘报告，不保存大模型发现和建议。

## 20. 测试与验收

必须覆盖：

```text
只读已落库事实，不请求 Binance；
不调用大模型；
不生成交易对象；
不修改上游对象；
不释放 ActiveLock；
不写策略、风控或真实交易配置；
按 UTC 4 小时周期正确切分；
能按 subject_orchestration_run_id 聚合一轮事实；
能沿真实业务外键追溯订单与成交；
缺失账户边界快照时返回缺失原因；
unknown 订单状态保持 unknown；
导出文件不包含密钥；
同一输入集合 content_hash 稳定；
大范围导出触发限制或二次确认；
OpsConsole 无权限用户不能下载。
```

交易相关验收说明：

```text
是否真实交易关闭：不关心，不影响导出；
是否使用 dry-run：导出预览不写库，创建导出可写 ReviewDatasetExport / 审计记录；
是否产生 CandidateOrderIntent：否；
是否产生 ApprovedOrderIntent：否；
是否产生 PreparedOrderIntent：否；
是否提交 OrderSubmissionAttempt：否；
是否写入 TradeFill：否；
是否写入或影响 BinancePositionSnapshot：否；
是否写 AlertEvent：可写导出相关审计 AlertEvent，但不得影响交易；
是否创建 NotificationDeliveryAttempt / NotificationSuppression：按 Notifications 规则处理导出类 AlertEvent；
是否发送 Hermes：默认不要求，除非后续通知需求明确。
```

## 21. 明确不负责

ReviewDataset 明确不负责：

```text
判断策略是否有效；
判断某笔交易是否应该下；
判断某个限价单没成交是否应该追单；
判断是否应该修改算法；
自动生成报告结论；
自动提交给大模型；
自动同步到外部知识库；
自动改代码；
自动改文档；
自动改配置；
自动调整真实交易状态。
```

本模块的第一目标是让复盘数据可信、完整、可下载、可追溯。
## 22. 与 StrategyReplay 的边界

ReviewDataset 和 StrategyReplay 都服务离线分析，但数据来源和职责不同。

ReviewDataset 整理的是正式系统已经落库的运行事实：

```text
正式 OrchestrationRun；
正式策略分析对象；
正式账户、价格、订单、成交、告警和审计事实。
```

StrategyReplay 生成的是后台研究和回放结果：

```text
独立 StrategyReplayRun；
独立 StrategyReplayPeriodResult；
独立 replay 摘要和导出文件。
```

规则：

```text
ReviewDataset 默认不读取 StrategyReplay 表；
ReviewDataset 不把 StrategyReplayRun 当作 subject_orchestration_run；
ReviewDataset 不把 StrategyReplay 结果当作正式策略分析事实；
StrategyReplay 不生成 ReviewDatasetRecord；
StrategyReplay 不修改 ReviewDatasetExport；
StrategyReplay 可以提供自己的导出能力，但该导出不属于 ReviewDataset；
删除 StrategyReplay 数据不得影响 ReviewDataset；
删除 ReviewDatasetExport 不得影响 StrategyReplay。
```

如果后续需要把 StrategyReplay 结果用于离线分析，应新增 StrategyReplayExport 或 BacktestExport；不得复用 ReviewDatasetExport 混合正式运行数据和研究回放数据。
