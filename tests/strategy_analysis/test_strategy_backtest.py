from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from io import StringIO
from types import SimpleNamespace
from typing import Any

import pytest
from django.core.management import call_command

from apps.foundation.results import ResultStatus, ServiceResult
from apps.market_data.domain import DATA_SOURCE_BINANCE_REST, TIMEFRAME_4H, configured_collection_domain
from apps.market_data.models import Kline
from apps.strategy_analysis.models import (
    StrategyAnalysisRelease,
    StrategyBacktestPeriodResult,
    StrategyBacktestRun,
    StrategyBacktestRunStatus,
)
from apps.strategy_analysis.services.backtest import (
    create_strategy_backtest_run,
    execute_strategy_backtest_run,
    run_strategy_backtest,
)


@pytest.mark.django_db
def test_strategy_backtest_simulates_short_profit_and_holds_no_target(monkeypatch) -> None:
    first = datetime(2026, 2, 20, 0, tzinfo=UTC)
    second = datetime(2026, 2, 20, 4, tzinfo=UTC)
    _create_4h_kline(first, "100", "90")
    _create_4h_kline(second, "90", "81")

    def fake_replay_strategy_analysis_chain(**kwargs):
        return ServiceResult(
            ResultStatus.SUCCEEDED,
            "strategy_analysis_replay_completed",
            "ok",
            kwargs["trace_id"],
            kwargs["trigger_source"],
            {
                "release_id": 10,
                "release_hash": "release-hash",
                "blocked_count": 0,
                "periods": [
                    _completed_period(first, target_position_ratio="-0.5", selected_strategy="short_trend_following"),
                    _completed_period(second, target_position_ratio="", selected_strategy=""),
                ],
            },
        )

    monkeypatch.setattr(
        "apps.strategy_analysis.services.backtest.replay_strategy_analysis_chain",
        fake_replay_strategy_analysis_chain,
    )

    result = run_strategy_backtest(
        start_analysis_close_time_utc=first,
        end_analysis_close_time_utc=second,
        initial_equity=Decimal("1000"),
        fee_rate=Decimal("0"),
        trace_id="trace-backtest-short",
        trigger_source="test",
    )

    assert result.status == ResultStatus.SUCCEEDED
    assert result.reason_code == "strategy_backtest_completed"
    assert result.data["completed_count"] == 2
    assert result.data["simulation_blocked_count"] == 0
    assert result.data["trade_count"] == 1
    assert result.data["final_equity"] == "1102.5"
    assert result.data["total_return_pct"] == "0.1025"
    assert result.data["periods"][0]["previous_position_ratio"] == "0"
    assert result.data["periods"][0]["position_change_ratio"] == "-0.5"
    assert result.data["periods"][0]["position_change_notional"] == "-500"
    assert result.data["periods"][0]["effective_position_ratio"] == "-0.5"
    assert result.data["periods"][1]["target_position_ratio"] == "-0.5"


@pytest.mark.django_db
def test_strategy_backtest_applies_leverage_to_effective_exposure(monkeypatch) -> None:
    analysis_time = datetime(2026, 2, 20, 0, tzinfo=UTC)
    _create_4h_kline(analysis_time, "100", "90")

    def fake_replay_strategy_analysis_chain(**kwargs):
        return ServiceResult(
            ResultStatus.SUCCEEDED,
            "strategy_analysis_replay_completed",
            "ok",
            kwargs["trace_id"],
            kwargs["trigger_source"],
            {
                "release_id": 10,
                "release_hash": "release-hash",
                "blocked_count": 0,
                "periods": [_completed_period(analysis_time, target_position_ratio="-0.5", selected_strategy="short_trend_following")],
            },
        )

    monkeypatch.setattr(
        "apps.strategy_analysis.services.backtest.replay_strategy_analysis_chain",
        fake_replay_strategy_analysis_chain,
    )

    result = run_strategy_backtest(
        start_analysis_close_time_utc=analysis_time,
        end_analysis_close_time_utc=analysis_time,
        initial_equity=Decimal("1000"),
        fee_rate=Decimal("0"),
        leverage=Decimal("2"),
        trace_id="trace-backtest-leverage",
        trigger_source="test",
    )

    assert result.status == ResultStatus.SUCCEEDED
    assert result.data["leverage"] == "2"
    assert result.data["final_equity"] == "1100"
    assert result.data["total_return_pct"] == "0.1"
    assert result.data["turnover_ratio"] == "1"
    assert result.data["periods"][0]["target_position_ratio"] == "-0.5"
    assert result.data["periods"][0]["effective_position_ratio"] == "-1"
    assert result.data["periods"][0]["effective_position_change_ratio"] == "-1"
    assert result.data["periods"][0]["position_change_notional"] == "-1000"
    assert result.data["periods"][0]["effective_position_notional"] == "-1000"


@pytest.mark.django_db
def test_strategy_backtest_marks_liquidation_and_stops_following_periods(monkeypatch) -> None:
    first = datetime(2026, 2, 20, 0, tzinfo=UTC)
    second = datetime(2026, 2, 20, 4, tzinfo=UTC)
    _create_4h_kline(first, "100", "95", high_price="101", low_price="89")
    _create_4h_kline(second, "95", "120")

    def fake_replay_strategy_analysis_chain(**kwargs):
        return ServiceResult(
            ResultStatus.SUCCEEDED,
            "strategy_analysis_replay_completed",
            "ok",
            kwargs["trace_id"],
            kwargs["trigger_source"],
            {
                "release_id": 10,
                "release_hash": "release-hash",
                "blocked_count": 0,
                "periods": [
                    _completed_period(first, target_position_ratio="1", selected_strategy="long_trend_following"),
                    _completed_period(second, target_position_ratio="1", selected_strategy="long_trend_following"),
                ],
            },
        )

    monkeypatch.setattr(
        "apps.strategy_analysis.services.backtest.replay_strategy_analysis_chain",
        fake_replay_strategy_analysis_chain,
    )

    result = run_strategy_backtest(
        start_analysis_close_time_utc=first,
        end_analysis_close_time_utc=second,
        initial_equity=Decimal("1000"),
        fee_rate=Decimal("0"),
        leverage=Decimal("10"),
        trace_id="trace-backtest-liquidation",
        trigger_source="test",
    )

    assert result.status == ResultStatus.SUCCEEDED
    assert result.reason_code == "strategy_backtest_completed_liquidated"
    assert result.data["is_liquidated"] is True
    assert result.data["liquidation_period_index"] == 1
    assert result.data["liquidation_analysis_close_time_utc"] == first.isoformat()
    assert result.data["liquidation_price"] == "90"
    assert result.data["liquidation_reason_code"] == "long_liquidation_intraperiod"
    assert result.data["completed_count"] == 1
    assert result.data["final_equity"] == "0"
    assert result.data["total_return_pct"] == "-1"
    assert len(result.data["periods"]) == 1
    assert result.data["periods"][0]["status"] == "liquidated"
    assert result.data["periods"][0]["is_liquidated"] is True
    assert result.data["periods"][0]["liquidation_price"] == "90"


@pytest.mark.django_db
def test_strategy_backtest_does_not_simulate_blocked_replay_period(monkeypatch) -> None:
    analysis_time = datetime(2026, 2, 20, 0, tzinfo=UTC)
    _create_4h_kline(analysis_time, "100", "90")

    def fake_replay_strategy_analysis_chain(**kwargs):
        return ServiceResult(
            ResultStatus.BLOCKED,
            "strategy_analysis_replay_has_blocked_period",
            "blocked",
            kwargs["trace_id"],
            kwargs["trigger_source"],
            {
                "release_id": 10,
                "release_hash": "release-hash",
                "blocked_count": 1,
                "periods": [
                    {
                        "analysis_close_time_utc": analysis_time.isoformat(),
                        "status": "blocked",
                        "stopped_step": "data_quality_4h",
                        "reason_code": "quality_issues_found",
                    }
                ],
            },
        )

    monkeypatch.setattr(
        "apps.strategy_analysis.services.backtest.replay_strategy_analysis_chain",
        fake_replay_strategy_analysis_chain,
    )

    result = run_strategy_backtest(
        start_analysis_close_time_utc=analysis_time,
        end_analysis_close_time_utc=analysis_time,
        initial_equity=Decimal("1000"),
        fee_rate=Decimal("0"),
        trace_id="trace-backtest-blocked-period",
        trigger_source="test",
    )

    assert result.status == ResultStatus.BLOCKED
    assert result.data["completed_count"] == 0
    assert result.data["simulation_blocked_count"] == 1
    assert result.data["periods"][0]["reason_code"] == "replay_period_not_simulatable:data_quality_4h"


def test_strategy_backtest_blocks_production(settings, monkeypatch) -> None:
    def fail_replay_strategy_analysis_chain(**kwargs):
        pytest.fail("生产环境拦截后不应调用 replay")

    monkeypatch.setattr(
        "apps.strategy_analysis.services.backtest.replay_strategy_analysis_chain",
        fail_replay_strategy_analysis_chain,
    )
    settings.PRODUCTION = True

    result = run_strategy_backtest(
        start_analysis_close_time_utc=datetime(2026, 2, 20, 0, tzinfo=UTC),
        end_analysis_close_time_utc=datetime(2026, 2, 20, 0, tzinfo=UTC),
        trace_id="trace-backtest-production-block",
        trigger_source="test",
    )

    assert result.status == ResultStatus.BLOCKED
    assert result.reason_code == "strategy_backtest_production_blocked"


@pytest.mark.django_db
def test_strategy_backtest_missing_execution_kline_marks_blocked(monkeypatch) -> None:
    analysis_time = datetime(2026, 2, 20, 0, tzinfo=UTC)

    def fake_replay_strategy_analysis_chain(**kwargs):
        return ServiceResult(
            ResultStatus.SUCCEEDED,
            "strategy_analysis_replay_completed",
            "ok",
            kwargs["trace_id"],
            kwargs["trigger_source"],
            {
                "release_id": 10,
                "release_hash": "release-hash",
                "blocked_count": 0,
                "periods": [_completed_period(analysis_time, target_position_ratio="0.5")],
            },
        )

    monkeypatch.setattr(
        "apps.strategy_analysis.services.backtest.replay_strategy_analysis_chain",
        fake_replay_strategy_analysis_chain,
    )

    result = run_strategy_backtest(
        start_analysis_close_time_utc=analysis_time,
        end_analysis_close_time_utc=analysis_time,
        initial_equity=Decimal("1000"),
        fee_rate=Decimal("0"),
        trace_id="trace-backtest-missing-kline",
        trigger_source="test",
    )

    assert result.status == ResultStatus.BLOCKED
    assert result.data["simulation_blocked_count"] == 1
    assert result.data["periods"][0]["reason_code"] == "execution_kline_missing"


@pytest.mark.django_db
def test_create_strategy_backtest_run_persists_queued_run_and_enqueues_task(monkeypatch) -> None:
    release = StrategyAnalysisRelease.objects.create(release_code="backtest-release", release_hash="release-hash")
    captured: dict[str, Any] = {}

    def fake_delay(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(id="celery-task-id")

    monkeypatch.setattr("apps.strategy_analysis.tasks.execute_strategy_backtest_run_task.delay", fake_delay)

    result = create_strategy_backtest_run(
        start_analysis_close_time_utc=datetime(2026, 2, 20, 0, tzinfo=UTC),
        end_analysis_close_time_utc=datetime(2026, 2, 20, 4, tzinfo=UTC),
        strategy_analysis_release_id=release.id,
        strategy_analysis_release_hash="",
        initial_equity=Decimal("1000"),
        fee_rate=Decimal("0.0002"),
        leverage=Decimal("3"),
        requested_by="tester",
        trace_id="trace-create-backtest-run",
        trigger_source="test",
    )

    assert result.status == ResultStatus.SUCCEEDED
    assert result.reason_code == "strategy_backtest_run_created"
    run = StrategyBacktestRun.objects.get(id=result.data["strategy_backtest_run_id"])
    assert run.status == StrategyBacktestRunStatus.QUEUED
    assert run.strategy_analysis_release_id == release.id
    assert run.strategy_analysis_release_hash == "release-hash"
    assert run.leverage == Decimal("3")
    assert run.requested_by == "tester"
    assert run.celery_task_id == "celery-task-id"
    assert captured["strategy_backtest_run_id"] == run.id


@pytest.mark.django_db
def test_execute_strategy_backtest_run_updates_result_summary(monkeypatch) -> None:
    release = StrategyAnalysisRelease.objects.create(release_code="execute-backtest-release", release_hash="release-hash")
    run = StrategyBacktestRun.objects.create(
        run_key="execute-backtest-run",
        status=StrategyBacktestRunStatus.QUEUED,
        strategy_analysis_release=release,
        strategy_analysis_release_hash=release.release_hash,
        start_analysis_close_time_utc=datetime(2026, 2, 20, 0, tzinfo=UTC),
        end_analysis_close_time_utc=datetime(2026, 2, 20, 0, tzinfo=UTC),
        initial_equity=Decimal("1000"),
        fee_rate=Decimal("0"),
        leverage=Decimal("2"),
        business_request_prefix="execute-backtest",
        trace_id="trace-execute-backtest-run",
        trigger_source="test",
    )

    captured: dict[str, Any] = {}

    def fake_run_strategy_backtest(**kwargs):
        captured.update(kwargs)
        kwargs["progress_callback"](
            1,
            1,
            {
                "analysis_close_time_utc": "2026-02-20T00:00:00+00:00",
                "status": "completed",
                "reason_code": "decision_snapshot_created",
            },
        )
        return ServiceResult(
            ResultStatus.SUCCEEDED,
            "strategy_backtest_completed",
            "ok",
            kwargs["trace_id"],
            kwargs["trigger_source"],
            {
                "final_equity": "1010",
                "completed_count": 1,
                "periods": [
                    {
                        "analysis_close_time_utc": "2026-02-20T00:00:00+00:00",
                        "status": "completed",
                        "reason_code": "decision_snapshot_created",
                        "market_regime": "bearish_trend_continuation",
                        "selected_strategy": "short_trend_following",
                        "signal_direction": "bearish",
                        "previous_position_ratio": "0",
                        "target_position_ratio": "-0.5",
                        "position_change_ratio": "-0.5",
                        "position_change_notional": "-1000",
                        "position_ratio": "-0.5",
                        "leverage": "2",
                        "effective_position_ratio": "-1",
                        "effective_position_change_ratio": "-1",
                        "effective_position_notional": "-1000",
                        "is_liquidated": True,
                        "liquidation_price": "90",
                        "liquidation_reason_code": "long_liquidation_intraperiod",
                        "open_price": "100",
                        "close_price": "90",
                        "kline_return_pct": "-0.1",
                        "period_return_pct": "0.05",
                        "fee": "0",
                        "equity": "1050",
                        "drawdown_pct": "0",
                    }
                ],
            },
        )

    monkeypatch.setattr("apps.strategy_analysis.services.backtest.run_strategy_backtest", fake_run_strategy_backtest)

    result = execute_strategy_backtest_run(strategy_backtest_run_id=run.id)

    assert result.status == ResultStatus.SUCCEEDED
    run.refresh_from_db()
    assert run.status == StrategyBacktestRunStatus.SUCCEEDED
    assert run.reason_code == "strategy_backtest_completed"
    assert run.result_summary["final_equity"] == "1010"
    assert run.progress_total_periods == 1
    assert run.progress_completed_periods == 1
    assert run.progress_last_status == "completed"
    assert run.progress_last_reason_code == "decision_snapshot_created"
    assert run.progress_current_analysis_close_time_utc == datetime(2026, 2, 20, 0, tzinfo=UTC)
    assert run.progress_updated_at_utc is not None
    assert run.started_at_utc is not None
    assert run.finished_at_utc is not None
    assert captured["leverage"] == Decimal("2")
    period = StrategyBacktestPeriodResult.objects.get(strategy_backtest_run=run, period_index=1)
    assert period.selected_strategy == "short_trend_following"
    assert period.previous_position_ratio == Decimal("0")
    assert period.target_position_ratio == Decimal("-0.5")
    assert period.position_change_ratio == Decimal("-0.5")
    assert period.position_change_notional == Decimal("-1000")
    assert period.leverage == Decimal("2")
    assert period.effective_position_ratio == Decimal("-1")
    assert period.effective_position_change_ratio == Decimal("-1")
    assert period.effective_position_notional == Decimal("-1000")
    assert period.is_liquidated is True
    assert period.liquidation_price == Decimal("90")
    assert period.liquidation_reason_code == "long_liquidation_intraperiod"
    assert period.simulated_execution_price == Decimal("100")
    assert period.close_price == Decimal("90")


def test_run_strategy_backtest_command_outputs_summary_json(monkeypatch) -> None:
    captured: dict[str, Any] = {}

    def fake_run_strategy_backtest(**kwargs):
        captured.update(kwargs)
        return ServiceResult(
            ResultStatus.SUCCEEDED,
            "strategy_backtest_completed",
            "ok",
            kwargs["trace_id"],
            kwargs["trigger_source"],
            {
                "release_id": kwargs["strategy_analysis_release_id"],
                "release_hash": kwargs["strategy_analysis_release_hash"],
                "period_count": 1,
                "initial_equity": "1000",
                "leverage": "2",
                "final_equity": "1010",
                "total_return_pct": "0.01",
                "max_drawdown_pct": "0",
                "trade_count": 1,
                "turnover_ratio": "0.5",
                "total_fee": "0.2",
                "benchmark_buy_hold_return_pct": "0.03",
                "completed_count": 1,
                "simulation_blocked_count": 0,
                "is_liquidated": False,
                "liquidation_period_index": 0,
                "liquidation_analysis_close_time_utc": "",
                "liquidation_price": "",
                "liquidation_reason_code": "",
                "strategy_counts": {"short_trend_following": 1},
                "periods": [{"analysis_close_time_utc": "2026-02-20T00:00:00+00:00"}],
            },
        )

    monkeypatch.setattr(
        "apps.strategy_analysis.management.commands.run_strategy_backtest.run_strategy_backtest",
        fake_run_strategy_backtest,
    )

    out = StringIO()
    call_command(
        "run_strategy_backtest",
        start_analysis_close_time_utc="2026-02-20T00:00:00+00:00",
        end_analysis_close_time_utc="2026-02-20T00:00:00+00:00",
        strategy_analysis_release_id=10,
        strategy_analysis_release_hash="release-hash",
        initial_equity="1000",
        fee_rate="0.0002",
        leverage="2",
        trace_id="trace-backtest-command",
        stdout=out,
    )

    payload = json.loads(out.getvalue())
    assert payload["reason_code"] == "strategy_backtest_completed"
    assert payload["data"]["final_equity"] == "1010"
    assert payload["data"]["leverage"] == "2"
    assert payload["data"]["first_period"]["analysis_close_time_utc"] == "2026-02-20T00:00:00+00:00"
    assert captured["strategy_analysis_release_id"] == 10
    assert captured["initial_equity"] == Decimal("1000")
    assert captured["fee_rate"] == Decimal("0.0002")
    assert captured["leverage"] == Decimal("2")


def _completed_period(
    analysis_time: datetime,
    *,
    target_position_ratio: str,
    selected_strategy: str = "short_trend_following",
) -> dict[str, Any]:
    decision_snapshot: dict[str, str] = {}
    if target_position_ratio:
        decision_snapshot["target_position_ratio"] = target_position_ratio
    return {
        "analysis_close_time_utc": analysis_time.isoformat(),
        "status": "completed" if target_position_ratio else "completed_no_strategy",
        "reason_code": "decision_snapshot_created" if target_position_ratio else "strategy_route_decision_created",
        "summary": {
            "market_regime": {"regime_code": "bearish_trend_continuation"},
            "strategy_routing": {"selected_strategy": selected_strategy},
            "strategy_signal": {"direction": "bearish"},
            "decision_snapshot": decision_snapshot,
        },
    }


def _create_4h_kline(
    open_time_utc: datetime,
    open_price: str,
    close_price: str,
    *,
    high_price: str | None = None,
    low_price: str | None = None,
) -> Kline:
    domain = configured_collection_domain()
    open_decimal = Decimal(open_price)
    close_decimal = Decimal(close_price)
    high = Decimal(high_price) if high_price is not None else max(open_decimal, close_decimal)
    low = Decimal(low_price) if low_price is not None else min(open_decimal, close_decimal)
    return Kline.objects.create(
        exchange=domain.exchange,
        market_type=domain.market_type,
        symbol=domain.symbol,
        timeframe=TIMEFRAME_4H,
        open_time_utc=open_time_utc,
        close_time_utc=open_time_utc + timedelta(hours=4),
        open_price=open_decimal,
        high_price=high,
        low_price=low,
        close_price=close_decimal,
        volume=Decimal("100"),
        quote_volume=Decimal("10000"),
        trade_count=100,
        data_source=DATA_SOURCE_BINANCE_REST,
    )
