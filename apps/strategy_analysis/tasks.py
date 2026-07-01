"""StrategyAnalysis 模块：策略回测后台任务入口。
负责：接收 Celery 任务并调用 StrategyBacktestRun 执行服务。
不负责：回测算法、正式编排、订单计划、风控审批、真实交易执行或订单同步。
读写数据库：通过 service 读写 StrategyBacktestRun 和测试回放相关事实。
访问 Redis：仅通过 Celery broker 间接使用。
访问外部服务：不涉及。
发送 Hermes：不涉及。
调用大模型：不涉及。
涉及交易执行：不涉及。
允许真实交易：不允许。
"""

from __future__ import annotations

from config.celery import app

from .services.backtest import execute_strategy_backtest_run


@app.task(name="strategy_analysis.execute_strategy_backtest_run")
def execute_strategy_backtest_run_task(*, strategy_backtest_run_id: int) -> dict[str, object]:
    result = execute_strategy_backtest_run(strategy_backtest_run_id=strategy_backtest_run_id)
    return {
        "status": str(result.status),
        "reason_code": result.reason_code,
        "message": result.message,
        "trace_id": result.trace_id,
        "trigger_source": result.trigger_source,
        "data": result.data,
    }
