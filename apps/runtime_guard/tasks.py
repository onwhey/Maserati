"""RuntimeGuard Celery tasks.

Module: RuntimeGuard
Responsibility: async guard scan entry point only.
Not responsible for recovery, lock release, business mutation, Binance, DeepSeek,
Hermes sending, or trade execution.
Database: delegates to RuntimeGuard service.
"""

from __future__ import annotations

import uuid

from config.celery import app

from .services.guard import run_runtime_guard


@app.task(name="runtime_guard.run")
def run_runtime_guard_task(*, trace_id: str, dry_run: bool = True, confirm_write: bool = False) -> dict[str, object]:
    summary = run_runtime_guard(
        trace_id=trace_id or uuid.uuid4().hex,
        trigger_source="celery_beat",
        dry_run=dry_run,
        confirm_write=confirm_write,
    )
    return summary.__dict__
