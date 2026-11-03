"""Simple per-client rate limiting.

In-memory, per process: suitable for a single instance and for development.
Behind several instances, replace the store with a shared one (e.g. Redis);
the dependency interface stays the same.
"""

from __future__ import annotations

import math
import threading
import time
from collections import deque

from fastapi import HTTPException, Request, status

from app.core.config import settings


class SlidingWindowLimiter:
    def __init__(self, limit: int, window_seconds: float = 60.0, clock=time.monotonic):
        self.limit = limit
        self.window = window_seconds
        self.clock = clock
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def check(self, key: str) -> float | None:
        """Record a hit; return None if allowed, else seconds until a slot frees."""
        now = self.clock()
        with self._lock:
            hits = self._hits.setdefault(key, deque())
            while hits and now - hits[0] >= self.window:
                hits.popleft()
            if len(hits) >= self.limit:
                return max(0.0, self.window - (now - hits[0]))
            hits.append(now)
            if len(self._hits) > 50_000:  # bound memory under key churn
                for k in [k for k, v in self._hits.items() if not v][:10_000]:
                    del self._hits[k]
            return None


def client_key(request: Request) -> str:
    if settings.TRUST_PROXY_HEADERS:
        forwarded = request.headers.get("x-forwarded-for", "")
        if forwarded:
            return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def rate_limited(limiter: SlidingWindowLimiter, scope: str):
    def dependency(request: Request) -> None:
        wait = limiter.check(f"{scope}:{client_key(request)}")
        if wait is not None:
            raise HTTPException(
                status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many requests. Please slow down.",
                headers={"Retry-After": str(max(1, math.ceil(wait)))},
            )
    return dependency


public_limiter = SlidingWindowLimiter(settings.RATE_LIMIT_PUBLIC_PER_MINUTE)
write_limiter = SlidingWindowLimiter(settings.RATE_LIMIT_WRITE_PER_MINUTE)
public_rate_limit = rate_limited(public_limiter, "public")
write_rate_limit = rate_limited(write_limiter, "write")
