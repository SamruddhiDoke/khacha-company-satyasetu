"""Verification progress events. Every event is persisted first, then pushed to
live subscribers, so an SSE client that reconnects replays exactly what has
actually happened (using Last-Event-ID) and nothing is invented client-side."""
from __future__ import annotations

import asyncio
import uuid
from collections import defaultdict

from sqlalchemy import func, select

from app.db import SessionLocal
from app.models import VerificationEvent

TERMINAL_KINDS = ("done", "error")


class EventBus:
    def __init__(self) -> None:
        self._subs: dict[uuid.UUID, set[asyncio.Queue]] = defaultdict(set)
        self._seq: dict[uuid.UUID, int] = {}
        self._lock = asyncio.Lock()

    def subscribe(self, job_id: uuid.UUID) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue()
        self._subs[job_id].add(q)
        return q

    def unsubscribe(self, job_id: uuid.UUID, q: asyncio.Queue) -> None:
        self._subs[job_id].discard(q)
        if not self._subs[job_id]:
            self._subs.pop(job_id, None)

    async def emit(self, job_id: uuid.UUID, kind: str, stage: str | None = None, status: str | None = None,
                   detail: str | None = None) -> dict:
        async with self._lock:
            async with SessionLocal() as db:
                if job_id not in self._seq:
                    self._seq[job_id] = int(
                        await db.scalar(select(func.coalesce(func.max(VerificationEvent.seq), 0))
                                        .where(VerificationEvent.job_id == job_id)) or 0)
                self._seq[job_id] += 1
                ev = VerificationEvent(job_id=job_id, seq=self._seq[job_id], kind=kind, stage=stage, status=status,
                                       detail=detail)
                db.add(ev)
                await db.commit()
                payload = serialize(ev)
            if kind in TERMINAL_KINDS:
                self._seq.pop(job_id, None)
        for q in list(self._subs.get(job_id, ())):
            q.put_nowait(payload)
        return payload


def serialize(ev: VerificationEvent) -> dict:
    return {"id": ev.id, "seq": ev.seq, "job_id": str(ev.job_id), "kind": ev.kind, "stage": ev.stage,
            "status": ev.status, "detail": ev.detail, "at": ev.created_at.isoformat()}


bus = EventBus()
