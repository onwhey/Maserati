"""Notifications Celery tasks.

Module: Notifications
Responsibility: async delivery entry points only.
Not responsible for business decisions, trading, Binance, DeepSeek, or Hermes-triggered actions.
Database: delegates to notification service.
"""

from __future__ import annotations

from config.celery import app

from .services import deliver_notification_attempt, scan_pending_delivery_attempts


@app.task(name="notifications.deliver_attempt")
def deliver_notification_attempt_task(*, delivery_attempt_id: int) -> dict[str, object]:
    response = deliver_notification_attempt(delivery_attempt_id=delivery_attempt_id)
    return response.__dict__


@app.task(name="notifications.scan_pending")
def scan_pending_notification_attempts_task(*, limit: int = 50) -> list[int]:
    attempt_ids = scan_pending_delivery_attempts(limit=limit)
    for attempt_id in attempt_ids:
        deliver_notification_attempt_task.delay(delivery_attempt_id=attempt_id)
    return attempt_ids
