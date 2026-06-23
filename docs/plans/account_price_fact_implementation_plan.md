# 账户与价格事实实施计划

## 1. 文档目的

本文档用于指导阶段 3 的代码实现。

阶段 3 的目标是实现 Binance 访问边界、自动账户边界快照和交易前价格事实：

```text
BinanceGateway
→ Binance Account Sync
→ BinanceSyncRun / Account / Balance / Position / SymbolRule Snapshot

DecisionSnapshot(TARGET_POSITION)
→ PriceSnapshot
```

阶段 3 完成后，系统应能：

```text
在每个自动四小时编排起始阶段稳定生成 trade_preparation 账户边界快照；
为 PerformanceMetrics 提供连续 UTC 4 小时账户边界事实；
在 TARGET_POSITION 分支主动请求一次 Binance mark price 并固化为 PriceSnapshot；
为后续 OrderPlan、RiskCheck、ExecutionPreparation 提供明确账户事实和价格事实。
```

本文档不实现 OrderPlan、RiskCheck、ExecutionPreparation、Execution、订单状态、成交同步、PerformanceMetrics 计算、后台页面或真实下单。

---

## 2. 阶段定位

阶段 3 是账户与价格事实阶段。

一句话：

```text
先把“当前账户事实”和“本轮交易价格事实”固定下来，后续订单计划只能消费这些明确事实，不能自己请求 Binance 或读取最新兜底。
```

本阶段解决：

```text
系统如何统一访问 Binance；
自动四小时账户边界快照如何稳定产生；
账户、余额、持仓、交易规则如何成为不可变事实；
PerformanceMetrics 为什么一定有四小时账户边界基础；
PriceSnapshot 如何主动请求 mark price；
PriceSnapshot 如何 MySQL 持久化、Redis 短期缓存；
OrderPlan 后续如何获得明确的 binance_sync_run_id 和 price_snapshot_id。
```

本阶段不解决：

```text
目标仓位如何转订单；
订单是否通过风控；
执行前盘口价格偏离检查；
订单提交；
订单状态追踪；
成交同步；
周期绩效计算；
真实交易是否最终执行。
```

---

## 3. 前置条件

进入本阶段前，应已完成或具备：

```text
阶段 0 项目底座；
阶段 1 行情数据与市场事实；
阶段 2 StrategyAnalysisRelease 与 DecisionSnapshot 合同稳定；
MySQL、Redis、Celery、UTC、日志脱敏、AlertEvent、AuditRecord、trace_id、trigger_source 可用；
真实交易硬权限默认关闭；
测试默认使用 fake BinanceGateway；
策略链路可以在 TARGET_POSITION / NO_TARGET_CHANGE / NO_TRADE 之间给出明确分支语义。
```

如果阶段 2 尚未完成，本阶段可以先实现 BinanceGateway、BinanceAccountSync 和 PriceSnapshot 的独立 service、模型和测试，但不得把它们接入正式订单链路。

---

## 4. 文档依据

编码前必须阅读并遵守：

```text
AGENTS.md
README.md
docs/rules/project_invariants.md
docs/requirements/project_scope.md
docs/requirements/project_foundation.md
docs/requirements/system_capabilities.md
docs/requirements/core_contracts.md
docs/requirements/binance_gateway.md
docs/requirements/binance_account_sync.md
docs/requirements/price_snapshot.md
docs/requirements/performance_metrics.md
docs/requirements/pipeline_orchestrator.md
docs/architecture/system_architecture.md
docs/architecture/data_flow_architecture.md
docs/architecture/module_boundary_architecture.md
docs/architecture/runtime_task_architecture.md
docs/architecture/testing_and_safety_architecture.md
docs/plans/foundation_implementation_plan.md
docs/plans/market_data_implementation_plan.md
docs/plans/strategy_analysis_implementation_plan.md
docs/plans/implementation_roadmap.md
```

如果本文档与 requirements 冲突，以 requirements 为准，并停止实现向用户确认。

---

## 5. 本阶段核心口径

### 5.1 自动账户边界快照必须四小时稳定创建

自动四小时编排在创建 `OrchestrationRun` 并冻结本轮运行身份后，必须优先尝试调用 Binance Account Sync：

```text
sync_purpose = trade_preparation
```

该步骤发生在：

```text
DataCollection 之前；
FeatureLayer 之前；
DecisionSnapshot 之前；
PriceSnapshot 之前；
真实交易权限检查之前；
OrderPlan 之前。
```

它不是 OrderPlan 的附属步骤，而是自动编排的账户边界事实步骤。

只要本轮自动编排已经开始，就必须优先尝试保存该账户边界事实。后续无论发生：

```text
StrategyAnalysisRelease 缺失；
DataCollection 或 MarketSnapshot 阻断；
策略链路 no_strategy；
DecisionSnapshot = NO_TARGET_CHANGE；
DecisionSnapshot = NO_TRADE；
DecisionSnapshot = TARGET_POSITION；
真实交易权限关闭；
质量阻断；
订单链路不进入；
```

都不得影响这次已经成功生成的 `trade_preparation` 账户边界快照资格。

该快照同时服务两类用途：

```text
后续可能进入订单链路时，作为 OrderPlan / RiskCheck / ExecutionPreparation 的账户事实；
无论是否交易，都作为 PerformanceMetrics 的 UTC 4 小时周期边界账户事实。
```

### 5.2 账户同步失败不能伪造边界事实

如果自动账户边界同步失败、阻断或 unknown：

```text
不得伪造 BinanceSyncRun；
不得使用 latest succeeded 兜底；
不得使用 ops_display 兜底；
不得使用 Redis 缓存账户事实兜底；
不得为了 PerformanceMetrics 补造账户边界；
编排 adapter 必须返回 STOP / FAIL 或等价不可继续结果。
```

PerformanceMetrics 后续只能看到该周期缺少边界快照，并记录 `insufficient_snapshot` 或 `skipped`。

### 5.3 PriceSnapshot 只属于 TARGET_POSITION 分支

PriceSnapshot 只在：

```text
DecisionSnapshot.target_intent = TARGET_POSITION
```

时创建。

以下分支不创建 PriceSnapshot：

```text
NO_TARGET_CHANGE；
NO_TRADE；
no_strategy；
策略质量不放行；
DecisionSnapshot blocked / failed / unknown。
```

当前编排口径是：

```text
TARGET_POSITION
→ PriceSnapshot
→ OrderPlanStepAdapter 真实交易权限检查
→ OrderPlan
```

因此，如果已经到达 TARGET_POSITION，PriceSnapshot 可以先作为本轮价格审计事实生成；真实交易权限关闭时，后续 OrderPlan 不会被调用，也不会生成 CandidateOrderIntent 或 ActiveLock。

### 5.4 BinanceGateway 是唯一 Binance REST 边界

任何业务模块不得自行：

```text
创建 HTTP client；
拼 Binance endpoint；
执行签名；
读取 API secret；
实现超时、重试、限频或熔断；
解析 Binance 错误码；
在 USDS-M 和 COIN-M 之间自动回退。
```

本阶段需要扩展或实现 BinanceGateway 中账户与价格所需能力。

订单提交能力不在本阶段启用。

### 5.5 active market domain 与数据采集域分离

阶段 1 的行情采集固定：

```text
Binance USDS-M BTCUSDT 4h / 1d Kline
```

它不受交易 active market domain 影响。

阶段 3 的账户同步和 PriceSnapshot 服务当前新交易链路，必须使用部署配置中的：

```text
active market_type；
active account_domain；
受控交易 symbol。
```

禁止：

```text
后台热切 active market type；
根据 symbol 自动猜 market_type；
USDS-M 请求失败后自动回退 COIN-M；
COIN-M 请求失败后自动回退 USDS-M；
把一个市场域的账户事实写入另一个市场域。
```

---

## 6. 本阶段实现范围

### 6.1 BinanceGateway 账户与价格能力

本阶段在已有公共行情 Gateway 基础上，至少实现或补齐：

```text
BinancePublicMarketGateway.get_mark_price；
BinancePublicMarketGateway.get_exchange_info；
BinancePublicMarketGateway.get_symbol_exchange_info；
BinanceAccountReadGateway.get_account；
BinanceAccountReadGateway.get_balances；
BinanceAccountReadGateway.get_positions；
统一 BinanceGatewayCallContext；
统一 BinanceGatewayResult；
公共请求与签名请求隔离；
READ 凭据与 TRADE 凭据隔离；
USDS-M / COIN-M adapter 隔离；
安全读取有限技术重试；
限频、冷却、熔断；
脱敏日志和错误分类；
fake gateway。
```

本阶段不实现或不启用：

```text
BinanceOrderSubmissionGateway.submit_order；
BinanceOrderStatusGateway.query_order；
BinanceFillQueryGateway.query_order_fills。
```

如果为了接口结构预留这些能力，只能返回明确 `capability_disabled`，不得访问真实 Binance。

### 6.2 Binance Account Sync

实现 Binance Account Sync 正式 service。

负责：

```text
接收 trade_preparation 或 ops_display 同步请求；
校验 active market_type 和 account_domain；
调用 BinanceAccountReadGateway 读取账户、余额、持仓；
调用 BinancePublicMarketGateway 读取交易规则；
创建 BinanceSyncRun；
标准化账户、余额、持仓和交易规则字段；
推断 position_mode；
记录 observed_exchange_leverage；
记录 COIN-M contract_size；
生成各快照 snapshot_hash；
生成 snapshot_set_hash；
在 MySQL 原子发布完整快照批次；
提供交易 selector 和展示 selector；
写必要 AlertEvent；
为 OpsConsole 提供账户总览一键刷新后端 service。
```

### 6.3 trade_preparation 自动账户边界同步

实现：

```text
sync_for_trade_preparation(
    business_request_key,
    market_type,
    account_domain,
    symbols,
    trace_id,
    trigger_source,
)
```

要求：

```text
每个自动四小时编排起始账户边界步骤调用一次；
每个 business_request_key 最多生成一份有效 BinanceSyncRun；
相同 business_request_key 幂等返回同一批次或当前失败结果；
不同 business_request_key 不复用同一批次；
同步失败不在本轮内再创建第二份可消费批次；
成功后由 adapter 返回 binance_sync_run_id；
编排层通过 OrchestrationBusinessObjectLink 记录该业务对象；
业务表不保存或查询 OrchestrationRun ID。
```

该批次必须供：

```text
OrderPlan；
RiskCheck；
ExecutionPreparation；
PerformanceMetrics；
Review。
```

其中 PerformanceMetrics 只读取自动边界 `trade_preparation` 快照，不请求 Binance，不补刷新账户。

### 6.4 ops_display 后台账户刷新

实现：

```text
refresh_for_ops_console(
    operator_id,
    trace_id,
    trigger_source="ui_one_click",
)
```

要求：

```text
只刷新当前 active account domain；
不允许前端传入任意 market_type；
不提供一次同步全部账户域能力；
记录 operator_id、trigger_source、trace_id 和审计；
生成 sync_purpose = ops_display 的独立 BinanceSyncRun；
只供 OpsConsole 展示、运维排查和人工查看；
不得被 OrderPlan、RiskCheck 或 PerformanceMetrics 自动消费；
不得改变真实交易允许状态。
```

### 6.5 PriceSnapshot

实现 PriceSnapshot 正式 service。

负责：

```text
接收唯一 business_request_key；
校验 active market_type / account_domain / symbol；
调用 BinancePublicMarketGateway.get_mark_price；
校验 mark_price、市场身份、价格时间和 Gateway 元数据；
创建唯一 PriceSnapshot；
写入 MySQL；
写入 Redis 专属缓存；
提供按明确 price_snapshot_id 读取的 selector；
校验 TTL、hash 和市场身份；
写必要 AlertEvent。
```

PriceSnapshot 不负责：

```text
读取 BinancePositionSnapshot.mark_price；
读取 Kline close price；
连接 WebSocket；
维护持续价格流；
执行最终盘口价格复核；
记录真实成交价；
生成订单；
风控审批；
交易执行。
```

### 6.6 PriceSnapshot 与真实交易权限

PriceSnapshot 不决定是否允许真实交易。

真实交易权限检查发生在：

```text
OrderPlanStepAdapter 调用 OrderPlan service 前。
```

如果真实交易权限关闭：

```text
不调用 OrderPlan；
不生成 OrderPlan；
不生成 CandidateOrderIntent；
不取得 ActiveLock；
不进入 RiskCheck；
不提交订单。
```

但这不反向删除已经生成的 PriceSnapshot。该价格事实可以作为本轮审计和后续复盘上下文。

---

## 7. 建议代码模块

具体 Django app 名称可在编码阶段最终确定，但建议：

```text
apps/binance_gateway/
apps/binance_account_sync/
apps/price_snapshot/
```

约束：

```text
apps/binance_gateway/ 只处理 Binance 通信能力，不写业务事实；
apps/binance_account_sync/ 保存账户、余额、持仓和交易规则快照；
apps/price_snapshot/ 保存交易前 mark price 事实；
业务逻辑放在 service / domain 层；
Gateway transport 不暴露给业务模块；
management command、Celery task、API view 只能作为薄入口调用 service。
```

禁止创建：

```text
一个包含账户同步、价格快照、订单计划和执行的综合 service；
业务模块直接依赖 Gateway 内部 transport；
业务模块直接依赖 Binance endpoint path；
让 PriceSnapshot 或 AccountSync 调用 OrderPlan。
```

---

## 8. 数据库迁移范围

### 8.1 Binance Account Sync 表

本阶段建议创建：

```text
BinanceSyncRun；
BinanceAccountSnapshot；
BinanceBalanceSnapshot；
BinancePositionSnapshot；
BinanceSymbolRuleSnapshot。
```

同一组表通过字段区分：

```text
market_type；
account_domain。
```

不得为 USDS-M 与 COIN-M 创建两套重复模型。

### 8.2 PriceSnapshot 表

本阶段建议创建：

```text
PriceSnapshot。
```

必须保证：

```text
business_request_key 唯一；
每个 business_request_key 最多一条 PriceSnapshot；
不同 business_request_key 不复用同一 PriceSnapshot；
PriceSnapshot 创建后核心字段不可修改。
```

### 8.3 字段与不可变性要求

账户与价格事实对象必须至少保存：

```text
exchange；
market_type；
account_domain；
symbol；
业务用途；
业务幂等 key；
as_of_utc；
expires_at_utc；
hash；
trace_id；
trigger_source；
Gateway 调用摘要；
脱敏 raw_payload 或受控摘要；
错误码和错误摘要。
```

成功发布后不得修改：

```text
business_request_key；
sync_purpose；
market_type；
account_domain；
symbol；
核心数值；
hash；
raw_payload；
as_of_utc；
expires_at_utc。
```

Binance 事实变化必须生成新批次或新价格快照。

---

## 9. 配置项

所有新增配置必须进入 `.env.example` 并带中文注释。

### 9.1 BinanceGateway 配置

至少包括：

```text
BINANCE_GATEWAY_ENABLED
BINANCE_API_ENVIRONMENT
BINANCE_ACTIVE_MARKET_TYPE
BINANCE_USDS_M_BASE_URL
BINANCE_COIN_M_BASE_URL
BINANCE_PUBLIC_DATA_ENABLED
BINANCE_ACCOUNT_READ_ENABLED
BINANCE_ORDER_SUBMISSION_ENABLED
BINANCE_ORDER_STATUS_QUERY_ENABLED
BINANCE_FILL_QUERY_ENABLED
BINANCE_REAL_TRADING_ENABLED
BINANCE_USDS_M_READ_API_KEY
BINANCE_USDS_M_READ_API_SECRET
BINANCE_USDS_M_TRADE_API_KEY
BINANCE_USDS_M_TRADE_API_SECRET
BINANCE_COIN_M_READ_API_KEY
BINANCE_COIN_M_READ_API_SECRET
BINANCE_COIN_M_TRADE_API_KEY
BINANCE_COIN_M_TRADE_API_SECRET
BINANCE_RECV_WINDOW_MS
BINANCE_MAX_CLOCK_SKEW_MS
BINANCE_SERVER_TIME_CACHE_SECONDS
BINANCE_CONNECT_TIMEOUT_SECONDS
BINANCE_READ_TIMEOUT_SECONDS
BINANCE_ORDER_SUBMIT_READ_TIMEOUT_SECONDS
BINANCE_SAFE_READ_MAX_ATTEMPTS
BINANCE_RETRY_BASE_DELAY_MS
BINANCE_RETRY_MAX_DELAY_MS
BINANCE_MIN_REQUEST_INTERVAL_MS
BINANCE_RATE_LIMIT_SAFETY_RATIO
BINANCE_RATE_LIMIT_COOLDOWN_SECONDS
BINANCE_ORDER_SUBMIT_LOCAL_LIMIT_PER_MINUTE
BINANCE_CIRCUIT_BREAKER_FAILURE_THRESHOLD
BINANCE_CIRCUIT_BREAKER_COOLDOWN_SECONDS
```

本阶段不得因为存在交易凭据配置就启用订单提交。

### 9.2 Binance Account Sync 配置

至少包括：

```text
BINANCE_ACCOUNT_SYNC_ENABLED
BINANCE_ACCOUNT_SYNC_TTL_SECONDS
BINANCE_ACCOUNT_SYNC_SYMBOLS
BINANCE_ACCOUNT_SYNC_CONSECUTIVE_FAILURE_ALERT_THRESHOLD
BINANCE_ACCOUNT_SYNC_OPS_REFRESH_COOLDOWN_SECONDS
```

`BINANCE_ACCOUNT_SYNC_ENABLED` 是部署级硬开关：

```text
不能由 OpsConsole 修改；
不表示真实交易权限；
关闭时不得请求 Binance；
关闭时不得生成可交易 BinanceSyncRun。
```

### 9.3 PriceSnapshot 配置

至少包括：

```text
PRICE_SNAPSHOT_ENABLED
PRICE_SNAPSHOT_TTL_SECONDS=600
PRICE_SNAPSHOT_REDIS_CACHE_ENABLED
PRICE_SNAPSHOT_REDIS_KEY_PREFIX=price_snapshot
PRICE_SNAPSHOT_MAX_DECIMAL_PLACES
```

规则：

```text
默认 TTL 为 600 秒；
Redis 缓存关闭或故障时回读 MySQL；
不能用 env 改变价格来源；
不能用 env 允许手工价格进入正式 PriceSnapshot。
```

---

## 10. 实施顺序

### 10.1 扩展 BinanceGateway 公共结构

执行内容：

```text
定义 Gateway call context；
定义 Gateway result；
定义错误分类；
定义 market_type / endpoint family 映射；
定义 credential scope；
实现脱敏日志；
实现 fake gateway；
实现安全读取重试框架；
实现限频、冷却和熔断基础。
```

验收重点：

```text
业务模块无法获得 raw request；
公共请求不加载 API secret；
签名请求不泄露 secret / signature；
USDS-M 与 COIN-M 不互相回退；
测试默认不访问真实 Binance。
```

### 10.2 实现账户读取 Gateway 能力

执行内容：

```text
实现 BinanceAccountReadGateway；
实现 get_account；
实现 get_balances；
实现 get_positions；
实现 READ 凭据加载；
实现签名、recvWindow、timestamp；
实现 clock skew 处理；
实现 fake response。
```

验收重点：

```text
只有 BinanceAccountSync 可以调用；
不提交订单；
不修改杠杆；
不修改保证金模式；
不修改持仓模式；
READ 凭据不得提升为 TRADE 能力。
```

### 10.3 实现公共市场价格与交易规则能力

执行内容：

```text
实现 get_mark_price；
实现 get_exchange_info；
实现 get_symbol_exchange_info；
补齐 Gateway 对 market_type / symbol 的校验；
确保 get_mark_price 每次业务调用实际请求 Binance；
实现 fake mark price 和交易规则返回。
```

验收重点：

```text
PriceSnapshot 只能用 get_mark_price；
BinanceAccountSync 只能用交易规则操作生成 SymbolRuleSnapshot；
get_mark_price 不返回 Gateway 历史缓存价格；
交易规则不由业务模块拼 endpoint 获取。
```

### 10.4 建立 Binance Account Sync 模型与迁移

执行内容：

```text
创建 BinanceSyncRun；
创建 BinanceAccountSnapshot；
创建 BinanceBalanceSnapshot；
创建 BinancePositionSnapshot；
创建 BinanceSymbolRuleSnapshot；
添加唯一约束、外键和必要索引；
添加 hash 字段；
生成 migration。
```

验收重点：

```text
sync_purpose 区分 trade_preparation 与 ops_display；
trade_preparation 业务唯一性正确；
succeeded 批次不能缺少子快照；
running / failed 批次不可被交易 selector 消费。
```

### 10.5 实现账户字段标准化与 hash

执行内容：

```text
标准化账户字段；
标准化余额字段；
标准化持仓字段；
标准化交易规则字段；
推断 position_mode；
解析 observed_exchange_leverage；
解析 COIN-M contract_size；
生成 snapshot_hash；
生成 snapshot_set_hash。
```

验收重点：

```text
USDS-M 与 COIN-M 字段不混用；
observed_exchange_leverage 不用配置伪造；
COIN-M contract_size 缺失时交易上下文不可消费；
position_mode hedge / unknown 可保存，但交易 selector fail-closed。
```

### 10.6 实现 trade_preparation 同步 service

执行内容：

```text
实现 sync_for_trade_preparation；
校验 active market_type / account_domain；
实现 business_request_key 幂等；
调用 Gateway 读取账户、余额、持仓和交易规则；
在事务中写入完整快照集合；
完整性校验通过后发布 succeeded；
失败时发布 failed 或返回 blocked；
写 AlertEvent。
```

验收重点：

```text
每个自动四小时 run 起始阶段都能生成账户边界快照；
不同 business_request_key 不复用批次；
失败不回退历史批次；
后续不交易也保留该账户边界事实；
PerformanceMetrics 可以依赖该事实做周期边界。
```

### 10.7 实现 ops_display 后台刷新 service

执行内容：

```text
实现 refresh_for_ops_console；
实现操作人权限校验入口形状；
实现短期防重复；
写 AuditRecord；
写 ops_display BinanceSyncRun；
提供展示 selector。
```

验收重点：

```text
不允许同步全部账户域；
不允许前端传任意 market_type；
ops_display 不能被交易 selector 或 PerformanceMetrics 消费；
失败只影响本次展示刷新。
```

### 10.8 实现账户 selector

执行内容：

```text
实现 get_sync_run；
实现 get_account_snapshot；
实现 get_balance_snapshots；
实现 get_balance_snapshot_for_asset；
实现 get_position_snapshot；
实现 get_symbol_rule_snapshot；
实现 get_sync_context_bundle；
实现 get_symbol_trading_context；
实现展示 selector。
```

验收重点：

```text
交易 selector 必须接收明确 sync_run_id；
不提供 latest succeeded 交易兜底；
不返回 ops_display 作为可交易上下文；
过期、hash 失配、快照不完整、position_mode 不支持时 fail-closed。
```

### 10.9 建立 PriceSnapshot 模型与迁移

执行内容：

```text
创建 PriceSnapshot；
添加 business_request_key 唯一约束；
添加 market_type / account_domain / symbol / price_type 字段；
添加 mark_price、as_of_utc、expires_at_utc；
添加 price_snapshot_hash；
添加 Gateway 摘要和脱敏 raw_payload；
生成 migration。
```

验收重点：

```text
每个 business_request_key 最多一条 PriceSnapshot；
PriceSnapshot 创建后核心字段不可修改；
MySQL 是永久事实来源。
```

### 10.10 实现 PriceSnapshot service

执行内容：

```text
实现 create_price_snapshot；
校验 business_request_key；
校验 active market identity；
调用 get_mark_price；
校验 mark_price 和 source_update_time_utc；
计算 TTL；
写 MySQL；
提交事务后写 Redis；
实现 Redis 缓存失败处理；
写 AlertEvent。
```

验收重点：

```text
新 business_request_key 主动请求 Binance mark price；
相同 business_request_key 返回已有记录且不再请求 Binance；
不同 business_request_key 不复用价格；
过期后不刷新、不覆盖、不新增第二条；
Redis 只缓存已写入 MySQL 的同一事实。
```

### 10.11 实现 PriceSnapshot selector

执行内容：

```text
按明确 price_snapshot_id 读取 Redis；
校验 hash、market identity 和 TTL；
缓存缺失或不一致时回读指定 MySQL；
必要时回填同一 Redis key。
```

验收重点：

```text
不读取 latest price；
不读取其他 price_snapshot_id；
不从 PositionSnapshot 或 Kline 补价格；
消费者不能自己请求 Binance。
```

### 10.12 建立薄入口和 adapter 形状

本阶段可以建立：

```text
BinanceAccountSyncStepAdapter；
PriceSnapshotStepAdapter；
账户同步 management command；
价格快照 management command；
OpsConsole 后台账户刷新 service 入口。
```

入口层只能：

```text
解析参数；
生成或传递 trace_id；
设置 trigger_source；
执行权限校验；
调用 service；
输出结构化结果。
```

入口层不得实现 Gateway 调用、字段标准化、hash、快照写入或交易消费判断。

### 10.13 建立测试

测试必须覆盖：

```text
BinanceGateway；
BinanceAccountSync；
PriceSnapshot；
trade_preparation 自动账户边界；
ops_display 后台刷新；
USDS-M / COIN-M 隔离；
READ / TRADE 凭据隔离；
幂等；
并发；
TTL；
Redis 缓存；
AlertEvent 脱敏；
PerformanceMetrics 所需边界事实稳定性。
```

---

## 11. 编排边界

本阶段不实现完整 PipelineOrchestrator。

但必须为后续编排提供明确 adapter 合同。

### 11.1 BinanceAccountSyncStepAdapter

自动四小时编排起始账户边界步骤中，adapter 必须：

```text
接收 OrchestrationStepRun 生成的不透明 business_request_key；
调用 sync_for_trade_preparation；
确认 BinanceSyncRun.status = succeeded；
确认 sync_purpose = trade_preparation；
确认快照集合完整；
返回 binance_sync_run_id；
由编排层写入 OrchestrationBusinessObjectLink；
继续 DataCollection。
```

该 adapter 不得：

```text
调用 PriceSnapshot；
检查真实交易权限；
调用 OrderPlan；
生成 CandidateOrderIntent；
取得 ActiveLock。
```

### 11.2 PriceSnapshotStepAdapter

只在 DecisionSnapshot 为 TARGET_POSITION 时，adapter 才调用 PriceSnapshotService。

adapter 必须：

```text
接收明确 DecisionSnapshot 分支；
生成价格步骤 business_request_key；
调用 create_price_snapshot；
返回 price_snapshot_id；
由编排层写入 OrchestrationBusinessObjectLink；
继续到 OrderPlanStepAdapter。
```

adapter 不得：

```text
在 NO_TARGET_CHANGE / NO_TRADE 分支调用 PriceSnapshot；
读取账户；
检查真实交易权限；
调用 OrderPlan；
生成订单意图；
刷新过期 PriceSnapshot。
```

### 11.3 与 OrderPlanStepAdapter 的衔接

OrderPlanStepAdapter 在调用 OrderPlan 前，必须已经拿到：

```text
decision_snapshot_id；
binance_sync_run_id；
price_snapshot_id；
真实交易权限检查结果。
```

本阶段只提供前两个事实模块，不实现 OrderPlanStepAdapter 的完整逻辑。

---

## 12. PerformanceMetrics 边界

PerformanceMetrics 依赖本阶段的 `trade_preparation BinanceSyncRun` 作为 UTC 4 小时周期边界账户事实。

因此本阶段必须保证：

```text
自动四小时编排起始阶段稳定尝试账户同步；
同步成功的 trade_preparation BinanceSyncRun 可被 OrchestrationBusinessObjectLink 关联；
同步成功后不因后续无交易、权限关闭或策略提前结束而删除或替换；
同一边界快照可作为上一周期结束状态和下一周期开始状态；
ops_display 快照不参与 PerformanceMetrics；
PerformanceMetrics 不要求 BinanceAccountSync 为它额外刷新账户。
```

本阶段不实现 PerformanceMetrics 计算。

但是阶段 3 验收必须能证明：

```text
每个自动四小时 run 起始账户边界步骤有稳定 trade_preparation 同步入口；
该同步入口独立于 PriceSnapshot 和订单链路；
该同步入口在真实交易权限关闭时仍应先于权限检查发生；
后续 PerformanceMetrics 能通过编排关联找到 start / end 两个边界 BinanceSyncRun。
```

---

## 13. Redis 使用边界

本阶段可以使用 Redis：

```text
Gateway 限频计数；
Gateway 冷却状态；
Gateway 熔断状态；
Gateway server-time offset；
账户同步短期防重复锁；
PriceSnapshot 专属读取缓存；
Celery broker / result backend。
```

Redis 不得作为：

```text
账户事实来源；
持仓事实来源；
交易规则事实来源；
PriceSnapshot 永久事实来源；
真实交易权限最终来源；
PerformanceMetrics 边界账户事实来源。
```

Redis 故障时：

```text
不得用缓存账户事实放行交易；
不得用 latest price 兜底；
不得破坏 MySQL 唯一性；
真实订单提交相关能力必须 fail-closed。
```

---

## 14. AlertEvent 与 AuditRecord

本阶段只写 AlertEvent，不直接发送 Hermes。

### 14.1 BinanceGateway 相关

Gateway 自身主要记录技术日志和指标。

业务 AlertEvent 由调用模块根据业务结果写入。

### 14.2 Binance Account Sync 相关

必须写 AlertEvent 的典型场景：

```text
自动账户边界同步失败；
active market type / account domain 配置非法；
Gateway 或 Account Sync 硬开关关闭；
账户读取权限缺失；
认证或权限错误；
Gateway 返回 unknown；
必要响应字段缺失或非法；
快照集合写入失败；
完整性或 hash 校验失败；
交易 selector 收到无效、过期或错误目的批次；
连续同步失败达到阈值。
```

ops_display 人工刷新必须写 AuditRecord。

### 14.3 PriceSnapshot 相关

必须写 AlertEvent 的典型场景：

```text
mark price 请求失败；
价格响应非法；
缺少可信价格时间；
市场身份不一致；
MySQL 写入失败；
Redis 缓存持续失败或 hash 不一致；
消费者试图混入未明确传入的 PriceSnapshot；
价格过期；
hash 校验失败。
```

AlertEvent 和 AuditRecord 不得包含：

```text
API key；
secret；
signature；
完整认证 header；
未脱敏 Gateway payload；
不可控大 JSON。
```

---

## 15. dry-run 规则

### 15.1 Binance Account Sync dry-run

可以：

```text
校验参数；
校验 active domain；
使用 fake Gateway 预览字段标准化；
返回预计同步摘要。
```

不得：

```text
写 BinanceSyncRun；
写账户、余额、持仓或交易规则快照；
写正式 AlertEvent；
进入交易 selector。
```

生产环境不提供绕过 Gateway 的手工账户事实写入入口。

### 15.2 PriceSnapshot dry-run

可以：

```text
校验参数；
使用 fake Gateway 或受控公共 Gateway 预览 mark price；
返回预计 PriceSnapshot 摘要。
```

不得：

```text
写 PriceSnapshot；
写 Redis；
写正式 AlertEvent；
进入 OrderPlan。
```

生产环境禁止人工指定任意价格并写入正式 PriceSnapshot。

---

## 16. 本阶段不实现

阶段 3 明确不实现：

```text
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
TradeFill；
OrderFillSummary；
ActiveLock；
PerformanceMetrics 计算；
RuntimeGuard；
Notifications 投递；
OpsConsole 页面；
DeepSeekGateway；
AIReview；
WebSocket；
User Data Stream；
真实订单提交；
撤单；
修改订单；
修改杠杆；
修改保证金模式；
资金划转。
```

本阶段也不得实现：

```text
通过账户快照自动生成订单；
通过 PriceSnapshot 自动生成订单；
用 ops_display 作为交易事实；
用 latest succeeded 账户快照兜底交易；
用 latest price 兜底交易；
因为真实交易权限关闭而跳过自动账户边界同步；
因为无交易而跳过自动账户边界同步。
```

---

## 17. 外部服务边界

阶段 3 可以在非测试环境通过 BinanceGateway 访问 Binance 读取接口。

允许的真实 Binance 能力仅限：

```text
公共 mark price；
公共交易规则；
签名账户读取；
签名余额读取；
签名持仓读取。
```

禁止：

```text
订单提交；
订单状态查询；
成交查询；
撤单；
修改订单；
修改杠杆；
修改保证金模式；
资金划转；
DeepSeek 调用；
Hermes 发送。
```

自动化测试必须使用 fake BinanceGateway，不得访问真实 Binance。

---

## 18. 测试计划

### 18.1 BinanceGateway 测试

必须测试：

```text
业务模块无法获得 raw request；
公共请求不加载 API secret；
READ 与 TRADE 凭据隔离；
USDS-M 只走 fapi adapter；
COIN-M 只走 dapi adapter；
market_type 与 account_domain 不一致时不发送签名请求；
安全读取只有限技术重试；
认证、权限、参数和市场域错误不重试；
get_mark_price 每次业务调用实际请求 Binance；
日志、异常和结果不包含 secret、signature 或完整 header；
Gateway disabled 时不发送外部请求。
```

### 18.2 Binance Account Sync 测试

必须测试：

```text
每个自动四小时编排起始账户边界请求创建新的 trade_preparation BinanceSyncRun；
相同 business_request_key 重复调用返回同一批次；
不同 business_request_key 不复用批次；
同步失败不回退其他 succeeded 批次；
同步发生在 DataCollection、FeatureLayer、DecisionSnapshot 和 OrderPlan 之前；
NO_TARGET_CHANGE / NO_TRADE / no_strategy / 真实交易权限关闭不会触发第二次 trade_preparation 同步；
后续无交易也保留该批次用于 PerformanceMetrics；
账户、余额、持仓或交易规则任一失败时批次 failed；
不完整批次不能发布 succeeded；
succeeded 批次快照不可修改；
交易 selector 只能读取明确 sync_run_id；
ops_display 批次不能被交易 selector 消费；
ops_display 批次不能被 PerformanceMetrics 消费；
position_mode hedge / unknown 时交易 selector 不可消费；
observed_exchange_leverage 不伪造；
COIN-M contract_size 缺失时交易上下文不可消费；
snapshot_hash 和 snapshot_set_hash 稳定。
```

### 18.3 PriceSnapshot 测试

必须测试：

```text
TARGET_POSITION 分支创建 PriceSnapshot；
NO_TARGET_CHANGE / NO_TRADE 分支不调用 PriceSnapshotService；
新 business_request_key 主动请求 Binance mark price；
相同 business_request_key 返回同一 PriceSnapshot 且不再次调用 Gateway；
不同 business_request_key 创建不同 PriceSnapshot；
mark_price 缺失、非法、零或负数时不创建；
缺少可信价格时间时不创建；
市场身份不一致时不创建；
默认 TTL 为 600 秒；
TTL 从 as_of_utc 计算；
TTL 过期后当前业务链阻断且不创建第二条快照；
MySQL 写入成功后才写 Redis；
Redis 缺失或 hash 不一致时回读指定 MySQL；
不使用 latest price key；
不从 BinancePositionSnapshot 或 Kline 派生价格；
正式入口不能手工指定价格。
```

### 18.4 PerformanceMetrics 边界测试

本阶段不计算 PerformanceMetrics，但必须测试账户边界事实可供后续识别：

```text
自动 run 起始账户同步成功后返回 binance_sync_run_id；
adapter 输出可被 OrchestrationBusinessObjectLink 记录；
真实交易权限关闭不影响账户边界同步优先发生；
无交易周期仍有 trade_preparation 快照；
ops_display 快照不会被标记为自动边界快照；
相邻自动 run 可分别绑定 start / end BinanceSyncRun。
```

### 18.5 安全测试

必须测试：

```text
测试默认不访问真实 Binance；
不初始化真实交易提交 Gateway；
不提交订单；
不修改杠杆；
不修改保证金模式；
Redis 不可用不导致账户或价格兜底放行；
AlertEvent 和 AuditRecord 脱敏；
业务表不保存或查询 OrchestrationRun ID。
```

---

## 19. 阶段验收命令

具体命令以项目实际依赖管理工具为准。

至少需要等价执行：

```text
python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py migrate
pytest tests/binance_gateway/
pytest tests/binance_account_sync/
pytest tests/price_snapshot/
pytest
```

如果使用 `uv`：

```text
uv run python manage.py check
uv run python manage.py makemigrations --check --dry-run
uv run python manage.py migrate
uv run pytest
```

如果使用 `poetry`：

```text
poetry run python manage.py check
poetry run python manage.py makemigrations --check --dry-run
poetry run python manage.py migrate
poetry run pytest
```

阶段回报必须说明实际运行了哪些命令。

---

## 20. 阶段通过标准

阶段 3 通过必须满足：

```text
所有 Binance 账户和价格读取都通过 BinanceGateway；
业务模块不能访问 raw request、endpoint path 或签名能力；
READ 与 TRADE 权限隔离；
USDS-M 与 COIN-M 严格隔离；
每个自动四小时编排起始账户边界请求生成或幂等返回 trade_preparation BinanceSyncRun；
trade_preparation 账户快照不依赖后续是否交易；
真实交易权限关闭不影响自动账户边界快照优先尝试生成；
后续无交易、NO_TRADE、NO_TARGET_CHANGE 或 no_strategy 时，该快照仍可作为 PerformanceMetrics 边界事实；
同步失败不伪造边界快照，不回退历史批次；
ops_display 只用于后台展示，不进入交易链路和 PerformanceMetrics；
账户、余额、持仓和交易规则快照完整、不可变、可 hash 校验；
PriceSnapshot 只在 TARGET_POSITION 分支创建；
每个 business_request_key 最多一条 PriceSnapshot；
PriceSnapshot 通过 Gateway 主动请求 mark price；
PriceSnapshot MySQL 持久化，Redis 只缓存同一事实；
PriceSnapshot 过期后不刷新、不覆盖、不新增第二条；
不从账户持仓 mark_price 或 Kline 派生正式 PriceSnapshot；
本阶段不生成订单、不执行风控、不下单、不修改交易所配置；
测试默认不访问真实 Binance；
所有时间使用 UTC。
```

---

## 21. 阶段失败标准

出现以下任一情况，本阶段不得通过：

```text
业务模块自行创建 Binance HTTP client；
业务模块自行签名；
公共请求加载 API secret；
READ 凭据被当作 TRADE 能力；
USDS-M / COIN-M 请求失败后自动回退；
自动四小时账户边界同步被放到 DecisionSnapshot 或 OrderPlan 之后；
真实交易权限关闭导致跳过自动账户边界同步；
无交易周期不生成 trade_preparation 账户边界快照；
同步失败后使用 latest succeeded 兜底；
ops_display 被交易 selector 或 PerformanceMetrics 消费；
succeeded BinanceSyncRun 缺少必需子快照；
PositionSnapshot.mark_price 被当作 PriceSnapshot 正式来源；
Kline close price 被当作 PriceSnapshot 正式来源；
PriceSnapshot 使用 latest price 兜底；
PriceSnapshot 过期后刷新同一 business_request_key；
Redis 成为账户或价格唯一事实来源；
测试访问真实 Binance；
本阶段提交订单、查询订单状态、查询成交或修改交易所配置。
```

---

## 22. 交付回报要求

阶段 3 编码完成后，回报必须说明：

```text
本阶段实现了什么；
新增和修改了哪些文件；
主要调用链路是什么；
是否写库；
是否访问 Redis；
是否访问 Binance；
是否发送 Hermes；
是否调用大模型；
是否涉及交易执行；
是否涉及真实交易；
是否涉及 BinanceGateway；
是否涉及 Binance Account Sync；
是否涉及 PriceSnapshot；
是否涉及 PerformanceMetrics 边界事实；
是否涉及 OrderPlan / CandidateOrderIntent；
是否涉及 RiskCheck / ApprovedOrderIntent；
是否涉及 ExecutionPreparation / Execution；
是否写 AlertEvent；
是否写 AuditRecord；
dry-run / confirm-write 行为；
异常处理方式；
测试命令和结果；
本阶段明确不负责什么；
是否违反 project_invariants.md。
```

如测试无法运行，必须说明原因和下一步处理。

---

## 23. 下一阶段入口

阶段 3 验收通过后，下一步进入：

```text
docs/plans/trading_execution_implementation_plan.md
```

也就是订单计划、风控与执行准备阶段。

在进入下一阶段前，不应开始订单提交、订单状态查询、成交同步、通知投递、绩效计算或 AI 复盘能力。
