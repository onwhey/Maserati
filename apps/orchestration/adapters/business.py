"""PipelineOrchestrator adapters.

Module: PipelineOrchestrator
Responsibility: call existing business services and normalize their results.
Not responsible for business decisions, Binance HTTP, DeepSeek, Hermes delivery,
real order submission logic, or direct lock manipulation.
Database: indirectly through called services. Redis/external services: only
through called services that already own those boundaries.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from django.conf import settings

from apps.foundation.results import ResultStatus, ServiceResult

from .base import (
    BusinessObjectRef,
    OrchestrationStepResult,
    StepContext,
    failed_step_result,
    missing_input_result,
    step_result_from_service_result,
)


def _service_no_action(*, context: StepContext, reason_code: str, message: str) -> ServiceResult:
    return ServiceResult(
        ResultStatus.SKIPPED,
        reason_code,
        message,
        context.trace_id,
        context.trigger_source,
        {"flow_action": "CONTINUE"},
    )


class ServiceStepAdapter:
    adapter_code = "ServiceStepAdapter"
    adapter_version = "1.0"
    module_code = "orchestration"
    object_mapping: dict[str, str] = {}
    primary_key: str | None = None

    def execute(self, context: StepContext) -> OrchestrationStepResult:
        try:
            result = self.call_service(context)
        except Exception as exc:  # noqa: BLE001 - 编排层必须把适配器异常收口成步骤失败事实。
            return failed_step_result(
                step_code=context.step_code,
                module_code=self.module_code,
                adapter_code=self.adapter_code,
                adapter_version=self.adapter_version,
                reason_code="orchestration_adapter_exception",
                message_zh=f"编排业务衔接器执行异常：{type(exc).__name__}",
                raw_result_summary={"error_type": type(exc).__name__},
            )
        return step_result_from_service_result(
            step_code=context.step_code,
            module_code=self.module_code,
            adapter_code=self.adapter_code,
            adapter_version=self.adapter_version,
            service_result=result,
            object_mapping=self.object_mapping,
            primary_key=self.primary_key,
        )

    def call_service(self, context: StepContext) -> ServiceResult:
        raise NotImplementedError


class BinanceAccountSyncStepAdapter(ServiceStepAdapter):
    adapter_code = "BinanceAccountSyncStepAdapter"
    module_code = "binance_account_sync"
    object_mapping = {"binance_sync_run_id": "BinanceSyncRun"}
    primary_key = "binance_sync_run_id"

    def call_service(self, context: StepContext) -> ServiceResult:
        from apps.binance_account_sync.services.sync import sync_for_trade_preparation

        return sync_for_trade_preparation(
            business_request_key=context.business_request_key,
            market_type=getattr(settings, "ACTIVE_MARKET_TYPE", ""),
            account_domain=getattr(settings, "ACTIVE_ACCOUNT_DOMAIN", ""),
            symbols=getattr(settings, "BINANCE_ACCOUNT_SYNC_SYMBOLS", None),
            trace_id=context.trace_id,
            trigger_source=context.trigger_source,
        )


class DataCollectionStepAdapter(ServiceStepAdapter):
    adapter_code = "DataCollectionStepAdapter"
    module_code = "market_data"
    object_mapping = {"data_collection_run_ids": "DataCollectionRun"}

    def call_service(self, context: StepContext) -> ServiceResult:
        from apps.market_data.domain import TIMEFRAME_1D, TIMEFRAME_4H
        from apps.market_data.services.collection import collect_klines

        ids: list[int] = []
        for timeframe in (TIMEFRAME_4H, TIMEFRAME_1D):
            result = collect_klines(
                timeframe=timeframe,
                collection_mode="latest_closed",
                business_request_key=f"{context.business_request_key}:{timeframe}",
                trace_id=context.trace_id,
                trigger_source=context.trigger_source,
                dry_run=False,
            )
            if result.status != ResultStatus.SUCCEEDED:
                return result
            run_id = result.data.get("data_collection_run_id")
            if run_id:
                ids.append(int(run_id))
        return ServiceResult(
            ResultStatus.SUCCEEDED,
            "data_collection_all_timeframes_completed",
            "4h 与 1d 行情采集步骤完成",
            context.trace_id,
            context.trigger_source,
            {"data_collection_run_ids": ids},
        )


class DataQualityStepAdapter(ServiceStepAdapter):
    adapter_code = "DataQualityStepAdapter"
    module_code = "market_data"
    object_mapping = {"data_quality_result_ids": "DataQualityResult"}

    def call_service(self, context: StepContext) -> ServiceResult:
        from apps.market_data.domain import TIMEFRAME_1D, TIMEFRAME_4H, latest_closed_open_time, timeframe_delta
        from apps.market_data.services.quality import check_data_quality

        ids: list[int] = []
        issues_found = False
        for timeframe in (TIMEFRAME_4H, TIMEFRAME_1D):
            latest_open = latest_closed_open_time(context.reference_time_utc, timeframe)
            lookback = _quality_lookback(timeframe)
            start_open = latest_open - (timeframe_delta(timeframe) * (lookback - 1))
            result = check_data_quality(
                timeframe=timeframe,
                check_start_open_time_utc=start_open,
                check_end_open_time_utc=latest_open,
                business_request_key=f"{context.business_request_key}:{timeframe}",
                trace_id=context.trace_id,
                trigger_source=context.trigger_source,
                quality_reference_time_utc=context.reference_time_utc,
                expected_latest_open_time_utc=latest_open,
                dry_run=False,
            )
            result_id = result.data.get("data_quality_result_id")
            if result_id:
                ids.append(int(result_id))
            if result.status != ResultStatus.SUCCEEDED:
                issues_found = True
        if issues_found:
            return ServiceResult(
                ResultStatus.SKIPPED,
                "data_quality_requires_backfill_or_manual_review",
                "行情质检存在问题，编排继续进入 DataBackfill 占位步骤",
                context.trace_id,
                context.trigger_source,
                {"data_quality_result_ids": ids, "allows_downstream": False, "flow_action": "CONTINUE"},
            )
        return ServiceResult(
            ResultStatus.SUCCEEDED,
            "data_quality_all_timeframes_passed",
            "4h 与 1d 行情质检通过",
            context.trace_id,
            context.trigger_source,
            {"data_quality_result_ids": ids, "allows_downstream": True},
        )


class DataBackfillStepAdapter(ServiceStepAdapter):
    adapter_code = "DataBackfillStepAdapter"
    module_code = "market_data"
    object_mapping = {"backfill_run_ids": "BackfillRun"}

    def call_service(self, context: StepContext) -> ServiceResult:
        return _service_no_action(
            context=context,
            reason_code="no_explicit_backfill_request_from_previous_step",
            message="上游质检未提供明确回补请求，本轮不由编排层猜测回补范围",
        )


class MarketSnapshotStepAdapter(ServiceStepAdapter):
    adapter_code = "MarketSnapshotStepAdapter"
    module_code = "market_data"
    object_mapping = {"market_snapshot_id": "MarketSnapshot"}
    primary_key = "market_snapshot_id"

    def call_service(self, context: StepContext) -> ServiceResult:
        from apps.market_data.domain import TIMEFRAME_4H, latest_closed_open_time, timeframe_delta
        from apps.market_data.services.snapshot import create_market_snapshot

        analysis_close = latest_closed_open_time(context.reference_time_utc, TIMEFRAME_4H) + timeframe_delta(TIMEFRAME_4H)
        return create_market_snapshot(
            analysis_close_time_utc=analysis_close,
            analysis_reference_time_utc=context.reference_time_utc,
            business_request_key=context.business_request_key,
            trace_id=context.trace_id,
            trigger_source=context.trigger_source,
            dry_run=False,
        )


class ReleaseAwareStepAdapter(ServiceStepAdapter):
    release_component_type: str = ""

    def execute(self, context: StepContext) -> OrchestrationStepResult:
        release_context = self._release_context(context)
        if isinstance(release_context, OrchestrationStepResult):
            return release_context
        return super().execute(context)

    def _release_context(self, context: StepContext) -> tuple[int, str, str] | OrchestrationStepResult:
        if not context.strategy_analysis_release_id or not context.strategy_analysis_release_hash:
            return failed_step_result(
                step_code=context.step_code,
                module_code=self.module_code,
                adapter_code=self.adapter_code,
                adapter_version=self.adapter_version,
                reason_code="strategy_analysis_release_missing",
                message_zh="正式策略分析链路缺少已冻结的当前版本包，步骤停止",
                raw_result_summary={"step_code": context.step_code},
            )
        try:
            definition_hash = _definition_set_hash(
                context.strategy_analysis_release_id,
                context.strategy_analysis_release_hash,
                self.release_component_type,
            )
        except Exception as exc:  # noqa: BLE001 - 版本包读取失败必须收口成明确步骤失败。
            return failed_step_result(
                step_code=context.step_code,
                module_code=self.module_code,
                adapter_code=self.adapter_code,
                adapter_version=self.adapter_version,
                reason_code="strategy_analysis_release_slice_invalid",
                message_zh="策略分析版本包切片不可用，步骤停止",
                raw_result_summary={"component_type": self.release_component_type, "error_type": type(exc).__name__},
            )
        return context.strategy_analysis_release_id, context.strategy_analysis_release_hash, definition_hash


class FeatureLayerStepAdapter(ReleaseAwareStepAdapter):
    adapter_code = "FeatureLayerStepAdapter"
    module_code = "strategy_analysis"
    release_component_type = "feature_definition"
    object_mapping = {"feature_set_id": "FeatureSet"}
    primary_key = "feature_set_id"

    def execute(self, context: StepContext) -> OrchestrationStepResult:
        market_snapshot_id = context.latest_object_id("MarketSnapshot")
        if market_snapshot_id is None:
            return missing_input_result(context=context, module_code=self.module_code, adapter_code=self.adapter_code, adapter_version=self.adapter_version, missing_object_type="MarketSnapshot")
        return super().execute(context)

    def call_service(self, context: StepContext) -> ServiceResult:
        from apps.strategy_analysis.services.feature_layer import build_feature_set

        release_context = self._release_context(context)
        if isinstance(release_context, OrchestrationStepResult):
            raise RuntimeError(release_context.reason_code)
        release_id, release_hash, definition_hash = release_context
        return build_feature_set(
            market_snapshot_id=context.latest_object_id("MarketSnapshot") or 0,
            strategy_analysis_release_id=release_id,
            release_hash=release_hash,
            expected_definition_set_hash=definition_hash,
            business_request_key=context.business_request_key,
            trace_id=context.trace_id,
            trigger_source=context.trigger_source,
        )


class AtomicSignalStepAdapter(ReleaseAwareStepAdapter):
    adapter_code = "AtomicSignalStepAdapter"
    module_code = "strategy_analysis"
    release_component_type = "atomic_signal_definition"
    object_mapping = {"atomic_signal_set_id": "AtomicSignalSet"}
    primary_key = "atomic_signal_set_id"

    def execute(self, context: StepContext) -> OrchestrationStepResult:
        if context.latest_object_id("FeatureSet") is None:
            return missing_input_result(context=context, module_code=self.module_code, adapter_code=self.adapter_code, adapter_version=self.adapter_version, missing_object_type="FeatureSet")
        return super().execute(context)

    def call_service(self, context: StepContext) -> ServiceResult:
        from apps.strategy_analysis.services.atomic_signal import build_atomic_signals

        release_id, release_hash, definition_hash = self._release_tuple(context)
        return build_atomic_signals(
            feature_set_id=context.latest_object_id("FeatureSet") or 0,
            strategy_analysis_release_id=release_id,
            release_hash=release_hash,
            expected_definition_set_hash=definition_hash,
            business_request_key=context.business_request_key,
            trace_id=context.trace_id,
            trigger_source=context.trigger_source,
        )

    def _release_tuple(self, context: StepContext) -> tuple[int, str, str]:
        release_context = self._release_context(context)
        if isinstance(release_context, OrchestrationStepResult):
            raise RuntimeError(release_context.reason_code)
        return release_context


class DomainSignalStepAdapter(AtomicSignalStepAdapter):
    adapter_code = "DomainSignalStepAdapter"
    release_component_type = "domain_signal_definition"
    object_mapping = {"domain_signal_set_id": "DomainSignalSet"}
    primary_key = "domain_signal_set_id"

    def execute(self, context: StepContext) -> OrchestrationStepResult:
        if context.latest_object_id("AtomicSignalSet") is None:
            return missing_input_result(context=context, module_code=self.module_code, adapter_code=self.adapter_code, adapter_version=self.adapter_version, missing_object_type="AtomicSignalSet")
        return ReleaseAwareStepAdapter.execute(self, context)

    def call_service(self, context: StepContext) -> ServiceResult:
        from apps.strategy_analysis.services.domain_signal import build_domain_signals

        release_id, release_hash, definition_hash = self._release_tuple(context)
        return build_domain_signals(
            atomic_signal_set_id=context.latest_object_id("AtomicSignalSet") or 0,
            strategy_analysis_release_id=release_id,
            release_hash=release_hash,
            expected_definition_set_hash=definition_hash,
            business_request_key=context.business_request_key,
            trace_id=context.trace_id,
            trigger_source=context.trigger_source,
        )


class MarketRegimeStepAdapter(AtomicSignalStepAdapter):
    adapter_code = "MarketRegimeStepAdapter"
    release_component_type = "market_regime_definition"
    object_mapping = {"market_regime_snapshot_id": "MarketRegimeSnapshot"}
    primary_key = "market_regime_snapshot_id"

    def execute(self, context: StepContext) -> OrchestrationStepResult:
        if context.latest_object_id("DomainSignalSet") is None:
            return missing_input_result(context=context, module_code=self.module_code, adapter_code=self.adapter_code, adapter_version=self.adapter_version, missing_object_type="DomainSignalSet")
        return ReleaseAwareStepAdapter.execute(self, context)

    def call_service(self, context: StepContext) -> ServiceResult:
        from apps.strategy_analysis.services.market_regime import classify_for_strategy_routing

        release_id, release_hash, definition_hash = self._release_tuple(context)
        return classify_for_strategy_routing(
            domain_signal_set_id=context.latest_object_id("DomainSignalSet") or 0,
            strategy_analysis_release_id=release_id,
            strategy_analysis_release_hash=release_hash,
            expected_market_regime_definition_hash=definition_hash,
            business_request_key=context.business_request_key,
            trace_id=context.trace_id,
            trigger_source=context.trigger_source,
        )


class StrategyRoutingStepAdapter(ServiceStepAdapter):
    adapter_code = "StrategyRoutingStepAdapter"
    module_code = "strategy_analysis"
    object_mapping = {"strategy_route_decision_id": "StrategyRouteDecision"}
    primary_key = "strategy_route_decision_id"

    def execute(self, context: StepContext) -> OrchestrationStepResult:
        if context.latest_object_id("MarketRegimeSnapshot") is None:
            return missing_input_result(context=context, module_code=self.module_code, adapter_code=self.adapter_code, adapter_version=self.adapter_version, missing_object_type="MarketRegimeSnapshot")
        return super().execute(context)

    def call_service(self, context: StepContext) -> ServiceResult:
        from apps.strategy_analysis.models import ReleaseItemComponentType
        from apps.strategy_analysis.services.strategy_routing import route_for_strategy_signal

        release_id, release_hash = _release_identity(context)
        policy_hash = _definition_set_hash(release_id, release_hash, ReleaseItemComponentType.STRATEGY_ROUTE_POLICY)
        strategy_hash = _definition_set_hash(release_id, release_hash, ReleaseItemComponentType.STRATEGY_DEFINITION)
        return route_for_strategy_signal(
            market_regime_snapshot_id=context.latest_object_id("MarketRegimeSnapshot") or 0,
            strategy_analysis_release_id=release_id,
            strategy_analysis_release_hash=release_hash,
            expected_strategy_route_policy_hash=policy_hash,
            expected_strategy_definition_set_hash=strategy_hash,
            business_request_key=context.business_request_key,
            trace_id=context.trace_id,
            trigger_source=context.trigger_source,
        )


class StrategySignalStepAdapter(ServiceStepAdapter):
    adapter_code = "StrategySignalStepAdapter"
    module_code = "strategy_analysis"
    object_mapping = {"strategy_signal_id": "StrategySignal"}
    primary_key = "strategy_signal_id"

    def execute(self, context: StepContext) -> OrchestrationStepResult:
        if context.latest_object_id("StrategyRouteDecision") is None:
            return missing_input_result(context=context, module_code=self.module_code, adapter_code=self.adapter_code, adapter_version=self.adapter_version, missing_object_type="StrategyRouteDecision")
        return super().execute(context)

    def call_service(self, context: StepContext) -> ServiceResult:
        from apps.strategy_analysis.models import StrategyRouteDecision
        from apps.strategy_analysis.services.strategy_signal import generate_strategy_signal

        release_id, release_hash = _release_identity(context)
        decision = StrategyRouteDecision.objects.select_related("selected_strategy_definition").get(
            id=context.latest_object_id("StrategyRouteDecision")
        )
        definition_hash = decision.selected_strategy_definition.definition_hash if decision.selected_strategy_definition_id else ""
        return generate_strategy_signal(
            strategy_route_decision_id=decision.id,
            strategy_analysis_release_id=release_id,
            strategy_analysis_release_hash=release_hash,
            expected_strategy_definition_hash=definition_hash,
            business_request_key=context.business_request_key,
            trace_id=context.trace_id,
            trigger_source=context.trigger_source,
        )


class StrategySignalQualityStepAdapter(ServiceStepAdapter):
    adapter_code = "StrategySignalQualityStepAdapter"
    module_code = "strategy_analysis"
    object_mapping = {"strategy_signal_quality_result_id": "StrategySignalQualityResult"}
    primary_key = "strategy_signal_quality_result_id"

    def execute(self, context: StepContext) -> OrchestrationStepResult:
        if context.latest_object_id("StrategySignal") is None:
            return missing_input_result(context=context, module_code=self.module_code, adapter_code=self.adapter_code, adapter_version=self.adapter_version, missing_object_type="StrategySignal")
        return super().execute(context)

    def call_service(self, context: StepContext) -> ServiceResult:
        from apps.strategy_analysis.models import ReleaseItemComponentType
        from apps.strategy_analysis.services.strategy_signal_quality import validate_strategy_signal

        release_id, release_hash = _release_identity(context)
        quality_hash = _definition_set_hash(release_id, release_hash, ReleaseItemComponentType.STRATEGY_SIGNAL_QUALITY_RULE_SET)
        return validate_strategy_signal(
            strategy_signal_id=context.latest_object_id("StrategySignal") or 0,
            strategy_analysis_release_id=release_id,
            strategy_analysis_release_hash=release_hash,
            expected_quality_rule_set_hash=quality_hash,
            business_request_key=context.business_request_key,
            validation_mode="formal_runtime",
            reference_time_utc=context.reference_time_utc,
            trace_id=context.trace_id,
            trigger_source=context.trigger_source,
        )


class DecisionSnapshotStepAdapter(ServiceStepAdapter):
    adapter_code = "DecisionSnapshotStepAdapter"
    module_code = "strategy_analysis"
    object_mapping = {"decision_snapshot_id": "DecisionSnapshot"}
    primary_key = "decision_snapshot_id"

    def execute(self, context: StepContext) -> OrchestrationStepResult:
        if context.latest_object_id("StrategySignalQualityResult") is None:
            return missing_input_result(context=context, module_code=self.module_code, adapter_code=self.adapter_code, adapter_version=self.adapter_version, missing_object_type="StrategySignalQualityResult")
        return super().execute(context)

    def call_service(self, context: StepContext) -> ServiceResult:
        from apps.strategy_analysis.services.decision_snapshot import build_decision_snapshot

        release_id, release_hash = _release_identity(context)
        return build_decision_snapshot(
            strategy_signal_quality_result_id=context.latest_object_id("StrategySignalQualityResult") or 0,
            strategy_analysis_release_id=release_id,
            strategy_analysis_release_hash=release_hash,
            business_request_key=context.business_request_key,
            trace_id=context.trace_id,
            trigger_source=context.trigger_source,
        )


class PriceSnapshotStepAdapter(ServiceStepAdapter):
    adapter_code = "PriceSnapshotStepAdapter"
    module_code = "price_snapshot"
    object_mapping = {"price_snapshot_id": "PriceSnapshot"}
    primary_key = "price_snapshot_id"

    def execute(self, context: StepContext) -> OrchestrationStepResult:
        if context.latest_object_id("DecisionSnapshot") is None:
            return missing_input_result(context=context, module_code=self.module_code, adapter_code=self.adapter_code, adapter_version=self.adapter_version, missing_object_type="DecisionSnapshot")
        return super().execute(context)

    def call_service(self, context: StepContext) -> ServiceResult:
        from apps.price_snapshot.services.snapshot import create_price_snapshot

        return create_price_snapshot(
            business_request_key=context.business_request_key,
            market_type=getattr(settings, "ACTIVE_MARKET_TYPE", ""),
            account_domain=getattr(settings, "ACTIVE_ACCOUNT_DOMAIN", ""),
            symbol=getattr(settings, "ACTIVE_SYMBOL", ""),
            trace_id=context.trace_id,
            trigger_source=context.trigger_source,
        )


class OrderPlanStepAdapter(ServiceStepAdapter):
    adapter_code = "OrderPlanStepAdapter"
    module_code = "order_plan"
    object_mapping = {
        "order_plan_id": "OrderPlan",
        "active_lock_id": "OrderPlanActiveLock",
        "candidate_order_intent_ids": "CandidateOrderIntent",
    }
    primary_key = "order_plan_id"

    def execute(self, context: StepContext) -> OrchestrationStepResult:
        for object_type in ("DecisionSnapshot", "BinanceSyncRun", "PriceSnapshot"):
            if context.latest_object_id(object_type) is None:
                return missing_input_result(context=context, module_code=self.module_code, adapter_code=self.adapter_code, adapter_version=self.adapter_version, missing_object_type=object_type)
        return super().execute(context)

    def call_service(self, context: StepContext) -> ServiceResult:
        from apps.order_plan.adapters import run_order_plan_step

        return run_order_plan_step(
            business_request_key=context.business_request_key,
            decision_snapshot_id=context.latest_object_id("DecisionSnapshot") or 0,
            binance_sync_run_id=context.latest_object_id("BinanceSyncRun") or 0,
            price_snapshot_id=context.latest_object_id("PriceSnapshot") or 0,
            reference_time_utc=context.reference_time_utc,
            trace_id=context.trace_id,
            trigger_source=context.trigger_source,
        )


class RiskCheckStepAdapter(ServiceStepAdapter):
    adapter_code = "RiskCheckStepAdapter"
    module_code = "risk_check"
    object_mapping = {"risk_check_result_id": "RiskCheckResult", "approved_order_intent_id": "ApprovedOrderIntent"}
    primary_key = "risk_check_result_id"

    def execute(self, context: StepContext) -> OrchestrationStepResult:
        for object_type in ("OrderPlan", "CandidateOrderIntent", "BinanceSyncRun", "PriceSnapshot", "OrderPlanActiveLock"):
            if context.latest_object_id(object_type) is None:
                return missing_input_result(context=context, module_code=self.module_code, adapter_code=self.adapter_code, adapter_version=self.adapter_version, missing_object_type=object_type)
        return super().execute(context)

    def call_service(self, context: StepContext) -> ServiceResult:
        from apps.risk_check.adapters import run_risk_check_step

        return run_risk_check_step(
            business_request_key=context.business_request_key,
            order_plan_id=context.latest_object_id("OrderPlan") or 0,
            candidate_order_intent_id=context.latest_object_id("CandidateOrderIntent") or 0,
            binance_sync_run_id=context.latest_object_id("BinanceSyncRun") or 0,
            price_snapshot_id=context.latest_object_id("PriceSnapshot") or 0,
            active_lock_id=context.latest_object_id("OrderPlanActiveLock") or 0,
            reference_time_utc=context.reference_time_utc,
            risk_rule_set=getattr(settings, "RISK_CHECK_RULE_SET", None),
            trace_id=context.trace_id,
            trigger_source=context.trigger_source,
        )


class ExecutionPreparationStepAdapter(ServiceStepAdapter):
    adapter_code = "ExecutionPreparationStepAdapter"
    module_code = "execution_preparation"
    object_mapping = {"execution_preparation_result_id": "ExecutionPreparationResult", "prepared_order_intent_id": "PreparedOrderIntent"}
    primary_key = "prepared_order_intent_id"

    def execute(self, context: StepContext) -> OrchestrationStepResult:
        if context.latest_object_id("ApprovedOrderIntent") is None:
            return missing_input_result(context=context, module_code=self.module_code, adapter_code=self.adapter_code, adapter_version=self.adapter_version, missing_object_type="ApprovedOrderIntent")
        return super().execute(context)

    def call_service(self, context: StepContext) -> ServiceResult:
        from apps.execution_preparation.services.preparation import prepare_execution

        return prepare_execution(
            approved_order_intent_id=context.latest_object_id("ApprovedOrderIntent") or 0,
            business_request_key=context.business_request_key,
            reference_time_utc=context.reference_time_utc,
            trace_id=context.trace_id,
            trigger_source=context.trigger_source,
        )


class OrderSubmissionStepAdapter(ServiceStepAdapter):
    adapter_code = "OrderSubmissionStepAdapter"
    module_code = "execution"
    object_mapping = {"order_submission_attempt_id": "OrderSubmissionAttempt"}
    primary_key = "order_submission_attempt_id"

    def execute(self, context: StepContext) -> OrchestrationStepResult:
        if context.latest_object_id("PreparedOrderIntent") is None:
            return missing_input_result(context=context, module_code=self.module_code, adapter_code=self.adapter_code, adapter_version=self.adapter_version, missing_object_type="PreparedOrderIntent")
        try:
            result = self.call_service(context)
        except Exception as exc:  # noqa: BLE001 - 编排层必须把适配器异常收口成步骤失败事实。
            return failed_step_result(
                step_code=context.step_code,
                module_code=self.module_code,
                adapter_code=self.adapter_code,
                adapter_version=self.adapter_version,
                reason_code="orchestration_adapter_exception",
                message_zh=f"编排业务衔接器执行异常：{type(exc).__name__}",
                raw_result_summary={"error_type": type(exc).__name__},
            )
        return step_result_from_service_result(
            step_code=context.step_code,
            module_code=self.module_code,
            adapter_code=self.adapter_code,
            adapter_version=self.adapter_version,
            service_result=self._map_main_run_flow(result),
            object_mapping=self.object_mapping,
            primary_key=self.primary_key,
        )

    def call_service(self, context: StepContext) -> ServiceResult:
        from apps.execution.services.submission import submit_prepared_order

        return submit_prepared_order(
            prepared_order_intent_id=context.latest_object_id("PreparedOrderIntent") or 0,
            business_request_key=context.business_request_key,
            trace_id=context.trace_id,
            trigger_source=context.trigger_source,
        )

    @staticmethod
    def _map_main_run_flow(result: ServiceResult) -> ServiceResult:
        order_submission_status = str(result.data.get("order_submission_status", ""))
        if order_submission_status in {"accepted", "unknown"}:
            return ServiceResult(
                result.status,
                result.reason_code,
                result.message,
                result.trace_id,
                result.trigger_source,
                {**result.data, "flow_action": "COMPLETE"},
            )
        if order_submission_status == "submitting":
            return ServiceResult(
                result.status,
                result.reason_code,
                result.message,
                result.trace_id,
                result.trigger_source,
                {**result.data, "flow_action": "STOP"},
            )
        return result


def _quality_lookback(timeframe: str) -> int:
    if timeframe == "1d":
        return int(getattr(settings, "MARKET_DATA_QUALITY_1D_LOOKBACK", 30))
    return int(getattr(settings, "MARKET_DATA_QUALITY_4H_LOOKBACK", 60))


def _release_identity(context: StepContext) -> tuple[int, str]:
    if not context.strategy_analysis_release_id or not context.strategy_analysis_release_hash:
        raise RuntimeError("strategy_analysis_release_missing")
    return context.strategy_analysis_release_id, context.strategy_analysis_release_hash


def _definition_set_hash(release_id: int, release_hash: str, component_type: str) -> str:
    from apps.strategy_analysis.services.release import resolve_frozen_slice

    return resolve_frozen_slice(
        release_id=release_id,
        release_hash=release_hash,
        component_type=component_type,
    ).definition_set_hash
