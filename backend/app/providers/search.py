"""Search provider adapters. They return candidate URLs only - snippets are
never used as evidence. Every candidate page is fetched and its text is what
evidence quotes are validated against."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Protocol

import httpx

from app.config import Settings
from app.core import usage
from app.providers.errors import ProviderError, ProviderNotConfigured, ProviderTimeout, QuotaExhausted, RateLimited
from app.providers.llm import CallStats

log = logging.getLogger(__name__)

# Social and user-generated platforms are excluded: they are where forwards
# circulate, not where they are verified.
EXCLUDED_DOMAINS = [
    "facebook.com", "instagram.com", "x.com", "twitter.com", "tiktok.com", "pinterest.com",
    "quora.com", "reddit.com", "sharechat.com", "t.me", "whatsapp.com", "linkedin.com",
]


@dataclass
class SearchHit:
    url: str
    title: str | None
    score: float | None
    published_date: str | None
    raw_content: str | None  # page text extracted by the provider - used only if a direct fetch fails
    found_via: str
    factcheck_rating: str | None = None
    publisher: str | None = None


class SearchProvider(Protocol):
    name: str

    async def search(self, query: str, *, country: str | None, stats: CallStats) -> list[SearchHit]: ...


class TavilySearch:
    name = "tavily"
    URL = "https://api.tavily.com/search"

    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None):
        if not settings.tavily_configured:
            raise ProviderNotConfigured("TAVILY_API_KEY is not set", provider="tavily")
        self._key = settings.tavily_api_key.get_secret_value().strip()  # type: ignore[union-attr]
        self.settings = settings
        self._client = client or httpx.AsyncClient(timeout=settings.tavily_timeout_s)
        self._limiter = usage.MinuteLimiter(30, "tavily")

    async def search(self, query: str, *, country: str | None, stats: CallStats) -> list[SearchHit]:
        await usage.ensure_daily_budget("tavily", self.settings.tavily_max_searches_per_day)
        if await usage.get_month_count("tavily") >= self.settings.tavily_max_searches_per_month:
            raise QuotaExhausted("The configured monthly Tavily search budget is used up.", provider="tavily")
        await self._limiter.acquire()
        body = {
            "query": query[:380],
            "search_depth": "basic",  # 1 credit
            "max_results": 6,
            "include_raw_content": "text",
            "include_answer": False,  # the provider's own AI answer is never used as evidence
            "exclude_domains": EXCLUDED_DOMAINS,
        }
        if country:
            body["country"] = country
        try:
            r = await self._client.post(self.URL, headers={"Authorization": f"Bearer {self._key}"}, json=body)
        except httpx.TimeoutException as e:
            await usage.record("tavily", errors=1)
            raise ProviderTimeout("The search provider timed out.", provider="tavily", retryable=True) from e
        except httpx.HTTPError as e:
            await usage.record("tavily", errors=1)
            raise ProviderError(f"Network error contacting Tavily: {type(e).__name__}", provider="tavily", retryable=True) from e
        stats.searches += 1
        if r.status_code == 200:
            await usage.record("tavily", units=1)
            data = r.json()
            return [
                SearchHit(
                    url=item["url"],
                    title=item.get("title"),
                    score=item.get("score"),
                    published_date=item.get("published_date"),
                    raw_content=item.get("raw_content"),
                    found_via="tavily",
                )
                for item in data.get("results", [])
                if item.get("url")
            ]
        await usage.record("tavily", requests=1, errors=1)
        if r.status_code == 429:
            raise RateLimited("Search provider rate limit reached.", provider="tavily", retryable=True)
        if r.status_code in (432, 433):
            raise QuotaExhausted("Tavily plan or credit limit reached.", provider="tavily")
        if r.status_code in (401, 403):
            raise ProviderError("Tavily rejected the API key.", provider="tavily")
        raise ProviderError(f"Tavily error HTTP {r.status_code}", provider="tavily", retryable=r.status_code >= 500)


class GoogleFactCheckSearch:
    """Google Fact Check Tools API (claims:search). Free; needs an API key with the API enabled."""

    name = "factcheck_api"
    URL = "https://factchecktools.googleapis.com/v1alpha1/claims:search"

    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None):
        if not settings.factcheck_configured:
            raise ProviderNotConfigured("FACTCHECK_API_KEY is not set", provider="factcheck_api")
        self._key = settings.factcheck_api_key.get_secret_value().strip()  # type: ignore[union-attr]
        self._client = client or httpx.AsyncClient(timeout=15)

    async def search(self, query: str, *, country: str | None, stats: CallStats) -> list[SearchHit]:
        try:
            r = await self._client.get(self.URL, params={"query": query[:300], "pageSize": 5, "key": self._key})
        except httpx.HTTPError as e:
            raise ProviderError(f"Fact Check API network error: {type(e).__name__}", provider="factcheck_api") from e
        await usage.record("factcheck_api", errors=0 if r.status_code == 200 else 1)
        if r.status_code != 200:
            raise ProviderError(f"Fact Check API error HTTP {r.status_code}", provider="factcheck_api")
        hits = []
        for claim in r.json().get("claims", []) or []:
            for review in claim.get("claimReview", []) or []:
                if review.get("url"):
                    hits.append(
                        SearchHit(
                            url=review["url"],
                            title=review.get("title"),
                            score=None,
                            published_date=review.get("reviewDate"),
                            raw_content=None,
                            found_via="factcheck_api",
                            factcheck_rating=review.get("textualRating"),
                            publisher=(review.get("publisher") or {}).get("name"),
                        )
                    )
        return hits[:4]
