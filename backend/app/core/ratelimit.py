import time
from collections import defaultdict, deque

from fastapi import HTTPException


class KeyedLimiter:
    """Per-key sliding window used to cap how often a session can start checks."""

    def __init__(self, per_minute: int):
        self.per_minute = per_minute
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def hit(self, key: str) -> None:
        now = time.monotonic()
        q = self._hits[key]
        while q and now - q[0] > 60:
            q.popleft()
        if len(q) >= self.per_minute:
            raise HTTPException(429, detail={"code": "rate_limited",
                                             "message": f"Too many checks started. Limit is {self.per_minute} per minute."})
        q.append(now)
