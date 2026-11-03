"""Per-client rate limiting.

In-memory, per process: suitable for a single instance and for development.
Behind several instances, replace the store with a shared one (e.g. Redis);
the dependency interface stays the same.

Memory is bounded: at most `max_keys` clients are tracked; the least recently
seen client is evicted first, so key churn (many distinct addresses) cannot
grow memory without limit.

Client identity is the socket peer address. `X-Forwarded-For` is honoured only
when the peer is one of `TRUSTED_PROXIES`, and then the right-most address that
is not itself a trusted proxy is used, so a client cannot spoof its identity by
sending the header itself.
"""

from __future__ import annotations

import ipaddress
import math
import threading
import time
from collections import OrderedDict, deque

from fastapi import HTTPException, Request, status

from app.core.config import settings


class SlidingWindowLimiter:
    def __init__(self, limit: int, window_seconds: float = 60.0, clock=time.monotonic,
                 max_keys: int = 10_000):
        self.limit = limit
        self.window = window_seconds
        self.clock = clock
        self.max_keys = max_keys
        self._hits: OrderedDict[str, deque[float]] = OrderedDict()
        self._lock = threading.Lock()

    def check(self, key: str) -> float | None:
        """Record a hit; return None if allowed, else seconds until a slot frees."""
        now = self.clock()
        with self._lock:
            hits = self._hits.get(key)
            if hits is None:
                hits = deque()
                self._hits[key] = hits
                while len(self._hits) > self.max_keys:
                    self._hits.popitem(last=False)  # evict least recently seen
            else:
                self._hits.move_to_end(key)
            while hits and now - hits[0] >= self.window:
                hits.popleft()
            if len(hits) >= self.limit:
                return max(0.0, self.window - (now - hits[0]))
            hits.append(now)
            return None

    def tracked_keys(self) -> int:
        return len(self._hits)


def _networks(entries) -> list:
    nets = []
    for entry in entries:
        try:
            nets.append(ipaddress.ip_network(entry.strip(), strict=False))
        except ValueError:
            continue
    return nets


def _is_trusted(address: str, nets) -> bool:
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return False
    return any(ip in net for net in nets)


def client_key(request: Request, trusted_proxies=None) -> str:
    peer = request.client.host if request.client else "unknown"
    nets = _networks(settings.TRUSTED_PROXIES if trusted_proxies is None else trusted_proxies)
    if not nets or not _is_trusted(peer, nets):
        return peer
    forwarded = [h.strip() for h in request.headers.get("x-forwarded-for", "").split(",") if h.strip()]
    for hop in reversed(forwarded):
        if not _is_trusted(hop, nets):
            try:
                return str(ipaddress.ip_address(hop))
            except ValueError:
                return peer  # malformed header: fall back to the proxy address
    return peer


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
