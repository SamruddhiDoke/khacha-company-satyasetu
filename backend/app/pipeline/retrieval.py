"""Search -> candidate selection -> direct page fetch -> text extraction."""
from __future__ import annotations

import asyncio
import hashlib
import io
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

import trafilatura
from pypdf import PdfReader

from app.config import get_settings
from app.core.safe_fetch import FetchFailed, FetchResult, UnsafeURL, safe_fetch
from app.pipeline.sources import classify, domain_of, rank_key
from app.providers.errors import ProviderError
from app.providers.llm import CallStats
from app.providers.search import SearchHit, SearchProvider

log = logging.getLogger(__name__)
MAX_STORED_TEXT = 120_000


@dataclass
class PageContent:
    title: str | None
    text: str
    published: str | None
    site_name: str | None


@dataclass
class RetrievedSource:
    url: str
    domain: str
    tier: str
    found_via: str
    search_score: float | None
    title: str | None = None
    publisher: str | None = None
    published_date: str | None = None
    final_url: str | None = None
    retrieval_method: str | None = None
    retrieved_at: datetime | None = None
    http_status: int | None = None
    fetch_ok: bool = False
    fetch_error: str | None = None
    text: str = ""
    factcheck_rating: str | None = None
    claim_indices: set[int] = field(default_factory=set)

    @property
    def content_sha256(self) -> str | None:
        return hashlib.sha256(self.text.encode()).hexdigest() if self.text else None


def extract_page(res: FetchResult) -> PageContent:
    if res.content_type == "application/pdf" or res.body[:5] == b"%PDF-":
        reader = PdfReader(io.BytesIO(res.body))
        pages = [(p.extract_text() or "") for p in reader.pages[:40]]
        title = (reader.metadata or {}).get("/Title") if reader.metadata else None
        return PageContent(str(title) if title else None, "\n\n".join(pages), None, None)
    html = res.body.decode("utf-8", errors="replace")
    if res.content_type == "text/plain":
        return PageContent(None, html, None, None)
    raw = trafilatura.extract(html, url=res.final_url, output_format="json", with_metadata=True,
                              include_comments=False, include_tables=True, favor_recall=True)
    if not raw:
        return PageContent(None, "", None, None)
    data = json.loads(raw)
    return PageContent(data.get("title"), data.get("text") or "", data.get("date"), data.get("sitename"))


async def fetch_source(src: RetrievedSource, raw_fallback: str | None) -> RetrievedSource:
    s = get_settings()
    try:
        res = await safe_fetch(src.url, timeout_s=s.fetch_timeout_s, max_bytes=s.fetch_max_bytes)
        page = extract_page(res)
        src.final_url, src.http_status = res.final_url, res.status
        if len(page.text.strip()) >= 200:
            src.text = page.text[:MAX_STORED_TEXT]
            src.retrieval_method = "direct"
            src.title = page.title or src.title
            src.publisher = src.publisher or page.site_name
            src.published_date = src.published_date or page.published
            src.fetch_ok = True
        else:
            src.fetch_error = "page had too little extractable text"
    except (FetchFailed, UnsafeURL) as e:
        src.fetch_error = str(e)
    except Exception as e:  # malformed documents etc.
        log.warning("fetch/extract failed for %s: %s", src.domain, type(e).__name__)
        src.fetch_error = f"extraction failed ({type(e).__name__})"
    if not src.fetch_ok and raw_fallback and len(raw_fallback.strip()) >= 200:
        # The site blocked or failed our direct fetch, but the search provider retrieved the page.
        src.text = raw_fallback[:MAX_STORED_TEXT]
        src.retrieval_method = "provider_extract"
        src.fetch_ok = True
    src.retrieved_at = datetime.now(timezone.utc)
    return src


async def search_claims(claims: list[tuple[int, list[str], str | None]], search: SearchProvider,
                        factcheck: SearchProvider | None, stats: CallStats) -> dict[int, list[SearchHit]]:
    """claims: (claim_index, queries, country). Returns hits per claim, within the per-check search budget."""
    s = get_settings()
    budget = s.max_total_searches_per_check
    plan: list[tuple[int, str, str | None]] = []
    for round_ in range(s.max_searches_per_claim):  # breadth first: every claim gets its first query
        for idx, queries, country in claims:
            if round_ < len(queries) and len(plan) < budget:
                plan.append((idx, queries[round_], country))
    results: dict[int, list[SearchHit]] = {idx: [] for idx, _, _ in claims}
    errors: list[ProviderError] = []

    async def run(idx: int, q: str, country: str | None) -> None:
        try:
            results[idx].extend(await search.search(q, country=country, stats=stats))
        except ProviderError as e:
            errors.append(e)

    await asyncio.gather(*(run(*p) for p in plan))
    if factcheck:
        async def fc(idx: int, q: str) -> None:
            try:
                results[idx].extend(await factcheck.search(q, country=None, stats=stats))
            except ProviderError as e:
                log.info("fact-check API lookup failed: %s", e)
        await asyncio.gather(*(fc(idx, qs[0]) for idx, qs, _ in claims if qs))
    log.info("search hits per claim: %s (errors: %d)", {i: len(h) for i, h in results.items()}, len(errors))
    if errors and not any(results.values()):
        raise errors[0]  # every search failed - surface the real provider error
    return results


def select_candidates(hits_by_claim: dict[int, list[SearchHit]]) -> tuple[dict[str, RetrievedSource], dict[str, str]]:
    s = get_settings()
    sources: dict[str, RetrievedSource] = {}
    raw: dict[str, str] = {}
    for idx, hits in hits_by_claim.items():
        seen_domains: set[str] = set()
        ranked = sorted(hits, key=lambda h: rank_key(classify(h.url), h.score), reverse=True)
        picked = 0
        for h in ranked:
            dom = domain_of(h.url)
            if dom in seen_domains or picked >= s.max_sources_per_claim:
                continue  # one page per domain per claim -> independent sources
            seen_domains.add(dom)
            picked += 1
            src = sources.get(h.url)
            if src is None:
                tier = "fact_check" if h.found_via == "factcheck_api" else classify(h.url)
                src = RetrievedSource(url=h.url, domain=dom, tier=tier, found_via=h.found_via, search_score=h.score,
                                      title=h.title, publisher=h.publisher, published_date=h.published_date,
                                      factcheck_rating=h.factcheck_rating)
                sources[h.url] = src
            src.claim_indices.add(idx)
            if h.raw_content and h.url not in raw:
                raw[h.url] = h.raw_content
    return sources, raw


async def fetch_all(sources: dict[str, RetrievedSource], raw: dict[str, str], stats: CallStats) -> None:
    sem = asyncio.Semaphore(5)

    async def one(src: RetrievedSource) -> None:
        async with sem:
            stats.fetches += 1
            await fetch_source(src, raw.get(src.url))

    await asyncio.gather(*(one(s) for s in sources.values()))
