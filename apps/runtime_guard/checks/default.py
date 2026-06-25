"""RuntimeGuard default checks.

Module: RuntimeGuard
Responsibility: read-only detection of stuck orchestration/order/notification facts.
Not responsible for recovery, lock release, business mutation, Binance, DeepSeek,
Hermes sending, or trade execution.
Database: read-only in checks.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

from django.conf import settings
from django.utils import timezone


@dataclass(frozen=True)
class IssueDraft:
    issue_type: str
    severity: str
    related_object_type: str
    related_object_id: str
    related_trace_id: str
    description_zh: str
    evidence: dict[str, Any] = field(default_factory=dict)
    needs_manual_attention: bool = True

    @property
    def issue_key_parts(self) -> dict[str, str]:
        return {
            "issue_type": self.issue_type,
            "object_type": self.related_object_type,
            "object_id": self.related_object_id,
        }


def collect_default_issue_drafts() -> list[IssueDraft]:
    drafts: list[IssueDraft] = []
    drafts.extend(check_stale_orchestration_runs())
    drafts.extend(check_stale_orchestration_steps())
    drafts.extend(check_stale_active_locks())
    drafts.extend(check_stale_order_submission_attempts())
    drafts.extend(check_notification_dispatch_gaps())
    return drafts


def check_stale_orchestration_runs() -> list[IssueDraft]:
    from apps.orchestration.models import OrchestrationRun, OrchestrationRunStatus

    threshold = _minutes("RUNTIME_GUARD_ORCHESTRATION_STALE_MINUTES", 30)
    cutoff = timezone.now() - threshold
    query = OrchestrationRun.objects.filter(
        status__in=[OrchestrationRunStatus.RUNNING, OrchestrationRunStatus.WAITING],
        updated_at_utc__lt=cutoff,
    )[:100]
    return [
        IssueDraft(
            issue_type="orchestration_run_stale",
            severity="high",
            related_object_type="OrchestrationRun",
            related_object_id=str(run.id),
            related_trace_id=run.trace_id,
            description_zh="编排运行长时间未完成，需要人工排查。",
            evidence={"status": run.status, "current_step_code": run.current_step_code, "updated_at_utc": run.updated_at_utc.isoformat()},
        )
        for run in query
    ]


def check_stale_orchestration_steps() -> list[IssueDraft]:
    from apps.orchestration.models import OrchestrationStepRun, OrchestrationStepRunStatus

    threshold = _minutes("RUNTIME_GUARD_STEP_STALE_MINUTES", 20)
    cutoff = timezone.now() - threshold
    query = OrchestrationStepRun.objects.filter(
        status__in=[OrchestrationStepRunStatus.RUNNING, OrchestrationStepRunStatus.WAITING],
        updated_at_utc__lt=cutoff,
    )[:100]
    return [
        IssueDraft(
            issue_type="orchestration_step_stale",
            severity="high",
            related_object_type="OrchestrationStepRun",
            related_object_id=str(step.id),
            related_trace_id=step.trace_id,
            description_zh="编排步骤长时间未完成，需要人工排查。",
            evidence={"step_code": step.step_code, "status": step.status, "updated_at_utc": step.updated_at_utc.isoformat()},
        )
        for step in query
    ]


def check_stale_active_locks() -> list[IssueDraft]:
    from apps.order_plan.models import ActiveLockStatus, OrderPlanActiveLock

    threshold = _minutes("RUNTIME_GUARD_ACTIVE_LOCK_STALE_MINUTES", 40)
    cutoff = timezone.now() - threshold
    query = OrderPlanActiveLock.objects.select_related("current_order_plan").filter(
        status=ActiveLockStatus.ACTIVE,
        updated_at_utc__lt=cutoff,
    )[:100]
    return [
        IssueDraft(
            issue_type="active_lock_stale",
            severity="critical",
            related_object_type="OrderPlanActiveLock",
            related_object_id=str(lock.id),
            related_trace_id=getattr(lock.current_order_plan, "trace_id", ""),
            description_zh="订单链路 ActiveLock 长时间处于保护中，需要人工确认订单状态与成交同步。",
            evidence={
                "status": lock.status,
                "market_type": lock.market_type,
                "account_domain": lock.account_domain,
                "symbol": lock.symbol,
                "updated_at_utc": lock.updated_at_utc.isoformat(),
            },
        )
        for lock in query
    ]


def check_stale_order_submission_attempts() -> list[IssueDraft]:
    from apps.execution.models import OrderSubmissionAttempt, OrderSubmissionAttemptStatus

    threshold = _minutes("RUNTIME_GUARD_ORDER_STATUS_STALE_MINUTES", 45)
    cutoff = timezone.now() - threshold
    query = OrderSubmissionAttempt.objects.filter(
        status__in=[OrderSubmissionAttemptStatus.ACCEPTED, OrderSubmissionAttemptStatus.UNKNOWN],
        updated_at_utc__lt=cutoff,
    )[:100]
    return [
        IssueDraft(
            issue_type="order_submission_status_stale",
            severity="critical",
            related_object_type="OrderSubmissionAttempt",
            related_object_id=str(attempt.id),
            related_trace_id=attempt.trace_id,
            description_zh="订单提交尝试长时间没有明确后续状态，需要人工排查 OrderStatusSync / FillSync。",
            evidence={"status": attempt.status, "exchange_order_id": attempt.exchange_order_id, "updated_at_utc": attempt.updated_at_utc.isoformat()},
        )
        for attempt in query
    ]


def check_notification_dispatch_gaps() -> list[IssueDraft]:
    from apps.alerts.models import AlertEvent

    threshold = _minutes("RUNTIME_GUARD_NOTIFICATION_STALE_MINUTES", 10)
    cutoff = timezone.now() - threshold
    query = (
        AlertEvent.objects.filter(delivery_enabled=True, created_at_utc__lt=cutoff)
        .exclude(delivery_attempts__isnull=False)
        .exclude(suppressions__isnull=False)
        .distinct()[:100]
    )
    return [
        IssueDraft(
            issue_type="alert_event_without_delivery_decision",
            severity="warning",
            related_object_type="AlertEvent",
            related_object_id=str(event.id),
            related_trace_id=event.trace_id,
            description_zh="允许外部投递的 AlertEvent 没有形成投递尝试或抑制记录。",
            evidence={"event_type": event.event_type, "source_module": event.source_module},
        )
        for event in query
    ]


def _minutes(name: str, default: int) -> timedelta:
    return timedelta(minutes=int(getattr(settings, name, default)))
