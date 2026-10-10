"""The verification pipeline for one message.

Stages emit `started` before work and `completed` only after the work has
actually finished. Any provider failure ends the job as `failed` with a
specific error code - there is no fallback that fabricates a result."""
from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.config import get_settings
from app.core.events import bus
from app.core.safe_fetch import FetchFailed, UnsafeURL, safe_fetch
from app.db import SessionLocal
from app.models import Claim, DocumentFinding, Evidence, Message, Source, VerificationJob
from app.pipeline import forensics, harm
from app.pipeline.explain import ClaimForExplanation, explain
from app.pipeline.llm_io import SYSTEM_EVALUATE, SYSTEM_EXTRACT, ClaimExtraction, EvidenceEvaluation, wrap
from app.pipeline.retrieval import RetrievedSource, extract_page, fetch_all, search_claims, select_candidates
from app.pipeline.text import detect_script_language, extract_urls, normalize_for_match, quote_in_text, select_passages, tokens
from app.pipeline.verdicts import EvidenceInput, counted_mask, decide_claim, decide_overall, overall_strength
from app.providers import registry
from app.providers.errors import ProviderError
from app.providers.llm import CallStats

log = logging.getLogger(__name__)
INDIA_HINTS = ("india", "bharat", "maharashtra", "delhi", "mumbai", "pune", "karnataka", "kerala", "tamil",
               "gujarat", "bihar", "uttar pradesh", "rajasthan", "bengal", "telangana", "punjab", "assam", "odisha")


class Stage:
    def __init__(self, job_id: uuid.UUID, name: str):
        self.job_id, self.name = job_id, name

    async def __aenter__(self) -> "Stage":
        self.detail: str | None = None
        self.skipped = False
        await bus.emit(self.job_id, "stage", self.name, "started")
        return self

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        if exc_type is None:
            await bus.emit(self.job_id, "stage", self.name, "skipped" if self.skipped else "completed", self.detail)
        else:
            await bus.emit(self.job_id, "stage", self.name, "failed", _safe_error(exc))
        return False


def _safe_error(exc: BaseException | None) -> str:
    if isinstance(exc, ProviderError):
        return str(exc)
    if isinstance(exc, asyncio.TimeoutError):
        return "timed out"
    return "internal error"


async def run_verification(job_id: uuid.UUID) -> None:
    settings = get_settings()
    stats = CallStats()
    try:
        await asyncio.wait_for(_run(job_id, stats), timeout=settings.check_timeout_s)
    except asyncio.TimeoutError:
        await _fail(job_id, "timeout", f"The check did not finish within {int(settings.check_timeout_s)} seconds.", stats)
    except ProviderError as e:
        await _fail(job_id, e.code, str(e), stats)
    except Exception:
        log.exception("verification %s crashed", job_id)
        await _fail(job_id, "internal", "An unexpected error occurred. Please retry.", stats)


async def _fail(job_id: uuid.UUID, code: str, message: str, stats: CallStats) -> None:
    async with SessionLocal() as db:
        job = await db.get(VerificationJob, job_id)
        if job:
            job.status, job.error_code, job.error_message = "failed", code, message
            job.finished_at = datetime.now(timezone.utc)
            job.usage, job.models_used = stats.as_dict(), stats.models
            await db.commit()
    await bus.emit(job_id, "error", None, "failed", f"{code}: {message}")


async def _run(job_id: uuid.UUID, stats: CallStats) -> None:
    settings = get_settings()
    async with SessionLocal() as db:
        job = await db.get(VerificationJob, job_id)
        if job is None:
            return
        msg = await db.get(Message, job.message_id)
        job.status, job.started_at = "running", datetime.now(timezone.utc)
        await db.commit()
        text = job.input_text
        language = job.language
        attachment = msg.attachment if msg else None
        att_kind = attachment.kind if attachment else None
        att_extraction = dict(attachment.extraction or {}) if attachment else {}

    content_meta: dict = {"script": detect_script_language(text)}
    if attachment:
        content_meta["attachment"] = {"kind": att_kind, "method": att_extraction.get("method"),
                                      "confidence": att_extraction.get("confidence"),
                                      "warnings": att_extraction.get("warnings", [])}
    await bus.emit(job_id, "stage", "received", "completed", f"{len(text)} characters")

    # --- Harm assessment (deterministic; independent of factual verdict) ---
    async with Stage(job_id, "harm_check") as st:
        signals = harm.assess(text)
        st.detail = f"{len(signals)} warning(s)"
        await _save(job_id, harm={"level": harm.risk_level(signals), "signals": signals}, content_meta=content_meta)

    # --- Document forensics for uploaded circulars ---
    if att_kind in ("pdf", "image"):
        async with Stage(job_id, "document_checks") as st:
            findings = forensics.analyse(att_extraction.get("pages") or [text], att_extraction.get("metadata"),
                                         att_extraction)
            async with SessionLocal() as db:
                db.add_all([DocumentFinding(job_id=job_id, **f) for f in findings])
                await db.commit()
            st.detail = f"{len(findings)} check(s)"

    # --- Linked page content ---
    linked_text = ""
    urls = extract_urls(text)[:2]
    if urls:
        async with Stage(job_id, "extracting_content") as st:
            notes = []
            for u in urls:
                try:
                    res = await safe_fetch(u, timeout_s=settings.fetch_timeout_s, max_bytes=settings.fetch_max_bytes)
                    page = extract_page(res)
                    if page.text.strip():
                        linked_text += f"\n\n[Content of linked page {u}]\n{page.text[:3500]}"
                        notes.append({"url": u, "status": "fetched", "title": page.title})
                    else:
                        notes.append({"url": u, "status": "no_text"})
                except UnsafeURL as e:
                    notes.append({"url": u, "status": "blocked", "reason": str(e)})
                except FetchFailed as e:
                    notes.append({"url": u, "status": "failed", "reason": str(e)})
            content_meta["linked_pages"] = notes
            st.detail = ", ".join(f"{n['status']}" for n in notes)
            await _save(job_id, content_meta=content_meta)

    # --- Providers (no substitutes) ---
    llm = registry.get_llm()
    search = registry.get_search()
    factcheck = registry.get_factcheck()

    # --- Claim extraction ---
    today = datetime.now(timezone.utc).date().isoformat()
    async with Stage(job_id, "extracting_claims") as st:
        extraction = await llm.generate_json(
            system=SYSTEM_EXTRACT.format(today=today, max_claims=settings.max_claims_per_check),
            prompt=wrap("untrusted_message", (text + linked_text)[: settings.max_input_chars + 4000]),
            out=ClaimExtraction, stats=stats,
        )
        claims = extraction.claims[: settings.max_claims_per_check + 4]
        checkable_count = 0
        kept = []
        for c in claims:  # enforce the per-check budget on checkable claims
            if c.checkable and c.search_queries:
                checkable_count += 1
                if checkable_count > settings.max_claims_per_check:
                    c.checkable = False
                    c.reason_not_checkable = "Skipped: per-check claim limit reached."
            elif c.checkable and not c.search_queries:
                c.checkable = False
                c.reason_not_checkable = "No search query could be formed for this claim."
            kept.append(c)
        claims = kept
        content_meta["message_language"] = extraction.message_language
        content_meta["ai_instruction_detected"] = extraction.contains_instructions_to_ai
        st.detail = f"{sum(c.checkable for c in claims)} checkable of {len(claims)} statement(s)"

    if not extraction.is_meaningful or not claims:
        await _complete(job_id, [], {}, {}, stats, language, llm, content_meta,
                        note="No checkable statements were found in this message.")
        return

    # --- Queries ---
    async with Stage(job_id, "preparing_queries") as st:
        plan = []
        for i, c in enumerate(claims):
            if not c.checkable:
                continue
            loc = (c.location or "").lower()
            india = any(h in loc for h in INDIA_HINTS) or content_meta["script"] == "devanagari"
            qs = [q.strip() for q in c.search_queries if q.strip()][: settings.max_searches_per_claim]
            plan.append((i, qs, "india" if india else None))
        st.detail = f"{sum(len(q) for _, q, _ in plan)} quer(ies) for {len(plan)} claim(s)"

    sources: dict[str, RetrievedSource] = {}
    raw: dict[str, str] = {}
    if plan:
        async with Stage(job_id, "searching_sources") as st:
            hits = await search_claims(plan, search, factcheck, stats)
            sources, raw = select_candidates(hits)
            st.detail = f"{sum(len(h) for h in hits.values())} result(s), {len(sources)} candidate page(s)"

        async with Stage(job_id, "fetching_sources") as st:
            await fetch_all(sources, raw, stats)
            ok = sum(1 for s in sources.values() if s.fetch_ok)
            st.detail = f"{ok} of {len(sources)} page(s) retrieved"

    # --- Evidence evaluation ---
    evaluations: dict[int, list[tuple[RetrievedSource, str, object]]] = {}
    what_changes: dict[int, str] = {}
    async with Stage(job_id, "evaluating_evidence") as st:
        async def evaluate(i: int) -> None:
            c = claims[i]
            terms = tokens(c.normalized_claim) + [t.lower() for e in c.entities for t in tokens(e)] + \
                [t for n in c.numbers for t in tokens(n)]
            numbered: list[tuple[str, RetrievedSource, str]] = []
            for s in sources.values():
                if i in s.claim_indices and s.fetch_ok:
                    for k, p in enumerate(select_passages(s.text, terms, k=3)):
                        numbered.append((f"P{len(numbered) + 1}", s, p.text))
            if not numbered:
                evaluations[i] = []
                return
            body = "\n\n".join(
                wrap("untrusted_passage", p, id=pid, publisher=s.publisher or s.domain,
                     date=s.published_date or "unknown")
                for pid, s, p in numbered)
            result = await llm.generate_json(
                system=SYSTEM_EVALUATE.format(today=today),
                prompt=f"CLAIM: {c.normalized_claim}\n(Original wording: {c.original_text})\n\n{body}",
                out=EvidenceEvaluation, stats=stats,
            )
            by_id = {pid: (s, p) for pid, s, p in numbered}
            evaluations[i] = [(by_id[a.passage_id][0], by_id[a.passage_id][1], a)
                              for a in result.assessments if a.passage_id in by_id]
            what_changes[i] = result.what_would_change

        await asyncio.gather(*(evaluate(i) for i, c in enumerate(claims) if c.checkable))
        st.detail = f"{sum(len(v) for v in evaluations.values())} passage assessment(s)"

    # --- Quote validation ---
    validated: dict[int, list[dict]] = {}
    async with Stage(job_id, "checking_quotations") as st:
        rejected = 0
        for i, items in evaluations.items():
            out = []
            for src, passage, a in items:
                quote = a.quote.strip() if a.quote else None
                valid = bool(quote) and quote_in_text(quote, passage) and quote_in_text(quote, src.text)
                reason = None
                if a.stance != "not_relevant" and not valid:
                    rejected += 1
                    reason = "quote not found verbatim in the retrieved source text" if quote else "no quote given"
                out.append({"src": src, "passage": passage, "quote": quote, "stance": a.stance,
                            "rationale": a.rationale, "valid": valid, "rejected_reason": reason,
                            "temporal": a.describes_past_state, "missing_context": a.missing_context})
            validated[i] = out
        st.detail = f"{rejected} quotation(s) rejected"

    await _complete(job_id, claims, validated, what_changes, stats, language, llm, content_meta, sources=sources)


async def _complete(job_id, claims, validated, what_changes, stats, language, llm, content_meta,
                    sources: dict[str, RetrievedSource] | None = None, note: str | None = None) -> None:
    sources = sources or {}
    async with Stage(job_id, "computing_verdicts") as st:
        decisions = []
        for i, c in enumerate(claims):
            ev = [EvidenceInput(e["stance"], e["valid"], e["src"].tier, e["src"].domain, e["temporal"],
                                e["missing_context"]) for e in validated.get(i, [])]
            decisions.append(decide_claim(c.checkable, ev))
            # Record exactly what the rules counted, so the report never shows excluded quotes as evidence.
            for e, (counted, reason) in zip(validated.get(i, []), counted_mask(ev)):
                e["counted"] = counted and c.checkable
                if reason:
                    e["rejected_reason"] = reason
        overall = decide_overall([d.verdict for d in decisions])
        strength = overall_strength([d.strength for d, c in zip(decisions, claims) if c.checkable])
        st.detail = overall

    # Source labels [S#] only for sources that contributed counted evidence.
    labels: dict[str, str] = {}
    for i in range(len(claims)):
        for e in validated.get(i, []):
            if e["counted"] and e["src"].url not in labels:
                labels[e["src"].url] = f"S{len(labels) + 1}"

    async with Stage(job_id, "preparing_explanation") as st:
        cfe = []
        for i, (c, d) in enumerate(zip(claims, decisions)):
            quotes = [(labels[e["src"].url], e["stance"], e["quote"]) for e in validated.get(i, []) if e["counted"]]
            mc = next((e["missing_context"] for e in validated.get(i, []) if e["counted"] and e["missing_context"]), None)
            cfe.append(ClaimForExplanation(i, c.normalized_claim, d.verdict,
                                           d.reason if c.checkable else (c.reason_not_checkable or d.reason),
                                           quotes, mc, what_changes.get(i)))
        if claims:
            pubs = {lbl: (sources[url].publisher or sources[url].domain) for url, lbl in labels.items()}
            explanation = await explain(llm, cfe, overall, {lbl: p for lbl, p in pubs.items()}, language, stats)
        else:
            from app.pipeline.explain import template_explanation
            explanation = template_explanation([], overall, {})
            explanation["summary"] = note or explanation["summary"]
        if note:
            explanation["note"] = note
        explanation["source_labels"] = {lbl: url for url, lbl in labels.items()}
        st.detail = explanation["source"]

    # --- Persist everything atomically ---
    async with SessionLocal() as db:
        job = await db.get(VerificationJob, job_id)
        src_rows: dict[str, Source] = {}
        for url, s in sources.items():
            row = Source(job_id=job_id, url=s.url, final_url=s.final_url, domain=s.domain, title=s.title,
                         publisher=s.publisher, published_date=s.published_date, tier=s.tier, found_via=s.found_via,
                         retrieval_method=s.retrieval_method, retrieved_at=s.retrieved_at, http_status=s.http_status,
                         fetch_ok=s.fetch_ok, fetch_error=s.fetch_error, content_sha256=s.content_sha256,
                         content_text=s.text or None, search_score=s.search_score, factcheck_rating=s.factcheck_rating)
            db.add(row)
            src_rows[url] = row
        await db.flush()
        msg_text_norm = normalize_for_match(job.input_text)
        for i, (c, d) in enumerate(zip(claims, decisions)):
            claim = Claim(job_id=job_id, idx=i, original_text=c.original_text,
                          span_found=normalize_for_match(c.original_text) in msg_text_norm,
                          normalized=c.normalized_claim, claim_type=c.claim_type, checkable=c.checkable,
                          reason_not_checkable=c.reason_not_checkable, entities=c.entities, dates=c.dates,
                          numbers=c.numbers, attribution=c.attribution, location=c.location, topic=c.topic,
                          queries=c.search_queries, verdict=d.verdict, evidence_strength=d.strength,
                          verdict_reason=d.reason, what_would_change=what_changes.get(i), weights=d.weights,
                          missing_context=cfe[i].missing_context,
                          conflict_note=("Credible sources disagree on this claim." if d.verdict == "conflicting" else None))
            db.add(claim)
            await db.flush()
            for e in validated.get(i, []):
                if e["stance"] == "not_relevant" and not e["valid"]:
                    continue  # irrelevant passages are not stored as evidence
                db.add(Evidence(claim_id=claim.id, source_id=src_rows[e["src"].url].id, passage=e["passage"][:4000],
                                quote=e["quote"], stance=e["stance"], rationale=e["rationale"], quote_valid=e["valid"],
                                rejected_reason=e["rejected_reason"], temporal_issue=e["temporal"],
                                missing_context=e["missing_context"],
                                counted=e["counted"]))
        job.status = "completed"
        job.overall_verdict, job.evidence_strength = overall, strength
        job.explanation, job.content_meta = explanation, content_meta
        job.models_used, job.usage = stats.models, stats.as_dict()
        job.finished_at = datetime.now(timezone.utc)
        await db.commit()
    await bus.emit(job_id, "done", None, "completed", overall)


async def _save(job_id: uuid.UUID, **fields) -> None:
    async with SessionLocal() as db:
        job = await db.get(VerificationJob, job_id)
        for k, v in fields.items():
            setattr(job, k, v)
        await db.commit()


async def load_job(db, job_id: uuid.UUID) -> VerificationJob | None:
    return await db.scalar(
        select(VerificationJob).where(VerificationJob.id == job_id).options(
            selectinload(VerificationJob.claims).selectinload(Claim.evidence),
            selectinload(VerificationJob.sources),
            selectinload(VerificationJob.findings),
        )
    )
