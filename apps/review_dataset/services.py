"""ReviewDataset 模块：生成离线复盘数据集与导出清单。

负责：读取已落库编排、业务对象链接、告警和审计事实，生成 ReviewDatasetRecord / ReviewDatasetExport。
不负责：判断策略对错、计算收益、调用大模型、请求 Binance、提交订单、修改上游业务事实。
读写数据库：读取已落库事实，写 ReviewDatasetRecord / ReviewDatasetExport / AuditRecord / AlertEvent。
访问 Redis：不涉及。
访问外部服务：不涉及。
发送 Hermes：不涉及；只写 AlertEvent。
调用大模型：不涉及。
涉及交易执行：不涉及。
允许真实交易：不允许。
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any

from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.alerts.services import record_alert_event
from apps.audit.services import record_audit
from apps.execution.models import OrderSubmissionAttempt
from apps.fill_sync.models import FillSyncResult, OrderFillSummary, TradeFill
from apps.foundation.redaction import sanitize_mapping
from apps.foundation.results import ResultStatus, ServiceResult
from apps.order_lifecycle.models import OrderCancelAttempt
from apps.order_status_sync.models import OrderStatusSyncRecord
from apps.orchestration.models import OrchestrationBusinessObjectLink, OrchestrationRun

from .models import ReviewDatasetBuildStatus, ReviewDatasetExport, ReviewDatasetExportStatus, ReviewDatasetRecord


SOURCE_MODULE = "review_dataset"
TRIGGER_SOURCE_OPS_CONSOLE = "ops_console_review_dataset"
PERIOD_LENGTH = timedelta(hours=4)
SUPPORTED_EXPORT_FORMATS = frozenset({"json", "jsonl"})


@dataclass(frozen=True)
class SelectedRuns:
    runs: list[OrchestrationRun]
    reason_code: str
    message: str


def preview_review_dataset(
    *,
    range_selector: Mapping[str, Any],
    filters: Mapping[str, Any] | None = None,
    trace_id: str = "",
    trigger_source: str = TRIGGER_SOURCE_OPS_CONSOLE,
) -> ServiceResult:
    selected = _select_runs(range_selector)
    if not selected.runs:
        return ServiceResult(
            status=ResultStatus.BLOCKED,
            reason_code=selected.reason_code,
            message=selected.message,
            trace_id=trace_id,
            trigger_source=trigger_source,
            data={"record_count": 0, "items": []},
        )
    items = [_record_preview(run, filters or {}) for run in selected.runs]
    return ServiceResult(
        status=ResultStatus.SUCCEEDED,
        reason_code="review_dataset_preview_ready",
        message="ReviewDataset 预览已生成。",
        trace_id=trace_id,
        trigger_source=trigger_source,
        data={
            "record_count": len(items),
            "items": items,
        },
    )


def build_review_dataset_records(
    *,
    range_selector: Mapping[str, Any],
    filters: Mapping[str, Any] | None = None,
    operator_id: str = "",
    reason: str = "",
    trace_id: str = "",
    trigger_source: str = TRIGGER_SOURCE_OPS_CONSOLE,
) -> ServiceResult:
    selected = _select_runs(range_selector)
    if not selected.runs:
        return ServiceResult(
            status=ResultStatus.BLOCKED,
            reason_code=selected.reason_code,
            message=selected.message,
            trace_id=trace_id,
            trigger_source=trigger_source,
            data={"record_ids": [], "record_count": 0},
        )

    records: list[ReviewDatasetRecord] = []
    with transaction.atomic():
        for run in selected.runs:
            records.append(_build_record(run=run, filters=filters or {}, operator_id=operator_id, trace_id=trace_id, trigger_source=trigger_source))
        audit = record_audit(
            operator_id=operator_id,
            operation_type="review_dataset_records_build",
            target_object_type="ReviewDatasetRecord",
            target_object_id="",
            before_state_summary={},
            after_state_summary={"record_ids": [record.id for record in records], "record_count": len(records)},
            reason=(reason or "生成 ReviewDatasetRecord")[:500],
            evidence={"range_selector": dict(range_selector), "filters": dict(filters or {})},
            result="succeeded",
            trace_id=trace_id,
            trigger_source=trigger_source,
        )
        _alert(
            event_key=_stable_hash({"event": "records_built", "audit_id": audit.id, "record_ids": [record.id for record in records]}),
            event_type="review_dataset_records_built",
            reason_code="review_dataset_records_built",
            message="ReviewDatasetRecord 已生成。",
            trace_id=trace_id,
            trigger_source=trigger_source,
            related_object_type="AuditRecord",
            related_object_id=str(audit.id),
            payload={"record_count": len(records), "record_ids": [record.id for record in records]},
        )

    return ServiceResult(
        status=ResultStatus.SUCCEEDED,
        reason_code="review_dataset_records_built",
        message="ReviewDatasetRecord 已生成。",
        trace_id=trace_id,
        trigger_source=trigger_source,
        data={"audit_record_id": audit.id, "record_ids": [record.id for record in records], "record_count": len(records)},
    )


def create_review_dataset_export(
    *,
    range_selector: Mapping[str, Any],
    filters: Mapping[str, Any] | None,
    export_format: str,
    operator_id: str,
    reason: str,
    trace_id: str,
    trigger_source: str = TRIGGER_SOURCE_OPS_CONSOLE,
) -> ServiceResult:
    normalized_format = export_format.strip().lower() or "json"
    allowed_formats = _allowed_export_formats()
    if normalized_format not in allowed_formats:
        return ServiceResult(
            status=ResultStatus.BLOCKED,
            reason_code="review_dataset_export_format_not_allowed",
            message="ReviewDataset 导出格式不在允许范围内。",
            trace_id=trace_id,
            trigger_source=trigger_source,
            data={"allowed_formats": sorted(allowed_formats)},
        )
    if not reason.strip():
        return ServiceResult(
            status=ResultStatus.BLOCKED,
            reason_code="review_dataset_export_reason_required",
            message="ReviewDataset 导出必须记录人工原因。",
            trace_id=trace_id,
            trigger_source=trigger_source,
        )

    build_result = build_review_dataset_records(
        range_selector=range_selector,
        filters=filters or {},
        operator_id=operator_id,
        reason=reason,
        trace_id=trace_id,
        trigger_source=trigger_source,
    )
    if build_result.status != ResultStatus.SUCCEEDED:
        return build_result

    record_ids = [int(value) for value in build_result.data.get("record_ids", [])]
    records = list(ReviewDatasetRecord.objects.filter(id__in=record_ids).order_by("period_start_utc", "id"))
    payload = _export_payload(records=records, range_selector=range_selector, filters=filters or {}, export_format=normalized_format)
    content = _serialize_export_payload(payload, normalized_format)
    content_hash = _stable_hash({"format": normalized_format, "content": content})
    export_key = _stable_hash(
        {
            "range_selector": dict(range_selector),
            "filters": dict(filters or {}),
            "format": normalized_format,
            "schema": _schema_version(),
            "record_hashes": [record.record_content_hash for record in records],
        }
    )
    storage_ref = _write_export_file(export_key=export_key, export_format=normalized_format, content=content)
    manifest = {
        "export_key": export_key,
        "dataset_schema_version": _schema_version(),
        "export_format": normalized_format,
        "record_count": len(records),
        "record_ids": [record.id for record in records],
        "content_hash": content_hash,
        "storage_ref": storage_ref,
    }

    with transaction.atomic():
        export, created = ReviewDatasetExport.objects.get_or_create(
            export_key=export_key,
            defaults={
                "status": ReviewDatasetExportStatus.BUILT,
                "range_selector": dict(range_selector),
                "filters": dict(filters or {}),
                "export_format": normalized_format,
                "dataset_schema_version": _schema_version(),
                "record_count": len(records),
                "file_count": 1 if records else 0,
                "row_counts": {"review_dataset_records": len(records)},
                "file_list": [{"path": storage_ref, "format": normalized_format, "content_hash": content_hash}],
                "manifest": manifest,
                "content_hash": content_hash,
                "storage_ref": storage_ref,
                "reason_code": "review_dataset_export_built",
                "reason_message": "ReviewDataset 导出已生成。",
                "requested_by": operator_id,
                "reason": reason[:500],
                "trace_id": trace_id,
                "trigger_source": trigger_source,
                "completed_at_utc": timezone.now(),
            },
        )
        if not created and export.status != ReviewDatasetExportStatus.BUILT:
            export.status = ReviewDatasetExportStatus.BUILT
            export.reason_code = "review_dataset_export_built"
            export.reason_message = "ReviewDataset 导出已生成。"
            export.record_count = len(records)
            export.file_count = 1 if records else 0
            export.row_counts = {"review_dataset_records": len(records)}
            export.file_list = [{"path": storage_ref, "format": normalized_format, "content_hash": content_hash}]
            export.manifest = manifest
            export.content_hash = content_hash
            export.storage_ref = storage_ref
            export.completed_at_utc = timezone.now()
            export.save()
        audit = record_audit(
            operator_id=operator_id,
            operation_type="review_dataset_export_create",
            target_object_type="ReviewDatasetExport",
            target_object_id=str(export.id),
            before_state_summary={},
            after_state_summary={"export_id": export.id, "export_key": export.export_key, "record_count": export.record_count},
            reason=reason[:500],
            evidence={"range_selector": dict(range_selector), "filters": dict(filters or {}), "export_format": normalized_format},
            result="succeeded",
            trace_id=trace_id,
            trigger_source=trigger_source,
        )
        _alert(
            event_key=_stable_hash({"event": "export_built", "export_id": export.id, "content_hash": content_hash}),
            event_type="review_dataset_export_built",
            reason_code="review_dataset_export_built",
            message="ReviewDatasetExport 已生成。",
            trace_id=trace_id,
            trigger_source=trigger_source,
            related_object_type="ReviewDatasetExport",
            related_object_id=str(export.id),
            payload={"export_id": export.id, "record_count": len(records), "audit_record_id": audit.id},
        )

    return ServiceResult(
        status=ResultStatus.SUCCEEDED,
        reason_code="review_dataset_export_built",
        message="ReviewDatasetExport 已生成。",
        trace_id=trace_id,
        trigger_source=trigger_source,
        data={"export_id": export.id, "export_key": export.export_key, "record_count": export.record_count, "storage_ref": export.storage_ref},
    )


def mark_review_dataset_export_downloaded(
    *,
    export_id: int,
    operator_id: str,
    trace_id: str,
    trigger_source: str = TRIGGER_SOURCE_OPS_CONSOLE,
) -> ServiceResult:
    export = ReviewDatasetExport.objects.get(id=export_id)
    export.downloaded_at_utc = timezone.now()
    export.save(update_fields=["downloaded_at_utc", "updated_at_utc"])
    record_audit(
        operator_id=operator_id,
        operation_type="review_dataset_export_download",
        target_object_type="ReviewDatasetExport",
        target_object_id=str(export.id),
        before_state_summary={},
        after_state_summary={"export_id": export.id, "downloaded_at_utc": export.downloaded_at_utc.isoformat()},
        reason="下载 ReviewDatasetExport",
        evidence={"export_key": export.export_key},
        result="succeeded",
        trace_id=trace_id,
        trigger_source=trigger_source,
    )
    return ServiceResult(
        status=ResultStatus.SUCCEEDED,
        reason_code="review_dataset_export_download_marked",
        message="ReviewDatasetExport 下载审计已记录。",
        trace_id=trace_id,
        trigger_source=trigger_source,
        data={"export_id": export.id, "storage_ref": export.storage_ref, "manifest": export.manifest},
    )


def _select_runs(range_selector: Mapping[str, Any]) -> SelectedRuns:
    run_ids = _run_ids_from_selector(range_selector)
    if not run_ids:
        return SelectedRuns([], "review_dataset_range_empty", "ReviewDataset 导出范围没有选中任何编排。")
    max_periods = int(getattr(settings, "REVIEW_DATASET_MAX_PERIODS_PER_EXPORT", 100))
    if len(run_ids) > max_periods:
        return SelectedRuns([], "review_dataset_range_too_large", "ReviewDataset 单次导出范围超过上限。")
    runs = list(OrchestrationRun.objects.filter(id__in=run_ids).order_by("scheduled_for_utc", "id"))
    if len(runs) != len(set(run_ids)):
        return SelectedRuns([], "review_dataset_run_missing", "ReviewDataset 导出范围中存在不存在的编排。")
    return SelectedRuns(runs, "review_dataset_range_selected", "ReviewDataset 导出范围已选定。")


def _run_ids_from_selector(range_selector: Mapping[str, Any]) -> list[int]:
    candidates: Any
    selector_type = str(range_selector.get("type", "")).strip()
    if "orchestration_run_ids" in range_selector:
        candidates = range_selector.get("orchestration_run_ids")
    elif "run_ids" in range_selector:
        candidates = range_selector.get("run_ids")
    elif selector_type in {"run_ids", "orchestration_run_ids"}:
        candidates = range_selector.get("ids")
    elif "orchestration_run_id" in range_selector:
        candidates = [range_selector.get("orchestration_run_id")]
    else:
        candidates = []
    if not isinstance(candidates, Sequence) or isinstance(candidates, str):
        return []
    ids: list[int] = []
    for item in candidates:
        try:
            value = int(item)
        except (TypeError, ValueError):
            continue
        if value > 0 and value not in ids:
            ids.append(value)
    return ids


def _record_preview(run: OrchestrationRun, filters: Mapping[str, Any]) -> dict[str, Any]:
    prepared = _prepared_record_payload(run=run, filters=filters)
    return {
        "orchestration_run_id": run.id,
        "period_start_utc": prepared["period_start_utc"],
        "period_end_utc": prepared["period_end_utc"],
        "build_status": prepared["build_status"],
        "reason_code": prepared["reason_code"],
        "missing_facts": prepared["missing_facts"],
        "object_counts": prepared["object_counts"],
    }


def _build_record(
    *,
    run: OrchestrationRun,
    filters: Mapping[str, Any],
    operator_id: str,
    trace_id: str,
    trigger_source: str,
) -> ReviewDatasetRecord:
    payload = _prepared_record_payload(run=run, filters=filters)
    input_refs_hash = _stable_hash(payload["input_refs"])
    content_hash = _stable_hash(
        {
            "summary": payload["summary"],
            "object_counts": payload["object_counts"],
            "missing_facts": payload["missing_facts"],
        }
    )
    record, _created = ReviewDatasetRecord.objects.get_or_create(
        subject_orchestration_run=run,
        dataset_schema_version=_schema_version(),
        input_refs_hash=input_refs_hash,
        defaults={
            "start_boundary_orchestration_run": payload["start_boundary_run"],
            "end_boundary_orchestration_run": payload["end_boundary_run"],
            "cleanup_orchestration_run": payload["cleanup_run"],
            "period_start_utc": payload["period_start"],
            "period_end_utc": payload["period_end"],
            "exchange": payload["exchange"],
            "market_type": payload["market_type"],
            "account_domain": payload["account_domain"],
            "symbol": payload["symbol"],
            "build_status": payload["build_status"],
            "reason_code": payload["reason_code"],
            "reason_message": payload["reason_message"],
            "record_content_hash": content_hash,
            "object_counts": payload["object_counts"],
            "object_refs": payload["object_refs"],
            "summary": payload["summary"],
            "missing_facts": payload["missing_facts"],
            "trace_id": trace_id or run.trace_id,
            "trigger_source": trigger_source,
            "operator_id": operator_id,
            "built_at_utc": timezone.now(),
        },
    )
    return record


def _prepared_record_payload(run: OrchestrationRun, filters: Mapping[str, Any]) -> dict[str, Any]:
    links = list(OrchestrationBusinessObjectLink.objects.filter(orchestration_run=run).order_by("step_code", "id"))
    link_counts = Counter(link.object_type for link in links)
    lifecycle_payload = _order_lifecycle_payload(links)
    object_counts = dict(link_counts)
    for object_type, count in lifecycle_payload["object_counts"].items():
        object_counts[object_type] = max(int(object_counts.get(object_type, 0)), int(count))
    object_refs = [
        {
            "step_code": link.step_code,
            "module_code": link.module_code,
            "object_role": link.object_role,
            "object_type": link.object_type,
            "object_id": link.object_id,
            "object_identity_hash": link.object_identity_hash,
            "object_label": link.object_label,
        }
        for link in links
    ]
    object_refs.extend(lifecycle_payload["object_refs"])
    period_start = run.scheduled_for_utc
    period_end = period_start + PERIOD_LENGTH
    start_boundary = _boundary_run_at(period_start)
    end_boundary = _boundary_run_at(period_end)
    missing_facts: list[dict[str, str]] = []
    if start_boundary is None:
        missing_facts.append({"fact": "start_boundary_orchestration_run", "reason_code": "start_boundary_missing"})
    if end_boundary is None:
        missing_facts.append({"fact": "end_boundary_orchestration_run", "reason_code": "end_boundary_missing"})
    if not links:
        missing_facts.append({"fact": "orchestration_business_object_links", "reason_code": "business_links_missing"})
    missing_facts.extend(lifecycle_payload["missing_facts"])

    summary = sanitize_mapping(
        {
            "orchestration_run": {
                "id": run.id,
                "run_key": run.run_key,
                "pipeline_code": run.pipeline_code,
                "scheduled_for_utc": run.scheduled_for_utc.isoformat(),
                "cycle_kind": run.cycle_kind,
                "status": run.status,
                "final_outcome": run.final_outcome,
                "reason_code": run.reason_code,
                "current_step_code": run.current_step_code,
                "last_completed_step_code": run.last_completed_step_code,
                "trace_id": run.trace_id,
            },
            "filters": dict(filters),
            "object_counts": object_counts,
            "order_lifecycle": lifecycle_payload["summary"],
        }
    )
    input_refs = {
        "orchestration_run_id": run.id,
        "orchestration_run_updated_at_utc": run.updated_at_utc.isoformat() if run.updated_at_utc else "",
        "link_refs": [{"id": link.id, "object_type": link.object_type, "object_id": link.object_id, "hash": link.object_identity_hash} for link in links],
        "order_lifecycle_refs": lifecycle_payload["input_refs"],
        "filters": dict(filters),
        "schema_version": _schema_version(),
    }
    return {
        "period_start": period_start,
        "period_end": period_end,
        "period_start_utc": period_start.isoformat(),
        "period_end_utc": period_end.isoformat(),
        "start_boundary_run": start_boundary,
        "end_boundary_run": end_boundary,
        "cleanup_run": None,
        "exchange": str(getattr(settings, "ACTIVE_EXCHANGE", "Binance") or "Binance").lower(),
        "market_type": str(getattr(settings, "ACTIVE_MARKET_TYPE", "")),
        "account_domain": str(getattr(settings, "ACTIVE_ACCOUNT_DOMAIN", "")),
        "symbol": str(getattr(settings, "ACTIVE_SYMBOL", "")),
        "build_status": ReviewDatasetBuildStatus.PARTIAL if missing_facts else ReviewDatasetBuildStatus.BUILT,
        "reason_code": "review_dataset_record_partial" if missing_facts else "review_dataset_record_built",
        "reason_message": "ReviewDatasetRecord 已生成；存在缺失事实。" if missing_facts else "ReviewDatasetRecord 已生成。",
        "object_counts": object_counts,
        "object_refs": object_refs,
        "summary": summary,
        "missing_facts": missing_facts,
        "input_refs": input_refs,
    }


def _order_lifecycle_payload(links: Sequence[OrchestrationBusinessObjectLink]) -> dict[str, Any]:
    attempt_ids = _order_submission_attempt_ids(links)
    if not attempt_ids:
        return {
            "summary": {
                "order_submission_attempts": [],
                "order_cancel_attempts": [],
                "order_status_sync_records": [],
                "fill_sync_results": [],
                "trade_fills": [],
                "order_fill_summaries": [],
            },
            "object_counts": {},
            "object_refs": [],
            "input_refs": [],
            "missing_facts": [],
        }

    attempts = list(OrderSubmissionAttempt.objects.filter(id__in=attempt_ids).order_by("id"))
    ordered_attempt_ids = [attempt.id for attempt in attempts]
    cancel_attempts = list(OrderCancelAttempt.objects.filter(order_submission_attempt_id__in=ordered_attempt_ids).order_by("order_submission_attempt_id", "id"))
    status_records = list(OrderStatusSyncRecord.objects.filter(order_submission_attempt_id__in=ordered_attempt_ids).order_by("order_submission_attempt_id", "poll_mode", "poll_sequence", "id"))
    fill_results = list(FillSyncResult.objects.filter(order_submission_attempt_id__in=ordered_attempt_ids).order_by("order_submission_attempt_id", "sync_sequence", "id"))
    trade_fills = list(TradeFill.objects.filter(order_submission_attempt_id__in=ordered_attempt_ids).order_by("order_submission_attempt_id", "trade_time_utc", "id"))
    fill_summaries = list(OrderFillSummary.objects.filter(order_submission_attempt_id__in=ordered_attempt_ids).order_by("order_submission_attempt_id", "id"))
    object_counts = {
        "OrderSubmissionAttempt": len(attempts),
        "OrderCancelAttempt": len(cancel_attempts),
        "OrderStatusSyncRecord": len(status_records),
        "FillSyncResult": len(fill_results),
        "TradeFill": len(trade_fills),
        "OrderFillSummary": len(fill_summaries),
    }
    return {
        "summary": {
            "order_submission_attempts": [_submission_attempt_row(attempt) for attempt in attempts],
            "order_cancel_attempts": [_cancel_attempt_row(cancel) for cancel in cancel_attempts],
            "order_status_sync_records": [_status_sync_row(record) for record in status_records],
            "fill_sync_results": [_fill_sync_row(result) for result in fill_results],
            "trade_fills": [_trade_fill_row(fill) for fill in trade_fills],
            "order_fill_summaries": [_order_fill_summary_row(summary) for summary in fill_summaries],
        },
        "object_counts": object_counts,
        "object_refs": _derived_order_lifecycle_refs(
            attempts=attempts,
            cancel_attempts=cancel_attempts,
            status_records=status_records,
            fill_results=fill_results,
            trade_fills=trade_fills,
            fill_summaries=fill_summaries,
        ),
        "input_refs": _order_lifecycle_input_refs(
            attempts=attempts,
            cancel_attempts=cancel_attempts,
            status_records=status_records,
            fill_results=fill_results,
            trade_fills=trade_fills,
            fill_summaries=fill_summaries,
        ),
        "missing_facts": _order_lifecycle_missing_facts(
            attempts=attempts,
            requested_attempt_ids=attempt_ids,
            cancel_attempts=cancel_attempts,
            status_records=status_records,
            fill_results=fill_results,
        ),
    }


def _order_submission_attempt_ids(links: Sequence[OrchestrationBusinessObjectLink]) -> list[int]:
    ids = _linked_ids(links, "OrderSubmissionAttempt")
    if ids:
        return ids
    order_plan_ids = _linked_ids(links, "OrderPlan")
    if order_plan_ids:
        return list(OrderSubmissionAttempt.objects.filter(order_plan_id__in=order_plan_ids).order_by("id").values_list("id", flat=True))
    prepared_ids = _linked_ids(links, "PreparedOrderIntent")
    if prepared_ids:
        return list(OrderSubmissionAttempt.objects.filter(prepared_order_intent_id__in=prepared_ids).order_by("id").values_list("id", flat=True))
    return []


def _linked_ids(links: Sequence[OrchestrationBusinessObjectLink], object_type: str) -> list[int]:
    values: list[int] = []
    for link in links:
        if link.object_type != object_type:
            continue
        try:
            value = int(link.object_id)
        except (TypeError, ValueError):
            continue
        if value > 0 and value not in values:
            values.append(value)
    return values


def _submission_attempt_row(attempt: OrderSubmissionAttempt) -> dict[str, Any]:
    return _clean_payload(
        {
            "id": attempt.id,
            "prepared_order_intent_id": attempt.prepared_order_intent_id,
            "approved_order_intent_id": attempt.approved_order_intent_id,
            "candidate_order_intent_id": attempt.candidate_order_intent_id,
            "order_plan_id": attempt.order_plan_id,
            "active_lock_id": attempt.active_lock_id,
            "status": attempt.status,
            "reason_code": attempt.reason_code,
            "exchange": attempt.exchange,
            "market_type": attempt.market_type,
            "account_domain": attempt.account_domain,
            "symbol": attempt.symbol,
            "side": attempt.side,
            "position_side": attempt.position_side,
            "order_type": attempt.order_type,
            "quantity": attempt.quantity,
            "quantity_unit": attempt.quantity_unit,
            "reduce_only": attempt.reduce_only,
            "order_notional": attempt.order_notional,
            "time_in_force": attempt.time_in_force,
            "limit_price": attempt.limit_price,
            "limit_valid_until_utc": attempt.limit_valid_until_utc,
            "price_condition_hash": attempt.price_condition_hash,
            "client_order_id": attempt.client_order_id,
            "exchange_order_id": attempt.exchange_order_id,
            "exchange_status": attempt.exchange_status,
            "request_sent": attempt.request_sent,
            "response_received": attempt.response_received,
            "gateway_attempt_count": attempt.gateway_attempt_count,
            "trace_id": attempt.trace_id,
            "trigger_source": attempt.trigger_source,
            "submitted_at_utc": attempt.submitted_at_utc,
            "finished_at_utc": attempt.finished_at_utc,
            "updated_at_utc": attempt.updated_at_utc,
        }
    )


def _cancel_attempt_row(cancel: OrderCancelAttempt) -> dict[str, Any]:
    return _clean_payload(
        {
            "id": cancel.id,
            "order_submission_attempt_id": cancel.order_submission_attempt_id,
            "active_lock_id": cancel.active_lock_id,
            "cancel_status": cancel.cancel_status,
            "reason_code": cancel.reason_code,
            "cancel_reason_code": cancel.cancel_reason_code,
            "request_sent": cancel.request_sent,
            "response_received": cancel.response_received,
            "gateway_attempt_count": cancel.gateway_attempt_count,
            "client_order_id": cancel.client_order_id,
            "exchange_order_id": cancel.exchange_order_id,
            "closeout_time_utc": cancel.closeout_time_utc,
            "limit_valid_until_utc": cancel.limit_valid_until_utc,
            "request_payload_hash": cancel.request_payload_hash,
            "response_hash": cancel.response_hash,
            "trace_id": cancel.trace_id,
            "trigger_source": cancel.trigger_source,
            "finished_at_utc": cancel.finished_at_utc,
            "updated_at_utc": cancel.updated_at_utc,
        }
    )


def _status_sync_row(record: OrderStatusSyncRecord) -> dict[str, Any]:
    return _clean_payload(
        {
            "id": record.id,
            "order_submission_attempt_id": record.order_submission_attempt_id,
            "active_lock_id": record.active_lock_id,
            "poll_mode": record.poll_mode,
            "poll_sequence": record.poll_sequence,
            "query_outcome": record.query_outcome,
            "reason_code": record.reason_code,
            "request_sent": record.request_sent,
            "response_received": record.response_received,
            "gateway_attempt_count": record.gateway_attempt_count,
            "exchange_order_id_returned": record.exchange_order_id_returned,
            "exchange_client_order_id_returned": record.exchange_client_order_id_returned,
            "exchange_status": record.exchange_status,
            "is_recognized_status": record.is_recognized_status,
            "is_terminal_status": record.is_terminal_status,
            "submission_resolution_status": record.submission_resolution_status,
            "response_hash": record.response_hash,
            "trace_id": record.trace_id,
            "trigger_source": record.trigger_source,
            "query_started_at_utc": record.query_started_at_utc,
            "query_finished_at_utc": record.query_finished_at_utc,
            "updated_at_utc": record.updated_at_utc,
        }
    )


def _fill_sync_row(result: FillSyncResult) -> dict[str, Any]:
    return _clean_payload(
        {
            "id": result.id,
            "order_submission_attempt_id": result.order_submission_attempt_id,
            "terminal_order_status_sync_record_id": result.terminal_order_status_sync_record_id,
            "active_lock_id": result.active_lock_id,
            "sync_sequence": result.sync_sequence,
            "sync_mode": result.sync_mode,
            "status": result.status,
            "reason_code": result.reason_code,
            "terminal_exchange_status": result.terminal_exchange_status,
            "terminal_executed_quantity": result.terminal_executed_quantity,
            "terminal_cumulative_quote_quantity": result.terminal_cumulative_quote_quantity,
            "page_count": result.page_count,
            "pagination_complete": result.pagination_complete,
            "returned_fill_count": result.returned_fill_count,
            "inserted_fill_count": result.inserted_fill_count,
            "duplicate_fill_count": result.duplicate_fill_count,
            "conflict_fill_count": result.conflict_fill_count,
            "input_hash": result.input_hash,
            "trace_id": result.trace_id,
            "trigger_source": result.trigger_source,
            "sync_started_at_utc": result.sync_started_at_utc,
            "sync_finished_at_utc": result.sync_finished_at_utc,
            "updated_at_utc": result.updated_at_utc,
        }
    )


def _trade_fill_row(fill: TradeFill) -> dict[str, Any]:
    return _clean_payload(
        {
            "id": fill.id,
            "order_submission_attempt_id": fill.order_submission_attempt_id,
            "terminal_order_status_sync_record_id": fill.terminal_order_status_sync_record_id,
            "first_seen_fill_sync_result_id": fill.first_seen_fill_sync_result_id,
            "exchange_trade_id": fill.exchange_trade_id,
            "side": fill.side,
            "position_side": fill.position_side,
            "price": fill.price,
            "quantity": fill.quantity,
            "quantity_unit": fill.quantity_unit,
            "quote_quantity": fill.quote_quantity,
            "base_quantity": fill.base_quantity,
            "commission": fill.commission,
            "commission_asset": fill.commission_asset,
            "realized_pnl": fill.realized_pnl,
            "realized_pnl_asset": fill.realized_pnl_asset,
            "is_buyer": fill.is_buyer,
            "is_maker": fill.is_maker,
            "trade_time_utc": fill.trade_time_utc,
            "raw_fill_hash": fill.raw_fill_hash,
            "trigger_source": fill.trigger_source,
            "created_at_utc": fill.created_at_utc,
        }
    )


def _order_fill_summary_row(summary: OrderFillSummary) -> dict[str, Any]:
    return _clean_payload(
        {
            "id": summary.id,
            "order_submission_attempt_id": summary.order_submission_attempt_id,
            "latest_fill_sync_result_id": summary.latest_fill_sync_result_id,
            "terminal_order_status_sync_record_id": summary.terminal_order_status_sync_record_id,
            "status": summary.status,
            "reason_code": summary.reason_code,
            "terminal_exchange_status": summary.terminal_exchange_status,
            "fill_count": summary.fill_count,
            "total_quantity": summary.total_quantity,
            "total_quote_quantity": summary.total_quote_quantity,
            "total_base_quantity": summary.total_base_quantity,
            "filled_notional_usd": summary.filled_notional_usd,
            "average_price": summary.average_price,
            "quantity_reconciled": summary.quantity_reconciled,
            "quote_reconciled": summary.quote_reconciled,
            "identity_reconciled": summary.identity_reconciled,
            "pagination_complete": summary.pagination_complete,
            "lock_finalization_status": summary.lock_finalization_status,
            "lock_finalized_at_utc": summary.lock_finalized_at_utc,
            "summary_hash": summary.summary_hash,
            "created_at_utc": summary.created_at_utc,
            "updated_at_utc": summary.updated_at_utc,
        }
    )


def _derived_order_lifecycle_refs(
    *,
    attempts: Sequence[OrderSubmissionAttempt],
    cancel_attempts: Sequence[OrderCancelAttempt],
    status_records: Sequence[OrderStatusSyncRecord],
    fill_results: Sequence[FillSyncResult],
    trade_fills: Sequence[TradeFill],
    fill_summaries: Sequence[OrderFillSummary],
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for object_type, objects in (
        ("OrderSubmissionAttempt", attempts),
        ("OrderCancelAttempt", cancel_attempts),
        ("OrderStatusSyncRecord", status_records),
        ("FillSyncResult", fill_results),
        ("TradeFill", trade_fills),
        ("OrderFillSummary", fill_summaries),
    ):
        rows.extend(
            {
                "step_code": "derived_order_lifecycle",
                "module_code": "review_dataset",
                "object_role": "related",
                "object_type": object_type,
                "object_id": str(item.id),
                "object_identity_hash": _stable_hash({"object_type": object_type, "id": item.id})[:64],
                "object_label": f"{object_type}<{item.id}>",
            }
            for item in objects
        )
    return rows


def _order_lifecycle_input_refs(
    *,
    attempts: Sequence[OrderSubmissionAttempt],
    cancel_attempts: Sequence[OrderCancelAttempt],
    status_records: Sequence[OrderStatusSyncRecord],
    fill_results: Sequence[FillSyncResult],
    trade_fills: Sequence[TradeFill],
    fill_summaries: Sequence[OrderFillSummary],
) -> list[dict[str, str]]:
    refs: list[dict[str, str]] = []
    for object_type, objects in (
        ("OrderSubmissionAttempt", attempts),
        ("OrderCancelAttempt", cancel_attempts),
        ("OrderStatusSyncRecord", status_records),
        ("FillSyncResult", fill_results),
        ("TradeFill", trade_fills),
        ("OrderFillSummary", fill_summaries),
    ):
        refs.extend(
            {
                "object_type": object_type,
                "object_id": str(item.id),
                "updated_at_utc": _dt_or_empty(getattr(item, "updated_at_utc", None)),
            }
            for item in objects
        )
    return refs


def _order_lifecycle_missing_facts(
    *,
    attempts: Sequence[OrderSubmissionAttempt],
    requested_attempt_ids: Sequence[int],
    cancel_attempts: Sequence[OrderCancelAttempt],
    status_records: Sequence[OrderStatusSyncRecord],
    fill_results: Sequence[FillSyncResult],
) -> list[dict[str, str]]:
    missing: list[dict[str, str]] = []
    status_attempt_ids = {record.order_submission_attempt_id for record in status_records}
    terminal_status_ids = {record.order_submission_attempt_id for record in status_records if record.is_terminal_status}
    fill_attempt_ids = {result.order_submission_attempt_id for result in fill_results}
    cancel_attempt_ids = {cancel.order_submission_attempt_id for cancel in cancel_attempts}
    for attempt in attempts:
        if attempt.status in {"accepted", "unknown"} and attempt.id not in status_attempt_ids:
            missing.append({"fact": "order_status_sync_record", "reason_code": "order_status_sync_missing", "order_submission_attempt_id": str(attempt.id)})
        if attempt.id in terminal_status_ids and attempt.id not in fill_attempt_ids:
            missing.append({"fact": "fill_sync_result", "reason_code": "fill_sync_missing_after_terminal_status", "order_submission_attempt_id": str(attempt.id)})
        if attempt.order_type == "LIMIT" and attempt.id not in cancel_attempt_ids and attempt.id not in terminal_status_ids:
            missing.append({"fact": "order_cycle_closeout", "reason_code": "limit_order_closeout_or_terminal_status_missing", "order_submission_attempt_id": str(attempt.id)})
    existing_attempt_ids = {attempt.id for attempt in attempts}
    missing.extend(
        {"fact": "order_submission_attempt", "reason_code": "linked_order_submission_attempt_missing", "order_submission_attempt_id": str(attempt_id)}
        for attempt_id in requested_attempt_ids
        if attempt_id not in existing_attempt_ids
    )
    return missing


def _clean_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    return sanitize_mapping({key: _json_value(value) for key, value in payload.items()})


def _json_value(value: Any) -> Any:
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if hasattr(value, "as_tuple"):
        return str(value)
    return value


def _dt_or_empty(value: Any) -> str:
    return value.isoformat() if value is not None and hasattr(value, "isoformat") else ""


def _boundary_run_at(scheduled_for_utc: Any) -> OrchestrationRun | None:
    return (
        OrchestrationRun.objects.filter(
            pipeline_code="main_trading_pipeline",
            trigger_mode="automatic",
            cycle_kind="4h",
            scheduled_for_utc=scheduled_for_utc,
        )
        .order_by("id")
        .first()
    )


def _export_payload(
    *,
    records: Sequence[ReviewDatasetRecord],
    range_selector: Mapping[str, Any],
    filters: Mapping[str, Any],
    export_format: str,
) -> dict[str, Any]:
    record_rows = [
        {
            "id": record.id,
            "subject_orchestration_run_id": record.subject_orchestration_run_id,
            "start_boundary_orchestration_run_id": record.start_boundary_orchestration_run_id,
            "end_boundary_orchestration_run_id": record.end_boundary_orchestration_run_id,
            "cleanup_orchestration_run_id": record.cleanup_orchestration_run_id,
            "period_start_utc": record.period_start_utc.isoformat(),
            "period_end_utc": record.period_end_utc.isoformat(),
            "exchange": record.exchange,
            "market_type": record.market_type,
            "account_domain": record.account_domain,
            "symbol": record.symbol,
            "dataset_schema_version": record.dataset_schema_version,
            "build_status": record.build_status,
            "reason_code": record.reason_code,
            "object_counts": record.object_counts,
            "object_refs": record.object_refs,
            "summary": record.summary,
            "missing_facts": record.missing_facts,
            "input_refs_hash": record.input_refs_hash,
            "record_content_hash": record.record_content_hash,
            "trace_id": record.trace_id,
            "built_at_utc": record.built_at_utc.isoformat(),
        }
        for record in records
    ]
    return {
        "manifest": {
            "dataset_schema_version": _schema_version(),
            "export_format": export_format,
            "range_selector": dict(range_selector),
            "filters": dict(filters),
            "generated_at_utc": timezone.now().isoformat(),
            "record_count": len(record_rows),
        },
        "review_dataset_records": record_rows,
    }


def _serialize_export_payload(payload: dict[str, Any], export_format: str) -> str:
    if export_format == "jsonl":
        rows = payload.get("review_dataset_records", [])
        return "\n".join(json.dumps(row, ensure_ascii=False, sort_keys=True, default=str) for row in rows) + ("\n" if rows else "")
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str, indent=2)


def _write_export_file(*, export_key: str, export_format: str, content: str) -> str:
    export_dir = _export_dir()
    export_dir.mkdir(parents=True, exist_ok=True)
    suffix = "jsonl" if export_format == "jsonl" else "json"
    path = export_dir / f"{export_key}.{suffix}"
    path.write_text(content, encoding="utf-8")
    try:
        return str(path.relative_to(settings.BASE_DIR))
    except ValueError:
        return str(path)


def _export_dir() -> Path:
    configured = str(getattr(settings, "REVIEW_DATASET_EXPORT_DIR", "review_exports") or "review_exports")
    path = Path(configured)
    if not path.is_absolute():
        path = Path(settings.BASE_DIR) / path
    return path


def _allowed_export_formats() -> set[str]:
    configured = getattr(settings, "REVIEW_DATASET_ALLOWED_EXPORT_FORMATS", ["json", "jsonl"])
    if isinstance(configured, str):
        values = [item.strip().lower() for item in configured.split(",") if item.strip()]
    else:
        values = [str(item).strip().lower() for item in configured]
    return set(values) & SUPPORTED_EXPORT_FORMATS or {"json"}


def _schema_version() -> str:
    return str(getattr(settings, "REVIEW_DATASET_SCHEMA_VERSION", "1.0") or "1.0")


def _stable_hash(payload: Any) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _alert(
    *,
    event_key: str,
    event_type: str,
    reason_code: str,
    message: str,
    trace_id: str,
    trigger_source: str,
    related_object_type: str,
    related_object_id: str,
    payload: Mapping[str, Any],
) -> None:
    record_alert_event(
        event_key=event_key,
        source_module=SOURCE_MODULE,
        event_type=event_type,
        event_category="review_dataset",
        severity="info",
        title_zh="ReviewDataset 事件",
        message_zh=message,
        reason_code=reason_code,
        reason_message=message,
        trace_id=trace_id,
        trigger_source=trigger_source,
        related_object_type=related_object_type,
        related_object_id=related_object_id,
        payload_summary=dict(payload),
        delivery_enabled=False,
    )
