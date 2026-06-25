"""OrderPlan 模块：集中取得并维护 ActiveLock；读写 MySQL；不访问 Redis 或外部服务；不发送 Hermes；不调用大模型；不提交订单；不允许真实交易。"""

from __future__ import annotations

from dataclasses import dataclass

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.foundation.idempotency import build_idempotency_key

from ..models import ActiveLockStatus, OrderPlan, OrderPlanActiveLock, OrderPlanActiveLockEvent
from .alerts import record_order_plan_alert


@dataclass(frozen=True)
class ActiveLockAcquireResult:
    acquired: bool
    reason_code: str
    active_lock: OrderPlanActiveLock


@dataclass(frozen=True)
class ActiveLockReleaseResult:
    released: bool
    reason_code: str
    active_lock: OrderPlanActiveLock | None


def acquire_for_order_plan(
    *,
    order_plan: OrderPlan,
    trace_id: str,
    trigger_source: str,
) -> ActiveLockAcquireResult:
    """在调用方数据库事务中为一条已计算计划取得唯一交易身份锁。"""

    lock = _get_or_create_locked_identity(order_plan)
    if lock.status == ActiveLockStatus.ACTIVE:
        if lock.current_order_plan_id == order_plan.id:
            return ActiveLockAcquireResult(True, "active_lock_already_acquired", lock)
        _record_blocked_acquire(lock=lock, order_plan=order_plan, reason_code="active_lock_conflict", trace_id=trace_id, trigger_source=trigger_source)
        return ActiveLockAcquireResult(False, "active_lock_conflict", lock)
    if lock.status == ActiveLockStatus.FAILED:
        _record_blocked_acquire(lock=lock, order_plan=order_plan, reason_code="active_lock_failed", trace_id=trace_id, trigger_source=trigger_source)
        return ActiveLockAcquireResult(False, "active_lock_failed", lock)

    previous_status = lock.status
    now = timezone.now()
    lock.status = ActiveLockStatus.ACTIVE
    lock.current_order_plan = order_plan
    lock.acquired_at_utc = now
    lock.released_at_utc = None
    lock.failed_at_utc = None
    lock.reason_code = "order_plan_created"
    lock.version += 1
    lock.save(
        update_fields=[
            "status",
            "current_order_plan",
            "acquired_at_utc",
            "released_at_utc",
            "failed_at_utc",
            "reason_code",
            "version",
            "updated_at_utc",
        ]
    )
    _record_event(
        lock=lock,
        order_plan=order_plan,
        event_type="acquired",
        from_status=previous_status,
        to_status=ActiveLockStatus.ACTIVE,
        reason_code="order_plan_created",
        evidence={"order_plan_id": order_plan.id},
        trace_id=trace_id,
        trigger_source=trigger_source,
    )
    record_order_plan_alert(
        event_type="active_lock_acquired",
        business_request_key=order_plan.business_request_key,
        trace_id=trace_id,
        trigger_source=trigger_source,
        status=ActiveLockStatus.ACTIVE,
        reason_code="order_plan_created",
        message="候选订单链路已取得唯一 ActiveLock；这不表示订单已提交。",
        order_plan_id=order_plan.id,
        payload_summary={"active_lock_id": lock.id, "symbol": lock.symbol},
    )
    return ActiveLockAcquireResult(True, "active_lock_acquired", lock)


def release_for_pre_execution_stop(
    *,
    active_lock_id: int,
    order_plan_id: int,
    source_module: str,
    source_object_id: int,
    reason_code: str,
    evidence: dict[str, object],
    trace_id: str,
    trigger_source: str,
) -> ActiveLockReleaseResult:
    """在订单尚未进入执行准备前，基于明确阻断/拒绝事实释放 ActiveLock。"""

    try:
        with transaction.atomic():
            lock = OrderPlanActiveLock.objects.select_for_update().get(id=active_lock_id)
            if lock.status == ActiveLockStatus.RELEASED:
                return ActiveLockReleaseResult(True, "active_lock_already_released", lock)
            if lock.status != ActiveLockStatus.ACTIVE:
                return ActiveLockReleaseResult(False, "active_lock_not_active", lock)
            if lock.current_order_plan_id != order_plan_id:
                return ActiveLockReleaseResult(False, "active_lock_order_plan_mismatch", lock)

            previous_status = lock.status
            now = timezone.now()
            lock.status = ActiveLockStatus.RELEASED
            lock.current_order_plan = None
            lock.released_at_utc = now
            lock.reason_code = reason_code
            lock.version += 1
            lock.save(
                update_fields=[
                    "status",
                    "current_order_plan",
                    "released_at_utc",
                    "reason_code",
                    "version",
                    "updated_at_utc",
                ]
            )
            order_plan = OrderPlan.objects.get(id=order_plan_id)
            _record_event(
                lock=lock,
                order_plan=order_plan,
                event_type="released_before_execution",
                from_status=previous_status,
                to_status=ActiveLockStatus.RELEASED,
                reason_code=reason_code,
                evidence={
                    **evidence,
                    "source_module": source_module,
                    "source_object_id": source_object_id,
                },
                trace_id=trace_id,
                trigger_source=trigger_source,
            )
            record_order_plan_alert(
                event_type="active_lock_released",
                business_request_key=order_plan.business_request_key,
                trace_id=trace_id,
                trigger_source=trigger_source,
                status=ActiveLockStatus.RELEASED,
                reason_code=reason_code,
                message="订单链路在进入执行准备前已明确停止，ActiveLock 已由锁服务安全释放。",
                order_plan_id=order_plan.id,
                payload_summary={
                    "active_lock_id": lock.id,
                    "source_module": source_module,
                    "source_object_id": source_object_id,
                },
            )
            return ActiveLockReleaseResult(True, "active_lock_released", lock)
    except OrderPlanActiveLock.DoesNotExist:
        return ActiveLockReleaseResult(False, "active_lock_not_found", None)


def release_for_order_submission_stop(
    *,
    active_lock_id: int,
    order_plan_id: int,
    source_module: str,
    source_object_id: int,
    reason_code: str,
    evidence: dict[str, object],
    trace_id: str,
    trigger_source: str,
) -> ActiveLockReleaseResult:
    """在订单明确未被接受或确认未发出时，基于提交阶段事实释放 ActiveLock。"""

    try:
        with transaction.atomic():
            lock = OrderPlanActiveLock.objects.select_for_update().get(id=active_lock_id)
            if lock.status == ActiveLockStatus.RELEASED:
                return ActiveLockReleaseResult(True, "active_lock_already_released", lock)
            if lock.status != ActiveLockStatus.ACTIVE:
                return ActiveLockReleaseResult(False, "active_lock_not_active", lock)
            if lock.current_order_plan_id != order_plan_id:
                return ActiveLockReleaseResult(False, "active_lock_order_plan_mismatch", lock)

            previous_status = lock.status
            now = timezone.now()
            lock.status = ActiveLockStatus.RELEASED
            lock.current_order_plan = None
            lock.released_at_utc = now
            lock.reason_code = reason_code
            lock.version += 1
            lock.save(
                update_fields=[
                    "status",
                    "current_order_plan",
                    "released_at_utc",
                    "reason_code",
                    "version",
                    "updated_at_utc",
                ]
            )
            order_plan = OrderPlan.objects.get(id=order_plan_id)
            _record_event(
                lock=lock,
                order_plan=order_plan,
                event_type="released_after_order_submission_stop",
                from_status=previous_status,
                to_status=ActiveLockStatus.RELEASED,
                reason_code=reason_code,
                evidence={
                    **evidence,
                    "source_module": source_module,
                    "source_object_id": source_object_id,
                },
                trace_id=trace_id,
                trigger_source=trigger_source,
            )
            record_order_plan_alert(
                event_type="active_lock_released",
                business_request_key=order_plan.business_request_key,
                trace_id=trace_id,
                trigger_source=trigger_source,
                status=ActiveLockStatus.RELEASED,
                reason_code=reason_code,
                message="订单提交阶段已明确未发出或未被交易所接受，ActiveLock 已由锁服务安全释放。",
                order_plan_id=order_plan.id,
                payload_summary={
                    "active_lock_id": lock.id,
                    "source_module": source_module,
                    "source_object_id": source_object_id,
                },
            )
            return ActiveLockReleaseResult(True, "active_lock_released", lock)
    except OrderPlanActiveLock.DoesNotExist:
        return ActiveLockReleaseResult(False, "active_lock_not_found", None)


def _get_or_create_locked_identity(order_plan: OrderPlan) -> OrderPlanActiveLock:
    identity = {
        "exchange": order_plan.exchange,
        "market_type": order_plan.market_type,
        "account_domain": order_plan.account_domain,
        "symbol": order_plan.symbol,
    }
    lock = OrderPlanActiveLock.objects.select_for_update().filter(**identity).first()
    if lock is not None:
        return lock
    try:
        with transaction.atomic():
            return OrderPlanActiveLock.objects.create(
                **identity,
                status=ActiveLockStatus.RELEASED,
                reason_code="lock_identity_initialized",
            )
    except IntegrityError:
        return OrderPlanActiveLock.objects.select_for_update().get(**identity)


def _record_blocked_acquire(
    *,
    lock: OrderPlanActiveLock,
    order_plan: OrderPlan,
    reason_code: str,
    trace_id: str,
    trigger_source: str,
) -> None:
    _record_event(
        lock=lock,
        order_plan=order_plan,
        event_type="acquire_blocked",
        from_status=lock.status,
        to_status=lock.status,
        reason_code=reason_code,
        evidence={"current_order_plan_id": lock.current_order_plan_id},
        trace_id=trace_id,
        trigger_source=trigger_source,
    )
    record_order_plan_alert(
        event_type="active_lock_conflict",
        business_request_key=order_plan.business_request_key,
        trace_id=trace_id,
        trigger_source=trigger_source,
        status="blocked",
        reason_code=reason_code,
        message="同一交易身份已有未安全结束的订单链路，新的 OrderPlan 已阻断。",
        order_plan_id=order_plan.id,
        payload_summary={"active_lock_id": lock.id, "current_order_plan_id": lock.current_order_plan_id},
    )


def _record_event(
    *,
    lock: OrderPlanActiveLock,
    order_plan: OrderPlan,
    event_type: str,
    from_status: str,
    to_status: str,
    reason_code: str,
    evidence: dict[str, object],
    trace_id: str,
    trigger_source: str,
) -> None:
    event_key = build_idempotency_key(
        "active_lock_event",
        lock.id,
        order_plan.id,
        event_type,
        reason_code,
        lock.version,
    )
    OrderPlanActiveLockEvent.objects.get_or_create(
        event_key=event_key,
        defaults={
            "active_lock": lock,
            "order_plan": order_plan,
            "event_type": event_type,
            "from_status": from_status,
            "to_status": to_status,
            "reason_code": reason_code,
            "evidence": evidence,
            "trace_id": trace_id,
            "trigger_source": trigger_source,
        },
    )
