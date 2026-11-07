"""
Lightweight in-memory sliding-window rate limiter (no extra dependency).

Scope / limits (documented honestly):
- State is per process. Render Free runs a single process, so this works;
  with multiple workers/instances move the counters to Redis/Firestore.
- Client IP is the LAST X-Forwarded-For entry (the one appended by our own
  reverse proxy), falling back to the socket peer.
"""
from __future__ import annotations

import time
from collections import defaultdict, deque

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # keep module importable (and unit-testable) without starlette
    from starlette.requests import Request

# (path prefix, method or "*", max requests, window seconds) — first match wins.
RULES: list[tuple[str, str, int, int]] = [
    ("/api/v1/admin/login", "POST", 5, 300),
    ("/api/v1/auth/", "POST", 20, 60),
    ("/api/v1/webhooks/", "*", 600, 60),   # GET (Monetag) + POST (Binance/legacy); secret is long, brute force is infeasible
    ("/api/v1/orders", "POST", 10, 60),
    ("/api/v1/ads/", "POST", 30, 60),
    ("/api/v1/coupons/", "POST", 20, 60),
    ("/api/v1/support/ticket", "POST", 5, 300),
    ("/api/v1/admin/", "*", 60, 60),
    ("/api/v1/", "*", 120, 60),
]


class SlidingWindowLimiter:
    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._last_sweep = 0.0

    def check(self, key: str, limit: int, window: int, now: float | None = None) -> tuple[bool, int]:
        """Returns (allowed, retry_after_seconds)."""
        now = time.monotonic() if now is None else now
        q = self._hits[key]
        while q and q[0] <= now - window:
            q.popleft()
        if len(q) >= limit:
            return False, max(1, int(q[0] + window - now) + 1)
        q.append(now)
        self._sweep(now, window)
        return True, 0

    def _sweep(self, now: float, window: int) -> None:
        if now - self._last_sweep < 60:
            return
        self._last_sweep = now
        for k in [k for k, q in self._hits.items() if not q or q[-1] <= now - max(window, 300)]:
            self._hits.pop(k, None)


def match_rule(path: str, method: str) -> tuple[int, int, str] | None:
    for prefix, m, limit, window in RULES:
        if path.startswith(prefix) and m in ("*", method):
            return limit, window, prefix
    return None


def client_ip(request: Request) -> str:
    xff = request.headers.get("x-forwarded-for", "")
    if xff:
        return xff.split(",")[-1].strip()
    return request.client.host if request.client else "unknown"


_limiter = SlidingWindowLimiter()


async def rate_limit_middleware(request: "Request", call_next):
    from starlette.responses import JSONResponse
    from app.core.config import settings

    if settings.RATE_LIMIT_ENABLED and request.method != "OPTIONS":
        rule = match_rule(request.url.path, request.method)
        if rule:
            limit, window, prefix = rule
            ok, retry = _limiter.check(f"{client_ip(request)}|{prefix}|{request.method}", limit, window)
            if not ok:
                return JSONResponse(
                    status_code=429,
                    content={"detail": "Too many requests. Please slow down."},
                    headers={"Retry-After": str(retry)},
                )
    return await call_next(request)
