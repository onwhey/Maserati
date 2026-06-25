"""PipelineOrchestrator 模块：定义业务 StepAdapter 合同；不读写数据库；不访问外部服务；不直接执行交易。"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol

from apps.foundation.results import ResultStatus, ServiceResult
from apps.foundation.redaction import sanitize_mapping


NORMALIZED_STATUSES = {"SUCCEEDED", "NO_ACTION", "BLOCKED", "UNKNOWN", "FAILED", "SKIPPED"}
FLOW_ACTIONS = {"CONTINUE", "COMPLETE", "WAIT", "STOP", "FAIL"}
SERVICE_FLOW_ACTIONS = {"CONTINUE", "COMPLETE", "WAIT", "STOP", "FAIL"}
DEFAULT_FLOW_BY_STATUS = {
    ResultStatus.SUCCEEDED: "CONTINUE",
    ResultStatus.NO_ACTION: "COMPLETE",
    ResultStatus.SKIPPED: "CONTINUE",
    ResultStatus.BLOCKED: "STOP",
    ResultStatus.DENIED: "STOP",
    ResultStatus.UNKNOWN: "COMPLETE",
    ResultStatus.FAILED: "FAIL",
}
NORMALIZED_BY_SERVICE_STATUS = {
    ResultStatus.SUCCEEDED: "SUCCEEDED",
    ResultStatus.NO_ACTION: "NO_ACTION",
    ResultStatus.SKIPPED: "SKIPPED",
    ResultStatus.BLOCKED: "BLOCKED",
    ResultStatus.DENIED: "BLOCKED",
    ResultStatus.UNKNOWN: "UNKNOWN",
    ResultStatus.FAILED: "FAILED",
}


@dataclass(frozen=True)
class BusinessObjectRef:
    object_type: str
    object_id: str
    role: str = "related"
    object_label: str = ""
    ref_strategy: str = "explicit_refs"


@dataclass(frozen=True)
class StepContext:
    orchestration_run_id: int
    step_run_id: int
    step_code: str
    business_request_key: str
    trace_id: str
    trigger_source: str
    reference_time_utc: datetime
    strategy_analysis_release_id: int | None = None
    strategy_analysis_release_hash: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    object_links: dict[str, list[BusinessObjectRef]] = field(default_factory=dict)

    def latest_object_id(self, object_type: str) -> int | None:
        refs = self.object_links.get(object_type, [])
        if not refs:
            return None
        raw = refs[-1].object_id
        return int(raw) if str(raw).isdigit() else None


@dataclass(frozen=True)
class OrchestrationStepResult:
    step_code: str
    module_code: str
    adapter_code: str
    adapter_version: str
    normalized_status: str
    flow_action: str
    reason_code: str
    message_zh: str
    primary_object_ref: BusinessObjectRef | None
    business_object_refs: tuple[BusinessObjectRef, ...]
    raw_business_status: str
    raw_result_summary: dict[str, Any]
    raw_result_hash: str
    needs_manual_attention: bool
    resume_token: str = ""
    resume_step_code: str = ""
    next_check_at_utc: datetime | None = None


class BusinessStepAdapter(Protocol):
    adapter_code: str
    adapter_version: str
    module_code: str

    def execute(self, context: StepContext) -> OrchestrationStepResult: ...


def result_hash(summary: dict[str, Any]) -> str:
    raw = json.dumps(summary, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def object_refs_from_data(data: dict[str, Any], mapping: dict[str, str], *, primary_key: str | None = None) -> tuple[BusinessObjectRef | None, tuple[BusinessObjectRef, ...]]:
    refs: list[BusinessObjectRef] = []
    primary: BusinessObjectRef | None = None
    for data_key, object_type in mapping.items():
        value = data.get(data_key)
        values = value if isinstance(value, list) else [value]
        for item in values:
            if item in (None, "", []):
                continue
            ref = BusinessObjectRef(object_type=object_type, object_id=str(item), role="output")
            refs.append(ref)
            if data_key == primary_key and primary is None:
                primary = BusinessObjectRef(object_type=object_type, object_id=str(item), role="primary")
    if primary is not None:
        refs.insert(0, primary)
    return primary, tuple(refs)


def step_result_from_service_result(
    *,
    step_code: str,
    module_code: str,
    adapter_code: str,
    adapter_version: str,
    service_result: ServiceResult,
    object_mapping: dict[str, str] | None = None,
    primary_key: str | None = None,
    default_unknown_flow: str = "COMPLETE",
) -> OrchestrationStepResult:
    if service_result.status not in NORMALIZED_BY_SERVICE_STATUS:
        return failed_step_result(
            step_code=step_code,
            module_code=module_code,
            adapter_code=adapter_code,
            adapter_version=adapter_version,
            reason_code="unmapped_business_result",
            message_zh="业务模块返回了未映射状态。",
            raw_result_summary={"status": str(service_result.status), "reason_code": service_result.reason_code},
        )
    normalized = NORMALIZED_BY_SERVICE_STATUS[service_result.status]
    requested_flow = service_result.data.get("flow_action")
    flow = DEFAULT_FLOW_BY_STATUS[service_result.status]
    if service_result.status == ResultStatus.UNKNOWN:
        flow = default_unknown_flow
    if isinstance(requested_flow, str) and requested_flow in SERVICE_FLOW_ACTIONS:
        flow = requested_flow
    if flow not in FLOW_ACTIONS:
        flow = "FAIL"
        normalized = "FAILED"

    primary, refs = object_refs_from_data(service_result.data, object_mapping or {}, primary_key=primary_key)
    summary = sanitize_mapping(
        {
            "status": service_result.status,
            "reason_code": service_result.reason_code,
            "data": {key: value for key, value in service_result.data.items() if key.endswith("_id") or key.endswith("_ids") or key == "flow_action"},
        }
    )
    return OrchestrationStepResult(
        step_code=step_code,
        module_code=module_code,
        adapter_code=adapter_code,
        adapter_version=adapter_version,
        normalized_status=normalized,
        flow_action=flow,
        reason_code=service_result.reason_code,
        message_zh=service_result.message,
        primary_object_ref=primary,
        business_object_refs=refs,
        raw_business_status=str(service_result.status),
        raw_result_summary=summary,
        raw_result_hash=result_hash(summary),
        needs_manual_attention=normalized in {"UNKNOWN", "FAILED"},
    )


def failed_step_result(
    *,
    step_code: str,
    module_code: str,
    adapter_code: str,
    adapter_version: str,
    reason_code: str,
    message_zh: str,
    raw_result_summary: dict[str, Any] | None = None,
) -> OrchestrationStepResult:
    summary = sanitize_mapping(raw_result_summary or {"reason_code": reason_code})
    return OrchestrationStepResult(
        step_code=step_code,
        module_code=module_code,
        adapter_code=adapter_code,
        adapter_version=adapter_version,
        normalized_status="FAILED",
        flow_action="FAIL",
        reason_code=reason_code,
        message_zh=message_zh,
        primary_object_ref=None,
        business_object_refs=(),
        raw_business_status="",
        raw_result_summary=summary,
        raw_result_hash=result_hash(summary),
        needs_manual_attention=True,
    )


def missing_input_result(
    *,
    context: StepContext,
    module_code: str,
    adapter_code: str,
    adapter_version: str,
    missing_object_type: str,
) -> OrchestrationStepResult:
    return failed_step_result(
        step_code=context.step_code,
        module_code=module_code,
        adapter_code=adapter_code,
        adapter_version=adapter_version,
        reason_code="orchestration_required_input_missing",
        message_zh=f"编排衔接器缺少明确输入对象：{missing_object_type}。",
        raw_result_summary={"missing_object_type": missing_object_type},
    )

