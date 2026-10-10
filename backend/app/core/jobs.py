"""In-process background job runner (modular monolith). Jobs are persisted, so
after a restart any job that was mid-flight is marked `interrupted` and can be
retried by the user - it is never silently reported as complete."""
from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import update

from app.config import get_settings
from app.db import SessionLocal
from app.models import ACTIVE_JOB_STATUSES, VerificationJob

log = logging.getLogger(__name__)
_tasks: set[asyncio.Task] = set()
_sem: asyncio.Semaphore | None = None


def _semaphore() -> asyncio.Semaphore:
    global _sem
    if _sem is None:
        _sem = asyncio.Semaphore(get_settings().max_concurrent_checks)
    return _sem


def schedule(job_id: uuid.UUID) -> None:
    from app.pipeline.orchestrator import run_verification

    async def runner() -> None:
        async with _semaphore():
            await run_verification(job_id)

    task = asyncio.create_task(runner(), name=f"verify-{job_id}")
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


async def mark_interrupted_jobs() -> int:
    async with SessionLocal() as db:
        res = await db.execute(
            update(VerificationJob)
            .where(VerificationJob.status.in_(ACTIVE_JOB_STATUSES))
            .values(status="failed", error_code="interrupted",
                    error_message="The server restarted while this check was running. Retry to run it again.",
                    finished_at=datetime.now(timezone.utc))
        )
        await db.commit()
        return res.rowcount or 0


async def wait_all(timeout: float = 30) -> None:
    """Used by tests and graceful shutdown."""
    if _tasks:
        await asyncio.wait(list(_tasks), timeout=timeout)
