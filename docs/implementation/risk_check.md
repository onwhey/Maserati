# RiskCheck 实现说明

## 1. 当前实现范围

当前代码已实现：

```text
RiskCheckResult；
RiskRuleSet / RiskRuleDefinition / RiskRuleResult / RiskCheckIssue；
ApprovedOrderIntent；
RiskCheck 插件注册与规则执行；
P0 默认风控规则集初始化；
primary 候选意图审核；
净额反手 fallback_reduce_only 候选意图审核；
ALLOW / DENY / BLOCKED / FAILED 聚合；
ApprovedOrderIntent 生成；
候选意图状态更新；
风控未放行时调用 OrderPlanActiveLockService 安全释放锁；
AlertEvent；
dry-run 风控演练。
```

当前实现不提交订单，不调用 Binance，不访问 Redis，不发送 Hermes，不调用大模型，不生成 PreparedOrderIntent。

## 2. 主要调用链

```text
run_risk_check
→ 校验直接输入对象
→ 读取 OrderPlan、primary CandidateOrderIntent、fallback_reduce_only、账户事实、价格事实和 ActiveLock
→ 校验账户快照集合与 PriceSnapshot 指纹
→ 加载或初始化当前风控规则集
→ RuleEngine 按规则顺序执行插件
→ 聚合风控结果
→ ALLOW 时生成 ApprovedOrderIntent
→ DENY / BLOCKED / FAILED 时标记候选意图并释放 ActiveLock
→ 写 AlertEvent
```

dry-run 会执行同一套规则判断，但不写 RiskCheckResult、ApprovedOrderIntent、候选意图状态、ActiveLock 或 AlertEvent。

## 3. 风控处理口径

RiskCheck 只审核 OrderPlan 已经生成的候选订单意图。

RiskCheck 不重新计算目标仓位，不缩单，不临时改造订单数量，不新增候选订单，不访问 Binance，不执行真实交易。

净额反手场景只允许在 OrderPlan 已预生成的两份候选意图中选择：

```text
primary：关闭旧方向并打开新方向；
fallback_reduce_only：只关闭旧方向。
```

如果 primary 因新增风险部分无法放行，但问题允许检查 fallback，且 fallback_reduce_only 通过全部风控，则生成指向 fallback 的 ApprovedOrderIntent。否则本轮风控不放行。

只降低风险的订单不要求新增保证金，也不要求存在可验证杠杆；新增风险订单必须具备可验证杠杆和可用余额事实。

## 4. 当前 P0 默认规则

默认规则覆盖：

```text
候选意图基础合法性；
OrderPlan 可消费性；
订单风险组件完整性；
业务对象绑定一致性；
账户同步批次可消费性；
账户快照与价格快照指纹；
市场身份一致性；
One-Way 持仓模式；
ActiveLock 一致性；
mark price 快照存在与未过期；
USDS-M / COIN-M 可用余额事实；
最小名义价值；
数量步进、最小数量和数量精度；
最大数量；
最大名义价值；
新增风险保证金估算；
净额反手 fallback_reduce_only 存在性。
```

规则失败默认 fail-closed：插件缺失、规则异常或事实不足时不放行。

## 5. 数据与外部影响

```text
写 MySQL：是；
访问 Redis：否；
访问 Binance：否；
发送 Hermes：否；
调用大模型：否；
创建 CandidateOrderIntent：否；
创建 ApprovedOrderIntent：ALLOW 时创建；
创建 PreparedOrderIntent：否；
创建 OrderSubmissionAttempt：否；
写入 TradeFill：否；
修改 BinancePositionSnapshot：否；
写 AlertEvent：是；
创建 NotificationDeliveryAttempt / NotificationSuppression：否。
```

## 6. 验证

定向测试：

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_risk_check_stage4.py -q
```

相邻链路测试：

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_order_plan_stage4.py tests\test_risk_check_stage4.py -q
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
