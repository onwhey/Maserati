"""PipelineOrchestrator selectors.

Module: PipelineOrchestrator
Responsibility: read orchestration audit facts for review/debug.
Not responsible for modifying business objects, external calls, Hermes, LLM, or trade execution.
Database: read-only.
"""

from __future__ import annotations

from typing import Any

from ..models import OrchestrationRun


def orchestration_run_detail(orchestration_run_id: int) -> dict[str, Any]:
    run = (
        OrchestrationRun.objects.prefetch_related("step_runs", "business_object_links")
        .get(id=orchestration_run_id)
    )
    return {
        "id": run.id,
        "run_key": run.run_key,
        "pipeline_code": run.pipeline_code,
        "scheduled_for_utc": run.scheduled_for_utc.isoformat(),
        "cycle_kind": run.cycle_kind,
        "status": run.status,
        "final_outcome": run.final_outcome,
        "reason_code": run.reason_code,
        "reason_message": run.reason_message,
        "trace_id": run.trace_id,
        "strategy_analysis_release_id": run.strategy_analysis_release_id,
        "strategy_analysis_release_hash": run.strategy_analysis_release_hash,
        "steps": [
            {
                "id": step.id,
                "step_code": step.step_code,
                "module_code": step.module_code,
                "status": step.status,
                "normalized_status": step.normalized_status,
                "flow_action": step.flow_action,
                "reason_code": step.reason_code,
                "primary_object_type": step.primary_object_type,
                "primary_object_id": step.primary_object_id,
            }
            for step in run.step_runs.order_by("execution_sequence", "id")
        ],
        "business_object_links": [
            {
                "step_code": link.step_code,
                "object_role": link.object_role,
                "object_type": link.object_type,
                "object_id": link.object_id,
            }
            for link in run.business_object_links.order_by("id")
        ],
    }

