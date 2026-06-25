"""RuntimeGuard service.

Module: RuntimeGuard
Responsibility: run read-only checks and persist guard issues/alerts when explicitly confirmed.
Not responsible for recovery, lock release, business mutation, Binance, DeepSeek,
Hermes sending, or trade execution.
Database: writes RuntimeGuard audit facts and AlertEvent only when confirm_write is true.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from django.db import transaction
from django.utils import timezone

from apps.alerts.services import record_alert_event

from ..checks.default import IssueDraft, collect_default_issue_drafts
from ..models import RuntimeGuardIssue, RuntimeGuardIssueStatus, RuntimeGuardRun, RuntimeGuardRunStatus


@dataclass(frozen=True)
class RuntimeGuardSummary:
    run_id: int | None
    dry_run: bool
    checked_item_count: int
    created_issue_count: int
    updated_issue_count: int
    alert_event_count: int
    issue_types: tuple[str, ...]


def run_runtime_guard(
    *,
    trace_id: str,
    trigger_source: str = "celery_beat",
    dry_run: bool = True,
    confirm_write: bool = False,
    reference_time_utc: datetime | None = None,
    issue_drafts: list[IssueDraft] | None = None,
) -> RuntimeGuardSummary:
    now = _ensure_utc(reference_time_utc or timezone.now())
    drafts = issue_drafts if issue_drafts is not None else collect_default_issue_drafts()
    if dry_run and not confirm_write:
        return RuntimeGuardSummary(
            run_id=None,
            dry_run=True,
            checked_item_count=len(drafts),
            created_issue_count=0,
            updated_issue_count=0,
            alert_event_count=0,
            issue_types=tuple(sorted({draft.issue_type for draft in drafts})),
        )

    run_key = _stable_hash({"kind": "runtime_guard", "time_bucket": now.replace(second=0, microsecond=0).isoformat(), "trigger_source": trigger_source})
    created_count = 0
    updated_count = 0
    alert_count = 0
    with transaction.atomic():
        run, _ = RuntimeGuardRun.objects.get_or_create(
            run_key=run_key,
            defaults={
                "status": RuntimeGuardRunStatus.RUNNING,
                "trigger_source": trigger_source,
                "trace_id": trace_id,
                "started_at_utc": now,
            },
        )
        for draft in drafts:
            issue_key = _stable_hash(draft.issue_key_parts)
            issue, created = RuntimeGuardIssue.objects.get_or_create(
                issue_key=issue_key,
                defaults={
                    "issue_type": draft.issue_type,
                    "severity": draft.severity,
                    "status": RuntimeGuardIssueStatus.OPEN,
                    "first_seen_at_utc": now,
                    "last_seen_at_utc": now,
                    "related_object_type": draft.related_object_type,
                    "related_object_id": draft.related_object_id,
                    "related_trace_id": draft.related_trace_id,
                    "description_zh": draft.description_zh,
                    "evidence": draft.evidence,
                    "needs_manual_attention": draft.needs_manual_attention,
                },
            )
            if created:
                created_count += 1
            else:
                issue.last_seen_at_utc = now
                issue.occurrence_count += 1
                issue.evidence = draft.evidence
                issue.description_zh = draft.description_zh
                issue.status = RuntimeGuardIssueStatus.OPEN if issue.status == RuntimeGuardIssueStatus.RESOLVED else issue.status
                issue.save(update_fields=["last_seen_at_utc", "occurrence_count", "evidence", "description_zh", "status", "updated_at_utc"])
                updated_count += 1
            if created or issue.alert_event_id is None:
                alert = _record_issue_alert(issue, trace_id=trace_id, trigger_source=trigger_source)
                issue.alert_event_id = alert.id
                issue.last_alerted_at_utc = now
                issue.save(update_fields=["alert_event_id", "last_alerted_at_utc", "updated_at_utc"])
                alert_count += 1
        run.status = RuntimeGuardRunStatus.SUCCEEDED
        run.finished_at_utc = now
        run.checked_item_count = len(drafts)
        run.created_issue_count = created_count
        run.updated_issue_count = updated_count
        run.alert_event_count = alert_count
        run.reason_code = "runtime_guard_completed"
        run.reason_message = "RuntimeGuard 巡检完成"
        run.save()
    return RuntimeGuardSummary(
        run_id=run.id,
        dry_run=False,
        checked_item_count=len(drafts),
        created_issue_count=created_count,
        updated_issue_count=updated_count,
        alert_event_count=alert_count,
        issue_types=tuple(sorted({draft.issue_type for draft in drafts})),
    )


def _record_issue_alert(issue: RuntimeGuardIssue, *, trace_id: str, trigger_source: str):
    return record_alert_event(
        event_key=_stable_hash({"kind": "runtime_guard_issue", "issue_id": issue.id, "occurrence": issue.occurrence_count}),
        source_module="runtime_guard",
        event_type=issue.issue_type,
        event_category="runtime_guard",
        severity=issue.severity,
        title_zh="RuntimeGuard 巡检发现问题",
        message_zh=issue.description_zh,
        trace_id=trace_id,
        trigger_source=trigger_source,
        related_object_type=issue.related_object_type,
        related_object_id=issue.related_object_id,
        business_status=issue.status,
        reason_code=issue.issue_type,
        payload_summary=issue.evidence,
        delivery_enabled=False,
    )


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _stable_hash(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()
