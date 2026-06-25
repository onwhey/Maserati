"""PipelineOrchestrator Celery tasks.

Module: PipelineOrchestrator
Responsibility: asynchronous entry points only.
Not responsible for business logic, Binance/DeepSeek calls, Hermes delivery,
lock release, or direct order submission.
Database: delegates to orchestration service.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from django.utils import timezone

from config.celery import app

from .services.orchestrator import drive_orchestration_run, resume_waiting_orchestration_step, start_and_drive_orchestration_run


@app.task(name="orchestration.start_main_trading_cycle")
def start_main_trading_cycle_task(*, scheduled_for_utc: str = "", trace_id: str = "") -> dict[str, object]:
    scheduled = datetime.fromisoformat(scheduled_for_utc) if scheduled_for_utc else _current_4h_boundary()
    summary = start_and_drive_orchestration_run(
        scheduled_for_utc=scheduled,
        cycle_kind="4h",
        trigger_mode="automatic",
        trigger_source="celery_beat",
        trace_id=trace_id or uuid.uuid4().hex,
    )
    return summary.__dict__


@app.task(name="orchestration.drive_run")
def drive_orchestration_run_task(*, orchestration_run_id: int) -> dict[str, object]:
    summary = drive_orchestration_run(orchestration_run_id=orchestration_run_id)
    return summary.__dict__


@app.task(name="orchestration.resume_waiting_step")
def resume_waiting_step_task(*, resume_token: str, trace_id: str = "") -> dict[str, object]:
    summary = resume_waiting_orchestration_step(resume_token=resume_token, trace_id=trace_id or uuid.uuid4().hex)
    return summary.__dict__


def _current_4h_boundary() -> datetime:
    now = timezone.now().astimezone(UTC)
    hour = (now.hour // 4) * 4
    return now.replace(hour=hour, minute=0, second=0, microsecond=0)
