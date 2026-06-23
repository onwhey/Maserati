# ProjectFoundation 阶段 0 实现记录

## 1. 记录目的

本文档记录阶段 0 当前已经落地的工程底座实现。

本文档不是 requirements，不新增业务需求，不替代 `docs/plans/foundation_implementation_plan.md`。

## 2. 当前实现范围

当前阶段已经实现：

```text
Django 5.2 项目结构；
pyproject.toml 依赖范围；
requirements.lock 实际安装版本；
.env.example 中文注释配置模板；
settings 显式读取 .env；
MySQL 配置读取；
Redis 配置读取；
Celery app 基础加载；
UTC 时间配置；
trace_id 和 trigger_source 基础；
基础异常与全局结果语义；
基础幂等辅助；
日志脱敏工具；
Django system checks；
AlertEvent 最小事实模型与写入 service；
AuditRecord 最小审计模型与写入 service；
RuntimeTradingConfig 与真实交易最终权限计算；
foundation_check 管理命令；
show_real_trading_permission 管理命令；
pytest / pytest-django 基础测试。
```

## 3. 当前代码结构

```text
config/
  settings.py
  celery.py
  urls.py
  asgi.py
  wsgi.py

apps/foundation/
  context.py
  triggers.py
  exceptions.py
  results.py
  idempotency.py
  redaction.py
  logging_filters.py
  checks.py
  health.py
  management/commands/foundation_check.py

apps/alerts/
  models.py
  services.py

apps/audit/
  models.py
  services.py

apps/runtime_config/
  models.py
  services.py
  management/commands/show_real_trading_permission.py
```

## 4. 数据库对象

阶段 0 已创建：

```text
AlertEvent
AuditRecord
RuntimeTradingConfig
```

这些对象只覆盖底座最小事实，不包含行情、策略、账户、订单、成交、编排、巡检、后台或 AI 复盘业务表。

## 5. 配置读取

`config/settings.py` 默认读取项目根目录 `.env`。

测试可以通过 `DJANGO_ENV_FILE` 指定不存在或隔离的 env 文件，用于验证配置缺失会清晰失败。

正式默认数据库不使用 SQLite。只有 `APP_ENV=test` 或 pytest 运行时使用内存 SQLite 测试库。

## 6. 真实交易权限

当前真实交易权限逻辑为：

```text
最终真实交易权限 = DEPLOYMENT_REAL_TRADING_ENABLED AND RuntimeTradingConfig.runtime_real_trading_permission
```

查看权限不会创建数据库记录。

只有明确调用运行开关变更 service 时，才会创建或修改 `RuntimeTradingConfig`，并写入 `AuditRecord` 与 `AlertEvent`。

## 7. 管理命令

### 7.1 底座检查

```powershell
.\.venv\Scripts\python.exe manage.py foundation_check
```

检查内容：

```text
Django system check；
数据库连接；
数据库迁移是否全部应用；
Redis 配置；
Celery app；
部署级真实交易硬权限；
Redis ping。
```

如果本地 Redis 暂未启动，可先运行：

```powershell
.\.venv\Scripts\python.exe manage.py foundation_check --skip-redis-ping
```

该命令不访问 Binance、不访问 DeepSeek、不发送 Hermes、不提交订单。

### 7.2 查看真实交易权限

```powershell
.\.venv\Scripts\python.exe manage.py show_real_trading_permission
```

输出：

```text
deployment_allowed；
runtime_allowed；
effective_allowed；
fail_closed；
reason_code。
```

该命令只读数据库，不修改运行开关。

## 8. 当前不包含

阶段 0 当前没有实现：

```text
行情采集；
数据质量；
数据回补；
MarketSnapshot；
FeatureLayer；
AtomicSignal；
DomainSignal；
MarketRegime；
StrategyRouting；
StrategySignal；
DecisionSnapshot；
BinanceGateway 真实请求；
Binance Account Sync；
PriceSnapshot；
OrderPlan；
RiskCheck；
ExecutionPreparation；
Execution；
OrderStatusSync；
FillSync；
PipelineOrchestrator；
RuntimeGuard；
Notifications 投递 worker；
OpsConsole；
PerformanceMetrics；
DeepSeekGateway；
AIReview。
```

## 9. 已知实现说明

`AlertEvent.event_key` 当前长度为 191。

原因：

```text
MySQL utf8mb4 下，较旧或受限索引配置可能无法创建 255 字符唯一索引。
191 字符可以兼容当前本地 MySQL 索引限制。
```

业务语义不变：`event_key` 仍然是 AlertEvent 的幂等唯一键。

## 10. 当前验收命令

```powershell
.\.venv\Scripts\python.exe manage.py check
.\.venv\Scripts\python.exe manage.py makemigrations --check --dry-run
.\.venv\Scripts\python.exe manage.py migrate
.\.venv\Scripts\python.exe manage.py foundation_check
.\.venv\Scripts\python.exe manage.py show_real_trading_permission
.\.venv\Scripts\python.exe -m pytest
```

如 Redis 未启动，`foundation_check` 可临时使用：

```powershell
.\.venv\Scripts\python.exe manage.py foundation_check --skip-redis-ping
```

但进入后续依赖 Redis 的阶段前，应启动 Redis 并通过完整 `foundation_check`。
