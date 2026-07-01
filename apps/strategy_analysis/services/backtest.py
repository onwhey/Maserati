"""StrategyAnalysis 模块：提供测试环境策略收益回放服务。
负责：调用历史策略链路回放结果，并用历史 4h K 线按固定规则模拟权益变化。
不负责：创建正式订单、风控审批、真实执行、订单同步、成交同步或自动修改策略版本包。
读写数据库：读取 Kline；会通过 replay_strategy_analysis_chain 在测试库写入策略分析链路结果。
访问 Redis：不涉及。
访问外部服务：不涉及。
发送 Hermes：不涉及。
调用大模型：不涉及。
涉及交易执行：不涉及。
允许真实交易：不允许。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.foundation.context import ensure_context
from apps.foundation.results import ResultStatus, ServiceResult
from apps.market_data.domain import TIMEFRAME_4H, configured_collection_domain, ensure_utc, is_timeframe_boundary, timeframe_delta
from apps.market_data.models import Kline

from ..models import StrategyAnalysisRelease, StrategyBacktestPeriodResult, StrategyBacktestRun, StrategyBacktestRunStatus
from .replay import replay_strategy_analysis_chain


NO_TARGET_POLICY_HOLD = "hold"
NO_TARGET_POLICY_FLAT = "flat"
REPLAY_SIMULATABLE_STATUSES = {"completed", "completed_no_strategy"}


def create_strategy_backtest_run(
    *,
    start_analysis_close_time_utc: datetime,
    end_analysis_close_time_utc: datetime,
    strategy_analysis_release_id: int,
    strategy_analysis_release_hash: str = "",
    lookback_4h_count: int = 500,
    lookback_1d_count: int = 500,
    initial_equity: Decimal = Decimal("10000"),
    fee_rate: Decimal = Decimal("0.0004"),
    leverage: Decimal = Decimal("1"),
    no_target_policy: str = NO_TARGET_POLICY_HOLD,
    business_request_prefix: str = "strategy-backtest",
    requested_by: str = "",
    trace_id: str | None = None,
    trigger_source: str = "ops_console_strategy_backtest",
) -> ServiceResult:
    context = ensure_context(trace_id=trace_id, trigger_source=trigger_source)
    guard_error = _environment_guard()
    if guard_error:
        return ServiceResult(ResultStatus.BLOCKED, guard_error, "StrategyBacktest 只允许测试或开发环境运行", context.trace_id, trigger_source)
    request_error = _validate_request(
        start_analysis_close_time_utc=start_analysis_close_time_utc,
        end_analysis_close_time_utc=end_analysis_close_time_utc,
        initial_equity=initial_equity,
        fee_rate=fee_rate,
        leverage=leverage,
        no_target_policy=no_target_policy,
    )
    if request_error:
        return ServiceResult(ResultStatus.BLOCKED, request_error, "StrategyBacktest 请求参数无效", context.trace_id, trigger_source)
    release = StrategyAnalysisRelease.objects.filter(id=strategy_analysis_release_id).first()
    if release is None:
        return ServiceResult(
            ResultStatus.BLOCKED,
            "strategy_backtest_release_not_found",
            "策略版本包不存在",
            context.trace_id,
            trigger_source,
        )
    effective_release_hash = strategy_analysis_release_hash or release.release_hash
    run = StrategyBacktestRun.objects.create(
        run_key=f"strategy-backtest-{uuid.uuid4().hex}",
        status=StrategyBacktestRunStatus.QUEUED,
        reason_code="strategy_backtest_queued",
        message="StrategyBacktest 已进入后台队列",
        strategy_analysis_release=release,
        strategy_analysis_release_hash=effective_release_hash,
        start_analysis_close_time_utc=ensure_utc(start_analysis_close_time_utc),
        end_analysis_close_time_utc=ensure_utc(end_analysis_close_time_utc),
        lookback_4h_count=lookback_4h_count,
        lookback_1d_count=lookback_1d_count,
        initial_equity=initial_equity,
        fee_rate=fee_rate,
        leverage=leverage,
        no_target_policy=no_target_policy,
        business_request_prefix=business_request_prefix,
        requested_by=requested_by,
        trace_id=context.trace_id,
        trigger_source=trigger_source,
    )
    try:
        from apps.strategy_analysis.tasks import execute_strategy_backtest_run_task

        task = execute_strategy_backtest_run_task.delay(strategy_backtest_run_id=run.id)
    except Exception as exc:  # pragma: no cover - 依赖外部 broker，测试中只验证状态写入
        run.status = StrategyBacktestRunStatus.FAILED
        run.reason_code = "strategy_backtest_enqueue_failed"
        run.message = "StrategyBacktest 后台任务提交失败"
        run.error_message = f"{exc.__class__.__name__}: {exc}"
        run.finished_at_utc = timezone.now()
        run.save(update_fields=["status", "reason_code", "message", "error_message", "finished_at_utc", "updated_at_utc"])
        return ServiceResult(
            ResultStatus.FAILED,
            "strategy_backtest_enqueue_failed",
            "StrategyBacktest 后台任务提交失败",
            context.trace_id,
            trigger_source,
            {"strategy_backtest_run_id": run.id, "status": run.status, "error_message": run.error_message},
        )
    run.celery_task_id = task.id or ""
    run.save(update_fields=["celery_task_id", "updated_at_utc"])
    return ServiceResult(
        ResultStatus.SUCCEEDED,
        "strategy_backtest_run_created",
        "StrategyBacktest 后台任务已创建",
        context.trace_id,
        trigger_source,
        {"strategy_backtest_run_id": run.id, "status": run.status, "celery_task_id": run.celery_task_id},
    )


def execute_strategy_backtest_run(*, strategy_backtest_run_id: int) -> ServiceResult:
    with transaction.atomic():
        run = StrategyBacktestRun.objects.select_for_update().get(id=strategy_backtest_run_id)
        if run.status not in {StrategyBacktestRunStatus.QUEUED, StrategyBacktestRunStatus.FAILED}:
            return ServiceResult(
                ResultStatus.NO_ACTION,
                "strategy_backtest_run_not_queued",
                "StrategyBacktestRun 当前状态不需要执行",
                run.trace_id,
                "celery_worker",
                {"strategy_backtest_run_id": run.id, "status": run.status},
            )
        run.status = StrategyBacktestRunStatus.RUNNING
        run.reason_code = "strategy_backtest_running"
        run.message = "StrategyBacktest 正在运行"
        run.started_at_utc = timezone.now()
        run.finished_at_utc = None
        run.error_message = ""
        run.progress_total_periods = len(_analysis_close_times(run.start_analysis_close_time_utc, run.end_analysis_close_time_utc))
        run.progress_completed_periods = 0
        run.progress_current_analysis_close_time_utc = None
        run.progress_last_status = ""
        run.progress_last_reason_code = ""
        run.progress_updated_at_utc = run.started_at_utc
        run.period_results.all().delete()
        run.save(
            update_fields=[
                "status",
                "reason_code",
                "message",
                "started_at_utc",
                "finished_at_utc",
                "error_message",
                "progress_total_periods",
                "progress_completed_periods",
                "progress_current_analysis_close_time_utc",
                "progress_last_status",
                "progress_last_reason_code",
                "progress_updated_at_utc",
                "updated_at_utc",
            ]
        )

    try:
        progress_callback = _build_run_progress_callback(run.id)
        result = run_strategy_backtest(
            start_analysis_close_time_utc=run.start_analysis_close_time_utc,
            end_analysis_close_time_utc=run.end_analysis_close_time_utc,
            strategy_analysis_release_id=run.strategy_analysis_release_id,
            strategy_analysis_release_hash=run.strategy_analysis_release_hash,
            lookback_4h_count=run.lookback_4h_count,
            lookback_1d_count=run.lookback_1d_count,
            initial_equity=run.initial_equity,
            fee_rate=run.fee_rate,
            leverage=run.leverage,
            no_target_policy=run.no_target_policy,
            business_request_prefix=f"{run.business_request_prefix}-{run.id}",
            trace_id=run.trace_id,
            trigger_source="strategy_backtest_celery_worker",
            progress_callback=progress_callback,
        )
    except Exception as exc:
        run.status = StrategyBacktestRunStatus.FAILED
        run.reason_code = "strategy_backtest_run_failed"
        run.message = "StrategyBacktest 执行失败"
        run.error_message = f"{exc.__class__.__name__}: {exc}"
        run.finished_at_utc = timezone.now()
        run.save(update_fields=["status", "reason_code", "message", "error_message", "finished_at_utc", "updated_at_utc"])
        return ServiceResult(
            ResultStatus.FAILED,
            run.reason_code,
            run.message,
            run.trace_id,
            "strategy_backtest_celery_worker",
            {"strategy_backtest_run_id": run.id, "status": run.status, "error_message": run.error_message},
        )

    if result.status == ResultStatus.SUCCEEDED:
        run.status = StrategyBacktestRunStatus.SUCCEEDED
    elif result.status == ResultStatus.FAILED:
        run.status = StrategyBacktestRunStatus.FAILED
    else:
        run.status = StrategyBacktestRunStatus.BLOCKED
    run.reason_code = result.reason_code
    run.message = result.message
    _replace_period_results(run, result.data)
    run.result_summary = _compact_result_summary(result.data)
    run.finished_at_utc = timezone.now()
    run.save(update_fields=["status", "reason_code", "message", "result_summary", "finished_at_utc", "updated_at_utc"])
    return ServiceResult(
        result.status,
        result.reason_code,
        result.message,
        run.trace_id,
        "strategy_backtest_celery_worker",
        {"strategy_backtest_run_id": run.id, "status": run.status, **result.data},
    )


def _compact_result_summary(data: dict[str, Any]) -> dict[str, Any]:
    summary = dict(data)
    periods = data.get("periods")
    if isinstance(periods, list):
        summary["stored_period_count"] = len(periods)
        summary["first_period"] = periods[0] if periods else {}
        summary["last_period"] = periods[-1] if periods else {}
        summary.pop("periods", None)
    return summary


def _replace_period_results(run: StrategyBacktestRun, data: dict[str, Any]) -> None:
    periods = data.get("periods")
    run.period_results.all().delete()
    if not isinstance(periods, list) or not periods:
        return

    rows: list[StrategyBacktestPeriodResult] = []
    for index, period in enumerate(periods, start=1):
        if not isinstance(period, dict):
            continue
        analysis_close_time = period.get("analysis_close_time_utc")
        try:
            parsed_analysis_close_time = _parse_utc(str(analysis_close_time))
        except (TypeError, ValueError):
            continue
        rows.append(
            StrategyBacktestPeriodResult(
                strategy_backtest_run=run,
                period_index=index,
                analysis_close_time_utc=parsed_analysis_close_time,
                status=str(period.get("status", ""))[:80],
                reason_code=str(period.get("reason_code", ""))[:120],
                market_regime=str(period.get("market_regime", ""))[:120],
                selected_strategy=str(period.get("selected_strategy", ""))[:120],
                signal_direction=str(period.get("signal_direction", ""))[:40],
                previous_position_ratio=_optional_decimal(period.get("previous_position_ratio")),
                target_position_ratio=_optional_decimal(period.get("target_position_ratio")),
                position_change_ratio=_optional_decimal(period.get("position_change_ratio")),
                position_change_notional=_optional_decimal(period.get("position_change_notional")),
                position_ratio=_optional_decimal(period.get("position_ratio")),
                leverage=_optional_decimal(period.get("leverage")),
                effective_position_ratio=_optional_decimal(period.get("effective_position_ratio")),
                effective_position_change_ratio=_optional_decimal(period.get("effective_position_change_ratio")),
                effective_position_notional=_optional_decimal(period.get("effective_position_notional")),
                is_liquidated=bool(period.get("is_liquidated", False)),
                liquidation_price=_optional_decimal(period.get("liquidation_price")),
                liquidation_reason_code=str(period.get("liquidation_reason_code", ""))[:120],
                simulated_execution_price=_optional_decimal(period.get("open_price")),
                close_price=_optional_decimal(period.get("close_price")),
                kline_return_pct=_optional_decimal(period.get("kline_return_pct")),
                period_return_pct=_optional_decimal(period.get("period_return_pct")),
                fee=_optional_decimal(period.get("fee")),
                equity=_optional_decimal(period.get("equity")),
                drawdown_pct=_optional_decimal(period.get("drawdown_pct")),
            )
        )
    if rows:
        StrategyBacktestPeriodResult.objects.bulk_create(rows, batch_size=500)


def run_strategy_backtest(
    *,
    start_analysis_close_time_utc: datetime,
    end_analysis_close_time_utc: datetime,
    strategy_analysis_release_id: int | None = None,
    strategy_analysis_release_hash: str = "",
    lookback_4h_count: int = 500,
    lookback_1d_count: int = 500,
    initial_equity: Decimal = Decimal("10000"),
    fee_rate: Decimal = Decimal("0.0004"),
    leverage: Decimal = Decimal("1"),
    no_target_policy: str = NO_TARGET_POLICY_HOLD,
    business_request_prefix: str = "strategy-backtest",
    trace_id: str | None = None,
    trigger_source: str = "management_command",
    progress_callback: Any | None = None,
) -> ServiceResult:
    context = ensure_context(trace_id=trace_id, trigger_source=trigger_source)
    guard_error = _environment_guard()
    if guard_error:
        return ServiceResult(ResultStatus.BLOCKED, guard_error, "StrategyBacktest 只允许测试或开发环境运行", context.trace_id, trigger_source)

    request_error = _validate_request(
        start_analysis_close_time_utc=start_analysis_close_time_utc,
        end_analysis_close_time_utc=end_analysis_close_time_utc,
        initial_equity=initial_equity,
        fee_rate=fee_rate,
        leverage=leverage,
        no_target_policy=no_target_policy,
    )
    if request_error:
        return ServiceResult(ResultStatus.BLOCKED, request_error, "StrategyBacktest 请求参数无效", context.trace_id, trigger_source)

    analysis_close_times = _analysis_close_times(start_analysis_close_time_utc, end_analysis_close_time_utc)
    replay = replay_strategy_analysis_chain(
        analysis_close_times=analysis_close_times,
        strategy_analysis_release_id=strategy_analysis_release_id,
        strategy_analysis_release_hash=strategy_analysis_release_hash,
        lookback_4h_count=lookback_4h_count,
        lookback_1d_count=lookback_1d_count,
        business_request_prefix=business_request_prefix,
        trace_id=context.trace_id,
        trigger_source=trigger_source,
        progress_callback=progress_callback,
    )
    data = replay.data or {}
    simulation = _simulate_periods(
        periods=data.get("periods", []),
        initial_equity=initial_equity,
        fee_rate=fee_rate,
        leverage=leverage,
        no_target_policy=no_target_policy,
    )
    replay_blocked = replay.status != ResultStatus.SUCCEEDED
    blocked_count = int(data.get("blocked_count") or 0) + simulation["simulation_blocked_count"]
    status = ResultStatus.SUCCEEDED if not replay_blocked and blocked_count == 0 else ResultStatus.BLOCKED
    reason_code = (
        "strategy_backtest_completed_liquidated"
        if status == ResultStatus.SUCCEEDED and simulation.get("is_liquidated")
        else "strategy_backtest_completed"
        if status == ResultStatus.SUCCEEDED
        else "strategy_backtest_completed_with_blocked_period"
    )
    return ServiceResult(
        status,
        reason_code,
        "StrategyBacktest 收益回放完成",
        context.trace_id,
        trigger_source,
        {
            "release_id": data.get("release_id"),
            "release_hash": data.get("release_hash"),
            "start_analysis_close_time_utc": ensure_utc(start_analysis_close_time_utc).isoformat(),
            "end_analysis_close_time_utc": ensure_utc(end_analysis_close_time_utc).isoformat(),
            "period_count": len(analysis_close_times),
            "replay_status": str(replay.status),
            "replay_reason_code": replay.reason_code,
            **simulation,
        },
    )


def _build_run_progress_callback(strategy_backtest_run_id: int):
    def progress_callback(completed_count: int, total_count: int, period_result: dict[str, Any]) -> None:
        analysis_close_time = period_result.get("analysis_close_time_utc")
        parsed_time = None
        if isinstance(analysis_close_time, str) and analysis_close_time:
            try:
                parsed_time = _parse_utc(analysis_close_time)
            except ValueError:
                parsed_time = None
        now = timezone.now()
        StrategyBacktestRun.objects.filter(id=strategy_backtest_run_id).update(
            progress_total_periods=total_count,
            progress_completed_periods=completed_count,
            progress_current_analysis_close_time_utc=parsed_time,
            progress_last_status=str(period_result.get("status", ""))[:80],
            progress_last_reason_code=str(period_result.get("reason_code", ""))[:120],
            progress_updated_at_utc=now,
            updated_at_utc=now,
        )

    return progress_callback


def _environment_guard() -> str:
    if bool(getattr(settings, "PRODUCTION", False)):
        return "strategy_backtest_production_blocked"
    if bool(getattr(settings, "DEPLOYMENT_REAL_TRADING_ENABLED", False)):
        return "strategy_backtest_real_trading_deployment_blocked"
    return ""


def _validate_request(
    *,
    start_analysis_close_time_utc: datetime,
    end_analysis_close_time_utc: datetime,
    initial_equity: Decimal,
    fee_rate: Decimal,
    leverage: Decimal,
    no_target_policy: str,
) -> str:
    start = ensure_utc(start_analysis_close_time_utc)
    end = ensure_utc(end_analysis_close_time_utc)
    if start > end:
        return "strategy_backtest_invalid_time_range"
    if not is_timeframe_boundary(start, TIMEFRAME_4H) or not is_timeframe_boundary(end, TIMEFRAME_4H):
        return "strategy_backtest_time_not_4h_boundary"
    if initial_equity <= 0:
        return "strategy_backtest_initial_equity_invalid"
    if fee_rate < 0:
        return "strategy_backtest_fee_rate_invalid"
    if not leverage.is_finite() or leverage <= 0:
        return "strategy_backtest_leverage_invalid"
    if no_target_policy not in {NO_TARGET_POLICY_HOLD, NO_TARGET_POLICY_FLAT}:
        return "strategy_backtest_no_target_policy_invalid"
    return ""


def _analysis_close_times(start: datetime, end: datetime) -> list[datetime]:
    current = ensure_utc(start)
    finish = ensure_utc(end)
    step = timeframe_delta(TIMEFRAME_4H)
    values: list[datetime] = []
    while current <= finish:
        values.append(current)
        current += step
    return values


def _simulate_periods(
    *,
    periods: list[dict[str, Any]],
    initial_equity: Decimal,
    fee_rate: Decimal,
    leverage: Decimal,
    no_target_policy: str,
) -> dict[str, Any]:
    domain = configured_collection_domain()
    equity = initial_equity
    peak_equity = initial_equity
    position_ratio = Decimal("0")
    total_fee = Decimal("0")
    turnover_ratio = Decimal("0")
    max_drawdown = Decimal("0")
    trade_count = 0
    completed_count = 0
    simulation_blocked_count = 0
    period_rows: list[dict[str, Any]] = []
    strategy_counts: dict[str, int] = {}
    benchmark_open: Decimal | None = None
    benchmark_close: Decimal | None = None
    is_liquidated = False
    liquidation_period_index = 0
    liquidation_analysis_close_time_utc = ""
    liquidation_price: Decimal | None = None
    liquidation_reason_code = ""

    for period in periods:
        summary = period.get("summary") or {}
        analysis_close_time = _parse_utc(period["analysis_close_time_utc"])
        if period.get("status") not in REPLAY_SIMULATABLE_STATUSES:
            simulation_blocked_count += 1
            period_rows.append(
                _blocked_period_row(
                    period,
                    position_ratio,
                    equity,
                    leverage,
                    f"replay_period_not_simulatable:{period.get('stopped_step') or period.get('reason_code') or 'unknown'}",
                )
            )
            continue
        kline = _execution_kline(domain=domain, analysis_close_time=analysis_close_time)
        if kline is None:
            simulation_blocked_count += 1
            period_rows.append(_blocked_period_row(period, position_ratio, equity, leverage, "execution_kline_missing"))
            continue
        if kline.open_price <= 0:
            simulation_blocked_count += 1
            period_rows.append(_blocked_period_row(period, position_ratio, equity, leverage, "execution_kline_open_price_invalid"))
            continue
        if benchmark_open is None:
            benchmark_open = kline.open_price
        benchmark_close = kline.close_price

        route = summary.get("strategy_routing") or {}
        selected_strategy = route.get("selected_strategy") or ""
        if selected_strategy:
            strategy_counts[selected_strategy] = strategy_counts.get(selected_strategy, 0) + 1

        previous_position_ratio = position_ratio
        target_ratio = _target_position(summary, current_position=previous_position_ratio, no_target_policy=no_target_policy)
        position_change = target_ratio - previous_position_ratio
        effective_position_ratio = target_ratio * leverage
        effective_position_change = position_change * leverage
        position_change_notional = effective_position_change * equity
        effective_position_notional = effective_position_ratio * equity
        fee = abs(effective_position_change) * equity * fee_rate
        if effective_position_change:
            trade_count += 1
        turnover_ratio += abs(effective_position_change)
        total_fee += fee
        equity_after_fee = equity - fee
        kline_return = (kline.close_price - kline.open_price) / kline.open_price
        strategy_period_return = effective_position_ratio * kline_return
        liquidation_event = _liquidation_event(
            kline=kline,
            effective_position_ratio=effective_position_ratio,
            effective_position_notional=effective_position_notional,
            equity_after_fee=equity_after_fee,
        )
        if liquidation_event:
            equity = Decimal("0")
            position_ratio = Decimal("0")
            drawdown = Decimal("1")
            max_drawdown = Decimal("1")
            completed_count += 1
            is_liquidated = True
            liquidation_period_index = completed_count
            liquidation_analysis_close_time_utc = period.get("analysis_close_time_utc", "")
            liquidation_price = liquidation_event["liquidation_price"]
            liquidation_reason_code = liquidation_event["reason_code"]
            period_rows.append(
                _period_row(
                    period=period,
                    summary=summary,
                    kline=kline,
                    previous_position_ratio=previous_position_ratio,
                    target_ratio=target_ratio,
                    position_change=position_change,
                    position_change_notional=position_change_notional,
                    position_ratio=position_ratio,
                    leverage=leverage,
                    effective_position_ratio=effective_position_ratio,
                    effective_position_change=effective_position_change,
                    effective_position_notional=effective_position_notional,
                    kline_return=kline_return,
                    strategy_period_return=Decimal("-1"),
                    fee=fee,
                    equity=equity,
                    drawdown=drawdown,
                    status="liquidated",
                    reason_code=liquidation_reason_code,
                    is_liquidated=True,
                    liquidation_price=liquidation_price,
                    liquidation_reason_code=liquidation_reason_code,
                )
            )
            break

        equity = equity_after_fee * (Decimal("1") + strategy_period_return)
        if equity <= 0:
            equity = Decimal("0")
            position_ratio = Decimal("0")
            drawdown = Decimal("1")
            max_drawdown = Decimal("1")
            completed_count += 1
            is_liquidated = True
            liquidation_period_index = completed_count
            liquidation_analysis_close_time_utc = period.get("analysis_close_time_utc", "")
            liquidation_price = kline.close_price
            liquidation_reason_code = "liquidation_by_equity_depletion"
            period_rows.append(
                _period_row(
                    period=period,
                    summary=summary,
                    kline=kline,
                    previous_position_ratio=previous_position_ratio,
                    target_ratio=target_ratio,
                    position_change=position_change,
                    position_change_notional=position_change_notional,
                    position_ratio=position_ratio,
                    leverage=leverage,
                    effective_position_ratio=effective_position_ratio,
                    effective_position_change=effective_position_change,
                    effective_position_notional=effective_position_notional,
                    kline_return=kline_return,
                    strategy_period_return=Decimal("-1"),
                    fee=fee,
                    equity=equity,
                    drawdown=drawdown,
                    status="liquidated",
                    reason_code=liquidation_reason_code,
                    is_liquidated=True,
                    liquidation_price=liquidation_price,
                    liquidation_reason_code=liquidation_reason_code,
                )
            )
            break

        position_ratio = target_ratio
        if equity > peak_equity:
            peak_equity = equity
        drawdown = (peak_equity - equity) / peak_equity if peak_equity > 0 else Decimal("0")
        if drawdown > max_drawdown:
            max_drawdown = drawdown
        completed_count += 1
        period_rows.append(
            _period_row(
                period=period,
                summary=summary,
                kline=kline,
                previous_position_ratio=previous_position_ratio,
                target_ratio=target_ratio,
                position_change=position_change,
                position_change_notional=position_change_notional,
                position_ratio=position_ratio,
                leverage=leverage,
                effective_position_ratio=effective_position_ratio,
                effective_position_change=effective_position_change,
                effective_position_notional=effective_position_notional,
                kline_return=kline_return,
                strategy_period_return=strategy_period_return,
                fee=fee,
                equity=equity,
                drawdown=drawdown,
            )
        )

    benchmark_return = (
        (benchmark_close - benchmark_open) / benchmark_open
        if benchmark_open is not None and benchmark_close is not None and benchmark_open > 0
        else Decimal("0")
    )
    return {
        "initial_equity": _decimal_text(initial_equity),
        "leverage": _decimal_text(leverage),
        "final_equity": _decimal_text(equity),
        "total_return_pct": _decimal_text((equity - initial_equity) / initial_equity),
        "max_drawdown_pct": _decimal_text(max_drawdown),
        "trade_count": trade_count,
        "turnover_ratio": _decimal_text(turnover_ratio),
        "total_fee": _decimal_text(total_fee),
        "benchmark_buy_hold_return_pct": _decimal_text(benchmark_return),
        "completed_count": completed_count,
        "simulation_blocked_count": simulation_blocked_count,
        "is_liquidated": is_liquidated,
        "liquidation_period_index": liquidation_period_index,
        "liquidation_analysis_close_time_utc": liquidation_analysis_close_time_utc,
        "liquidation_price": _decimal_text(liquidation_price),
        "liquidation_reason_code": liquidation_reason_code,
        "strategy_counts": strategy_counts,
        "periods": period_rows,
    }


def _execution_kline(*, domain, analysis_close_time: datetime) -> Kline | None:
    return Kline.objects.filter(
        exchange=domain.exchange,
        market_type=domain.market_type,
        symbol=domain.symbol,
        timeframe=TIMEFRAME_4H,
        open_time_utc=analysis_close_time,
    ).first()


def _target_position(summary: dict[str, Any], *, current_position: Decimal, no_target_policy: str) -> Decimal:
    decision = summary.get("decision_snapshot") or {}
    target_text = decision.get("target_position_ratio")
    if target_text not in (None, ""):
        try:
            return Decimal(str(target_text))
        except InvalidOperation:
            return current_position
    if no_target_policy == NO_TARGET_POLICY_FLAT:
        return Decimal("0")
    return current_position


def _liquidation_event(
    *,
    kline: Kline,
    effective_position_ratio: Decimal,
    effective_position_notional: Decimal,
    equity_after_fee: Decimal,
) -> dict[str, Any] | None:
    if effective_position_ratio == 0:
        return None
    abs_notional = abs(effective_position_notional)
    if abs_notional <= 0:
        return None
    if equity_after_fee <= 0:
        return {"reason_code": "liquidation_by_fee", "liquidation_price": kline.open_price}

    adverse_move_to_zero = equity_after_fee / abs_notional
    if adverse_move_to_zero <= 0:
        return {"reason_code": "liquidation_by_fee", "liquidation_price": kline.open_price}

    if effective_position_ratio > 0:
        liquidation_price = kline.open_price * (Decimal("1") - adverse_move_to_zero)
        if liquidation_price > 0 and kline.low_price <= liquidation_price:
            return {"reason_code": "long_liquidation_intraperiod", "liquidation_price": liquidation_price}
        return None

    liquidation_price = kline.open_price * (Decimal("1") + adverse_move_to_zero)
    if kline.high_price >= liquidation_price:
        return {"reason_code": "short_liquidation_intraperiod", "liquidation_price": liquidation_price}
    return None


def _period_row(
    *,
    period: dict[str, Any],
    summary: dict[str, Any],
    kline: Kline,
    previous_position_ratio: Decimal,
    target_ratio: Decimal,
    position_change: Decimal,
    position_change_notional: Decimal,
    position_ratio: Decimal,
    leverage: Decimal,
    effective_position_ratio: Decimal,
    effective_position_change: Decimal,
    effective_position_notional: Decimal,
    kline_return: Decimal,
    strategy_period_return: Decimal,
    fee: Decimal,
    equity: Decimal,
    drawdown: Decimal,
    status: str | None = None,
    reason_code: str | None = None,
    is_liquidated: bool = False,
    liquidation_price: Decimal | None = None,
    liquidation_reason_code: str = "",
) -> dict[str, Any]:
    route = summary.get("strategy_routing") or {}
    signal = summary.get("strategy_signal") or {}
    regime = summary.get("market_regime") or {}
    return {
        "analysis_close_time_utc": period.get("analysis_close_time_utc"),
        "status": status or period.get("status"),
        "reason_code": reason_code or period.get("reason_code"),
        "market_regime": regime.get("regime_code", ""),
        "selected_strategy": route.get("selected_strategy", ""),
        "signal_direction": signal.get("direction", ""),
        "previous_position_ratio": _decimal_text(previous_position_ratio),
        "target_position_ratio": _decimal_text(target_ratio),
        "position_change_ratio": _decimal_text(position_change),
        "position_change_notional": _decimal_text(position_change_notional),
        "position_ratio": _decimal_text(position_ratio),
        "leverage": _decimal_text(leverage),
        "effective_position_ratio": _decimal_text(effective_position_ratio),
        "effective_position_change_ratio": _decimal_text(effective_position_change),
        "effective_position_notional": _decimal_text(effective_position_notional),
        "is_liquidated": is_liquidated,
        "liquidation_price": _decimal_text(liquidation_price),
        "liquidation_reason_code": liquidation_reason_code,
        "open_price": _decimal_text(kline.open_price),
        "close_price": _decimal_text(kline.close_price),
        "kline_return_pct": _decimal_text(kline_return),
        "period_return_pct": _decimal_text(strategy_period_return),
        "fee": _decimal_text(fee),
        "equity": _decimal_text(equity),
        "drawdown_pct": _decimal_text(drawdown),
    }


def _blocked_period_row(
    period: dict[str, Any],
    position_ratio: Decimal,
    equity: Decimal,
    leverage: Decimal,
    reason_code: str,
) -> dict[str, Any]:
    effective_position_ratio = position_ratio * leverage
    return {
        "analysis_close_time_utc": period.get("analysis_close_time_utc"),
        "status": "blocked",
        "reason_code": reason_code,
        "previous_position_ratio": _decimal_text(position_ratio),
        "target_position_ratio": _decimal_text(position_ratio),
        "position_change_ratio": "0",
        "position_change_notional": "0",
        "position_ratio": _decimal_text(position_ratio),
        "leverage": _decimal_text(leverage),
        "effective_position_ratio": _decimal_text(effective_position_ratio),
        "effective_position_change_ratio": "0",
        "effective_position_notional": _decimal_text(effective_position_ratio * equity),
        "is_liquidated": False,
        "liquidation_price": "",
        "liquidation_reason_code": "",
        "equity": _decimal_text(equity),
    }


def _parse_utc(value: str) -> datetime:
    return ensure_utc(datetime.fromisoformat(value.replace("Z", "+00:00")))


def _decimal_text(value: Decimal | None) -> str:
    if value is None:
        return ""
    normalized = value.normalize()
    if normalized == 0:
        return "0"
    return format(normalized, "f")


def _optional_decimal(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
