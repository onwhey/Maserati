# ExecutionPreparation 实现说明

## 1. 当前实现范围

当前代码已实现：

```text
ExecutionPreparationResult；
PreparedOrderIntent；
ApprovedOrderIntent → ExecutionPreparation → PreparedOrderIntent；
执行准备幂等占位；
ApprovedOrderIntent 上游链路校验；
PriceSnapshot 指纹和有效期校验；
BinanceSyncRun 快照集合校验；
ActiveLock active 校验；
BinancePublicMarketGateway.get_book_ticker 调用；
BUY 使用 best ask；
SELL 使用 best bid；
1% price guard；
交易规则复核；
reduce-only 复核；
client_order_id；
订单提交幂等键；
AlertEvent；
执行准备阻断时通过 OrderPlanActiveLockService 安全释放锁。
```

当前实现不提交订单，不调用订单提交 Gateway，不创建 OrderSubmissionAttempt，不查询订单状态，不查询成交，不修改杠杆或保证金模式。

## 2. 主要调用链

```text
prepare_execution
→ 读取 ApprovedOrderIntent
→ 占用该 ApprovedOrderIntent 的唯一 ExecutionPreparationResult
→ 校验 RiskCheckResult / CandidateOrderIntent / OrderPlan / PriceSnapshot / BinanceSyncRun / ActiveLock
→ 调用 BinancePublicMarketGateway.get_book_ticker
→ BUY 选择 ask，SELL 选择 bid
→ 与绑定 PriceSnapshot.mark_price 比较
→ 偏差 <= 100 bps 时生成 PreparedOrderIntent
→ 偏差 > 100 bps 或业务事实不安全时 BLOCKED
→ 写 AlertEvent
```

幂等重放直接返回既有 ExecutionPreparationResult，不重新查询盘口。

## 3. 当前 price guard 口径

```text
price_deviation_ratio = abs(selected_live_price - reference_mark_price) / reference_mark_price
price_deviation_bps = price_deviation_ratio * 10000
```

规则：

```text
price_deviation_bps <= EXECUTION_PREPARATION_MAX_PRICE_DEVIATION_BPS：允许继续；
price_deviation_bps > EXECUTION_PREPARATION_MAX_PRICE_DEVIATION_BPS：阻断。
```

默认阈值为 100 bps，即 1%。

盘口结果只作为执行前证据，不会写回 PriceSnapshot，也不是成交价。

## 4. 数据与外部影响

```text
写 MySQL：是；
访问 Redis：否；
访问 Binance：是，仅通过 BinancePublicMarketGateway.get_book_ticker；
访问订单提交接口：否；
发送 Hermes：否；
调用大模型：否；
创建 CandidateOrderIntent：否；
创建 ApprovedOrderIntent：否；
创建 PreparedOrderIntent：PREPARED 时创建；
创建 OrderSubmissionAttempt：否；
写入 TradeFill：否；
修改 BinancePositionSnapshot：否；
写 AlertEvent：是；
创建 NotificationDeliveryAttempt / NotificationSuppression：否。
```

## 5. 验证

定向测试：

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_execution_preparation_stage4.py -q
```

阶段 4 相邻链路测试：

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_order_plan_stage4.py tests\test_risk_check_stage4.py tests\test_execution_preparation_stage4.py -q
```

全量测试：

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

Django 与迁移检查：

```powershell
.\.venv\Scripts\python.exe manage.py check
.\.venv\Scripts\python.exe manage.py makemigrations --check --dry-run
```
