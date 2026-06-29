"""ReviewDataset 模块：只读查询 ReviewDataset 记录与导出事实。

负责：为 OpsConsole/API 返回脱敏查询结果。
不负责：生成数据集、创建导出、调用外部服务、修改交易链路。
读写数据库：只读 MySQL。
访问 Redis：不涉及。
访问外部服务：不涉及。
发送 Hermes：不涉及。
调用大模型：不涉及。
涉及交易执行：不涉及。
允许真实交易：不允许。
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from decimal import Decimal
from typing import Any

from django.core.exceptions import ObjectDoesNotExist
from django.db.models import QuerySet

from apps.foundation.redaction import sanitize_mapping, sanitize_value

from .models import ReviewDatasetExport, ReviewDatasetRecord


DEFAULT_LIMIT = 20
MAX_LIMIT = 100


class ReviewDatasetObjectNotFound(LookupError):
    pass


def list_review_dataset_records(params: Mapping[str, Any]) -> dict[str, Any]:
    queryset = ReviewDatasetRecord.objects.order_by("-period_start_utc", "-id")
    for field in ("build_status", "market_type", "account_domain", "symbol", "trace_id"):
        if value := params.get(field):
            queryset = queryset.filter(**{field: value})
    rows, pagination = _paginated(queryset, params)
    return {"items": [_record_row(record) for record in rows], "pagination": pagination}


def get_review_dataset_record_detail(record_id: int) -> dict[str, Any]:
    try:
        record = ReviewDatasetRecord.objects.select_related(
            "subject_orchestration_run",
            "start_boundary_orchestration_run",
            "end_boundary_orchestration_run",
            "cleanup_orchestration_run",
        ).get(id=record_id)
    except ObjectDoesNotExist as exc:
        raise ReviewDatasetObjectNotFound(f"ReviewDatasetRecord {record_id} not found") from exc
    row = _record_row(record)
    row.update(
        {
            "object_refs": _clean(record.object_refs),
            "summary": _clean(record.summary),
            "missing_facts": _clean(record.missing_facts),
        }
    )
    return row


def list_review_dataset_exports(params: Mapping[str, Any]) -> dict[str, Any]:
    queryset = ReviewDatasetExport.objects.order_by("-created_at_utc", "-id")
    for field in ("status", "export_format", "requested_by", "trace_id", "export_key"):
        if value := params.get(field):
            queryset = queryset.filter(**{field: value})
    rows, pagination = _paginated(queryset, params)
    return {"items": [_export_row(export) for export in rows], "pagination": pagination}


def get_review_dataset_export_detail(export_id: int) -> dict[str, Any]:
    try:
        export = ReviewDatasetExport.objects.get(id=export_id)
    except ObjectDoesNotExist as exc:
        raise ReviewDatasetObjectNotFound(f"ReviewDatasetExport {export_id} not found") from exc
    row = _export_row(export)
    row.update(
        {
            "range_selector": _clean(export.range_selector),
            "filters": _clean(export.filters),
            "row_counts": _clean(export.row_counts),
            "file_list": _clean(export.file_list),
            "manifest": _clean(export.manifest),
        }
    )
    return row


def latest_review_dataset_summary() -> dict[str, Any]:
    latest_record = ReviewDatasetRecord.objects.order_by("-built_at_utc", "-id").first()
    latest_export = ReviewDatasetExport.objects.order_by("-created_at_utc", "-id").first()
    return {
        "record_count": ReviewDatasetRecord.objects.count(),
        "export_count": ReviewDatasetExport.objects.count(),
        "latest_record": _record_row(latest_record) if latest_record is not None else None,
        "latest_export": _export_row(latest_export) if latest_export is not None else None,
    }


def _record_row(record: ReviewDatasetRecord) -> dict[str, Any]:
    return {
        "id": record.id,
        "subject_orchestration_run_id": record.subject_orchestration_run_id,
        "start_boundary_orchestration_run_id": record.start_boundary_orchestration_run_id,
        "end_boundary_orchestration_run_id": record.end_boundary_orchestration_run_id,
        "cleanup_orchestration_run_id": record.cleanup_orchestration_run_id,
        "period_start_utc": _dt(record.period_start_utc),
        "period_end_utc": _dt(record.period_end_utc),
        "exchange": record.exchange,
        "market_type": record.market_type,
        "account_domain": record.account_domain,
        "symbol": record.symbol,
        "dataset_schema_version": record.dataset_schema_version,
        "build_status": record.build_status,
        "reason_code": record.reason_code,
        "reason_message": record.reason_message,
        "object_counts": _clean(record.object_counts),
        "missing_fact_count": len(record.missing_facts or []),
        "input_refs_hash": record.input_refs_hash,
        "record_content_hash": record.record_content_hash,
        "trace_id": record.trace_id,
        "trigger_source": record.trigger_source,
        "operator_id": record.operator_id,
        "built_at_utc": _dt(record.built_at_utc),
        "created_at_utc": _dt(record.created_at_utc),
    }


def _export_row(export: ReviewDatasetExport) -> dict[str, Any]:
    return {
        "id": export.id,
        "export_key": export.export_key,
        "status": export.status,
        "export_format": export.export_format,
        "dataset_schema_version": export.dataset_schema_version,
        "record_count": export.record_count,
        "file_count": export.file_count,
        "content_hash": export.content_hash,
        "storage_ref": export.storage_ref,
        "reason_code": export.reason_code,
        "reason_message": export.reason_message,
        "requested_by": export.requested_by,
        "reason": export.reason,
        "trace_id": export.trace_id,
        "trigger_source": export.trigger_source,
        "created_at_utc": _dt(export.created_at_utc),
        "completed_at_utc": _dt(export.completed_at_utc),
        "downloaded_at_utc": _dt(export.downloaded_at_utc),
    }


def _paginated(queryset: QuerySet[Any], params: Mapping[str, Any]) -> tuple[list[Any], dict[str, int]]:
    limit = _int_param(params, "limit", default=DEFAULT_LIMIT)
    offset = _int_param(params, "offset", default=0, min_value=0, max_value=10000)
    total = queryset.count()
    rows = list(queryset[offset : offset + limit])
    return rows, {"limit": limit, "offset": offset, "total": total}


def _int_param(params: Mapping[str, Any], name: str, *, default: int, min_value: int = 1, max_value: int = MAX_LIMIT) -> int:
    raw = params.get(name)
    if raw in (None, ""):
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return default
    return max(min_value, min(value, max_value))


def _dt(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _clean(value: Any, *, depth: int = 0) -> Any:
    if depth > 3:
        return "[TRUNCATED]"
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return _dt(value)
    if isinstance(value, Mapping):
        return sanitize_mapping({str(k): _clean(v, depth=depth + 1) for k, v in list(value.items())[:80]})
    if isinstance(value, list):
        return [_clean(item, depth=depth + 1) for item in value[:200]]
    if isinstance(value, str):
        return sanitize_value(value[:2000])
    return value
