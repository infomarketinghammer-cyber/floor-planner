"""In-memory sliding-window rate limits. Per server process: run one instance, or each
instance keeps its own counts."""

import time
from collections import defaultdict, deque

from fastapi import HTTPException, status


class RateLimiter:
    def __init__(self, limit: int, window_s: int, message: str) -> None:
        self.limit, self.window_s, self.message = limit, window_s, message
        self._calls: dict[str, deque[float]] = defaultdict(deque)

    def check(self, key: str) -> None:
        """Count a call for `key`; 429 once there have been `limit` in the window."""
        now = time.monotonic()
        calls = self._calls[key]
        while calls and now - calls[0] > self.window_s:
            calls.popleft()
        if len(calls) >= self.limit:
            raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, self.message)
        calls.append(now)
        if len(self._calls) > 50_000:  # forget idle keys so memory stays bounded
            for k in [k for k, v in self._calls.items() if not v or now - v[-1] > self.window_s]:
                del self._calls[k]
