"""PipelineOrchestrator service.

Module: PipelineOrchestrator
Responsibility: create runs, freeze formal step definitions, call adapters, and
persist step/object audit facts.
Not responsible for interpreting business internals, Binance/DeepSeek calls,
Hermes delivery, lock release, or order submission logic.
Database: writes orchestration facts. Redis: not used.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.alerts.models import AlertSeverity
from apps.alerts.services import record_alert_event
from apps.foundation.results import ResultStatus, ServiceResult

from ..adapters.base import BusinessObjectRef, BusinessStepAdapter, OrchestrationStepResult, StepContext, failed_step_result
from ..adapters.registry import default_adapter_registry, get_adapter
from ..models import (
    OrchestrationBusinessObjectLink,
    OrchestrationFinalOutcome,
    OrchestrationRun,
    OrchestrationRunConfigSnapshot,
    OrchestrationRunStatus,
    OrchestrationStepRun,
    OrchestrationStepRunStatus,
    OrchestrationTriggerMode,
)
from ..registry.definitions import (
    PIPELINE_CODE,
    FORMAL_STEPS,
    REGISTRY_VERSION,
    StepDefinition,
    adapter_versions,
    enabled_steps,
    mapping_versions,
    ordered_step_codes,
    registry_hash,
    step_by_code,
    validate_registry,
)


MAX_STEPS_PER_DRIVE = 80


@dataclass(frozen=True)
class DriveSummary:
    orchestration_run_id: int
    status: str
    final_outcome: str
    executed_step_count: int
    last_step_code: str
    reason_code: str
    message: str


def start_or_get_orchestration_run(
    *,
    scheduled_for_utc: datetime,
    cycle_kind: str = "4h",
    trigger_mode: str = OrchestrationTriggerMode.AUTOMATIC,
    trigger_source: str = "celery_beat",
    trace_id: str = "",
    pipeline_code: str = PIPELINE_CODE,
) -> OrchestrationRun:
    validate_registry(FORMAL_STEPS)
    scheduled = _ensure_utc(scheduled_for_utc)
    trace = trace_id or _stable_hash({"scheduled_for_utc": scheduled.isoformat(), "cycle_kind": cycle_kind})[:32]
    release_id, release_hash, freeze_status, freeze_reason = _current_release_identity()
    snapshot_payload = _config_snapshot_payload(
        release_id=release_id,
        release_hash=release_hash,
        freeze_status=freeze_status,
        freeze_reason=freeze_reason,
    )
    snapshot_hash = _stable_hash(snapshot_payload)
    run_key = _stable_hash(
        {
            "pipeline_code": pipeline_code,
            "scheduled_for_utc": scheduled.isoformat(),
            "cycle_kind": cycle_kind,
            "trigger_mode": trigger_mode,
        }
    )
    defaults = {
        "pipeline_code": pipeline_code,
        "registry_version": REGISTRY_VERSION,
        "registry_hash": registry_hash(),
        "strategy_analysis_release_id": release_id,
        "strategy_analysis_release_hash": release_hash,
        "strategy_analysis_release_freeze_status": freeze_status,
        "strategy_analysis_release_freeze_reason_code": freeze_reason,
        "run_config_snapshot_hash": snapshot_hash,
        "scheduled_for_utc": scheduled,
        "cycle_kind": cycle_kind,
        "trigger_mode": trigger_mode,
        "trigger_source": trigger_source,
        "status": OrchestrationRunStatus.CREATED,
        "final_outcome": OrchestrationFinalOutcome.NONE,
        "trace_id": trace,
    }
    with transaction.atomic():
        run, created = OrchestrationRun.objects.get_or_create(run_key=run_key, defaults=defaults)
        if created:
            OrchestrationRunConfigSnapshot.objects.create(
                orchestration_run=run,
                registry_version=REGISTRY_VERSION,
                registry_hash=registry_hash(),
                strategy_analysis_release_id=release_id,
                strategy_analysis_release_hash=release_hash,
                adapter_versions=adapter_versions(),
                result_mapping_versions=mapping_versions(),
                config_snapshot=snapshot_payload,
                snapshot_hash=snapshot_hash,
            )
            _record_run_alert(run, "orchestration_run_created", "编排运行已创建")
    return run


def drive_orchestration_run(
    *,
    orchestration_run_id: int,
    adapter_registry: Mapping[str, BusinessStepAdapter] | None = None,
    max_steps: int = MAX_STEPS_PER_DRIVE,
) -> DriveSummary:
    registry = adapter_registry or default_adapter_registry()
    executed_count = 0
    last_step_code = ""
    while executed_count < max_steps:
        run = OrchestrationRun.objects.get(id=orchestration_run_id)
        if run.status in _TERMINAL_RUN_STATUSES:
            return _summary(run, executed_count, last_step_code, "orchestration_already_terminal", "编排运行已经结束")
        if run.status == OrchestrationRunStatus.WAITING:
            return _summary(run, executed_count, run.current_step_code, "orchestration_waiting_for_resume", "编排运行正在等待恢复令牌，不由普通 driver 重复执行")
        next_step = _next_step_definition(run)
        if next_step is None:
            _finish_run(run, OrchestrationRunStatus.COMPLETED, OrchestrationFinalOutcome.SUCCEEDED, "pipeline_completed", "编排步骤全部完成")
            return _summary(run, executed_count, last_step_code, "pipeline_completed", "编排步骤全部完成")
        step_run = _claim_step_run(run, next_step)
        if step_run.status in _TERMINAL_STEP_STATUSES:
            executed_count += 1
            last_step_code = step_run.step_code
            continue
        result = _execute_adapter(run, step_run, next_step, registry)
        _persist_step_result(step_run, result)
        _record_step_alert(run, step_run, result)
        executed_count += 1
        last_step_code = step_run.step_code
        action = result.flow_action
        if action == "CONTINUE":
            _mark_run_progress(run, step_run)
            continue
        if action == "COMPLETE":
            outcome = OrchestrationFinalOutcome.NO_ACTION if result.normalized_status in {"NO_ACTION", "SKIPPED", "UNKNOWN"} else OrchestrationFinalOutcome.SUCCEEDED
            status = OrchestrationRunStatus.COMPLETED_NO_ACTION if outcome == OrchestrationFinalOutcome.NO_ACTION else OrchestrationRunStatus.COMPLETED
            _finish_run(run, status, outcome, result.reason_code, result.message_zh, stopped_step=step_run.step_code)
            return _summary(run, executed_count, last_step_code, result.reason_code, result.message_zh)
        if action == "WAIT":
            _wait_run(run, step_run, result)
            return _summary(run, executed_count, last_step_code, result.reason_code, result.message_zh)
        if action == "STOP":
            _finish_run(run, OrchestrationRunStatus.BLOCKED, OrchestrationFinalOutcome.BLOCKED, result.reason_code, result.message_zh, stopped_step=step_run.step_code)
            return _summary(run, executed_count, last_step_code, result.reason_code, result.message_zh)
        _finish_run(run, OrchestrationRunStatus.FAILED, OrchestrationFinalOutcome.FAILED, result.reason_code, result.message_zh, stopped_step=step_run.step_code)
        return _summary(run, executed_count, last_step_code, result.reason_code, result.message_zh)

    run = OrchestrationRun.objects.get(id=orchestration_run_id)
    run.reason_code = "orchestration_max_steps_reached"
    run.reason_message = "本次推进达到最大步骤数限制"
    run.needs_manual_attention = True
    run.save(update_fields=["reason_code", "reason_message", "needs_manual_attention", "updated_at_utc"])
    return _summary(run, executed_count, last_step_code, "orchestration_max_steps_reached", "本次推进达到最大步骤数限制")


def start_and_drive_orchestration_run(
    *,
    scheduled_for_utc: datetime,
    cycle_kind: str = "4h",
    trigger_mode: str = OrchestrationTriggerMode.AUTOMATIC,
    trigger_source: str = "celery_beat",
    trace_id: str = "",
    adapter_registry: Mapping[str, BusinessStepAdapter] | None = None,
) -> DriveSummary:
    run = start_or_get_orchestration_run(
        scheduled_for_utc=scheduled_for_utc,
        cycle_kind=cycle_kind,
        trigger_mode=trigger_mode,
        trigger_source=trigger_source,
        trace_id=trace_id,
    )
    return drive_orchestration_run(orchestration_run_id=run.id, adapter_registry=adapter_registry)


def resume_waiting_orchestration_step(
    *,
    resume_token: str,
    trace_id: str = "",
    trigger_source: str = "orchestration_resume_task",
    adapter_registry: Mapping[str, BusinessStepAdapter] | None = None,
) -> DriveSummary:
    step_run = OrchestrationStepRun.objects.select_related("orchestration_run").get(resume_token=resume_token)
    run = step_run.orchestration_run
    if run.status != OrchestrationRunStatus.WAITING or step_run.status != OrchestrationStepRunStatus.WAITING:
        return _summary(run, 0, step_run.step_code, "resume_token_not_waiting", "恢复令牌对应步骤当前不处于等待状态")
    run.trace_id = trace_id or run.trace_id
    run.trigger_source = trigger_source
    run.status = OrchestrationRunStatus.RUNNING
    run.current_step_code = step_run.step_code
    run.waiting_since_utc = None
    run.save(update_fields=["trace_id", "trigger_source", "status", "current_step_code", "waiting_since_utc", "updated_at_utc"])
    step_run.status = OrchestrationStepRunStatus.RUNNING
    step_run.resume_token = None
    step_run.waiting_since_utc = None
    step_run.last_status_updated_at_utc = timezone.now()
    step_run.save(update_fields=["status", "resume_token", "waiting_since_utc", "last_status_updated_at_utc", "updated_at_utc"])

    registry = adapter_registry or default_adapter_registry()
    definition = step_by_code(step_run.step_code)
    result = _execute_adapter(run, step_run, definition, registry)
    _persist_step_result(step_run, result)
    _record_step_alert(run, step_run, result)
    action = result.flow_action
    if action == "CONTINUE":
        _mark_run_progress(run, step_run)
        return drive_orchestration_run(orchestration_run_id=run.id, adapter_registry=adapter_registry)
    if action == "COMPLETE":
        outcome = OrchestrationFinalOutcome.NO_ACTION if result.normalized_status in {"NO_ACTION", "SKIPPED", "UNKNOWN"} else OrchestrationFinalOutcome.SUCCEEDED
        status = OrchestrationRunStatus.COMPLETED_NO_ACTION if outcome == OrchestrationFinalOutcome.NO_ACTION else OrchestrationRunStatus.COMPLETED
        _finish_run(run, status, outcome, result.reason_code, result.message_zh, stopped_step=step_run.step_code)
    elif action == "WAIT":
        _wait_run(run, step_run, result)
    elif action == "STOP":
        _finish_run(run, OrchestrationRunStatus.BLOCKED, OrchestrationFinalOutcome.BLOCKED, result.reason_code, result.message_zh, stopped_step=step_run.step_code)
    else:
        _finish_run(run, OrchestrationRunStatus.FAILED, OrchestrationFinalOutcome.FAILED, result.reason_code, result.message_zh, stopped_step=step_run.step_code)
    return _summary(run, 1, step_run.step_code, result.reason_code, result.message_zh)


def _execute_adapter(
    run: OrchestrationRun,
    step_run: OrchestrationStepRun,
    definition: StepDefinition,
    registry: Mapping[str, BusinessStepAdapter],
) -> OrchestrationStepResult:
    try:
        adapter = get_adapter(definition.adapter_code, registry)
    except LookupError:
        return failed_step_result(
            step_code=definition.step_code,
            module_code=definition.module_code,
            adapter_code=definition.adapter_code,
            adapter_version=definition.adapter_version,
            reason_code="orchestration_adapter_missing",
            message_zh="编排步骤缺少业务衔接器",
            raw_result_summary={"adapter_code": definition.adapter_code},
        )
    context = StepContext(
        orchestration_run_id=run.id,
        step_run_id=step_run.id,
        step_code=definition.step_code,
        business_request_key=step_run.business_request_key,
        trace_id=run.trace_id,
        trigger_source=run.trigger_source,
        reference_time_utc=run.scheduled_for_utc,
        strategy_analysis_release_id=run.strategy_analysis_release_id,
        strategy_analysis_release_hash=run.strategy_analysis_release_hash,
        metadata={},
        object_links=_object_links_for_context(run),
    )
    return adapter.execute(context)


def _claim_step_run(run: OrchestrationRun, definition: StepDefinition) -> OrchestrationStepRun:
    sequence = _sequence_for_step(definition)
    business_request_key = _stable_hash(
        {
            "orchestration_run_id": run.id,
            "run_key": run.run_key,
            "step_code": definition.step_code,
            "execution_sequence": sequence,
        }
    )
    now = timezone.now()
    with transaction.atomic():
        step_run, created = OrchestrationStepRun.objects.get_or_create(
            business_request_key=business_request_key,
            defaults={
                "orchestration_run": run,
                "step_code": definition.step_code,
                "module_code": definition.module_code,
                "adapter_code": definition.adapter_code,
                "adapter_version": definition.adapter_version,
                "result_mapping_version": definition.result_mapping_version,
                "execution_sequence": sequence,
                "status": OrchestrationStepRunStatus.CREATED,
                "trace_id": run.trace_id,
            },
        )
        if created or step_run.status == OrchestrationStepRunStatus.CREATED:
            step_run.status = OrchestrationStepRunStatus.RUNNING
            step_run.started_at_utc = step_run.started_at_utc or now
            step_run.last_status_updated_at_utc = now
            step_run.save(update_fields=["status", "started_at_utc", "last_status_updated_at_utc", "updated_at_utc"])
            run.status = OrchestrationRunStatus.RUNNING
            run.current_step_code = definition.step_code
            run.started_at_utc = run.started_at_utc or now
            run.save(update_fields=["status", "current_step_code", "started_at_utc", "updated_at_utc"])
    return step_run


def _persist_step_result(step_run: OrchestrationStepRun, result: OrchestrationStepResult) -> None:
    now = timezone.now()
    status = _step_status_from_result(result)
    with transaction.atomic():
        locked = OrchestrationStepRun.objects.select_for_update().get(id=step_run.id)
        locked.status = status
        locked.normalized_status = result.normalized_status
        locked.flow_action = result.flow_action
        locked.reason_code = result.reason_code
        locked.reason_message = result.message_zh[:500]
        locked.raw_business_status = result.raw_business_status[:80]
        locked.raw_result_summary = result.raw_result_summary
        locked.raw_result_hash = result.raw_result_hash
        locked.needs_manual_attention = result.needs_manual_attention
        locked.resume_token = result.resume_token or None
        locked.resume_step_code = result.resume_step_code
        locked.next_check_at_utc = result.next_check_at_utc
        if result.primary_object_ref is not None:
            locked.primary_object_type = result.primary_object_ref.object_type
            locked.primary_object_id = result.primary_object_ref.object_id
        if status == OrchestrationStepRunStatus.WAITING:
            locked.waiting_since_utc = now
            if result.primary_object_ref is not None:
                locked.waiting_object_type = result.primary_object_ref.object_type
                locked.waiting_object_id = result.primary_object_ref.object_id
        else:
            locked.finished_at_utc = now
        locked.last_status_updated_at_utc = now
        locked.save()
        _persist_object_links(locked, result.business_object_refs)


def _persist_object_links(step_run: OrchestrationStepRun, refs: tuple[BusinessObjectRef, ...]) -> None:
    for ref in refs:
        OrchestrationBusinessObjectLink.objects.get_or_create(
            orchestration_run=step_run.orchestration_run,
            step_run=step_run,
            object_role=ref.role,
            object_type=ref.object_type,
            object_id=ref.object_id,
            defaults={
                "step_code": step_run.step_code,
                "module_code": step_run.module_code,
                "object_label": ref.object_label,
                "ref_strategy": ref.ref_strategy,
                "trace_id": step_run.trace_id,
            },
        )


def _mark_run_progress(run: OrchestrationRun, step_run: OrchestrationStepRun) -> None:
    OrchestrationRun.objects.filter(id=run.id).update(
        status=OrchestrationRunStatus.RUNNING,
        last_completed_step_code=step_run.step_code,
        current_step_code="",
        waiting_since_utc=None,
        reason_code=step_run.reason_code,
        reason_message=step_run.reason_message,
        needs_manual_attention=step_run.needs_manual_attention,
    )


def _wait_run(run: OrchestrationRun, step_run: OrchestrationStepRun, result: OrchestrationStepResult) -> None:
    OrchestrationRun.objects.filter(id=run.id).update(
        status=OrchestrationRunStatus.WAITING,
        final_outcome=OrchestrationFinalOutcome.NONE,
        current_step_code=step_run.step_code,
        last_stopped_step_code=step_run.step_code,
        waiting_since_utc=timezone.now(),
        reason_code=result.reason_code,
        reason_message=result.message_zh[:500],
        needs_manual_attention=result.needs_manual_attention,
    )


def _finish_run(
    run: OrchestrationRun,
    status: str,
    outcome: str,
    reason_code: str,
    message: str,
    *,
    stopped_step: str = "",
) -> None:
    OrchestrationRun.objects.filter(id=run.id).update(
        status=status,
        final_outcome=outcome,
        current_step_code="",
        last_stopped_step_code=stopped_step,
        reason_code=reason_code,
        reason_message=message[:500],
        finished_at_utc=timezone.now(),
        needs_manual_attention=status in {OrchestrationRunStatus.BLOCKED, OrchestrationRunStatus.FAILED, OrchestrationRunStatus.UNKNOWN},
    )
    run.refresh_from_db()
    _record_run_alert(run, f"orchestration_run_{status}", message)


def _next_step_definition(run: OrchestrationRun) -> StepDefinition | None:
    finished_codes = set(
        run.step_runs.filter(status__in=_TERMINAL_STEP_STATUSES).values_list("step_code", flat=True)
    )
    for step_code in ordered_step_codes():
        if step_code not in finished_codes:
            return step_by_code(step_code)
    return None


def _sequence_for_step(definition: StepDefinition) -> int:
    return definition.step_order


def _object_links_for_context(run: OrchestrationRun) -> dict[str, list[BusinessObjectRef]]:
    refs: dict[str, list[BusinessObjectRef]] = {}
    for link in run.business_object_links.order_by("id"):
        refs.setdefault(link.object_type, []).append(
            BusinessObjectRef(
                object_type=link.object_type,
                object_id=link.object_id,
                role=link.object_role,
                object_label=link.object_label,
                ref_strategy=link.ref_strategy,
            )
        )
    return refs


def _step_status_from_result(result: OrchestrationStepResult) -> str:
    if result.flow_action == "WAIT":
        return OrchestrationStepRunStatus.WAITING
    return {
        "SUCCEEDED": OrchestrationStepRunStatus.SUCCEEDED,
        "NO_ACTION": OrchestrationStepRunStatus.NO_ACTION,
        "SKIPPED": OrchestrationStepRunStatus.SKIPPED,
        "BLOCKED": OrchestrationStepRunStatus.BLOCKED,
        "UNKNOWN": OrchestrationStepRunStatus.UNKNOWN,
        "FAILED": OrchestrationStepRunStatus.FAILED,
    }.get(result.normalized_status, OrchestrationStepRunStatus.FAILED)


def _summary(run: OrchestrationRun, count: int, last_step_code: str, reason_code: str, message: str) -> DriveSummary:
    run.refresh_from_db()
    return DriveSummary(
        orchestration_run_id=run.id,
        status=run.status,
        final_outcome=run.final_outcome,
        executed_step_count=count,
        last_step_code=last_step_code,
        reason_code=reason_code,
        message=message,
    )


def _current_release_identity() -> tuple[int | None, str, str, str]:
    try:
        from apps.strategy_analysis.services.release import get_current_active_release

        release = get_current_active_release()
    except Exception:  # noqa: BLE001 - 启动编排不能因为查询当前版本包异常而猜测继续。
        return None, "", "failed", "strategy_analysis_release_unreadable"
    if release is None:
        return None, "", "missing", "strategy_analysis_release_missing"
    return release.id, release.release_hash, "frozen", "strategy_analysis_release_frozen"


def _config_snapshot_payload(*, release_id: int | None, release_hash: str, freeze_status: str, freeze_reason: str) -> dict[str, Any]:
    return {
        "pipeline_code": PIPELINE_CODE,
        "registry_version": REGISTRY_VERSION,
        "registry_hash": registry_hash(),
        "enabled_steps": [step.step_code for step in enabled_steps()],
        "adapter_versions": adapter_versions(),
        "result_mapping_versions": mapping_versions(),
        "strategy_analysis_release_id": release_id,
        "strategy_analysis_release_hash": release_hash,
        "strategy_analysis_release_freeze_status": freeze_status,
        "strategy_analysis_release_freeze_reason_code": freeze_reason,
    }


def _record_run_alert(run: OrchestrationRun, event_type: str, message: str) -> None:
    record_alert_event(
        event_key=_stable_hash({"kind": "orchestration_run", "event_type": event_type, "run_id": run.id, "status": run.status}),
        source_module="pipeline_orchestrator",
        event_type=event_type,
        event_category="orchestration",
        severity=AlertSeverity.INFO,
        title_zh="编排运行事件",
        message_zh=message,
        trace_id=run.trace_id,
        trigger_source=run.trigger_source,
        related_object_type="OrchestrationRun",
        related_object_id=str(run.id),
        business_status=run.status,
        reason_code=run.reason_code,
        payload_summary={"final_outcome": run.final_outcome, "scheduled_for_utc": run.scheduled_for_utc.isoformat()},
        delivery_enabled=False,
    )


def _record_step_alert(run: OrchestrationRun, step_run: OrchestrationStepRun, result: OrchestrationStepResult) -> None:
    record_alert_event(
        event_key=_stable_hash({"kind": "orchestration_step", "step_run_id": step_run.id, "status": result.normalized_status}),
        source_module="pipeline_orchestrator",
        event_type=f"orchestration_step_{result.normalized_status.lower()}",
        event_category="orchestration",
        severity=AlertSeverity.WARNING if result.normalized_status in {"BLOCKED", "UNKNOWN", "FAILED"} else AlertSeverity.INFO,
        title_zh="编排步骤事件",
        message_zh=result.message_zh,
        trace_id=run.trace_id,
        trigger_source=run.trigger_source,
        related_object_type="OrchestrationStepRun",
        related_object_id=str(step_run.id),
        business_status=result.normalized_status,
        reason_code=result.reason_code,
        payload_summary={"step_code": step_run.step_code, "flow_action": result.flow_action},
        delivery_enabled=False,
    )


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _stable_hash(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


_TERMINAL_RUN_STATUSES = {
    OrchestrationRunStatus.COMPLETED,
    OrchestrationRunStatus.COMPLETED_NO_ACTION,
    OrchestrationRunStatus.BLOCKED,
    OrchestrationRunStatus.UNKNOWN,
    OrchestrationRunStatus.FAILED,
    OrchestrationRunStatus.STALE_INTERRUPTED,
}

_TERMINAL_STEP_STATUSES = {
    OrchestrationStepRunStatus.SUCCEEDED,
    OrchestrationStepRunStatus.NO_ACTION,
    OrchestrationStepRunStatus.SKIPPED,
    OrchestrationStepRunStatus.BLOCKED,
    OrchestrationStepRunStatus.UNKNOWN,
    OrchestrationStepRunStatus.FAILED,
}
