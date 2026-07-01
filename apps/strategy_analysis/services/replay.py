"""StrategyAnalysis 模块：批量回放策略分析链路。

负责：按多个 4h 分析边界串联 MarketSnapshot 到 DecisionSnapshot 的既有 service，并输出验收摘要。
不负责：新增策略算法、生成订单、进入 OrderPlan、风控审批、交易执行、订单同步或复盘结论。
读写数据库：通过既有 MarketData / StrategyAnalysis service 写入正式分析事实，并读取摘要。
访问 Redis：不涉及。
访问外部服务：不涉及；行情数据必须已由 DataCollection 落库。
发送 Hermes：不涉及。
调用大模型：不涉及。
涉及交易执行：不涉及。
允许真实交易：不涉及真实交易。
"""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from collections.abc import Callable
from typing import Any

from apps.foundation.context import ensure_context
from apps.foundation.results import ResultStatus, ServiceResult
from apps.market_data.domain import TIMEFRAME_1D, TIMEFRAME_4H, ensure_utc, latest_closed_open_time, timeframe_delta
from apps.market_data.services.quality import check_data_quality
from apps.market_data.services.snapshot import create_market_snapshot

from ..models import (
    DecisionSnapshot,
    DomainSignalValue,
    MarketRegimeSnapshot,
    ReleaseItemComponentType,
    StrategyAnalysisRelease,
    StrategyRouteDecision,
    StrategySignal,
    StrategySignalQualityResult,
)
from .atomic_signal import build_atomic_signals
from .decision_snapshot import build_decision_snapshot
from .domain_signal import build_domain_signals
from .feature_layer import build_feature_set
from .market_regime import classify_for_strategy_routing
from .release import calculate_definition_set_hash, get_current_active_release
from .strategy_routing import route_for_strategy_signal
from .strategy_signal import generate_strategy_signal
from .strategy_signal_quality import validate_strategy_signal


TERMINAL_SUCCESS_STATUSES = {"completed", "completed_no_strategy"}


def replay_strategy_analysis_chain(
    *,
    analysis_close_times: list[datetime],
    strategy_analysis_release_id: int | None = None,
    strategy_analysis_release_hash: str = "",
    lookback_4h_count: int = 500,
    lookback_1d_count: int = 500,
    business_request_prefix: str = "strategy-analysis-replay",
    trace_id: str | None = None,
    trigger_source: str = "management_command",
    progress_callback: Callable[[int, int, dict[str, Any]], None] | None = None,
) -> ServiceResult:
    """批量回放策略分析链路，只到 DecisionSnapshot，不进入订单链路。"""

    context = ensure_context(trace_id=trace_id, trigger_source=trigger_source)
    if not analysis_close_times:
        return ServiceResult(
            ResultStatus.BLOCKED,
            "analysis_close_times_required",
            "必须提供至少一个 4h 分析边界",
            context.trace_id,
            trigger_source,
        )
    release = _resolve_release(
        strategy_analysis_release_id=strategy_analysis_release_id,
        strategy_analysis_release_hash=strategy_analysis_release_hash,
        trace_id=context.trace_id,
        trigger_source=trigger_source,
    )
    if isinstance(release, ServiceResult):
        return release

    hashes = _release_hashes(release)
    period_results: list[dict[str, Any]] = []
    total_periods = len(analysis_close_times)
    for index, analysis_close_time in enumerate(analysis_close_times, start=1):
        period_result = _replay_one_period(
            analysis_close_time=ensure_utc(analysis_close_time),
            release=release,
            hashes=hashes,
            lookback_4h_count=lookback_4h_count,
            lookback_1d_count=lookback_1d_count,
            business_request_prefix=business_request_prefix,
            trace_id=context.trace_id,
            trigger_source=trigger_source,
        )
        period_results.append(period_result)
        if progress_callback is not None:
            progress_callback(index, total_periods, period_result)

    all_completed = all(result["status"] in TERMINAL_SUCCESS_STATUSES for result in period_results)
    return ServiceResult(
        ResultStatus.SUCCEEDED if all_completed else ResultStatus.BLOCKED,
        "strategy_analysis_replay_completed" if all_completed else "strategy_analysis_replay_has_blocked_period",
        "策略分析链路批量回放完成",
        context.trace_id,
        trigger_source,
        {
            "release_id": release.id,
            "release_hash": release.release_hash,
            "period_count": len(period_results),
            "completed_count": sum(1 for result in period_results if result["status"] in TERMINAL_SUCCESS_STATUSES),
            "blocked_count": sum(1 for result in period_results if result["status"] not in TERMINAL_SUCCESS_STATUSES),
            "periods": period_results,
        },
    )


def _replay_one_period(
    *,
    analysis_close_time: datetime,
    release: StrategyAnalysisRelease,
    hashes: dict[str, str],
    lookback_4h_count: int,
    lookback_1d_count: int,
    business_request_prefix: str,
    trace_id: str,
    trigger_source: str,
) -> dict[str, Any]:
    analysis_reference_time = analysis_close_time + timedelta(seconds=1)
    period_key = _period_key(analysis_close_time)
    base = {
        "analysis_close_time_utc": analysis_close_time.isoformat(),
        "analysis_reference_time_utc": analysis_reference_time.isoformat(),
    }
    windows = _quality_windows(
        analysis_close_time=analysis_close_time,
        analysis_reference_time=analysis_reference_time,
        lookback_4h_count=lookback_4h_count,
        lookback_1d_count=lookback_1d_count,
    )

    quality_4h = check_data_quality(
        timeframe=TIMEFRAME_4H,
        check_start_open_time_utc=windows["start_4h"],
        check_end_open_time_utc=windows["end_4h"],
        expected_latest_open_time_utc=windows["end_4h"],
        quality_reference_time_utc=analysis_reference_time,
        business_request_key=_key(business_request_prefix, period_key, "quality-4h"),
        trace_id=trace_id,
        trigger_source=trigger_source,
    )
    blocked = _blocked_period(base, "data_quality_4h", quality_4h)
    if blocked:
        return blocked

    quality_1d = check_data_quality(
        timeframe=TIMEFRAME_1D,
        check_start_open_time_utc=windows["start_1d"],
        check_end_open_time_utc=windows["end_1d"],
        expected_latest_open_time_utc=windows["end_1d"],
        quality_reference_time_utc=analysis_reference_time,
        business_request_key=_key(business_request_prefix, period_key, "quality-1d"),
        trace_id=trace_id,
        trigger_source=trigger_source,
    )
    blocked = _blocked_period(base, "data_quality_1d", quality_1d)
    if blocked:
        return blocked

    snapshot = create_market_snapshot(
        analysis_close_time_utc=analysis_close_time,
        analysis_reference_time_utc=analysis_reference_time,
        lookback_4h_count=lookback_4h_count,
        lookback_1d_count=lookback_1d_count,
        business_request_key=_key(business_request_prefix, period_key, "market-snapshot"),
        trace_id=trace_id,
        trigger_source=trigger_source,
    )
    blocked = _blocked_period(base, "market_snapshot", snapshot)
    if blocked:
        return blocked

    feature = build_feature_set(
        market_snapshot_id=snapshot.data["market_snapshot_id"],
        strategy_analysis_release_id=release.id,
        release_hash=release.release_hash,
        expected_definition_set_hash=hashes["feature"],
        business_request_key=_key(business_request_prefix, period_key, "feature-set"),
        trace_id=trace_id,
        trigger_source=trigger_source,
    )
    blocked = _blocked_period(base, "feature_layer", feature)
    if blocked:
        return blocked

    atomic = build_atomic_signals(
        feature_set_id=feature.data["feature_set_id"],
        strategy_analysis_release_id=release.id,
        release_hash=release.release_hash,
        expected_definition_set_hash=hashes["atomic"],
        business_request_key=_key(business_request_prefix, period_key, "atomic-set"),
        trace_id=trace_id,
        trigger_source=trigger_source,
    )
    blocked = _blocked_period(base, "atomic_signal", atomic)
    if blocked:
        return blocked

    domain = build_domain_signals(
        atomic_signal_set_id=atomic.data["atomic_signal_set_id"],
        strategy_analysis_release_id=release.id,
        release_hash=release.release_hash,
        expected_definition_set_hash=hashes["domain"],
        business_request_key=_key(business_request_prefix, period_key, "domain-set"),
        trace_id=trace_id,
        trigger_source=trigger_source,
    )
    blocked = _blocked_period(base, "domain_signal", domain)
    if blocked:
        return blocked

    regime = classify_for_strategy_routing(
        domain_signal_set_id=domain.data["domain_signal_set_id"],
        strategy_analysis_release_id=release.id,
        strategy_analysis_release_hash=release.release_hash,
        expected_market_regime_definition_hash=hashes["market_regime"],
        business_request_key=_key(business_request_prefix, period_key, "market-regime"),
        trace_id=trace_id,
        trigger_source=trigger_source,
    )
    blocked = _blocked_period(base, "market_regime", regime)
    if blocked:
        return blocked

    route = route_for_strategy_signal(
        market_regime_snapshot_id=regime.data["market_regime_snapshot_id"],
        strategy_analysis_release_id=release.id,
        strategy_analysis_release_hash=release.release_hash,
        expected_strategy_route_policy_hash=hashes["route_policy"],
        expected_strategy_definition_set_hash=hashes["strategy_set"],
        business_request_key=_key(business_request_prefix, period_key, "strategy-route"),
        trace_id=trace_id,
        trigger_source=trigger_source,
    )
    blocked = _blocked_period(base, "strategy_routing", route)
    if blocked:
        return blocked
    if not route.data.get("allows_strategy_signal"):
        return {
            **base,
            "status": "completed_no_strategy",
            "stopped_step": "strategy_routing",
            "reason_code": route.reason_code,
            "summary": _summary(
                domain_signal_set_id=domain.data["domain_signal_set_id"],
                market_regime_snapshot_id=regime.data["market_regime_snapshot_id"],
                strategy_route_decision_id=route.data["strategy_route_decision_id"],
            ),
        }

    route_decision = StrategyRouteDecision.objects.select_related("selected_strategy_definition").get(
        id=route.data["strategy_route_decision_id"]
    )
    strategy_definition_hash = (
        route_decision.selected_strategy_definition.definition_hash
        if route_decision.selected_strategy_definition_id
        else ""
    )
    signal = generate_strategy_signal(
        strategy_route_decision_id=route_decision.id,
        strategy_analysis_release_id=release.id,
        strategy_analysis_release_hash=release.release_hash,
        expected_strategy_definition_hash=strategy_definition_hash,
        business_request_key=_key(business_request_prefix, period_key, "strategy-signal"),
        trace_id=trace_id,
        trigger_source=trigger_source,
    )
    blocked = _blocked_period(base, "strategy_signal", signal)
    if blocked:
        return blocked

    quality = validate_strategy_signal(
        strategy_signal_id=signal.data["strategy_signal_id"],
        strategy_analysis_release_id=release.id,
        strategy_analysis_release_hash=release.release_hash,
        expected_quality_rule_set_hash=hashes["quality"],
        business_request_key=_key(business_request_prefix, period_key, "signal-quality"),
        validation_mode="replay",
        reference_time_utc=analysis_reference_time,
        trace_id=trace_id,
        trigger_source=trigger_source,
    )
    blocked = _blocked_period(base, "strategy_signal_quality", quality)
    if blocked:
        return blocked

    decision = build_decision_snapshot(
        strategy_signal_quality_result_id=quality.data["quality_result_id"],
        strategy_analysis_release_id=release.id,
        strategy_analysis_release_hash=release.release_hash,
        business_request_key=_key(business_request_prefix, period_key, "decision-snapshot"),
        trace_id=trace_id,
        trigger_source=trigger_source,
    )
    blocked = _blocked_period(base, "decision_snapshot", decision)
    if blocked:
        return blocked

    return {
        **base,
        "status": "completed",
        "stopped_step": "",
        "reason_code": decision.reason_code,
        "ids": {
            "market_snapshot_id": snapshot.data["market_snapshot_id"],
            "feature_set_id": feature.data["feature_set_id"],
            "atomic_signal_set_id": atomic.data["atomic_signal_set_id"],
            "domain_signal_set_id": domain.data["domain_signal_set_id"],
            "market_regime_snapshot_id": regime.data["market_regime_snapshot_id"],
            "strategy_route_decision_id": route.data["strategy_route_decision_id"],
            "strategy_signal_id": signal.data["strategy_signal_id"],
            "quality_result_id": quality.data["quality_result_id"],
            "decision_snapshot_id": decision.data["decision_snapshot_id"],
        },
        "summary": _summary(
            domain_signal_set_id=domain.data["domain_signal_set_id"],
            market_regime_snapshot_id=regime.data["market_regime_snapshot_id"],
            strategy_route_decision_id=route.data["strategy_route_decision_id"],
            strategy_signal_id=signal.data["strategy_signal_id"],
            quality_result_id=quality.data["quality_result_id"],
            decision_snapshot_id=decision.data["decision_snapshot_id"],
        ),
    }


def _resolve_release(
    *,
    strategy_analysis_release_id: int | None,
    strategy_analysis_release_hash: str,
    trace_id: str,
    trigger_source: str,
) -> StrategyAnalysisRelease | ServiceResult:
    if strategy_analysis_release_id:
        release = StrategyAnalysisRelease.objects.filter(id=strategy_analysis_release_id).first()
        if release is None:
            return ServiceResult(ResultStatus.BLOCKED, "strategy_analysis_release_missing", "版本包不存在", trace_id, trigger_source)
    else:
        release = get_current_active_release()
        if release is None:
            return ServiceResult(
                ResultStatus.BLOCKED,
                "active_strategy_analysis_release_missing",
                "没有当前启用版本包",
                trace_id,
                trigger_source,
            )
    if strategy_analysis_release_hash and release.release_hash != strategy_analysis_release_hash:
        return ServiceResult(
            ResultStatus.BLOCKED,
            "strategy_analysis_release_hash_mismatch",
            "版本包指纹不匹配",
            trace_id,
            trigger_source,
        )
    if not release.release_hash:
        return ServiceResult(
            ResultStatus.BLOCKED,
            "strategy_analysis_release_hash_missing",
            "版本包缺少指纹",
            trace_id,
            trigger_source,
        )
    return release


def _release_hashes(release: StrategyAnalysisRelease) -> dict[str, str]:
    return {
        "feature": _definition_set_hash(release, ReleaseItemComponentType.FEATURE_DEFINITION),
        "atomic": _definition_set_hash(release, ReleaseItemComponentType.ATOMIC_SIGNAL_DEFINITION),
        "domain": _definition_set_hash(release, ReleaseItemComponentType.DOMAIN_SIGNAL_DEFINITION),
        "market_regime": _single_definition_hash(release, ReleaseItemComponentType.MARKET_REGIME_DEFINITION),
        "route_policy": _single_definition_hash(release, ReleaseItemComponentType.STRATEGY_ROUTE_POLICY),
        "strategy_set": _definition_set_hash(release, ReleaseItemComponentType.STRATEGY_DEFINITION),
        "quality": _single_definition_hash(release, ReleaseItemComponentType.STRATEGY_SIGNAL_QUALITY_RULE_SET),
    }


def _definition_set_hash(release: StrategyAnalysisRelease, component_type: str) -> str:
    items = release.items.filter(component_type=component_type).order_by("sort_order", "component_code", "id")
    return calculate_definition_set_hash(items)


def _single_definition_hash(release: StrategyAnalysisRelease, component_type: str) -> str:
    item = release.items.filter(component_type=component_type).order_by("sort_order", "component_code", "id").first()
    return item.definition_hash if item else ""


def _quality_windows(
    *,
    analysis_close_time: datetime,
    analysis_reference_time: datetime,
    lookback_4h_count: int,
    lookback_1d_count: int,
) -> dict[str, datetime]:
    end_4h = analysis_close_time - timeframe_delta(TIMEFRAME_4H)
    start_4h = end_4h - timeframe_delta(TIMEFRAME_4H) * (lookback_4h_count - 1)
    end_1d = latest_closed_open_time(analysis_reference_time, TIMEFRAME_1D)
    start_1d = end_1d - timeframe_delta(TIMEFRAME_1D) * (lookback_1d_count - 1)
    return {
        "start_4h": start_4h,
        "end_4h": end_4h,
        "start_1d": start_1d,
        "end_1d": end_1d,
    }


def _blocked_period(base: dict[str, Any], step: str, result: ServiceResult) -> dict[str, Any] | None:
    if result.status == ResultStatus.SUCCEEDED:
        return None
    return {
        **base,
        "status": str(result.status),
        "stopped_step": step,
        "reason_code": result.reason_code,
        "message": result.message,
        "data": result.data,
    }


def _summary(
    *,
    domain_signal_set_id: int,
    market_regime_snapshot_id: int,
    strategy_route_decision_id: int,
    strategy_signal_id: int | None = None,
    quality_result_id: int | None = None,
    decision_snapshot_id: int | None = None,
) -> dict[str, Any]:
    domain_values = DomainSignalValue.objects.filter(domain_signal_set_id=domain_signal_set_id).order_by("domain_code")
    regime = MarketRegimeSnapshot.objects.get(id=market_regime_snapshot_id)
    route = StrategyRouteDecision.objects.select_related("selected_strategy_definition").get(id=strategy_route_decision_id)
    summary: dict[str, Any] = {
        "domain_signals": [
            {
                "domain_code": value.domain_code,
                "direction": value.direction,
                "state_code": value.state_code,
                "strength": _decimal_text(value.strength),
                "coverage_ratio": _decimal_text(value.coverage_ratio),
                "agreement_ratio": _decimal_text(value.agreement_ratio),
            }
            for value in domain_values
        ],
        "market_regime": {
            "regime_code": regime.regime_code,
            "regime_confidence": _decimal_text(regime.regime_confidence),
            "classification_margin": _decimal_text(regime.classification_margin),
        },
        "strategy_routing": {
            "route_outcome": route.route_outcome,
            "selected_strategy": route.selected_strategy_definition.strategy_code
            if route.selected_strategy_definition_id
            else "",
            "selected_strategy_version": route.selected_strategy_definition.strategy_version
            if route.selected_strategy_definition_id
            else "",
            "fallback_used": route.fallback_used,
        },
    }
    if strategy_signal_id:
        signal = StrategySignal.objects.get(id=strategy_signal_id)
        summary["strategy_signal"] = {
            "strategy_code": signal.strategy_code,
            "strategy_version": signal.strategy_version,
            "direction": signal.direction,
            "strength": _decimal_text(signal.strength),
            "confidence": _decimal_text(signal.confidence),
            "trade_price_condition": signal.trade_price_condition,
        }
    if quality_result_id:
        quality = StrategySignalQualityResult.objects.get(id=quality_result_id)
        summary["strategy_signal_quality"] = {
            "quality_status": quality.quality_status,
            "allows_decision_snapshot": quality.allows_decision_snapshot,
            "issue_count": quality.issue_count,
            "warning_count": quality.warning_count,
            "error_count": quality.error_count,
            "critical_count": quality.critical_count,
        }
    if decision_snapshot_id:
        decision = DecisionSnapshot.objects.get(id=decision_snapshot_id)
        summary["decision_snapshot"] = {
            "target_intent": decision.target_intent,
            "target_position_ratio": _decimal_text(decision.target_position_ratio),
            "target_confidence": _decimal_text(decision.target_confidence),
            "allows_order_plan": decision.allows_order_plan,
            "target_reason_code": decision.target_reason_code,
            "target_reason_summary_zh": decision.target_reason_summary_zh,
        }
    return summary


def _decimal_text(value: Decimal | None) -> str:
    if value is None:
        return ""
    normalized = value.normalize()
    if normalized == 0:
        return "0"
    return format(normalized, "f")


def _period_key(analysis_close_time: datetime) -> str:
    return analysis_close_time.strftime("%Y%m%dT%H%M%SZ")


def _key(prefix: str, period_key: str, step: str) -> str:
    return f"{prefix}:{period_key}:{step}"[:191]
