"""SatyaSetu API entry point."""
from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import delete, select
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api import chat, system, verify
from app.config import get_settings
from app.core import jobs
from app.db import SessionLocal
from app.models import Attachment, Conversation, Session

settings = get_settings()
logging.basicConfig(level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
# httpx logs full request URLs (which can include API keys in query strings) at INFO - keep it quiet.
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
log = logging.getLogger("satyasetu")


async def retention_cleanup() -> dict:
    """Delete conversations untouched for RETENTION_DAYS, their uploads, and idle empty sessions."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=settings.retention_days)
    async with SessionLocal() as db:
        old = (await db.scalars(select(Conversation).where(Conversation.updated_at < cutoff))).all()
        for c in old:
            await db.delete(c)
        stale_att = (await db.scalars(select(Attachment).where(Attachment.created_at < cutoff))).all()
        for a in stale_att:
            try:
                os.remove(a.storage_path)
            except OSError:
                pass
            await db.delete(a)
        res = await db.execute(delete(Session).where(Session.last_seen_at < cutoff))
        await db.commit()
    return {"conversations": len(old), "attachments": len(stale_att), "sessions": res.rowcount or 0}


async def _cleanup_loop() -> None:
    while True:
        try:
            removed = await retention_cleanup()
            if any(removed.values()):
                log.info("retention cleanup removed %s", removed)
        except Exception:
            log.exception("retention cleanup failed")
        await asyncio.sleep(6 * 3600)


@asynccontextmanager
async def lifespan(app: FastAPI):
    n = await jobs.mark_interrupted_jobs()
    if n:
        log.warning("%d verification(s) were interrupted by a restart and marked as failed (retryable)", n)
    log.info("live verification %s (gemini=%s, tavily=%s)",
             "ENABLED" if settings.gemini_configured and settings.tavily_configured else "NOT CONFIGURED",
             settings.gemini_configured, settings.tavily_configured)
    task = asyncio.create_task(_cleanup_loop())
    yield
    task.cancel()
    await jobs.wait_all(timeout=5)


app = FastAPI(title="SatyaSetu API", version="0.1.0", lifespan=lifespan, openapi_url="/api/openapi.json",
              docs_url=None, redoc_url=None,
              description="Evidence-based verification of forwarded messages.")
app.include_router(system.router)
app.include_router(chat.router)
app.include_router(verify.router)


@app.middleware("http")
async def guard(request: Request, call_next):
    cl = request.headers.get("content-length")
    limit = settings.max_upload_bytes + 100_000 if request.url.path.endswith("/attachments") else 256_000
    if cl and cl.isdigit() and int(cl) > limit:
        return JSONResponse({"code": "payload_too_large", "message": "Request body is too large."}, status_code=413)
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    return response


@app.exception_handler(StarletteHTTPException)
async def http_error(request: Request, exc: StarletteHTTPException):
    detail = exc.detail if isinstance(exc.detail, dict) else {"code": "http_error", "message": str(exc.detail)}
    return JSONResponse(detail, status_code=exc.status_code)


@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, exc: RequestValidationError):
    first = exc.errors()[0] if exc.errors() else {}
    loc = ".".join(str(x) for x in first.get("loc", []) if x != "body")
    return JSONResponse({"code": "invalid_request", "message": f"{loc}: {first.get('msg', 'invalid input')}".strip(": ")},
                        status_code=422)
