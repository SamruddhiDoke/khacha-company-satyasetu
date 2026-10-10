"""Free-quota protection: persistent per-day request counters plus an in-process
per-minute limiter. Limits are checked *before* a request is sent so the app
stops short of the provider's free quota instead of discovering it with a 429."""
import asyncio
import time
from collections import deque
from datetime import date, datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert

from app.db import SessionLocal
from app.models import ProviderUsage
from app.providers.errors import QuotaExhausted, RateLimited


def today() -> date:
    return datetime.now(timezone.utc).date()


async def get_count(provider: str, day: date | None = None) -> int:
    async with SessionLocal() as db:
        row = await db.scalar(
            select(ProviderUsage.requests).where(ProviderUsage.provider == provider, ProviderUsage.day == (day or today()))
        )
        return row or 0


async def get_month_count(provider: str) -> int:
    d = today()
    async with SessionLocal() as db:
        total = await db.scalar(
            select(func.coalesce(func.sum(ProviderUsage.requests), 0)).where(
                ProviderUsage.provider == provider,
                ProviderUsage.day >= d.replace(day=1),
            )
        )
        return int(total or 0)


async def record(provider: str, *, requests: int = 1, units: int = 0, errors: int = 0) -> None:
    async with SessionLocal() as db:
        stmt = insert(ProviderUsage).values(provider=provider, day=today(), requests=requests, units=units, errors=errors)
        stmt = stmt.on_conflict_do_update(
            index_elements=["provider", "day"],
            set_={
                "requests": ProviderUsage.requests + requests,
                "units": ProviderUsage.units + units,
                "errors": ProviderUsage.errors + errors,
            },
        )
        await db.execute(stmt)
        await db.commit()


class MinuteLimiter:
    """Sliding-window limiter. Waits briefly for a slot; raises if the wait would be long."""

    def __init__(self, per_minute: int, provider: str, max_wait_s: float = 20.0):
        self.per_minute = per_minute
        self.provider = provider
        self.max_wait_s = max_wait_s
        self._times: deque[float] = deque()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            now = time.monotonic()
            while self._times and now - self._times[0] > 60:
                self._times.popleft()
            if len(self._times) >= self.per_minute:
                wait = 60 - (now - self._times[0]) + 0.05
                if wait > self.max_wait_s:
                    raise RateLimited(
                        f"{self.provider}: local rate limit of {self.per_minute}/min reached; try again shortly",
                        provider=self.provider,
                        retryable=True,
                    )
                await asyncio.sleep(wait)
                self._times.popleft()
            self._times.append(time.monotonic())


async def ensure_daily_budget(provider: str, limit: int) -> None:
    if await get_count(provider) >= limit:
        raise QuotaExhausted(
            f"{provider}: the configured daily request budget ({limit}) is used up. It resets at 00:00 UTC.",
            provider=provider,
        )
