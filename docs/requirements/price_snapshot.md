# PriceSnapshot 需求

## 1. 模块定位

PriceSnapshot 是自动交易链路的价格事实模块。

正式自动编排只在 DecisionSnapshot 为 `TARGET_POSITION` 时调用 PriceSnapshot。自动四小时账户边界同步已在编排起始阶段完成；`NO_TARGET_CHANGE` 或 `NO_TRADE` 分支正常结束，不创建 PriceSnapshot。

每个唯一 `business_request_key` 必须通过 Binance Gateway 主动请求一次当前交易标的的 Binance `mark_price`，并将结果固化为唯一的 `PriceSnapshot`。

PriceSnapshot 同时写入：

```text
MySQL：永久事实来源，用于审计、追溯和复盘；
Redis：同一事实记录的短期缓存，用于本轮快速读取。
```

本模块不计算策略价格，不预测价格，也不记录最终成交价。

## 2. 核心原则

```text
价格类型固定为 mark_price；
正式自动编排只有 TARGET_POSITION 分支创建 PriceSnapshot；
价格必须通过 BinancePublicMarketGateway 主动获取；
每个 business_request_key 只能有一个 PriceSnapshot；
不同 business_request_key 的价格快照不得作为幂等重放结果混用；
OrderPlan 与 RiskCheck 必须使用 Connector 显式传入的同一份价格快照；
PriceSnapshot 默认有效期为 600 秒；
本次业务请求的快照过期后不得刷新、覆盖或创建第二份快照；
MySQL 是唯一持久化事实；
Redis 只用于本轮读取加速；
Redis 缺失时只能回读同一条 MySQL 记录；
不得回退到其他业务请求的价格；
不得使用 K 线收盘价或账户持仓中的 mark_price 兜底。
```

## 3. 负责事项

本模块负责：

```text
接收带不透明 business_request_key 的价格快照创建请求；
校验幂等键、市场身份和 active domain；
调用 BinancePublicMarketGateway 获取 mark_price；
校验价格、时间和 Gateway 元数据；
创建唯一 PriceSnapshot；
生成 price_snapshot_hash；
将 PriceSnapshot 持久化到 MySQL；
将同一记录的读取摘要缓存到 Redis；
向 PriceSnapshotStepAdapter 返回 price_snapshot_id；
提供按明确 price_snapshot_id 读取的 selector；
提供 TTL 和市场身份校验；
记录创建失败、缓存异常和非法消费 AlertEvent；
为复盘提供不可变价格证据。
```

## 4. 不负责事项

本模块不负责：

```text
读取 BinancePositionSnapshot.mark_price 作为正式来源；
读取 K 线 close price 作为正式来源；
连接 WebSocket；
维护持续实时价格流；
保存盘口深度；
保存 best bid / best ask；
滑点估算；
策略分析；
生成目标仓位；
计算订单数量或合约张数；
执行保证金检查；
生成订单意图；
审批风控；
提交订单；
记录实际成交价；
执行最终报单前价格对比；
为相同 business_request_key 刷新或替换 PriceSnapshot；
跨业务请求选择最新价格；
调用 Hermes；
调用大模型。
```

最终报单前的市场价格复核、允许偏离阈值以及与实际成交结果的比较，属于 ExecutionPreparation、Execution 和 FillSync 的合同。

## 5. 正式价格来源

正式来源固定为：

```text
Binance REST mark price
```

调用路径：

```text
PriceSnapshotStepAdapter
→ PriceSnapshotService
→ BinancePublicMarketGateway.get_mark_price(market_type, symbol, call_context)
→ Binance
→ PriceSnapshot
```

本模块不得自行创建 HTTP client、拼接 endpoint、执行重试或处理限频。底层请求行为统一由 Binance Gateway 负责。

测试必须使用 fake BinancePublicMarketGateway。测试 fixture 通过 fake gateway 返回，不提供绕过 Gateway 的正式手工价格写入入口。

## 6. 价格类型

当前只允许：

```text
price_type = mark_price
```

`mark_price` 必须：

```text
存在；
可无损转换为 Decimal；
大于零；
不是 NaN 或 Infinity；
符合配置允许的最大精度；
与请求的 market_type 和 symbol 一致。
```

当前不允许将以下价格写入 PriceSnapshot：

```text
last_price
index_price
close_price
best_bid
best_ask
mid_price
average_fill_price
manual_price
```

## 7. 市场身份

每条 PriceSnapshot 必须绑定：

```text
exchange = binance
market_type
account_domain
symbol
price_type = mark_price
```

当前支持：

```text
usds_m_futures
coin_m_futures
```

创建前必须满足：

```text
requested_market_type = configured_active_market_type；
requested_account_domain = configured_active_account_domain；
requested_symbol 属于当前受控交易标的；
market_type = account_domain；
Gateway 返回的市场身份与请求一致。
```

任何不一致都必须阻断，且不得尝试另一市场域。

## 8. business_request_key 唯一性

PriceSnapshotStepAdapter 为每次正式价格步骤传入唯一、不透明的 `business_request_key`。本模块不解析该 key，也不通过它查询编排数据。

数据库必须具有能够保证以下语义的唯一约束：

```text
business_request_key 唯一
```

要求：

```text
新 business_request_key 必须创建新的 PriceSnapshot；
相同 business_request_key 重复调用返回已存在的 PriceSnapshot；
相同 business_request_key 不得再次请求 Binance 生成新价格；
不同 business_request_key 不得复用同一个 PriceSnapshot 作为幂等结果；
不得修改 PriceSnapshot 的 business_request_key；
不得覆盖已经生成的价格；
不得因为价格过期创建第二条记录。
```

编排步骤与 PriceSnapshot 的关系只由 OrchestrationBusinessObjectLink 维护，不写入本业务模型。

## 9. 对外创建入口

语义接口：

```text
create_price_snapshot(
    business_request_key,
    market_type,
    account_domain,
    symbol,
    trace_id,
    trigger_source,
)
```

返回：

```text
PriceSnapshot
```

调用前必须校验：

```text
business_request_key 存在且格式合法；
市场身份完整且等于 active domain。
```

幂等重放时：

```text
business_request_key 已有 PriceSnapshot → 返回已有记录，不调用 Binance；
business_request_key 尚无 PriceSnapshot → 发起一次业务价格请求；
并发调用 → 最终只能保存一条记录，且最多一次调用结果可以发布。
```

Binance Gateway 内部针对安全读取的有限技术重试仍属于同一次业务价格请求，不构成第二条 PriceSnapshot。

## 10. PriceSnapshot 模型

至少记录：

```text
id
business_request_key
exchange
market_type
account_domain
symbol
price_type
mark_price
price_unit
source
source_operation
source_update_time_utc
requested_at_utc
received_at_utc
as_of_utc
expires_at_utc
gateway_latency_ms
gateway_attempt_count
price_snapshot_hash
raw_payload
trace_id
trigger_source
created_at_utc
```

字段语义：

```text
source = binance_rest；
source_operation = get_mark_price；
source_update_time_utc = Binance 响应提供的价格更新时间；
requested_at_utc = 系统开始本次价格获取的时间；
received_at_utc = 系统取得有效 Gateway 响应的时间；
as_of_utc = 该价格事实对应的 Binance 更新时间；
expires_at_utc = as_of_utc + 配置 TTL；
raw_payload = 完成审计所需的脱敏 Binance 业务 payload；
price_snapshot_hash = 核心字段指纹。
```

如果 Binance 响应没有可验证的价格更新时间，不得使用服务器本地时间伪造。应由 Binance Gateway 返回的可信 server time 和响应合同确定是否可以形成 PriceSnapshot；无法确认时创建失败。

## 11. 创建校验

创建 PriceSnapshot 必须校验：

```text
Gateway 调用成功；
response_received = true；
payload 结构合法；
exchange / market_type / symbol 一致；
mark_price 合法且大于零；
source_update_time_utc 存在且可按 UTC 解释；
source_update_time_utc 不明显晚于可信当前时间；
价格在创建时尚未超过 TTL；
business_request_key 尚未对应其他 PriceSnapshot。
```

校验失败时：

```text
不得创建可消费 PriceSnapshot；
不得写入 Redis 价格缓存；
adapter 返回 STOP，不进入 OrderPlan；
记录 reason_code；
写 AlertEvent。
```

## 12. TTL

默认配置：

```text
PRICE_SNAPSHOT_TTL_SECONDS = 600
```

TTL 从 `as_of_utc` 开始计算，而不是从消费者读取时间或 Redis 写入时间开始计算。

消费时：

```text
reference_time_utc <= expires_at_utc → 时间条件可用；
reference_time_utc > expires_at_utc → stale，不可继续交易链路。
```

过期后：

```text
不得延长 expires_at_utc；
不得覆盖 mark_price；
不得重新请求 Binance 更新同一记录；
不得为同一 business_request_key 创建第二条 PriceSnapshot；
不得使用其他请求的价格兜底；
OrderPlan / RiskCheck / ExecutionPreparation 必须阻断；
写明 price_snapshot_stale。
```

TTL 是部署配置，但运行时配置只能进一步缩短，不得突破部署硬上限延长。

## 13. MySQL 持久化

MySQL 是 PriceSnapshot 的唯一业务事实来源。

规则：

```text
只有通过全部校验的价格才能保存；
写入必须在数据库事务中完成；
business_request_key 与 PriceSnapshot 的唯一关系必须在数据库事务中确认；
唯一约束冲突时必须读取并返回已存在记录；
保存后核心字段不可修改；
不得删除历史价格以便重新创建；
复盘必须读取 MySQL 事实，不得依赖 Redis 历史。
```

如果 MySQL 写入失败：

```text
本次请求没有 PriceSnapshot；
不得只写 Redis；
不得进入 OrderPlan；
写 AlertEvent。
```

## 14. Redis 缓存

Redis 只缓存已经成功写入 MySQL 的同一条 PriceSnapshot。

推荐业务键：

```text
price_snapshot:{price_snapshot_id}
```

缓存内容至少包含：

```text
price_snapshot_id
market_type
account_domain
symbol
price_type
mark_price
as_of_utc
expires_at_utc
price_snapshot_hash
```

Redis TTL 不得超过 PriceSnapshot 剩余有效期。

禁止：

```text
使用不带 price_snapshot_id 的 latest_price 作为交易读取键；
把 Redis 作为唯一价格事实来源；
缓存尚未写入 MySQL 的价格；
缓存与 MySQL 不同的 mark_price；
通过刷新 Redis TTL 延长业务 TTL；
在 Redis 中覆盖其他 PriceSnapshot 的缓存；
复盘只读取 Redis。
```

## 15. 缓存写入与失败处理

顺序必须为：

```text
请求 Binance
→ 校验价格
→ 写入 MySQL
→ 提交数据库事务
→ 写入 Redis 缓存
```

Redis 写入失败时：

```text
MySQL PriceSnapshot 仍然有效；
不得回滚或删除已经提交的 MySQL 事实；
记录缓存失败日志和运行状态；
消费者回读 MySQL；
不得重新请求 Binance；
不得创建第二条 PriceSnapshot。
```

Redis 缓存不是交易是否允许的独立条件。只要 MySQL 事实有效且未过期，消费者可以继续使用。

## 16. 读取规则

正式消费者必须传入：

```text
price_snapshot_id
reference_time_utc
expected_market_type
expected_account_domain
expected_symbol
```

读取流程：

```text
1. 尝试读取 price_snapshot_id 专属 Redis key。
2. 校验 price_snapshot_id、市场身份、hash 和 expires_at_utc。
3. 缓存命中且一致时返回缓存摘要。
4. 缓存缺失、损坏或不一致时读取指定 MySQL PriceSnapshot。
5. MySQL 校验通过后可以回填同一 Redis key。
6. MySQL 缺失或校验失败时返回 unavailable / blocked。
```

不得执行：

```text
查询数据库全局 latest PriceSnapshot；
查询同 symbol 最近一条价格作为兜底；
查询其他业务请求的价格；
读取其他 price_snapshot_id；
从 BinancePositionSnapshot 补价格；
从 Kline 补价格；
消费者自己请求 Binance。
```

## 17. OrderPlan 与 RiskCheck 消费合同

PriceSnapshotStepAdapter 必须把同一个 `price_snapshot_id` 作为业务对象引用返回；Connector 将该明确 ID 传给 OrderPlan 和 RiskCheck。

两者必须校验：

```text
market_type / account_domain / symbol 一致；
price_type = mark_price；
price_snapshot_hash 可验证；
reference_time_utc 未超过 expires_at_utc。
```

OrderPlan 与 RiskCheck 不得各自选择不同价格，也不得自行重新请求 Binance。

条件不满足时：

```text
OrderPlan 必须 blocked，或 RiskCheck 必须 BLOCKED；
不得继续生成或批准订单意图；
写明确 reason_code 和 AlertEvent。
```

## 18. ExecutionPreparation 边界

ExecutionPreparation 只能读取 ApprovedOrderIntent 业务链明确引用的 PriceSnapshot，确认其身份、hash 和 TTL。

本模块不为 ExecutionPreparation 创建第二条价格快照。

如果该 PriceSnapshot 已过期：

```text
ExecutionPreparation 必须阻断；
本次业务链不得刷新价格后继续；
不得另建 execution_guard PriceSnapshot；
不得使用其他 price_snapshot_id 的价格。
```

最终报单前是否另行查询更接近执行时点的市场价格、使用何种价格、如何与 PriceSnapshot.mark_price 比较以及允许多少偏离，由 ExecutionPreparation / Execution 需求定义。该查询结果不是新的 PriceSnapshot，不得覆盖原 PriceSnapshot。

## 19. 与 Binance Account Sync 的关系

PriceSnapshot 与 BinanceSyncRun 都是 Connector 明确传给 OrderPlan 的交易前事实，但职责独立。

规则：

```text
PriceSnapshot 不得从 BinancePositionSnapshot.mark_price 派生；
BinancePositionSnapshot.mark_price 只保留为账户持仓响应中的观测字段；
PriceSnapshot 必须通过 BinancePublicMarketGateway 单独请求；
两者必须由 Connector 关联到同一次编排运行，并保持 market_type、account_domain 和 symbol 一致；
任一失败都不得由另一对象兜底；
PriceSnapshot 不修改 BinancePositionSnapshot。
```

## 20. Hash 与不可变性

`price_snapshot_hash` 至少覆盖：

```text
schema_version
business_request_key
exchange
market_type
account_domain
symbol
price_type
mark_price
price_unit
source
source_operation
source_update_time_utc
as_of_utc
expires_at_utc
```

创建后不得修改：

```text
business_request_key；
市场身份；
mark_price；
price_type；
时间字段；
source；
raw_payload；
price_snapshot_hash。
```

Redis 缓存值必须携带同一个 `price_snapshot_hash`。

## 21. 状态与原因码

PriceSnapshot 是成功取得的不可变价格事实，不承担复杂状态机。

创建 service 至少返回：

```text
succeeded
idempotent_existing
blocked
failed
```

原因码至少包括：

```text
business_request_key_missing
business_request_key_invalid
price_snapshot_already_exists
market_identity_mismatch
gateway_disabled
mark_price_request_failed
mark_price_response_invalid
mark_price_missing
mark_price_non_positive
mark_price_time_missing
mark_price_stale_at_creation
mysql_write_failed
redis_write_failed
price_snapshot_not_found
price_snapshot_stale
price_snapshot_hash_mismatch
cross_cycle_price_snapshot
```

`redis_write_failed` 不改变 MySQL PriceSnapshot 的成功事实。

## 22. AlertEvent

必须写 AlertEvent 的场景至少包括：

```text
Binance mark price 请求最终失败；
Gateway 返回非法价格或缺少可信时间；
市场身份不一致；
MySQL 写入失败；
Redis 写入持续失败或缓存内容与 MySQL 不一致；
Connector 或消费者试图混入未明确传入的 PriceSnapshot；
OrderPlan 与 RiskCheck 使用不同 price_snapshot_id；
消费者发现价格过期；
hash 校验失败。
```

成功创建 PriceSnapshot 可以只记录结构化日志，由 adapter 返回对象引用供编排层关联，不强制发送 Hermes。

AlertEvent 不得包含 API key、secret、signature 或未经脱敏的 Gateway 元数据。

## 23. 配置

所有配置必须进入 `.env.example` 并带中文注释：

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
部署配置定义 TTL 硬上限；
运行时只能缩短 TTL；
Redis 缓存关闭或故障时回读 MySQL；
Binance base URL、Gateway timeout、重试和限频不在本模块重复配置。
```

## 24. 数据库、Redis 与外部服务

```text
读写 MySQL：是，保存永久 PriceSnapshot。
访问 Redis：是，缓存本轮同一 PriceSnapshot。
访问 Binance：是，但只能通过 BinancePublicMarketGateway。
发送 Hermes：不直接发送，只写 AlertEvent。
调用大模型：否。
涉及交易执行：否。
允许真实交易：否。
```

## 25. 入口边界

允许提供：

```text
PriceSnapshot application service；
PipelineStage adapter；
受控 management command；
测试 fake gateway 入口。
```

入口层只能解析参数、传递 trace_id 和 trigger_source、调用 service 并输出摘要。

禁止提供允许人工指定任意价格并写入正式 PriceSnapshot 的生产入口。

## 26. 测试要求

自动化测试必须使用 fake BinancePublicMarketGateway，不得访问真实 Binance。

至少覆盖：

```text
1. 新 business_request_key 主动请求 Binance mark price 并创建 PriceSnapshot。
1a. NO_TARGET_CHANGE / NO_TRADE 自动分支不调用 PriceSnapshotService，也不请求 mark price。
2. 不从 BinancePositionSnapshot 读取正式价格。
3. 不从 Kline close price 读取正式价格。
4. 相同 business_request_key 重复调用返回同一 PriceSnapshot 且不再次调用 Gateway。
5. 相同 business_request_key 并发调用最终只有一条 PriceSnapshot。
6. 不同 business_request_key 创建不同 PriceSnapshot。
7. 消费者不能选择未由 Connector 明确传入的 PriceSnapshot。
8. OrderPlan 与 RiskCheck 使用同一 price_snapshot_id。
9. OrderPlan 与 RiskCheck 使用不同 ID 时阻断并告警。
10. mark_price 缺失、非法、零或负数时不创建快照。
11. 缺少可信价格时间时不创建快照。
12. 市场身份不一致时不创建快照。
13. PriceSnapshot 默认 TTL 为 600 秒。
14. TTL 从 as_of_utc 计算。
15. TTL 内可供正式消费者使用。
16. TTL 过期后当前业务链阻断且不创建第二条快照。
17. 过期后不回退历史价格。
18. MySQL 写入成功后才写 Redis。
19. MySQL 写入失败时不写 Redis。
20. Redis 写失败时 MySQL 事实保持有效。
21. Redis 缺失时回读指定 MySQL 记录。
22. Redis hash 不一致时丢弃缓存并回读 MySQL。
23. Redis TTL 不超过业务剩余 TTL。
24. 不使用不带 price_snapshot_id 的 latest price key。
25. price_snapshot_hash 稳定且核心字段变化时改变。
26. PriceSnapshot 创建后不可修改。
27. ExecutionPreparation 不能请求本模块生成第二条快照。
28. 正式生产入口不能手工指定价格。
29. Gateway 错误产生明确失败结果和脱敏 AlertEvent。
30. 测试不会初始化真实 Binance client。
```

## 27. 验收标准

满足以下条件才算通过：

```text
每个唯一 business_request_key 通过 Binance Gateway 主动获取一份 mark price；
只有 TARGET_POSITION 正式自动分支生成价格业务请求；
NO_TARGET_CHANGE / NO_TRADE 分支不生成 PriceSnapshot；
每个 business_request_key 最多一条 PriceSnapshot；
OrderPlan 与 RiskCheck 使用 Connector 显式传入的同一份价格；
未显式关联的价格不能混用；
默认 TTL 为十分钟；
过期后不刷新、不覆盖、不新增第二条；
MySQL 可以永久复盘当时使用的价格；
Redis 只缓存同一 MySQL 事实并支持本轮快速读取；
Redis 故障不会导致跨业务请求或虚假价格兜底；
不从账户持仓快照或 K 线派生正式价格；
不记录或伪造最终成交价；
所有 Binance 请求均通过 BinancePublicMarketGateway；
模块不做策略判断、订单规划、风控审批或交易执行。
```

## 28. 当前不包含的能力

```text
WebSocket PriceFeed；
持续实时价格流；
相同 business_request_key 多次 PriceSnapshot；
多价格源投票；
last price / index price；
best bid / best ask；
盘口深度；
滑点估算；
执行前价格偏离规则；
实际成交价记录；
价格异常自动暂停交易；
跨 symbol 组合定价。
```
