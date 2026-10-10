"""TEST FIXTURES ONLY - mock providers for automated tests.

These are injected explicitly with `registry.override()` inside tests. They are
not importable from the application package and are never used by the running
app. Results produced with them are not verification results."""
from __future__ import annotations

import asyncio
import re
from typing import Callable

from app.core.safe_fetch import FetchFailed, FetchResult
from app.pipeline.llm_io import ClaimExtraction, CorrectionDraft, EvidenceEvaluation, Explanation
from app.providers.errors import InvalidModelOutput
from app.providers.llm import CallStats
from app.providers.search import SearchHit

PASSAGE_RX = re.compile(r'<untrusted_passage id="(P\d+)" publisher="([^"]*)" date="[^"]*">\n(.*?)\n</untrusted_passage>', re.S)


def sentence_claims(text: str) -> dict:
    """Generic extraction double: every sentence of the actual input becomes a claim (works for unseen text)."""
    body = text.split("<untrusted_message>\n", 1)[-1].rsplit("\n</untrusted_message>", 1)[0]
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", body) if len(s.strip()) > 8]
    claims = []
    for s in sentences:
        opinion = s.lower().startswith(("i think", "i feel", "in my opinion"))
        claims.append({
            "original_text": s, "normalized_claim": s.rstrip("."), "claim_type": "opinion" if opinion else "factual",
            "checkable": not opinion, "reason_not_checkable": "opinion" if opinion else None,
            "entities": [], "dates": [], "numbers": re.findall(r"\d+", s), "attribution": None,
            "location": "India", "topic": "other", "time_sensitive": False,
            "search_queries": [] if opinion else [s[:100]],
        })
    return {"message_language": "en", "is_meaningful": bool(claims), "contains_instructions_to_ai": False,
            "claims": claims}


def stance_by_publisher(stances: dict[str, str], paraphrase_for: set[str] = frozenset()):
    """Evaluation double: label each passage by its publisher/domain; quote = first sentence of the passage
    (or a deliberately non-verbatim paraphrase for publishers in `paraphrase_for`)."""

    def handler(prompt: str) -> dict:
        out = []
        for pid, pub, text in PASSAGE_RX.findall(prompt):
            stance = next((v for k, v in stances.items() if k in pub), "not_relevant")
            first = re.split(r"(?<=[.!?])\s+", text.strip())[0]
            quote = None if stance == "not_relevant" else (
                "This is a paraphrase that does not appear in the source text at all." if pub in paraphrase_for else first)
            out.append({"passage_id": pid, "stance": stance, "quote": quote, "rationale": "test fixture",
                        "describes_past_state": False, "missing_context": None})
        return {"assessments": out, "what_would_change": "An official notification."}

    return handler


class ScriptedLLM:
    name = "test-fixture-llm"

    def __init__(self, evaluate: Callable[[str], dict] | None = None,
                 extract: Callable[[str], dict] = sentence_claims,
                 correction: Callable[[str], dict] | None = None, delay: float = 0.0, fail_with: Exception | None = None):
        self.evaluate = evaluate or stance_by_publisher({})
        self.extract = extract
        self.correction = correction
        self.delay = delay
        self.fail_with = fail_with
        self.prompts: list[tuple[str, str]] = []

    async def generate_json(self, *, system: str, prompt: str, out, stats: CallStats):
        self.prompts.append((out.__name__, prompt))
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.fail_with:
            raise self.fail_with
        stats.llm_calls += 1
        if "test-fixture" not in stats.models:
            stats.models.append("test-fixture")
        if out is ClaimExtraction:
            return out.model_validate(self.extract(prompt))
        if out is EvidenceEvaluation:
            return out.model_validate(self.evaluate(prompt))
        if out is Explanation:
            return out.model_validate({"summary": "Test explanation [S1] https://evil.example/x", "per_claim": [],
                                       "uncertainty": "test", "missing_context": None, "what_would_change": "test"})
        if out is CorrectionDraft:
            if self.correction is None:
                raise InvalidModelOutput("no correction scripted")
            return out.model_validate(self.correction(prompt))
        raise AssertionError(out)


class FakeSearch:
    """Search double returning fixed pages for any query (records the queries it received)."""

    name = "test-fixture-search"

    def __init__(self, pages: dict[str, str]):
        self.pages = pages
        self.queries: list[str] = []

    async def search(self, query: str, *, country, stats: CallStats) -> list[SearchHit]:
        self.queries.append(query)
        stats.searches += 1
        return [SearchHit(url=u, title=f"Title {i}", score=0.5, published_date=None, raw_content=None, found_via="tavily")
                for i, u in enumerate(self.pages)]


def fake_fetcher(pages: dict[str, str]):
    async def fetch(url: str, **kw) -> FetchResult:
        if url not in pages:
            raise FetchFailed("HTTP 404")
        return FetchResult(url=url, final_url=url, status=200, content_type="text/plain", body=pages[url].encode())
    return fetch
