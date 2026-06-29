# OrderPlan 实现说明

## 1. 当前实现范围

当前代码已实现：

```text
OrderPlanStepAdapter 真实交易权限前置检查；
部署市场身份检查；
明确 DecisionSnapshot、BinanceSyncRun、PriceSnapshot 消费；
账户子快照与 PriceSnapshot 指纹校验；
USDS-M 目标数量计算；
COIN-M 目标合约张数计算；
step_size 向零取整；
最小调仓与交易规则边界判断；
OrderPlan、CandidateOrderIntent、OrderPlanActiveLock、OrderPlanActiveLockEvent；
primary 候选意图；
净额反手 fallback_reduce_only 候选意图；
OrderPlan 幂等与 ActiveLock 冲突保护；
AlertEvent。
```

当前实现不提交订单，不调用 Binance，不执行风控，不生成 ApprovedOrderIntent。

## 2. 主要调用链

```text
run_order_plan_step
→ 读取部署级真实交易硬权限与 MySQL 运行开关
→ 检查部署市场身份
→ create_order_plan
→ 校验明确上游业务对象及其指纹
→ calculate_order_plan
→ 数据库事务内创建 OrderPlan
→ 需要调仓时取得 OrderPlanActiveLock
→ 创建 primary CandidateOrderIntent
→ 净额反手时创建 fallback_reduce_only CandidateOrderIntent
```

权限关闭时，Adapter 返回正常结束，不调用 OrderPlan，也不创建计划、候选意图或锁。

## 3. 计算口径

所有仓位、数量、价格和名义价值计算均使用 Decimal。

USDS-M 使用当前权益、目标仓位比例和 mark price 换算基础资产数量。

COIN-M 先按 mark price 把原生结算资产权益换算为 USD 名义，再使用 contract_size 换算合约张数。

目标数量和订单差额按 step_size 向零取整，不通过放大数量追齐目标。目标数量取整后同步重算目标名义价值。可交易差额低于系统最小调仓阈值时，OrderPlan 记录 `no_order_required`，不取得 ActiveLock。

只减仓场景如果无法形成满足交易所最小数量、最小名义和数量精度的合法订单，必须阻断，不能伪装成“无需交易”。目标为零但因 step_size 留下合法残余仓位时，候选意图标记为减仓并明确记录残余，不宣称已经完全平仓。

净额反手只生成一笔 primary 候选订单，但保存“关闭旧方向”和“打开新方向”两个风险组件；同时预生成只关闭旧方向的 fallback。RiskCheck 后续只能选择这两份既有候选意图，不能临时改造订单。

幂等重放除校验直接业务对象 ID 和配置指纹外，还会重新验证账户子快照、价格快照和 DecisionSnapshot 冻结内容；绑定事实被篡改时不返回可继续消费的既有计划。

## 4. 冻结价格条件与 LIMIT 候选意图

OrderPlan 只消费 `DecisionSnapshot.frozen_trade_price_condition`，不回读 StrategySignal、MarketRegime 或结构领域事实重新解释价格条件。

当冻结价格条件不存在时，且确需调仓，OrderPlan 继续生成 MARKET 候选意图。

当冻结价格条件存在且符合标准结构时：

```text
allow_chasing = true 且当前 PriceSnapshot 位于 acceptable_price_zone 内
→ 生成 MARKET 候选意图；

acceptable_price_zone 是可解析的结构化区间，且无法或不允许 MARKET 执行
→ 生成 LIMIT 候选意图；

acceptable_price_zone 只是文本说明，无法形成可报单价格
→ no_order_required；

acceptable_price_zone 是结构化区间但边界缺失、非法、非正数或上下沿反转
→ blocked。
```

LIMIT 价格转换规则：

```text
BUY 候选意图：使用 acceptable_price_zone 上沿作为 limit_price；
SELL 候选意图：使用 acceptable_price_zone 下沿作为 limit_price。
```

这表示“买入最高愿意接受的价格”和“卖出最低愿意接受的价格”。OrderPlan 不根据文案猜测价格，也不请求 Binance 刷新价格。

标准价格条件生成的 LIMIT 候选意图默认使用 `GTC`，并把 `limit_valid_until_utc` 设为本 4 小时周期结束前 10 分钟。该时间只用于后续 OrderCycleCloseout 周期收尾，不表示交易所自动到期。

`limit_price_source` 不作为独立数据库字段保存，写入 CandidateOrderIntent 的 evidence 与 price_condition_evidence 中，便于复盘说明该价格来自可接受区间上沿或下沿。

## 5. ActiveLock 当前边界

当前已实现锁身份唯一约束、锁取得、released 再取得、active 冲突阻断、failed 持续阻断和锁事件记录。

当前已补充“执行前停止”类锁释放入口，供 RiskCheck 或后续执行前检查在明确阻断、拒绝或失败且不会继续提交订单时调用。

Execution、OrderStatusSync 和 FillSync 后续仍必须根据各自已落库的确定事实调用 OrderPlan 所属锁服务完成安全收尾，不得直接更新锁表。

## 6. 数据与外部影响

```text
写 MySQL：是；
读取 Redis：PriceSnapshot selector 可读取同一价格快照缓存；
访问 Binance：否；
发送 Hermes：否；
调用大模型：否；
创建 CandidateOrderIntent：仅权限通过、事实完整且确需调仓时；
创建 ApprovedOrderIntent：否；
创建 PreparedOrderIntent：否；
创建 OrderSubmissionAttempt：否；
写入 TradeFill：否；
修改 BinancePositionSnapshot：否。
```

## 7. 验证

定向测试：

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_order_plan_stage4.py -q
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
