from __future__ import annotations

import json
from datetime import UTC, datetime
from io import StringIO
from typing import Any

import pytest
from django.core.management import call_command

from apps.foundation.results import ResultStatus, ServiceResult
from apps.strategy_analysis.models import ReleaseApprovalStatus, StrategyAnalysisRelease
from apps.strategy_analysis.services.replay import replay_strategy_analysis_chain


def test_replay_strategy_analysis_chain_command_parses_explicit_times(monkeypatch) -> None:
    captured: dict[str, Any] = {}

    def fake_replay_strategy_analysis_chain(**kwargs):
        captured.update(kwargs)
        return ServiceResult(
            ResultStatus.SUCCEEDED,
            "strategy_analysis_replay_completed",
            "ok",
            kwargs["trace_id"],
            kwargs["trigger_source"],
            {"period_count": len(kwargs["analysis_close_times"])},
        )

    monkeypatch.setattr(
        "apps.strategy_analysis.management.commands.replay_strategy_analysis_chain.replay_strategy_analysis_chain",
        fake_replay_strategy_analysis_chain,
    )

    out = StringIO()
    call_command(
        "replay_strategy_analysis_chain",
        analysis_close_times="2026-07-01T08:00:00+00:00,2026-07-01T04:00:00+00:00",
        strategy_analysis_release_id=10,
        strategy_analysis_release_hash="release-hash",
        trace_id="trace-replay-command",
        stdout=out,
    )

    payload = json.loads(out.getvalue())
    assert payload["reason_code"] == "strategy_analysis_replay_completed"
    assert captured["strategy_analysis_release_id"] == 10
    assert captured["strategy_analysis_release_hash"] == "release-hash"
    assert captured["analysis_close_times"] == [
        datetime(2026, 7, 1, 8, tzinfo=UTC),
        datetime(2026, 7, 1, 4, tzinfo=UTC),
    ]
    assert captured["lookback_4h_count"] == 500
    assert captured["lookback_1d_count"] == 500


def test_replay_strategy_analysis_chain_command_builds_recent_periods(monkeypatch) -> None:
    captured: dict[str, Any] = {}

    def fake_replay_strategy_analysis_chain(**kwargs):
        captured.update(kwargs)
        return ServiceResult(
            ResultStatus.SUCCEEDED,
            "strategy_analysis_replay_completed",
            "ok",
            kwargs["trace_id"],
            kwargs["trigger_source"],
            {},
        )

    monkeypatch.setattr(
        "apps.strategy_analysis.management.commands.replay_strategy_analysis_chain.replay_strategy_analysis_chain",
        fake_replay_strategy_analysis_chain,
    )

    call_command(
        "replay_strategy_analysis_chain",
        end_analysis_close_time_utc="2026-07-01T08:00:00+00:00",
        period_count=3,
        trace_id="trace-replay-command",
        stdout=StringIO(),
    )

    assert captured["analysis_close_times"] == [
        datetime(2026, 7, 1, 8, tzinfo=UTC),
        datetime(2026, 7, 1, 4, tzinfo=UTC),
        datetime(2026, 7, 1, 0, tzinfo=UTC),
    ]


def test_replay_strategy_analysis_chain_command_builds_range_periods(monkeypatch) -> None:
    captured: dict[str, Any] = {}

    def fake_replay_strategy_analysis_chain(**kwargs):
        captured.update(kwargs)
        return ServiceResult(
            ResultStatus.SUCCEEDED,
            "strategy_analysis_replay_completed",
            "ok",
            kwargs["trace_id"],
            kwargs["trigger_source"],
            {"period_count": len(kwargs["analysis_close_times"]), "periods": []},
        )

    monkeypatch.setattr(
        "apps.strategy_analysis.management.commands.replay_strategy_analysis_chain.replay_strategy_analysis_chain",
        fake_replay_strategy_analysis_chain,
    )

    call_command(
        "replay_strategy_analysis_chain",
        start_analysis_close_time_utc="2026-02-07T00:00:00+00:00",
        end_analysis_close_time_utc="2026-02-07T08:00:00+00:00",
        business_request_prefix="strategy-replay-range-test",
        trace_id="trace-replay-range-command",
        stdout=StringIO(),
    )

    assert captured["analysis_close_times"] == [
        datetime(2026, 2, 7, 0, tzinfo=UTC),
        datetime(2026, 2, 7, 4, tzinfo=UTC),
        datetime(2026, 2, 7, 8, tzinfo=UTC),
    ]


def test_replay_strategy_analysis_chain_command_compact_output(monkeypatch) -> None:
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
                "period_count": 1,
                "completed_count": 1,
                "blocked_count": 0,
                "periods": [
                    {
                        "analysis_close_time_utc": "2026-02-07T00:00:00+00:00",
                        "status": "completed",
                        "stopped_step": "",
                        "reason_code": "decision_snapshot_created",
                        "summary": {
                            "domain_signals": [
                                {
                                    "domain_code": "trend",
                                    "direction": "bearish",
                                    "state_code": "trend_1d_bearish_4h_aligned",
                                    "strength": "0.75",
                                }
                            ],
                            "market_regime": {"regime_code": "bearish_trend_continuation"},
                            "strategy_routing": {"selected_strategy": "short_trend_following"},
                            "strategy_signal": {"direction": "bearish", "confidence": "0.6"},
                            "decision_snapshot": {
                                "target_position_ratio": "-0.1",
                                "target_reason_summary_zh": "目标空仓",
                            },
                        },
                    }
                ],
            },
        )

    monkeypatch.setattr(
        "apps.strategy_analysis.management.commands.replay_strategy_analysis_chain.replay_strategy_analysis_chain",
        fake_replay_strategy_analysis_chain,
    )

    out = StringIO()
    call_command(
        "replay_strategy_analysis_chain",
        analysis_close_time_utc=["2026-02-07T00:00:00+00:00"],
        output_mode="compact",
        trace_id="trace-replay-compact-command",
        stdout=out,
    )

    payload = json.loads(out.getvalue())
    period = payload["data"]["periods"][0]
    assert period["market_regime"] == "bearish_trend_continuation"
    assert period["selected_strategy"] == "short_trend_following"
    assert period["trend"]["state_code"] == "trend_1d_bearish_4h_aligned"
    assert period["target_position_ratio"] == "-0.1"
    assert "summary" not in period


@pytest.mark.django_db
def test_replay_strategy_analysis_chain_stops_period_when_quality_fails(monkeypatch) -> None:
    release = StrategyAnalysisRelease.objects.create(
        release_code="active_replay_release",
        release_hash="active-replay-release-hash",
        approval_status=ReleaseApprovalStatus.APPROVED,
        is_active=True,
        active_slot=1,
    )

    def fake_check_data_quality(**kwargs):
        return ServiceResult(
            ResultStatus.BLOCKED,
            "quality_issues_found",
            "quality failed",
            kwargs["trace_id"],
            kwargs["trigger_source"],
            {},
        )

    def fail_create_market_snapshot(**kwargs):
        pytest.fail("MarketSnapshot 不应在 4h DataQuality 失败后继续执行")

    monkeypatch.setattr("apps.strategy_analysis.services.replay.check_data_quality", fake_check_data_quality)
    monkeypatch.setattr("apps.strategy_analysis.services.replay.create_market_snapshot", fail_create_market_snapshot)

    result = replay_strategy_analysis_chain(
        analysis_close_times=[datetime(2026, 7, 1, 8, tzinfo=UTC)],
        strategy_analysis_release_id=release.id,
        strategy_analysis_release_hash=release.release_hash,
        trace_id="trace-replay-service",
        trigger_source="test",
    )

    assert result.status == ResultStatus.BLOCKED
    assert result.reason_code == "strategy_analysis_replay_has_blocked_period"
    period = result.data["periods"][0]
    assert period["stopped_step"] == "data_quality_4h"
    assert period["reason_code"] == "quality_issues_found"
