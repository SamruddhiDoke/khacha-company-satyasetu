"""Conversations, messages and attachments."""
from __future__ import annotations

import asyncio
import hashlib
import os
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.session import current_session
from app.db import get_db
from app.ingest import extract
from app.models import Attachment, Conversation, Message, Session, VerificationJob
from app.pipeline.text import URL_RE
from app.schemas import (
    AttachmentOut,
    ConversationCreate,
    ConversationOut,
    ConversationUpdate,
    JobSummary,
    MessageCreate,
    MessageOut,
)

router = APIRouter(prefix="/api", tags=["chat"])


def err(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(status, detail={"code": code, "message": message})


async def owned_conversation(db: AsyncSession, sess: Session, conv_id: uuid.UUID, lock: bool = False) -> Conversation:
    q = select(Conversation).where(Conversation.id == conv_id, Conversation.session_id == sess.id)
    if lock:
        q = q.with_for_update()
    conv = await db.scalar(q)
    if conv is None:
        raise err(404, "not_found", "Conversation not found.")
    return conv


def attachment_out(a: Attachment | None) -> AttachmentOut | None:
    if a is None:
        return None
    ex = a.extraction or {}
    return AttachmentOut(id=a.id, filename=a.filename, mime_type=a.mime_type, kind=a.kind, size_bytes=a.size_bytes,
                         extraction_method=ex.get("method"), extraction_confidence=ex.get("confidence"),
                         extraction_warnings=ex.get("warnings", []))


async def latest_jobs(db: AsyncSession, message_ids: list[uuid.UUID]) -> dict[uuid.UUID, VerificationJob]:
    if not message_ids:
        return {}
    rows = (await db.scalars(select(VerificationJob).where(VerificationJob.message_id.in_(message_ids))
                             .order_by(VerificationJob.created_at))).all()
    return {j.message_id: j for j in rows}  # later rows overwrite -> latest attempt


def message_out(m: Message, job: VerificationJob | None) -> MessageOut:
    return MessageOut(id=m.id, conversation_id=m.conversation_id, seq=m.seq, role=m.role, kind=m.kind, text=m.text,
                      created_at=m.created_at, attachment=attachment_out(m.attachment),
                      latest_job=JobSummary.model_validate(job) if job else None)


# ---------------------------------------------------------------- conversations
@router.get("/conversations", response_model=list[ConversationOut])
async def list_conversations(q: str | None = None, sess: Session = Depends(current_session),
                             db: AsyncSession = Depends(get_db)):
    convs = (await db.scalars(select(Conversation).where(Conversation.session_id == sess.id)
                              .order_by(Conversation.updated_at.desc()).limit(200))).all()
    out = []
    for c in convs:
        last = await db.scalar(select(Message).where(Message.conversation_id == c.id).order_by(Message.seq.desc()).limit(1))
        count = await db.scalar(select(func.count()).select_from(Message).where(Message.conversation_id == c.id))
        job = None
        if last:
            job = await db.scalar(select(VerificationJob).where(VerificationJob.message_id == last.id)
                                  .order_by(VerificationJob.created_at.desc()).limit(1))
        preview = (last.text or (last.attachment.filename if last.attachment else ""))[:120] if last else None
        if q and q.lower() not in c.title.lower() and q.lower() not in (preview or "").lower():
            continue
        out.append(ConversationOut(id=c.id, title=c.title, created_at=c.created_at, updated_at=c.updated_at,
                                   last_message_preview=preview, message_count=count or 0,
                                   last_verdict=job.overall_verdict if job else None,
                                   last_status=job.status if job else None))
    return out


@router.post("/conversations", response_model=ConversationOut, status_code=201)
async def create_conversation(body: ConversationCreate, sess: Session = Depends(current_session),
                              db: AsyncSession = Depends(get_db)):
    conv = Conversation(session_id=sess.id, title=(body.title or "New conversation").strip()[:120])
    db.add(conv)
    await db.commit()
    return ConversationOut.model_validate(conv)


@router.get("/conversations/{conv_id}", response_model=ConversationOut)
async def get_conversation(conv_id: uuid.UUID, sess: Session = Depends(current_session), db: AsyncSession = Depends(get_db)):
    return ConversationOut.model_validate(await owned_conversation(db, sess, conv_id))


@router.patch("/conversations/{conv_id}", response_model=ConversationOut)
async def rename_conversation(conv_id: uuid.UUID, body: ConversationUpdate, sess: Session = Depends(current_session),
                              db: AsyncSession = Depends(get_db)):
    conv = await owned_conversation(db, sess, conv_id)
    conv.title = body.title.strip()
    await db.commit()
    return ConversationOut.model_validate(conv)


@router.delete("/conversations/{conv_id}", status_code=204)
async def delete_conversation(conv_id: uuid.UUID, sess: Session = Depends(current_session),
                              db: AsyncSession = Depends(get_db)):
    conv = await owned_conversation(db, sess, conv_id)
    att_ids = [a for a in (await db.scalars(select(Message.attachment_id).where(
        Message.conversation_id == conv.id, Message.attachment_id.is_not(None)))).all()]
    paths = [p for p in (await db.scalars(select(Attachment.storage_path).where(Attachment.id.in_(att_ids)))).all()]
    await db.delete(conv)  # cascades: messages -> jobs -> claims/sources/evidence/events/corrections/findings
    if att_ids:
        await db.execute(delete(Attachment).where(Attachment.id.in_(att_ids)))
    await db.commit()
    for p in paths:
        try:
            os.remove(p)
        except OSError:
            pass


# ---------------------------------------------------------------- messages
@router.get("/conversations/{conv_id}/messages", response_model=list[MessageOut])
async def list_messages(conv_id: uuid.UUID, sess: Session = Depends(current_session), db: AsyncSession = Depends(get_db)):
    conv = await owned_conversation(db, sess, conv_id)
    msgs = (await db.scalars(select(Message).where(Message.conversation_id == conv.id).order_by(Message.seq))).unique().all()
    jobs = await latest_jobs(db, [m.id for m in msgs])
    return [message_out(m, jobs.get(m.id)) for m in msgs]


async def _append(db: AsyncSession, conv: Conversation, **fields) -> Message:
    seq = (await db.scalar(select(func.coalesce(func.max(Message.seq), 0)).where(Message.conversation_id == conv.id))) + 1
    msg = Message(conversation_id=conv.id, seq=seq, **fields)
    db.add(msg)
    now = datetime.now(timezone.utc)
    conv.updated_at = now
    if conv.title == "New conversation":
        basis = fields.get("text") or (fields.get("attachment").filename if fields.get("attachment") else "")
        conv.title = (" ".join(basis.split())[:60] or "New conversation")
    await db.commit()
    await db.refresh(msg)
    return msg


@router.post("/conversations/{conv_id}/messages", response_model=MessageOut, status_code=201)
async def send_message(conv_id: uuid.UUID, body: MessageCreate, sess: Session = Depends(current_session),
                       db: AsyncSession = Depends(get_db)):
    text = body.text.strip()
    if not text:
        raise err(422, "empty_message", "Message is empty.")
    conv = await owned_conversation(db, sess, conv_id, lock=True)
    kind = "url" if URL_RE.fullmatch(text) else "text"
    msg = await _append(db, conv, role="user", kind=kind, text=text)
    return message_out(msg, None)


# ---------------------------------------------------------------- attachments
@router.post("/conversations/{conv_id}/attachments", response_model=MessageOut, status_code=201)
async def upload_attachment(conv_id: uuid.UUID, file: UploadFile = File(...), caption: str = Form(""),
                            sess: Session = Depends(current_session), db: AsyncSession = Depends(get_db)):
    s = get_settings()
    await owned_conversation(db, sess, conv_id)
    data = await file.read(s.max_upload_bytes + 1)
    if len(data) > s.max_upload_bytes:
        raise err(413, "file_too_large", f"Files must be under {s.max_upload_bytes // 1_000_000} MB.")
    if not data:
        raise err(422, "empty_file", "The file is empty.")
    try:
        kind, mime = extract.sniff(data)
    except extract.UnsupportedFile as e:
        raise err(415, "unsupported_file", str(e))
    if kind == "audio" and not s.whisper_enabled:
        raise err(415, "audio_disabled", "Audio transcription is disabled in this installation.")
    att_id = uuid.uuid4()
    folder = os.path.join(s.data_dir, "uploads", str(sess.id))
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, str(att_id))
    with open(path, "wb") as fh:
        fh.write(data)
    try:
        if kind == "image":
            ex = await asyncio.wait_for(run_in_threadpool(extract.ocr_image, data), timeout=90)
        elif kind == "pdf":
            ex = await asyncio.wait_for(run_in_threadpool(extract.extract_pdf, data), timeout=180)
        else:
            ex = await asyncio.wait_for(
                run_in_threadpool(extract.transcribe, path, s.max_audio_seconds, s.whisper_model), timeout=300)
    except extract.UnsupportedFile as e:
        os.remove(path)
        raise err(415, "unsupported_file", str(e))
    except asyncio.TimeoutError:
        os.remove(path)
        raise err(504, "extraction_timeout", "Reading the file took too long.")
    except Exception as e:
        os.remove(path)
        raise err(422, "extraction_failed", f"Could not read this file ({type(e).__name__}).")

    safe_name = os.path.basename(file.filename or f"upload.{mime.split('/')[-1]}")[:200]
    att = Attachment(id=att_id, session_id=sess.id, filename=safe_name, mime_type=mime, kind=kind,
                     size_bytes=len(data), sha256=hashlib.sha256(data).hexdigest(), storage_path=path,
                     extracted_text=ex.text[:50_000], extraction=ex.as_meta())
    db.add(att)
    conv = await owned_conversation(db, sess, conv_id, lock=True)
    msg = await _append(db, conv, role="user", kind=kind, text=caption.strip()[:2000], attachment=att)
    return message_out(msg, None)


@router.get("/attachments/{att_id}/file")
async def get_attachment_file(att_id: uuid.UUID, sess: Session = Depends(current_session), db: AsyncSession = Depends(get_db)):
    att = await db.scalar(select(Attachment).where(Attachment.id == att_id, Attachment.session_id == sess.id))
    if att is None or not os.path.exists(att.storage_path):
        raise err(404, "not_found", "Attachment not found.")
    disposition = "inline" if att.kind in ("image", "audio") else "attachment"
    return FileResponse(att.storage_path, media_type=att.mime_type, filename=att.filename,
                        content_disposition_type=disposition,
                        headers={"X-Content-Type-Options": "nosniff", "Content-Security-Policy": "default-src 'none'"})


@router.get("/attachments/{att_id}/text")
async def get_attachment_text(att_id: uuid.UUID, sess: Session = Depends(current_session), db: AsyncSession = Depends(get_db)):
    att = await db.scalar(select(Attachment).where(Attachment.id == att_id, Attachment.session_id == sess.id))
    if att is None:
        raise err(404, "not_found", "Attachment not found.")
    return {"text": att.extracted_text or "", "extraction": {k: v for k, v in (att.extraction or {}).items() if k != "pages"}}
