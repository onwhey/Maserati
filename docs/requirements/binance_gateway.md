# Binance Gateway 需求

## 1. 模块定位

Binance Gateway 是系统访问 Binance REST API 的唯一基础设施边界。

任何业务模块需要读取 Binance 行情、账户、订单或成交信息，或者提交 Binance 订单，都必须通过 Binance Gateway 提供的受限接口完成。

业务模块不得自行实现：

```text
HTTP 请求
URL 拼接
API 签名
时间戳和 recvWindow
API key / secret 读取
超时与连接管理
请求重试
限频处理
Binance 错误解析
敏感信息脱敏
USDS-M / COIN-M endpoint 选择
```

Binance Gateway 是通信基础能力，不是策略模块、账户事实模块、价格事实模块、订单规划模块、风控模块或交易生命周期模块。

## 2. 设计目标

本模块必须实现：

```text
所有 Binance REST 访问统一出口；
按业务能力提供最小权限接口；
USDS-M 与 COIN-M 严格隔离；
公共请求与签名请求严格隔离；
读取权限与交易权限严格隔离；
请求、响应和错误使用统一结构；
统一执行签名、超时、限频、重试和脱敏；
为业务模块返回足够的可追溯请求元数据；
测试时可完整替换为 fake gateway；
任何真实订单提交都不能因底层自动重试而重复下单。
```

## 3. 模块边界

### 3.1 负责事项

Binance Gateway 负责：

```text
选择与 market_type 对应的 endpoint family；
构造规范化 REST 请求；
为签名请求生成 timestamp、recvWindow 和 signature；
加载对应权限和市场域的凭据；
执行连接、读取超时和连接池管理；
执行安全读取请求的有限重试；
禁止订单提交请求自动重试；
执行本地限频、冷却和并发控制；
解析 Binance HTTP 状态和业务错误码；
返回原始业务 payload 和脱敏后的响应元数据；
记录技术日志和调用指标；
过滤日志与异常中的敏感字段。
```

### 3.2 不负责事项

Binance Gateway 不负责：

```text
保存 K 线；
生成 MarketSnapshot 或 PriceSnapshot；
保存账户、余额、持仓或交易规则快照；
决定 active market domain；
生成 OrderPlan 或订单意图；
执行 RiskCheck；
生成 PreparedOrderIntent；
决定是否应该下单；
生成 client_order_id；
修改订单参数；
解释订单生命周期；
保存 OrderSubmissionAttempt；
保存订单状态或成交记录；
更新持仓；
释放 OrderPlanActiveLock；
写业务模块的成功或失败状态；
代替业务模块写 AlertEvent；
调用 Hermes；
调用大模型。
```

Gateway 返回技术事实，业务含义和数据库写入由调用方负责。

## 4. 内部结构

Binance Gateway 由两层组成：

```text
受限能力接口
→ BinanceTransport
```

`BinanceTransport` 是模块内部实现，不得作为公共 service 暴露给业务模块。

禁止提供以下公共能力：

```text
request(method, path, params)
signed_request(method, path, params)
call_any_endpoint(...)
raw_client
session
```

业务模块只能调用本文档定义的具体操作。

## 5. 受限接口总览

当前系统提供六类受限接口。

| 接口 | 权限性质 | 允许调用方 | 支持能力 |
|---|---|---|---|
| BinancePublicMarketGateway | 公共只读 | DataCollection、DataBackfill、BinanceAccountSync、PriceSnapshot、ExecutionPreparation | K 线、标记价格、最优买卖盘、交易规则、服务器时间 |
| BinanceAccountReadGateway | 签名只读 | BinanceAccountSync | 账户、余额、持仓 |
| BinanceOrderSubmissionGateway | 签名交易 | Execution | 提交一笔已经冻结的订单请求 |
| BinanceOrderCancelGateway | 签名交易 | OrderCycleCloseout | 撤销一笔已经提交且仍未终态的限价订单 |
| BinanceOrderStatusGateway | 签名只读 | OrderStatusSync | 查询一笔订单状态 |
| BinanceFillQueryGateway | 签名只读 | FillSync | 查询一笔订单的成交明细 |

接口权限按调用方和操作双重限制。获得某个 Gateway 实例，不代表获得其他接口能力。

## 6. BinancePublicMarketGateway

### 6.1 定位

公共市场接口只访问不需要账户签名的 Binance 市场数据和交易规则接口。

### 6.2 允许操作

必须提供以下语义操作：

```text
get_server_time(market_type, call_context)
get_klines(market_type, symbol, interval, start_time_utc, end_time_utc, limit, call_context)
get_mark_price(market_type, symbol, call_context)
get_book_ticker(market_type, symbol, call_context)
get_exchange_info(market_type, call_context)
get_symbol_exchange_info(market_type, symbol, call_context)
```

实际 Python 方法名可在开发计划中确定，但不得改变操作语义。

### 6.3 使用边界

```text
DataCollection / DataBackfill 只能使用 server time 和 K 线操作。
PriceSnapshot 只能使用 server time 和标记价格操作。
BinanceAccountSync 可以使用交易规则操作生成 SymbolRuleSnapshot。
ExecutionPreparation 只能使用最优买卖盘操作执行报单前 price guard。
```

公共市场接口不得读取账户数据，不得查询用户订单和成交，不得提交订单。

`get_mark_price` 和 `get_book_ticker` 每次业务调用都必须实际请求 Binance，不得返回 Gateway 历史缓存价格。Gateway 内部针对允许技术异常执行的有限重试仍属于同一次业务调用，不构成第二次业务价格请求。

`get_book_ticker` 必须返回目标 symbol 当前响应中的：

```text
best_bid_price
best_bid_quantity
best_ask_price
best_ask_quantity
```

它必须发起本次调用对应的实际 Binance 请求，不得返回业务层历史缓存价格。Gateway 只负责返回盘口事实，不负责按订单方向选价、计算偏差或决定是否允许交易。

## 7. BinanceAccountReadGateway

### 7.1 定位

账户只读接口为 BinanceAccountSync 提供当前 active market domain 的账户事实。

### 7.2 允许操作

必须提供以下语义操作：

```text
get_account(market_type, call_context)
get_balances(market_type, call_context)
get_positions(market_type, call_context, symbols=None)
```

如果 Binance 某个市场域在单一账户响应中已经包含余额或持仓信息，Gateway 仍应返回稳定的操作结果结构，不得把 endpoint 差异泄漏为业务层分支。

### 7.3 使用边界

只有 BinanceAccountSync 可以调用账户只读接口。

账户只读接口不得：

```text
修改杠杆；
修改保证金模式；
修改持仓模式；
执行资金划转；
提交或撤销订单。
```

## 8. BinanceOrderSubmissionGateway

### 8.1 定位

订单提交接口是 Binance Gateway 中唯一具有交易写权限的接口。

它只负责将 Execution 已校验的冻结参数提交给 Binance。

### 8.2 唯一调用方

只有 Execution 可以调用订单提交接口。

以下模块禁止获得或调用该接口：

```text
StrategySignal
DecisionSnapshot
BinanceAccountSync
PriceSnapshot
OrderPlan
RiskCheck
ExecutionPreparation
OrderStatusSync
FillSync
PipelineOrchestrator
RuntimeGuard
OpsConsole
Notifications
```

PipelineOrchestrator 和 OpsConsole 只能调用 Execution 的受控 application service，不能直接调用 Gateway。

### 8.3 允许操作

当前只提供：

```text
submit_order(market_type, frozen_order_request, call_context)
```

`frozen_order_request` 必须来自有效的 PreparedOrderIntent，不得由 Gateway 临时补充或修改业务参数。

Gateway 必须通过类型明确的订单请求结构或等价字段白名单进行序列化。当前订单提交只支持 `MARKET` 与 `LIMIT`。

MARKET 订单只允许向 Binance 发送：

```text
symbol
side
type = MARKET
quantity
positionSide = BOTH，或按 One-Way Mode 固定协议省略
reduceOnly
newClientOrderId
```

`market_type` 和调用上下文用于内部路由与校验，不作为调用方可注入的任意 Binance 参数透传。

LIMIT 订单只允许向 Binance 发送：

```text
symbol
side
type = LIMIT
quantity
price
timeInForce
goodTillDate 或 Binance 对应到期字段（仅当上游 PreparedOrderIntent 已冻结且当前 market_type adapter 明确支持）
positionSide = BOTH，或按 One-Way Mode 固定协议省略
reduceOnly
newClientOrderId
```

LIMIT 提交中的 `price`、`timeInForce` 和到期字段必须完全来自 `PreparedOrderIntent` 冻结结果。Gateway 不得自行计算限价、延长到期时间、替换 timeInForce 或把 LIMIT 改成 MARKET。

Gateway 必须拒绝未知字段，并明确禁止发送：

```text
stopPrice
leverage
marginType
positionMode
任意未列入白名单的 Binance 参数
```

Gateway 只做请求结构验证和序列化，不补充、修改、缩小、拆分或重新设计订单。字段缺失、值非法或出现额外字段时，必须在请求发送前返回 `request_validation_failed`。

当前不提供：

```text
replace_order
batch_order
modify_order
change_leverage
change_margin_type
change_position_mode
```

撤销既有限价单不属于 `BinanceOrderSubmissionGateway`。如需撤销本周期到期或残留的限价单，必须通过独立的 `BinanceOrderCancelGateway` 完成。

### 8.5 BinanceOrderCancelGateway

`BinanceOrderCancelGateway` 是独立的签名交易接口，只允许 `OrderCycleCloseout` 调用。

它只提供：

```text
cancel_order(market_type, frozen_cancel_request, call_context)
```

`frozen_cancel_request` 必须来自已经落库的订单链路事实，至少包含：

```text
symbol
client_order_id 或 exchange_order_id
market_type
account_domain
order_submission_attempt_id
prepared_order_intent_id
cancel_reason_code
```

Gateway 只负责把已冻结撤单请求序列化并发送给 Binance，不负责决定是否应该撤单、是否应该解锁、是否应该重新下单、是否应该追单。

撤单请求不得携带：

```text
quantity
price
side
newClientOrderId
leverage
marginType
positionMode
任意未列入撤单白名单的 Binance 参数
```

撤单操作不属于订单提交重试。撤单只能针对已经提交过、身份明确、仍未终态的 LIMIT 订单；不得用于重新提交订单、改单、追单或绕过 ActiveLock。

撤单结果只表示 Binance 对撤销请求的响应。订单最终状态仍必须由 `OrderStatusSync` 查询并落库，成交事实仍必须由 `FillSync` 查询并收尾。

撤单请求属于交易写操作，但它处理的是既有订单风险收尾。关闭新的真实交易运行开关不得阻止已提交订单的受控撤单收尾；如果当前部署缺少撤单所需的交易凭据或市场权限，Gateway 必须在请求前返回 `permission_denied` 或 `configuration_error`，由 `OrderCycleCloseout` 保持锁并写 AlertEvent。

### 8.4 禁止自动重试

订单提交操作不得进行底层自动重试。

该禁令覆盖全部调用层级：

```text
BinanceOrderSubmissionGateway 不重试；
BinanceTransport 不重试；
Execution 业务 service 不重试；
Celery task 不重试；
PipelineOrchestrator 不重试；
management command、OpsConsole 和人工重放不得再次提交同一 PreparedOrderIntent。
```

无论请求在发送前失败、发送后超时、收到明确拒绝、触发限频、返回 5xx 或结果无法判断，都不得对同一 `PreparedOrderIntent` 再次调用 `submit_order`。

如果明确 `request_sent = false`，本次 PreparedOrderIntent 仍然终结，不得复用。后续只能在 ActiveLock 安全释放后，由新的编排运行通过完整业务链路生成新订单。

如果 `request_sent = true` 或无法判断是否发送，结果必须为 `unknown`，保持 ActiveLock 阻断，并通过 `BinanceOrderStatusGateway` 使用原 `client_order_id` 查询。

发生以下情况时，Gateway 必须返回不确定结果元数据，由 Execution 映射为 `OrderSubmissionAttempt.unknown`：

```text
请求可能已经发送后的 read timeout；
连接在写入过程中中断；
服务端结果无法确认；
响应结构损坏但不能证明请求未被接受。
```

只有在 Gateway 能确定请求尚未离开本地进程时，才可以返回明确的 `not_sent` 技术结果；Execution 仍不得对同一 `PreparedOrderIntent` 再次调用提交接口，Gateway 也不得自行重试。

## 9. BinanceOrderStatusGateway

### 9.1 定位

订单状态接口只查询一条既有提交尝试对应的 Binance 订单状态。

### 9.2 允许操作

```text
query_order(
    market_type,
    symbol,
    call_context,
    client_order_id=None,
    exchange_order_id=None,
)
```

查询编号优先级和业务合法性由 OrderStatusSync 决定。Gateway 只负责把已选择的编号映射为对应 Binance 参数。

对于 `OrderSubmissionAttempt.status = unknown`，OrderStatusSync 必须能够使用提交前已经冻结的原 `client_order_id` 查询；Gateway 不要求调用方必须先获得 `exchange_order_id`。

Gateway 必须保留 Binance 对“订单明确未找到”的原始业务错误语义，但不得自行把它解释为提交失败、允许重下单或允许解锁。

### 9.3 使用边界

只有 OrderStatusSync 可以调用订单状态接口。

查询成功只表示取得 Binance 订单状态。Gateway 不解释是否应该解锁、补单、撤单或更新持仓。

订单状态查询属于安全读取，可以按 Gateway 读取重试合同执行有限技术重试。业务层的 2 秒轮询属于独立逻辑轮次，两类次数必须分别记录。

## 10. BinanceFillQueryGateway

### 10.1 定位

成交查询接口只查询一条既有订单对应的 Binance 逐笔成交事实。

### 10.2 允许操作

```text
query_order_fills(
    market_type,
    symbol,
    exchange_order_id,
    call_context,
    page_cursor=None,
    page_size=None,
)
```

如果某个市场域支持可靠地按其他唯一编号查询，必须在开发计划中明确映射和测试，不得由调用方传入任意 endpoint 参数。

Gateway 必须返回分页语义：

```text
fills
page_cursor
next_page_cursor
pagination_complete
```

Gateway 负责把统一 page cursor 映射为对应市场域接口支持的分页参数，但不负责判断订单成交是否完整、是否可以生成 synced_empty 或是否可以释放 ActiveLock。

### 10.3 使用边界

只有 FillSync 可以调用成交查询接口。

Gateway 不进行成交去重、累计、汇总、盈亏计算或持仓更新。

## 11. 市场域与 endpoint family

当前支持：

```text
usds_m_futures
coin_m_futures
```

映射规则：

```text
usds_m_futures → fapi adapter
coin_m_futures → dapi adapter
```

每次调用必须显式传入 `market_type`。Gateway 不得根据 symbol、资产名称或响应内容猜测市场域。

Gateway 必须根据业务用途采用以下三种市场校验规则。

### 11.1 固定行情采集市场

DataCollection 和 DataBackfill 固定请求 Binance USDS-M BTCUSDT 行情，不受当前交易 active market domain 影响。

Gateway 必须校验：

```text
market_type = usds_m_futures；
symbol = BTCUSDT；
调用方只能使用 server time 和 Kline 操作。
```

### 11.2 新交易链路市场

BinanceAccountSync、PriceSnapshot、ExecutionPreparation 和 Execution 为当前新交易链路服务时，必须使用部署配置确定的 active market_type 和 account_domain。

Gateway 必须校验调用上下文、冻结业务对象和所选 adapter 一致，但不得自行切换交易市场。

### 11.3 既有订单追踪市场

OrderCycleCloseout、OrderStatusSync 和 FillSync 必须使用原 OrderSubmissionAttempt 及其上游订单链已经冻结的 market_type、account_domain 和 symbol，不得用当前部署 active market domain 覆盖历史订单身份。

如果当前部署具备原订单市场对应的只读凭据和查询能力，Gateway 必须按原订单 market_type 选择查询 adapter。该查询只用于既有订单收尾，不代表同时启用两个 active trading domain。

如果缺少原订单市场的只读凭据或查询能力，Gateway 必须在请求发送前明确失败，不得改查当前 active market domain。

所有规则共同禁止：

```text
使用 fapi 凭据调用 dapi；
使用 dapi 凭据调用 fapi；
USDS-M 请求失败后自动回退到 COIN-M；
COIN-M 请求失败后自动回退到 USDS-M；
通过前端热切换 endpoint family；
一次业务调用同时向两个市场发送请求。
```

具体 endpoint path 由 fapi / dapi adapter 管理。业务模块不得依赖 path 字符串。

## 12. 调用上下文

所有 Gateway 调用必须接收 `BinanceGatewayCallContext` 或等价不可变结构，至少包含：

```text
trace_id
trigger_source
operation
market_type
account_domain（签名请求必须提供）
symbol（操作涉及交易对时提供）
business_object_type
business_object_id
request_time_utc
```

订单提交还必须包含：

```text
prepared_order_intent_id
client_order_id
execution_mode
```

订单撤销还必须包含：

```text
order_submission_attempt_id
prepared_order_intent_id
active_lock_id
client_order_id
exchange_order_id（如已知）
cancel_reason_code
```

调用上下文只用于校验、追踪、日志和元数据返回，不替代业务唯一键。

## 13. 标准返回结构

所有操作必须返回稳定的 `BinanceGatewayResult` 或等价结构：

```text
operation
market_type
endpoint_family
success
payload
response_received
request_sent
http_status
binance_error_code
sanitized_error_message
server_time_utc
request_started_at_utc
request_finished_at_utc
latency_ms
attempt_count
rate_limit_metadata
trace_id
```

规则：

```text
payload 保留业务模块进行字段标准化所需的 Binance 原始业务内容；
payload 不得包含 secret、signature 或认证 header；
Gateway 不把 Binance payload 直接写入业务数据库；
业务模块自行决定保存完整 payload、摘要或标准化字段；
错误返回也必须携带可追溯元数据；
订单提交必须明确 request_sent 和 response_received。
```

## 14. 标准错误分类

Gateway 必须把底层异常转换为稳定错误分类：

```text
gateway_disabled
capability_disabled
configuration_error
credential_missing
authentication_failed
permission_denied
invalid_market_type
domain_mismatch
request_validation_failed
clock_skew
rate_limited
connect_timeout
read_timeout
network_error
server_error
binance_rejected
response_schema_error
unknown_result
```

错误分类不得直接替业务模块决定 `blocked`、`failed`、`rejected` 或 `unknown`。调用模块按自己的合同完成映射。

订单提交的特殊映射原则：

```text
确认未发送 → Execution 可以映射为 failed_before_submit 或 blocked_before_submit；
Binance 明确拒绝 → Execution 映射为 rejected；
可能已发送但结果不确定 → Execution 必须映射为 unknown；
明确收到成功响应 → Execution 映射为 accepted。
```

## 15. 认证与签名

公共市场接口不得加载 API secret。

签名接口必须：

```text
从 settings 读取当前 market_type 和权限类别对应的凭据；
使用 Binance 要求的签名算法生成签名；
使用 UTC 时间和受控 server-time offset 生成 timestamp；
使用配置的 recvWindow；
禁止记录签名前原串、signature、secret 和完整认证 header；
请求结束后不得把 secret 放入结果对象、异常对象或 task 参数。
```

读取凭据与交易凭据必须在配置语义上分离：

```text
READ credentials：账户、订单状态、成交查询。
TRADE credentials：订单提交。
```

同一实际 Binance key 是否同时具备读取与交易权限由部署方决定，但代码不得默认把读取权限提升为交易权限。

## 16. 时间同步

Binance 返回时间戳按 UTC 解释。

Gateway 必须提供服务器时间读取能力，并维护短期 server-time offset，供签名请求使用。

规则：

```text
不得使用服务器本地时区参与业务判断；
不得把 PRC 时间传给 Binance；
签名出现 timestamp / recvWindow 错误时，不得无限重试；
时间偏差超过配置阈值时，签名请求必须失败并返回 clock_skew；
订单提交不得因为刷新时间偏差而自动重复提交。
```

server-time offset 可以放入进程内短期缓存或 Redis，不得作为核心业务事实。

## 17. 超时与重试

### 17.1 安全读取请求

以下接口可以执行有限重试：

```text
BinancePublicMarketGateway
BinanceAccountReadGateway
BinanceOrderStatusGateway
BinanceFillQueryGateway
```

只允许对以下技术异常重试：

```text
连接失败；
connect timeout；
HTTP 429 且响应给出可遵守的冷却条件；
部分 HTTP 5xx；
明确可重试的临时网络错误。
```

规则：

```text
最大尝试次数必须来自配置；
采用有上限的退避；
不得无限重试；
认证、权限、参数、市场域和响应结构错误不得自动重试；
每次尝试必须反映在 attempt_count 和技术日志中。
```

### 17.2 订单提交请求

`BinanceOrderSubmissionGateway` 不得自动重试，无论错误是否看起来可重试。

订单恢复只能通过 OrderStatusSync 使用原 `client_order_id` 查询，不得通过再次提交完成。

### 17.3 Gateway 重试与业务恢复边界

重试分为两层：

```text
Gateway 负责单次安全读取调用内部的有限技术重试；
业务 service 或编排层负责 Gateway 最终失败后的业务状态、重新调度和补偿动作。
```

业务模块不得自行实现 HTTP 重试、签名重试或 adapter 重试循环。

对于 DataCollection、BinanceAccountSync、PriceSnapshot、OrderStatusSync 和 FillSync 等读取业务：

```text
Gateway 可以对允许的临时技术错误执行有限重试；
Gateway 耗尽尝试后返回标准错误分类和 attempt_count；
业务层决定本轮失败、阻断、稍后重新调度或补采明确区间；
业务层不得把失败解释为旧事实仍然有效；
Gateway 尝试次数与业务逻辑轮次必须分别设上限，避免嵌套重试放大请求量。
```

对于订单提交：

```text
Gateway 层不重试；
业务层不重试；
任务与编排层不重试；
只能查询、对账或人工核对，不能再次提交。
```

## 18. 限频与并发

限频必须在 Gateway 统一实现，业务模块不得各自维护互相独立的请求计数器。

Gateway 必须：

```text
按 market_type、credential scope 和 operation category 隔离计数；
识别 Binance 返回的限频与订单计数响应 header；
在达到本地安全阈值前拒绝新请求；
收到 HTTP 429 后进入配置化冷却；
不得快速循环重试；
为订单提交保留独立且更严格的本地限频；
返回 rate_limit_metadata 供业务审计。
```

分布式部署时可以使用 Redis 保存短期限频计数和冷却状态。Redis 不得保存业务请求和响应的唯一副本。

## 19. 熔断

Gateway 应按以下维度维护短期熔断状态：

```text
market_type
capability
credential scope
```

连续出现认证失败、权限失败、时钟异常、限频或服务端异常时，可以阻断新的同类调用。

熔断只阻止外部请求，不修改业务对象，不释放订单锁，不改变调用方编排状态，也不修改任何运行配置。

订单提交熔断恢复后也不得自动重放历史提交。

## 20. 日志、指标与审计元数据

Gateway 必须记录脱敏技术日志和指标：

```text
operation
market_type
endpoint_family
success
error_category
http_status
latency_ms
attempt_count
rate_limit summary
trace_id
```

禁止记录：

```text
API secret
signature
完整 API key
完整认证 header
数据库密码
Redis 密码
未经检查的请求参数原文
可能包含认证信息的异常 repr
```

Gateway 不直接写业务 AlertEvent。调用方必须根据业务结果写对应 AlertEvent，避免同一失败生成两套含义不同的业务事件。

Gateway 可以暴露技术指标供 RuntimeGuard 巡检，但 RuntimeGuard 不得通过 Gateway 自动修复业务状态。

## 21. 环境配置

所有配置必须进入 `.env.example`，并带中文注释。真实 `.env` 不得提交。

### 21.1 总体与市场域

```text
BINANCE_GATEWAY_ENABLED
BINANCE_API_ENVIRONMENT
BINANCE_ACTIVE_MARKET_TYPE
BINANCE_USDS_M_BASE_URL
BINANCE_COIN_M_BASE_URL
```

约束：

```text
BINANCE_API_ENVIRONMENT 只能使用明确枚举，例如 production / testnet；
环境、base_url 和凭据必须一致；
active market type 属于新交易链路的部署硬配置，不允许后台热切换；
该配置不改变 DataCollection / DataBackfill 固定的 USDS-M BTCUSDT 采集域，也不覆盖既有订单已经冻结的追踪市场；
base_url 不得由业务模块传入；
测试不得误连 production base_url。
```

### 21.2 能力硬开关

```text
BINANCE_PUBLIC_DATA_ENABLED
BINANCE_ACCOUNT_READ_ENABLED
BINANCE_ORDER_SUBMISSION_ENABLED
BINANCE_ORDER_STATUS_QUERY_ENABLED
BINANCE_FILL_QUERY_ENABLED
BINANCE_REAL_TRADING_ENABLED
```

默认规则：

```text
真实订单提交默认关闭；
真实交易默认关闭；
签名读取能力必须显式开启；
后台真实交易运行开关不能突破这些硬开关；
Gateway 不读取或管理后台运行开关，正式编排必须在进入 OrderPlan 前完成一次运行权限检查。
```

订单最终权限至少满足：

```text
BINANCE_GATEWAY_ENABLED
AND BINANCE_ORDER_SUBMISSION_ENABLED
AND BINANCE_REAL_TRADING_ENABLED
```

### 21.3 凭据

```text
BINANCE_USDS_M_READ_API_KEY
BINANCE_USDS_M_READ_API_SECRET
BINANCE_USDS_M_TRADE_API_KEY
BINANCE_USDS_M_TRADE_API_SECRET
BINANCE_COIN_M_READ_API_KEY
BINANCE_COIN_M_READ_API_SECRET
BINANCE_COIN_M_TRADE_API_KEY
BINANCE_COIN_M_TRADE_API_SECRET
```

规则：

```text
凭据必须按 market_type 和权限类别显式选择；
不得在 USDS-M 与 COIN-M 之间隐式回退；
不得把 READ 配置对象当作 TRADE 配置对象；
日志最多显示 configured=true 和必要的脱敏前缀；
任何页面不得读取或修改完整 secret。
```

### 21.4 时间、超时与重试

```text
BINANCE_RECV_WINDOW_MS
BINANCE_MAX_CLOCK_SKEW_MS
BINANCE_SERVER_TIME_CACHE_SECONDS
BINANCE_CONNECT_TIMEOUT_SECONDS
BINANCE_READ_TIMEOUT_SECONDS
BINANCE_ORDER_SUBMIT_READ_TIMEOUT_SECONDS
BINANCE_SAFE_READ_MAX_ATTEMPTS
BINANCE_RETRY_BASE_DELAY_MS
BINANCE_RETRY_MAX_DELAY_MS
```

### 21.5 限频与熔断

```text
BINANCE_MIN_REQUEST_INTERVAL_MS
BINANCE_RATE_LIMIT_SAFETY_RATIO
BINANCE_RATE_LIMIT_COOLDOWN_SECONDS
BINANCE_ORDER_SUBMIT_LOCAL_LIMIT_PER_MINUTE
BINANCE_CIRCUIT_BREAKER_FAILURE_THRESHOLD
BINANCE_CIRCUIT_BREAKER_COOLDOWN_SECONDS
```

具体默认值由开发计划根据 Binance 官方限制和部署规模确定，不得散落硬编码在业务模块中。

## 22. 与业务模块的关系

### 22.1 DataCollection / DataBackfill

通过 `BinancePublicMarketGateway` 获取服务器时间和已收盘 K 线。采集市场固定为 Binance USDS-M BTCUSDT，不读取 `BINANCE_ACTIVE_MARKET_TYPE` 决定采集域。K 线闭合判断、幂等写入和数据冲突处理仍由数据模块负责。

### 22.2 BinanceAccountSync

通过：

```text
BinanceAccountReadGateway
BinancePublicMarketGateway
```

读取账户、余额、持仓和交易规则，并生成数据库事实快照。

BinanceAccountSync 对 OpsConsole 提供一键刷新 application service。OpsConsole 不直接调用任何 Gateway。

一键刷新只处理当前 active account domain，不提供一次同步全部市场域的能力。

### 22.3 PriceSnapshot

需要读取 Binance 标记价格时，只能调用 `BinancePublicMarketGateway.get_mark_price`。每次业务调用必须实际请求 Binance，不得返回 Gateway 历史缓存价格。PriceSnapshot 仍负责价格事实落库、TTL 和消费边界。

### 22.4 ExecutionPreparation

报单前实时价格复核只能调用 `BinancePublicMarketGateway.get_book_ticker`。

ExecutionPreparation 负责：

```text
BUY 选择 best ask；
SELL 选择 best bid；
与 ExecutionPreparation 明确输入的 PriceSnapshot.mark_price 比较；
记录价格偏差和审计证据；
按 ExecutionPreparation 阈值决定通过或阻断。
```

Gateway 不读取 PriceSnapshot，不决定 1% 阈值，不生成 PreparedOrderIntent，也不提交订单。

### 22.5 Execution

只有 Execution 可以调用 `BinanceOrderSubmissionGateway`。Gateway 返回提交技术结果，Execution 保存 OrderSubmissionAttempt 并写业务 AlertEvent。

### 22.6 OrderStatusSync

只调用 `BinanceOrderStatusGateway`，使用原订单冻结市场选择 adapter，并将返回事实保存为 OrderStatusSyncRecord。

### 22.7 FillSync

只调用 `BinanceFillQueryGateway`，使用原订单冻结市场选择 adapter，并负责逐笔成交幂等和 OrderFillSummary。

## 23. 数据库与 Redis

Binance Gateway 不拥有核心业务表。

Gateway 不保存：

```text
Kline
BinanceSyncRun
PriceSnapshot
OrderSubmissionAttempt
OrderStatusSyncRecord
TradeFill
OrderFillSummary
```

Gateway 可以使用 Redis 保存：

```text
短期限频计数；
短期冷却状态；
短期熔断状态；
短期 server-time offset；
分布式请求协调锁。
```

Redis 故障时不得默认放行真实订单提交。读取请求是否降级由对应业务模块决定。

## 24. 测试要求

必须提供 fake gateway 或可注入 transport，自动化测试不得访问真实 Binance。

至少覆盖：

```text
1. 所有五类接口只能调用允许的操作。
2. 业务模块无法获得通用 raw request 能力。
3. USDS-M 只选择 fapi adapter。
4. COIN-M 只选择 dapi adapter。
5. market_type 与 account_domain 不一致时不发送签名请求。
6. 公共请求不加载 API secret。
7. READ 与 TRADE 凭据按权限隔离。
8. 缺少凭据时签名请求失败且不发送。
9. 日志、异常和结果不包含 secret、signature 或完整 header。
10. 签名参数使用 UTC timestamp 和配置 recvWindow。
11. clock skew 超限时签名请求失败。
12. 安全读取只对允许的技术异常有限重试。
13. 参数、认证和权限错误不重试。
14. 订单提交无论何种错误都不自动重试。
15. 订单提交 read timeout 返回可能已发送的未知结果。
16. 订单提交明确 Binance 拒绝时返回明确拒绝结果。
17. 本地限频命中时不发送外部请求。
18. HTTP 429 进入冷却且不快速重试。
19. 熔断打开时拒绝同类请求。
20. Gateway disabled 时所有外部请求被阻断。
21. 各能力硬开关分别生效。
22. 调用方参数或数据库配置不能突破 Gateway 的部署级硬开关。
23. call context 和 trace_id 原样传递到结果元数据。
24. 业务 payload 与技术元数据可以被调用模块分别消费。
25. Redis 故障时真实订单提交 fail-closed。
26. OpsConsole 不能直接调用 Gateway。
27. get_book_ticker 同时返回可解析的 best bid、best ask 及对应数量。
28. ExecutionPreparation 只能使用 get_book_ticker，不能获得账户读取或订单提交能力。
29. get_mark_price 和 get_book_ticker 每次业务调用都实际请求 Binance，不返回 Gateway 历史缓存价格，调用上下文和请求时间可审计。
30. Gateway 不按 BUY / SELL 选择价格，也不计算或判断 1% 偏差。
31. 订单提交在 Gateway、Execution、Celery 和编排层均不会重试。
32. 提交前明确 request_sent=false 时，同一 PreparedOrderIntent 也不会再次提交。
33. 安全读取的 Gateway 技术重试与业务重新调度分别限次，不形成无界嵌套重试。
34. unknown 提交可以只凭原 client_order_id 查询订单，不要求 exchange_order_id。
35. Gateway 的订单未找到结果不会被解释为提交失败或解锁依据。
36. OrderStatusSync 的逻辑 poll_sequence 与 Gateway attempt_count 分别记录。
37. FillSync 可以按 exchange_order_id 和 page_cursor 读取全部成交页。
38. 成交查询明确返回 next_page_cursor 和 pagination_complete，不静默截断。
39. Gateway 不判断成交数量是否完整，不生成 synced_empty，不释放 ActiveLock。
40. DataCollection / DataBackfill 固定使用 USDS-M BTCUSDT，不因 active trading market 改变。
41. 新交易链路只能使用部署 active market_type 和 account_domain。
42. OrderStatusSync / FillSync 使用原订单冻结市场，不被当前 active trading market 覆盖。
43. 当前部署缺少原订单市场的读取能力时明确失败，不回退到另一市场。
44. MARKET 提交只发送字段白名单内参数，出现未知字段或禁用字段时 request_sent=false。
45. Gateway 不补充或修改冻结订单参数。
```

## 25. 验收标准

满足以下条件才算通过：

```text
所有 Binance REST 请求都能定位到五类受限接口之一；
仓库中不存在业务模块自行签名或自行创建 Binance HTTP client；
不存在对业务模块公开的通用 endpoint 调用方法；
固定行情采集、新交易链路和既有订单追踪分别采用明确且可测试的市场校验规则；
市场域、权限类别和凭据选择明确且可测试；
订单提交只能从 Execution 到达 BinanceOrderSubmissionGateway；
订单提交不会被 Gateway 自动重试；
读取重试、限频、熔断、超时和错误分类集中实现；
敏感信息不会进入日志、异常、结果对象或业务通知；
所有关键配置均进入 .env.example 并带中文注释；
fake gateway 可以覆盖全部接口测试；
mark price 和报单前盘口价格均由公共市场接口实际请求，且与业务价格事实及 price guard 职责分离；
订单提交采用严格字段白名单，不允许任意 Binance 参数透传；
Gateway 不生成业务决策，不写业务事实，不改变订单锁。
```

## 26. 当前不包含的能力

```text
WebSocket 行情流；
Binance User Data Stream；
订单修改；
批量订单；
杠杆修改；
保证金模式修改；
持仓模式修改；
资金划转；
多 active domain 并行交易；
多账户并行交易；
其他交易所抽象。
```

如果增加上述能力，必须新增明确的受限接口和调用方权限，不得扩展为公共 `request()`。
