"""Verification jobs, live progress (SSE), corrections and history."""
from __future__ import annotations

import asyncio
import hashlib
import json
import uuid

from fastapi import APIRouter, Depends, Header, Request
from fastapi.responses import JSONResponse, StreamingResponse
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.chat import err
from app.config import get_settings
from app.core import jobs
from app.core.events import TERMINAL_KINDS, bus, serialize
from app.core.ratelimit import KeyedLimiter
from app.core.session import current_session
from app.db import SessionLocal, get_db
from app.models import (
    ACTIVE_JOB_STATUSES,
    Claim,
    Conversation,
    Correction,
    Message,
    Session,
    VerificationEvent,
    VerificationJob,
)
from app.pipeline.correction import draft_correction
from app.pipeline.orchestrator import load_job
from app.providers import registry
from app.providers.errors import ProviderNotConfigured
from app.providers.llm import CallStats
from app.schemas import (
    ClaimOut,
    CorrectionOut,
    CorrectionRequest,
    EventOut,
    FindingOut,
    HistoryItem,
    JobDetail,
    JobSummary,
    SourceLink,
    SourceOut,
    VerifyRequest,
)

router = APIRouter(prefix="/api", tags=["verification"])
_limiter: KeyedLimiter | None = None


def limiter() -> KeyedLimiter:
    global _limiter
    if _limiter is None:
        _limiter = KeyedLimiter(get_settings().verifications_per_minute_per_session)
    return _limiter


async def enforce_check_quotas(db: AsyncSession, sess: Session) -> None:
    """Stop any single visitor (or a burst of visitors) from using up the shared free provider quota."""
    s = get_settings()
    now = datetime.now(timezone.utc)
    hour = await db.scalar(select(func.count()).select_from(VerificationJob)
                           .where(VerificationJob.created_at > now - timedelta(hours=1)))
    if hour >= s.verifications_per_hour_global:
        raise err(429, "busy", "SatyaSetu has reached its hourly limit of fact-checks on this free demo server. "
                               "Please try again later.")
    day = await db.scalar(select(func.count()).select_from(VerificationJob)
                          .where(VerificationJob.session_id == sess.id,
                                 VerificationJob.created_at > now - timedelta(days=1)))
    if day >= s.verifications_per_day_per_session:
        raise err(429, "daily_limit", f"You have used today's limit of {s.verifications_per_day_per_session} checks "
                                      "on this free demo server. Please try again tomorrow.")


async def owned_message(db: AsyncSession, sess: Session, message_id: uuid.UUID) -> Message:
    msg = await db.scalar(select(Message).join(Conversation).where(Message.id == message_id,
                                                                     Conversation.session_id == sess.id))
    if msg is None:
        raise err(404, "not_found", "Message not found.")
    return msg


async def owned_job(db: AsyncSession, sess: Session, job_id: uuid.UUID) -> VerificationJob:
    job = await load_job(db, job_id)
    if job is None or job.session_id != sess.id:
        raise err(404, "not_found", "Verification not found.")
    return job


def build_input(msg: Message) -> str:
    s = get_settings()
    parts = [msg.text.strip()] if msg.text.strip() else []
    if msg.attachment and msg.attachment.extracted_text:
        label = {"image": "Text read from image", "pdf": "Text from document",
                 "audio": "Transcript of audio"}.get(msg.attachment.kind, "Extracted text")
        parts.append(f"[{label}]\n{msg.attachment.extracted_text.strip()}")
    return "\n\n".join(parts)[: s.max_input_chars]


@router.post("/messages/{message_id}/verifications", response_model=JobSummary,
             responses={200: {"model": JobSummary}, 202: {"model": JobSummary}})
async def start_verification(message_id: uuid.UUID, body: VerifyRequest, sess: Session = Depends(current_session),
                             db: AsyncSession = Depends(get_db)):
    msg = await owned_message(db, sess, message_id)
    if msg.role != "user":
        raise err(422, "not_verifiable", "Only submitted messages can be verified.")
    existing = (await db.scalars(select(VerificationJob).where(VerificationJob.message_id == msg.id)
                                 .order_by(VerificationJob.created_at.desc()))).all()
    active = next((j for j in existing if j.status in ACTIVE_JOB_STATUSES), None)
    if active:  # duplicate click while running -> same job, no new work
        return JSONResponse(JobSummary.model_validate(active).model_dump(mode="json"), status_code=200)
    if existing and not body.retry:
        return JSONResponse(JobSummary.model_validate(existing[0]).model_dump(mode="json"), status_code=200)

    text = build_input(msg)
    if len(text.strip()) < 3:
        raise err(422, "empty_input", "There is no text to verify in this message.")
    if not any(ch.isalnum() for ch in text):
        raise err(422, "no_content", "This message has no words or numbers to verify.")
    msg_id = msg.id
    limiter().hit(str(sess.id))
    await enforce_check_quotas(db, sess)
    job = VerificationJob(message_id=msg_id, session_id=sess.id, language=body.language, input_text=text,
                          input_sha256=hashlib.sha256(text.encode()).hexdigest(), attempt=len(existing) + 1)
    db.add(job)
    try:
        await db.commit()
    except IntegrityError:  # a concurrent request created the active job first
        await db.rollback()
        active = await db.scalar(select(VerificationJob).where(VerificationJob.message_id == msg_id,
                                                               VerificationJob.status.in_(ACTIVE_JOB_STATUSES)))
        return JSONResponse(JobSummary.model_validate(active).model_dump(mode="json"), status_code=200)
    await bus.emit(job.id, "stage", "queued", "completed", None)
    jobs.schedule(job.id)
    return JSONResponse(JobSummary.model_validate(job).model_dump(mode="json"), status_code=202)


async def job_detail(db: AsyncSession, job: VerificationJob) -> JobDetail:
    events = (await db.scalars(select(VerificationEvent).where(VerificationEvent.job_id == job.id)
                               .order_by(VerificationEvent.seq))).all()
    conv_id = await db.scalar(select(Message.conversation_id).where(Message.id == job.message_id))
    labels = {url: lbl for lbl, url in ((job.explanation or {}).get("source_labels") or {}).items()}
    sources = [SourceOut.model_validate(s).model_copy(update={"label": labels.get(s.url)}) for s in job.sources]
    sources.sort(key=lambda s: (s.label is None, int(s.label[1:]) if s.label else 0, not s.fetch_ok))
    return JobDetail(
        **JobSummary.model_validate(job).model_dump(),
        input_text=job.input_text, conversation_id=conv_id, explanation=job.explanation, harm=job.harm,
        content_meta=job.content_meta, models_used=job.models_used or [], usage=job.usage or {},
        claims=[ClaimOut.model_validate(c) for c in job.claims], sources=sources,
        findings=[FindingOut.model_validate(f) for f in job.findings],
        events=[EventOut(**serialize(e)) for e in events],
    )


@router.get("/verifications/{job_id}", response_model=JobDetail)
async def get_verification(job_id: uuid.UUID, sess: Session = Depends(current_session), db: AsyncSession = Depends(get_db)):
    return await job_detail(db, await owned_job(db, sess, job_id))


@router.get("/verifications/{job_id}/events", response_class=StreamingResponse,
            responses={200: {"content": {"text/event-stream": {}}}})
async def stream_events(job_id: uuid.UUID, request: Request, after: int = 0,
                        last_event_id: str | None = Header(None), sess: Session = Depends(current_session),
                        db: AsyncSession = Depends(get_db)):
    """Server-Sent Events. Replays persisted events after `Last-Event-ID` (or ?after=), then streams live ones."""
    job = await db.scalar(select(VerificationJob).where(VerificationJob.id == job_id, VerificationJob.session_id == sess.id))
    if job is None:
        raise err(404, "not_found", "Verification not found.")
    cursor = int(last_event_id) if last_event_id and last_event_id.isdigit() else after

    async def gen():
        nonlocal cursor
        q = bus.subscribe(job_id)
        try:
            async with SessionLocal() as s2:
                past = (await s2.scalars(select(VerificationEvent).where(VerificationEvent.job_id == job_id,
                                                                         VerificationEvent.id > cursor)
                                         .order_by(VerificationEvent.id))).all()
                status = await s2.scalar(select(VerificationJob.status).where(VerificationJob.id == job_id))
            yield "retry: 3000\n\n"
            for ev in past:
                payload = serialize(ev)
                cursor = ev.id
                yield f"id: {ev.id}\nevent: {ev.kind}\ndata: {json.dumps(payload)}\n\n"
                if ev.kind in TERMINAL_KINDS:
                    return
            if status not in ACTIVE_JOB_STATUSES:
                # Finished without a terminal event (e.g. interrupted by a restart): report the stored status.
                yield f"event: status\ndata: {json.dumps({'status': status})}\n\n"
                return
            while True:
                if await request.is_disconnected():
                    return
                try:
                    payload = await asyncio.wait_for(q.get(), timeout=15)
                except asyncio.TimeoutError:
                    yield ": keep-alive\n\n"
                    continue
                if payload["id"] <= cursor:
                    continue
                cursor = payload["id"]
                yield f"id: {payload['id']}\nevent: {payload['kind']}\ndata: {json.dumps(payload)}\n\n"
                if payload["kind"] in TERMINAL_KINDS:
                    return
        finally:
            bus.unsubscribe(job_id, q)

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ---------------------------------------------------------------- corrections
@router.post("/verifications/{job_id}/corrections", response_model=CorrectionOut, status_code=201)
async def create_correction(job_id: uuid.UUID, body: CorrectionRequest, sess: Session = Depends(current_session),
                            db: AsyncSession = Depends(get_db)):
    job = await owned_job(db, sess, job_id)
    if job.status != "completed":
        raise err(409, "not_completed", "A correction can only be drafted from a completed verification.")
    try:
        llm = registry.get_llm()
    except ProviderNotConfigured:
        llm = None
    stats = CallStats()
    text, generator, validation = await draft_correction(llm, job, body.relationship, body.channel, body.language,
                                                         body.tone, stats)
    corr = Correction(job_id=job.id, relationship_to=body.relationship, channel=body.channel, language=body.language,
                      tone=body.tone, text=text, generator=generator, validation=validation)
    db.add(corr)
    await db.commit()
    return correction_out(corr, job)


def correction_out(corr: Correction, job: VerificationJob) -> CorrectionOut:
    labels = (job.explanation or {}).get("source_labels") or {}
    by_url = {s.url: s for s in job.sources}
    links = [SourceLink(label=lbl, url=url, publisher=(by_url[url].publisher or by_url[url].domain) if url in by_url else url)
             for lbl, url in labels.items()][:3]
    return CorrectionOut.model_validate(corr).model_copy(update={"links": links})


@router.get("/verifications/{job_id}/corrections", response_model=list[CorrectionOut])
async def list_corrections(job_id: uuid.UUID, sess: Session = Depends(current_session), db: AsyncSession = Depends(get_db)):
    job = await owned_job(db, sess, job_id)
    rows = (await db.scalars(select(Correction).where(Correction.job_id == job.id).order_by(Correction.created_at))).all()
    return [correction_out(c, job) for c in rows]


# ---------------------------------------------------------------- history
@router.get("/history", response_model=list[HistoryItem])
async def history(limit: int = 50, sess: Session = Depends(current_session), db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(
        select(VerificationJob, Message, Conversation)
        .join(Message, Message.id == VerificationJob.message_id)
        .join(Conversation, Conversation.id == Message.conversation_id)
        .where(VerificationJob.session_id == sess.id)
        .order_by(VerificationJob.created_at.desc()).limit(min(limit, 200))
    )).unique().all()
    counts = dict((await db.execute(select(Claim.job_id, func.count()).where(
        Claim.job_id.in_([r[0].id for r in rows])).group_by(Claim.job_id))).all()) if rows else {}
    return [HistoryItem(job=JobSummary.model_validate(j), conversation_id=c.id, conversation_title=c.title,
                        message_preview=(j.input_text or "")[:140], claim_count=counts.get(j.id, 0))
            for j, m, c in rows]


@router.delete("/history/{job_id}", status_code=204)
async def delete_history_item(job_id: uuid.UUID, sess: Session = Depends(current_session), db: AsyncSession = Depends(get_db)):
    job = await owned_job(db, sess, job_id)
    if job.status in ACTIVE_JOB_STATUSES:
        raise err(409, "job_active", "Wait for the check to finish before deleting it.")
    await db.delete(job)
    await db.commit()
