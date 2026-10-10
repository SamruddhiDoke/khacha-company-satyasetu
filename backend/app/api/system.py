"""Health, readiness, capabilities, usage and preferences."""
from __future__ import annotations

import importlib
import shutil

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import ALLOWED_LANGUAGES, get_settings
from app.core.session import current_session
from app.core.usage import today
from app.db import get_db
from app.models import ProviderUsage, Session
from app.providers import registry
from app.providers.llm import GeminiProvider
from app.schemas import Capabilities, Preferences, ProviderStatus, UsageOut, UsageRow

router = APIRouter(prefix="/api", tags=["system"])

DATA_USE_NOTICE = (
    "Text you verify is sent to Google's Gemini API and Tavily search. On the Gemini API free tier, Google states "
    "that submitted content may be used to improve its products and may be reviewed by humans. Do not verify "
    "messages containing passwords, OTPs, ID numbers or other sensitive personal information."
)


def _importable(module: str) -> bool:
    try:
        importlib.import_module(module)
        return True
    except Exception:
        return False


@router.get("/health")
async def health():
    return {"status": "ok"}


@router.get("/ready")
async def ready(db: AsyncSession = Depends(get_db)):
    checks = {}
    try:
        await db.execute(text("SELECT 1"))
        checks["database"] = "ok"
        version = await db.scalar(text("SELECT version_num FROM alembic_version"))
        checks["migrations"] = version or "missing"
    except Exception as e:
        checks["database"] = f"error: {type(e).__name__}"
    s = get_settings()
    checks["llm_provider"] = "configured" if s.gemini_configured else "not_configured"
    checks["search_provider"] = "configured" if s.tavily_configured else "not_configured"
    ok = checks.get("database") == "ok" and checks.get("migrations") not in (None, "missing")
    # The app is ready to serve even without provider keys; live verification is reported separately.
    return JSONResponse({"ready": ok, "live_verification": s.gemini_configured and s.tavily_configured,
                         "checks": checks}, status_code=200 if ok else 503)


@router.get("/capabilities", response_model=Capabilities)
async def capabilities(probe: bool = False):
    s = get_settings()
    providers: dict[str, ProviderStatus] = {}
    if s.gemini_configured:
        detail = f"model {s.gemini_model}" + (f", fallback {s.gemini_fallback_model}" if s.gemini_fallback_model else "")
        if probe:  # models.get metadata calls - no generation quota is used
            llm = registry.get_llm()
            if isinstance(llm, GeminiProvider):
                results = [f"{m}: {(await llm.check_model(m))[1]}" for m in llm.models]
                detail = "; ".join(results)
        providers["llm"] = ProviderStatus(configured=True, detail=detail)
    else:
        providers["llm"] = ProviderStatus(configured=False, detail="Set GEMINI_API_KEY in .env to enable claim analysis.")
    providers["search"] = ProviderStatus(
        configured=s.tavily_configured,
        detail="Tavily web search" if s.tavily_configured else "Set TAVILY_API_KEY in .env to enable source retrieval.")
    providers["factcheck_db"] = ProviderStatus(
        configured=s.factcheck_configured,
        detail="Google Fact Check Tools API" if s.factcheck_configured else "Optional: set FACTCHECK_API_KEY.")
    tesseract = shutil.which("tesseract") is not None
    whisper = s.whisper_enabled and _importable("faster_whisper")
    modalities = {
        "text": ProviderStatus(configured=True, detail="Typed or pasted text"),
        "url": ProviderStatus(configured=True, detail="Public web pages (fetched with SSRF protection)"),
        "image": ProviderStatus(configured=tesseract, detail="OCR with Tesseract (eng+hin+mar)" if tesseract else "Tesseract not installed"),
        "pdf": ProviderStatus(configured=True, detail="Text layer; scanned pages via OCR" if tesseract else "Text layer only"),
        "audio": ProviderStatus(configured=whisper, detail=f"Local Whisper ({s.whisper_model}) transcription" if whisper else "Disabled"),
        "video": ProviderStatus(configured=False, detail="Not supported yet"),
    }
    return Capabilities(
        live_verification=s.gemini_configured and s.tavily_configured, providers=providers, modalities=modalities,
        languages=list(ALLOWED_LANGUAGES),
        limits={"max_input_chars": s.max_input_chars, "max_claims_per_check": s.max_claims_per_check,
                "max_upload_bytes": s.max_upload_bytes, "max_audio_seconds": s.max_audio_seconds},
        retention_days=s.retention_days, data_use_notice=DATA_USE_NOTICE,
    )


@router.get("/usage", response_model=UsageOut)
async def usage(db: AsyncSession = Depends(get_db)):
    s = get_settings()
    rows = (await db.scalars(select(ProviderUsage).where(ProviderUsage.day == today()))).all()
    return UsageOut(
        today=[UsageRow(provider=r.provider, day=r.day.isoformat(), requests=r.requests, units=r.units, errors=r.errors)
               for r in rows],
        limits={"gemini_requests_per_day": s.gemini_max_requests_per_day,
                "tavily_searches_per_day": s.tavily_max_searches_per_day,
                "tavily_searches_per_month": s.tavily_max_searches_per_month},
    )


@router.get("/preferences", response_model=Preferences)
async def get_preferences(sess: Session = Depends(current_session)):
    return Preferences(**(sess.preferences or {}))


@router.put("/preferences", response_model=Preferences)
async def put_preferences(body: Preferences, sess: Session = Depends(current_session), db: AsyncSession = Depends(get_db)):
    s = await db.get(Session, sess.id)
    s.preferences = body.model_dump()
    await db.commit()
    return body

